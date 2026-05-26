from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# Ensure `core` package is importable when running:
#   imported by scripts/case_library_builder.py
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.base_context import event_anchor_by_key, section_anchor_by_key
from core.loader import load_config
from core.types import AppConfig, BaseContext, EventAnchor, ScenarioConfig, SectionAnchor, TranslatedData, ValidatedInput

def _require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml (required by generator).") from exc
    return yaml

DAY_START = 6 * 3600
DAY_END = 23 * 3600 + 59 * 60 + 59

DELAY_LEVELS = [
    ("L1", 4200, 7200, 25),
    ("L2", 1200, 4199, 25),
    ("L3", 360, 1199, 25),
    ("L4", 60, 359, 25),
]

SPEED_LEVELS = [
    ("L1_40kmh", 40, 40, 20),
    ("L2_80kmh", 80, 80, 20),
    ("L3_160kmh", 160, 160, 20),
    ("L4_200kmh", 200, 200, 20),
    ("L5_250kmh", 250, 250, 20),
]

INTERRUPTION_SPAN_WEIGHTS = [(1, 34), (2, 33), (3, 33)]
COMBO_TYPES = [
    "delay_speedlimit",
    "speedlimit_interruption",
    "delay_interruption",
    "delay_speedlimit_interruption",
]

DEFAULT_BASE_CONFIG_CANDIDATES: List[Path] = []


@dataclass(frozen=True)
class BaseData:
    app_config: Optional[AppConfig]
    validated: ValidatedInput
    translated: TranslatedData
    event_candidates: List[Tuple[str, str, str, int, str]]
    section_candidates: List[Tuple[str, str]]
    event_anchor_by_key: Dict[Tuple[str, str, str], EventAnchor]
    section_anchor_by_key: Dict[Tuple[str, str], SectionAnchor]
    station_order: List[str]
    station_neighbors: Dict[str, set[str]]
    section_train_count: Dict[Tuple[str, str], int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate case library for converter validation.")
    parser.add_argument(
        "--base-config",
        default="",
        help="Base config path. Standalone generation requires an explicit case config.",
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--seed", type=int, default=20260320)
    parser.add_argument("--delay-count", type=int, default=10)
    parser.add_argument("--speed-count", type=int, default=10)
    parser.add_argument("--interruption-count", type=int, default=10)
    parser.add_argument("--combo-per-type", type=int, default=10)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def resolve_base_config(arg_value: str) -> Path:
    raw = (arg_value or "").strip()
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        if candidate.exists() and candidate.is_file():
            return candidate
        raise FileNotFoundError(f"Base config not found: {candidate}")

    for rel in DEFAULT_BASE_CONFIG_CANDIDATES:
        candidate = REPO_ROOT / rel
        if candidate.exists() and candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "No base config found. Please pass --base-config <path>."
    )


def to_hms(seconds: int) -> str:
    seconds = max(0, min(24 * 3600 - 1, int(seconds)))
    hour = seconds // 3600
    minute = (seconds % 3600) // 60
    second = seconds % 60
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def proportional_counts(total: int, weights: Sequence[int]) -> List[int]:
    if total < 0:
        raise ValueError("total must be >= 0.")
    if not weights:
        return []
    if any(weight < 0 for weight in weights):
        raise ValueError("weights must be >= 0.")
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise ValueError("weights must contain at least one positive value.")
    if total == 0:
        return [0] * len(weights)

    scaled = [total * weight / weight_sum for weight in weights]
    floors = [int(value) for value in scaled]
    remainder = total - sum(floors)
    order = sorted(
        range(len(weights)),
        key=lambda idx: (scaled[idx] - floors[idx], weights[idx], -idx),
        reverse=True,
    )
    for idx in order[:remainder]:
        floors[idx] += 1
    return floors


def validate_case_counts(
    delay_count: int,
    speed_count: int,
    interruption_count: int,
    combo_per_type: int,
) -> None:
    fields = {
        "delay-count": delay_count,
        "speed-count": speed_count,
        "interruption-count": interruption_count,
        "combo-per-type": combo_per_type,
    }
    for name, value in fields.items():
        if value < 0:
            raise ValueError(f"{name} must be >= 0.")

    total = delay_count + speed_count + interruption_count + combo_per_type * len(COMBO_TYPES)
    if total <= 0:
        raise ValueError("At least one case count must be greater than 0.")


def weighted_level_sequence(
    rng: random.Random,
    level_specs: Sequence[Tuple[str, int, int, int]],
    count: int,
) -> List[Tuple[str, int, int]]:
    quotas = proportional_counts(count, [weight for _, _, _, weight in level_specs])
    seq: List[Tuple[str, int, int]] = []
    for (level, low, high, _weight), quota in zip(level_specs, quotas):
        seq.extend([(level, low, high)] * quota)
    rng.shuffle(seq)
    return seq


def random_window(rng: random.Random, min_len: int = 900, max_len: int = 3600) -> Tuple[int, int]:
    duration = rng.randint(min_len, max_len)
    start = rng.randint(DAY_START, DAY_END - duration)
    return start, start + duration


def window_covering_point(rng: random.Random, point: int, min_len: int = 900, max_len: int = 3600) -> Tuple[int, int]:
    duration = rng.randint(min_len, max_len)
    earliest_start = max(DAY_START, point - duration + 60)
    latest_start = min(point, DAY_END - duration)
    if earliest_start > latest_start:
        return random_window(rng, min_len=min_len, max_len=max_len)
    start = rng.randint(earliest_start, latest_start)
    return start, start + duration


def window_excluding_point(rng: random.Random, point: int, min_len: int = 900, max_len: int = 3600) -> Tuple[int, int]:
    duration = rng.randint(min_len, max_len)
    options: List[Tuple[int, int]] = []
    if DAY_START + duration < point - 60:
        end = rng.randint(DAY_START + duration, point - 60)
        options.append((end - duration, end))
    if point + 60 < DAY_END - duration:
        start = rng.randint(point + 60, DAY_END - duration)
        options.append((start, start + duration))
    if not options:
        return random_window(rng, min_len=min_len, max_len=max_len)
    return rng.choice(options)


def window_related_to_window(rng: random.Random, base_window: Tuple[int, int], overlap: bool) -> Tuple[int, int]:
    duration = rng.randint(900, 3600)
    b_start, b_end = base_window
    if overlap:
        earliest_start = max(DAY_START, b_start - duration + 60)
        latest_start = min(DAY_END - duration, b_end - 60)
        if earliest_start <= latest_start:
            start = rng.randint(earliest_start, latest_start)
            return start, start + duration
        return random_window(rng)

    candidates: List[Tuple[int, int]] = []
    if DAY_START + duration < b_start - 60:
        end = rng.randint(DAY_START + duration, b_start - 60)
        candidates.append((end - duration, end))
    if b_end + 60 < DAY_END - duration:
        start = rng.randint(b_end + 60, DAY_END - duration)
        candidates.append((start, start + duration))
    if not candidates:
        return random_window(rng)
    return rng.choice(candidates)


def build_station_neighbors(station_order: Sequence[str]) -> Dict[str, set[str]]:
    neighbors: Dict[str, set[str]] = {station: set() for station in station_order}
    for idx, station in enumerate(station_order):
        if idx > 0:
            neighbors[station].add(station_order[idx - 1])
        if idx + 1 < len(station_order):
            neighbors[station].add(station_order[idx + 1])
    return neighbors


def sections_adjacent(s1: Tuple[str, str], s2: Tuple[str, str]) -> bool:
    return bool(set(s1) & set(s2))

def pick_section_by_relation(
    rng: random.Random,
    sections: Sequence[Tuple[str, str]],
    reference: Tuple[str, str],
    relation: str,
) -> Tuple[str, str]:
    if relation == "same":
        return reference
    if relation == "adjacent":
        candidates = [s for s in sections if s != reference and sections_adjacent(s, reference)]
    else:
        candidates = [s for s in sections if s != reference and not sections_adjacent(s, reference)]
    if not candidates:
        candidates = [s for s in sections if s != reference]
    if not candidates:
        return reference
    return rng.choice(candidates)


def pick_delay_event_by_relation(
    rng: random.Random,
    base: BaseData,
    section: Tuple[str, str],
    relation: str,
) -> Tuple[str, str, str, int, str]:
    s1, s2 = section
    if relation == "same":
        station_pool = {s1, s2}
    elif relation == "adjacent":
        station_pool = (base.station_neighbors.get(s1, set()) | base.station_neighbors.get(s2, set())) - {s1, s2}
    else:
        near = {s1, s2} | base.station_neighbors.get(s1, set()) | base.station_neighbors.get(s2, set())
        station_pool = set(base.station_order) - near

    candidates = [item for item in base.event_candidates if item[1] in station_pool]
    if not candidates:
        candidates = base.event_candidates
    return rng.choice(candidates)


def pick_contiguous_sections(rng: random.Random, section_candidates: List[Tuple[str, str]], span: int) -> List[Tuple[str, str]]:
    span = max(1, min(span, len(section_candidates)))
    # Build adjacency map to find contiguous chains in the actual train travel direction.
    next_map: Dict[str, str] = {s: e for s, e in section_candidates}
    valid_chains: List[List[Tuple[str, str]]] = []
    for s, e in section_candidates:
        chain: List[Tuple[str, str]] = [(s, e)]
        cur = e
        for _ in range(span - 1):
            if cur not in next_map:
                break
            nxt = next_map[cur]
            chain.append((cur, nxt))
            cur = nxt
        if len(chain) == span:
            valid_chains.append(chain)
    if not valid_chains:
        return list(rng.sample(section_candidates, min(span, len(section_candidates))))
    return list(rng.choice(valid_chains))


def combo_relation_plan(rng: random.Random, count: int) -> List[Tuple[str, str]]:
    time_counts = proportional_counts(count, [1, 1])
    time_rel = ["overlap"] * time_counts[0] + ["non_overlap"] * time_counts[1]
    space_counts = proportional_counts(count, [1, 2, 1])
    space_rel = ["same"] * space_counts[0] + ["adjacent"] * space_counts[1] + ["distant"] * space_counts[2]
    rng.shuffle(time_rel)
    rng.shuffle(space_rel)
    return list(zip(time_rel, space_rel))


def load_base_data(base_config_path: Path) -> BaseData:
    app_config = load_config(base_config_path)
    neutral = replace(app_config, scenarios=ScenarioConfig(delays=[], speed_limits=[]))
    return load_base_data_from_context(neutral.base_context, app_config=neutral)


def load_base_data_from_context(context: BaseContext, app_config: Optional[AppConfig] = None) -> BaseData:
    validated = context.validated
    translated = context.translated
    event_anchor_map = event_anchor_by_key(context)
    section_anchor_map = section_anchor_by_key(context)

    event_candidates = [
        (tid, station, etype, translated.event_time[(tid, station, etype)], event_anchor_map[(tid, station, etype)].anchor_id)
        for (tid, station, etype) in translated.event_keys
    ]
    section_candidates = sorted(set(translated.section_min_runtime.keys()))
    station_order = context.station_order
    station_neighbors = build_station_neighbors(station_order)

    section_train_count: Dict[Tuple[str, str], int] = defaultdict(int)
    for train_id in translated.train_ids:
        for section in translated.train_sections[train_id]:
            section_train_count[section] += 1

    return BaseData(
        app_config=app_config,
        validated=validated,
        translated=translated,
        event_candidates=event_candidates,
        section_candidates=section_candidates,
        event_anchor_by_key=event_anchor_map,
        section_anchor_by_key=section_anchor_map,
        station_order=station_order,
        station_neighbors=station_neighbors,
        section_train_count=dict(section_train_count),
    )


def base_config_payload(case_name: str, output_dir: str, base: BaseData) -> Dict[str, object]:
    if base.app_config is None:
        return {
            "project": {
                "name": case_name,
                "output_dir": output_dir,
                "base_context_path": "",
            },
            "build": {
                "scenarios": {
                    "delays": [],
                    "speed_limits": [],
                }
            },
        }
    cfg = base.app_config
    return {
        "project": {
            "name": case_name,
            "output_dir": output_dir,
            "base_context_path": str(cfg.project.base_context_path).replace("\\", "/"),
        },
        "build": {
            "scenarios": {
                "delays": [],
                "speed_limits": [],
            }
        },
        "solve": {
            "lp_path": "",
            "objective_delay_weight": cfg.solver.objective_delay_weight,
            "objective_mode": cfg.solver.objective_mode,
            "cancellation_enabled": cfg.solver.cancellation_enabled,
            "cancellation_penalty_weight": cfg.solver.cancellation_penalty_weight,
            "arr_arr_headway_seconds": cfg.solver.arr_arr_headway_seconds,
            "dep_dep_headway_seconds": cfg.solver.dep_dep_headway_seconds,
            "dwell_seconds_at_stops": cfg.solver.dwell_seconds_at_stops,
            "big_m": cfg.solver.big_m,
            "tolerance_delay_seconds": cfg.solver.tolerance_delay_seconds,
        },
        "export-timetable": {
            "sol_path": "",
        },
        "analyze": {
            "enable_metrics": cfg.analyze.enable_metrics,
            "enable_plot": cfg.analyze.enable_plot,
            "plot_grid": cfg.analyze.plot_grid,
            "plot_title": cfg.analyze.plot_title,
            "adj_timetable_path": "",
            "adj_timetable_sheet_name": cfg.analyze.adjusted_timetable_sheet_name,
        },
    }


def case_output_dir(case_id: str) -> str:
    return f"projects/demo/datasets/case_library/cases/{case_id}"


def write_case(case_dir: Path, config_payload: Dict[str, object], meta_payload: Dict[str, object]) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    yaml = _require_yaml()
    with (case_dir / "config.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(config_payload, f, allow_unicode=True, sort_keys=False)
    with (case_dir / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta_payload, f, ensure_ascii=False, indent=2)

def generate_delay_cases(rng: random.Random, base: BaseData, output_root: Path, case_index: int, count: int) -> int:
    seq = weighted_level_sequence(rng, DELAY_LEVELS, count)

    for level, low, high in seq:
        train_id, station, event_type, event_time, event_anchor_id = rng.choice(base.event_candidates)
        delay_seconds = rng.randint(low, high)
        case_id = f"case{case_index:04d}_delay_{level.lower()}"
        cfg = base_config_payload(case_id, case_output_dir(case_id), base)
        cfg["build"]["scenarios"]["delays"] = [
            {
                "event_anchor_id": event_anchor_id,
                "seconds": delay_seconds,
            }
        ]
        meta = {
            "case_id": case_id,
            "scenario_type": "delay",
            "events": [
                {
                    "type": "delay",
                    "start_time": to_hms(event_time),
                    "end_time": to_hms(event_time),
                    "location": {"station": station},
                    "intensity": {"level": level, "seconds": delay_seconds},
                    "affected_trains_count": 1,
                }
            ],
            "time_relation": None,
            "space_relation": None,
            "seed": rng.randint(0, 2**31 - 1),
        }
        write_case(output_root / case_id, cfg, meta)
        case_index += 1
    return case_index


def generate_speed_cases(rng: random.Random, base: BaseData, output_root: Path, case_index: int, count: int) -> int:
    seq = weighted_level_sequence(rng, SPEED_LEVELS, count)

    for level, low, high in seq:
        section = rng.choice(base.section_candidates)
        window = random_window(rng)
        limit_speed = rng.randint(low, high)
        case_id = f"case{case_index:04d}_speedlimit_{level.lower()}"
        cfg = base_config_payload(case_id, case_output_dir(case_id), base)
        cfg["build"]["scenarios"]["speed_limits"] = [
            {
                "section_anchor_id": base.section_anchor_by_key[section].anchor_id,
                "start_time": to_hms(window[0]),
                "duration": window[1] - window[0],
                "limit_speed": limit_speed,
            }
        ]
        meta = {
            "case_id": case_id,
            "scenario_type": "speedlimit",
            "events": [
                {
                    "type": "speed_limit",
                    "start_time": to_hms(window[0]),
                    "end_time": to_hms(window[1]),
                    "location": {"segment": [section[0], section[1]]},
                    "intensity": {"level": level, "limit_speed": limit_speed},
                    "affected_trains_count": base.section_train_count.get(section, 0),
                }
            ],
            "time_relation": None,
            "space_relation": None,
            "seed": rng.randint(0, 2**31 - 1),
        }
        write_case(output_root / case_id, cfg, meta)
        case_index += 1
    return case_index


def generate_interruption_cases(rng: random.Random, base: BaseData, output_root: Path, case_index: int, count: int) -> int:
    seq: List[int] = []
    quotas = proportional_counts(count, [weight for _span, weight in INTERRUPTION_SPAN_WEIGHTS])
    for (span, _weight), quota in zip(INTERRUPTION_SPAN_WEIGHTS, quotas):
        seq.extend([span] * quota)
    rng.shuffle(seq)

    for span in seq:
        sections = pick_contiguous_sections(rng, base.section_candidates, span=span)
        window = random_window(rng, min_len=1200, max_len=4200)
        case_id = f"case{case_index:04d}_interruption_s{span}"
        cfg = base_config_payload(case_id, case_output_dir(case_id), base)
        cfg["build"]["scenarios"]["speed_limits"] = [
            {
                "section_anchor_id": base.section_anchor_by_key[(s1, s2)].anchor_id,
                "start_time": to_hms(window[0]),
                "duration": window[1] - window[0],
                "limit_speed": 0,
            }
            for s1, s2 in sections
        ]
        events = [
            {
                "type": "interruption",
                "start_time": to_hms(window[0]),
                "end_time": to_hms(window[1]),
                "location": {"segment": [s1, s2]},
                "intensity": {"span_sections": span},
                "affected_trains_count": base.section_train_count.get((s1, s2), 0),
            }
            for s1, s2 in sections
        ]
        meta = {
            "case_id": case_id,
            "scenario_type": "interruption",
            "events": events,
            "time_relation": None,
            "space_relation": None,
            "seed": rng.randint(0, 2**31 - 1),
        }
        write_case(output_root / case_id, cfg, meta)
        case_index += 1
    return case_index

def combo_case_payload(
    rng: random.Random,
    base: BaseData,
    case_id: str,
    combo_type: str,
    time_relation: str,
    space_relation: str,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    cfg = base_config_payload(case_id, case_output_dir(case_id), base)
    events: List[Dict[str, object]] = []

    if combo_type == "delay_speedlimit":
        section = rng.choice(base.section_candidates)
        delay_event = pick_delay_event_by_relation(rng, base, section, relation=space_relation)
        delay_seconds = rng.randint(120, 3600)
        speed_window = window_covering_point(rng, delay_event[3]) if time_relation == "overlap" else window_excluding_point(rng, delay_event[3])
        limit_speed = rng.choice([40, 80, 160, 200, 250])

        cfg["build"]["scenarios"]["delays"] = [{"event_anchor_id": delay_event[4], "seconds": delay_seconds}]
        cfg["build"]["scenarios"]["speed_limits"] = [{"section_anchor_id": base.section_anchor_by_key[section].anchor_id, "start_time": to_hms(speed_window[0]), "duration": speed_window[1] - speed_window[0], "limit_speed": limit_speed}]

        events.append({"type": "delay", "start_time": to_hms(delay_event[3]), "end_time": to_hms(delay_event[3]), "location": {"station": delay_event[1]}, "intensity": {"seconds": delay_seconds}, "affected_trains_count": 1})
        events.append({"type": "speed_limit", "start_time": to_hms(speed_window[0]), "end_time": to_hms(speed_window[1]), "location": {"segment": [section[0], section[1]]}, "intensity": {"limit_speed": limit_speed}, "affected_trains_count": base.section_train_count.get(section, 0)})

    elif combo_type == "speedlimit_interruption":
        speed_section = rng.choice(base.section_candidates)
        interruption_section = pick_section_by_relation(rng, base.section_candidates, speed_section, space_relation)
        speed_window = random_window(rng)
        interruption_window = window_related_to_window(rng, speed_window, overlap=(time_relation == "overlap"))
        limit_speed = rng.choice([40, 80, 160, 200, 250])

        cfg["build"]["scenarios"]["speed_limits"] = [
            {"section_anchor_id": base.section_anchor_by_key[speed_section].anchor_id, "start_time": to_hms(speed_window[0]), "duration": speed_window[1] - speed_window[0], "limit_speed": limit_speed},
            {"section_anchor_id": base.section_anchor_by_key[interruption_section].anchor_id, "start_time": to_hms(interruption_window[0]), "duration": interruption_window[1] - interruption_window[0], "limit_speed": 0},
        ]

        events.append({"type": "speed_limit", "start_time": to_hms(speed_window[0]), "end_time": to_hms(speed_window[1]), "location": {"segment": [speed_section[0], speed_section[1]]}, "intensity": {"limit_speed": limit_speed}, "affected_trains_count": base.section_train_count.get(speed_section, 0)})
        events.append({"type": "interruption", "start_time": to_hms(interruption_window[0]), "end_time": to_hms(interruption_window[1]), "location": {"segment": [interruption_section[0], interruption_section[1]]}, "intensity": {"span_sections": 1}, "affected_trains_count": base.section_train_count.get(interruption_section, 0)})

    elif combo_type == "delay_interruption":
        interruption_section = rng.choice(base.section_candidates)
        delay_event = pick_delay_event_by_relation(rng, base, interruption_section, relation=space_relation)
        delay_seconds = rng.randint(120, 3600)
        interruption_window = window_covering_point(rng, delay_event[3]) if time_relation == "overlap" else window_excluding_point(rng, delay_event[3])

        cfg["build"]["scenarios"]["delays"] = [{"event_anchor_id": delay_event[4], "seconds": delay_seconds}]
        cfg["build"]["scenarios"]["speed_limits"] = [{"section_anchor_id": base.section_anchor_by_key[interruption_section].anchor_id, "start_time": to_hms(interruption_window[0]), "duration": interruption_window[1] - interruption_window[0], "limit_speed": 0}]

        events.append({"type": "delay", "start_time": to_hms(delay_event[3]), "end_time": to_hms(delay_event[3]), "location": {"station": delay_event[1]}, "intensity": {"seconds": delay_seconds}, "affected_trains_count": 1})
        events.append({"type": "interruption", "start_time": to_hms(interruption_window[0]), "end_time": to_hms(interruption_window[1]), "location": {"segment": [interruption_section[0], interruption_section[1]]}, "intensity": {"span_sections": 1}, "affected_trains_count": base.section_train_count.get(interruption_section, 0)})

    elif combo_type == "delay_speedlimit_interruption":
        speed_section = rng.choice(base.section_candidates)
        interruption_section = pick_section_by_relation(rng, base.section_candidates, speed_section, relation=space_relation)
        delay_event = pick_delay_event_by_relation(rng, base, speed_section, relation=space_relation)
        delay_seconds = rng.randint(120, 3600)
        limit_speed = rng.choice([40, 80, 160, 200, 250])

        speed_window = window_covering_point(rng, delay_event[3])
        interruption_window = window_related_to_window(rng, speed_window, overlap=(time_relation == "overlap"))

        cfg["build"]["scenarios"]["delays"] = [{"event_anchor_id": delay_event[4], "seconds": delay_seconds}]
        cfg["build"]["scenarios"]["speed_limits"] = [
            {"section_anchor_id": base.section_anchor_by_key[speed_section].anchor_id, "start_time": to_hms(speed_window[0]), "duration": speed_window[1] - speed_window[0], "limit_speed": limit_speed},
            {"section_anchor_id": base.section_anchor_by_key[interruption_section].anchor_id, "start_time": to_hms(interruption_window[0]), "duration": interruption_window[1] - interruption_window[0], "limit_speed": 0},
        ]

        events.append({"type": "delay", "start_time": to_hms(delay_event[3]), "end_time": to_hms(delay_event[3]), "location": {"station": delay_event[1]}, "intensity": {"seconds": delay_seconds}, "affected_trains_count": 1})
        events.append({"type": "speed_limit", "start_time": to_hms(speed_window[0]), "end_time": to_hms(speed_window[1]), "location": {"segment": [speed_section[0], speed_section[1]]}, "intensity": {"limit_speed": limit_speed}, "affected_trains_count": base.section_train_count.get(speed_section, 0)})
        events.append({"type": "interruption", "start_time": to_hms(interruption_window[0]), "end_time": to_hms(interruption_window[1]), "location": {"segment": [interruption_section[0], interruption_section[1]]}, "intensity": {"span_sections": 1}, "affected_trains_count": base.section_train_count.get(interruption_section, 0)})

    else:
        raise ValueError(f"Unsupported combo type: {combo_type}")

    meta = {
        "case_id": case_id,
        "scenario_type": "combo",
        "combo_type": combo_type,
        "events": events,
        "time_relation": time_relation,
        "space_relation": space_relation,
        "seed": rng.randint(0, 2**31 - 1),
    }
    return cfg, meta


def generate_combo_cases(rng: random.Random, base: BaseData, output_root: Path, case_index: int, per_type: int) -> int:
    relations = combo_relation_plan(rng, per_type)
    for combo_type in COMBO_TYPES:
        for time_relation, space_relation in relations:
            case_id = f"case{case_index:04d}_combo_{combo_type}"
            cfg, meta = combo_case_payload(rng, base, case_id, combo_type, time_relation, space_relation)
            write_case(output_root / case_id, cfg, meta)
            case_index += 1
    return case_index

def write_manifest(
    output_root: Path,
    base_config: Path,
    seed: int,
    delay_count: int,
    speed_count: int,
    interruption_count: int,
    combo_per_type: int,
) -> None:
    payload = {
        "base_config": str(base_config).replace("\\", "/"),
        "seed": seed,
        "distribution": {
            "delay": delay_count,
            "speedlimit": speed_count,
            "interruption": interruption_count,
            "combo": {
                "delay_speedlimit": combo_per_type,
                "speedlimit_interruption": combo_per_type,
                "delay_interruption": combo_per_type,
                "delay_speedlimit_interruption": combo_per_type,
                "total": combo_per_type * len(COMBO_TYPES),
            },
            "total": delay_count + speed_count + interruption_count + combo_per_type * len(COMBO_TYPES),
        },
    }
    with (output_root / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    args = parse_args()
    validate_case_counts(
        delay_count=args.delay_count,
        speed_count=args.speed_count,
        interruption_count=args.interruption_count,
        combo_per_type=args.combo_per_type,
    )

    base_config = resolve_base_config(args.base_config)

    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    if args.clean and output_root.exists():
        for case_dir in output_root.glob("case*"):
            if case_dir.is_dir():
                shutil.rmtree(case_dir)
        manifest_path = output_root / "manifest.json"
        if manifest_path.exists():
            manifest_path.unlink()

    rng = random.Random(args.seed)
    base = load_base_data(base_config)

    case_index = 1
    case_index = generate_delay_cases(rng, base, output_root, case_index, args.delay_count)
    case_index = generate_speed_cases(rng, base, output_root, case_index, args.speed_count)
    case_index = generate_interruption_cases(rng, base, output_root, case_index, args.interruption_count)
    case_index = generate_combo_cases(rng, base, output_root, case_index, args.combo_per_type)

    write_manifest(
        output_root=output_root,
        base_config=base_config,
        seed=args.seed,
        delay_count=args.delay_count,
        speed_count=args.speed_count,
        interruption_count=args.interruption_count,
        combo_per_type=args.combo_per_type,
    )

    print(f"Generated {case_index - 1} cases under {output_root}")


if __name__ == "__main__":
    main()

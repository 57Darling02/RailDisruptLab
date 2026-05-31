from __future__ import annotations

import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from core.base_context import event_anchor_by_key, load_base_context, section_anchor_by_key
from core.file_ops import copy_or_link_file
from core.project_layout import ProjectLayout, require_id, reset_dir, sanitize_id
from core.scenario_config import ScenarioDocument
from core.types import BaseContext, SectionAnchor
from backend.scenario_cases import (
    delete_scenario_case,
    scenario_case_layout,
    update_scenario_disturbances,
    write_case_context,
    write_scenario_document as write_case_scenario_document,
)


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


@dataclass(frozen=True)
class ScenarioGenerationBase:
    event_candidates: List[Tuple[str, str, str, int, str]]
    section_candidates: List[Tuple[str, str]]
    section_anchor_by_key: Dict[Tuple[str, str], SectionAnchor]
    station_order: List[str]
    station_neighbors: Dict[str, set[str]]


def read_scenario_options(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    case = scenario_case_layout(layout, scenario_set_id, scenario_id)
    if not case.context_json.is_file():
        raise FileNotFoundError(f"Scenario is not activated: {case.context_json}")
    context = load_base_context(case.context_json)
    return {
        "project_id": layout.name,
        "scenario_set_id": require_id(scenario_set_id, "scenario_set_id"),
        "scenario_id": require_id(scenario_id, "scenario_id"),
        "event_anchors": [
            {
                "anchor_id": anchor.anchor_id,
                "train_id": anchor.train_id,
                "station": anchor.station,
                "event_type": anchor.event_type,
                "planned_time": anchor.planned_time,
                "planned_time_text": seconds_to_hms(anchor.planned_time),
            }
            for anchor in sorted(
                context.event_anchors.values(),
                key=lambda item: (item.train_index, item.planned_time, item.station_order, item.event_type),
            )
        ],
        "section_anchors": [
            {
                "anchor_id": anchor.anchor_id,
                "start_station": anchor.start_station,
                "end_station": anchor.end_station,
                "direction": anchor.direction,
                "section_order": anchor.section_order,
                "mileage": anchor.mileage,
                "min_runtime": anchor.min_runtime,
            }
            for anchor in sorted(
                context.section_anchors.values(),
                key=lambda item: (item.direction, item.section_order, item.start_station, item.end_station),
            )
        ],
    }


def create_scenario_set(layout: ProjectLayout, scenario_set_id: str, *, exist_ok: bool = False) -> None:
    require_project(layout)
    root = layout.scenario_set(scenario_set_id).root
    if root.exists():
        if not root.is_dir():
            raise NotADirectoryError(f"Scenario set path is not a directory: {root}")
        if not exist_ok:
            raise FileExistsError(f"Scenario set already exists: {root}")
    else:
        root.mkdir(parents=True, exist_ok=False)
    print(f"Scenario set ready: {root}")


def add_scenario(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    delays: Sequence[Mapping[str, object]] | None = None,
    speed_limits: Sequence[Mapping[str, object]] | None = None,
    overwrite: bool = False,
) -> None:
    update_scenario_disturbances(
        layout,
        scenario_set_id,
        scenario_id,
        delays=list(delays or []),
        speed_limits=list(speed_limits or []),
    )


def delete_scenario(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> None:
    delete_scenario_case(layout, scenario_set_id, scenario_id)
    print(f"Scenario deleted: {scenario_set_id}/{scenario_id}")


def normal_generate(
    layout: ProjectLayout,
    *,
    scenario_set_id: str,
    scenario_id_prefix: str = "sim",
    simulation_count: int = 1,
    source_timetable_path: str = "",
    source_mileage_path: str = "",
    seed: int = 20260320,
    delay_count: int = 10,
    speed_count: int = 10,
    interruption_count: int = 10,
    combo_per_type: int = 10,
    overwrite: bool = False,
) -> None:
    scenario_set_id = sanitize_required_id(scenario_set_id, "scenario_set_id")
    validate_case_counts(
        delay_count=delay_count,
        speed_count=speed_count,
        interruption_count=interruption_count,
        combo_per_type=combo_per_type,
    )
    simulation_count = max(1, int(simulation_count))
    scenario_id_prefix = sanitize_required_id(scenario_id_prefix or "sim", "scenario_id_prefix")
    timetable_path = task_upload_path(layout, source_timetable_path, "source_timetable_path")
    mileage_path = task_upload_path(layout, source_mileage_path, "source_mileage_path")
    if not timetable_path.is_file():
        raise FileNotFoundError(f"Timetable not found in project source: {timetable_path}")
    if not mileage_path.is_file():
        raise FileNotFoundError(f"Mileage table not found in project source: {mileage_path}")

    root = layout.scenario_set(scenario_set_id).root
    root.mkdir(parents=True, exist_ok=True)
    targets = [
        layout.scenario_set(scenario_set_id).scenario(f"{scenario_id_prefix}_{index:04d}")
        for index in range(1, simulation_count + 1)
    ]
    existing = [target.root for target in targets if target.root.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Scenario already exists, enable overwrite to replace: {existing[0]}")

    rng = random.Random(seed)
    tmp_case = layout.scenario_set(scenario_set_id).scenario(f".tmp_{scenario_id_prefix}")
    if tmp_case.root.exists():
        reset_dir(tmp_case.root)
    tmp_case.source_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(timetable_path, tmp_case.timetable_xlsx)
    shutil.copy2(mileage_path, tmp_case.mileage_xlsx)
    write_case_context(tmp_case, scenario_id=tmp_case.root.name)
    context = load_base_context(tmp_case.context_json)
    base = load_generation_base(context)

    try:
        for target in targets:
            if target.root.exists():
                reset_dir(target.root)
            target.source_dir.mkdir(parents=True, exist_ok=False)
            shutil.copy2(timetable_path, target.timetable_xlsx)
            shutil.copy2(mileage_path, target.mileage_xlsx)
            copy_or_link_file(tmp_case.context_json, target.context_json)
            payload = generate_simulated_payload(
                rng,
                base,
                delay_count=delay_count,
                speed_count=speed_count,
                interruption_count=interruption_count,
                combo_per_type=combo_per_type,
            )
            write_case_scenario_document(
                target,
                ScenarioDocument(name=target.root.name, scenarios=payload),
            )
            print(f"Generated simulated scenario: {target.root}")
    finally:
        if tmp_case.root.exists():
            reset_dir(tmp_case.root)
        cleanup_task_uploads(timetable_path, mileage_path, project_root=layout.root)

    print(f"Generated {simulation_count} simulated scenario(s): {root}")


def generate_simulated_payload(
    rng: random.Random,
    base: ScenarioGenerationBase,
    *,
    delay_count: int,
    speed_count: int,
    interruption_count: int,
    combo_per_type: int,
) -> Dict[str, object]:
    delays: List[Dict[str, object]] = []
    speed_limits: List[Dict[str, object]] = []
    for _level, low, high in weighted_level_sequence(rng, DELAY_LEVELS, delay_count):
        _train_id, _station, _event_type, _event_time, event_anchor_id = rng.choice(base.event_candidates)
        delays.append({"event_anchor_id": event_anchor_id, "seconds": rng.randint(low, high)})
    for _level, low, high in weighted_level_sequence(rng, SPEED_LEVELS, speed_count):
        section = rng.choice(base.section_candidates)
        speed_limits.append(speed_payload(base, section, random_window(rng), rng.randint(low, high)))
    for span in interruption_spans(rng, interruption_count):
        window = random_window(rng, min_len=1200, max_len=4200)
        for section in pick_contiguous_sections(rng, base.section_candidates, span=span):
            speed_limits.append(speed_payload(base, section, window, 0))
    for combo_type in COMBO_TYPES:
        for time_relation, space_relation in combo_relation_plan(rng, combo_per_type):
            combo_delays, combo_speed_limits = combo_case_payload(rng, base, combo_type, time_relation, space_relation)
            delays.extend(combo_delays)
            speed_limits.extend(combo_speed_limits)
    return {"delays": delays, "speed_limits": speed_limits}


def interruption_spans(rng: random.Random, count: int) -> List[int]:
    seq: List[int] = []
    quotas = proportional_counts(count, [weight for _span, weight in INTERRUPTION_SPAN_WEIGHTS])
    for (span, _weight), quota in zip(INTERRUPTION_SPAN_WEIGHTS, quotas):
        seq.extend([span] * quota)
    rng.shuffle(seq)
    return seq


def normalize_scenario_payload(layout: ProjectLayout, payload: Mapping[str, object]) -> Dict[str, object]:
    return {
        "delays": list(list_payload(payload.get("delays"))),
        "speed_limits": list(list_payload(payload.get("speed_limits"))),
    }


def load_generation_base(context: BaseContext) -> ScenarioGenerationBase:
    translated = context.translated
    event_anchor_map = event_anchor_by_key(context)
    section_anchor_map = section_anchor_by_key(context)
    event_candidates = [
        (
            train_id,
            station,
            event_type,
            translated.event_time[(train_id, station, event_type)],
            event_anchor_map[(train_id, station, event_type)].anchor_id,
        )
        for (train_id, station, event_type) in translated.event_keys
    ]
    section_candidates = sorted(set(translated.section_min_runtime.keys()))

    return ScenarioGenerationBase(
        event_candidates=event_candidates,
        section_candidates=section_candidates,
        section_anchor_by_key=section_anchor_map,
        station_order=context.station_order,
        station_neighbors=build_station_neighbors(context.station_order),
    )


def combo_case_payload(
    rng: random.Random,
    base: ScenarioGenerationBase,
    combo_type: str,
    time_relation: str,
    space_relation: str,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    delays: List[Dict[str, object]] = []
    speed_limits: List[Dict[str, object]] = []

    if combo_type == "delay_speedlimit":
        section = rng.choice(base.section_candidates)
        delay_event = pick_delay_event_by_relation(rng, base, section, relation=space_relation)
        speed_window = window_covering_point(rng, delay_event[3]) if time_relation == "overlap" else window_excluding_point(rng, delay_event[3])
        delays.append({"event_anchor_id": delay_event[4], "seconds": rng.randint(120, 3600)})
        speed_limits.append(speed_payload(base, section, speed_window, rng.choice([40, 80, 160, 200, 250])))
    elif combo_type == "speedlimit_interruption":
        speed_section = rng.choice(base.section_candidates)
        interruption_section = pick_section_by_relation(rng, base.section_candidates, speed_section, space_relation)
        speed_window = random_window(rng)
        interruption_window = window_related_to_window(rng, speed_window, overlap=(time_relation == "overlap"))
        speed_limits.append(speed_payload(base, speed_section, speed_window, rng.choice([40, 80, 160, 200, 250])))
        speed_limits.append(speed_payload(base, interruption_section, interruption_window, 0))
    elif combo_type == "delay_interruption":
        interruption_section = rng.choice(base.section_candidates)
        delay_event = pick_delay_event_by_relation(rng, base, interruption_section, relation=space_relation)
        interruption_window = window_covering_point(rng, delay_event[3]) if time_relation == "overlap" else window_excluding_point(rng, delay_event[3])
        delays.append({"event_anchor_id": delay_event[4], "seconds": rng.randint(120, 3600)})
        speed_limits.append(speed_payload(base, interruption_section, interruption_window, 0))
    elif combo_type == "delay_speedlimit_interruption":
        speed_section = rng.choice(base.section_candidates)
        interruption_section = pick_section_by_relation(rng, base.section_candidates, speed_section, relation=space_relation)
        delay_event = pick_delay_event_by_relation(rng, base, speed_section, relation=space_relation)
        speed_window = window_covering_point(rng, delay_event[3])
        interruption_window = window_related_to_window(rng, speed_window, overlap=(time_relation == "overlap"))
        delays.append({"event_anchor_id": delay_event[4], "seconds": rng.randint(120, 3600)})
        speed_limits.append(speed_payload(base, speed_section, speed_window, rng.choice([40, 80, 160, 200, 250])))
        speed_limits.append(speed_payload(base, interruption_section, interruption_window, 0))
    else:
        raise ValueError(f"Unsupported combo type: {combo_type}")

    return delays, speed_limits


def speed_payload(
    base: ScenarioGenerationBase,
    section: Tuple[str, str],
    window: Tuple[int, int],
    limit_speed: float,
) -> Dict[str, object]:
    return {
        "section_anchor_id": base.section_anchor_by_key[section].anchor_id,
        "start_time": seconds_to_hms(window[0]),
        "duration": window[1] - window[0],
        "limit_speed": limit_speed,
    }


def validate_case_counts(
    *,
    delay_count: int,
    speed_count: int,
    interruption_count: int,
    combo_per_type: int,
) -> None:
    fields = {
        "delay_count": delay_count,
        "speed_count": speed_count,
        "interruption_count": interruption_count,
        "combo_per_type": combo_per_type,
    }
    for name, value in fields.items():
        if value < 0:
            raise ValueError(f"{name} must be >= 0.")

    total = delay_count + speed_count + interruption_count + combo_per_type * len(COMBO_TYPES)
    if total <= 0:
        raise ValueError("At least one scenario count must be greater than 0.")


def weighted_level_sequence(
    rng: random.Random,
    level_specs: Sequence[Tuple[str, int, int, int]],
    count: int,
) -> List[Tuple[str, int, int]]:
    quotas = proportional_counts(count, [weight for _, _, _, weight in level_specs])
    sequence: List[Tuple[str, int, int]] = []
    for (level, low, high, _weight), quota in zip(level_specs, quotas):
        sequence.extend([(level, low, high)] * quota)
    rng.shuffle(sequence)
    return sequence


def proportional_counts(total: int, weights: Sequence[int]) -> List[int]:
    if total < 0:
        raise ValueError("total must be >= 0.")
    if not weights:
        return []
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
    return rng.choice(options) if options else random_window(rng, min_len=min_len, max_len=max_len)


def window_related_to_window(rng: random.Random, base_window: Tuple[int, int], overlap: bool) -> Tuple[int, int]:
    duration = rng.randint(900, 3600)
    base_start, base_end = base_window
    if overlap:
        earliest_start = max(DAY_START, base_start - duration + 60)
        latest_start = min(DAY_END - duration, base_end - 60)
        if earliest_start <= latest_start:
            start = rng.randint(earliest_start, latest_start)
            return start, start + duration
        return random_window(rng)

    candidates: List[Tuple[int, int]] = []
    if DAY_START + duration < base_start - 60:
        end = rng.randint(DAY_START + duration, base_start - 60)
        candidates.append((end - duration, end))
    if base_end + 60 < DAY_END - duration:
        start = rng.randint(base_end + 60, DAY_END - duration)
        candidates.append((start, start + duration))
    return rng.choice(candidates) if candidates else random_window(rng)


def build_station_neighbors(station_order: Sequence[str]) -> Dict[str, set[str]]:
    neighbors: Dict[str, set[str]] = {station: set() for station in station_order}
    for index, station in enumerate(station_order):
        if index > 0:
            neighbors[station].add(station_order[index - 1])
        if index + 1 < len(station_order):
            neighbors[station].add(station_order[index + 1])
    return neighbors


def sections_adjacent(left: Tuple[str, str], right: Tuple[str, str]) -> bool:
    return bool(set(left) & set(right))


def pick_section_by_relation(
    rng: random.Random,
    sections: Sequence[Tuple[str, str]],
    reference: Tuple[str, str],
    relation: str,
) -> Tuple[str, str]:
    if relation == "same":
        return reference
    if relation == "adjacent":
        candidates = [section for section in sections if section != reference and sections_adjacent(section, reference)]
    else:
        candidates = [section for section in sections if section != reference and not sections_adjacent(section, reference)]
    if not candidates:
        candidates = [section for section in sections if section != reference]
    return rng.choice(candidates) if candidates else reference


def pick_delay_event_by_relation(
    rng: random.Random,
    base: ScenarioGenerationBase,
    section: Tuple[str, str],
    relation: str,
) -> Tuple[str, str, str, int, str]:
    start_station, end_station = section
    if relation == "same":
        station_pool = {start_station, end_station}
    elif relation == "adjacent":
        station_pool = (
            base.station_neighbors.get(start_station, set()) | base.station_neighbors.get(end_station, set())
        ) - {start_station, end_station}
    else:
        near = {
            start_station,
            end_station,
            *base.station_neighbors.get(start_station, set()),
            *base.station_neighbors.get(end_station, set()),
        }
        station_pool = set(base.station_order) - near

    candidates = [item for item in base.event_candidates if item[1] in station_pool]
    return rng.choice(candidates or base.event_candidates)


def pick_contiguous_sections(
    rng: random.Random,
    section_candidates: List[Tuple[str, str]],
    span: int,
) -> List[Tuple[str, str]]:
    span = max(1, min(span, len(section_candidates)))
    next_map: Dict[str, str] = {start: end for start, end in section_candidates}
    chains: List[List[Tuple[str, str]]] = []
    for start, end in section_candidates:
        chain: List[Tuple[str, str]] = [(start, end)]
        current = end
        for _ in range(span - 1):
            if current not in next_map:
                break
            next_station = next_map[current]
            chain.append((current, next_station))
            current = next_station
        if len(chain) == span:
            chains.append(chain)
    if chains:
        return list(rng.choice(chains))
    return list(rng.sample(section_candidates, min(span, len(section_candidates))))


def combo_relation_plan(rng: random.Random, count: int) -> List[Tuple[str, str]]:
    time_counts = proportional_counts(count, [1, 1])
    time_relations = ["overlap"] * time_counts[0] + ["non_overlap"] * time_counts[1]
    space_counts = proportional_counts(count, [1, 2, 1])
    space_relations = ["same"] * space_counts[0] + ["adjacent"] * space_counts[1] + ["distant"] * space_counts[2]
    rng.shuffle(time_relations)
    rng.shuffle(space_relations)
    return list(zip(time_relations, space_relations))


def require_project(layout: ProjectLayout) -> None:
    if not layout.root.is_dir():
        raise FileNotFoundError(f"Project not found: {layout.root}")


def task_upload_path(layout: ProjectLayout, path_text: str, key: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError(f"{key} must be an absolute task upload path.")
    root = (layout.root / ".tmp" / "uploads").resolve()
    resolved = path.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"{key} must be under project .tmp/uploads/: {path}")
    return resolved


def cleanup_task_uploads(*paths: Path, project_root: Path) -> None:
    upload_root = (project_root / ".tmp" / "uploads").resolve()
    parents = {path.resolve().parent for path in paths if upload_root in path.resolve().parents}
    for parent in parents:
        if parent.exists():
            reset_dir(parent)


def list_payload(value: object) -> List[Mapping[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Scenario delays and speed_limits must be arrays.")
    result: List[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("Scenario disturbance entries must be objects.")
        result.append(item)
    return result


def sanitize_required_id(value: object, field_name: str) -> str:
    return require_id(value, field_name)


def seconds_to_hms(seconds: int) -> str:
    total = max(0, min(24 * 3600 - 1, int(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def write_yaml(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(require_yaml().safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml

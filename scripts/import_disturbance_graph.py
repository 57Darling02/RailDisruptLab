from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.base_context import load_base_context
from core.disturbance_graph import disturbance_graph_to_scenario
from core.loader import load_config
from core.types import AppConfig, ScenarioConfig


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a disturbance graph JSON as a RailGraph2Gurobi config.")
    parser.add_argument("--graph", required=True, help="Source disturbance graph JSON.")
    parser.add_argument("--base-config", default="config/demo.yml", help="Config that provides solver/analyze defaults.")
    parser.add_argument("--output-config", required=True, help="Output YAML config.")
    return parser.parse_args()


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _resolve_base_context_path(path_text: str, graph_path: Path) -> Path:
    raw_path = Path(path_text)
    if raw_path.is_absolute():
        return raw_path
    candidates = [
        (REPO_ROOT / raw_path).resolve(),
        (graph_path.parent / raw_path).resolve(),
        (Path.cwd() / raw_path).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _seconds_to_hms(seconds: int) -> str:
    total = max(0, min(24 * 3600 - 1, int(seconds)))
    hour = total // 3600
    minute = (total % 3600) // 60
    second = total % 60
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _clean_number(value: float) -> int | float:
    value = float(value)
    return int(value) if value.is_integer() else value


def _config_payload(
    name: str,
    base_context_path: str,
    defaults: AppConfig,
    scenarios: ScenarioConfig,
) -> Dict[str, object]:
    return {
        "project": {
            "name": name,
            "output_dir": f"outputs/main/datasets/{name}/cases/{name}",
            "base_context_path": base_context_path.replace("\\", "/"),
        },
        "build": {
            "scenarios": {
                "delays": [
                    {
                        "event_anchor_id": item.event_anchor_id,
                        "seconds": int(item.seconds),
                    }
                    for item in scenarios.delays
                ],
                "speed_limits": [
                    {
                        "section_anchor_id": item.section_anchor_id,
                        "start_time": _seconds_to_hms(item.start_time),
                        "duration": int(item.duration),
                        "limit_speed": _clean_number(item.limit_speed),
                    }
                    for item in scenarios.speed_limits
                ],
            }
        },
        "solve": {
            "lp_path": "",
            "objective_delay_weight": defaults.solver.objective_delay_weight,
            "objective_mode": defaults.solver.objective_mode,
            "cancellation_enabled": defaults.solver.cancellation_enabled,
            "cancellation_penalty_weight": defaults.solver.cancellation_penalty_weight,
            "arr_arr_headway_seconds": defaults.solver.arr_arr_headway_seconds,
            "dep_dep_headway_seconds": defaults.solver.dep_dep_headway_seconds,
            "dwell_seconds_at_stops": defaults.solver.dwell_seconds_at_stops,
            "big_m": defaults.solver.big_m,
            "tolerance_delay_seconds": defaults.solver.tolerance_delay_seconds,
        },
        "export-timetable": {
            "sol_path": "",
        },
        "analyze": {
            "enable_metrics": defaults.analyze.enable_metrics,
            "enable_plot": defaults.analyze.enable_plot,
            "plot_grid": defaults.analyze.plot_grid,
            "plot_title": defaults.analyze.plot_title,
            "adj_timetable_path": "",
            "adj_timetable_sheet_name": defaults.analyze.adjusted_timetable_sheet_name,
        },
    }


def main() -> None:
    args = parse_args()
    graph_path = _resolve(args.graph)
    base_config_path = _resolve(args.base_config)
    output_config_path = _resolve(args.output_config)

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    base_context_path = str(graph.get("base_context_path", "")).strip()
    if not base_context_path:
        raise ValueError("Disturbance graph is missing base_context_path.")
    context = load_base_context(_resolve_base_context_path(base_context_path, graph_path))
    scenarios = disturbance_graph_to_scenario(graph, context)

    defaults = load_config(base_config_path)
    payload = _config_payload(output_config_path.stem, base_context_path, defaults, scenarios)

    output_config_path.parent.mkdir(parents=True, exist_ok=True)
    yaml = _require_yaml()
    with output_config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)

    print(f"Config imported from disturbance graph: {output_config_path}")
    print(f"Delays: {len(scenarios.delays)}")
    print(f"Speed limits including interruptions: {len(scenarios.speed_limits)}")


if __name__ == "__main__":
    main()

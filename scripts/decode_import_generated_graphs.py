from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.base_context import load_base_context
from core.disturbance_graph import disturbance_graph_to_scenario
from core.loader import load_config
from core.types import AppConfig, ScenarioConfig
from core.vae_learning_graph import (
    DEFAULT_MAX_SLOTS,
    DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
    GENERATED_GRAPH_TYPE,
    MATH_GENERATED_GRAPH_TYPE,
    typed_generated_graph_to_disturbance_graph,
)


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch decode VAE generated math graphs and import them as RailGraph2Gurobi configs."
    )
    parser.add_argument("--generated-graphs", required=True, help="Generated graph JSON file or directory.")
    parser.add_argument("--glob", default="*.json", help="Glob used when --generated-graphs is a directory.")
    parser.add_argument("--base-config", required=True, help="Config that provides solver/analyze defaults.")
    parser.add_argument("--base-context-path", default="", help="Optional BaseContext path override.")
    parser.add_argument("--output-disturbance-root", default="", help="Defaults to <generation>/disturbance_graphs.")
    parser.add_argument("--output-config-root", default="", help="Defaults to <generation>/configs.")
    parser.add_argument(
        "--project-output-root",
        default="",
        help="Prefix written to generated YAML project.output_dir. Defaults to <generation>/case_outputs.",
    )
    parser.add_argument("--summary-csv", default="", help="Defaults to <generation>/decode_summary.csv.")
    parser.add_argument("--summary-json", default="", help="Defaults to <generation>/decode_summary.json.")
    parser.add_argument("--max-slots", type=int, default=DEFAULT_MAX_SLOTS)
    parser.add_argument("--speed-interruption-threshold", type=float, default=DEFAULT_SPEED_INTERRUPTION_THRESHOLD)
    parser.add_argument("--stop-on-error", action="store_true", help="Stop after the first failed graph.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generated_graphs_root = _resolve(args.generated_graphs)
    generate_run_dir = _infer_generate_run_dir(generated_graphs_root)
    graph_paths = _collect_generated_graphs(generated_graphs_root, args.glob)
    if not graph_paths:
        raise FileNotFoundError(f"No generated graph JSON files found: {args.generated_graphs}")

    base_config_path = _resolve(args.base_config)
    output_disturbance_root = (
        _resolve(args.output_disturbance_root)
        if args.output_disturbance_root
        else generate_run_dir / "disturbance_graphs"
    )
    output_config_root = (
        _resolve(args.output_config_root)
        if args.output_config_root
        else generate_run_dir / "configs"
    )
    project_output_root = (
        _clean_path_text(args.project_output_root)
        if args.project_output_root
        else _config_path_text(generate_run_dir / "case_outputs")
    )
    summary_csv = _resolve(args.summary_csv) if args.summary_csv else generate_run_dir / "decode_summary.csv"
    summary_json = _resolve(args.summary_json) if args.summary_json else generate_run_dir / "decode_summary.json"
    defaults = load_config(base_config_path)
    yaml = _require_yaml()

    records: List[Dict[str, object]] = []
    for index, graph_path in enumerate(graph_paths, start=1):
        record = _process_one_graph(
            index=index,
            graph_path=graph_path,
            base_context_override=args.base_context_path,
            defaults=defaults,
            yaml=yaml,
            output_disturbance_root=output_disturbance_root,
            output_config_root=output_config_root,
            project_output_root=project_output_root,
            max_slots=args.max_slots,
            speed_interruption_threshold=args.speed_interruption_threshold,
        )
        records.append(record)
        _print_record(record, index, len(graph_paths))
        if record["status"] == "failed" and args.stop_on_error:
            break

    _write_csv(summary_csv, records)
    _write_json(
        summary_json,
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "generated_graphs": _to_posix(_resolve(args.generated_graphs)),
            "generate_run_dir": _to_posix(generate_run_dir),
            "glob": args.glob,
            "base_config": _to_posix(base_config_path),
            "output_disturbance_root": _to_posix(output_disturbance_root),
            "output_config_root": _to_posix(output_config_root),
            "project_output_root": project_output_root,
            "total": len(records),
            "status_counts": _status_counts(records),
            "summary_csv": _to_posix(summary_csv),
        },
    )
    print(f"Summary -> {summary_csv}")

    failed = [record for record in records if record["status"] == "failed"]
    if failed:
        raise SystemExit(1)


def _process_one_graph(
    *,
    index: int,
    graph_path: Path,
    base_context_override: str,
    defaults: AppConfig,
    yaml: Any,
    output_disturbance_root: Path,
    output_config_root: Path,
    project_output_root: str,
    max_slots: int,
    speed_interruption_threshold: float,
) -> Dict[str, object]:
    stem = graph_path.stem
    disturbance_path = output_disturbance_root / f"{stem}.json"
    config_path = output_config_root / f"{stem}.yaml"
    project_output_dir = _join_path_text(project_output_root, stem)
    record: Dict[str, object] = {
        "index": index,
        "generated_graph": _to_posix(graph_path),
        "status": "ok",
        "error": "",
        "disturbance_graph": _to_posix(disturbance_path),
        "config_path": _to_posix(config_path),
        "project_output_dir": project_output_dir,
        "disturbance_count": 0,
        "delay_count": 0,
        "speed_limit_count": 0,
    }

    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        context_path_text = base_context_override or _graph_base_context_path(graph)
        if not context_path_text:
            raise ValueError("Generated graph is missing base_context_path; pass --base-context-path.")
        graph = _with_base_context_override(graph, context_path_text)
        context = load_base_context(_resolve_base_context_path(context_path_text, graph_path))
        disturbance_graph = typed_generated_graph_to_disturbance_graph(
            graph,
            context,
            max_slots=max_slots,
            speed_interruption_threshold=speed_interruption_threshold,
        )
        disturbance_path.parent.mkdir(parents=True, exist_ok=True)
        disturbance_path.write_text(json.dumps(disturbance_graph, ensure_ascii=False, indent=2), encoding="utf-8")

        scenarios = disturbance_graph_to_scenario(disturbance_graph, context)
        payload = _config_payload(
            config_path.stem,
            str(disturbance_graph["base_context_path"]),
            defaults,
            scenarios,
            project_output_dir,
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)

        record["disturbance_count"] = len(disturbance_graph.get("disturbances", []))
        record["delay_count"] = len(scenarios.delays)
        record["speed_limit_count"] = len(scenarios.speed_limits)
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    return record


def _collect_generated_graphs(root: Path, pattern: str) -> List[Path]:
    if root.is_file():
        candidates = [root]
    else:
        graph_root = root / "math_graphs" if (root / "math_graphs").is_dir() else root
        candidates = sorted(path for path in graph_root.glob(pattern) if path.is_file())
    result: List[Path] = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("graph_type") in {MATH_GENERATED_GRAPH_TYPE, GENERATED_GRAPH_TYPE}:
            result.append(path)
    return result


def _infer_generate_run_dir(path: Path) -> Path:
    if path.is_file():
        parent = path.parent
        return parent.parent if parent.name == "math_graphs" else parent
    if path.name == "math_graphs":
        return path.parent
    if (path / "math_graphs").is_dir():
        return path
    return path


def _with_base_context_override(graph: Dict[str, object], base_context_path: str) -> Dict[str, object]:
    if graph.get("graph_type") == MATH_GENERATED_GRAPH_TYPE:
        copied = dict(graph)
        decode_handle = dict(copied.get("decode_handle") or {})
        decode_handle["base_context_path"] = base_context_path.replace("\\", "/")
        copied["decode_handle"] = decode_handle
        return copied
    if graph.get("graph_type") == GENERATED_GRAPH_TYPE:
        copied = dict(graph)
        copied["base_context_path"] = base_context_path.replace("\\", "/")
        return copied
    return graph


def _graph_base_context_path(graph: object) -> str:
    if not isinstance(graph, dict):
        return ""
    if graph.get("graph_type") == MATH_GENERATED_GRAPH_TYPE:
        decode_handle = graph.get("decode_handle", {})
        if isinstance(decode_handle, dict):
            return str(decode_handle.get("base_context_path", "")).strip()
        return ""
    return str(graph.get("base_context_path", "")).strip()


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _clean_path_text(path_text: str) -> str:
    return str(path_text).replace("\\", "/").rstrip("/")


def _join_path_text(root_text: str, name: str) -> str:
    root = _clean_path_text(root_text)
    return f"{root}/{name}" if root else name


def _config_path_text(path: Path) -> str:
    resolved = path if path.is_absolute() else REPO_ROOT / path
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        return _to_posix(resolved)
    return _to_posix(relative)


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


def _clean_number(value: float) -> object:
    value = float(value)
    return int(value) if value.is_integer() else value


def _config_payload(
    name: str,
    base_context_path: str,
    defaults: AppConfig,
    scenarios: ScenarioConfig,
    project_output_dir: str,
) -> Dict[str, object]:
    return {
        "project": {
            "name": name,
            "output_dir": project_output_dir,
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
            "adj_timetable_path": "",
            "adj_timetable_sheet_name": defaults.analyze.adjusted_timetable_sheet_name,
        },
    }


def _write_csv(path: Path, records: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(records[0].keys()) if records else ["index", "generated_graph", "status", "error"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(records)


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _status_counts(records: List[Dict[str, object]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        status = str(record.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _print_record(record: Dict[str, object], completed: int, total: int) -> None:
    print(
        f"[{completed}/{total}] {record['status']} | {Path(str(record['generated_graph'])).name} | "
        f"disturbances={record['disturbance_count']} delays={record['delay_count']} "
        f"speed_limits={record['speed_limit_count']}"
    )
    if record["status"] == "failed":
        print(f"  ! {record['error']}", file=sys.stderr)


def _to_posix(path: Path) -> str:
    return str(path).replace("\\", "/")


if __name__ == "__main__":
    main()

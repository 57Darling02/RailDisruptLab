from __future__ import annotations

import argparse
import copy
import csv
import contextlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project imports work when running as:
#   python scripts/bench_build.py
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.loader import load_config
from core.vae_learning_graph import (
    DEFAULT_EVENT_TIME_WINDOW,
    DEFAULT_EVENT_TOP_K,
    DEFAULT_MAX_SLOTS,
    DEFAULT_SECTION_ORDER_WINDOW,
    DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
    infer_math_dataset_schema,
    relative_to_repo,
    scenario_to_typed_vae_learning_graph,
    typed_learning_graph_to_dataset_profile,
    typed_learning_graph_to_math_context_graph,
    typed_learning_graph_to_math_learning_sample,
)
from main import cmd_build
from core.project_layout import reset_dir
from core.scenario_config import expand_config_scenarios


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch run main build stage for scenario input configs."
    )
    parser.add_argument(
        "--config-root",
        default="config",
        help="Root directory containing case config files.",
    )
    parser.add_argument(
        "--glob",
        default="demo.yml",
        help="Glob pattern under config-root to find config files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process first N configs (0 = all).",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop immediately when one config fails.",
    )
    parser.add_argument("--max-slots", type=int, default=DEFAULT_MAX_SLOTS)
    parser.add_argument("--event-time-window", type=int, default=DEFAULT_EVENT_TIME_WINDOW)
    parser.add_argument("--event-top-k", type=int, default=DEFAULT_EVENT_TOP_K)
    parser.add_argument("--section-order-window", type=int, default=DEFAULT_SECTION_ORDER_WINDOW)
    parser.add_argument("--speed-interruption-threshold", type=float, default=DEFAULT_SPEED_INTERRUPTION_THRESHOLD)
    parser.add_argument("--scenarios", default="", help="Override build.scenarios with a scenario file or directory.")
    parser.add_argument("--output-dir", required=True, help="Dataset output directory.")
    return parser.parse_args()


def _resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _to_posix(path_value: Path) -> str:
    return str(path_value).replace("\\", "/")


class _TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, value: str) -> int:
        for stream in self.streams:
            stream.write(value)
        return len(value)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


@dataclass(frozen=True)
class BuildInput:
    source_config_path: Path
    case_id: str
    payload: Dict[str, object]
    scenario_path: Optional[Path]


def _case_id_from_path(config_path: Path) -> str:
    if config_path.name == "config.yaml":
        return config_path.parent.name
    return config_path.stem


def _collect_configs(config_root: Path, pattern: str, limit: int) -> List[Path]:
    if not config_root.exists():
        raise FileNotFoundError(f"config root not found: {config_root}")
    configs = sorted(path for path in config_root.glob(pattern) if path.is_file())
    if limit > 0:
        configs = configs[:limit]
    return configs


def _write_csv(path: Path, records: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        headers = ["index", "config_file", "status", "error"]
    else:
        headers = list(records[0].keys())
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(records)


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml


def main() -> None:
    args = parse_args()
    config_root = _resolve_path(args.config_root)
    run_dir = _resolve_path(args.output_dir)
    reset_dir(run_dir, allowed_root=REPO_ROOT / "outputs")
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "logs" / "build.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("w", encoding="utf-8") as log_handle:
        with contextlib.redirect_stdout(_TeeStream(sys.stdout, log_handle)):
            with contextlib.redirect_stderr(_TeeStream(sys.stderr, log_handle)):
                _main(args, config_root, run_dir, log_file)


def _main(args: argparse.Namespace, config_root: Path, run_dir: Path, log_file: Path) -> None:
    yaml = _require_yaml()
    manifest_json = run_dir / "manifest.json"
    summary_csv = run_dir / "benchmark" / "build_summary.csv"
    summary_json = run_dir / "benchmark" / "build_summary.json"
    configs_dir = run_dir / "configs"
    case_outputs_dir = run_dir / "cases"
    graph_dir = run_dir / "graph"
    sample_dir = graph_dir / "samples"
    context_graph_path = graph_dir / "context.json"
    dataset_profile_path = graph_dir / "dataset_profile.json"

    source_configs = _collect_configs(config_root, args.glob, args.limit)
    build_inputs = _expand_build_inputs(
        source_configs=source_configs,
        scenarios_override=_resolve_path(args.scenarios) if args.scenarios else None,
        yaml=yaml,
    )
    print(f"Run directory: {run_dir}")
    print(f"Log file: {log_file}")
    print(f"Configs: {configs_dir}")
    print(f"Case outputs: {case_outputs_dir}")
    print(f"Graph samples: {sample_dir}")
    print(f"Context graph: {context_graph_path}")
    print(f"Found source configs: {len(source_configs)}")
    print(f"Expanded cases: {len(build_inputs)}")

    records: List[Dict[str, object]] = []
    graph_sample_records: List[Dict[str, object]] = []
    learning_samples: List[Dict[str, object]] = []
    profile_source_graph: Optional[Dict[str, object]] = None
    shared_context_graph: Optional[Dict[str, object]] = None

    for idx, build_input in enumerate(build_inputs, start=1):
        time.sleep(0.2)
        start = time.perf_counter()
        config_path = build_input.source_config_path
        record: Dict[str, object] = {
            "index": idx,
            "source_config_file": _to_posix(config_path),
            "scenario_file": _to_posix(build_input.scenario_path) if build_input.scenario_path else "",
            "config_file": "",
            "case_id": build_input.case_id,
            "status": "ok",
            "error": "",
            "output_dir": "",
            "lp_path": "",
            "lp_exists": False,
            "learning_sample_path": "",
            "duration_sec": 0.0,
        }

        try:
            case_id, build_config_path = _prepare_case_config(
                build_input=build_input,
                configs_dir=configs_dir,
                case_outputs_dir=case_outputs_dir,
                yaml=yaml,
            )
            record["case_id"] = case_id
            record["config_file"] = _to_posix(build_config_path)

            code = cmd_build(build_config_path)
            if code != 0:
                raise RuntimeError(f"cmd_build returned non-zero code: {code}")

            loaded = load_config(build_config_path)
            record["case_id"] = loaded.project.name or _case_id_from_path(config_path)
            record["output_dir"] = _to_posix(loaded.project.output_dir)
            record["lp_path"] = _to_posix(loaded.build.lp_path)
            record["lp_exists"] = loaded.build.lp_path.exists()
            if not loaded.build.lp_path.exists():
                raise FileNotFoundError(f"LP file not found after build: {loaded.build.lp_path}")

            typed_graph = scenario_to_typed_vae_learning_graph(
                loaded,
                source_config_path=relative_to_repo(build_config_path, REPO_ROOT),
                max_slots=args.max_slots,
                event_time_window=args.event_time_window,
                event_top_k=args.event_top_k,
                section_order_window=args.section_order_window,
                speed_interruption_threshold=args.speed_interruption_threshold,
            )
            if profile_source_graph is None:
                profile_source_graph = typed_graph
            elif typed_graph.get("base_context_path") != profile_source_graph.get("base_context_path"):
                raise ValueError("Math graph export only supports one base_context_path per case graph library.")

            context_graph = typed_learning_graph_to_math_context_graph(typed_graph)
            if shared_context_graph is None:
                shared_context_graph = context_graph
            elif context_graph != shared_context_graph:
                raise ValueError("Math graph export only supports one shared context graph per case graph library.")

            learning_sample = typed_learning_graph_to_math_learning_sample(typed_graph, context_ref="context.json", sample_id=case_id)
            learning_sample_path = sample_dir / f"{_sanitize(case_id)}.json"
            _write_json(learning_sample_path, learning_sample)
            learning_samples.append(learning_sample)
            graph_sample_records.append(
                {
                    "learning_sample_path": relative_to_repo(learning_sample_path, REPO_ROOT),
                    "context_graph_path": relative_to_repo(context_graph_path, REPO_ROOT),
                    "source_config_path": relative_to_repo(build_config_path, REPO_ROOT),
                }
            )
            record["learning_sample_path"] = _to_posix(learning_sample_path)
        except Exception as exc:  # pragma: no cover
            record["status"] = "failed"
            record["error"] = str(exc)

        record["duration_sec"] = round(time.perf_counter() - start, 3)
        records.append(record)

        print(
            f"[{idx}/{len(build_inputs)}] {record['status']} | "
            f"{record['case_id']} | {record['duration_sec']}s"
        )
        if record["status"] == "failed":
            print(f"    reason: {record['error']}", file=sys.stderr)

        if record["status"] == "failed" and args.stop_on_error:
            break

    status_counts: Dict[str, int] = {}
    for item in records:
        status = str(item.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1

    payload: Dict[str, object] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_dir": _to_posix(run_dir),
        "config_root": _to_posix(config_root),
        "glob": args.glob,
        "limit": args.limit,
        "scenarios_override": _to_posix(_resolve_path(args.scenarios)) if args.scenarios else "",
        "total": len(records),
        "status_counts": status_counts,
        "log_file": _to_posix(log_file),
        "configs_dir": _to_posix(configs_dir),
        "case_outputs_dir": _to_posix(case_outputs_dir),
        "sample_dir": _to_posix(sample_dir),
        "context_graph": _to_posix(context_graph_path),
        "dataset_profile": _to_posix(dataset_profile_path),
        "summary_csv": _to_posix(summary_csv),
        "summary_json": _to_posix(summary_json),
    }

    inferred_schema: Dict[str, object] = {}
    if shared_context_graph is not None:
        inferred_context_graph, inferred_schema = infer_math_dataset_schema(
            shared_context_graph,
            learning_samples,
        )
        _write_json(context_graph_path, inferred_context_graph)

    if profile_source_graph is not None:
        _write_dataset_profile(
            dataset_profile_path=dataset_profile_path,
            profile_source_graph=profile_source_graph,
            sample_records=graph_sample_records,
            inferred_schema=inferred_schema,
            args=args,
        )

    _write_csv(summary_csv, records)
    _write_json(summary_json, payload)
    _write_json(manifest_json, payload)

    print(f"Status counts: {status_counts}")

    failed_records = [item for item in records if str(item.get("status")) == "failed"]
    if failed_records:
        print("Failed cases:", file=sys.stderr)
        for item in failed_records:
            print(
                f"- {item.get('case_id', '')}: {item.get('error', '')}",
                file=sys.stderr,
            )

    print(f"Summary CSV: {summary_csv}")
    print(f"Summary JSON: {summary_json}")
    print(f"Log file: {log_file}")
    print(f"Configs: {configs_dir}")
    print(f"Case outputs: {case_outputs_dir}")
    print(f"Graph samples: {sample_dir}")
    print(f"Context graph: {context_graph_path}")


def _expand_build_inputs(
    *,
    source_configs: List[Path],
    scenarios_override: Optional[Path],
    yaml: Any,
) -> List[BuildInput]:
    inputs: List[BuildInput] = []
    for source_config_path in source_configs:
        payload = yaml.safe_load(source_config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"Config must be a YAML object: {source_config_path}")
        if scenarios_override is not None:
            payload = copy.deepcopy(payload)
            build = payload.setdefault("build", {})
            if not isinstance(build, dict):
                raise ValueError(f"Config build section must be a YAML object: {source_config_path}")
            build["scenarios"] = _to_posix(scenarios_override)
        scenario_docs = expand_config_scenarios(payload, source_config_path, yaml)
        for scenario_doc in scenario_docs:
            case_payload = copy.deepcopy(payload)
            build = case_payload.setdefault("build", {})
            if not isinstance(build, dict):
                raise ValueError(f"Config build section must be a YAML object: {source_config_path}")
            build["scenarios"] = scenario_doc.scenarios
            inputs.append(
                BuildInput(
                    source_config_path=source_config_path,
                    case_id=scenario_doc.name,
                    payload=case_payload,
                    scenario_path=scenario_doc.path,
                )
            )
    return inputs


def _prepare_case_config(
    *,
    build_input: BuildInput,
    configs_dir: Path,
    case_outputs_dir: Path,
    yaml: Any,
) -> Tuple[str, Path]:
    payload = copy.deepcopy(build_input.payload)
    project = payload.setdefault("project", {})
    if not isinstance(project, dict):
        raise ValueError(f"Config project section must be a YAML object: {build_input.source_config_path}")
    case_id = build_input.case_id or str(project.get("name", "")).strip() or _case_id_from_path(build_input.source_config_path)
    project["name"] = case_id
    project["output_dir"] = _repo_path_text(case_outputs_dir / _sanitize(case_id))
    build_config_path = configs_dir / f"{_sanitize(case_id)}.yaml"
    build_config_path.parent.mkdir(parents=True, exist_ok=True)
    with build_config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)
    return case_id, build_config_path


def _write_dataset_profile(
    *,
    dataset_profile_path: Path,
    profile_source_graph: Dict[str, object],
    sample_records: List[Dict[str, object]],
    inferred_schema: Dict[str, object],
    args: argparse.Namespace,
) -> None:
    profile = typed_learning_graph_to_dataset_profile(
        profile_source_graph,
        export_profile={
            "max_slots": int(args.max_slots),
            "event_time_window": int(args.event_time_window),
            "event_top_k": int(args.event_top_k),
            "section_order_window": int(args.section_order_window),
            "speed_interruption_threshold": float(args.speed_interruption_threshold),
        },
        samples=sample_records,
        inferred_schema=inferred_schema,
    )
    _write_json(dataset_profile_path, profile)


def _repo_path_text(path: Path) -> str:
    resolved = path.resolve()
    try:
        return relative_to_repo(resolved, REPO_ROOT)
    except ValueError:
        return _to_posix(resolved)


def _sanitize(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    return cleaned or "case"


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import csv
import contextlib
import json
import shutil
import sys
import time
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
    relative_to_repo,
    scenario_to_typed_vae_learning_graph,
    typed_learning_graph_to_dataset_profile,
    typed_learning_graph_to_math_learning_graph,
)
from main import cmd_build


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch run main build stage for case configs produced by case_library_builder.py."
    )
    parser.add_argument(
        "--config-root",
        default="config/batch_case_configs_demo",
        help="Root directory containing case config files.",
    )
    parser.add_argument(
        "--glob",
        default="**/*.yaml",
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
    parser.add_argument("--no-publish-latest", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def _resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _to_posix(path_value: Path) -> str:
    return str(path_value).replace("\\", "/")


def _timestamp_for_path() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _run_dir() -> Path:
    base_path = _resolve_path(f"outputs/bench_build/{_timestamp_for_path()}")
    run_path = base_path
    suffix = 2
    while run_path.exists():
        run_path = base_path.with_name(f"{base_path.name}_{suffix}")
        suffix += 1
    return run_path


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
    run_dir = _run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "bench_build.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("w", encoding="utf-8") as log_handle:
        with contextlib.redirect_stdout(_TeeStream(sys.stdout, log_handle)):
            with contextlib.redirect_stderr(_TeeStream(sys.stderr, log_handle)):
                _main(args, config_root, run_dir, log_file)


def _main(args: argparse.Namespace, config_root: Path, run_dir: Path, log_file: Path) -> None:
    yaml = _require_yaml()
    summary_csv = run_dir / "summary.csv"
    summary_json = run_dir / "summary.json"
    case_library_dir = run_dir / "case_library"
    case_graph_library_dir = run_dir / "case_graph_library"
    graph_dir = case_graph_library_dir / "graphs"

    configs = _collect_configs(config_root, args.glob, args.limit)
    print(f"Run directory: {run_dir}")
    print(f"Log file: {log_file}")
    print(f"Case library: {case_library_dir}")
    print(f"Case graph library: {case_graph_library_dir}")
    print(f"Found configs: {len(configs)}")

    records: List[Dict[str, object]] = []
    graph_sample_records: List[Dict[str, object]] = []
    profile_source_graph: Optional[Dict[str, object]] = None

    for idx, config_path in enumerate(configs, start=1):
        time.sleep(0.2)
        start = time.perf_counter()
        case_id = _case_id_from_source(config_path, yaml)
        record: Dict[str, object] = {
            "index": idx,
            "source_config_file": _to_posix(config_path),
            "config_file": "",
            "case_id": case_id,
            "status": "ok",
            "error": "",
            "output_dir": "",
            "lp_path": "",
            "lp_exists": False,
            "math_graph_path": "",
            "duration_sec": 0.0,
        }

        try:
            case_id, build_config_path = _prepare_case_config(
                source_config_path=config_path,
                case_library_dir=case_library_dir,
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

            math_graph = typed_learning_graph_to_math_learning_graph(typed_graph)
            math_graph_path = graph_dir / f"{_sanitize(case_id)}.json"
            _write_json(math_graph_path, math_graph)
            graph_sample_records.append(
                {
                    "math_graph_path": relative_to_repo(math_graph_path, REPO_ROOT),
                    "source_config_path": relative_to_repo(build_config_path, REPO_ROOT),
                }
            )
            record["math_graph_path"] = _to_posix(math_graph_path)
        except Exception as exc:  # pragma: no cover
            record["status"] = "failed"
            record["error"] = str(exc)

        record["duration_sec"] = round(time.perf_counter() - start, 3)
        records.append(record)

        print(
            f"[{idx}/{len(configs)}] {record['status']} | "
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
        "config_root": _to_posix(config_root),
        "glob": args.glob,
        "limit": args.limit,
        "total": len(records),
        "status_counts": status_counts,
        "run_dir": _to_posix(run_dir),
        "log_file": _to_posix(log_file),
        "case_library": _to_posix(case_library_dir),
        "case_graph_library": _to_posix(case_graph_library_dir),
        "summary_csv": _to_posix(summary_csv),
        "summary_json": _to_posix(summary_json),
    }

    if profile_source_graph is not None:
        _write_case_graph_profile(
            case_graph_library_dir=case_graph_library_dir,
            profile_source_graph=profile_source_graph,
            sample_records=graph_sample_records,
            args=args,
        )

    _write_csv(summary_csv, records)
    _write_json(summary_json, payload)

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
    print(f"Case library: {case_library_dir}")
    print(f"Case graph library: {case_graph_library_dir}")

    if not failed_records and not args.no_publish_latest:
        latest_case_library = _resolve_path("outputs/bench_build/case_library")
        latest_case_graph_library = _resolve_path("outputs/bench_build/case_graph_library")
        _publish_case_library(case_library_dir, latest_case_library, yaml)
        _publish_directory(case_graph_library_dir, latest_case_graph_library)
        _rewrite_latest_case_graph_profile(latest_case_graph_library)
        (_resolve_path("outputs/bench_build/latest_run.txt")).write_text(
            _to_posix(run_dir) + "\n",
            encoding="utf-8",
        )
        print(f"Latest case library: {latest_case_library}")
        print(f"Latest case graph library: {latest_case_graph_library}")
    elif failed_records:
        print("Latest case libraries were not updated because build had failures.", file=sys.stderr)


def _case_id_from_source(config_path: Path, yaml: Any) -> str:
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return _case_id_from_path(config_path)
    if isinstance(payload, dict):
        project = payload.get("project")
        if isinstance(project, dict):
            name = str(project.get("name", "")).strip()
            if name:
                return name
    return _case_id_from_path(config_path)


def _prepare_case_config(*, source_config_path: Path, case_library_dir: Path, yaml: Any) -> Tuple[str, Path]:
    payload = yaml.safe_load(source_config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a YAML object: {source_config_path}")
    project = payload.setdefault("project", {})
    if not isinstance(project, dict):
        raise ValueError(f"Config project section must be a YAML object: {source_config_path}")
    case_id = str(project.get("name", "")).strip() or _case_id_from_path(source_config_path)
    case_dir = case_library_dir / _sanitize(case_id)
    project["name"] = case_id
    project["output_dir"] = _repo_path_text(case_dir)
    build_config_path = case_dir / "config.yaml"
    build_config_path.parent.mkdir(parents=True, exist_ok=True)
    with build_config_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)
    return case_id, build_config_path


def _write_case_graph_profile(
    *,
    case_graph_library_dir: Path,
    profile_source_graph: Dict[str, object],
    sample_records: List[Dict[str, object]],
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
    )
    _write_json(case_graph_library_dir / "dataset_profile.json", profile)


def _publish_case_library(source: Path, destination: Path, yaml: Any) -> None:
    _publish_directory(source, destination)
    for config_path in destination.rglob("config.yaml"):
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            continue
        project = payload.setdefault("project", {})
        if not isinstance(project, dict):
            continue
        project["output_dir"] = _repo_path_text(config_path.parent)
        with config_path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(payload, file, allow_unicode=True, sort_keys=False)


def _publish_directory(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_destination = destination.with_name(f"{destination.name}.tmp_publish")
    if temp_destination.exists():
        shutil.rmtree(temp_destination)
    shutil.copytree(source, temp_destination)
    if destination.exists():
        shutil.rmtree(destination)
    temp_destination.rename(destination)


def _rewrite_latest_case_graph_profile(case_graph_library_dir: Path) -> None:
    profile_path = case_graph_library_dir / "dataset_profile.json"
    if not profile_path.exists():
        return
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    samples = profile.get("samples")
    if isinstance(samples, list):
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            graph_path = str(sample.get("math_graph_path", ""))
            if graph_path:
                sample["math_graph_path"] = _repo_path_text(case_graph_library_dir / "graphs" / Path(graph_path).name)
            source_path = str(sample.get("source_config_path", ""))
            if source_path:
                case_id = Path(source_path).parent.name if Path(source_path).name == "config.yaml" else Path(source_path).stem
                sample["source_config_path"] = _repo_path_text(
                    _resolve_path("outputs/bench_build/case_library") / _sanitize(case_id) / "config.yaml"
                )
    _write_json(profile_path, profile)


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


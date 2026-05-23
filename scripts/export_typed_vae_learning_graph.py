from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Dict, List

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
    summarize_math_learning_graph,
    typed_learning_graph_to_dataset_profile,
    typed_learning_graph_to_math_learning_graph,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export math VAE learning graphs and one dataset profile.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", help="Source YAML config for single-graph export.")
    source.add_argument("--config-glob", help="Glob pattern for batch export.")
    parser.add_argument("--output", help="Output math JSON path for single-graph export.")
    parser.add_argument("--output-dir", help="Output dataset root for batch export. Math samples are written to <output-dir>/graphs.")
    parser.add_argument("--profile-output", help="Optional dataset profile JSON path.")
    parser.add_argument("--no-profile", action="store_true", help="Do not write dataset profile JSON.")
    parser.add_argument("--max-slots", type=int, default=DEFAULT_MAX_SLOTS)
    parser.add_argument("--event-time-window", type=int, default=DEFAULT_EVENT_TIME_WINDOW)
    parser.add_argument("--event-top-k", type=int, default=DEFAULT_EVENT_TOP_K)
    parser.add_argument("--section-order-window", type=int, default=DEFAULT_SECTION_ORDER_WINDOW)
    parser.add_argument("--speed-interruption-threshold", type=float, default=DEFAULT_SPEED_INTERRUPTION_THRESHOLD)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.config:
        _export_single(args)
        return
    _export_batch(args)


def _export_single(args: argparse.Namespace) -> None:
    if not args.output:
        raise ValueError("--output is required with --config.")
    config_path = _resolve(args.config)
    output_path = _resolve(args.output)
    typed_graph = _build_typed_graph(config_path, args)
    graph = typed_learning_graph_to_math_learning_graph(typed_graph)

    _write_json(output_path, graph)
    if not args.no_profile:
        profile_path = _resolve(args.profile_output) if args.profile_output else _default_profile_path(output_path)
        profile = typed_learning_graph_to_dataset_profile(
            typed_graph,
            export_profile=_export_profile(args),
            samples=[
                _sample_record(
                    math_graph_path=output_path,
                    source_config_path=config_path,
                )
            ],
        )
        _write_json(profile_path, profile)
        print(f"Dataset profile exported: {profile_path}")
    summary = summarize_math_learning_graph(graph)
    print(f"Math VAE learning graph exported: {output_path}")
    print(f"Pools: {summary['pool_counts']}")
    print(f"Targets: {summary['target_counts']}")
    print(f"Context edges: {sum(summary['edge_counts'].values())}")


def _export_batch(args: argparse.Namespace) -> None:
    if not args.output_dir:
        raise ValueError("--output-dir is required with --config-glob.")
    config_paths = _glob_configs(args.config_glob)
    if not config_paths:
        raise FileNotFoundError(f"No configs matched --config-glob: {args.config_glob}")

    output_dir = _resolve(args.output_dir)
    graph_dir = output_dir / "graphs"
    graph_dir.mkdir(parents=True, exist_ok=True)
    used_names: Dict[str, int] = {}
    profile_source_graph: Dict[str, object] | None = None
    sample_records: List[Dict[str, object]] = []
    for config_path in config_paths:
        typed_graph = _build_typed_graph(config_path, args)
        if profile_source_graph is None:
            profile_source_graph = typed_graph
        elif typed_graph.get("base_context_path") != profile_source_graph.get("base_context_path"):
            raise ValueError("Batch export only supports one base_context_path per dataset profile.")

        graph = typed_learning_graph_to_math_learning_graph(typed_graph)
        file_name = _graph_file_name(config_path, used_names)
        graph_path = graph_dir / file_name
        _write_json(graph_path, graph)
        sample_records.append(_sample_record(math_graph_path=graph_path, source_config_path=config_path))

    print(f"Math VAE learning graphs exported: {graph_dir}")
    if not args.no_profile and profile_source_graph is not None:
        profile_path = _resolve(args.profile_output) if args.profile_output else output_dir / "dataset_profile.json"
        profile = typed_learning_graph_to_dataset_profile(
            profile_source_graph,
            export_profile=_export_profile(args),
            samples=sample_records,
        )
        _write_json(profile_path, profile)
        print(f"Dataset profile exported: {profile_path}")
    print(f"Graphs: {len(config_paths)}")


def _build_typed_graph(config_path: Path, args: argparse.Namespace) -> Dict[str, object]:
    config = load_config(config_path)
    return scenario_to_typed_vae_learning_graph(
        config,
        source_config_path=relative_to_repo(config_path, REPO_ROOT),
        max_slots=args.max_slots,
        event_time_window=args.event_time_window,
        event_top_k=args.event_top_k,
        section_order_window=args.section_order_window,
        speed_interruption_threshold=args.speed_interruption_threshold,
    )


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def _glob_configs(pattern: str) -> List[Path]:
    raw_pattern = Path(pattern)
    resolved_pattern = str(raw_pattern if raw_pattern.is_absolute() else (REPO_ROOT / raw_pattern).resolve())
    return sorted(Path(path).resolve() for path in glob.glob(resolved_pattern, recursive=True))


def _graph_file_name(config_path: Path, used_names: Dict[str, int]) -> str:
    stem = _sanitize(config_path.stem)
    used_names[stem] = used_names.get(stem, 0) + 1
    if used_names[stem] == 1:
        return f"{stem}.json"
    return f"{stem}_{used_names[stem]:04d}.json"


def _default_profile_path(output_path: Path) -> Path:
    return output_path.parent / "dataset_profile.json"


def _export_profile(args: argparse.Namespace) -> Dict[str, object]:
    return {
        "max_slots": int(args.max_slots),
        "event_time_window": int(args.event_time_window),
        "event_top_k": int(args.event_top_k),
        "section_order_window": int(args.section_order_window),
        "speed_interruption_threshold": float(args.speed_interruption_threshold),
    }


def _sample_record(*, math_graph_path: Path, source_config_path: Path) -> Dict[str, object]:
    return {
        "math_graph_path": relative_to_repo(math_graph_path, REPO_ROOT),
        "source_config_path": relative_to_repo(source_config_path, REPO_ROOT),
    }


def _sanitize(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    return cleaned or "graph"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.base_context import load_base_context
from core.vae_learning_graph import (
    DEFAULT_MAX_SLOTS,
    DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
    MATH_GENERATED_GRAPH_TYPE,
    typed_generated_graph_to_disturbance_graph,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decode a generated VAE graph to disturbance_graph JSON.")
    parser.add_argument("--typed-graph", required=True, help="Generated typed/math graph JSON.")
    parser.add_argument("--output-disturbance-graph", required=True, help="Output disturbance graph JSON.")
    parser.add_argument("--base-context-path", default="", help="Optional BaseContext path override.")
    parser.add_argument("--max-slots", type=int, default=DEFAULT_MAX_SLOTS)
    parser.add_argument("--speed-interruption-threshold", type=float, default=DEFAULT_SPEED_INTERRUPTION_THRESHOLD)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    typed_graph_path = _resolve(args.typed_graph)
    output_path = _resolve(args.output_disturbance_graph)
    graph = json.loads(typed_graph_path.read_text(encoding="utf-8"))

    context_path_text = args.base_context_path or _graph_base_context_path(graph)
    if not context_path_text:
        raise ValueError("Generated VAE graph is missing base_context_path.")
    context = load_base_context(_resolve_base_context_path(context_path_text, typed_graph_path))

    disturbance_graph = typed_generated_graph_to_disturbance_graph(
        graph,
        context,
        max_slots=args.max_slots,
        speed_interruption_threshold=args.speed_interruption_threshold,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(disturbance_graph, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Disturbance graph decoded: {output_path}")
    print(f"Disturbances: {len(disturbance_graph['disturbances'])}")


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


def _graph_base_context_path(graph: object) -> str:
    if not isinstance(graph, dict):
        return ""
    if graph.get("graph_type") == MATH_GENERATED_GRAPH_TYPE:
        decode_handle = graph.get("decode_handle", {})
        if isinstance(decode_handle, dict):
            return str(decode_handle.get("base_context_path", "")).strip()
        return ""
    return str(graph.get("base_context_path", "")).strip()


if __name__ == "__main__":
    main()

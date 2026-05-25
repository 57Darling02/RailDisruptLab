from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.disturbance_graph import scenario_to_disturbance_graph
from core.loader import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export build.scenarios to a disturbance graph JSON.")
    parser.add_argument("--config", required=True, help="Source YAML config.")
    parser.add_argument("--output", required=True, help="Output disturbance graph JSON.")
    return parser.parse_args()


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def main() -> None:
    args = parse_args()
    config_path = _resolve(args.config)
    output_path = _resolve(args.output)

    config = load_config(config_path)
    graph = scenario_to_disturbance_graph(config)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Disturbance graph exported: {output_path}")
    print(f"Disturbances: {len(graph['disturbances'])}")


if __name__ == "__main__":
    main()

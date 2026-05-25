from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

from src.metrics import (
    MATH_GENERATED_GRAPH_TYPE,
    compare_graph_sets,
    compare_solver_difficulty,
    load_json_graphs,
    load_solver_table,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate generated math graphs and solver difficulty.")
    parser.add_argument("--reference-graphs", default="", help="Reference compact VAE graph library.")
    parser.add_argument("--generated-graphs", default="", help="Generated graph file or directory.")
    parser.add_argument("--reference-solve-csv", default="", help="Reference solver metrics CSV.")
    parser.add_argument("--generated-solve-csv", default="", help="Generated solver metrics CSV.")
    parser.add_argument("--output", required=True, help="Output JSON report path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report: Dict[str, object] = {}

    if args.reference_graphs and args.generated_graphs:
        reference_graphs = load_json_graphs(args.reference_graphs)
        generated_graphs = load_json_graphs(args.generated_graphs)
        if not generated_graphs:
            generated_graphs = load_json_graphs(args.generated_graphs, graph_type=MATH_GENERATED_GRAPH_TYPE)
        report["graph_similarity"] = compare_graph_sets(reference_graphs, generated_graphs)

    if args.reference_solve_csv and args.generated_solve_csv:
        reference_rows = load_solver_table(args.reference_solve_csv)
        generated_rows = load_solver_table(args.generated_solve_csv)
        report["solver_difficulty"] = compare_solver_difficulty(reference_rows, generated_rows)

    if not report:
        raise ValueError("Provide graph inputs, solver CSV inputs, or both.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evaluation report written: {output_path}")


if __name__ == "__main__":
    main()

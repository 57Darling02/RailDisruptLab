from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.project_layout import ProjectLayout
from core.workflow.service import (
    analyze_dataset,
    build_dataset,
    generate_scenarios,
    new_project,
    normal_generate,
    prepare,
    solve_dataset,
    train_model,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    if len(argv) >= 1 and argv[0] == "newproject":
        parser = argparse.ArgumentParser(description="Create a RailGraph2Gurobi project sandbox.")
        parser.add_argument("command", choices=["newproject"])
        parser.add_argument("projectid")
        return parser.parse_args(argv)

    parser = argparse.ArgumentParser(description="Project sandbox workflow.")
    parser.add_argument("projectid")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prepare", help="Build project context.json from conf/prepare.yml.")

    normal = sub.add_parser("normal_generate", help="Generate a normal random scenario set.")
    normal.add_argument("config_id", nargs="?", default="default")

    build = sub.add_parser("build", help="Build LP instances from a scenario set.")
    build.add_argument("scenario_set_id")
    build.add_argument("dataset_id")

    solve = sub.add_parser("solve", help="Solve all LPs in a dataset.")
    solve.add_argument("dataset_id")
    solve.add_argument("--limit", type=int, default=0)
    solve.add_argument("--time-limit", type=float, default=None)

    analyze = sub.add_parser("analyze", help="Export adjusted timetables and analyze a dataset.")
    analyze.add_argument("dataset_id")
    analyze.add_argument("--limit", type=int, default=0)

    model = sub.add_parser("model", help="Model commands.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    train = model_sub.add_parser("train", help="Train VAE from a scenario set.")
    train.add_argument("config_id", nargs="?", default="default")

    generation = sub.add_parser("generation", help="Generate and decode scenarios with a trained model.")
    generation.add_argument("model_id")
    generation.add_argument("scenario_set_id")
    generation.add_argument("--num-samples", type=int, default=100)
    generation.add_argument("--seed", type=int, default=1)
    generation.add_argument("--device", default="auto")
    generation.add_argument("--overwrite", action="store_true")

    return parser.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])
    if args.command == "newproject":
        new_project(ProjectLayout.from_name(args.projectid))
        return

    layout = ProjectLayout.from_name(args.projectid)
    if args.command == "prepare":
        prepare(layout)
    elif args.command == "normal_generate":
        normal_generate(layout, args.config_id)
    elif args.command == "build":
        build_dataset(layout, args.scenario_set_id, args.dataset_id)
    elif args.command == "solve":
        solve_dataset(layout, args.dataset_id, limit=args.limit, time_limit=args.time_limit)
    elif args.command == "analyze":
        analyze_dataset(layout, args.dataset_id, limit=args.limit)
    elif args.command == "model" and args.model_command == "train":
        train_model(layout, args.config_id)
    elif args.command == "generation":
        generate_scenarios(
            layout,
            model_id=args.model_id,
            scenario_set_id=args.scenario_set_id,
            num_samples=args.num_samples,
            seed=args.seed,
            device=args.device,
            overwrite=args.overwrite,
        )
    else:  # pragma: no cover
        raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover
        print(f"project.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.analysis.timetable import export_dataset_timetables
from backend.scenarios import (
    create_scenario_set,
    delete_scenario,
    normal_generate,
)
from core.project_layout import ProjectLayout
from core.vae_learning_graph import (
    DEFAULT_EVENT_TIME_WINDOW,
    DEFAULT_EVENT_TOP_K,
    DEFAULT_MAX_SLOTS,
    DEFAULT_SECTION_ORDER_WINDOW,
    DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
)
from core.workflow.service import (
    build_dataset,
    create_dataset,
    delete_project,
    delete_source_file,
    generate_scenarios,
    new_project,
    prepare,
    solve_dataset,
    train_model,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    if len(argv) >= 1 and argv[0] in {"newproject", "deleteproject"}:
        parser = argparse.ArgumentParser(description="Manage a RailDisruptLab project sandbox.")
        parser.add_argument("command", choices=["newproject", "deleteproject"])
        parser.add_argument("projectid")
        parser.add_argument("--force", action="store_true")
        return parser.parse_args(argv)

    parser = argparse.ArgumentParser(description="Project sandbox workflow.")
    parser.add_argument("projectid")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_cmd = sub.add_parser("prepare", help="Build project context.json from project source files.")
    prepare_cmd.add_argument("--timetable-filename", required=True)
    prepare_cmd.add_argument("--mileage-filename", required=True)
    prepare_cmd.add_argument("--timetable-sheet-name", default="Sheet1")
    prepare_cmd.add_argument("--mileage-sheet-name", default="Sheet1")

    source = sub.add_parser("source", help="Manage project source files.")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    source_delete = source_sub.add_parser("delete", help="Delete a source file.")
    source_delete.add_argument("filename")

    normal = sub.add_parser("normal_generate", help="Generate normal random scenarios into a scenario set.")
    normal.add_argument("scenario_set_id")
    normal.add_argument("--seed", type=int, default=20260320)
    normal.add_argument("--delay-count", type=int, default=10)
    normal.add_argument("--speed-count", type=int, default=10)
    normal.add_argument("--interruption-count", type=int, default=10)
    normal.add_argument("--combo-per-type", type=int, default=10)
    normal.add_argument("--overwrite", action="store_true")
    normal.add_argument("--merge", action="store_true")

    scenario_set = sub.add_parser("scenario-set", aliases=["scenario_set"], help="Manage scenario sets.")
    scenario_set_sub = scenario_set.add_subparsers(dest="scenario_set_command", required=True)
    scenario_set_create = scenario_set_sub.add_parser("create", help="Create an empty scenario set.")
    scenario_set_create.add_argument("scenario_set_id")
    scenario_set_create.add_argument("--exist-ok", action="store_true")

    scenario = sub.add_parser("scenario", help="Manage scenarios in a scenario set.")
    scenario_sub = scenario.add_subparsers(dest="scenario_command", required=True)
    scenario_delete = scenario_sub.add_parser("delete", help="Delete a scenario from a scenario set.")
    scenario_delete.add_argument("scenario_set_id")
    scenario_delete.add_argument("scenario_id")

    build = sub.add_parser("build", help="Build LP instances from a scenario set.")
    build.add_argument("scenario_set_id")
    build.add_argument("dataset_id")
    build.add_argument("--scenario-id", default="", help="Build only one scenario from the scenario set.")
    build.add_argument("--objective-delay-weight", type=float, default=1.0)
    build.add_argument("--objective-mode", default="abs")
    build.add_argument("--cancellation-enabled", action="store_true")
    build.add_argument("--cancellation-penalty-weight", type=float, default=1000.0)
    build.add_argument("--arr-arr-headway-seconds", type=int, default=180)
    build.add_argument("--dep-dep-headway-seconds", type=int, default=180)
    build.add_argument("--dwell-seconds-at-stops", type=int, default=120)
    build.add_argument("--big-m", type=int, default=100000)
    build.add_argument("--tolerance-delay-seconds", type=int, default=7200)

    dataset = sub.add_parser("dataset", help="Manage MILP datasets.")
    dataset_sub = dataset.add_subparsers(dest="dataset_command", required=True)
    dataset_create = dataset_sub.add_parser("create", help="Create an empty MILP dataset directory.")
    dataset_create.add_argument("dataset_id")
    dataset_create.add_argument("--exist-ok", action="store_true")

    solve = sub.add_parser("solve", help="Solve LP files in a dataset.")
    solve.add_argument("dataset_id")
    solve.add_argument("--case-id", default="", help="Solve only one case in the dataset.")
    solve.add_argument("--limit", type=int, default=0)
    solve.add_argument("--time-limit", type=float, default=120.0)
    solve.add_argument("--mip-gap", type=float, default=0.0)
    solve.add_argument("--threads", type=int, default=0)

    export_timetable = sub.add_parser("export_timetable", help="Export adjusted timetables from solved cases.")
    export_timetable.add_argument("dataset_id")
    export_timetable.add_argument("--case-id", default="", help="Export only one case in the dataset.")
    export_timetable.add_argument("--limit", type=int, default=0)

    model = sub.add_parser("model", help="Model commands.")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    train = model_sub.add_parser("train", help="Train VAE from a scenario set.")
    train.add_argument("model_id")
    train.add_argument("scenario_set_id")
    train.add_argument("--max-slots", type=int, default=DEFAULT_MAX_SLOTS)
    train.add_argument("--event-time-window", type=int, default=DEFAULT_EVENT_TIME_WINDOW)
    train.add_argument("--event-top-k", type=int, default=DEFAULT_EVENT_TOP_K)
    train.add_argument("--section-order-window", type=int, default=DEFAULT_SECTION_ORDER_WINDOW)
    train.add_argument("--hidden-dim", type=int, default=64)
    train.add_argument("--latent-dim", type=int, default=16)
    train.add_argument("--message-passing-steps", type=int, default=2)
    train.add_argument("--epochs", type=int, default=800)
    train.add_argument("--batch-size", type=int, default=8)
    train.add_argument("--lr", type=float, default=0.0003)
    train.add_argument("--seed", type=int, default=1)
    train.add_argument("--device", default="auto")
    train.add_argument("--log-every", type=int, default=1)
    train.add_argument("--count-weight", type=float, default=1.0)
    train.add_argument("--anchor-weight", type=float, default=1.0)
    train.add_argument("--param-weight", type=float, default=2.0)
    train.add_argument("--kl-weight", type=float, default=0.0015)

    generation = sub.add_parser("generation", help="Generate and decode scenarios with a trained model.")
    generation.add_argument("model_id")
    generation.add_argument("checkpoint")
    generation.add_argument("scenario_set_id")
    generation.add_argument("--num-samples", type=int, default=100)
    generation.add_argument("--seed", type=int, default=1)
    generation.add_argument("--device", default="auto")
    generation.add_argument(
        "--speed-interruption-threshold",
        type=float,
        default=DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
    )
    generation.add_argument("--overwrite", action="store_true")

    return parser.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])
    if args.command == "newproject":
        new_project(ProjectLayout.from_name(args.projectid))
        return
    if args.command == "deleteproject":
        delete_project(ProjectLayout.from_name(args.projectid), force=args.force)
        return

    layout = ProjectLayout.from_name(args.projectid)
    if args.command == "prepare":
        prepare(
            layout,
            timetable_filename=args.timetable_filename,
            mileage_filename=args.mileage_filename,
            timetable_sheet_name=args.timetable_sheet_name,
            mileage_sheet_name=args.mileage_sheet_name,
        )
    elif args.command == "source" and args.source_command == "delete":
        delete_source_file(layout, args.filename)
    elif args.command == "normal_generate":
        normal_generate(
            layout,
            scenario_set_id=args.scenario_set_id,
            seed=args.seed,
            delay_count=args.delay_count,
            speed_count=args.speed_count,
            interruption_count=args.interruption_count,
            combo_per_type=args.combo_per_type,
            overwrite=args.overwrite,
            merge=args.merge,
        )
    elif args.command in {"scenario-set", "scenario_set"} and args.scenario_set_command == "create":
        create_scenario_set(layout, args.scenario_set_id, exist_ok=args.exist_ok)
    elif args.command == "scenario" and args.scenario_command == "delete":
        delete_scenario(layout, args.scenario_set_id, args.scenario_id)
    elif args.command == "build":
        build_dataset(
            layout,
            args.scenario_set_id,
            args.dataset_id,
            scenario_id=args.scenario_id,
            objective_delay_weight=args.objective_delay_weight,
            objective_mode=args.objective_mode,
            cancellation_enabled=args.cancellation_enabled,
            cancellation_penalty_weight=args.cancellation_penalty_weight,
            arr_arr_headway_seconds=args.arr_arr_headway_seconds,
            dep_dep_headway_seconds=args.dep_dep_headway_seconds,
            dwell_seconds_at_stops=args.dwell_seconds_at_stops,
            big_m=args.big_m,
            tolerance_delay_seconds=args.tolerance_delay_seconds,
        )
    elif args.command == "dataset" and args.dataset_command == "create":
        create_dataset(layout, args.dataset_id, exist_ok=args.exist_ok)
    elif args.command == "solve":
        solve_dataset(
            layout,
            args.dataset_id,
            case_id=args.case_id,
            limit=args.limit,
            time_limit=args.time_limit,
            mip_gap=args.mip_gap,
            threads=args.threads,
        )
    elif args.command == "export_timetable":
        export_dataset_timetables(
            layout,
            args.dataset_id,
            case_id=args.case_id,
            limit=args.limit,
        )
    elif args.command == "model" and args.model_command == "train":
        train_model(
            layout,
            model_id=args.model_id,
            scenario_set_id=args.scenario_set_id,
            max_slots=args.max_slots,
            event_time_window=args.event_time_window,
            event_top_k=args.event_top_k,
            section_order_window=args.section_order_window,
            hidden_dim=args.hidden_dim,
            latent_dim=args.latent_dim,
            message_passing_steps=args.message_passing_steps,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            seed=args.seed,
            device=args.device,
            log_every=args.log_every,
            count_weight=args.count_weight,
            anchor_weight=args.anchor_weight,
            param_weight=args.param_weight,
            kl_weight=args.kl_weight,
        )
    elif args.command == "generation":
        generate_scenarios(
            layout,
            model_id=args.model_id,
            checkpoint=args.checkpoint,
            scenario_set_id=args.scenario_set_id,
            num_samples=args.num_samples,
            seed=args.seed,
            device=args.device,
            speed_interruption_threshold=args.speed_interruption_threshold,
            overwrite=args.overwrite,
        )
    else:  # pragma: no cover
        raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()

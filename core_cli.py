from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from core.base_context import build_base_context, load_base_context, write_base_context
from core.builder import build_model
from core.exporter import export_lp
from core.loader import load_config_payload, load_mileage_table, load_timetable, parse_scenario_config
from core.project_layout import to_posix
from core.scenario_config import load_scenario_document
from core.vae_learning_graph import (
    DEFAULT_EVENT_TIME_WINDOW,
    DEFAULT_EVENT_TOP_K,
    DEFAULT_MAX_SLOTS,
    DEFAULT_SECTION_ORDER_WINDOW,
    scenario_config_to_typed_vae_learning_graph,
    typed_learning_graph_to_math_context_graph,
    typed_learning_graph_to_math_learning_sample,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="RailDisruptLab core path-only CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    context_parser = subparsers.add_parser("build-context")
    context_parser.add_argument("--timetable", required=True)
    context_parser.add_argument("--mileage", required=True)
    context_parser.add_argument("--output", required=True)
    context_parser.add_argument("--timetable-sheet-name", default="Sheet1")
    context_parser.add_argument("--mileage-sheet-name", default="Sheet1")

    milp_parser = subparsers.add_parser("build-milp-case")
    milp_parser.add_argument("--context", required=True)
    milp_parser.add_argument("--scenario", required=True)
    milp_parser.add_argument("--output-dir", required=True)
    milp_parser.add_argument("--summary-output", default="")
    milp_parser.add_argument("--objective-delay-weight", type=float, default=1.0)
    milp_parser.add_argument("--objective-mode", default="abs", choices=["abs", "delay"])
    milp_parser.add_argument("--cancellation-enabled", action="store_true")
    milp_parser.add_argument("--cancellation-penalty-weight", type=float, default=1000.0)
    milp_parser.add_argument("--arr-arr-headway-seconds", type=int, default=180)
    milp_parser.add_argument("--dep-dep-headway-seconds", type=int, default=180)
    milp_parser.add_argument("--dwell-seconds-at-stops", type=int, default=120)
    milp_parser.add_argument("--big-m", type=int, default=100000)
    milp_parser.add_argument("--tolerance-delay-seconds", type=int, default=7200)

    vae_parser = subparsers.add_parser("export-vae-case-graph")
    vae_parser.add_argument("--context", required=True)
    vae_parser.add_argument("--scenario", required=True)
    vae_parser.add_argument("--context-output", required=True)
    vae_parser.add_argument("--sample-output", required=True)
    vae_parser.add_argument("--max-slots", type=int, default=DEFAULT_MAX_SLOTS)
    vae_parser.add_argument("--event-time-window", type=int, default=DEFAULT_EVENT_TIME_WINDOW)
    vae_parser.add_argument("--event-top-k", type=int, default=DEFAULT_EVENT_TOP_K)
    vae_parser.add_argument("--section-order-window", type=int, default=DEFAULT_SECTION_ORDER_WINDOW)

    args = parser.parse_args()
    if args.command == "build-context":
        build_context(args)
    elif args.command == "build-milp-case":
        build_milp_case(args)
    elif args.command == "export-vae-case-graph":
        export_vae_case_graph(args)
    else:  # pragma: no cover
        raise ValueError(f"Unsupported command: {args.command}")


def build_context(args: argparse.Namespace) -> None:
    timetable = Path(args.timetable)
    mileage = Path(args.mileage)
    context = build_base_context(
        timetable_path=timetable,
        mileage_path=mileage,
        timetable_sheet_name=args.timetable_sheet_name,
        mileage_sheet_name=args.mileage_sheet_name,
        timetable_table=load_timetable(timetable, args.timetable_sheet_name),
        mileage_table=load_mileage_table(mileage, args.mileage_sheet_name),
    )
    write_base_context(context, Path(args.output))


def build_milp_case(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    case_id = output_dir.name
    payload = {
        "project": {
            "name": case_id,
            "output_dir": to_posix(output_dir),
            "base_context_path": to_posix(Path(args.context)),
        },
        "build": {"scenarios": {"path": to_posix(Path(args.scenario))}},
        "solver": {
            "objective_delay_weight": args.objective_delay_weight,
            "objective_mode": args.objective_mode,
            "cancellation_enabled": bool(args.cancellation_enabled),
            "cancellation_penalty_weight": args.cancellation_penalty_weight,
            "arr_arr_headway_seconds": args.arr_arr_headway_seconds,
            "dep_dep_headway_seconds": args.dep_dep_headway_seconds,
            "dwell_seconds_at_stops": args.dwell_seconds_at_stops,
            "big_m": args.big_m,
            "tolerance_delay_seconds": args.tolerance_delay_seconds,
        },
        "solve": {},
        "export-timetable": {},
    }
    config = load_config_payload(payload, output_dir / "case.yml")
    model = build_model(config.base_context.translated, config)
    export_lp(model, config.build.lp_path)
    if args.summary_output:
        write_json(
            Path(args.summary_output),
            {
                "case_id": case_id,
                "constraints": len(model.constraints),
                "artifacts": {"lp": to_posix(config.build.lp_path)},
            },
        )


def export_vae_case_graph(args: argparse.Namespace) -> None:
    yaml = require_yaml()
    scenario_path = Path(args.scenario)
    context_path = Path(args.context)
    context = load_base_context(context_path)
    doc = load_scenario_document(scenario_path, yaml)
    scenarios = parse_scenario_config(doc.scenarios, context)
    typed = scenario_config_to_typed_vae_learning_graph(
        scenarios,
        context,
        base_context_path=to_posix(context_path),
        source_config_path=to_posix(scenario_path),
        max_slots=args.max_slots,
        event_time_window=args.event_time_window,
        event_top_k=args.event_top_k,
        section_order_window=args.section_order_window,
    )
    context_output = Path(args.context_output)
    sample_output = Path(args.sample_output)
    write_json(context_output, typed_learning_graph_to_math_context_graph(typed))
    relative_context_ref = to_posix(Path(os.path.relpath(context_output, sample_output.parent)))
    write_json(
        sample_output,
        typed_learning_graph_to_math_learning_sample(
            typed,
            context_ref=relative_context_ref,
            sample_id=doc.name,
        ),
    )


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: PyYAML") from exc
    return yaml


if __name__ == "__main__":
    main()

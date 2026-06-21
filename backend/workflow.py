from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from backend.analysis.timetable import materialize_case_timetable
from backend.run_graphs import load_scenario_context, resolve_run_graph_context
from core.base_context import load_base_context
from core.disturbance_graph import disturbance_graph_to_scenario
from core.loader import parse_scenario_config
from core.project_layout import ProjectLayout, REPO_ROOT, reset_dir, sanitize_id, to_posix
from core.scenario_config import (
    ScenarioDocument,
    RunGraphReference,
    load_scenario_document,
    scenario_config_to_yaml,
    scenario_document_to_yaml,
    scenario_file_by_id,
    scenario_files,
)
from core.types import BaseContext, ScenarioConfig
from core.vae_learning_graph import (
    DEFAULT_EVENT_TIME_WINDOW,
    DEFAULT_EVENT_TOP_K,
    DEFAULT_MAX_SLOTS,
    DEFAULT_SECTION_ORDER_WINDOW,
    DEFAULT_USE_RELATION_GRAPH,
    infer_math_dataset_schema,
    scenario_config_to_typed_vae_learning_graph,
    typed_generated_graph_to_disturbance_graph,
    typed_learning_graph_to_math_context_graph,
)


def new_project(layout: ProjectLayout) -> None:
    for directory in (
        layout.run_graph_sets_dir,
        layout.scenario_sets_dir,
        layout.model_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    print(f"Project initialized: {layout.root}")


def delete_project(layout: ProjectLayout, *, force: bool = False) -> None:
    if not force:
        raise ValueError("Project deletion requires --force.")
    if not layout.root.is_dir():
        raise FileNotFoundError(f"Project not found: {layout.root}")
    reset_dir(layout.root)
    print(f"Project deleted: {layout.root}")


def create_adjustment_plan(
    layout: ProjectLayout,
    scenario_set_id: str,
    plan_id: str,
    *,
    exist_ok: bool = False,
) -> None:
    require_project(layout)
    scenario_set = layout.scenario_set(scenario_set_id)
    root = scenario_set.adjustment_plan(plan_id).root
    if root.exists():
        if not root.is_dir():
            raise NotADirectoryError(f"Adjustment plan path is not a directory: {root}")
        if not exist_ok:
            raise FileExistsError(f"Adjustment plan already exists: {root}")
    else:
        root.mkdir(parents=True, exist_ok=False)
    print(f"Adjustment plan ready: {root}")


def build_adjustment_plan(
    layout: ProjectLayout,
    scenario_set_id: str,
    plan_id: str,
    *,
    scenario_id: str = "",
    objective_delay_weight: float = 1.0,
    objective_mode: str = "abs",
    cancellation_enabled: bool = False,
    cancellation_penalty_weight: float = 1000.0,
    arr_arr_headway_seconds: int = 180,
    dep_dep_headway_seconds: int = 180,
    dwell_seconds_at_stops: int = 120,
    big_m: int = 100000,
    tolerance_delay_seconds: int = 7200,
) -> None:
    docs = load_scenario_documents(layout, scenario_set_id, scenario_id=scenario_id)
    validate_scenario_documents(layout, docs)
    plan = layout.scenario_set(scenario_set_id).adjustment_plan(plan_id)
    if plan.root.exists() and not plan.root.is_dir():
        raise NotADirectoryError(f"Adjustment plan path is not a directory: {plan.root}")
    if not plan.root.is_dir():
        plan.root.mkdir(parents=True, exist_ok=False)
    prepare_output_dir(plan.root, overwrite=True)

    for index, doc in enumerate(docs, start=1):
        started = datetime.now()
        case_id = sanitize_id(doc.name)
        case_dir = plan.cases_dir / case_id
        record = base_record(index, case_id)
        build_config = {
            "objective_delay_weight": objective_delay_weight,
            "objective_mode": objective_mode,
            "cancellation_enabled": cancellation_enabled,
            "cancellation_penalty_weight": cancellation_penalty_weight,
            "arr_arr_headway_seconds": arr_arr_headway_seconds,
            "dep_dep_headway_seconds": dep_dep_headway_seconds,
            "dwell_seconds_at_stops": dwell_seconds_at_stops,
            "big_m": big_m,
            "tolerance_delay_seconds": tolerance_delay_seconds,
        }
        lp_path = case_dir / f"{case_id}.lp"
        cli_summary_path = case_dir / "core_build_summary.json"
        try:
            case_dir.mkdir(parents=True, exist_ok=True)
            write_yaml(case_dir / "scenario.yml", scenario_document_to_yaml(doc))
            if doc.path is None:
                raise ValueError(f"Scenario document path is required: {doc.name}")
            scenario_context_path = resolve_run_graph_context(layout, doc.run_graph)
            run(
                [
                    sys.executable,
                    "core_cli.py",
                    "build-milp-case",
                    "--context",
                    to_posix(scenario_context_path),
                    "--scenario",
                    to_posix(case_dir / "scenario.yml"),
                    "--output-dir",
                    to_posix(case_dir),
                    "--summary-output",
                    to_posix(cli_summary_path),
                    "--objective-delay-weight",
                    str(objective_delay_weight),
                    "--objective-mode",
                    objective_mode,
                    "--cancellation-penalty-weight",
                    str(cancellation_penalty_weight),
                    "--arr-arr-headway-seconds",
                    str(arr_arr_headway_seconds),
                    "--dep-dep-headway-seconds",
                    str(dep_dep_headway_seconds),
                    "--dwell-seconds-at-stops",
                    str(dwell_seconds_at_stops),
                    "--big-m",
                    str(big_m),
                    "--tolerance-delay-seconds",
                    str(tolerance_delay_seconds),
                    *(
                        ["--cancellation-enabled"]
                        if cancellation_enabled
                        else []
                    ),
                ]
            )
            cli_summary = read_json(cli_summary_path)
            record.update(
                {
                    "status": "ok",
                    "constraints": int(cli_summary.get("constraints", 0) or 0),
                }
            )
        except Exception as exc:
            record.update({"status": "failed", "error": str(exc)})
        record["duration_sec"] = elapsed_seconds(started)
        write_json(
            case_dir / "build.json",
            {
                "case_id": case_id,
                "scenario_set_id": sanitize_id(scenario_set_id),
                "source_scenario_id": sanitize_id(doc.name),
                "build_config": build_config,
                "result": record,
                "artifacts": {
                    "scenario": to_posix(case_dir / "scenario.yml"),
                    "lp": to_posix(lp_path),
                },
            },
        )
        print(f"[{index}/{len(docs)}] {record['status']} | {case_id}")

    write_json(
        plan.root / "plan.json",
        {
            "plan_id": sanitize_id(plan_id),
            "scenario_set_id": sanitize_id(scenario_set_id),
            "scenario_id": sanitize_id(scenario_id) if scenario_id else "",
            "build_config": {
                "objective_delay_weight": objective_delay_weight,
                "objective_mode": objective_mode,
                "cancellation_enabled": cancellation_enabled,
                "cancellation_penalty_weight": cancellation_penalty_weight,
                "arr_arr_headway_seconds": arr_arr_headway_seconds,
                "dep_dep_headway_seconds": dep_dep_headway_seconds,
                "dwell_seconds_at_stops": dwell_seconds_at_stops,
                "big_m": big_m,
                "tolerance_delay_seconds": tolerance_delay_seconds,
            },
            "case_count": len(docs),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    fail_if_records_failed(read_case_stage_records(plan.cases_dir, "build.json"), "build")
    print(f"Adjustment plan built: {plan.root}")


def solve_adjustment_plan(
    layout: ProjectLayout,
    scenario_set_id: str,
    plan_id: str,
    *,
    case_id: str = "",
    limit: int = 0,
    time_limit: float = 120.0,
    mip_gap: float = 0.0,
    threads: int = 0,
    skip_solved: bool = False,
) -> None:
    plan = layout.scenario_set(scenario_set_id).adjustment_plan(plan_id)
    case_dirs = [plan_case_dir(plan, case_id)] if case_id else limit_items(plan_case_dirs(plan), limit)
    records = [
        solve_case(
            layout,
            case_dir,
            index,
            time_limit=time_limit,
            mip_gap=mip_gap,
            threads=threads,
            skip_solved=skip_solved and not case_id,
        )
        for index, case_dir in enumerate(case_dirs, start=1)
    ]

    fail_if_records_failed(records, "solve")
    fail_if_derived_records_failed(records, "timetable", "timetable materialization")
    ok_count = sum(1 for record in records if record.get("status") in {"ok", "timeout", "skipped"})
    print(f"Solve finished: {ok_count}/{len(records)} case(s)")


def solve_case(
    layout: ProjectLayout,
    case_dir: Path,
    index: int,
    *,
    time_limit: float = 120.0,
    mip_gap: float = 0.0,
    threads: int = 0,
    skip_solved: bool = False,
) -> Dict[str, object]:
    started = datetime.now()
    case_id = sanitize_id(case_dir.name)
    lp_path = case_dir / f"{case_id}.lp"
    sol_path = case_dir / f"{case_id}.sol"
    summary_path = case_dir / "core_solve_summary.json"
    timetable_path = case_dir / "adjusted_timetable.json"
    record = base_record(index, case_id)
    timetable_record: Dict[str, object] = {"status": "pending"}
    solver_config = {
        "time_limit": max(0.0, float(time_limit or 0.0)),
        "mip_gap": max(0.0, float(mip_gap or 0.0)),
        "threads": max(0, int(threads or 0)),
        "skip_solved": bool(skip_solved),
    }
    try:
        if not lp_path.is_file():
            raise FileNotFoundError(f"LP not found: {lp_path}")
        if skip_solved and sol_path.is_file() and sol_path.with_suffix(".sol.csv").is_file():
            record.update({"status": "skipped", "reason": "solution_exists"})
        else:
            run(
                [
                    sys.executable,
                    "core_cli.py",
                    "solve-milp-case",
                    "--lp",
                    to_posix(lp_path),
                    "--solution",
                    to_posix(sol_path),
                    "--summary-output",
                    to_posix(summary_path),
                    "--time-limit",
                    str(float(solver_config["time_limit"])),
                    "--mip-gap",
                    str(float(solver_config["mip_gap"])),
                    "--threads",
                    str(int(solver_config["threads"])),
                ]
            )
            summary = read_json(summary_path)
            if not isinstance(summary, dict):
                raise ValueError(f"Solve summary must be an object: {summary_path}")
            record.update(summary)
        if record.get("status") in {"ok", "timeout", "skipped"} and sol_path.is_file():
            timetable_record = materialize_case_timetable(layout, case_dir, index)
    except Exception as exc:
        record.update({"status": "failed", "error": str(exc)})
    record["duration_sec"] = elapsed_seconds(started)
    write_json(
        case_dir / "solve.json",
        {
            "case_id": case_id,
            "solver_config": solver_config,
            "result": record,
            "artifacts": {
                "lp": to_posix(lp_path),
                "solution": to_posix(sol_path),
                "solution_csv": to_posix(sol_path.with_suffix(".sol.csv")),
                "timetable": to_posix(timetable_path),
                "summary": to_posix(summary_path),
            },
            "derived": {
                "timetable": timetable_record,
            },
        },
    )
    timetable_status = str(timetable_record.get("status") or "")
    suffix = f" | timetable:{timetable_status}" if timetable_status and timetable_status != "pending" else ""
    print(f"[{index}] {record['status']} | {case_id}{suffix}")
    return {**record, "derived": {"timetable": timetable_record}}


def train_model(
    layout: ProjectLayout,
    *,
    model_id: str,
    scenario_set_id: str,
    max_slots: int = DEFAULT_MAX_SLOTS,
    event_time_window: int = DEFAULT_EVENT_TIME_WINDOW,
    event_top_k: int = DEFAULT_EVENT_TOP_K,
    section_order_window: int = DEFAULT_SECTION_ORDER_WINDOW,
    hidden_dim: int = 64,
    latent_dim: int = 16,
    message_passing_steps: int = 2,
    epochs: int = 800,
    checkpoint_every: int = 5,
    batch_size: int = 8,
    lr: float = 0.0003,
    seed: int = 1,
    device: str = "auto",
    log_every: int = 1,
    count_weight: float = 1.0,
    anchor_weight: float = 1.0,
    param_weight: float = 2.0,
    kl_weight: float = 0.0015,
    use_relation_graph: bool = DEFAULT_USE_RELATION_GRAPH,
    relation_weight: float = 0.5,
) -> None:
    scenario_set_id = sanitize_id(scenario_set_id)
    model_id = sanitize_id(model_id)
    model = layout.model(model_id)
    docs = load_scenario_set(layout, scenario_set_id)
    validate_scenario_documents(layout, docs)
    if model.root.exists():
        reset_dir(model.root)
    model.root.mkdir(parents=True, exist_ok=True)
    export_training_graphs(
        layout,
        model,
        scenario_set_id,
        docs=docs,
        graph_settings={
            "max_slots": max_slots,
            "event_time_window": event_time_window,
            "event_top_k": event_top_k,
            "section_order_window": section_order_window,
            "use_relation_graph": use_relation_graph,
        },
    )

    run(
        [
            sys.executable,
            "scripts/train_vae.py",
            "--graphs-root",
            to_posix(model.graph_dir),
            "--output-dir",
            to_posix(model.root),
            "--hidden-dim",
            str(hidden_dim),
            "--latent-dim",
            str(latent_dim),
            "--message-passing-steps",
            str(message_passing_steps),
            "--epochs",
            str(epochs),
            "--checkpoint-every",
            str(checkpoint_every),
            "--batch-size",
            str(batch_size),
            "--lr",
            str(lr),
            "--seed",
            str(seed),
            "--device",
            device,
            "--log-every",
            str(log_every),
            "--count-weight",
            str(count_weight),
            "--anchor-weight",
            str(anchor_weight),
            "--param-weight",
            str(param_weight),
            "--kl-weight",
            str(kl_weight),
            *relation_graph_cli_args(use_relation_graph),
            "--relation-weight",
            str(relation_weight),
        ]
    )
    print(f"Model trained: {model.root}")


def generate_scenarios(
    layout: ProjectLayout,
    *,
    model_id: str,
    checkpoint: str,
    scenario_set_id: str,
    source_scenario_set_id: str = "",
    run_graph: RunGraphReference | None = None,
    output_prefix: str = "generated",
    num_samples: int,
    seed: int,
    device: str,
    speed_interruption_threshold: float,
    overwrite: bool,
) -> None:
    num_samples = max(1, int(num_samples))
    model = layout.model(model_id)
    checkpoint_path = model_checkpoint_path(model.root, checkpoint)
    output_root = layout.scenario_set(scenario_set_id).root
    target_cases = generation_target_cases(layout, scenario_set_id, output_prefix, num_samples)
    existing_targets = [case.scenario_yml for _scenario_id, case in target_cases if case.scenario_yml.exists()]
    if existing_targets and not overwrite:
        raise FileExistsError(f"Generated scenario already exists: {existing_targets[0]}")

    source_set_id = sanitize_id(source_scenario_set_id)
    if bool(source_set_id) == bool(run_graph):
        raise ValueError("Generation requires exactly one context source: scenario category or run graph.")

    tmp_root = layout.root / ".tmp" / f"generation_{sanitize_id(scenario_set_id)}_{datetime.now():%Y%m%d_%H%M%S_%f}"
    context_graph_root = tmp_root / "context_graphs"
    generation_run = tmp_root / "decode"
    try:
        graph_settings = generation_graph_settings(model)
        if run_graph is not None:
            source_context_path = resolve_run_graph_context(layout, run_graph)
            prepare_output_dir(context_graph_root, overwrite=True)
            contexts_dir = context_graph_root / "contexts"
            contexts_dir.mkdir(parents=True, exist_ok=True)
            write_generation_context_graph(
                load_base_context(source_context_path),
                source_context_path,
                contexts_dir / "run_graph_source.json",
                graph_settings=graph_settings,
                source_config_path="",
            )
            source_records = [
                {
                    "index": index,
                    "scenario_id": "",
                    "run_graph": run_graph,
                    "context_path": source_context_path.resolve(),
                    "scenario_path": None,
                }
                for index in range(1, num_samples + 1)
            ]
        else:
            source_records = export_generation_context_graphs(
                layout,
                source_set_id,
                context_graph_root,
                num_samples=num_samples,
                seed=seed,
                graph_settings=graph_settings,
            )
            validate_generation_targets_do_not_replace_sources(target_cases, source_records)
        run(
            [
                sys.executable,
                "scripts/generate_vae.py",
                "--context-graphs",
                to_posix(context_graph_root),
                "--checkpoint",
                to_posix(checkpoint_path),
                "--num-samples",
                str(num_samples),
                "--seed",
                str(seed),
                "--device",
                device,
                "--output-dir",
                to_posix(generation_run),
            ]
        )
        graph_paths = sorted((generation_run / "math_graphs").glob("*.json"))
        if len(graph_paths) != num_samples:
            raise RuntimeError(f"Generation produced {len(graph_paths)} graph(s), expected {num_samples}.")
        decoded_outputs: List[Dict[str, object]] = []
        for (scenario_id, target), graph_path in zip(target_cases, graph_paths):
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            base_context_path = str(graph.get("decode_handle", {}).get("base_context_path", ""))
            if not base_context_path:
                raise ValueError(f"Generated graph missing decode_handle.base_context_path: {graph_path}")
            source_context_path = Path(base_context_path)
            context = load_base_context(source_context_path)
            disturbance_graph = typed_generated_graph_to_disturbance_graph(
                graph,
                context,
                speed_interruption_threshold=speed_interruption_threshold,
            )
            scenarios = disturbance_graph_to_scenario(disturbance_graph, context)
            decoded_outputs.append(
                {
                    "target": target,
                    "scenario_id": scenario_id,
                    "scenarios": scenarios,
                    "run_graph": source_run_graph_for_context(source_records, source_context_path),
                }
            )
        for record in decoded_outputs:
            write_generated_scenario(
                record["target"],
                str(record["scenario_id"]),
                record["scenarios"],
                run_graph=record["run_graph"],
                overwrite=overwrite,
            )
        print(f"Generated and decoded {len(graph_paths)} scenarios: {output_root}")
    finally:
        if tmp_root.exists():
            reset_dir(tmp_root)


def generation_target_cases(
    layout: ProjectLayout,
    scenario_set_id: str,
    output_prefix: str,
    num_samples: int,
) -> List[tuple[str, Any]]:
    return [
        (
            sanitize_id(f"{output_prefix}_{index:04d}"),
            layout.scenario_set(scenario_set_id).scenario(f"{output_prefix}_{index:04d}"),
        )
        for index in range(1, num_samples + 1)
    ]


def write_generated_scenario(
    target: Any,
    scenario_id: str,
    scenarios: ScenarioConfig,
    *,
    run_graph: RunGraphReference,
    overwrite: bool,
) -> None:
    if target.scenario_yml.exists():
        if not overwrite:
            raise FileExistsError(f"Generated scenario already exists: {target.scenario_yml}")
        target.scenario_yml.unlink()
    write_yaml(target.scenario_yml, scenario_config_to_yaml(scenarios, run_graph))


def source_run_graph_for_context(records: List[Dict[str, object]], context_path: Path) -> RunGraphReference:
    resolved = context_path.resolve()
    for record in records:
        if Path(record["context_path"]).resolve() == resolved:
            run_graph = record.get("run_graph")
            if isinstance(run_graph, RunGraphReference):
                return run_graph
    raise ValueError(f"Generated graph context is not from a known run graph: {context_path}")


def generation_graph_settings(model: Any) -> Dict[str, object]:
    config = read_json_if_exists(model.root / "training_config.json")
    if "use_relation_graph" not in config:
        raise ValueError("Model training_config.json is missing use_relation_graph; retrain the model.")
    return {
        "max_slots": int(config.get("max_slots", DEFAULT_MAX_SLOTS) or DEFAULT_MAX_SLOTS),
        "event_time_window": int(config.get("event_time_window", DEFAULT_EVENT_TIME_WINDOW) or DEFAULT_EVENT_TIME_WINDOW),
        "event_top_k": int(config.get("event_top_k", DEFAULT_EVENT_TOP_K) or DEFAULT_EVENT_TOP_K),
        "section_order_window": int(
            config.get("section_order_window", DEFAULT_SECTION_ORDER_WINDOW) or DEFAULT_SECTION_ORDER_WINDOW
        ),
        "use_relation_graph": graph_setting_bool(config["use_relation_graph"]),
    }


def graph_setting_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def relation_graph_cli_args(use_relation_graph: bool) -> List[str]:
    return ["--use-relation-graph"] if use_relation_graph else ["--no-relation-graph"]


def export_generation_context_graphs(
    layout: ProjectLayout,
    scenario_set_id: str,
    output_dir: Path,
    *,
    num_samples: int,
    seed: int,
    graph_settings: Dict[str, object],
) -> List[Dict[str, object]]:
    docs = load_scenario_set(layout, scenario_set_id)
    validate_scenario_documents(layout, docs)
    prepare_output_dir(output_dir, overwrite=True)
    contexts_dir = output_dir / "contexts"
    contexts_dir.mkdir(parents=True, exist_ok=True)
    selected_docs = sample_generation_source_documents(docs, num_samples=num_samples, seed=seed)
    records: List[Dict[str, object]] = []
    for index, doc in enumerate(selected_docs, start=1):
        if doc.path is None:
            raise ValueError(f"Scenario document path is required: {doc.name}")
        context_path = resolve_run_graph_context(layout, doc.run_graph)
        write_generation_context_graph(
            load_base_context(context_path),
            context_path,
            contexts_dir / f"sample_{index:06d}.json",
            graph_settings=graph_settings,
            source_config_path=to_posix(doc.path),
        )
        records.append(
            {
                "index": index,
                "scenario_id": sanitize_id(doc.name),
                "run_graph": doc.run_graph,
                "context_path": context_path.resolve(),
                "scenario_path": doc.path.resolve(),
            }
        )
    print(f"Generation context graphs exported: {output_dir} ({len(records)} sampled context(s))")
    return records


def sample_generation_source_documents(
    docs: List[ScenarioDocument],
    *,
    num_samples: int,
    seed: int,
) -> List[ScenarioDocument]:
    if not docs:
        raise ValueError("Generation source scenario category is empty.")
    rng = random.Random(seed)
    return [rng.choice(docs) for _ in range(num_samples)]


def validate_generation_targets_do_not_replace_sources(
    target_cases: List[tuple[str, Any]],
    source_records: List[Dict[str, object]],
) -> None:
    source_paths = {
        Path(record["scenario_path"]).resolve()
        for record in source_records
        if record.get("scenario_path") is not None
    }
    for _scenario_id, target in target_cases:
        if target.scenario_yml.resolve() in source_paths:
            raise ValueError(f"Generated target would replace its source scenario: {target.scenario_yml}")


def write_generation_context_graph(
    base_context: BaseContext,
    base_context_path: Path,
    output_path: Path,
    *,
    graph_settings: Dict[str, object],
    source_config_path: str = "",
) -> None:
    typed = scenario_config_to_typed_vae_learning_graph(
        ScenarioConfig(delays=[], speed_limits=[]),
        base_context,
        base_context_path=to_posix(base_context_path),
        source_config_path=source_config_path,
        max_slots=int(graph_settings.get("max_slots", DEFAULT_MAX_SLOTS)),
        event_time_window=int(graph_settings.get("event_time_window", DEFAULT_EVENT_TIME_WINDOW)),
        event_top_k=int(graph_settings.get("event_top_k", DEFAULT_EVENT_TOP_K)),
        section_order_window=int(graph_settings.get("section_order_window", DEFAULT_SECTION_ORDER_WINDOW)),
        use_relation_graph=graph_setting_bool(graph_settings["use_relation_graph"]),
    )
    write_json(output_path, typed_learning_graph_to_math_context_graph(typed))


def export_training_graphs(
    layout: ProjectLayout,
    model: Any,
    scenario_set_id: str,
    *,
    docs: List[ScenarioDocument] | None = None,
    graph_settings: Dict[str, object],
) -> None:
    reset_dir(model.graph_dir)
    model.sample_dir.mkdir(parents=True, exist_ok=True)
    model.context_graph_dir.mkdir(parents=True, exist_ok=True)
    docs = docs if docs is not None else load_scenario_set(layout, scenario_set_id)
    validate_scenario_documents(layout, docs)
    total = len(docs)
    write_graph_progress(
        model,
        global_graph_status="running",
        sample_graph_status="pending",
        sample_total=total,
        sample_completed=0,
    )

    first_context_graph: Dict[str, object] | None = None
    samples: List[Dict[str, object]] = []
    sample_records: List[Dict[str, object]] = []

    for index, doc in enumerate(docs, start=1):
        if doc.path is None:
            raise ValueError(f"Scenario document path is required: {doc.name}")
        scenario_context_path = resolve_run_graph_context(layout, doc.run_graph)
        context_path = model.context_graph_dir / f"{sanitize_id(doc.name)}.json"
        sample_path = model.sample_dir / f"{sanitize_id(doc.name)}.json"
        run(
            [
                sys.executable,
                "core_cli.py",
                "export-vae-case-graph",
                "--context",
                to_posix(scenario_context_path),
                "--scenario",
                to_posix(doc.path),
                "--context-output",
                to_posix(context_path),
                "--sample-output",
                to_posix(sample_path),
                "--max-slots",
                str(int(graph_settings.get("max_slots", DEFAULT_MAX_SLOTS))),
                "--event-time-window",
                str(int(graph_settings.get("event_time_window", DEFAULT_EVENT_TIME_WINDOW))),
                "--event-top-k",
                str(int(graph_settings.get("event_top_k", DEFAULT_EVENT_TOP_K))),
                "--section-order-window",
                str(int(graph_settings.get("section_order_window", DEFAULT_SECTION_ORDER_WINDOW))),
                *relation_graph_cli_args(
                    graph_setting_bool(graph_settings["use_relation_graph"])
                ),
            ]
        )
        context = read_json(context_path)
        sample = read_json(sample_path)
        if first_context_graph is None:
            first_context_graph = context
            write_graph_progress(
                model,
                global_graph_status="done",
                sample_graph_status="running",
                sample_total=total,
                sample_completed=0,
            )
        samples.append(sample)
        sample_records.append(
            {
                "learning_sample_path": to_posix(sample_path),
                "context_graph_path": to_posix(context_path),
                "source_scenario_path": to_posix(doc.path or Path(doc.name)),
            }
        )
        write_graph_progress(
            model,
            global_graph_status="done",
            sample_graph_status="running",
            sample_total=total,
            sample_completed=index,
        )

    if first_context_graph is None:
        raise ValueError(f"No scenarios found for training: {scenario_set_id}")
    _inferred_context, inferred_schema = infer_math_dataset_schema(first_context_graph, samples)
    write_json(
        model.graph_dir / "dataset_profile.json",
        math_context_graph_to_dataset_profile(
            first_context_graph,
            samples=sample_records,
            inferred_schema=inferred_schema,
            export_profile=dict(graph_settings),
        ),
    )
    write_graph_progress(
        model,
        global_graph_status="done",
        sample_graph_status="done",
        sample_total=total,
        sample_completed=total,
    )


def math_context_graph_to_dataset_profile(
    context_graph: Dict[str, object],
    *,
    samples: List[Dict[str, object]],
    inferred_schema: Dict[str, object],
    export_profile: Dict[str, object],
) -> Dict[str, object]:
    rules = context_graph.get("rules", {})
    pools = list(dict(rules).get("pools", [])) if isinstance(rules, dict) else []
    tasks = list(dict(rules).get("tasks", [])) if isinstance(rules, dict) else []
    relation_feature_dim = int(dict(rules).get("target_relation_feature_dim", 0) or 0) if isinstance(rules, dict) else 0
    if "use_relation_graph" not in export_profile:
        raise ValueError("Dataset export_profile is missing use_relation_graph.")
    use_relation_graph = graph_setting_bool(export_profile["use_relation_graph"])
    if use_relation_graph != (relation_feature_dim > 0):
        raise ValueError("Dataset relation graph setting does not match target_relation_feature_dim.")
    return {
        "schema_version": context_graph.get("schema_version", 1),
        "graph_type": "vae_math_dataset_profile",
        "math_context_graph_type": "vae_math_context_graph",
        "math_learning_sample_type": "vae_math_learning_sample",
        "base_context_path": str(context_graph.get("decode_handle", {}).get("base_context_path", ""))
        if isinstance(context_graph.get("decode_handle"), dict)
        else "",
        "export_profile": dict(export_profile),
        "type_system": {},
        "relation_graph": {
            "enabled": use_relation_graph,
            "target_relation_feature_dim": relation_feature_dim,
        },
        "pools": {
            str(item.get("pool_id")): {
                "size": item.get("size"),
                "feature_dim": item.get("feature_dim"),
            }
            for item in pools
            if isinstance(item, dict)
        },
        "tasks": tasks,
        "inferred_schema": dict(inferred_schema),
        "decode_contract": {},
        "samples": list(samples),
    }


def write_graph_progress(
    model: Any,
    *,
    global_graph_status: str,
    sample_graph_status: str,
    sample_total: int,
    sample_completed: int,
) -> None:
    write_json(
        model.graph_progress,
        {
            "global_graph": {"status": global_graph_status},
            "sample_graphs": {
                "status": sample_graph_status,
                "total": sample_total,
                "completed": sample_completed,
            },
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def require_project(layout: ProjectLayout) -> None:
    if not layout.root.is_dir():
        raise FileNotFoundError(f"Project not found: {layout.root}")


def model_checkpoint_path(model_root: Path, checkpoint: str) -> Path:
    if not checkpoint.strip():
        raise ValueError("Checkpoint is required.")
    path = (model_root / checkpoint).resolve()
    root = model_root.resolve()
    if root not in path.parents:
        raise ValueError(f"Checkpoint must be inside model directory: {checkpoint}")
    if path.suffix != ".pt":
        raise ValueError(f"Checkpoint must be a .pt file: {checkpoint}")
    if not path.is_file():
        raise FileNotFoundError(f"Checkpoint not found: {path}")
    return path


def load_scenario_set(layout: ProjectLayout, scenario_set_id: str) -> List[ScenarioDocument]:
    root = layout.scenario_set(scenario_set_id).root
    if not root.is_dir():
        raise FileNotFoundError(f"Scenario set not found: {root}")
    yaml = require_yaml()
    docs = [load_scenario_document(path, yaml) for path in scenario_files(root)]
    if not docs:
        raise FileNotFoundError(f"No scenario YAML files found: {root}")
    return docs


def load_scenario_documents(
    layout: ProjectLayout,
    scenario_set_id: str,
    *,
    scenario_id: str = "",
) -> List[ScenarioDocument]:
    if not scenario_id:
        return load_scenario_set(layout, scenario_set_id)
    root = layout.scenario_set(scenario_set_id).root
    if not root.is_dir():
        raise FileNotFoundError(f"Scenario set not found: {root}")
    path = scenario_file_by_id(root, scenario_id)
    if path is None:
        raise FileNotFoundError(f"Scenario not found in {root}: {sanitize_id(scenario_id)}")
    return [load_scenario_document(path, require_yaml())]


def validate_scenario_documents(layout: ProjectLayout, docs: List[ScenarioDocument]) -> None:
    missing = []
    failed = []
    for doc in docs:
        if doc.path is None:
            missing.append(doc.name)
            continue
        try:
            context = load_base_context(resolve_run_graph_context(layout, doc.run_graph))
            parse_scenario_config(
                {
                    "delays": doc.scenarios.get("delays", []) or [],
                    "speed_limits": doc.scenarios.get("speed_limits", []) or [],
                },
                context,
            )
        except Exception as exc:
            failed.append(f"{doc.name}: {exc}")
    if missing:
        names = ", ".join(sanitize_id(name) for name in missing[:10])
        raise FileNotFoundError(f"Scenario file path is required before batch execution: {names}")
    if failed:
        names = "; ".join(failed[:5])
        raise ValueError(f"Scenario validation failed before batch execution: {names}")


def default_build_config() -> Dict[str, object]:
    return {
        "objective_delay_weight": 1.0,
        "objective_mode": "abs",
        "cancellation_enabled": False,
        "cancellation_penalty_weight": 1000.0,
        "arr_arr_headway_seconds": 180,
        "dep_dep_headway_seconds": 180,
        "dwell_seconds_at_stops": 120,
        "big_m": 100000,
        "tolerance_delay_seconds": 7200,
    }


def prepare_output_dir(path: Path, *, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists, set overwrite: true or pass --overwrite: {path}")
        reset_dir(path)
    path.mkdir(parents=True, exist_ok=True)


def limit_items(items: List[Any], limit: int) -> List[Any]:
    return items[:limit] if limit and limit > 0 else items


def plan_case_dirs(plan: Any) -> List[Path]:
    root = plan.cases_dir
    if not root.is_dir():
        raise FileNotFoundError(f"Adjustment plan cases not found: {root}")
    case_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    if not case_dirs:
        raise FileNotFoundError(f"No cases found in adjustment plan: {root}")
    return case_dirs


def plan_case_dir(plan: Any, case_id: str) -> Path:
    case_dir = plan.cases_dir / sanitize_id(case_id)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Adjustment plan case not found: {case_dir}")
    return case_dir


def base_record(index: int, case_id: str) -> Dict[str, object]:
    return {
        "index": index,
        "case_id": case_id,
        "status": "pending",
        "error": "",
        "duration_sec": 0.0,
    }


def read_case_stage_records(cases_dir: Path, filename: str) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    if not cases_dir.is_dir():
        return records
    for path in sorted(cases_dir.glob(f"*/{filename}")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            records.append(dict(payload["result"]))
    return records


def fail_if_records_failed(records: Iterable[Dict[str, object]], stage: str) -> None:
    failed = [record for record in records if record.get("status") == "failed"]
    if failed:
        raise RuntimeError(f"{stage} failed for {len(failed)} case(s). First failure: {record_error(failed[0])}")


def fail_if_derived_records_failed(records: Iterable[Dict[str, object]], key: str, stage: str) -> None:
    failed: List[Dict[str, object]] = []
    for record in records:
        derived = record.get("derived")
        if not isinstance(derived, dict):
            continue
        item = derived.get(key)
        if isinstance(item, dict) and item.get("status") == "failed":
            failed.append(item)
    if failed:
        raise RuntimeError(f"{stage} failed for {len(failed)} case(s). First failure: {record_error(failed[0])}")


def record_error(record: Dict[str, object]) -> str:
    case_id = str(record.get("case_id") or "unknown")
    error = str(record.get("error") or "").strip()
    return f"{case_id}: {error}" if error else case_id


def write_yaml(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(require_yaml().safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json_if_exists(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_json(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def run(cmd: List[str]) -> None:
    if cmd and Path(cmd[0]).name.startswith("python") and "-u" not in cmd[1:2]:
        cmd = [cmd[0], "-u", *cmd[1:]]
    print(" ".join(cmd))
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env)


def seconds_to_hms(seconds: int) -> str:
    total = max(0, min(24 * 3600 - 1, int(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def elapsed_seconds(started: datetime) -> float:
    return round((datetime.now() - started).total_seconds(), 3)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml

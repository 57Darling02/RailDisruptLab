from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from core.base_context import build_base_context, load_base_context, write_base_context
from core.disturbance_graph import disturbance_graph_to_scenario
from core.file_ops import copy_or_link_file
from core.loader import load_mileage_table, load_timetable
from core.project_layout import ProjectLayout, REPO_ROOT, reset_dir, sanitize_id, to_posix
from core.scenario_config import (
    ScenarioDocument,
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
    infer_math_dataset_schema,
    scenario_config_to_typed_vae_learning_graph,
    typed_generated_graph_to_disturbance_graph,
    typed_learning_graph_to_math_context_graph,
)


def new_project(layout: ProjectLayout) -> None:
    for directory in (
        layout.scenario_sets_dir,
        layout.datasets_dir,
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


def create_dataset(layout: ProjectLayout, dataset_id: str, *, exist_ok: bool = False) -> None:
    require_project(layout)
    root = layout.dataset(dataset_id).root
    if root.exists():
        if not root.is_dir():
            raise NotADirectoryError(f"Dataset path is not a directory: {root}")
        if not exist_ok:
            raise FileExistsError(f"Dataset already exists: {root}")
    else:
        root.mkdir(parents=True, exist_ok=False)
    print(f"MILP dataset ready: {root}")


def build_dataset(
    layout: ProjectLayout,
    scenario_set_id: str,
    dataset_id: str,
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
    require_activated_scenarios(docs)
    dataset = layout.dataset(dataset_id)
    if dataset.root.exists() and not dataset.root.is_dir():
        raise NotADirectoryError(f"MILP dataset path is not a directory: {dataset.root}")
    if not dataset.root.is_dir():
        dataset.root.mkdir(parents=True, exist_ok=False)
    prepare_output_dir(dataset.root, overwrite=True)

    for index, doc in enumerate(docs, start=1):
        started = datetime.now()
        case_id = sanitize_id(doc.name)
        case_dir = dataset.cases_dir / case_id
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
            write_yaml(case_dir / "scenario.yml", scenario_document_to_yaml(case_id, doc))
            if doc.path is None:
                raise ValueError(f"Scenario document path is required: {doc.name}")
            copy_or_link_file(doc.path.parent / "context.json", case_dir / "context.json")
            run(
                [
                    sys.executable,
                    "core_cli.py",
                    "build-milp-case",
                    "--context",
                    to_posix(case_dir / "context.json"),
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

    fail_if_records_failed(read_case_stage_records(dataset.cases_dir, "build.json"), "build")
    print(f"Dataset built: {dataset.root}")


def solve_dataset(
    layout: ProjectLayout,
    dataset_id: str,
    *,
    case_id: str = "",
    limit: int = 0,
    time_limit: float = 120.0,
    mip_gap: float = 0.0,
    threads: int = 0,
    skip_solved: bool = False,
) -> None:
    dataset = layout.dataset(dataset_id)
    case_dirs = [dataset_case_dir(dataset, case_id)] if case_id else limit_items(dataset_case_dirs(dataset), limit)
    records = [
        solve_case(
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
    ok_count = sum(1 for record in records if record.get("status") in {"ok", "timeout", "skipped"})
    print(f"Solve finished: {ok_count}/{len(records)} case(s)")


def solve_case(
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
    record = base_record(index, case_id)
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
                "summary": to_posix(summary_path),
            },
        },
    )
    print(f"[{index}] {record['status']} | {case_id}")
    return record


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
    batch_size: int = 8,
    lr: float = 0.0003,
    seed: int = 1,
    device: str = "auto",
    log_every: int = 1,
    count_weight: float = 1.0,
    anchor_weight: float = 1.0,
    param_weight: float = 2.0,
    kl_weight: float = 0.0015,
    relation_weight: float = 0.5,
) -> None:
    scenario_set_id = sanitize_id(scenario_set_id)
    model_id = sanitize_id(model_id)
    model = layout.model(model_id)
    docs = load_scenario_set(layout, scenario_set_id)
    require_activated_scenarios(docs)
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
    source_timetable_path: str = "",
    source_mileage_path: str = "",
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
    existing_targets = [case.root for _scenario_id, case in target_cases if case.root.exists()]
    if existing_targets and not overwrite:
        raise FileExistsError(f"Generated scenario already exists: {existing_targets[0]}")

    source_set_id = sanitize_id(source_scenario_set_id)
    source_timetable_path = source_timetable_path.strip()
    source_mileage_path = source_mileage_path.strip()
    has_upload_source = bool(source_timetable_path or source_mileage_path)
    if bool(source_set_id) == has_upload_source:
        raise ValueError("Generation requires exactly one context source: scenario category or uploaded source files.")

    tmp_root = layout.root / ".tmp" / f"generation_{sanitize_id(scenario_set_id)}_{datetime.now():%Y%m%d_%H%M%S_%f}"
    context_graph_root = tmp_root / "context_graphs"
    generation_run = tmp_root / "decode"
    try:
        graph_settings = generation_graph_settings(model)
        if has_upload_source:
            export_uploaded_generation_context_graph(
                layout,
                source_timetable_path=source_timetable_path,
                source_mileage_path=source_mileage_path,
                context_path=tmp_root / "source_context" / "context.json",
                output_dir=context_graph_root,
                graph_settings=graph_settings,
            )
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
            require_generation_source_files(source_context_path)
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
                    "source_context_path": source_context_path,
                }
            )
        for record in decoded_outputs:
            write_generated_scenario(
                record["target"],
                str(record["scenario_id"]),
                record["scenarios"],
                source_context_path=Path(record["source_context_path"]),
                overwrite=overwrite,
            )
        print(f"Generated and decoded {len(graph_paths)} scenarios: {output_root}")
    finally:
        if tmp_root.exists():
            reset_dir(tmp_root)
        cleanup_generation_uploads(source_timetable_path, source_mileage_path, project_root=layout.root)


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
    source_context_path: Path,
    overwrite: bool,
) -> None:
    if target.root.exists():
        if not overwrite:
            raise FileExistsError(f"Generated scenario already exists: {target.root}")
        reset_dir(target.root)
    created = False
    try:
        target.root.mkdir(parents=True, exist_ok=False)
        created = True
        copy_generation_source_files(source_context_path, target.source_dir)
        copy_generation_context(source_context_path, target.context_json)
        write_yaml(target.scenario_yml, scenario_config_to_yaml(scenario_id, scenarios))
    except Exception:
        if created and target.root.exists():
            reset_dir(target.root)
        raise


def copy_generation_source_files(context_path: Path, target_source_dir: Path) -> None:
    timetable_path, mileage_path = require_generation_source_files(context_path)
    target_source_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(timetable_path, target_source_dir / "timetable.xlsx")
    shutil.copy2(mileage_path, target_source_dir / "mileage.xlsx")


def require_generation_source_files(context_path: Path) -> tuple[Path, Path]:
    context = load_base_context(context_path)
    timetable_path = Path(context.source_timetable_path)
    mileage_path = Path(context.source_mileage_path)
    if not timetable_path.is_file():
        raise FileNotFoundError(f"Generation source timetable not found: {timetable_path}")
    if not mileage_path.is_file():
        raise FileNotFoundError(f"Generation source mileage table not found: {mileage_path}")
    return timetable_path, mileage_path


def copy_generation_context(source_context_path: Path, target_context_path: Path) -> None:
    source = load_base_context(source_context_path)
    target_context = replace(
        source,
        source_timetable_path=target_context_path.parent / "source" / "timetable.xlsx",
        source_mileage_path=target_context_path.parent / "source" / "mileage.xlsx",
    )
    write_base_context(
        target_context,
        target_context_path,
        metadata={
            "id": sanitize_id(target_context_path.parent.name),
            "timetable_filename": "timetable.xlsx",
            "mileage_filename": "mileage.xlsx",
            "timetable_sheet_name": target_context.timetable_sheet_name,
            "mileage_sheet_name": target_context.mileage_sheet_name,
        },
    )


def generation_graph_settings(model: Any) -> Dict[str, object]:
    config = read_json_if_exists(model.root / "training_config.json")
    return {
        "max_slots": int(config.get("max_slots", DEFAULT_MAX_SLOTS) or DEFAULT_MAX_SLOTS),
        "event_time_window": int(config.get("event_time_window", DEFAULT_EVENT_TIME_WINDOW) or DEFAULT_EVENT_TIME_WINDOW),
        "event_top_k": int(config.get("event_top_k", DEFAULT_EVENT_TOP_K) or DEFAULT_EVENT_TOP_K),
        "section_order_window": int(
            config.get("section_order_window", DEFAULT_SECTION_ORDER_WINDOW) or DEFAULT_SECTION_ORDER_WINDOW
        ),
    }


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
    require_activated_scenarios(docs)
    prepare_output_dir(output_dir, overwrite=True)
    contexts_dir = output_dir / "contexts"
    contexts_dir.mkdir(parents=True, exist_ok=True)
    selected_docs = sample_generation_source_documents(docs, num_samples=num_samples, seed=seed)
    records: List[Dict[str, object]] = []
    for index, doc in enumerate(selected_docs, start=1):
        if doc.path is None:
            raise ValueError(f"Scenario document path is required: {doc.name}")
        context_path = doc.path.parent / "context.json"
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
                "scenario_root": doc.path.parent.resolve(),
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
    source_roots = {
        record["scenario_root"]
        for record in source_records
        if isinstance(record.get("scenario_root"), Path)
    }
    for _scenario_id, target in target_cases:
        if target.root.resolve() in source_roots:
            raise ValueError(f"Generated target would replace its source scenario: {target.root}")


def export_uploaded_generation_context_graph(
    layout: ProjectLayout,
    *,
    source_timetable_path: str,
    source_mileage_path: str,
    context_path: Path,
    output_dir: Path,
    graph_settings: Dict[str, object],
) -> None:
    timetable_path = generation_task_upload_path(layout, source_timetable_path, "source_timetable_path")
    mileage_path = generation_task_upload_path(layout, source_mileage_path, "source_mileage_path")
    if not timetable_path.is_file():
        raise FileNotFoundError(f"Timetable not found in project source: {timetable_path}")
    if not mileage_path.is_file():
        raise FileNotFoundError(f"Mileage table not found in project source: {mileage_path}")
    context = build_base_context(
        timetable_path=timetable_path,
        mileage_path=mileage_path,
        timetable_sheet_name="Sheet1",
        mileage_sheet_name="Sheet1",
        timetable_table=load_timetable(timetable_path, "Sheet1"),
        mileage_table=load_mileage_table(mileage_path, "Sheet1"),
    )
    write_base_context(
        context,
        context_path,
        metadata={
            "id": "generation_source",
            "timetable_filename": timetable_path.name,
            "mileage_filename": mileage_path.name,
            "timetable_sheet_name": "Sheet1",
            "mileage_sheet_name": "Sheet1",
        },
    )
    prepare_output_dir(output_dir, overwrite=True)
    contexts_dir = output_dir / "contexts"
    contexts_dir.mkdir(parents=True, exist_ok=True)
    write_generation_context_graph(
        context,
        context_path,
        contexts_dir / "uploaded_source.json",
        graph_settings=graph_settings,
    )
    print(f"Uploaded generation context graph exported: {output_dir}")


def generation_task_upload_path(layout: ProjectLayout, path_text: str, key: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError(f"{key} must be an absolute task upload path.")
    root = (layout.root / ".tmp" / "uploads").resolve()
    resolved = path.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"{key} must be under project .tmp/uploads/: {path}")
    return resolved


def cleanup_generation_uploads(*path_texts: str, project_root: Path) -> None:
    upload_root = (project_root / ".tmp" / "uploads").resolve()
    parents = set()
    for path_text in path_texts:
        if not path_text.strip():
            continue
        resolved = Path(path_text).resolve()
        if upload_root in resolved.parents:
            parents.add(resolved.parent)
    for parent in parents:
        if parent.exists():
            reset_dir(parent)


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
    require_activated_scenarios(docs)
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
        scenario_context_path = doc.path.parent / "context.json"
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


def require_activated_scenarios(docs: List[ScenarioDocument]) -> None:
    missing = []
    for doc in docs:
        if doc.path is None:
            missing.append(doc.name)
            continue
        if not (doc.path.parent / "context.json").is_file():
            missing.append(doc.name)
    if missing:
        names = ", ".join(sanitize_id(name) for name in missing[:10])
        raise FileNotFoundError(f"Scenario context is required before batch execution: {names}")


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


def dataset_case_dirs(dataset: Any) -> List[Path]:
    root = dataset.cases_dir
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset cases not found: {root}")
    case_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    if not case_dirs:
        raise FileNotFoundError(f"No cases found in dataset: {root}")
    return case_dirs


def dataset_case_dir(dataset: Any, case_id: str) -> Path:
    case_dir = dataset.cases_dir / sanitize_id(case_id)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Dataset case not found: {case_dir}")
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

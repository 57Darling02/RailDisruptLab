from __future__ import annotations

import csv
import json
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from core.base_context import build_base_context, load_base_context, write_base_context
from core.builder import build_model
from core.disturbance_graph import disturbance_graph_to_scenario
from core.exporter import export_lp
from core.loader import load_config_payload, load_mileage_table, load_timetable
from core.postprocess import export_adjusted_timetable
from core.project_layout import ProjectLayout, REPO_ROOT, reset_dir, sanitize_id, to_posix
from core.scenario_config import ScenarioDocument, load_scenario_document, scenario_files
from core.solver import GurobiSolveError, load_solution_values, solve_lp
from core.types import AppConfig, ScenarioConfig
from core.vae_learning_graph import (
    DEFAULT_EVENT_TIME_WINDOW,
    DEFAULT_EVENT_TOP_K,
    DEFAULT_MAX_SLOTS,
    DEFAULT_SECTION_ORDER_WINDOW,
    DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
    infer_math_dataset_schema,
    scenario_to_typed_vae_learning_graph,
    typed_generated_graph_to_disturbance_graph,
    typed_learning_graph_to_dataset_profile,
    typed_learning_graph_to_math_context_graph,
    typed_learning_graph_to_math_learning_sample,
)


def new_project(layout: ProjectLayout) -> None:
    for directory in (
        layout.source_dir,
        layout.default_scenario_set,
        layout.datasets_dir,
        layout.conf_dir / "normal_generate",
        layout.conf_dir / "train",
        layout.model_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    write_yaml_if_missing(
        layout.prepare_config,
        {
            "timetable_filename": "",
            "mileage_filename": "",
            "timetable_sheet_name": "Sheet1",
            "mileage_sheet_name": "Sheet1",
        },
    )
    write_yaml_if_missing(
        layout.normal_generate_config("default"),
        {
            "scenario_set_id": "",
            "overwrite": False,
            "seed": 20260320,
            "delay_count": 10,
            "speed_count": 10,
            "interruption_count": 10,
            "combo_per_type": 10,
        },
    )
    write_yaml_if_missing(layout.solve_config, default_solve_config())
    write_yaml_if_missing(
        layout.analyze_config,
        {
            "enable_metrics": True,
            "enable_plot": True,
            "plot_grid": True,
            "adj_timetable_sheet_name": "Sheet1",
        },
    )
    write_yaml_if_missing(
        layout.train_config("default"),
        {
            "scenario_set_id": "",
            "model_id": "",
            "data": {
                "limit": 0,
                "max_slots": DEFAULT_MAX_SLOTS,
                "event_time_window": DEFAULT_EVENT_TIME_WINDOW,
                "event_top_k": DEFAULT_EVENT_TOP_K,
                "section_order_window": DEFAULT_SECTION_ORDER_WINDOW,
                "speed_interruption_threshold": DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
            },
            "model": {
                "hidden_dim": 64,
                "latent_dim": 16,
                "message_passing_steps": 2,
            },
            "optimization": {
                "epochs": 800,
                "batch_size": 8,
                "lr": 0.0003,
                "seed": 1,
                "device": "auto",
                "log_every": 1,
            },
            "loss_weights": {
                "count": 1.0,
                "anchor": 1.0,
                "param": 2.0,
                "kl": 0.0015,
            },
        },
    )
    (layout.source_dir / ".gitkeep").touch(exist_ok=True)
    print(f"Project initialized: {layout.root}")


def prepare(layout: ProjectLayout) -> None:
    config = read_yaml(layout.prepare_config)
    timetable_filename = required_filename(config, "timetable_filename")
    mileage_filename = required_filename(config, "mileage_filename")
    timetable_path = layout.source_dir / timetable_filename
    mileage_path = layout.source_dir / mileage_filename
    if not timetable_path.is_file():
        raise FileNotFoundError(f"Timetable not found in project source: {timetable_path}")
    if not mileage_path.is_file():
        raise FileNotFoundError(f"Mileage table not found in project source: {mileage_path}")

    timetable_sheet = str(config.get("timetable_sheet_name", "Sheet1") or "Sheet1")
    mileage_sheet = str(config.get("mileage_sheet_name", "Sheet1") or "Sheet1")
    context = build_base_context(
        timetable_path=timetable_path,
        mileage_path=mileage_path,
        timetable_sheet_name=timetable_sheet,
        mileage_sheet_name=mileage_sheet,
        timetable_table=load_timetable(timetable_path, timetable_sheet),
        mileage_table=load_mileage_table(mileage_path, mileage_sheet),
    )
    write_base_context(
        context,
        layout.context_json,
        metadata={
            "id": layout.name,
            "prepared_at": now(),
            "prepare_config": to_posix(layout.prepare_config),
        },
    )
    print(f"Context exported: {layout.context_json}")


def normal_generate(layout: ProjectLayout, config_id: str) -> None:
    config = read_yaml(layout.normal_generate_config(config_id))
    scenario_set_id = required_id(config, "scenario_set_id")
    output_root = layout.scenario_set(scenario_set_id).root
    prepare_output_dir(output_root, overwrite=bool(config.get("overwrite", False)))

    import scripts._case_generation_core as gen

    rng = random.Random(int(config.get("seed", 20260320)))
    base = gen.load_base_data_from_context(load_project_context(layout))
    gen.validate_case_counts(
        delay_count=int(config.get("delay_count", 10)),
        speed_count=int(config.get("speed_count", 10)),
        interruption_count=int(config.get("interruption_count", 10)),
        combo_per_type=int(config.get("combo_per_type", 10)),
    )

    original_write_case = gen.write_case
    try:
        gen.write_case = write_scenario_case
        case_index = 1
        case_index = gen.generate_delay_cases(rng, base, output_root, case_index, int(config.get("delay_count", 10)))
        case_index = gen.generate_speed_cases(rng, base, output_root, case_index, int(config.get("speed_count", 10)))
        case_index = gen.generate_interruption_cases(rng, base, output_root, case_index, int(config.get("interruption_count", 10)))
        case_index = gen.generate_combo_cases(rng, base, output_root, case_index, int(config.get("combo_per_type", 10)))
    finally:
        gen.write_case = original_write_case

    print(f"Generated {len(scenario_files(output_root))} scenarios: {output_root}")


def build_dataset(layout: ProjectLayout, scenario_set_id: str, dataset_id: str) -> None:
    dataset = layout.dataset(dataset_id)
    prepare_output_dir(dataset.root, overwrite=True)
    solve_config = read_yaml(layout.solve_config)
    records: List[Dict[str, object]] = []
    docs = load_scenario_set(layout, scenario_set_id)

    for index, doc in enumerate(docs, start=1):
        started = datetime.now()
        case_id = sanitize_id(doc.name)
        case_dir = dataset.cases_dir / case_id
        record = base_record(index, case_id, doc.path)
        try:
            config = case_app_config(layout, doc, case_dir, solve_config, analyze_config={})
            model = build_model(config.base_context.translated, config)
            export_lp(model, config.build.lp_path)
            record.update(
                {
                    "status": "ok",
                    "lp_path": to_posix(config.build.lp_path),
                    "lp_exists": config.build.lp_path.exists(),
                    "constraints": len(model.constraints),
                }
            )
        except Exception as exc:
            record.update({"status": "failed", "error": str(exc)})
        record["duration_sec"] = elapsed_seconds(started)
        records.append(record)
        print(f"[{index}/{len(docs)}] {record['status']} | {case_id}")

    write_csv(dataset.build_csv, records, build_headers())
    write_json(
        dataset.dataset_json,
        {
            "project": layout.name,
            "dataset_id": sanitize_id(dataset_id),
            "scenario_set_id": sanitize_id(scenario_set_id),
            "created_at": now(),
            "case_count": len(records),
        },
    )
    fail_if_records_failed(records, "build")
    print(f"Dataset built: {dataset.root}")


def solve_dataset(layout: ProjectLayout, dataset_id: str, *, limit: int = 0, time_limit: float | None = None) -> None:
    dataset = layout.dataset(dataset_id)
    metadata = read_json(dataset.dataset_json)
    solve_config = read_yaml(layout.solve_config)
    if time_limit is not None:
        solve_config["time_limit"] = time_limit
    records: List[Dict[str, object]] = []
    docs = load_scenario_set(layout, str(metadata["scenario_set_id"]))
    docs = limit_items(docs, limit)

    for index, doc in enumerate(docs, start=1):
        started = datetime.now()
        case_id = sanitize_id(doc.name)
        case_dir = dataset.cases_dir / case_id
        record = base_record(index, case_id, doc.path)
        try:
            config = case_app_config(layout, doc, case_dir, solve_config, analyze_config={})
            record["sol_path"] = to_posix(config.solve.solution_path)
            record["sol_exists"] = config.solve.solution_path.exists()
            if not config.solve.lp_path.is_file():
                raise FileNotFoundError(f"LP not found: {config.solve.lp_path}")
            result = solve_lp(
                config.solve.lp_path,
                config.solve.solution_path,
                quiet=True,
                threads=int(solve_config.get("threads_per_solve", 0) or 0),
                time_limit=float(solve_config.get("time_limit", 0.0) or 0.0),
                mip_gap=float(solve_config.get("mip_gap", 0.0) or 0.0),
            )
            record.update(
                {
                    "status": "timeout" if result.timed_out else "ok",
                    "sol_exists": config.solve.solution_path.exists(),
                    "objective": round(result.objective, 4),
                    "mip_gap": round(result.mip_gap, 6),
                    "num_nodes": int(round(result.node_count)),
                }
            )
        except GurobiSolveError as exc:
            record["sol_exists"] = Path(str(record.get("sol_path", ""))).exists() if record.get("sol_path") else False
            record.update(
                {
                    "status": "timeout" if exc.timed_out else "failed",
                    "error": str(exc),
                    "num_nodes": int(round(exc.node_count)) if exc.node_count is not None else None,
                }
            )
        except Exception as exc:
            record.update({"status": "failed", "error": str(exc)})
        record["duration_sec"] = elapsed_seconds(started)
        records.append(record)
        print(f"[{index}/{len(docs)}] {record['status']} | {case_id}")

    write_csv(dataset.solve_csv, records, solve_headers())
    fail_if_records_failed(records, "solve")
    print(f"Solve summary: {dataset.solve_csv}")


def analyze_dataset(layout: ProjectLayout, dataset_id: str, *, limit: int = 0) -> None:
    from analysis.io import timetable_from_base_context
    from analysis.scenario_report import build_case_scenario_report_data

    dataset = layout.dataset(dataset_id)
    metadata = read_json(dataset.dataset_json)
    solve_config = read_yaml(layout.solve_config)
    analyze_config = read_yaml(layout.analyze_config)
    records: List[Dict[str, object]] = []
    docs = limit_items(load_scenario_set(layout, str(metadata["scenario_set_id"])), limit)

    for index, doc in enumerate(docs, start=1):
        started = datetime.now()
        case_id = sanitize_id(doc.name)
        case_dir = dataset.cases_dir / case_id
        record = base_record(index, case_id, doc.path)
        try:
            config = case_app_config(layout, doc, case_dir, solve_config, analyze_config=analyze_config)
            if not config.solve.solution_path.is_file():
                raise FileNotFoundError(f"Solution not found: {config.solve.solution_path}")
            values = load_solution_values(config.solve.solution_path)
            export_adjusted_timetable(
                config.base_context.translated,
                values,
                config.export_timetable.timetable_path,
            )
            metrics_exists = False
            plot_exists = False
            if bool(analyze_config.get("enable_metrics", True)):
                from analysis.metrics import analyze_timetable

                analyze_timetable(
                    config.analyze.plan_timetable_path,
                    config.analyze.adjusted_timetable_path,
                    config.analyze.metrics_output_path,
                    plan_sheet_name=config.analyze.plan_timetable_sheet_name,
                    adjusted_sheet_name=config.analyze.adjusted_timetable_sheet_name,
                    plan_df=timetable_from_base_context(config.base_context),
                )
                metrics_exists = config.analyze.metrics_output_path.exists()
            if bool(analyze_config.get("enable_plot", True)):
                from analysis.plot import plot_timetable

                scenario_rows = build_case_scenario_report_data(
                    case_id=case_id,
                    scenarios=scenario_config_to_report_payload(config.scenarios),
                    config=config,
                    translated=config.base_context.translated,
                )["scenario_rows"]
                plot_timetable(
                    config.analyze.plot_timetable_path,
                    config.analyze.plot_output_path,
                    show_grid=bool(analyze_config.get("plot_grid", True)),
                    title=config.solve.solution_path.name,
                    subtitle=scenario_note(config),
                    sheet_name=config.analyze.adjusted_timetable_sheet_name,
                    scenario_overlay=scenario_rows,
                    station_order=config.base_context.station_order,
                )
                plot_exists = config.analyze.plot_output_path.exists()
            record.update(
                {
                    "status": "ok",
                    "adjusted_timetable_path": to_posix(config.export_timetable.timetable_path),
                    "metrics_path": to_posix(config.analyze.metrics_output_path),
                    "metrics_exists": metrics_exists,
                    "plot_path": to_posix(config.analyze.plot_output_path),
                    "plot_exists": plot_exists,
                }
            )
        except Exception as exc:
            record.update({"status": "failed", "error": str(exc)})
        record["duration_sec"] = elapsed_seconds(started)
        records.append(record)
        print(f"[{index}/{len(docs)}] {record['status']} | {case_id}")

    write_csv(dataset.analyze_csv, records, analyze_headers())
    fail_if_records_failed(records, "analyze")
    print(f"Analyze summary: {dataset.analyze_csv}")


def train_model(layout: ProjectLayout, config_id: str) -> None:
    config = read_yaml(layout.train_config(config_id))
    scenario_set_id = required_id(config, "scenario_set_id")
    model_id = required_id(config, "model_id")
    model = layout.model(model_id)
    model.root.mkdir(parents=True, exist_ok=True)
    export_training_graphs(layout, model, scenario_set_id, config)

    train_config = {
        "train": {
            "data": {
                "graphs_root": to_posix(model.graph_dir),
                "limit": int(section(config, "data").get("limit", 0) or 0),
            },
            "model": section(config, "model"),
            "optimization": section(config, "optimization"),
            "loss_weights": section(config, "loss_weights"),
            "output": {"dir": to_posix(model.root)},
        }
    }
    write_yaml(model.train_config, train_config)
    run([sys.executable, "scripts/train_vae.py", to_posix(model.train_config)])
    print(f"Model trained: {model.root}")


def generate_scenarios(
    layout: ProjectLayout,
    *,
    model_id: str,
    scenario_set_id: str,
    num_samples: int,
    seed: int,
    device: str,
    overwrite: bool,
) -> None:
    model = layout.model(model_id)
    output_root = layout.scenario_set(scenario_set_id).root
    prepare_output_dir(output_root, overwrite=overwrite)
    generation_run = model.generation_dir / sanitize_id(scenario_set_id)
    run(
        [
            sys.executable,
            "scripts/generate_vae.py",
            "--context-graph",
            to_posix(model.context_graph),
            "--checkpoint",
            to_posix(model.best_model),
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
    context = load_project_context(layout)
    graph_paths = sorted((generation_run / "math_graphs").glob("*.json"))
    for index, graph_path in enumerate(graph_paths, start=1):
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        disturbance_graph = typed_generated_graph_to_disturbance_graph(graph, context)
        scenarios = disturbance_graph_to_scenario(disturbance_graph, context)
        scenario_path = output_root / f"sample_{index:06d}.yml"
        write_yaml(scenario_path, scenario_config_to_yaml(f"sample_{index:06d}", scenarios))
    print(f"Generated and decoded {len(graph_paths)} scenarios: {output_root}")


def export_training_graphs(
    layout: ProjectLayout,
    model: Any,
    scenario_set_id: str,
    train_config: Dict[str, object],
) -> None:
    graph_settings = section(train_config, "data")
    reset_dir(model.graph_dir)
    model.sample_dir.mkdir(parents=True, exist_ok=True)
    solve_config = read_yaml(layout.solve_config)
    docs = limit_items(load_scenario_set(layout, scenario_set_id), int(graph_settings.get("limit", 0) or 0))

    context_graph: Dict[str, object] | None = None
    profile_source: Dict[str, object] | None = None
    samples: List[Dict[str, object]] = []
    sample_records: List[Dict[str, object]] = []

    for doc in docs:
        config = case_app_config(layout, doc, model.root / "_graph_cases" / sanitize_id(doc.name), solve_config, analyze_config={})
        typed = scenario_to_typed_vae_learning_graph(
            config,
            source_config_path=to_posix(doc.path or Path(doc.name)),
            max_slots=int(graph_settings.get("max_slots", DEFAULT_MAX_SLOTS)),
            event_time_window=int(graph_settings.get("event_time_window", DEFAULT_EVENT_TIME_WINDOW)),
            event_top_k=int(graph_settings.get("event_top_k", DEFAULT_EVENT_TOP_K)),
            section_order_window=int(graph_settings.get("section_order_window", DEFAULT_SECTION_ORDER_WINDOW)),
            speed_interruption_threshold=float(
                graph_settings.get("speed_interruption_threshold", DEFAULT_SPEED_INTERRUPTION_THRESHOLD)
            ),
        )
        context = typed_learning_graph_to_math_context_graph(typed)
        if context_graph is None:
            context_graph = context
            profile_source = typed
        elif context != context_graph:
            raise ValueError("All training samples must share the same context graph.")
        sample = typed_learning_graph_to_math_learning_sample(typed, context_ref="context.json", sample_id=doc.name)
        sample_path = model.sample_dir / f"{sanitize_id(doc.name)}.json"
        write_json(sample_path, sample)
        samples.append(sample)
        sample_records.append(
            {
                "learning_sample_path": to_posix(sample_path),
                "context_graph_path": to_posix(model.context_graph),
                "source_scenario_path": to_posix(doc.path or Path(doc.name)),
            }
        )

    if context_graph is None or profile_source is None:
        raise ValueError(f"No scenarios found for training: {scenario_set_id}")
    inferred_context, inferred_schema = infer_math_dataset_schema(context_graph, samples)
    write_json(model.context_graph, inferred_context)
    write_json(
        model.graph_dir / "dataset_profile.json",
        typed_learning_graph_to_dataset_profile(
            profile_source,
            samples=sample_records,
            inferred_schema=inferred_schema,
            export_profile=dict(graph_settings),
        ),
    )


def case_app_config(
    layout: ProjectLayout,
    scenario_doc: ScenarioDocument,
    case_dir: Path,
    solve_config: Dict[str, object],
    analyze_config: Dict[str, object],
) -> AppConfig:
    case_id = sanitize_id(scenario_doc.name)
    payload = {
        "project": {
            "name": case_id,
            "output_dir": to_posix(case_dir),
            "base_context_path": to_posix(layout.context_json),
        },
        "build": {"scenarios": scenario_doc.scenarios},
        "solve": {key: value for key, value in solve_config.items() if key not in {"time_limit", "mip_gap", "threads_per_solve"}},
        "export-timetable": {"sol_path": ""},
        "analyze": {
            "enable_metrics": bool(analyze_config.get("enable_metrics", False)),
            "enable_plot": bool(analyze_config.get("enable_plot", False)),
            "plot_grid": bool(analyze_config.get("plot_grid", True)),
            "plot_title": "",
            "adj_timetable_path": "",
            "adj_timetable_sheet_name": str(analyze_config.get("adj_timetable_sheet_name", "Sheet1") or "Sheet1"),
        },
    }
    return load_config_payload(payload, case_dir / "case.yml")


def load_project_context(layout: ProjectLayout):
    if not layout.context_json.is_file():
        raise FileNotFoundError(f"Missing project context. Run: python scripts/project.py {layout.name} prepare")
    return load_base_context(layout.context_json)


def load_scenario_set(layout: ProjectLayout, scenario_set_id: str) -> List[ScenarioDocument]:
    root = layout.scenario_set(scenario_set_id).root
    if not root.is_dir():
        raise FileNotFoundError(f"Scenario set not found: {root}")
    yaml = require_yaml()
    docs = [load_scenario_document(path, yaml) for path in scenario_files(root)]
    if not docs:
        raise FileNotFoundError(f"No scenario YAML files found: {root}")
    return docs


def write_scenario_case(case_path: Path, config_payload: Dict[str, object], _meta_payload: Dict[str, object]) -> None:
    project = config_payload.get("project", {})
    build = config_payload.get("build", {})
    scenarios = build.get("scenarios", {}) if isinstance(build, dict) else {}
    payload = {
        "name": project.get("name", case_path.name) if isinstance(project, dict) else case_path.name,
        "delays": scenarios.get("delays", []) if isinstance(scenarios, dict) else [],
        "speed_limits": scenarios.get("speed_limits", []) if isinstance(scenarios, dict) else [],
    }
    write_yaml(case_path.with_suffix(".yml"), payload)


def scenario_config_to_yaml(name: str, scenarios: ScenarioConfig) -> Dict[str, object]:
    return {
        "name": name,
        "delays": [
            {
                "event_anchor_id": item.event_anchor_id,
                "seconds": int(item.seconds),
            }
            for item in scenarios.delays
        ],
        "speed_limits": [
            {
                "section_anchor_id": item.section_anchor_id,
                "start_time": seconds_to_hms(item.start_time),
                "duration": int(item.duration),
                "limit_speed": clean_number(item.limit_speed),
            }
            for item in scenarios.speed_limits
        ],
    }


def scenario_config_to_report_payload(scenarios: ScenarioConfig) -> Dict[str, object]:
    return {
        "delays": [
            {
                "train_id": item.train_id,
                "station": item.station,
                "event_type": item.event_type,
                "seconds": item.seconds,
            }
            for item in scenarios.delays
        ],
        "speed_limits": [
            {
                "start_station": item.start_station,
                "end_station": item.end_station,
                "limit_speed": item.limit_speed,
                "start_time": seconds_to_hms(item.start_time),
                "end_time": seconds_to_hms(item.end_time),
            }
            for item in scenarios.speed_limits
            if item.limit_speed > 0
        ],
        "interruptions": [
            {
                "start_station": item.start_station,
                "end_station": item.end_station,
                "start_time": seconds_to_hms(item.start_time),
                "end_time": seconds_to_hms(item.end_time),
            }
            for item in scenarios.speed_limits
            if item.limit_speed == 0
        ],
    }


def scenario_note(config: AppConfig) -> str:
    count = len(config.scenarios.delays) + len(config.scenarios.speed_limits)
    return f"Scenarios: {count}" if count else "Scenarios: none"


def required_filename(config: Dict[str, object], key: str) -> str:
    value = str(config.get(key, "") or "").strip()
    if not value:
        raise ValueError(f"Missing required {key}")
    if Path(value).name != value:
        raise ValueError(f"{key} must be a filename under project source/: {value}")
    return value


def required_id(config: Dict[str, object], key: str) -> str:
    value = str(config.get(key, "") or "").strip()
    if not value:
        raise ValueError(f"Missing required {key}")
    return sanitize_id(value)


def default_solve_config() -> Dict[str, object]:
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
        "threads_per_solve": 0,
        "time_limit": 120.0,
        "mip_gap": 0.0,
    }


def prepare_output_dir(path: Path, *, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists, set overwrite: true or pass --overwrite: {path}")
        reset_dir(path)
    path.mkdir(parents=True, exist_ok=True)


def limit_items(items: List[Any], limit: int) -> List[Any]:
    return items[:limit] if limit and limit > 0 else items


def base_record(index: int, case_id: str, scenario_path: Path | None) -> Dict[str, object]:
    return {
        "index": index,
        "case_id": case_id,
        "scenario_path": to_posix(scenario_path) if scenario_path else "",
        "status": "pending",
        "error": "",
        "duration_sec": 0.0,
    }


def build_headers() -> List[str]:
    return ["index", "case_id", "scenario_path", "status", "error", "lp_path", "lp_exists", "constraints", "duration_sec"]


def solve_headers() -> List[str]:
    return [
        "index",
        "case_id",
        "scenario_path",
        "status",
        "error",
        "sol_path",
        "sol_exists",
        "objective",
        "mip_gap",
        "num_nodes",
        "duration_sec",
    ]


def analyze_headers() -> List[str]:
    return [
        "index",
        "case_id",
        "scenario_path",
        "status",
        "error",
        "adjusted_timetable_path",
        "metrics_path",
        "metrics_exists",
        "plot_path",
        "plot_exists",
        "duration_sec",
    ]


def fail_if_records_failed(records: Iterable[Dict[str, object]], stage: str) -> None:
    failed = [record for record in records if record.get("status") == "failed"]
    if failed:
        raise RuntimeError(f"{stage} failed for {len(failed)} case(s).")


def section(payload: Dict[str, object], name: str) -> Dict[str, object]:
    value = payload.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a YAML object.")
    return value


def read_yaml(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")
    payload = require_yaml().safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML must contain an object: {path}")
    return payload


def write_yaml(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(require_yaml().safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_yaml_if_missing(path: Path, payload: Dict[str, object]) -> None:
    if not path.exists():
        write_yaml(path, payload)


def read_json(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, records: List[Dict[str, object]], headers: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key, "") for key in headers})


def run(cmd: List[str]) -> None:
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def seconds_to_hms(seconds: int) -> str:
    total = max(0, min(24 * 3600 - 1, int(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def clean_number(value: float) -> object:
    number = float(value)
    return int(number) if number.is_integer() else number


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

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from core.base_context import build_base_context, load_base_context, write_base_context
from core.builder import build_model
from core.disturbance_graph import disturbance_graph_to_scenario
from core.exporter import export_lp
from core.loader import load_config_payload, load_mileage_table, load_timetable, parse_scenario_config
from core.project_layout import ProjectLayout, REPO_ROOT, reset_dir, sanitize_id, to_posix
from core.scenario_config import (
    ScenarioDocument,
    load_scenario_document,
    scenario_config_to_yaml,
    scenario_document_to_yaml,
    scenario_file_by_id,
    scenario_files,
)
from core.solver import GurobiSolveError, solve_lp
from core.types import AppConfig
from core.vae_learning_graph import (
    DEFAULT_EVENT_TIME_WINDOW,
    DEFAULT_EVENT_TOP_K,
    DEFAULT_MAX_SLOTS,
    DEFAULT_SECTION_ORDER_WINDOW,
    infer_math_dataset_schema,
    scenario_to_typed_vae_learning_graph,
    scenario_config_to_typed_vae_learning_graph,
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


def prepare(
    layout: ProjectLayout,
    *,
    timetable_filename: str,
    mileage_filename: str,
    timetable_sheet_name: str = "Sheet1",
    mileage_sheet_name: str = "Sheet1",
) -> None:
    timetable_filename = required_filename({"timetable_filename": timetable_filename}, "timetable_filename")
    mileage_filename = required_filename({"mileage_filename": mileage_filename}, "mileage_filename")
    timetable_path = layout.source_dir / timetable_filename
    mileage_path = layout.source_dir / mileage_filename
    if not timetable_path.is_file():
        raise FileNotFoundError(f"Timetable not found in project source: {timetable_path}")
    if not mileage_path.is_file():
        raise FileNotFoundError(f"Mileage table not found in project source: {mileage_path}")

    timetable_sheet = str(timetable_sheet_name or "Sheet1")
    mileage_sheet = str(mileage_sheet_name or "Sheet1")
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
            "timetable_filename": timetable_filename,
            "mileage_filename": mileage_filename,
            "timetable_sheet_name": timetable_sheet,
            "mileage_sheet_name": mileage_sheet,
        },
    )
    print(f"Context exported: {layout.context_json}")


def delete_source_file(layout: ProjectLayout, filename: str) -> None:
    require_project(layout)
    clean_filename = required_filename({"filename": filename}, "filename")
    path = layout.source_dir / clean_filename
    if not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")
    path.unlink()
    print(f"Source file deleted: {path}")


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
    dataset = layout.dataset(dataset_id)
    if dataset.root.exists() and not dataset.root.is_dir():
        raise NotADirectoryError(f"MILP dataset path is not a directory: {dataset.root}")
    if not dataset.root.is_dir():
        raise FileNotFoundError(f"MILP dataset not found, create it first: {dataset.root}")
    prepare_output_dir(dataset.root, overwrite=True)
    docs = load_scenario_documents(layout, scenario_set_id, scenario_id=scenario_id)

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
        try:
            case_dir.mkdir(parents=True, exist_ok=True)
            write_yaml(case_dir / "scenario.yml", scenario_document_to_yaml(case_id, doc))
            config = case_app_config(
                layout,
                doc,
                case_dir,
                build_config,
            )
            model = build_model(config.base_context.translated, config)
            export_lp(model, config.build.lp_path)
            record.update(
                {
                    "status": "ok",
                    "constraints": len(model.constraints),
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
) -> None:
    dataset = layout.dataset(dataset_id)
    case_dirs = [dataset_case_dir(dataset, case_id)] if case_id else limit_items(dataset_case_dirs(dataset), limit)
    records = [
        solve_case(case_dir, index, time_limit=time_limit, mip_gap=mip_gap, threads=threads)
        for index, case_dir in enumerate(case_dirs, start=1)
    ]

    fail_if_records_failed(records, "solve")
    ok_count = sum(1 for record in records if record.get("status") in {"ok", "timeout"})
    print(f"Solve finished: {ok_count}/{len(records)} case(s)")


def solve_case(
    case_dir: Path,
    index: int,
    *,
    time_limit: float = 120.0,
    mip_gap: float = 0.0,
    threads: int = 0,
) -> Dict[str, object]:
    started = datetime.now()
    case_id = sanitize_id(case_dir.name)
    lp_path = case_dir / f"{case_id}.lp"
    sol_path = case_dir / f"{case_id}.sol"
    record = base_record(index, case_id)
    solver_config = {
        "time_limit": max(0.0, float(time_limit or 0.0)),
        "mip_gap": max(0.0, float(mip_gap or 0.0)),
        "threads": max(0, int(threads or 0)),
    }
    try:
        if not lp_path.is_file():
            raise FileNotFoundError(f"LP not found: {lp_path}")
        result = solve_lp(
            lp_path,
            sol_path,
            quiet=True,
            threads=int(solver_config["threads"]),
            time_limit=float(solver_config["time_limit"]),
            mip_gap=float(solver_config["mip_gap"]),
        )
        write_solution_csv(sol_path.with_suffix(".sol.csv"), result.values)
        record.update(
            {
                "status": "timeout" if result.timed_out else "ok",
                "objective": round(result.objective, 4),
                "mip_gap": round(result.mip_gap, 6),
                "num_nodes": int(round(result.node_count)),
            }
        )
    except GurobiSolveError as exc:
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
) -> None:
    scenario_set_id = sanitize_id(scenario_set_id)
    model_id = sanitize_id(model_id)
    model = layout.model(model_id)
    if model.root.exists():
        reset_dir(model.root)
    model.root.mkdir(parents=True, exist_ok=True)
    export_training_graphs(
        layout,
        model,
        scenario_set_id,
        {
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
        ]
    )
    print(f"Model trained: {model.root}")


def generate_scenarios(
    layout: ProjectLayout,
    *,
    model_id: str,
    checkpoint: str,
    scenario_set_id: str,
    num_samples: int,
    seed: int,
    device: str,
    speed_interruption_threshold: float,
    overwrite: bool,
) -> None:
    model = layout.model(model_id)
    checkpoint_path = model_checkpoint_path(model.root, checkpoint)
    output_root = layout.scenario_set(scenario_set_id).root
    prepare_output_dir(output_root, overwrite=overwrite)
    generation_run = layout.root / ".tmp" / f"generation_{sanitize_id(scenario_set_id)}_{datetime.now():%Y%m%d_%H%M%S_%f}"
    try:
        run(
            [
                sys.executable,
                "scripts/generate_vae.py",
                "--context-graph",
                to_posix(model.context_graph),
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
        context = load_project_context(layout)
        graph_paths = sorted((generation_run / "math_graphs").glob("*.json"))
        for index, graph_path in enumerate(graph_paths, start=1):
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            disturbance_graph = typed_generated_graph_to_disturbance_graph(
                graph,
                context,
                speed_interruption_threshold=speed_interruption_threshold,
            )
            scenarios = disturbance_graph_to_scenario(disturbance_graph, context)
            scenario_path = output_root / f"sample_{index:06d}.yml"
            write_yaml(scenario_path, scenario_config_to_yaml(f"sample_{index:06d}", scenarios))
        print(f"Generated and decoded {len(graph_paths)} scenarios: {output_root}")
    finally:
        if generation_run.exists():
            reset_dir(generation_run)


def export_training_graphs(
    layout: ProjectLayout,
    model: Any,
    scenario_set_id: str,
    graph_settings: Dict[str, object],
) -> None:
    reset_dir(model.graph_dir)
    model.sample_dir.mkdir(parents=True, exist_ok=True)
    base_context = load_project_context(layout)
    base_context_path = to_posix(layout.context_json)
    docs = load_scenario_set(layout, scenario_set_id)
    total = len(docs)
    write_graph_progress(
        model,
        global_graph_status="running",
        sample_graph_status="pending",
        sample_total=total,
        sample_completed=0,
    )

    context_graph: Dict[str, object] | None = None
    profile_source: Dict[str, object] | None = None
    samples: List[Dict[str, object]] = []
    sample_records: List[Dict[str, object]] = []

    for index, doc in enumerate(docs, start=1):
        scenarios = parse_scenario_config(doc.scenarios, base_context)
        typed = scenario_config_to_typed_vae_learning_graph(
            scenarios,
            base_context,
            base_context_path=base_context_path,
            source_config_path=to_posix(doc.path or Path(doc.name)),
            max_slots=int(graph_settings.get("max_slots", DEFAULT_MAX_SLOTS)),
            event_time_window=int(graph_settings.get("event_time_window", DEFAULT_EVENT_TIME_WINDOW)),
            event_top_k=int(graph_settings.get("event_top_k", DEFAULT_EVENT_TOP_K)),
            section_order_window=int(graph_settings.get("section_order_window", DEFAULT_SECTION_ORDER_WINDOW)),
        )
        context = typed_learning_graph_to_math_context_graph(typed)
        if context_graph is None:
            context_graph = context
            profile_source = typed
            write_graph_progress(
                model,
                global_graph_status="done",
                sample_graph_status="running",
                sample_total=total,
                sample_completed=0,
            )
        elif context != context_graph:
            raise ValueError("All training samples must share the same context graph.")
        sample = typed_learning_graph_to_math_learning_sample(
            typed,
            context_ref=model.context_graph.name,
            sample_id=doc.name,
        )
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
        write_graph_progress(
            model,
            global_graph_status="done",
            sample_graph_status="running",
            sample_total=total,
            sample_completed=index,
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
    write_graph_progress(
        model,
        global_graph_status="done",
        sample_graph_status="done",
        sample_total=total,
        sample_completed=total,
    )


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


def case_app_config(
    layout: ProjectLayout,
    scenario_doc: ScenarioDocument,
    case_dir: Path,
    build_config: Dict[str, object] | None = None,
) -> AppConfig:
    case_id = sanitize_id(scenario_doc.name)
    payload = {
        "project": {
            "name": case_id,
            "output_dir": to_posix(case_dir),
            "base_context_path": to_posix(layout.context_json),
        },
        "build": {"scenarios": scenario_doc.scenarios},
        "solver": dict(build_config or default_build_config()),
        "solve": {},
        "export-timetable": {"sol_path": ""},
    }
    return load_config_payload(payload, case_dir / "case.yml")


def load_project_context(layout: ProjectLayout):
    if not layout.context_json.is_file():
        raise FileNotFoundError(f"Missing project context. Run: python scripts/project.py {layout.name} prepare")
    return load_base_context(layout.context_json)


def require_project(layout: ProjectLayout) -> None:
    if not layout.root.is_dir():
        raise FileNotFoundError(f"Project not found. Run: python scripts/project.py newproject {layout.name}")


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
        raise RuntimeError(f"{stage} failed for {len(failed)} case(s).")


def write_yaml(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(require_yaml().safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_solution_csv(path: Path, values: Dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["variable", "value"])
        writer.writeheader()
        for name in sorted(values):
            writer.writerow({"variable": name, "value": values[name]})


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

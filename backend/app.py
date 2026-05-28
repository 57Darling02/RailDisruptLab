from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - Pydantic v1 compatibility
    ConfigDict = None

from backend import RailGraphBackend
from backend.pueue_client import PueueError
from backend.task_contracts import TASK_DEFAULTS
from core.project_layout import REPO_ROOT


class ProjectCreateRequest(BaseModel):
    project_id: str


class ScenarioSetCreateRequest(BaseModel):
    scenario_set_id: str
    exist_ok: bool = False


class ScenarioWriteRequest(BaseModel):
    scenario_id: str
    delays: List[Dict[str, object]] = []
    speed_limits: List[Dict[str, object]] = []
    overwrite: bool = False


class PrepareRequest(BaseModel):
    timetable_filename: str
    mileage_filename: str
    timetable_sheet_name: str = TASK_DEFAULTS["prepare"]["timetable_sheet_name"]
    mileage_sheet_name: str = TASK_DEFAULTS["prepare"]["mileage_sheet_name"]


class NormalGenerateRequest(BaseModel):
    scenario_set_id: str
    seed: int = TASK_DEFAULTS["normal_generate"]["seed"]
    delay_count: int = TASK_DEFAULTS["normal_generate"]["delay_count"]
    speed_count: int = TASK_DEFAULTS["normal_generate"]["speed_count"]
    interruption_count: int = TASK_DEFAULTS["normal_generate"]["interruption_count"]
    combo_per_type: int = TASK_DEFAULTS["normal_generate"]["combo_per_type"]
    overwrite: bool = TASK_DEFAULTS["normal_generate"]["overwrite"]
    merge: bool = TASK_DEFAULTS["normal_generate"]["merge"]


class BuildRequest(BaseModel):
    scenario_set_id: str
    dataset_id: str
    scenario_id: str = TASK_DEFAULTS["build"]["scenario_id"]
    objective_delay_weight: float = TASK_DEFAULTS["build"]["objective_delay_weight"]
    objective_mode: str = TASK_DEFAULTS["build"]["objective_mode"]
    cancellation_enabled: bool = TASK_DEFAULTS["build"]["cancellation_enabled"]
    cancellation_penalty_weight: float = TASK_DEFAULTS["build"]["cancellation_penalty_weight"]
    arr_arr_headway_seconds: int = TASK_DEFAULTS["build"]["arr_arr_headway_seconds"]
    dep_dep_headway_seconds: int = TASK_DEFAULTS["build"]["dep_dep_headway_seconds"]
    dwell_seconds_at_stops: int = TASK_DEFAULTS["build"]["dwell_seconds_at_stops"]
    big_m: int = TASK_DEFAULTS["build"]["big_m"]
    tolerance_delay_seconds: int = TASK_DEFAULTS["build"]["tolerance_delay_seconds"]


class DatasetCreateRequest(BaseModel):
    dataset_id: str
    exist_ok: bool = False


class SolveRequest(BaseModel):
    dataset_id: str
    case_id: str = TASK_DEFAULTS["solve"]["case_id"]
    limit: int = TASK_DEFAULTS["solve"]["limit"]
    time_limit: Optional[float] = None
    mip_gap: Optional[float] = None
    threads: Optional[int] = None


class ExportTimetableRequest(BaseModel):
    dataset_id: str
    case_id: str = TASK_DEFAULTS["export_timetable"]["case_id"]
    limit: int = TASK_DEFAULTS["export_timetable"]["limit"]


class TrainRequest(BaseModel):
    model_id: str
    scenario_set_id: str
    max_slots: int = TASK_DEFAULTS["train"]["max_slots"]
    event_time_window: int = TASK_DEFAULTS["train"]["event_time_window"]
    event_top_k: int = TASK_DEFAULTS["train"]["event_top_k"]
    section_order_window: int = TASK_DEFAULTS["train"]["section_order_window"]
    hidden_dim: int = TASK_DEFAULTS["train"]["hidden_dim"]
    latent_dim: int = TASK_DEFAULTS["train"]["latent_dim"]
    message_passing_steps: int = TASK_DEFAULTS["train"]["message_passing_steps"]
    epochs: int = TASK_DEFAULTS["train"]["epochs"]
    batch_size: int = TASK_DEFAULTS["train"]["batch_size"]
    lr: float = TASK_DEFAULTS["train"]["lr"]
    seed: int = TASK_DEFAULTS["train"]["seed"]
    device: str = TASK_DEFAULTS["train"]["device"]
    log_every: int = TASK_DEFAULTS["train"]["log_every"]
    count_weight: float = TASK_DEFAULTS["train"]["count_weight"]
    anchor_weight: float = TASK_DEFAULTS["train"]["anchor_weight"]
    param_weight: float = TASK_DEFAULTS["train"]["param_weight"]
    kl_weight: float = TASK_DEFAULTS["train"]["kl_weight"]


class GenerationRequest(BaseModel):
    if ConfigDict is not None:
        model_config = ConfigDict(protected_namespaces=())

    model_id: str
    checkpoint: str
    scenario_set_id: str
    num_samples: int = TASK_DEFAULTS["generation"]["num_samples"]
    seed: int = TASK_DEFAULTS["generation"]["seed"]
    device: str = TASK_DEFAULTS["generation"]["device"]
    speed_interruption_threshold: float = TASK_DEFAULTS["generation"]["speed_interruption_threshold"]
    overwrite: bool = TASK_DEFAULTS["generation"]["overwrite"]


backend = RailGraphBackend()
api = FastAPI(title="RailGraph2Gurobi API")
app = FastAPI(title="RailGraph2Gurobi")


@app.on_event("startup")
def app_startup() -> None:
    backend.ensure_ready()


@api.get("/health")
def health() -> Dict[str, object]:
    return backend.health()


@api.get("/projects")
def list_projects() -> List[Dict[str, object]]:
    return backend.list_projects()


@api.post("/projects")
def create_project(request: ProjectCreateRequest) -> Dict[str, object]:
    return _task_response(backend.create_project(request.project_id))


@api.delete("/projects/{project_id}")
def delete_project(project_id: str) -> Dict[str, object]:
    return _task_response(backend.delete_project(project_id))


@api.get("/projects/{project_id}")
def get_project(project_id: str) -> Dict[str, object]:
    return backend.get_project_state(project_id)


@api.get("/projects/{project_id}/scenario-sets")
def list_scenario_sets(project_id: str) -> List[Dict[str, object]]:
    return backend.list_scenario_sets(project_id)


@api.post("/projects/{project_id}/scenario-sets")
def create_scenario_set(project_id: str, request: ScenarioSetCreateRequest) -> Dict[str, object]:
    return _task_response(
        backend.create_scenario_set(project_id, request.scenario_set_id, exist_ok=request.exist_ok)
    )


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios")
def list_scenarios(project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
    return backend.list_scenarios(project_id, scenario_set_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/visualization")
def read_scenario_set_visualization(project_id: str, scenario_set_id: str) -> Dict[str, object]:
    return backend.read_scenario_set_visualization(project_id, scenario_set_id)


@api.get("/projects/{project_id}/analysis/dataset-solve")
def read_dataset_solve_analysis(project_id: str, dataset_ids: List[str] = Query(...)) -> Dict[str, object]:
    if not dataset_ids:
        raise HTTPException(status_code=400, detail="dataset_ids is required")
    return backend.read_dataset_solve_analysis(project_id, dataset_ids)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios/{scenario_id}")
def read_scenario(project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    return backend.read_scenario(project_id, scenario_set_id, scenario_id)


@api.get("/projects/{project_id}/scenario-options")
def read_scenario_options(project_id: str) -> Dict[str, object]:
    return backend.read_scenario_options(project_id)


@api.post("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios")
def add_scenario(project_id: str, scenario_set_id: str, request: ScenarioWriteRequest) -> Dict[str, object]:
    return _task_response(
        backend.add_scenario(
            project_id,
            scenario_set_id,
            request.scenario_id,
            delays=request.delays,
            speed_limits=request.speed_limits,
            overwrite=request.overwrite,
        )
    )


@api.delete("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios/{scenario_id}")
def delete_scenario(project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    return _task_response(backend.delete_scenario(project_id, scenario_set_id, scenario_id))


@api.post("/projects/{project_id}/source")
def upload_source(project_id: str, file: UploadFile = File(...)) -> Dict[str, object]:
    content = file.file.read()
    path = backend.save_source_file(project_id, file.filename or "source.bin", content)
    return {"path": path, "size_bytes": len(content)}


@api.get("/projects/{project_id}/source/{filename}")
def download_source(project_id: str, filename: str) -> FileResponse:
    path = backend.source_file_path(project_id, filename)
    return FileResponse(path, filename=path.name)


@api.delete("/projects/{project_id}/source/{filename}")
def delete_source(project_id: str, filename: str) -> Dict[str, object]:
    return _task_response(backend.delete_source_file(project_id, filename))


@api.get("/projects/{project_id}/tasks")
def list_project_tasks(project_id: str) -> List[Dict[str, object]]:
    return backend.list_tasks(project_id)


@api.post("/projects/{project_id}/tasks/prepare")
def submit_prepare(project_id: str, request: PrepareRequest) -> Dict[str, object]:
    return _task_response(
        backend.prepare(
            project_id,
            timetable_filename=request.timetable_filename,
            mileage_filename=request.mileage_filename,
            timetable_sheet_name=request.timetable_sheet_name,
            mileage_sheet_name=request.mileage_sheet_name,
        )
    )


@api.post("/projects/{project_id}/tasks/normal-generate")
def submit_normal_generate(project_id: str, request: NormalGenerateRequest) -> Dict[str, object]:
    return _task_response(
        backend.normal_generate(
            project_id,
            scenario_set_id=request.scenario_set_id,
            seed=request.seed,
            delay_count=request.delay_count,
            speed_count=request.speed_count,
            interruption_count=request.interruption_count,
            combo_per_type=request.combo_per_type,
            overwrite=request.overwrite,
            merge=request.merge,
        )
    )


@api.post("/projects/{project_id}/tasks/build")
def submit_build(project_id: str, request: BuildRequest) -> Dict[str, object]:
    return _task_response(
        backend.build(
            project_id,
            request.scenario_set_id,
            request.dataset_id,
            scenario_id=request.scenario_id,
            objective_delay_weight=request.objective_delay_weight,
            objective_mode=request.objective_mode,
            cancellation_enabled=request.cancellation_enabled,
            cancellation_penalty_weight=request.cancellation_penalty_weight,
            arr_arr_headway_seconds=request.arr_arr_headway_seconds,
            dep_dep_headway_seconds=request.dep_dep_headway_seconds,
            dwell_seconds_at_stops=request.dwell_seconds_at_stops,
            big_m=request.big_m,
            tolerance_delay_seconds=request.tolerance_delay_seconds,
        )
    )


@api.post("/projects/{project_id}/datasets")
def create_dataset(project_id: str, request: DatasetCreateRequest) -> Dict[str, object]:
    return _task_response(backend.create_dataset(project_id, request.dataset_id, exist_ok=request.exist_ok))


@api.post("/projects/{project_id}/tasks/solve")
def submit_solve(project_id: str, request: SolveRequest) -> Dict[str, object]:
    return _task_response(
        backend.solve(
            project_id,
            request.dataset_id,
            case_id=request.case_id,
            limit=request.limit,
            time_limit=request.time_limit,
            mip_gap=request.mip_gap,
            threads=request.threads,
        )
    )


@api.post("/projects/{project_id}/tasks/export-timetable")
def submit_export_timetable(project_id: str, request: ExportTimetableRequest) -> Dict[str, object]:
    return _task_response(
        backend.export_timetable(
            project_id,
            request.dataset_id,
            case_id=request.case_id,
            limit=request.limit,
        )
    )


@api.post("/projects/{project_id}/tasks/train")
def submit_train(project_id: str, request: TrainRequest) -> Dict[str, object]:
    return _task_response(
        backend.train(
            project_id,
            request.model_id,
            request.scenario_set_id,
            max_slots=request.max_slots,
            event_time_window=request.event_time_window,
            event_top_k=request.event_top_k,
            section_order_window=request.section_order_window,
            hidden_dim=request.hidden_dim,
            latent_dim=request.latent_dim,
            message_passing_steps=request.message_passing_steps,
            epochs=request.epochs,
            batch_size=request.batch_size,
            lr=request.lr,
            seed=request.seed,
            device=request.device,
            log_every=request.log_every,
            count_weight=request.count_weight,
            anchor_weight=request.anchor_weight,
            param_weight=request.param_weight,
            kl_weight=request.kl_weight,
        )
    )


@api.post("/projects/{project_id}/tasks/generation")
def submit_generation(project_id: str, request: GenerationRequest) -> Dict[str, object]:
    return _task_response(
        backend.generation(
            project_id,
            request.model_id,
            request.checkpoint,
            request.scenario_set_id,
            num_samples=request.num_samples,
            seed=request.seed,
            device=request.device,
            speed_interruption_threshold=request.speed_interruption_threshold,
            overwrite=request.overwrite,
        )
    )


@api.get("/tasks")
def list_tasks(project_id: Optional[str] = None) -> List[Dict[str, object]]:
    return backend.list_tasks(project_id)


@api.delete("/tasks")
def clean_tasks(
    project_id: Optional[str] = None,
    successful_only: bool = False,
) -> Dict[str, object]:
    return backend.clean_tasks(project_id, successful_only=successful_only)


@api.get("/tasks/{task_id}")
def get_task(task_id: int) -> Dict[str, object]:
    task = backend.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@api.get("/tasks/{task_id}/log", response_class=PlainTextResponse)
def get_task_log(task_id: int, lines: Optional[int] = None) -> str:
    return backend.task_log(task_id, lines=lines)


@api.post("/tasks/{task_id}/wait")
def wait_task(task_id: int) -> Dict[str, object]:
    task = backend.wait_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@api.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: int) -> Dict[str, object]:
    return backend.cancel_task(task_id)


@api.get("/projects/{project_id}/datasets/{dataset_id}/cases/{case_id}/timetable")
def read_case_timetable(project_id: str, dataset_id: str, case_id: str) -> Dict[str, object]:
    return backend.read_case_timetable(project_id, dataset_id, case_id)


@api.get("/projects/{project_id}/plan-timetable")
def read_plan_timetable(project_id: str) -> Dict[str, object]:
    return backend.read_plan_timetable(project_id)


@api.get("/projects/{project_id}/datasets/{dataset_id}/artifacts")
def list_case_artifacts(project_id: str, dataset_id: str) -> List[Dict[str, object]]:
    return backend.list_case_artifacts(project_id, dataset_id)


@api.get("/projects/{project_id}/models/{model_id}/training-summary")
def read_training_summary(project_id: str, model_id: str) -> Dict[str, object]:
    return backend.read_training_summary(project_id, model_id)


@api.get("/projects/{project_id}/models/{model_id}/detail")
def read_model_detail(project_id: str, model_id: str) -> Dict[str, object]:
    return backend.read_model_detail(project_id, model_id)


@api.get("/projects/{project_id}/models/{model_id}/files")
def list_model_files(project_id: str, model_id: str) -> List[Dict[str, object]]:
    return backend.list_model_files(project_id, model_id)


def _task_response(task: Dict[str, object]) -> Dict[str, object]:
    return {"task": task}


@api.exception_handler(PueueError)
def pueue_exception_handler(_request, exc: PueueError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@api.exception_handler(FileNotFoundError)
def not_found_exception_handler(_request, exc: FileNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@api.exception_handler(ValueError)
def value_error_exception_handler(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


frontend_root = REPO_ROOT / "frontend"
frontend_dist = frontend_root / "dist"
frontend_dir = frontend_dist if frontend_dist.is_dir() else frontend_root
app.mount("/api", api)
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

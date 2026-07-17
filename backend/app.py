from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - Pydantic v1 compatibility
    ConfigDict = None

from backend import RailGraphBackend
from backend.pueue_client import PueueError
from backend.task_contracts import TASK_DEFAULTS
from backend.task_resources import TaskResourceConflict
from core.project_layout import REPO_ROOT


class ProjectCreateRequest(BaseModel):
    project_id: str


class ScenarioSetCreateRequest(BaseModel):
    scenario_set_id: str
    exist_ok: bool = False


class RunGraphSetCreateRequest(BaseModel):
    run_graph_set_id: str
    exist_ok: bool = False


class RunGraphReferenceRequest(BaseModel):
    set_id: str
    graph_id: str
    context_sha256: str = ""

    def to_domain(self):
        from core.scenario_config import RunGraphReference

        return RunGraphReference(
            set_id=self.set_id,
            graph_id=self.graph_id,
            context_sha256=self.context_sha256,
        )


class ScenarioWriteRequest(BaseModel):
    scenario_id: str
    run_graph: RunGraphReferenceRequest
    delays: List[Dict[str, object]] = []
    speed_limits: List[Dict[str, object]] = []
    overwrite: bool = False


class ScenarioDisturbanceWriteRequest(BaseModel):
    run_graph: Optional[RunGraphReferenceRequest] = None
    delays: List[Dict[str, object]] = []
    speed_limits: List[Dict[str, object]] = []
    overwrite: bool = False


class ScenarioValidationRequest(BaseModel):
    run_graph: Optional[RunGraphReferenceRequest] = None


class NormalGenerateRequest(BaseModel):
    scenario_set_id: str
    scenario_id_prefix: str = "sim"
    simulation_count: int = 1
    run_graph: RunGraphReferenceRequest
    seed: int = TASK_DEFAULTS["normal_generate"]["seed"]
    delay_count: int = TASK_DEFAULTS["normal_generate"]["delay_count"]
    speed_count: int = TASK_DEFAULTS["normal_generate"]["speed_count"]
    interruption_count: int = TASK_DEFAULTS["normal_generate"]["interruption_count"]
    combo_per_type: int = TASK_DEFAULTS["normal_generate"]["combo_per_type"]
    overwrite: bool = TASK_DEFAULTS["normal_generate"]["overwrite"]


class BuildRequest(BaseModel):
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


class AdjustmentPlanCreateRequest(BaseModel):
    plan_id: str
    exist_ok: bool = False


class AdjustmentPlanRefRequest(BaseModel):
    scenario_set_id: str
    plan_id: str


class AdjustmentPlanAnalysisRequest(BaseModel):
    plans: List[AdjustmentPlanRefRequest]


class SolveRequest(BaseModel):
    case_id: str = TASK_DEFAULTS["solve"]["case_id"]
    limit: int = TASK_DEFAULTS["solve"]["limit"]
    time_limit: Optional[float] = None
    mip_gap: Optional[float] = None
    threads: Optional[int] = None
    skip_solved: bool = TASK_DEFAULTS["solve"]["skip_solved"]


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
    checkpoint_every: int = TASK_DEFAULTS["train"]["checkpoint_every"]
    batch_size: int = TASK_DEFAULTS["train"]["batch_size"]
    lr: float = TASK_DEFAULTS["train"]["lr"]
    seed: int = TASK_DEFAULTS["train"]["seed"]
    device: str = TASK_DEFAULTS["train"]["device"]
    log_every: int = TASK_DEFAULTS["train"]["log_every"]
    count_weight: float = TASK_DEFAULTS["train"]["count_weight"]
    anchor_weight: float = TASK_DEFAULTS["train"]["anchor_weight"]
    param_weight: float = TASK_DEFAULTS["train"]["param_weight"]
    kl_weight: float = TASK_DEFAULTS["train"]["kl_weight"]
    use_relation_graph: bool = TASK_DEFAULTS["train"]["use_relation_graph"]
    relation_weight: float = TASK_DEFAULTS["train"]["relation_weight"]


class GenerationRequest(BaseModel):
    if ConfigDict is not None:
        model_config = ConfigDict(protected_namespaces=())

    model_id: str
    checkpoint: str
    scenario_set_id: str
    source_scenario_set_id: str = TASK_DEFAULTS["generation"]["source_scenario_set_id"]
    run_graph: Optional[RunGraphReferenceRequest] = None
    output_prefix: str = TASK_DEFAULTS["generation"]["output_prefix"]
    num_samples: int = TASK_DEFAULTS["generation"]["num_samples"]
    seed: int = TASK_DEFAULTS["generation"]["seed"]
    device: str = TASK_DEFAULTS["generation"]["device"]
    speed_interruption_threshold: float = TASK_DEFAULTS["generation"]["speed_interruption_threshold"]
    overwrite: bool = TASK_DEFAULTS["generation"]["overwrite"]


backend = RailGraphBackend()
api = FastAPI(title="RailDisruptLab API")
app = FastAPI(title="RailDisruptLab")


@app.on_event("startup")
def app_startup() -> None:
    backend.ensure_ready()


@api.get("/health")
def health() -> Dict[str, object]:
    return backend.health()


@api.get("/projects")
def list_projects() -> List[Dict[str, object]]:
    return backend.list_projects()


@api.get("/project-options")
def list_project_options(q: str = "", limit: int = 50) -> List[Dict[str, object]]:
    return backend.list_project_options(query=q, limit=limit)


@api.post("/projects")
def create_project(request: ProjectCreateRequest) -> Dict[str, object]:
    return backend.create_project(request.project_id)


@api.delete("/projects/{project_id}")
def delete_project(project_id: str) -> Dict[str, object]:
    return _task_response(backend.delete_project(project_id))


@api.get("/projects/{project_id}")
def get_project(project_id: str) -> Dict[str, object]:
    return backend.get_project_state(project_id)


@api.get("/projects/{project_id}/resource-options")
def list_resource_options(
    project_id: str,
    resource: str = Query(...),
    q: str = "",
    limit: int = 50,
) -> List[Dict[str, object]]:
    return backend.list_resource_options(project_id, resource, query=q, limit=limit)


@api.get("/projects/{project_id}/scenario-sets")
def list_scenario_sets(project_id: str) -> List[Dict[str, object]]:
    return backend.list_scenario_sets(project_id)


@api.get("/projects/{project_id}/run-graph-sets")
def list_run_graph_sets(project_id: str) -> List[Dict[str, object]]:
    return backend.list_run_graph_sets(project_id)


@api.post("/projects/{project_id}/run-graph-sets")
def create_run_graph_set(project_id: str, request: RunGraphSetCreateRequest) -> Dict[str, object]:
    return backend.create_run_graph_set(project_id, request.run_graph_set_id, exist_ok=request.exist_ok)


@api.delete("/projects/{project_id}/run-graph-sets/{run_graph_set_id}")
def delete_run_graph_set(project_id: str, run_graph_set_id: str) -> Dict[str, object]:
    return backend.delete_run_graph_set(project_id, run_graph_set_id)


@api.get("/projects/{project_id}/run-graph-sets/{run_graph_set_id}/run-graphs")
def list_run_graphs(project_id: str, run_graph_set_id: str) -> List[Dict[str, object]]:
    return backend.list_run_graphs(project_id, run_graph_set_id)


@api.post("/projects/{project_id}/run-graph-sets/{run_graph_set_id}/run-graphs")
def create_run_graph(
    project_id: str,
    run_graph_set_id: str,
    run_graph_id: str = Query(...),
    overwrite: bool = Query(False),
    timetable_file: UploadFile = File(...),
    mileage_file: UploadFile = File(...),
) -> Dict[str, object]:
    return _task_response(
        backend.create_run_graph(
            project_id,
            run_graph_set_id,
            run_graph_id,
            timetable_source=timetable_file.file,
            mileage_source=mileage_file.file,
            overwrite=overwrite,
        )
    )


@api.get("/projects/{project_id}/run-graph-sets/{run_graph_set_id}/run-graphs/{run_graph_id}")
def read_run_graph(project_id: str, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
    return backend.read_run_graph(project_id, run_graph_set_id, run_graph_id)


@api.get("/projects/{project_id}/run-graph-sets/{run_graph_set_id}/run-graphs/{run_graph_id}/timetable")
def read_run_graph_timetable(project_id: str, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
    return backend.read_run_graph_timetable(project_id, run_graph_set_id, run_graph_id)


@api.delete("/projects/{project_id}/run-graph-sets/{run_graph_set_id}/run-graphs/{run_graph_id}")
def delete_run_graph(project_id: str, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
    return backend.delete_run_graph(project_id, run_graph_set_id, run_graph_id)


@api.get("/projects/{project_id}/run-graph-sets/{run_graph_set_id}/run-graphs/{run_graph_id}/options")
def read_run_graph_options(project_id: str, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
    return backend.read_run_graph_options(project_id, run_graph_set_id, run_graph_id)


@api.post("/projects/{project_id}/scenario-sets")
def create_scenario_set(project_id: str, request: ScenarioSetCreateRequest) -> Dict[str, object]:
    return backend.create_scenario_set(project_id, request.scenario_set_id, exist_ok=request.exist_ok)


@api.delete("/projects/{project_id}/scenario-sets/{scenario_set_id}")
def delete_scenario_set(project_id: str, scenario_set_id: str) -> Dict[str, object]:
    return backend.delete_scenario_set(project_id, scenario_set_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios")
def list_scenarios(project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
    return backend.list_scenarios(project_id, scenario_set_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenario-options")
def list_scenario_options(
    project_id: str,
    scenario_set_id: str,
    q: str = "",
    limit: int = 50,
) -> List[Dict[str, object]]:
    return backend.list_scenario_options(project_id, scenario_set_id, query=q, limit=limit)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/visualization")
def read_scenario_set_visualization(project_id: str, scenario_set_id: str) -> Dict[str, object]:
    return backend.read_scenario_set_visualization(project_id, scenario_set_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plans")
def list_adjustment_plans(project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
    return backend.list_adjustment_plans(project_id, scenario_set_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plan-options")
def list_adjustment_plan_options(
    project_id: str,
    scenario_set_id: str,
    q: str = "",
    limit: int = 50,
) -> List[Dict[str, object]]:
    return backend.list_adjustment_plan_options(project_id, scenario_set_id, query=q, limit=limit)


@api.post("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plans")
def create_adjustment_plan(
    project_id: str,
    scenario_set_id: str,
    request: AdjustmentPlanCreateRequest,
) -> Dict[str, object]:
    return backend.create_adjustment_plan(project_id, scenario_set_id, request.plan_id, exist_ok=request.exist_ok)


@api.delete("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plans/{plan_id}")
def delete_adjustment_plan(project_id: str, scenario_set_id: str, plan_id: str) -> Dict[str, object]:
    return backend.delete_adjustment_plan(project_id, scenario_set_id, plan_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/analysis/adjustment-plan-solve")
def read_adjustment_plan_solve_analysis(
    project_id: str,
    scenario_set_id: str,
    plan_ids: List[str] = Query(...),
) -> Dict[str, object]:
    if not plan_ids:
        raise HTTPException(status_code=400, detail="plan_ids is required")
    return backend.read_adjustment_plan_solve_analysis(project_id, scenario_set_id, plan_ids)


@api.post("/projects/{project_id}/analysis/adjustment-plan-solve")
def read_project_adjustment_plan_solve_analysis(
    project_id: str,
    request: AdjustmentPlanAnalysisRequest,
) -> Dict[str, object]:
    if not request.plans:
        raise HTTPException(status_code=400, detail="plans is required")
    return backend.read_project_adjustment_plan_solve_analysis(
        project_id,
        [
            {"scenario_set_id": item.scenario_set_id, "plan_id": item.plan_id}
            for item in request.plans
        ],
    )


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios/{scenario_id}")
def read_scenario(project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    return backend.read_scenario(project_id, scenario_set_id, scenario_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios/{scenario_id}/timetable")
def read_scenario_timetable(project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    return backend.read_scenario_timetable(project_id, scenario_set_id, scenario_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios/{scenario_id}/options")
def read_scenario_options(project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    return backend.read_scenario_options(project_id, scenario_set_id, scenario_id)


@api.post("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios")
def add_scenario(project_id: str, scenario_set_id: str, request: ScenarioWriteRequest) -> Dict[str, object]:
    return backend.create_scenario_case(
        project_id,
        scenario_set_id,
        request.scenario_id,
        run_graph=request.run_graph.to_domain(),
        delays=request.delays,
        speed_limits=request.speed_limits,
        overwrite=request.overwrite,
    )


@api.put("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios/{scenario_id}/disturbances")
def update_scenario_disturbances(
    project_id: str,
    scenario_set_id: str,
    scenario_id: str,
    request: ScenarioDisturbanceWriteRequest,
) -> Dict[str, object]:
    return backend.update_scenario_disturbances(
        project_id,
        scenario_set_id,
        scenario_id,
        run_graph=request.run_graph.to_domain() if request.run_graph else None,
        delays=request.delays,
        speed_limits=request.speed_limits,
        overwrite=request.overwrite,
    )


@api.post("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios/{scenario_id}/validation")
def validate_scenario(
    project_id: str,
    scenario_set_id: str,
    scenario_id: str,
    request: ScenarioValidationRequest,
) -> Dict[str, object]:
    return backend.validate_scenario_case(
        project_id,
        scenario_set_id,
        scenario_id,
        run_graph=request.run_graph.to_domain() if request.run_graph else None,
    )


@api.delete("/projects/{project_id}/scenario-sets/{scenario_set_id}/scenarios/{scenario_id}")
def delete_scenario(project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    return _task_response(backend.delete_scenario(project_id, scenario_set_id, scenario_id))


@api.get("/projects/{project_id}/tasks")
def list_project_tasks(project_id: str) -> List[Dict[str, object]]:
    return backend.list_tasks(project_id)


@api.post("/projects/{project_id}/tasks/normal-generate")
def submit_normal_generate(project_id: str, request: NormalGenerateRequest) -> Dict[str, object]:
    return _task_response(
        backend.normal_generate(
            project_id,
            scenario_set_id=request.scenario_set_id,
            scenario_id_prefix=request.scenario_id_prefix,
            simulation_count=request.simulation_count,
            run_graph=request.run_graph.to_domain(),
            seed=request.seed,
            delay_count=request.delay_count,
            speed_count=request.speed_count,
            interruption_count=request.interruption_count,
            combo_per_type=request.combo_per_type,
            overwrite=request.overwrite,
        )
    )


@api.post("/projects/{project_id}/scenario-sets/{scenario_set_id}/tasks/validate-scenarios")
def submit_validate_scenarios(project_id: str, scenario_set_id: str) -> Dict[str, object]:
    return _task_response(backend.validate_scenario_set(project_id, scenario_set_id))


@api.post("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plans/{plan_id}/tasks/build")
def submit_build(project_id: str, scenario_set_id: str, plan_id: str, request: BuildRequest) -> Dict[str, object]:
    return _task_response(
        backend.build(
            project_id,
            scenario_set_id,
            plan_id,
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


@api.post("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plans/{plan_id}/tasks/solve")
def submit_solve(project_id: str, scenario_set_id: str, plan_id: str, request: SolveRequest) -> Dict[str, object]:
    return _task_response(
        backend.solve(
            project_id,
            scenario_set_id,
            plan_id,
            case_id=request.case_id,
            limit=request.limit,
            time_limit=request.time_limit,
            mip_gap=request.mip_gap,
            threads=request.threads,
            skip_solved=request.skip_solved,
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
            checkpoint_every=request.checkpoint_every,
            batch_size=request.batch_size,
            lr=request.lr,
            seed=request.seed,
            device=request.device,
            log_every=request.log_every,
            count_weight=request.count_weight,
            anchor_weight=request.anchor_weight,
            param_weight=request.param_weight,
            kl_weight=request.kl_weight,
            use_relation_graph=request.use_relation_graph,
            relation_weight=request.relation_weight,
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
            source_scenario_set_id=request.source_scenario_set_id,
            run_graph=request.run_graph.to_domain() if request.run_graph else None,
            output_prefix=request.output_prefix,
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


@api.delete("/tasks/{task_id}")
def remove_task(task_id: int) -> Dict[str, object]:
    return backend.remove_task(task_id)


@api.get("/tasks/{task_id}")
def get_task(task_id: int) -> Dict[str, object]:
    task = backend.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@api.get("/tasks/{task_id}/log", response_class=PlainTextResponse)
def get_task_log(task_id: int, lines: Optional[int] = None) -> str:
    return backend.task_log(task_id, lines=lines)


@api.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: int) -> Dict[str, object]:
    return backend.cancel_task(task_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plans/{plan_id}/cases/{case_id}/timetable")
def read_case_timetable(project_id: str, scenario_set_id: str, plan_id: str, case_id: str) -> Dict[str, object]:
    return backend.read_case_timetable(project_id, scenario_set_id, plan_id, case_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plans/{plan_id}/artifacts")
def list_case_artifacts(project_id: str, scenario_set_id: str, plan_id: str) -> List[Dict[str, object]]:
    return backend.list_case_artifacts(project_id, scenario_set_id, plan_id)


@api.get("/projects/{project_id}/scenario-sets/{scenario_set_id}/adjustment-plans/{plan_id}/detail")
def read_adjustment_plan_detail(project_id: str, scenario_set_id: str, plan_id: str) -> Dict[str, object]:
    return backend.read_adjustment_plan_detail(project_id, scenario_set_id, plan_id)


@api.get("/projects/{project_id}/models/{model_id}/training-summary")
def read_training_summary(project_id: str, model_id: str) -> Dict[str, object]:
    return backend.read_training_summary(project_id, model_id)


@api.get("/projects/{project_id}/models/{model_id}/detail")
def read_model_detail(project_id: str, model_id: str) -> Dict[str, object]:
    return backend.read_model_detail(project_id, model_id)


@api.get("/projects/{project_id}/models/{model_id}/files")
def list_model_files(project_id: str, model_id: str) -> List[Dict[str, object]]:
    return backend.list_model_files(project_id, model_id)


@api.delete("/projects/{project_id}/models/{model_id}")
def delete_model(project_id: str, model_id: str) -> Dict[str, object]:
    return backend.delete_model(project_id, model_id)


def _task_response(task: Dict[str, object]) -> Dict[str, object]:
    return {"task": task}


@api.exception_handler(PueueError)
def pueue_exception_handler(_request, exc: PueueError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@api.exception_handler(FileNotFoundError)
def not_found_exception_handler(_request, exc: FileNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@api.exception_handler(TaskResourceConflict)
def task_resource_conflict_handler(_request, exc: TaskResourceConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@api.exception_handler(ValueError)
def value_error_exception_handler(_request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


frontend_dist = REPO_ROOT / "frontend" / "dist"
app.mount("/api", api)
if (frontend_dist / "index.html").is_file():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:

    @app.get("/", include_in_schema=False)
    def frontend_not_built() -> PlainTextResponse:
        return PlainTextResponse(
            "Frontend build is missing. Run: pnpm --dir frontend build",
            status_code=503,
        )

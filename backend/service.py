from __future__ import annotations

import json
from datetime import datetime
import sys
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from backend.analysis.adjustment_plan import (
    read_adjustment_plan_detail,
    read_adjustment_plan_solve_analysis,
    read_project_adjustment_plan_solve_analysis,
)
from backend.scenario_cases import (
    create_scenario_case,
    list_scenario_case_options,
    read_scenario_set_analysis,
    read_scenario_timetable,
    update_scenario_disturbances,
    validate_scenario_case,
)
from backend.analysis.timetable import read_case_timetable
from backend.lifecycle import delete_adjustment_plan, delete_model, delete_scenario_set, ensure_no_active_reference
from backend.pueue_client import PueueClient
from backend.repository import ProjectRepository
from backend.run_graphs import (
    create_run_graph_set,
    delete_run_graph,
    delete_run_graph_set,
    list_run_graphs,
    list_run_graph_sets,
    read_run_graph,
    read_run_graph_options,
    read_run_graph_timetable,
)
from backend.scenarios import create_scenario_set as create_scenario_set_dir, read_scenario_options
from backend.task_contracts import TASK_DEFAULTS, normalize_project_id, normalize_task_params
from backend.task_resources import RUNNING_TASK_STATUSES, ensure_no_active_conflict
from backend.workflow import create_adjustment_plan as create_adjustment_plan_dir, new_project
from core.project_layout import PROJECTS_ROOT, REPO_ROOT, require_id, sanitize_id, to_posix
from core.scenario_config import RunGraphReference

RESOURCE_OPTION_LABELS = {
    "scenario_sets": ("scenario_set_id", "case_count"),
    "run_graph_sets": ("run_graph_set_id", "run_graph_count"),
    "models": ("model_id", "sample_count"),
}


def resource_option_label(value: str, count: object) -> str:
    if isinstance(count, int):
        return "{} ({})".format(value, count)
    return value


def write_upload_source(source: Any, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(source, bytes):
        target.write_bytes(source)
        return
    with target.open("wb") as output:
        shutil.copyfileobj(source, output)


class RailGraphBackend:
    def __init__(
        self,
        *,
        projects_root: Path = PROJECTS_ROOT,
        repo_root: Path = REPO_ROOT,
        python_executable: str = sys.executable,
    ):
        self.repository = ProjectRepository(projects_root=projects_root)
        self.tasks = PueueClient(python_executable=python_executable, repo_root=repo_root)

    def ensure_ready(self) -> None:
        self.tasks.ensure_ready()

    def health(self) -> Dict[str, object]:
        return {
            "ok": True,
            "projects_root": to_posix(self.repository.projects_root),
            "task_backend": self.tasks.health(),
        }

    def list_projects(self) -> List[Dict[str, object]]:
        return self.repository.list_projects()

    def list_project_options(self, *, query: str = "", limit: int = 50) -> List[Dict[str, object]]:
        query_text = query.strip().lower()
        result: List[Dict[str, object]] = []
        for item in self.repository.list_projects():
            value = str(item.get("project_id", "") or "")
            if query_text and query_text not in value.lower():
                continue
            result.append({"label": value, "value": value})
            if len(result) >= max(1, limit):
                break
        return result

    def get_project_state(self, project_id: str) -> Dict[str, object]:
        return self.repository.get_project_state(project_id)

    def list_scenario_sets(self, project_id: str) -> List[Dict[str, object]]:
        return self.repository.list_scenario_sets(project_id)

    def list_run_graph_sets(self, project_id: str) -> List[Dict[str, object]]:
        return list_run_graph_sets(self.repository.layout(project_id))

    def create_run_graph_set(self, project_id: str, run_graph_set_id: str, *, exist_ok: bool = False) -> Dict[str, object]:
        return create_run_graph_set(self.repository.layout(project_id), run_graph_set_id, exist_ok=exist_ok)

    def delete_run_graph_set(self, project_id: str, run_graph_set_id: str) -> Dict[str, object]:
        self.ensure_no_resource_conflict(
            project_id,
            action="run_graph_set_delete",
            params={"run_graph_set_id": run_graph_set_id},
        )
        return delete_run_graph_set(self.repository.layout(project_id), run_graph_set_id)

    def list_run_graphs(self, project_id: str, run_graph_set_id: str) -> List[Dict[str, object]]:
        return list_run_graphs(self.repository.layout(project_id), run_graph_set_id)

    def create_run_graph(
        self,
        project_id: str,
        run_graph_set_id: str,
        run_graph_id: str,
        *,
        timetable_source: Any,
        mileage_source: Any,
        overwrite: bool = False,
    ) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        run_graph_set_id = require_id(run_graph_set_id, "run_graph_set_id")
        run_graph_id = require_id(run_graph_id, "run_graph_id")
        task_root = self._new_task_root(project_id, "run_graph_build")
        source_dir = task_root / "source"
        source_dir.mkdir(parents=True, exist_ok=False)
        timetable_path = source_dir / "timetable.xlsx"
        mileage_path = source_dir / "mileage.xlsx"
        write_upload_source(timetable_source, timetable_path)
        write_upload_source(mileage_source, mileage_path)
        try:
            return self.submit_task(
                project_id,
                "run_graph_build",
                {
                    "run_graph": {"set_id": run_graph_set_id, "graph_id": run_graph_id},
                    "timetable_path": to_posix(timetable_path),
                    "mileage_path": to_posix(mileage_path),
                    "overwrite": overwrite,
                },
                label="run_graph_build",
                task_root=task_root,
            )
        except Exception:
            shutil.rmtree(task_root, ignore_errors=True)
            raise

    def read_run_graph(self, project_id: str, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
        return read_run_graph(self.repository.layout(project_id), run_graph_set_id, run_graph_id)

    def read_run_graph_timetable(self, project_id: str, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
        return read_run_graph_timetable(self.repository.layout(project_id), run_graph_set_id, run_graph_id)

    def delete_run_graph(self, project_id: str, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
        self.ensure_no_resource_conflict(
            project_id,
            action="run_graph_write",
            params={"run_graph": {"set_id": run_graph_set_id, "graph_id": run_graph_id}},
        )
        return delete_run_graph(self.repository.layout(project_id), run_graph_set_id, run_graph_id)

    def read_run_graph_options(self, project_id: str, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
        return read_run_graph_options(self.repository.layout(project_id), run_graph_set_id, run_graph_id)

    def list_resource_options(
        self,
        project_id: str,
        resource: str,
        *,
        query: str = "",
        limit: int = 50,
    ) -> List[Dict[str, object]]:
        if resource not in RESOURCE_OPTION_LABELS:
            raise ValueError("Unsupported resource: {}".format(resource))
        items = self._resource_items(project_id, resource)
        id_key, count_key = RESOURCE_OPTION_LABELS[resource]
        query_text = query.strip().lower()
        result: List[Dict[str, object]] = []
        for item in items:
            value = str(item.get(id_key, "") or "")
            label = resource_option_label(value, item.get(count_key))
            if query_text and query_text not in value.lower() and query_text not in label.lower():
                continue
            result.append({"label": label, "value": value})
            if len(result) >= max(1, limit):
                break
        return result

    def _resource_items(self, project_id: str, resource: str) -> List[Dict[str, object]]:
        if resource == "scenario_sets":
            return self.repository.list_scenario_sets(project_id)
        if resource == "run_graph_sets":
            return self.list_run_graph_sets(project_id)
        if resource == "models":
            return self.repository.list_models(project_id)
        raise ValueError("Unsupported resource: {}".format(resource))

    def list_adjustment_plans(self, project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
        return self.repository.list_adjustment_plans(project_id, scenario_set_id)

    def list_adjustment_plan_options(
        self,
        project_id: str,
        scenario_set_id: str,
        *,
        query: str = "",
        limit: int = 50,
    ) -> List[Dict[str, object]]:
        query_text = query.strip().lower()
        result: List[Dict[str, object]] = []
        for item in self.repository.list_adjustment_plans(project_id, scenario_set_id):
            value = str(item.get("plan_id", "") or "")
            label = resource_option_label(value, item.get("case_count"))
            if query_text and query_text not in value.lower() and query_text not in label.lower():
                continue
            result.append({"label": label, "value": value})
            if len(result) >= max(1, limit):
                break
        return result

    def list_scenarios(self, project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
        self.ensure_no_scenario_set_read_conflict(project_id, scenario_set_id)
        return self.repository.list_scenarios(project_id, scenario_set_id)

    def list_scenario_options(
        self,
        project_id: str,
        scenario_set_id: str,
        *,
        query: str = "",
        limit: int = 50,
    ) -> List[Dict[str, object]]:
        return list_scenario_case_options(
            self.repository.layout(project_id),
            scenario_set_id,
            query=query,
            limit=limit,
        )

    def read_scenario(self, project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
        self.ensure_no_scenario_case_read_conflict(project_id, scenario_set_id, scenario_id)
        return self.repository.read_scenario(project_id, scenario_set_id, scenario_id)

    def read_scenario_timetable(self, project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
        self.ensure_no_scenario_case_read_conflict(project_id, scenario_set_id, scenario_id)
        return read_scenario_timetable(self.repository.layout(project_id), scenario_set_id, scenario_id)

    def read_scenario_options(self, project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
        self.ensure_no_scenario_case_read_conflict(project_id, scenario_set_id, scenario_id)
        return read_scenario_options(self.repository.layout(project_id), scenario_set_id, scenario_id)

    def read_scenario_set_visualization(self, project_id: str, scenario_set_id: str) -> Dict[str, object]:
        self.ensure_no_scenario_set_read_conflict(project_id, scenario_set_id)
        return read_scenario_set_analysis(self.repository.layout(project_id), scenario_set_id)

    def create_scenario_case(
        self,
        project_id: str,
        scenario_set_id: str,
        scenario_id: str,
        *,
        run_graph: RunGraphReference,
        delays: List[Dict[str, object]] | None = None,
        speed_limits: List[Dict[str, object]] | None = None,
        overwrite: bool = False,
    ) -> Dict[str, object]:
        self.ensure_no_scenario_case_conflict(project_id, scenario_set_id, scenario_id)
        return create_scenario_case(
            self.repository.layout(project_id),
            scenario_set_id,
            scenario_id,
            run_graph=run_graph,
            delays=delays or [],
            speed_limits=speed_limits or [],
            overwrite=overwrite,
        )

    def update_scenario_disturbances(
        self,
        project_id: str,
        scenario_set_id: str,
        scenario_id: str,
        *,
        run_graph: RunGraphReference | None = None,
        delays: List[Dict[str, object]],
        speed_limits: List[Dict[str, object]],
        overwrite: bool = False,
    ) -> Dict[str, object]:
        self.ensure_no_scenario_case_conflict(project_id, scenario_set_id, scenario_id)
        return update_scenario_disturbances(
            self.repository.layout(project_id),
            scenario_set_id,
            scenario_id,
            run_graph=run_graph,
            delays=delays,
            speed_limits=speed_limits,
            overwrite=overwrite,
        )

    def validate_scenario_case(
        self,
        project_id: str,
        scenario_set_id: str,
        scenario_id: str,
        *,
        run_graph: RunGraphReference | None = None,
    ) -> Dict[str, object]:
        self.ensure_no_scenario_case_conflict(project_id, scenario_set_id, scenario_id)
        return validate_scenario_case(
            self.repository.layout(project_id),
            scenario_set_id,
            scenario_id,
            run_graph=run_graph,
        )

    def ensure_no_scenario_case_conflict(
        self,
        project_id: str,
        scenario_set_id: str,
        scenario_id: str,
        *,
        action: str = "scenario_add",
    ) -> None:
        self.ensure_no_resource_conflict(
            project_id,
            action=action,
            params={
                "scenario_set_id": scenario_set_id,
                "scenario_id": scenario_id,
            },
        )

    def ensure_no_scenario_set_read_conflict(self, project_id: str, scenario_set_id: str) -> None:
        self.ensure_no_resource_conflict(
            project_id,
            action="scenario_set_read",
            params={"scenario_set_id": scenario_set_id},
        )

    def ensure_no_scenario_case_read_conflict(
        self,
        project_id: str,
        scenario_set_id: str,
        scenario_id: str,
    ) -> None:
        self.ensure_no_resource_conflict(
            project_id,
            action="scenario_case_read",
            params={"scenario_set_id": scenario_set_id, "scenario_id": scenario_id},
        )

    def ensure_no_adjustment_plan_read_conflict(
        self,
        project_id: str,
        scenario_set_id: str,
        plan_id: str,
    ) -> None:
        self.ensure_no_resource_conflict(
            project_id,
            action="adjustment_plan_read",
            params={"scenario_set_id": scenario_set_id, "plan_id": plan_id},
        )

    def ensure_no_adjustment_plan_case_read_conflict(
        self,
        project_id: str,
        scenario_set_id: str,
        plan_id: str,
        case_id: str,
    ) -> None:
        self.ensure_no_resource_conflict(
            project_id,
            action="adjustment_plan_case_read",
            params={"scenario_set_id": scenario_set_id, "plan_id": plan_id, "case_id": case_id},
        )

    def ensure_no_resource_conflict(
        self,
        project_id: str,
        *,
        action: str,
        params: Dict[str, Any],
        active_tasks: List[Dict[str, object]] | None = None,
    ) -> None:
        project_id = normalize_project_id(project_id)
        ensure_no_active_conflict(
            active_tasks if active_tasks is not None else self.tasks.list_active_tasks(group=project_id),
            action=action,
            params=params,
        )

    def read_case_timetable(self, project_id: str, scenario_set_id: str, plan_id: str, case_id: str) -> Dict[str, object]:
        self.ensure_no_adjustment_plan_case_read_conflict(project_id, scenario_set_id, plan_id, case_id)
        return read_case_timetable(self.repository.layout(project_id), scenario_set_id, plan_id, case_id)

    def list_case_artifacts(self, project_id: str, scenario_set_id: str, plan_id: str) -> List[Dict[str, object]]:
        return self.repository.list_case_artifacts(project_id, scenario_set_id, plan_id)

    def read_adjustment_plan_detail(self, project_id: str, scenario_set_id: str, plan_id: str) -> Dict[str, object]:
        return read_adjustment_plan_detail(self.repository.layout(project_id), scenario_set_id, plan_id)

    def read_adjustment_plan_solve_analysis(
        self,
        project_id: str,
        scenario_set_id: str,
        plan_ids: List[str],
    ) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        active_tasks = self.tasks.list_active_tasks(group=project_id)
        for plan_id in plan_ids:
            self.ensure_no_resource_conflict(
                project_id,
                action="adjustment_plan_read",
                params={"scenario_set_id": scenario_set_id, "plan_id": plan_id},
                active_tasks=active_tasks,
            )
        return read_adjustment_plan_solve_analysis(self.repository.layout(project_id), scenario_set_id, plan_ids)

    def read_project_adjustment_plan_solve_analysis(
        self,
        project_id: str,
        plan_refs: List[Dict[str, object]],
    ) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        active_tasks = self.tasks.list_active_tasks(group=project_id)
        for ref in plan_refs:
            self.ensure_no_resource_conflict(
                project_id,
                action="adjustment_plan_read",
                params={
                    "scenario_set_id": str(ref.get("scenario_set_id") or ""),
                    "plan_id": str(ref.get("plan_id") or ""),
                },
                active_tasks=active_tasks,
            )
        return read_project_adjustment_plan_solve_analysis(self.repository.layout(project_id), plan_refs)

    def read_training_summary(self, project_id: str, model_id: str) -> Dict[str, object]:
        return self.repository.read_training_summary(project_id, model_id)

    def read_model_detail(self, project_id: str, model_id: str) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        model_id = require_id(model_id, "model_id")
        detail = self.repository.read_model_detail(project_id, model_id)
        return merge_model_task_progress(detail, latest_train_task(self.tasks.list_tasks(group=project_id), model_id))

    def list_model_files(self, project_id: str, model_id: str) -> List[Dict[str, object]]:
        return self.repository.list_model_files(project_id, model_id)

    def delete_model(self, project_id: str, model_id: str) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        model_id = require_id(model_id, "model_id")
        ensure_no_active_reference(
            self.tasks.list_active_tasks(group=project_id),
            field="model_id",
            value=model_id,
            action_labels=("train", "generation"),
        )
        return delete_model(self.repository.layout(project_id), model_id)

    def list_tasks(self, project_id: Optional[str] = None) -> List[Dict[str, object]]:
        return self.tasks.list_tasks(group=project_id)

    def get_task(self, task_id: Union[str, int]) -> Optional[Dict[str, object]]:
        return self.tasks.get_task(task_id)

    def task_log(self, task_id: Union[str, int], *, lines: Optional[int] = None) -> str:
        return self.tasks.log(task_id, lines=lines)

    def cancel_task(self, task_id: Union[str, int]) -> Dict[str, object]:
        return self.tasks.cancel(task_id)

    def remove_task(self, task_id: Union[str, int]) -> Dict[str, object]:
        return self.tasks.remove_task(task_id)

    def create_project(self, project_id: str) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        new_project(self.repository.layout(project_id))
        return self.repository.get_project_state(project_id)

    def delete_project(self, project_id: str) -> Dict[str, object]:
        return self.submit_task(project_id, "deleteproject", {}, label="deleteproject")

    def create_scenario_set(self, project_id: str, scenario_set_id: str, *, exist_ok: bool = False) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
        create_scenario_set_dir(self.repository.layout(project_id), scenario_set_id, exist_ok=exist_ok)
        for item in self.repository.list_scenario_sets(project_id):
            if item["scenario_set_id"] == scenario_set_id:
                return item
        raise FileNotFoundError(f"Scenario set not found after create: {scenario_set_id}")

    def delete_scenario_set(self, project_id: str, scenario_set_id: str) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
        ensure_no_active_conflict(
            self.tasks.list_active_tasks(group=project_id),
            action="scenario_set_delete",
            params={"scenario_set_id": scenario_set_id},
        )
        return delete_scenario_set(self.repository.layout(project_id), scenario_set_id)

    def validate_scenario_set(self, project_id: str, scenario_set_id: str) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
        return self.submit_task(
            project_id,
            "scenario_set_validate",
            {"scenario_set_id": scenario_set_id},
            label="scenario_set_validate",
        )

    def add_scenario(
        self,
        project_id: str,
        scenario_set_id: str,
        scenario_id: str,
        *,
        delays: List[Dict[str, object]],
        speed_limits: List[Dict[str, object]],
        run_graph: RunGraphReference,
        overwrite: bool = False,
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "scenario_add",
            {
                "scenario_set_id": scenario_set_id,
                "scenario_id": scenario_id,
                "run_graph": run_graph.to_payload(),
                "delays": delays,
                "speed_limits": speed_limits,
                "overwrite": overwrite,
            },
            label="scenario_add",
        )

    def delete_scenario(self, project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "scenario_delete",
            {"scenario_set_id": scenario_set_id, "scenario_id": scenario_id},
            label="scenario_delete",
        )

    def normal_generate(
        self,
        project_id: str,
        *,
        scenario_set_id: str,
        scenario_id_prefix: str = "",
        simulation_count: int = 1,
        run_graph: RunGraphReference,
        seed: int = TASK_DEFAULTS["normal_generate"]["seed"],
        delay_count: int = TASK_DEFAULTS["normal_generate"]["delay_count"],
        speed_count: int = TASK_DEFAULTS["normal_generate"]["speed_count"],
        interruption_count: int = TASK_DEFAULTS["normal_generate"]["interruption_count"],
        combo_per_type: int = TASK_DEFAULTS["normal_generate"]["combo_per_type"],
        overwrite: bool = TASK_DEFAULTS["normal_generate"]["overwrite"],
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "normal_generate",
            {
                "scenario_set_id": scenario_set_id,
                "scenario_id_prefix": scenario_id_prefix,
                "simulation_count": simulation_count,
                "run_graph": run_graph.to_payload(),
                "seed": seed,
                "delay_count": delay_count,
                "speed_count": speed_count,
                "interruption_count": interruption_count,
                "combo_per_type": combo_per_type,
                "overwrite": overwrite,
            },
            label="normal_generate",
        )

    def create_adjustment_plan(
        self,
        project_id: str,
        scenario_set_id: str,
        plan_id: str,
        *,
        exist_ok: bool = False,
    ) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
        plan_id = require_id(plan_id, "plan_id")
        create_adjustment_plan_dir(self.repository.layout(project_id), scenario_set_id, plan_id, exist_ok=exist_ok)
        for item in self.repository.list_adjustment_plans(project_id, scenario_set_id):
            if item["plan_id"] == plan_id:
                return item
        raise FileNotFoundError(f"Adjustment plan not found after create: {scenario_set_id}/{plan_id}")

    def delete_adjustment_plan(self, project_id: str, scenario_set_id: str, plan_id: str) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
        plan_id = require_id(plan_id, "plan_id")
        ensure_no_active_conflict(
            self.tasks.list_active_tasks(group=project_id),
            action="adjustment_plan_delete",
            params={"scenario_set_id": scenario_set_id, "plan_id": plan_id},
        )
        return delete_adjustment_plan(self.repository.layout(project_id), scenario_set_id, plan_id)

    def build(
        self,
        project_id: str,
        scenario_set_id: str,
        plan_id: str,
        *,
        scenario_id: str = TASK_DEFAULTS["build"]["scenario_id"],
        objective_delay_weight: float = TASK_DEFAULTS["build"]["objective_delay_weight"],
        objective_mode: str = TASK_DEFAULTS["build"]["objective_mode"],
        cancellation_enabled: bool = TASK_DEFAULTS["build"]["cancellation_enabled"],
        cancellation_penalty_weight: float = TASK_DEFAULTS["build"]["cancellation_penalty_weight"],
        arr_arr_headway_seconds: int = TASK_DEFAULTS["build"]["arr_arr_headway_seconds"],
        dep_dep_headway_seconds: int = TASK_DEFAULTS["build"]["dep_dep_headway_seconds"],
        dwell_seconds_at_stops: int = TASK_DEFAULTS["build"]["dwell_seconds_at_stops"],
        big_m: int = TASK_DEFAULTS["build"]["big_m"],
        tolerance_delay_seconds: int = TASK_DEFAULTS["build"]["tolerance_delay_seconds"],
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "build",
            {
                "scenario_set_id": scenario_set_id,
                "plan_id": plan_id,
                "scenario_id": scenario_id,
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
            label="build",
        )

    def solve(
        self,
        project_id: str,
        scenario_set_id: str,
        plan_id: str,
        *,
        case_id: str = TASK_DEFAULTS["solve"]["case_id"],
        limit: int = TASK_DEFAULTS["solve"]["limit"],
        time_limit: Optional[float] = None,
        mip_gap: Optional[float] = None,
        threads: Optional[int] = None,
        skip_solved: bool = TASK_DEFAULTS["solve"]["skip_solved"],
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "solve",
            {
                "scenario_set_id": scenario_set_id,
                "plan_id": plan_id,
                "case_id": case_id,
                "limit": limit,
                "time_limit": time_limit,
                "mip_gap": mip_gap,
                "threads": threads,
                "skip_solved": skip_solved,
            },
            label="solve",
        )

    def train(
        self,
        project_id: str,
        model_id: str,
        scenario_set_id: str,
        *,
        max_slots: int = TASK_DEFAULTS["train"]["max_slots"],
        event_time_window: int = TASK_DEFAULTS["train"]["event_time_window"],
        event_top_k: int = TASK_DEFAULTS["train"]["event_top_k"],
        section_order_window: int = TASK_DEFAULTS["train"]["section_order_window"],
        hidden_dim: int = TASK_DEFAULTS["train"]["hidden_dim"],
        latent_dim: int = TASK_DEFAULTS["train"]["latent_dim"],
        message_passing_steps: int = TASK_DEFAULTS["train"]["message_passing_steps"],
        epochs: int = TASK_DEFAULTS["train"]["epochs"],
        checkpoint_every: int = TASK_DEFAULTS["train"]["checkpoint_every"],
        batch_size: int = TASK_DEFAULTS["train"]["batch_size"],
        lr: float = TASK_DEFAULTS["train"]["lr"],
        seed: int = TASK_DEFAULTS["train"]["seed"],
        device: str = TASK_DEFAULTS["train"]["device"],
        log_every: int = TASK_DEFAULTS["train"]["log_every"],
        count_weight: float = TASK_DEFAULTS["train"]["count_weight"],
        anchor_weight: float = TASK_DEFAULTS["train"]["anchor_weight"],
        param_weight: float = TASK_DEFAULTS["train"]["param_weight"],
        kl_weight: float = TASK_DEFAULTS["train"]["kl_weight"],
        use_relation_graph: bool = TASK_DEFAULTS["train"]["use_relation_graph"],
        relation_weight: float = TASK_DEFAULTS["train"]["relation_weight"],
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "train",
            {
                "model_id": model_id,
                "scenario_set_id": scenario_set_id,
                "max_slots": max_slots,
                "event_time_window": event_time_window,
                "event_top_k": event_top_k,
                "section_order_window": section_order_window,
                "hidden_dim": hidden_dim,
                "latent_dim": latent_dim,
                "message_passing_steps": message_passing_steps,
                "epochs": epochs,
                "checkpoint_every": checkpoint_every,
                "batch_size": batch_size,
                "lr": lr,
                "seed": seed,
                "device": device,
                "log_every": log_every,
                "count_weight": count_weight,
                "anchor_weight": anchor_weight,
                "param_weight": param_weight,
                "kl_weight": kl_weight,
                "use_relation_graph": use_relation_graph,
                "relation_weight": relation_weight,
            },
            label="train",
        )

    def generation(
        self,
        project_id: str,
        model_id: str,
        checkpoint: str,
        scenario_set_id: str,
        *,
        source_scenario_set_id: str = TASK_DEFAULTS["generation"]["source_scenario_set_id"],
        run_graph: RunGraphReference | None = None,
        output_prefix: str = TASK_DEFAULTS["generation"]["output_prefix"],
        num_samples: int = TASK_DEFAULTS["generation"]["num_samples"],
        seed: int = TASK_DEFAULTS["generation"]["seed"],
        device: str = TASK_DEFAULTS["generation"]["device"],
        speed_interruption_threshold: float = TASK_DEFAULTS["generation"]["speed_interruption_threshold"],
        overwrite: bool = TASK_DEFAULTS["generation"]["overwrite"],
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "generation",
            {
                "model_id": model_id,
                "checkpoint": checkpoint,
                "scenario_set_id": scenario_set_id,
                "source_scenario_set_id": source_scenario_set_id,
                "run_graph": run_graph.to_payload() if run_graph else {},
                "output_prefix": output_prefix,
                "num_samples": num_samples,
                "seed": seed,
                "device": device,
                "speed_interruption_threshold": speed_interruption_threshold,
                "overwrite": overwrite,
            },
            label="generation",
        )

    def submit_task(
        self,
        project_id: str,
        action: str,
        params: Dict[str, Any],
        *,
        label: str,
        task_root: Path | None = None,
    ) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        params = normalize_task_params(action, params)
        ensure_no_active_conflict(
            self.tasks.list_active_tasks(group=project_id),
            action=action,
            params=params,
        )
        task_input = self._write_task_input(project_id, action, params, task_root=task_root)
        return self.tasks.submit_runner(project_id, task_input, label=label)

    def _new_task_root(self, project_id: str, action: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return self.tasks.repo_root / "var" / "tasks" / project_id / f"{stamp}_{sanitize_id(action)}"

    def _write_task_input(
        self,
        project_id: str,
        action: str,
        params: Dict[str, Any],
        *,
        task_root: Path | None = None,
    ) -> Path:
        root = task_root or self._new_task_root(project_id, action)
        root.mkdir(parents=True, exist_ok=task_root is not None)
        path = root / "input.json"
        payload = {
            "action": action,
            "project_id": project_id,
            "params": params,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path


def latest_train_task(tasks: List[Dict[str, object]], model_id: str) -> Dict[str, object] | None:
    candidates = [
        task
        for task in tasks
        if str(task.get("action") or task.get("label") or "") == "train"
        and str(dict_value(task.get("params")).get("model_id") or "") == model_id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda task: int(task.get("id") or 0))


def merge_model_task_progress(
    detail: Dict[str, object],
    task: Dict[str, object] | None,
) -> Dict[str, object]:
    if task is None:
        return detail
    progress = dict_value(detail.get("training_progress"))
    status = str(task.get("status") or "")
    if status in RUNNING_TASK_STATUSES:
        if progress.get("status") == "idle":
            progress["status"] = "graphing"
            progress["label"] = "构建训练图"
            progress["detail"] = "训练任务已提交"
        elif progress.get("status") == "incomplete":
            progress["status"] = "training"
        progress["task"] = task_summary(task)
    elif task_failed(task) and progress.get("status") != "ready":
        progress["status"] = "failed"
        progress["label"] = "训练异常"
        progress["detail"] = "任务日志中包含异常退出信息"
        progress["task"] = task_summary(task)
    detail["training_progress"] = progress
    return detail


def task_failed(task: Dict[str, object]) -> bool:
    status = str(task.get("status") or "")
    if status in {"Failed", "Killed"}:
        return True
    return status == "Done" and detail_indicates_failure(task.get("status_detail"))


def detail_indicates_failure(detail: object) -> bool:
    if detail is None:
        return False
    if isinstance(detail, str):
        return failure_text(detail)
    if isinstance(detail, (int, float, bool)):
        return False
    if isinstance(detail, list):
        return any(detail_indicates_failure(item) for item in detail)
    if isinstance(detail, dict):
        return any(
            failure_text(str(key))
            or (
                isinstance(value, (int, float))
                and value != 0
                and any(token in str(key).lower() for token in ("exit", "code", "status"))
            )
            or detail_indicates_failure(value)
            for key, value in detail.items()
        )
    return False


def failure_text(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("fail", "error", "killed", "signal", "non-zero", "nonzero"))


def task_summary(task: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": task.get("id"),
        "status": task.get("status"),
        "display_name": task.get("display_name"),
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
    }


def dict_value(value: object) -> Dict[str, object]:
    return value if isinstance(value, dict) else {}

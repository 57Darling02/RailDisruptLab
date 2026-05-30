from __future__ import annotations

import json
from datetime import datetime
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from backend.analysis.dataset import read_dataset_solve_analysis
from backend.analysis.scenario_set import read_scenario_set_visualization
from backend.analysis.timetable import read_case_timetable, read_plan_timetable
from backend.lifecycle import delete_dataset, delete_model, delete_scenario_set, ensure_no_active_reference
from backend.pueue_client import PueueClient
from backend.repository import ProjectRepository
from backend.scenarios import read_scenario_options
from backend.task_contracts import TASK_DEFAULTS, normalize_project_id, normalize_task_params
from backend.task_resources import ensure_no_active_conflict
from core.project_layout import PROJECTS_ROOT, REPO_ROOT, require_id, sanitize_id, to_posix


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

    def get_project_state(self, project_id: str) -> Dict[str, object]:
        return self.repository.get_project_state(project_id)

    def list_scenario_sets(self, project_id: str) -> List[Dict[str, object]]:
        return self.repository.list_scenario_sets(project_id)

    def list_scenarios(self, project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
        return self.repository.list_scenarios(project_id, scenario_set_id)

    def read_scenario(self, project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
        return self.repository.read_scenario(project_id, scenario_set_id, scenario_id)

    def read_scenario_options(self, project_id: str) -> Dict[str, object]:
        return read_scenario_options(self.repository.layout(project_id))

    def read_scenario_set_visualization(self, project_id: str, scenario_set_id: str) -> Dict[str, object]:
        return read_scenario_set_visualization(self.repository.layout(project_id), scenario_set_id)

    def save_source_file(self, project_id: str, filename: str, content: bytes) -> str:
        return to_posix(self.repository.save_source_file(project_id, filename, content))

    def activate_plan(
        self,
        project_id: str,
        *,
        timetable_filename: str,
        timetable_content: bytes,
        mileage_filename: str,
        mileage_content: bytes,
        timetable_sheet_name: str = TASK_DEFAULTS["prepare"]["timetable_sheet_name"],
        mileage_sheet_name: str = TASK_DEFAULTS["prepare"]["mileage_sheet_name"],
    ) -> Dict[str, object]:
        timetable_path = self.repository.save_source_file(project_id, timetable_filename, timetable_content)
        mileage_path = self.repository.save_source_file(project_id, mileage_filename, mileage_content)
        return self.prepare(
            project_id,
            timetable_filename=timetable_path.name,
            mileage_filename=mileage_path.name,
            timetable_sheet_name=timetable_sheet_name,
            mileage_sheet_name=mileage_sheet_name,
        )

    def read_case_timetable(self, project_id: str, dataset_id: str, case_id: str) -> Dict[str, object]:
        return read_case_timetable(self.repository.layout(project_id), dataset_id, case_id)

    def read_plan_timetable(self, project_id: str) -> Dict[str, object]:
        return read_plan_timetable(self.repository.layout(project_id))

    def list_case_artifacts(self, project_id: str, dataset_id: str) -> List[Dict[str, object]]:
        return self.repository.list_case_artifacts(project_id, dataset_id)

    def read_dataset_solve_analysis(self, project_id: str, dataset_ids: List[str]) -> Dict[str, object]:
        return read_dataset_solve_analysis(self.repository.layout(project_id), dataset_ids)

    def read_training_summary(self, project_id: str, model_id: str) -> Dict[str, object]:
        return self.repository.read_training_summary(project_id, model_id)

    def read_model_detail(self, project_id: str, model_id: str) -> Dict[str, object]:
        return self.repository.read_model_detail(project_id, model_id)

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
        return self.submit_task(project_id, "newproject", {}, label="newproject")

    def delete_project(self, project_id: str) -> Dict[str, object]:
        return self.submit_task(project_id, "deleteproject", {}, label="deleteproject")

    def source_file_path(self, project_id: str, filename: str) -> Path:
        return self.repository.source_file_path(project_id, filename)

    def delete_source_file(self, project_id: str, filename: str) -> Dict[str, object]:
        return self.submit_task(project_id, "source_delete", {"filename": filename}, label="source_delete")

    def create_scenario_set(self, project_id: str, scenario_set_id: str, *, exist_ok: bool = False) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "scenario_set_create",
            {"scenario_set_id": scenario_set_id, "exist_ok": exist_ok},
            label="scenario_set_create",
        )

    def delete_scenario_set(self, project_id: str, scenario_set_id: str) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
        ensure_no_active_reference(
            self.tasks.list_active_tasks(group=project_id),
            field="scenario_set_id",
            value=scenario_set_id,
            action_labels=(
                "scenario_set_create",
                "normal_generate",
                "scenario_add",
                "scenario_delete",
                "build",
                "train",
                "generation",
            ),
        )
        return delete_scenario_set(self.repository.layout(project_id), scenario_set_id)

    def add_scenario(
        self,
        project_id: str,
        scenario_set_id: str,
        scenario_id: str,
        *,
        delays: List[Dict[str, object]],
        speed_limits: List[Dict[str, object]],
        overwrite: bool = False,
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "scenario_add",
            {
                "scenario_set_id": scenario_set_id,
                "scenario_id": scenario_id,
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

    def prepare(
        self,
        project_id: str,
        *,
        timetable_filename: str,
        mileage_filename: str,
        timetable_sheet_name: str = TASK_DEFAULTS["prepare"]["timetable_sheet_name"],
        mileage_sheet_name: str = TASK_DEFAULTS["prepare"]["mileage_sheet_name"],
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "prepare",
            {
                "timetable_filename": timetable_filename,
                "mileage_filename": mileage_filename,
                "timetable_sheet_name": timetable_sheet_name,
                "mileage_sheet_name": mileage_sheet_name,
            },
            label="prepare",
        )

    def normal_generate(
        self,
        project_id: str,
        *,
        scenario_set_id: str,
        seed: int = TASK_DEFAULTS["normal_generate"]["seed"],
        delay_count: int = TASK_DEFAULTS["normal_generate"]["delay_count"],
        speed_count: int = TASK_DEFAULTS["normal_generate"]["speed_count"],
        interruption_count: int = TASK_DEFAULTS["normal_generate"]["interruption_count"],
        combo_per_type: int = TASK_DEFAULTS["normal_generate"]["combo_per_type"],
        overwrite: bool = TASK_DEFAULTS["normal_generate"]["overwrite"],
        merge: bool = TASK_DEFAULTS["normal_generate"]["merge"],
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "normal_generate",
            {
                "scenario_set_id": scenario_set_id,
                "seed": seed,
                "delay_count": delay_count,
                "speed_count": speed_count,
                "interruption_count": interruption_count,
                "combo_per_type": combo_per_type,
                "overwrite": overwrite,
                "merge": merge,
            },
            label="normal_generate",
        )

    def create_dataset(self, project_id: str, dataset_id: str, *, exist_ok: bool = False) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "dataset_create",
            {"dataset_id": dataset_id, "exist_ok": exist_ok},
            label="dataset_create",
        )

    def delete_dataset(self, project_id: str, dataset_id: str) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        dataset_id = require_id(dataset_id, "dataset_id")
        ensure_no_active_reference(
            self.tasks.list_active_tasks(group=project_id),
            field="dataset_id",
            value=dataset_id,
            action_labels=("dataset_create", "build", "solve", "export_timetable"),
        )
        return delete_dataset(self.repository.layout(project_id), dataset_id)

    def build(
        self,
        project_id: str,
        scenario_set_id: str,
        dataset_id: str,
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
                "dataset_id": dataset_id,
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
        dataset_id: str,
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
                "dataset_id": dataset_id,
                "case_id": case_id,
                "limit": limit,
                "time_limit": time_limit,
                "mip_gap": mip_gap,
                "threads": threads,
                "skip_solved": skip_solved,
            },
            label="solve",
        )

    def export_timetable(
        self,
        project_id: str,
        dataset_id: str,
        *,
        case_id: str = TASK_DEFAULTS["export_timetable"]["case_id"],
        limit: int = TASK_DEFAULTS["export_timetable"]["limit"],
    ) -> Dict[str, object]:
        return self.submit_task(
            project_id,
            "export_timetable",
            {
                "dataset_id": dataset_id,
                "case_id": case_id,
                "limit": limit,
            },
            label="export_timetable",
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
        batch_size: int = TASK_DEFAULTS["train"]["batch_size"],
        lr: float = TASK_DEFAULTS["train"]["lr"],
        seed: int = TASK_DEFAULTS["train"]["seed"],
        device: str = TASK_DEFAULTS["train"]["device"],
        log_every: int = TASK_DEFAULTS["train"]["log_every"],
        count_weight: float = TASK_DEFAULTS["train"]["count_weight"],
        anchor_weight: float = TASK_DEFAULTS["train"]["anchor_weight"],
        param_weight: float = TASK_DEFAULTS["train"]["param_weight"],
        kl_weight: float = TASK_DEFAULTS["train"]["kl_weight"],
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
                "batch_size": batch_size,
                "lr": lr,
                "seed": seed,
                "device": device,
                "log_every": log_every,
                "count_weight": count_weight,
                "anchor_weight": anchor_weight,
                "param_weight": param_weight,
                "kl_weight": kl_weight,
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
    ) -> Dict[str, object]:
        project_id = normalize_project_id(project_id)
        params = normalize_task_params(action, params)
        ensure_no_active_conflict(
            self.tasks.list_active_tasks(group=project_id),
            action=action,
            params=params,
        )
        task_input = self._write_task_input(project_id, action, params)
        return self.tasks.submit_runner(project_id, task_input, label=label)

    def _write_task_input(self, project_id: str, action: str, params: Dict[str, Any]) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        root = self.tasks.repo_root / "var" / "tasks" / project_id / f"{stamp}_{sanitize_id(action)}"
        root.mkdir(parents=True, exist_ok=False)
        path = root / "input.json"
        payload = {
            "action": action,
            "project_id": project_id,
            "params": params,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

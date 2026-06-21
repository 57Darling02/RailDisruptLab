from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from backend.analysis.model import (
    list_model_checkpoints,
    read_model_detail as read_model_detail_payload,
    read_training_summary as read_training_summary_payload,
)
from core.project_layout import PROJECTS_ROOT, ProjectLayout, require_id, sanitize_id, to_posix
from backend.scenario_cases import (
    list_scenario_cases,
    read_scenario_case,
)
from backend.state import (
    get_project_state,
    list_adjustment_plans,
    list_project_models,
    list_project_scenario_sets,
    list_projects,
)


class ProjectRepository:
    def __init__(self, projects_root: Path = PROJECTS_ROOT):
        self.projects_root = projects_root

    def layout(self, project_id: str) -> ProjectLayout:
        project_id = require_id(project_id, "project_id")
        return ProjectLayout(name=project_id, root=self.projects_root / project_id)

    def list_projects(self) -> List[Dict[str, object]]:
        return list_projects(self.projects_root)

    def get_project_state(self, project_id: str) -> Dict[str, object]:
        return get_project_state(project_id, self.projects_root)

    def list_scenario_sets(self, project_id: str) -> List[Dict[str, object]]:
        return list_project_scenario_sets(self.layout(project_id))

    def list_adjustment_plans(self, project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
        return list_adjustment_plans(self.layout(project_id), scenario_set_id)

    def list_models(self, project_id: str) -> List[Dict[str, object]]:
        return list_project_models(self.layout(project_id))

    def list_scenarios(self, project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
        return list_scenario_cases(self.layout(project_id), scenario_set_id)

    def read_scenario(self, project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
        return read_scenario_case(self.layout(project_id), scenario_set_id, scenario_id)

    def read_training_summary(self, project_id: str, model_id: str) -> Dict[str, object]:
        return read_training_summary_payload(self.layout(project_id), model_id)

    def read_model_detail(self, project_id: str, model_id: str) -> Dict[str, object]:
        return read_model_detail_payload(self.layout(project_id), model_id)

    def list_model_files(self, project_id: str, model_id: str) -> List[Dict[str, object]]:
        return list_model_checkpoints(self.layout(project_id).model(model_id))

    def list_case_artifacts(self, project_id: str, scenario_set_id: str, plan_id: str) -> List[Dict[str, object]]:
        cases_dir = self.layout(project_id).scenario_set(scenario_set_id).adjustment_plan(plan_id).cases_dir
        if not cases_dir.is_dir():
            return []
        artifacts: List[Dict[str, object]] = []
        for path in sorted(item for item in cases_dir.glob("*/*") if item.is_file()):
            artifacts.append(
                {
                    "case_id": path.parent.name,
                    "name": path.name,
                    "path": to_posix(path),
                    "size_bytes": path.stat().st_size,
                }
            )
        return artifacts


def read_yaml(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError("YAML not found: {}".format(path))
    payload = require_yaml().safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("YAML must contain an object: {}".format(path))
    return payload


def write_yaml(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(require_yaml().safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml

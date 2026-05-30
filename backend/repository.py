from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from core.project_layout import PROJECTS_ROOT, ProjectLayout, require_id, sanitize_id, to_posix
from core.scenario_config import load_scenario_document, scenario_file_by_id, scenario_files
from backend.state import get_project_state, list_projects


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
        layout = self.layout(project_id)
        if not layout.scenario_sets_dir.is_dir():
            return []
        return [
            {
                "scenario_set_id": root.name,
                "root": to_posix(root),
                "case_count": len(scenario_files(root)),
            }
            for root in sorted(path for path in layout.scenario_sets_dir.iterdir() if path.is_dir())
        ]

    def list_scenarios(self, project_id: str, scenario_set_id: str) -> List[Dict[str, object]]:
        root = self.layout(project_id).scenario_set(scenario_set_id).root
        if not root.is_dir():
            raise FileNotFoundError("Scenario set not found: {}".format(root))
        yaml = require_yaml()
        scenarios: List[Dict[str, object]] = []
        for path in scenario_files(root):
            doc = load_scenario_document(path, yaml)
            speed_limit_count, interruption_count = speed_limit_counts(doc.scenarios.get("speed_limits", []) or [])
            scenarios.append(
                {
                    "scenario_id": sanitize_id(path.stem),
                    "name": doc.name,
                    "path": to_posix(path),
                    "size_bytes": path.stat().st_size,
                    "delay_count": len(doc.scenarios.get("delays", []) or []),
                    "speed_limit_count": speed_limit_count,
                    "interruption_count": interruption_count,
                }
            )
        return scenarios

    def read_scenario(self, project_id: str, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
        root = self.layout(project_id).scenario_set(scenario_set_id).root
        if not root.is_dir():
            raise FileNotFoundError("Scenario set not found: {}".format(root))
        path = scenario_file_by_id(root, scenario_id)
        if path is None:
            raise FileNotFoundError("Scenario not found: {}".format(scenario_id))
        return read_yaml(path)

    def save_source_file(self, project_id: str, filename: str, content: bytes) -> Path:
        layout = self.layout(project_id)
        layout.source_dir.mkdir(parents=True, exist_ok=True)
        target = layout.source_dir / Path(filename).name
        target.write_bytes(content)
        return target

    def source_file_path(self, project_id: str, filename: str) -> Path:
        path = self.layout(project_id).source_dir / Path(filename).name
        if not path.is_file():
            raise FileNotFoundError("Source file not found: {}".format(path))
        return path

    def read_training_summary(self, project_id: str, model_id: str) -> Dict[str, object]:
        return read_json(self.layout(project_id).model(model_id).root / "training_summary.json")

    def read_model_detail(self, project_id: str, model_id: str) -> Dict[str, object]:
        model_id = require_id(model_id, "model_id")
        root = self.layout(project_id).model(model_id).root
        if not root.is_dir():
            raise FileNotFoundError("Model not found: {}".format(root))
        return {
            "model_id": model_id,
            "root": to_posix(root),
            "summary": read_json_if_exists(root / "training_summary.json"),
            "config": read_json_if_exists(root / "training_config.json"),
            "schema": read_json_if_exists(root / "schema_summary.json"),
            "graph_progress": read_json_if_exists(root / "graph" / "graph_progress.json"),
            "history": read_history_summary(root / "history.json"),
            "loss_points": read_loss_points(root),
            "training_log_tail": read_text_tail(root / "training.log", tail_lines=120),
            "checkpoints": self.list_model_files(project_id, model_id),
        }

    def list_model_files(self, project_id: str, model_id: str) -> List[Dict[str, object]]:
        root = self.layout(project_id).model(model_id).root
        if not root.is_dir():
            raise FileNotFoundError("Model not found: {}".format(root))
        files: List[Dict[str, object]] = []
        for path in sorted(item for item in root.glob("*.pt") if item.is_file()):
            files.append(
                {
                    "name": path.name,
                    "relative_path": to_posix(path.relative_to(root)),
                    "path": to_posix(path),
                    "role": checkpoint_role(path.name),
                    "size_bytes": path.stat().st_size,
                }
            )
        return files

    def list_case_artifacts(self, project_id: str, dataset_id: str) -> List[Dict[str, object]]:
        cases_dir = self.layout(project_id).dataset(dataset_id).cases_dir
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


def read_json(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError("JSON not found: {}".format(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON must contain an object: {}".format(path))
    return payload


def read_json_if_exists(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_history_summary(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {"count": 0, "latest": {}, "best": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"count": 0, "latest": {}, "best": {}}
    if not isinstance(payload, list):
        return {"count": 0, "latest": {}, "best": {}}
    records = [item for item in payload if isinstance(item, dict)]
    best = min(
        (item for item in records if isinstance(item.get("loss"), (int, float))),
        key=lambda item: float(item["loss"]),
        default={},
    )
    return {
        "count": len(records),
        "latest": records[-1] if records else {},
        "best": best,
    }


def read_text_tail(path: Path, *, tail_lines: int) -> str:
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-tail_lines:])


def read_loss_points(root: Path) -> List[Dict[str, object]]:
    return read_loss_history(root / "loss_history.jsonl")


def read_loss_history(path: Path) -> List[Dict[str, object]]:
    if not path.is_file():
        return []
    points: List[Dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        point = normalize_loss_point(payload)
        if point:
            points.append(point)
    return points


def normalize_loss_point(payload: Dict[str, Any]) -> Dict[str, object]:
    try:
        point: Dict[str, object] = {
            "step": int(payload["step"]),
            "epoch": int(payload["epoch"]),
            "epoch_step": int(payload["epoch_step"]),
            "total_steps": int(payload["total_steps"]),
            "loss": float(payload["loss"]),
        }
    except (KeyError, TypeError, ValueError):
        return {}
    for key in ("count_loss", "anchor_loss", "param_loss", "kl", "elapsed"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            point[key] = float(value)
    return point


def checkpoint_role(filename: str) -> str:
    if filename == "best_model.pt":
        return "best"
    if filename == "last_model.pt":
        return "last"
    return "checkpoint"


def speed_limit_counts(items: object) -> tuple[int, int]:
    speed_limit_count = 0
    interruption_count = 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            limit_speed = float(item.get("limit_speed", 0) or 0)
        except (TypeError, ValueError):
            limit_speed = 0.0
        if limit_speed > 20:
            speed_limit_count += 1
        else:
            interruption_count += 1
    return speed_limit_count, interruption_count


def require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml

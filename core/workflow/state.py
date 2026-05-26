from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from core.project_layout import PROJECTS_ROOT, ProjectLayout, sanitize_id, to_posix
from core.scenario_config import scenario_files


def list_projects(projects_root: Path = PROJECTS_ROOT) -> List[Dict[str, object]]:
    if not projects_root.is_dir():
        return []
    result: List[Dict[str, object]] = []
    for root in sorted(path for path in projects_root.iterdir() if path.is_dir()):
        layout = ProjectLayout(name=sanitize_id(root.name), root=root)
        result.append(
            {
                "project_id": layout.name,
                "root": to_posix(layout.root),
                "has_context": layout.context_json.is_file(),
            }
        )
    return result


def get_project_state(project_id: str) -> Dict[str, object]:
    layout = ProjectLayout.from_name(project_id)
    return {
        "project_id": layout.name,
        "root": to_posix(layout.root),
        "exists": layout.root.is_dir(),
        "has_context": layout.context_json.is_file(),
        "source_files": _files(layout.source_dir),
        "configs": _configs(layout),
        "scenario_sets": _scenario_sets(layout),
        "datasets": _datasets(layout),
        "models": _models(layout),
    }


def _files(root: Path) -> List[Dict[str, object]]:
    if not root.is_dir():
        return []
    return [
        {
            "name": path.name,
            "path": to_posix(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != ".gitkeep"
    ]


def _configs(layout: ProjectLayout) -> Dict[str, object]:
    return {
        "prepare": _file_state(layout.prepare_config),
        "solve": _file_state(layout.solve_config),
        "analyze": _file_state(layout.analyze_config),
        "normal_generate": _config_group(layout.conf_dir / "normal_generate"),
        "train": _config_group(layout.conf_dir / "train"),
    }


def _config_group(root: Path) -> List[Dict[str, object]]:
    if not root.is_dir():
        return []
    return [_file_state(path) for path in sorted(root.glob("*.yml"))]


def _scenario_sets(layout: ProjectLayout) -> List[Dict[str, object]]:
    if not layout.scenario_sets_dir.is_dir():
        return []
    result: List[Dict[str, object]] = []
    for root in sorted(path for path in layout.scenario_sets_dir.iterdir() if path.is_dir()):
        files = list(scenario_files(root))
        result.append(
            {
                "scenario_set_id": root.name,
                "root": to_posix(root),
                "case_count": len(files),
                "files": [to_posix(path) for path in files],
            }
        )
    return result


def _datasets(layout: ProjectLayout) -> List[Dict[str, object]]:
    if not layout.datasets_dir.is_dir():
        return []
    result: List[Dict[str, object]] = []
    for root in sorted(path for path in layout.datasets_dir.iterdir() if path.is_dir()):
        dataset_json = root / "dataset.json"
        metadata = _read_json_if_exists(dataset_json)
        result.append(
            {
                "dataset_id": root.name,
                "root": to_posix(root),
                "metadata": metadata,
                "has_dataset_json": dataset_json.is_file(),
                "has_build_csv": (root / "build.csv").is_file(),
                "has_solve_csv": (root / "solve.csv").is_file(),
                "has_analyze_csv": (root / "analyze.csv").is_file(),
                "case_count": _case_count(root / "cases"),
            }
        )
    return result


def _models(layout: ProjectLayout) -> List[Dict[str, object]]:
    if not layout.model_dir.is_dir():
        return []
    result: List[Dict[str, object]] = []
    for root in sorted(path for path in layout.model_dir.iterdir() if path.is_dir()):
        graph_dir = root / "graph"
        sample_dir = graph_dir / "samples"
        result.append(
            {
                "model_id": root.name,
                "root": to_posix(root),
                "has_context_graph": (graph_dir / "context.json").is_file(),
                "sample_count": len(list(sample_dir.glob("*.json"))) if sample_dir.is_dir() else 0,
                "has_dataset_profile": (graph_dir / "dataset_profile.json").is_file(),
                "has_best_model": (root / "best_model.pt").is_file(),
                "has_last_model": (root / "last_model.pt").is_file(),
                "has_training_summary": (root / "training_summary.json").is_file(),
            }
        )
    return result


def _file_state(path: Path) -> Dict[str, object]:
    return {
        "name": path.name,
        "path": to_posix(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
    }


def _read_json_if_exists(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _case_count(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for path in root.iterdir() if path.is_dir())

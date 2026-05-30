from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from core.project_layout import PROJECTS_ROOT, ProjectLayout, require_id, sanitize_id, to_posix
from core.scenario_config import scenario_files


def list_projects(projects_root: Path = PROJECTS_ROOT) -> List[Dict[str, object]]:
    if not projects_root.is_dir():
        return []
    result: List[Dict[str, object]] = []
    for root in sorted(path for path in projects_root.iterdir() if path.is_dir()):
        try:
            project_id = require_id(root.name, "project_id")
        except ValueError:
            continue
        layout = ProjectLayout(name=project_id, root=root)
        result.append(
            {
                "project_id": layout.name,
                "root": to_posix(layout.root),
                "has_context": layout.context_json.is_file(),
            }
        )
    return result


def get_project_state(project_id: str, projects_root: Path = PROJECTS_ROOT) -> Dict[str, object]:
    project_id = require_id(project_id, "project_id")
    layout = ProjectLayout(name=project_id, root=projects_root / project_id)
    return {
        "project_id": layout.name,
        "root": to_posix(layout.root),
        "exists": layout.root.is_dir(),
        "has_context": layout.context_json.is_file(),
        "source_files": _files(layout.source_dir),
        "scenario_sets": list_project_scenario_sets(layout),
        "datasets": list_project_datasets(layout),
        "models": list_project_models(layout),
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
        if path.is_file()
    ]


def list_project_scenario_sets(layout: ProjectLayout) -> List[Dict[str, object]]:
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


def list_project_datasets(layout: ProjectLayout) -> List[Dict[str, object]]:
    if not layout.datasets_dir.is_dir():
        return []
    result: List[Dict[str, object]] = []
    for root in sorted(path for path in layout.datasets_dir.iterdir() if path.is_dir()):
        case_stats = _case_stats(root / "cases")
        result.append(
            {
                "dataset_id": root.name,
                "root": to_posix(root),
                "case_count": case_stats["case_count"],
                "built_count": case_stats["built_count"],
                "solved_count": case_stats["solved_count"],
                "timetable_count": case_stats["timetable_count"],
                "is_fully_built": case_stats["case_count"] > 0
                and case_stats["built_count"] == case_stats["case_count"],
                "is_fully_solved": case_stats["case_count"] > 0
                and case_stats["solved_count"] == case_stats["case_count"],
                "is_timetable_ready": case_stats["case_count"] > 0
                and case_stats["timetable_count"] == case_stats["case_count"],
            }
        )
    return result


def list_project_models(layout: ProjectLayout) -> List[Dict[str, object]]:
    if not layout.model_dir.is_dir():
        return []
    result: List[Dict[str, object]] = []
    for root in sorted(path for path in layout.model_dir.iterdir() if path.is_dir()):
        if root.name.startswith("."):
            continue
        graph_dir = root / "graph"
        sample_dir = graph_dir / "samples"
        result.append(
            {
                "model_id": root.name,
                "root": to_posix(root),
                "is_ready": _is_ready_model(root),
                "has_context_graph": (graph_dir / "math_context.json").is_file(),
                "sample_count": len(list(sample_dir.glob("*.json"))) if sample_dir.is_dir() else 0,
                "has_dataset_profile": (graph_dir / "dataset_profile.json").is_file(),
                "has_best_model": (root / "best_model.pt").is_file(),
                "has_last_model": (root / "last_model.pt").is_file(),
                "has_training_summary": (root / "training_summary.json").is_file(),
            }
        )
    return result


def _is_ready_model(root: Path) -> bool:
    return (
        (root / "training_summary.json").is_file()
        and (root / "training_config.json").is_file()
        and (root / "schema_summary.json").is_file()
        and ((root / "best_model.pt").is_file() or (root / "last_model.pt").is_file())
    )


def _case_stats(root: Path) -> Dict[str, int]:
    if not root.is_dir():
        return {"case_count": 0, "built_count": 0, "solved_count": 0, "timetable_count": 0}
    case_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    built_count = 0
    solved_count = 0
    timetable_count = 0
    for case_dir in case_dirs:
        case_id = case_dir.name
        if (case_dir / f"{case_id}.lp").is_file() and (case_dir / "build.json").is_file():
            built_count += 1
        if (case_dir / f"{case_id}.sol").is_file() and (case_dir / f"{case_id}.sol.csv").is_file():
            solved_count += 1
        if (case_dir / "adjusted_timetable.json").is_file():
            timetable_count += 1
    return {
        "case_count": len(case_dirs),
        "built_count": built_count,
        "solved_count": solved_count,
        "timetable_count": timetable_count,
    }

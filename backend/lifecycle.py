from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Iterable, Sequence

from core.project_layout import ProjectLayout, sanitize_id, to_posix
from backend.task_resources import RUNNING_TASK_STATUSES, task_references_value


def delete_scenario_set(layout: ProjectLayout, scenario_set_id: str) -> Dict[str, object]:
    scenario_set_id = sanitize_id(scenario_set_id)
    root = layout.scenario_set(scenario_set_id).root
    delete_project_child_dir(root, allowed_root=layout.scenario_sets_dir)
    return {"deleted": True, "kind": "scenario_set", "scenario_set_id": scenario_set_id, "path": to_posix(root)}


def delete_dataset(layout: ProjectLayout, dataset_id: str) -> Dict[str, object]:
    dataset_id = sanitize_id(dataset_id)
    root = layout.dataset(dataset_id).root
    delete_project_child_dir(root, allowed_root=layout.datasets_dir)
    return {"deleted": True, "kind": "dataset", "dataset_id": dataset_id, "path": to_posix(root)}


def delete_model(layout: ProjectLayout, model_id: str) -> Dict[str, object]:
    model_id = sanitize_id(model_id)
    root = layout.model(model_id).root
    delete_project_child_dir(root, allowed_root=layout.model_dir)
    return {"deleted": True, "kind": "model", "model_id": model_id, "path": to_posix(root)}


def delete_project_child_dir(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to delete path outside {root}: {path}")
    if path.is_symlink() or path.is_file():
        raise ValueError(f"Refusing to delete non-directory project artifact: {path}")
    if not path.is_dir():
        raise FileNotFoundError(f"Project artifact not found: {path}")
    shutil.rmtree(path)


def ensure_no_active_reference(
    tasks: Iterable[Dict[str, object]],
    *,
    field: str,
    value: str,
    action_labels: Sequence[str],
) -> None:
    target = sanitize_id(value)
    labels = set(action_labels)
    blockers = [
        task
        for task in tasks
        if str(task.get("status", "")) in RUNNING_TASK_STATUSES
        and str(task.get("label", "")) in labels
        and task_references_value(task, field=field, value=target)
    ]
    if blockers:
        ids = ", ".join(f"#{task.get('id')}" for task in blockers[:5])
        raise ValueError(f"仍有任务正在使用 {target}：{ids}。请先中断或等待任务结束。")

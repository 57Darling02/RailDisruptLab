from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from core.project_layout import sanitize_id


RUNNING_TASK_STATUSES = {"Queued", "Running", "Paused", "Stashed", "Locked"}


@dataclass(frozen=True)
class TaskResources:
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()


def ensure_no_active_conflict(
    tasks: Iterable[Dict[str, object]],
    *,
    action: str,
    params: Mapping[str, Any],
) -> None:
    resources = task_resources(action, params)
    if not resources.reads and not resources.writes:
        return

    blockers = []
    for task in tasks:
        if str(task.get("status", "")) not in RUNNING_TASK_STATUSES:
            continue
        existing = resources_for_task(task)
        if resources_conflict(resources, existing):
            blockers.append((task, resource_intersection(resources, existing)))

    if blockers:
        details = ", ".join(
            f"#{task.get('id')}({', '.join(sorted(resources))})"
            for task, resources in blockers[:5]
        )
        raise ValueError(f"任务资源冲突：{details}。请等待或中断相关任务。")


def resources_conflict(left: TaskResources, right: TaskResources) -> bool:
    return bool(
        left.writes & right.writes
        or left.writes & right.reads
        or left.reads & right.writes
    )


def resource_intersection(left: TaskResources, right: TaskResources) -> set[str]:
    return set(left.writes & right.writes) | set(left.writes & right.reads) | set(left.reads & right.writes)


def resources_for_task(task: Dict[str, object]) -> TaskResources:
    payload = task_input_payload(task)
    action = str(payload.get("action") or task.get("label") or "")
    raw_params = payload.get("params", {})
    params = raw_params if isinstance(raw_params, Mapping) else {}
    return task_resources(action, params)


def task_resources(action: str, params: Mapping[str, Any]) -> TaskResources:
    reads: set[str] = set()
    writes: set[str] = set()

    if action:
        reads.add("project")

    if action == "newproject":
        reads.clear()
        writes.add("project")
    elif action == "deleteproject":
        writes.add("project")
    elif action == "prepare":
        writes.add("context")
    elif action == "scenario_set_create":
        writes.add(resource("scenario_set", params.get("scenario_set_id")))
    elif action in {"scenario_add", "scenario_delete", "normal_generate"}:
        reads.add("context")
        writes.add(resource("scenario_set", params.get("scenario_set_id")))
    elif action == "dataset_create":
        writes.add(resource("dataset", params.get("dataset_id")))
    elif action == "build":
        reads.update(
            {
                "context",
                resource("scenario_set", params.get("scenario_set_id")),
            }
        )
        writes.add(resource("dataset", params.get("dataset_id")))
    elif action == "solve":
        writes.add(dataset_case_or_dataset(params))
    elif action == "export_timetable":
        reads.add("context")
        writes.add(dataset_case_or_dataset(params))
    elif action == "train":
        reads.update(
            {
                "context",
                resource("scenario_set", params.get("scenario_set_id")),
            }
        )
        writes.add(resource("model", params.get("model_id")))
    elif action == "generation":
        reads.update(
            {
                "context",
                resource("model", params.get("model_id")),
            }
        )
        writes.add(resource("scenario_set", params.get("scenario_set_id")))

    return TaskResources(
        reads=frozenset(item for item in reads if item),
        writes=frozenset(item for item in writes if item),
    )


def resource(kind: str, value: object) -> str:
    text = str(value or "").strip()
    return f"{kind}:{sanitize_id(text)}" if text else ""


def dataset_case_or_dataset(params: Mapping[str, Any]) -> str:
    dataset_id = str(params.get("dataset_id") or "").strip()
    case_id = str(params.get("case_id") or "").strip()
    if not dataset_id:
        return ""
    dataset_resource = resource("dataset", dataset_id)
    return f"{dataset_resource}:case:{sanitize_id(case_id)}" if case_id else dataset_resource


def task_references_value(task: Dict[str, object], *, field: str, value: str) -> bool:
    payload = task_input_payload(task)
    params = payload.get("params") if isinstance(payload, Mapping) else None
    if isinstance(params, Mapping) and sanitize_id(str(params.get(field, ""))) == value:
        return True
    command = f"{task.get('command', '')} {task.get('original_command', '')}"
    needle = f'"{field}": "{value}"'
    return needle in command


def task_input_payload(task: Dict[str, object]) -> Mapping[str, Any]:
    for command_key in ("command", "original_command"):
        path = task_input_path(str(task.get(command_key, "") or ""))
        if path is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            return payload
    return {}


def task_input_path(command: str) -> Path | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    for part in reversed(parts):
        path = Path(part)
        if path.name == "input.json" and path.is_file():
            return path
    return None

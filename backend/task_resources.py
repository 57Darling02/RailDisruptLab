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
        resources_overlap(left.writes, right.writes)
        or resources_overlap(left.writes, right.reads)
        or resources_overlap(left.reads, right.writes)
    )


def resource_intersection(left: TaskResources, right: TaskResources) -> set[str]:
    return (
        resource_overlaps(left.writes, right.writes)
        | resource_overlaps(left.writes, right.reads)
        | resource_overlaps(left.reads, right.writes)
    )


def resources_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    return any(resource_overlaps_one(left_item, right_item) for left_item in left for right_item in right)


def resource_overlaps(left: Iterable[str], right: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for left_item in left:
        for right_item in right:
            if resource_overlaps_one(left_item, right_item):
                result.add(left_item if len(left_item) >= len(right_item) else right_item)
    return result


def resource_overlaps_one(left: str, right: str) -> bool:
    return left == right or left.startswith(f"{right}:") or right.startswith(f"{left}:")


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
    elif action == "scenario_set_create":
        writes.add(resource("scenario_set", params.get("scenario_set_id")))
    elif action == "scenario_set_delete":
        writes.add(resource("scenario_set", params.get("scenario_set_id")))
    elif action in {"scenario_add", "scenario_delete", "scenario_activate", "normal_generate"}:
        if action == "normal_generate":
            writes.add(resource("scenario_set", params.get("scenario_set_id")))
        else:
            writes.add(scenario_case_resource(params))
    elif action == "dataset_create":
        writes.add(resource("dataset", params.get("dataset_id")))
    elif action == "build":
        reads.update(
            {
                resource("scenario_set", params.get("scenario_set_id")),
            }
        )
        writes.add(resource("dataset", params.get("dataset_id")))
    elif action == "solve":
        writes.add(dataset_case_or_dataset(params))
    elif action == "export_timetable":
        writes.add(dataset_case_or_dataset(params))
    elif action == "train":
        reads.update(
            {
                resource("scenario_set", params.get("scenario_set_id")),
            }
        )
        writes.add(resource("model", params.get("model_id")))
    elif action == "generation":
        source_set_id = str(params.get("source_scenario_set_id") or "").strip()
        reads.add(resource("model", params.get("model_id")))
        if source_set_id:
            reads.add(resource("scenario_set", source_set_id))
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


def scenario_case_resource(params: Mapping[str, Any]) -> str:
    scenario_set_id = str(params.get("scenario_set_id") or "").strip()
    scenario_id = str(params.get("scenario_id") or "").strip()
    if not scenario_set_id:
        return ""
    scenario_set_resource = resource("scenario_set", scenario_set_id)
    return f"{scenario_set_resource}:scenario:{sanitize_id(scenario_id)}" if scenario_id else scenario_set_resource


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

from __future__ import annotations

from contextlib import contextmanager
import json
import shlex
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping

from core.project_layout import sanitize_id

try:  # Pueue is a local Unix service; retain an in-process fallback for other platforms.
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


RUNNING_TASK_STATUSES = {"Queued", "Running", "Paused", "Stashed", "Locked"}
_PROJECT_LOCKS: dict[Path, threading.RLock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


class TaskResourceConflict(ValueError):
    pass


@dataclass(frozen=True)
class TaskResources:
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()


@contextmanager
def project_resource_lock(repo_root: Path, project_id: str) -> Iterator[None]:
    """Serialize resource admission for one project across backend processes."""
    lock_dir = repo_root / "var" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{sanitize_id(project_id)}.lock"
    with _local_lock(lock_path):
        with lock_path.open("a", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _local_lock(path: Path) -> Iterator[None]:
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.setdefault(path.resolve(), threading.RLock())
    with lock:
        yield


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
        raise TaskResourceConflict(f"任务资源冲突：{details}。请等待或中断相关任务。")


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
    action = str(payload.get("action") or task.get("action") or task.get("label") or "")
    raw_params = payload.get("params") if payload else task.get("params", {})
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
    elif action == "adjustment_plan_create":
        writes.add(adjustment_plan_resource(params))
    elif action == "model_delete":
        writes.add(resource("model", params.get("model_id")))
    elif action == "run_graph_set_create":
        writes.add(run_graph_set_resource(params.get("run_graph_set_id")))
    elif action == "scenario_set_validate":
        writes.add(scenario_collection_resource(params))
        reads.add("run_graph")
    elif action == "scenario_set_delete":
        writes.add(resource("scenario_set", params.get("scenario_set_id")))
    elif action == "run_graph_set_delete":
        writes.add(run_graph_set_resource(params.get("run_graph_set_id")))
    elif action in {"run_graph_write", "run_graph_build"}:
        writes.add(run_graph_resource(params.get("run_graph")))
    elif action == "scenario_set_read":
        reads.add(scenario_collection_resource(params))
    elif action == "scenario_case_read":
        reads.add(scenario_case_resource(params))
    elif action == "adjustment_plan_delete":
        writes.add(adjustment_plan_resource(params))
    elif action == "adjustment_plan_read":
        reads.add(adjustment_plan_resource(params))
    elif action == "adjustment_plan_case_read":
        reads.add(adjustment_plan_case_or_plan(params))
    elif action in {"scenario_add", "scenario_delete", "normal_generate"}:
        if action == "normal_generate":
            writes.add(scenario_collection_resource(params))
            reads.add(run_graph_resource(params.get("run_graph")))
        else:
            writes.add(scenario_case_resource(params))
            if action == "scenario_add":
                reads.add(run_graph_resource(params.get("run_graph")))
    elif action == "build":
        reads.update(
            {
                scenario_build_source_resource(params),
                "run_graph",
            }
        )
        writes.add(adjustment_plan_resource(params))
    elif action == "solve":
        writes.add(adjustment_plan_case_or_plan(params))
    elif action == "train":
        reads.update(
            {
                scenario_collection_resource(params),
                "run_graph",
            }
        )
        writes.add(resource("model", params.get("model_id")))
    elif action == "generation":
        source_set_id = str(params.get("source_scenario_set_id") or "").strip()
        reads.add(resource("model", params.get("model_id")))
        if source_set_id:
            reads.add(scenario_collection_key(source_set_id))
            reads.add("run_graph")
        else:
            reads.add(run_graph_resource(params.get("run_graph")))
        writes.add(scenario_collection_resource(params))

    return TaskResources(
        reads=frozenset(item for item in reads if item),
        writes=frozenset(item for item in writes if item),
    )


def resource(kind: str, value: object) -> str:
    text = str(value or "").strip()
    return f"{kind}:{sanitize_id(text)}" if text else ""


def adjustment_plan_resource(params: Mapping[str, Any]) -> str:
    scenario_set_id = str(params.get("scenario_set_id") or "").strip()
    plan_id = str(params.get("plan_id") or "").strip()
    if not scenario_set_id or not plan_id:
        return ""
    return f"{resource('scenario_set', scenario_set_id)}:adjustment_plan:{sanitize_id(plan_id)}"


def adjustment_plan_case_or_plan(params: Mapping[str, Any]) -> str:
    case_id = str(params.get("case_id") or "").strip()
    plan_resource = adjustment_plan_resource(params)
    if not plan_resource:
        return ""
    return f"{plan_resource}:case:{sanitize_id(case_id)}" if case_id else plan_resource


def scenario_collection_resource(params: Mapping[str, Any]) -> str:
    scenario_set_id = str(params.get("scenario_set_id") or "").strip()
    return scenario_collection_key(scenario_set_id)


def scenario_collection_key(scenario_set_id: str) -> str:
    return f"{resource('scenario_set', scenario_set_id)}:scenarios" if scenario_set_id else ""


def scenario_build_source_resource(params: Mapping[str, Any]) -> str:
    scenario_id = str(params.get("scenario_id") or "").strip()
    return scenario_case_resource(params) if scenario_id else scenario_collection_resource(params)


def scenario_case_resource(params: Mapping[str, Any]) -> str:
    scenario_id = str(params.get("scenario_id") or "").strip()
    collection = scenario_collection_resource(params)
    if not collection:
        return ""
    return f"{collection}:{sanitize_id(scenario_id)}" if scenario_id else collection


def run_graph_resource(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    set_id = str(value.get("set_id") or "").strip()
    graph_id = str(value.get("graph_id") or "").strip()
    if not set_id:
        return ""
    key = run_graph_set_resource(set_id)
    return f"{key}:run_graph:{sanitize_id(graph_id)}" if graph_id else key


def run_graph_set_resource(value: object) -> str:
    text = str(value or "").strip()
    return f"run_graph:{sanitize_id(text)}" if text else "run_graph"


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

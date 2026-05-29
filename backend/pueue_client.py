from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from backend.task_resources import RUNNING_TASK_STATUSES, task_input_payload
from core.project_layout import REPO_ROOT, sanitize_id, to_posix


class PueueError(RuntimeError):
    pass


DEFAULT_GROUP_PARALLEL = 4
TASK_PARALLEL_ENV = "RDL_TASK_PARALLEL"


class PueueClient:
    def __init__(
        self,
        *,
        repo_root: Path = REPO_ROOT,
        python_executable: str = sys.executable,
        config_path: Optional[Path] = None,
        pueue_bin: str = "pueue",
        pueued_bin: str = "pueued",
    ):
        self.repo_root = repo_root
        self.python_executable = python_executable
        self.config_path = config_path or repo_root / "var" / "pueue" / "pueue.yml"
        self.pueue_bin = pueue_bin
        self.pueued_bin = pueued_bin

    def health(self) -> Dict[str, object]:
        try:
            status = self.status()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "config": to_posix(self.config_path),
            "parallel": configured_parallel(),
            "groups": sorted(status.get("groups", {}).keys()),
        }

    def ensure_ready(self) -> None:
        self._ensure_binaries()
        self._ensure_config()
        if self._can_connect():
            return
        self._start_daemon()
        last_error = ""
        for _ in range(40):
            if self._can_connect():
                return
            time.sleep(0.25)
            try:
                self.status()
            except Exception as exc:
                last_error = str(exc)
        raise PueueError("Pueue daemon did not become ready. {}".format(last_error))

    def submit_module(self, group: str, module: str, args: Sequence[str], *, label: str = "") -> Dict[str, object]:
        return self.submit_python(
            group,
            [self.python_executable, "-u", "-m", module, *[str(item) for item in args]],
            label=label,
        )

    def submit_runner(self, group: str, task_input: Path, *, label: str = "") -> Dict[str, object]:
        return self.submit_module(group, "backend.runner", [to_posix(task_input)], label=label)

    def submit_python(self, group: str, command_parts: Sequence[str], *, label: str = "") -> Dict[str, object]:
        group = sanitize_id(group)
        self.ensure_ready()
        self.ensure_group(group)

        command = self._shell_command(command_parts)
        add_args = [
            "add",
            "--group",
            group,
            "--working-directory",
            to_posix(self.repo_root),
            "--print-task-id",
        ]
        if label:
            add_args.extend(["--label", label])
        add_args.extend(["--", command])
        result = self._run(add_args)
        task_id = result.stdout.strip().splitlines()[-1].strip()
        return self._submitted_task(task_id, group=group, command=command, label=label)

    def ensure_group(self, group: str, parallel: Optional[int] = None) -> None:
        group = sanitize_id(group)
        parallel = parallel if parallel is not None else configured_parallel()
        status = self.status()
        groups = status.get("groups", {})
        if not isinstance(groups, dict):
            groups = {}
        if group not in groups:
            self._run(["group", "add", group])
        self._run(["parallel", "--group", group, str(parallel)])

    def status(self, group: Optional[str] = None) -> Dict[str, object]:
        args = ["status", "--json"]
        if group:
            args.extend(["--group", sanitize_id(group)])
        result = self._run(args)
        return json.loads(result.stdout or "{}")

    def list_tasks(self, group: Optional[str] = None) -> List[Dict[str, object]]:
        payload = self.status(group=group)
        tasks = payload.get("tasks", {})
        if not isinstance(tasks, dict):
            return []
        return [self._normalize_task(task) for _, task in sorted(tasks.items(), key=lambda item: int(item[0]))]

    def list_active_tasks(self, group: Optional[str] = None) -> List[Dict[str, object]]:
        payload = self.status(group=group)
        tasks = payload.get("tasks", {})
        if not isinstance(tasks, dict):
            return []
        return [
            self._normalize_task(task)
            for _, task in sorted(tasks.items(), key=lambda item: int(item[0]))
            if self._status_name(task.get("status")) in RUNNING_TASK_STATUSES
        ]

    def get_task(self, task_id: Union[str, int]) -> Optional[Dict[str, object]]:
        task_key = str(task_id)
        tasks = self.status().get("tasks", {})
        if isinstance(tasks, dict) and task_key in tasks:
            return self._normalize_task(tasks[task_key])
        return None

    def log(self, task_id: Union[str, int], *, lines: Optional[int] = None) -> str:
        local_log = self._task_log_path(task_id)
        if local_log.is_file():
            return tail_text(local_log, lines=lines)

        args = ["log"]
        if lines is None:
            args.append("--full")
        else:
            args.extend(["--lines", str(lines)])
        args.append(str(task_id))
        result = self._run(args)
        return result.stdout

    def wait(self, task_id: Union[str, int]) -> Optional[Dict[str, object]]:
        self._run(["wait", "--quiet", str(task_id)])
        return self.get_task(task_id)

    def cancel(self, task_id: Union[str, int]) -> Dict[str, object]:
        task = self.get_task(task_id)
        if task is None:
            return {"id": int(task_id), "status": "missing"}

        status = str(task.get("status", ""))
        if status in {"Queued", "Stashed"}:
            self._run(["remove", str(task_id)])
            return {"id": int(task_id), "status": "removed"}
        if status in {"Running", "Paused"}:
            self._run(["kill", str(task_id)])
            return self._wait_for_status_change(task_id, previous_status=status) or {
                "id": int(task_id),
                "status": "killed",
            }
        return task

    def clean(self, group: Optional[str] = None, *, successful_only: bool = False) -> Dict[str, object]:
        args = ["clean"]
        if successful_only:
            args.append("--successful-only")
        if group:
            args.extend(["--group", sanitize_id(group)])
        before = len(self.list_tasks(group=group))
        self._run(args)
        after = len(self.list_tasks(group=group))
        return {"removed": max(before - after, 0), "remaining": after}

    def _task_log_path(self, task_id: Union[str, int]) -> Path:
        return self.config_path.parent / "task_logs" / f"{int(task_id)}.log"

    def _wait_for_status_change(
        self,
        task_id: Union[str, int],
        *,
        previous_status: str,
        timeout_sec: float = 2.0,
    ) -> Optional[Dict[str, object]]:
        deadline = time.time() + timeout_sec
        current = self.get_task(task_id)
        while current is not None and current.get("status") == previous_status and time.time() < deadline:
            time.sleep(0.1)
            current = self.get_task(task_id)
        return current

    def _ensure_binaries(self) -> None:
        self.pueue_bin = self._resolve_executable(self.pueue_bin)
        self.pueued_bin = self._resolve_executable(self.pueued_bin)
        missing = [name for name in (self.pueue_bin, self.pueued_bin) if shutil.which(name) is None]
        if missing:
            raise PueueError("Missing Pueue executable(s): {}".format(", ".join(missing)))

    def _resolve_executable(self, name: str) -> str:
        if shutil.which(name) is not None:
            return name
        local = Path(self.python_executable).resolve().parent / name
        if local.is_file():
            return to_posix(local)
        return name

    def _ensure_config(self) -> None:
        pueue_dir = self.config_path.parent
        pueue_dir.mkdir(parents=True, exist_ok=True)
        if self.config_path.is_file():
            return
        config = """shared:
  pueue_directory: {pueue_dir}
  runtime_directory: {pueue_dir}
  alias_file: {pueue_dir}/aliases.yml
client:
  read_local_logs: true
daemon:
  default_parallel_tasks: {default_parallel}
""".format(pueue_dir=to_posix(pueue_dir), default_parallel=DEFAULT_GROUP_PARALLEL)
        self.config_path.write_text(config, encoding="utf-8")

    def _start_daemon(self) -> None:
        log_path = self.config_path.parent / "pueued.log"
        log = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            [self.pueued_bin, "--config", to_posix(self.config_path)],
            cwd=self.repo_root,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )
        log.close()

    def _can_connect(self) -> bool:
        try:
            self.status()
        except Exception:
            return False
        return True

    def _run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self._ensure_config()
        command = [self.pueue_bin, "--config", to_posix(self.config_path), *list(args)]
        result = subprocess.run(
            command,
            cwd=self.repo_root,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "Pueue command failed"
            raise PueueError(message)
        return result

    @staticmethod
    def _shell_command(parts: Sequence[str]) -> str:
        return " ".join(shlex.quote(str(part)) for part in parts)

    @staticmethod
    def _normalize_task(task: Dict[str, object]) -> Dict[str, object]:
        status = task.get("status")
        status_payload: object = status
        status_name = PueueClient._status_name(status)
        if isinstance(status, dict) and status_name:
            status_payload = status.get(status_name)

        payload = task_input_payload(task)
        action = str(payload.get("action") or task.get("label") or "")
        raw_params = payload.get("params", {})
        params = raw_params if isinstance(raw_params, dict) else {}

        return {
            "id": task.get("id"),
            "group": task.get("group"),
            "label": task.get("label"),
            "display_name": task_display_name(action, params, fallback=str(task.get("label") or "")),
            "command": task.get("command"),
            "original_command": task.get("original_command"),
            "path": task.get("path"),
            "status": status_name or str(status),
            "status_detail": status_payload,
            "created_at": task.get("created_at"),
            "started_at": task_time(task, status_payload, "started_at", "start_at", "start"),
            "finished_at": task_time(task, status_payload, "finished_at", "end_at", "end"),
            "dependencies": task.get("dependencies", []),
            "priority": task.get("priority", 0),
        }

    @staticmethod
    def _submitted_task(task_id: str, *, group: str, command: str, label: str) -> Dict[str, object]:
        payload = task_input_payload({"command": command})
        action = str(payload.get("action") or label or "")
        raw_params = payload.get("params", {})
        params = raw_params if isinstance(raw_params, dict) else {}
        created_at = payload.get("created_at")
        return {
            "id": int(task_id),
            "group": group,
            "label": label,
            "display_name": task_display_name(action, params, fallback=label),
            "command": command,
            "original_command": command,
            "path": None,
            "status": "Queued",
            "status_detail": "Queued",
            "created_at": str(created_at) if created_at else None,
            "started_at": None,
            "finished_at": None,
            "dependencies": [],
            "priority": 0,
        }

    @staticmethod
    def _status_name(status: object) -> str:
        if isinstance(status, str):
            return status
        if isinstance(status, dict) and status:
            return str(next(iter(status.keys())))
        return str(status)


def task_time(task: Dict[str, object], status_payload: object, *keys: str) -> Optional[str]:
    for key in keys:
        value = task.get(key)
        if value:
            return str(value)
    if isinstance(status_payload, dict):
        for key in keys:
            value = status_payload.get(key)
            if value:
                return str(value)
    return None


def task_display_name(action: str, params: Dict[str, object], *, fallback: str) -> str:
    if action == "newproject":
        return "创建项目"
    if action == "deleteproject":
        return "删除项目"
    if action == "source_delete":
        return titled(params, "filename", "删除源文件")
    if action == "prepare":
        return "激活原计划运行图"
    if action == "scenario_set_create":
        return titled(params, "scenario_set_id", "创建扰动场景集")
    if action == "normal_generate":
        return titled(params, "scenario_set_id", "批量生成场景")
    if action == "scenario_add":
        return titled(params, ("scenario_set_id", "scenario_id"), "新增场景")
    if action == "scenario_delete":
        return titled(params, ("scenario_set_id", "scenario_id"), "删除场景")
    if action == "dataset_create":
        return titled(params, "dataset_id", "创建 MILP 实例集")
    if action == "build":
        return titled(params, ("dataset_id", "scenario_id"), "构建 MILP")
    if action == "solve":
        return titled(params, ("dataset_id", "case_id"), "求解")
    if action == "export_timetable":
        return titled(params, ("dataset_id", "case_id"), "导出时刻表")
    if action == "train":
        return titled(params, "model_id", "训练模型")
    if action == "generation":
        return titled(params, ("scenario_set_id", "model_id"), "生成场景")
    return fallback


def titled(params: Dict[str, object], keys: Union[str, Sequence[str]], action_label: str) -> str:
    location = task_location(params, keys)
    return f"{action_label}-{location}" if location else action_label


def task_location(params: Dict[str, object], keys: Union[str, Sequence[str]]) -> str:
    if isinstance(keys, str):
        keys = (keys,)
    parts = [str(params.get(key, "") or "").strip() for key in keys]
    return "/".join(part for part in parts if part)


def tail_text(path: Path, *, lines: Optional[int] = None) -> str:
    if lines is None or lines <= 0:
        return path.read_text(encoding="utf-8", errors="replace")

    chunks: List[bytes] = []
    newline_count = 0
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        while position > 0 and newline_count <= lines:
            read_size = min(8192, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")

    text = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def configured_parallel() -> int:
    value = os.environ.get(TASK_PARALLEL_ENV, "").strip()
    if not value:
        return DEFAULT_GROUP_PARALLEL
    try:
        parallel = int(value)
    except ValueError:
        return DEFAULT_GROUP_PARALLEL
    return max(1, parallel)

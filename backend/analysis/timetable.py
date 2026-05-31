from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from backend.analysis.disturbances import read_scenario_disturbances
from core.base_context import load_base_context
from core.project_layout import DatasetLayout, ProjectLayout, REPO_ROOT, require_id, sanitize_id, to_posix


def export_dataset_timetables(
    layout: ProjectLayout,
    dataset_id: str,
    *,
    case_id: str = "",
    limit: int = 0,
) -> None:
    dataset = layout.dataset(dataset_id)
    case_dirs = [dataset_case_dir(dataset, case_id)] if case_id else limit_items(dataset_case_dirs(dataset), limit)
    records = [
        export_case_timetable(case_dir, index)
        for index, case_dir in enumerate(case_dirs, start=1)
    ]

    fail_if_records_failed(records, "export-timetable")
    ok_count = sum(1 for record in records if record.get("status") == "ok")
    print(f"Export timetable finished: {ok_count}/{len(records)} case(s)")


def export_case_timetable(case_dir: Path, index: int) -> Dict[str, object]:
    started = datetime.now()
    case_id = sanitize_id(case_dir.name)
    sol_path = case_dir / f"{case_id}.sol"
    output_path = case_dir / "adjusted_timetable.json"
    summary_path = case_dir / "core_timetable_summary.json"
    record = base_record(index, case_id)
    try:
        if not sol_path.is_file():
            raise FileNotFoundError(f"Solution not found: {sol_path}")
        run(
            [
                sys.executable,
                "core_cli.py",
                "export-timetable-case",
                "--context",
                to_posix(case_dir / "context.json"),
                "--solution",
                to_posix(sol_path),
                "--output",
                to_posix(output_path),
                "--summary-output",
                to_posix(summary_path),
            ]
        )
        summary = read_json(summary_path)
        if not isinstance(summary, dict):
            raise ValueError(f"Timetable summary must be an object: {summary_path}")
        record.update(summary)
    except Exception as exc:
        record.update({"status": "failed", "error": str(exc)})
    record["duration_sec"] = elapsed_seconds(started)
    print(f"[{index}] {record['status']} | {case_id}")
    return record


def read_case_timetable(layout: ProjectLayout, dataset_id: str, case_id: str) -> Dict[str, object]:
    dataset_id = require_id(dataset_id, "dataset_id")
    case_id = require_id(case_id, "case_id")
    dataset = layout.dataset(dataset_id)
    case_dir = dataset.cases_dir / case_id
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Dataset case not found: {case_dir}")

    adjusted = read_json(case_dir / "adjusted_timetable.json")
    context = load_base_context(case_dir / "context.json")
    return {
        "project_id": layout.name,
        "dataset_id": dataset_id,
        "case_id": case_id,
        "station_order": list(context.station_order),
        "mileage_by_station": dict(context.mileage_by_station),
        "train_routes": dict(context.translated.train_routes),
        "plan": {"rows": plan_rows(context)},
        "adjusted": adjusted,
        "disturbances": read_case_disturbances(layout, case_dir, case_id, context),
    }


def plan_rows(context: Any) -> List[Dict[str, object]]:
    return [
        {
            "train_id": row.train_id,
            "station": row.station,
            "arrival_time": row.arrival_time,
            "departure_time": row.departure_time,
            "is_canceled": False,
            "row_number": row.row_number,
        }
        for row in context.validated.timetable_rows
    ]


def read_case_disturbances(
    layout: ProjectLayout,
    case_dir: Path,
    case_id: str,
    context: Any,
) -> List[Dict[str, object]]:
    scenario_path = case_dir / "scenario.yml"
    if not scenario_path.is_file():
        return []
    return read_scenario_disturbances(scenario_path, context)


def dataset_case_dirs(dataset: DatasetLayout) -> List[Path]:
    root = dataset.cases_dir
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset cases not found: {root}")
    case_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    if not case_dirs:
        raise FileNotFoundError(f"No cases found in dataset: {root}")
    return case_dirs


def dataset_case_dir(dataset: DatasetLayout, case_id: str) -> Path:
    case_dir = dataset.cases_dir / require_id(case_id, "case_id")
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Dataset case not found: {case_dir}")
    return case_dir


def limit_items(items: List[Path], limit: int) -> List[Path]:
    return items[:limit] if limit and limit > 0 else items


def base_record(index: int, case_id: str) -> Dict[str, object]:
    return {
        "index": index,
        "case_id": case_id,
        "status": "pending",
        "error": "",
        "duration_sec": 0.0,
    }


def fail_if_records_failed(records: Iterable[Dict[str, object]], stage: str) -> None:
    failed = [record for record in records if record.get("status") == "failed"]
    if failed:
        raise RuntimeError(f"{stage} failed for {len(failed)} case(s). First failure: {record_error(failed[0])}")


def record_error(record: Dict[str, object]) -> str:
    case_id = str(record.get("case_id") or "unknown")
    error = str(record.get("error") or "").strip()
    return f"{case_id}: {error}" if error else case_id


def elapsed_seconds(started: datetime) -> float:
    return round((datetime.now() - started).total_seconds(), 3)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def run(cmd: List[str]) -> None:
    if cmd and Path(cmd[0]).name.startswith("python") and "-u" not in cmd[1:2]:
        cmd = [cmd[0], "-u", *cmd[1:]]
    print(" ".join(cmd))
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env)

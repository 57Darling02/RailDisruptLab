from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from backend.analysis.disturbances import read_scenario_disturbances
from backend.run_graphs import resolve_run_graph_context
from core.base_context import load_base_context
from core.postprocess import adjusted_timetable_rows
from core.project_layout import ProjectLayout, require_id, sanitize_id
from core.scenario_config import load_scenario_document
from core.solver import load_solution_values


def materialize_case_timetable(layout: ProjectLayout, case_dir: Path, index: int = 1) -> Dict[str, object]:
    started = datetime.now()
    case_id = sanitize_id(case_dir.name)
    sol_path = case_dir / f"{case_id}.sol"
    output_path = case_dir / "adjusted_timetable.json"
    record = base_record(index, case_id)
    try:
        if not sol_path.is_file():
            raise FileNotFoundError(f"Solution not found: {sol_path}")
        context_path = case_context_path(layout, case_dir)
        context = load_base_context(context_path)
        rows = adjusted_timetable_rows(
            context.translated,
            load_solution_values(sol_path),
        )
        write_json(
            output_path,
            {
                "case_id": case_id,
                "station_order": list(context.station_order),
                "source": timetable_source_signature(layout, case_dir),
                "rows": rows,
            },
        )
        record.update({"status": "ok", "row_count": len(rows)})
    except Exception as exc:
        record.update({"status": "failed", "error": str(exc)})
    record["duration_sec"] = elapsed_seconds(started)
    return record


def read_case_timetable(layout: ProjectLayout, scenario_set_id: str, plan_id: str, case_id: str) -> Dict[str, object]:
    scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
    plan_id = require_id(plan_id, "plan_id")
    case_id = require_id(case_id, "case_id")
    plan = layout.scenario_set(scenario_set_id).adjustment_plan(plan_id)
    case_dir = plan.cases_dir / case_id
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Adjustment plan case not found: {case_dir}")

    if not is_case_timetable_fresh(layout, case_dir):
        record = materialize_case_timetable(layout, case_dir)
        if record.get("status") != "ok":
            raise RuntimeError(record_error(record))

    adjusted = read_json(case_dir / "adjusted_timetable.json")
    context = load_base_context(case_context_path(layout, case_dir))
    return {
        "project_id": layout.name,
        "scenario_set_id": scenario_set_id,
        "plan_id": plan_id,
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


def base_record(index: int, case_id: str) -> Dict[str, object]:
    return {
        "index": index,
        "case_id": case_id,
        "status": "pending",
        "error": "",
        "duration_sec": 0.0,
    }


def record_error(record: Dict[str, object]) -> str:
    case_id = str(record.get("case_id") or "unknown")
    error = str(record.get("error") or "").strip()
    return f"{case_id}: {error}" if error else case_id


def elapsed_seconds(started: datetime) -> float:
    return round((datetime.now() - started).total_seconds(), 3)


def is_case_timetable_fresh(layout: ProjectLayout, case_dir: Path) -> bool:
    path = case_dir / "adjusted_timetable.json"
    if not path.is_file():
        return False
    try:
        payload = read_json(path)
        return payload.get("source") == timetable_source_signature(layout, case_dir)
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def timetable_source_signature(layout: ProjectLayout, case_dir: Path) -> Dict[str, Dict[str, object]]:
    case_id = sanitize_id(case_dir.name)
    return {
        "context": file_signature(case_context_path(layout, case_dir)),
        "scenario": file_signature(case_dir / "scenario.yml"),
        "solution": file_signature(case_dir / f"{case_id}.sol"),
    }


def case_context_path(layout: ProjectLayout, case_dir: Path) -> Path:
    scenario_path = case_dir / "scenario.yml"
    doc = load_scenario_document(scenario_path, require_yaml())
    return resolve_run_graph_context(layout, doc.run_graph)


def file_signature(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")
    return {
        "path": path.name,
        "size": path.stat().st_size,
        "sha256": file_digest(path),
    }


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def read_json(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml

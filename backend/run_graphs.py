from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from core.base_context import build_base_context, load_base_context, write_base_context
from core.file_ops import file_digest
from core.loader import load_mileage_table, load_timetable
from core.project_layout import ProjectLayout, RunGraphLayout, require_id, reset_dir, to_posix
from core.scenario_config import RunGraphReference, load_scenario_document, scenario_files


TIMETABLE_FILENAME = "timetable.xlsx"
MILEAGE_FILENAME = "mileage.xlsx"
DEFAULT_TIMETABLE_SHEET = "Sheet1"
DEFAULT_MILEAGE_SHEET = "Sheet1"


@dataclass(frozen=True)
class ScenarioRunGraphReference:
    scenario_set_id: str
    scenario_id: str
    run_graph: RunGraphReference
    source: str = "scenario"


@dataclass(frozen=True)
class BrokenScenarioReference:
    path: Path
    error: str


def create_run_graph_set(layout: ProjectLayout, run_graph_set_id: str, *, exist_ok: bool = False) -> Dict[str, object]:
    run_graph_set_id = require_id(run_graph_set_id, "run_graph_set_id")
    root = layout.run_graph_set(run_graph_set_id).root
    if root.exists():
        if not root.is_dir():
            raise NotADirectoryError(f"Run graph set path is not a directory: {root}")
        if not exist_ok:
            raise FileExistsError(f"Run graph set already exists: {root}")
    else:
        root.mkdir(parents=True, exist_ok=False)
    return run_graph_set_summary(layout, run_graph_set_id)


def list_run_graph_sets(layout: ProjectLayout) -> List[Dict[str, object]]:
    if not layout.run_graph_sets_dir.is_dir():
        return []
    return [
        run_graph_set_summary(layout, root.name)
        for root in sorted(path for path in layout.run_graph_sets_dir.iterdir() if path.is_dir())
    ]


def run_graph_set_summary(layout: ProjectLayout, run_graph_set_id: str) -> Dict[str, object]:
    run_graph_set_id = require_id(run_graph_set_id, "run_graph_set_id")
    root = layout.run_graph_set(run_graph_set_id).root
    return {
        "run_graph_set_id": run_graph_set_id,
        "root": to_posix(root),
        "run_graph_count": len(list_run_graphs(layout, run_graph_set_id)),
    }


def delete_run_graph_set(layout: ProjectLayout, run_graph_set_id: str) -> Dict[str, object]:
    run_graph_set_id = require_id(run_graph_set_id, "run_graph_set_id")
    root = layout.run_graph_set(run_graph_set_id).root
    if not root.is_dir():
        raise FileNotFoundError(f"Run graph set not found: {root}")
    references = run_graph_references(layout)
    if any(ref.run_graph.set_id == run_graph_set_id for ref in references):
        raise ValueError(f"Run graph set is referenced by scenario: {run_graph_set_id}")
    reset_dir(root, allowed_root=layout.run_graph_sets_dir)
    return {"deleted": True, "kind": "run_graph_set", "run_graph_set_id": run_graph_set_id, "path": to_posix(root)}


def create_run_graph(
    layout: ProjectLayout,
    run_graph_set_id: str,
    run_graph_id: str,
    *,
    timetable_content: bytes,
    mileage_content: bytes,
    timetable_sheet_name: str = DEFAULT_TIMETABLE_SHEET,
    mileage_sheet_name: str = DEFAULT_MILEAGE_SHEET,
    overwrite: bool = False,
) -> Dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rdl_run_graph_") as root:
        temp_root = Path(root)
        timetable_source = temp_root / TIMETABLE_FILENAME
        mileage_source = temp_root / MILEAGE_FILENAME
        timetable_source.write_bytes(timetable_content)
        mileage_source.write_bytes(mileage_content)
        return create_run_graph_from_files(
            layout,
            run_graph_set_id,
            run_graph_id,
            timetable_source=timetable_source,
            mileage_source=mileage_source,
            timetable_sheet_name=timetable_sheet_name,
            mileage_sheet_name=mileage_sheet_name,
            overwrite=overwrite,
        )


def create_run_graph_from_files(
    layout: ProjectLayout,
    run_graph_set_id: str,
    run_graph_id: str,
    *,
    timetable_source: Path,
    mileage_source: Path,
    timetable_sheet_name: str = DEFAULT_TIMETABLE_SHEET,
    mileage_sheet_name: str = DEFAULT_MILEAGE_SHEET,
    overwrite: bool = False,
) -> Dict[str, object]:
    run_graph_set_id = require_id(run_graph_set_id, "run_graph_set_id")
    run_graph_id = require_id(run_graph_id, "run_graph_id")
    run_graph_set = layout.run_graph_set(run_graph_set_id)
    run_graph = run_graph_set.run_graph(run_graph_id)
    if run_graph.root.exists():
        if not overwrite:
            raise FileExistsError(f"Run graph already exists: {run_graph.root}")
        ensure_run_graph_not_referenced(layout, run_graph_set_id, run_graph_id)

    run_graph_set.run_graphs_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = run_graph_set.root / ".run_graph_builds"
    staging_dir.mkdir(parents=True, exist_ok=True)
    temp_root = staging_dir / f"{run_graph.root.name}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    if temp_root.exists():
        reset_dir(temp_root, allowed_root=run_graph_set.root)
    success = False
    try:
        temp_graph = RunGraphLayout(temp_root)
        temp_graph.source_dir.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(timetable_source, temp_graph.timetable_xlsx)
        shutil.copyfile(mileage_source, temp_graph.mileage_xlsx)
        context = build_base_context(
            timetable_path=temp_graph.timetable_xlsx,
            mileage_path=temp_graph.mileage_xlsx,
            timetable_sheet_name=timetable_sheet_name,
            mileage_sheet_name=mileage_sheet_name,
            timetable_table=load_timetable(temp_graph.timetable_xlsx, timetable_sheet_name),
            mileage_table=load_mileage_table(temp_graph.mileage_xlsx, mileage_sheet_name),
        )
        write_base_context(
            context,
            temp_graph.context_json,
            metadata={
                "id": f"{run_graph_set_id}/{run_graph_id}",
                "run_graph_set_id": run_graph_set_id,
                "run_graph_id": run_graph_id,
                "timetable_filename": TIMETABLE_FILENAME,
                "mileage_filename": MILEAGE_FILENAME,
                "timetable_sheet_name": timetable_sheet_name,
                "mileage_sheet_name": mileage_sheet_name,
                "timetable_sha256": file_digest(temp_graph.timetable_xlsx),
                "mileage_sha256": file_digest(temp_graph.mileage_xlsx),
            },
        )
        metadata = build_run_graph_metadata(layout, run_graph_set_id, run_graph_id, temp_graph)
        metadata["root"] = to_posix(run_graph.root)
        metadata["context_path"] = to_posix(run_graph.context_json)
        write_json(temp_graph.metadata_json, metadata)
        if run_graph.root.exists():
            reset_dir(run_graph.root, allowed_root=run_graph_set.run_graphs_dir)
        temp_root.replace(run_graph.root)
        success = True
        return metadata
    finally:
        if not success and temp_root.exists():
            reset_dir(temp_root, allowed_root=run_graph_set.root)


def list_run_graphs(layout: ProjectLayout, run_graph_set_id: str) -> List[Dict[str, object]]:
    run_graph_set_id = require_id(run_graph_set_id, "run_graph_set_id")
    root = layout.run_graph_set(run_graph_set_id).run_graphs_dir
    if not root.is_dir():
        return []
    return [
        read_run_graph(layout, run_graph_set_id, path.name)
        for path in sorted(item for item in root.iterdir() if item.is_dir())
    ]


def read_run_graph(layout: ProjectLayout, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
    run_graph = existing_run_graph(layout, run_graph_set_id, run_graph_id)
    if run_graph.metadata_json.is_file():
        metadata = read_json(run_graph.metadata_json)
    else:
        metadata = build_run_graph_metadata(layout, run_graph_set_id, run_graph_id, run_graph)
    return metadata


def read_run_graph_timetable(layout: ProjectLayout, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
    from backend.analysis.timetable import plan_rows

    run_graph = run_graph_ref(layout, run_graph_set_id, run_graph_id)
    context = load_base_context(resolve_run_graph_context(layout, run_graph))
    return {
        "project_id": layout.name,
        "run_graph": run_graph.to_payload(),
        "station_order": list(context.station_order),
        "mileage_by_station": dict(context.mileage_by_station),
        "train_routes": dict(context.translated.train_routes),
        "plan": {"rows": plan_rows(context)},
        "disturbances": [],
    }


def delete_run_graph(layout: ProjectLayout, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
    run_graph_set_id = require_id(run_graph_set_id, "run_graph_set_id")
    run_graph_id = require_id(run_graph_id, "run_graph_id")
    run_graph = existing_run_graph(layout, run_graph_set_id, run_graph_id)
    ensure_run_graph_not_referenced(layout, run_graph_set_id, run_graph_id)
    reset_dir(run_graph.root, allowed_root=layout.run_graph_set(run_graph_set_id).run_graphs_dir)
    return {"deleted": True, "kind": "run_graph", "run_graph_set_id": run_graph_set_id, "run_graph_id": run_graph_id}


def read_run_graph_options(layout: ProjectLayout, run_graph_set_id: str, run_graph_id: str) -> Dict[str, object]:
    context = load_base_context(resolve_run_graph_context(layout, run_graph_ref(layout, run_graph_set_id, run_graph_id)))
    return {
        "project_id": layout.name,
        "run_graph_set_id": require_id(run_graph_set_id, "run_graph_set_id"),
        "run_graph_id": require_id(run_graph_id, "run_graph_id"),
        "event_anchors": [
            {
                "anchor_id": anchor.anchor_id,
                "train_id": anchor.train_id,
                "station": anchor.station,
                "event_type": anchor.event_type,
                "planned_time": anchor.planned_time,
                "planned_time_text": seconds_to_hms(anchor.planned_time),
            }
            for anchor in sorted(
                context.event_anchors.values(),
                key=lambda item: (item.train_index, item.planned_time, item.station_order, item.event_type),
            )
        ],
        "section_anchors": [
            {
                "anchor_id": anchor.anchor_id,
                "start_station": anchor.start_station,
                "end_station": anchor.end_station,
                "direction": anchor.direction,
                "section_order": anchor.section_order,
                "mileage": anchor.mileage,
                "min_runtime": anchor.min_runtime,
            }
            for anchor in sorted(
                context.section_anchors.values(),
                key=lambda item: (item.direction, item.section_order, item.start_station, item.end_station),
            )
        ],
    }


def run_graph_ref(layout: ProjectLayout, run_graph_set_id: str, run_graph_id: str) -> RunGraphReference:
    metadata = read_run_graph(layout, run_graph_set_id, run_graph_id)
    return RunGraphReference(
        set_id=str(metadata["run_graph_set_id"]),
        graph_id=str(metadata["run_graph_id"]),
        context_sha256=str(metadata["context_sha256"]),
    )


def resolve_run_graph_context(layout: ProjectLayout, run_graph: RunGraphReference) -> Path:
    graph = existing_run_graph(layout, run_graph.set_id, run_graph.graph_id)
    actual = file_digest(graph.context_json)
    if actual != run_graph.context_sha256:
        raise ValueError(
            "Run graph context sha256 mismatch: "
            f"{run_graph.set_id}/{run_graph.graph_id} expected {run_graph.context_sha256}, got {actual}"
        )
    return graph.context_json


def load_scenario_context(layout: ProjectLayout, doc: Any) -> Any:
    return load_base_context(resolve_run_graph_context(layout, doc.run_graph))


def context_stats(context: Any) -> Dict[str, object]:
    mileage_values = list(context.mileage_by_station.values())
    total_mileage = max(mileage_values) - min(mileage_values) if mileage_values else 0
    return {
        "station_count": len(context.station_order),
        "train_count": len(context.translated.train_ids),
        "total_mileage": total_mileage,
        "event_node_count": len(context.event_anchors),
        "section_node_count": len(context.section_anchors),
    }


def validate_scenario_document(layout: ProjectLayout, doc: Any) -> None:
    from core.loader import parse_scenario_config

    context = load_scenario_context(layout, doc)
    parse_scenario_config(
        {
            "delays": list(doc.scenarios.get("delays", []) or []),
            "speed_limits": list(doc.scenarios.get("speed_limits", []) or []),
        },
        context,
    )


def existing_run_graph(layout: ProjectLayout, run_graph_set_id: str, run_graph_id: str) -> RunGraphLayout:
    run_graph = layout.run_graph_set(run_graph_set_id).run_graph(run_graph_id)
    if not run_graph.root.is_dir():
        raise FileNotFoundError(f"Run graph not found: {run_graph.root}")
    if not run_graph.context_json.is_file():
        raise FileNotFoundError(f"Run graph context not found: {run_graph.context_json}")
    return run_graph


def build_run_graph_metadata(
    layout: ProjectLayout,
    run_graph_set_id: str,
    run_graph_id: str,
    run_graph: RunGraphLayout,
) -> Dict[str, object]:
    context = load_base_context(run_graph.context_json)
    mileage_values = list(context.mileage_by_station.values())
    total_mileage = max(mileage_values) - min(mileage_values) if mileage_values else 0
    return {
        "project_id": layout.name,
        "run_graph_set_id": require_id(run_graph_set_id, "run_graph_set_id"),
        "run_graph_id": require_id(run_graph_id, "run_graph_id"),
        "root": to_posix(run_graph.root),
        "context_path": to_posix(run_graph.context_json),
        "context_sha256": file_digest(run_graph.context_json),
        "timetable_sha256": file_digest(run_graph.timetable_xlsx),
        "mileage_sha256": file_digest(run_graph.mileage_xlsx),
        "station_count": len(context.station_order),
        "train_count": len(context.translated.train_ids),
        "total_mileage": total_mileage,
        "event_node_count": len(context.event_anchors),
        "section_node_count": len(context.section_anchors),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def ensure_run_graph_not_referenced(layout: ProjectLayout, run_graph_set_id: str, run_graph_id: str) -> None:
    for ref in run_graph_references(layout):
        if ref.run_graph.set_id == run_graph_set_id and ref.run_graph.graph_id == run_graph_id:
            raise ValueError(
                f"Run graph is referenced by {ref.source}: "
                f"{ref.scenario_set_id}/{ref.scenario_id}"
            )


def run_graph_references(layout: ProjectLayout) -> List[ScenarioRunGraphReference]:
    if not layout.scenario_sets_dir.is_dir():
        return []
    result = []
    broken: List[BrokenScenarioReference] = []
    yaml = require_yaml()
    for scenario_set in sorted(path for path in layout.scenario_sets_dir.iterdir() if path.is_dir()):
        for path in scenario_files(scenario_set):
            try:
                doc = load_scenario_document(path, yaml)
            except Exception as exc:
                broken.append(BrokenScenarioReference(path, str(exc)))
                continue
            result.append(ScenarioRunGraphReference(scenario_set.name, path.stem, doc.run_graph))
        plans_dir = layout.scenario_set(scenario_set.name).adjustment_plans_dir
        if not plans_dir.is_dir():
            continue
        for path in sorted(plans_dir.glob("*/cases/*/scenario.yml")):
            try:
                doc = load_scenario_document(path, yaml)
            except Exception as exc:
                broken.append(BrokenScenarioReference(path, str(exc)))
                continue
            result.append(
                ScenarioRunGraphReference(
                    scenario_set.name,
                    f"{path.parents[2].name}/{path.parent.name}",
                    doc.run_graph,
                    source="adjustment plan case",
                )
            )
    if broken:
        details = "; ".join(f"{to_posix(item.path)}: {item.error}" for item in broken[:5])
        raise ValueError(f"Cannot audit run graph references because scenario YAML is invalid: {details}")
    return result


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def read_json(path: Path) -> Dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def seconds_to_hms(seconds: int) -> str:
    total = max(0, min(24 * 3600 - 1, int(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml

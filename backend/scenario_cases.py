from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from backend.analysis.disturbances import read_scenario_disturbances
from backend.analysis.scenario_set import disturbance_counts, scenario_category, scenario_set_summary
from backend.analysis.timetable import plan_rows
from core.base_context import build_base_context, load_base_context, write_base_context
from core.loader import load_mileage_table, load_timetable, parse_scenario_config
from core.project_layout import ProjectLayout, ScenarioCaseLayout, require_id, reset_dir, sanitize_id, to_posix
from core.scenario_config import ScenarioDocument, load_scenario_document, scenario_config_to_yaml, scenario_files

TIMETABLE_FILENAME = "timetable.xlsx"
MILEAGE_FILENAME = "mileage.xlsx"
TIMETABLE_SHEET = "Sheet1"
MILEAGE_SHEET = "Sheet1"


def create_scenario_case(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    timetable_content: bytes,
    mileage_content: bytes,
    overwrite: bool = False,
) -> Dict[str, object]:
    require_project(layout)
    case = scenario_case_layout(layout, scenario_set_id, scenario_id)
    if case.root.exists():
        if not overwrite:
            raise FileExistsError(f"Scenario already exists: {case.root}")
        reset_dir(case.root)
    case.source_dir.mkdir(parents=True, exist_ok=False)
    case.timetable_xlsx.write_bytes(timetable_content)
    case.mileage_xlsx.write_bytes(mileage_content)
    write_scenario_document(case, ScenarioDocument(name=scenario_id, scenarios={"delays": [], "speed_limits": []}))
    return scenario_case_summary(layout, scenario_set_id, scenario_id)


def activate_scenario_case(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    timetable_content: bytes | None = None,
    mileage_content: bytes | None = None,
    timetable_sheet_name: str = TIMETABLE_SHEET,
    mileage_sheet_name: str = MILEAGE_SHEET,
) -> Dict[str, object]:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    if timetable_content is not None:
        case.source_dir.mkdir(parents=True, exist_ok=True)
        case.timetable_xlsx.write_bytes(timetable_content)
    if mileage_content is not None:
        case.source_dir.mkdir(parents=True, exist_ok=True)
        case.mileage_xlsx.write_bytes(mileage_content)
    write_case_context(
        case,
        scenario_id=scenario_id,
        timetable_sheet_name=timetable_sheet_name,
        mileage_sheet_name=mileage_sheet_name,
    )
    return read_scenario_case(layout, scenario_set_id, scenario_id)


def write_case_context(
    case: ScenarioCaseLayout,
    *,
    scenario_id: str,
    timetable_sheet_name: str = TIMETABLE_SHEET,
    mileage_sheet_name: str = MILEAGE_SHEET,
) -> None:
    if not case.timetable_xlsx.is_file():
        raise FileNotFoundError(f"Missing timetable source: {case.timetable_xlsx}")
    if not case.mileage_xlsx.is_file():
        raise FileNotFoundError(f"Missing mileage source: {case.mileage_xlsx}")
    context = build_base_context(
        timetable_path=case.timetable_xlsx,
        mileage_path=case.mileage_xlsx,
        timetable_sheet_name=timetable_sheet_name,
        mileage_sheet_name=mileage_sheet_name,
        timetable_table=load_timetable(case.timetable_xlsx, timetable_sheet_name),
        mileage_table=load_mileage_table(case.mileage_xlsx, mileage_sheet_name),
    )
    write_base_context(
        context,
        case.context_json,
        metadata={
            "id": sanitize_id(scenario_id),
            "timetable_filename": TIMETABLE_FILENAME,
            "mileage_filename": MILEAGE_FILENAME,
            "timetable_sheet_name": timetable_sheet_name,
            "mileage_sheet_name": mileage_sheet_name,
        },
    )


def read_scenario_case(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    return {
        **scenario_case_summary(layout, scenario_set_id, scenario_id),
        "context_stats": context_stats(case.context_json) if case.context_json.is_file() else None,
        "source_files": source_file_summaries(case),
        "scenario": read_yaml_if_exists(case.scenario_yml),
        "timetable": scenario_timetable(case) if case.context_json.is_file() else None,
    }


def read_scenario_summary(layout: ProjectLayout) -> Dict[str, object]:
    scenarios = [
        scenario_case_summary(layout, item["scenario_set_id"], item["scenario_id"])
        for item in iter_scenario_cases(layout)
    ]
    totals = {"delay": 0, "speed_limit": 0, "interruption": 0, "total": 0}
    for item in scenarios:
        counts = dict(item.get("counts", {}))
        for key in totals:
            totals[key] += int(counts.get(key, 0) or 0)
    return {
        "project_id": layout.name,
        "scenario_count": len(scenarios),
        "disturbance_counts": totals,
    }


def read_scenario_set_detail(layout: ProjectLayout, scenario_set_id: str) -> Dict[str, object]:
    scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
    root = layout.scenario_set(scenario_set_id).root
    if not root.is_dir():
        raise FileNotFoundError(f"Scenario category not found: {root}")
    scenarios = [
        scenario_case_visualization_item(layout, scenario_set_id, path)
        for path in scenario_files(root)
    ]
    all_disturbances = [
        dict(item, scenario_id=scenario["scenario_id"])
        for scenario in scenarios
        for item in scenario.get("disturbances", [])
        if isinstance(item, dict)
    ]
    context = first_context(layout, scenario_set_id)
    station_order = list(context.station_order) if context is not None else []
    plan = {"rows": plan_rows(context)} if context is not None else {"rows": []}
    return {
        "project_id": layout.name,
        "scenario_set_id": scenario_set_id,
        "scenarios": scenarios,
        "station_order": station_order,
        "summary": scenario_set_summary(scenarios, context, station_order, plan["rows"]),
        "time_distribution": time_distribution(all_disturbances),
        "space_distribution": space_distribution(all_disturbances),
    }


def scenario_case_visualization_item(layout: ProjectLayout, scenario_set_id: str, scenario_path: Path) -> Dict[str, object]:
    scenario_id = sanitize_id(scenario_path.parent.name)
    case = layout.scenario_set(scenario_set_id).scenario(scenario_id)
    disturbances = []
    if case.context_json.is_file():
        disturbances = read_scenario_disturbances(case.scenario_yml, load_base_context(case.context_json))
    else:
        doc = load_scenario_document(case.scenario_yml, require_yaml())
        speed_limits = list(doc.scenarios.get("speed_limits", []) or [])
        delays = list(doc.scenarios.get("delays", []) or [])
        disturbances = [
            {"type": "delay"}
            for _item in delays
        ] + [
            {"type": "interruption" if float(item.get("limit_speed", 0) or 0) <= 20 else "speed_limit"}
            for item in speed_limits
            if isinstance(item, Mapping)
        ]
    counts = disturbance_counts(disturbances)
    return {
        "scenario_id": scenario_id,
        "name": scenario_id,
        "path": to_posix(case.root),
        "activated": case.context_json.is_file(),
        "disturbances": disturbances,
        "counts": counts,
        "category": scenario_category(disturbances),
    }


def scenario_case_summary(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    scenario_id = require_id(scenario_id, "scenario_id")
    case = layout.scenario_set(scenario_set_id).scenario(scenario_id)
    if not case.root.is_dir():
        raise FileNotFoundError(f"Scenario not found: {case.root}")
    doc = load_scenario_document(case.scenario_yml, require_yaml()) if case.scenario_yml.is_file() else ScenarioDocument(
        name=scenario_id,
        scenarios={"delays": [], "speed_limits": []},
        path=case.scenario_yml,
    )
    speed_limit_count, interruption_count = speed_limit_counts(doc.scenarios.get("speed_limits", []) or [])
    counts = {
        "delay": len(doc.scenarios.get("delays", []) or []),
        "speed_limit": speed_limit_count,
        "interruption": interruption_count,
    }
    counts["total"] = counts["delay"] + counts["speed_limit"] + counts["interruption"]
    return {
        "scenario_set_id": require_id(scenario_set_id, "scenario_set_id"),
        "scenario_id": scenario_id,
        "name": doc.name,
        "root": to_posix(case.root),
        "activated": case.context_json.is_file(),
        "has_timetable": case.timetable_xlsx.is_file(),
        "has_mileage": case.mileage_xlsx.is_file(),
        "counts": counts,
        "delay_count": counts["delay"],
        "speed_limit_count": counts["speed_limit"],
        "interruption_count": counts["interruption"],
    }


def list_scenario_cases(layout: ProjectLayout, scenario_set_id: str) -> List[Dict[str, object]]:
    return [
        scenario_case_summary(layout, scenario_set_id, path.parent.name)
        for path in scenario_files(layout.scenario_set(scenario_set_id).root)
    ]


def delete_scenario_case(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> None:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    reset_dir(case.root)


def scenario_source_file(layout: ProjectLayout, scenario_set_id: str, scenario_id: str, filename: str) -> Path:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    clean = Path(filename).name
    if clean not in {TIMETABLE_FILENAME, MILEAGE_FILENAME}:
        raise FileNotFoundError(f"Unsupported scenario source file: {filename}")
    path = case.source_dir / clean
    if not path.is_file():
        raise FileNotFoundError(f"Scenario source file not found: {path}")
    return path


def write_scenario_document(case: ScenarioCaseLayout, doc: ScenarioDocument) -> None:
    write_yaml(case.scenario_yml, scenario_document_to_yaml(case.root.name, doc))


def write_yaml(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(require_yaml().safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def scenario_document_to_yaml(scenario_id: str, doc: ScenarioDocument) -> Dict[str, object]:
    return {
        "name": sanitize_id(scenario_id),
        "delays": list(doc.scenarios.get("delays", []) or []),
        "speed_limits": list(doc.scenarios.get("speed_limits", []) or []),
    }


def normalize_scenario_for_case(case: ScenarioCaseLayout, scenario_id: str, payload: Mapping[str, object]) -> Dict[str, object]:
    if not case.context_json.is_file():
        raise FileNotFoundError(f"Scenario is not activated: {case.context_json}")
    context = load_base_context(case.context_json)
    scenarios = parse_scenario_config(
        {
            "delays": list_payload(payload.get("delays")),
            "speed_limits": list_payload(payload.get("speed_limits")),
        },
        context,
    )
    canonical = scenario_config_to_yaml(scenario_id, scenarios)
    return {
        "delays": list(canonical.get("delays", []) or []),
        "speed_limits": list(canonical.get("speed_limits", []) or []),
    }


def update_scenario_disturbances(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    delays: Sequence[Mapping[str, object]],
    speed_limits: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    scenario_id = require_id(scenario_id, "scenario_id")
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    normalized = normalize_scenario_for_case(
        case,
        scenario_id,
        {"delays": list(delays), "speed_limits": list(speed_limits)},
    )
    write_scenario_document(case, ScenarioDocument(name=scenario_id, scenarios=normalized))
    return read_scenario_case(layout, scenario_set_id, scenario_id)


def copy_case_sources(source_case: ScenarioCaseLayout, target_case: ScenarioCaseLayout) -> None:
    target_case.source_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_case.timetable_xlsx, target_case.timetable_xlsx)
    shutil.copy2(source_case.mileage_xlsx, target_case.mileage_xlsx)


def scenario_case_layout(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> ScenarioCaseLayout:
    return layout.scenario_set(require_id(scenario_set_id, "scenario_set_id")).scenario(scenario_id)


def existing_scenario_case(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> ScenarioCaseLayout:
    case = scenario_case_layout(layout, scenario_set_id, scenario_id)
    if not case.root.is_dir():
        raise FileNotFoundError(f"Scenario not found: {case.root}")
    return case


def require_project(layout: ProjectLayout) -> None:
    if not layout.root.is_dir():
        raise FileNotFoundError(f"Project not found: {layout.root}")


def iter_scenario_cases(layout: ProjectLayout) -> List[Dict[str, str]]:
    if not layout.scenario_sets_dir.is_dir():
        return []
    result: List[Dict[str, str]] = []
    for scenario_set_dir in sorted(path for path in layout.scenario_sets_dir.iterdir() if path.is_dir()):
        for scenario_path in scenario_files(scenario_set_dir):
            result.append({"scenario_set_id": scenario_set_dir.name, "scenario_id": scenario_path.parent.name})
    return result


def context_stats(path: Path) -> Dict[str, object]:
    context = load_base_context(path)
    mileage_values = list(context.mileage_by_station.values())
    total_mileage = max(mileage_values) - min(mileage_values) if mileage_values else 0
    return {
        "station_count": len(context.station_order),
        "train_count": len(context.translated.train_ids),
        "total_mileage": total_mileage,
        "event_node_count": len(context.event_anchors),
        "section_node_count": len(context.section_anchors),
    }


def source_file_summaries(case: ScenarioCaseLayout) -> List[Dict[str, object]]:
    result = []
    for path in (case.timetable_xlsx, case.mileage_xlsx):
        result.append(
            {
                "name": path.name,
                "path": to_posix(path),
                "exists": path.is_file(),
                "size_bytes": path.stat().st_size if path.is_file() else 0,
            }
        )
    return result


def scenario_timetable(case: ScenarioCaseLayout) -> Dict[str, object]:
    context = load_base_context(case.context_json)
    disturbances = read_scenario_disturbances(case.scenario_yml, context) if case.scenario_yml.is_file() else []
    return {
        "station_order": list(context.station_order),
        "mileage_by_station": dict(context.mileage_by_station),
        "train_routes": dict(context.translated.train_routes),
        "plan": {"rows": plan_rows(context)},
        "disturbances": disturbances,
    }


def first_context(layout: ProjectLayout, scenario_set_id: str) -> Any | None:
    for path in scenario_files(layout.scenario_set(scenario_set_id).root):
        context_path = path.parent / "context.json"
        if context_path.is_file():
            return load_base_context(context_path)
    return None


def time_distribution(disturbances: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    buckets = {hour: 0 for hour in range(24)}
    for item in disturbances:
        start = int(float(item.get("start_time", 0) or 0))
        hour = max(0, min(23, start // 3600))
        buckets[hour] += 1
    return [{"label": f"{hour:02d}:00", "count": count} for hour, count in buckets.items()]


def space_distribution(disturbances: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    counts: Dict[str, int] = {}
    for item in disturbances:
        label = str(item.get("station") or "")
        if not label:
            start = str(item.get("start_station") or "")
            end = str(item.get("end_station") or "")
            label = f"{start}-{end}" if start or end else "未知"
        counts[label] = counts.get(label, 0) + 1
    return [{"label": key, "count": value} for key, value in sorted(counts.items())]


def speed_limit_counts(items: Sequence[object]) -> tuple[int, int]:
    speed_limit_count = 0
    interruption_count = 0
    for item in items:
        if not isinstance(item, Mapping):
            continue
        limit_speed = float(item.get("limit_speed", 0) or 0)
        if limit_speed <= 20:
            interruption_count += 1
        else:
            speed_limit_count += 1
    return speed_limit_count, interruption_count


def list_payload(value: object) -> List[Mapping[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Scenario delays and speed_limits must be arrays.")
    result: List[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("Scenario disturbance entries must be objects.")
        result.append(item)
    return result


def read_yaml_if_exists(path: Path) -> Dict[str, object] | None:
    if not path.is_file():
        return None
    payload = require_yaml().safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML file must be an object: {path}")
    return payload


def require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: PyYAML") from exc
    return yaml

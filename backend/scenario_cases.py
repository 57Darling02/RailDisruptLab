from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from backend.analysis.disturbances import parse_seconds_of_day, read_scenario_disturbances
from backend.analysis.scenario_set import (
    disturbance_counts,
    metric_card,
    relation_rows,
    scenario_category,
    scenario_set_summary,
)
from backend.analysis.timetable import plan_rows
from core.base_context import build_base_context, load_base_context, write_base_context
from core.file_ops import file_digest
from core.loader import load_mileage_table, load_timetable, parse_scenario_config
from core.project_layout import ProjectLayout, ScenarioCaseLayout, require_id, reset_dir, sanitize_id, to_posix
from core.scenario_config import (
    ScenarioDocument,
    load_scenario_document,
    scenario_config_to_yaml,
    scenario_files,
)

TIMETABLE_FILENAME = "timetable.xlsx"
MILEAGE_FILENAME = "mileage.xlsx"
TIMETABLE_SHEET = "Sheet1"
MILEAGE_SHEET = "Sheet1"
ACTIVE_STATUS = "active"
INACTIVE_STATUS = "inactive"
VALID_STATUS = "valid"
INVALID_STATUS = "invalid"


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
    return scenario_case_light_summary(layout, scenario_set_id, scenario_id)


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
        case.context_json.unlink(missing_ok=True)
    if mileage_content is not None:
        case.source_dir.mkdir(parents=True, exist_ok=True)
        case.mileage_xlsx.write_bytes(mileage_content)
        case.context_json.unlink(missing_ok=True)
    write_case_context(
        case,
        scenario_id=scenario_id,
        timetable_sheet_name=timetable_sheet_name,
        mileage_sheet_name=mileage_sheet_name,
    )
    return read_scenario_case(layout, scenario_set_id, scenario_id)


def update_scenario_case_sources(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    timetable_content: bytes | None = None,
    mileage_content: bytes | None = None,
) -> Dict[str, object]:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    if timetable_content is None and mileage_content is None:
        raise ValueError("At least one source file is required.")
    case.source_dir.mkdir(parents=True, exist_ok=True)
    if timetable_content is not None:
        case.timetable_xlsx.write_bytes(timetable_content)
    if mileage_content is not None:
        case.mileage_xlsx.write_bytes(mileage_content)
    case.context_json.unlink(missing_ok=True)
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
    doc = load_case_scenario_document(case, scenario_id)
    validate_scenario_document_shape(doc)
    parse_scenario_config(
        {
            "delays": list_payload(doc.scenarios.get("delays")),
            "speed_limits": list_payload(doc.scenarios.get("speed_limits")),
        },
        context,
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
            "timetable_sha256": file_digest(case.timetable_xlsx),
            "mileage_sha256": file_digest(case.mileage_xlsx),
        },
    )


def read_scenario_case(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    summary = scenario_case_summary(layout, scenario_set_id, scenario_id)
    active = summary["activation_status"] == ACTIVE_STATUS
    return {
        **summary,
        "context_stats": context_stats(case.context_json) if active else None,
        "source_files": source_file_summaries(case),
        "scenario": read_yaml_if_exists_safe(case.scenario_yml),
        "timetable": scenario_timetable(case) if active else None,
    }


def read_scenario_set_analysis(layout: ProjectLayout, scenario_set_id: str) -> Dict[str, object]:
    scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
    root = layout.scenario_set(scenario_set_id).root
    if not root.is_dir():
        raise FileNotFoundError(f"Scenario category not found: {root}")

    scenarios = []
    for path in scenario_files(root):
        item = scenario_case_visualization_item(layout, scenario_set_id, path)
        scenarios.append(item)
    return scenario_set_analysis_payload(layout, scenario_set_id, scenarios, None)


def cached_base_context(path: Path, cache: Dict[str, object]) -> object:
    stat = path.stat()
    key = f"inode:{stat.st_dev}:{stat.st_ino}"
    context = cache.get(key)
    if context is None:
        context = load_base_context(path)
        cache[key] = context
    return context


def scenario_set_analysis_payload(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenarios: List[Dict[str, object]],
    context: Any | None,
) -> Dict[str, object]:
    all_disturbances = [
        dict(item, scenario_id=scenario["scenario_id"])
        for scenario in scenarios
        for item in scenario.get("disturbances", [])
        if isinstance(item, dict)
    ]
    station_order = list(context.station_order) if context is not None else []
    plan = {"rows": plan_rows(context)} if context is not None else {"rows": []}
    return {
        "project_id": layout.name,
        "scenario_set_id": scenario_set_id,
        "scenarios": scenarios,
        "station_order": station_order,
        "mileage_by_station": dict(context.mileage_by_station) if context is not None else {},
        "train_routes": dict(context.translated.train_routes) if context is not None else {},
        "plan": plan,
        "summary": (
            scenario_set_summary(scenarios, context, station_order, plan["rows"])
            if context is not None
            else lightweight_scenario_set_summary(scenarios)
        ),
        "time_distribution": time_distribution(all_disturbances),
        "space_distribution": space_distribution(all_disturbances),
    }


def lightweight_scenario_set_summary(scenarios: List[Dict[str, object]]) -> Dict[str, object]:
    all_disturbances = [
        dict(item, scenario_id=scenario["scenario_id"])
        for scenario in scenarios
        for item in scenario.get("disturbances", [])
        if isinstance(item, dict)
    ]
    counts = disturbance_counts(all_disturbances)
    category_counts: Dict[str, int] = {}
    for scenario in scenarios:
        category = str(scenario.get("category", "empty") or "empty")
        category_counts[category] = category_counts.get(category, 0) + 1
    total = max(len(scenarios), 1)
    disturbance_totals = [
        int(dict(item.get("counts", {})).get("total", 0))
        for item in scenarios
    ]
    return {
        "scenario_count": len(scenarios),
        "disturbance_counts": counts,
        "category_ratios": [
            {
                "key": key,
                "label": scenario_category_label(key),
                "count": count,
                "ratio": round(count / total, 6),
            }
            for key, count in sorted(category_counts.items())
        ],
        "coverage": {"time_span_seconds": 0, "space_span_units": 0, "rows": []},
        "disturbances": all_disturbances,
        "math_graph_metrics": {
            "cards": [
                metric_card("scenario_count", "场景样本数", len(scenarios)),
                metric_card("target_nodes", "扰动节点数", counts["total"]),
            ],
            "anchor_coverage": [],
            "parameter_stats": [],
            "relation_counts": relation_rows({}),
        },
        "combination_complexity": {
            "cards": [
                metric_card("mixed_ratio", "混合场景占比", safe_ratio_value(category_counts.get("mixed", 0), len(scenarios)), value_type="percent"),
                metric_card("average_disturbances", "平均扰动数", safe_ratio_value(sum(disturbance_totals), len(disturbance_totals))),
                metric_card("max_disturbances", "最大扰动数", max(disturbance_totals, default=0)),
            ],
            "count_distribution": [
                {"label": str(key), "count": disturbance_totals.count(key)}
                for key in sorted(set(disturbance_totals))
            ],
            "type_pair_counts": [],
            "relation_counts": relation_rows({}),
        },
        "joint_structure": {
            "time_bins": [item["label"] for item in time_distribution(all_disturbances)],
            "type_time": type_time_rows(all_disturbances),
            "location_time": location_time_rows(all_disturbances),
        },
    }


def scenario_case_visualization_item(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_path: Path,
) -> Dict[str, object]:
    scenario_id = sanitize_id(scenario_path.parent.name)
    case = layout.scenario_set(scenario_set_id).scenario(scenario_id)
    check = check_scenario_yaml(case, scenario_id)
    doc = check.get("_document") if isinstance(check.get("_document"), ScenarioDocument) else None
    disturbances = scenario_document_disturbances(doc) if doc is not None else []
    counts = disturbance_counts(disturbances)
    return {
        "scenario_id": scenario_id,
        "name": doc.name if doc is not None else scenario_id,
        "path": to_posix(case.root),
        "yaml_status": check["yaml_status"],
        "yaml_reason": check["yaml_reason"],
        "disturbances": disturbances,
        "counts": counts,
        "category": scenario_category(disturbances),
    }


def scenario_document_disturbances(
    doc: ScenarioDocument,
    context: Any | None = None,
) -> List[Dict[str, object]]:
    event_anchors = getattr(context, "event_anchors", {}) if context is not None else {}
    section_anchors = getattr(context, "section_anchors", {}) if context is not None else {}
    disturbances: List[Dict[str, object]] = []

    for index, item in enumerate(list_payload(doc.scenarios.get("delays")), start=1):
        anchor_id = str(item.get("event_anchor_id", "") or "")
        anchor = event_anchors.get(anchor_id)
        disturbances.append(
            {
                "id": f"delay_{index}",
                "type": "delay",
                "event_anchor_id": anchor_id,
                "train_id": str(item.get("train_id", "") or getattr(anchor, "train_id", "") or ""),
                "station": str(item.get("station", "") or getattr(anchor, "station", "") or ""),
                "event_type": str(item.get("event_type", "") or getattr(anchor, "event_type", "") or ""),
                "seconds": int(float(item.get("seconds", 0) or 0)),
                "start_time": getattr(anchor, "planned_time", None) or 0,
                "station_order": getattr(anchor, "station_order", None),
            }
        )

    for index, item in enumerate(list_payload(doc.scenarios.get("speed_limits")), start=1):
        anchor_id = str(item.get("section_anchor_id", "") or "")
        anchor = section_anchors.get(anchor_id)
        start_time = parse_seconds_of_day(item.get("start_time", 0))
        duration = int(float(item.get("duration", 0) or 0))
        limit_speed = float(item.get("limit_speed", 0) or 0)
        disturbances.append(
            {
                "id": f"speed_{index}",
                "type": "interruption" if limit_speed <= 20 else "speed_limit",
                "section_anchor_id": anchor_id,
                "start_station": str(item.get("start_station", "") or getattr(anchor, "start_station", "") or ""),
                "end_station": str(item.get("end_station", "") or getattr(anchor, "end_station", "") or ""),
                "start_time": start_time,
                "end_time": start_time + duration,
                "duration": duration,
                "limit_speed": limit_speed,
                "section_order": getattr(anchor, "section_order", None),
                "mileage": getattr(anchor, "mileage", None),
            }
        )

    return disturbances


def scenario_category_label(category: str) -> str:
    labels = {
        "empty": "空场景",
        "delay": "纯晚点",
        "speed_limit": "纯限速",
        "interruption": "纯中断",
        "mixed": "混合",
    }
    return labels.get(category, category)


def disturbance_type_label(item_type: str) -> str:
    labels = {
        "delay": "晚点",
        "speed_limit": "限速",
        "interruption": "中断",
    }
    return labels.get(item_type, item_type)


def safe_ratio_value(numerator: float | int, denominator: float | int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def type_time_rows(disturbances: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    counts: Dict[tuple[str, str], int] = {}
    for item in disturbances:
        item_type = str(item.get("type", "") or "")
        if item_type not in {"delay", "speed_limit", "interruption"}:
            continue
        key = (item_type, time_bin_label(item.get("start_time")))
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "type": item_type,
            "type_label": disturbance_type_label(item_type),
            "time_bin": time_bin,
            "count": count,
        }
        for (item_type, time_bin), count in sorted(counts.items())
    ]


def location_time_rows(disturbances: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    counts: Dict[tuple[str, str, str], int] = {}
    for item in disturbances:
        item_type = str(item.get("type", "") or "")
        if item_type not in {"delay", "speed_limit", "interruption"}:
            continue
        location = disturbance_location(item)
        if not location:
            continue
        key = (item_type, location, time_bin_label(item.get("start_time")))
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "type": item_type,
            "type_label": disturbance_type_label(item_type),
            "location": location,
            "time_bin": time_bin,
            "count": count,
        }
        for (item_type, location, time_bin), count in sorted(counts.items())
    ]


def disturbance_location(item: Mapping[str, object]) -> str:
    if item.get("type") == "delay":
        return str(item.get("station", "") or "")
    start = str(item.get("start_station", "") or "")
    end = str(item.get("end_station", "") or "")
    return f"{start}-{end}" if start and end else ""


def time_bin_label(value: object) -> str:
    seconds = int(float(value or 0))
    hour = max(0, min(23, seconds // 3600))
    start = (hour // 2) * 2
    return f"{start:02d}-{start + 2:02d}时"


def scenario_case_summary(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    scenario_id = require_id(scenario_id, "scenario_id")
    case = layout.scenario_set(scenario_set_id).scenario(scenario_id)
    if not case.root.is_dir():
        raise FileNotFoundError(f"Scenario not found: {case.root}")
    check = check_scenario_activation(case, scenario_id)
    doc = check.get("_document") if isinstance(check.get("_document"), ScenarioDocument) else ScenarioDocument(
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
        "activated": check["activation_status"] == ACTIVE_STATUS,
        "activation_status": check["activation_status"],
        "activation_reason": check["activation_reason"],
        "has_context": check["has_context"],
        "has_timetable": case.timetable_xlsx.is_file(),
        "has_mileage": case.mileage_xlsx.is_file(),
        "counts": counts,
        "delay_count": counts["delay"],
        "speed_limit_count": counts["speed_limit"],
        "interruption_count": counts["interruption"],
    }


def scenario_case_light_summary(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    scenario_id = require_id(scenario_id, "scenario_id")
    case = layout.scenario_set(scenario_set_id).scenario(scenario_id)
    if not case.root.is_dir():
        raise FileNotFoundError(f"Scenario not found: {case.root}")
    check = check_scenario_yaml(case, scenario_id)
    doc = check.get("_document") if isinstance(check.get("_document"), ScenarioDocument) else ScenarioDocument(
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
        "yaml_status": check["yaml_status"],
        "yaml_reason": check["yaml_reason"],
        "has_context": case.context_json.is_file(),
        "has_timetable": case.timetable_xlsx.is_file(),
        "has_mileage": case.mileage_xlsx.is_file(),
        "counts": counts,
        "delay_count": counts["delay"],
        "speed_limit_count": counts["speed_limit"],
        "interruption_count": counts["interruption"],
    }


def list_scenario_cases(layout: ProjectLayout, scenario_set_id: str) -> List[Dict[str, object]]:
    return [
        scenario_case_light_summary(layout, scenario_set_id, path.parent.name)
        for path in scenario_files(layout.scenario_set(scenario_set_id).root)
    ]


def list_scenario_case_options(
    layout: ProjectLayout,
    scenario_set_id: str,
    *,
    query: str = "",
    limit: int = 50,
) -> List[Dict[str, object]]:
    query_text = query.strip().lower()
    result: List[Dict[str, object]] = []
    for path in scenario_files(layout.scenario_set(scenario_set_id).root):
        scenario_id = sanitize_id(path.parent.name)
        if query_text and query_text not in scenario_id.lower():
            continue
        case = layout.scenario_set(scenario_set_id).scenario(scenario_id)
        suffix = "已激活" if case.context_json.is_file() else "未激活"
        result.append({"label": f"{scenario_id} ({suffix})", "value": scenario_id})
        if len(result) >= max(1, limit):
            break
    return result


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
    activation = check_scenario_activation(case, scenario_id)
    if activation["activation_status"] != ACTIVE_STATUS:
        reason = str(activation["activation_reason"] or activation_status_label(str(activation["activation_status"])))
        raise FileNotFoundError(f"Scenario is not active: {reason}")
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
    doc = load_case_scenario_document(case, case.root.name)
    validate_scenario_document_shape(doc)
    parse_scenario_config(
        {
            "delays": list_payload(doc.scenarios.get("delays")),
            "speed_limits": list_payload(doc.scenarios.get("speed_limits")),
        },
        context,
    )
    disturbances = read_scenario_disturbances(case.scenario_yml, context) if case.scenario_yml.is_file() else []
    return {
        "station_order": list(context.station_order),
        "mileage_by_station": dict(context.mileage_by_station),
        "train_routes": dict(context.translated.train_routes),
        "plan": {"rows": plan_rows(context)},
        "disturbances": disturbances,
    }


def first_context(layout: ProjectLayout, scenario_set_id: str) -> Any | None:
    context_cache: Dict[str, object] = {}
    for path in scenario_files(layout.scenario_set(scenario_set_id).root):
        context_path = path.parent / "context.json"
        case = layout.scenario_set(scenario_set_id).scenario(path.parent.name)
        check = check_scenario_activation(case, path.parent.name, context_cache=context_cache)
        if check["activation_status"] == ACTIVE_STATUS:
            return check.get("_context") or cached_base_context(context_path, context_cache)
    return None


def check_scenario_activation(
    case: ScenarioCaseLayout,
    scenario_id: str,
    *,
    context_cache: Dict[str, object] | None = None,
) -> Dict[str, object]:
    has_context = case.context_json.is_file()
    try:
        doc = load_case_scenario_document(case, scenario_id)
        validate_scenario_document_shape(doc)
    except Exception as exc:
        return activation_check(INVALID_STATUS, str(exc), has_context=has_context)

    if not has_context:
        return activation_check(INACTIVE_STATUS, "", has_context=False, document=doc)

    try:
        metadata = read_context_metadata(case.context_json)
        validate_context_source_metadata(case, metadata)
        context = (
            cached_base_context(case.context_json, context_cache)
            if context_cache is not None
            else load_base_context(case.context_json)
        )
        parse_scenario_config(
            {
                "delays": list_payload(doc.scenarios.get("delays")),
                "speed_limits": list_payload(doc.scenarios.get("speed_limits")),
            },
            context,
        )
    except Exception as exc:
        return activation_check(INVALID_STATUS, str(exc), has_context=True, document=doc)

    return activation_check(ACTIVE_STATUS, "", has_context=True, document=doc, context=context)


def check_scenario_yaml(case: ScenarioCaseLayout, scenario_id: str) -> Dict[str, object]:
    try:
        doc = load_case_scenario_document(case, scenario_id)
        validate_scenario_document_shape(doc)
    except Exception as exc:
        return yaml_check(INVALID_STATUS, str(exc))
    return yaml_check(VALID_STATUS, "", document=doc)


def activation_check(
    status: str,
    reason: str,
    *,
    has_context: bool,
    document: ScenarioDocument | None = None,
    context: Any | None = None,
) -> Dict[str, object]:
    result: Dict[str, object] = {
        "activation_status": status,
        "activation_reason": reason,
        "has_context": has_context,
    }
    if document is not None:
        result["_document"] = document
    if context is not None:
        result["_context"] = context
    return result


def yaml_check(status: str, reason: str, *, document: ScenarioDocument | None = None) -> Dict[str, object]:
    result: Dict[str, object] = {
        "yaml_status": status,
        "yaml_reason": reason,
    }
    if document is not None:
        result["_document"] = document
    return result


def load_case_scenario_document(case: ScenarioCaseLayout, scenario_id: str) -> ScenarioDocument:
    if case.scenario_yml.is_file():
        return load_scenario_document(case.scenario_yml, require_yaml())
    return ScenarioDocument(
        name=scenario_id,
        scenarios={"delays": [], "speed_limits": []},
        path=case.scenario_yml,
    )


def validate_scenario_document_shape(doc: ScenarioDocument) -> None:
    list_payload(doc.scenarios.get("delays"))
    list_payload(doc.scenarios.get("speed_limits"))


def read_context_metadata(path: Path) -> Dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Context JSON must be an object: {path}")
    project = payload.get("project") or {}
    return project if isinstance(project, dict) else {}


def validate_context_source_metadata(case: ScenarioCaseLayout, metadata: Mapping[str, object]) -> None:
    expected = {
        "timetable_sha256": case.timetable_xlsx,
        "mileage_sha256": case.mileage_xlsx,
    }
    for key, path in expected.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing source file referenced by context: {path}")
        recorded = str(metadata.get(key, "") or "").strip()
        if not recorded:
            continue
        actual = file_digest(path)
        if recorded != actual:
            label = TIMETABLE_FILENAME if key == "timetable_sha256" else MILEAGE_FILENAME
            raise ValueError(f"{label} has changed since activation; please reactivate the scenario.")


def activation_status_label(status: str) -> str:
    labels = {
        ACTIVE_STATUS: "已激活",
        INACTIVE_STATUS: "未激活",
        INVALID_STATUS: "激活无效",
    }
    return labels.get(status, status)


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


def read_yaml_if_exists_safe(path: Path) -> Dict[str, object] | None:
    try:
        return read_yaml_if_exists(path)
    except Exception:
        return None


def require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: PyYAML") from exc
    return yaml

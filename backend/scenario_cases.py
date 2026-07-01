from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from backend.analysis.disturbances import parse_seconds_of_day, read_scenario_disturbances
from backend.analysis.scenario_set import (
    disturbance_counts,
    disturbance_time_coverage,
    metric_card,
    relation_rows,
    scenario_category,
)
from backend.analysis.timetable import plan_rows
from backend.run_graphs import (
    context_stats,
    load_scenario_context,
    run_graph_context_sha256,
    resolve_run_graph_context,
    read_run_graph,
)
from core.loader import parse_scenario_config
from core.project_layout import ProjectLayout, ScenarioCaseLayout, require_id, sanitize_id, to_posix
from core.scenario_config import (
    RunGraphReference,
    ScenarioDocument,
    ScenarioValidation,
    load_scenario_document,
    scenario_config_to_yaml,
    scenario_document_to_yaml,
    scenario_disturbances_sha256,
    scenario_files,
)

VALID_STATUS = "valid"
INVALID_STATUS = "invalid"
VALIDATION_VALID = "valid"
VALIDATION_STALE = "stale"
VALIDATION_PENDING = "pending"
VALIDATION_INVALID = "invalid"


def create_scenario_case(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    run_graph: RunGraphReference,
    delays: Sequence[Mapping[str, object]] | None = None,
    speed_limits: Sequence[Mapping[str, object]] | None = None,
    overwrite: bool = False,
) -> Dict[str, object]:
    require_project(layout)
    scenario_set = layout.scenario_set(scenario_set_id)
    scenario_set.root.mkdir(parents=True, exist_ok=True)
    case = scenario_case_layout(layout, scenario_set_id, scenario_id)
    if case.scenario_yml.exists() and not overwrite:
        raise FileExistsError(f"Scenario already exists: {case.scenario_yml}")
    doc = ScenarioDocument(
        name=require_id(scenario_id, "scenario_id"),
        run_graph=run_graph,
        scenarios={"delays": list(delays or []), "speed_limits": list(speed_limits or [])},
        path=case.scenario_yml,
    )
    normalized = validate_and_stamp_scenario(layout, doc)
    write_scenario_document(case, normalized)
    return scenario_case_light_summary(layout, scenario_set_id, scenario_id)


def read_scenario_case(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    summary = scenario_case_summary(layout, scenario_set_id, scenario_id)
    doc = load_case_scenario_document(case, scenario_id) if summary["run_graph"] else None
    run_graph_detail = None
    scenario_payload = None
    if doc is not None:
        scenario_payload = scenario_document_to_yaml(doc)
    if doc is not None:
        try:
            run_graph_detail = read_run_graph(layout, doc.run_graph.set_id, doc.run_graph.graph_id)
        except Exception:
            run_graph_detail = None
    return {
        **summary,
        "context_stats": context_stats_from_run_graph_detail(run_graph_detail),
        "run_graph_detail": run_graph_detail,
        "scenario": scenario_payload,
    }


def read_scenario_timetable(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    doc = load_case_scenario_document(case, scenario_id)
    require_scenario_validation(layout, doc)
    context = load_scenario_context(layout, doc)
    return {
        "project_id": layout.name,
        "scenario_set_id": require_id(scenario_set_id, "scenario_set_id"),
        "scenario_id": require_id(scenario_id, "scenario_id"),
        "station_order": list(context.station_order),
        "mileage_by_station": dict(context.mileage_by_station),
        "train_routes": dict(context.translated.train_routes),
        "plan": {"rows": plan_rows(context)},
        "disturbances": read_scenario_disturbances(case.scenario_yml, context),
    }


def read_scenario_set_analysis(layout: ProjectLayout, scenario_set_id: str) -> Dict[str, object]:
    scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
    root = layout.scenario_set(scenario_set_id).root
    if not root.is_dir():
        raise FileNotFoundError(f"Scenario category not found: {root}")

    sha_cache: Dict[tuple[str, str], str] = {}
    context_cache: Dict[tuple[str, str], Any] = {}
    scenarios = [
        scenario_case_visualization_item(layout, scenario_set_id, path, sha_cache=sha_cache, context_cache=context_cache)
        for path in scenario_files(root)
    ]
    all_disturbances = [
        dict(item, scenario_id=scenario["scenario_id"])
        for scenario in scenarios
        for item in scenario.get("disturbances", [])
        if isinstance(item, dict)
    ]
    return {
        "project_id": layout.name,
        "scenario_set_id": scenario_set_id,
        "scenarios": scenarios,
        "station_order": [],
        "mileage_by_station": {},
        "train_routes": {},
        "plan": {"rows": []},
        "summary": lightweight_scenario_set_summary(scenarios),
        "time_distribution": time_distribution(all_disturbances),
        "space_distribution": space_distribution(all_disturbances),
    }


def scenario_case_visualization_item(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_path: Path,
    *,
    sha_cache: Dict[tuple[str, str], str] | None = None,
    context_cache: Dict[tuple[str, str], Any] | None = None,
) -> Dict[str, object]:
    scenario_id = sanitize_id(scenario_path.stem)
    try:
        doc = load_scenario_document(scenario_path, require_yaml())
        disturbances = visualization_disturbances(layout, scenario_path, doc, context_cache)
        status = VALID_STATUS
        reason = ""
    except Exception as exc:
        doc = None
        disturbances = []
        status = INVALID_STATUS
        reason = str(exc)
    counts = disturbance_counts(disturbances)
    return {
        "scenario_id": scenario_id,
        "name": scenario_id,
        "path": to_posix(scenario_path),
        "yaml_status": status,
        "yaml_reason": reason,
        "run_graph": doc.run_graph.to_payload() if doc is not None else None,
        "validation": doc.validation.to_payload() if doc is not None else None,
        "validation_state": scenario_validation_state(layout, doc, sha_cache=sha_cache) if doc is not None else invalid_validation_state(reason),
        "disturbances": disturbances,
        "counts": counts,
        "category": scenario_category(disturbances),
    }


def visualization_disturbances(
    layout: ProjectLayout,
    scenario_path: Path,
    doc: ScenarioDocument,
    context_cache: Dict[tuple[str, str], Any] | None,
) -> List[Dict[str, object]]:
    try:
        context = cached_scenario_context(layout, doc, context_cache)
        return read_scenario_disturbances(scenario_path, context)
    except Exception:
        return yaml_disturbances(doc)


def cached_scenario_context(
    layout: ProjectLayout,
    doc: ScenarioDocument,
    context_cache: Dict[tuple[str, str], Any] | None,
) -> Any:
    key = (str(doc.run_graph.set_id), str(doc.run_graph.graph_id))
    if context_cache is None:
        return load_scenario_context(layout, doc)
    if key not in context_cache:
        context_cache[key] = load_scenario_context(layout, doc)
    return context_cache[key]


def scenario_case_summary(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    validate_context: bool = False,
    sha_cache: Dict[tuple[str, str], str] | None = None,
) -> Dict[str, object]:
    scenario_id = require_id(scenario_id, "scenario_id")
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    check = check_scenario_yaml(
        case,
        scenario_id,
        validate_context=validate_context,
        layout=layout if validate_context else None,
    )
    doc = check.get("_document") if isinstance(check.get("_document"), ScenarioDocument) else None
    validation_state = scenario_validation_state(layout, doc, sha_cache=sha_cache) if doc is not None else invalid_validation_state(check["yaml_reason"])
    scenarios = doc.scenarios if doc is not None else {"delays": [], "speed_limits": []}
    speed_limit_count, interruption_count = speed_limit_counts(scenarios.get("speed_limits", []) or [])
    counts = {
        "delay": len(scenarios.get("delays", []) or []),
        "speed_limit": speed_limit_count,
        "interruption": interruption_count,
    }
    counts["total"] = counts["delay"] + counts["speed_limit"] + counts["interruption"]
    return {
        "scenario_set_id": require_id(scenario_set_id, "scenario_set_id"),
        "scenario_id": scenario_id,
        "name": scenario_id,
        "root": to_posix(case.scenario_yml),
        "yaml_status": check["yaml_status"],
        "yaml_reason": check["yaml_reason"],
        "run_graph": doc.run_graph.to_payload() if doc is not None else None,
        "validation": doc.validation.to_payload() if doc is not None else None,
        "validation_state": validation_state,
        "counts": counts,
        "delay_count": counts["delay"],
        "speed_limit_count": counts["speed_limit"],
        "interruption_count": counts["interruption"],
    }


def scenario_case_light_summary(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> Dict[str, object]:
    return scenario_case_summary(layout, scenario_set_id, scenario_id)


def list_scenario_cases(layout: ProjectLayout, scenario_set_id: str) -> List[Dict[str, object]]:
    sha_cache: Dict[tuple[str, str], str] = {}
    return [
        scenario_case_summary(layout, scenario_set_id, path.stem, sha_cache=sha_cache)
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
        scenario_id = sanitize_id(path.stem)
        if query_text and query_text not in scenario_id.lower():
            continue
        result.append({"label": scenario_id, "value": scenario_id})
        if len(result) >= max(1, limit):
            break
    return result


def update_scenario_disturbances(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    delays: Sequence[Mapping[str, object]],
    speed_limits: Sequence[Mapping[str, object]],
    run_graph: RunGraphReference | None = None,
    overwrite: bool = False,
) -> Dict[str, object]:
    scenario_id = require_id(scenario_id, "scenario_id")
    case = scenario_case_layout(layout, scenario_set_id, scenario_id)
    if not case.scenario_yml.is_file():
        if run_graph is None:
            raise FileNotFoundError(f"Scenario not found: {case.scenario_yml}")
        return create_scenario_case(
            layout,
            scenario_set_id,
            scenario_id,
            run_graph=run_graph,
            delays=delays,
            speed_limits=speed_limits,
            overwrite=overwrite,
        )
    existing = load_case_scenario_document(case, scenario_id)
    doc = ScenarioDocument(
        name=scenario_id,
        run_graph=run_graph or existing.run_graph,
        scenarios={"delays": list(delays), "speed_limits": list(speed_limits)},
        path=case.scenario_yml,
    )
    write_scenario_document(case, clear_scenario_validation(doc))
    return read_scenario_case(layout, scenario_set_id, scenario_id)


def validate_scenario_case(
    layout: ProjectLayout,
    scenario_set_id: str,
    scenario_id: str,
    *,
    run_graph: RunGraphReference | None = None,
) -> Dict[str, object]:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    existing = load_case_scenario_document(case, scenario_id)
    doc = ScenarioDocument(
        name=existing.name,
        run_graph=run_graph or existing.run_graph,
        scenarios=existing.scenarios,
        path=case.scenario_yml,
    )
    normalized = validate_and_stamp_scenario(layout, doc)
    write_scenario_document(case, normalized)
    return read_scenario_case(layout, scenario_set_id, scenario_id)


def validate_scenario_set(layout: ProjectLayout, scenario_set_id: str) -> Dict[str, object]:
    scenario_set_id = require_id(scenario_set_id, "scenario_set_id")
    root = layout.scenario_set(scenario_set_id).root
    if not root.is_dir():
        raise FileNotFoundError(f"Scenario category not found: {root}")
    paths = scenario_files(root)
    records = []
    failed = []
    context_cache: Dict[tuple[str, str, str], object] = {}
    sha_cache: Dict[tuple[str, str], str] = {}
    for index, path in enumerate(paths, start=1):
        scenario_id = sanitize_id(path.stem)
        try:
            case = scenario_case_layout(layout, scenario_set_id, scenario_id)
            doc = load_case_scenario_document(case, scenario_id)
            normalized = validate_and_stamp_scenario(layout, doc, context_cache=context_cache, sha_cache=sha_cache)
            write_scenario_document(case, normalized)
            record = {"index": index, "scenario_id": scenario_id, "status": "ok", "error": ""}
            print(f"[{index}/{len(paths)}] ok | {scenario_id}")
        except Exception as exc:
            record = {"index": index, "scenario_id": scenario_id, "status": "failed", "error": str(exc)}
            failed.append(record)
            print(f"[{index}/{len(paths)}] failed | {scenario_id}: {exc}")
        records.append(record)
    if failed:
        first = failed[0]
        raise RuntimeError(
            f"Scenario validation failed for {len(failed)} of {len(paths)} scenario(s). "
            f"First failure: {first['scenario_id']}: {first['error']}"
        )
    print(f"Validated {len(paths)} scenario(s): {scenario_set_id}")
    return {"scenario_set_id": scenario_set_id, "total": len(paths), "failed": 0, "records": records}


def delete_scenario_case(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> None:
    case = existing_scenario_case(layout, scenario_set_id, scenario_id)
    case.scenario_yml.unlink()


def scenario_case_layout(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> ScenarioCaseLayout:
    return layout.scenario_set(require_id(scenario_set_id, "scenario_set_id")).scenario(scenario_id)


def existing_scenario_case(layout: ProjectLayout, scenario_set_id: str, scenario_id: str) -> ScenarioCaseLayout:
    case = scenario_case_layout(layout, scenario_set_id, scenario_id)
    if not case.scenario_yml.is_file():
        raise FileNotFoundError(f"Scenario not found: {case.scenario_yml}")
    return case


def load_case_scenario_document(case: ScenarioCaseLayout, scenario_id: str) -> ScenarioDocument:
    if not case.scenario_yml.is_file():
        raise FileNotFoundError(f"Scenario not found: {case.scenario_yml}")
    doc = load_scenario_document(case.scenario_yml, require_yaml())
    return ScenarioDocument(
        name=require_id(scenario_id, "scenario_id"),
        run_graph=doc.run_graph,
        scenarios=doc.scenarios,
        path=case.scenario_yml,
        validation=doc.validation,
    )


def normalize_scenario_document(
    layout: ProjectLayout,
    doc: ScenarioDocument,
    *,
    context_cache: Dict[tuple[str, str, str], object] | None = None,
    sha_cache: Dict[tuple[str, str], str] | None = None,
) -> ScenarioDocument:
    context = cached_load_scenario_context(layout, doc, context_cache)
    scenarios = parse_scenario_config(
        {
            "delays": list_payload(doc.scenarios.get("delays")),
            "speed_limits": list_payload(doc.scenarios.get("speed_limits")),
        },
        context,
    )
    canonical = scenario_config_to_yaml(scenarios, doc.run_graph)
    normalized_scenarios = {
        "delays": list(canonical.get("delays", []) or []),
        "speed_limits": list(canonical.get("speed_limits", []) or []),
    }
    validation = validation_stamp(
        layout,
        ScenarioDocument(name=doc.name, run_graph=doc.run_graph, scenarios=normalized_scenarios, path=doc.path),
        sha_cache=sha_cache,
    )
    return ScenarioDocument(
        name=doc.name,
        run_graph=doc.run_graph,
        scenarios=normalized_scenarios,
        path=doc.path,
        validation=validation,
    )


def validate_empty_scenario(
    layout: ProjectLayout,
    doc: ScenarioDocument,
    *,
    sha_cache: Dict[tuple[str, str], str] | None = None,
) -> ScenarioDocument:
    resolve_run_graph_context(layout, doc.run_graph)
    return ScenarioDocument(
        name=doc.name,
        run_graph=doc.run_graph,
        scenarios=doc.scenarios,
        path=doc.path,
        validation=validation_stamp(layout, doc, sha_cache=sha_cache),
    )


def validate_and_stamp_scenario(
    layout: ProjectLayout,
    doc: ScenarioDocument,
    *,
    context_cache: Dict[tuple[str, str, str], object] | None = None,
    sha_cache: Dict[tuple[str, str], str] | None = None,
) -> ScenarioDocument:
    if has_disturbances(doc):
        return normalize_scenario_document(layout, doc, context_cache=context_cache, sha_cache=sha_cache)
    return validate_empty_scenario(layout, doc, sha_cache=sha_cache)


def clear_scenario_validation(doc: ScenarioDocument) -> ScenarioDocument:
    return ScenarioDocument(
        name=doc.name,
        run_graph=RunGraphReference(set_id=doc.run_graph.set_id, graph_id=doc.run_graph.graph_id),
        scenarios=doc.scenarios,
        path=doc.path,
    )


def validation_stamp(
    layout: ProjectLayout,
    doc: ScenarioDocument,
    *,
    sha_cache: Dict[tuple[str, str], str] | None = None,
) -> ScenarioValidation:
    return ScenarioValidation(
        context_sha256=cached_run_graph_context_sha256(layout, doc.run_graph, sha_cache),
        disturbances_sha256=scenario_disturbances_sha256(doc.scenarios),
        validated_at=datetime.now().isoformat(timespec="seconds"),
    )


def scenario_validation_state(
    layout: ProjectLayout,
    doc: ScenarioDocument,
    *,
    sha_cache: Dict[tuple[str, str], str] | None = None,
) -> Dict[str, object]:
    try:
        actual_context_sha256 = cached_run_graph_context_sha256(layout, doc.run_graph, sha_cache)
    except Exception as exc:
        return invalid_validation_state(str(exc))
    actual_disturbances_sha256 = scenario_disturbances_sha256(doc.scenarios)
    validation = doc.validation
    if not validation.context_sha256 and not validation.disturbances_sha256:
        return validation_state_payload(
            VALIDATION_PENDING,
            "未校验",
            actual_context_sha256=actual_context_sha256,
            actual_disturbances_sha256=actual_disturbances_sha256,
            validation=validation,
        )
    reasons = []
    if validation.context_sha256 != actual_context_sha256:
        reasons.append("运行图已变化")
    if validation.disturbances_sha256 != actual_disturbances_sha256:
        reasons.append("扰动已修改")
    if reasons:
        return validation_state_payload(
            VALIDATION_STALE,
            "，".join(reasons) + "，需重新校验",
            actual_context_sha256=actual_context_sha256,
            actual_disturbances_sha256=actual_disturbances_sha256,
            validation=validation,
        )
    return validation_state_payload(
        VALIDATION_VALID,
        "校验通过",
        actual_context_sha256=actual_context_sha256,
        actual_disturbances_sha256=actual_disturbances_sha256,
        validation=validation,
    )


def require_scenario_validation(
    layout: ProjectLayout,
    doc: ScenarioDocument,
    *,
    sha_cache: Dict[tuple[str, str], str] | None = None,
) -> None:
    state = scenario_validation_state(layout, doc, sha_cache=sha_cache)
    if state["status"] != VALIDATION_VALID:
        raise ValueError(f"Scenario must be validated before use: {doc.name} ({state['reason']})")


def cached_run_graph_context_sha256(
    layout: ProjectLayout,
    run_graph: RunGraphReference,
    cache: Dict[tuple[str, str], str] | None,
) -> str:
    if cache is None:
        return run_graph_context_sha256(layout, run_graph)
    key = (run_graph.set_id, run_graph.graph_id)
    if key not in cache:
        cache[key] = run_graph_context_sha256(layout, run_graph)
    return cache[key]


def cached_load_scenario_context(
    layout: ProjectLayout,
    doc: ScenarioDocument,
    cache: Dict[tuple[str, str, str], object] | None,
) -> object:
    if cache is None:
        return load_scenario_context(layout, doc)
    run_graph = doc.run_graph
    key = (run_graph.set_id, run_graph.graph_id, run_graph.context_sha256)
    if key not in cache:
        cache[key] = load_scenario_context(layout, doc)
    return cache[key]


def invalid_validation_state(reason: str) -> Dict[str, object]:
    return validation_state_payload(VALIDATION_INVALID, reason)


def validation_state_payload(
    status: str,
    reason: str,
    *,
    actual_context_sha256: str = "",
    actual_disturbances_sha256: str = "",
    validation: ScenarioValidation | None = None,
) -> Dict[str, object]:
    return {
        "status": status,
        "reason": reason,
        "context_sha256": actual_context_sha256,
        "disturbances_sha256": actual_disturbances_sha256,
        "validation": asdict(validation or ScenarioValidation()),
    }


def has_disturbances(doc: ScenarioDocument) -> bool:
    return bool(doc.scenarios.get("delays") or doc.scenarios.get("speed_limits"))


def write_scenario_document(case: ScenarioCaseLayout, doc: ScenarioDocument) -> None:
    write_yaml(case.scenario_yml, scenario_document_to_yaml(doc))


def write_yaml(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(require_yaml().safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def check_scenario_yaml(
    case: ScenarioCaseLayout,
    scenario_id: str,
    *,
    validate_context: bool,
    layout: ProjectLayout | None = None,
) -> Dict[str, object]:
    try:
        doc = load_case_scenario_document(case, scenario_id)
    except Exception as exc:
        return yaml_check(INVALID_STATUS, str(exc))
    if not validate_context:
        return yaml_check(VALID_STATUS, "", document=doc)
    if layout is None:
        raise ValueError("layout is required when validate_context is true.")
    try:
        require_scenario_validation(layout, doc)
    except Exception as exc:
        return yaml_check(INVALID_STATUS, str(exc), document=doc)
    return yaml_check(VALID_STATUS, "", document=doc)


def yaml_check(status: str, reason: str, *, document: ScenarioDocument | None = None) -> Dict[str, object]:
    result: Dict[str, object] = {
        "yaml_status": status,
        "yaml_reason": reason,
    }
    if document is not None:
        result["_document"] = document
    return result


def iter_scenario_cases(layout: ProjectLayout) -> List[Dict[str, str]]:
    if not layout.scenario_sets_dir.is_dir():
        return []
    result: List[Dict[str, str]] = []
    for scenario_set_dir in sorted(path for path in layout.scenario_sets_dir.iterdir() if path.is_dir()):
        for scenario_path in scenario_files(scenario_set_dir):
            result.append({"scenario_set_id": scenario_set_dir.name, "scenario_id": scenario_path.stem})
    return result


def require_project(layout: ProjectLayout) -> None:
    if not layout.root.is_dir():
        raise FileNotFoundError(f"Project not found: {layout.root}")


def context_stats_payload(layout: ProjectLayout, doc: ScenarioDocument) -> Dict[str, object]:
    return context_stats(load_scenario_context(layout, doc))


def context_stats_from_run_graph_detail(detail: Mapping[str, object] | None) -> Dict[str, object] | None:
    if not detail:
        return None
    return {
        "station_count": int(detail.get("station_count") or 0),
        "train_count": int(detail.get("train_count") or 0),
        "total_mileage": float(detail.get("total_mileage") or 0),
        "event_node_count": int(detail.get("event_node_count") or 0),
        "section_node_count": int(detail.get("section_node_count") or 0),
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
        "coverage": disturbance_time_coverage(all_disturbances, []),
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
            "time_bins": time_bin_labels(),
            "type_time": type_time_rows(all_disturbances),
            "location_time": location_time_rows(all_disturbances),
        },
    }


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


def time_distribution(disturbances: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    buckets = {hour: 0 for hour in range(24)}
    unknown_count = 0
    for item in disturbances:
        if "start_time" not in item or item.get("start_time") in {None, ""}:
            unknown_count += 1
            continue
        start = int(float(item.get("start_time") or 0))
        hour = max(0, min(23, start // 3600))
        buckets[hour] += 1
    rows = [{"label": f"{hour:02d}:00", "count": count} for hour, count in buckets.items()]
    if unknown_count:
        rows.append({"label": "未知", "count": unknown_count})
    return rows


def time_bin_labels() -> List[str]:
    return [
        f"{hour:02d}-{hour + 2:02d}时"
        for hour in range(0, 24, 2)
    ]


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
    if value is None or value == "":
        return "未知"
    seconds = int(float(value))
    hour = max(0, min(23, seconds // 3600))
    start = (hour // 2) * 2
    return f"{start:02d}-{start + 2:02d}时"


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


def yaml_disturbances(doc: ScenarioDocument) -> List[Dict[str, object]]:
    disturbances: List[Dict[str, object]] = []
    for index, item in enumerate(list_payload(doc.scenarios.get("delays")), start=1):
        train_id = str(item.get("train_id", "") or "")
        station = str(item.get("station", "") or "")
        event_type = str(item.get("event_type", "") or "")
        disturbances.append(
            {
                "id": f"delay_{index}",
                "type": "delay",
                "train_id": train_id,
                "station": station,
                "event_type": event_type,
                "seconds": int(float(item.get("seconds", 0) or 0)),
                "start_time": None,
                "station_order": None,
            }
        )

    for index, item in enumerate(list_payload(doc.scenarios.get("speed_limits")), start=1):
        start_time = parse_seconds_of_day(item.get("start_time", 0))
        duration = int(float(item.get("duration", 0) or 0))
        limit_speed = float(item.get("limit_speed", 0) or 0)
        disturbances.append(
            {
                "id": f"speed_{index}",
                "type": "interruption" if limit_speed <= 20 else "speed_limit",
                "start_station": str(item.get("start_station", "") or ""),
                "end_station": str(item.get("end_station", "") or ""),
                "start_time": start_time,
                "end_time": start_time + duration,
                "duration": duration,
                "limit_speed": limit_speed,
                "section_order": None,
                "mileage": None,
            }
        )
    return disturbances


def list_payload(value: object) -> List[Mapping[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Scenario delays/speed_limits must be lists.")
    result: List[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("Scenario event must be a YAML object.")
        result.append(item)
    return result


def require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml

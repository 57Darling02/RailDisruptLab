from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from backend.analysis.disturbances import read_scenario_disturbances
from backend.analysis.timetable import plan_rows
from core.base_context import load_base_context
from core.project_layout import ProjectLayout, require_id, sanitize_id, to_posix
from core.scenario_config import scenario_files


SCENARIO_TYPE_LABELS = {
    "empty": "空场景",
    "delay": "纯晚点",
    "speed_limit": "纯限速",
    "interruption": "纯中断",
    "mixed": "混合",
}

DISTURBANCE_TYPE_LABELS = {
    "delay": "晚点",
    "speed_limit": "限速",
    "interruption": "中断",
}

RELATION_LABELS = {
    "same_anchor": "同锚点",
    "time_overlap": "时间重叠",
    "time_near": "时间相邻",
    "spatial_near": "空间相邻",
}

TIME_BIN_SECONDS = 2 * 3600
NEAR_TIME_SECONDS = 30 * 60
NEAR_SPACE_UNITS = 1.0


def read_scenario_set_visualization(layout: ProjectLayout, scenario_set_id: str) -> Dict[str, object]:
    from backend.scenario_cases import read_scenario_set_analysis

    detail = read_scenario_set_analysis(layout, scenario_set_id)
    detail.setdefault("mileage_by_station", {})
    detail.setdefault("train_routes", {})
    detail.setdefault("plan", {"rows": []})
    return detail


def scenario_visualization_item(path: Path, context: Any) -> Dict[str, object]:
    disturbances = read_scenario_disturbances(path, context)
    return {
        "scenario_id": sanitize_id(path.stem),
        "name": path.stem,
        "path": to_posix(path),
        "disturbances": disturbances,
        "counts": disturbance_counts(disturbances),
        "category": scenario_category(disturbances),
    }


def scenario_set_summary(
    scenarios: List[Dict[str, object]],
    context: Any,
    station_order: List[str],
    plan_rows_payload: List[Dict[str, object]],
) -> Dict[str, object]:
    all_disturbances = [
        dict(item, scenario_id=scenario["scenario_id"])
        for scenario in scenarios
        for item in scenario.get("disturbances", [])
        if isinstance(item, dict)
    ]
    category_counts = Counter(str(item.get("category", "empty")) for item in scenarios)
    total = max(len(scenarios), 1)
    pair_summary = disturbance_pair_summary(scenarios)
    return {
        "scenario_count": len(scenarios),
        "disturbance_counts": disturbance_counts(all_disturbances),
        "category_ratios": [
            {
                "key": key,
                "label": SCENARIO_TYPE_LABELS.get(key, key),
                "count": count,
                "ratio": round(count / total, 6),
            }
            for key, count in sorted(category_counts.items())
        ],
        "coverage": disturbance_coverage(all_disturbances, station_order, plan_rows_payload),
        "disturbances": all_disturbances,
        "math_graph_metrics": math_graph_metrics(
            scenarios,
            all_disturbances,
            context,
            pair_summary,
        ),
        "combination_complexity": combination_complexity(scenarios, pair_summary),
        "joint_structure": joint_structure(all_disturbances),
    }


def math_graph_metrics(
    scenarios: List[Dict[str, object]],
    disturbances: List[Dict[str, object]],
    context: Any,
    pair_summary: Dict[str, object],
) -> Dict[str, object]:
    event_anchor_total = len(getattr(context, "event_anchors", {}) or {}) if context is not None else 0
    section_anchor_total = len(getattr(context, "section_anchors", {}) or {}) if context is not None else 0
    used_event_anchors = {
        str(item.get("event_anchor_id"))
        for item in disturbances
        if item.get("type") == "delay" and item.get("event_anchor_id")
    }
    used_section_anchors = {
        str(item.get("section_anchor_id"))
        for item in disturbances
        if item.get("type") in {"speed_limit", "interruption"} and item.get("section_anchor_id")
    }
    target_node_count = len(disturbances)
    target_edge_count = int(pair_summary["edge_count"])
    possible_pair_count = int(pair_summary["possible_pair_count"])
    relation_density = target_edge_count / possible_pair_count if possible_pair_count else 0.0
    average_degree = (2 * target_edge_count / target_node_count) if target_node_count else 0.0
    type_counts = Counter(str(item.get("type", "")) for item in disturbances if item.get("type"))

    return {
        "cards": [
            metric_card("scenario_count", "场景样本数", len(scenarios)),
            metric_card("target_nodes", "扰动节点数", target_node_count),
            metric_card("target_edges", "辅助关系边数", target_edge_count),
            metric_card("relation_density", "辅助关系密度", relation_density, value_type="percent"),
            metric_card("average_degree", "平均关系度", average_degree),
            metric_card("type_entropy", "类型均衡度", normalized_entropy(type_counts.values()), value_type="percent"),
        ],
        "anchor_coverage": [
            coverage_metric("event_anchor", "事件锚点覆盖", len(used_event_anchors), event_anchor_total),
            coverage_metric("section_anchor", "区间锚点覆盖", len(used_section_anchors), section_anchor_total),
        ],
        "parameter_stats": parameter_stats(disturbances),
        "relation_counts": relation_rows(Counter(pair_summary["relation_counts"])),
    }


def combination_complexity(
    scenarios: List[Dict[str, object]],
    pair_summary: Dict[str, object],
) -> Dict[str, object]:
    scenario_count = len(scenarios)
    disturbance_totals = [
        int(dict(item.get("counts", {})).get("total", 0))
        for item in scenarios
    ]
    non_empty_count = sum(1 for value in disturbance_totals if value > 0)
    multi_count = sum(1 for value in disturbance_totals if value > 1)
    mixed_count = sum(1 for item in scenarios if item.get("category") == "mixed")

    return {
        "cards": [
            metric_card("mixed_ratio", "混合场景占比", safe_ratio(mixed_count, scenario_count), value_type="percent"),
            metric_card("multi_disturbance_ratio", "多扰动场景占比", safe_ratio(multi_count, scenario_count), value_type="percent"),
            metric_card("average_disturbances", "平均扰动数", mean(disturbance_totals)),
            metric_card(
                "average_disturbances_non_empty",
                "非空场景平均扰动数",
                mean(value for value in disturbance_totals if value > 0),
            ),
            metric_card("max_disturbances", "最大扰动数", max(disturbance_totals, default=0)),
        ],
        "count_distribution": [
            {"label": str(key), "count": count}
            for key, count in sorted(Counter(disturbance_totals).items())
        ],
        "type_pair_counts": [
            {"key": key, "label": key.replace("+", " + "), "count": count}
            for key, count in sorted(Counter(pair_summary["type_pair_counts"]).items())
        ],
        "relation_counts": relation_rows(Counter(pair_summary["relation_counts"])),
    }


def joint_structure(disturbances: List[Dict[str, object]]) -> Dict[str, object]:
    type_time = Counter()
    location_time = Counter()
    for item in disturbances:
        item_type = str(item.get("type", ""))
        if item_type not in DISTURBANCE_TYPE_LABELS:
            continue
        time_bin = time_bin_label(number_or_none(item.get("start_time")))
        type_label = DISTURBANCE_TYPE_LABELS[item_type]
        location = disturbance_location_label(item)
        type_time[(item_type, type_label, time_bin)] += 1
        if location:
            location_time[(item_type, type_label, location, time_bin)] += 1

    return {
        "time_bins": time_bin_labels(),
        "type_time": [
            {
                "type": item_type,
                "type_label": type_label,
                "time_bin": time_bin,
                "count": count,
            }
            for (item_type, type_label, time_bin), count in sorted(type_time.items())
        ],
        "location_time": [
            {
                "type": item_type,
                "type_label": type_label,
                "location": location,
                "time_bin": time_bin,
                "count": count,
            }
            for (item_type, type_label, location, time_bin), count in sorted(location_time.items())
        ],
    }


def disturbance_pair_summary(scenarios: List[Dict[str, object]]) -> Dict[str, object]:
    relation_counts: Counter[str] = Counter()
    type_pair_counts: Counter[str] = Counter()
    edge_count = 0
    possible_pair_count = 0

    for scenario in scenarios:
        disturbances = [
            item
            for item in scenario.get("disturbances", [])
            if isinstance(item, dict)
        ]
        for left_index, left in enumerate(disturbances):
            for right in disturbances[left_index + 1:]:
                possible_pair_count += 1
                type_pair_counts[type_pair_key(left, right)] += 1
                relations = disturbance_pair_relations(left, right)
                if relations:
                    edge_count += 1
                    relation_counts.update(relations)

    return {
        "possible_pair_count": possible_pair_count,
        "edge_count": edge_count,
        "relation_counts": dict(relation_counts),
        "type_pair_counts": dict(type_pair_counts),
    }


def metric_card(
    key: str,
    label: str,
    value: float | int,
    *,
    value_type: str = "number",
) -> Dict[str, object]:
    return {
        "key": key,
        "label": label,
        "value": round(float(value), 6) if isinstance(value, float) else value,
        "value_type": value_type,
    }


def coverage_metric(key: str, label: str, used: int, total: int) -> Dict[str, object]:
    return {
        "key": key,
        "label": label,
        "used": used,
        "total": total,
        "ratio": round(safe_ratio(used, total), 6),
    }


def relation_rows(counts: Counter[str]) -> List[Dict[str, object]]:
    return [
        {
            "key": key,
            "label": label,
            "count": int(counts.get(key, 0)),
        }
        for key, label in RELATION_LABELS.items()
    ]


def parameter_stats(disturbances: List[Dict[str, object]]) -> List[Dict[str, object]]:
    specs = [
        ("delay_seconds", "晚点时长", "delay", "seconds", "秒"),
        ("delay_start_time", "晚点发生时刻", "delay", "start_time", "秒"),
        ("speed_duration", "限速持续时长", "speed_limit", "duration", "秒"),
        ("speed_limit", "限速值", "speed_limit", "limit_speed", "km/h"),
        ("interruption_duration", "中断持续时长", "interruption", "duration", "秒"),
        ("interruption_start_time", "中断开始时刻", "interruption", "start_time", "秒"),
    ]
    rows = []
    for key, label, item_type, field, unit in specs:
        values = [
            value
            for value in (number_or_none(item.get(field)) for item in disturbances if item.get("type") == item_type)
            if value is not None and math.isfinite(value)
        ]
        rows.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "count": len(values),
                "min": round(min(values), 6) if values else None,
                "max": round(max(values), 6) if values else None,
                "mean": round(mean(values), 6) if values else None,
            }
        )
    return rows


def disturbance_pair_relations(left: Dict[str, object], right: Dict[str, object]) -> List[str]:
    relations: List[str] = []
    left_anchor = disturbance_anchor_key(left)
    right_anchor = disturbance_anchor_key(right)
    if left_anchor and left_anchor == right_anchor:
        relations.append("same_anchor")

    left_interval = raw_time_interval(left)
    right_interval = raw_time_interval(right)
    if left_interval and right_interval:
        if intervals_overlap(left_interval, right_interval):
            relations.append("time_overlap")
        elif interval_gap(left_interval, right_interval) <= NEAR_TIME_SECONDS:
            relations.append("time_near")

    left_location = disturbance_location_order(left)
    right_location = disturbance_location_order(right)
    if left_location is not None and right_location is not None:
        if abs(left_location - right_location) <= NEAR_SPACE_UNITS:
            relations.append("spatial_near")

    return relations


def disturbance_anchor_key(item: Dict[str, object]) -> str:
    if item.get("type") == "delay":
        return str(item.get("event_anchor_id", "") or "")
    if item.get("type") in {"speed_limit", "interruption"}:
        return str(item.get("section_anchor_id", "") or "")
    return ""


def raw_time_interval(item: Dict[str, object]) -> Tuple[float, float] | None:
    start = number_or_none(item.get("start_time"))
    if start is None:
        return None
    if item.get("type") == "delay":
        duration = max(number_or_none(item.get("seconds")) or 0.0, 0.0)
        return (start, start + duration)
    end = number_or_none(item.get("end_time"))
    if end is None:
        end = start + max(number_or_none(item.get("duration")) or 0.0, 0.0)
    return (start, end) if end >= start else (end, start)


def intervals_overlap(left: Tuple[float, float], right: Tuple[float, float]) -> bool:
    return min(left[1], right[1]) > max(left[0], right[0])


def interval_gap(left: Tuple[float, float], right: Tuple[float, float]) -> float:
    if intervals_overlap(left, right):
        return 0.0
    return max(left[0], right[0]) - min(left[1], right[1])


def disturbance_location_order(item: Dict[str, object]) -> float | None:
    if item.get("type") == "delay":
        return number_or_none(item.get("station_order"))
    return number_or_none(item.get("section_order"))


def disturbance_location_label(item: Dict[str, object]) -> str:
    if item.get("type") == "delay":
        return str(item.get("station", "") or "")
    start_station = str(item.get("start_station", "") or "")
    end_station = str(item.get("end_station", "") or "")
    return f"{start_station}-{end_station}" if start_station and end_station else ""


def type_pair_key(left: Dict[str, object], right: Dict[str, object]) -> str:
    keys = sorted(str(item.get("type", "")) for item in (left, right))
    labels = [DISTURBANCE_TYPE_LABELS.get(key, key) for key in keys if key]
    return "+".join(labels)


def time_bin_labels() -> List[str]:
    return [
        f"{hour:02d}-{hour + 2:02d}时"
        for hour in range(0, 24, 2)
    ]


def time_bin_label(seconds: float | None) -> str:
    labels = time_bin_labels()
    if seconds is None or not math.isfinite(seconds):
        return labels[0]
    index = max(0, min(int(seconds // TIME_BIN_SECONDS), len(labels) - 1))
    return labels[index]


def normalized_entropy(values: Iterable[int]) -> float:
    counts = [value for value in values if value > 0]
    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    entropy = -sum((value / total) * math.log(value / total) for value in counts)
    return entropy / math.log(len(DISTURBANCE_TYPE_LABELS))


def safe_ratio(numerator: float | int, denominator: float | int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def mean(values: Iterable[float | int]) -> float:
    items = [float(value) for value in values]
    return sum(items) / len(items) if items else 0.0


def disturbance_counts(disturbances: Iterable[Dict[str, object]]) -> Dict[str, int]:
    counts = {"delay": 0, "speed_limit": 0, "interruption": 0, "total": 0}
    for item in disturbances:
        item_type = str(item.get("type", ""))
        if item_type in counts:
            counts[item_type] += 1
            counts["total"] += 1
    return counts


def scenario_category(disturbances: List[Dict[str, object]]) -> str:
    types = {str(item.get("type", "")) for item in disturbances if item.get("type")}
    if not types:
        return "empty"
    if len(types) == 1:
        return next(iter(types))
    return "mixed"


def disturbance_coverage(
    disturbances: List[Dict[str, object]],
    station_order: List[str],
    plan_rows_payload: List[Dict[str, object]],
) -> Dict[str, object]:
    time_min, time_max = plan_time_extent(plan_rows_payload)
    total_time = max(time_max - time_min, 1)
    station_count = max(len(station_order), 1)
    section_count = max(len(station_order) - 1, 1)
    total_space = station_count + section_count
    station_index = {station: index for index, station in enumerate(station_order)}

    rows = [
        coverage_row(
            "all",
            "全部扰动",
            disturbances,
            station_index,
            time_min,
            time_max,
            total_time,
            total_space,
        )
    ]
    for item_type, label in [
        ("delay", "晚点"),
        ("speed_limit", "限速"),
        ("interruption", "中断"),
    ]:
        typed = [item for item in disturbances if item.get("type") == item_type]
        rows.append(
            coverage_row(
                item_type,
                label,
                typed,
                station_index,
                time_min,
                time_max,
                total_time,
                station_count if item_type == "delay" else section_count,
            )
        )

    return {
        "time_span_seconds": total_time,
        "space_span_units": total_space,
        "rows": rows,
    }


def coverage_row(
    item_type: str,
    label: str,
    disturbances: List[Dict[str, object]],
    station_index: Dict[str, int],
    time_min: int,
    time_max: int,
    total_time: int,
    total_space: int,
) -> Dict[str, object]:
    time_seconds = merged_interval_length(
        disturbance_time_interval(item, time_min, time_max)
        for item in disturbances
    )
    space_units = len(
        {
            unit
            for item in disturbances
            for unit in disturbance_space_units(item, station_index)
        }
    )
    return {
        "type": item_type,
        "label": label,
        "time_seconds": time_seconds,
        "time_ratio": round(min(time_seconds / total_time, 1.0), 6),
        "space_units": space_units,
        "space_ratio": round(min(space_units / max(total_space, 1), 1.0), 6),
    }


def plan_time_extent(rows: List[Dict[str, object]]) -> Tuple[int, int]:
    times = [
        value
        for row in rows
        for value in [
            parse_hms(row.get("arrival_time")),
            parse_hms(row.get("departure_time")),
        ]
        if value is not None
    ]
    if not times:
        return 0, 24 * 3600
    return min(times), max(times)


def disturbance_time_interval(
    item: Dict[str, object],
    time_min: int,
    time_max: int,
) -> Tuple[int, int] | None:
    if item.get("type") == "delay":
        start = number_or_none(item.get("start_time"))
        duration = max(int(float(item.get("seconds", 0) or 0)), 0)
        end = None if start is None else start + duration
    else:
        start = number_or_none(item.get("start_time"))
        end = number_or_none(item.get("end_time"))
        if start is not None and end is None:
            end = start + max(int(float(item.get("duration", 0) or 0)), 0)
    if start is None or end is None:
        return None
    clipped_start = max(int(start), time_min)
    clipped_end = min(int(end), time_max)
    return (clipped_start, clipped_end) if clipped_end > clipped_start else None


def merged_interval_length(intervals: Iterable[Tuple[int, int] | None]) -> int:
    merged: List[Tuple[int, int]] = []
    for interval in sorted(item for item in intervals if item is not None):
        start, end = interval
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum(end - start for start, end in merged)


def disturbance_space_units(item: Dict[str, object], station_index: Dict[str, int]) -> List[Tuple[str, int]]:
    if item.get("type") == "delay":
        index = station_index.get(str(item.get("station", "")))
        return [("station", index)] if index is not None else []
    start = station_index.get(str(item.get("start_station", "")))
    end = station_index.get(str(item.get("end_station", "")))
    if start is None or end is None:
        return []
    lower = min(start, end)
    upper = max(start, end)
    return [("section", index) for index in range(lower, upper)] or [("section", lower)]


def parse_hms(value: object) -> int | None:
    if not value:
        return None
    parts = str(value).split(":")
    if len(parts) != 3:
        return None
    try:
        hour, minute, second = [int(part) for part in parts]
    except ValueError:
        return None
    return hour * 3600 + minute * 60 + second


def number_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

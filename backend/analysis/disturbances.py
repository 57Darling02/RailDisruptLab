from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core.scenario_config import load_scenario_document


def read_scenario_disturbances(path: Path, context: Any) -> List[Dict[str, object]]:
    doc = load_scenario_document(path, require_yaml())
    disturbances: List[Dict[str, object]] = []
    event_anchors = getattr(context, "event_anchors", {})
    section_anchors = getattr(context, "section_anchors", {})

    for index, item in enumerate(doc.scenarios.get("delays", []) or [], start=1):
        anchor = event_anchors.get(str(item.get("event_anchor_id", "")))
        train_id = str(item.get("train_id", "") or getattr(anchor, "train_id", ""))
        station = str(item.get("station", "") or getattr(anchor, "station", ""))
        event_type = str(item.get("event_type", "") or getattr(anchor, "event_type", ""))
        disturbances.append(
            {
                "id": f"delay_{index}",
                "type": "delay",
                "event_anchor_id": str(item.get("event_anchor_id", "")),
                "train_id": train_id,
                "station": station,
                "event_type": event_type,
                "seconds": int(float(item.get("seconds", 0) or 0)),
                "start_time": getattr(anchor, "planned_time", None)
                or context.translated.event_time.get((train_id, station, event_type), 0),
                "station_order": getattr(anchor, "station_order", None),
            }
        )

    for index, item in enumerate(doc.scenarios.get("speed_limits", []) or [], start=1):
        anchor = section_anchors.get(str(item.get("section_anchor_id", "")))
        start_station = str(item.get("start_station", "") or getattr(anchor, "start_station", ""))
        end_station = str(item.get("end_station", "") or getattr(anchor, "end_station", ""))
        start_time = parse_seconds_of_day(item.get("start_time", 0))
        duration = int(float(item.get("duration", 0) or 0))
        limit_speed = float(item.get("limit_speed", 0) or 0)
        disturbances.append(
            {
                "id": f"speed_{index}",
                "type": "interruption" if limit_speed <= 20 else "speed_limit",
                "section_anchor_id": str(item.get("section_anchor_id", "")),
                "start_station": start_station,
                "end_station": end_station,
                "start_time": start_time,
                "end_time": start_time + duration,
                "duration": duration,
                "limit_speed": limit_speed,
                "section_order": getattr(anchor, "section_order", None),
                "mileage": getattr(anchor, "mileage", None),
            }
        )

    return disturbances


def parse_seconds_of_day(value: object) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    parts = str(value or "0").strip().split(":")
    if len(parts) == 3:
        hour, minute, second = [int(part) for part in parts]
        return hour * 3600 + minute * 60 + second
    if len(parts) == 2:
        hour, minute = [int(part) for part in parts]
        return hour * 3600 + minute * 60
    return int(float(str(value or 0)))


def require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: PyYAML") from exc
    return yaml

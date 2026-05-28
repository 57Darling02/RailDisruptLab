from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set

from core.types import EventKey, TranslatedData


def _format_seconds(value: float) -> str:
    total = int(round(value))
    hour = total // 3600
    minute = (total % 3600) // 60
    second = total % 60
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _time_of(
    values: Dict[str, float],
    event_id: Dict[EventKey, str],
    legacy_event_time: Dict[EventKey, float],
    event_key: EventKey,
) -> Optional[str]:
    token = event_id.get(event_key)
    if token is None:
        return None
    var_name = f"t_{token}"
    if var_name not in values:
        legacy_value = legacy_event_time.get(event_key)
        if legacy_value is None:
            return None
        return _format_seconds(legacy_value)
    return _format_seconds(values[var_name])


def _planned_time_of(translated: TranslatedData, event_key: EventKey) -> Optional[str]:
    planned_value = translated.event_time.get(event_key)
    if planned_value is None:
        return None
    return _format_seconds(planned_value)


def _strip_optional_quotes(text: str) -> str:
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _parse_event_tuple_var_name(var_name: str, base_name: str) -> Optional[EventKey]:
    for prefix in (f"{base_name}(", f"{base_name}["):
        if not var_name.startswith(prefix):
            continue

        closer = ")" if prefix.endswith("(") else "]"
        if not var_name.endswith(closer):
            return None

        inner = var_name[len(prefix) : -1].strip()
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1].strip()

        parts = [_strip_optional_quotes(part) for part in inner.split(",")]
        if len(parts) != 3 or any(part == "" for part in parts):
            return None

        train_id, station, event_type = parts
        return train_id, station, event_type

    return None


def _parse_legacy_event_var_name(var_name: str) -> Optional[EventKey]:
    # Legacy solutions may use:
    #   event_start_time(train_id,station,event_type)
    # or
    #   event_start_time[train_id,station,event_type]
    return _parse_event_tuple_var_name(var_name, "event_start_time")


def _build_legacy_event_time_map(values: Dict[str, float]) -> Dict[EventKey, float]:
    legacy_event_time: Dict[EventKey, float] = {}
    for var_name, var_value in values.items():
        event_key = _parse_legacy_event_var_name(var_name)
        if event_key is None:
            continue
        legacy_event_time[event_key] = var_value
    return legacy_event_time


def _parse_legacy_cancellation_var_name(var_name: str) -> Optional[EventKey]:
    return _parse_event_tuple_var_name(var_name, "cancellation")


def _build_cancellation_map(
    values: Dict[str, float],
    event_id: Dict[EventKey, str],
) -> Dict[EventKey, float]:
    cancellation_by_event: Dict[EventKey, float] = {}
    event_by_token = {token: event_key for event_key, token in event_id.items()}

    for var_name, var_value in values.items():
        if var_name.startswith("c_"):
            event_key = event_by_token.get(var_name[2:])
            if event_key is not None:
                cancellation_by_event[event_key] = var_value
                continue

        event_key = _parse_legacy_cancellation_var_name(var_name)
        if event_key is not None:
            cancellation_by_event[event_key] = var_value

    return cancellation_by_event


def _build_canceled_train_ids(
    translated: TranslatedData,
    cancellation_by_event: Dict[EventKey, float],
) -> Set[str]:
    if not cancellation_by_event:
        return set()

    return {
        train_id
        for train_id in translated.train_ids
        if any(
            cancellation_by_event.get((train_id, station, event_type), 0.0) >= 0.5
            for station in translated.train_routes[train_id]
            for event_type in ("arr", "dep")
        )
    }


def export_adjusted_timetable(
    translated: TranslatedData,
    values: Dict[str, float],
    output_path: Path,
) -> List[Dict[str, object]]:
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: openpyxl") from exc

    rows = adjusted_timetable_rows(translated, values)

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Sheet1"
    worksheet.append(["train_id", "station", "arrival_time", "departure_time", "is_canceled"])

    for row in rows:
        worksheet.append(
            [
                row["train_id"],
                row["station"],
                row["arrival_time"],
                row["departure_time"],
                int(bool(row["is_canceled"])),
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return rows


def adjusted_timetable_rows(
    translated: TranslatedData,
    values: Dict[str, float],
) -> List[Dict[str, object]]:
    event_id = {event_key: f"e{idx}" for idx, event_key in enumerate(translated.event_keys, start=1)}
    legacy_event_time = _build_legacy_event_time_map(values)
    canceled_train_ids = _build_canceled_train_ids(
        translated,
        _build_cancellation_map(values, event_id),
    )
    rows: List[Dict[str, object]] = []
    row_number = 1
    for train_id in translated.train_ids:
        is_canceled = train_id in canceled_train_ids
        for station in translated.train_routes[train_id]:
            arr_key = (train_id, station, "arr")
            dep_key = (train_id, station, "dep")
            if is_canceled:
                arr = _planned_time_of(translated, arr_key)
                dep = _planned_time_of(translated, dep_key)
            else:
                arr = _time_of(values, event_id, legacy_event_time, arr_key)
                dep = _time_of(values, event_id, legacy_event_time, dep_key)
            if arr is None and dep is None:
                continue
            rows.append(
                {
                    "train_id": train_id,
                    "station": station,
                    "arrival_time": arr,
                    "departure_time": dep,
                    "is_canceled": is_canceled,
                    "row_number": row_number,
                }
            )
            row_number += 1
    return rows

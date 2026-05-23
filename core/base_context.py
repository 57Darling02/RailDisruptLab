from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from core.translator import translate
from core.types import (
    BaseContext,
    EventAnchor,
    EventKey,
    MileageRow,
    RawTable,
    SectionAnchor,
    SectionKey,
    TimetableRow,
    TrainSectionKey,
    TranslatedData,
    ValidatedInput,
)
from core.validator import _validate_mileage_rows, _validate_station_coverage, _validate_timetable_rows

SCHEMA_VERSION = 1


def default_base_context_path(timetable_path: Path) -> Path:
    return timetable_path.parent / f"context_{timetable_path.stem}.json"


def build_base_context(
    timetable_path: Path,
    mileage_path: Path,
    timetable_sheet_name: str,
    mileage_sheet_name: str,
    timetable_table: RawTable,
    mileage_table: RawTable,
) -> BaseContext:
    timetable_rows = _validate_timetable_rows(timetable_table)
    mileage_rows = _validate_mileage_rows(mileage_table)
    _validate_station_coverage(timetable_rows, mileage_rows)

    validated = ValidatedInput(timetable_rows=timetable_rows, mileage_rows=mileage_rows)
    translated = translate(validated, None)  # translate currently keeps config only for forward compatibility.
    mileage_by_station = {row.station: row.mileage for row in mileage_rows}
    station_order = [row.station for row in sorted(mileage_rows, key=lambda item: item.mileage)]

    return BaseContext(
        schema_version=SCHEMA_VERSION,
        source_timetable_path=timetable_path,
        source_mileage_path=mileage_path,
        timetable_sheet_name=timetable_sheet_name,
        mileage_sheet_name=mileage_sheet_name,
        validated=validated,
        translated=translated,
        station_order=station_order,
        mileage_by_station=mileage_by_station,
        event_anchors=_build_event_anchors(translated, station_order),
        section_anchors=_build_section_anchors(translated, mileage_by_station),
    )


def event_anchor_key(anchor: EventAnchor) -> EventKey:
    return anchor.train_id, anchor.station, anchor.event_type


def section_anchor_key(anchor: SectionAnchor) -> SectionKey:
    return anchor.start_station, anchor.end_station


def event_anchor_by_key(context: BaseContext) -> Dict[EventKey, EventAnchor]:
    return {event_anchor_key(anchor): anchor for anchor in context.event_anchors.values()}


def section_anchor_by_key(context: BaseContext) -> Dict[SectionKey, SectionAnchor]:
    return {section_anchor_key(anchor): anchor for anchor in context.section_anchors.values()}


def write_base_context(context: BaseContext, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_base_context_to_payload(context), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_base_context(path: Path) -> BaseContext:
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = int(payload.get("schema_version", 0))
    if version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported base context schema_version: {version}")
    return _base_context_from_payload(payload)


def _build_event_anchors(translated: TranslatedData, station_order: List[str]) -> Dict[str, EventAnchor]:
    train_index = {train_id: idx for idx, train_id in enumerate(translated.train_ids)}
    station_index = {station: idx for idx, station in enumerate(station_order)}
    anchors: Dict[str, EventAnchor] = {}
    for idx, (train_id, station, event_type) in enumerate(translated.event_keys, start=1):
        anchor_id = f"E{idx:06d}"
        anchors[anchor_id] = EventAnchor(
            anchor_id=anchor_id,
            train_id=train_id,
            station=station,
            event_type=event_type,
            planned_time=translated.event_time[(train_id, station, event_type)],
            train_index=train_index[train_id],
            station_index=station_index.get(station, -1),
            direction=translated.train_directions.get(train_id, ""),
            station_order=station_index.get(station, -1),
        )
    return anchors


def _build_section_anchors(translated: TranslatedData, mileage_by_station: Dict[str, float]) -> Dict[str, SectionAnchor]:
    seen: set[SectionKey] = set()
    ordered_sections: List[SectionKey] = []
    for train_id in translated.train_ids:
        for section in translated.train_sections[train_id]:
            if section in seen:
                continue
            seen.add(section)
            ordered_sections.append(section)

    anchors: Dict[str, SectionAnchor] = {}
    for idx, (start_station, end_station) in enumerate(ordered_sections, start=1):
        start_mileage = mileage_by_station[start_station]
        end_mileage = mileage_by_station[end_station]
        anchor_id = f"S{idx:06d}"
        anchors[anchor_id] = SectionAnchor(
            anchor_id=anchor_id,
            start_station=start_station,
            end_station=end_station,
            direction="down" if end_mileage > start_mileage else "up",
            section_order=idx - 1,
            mileage=abs(end_mileage - start_mileage),
            min_runtime=translated.section_min_runtime[(start_station, end_station)],
        )
    return anchors


def _rows_to_payload(rows: Iterable[TimetableRow | MileageRow]) -> List[Dict[str, Any]]:
    return [asdict(row) for row in rows]


def _event_key_payload(key: EventKey) -> List[str]:
    return [key[0], key[1], key[2]]


def _section_key_payload(key: SectionKey) -> List[str]:
    return [key[0], key[1]]


def _train_section_key_payload(key: TrainSectionKey) -> List[str]:
    return [key[0], key[1], key[2]]


def _order_key_payload(key: Tuple[str, str, str, str]) -> List[str]:
    return [key[0], key[1], key[2], key[3]]


def _translated_to_payload(translated: TranslatedData) -> Dict[str, Any]:
    return {
        "train_ids": translated.train_ids,
        "train_directions": translated.train_directions,
        "train_routes": translated.train_routes,
        "train_origins": translated.train_origins,
        "train_destinations": translated.train_destinations,
        "train_stops": translated.train_stops,
        "event_keys": [_event_key_payload(key) for key in translated.event_keys],
        "event_time": [
            {"key": _event_key_payload(key), "value": value}
            for key, value in translated.event_time.items()
        ],
        "station_min_dwell": translated.station_min_dwell,
        "section_min_runtime": [
            {"key": _section_key_payload(key), "value": value}
            for key, value in translated.section_min_runtime.items()
        ],
        "train_sections": {
            train_id: [_section_key_payload(section) for section in sections]
            for train_id, sections in translated.train_sections.items()
        },
        "planned_section_runtime": [
            {"key": _train_section_key_payload(key), "value": value}
            for key, value in translated.planned_section_runtime.items()
        ],
        "arr_order_pair": [_order_key_payload(key) for key in translated.arr_order_pair],
        "dep_order_pair": [_order_key_payload(key) for key in translated.dep_order_pair],
        "arr_order_single": [_order_key_payload(key) for key in translated.arr_order_single],
        "dep_order_single": [_order_key_payload(key) for key in translated.dep_order_single],
    }


def _base_context_to_payload(context: BaseContext) -> Dict[str, Any]:
    return {
        "schema_version": context.schema_version,
        "source": {
            "timetable_path": str(context.source_timetable_path).replace("\\", "/"),
            "mileage_path": str(context.source_mileage_path).replace("\\", "/"),
            "timetable_sheet_name": context.timetable_sheet_name,
            "mileage_sheet_name": context.mileage_sheet_name,
        },
        "validated": {
            "timetable_rows": _rows_to_payload(context.validated.timetable_rows),
            "mileage_rows": _rows_to_payload(context.validated.mileage_rows),
        },
        "translated": _translated_to_payload(context.translated),
        "station_order": context.station_order,
        "mileage_by_station": context.mileage_by_station,
        "event_anchors": [asdict(anchor) for anchor in context.event_anchors.values()],
        "section_anchors": [asdict(anchor) for anchor in context.section_anchors.values()],
    }


def _event_key_from_payload(value: List[str]) -> EventKey:
    return str(value[0]), str(value[1]), str(value[2])


def _section_key_from_payload(value: List[str]) -> SectionKey:
    return str(value[0]), str(value[1])


def _train_section_key_from_payload(value: List[str]) -> TrainSectionKey:
    return str(value[0]), str(value[1]), str(value[2])


def _order_key_from_payload(value: List[str]) -> Tuple[str, str, str, str]:
    return str(value[0]), str(value[1]), str(value[2]), str(value[3])


def _translated_from_payload(payload: Dict[str, Any]) -> TranslatedData:
    return TranslatedData(
        train_ids=[str(item) for item in payload["train_ids"]],
        train_directions={str(k): str(v) for k, v in payload["train_directions"].items()},
        train_routes={str(k): [str(item) for item in v] for k, v in payload["train_routes"].items()},
        train_origins={str(k): str(v) for k, v in payload["train_origins"].items()},
        train_destinations={str(k): str(v) for k, v in payload["train_destinations"].items()},
        train_stops={str(k): [str(item) for item in v] for k, v in payload["train_stops"].items()},
        event_keys=[_event_key_from_payload(item) for item in payload["event_keys"]],
        event_time={
            _event_key_from_payload(item["key"]): int(item["value"])
            for item in payload["event_time"]
        },
        station_min_dwell={str(k): int(v) for k, v in payload["station_min_dwell"].items()},
        section_min_runtime={
            _section_key_from_payload(item["key"]): int(item["value"])
            for item in payload["section_min_runtime"]
        },
        train_sections={
            str(train_id): [_section_key_from_payload(section) for section in sections]
            for train_id, sections in payload["train_sections"].items()
        },
        planned_section_runtime={
            _train_section_key_from_payload(item["key"]): int(item["value"])
            for item in payload["planned_section_runtime"]
        },
        arr_order_pair=[_order_key_from_payload(item) for item in payload["arr_order_pair"]],
        dep_order_pair=[_order_key_from_payload(item) for item in payload["dep_order_pair"]],
        arr_order_single=[_order_key_from_payload(item) for item in payload["arr_order_single"]],
        dep_order_single=[_order_key_from_payload(item) for item in payload["dep_order_single"]],
    )


def _base_context_from_payload(payload: Dict[str, Any]) -> BaseContext:
    source = payload["source"]
    timetable_rows = [TimetableRow(**item) for item in payload["validated"]["timetable_rows"]]
    mileage_rows = [MileageRow(**item) for item in payload["validated"]["mileage_rows"]]
    event_anchors = {
        str(item["anchor_id"]): EventAnchor(**item)
        for item in payload["event_anchors"]
    }
    section_anchors = {
        str(item["anchor_id"]): SectionAnchor(**item)
        for item in payload["section_anchors"]
    }
    return BaseContext(
        schema_version=int(payload["schema_version"]),
        source_timetable_path=Path(source["timetable_path"]),
        source_mileage_path=Path(source["mileage_path"]),
        timetable_sheet_name=str(source["timetable_sheet_name"]),
        mileage_sheet_name=str(source["mileage_sheet_name"]),
        validated=ValidatedInput(timetable_rows=timetable_rows, mileage_rows=mileage_rows),
        translated=_translated_from_payload(payload["translated"]),
        station_order=[str(item) for item in payload["station_order"]],
        mileage_by_station={str(k): float(v) for k, v in payload["mileage_by_station"].items()},
        event_anchors=event_anchors,
        section_anchors=section_anchors,
    )

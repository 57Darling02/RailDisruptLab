from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

EventKey = Tuple[str, str, str]
SectionKey = Tuple[str, str]
TrainSectionKey = Tuple[str, str, str]
OrderKey = Tuple[str, str, str, str]


@dataclass(frozen=True)
class DelayScenario:
    event_anchor_id: str
    train_id: str
    station: str
    event_type: str
    seconds: int


@dataclass(frozen=True)
class SpeedLimitScenario:
    section_anchor_id: str
    start_station: str
    end_station: str
    start_time: int
    duration: int
    limit_speed: float

    @property
    def end_time(self) -> int:
        return self.start_time + self.duration


@dataclass(frozen=True)
class InputConfig:
    timetable_path: Path
    mileage_path: Path
    timetable_sheet_name: str
    mileage_sheet_name: str


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    output_dir: Path
    base_context_path: Path


@dataclass(frozen=True)
class BuildConfig:
    lp_path: Path


@dataclass(frozen=True)
class SolveConfig:
    lp_path: Path
    solution_path: Path


@dataclass(frozen=True)
class ExportTimetableConfig:
    solution_path: Path
    timetable_path: Path


@dataclass(frozen=True)
class AnalyzeConfig:
    adjusted_timetable_path: Path
    adjusted_timetable_sheet_name: str


@dataclass(frozen=True)
class SolverConfig:
    objective_delay_weight: float
    objective_mode: str
    cancellation_enabled: bool
    cancellation_penalty_weight: float
    arr_arr_headway_seconds: int
    dep_dep_headway_seconds: int
    dwell_seconds_at_stops: int
    big_m: int
    tolerance_delay_seconds: int


@dataclass(frozen=True)
class ScenarioConfig:
    delays: List[DelayScenario]
    speed_limits: List[SpeedLimitScenario]


@dataclass(frozen=True)
class AppConfig:
    project: ProjectConfig
    input: InputConfig
    solver: SolverConfig
    scenarios: ScenarioConfig
    build: BuildConfig
    solve: SolveConfig
    export_timetable: ExportTimetableConfig
    analyze: AnalyzeConfig
    base_context: BaseContext


@dataclass(frozen=True)
class RawTable:
    headers: List[str]
    rows: List[Dict[str, Optional[str]]]


@dataclass(frozen=True)
class TimetableRow:
    train_id: str
    station: str
    arrival_time: Optional[str]
    departure_time: Optional[str]
    row_number: int


@dataclass(frozen=True)
class MileageRow:
    station: str
    mileage: float
    row_number: int


@dataclass(frozen=True)
class ValidatedInput:
    timetable_rows: List[TimetableRow]
    mileage_rows: List[MileageRow]


@dataclass(frozen=True)
class TranslatedData:
    train_ids: List[str]
    train_directions: Dict[str, str]
    train_routes: Dict[str, List[str]]
    train_origins: Dict[str, str]
    train_destinations: Dict[str, str]
    train_stops: Dict[str, List[str]]
    event_keys: List[EventKey]
    event_time: Dict[EventKey, int]
    station_min_dwell: Dict[str, int]
    section_min_runtime: Dict[SectionKey, int]
    train_sections: Dict[str, List[SectionKey]]
    planned_section_runtime: Dict[TrainSectionKey, int]
    arr_order_pair: List[OrderKey]
    dep_order_pair: List[OrderKey]
    arr_order_single: List[OrderKey]
    dep_order_single: List[OrderKey]


@dataclass(frozen=True)
class EventAnchor:
    anchor_id: str
    train_id: str
    station: str
    event_type: str
    planned_time: int
    train_index: int
    station_index: int
    direction: str
    station_order: int


@dataclass(frozen=True)
class SectionAnchor:
    anchor_id: str
    start_station: str
    end_station: str
    direction: str
    section_order: int
    mileage: float
    min_runtime: int


@dataclass(frozen=True)
class BaseContext:
    schema_version: int
    source_timetable_path: Path
    source_mileage_path: Path
    timetable_sheet_name: str
    mileage_sheet_name: str
    validated: ValidatedInput
    translated: TranslatedData
    station_order: List[str]
    mileage_by_station: Dict[str, float]
    event_anchors: Dict[str, EventAnchor]
    section_anchors: Dict[str, SectionAnchor]


@dataclass(frozen=True)
class LinearConstraint:
    name: str
    coefficients: Dict[str, float]
    sense: str
    rhs: float


@dataclass(frozen=True)
class LinearModel:
    name: str
    variables: Dict[str, Tuple[float, Optional[float], str]]
    objective: Dict[str, float]
    objective_sense: str
    constraints: List[LinearConstraint]

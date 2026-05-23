from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from core.types import AppConfig, BaseContext, DelayScenario, ScenarioConfig, SpeedLimitScenario

SCHEMA_VERSION = 1
GRAPH_TYPE = "disturbance_graph"
DAY_SECONDS = 24 * 3600


def scenario_to_disturbance_graph(config: AppConfig) -> Dict[str, object]:
    disturbances: List[Dict[str, object]] = []
    role_edges: List[Dict[str, str]] = []
    next_id = 1

    for delay in config.scenarios.delays:
        disturbance_id = _disturbance_id(next_id)
        next_id += 1
        disturbances.append(
            {
                "disturbance_id": disturbance_id,
                "kind": "delay",
                "delay_seconds": int(delay.seconds),
            }
        )
        role_edges.append(
            {
                "source": disturbance_id,
                "target": delay.event_anchor_id,
                "role": "on_event",
            }
        )

    for speed_limit in config.scenarios.speed_limits:
        disturbance_id = _disturbance_id(next_id)
        next_id += 1
        disturbances.append(
            {
                "disturbance_id": disturbance_id,
                "kind": "speed_limit",
                "start_time": int(speed_limit.start_time),
                "duration": int(speed_limit.duration),
                "speed_limit": _clean_number(speed_limit.limit_speed),
            }
        )
        role_edges.append(
            {
                "source": disturbance_id,
                "target": speed_limit.section_anchor_id,
                "role": "on_section",
            }
        )

    graph: Dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "graph_type": GRAPH_TYPE,
        "base_context_path": str(config.project.base_context_path).replace("\\", "/"),
        "disturbances": disturbances,
        "role_edges": role_edges,
    }
    validate_disturbance_graph(graph, config.base_context)
    return graph


def disturbance_graph_to_scenario(graph: Dict[str, object], base_context: BaseContext) -> ScenarioConfig:
    validate_disturbance_graph(graph, base_context)
    edge_by_source = _single_edge_by_source(graph)

    delays: List[DelayScenario] = []
    speed_limits: List[SpeedLimitScenario] = []

    for disturbance in _disturbances(graph):
        disturbance_id = str(disturbance["disturbance_id"])
        edge = edge_by_source[disturbance_id]
        kind = str(disturbance["kind"])

        if kind == "delay":
            event_anchor_id = edge["target"]
            anchor = base_context.event_anchors[event_anchor_id]
            delays.append(
                DelayScenario(
                    event_anchor_id=event_anchor_id,
                    train_id=anchor.train_id,
                    station=anchor.station,
                    event_type=anchor.event_type,
                    seconds=_int_field(disturbance, "delay_seconds"),
                )
            )
            continue

        section_anchor_id = edge["target"]
        anchor = base_context.section_anchors[section_anchor_id]
        speed_limits.append(
            SpeedLimitScenario(
                section_anchor_id=section_anchor_id,
                start_station=anchor.start_station,
                end_station=anchor.end_station,
                start_time=_int_field(disturbance, "start_time"),
                duration=_int_field(disturbance, "duration"),
                limit_speed=_float_field(disturbance, "speed_limit"),
            )
        )

    return ScenarioConfig(delays=delays, speed_limits=speed_limits)


def validate_disturbance_graph(graph: Dict[str, object], base_context: BaseContext) -> None:
    if not isinstance(graph, dict):
        raise ValueError("Disturbance graph must be a JSON object.")
    if int(graph.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError(f"Unsupported disturbance graph schema_version: {graph.get('schema_version')}")
    if graph.get("graph_type") != GRAPH_TYPE:
        raise ValueError(f"Unsupported disturbance graph graph_type: {graph.get('graph_type')}")
    if "anchors" in graph:
        raise ValueError("Disturbance graph must not define anchors; use BaseContext anchors.")
    if not str(graph.get("base_context_path", "")).strip():
        raise ValueError("Missing disturbance graph base_context_path.")

    disturbances = _disturbances(graph)
    role_edges = _role_edges(graph)
    disturbance_ids = _validate_disturbance_ids(disturbances)
    edges_by_source = _validate_role_edges(role_edges, disturbance_ids, base_context)

    for disturbance in disturbances:
        disturbance_id = str(disturbance["disturbance_id"])
        kind = str(disturbance.get("kind", "")).strip()
        if kind == "delay":
            _validate_delay_disturbance(disturbance, edges_by_source[disturbance_id])
        elif kind == "speed_limit":
            _validate_speed_limit_disturbance(disturbance, edges_by_source[disturbance_id])
        else:
            raise ValueError(f"Unsupported disturbance kind for {disturbance_id}: {kind}")


def _disturbance_id(index: int) -> str:
    return f"D{index:06d}"


def _clean_number(value: float) -> int | float:
    value = float(value)
    return int(value) if value.is_integer() else value


def _disturbances(graph: Dict[str, object]) -> List[Dict[str, object]]:
    disturbances = graph.get("disturbances")
    if not isinstance(disturbances, list):
        raise ValueError("Disturbance graph disturbances must be a list.")
    if not all(isinstance(item, dict) for item in disturbances):
        raise ValueError("Each disturbance must be a JSON object.")
    return disturbances


def _role_edges(graph: Dict[str, object]) -> List[Dict[str, str]]:
    role_edges = graph.get("role_edges")
    if not isinstance(role_edges, list):
        raise ValueError("Disturbance graph role_edges must be a list.")
    if not all(isinstance(item, dict) for item in role_edges):
        raise ValueError("Each role edge must be a JSON object.")
    return role_edges


def _validate_disturbance_ids(disturbances: List[Dict[str, object]]) -> set[str]:
    disturbance_ids: set[str] = set()
    for disturbance in disturbances:
        disturbance_id = str(disturbance.get("disturbance_id", "")).strip()
        if not disturbance_id:
            raise ValueError("Disturbance is missing disturbance_id.")
        if disturbance_id in disturbance_ids:
            raise ValueError(f"Duplicated disturbance_id: {disturbance_id}")
        disturbance_ids.add(disturbance_id)
    return disturbance_ids


def _validate_role_edges(
    role_edges: List[Dict[str, str]],
    disturbance_ids: set[str],
    base_context: BaseContext,
) -> Dict[str, List[Dict[str, str]]]:
    edges_by_source: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for edge in role_edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        role = str(edge.get("role", "")).strip()
        if source not in disturbance_ids:
            raise ValueError(f"Unknown role edge source disturbance: {source}")
        if role == "on_event":
            if target not in base_context.event_anchors:
                raise ValueError(f"Unknown event anchor target: {target}")
        elif role == "on_section":
            if target not in base_context.section_anchors:
                raise ValueError(f"Unknown section anchor target: {target}")
        else:
            raise ValueError(f"Unsupported role edge role for {source}: {role}")
        edges_by_source[source].append({"source": source, "target": target, "role": role})
    for disturbance_id in disturbance_ids:
        if disturbance_id not in edges_by_source:
            raise ValueError(f"Disturbance has no role edge: {disturbance_id}")
    return edges_by_source


def _validate_delay_disturbance(disturbance: Dict[str, object], edges: List[Dict[str, str]]) -> None:
    disturbance_id = str(disturbance["disturbance_id"])
    delay_seconds = _int_field(disturbance, "delay_seconds")
    if delay_seconds <= 0:
        raise ValueError(f"Delay disturbance delay_seconds must be > 0: {disturbance_id}")
    _require_exact_role(disturbance_id, edges, expected_role="on_event")


def _validate_speed_limit_disturbance(disturbance: Dict[str, object], edges: List[Dict[str, str]]) -> None:
    disturbance_id = str(disturbance["disturbance_id"])
    if "end_time" in disturbance:
        raise ValueError(f"Speed limit disturbance must use duration, not end_time: {disturbance_id}")
    start_time = _int_field(disturbance, "start_time")
    duration = _int_field(disturbance, "duration")
    speed_limit = _float_field(disturbance, "speed_limit")
    if start_time < 0:
        raise ValueError(f"Speed limit disturbance start_time must be >= 0: {disturbance_id}")
    if duration <= 0:
        raise ValueError(f"Speed limit disturbance duration must be > 0: {disturbance_id}")
    if start_time + duration > DAY_SECONDS:
        raise ValueError(f"Speed limit disturbance start_time + duration must not exceed 24:00:00: {disturbance_id}")
    if speed_limit < 0:
        raise ValueError(f"Speed limit disturbance speed_limit must be >= 0: {disturbance_id}")
    _require_exact_role(disturbance_id, edges, expected_role="on_section")


def _require_exact_role(disturbance_id: str, edges: List[Dict[str, str]], expected_role: str) -> None:
    matching = [edge for edge in edges if edge["role"] == expected_role]
    if len(matching) != 1 or len(edges) != 1:
        raise ValueError(f"Disturbance {disturbance_id} must have exactly one {expected_role} edge.")


def _single_edge_by_source(graph: Dict[str, object]) -> Dict[str, Dict[str, str]]:
    return {edges[0]["source"]: edges[0] for edges in _validate_edges_after_validation(graph).values()}


def _validate_edges_after_validation(graph: Dict[str, object]) -> Dict[str, List[Dict[str, str]]]:
    edges_by_source: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for edge in _role_edges(graph):
        edges_by_source[str(edge["source"])].append(
            {
                "source": str(edge["source"]),
                "target": str(edge["target"]),
                "role": str(edge["role"]),
            }
        )
    return edges_by_source


def _int_field(payload: Dict[str, object], field_name: str) -> int:
    value = _required_field(payload, field_name)
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{field_name} must be an integer.")


def _float_field(payload: Dict[str, object], field_name: str) -> float:
    value = _required_field(payload, field_name)
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number.")
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"{field_name} must be a number.")


def _required_field(payload: Dict[str, object], field_name: str) -> Any:
    if field_name not in payload:
        identifier = payload.get("disturbance_id", "<unknown>")
        raise ValueError(f"Missing field {field_name} on disturbance {identifier}.")
    return payload[field_name]

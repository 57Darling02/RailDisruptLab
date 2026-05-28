from __future__ import annotations

import math
from copy import deepcopy
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.disturbance_graph import (
    DAY_SECONDS,
    GRAPH_TYPE as DISTURBANCE_GRAPH_TYPE,
    disturbance_graph_from_scenario,
    scenario_to_disturbance_graph,
    validate_disturbance_graph,
)
from core.types import AppConfig, BaseContext, EventAnchor, ScenarioConfig, SectionAnchor

SCHEMA_VERSION = 1
GRAPH_TYPE = "typed_vae_learning_graph"
GENERATED_GRAPH_TYPE = "generated_typed_disturbance_graph"
MATH_CONTEXT_GRAPH_TYPE = "vae_math_context_graph"
MATH_LEARNING_SAMPLE_TYPE = "vae_math_learning_sample"
MATH_GENERATED_GRAPH_TYPE = "vae_math_generated_graph"
PROFILE_GRAPH_TYPE = "vae_math_dataset_profile"

DEFAULT_MAX_SLOTS = 8
DEFAULT_SPEED_INTERRUPTION_THRESHOLD = 20.0
DEFAULT_SPEED_LIMIT_MAX = 350.0
DEFAULT_EVENT_TIME_WINDOW = 3600
DEFAULT_EVENT_TOP_K = 8
DEFAULT_SECTION_ORDER_WINDOW = 2

NODE_TYPE_EVENT_ANCHOR = 0
NODE_TYPE_SECTION_ANCHOR = 1
POOL_EVENT_ANCHORS = 0
POOL_SECTION_ANCHORS = 1
TASK_EVENT_DELAY = 0
TASK_SECTION_SPEED = 1
EDGE_TYPE_EVENT_EVENT_AUX = 0
EDGE_TYPE_SECTION_SECTION_AUX = 1
EDGE_TYPE_EVENT_SECTION_AUX = 2

EVENT_POOL_FEATURES = [
    "planned_time_norm",
    "train_index_norm",
    "station_index_norm",
    "direction_id",
    "station_order_norm",
    "event_type_id",
]
SECTION_POOL_FEATURES = [
    "section_order_norm",
    "mileage_norm",
    "min_runtime_norm",
    "direction_id",
]
EVENT_EVENT_EDGE_FEATURES = [
    "same_train",
    "same_station",
    "planned_time_diff_norm",
]
SECTION_SECTION_EDGE_FEATURES = [
    "mileage_diff_norm",
]
EVENT_SECTION_EDGE_FEATURES = [
    "train_route_contains_section",
    "station_to_section_order_distance_norm",
]
DISTURBANCE_RELATION_FEATURES = [
    "same_anchor",
    "spatial_near",
    "time_overlap",
    "time_gap_norm",
    "delay_section_route_near",
    "same_time_neighborhood",
]


def scenario_to_typed_vae_learning_graph(
    config: AppConfig,
    *,
    source_config_path: str = "",
    max_slots: int = DEFAULT_MAX_SLOTS,
    event_time_window: int = DEFAULT_EVENT_TIME_WINDOW,
    event_top_k: int = DEFAULT_EVENT_TOP_K,
    section_order_window: int = DEFAULT_SECTION_ORDER_WINDOW,
) -> Dict[str, object]:
    target_graph = scenario_to_disturbance_graph(config)
    return semantic_disturbance_graph_to_typed_learning_graph(
        target_graph,
        config.base_context,
        base_context_path=str(config.project.base_context_path).replace("\\", "/"),
        source_config_path=source_config_path,
        max_slots=max_slots,
        event_time_window=event_time_window,
        event_top_k=event_top_k,
        section_order_window=section_order_window,
    )


def scenario_config_to_typed_vae_learning_graph(
    scenarios: ScenarioConfig,
    base_context: BaseContext,
    *,
    base_context_path: str = "",
    source_config_path: str = "",
    max_slots: int = DEFAULT_MAX_SLOTS,
    event_time_window: int = DEFAULT_EVENT_TIME_WINDOW,
    event_top_k: int = DEFAULT_EVENT_TOP_K,
    section_order_window: int = DEFAULT_SECTION_ORDER_WINDOW,
) -> Dict[str, object]:
    target_graph = disturbance_graph_from_scenario(scenarios, base_context_path=base_context_path)
    return semantic_disturbance_graph_to_typed_learning_graph(
        target_graph,
        base_context,
        base_context_path=base_context_path,
        source_config_path=source_config_path,
        max_slots=max_slots,
        event_time_window=event_time_window,
        event_top_k=event_top_k,
        section_order_window=section_order_window,
    )


def semantic_disturbance_graph_to_typed_learning_graph(
    graph: Dict[str, object],
    base_context: BaseContext,
    *,
    base_context_path: str = "",
    source_config_path: str = "",
    max_slots: int = DEFAULT_MAX_SLOTS,
    event_time_window: int = DEFAULT_EVENT_TIME_WINDOW,
    event_top_k: int = DEFAULT_EVENT_TOP_K,
    section_order_window: int = DEFAULT_SECTION_ORDER_WINDOW,
) -> Dict[str, object]:
    validate_disturbance_graph(graph, base_context)
    context_pools, event_index, section_index = _context_pools(base_context)
    return {
        "schema_version": SCHEMA_VERSION,
        "graph_type": GRAPH_TYPE,
        "base_context_path": (base_context_path or str(graph.get("base_context_path", ""))).replace("\\", "/"),
        "source_config_path": source_config_path.replace("\\", "/"),
        "type_system": _type_system(),
        "context_pools": context_pools,
        "context_edges": _context_edges(
            base_context,
            event_index,
            section_index,
            event_time_window=event_time_window,
            event_top_k=event_top_k,
            section_order_window=section_order_window,
        ),
        "generation_tasks": _generation_tasks(max_slots),
        "targets": _targets_from_disturbance_graph(graph, event_index, section_index, max_slots),
        "derived_relations": derive_disturbance_relation_features(graph, base_context),
        "decode_contract": _decode_contract(max_slots),
    }


def derive_disturbance_relation_features(
    graph: Dict[str, object],
    base_context: BaseContext,
) -> List[Dict[str, object]]:
    validate_disturbance_graph(graph, base_context)
    role_by_source = _single_role_edge_by_source(graph)
    records: List[Dict[str, object]] = []
    delay_slot = 0
    section_slot = 0

    for disturbance in _objects(graph.get("disturbances"), "disturbances"):
        disturbance_id = str(disturbance["disturbance_id"])
        edge = role_by_source[disturbance_id]
        kind = str(disturbance["kind"])
        if kind == "delay":
            anchor = base_context.event_anchors[str(edge["target"])]
            records.append(
                {
                    "disturbance_id": disturbance_id,
                    "task_id": TASK_EVENT_DELAY,
                    "slot": delay_slot,
                    "anchor_id": anchor.anchor_id,
                    "anchor_kind": "event",
                    "station": anchor.station,
                    "train_id": anchor.train_id,
                    "time_start": int(anchor.planned_time),
                    "time_end": int(anchor.planned_time),
                    "section": None,
                }
            )
            delay_slot += 1
            continue

        anchor = base_context.section_anchors[str(edge["target"])]
        start_time = _int_field(disturbance, "start_time")
        duration = _int_field(disturbance, "duration")
        records.append(
            {
                "disturbance_id": disturbance_id,
                "task_id": TASK_SECTION_SPEED,
                "slot": section_slot,
                "anchor_id": anchor.anchor_id,
                "anchor_kind": "section",
                "station": "",
                "train_id": "",
                "time_start": start_time,
                "time_end": start_time + duration,
                "section": (anchor.start_station, anchor.end_station),
            }
        )
        section_slot += 1

    relations: List[Dict[str, object]] = []
    for left_index, left in enumerate(records):
        for right in records[left_index + 1 :]:
            features = _disturbance_relation_vector(left, right, base_context)
            relations.append(
                {
                    "left": {"task_id": left["task_id"], "slot": left["slot"]},
                    "right": {"task_id": right["task_id"], "slot": right["slot"]},
                    "features": features,
                    "debug": {
                        "left_disturbance_id": left["disturbance_id"],
                        "right_disturbance_id": right["disturbance_id"],
                    },
                }
            )
    return relations


def typed_learning_graph_to_math_context_graph(graph: Dict[str, object]) -> Dict[str, object]:
    if not isinstance(graph, dict):
        raise ValueError("Typed learning graph must be a JSON object.")
    if graph.get("graph_type") != GRAPH_TYPE:
        raise ValueError(f"Unsupported typed learning graph graph_type: {graph.get('graph_type')}")

    pools = graph.get("context_pools")
    if not isinstance(pools, dict):
        raise ValueError("Typed learning graph context_pools must be a JSON object.")
    generation_tasks = _objects(graph.get("generation_tasks"), "generation_tasks")
    context_edges = _objects(graph.get("context_edges"), "context_edges")

    return {
        "schema_version": SCHEMA_VERSION,
        "graph_type": MATH_CONTEXT_GRAPH_TYPE,
        "decode_handle": {
            "base_context_path": str(graph.get("base_context_path", "")).replace("\\", "/"),
        },
        "rules": {
            "pools": _math_pool_rules(pools),
            "tasks": _math_task_rules(generation_tasks),
            "edge_types": _math_edge_type_rules(),
            "target_relation_feature_dim": len(DISTURBANCE_RELATION_FEATURES),
        },
        "graph": {
            "pool_x": _math_pool_x(pools),
            "edges": _math_edges(context_edges),
        },
    }


def typed_learning_graph_to_math_learning_sample(
    graph: Dict[str, object],
    *,
    context_ref: str = "math_context.json",
    sample_id: str = "",
) -> Dict[str, object]:
    if not isinstance(graph, dict):
        raise ValueError("Typed learning graph must be a JSON object.")
    if graph.get("graph_type") != GRAPH_TYPE:
        raise ValueError(f"Unsupported typed learning graph graph_type: {graph.get('graph_type')}")
    targets = graph.get("targets")
    if not isinstance(targets, dict):
        raise ValueError("Typed learning graph targets must be a JSON object.")
    payload: Dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "graph_type": MATH_LEARNING_SAMPLE_TYPE,
        "context_ref": context_ref.replace("\\", "/"),
        "supervision": {
            "targets": _math_targets(targets),
            "target_relations": _math_target_relations(graph.get("derived_relations", [])),
        },
    }
    if sample_id:
        payload["sample_id"] = sample_id
    return payload


def infer_math_dataset_schema(
    context_graph: Dict[str, object],
    learning_samples: List[Dict[str, object]],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    if context_graph.get("graph_type") != MATH_CONTEXT_GRAPH_TYPE:
        raise ValueError(f"Unsupported math context graph graph_type: {context_graph.get('graph_type')}")
    rules = context_graph.get("rules")
    if not isinstance(rules, dict):
        raise ValueError("Math context graph rules must be a JSON object.")

    task_stats = _infer_task_stats(rules.get("tasks"), learning_samples)
    inferred = deepcopy(context_graph)
    inferred_rules = inferred["rules"]
    inferred_tasks: List[Dict[str, object]] = []
    for task in _objects(inferred_rules.get("tasks"), "rules.tasks"):
        task_id = _int_value(task.get("task_id"), "task.task_id")
        stat = task_stats[str(task_id)]
        updated = dict(task)
        updated["max_slots"] = int(stat["count_bounds"][1])
        updated["count_bounds"] = list(stat["count_bounds"])
        updated["param_bounds"] = [list(row) for row in stat["param_bounds"]]
        updated["slot_constraints"] = dict(stat["slot_count_per_disturbance"])
        inferred_tasks.append(updated)
    inferred_rules["tasks"] = inferred_tasks
    return inferred, {"tasks": task_stats}


def typed_learning_graph_to_dataset_profile(
    graph: Dict[str, object],
    *,
    export_profile: Dict[str, object] | None = None,
    samples: List[Dict[str, object]] | None = None,
    inferred_schema: Dict[str, object] | None = None,
) -> Dict[str, object]:
    if not isinstance(graph, dict):
        raise ValueError("Typed learning graph must be a JSON object.")
    if graph.get("graph_type") != GRAPH_TYPE:
        raise ValueError(f"Unsupported typed learning graph graph_type: {graph.get('graph_type')}")

    pools = graph.get("context_pools")
    if not isinstance(pools, dict):
        raise ValueError("Typed learning graph context_pools must be a JSON object.")

    return {
        "schema_version": SCHEMA_VERSION,
        "graph_type": PROFILE_GRAPH_TYPE,
        "math_context_graph_type": MATH_CONTEXT_GRAPH_TYPE,
        "math_learning_sample_type": MATH_LEARNING_SAMPLE_TYPE,
        "base_context_path": str(graph.get("base_context_path", "")).replace("\\", "/"),
        "export_profile": dict(export_profile or {}),
        "type_system": graph.get("type_system", {}),
        "pools": _profile_pools(pools),
        "tasks": _objects(graph.get("generation_tasks"), "generation_tasks"),
        "inferred_schema": dict(inferred_schema or {}),
        "decode_contract": graph.get("decode_contract", {}),
        "samples": list(samples or []),
    }


def summarize_math_context_graph(graph: Dict[str, object]) -> Dict[str, object]:
    if graph.get("graph_type") != MATH_CONTEXT_GRAPH_TYPE:
        raise ValueError(f"Unsupported math context graph graph_type: {graph.get('graph_type')}")
    rules = graph.get("rules", {})
    body = graph.get("graph", {})
    pool_counts = {
        str(pool["pool_id"]): int(pool["size"])
        for pool in _objects(rules.get("pools"), "rules.pools")
    } if isinstance(rules, dict) else {}
    edge_counts: Counter[str] = Counter()
    if isinstance(body, dict):
        for edge in _objects(body.get("edges"), "graph.edges"):
            edge_counts[str(edge.get("edge_type_id", ""))] += 1
    return {
        "graph_type": graph.get("graph_type", ""),
        "base_context_path": graph.get("decode_handle", {}).get("base_context_path", "")
        if isinstance(graph.get("decode_handle"), dict)
        else "",
        "pool_counts": dict(sorted(pool_counts.items())),
        "edge_counts": dict(sorted(edge_counts.items())),
    }


def validate_typed_generated_graph(
    graph: Dict[str, object],
    base_context: BaseContext,
    *,
    max_slots: int = DEFAULT_MAX_SLOTS,
) -> None:
    graph = normalize_generated_vae_graph(graph)
    if not isinstance(graph, dict):
        raise ValueError("Generated typed graph must be a JSON object.")
    if int(graph.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError(f"Unsupported generated typed graph schema_version: {graph.get('schema_version')}")
    if graph.get("graph_type") != GENERATED_GRAPH_TYPE:
        raise ValueError(f"Unsupported generated typed graph graph_type: {graph.get('graph_type')}")
    if not str(graph.get("base_context_path", "")).strip():
        raise ValueError("Generated typed graph is missing base_context_path.")

    outputs = graph.get("task_outputs")
    if not isinstance(outputs, dict):
        raise ValueError("Generated typed graph task_outputs must be a JSON object.")

    pool_sizes = {
        TASK_EVENT_DELAY: len(base_context.event_anchors),
        TASK_SECTION_SPEED: len(base_context.section_anchors),
    }
    for task in _generation_tasks(max_slots):
        task_id = int(task["task_id"])
        task_key = _task_key(task_id)
        if task_key not in outputs:
            raise ValueError(f"Generated typed graph is missing task output: {task_key}")
        _validate_task_output(
            task_key,
            outputs[task_key],
            task_id=task_id,
            param_dim=int(task["param_dim"]),
            max_slots=max_slots,
            pool_size=pool_sizes[task_id],
        )


def typed_generated_graph_to_disturbance_graph(
    graph: Dict[str, object],
    base_context: BaseContext,
    *,
    max_slots: int = DEFAULT_MAX_SLOTS,
    speed_interruption_threshold: float = DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
) -> Dict[str, object]:
    graph = normalize_generated_vae_graph(graph)
    validate_typed_generated_graph(graph, base_context, max_slots=max_slots)
    event_anchors = _sorted_event_anchors(base_context)
    section_anchors = _sorted_section_anchors(base_context)
    outputs = graph["task_outputs"]

    disturbances: List[Dict[str, object]] = []
    role_edges: List[Dict[str, str]] = []
    next_id = 1

    delay_output = outputs[_task_key(TASK_EVENT_DELAY)]
    for slot in range(int(delay_output["count"])):
        disturbance_id = _disturbance_id(next_id)
        next_id += 1
        delay_seconds = round(_number(delay_output["params"][slot][0], "delay_seconds_norm") * DAY_SECONDS)
        if delay_seconds <= 0:
            raise ValueError(f"Decoded delay_seconds must be > 0 for {disturbance_id}.")
        anchor = event_anchors[_int_value(delay_output["anchor_index"][slot], "anchor_index")]
        disturbances.append(
            {
                "disturbance_id": disturbance_id,
                "kind": "delay",
                "delay_seconds": int(delay_seconds),
            }
        )
        role_edges.append({"source": disturbance_id, "target": anchor.anchor_id, "role": "on_event"})

    section_output = outputs[_task_key(TASK_SECTION_SPEED)]
    for slot in range(int(section_output["count"])):
        disturbance_id = _disturbance_id(next_id)
        next_id += 1
        params = section_output["params"][slot]
        start_time = round(_number(params[0], "start_time_norm") * DAY_SECONDS)
        duration = round(_number(params[1], "duration_norm") * DAY_SECONDS)
        speed_value = _speed_limit_from_norm(_number(params[2], "speed_limit_norm"))
        speed_limit = 0 if speed_value < speed_interruption_threshold else _clean_number(speed_value)
        if start_time < 0:
            raise ValueError(f"Decoded start_time must be >= 0 for {disturbance_id}.")
        if duration <= 0:
            raise ValueError(f"Decoded duration must be > 0 for {disturbance_id}.")
        if start_time + duration > DAY_SECONDS:
            raise ValueError(f"Decoded start_time + duration must not exceed 24:00:00 for {disturbance_id}.")
        anchor = section_anchors[_int_value(section_output["anchor_index"][slot], "anchor_index")]
        disturbances.append(
            {
                "disturbance_id": disturbance_id,
                "kind": "speed_limit",
                "start_time": int(start_time),
                "duration": int(duration),
                "speed_limit": speed_limit,
            }
        )
        role_edges.append({"source": disturbance_id, "target": anchor.anchor_id, "role": "on_section"})

    disturbance_graph: Dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "graph_type": DISTURBANCE_GRAPH_TYPE,
        "base_context_path": str(graph["base_context_path"]).replace("\\", "/"),
        "disturbances": disturbances,
        "role_edges": role_edges,
    }
    validate_disturbance_graph(disturbance_graph, base_context)
    return disturbance_graph


def normalize_generated_vae_graph(graph: Dict[str, object]) -> Dict[str, object]:
    if not isinstance(graph, dict):
        raise ValueError("Generated VAE graph must be a JSON object.")
    graph_type = graph.get("graph_type")
    if graph_type == GENERATED_GRAPH_TYPE:
        return graph
    if graph_type != MATH_GENERATED_GRAPH_TYPE:
        raise ValueError(f"Unsupported generated VAE graph graph_type: {graph_type}")

    decode_handle = graph.get("decode_handle")
    if not isinstance(decode_handle, dict):
        raise ValueError("Generated math graph decode_handle must be a JSON object.")
    base_context_path = str(decode_handle.get("base_context_path", "")).strip()
    if not base_context_path:
        raise ValueError("Generated math graph decode_handle.base_context_path is required.")
    outputs = graph.get("task_outputs")
    if not isinstance(outputs, dict):
        raise ValueError("Generated math graph task_outputs must be a JSON object.")

    normalized_outputs: Dict[str, object] = {}
    for task in _generation_tasks(DEFAULT_MAX_SLOTS):
        task_id = int(task["task_id"])
        task_key = _task_key(task_id)
        output = outputs.get(str(task_id), outputs.get(task_key))
        if output is None:
            raise ValueError(f"Generated math graph is missing task output: {task_id}")
        normalized_outputs[task_key] = output

    return {
        "schema_version": int(graph.get("schema_version", SCHEMA_VERSION)),
        "graph_type": GENERATED_GRAPH_TYPE,
        "base_context_path": base_context_path.replace("\\", "/"),
        "task_outputs": normalized_outputs,
    }


def summarize_learning_graph(graph: Dict[str, object]) -> Dict[str, object]:
    pools = graph.get("context_pools", {})
    targets = graph.get("targets", {})
    edges = _objects(graph.get("context_edges"), "context_edges")
    edge_counts = Counter(str(edge.get("edge_type_id", "")) for edge in edges)
    pool_counts = {
        str(pool_key): len(_strings(pool.get("ids"), f"{pool_key}.ids"))
        for pool_key, pool in pools.items()
        if isinstance(pool, dict)
    } if isinstance(pools, dict) else {}
    target_counts = {
        task_key: int(task_target.get("count", 0))
        for task_key, task_target in targets.items()
        if isinstance(task_target, dict)
    } if isinstance(targets, dict) else {}
    return {
        "graph_type": graph.get("graph_type", ""),
        "base_context_path": graph.get("base_context_path", ""),
        "source_config_path": graph.get("source_config_path", ""),
        "pool_counts": dict(sorted(pool_counts.items())),
        "edge_counts": dict(sorted(edge_counts.items())),
        "target_counts": dict(sorted(target_counts.items())),
        "derived_relation_count": len(_objects(graph.get("derived_relations"), "derived_relations")),
    }


def relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _math_pool_rules(pools: Dict[str, object]) -> List[Dict[str, object]]:
    result: List[Dict[str, object]] = []
    for pool_key in sorted(pools, key=lambda key: int(str(key).split("_")[-1])):
        pool = pools[pool_key]
        if not isinstance(pool, dict):
            raise ValueError(f"{pool_key} must be a JSON object.")
        pool_id = _int_value(pool.get("pool_id"), f"{pool_key}.pool_id")
        x = _vectors(pool.get("x"), f"{pool_key}.x")
        feature_dim = len(x[0]) if x else len(_strings(pool.get("feature_names", []), f"{pool_key}.feature_names"))
        result.append(
            {
                "pool_id": pool_id,
                "size": len(x),
                "feature_dim": feature_dim,
            }
        )
    return result


def _math_task_rules(tasks: List[Dict[str, object]]) -> List[Dict[str, object]]:
    result: List[Dict[str, object]] = []
    for task in sorted(tasks, key=lambda item: int(item["task_id"])):
        task_id = _int_value(task.get("task_id"), "task.task_id")
        param_dim = _int_value(task.get("param_dim"), f"task_{task_id}.param_dim")
        rule: Dict[str, object] = {
            "task_id": task_id,
            "target_pool_id": _int_value(task.get("target_pool_id"), f"task_{task_id}.target_pool_id"),
            "max_slots": _int_value(task.get("max_slots"), f"task_{task_id}.max_slots"),
            "param_dim": param_dim,
            "param_bounds": _fallback_param_bounds(task_id, param_dim),
        }
        constraints = _task_param_constraints(task_id)
        if constraints:
            rule["param_constraints"] = constraints
        result.append(rule)
    return result


def _math_edge_type_rules() -> List[Dict[str, object]]:
    return [
        {
            "edge_type_id": EDGE_TYPE_EVENT_EVENT_AUX,
            "source_pool_id": POOL_EVENT_ANCHORS,
            "target_pool_id": POOL_EVENT_ANCHORS,
            "feature_dim": len(EVENT_EVENT_EDGE_FEATURES),
        },
        {
            "edge_type_id": EDGE_TYPE_SECTION_SECTION_AUX,
            "source_pool_id": POOL_SECTION_ANCHORS,
            "target_pool_id": POOL_SECTION_ANCHORS,
            "feature_dim": len(SECTION_SECTION_EDGE_FEATURES),
        },
        {
            "edge_type_id": EDGE_TYPE_EVENT_SECTION_AUX,
            "source_pool_id": POOL_EVENT_ANCHORS,
            "target_pool_id": POOL_SECTION_ANCHORS,
            "feature_dim": len(EVENT_SECTION_EDGE_FEATURES),
        },
    ]


def _math_pool_x(pools: Dict[str, object]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for pool in pools.values():
        if not isinstance(pool, dict):
            raise ValueError("Each context pool must be a JSON object.")
        pool_id = _int_value(pool.get("pool_id"), "pool_id")
        result[str(pool_id)] = _vectors(pool.get("x"), f"pool_{pool_id}.x")
    return result


def _math_edges(edges: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return [
        {
            "edge_type_id": _int_value(edge.get("edge_type_id"), "edge.edge_type_id"),
            "source_pool_id": _int_value(edge.get("source_pool_id"), "edge.source_pool_id"),
            "source_index": _int_value(edge.get("source_index"), "edge.source_index"),
            "target_pool_id": _int_value(edge.get("target_pool_id"), "edge.target_pool_id"),
            "target_index": _int_value(edge.get("target_index"), "edge.target_index"),
            "directed": bool(edge.get("directed", True)),
            "x": [_number(value, "edge.features") for value in _values(edge.get("features"), "edge.features")],
        }
        for edge in edges
    ]


def _math_targets(targets: Dict[str, object]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for task_key, target in targets.items():
        if not isinstance(target, dict):
            raise ValueError(f"Target {task_key} must be a JSON object.")
        task_id = _int_value(target.get("task_id"), f"{task_key}.task_id")
        result[str(task_id)] = {
            "count": _int_value(target.get("count"), f"{task_key}.count"),
            "anchor_index": [_int_value(value, f"{task_key}.anchor_index") for value in _values(target.get("anchor_index"), f"{task_key}.anchor_index")],
            "params": _vectors(target.get("params"), f"{task_key}.params"),
        }
    return result


def _infer_task_stats(
    tasks_value: object,
    learning_samples: List[Dict[str, object]],
) -> Dict[str, Dict[str, object]]:
    stats: Dict[str, Dict[str, object]] = {}
    for task in _objects(tasks_value, "rules.tasks"):
        task_id = _int_value(task.get("task_id"), "task.task_id")
        param_dim = _int_value(task.get("param_dim"), f"task_{task_id}.param_dim")
        counts: List[int] = []
        param_values: List[List[float]] = [[] for _ in range(param_dim)]
        anchor_lengths: List[int] = []
        param_lengths: List[int] = []

        for sample in learning_samples:
            supervision = sample.get("supervision")
            if not isinstance(supervision, dict):
                raise ValueError("Learning sample supervision must be a JSON object.")
            targets = supervision.get("targets")
            if not isinstance(targets, dict):
                raise ValueError("Learning sample supervision.targets must be a JSON object.")
            target = targets.get(str(task_id))
            if not isinstance(target, dict):
                raise ValueError(f"Learning sample is missing target: {task_id}")
            count = _int_value(target.get("count"), f"target_{task_id}.count")
            anchors = _values(target.get("anchor_index"), f"target_{task_id}.anchor_index")
            params = _vectors(target.get("params"), f"target_{task_id}.params")
            if len(anchors) != count or len(params) != count:
                raise ValueError(f"Target {task_id} anchor_index and params lengths must equal count.")
            counts.append(count)
            if count > 0:
                anchor_lengths.append(len(anchors) // count)
                param_lengths.append(len(params) // count)
            for row in params:
                if len(row) != param_dim:
                    raise ValueError(f"Target {task_id} params width must equal param_dim.")
                for dim, value in enumerate(row):
                    param_values[dim].append(float(value))

        if not counts:
            raise ValueError(f"No samples available to infer task {task_id} schema.")
        param_bounds = [
            _observed_bounds(values, fallback=_fallback_param_bounds(task_id, param_dim)[dim])
            for dim, values in enumerate(param_values)
        ]
        stats[str(task_id)] = {
            "count_bounds": [min(counts), max(counts)],
            "param_bounds": param_bounds,
            "observed_count_values": dict(sorted(Counter(counts).items())),
            "observed_param_stats": [
                _observed_param_stats(values)
                for values in param_values
            ],
            "slot_count_per_disturbance": {
                "anchor_count_bounds": _observed_bounds(anchor_lengths, fallback=[1, 1], integer=True),
                "param_row_count_bounds": _observed_bounds(param_lengths, fallback=[1, 1], integer=True),
            },
        }
    return stats


def _observed_bounds(
    values: List[float] | List[int],
    *,
    fallback: List[float] | List[int],
    integer: bool = False,
) -> List[float] | List[int]:
    if not values:
        return list(fallback)
    lower = min(values)
    upper = max(values)
    if integer:
        return [int(lower), int(upper)]
    if lower == upper:
        eps = max(1.0 / DAY_SECONDS, abs(float(lower)) * 0.01)
        lower = max(0.0, float(lower) - eps)
        upper = min(1.0, float(upper) + eps)
    return [float(lower), float(upper)]


def _observed_param_stats(values: List[float]) -> Dict[str, object]:
    if not values:
        return {"count": 0, "min": None, "max": None}
    total = sum(values)
    return {
        "count": len(values),
        "min": min(values),
        "mean": total / len(values),
        "max": max(values),
    }


def _math_target_relations(relations_value: object) -> List[Dict[str, object]]:
    result: List[Dict[str, object]] = []
    for relation in _objects(relations_value, "derived_relations"):
        left = relation.get("left")
        right = relation.get("right")
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise ValueError("Each derived relation must contain left and right JSON objects.")
        result.append(
            {
                "left_task_id": _int_value(left.get("task_id"), "relation.left.task_id"),
                "left_slot": _int_value(left.get("slot"), "relation.left.slot"),
                "right_task_id": _int_value(right.get("task_id"), "relation.right.task_id"),
                "right_slot": _int_value(right.get("slot"), "relation.right.slot"),
                "x": [_number(value, "relation.features") for value in _values(relation.get("features"), "relation.features")],
            }
        )
    return result


def _profile_pools(pools: Dict[str, object]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for pool in pools.values():
        if not isinstance(pool, dict):
            raise ValueError("Each context pool must be a JSON object.")
        pool_id = _int_value(pool.get("pool_id"), "pool_id")
        result[str(pool_id)] = {
            "feature_names": pool.get("feature_names", []),
            "ids": pool.get("ids", []),
            "debug": pool.get("debug", []),
        }
    return result


def _fallback_param_bounds(task_id: int, param_dim: int) -> List[List[float]]:
    if task_id == TASK_EVENT_DELAY:
        return [[1.0 / DAY_SECONDS, 1.0]]
    if task_id == TASK_SECTION_SPEED:
        return [[0.0, 1.0], [1.0 / DAY_SECONDS, 1.0], [0.0, 1.0]]
    return [[0.0, 1.0] for _ in range(param_dim)]


def _task_param_constraints(task_id: int) -> List[Dict[str, object]]:
    if task_id == TASK_SECTION_SPEED:
        return [
            {
                "constraint_type": "sum_leq",
                "param_indexes": [0, 1],
                "limit": 1.0,
                "repair_param_index": 1,
            }
        ]
    return []


def _type_system() -> Dict[str, object]:
    return {
        "node_types": {
            str(NODE_TYPE_EVENT_ANCHOR): "event_anchor",
            str(NODE_TYPE_SECTION_ANCHOR): "section_anchor",
        },
        "pool_types": {
            str(POOL_EVENT_ANCHORS): "event_anchor_pool",
            str(POOL_SECTION_ANCHORS): "section_anchor_pool",
        },
        "task_types": {
            str(TASK_EVENT_DELAY): "event_delay_task",
            str(TASK_SECTION_SPEED): "section_speed_task",
        },
        "edge_types": {
            str(EDGE_TYPE_EVENT_EVENT_AUX): "event_event_aux",
            str(EDGE_TYPE_SECTION_SECTION_AUX): "section_section_aux",
            str(EDGE_TYPE_EVENT_SECTION_AUX): "event_section_aux",
        },
        "pool_feature_names": {
            str(POOL_EVENT_ANCHORS): EVENT_POOL_FEATURES,
            str(POOL_SECTION_ANCHORS): SECTION_POOL_FEATURES,
        },
        "edge_feature_names": {
            str(EDGE_TYPE_EVENT_EVENT_AUX): EVENT_EVENT_EDGE_FEATURES,
            str(EDGE_TYPE_SECTION_SECTION_AUX): SECTION_SECTION_EDGE_FEATURES,
            str(EDGE_TYPE_EVENT_SECTION_AUX): EVENT_SECTION_EDGE_FEATURES,
        },
        "relation_feature_names": DISTURBANCE_RELATION_FEATURES,
    }


def _context_pools(base_context: BaseContext) -> Tuple[Dict[str, object], Dict[str, int], Dict[str, int]]:
    event_anchors = _sorted_event_anchors(base_context)
    section_anchors = _sorted_section_anchors(base_context)
    event_index = {anchor.anchor_id: index for index, anchor in enumerate(event_anchors)}
    section_index = {anchor.anchor_id: index for index, anchor in enumerate(section_anchors)}

    max_train_index = max((anchor.train_index for anchor in event_anchors), default=0)
    max_station_index = max((anchor.station_index for anchor in event_anchors), default=0)
    max_station_order = max((anchor.station_order for anchor in event_anchors), default=0)
    max_section_order = max((anchor.section_order for anchor in section_anchors), default=0)
    max_mileage = max((abs(float(anchor.mileage)) for anchor in section_anchors), default=1.0)
    max_runtime = max((abs(int(anchor.min_runtime)) for anchor in section_anchors), default=1)

    return (
        {
            _pool_key(POOL_EVENT_ANCHORS): {
                "pool_id": POOL_EVENT_ANCHORS,
                "node_type_id": NODE_TYPE_EVENT_ANCHOR,
                "feature_names": EVENT_POOL_FEATURES,
                "ids": [anchor.anchor_id for anchor in event_anchors],
                "x": [
                    [
                        _day_norm(anchor.planned_time),
                        _norm(anchor.train_index, max_train_index),
                        _norm(anchor.station_index, max_station_index),
                        _direction_id(anchor.direction),
                        _norm(anchor.station_order, max_station_order),
                        _event_type_id(anchor.event_type),
                    ]
                    for anchor in event_anchors
                ],
                "debug": [
                    {
                        "anchor_id": anchor.anchor_id,
                        "train_id": anchor.train_id,
                        "station": anchor.station,
                        "event_type": anchor.event_type,
                        "planned_time": int(anchor.planned_time),
                    }
                    for anchor in event_anchors
                ],
            },
            _pool_key(POOL_SECTION_ANCHORS): {
                "pool_id": POOL_SECTION_ANCHORS,
                "node_type_id": NODE_TYPE_SECTION_ANCHOR,
                "feature_names": SECTION_POOL_FEATURES,
                "ids": [anchor.anchor_id for anchor in section_anchors],
                "x": [
                    [
                        _norm(anchor.section_order, max_section_order),
                        _norm(anchor.mileage, max_mileage),
                        _norm(anchor.min_runtime, max_runtime),
                        _direction_id(anchor.direction),
                    ]
                    for anchor in section_anchors
                ],
                "debug": [
                    {
                        "anchor_id": anchor.anchor_id,
                        "start_station": anchor.start_station,
                        "end_station": anchor.end_station,
                        "direction": anchor.direction,
                    }
                    for anchor in section_anchors
                ],
            },
        },
        event_index,
        section_index,
    )


def _context_edges(
    base_context: BaseContext,
    event_index: Dict[str, int],
    section_index: Dict[str, int],
    *,
    event_time_window: int,
    event_top_k: int,
    section_order_window: int,
) -> List[Dict[str, object]]:
    edges: List[Dict[str, object]] = []
    edges.extend(_event_event_aux_edges(base_context, event_index, event_time_window, event_top_k))
    edges.extend(_section_section_aux_edges(base_context, section_index, section_order_window))
    edges.extend(_event_section_aux_edges(base_context, event_index, section_index))
    return edges


def _event_event_aux_edges(
    base_context: BaseContext,
    event_index: Dict[str, int],
    event_time_window: int,
    event_top_k: int,
) -> List[Dict[str, object]]:
    anchors = _sorted_event_anchors(base_context)
    if len(anchors) < 2:
        return []

    window = max(1, int(event_time_window))
    top_k = max(1, int(event_top_k))
    candidates: Dict[Tuple[str, str], Dict[str, object]] = {}
    by_anchor: Dict[str, List[Tuple[Tuple[str, str], Tuple[float, int, str]]]] = defaultdict(list)

    for left_index, left in enumerate(anchors):
        for right in anchors[left_index + 1 :]:
            raw = _event_event_raw_features(left, right, window)
            if not (raw["same_train"] or raw["same_station"] or raw["planned_time_diff"] <= window):
                continue
            pair = (left.anchor_id, right.anchor_id)
            candidates[pair] = raw
            rank = (
                -(float(raw["same_train"]) + float(raw["same_station"]) + float(raw["planned_time_affinity"])),
                int(raw["planned_time_diff"]),
                right.anchor_id,
            )
            by_anchor[left.anchor_id].append((pair, rank))
            by_anchor[right.anchor_id].append((pair, (rank[0], rank[1], left.anchor_id)))

    selected: set[Tuple[str, str]] = set()
    for anchor_id in sorted(by_anchor):
        selected.update(pair for pair, _rank in sorted(by_anchor[anchor_id], key=lambda item: item[1])[:top_k])

    return [
        _typed_edge(
            EDGE_TYPE_EVENT_EVENT_AUX,
            POOL_EVENT_ANCHORS,
            event_index[source],
            POOL_EVENT_ANCHORS,
            event_index[target],
            False,
            _event_event_feature_vector(candidates[(source, target)]),
            {"source_id": source, "target_id": target},
        )
        for source, target in sorted(selected)
    ]


def _section_section_aux_edges(
    base_context: BaseContext,
    section_index: Dict[str, int],
    section_order_window: int,
) -> List[Dict[str, object]]:
    anchors = _sorted_section_anchors(base_context)
    window = max(0, int(section_order_window))
    max_mileage = max((abs(float(anchor.mileage)) for anchor in anchors), default=1.0)
    edges: List[Dict[str, object]] = []

    for left_index, left in enumerate(anchors):
        for right in anchors[left_index + 1 :]:
            raw = _section_section_raw_features(left, right)
            if not (raw["shared_endpoint"] or raw["adjacent_section"] or raw["section_order_diff"] <= window):
                continue
            edges.append(
                _typed_edge(
                    EDGE_TYPE_SECTION_SECTION_AUX,
                    POOL_SECTION_ANCHORS,
                    section_index[left.anchor_id],
                    POOL_SECTION_ANCHORS,
                    section_index[right.anchor_id],
                    False,
                    _section_section_feature_vector(raw, max_mileage),
                    {"source_id": left.anchor_id, "target_id": right.anchor_id},
                )
            )
    return edges


def _event_section_aux_edges(
    base_context: BaseContext,
    event_index: Dict[str, int],
    section_index: Dict[str, int],
) -> List[Dict[str, object]]:
    station_index = {station: index for index, station in enumerate(base_context.station_order)}
    max_station_order = max(station_index.values(), default=0)
    section_anchors = _sorted_section_anchors(base_context)
    edges: List[Dict[str, object]] = []

    for event_anchor in _sorted_event_anchors(base_context):
        route_sections = set(base_context.translated.train_sections.get(event_anchor.train_id, []))
        for section_anchor in section_anchors:
            raw = _event_section_raw_features(event_anchor, section_anchor, station_index, route_sections)
            if not (raw["event_station_is_section_endpoint"] or raw["train_route_contains_section"]):
                continue
            edges.append(
                _typed_edge(
                    EDGE_TYPE_EVENT_SECTION_AUX,
                    POOL_EVENT_ANCHORS,
                    event_index[event_anchor.anchor_id],
                    POOL_SECTION_ANCHORS,
                    section_index[section_anchor.anchor_id],
                    False,
                    _event_section_feature_vector(raw, max_station_order),
                    {"source_id": event_anchor.anchor_id, "target_id": section_anchor.anchor_id},
                )
            )
    return edges


def _targets_from_disturbance_graph(
    graph: Dict[str, object],
    event_index: Dict[str, int],
    section_index: Dict[str, int],
    max_slots: int,
) -> Dict[str, object]:
    role_by_source = _single_role_edge_by_source(graph)
    delay_anchor_index: List[int] = []
    delay_params: List[List[float]] = []
    delay_debug: List[Dict[str, object]] = []
    section_anchor_index: List[int] = []
    section_params: List[List[float | int]] = []
    section_debug: List[Dict[str, object]] = []

    for disturbance in _objects(graph.get("disturbances"), "disturbances"):
        disturbance_id = str(disturbance["disturbance_id"])
        edge = role_by_source[disturbance_id]
        kind = str(disturbance["kind"])
        if kind == "delay":
            anchor_id = str(edge["target"])
            delay_anchor_index.append(event_index[anchor_id])
            delay_params.append([_day_norm(_int_field(disturbance, "delay_seconds"))])
            delay_debug.append({"disturbance_id": disturbance_id, "anchor_id": anchor_id})
            continue

        anchor_id = str(edge["target"])
        section_anchor_index.append(section_index[anchor_id])
        section_params.append(
            [
                _day_norm(_int_field(disturbance, "start_time")),
                _day_norm(_int_field(disturbance, "duration")),
                _speed_limit_norm(_float_field(disturbance, "speed_limit")),
            ]
        )
        section_debug.append({"disturbance_id": disturbance_id, "anchor_id": anchor_id})

    _check_target_count(_task_key(TASK_EVENT_DELAY), len(delay_anchor_index), max_slots)
    _check_target_count(_task_key(TASK_SECTION_SPEED), len(section_anchor_index), max_slots)
    return {
        _task_key(TASK_EVENT_DELAY): {
            "task_id": TASK_EVENT_DELAY,
            "count": len(delay_anchor_index),
            "anchor_index": delay_anchor_index,
            "params": delay_params,
            "debug": delay_debug,
        },
        _task_key(TASK_SECTION_SPEED): {
            "task_id": TASK_SECTION_SPEED,
            "count": len(section_anchor_index),
            "anchor_index": section_anchor_index,
            "params": section_params,
            "debug": section_debug,
        },
    }


def _generation_tasks(max_slots: int) -> List[Dict[str, object]]:
    slots = int(max_slots)
    if slots <= 0:
        raise ValueError("max_slots must be > 0.")
    return [
        {
            "task_id": TASK_EVENT_DELAY,
            "task_key": _task_key(TASK_EVENT_DELAY),
            "task_type_id": TASK_EVENT_DELAY,
            "target_pool_id": POOL_EVENT_ANCHORS,
            "max_slots": slots,
            "param_dim": 1,
            "param_names": ["delay_seconds_norm"],
        },
        {
            "task_id": TASK_SECTION_SPEED,
            "task_key": _task_key(TASK_SECTION_SPEED),
            "task_type_id": TASK_SECTION_SPEED,
            "target_pool_id": POOL_SECTION_ANCHORS,
            "max_slots": slots,
            "param_dim": 3,
            "param_names": ["start_time_norm", "duration_norm", "speed_limit_norm"],
        },
    ]


def _decode_contract(max_slots: int) -> Dict[str, object]:
    return {
        "day_seconds": DAY_SECONDS,
        "speed_limit_max": DEFAULT_SPEED_LIMIT_MAX,
        "generated_graph_type": GENERATED_GRAPH_TYPE,
        "tasks": {
            _task_key(TASK_EVENT_DELAY): {
                "task_id": TASK_EVENT_DELAY,
                "target_pool_id": POOL_EVENT_ANCHORS,
                "role": "on_event",
                "disturbance_kind": "delay",
                "max_slots": int(max_slots),
                "param_names": ["delay_seconds_norm"],
            },
            _task_key(TASK_SECTION_SPEED): {
                "task_id": TASK_SECTION_SPEED,
                "target_pool_id": POOL_SECTION_ANCHORS,
                "role": "on_section",
                "disturbance_kind": "speed_limit",
                "max_slots": int(max_slots),
                "param_names": ["start_time_norm", "duration_norm", "speed_limit_norm"],
                "speed_limit_rule": "speed_limit = speed_limit_norm * speed_limit_max",
                "interruption_rule": "speed_limit = 0 if decoded_speed < threshold else decoded_speed",
            },
        },
    }


def _validate_task_output(
    task_key: str,
    output: object,
    *,
    task_id: int,
    param_dim: int,
    max_slots: int,
    pool_size: int,
) -> None:
    if not isinstance(output, dict):
        raise ValueError(f"Task output {task_key} must be a JSON object.")
    count = _int_value(output.get("count"), f"{task_key}.count")
    if count < 0 or count > max_slots:
        raise ValueError(f"Task output {task_key} count must be between 0 and {max_slots}.")
    anchor_index = output.get("anchor_index")
    params = output.get("params")
    if not isinstance(anchor_index, list):
        raise ValueError(f"Task output {task_key} anchor_index must be a list.")
    if not isinstance(params, list):
        raise ValueError(f"Task output {task_key} params must be a list.")
    if len(anchor_index) != count:
        raise ValueError(f"Task output {task_key} anchor_index length must equal count.")
    if len(params) != count:
        raise ValueError(f"Task output {task_key} params length must equal count.")

    for slot in range(count):
        index = _int_value(anchor_index[slot], f"{task_key}.anchor_index[{slot}]")
        if index < 0 or index >= pool_size:
            raise ValueError(f"Task output {task_key} anchor_index[{slot}] is out of range.")
        row = params[slot]
        if not isinstance(row, list) or len(row) != param_dim:
            raise ValueError(f"Task output {task_key} params[{slot}] must have length {param_dim}.")
        values = [_number(value, f"{task_key}.params[{slot}]") for value in row]
        if task_id == TASK_EVENT_DELAY:
            if round(values[0] * DAY_SECONDS) <= 0:
                raise ValueError(f"Task output {task_key} params[{slot}] decodes to non-positive delay.")
        elif task_id == TASK_SECTION_SPEED:
            start_time = round(values[0] * DAY_SECONDS)
            duration = round(values[1] * DAY_SECONDS)
            speed_norm = values[2]
            if start_time < 0:
                raise ValueError(f"Task output {task_key} params[{slot}] decodes to negative start_time.")
            if duration <= 0:
                raise ValueError(f"Task output {task_key} params[{slot}] decodes to non-positive duration.")
            if start_time + duration > DAY_SECONDS:
                raise ValueError(f"Task output {task_key} params[{slot}] exceeds 24:00:00.")
            if speed_norm < 0.0 or speed_norm > 1.0:
                raise ValueError(f"Task output {task_key} params[{slot}] speed_limit_norm must be in [0, 1].")


def _disturbance_relation_vector(
    left: Dict[str, object],
    right: Dict[str, object],
    base_context: BaseContext,
) -> List[float]:
    same_anchor = int(left["anchor_id"] == right["anchor_id"])
    spatial_near = _spatial_near(left, right, base_context)
    left_start, left_end = int(left["time_start"]), int(left["time_end"])
    right_start, right_end = int(right["time_start"]), int(right["time_end"])
    time_overlap = int(left_start <= right_end and right_start <= left_end)
    time_gap = 0 if time_overlap else min(abs(left_start - right_end), abs(right_start - left_end))
    delay_section_route_near = _delay_section_route_near(left, right, base_context)
    same_time_neighborhood = int(time_overlap or time_gap <= DEFAULT_EVENT_TIME_WINDOW)
    return [
        float(same_anchor),
        float(spatial_near),
        float(time_overlap),
        _day_norm(time_gap),
        float(delay_section_route_near),
        float(same_time_neighborhood),
    ]


def _spatial_near(left: Dict[str, object], right: Dict[str, object], base_context: BaseContext) -> int:
    left_section = left.get("section")
    right_section = right.get("section")
    if left_section and right_section:
        return int(bool(set(left_section) & set(right_section)))
    if left_section or right_section:
        event = left if not left.get("section") else right
        section = left_section or right_section
        return int(str(event.get("station", "")) in set(section))
    if left.get("station") == right.get("station"):
        return 1
    station_index = {station: index for index, station in enumerate(base_context.station_order)}
    left_order = station_index.get(str(left.get("station", "")), -999)
    right_order = station_index.get(str(right.get("station", "")), 999)
    return int(abs(left_order - right_order) <= 1)


def _delay_section_route_near(left: Dict[str, object], right: Dict[str, object], base_context: BaseContext) -> int:
    event = None
    section = None
    if left.get("task_id") == TASK_EVENT_DELAY and right.get("section"):
        event = left
        section = right["section"]
    elif right.get("task_id") == TASK_EVENT_DELAY and left.get("section"):
        event = right
        section = left["section"]
    if event is None or section is None:
        return 0
    train_sections = set(base_context.translated.train_sections.get(str(event.get("train_id", "")), []))
    return int(section in train_sections or str(event.get("station", "")) in set(section))


def _event_event_raw_features(left: EventAnchor, right: EventAnchor, window: int) -> Dict[str, object]:
    time_diff = abs(int(left.planned_time) - int(right.planned_time))
    return {
        "same_train": int(left.train_id == right.train_id),
        "same_station": int(left.station == right.station),
        "planned_time_diff": time_diff,
        "planned_time_affinity": round(math.exp(-time_diff / max(1, window)), 8),
    }


def _event_event_feature_vector(raw: Dict[str, object]) -> List[float]:
    return [
        float(raw["same_train"]),
        float(raw["same_station"]),
        _day_norm(float(raw["planned_time_diff"])),
    ]


def _section_section_raw_features(left: SectionAnchor, right: SectionAnchor) -> Dict[str, object]:
    left_stations = {left.start_station, left.end_station}
    right_stations = {right.start_station, right.end_station}
    return {
        "shared_endpoint": int(bool(left_stations & right_stations)),
        "adjacent_section": int(left.end_station == right.start_station or right.end_station == left.start_station),
        "section_order_diff": abs(int(left.section_order) - int(right.section_order)),
        "mileage_diff": abs(float(left.mileage) - float(right.mileage)),
    }


def _section_section_feature_vector(
    raw: Dict[str, object],
    max_mileage: float,
) -> List[float]:
    return [
        _norm(float(raw["mileage_diff"]), max_mileage),
    ]


def _event_section_raw_features(
    event_anchor: EventAnchor,
    section_anchor: SectionAnchor,
    station_index: Dict[str, int],
    route_sections: set[Tuple[str, str]],
) -> Dict[str, object]:
    start_order = station_index.get(section_anchor.start_station, -1)
    end_order = station_index.get(section_anchor.end_station, -1)
    if start_order < 0 or end_order < 0 or event_anchor.station_order < 0:
        distance = -1
    else:
        distance = min(
            abs(int(event_anchor.station_order) - start_order),
            abs(int(event_anchor.station_order) - end_order),
        )
    section_key = (section_anchor.start_station, section_anchor.end_station)
    return {
        "event_station_is_section_endpoint": int(
            event_anchor.station in {section_anchor.start_station, section_anchor.end_station}
        ),
        "station_to_section_order_distance": distance,
        "train_route_contains_section": int(section_key in route_sections),
    }


def _event_section_feature_vector(raw: Dict[str, object], max_station_order: int) -> List[float]:
    distance = float(raw["station_to_section_order_distance"])
    return [
        float(raw["train_route_contains_section"]),
        0.0 if distance < 0 else _norm(distance, max_station_order),
    ]


def _typed_edge(
    edge_type_id: int,
    source_pool_id: int,
    source_index: int,
    target_pool_id: int,
    target_index: int,
    directed: bool,
    features: List[float],
    debug: Dict[str, object],
) -> Dict[str, object]:
    return {
        "edge_type_id": edge_type_id,
        "source_pool_id": source_pool_id,
        "source_index": source_index,
        "target_pool_id": target_pool_id,
        "target_index": target_index,
        "directed": directed,
        "features": features,
        "debug": debug,
    }


def _single_role_edge_by_source(graph: Dict[str, object]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for edge in _objects(graph.get("role_edges"), "role_edges"):
        source = str(edge["source"])
        result[source] = {"source": source, "target": str(edge["target"]), "role": str(edge["role"])}
    return result


def _check_target_count(task_key: str, count: int, max_slots: int) -> None:
    if count > int(max_slots):
        raise ValueError(f"{task_key} count {count} exceeds max_slots={max_slots}.")


def _task_key(task_id: int) -> str:
    return f"task_{task_id}"


def _pool_key(pool_id: int) -> str:
    return f"pool_{pool_id}"


def _disturbance_id(index: int) -> str:
    return f"D{index:06d}"


def _sorted_event_anchors(context: BaseContext) -> List[EventAnchor]:
    return sorted(context.event_anchors.values(), key=lambda anchor: anchor.anchor_id)


def _sorted_section_anchors(context: BaseContext) -> List[SectionAnchor]:
    return sorted(context.section_anchors.values(), key=lambda anchor: anchor.anchor_id)


def _direction_id(direction: str) -> int:
    normalized = str(direction).strip().lower()
    if normalized == "down":
        return 0
    if normalized == "up":
        return 1
    return 2


def _event_type_id(event_type: str) -> int:
    normalized = str(event_type).strip().lower()
    if normalized == "arr":
        return 0
    if normalized == "dep":
        return 1
    return 2


def _day_norm(value: int | float) -> float:
    return round(float(value) / DAY_SECONDS, 8)


def _speed_limit_norm(value: int | float) -> float:
    return round(float(value) / DEFAULT_SPEED_LIMIT_MAX, 8)


def _speed_limit_from_norm(value: int | float) -> float:
    return float(value) * DEFAULT_SPEED_LIMIT_MAX


def _norm(value: int | float, max_value: int | float) -> float:
    denominator = max(1.0, float(max_value))
    return round(float(value) / denominator, 8)


def _clean_number(value: float) -> int | float:
    value = float(value)
    nearest = round(value)
    if abs(value - nearest) <= 1e-6:
        return int(nearest)
    return round(value, 8)


def _objects(value: Any, label: str) -> List[Dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Each {label} item must be a JSON object.")
    return value


def _strings(value: Any, label: str) -> List[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return [str(item) for item in value]


def _values(value: Any, label: str) -> List[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return list(value)


def _vectors(value: Any, label: str) -> List[List[float]]:
    rows = _values(value, label)
    result: List[List[float]] = []
    width = None
    for row_index, row in enumerate(rows):
        if not isinstance(row, list):
            raise ValueError(f"{label}[{row_index}] must be a list.")
        numbers = [_number(item, f"{label}[{row_index}]") for item in row]
        if width is None:
            width = len(numbers)
        elif len(numbers) != width:
            raise ValueError(f"{label} rows must have a consistent width.")
        result.append(numbers)
    return result


def _int_value(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{label} must be an integer.")


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite.")
    return result


def _int_field(payload: Dict[str, object], field_name: str) -> int:
    if field_name not in payload:
        raise ValueError(f"Missing field {field_name}.")
    return _int_value(payload[field_name], field_name)


def _float_field(payload: Dict[str, object], field_name: str) -> float:
    if field_name not in payload:
        raise ValueError(f"Missing field {field_name}.")
    return _number(payload[field_name], field_name)

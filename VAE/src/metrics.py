from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

MATH_GRAPH_TYPE = "vae_math_learning_graph"
MATH_GENERATED_GRAPH_TYPE = "vae_math_generated_graph"


def load_json_graphs(root: str | Path, graph_type: str = "") -> List[Dict[str, object]]:
    root_path = Path(root)
    if root_path.is_file():
        candidates = [root_path]
    else:
        graph_root = root_path / "graphs" if (root_path / "graphs").is_dir() else root_path
        candidates = sorted(graph_root.rglob("*.json"))

    graphs: List[Dict[str, object]] = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if graph_type and payload.get("graph_type") != graph_type:
            continue
        graphs.append(payload)
    return graphs


def math_graph_structure_stats(graphs: Sequence[Dict[str, object]]) -> Dict[str, object]:
    pool_sizes: Dict[str, List[float]] = defaultdict(list)
    edge_counts: Dict[str, List[float]] = defaultdict(list)
    source_degrees: Dict[str, List[float]] = defaultdict(list)
    target_degrees: Dict[str, List[float]] = defaultdict(list)
    relation_counts: List[float] = []
    sample_count = 0

    for graph in graphs:
        if graph.get("graph_type") != MATH_GRAPH_TYPE:
            continue
        sample_count += 1
        rules = _object(graph.get("rules"), "rules")
        body = _object(graph.get("graph"), "graph")
        supervision = _object(graph.get("supervision"), "supervision")
        pool_size_by_id = {
            str(_int(pool.get("pool_id"), "pool_id")): _int(pool.get("size"), "size")
            for pool in _objects(rules.get("pools"), "rules.pools")
        }
        for pool_id, size in pool_size_by_id.items():
            pool_sizes[pool_id].append(float(size))

        per_edge_count: Counter[str] = Counter()
        per_source_degree: Dict[str, Counter[int]] = defaultdict(Counter)
        per_target_degree: Dict[str, Counter[int]] = defaultdict(Counter)
        for edge in _objects(body.get("edges"), "graph.edges"):
            edge_type_id = str(_int(edge.get("edge_type_id"), "edge_type_id"))
            per_edge_count[edge_type_id] += 1
            per_source_degree[edge_type_id][_int(edge.get("source_index"), "source_index")] += 1
            per_target_degree[edge_type_id][_int(edge.get("target_index"), "target_index")] += 1
        for edge_type_id, count in per_edge_count.items():
            edge_counts[edge_type_id].append(float(count))
        for edge_type_id, degree_counter in per_source_degree.items():
            source_degrees[edge_type_id].extend(float(value) for value in degree_counter.values())
        for edge_type_id, degree_counter in per_target_degree.items():
            target_degrees[edge_type_id].extend(float(value) for value in degree_counter.values())

        relation_counts.append(float(len(_objects(supervision.get("target_relations", []), "target_relations"))))

    return {
        "sample_count": sample_count,
        "pool_sizes": _summary_map(pool_sizes),
        "edge_counts": _summary_map(edge_counts),
        "source_degrees": _summary_map(source_degrees),
        "target_degrees": _summary_map(target_degrees),
        "target_relation_count": _summary(relation_counts),
    }


def task_output_stats(graphs: Sequence[Dict[str, object]]) -> Dict[str, object]:
    counts: Dict[str, List[float]] = defaultdict(list)
    anchor_hist: Dict[str, Counter[int]] = defaultdict(Counter)
    params: Dict[str, Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))
    sample_count = 0

    for graph in graphs:
        outputs = _task_outputs(graph)
        if not outputs:
            continue
        sample_count += 1
        for task_id, output in outputs.items():
            count = _int(output.get("count", 0), "count")
            counts[task_id].append(float(count))
            for anchor_index in _list(output.get("anchor_index", []), "anchor_index")[:count]:
                anchor_hist[task_id][_int(anchor_index, "anchor_index")] += 1
            for row in _list(output.get("params", []), "params")[:count]:
                for dim, value in enumerate(_list(row, "params[]")):
                    params[task_id][dim].append(_float(value, "param"))

    return {
        "sample_count": sample_count,
        "task_counts": _summary_map(counts),
        "anchor_histograms": {
            task_id: {str(index): count for index, count in sorted(counter.items())}
            for task_id, counter in sorted(anchor_hist.items())
        },
        "params": {
            task_id: {str(dim): _summary(values) for dim, values in sorted(dim_map.items())}
            for task_id, dim_map in sorted(params.items())
        },
    }


def compare_graph_sets(
    reference_graphs: Sequence[Dict[str, object]],
    generated_graphs: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    reference_structure = math_graph_structure_stats(reference_graphs)
    generated_structure = math_graph_structure_stats(generated_graphs)
    reference_targets = task_output_stats(reference_graphs)
    generated_outputs = task_output_stats(generated_graphs)
    if int(generated_structure.get("sample_count", 0)) > 0:
        structure_similarity: Dict[str, object] = {
            "pool_size_mean_delta": _summary_delta(reference_structure["pool_sizes"], generated_structure["pool_sizes"]),
            "edge_count_mean_delta": _summary_delta(reference_structure["edge_counts"], generated_structure["edge_counts"]),
            "source_degree_mean_delta": _summary_delta(reference_structure["source_degrees"], generated_structure["source_degrees"]),
            "target_degree_mean_delta": _summary_delta(reference_structure["target_degrees"], generated_structure["target_degrees"]),
        }
    else:
        structure_similarity = {
            "status": "not_applicable",
            "reason": "vae_math_generated_graph contains task outputs only; compare decoded configs with solver metrics for downstream structure and difficulty.",
        }

    return {
        "reference_structure": reference_structure,
        "generated_structure": generated_structure,
        "reference_targets": reference_targets,
        "generated_outputs": generated_outputs,
        "structure_similarity": structure_similarity,
        "generation_similarity": {
            "task_count_mean_delta": _summary_delta(reference_targets["task_counts"], generated_outputs["task_counts"]),
            "anchor_histogram_cosine": _counter_cosine_map(
                reference_targets["anchor_histograms"],
                generated_outputs["anchor_histograms"],
            ),
            "param_mean_delta": _nested_summary_delta(reference_targets["params"], generated_outputs["params"]),
        },
    }


def load_solver_table(path: str | Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))
    return rows


def solver_difficulty_stats(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    numeric_columns = [
        "duration_sec",
        "objective",
        "solving_time",
        "num_nodes",
        "mip_gap",
        "obj",
        "obj_bound",
        "t_first_feas",
        "gap_first_feas",
        "work",
    ]
    status_counts = Counter(str(row.get("status_name", row.get("status", ""))) for row in rows)
    return {
        "case_count": len(rows),
        "status_distribution": dict(sorted(status_counts.items())),
        "numeric": {
            column: _summary(_column_values(rows, column))
            for column in numeric_columns
            if _column_values(rows, column)
        },
    }


def compare_solver_difficulty(
    reference_rows: Sequence[Dict[str, object]],
    generated_rows: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    reference = solver_difficulty_stats(reference_rows)
    generated = solver_difficulty_stats(generated_rows)
    return {
        "reference": reference,
        "generated": generated,
        "difficulty_similarity": {
            "numeric_mean_delta": _summary_delta(reference["numeric"], generated["numeric"]),
            "status_cosine": _counter_cosine(reference["status_distribution"], generated["status_distribution"]),
        },
    }


def disturbance_kind_distribution(disturbance_graph: Dict[str, object]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for disturbance in disturbance_graph.get("disturbances", []):
        kind = str(disturbance.get("kind", ""))
        if kind == "speed_limit" and float(disturbance.get("speed_limit", 0)) == 0:
            counts["interruption"] += 1
        else:
            counts[kind] += 1
    return dict(sorted(counts.items()))


def disturbance_graph_stats(disturbance_graph: Dict[str, object]) -> Dict[str, object]:
    disturbances = disturbance_graph.get("disturbances", [])
    role_edges = disturbance_graph.get("role_edges", [])
    return {
        "disturbance_count": len(disturbances),
        "role_edge_count": len(role_edges),
        "kind_distribution": disturbance_kind_distribution(disturbance_graph),
    }


def _task_outputs(graph: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    if graph.get("graph_type") == MATH_GRAPH_TYPE:
        supervision = _object(graph.get("supervision"), "supervision")
        return {
            str(task_id): _object(output, "supervision.targets[]")
            for task_id, output in _object(supervision.get("targets"), "supervision.targets").items()
        }
    if graph.get("graph_type") == MATH_GENERATED_GRAPH_TYPE:
        return {
            str(task_id): _object(output, "task_outputs[]")
            for task_id, output in _object(graph.get("task_outputs"), "task_outputs").items()
        }
    return {}


def _summary_map(values_by_key: Dict[str, Sequence[float]]) -> Dict[str, Dict[str, float]]:
    return {str(key): _summary(values) for key, values in sorted(values_by_key.items())}


def _summary(values: Sequence[float]) -> Dict[str, float]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"count": 0.0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    mean = sum(clean) / len(clean)
    variance = sum((value - mean) ** 2 for value in clean) / len(clean)
    return {
        "count": float(len(clean)),
        "mean": mean,
        "std": math.sqrt(variance),
        "min": min(clean),
        "max": max(clean),
    }


def _summary_delta(
    reference: Dict[str, Dict[str, float]],
    generated: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, float]]:
    result: Dict[str, Dict[str, float]] = {}
    for key in sorted(set(reference) | set(generated)):
        ref = reference.get(key, {})
        gen = generated.get(key, {})
        ref_mean = float(ref.get("mean", 0.0))
        gen_mean = float(gen.get("mean", 0.0))
        denom = abs(ref_mean) if abs(ref_mean) > 1e-9 else 1.0
        result[key] = {
            "reference_mean": ref_mean,
            "generated_mean": gen_mean,
            "absolute_delta": abs(gen_mean - ref_mean),
            "relative_delta": abs(gen_mean - ref_mean) / denom,
        }
    return result


def _nested_summary_delta(
    reference: Dict[str, Dict[str, Dict[str, float]]],
    generated: Dict[str, Dict[str, Dict[str, float]]],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    result: Dict[str, Dict[str, Dict[str, float]]] = {}
    for task_id in sorted(set(reference) | set(generated)):
        result[task_id] = _summary_delta(reference.get(task_id, {}), generated.get(task_id, {}))
    return result


def _counter_cosine_map(
    reference: Dict[str, Dict[str, int]],
    generated: Dict[str, Dict[str, int]],
) -> Dict[str, float]:
    return {
        task_id: _counter_cosine(reference.get(task_id, {}), generated.get(task_id, {}))
        for task_id in sorted(set(reference) | set(generated))
    }


def _counter_cosine(reference: Dict[str, int], generated: Dict[str, int]) -> float:
    keys = set(reference) | set(generated)
    if not keys:
        return 1.0
    dot = sum(float(reference.get(key, 0)) * float(generated.get(key, 0)) for key in keys)
    ref_norm = math.sqrt(sum(float(reference.get(key, 0)) ** 2 for key in keys))
    gen_norm = math.sqrt(sum(float(generated.get(key, 0)) ** 2 for key in keys))
    if ref_norm == 0.0 and gen_norm == 0.0:
        return 1.0
    if ref_norm == 0.0 or gen_norm == 0.0:
        return 0.0
    return dot / (ref_norm * gen_norm)


def _column_values(rows: Sequence[Dict[str, object]], column: str) -> List[float]:
    values: List[float] = []
    for row in rows:
        raw = row.get(column)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def _objects(value: object, label: str) -> List[Dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return [_object(item, f"{label}[]") for item in value]


def _object(value: object, label: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _list(value: object, label: str) -> List[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return value


def _int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise ValueError(f"{label} must be an integer.")


def _float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    return result

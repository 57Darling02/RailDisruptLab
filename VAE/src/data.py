from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import torch
from torch.utils.data import Dataset

MATH_CONTEXT_GRAPH_TYPE = "vae_math_context_graph"
MATH_LEARNING_SAMPLE_TYPE = "vae_math_learning_sample"
MATH_GENERATED_GRAPH_TYPE = "vae_math_generated_graph"
MATH_CONTEXT_FILENAME = "math_context.json"


@dataclass(frozen=True)
class PoolRule:
    pool_id: int
    size: int
    feature_dim: int


@dataclass(frozen=True)
class EdgeTypeRule:
    edge_type_id: int
    source_pool_id: int
    target_pool_id: int
    feature_dim: int


@dataclass(frozen=True)
class TaskRule:
    task_id: int
    target_pool_id: int
    max_slots: int
    count_bounds: Tuple[int, int]
    param_dim: int
    param_bounds: Tuple[Tuple[float, float], ...]
    param_constraints: Tuple[Dict[str, object], ...]


@dataclass
class EdgeBatch:
    edge_type_id: int
    source_pool_id: int
    target_pool_id: int
    edge_index: torch.Tensor
    edge_attr: torch.Tensor
    directed: torch.Tensor


@dataclass
class TargetData:
    count: int
    anchor_index: torch.Tensor
    params: torch.Tensor


@dataclass
class MathGraphSample:
    graph_path: str
    decode_handle: Dict[str, object]
    pool_rules: Dict[int, PoolRule]
    task_rules: Dict[int, TaskRule]
    edge_type_rules: Dict[int, EdgeTypeRule]
    pool_x: Dict[int, torch.Tensor]
    edges: Dict[int, EdgeBatch]
    targets: Dict[int, TargetData]
    target_relation_index: torch.Tensor
    target_relation_x: torch.Tensor

    def to(self, device: Union[torch.device, str]) -> "MathGraphSample":
        for pool_id, value in list(self.pool_x.items()):
            self.pool_x[pool_id] = value.to(device)
        for edge_type_id, edge in list(self.edges.items()):
            self.edges[edge_type_id] = EdgeBatch(
                edge_type_id=edge.edge_type_id,
                source_pool_id=edge.source_pool_id,
                target_pool_id=edge.target_pool_id,
                edge_index=edge.edge_index.to(device),
                edge_attr=edge.edge_attr.to(device),
                directed=edge.directed.to(device),
            )
        for task_id, target in list(self.targets.items()):
            self.targets[task_id] = TargetData(
                count=target.count,
                anchor_index=target.anchor_index.to(device),
                params=target.params.to(device),
            )
        self.target_relation_index = self.target_relation_index.to(device)
        self.target_relation_x = self.target_relation_x.to(device)
        return self


class RailDisturbanceDataset(Dataset):
    def __init__(self, graph_root: Union[str, Path], num_instances: Optional[int] = None):
        self.graph_root = Path(graph_root)
        self.files = list_learning_sample_files(self.graph_root)
        if num_instances is not None:
            self.files = self.files[:num_instances]
        if not self.files:
            raise FileNotFoundError(f"No VAE learning sample JSON files found: {self.graph_root}")

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, index: int) -> MathGraphSample:
        path = self.files[index]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("graph_type") != MATH_LEARNING_SAMPLE_TYPE:
            raise ValueError(f"Unsupported graph_type in {path}: {payload.get('graph_type')}")
        context_payload = load_context_for_sample(path, payload)
        return math_learning_sample_to_sample(context_payload, payload, graph_path=str(path))


class RailDisturbanceContextDataset(Dataset):
    def __init__(self, graph_root: Union[str, Path], num_instances: Optional[int] = None):
        self.graph_root = Path(graph_root)
        self.files = list_context_graph_files(self.graph_root)
        if num_instances is not None:
            self.files = self.files[:num_instances]
        if not self.files:
            raise FileNotFoundError(f"No {MATH_CONTEXT_GRAPH_TYPE} JSON files found: {self.graph_root}")

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, index: int) -> MathGraphSample:
        payload = load_context_graph(self.files[index])
        return math_context_graph_to_sample(payload, graph_path=str(self.files[index]))


def list_learning_sample_files(root: Union[str, Path]) -> List[Path]:
    root_path = Path(root)
    if root_path.is_file():
        candidates = [root_path]
    else:
        graph_sample_root = root_path / "samples"
        if not graph_sample_root.is_dir():
            return []
        candidates = sorted(graph_sample_root.rglob("*.json"))
    return [path for path in candidates if path.is_file() and _is_math_learning_sample(path)]


def list_context_graph_files(root: Union[str, Path]) -> List[Path]:
    root_path = Path(root)
    if root_path.is_file():
        candidates = [root_path]
    elif (root_path / MATH_CONTEXT_FILENAME).is_file():
        candidates = [root_path / MATH_CONTEXT_FILENAME]
    elif (root_path / "contexts").is_dir():
        candidates = sorted((root_path / "contexts").rglob("*.json"))
    else:
        candidates = []
    return [path for path in candidates if path.is_file() and _is_math_context_graph(path)]


def load_context_graph(path: Union[str, Path]) -> Dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("graph_type") != MATH_CONTEXT_GRAPH_TYPE:
        raise ValueError(f"Unsupported graph_type in {path}: {payload.get('graph_type')}")
    return payload


def load_learning_sample(path: Union[str, Path]) -> Dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("graph_type") != MATH_LEARNING_SAMPLE_TYPE:
        raise ValueError(f"Unsupported graph_type in {path}: {payload.get('graph_type')}")
    return payload


def load_context_for_sample(sample_path: Union[str, Path], sample_payload: Dict[str, object]) -> Dict[str, object]:
    path = Path(sample_path)
    context_ref = Path(str(sample_payload.get("context_ref", "") or ""))
    if not context_ref:
        raise ValueError(f"Learning sample is missing context_ref: {path}")
    if context_ref.is_absolute():
        context_path = context_ref
    else:
        candidates = [
            path.parent / context_ref,
            path.parent.parent / context_ref,
        ]
        context_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    return load_context_graph(context_path)


def math_learning_sample_to_sample(
    context_payload: Dict[str, object],
    sample_payload: Dict[str, object],
    graph_path: str = "",
) -> MathGraphSample:
    if sample_payload.get("graph_type") != MATH_LEARNING_SAMPLE_TYPE:
        raise ValueError(f"Unsupported graph_type: {sample_payload.get('graph_type')}")
    sample = math_context_graph_to_sample(context_payload, graph_path=graph_path)
    supervision = _object(sample_payload.get("supervision"), "supervision")
    sample.targets = _target_tensors(supervision.get("targets"), sample.task_rules, sample.pool_rules)
    sample.target_relation_index, sample.target_relation_x = _relation_tensors(
        supervision.get("target_relations", []),
        int(_object(context_payload.get("rules"), "rules").get("target_relation_feature_dim", 0) or 0),
    )
    return sample


def math_context_graph_to_sample(payload: Dict[str, object], graph_path: str = "") -> MathGraphSample:
    if payload.get("graph_type") != MATH_CONTEXT_GRAPH_TYPE:
        raise ValueError(f"Unsupported graph_type: {payload.get('graph_type')}")

    rules = _object(payload.get("rules"), "rules")
    body = _object(payload.get("graph"), "graph")
    decode_handle = _object(payload.get("decode_handle"), "decode_handle")

    pool_rules = _pool_rules(rules.get("pools"))
    task_rules = _task_rules(rules.get("tasks"))
    edge_type_rules = _edge_type_rules(rules.get("edge_types"))
    pool_x = _pool_tensors(body.get("pool_x"), pool_rules)
    edges = _edge_tensors(body.get("edges"), edge_type_rules)
    relation_feature_dim = int(rules.get("target_relation_feature_dim", 0) or 0)

    return MathGraphSample(
        graph_path=graph_path,
        decode_handle=dict(decode_handle),
        pool_rules=pool_rules,
        task_rules=task_rules,
        edge_type_rules=edge_type_rules,
        pool_x=pool_x,
        edges=edges,
        targets=_empty_targets(task_rules),
        target_relation_index=torch.empty((0, 4), dtype=torch.long),
        target_relation_x=torch.empty((0, relation_feature_dim), dtype=torch.float32),
    )


def target_copy_sample(sample: MathGraphSample) -> Dict[str, object]:
    task_outputs: Dict[str, object] = {}
    for task_id, rule in sorted(sample.task_rules.items()):
        target = sample.targets[task_id]
        task_outputs[str(task_id)] = {
            "count": int(target.count),
            "anchor_index": [int(value) for value in target.anchor_index.tolist()],
            "params": target.params.cpu().tolist(),
        }
    return {
        "schema_version": 1,
        "graph_type": MATH_GENERATED_GRAPH_TYPE,
        "decode_handle": dict(sample.decode_handle),
        "task_outputs": task_outputs,
    }


def _is_math_context_graph(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("graph_type") == MATH_CONTEXT_GRAPH_TYPE


def _is_math_learning_sample(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("graph_type") == MATH_LEARNING_SAMPLE_TYPE


def _load_library_context(root: Path) -> Optional[Dict[str, object]]:
    if root.is_file():
        try:
            payload = json.loads(root.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("graph_type") == MATH_CONTEXT_GRAPH_TYPE:
            return payload
        return None
    context_path = root / MATH_CONTEXT_FILENAME
    if context_path.is_file():
        return load_context_graph(context_path)
    return None


def _empty_targets(task_rules: Dict[int, TaskRule]) -> Dict[int, TargetData]:
    result: Dict[int, TargetData] = {}
    for task_id, rule in task_rules.items():
        result[task_id] = TargetData(
            count=0,
            anchor_index=torch.empty((0,), dtype=torch.long),
            params=torch.empty((0, rule.param_dim), dtype=torch.float32),
        )
    return result


def _pool_rules(value: object) -> Dict[int, PoolRule]:
    result: Dict[int, PoolRule] = {}
    for item in _list(value, "rules.pools"):
        entry = _object(item, "rules.pools[]")
        rule = PoolRule(
            pool_id=_int(entry.get("pool_id"), "pool_id"),
            size=_int(entry.get("size"), "size"),
            feature_dim=_int(entry.get("feature_dim"), "feature_dim"),
        )
        result[rule.pool_id] = rule
    return result


def _task_rules(value: object) -> Dict[int, TaskRule]:
    result: Dict[int, TaskRule] = {}
    for item in _list(value, "rules.tasks"):
        entry = _object(item, "rules.tasks[]")
        task_id = _int(entry.get("task_id"), "task_id")
        param_dim = _int(entry.get("param_dim"), "param_dim")
        max_slots = _int(entry.get("max_slots"), "max_slots")
        count_bounds_raw = _list(entry.get("count_bounds", [0, max_slots]), "count_bounds")
        if len(count_bounds_raw) != 2:
            raise ValueError(f"Task {task_id} count_bounds must contain [min, max].")
        count_bounds = (
            _int(count_bounds_raw[0], "count_bounds.min"),
            _int(count_bounds_raw[1], "count_bounds.max"),
        )
        if count_bounds[0] < 0 or count_bounds[1] < count_bounds[0] or count_bounds[1] > max_slots:
            raise ValueError(f"Task {task_id} count_bounds must satisfy 0 <= min <= max <= max_slots.")
        bounds = tuple(
            (_float(row[0], "param_bounds.min"), _float(row[1], "param_bounds.max"))
            for row in _list(entry.get("param_bounds", []), "param_bounds")
        )
        if bounds and len(bounds) != param_dim:
            raise ValueError(f"Task {task_id} param_bounds length must equal param_dim.")
        result[task_id] = TaskRule(
            task_id=task_id,
            target_pool_id=_int(entry.get("target_pool_id"), "target_pool_id"),
            max_slots=max_slots,
            count_bounds=count_bounds,
            param_dim=param_dim,
            param_bounds=bounds or tuple((0.0, 1.0) for _ in range(param_dim)),
            param_constraints=tuple(
                dict(_object(constraint, "param_constraints[]"))
                for constraint in _list(entry.get("param_constraints", []), "param_constraints")
            ),
        )
    return result


def _edge_type_rules(value: object) -> Dict[int, EdgeTypeRule]:
    result: Dict[int, EdgeTypeRule] = {}
    for item in _list(value, "rules.edge_types"):
        entry = _object(item, "rules.edge_types[]")
        rule = EdgeTypeRule(
            edge_type_id=_int(entry.get("edge_type_id"), "edge_type_id"),
            source_pool_id=_int(entry.get("source_pool_id"), "source_pool_id"),
            target_pool_id=_int(entry.get("target_pool_id"), "target_pool_id"),
            feature_dim=_int(entry.get("feature_dim"), "feature_dim"),
        )
        result[rule.edge_type_id] = rule
    return result


def _pool_tensors(value: object, rules: Dict[int, PoolRule]) -> Dict[int, torch.Tensor]:
    pool_x_raw = _object(value, "graph.pool_x")
    result: Dict[int, torch.Tensor] = {}
    for pool_id, rule in rules.items():
        rows = _matrix(pool_x_raw.get(str(pool_id)), f"graph.pool_x.{pool_id}")
        if len(rows) != rule.size:
            raise ValueError(f"Pool {pool_id} row count must equal rule.size.")
        if rows and len(rows[0]) != rule.feature_dim:
            raise ValueError(f"Pool {pool_id} feature width must equal rule.feature_dim.")
        result[pool_id] = torch.tensor(rows, dtype=torch.float32)
    return result


def _edge_tensors(value: object, rules: Dict[int, EdgeTypeRule]) -> Dict[int, EdgeBatch]:
    indices: Dict[int, List[List[int]]] = {edge_type_id: [] for edge_type_id in rules}
    attrs: Dict[int, List[List[float]]] = {edge_type_id: [] for edge_type_id in rules}
    directed_flags: Dict[int, List[bool]] = {edge_type_id: [] for edge_type_id in rules}
    for item in _list(value, "graph.edges"):
        edge = _object(item, "graph.edges[]")
        edge_type_id = _int(edge.get("edge_type_id"), "edge_type_id")
        rule = rules[edge_type_id]
        if _int(edge.get("source_pool_id"), "source_pool_id") != rule.source_pool_id:
            raise ValueError(f"Edge {edge_type_id} source_pool_id does not match rule.")
        if _int(edge.get("target_pool_id"), "target_pool_id") != rule.target_pool_id:
            raise ValueError(f"Edge {edge_type_id} target_pool_id does not match rule.")
        feature = _vector(edge.get("x"), "edge.x")
        if len(feature) != rule.feature_dim:
            raise ValueError(f"Edge {edge_type_id} feature width must equal rule.feature_dim.")
        indices[edge_type_id].append([
            _int(edge.get("source_index"), "source_index"),
            _int(edge.get("target_index"), "target_index"),
        ])
        attrs[edge_type_id].append(feature)
        directed_flags[edge_type_id].append(bool(edge.get("directed", True)))

    result: Dict[int, EdgeBatch] = {}
    for edge_type_id, rule in rules.items():
        edge_index = torch.tensor(indices[edge_type_id], dtype=torch.long).t().contiguous()
        if edge_index.numel() == 0:
            edge_index = torch.empty((2, 0), dtype=torch.long)
        edge_attr = torch.tensor(attrs[edge_type_id], dtype=torch.float32)
        if edge_attr.numel() == 0:
            edge_attr = torch.empty((0, rule.feature_dim), dtype=torch.float32)
        directed = torch.tensor(directed_flags[edge_type_id], dtype=torch.bool)
        result[edge_type_id] = EdgeBatch(
            edge_type_id=edge_type_id,
            source_pool_id=rule.source_pool_id,
            target_pool_id=rule.target_pool_id,
            edge_index=edge_index,
            edge_attr=edge_attr,
            directed=directed,
        )
    return result


def _target_tensors(
    value: object,
    task_rules: Dict[int, TaskRule],
    pool_rules: Dict[int, PoolRule],
) -> Dict[int, TargetData]:
    targets_raw = _object(value, "supervision.targets")
    result: Dict[int, TargetData] = {}
    for task_id, rule in task_rules.items():
        target = _object(targets_raw.get(str(task_id)), f"supervision.targets.{task_id}")
        count = _int(target.get("count"), "count")
        if count < 0 or count > rule.max_slots:
            raise ValueError(f"Task {task_id} count must be between 0 and max_slots.")
        if count < rule.count_bounds[0] or count > rule.count_bounds[1]:
            raise ValueError(f"Task {task_id} count must be within count_bounds.")
        anchor_index = [_int(value, "anchor_index") for value in _list(target.get("anchor_index"), "anchor_index")]
        params = _matrix(target.get("params"), "params")
        if len(anchor_index) != count or len(params) != count:
            raise ValueError(f"Task {task_id} target lengths must equal count.")
        if any(index < 0 or index >= pool_rules[rule.target_pool_id].size for index in anchor_index):
            raise ValueError(f"Task {task_id} anchor_index is out of range.")
        if any(len(row) != rule.param_dim for row in params):
            raise ValueError(f"Task {task_id} params width must equal param_dim.")
        result[task_id] = TargetData(
            count=count,
            anchor_index=torch.tensor(anchor_index, dtype=torch.long),
            params=torch.tensor(params, dtype=torch.float32),
        )
    return result


def _relation_tensors(value: object, feature_dim: int) -> Tuple[torch.Tensor, torch.Tensor]:
    index_rows: List[List[int]] = []
    feature_rows: List[List[float]] = []
    for item in _list(value, "supervision.target_relations"):
        relation = _object(item, "supervision.target_relations[]")
        feature = _vector(relation.get("x"), "relation.x")
        if feature_dim and len(feature) != feature_dim:
            raise ValueError("Relation feature width must equal rules.target_relation_feature_dim.")
        index_rows.append([
            _int(relation.get("left_task_id"), "left_task_id"),
            _int(relation.get("left_slot"), "left_slot"),
            _int(relation.get("right_task_id"), "right_task_id"),
            _int(relation.get("right_slot"), "right_slot"),
        ])
        feature_rows.append(feature)
    relation_index = torch.tensor(index_rows, dtype=torch.long)
    if relation_index.numel() == 0:
        relation_index = torch.empty((0, 4), dtype=torch.long)
    relation_x = torch.tensor(feature_rows, dtype=torch.float32)
    if relation_x.numel() == 0:
        relation_x = torch.empty((0, feature_dim), dtype=torch.float32)
    return relation_index, relation_x


def _object(value: object, label: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _list(value: object, label: str) -> List[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return value


def _vector(value: object, label: str) -> List[float]:
    return [_float(item, label) for item in _list(value, label)]


def _matrix(value: object, label: str) -> List[List[float]]:
    rows = _list(value, label)
    result: List[List[float]] = []
    width: Optional[int] = None
    for row in rows:
        vector = _vector(row, label)
        if width is None:
            width = len(vector)
        elif len(vector) != width:
            raise ValueError(f"{label} rows must have a consistent width.")
        result.append(vector)
    return result


def _int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{label} must be an integer.")


def _float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    return float(value)

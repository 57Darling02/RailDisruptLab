from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from src.data import MathGraphSample, TaskRule


ARCHITECTURE_VERSION = 2
DISTURBANCE_POOL_ID = -1
RELATION_EDGE_KEY = "target_relation"


@dataclass(frozen=True)
class _HiddenEdge:
    edge_key: str
    source_pool_id: int
    target_pool_id: int
    edge_index: torch.Tensor
    edge_h: torch.Tensor
    directed: torch.Tensor


@dataclass(frozen=True)
class _RelationPrediction:
    pred: torch.Tensor
    target: torch.Tensor


@dataclass(frozen=True)
class _RelationRows:
    edge: _HiddenEdge
    source_index: torch.Tensor
    target_index: torch.Tensor
    target_x: torch.Tensor


@dataclass(frozen=True)
class _JointEncoding:
    posterior_input: torch.Tensor
    relation_pred: _RelationPrediction | None


class RailDisturbanceVAE(nn.Module):
    """Conditional graph VAE over mathematical rail-disturbance samples.

    The prior sees only the fixed context graph C. The posterior sees the
    joint graph C + G_D + R. The decoder uses z as a global condition over
    context anchor embeddings instead of pretending z is a graph node.
    """

    def __init__(
        self,
        pool_feature_dims: Dict[int, int],
        edge_feature_dims: Dict[int, int],
        task_defs: Dict[int, Dict[str, object]],
        relation_feature_dim: int,
        hidden_dim: int = 64,
        latent_dim: int = 32,
        message_passing_steps: int = 2,
    ):
        super().__init__()
        self.pool_feature_dims = dict(sorted((int(k), int(v)) for k, v in pool_feature_dims.items()))
        self.edge_feature_dims = dict(sorted((int(k), int(v)) for k, v in edge_feature_dims.items()))
        self.task_defs = {
            int(task_id): {
                "target_pool_id": int(defn["target_pool_id"]),
                "max_slots": int(defn["max_slots"]),
                "count_bounds": tuple(int(item) for item in defn.get("count_bounds", (0, int(defn["max_slots"])))),
                "param_dim": int(defn["param_dim"]),
                "param_bounds": tuple(tuple(float(item) for item in row) for row in defn.get("param_bounds", [])),
                "param_constraints": tuple(dict(item) for item in defn.get("param_constraints", [])),
            }
            for task_id, defn in sorted(task_defs.items())
        }
        self.relation_feature_dim = int(relation_feature_dim)
        self.hidden_dim = int(hidden_dim)
        self.latent_dim = int(latent_dim)
        self.message_passing_steps = int(message_passing_steps)

        self.context_edge_keys = [_context_edge_key(edge_type_id) for edge_type_id in self.edge_feature_dims]
        self.anchor_edge_keys = [_anchor_edge_key(task_id) for task_id in self.task_defs]

        self.pool_encoders = nn.ModuleDict(
            {
                _module_key(pool_id): _mlp(feature_dim, hidden_dim)
                for pool_id, feature_dim in self.pool_feature_dims.items()
            }
        )
        self.edge_encoders = nn.ModuleDict(
            {
                _module_key(edge_type_id): _mlp(feature_dim, hidden_dim)
                for edge_type_id, feature_dim in self.edge_feature_dims.items()
            }
        )
        self.context_gnn = _TypedMessagePassing(
            pool_ids=self.pool_feature_dims.keys(),
            edge_keys=self.context_edge_keys,
            hidden_dim=hidden_dim,
            message_passing_steps=message_passing_steps,
        )
        self.joint_gnn = _TypedMessagePassing(
            pool_ids=[*self.pool_feature_dims.keys(), DISTURBANCE_POOL_ID],
            edge_keys=[*self.context_edge_keys, *self.anchor_edge_keys, RELATION_EDGE_KEY],
            hidden_dim=hidden_dim,
            message_passing_steps=message_passing_steps,
        )
        self.disturbance_node_encoders = nn.ModuleDict(
            {
                _module_key(task_id): _mlp(hidden_dim + _param_input_dim(int(defn["param_dim"])), hidden_dim)
                for task_id, defn in self.task_defs.items()
            }
        )
        self.anchor_edge_encoders = nn.ModuleDict(
            {
                _module_key(task_id): _mlp(_param_input_dim(int(defn["param_dim"])), hidden_dim)
                for task_id, defn in self.task_defs.items()
            }
        )
        self.relation_encoder = _mlp(_param_input_dim(self.relation_feature_dim), hidden_dim)
        self.relation_predictor = (
            nn.Sequential(
                _mlp(hidden_dim * 3, hidden_dim),
                nn.Linear(hidden_dim, self.relation_feature_dim),
            )
            if self.relation_feature_dim > 0
            else None
        )

        context_dim = hidden_dim * (len(self.pool_feature_dims) + len(self.edge_feature_dims))
        joint_dim = context_dim + hidden_dim * 3
        self.context_dim = context_dim
        self.joint_dim = joint_dim

        self.prior_mu = nn.Linear(context_dim, latent_dim)
        self.prior_logvar = nn.Linear(context_dim, latent_dim)
        self.posterior_mu = nn.Linear(joint_dim, latent_dim)
        self.posterior_logvar = nn.Linear(joint_dim, latent_dim)

        decoder_input_dim = context_dim + latent_dim
        self.decoder_readout = _mlp(decoder_input_dim, hidden_dim)
        self.count_heads = nn.ModuleDict()
        self.slot_query_heads = nn.ModuleDict()
        self.param_heads = nn.ModuleDict()
        for task_id, defn in self.task_defs.items():
            max_slots = int(defn["max_slots"])
            param_dim = int(defn["param_dim"])
            self.count_heads[_module_key(task_id)] = nn.Linear(hidden_dim, max_slots + 1)
            self.slot_query_heads[_module_key(task_id)] = nn.Linear(hidden_dim, max_slots * hidden_dim)
            self.param_heads[_module_key(task_id)] = nn.Sequential(
                _mlp(hidden_dim * 3 + latent_dim, hidden_dim),
                nn.Linear(hidden_dim, param_dim),
            )

    @classmethod
    def from_sample(
        cls,
        sample: MathGraphSample,
        hidden_dim: int = 64,
        latent_dim: int = 32,
        message_passing_steps: int = 2,
    ) -> "RailDisturbanceVAE":
        return cls(
            pool_feature_dims={pool_id: rule.feature_dim for pool_id, rule in sample.pool_rules.items()},
            edge_feature_dims={edge_type_id: rule.feature_dim for edge_type_id, rule in sample.edge_type_rules.items()},
            task_defs={
                task_id: {
                    "target_pool_id": rule.target_pool_id,
                    "max_slots": rule.max_slots,
                    "count_bounds": rule.count_bounds,
                    "param_dim": rule.param_dim,
                    "param_bounds": rule.param_bounds,
                    "param_constraints": rule.param_constraints,
                }
                for task_id, rule in sample.task_rules.items()
            },
            relation_feature_dim=sample.target_relation_x.shape[1],
            hidden_dim=hidden_dim,
            latent_dim=latent_dim,
            message_passing_steps=message_passing_steps,
        )

    def config_dict(self) -> Dict[str, object]:
        return {
            "architecture_version": ARCHITECTURE_VERSION,
            "pool_feature_dims": {str(k): v for k, v in self.pool_feature_dims.items()},
            "edge_feature_dims": {str(k): v for k, v in self.edge_feature_dims.items()},
            "task_defs": {str(k): v for k, v in self.task_defs.items()},
            "relation_feature_dim": self.relation_feature_dim,
            "hidden_dim": self.hidden_dim,
            "latent_dim": self.latent_dim,
            "message_passing_steps": self.message_passing_steps,
        }

    @classmethod
    def from_config(cls, config: Dict[str, object]) -> "RailDisturbanceVAE":
        version = int(config.get("architecture_version", 1))
        if version != ARCHITECTURE_VERSION:
            raise ValueError(
                f"Unsupported VAE architecture_version={version}; "
                f"retrain with architecture_version={ARCHITECTURE_VERSION}."
            )
        return cls(
            pool_feature_dims={int(k): int(v) for k, v in dict(config["pool_feature_dims"]).items()},
            edge_feature_dims={int(k): int(v) for k, v in dict(config["edge_feature_dims"]).items()},
            task_defs={int(k): dict(v) for k, v in dict(config["task_defs"]).items()},
            relation_feature_dim=int(config["relation_feature_dim"]),
            hidden_dim=int(config["hidden_dim"]),
            latent_dim=int(config["latent_dim"]),
            message_passing_steps=int(config.get("message_passing_steps", 2)),
        )

    def forward(self, sample: MathGraphSample) -> Dict[str, object]:
        context_inputs, context_edges = self._context_inputs(sample)
        pool_embeddings = self.context_gnn(context_inputs, context_edges)
        context = self._context_summary(pool_embeddings, context_edges, next(self.parameters()).device)
        joint = self.encode_joint(sample, context_inputs, context_edges)
        prior_mu, prior_logvar = self.prior(context)
        posterior_mu, posterior_logvar = self.posterior(joint.posterior_input)
        z = self.reparameterize(posterior_mu, posterior_logvar)
        decoded = self.decode(z, pool_embeddings, context_edges)
        return {
            "prior_mu": prior_mu,
            "prior_logvar": prior_logvar,
            "posterior_mu": posterior_mu,
            "posterior_logvar": posterior_logvar,
            "tasks": decoded,
            "relation_pred": joint.relation_pred,
        }

    def encode_context(
        self,
        sample: MathGraphSample,
    ) -> Tuple[torch.Tensor, Dict[int, torch.Tensor], List[_HiddenEdge]]:
        context_inputs, context_edges = self._context_inputs(sample)
        device = next(self.parameters()).device
        pool_embeddings = self.context_gnn(context_inputs, context_edges)
        return self._context_summary(pool_embeddings, context_edges, device), pool_embeddings, context_edges

    def _context_inputs(self, sample: MathGraphSample) -> Tuple[Dict[int, torch.Tensor], List[_HiddenEdge]]:
        device = next(self.parameters()).device
        pool_embeddings = {
            pool_id: self.pool_encoders[_module_key(pool_id)](sample.pool_x[pool_id].to(device))
            for pool_id in self.pool_feature_dims
        }
        context_edges = self._context_edges(sample, device)
        return pool_embeddings, context_edges

    def encode_joint(
        self,
        sample: MathGraphSample,
        context_pool_embeddings: Dict[int, torch.Tensor],
        context_edges: List[_HiddenEdge],
    ) -> _JointEncoding:
        device = next(self.parameters()).device
        disturbance_h, anchor_edges, relation_rows = self._disturbance_graph(
            sample,
            context_pool_embeddings,
            device,
        )
        relation_edges = [relation_rows.edge]
        node_h = {pool_id: embeddings for pool_id, embeddings in context_pool_embeddings.items()}
        node_h[DISTURBANCE_POOL_ID] = disturbance_h

        joint_edges = [*context_edges, *anchor_edges, *relation_edges]
        joint_h = self.joint_gnn(node_h, joint_edges)
        context_summary = self._context_summary(joint_h, context_edges, device)
        disturbance_summary = _mean_or_zero(joint_h[DISTURBANCE_POOL_ID], self.hidden_dim, device)
        anchor_summary = _mean_edge_or_zero(anchor_edges, self.hidden_dim, device)
        relation_summary = _mean_edge_or_zero(relation_edges, self.hidden_dim, device)
        posterior_input = torch.cat([context_summary, disturbance_summary, anchor_summary, relation_summary], dim=0)
        relation_pred = self._predict_relations(joint_h[DISTURBANCE_POOL_ID], relation_rows)
        return _JointEncoding(posterior_input=posterior_input, relation_pred=relation_pred)

    def prior(self, context: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        return self.prior_mu(context), self.prior_logvar(context)

    def posterior(self, joint: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        return self.posterior_mu(joint), self.posterior_logvar(joint)

    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        if not self.training:
            return mu
        std = torch.exp(0.5 * logvar)
        return mu + torch.randn_like(std) * std

    def decode(
        self,
        z: torch.Tensor,
        context_pool_embeddings: Dict[int, torch.Tensor],
        context_edges: List[_HiddenEdge],
    ) -> Dict[int, Dict[str, torch.Tensor]]:
        device = z.device
        context = self._context_summary(context_pool_embeddings, context_edges, device)
        hidden = self.decoder_readout(torch.cat([context, z], dim=0))

        result: Dict[int, Dict[str, torch.Tensor]] = {}
        for task_id, defn in self.task_defs.items():
            max_slots = int(defn["max_slots"])
            target_pool_id = int(defn["target_pool_id"])
            slot_queries = self.slot_query_heads[_module_key(task_id)](hidden).view(max_slots, self.hidden_dim)
            target_pool = context_pool_embeddings[target_pool_id]
            anchor_logits = slot_queries @ target_pool.t()
            anchor_weights = torch.softmax(anchor_logits, dim=-1)
            attended_anchor = anchor_weights @ target_pool
            task_context = hidden.unsqueeze(0).expand(max_slots, self.hidden_dim)
            z_rows = z.unsqueeze(0).expand(max_slots, self.latent_dim)
            param_input = torch.cat([task_context, slot_queries, attended_anchor, z_rows], dim=-1)
            params = self.param_heads[_module_key(task_id)](param_input)
            result[task_id] = {
                "count_logits": self.count_heads[_module_key(task_id)](hidden),
                "anchor_logits": anchor_logits,
                "params": params,
            }
        return result

    def decode_from_prior(self, sample: MathGraphSample) -> Dict[int, Dict[str, torch.Tensor]]:
        context, pool_embeddings, context_edges = self.encode_context(sample)
        prior_mu, prior_logvar = self.prior(context)
        std = torch.exp(0.5 * prior_logvar)
        z = prior_mu + torch.randn_like(std) * std
        return self.decode(z, pool_embeddings, context_edges)

    def _context_edges(self, sample: MathGraphSample, device: torch.device) -> List[_HiddenEdge]:
        result: List[_HiddenEdge] = []
        for edge_type_id in self.edge_feature_dims:
            edge = sample.edges[edge_type_id]
            edge_attr = edge.edge_attr.to(device)
            edge_h = self.edge_encoders[_module_key(edge_type_id)](edge_attr)
            result.append(
                _HiddenEdge(
                    edge_key=_context_edge_key(edge_type_id),
                    source_pool_id=edge.source_pool_id,
                    target_pool_id=edge.target_pool_id,
                    edge_index=edge.edge_index.to(device),
                    edge_h=edge_h,
                    directed=edge.directed.to(device),
                )
            )
        return result

    def _disturbance_graph(
        self,
        sample: MathGraphSample,
        context_pool_embeddings: Dict[int, torch.Tensor],
        device: torch.device,
    ) -> Tuple[torch.Tensor, List[_HiddenEdge], _RelationRows]:
        node_rows: List[torch.Tensor] = []
        node_lookup: Dict[Tuple[int, int], int] = {}
        anchor_sources: Dict[int, List[int]] = {task_id: [] for task_id in self.task_defs}
        anchor_targets: Dict[int, List[int]] = {task_id: [] for task_id in self.task_defs}
        anchor_inputs: Dict[int, List[torch.Tensor]] = {task_id: [] for task_id in self.task_defs}

        for task_id, target in sorted(sample.targets.items()):
            defn = self.task_defs[task_id]
            target_pool_id = int(defn["target_pool_id"])
            param_dim = int(defn["param_dim"])
            for slot in range(target.count):
                anchor_index = int(target.anchor_index[slot].item())
                params = target.params[slot].to(device)
                param_input = _param_input(params, param_dim, device)
                anchor_h = context_pool_embeddings[target_pool_id][anchor_index]
                node_input = torch.cat([anchor_h, param_input], dim=0)
                node_lookup[(task_id, slot)] = len(node_rows)
                node_rows.append(self.disturbance_node_encoders[_module_key(task_id)](node_input))
                anchor_sources[task_id].append(node_lookup[(task_id, slot)])
                anchor_targets[task_id].append(anchor_index)
                anchor_inputs[task_id].append(param_input)

        disturbance_h = (
            torch.stack(node_rows, dim=0)
            if node_rows
            else torch.empty((0, self.hidden_dim), dtype=torch.float32, device=device)
        )
        anchor_edges = self._anchor_edges(anchor_sources, anchor_targets, anchor_inputs, device)
        relation_rows = self._relation_edges(sample, node_lookup, device)
        return disturbance_h, anchor_edges, relation_rows

    def _anchor_edges(
        self,
        sources_by_task: Dict[int, List[int]],
        targets_by_task: Dict[int, List[int]],
        inputs_by_task: Dict[int, List[torch.Tensor]],
        device: torch.device,
    ) -> List[_HiddenEdge]:
        result: List[_HiddenEdge] = []
        for task_id, defn in self.task_defs.items():
            sources = sources_by_task[task_id]
            if sources:
                edge_input = torch.stack(inputs_by_task[task_id], dim=0)
                edge_h = self.anchor_edge_encoders[_module_key(task_id)](edge_input)
                edge_index = torch.tensor(
                    [sources, targets_by_task[task_id]],
                    dtype=torch.long,
                    device=device,
                )
                directed = torch.zeros((len(sources),), dtype=torch.bool, device=device)
            else:
                edge_h = torch.empty((0, self.hidden_dim), dtype=torch.float32, device=device)
                edge_index = torch.empty((2, 0), dtype=torch.long, device=device)
                directed = torch.empty((0,), dtype=torch.bool, device=device)
            result.append(
                _HiddenEdge(
                    edge_key=_anchor_edge_key(task_id),
                    source_pool_id=DISTURBANCE_POOL_ID,
                    target_pool_id=int(defn["target_pool_id"]),
                    edge_index=edge_index,
                    edge_h=edge_h,
                    directed=directed,
                )
            )
        return result

    def _relation_edges(
        self,
        sample: MathGraphSample,
        node_lookup: Dict[Tuple[int, int], int],
        device: torch.device,
    ) -> _RelationRows:
        source_rows: List[int] = []
        target_rows: List[int] = []
        relation_inputs: List[torch.Tensor] = []
        relation_index = sample.target_relation_index.to(device)
        relation_x = sample.target_relation_x.to(device)

        for row_id, row in enumerate(relation_index.tolist()):
            left_key = (int(row[0]), int(row[1]))
            right_key = (int(row[2]), int(row[3]))
            if left_key not in node_lookup or right_key not in node_lookup:
                raise ValueError(f"target_relations references missing disturbance slot: {left_key} -> {right_key}")
            source_rows.append(node_lookup[left_key])
            target_rows.append(node_lookup[right_key])
            relation_inputs.append(_param_input(relation_x[row_id], self.relation_feature_dim, device))

        if source_rows:
            relation_input = torch.stack(relation_inputs, dim=0)
            edge_h = self.relation_encoder(relation_input)
            edge_index = torch.tensor([source_rows, target_rows], dtype=torch.long, device=device)
            directed = torch.zeros((len(source_rows),), dtype=torch.bool, device=device)
            target_x = relation_x
        else:
            edge_h = torch.empty((0, self.hidden_dim), dtype=torch.float32, device=device)
            edge_index = torch.empty((2, 0), dtype=torch.long, device=device)
            directed = torch.empty((0,), dtype=torch.bool, device=device)
            target_x = torch.empty((0, self.relation_feature_dim), dtype=torch.float32, device=device)
        return _RelationRows(
            edge=_HiddenEdge(
                edge_key=RELATION_EDGE_KEY,
                source_pool_id=DISTURBANCE_POOL_ID,
                target_pool_id=DISTURBANCE_POOL_ID,
                edge_index=edge_index,
                edge_h=edge_h,
                directed=directed,
            ),
            source_index=edge_index[0],
            target_index=edge_index[1],
            target_x=target_x,
        )

    def _predict_relations(
        self,
        disturbance_h: torch.Tensor,
        relation_rows: _RelationRows,
    ) -> _RelationPrediction | None:
        if self.relation_feature_dim <= 0 or relation_rows.source_index.numel() == 0:
            return None
        if self.relation_predictor is None:
            return None
        source_h = disturbance_h.index_select(0, relation_rows.source_index)
        target_h = disturbance_h.index_select(0, relation_rows.target_index)
        edge_h = relation_rows.edge.edge_h
        pred = self.relation_predictor(torch.cat([source_h, target_h, edge_h], dim=-1))
        return _RelationPrediction(pred=pred, target=relation_rows.target_x)

    def _context_summary(
        self,
        pool_embeddings: Dict[int, torch.Tensor],
        context_edges: List[_HiddenEdge],
        device: torch.device,
    ) -> torch.Tensor:
        pooled: List[torch.Tensor] = []
        for pool_id in self.pool_feature_dims:
            pooled.append(_mean_or_zero(pool_embeddings[pool_id], self.hidden_dim, device))
        for edge in context_edges:
            pooled.append(_mean_or_zero(edge.edge_h, self.hidden_dim, device))
        return torch.cat(pooled, dim=0)


def vae_loss(
    sample: MathGraphSample,
    outputs: Dict[str, object],
    kl_weight: float = 1.0,
    count_weight: float = 1.0,
    anchor_weight: float = 1.0,
    param_weight: float = 1.0,
    relation_weight: float = 0.5,
) -> Tuple[torch.Tensor, Dict[str, float]]:
    device = outputs["prior_mu"].device
    count_loss = torch.tensor(0.0, device=device)
    anchor_loss = torch.tensor(0.0, device=device)
    param_loss = torch.tensor(0.0, device=device)
    relation_loss = torch.tensor(0.0, device=device)

    decoded = outputs["tasks"]
    for task_id, target in sample.targets.items():
        task_output = decoded[task_id]
        count_target = torch.tensor([target.count], dtype=torch.long, device=device)
        count_loss = count_loss + F.cross_entropy(task_output["count_logits"].unsqueeze(0), count_target)
        if target.count <= 0:
            continue
        anchor_loss = anchor_loss + F.cross_entropy(
            task_output["anchor_logits"][: target.count],
            target.anchor_index.to(device),
        )
        param_loss = param_loss + F.smooth_l1_loss(
            task_output["params"][: target.count],
            target.params.to(device),
        )

    kl = _normal_kl(
        outputs["posterior_mu"],
        outputs["posterior_logvar"],
        outputs["prior_mu"],
        outputs["prior_logvar"],
    )
    relation_pred = outputs.get("relation_pred")
    if relation_pred is not None:
        relation_loss = F.smooth_l1_loss(relation_pred.pred, relation_pred.target)
    total = (
        float(count_weight) * count_loss
        + float(anchor_weight) * anchor_loss
        + float(param_weight) * param_loss
        + float(kl_weight) * kl
        + float(relation_weight) * relation_loss
    )
    metrics = {
        "loss": float(total.detach().cpu()),
        "count_loss": float(count_loss.detach().cpu()),
        "anchor_loss": float(anchor_loss.detach().cpu()),
        "param_loss": float(param_loss.detach().cpu()),
        "relation_loss": float(relation_loss.detach().cpu()),
        "kl": float(kl.detach().cpu()),
    }
    return total, metrics


def generated_outputs_to_json(
    sample: MathGraphSample,
    task_outputs: Dict[int, Dict[str, torch.Tensor]],
) -> Dict[str, object]:
    outputs: Dict[str, object] = {}
    for task_id, rule in sorted(sample.task_rules.items()):
        raw = task_outputs[task_id]
        count = int(torch.argmax(raw["count_logits"]).item())
        count_min, count_max = rule.count_bounds
        count = max(int(count_min), min(count, int(count_max)))
        anchor_logits = raw["anchor_logits"]
        params = _repair_params(raw["params"], rule).detach().cpu()
        outputs[str(task_id)] = {
            "count": count,
            "anchor_index": [
                int(torch.argmax(anchor_logits[slot]).item())
                for slot in range(count)
            ],
            "params": params[:count].tolist(),
        }
    return {
        "schema_version": 1,
        "graph_type": "vae_math_generated_graph",
        "decode_handle": dict(sample.decode_handle),
        "task_outputs": outputs,
    }


class _TypedMessagePassing(nn.Module):
    def __init__(
        self,
        *,
        pool_ids: Iterable[int],
        edge_keys: Iterable[str],
        hidden_dim: int,
        message_passing_steps: int,
    ):
        super().__init__()
        self.pool_ids = [int(pool_id) for pool_id in pool_ids]
        self.edge_keys = [str(edge_key) for edge_key in edge_keys]
        self.hidden_dim = int(hidden_dim)
        self.message_passing_steps = int(message_passing_steps)
        self.forward_message_layers = nn.ModuleDict(
            {
                _module_key(edge_key): _mlp(hidden_dim * 3, hidden_dim)
                for edge_key in self.edge_keys
            }
        )
        self.reverse_message_layers = nn.ModuleDict(
            {
                _module_key(edge_key): _mlp(hidden_dim * 3, hidden_dim)
                for edge_key in self.edge_keys
            }
        )
        self.pool_update_layers = nn.ModuleDict(
            {
                _module_key(pool_id): _mlp(hidden_dim * 2, hidden_dim)
                for pool_id in self.pool_ids
            }
        )
        self.pool_norms = nn.ModuleDict(
            {
                _module_key(pool_id): nn.LayerNorm(hidden_dim)
                for pool_id in self.pool_ids
            }
        )

    def forward(self, node_h: Dict[int, torch.Tensor], edges: List[_HiddenEdge]) -> Dict[int, torch.Tensor]:
        if self.message_passing_steps <= 0:
            return node_h

        current = dict(node_h)
        for _step in range(self.message_passing_steps):
            aggregated = {pool_id: torch.zeros_like(current[pool_id]) for pool_id in self.pool_ids}
            degrees = {
                pool_id: torch.zeros(
                    (current[pool_id].shape[0], 1),
                    dtype=current[pool_id].dtype,
                    device=current[pool_id].device,
                )
                for pool_id in self.pool_ids
            }

            for edge in edges:
                if edge.edge_index.numel() == 0:
                    continue
                source_index = edge.edge_index[0]
                target_index = edge.edge_index[1]
                source_h = current[edge.source_pool_id].index_select(0, source_index)
                target_h = current[edge.target_pool_id].index_select(0, target_index)
                forward_message = self.forward_message_layers[_module_key(edge.edge_key)](
                    torch.cat([source_h, target_h, edge.edge_h], dim=-1)
                )
                _index_add_messages(
                    aggregated[edge.target_pool_id],
                    degrees[edge.target_pool_id],
                    target_index,
                    forward_message,
                )

                reverse_mask = ~edge.directed
                if bool(reverse_mask.any()):
                    reverse_rows = torch.where(reverse_mask)[0]
                    reverse_source_index = target_index.index_select(0, reverse_rows)
                    reverse_target_index = source_index.index_select(0, reverse_rows)
                    reverse_source_h = current[edge.target_pool_id].index_select(0, reverse_source_index)
                    reverse_target_h = current[edge.source_pool_id].index_select(0, reverse_target_index)
                    reverse_edge_h = edge.edge_h.index_select(0, reverse_rows)
                    reverse_message = self.reverse_message_layers[_module_key(edge.edge_key)](
                        torch.cat([reverse_source_h, reverse_target_h, reverse_edge_h], dim=-1)
                    )
                    _index_add_messages(
                        aggregated[edge.source_pool_id],
                        degrees[edge.source_pool_id],
                        reverse_target_index,
                        reverse_message,
                    )

            updated: Dict[int, torch.Tensor] = {}
            for pool_id in self.pool_ids:
                node = current[pool_id]
                degree = degrees[pool_id].clamp_min(1.0)
                neighborhood = aggregated[pool_id] / degree
                update = self.pool_update_layers[_module_key(pool_id)](torch.cat([node, neighborhood], dim=-1))
                updated[pool_id] = self.pool_norms[_module_key(pool_id)](node + update)
            current = updated
        return current


def _normal_kl(
    mu_q: torch.Tensor,
    logvar_q: torch.Tensor,
    mu_p: torch.Tensor,
    logvar_p: torch.Tensor,
) -> torch.Tensor:
    var_q = torch.exp(logvar_q)
    var_p = torch.exp(logvar_p)
    return 0.5 * torch.sum(logvar_p - logvar_q + (var_q + (mu_q - mu_p).pow(2)) / var_p - 1.0)


def _repair_params(params: torch.Tensor, rule: TaskRule) -> torch.Tensor:
    repaired = params.clone()
    for dim, (lower, upper) in enumerate(rule.param_bounds):
        repaired[:, dim] = repaired[:, dim].clamp(float(lower), float(upper))
    for constraint in rule.param_constraints:
        if constraint.get("constraint_type") != "sum_leq":
            continue
        indexes = [int(index) for index in constraint.get("param_indexes", [])]
        if len(indexes) != 2:
            continue
        limit = float(constraint.get("limit", 1.0))
        repair_index = int(constraint.get("repair_param_index", indexes[-1]))
        if repair_index not in indexes:
            repair_index = indexes[-1]
        other_index = indexes[0] if repair_index == indexes[1] else indexes[1]
        repair_lower, repair_upper = (float(value) for value in rule.param_bounds[repair_index])
        other_lower, other_upper = (float(value) for value in rule.param_bounds[other_index])

        repaired[:, repair_index] = torch.minimum(
            repaired[:, repair_index],
            torch.full_like(repaired[:, repair_index], limit) - repaired[:, other_index],
        ).clamp(repair_lower, repair_upper)

        overflow = repaired[:, indexes[0]] + repaired[:, indexes[1]] > limit
        if bool(overflow.any()):
            repaired[overflow, other_index] = torch.minimum(
                repaired[overflow, other_index],
                torch.full_like(repaired[overflow, other_index], limit) - repaired[overflow, repair_index],
            )
            repaired[:, other_index] = repaired[:, other_index].clamp(other_lower, other_upper)
            repaired[:, repair_index] = torch.minimum(
                repaired[:, repair_index],
                torch.full_like(repaired[:, repair_index], limit) - repaired[:, other_index],
            ).clamp(repair_lower, repair_upper)
    return repaired


def _index_add_messages(
    accumulator: torch.Tensor,
    degrees: torch.Tensor,
    index: torch.Tensor,
    messages: torch.Tensor,
) -> None:
    accumulator.index_add_(0, index, messages)
    degrees.index_add_(0, index, torch.ones((messages.shape[0], 1), dtype=messages.dtype, device=messages.device))


def _mean_or_zero(value: torch.Tensor, hidden_dim: int, device: torch.device) -> torch.Tensor:
    if value.numel():
        return value.mean(dim=0)
    return torch.zeros(hidden_dim, dtype=torch.float32, device=device)


def _mean_edge_or_zero(edges: List[_HiddenEdge], hidden_dim: int, device: torch.device) -> torch.Tensor:
    rows = [edge.edge_h for edge in edges if edge.edge_h.numel()]
    if not rows:
        return torch.zeros(hidden_dim, dtype=torch.float32, device=device)
    return torch.cat(rows, dim=0).mean(dim=0)


def _param_input(value: torch.Tensor, feature_dim: int, device: torch.device) -> torch.Tensor:
    if feature_dim > 0:
        return value.to(device).float()
    return torch.zeros(1, dtype=torch.float32, device=device)


def _param_input_dim(feature_dim: int) -> int:
    return max(1, int(feature_dim))


def _context_edge_key(edge_type_id: int) -> str:
    return f"context_{int(edge_type_id)}"


def _anchor_edge_key(task_id: int) -> str:
    return f"anchor_{int(task_id)}"


def _module_key(value: object) -> str:
    return str(value).replace(".", "_")


def _mlp(input_dim: int, hidden_dim: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.ReLU(),
        nn.Linear(hidden_dim, hidden_dim),
        nn.ReLU(),
    )

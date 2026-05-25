from __future__ import annotations

from typing import Dict, List, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from src.data import MathGraphSample, TaskRule


class RailDisturbanceVAE(nn.Module):
    """VAE over mathematical rail-disturbance graph samples.

    The model only consumes numeric pools, numeric edges, task rules, and
    numeric supervision. Railway names and anchor ids stay outside this module.
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

        self.pool_encoders = nn.ModuleDict(
            {
                str(pool_id): _mlp(feature_dim, hidden_dim)
                for pool_id, feature_dim in self.pool_feature_dims.items()
            }
        )
        self.edge_encoders = nn.ModuleDict(
            {
                str(edge_type_id): _mlp(feature_dim, hidden_dim)
                for edge_type_id, feature_dim in self.edge_feature_dims.items()
            }
        )
        self.forward_message_layers = nn.ModuleDict(
            {
                str(edge_type_id): _mlp(hidden_dim * 3, hidden_dim)
                for edge_type_id in self.edge_feature_dims
            }
        )
        self.reverse_message_layers = nn.ModuleDict(
            {
                str(edge_type_id): _mlp(hidden_dim * 3, hidden_dim)
                for edge_type_id in self.edge_feature_dims
            }
        )
        self.pool_update_layers = nn.ModuleDict(
            {
                str(pool_id): _mlp(hidden_dim * 2, hidden_dim)
                for pool_id in self.pool_feature_dims
            }
        )
        self.pool_norms = nn.ModuleDict(
            {
                str(pool_id): nn.LayerNorm(hidden_dim)
                for pool_id in self.pool_feature_dims
            }
        )
        self.target_encoders = nn.ModuleDict(
            {
                str(task_id): _mlp(1 + int(defn["max_slots"]) + int(defn["max_slots"]) * int(defn["param_dim"]), hidden_dim)
                for task_id, defn in self.task_defs.items()
            }
        )
        self.relation_encoder = _mlp(max(1, self.relation_feature_dim), hidden_dim)

        context_dim = hidden_dim * (len(self.pool_feature_dims) + len(self.edge_feature_dims))
        target_dim = hidden_dim * (len(self.task_defs) + 1)
        self.context_dim = context_dim
        self.target_dim = target_dim

        self.prior_mu = nn.Linear(context_dim, latent_dim)
        self.prior_logvar = nn.Linear(context_dim, latent_dim)
        self.posterior_mu = nn.Linear(context_dim + target_dim, latent_dim)
        self.posterior_logvar = nn.Linear(context_dim + target_dim, latent_dim)

        self.decoder = _mlp(context_dim + latent_dim, hidden_dim)
        self.count_heads = nn.ModuleDict()
        self.slot_query_heads = nn.ModuleDict()
        self.param_heads = nn.ModuleDict()
        for task_id, defn in self.task_defs.items():
            max_slots = int(defn["max_slots"])
            param_dim = int(defn["param_dim"])
            self.count_heads[str(task_id)] = nn.Linear(hidden_dim, max_slots + 1)
            self.slot_query_heads[str(task_id)] = nn.Linear(hidden_dim, max_slots * hidden_dim)
            self.param_heads[str(task_id)] = nn.Linear(hidden_dim, max_slots * param_dim)

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
        context, pool_embeddings = self.encode_context(sample)
        target = self.encode_target(sample)
        prior_mu, prior_logvar = self.prior(context)
        posterior_mu, posterior_logvar = self.posterior(context, target)
        z = self.reparameterize(posterior_mu, posterior_logvar)
        decoded = self.decode(z, context, pool_embeddings)
        return {
            "prior_mu": prior_mu,
            "prior_logvar": prior_logvar,
            "posterior_mu": posterior_mu,
            "posterior_logvar": posterior_logvar,
            "tasks": decoded,
        }

    def encode_context(self, sample: MathGraphSample) -> Tuple[torch.Tensor, Dict[int, torch.Tensor]]:
        device = next(self.parameters()).device
        pooled: List[torch.Tensor] = []
        pool_embeddings: Dict[int, torch.Tensor] = {}

        for pool_id in self.pool_feature_dims:
            x = sample.pool_x[pool_id].to(device)
            embeddings = self.pool_encoders[str(pool_id)](x)
            pool_embeddings[pool_id] = embeddings

        pool_embeddings = self.message_pass(sample, pool_embeddings)

        for pool_id in self.pool_feature_dims:
            embeddings = pool_embeddings[pool_id]
            pooled.append(embeddings.mean(dim=0) if embeddings.numel() else torch.zeros(self.hidden_dim, device=device))

        for edge_type_id, feature_dim in self.edge_feature_dims.items():
            edge_attr = sample.edges[edge_type_id].edge_attr.to(device)
            if edge_attr.numel():
                pooled.append(self.edge_encoders[str(edge_type_id)](edge_attr).mean(dim=0))
            else:
                pooled.append(torch.zeros(self.hidden_dim, device=device))

        return torch.cat(pooled, dim=0), pool_embeddings

    def message_pass(
        self,
        sample: MathGraphSample,
        pool_embeddings: Dict[int, torch.Tensor],
    ) -> Dict[int, torch.Tensor]:
        if self.message_passing_steps <= 0:
            return pool_embeddings

        device = next(self.parameters()).device
        current = pool_embeddings
        for _step in range(self.message_passing_steps):
            aggregated = {pool_id: torch.zeros_like(x) for pool_id, x in current.items()}
            degrees = {
                pool_id: torch.zeros((x.shape[0], 1), dtype=x.dtype, device=device)
                for pool_id, x in current.items()
            }

            for edge_type_id in self.edge_feature_dims:
                edge = sample.edges[edge_type_id]
                if edge.edge_index.numel() == 0:
                    continue
                source_pool_id = edge.source_pool_id
                target_pool_id = edge.target_pool_id
                edge_index = edge.edge_index.to(device)
                source_index = edge_index[0]
                target_index = edge_index[1]
                edge_h = self.edge_encoders[str(edge_type_id)](edge.edge_attr.to(device))

                source_h = current[source_pool_id].index_select(0, source_index)
                target_h = current[target_pool_id].index_select(0, target_index)
                forward_message = self.forward_message_layers[str(edge_type_id)](
                    torch.cat([source_h, target_h, edge_h], dim=-1)
                )
                _index_add_messages(aggregated[target_pool_id], degrees[target_pool_id], target_index, forward_message)

                reverse_mask = ~edge.directed.to(device)
                if bool(reverse_mask.any()):
                    reverse_rows = torch.where(reverse_mask)[0]
                    reverse_source_index = target_index.index_select(0, reverse_rows)
                    reverse_target_index = source_index.index_select(0, reverse_rows)
                    reverse_source_h = current[target_pool_id].index_select(0, reverse_source_index)
                    reverse_target_h = current[source_pool_id].index_select(0, reverse_target_index)
                    reverse_edge_h = edge_h.index_select(0, reverse_rows)
                    reverse_message = self.reverse_message_layers[str(edge_type_id)](
                        torch.cat([reverse_source_h, reverse_target_h, reverse_edge_h], dim=-1)
                    )
                    _index_add_messages(
                        aggregated[source_pool_id],
                        degrees[source_pool_id],
                        reverse_target_index,
                        reverse_message,
                    )

            updated: Dict[int, torch.Tensor] = {}
            for pool_id, node_h in current.items():
                degree = degrees[pool_id].clamp_min(1.0)
                neighborhood_h = aggregated[pool_id] / degree
                update = self.pool_update_layers[str(pool_id)](torch.cat([node_h, neighborhood_h], dim=-1))
                updated[pool_id] = self.pool_norms[str(pool_id)](node_h + update)
            current = updated
        return current

    def encode_target(self, sample: MathGraphSample) -> torch.Tensor:
        device = next(self.parameters()).device
        pooled: List[torch.Tensor] = []
        for task_id, defn in self.task_defs.items():
            target = sample.targets[task_id]
            max_slots = int(defn["max_slots"])
            param_dim = int(defn["param_dim"])
            pool_id = int(defn["target_pool_id"])
            pool_size = max(1, sample.pool_rules[pool_id].size - 1)

            count_part = torch.tensor([target.count / max(1, max_slots)], dtype=torch.float32, device=device)
            anchor_part = torch.zeros(max_slots, dtype=torch.float32, device=device)
            param_part = torch.zeros(max_slots, param_dim, dtype=torch.float32, device=device)
            if target.count:
                anchor_part[: target.count] = target.anchor_index.to(device).float() / pool_size
                param_part[: target.count] = target.params.to(device)
            vector = torch.cat([count_part, anchor_part, param_part.flatten()], dim=0)
            pooled.append(self.target_encoders[str(task_id)](vector))

        relation_x = sample.target_relation_x.to(device)
        if relation_x.numel():
            pooled.append(self.relation_encoder(relation_x).mean(dim=0))
        else:
            pooled.append(torch.zeros(self.hidden_dim, device=device))
        return torch.cat(pooled, dim=0)

    def prior(self, context: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        return self.prior_mu(context), self.prior_logvar(context)

    def posterior(self, context: torch.Tensor, target: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        combined = torch.cat([context, target], dim=0)
        return self.posterior_mu(combined), self.posterior_logvar(combined)

    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        if not self.training:
            return mu
        std = torch.exp(0.5 * logvar)
        return mu + torch.randn_like(std) * std

    def decode(
        self,
        z: torch.Tensor,
        context: torch.Tensor,
        pool_embeddings: Dict[int, torch.Tensor],
    ) -> Dict[int, Dict[str, torch.Tensor]]:
        hidden = self.decoder(torch.cat([z, context], dim=0))
        result: Dict[int, Dict[str, torch.Tensor]] = {}
        for task_id, defn in self.task_defs.items():
            max_slots = int(defn["max_slots"])
            param_dim = int(defn["param_dim"])
            target_pool_id = int(defn["target_pool_id"])
            slot_queries = self.slot_query_heads[str(task_id)](hidden).view(max_slots, self.hidden_dim)
            anchor_logits = slot_queries @ pool_embeddings[target_pool_id].t()
            params = self.param_heads[str(task_id)](hidden).view(max_slots, param_dim)
            result[task_id] = {
                "count_logits": self.count_heads[str(task_id)](hidden),
                "anchor_logits": anchor_logits,
                "params": params,
            }
        return result

    def decode_from_prior(self, sample: MathGraphSample) -> Dict[int, Dict[str, torch.Tensor]]:
        context, pool_embeddings = self.encode_context(sample)
        prior_mu, prior_logvar = self.prior(context)
        std = torch.exp(0.5 * prior_logvar)
        z = prior_mu + torch.randn_like(std) * std
        return self.decode(z, context, pool_embeddings)


def vae_loss(
    sample: MathGraphSample,
    outputs: Dict[str, object],
    kl_weight: float = 1.0,
    count_weight: float = 1.0,
    anchor_weight: float = 1.0,
    param_weight: float = 1.0,
) -> Tuple[torch.Tensor, Dict[str, float]]:
    device = outputs["prior_mu"].device
    count_loss = torch.tensor(0.0, device=device)
    anchor_loss = torch.tensor(0.0, device=device)
    param_loss = torch.tensor(0.0, device=device)

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
    total = (
        float(count_weight) * count_loss
        + float(anchor_weight) * anchor_loss
        + float(param_weight) * param_loss
        + float(kl_weight) * kl
    )
    metrics = {
        "loss": float(total.detach().cpu()),
        "count_loss": float(count_loss.detach().cpu()),
        "anchor_loss": float(anchor_loss.detach().cpu()),
        "param_loss": float(param_loss.detach().cpu()),
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


def _mlp(input_dim: int, hidden_dim: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.ReLU(),
        nn.Linear(hidden_dim, hidden_dim),
        nn.ReLU(),
    )

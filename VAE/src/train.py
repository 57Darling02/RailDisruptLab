from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the math rail-disturbance VAE.")
    parser.add_argument("--graphs-root", required=True, help="Math learning graph file or directory.")
    parser.add_argument("--output-dir", required=True, help="Directory for checkpoint and training metadata.")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--latent-dim", type=int, default=32)
    parser.add_argument("--message-passing-steps", type=int, default=2)
    parser.add_argument("--kl-weight", type=float, default=1e-3)
    parser.add_argument("--limit", type=int, default=0, help="Optional number of graphs to load; 0 means all.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or cuda:<index>.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    import torch

    from src.data import RailDisturbanceDataset
    from src.model import RailDisturbanceVAE, vae_loss

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = _device(args.device, torch)
    dataset = RailDisturbanceDataset(args.graphs_root, num_instances=args.limit or None)
    first_sample = dataset[0]
    model = RailDisturbanceVAE.from_sample(
        first_sample,
        hidden_dim=args.hidden_dim,
        latent_dim=args.latent_dim,
        message_passing_steps=args.message_passing_steps,
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "training_config.json").write_text(
        json.dumps(vars(args), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "schema_summary.json").write_text(
        json.dumps(_schema_summary(first_sample), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    history: List[Dict[str, float]] = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        indices = list(range(len(dataset)))
        random.shuffle(indices)
        epoch_metrics: Dict[str, float] = {}
        steps = 0

        for start in range(0, len(indices), max(1, args.batch_size)):
            batch_indices = indices[start : start + max(1, args.batch_size)]
            optimizer.zero_grad()
            batch_loss = None
            batch_metrics: Dict[str, float] = {}
            for index in batch_indices:
                sample = dataset[index].to(device)
                outputs = model(sample)
                loss, metrics = vae_loss(sample, outputs, kl_weight=args.kl_weight)
                if not torch.isfinite(loss):
                    raise ValueError(f"Non-finite loss for sample: {sample.graph_path}")
                batch_loss = loss if batch_loss is None else batch_loss + loss
                for key, value in metrics.items():
                    batch_metrics[key] = batch_metrics.get(key, 0.0) + float(value)
            assert batch_loss is not None
            (batch_loss / len(batch_indices)).backward()
            optimizer.step()

            for key, value in batch_metrics.items():
                epoch_metrics[key] = epoch_metrics.get(key, 0.0) + value / len(batch_indices)
            steps += 1

        averaged = {key: value / max(1, steps) for key, value in epoch_metrics.items()}
        averaged["epoch"] = float(epoch)
        history.append(averaged)
        print(
            "epoch={epoch} loss={loss:.6f} count={count_loss:.6f} "
            "anchor={anchor_loss:.6f} param={param_loss:.6f} kl={kl:.6f}".format(
                epoch=epoch,
                loss=averaged.get("loss", 0.0),
                count_loss=averaged.get("count_loss", 0.0),
                anchor_loss=averaged.get("anchor_loss", 0.0),
                param_loss=averaged.get("param_loss", 0.0),
                kl=averaged.get("kl", 0.0),
            )
        )

    torch.save(
        {
            "state_dict": model.state_dict(),
            "model_config": model.config_dict(),
        },
        output_dir / "model.pt",
    )
    (output_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(f"Model checkpoint written: {output_dir / 'model.pt'}")


def _device(value: str, torch_module) -> object:
    if value == "auto":
        return torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    return torch_module.device(value)


def _schema_summary(sample) -> Dict[str, object]:
    return {
        "pools": {
            str(pool_id): {
                "size": rule.size,
                "feature_dim": rule.feature_dim,
            }
            for pool_id, rule in sample.pool_rules.items()
        },
        "edge_types": {
            str(edge_type_id): {
                "source_pool_id": rule.source_pool_id,
                "target_pool_id": rule.target_pool_id,
                "feature_dim": rule.feature_dim,
            }
            for edge_type_id, rule in sample.edge_type_rules.items()
        },
        "tasks": {
            str(task_id): {
                "target_pool_id": rule.target_pool_id,
                "max_slots": rule.max_slots,
                "param_dim": rule.param_dim,
            }
            for task_id, rule in sample.task_rules.items()
        },
        "message_passing": {
            "uses_edge_index": True,
            "uses_edge_attr": True,
        },
    }


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from core.file_ops import atomic_write_text

DEFAULT_OUTPUT_DIR = Path("projects/demo/model/default")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the math rail-disturbance VAE.")
    parser.add_argument("--graphs-root", required=True, help="Training graph library directory.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Model output directory.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--latent-dim", type=int, default=16)
    parser.add_argument("--message-passing-steps", type=int, default=2)
    parser.add_argument("--epochs", type=int, default=800)
    parser.add_argument("--checkpoint-every", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=0.0003)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--log-every", type=int, default=1)
    parser.add_argument("--count-weight", type=float, default=1.0)
    parser.add_argument("--anchor-weight", type=float, default=1.0)
    parser.add_argument("--param-weight", type=float, default=2.0)
    parser.add_argument("--kl-weight", type=float, default=0.0015)
    parser.add_argument("--use-relation-graph", dest="use_relation_graph", action="store_true", default=True)
    parser.add_argument("--no-relation-graph", dest="use_relation_graph", action="store_false")
    parser.add_argument("--relation-weight", type=float, default=0.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    import torch

    from src.data import RailDisturbanceDataset
    from src.model import ARCHITECTURE_VERSION, RailDisturbanceVAE, vae_loss

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = _device(args.device, torch)
    dataset = RailDisturbanceDataset(args.graphs_root, num_instances=args.limit or None)
    first_sample = dataset[0]
    if args.use_relation_graph != (first_sample.target_relation_x.shape[1] > 0):
        expected = "enabled" if args.use_relation_graph else "disabled"
        raise ValueError(f"Training graph relation schema does not match use_relation_graph={expected}.")
    model = RailDisturbanceVAE.from_sample(
        first_sample,
        hidden_dim=args.hidden_dim,
        latent_dim=args.latent_dim,
        message_passing_steps=args.message_passing_steps,
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    output_dir = Path(args.output_dir)
    _prepare_output_dir(output_dir, allowed_root=Path("projects"))
    logger = _TrainingLogger(
        output_dir / "training.log",
        loss_history_path=output_dir / "loss_history.jsonl",
    )
    config_payload = vars(args).copy()
    config_payload["architecture_version"] = ARCHITECTURE_VERSION
    config_payload["created_at"] = datetime.now().isoformat(timespec="seconds")
    config_payload["run_dir"] = str(output_dir.resolve()).replace("\\", "/")
    config_payload["resolved_output_dir"] = str(output_dir.resolve()).replace("\\", "/")
    atomic_write_text(output_dir / "training_config.json", json.dumps(config_payload, ensure_ascii=False, indent=2))
    atomic_write_text(
        output_dir / "schema_summary.json",
        json.dumps(_schema_summary(first_sample, architecture_version=ARCHITECTURE_VERSION), ensure_ascii=False, indent=2),
    )
    logger.log("Training started")
    logger.log(f"graphs_root={args.graphs_root}")
    logger.log(f"run_dir={output_dir}")
    logger.log(f"samples={len(dataset)} epochs={args.epochs} batch_size={args.batch_size} device={device}")
    logger.log(f"training_config={output_dir / 'training_config.json'}")
    logger.log(f"schema_summary={output_dir / 'schema_summary.json'}")
    logger.log(f"history={output_dir / 'history.json'}")
    logger.log(f"loss_history={output_dir / 'loss_history.jsonl'}")
    checkpoints_dir = output_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    logger.log(f"checkpoints={checkpoints_dir}")

    history: List[Dict[str, float]] = []
    best_metrics: Dict[str, float] | None = None
    best_path: Path | None = None
    global_step = 0
    try:
        for epoch in range(1, args.epochs + 1):
            model.train()
            indices = list(range(len(dataset)))
            random.shuffle(indices)
            epoch_metrics: Dict[str, float] = {}
            steps = 0
            batch_size = max(1, args.batch_size)
            total_steps = max(1, (len(indices) + batch_size - 1) // batch_size)
            epoch_start = time.perf_counter()

            for start in range(0, len(indices), batch_size):
                batch_indices = indices[start : start + batch_size]
                optimizer.zero_grad()
                batch_loss = None
                batch_metrics: Dict[str, float] = {}
                for index in batch_indices:
                    sample = dataset[index].to(device)
                    outputs = model(sample)
                    loss, metrics = vae_loss(
                        sample,
                        outputs,
                        kl_weight=args.kl_weight,
                        count_weight=args.count_weight,
                        anchor_weight=args.anchor_weight,
                        param_weight=args.param_weight,
                        relation_weight=args.relation_weight,
                    )
                    if not torch.isfinite(loss):
                        raise ValueError(f"Non-finite loss for sample: {sample.graph_path}")
                    batch_loss = loss if batch_loss is None else batch_loss + loss
                    for key, value in metrics.items():
                        batch_metrics[key] = batch_metrics.get(key, 0.0) + float(value)
                assert batch_loss is not None
                (batch_loss / len(batch_indices)).backward()
                optimizer.step()

                batch_average = {
                    key: value / len(batch_indices)
                    for key, value in batch_metrics.items()
                }
                for key, value in batch_average.items():
                    epoch_metrics[key] = epoch_metrics.get(key, 0.0) + value
                steps += 1
                global_step += 1
                logger.progress(
                    global_step=global_step,
                    epoch=epoch,
                    epochs=args.epochs,
                    step=steps,
                    total_steps=total_steps,
                    metrics=batch_average,
                    elapsed=time.perf_counter() - epoch_start,
                    log_every=max(1, args.log_every),
                )

            averaged = {key: value / max(1, steps) for key, value in epoch_metrics.items()}
            averaged["epoch"] = float(epoch)
            history.append(averaged)
            atomic_write_text(output_dir / "history.json", json.dumps(history, indent=2))
            should_check_checkpoint = epoch % max(1, args.checkpoint_every) == 0 or epoch == args.epochs
            if should_check_checkpoint and (best_metrics is None or averaged["loss"] < best_metrics["loss"]):
                previous_best_path = best_path
                best_metrics = dict(averaged)
                best_path = _checkpoint_path(checkpoints_dir, epoch)
                _save_checkpoint(model, best_path, best_metrics)
                _delete_unreferenced(previous_best_path, keep={best_path})
                logger.log(f"Best checkpoint updated: {best_path}")
            logger.epoch_end(epoch, args.epochs, averaged, time.perf_counter() - epoch_start)

        last_metrics = dict(history[-1]) if history else {}
        last_epoch = int(last_metrics.get("epoch", 0))
        best_epoch = int(best_metrics.get("epoch", 0)) if best_metrics else 0
        last_path = _checkpoint_path(checkpoints_dir, last_epoch) if last_epoch else None
        if last_path and last_path != best_path:
            _save_checkpoint(model, last_path, last_metrics)
        keep_paths = {path for path in (best_path, last_path) if path is not None}
        _cleanup_checkpoints(checkpoints_dir, keep_paths)
        atomic_write_text(
            output_dir / "training_summary.json",
            json.dumps(
                {
                    "last_epoch": last_epoch,
                    "last_metrics": last_metrics,
                    "best_epoch": best_epoch,
                    "best_metrics": best_metrics or {},
                    "last_checkpoint": _relative_checkpoint(output_dir, last_path),
                    "best_checkpoint": _relative_checkpoint(output_dir, best_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        logger.log(f"Last checkpoint: {last_path}")
        logger.log(f"Best checkpoint: {best_path}")
    finally:
        logger.close()


def _device(value: str, torch_module) -> object:
    if value == "auto":
        return torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    return torch_module.device(value)


def _save_checkpoint(model, path: Path, metrics: Dict[str, float]) -> None:
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "model_config": model.config_dict(),
            "metrics": dict(metrics),
        },
        path,
    )


def _checkpoint_path(checkpoints_dir: Path, epoch: int) -> Path:
    return checkpoints_dir / f"epoch_{max(0, int(epoch)):06d}.pt"


def _relative_checkpoint(output_dir: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(output_dir.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _delete_unreferenced(path: Path | None, *, keep: Iterable[Path]) -> None:
    if path is None:
        return
    keep_paths = {item.resolve() for item in keep}
    if path.resolve() in keep_paths:
        return
    if path.is_file():
        path.unlink()


def _cleanup_checkpoints(checkpoints_dir: Path, keep: Iterable[Path]) -> None:
    keep_paths = {path.resolve() for path in keep}
    if not checkpoints_dir.is_dir():
        return
    for path in checkpoints_dir.glob("*.pt"):
        if path.resolve() not in keep_paths:
            path.unlink()


def _prepare_output_dir(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to clear path outside allowed root: {path}")
    if path.is_symlink() or path.is_file():
        raise ValueError(f"Output dir must be a directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    for filename in (
        "training.log",
        "training_config.json",
        "schema_summary.json",
        "history.json",
        "loss_history.jsonl",
        "training_summary.json",
        "train_config.yml",
        "best_model.pt",
        "last_model.pt",
    ):
        target = path / filename
        if target.exists():
            target.unlink()
    checkpoints_dir = path / "checkpoints"
    if checkpoints_dir.is_dir():
        for checkpoint in checkpoints_dir.glob("*.pt"):
            checkpoint.unlink()


def _schema_summary(sample, *, architecture_version: int) -> Dict[str, object]:
    use_relation_graph = sample.target_relation_x.shape[1] > 0
    return {
        "architecture_version": architecture_version,
        "posterior_encoder": "joint_gnn(C + G_D + R)" if use_relation_graph else "joint_gnn(C + G_D)",
        "decoder": "z_conditioned_heads(C embeddings, z) -> task_outputs",
        "use_relation_graph": use_relation_graph,
        "auxiliary_loss": "target_relation_smooth_l1" if use_relation_graph else "none",
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
                "count_bounds": rule.count_bounds,
                "param_dim": rule.param_dim,
                "param_bounds": rule.param_bounds,
                "param_transform": rule.param_transform,
            }
            for task_id, rule in sample.task_rules.items()
        },
        "message_passing": {
            "uses_edge_index": True,
            "uses_edge_attr": True,
        },
    }


class _TrainingLogger:
    def __init__(self, log_path: Path, *, loss_history_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.log_path.open("w", encoding="utf-8")
        self.loss_file = loss_history_path.open("w", encoding="utf-8")
        self.last_progress_len = 0

    def close(self) -> None:
        self.file.close()
        self.loss_file.close()

    def log(self, message: str) -> None:
        self._clear_progress_line()
        line = f"{_timestamp()} {message}"
        print(line, flush=True)
        self.file.write(line + "\n")
        self.file.flush()

    def progress(
        self,
        *,
        global_step: int,
        epoch: int,
        epochs: int,
        step: int,
        total_steps: int,
        metrics: Dict[str, float],
        elapsed: float,
        log_every: int,
    ) -> None:
        line = _progress_line(epoch, epochs, step, total_steps, metrics, elapsed)
        self._write_loss_point(global_step, epoch, step, total_steps, metrics, elapsed)
        sys.stdout.write("\r" + line + " " * max(0, self.last_progress_len - len(line)))
        sys.stdout.flush()
        self.last_progress_len = len(line)
        if step == total_steps or step % log_every == 0:
            self.file.write(f"{_timestamp()} {line}\n")
            self.file.flush()

    def _write_loss_point(
        self,
        global_step: int,
        epoch: int,
        epoch_step: int,
        total_steps: int,
        metrics: Dict[str, float],
        elapsed: float,
    ) -> None:
        payload: Dict[str, object] = {
            "step": global_step,
            "epoch": epoch,
            "epoch_step": epoch_step,
            "total_steps": total_steps,
            "elapsed": elapsed,
        }
        payload.update({key: float(value) for key, value in metrics.items()})
        self.loss_file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.loss_file.flush()

    def epoch_end(self, epoch: int, epochs: int, metrics: Dict[str, float], elapsed: float) -> None:
        self._clear_progress_line()
        line = (
            "epoch={epoch}/{epochs} done loss={loss:.6f} count={count_loss:.6f} "
            "anchor={anchor_loss:.6f} param={param_loss:.6f} "
            "relation={relation_loss:.6f} kl={kl:.6f} elapsed={elapsed:.1f}s"
        ).format(
            epoch=epoch,
            epochs=epochs,
            loss=metrics.get("loss", 0.0),
            count_loss=metrics.get("count_loss", 0.0),
            anchor_loss=metrics.get("anchor_loss", 0.0),
            param_loss=metrics.get("param_loss", 0.0),
            relation_loss=metrics.get("relation_loss", 0.0),
            kl=metrics.get("kl", 0.0),
            elapsed=elapsed,
        )
        print(line, flush=True)
        self.file.write(f"{_timestamp()} {line}\n")
        self.file.flush()

    def _clear_progress_line(self) -> None:
        if self.last_progress_len:
            sys.stdout.write("\r" + " " * self.last_progress_len + "\r")
            sys.stdout.flush()
            self.last_progress_len = 0


def _progress_line(
    epoch: int,
    epochs: int,
    step: int,
    total_steps: int,
    metrics: Dict[str, float],
    elapsed: float,
) -> str:
    width = 28
    ratio = min(1.0, max(0.0, float(step) / float(max(1, total_steps))))
    filled = int(round(width * ratio))
    bar = "#" * filled + "." * (width - filled)
    return (
        "epoch={epoch}/{epochs} [{bar}] {step}/{total_steps} "
        "loss={loss:.6f} count={count_loss:.6f} anchor={anchor_loss:.6f} "
        "param={param_loss:.6f} relation={relation_loss:.6f} kl={kl:.6f} elapsed={elapsed:.1f}s"
    ).format(
        epoch=epoch,
        epochs=epochs,
        bar=bar,
        step=step,
        total_steps=total_steps,
        loss=metrics.get("loss", 0.0),
        count_loss=metrics.get("count_loss", 0.0),
        anchor_loss=metrics.get("anchor_loss", 0.0),
        param_loss=metrics.get("param_loss", 0.0),
        relation_loss=metrics.get("relation_loss", 0.0),
        kl=metrics.get("kl", 0.0),
        elapsed=elapsed,
    )


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_OUTPUT_DIR = Path("outputs/main/models/default")
DEFAULT_CONFIG_PATH = "config/demo.yml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the math rail-disturbance VAE.")
    parser.add_argument("config", nargs="?", default=DEFAULT_CONFIG_PATH, help="Training YAML config path.")
    parser.add_argument("--graphs-root", default="", help="Override config data.graphs_root.")
    parser.add_argument("--output-dir", default="", help="Override config output.dir.")
    cli_args = parser.parse_args()
    args = _load_train_config(cli_args.config)
    if cli_args.graphs_root:
        args.graphs_root = cli_args.graphs_root
    if cli_args.output_dir:
        args.output_dir = cli_args.output_dir
    if not str(args.graphs_root).strip():
        raise ValueError("config.train.data.graphs_root is required unless --graphs-root is provided.")
    return args


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
    _reset_path(output_dir, allowed_root=Path("outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = _TrainingLogger(output_dir / "training.log")
    config_payload = vars(args).copy()
    config_payload["created_at"] = datetime.now().isoformat(timespec="seconds")
    config_payload["run_dir"] = str(output_dir.resolve()).replace("\\", "/")
    config_payload["resolved_output_dir"] = str(output_dir.resolve()).replace("\\", "/")
    (output_dir / "training_config.json").write_text(
        json.dumps(config_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "schema_summary.json").write_text(
        json.dumps(_schema_summary(first_sample), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.log("Training started")
    logger.log(f"config={args.config}")
    logger.log(f"graphs_root={args.graphs_root}")
    logger.log(f"run_dir={output_dir}")
    logger.log(f"samples={len(dataset)} epochs={args.epochs} batch_size={args.batch_size} device={device}")
    logger.log(f"training_config={output_dir / 'training_config.json'}")
    logger.log(f"schema_summary={output_dir / 'schema_summary.json'}")
    logger.log(f"history={output_dir / 'history.json'}")
    logger.log(f"best_checkpoint={output_dir / 'best_model.pt'}")
    logger.log(f"last_checkpoint={output_dir / 'last_model.pt'}")

    history: List[Dict[str, float]] = []
    best_metrics: Dict[str, float] | None = None
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
                logger.progress(
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
            (output_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
            if best_metrics is None or averaged["loss"] < best_metrics["loss"]:
                best_metrics = dict(averaged)
                _save_checkpoint(model, output_dir / "best_model.pt", best_metrics)
                logger.log(f"Best checkpoint updated: {output_dir / 'best_model.pt'}")
            logger.epoch_end(epoch, args.epochs, averaged, time.perf_counter() - epoch_start)

        last_metrics = dict(history[-1]) if history else {}
        _save_checkpoint(model, output_dir / "last_model.pt", last_metrics)
        (output_dir / "training_summary.json").write_text(
            json.dumps(
                {
                    "last_epoch": int(last_metrics.get("epoch", 0)),
                    "last_metrics": last_metrics,
                    "best_epoch": int(best_metrics.get("epoch", 0)) if best_metrics else 0,
                    "best_metrics": best_metrics or {},
                    "last_model": str((output_dir / "last_model.pt").resolve()).replace("\\", "/"),
                    "best_model": str((output_dir / "best_model.pt").resolve()).replace("\\", "/"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.log(f"Last checkpoint written: {output_dir / 'last_model.pt'}")
        logger.log(f"Best checkpoint: {output_dir / 'best_model.pt'}")
    finally:
        logger.close()


def _device(value: str, torch_module) -> object:
    if value == "auto":
        return torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    return torch_module.device(value)


def _save_checkpoint(model, path: Path, metrics: Dict[str, float]) -> None:
    import torch

    torch.save(
        {
            "state_dict": model.state_dict(),
            "model_config": model.config_dict(),
            "metrics": dict(metrics),
        },
        path,
    )


def _load_train_config(path_text: str) -> argparse.Namespace:
    path = Path(path_text)
    if not path.exists():
        raise FileNotFoundError(f"Training config not found: {path}")
    yaml = _require_yaml()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Training config must be a YAML object: {path}")
    if isinstance(payload.get("train"), dict):
        payload = payload["train"]
    data = _section(payload, "data")
    model = _section(payload, "model")
    optimization = _section(payload, "optimization")
    loss_weights = _section(payload, "loss_weights")
    output = _section(payload, "output")
    graphs_root = str(data.get("graphs_root", "")).strip()
    return argparse.Namespace(
        config=str(path),
        graphs_root=graphs_root,
        limit=int(data.get("limit", 0)),
        hidden_dim=int(model.get("hidden_dim", 64)),
        latent_dim=int(model.get("latent_dim", 32)),
        message_passing_steps=int(model.get("message_passing_steps", 2)),
        epochs=int(optimization.get("epochs", 3)),
        batch_size=int(optimization.get("batch_size", 1)),
        lr=float(optimization.get("lr", 1e-3)),
        seed=int(optimization.get("seed", 1)),
        device=str(optimization.get("device", "auto")),
        log_every=int(optimization.get("log_every", 1)),
        count_weight=float(loss_weights.get("count", 1.0)),
        anchor_weight=float(loss_weights.get("anchor", 1.0)),
        param_weight=float(loss_weights.get("param", 1.0)),
        kl_weight=float(loss_weights.get("kl", 1e-3)),
        output_dir=str(output.get("dir", DEFAULT_OUTPUT_DIR)),
    )


def _section(payload: Dict[str, object], name: str) -> Dict[str, object]:
    value = payload.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"config.{name} must be a YAML object.")
    return value


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml


def _reset_path(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to clear path outside allowed root: {path}")
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


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
                "count_bounds": rule.count_bounds,
                "param_dim": rule.param_dim,
            }
            for task_id, rule in sample.task_rules.items()
        },
        "message_passing": {
            "uses_edge_index": True,
            "uses_edge_attr": True,
        },
    }


class _TrainingLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.log_path.open("w", encoding="utf-8")
        self.last_progress_len = 0

    def close(self) -> None:
        self.file.close()

    def log(self, message: str) -> None:
        self._clear_progress_line()
        line = f"{_timestamp()} {message}"
        print(line, flush=True)
        self.file.write(line + "\n")
        self.file.flush()

    def progress(
        self,
        *,
        epoch: int,
        epochs: int,
        step: int,
        total_steps: int,
        metrics: Dict[str, float],
        elapsed: float,
        log_every: int,
    ) -> None:
        line = _progress_line(epoch, epochs, step, total_steps, metrics, elapsed)
        sys.stdout.write("\r" + line + " " * max(0, self.last_progress_len - len(line)))
        sys.stdout.flush()
        self.last_progress_len = len(line)
        if step == total_steps or step % log_every == 0:
            self.file.write(f"{_timestamp()} {line}\n")
            self.file.flush()

    def epoch_end(self, epoch: int, epochs: int, metrics: Dict[str, float], elapsed: float) -> None:
        self._clear_progress_line()
        line = (
            "epoch={epoch}/{epochs} done loss={loss:.6f} count={count_loss:.6f} "
            "anchor={anchor_loss:.6f} param={param_loss:.6f} kl={kl:.6f} elapsed={elapsed:.1f}s"
        ).format(
            epoch=epoch,
            epochs=epochs,
            loss=metrics.get("loss", 0.0),
            count_loss=metrics.get("count_loss", 0.0),
            anchor_loss=metrics.get("anchor_loss", 0.0),
            param_loss=metrics.get("param_loss", 0.0),
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
        "param={param_loss:.6f} kl={kl:.6f} elapsed={elapsed:.1f}s"
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
        kl=metrics.get("kl", 0.0),
        elapsed=elapsed,
    )


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    main()

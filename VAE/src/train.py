from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

TRAIN_ROOT = Path("outputs/train")
LATEST_MODEL_DIR = TRAIN_ROOT / "model"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the math rail-disturbance VAE.")
    parser.add_argument("--graphs-root", required=True, help="Math learning graph file or directory.")
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
    parser.add_argument("--log-every", type=int, default=1, help="Write every N training steps to training.log.")
    parser.add_argument("--no-publish-latest", action="store_true", help=argparse.SUPPRESS)
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

    output_dir = _run_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = _TrainingLogger(output_dir / "training.log")
    config_payload = vars(args).copy()
    config_payload["created_at"] = datetime.now().isoformat(timespec="seconds")
    config_payload["run_dir"] = str(output_dir.resolve()).replace("\\", "/")
    config_payload["latest_model_dir"] = str(LATEST_MODEL_DIR.resolve()).replace("\\", "/")
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
    logger.log(f"graphs_root={args.graphs_root}")
    logger.log(f"run_dir={output_dir}")
    logger.log(f"latest_model_dir={LATEST_MODEL_DIR}")
    logger.log(f"samples={len(dataset)} epochs={args.epochs} batch_size={args.batch_size} device={device}")
    logger.log(f"training_config={output_dir / 'training_config.json'}")
    logger.log(f"schema_summary={output_dir / 'schema_summary.json'}")
    logger.log(f"history={output_dir / 'history.json'}")
    logger.log(f"checkpoint={output_dir / 'model.pt'}")

    history: List[Dict[str, float]] = []
    completed = False
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
                    loss, metrics = vae_loss(sample, outputs, kl_weight=args.kl_weight)
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
            logger.epoch_end(epoch, args.epochs, averaged, time.perf_counter() - epoch_start)

        torch.save(
            {
                "state_dict": model.state_dict(),
                "model_config": model.config_dict(),
            },
            output_dir / "model.pt",
        )
        logger.log(f"Model checkpoint written: {output_dir / 'model.pt'}")
        completed = True
    finally:
        logger.close()
    if completed and not args.no_publish_latest:
        _publish_latest_model(output_dir)
        print(f"Latest model directory: {LATEST_MODEL_DIR}", flush=True)


def _device(value: str, torch_module) -> object:
    if value == "auto":
        return torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    return torch_module.device(value)


def _run_dir() -> Path:
    TRAIN_ROOT.mkdir(parents=True, exist_ok=True)
    base_path = TRAIN_ROOT / _timestamp_for_path()
    run_path = base_path
    suffix = 2
    while run_path.exists():
        run_path = base_path.with_name(f"{base_path.name}_{suffix}")
        suffix += 1
    return run_path


def _timestamp_for_path() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _publish_latest_model(run_dir: Path) -> None:
    temp_dir = LATEST_MODEL_DIR.with_name(f"{LATEST_MODEL_DIR.name}.tmp_publish")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    shutil.copytree(run_dir, temp_dir)
    if LATEST_MODEL_DIR.exists():
        if LATEST_MODEL_DIR.is_dir():
            shutil.rmtree(LATEST_MODEL_DIR)
        else:
            LATEST_MODEL_DIR.unlink()
    temp_dir.rename(LATEST_MODEL_DIR)
    (TRAIN_ROOT / "latest_run.txt").write_text(str(run_dir).replace("\\", "/") + "\n", encoding="utf-8")


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

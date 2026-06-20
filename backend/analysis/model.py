from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from core.project_layout import ModelLayout, ProjectLayout, require_id, to_posix


LOSS_METRICS = ("loss", "count_loss", "anchor_loss", "param_loss", "relation_loss", "kl")
STAGE_WEIGHTS = {
    "training_graph": 0.50,
    "vae_training": 0.50,
}


def read_model_detail(layout: ProjectLayout, model_id: str) -> Dict[str, object]:
    model_id = require_id(model_id, "model_id")
    model = layout.model(model_id)
    if not model.root.is_dir():
        raise FileNotFoundError(f"Model not found: {model.root}")

    summary = read_json_if_exists(model.root / "training_summary.json")
    config = read_json_if_exists(model.root / "training_config.json")
    schema = read_json_if_exists(model.root / "schema_summary.json")
    graph_progress = read_json_if_exists(model.graph_progress)
    history = read_history_summary(model.root / "history.json")
    loss_points = read_loss_history(model.root / "loss_history.jsonl")
    checkpoints = list_model_checkpoints(model, summary)

    return {
        "model_id": model_id,
        "root": to_posix(model.root),
        "summary": summary,
        "config": config,
        "schema": schema,
        "history": history,
        "loss_series": epoch_loss_series(loss_points),
        "checkpoints": checkpoints,
        "training_progress": training_progress(
            model,
            config=config,
            summary=summary,
            graph_progress=graph_progress,
            loss_points=loss_points,
            checkpoints=checkpoints,
        ),
    }


def read_training_summary(layout: ProjectLayout, model_id: str) -> Dict[str, object]:
    return read_json(layout.model(model_id).root / "training_summary.json")


def list_model_checkpoints(model: ModelLayout, summary: Dict[str, object] | None = None) -> List[Dict[str, object]]:
    if not model.root.is_dir():
        raise FileNotFoundError(f"Model not found: {model.root}")
    role_paths = checkpoint_role_paths(model, summary or read_json_if_exists(model.root / "training_summary.json"))
    files: List[Dict[str, object]] = []
    for path in sorted(model.root.rglob("*.pt")):
        if not path.is_file():
            continue
        relative_path = to_posix(path.relative_to(model.root))
        roles = checkpoint_roles(relative_path, path.name, role_paths)
        files.append(
            {
                "name": path.name,
                "relative_path": relative_path,
                "path": to_posix(path),
                "role": roles[0] if roles else "checkpoint",
                "roles": roles,
                "size_bytes": path.stat().st_size,
            }
        )
    return files


def training_progress(
    model: ModelLayout,
    *,
    config: Dict[str, object],
    summary: Dict[str, object],
    graph_progress: Dict[str, object],
    loss_points: List[Dict[str, object]],
    checkpoints: List[Dict[str, object]],
) -> Dict[str, object]:
    latest_loss = loss_points[-1] if loss_points else {}
    total_epochs = int_value(config.get("epochs"))
    train_percent = vae_training_percent(latest_loss, total_epochs, model_is_ready(model))
    stages = [
        training_graph_stage(model, graph_progress),
        vae_training_stage(model, latest_loss, total_epochs, train_percent),
    ]
    percentage = weighted_percentage(stages)
    status = training_status(model, loss_points, stages)
    if status == "ready":
        percentage = 100
    elif status != "failed":
        percentage = min(99, percentage)

    return {
        "status": status,
        "label": training_status_label(status, stages),
        "detail": training_status_detail(status, latest_loss, total_epochs, stages),
        "percentage": percentage,
        "stages": stages,
        "metrics": training_metrics(
            summary=summary,
            latest_loss=latest_loss,
            total_epochs=total_epochs,
            checkpoints=checkpoints,
        ),
    }


def training_graph_stage(model: ModelLayout, graph_progress: Dict[str, object]) -> Dict[str, object]:
    global_status = graph_status(graph_progress, "global_graph")
    sample_progress = object_value(graph_progress.get("sample_graphs"))
    status = str(sample_progress.get("status", "") or "")
    total = int_value(sample_progress.get("total"))
    completed = int_value(sample_progress.get("completed"))
    has_context_graph = any(model.context_graph_dir.glob("*.json")) if model.context_graph_dir.is_dir() else False
    sample_count = len(list(model.sample_dir.glob("*.json"))) if model.sample_dir.is_dir() else 0
    if not total and sample_count:
        total = sample_count
        completed = sample_count
    if status == "done" or (total > 0 and completed >= total and has_context_graph):
        state = "done"
        percentage = 100
    elif status == "running" or global_status == "running":
        state = "running"
        sample_percent = ratio_percent(completed, total)
        percentage = max(5, sample_percent if global_status == "done" or has_context_graph else min(20, sample_percent))
    else:
        state = "pending"
        percentage = ratio_percent(completed, total)
    detail = f"{completed}/{total} 个场景图" if total else "等待训练图构建"
    return progress_stage("training_graph", "构建训练图", state, percentage, detail)


def vae_training_stage(
    model: ModelLayout,
    latest_loss: Dict[str, object],
    total_epochs: int,
    percentage: int,
) -> Dict[str, object]:
    if model_is_ready(model):
        state = "done"
    elif latest_loss:
        state = "running"
    else:
        state = "pending"
    return progress_stage(
        "vae_training",
        "训练 VAE",
        state,
        percentage,
        epoch_detail(latest_loss, total_epochs) if latest_loss else "等待训练日志",
    )


def progress_stage(
    key: str,
    label: str,
    status: str,
    percentage: int,
    detail: str,
) -> Dict[str, object]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "status_label": stage_status_label(status),
        "percentage": max(0, min(100, int(percentage))),
        "detail": detail,
    }


def training_metrics(
    *,
    summary: Dict[str, object],
    latest_loss: Dict[str, object],
    total_epochs: int,
    checkpoints: List[Dict[str, object]],
) -> Dict[str, object]:
    best_metrics = object_value(summary.get("best_metrics"))
    latest_epoch = int_value(latest_loss.get("epoch"))
    latest_step = int_value(latest_loss.get("step"))
    latest_loss_value = number_value(latest_loss.get("loss"))
    best_loss = number_value(best_metrics.get("loss"))
    best_epoch = int_value(summary.get("best_epoch"))
    return {
        "latest_epoch": latest_epoch or None,
        "total_epochs": total_epochs or None,
        "latest_step": latest_step or None,
        "latest_loss": latest_loss_value,
        "best_epoch": best_epoch or None,
        "best_loss": best_loss,
        "checkpoint_count": len(checkpoints),
    }


def vae_training_percent(latest_loss: Dict[str, object], total_epochs: int, ready: bool) -> int:
    if ready:
        return 100
    if not latest_loss or not total_epochs:
        return 0
    step = int_value(latest_loss.get("step"))
    total_steps = int_value(latest_loss.get("total_steps"))
    if not step or not total_steps:
        return 0
    return min(99, ratio_percent(step, total_epochs * total_steps))


def training_status(model: ModelLayout, loss_points: List[Dict[str, object]], stages: List[Dict[str, object]]) -> str:
    if model_is_ready(model):
        return "ready"
    if loss_points:
        return "training"
    if any(stage.get("status") == "running" for stage in stages):
        return "graphing"
    if any(int(stage.get("percentage", 0) or 0) > 0 for stage in stages):
        return "incomplete"
    return "idle"


def training_status_label(status: str, stages: List[Dict[str, object]]) -> str:
    if status == "ready":
        return "训练完成"
    if status == "training":
        return "训练 VAE"
    if status == "graphing":
        running = next((stage for stage in stages if stage.get("status") == "running"), None)
        return str(running.get("label")) if running else "构建训练图"
    if status == "incomplete":
        return "训练未完成"
    return "等待训练"


def training_status_detail(status: str, latest_loss: Dict[str, object], total_epochs: int, stages: List[Dict[str, object]]) -> str:
    if status == "ready":
        return "checkpoint 与训练摘要已生成"
    if status == "training":
        return epoch_detail(latest_loss, total_epochs)
    if status == "graphing":
        running = next((stage for stage in stages if stage.get("status") == "running"), None)
        return str(running.get("detail")) if running else "正在构建训练图"
    if status == "incomplete":
        return "已有部分训练产物，但尚未形成可用模型"
    return "点击训练新模型开始"


def epoch_detail(latest_loss: Dict[str, object], total_epochs: int) -> str:
    epoch = int_value(latest_loss.get("epoch"))
    return f"epoch {epoch}/{total_epochs}" if total_epochs else f"epoch {epoch}"


def weighted_percentage(stages: List[Dict[str, object]]) -> int:
    total = 0.0
    for stage in stages:
        key = str(stage.get("key", ""))
        total += STAGE_WEIGHTS.get(key, 0.0) * int(stage.get("percentage", 0) or 0)
    return round(total)


def stage_status_label(status: str) -> str:
    return {
        "done": "完成",
        "running": "运行中",
        "pending": "等待",
        "failed": "失败",
    }.get(status, status)


def graph_status(graph_progress: Dict[str, object], key: str) -> str:
    return str(object_value(graph_progress.get(key)).get("status", "") or "")


def epoch_loss_series(points: List[Dict[str, object]]) -> Dict[str, List[Dict[str, object]]]:
    return {metric: epoch_metric_series(points, metric) for metric in LOSS_METRICS}


def epoch_metric_series(points: List[Dict[str, object]], metric: str) -> List[Dict[str, object]]:
    groups: Dict[int, List[float]] = {}
    last_by_epoch: Dict[int, float] = {}
    for point in points:
        epoch = int_value(point.get("epoch"))
        value = number_value(point.get(metric))
        if not epoch or value is None:
            continue
        groups.setdefault(epoch, []).append(value)
        last_by_epoch[epoch] = value
    rows: List[Dict[str, object]] = []
    for epoch in sorted(groups):
        values = groups[epoch]
        mean = sum(values) / max(len(values), 1)
        rows.append(
            {
                "metric": metric,
                "epoch": epoch,
                "value": mean,
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "last": last_by_epoch.get(epoch, mean),
            }
        )
    return rows


def read_json(path: Path) -> Dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def read_json_if_exists(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_history_summary(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {"count": 0, "latest": {}, "best": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"count": 0, "latest": {}, "best": {}}
    if not isinstance(payload, list):
        return {"count": 0, "latest": {}, "best": {}}
    records = [item for item in payload if isinstance(item, dict)]
    best = min(
        (item for item in records if isinstance(item.get("loss"), (int, float))),
        key=lambda item: float(item["loss"]),
        default={},
    )
    return {
        "count": len(records),
        "latest": records[-1] if records else {},
        "best": best,
    }


def read_loss_history(path: Path) -> List[Dict[str, object]]:
    if not path.is_file():
        return []
    points: List[Dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        point = normalize_loss_point(payload)
        if point:
            points.append(point)
    return points


def normalize_loss_point(payload: Dict[str, Any]) -> Dict[str, object]:
    try:
        point: Dict[str, object] = {
            "step": int(payload["step"]),
            "epoch": int(payload["epoch"]),
            "epoch_step": int(payload["epoch_step"]),
            "total_steps": int(payload["total_steps"]),
            "loss": float(payload["loss"]),
        }
    except (KeyError, TypeError, ValueError):
        return {}
    for key in ("count_loss", "anchor_loss", "param_loss", "kl", "elapsed"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            point[key] = float(value)
    return point


def read_text_tail(path: Path, *, tail_lines: int) -> str:
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-tail_lines:])


def checkpoint_role_paths(model: ModelLayout, summary: Dict[str, object]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    best_checkpoint = checkpoint_relative_path(model, summary.get("best_checkpoint") or summary.get("best_model"))
    last_checkpoint = checkpoint_relative_path(model, summary.get("last_checkpoint") or summary.get("last_model"))
    if best_checkpoint:
        result["best"] = best_checkpoint
    elif (model.root / "best_model.pt").is_file():
        result["best"] = "best_model.pt"
    if last_checkpoint:
        result["last"] = last_checkpoint
    elif (model.root / "last_model.pt").is_file():
        result["last"] = "last_model.pt"
    return result


def checkpoint_relative_path(model: ModelLayout, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute():
        try:
            return to_posix(path.resolve().relative_to(model.root.resolve()))
        except ValueError:
            return ""
    return to_posix(path)


def checkpoint_roles(relative_path: str, filename: str, role_paths: Dict[str, str]) -> List[str]:
    roles: List[str] = []
    if relative_path == role_paths.get("best") or filename == "best_model.pt":
        roles.append("best")
    if relative_path == role_paths.get("last") or filename == "last_model.pt":
        roles.append("last")
    return roles


def model_is_ready(model: ModelLayout) -> bool:
    summary = read_json_if_exists(model.root / "training_summary.json")
    role_paths = checkpoint_role_paths(model, summary)
    return (
        (model.root / "training_summary.json").is_file()
        and (model.root / "training_config.json").is_file()
        and (model.root / "schema_summary.json").is_file()
        and any((model.root / path).is_file() for path in role_paths.values())
    )


def object_value(value: object) -> Dict[str, object]:
    return value if isinstance(value, dict) else {}


def number_value(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else 0
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def ratio_percent(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return max(0, min(100, round((numerator / denominator) * 100)))

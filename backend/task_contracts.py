from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping

from backend.analysis.timetable import export_dataset_timetables
from backend.scenarios import add_scenario, create_scenario_set, delete_scenario, normal_generate
from core.project_layout import ProjectLayout, require_id, sanitize_id
from core.vae_learning_graph import (
    DEFAULT_EVENT_TIME_WINDOW,
    DEFAULT_EVENT_TOP_K,
    DEFAULT_MAX_SLOTS,
    DEFAULT_SECTION_ORDER_WINDOW,
    DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
)
from backend.workflow import build_dataset, create_dataset, delete_project, generate_scenarios, new_project, solve_dataset, train_model


TASK_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "newproject": {},
    "deleteproject": {},
    "scenario_set_create": {"exist_ok": False},
    "scenario_add": {"delays": [], "speed_limits": [], "overwrite": False},
    "scenario_delete": {},
    "normal_generate": {
        "scenario_id_prefix": "sim",
        "simulation_count": 1,
        "source_timetable_path": "",
        "source_mileage_path": "",
        "seed": 20260320,
        "delay_count": 10,
        "speed_count": 10,
        "interruption_count": 10,
        "combo_per_type": 10,
        "overwrite": True,
    },
    "dataset_create": {"exist_ok": False},
    "build": {
        "scenario_id": "",
        "objective_delay_weight": 1.0,
        "objective_mode": "abs",
        "cancellation_enabled": False,
        "cancellation_penalty_weight": 1000.0,
        "arr_arr_headway_seconds": 180,
        "dep_dep_headway_seconds": 180,
        "dwell_seconds_at_stops": 120,
        "big_m": 100000,
        "tolerance_delay_seconds": 7200,
    },
    "solve": {
        "case_id": "",
        "limit": 0,
        "time_limit": 120.0,
        "mip_gap": 0.0,
        "threads": 0,
        "skip_solved": False,
    },
    "export_timetable": {
        "case_id": "",
        "limit": 0,
    },
    "train": {
        "max_slots": DEFAULT_MAX_SLOTS,
        "event_time_window": DEFAULT_EVENT_TIME_WINDOW,
        "event_top_k": DEFAULT_EVENT_TOP_K,
        "section_order_window": DEFAULT_SECTION_ORDER_WINDOW,
        "hidden_dim": 64,
        "latent_dim": 16,
        "message_passing_steps": 2,
        "epochs": 800,
        "batch_size": 8,
        "lr": 0.0003,
        "seed": 1,
        "device": "auto",
        "log_every": 1,
        "count_weight": 1.0,
        "anchor_weight": 1.0,
        "param_weight": 2.0,
        "kl_weight": 0.0015,
        "relation_weight": 0.5,
    },
    "generation": {
        "source_scenario_set_id": "",
        "source_timetable_path": "",
        "source_mileage_path": "",
        "output_prefix": "generated",
        "num_samples": 100,
        "seed": 1,
        "device": "auto",
        "speed_interruption_threshold": DEFAULT_SPEED_INTERRUPTION_THRESHOLD,
        "overwrite": False,
    },
}

TASK_REQUIRED: Dict[str, tuple[str, ...]] = {
    "newproject": (),
    "deleteproject": (),
    "scenario_set_create": ("scenario_set_id",),
    "scenario_add": ("scenario_set_id", "scenario_id"),
    "scenario_delete": ("scenario_set_id", "scenario_id"),
    "normal_generate": ("scenario_set_id",),
    "dataset_create": ("dataset_id",),
    "build": ("scenario_set_id", "dataset_id"),
    "solve": ("dataset_id",),
    "export_timetable": ("dataset_id",),
    "train": ("model_id", "scenario_set_id"),
    "generation": ("model_id", "checkpoint", "scenario_set_id"),
}


def task_default(action: str, key: str) -> Any:
    return TASK_DEFAULTS[action][key]


def normalize_project_id(project_id: object) -> str:
    return require_id(project_id, "project_id")


def normalize_task_params(action: str, params: Mapping[str, Any] | None) -> Dict[str, Any]:
    if action not in TASK_DEFAULTS:
        raise ValueError(f"Unsupported task action: {action}")

    normalized = dict(TASK_DEFAULTS[action])
    for key, value in dict(params or {}).items():
        if value is None and key in normalized:
            continue
        normalized[key] = value

    for key in TASK_REQUIRED[action]:
        if not str(normalized.get(key, "") or "").strip():
            raise ValueError(f"Missing required task field: {key}")

    for key, value in list(normalized.items()):
        if key.endswith("_id"):
            text = str(value or "").strip()
            normalized[key] = require_id(text, key) if text else ""

    validate_task_params(action, normalized)
    return normalized


def validate_task_params(action: str, params: Mapping[str, Any]) -> None:
    if action == "normal_generate":
        has_path_pair = bool(str(params.get("source_timetable_path") or "").strip()) and bool(
            str(params.get("source_mileage_path") or "").strip()
        )
        if not has_path_pair:
            raise ValueError("normal_generate requires uploaded timetable and mileage source paths")
        return
    if action == "generation":
        has_category_source = bool(str(params.get("source_scenario_set_id") or "").strip())
        has_upload_source = bool(str(params.get("source_timetable_path") or "").strip()) or bool(
            str(params.get("source_mileage_path") or "").strip()
        )
        if has_category_source == has_upload_source:
            raise ValueError("generation requires exactly one context source: source_scenario_set_id or uploaded source files")
        if has_upload_source:
            has_path_pair = bool(str(params.get("source_timetable_path") or "").strip()) and bool(
                str(params.get("source_mileage_path") or "").strip()
            )
            if not has_path_pair:
                raise ValueError("generation uploaded context source requires timetable and mileage source paths")
        return
    if action != "build":
        return
    objective_mode = str(params.get("objective_mode", "") or "").strip()
    if objective_mode not in {"abs", "delay"}:
        raise ValueError("build.objective_mode must be one of: abs, delay")
    require_positive_float(params, "objective_delay_weight")
    require_non_negative_float(params, "cancellation_penalty_weight")
    require_positive_int(params, "arr_arr_headway_seconds")
    require_positive_int(params, "dep_dep_headway_seconds")
    require_positive_int(params, "dwell_seconds_at_stops")
    require_positive_int(params, "big_m")
    require_positive_int(params, "tolerance_delay_seconds")


def require_positive_float(params: Mapping[str, Any], key: str) -> None:
    value = numeric_param(params, key)
    if value <= 0:
        raise ValueError(f"build.{key} must be > 0")


def require_non_negative_float(params: Mapping[str, Any], key: str) -> None:
    value = numeric_param(params, key)
    if value < 0:
        raise ValueError(f"build.{key} must be >= 0")


def require_positive_int(params: Mapping[str, Any], key: str) -> None:
    value = numeric_param(params, key)
    if value <= 0 or int(value) != value:
        raise ValueError(f"build.{key} must be a positive integer")


def numeric_param(params: Mapping[str, Any], key: str) -> float:
    try:
        value = float(params[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"build.{key} must be a finite number") from exc
    if not math.isfinite(value):
        raise ValueError(f"build.{key} must be a finite number")
    return value


def run_task_payload(payload: Mapping[str, Any]) -> None:
    action = required_payload_text(payload, "action")
    project_id = normalize_project_id(payload.get("project_id"))
    raw_params = payload.get("params", {})
    if not isinstance(raw_params, Mapping):
        raise ValueError("Task params must be a JSON object.")

    params = normalize_task_params(action, raw_params)
    layout = ProjectLayout.from_name(project_id)
    print_task_header(action, layout, params)
    execute_task(action, layout, params)


def execute_task(action: str, layout: ProjectLayout, params: Mapping[str, Any]) -> None:
    if action == "newproject":
        new_project(layout)
    elif action == "deleteproject":
        delete_project(layout, force=True)
    elif action == "scenario_set_create":
        create_scenario_set(
            layout,
            text_param(params, "scenario_set_id"),
            exist_ok=bool_param(params, "exist_ok"),
        )
    elif action == "scenario_add":
        add_scenario(
            layout,
            text_param(params, "scenario_set_id"),
            text_param(params, "scenario_id"),
            delays=list_param(params, "delays"),
            speed_limits=list_param(params, "speed_limits"),
            overwrite=bool_param(params, "overwrite"),
        )
    elif action == "scenario_delete":
        delete_scenario(
            layout,
            text_param(params, "scenario_set_id"),
            text_param(params, "scenario_id"),
        )
    elif action == "normal_generate":
        normal_generate(
            layout,
            scenario_set_id=text_param(params, "scenario_set_id"),
            scenario_id_prefix=text_param(params, "scenario_id_prefix"),
            simulation_count=int_param(params, "simulation_count"),
            source_timetable_path=text_param(params, "source_timetable_path"),
            source_mileage_path=text_param(params, "source_mileage_path"),
            seed=int_param(params, "seed"),
            delay_count=int_param(params, "delay_count"),
            speed_count=int_param(params, "speed_count"),
            interruption_count=int_param(params, "interruption_count"),
            combo_per_type=int_param(params, "combo_per_type"),
            overwrite=bool_param(params, "overwrite"),
        )
    elif action == "dataset_create":
        create_dataset(
            layout,
            text_param(params, "dataset_id"),
            exist_ok=bool_param(params, "exist_ok"),
        )
    elif action == "build":
        build_dataset(
            layout,
            text_param(params, "scenario_set_id"),
            text_param(params, "dataset_id"),
            scenario_id=text_param(params, "scenario_id"),
            objective_delay_weight=float_param(params, "objective_delay_weight"),
            objective_mode=text_param(params, "objective_mode"),
            cancellation_enabled=bool_param(params, "cancellation_enabled"),
            cancellation_penalty_weight=float_param(params, "cancellation_penalty_weight"),
            arr_arr_headway_seconds=int_param(params, "arr_arr_headway_seconds"),
            dep_dep_headway_seconds=int_param(params, "dep_dep_headway_seconds"),
            dwell_seconds_at_stops=int_param(params, "dwell_seconds_at_stops"),
            big_m=int_param(params, "big_m"),
            tolerance_delay_seconds=int_param(params, "tolerance_delay_seconds"),
        )
    elif action == "solve":
        solve_dataset(
            layout,
            text_param(params, "dataset_id"),
            case_id=text_param(params, "case_id"),
            limit=int_param(params, "limit"),
            time_limit=float_param(params, "time_limit"),
            mip_gap=float_param(params, "mip_gap"),
            threads=int_param(params, "threads"),
            skip_solved=bool_param(params, "skip_solved"),
        )
    elif action == "export_timetable":
        export_dataset_timetables(
            layout,
            text_param(params, "dataset_id"),
            case_id=text_param(params, "case_id"),
            limit=int_param(params, "limit"),
        )
    elif action == "train":
        train_model(
            layout,
            model_id=text_param(params, "model_id"),
            scenario_set_id=text_param(params, "scenario_set_id"),
            max_slots=int_param(params, "max_slots"),
            event_time_window=int_param(params, "event_time_window"),
            event_top_k=int_param(params, "event_top_k"),
            section_order_window=int_param(params, "section_order_window"),
            hidden_dim=int_param(params, "hidden_dim"),
            latent_dim=int_param(params, "latent_dim"),
            message_passing_steps=int_param(params, "message_passing_steps"),
            epochs=int_param(params, "epochs"),
            batch_size=int_param(params, "batch_size"),
            lr=float_param(params, "lr"),
            seed=int_param(params, "seed"),
            device=text_param(params, "device"),
            log_every=int_param(params, "log_every"),
            count_weight=float_param(params, "count_weight"),
            anchor_weight=float_param(params, "anchor_weight"),
            param_weight=float_param(params, "param_weight"),
            kl_weight=float_param(params, "kl_weight"),
            relation_weight=float_param(params, "relation_weight"),
        )
    elif action == "generation":
        generate_scenarios(
            layout,
            model_id=text_param(params, "model_id"),
            checkpoint=text_param(params, "checkpoint"),
            scenario_set_id=text_param(params, "scenario_set_id"),
            source_scenario_set_id=text_param(params, "source_scenario_set_id"),
            source_timetable_path=text_param(params, "source_timetable_path"),
            source_mileage_path=text_param(params, "source_mileage_path"),
            output_prefix=text_param(params, "output_prefix"),
            num_samples=int_param(params, "num_samples"),
            seed=int_param(params, "seed"),
            device=text_param(params, "device"),
            speed_interruption_threshold=float_param(params, "speed_interruption_threshold"),
            overwrite=bool_param(params, "overwrite"),
        )
    else:
        raise ValueError(f"Unsupported task action: {action}")


def print_task_header(action: str, layout: ProjectLayout, params: Mapping[str, Any]) -> None:
    print(f"Task action: {action}")
    print(f"Project: {layout.name}")
    print("Parameters:")
    print(json.dumps(dict(params), ensure_ascii=False, indent=2, sort_keys=True))


def required_payload_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key, "") or "").strip()
    if not value:
        raise ValueError(f"Missing required task field: {key}")
    return value


def text_param(params: Mapping[str, Any], key: str) -> str:
    return str(params.get(key, "") or "").strip()


def bool_param(params: Mapping[str, Any], key: str) -> bool:
    value = params.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def int_param(params: Mapping[str, Any], key: str) -> int:
    return int(params[key])


def float_param(params: Mapping[str, Any], key: str) -> float:
    return float(params[key])


def list_param(params: Mapping[str, Any], key: str) -> list[Any]:
    value = params.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"Task field must be a list: {key}")
    return value


def read_task_input(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Task input must be a JSON object: {path}")
    return payload

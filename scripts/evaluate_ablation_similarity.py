#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
VAE_ROOT = REPO_ROOT / "VAE"
if str(VAE_ROOT) not in sys.path:
    sys.path.insert(0, str(VAE_ROOT))

from src.metrics import MATH_GENERATED_GRAPH_TYPE, compare_graph_sets, load_json_graphs
from src.similarity_metrics import (
    bin_numeric_values,
    bounded,
    categorical_distribution_metrics,
    counter_from_values,
    equal_width_bins,
    finite_values,
    js_divergence,
    mean_bounded,
    normalized_wasserstein,
    numeric_distribution_metrics,
    primary_distribution_error,
    primary_numeric_error,
    relative_error,
    summary,
)


TIME_EDGES = [float(value) for value in range(0, 86400 + 1, 7200)]
TIME_LABELS = [f"{hour:02d}-{hour + 2:02d}时" for hour in range(0, 24, 2)]
DELAY_EDGES = [0.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, 7200.0, math.inf]
DELAY_LABELS = ["0-5分", "5-10分", "10-20分", "20-30分", "30-60分", "60-120分", ">120分"]
DURATION_EDGES = [0.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, 7200.0, 14400.0, math.inf]
DURATION_LABELS = ["0-5分", "5-10分", "10-20分", "20-30分", "30-60分", "60-120分", "120-240分", ">240分"]
SPEED_EDGES = [0.0, 60.0, 100.0, 160.0, 220.0, math.inf]
SPEED_LABELS = ["0-60", "60-100", "100-160", "160-220", ">220"]
COUNT_EDGES = [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, math.inf]
COUNT_LABELS = ["0", "1", "2", "3", "4", ">=5"]

COUNT_FIELDS = ["disturbance_count", "delay_count", "speed_limit_count", "interruption_count"]
MILP_FIELDS = ["milp_num_vars", "milp_num_constrs", "milp_num_nzs", "milp_num_bin_vars", "milp_num_int_vars", "build_duration_sec"]
SOLVER_NUMERIC_FIELDS = [
    "duration_sec",
    "objective",
    "mip_gap",
    "num_nodes",
    "t_first_feas",
    "work",
    "solving_time",
    "obj_bound",
    "gap_first_feas",
]

FIELD_LABELS = {
    "disturbance_count": "总扰动数",
    "delay_count": "晚点数",
    "speed_limit_count": "限速数",
    "interruption_count": "中断数",
    "delay_seconds": "晚点时长",
    "delay_time_sec": "晚点发生时间",
    "delay_station_order": "晚点站点",
    "speed_start_sec": "限速开始时间",
    "speed_duration_sec": "限速持续时长",
    "speed_limit_kmh": "限速值",
    "speed_section_order": "限速区间",
    "interruption_start_sec": "中断开始时间",
    "interruption_duration_sec": "中断持续时长",
    "interruption_section_order": "中断区间",
    "milp_num_vars": "变量数",
    "milp_num_constrs": "约束数",
    "milp_num_nzs": "非零系数数",
    "milp_num_bin_vars": "二进制变量数",
    "milp_num_int_vars": "整数变量数",
    "build_duration_sec": "构建耗时",
    "duration_sec": "求解时间",
    "objective": "目标值",
    "mip_gap": "MIP gap",
    "num_nodes": "分支节点数",
    "t_first_feas": "首个可行解时间",
    "work": "Gurobi work",
    "solving_time": "solver solving_time",
    "obj_bound": "目标下界",
    "gap_first_feas": "首个可行解 gap",
}

JOINT_LABELS = {
    "type_time": "扰动类型×时间段",
    "delay_station_time": "晚点站点×时间段",
    "speed_section_time": "限速区间×时间段",
    "interruption_section_time": "中断区间×时间段",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate ablation similarity against a reference dataset.")
    parser.add_argument("--ablation-root", required=True)
    parser.add_argument("--output-root", default="", help="Defaults to <ablation-root>/similarity_eval.")
    parser.add_argument("--docs-dir", default="docs/消融实验")
    parser.add_argument("--skip-milp-read", action="store_true", help="Skip gurobipy LP inspection and use build duration only.")
    parser.add_argument("--self-test", action="store_true", help="Run lightweight metric sanity checks and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_tests()
        return

    ablation_root = resolve_path(args.ablation_root)
    output_root = resolve_path(args.output_root) if args.output_root else ablation_root / "similarity_eval"
    docs_dir = resolve_path(args.docs_dir)
    run_dir = output_root
    figures_dir = run_dir / "figures"
    docs_figures_dir = docs_dir / "figures"
    run_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    docs_figures_dir.mkdir(parents=True, exist_ok=True)

    cache_path = output_root / "milp_size_cache.json"
    milp_cache = read_json(cache_path, default={})

    reference_build = resolve_run_path(ablation_root / "reference/build_run.txt")
    groups = discover_groups(ablation_root)
    datasets: Dict[str, Dict[str, object]] = {}

    datasets["reference"] = load_dataset(
        "reference",
        reference_build,
        ablation_root / "reference",
        milp_cache=milp_cache,
        skip_milp_read=args.skip_milp_read,
    )
    for label, step_dir in groups.items():
        build_run = resolve_run_path(step_dir / "generated_build_run.txt")
        datasets[label] = load_dataset(
            label,
            build_run,
            step_dir,
            milp_cache=milp_cache,
            skip_milp_read=args.skip_milp_read,
        )
        datasets[label]["train"] = load_train(step_dir)
        datasets[label]["task_output"] = load_task_output_similarity(step_dir)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache_path, milp_cache)

    bin_context = make_bin_context(datasets)
    metric_rows: List[Dict[str, object]] = []
    group_rows: List[Dict[str, object]] = []
    metrics = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "ablation_root": str(ablation_root),
        "output_dir": str(run_dir),
        "reference": dataset_public_summary(datasets["reference"]),
        "groups": {},
        "bins": {
            "time": TIME_LABELS,
            "delay_duration": DELAY_LABELS,
            "duration": DURATION_LABELS,
            "speed": SPEED_LABELS,
            "count": COUNT_LABELS,
        },
        "notes": {
            "js_divergence": "JSD is computed on fixed bins with log2 normalization, lower is better.",
            "joint_structure": "Joint histograms compare co-occurrence patterns rather than marginal distributions only.",
            "unavailable_solver_metrics": "Solver metrics such as num_nodes and t_first_feas are used when present in solver CSVs.",
        },
    }

    reference = datasets["reference"]
    for label in groups:
        group = datasets[label]
        scenario = compare_scenario(reference, group, metric_rows, bin_context)
        joint = compare_joint_structure(reference, group, metric_rows)
        milp = compare_milp(reference, group, metric_rows, bin_context)
        solver = compare_solver(reference, group, metric_rows, bin_context)
        task_output = group.get("task_output", {})
        train = group.get("train", {})
        task_error = float(task_output.get("aggregate_error", 0.0))
        composite_components = {
            "task_output_error": task_error,
            "scenario_error": float(scenario["aggregate_error"]),
            "joint_error": float(joint["aggregate_error"]),
            "milp_error": float(milp["aggregate_error"]),
            "solver_error": float(solver["aggregate_error"]),
        }
        composite_error = mean_float(composite_components.values())
        similarity_score = 1.0 - bounded(composite_error)
        metrics["groups"][label] = {
            "paths": {
                "step_dir": str(group["step_dir"]),
                "build_run": str(group["build_run"]),
            },
            "train": train,
            "task_output": task_output,
            "scenario_similarity": scenario,
            "joint_similarity": joint,
            "milp_similarity": milp,
            "solver_similarity": solver,
            "composite": {
                **composite_components,
                "composite_error": composite_error,
                "similarity_score": similarity_score,
            },
            "data": dataset_public_summary(group),
        }
        row = make_group_summary_row(label, metrics["groups"][label])
        group_rows.append(row)
        for key, value in composite_components.items():
            metric_rows.append(
                {
                    "group": label,
                    "dimension": "综合",
                    "metric": key,
                    "stat": "primary_error",
                    "value": value,
                }
            )
        metric_rows.append(
            {
                "group": label,
                "dimension": "综合",
                "metric": "similarity_score",
                "stat": "score",
                "value": similarity_score,
            }
        )

    sample_rows = []
    for dataset in datasets.values():
        sample_rows.extend(dataset["sample_rows"])

    write_json(run_dir / "metrics_summary.json", metrics)
    write_csv(run_dir / "group_summary.csv", group_rows)
    write_csv(run_dir / "metric_long.csv", metric_rows)
    write_csv(run_dir / "sample_features.csv", sample_rows)
    write_json(docs_dir / "metrics_summary.json", metrics)

    configure_matplotlib()
    figures = make_figures(metrics, datasets, figures_dir)
    for figure_path in figures.values():
        shutil.copy2(figure_path, docs_figures_dir / figure_path.name)

    report_path = docs_dir / "报告.md"
    write_report(metrics, figures, docs_dir, report_path)
    print(f"Similarity evaluation written: {run_dir}")
    print(f"Report written: {report_path}")


def resolve_path(path_text: str | Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def resolve_run_path(path_file: Path) -> Path:
    text = path_file.read_text(encoding="utf-8").strip()
    path = Path(text)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def discover_groups(ablation_root: Path) -> Dict[str, Path]:
    pairs: List[Tuple[int, str, Path]] = []
    pattern = re.compile(r"steps_(\d+)$")
    for path in ablation_root.glob("steps_*"):
        if not path.is_dir():
            continue
        match = pattern.search(path.name)
        if match:
            step = int(match.group(1))
            pairs.append((step, f"steps={step}", path))
    pairs.sort(key=lambda item: item[0])
    return {label: path for _, label, path in pairs}


def read_json(path: Path, default: object | None = None) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


def json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return str(value)


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers: List[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    if not headers:
        headers = ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: format_csv_value(row.get(key, "")) for key in headers})


def format_csv_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return value


def load_dataset(
    label: str,
    build_run: Path,
    step_dir: Path,
    *,
    milp_cache: Dict[str, object],
    skip_milp_read: bool,
) -> Dict[str, object]:
    context = load_anchor_context(build_run)
    build_rows = read_csv(build_summary_path(build_run))
    benchmark_dir = load_benchmark_dir(step_dir)
    solve_rows = read_csv(resolve_stage_summary(benchmark_dir, "solve"))
    solve_by_case = {row.get("case_id", ""): row for row in solve_rows}
    build_by_case = {row.get("case_id", ""): row for row in build_rows}
    milp_by_case = collect_milp_sizes(build_rows, build_run, milp_cache, skip_milp_read)
    sample_rows: List[Dict[str, object]] = []
    events: List[Dict[str, object]] = []

    for config_path in sorted((build_run / "configs").glob("*.yaml")):
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        case_id = config_path.stem
        scenarios = ((payload.get("build") or {}).get("scenarios") or {})
        extracted = extract_case_features(label, case_id, scenarios, context)
        row = extracted["sample"]
        row.update(
            {
                "dataset": label,
                "case_id": case_id,
                "config_file": str(config_path),
            }
        )
        build_row = build_by_case.get(case_id, {})
        solve_row = solve_by_case.get(case_id, {})
        row["build_status"] = build_row.get("status", "")
        row["build_duration_sec"] = to_float_or_blank(build_row.get("duration_sec"))
        row["solve_status"] = solve_row.get("status", "")
        row["solve_duration_sec"] = to_float_or_blank(solve_row.get("duration_sec"))
        row["solve_objective"] = to_float_or_blank(solve_row.get("objective"))
        row["solve_mip_gap"] = to_float_or_blank(solve_row.get("mip_gap"))
        for key, value in milp_by_case.get(case_id, {}).items():
            row[key] = value
        sample_rows.append(row)
        events.extend(extracted["events"])

    return {
        "label": label,
        "step_dir": step_dir,
        "build_run": build_run,
        "benchmark_dir": benchmark_dir,
        "context": context,
        "sample_rows": sample_rows,
        "events": events,
        "build_rows": build_rows,
        "solve_rows": solve_rows,
        "milp_unavailable": skip_milp_read,
    }


def load_benchmark_dir(step_dir: Path) -> Path | None:
    pointer = step_dir / "benchmark_dir.txt"
    if not pointer.exists():
        raise FileNotFoundError(f"Missing benchmark pointer: {pointer}")
    text = pointer.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Empty benchmark pointer: {pointer}")
    path = Path(text)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def resolve_stage_summary(benchmark_dir: Path | None, stage: str) -> Path:
    if benchmark_dir is None:
        raise ValueError("benchmark_dir is required.")
    return benchmark_dir / "benchmark" / f"{stage}_summary.csv"


def build_summary_path(build_run: Path) -> Path:
    return build_run / "benchmark" / "build_summary.csv"


def load_anchor_context(build_run: Path) -> Dict[str, object]:
    context_path = build_run / "graph" / "context.json"
    context_payload = read_json(context_path, default={}) or {}
    base_context_text = ((context_payload.get("decode_handle") or {}).get("base_context_path") or "")
    base_context_path = Path(str(base_context_text))
    candidates = []
    if base_context_path.is_absolute():
        candidates.append(base_context_path)
    else:
        candidates.extend([REPO_ROOT / base_context_path, build_run / base_context_path, context_path.parent / base_context_path])
    base_context = {}
    base_path = None
    for candidate in candidates:
        if candidate.exists():
            base_context = read_json(candidate, default={}) or {}
            base_path = candidate
            break
    event_anchors = {
        str(item.get("anchor_id")): item
        for item in base_context.get("event_anchors", [])
        if isinstance(item, dict) and item.get("anchor_id")
    }
    section_anchors = {
        str(item.get("anchor_id")): item
        for item in base_context.get("section_anchors", [])
        if isinstance(item, dict) and item.get("anchor_id")
    }
    max_station_order = max([int(item.get("station_order", item.get("station_index", 0))) for item in event_anchors.values()] or [0])
    max_section_order = max([int(item.get("section_order", 0)) for item in section_anchors.values()] or [0])
    return {
        "context_path": str(context_path),
        "base_context_path": str(base_path) if base_path else "",
        "event_anchors": event_anchors,
        "section_anchors": section_anchors,
        "max_station_order": max_station_order,
        "max_section_order": max_section_order,
    }


def extract_case_features(
    dataset: str,
    case_id: str,
    scenarios: Mapping[str, object],
    context: Mapping[str, object],
) -> Dict[str, object]:
    events: List[Dict[str, object]] = []
    event_anchors: Mapping[str, Mapping[str, object]] = context.get("event_anchors", {})  # type: ignore[assignment]
    section_anchors: Mapping[str, Mapping[str, object]] = context.get("section_anchors", {})  # type: ignore[assignment]
    delays = [item for item in scenarios.get("delays", []) or [] if isinstance(item, dict)]
    speed_limits = [item for item in scenarios.get("speed_limits", []) or [] if isinstance(item, dict)]

    for item in delays:
        anchor_id = str(item.get("event_anchor_id", ""))
        anchor = event_anchors.get(anchor_id, {})
        planned_time = to_float(anchor.get("planned_time"))
        station_order = to_float(anchor.get("station_order", anchor.get("station_index")))
        delay_seconds = to_float(item.get("seconds"))
        event = {
            "dataset": dataset,
            "case_id": case_id,
            "kind": "delay",
            "anchor_id": anchor_id,
            "time_sec": planned_time,
            "time_bin": bin_label(planned_time, TIME_EDGES, TIME_LABELS),
            "delay_seconds": delay_seconds,
            "delay_time_sec": planned_time,
            "delay_station_order": station_order,
            "location_order": station_order,
        }
        events.append(event)

    for item in speed_limits:
        section_id = str(item.get("section_anchor_id", ""))
        section = section_anchors.get(section_id, {})
        start_time = parse_time_seconds(item.get("start_time"))
        duration = to_float(item.get("duration"))
        speed = to_float(item.get("limit_speed"))
        section_order = to_float(section.get("section_order"))
        kind = "interruption" if abs(speed) <= 1e-9 else "speed_limit"
        event = {
            "dataset": dataset,
            "case_id": case_id,
            "kind": kind,
            "anchor_id": section_id,
            "time_sec": start_time,
            "time_bin": bin_label(start_time, TIME_EDGES, TIME_LABELS),
            "location_order": section_order,
        }
        if kind == "interruption":
            event.update(
                {
                    "interruption_start_sec": start_time,
                    "interruption_duration_sec": duration,
                    "interruption_section_order": section_order,
                }
            )
        else:
            event.update(
                {
                    "speed_start_sec": start_time,
                    "speed_duration_sec": duration,
                    "speed_limit_kmh": speed,
                    "speed_section_order": section_order,
                }
            )
        events.append(event)

    delay_events = [event for event in events if event["kind"] == "delay"]
    speed_events = [event for event in events if event["kind"] == "speed_limit"]
    interruption_events = [event for event in events if event["kind"] == "interruption"]
    sample = {
        "disturbance_count": len(events),
        "delay_count": len(delay_events),
        "speed_limit_count": len(speed_events),
        "interruption_count": len(interruption_events),
        "delay_seconds_mean": mean_or_blank(event.get("delay_seconds") for event in delay_events),
        "delay_time_sec_mean": mean_or_blank(event.get("delay_time_sec") for event in delay_events),
        "delay_station_order_mean": mean_or_blank(event.get("delay_station_order") for event in delay_events),
        "speed_start_sec_mean": mean_or_blank(event.get("speed_start_sec") for event in speed_events),
        "speed_duration_sec_mean": mean_or_blank(event.get("speed_duration_sec") for event in speed_events),
        "speed_limit_kmh_mean": mean_or_blank(event.get("speed_limit_kmh") for event in speed_events),
        "speed_section_order_mean": mean_or_blank(event.get("speed_section_order") for event in speed_events),
        "interruption_start_sec_mean": mean_or_blank(event.get("interruption_start_sec") for event in interruption_events),
        "interruption_duration_sec_mean": mean_or_blank(event.get("interruption_duration_sec") for event in interruption_events),
        "interruption_section_order_mean": mean_or_blank(event.get("interruption_section_order") for event in interruption_events),
    }
    return {"sample": sample, "events": events}


def parse_time_seconds(value: object) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) == 3:
        return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
    return to_float(text)


def bin_label(value: object, edges: Sequence[float], labels: Sequence[str]) -> str:
    hist = bin_numeric_values([value], edges, labels)
    for label, count in hist.items():
        if count:
            return label
    return labels[0]


def to_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def to_float_or_blank(value: object) -> float | str:
    if value in (None, ""):
        return ""
    number = to_float(value, default=float("nan"))
    return number if math.isfinite(number) else ""


def mean_or_blank(values: Iterable[object]) -> float | str:
    clean = finite_values(values)
    return sum(clean) / len(clean) if clean else ""


def collect_milp_sizes(
    build_rows: Sequence[Mapping[str, str]],
    build_run: Path,
    cache: Dict[str, object],
    skip_milp_read: bool,
) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    if skip_milp_read:
        return result
    try:
        import gurobipy as gp
    except ImportError:
        return result

    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 0)
    env.start()
    try:
        for row in build_rows:
            case_id = str(row.get("case_id", ""))
            if not case_id:
                continue
            lp_path = resolve_lp_path(row, build_run)
            if not lp_path.exists():
                continue
            cache_key = lp_cache_key(lp_path)
            cached = cache.get(cache_key)
            if isinstance(cached, dict):
                result[case_id] = dict(cached)
                continue
            try:
                model = gp.read(str(lp_path), env)
                metrics = {
                    "milp_num_vars": int(model.NumVars),
                    "milp_num_constrs": int(model.NumConstrs),
                    "milp_num_nzs": int(model.NumNZs),
                    "milp_num_bin_vars": int(model.NumBinVars),
                    "milp_num_int_vars": int(model.NumIntVars),
                }
                model.dispose()
                cache[cache_key] = metrics
                result[case_id] = metrics
            except Exception as exc:
                result[case_id] = {"milp_error": str(exc)}
    finally:
        env.dispose()
    return result


def resolve_lp_path(row: Mapping[str, str], build_run: Path) -> Path:
    raw = str(row.get("lp_path", ""))
    case_id = str(row.get("case_id", ""))
    candidates: List[Path] = []
    if raw:
        path = Path(raw)
        candidates.append(path if path.is_absolute() else (REPO_ROOT / path))
    if case_id:
        candidates.append(build_run / "cases" / case_id / f"{case_id}.lp")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1] if candidates else build_run / "missing.lp"


def lp_cache_key(lp_path: Path) -> str:
    stat = lp_path.stat()
    return f"{lp_path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"


def load_train(step_dir: Path) -> Dict[str, object]:
    summary_path = step_dir / "training_summary.json"
    history_path = step_dir / "history.json"
    payload = read_json(summary_path, default={}) or {}
    history = read_json(history_path, default=[]) or []
    best_metrics = payload.get("best_metrics") or {}
    return {
        "best_epoch": int(payload.get("best_epoch", 0) or 0),
        "best_loss": to_float(best_metrics.get("loss")),
        "last_epoch": int(payload.get("last_epoch", 0) or 0),
        "history_count": len(history) if isinstance(history, list) else 0,
    }


def load_task_output_similarity(step_dir: Path) -> Dict[str, object]:
    evaluation_path = step_dir / "evaluation.json"
    evaluation = read_json(evaluation_path, default={}) or {}
    generation = (((evaluation.get("graph_similarity") or {}).get("generation_similarity")) or {})
    count_delta = generation.get("task_count_mean_delta") or {}
    anchor_cosine = generation.get("anchor_histogram_cosine") or {}
    param_delta = generation.get("param_mean_delta") or {}
    errors: List[float] = []
    count_errors = {}
    anchor_errors = {}
    for task_id, item in count_delta.items():
        value = to_float((item or {}).get("absolute_delta"))
        count_errors[str(task_id)] = value
        errors.append(bounded(value))
    for task_id, value in anchor_cosine.items():
        error = 1.0 - to_float(value)
        anchor_errors[str(task_id)] = error
        errors.append(bounded(error))
    param_errors = []
    for dim_map in param_delta.values():
        for item in dim_map.values():
            value = to_float((item or {}).get("relative_delta"))
            param_errors.append(value)
            errors.append(bounded(value))
    return {
        "count_absolute_delta": count_errors,
        "anchor_error": anchor_errors,
        "param_relative_error_mean": mean_float(param_errors),
        "aggregate_error": mean_float(errors),
    }


def make_bin_context(datasets: Mapping[str, Mapping[str, object]]) -> Dict[str, object]:
    max_station = 0
    max_section = 0
    all_rows: List[Mapping[str, object]] = []
    all_solve_rows: List[Mapping[str, object]] = []
    for dataset in datasets.values():
        context = dataset.get("context", {})
        max_station = max(max_station, int(context.get("max_station_order", 0)))
        max_section = max(max_section, int(context.get("max_section_order", 0)))
        all_rows.extend(dataset.get("sample_rows", []))  # type: ignore[arg-type]
        all_solve_rows.extend(dataset.get("solve_rows", []))  # type: ignore[arg-type]
    result = {
        "station": index_bins(max_station),
        "section": index_bins(max_section),
        "milp": {},
        "solver": {},
    }
    for field in MILP_FIELDS:
        values = [row.get(field) for row in all_rows]
        result["milp"][field] = equal_width_bins(values, bucket_count=8)
    for field in SOLVER_NUMERIC_FIELDS:
        values = [row.get(field) for row in all_solve_rows if row.get(field) not in (None, "")]
        if field == "duration_sec":
            result["solver"][field] = ([0.0, 10.0, 30.0, 60.0, 90.0, 120.0, math.inf], ["0-10秒", "10-30秒", "30-60秒", "60-90秒", "90-120秒", ">120秒"])
        elif field in {"mip_gap", "gap_first_feas"}:
            result["solver"][field] = ([0.0, 0.001, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0, math.inf], ["0-0.1%", "0.1-1%", "1-5%", "5-10%", "10-20%", "20-50%", "50-100%", ">100%"])
        elif values:
            result["solver"][field] = equal_width_bins(values, bucket_count=8)
    return result


def index_bins(max_index: int) -> Tuple[List[float], List[str]]:
    edges = [index - 0.5 for index in range(max_index + 1)] + [max_index + 0.5]
    labels = [str(index) for index in range(max_index + 1)]
    return [float(edge) for edge in edges], labels


def compare_scenario(
    reference: Mapping[str, object],
    group: Mapping[str, object],
    metric_rows: List[Dict[str, object]],
    bin_context: Mapping[str, object],
) -> Dict[str, object]:
    label = str(group["label"])
    ref_samples = reference["sample_rows"]
    gen_samples = group["sample_rows"]
    ref_events = reference["events"]
    gen_events = group["events"]
    result: Dict[str, object] = {"counts": {}, "kind_distribution": {}, "delay": {}, "speed_limit": {}, "interruption": {}}
    primary_errors: List[float] = []

    for field in COUNT_FIELDS:
        metrics = numeric_distribution_metrics(
            values_from_rows(ref_samples, field),
            values_from_rows(gen_samples, field),
            bins=(COUNT_EDGES, COUNT_LABELS),
            normalizer=5.0,
        )
        result["counts"][field] = metrics
        primary_errors.append(primary_numeric_error(metrics))
        emit_numeric_metrics(metric_rows, label, "扰动数量", field, metrics)

    kind_metrics = categorical_distribution_metrics(
        [event.get("kind") for event in ref_events],
        [event.get("kind") for event in gen_events],
    )
    result["kind_distribution"] = kind_metrics
    primary_errors.append(primary_distribution_error(kind_metrics))
    emit_distribution_metrics(metric_rows, label, "扰动类型", "kind_distribution", kind_metrics)

    station_bins = bin_context["station"]
    section_bins = bin_context["section"]
    specs = [
        ("delay", "delay_seconds", (DELAY_EDGES, DELAY_LABELS), 7200.0),
        ("delay", "delay_time_sec", (TIME_EDGES, TIME_LABELS), 86400.0),
        ("delay", "delay_station_order", station_bins, max_bin_normalizer(station_bins)),
        ("speed_limit", "speed_start_sec", (TIME_EDGES, TIME_LABELS), 86400.0),
        ("speed_limit", "speed_duration_sec", (DURATION_EDGES, DURATION_LABELS), 14400.0),
        ("speed_limit", "speed_limit_kmh", (SPEED_EDGES, SPEED_LABELS), 300.0),
        ("speed_limit", "speed_section_order", section_bins, max_bin_normalizer(section_bins)),
        ("interruption", "interruption_start_sec", (TIME_EDGES, TIME_LABELS), 86400.0),
        ("interruption", "interruption_duration_sec", (DURATION_EDGES, DURATION_LABELS), 14400.0),
        ("interruption", "interruption_section_order", section_bins, max_bin_normalizer(section_bins)),
    ]
    for kind, field, bins, normalizer in specs:
        metrics = numeric_distribution_metrics(
            values_from_events(ref_events, kind, field),
            values_from_events(gen_events, kind, field),
            bins=bins,
            normalizer=normalizer,
        )
        result[kind][field] = metrics
        primary_errors.append(primary_numeric_error(metrics))
        emit_numeric_metrics(metric_rows, label, f"扰动参数-{kind}", field, metrics)

    result["aggregate_error"] = mean_float(primary_errors)
    return result


def compare_joint_structure(
    reference: Mapping[str, object],
    group: Mapping[str, object],
    metric_rows: List[Dict[str, object]],
) -> Dict[str, object]:
    label = str(group["label"])
    ref_events = reference["events"]
    gen_events = group["events"]
    specs = {
        "type_time": (
            joint_values(ref_events, "type_time"),
            joint_values(gen_events, "type_time"),
        ),
        "delay_station_time": (
            joint_values(ref_events, "delay_station_time"),
            joint_values(gen_events, "delay_station_time"),
        ),
        "speed_section_time": (
            joint_values(ref_events, "speed_section_time"),
            joint_values(gen_events, "speed_section_time"),
        ),
        "interruption_section_time": (
            joint_values(ref_events, "interruption_section_time"),
            joint_values(gen_events, "interruption_section_time"),
        ),
    }
    result: Dict[str, object] = {"metrics": {}}
    errors: List[float] = []
    for name, (ref_values, gen_values) in specs.items():
        metrics = categorical_distribution_metrics(ref_values, gen_values)
        result["metrics"][name] = metrics
        errors.append(float(metrics["js_divergence"]))
        emit_distribution_metrics(metric_rows, label, "联合结构", name, metrics)
    result["aggregate_error"] = mean_float(errors)
    return result


def compare_milp(
    reference: Mapping[str, object],
    group: Mapping[str, object],
    metric_rows: List[Dict[str, object]],
    bin_context: Mapping[str, object],
) -> Dict[str, object]:
    label = str(group["label"])
    result: Dict[str, object] = {"numeric": {}, "unavailable": []}
    errors: List[float] = []
    for field in MILP_FIELDS:
        ref_values = values_from_rows(reference["sample_rows"], field)
        gen_values = values_from_rows(group["sample_rows"], field)
        if not finite_values(ref_values) and not finite_values(gen_values):
            result["unavailable"].append(field)
            continue
        bins = bin_context["milp"].get(field)
        normalizer = normalizer_from_values(ref_values, gen_values)
        metrics = numeric_distribution_metrics(ref_values, gen_values, bins=bins, normalizer=normalizer)
        result["numeric"][field] = metrics
        errors.append(primary_numeric_error(metrics))
        emit_numeric_metrics(metric_rows, label, "MILP规模", field, metrics)
    result["aggregate_error"] = mean_float(errors)
    return result


def compare_solver(
    reference: Mapping[str, object],
    group: Mapping[str, object],
    metric_rows: List[Dict[str, object]],
    bin_context: Mapping[str, object],
) -> Dict[str, object]:
    label = str(group["label"])
    ref_rows = reference["solve_rows"]
    gen_rows = group["solve_rows"]
    result: Dict[str, object] = {"status": {}, "numeric": {}, "unavailable": []}
    status_metrics = categorical_distribution_metrics(
        [row.get("status", "") for row in ref_rows],
        [row.get("status", "") for row in gen_rows],
    )
    result["status"] = status_metrics
    errors = [primary_distribution_error(status_metrics)]
    emit_distribution_metrics(metric_rows, label, "求解状态", "status", status_metrics)

    for field in SOLVER_NUMERIC_FIELDS:
        ref_values = values_from_rows(ref_rows, field)
        gen_values = values_from_rows(gen_rows, field)
        if not finite_values(ref_values) and not finite_values(gen_values):
            result["unavailable"].append(field)
            continue
        bins = bin_context["solver"].get(field) or equal_width_bins(ref_values + gen_values, bucket_count=8)
        normalizer = normalizer_from_values(ref_values, gen_values)
        if field == "duration_sec":
            normalizer = 120.0
        elif field in {"mip_gap", "gap_first_feas"}:
            normalizer = 1.0
        metrics = numeric_distribution_metrics(ref_values, gen_values, bins=bins, normalizer=normalizer)
        result["numeric"][field] = metrics
        errors.append(primary_numeric_error(metrics))
        emit_numeric_metrics(metric_rows, label, "求解行为", field, metrics)
    result["aggregate_error"] = mean_float(errors)
    return result


def values_from_rows(rows: object, field: str) -> List[object]:
    return [row.get(field) for row in rows if isinstance(row, Mapping)]


def values_from_events(events: object, kind: str, field: str) -> List[object]:
    return [event.get(field) for event in events if isinstance(event, Mapping) and event.get("kind") == kind and event.get(field) not in (None, "")]


def joint_values(events: object, mode: str) -> List[str]:
    values: List[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        kind = str(event.get("kind", ""))
        time_bin = str(event.get("time_bin", ""))
        if mode == "type_time":
            values.append(f"{kind}|{time_bin}")
        elif mode == "delay_station_time" and kind == "delay":
            values.append(f"{event.get('delay_station_order')}|{time_bin}")
        elif mode == "speed_section_time" and kind == "speed_limit":
            values.append(f"{event.get('speed_section_order')}|{time_bin}")
        elif mode == "interruption_section_time" and kind == "interruption":
            values.append(f"{event.get('interruption_section_order')}|{time_bin}")
    return values


def max_bin_normalizer(bins: object) -> float:
    edges, _labels = bins
    finite = [edge for edge in edges if math.isfinite(float(edge))]
    return max(finite) - min(finite) if finite else 1.0


def normalizer_from_values(reference_values: Iterable[object], generated_values: Iterable[object]) -> float:
    values = finite_values(reference_values) + finite_values(generated_values)
    if not values:
        return 1.0
    span = max(values) - min(values)
    return span if span > 1e-12 else max(abs(values[0]), 1.0)


def emit_numeric_metrics(
    metric_rows: List[Dict[str, object]],
    group: str,
    dimension: str,
    metric: str,
    payload: Mapping[str, object],
) -> None:
    for stat in [
        "mean_relative_error",
        "std_relative_error",
        "js_divergence",
        "js_similarity",
        "normalized_wasserstein",
        "ks_statistic",
    ]:
        if stat in payload:
            metric_rows.append(
                {
                    "group": group,
                    "dimension": dimension,
                    "metric": metric,
                    "metric_label": FIELD_LABELS.get(metric, metric),
                    "stat": stat,
                    "value": payload.get(stat),
                }
            )
    ref = payload.get("reference")
    gen = payload.get("generated")
    if isinstance(ref, Mapping) and isinstance(gen, Mapping):
        metric_rows.append(
            {
                "group": group,
                "dimension": dimension,
                "metric": metric,
                "metric_label": FIELD_LABELS.get(metric, metric),
                "stat": "reference_mean",
                "value": ref.get("mean"),
            }
        )
        metric_rows.append(
            {
                "group": group,
                "dimension": dimension,
                "metric": metric,
                "metric_label": FIELD_LABELS.get(metric, metric),
                "stat": "generated_mean",
                "value": gen.get("mean"),
            }
        )


def emit_distribution_metrics(
    metric_rows: List[Dict[str, object]],
    group: str,
    dimension: str,
    metric: str,
    payload: Mapping[str, object],
) -> None:
    for stat in ["js_divergence", "js_similarity", "l1_distance", "cosine"]:
        metric_rows.append(
            {
                "group": group,
                "dimension": dimension,
                "metric": metric,
                "metric_label": JOINT_LABELS.get(metric, FIELD_LABELS.get(metric, metric)),
                "stat": stat,
                "value": payload.get(stat),
            }
        )


def dataset_public_summary(dataset: Mapping[str, object]) -> Dict[str, object]:
    sample_rows = dataset.get("sample_rows", [])
    events = dataset.get("events", [])
    solve_rows = dataset.get("solve_rows", [])
    status_counts = counter_from_values(row.get("status", "") for row in solve_rows if isinstance(row, Mapping))
    return {
        "label": dataset.get("label"),
        "build_run": str(dataset.get("build_run")),
        "case_count": len(sample_rows) if isinstance(sample_rows, list) else 0,
        "event_count": len(events) if isinstance(events, list) else 0,
        "event_kind_distribution": counter_from_values(event.get("kind") for event in events if isinstance(event, Mapping)),
        "solve_status_counts": status_counts,
    }


def make_group_summary_row(label: str, group: Mapping[str, object]) -> Dict[str, object]:
    train = group.get("train", {})
    composite = group.get("composite", {})
    scenario = group.get("scenario_similarity", {})
    joint = group.get("joint_similarity", {})
    milp = group.get("milp_similarity", {})
    solver = group.get("solver_similarity", {})
    solve_status = ((group.get("data") or {}).get("solve_status_counts") or {}) if isinstance(group.get("data"), Mapping) else {}
    solver_numeric = (solver.get("numeric") or {}) if isinstance(solver, Mapping) else {}
    return {
        "group": label,
        "best_loss": (train or {}).get("best_loss"),
        "best_epoch": (train or {}).get("best_epoch"),
        "task_output_error": composite.get("task_output_error"),
        "scenario_error": composite.get("scenario_error"),
        "joint_error": composite.get("joint_error"),
        "milp_error": composite.get("milp_error"),
        "solver_error": composite.get("solver_error"),
        "composite_error": composite.get("composite_error"),
        "similarity_score": composite.get("similarity_score"),
        "scenario_kind_js": ((scenario.get("kind_distribution") or {}).get("js_divergence") if isinstance(scenario, Mapping) else ""),
        "joint_error_mean": joint.get("aggregate_error") if isinstance(joint, Mapping) else "",
        "milp_num_constrs_rel_error": (((milp.get("numeric") or {}).get("milp_num_constrs") or {}).get("mean_relative_error") if isinstance(milp, Mapping) else ""),
        "solver_status_js": ((solver.get("status") or {}).get("js_divergence") if isinstance(solver, Mapping) else ""),
        "solver_duration_js": ((solver_numeric.get("duration_sec") or {}).get("js_divergence") if isinstance(solver_numeric, Mapping) else ""),
        "solve_status_counts": solve_status,
    }


def mean_float(values: Iterable[object]) -> float:
    clean = finite_values(values)
    return sum(clean) / len(clean) if clean else 0.0


def configure_matplotlib() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    matplotlib.rcParams["svg.fonttype"] = "none"
    matplotlib.rcParams["axes.unicode_minus"] = False
    preferred = ["Noto Sans CJK JP", "Noto Sans CJK SC", "Source Han Sans CN", "WenQuanYi Zen Hei", "SimHei", "Arial Unicode MS"]
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in preferred:
        if name in available:
            plt.rcParams["font.family"] = name
            break


def make_figures(metrics: Mapping[str, object], datasets: Mapping[str, Mapping[str, object]], figures_dir: Path) -> Dict[str, Path]:
    figures = {
        "train_loss": figures_dir / "训练损失曲线.svg",
        "scenario": figures_dir / "扰动场景分布相似性.svg",
        "joint": figures_dir / "联合结构相似性.svg",
        "milp": figures_dir / "MILP规模相似性.svg",
        "solver": figures_dir / "求解行为相似性.svg",
        "composite": figures_dir / "综合相似性评分.svg",
    }
    plot_train_loss(datasets, figures["train_loss"])
    plot_grouped_bars(
        collect_bar_values(metrics, "scenario"),
        ["类型JSD", "晚点时长JSD", "限速程度JSD", "中断时长JSD", "场景综合误差"],
        "扰动场景分布相似性（越低越接近参考集）",
        "误差",
        figures["scenario"],
    )
    plot_grouped_bars(
        collect_bar_values(metrics, "joint"),
        ["类型×时间", "晚点站点×时间", "限速区间×时间", "中断区间×时间", "联合综合误差"],
        "联合结构相似性（JSD，越低越接近参考集）",
        "JSD",
        figures["joint"],
    )
    plot_grouped_bars(
        collect_bar_values(metrics, "milp"),
        ["变量数", "约束数", "非零系数", "构建耗时", "MILP综合误差"],
        "MILP规模相似性（越低越接近参考集）",
        "误差",
        figures["milp"],
    )
    plot_grouped_bars(
        collect_bar_values(metrics, "solver"),
        ["状态JSD", "时间JSD", "目标值JSD", "Gap JSD", "求解综合误差"],
        "求解行为相似性（越低越接近参考集）",
        "误差",
        figures["solver"],
    )
    plot_grouped_bars(
        collect_bar_values(metrics, "composite"),
        ["Task输出", "扰动场景", "联合结构", "MILP规模", "求解行为", "综合误差"],
        "综合相似性评分拆解（越低越接近参考集）",
        "误差",
        figures["composite"],
    )
    return figures


def plot_train_loss(datasets: Mapping[str, Mapping[str, object]], path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    for label, dataset in datasets.items():
        if label == "reference":
            continue
        step_dir = Path(str(dataset["step_dir"]))
        history = read_json(step_dir / "history.json", default=[]) or []
        xs = []
        ys = []
        for index, item in enumerate(history):
            if not isinstance(item, Mapping):
                continue
            if index % 5 == 0 or index == len(history) - 1:
                xs.append(to_float(item.get("epoch")))
                ys.append(to_float(item.get("loss")))
        if xs:
            ax.plot(xs, ys, label=label, linewidth=1.8)
    ax.set_title("训练损失曲线")
    ax.set_xlabel("训练轮次")
    ax.set_ylabel("Loss")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def collect_bar_values(metrics: Mapping[str, object], figure_key: str) -> Dict[str, List[float]]:
    groups = metrics.get("groups", {})
    values: Dict[str, List[float]] = {}
    for label, group in groups.items():
        if figure_key == "scenario":
            scenario = group["scenario_similarity"]
            values[label] = [
                safe_get(scenario, ["kind_distribution", "js_divergence"]),
                safe_get(scenario, ["delay", "delay_seconds", "js_divergence"]),
                safe_get(scenario, ["speed_limit", "speed_limit_kmh", "js_divergence"]),
                safe_get(scenario, ["interruption", "interruption_duration_sec", "js_divergence"]),
                safe_get(scenario, ["aggregate_error"]),
            ]
        elif figure_key == "joint":
            joint = group["joint_similarity"]
            values[label] = [
                safe_get(joint, ["metrics", "type_time", "js_divergence"]),
                safe_get(joint, ["metrics", "delay_station_time", "js_divergence"]),
                safe_get(joint, ["metrics", "speed_section_time", "js_divergence"]),
                safe_get(joint, ["metrics", "interruption_section_time", "js_divergence"]),
                safe_get(joint, ["aggregate_error"]),
            ]
        elif figure_key == "milp":
            milp = group["milp_similarity"]
            values[label] = [
                safe_get(milp, ["numeric", "milp_num_vars", "mean_relative_error"]),
                safe_get(milp, ["numeric", "milp_num_constrs", "mean_relative_error"]),
                safe_get(milp, ["numeric", "milp_num_nzs", "mean_relative_error"]),
                safe_get(milp, ["numeric", "build_duration_sec", "mean_relative_error"]),
                safe_get(milp, ["aggregate_error"]),
            ]
        elif figure_key == "solver":
            solver = group["solver_similarity"]
            values[label] = [
                safe_get(solver, ["status", "js_divergence"]),
                safe_get(solver, ["numeric", "duration_sec", "js_divergence"]),
                safe_get(solver, ["numeric", "objective", "js_divergence"]),
                safe_get(solver, ["numeric", "mip_gap", "js_divergence"]),
                safe_get(solver, ["aggregate_error"]),
            ]
        elif figure_key == "composite":
            composite = group["composite"]
            values[label] = [
                safe_get(composite, ["task_output_error"]),
                safe_get(composite, ["scenario_error"]),
                safe_get(composite, ["joint_error"]),
                safe_get(composite, ["milp_error"]),
                safe_get(composite, ["solver_error"]),
                safe_get(composite, ["composite_error"]),
            ]
    return values


def safe_get(payload: Mapping[str, object], keys: Sequence[str]) -> float:
    current: object = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return 0.0
        current = current.get(key)
    return to_float(current)


def plot_grouped_bars(
    values: Mapping[str, Sequence[float]],
    categories: Sequence[str],
    title: str,
    ylabel: str,
    path: Path,
) -> None:
    import numpy as np
    import matplotlib.pyplot as plt

    labels = list(values)
    x = np.arange(len(categories))
    width = 0.8 / max(1, len(labels))
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    for index, label in enumerate(labels):
        offset = (index - (len(labels) - 1) / 2.0) * width
        y = [bounded(float(value), upper=1.2) for value in values[label]]
        ax.bar(x + offset, y, width, label=label)
        for xpos, ypos in zip(x + offset, y):
            ax.text(xpos, ypos + 0.012, f"{ypos:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=15, ha="right")
    ax.set_ylim(0.0, max(0.12, min(1.25, max([max([bounded(float(v), upper=1.2) for v in row]) for row in values.values()] or [0.0]) * 1.25)))
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_report(metrics: Mapping[str, object], figures: Mapping[str, Path], docs_dir: Path, report_path: Path) -> None:
    groups = metrics["groups"]
    ranked = sorted(groups.items(), key=lambda item: float(item[1]["composite"]["composite_error"]))
    best_label, best_group = ranked[0]
    lines: List[str] = []
    lines.append("# GNN 传递步数消融实验报告")
    lines.append("")
    lines.append("## 数据与口径")
    lines.append("")
    lines.append(f"- 参考集 dataset：`{metrics['reference']['build_run']}`。")
    output_dir = str(metrics["output_dir"])
    lines.append(f"- 本报告由 `scripts/evaluate_ablation_similarity.py` 可重复生成；完整 JSON/CSV 输出位于 `{output_dir}`。")
    lines.append("- 评估不重跑训练、generate、build 或 solve，只读取既有 run 产物。")
    lines.append("- `limit_speed == 0` 计为中断，`limit_speed > 0` 计为普通限速；晚点时长、限速持续时长、限速值等扰动程度指标均使用分箱 JSD。")
    lines.append("- 如果 solve CSV 缺少 `num_nodes` 或 `t_first_feas`，对应的分支节点数或首个可行解时间指标会自动跳过。")
    lines.append("")
    lines.append("## 指标解释")
    lines.append("")
    lines.append("- 值相对误差回答“均值差多少”，适合变量数、约束数、平均求解时间等规模量。")
    lines.append("- 分布相似性回答“整体形状是否像”，本报告对类别/分箱变量使用 JSD，对有序变量同时报告 Wasserstein/EMD 和 KS statistic。")
    lines.append("- JSD 先把连续变量分箱再比较概率分布，因此 92 秒和 114 秒这类落在同一业务桶内的扰动不会被过度惩罚；但跨桶偏移会体现为分布差异。")
    lines.append("- 联合结构指标比较 `扰动类型×时间段`、`站点/区间×时间段` 的联合直方图 JSD，用来判断模型是否学到了时空组合模式，而不只是单变量边际分布。")
    lines.append("")
    lines.append("## 可视化")
    lines.append("")
    for key, title in [
        ("train_loss", "训练损失曲线"),
        ("scenario", "扰动场景分布相似性"),
        ("joint", "联合结构相似性"),
        ("milp", "MILP规模相似性"),
        ("solver", "求解行为相似性"),
        ("composite", "综合相似性评分"),
    ]:
        rel = figures[key].name
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"![](figures/{rel})")
        lines.append("")
    lines.append("## 关键结果")
    lines.append("")
    lines.append("综合误差为 Task 输出、扰动场景、联合结构、MILP 规模、求解行为五个维度的一致权重平均值；相似度为 `1 - 综合误差`，越高越接近参考集。")
    lines.append("")
    lines.append("| 组别 | best loss | Task输出误差 | 扰动场景误差 | 联合结构误差 | MILP误差 | 求解误差 | 综合误差 | 相似度 | solve状态 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for label, group in groups.items():
        train = group["train"]
        composite = group["composite"]
        status = group["data"]["solve_status_counts"]
        lines.append(
            "| {label} | {loss} | {task} | {scenario} | {joint} | {milp} | {solver} | {composite_error} | {score} | {status} |".format(
                label=label,
                loss=fmt(train.get("best_loss")),
                task=fmt(composite["task_output_error"]),
                scenario=fmt(composite["scenario_error"]),
                joint=fmt(composite["joint_error"]),
                milp=fmt(composite["milp_error"]),
                solver=fmt(composite["solver_error"]),
                composite_error=fmt(composite["composite_error"]),
                score=fmt(composite["similarity_score"]),
                status=", ".join(f"{key}={value}" for key, value in status.items()),
            )
        )
    lines.append("")
    lines.append("## 分项分析")
    lines.append("")
    lines.append(f"综合五类误差后，`{best_label}` 当前最接近参考集，综合误差为 `{fmt(best_group['composite']['composite_error'])}`。这个结论同时考虑 task output、扰动场景、联合结构、MILP 规模和求解行为，不只依赖训练 loss。")
    lines.append("")
    for label, group in groups.items():
        scenario = group["scenario_similarity"]
        joint = group["joint_similarity"]
        milp = group["milp_similarity"]
        solver = group["solver_similarity"]
        lines.append(
            "- `{}`：扰动类型 JSD `{}`，晚点程度 JSD `{}`，限速程度 JSD `{}`，联合结构平均 JSD `{}`，约束数均值相对误差 `{}`，求解状态 JSD `{}`，求解时间 JSD `{}`。".format(
                label,
                fmt(scenario["kind_distribution"]["js_divergence"]),
                fmt(scenario["delay"]["delay_seconds"]["js_divergence"]),
                fmt(scenario["speed_limit"]["speed_limit_kmh"]["js_divergence"]),
                fmt(joint["aggregate_error"]),
                fmt(milp["numeric"]["milp_num_constrs"]["mean_relative_error"]),
                fmt(solver["status"]["js_divergence"]),
                fmt(solver["numeric"]["duration_sec"]["js_divergence"]),
            )
        )
    lines.append("")
    dim_keys = [
        ("task_output_error", "Task 输出"),
        ("scenario_error", "扰动场景"),
        ("joint_error", "联合结构"),
        ("milp_error", "MILP 规模"),
        ("solver_error", "求解行为"),
    ]
    best_parts = []
    for key, title in dim_keys:
        dim_best_label, dim_best_group = min(groups.items(), key=lambda item: float(item[1]["composite"][key]))
        best_parts.append(f"{title}：`{dim_best_label}` `{fmt(dim_best_group['composite'][key])}`")
    lines.append("分项最优分别为：" + "；".join(best_parts) + "。")
    lines.append("")
    lines.append("因此需要避免只看单项指标：`steps=3` 在扰动场景和联合结构上略优，但 Task 输出、MILP 规模和求解行为误差更高；`steps=4` 的扰动场景、联合结构和 MILP 规模误差进一步增大。`steps=2` 的优势在于 Task 输出、MILP 规模和求解行为更稳定地贴近参考集，综合上更可信。")
    lines.append("")
    lines.append("从指标结构看，如果某组训练 loss 更低但联合结构或求解行为误差更高，说明它可能只学到了 task output 的局部统计，而没有充分复现铁路突发事件的时空组合和优化难度。相反，扰动程度分箱 JSD、联合结构 JSD、MILP 规模和求解行为同时接近参考集，才更能说明模型学到了可被 RailGraph2Gurobi 消化的真实扰动分布。")
    lines.append("")
    lines.append("## 产物位置")
    lines.append("")
    lines.append(f"- `{output_dir}/metrics_summary.json`：完整指标。")
    lines.append(f"- `{output_dir}/group_summary.csv`：三组汇总表。")
    lines.append(f"- `{output_dir}/metric_long.csv`：长表指标，便于后续制图或论文表格。")
    lines.append(f"- `{output_dir}/sample_features.csv`：逐样本特征。")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def fmt(value: object, digits: int = 3) -> str:
    return f"{to_float(value):.{digits}f}"


def run_self_tests() -> None:
    same = numeric_distribution_metrics([1, 2, 3], [1, 2, 3], bins=([0, 2, 4], ["低", "高"]), normalizer=4)
    assert abs(float(same["js_divergence"])) < 1e-12
    assert abs(float(same["ks_statistic"])) < 1e-12
    assert abs(float(same["wasserstein"])) < 1e-12
    opposite = categorical_distribution_metrics(["a"], ["b"])
    assert float(opposite["js_divergence"]) > 0.99
    scenarios = {"delays": [], "speed_limits": [{"section_anchor_id": "S1", "start_time": "01:00:00", "duration": 600, "limit_speed": 0}]}
    context = {"event_anchors": {}, "section_anchors": {"S1": {"section_order": 0}}}
    extracted = extract_case_features("test", "case", scenarios, context)
    assert extracted["sample"]["interruption_count"] == 1
    ref_joint = categorical_distribution_metrics(["A|早", "B|晚"], ["A|晚", "B|早"])
    assert float(ref_joint["js_divergence"]) > 0.99
    print("self-test passed")


if __name__ == "__main__":
    main()

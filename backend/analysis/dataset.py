from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List

from core.project_layout import ProjectLayout, require_id, sanitize_id, to_posix


METRIC_LABELS = {
    "objective": "目标值",
    "mip_gap": "MIP Gap",
    "num_nodes": "分支节点数",
    "duration_sec": "求解耗时",
}

SOLVER_CONFIG_KEYS = ("time_limit", "mip_gap", "threads")


def read_dataset_solve_analysis(layout: ProjectLayout, dataset_ids: Iterable[str]) -> Dict[str, object]:
    dataset_ids = [require_id(item, "dataset_id") for item in dataset_ids if str(item or "").strip()]
    datasets = [read_dataset_solve_state(layout, dataset_id) for dataset_id in dataset_ids]
    baseline = datasets[0] if datasets else None

    return {
        "project_id": layout.name,
        "datasets": datasets,
        "metric_labels": METRIC_LABELS,
        "comparison": compare_to_baseline(baseline, datasets[1:] if baseline else []),
        "warnings": solve_analysis_warnings(datasets),
    }


def read_dataset_solve_state(layout: ProjectLayout, dataset_id: str) -> Dict[str, object]:
    dataset = layout.dataset(dataset_id)
    if not dataset.root.is_dir():
        raise FileNotFoundError(f"Dataset not found: {dataset.root}")

    cases = [read_case_solve_state(path) for path in dataset_case_dirs(dataset.cases_dir)]
    config_counter = Counter(
        config_signature(case["solver_config"])
        for case in cases
        if case.get("solver_config")
    )
    status_counts = Counter(str(case.get("status", "unknown")) for case in cases)

    return {
        "dataset_id": dataset_id,
        "root": to_posix(dataset.root),
        "case_count": len(cases),
        "solved_count": sum(1 for case in cases if case.get("is_solved")),
        "config_known_count": sum(1 for case in cases if case.get("solver_config")),
        "config_consistent": len(config_counter) <= 1,
        "solver_config": dict(cases[0].get("solver_config", {})) if config_counter else {},
        "solver_config_signatures": [
            {"signature": key, "count": count}
            for key, count in sorted(config_counter.items())
        ],
        "status_counts": [
            {"label": key, "count": count}
            for key, count in sorted(status_counts.items())
        ],
        "summary_metrics": summary_metrics(cases),
        "cases": cases,
    }


def read_case_solve_state(case_dir: Path) -> Dict[str, object]:
    case_id = sanitize_id(case_dir.name)
    lp_path = case_dir / f"{case_id}.lp"
    sol_path = case_dir / f"{case_id}.sol"
    sol_csv_path = sol_path.with_suffix(".sol.csv")
    build = read_json_if_exists(case_dir / "build.json")
    build_result = build.get("result", {}) if isinstance(build.get("result"), dict) else {}
    summary = read_json_if_exists(case_dir / "solve.json")
    result = summary.get("result", {}) if isinstance(summary.get("result"), dict) else {}
    solver_config = summary.get("solver_config", {}) if isinstance(summary.get("solver_config"), dict) else {}
    objective = number_or_none(result.get("objective")) or read_solution_objective(sol_path)

    return {
        "case_id": case_id,
        "status": str(result.get("status") or ("ok" if sol_path.is_file() and sol_csv_path.is_file() else "missing")),
        "is_solved": sol_path.is_file() and sol_csv_path.is_file(),
        "solver_config": normalize_solver_config(solver_config),
        "metrics": {
            "objective": objective,
            "mip_gap": number_or_none(result.get("mip_gap")),
            "num_nodes": number_or_none(result.get("num_nodes")),
            "duration_sec": number_or_none(result.get("duration_sec")),
            "constraints": number_or_none(build_result.get("constraints")),
            "build_duration_sec": number_or_none(build_result.get("duration_sec")),
        },
        "artifacts": {
            "build": to_posix(case_dir / "build.json"),
            "lp": to_posix(lp_path),
            "solution": to_posix(sol_path),
            "solution_csv": to_posix(sol_csv_path),
            "solve": to_posix(case_dir / "solve.json"),
        },
    }


def compare_to_baseline(
    baseline: Dict[str, object] | None,
    candidates: List[Dict[str, object]],
) -> Dict[str, object]:
    if not baseline:
        return {"baseline_dataset_id": "", "rows": []}
    baseline_cases = {
        str(case.get("case_id", "")): case
        for case in baseline.get("cases", [])
        if isinstance(case, dict)
    }
    rows: List[Dict[str, object]] = []
    for dataset in candidates:
        for case in dataset.get("cases", []):
            if not isinstance(case, dict):
                continue
            baseline_case = baseline_cases.get(str(case.get("case_id", "")))
            if not baseline_case:
                continue
            rows.extend(compare_case_metrics(str(dataset["dataset_id"]), baseline_case, case))
    return {
        "baseline_dataset_id": baseline["dataset_id"],
        "rows": rows,
    }


def compare_case_metrics(
    dataset_id: str,
    baseline_case: Dict[str, object],
    candidate_case: Dict[str, object],
) -> List[Dict[str, object]]:
    baseline_metrics = baseline_case.get("metrics", {})
    candidate_metrics = candidate_case.get("metrics", {})
    if not isinstance(baseline_metrics, dict) or not isinstance(candidate_metrics, dict):
        return []

    rows: List[Dict[str, object]] = []
    for key, label in METRIC_LABELS.items():
        baseline_value = number_or_none(baseline_metrics.get(key))
        candidate_value = number_or_none(candidate_metrics.get(key))
        if baseline_value is None or candidate_value is None:
            continue
        delta = candidate_value - baseline_value
        rows.append(
            {
                "dataset_id": dataset_id,
                "case_id": candidate_case.get("case_id", ""),
                "metric": key,
                "metric_label": label,
                "baseline_value": baseline_value,
                "value": candidate_value,
                "absolute_error": abs(delta),
                "relative_error": abs(delta) / abs(baseline_value) if abs(baseline_value) > 1e-12 else None,
                "signed_delta": delta,
            }
        )
    return rows


def solve_analysis_warnings(datasets: List[Dict[str, object]]) -> List[Dict[str, object]]:
    warnings: List[Dict[str, object]] = []
    for dataset in datasets:
        dataset_id = str(dataset.get("dataset_id", ""))
        case_count = int(dataset.get("case_count", 0) or 0)
        solved_count = int(dataset.get("solved_count", 0) or 0)
        config_known_count = int(dataset.get("config_known_count", 0) or 0)
        if case_count and solved_count < case_count:
            warnings.append(
                {
                    "type": "incomplete",
                    "dataset_id": dataset_id,
                    "message": f"{dataset_id} 求解数据不完整：{solved_count}/{case_count}。",
                }
            )
        if case_count and config_known_count < case_count:
            warnings.append(
                {
                    "type": "unknown_solver_config",
                    "dataset_id": dataset_id,
                    "message": f"{dataset_id} 有 {case_count - config_known_count} 个实例缺少求解器配置记录。",
                }
            )
        if not bool(dataset.get("config_consistent", True)):
            warnings.append(
                {
                    "type": "mixed_solver_config",
                    "dataset_id": dataset_id,
                    "message": f"{dataset_id} 内部存在多组求解器配置。",
                }
            )

    known_signatures = {
        config_signature(dataset.get("solver_config", {}))
        for dataset in datasets
        if dataset.get("solver_config")
    }
    if len(known_signatures) > 1:
        warnings.append(
            {
                "type": "solver_config_mismatch",
                "dataset_id": "",
                "message": "检测到求解器配置不一致，求解行为对比可能不准确。",
            }
        )
    return warnings


def summary_metrics(cases: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return [
        metric_summary(key, label, metric_values(cases, key))
        for key, label in METRIC_LABELS.items()
    ]


def metric_summary(key: str, label: str, values: List[float]) -> Dict[str, object]:
    return {
        "key": key,
        "label": label,
        "count": len(values),
        "mean": round(sum(values) / len(values), 6) if values else None,
        "min": round(min(values), 6) if values else None,
        "max": round(max(values), 6) if values else None,
    }


def metric_values(cases: List[Dict[str, object]], key: str) -> List[float]:
    values: List[float] = []
    for case in cases:
        metrics = case.get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        value = number_or_none(metrics.get(key))
        if value is not None:
            values.append(value)
    return values


def dataset_case_dirs(cases_dir: Path) -> List[Path]:
    if not cases_dir.is_dir():
        return []
    return sorted(path for path in cases_dir.iterdir() if path.is_dir())


def read_json_if_exists(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_solution_objective(path: Path) -> float | None:
    if not path.is_file():
        return None
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:512]
    except OSError:
        return None
    match = re.search(r"Objective value\s*=\s*([-+0-9.eE]+)", head)
    return number_or_none(match.group(1)) if match else None


def normalize_solver_config(payload: Dict[str, object]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key in SOLVER_CONFIG_KEYS:
        value = payload.get(key)
        number = number_or_none(value)
        if number is not None:
            result[key] = int(number) if key == "threads" else number
    return result


def config_signature(payload: object) -> str:
    if not isinstance(payload, dict) or not payload:
        return ""
    normalized = normalize_solver_config(payload)
    return "|".join(f"{key}={normalized.get(key, '')}" for key in SOLVER_CONFIG_KEYS)


def number_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

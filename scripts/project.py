from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.project_layout import ProjectLayout, repo_path, reset_dir, to_posix

DEFAULT_PROJECT_CONFIG = "config/demo.yml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project-oriented RailGraph2Gurobi workflow.")
    sub = parser.add_subparsers(dest="domain", required=True)

    dataset = sub.add_parser("dataset", help="Build and benchmark datasets.")
    dataset_sub = dataset.add_subparsers(dest="action", required=True)
    d_build = dataset_sub.add_parser("build", help="Build a dataset from case configs.")
    add_project_args(d_build)
    source = d_build.add_mutually_exclusive_group(required=True)
    source.add_argument("--config-root")
    source.add_argument("--config")
    d_build.add_argument("--project-config", default=DEFAULT_PROJECT_CONFIG, help="Project config used when --project is omitted with --config-root.")
    d_build.add_argument("--scenarios", default="", help="Override build.scenarios with a scenario file or directory.")
    d_build.add_argument("--glob", default="**/*.yaml")
    d_build.add_argument("--limit", type=int, default=0)
    d_build.add_argument("--stop-on-error", action="store_true")

    d_benchmark = dataset_sub.add_parser("benchmark", help="Solve/export/analyze a dataset.")
    add_project_args(d_benchmark)
    d_benchmark.add_argument("--config", default=DEFAULT_PROJECT_CONFIG, help="Project config used when --project is omitted.")
    d_benchmark.add_argument("--glob", default="**/*.yaml")
    d_benchmark.add_argument("--limit", type=int, default=0)
    d_benchmark.add_argument("--workers", type=int, default=1)
    d_benchmark.add_argument("--threads-per-solve", type=int, default=0)
    d_benchmark.add_argument("--time-limit", type=float, default=120.0)
    d_benchmark.add_argument("--mip-gap", type=float, default=0.0)
    d_benchmark.add_argument("--skip-solve", action="store_true")
    d_benchmark.add_argument("--skip-export", action="store_true")
    d_benchmark.add_argument("--skip-analyze", action="store_true")
    d_benchmark.add_argument("--scenario-report", choices=("on", "off"), default="on")
    d_benchmark.add_argument("--scenario-report-scope", choices=("batch", "per_case", "both"), default="batch")

    model = sub.add_parser("model", help="Train models.")
    model_sub = model.add_subparsers(dest="action", required=True)
    m_train = model_sub.add_parser("train", help="Train VAE from a dataset graph library.")
    add_project_args(m_train, dataset_required=True, model_required=True)
    m_train.add_argument("--config", default=DEFAULT_PROJECT_CONFIG)

    generation = sub.add_parser("generation", help="Create, decode, and evaluate generated graphs.")
    generation_sub = generation.add_subparsers(dest="action", required=True)
    g_create = generation_sub.add_parser("create", help="Generate math graphs.")
    add_project_args(g_create, dataset_required=True, model_required=False, generation_required=True)
    g_create.add_argument("--config", default=DEFAULT_PROJECT_CONFIG, help="Project config used when --project is omitted.")
    g_create.add_argument("--model", default="", help="Model id used in --mode model.")
    g_create.add_argument("--num-samples", type=int, default=100)
    g_create.add_argument("--mode", choices=("model", "target-copy"), default="model")
    g_create.add_argument("--seed", type=int, default=1)
    g_create.add_argument("--device", default="auto")

    g_decode = generation_sub.add_parser("decode", help="Decode generated graphs into case configs.")
    add_project_args(g_decode, dataset_required=False, generation_required=True)
    g_decode.add_argument("--config", default=DEFAULT_PROJECT_CONFIG, help="Project config used when --project is omitted.")
    g_decode.add_argument("--base-config", default=DEFAULT_PROJECT_CONFIG)

    g_eval = generation_sub.add_parser("evaluate-graphs", help="Compare generated graph outputs with a reference dataset.")
    add_project_args(g_eval, dataset_required=True, generation_required=True)
    g_eval.add_argument("--config", default=DEFAULT_PROJECT_CONFIG, help="Project config used when --project is omitted.")

    compare = sub.add_parser("compare", help="Compare benchmarked datasets.")
    compare_sub = compare.add_subparsers(dest="action", required=True)
    c_solver = compare_sub.add_parser("solver", help="Compare solver difficulty between two datasets.")
    c_solver.add_argument("--project", default="")
    c_solver.add_argument("--config", default=DEFAULT_PROJECT_CONFIG, help="Project config used when --project is omitted.")
    c_solver.add_argument("--reference", required=True)
    c_solver.add_argument("--candidate", required=True)
    c_solver.add_argument("--generation", default="", help="Optional generation id where solver_difficulty.json is written.")

    return parser.parse_args()


def add_project_args(
    parser: argparse.ArgumentParser,
    *,
    dataset_required: bool = True,
    model_required: bool = False,
    generation_required: bool = False,
) -> None:
    parser.add_argument("--project", default="")
    if dataset_required:
        parser.add_argument("--dataset", required=True)
    if model_required:
        parser.add_argument("--model", required=True)
    if generation_required:
        parser.add_argument("--generation", required=True)


def main() -> None:
    args = parse_args()
    project_name = resolve_project_name(args)
    layout = ProjectLayout.from_name(project_name)
    layout.root.mkdir(parents=True, exist_ok=True)
    write_json(layout.manifest, {"project": layout.name, "root": to_posix(layout.root), "updated_at": now()})

    if args.domain == "dataset" and args.action == "build":
        dataset_build(args, layout)
    elif args.domain == "dataset" and args.action == "benchmark":
        dataset_benchmark(args, layout)
    elif args.domain == "model" and args.action == "train":
        model_train(args, layout)
    elif args.domain == "generation" and args.action == "create":
        generation_create(args, layout)
    elif args.domain == "generation" and args.action == "decode":
        generation_decode(args, layout)
    elif args.domain == "generation" and args.action == "evaluate-graphs":
        generation_evaluate_graphs(args, layout)
    elif args.domain == "compare" and args.action == "solver":
        compare_solver(args, layout)
    else:  # pragma: no cover
        raise ValueError(f"Unsupported command: {args.domain} {args.action}")


def dataset_build(args: argparse.Namespace, layout: ProjectLayout) -> None:
    dataset = layout.dataset(args.dataset)
    config_root = args.config_root
    glob_pattern = args.glob
    if args.config:
        config_path = repo_path(args.config)
        config_root = to_posix(config_path.parent)
        glob_pattern = config_path.name
    cmd = [
        sys.executable,
        "scripts/bench_build.py",
        "--config-root",
        config_root,
        "--glob",
        glob_pattern,
        "--output-dir",
        to_posix(dataset.root),
    ]
    if args.limit > 0:
        cmd.extend(["--limit", str(args.limit)])
    if args.scenarios:
        cmd.extend(["--scenarios", args.scenarios])
    if args.stop_on_error:
        cmd.append("--stop-on-error")
    run_logged(cmd, layout.root / "logs" / f"dataset_{args.dataset}_build.wrapper.log")


def dataset_benchmark(args: argparse.Namespace, layout: ProjectLayout) -> None:
    dataset = layout.dataset(args.dataset)
    if not dataset.configs_dir.is_dir():
        raise FileNotFoundError(f"Dataset configs not found: {dataset.configs_dir}")
    if not args.skip_solve:
        end_index = args.limit if args.limit > 0 else 0
        cmd = [
            sys.executable,
            "scripts/bench_solve.py",
            "--config-root",
            to_posix(dataset.configs_dir),
            "--glob",
            args.glob,
            "--end-index",
            str(end_index),
            "--workers",
            str(args.workers),
            "--threads-per-solve",
            str(args.threads_per_solve),
            "--time-limit",
            str(args.time_limit),
            "--mip-gap",
            str(args.mip_gap),
            "--summary-csv",
            to_posix(dataset.solve_summary_csv),
            "--summary-json",
            to_posix(dataset.solve_summary_json),
        ]
        run_logged(cmd, dataset.logs_dir / "solve.log")
    if not args.skip_export:
        cmd = [
            sys.executable,
            "scripts/bench_export_timetable.py",
            "--config-root",
            to_posix(dataset.configs_dir),
            "--glob",
            args.glob,
            "--limit",
            str(args.limit),
            "--summary-csv",
            to_posix(dataset.export_summary_csv),
            "--summary-json",
            to_posix(dataset.export_summary_json),
        ]
        run_logged(cmd, dataset.logs_dir / "export_timetable.log")
    if not args.skip_analyze:
        cmd = [
            sys.executable,
            "scripts/bench_analyze.py",
            "--config-root",
            to_posix(dataset.configs_dir),
            "--glob",
            args.glob,
            "--limit",
            str(args.limit),
            "--summary-csv",
            to_posix(dataset.analyze_summary_csv),
            "--summary-json",
            to_posix(dataset.analyze_summary_json),
            "--scenario-report",
            args.scenario_report,
            "--scenario-report-scope",
            args.scenario_report_scope,
            "--scenario-report-output-root",
            to_posix(dataset.benchmark_dir / "scenario_report"),
        ]
        run_logged(cmd, dataset.logs_dir / "analyze.log")
    write_json(
        dataset.benchmark_dir / "benchmark_manifest.json",
        {"dataset": args.dataset, "updated_at": now(), "dataset_dir": to_posix(dataset.root)},
    )


def model_train(args: argparse.Namespace, layout: ProjectLayout) -> None:
    dataset = layout.dataset(args.dataset)
    model = layout.model(args.model)
    cmd = [
        sys.executable,
        "scripts/train_vae.py",
        args.config,
        "--graphs-root",
        to_posix(dataset.graph_dir),
        "--output-dir",
        to_posix(model.root),
    ]
    run_logged(cmd, layout.root / "logs" / f"model_{args.model}_train.wrapper.log")
    write_json(model.root / "manifest.json", {"model": args.model, "dataset": args.dataset, "updated_at": now()})


def generation_create(args: argparse.Namespace, layout: ProjectLayout) -> None:
    dataset = layout.dataset(args.dataset)
    generation = layout.generation(args.generation)
    cmd = [
        sys.executable,
        "scripts/generate_vae.py",
        "--context-graphs" if args.mode == "target-copy" else "--context-graph",
        to_posix(dataset.graph_dir if args.mode == "target-copy" else dataset.context_graph),
        "--num-samples",
        str(args.num_samples),
        "--mode",
        args.mode,
        "--seed",
        str(args.seed),
        "--device",
        args.device,
        "--output-dir",
        to_posix(generation.root),
    ]
    if args.mode == "model":
        if not args.model:
            raise ValueError("--model is required when --mode model.")
        cmd.extend(["--checkpoint", to_posix(layout.model(args.model).best_model)])
    run_logged(cmd, layout.root / "logs" / f"generation_{args.generation}_create.wrapper.log")
    write_json(
        generation.manifest,
        {
            "generation": args.generation,
            "dataset": args.dataset,
            "model": args.model,
            "mode": args.mode,
            "updated_at": now(),
        },
    )


def generation_decode(args: argparse.Namespace, layout: ProjectLayout) -> None:
    generation = layout.generation(args.generation)
    reset_dir(generation.disturbance_graphs_dir)
    reset_dir(generation.configs_dir)
    reset_dir(generation.case_outputs_dir)
    cmd = [
        sys.executable,
        "scripts/decode_import_generated_graphs.py",
        "--generated-graphs",
        to_posix(generation.root),
        "--base-config",
        args.base_config,
        "--output-disturbance-root",
        to_posix(generation.disturbance_graphs_dir),
        "--output-config-root",
        to_posix(generation.configs_dir),
        "--project-output-root",
        to_posix(generation.case_outputs_dir),
        "--summary-csv",
        to_posix(generation.decode_summary_csv),
        "--summary-json",
        to_posix(generation.decode_summary_json),
    ]
    run_logged(cmd, generation.logs_dir / "decode.log")


def generation_evaluate_graphs(args: argparse.Namespace, layout: ProjectLayout) -> None:
    dataset = layout.dataset(args.dataset)
    generation = layout.generation(args.generation)
    cmd = [
        sys.executable,
        "scripts/evaluate_vae.py",
        "--reference-graphs",
        to_posix(dataset.graph_dir),
        "--generated-graphs",
        to_posix(generation.root),
        "--output",
        to_posix(generation.graph_evaluation),
    ]
    run_logged(cmd, generation.logs_dir / "evaluate_graphs.log")


def compare_solver(args: argparse.Namespace, layout: ProjectLayout) -> None:
    reference = layout.dataset(args.reference)
    candidate = layout.dataset(args.candidate)
    output = (
        layout.generation(args.generation).solver_difficulty
        if args.generation
        else layout.comparison(f"{args.reference}_vs_{args.candidate}").root / "solver_difficulty.json"
    )
    cmd = [
        sys.executable,
        "scripts/evaluate_vae.py",
        "--reference-solve-csv",
        to_posix(reference.solve_summary_csv),
        "--generated-solve-csv",
        to_posix(candidate.solve_summary_csv),
        "--output",
        to_posix(output),
    ]
    run_logged(cmd, output.parent / "solver_compare.log")


def run_logged(cmd: List[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(" ".join(cmd))
    with log_path.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}. See {log_path}")


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_project_name(args: argparse.Namespace) -> str:
    value = str(getattr(args, "project", "") or "").strip()
    if value:
        return value
    for attr in ("config", "project_config"):
        config = str(getattr(args, attr, "") or "").strip()
        if not config:
            continue
        project_name = read_project_name(repo_path(config))
        if project_name:
            return project_name
    raise ValueError("--project is required unless --config or --project-config points to a project config with project.name.")


def read_project_name(path: Path) -> str:
    if not path.is_file():
        return ""
    payload = _require_yaml().safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return ""
    project = payload.get("project")
    if not isinstance(project, dict):
        return ""
    return str(project.get("name", "") or "").strip()


def _require_yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Missing dependency: pyyaml") from exc
    return yaml


if __name__ == "__main__":
    main()

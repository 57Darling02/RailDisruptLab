from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

MATH_CONTEXT_GRAPH_TYPE = "vae_math_context_graph"
MATH_LEARNING_SAMPLE_TYPE = "vae_math_learning_sample"
MATH_GENERATED_GRAPH_TYPE = "vae_math_generated_graph"
MATH_CONTEXT_FILENAME = "math_context.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate math rail-disturbance graphs.")
    parser.add_argument(
        "--context-graphs",
        default="",
        help="Context graph file or compact graph library directory.",
    )
    parser.add_argument("--context-graph", default="", help="Alias for --context-graphs in --mode model.")
    parser.add_argument("--checkpoint", default="", help="Checkpoint path required for --mode model.")
    parser.add_argument("--num-samples", type=int, default=1)
    parser.add_argument("--mode", choices=["target-copy", "model"], default="model")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or cuda:<index>.")
    parser.add_argument("--output-dir", required=True, help="Generation output directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.context_graphs = _context_input(args)
    run_dir, math_graphs_dir = _prepare_run_dirs(Path(args.output_dir))
    _write_generation_config(args, run_dir, math_graphs_dir)
    if args.mode == "target-copy":
        _generate_target_copy(args, math_graphs_dir)
    else:
        _generate_model(args, math_graphs_dir)
    _write_generation_summary(args, run_dir, math_graphs_dir)
    print(f"Generation run: {run_dir}")
    print(f"Math graphs: {math_graphs_dir}")


def _generate_target_copy(args: argparse.Namespace, math_graphs_dir: Path) -> None:
    generated_sources = _target_copy_sources(Path(args.context_graphs))
    if not generated_sources:
        raise FileNotFoundError(f"No VAE learning samples found: {args.context_graphs}")
    for index in range(args.num_samples):
        generated = generated_sources[index % len(generated_sources)]
        path = math_graphs_dir / f"sample_{index + 1:06d}.json"
        path.write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated target-copy math graphs: {math_graphs_dir}")


def _generate_model(args: argparse.Namespace, math_graphs_dir: Path) -> None:
    if not args.checkpoint:
        raise ValueError("--checkpoint is required when --mode model.")

    import torch

    from src.data import RailDisturbanceContextDataset
    from src.model import RailDisturbanceVAE, generated_outputs_to_json

    torch.manual_seed(args.seed)
    device = _device(args.device, torch)
    checkpoint = torch.load(args.checkpoint, map_location=device)
    model = RailDisturbanceVAE.from_config(checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    dataset = RailDisturbanceContextDataset(args.context_graphs)

    with torch.no_grad():
        for index in range(args.num_samples):
            sample = dataset[index % len(dataset)].to(device)
            task_outputs = model.decode_from_prior(sample)
            generated = generated_outputs_to_json(sample, task_outputs)
            path = math_graphs_dir / f"sample_{index + 1:06d}.json"
            path.write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated model math graphs: {math_graphs_dir}")


def _prepare_run_dirs(output_dir: Path) -> Tuple[Path, Path]:
    _reset_path(output_dir, allowed_root=Path("projects"))
    output_dir.mkdir(parents=True, exist_ok=True)
    math_graphs_dir = output_dir / "math_graphs"
    math_graphs_dir.mkdir(parents=True, exist_ok=False)
    return output_dir, math_graphs_dir


def _write_generation_config(args: argparse.Namespace, run_dir: Path, math_graphs_dir: Path) -> None:
    payload = vars(args).copy()
    payload["created_at"] = datetime.now().isoformat(timespec="seconds")
    payload["run_dir"] = _to_posix(run_dir)
    payload["math_graphs_dir"] = _to_posix(math_graphs_dir)
    (run_dir / "generation_config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_generation_summary(args: argparse.Namespace, run_dir: Path, math_graphs_dir: Path) -> None:
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": _to_posix(run_dir),
        "math_graphs_dir": _to_posix(math_graphs_dir),
        "mode": args.mode,
        "num_samples": args.num_samples,
        "sample_count": len(list(math_graphs_dir.glob("*.json"))),
    }
    (run_dir / "generation_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _reset_path(path: Path, *, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to clear path outside allowed root: {path}")
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _to_posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def _target_copy_sample(context: Dict[str, object], sample: Dict[str, object]) -> Dict[str, object]:
    if context.get("graph_type") != MATH_CONTEXT_GRAPH_TYPE:
        raise ValueError(f"Unsupported context graph_type: {context.get('graph_type')}")
    if sample.get("graph_type") != MATH_LEARNING_SAMPLE_TYPE:
        raise ValueError(f"Unsupported sample graph_type: {sample.get('graph_type')}")
    supervision = _object(sample.get("supervision"), "supervision")
    targets = _object(supervision.get("targets"), "supervision.targets")
    return _target_outputs_to_generated(
        schema_version=int(context.get("schema_version", sample.get("schema_version", 1))),
        decode_handle=dict(_object(context.get("decode_handle"), "decode_handle")),
        targets=targets,
    )


def _target_outputs_to_generated(
    *,
    schema_version: int,
    decode_handle: Dict[str, object],
    targets: Dict[str, object],
) -> Dict[str, object]:
    task_outputs = {
        str(task_id): {
            "count": int(target["count"]),
            "anchor_index": list(target["anchor_index"]),
            "params": list(target["params"]),
        }
        for task_id, target in targets.items()
        if isinstance(target, dict)
    }
    return {
        "schema_version": schema_version,
        "graph_type": MATH_GENERATED_GRAPH_TYPE,
        "decode_handle": decode_handle,
        "task_outputs": task_outputs,
    }


def _target_copy_sources(root: Path) -> List[Dict[str, object]]:
    if root.is_file():
        payload = json.loads(root.read_text(encoding="utf-8"))
        if payload.get("graph_type") == MATH_LEARNING_SAMPLE_TYPE:
            context = _load_context_for_sample(root, payload)
            return [_target_copy_sample(context, payload)]
        raise ValueError(f"Unsupported graph_type: {payload.get('graph_type')}")

    context_path = root / MATH_CONTEXT_FILENAME
    sample_dir = root / "samples"
    if context_path.is_file() and sample_dir.is_dir():
        context = json.loads(context_path.read_text(encoding="utf-8"))
        result: List[Dict[str, object]] = []
        for path in sorted(sample_dir.rglob("*.json")):
            sample = json.loads(path.read_text(encoding="utf-8"))
            if sample.get("graph_type") == MATH_LEARNING_SAMPLE_TYPE:
                result.append(_target_copy_sample(context, sample))
        return result

    return []


def _load_context_for_sample(sample_path: Path, sample: Dict[str, object]) -> Dict[str, object]:
    context_ref = Path(str(sample.get("context_ref", MATH_CONTEXT_FILENAME)))
    if context_ref.is_absolute():
        context_path = context_ref
    else:
        candidates = [
            sample_path.parent / context_ref,
            sample_path.parent.parent / context_ref,
        ]
        context_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    return json.loads(context_path.read_text(encoding="utf-8"))


def _device(value: str, torch_module) -> object:
    if value == "auto":
        return torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    return torch_module.device(value)


def _context_input(args: argparse.Namespace) -> str:
    value = args.context_graph or args.context_graphs
    if not value:
        raise ValueError("--context-graph or --context-graphs is required.")
    return value


def _object(value: object, label: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


if __name__ == "__main__":
    main()

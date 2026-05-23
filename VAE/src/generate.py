from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

MATH_GRAPH_TYPE = "vae_math_learning_graph"
MATH_GENERATED_GRAPH_TYPE = "vae_math_generated_graph"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate math rail-disturbance graphs.")
    parser.add_argument("--context-graphs", required=True, help="Math learning graph file or directory.")
    parser.add_argument("--output-dir", required=True, help="Directory for generated math graphs.")
    parser.add_argument("--checkpoint", default="", help="Checkpoint path required for --mode model.")
    parser.add_argument("--num-samples", type=int, default=1)
    parser.add_argument("--mode", choices=["target-copy", "model"], default="model")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or cuda:<index>.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "target-copy":
        _generate_target_copy(args, output_dir)
        return
    _generate_model(args, output_dir)


def _generate_target_copy(args: argparse.Namespace, output_dir: Path) -> None:
    files = _math_graph_files(Path(args.context_graphs))
    if not files:
        raise FileNotFoundError(f"No {MATH_GRAPH_TYPE} JSON files found: {args.context_graphs}")
    for index in range(args.num_samples):
        payload = json.loads(files[index % len(files)].read_text(encoding="utf-8"))
        generated = _target_copy(payload)
        path = output_dir / f"sample_{index + 1:06d}.json"
        path.write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated target-copy math graphs: {output_dir}")


def _generate_model(args: argparse.Namespace, output_dir: Path) -> None:
    if not args.checkpoint:
        raise ValueError("--checkpoint is required when --mode model.")

    import torch

    from src.data import RailDisturbanceDataset
    from src.model import RailDisturbanceVAE, generated_outputs_to_json

    torch.manual_seed(args.seed)
    device = _device(args.device, torch)
    checkpoint = torch.load(args.checkpoint, map_location=device)
    model = RailDisturbanceVAE.from_config(checkpoint["model_config"]).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    dataset = RailDisturbanceDataset(args.context_graphs)

    with torch.no_grad():
        for index in range(args.num_samples):
            sample = dataset[index % len(dataset)].to(device)
            task_outputs = model.decode_from_prior(sample)
            generated = generated_outputs_to_json(sample, task_outputs)
            path = output_dir / f"sample_{index + 1:06d}.json"
            path.write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated model math graphs: {output_dir}")


def _target_copy(payload: Dict[str, object]) -> Dict[str, object]:
    if payload.get("graph_type") != MATH_GRAPH_TYPE:
        raise ValueError(f"Unsupported graph_type: {payload.get('graph_type')}")
    supervision = _object(payload.get("supervision"), "supervision")
    targets = _object(supervision.get("targets"), "supervision.targets")
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
        "schema_version": int(payload.get("schema_version", 1)),
        "graph_type": MATH_GENERATED_GRAPH_TYPE,
        "decode_handle": dict(_object(payload.get("decode_handle"), "decode_handle")),
        "task_outputs": task_outputs,
    }


def _math_graph_files(root: Path) -> List[Path]:
    if root.is_file():
        candidates = [root]
    else:
        graph_root = root / "graphs" if (root / "graphs").is_dir() else root
        candidates = sorted(graph_root.rglob("*.json"))
    result: List[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if payload.get("graph_type") == MATH_GRAPH_TYPE:
            result.append(path)
    return result


def _device(value: str, torch_module) -> object:
    if value == "auto":
        return torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    return torch_module.device(value)


def _object(value: object, label: str) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


if __name__ == "__main__":
    main()

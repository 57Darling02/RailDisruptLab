from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_ROOT = REPO_ROOT / "outputs"


def sanitize_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    return cleaned.strip("_") or "default"


def repo_path(path_text: str | Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def to_posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def reset_dir(path: Path, *, allowed_root: Path = OUTPUTS_ROOT) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to clear path outside {root}: {path}")
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


@dataclass(frozen=True)
class DatasetLayout:
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def configs_dir(self) -> Path:
        return self.root / "configs"

    @property
    def cases_dir(self) -> Path:
        return self.root / "cases"

    @property
    def graph_dir(self) -> Path:
        return self.root / "graph"

    @property
    def context_graph(self) -> Path:
        return self.graph_dir / "context.json"

    @property
    def sample_dir(self) -> Path:
        return self.graph_dir / "samples"

    @property
    def dataset_profile(self) -> Path:
        return self.graph_dir / "dataset_profile.json"

    @property
    def benchmark_dir(self) -> Path:
        return self.root / "benchmark"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def build_summary_csv(self) -> Path:
        return self.benchmark_dir / "build_summary.csv"

    @property
    def build_summary_json(self) -> Path:
        return self.benchmark_dir / "build_summary.json"

    @property
    def solve_summary_csv(self) -> Path:
        return self.benchmark_dir / "solve_summary.csv"

    @property
    def solve_summary_json(self) -> Path:
        return self.benchmark_dir / "solve_summary.json"

    @property
    def export_summary_csv(self) -> Path:
        return self.benchmark_dir / "export_timetable_summary.csv"

    @property
    def export_summary_json(self) -> Path:
        return self.benchmark_dir / "export_timetable_summary.json"

    @property
    def analyze_summary_csv(self) -> Path:
        return self.benchmark_dir / "analyze_summary.csv"

    @property
    def analyze_summary_json(self) -> Path:
        return self.benchmark_dir / "analyze_summary.json"


@dataclass(frozen=True)
class ModelLayout:
    root: Path

    @property
    def train_config(self) -> Path:
        return self.root / "train_config.yml"

    @property
    def best_model(self) -> Path:
        return self.root / "best_model.pt"


@dataclass(frozen=True)
class GenerationLayout:
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def math_graphs_dir(self) -> Path:
        return self.root / "math_graphs"

    @property
    def disturbance_graphs_dir(self) -> Path:
        return self.root / "disturbance_graphs"

    @property
    def configs_dir(self) -> Path:
        return self.root / "configs"

    @property
    def case_outputs_dir(self) -> Path:
        return self.root / "case_outputs"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def decode_summary_csv(self) -> Path:
        return self.root / "decode_summary.csv"

    @property
    def decode_summary_json(self) -> Path:
        return self.root / "decode_summary.json"

    @property
    def graph_evaluation(self) -> Path:
        return self.root / "graph_evaluation.json"

    @property
    def solver_difficulty(self) -> Path:
        return self.root / "solver_difficulty.json"


@dataclass(frozen=True)
class ComparisonLayout:
    root: Path

    @property
    def metrics_summary(self) -> Path:
        return self.root / "metrics_summary.json"


@dataclass(frozen=True)
class ProjectLayout:
    name: str
    root: Path

    @classmethod
    def from_name(cls, name: str) -> "ProjectLayout":
        return cls(name=sanitize_id(name), root=OUTPUTS_ROOT / sanitize_id(name))

    @property
    def manifest(self) -> Path:
        return self.root / "project.json"

    def dataset(self, dataset_id: str) -> DatasetLayout:
        return DatasetLayout(self.root / "datasets" / sanitize_id(dataset_id))

    def model(self, model_id: str) -> ModelLayout:
        return ModelLayout(self.root / "models" / sanitize_id(model_id))

    def generation(self, generation_id: str) -> GenerationLayout:
        return GenerationLayout(self.root / "generations" / sanitize_id(generation_id))

    def comparison(self, comparison_id: str) -> ComparisonLayout:
        return ComparisonLayout(self.root / "comparisons" / sanitize_id(comparison_id))

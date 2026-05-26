from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT / "projects"


def sanitize_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    return cleaned.strip("_") or "default"


def repo_path(path_text: str | Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def to_posix(path: Path) -> str:
    return str(path).replace("\\", "/")


def reset_dir(path: Path, *, allowed_root: Path = PROJECTS_ROOT) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to clear path outside {root}: {path}")
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


@dataclass(frozen=True)
class ScenarioSetLayout:
    root: Path


@dataclass(frozen=True)
class DatasetLayout:
    root: Path

    @property
    def dataset_json(self) -> Path:
        return self.root / "dataset.json"

    @property
    def cases_dir(self) -> Path:
        return self.root / "cases"

    @property
    def build_csv(self) -> Path:
        return self.root / "build.csv"

    @property
    def solve_csv(self) -> Path:
        return self.root / "solve.csv"

    @property
    def analyze_csv(self) -> Path:
        return self.root / "analyze.csv"


@dataclass(frozen=True)
class ModelLayout:
    root: Path

    @property
    def graph_dir(self) -> Path:
        return self.root / "graph"

    @property
    def sample_dir(self) -> Path:
        return self.graph_dir / "samples"

    @property
    def context_graph(self) -> Path:
        return self.graph_dir / "context.json"

    @property
    def train_config(self) -> Path:
        return self.root / "train_config.yml"

    @property
    def best_model(self) -> Path:
        return self.root / "best_model.pt"

    @property
    def generation_dir(self) -> Path:
        return self.root / "generated"


@dataclass(frozen=True)
class ProjectLayout:
    name: str
    root: Path

    @classmethod
    def from_name(cls, name: str) -> "ProjectLayout":
        project_id = sanitize_id(name)
        return cls(name=project_id, root=PROJECTS_ROOT / project_id)

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def scenario_sets_dir(self) -> Path:
        return self.root / "scenario_sets"

    @property
    def default_scenario_set(self) -> Path:
        return self.scenario_sets_dir / "default"

    @property
    def datasets_dir(self) -> Path:
        return self.root / "datasets"

    @property
    def model_dir(self) -> Path:
        return self.root / "model"

    @property
    def conf_dir(self) -> Path:
        return self.root / "conf"

    @property
    def context_json(self) -> Path:
        return self.root / "context.json"

    @property
    def prepare_config(self) -> Path:
        return self.conf_dir / "prepare.yml"

    @property
    def solve_config(self) -> Path:
        return self.conf_dir / "solve.yml"

    @property
    def analyze_config(self) -> Path:
        return self.conf_dir / "analyze.yml"

    def normal_generate_config(self, config_id: str) -> Path:
        return self.conf_dir / "normal_generate" / f"{sanitize_id(config_id)}.yml"

    def train_config(self, config_id: str) -> Path:
        return self.conf_dir / "train" / f"{sanitize_id(config_id)}.yml"

    def scenario_set(self, scenario_set_id: str) -> ScenarioSetLayout:
        return ScenarioSetLayout(self.scenario_sets_dir / sanitize_id(scenario_set_id))

    def dataset(self, dataset_id: str) -> DatasetLayout:
        return DatasetLayout(self.datasets_dir / sanitize_id(dataset_id))

    def model(self, model_id: str) -> ModelLayout:
        return ModelLayout(self.model_dir / sanitize_id(model_id))

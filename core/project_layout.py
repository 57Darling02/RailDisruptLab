from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT / "projects"


def sanitize_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    return cleaned.strip("_")


def require_id(value: object, field_name: str = "id") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing required field: {field_name}")
    cleaned = sanitize_id(text)
    if not cleaned:
        raise ValueError(f"Invalid {field_name}: {value}")
    return cleaned


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
    def cases_dir(self) -> Path:
        return self.root / "cases"


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
        return self.graph_dir / "math_context.json"

    @property
    def graph_progress(self) -> Path:
        return self.graph_dir / "graph_progress.json"

    @property
    def best_model(self) -> Path:
        return self.root / "best_model.pt"


@dataclass(frozen=True)
class ProjectLayout:
    name: str
    root: Path

    @classmethod
    def from_name(cls, name: str) -> "ProjectLayout":
        project_id = require_id(name, "project_id")
        return cls(name=project_id, root=PROJECTS_ROOT / project_id)

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def scenario_sets_dir(self) -> Path:
        return self.root / "scenario_sets"

    @property
    def datasets_dir(self) -> Path:
        return self.root / "datasets"

    @property
    def model_dir(self) -> Path:
        return self.root / "model"

    @property
    def context_json(self) -> Path:
        return self.root / "context.json"

    def scenario_set(self, scenario_set_id: str) -> ScenarioSetLayout:
        return ScenarioSetLayout(self.scenario_sets_dir / require_id(scenario_set_id, "scenario_set_id"))

    def dataset(self, dataset_id: str) -> DatasetLayout:
        return DatasetLayout(self.datasets_dir / require_id(dataset_id, "dataset_id"))

    def model(self, model_id: str) -> ModelLayout:
        return ModelLayout(self.model_dir / require_id(model_id, "model_id"))

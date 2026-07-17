from __future__ import annotations

import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import uuid4


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


@contextmanager
def replace_dir_with_rollback(path: Path, *, allowed_root: Path = PROJECTS_ROOT) -> Iterator[Path]:
    """Replace a project artifact directory, restoring its previous version on failure."""
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"Refusing to replace path outside {root}: {path}")
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError(f"Artifact path must be a directory: {path}")

    had_previous = path.is_dir()
    backup = path.with_name(f".{path.name}.backup-{uuid4().hex}")
    if had_previous:
        path.replace(backup)
    try:
        path.mkdir(parents=True, exist_ok=False)
    except BaseException:
        if had_previous and backup.exists() and not path.exists():
            backup.replace(path)
        raise

    try:
        yield path
    except BaseException:
        try:
            if path.exists():
                reset_dir(path, allowed_root=allowed_root)
        finally:
            if had_previous and backup.exists():
                backup.replace(path)
        raise
    else:
        if had_previous and backup.exists():
            reset_dir(backup, allowed_root=allowed_root)


@dataclass(frozen=True)
class ScenarioSetLayout:
    root: Path

    @property
    def scenarios_dir(self) -> Path:
        return self.root / "scenarios"

    @property
    def adjustment_plans_dir(self) -> Path:
        return self.root / "adjustment_plans"

    def scenario(self, scenario_id: str) -> "ScenarioCaseLayout":
        return ScenarioCaseLayout(self.scenarios_dir / f"{require_id(scenario_id, 'scenario_id')}.yml")

    def adjustment_plan(self, plan_id: str) -> "AdjustmentPlanLayout":
        return AdjustmentPlanLayout(self.adjustment_plans_dir / require_id(plan_id, "plan_id"))


@dataclass(frozen=True)
class ScenarioCaseLayout:
    path: Path

    @property
    def scenario_yml(self) -> Path:
        return self.path

    @property
    def root(self) -> Path:
        return self.path.parent


@dataclass(frozen=True)
class RunGraphSetLayout:
    root: Path

    @property
    def run_graphs_dir(self) -> Path:
        return self.root / "run_graphs"

    def run_graph(self, run_graph_id: str) -> "RunGraphLayout":
        return RunGraphLayout(self.run_graphs_dir / require_id(run_graph_id, "run_graph_id"))


@dataclass(frozen=True)
class RunGraphLayout:
    root: Path

    @property
    def source_dir(self) -> Path:
        return self.root / "source"

    @property
    def timetable_xlsx(self) -> Path:
        return self.source_dir / "timetable.xlsx"

    @property
    def mileage_xlsx(self) -> Path:
        return self.source_dir / "mileage.xlsx"

    @property
    def context_json(self) -> Path:
        return self.root / "context.json"

    @property
    def metadata_json(self) -> Path:
        return self.root / "metadata.json"


@dataclass(frozen=True)
class AdjustmentPlanLayout:
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
    def context_graph_dir(self) -> Path:
        return self.graph_dir / "contexts"

    @property
    def context_graph(self) -> Path:
        return self.graph_dir / "math_context.json"

    @property
    def graph_progress(self) -> Path:
        return self.graph_dir / "graph_progress.json"


@dataclass(frozen=True)
class ProjectLayout:
    name: str
    root: Path

    @classmethod
    def from_name(cls, name: str) -> "ProjectLayout":
        project_id = require_id(name, "project_id")
        return cls(name=project_id, root=PROJECTS_ROOT / project_id)

    @property
    def scenario_sets_dir(self) -> Path:
        return self.root / "scenario_sets"

    @property
    def run_graph_sets_dir(self) -> Path:
        return self.root / "run_graph_sets"

    @property
    def model_dir(self) -> Path:
        return self.root / "model"

    def scenario_set(self, scenario_set_id: str) -> ScenarioSetLayout:
        return ScenarioSetLayout(self.scenario_sets_dir / require_id(scenario_set_id, "scenario_set_id"))

    def run_graph_set(self, run_graph_set_id: str) -> RunGraphSetLayout:
        return RunGraphSetLayout(self.run_graph_sets_dir / require_id(run_graph_set_id, "run_graph_set_id"))

    def model(self, model_id: str) -> ModelLayout:
        return ModelLayout(self.model_dir / require_id(model_id, "model_id"))

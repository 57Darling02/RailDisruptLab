from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


SCENARIO_EXTENSIONS = {".yaml", ".yml"}
REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT / "projects"


@dataclass(frozen=True)
class ScenarioDocument:
    name: str
    scenarios: Dict[str, object]
    path: Optional[Path] = None


def load_scenarios_for_config(value: object, owner_path: Path, yaml: Any) -> Dict[str, object]:
    ref_path = scenario_reference_path(value, owner_path)
    if ref_path is not None:
        if ref_path.is_dir():
            return {"delays": [], "speed_limits": []}
        return load_scenario_document(ref_path, yaml).scenarios
    return scenario_document_from_payload(value or {}, owner_path.stem).scenarios


def expand_config_scenarios(payload: Dict[str, object], owner_path: Path, yaml: Any) -> List[ScenarioDocument]:
    build = payload.get("build") or {}
    if not isinstance(build, dict):
        raise ValueError(f"Config build section must be a YAML object: {owner_path}")
    value = build.get("scenarios", {})
    ref_path = scenario_reference_path(value, owner_path)
    if ref_path is None:
        return [scenario_document_from_payload(value or {}, _project_or_file_name(payload, owner_path))]
    if ref_path.is_dir():
        docs = [load_scenario_document(path, yaml) for path in scenario_files(ref_path)]
        if not docs:
            raise FileNotFoundError(f"No scenario YAML files found: {ref_path}")
        return docs
    return [load_scenario_document(ref_path, yaml)]


def scenario_files(root: Path) -> List[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SCENARIO_EXTENSIONS
    )


def load_scenario_document(path: Path, yaml: Any) -> ScenarioDocument:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Scenario file must be a YAML object: {path}")
    return scenario_document_from_payload(payload, path.stem, path=path)


def scenario_document_from_payload(
    payload: object,
    fallback_name: str,
    *,
    path: Optional[Path] = None,
) -> ScenarioDocument:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"Scenario payload must be a YAML object: {path or fallback_name}")

    scenario_node = payload.get("scenario")
    scenario_meta = scenario_node if isinstance(scenario_node, dict) else {}
    scenarios = _extract_scenarios(payload)
    if "interruptions" in scenarios:
        raise ValueError("Legacy interruptions are not supported; use speed_limits with limit_speed=0.")

    return ScenarioDocument(
        name=_clean_name(
            payload.get("name")
            or payload.get("case_id")
            or scenario_meta.get("name")
            or _project_name(payload)
            or fallback_name
        ),
        scenarios={
            "delays": copy.deepcopy(scenarios.get("delays", []) or []),
            "speed_limits": copy.deepcopy(scenarios.get("speed_limits", []) or []),
        },
        path=path,
    )


def scenario_reference_path(value: object, owner_path: Path) -> Optional[Path]:
    path_text = ""
    if isinstance(value, str):
        path_text = value
    elif isinstance(value, dict):
        for key in ("path", "file", "dir", "root"):
            if key in value and str(value.get(key, "")).strip():
                path_text = str(value[key])
                break
    if not path_text.strip():
        return None
    path = Path(path_text.strip())
    if path.is_absolute():
        return path
    return resolve_config_reference(path, owner_path)


def config_reference_base(owner_path: Path) -> Path:
    resolved = (owner_path if owner_path.is_absolute() else REPO_ROOT / owner_path).resolve()
    try:
        relative = resolved.relative_to(PROJECTS_ROOT)
    except ValueError:
        return REPO_ROOT
    if len(relative.parts) < 2:
        return REPO_ROOT
    return PROJECTS_ROOT / relative.parts[0]


def resolve_config_reference(path: Path, owner_path: Path) -> Path:
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] in {"config", "docs", "inputs", "outputs", "projects"}:
        return (REPO_ROOT / path).resolve()
    return (config_reference_base(owner_path) / path).resolve()


def _extract_scenarios(payload: Dict[str, object]) -> Dict[str, object]:
    build = payload.get("build")
    if isinstance(build, dict) and "scenarios" in build:
        scenarios = build.get("scenarios") or {}
    elif isinstance(payload.get("scenarios"), dict):
        scenarios = payload.get("scenarios") or {}
    elif isinstance(payload.get("scenario"), dict):
        scenarios = payload.get("scenario") or {}
    else:
        scenarios = payload
    if not isinstance(scenarios, dict):
        raise ValueError("scenarios must be a YAML object.")
    return scenarios


def _project_or_file_name(payload: Dict[str, object], path: Path) -> str:
    return _project_name(payload) or path.stem


def _project_name(payload: Dict[str, object]) -> str:
    project = payload.get("project")
    if isinstance(project, dict):
        return _clean_name(project.get("name"))
    return ""


def _clean_name(value: object) -> str:
    text = str(value or "").strip()
    return text or "case"

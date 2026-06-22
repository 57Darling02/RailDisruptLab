from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.project_layout import sanitize_id
from core.types import ScenarioConfig


SCENARIO_EXTENSIONS = {".yaml", ".yml"}
SCENARIO_CASES_DIRNAME = "scenarios"
SCENARIO_ALLOWED_KEYS = {"run_graph", "validation", "delays", "speed_limits"}
SCENARIO_EVENTS_KEYS = {"delays", "speed_limits"}
DELAY_ALLOWED_KEYS = {"train_id", "station", "event_type", "seconds"}
SPEED_LIMIT_ALLOWED_KEYS = {"start_station", "end_station", "start_time", "duration", "limit_speed"}
REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT / "projects"


@dataclass(frozen=True)
class RunGraphReference:
    set_id: str
    graph_id: str
    context_sha256: str = ""

    def to_payload(self, *, include_context_sha256: bool = True) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "set_id": self.set_id,
            "graph_id": self.graph_id,
        }
        if include_context_sha256 and self.context_sha256:
            payload["context_sha256"] = self.context_sha256
        return payload


@dataclass(frozen=True)
class ScenarioValidation:
    context_sha256: str = ""
    disturbances_sha256: str = ""
    validated_at: str = ""

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {}
        if self.context_sha256:
            payload["context_sha256"] = self.context_sha256
        if self.disturbances_sha256:
            payload["disturbances_sha256"] = self.disturbances_sha256
        if self.validated_at:
            payload["validated_at"] = self.validated_at
        return payload


@dataclass(frozen=True)
class ScenarioDocument:
    name: str
    run_graph: RunGraphReference
    scenarios: Dict[str, object]
    path: Optional[Path] = None
    validation: ScenarioValidation = field(default_factory=ScenarioValidation)


def load_scenarios_for_config(value: object, owner_path: Path, yaml: Any) -> Dict[str, object]:
    ref_path = scenario_reference_path(value, owner_path)
    if ref_path is not None:
        if ref_path.is_dir():
            return {"delays": [], "speed_limits": []}
        return load_scenario_document(ref_path, yaml).scenarios
    return scenario_events_from_payload(value or {}, owner_path)


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
    scenarios_root = root / SCENARIO_CASES_DIRNAME
    if not scenarios_root.is_dir():
        return []
    return sorted(
        path
        for path in scenarios_root.iterdir()
        if path.is_file() and path.suffix.lower() in SCENARIO_EXTENSIONS
    )


def scenario_file_by_id(root: Path, scenario_id: str) -> Optional[Path]:
    clean_id = sanitize_id(scenario_id)
    path = root / SCENARIO_CASES_DIRNAME / f"{clean_id}.yml"
    return path if path.is_file() else None


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

    unknown_keys = sorted(str(key) for key in payload.keys() if str(key) not in SCENARIO_ALLOWED_KEYS)
    if unknown_keys:
        raise ValueError(
            "Unsupported scenario YAML field(s): "
            f"{', '.join(unknown_keys)}. Use only run_graph, delays, and speed_limits."
        )
    if "interruptions" in payload:
        raise ValueError("Legacy interruptions are not supported; use speed_limits with limit_speed=0.")

    return ScenarioDocument(
        name=sanitize_id(fallback_name),
        run_graph=run_graph_reference_from_payload(payload.get("run_graph"), path or Path(fallback_name)),
        validation=scenario_validation_from_payload(payload, path or Path(fallback_name)),
        scenarios={
            "delays": scenario_event_list(payload.get("delays"), "delays", path or Path(fallback_name)),
            "speed_limits": scenario_event_list(payload.get("speed_limits"), "speed_limits", path or Path(fallback_name)),
        },
        path=path,
    )


def scenario_config_to_yaml(
    scenarios: ScenarioConfig,
    run_graph: RunGraphReference,
    validation: ScenarioValidation | None = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "run_graph": run_graph.to_payload(include_context_sha256=False),
    }
    if validation is not None and validation.to_payload():
        payload["validation"] = validation.to_payload()
    payload.update({
        "delays": [
            {
                "train_id": item.train_id,
                "station": item.station,
                "event_type": item.event_type,
                "seconds": int(item.seconds),
            }
            for item in scenarios.delays
        ],
        "speed_limits": [
            {
                "start_station": item.start_station,
                "end_station": item.end_station,
                "start_time": seconds_to_hms(item.start_time),
                "duration": int(item.duration),
                "limit_speed": clean_number(item.limit_speed),
            }
            for item in scenarios.speed_limits
        ],
    })
    return payload


def scenario_document_to_yaml(doc: ScenarioDocument) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "run_graph": doc.run_graph.to_payload(include_context_sha256=False),
    }
    if doc.validation.to_payload():
        payload["validation"] = doc.validation.to_payload()
    payload.update({
        "delays": copy.deepcopy(doc.scenarios.get("delays", []) or []),
        "speed_limits": copy.deepcopy(doc.scenarios.get("speed_limits", []) or []),
    })
    return payload


def scenario_disturbances_sha256(scenarios: Dict[str, object]) -> str:
    payload = {
        "delays": copy.deepcopy(scenarios.get("delays", []) or []),
        "speed_limits": copy.deepcopy(scenarios.get("speed_limits", []) or []),
    }
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def scenario_events_from_payload(payload: object, owner: Path) -> Dict[str, object]:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"Scenario events payload must be a YAML object: {owner}")
    unknown_keys = sorted(str(key) for key in payload.keys() if str(key) not in SCENARIO_EVENTS_KEYS)
    if unknown_keys:
        raise ValueError(
            "Unsupported scenario events field(s): "
            f"{', '.join(unknown_keys)}. Use only delays and speed_limits."
        )
    return {
        "delays": scenario_event_list(payload.get("delays"), "delays", owner),
        "speed_limits": scenario_event_list(payload.get("speed_limits"), "speed_limits", owner),
    }


def scenario_event_list(value: object, field_name: str, owner: Path) -> List[object]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Scenario {field_name} must be a list: {owner}")
    allowed_keys = event_allowed_keys(field_name)
    return [
        validate_semantic_event(item, field_name, index, allowed_keys, owner)
        for index, item in enumerate(value, start=1)
    ]


def event_allowed_keys(field_name: str) -> set[str]:
    if field_name == "delays":
        return DELAY_ALLOWED_KEYS
    if field_name == "speed_limits":
        return SPEED_LIMIT_ALLOWED_KEYS
    raise ValueError(f"Unsupported scenario event list: {field_name}")


def validate_semantic_event(
    value: object,
    field_name: str,
    index: int,
    allowed_keys: set[str],
    owner: Path,
) -> Dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"Scenario {field_name}[{index}] must be a YAML object: {owner}")
    unknown_keys = sorted(str(key) for key in value.keys() if str(key) not in allowed_keys)
    if unknown_keys:
        allowed = ", ".join(sorted(allowed_keys))
        raise ValueError(
            f"Unsupported scenario {field_name}[{index}] field(s): {', '.join(unknown_keys)}. "
            f"Scenario YAML must use semantic fields only: {allowed}."
        )
    missing = [key for key in sorted(allowed_keys) if not has_text(value, key)]
    if missing:
        raise ValueError(
            f"Missing scenario {field_name}[{index}] field(s): {', '.join(missing)}: {owner}"
        )
    return copy.deepcopy(value)


def has_text(payload: Dict[str, object], key: str) -> bool:
    return key in payload and str(payload.get(key, "")).strip() != ""


def run_graph_reference_from_payload(value: object, owner: Path) -> RunGraphReference:
    if not isinstance(value, dict):
        raise ValueError(f"Scenario run_graph must be a YAML object: {owner}")
    set_id = sanitize_id(str(value.get("set_id") or ""))
    graph_id = sanitize_id(str(value.get("graph_id") or ""))
    if not set_id:
        raise ValueError(f"Scenario run_graph.set_id is required: {owner}")
    if not graph_id:
        raise ValueError(f"Scenario run_graph.graph_id is required: {owner}")
    return RunGraphReference(set_id=set_id, graph_id=graph_id)


def scenario_validation_from_payload(payload: Dict[str, object], owner: Path) -> ScenarioValidation:
    value = payload.get("validation")
    if value is None:
        run_graph = payload.get("run_graph")
        legacy_context_sha256 = ""
        if isinstance(run_graph, dict):
            legacy_context_sha256 = str(run_graph.get("context_sha256") or "").strip()
        return ScenarioValidation(context_sha256=legacy_context_sha256)
    if not isinstance(value, dict):
        raise ValueError(f"Scenario validation must be a YAML object: {owner}")
    return ScenarioValidation(
        context_sha256=str(value.get("context_sha256") or "").strip(),
        disturbances_sha256=str(value.get("disturbances_sha256") or "").strip(),
        validated_at=str(value.get("validated_at") or "").strip(),
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


def seconds_to_hms(seconds: int) -> str:
    total = max(0, min(24 * 3600 - 1, int(seconds)))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def clean_number(value: float) -> object:
    number = float(value)
    return int(number) if number.is_integer() else number

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.project_layout import ProjectLayout, require_id, sanitize_id
from core.scenario_config import SCENARIO_EXTENSIONS


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy scenario YAML files to scenario-level contexts.")
    parser.add_argument("project_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    layout = ProjectLayout.from_name(args.project_id)
    if not layout.context_json.is_file():
        raise FileNotFoundError(f"Missing project context for migration: {layout.context_json}")
    if not layout.scenario_sets_dir.is_dir():
        raise FileNotFoundError(f"Missing scenario_sets directory: {layout.scenario_sets_dir}")

    for scenario_set_dir in sorted(path for path in layout.scenario_sets_dir.iterdir() if path.is_dir()):
        legacy_files = [
            path
            for path in sorted(scenario_set_dir.iterdir())
            if path.is_file() and path.suffix.lower() in SCENARIO_EXTENSIONS
        ]
        for source in legacy_files:
            scenario_id = sanitize_id(source.stem)
            require_id(scenario_id, "scenario_id")
            target_dir = scenario_set_dir / "scenarios" / scenario_id
            scenario_target = target_dir / "scenario.yml"
            context_target = target_dir / "context.json"
            print(f"{source} -> {scenario_target}")
            if args.dry_run:
                continue
            if target_dir.exists():
                raise FileExistsError(f"Refusing to overwrite migrated scenario: {target_dir}")
            target_dir.mkdir(parents=True, exist_ok=False)
            shutil.move(str(source), scenario_target)
            shutil.copy2(layout.context_json, context_target)


if __name__ == "__main__":
    main()

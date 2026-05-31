from __future__ import annotations

import argparse
import signal
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.file_ops import copy_or_link_file, file_digest
from core.project_layout import ProjectLayout, require_id, sanitize_id
from core.scenario_config import SCENARIO_EXTENSIONS


def main() -> None:
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    parser = argparse.ArgumentParser(description="Migrate legacy project products to scenario-level contexts.")
    parser.add_argument("project_id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dedupe-contexts", action="store_true")
    parser.add_argument("--dataset-contexts", action="store_true")
    parser.add_argument("--overwrite-dataset-contexts", action="store_true")
    args = parser.parse_args()

    layout = ProjectLayout.from_name(args.project_id)

    if args.dedupe_contexts:
        require_scenario_sets_dir(layout)
        dedupe_contexts(layout, dry_run=args.dry_run)
        return

    if args.dataset_contexts:
        require_scenario_sets_dir(layout)
        migrate_dataset_contexts(
            layout,
            dry_run=args.dry_run,
            overwrite=args.overwrite_dataset_contexts,
        )
        return

    require_scenario_sets_dir(layout)
    migrate_project(
        layout,
        dry_run=args.dry_run,
        overwrite_dataset_contexts=args.overwrite_dataset_contexts,
    )


@dataclass(frozen=True)
class ScenarioMigration:
    scenario_set_id: str
    scenario_id: str
    source: Path
    target_dir: Path
    scenario_target: Path
    context_target: Path


def migrate_project(layout: ProjectLayout, *, dry_run: bool, overwrite_dataset_contexts: bool) -> None:
    migrations = legacy_scenario_migrations(layout)
    if migrations and not layout.context_json.is_file():
        raise FileNotFoundError(f"Missing project context for migration: {layout.context_json}")
    migrate_legacy_scenarios(layout, migrations, dry_run=dry_run)
    planned_contexts = {
        (migration.scenario_set_id, migration.scenario_id): migration.context_target
        for migration in migrations
    }
    migrate_dataset_contexts(
        layout,
        dry_run=dry_run,
        overwrite=overwrite_dataset_contexts,
        planned_contexts=planned_contexts,
    )


def legacy_scenario_migrations(layout: ProjectLayout) -> list[ScenarioMigration]:
    migrations: list[ScenarioMigration] = []
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
            migrations.append(
                ScenarioMigration(
                    scenario_set_id=scenario_set_dir.name,
                    scenario_id=scenario_id,
                    source=source,
                    target_dir=target_dir,
                    scenario_target=scenario_target,
                    context_target=context_target,
                )
            )
    return migrations


def migrate_legacy_scenarios(
    layout: ProjectLayout,
    migrations: list[ScenarioMigration],
    *,
    dry_run: bool,
) -> None:
    stats = {"checked": len(migrations), "migrated": 0, "would_migrate": 0}
    for migration in migrations:
        print(f"{migration.source} -> {migration.scenario_target}")
        if dry_run:
            stats["would_migrate"] += 1
            continue
        if migration.target_dir.exists():
            raise FileExistsError(f"Refusing to overwrite migrated scenario: {migration.target_dir}")
        migration.target_dir.mkdir(parents=True, exist_ok=False)
        shutil.move(str(migration.source), migration.scenario_target)
        copy_or_link_file(layout.context_json, migration.context_target)
        stats["migrated"] += 1
    print(
        "scenario files: "
        f"checked={stats['checked']} migrated={stats['migrated']} "
        f"would_migrate={stats['would_migrate']}"
    )


def require_scenario_sets_dir(layout: ProjectLayout) -> None:
    if not layout.scenario_sets_dir.is_dir():
        raise FileNotFoundError(f"Missing scenario_sets directory: {layout.scenario_sets_dir}")


def migrate_dataset_contexts(
    layout: ProjectLayout,
    *,
    dry_run: bool,
    overwrite: bool,
    planned_contexts: dict[tuple[str, str], Path] | None = None,
) -> None:
    if not layout.datasets_dir.is_dir():
        print(f"dataset contexts: checked=0 linked=0 would_link=0 skipped=0 missing=0")
        return

    stats = {"checked": 0, "linked": 0, "would_link": 0, "skipped": 0, "missing": 0}
    for build_path in sorted(layout.datasets_dir.glob("*/cases/*/build.json")):
        stats["checked"] += 1
        case_dir = build_path.parent
        target = case_dir / "context.json"
        if target.is_file() and not overwrite:
            stats["skipped"] += 1
            continue

        source = dataset_case_context_source(layout, build_path, planned_contexts=planned_contexts)
        if source is None:
            stats["missing"] += 1
            print(f"missing context source for {build_path}")
            continue

        print(f"{source} -> {target}")
        if dry_run:
            stats["would_link"] += 1
            continue
        copy_or_link_file(source, target)
        stats["linked"] += 1

    print(
        "dataset contexts: "
        f"checked={stats['checked']} linked={stats['linked']} would_link={stats['would_link']} "
        f"skipped={stats['skipped']} missing={stats['missing']}"
    )


def dataset_case_context_source(
    layout: ProjectLayout,
    build_path: Path,
    *,
    planned_contexts: dict[tuple[str, str], Path] | None = None,
) -> Path | None:
    payload = read_json(build_path)
    scenario_set_id = sanitize_id(str(payload.get("scenario_set_id") or ""))
    scenario_id = sanitize_id(str(payload.get("source_scenario_id") or payload.get("case_id") or build_path.parent.name))
    if not scenario_set_id or not scenario_id:
        return None
    planned = (planned_contexts or {}).get((scenario_set_id, scenario_id))
    if planned is not None:
        return planned
    source = layout.scenario_set(scenario_set_id).scenario(scenario_id).context_json
    return source if source.is_file() else None


def dedupe_contexts(layout: ProjectLayout, *, dry_run: bool) -> None:
    contexts = sorted(layout.scenario_sets_dir.glob("*/scenarios/*/context.json"))
    canonical_by_digest: dict[str, Path] = {}
    for context in contexts:
        digest = file_digest(context)
        canonical = canonical_by_digest.setdefault(digest, context)
        if canonical == context:
            continue
        if same_inode(canonical, context):
            continue
        print(f"{context} -> hardlink {canonical}")
        if dry_run:
            continue
        copy_or_link_file(canonical, context)


def same_inode(left: Path, right: Path) -> bool:
    try:
        return left.stat().st_ino == right.stat().st_ino and left.stat().st_dev == right.stat().st_dev
    except OSError:
        return False


def read_json(path: Path) -> dict[str, object]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


if __name__ == "__main__":
    main()

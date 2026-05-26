from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.base_context import build_base_context, default_base_context_path, write_base_context
from core.loader import load_mileage_table, load_timetable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a BaseContext JSON from timetable and mileage inputs.")
    parser.add_argument("--timetable-path", required=True, help="Path to timetable .xlsx.")
    parser.add_argument("--mileage-path", required=True, help="Path to mileage .xlsx.")
    parser.add_argument("--timetable-sheet-name", default="Sheet1")
    parser.add_argument("--mileage-sheet-name", default="Sheet1")
    parser.add_argument("--output-path", default="", help="Defaults to outputs/base_context/context_<timetable stem>.json.")
    return parser.parse_args()


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def main() -> None:
    args = parse_args()
    timetable_path = _resolve(args.timetable_path)
    mileage_path = _resolve(args.mileage_path)
    output_path = _resolve(args.output_path) if args.output_path.strip() else default_base_context_path(timetable_path)

    timetable = load_timetable(timetable_path, args.timetable_sheet_name)
    mileage = load_mileage_table(mileage_path, args.mileage_sheet_name)
    context = build_base_context(
        timetable_path=timetable_path,
        mileage_path=mileage_path,
        timetable_sheet_name=args.timetable_sheet_name,
        mileage_sheet_name=args.mileage_sheet_name,
        timetable_table=timetable,
        mileage_table=mileage,
    )
    write_base_context(context, output_path)

    print(f"BaseContext exported: {output_path}")
    print(f"Trains: {len(context.translated.train_ids)}")
    print(f"Events: {len(context.translated.event_keys)}")
    print(f"EventAnchors: {len(context.event_anchors)}")
    print(f"SectionAnchors: {len(context.section_anchors)}")


if __name__ == "__main__":
    main()

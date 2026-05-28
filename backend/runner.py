from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from backend.task_contracts import read_task_input, run_task_payload


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run a backend task snapshot.")
    parser.add_argument("task_input", type=Path)
    args = parser.parse_args(argv)
    run_task_payload(read_task_input(args.task_input))


if __name__ == "__main__":
    main()

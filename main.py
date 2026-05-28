from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from core.project_layout import REPO_ROOT


FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
TASK_PARALLEL_ENV = "R2G_TASK_PARALLEL"
TASK_PARALLEL = 8


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RailGraph2Gurobi backend.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    os.environ.setdefault(TASK_PARALLEL_ENV, str(TASK_PARALLEL))

    if not (FRONTEND_DIST / "index.html").is_file():
        print(
            "Frontend dist not found. The backend API will still start, but '/' has no built UI yet.\n"
            "Build it with: pnpm --dir frontend build\n"
            "For development, run the Vue dev server separately: pnpm --dir frontend dev",
            file=sys.stderr,
        )

    uvicorn.run("backend.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()

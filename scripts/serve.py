#!/usr/bin/env python3
"""Serve the built Crystal Material Universe frontend and API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from materials_api.app import create_app  # noqa: E402
from materials_api.layout import RepositoryLayout  # noqa: E402


LAYOUT = RepositoryLayout.from_root(PROJECT_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--runtime", type=Path, default=LAYOUT.index)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database = args.runtime / "materials.sqlite"
    blobs = args.runtime / "structures.blob"
    if not database.is_file() or not blobs.is_file():
        raise SystemExit(f"index not found in {args.runtime}; run scripts/build_index.py first")
    app = create_app(
        database_path=database,
        blob_path=blobs,
        frontend_dir=LAYOUT.frontend_static,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate both MateriaViva source datasets and write canonical manifests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from materials_api.data_contract import validate_source_dataset, write_manifest  # noqa: E402
from materials_api.layout import RepositoryLayout  # noqa: E402


EXPECTED_COUNTS = {"experimental": 99_162, "candidate": 6_120_140}
LAYOUT = RepositoryLayout.from_root(PROJECT_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experimental", type=Path, default=LAYOUT.experimental_source)
    parser.add_argument("--candidate", type=Path, default=LAYOUT.candidate_source)
    parser.add_argument("--manifest-dir", type=Path, default=LAYOUT.data / "manifests")
    parser.add_argument(
        "--no-count-check",
        action="store_true",
        help="validate schema and records without enforcing the released row counts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reports = {}
    for role, source in (
        ("experimental", args.experimental),
        ("candidate", args.candidate),
    ):
        report = validate_source_dataset(source, role=role)
        expected = EXPECTED_COUNTS[role]
        if not args.no_count_check and report.total_records != expected:
            raise SystemExit(
                f"{role} row count mismatch: expected {expected:,}, "
                f"found {report.total_records:,}"
            )
        write_manifest(report, args.manifest_dir / f"{role}.json")
        reports[role] = report.to_manifest()
    print(json.dumps(reports, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build a searchable SQLite/blob index from the two crystal CSV datasets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from materials_api.data_contract import validate_source_dataset, write_manifest  # noqa: E402
from materials_api.indexer import IndexConfig, build_index  # noqa: E402
from materials_api.layout import RepositoryLayout  # noqa: E402


LAYOUT = RepositoryLayout.from_root(PROJECT_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experimental",
        type=Path,
        default=LAYOUT.experimental_source,
        help="directory containing experimental train.csv and val.csv",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=LAYOUT.candidate_source,
        help="directory containing candidate train.csv and val.csv",
    )
    parser.add_argument(
        "--stats",
        type=Path,
        default=LAYOUT.stats,
        help="optional exp_spg.tsv and pool_spg.tsv directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=LAYOUT.index,
        help="runtime index directory",
    )
    parser.add_argument(
        "--limit-per-dataset",
        type=int,
        default=None,
        help="development-only row limit for each dataset",
    )
    parser.add_argument("--commit-every", type=int, default=5_000)
    parser.add_argument("--compression-level", type=int, choices=range(0, 10), default=3)
    parser.add_argument(
        "--skip-source-validation",
        action="store_true",
        help="skip the full Crystal Record v1 scan (development only)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for label, path in (("experimental", args.experimental), ("candidate", args.candidate)):
        if not (path / "train.csv").is_file():
            raise SystemExit(f"{label} dataset is missing train.csv: {path}")
        if not args.skip_source_validation:
            validation = validate_source_dataset(path, role=label)
            manifest_path = LAYOUT.data / "manifests" / f"{label}.json"
            write_manifest(validation, manifest_path)
            print(
                f"[{label}] Crystal Record v1 validated: "
                f"{validation.total_records:,} rows",
                file=sys.stderr,
                flush=True,
            )
    report = build_index(IndexConfig(
        experimental_dir=args.experimental,
        candidate_dir=args.candidate,
        output_dir=args.output,
        stats_dir=args.stats if args.stats.is_dir() else None,
        limit_per_dataset=args.limit_per_dataset,
        commit_every=args.commit_every,
        compression_level=args.compression_level,
        progress_callback=lambda dataset, dataset_count, total: print(
            f"[{dataset}] {dataset_count:,} rows; total {total:,}",
            file=sys.stderr,
            flush=True,
        ),
    ))
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

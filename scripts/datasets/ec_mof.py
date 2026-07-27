#!/usr/bin/env python3
"""Acquire EC-MOF Phase-I bulk/monolayer endpoints and their property tables."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from scripts.datasets.acquire import _download_item, default_data_root


BASE_URL = "https://ec-mof.njit.edu"
SOURCE = {"id": "ec-mof", "data_path": "raw/acquired/ec-mof"}
METALS = ("Co", "Cu", "Fe", "Mn", "Ni", "Pd", "Pt", "Zn")
GROUPS = ("I", "H", "T")
SECOND_METALS = ("Co", "Cu", "Fe", "Ni", "Pd", "Zn")
MODELS = ("Bulk", "Mono")


def build_candidate_stems() -> list[str]:
    """Reproduce the finite selector space encoded by the official EC-MOF page."""
    stems: set[str] = set()
    for metal in METALS:
        for model in MODELS:
            stems.add(f"{metal}HAT_{model}")

        for linker in ("B", "TP", "TC", "HATN", "TN", "TT", "TX"):
            for group in GROUPS:
                for model in MODELS:
                    stems.add(f"{metal}H{group}{linker}_{model}")

        for group in GROUPS:
            for model in MODELS:
                stems.add(f"{metal}P{group}C_{model}")
                stems.add(f"{metal}O{group}Pc_{model}")
                stems.add(f"{metal}O{group}NPc_{model}")

        for linker in ("Pc", "NPc"):
            for group in GROUPS:
                for second_metal in SECOND_METALS:
                    for model in MODELS:
                        stems.add(f"{metal}O{group}{linker}{second_metal}_{model}")
    return sorted(stems)


def _item(stem: str, kind: str) -> dict[str, str]:
    if kind == "structure":
        return {
            "filename": f"structures/{stem}.cif",
            "url": f"{BASE_URL}/MOFdata/{stem}.cif",
        }
    if kind == "properties":
        return {
            "filename": f"properties/{stem}.html",
            "url": f"{BASE_URL}/mofsdb.php?q={stem}",
        }
    raise ValueError(f"unknown EC-MOF item kind: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--limit", type=int, help="Optional smoke-test limit")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    stems = build_candidate_stems()
    if args.limit is not None:
        stems = stems[: args.limit]
    data_root = default_data_root()
    failures: list[dict[str, Any]] = []
    downloaded = 0

    for index, stem in enumerate(stems, start=1):
        try:
            structure = _download_item(data_root, SOURCE, _item(stem, "structure"), retries=0)
        except subprocess.CalledProcessError as exc:
            failures.append({"stem": stem, "kind": "structure", "returncode": exc.returncode})
            print(f"[{index}/{len(stems)}] unavailable: {stem}", flush=True)
            time.sleep(args.delay)
            continue

        time.sleep(args.delay)
        try:
            properties = _download_item(data_root, SOURCE, _item(stem, "properties"), retries=0)
        except subprocess.CalledProcessError as exc:
            failures.append({"stem": stem, "kind": "properties", "returncode": exc.returncode})
            print(f"[{index}/{len(stems)}] structure only: {structure}", flush=True)
        else:
            downloaded += 1
            print(f"[{index}/{len(stems)}] {structure} | {properties}", flush=True)
        time.sleep(args.delay)

    manifest = {
        "source_id": "ec-mof",
        "official_selector_candidates": len(build_candidate_stems()),
        "requested_candidates": len(stems),
        "downloaded_structure_property_pairs": downloaded,
        "failures": failures,
        "complete": args.limit is None and not failures,
    }
    manifest_path = Path(data_root) / SOURCE["data_path"] / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    building = manifest_path.with_name(manifest_path.name + ".building")
    building.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

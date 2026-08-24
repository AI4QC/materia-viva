#!/usr/bin/env python3
"""Golden samples for property adapters: freeze what an adapter emits.

An adapter turns one source's raw files into `SourceRecord`s, and 55 of them
currently have no test at all — so a changed unit, a dropped field or a broken
regex reaches the published property rows unnoticed. A golden sample is a small
raw fixture plus the records the adapter is expected to emit from it, compared
field by field.

Two uses, deliberately distinguished by `authored_by` in the golden file, because
conflating them is how a zero diff comes to mean nothing:

* `recorded-from-adapter` — the expectation was produced by running the adapter.
  This proves behaviour has not *changed*; it cannot prove the mapping is right,
  since a wrong mapping would have been recorded just as faithfully.
* `independent` — the expectation was written from the upstream documentation by
  someone who did not see the adapter. Only this can gate a *new* adapter, and
  the framework cannot verify the claim; it only carries it so a reviewer can.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
from pathlib import Path
from typing import Any

from scripts.properties.base import SourceAdapter, SourceRecord
from scripts.properties.registry import CANONICAL_PROPERTIES

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = PROJECT_ROOT / "backend" / "tests" / "golden"


def adapter_class(source_key: str) -> type[SourceAdapter]:
    module = importlib.import_module(
        f"scripts.properties.adapters.{source_key.replace('-', '_')}"
    )
    found = [
        obj
        for _name, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, SourceAdapter)
        and obj is not SourceAdapter
        and obj.source_key == source_key
    ]
    if len(found) != 1:
        raise SystemExit(
            f"expected exactly one adapter for {source_key!r} in {module.__name__}, "
            f"found {[c.__name__ for c in found]}"
        )
    return found[0]


def serialise(record: SourceRecord) -> dict[str, Any]:
    """One record as comparable JSON.

    The structure is reduced to a digest of its CIF: the point of comparison is
    the mapping, and a full CIF would make every diff unreadable. A pymatgen
    upgrade can legitimately move the digest, in which case the diff shows only
    digests moving and no property changing.
    """
    cif = record.structure_cif()
    properties = sorted(
        (
            {"name": p.name, "value": p.value, "unit": p.unit, "method": p.method}
            for p in record.properties
        ),
        key=lambda p: (p["name"], p["method"] or "", str(p["value"])),
    )
    return {
        "native_id": record.native_id,
        "experimental": record.experimental,
        "match_ids": sorted([list(pair) for pair in record.match_ids]),
        "structure": None if cif is None else "sha256:" + hashlib.sha256(cif.encode()).hexdigest(),
        "properties": properties,
    }


def run_adapter(source_key: str, raw_root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    adapter = adapter_class(source_key)(root=raw_root)
    return [serialise(record) for record in adapter.iter_records(limit=limit)]


def unit_violations(records: list[dict[str, Any]]) -> list[str]:
    """Canonical property names must carry the registry's unit, exactly."""
    problems = []
    for record in records:
        for prop in record["properties"]:
            canonical = CANONICAL_PROPERTIES.get(prop["name"])
            if canonical is None:
                continue
            expected_unit = canonical[0]
            if prop["unit"] != expected_unit:
                problems.append(
                    f"{record['native_id']}: {prop['name']} carries unit "
                    f"{prop['unit']!r}, registry says {expected_unit!r}"
                )
    return problems


def diff(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> list[str]:
    lines = []
    if len(expected) != len(actual):
        lines.append(f"record count: expected {len(expected)}, got {len(actual)}")
    for index, (want, got) in enumerate(zip(expected, actual)):
        for field in ("native_id", "experimental", "match_ids", "structure"):
            if want.get(field) != got.get(field):
                lines.append(f"[{index}] {field}: expected {want.get(field)!r}, got {got.get(field)!r}")
        if want.get("properties") != got.get("properties"):
            # both sides through the same dump: a diff a human has to read must
            # not differ only in key order
            lines.append(
                f"[{index}] {want.get('native_id')}: properties differ\n"
                f"      expected {json.dumps(want.get('properties'), sort_keys=True)}\n"
                f"      got      {json.dumps(got.get('properties'), sort_keys=True)}"
            )
    return lines


def golden_dir(source_key: str) -> Path:
    return GOLDEN_ROOT / source_key


def check(source_key: str) -> list[str]:
    """Run the adapter against its fixture and return every complaint."""
    directory = golden_dir(source_key)
    golden = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    actual = run_adapter(source_key, directory / "raw", limit=golden.get("limit"))
    return diff(golden["records"], actual) + unit_violations(actual)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True)
    parser.add_argument(
        "--record",
        action="store_true",
        help="write expected.json from the adapter's current output "
             "(a regression baseline, not a correctness oracle)",
    )
    args = parser.parse_args(argv)

    directory = golden_dir(args.source)
    if not (directory / "raw").is_dir():
        parser.error(f"no fixture at {directory / 'raw'}")

    if args.record:
        records = run_adapter(args.source, directory / "raw")
        (directory / "expected.json").write_text(
            json.dumps(
                {
                    "source_key": args.source,
                    "authored_by": "recorded-from-adapter",
                    "records": records,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"recorded {len(records)} records to {directory / 'expected.json'}")
        for problem in unit_violations(records):
            print(f"  unit: {problem}")
        return 0

    problems = check(args.source)
    if problems:
        print(f"{args.source}: {len(problems)} problem(s)")
        for line in problems:
            print(f"  {line}")
        return 1
    print(f"{args.source}: golden sample matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

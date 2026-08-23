#!/usr/bin/env python3
"""Per-source staging pipeline: adapt -> (hash) -> match.

Every stage is resumable and leaves its artifacts under
``data/props_work/<source>/``:

* ``staging_props.tsv.gz``    native_id, property, value_num, value_text, unit, method
* ``id_matches.tsv.gz``       native_id, material_id, via
* ``staging_structs.jsonl.gz`` records that still need fingerprint matching
* ``hashes.tsv.gz``           native_id, n_sites, bawl_hash
* ``matched.tsv.gz``          native_id, material_id, via   (id + hash matches)
* ``new_structs.jsonl.gz``    admitted structures the pool does not contain
* ``report.json``             stage counters

Matching an already-loaded source again is safe: the loader records admitted
new-structure fingerprints back into the match map, so re-runs and later
sources resolve them as ordinary hash matches.
"""

from __future__ import annotations

import argparse
import gzip
import importlib
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.properties.base import WORK_ROOT, SourceAdapter, default_nproc  # noqa: E402
from scripts.properties.cif_trim import trim_cif  # noqa: E402
from scripts.properties.match_map import DEFAULT_OUT as MATCH_MAP  # noqa: E402

BATCH = 2_000


def _clean(value: str) -> str:
    """Keep staged TSV cells single-line and tab-free."""

    return value.replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()


def load_adapter(source: str) -> SourceAdapter:
    module_name = source.replace("-", "_")
    module = importlib.import_module(f"scripts.properties.adapters.{module_name}")
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, SourceAdapter)
            and value is not SourceAdapter
            and value.source_key == source
        ):
            return value()
    raise SystemExit(f"no adapter class with source_key={source!r} in {module_name}")


class MatchLookup:
    """Batched lookups against match_map.sqlite."""

    def __init__(self, path: Path) -> None:
        if not path.exists():
            raise SystemExit(f"match map missing, run match_map.py first: {path}")
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def by_ids(self, pairs: list[tuple[str, str]]) -> dict[tuple[str, str], list[str]]:
        result: dict[tuple[str, str], list[str]] = {}
        for start in range(0, len(pairs), 400):
            chunk = pairs[start : start + 400]
            placeholders = ",".join("(?,?)" for _ in chunk)
            flat = [item for pair in chunk for item in pair]
            for source, native_id, material_id in self.db.execute(
                f"SELECT source, native_id, material_id FROM id_map "
                f"WHERE (source, native_id) IN (VALUES {placeholders})",
                flat,
            ):
                result.setdefault((source, native_id), []).append(material_id)
        return result

    def by_hashes(self, hashes: list[str]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for start in range(0, len(hashes), 800):
            chunk = hashes[start : start + 800]
            placeholders = ",".join("?" for _ in chunk)
            for hashed, material_id in self.db.execute(
                f"SELECT hash, material_id FROM hash_map "
                f"WHERE hash IN ({placeholders})",
                chunk,
            ):
                result.setdefault(hashed, []).append(material_id)
        return result


def stage_adapt(source: str, limit: int | None) -> dict:
    adapter = load_adapter(source)
    work = WORK_ROOT / source
    work.mkdir(parents=True, exist_ok=True)
    lookup = MatchLookup(MATCH_MAP)
    counters: Counter[str] = Counter()
    started = time.time()

    props_path = work / "staging_props.tsv.gz"
    ids_path = work / "id_matches.tsv.gz"
    structs_path = work / "staging_structs.jsonl.gz"

    batch: list = []

    with gzip.open(props_path.with_suffix(".part"), "wt", encoding="utf-8") as props, \
            gzip.open(ids_path.with_suffix(".part"), "wt", encoding="utf-8") as ids, \
            gzip.open(structs_path.with_suffix(".part"), "wt", encoding="utf-8") as structs:
        props.write("native_id\tproperty\tvalue_num\tvalue_text\tunit\tmethod\n")
        ids.write("native_id\tmaterial_id\tvia\n")

        def flush() -> None:
            if not batch:
                return
            wanted = [pair for record in batch for pair in record.match_ids]
            found = lookup.by_ids(wanted) if wanted else {}
            for record in batch:
                counters["records"] += 1
                native_id = _clean(record.native_id)
                n_props = 0
                for prop in record.properties:
                    value_num, value_text = prop.as_row()
                    if value_num is None and value_text is None:
                        continue
                    props.write("\t".join((
                        native_id,
                        _clean(prop.name),
                        "" if value_num is None else repr(value_num),
                        _clean(value_text or ""),
                        _clean(prop.unit or ""),
                        _clean(prop.method or ""),
                    )) + "\n")
                    n_props += 1
                counters["property_rows"] += n_props
                material_ids: dict[str, str] = {}
                for pair in record.match_ids:
                    for material_id in found.get(pair, ()):
                        material_ids.setdefault(material_id, f"id:{pair[0]}")
                if material_ids:
                    counters["id_matched"] += 1
                    for material_id, via in material_ids.items():
                        ids.write(f"{native_id}\t{material_id}\t{via}\n")
                    if not adapter.always_hash:
                        continue
                cif = record.structure_cif()
                if cif:
                    structs.write(json.dumps({
                        "native_id": native_id,
                        "cif": cif,
                        "experimental": record.experimental,
                    }, ensure_ascii=False) + "\n")
                    counters["needs_hash"] += 1
                else:
                    counters["unmatched_no_structure"] += 1
            batch.clear()

        for record in adapter.iter_records(limit=limit):
            batch.append(record)
            if len(batch) >= BATCH:
                flush()
                if counters["records"] % 100_000 < BATCH:
                    print(
                        f"[{source}] {counters['records']:,} records, "
                        f"{counters['id_matched']:,} id-matched, "
                        f"{counters['needs_hash']:,} queued for hashing "
                        f"({time.time() - started:.0f}s)",
                        flush=True,
                    )
        flush()

    for path in (props_path, ids_path, structs_path):
        path.with_suffix(".part").replace(path)
    counters["adapt_minutes"] = round((time.time() - started) / 60, 1)
    return dict(counters)


def stage_hash(source: str, nproc: int) -> dict:
    from scripts.properties.hashing import run as run_hash

    work = WORK_ROOT / source
    structs_path = work / "staging_structs.jsonl.gz"
    out = work / "hashes.tsv.gz"
    with gzip.open(structs_path, "rt", encoding="utf-8") as handle:
        if handle.read(1) == "":
            out_handle = gzip.open(out, "wt", encoding="utf-8")
            out_handle.write("native_id\tn_sites\tformula\tbawl_hash\n")
            out_handle.close()
            return {"hashed": 0, "hash_failed": 0}
    return run_hash(structs_path, out, nproc=nproc, chunk=32)


def stage_match(source: str) -> dict:
    work = WORK_ROOT / source
    adapter = load_adapter(source)
    lookup = MatchLookup(MATCH_MAP)
    counters: Counter[str] = Counter()

    hash_rows: dict[str, tuple[str, int, str]] = {}
    with gzip.open(work / "hashes.tsv.gz", "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, n_sites, formula, hashed = line.rstrip("\n").split("\t")
            if hashed.startswith("FAIL:"):
                counters[f"fail:{hashed.split(':')[1]}"] += 1
                counters["hash_failed"] += 1
            else:
                hash_rows[native_id] = (hashed, int(n_sites), formula)

    found = lookup.by_hashes(list({hashed for hashed, _, _ in hash_rows.values()}))

    matched_path = work / "matched.tsv.gz"
    new_path = work / "new_structs.jsonl.gz"
    alias_path = work / "alias.tsv.gz"
    #: fingerprint -> the native_id admitted for it from this source
    seen_new: dict[str, str] = {}
    with gzip.open(matched_path.with_suffix(".part"), "wt", encoding="utf-8") as matched, \
            gzip.open(alias_path.with_suffix(".part"), "wt", encoding="utf-8") as alias_out, \
            gzip.open(new_path.with_suffix(".part"), "wt", encoding="utf-8") as new_out, \
            gzip.open(work / "id_matches.tsv.gz", "rt", encoding="utf-8") as ids, \
            gzip.open(work / "staging_structs.jsonl.gz", "rt", encoding="utf-8") as structs:
        matched.write("native_id\tmaterial_id\tvia\n")
        next(ids)
        for line in ids:
            matched.write(line)
            counters["matched_by_id_rows"] += 1
        for line in structs:
            payload = json.loads(line)
            native_id = payload["native_id"]
            if native_id not in hash_rows:
                continue
            hashed, n_sites, formula = hash_rows[native_id]
            hits = found.get(hashed)
            if hits:
                counters["matched_by_hash"] += 1
                for material_id in dict.fromkeys(hits):
                    matched.write(f"{native_id}\t{material_id}\thash\n")
            elif adapter.properties_only:
                counters["unmatched_dropped"] += 1
            elif hashed in seen_new:
                # Same fingerprint as a record already admitted from this very
                # source — one structure, but the records are NOT interchangeable:
                # Alexandria's agm-X / agm-X:pbesol / agm-X:scan are the same
                # crystal computed with three functionals, each carrying its own
                # properties. Alias the duplicate to the canonical record so the
                # loader attaches its properties to the same material instead of
                # dropping them.
                counters["duplicate_within_source"] += 1
                alias_out.write(f"{native_id}\t{seen_new[hashed]}\n")
            else:
                seen_new[hashed] = native_id
                # First place an admitted structure's text is persisted for the
                # loader, so it is where the non-structural payload gets cut.
                # Deliberately NOT applied before the hash stage: COD was
                # already hashed on full text, and trimming is fingerprint-
                # preserving (cif_trim_verify.py checks the primitive-reduced
                # BAWL hash of trimmed vs original), so `hashed` stays valid.
                payload["cif"] = trim_cif(payload["cif"])
                payload["bawl_hash"] = hashed
                payload["n_sites"] = n_sites
                payload["formula"] = formula
                new_out.write(json.dumps(payload, ensure_ascii=False) + "\n")
                counters["new_structures"] += 1
    matched_path.with_suffix(".part").replace(matched_path)
    alias_path.with_suffix(".part").replace(alias_path)
    new_path.with_suffix(".part").replace(new_path)
    return dict(counters)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument(
        "--stage", choices=("adapt", "hash", "match", "all"), default="all"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--nproc", type=int, default=default_nproc())
    args = parser.parse_args()

    work = WORK_ROOT / args.source
    report_path = work / "report.json"
    report: dict = {}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))

    stages = ("adapt", "hash", "match") if args.stage == "all" else (args.stage,)
    for stage in stages:
        print(f"=== {args.source}: {stage} ===", flush=True)
        result = {
            "adapt": lambda: stage_adapt(args.source, args.limit),
            "hash": lambda: stage_hash(args.source, args.nproc),
            "match": lambda: stage_match(args.source),
        }[stage]()
        report[stage] = result
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

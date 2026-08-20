#!/usr/bin/env python3
"""Stream-extract OQMD v1.8 from its 21GB MySQL dump into extracted.sqlite.

The dump (``data/raw/acquired/oqmd/qmdb__v1_8__022026.sql.gz``) decompresses
to a ~120GB stream whose tables appear alphabetically.  Two passes:

* pass 1  ``calculations`` (10.35-13.8GB), then ``entries`` (108.8GB, after
  a 93GB ``dos`` section that is skipped by line-prefix), then
  ``formation_energies`` (109.1GB, fit 'standard': canonical delta_e and
  hull stability; the entries-table copies are mostly NULL).  Chooses the
  best converged calculation per entry (label 'static' > 'standard' >
  other) and writes one row per non-duplicate entry (duplicate_of_id is
  self-referencing for canonical entries).
* pass 2  ``atoms`` (0-10.35GB) filtered to the chosen output structure ids,
  then ``structures`` (117.1-119.0GB) for lattice/volume/spacegroup, then
  aggregates per-entry ``sites`` JSON.

Column orders are parsed from the CREATE TABLE statements at runtime, never
guessed.  INSERT tuples are parsed with a fast split path guarded by field
counts, falling back to a quote-aware regex tokenizer that understands
backslash escapes (\\') and NULL.  All parsing stays on bytes (latin1 dump).

Validation run (head of the stream only):
    python scripts/properties/adapters/oqmd_extract.py --pass 1 --max-bytes 3e9

Full extraction (report says which passes are pending):
    python scripts/properties/adapters/oqmd_extract.py --pass 1
    python scripts/properties/adapters/oqmd_extract.py --pass 2
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DUMP = PROJECT_ROOT / "data" / "raw" / "acquired" / "oqmd" / "qmdb__v1_8__022026.sql.gz"
DEFAULT_OUT = PROJECT_ROOT / "data" / "props_work" / "oqmd" / "extracted.sqlite"

# one full quoted-string-aware tuple: (...) with '...' islands that may hold
# parens/commas and backslash escapes
TUPLE_RE = re.compile(rb"\((?:[^()']|'(?:[^'\\]|\\.)*')*\)")
# one field inside a tuple: quoted string first, else anything up to a comma
FIELD_RE = re.compile(rb"'(?:[^'\\]|\\.)*'|[^,]+")
UNESC_RE = re.compile(rb"\\(.)")
_ESCAPES = {
    ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t",
    ord("0"): b"\0", ord("Z"): b"\x1a", ord("b"): b"\x08",
}


def _unescape(raw: bytes) -> bytes:
    return UNESC_RE.sub(lambda m: _ESCAPES.get(m.group(1)[0], m.group(1)), raw)


def f_text(raw: bytes) -> str | None:
    if raw == b"NULL":
        return None
    if raw[:1] == b"'":
        raw = raw[1:-1]
    if b"\\" in raw:
        raw = _unescape(raw)
    return raw.decode("latin-1")


def f_float(raw: bytes) -> float | None:
    return None if raw == b"NULL" else float(raw)


def f_int(raw: bytes) -> int | None:
    return None if raw == b"NULL" else int(raw)


def open_stream(path: Path):
    """Return (proc_or_None, binary_handle) decompressing ``path``."""

    for tool in (["unpigz", "-c"], ["pigz", "-dc"], ["gzip", "-dc"], ["zcat"]):
        if shutil.which(tool[0]):
            proc = subprocess.Popen(
                tool + [str(path)], stdout=subprocess.PIPE, bufsize=8 * 1024 * 1024
            )
            return proc, proc.stdout
    import gzip

    return None, gzip.open(path, "rb")


def parse_tuples_careful(line: bytes, ncols: int, start: int) -> list[list[bytes]]:
    rows = []
    for match in TUPLE_RE.finditer(line, start):
        fields = FIELD_RE.findall(match.group(0)[1:-1])
        if len(fields) != ncols:
            raise ValueError(
                f"tuple with {len(fields)} fields, expected {ncols}: "
                f"{match.group(0)[:200]!r}"
            )
        rows.append(fields)
    return rows


class DumpStreamer:
    """One pass over the dump; dispatches parsed INSERT rows to handlers."""

    def __init__(self, dump: Path, max_bytes: float | None = None) -> None:
        self.dump = dump
        self.max_bytes = max_bytes
        self.schemas: dict[str, list[str]] = {}
        self.bytes_read = 0
        self.truncated = False

    def run(self, handlers: dict[str, tuple[bool, object]], stop_after: str) -> None:
        """handlers: table -> (always_careful, fn(rows: list[list[bytes]])).

        ``stop_after``: stop once a CREATE TABLE for a table sorting after
        this name appears (dump tables are alphabetical).
        """

        proc, handle = open_stream(self.dump)
        in_create: str | None = None
        started = time.time()
        next_report = 5 * 10**9
        try:
            for line in handle:
                self.bytes_read += len(line)
                if line.startswith(b"INSERT INTO `"):
                    table = line[13 : line.index(b"`", 13)].decode("ascii")
                    entry = handlers.get(table)
                    if entry is not None:
                        careful, fn = entry
                        fn(self._parse_insert(line, table, careful))
                elif line.startswith(b"CREATE TABLE `"):
                    name = line[14 : line.index(b"`", 14)].decode("ascii")
                    if name > stop_after:
                        break
                    in_create = name
                    self.schemas[name] = []
                elif in_create is not None:
                    if line.startswith(b"  `"):
                        self.schemas[in_create].append(
                            line[3 : line.index(b"`", 3)].decode("ascii")
                        )
                    elif line.startswith(b")"):
                        in_create = None
                if self.bytes_read >= next_report:
                    print(
                        f"  ... {self.bytes_read/1e9:.1f}GB streamed "
                        f"({time.time()-started:.0f}s)",
                        flush=True,
                    )
                    next_report += 5 * 10**9
                if self.max_bytes is not None and self.bytes_read >= self.max_bytes:
                    self.truncated = True
                    print(
                        f"  max-bytes reached at {self.bytes_read/1e9:.2f}GB, stopping",
                        flush=True,
                    )
                    break
        finally:
            handle.close()
            if proc is not None:
                proc.terminate()
                proc.wait()

    def columns(self, table: str) -> list[str]:
        if table not in self.schemas:
            raise SystemExit(f"CREATE TABLE for {table!r} never seen in stream")
        return self.schemas[table]

    def _parse_insert(self, line: bytes, table: str, careful: bool) -> list[list[bytes]]:
        ncols = len(self.columns(table))
        start = line.index(b" VALUES (") + 8
        # fast path: split on the inter-tuple separator, validate field counts
        if not careful and b"\\" not in line:
            stripped = line.rstrip()
            if stripped.endswith(b";"):
                stripped = stripped[:-1]
            body = stripped[start + 1 : -1]
            rows = []
            ok = True
            for chunk in body.split(b"),("):
                fields = chunk.split(b",")
                if len(fields) != ncols:
                    ok = False
                    break
                rows.append(fields)
            if ok:
                return rows
        return parse_tuples_careful(line, ncols, start)


class FilteredFastTable:
    """Fast pre-filtered scan for huge numeric tables (atoms, structures).

    Splits each INSERT body on '),(' and checks a key field against a wanted
    set before fully splitting the chunk.  Rows whose chunk fails the field
    count (embedded separators inside strings) trigger a careful re-parse of
    the whole line; real tuple boundaries always survive the fast split, so
    wanted rows are never silently lost.
    """

    def __init__(self, key_index: int, wanted: set[bytes], on_row) -> None:
        if key_index > 1:
            raise ValueError("fast filter supports key at field 0 or 1 only")
        self.key_index = key_index
        self.wanted = wanted
        self.on_row = on_row

    def handle_line(self, line: bytes, ncols: int, start: int) -> None:
        stripped = line.rstrip()
        if stripped.endswith(b";"):
            stripped = stripped[:-1]
        body = stripped[start + 1 : -1]
        key_index = self.key_index
        wanted = self.wanted
        pending: list[list[bytes]] = []
        for chunk in body.split(b"),("):
            head = chunk.split(b",", key_index + 1)
            if len(head) <= key_index or head[key_index] not in wanted:
                continue
            fields = chunk.split(b",")
            if len(fields) != ncols:
                # embedded '),(' or ',' inside a string: redo the whole line
                pending = [
                    row for row in parse_tuples_careful(line, ncols, start)
                    if row[key_index] in wanted
                ]
                break
            pending.append(fields)
        for row in pending:
            self.on_row(row)


def connect(out: Path) -> sqlite3.Connection:
    out.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    return db


def set_meta(db: sqlite3.Connection, key: str, value) -> None:
    db.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (key, json.dumps(value, sort_keys=True)),
    )
    db.commit()


ICSD_RE = re.compile(r"(?i)^icsd-\d+$")


def run_pass1(dump: Path, out: Path, max_bytes: float | None) -> None:
    db = connect(out)
    db.execute("DROP TABLE IF EXISTS entry")
    db.execute(
        """CREATE TABLE entry (
            entry_id INTEGER PRIMARY KEY,
            label TEXT, icsd TEXT, composition TEXT, natoms INTEGER,
            delta_e REAL, stability REAL,
            fe_delta_e REAL, fe_stability REAL,
            calc_id INTEGER, calc_label TEXT, output_id INTEGER,
            band_gap REAL, energy_pa REAL, magmom_pa REAL,
            lattice TEXT, volume REAL, spacegroup INTEGER,
            struct_natoms INTEGER, sites TEXT
        )"""
    )
    db.commit()

    streamer = DumpStreamer(dump, max_bytes)
    counters = {"calculations": 0, "converged_kept": 0, "entries": 0,
                "entries_kept": 0, "duplicates_skipped": 0,
                "formation_energies": 0, "fe_standard": 0, "fe_collisions": 0}
    # entry_id(bytes) -> (rank, calc_id, label, output_id, band_gap,
    #                     energy_pa, magmom_pa)
    best: dict[bytes, tuple] = {}
    calc_idx: dict[str, int] = {}
    entry_idx: dict[str, int] = {}

    def handle_calculations(rows: list[list[bytes]]) -> None:
        if not calc_idx:
            cols = streamer.columns("calculations")
            for name in ("id", "label", "entry_id", "output_id", "energy_pa",
                         "magmom_pa", "band_gap", "converged"):
                calc_idx[name] = cols.index(name)
        i_id, i_label, i_entry = calc_idx["id"], calc_idx["label"], calc_idx["entry_id"]
        i_out, i_epa = calc_idx["output_id"], calc_idx["energy_pa"]
        i_mpa, i_gap = calc_idx["magmom_pa"], calc_idx["band_gap"]
        i_conv = calc_idx["converged"]
        counters["calculations"] += len(rows)
        for f in rows:
            if f[i_conv] != b"1" or f[i_entry] == b"NULL":
                continue
            counters["converged_kept"] += 1
            label = f_text(f[i_label]) or ""
            tier = 0 if label == "static" else 1 if label == "standard" else 2
            calc_id = int(f[i_id])
            has_out = f[i_out] != b"NULL"
            rank = (tier, 0 if has_out else 1, -calc_id)
            prev = best.get(f[i_entry])
            if prev is None or rank < prev[0]:
                best[f[i_entry]] = (
                    rank, calc_id, label, f_int(f[i_out]), f_float(f[i_gap]),
                    f_float(f[i_epa]), f_float(f[i_mpa]),
                )

    batch: list[tuple] = []

    def flush_entries() -> None:
        if batch:
            db.executemany(
                "INSERT OR REPLACE INTO entry (entry_id, label, icsd, composition,"
                " natoms, delta_e, stability, calc_id, calc_label, output_id,"
                " band_gap, energy_pa, magmom_pa)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                batch,
            )
            batch.clear()

    def handle_entries(rows: list[list[bytes]]) -> None:
        if not entry_idx:
            cols = streamer.columns("entries")
            for name in ("id", "label", "duplicate_of_id", "delta_e",
                         "stability", "composition_id", "natoms"):
                entry_idx[name] = cols.index(name)
        i_id, i_label = entry_idx["id"], entry_idx["label"]
        i_dup, i_de = entry_idx["duplicate_of_id"], entry_idx["delta_e"]
        i_st, i_comp = entry_idx["stability"], entry_idx["composition_id"]
        i_nat = entry_idx["natoms"]
        counters["entries"] += len(rows)
        for f in rows:
            # duplicate_of_id is self-referencing for canonical entries;
            # only skip rows pointing at a *different* entry
            if f[i_dup] != b"NULL" and f[i_dup] != f[i_id]:
                counters["duplicates_skipped"] += 1
                continue
            label = f_text(f[i_label])
            icsd = label if label and ICSD_RE.match(label) else None
            calc = best.get(f[i_id])
            batch.append((
                int(f[i_id]), label, icsd, f_text(f[i_comp]), f_int(f[i_nat]),
                f_float(f[i_de]), f_float(f[i_st]),
                calc[1] if calc else None, calc[2] if calc else None,
                calc[3] if calc else None, calc[4] if calc else None,
                calc[5] if calc else None, calc[6] if calc else None,
            ))
            counters["entries_kept"] += 1
        if len(batch) >= 20_000:
            flush_entries()

    # formation_energies (fit 'standard') carries the canonical delta_e and
    # the hull distance; entries.stability is entirely NULL in this dump and
    # entries.delta_e only sparsely filled
    fe_idx: dict[str, int] = {}
    fe_best: dict[bytes, tuple[float | None, float | None]] = {}

    def handle_formation_energies(rows: list[list[bytes]]) -> None:
        if not fe_idx:
            cols = streamer.columns("formation_energies")
            for name in ("entry_id", "fit_id", "stability", "delta_e"):
                fe_idx[name] = cols.index(name)
        i_entry, i_fit = fe_idx["entry_id"], fe_idx["fit_id"]
        i_st, i_de = fe_idx["stability"], fe_idx["delta_e"]
        counters["formation_energies"] += len(rows)
        for f in rows:
            if f[i_fit] != b"'standard'" or f[i_entry] == b"NULL":
                continue
            counters["fe_standard"] += 1
            if f[i_entry] in fe_best:
                counters["fe_collisions"] += 1
            fe_best[f[i_entry]] = (f_float(f[i_de]), f_float(f[i_st]))

    streamer.run(
        {
            "calculations": (True, handle_calculations),  # settings text: careful
            "entries": (False, handle_entries),
            "formation_energies": (False, handle_formation_energies),
        },
        stop_after="formation_energies",
    )
    flush_entries()
    db.executemany(
        "UPDATE entry SET fe_delta_e=?, fe_stability=? WHERE entry_id=?",
        ((de, st, int(eid)) for eid, (de, st) in fe_best.items()),
    )
    counters["entries_with_calc"] = db.execute(
        "SELECT COUNT(*) FROM entry WHERE calc_id IS NOT NULL"
    ).fetchone()[0]
    counters["entries_with_fe"] = db.execute(
        "SELECT COUNT(*) FROM entry WHERE fe_delta_e IS NOT NULL"
    ).fetchone()[0]
    counters["entries_with_hull"] = db.execute(
        "SELECT COUNT(*) FROM entry WHERE fe_stability IS NOT NULL"
    ).fetchone()[0]
    counters["entries_with_output"] = db.execute(
        "SELECT COUNT(*) FROM entry WHERE output_id IS NOT NULL"
    ).fetchone()[0]
    counters["icsd_labelled"] = db.execute(
        "SELECT COUNT(*) FROM entry WHERE icsd IS NOT NULL"
    ).fetchone()[0]
    counters["bytes_read"] = streamer.bytes_read
    counters["truncated"] = streamer.truncated
    db.execute("CREATE INDEX IF NOT EXISTS idx_entry_output ON entry(output_id)")
    set_meta(db, "pass1", counters)
    set_meta(db, "schema_pass1", streamer.schemas)
    db.commit()
    db.close()
    print("pass 1 done:", json.dumps(counters, indent=2, sort_keys=True))


def run_pass2(dump: Path, out: Path, max_bytes: float | None,
              limit_entries: int | None, keep_sites: bool) -> None:
    db = connect(out)
    try:
        n_entries = db.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    except sqlite3.OperationalError:
        raise SystemExit("run pass 1 first (entry table missing)")
    if n_entries == 0:
        raise SystemExit("entry table is empty; pass 1 saw no entries rows")

    sql = "SELECT output_id, entry_id FROM entry WHERE output_id IS NOT NULL ORDER BY entry_id"
    if limit_entries is not None:
        sql += f" LIMIT {int(limit_entries)}"
    wanted: dict[bytes, int] = {
        str(sid).encode(): eid for sid, eid in db.execute(sql)
    }
    print(f"pass 2: filtering for {len(wanted):,} output structures "
          f"(of {n_entries:,} entries)")
    wanted_set = set(wanted)

    db.execute("DROP TABLE IF EXISTS site")
    db.execute(
        "CREATE TABLE site (structure_id INTEGER, atom_id INTEGER, element TEXT,"
        " x REAL, y REAL, z REAL, magmom REAL, occupancy REAL)"
    )
    db.execute("UPDATE entry SET lattice=NULL, volume=NULL, spacegroup=NULL,"
               " struct_natoms=NULL, sites=NULL WHERE output_id IS NOT NULL"
               + ("" if limit_entries is None else
                  f" AND entry_id IN (SELECT entry_id FROM entry WHERE output_id"
                  f" IS NOT NULL ORDER BY entry_id LIMIT {int(limit_entries)})"))
    db.commit()

    streamer = DumpStreamer(dump, max_bytes)
    counters = {"atom_rows": 0, "site_rows": 0, "structures": 0,
                "structures_matched": 0}
    site_batch: list[tuple] = []
    struct_batch: list[tuple] = []
    atoms_idx: dict[str, int] = {}
    struct_idx: dict[str, int] = {}

    def flush_sites() -> None:
        if site_batch:
            db.executemany("INSERT INTO site VALUES (?,?,?,?,?,?,?,?)", site_batch)
            site_batch.clear()

    def flush_structs() -> None:
        if struct_batch:
            db.executemany(
                "UPDATE entry SET lattice=?, volume=?, spacegroup=?,"
                " struct_natoms=? WHERE entry_id=?",
                struct_batch,
            )
            struct_batch.clear()

    def on_atom(f: list[bytes]) -> None:
        i = atoms_idx
        site_batch.append((
            int(f[i["structure_id"]]), int(f[i["id"]]), f_text(f[i["element_id"]]),
            f_float(f[i["x"]]), f_float(f[i["y"]]), f_float(f[i["z"]]),
            f_float(f[i["magmom"]]), f_float(f[i["occupancy"]]),
        ))
        counters["site_rows"] += 1
        if len(site_batch) >= 50_000:
            flush_sites()

    def on_structure(f: list[bytes]) -> None:
        i = struct_idx
        # qmpy cell rows are (x1,x2,x3), (y1,y2,y3), (z1,z2,z3): verified on
        # hexagonal spacegroups (gamma=120.0 this way, 116.6 transposed)
        lattice = [
            [f_float(f[i["x1"]]), f_float(f[i["x2"]]), f_float(f[i["x3"]])],
            [f_float(f[i["y1"]]), f_float(f[i["y2"]]), f_float(f[i["y3"]])],
            [f_float(f[i["z1"]]), f_float(f[i["z2"]]), f_float(f[i["z3"]])],
        ]
        counters["structures_matched"] += 1
        struct_batch.append((
            json.dumps(lattice), f_float(f[i["volume"]]),
            f_int(f[i["spacegroup_id"]]), f_int(f[i["natoms"]]),
            wanted[f[i["id"]]],
        ))
        if len(struct_batch) >= 20_000:
            flush_structs()

    atoms_filter = FilteredFastTable(1, wanted_set, on_atom)
    struct_filter = FilteredFastTable(0, wanted_set, on_structure)

    def handle_atoms_line(line: bytes) -> None:
        if not atoms_idx:
            cols = streamer.columns("atoms")
            for name in ("id", "structure_id", "element_id", "x", "y", "z",
                         "magmom", "occupancy"):
                atoms_idx[name] = cols.index(name)
            if atoms_idx["structure_id"] != 1:
                raise SystemExit("atoms.structure_id is not field 1; adjust filter")
        counters["atom_rows"] += line.count(b"),(") + 1
        atoms_filter.handle_line(line, len(streamer.columns("atoms")),
                                 line.index(b" VALUES (") + 8)

    def handle_structures_line(line: bytes) -> None:
        if not struct_idx:
            cols = streamer.columns("structures")
            for name in ("id", "natoms", "x1", "y1", "z1", "x2", "y2", "z2",
                         "x3", "y3", "z3", "spacegroup_id", "volume"):
                struct_idx[name] = cols.index(name)
            if struct_idx["id"] != 0:
                raise SystemExit("structures.id is not field 0; adjust filter")
        counters["structures"] += line.count(b"),(") + 1
        struct_filter.handle_line(line, len(streamer.columns("structures")),
                                  line.index(b" VALUES (") + 8)

    # raw-line handlers: bypass DumpStreamer's generic tuple parser so the
    # pre-filter can reject rows before a full field split
    orig_parse = streamer._parse_insert

    def parse_or_dispatch(line: bytes, table: str, careful: bool):
        if table == "atoms":
            handle_atoms_line(line)
            return []
        if table == "structures":
            handle_structures_line(line)
            return []
        return orig_parse(line, table, careful)

    streamer._parse_insert = parse_or_dispatch  # type: ignore[method-assign]
    streamer.run(
        {"atoms": (False, lambda rows: None),
         "structures": (False, lambda rows: None)},
        stop_after="structures",
    )
    flush_sites()
    flush_structs()
    db.commit()

    # aggregate sites JSON per entry
    db.execute("CREATE INDEX IF NOT EXISTS idx_site_sid ON site(structure_id)")
    natoms_by_sid = {
        int(sid): (eid, nat)
        for sid, eid, nat in db.execute(
            "SELECT output_id, entry_id, struct_natoms FROM entry"
            " WHERE output_id IS NOT NULL AND lattice IS NOT NULL"
        )
    }
    counters["sites_count_mismatch"] = 0
    counters["entries_with_sites"] = 0
    updates: list[tuple] = []
    current_sid: int | None = None
    current: list[list] = []

    def finish_group() -> None:
        if current_sid is None or current_sid not in natoms_by_sid:
            return
        eid, natoms = natoms_by_sid[current_sid]
        if natoms is not None and len(current) != natoms:
            counters["sites_count_mismatch"] += 1
            return
        updates.append((json.dumps(current), eid))
        counters["entries_with_sites"] += 1

    for sid, element, x, y, z, occ, mag in db.execute(
        "SELECT structure_id, element, x, y, z, occupancy, magmom FROM site"
        " ORDER BY structure_id, atom_id"
    ):
        if sid != current_sid:
            finish_group()
            current_sid, current = sid, []
        current.append([element, x, y, z, occ, mag])
    finish_group()
    db.executemany("UPDATE entry SET sites=? WHERE entry_id=?", updates)
    counters["bytes_read"] = streamer.bytes_read
    counters["truncated"] = streamer.truncated
    counters["limit_entries"] = limit_entries
    if not keep_sites:
        db.execute("DROP TABLE site")
    set_meta(db, "pass2", counters)
    db.commit()
    if not keep_sites:
        db.execute("VACUUM")
    db.close()
    print("pass 2 done:", json.dumps(counters, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, default=DEFAULT_DUMP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--pass", dest="passes", choices=("1", "2", "all"),
                        default="all")
    parser.add_argument("--max-bytes", type=float, default=None,
                        help="stop each pass after this many uncompressed bytes"
                             " (validation runs)")
    parser.add_argument("--limit-entries", type=int, default=None,
                        help="pass 2: only fetch structures for the first N"
                             " entries (validation runs)")
    parser.add_argument("--keep-sites", action="store_true",
                        help="keep the raw per-atom site table in the sqlite")
    args = parser.parse_args()

    if not args.dump.exists():
        raise SystemExit(f"dump not found: {args.dump}")
    started = time.time()
    if args.passes in ("1", "all"):
        print(f"=== pass 1: calculations + entries ({args.dump}) ===", flush=True)
        run_pass1(args.dump, args.out, args.max_bytes)
    if args.passes in ("2", "all"):
        print(f"=== pass 2: atoms + structures ({args.dump}) ===", flush=True)
        run_pass2(args.dump, args.out, args.max_bytes, args.limit_entries,
                  args.keep_sites)
    print(f"total {time.time()-started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

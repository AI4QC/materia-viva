"""RRUFF measured spectra -> xy curves (powder XRD, Raman, infrared).

Powder XRD reads the archives under data/raw/acquired/rruff/powder/
(XY_Processed.zip preferred, XY_RAW.zip as fallback for R-ids with no
processed file). Each zip member is a per-sample .txt with ``##KEY=value``
headers followed by ``x, y`` float pairs (2-theta / intensity).
One XRD curve per matched RRUFF R-id (first Processed file wins).

Raman reads the eight archives under data/raw/acquired/rruff/raman/
(quality tiers excellent/fair/poor/unrated x oriented/unoriented, plus
low-resolution LR-Raman broad scans). Same ``##KEY=value`` text format.
Member names always split into 8 ``__`` tokens:
``Mineral__R######[-n]__Raman__<wavelength>__<angle>__<orient>__<tag>__hash``
(LR-Raman uses ``Broad_Scan`` for token 2); token 3 is the laser wavelength
in nm with ``-`` standing in for a decimal point (e.g. ``514-5`` = 514.5).
Per matched R-id at most one Raman curve is emitted per laser wavelength,
choosing full-resolution over LR-Raman, then the better quality tier
(excellent > fair > poor > unrated), then Processed over RAW.

Infrared reads data/raw/acquired/rruff/infrared/RAW.zip and emits at most
one IR curve per matched R-id (first member in name order).

A native id may map to several material_ids, so one CurveRecord is yielded
per match. ``limit`` counts every yielded record across all three kinds.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

try:
    from scripts.properties.curves import PROJECT_ROOT, CurveRecord
except ImportError:  # pragma: no cover - standalone / dry-run fallback
    from dataclasses import dataclass

    PROJECT_ROOT = Path(__file__).resolve().parents[3]

    @dataclass
    class CurveRecord:  # mirrors scripts.properties.curves.CurveRecord
        material_id: str
        curve_type: str
        fmt: str
        payload: str | bytes
        native_id: str | None = None
        method: str | None = None
        label: str | None = None

RRUFF_DIR = PROJECT_ROOT / "data" / "raw" / "acquired" / "rruff"
POWDER_DIR = RRUFF_DIR / "powder"
PROCESSED_ZIP = POWDER_DIR / "XY_Processed.zip"
RAW_ZIP = POWDER_DIR / "XY_RAW.zip"
RAMAN_DIR = RRUFF_DIR / "raman"
IR_ZIP = RRUFF_DIR / "infrared" / "RAW.zip"

MAX_POINTS = 2000
MAX_PAYLOAD = 1_500_000  # bytes, uncompressed
RID_RE = re.compile(r"\b(R\d{6})\b")
LAX_RID_RE = re.compile(r"R\d{6}")  # also hits R050441_a / R040063-1 tokens

#: (zip file name, tier tag) in preference order; LR-Raman always loses to
#: any full-resolution spectrum at the same wavelength.
RAMAN_ZIPS = (
    ("excellent_oriented.zip", "excellent"),
    ("excellent_unoriented.zip", "excellent"),
    ("fair_oriented.zip", "fair"),
    ("fair_unoriented.zip", "fair"),
    ("poor_unoriented.zip", "poor"),
    ("unrated_oriented.zip", "unrated"),
    ("unrated_unoriented.zip", "unrated"),
    ("LR-Raman.zip", "LR"),
)
TIER_RANK = {"excellent": 0, "fair": 1, "poor": 2, "unrated": 3, "LR": 4}


def _rid_from_member(name: str, header: dict[str, str]) -> str | None:
    """RRUFF id via ##RRUFFID=, else the filename token (R123456[-n])."""

    rid = header.get("RRUFFID", "").strip()
    match = RID_RE.search(rid) or RID_RE.search(Path(name).name)
    return match.group(1) if match else None


def _parse_member(handle: io.TextIOBase):
    """Return (header dict, x list, y list) from one sample .txt."""

    header: dict[str, str] = {}
    xs: list[float] = []
    ys: list[float] = []
    for line in handle:
        line = line.strip()
        if not line:
            continue
        if line.startswith("##"):
            key, _, value = line[2:].partition("=")
            header[key.strip().upper()] = value.strip()
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        xs.append(x)
        ys.append(y)
    return header, xs, ys


def _downsample(xs: list[float], ys: list[float]):
    if len(xs) > MAX_POINTS:
        stride = -(-len(xs) // MAX_POINTS)  # ceil div -> uniform stride
        xs = xs[::stride]
        ys = ys[::stride]
    return xs, ys


def _method(header: dict[str, str]) -> str:
    """'measured' plus wavelength/instrument info when compactly available."""

    for key in ("WAVELENGTH", "RADIATION", "INSTRUMENT"):
        value = header.get(key, "").strip()
        if value and len(value) <= 24:
            return f"measured, {value}"
    return "measured"


def _iter_zip(zip_path: Path):
    """Yield (member_name, header, xs, ys) streaming one member at a time."""

    if not zip_path.exists():
        return
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(archive.namelist()):
            if not name.lower().endswith(".txt"):
                continue
            with archive.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                header, xs, ys = _parse_member(text)
            yield name, header, xs, ys


def _iter_xrd(matched: dict[str, list[str]]):
    done: set[str] = set()
    for zip_path in (PROCESSED_ZIP, RAW_ZIP):
        for name, header, xs, ys in _iter_zip(zip_path):
            rid = _rid_from_member(name, header)
            if rid is None or rid in done or rid not in matched:
                continue
            if not xs:
                continue
            if any(a > b for a, b in zip(xs, xs[1:])):  # enforce ascending x
                order = sorted(range(len(xs)), key=xs.__getitem__)
                xs = [xs[i] for i in order]
                ys = [ys[i] for i in order]
            xs, ys = _downsample(xs, ys)
            payload = json.dumps(
                {
                    "x": [round(x, 4) for x in xs],
                    "y": [round(y, 4) for y in ys],
                    "x_label": "2θ",
                    "y_label": "Intensity",
                    "x_unit": "deg",
                    "y_unit": "a.u.",
                },
                separators=(",", ":"),
            )
            if len(payload.encode("utf-8")) > MAX_PAYLOAD:
                continue
            done.add(rid)  # first Processed file wins; RAW only fills gaps
            method = _method(header)
            for material_id in matched[rid]:
                yield CurveRecord(
                    material_id=material_id,
                    curve_type="xrd",
                    fmt="xy",
                    payload=payload,
                    native_id=rid,
                    method=method,
                    label="Powder XRD (measured)",
                )


def _spectrum_payload(xs, ys, x_label: str, x_unit: str) -> str | None:
    """Ascending-x, downsampled, size-capped xy JSON (None when unusable)."""

    if not xs:
        return None
    if any(a > b for a, b in zip(xs, xs[1:])):
        order = sorted(range(len(xs)), key=xs.__getitem__)
        xs = [xs[i] for i in order]
        ys = [ys[i] for i in order]
    xs, ys = _downsample(xs, ys)
    payload = json.dumps(
        {
            "x": [round(x, 4) for x in xs],
            "y": [round(y, 4) for y in ys],
            "x_label": x_label,
            "y_label": "Intensity",
            "x_unit": x_unit,
            "y_unit": "a.u.",
        },
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) > MAX_PAYLOAD:
        return None
    return payload


def _wavelength_token(name: str) -> str | None:
    """Laser wavelength (nm) from member-name token 3; ``-`` = decimal dot."""

    tokens = Path(name).name.split("__")
    if len(tokens) < 7:
        return None
    wavelength = tokens[3].replace("-", ".")
    if re.fullmatch(r"\d{3,4}(\.\d+)?", wavelength):
        return wavelength.rstrip("0").rstrip(".") if "." in wavelength else wavelength
    return None


def _select_raman_members(matched: dict[str, list[str]]):
    """Best member per (R-id, wavelength): {zip name: [(member, tier, wl)]}.

    Rank order: full-resolution beats LR-Raman, then quality tier, then
    Processed beats RAW; member name breaks remaining ties (oriented angle 0
    first).
    """

    best: dict[tuple[str, str], tuple] = {}
    for zip_name, tier in RAMAN_ZIPS:
        zip_path = RAMAN_DIR / zip_name
        if not zip_path.exists():
            continue
        with zipfile.ZipFile(zip_path) as archive:
            for name in archive.namelist():
                if not name.lower().endswith(".txt"):
                    continue
                tokens = Path(name).name.split("__")
                if len(tokens) < 7:
                    continue
                rid_match = LAX_RID_RE.search(tokens[1])
                if not rid_match:
                    continue
                rid = rid_match.group(0)
                if rid not in matched:
                    continue
                wavelength = _wavelength_token(name) or tokens[3]
                is_raw = "processed" not in tokens[6].lower()
                rank = (tier == "LR", TIER_RANK[tier], is_raw, name)
                key = (rid, wavelength)
                if key not in best or rank < best[key][0]:
                    best[key] = (rank, zip_name, name, tier, wavelength)

    by_zip: dict[str, list[tuple[str, str, str, str]]] = {}
    for (rid, _wl), (_rank, zip_name, name, tier, wavelength) in best.items():
        by_zip.setdefault(zip_name, []).append((name, rid, tier, wavelength))
    for members in by_zip.values():
        members.sort()
    return by_zip


def _iter_raman(matched: dict[str, list[str]]):
    by_zip = _select_raman_members(matched)
    emitted: set[tuple[str, str]] = set()
    for zip_name, _tier in RAMAN_ZIPS:  # deterministic tier-major order
        members = by_zip.get(zip_name)
        if not members:
            continue
        with zipfile.ZipFile(RAMAN_DIR / zip_name) as archive:
            for name, rid, tier, wavelength in members:
                with archive.open(name) as raw:
                    text = io.TextIOWrapper(
                        raw, encoding="utf-8", errors="replace"
                    )
                    header, xs, ys = _parse_member(text)
                payload = _spectrum_payload(xs, ys, "Raman shift", "cm⁻¹")
                if payload is None:
                    continue
                # A missing filename token can hide the wavelength the header
                # knows (e.g. ##RAMAN WAVELENGTH=532), so re-dedupe on the
                # resolved value; "unknown" headers stay blank.
                from_header = header.get("RAMAN WAVELENGTH", "").strip()
                if not wavelength and re.fullmatch(
                    r"\d{3,4}(\.\d+)?", from_header
                ):
                    wavelength = from_header
                if (rid, wavelength) in emitted:
                    continue
                emitted.add((rid, wavelength))
                method = (
                    f"Raman {wavelength} nm ({tier})"
                    if wavelength
                    else f"Raman ({tier})"
                )
                for material_id in matched[rid]:
                    yield CurveRecord(
                        material_id=material_id,
                        curve_type="raman",
                        fmt="xy",
                        payload=payload,
                        native_id=rid,
                        method=method,
                        label="Raman spectrum",
                    )


def _iter_ir(matched: dict[str, list[str]]):
    done: set[str] = set()
    for name, header, xs, ys in _iter_zip(IR_ZIP):
        tokens = Path(name).name.split("__")
        rid_source = tokens[1] if len(tokens) > 1 else Path(name).name
        rid_match = LAX_RID_RE.search(rid_source)
        rid = rid_match.group(0) if rid_match else _rid_from_member(name, header)
        if rid is None or rid in done or rid not in matched:
            continue
        payload = _spectrum_payload(xs, ys, "Wavenumber", "cm⁻¹")
        if payload is None:
            continue
        done.add(rid)  # at most one IR curve per R-id (first in name order)
        for material_id in matched[rid]:
            yield CurveRecord(
                material_id=material_id,
                curve_type="ir",
                fmt="xy",
                payload=payload,
                native_id=rid,
                method="IR (RAW)",
                label="Infrared spectrum",
            )


def iter_curves(resolver, limit=None):
    matched: dict[str, list[str]] = {}
    for native_id, material_id in resolver.matched_pairs("rruff"):
        rid_match = RID_RE.search(native_id)
        rid = rid_match.group(1) if rid_match else native_id
        matched.setdefault(rid, []).append(material_id)

    yielded = 0
    for records in (_iter_xrd(matched), _iter_raman(matched), _iter_ir(matched)):
        for record in records:
            yield record
            yielded += 1
            if limit is not None and yielded >= limit:
                return

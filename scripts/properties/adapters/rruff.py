"""RRUFF: XRD-derived mineral structures from the DIF archive.

One record per RRUFF sample id (R######), streamed out of powder/DIF.zip
(~3,000 small text files). Each DIF file carries refined cell parameters, a
space group symbol and the asymmetric unit ("ATOM X Y Z OCCUPANCY ISO(B)"),
from which the full cell is generated via Structure.from_spacegroup. Files
without an atom table (peak-list-only DIFs) or with a space group symbol
pymatgen cannot interpret yield property-only records. Sites with partial or
mixed occupancy are kept as disordered species dicts; the hash stage marks
those DISORDERED and drops them, which is expected.

Atom labels are plain element symbols plus a handful of specials seen in the
archive: OH/Oh/Ow/Oa/... (hydroxyl/water/site-suffixed oxygen -> O), Wa
(water oxygen -> O, must not become tungsten) and D (deuterium -> H); anything
else falls back to longest leading element-symbol match.

Properties: mineral_name from the DIF title line, and the sample's measured
microprobe chemistry (looked up by R-id from the ##MEASURED CHEMISTRY header
of powder/XY_Processed.zip) when it is compact. Spectra are skipped entirely.
Everything is experimental; no cross-database ids, so always_hash.
"""

from __future__ import annotations

import re
import warnings
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_RE_RID = re.compile(r"(R\d{6})")
_RE_CELL = re.compile(
    r"CELL PARAMETERS:\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)"
    r"\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)"
)
_RE_SG = re.compile(r"SPACE GROUP:\s*(\S+)")
_RE_ATOM_HEADER = re.compile(r"^\s*ATOM\s+X\s+Y\s+Z\s+OCCUPANCY\s+ISO.*$", re.M)
_RE_ATOM_ROW = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9]*)\s+"
    r"(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?\s*$"
)

#: labels that must not go through leading-element matching
_SPECIAL_LABELS = {"Wa": "O", "D": "H", "T": "H"}

#: Longest measured-chemistry string kept. A microprobe formula for a
#: multi-site mineral runs well past 80 characters
#: ("(K_0.67_Na_1.33_)Fe^2+^_1.00_(Ca_0.80_Na_2.20_)..." is 160), so the old
#: cap dropped ~400 perfectly good formulas; 200 still cuts the handful of
#: free-text analyses that run to several hundred characters.
_CHEMISTRY_MAX = 200


def _element_symbols() -> list[str]:
    from pymatgen.core.periodic_table import Element

    return sorted((element.symbol for element in Element), key=len, reverse=True)


class RruffAdapter(SourceAdapter):
    source_key = "rruff"
    always_hash = True

    def _measured_chemistry(self) -> dict[str, str]:
        """R-id -> ##MEASURED CHEMISTRY line from the XY_Processed headers."""

        chem: dict[str, str] = {}
        archive = self.root / "powder" / "XY_Processed.zip"
        if not archive.exists():
            return chem
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                with bundle.open(name) as handle:
                    head = handle.read(4096).decode("utf-8", errors="replace")
                rid = None
                for line in head.splitlines():
                    if line.startswith("##RRUFFID="):
                        rid = safe_text(line.split("=", 1)[1])
                    elif line.startswith("##MEASURED CHEMISTRY=") and rid:
                        value = safe_text(line.split("=", 1)[1])
                        if value:
                            chem.setdefault(rid, value)
        return chem

    def _element_for_label(self, label: str) -> str | None:
        if label in self._element_set:
            return label
        special = _SPECIAL_LABELS.get(label)
        if special:
            return special
        for candidate in (label, label.capitalize()):
            for symbol in self._elements:
                if candidate.startswith(symbol):
                    return symbol
        return None

    def _space_group(self, symbol: str):
        from pymatgen.symmetry.groups import SpaceGroup

        candidates = [symbol]
        if "-" not in symbol and "3" in symbol:
            # RRUFF omits the overline in cubic symbols (Fd3m -> Fd-3m)
            candidates.append(symbol.replace("3", "-3", 1))
        for candidate in candidates:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    return SpaceGroup(candidate)
            except Exception:  # noqa: BLE001 - unknown setting, try next form
                continue
        return None

    def _parse_structure(self, text: str):
        """DIF text -> pymatgen Structure (possibly disordered) or None."""

        from pymatgen.core import Lattice, Structure

        if "ALTERNATE SETTING FOR SPACE GROUP:" in text:
            # coords use a setting pymatgen's symbol tables do not cover;
            # applying standard-setting ops would build a wrong cell (~6%)
            return None
        cell = _RE_CELL.search(text)
        sg_match = _RE_SG.search(text)
        header = _RE_ATOM_HEADER.search(text)
        if not cell or not sg_match or not header:
            return None
        spacegroup = self._space_group(sg_match.group(1))
        if spacegroup is None:
            return None
        # collapse the asymmetric-unit rows into per-coordinate compositions
        sites: dict[tuple[float, float, float], dict[str, float]] = {}
        order: list[tuple[float, float, float]] = []
        for line in text[header.end():].splitlines():
            if not line.strip():
                if sites:
                    break
                continue
            row = _RE_ATOM_ROW.match(line)
            if not row:
                break
            label, x, y, z, occupancy, _iso = row.groups()
            if occupancy is None:
                return None  # occupancy column absent: do not generate
            element = self._element_for_label(label)
            if element is None:
                return None
            key = (round(float(x), 5), round(float(y), 5), round(float(z), 5))
            if key not in sites:
                sites[key] = {}
                order.append(key)
            sites[key][element] = sites[key].get(element, 0.0) + float(occupancy)
        if not sites:
            return None
        species: list = []
        coords: list[list[float]] = []
        for key in order:
            composition = sites[key]
            total = sum(composition.values())
            if total <= 0:
                return None
            if total > 1.0:  # rounding overshoot on shared sites
                composition = {el: occ / total for el, occ in composition.items()}
            if len(composition) == 1 and abs(total - 1.0) <= 1e-3:
                species.append(next(iter(composition)))
            else:
                species.append(composition)
            coords.append(list(key))
        a, b, c, alpha, beta, gamma = (float(v) for v in cell.groups())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                structure = Structure.from_spacegroup(
                    spacegroup.symbol,
                    Lattice.from_parameters(a, b, c, alpha, beta, gamma),
                    species,
                    coords,
                    # DIF coords are 5-decimal, so 1/3 comes as 0.33333 and the
                    # default 1e-5 tol leaves duplicate symmetry-mapped atoms
                    tol=1e-3,
                )
        except Exception:  # noqa: BLE001 - keep the property-only record
            return None
        if structure.is_ordered and len(structure) > 1:
            # refined coords slightly off special positions leave symmetry
            # ghosts (~0.05-0.4 A apart); average them back onto the site
            import numpy as np

            distances = structure.distance_matrix
            np.fill_diagonal(distances, np.inf)
            if distances.min() < 0.5:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        structure = structure.merge_sites(tol=0.5, mode="average")
                except Exception:  # noqa: BLE001 - keep the unmerged cell
                    pass
        return structure

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        self._elements = _element_symbols()
        self._element_set = set(self._elements)
        measured = self._measured_chemistry()
        seen: set[str] = set()
        count = 0
        with zipfile.ZipFile(self.root / "powder" / "DIF.zip") as bundle:
            for name in sorted(bundle.namelist()):
                if limit is not None and count >= limit:
                    return
                rid_match = _RE_RID.search(name)
                if not rid_match:  # X-id standards samples, not RRUFF minerals
                    continue
                rid = rid_match.group(1)
                if rid in seen:  # one structure per R-id, first wins
                    continue
                seen.add(rid)
                text = bundle.read(name).decode("utf-8", errors="replace")
                properties = []
                title = next(
                    (line.strip() for line in text.splitlines() if line.strip()),
                    None,
                )
                mineral = safe_text(title) or safe_text(name.split("__", 1)[0])
                if mineral:
                    properties.append(
                        PropertyValue("mineral_name", mineral, None, "experiment")
                    )
                chemistry = measured.get(rid)
                if chemistry and len(chemistry) < _CHEMISTRY_MAX:
                    properties.append(
                        PropertyValue(
                            "measured_chemistry", chemistry, None, "microprobe"
                        )
                    )
                structure = self._parse_structure(text)
                count += 1
                yield SourceRecord(
                    native_id=rid,
                    properties=properties,
                    structure=structure,
                    experimental=True,
                )

"""ELEMENTA: PBE relaxation-endpoint energetics for the local trajectory pool.

Two work TSVs (endpoints_open.tsv ~2.03M rows, endpoints_spin.tsv ~207k rows),
one row per trajectory endpoint. The pool already contains every ELEMENTA
endpoint structure (loaded via the merge pipeline), so records are
properties-only and match purely on the native id
``{archive}:{material}:{structure}:{spin}`` — verified identical to the
``id_map`` entries in match_map.sqlite (spin is the empty string for the open
archive, leaving a trailing colon).

Energies are per cell in the TSV; ``n_sites`` is present, so the staged value
is ``total_energy_per_atom``. ``magmom`` is per cell and is staged for *both*
archives: the open archive is spin-polarised too (2,028,008 finite values,
peaking at 7.9 μB/atom on Gd), it was withheld only by an archive guard that
had no basis in the data.

``max_force`` (largest force magnitude over the frame, eV/Å) and
``max_abs_stress`` (largest absolute component of the frame's stress tensor,
eV/Å³ — the extxyz ``stress="..."`` convention) are the residuals stage 1
recorded "to decide whether that endpoint is a relaxed structure", so they are
staged as ``max_residual_force`` / ``max_residual_stress``. ``ionic_step`` (the
frame index inside the trajectory) and ``n_sites`` (structure-derived, already
pool-wide) are bookkeeping and are not staged; ``nelm`` exists only in the
extxyz comment lines, not in the endpoint TSVs, and is electronic-convergence
bookkeeping either way.

Method strings: the two pre-existing properties keep ``PBE (ELEMENTA)``
verbatim. The residuals name the archive and the trajectory they belong to
(``PBE (ELEMENTA open: structure_01)``), because several endpoints of one
composition can land on the same pool material and a constant method would
make those rows indistinguishable.
"""

from __future__ import annotations

import csv
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

METHOD = "PBE (ELEMENTA)"

#: canonical name -> physically plausible window; outside is dropped and counted.
#: total_magnetization is guarded against n_sites instead (12 μB/atom, ~1.5x the
#: 7.9 μB/atom Gd maximum actually present in either archive).
_RANGES: dict[str, tuple[float, float]] = {
    # VASP PAW total energies; ELEMENTA spans -0.29 .. -170 eV per cell over
    # 1-44 sites, i.e. roughly -0.15 .. -14 eV/atom
    "total_energy_per_atom": (-100.0, 10.0),
    # relaxation residual, both archives measured 0 .. 1.26 eV/Å
    "max_residual_force": (0.0, 50.0),
    # 1 eV/Å³ = 160.2 GPa; both archives measured 1e-6 .. 0.033 eV/Å³
    "max_residual_stress": (0.0, 10.0),
}

_MAGMOM_PER_SITE_LIMIT = 12.0


class ElementaAdapter(SourceAdapter):
    source_key = "elementa"
    properties_only = True

    def __init__(self, root=None) -> None:
        super().__init__(root)
        self.drops: Counter[str] = Counter()

    def _guard(self, value: float | None, name: str) -> float | None:
        """Drop (and count) values outside the window declared for `name`."""

        window = _RANGES.get(name)
        if value is None or window is None:
            return value
        if not (window[0] <= value <= window[1]):
            self.drops[name] += 1
            return None
        return value

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        try:
            for archive in ("open", "spin"):
                path = self.root / "work" / f"endpoints_{archive}.tsv"
                with path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle, delimiter="\t")
                    for row in reader:
                        if limit is not None and count >= limit:
                            return
                        count += 1
                        material = (row.get("material") or "").strip()
                        structure = (row.get("structure") or "").strip()
                        spin = (row.get("spin") or "").strip()
                        native_id = f"{archive}:{material}:{structure}:{spin}"
                        # names the trajectory this endpoint came out of, so
                        # sibling endpoints on one pool material stay apart
                        trajectory = structure + (f"/{spin}" if spin else "")
                        endpoint_method = f"PBE (ELEMENTA {archive}: {trajectory})"
                        properties = []
                        energy = safe_float(row.get("energy"))
                        n_sites = safe_float(row.get("n_sites"))
                        if energy is not None and n_sites and n_sites > 0:
                            per_atom = self._guard(
                                energy / n_sites, "total_energy_per_atom"
                            )
                            if per_atom is not None:
                                properties.append(
                                    PropertyValue(
                                        "total_energy_per_atom",
                                        per_atom,
                                        "eV/atom",
                                        METHOD,
                                    )
                                )
                        magmom = safe_float(row.get("magmom"))
                        if magmom is not None:
                            limit_ub = _MAGMOM_PER_SITE_LIMIT * (n_sites or 1000.0)
                            if abs(magmom) <= limit_ub:
                                properties.append(
                                    PropertyValue(
                                        "total_magnetization",
                                        magmom,
                                        "μB/cell",
                                        METHOD,
                                    )
                                )
                            else:
                                self.drops["total_magnetization"] += 1
                        for key, name, unit in (
                            ("max_force", "max_residual_force", "eV/Å"),
                            ("max_abs_stress", "max_residual_stress", "eV/Å³"),
                        ):
                            value = self._guard(safe_float(row.get(key)), name)
                            if value is not None:
                                properties.append(
                                    PropertyValue(name, value, unit, endpoint_method)
                                )
                        yield SourceRecord(
                            native_id=native_id,
                            properties=properties,
                            structure=None,
                            match_ids=[("elementa", native_id)],
                        )
        finally:
            print(
                "[elementa] value drops: "
                + (str(dict(self.drops)) if self.drops else "none"),
                flush=True,
            )

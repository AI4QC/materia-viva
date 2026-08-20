"""Carolina Materials Database: ML-generated hypothetical inorganic crystals.

The provider (carolinamatdb.org, Hu group / USC) publishes no bulk route, so
this reads the CC BY 4.0 MatSciML redistribution
(Zenodo 8381476, ``bulk/matsciml-zenodo-8381476/carolina_matdb.zip``), whose
LMDB holds all 214,435 records keyed ``0..214434``.

Two traps in the raw records, both verified before writing this adapter:

* the field named ``cart_coords`` actually holds FRACTIONAL coordinates —
  reconstructing it as cartesian would produce nonsense cells;
* records mix cell settings (some ternaries are stored as conventional cells
  while the website serves primitives), which is irrelevant here because the
  pipeline primitive-reduces before fingerprinting.

``energy`` is the per-atom formation energy (identical to ColabFit's
``formation_energy`` on 5,000 sampled records). Its tail is corrupt — values
run to +667 eV/atom — so the property is dropped outside ±10 eV/atom while the
structure is still admitted.

native_id is ``carolina-<lmdb key>``, matching the refs that
``scripts/properties/carolina_refs.py`` already wrote, so re-matching is
idempotent rather than duplicating. No cross-database ids survive in either
redistribution, so matching is fingerprint-only and the pipeline's standard
pool dedup decides what is genuinely new.
"""

from __future__ import annotations

import pickle
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

LMDB_PATH = (
    "data/raw/acquired/carolina/bulk/matsciml-zenodo-8381476/"
    "carolina_matdb/base/all/data.lmdb"
)

#: formation energies outside this window are source corruption, not physics
MAX_ABS_FORMATION_ENERGY = 10.0


class CarolinaAdapter(SourceAdapter):
    source_key = "carolina"
    always_hash = False
    properties_only = False

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        import lmdb
        from pymatgen.core import Lattice, Structure

        env = lmdb.open(LMDB_PATH, readonly=True, lock=False, subdir=False)
        count = 0
        with env.begin() as txn:
            for key, payload in txn.cursor():
                if limit is not None and count >= limit:
                    return
                try:
                    record = pickle.loads(payload)
                except Exception:  # noqa: BLE001 - skip unreadable rows
                    continue
                native_id = f"carolina-{key.decode()}"
                try:
                    lattice = Lattice.from_parameters(
                        float(record["_cell_length_a"]),
                        float(record["_cell_length_b"]),
                        float(record["_cell_length_c"]),
                        float(record["_cell_angle_alpha"]),
                        float(record["_cell_angle_beta"]),
                        float(record["_cell_angle_gamma"]),
                    )
                    structure = Structure(
                        lattice,
                        [int(z) for z in record["atomic_numbers"]],
                        # despite its name this field is fractional
                        record["cart_coords"],
                        coords_are_cartesian=False,
                    )
                except Exception:  # noqa: BLE001 - keep nothing unparseable
                    continue

                properties = []
                energy = safe_float(record.get("energy"))
                if energy is not None and abs(energy) <= MAX_ABS_FORMATION_ENERGY:
                    properties.append(PropertyValue(
                        "formation_energy_per_atom", energy, "eV/atom", "PBE"
                    ))
                spacegroup = safe_float(record.get("_symmetry_Int_Tables_number"))
                if spacegroup and 1 <= spacegroup <= 230:
                    properties.append(PropertyValue(
                        "spacegroup_number", int(spacegroup), None, "PBE"
                    ))

                yield SourceRecord(
                    native_id=native_id,
                    properties=properties,
                    structure=structure,
                    match_ids=[],
                )
                count += 1

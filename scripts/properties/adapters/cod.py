"""COD: Crystallography Open Database, full-catalog parquet snapshot.

One 30.4GB parquet (533,486 rows, snapshot rev 282068) whose ``cif_text``
column holds the as-published experimental CIF; it is passed through
verbatim. Streamed with ``iter_batches`` over the needed columns only.

Filtering mirrors the original tier build (pipeline_stage1.py stage_cod)
minus the inorganic restriction: rows whose ``method`` says
theoretical/calculated, whose ``status`` is retracted/errors, or that carry a
``duplicateof``/``optimal`` redirect are dropped. Organics are deliberately
ADMITTED this time (the C/H block the old build excluded), and disordered
entries are not pre-filtered — the hash stage marks them DISORDERED and
drops them itself.

Every record is experimental. ``match_ids`` carries the record's own pool
notation id (cod-N), so the 25,339 COD entries already in the pool resolve
instantly by id; with the default always_hash=False an id hit means "this IS
that pool entry" and skips hashing. Rows without coordinates (or without CIF
text) are yielded structure-less so a pool-resident id can still collect
their properties; rows without a usable COD id are skipped outright.

Properties: mineral_name, chemical_name (chemname, else commonname; values
over 120 chars are skipped rather than truncated — a cut IUPAC name is
garbage), and measurement_temperature from diffrtemp/celltemp, which mirror
the CIF core tags _diffrn_ambient_temperature/_cell_measurement_temperature
and are defined in kelvins (sampled values: median 293, range 1.5-1100). Those
carry the plain method 'experiment (COD)'.

measurement_pressure comes from the two pressure columns, which mirror the CIF
core tags _diffrn_ambient_pressure (``diffrpressure``, 4,476 rows) and
_cell_measurement_pressure (``cellpressure``, 1,242 rows). Both are defined in
**kilopascals** by the CIF core dictionary — verified against the raw CIF text
of the high-pressure L-serine series, where cod-2100592 stores
``_cell_measurement_pressure 4500000`` for a 4.5 GPa neutron experiment — so
they are divided by 1e6 for the canonical GPa unit. The two tags describe
different moments of the experiment and 506 entries carry both, so they keep
separate methods ('experiment (COD) diffraction ambient' /
'experiment (COD) cell measurement') instead of one falling back to the other.

Bibliography/journal columns, R-factors and goodness-of-fit, radiation type
and wavelength, ``compoundsource`` (free-text sample provenance) and the
free-text ``thermalhist``/``pressurehist`` narratives are deliberately not
ingested, and neither are the cell metrics/space group/Z, which the pool
derives from the structure itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_COLUMNS = [
    "file",
    "method",
    "status",
    "duplicateof",
    "optimal",
    "flags",
    "cif_text",
    "mineral",
    "chemname",
    "commonname",
    "diffrtemp",
    "celltemp",
    "diffrpressure",
    "cellpressure",
]

_METHOD = "experiment (COD)"
_DROP_METHODS = {"theoretical", "calculated"}
_DROP_STATUS = {"retracted", "errors"}
_NAME_CAP = 120

#: kPa -> GPa; the CIF core dictionary defines both pressure tags in kPa
KPA_TO_GPA = 1.0e-6
#: 5e8 kPa = 500 GPa, comfortably above the 271 GPa diamond-anvil maximum
#: present in the snapshot; 0 and below are 'not recorded' sentinels
_PRESSURE_MAX_KPA = 5.0e8

# column -> method naming the CIF tag the value came from
_PRESSURES = (
    ("diffrpressure", f"{_METHOD} diffraction ambient"),
    ("cellpressure", f"{_METHOD} cell measurement"),
)


class CodAdapter(SourceAdapter):
    source_key = "cod"

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(
            root or PROJECT_ROOT / "data" / "raw" / "external_structs" / "cod"
        )

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(self.root / "cod_full.parquet")
        count = 0
        for batch in parquet.iter_batches(batch_size=2048, columns=_COLUMNS):
            data = batch.to_pydict()
            for i in range(len(data["file"])):
                if limit is not None and count >= limit:
                    return

                pair = normalize_match_id("cod", data["file"][i])
                if pair is None:
                    continue  # no usable COD id: nothing to attach to

                method = (data["method"][i] or "").strip().lower()
                if method in _DROP_METHODS:
                    continue
                status = (data["status"][i] or "").strip().lower()
                if status in _DROP_STATUS:
                    continue
                if data["duplicateof"][i] or data["optimal"][i]:
                    continue  # redirected onto another COD entry

                properties = []
                mineral = safe_text(data["mineral"][i])
                if mineral:
                    properties.append(
                        PropertyValue("mineral_name", mineral, None, _METHOD)
                    )
                name = safe_text(data["chemname"][i]) or safe_text(
                    data["commonname"][i]
                )
                if name and len(name) <= _NAME_CAP:
                    properties.append(
                        PropertyValue("chemical_name", name, None, _METHOD)
                    )
                temperature = safe_float(data["diffrtemp"][i])
                if temperature is None:
                    temperature = safe_float(data["celltemp"][i])
                if temperature is not None and 0 < temperature < 5000:
                    properties.append(
                        PropertyValue(
                            "measurement_temperature", temperature, "K", _METHOD
                        )
                    )
                for column, method in _PRESSURES:
                    pressure = safe_float(data[column][i])
                    if pressure is None or not 0 < pressure <= _PRESSURE_MAX_KPA:
                        continue
                    properties.append(
                        PropertyValue(
                            "measurement_pressure",
                            pressure * KPA_TO_GPA,
                            "GPa",
                            method,
                        )
                    )

                cif = data["cif_text"][i]
                flags = data["flags"][i] or ""
                if not cif or "has coordinates" not in flags:
                    # sites are absent: unhashable, but a pool-resident id
                    # match can still collect the properties
                    cif = None

                yield SourceRecord(
                    native_id=pair[1],
                    properties=properties,
                    structure=cif,
                    match_ids=[pair],
                    experimental=True,
                )
                count += 1

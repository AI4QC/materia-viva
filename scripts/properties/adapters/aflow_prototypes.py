"""AFLOW Prototype Encyclopedia: structure prototypes with ICSD parents.

One tarball of per-prototype directories, each holding ``info.json``
(metadata) and ``aflow.cif`` (symmetrized CIF of the decorated template).
Prototype decorations are idealised templates, not new materials, so
``properties_only`` keeps hash-misses out of the pool; records matching an
existing entry (via the ICSD parent id or via structure hash) annotate it
with the prototype label, mineral name, Strukturbericht designation, Pearson
symbol and space-group number. The free-parameter tables
(parameter_symbols/parameter_values), the compounds list, the CCDC id and the
TeX/notes fields are not properties of the matched material and stay out.
"""

from __future__ import annotations

import json
import tarfile
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

METHOD = "AFLOW prototype encyclopedia"


class AflowPrototypesAdapter(SourceAdapter):
    source_key = "aflow-prototypes"
    properties_only = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        archive = self.root / "aflow_prototype_encyclopedia-main.tar.gz"
        count = 0
        pending: dict[str, dict[str, str]] = {}
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                if limit is not None and count >= limit:
                    return
                if not member.isfile():
                    continue
                parts = member.name.split("/")
                # aflow_prototype_encyclopedia-main/data/<LABEL>/<file>
                if len(parts) != 4 or parts[1] != "data":
                    continue
                label, filename = parts[2], parts[3]
                if filename not in {"info.json", "aflow.cif"}:
                    continue
                handle = bundle.extractfile(member)
                if handle is None:
                    continue
                bucket = pending.setdefault(label, {})
                bucket[filename] = handle.read().decode("utf-8", "replace")
                if len(bucket) == 2:
                    del pending[label]
                    record = self._build(label, bucket)
                    if record is not None:
                        count += 1
                        yield record

    def _build(self, label: str, bucket: dict[str, str]) -> SourceRecord | None:
        try:
            info = json.loads(bucket["info.json"])
        except (KeyError, json.JSONDecodeError):
            return None
        cif = bucket.get("aflow.cif")
        properties = [
            PropertyValue("structure_prototype", label, None, METHOD),
        ]
        mineral = safe_text(info.get("mineral_name"))
        if mineral:
            properties.append(
                PropertyValue("mineral_name", mineral, None, METHOD)
            )
        strukturbericht = safe_text(info.get("strukturbericht"))
        if strukturbericht:
            properties.append(
                PropertyValue("strukturbericht", strukturbericht, None, METHOD)
            )
        pearson = safe_text(info.get("pearson_symbol"))
        if pearson:
            properties.append(
                PropertyValue("pearson_symbol", pearson, None, METHOD)
            )
        spacegroup = safe_float(info.get("space_group_number"))
        if spacegroup is not None and 1 <= spacegroup <= 230:
            properties.append(
                PropertyValue(
                    "spacegroup_number", int(spacegroup), None, METHOD
                )
            )
        match_ids = []
        icsd = normalize_match_id("icsd", info.get("icsd"))
        if icsd:
            match_ids.append(icsd)
        return SourceRecord(
            native_id=label,
            properties=properties,
            structure=cif,
            match_ids=match_ids,
        )

"""CSLLM PU-screened NON-synthesizable theoretical structures (negatives).

One zip (``unsym_structs_screen.zip``) of 106,470 pymatgen P1 CIFs that the
CSLLM positive-unlabeled screening classified as not synthesizable. These are
theoretical negatives, never pool candidates: the adapter is
``properties_only`` so the match stage drops every record without a pool hit,
and no structure is ever admitted as new. The CIF text is still passed
through so the hash stage can fingerprint each record and find pool matches;
there are no cross-database ids (``match_ids=[]``).

``predicted_synthesizable`` semantics: the False label attaches only to pool
materials whose fingerprint matches a screened structure — it asserts nothing
about materials outside the screened set, and a missing row is not a
prediction of synthesizability. Every record carries exactly this one
property (bool False, method 'CSLLM PU screening').

native_id is the CIF basename without extension (e.g. '1' for
``unsym_structs_screen/1.cif``).
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterator

from scripts.properties.base import (
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
)

_ARCHIVE = "unsym_structs_screen.zip"
_METHOD = "CSLLM PU screening"


class CsllmNegativesAdapter(SourceAdapter):
    source_key = "csllm-negatives"
    # negatives are labels on existing pool materials, never new structures
    properties_only = True
    # a hash match means "this record IS that pool structure": default stands
    always_hash = False

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(
            root
            or PROJECT_ROOT / "data" / "raw" / "external_structs" / "csllm_negatives"
        )

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        with zipfile.ZipFile(self.root / _ARCHIVE) as bundle:
            for name in bundle.namelist():
                if not name.endswith(".cif"):
                    continue
                if limit is not None and count >= limit:
                    return
                stem = name.rsplit("/", 1)[-1][: -len(".cif")]
                cif = bundle.read(name).decode("utf-8", errors="replace")
                count += 1
                yield SourceRecord(
                    native_id=stem,
                    properties=[
                        PropertyValue(
                            "predicted_synthesizable", False, None, _METHOD
                        )
                    ],
                    structure=cif,
                    match_ids=[],
                )

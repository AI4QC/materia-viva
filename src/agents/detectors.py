"""The deterministic half of the cleaner's work: find what needs judging.

The cleaner deduplicates and corrects. Neither is a judgement a script can make,
but both start from a scan a script can do exactly, and each of these three
answers a failure this repository has actually had:

* `mentions_of` — the gate compares hosts and names, so a candidate whose content
  the catalog already holds under another provider is invisible to it. CAMD was
  refused only because someone read `odbx.py` and found the word there; this makes
  that reading mechanical.
* `unit_disagreements` — an adapter can emit a canonical property under a unit the
  registry does not declare, and the unit is discarded on the way into
  `property_defs`, so the rows publish under the registry's unit carrying the
  adapter's numbers. That is how mc2d's interlayer binding energies came to be a
  thousandfold out.
* `stale_upstream_ids` — the gate catches prose still naming a replaced upstream
  id in a diff. Nothing catches it in the catalog as it stands.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = PROJECT_ROOT / "scripts" / "properties" / "adapters"
CATALOG = PROJECT_ROOT / "scripts" / "datasets" / "sources.json"


@dataclass(frozen=True)
class Mention:
    where: str
    line: int
    text: str


def mentions_of(name: str, *, catalog: Path = CATALOG,
                adapters: Path = ADAPTER_ROOT) -> list[Mention]:
    """Where the repository already talks about `name`.

    A candidate is redundant when something we ingest already carries its
    content, and the place that says so is usually the adapter that ingests it:
    `odbx.py` opens with "the CAMD dataset" and its native ids are `camd-oqmd_…`.
    Matching is case-insensitive on a word boundary so `CAMD` does not also hit
    `camdenite`.
    """
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.I)
    found: list[Mention] = []
    for path in sorted(adapters.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                found.append(Mention(f"adapters/{path.name}", number, line.strip()))
    entries = json.loads(catalog.read_text(encoding="utf-8"))["sources"]
    for entry in entries:
        for field in ("name", "status", "notes"):
            value = entry.get(field)
            if value and pattern.search(str(value)):
                found.append(Mention(f"catalog:{entry['id']}:{field}", 0, str(value)[:160]))
    return found


def unit_disagreements(*, adapters: Path = ADAPTER_ROOT) -> list[tuple[str, str, str, str]]:
    """Adapters emitting a canonical property under the wrong unit.

    Returns (adapter, property, emitted unit, unit the registry declares). Only
    literal units are read; a unit computed at runtime is not something a static
    pass can judge.
    """
    from scripts.properties.registry import CANONICAL_PROPERTIES

    out = []
    for path in sorted(adapters.glob("*.py")):
        if path.stem in {"__init__", "_util"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "PropertyValue"):
                continue
            args = node.args
            if len(args) < 3 or not isinstance(args[0], ast.Constant):
                continue
            canonical = CANONICAL_PROPERTIES.get(args[0].value)
            if canonical is None or not isinstance(args[2], ast.Constant):
                continue
            if args[2].value != canonical[0]:
                out.append((path.stem, args[0].value, args[2].value, canonical[0]))
    return out


#: An id only counts as an upstream reference when the prose says so. Status
#: strings are full of six-digit counts — oqmd's byte count, aflow's structure
#: count, carolina's record counts — and a first version of this flagged all of
#: them and nothing real. A check that cries wolf trains people to ignore it.
_REFERENCED_ID = re.compile(
    r"(?:zenodo|figshare|materialscloud|materials-cloud|record|article)[^0-9a-z]{0,3}(\d{6,})",
    re.I,
)


def stale_upstream_ids(catalog: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Upstream ids named in a source's prose that its download URLs no longer use.

    Returns (source id, field, the id). The same reading the gate applies to a
    diff, applied to the catalog as it stands — prose outlives the URL it
    describes, and nothing else looks.
    """
    out = []
    for source in catalog["sources"]:
        in_urls = {
            identifier
            for item in source.get("downloads", [])
            for identifier in re.findall(r"\d{6,}", item.get("url", ""))
        }
        if not in_urls:
            continue
        for field in ("status", "notes"):
            text = source.get(field) or ""
            named = set(_REFERENCED_ID.findall(text))
            for identifier in sorted(named - in_urls):
                out.append((source["id"], field, identifier))
    return out

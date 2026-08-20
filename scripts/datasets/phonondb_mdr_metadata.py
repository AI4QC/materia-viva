#!/usr/bin/env python3
"""OAI-PMH harvest of NIMS MDR record metadata, for the PhononDB crosswalk.

Why this exists
---------------
The PhononDB acquisition (``data/raw/acquired/phonondb``) carries ZERO
cross-database identifiers: the zips are named by bare MDR dataset UUIDs and
``phonopy_params.yaml`` holds no mp/icsd/cod/oqmd field. The MDR *record*
metadata does, though -- every PhononDB dataset is titled

    Ab-initio phonon calculation for KCaSiHO4 / P2_1 (4) / materials id 995190

where "materials id 995190" is the Materials Project entry the initial
structure came from (the description says so outright: "obtained from the
Materials Project using pymatgen MPRester"). Harvesting the record metadata
therefore restores an authoritative id route for the whole collection.

Route selection (probed 2026-08-18)
-----------------------------------
* ``/concern/datasets/<uuid>``            -> 404 (not the Hyrax layout)
* ``/datasets/<uuid>``                    -> 200 HTML, ~30 kB per record
* ``/datasets/<uuid>.json``               -> 200 schema.org JSON-LD, ~3 kB.
  Correct but needs 10,034 requests.
* ``/datasets?collection=<uuid>``         -> HTML result list, page size is
  pinned at 10 regardless of ``per_page``/``rows``/``limit``, and the server
  refuses to page past 10,000 of the 10,034 hits ("use facet search for the
  excess"). 1,004+ requests and ~110 MB of HTML.
* ``/datasets.json``, ``?format=json``, ``/catalog.json`` -> 404/406/410.
* DataCite: the collection DOI 10.48505/nims.4197 resolves but declares no
  child DOIs, and no per-record DOI exists (``api.datacite.org`` returns 0
  hits for the record UUIDs and for the title stem), so content negotiation
  cannot enumerate the collection.
* **``/oai`` -> OAI-PMH 2.0**, ``oai_dc`` and ``jpcoar_2.0``, 100 records per
  response with a resumption token. CHOSEN: it is the protocol the repository
  publishes for machine harvesting, and it costs ~235 requests instead of
  10,034 -- a 43x reduction in load on NIMS.

The repository exposes no setSpec (``ListSets`` is empty), so the harvest
necessarily streams all 23,439 MDR datasets and the PhononDB subset is
selected afterwards by UUID against the acquisition manifest. Records are
served in ascending UUID order and the OAI identifier IS the dataset UUID
(``oai:mdr.nims.go.jp:<uuid>``), which is what makes the join exact.

``robots.txt`` (fetched 2026-08-18) disallows only /contacts/, /dashboard/,
/links/, /previous_urls/ and /users/ -- neither /oai nor /datasets is
restricted.

Politeness
----------
Serial requests, ``--request-delay`` seconds between them (default 1.0),
honest User-Agent naming the project and a contact address, exponential
backoff on 429/5xx, and a hard stop with a printed diagnosis if the server
answers 429 or 403 twice in a row.

Resumability
------------
Each response is written verbatim to ``page-NNNNNN.xml``, and page *N* carries
the resumption token for page *N+1*, so a resumed run just re-reads the last
page on disk. If the server rejects a stored token as expired
(``badResumptionToken``) the harvest restarts from the first page and
overwrites, because the ordering is by UUID and therefore stable.

Outputs (under ``data/raw/acquired/phonondb/mdr-metadata-<date>/``)
------------------------------------------------------------------
* ``page-NNNNNN.xml``  -- verbatim OAI-PMH responses
* ``manifest.json``    -- endpoint, verb, counts, per-page bytes/sha256
* ``../uuid_to_mpid.json`` (written by ``--crosswalk``) --
  ``{uuid: {"mp_id": "mp-995190", "formula": "KCaSiHO4", ...}}``
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root

ENDPOINT = "https://mdr.nims.go.jp/oai"
METADATA_PREFIX = "oai_dc"
USER_AGENT = (
    "MateriaViva-dataset-acquisition/1.0 "
    "(materials-database crosswalk; contact smoakvescio@gmail.com)"
)
#: the OAI identifier prefix; the suffix is the MDR dataset UUID verbatim
OAI_PREFIX = "oai:mdr.nims.go.jp:"

_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

#: "... / materials id 995190" and the "mp-995190" / "mvc-11" spellings.
#: PhononDB titles use the bare-number form; the others are accepted so a
#: future MDR collection that spells the id out does not silently miss.
_MP_ID = re.compile(
    r"materials?[ _-]id[ :]+((?:mp-|mvc-)?\d+)", re.I
)
#: "Ab-initio phonon calculation for KCaSiHO4 / P2_1 (4) / materials id ..."
_TITLE = re.compile(
    r"^(?P<kind>.+?) for (?P<formula>[^/]+?)\s*/\s*"
    r"(?P<spacegroup>[^/]+?)\s*/\s*materials?[ _-]id",
    re.I,
)
_ICSD = re.compile(r"\bicsd[ _-]?(?:id|code|collection code)?[ :#-]*(\d{1,7})\b", re.I)


# --------------------------------------------------------------------------
# harvest
# --------------------------------------------------------------------------


def _request_url(*, token: str | None) -> str:
    params = (
        {"verb": "ListRecords", "resumptionToken": token}
        if token
        else {"verb": "ListRecords", "metadataPrefix": METADATA_PREFIX}
    )
    return f"{ENDPOINT}?{urlencode(params)}"


class RateLimited(RuntimeError):
    """The server asked us to back off; the caller must stop, not retry."""


class ExpiredToken(RuntimeError):
    """A stored resumption token is no longer valid; restart the harvest."""


def _fetch(url: str, *, attempts: int = 5, timeout: int = 180) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    throttles = 0
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as error:
            last_error = error
            if error.code in (403, 429):
                throttles += 1
                if throttles >= 2:
                    raise RateLimited(
                        f"HTTP {error.code} from {url}: the repository is "
                        "signalling rate limiting or refusing the client. "
                        "Stopping rather than pushing through."
                    ) from error
                time.sleep(60)
                continue
            if error.code < 500:
                raise
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
        if attempt + 1 < attempts:
            time.sleep(min(60, 2 ** (attempt + 1)))
    assert last_error is not None
    raise last_error


def _parse(payload: bytes) -> ET.Element:
    root = ET.fromstring(payload)
    error = root.find("oai:error", _NS)
    if error is not None:
        code = error.get("code", "")
        if code == "badResumptionToken":
            raise ExpiredToken(error.text or code)
        raise RuntimeError(f"OAI-PMH error {code}: {error.text}")
    return root


def _records(root: ET.Element) -> list[ET.Element]:
    return root.findall("./oai:ListRecords/oai:record", _NS)


def _token(root: ET.Element) -> str | None:
    node = root.find("./oai:ListRecords/oai:resumptionToken", _NS)
    if node is None or not (node.text or "").strip():
        return None
    return node.text.strip()


def _digest(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()


def _write_manifest(output_dir: Path, state: dict) -> None:
    manifest = dict(state)
    manifest["files"] = {
        path.name: dict(zip(("bytes", "sha256"), _digest(path)))
        for path in sorted(output_dir.glob("page-*.xml"))
    }
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    building = output_dir / "manifest.json.building"
    building.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    building.replace(output_dir / "manifest.json")


def harvest(*, output_dir: Path, request_delay: float = 1.0,
            max_pages: int | None = None) -> Path:
    """Stream every MDR record into page-NNNNNN.xml; resume where we stopped."""

    output_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(output_dir.glob("page-*.xml"))

    page = 0
    token: str | None = None
    records = 0
    if existing:
        # replay what is on disk: the last page carries the next token
        for path in existing:
            try:
                root = _parse(path.read_bytes())
            except (ET.ParseError, RuntimeError):
                break
            page += 1
            records += len(_records(root))
            token = _token(root)
        print(f"resuming after page {page} ({records} records on disk)", flush=True)
        if token is None and page:
            print("harvest already complete", flush=True)
            _write_manifest(output_dir, _state(page, records, complete=True))
            return output_dir / "manifest.json"

    started = datetime.now(timezone.utc).isoformat()
    while True:
        if max_pages is not None and page >= max_pages:
            print(f"stopping at --max-pages {max_pages}", flush=True)
            break
        url = _request_url(token=token)
        try:
            payload = _fetch(url)
            root = _parse(payload)
        except ExpiredToken:
            if page == 0:
                raise
            print(
                "stored resumption token expired; restarting the harvest from "
                "page 1 (records are served in stable UUID order)",
                flush=True,
            )
            page, token, records = 0, None, 0
            time.sleep(request_delay)
            continue
        page += 1
        (output_dir / f"page-{page:06d}.xml").write_bytes(payload)
        batch = len(_records(root))
        records += batch
        token = _token(root)
        print(f"page {page}: +{batch} (total {records})", flush=True)
        _write_manifest(
            output_dir,
            _state(page, records, complete=token is None, started=started),
        )
        if token is None:
            break
        time.sleep(request_delay)

    _write_manifest(
        output_dir, _state(page, records, complete=token is None, started=started)
    )
    return output_dir / "manifest.json"


def _state(pages: int, records: int, *, complete: bool,
           started: str | None = None) -> dict:
    state = {
        "source": "NIMS Materials Data Repository (MDR) OAI-PMH record metadata",
        "endpoint": ENDPOINT,
        "verb": "ListRecords",
        "metadata_prefix": METADATA_PREFIX,
        "identifier_scheme": f"{OAI_PREFIX}<mdr-dataset-uuid>",
        "collection_of_interest": "d7aab932-8512-4b9a-b93d-b61f6e5e7019",
        "collection_doi": "10.48505/nims.4197",
        "license": "CC BY 4.0",
        "note": (
            "The repository publishes no setSpec, so the harvest streams every "
            "MDR dataset; the PhononDB subset is selected by UUID against "
            "../manifest.json dataset_ids."
        ),
        "user_agent": USER_AGENT,
        "pages": pages,
        "records": records,
        "complete": complete,
    }
    if started:
        state["started_at"] = started
    return state


# --------------------------------------------------------------------------
# crosswalk
# --------------------------------------------------------------------------


def _text(node: ET.Element, tag: str) -> str:
    found = node.find(tag, _NS)
    return (found.text or "").strip() if found is not None else ""


def _all_text(node: ET.Element, tag: str) -> list[str]:
    return [(item.text or "").strip() for item in node.findall(tag, _NS)]


def iter_harvested(output_dir: Path):
    """Yield (uuid, dc-fields) for every harvested record."""

    for path in sorted(output_dir.glob("page-*.xml")):
        try:
            root = _parse(path.read_bytes())
        except (ET.ParseError, RuntimeError):
            continue
        for record in _records(root):
            identifier = _text(record, "./oai:header/oai:identifier")
            if not identifier.startswith(OAI_PREFIX):
                continue
            uuid = identifier[len(OAI_PREFIX):]
            dublin = record.find("./oai:metadata/oai_dc:dc", _NS)
            if dublin is None:
                continue
            yield uuid, {
                "title": _text(dublin, "dc:title"),
                "description": _text(dublin, "dc:description"),
                "subjects": _all_text(dublin, "dc:subject"),
                "identifiers": _all_text(dublin, "dc:identifier"),
            }


def normalise_mp_id(raw: str) -> str:
    """'995190' / 'mp-995190' / 'mvc-11' -> the canonical MP id string."""

    value = raw.strip().lower()
    if value.startswith(("mp-", "mvc-")):
        return value
    return f"mp-{value}"


def parse_record(fields: dict) -> dict | None:
    """Pull mp id / formula / spacegroup / ICSD out of one record's DC fields."""

    title = fields.get("title", "")
    haystack = f"{title}\n{fields.get('description', '')}"
    match = _MP_ID.search(haystack)
    if not match:
        return None
    entry = {"mp_id": normalise_mp_id(match.group(1))}

    parsed = _TITLE.match(title)
    subjects = [value for value in fields.get("subjects", []) if value]
    if parsed:
        entry["formula"] = parsed.group("formula").strip()
        entry["spacegroup"] = parsed.group("spacegroup").strip()
    elif len(subjects) >= 2:
        entry["formula"] = subjects[1]
    entry["title"] = title

    icsd = _ICSD.search(haystack)
    if icsd:
        entry["icsd_id"] = icsd.group(1)
    return entry


def build_crosswalk(*, output_dir: Path, acquisition_dir: Path,
                    destination: Path) -> dict:
    """Join the harvest onto the acquisition's dataset_ids and write the map."""

    manifest = json.loads(
        (acquisition_dir / "manifest.json").read_text(encoding="utf-8")
    )
    wanted = list(manifest.get("dataset_ids") or [])
    wanted_set = set(wanted)

    crosswalk: dict[str, dict] = {}
    seen = 0
    unparsed: list[str] = []
    for uuid, fields in iter_harvested(output_dir):
        if uuid not in wanted_set:
            continue
        seen += 1
        entry = parse_record(fields)
        if entry is None:
            unparsed.append(uuid)
            continue
        crosswalk[uuid] = entry

    ordered = {uuid: crosswalk[uuid] for uuid in wanted if uuid in crosswalk}
    destination.write_text(
        json.dumps(ordered, indent=1, sort_keys=False) + "\n", encoding="utf-8"
    )

    report = {
        "requested": len(wanted),
        "found_in_harvest": seen,
        "resolved_mp_ids": len(ordered),
        "harvested_without_mp_id": len(unparsed),
        "missing_from_harvest": len(wanted_set) - seen,
        "distinct_mp_ids": len({item["mp_id"] for item in ordered.values()}),
        "with_formula": sum(1 for item in ordered.values() if item.get("formula")),
        "with_icsd": sum(1 for item in ordered.values() if item.get("icsd_id")),
        "destination": str(destination),
    }
    print(json.dumps(report, indent=2), flush=True)
    return report


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--crosswalk",
        action="store_true",
        help="skip fetching and only rebuild uuid_to_mpid.json from the pages",
    )
    args = parser.parse_args()

    acquisition = default_data_root() / "raw" / "acquired" / "phonondb"
    output = args.output or (acquisition / "mdr-metadata-2026-08-18")

    if not args.crosswalk:
        print(harvest(
            output_dir=output,
            request_delay=args.request_delay,
            max_pages=args.max_pages,
        ))
    build_crosswalk(
        output_dir=output,
        acquisition_dir=acquisition,
        destination=acquisition / "uuid_to_mpid.json",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

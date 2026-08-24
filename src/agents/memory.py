"""What a sweep already looked at and turned down.

A candidate refused at the gate never enters the catalog and, until this file
existed, left no trace — so the next sweep proposed the same four again and paid
the challenger to kill them a second time. This is that trace.

Only refusals are remembered. A candidate that was accepted is in
`sources.json`, which is already a memory of it; recording it twice would give
the same fact two homes.

The file is **in the repository, not beside the run records**, for two reasons.
A refusal is a judgement — someone decided a database was redundant, or its
licence would not clear — and a judgement is worth reviewing as a diff. And a
memory that lives on one machine is lost the moment the work moves, which is the
cost the probe's baseline already pays and does not need paying twice.

Nothing here is written by an agent. A role proposes and a role attacks; a
person runs `remember` once they have read the outcome. Section 1.2 again: an
agent may propose anything, and nothing enters on its word.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REJECTED = PROJECT_ROOT / "scripts" / "datasets" / "rejected.json"


@dataclass(frozen=True)
class Rejection:
    """One candidate that was looked at and turned down."""

    id: str
    url: str
    why: str
    when: str
    #: the run whose artifacts the decision was read from, when there was one
    run_id: str = ""


def load(path: Path | None = None) -> list[Rejection]:
    # resolved on call, not bound at import: a default argument would freeze the
    # module constant at definition time and quietly ignore any later redirection
    path = path or REJECTED
    if not path.exists():
        return []
    return [Rejection(**entry) for entry in json.loads(path.read_text(encoding="utf-8"))]


def remember(
    id: str,
    url: str,
    why: str,
    *,
    run_id: str = "",
    path: Path | None = None,
    now: datetime | None = None,
) -> Rejection:
    """Record a refusal. Re-recording the same id replaces it rather than duplicating.

    A candidate can be looked at twice and turned down for a better reason the
    second time; two rows saying different things about one id is the drift this
    module exists to prevent.
    """
    path = path or REJECTED
    if not why.strip():
        raise ValueError(f"{id} needs a reason: a refusal nobody can read is not a memory")
    entry = Rejection(
        id=id, url=url, why=why.strip(), run_id=run_id,
        when=(now or datetime.now(timezone.utc)).date().isoformat(),
    )
    kept = [row for row in load(path) if row.id != id]
    kept.append(entry)
    kept.sort(key=lambda row: row.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(row) for row in kept], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return entry


def briefing(path: Path | None = None, limit: int = 40) -> str:
    """The refusals, as a line an explorer's task can carry.

    Empty when nothing has been refused, so the first sweep is not handed a
    paragraph explaining that there is nothing to tell it.
    """
    path = path or REJECTED
    rows = load(path)
    if not rows:
        return ""
    shown = rows[:limit]
    lines = "\n".join(f"- {row.id} ({row.url}): {row.why}" for row in shown)
    more = f"\n- …and {len(rows) - len(shown)} more in {path.name}" if len(rows) > len(shown) else ""
    return (
        "These candidates have already been looked at and turned down. Do not propose them "
        f"again unless you have evidence the reason no longer holds — say so explicitly if you do:\n{lines}{more}"
    )

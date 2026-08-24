"""What a run spent, in units that survive changing provider.

Dollars are a provider's opinion; tokens are what was actually consumed, and they
are the only figure that still compares after a model or a vendor changes. So a
run records tokens first and cost second, split the way every provider splits
them — read in, written out, and the two cache classes that make a long agent
loop affordable.

`Usage` is deliberately not the SDK's shape. `claude_agent_sdk` reports camelCase
`ModelUsage` per model; another backend will report something else. Each executor
maps its provider's shape into this one, which is what keeps the accounting, the
budget and the trace from having to know who ran the work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class Usage:
    """Tokens spent, provider-neutral."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float | None = None
    #: model name -> provider, for a run that used more than one
    models: tuple[tuple[str, str], ...] = ()

    @property
    def total(self) -> int:
        """Every token the provider counted, cache included.

        Cache reads are cheap, not free, and leaving them out of the total is how
        a loop that looks affordable per turn stops being affordable per sweep.
        """
        return self.input + self.output + self.cache_read + self.cache_write

    @property
    def billable(self) -> int:
        """Tokens that were not served from cache."""
        return self.input + self.output + self.cache_write

    def __add__(self, other: "Usage") -> "Usage":
        costs = [c for c in (self.cost_usd, other.cost_usd) if c is not None]
        return Usage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
            cost_usd=round(sum(costs), 6) if costs else None,
            models=tuple(dict.fromkeys(self.models + other.models)),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "total": self.total,
            "billable": self.billable,
            "cost_usd": self.cost_usd,
            "models": [list(pair) for pair in self.models],
        }

    @classmethod
    def from_record(cls, record: dict[str, Any] | None) -> "Usage":
        if not record:
            return cls()
        return cls(
            input=record.get("input", 0),
            output=record.get("output", 0),
            cache_read=record.get("cache_read", 0),
            cache_write=record.get("cache_write", 0),
            cost_usd=record.get("cost_usd"),
            models=tuple(tuple(pair) for pair in record.get("models", ())),
        )


def from_anthropic_model_usage(model_usage: dict[str, Any] | None,
                               total_cost_usd: float | None = None) -> Usage:
    """Map `claude_agent_sdk`'s per-model camelCase report into `Usage`."""
    if not model_usage:
        return Usage(cost_usd=total_cost_usd)
    spent = Usage(cost_usd=total_cost_usd)
    for model, per in model_usage.items():
        spent = spent + Usage(
            input=per.get("inputTokens", 0),
            output=per.get("outputTokens", 0),
            cache_read=per.get("cacheReadInputTokens", 0),
            cache_write=per.get("cacheCreationInputTokens", 0),
            models=((model, per.get("provider", "anthropic")),),
        )
    return Usage(**{**spent.__dict__, "cost_usd": total_cost_usd})


@dataclass
class Budget:
    """A ceiling a pipeline is stopped against, before the step that would break it.

    The proposal put a sweep at roughly 300k tokens and noted that nothing
    enforced a limit. This is the limit. It is checked before a step rather than
    after, because a budget you discover you have exceeded is a report, not a
    budget.

    Counted in tokens and not in money, for the same reason `Usage` is: a ceiling
    in a provider's currency stops meaning the same thing when the provider or
    its prices change. Cost is still recorded and reported; it is just not what
    the limit is drawn in.
    """

    tokens: int | None = None
    spent: Usage = field(default_factory=Usage)

    def record(self, usage: Usage) -> None:
        self.spent = self.spent + usage

    @property
    def exhausted(self) -> bool:
        return self.remaining_tokens == 0

    @property
    def remaining_tokens(self) -> int | None:
        return None if self.tokens is None else max(0, self.tokens - self.spent.total)

    def why(self) -> str:
        if self.remaining_tokens == 0:
            return f"token budget of {self.tokens:,} is spent ({self.spent.total:,} used)"
        return ""


def run_records(root: Path) -> Iterator[dict[str, Any]]:
    """Every per-run record under a runs directory, oldest path first."""
    for path in sorted(root.rglob("run.json")):
        try:
            yield json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue


def trace(root: Path, *, by: str = "role") -> dict[str, Usage]:
    """What has been spent, grouped.

    `by` is any field the record carries — `role`, `backend`, or `started_at`
    truncated to a day, which is the one a monthly ceiling is argued over.
    """
    grouped: dict[str, Usage] = {}
    for record in run_records(root):
        key = record.get(by) or "unknown"
        if by == "day":
            key = (record.get("started_at") or "unknown")[:10]
        grouped[key] = grouped.get(key, Usage()) + Usage.from_record(record.get("usage"))
    return dict(sorted(grouped.items()))


def total(root: Path) -> Usage:
    spent = Usage()
    for record in run_records(root):
        spent = spent + Usage.from_record(record.get("usage"))
    return spent


def report(root: Path, *, by: str = "role") -> list[str]:
    grouped = trace(root, by=by)
    if not grouped:
        return [f"no runs recorded under {root}"]
    width = max(len(k) for k in grouped)
    lines = [f"{'':{width}}  {'total':>12}  {'billable':>10}  {'cached':>10}  {'cost':>8}"]
    for key, usage in grouped.items():
        cost = "" if usage.cost_usd is None else f"${usage.cost_usd:.2f}"
        lines.append(
            f"{key:{width}}  {usage.total:>12,}  {usage.billable:>10,}  "
            f"{usage.cache_read:>10,}  {cost:>8}"
        )
    whole = total(root)
    lines.append(f"{'all':{width}}  {whole.total:>12,}  {whole.billable:>10,}  "
                 f"{whole.cache_read:>10,}  "
                 f"{'' if whole.cost_usd is None else f'${whole.cost_usd:.2f}':>8}")
    return lines

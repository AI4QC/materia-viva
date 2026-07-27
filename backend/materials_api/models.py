"""API response models and shared query parsing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pymatgen.core import Element


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    pages: int
    facets: dict[str, Any]


class ApiStatus(BaseModel):
    status: str = "ok"
    index_ready: bool
    ovito_available: bool


def parse_element_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    result: list[str] = []
    for raw in value.split(","):
        symbol = raw.strip()
        if not symbol:
            continue
        try:
            normalized = Element(symbol).symbol
        except Exception as exc:
            raise ValueError(f"unknown element: {symbol}") from exc
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def parse_csv(value: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in (value or "").split(",") if item.strip()))

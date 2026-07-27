"""Filesystem layout for the standalone MatData repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepositoryLayout:
    root: Path

    @classmethod
    def from_root(cls, root: str | Path) -> "RepositoryLayout":
        return cls(Path(root).resolve())

    @classmethod
    def from_anchor(cls, anchor: str | Path) -> "RepositoryLayout":
        return cls.from_root(Path(anchor).resolve().parents[1])

    @property
    def backend(self) -> Path:
        return self.root / "backend"

    @property
    def frontend_static(self) -> Path:
        return self.backend / "static"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def experimental_source(self) -> Path:
        return self.data / "sources" / "experimental"

    @property
    def candidate_source(self) -> Path:
        return self.data / "sources" / "candidate"

    @property
    def stats(self) -> Path:
        return self.data / "raw" / "external_structs" / "work" / "stats"

    @property
    def index(self) -> Path:
        return self.data / "index"

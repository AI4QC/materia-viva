"""Append-only compressed storage for random-access CIF payloads."""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class BlobRef:
    offset: int
    length: int


class BlobWriter:
    def __init__(self, path: str | Path, *, compression_level: int = 6) -> None:
        self.path = Path(path)
        self.compression_level = compression_level
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "BlobWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("wb")
        return self

    def append(self, text: str) -> BlobRef:
        if self._handle is None:
            raise RuntimeError("BlobWriter is not open")
        payload = zlib.compress(text.encode("utf-8"), self.compression_level)
        offset = self._handle.tell()
        self._handle.write(payload)
        return BlobRef(offset=offset, length=len(payload))

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


class BlobReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "BlobReader":
        self._handle = self.path.open("rb")
        return self

    def read(self, offset: int, length: int) -> str:
        if self._handle is None:
            raise RuntimeError("BlobReader is not open")
        if offset < 0 or length <= 0:
            raise ValueError("invalid blob range")
        self._handle.seek(offset)
        payload = self._handle.read(length)
        if len(payload) != length:
            raise ValueError("corrupt CIF blob: truncated payload")
        try:
            return zlib.decompress(payload).decode("utf-8")
        except (zlib.error, UnicodeDecodeError) as exc:
            raise ValueError("corrupt CIF blob payload") from exc

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

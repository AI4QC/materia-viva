"""Robust, cached OVITO rendering isolated from the FastAPI process.

The subprocess boundary follows the proven catdt ``core/viz`` pattern: native
OVITO/Tachyon failures cannot crash the long-lived web server.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RENDERER_VERSION = "2"


class OvitoRenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderOptions:
    view: str = "isometric"
    representation: str = "ball_stick"
    supercell: tuple[int, int, int] = (2, 2, 2)
    show_cell: bool = True
    quality: str = "preview"

    def __post_init__(self) -> None:
        if self.view not in {"isometric", "front", "top"}:
            raise ValueError("view must be isometric, front, or top")
        if self.representation not in {"ball_stick", "spacefill"}:
            raise ValueError("representation must be ball_stick or spacefill")
        if self.quality not in {"preview", "high"}:
            raise ValueError("quality must be preview or high")
        if len(self.supercell) != 3 or any(value < 1 or value > 4 for value in self.supercell):
            raise ValueError("supercell values must be between 1 and 4")


class OvitoRenderService:
    def __init__(
        self,
        cache_dir: str | Path,
        *,
        worker_python: str | Path | None = None,
        timeout_seconds: int = 180,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.worker_python = str(
            worker_python
            or os.environ.get("MATERIALS_OVITO_PYTHON")
            or sys.executable
        )
        self.timeout_seconds = max(10, timeout_seconds)
        self.runner = runner
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def available(self) -> bool:
        return Path(self.worker_python).is_file()

    def render(self, cif: str, material_id: str, options: RenderOptions) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = self._cache_key(cif, options)
        target = self.cache_dir / f"{cache_key}.png"
        if self._valid_png(target):
            return target

        with self._lock_for(cache_key):
            if self._valid_png(target):
                return target
            input_handle = tempfile.NamedTemporaryFile(
                mode="w", suffix=".cif", prefix="materiaviva-", delete=False,
                encoding="utf-8",
            )
            temp_input = Path(input_handle.name)
            temp_output = target.with_suffix(".tmp.png")
            try:
                input_handle.write(cif)
                input_handle.close()
                command = self._command(temp_input, temp_output, options)
                environment = self._environment()
                try:
                    result = self.runner(
                        command,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout_seconds,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise OvitoRenderError(
                        f"OVITO render timed out after {self.timeout_seconds}s"
                    ) from exc
                if result.returncode != 0:
                    error = (result.stderr or result.stdout or "unknown OVITO failure").strip()[-2_000:]
                    raise OvitoRenderError(
                        f"OVITO subprocess failed for {material_id} (code {result.returncode}): {error}"
                    )
                if not self._valid_png(temp_output):
                    raise OvitoRenderError("OVITO worker did not produce a valid PNG")
                os.replace(temp_output, target)
                return target
            finally:
                input_handle.close()
                temp_input.unlink(missing_ok=True)
                temp_output.unlink(missing_ok=True)

    async def render_async(self, cif: str, material_id: str, options: RenderOptions) -> Path:
        """Render without blocking the ASGI event loop.

        Custom runners are used only by unit tests and complete synchronously.
        Production uses asyncio's subprocess transport, keeping OVITO isolated
        without relying on the host interpreter's default thread executor.
        """

        if self.runner is not subprocess.run:
            return self.render(cif, material_id, options)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache_dir / f"{self._cache_key(cif, options)}.png"
        if self._valid_png(target):
            return target

        input_handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".cif", prefix="materiaviva-", delete=False,
            encoding="utf-8",
        )
        output_handle = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="materiaviva-", dir=self.cache_dir, delete=False
        )
        temp_input = Path(input_handle.name)
        temp_output = Path(output_handle.name)
        output_handle.close()
        try:
            input_handle.write(cif)
            input_handle.close()
            process = await asyncio.create_subprocess_exec(
                *self._command(temp_input, temp_output, options),
                env=self._environment(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.wait()
                raise OvitoRenderError(
                    f"OVITO render timed out after {self.timeout_seconds}s"
                ) from exc
            if process.returncode != 0:
                error = (stderr or stdout or b"unknown OVITO failure").decode(
                    "utf-8", errors="replace"
                ).strip()[-2_000:]
                raise OvitoRenderError(
                    f"OVITO subprocess failed for {material_id} (code {process.returncode}): {error}"
                )
            if not self._valid_png(temp_output):
                raise OvitoRenderError("OVITO worker did not produce a valid PNG")
            if self._valid_png(target):
                return target
            os.replace(temp_output, target)
            return target
        finally:
            input_handle.close()
            temp_input.unlink(missing_ok=True)
            temp_output.unlink(missing_ok=True)

    @staticmethod
    def _cache_key(cif: str, options: RenderOptions) -> str:
        return hashlib.sha256(
            RENDERER_VERSION.encode("ascii")
            + cif.encode("utf-8")
            + json.dumps(asdict(options), sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _command(self, input_path: Path, output_path: Path, options: RenderOptions) -> list[str]:
        command = [
            self.worker_python,
            "-m",
            "materials_api.ovito_worker",
            str(input_path),
            "--output",
            str(output_path),
            "--view",
            options.view,
            "--representation",
            options.representation,
            "--supercell",
            ",".join(str(value) for value in options.supercell),
            "--quality",
            options.quality,
        ]
        if options.show_cell:
            command.append("--show-cell")
        return command

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        backend_root = str(Path(__file__).resolve().parents[1])
        environment["PYTHONPATH"] = backend_root + os.pathsep + environment.get("PYTHONPATH", "")
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        return environment

    def _lock_for(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    @staticmethod
    def _valid_png(path: Path) -> bool:
        if not path.is_file() or path.stat().st_size < len(PNG_SIGNATURE):
            return False
        with path.open("rb") as handle:
            return handle.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE

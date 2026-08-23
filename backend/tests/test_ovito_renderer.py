import subprocess
import sys
import asyncio

import pytest

from materials_api.ovito_renderer import (
    OvitoRenderError,
    OvitoRenderService,
    RenderOptions,
    _probe_ovito,
)


PNG = b"\x89PNG\r\n\x1a\nrendered"


def test_ovito_renderer_uses_isolated_worker_and_content_addressed_cache(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        output = command[command.index("--output") + 1]
        with open(output, "wb") as handle:
            handle.write(PNG)
        return subprocess.CompletedProcess(command, 0, "", "")

    service = OvitoRenderService(
        cache_dir=tmp_path / "cache",
        worker_python="/opt/ovito/bin/python",
        runner=runner,
    )
    options = RenderOptions(view="isometric", representation="ball_stick", show_cell=True)

    first = service.render("data_Li\n", "exp-1", options)
    second = service.render("data_Li\n", "exp-1", options)

    assert first == second
    assert first.read_bytes() == PNG
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:3] == ["/opt/ovito/bin/python", "-m", "materials_api.ovito_worker"]
    assert "--show-cell" in command
    assert kwargs["timeout"] >= 10


def test_ovito_renderer_cache_key_includes_view_options(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        output = command[command.index("--output") + 1]
        with open(output, "wb") as handle:
            handle.write(PNG)
        return subprocess.CompletedProcess(command, 0, "", "")

    service = OvitoRenderService(tmp_path, runner=runner)
    iso = service.render("data_Si\n", "pool-1", RenderOptions(view="isometric"))
    top = service.render("data_Si\n", "pool-1", RenderOptions(view="top"))

    assert iso != top
    assert len(calls) == 2


def test_async_render_path_preserves_cache_contract_for_api(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        output = command[command.index("--output") + 1]
        with open(output, "wb") as handle:
            handle.write(PNG)
        return subprocess.CompletedProcess(command, 0, "", "")

    service = OvitoRenderService(tmp_path, runner=runner)
    first = asyncio.run(service.render_async("data_C\n", "c-1", RenderOptions()))
    second = asyncio.run(service.render_async("data_C\n", "c-1", RenderOptions()))

    assert first == second
    assert len(calls) == 1


def test_ovito_renderer_surfaces_bounded_worker_error(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 7, "", "native failure " * 400)

    service = OvitoRenderService(tmp_path, runner=runner)

    with pytest.raises(OvitoRenderError, match="native failure") as error:
        service.render("data_Bad\n", "bad", RenderOptions())

    assert len(str(error.value)) < 2400


def test_available_is_false_when_the_worker_interpreter_cannot_import_ovito(tmp_path):
    # The regression this guards: the fallback interpreter is the one running
    # this process, so "the file exists" was always true and /api/health
    # advertised server-side rendering on hosts with no OVITO at all.
    service = OvitoRenderService(
        tmp_path / "cache",
        worker_python=sys.executable,
        prober=lambda _: False,
    )

    assert service.available() is False


def test_available_is_true_only_when_the_import_succeeds(tmp_path):
    service = OvitoRenderService(
        tmp_path / "cache",
        worker_python=sys.executable,
        prober=lambda _: True,
    )

    assert service.available() is True


def test_available_skips_the_probe_when_the_interpreter_is_missing(tmp_path):
    probed = []

    service = OvitoRenderService(
        tmp_path / "cache",
        worker_python=tmp_path / "no-such-python",
        prober=lambda path: probed.append(path) or True,
    )

    assert service.available() is False
    assert probed == []


def test_available_probes_once_and_caches(tmp_path):
    calls = []

    service = OvitoRenderService(
        tmp_path / "cache",
        worker_python=sys.executable,
        prober=lambda path: (calls.append(path), True)[1],
    )

    assert [service.available() for _ in range(3)] == [True, True, True]
    assert len(calls) == 1


def test_probe_reports_unavailable_for_an_interpreter_that_cannot_be_executed():
    assert _probe_ovito("/nonexistent/bin/python") is False

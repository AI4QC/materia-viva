import asyncio
import subprocess
import sys

import pytest

from materials_api.ovito_renderer import OvitoRenderError, OvitoRenderService, RenderOptions


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


def test_availability_asks_whether_ovito_imports_not_whether_a_file_exists(tmp_path):
    """`sys.executable` always exists, so the old check always said yes.

    On a machine without OVITO the service fell back to the host interpreter,
    reported itself available, and the frontend promised a render that could
    only ever fail.
    """
    asked = []

    def runner(command, **kwargs):
        asked.append(command)
        return subprocess.CompletedProcess(command, 1, "", "ModuleNotFoundError: No module named 'ovito'")

    service = OvitoRenderService(cache_dir=tmp_path, worker_python=sys.executable, runner=runner)

    assert service.available() is False
    assert asked, "availability was decided without asking the interpreter anything"


def test_availability_is_decided_once_rather_than_per_request(tmp_path):
    # /api/stats is on the landing page's critical path; a subprocess per call is not free
    asked = []

    def runner(command, **kwargs):
        asked.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    service = OvitoRenderService(cache_dir=tmp_path, worker_python=sys.executable, runner=runner)

    assert service.available() is True
    assert service.available() is True
    assert len(asked) == 1


def test_a_worker_traceback_is_not_handed_to_the_caller_verbatim(tmp_path):
    """The 503 body reached the browser as a traceback carrying ANSI colour codes."""
    traceback = (
        "Traceback (most recent call last):\n"
        '  File \x1b[35m"/x/ovito_worker.py"\x1b[0m, line \x1b[35m133\x1b[0m, in \x1b[35m<module>\x1b[0m\n'
        "    raise SystemExit(main())\n"
        "ModuleNotFoundError: No module named 'ovito'"
    )

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", traceback)

    service = OvitoRenderService(cache_dir=tmp_path, worker_python="/opt/ovito/bin/python",
                                 runner=runner)

    with pytest.raises(OvitoRenderError) as failure:
        service.render("data_Li\n", "exp-1", RenderOptions())

    message = str(failure.value)
    assert "\x1b[" not in message, "ANSI escapes reached the caller"
    assert "Traceback (most recent call last)" not in message
    assert "No module named 'ovito'" in message, "the actual reason was thrown away"

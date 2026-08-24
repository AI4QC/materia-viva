import json
from datetime import datetime, timedelta, timezone

from src.agents.schedule import CADENCE, JOBS, crontab_line, due, load_state, mark, run_due

WHEN = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)


def test_a_job_that_has_never_run_is_due_now(tmp_path):
    ready = [job.name for job in due(path=tmp_path / "schedule.json", now=WHEN)]
    assert ready == ["probe", "audit"]


def test_a_job_that_just_ran_is_not_due_again(tmp_path):
    state = tmp_path / "schedule.json"
    mark("probe", path=state, now=WHEN)
    ready = [job.name for job in due(path=state, now=WHEN + timedelta(days=1))]
    assert "probe" not in ready and "audit" in ready


def test_a_job_becomes_due_once_its_cadence_has_elapsed(tmp_path):
    state = tmp_path / "schedule.json"
    mark("probe", path=state, now=WHEN)
    assert "probe" not in [j.name for j in due(path=state, now=WHEN + timedelta(days=6))]
    assert "probe" in [j.name for j in due(path=state, now=WHEN + timedelta(days=7))]


def test_the_expensive_sweep_never_comes_round_by_itself():
    """`agent-framework.md` says nothing puts a sweep on a timer until one has run
    unattended and been read. That is a cadence, so it belongs in the cadence table."""
    assert JOBS["discovery-sweep"].manual
    assert JOBS["upgrade"].manual  # cannot be scheduled: it has to be told which source
    assert all(job.what.strip() for job in CADENCE)


def test_a_failed_job_stays_due_rather_than_counting_as_done(tmp_path):
    state = tmp_path / "schedule.json"

    def explode():
        raise RuntimeError("upstream said no")

    done = run_due(path=state, now=WHEN, runners={"probe": explode})
    assert ("probe", "failed: RuntimeError: upstream said no") in done
    assert "probe" not in load_state(state)
    assert "probe" in [job.name for job in due(path=state, now=WHEN)]


def test_a_job_with_no_runner_is_reported_not_silently_marked(tmp_path):
    state = tmp_path / "schedule.json"
    done = run_due(path=state, now=WHEN, runners={})
    assert dict(done) == {"probe": "no runner", "audit": "no runner"}
    assert load_state(state) == {}


def test_a_successful_job_is_recorded(tmp_path):
    state = tmp_path / "schedule.json"
    ran = []
    run_due(path=state, now=WHEN, runners={"probe": lambda: ran.append("probe"),
                                           "audit": lambda: ran.append("audit")})
    assert ran == ["probe", "audit"]
    assert set(load_state(state)) == {"probe", "audit"}


def test_a_truncated_state_file_does_not_stop_the_schedule_for_ever(tmp_path):
    state = tmp_path / "schedule.json"
    state.write_text("{not json", encoding="utf-8")
    assert load_state(state) == {}
    assert [job.name for job in due(path=state, now=WHEN)] == ["probe", "audit"]


def test_the_cron_line_calls_the_command_that_exists(tmp_path):
    line = crontab_line()
    assert "-m src.agents due --run" in line
    assert "PYTHONPATH=backend:." in line  # the gate needs it; so does importing src.agents


def test_the_state_file_is_written_where_a_human_can_read_it(tmp_path):
    state = tmp_path / "nested" / "schedule.json"
    mark("probe", path=state, now=WHEN)
    assert json.loads(state.read_text(encoding="utf-8"))["probe"].startswith("2026-08-24")

"""What each job kind does — over fake applications, a fake ``systemd-run`` and mocked HTTP.

No test here launches a real application, reaches a real Ollama or touches the operator's home:
every executable is a fixture script in ``tmp_path``, every application configured explicitly (an
unconfigured one would be looked up on ``PATH``), and the data root is redirected.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

from tests.integration.test_jobs_queue import T0, database, services_for, settings_for
from tests.support import fake_application
from weightroom.domain.jobs import JOB_KINDS, SUITE_RUN_SCOPE_PREFIX
from weightroom.services.job_kinds import EXECUTORS
from weightroom.services.jobs import (
    JobContext,
    JobServices,
    JobView,
    Outcome,
    OutputBuffer,
    claim_next,
    enqueue,
    finish,
)

if TYPE_CHECKING:
    from pathlib import Path

    from weightroom.config import Settings
    from weightroom.services.database import Database

__all__ = ["database"]  # the fixture, re-used from the queue's tests

RUN_ID = "01RUNFIXTURE0000000000000A"


def run_kind(
    database: Database,
    settings: Settings,
    services: JobServices,
    kind: str,
    params: dict[str, object],
) -> tuple[Outcome, str, JobView]:
    """Queue, claim and execute one job of ``kind`` directly, without the worker."""
    job = enqueue(database, kind=kind, params=params, now=T0)
    claimed = claim_next(database, now=T0, lease_seconds=60)
    assert claimed is not None
    assert claimed.id == job.id
    output = OutputBuffer(1_000_000)
    context = JobContext(
        job=claimed,
        settings=settings,
        database=database,
        services=services,
        output=output,
        cancelled=lambda: False,
        now=lambda: T0,
    )
    return EXECUTORS[kind](context), output.text(), claimed


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _systemd_run(tmp_path: Path) -> Path:
    """Records its argv, then runs what follows its ten scope arguments — as the real one does."""
    record = tmp_path / "systemd-run.argv"
    return _script(
        tmp_path / "systemd-run", f'printf "%s\\n" "$@" > {record}\nshift 10\nexec "$@"\n'
    )


def _freeweight(tmp_path: Path, *, start_exit: int = 0) -> Path:
    return _script(
        tmp_path / "freeweight",
        'if [ "$1" = "run" ] && [ "$2" = "start" ]; then\n'
        f'  echo \'{{"run_id": "{RUN_ID}", "status": "queued"}}\'\n'
        f"  exit {start_exit}\n"
        "fi\n"
        'if [ "$1" = "run" ] && [ "$2" = "wait" ]; then\n'
        '  echo "followed $3"\n'
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
    )


def test_every_kind_has_an_executor_and_nothing_else_does() -> None:
    assert set(EXECUTORS) == set(JOB_KINDS)


# --- freeweight_suite_run -------------------------------------------------------------------------


@pytest.mark.parametrize("allow", [False, True])
def test_a_suite_run_is_launched_under_the_memory_cap_with_freewights_own_flags(
    tmp_path: Path, database: Database, allow: bool
) -> None:
    wrapper = _systemd_run(tmp_path)
    freeweight = _freeweight(tmp_path)
    settings = settings_for(
        tmp_path,
        f'[apps.freeweight]\nexecutable = "{freeweight}"\n'
        '[host]\nmemory_high = "20G"\nmemory_max = "22G"\n',
    )
    services = replace(
        services_for(), which=lambda name: str(wrapper) if name == "systemd-run" else None
    )
    outcome, text, _job = run_kind(
        database,
        settings,
        services,
        "freeweight_suite_run",
        {
            "model": "ollama/qwen3:8b",
            "suite": "native.performance",
            "allow_prompt_override": allow,
            "label": "q8 baseline" if allow else None,
        },
    )
    assert outcome == Outcome("completed")
    argv = (tmp_path / "systemd-run.argv").read_text().splitlines()
    # Row WP3: the Runs page's label reaches `run start --label` as one argument, and only when set.
    assert ("--label" in argv) is allow
    if allow:
        assert argv[argv.index("--label") + 1] == "q8 baseline"
    assert argv[:10] == [
        "--user",
        "--scope",
        "--quiet",
        f"--unit={SUITE_RUN_SCOPE_PREFIX}{_job.id}",
        "-p",
        "MemoryHigh=20G",
        "-p",
        "MemoryMax=22G",
        "-p",
        "MemorySwapMax=0",
    ]
    assert argv[10:15] == [str(freeweight.resolve()), "run", "start", "--model", "ollama/qwen3:8b"]
    assert ("--allow-prompt-override" in argv) is allow
    assert RUN_ID in text


def test_a_suite_run_carries_the_adapter_into_the_childs_argv(
    tmp_path: Path, database: Database
) -> None:
    """Row WPF2: the adapter is one more argument to the same capped command.

    Asserted on the child's own argv, not on the form: H6's lesson is that an adapter stored and
    never sent measures the bare base and files the numbers under the adapter's name.
    """
    wrapper = _systemd_run(tmp_path)
    freeweight = _freeweight(tmp_path)
    settings = settings_for(tmp_path, f'[apps.freeweight]\nexecutable = "{freeweight}"\n')
    services = replace(
        services_for(), which=lambda name: str(wrapper) if name == "systemd-run" else None
    )

    outcome, _text, _job = run_kind(
        database,
        settings,
        services,
        "freeweight_suite_run",
        {"model": "ollama/qwen3:8b", "suite": "native.performance", "adapter": "terse"},
    )

    assert outcome == Outcome("completed")
    argv = (tmp_path / "systemd-run.argv").read_text().splitlines()
    assert argv[argv.index("--adapter") + 1] == "terse"


def test_a_suite_run_with_no_adapter_sends_no_adapter_flag(
    tmp_path: Path, database: Database
) -> None:
    """The bare base is still the default, and says nothing rather than saying "none"."""
    wrapper = _systemd_run(tmp_path)
    freeweight = _freeweight(tmp_path)
    settings = settings_for(tmp_path, f'[apps.freeweight]\nexecutable = "{freeweight}"\n')
    services = replace(
        services_for(), which=lambda name: str(wrapper) if name == "systemd-run" else None
    )

    run_kind(
        database,
        settings,
        services,
        "freeweight_suite_run",
        {"model": "ollama/qwen3:8b", "suite": "native.performance"},
    )

    assert "--adapter" not in (tmp_path / "systemd-run.argv").read_text().splitlines()


def test_a_suite_run_another_process_holds_is_followed_to_its_end(
    tmp_path: Path, database: Database
) -> None:
    wrapper = _systemd_run(tmp_path)
    freeweight = _freeweight(tmp_path, start_exit=7)
    settings = settings_for(tmp_path, f'[apps.freeweight]\nexecutable = "{freeweight}"\n')
    services = replace(
        services_for(), which=lambda name: str(wrapper) if name == "systemd-run" else None
    )
    outcome, text, _job = run_kind(
        database,
        settings,
        services,
        "freeweight_suite_run",
        {"model": "ollama/qwen3:8b", "suite": "native.performance"},
    )
    assert outcome == Outcome("completed")
    assert f"followed {RUN_ID}" in text


def test_a_suite_run_is_never_started_uncapped(tmp_path: Path, database: Database) -> None:
    freeweight = _freeweight(tmp_path)
    settings = settings_for(tmp_path, f'[apps.freeweight]\nexecutable = "{freeweight}"\n')
    outcome, _text, _job = run_kind(
        database,
        settings,
        replace(services_for(), which=lambda _name: None),
        "freeweight_suite_run",
        {"model": "ollama/qwen3:8b", "suite": "native.performance"},
    )
    assert outcome.state == "failed"
    assert "ADR-0119" in (outcome.error or "")
    assert not (tmp_path / "systemd-run.argv").exists()


def _previous_run_finished(database: Database, *, seconds_ago: float) -> None:
    job = enqueue(
        database,
        kind="freeweight_suite_run",
        params={"model": "ollama/qwen3:8b", "suite": "native.echo"},
        now=T0,
    )
    claim_next(database, now=T0, lease_seconds=60)
    finish(
        database,
        job.id,
        state="completed",
        now=T0 - timedelta(seconds=seconds_ago),
        output=None,
        error=None,
    )


def test_a_suite_run_whose_cooldown_has_passed_starts_at_once(
    tmp_path: Path, database: Database
) -> None:
    wrapper = _systemd_run(tmp_path)
    freeweight = _freeweight(tmp_path)
    settings = settings_for(tmp_path, f'[apps.freeweight]\nexecutable = "{freeweight}"\n')
    services = replace(
        services_for(), which=lambda name: str(wrapper) if name == "systemd-run" else None
    )
    _previous_run_finished(database, seconds_ago=60)

    outcome, text, _job = run_kind(
        database,
        settings,
        services,
        "freeweight_suite_run",
        {"model": "ollama/qwen3:8b", "suite": "native.performance", "cooldown_seconds": 30},
    )

    assert outcome == Outcome("completed")
    assert "Cooling down" not in text


def test_a_suite_run_waits_out_its_cooldown_and_a_cancel_ends_the_wait(
    tmp_path: Path, database: Database
) -> None:
    """The wait is before anything launches, so a cancel in it starts no run at all."""
    wrapper = _systemd_run(tmp_path)
    freeweight = _freeweight(tmp_path)
    settings = settings_for(tmp_path, f'[apps.freeweight]\nexecutable = "{freeweight}"\n')
    services = replace(
        services_for(), which=lambda name: str(wrapper) if name == "systemd-run" else None
    )
    _previous_run_finished(database, seconds_ago=10)
    job = enqueue(
        database,
        kind="freeweight_suite_run",
        params={"model": "ollama/qwen3:8b", "suite": "native.performance", "cooldown_seconds": 30},
        now=T0,
    )
    claimed = claim_next(database, now=T0, lease_seconds=60)
    assert claimed is not None
    assert claimed.id == job.id
    output = OutputBuffer(1_000_000)
    context = JobContext(
        job=claimed,
        settings=settings,
        database=database,
        services=services,
        output=output,
        cancelled=lambda: True,
        now=lambda: T0,
    )

    outcome = EXECUTORS["freeweight_suite_run"](context)

    assert outcome == Outcome("cancelled", "the run was cancelled during its cooldown")
    assert "Cooling down 20 s" in output.text()
    assert not (tmp_path / "systemd-run.argv").exists()


# --- backup, model_refresh, docs_index ------------------------------------------------------------


def test_backup_calls_each_applications_own_verb_and_backs_weightroom_up_in_process(
    tmp_path: Path, database: Database
) -> None:
    loadcoach, _config, _document = fake_application(tmp_path, "loadcoach")
    settings = settings_for(tmp_path, f'[apps.loadcoach]\nexecutable = "{loadcoach}"\n')
    outcome, text, _job = run_kind(
        database, settings, services_for(), "backup", {"apps": ["loadcoach", "weightroom"]}
    )
    assert outcome == Outcome("completed")
    assert "loadcoach: backed up" in text
    assert "weightroom: backed up" in text
    assert list((tmp_path / "backups").glob("manual-*.sqlite3"))


def test_a_failed_backup_names_the_application(tmp_path: Path, database: Database) -> None:
    broken = _script(tmp_path / "ideapress", 'echo "ideapress: disk full" >&2\nexit 1\n')
    settings = settings_for(tmp_path, f'[apps.ideapress]\nexecutable = "{broken}"\n')
    outcome, text, _job = run_kind(
        database, settings, services_for(), "backup", {"apps": ["ideapress"]}
    )
    assert outcome == Outcome("failed", "no backup of ideapress")
    assert "disk full" in text


def test_model_refresh_runs_each_refresh_then_the_catalog_join(
    tmp_path: Path, database: Database
) -> None:
    answer = 'if [ "$1" = "models" ]; then echo \'{"added": 1, "total": 3}\'; fi\nexit 0\n'
    freeweight = _script(tmp_path / "freeweight", answer)
    loadcoach = _script(tmp_path / "loadcoach", answer)
    settings = settings_for(
        tmp_path,
        f'[apps.freeweight]\nexecutable = "{freeweight}"\n'
        f'[apps.loadcoach]\nexecutable = "{loadcoach}"\n',
    )
    outcome, text, _job = run_kind(database, settings, services_for(), "model_refresh", {})
    assert outcome == Outcome("completed")
    assert 'freeweight: {"added": 1, "total": 3}' in text
    assert 'loadcoach: {"added": 1, "total": 3}' in text
    assert "catalog: 0 model(s)" in text


def test_docs_index_rebuilds_from_the_configured_root(tmp_path: Path, database: Database) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "README.md").write_text("# The suite\n\nHello.\n", encoding="utf-8")
    settings = settings_for(tmp_path, f'[docs]\nroot = "{root}"\n')
    outcome, text, _job = run_kind(database, settings, services_for(), "docs_index", {})
    assert outcome == Outcome("completed")
    assert "indexed 1 document(s)" in text


# --- retention_trim -------------------------------------------------------------------------------


def _aged(path: Path, days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"backup")
    stamp = (T0 - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))


def test_retention_expires_old_guarded_write_backups_and_leaves_freeweight_alone(
    tmp_path: Path, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEIGHTROOM_DATA_DIR", str(tmp_path / "data"))
    directory = tmp_path / "data" / "backups" / "loadcoach"
    old = directory / "20260501T000000Z-guarded-write.sqlite3"
    fresh = directory / "20260909T000000Z-guarded-write.sqlite3"
    _aged(old, 120)
    _aged(fresh, 1)
    outcome, text, _job = run_kind(
        database, settings_for(tmp_path), services_for(), "retention_trim", {}
    )
    assert outcome == Outcome("completed")
    assert not old.exists()
    assert fresh.exists()
    assert "1 guarded-write backup(s) older than 90 days removed" in text
    assert "freeweight: not trimmed" in text


@respx.mock
def test_retention_deletes_old_freeweight_results_through_freeweights_own_preview_and_token(
    tmp_path: Path, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEIGHTROOM_DATA_DIR", str(tmp_path / "data"))
    preview = respx.post("http://127.0.0.1:8765/api/v1/database/delete-preview").mock(
        return_value=httpx.Response(200, json={"run_count": 2, "token": "tok-1"})
    )
    deletion = respx.delete("http://127.0.0.1:8765/api/v1/database/results").mock(
        return_value=httpx.Response(200, json={"deleted_runs": 2})
    )
    outcome, text, _job = run_kind(
        database,
        settings_for(tmp_path),
        services_for(),
        "retention_trim",
        {"freeweight_older_than_days": 30},
    )
    assert outcome == Outcome("completed")
    cutoff = (T0 - timedelta(days=30)).isoformat()
    assert preview.calls.last.request.content == (
        b'{"scope":"before","selector":"' + cutoff.encode() + b'"}'
    )
    assert b'"token":"tok-1"' in deletion.calls.last.request.content
    assert f"2 run(s) created before {cutoff} deleted by FreeWeight" in text


# --- freeweight_goal_calibrate (row WP4) ----------------------------------------------------------


def _calibrating_freeweight(tmp_path: Path, *, exit_code: int = 0) -> Path:
    return _script(
        tmp_path / "freeweight",
        'if [ "$1" = "goals" ] && [ "$2" = "calibrate" ]; then\n'
        '  echo \'{"event": "calibration.started", "holdout": 2}\'\n'
        '  echo \'{"event": "calibration.sample_judged", "sample": 1, "of": 2}\'\n'
        '  echo \'{"event": "calibration.sample_judged", "sample": 2, "of": 2}\'\n'
        '  echo \'{"event": "calibration.completed", "state": "calibrated"}\'\n'
        f"  exit {exit_code}\n"
        "fi\n"
        "exit 2\n",
    )


def test_a_calibration_runs_its_jury_under_the_memory_cap_and_prints_its_progress(
    tmp_path: Path, database: Database
) -> None:
    wrapper = _systemd_run(tmp_path)
    freeweight = _calibrating_freeweight(tmp_path)
    settings = settings_for(
        tmp_path,
        f'[apps.freeweight]\nexecutable = "{freeweight}"\n'
        '[host]\nmemory_high = "20G"\nmemory_max = "22G"\n',
    )
    services = replace(
        services_for(), which=lambda name: str(wrapper) if name == "systemd-run" else None
    )
    outcome, text, job = run_kind(
        database, settings, services, "freeweight_goal_calibrate",
        {"goal": "wp4_voice", "graded_by": "jordan"},
    )  # fmt: skip
    assert outcome == Outcome("completed")
    argv = (tmp_path / "systemd-run.argv").read_text().splitlines()
    assert argv[3] == f"--unit={SUITE_RUN_SCOPE_PREFIX}{job.id}"
    assert argv[4:10] == ["-p", "MemoryHigh=20G", "-p", "MemoryMax=22G", "-p", "MemorySwapMax=0"]
    assert argv[10:] == [
        str(freeweight.resolve()), "goals", "calibrate", "wp4_voice", "--progress", "--json",
        "--graded-by", "jordan",
    ]  # fmt: skip
    assert text.count("calibration.sample_judged") == 2


def test_a_calibration_is_never_started_uncapped_and_a_failure_is_named(
    tmp_path: Path, database: Database
) -> None:
    freeweight = _calibrating_freeweight(tmp_path, exit_code=5)
    settings = settings_for(tmp_path, f'[apps.freeweight]\nexecutable = "{freeweight}"\n')
    uncapped, _text, _job = run_kind(
        database, settings, replace(services_for(), which=lambda _name: None),
        "freeweight_goal_calibrate", {"goal": "wp4_voice"},
    )  # fmt: skip
    assert uncapped.state == "failed" and "ADR-0119" in (uncapped.error or "")
    wrapper = _systemd_run(tmp_path)
    services = replace(
        services_for(), which=lambda name: str(wrapper) if name == "systemd-run" else None
    )
    failed, _text, _job = run_kind(
        database, settings, services, "freeweight_goal_calibrate", {"goal": "wp4_voice"}
    )
    assert failed == Outcome("failed", "freeweight exited 5")
    argv = (tmp_path / "systemd-run.argv").read_text().splitlines()
    assert "--graded-by" not in argv

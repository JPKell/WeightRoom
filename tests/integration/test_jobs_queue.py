"""The queue in WeightRoomGym's own database: claims, leases, recovery, cancel, schedules, worker.

Development plan Phase 9's queue tests: lease expiry and requeue, the cancel states, a schedule's
catch-up after downtime in the database itself (once, never N times), and one execution audited as
one ``job.run`` row — pending while it runs, completed when it ends.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy import select

from weightroom.config import Settings, load_settings
from weightroom.domain.jobs import JobInvalidState, JobParamsInvalid
from weightroom.infrastructure.db.models import AuditLog
from weightroom.services import audit
from weightroom.services.database import Database, ensure_ready
from weightroom.services.db_reader import DatabaseUrlCache
from weightroom.services.jobs import (
    JobContext,
    JobNotFound,
    JobServices,
    JobView,
    JobWorker,
    Outcome,
    OutputBuffer,
    ScheduleView,
    attach_audit,
    claim_next,
    enqueue,
    finish,
    get_job,
    list_schedules,
    recover,
    renew_leases,
    request_cancel,
    run_streaming,
    tick_schedules,
    trim_finished_jobs,
    update_schedule,
)
from weightroom.services.processes import FakeSystemdController

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

T0 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
LEASE = 60


def settings_for(tmp_path: Path, extra: str = "") -> Settings:
    """Settings whose database is the one the ``database`` fixture opens."""
    file = tmp_path / "config.toml"
    file.write_text(
        f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/weightroom.sqlite3"\n{extra}',
        encoding="utf-8",
    )
    return load_settings(config_path=file).settings


def services_for() -> JobServices:
    """Boundaries over a fake host: no systemd, no applications, no network."""
    return JobServices(
        controller=FakeSystemdController(),
        http=httpx.Client(),
        urls=DatabaseUrlCache(),
    )


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    handle = Database.from_url(f"sqlite:///{tmp_path}/weightroom.sqlite3")
    ensure_ready(handle, auto_migrate=True)
    yield handle
    handle.close()


def _claimed(
    database: Database,
    kind: str = "backup",
    params: dict[str, object] | None = None,
    *,
    at: datetime = T0,
) -> JobView:
    job = enqueue(database, kind=kind, params=params, now=at)
    claimed = claim_next(database, now=at, lease_seconds=LEASE)
    assert claimed is not None
    assert claimed.id == job.id
    return claimed


def _schedule(database: Database, kind: str) -> ScheduleView:
    return next(one for one in list_schedules(database) if one.kind == kind)


# --- Claims and leases ----------------------------------------------------------------------------


def test_the_claim_takes_the_oldest_queued_job_once_and_counts_the_attempt(
    database: Database,
) -> None:
    first = enqueue(database, kind="docs_index", params={}, now=T0)
    second = enqueue(database, kind="backup", params={}, now=T0 + timedelta(seconds=1))
    claimed = claim_next(database, now=T0, lease_seconds=LEASE)
    assert claimed is not None
    assert (claimed.id, claimed.state, claimed.attempt) == (first.id, "running", 1)
    assert claimed.lease_expires_at == T0 + timedelta(seconds=LEASE)
    following = claim_next(database, now=T0, lease_seconds=LEASE)
    assert following is not None
    assert following.id == second.id
    assert claim_next(database, now=T0, lease_seconds=LEASE) is None


def test_claims_racing_for_one_job_take_it_exactly_once(database: Database) -> None:
    enqueue(database, kind="docs_index", params={}, now=T0)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(lambda _n: claim_next(database, now=T0, lease_seconds=LEASE), range(6))
        )
    assert len([one for one in results if one is not None]) == 1


def test_an_expired_lease_requeues_an_idempotent_job_and_fails_a_suite_run(
    database: Database,
) -> None:
    backup = _claimed(database, "backup", {})
    run = _claimed(
        database, "freeweight_suite_run", {"model": "ollama/m", "suite": "native.performance"}
    )
    for job in (backup, run):
        pending = audit.record(
            database, action="job.run", actor="job", outcome="pending", now=T0, target=job.id
        )
        attach_audit(database, job.id, pending)
    assert not recover(database, now=T0 + timedelta(seconds=30)).changed

    report = recover(database, now=T0 + timedelta(seconds=LEASE + 1))

    assert report.requeued == (backup.id,)
    assert report.failed == (run.id,)
    assert get_job(database, backup.id).state == "queued"
    lost = get_job(database, run.id)
    assert (lost.state, lost.error) == ("failed", "worker_lost")
    assert not recover(database, now=T0 + timedelta(seconds=LEASE + 2)).changed
    with database.read() as session:
        rows = session.execute(select(AuditLog).where(AuditLog.action == "job.run")).scalars()
        completed = {row.target: (row.outcome, row.message or "") for row in rows}
    assert completed[backup.id][0] == "failed"
    assert "queued again" in completed[backup.id][1]
    assert completed[run.id][0] == "failed"
    assert "worker_lost" in completed[run.id][1]
    again = claim_next(database, now=T0 + timedelta(seconds=LEASE + 3), lease_seconds=LEASE)
    assert again is not None
    assert (again.id, again.attempt) == (backup.id, 2)


def test_the_lease_keepers_renewal_keeps_a_long_job_alive(database: Database) -> None:
    job = _claimed(database)
    renewed = renew_leases(database, [job.id], now=T0 + timedelta(seconds=50), lease_seconds=LEASE)
    assert renewed == 1
    assert not recover(database, now=T0 + timedelta(seconds=LEASE + 1)).changed
    assert get_job(database, job.id).state == "running"


def test_a_worker_that_lost_its_lease_cannot_finish_the_job(database: Database) -> None:
    job = _claimed(database)
    recover(database, now=T0 + timedelta(seconds=LEASE + 1))
    with pytest.raises(JobInvalidState):
        finish(database, job.id, state="completed", now=T0, output="", error=None)


# --- Cancel ---------------------------------------------------------------------------------------


def test_cancel_is_immediate_when_queued_a_flag_when_running_and_refused_after(
    database: Database,
) -> None:
    queued = enqueue(database, kind="docs_index", params={}, now=T0)
    cancelled = request_cancel(database, queued.id, now=T0)
    assert (cancelled.state, cancelled.finished_at) == ("cancelled", T0)
    running = _claimed(database)
    flagged = request_cancel(database, running.id, now=T0)
    assert (flagged.state, flagged.cancel_requested_at) == ("running", T0)
    with pytest.raises(JobInvalidState):
        request_cancel(database, queued.id, now=T0)
    with pytest.raises(JobNotFound):
        request_cancel(database, "01NOSUCHJOB000000000000000", now=T0)


def test_a_cancelled_job_whose_worker_died_is_cancelled_by_recovery_not_requeued(
    database: Database,
) -> None:
    job = _claimed(database)
    request_cancel(database, job.id, now=T0)
    report = recover(database, now=T0 + timedelta(seconds=LEASE + 1))
    assert report.cancelled == (job.id,)
    assert get_job(database, job.id).state == "cancelled"


def test_trim_removes_finished_jobs_past_ninety_days_only(database: Database) -> None:
    old = _claimed(database, at=T0 - timedelta(days=100))
    finish(
        database, old.id, state="completed", now=T0 - timedelta(days=95), output=None, error=None
    )
    recent = _claimed(database, at=T0 - timedelta(days=2))
    finish(database, recent.id, state="failed", now=T0 - timedelta(days=1), output=None, error="x")
    waiting = enqueue(database, kind="docs_index", params={}, now=T0 - timedelta(days=200))
    assert trim_finished_jobs(database, now=T0) == 1
    with pytest.raises(JobNotFound):
        get_job(database, old.id)
    assert get_job(database, recent.id).state == "failed"
    assert get_job(database, waiting.id).state == "queued"


# --- Schedules ------------------------------------------------------------------------------------


def test_five_schedules_are_seeded_disabled_and_the_suite_run_needs_a_model(
    database: Database,
) -> None:
    schedules = list_schedules(database)
    assert sorted(one.kind for one in schedules) == [
        "backup",
        "docs_index",
        "freeweight_suite_run",
        "model_refresh",
        "retention_trim",
    ]
    assert not any(one.enabled for one in schedules)
    assert "model" in (_schedule(database, "freeweight_suite_run").problem or "")


def test_a_schedule_missed_during_downtime_enqueues_once_in_the_database(
    database: Database,
) -> None:
    schedule = _schedule(database, "docs_index")
    enabled = update_schedule(
        database,
        schedule.id,
        now=datetime(2026, 9, 7, 1, 0, tzinfo=UTC),
        cron="0 2 * * *",
        enabled=True,
    )
    assert enabled.next_run_at == datetime(2026, 9, 7, 2, 0, tzinfo=UTC)
    back = datetime(2026, 9, 10, 9, 30, tzinfo=UTC)  # three nights later

    enqueued = tick_schedules(database, now=back)

    assert len(enqueued) == 1
    assert tick_schedules(database, now=back + timedelta(seconds=1)) == []
    after = _schedule(database, "docs_index")
    assert after.next_run_at == datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    assert (after.last_run_at, after.last_job_id) == (back, enqueued[0])
    job = get_job(database, enqueued[0])
    assert (job.kind, job.schedule_id, job.state) == ("docs_index", schedule.id, "queued")


def test_a_schedule_is_not_enabled_with_parameters_its_kind_refuses(database: Database) -> None:
    schedule = _schedule(database, "freeweight_suite_run")
    with pytest.raises(JobParamsInvalid):
        update_schedule(database, schedule.id, now=T0, enabled=True)
    fixed = update_schedule(
        database,
        schedule.id,
        now=T0,
        enabled=True,
        params={"model": "ollama/qwen3:8b", "suite": "native.performance"},
    )
    assert fixed.enabled
    assert fixed.problem is None
    assert fixed.next_run_at == datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    assert update_schedule(database, schedule.id, now=T0, enabled=False).next_run_at is None
    assert tick_schedules(database, now=T0 + timedelta(days=30)) == []


# --- The worker -----------------------------------------------------------------------------------


def test_the_worker_executes_one_job_and_audits_it_pending_then_ok(
    database: Database, tmp_path: Path
) -> None:
    def executor(context: JobContext) -> Outcome:
        context.output.line("indexed 3 documents")
        return Outcome("completed")

    worker = JobWorker(
        database,
        settings_for(tmp_path),
        services_for(),
        executors={"docs_index": executor},
        clock=lambda: T0,
    )
    job = enqueue(database, kind="docs_index", params={}, now=T0)

    assert worker.run_once() == job.id

    done = get_job(database, job.id)
    assert (done.state, done.output, done.error) == ("completed", "indexed 3 documents\n", None)
    with database.read() as session:
        rows = [
            (row.id, row.actor, row.outcome, row.target)
            for row in session.execute(
                select(AuditLog).where(AuditLog.action == "job.run")
            ).scalars()
        ]
    assert [row[1:] for row in rows] == [("job", "ok", job.id)]
    assert done.audit_id == rows[0][0]
    assert worker.run_once() is None
    assert worker.held == frozenset()


def test_a_crashing_executor_is_a_failed_job_and_the_worker_goes_on(
    database: Database, tmp_path: Path
) -> None:
    def executor(context: JobContext) -> Outcome:
        message = "boom"
        raise RuntimeError(message)

    worker = JobWorker(
        database,
        settings_for(tmp_path),
        services_for(),
        executors={"docs_index": executor},
        clock=lambda: T0,
    )
    job = enqueue(database, kind="docs_index", params={}, now=T0)
    worker.run_once()
    failed = get_job(database, job.id)
    assert failed.state == "failed"
    assert "boom" in (failed.error or "")


def test_a_cancel_reaches_the_executor_of_a_running_job(database: Database, tmp_path: Path) -> None:
    def executor(context: JobContext) -> Outcome:
        request_cancel(context.database, context.job.id, now=T0)
        deadline = time.monotonic() + 5.0
        while not context.cancelled():
            assert time.monotonic() < deadline
            time.sleep(0.05)
        return Outcome("cancelled", "stopped on the cancel")

    worker = JobWorker(
        database,
        settings_for(tmp_path),
        services_for(),
        executors={"docs_index": executor},
        clock=lambda: T0,
    )
    job = enqueue(database, kind="docs_index", params={}, now=T0)
    worker.run_once()
    assert get_job(database, job.id).state == "cancelled"


def test_started_the_worker_recovers_runs_queued_work_on_its_threads_and_stops(
    database: Database, tmp_path: Path
) -> None:
    ran = threading.Event()

    def executor(context: JobContext) -> Outcome:
        ran.set()
        return Outcome("completed")

    stale = _claimed(database, "docs_index", {}, at=datetime.now(UTC) - timedelta(hours=1))
    worker = JobWorker(
        database,
        settings_for(tmp_path, "[jobs]\npoll_interval_ms = 100\nlease_seconds = 6\n"),
        services_for(),
        executors={"docs_index": executor},
    )
    worker.start()
    try:
        assert ran.wait(10.0)
        deadline = time.monotonic() + 10.0
        while get_job(database, stale.id).state != "completed":
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        worker.stop()


# --- Streaming a child ----------------------------------------------------------------------------


def test_output_is_flushed_as_it_grows_and_only_the_tail_is_kept() -> None:
    flushed: list[str] = []
    ticks = iter([0.0, 0.2, 1.5, 1.6, 3.0])
    buffer = OutputBuffer(
        1024, flush=flushed.append, interval_seconds=1.0, clock=lambda: next(ticks)
    )
    for _n in range(5):
        buffer.write("x" * 1000 + "\n")
    assert len(flushed) == 3
    assert len(buffer.text().encode()) <= 1024
    assert buffer.text().endswith("x\n")


def test_a_streamed_child_is_captured_and_a_cancel_stops_it() -> None:
    output = OutputBuffer(10_000)
    script = "import time; print('started', flush=True); time.sleep(60)"
    began = time.monotonic()
    result = run_streaming(
        [sys.executable, "-c", script],
        {"PATH": os.environ.get("PATH", "")},
        output=output,
        cancelled=lambda: "started" in output.text(),
        timeout_seconds=60.0,
        poll_seconds=0.05,
        grace_seconds=5.0,
    )
    assert result.cancelled
    assert not result.ok
    assert time.monotonic() - began < 15.0
    assert "started" in output.text()


def test_a_line_a_child_prints_before_going_quiet_is_flushed_while_it_still_runs() -> None:
    # `freeweight run start --json` prints the run id and is silent until the run ends; the Runs
    # page follows that id from the row, so it cannot wait for the next line or the exit.
    flushed: list[str] = []
    output = OutputBuffer(10_000, flush=flushed.append, interval_seconds=1.0)
    script = "import time; print('$ start', flush=True); print('run R', flush=True); time.sleep(60)"
    result = run_streaming(
        [sys.executable, "-c", script],
        {"PATH": os.environ.get("PATH", "")},
        output=output,
        cancelled=lambda: any("run R" in one for one in flushed),
        timeout_seconds=10.0,
        poll_seconds=0.05,
        grace_seconds=5.0,
    )
    assert result.cancelled
    assert not result.timed_out


def test_a_child_that_outlives_its_timeout_is_stopped() -> None:
    result = run_streaming(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        {},
        output=OutputBuffer(1_000),
        cancelled=lambda: False,
        timeout_seconds=0.3,
        poll_seconds=0.05,
        grace_seconds=2.0,
    )
    assert result.timed_out
    assert not result.ok


def test_a_child_that_cannot_start_is_a_result_not_an_exception(tmp_path: Path) -> None:
    output = OutputBuffer(1_000)
    result = run_streaming(
        [str(tmp_path / "absent")],
        {},
        output=output,
        cancelled=lambda: False,
        timeout_seconds=1.0,
    )
    assert result.returncode == -1
    assert "could not be started" in output.text()

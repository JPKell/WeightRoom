"""weightroom.services.jobs — the queue, its worker, its lease keeper, its schedules (spec §7.10).

ADR-0010's database-backed queue in WeightRoomGym's own database, with ADR-0029's lessons applied
(the four are answered one by one in ``domain/jobs.py``'s docstring). How each moving part works:

**The claim is a compare-and-set.** The oldest queued job's id is read, then one ``UPDATE … WHERE
id = :id AND state = 'queued'`` moves it to ``running`` with its lease; a claim that changes no row
lost a race and looks again. Identical on SQLite and PostgreSQL — a row lock plus the re-evaluated
``WHERE`` on one, the single writer on the other — so no dialect-specific ``SKIP LOCKED`` is needed
for a queue with one worker per process.

**The lease keeper is its own thread.** It renews every job this process holds every
``lease_seconds / 3``; the worker thread spends hours inside a benchmark run and never renews
anything itself (ADR-0029 §4). A process that dies stops renewing, and its jobs' leases expire.

**Recovery runs at startup and on every worker tick.** An expired lease on an idempotent kind puts
the job back in the queue; on any other kind it fails as ``worker_lost``; a job whose cancel was
requested before its worker vanished is cancelled. Running it twice changes nothing.

**Schedules fire from the same tick.** Each enabled schedule is decided by
:func:`~weightroom.domain.jobs.schedule_tick` and its ``next_run_at`` is moved by a compare-and-set
of its own, so two ticks — or two processes — enqueue a due slot once.

**Every execution is one ``job.run`` audit row**, written ``pending`` when the job starts and
completed when it ends (spec §11 contract 2), with actor ``job``. Enqueueing, cancelling and editing
a schedule are the person's actions and are audited where the person acts (the routes, the CLI).

What each kind *does* lives in ``services/job_kinds.py``; this module is the queue.
"""

from __future__ import annotations

import json
import logging
import signal
import subprocess  # noqa: S404 — explicit argv, an allowlisted environment, never a shell
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, cast

from baseaicore import SuiteError, new_id
from sqlalchemy import delete, or_, select, update

from weightroom.domain.jobs import (
    TERMINAL_STATES,
    WORKER_LOST,
    CronInvalid,
    JobParamsInvalid,
    cancel_action,
    cap_output,
    heartbeat_seconds,
    lease_until,
    next_fire,
    parse_cron,
    recovery_action,
    require_transition,
    schedule_tick,
    validate_params,
)
from weightroom.infrastructure.db.models import Job, JobSchedule
from weightroom.services import audit
from weightroom.services.processes import OUTPUT_CAP_BYTES

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    import httpx
    from sqlalchemy import CursorResult

    from weightroom.config import Settings
    from weightroom.services.database import Database
    from weightroom.services.db_reader import DatabaseUrlCache
    from weightroom.services.processes import Runner, SystemdController

__all__ = [
    "FINISHED_RETENTION_DAYS",
    "JobContext",
    "JobNotFound",
    "JobServices",
    "JobView",
    "JobWorker",
    "Outcome",
    "OutputBuffer",
    "RecoveryReport",
    "ScheduleView",
    "StreamResult",
    "claim_next",
    "enqueue",
    "finish",
    "get_job",
    "get_schedule",
    "list_jobs",
    "list_schedules",
    "recover",
    "renew_leases",
    "request_cancel",
    "run_streaming",
    "tick_schedules",
    "trim_finished_jobs",
    "update_schedule",
]

logger = logging.getLogger(__name__)

FINISHED_RETENTION_DAYS: Final = 90
"""Data model §3: a finished job's row goes after 90 days; its audit row stays for ever."""

_CLAIM_ATTEMPTS: Final = 3
_CANCEL_PROBE_SECONDS: Final = 1.0
_OUTPUT_FLUSH_SECONDS: Final = 1.0
_STOP_GRACE_SECONDS: Final = 30.0
_STREAM_POLL_SECONDS: Final = 0.5


class JobNotFound(SuiteError):
    """A job or schedule id that is not in the database."""

    code: ClassVar[str] = "JOB_NOT_FOUND"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True, slots=True)
class JobView:
    """One job as the pages, the API and the CLI show it (api.md §7)."""

    id: str
    kind: str
    params: dict[str, Any]
    state: str
    schedule_id: str | None
    attempt: int
    lease_expires_at: datetime | None
    cancel_requested_at: datetime | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    output: str | None
    error: str | None
    audit_id: str | None

    @classmethod
    def of(cls, row: Job) -> JobView:
        """Read a row."""
        return cls(
            id=row.id,
            kind=row.kind,
            params=dict(cast("Mapping[str, Any]", row.params or {})),
            state=row.state,
            schedule_id=row.schedule_id,
            attempt=row.attempt,
            lease_expires_at=row.lease_expires_at,
            cancel_requested_at=row.cancel_requested_at,
            queued_at=row.queued_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            output=row.output,
            error=row.error,
            audit_id=row.audit_id,
        )

    @property
    def finished(self) -> bool:
        """Whether the job has reached a terminal state."""
        return self.state in TERMINAL_STATES

    def as_json(self) -> dict[str, Any]:
        """The api.md §7 shape."""
        return {
            "id": self.id,
            "kind": self.kind,
            "params": self.params,
            "state": self.state,
            "schedule_id": self.schedule_id,
            "attempt": self.attempt,
            "lease_expires_at": _iso(self.lease_expires_at),
            "cancel_requested_at": _iso(self.cancel_requested_at),
            "queued_at": _iso(self.queued_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "output": self.output,
            "error": self.error,
            "audit_id": self.audit_id,
        }


@dataclass(frozen=True, slots=True)
class ScheduleView:
    """One schedule, and why it cannot be enabled when it cannot."""

    id: str
    kind: str
    params: dict[str, Any]
    cron: str
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_job_id: str | None
    problem: str | None

    @classmethod
    def of(cls, row: JobSchedule) -> ScheduleView:
        """Read a row, and check its parameters as enabling it would."""
        params = dict(cast("Mapping[str, Any]", row.params or {}))
        try:
            validate_params(row.kind, params)
            problem = None
        except JobParamsInvalid as exc:
            problem = exc.message
        return cls(
            id=row.id,
            kind=row.kind,
            params=params,
            cron=row.cron,
            enabled=row.enabled,
            next_run_at=row.next_run_at,
            last_run_at=row.last_run_at,
            last_job_id=row.last_job_id,
            problem=problem,
        )

    def as_json(self) -> dict[str, Any]:
        """The api.md §7 shape."""
        return {
            "id": self.id,
            "kind": self.kind,
            "params": self.params,
            "cron": self.cron,
            "timezone": "UTC",
            "enabled": self.enabled,
            "next_run_at": _iso(self.next_run_at),
            "last_run_at": _iso(self.last_run_at),
            "last_job_id": self.last_job_id,
            "problem": self.problem,
        }


def _rowcount(result: object) -> int:
    return cast("CursorResult[Any]", result).rowcount or 0


# --- The queue ------------------------------------------------------------------------------------


def enqueue(
    database: Database,
    *,
    kind: str,
    params: Mapping[str, Any] | None,
    now: datetime,
    schedule_id: str | None = None,
) -> JobView:
    """Queue one job.

    Args:
        database: WeightRoomGym's own database.
        kind: One of :data:`~weightroom.domain.jobs.JOB_KINDS`.
        params: The kind's parameters; defaults are filled in.
        now: The instant it was queued.
        schedule_id: The schedule it came from, when it did.

    Returns:
        The queued job.

    Raises:
        JobParamsInvalid: An unknown kind or parameters its kind refuses.
    """
    validated = validate_params(kind, params)
    with database.write() as session:
        row = Job(
            id=new_id(),
            kind=kind,
            params=validated,
            state="queued",
            schedule_id=schedule_id,
            attempt=0,
            queued_at=now,
        )
        session.add(row)
        session.flush()
        return JobView.of(row)


def get_job(database: Database, job_id: str) -> JobView:
    """One job.

    Raises:
        JobNotFound: No such job.
    """
    with database.read() as session:
        row = session.get(Job, job_id)
        if row is None:
            raise JobNotFound(f"No job {job_id!r}.", details={"job_id": job_id})
        return JobView.of(row)


def list_jobs(
    database: Database,
    *,
    limit: int,
    state: str | None = None,
    kind: str | None = None,
    before_id: str | None = None,
) -> tuple[list[JobView], bool]:
    """Jobs newest first (ULIDs order by time), and whether more follow."""
    statement = select(Job).order_by(Job.id.desc()).limit(limit + 1)
    if state is not None:
        statement = statement.where(Job.state == state)
    if kind is not None:
        statement = statement.where(Job.kind == kind)
    if before_id is not None:
        statement = statement.where(Job.id < before_id)
    with database.read() as session:
        rows = session.execute(statement).scalars().all()
        views = [JobView.of(row) for row in rows[:limit]]
    return views, len(rows) > limit


def request_cancel(database: Database, job_id: str, *, now: datetime) -> JobView:
    """Cancel a queued job outright, or flag a running one for its executor.

    Raises:
        JobNotFound: No such job.
        JobInvalidState: The job has already finished.
    """
    with database.write() as session:
        row = session.get(Job, job_id)
        if row is None:
            raise JobNotFound(f"No job {job_id!r}.", details={"job_id": job_id})
        if cancel_action(row.state) == "cancel":
            require_transition(row.state, "cancelled")
            row.state = "cancelled"
            row.finished_at = now
            row.error = "cancelled before it started"
        elif row.cancel_requested_at is None:
            row.cancel_requested_at = now
        return JobView.of(row)


def cancel_requested(database: Database, job_id: str) -> bool:
    """Whether a cancel has been asked of ``job_id`` — what a running executor polls."""
    with database.read() as session:
        requested = session.execute(
            select(Job.cancel_requested_at).where(Job.id == job_id)
        ).scalar()
    return requested is not None


def claim_next(database: Database, *, now: datetime, lease_seconds: float) -> JobView | None:
    """Claim the oldest queued job under a lease; ``None`` when nothing is queued.

    The claim increments ``attempt`` — the only writer of it (``domain/jobs.py``, ADR-0029 §2).
    """
    for _attempt in range(_CLAIM_ATTEMPTS):
        with database.read() as session:
            candidate = session.execute(
                select(Job.id).where(Job.state == "queued").order_by(Job.queued_at, Job.id).limit(1)
            ).scalar()
        if candidate is None:
            return None
        with database.write() as session:
            moved = session.execute(
                update(Job)
                .where(Job.id == candidate, Job.state == "queued")
                .values(
                    state="running",
                    attempt=Job.attempt + 1,
                    lease_expires_at=lease_until(now, lease_seconds),
                    started_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if _rowcount(moved) == 1:
                row = session.get(Job, candidate, populate_existing=True)
                if row is not None:
                    return JobView.of(row)
    return None


def renew_leases(
    database: Database, job_ids: Sequence[str], *, now: datetime, lease_seconds: float
) -> int:
    """Extend the lease of every still-running job in ``job_ids``; how many were renewed."""
    if not job_ids:
        return 0
    with database.write() as session:
        return _rowcount(
            session.execute(
                update(Job)
                .where(Job.id.in_(list(job_ids)), Job.state == "running")
                .values(lease_expires_at=lease_until(now, lease_seconds))
                .execution_options(synchronize_session=False)
            )
        )


def set_output(database: Database, job_id: str, output: str) -> None:
    """Store a running job's captured output so far — the job page's live view reads it."""
    with database.write() as session:
        session.execute(
            update(Job)
            .where(Job.id == job_id, Job.state == "running")
            .values(output=output)
            .execution_options(synchronize_session=False)
        )


def attach_audit(database: Database, job_id: str, audit_id: str) -> None:
    """Record which ``job.run`` row this execution wrote."""
    with database.write() as session:
        session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(audit_id=audit_id)
            .execution_options(synchronize_session=False)
        )


def finish(
    database: Database,
    job_id: str,
    *,
    state: str,
    now: datetime,
    output: str | None,
    error: str | None,
) -> JobView:
    """Move a running job to ``completed``, ``failed`` or ``cancelled``.

    Raises:
        JobNotFound: No such job.
        JobInvalidState: The job is no longer running — its lease expired and recovery moved it,
            which is the one way a worker loses a job it was executing.
    """
    with database.write() as session:
        row = session.get(Job, job_id)
        if row is None:
            raise JobNotFound(f"No job {job_id!r}.", details={"job_id": job_id})
        require_transition(row.state, state)
        row.state = state
        row.finished_at = now
        row.lease_expires_at = None
        row.output = output
        row.error = error
        return JobView.of(row)


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """What a recovery pass did, by job id."""

    requeued: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    cancelled: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Whether the pass moved anything."""
        return bool(self.requeued or self.failed or self.cancelled)


def recover(database: Database, *, now: datetime) -> RecoveryReport:
    """Release every expired lease (queue-and-scheduling §10, row W9's shape).

    A job whose cancel was requested is cancelled; an idempotent kind is queued again; any other
    fails as ``worker_lost``. Each moved job's pending ``job.run`` row is completed ``failed`` with
    the reason. Idempotent: a second pass finds nothing expired.
    """
    expired = or_(Job.lease_expires_at.is_(None), Job.lease_expires_at <= now)
    with database.read() as session:
        stale = (
            session.execute(select(Job.id).where(Job.state == "running", expired)).scalars().all()
        )
    if not stale:
        return RecoveryReport()
    requeued: list[str] = []
    failed: list[str] = []
    cancelled: list[str] = []
    audits: list[tuple[str, str]] = []
    with database.write() as session:
        rows = session.execute(
            select(Job).where(Job.id.in_(stale), Job.state == "running", expired)
        ).scalars()
        for row in rows:
            action = recovery_action(kind=row.kind, lease_expires_at=row.lease_expires_at, now=now)
            if action is None:  # pragma: no cover — the query already selected expired leases
                continue
            row.lease_expires_at = None
            if row.cancel_requested_at is not None:
                reason = "cancelled; its worker was lost before it stopped"
                row.state, row.finished_at, row.error = "cancelled", now, reason
                cancelled.append(row.id)
            elif action == "requeue":
                reason = "the lease expired with the job unfinished; it was queued again"
                row.state = "queued"
                requeued.append(row.id)
            else:
                reason = f"{WORKER_LOST}: the lease expired with the job unfinished"
                row.state, row.finished_at, row.error = "failed", now, WORKER_LOST
                failed.append(row.id)
            if row.audit_id is not None:
                audits.append((row.audit_id, reason))
    for audit_id, reason in audits:
        try:
            audit.complete(database, audit_id, outcome="failed", message=reason)
        except ValueError:
            logger.info("jobs.recovery_audit_already_complete", extra={"audit_id": audit_id})
    report = RecoveryReport(tuple(requeued), tuple(failed), tuple(cancelled))
    logger.warning(
        "jobs.recovered",
        extra={"requeued": report.requeued, "failed": report.failed, "cancelled": report.cancelled},
    )
    return report


def trim_finished_jobs(
    database: Database, *, now: datetime, days: int = FINISHED_RETENTION_DAYS
) -> int:
    """Delete finished jobs older than ``days``; their audit rows stay (data model §3)."""
    with database.write() as session:
        return _rowcount(
            session.execute(
                delete(Job)
                .where(Job.state.in_(sorted(TERMINAL_STATES)))
                .where(Job.finished_at < now - timedelta(days=days))
                .execution_options(synchronize_session=False)
            )
        )


# --- Schedules ------------------------------------------------------------------------------------


def list_schedules(database: Database) -> list[ScheduleView]:
    """Every schedule, in kind order."""
    with database.read() as session:
        rows = session.execute(select(JobSchedule).order_by(JobSchedule.kind)).scalars().all()
        return [ScheduleView.of(row) for row in rows]


def get_schedule(database: Database, schedule_id: str) -> ScheduleView:
    """One schedule.

    Raises:
        JobNotFound: No such schedule.
    """
    with database.read() as session:
        row = session.get(JobSchedule, schedule_id)
        if row is None:
            raise JobNotFound(f"No schedule {schedule_id!r}.", details={"schedule_id": schedule_id})
        return ScheduleView.of(row)


def update_schedule(
    database: Database,
    schedule_id: str,
    *,
    now: datetime,
    cron: str | None = None,
    enabled: bool | None = None,
    params: Mapping[str, Any] | None = None,
) -> ScheduleView:
    """Change a schedule's cron, parameters or enabled flag.

    Enabling one — or editing one that is enabled — validates its parameters as a run would, so a
    schedule that could never run cannot be switched on. Enabling or changing the cron takes the
    first future slot; disabling clears it, so a schedule re-enabled after a month does not catch up
    on the month.

    Raises:
        JobNotFound: No such schedule.
        CronInvalid: The expression is not five valid fields, or never fires.
        JobParamsInvalid: The schedule would be enabled with parameters its kind refuses.
    """
    expression = parse_cron(cron) if cron is not None else None
    with database.write() as session:
        row = session.get(JobSchedule, schedule_id)
        if row is None:
            raise JobNotFound(f"No schedule {schedule_id!r}.", details={"schedule_id": schedule_id})
        new_params = (
            dict(params)
            if params is not None
            else dict(cast("Mapping[str, Any]", row.params or {}))
        )
        new_enabled = row.enabled if enabled is None else enabled
        if new_enabled:
            new_params = validate_params(row.kind, new_params)
        moved = expression is not None and expression.text != row.cron
        if expression is not None:
            row.cron = expression.text
        if not new_enabled:
            row.next_run_at = None
        elif moved or not row.enabled or row.next_run_at is None:
            row.next_run_at = next_fire(parse_cron(row.cron), after=now)
        row.enabled = new_enabled
        row.params = new_params
        session.flush()
        return ScheduleView.of(row)


def tick_schedules(database: Database, *, now: datetime) -> list[str]:
    """Decide every enabled schedule at ``now`` and enqueue what is due; the job ids enqueued.

    A due schedule fires once however many slots it missed (``domain/jobs.schedule_tick``). Its
    ``next_run_at`` is moved by a compare-and-set, so a second tick enqueues nothing. A schedule
    whose parameters have stopped validating moves on without enqueueing, and says so in the log.
    """
    with database.read() as session:
        due = [
            (
                row.id,
                row.kind,
                dict(cast("Mapping[str, Any]", row.params or {})),
                row.cron,
                row.next_run_at,
            )
            for row in session.execute(
                select(JobSchedule).where(
                    JobSchedule.enabled.is_(True),
                    or_(JobSchedule.next_run_at.is_(None), JobSchedule.next_run_at <= now),
                )
            ).scalars()
        ]
    enqueued: list[str] = []
    for schedule_id, kind, params, cron, next_run_at in due:
        try:
            tick = schedule_tick(parse_cron(cron), next_run_at=next_run_at, now=now)
        except CronInvalid:
            logger.warning("jobs.schedule_cron_invalid", extra={"schedule_id": schedule_id})
            continue
        with database.write() as session:
            current = (
                JobSchedule.next_run_at.is_(None)
                if next_run_at is None
                else JobSchedule.next_run_at == next_run_at
            )
            values: dict[str, Any] = {"next_run_at": tick.next_run_at}
            if tick.fire:
                values["last_run_at"] = now
            moved = session.execute(
                update(JobSchedule)
                .where(JobSchedule.id == schedule_id, JobSchedule.enabled.is_(True), current)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if _rowcount(moved) != 1 or not tick.fire:
                continue
            try:
                validated = validate_params(kind, params)
            except JobParamsInvalid as exc:
                logger.warning(
                    "jobs.schedule_params_invalid",
                    extra={"schedule_id": schedule_id, "detail": exc.message},
                )
                continue
            job = Job(
                id=new_id(),
                kind=kind,
                params=validated,
                state="queued",
                schedule_id=schedule_id,
                attempt=0,
                queued_at=now,
            )
            session.add(job)
            session.flush()
            session.execute(
                update(JobSchedule)
                .where(JobSchedule.id == schedule_id)
                .values(last_job_id=job.id)
                .execution_options(synchronize_session=False)
            )
            enqueued.append(job.id)
    return enqueued


# --- Executing a job ------------------------------------------------------------------------------


class OutputBuffer:
    """A job's captured stdout/stderr: capped to its tail, flushed to the row as it grows.

    Thread-safe — a subprocess's reader thread writes while the worker thread reads — and bounded in
    memory at a few times the cap however much a child prints.
    """

    def __init__(
        self,
        cap_bytes: int,
        *,
        flush: Callable[[str], None] | None = None,
        interval_seconds: float = _OUTPUT_FLUSH_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """An empty buffer; ``flush`` gets the capped text at most every ``interval_seconds``."""
        self._cap = cap_bytes
        self._parts: list[str] = []
        self._size = 0
        self._lock = threading.Lock()
        self._flush = flush
        self._interval = interval_seconds
        self._clock = clock
        self._flushed_at = float("-inf")
        self._unflushed = False

    def write(self, text: str) -> None:
        """Append ``text``; compact when it has grown past four caps; flush when it is time."""
        with self._lock:
            self._parts.append(text)
            self._size += len(text)
            if self._size > 4 * self._cap:
                collapsed = cap_output("".join(self._parts), self._cap)
                self._parts, self._size = [collapsed], len(collapsed)
            self._unflushed = True
        self.flush_due()

    def flush_due(self) -> None:
        """Flush what was written since the last flush, once ``interval_seconds`` have passed.

        ``run_streaming`` also calls it between polls, so a line a child prints before going quiet —
        the run id ``freeweight run start --json`` prints, which the Runs page follows — reaches the
        row within one interval, not when the child next prints or exits.
        """
        pending: str | None = None
        with self._lock:
            now = self._clock()
            due = now - self._flushed_at >= self._interval
            if self._flush is not None and self._unflushed and due:
                self._flushed_at, self._unflushed = now, False
                pending = cap_output("".join(self._parts), self._cap)
        if pending is not None and self._flush is not None:
            try:
                self._flush(pending)
            except Exception:  # noqa: BLE001 — a failed live view never fails the job
                logger.warning("jobs.output_flush_failed", exc_info=True)

    def line(self, text: str) -> None:
        """Append one line."""
        self.write(text if text.endswith("\n") else text + "\n")

    def text(self) -> str:
        """Everything kept, capped."""
        with self._lock:
            return cap_output("".join(self._parts), self._cap)


@dataclass(frozen=True, slots=True)
class Outcome:
    """How an executor ended.

    ``handed_off`` is ``self_restore``'s alone: the job is still running, in another process that
    records its end itself (ADR-0136 rule 2).
    """

    state: Literal["completed", "failed", "cancelled", "handed_off"]
    error: str | None = None


type Launcher = Callable[[Sequence[str], Mapping[str, str]], subprocess.Popen[str]]


def _launch(argv: Sequence[str], env: Mapping[str, str]) -> subprocess.Popen[str]:
    """Start one streaming child: stdout and stderr on one pipe, its own session."""
    return subprocess.Popen(  # noqa: S603 — argv list, never a shell; env is an allowlist
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=dict(env),
        start_new_session=True,
    )


@dataclass(frozen=True, slots=True)
class JobServices:
    """The boundaries the job kinds reach through — injected, so a test builds them over fakes."""

    controller: SystemdController
    http: httpx.Client
    urls: DatabaseUrlCache
    ollama_http: httpx.Client | None = None
    which: Callable[[str], str | None] | None = None
    runner: Runner | None = None
    launcher: Launcher = _launch
    config_path: Path | None = None
    cgroup: Callable[[], str] | None = None


@dataclass(frozen=True, slots=True)
class JobContext:
    """What an executor is handed: its job, the console's own handles and its two channels back."""

    job: JobView
    settings: Settings
    database: Database
    services: JobServices
    output: OutputBuffer
    cancelled: Callable[[], bool]
    now: Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class StreamResult:
    """A streamed child's end: its exit code and whether the console stopped it, and why."""

    argv: tuple[str, ...]
    returncode: int
    timed_out: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        """Exit 0, on its own."""
        return self.returncode == 0 and not self.timed_out and not self.cancelled


def _pump(process: subprocess.Popen[str], output: OutputBuffer) -> None:
    stream = process.stdout
    if stream is None:  # pragma: no cover — the launcher always gives a pipe
        return
    try:
        for raw in stream:
            output.write(raw[:OUTPUT_CAP_BYTES])
    except (OSError, ValueError):  # the pipe closed under us
        return


def run_streaming(
    argv: Sequence[str],
    env: Mapping[str, str],
    *,
    output: OutputBuffer,
    cancelled: Callable[[], bool],
    timeout_seconds: float,
    launcher: Launcher = _launch,
    grace_seconds: float = _STOP_GRACE_SECONDS,
    poll_seconds: float = _STREAM_POLL_SECONDS,
) -> StreamResult:
    """Run a long child, its output streamed into ``output``, stoppable by a cancel.

    ``processes.run_command`` captures and returns; a benchmark run takes an hour and its output is
    watched while it runs, and it has to stop when the operator cancels — so this polls.

    A cancel sends ``SIGINT`` — the suite's CLIs treat it as Ctrl-C and stop cleanly (FreeWeight
    exits 6 with the run marked cancelled) — a timeout sends ``SIGTERM``, and a child still alive
    ``grace_seconds`` later is killed.

    Returns:
        The result. A child that cannot be started is ``returncode -1`` with the reason in
        ``output``, never an exception.
    """
    try:
        process = launcher(argv, env)
    except OSError as exc:
        output.line(f"{argv[0]} could not be started: {exc}")
        return StreamResult(tuple(argv), -1)
    reader = threading.Thread(target=_pump, args=(process, output), daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout_seconds
    stopped_at: float | None = None
    was_cancelled = timed_out = False
    while True:
        try:
            returncode = process.wait(timeout=poll_seconds)
            break
        except subprocess.TimeoutExpired:
            output.flush_due()
        if stopped_at is None:
            if cancelled():
                was_cancelled, stopped_at = True, time.monotonic()
                process.send_signal(signal.SIGINT)
            elif time.monotonic() >= deadline:
                timed_out, stopped_at = True, time.monotonic()
                process.send_signal(signal.SIGTERM)
        elif time.monotonic() - stopped_at >= grace_seconds:
            process.kill()
    reader.join(timeout=5.0)
    return StreamResult(tuple(argv), returncode, timed_out=timed_out, cancelled=was_cancelled)


class _CancelProbe:
    """``cancel_requested`` for one job, read at most once a second."""

    def __init__(self, database: Database, job_id: str) -> None:
        self._database = database
        self._job_id = job_id
        self._checked_at = float("-inf")
        self._seen = False

    def __call__(self) -> bool:
        if self._seen:
            return True
        now = time.monotonic()
        if now - self._checked_at >= _CANCEL_PROBE_SECONDS:
            self._checked_at = now
            try:
                self._seen = cancel_requested(self._database, self._job_id)
            except Exception:  # noqa: BLE001 — an unreadable flag is not a cancel
                logger.warning("jobs.cancel_probe_failed", exc_info=True)
        return self._seen


def _audit_app(kind: str) -> str:
    # `catalog_pull` can no longer be started (ADR-0146), but a stored row of it can still be
    # cancelled or failed, and its audit row keeps naming Ollama as it always did.
    return {"freeweight_suite_run": "freeweight", "catalog_pull": "ollama"}.get(kind, "weightroom")


type Executor = Callable[[JobContext], Outcome]


class JobWorker:
    """The one worker thread and the one lease keeper thread of a serving console.

    Built by the web lifespan (``app.state.jobs``), started after its first recovery pass and
    stopped at shutdown. :meth:`run_once` is the whole of one tick and is what tests drive, with no
    thread at all.

    Args:
        database: WeightRoomGym's own database.
        settings: The validated settings — ``[jobs]`` and everything the kinds read.
        services: The boundaries the kinds reach through.
        executors: Kind to executor; ``services/job_kinds.EXECUTORS`` when ``None``.
        clock: The wall clock, injected.
    """

    def __init__(
        self,
        database: Database,
        settings: Settings,
        services: JobServices,
        *,
        executors: Mapping[str, Executor] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Configure the worker without starting either thread."""
        if executors is None:
            from weightroom.services.job_kinds import EXECUTORS

            executors = EXECUTORS
        self._database = database
        self._settings = settings
        self._services = services
        self._executors = dict(executors)
        self._clock = clock
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._held: set[str] = set()
        self._held_lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    @property
    def held(self) -> frozenset[str]:
        """The jobs this process is executing, whose leases the keeper renews."""
        with self._held_lock:
            return frozenset(self._held)

    def start(self) -> None:
        """Recover, then start the worker and the keeper; a second call does nothing."""
        if self._threads:
            return
        recover(self._database, now=self._clock())
        self._stop.clear()
        for target, name in ((self._work, "wr-gym-jobs"), (self._keep, "wr-gym-lease-keeper")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self, *, timeout: float = 5.0) -> None:
        """Stop both threads and wait for them. A job still executing keeps its lease until the
        process exits, then recovery decides it."""
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def wake(self) -> None:
        """Look for work now rather than at the next poll — called after an enqueue."""
        self._wake.set()

    def _poll_seconds(self) -> float:
        from weightroom.services.settings import read_runtime_settings

        try:
            effective = read_runtime_settings(self._database, settings=self._settings)
            return float(effective["jobs.poll_interval_ms"]) / 1000.0
        except Exception:  # noqa: BLE001 — an unreadable settings row falls back to the file
            return self._settings.jobs.poll_interval_ms / 1000.0

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                ran = self.run_once()
            except Exception:  # noqa: BLE001 — one bad tick never stops the queue
                logger.exception("jobs.tick_failed")
                ran = None
            if ran is None:
                self._wake.wait(self._poll_seconds())
                self._wake.clear()

    def _keep(self) -> None:
        interval = heartbeat_seconds(self._settings.jobs.lease_seconds)
        while not self._stop.wait(interval):
            try:
                renew_leases(
                    self._database,
                    sorted(self.held),
                    now=self._clock(),
                    lease_seconds=self._settings.jobs.lease_seconds,
                )
            except Exception:  # noqa: BLE001 — a missed renewal is what the lease tolerates
                logger.warning("jobs.renew_failed", exc_info=True)

    def run_once(self) -> str | None:
        """One tick: recover expired leases, fire due schedules, claim and execute one job.

        Returns:
            The id of the job executed, or ``None`` when nothing was queued.
        """
        now = self._clock()
        recover(self._database, now=now)
        tick_schedules(self._database, now=now)
        job = claim_next(self._database, now=now, lease_seconds=self._settings.jobs.lease_seconds)
        if job is None:
            return None
        self.execute(job)
        return job.id

    def execute(self, job: JobView) -> JobView | None:
        """Execute one claimed job and record its end.

        Returns:
            The finished job; ``None`` when it was handed off, or when its lease was lost while it
            ran and recovery had already moved it.
        """
        executor = self._executors.get(job.kind)
        audit_id = audit.record(
            self._database,
            action="job.run",
            actor="job",
            outcome="pending",
            now=self._clock(),
            app=_audit_app(job.kind),
            target=job.id,
            params={"kind": job.kind, "params": job.params, "attempt": job.attempt},
        )
        attach_audit(self._database, job.id, audit_id)
        with self._held_lock:
            self._held.add(job.id)
        output = OutputBuffer(
            self._settings.jobs.output_cap_bytes,
            flush=lambda text: set_output(self._database, job.id, text),
        )
        context = JobContext(
            job=job,
            settings=self._settings,
            database=self._database,
            services=self._services,
            output=output,
            cancelled=_CancelProbe(self._database, job.id),
            now=self._clock,
        )
        try:
            if executor is None:
                outcome = Outcome("failed", f"no executor for kind {job.kind!r} in this build")
            else:
                outcome = executor(context)
        except SuiteError as exc:
            outcome = Outcome("failed", exc.message)
        except Exception as exc:  # noqa: BLE001 — a crashing kind is a failed job, not a dead worker
            logger.exception("jobs.executor_crashed", extra={"job_id": job.id, "kind": job.kind})
            outcome = Outcome("failed", f"{type(exc).__name__}: {exc}")
        if outcome.state == "handed_off":
            set_output(self._database, job.id, output.text())
            return None
        with self._held_lock:
            self._held.discard(job.id)
        try:
            finished = finish(
                self._database,
                job.id,
                state=outcome.state,
                now=self._clock(),
                output=output.text(),
                error=outcome.error,
            )
        except SuiteError:
            logger.warning("jobs.lease_lost_while_running", extra={"job_id": job.id})
            return None
        try:
            audit.complete(
                self._database,
                audit_id,
                outcome="ok" if outcome.state == "completed" else "failed",
                message=outcome.error,
            )
        except ValueError:
            logger.info("jobs.audit_already_complete", extra={"audit_id": audit_id})
        return finished


def params_from_text(text: str) -> dict[str, Any]:
    """A parameters object typed into a form: ``{}`` for nothing, else a JSON object.

    Raises:
        JobParamsInvalid: Not JSON, or not an object.
    """
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise JobParamsInvalid(
            f"The parameters are not JSON: {exc}.", details={"params": text[:200]}
        ) from exc
    if not isinstance(value, dict):
        raise JobParamsInvalid("The parameters must be a JSON object.", details={})
    return value

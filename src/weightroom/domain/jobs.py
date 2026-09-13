"""weightroom.domain.jobs — the queue's rules, as pure functions (spec §7.10).

ADR-0010's shape, and ADR-0029's four findings answered for a console with seven job kinds and one
worker thread:

1. **Ageing never happens.** Not needed: jobs are claimed oldest first and carry no priority to
   age (spec §7.10, "ageing not needed for four kinds").
2. **The attempt counter has two writers.** One writer: the claim increments ``attempt`` and
   nothing else does. ADR-0029 moved LoadCoach's increment out of its claim because LoadCoach
   retries *inside* a lease and records each try as a ``job_attempts`` row; this queue has no
   in-lease retry and no attempts table, so one claim is one execution and the collision cannot
   arise.
3. **A claimed job with nowhere to go.** :data:`TRANSITIONS` is complete for the states this queue
   has: a cancel that arrives after the claim is a flag on the running job, honoured by its
   executor, and every running job has three terminal exits and one recovery exit.
4. **The heartbeat has no thread.** The lease keeper renews on its own thread, never the worker's,
   which spends an hour inside a benchmark run (``services/jobs.py``).

Schedules are five-field cron expressions evaluated in **UTC**, parsed here with the standard
library only. A schedule missed while the console was down fires once when it returns, never once
per missed slot (:func:`schedule_tick`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal

from baseaicore import SuiteError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "BACKUP_TARGETS",
    "IDEMPOTENT_KINDS",
    "JOB_KINDS",
    "JOB_STATES",
    "REFRESH_TARGETS",
    "SELF_RESTORE_CONFIRMATION",
    "SUITE_RUN_SCOPE_PREFIX",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "WORKER_LOST",
    "CronExpression",
    "CronInvalid",
    "JobInvalidState",
    "JobParamsInvalid",
    "ScheduleTick",
    "cancel_action",
    "cap_output",
    "heartbeat_seconds",
    "lease_until",
    "needs_reauth",
    "next_fire",
    "parse_cron",
    "recovery_action",
    "require_transition",
    "schedule_tick",
    "validate_params",
]

JOB_KINDS: Final[tuple[str, ...]] = (
    "freeweight_suite_run",
    "freeweight_goal_calibrate",
    "retention_trim",
    "backup",
    "model_refresh",
    "docs_index",
    "self_restore",
)
"""Spec §7.10's four, the two earlier rows left as callables, and WeightRoomGym's own restore
(ADR-0136). ``catalog_pull`` left with the catalog (ADR-0146): it can no longer be queued, and a
stored row of it still lists, renders and cancels — nothing that reads a job checks its kind."""

JOB_STATES: Final[tuple[str, ...]] = ("queued", "running", "completed", "failed", "cancelled")
TERMINAL_STATES: Final[frozenset[str]] = frozenset({"completed", "failed", "cancelled"})

TRANSITIONS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("queued", "running"),  # the claim
        ("queued", "cancelled"),  # a cancel before the claim takes effect at once
        ("running", "completed"),
        ("running", "failed"),
        ("running", "cancelled"),  # the executor honoured the cancel flag
        ("running", "queued"),  # recovery: an idempotent job whose lease expired
    }
)
"""Every legal move; anything else is refused by :func:`require_transition`."""

IDEMPOTENT_KINDS: Final[frozenset[str]] = frozenset(
    {"retention_trim", "backup", "model_refresh", "docs_index"}
)
"""Kinds whose second execution is harmless, so a lost lease requeues them.

``freeweight_suite_run`` is not — a second run is a second measurement of the machine, recorded
for ever — and neither is ``self_restore``, whose second execution would discard what the first
carried forward. A lost lease fails those with :data:`WORKER_LOST` (queue-and-scheduling §3).
"""

WORKER_LOST: Final = "worker_lost"

SUITE_RUN_SCOPE_PREFIX: Final = "wr-gym-fwrun-"
"""The transient scope a `freeweight_suite_run` job launches under: `wr-gym-fwrun-<job id>.scope`.

Named rather than left to `systemd-run`'s `run-r<hex>.scope`, so the memory-cap alert source can
recognise a kill inside one (row W10; `history/handoffs/W9_HANDOFF.md` §5 item 5g).
"""

BACKUP_TARGETS: Final[tuple[str, ...]] = (
    "freeweight",
    "loadcoach",
    "ideapress",
    "promptcadence",
    "weightroom",
)
REFRESH_TARGETS: Final[tuple[str, ...]] = ("freeweight", "loadcoach")
"""The two applications with a ``models refresh`` verb — the only two that own a models table."""

SELF_RESTORE_CONFIRMATION: Final = "weightroom"
"""What the operator types to restore WeightRoomGym's own database (ADR-0136 rule 1)."""


class JobInvalidState(SuiteError):
    """A move the state machine does not allow — cancelling a finished job, most often."""

    code: ClassVar[str] = "JOB_INVALID_STATE"


class JobParamsInvalid(SuiteError):
    """A job kind this queue does not have, or parameters its kind does not accept."""

    code: ClassVar[str] = "VALIDATION_ERROR"


class CronInvalid(SuiteError):
    """A schedule expression that is not five valid fields, or one that never fires."""

    code: ClassVar[str] = "VALIDATION_ERROR"


# --- States and leases ----------------------------------------------------------------------------


def require_transition(current: str, target: str) -> None:
    """Refuse a move :data:`TRANSITIONS` does not name.

    Raises:
        JobInvalidState: ``current → target`` is not a legal move.
    """
    if (current, target) not in TRANSITIONS:
        raise JobInvalidState(
            f"A {current} job cannot become {target}.",
            details={"state": current, "target": target},
        )


def needs_reauth(kind: str, params: Mapping[str, Any] | None) -> bool:
    """Whether queueing or scheduling ``kind`` with ``params`` is a security action.

    Two are: restoring WeightRoomGym's own database (ADR-0136 rule 1), and a retention trim that
    deletes FreeWeight's stored results — the deletion the console's own curated path
    re-authenticates (ADR-0134 rule 2), so a schedule must not become the way around that.
    """
    if kind == "self_restore":
        return True
    return kind == "retention_trim" and (params or {}).get("freeweight_older_than_days") is not None


def cancel_action(state: str) -> Literal["cancel", "request"]:
    """What cancelling a job in ``state`` does.

    Returns:
        ``cancel`` for a queued job, which is cancelled in the same transaction; ``request`` for a
        running one, whose executor sees the flag and stops.

    Raises:
        JobInvalidState: The job has already finished (api.md §7: cancelling a finished job).
    """
    if state == "queued":
        return "cancel"
    if state == "running":
        return "request"
    raise JobInvalidState(
        f"The job is already {state}; there is nothing to cancel.", details={"state": state}
    )


def heartbeat_seconds(lease_seconds: float) -> float:
    """How often the lease keeper renews: a third of the lease (data model §2, ADR-0029 §4)."""
    return lease_seconds / 3


def lease_until(now: datetime, lease_seconds: float) -> datetime:
    """When a lease taken or renewed at ``now`` expires."""
    return now + timedelta(seconds=lease_seconds)


def recovery_action(
    *, kind: str, lease_expires_at: datetime | None, now: datetime
) -> Literal["requeue", "fail"] | None:
    """What the recovery pass does with one running job.

    Args:
        kind: The job's kind.
        lease_expires_at: Its lease; ``None`` is read as expired, since a running job with no lease
            is one no keeper holds.
        now: The instant.

    Returns:
        ``None`` while the lease is live — a worker holds it; ``requeue`` for an idempotent kind
        whose lease expired; ``fail`` (with :data:`WORKER_LOST`) for any other.
    """
    if lease_expires_at is not None and lease_expires_at > now:
        return None
    return "requeue" if kind in IDEMPOTENT_KINDS else "fail"


def cap_output(text: str, cap_bytes: int) -> str:
    """Keep the last ``cap_bytes`` of ``text``, saying how much went.

    The tail rather than the head: a benchmark's result and a command's failure are both at the end.

    Returns:
        ``text`` unchanged when it fits; otherwise a one-line marker and the tail, together at most
        ``cap_bytes`` of UTF-8, with a character cut in half dropped rather than mangled.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= cap_bytes:
        return text
    marker = f"[… {len(encoded)} bytes, earlier output dropped …]\n"
    room = max(cap_bytes - len(marker.encode("utf-8")), 0)
    tail = encoded[len(encoded) - room :].decode("utf-8", errors="ignore") if room else ""
    return marker + tail


# --- Parameters -----------------------------------------------------------------------------------

_SUITE_KEY: Final = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
_GOAL_SLUG: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
"""FreeWeight's own slug pattern (``domain/goals/pack.SLUG_PATTERN``); it is one CLI argument."""
_ADAPTER_NAME: Final = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
"""The adapter-name pattern ``model.adapter_manifest`` 1.0 states; it is one CLI argument.

Checked here because it reaches a child process's argv, not to decide whether the adapter exists or
can be served — that is FreeWeight's answer and the console renders it (ADR-0140, ADR-0058)."""


class _Required:
    """The default of a parameter that has none."""


_REQUIRED: Final = _Required()

type _Check = Callable[[str, str, Any], Any]


def _refuse(kind: str, name: str, problem: str) -> JobParamsInvalid:
    return JobParamsInvalid(
        f"{kind}: {name} {problem}.",
        details={"fields": [{"path": f"params.{name}", "problem": problem}], "kind": kind},
    )


def _text(pattern: re.Pattern[str] | None = None, *, max_chars: int = 4096) -> _Check:
    def check(kind: str, name: str, value: Any) -> str:  # noqa: ANN401 — JSON input
        if not isinstance(value, str) or not value.strip() or len(value) > max_chars:
            raise _refuse(kind, name, "must be non-empty text")
        if pattern is not None and not pattern.match(value):
            raise _refuse(kind, name, f"does not match {pattern.pattern}")
        return value.strip()

    return check


def _optional_text(pattern: re.Pattern[str] | None = None, *, max_chars: int) -> _Check:
    """Text that may be left out: ``None`` or blank is ``None``, anything longer is refused."""

    def check(kind: str, name: str, value: Any) -> str | None:  # noqa: ANN401 — JSON input
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str) or len(value) > max_chars:
            raise _refuse(kind, name, f"must be text of at most {max_chars} characters")
        text = value.strip()
        if pattern is not None and not pattern.match(text):
            raise _refuse(kind, name, f"does not match {pattern.pattern}")
        return text

    return check


def _flag(kind: str, name: str, value: Any) -> bool:  # noqa: ANN401 — JSON input
    if not isinstance(value, bool):
        raise _refuse(kind, name, "must be true or false")
    return value


def _days(minimum: int) -> _Check:
    def check(kind: str, name: str, value: Any) -> int | None:  # noqa: ANN401 — JSON input
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise _refuse(kind, name, f"must be a whole number of days, at least {minimum}")
        return int(value)

    return check


def _targets(allowed: tuple[str, ...]) -> _Check:
    def check(kind: str, name: str, value: Any) -> list[str]:  # noqa: ANN401 — JSON input
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(one, str) or one not in allowed for one in value)
        ):
            raise _refuse(kind, name, f"must be a non-empty list drawn from {', '.join(allowed)}")
        return [one for one in allowed if one in value]

    return check


_PARAMS: Final[Mapping[str, Mapping[str, tuple[_Check, Any]]]] = {
    "freeweight_suite_run": {
        "model": (_text(max_chars=512), _REQUIRED),
        "suite": (_text(_SUITE_KEY, max_chars=128), _REQUIRED),
        "allow_prompt_override": (_flag, False),
        # Row WP3: the Runs page's label, passed through as `run start --label`.
        "label": (_optional_text(max_chars=120), None),
        # Row WPF2: the adapter, passed through as `run start --adapter`. One more argument to the
        # same capped command, never a second path (ADR-0119, WP3 §2 item 2).
        "adapter": (_optional_text(_ADAPTER_NAME, max_chars=64), None),
    },
    # Row WP4: a goal's calibration — its jury grading the holdout — run as `goals calibrate`.
    "freeweight_goal_calibrate": {
        "goal": (_text(_GOAL_SLUG, max_chars=64), _REQUIRED),
        "graded_by": (_optional_text(max_chars=120), None),
    },
    "retention_trim": {
        "guarded_backup_days": (_days(0), 90),
        "freeweight_older_than_days": (_days(1), None),
    },
    "backup": {"apps": (_targets(BACKUP_TARGETS), list(BACKUP_TARGETS))},
    "model_refresh": {"apps": (_targets(REFRESH_TARGETS), list(REFRESH_TARGETS))},
    "docs_index": {},
    "self_restore": {"file": (_text(max_chars=4096), _REQUIRED)},
}


def validate_params(kind: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Check ``params`` against ``kind``'s parameters and fill in the defaults.

    Args:
        kind: One of :data:`JOB_KINDS`.
        params: The JSON object given, or ``None`` for none.

    Returns:
        Every parameter the kind takes, given or defaulted.

    Raises:
        JobParamsInvalid: An unknown kind, an unknown parameter, a missing required one, or a value
            of the wrong shape — each named.
    """
    spec = _PARAMS.get(kind)
    if spec is None:
        raise JobParamsInvalid(
            f"{kind!r} is not a job kind; the kinds are {', '.join(JOB_KINDS)}.",
            details={"kind": kind},
        )
    given = dict(params or {})
    unknown = sorted(set(given) - set(spec))
    if unknown:
        raise JobParamsInvalid(
            f"{kind} takes no parameter {', '.join(unknown)}; it takes "
            f"{', '.join(spec) or 'none'}.",
            details={"kind": kind, "unknown": unknown},
        )
    out: dict[str, Any] = {}
    for name, (check, default) in spec.items():
        if name in given:
            out[name] = check(kind, name, given[name])
        elif isinstance(default, _Required):
            raise _refuse(kind, name, "is required")
        else:
            out[name] = list(default) if isinstance(default, list) else default
    return out


# --- Cron -----------------------------------------------------------------------------------------

_FIELDS: Final[tuple[tuple[str, int, int], ...]] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 7),
)
_MONTH_NAMES: Final[dict[str, int]] = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_DAY_NAMES: Final[dict[str, int]] = {
    name: number for number, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))
}
_SEARCH_DAYS: Final = 366 * 8
"""How far :func:`next_fire` looks: a 29 February expression fires within four years, and
anything that has not fired in eight never will."""


@dataclass(frozen=True, slots=True)
class CronExpression:
    """A parsed five-field expression: the matching values per field, sorted.

    Attributes:
        text: The expression, whitespace normalised.
        minutes: Matching minutes.
        hours: Matching hours.
        days_of_month: Matching days of the month.
        months: Matching months.
        days_of_week: Matching weekdays, ``0`` Sunday.
        day_of_month_restricted: Whether the day-of-month field was other than ``*…``.
        day_of_week_restricted: Likewise for the day of the week — when both are, a day matches
            if **either** does (Vixie cron's rule, and every crontab's).
    """

    text: str
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    day_of_month_restricted: bool
    day_of_week_restricted: bool

    def matches_day(self, day: date) -> bool:
        """Whether any minute of ``day`` can match."""
        if day.month not in self.months:
            return False
        by_date = day.day in self.days_of_month
        by_weekday = day.isoweekday() % 7 in self.days_of_week
        if self.day_of_month_restricted and self.day_of_week_restricted:
            return by_date or by_weekday
        if self.day_of_month_restricted:
            return by_date
        if self.day_of_week_restricted:
            return by_weekday
        return True


def _invalid(text: str, problem: str) -> CronInvalid:
    return CronInvalid(
        f"{text!r} is not a schedule: {problem}. Five fields: minute hour day-of-month month "
        "day-of-week, evaluated in UTC.",
        details={"cron": text, "problem": problem},
    )


def _value(token: str, index: int, text: str) -> int:
    name, low, high = _FIELDS[index]
    names = _MONTH_NAMES if index == 3 else _DAY_NAMES if index == 4 else {}
    lowered = token.lower()
    if lowered in names:
        return names[lowered]
    if not token.isdigit() or not low <= int(token) <= high:
        raise _invalid(text, f"{token!r} is not a {name} ({low}–{high})")
    return int(token)


def _field(field: str, index: int, text: str) -> tuple[frozenset[int], bool]:
    name, low, high = _FIELDS[index]
    values: set[int] = set()
    for part in field.split(","):
        base, slash, step_text = part.partition("/")
        if slash and (not step_text.isdigit() or int(step_text) == 0):
            raise _invalid(text, f"{part!r} has a step that is not a positive number")
        step = int(step_text) if slash else 1
        if base == "*":
            start, end = low, high
        elif "-" in base:
            first, _dash, last = base.partition("-")
            start, end = _value(first, index, text), _value(last, index, text)
            if start > end:
                raise _invalid(text, f"{part!r} is a {name} range that runs backwards")
        else:
            start = _value(base, index, text)
            end = high if slash else start
        values.update(range(start, end + 1, step))
    if index == 4 and 7 in values:
        values.discard(7)
        values.add(0)
    return frozenset(values), not field.startswith("*")


def parse_cron(text: str) -> CronExpression:
    """Parse a five-field expression: ``*``, ``a``, ``a-b``, lists, ``/n`` steps, month and weekday
    names.

    Raises:
        CronInvalid: Not five fields, a value out of range, a malformed step or range, or an
            expression that never fires (``0 0 31 2 *``).
    """
    fields = text.split()
    if len(fields) != len(_FIELDS):
        raise _invalid(text, f"{len(fields)} fields, not {len(_FIELDS)}")
    parsed = [_field(field, index, text) for index, field in enumerate(fields)]
    expression = CronExpression(
        text=" ".join(fields),
        minutes=tuple(sorted(parsed[0][0])),
        hours=tuple(sorted(parsed[1][0])),
        days_of_month=parsed[2][0],
        months=parsed[3][0],
        days_of_week=parsed[4][0],
        day_of_month_restricted=parsed[2][1],
        day_of_week_restricted=parsed[4][1],
    )
    next_fire(expression, after=datetime(2000, 1, 1, tzinfo=UTC))
    return expression


def next_fire(expression: CronExpression, *, after: datetime) -> datetime:
    """The first matching minute strictly after ``after``, in UTC.

    Raises:
        CronInvalid: Nothing matches within :data:`_SEARCH_DAYS`.
    """
    instant = after.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for offset in range(_SEARCH_DAYS):
        candidate = instant.date() + timedelta(days=offset)
        if not expression.matches_day(candidate):
            continue
        floor_hour, floor_minute = (instant.hour, instant.minute) if offset == 0 else (0, 0)
        for hour in expression.hours:
            if hour < floor_hour:
                continue
            for minute in expression.minutes:
                if hour == floor_hour and minute < floor_minute:
                    continue
                return datetime.combine(candidate, time(hour, minute), tzinfo=UTC)
    raise _invalid(expression.text, "it never fires")


@dataclass(frozen=True, slots=True)
class ScheduleTick:
    """One evaluation of a schedule: whether it enqueues now, and when it next runs."""

    fire: bool
    next_run_at: datetime


def schedule_tick(
    expression: CronExpression, *, next_run_at: datetime | None, now: datetime
) -> ScheduleTick:
    """Decide one schedule at ``now``: catch-up runs **once**.

    Args:
        expression: The schedule's cron.
        next_run_at: When it was due, or ``None`` for a schedule just enabled or edited.
        now: The instant.

    Returns:
        A slot due (at or before ``now``, however many were missed) fires once, and the next run is
        the first slot after ``now`` — never the slot after the missed one, which is what would
        queue a run per missed night. A schedule with no slot yet takes its first future one
        without firing. A future slot is left alone.
    """
    if next_run_at is None:
        return ScheduleTick(fire=False, next_run_at=next_fire(expression, after=now))
    if next_run_at <= now:
        return ScheduleTick(fire=True, next_run_at=next_fire(expression, after=now))
    return ScheduleTick(fire=False, next_run_at=next_run_at)

"""weightroom.services.journal — ``journalctl`` history and a live follow, per ADR-0125 rule 3.

Two reads of the same journal, with different shapes.

**History** is one ``journalctl --user -u <unit> -o json`` per page, newest first, capped at
:data:`JOURNAL_PAGE_CAP` rows, paged with the journal's own cursor. The cursor is systemd's,
not one invented here: it is stable across restarts of the console, it survives log rotation,
and ``--reverse --cursor <c>`` resumes *at* that entry and walks backwards, which was measured
rather than assumed (row W2).

**Follow** is one ``journalctl … -f`` per connected stream, whose stdout a reader thread parses
into MirrorWall's :class:`~mirrorwall.Subscription` — the bounded queue that drops the oldest
event and counts what it dropped. That count is what lets the stream tell a slow browser it fell
behind (the *dropped N lines* frame) instead of silently serving it a log with holes.

One process per connected stream, rather than one shared reader with a broker behind it. The
shared design is what MirrorWall's :class:`~mirrorwall.EventBroker` is for, and it is the right
one when the producer is expensive or must not be duplicated. Here the producer is a pipe from a
process systemd already runs, an operator console has one operator, and the shared version costs
a subscriber count, a start/stop race and a lifetime that outlives every request. The ceiling is
explicit: :data:`MAX_CONCURRENT_FOLLOWS` streams at once, after which a request is refused by
name rather than quietly forking a hundred readers.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess  # noqa: S404 — explicit argv, an allowlisted environment, never a shell
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Final

from baseaicore import SuiteError
from mirrorwall import Event, Subscription

from weightroom.services.processes import (
    OUTPUT_CAP_BYTES,
    CommandResult,
    Runner,
    Scope,
    UnitUnsupported,
    child_environment,
    run_command,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence

__all__ = [
    "DEFAULT_FOLLOW_BACKFILL",
    "DEFAULT_PAGE_LIMIT",
    "JOURNAL_PAGE_CAP",
    "MAX_CONCURRENT_FOLLOWS",
    "PRIORITY_NAMES",
    "JournalLine",
    "JournalPage",
    "JournalReader",
    "TooManyFollowers",
    "unwrap_suite_log",
    "priority_for_level",
]

logger = logging.getLogger(__name__)

JOURNAL_PAGE_CAP: Final = 5000
"""api.md §2: a history page is capped at five thousand rows, cursor or no cursor."""

DEFAULT_PAGE_LIMIT: Final = 200
DEFAULT_FOLLOW_BACKFILL: Final = 200
"""How many existing lines a follow opens with, so a reconnecting pane refills its tail."""

MAX_CONCURRENT_FOLLOWS: Final = 16
"""The ceiling on live ``journalctl -f`` processes; see this module's docstring."""

_FOLLOW_TIMEOUT_SECONDS: Final = 5.0
_HISTORY_TIMEOUT_SECONDS: Final = 30.0
_FILTER_OVERFETCH: Final = 10
"""How many rows a severity-filtered page reads for each row it wants."""

PRIORITY_NAMES: Final[dict[int, str]] = {
    0: "emerg",
    1: "alert",
    2: "crit",
    3: "err",
    4: "warning",
    5: "notice",
    6: "info",
    7: "debug",
}
"""syslog priorities, as the page's level filter names them."""

_NAME_TO_PRIORITY: Final[dict[str, int]] = {name: value for value, name in PRIORITY_NAMES.items()}


class TooManyFollowers(SuiteError):
    """More live log streams were asked for than :data:`MAX_CONCURRENT_FOLLOWS`."""

    code: ClassVar[str] = "RATE_LIMITED"


def priority_for_level(level: str | None) -> int | None:
    """Turn a level name or number into a syslog priority for ``journalctl -p``.

    Args:
        level: ``"err"``, ``"warning"``, ``"3"`` — or ``None``.

    Returns:
        The priority, or ``None`` when no filter was asked for.

    Raises:
        ValueError: The name is not one of :data:`PRIORITY_NAMES`.
    """
    if level is None or level == "":
        return None
    if level.isdigit() and 0 <= int(level) <= 7:
        return int(level)
    if level in _NAME_TO_PRIORITY:
        return _NAME_TO_PRIORITY[level]
    message = f"{level!r} is not a journal level; the names are {sorted(_NAME_TO_PRIORITY)}"
    raise ValueError(message)


def _message_text(raw: Any) -> str:  # noqa: ANN401 — the journal's own JSON, any shape
    """``MESSAGE`` as text.

    The journal stores a message as a string, or — when it is not valid UTF-8 — as an array of
    byte values, or not at all. All three are ordinary; a page that rendered ``None`` for the
    second would show an empty line where a binary log entry was.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        try:
            return bytes(int(value) for value in raw).decode("utf-8", errors="replace")
        except (TypeError, ValueError):  # pragma: no cover — defensive against a hostile journal
            return ""
    return "" if raw is None else str(raw)


_SUITE_LEVELS: Final[dict[str, str]] = {
    "CRITICAL": "crit",
    "FATAL": "crit",
    "ERROR": "err",
    "WARNING": "warning",
    "WARN": "warning",
    "INFO": "info",
    "DEBUG": "debug",
}


def _version_of(record: dict[str, Any]) -> str | None:
    """The record's own version, however its logger spelled the key.

    FreeWeight writes a top-level ``version``; LoadCoach writes ``loadcoach_version``; IdeaPress
    and PromptCadence write neither yet. Rather than hardcode four key names — which would need a
    new one for every future logger — the first key ending in ``_version`` is read too, so a
    logger this was never updated for still shows a number instead of silently showing none.
    """
    version = record.get("version")
    if isinstance(version, str):
        return version
    return next(
        (
            value
            for key, value in record.items()
            if key.endswith("_version") and isinstance(value, str)
        ),
        None,
    )


def unwrap_suite_log(
    message: str,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    """Unwrap a suite JSON log record, if that is what this line is.

    Every application in the suite logs one JSON object per line to stdout, so the journal holds
    the whole document as the message and records its priority as ``info`` — stdout has no
    severity. Two consequences, both of which this fixes: a log pane would render a wall of JSON,
    and an application's own ``ERROR`` would be invisible to a severity filter, because the
    *transport's* priority is 6 whatever the record says.

    Args:
        message: The journal's message text.

    Returns:
        ``(text, level, logger, request_id, version)`` — the record's own message, its own level
        as one of :data:`PRIORITY_NAMES`, the logger name, the correlation id bound for the
        request that produced it, and the application's own version (see :func:`_version_of`);
        ``(message, None, None, None, None)`` for a line that is not one of ours, which is left
        exactly as the journal holds it.

        The message itself is read from ``message`` first, then ``event`` — FreeWeight's own
        formatter (``freeweight.observability.logging.JsonFormatter``) writes ``event`` where
        LoadCoach, IdeaPress and PromptCadence all write ``message``, and a record checked against
        one spelling only was never unwrapped for the fourth of the suite's four loggers (found
        live against the operator's own ``freeweight.service`` journal, row WX2).
    """
    if not message.startswith("{") or ('"message"' not in message and '"event"' not in message):
        return message, None, None, None, None
    try:
        record = json.loads(message)
    except json.JSONDecodeError:
        return message, None, None, None, None
    if not isinstance(record, dict):
        return message, None, None, None, None
    text = record.get("message")
    if not isinstance(text, str):
        text = record.get("event")
    if not isinstance(text, str):
        return message, None, None, None, None
    level = _SUITE_LEVELS.get(str(record.get("level", "")).upper())
    logger_name = record.get("logger")
    request_id = record.get("request_id")
    return (
        text,
        level,
        str(logger_name) if isinstance(logger_name, str) else None,
        str(request_id) if isinstance(request_id, str) else None,
        _version_of(record),
    )


@dataclass(frozen=True, slots=True)
class JournalLine:
    """One journal entry, in the fields a log pane shows.

    Attributes:
        cursor: systemd's own opaque position, the unit of paging and of resumption.
        at: When it was logged, from ``__REALTIME_TIMESTAMP`` (microseconds since the epoch).
        priority: The syslog priority the *journal* recorded, 0–7.
        unit: The unit it came from, user or system.
        message: The text exactly as the journal holds it — a suite application's whole JSON
            record, when that is what it wrote.
        pid: The process, where the journal recorded one.
        identifier: ``SYSLOG_IDENTIFIER`` — usually the command's name.
        text: What a pane shows: the record's own message for a suite log line, else ``message``.
        record_level: The record's own severity, where it has one; see :func:`unwrap_suite_log`.
        logger: The record's own logger name, where it has one.
        request_id: The correlation id bound for the request that produced it, where it has one.
        version: The application's own version, where its logger names one.
    """

    cursor: str
    at: datetime
    priority: int
    unit: str
    message: str
    pid: int | None = None
    identifier: str = ""
    text: str = ""
    record_level: str | None = None
    logger: str | None = None
    request_id: str | None = None
    version: str | None = None

    @property
    def level(self) -> str:
        """The line's severity: the record's own where it has one, else the journal's priority.

        A suite application writes JSON to stdout, which the journal necessarily files at
        ``info``; the record's own ``ERROR`` is the true answer and is what the pane colours and
        what an operator means by *show me the errors*.
        """
        return self.record_level or PRIORITY_NAMES.get(self.priority, "info")

    @property
    def app(self) -> str:
        """The application this line belongs to: the unit without ``.service``."""
        return self.unit.removesuffix(".service")

    def as_json(self) -> dict[str, Any]:
        """The wire shape, for the history page and the SSE frame alike."""
        return {
            "cursor": self.cursor,
            "at": self.at.isoformat(),
            "priority": self.priority,
            "level": self.level,
            "unit": self.unit,
            "app": self.app,
            "message": self.text or self.message,
            "raw": self.message if self.text != self.message else None,
            "logger": self.logger,
            "request_id": self.request_id,
            "version": self.version,
            "pid": self.pid,
            "identifier": self.identifier,
        }


def parse_entry(raw: Mapping[str, Any]) -> JournalLine | None:
    """Turn one ``-o json`` object into a :class:`JournalLine`, or ``None`` when it is not one.

    Args:
        raw: The decoded object.

    Returns:
        The line, or ``None`` for an entry with no cursor — which is not an entry.
    """
    cursor = raw.get("__CURSOR")
    if not isinstance(cursor, str) or not cursor:
        return None
    stamp = raw.get("__REALTIME_TIMESTAMP", "0")
    microseconds = int(stamp) if isinstance(stamp, str) and stamp.isdigit() else 0
    priority_raw = raw.get("PRIORITY", "6")
    priority = int(priority_raw) if isinstance(priority_raw, str) and priority_raw.isdigit() else 6
    pid_raw = raw.get("_PID", "")
    # `USER_UNIT`/`UNIT` first. A message the service manager logs *about* a unit — "Started
    # loadcoach.service", "Failed with result 'exit-code'" — is emitted by `init.scope`, so the
    # underscored trusted fields name the manager rather than the unit the line is about, and a
    # per-application pane would label every one of those lines `init.scope`. The non-underscored
    # fields are the ones journalctl itself matches `-u` against. Found live at row W2.
    message = _message_text(raw.get("MESSAGE"))
    text, record_level, logger_name, request_id, version = unwrap_suite_log(message)
    unit = (
        raw.get("USER_UNIT")
        or raw.get("UNIT")
        or raw.get("_SYSTEMD_USER_UNIT")
        or raw.get("_SYSTEMD_UNIT")
        or ""
    )
    return JournalLine(
        cursor=cursor,
        at=datetime.fromtimestamp(microseconds / 1_000_000, tz=UTC),
        priority=min(max(priority, 0), 7),
        unit=str(unit),
        message=message,
        pid=int(pid_raw) if isinstance(pid_raw, str) and pid_raw.isdigit() else None,
        identifier=str(raw.get("SYSLOG_IDENTIFIER", "")),
        text=text,
        record_level=record_level,
        logger=logger_name,
        request_id=request_id,
        version=version,
    )


@dataclass(frozen=True, slots=True)
class JournalPage:
    """One page of history, newest first.

    Attributes:
        lines: The entries, newest first.
        next_cursor: Where the next (older) page starts, or ``None`` at the end of the journal.
        capped: Whether the request asked for more than :data:`JOURNAL_PAGE_CAP` and was clamped.
    """

    lines: tuple[JournalLine, ...]
    next_cursor: str | None
    capped: bool = False

    def as_json(self) -> dict[str, Any]:
        """The api.md §2 shape."""
        return {
            "lines": [line.as_json() for line in self.lines],
            "next_cursor": self.next_cursor,
            "has_more": self.next_cursor is not None,
            "capped_at": JOURNAL_PAGE_CAP if self.capped else None,
        }


class JournalReader:
    """``journalctl`` as a boundary, with the same injection points as the systemd controller.

    Args:
        which: Executable lookup, injected so a test can point at a fixture ``journalctl`` on
            ``PATH`` or withhold it entirely.
        runner: The one-shot process boundary, for history.
        environment: How a child's environment is built — the allowlist, never this process's.
        launcher: How a *streaming* child is started; injected for the same reasons, and
            separately because a follow owns a pipe for its whole life rather than a result.
    """

    __slots__ = ("_environment", "_launcher", "_live", "_lock", "_runner", "_which")

    def __init__(
        self,
        *,
        which: Callable[[str], str | None] = shutil.which,
        runner: Runner = run_command,
        environment: Callable[[], dict[str, str]] = child_environment,
        launcher: Callable[[Sequence[str], Mapping[str, str]], subprocess.Popen[str]] | None = None,
    ) -> None:
        """Build a reader over this host."""
        self._which = which
        self._runner = runner
        self._environment = environment
        self._launcher = launcher if launcher is not None else _launch_follow
        self._lock = threading.Lock()
        self._live = 0

    def available(self) -> bool:
        """Whether ``journalctl`` is on ``PATH``."""
        return self._which("journalctl") is not None

    def _journalctl(self) -> str:
        found = self._which("journalctl")
        if found is None:
            raise UnitUnsupported(
                "This host has no journalctl; the log pages are unsupported here. Every other "
                "page works (ADR-0125 rule 7).",
                details={"binary": "journalctl"},
            )
        return found

    def _base_argv(self, units: Sequence[str], *, scope: Scope) -> list[str]:
        argv = [self._journalctl(), "--no-pager", "-o", "json"]
        if scope == "user":
            argv.append("--user")
        for unit in units:
            argv += ["-u", unit]
        return argv

    def history(
        self,
        units: Sequence[str],
        *,
        scope: Scope = "user",
        since: str | None = None,
        until: str | None = None,
        level: str | None = None,
        query: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> JournalPage:
        """One page of history, newest first.

        Args:
            units: The units to read; several means one interleaved stream.
            scope: ``user`` for the applications, ``system`` for Ollama.
            since: ``journalctl --since`` — ``"-1h"``, ``"2026-09-09 12:00"``.
            until: ``journalctl --until``.
            level: A level name or number; entries at that severity **and more severe**.
                Applied here rather than by ``journalctl -p``: a suite application writes JSON to
                stdout, so the journal files even its ``ERROR`` records at priority 6 and ``-p
                err`` would return none of them. The reader over-fetches and filters on each
                line's true severity, so a filtered page can come back short of ``limit`` — which
                is why ``next_cursor`` is decided by the *fetched* window, not the filtered one.
            query: Free text. Matched literally: the string is escaped before it reaches
                ``--grep``, so an operator searching for ``a[0]`` finds ``a[0]`` and does not
                accidentally write a character class.
            limit: Rows wanted, clamped to :data:`JOURNAL_PAGE_CAP`.
            cursor: The previous page's ``next_cursor``; the page resumes at it and walks back.

        Returns:
            The page.

        Raises:
            UnitUnsupported: This host has no ``journalctl``.
            ValueError: ``level`` is not a journal level.
            JournalUnreadable: ``journalctl`` ran and refused — most often because the operator
                is not in a group that may read this unit's journal.
        """
        wanted = max(1, min(limit, JOURNAL_PAGE_CAP))
        threshold = priority_for_level(level)
        # Over-fetch when filtering, because the filter is applied here and not by journalctl.
        fetch = (
            min(wanted * _FILTER_OVERFETCH, JOURNAL_PAGE_CAP) if threshold is not None else wanted
        )
        argv = self._base_argv(units, scope=scope)
        # One extra row when resuming: `--cursor` is inclusive, so the first row of a resumed
        # page is the last row of the previous one.
        argv += ["--reverse", "-n", str(fetch + (1 if cursor else 0))]
        if cursor:
            argv += ["--cursor", cursor]
        if since:
            argv += ["--since", since]
        if until:
            argv += ["--until", until]
        if query:
            argv += ["--case-sensitive=no", "--grep", re.escape(query)]
        result = self._runner(argv, self._environment(), _HISTORY_TIMEOUT_SECONDS)
        _refuse_unreadable(result, units)
        lines = [
            line
            for line in (_decode(raw) for raw in result.stdout.splitlines())
            if line is not None
        ]
        if cursor and lines and lines[0].cursor == cursor:
            lines = lines[1:]
        # The cursor tracks the window that was *read*, so paging never skips an entry that the
        # severity filter happened to exclude on this page.
        last_read = lines[-1].cursor if len(lines) >= fetch else None
        if threshold is not None:
            lines = [line for line in lines if _NAME_TO_PRIORITY[line.level] <= threshold]
        page = tuple(lines[:wanted])
        next_cursor = (
            last_read
            if threshold is not None
            else (page[-1].cursor if len(page) == wanted else None)
        )
        return JournalPage(lines=page, next_cursor=next_cursor, capped=limit > JOURNAL_PAGE_CAP)

    @contextmanager
    def follow(
        self,
        units: Sequence[str],
        *,
        scope: Scope = "user",
        backfill: int = DEFAULT_FOLLOW_BACKFILL,
        queue_size: int = 512,
    ) -> Iterator[Subscription]:
        """Open a live tail of ``units`` as a bounded subscription.

        The subscription carries :class:`~mirrorwall.Event` objects whose ``type`` is ``log``
        (payload: one :meth:`JournalLine.as_json`) or ``log.closed`` (the reader ended). Its
        ``dropped`` count is the number of lines a slow consumer lost, which the route turns
        into the *dropped N lines* frame.

        Args:
            units: The units to tail.
            scope: ``user`` or ``system``.
            backfill: How many existing lines to open with.
            queue_size: How many undelivered lines the subscriber holds before the oldest goes.

        Yields:
            The subscription, live for the duration of the block. The process is terminated and
            the reader thread joined on the way out, whether the block left normally or not.

        Raises:
            UnitUnsupported: This host has no ``journalctl``.
            TooManyFollowers: :data:`MAX_CONCURRENT_FOLLOWS` streams are already open.
        """
        argv = self._base_argv(units, scope=scope) + ["-f", "-n", str(max(0, backfill))]
        with self._lock:
            if self._live >= MAX_CONCURRENT_FOLLOWS:
                raise TooManyFollowers(
                    f"{MAX_CONCURRENT_FOLLOWS} live log streams are already open; close one and "
                    f"try again.",
                    details={"limit": MAX_CONCURRENT_FOLLOWS},
                )
            self._live += 1
        subscription = Subscription(maxlen=queue_size)
        process: subprocess.Popen[str] | None = None
        thread: threading.Thread | None = None
        try:
            process = self._launcher(argv, self._environment())
            thread = threading.Thread(
                target=_pump,
                args=(process, subscription),
                name=f"journal-{'-'.join(units)[:32]}",
                daemon=True,
            )
            thread.start()
            yield subscription
        finally:
            if process is not None:
                _stop(process)
            if thread is not None:
                thread.join(timeout=_FOLLOW_TIMEOUT_SECONDS)
            subscription.close()
            with self._lock:
                self._live -= 1


class JournalUnreadable(SuiteError):
    """``journalctl`` ran and refused — usually a group permission on a system unit."""

    code: ClassVar[str] = "UNIT_ACTION_FAILED"


def _refuse_unreadable(result: CommandResult, units: Sequence[str]) -> None:
    """Turn a non-zero ``journalctl`` into the console's own refusal, in systemd's words."""
    if result.ok:
        return
    raise JournalUnreadable(
        f"journalctl could not read {', '.join(units) or 'the journal'}: {result.failure_text}",
        details={"units": list(units), "stderr": result.stderr.strip()},
    )


def _decode(raw: str) -> JournalLine | None:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parse_entry(decoded) if isinstance(decoded, dict) else None


def _launch_follow(argv: Sequence[str], env: Mapping[str, str]) -> subprocess.Popen[str]:
    """Start a streaming ``journalctl``; the module's one long-lived child."""
    return subprocess.Popen(  # noqa: S603 — argv list, never a shell; env is an allowlist
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=dict(env),
    )


def _pump(process: subprocess.Popen[str], subscription: Subscription) -> None:
    """Parse the child's stdout into the subscription until it ends. Runs on a worker thread."""
    sequence = 0
    stream = process.stdout
    if stream is None:  # pragma: no cover — the launcher always gives a pipe
        return
    try:
        for raw in stream:
            line = _decode(raw[:OUTPUT_CAP_BYTES])
            if line is None:
                continue
            sequence += 1
            subscription.publish(Event(sequence=sequence, type="log", payload=line.as_json()))
    except (OSError, ValueError) as exc:  # the pipe closed under us; the stream ends, not crashes
        logger.debug("journal.reader_ended", extra={"detail": str(exc)})
    finally:
        subscription.publish(
            Event(sequence=sequence + 1, type="log.closed", payload={"reason": "reader ended"})
        )


def _stop(process: subprocess.Popen[str]) -> None:
    """Terminate the follower and reap it; kill it if it will not go."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_FOLLOW_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:  # pragma: no cover — journalctl exits on SIGTERM
        process.kill()
        process.wait(timeout=_FOLLOW_TIMEOUT_SECONDS)

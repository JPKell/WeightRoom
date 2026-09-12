"""weightroom.services.telemetry — the one sampler WeightRoomGym owns, persisted and streamed.

``sweatmeter`` in process, at ``[telemetry] interval_ms`` (spec §7.7): one background thread
samples the host and its primary GPU and writes one row to ``telemetry_samples`` per tick. There
is no second sampler and telemetry is never re-collected per request — every reader (the SSE
stream, the history page, ``/system/status``) reads the same persisted rows or the same
in-memory ``latest()`` cache.

**Persist, then serve.** Unlike FreeWeight's live-only telemetry bar (this package's own
``services/telemetry.py`` docstring on that application explains why a *run's* bar can afford to
be live-only), WeightRoomGym's stream must replay from ``Last-Event-ID`` — an operator's browser
tab reconnecting after a laptop sleep expects the gap filled, not silence until the next tick.
So the pattern here is FreeWeight's own **run event store** instead: a subscriber, live or
replaying, asks the database for rows after the highest ``id`` it has already seen, on a short
poll (``services/apps.py``'s log stream and FreeWeight's ``services/events.py`` both read this
way already; nothing here invents a third style).

**Resident models are not sampled at 1 Hz.** ``resident_json`` is real — Ollama's ``/api/ps``
through ModelRack — but refreshed on its own five-second cadence
(:data:`RESIDENT_REFRESH_SECONDS`) and reused by every sample struck within that window, because
asking Ollama once a second buys nothing an operator's eye can see and costs a process-local HTTP
round trip on the sampler's own thread every tick. LoadCoach's queue depth is not persisted at
all: it is a second application's live number, carried in the SSE frame's payload (never written
to a column), so a stale queue count in telemetry history cannot outlive the connection that
showed it. **Both upstream reads are demand-driven** (:data:`READER_IDLE_SECONDS`): with no page
or stream reading, the sampler still samples the host — that is local and feeds history — but
asks Ollama and LoadCoach nothing.

**Downsampling is a sweep, not a read-time aggregation** (data model §2: "downsampled to one per
minute by the sweep"): once a row has aged past an hour, the sweep keeps the newest row in each
minute and deletes the rest, and drops anything older than ``[telemetry] history_hours``
outright. Grouped in Python rather than with a dialect-specific date-truncation function, so the
same code runs unchanged on SQLite and PostgreSQL (ADR-0006).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, cast

from baseaicore import UnsupportedPlatformError, is_supported
from mirrorwall import Event, format_frame
from setspec import GeneratorInfo
from sqlalchemy import delete, select
from sweatmeter import TelemetryCollector, TelemetrySampler
from sweatmeter.platform import NullHostReader, create_host_reader

from weightroom.__about__ import __version__
from weightroom.infrastructure.db.models import TelemetrySample
from weightroom.services.ollama import resident_models

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import httpx
    from baseaicore import Measurement
    from sqlalchemy import CursorResult
    from sweatmeter import GpuSample, TelemetrySnapshot

    from weightroom.config import Settings
    from weightroom.services.database import Database

__all__ = [
    "FIGURE_COLUMNS",
    "RESIDENT_REFRESH_SECONDS",
    "SWEEP_INTERVAL_SECONDS",
    "TelemetryService",
    "build_collector",
    "downsample_and_retain",
    "format_heartbeat",
    "history_rows",
    "read_since",
    "sample_frame",
    "sample_to_json",
    "snapshot_to_row",
    "sparkline_svg",
]

logger = logging.getLogger(__name__)

_GENERATOR = GeneratorInfo(name="weightroom", version=__version__)

RESIDENT_REFRESH_SECONDS: Final = 5.0
"""How often the sampler re-asks Ollama for residency; every other tick reuses the last answer."""

QUEUE_REFRESH_SECONDS: Final = 5.0
"""How often LoadCoach's queue depth is re-read while someone is reading it."""

READER_IDLE_SECONDS: Final = 15.0
"""How long after the last reader the sampler keeps making upstream calls.

A telemetry stream reads once per sample and a page render once, so an open tab renews this every
second; this long with no reader means no tab is open, and Ollama and LoadCoach are left alone
until one is.
"""

SWEEP_INTERVAL_SECONDS: Final = 60.0
"""How often the retention/downsampling sweep runs — once a minute is the resolution it keeps."""

_MAX_STREAM_BATCH: Final = 500
_STREAM_POLL_SECONDS: Final = 0.2

FIGURE_COLUMNS: Final[dict[str, str]] = {
    "cpu_percent": "cpu_percent",
    "cpu_temperature_c": "cpu_temperature_c",
    "ram_used_bytes": "ram_used_bytes",
    "ram_total_bytes": "ram_total_bytes",
    "gpu_utilization_percent": "gpu_utilization_percent",
    "gpu_temperature_c": "gpu_temperature_c",
    "gpu_power_watts": "gpu_power_watts",
    "gpu_vram_used_bytes": "gpu_vram_used_bytes",
    "gpu_vram_total_bytes": "gpu_vram_total_bytes",
}
"""The ``figure=`` vocabulary ``GET /system/telemetry/history`` accepts — one per column."""


def build_collector() -> TelemetryCollector:
    """Build a :class:`~sweatmeter.TelemetryCollector` for this platform.

    Degrades to :class:`~sweatmeter.platform.NullHostReader` rather than raising on a platform
    with no reader (SweatMeter spec §13's documented degrade path) — every field then reads
    honestly ``UNSUPPORTED`` instead of the console failing to start.
    """
    try:
        host = create_host_reader()
    except UnsupportedPlatformError:
        host = NullHostReader()
    return TelemetryCollector(host=host)


def _num(value: Measurement | None) -> float | None:
    """A measurement as a plain float, or ``None`` when this environment cannot supply it."""
    if value is None or not is_supported(value):
        return None
    return float(value)


def _primary_gpu(snapshot: TelemetrySnapshot) -> GpuSample | None:
    """The strip shows one GPU (index 0 by convention); a headless host has none."""
    return snapshot.gpus[0] if snapshot.gpus else None


def snapshot_to_row(
    snapshot: TelemetrySnapshot, *, interval_ms: int, resident: Sequence[dict[str, Any]] | None
) -> TelemetrySample:
    """Build the row one sample writes. Every numeric field is ``None`` where unavailable."""
    gpu = _primary_gpu(snapshot)
    return TelemetrySample(
        at=snapshot.timestamp,
        interval_ms=interval_ms,
        cpu_percent=_num(snapshot.cpu_percent),
        cpu_temperature_c=_num(snapshot.cpu_temperature_c),
        ram_used_bytes=None if (v := _num(snapshot.ram_used_bytes)) is None else int(v),
        ram_total_bytes=None if (v := _num(snapshot.ram_total_bytes)) is None else int(v),
        gpu_index=gpu.index if gpu is not None else None,
        gpu_utilization_percent=_num(gpu.utilization_percent) if gpu is not None else None,
        gpu_temperature_c=_num(gpu.temperature_c) if gpu is not None else None,
        gpu_power_watts=_num(gpu.power_watts) if gpu is not None else None,
        gpu_vram_used_bytes=(
            None if gpu is None or (v := _num(gpu.vram_used_bytes)) is None else int(v)
        ),
        gpu_vram_total_bytes=(
            None if gpu is None or (v := _num(gpu.vram_total_bytes)) is None else int(v)
        ),
        resident_json=list(resident) if resident is not None else None,
    )


def sample_to_json(row: TelemetrySample) -> dict[str, Any]:
    """Render a persisted row as the shape MirrorWall's ``telemetry.js`` consumes.

    One GPU entry when the sample carries one, none otherwise — ``telemetry.js`` already treats
    "no device at this index" as unavailable rather than zero, so an empty list is enough; no
    second sentinel is invented here.
    """
    gpus: list[dict[str, Any]] = []
    if row.gpu_index is not None:
        gpus.append(
            {
                "index": row.gpu_index,
                "utilization_percent": row.gpu_utilization_percent,
                "temperature_c": row.gpu_temperature_c,
                "power_watts": row.gpu_power_watts,
                "vram_used_bytes": row.gpu_vram_used_bytes,
                "vram_total_bytes": row.gpu_vram_total_bytes,
            }
        )
    return {
        "at": row.at.isoformat(),
        "interval_ms": row.interval_ms,
        "cpu_percent": row.cpu_percent,
        "cpu_temperature_c": row.cpu_temperature_c,
        "ram_used_bytes": row.ram_used_bytes,
        "ram_total_bytes": row.ram_total_bytes,
        "gpus": gpus,
        "unavailable_reasons": {},
        "resident": row.resident_json or [],
    }


def sample_frame(row: TelemetrySample, *, queue: dict[str, Any] | None = None) -> str:
    """One ``telemetry.sampled`` SSE frame for ``row``, ``queue`` folded in live (never stored)."""
    payload = sample_to_json(row)
    payload["queue"] = queue
    return format_frame(
        Event(sequence=row.id, type="telemetry.sampled", payload=payload), generator=_GENERATOR
    )


def format_heartbeat() -> str:
    """One SSE heartbeat comment, sent when nothing new has been sampled in a while."""
    return f": heartbeat {datetime.now(UTC).isoformat()}\n\n"


def read_since(
    database: Database, *, after_id: int, limit: int = _MAX_STREAM_BATCH
) -> list[TelemetrySample]:
    """Rows strictly after ``after_id``, ascending: the one read behind replay and the live tail."""
    with database.read() as session:
        rows = session.execute(
            select(TelemetrySample)
            .where(TelemetrySample.id > after_id)
            .order_by(TelemetrySample.id.asc())
            .limit(limit)
        ).scalars()
        return list(rows)


def history_rows(
    database: Database, *, figure: str, hours: float, now: datetime
) -> list[tuple[datetime, float | int | None]]:
    """``(at, value)`` for one figure over the ``hours`` before ``now``, already downsampled.

    ``now`` is injected: samples written at a fixed instant fall out of a window read off the real
    clock once that instant is a day old.

    Raises:
        ValueError: ``figure`` is not one of :data:`FIGURE_COLUMNS`.
    """
    if figure not in FIGURE_COLUMNS:
        message = f"{figure!r} is not a telemetry figure; the names are {sorted(FIGURE_COLUMNS)}."
        raise ValueError(message)
    column = getattr(TelemetrySample, FIGURE_COLUMNS[figure])
    cutoff = now - timedelta(hours=max(0.0, hours))
    with database.read() as session:
        rows = session.execute(
            select(TelemetrySample.at, column)
            .where(TelemetrySample.at >= cutoff)
            .order_by(TelemetrySample.at.asc())
        ).all()
        return [(at, value) for at, value in rows]


_SPARKLINE_WIDTH: Final = 640
_SPARKLINE_HEIGHT: Final = 160
_SPARKLINE_PAD: Final = 8


def sparkline_svg(rows: Sequence[tuple[datetime, float | int | None]]) -> str | None:
    """A server-rendered SVG polyline over ``rows`` — no chart library (ADR-0020 rule 5).

    Row WX6 vendored ECharts into MirrorWall (ADR-0142) and the history page now draws one
    alongside this SVG (:func:`echarts_line_option`); this function stays as that chart's
    accessible alternative (UI standards §5, §7), rendered whether or not the reader's browser
    ever draws the chart.

    Args:
        rows: ``(at, value)`` pairs, ascending; a ``None`` value is a gap in the line, never
            plotted as zero (ADR-0016).

    Returns:
        The ``<svg>...</svg>`` markup, or ``None`` when there is nothing to plot.
    """
    plottable = [(at, float(value)) for at, value in rows if value is not None]
    if not plottable:
        return None
    values = [value for _at, value in plottable]
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    inner_w = _SPARKLINE_WIDTH - 2 * _SPARKLINE_PAD
    inner_h = _SPARKLINE_HEIGHT - 2 * _SPARKLINE_PAD
    count = len(plottable)
    points = []
    for index, (_at, value) in enumerate(plottable):
        x = _SPARKLINE_PAD + (inner_w * index / (count - 1) if count > 1 else inner_w / 2)
        y = _SPARKLINE_PAD + inner_h * (1 - (value - low) / span)
        points.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(points)
    return (
        f'<svg viewBox="0 0 {_SPARKLINE_WIDTH} {_SPARKLINE_HEIGHT}" role="img" '
        f'aria-label="History from {low:g} to {high:g}" class="sparkline">'
        f'<polyline points="{polyline}" fill="none" stroke="currentColor" stroke-width="2"/>'
        f"</svg>"
    )


def echarts_line_option(
    rows: Sequence[tuple[datetime, float | int | None]], *, figure: str
) -> dict[str, Any] | None:
    """The ECharts option :func:`~weightroom.web.rendering.render`'s ``chart_container`` draws.

    Row WX6 (ADR-0142): the same data :func:`sparkline_svg` plots, reshaped for ECharts instead of
    drawn as SVG here. Colour is never in this dict — ``charts.js`` themes it from tokens at draw
    time (ADR-0020), so this function stays server-side and library-agnostic in what it returns.

    Args:
        rows: ``(at, value)`` pairs, ascending; a ``None`` value is a gap, dropped rather than
            plotted at zero (ADR-0016) — the same rule :func:`sparkline_svg` follows.
        figure: the figure's own name, used as the series label only.

    Returns:
        An ECharts option dict, or ``None`` when there is nothing to plot — the caller falls back
        to the accessible alternative alone, same as an absent SVG.
    """
    plottable = [(at, float(value)) for at, value in rows if value is not None]
    if not plottable:
        return None
    return {
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value"},
        "series": [
            {
                "name": figure,
                "type": "line",
                "showSymbol": False,
                "data": [[at.isoformat(), value] for at, value in plottable],
            }
        ],
    }


def downsample_and_retain(
    database: Database, *, history_hours: float, now: datetime | None = None
) -> int:
    """Reduce rows older than an hour to one per minute, and drop anything past ``history_hours``.

    Grouped in Python (this module's docstring) rather than a dialect-specific date-truncation
    function, so the same sweep runs on SQLite and PostgreSQL alike.

    Returns:
        How many rows were deleted.
    """
    instant = now if now is not None else datetime.now(UTC)
    retain_cutoff = instant - timedelta(hours=max(0.0, history_hours))
    downsample_cutoff = instant - timedelta(hours=1)
    deleted = 0
    with database.write() as session:
        # `rowcount` is defined on `CursorResult`, which is what a DML `session.execute()`
        # returns; the ORM-generic `Result` type mypy infers here does not carry it.
        retained = cast(
            "CursorResult[Any]",
            session.execute(delete(TelemetrySample).where(TelemetrySample.at < retain_cutoff)),
        )
        deleted += retained.rowcount or 0
        aging = session.execute(
            select(TelemetrySample.id, TelemetrySample.at)
            .where(TelemetrySample.at >= retain_cutoff, TelemetrySample.at < downsample_cutoff)
            .order_by(TelemetrySample.at.asc())
        ).all()
        keep_per_minute: dict[str, int] = {}
        for row_id, at in aging:
            minute_key = at.strftime("%Y-%m-%dT%H:%M")
            keep_per_minute[minute_key] = row_id  # last row seen in the minute wins — newest kept
        doomed = [row_id for row_id, _at in aging if row_id not in keep_per_minute.values()]
        if doomed:
            swept = cast(
                "CursorResult[Any]",
                session.execute(delete(TelemetrySample).where(TelemetrySample.id.in_(doomed))),
            )
            deleted += swept.rowcount or 0
    return deleted


@dataclass
class _ResidentCache:
    """The last Ollama residency read, reused within :data:`RESIDENT_REFRESH_SECONDS`."""

    checked_at: float = 0.0
    residents: list[dict[str, Any]] | None = None

    def get(self, settings: Settings, *, client: httpx.Client, now: float) -> list[dict[str, Any]]:
        if self.residents is not None and (now - self.checked_at) < RESIDENT_REFRESH_SECONDS:
            return self.residents
        resident, _error = resident_models(settings, client=client)
        self.residents = [entry.as_json() for entry in resident]
        self.checked_at = now
        return self.residents


class TelemetryService:
    """Owns the sampler thread, the resident cache and the retention sweep.

    Built once by the web lifespan (``app.state.telemetry``) and stopped at shutdown; every
    request reads through its ``latest()`` cache or through :func:`read_since`/:func:`history_rows`
    against the database it was given — never by triggering a fresh collection of its own.

    Args:
        database: Where samples are written.
        settings: For ``[telemetry]`` and Ollama's base URL.
        collector: The live collector; :func:`build_collector` by default.
        ollama_client: The pooled transport for the residency read, carrying Ollama's base URL
            (ADR-0123 rule 5 — ModelRack's client, never a second Ollama client written here).
        app_client: The general-purpose pooled transport ``services/apps.py`` uses to reach the
            four applications, for the one absolute-URL read of LoadCoach's queue depth.
        clock: Monotonic seconds, for the refresh and idle windows; injected by tests.
    """

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        collector: TelemetryCollector | None = None,
        ollama_client: httpx.Client | None = None,
        app_client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the sampler without starting its thread."""
        self._database = database
        self._settings = settings
        self._ollama_client = ollama_client
        self._app_client = app_client if app_client is not None else ollama_client
        self._resident_cache = _ResidentCache()
        self._queue: dict[str, Any] | None = None
        self._clock = clock
        self._queue_read_at = float("-inf")
        self._reader_at = float("-inf")
        self._sweep_lock = threading.Lock()
        self._last_sweep = 0.0
        collector = collector if collector is not None else build_collector()
        self._sampler = TelemetrySampler(
            collector,
            interval_seconds=settings.telemetry.interval_ms / 1000.0,
            on_sample=self._on_sample,
        )

    def _on_sample(self, snapshot: TelemetrySnapshot) -> None:
        now = self._clock()
        # Upstream reads happen here, on the sampler thread, and every reader shares them — they
        # used to be made per reader, five a second per open stream, until LoadCoach answered 429.
        # They are also demand-driven: the host sample below is always taken, but Ollama and
        # LoadCoach are asked nothing unless a page or stream has read within READER_IDLE_SECONDS,
        # and then at most once per refresh window each. An idle console makes no HTTP calls.
        watched = (now - self._reader_at) < READER_IDLE_SECONDS
        if not watched:
            self._queue = None
        elif (now - self._queue_read_at) >= QUEUE_REFRESH_SECONDS:
            self._queue = self._read_queue()
            self._queue_read_at = now
        resident: list[dict[str, Any]] | None = None
        if self._ollama_client is not None and watched:
            try:
                resident = self._resident_cache.get(
                    self._settings, client=self._ollama_client, now=now
                )
            except Exception:  # noqa: BLE001 — a residency hiccup never stops the sampler
                logger.warning("telemetry.resident_read_failed", exc_info=True)
        row = snapshot_to_row(
            snapshot, interval_ms=self._settings.telemetry.interval_ms, resident=resident
        )
        try:
            with self._database.write() as session:
                session.add(row)
        except Exception:  # noqa: BLE001 — a write failure degrades history, not the live tick
            logger.warning("telemetry.write_failed", exc_info=True)
        self._maybe_sweep()

    def _maybe_sweep(self) -> None:
        now = time.monotonic()
        with self._sweep_lock:
            if (now - self._last_sweep) < SWEEP_INTERVAL_SECONDS:
                return
            self._last_sweep = now
        try:
            downsample_and_retain(
                self._database, history_hours=self._settings.telemetry.history_hours
            )
        except Exception:  # noqa: BLE001 — the sweep is maintenance, not the sample itself
            logger.warning("telemetry.sweep_failed", exc_info=True)

    def start(self) -> None:
        """Start background sampling, or do nothing if already running."""
        self._sampler.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        """Stop background sampling and wait for the worker thread to exit."""
        self._sampler.stop(timeout=timeout)

    def latest(self) -> TelemetrySnapshot | None:
        """The newest live sample, or ``None`` before the first successful collection."""
        return self._sampler.latest()

    def queue_snapshot(self) -> dict[str, Any] | None:
        """LoadCoach's queue depth as of the last read — never persisted, never fetched here.

        Calling this is also how the sampler learns someone is looking: it renews the
        :data:`READER_IDLE_SECONDS` window that both upstream reads depend on.

        Returns:
            ``{"active", "depth_by_state"}`` from the latest read, or ``None`` before one, with no
            LoadCoach configured, when the last read failed, or while nobody has been reading. A
            request never triggers an upstream call of its own; the sampler makes at most one per
            :data:`QUEUE_REFRESH_SECONDS` while readers keep asking.
        """
        self._reader_at = self._clock()
        return self._queue

    def forget_queue(self) -> None:
        """Drop the last queue reading, so the next paint shows ``—`` rather than a stale figure.

        Called when the console itself drives LoadCoach's unit. The reading refreshes every
        :data:`QUEUE_REFRESH_SECONDS` on the sampler thread, so a stop made anywhere else still
        shows its last figure for up to that window — but a stop the operator has just clicked
        must not answer with the depth LoadCoach had before it (row WPF1; ``WP6_HANDOFF.md`` §4).
        """
        self._queue = None

    def peek_queue(self) -> dict[str, Any] | None:
        """The value :meth:`queue_snapshot` returns, without renewing the reader window.

        For a first paint: rendering a page is not watching it. Only an open telemetry stream keeps
        upstream reads going, so a page whose strip is hidden — and so opens no stream — costs
        Ollama and LoadCoach nothing however often it is loaded.

        Returns:
            The latest queue read, or ``None`` under the same conditions as
            :meth:`queue_snapshot`.
        """
        return self._queue

    def _read_queue(self) -> dict[str, Any] | None:
        """One read of LoadCoach's ``/system/status``, on the sampler thread."""
        if self._app_client is None:
            return None
        base_url = self._settings.apps.loadcoach.base_url
        if not base_url:
            return None
        from weightroom.services.apps import bearer_token

        headers = {}
        token = bearer_token(self._settings, "loadcoach")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self._app_client.get(
                f"{base_url.rstrip('/')}/api/v1/system/status", headers=headers, timeout=3.0
            )
            response.raise_for_status()
            body = response.json()
        except Exception:  # noqa: BLE001 — a queue read that fails renders "—", not an error page
            return None
        if not isinstance(body, dict):
            return None
        return {
            "active": body.get("active"),
            "depth_by_state": body.get("depth_by_state"),
        }

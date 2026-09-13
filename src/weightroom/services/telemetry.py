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
import math
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
    "CHART_POINTS",
    "FIGURE_COLUMNS",
    "FIGURE_SCALES",
    "RESIDENT_REFRESH_SECONDS",
    "SWEEP_INTERVAL_SECONDS",
    "FigurePanel",
    "FigureScale",
    "TelemetryService",
    "build_collector",
    "downsample_and_retain",
    "format_figure",
    "format_heartbeat",
    "history_rows",
    "read_since",
    "sample_frame",
    "sample_to_json",
    "snapshot_to_row",
    "telemetry_panels",
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


@dataclass(frozen=True, slots=True)
class FigureScale:
    """How one charted figure is named, printed and scaled on the telemetry page (row WY4).

    Attributes:
        label: The chart's and the bar's short label.
        unit: One of :func:`format_figure`'s unit names.
        low: The bottom of the value scale, and of the fill's colour ramp.
        high: The top of the scale. ``None`` takes the paired ``total`` figure and, with no total
            (or none measured), the highest sample in the window.
        total: The figure that bounds this one (RAM used by RAM total) — printed beside the
            current value, never charted on its own.
    """

    label: str
    unit: str
    low: float = 0.0
    high: float | None = None
    total: str | None = None


FIGURE_SCALES: Final[dict[str, FigureScale]] = {
    "cpu_percent": FigureScale("CPU", "percent", high=100.0),
    "ram_used_bytes": FigureScale("RAM", "bytes", total="ram_total_bytes"),
    "gpu_utilization_percent": FigureScale("GPU", "percent", high=100.0),
    "gpu_vram_used_bytes": FigureScale("VRAM", "bytes", total="gpu_vram_total_bytes"),
    # ponytail: 30–100 °C is a desktop-CPU guess (an idle floor, Tjmax as the ceiling); take the
    # sensor's own critical threshold if SweatMeter ever reports one.
    "cpu_temperature_c": FigureScale("CPU temp", "celsius", low=30.0, high=100.0),
    # ponytail: 30–95 °C is a consumer-GPU guess, 10 °C over `[alerts] gpu_temperature_c`'s 85;
    # take the card's slowdown temperature if the telemetry ever carries it.
    "gpu_temperature_c": FigureScale("GPU temp", "celsius", low=30.0, high=95.0),
    # The telemetry carries no power limit: 0 to the highest sample in the window.
    "gpu_power_watts": FigureScale("GPU power", "watts"),
}
"""Every charted figure, in page order, with its scale — the one table the page reads.

The two totals are not keys: they are values printed beside their used figure (``18.2 G / 64 G``).
"""

CHART_POINTS: Final = 240
"""The most points one small multiple is sent. A chart a quarter of a 1440 px page wide cannot
show more, and a day of samples is about 5 000 rows per figure."""

_EM_DASH: Final = "—"
_SUFFIXES: Final = ("", "K", "M", "G", "T")


def _half_up(value: float, decimals: int) -> float:
    """Round half up with the same floating-point steps as ``charts.js``'s ``roundHalfUp``."""
    scale = 10 if decimals else 1
    return math.floor(value * scale + 0.5) / scale


def _number(value: float) -> str:
    """``64.0`` as ``64`` and ``18.2`` as ``18.2`` — what JavaScript's ``String()`` prints."""
    return str(int(value)) if value == int(value) else str(value)


def _scaled(value: float, base: int, smallest: str) -> str:
    """``value`` over ``base`` until it fits, with its suffix; ``smallest`` below one ``K``."""
    index = 0
    while value >= base and index < len(_SUFFIXES) - 1:
        value /= base
        index += 1
    shown = _half_up(value, 0 if value >= 100 else 1)
    if shown >= base and index < len(_SUFFIXES) - 1:
        index += 1
        shown = _half_up(shown / base, 1)
    suffix = _SUFFIXES[index] or smallest
    return _number(shown) + (f" {suffix}" if suffix else "")


def format_figure(value: float | None, unit: str) -> str:
    """Print one telemetry value exactly as the page's JavaScript does (``mirrorwallCharts``).

    Args:
        value: The reading; ``None`` is unavailable.
        unit: ``bytes`` (binary, ``K``/``M``/``G``/``T``, ``B`` below 1 K), ``count`` (SI, the same
            suffixes), or ``percent``, ``celsius`` and ``watts`` (whole numbers). Any other unit
            prints the bare number to one decimal.

    Returns:
        The text — one decimal below 100 of a suffix, none from 100 — or ``—`` for ``None``, never
        ``0`` (ADR-0016).
    """
    if value is None:
        return _EM_DASH
    if unit == "percent":
        return f"{_number(_half_up(value, 0))}%"
    if unit == "celsius":
        return f"{_number(_half_up(value, 0))} °C"
    if unit == "watts":
        return f"{_number(_half_up(value, 0))} W"
    if unit == "bytes":
        return _scaled(value, 1024, "B")
    if unit == "count":
        return _scaled(value, 1000, "")
    return _number(_half_up(value, 1))


@dataclass(frozen=True, slots=True)
class FigurePanel:
    """One figure as the telemetry page draws it: a live bar and a small multiple.

    Attributes:
        name: The figure (a :data:`FIGURE_SCALES` key).
        label: Its short label.
        unit: Its :func:`format_figure` unit.
        low: The bottom of its scale.
        high: The top of its scale, resolved for this window.
        current: The newest sample's reading; ``None`` when that sample could not measure it.
        total: The paired total's newest measured reading, when the figure has a total.
        total_field: The paired total's name, which the live bar reads beside the figure.
        percent: ``current`` on the scale, 0–100, or ``None`` with no current reading.
        text: ``current`` printed.
        total_text: ``total`` printed when the figure has a total (``—`` if none was measured),
            otherwise ``None``.
        aria_label: The chart's accessible name: its current, minimum and maximum.
        option: The ECharts option, or ``None`` when the window holds no reading at all.
    """

    name: str
    label: str
    unit: str
    low: float
    high: float
    current: float | None
    total: float | None
    total_field: str | None
    percent: float | None
    text: str
    total_text: str | None
    aria_label: str
    option: dict[str, Any] | None


def telemetry_panels(
    database: Database, *, hours: float, now: datetime, max_points: int = CHART_POINTS
) -> list[FigurePanel]:
    """Every :data:`FIGURE_SCALES` figure over the ``hours`` before ``now``, from one read.

    One ``SELECT`` of every figure column; each series is cut from its rows — never one query per
    figure.

    Args:
        database: WeightRoomGym's own database.
        hours: The window; a negative value is an empty one.
        now: The window's end, injected like :func:`history_rows`'s.
        max_points: The most points sent per chart. Above it, time buckets keep their highest
            reading, so a spike survives the reduction.

    Returns:
        One panel per figure, in :data:`FIGURE_SCALES` order. A figure with no reading anywhere in
        the window has ``option=None`` and prints ``—``: no chart, never a flat line at zero
        (ADR-0016).
    """
    names = list(FIGURE_COLUMNS)
    columns = [getattr(TelemetrySample, FIGURE_COLUMNS[name]) for name in names]
    cutoff = now - timedelta(hours=max(0.0, hours))
    with database.read() as session:
        rows = session.execute(
            select(TelemetrySample.at, *columns)
            .where(TelemetrySample.at >= cutoff)
            .order_by(TelemetrySample.at.asc())
        ).all()
    series = {name: [(row[0], row[index + 1]) for row in rows] for index, name in enumerate(names)}
    return [
        _panel(name, scale, series, max_points=max_points) for name, scale in FIGURE_SCALES.items()
    ]


def _panel(
    name: str,
    scale: FigureScale,
    series: dict[str, list[tuple[datetime, Any]]],
    *,
    max_points: int,
) -> FigurePanel:
    """Build one figure's panel from the window's series (:func:`telemetry_panels`)."""
    points = series[name]
    values = [value for _at, value in points if value is not None]
    current = points[-1][1] if points else None
    total = None
    if scale.total is not None:
        total = next((v for _at, v in reversed(series[scale.total]) if v is not None), None)
    high = scale.high if scale.high is not None else (total or max(values, default=0.0))
    high = max(float(high), scale.low + 1.0)
    percent = None
    if current is not None:
        percent = round(min(100.0, max(0.0, (current - scale.low) / (high - scale.low) * 100)), 1)
    total_text = format_figure(total, scale.unit) if scale.total is not None else None
    option = None
    aria_label = f"{scale.label}: not measured"
    if values:
        aria_label = (
            f"{scale.label}: now {format_figure(current, scale.unit)}, "
            f"minimum {format_figure(min(values), scale.unit)}, "
            f"maximum {format_figure(max(values), scale.unit)}"
        )
        option = _chart_option(scale, high=high, data=_bucketed(points, max_points))
    return FigurePanel(
        name=name,
        label=scale.label,
        unit=scale.unit,
        low=scale.low,
        high=high,
        current=current,
        total=total,
        total_field=scale.total,
        percent=percent,
        text=format_figure(current, scale.unit),
        total_text=total_text,
        aria_label=aria_label,
        option=option,
    )


def _bucketed(points: Sequence[tuple[datetime, Any]], max_points: int) -> list[list[Any]]:
    """``[epoch_ms, value]`` pairs, at most ``max_points``; each bucket keeps its highest reading.

    A bucket whose every reading is ``None`` stays ``None`` — a gap in the line, not a zero. A
    stretch with no rows at all (the console was stopped) is joined across, not gapped.
    """

    def compact(value: float | None) -> float | None:
        return round(value, 1) if isinstance(value, float) else value

    if len(points) <= max_points:
        return [[int(at.timestamp() * 1000), compact(value)] for at, value in points]
    start = points[0][0]
    span_seconds = (points[-1][0] - start).total_seconds() or 1.0
    merged: dict[int, list[Any]] = {}
    for at, value in points:
        key = min(int((at - start).total_seconds() * max_points / span_seconds), max_points - 1)
        slot = merged.setdefault(key, [at, None])
        slot[0] = at
        if value is not None and (slot[1] is None or value > slot[1]):
            slot[1] = value
    return [[int(at.timestamp() * 1000), compact(value)] for at, value in merged.values()]


def _chart_option(scale: FigureScale, *, high: float, data: list[list[Any]]) -> dict[str, Any]:
    """A compact area chart whose fill follows its value (ADR-0147), with no colour in it.

    ``visualMap.mw_scale`` and the top-level ``mw_unit`` are MirrorWall ``charts.js`` markers: it
    colours the scale from the status tokens and prints the axis and tooltip through its formatter.
    """
    return {
        "mw_unit": scale.unit,
        "animation": False,
        "grid": {"left": 48, "right": 8, "top": 8, "bottom": 20},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "time", "splitNumber": 3, "splitLine": {"show": False}},
        "yAxis": {
            "type": "value",
            "min": scale.low,
            "max": high,
            "interval": (high - scale.low) / 2,
        },
        "visualMap": {
            "type": "continuous",
            "show": False,
            "dimension": 1,
            "min": scale.low,
            "max": high,
            "mw_scale": "load",
        },
        "series": [
            {
                "name": scale.label,
                "type": "line",
                "showSymbol": False,
                "lineStyle": {"width": 1.5},
                "areaStyle": {"opacity": 0.35},
                "data": data,
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

"""weightroom.web.routes.system — version, health, system status, telemetry (api.md §1).

``GET /version`` is the one route that answers without a session (ADR-0026 §5); ``/health``
and ``/system/status`` need one, because their component detail is operational information.

The telemetry stream reuses the replay-by-polling pattern already in this application
(``web/routes/apps.py``'s log stream) and in FreeWeight's run event store: a subscriber, live or
resuming from ``Last-Event-ID``, asks the database for rows after the highest id it has already
seen. There is no in-memory fan-out and no second sampler — every reader goes through
``app.state.telemetry``, built once by the lifespan.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from weightroom.__about__ import __version__
from weightroom.services.health import health_report, system_status
from weightroom.services.ollama import ollama_report
from weightroom.services.telemetry import (
    FIGURE_COLUMNS,
    FIGURE_SCALES,
    format_heartbeat,
    history_rows,
    read_since,
    sample_frame,
    telemetry_panels,
)
from weightroom.web.routes.apps import render_shell_page, revision_pairs, views_for_request
from weightroom.web.session import CurrentOperator, now_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["API_VERSION", "SCHEMA_VERSION", "router", "ui_router"]

ui_router = APIRouter(tags=["ui"], include_in_schema=False)

API_VERSION = "v1"
SCHEMA_VERSION = "1"

router = APIRouter(tags=["system"])

_HEARTBEAT_SECONDS = 15.0
_POLL_SECONDS = 0.2


@router.get("/version", summary="Application and API versions")
async def version() -> dict[str, str]:
    """Return the application version, the API major and the settings-schema version."""
    return {
        "application": "weightroom",
        "version": __version__,
        "api_version": API_VERSION,
        "schema_version": SCHEMA_VERSION,
    }


@router.get("/health", summary="Component health")
async def health(request: Request, principal: CurrentOperator) -> JSONResponse:
    """The health report; ``200`` for ok/degraded, ``503`` when the database is unavailable."""
    app = request.app
    report = health_report(
        app.state.settings,
        database=app.state.database,
        tls=app.state.tls,
        now=now_of(request),
        views=views_for_request(request),
    )
    return JSONResponse(
        status_code=503 if report["status"] == "unavailable" else 200, content=report
    )


def _ollama_summary(request: Request) -> dict[str, object]:
    """A trimmed Ollama view for the machine status: unit state and residency, no checklist."""
    app = request.app
    report = ollama_report(
        app.state.settings,
        controller=app.state.controller,
        client=app.state.ollama_http,
        journal=app.state.journal,
        database=app.state.database,
        residency=True,
    )
    return {
        "unit": report.unit,
        "state": report.state,
        "safe": report.safe,
        "residency": [entry.as_json() for entry in report.residency],
    }


def _telemetry_summary(request: Request) -> dict[str, object] | None:
    """The latest sample plus the live queue read, or ``None`` before the first tick."""
    from weightroom.services.telemetry import sample_to_json, snapshot_to_row

    service = getattr(request.app.state, "telemetry", None)
    if service is None:
        return None
    snapshot = service.latest()
    if snapshot is None:
        return None
    row = snapshot_to_row(
        snapshot, interval_ms=request.app.state.settings.telemetry.interval_ms, resident=None
    )
    payload = sample_to_json(row)
    payload["queue"] = service.queue_snapshot()
    return payload


@router.get("/system/status", summary="The machine view")
async def status(request: Request, principal: CurrentOperator) -> dict[str, object]:
    """Spec §17's machine view; every figure a later phase fills in is ``null`` here."""
    app = request.app
    # Each revision read may launch `<app> config show` (cached a minute) and opens a database:
    # blocking work, kept off the event loop.
    revisions = await asyncio.to_thread(revision_pairs, request)
    return system_status(
        app.state.settings,
        tls=app.state.tls,
        now=now_of(request),
        views=views_for_request(request),
        ollama=_ollama_summary(request),
        telemetry=_telemetry_summary(request),
        revisions=revisions,
    )


@router.get("/system/resident", summary="Resident models, Ollama and LoadCoach")
async def resident(request: Request, principal: CurrentOperator) -> dict[str, object]:
    """Ollama's ``/api/ps`` through ModelRack, and LoadCoach's own residency, each with its
    source.
    """
    app = request.app
    from weightroom.services.ollama import resident_models

    ollama_rows, ollama_error = resident_models(app.state.settings, client=app.state.ollama_http)
    loadcoach_rows: list[dict[str, object]] = []
    loadcoach_error: str | None = None
    base_url = app.state.settings.apps.loadcoach.base_url
    if base_url:
        from weightroom.services.apps import bearer_token

        headers = {}
        token = bearer_token(app.state.settings, "loadcoach")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = app.state.http.get(
                f"{base_url.rstrip('/')}/api/v1/system/status", headers=headers, timeout=3.0
            )
            resp.raise_for_status()
            body = resp.json()
            loadcoach_rows = list(body.get("residency") or []) if isinstance(body, dict) else []
        except Exception as exc:  # noqa: BLE001 — a stopped LoadCoach renders "—", not an error page
            loadcoach_error = f"{type(exc).__name__}: {exc}"
    else:
        loadcoach_error = "no base_url configured"
    return {
        "ollama": {
            "source": "ollama",
            "models": [m.as_json() for m in ollama_rows],
            "error": ollama_error,
        },
        "loadcoach": {"source": "loadcoach", "models": loadcoach_rows, "error": loadcoach_error},
    }


@router.get("/system/telemetry/history", summary="One figure's history")
async def telemetry_history(
    request: Request,
    principal: CurrentOperator,
    figure: Annotated[str, Query()],
    hours: Annotated[float, Query(ge=0.1, le=168.0)] = 24.0,
) -> JSONResponse:
    """Downsampled ``(at, value)`` pairs for ``figure`` over the trailing ``hours``.

    Raises:
        ValueError: propagated as a ``400`` by the app's validation handler when ``figure`` is
            not one of :data:`~weightroom.services.telemetry.FIGURE_COLUMNS`.
    """
    if figure not in FIGURE_COLUMNS:
        return JSONResponse(
            status_code=400,
            content={
                "code": "VALIDATION_ERROR",
                "message": f"{figure!r} is not a telemetry figure.",
                "details": {"figures": sorted(FIGURE_COLUMNS)},
            },
        )
    rows = history_rows(request.app.state.database, figure=figure, hours=hours, now=now_of(request))
    return JSONResponse(
        content={
            "figure": figure,
            "hours": hours,
            "samples": [{"at": at.isoformat(), "value": value} for at, value in rows],
        }
    )


def _resolve_last_id(request: Request, last_event_id: str | None) -> int:
    """Where a subscriber resumes: the header, else the query, else the beginning."""
    raw = request.headers.get("last-event-id") or last_event_id or "0"
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


async def _telemetry_frames(request: Request, *, after_id: int) -> AsyncIterator[str]:
    database = request.app.state.database
    service = getattr(request.app.state, "telemetry", None)
    last_id = after_id
    next_heartbeat = time.monotonic() + _HEARTBEAT_SECONDS
    while not await request.is_disconnected():
        batch = await asyncio.to_thread(read_since, database, after_id=last_id)
        queue = service.queue_snapshot() if service is not None and batch else None
        for row in batch:
            yield sample_frame(row, queue=queue)
            last_id = row.id
            next_heartbeat = time.monotonic() + _HEARTBEAT_SECONDS
        if not batch:
            if time.monotonic() >= next_heartbeat:
                yield format_heartbeat()
                next_heartbeat = time.monotonic() + _HEARTBEAT_SECONDS
            await asyncio.sleep(_POLL_SECONDS)


@router.get("/system/telemetry/stream", summary="Live telemetry, replayable")
async def telemetry_stream(
    request: Request,
    principal: CurrentOperator,
    last_event_id: Annotated[str | None, Query(alias="last_event_id")] = None,
) -> StreamingResponse:
    """SSE of ``telemetry.sampled`` events, resuming from ``Last-Event-ID`` within the window."""
    after = _resolve_last_id(request, last_event_id)
    return StreamingResponse(
        _telemetry_frames(request, after_id=after),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _marked_figure(figure: str | None) -> str | None:
    """The chart ``?figure=`` points at: the figure itself, or the chart its total is printed on."""
    if figure is None or figure in FIGURE_SCALES:
        return figure
    return next((name for name, scale in FIGURE_SCALES.items() if scale.total == figure), None)


@ui_router.get("/telemetry/history", summary="Every telemetry figure", response_class=HTMLResponse)
def telemetry_history_page(
    request: Request,
    principal: CurrentOperator,
    figure: str | None = None,
    hours: float = 24.0,
) -> HTMLResponse:
    """Every figure on one page: live bars over a small multiple each (row WY4).

    What clicking a strip figure opens (Phase 3 acceptance criterion 1): the strip still links
    ``?figure=<name>``, which now marks that figure's chart and scrolls to it instead of choosing
    the only one drawn. An unknown name marks nothing. One database read builds every chart
    (:func:`~weightroom.services.telemetry.telemetry_panels`); the one page that opts into
    MirrorWall's ECharts (ADR-0142).
    """
    panels = telemetry_panels(request.app.state.database, hours=hours, now=now_of(request))
    return render_shell_page(
        request,
        "telemetry_history.html",
        page="telemetry",
        principal=principal,
        panels=panels,
        marked=_marked_figure(figure),
        # ADR-0142: opt-in per page, unlike htmx's every-page default — most pages draw no chart.
        mirrorwall={"htmx": True, "echarts": True},
    )

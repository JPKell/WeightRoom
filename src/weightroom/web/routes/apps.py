"""weightroom.web.routes.apps — the four applications: state, control, health and the journal.

api.md §2. Three shapes of route live here and they are deliberately not merged:

* ``/api/v1/apps…`` — JSON, for a script and for the pages' own fetches.
* ``/apps…`` — the pages, and **one** form-post control route rather than three. A browser form
  cannot send a method other than ``GET`` or ``POST``, so the three verbs would have needed three
  paths that differ only in a word; one path with a validated ``verb`` field is the same
  guarantee with a third of the surface, and one entry in the audit-route registry.
* ``/api/v1/…/logs/stream`` — server-sent events (ADR-0004: SSE, never WebSockets).

Every state-changing route writes exactly one ``audit_log`` row, including the ones that fail:
spec §11 contract 2 is *every action*, and an action systemd refused is the one an operator most
wants to find in the trail.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal

import anyio
from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from mirrorwall import Event, format_frame
from setspec import GeneratorInfo

from weightroom.__about__ import __version__
from weightroom.config import APP_LABELS, APPLICATIONS
from weightroom.domain.units import unit_name
from weightroom.services.apps import (
    AppNotInstalled,
    AppView,
    app_health,
    inventory,
    require_app,
    unit_statuses,
    view_for,
)
from weightroom.services.audit import record
from weightroom.services.journal import (
    DEFAULT_FOLLOW_BACKFILL,
    DEFAULT_PAGE_LIMIT,
    JOURNAL_PAGE_CAP,
    JournalReader,
)
from weightroom.services.processes import UnitActionFailed, UnitUnsupported, act_and_settle
from weightroom.web.csrf import render_form_page
from weightroom.web.session import CurrentOperator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

    from weightroom.services.alerts import Banner
    from weightroom.services.app_pages import Sourced
    from weightroom.services.auth import Principal
    from weightroom.services.db_reader import AppDatabase

__all__ = [
    "CONTROL_VERBS",
    "render_shell_page",
    "revision_pairs",
    "router",
    "ui_router",
    "views_for_request",
]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["apps"])
ui_router = APIRouter(tags=["ui"], include_in_schema=False)

CONTROL_VERBS: Final[frozenset[str]] = frozenset({"start", "stop", "restart"})
"""What the console drives. ``enable``/``disable`` are the wizard's, not a button's."""

_HEARTBEAT_SECONDS: Final = 15.0
_POLL_SECONDS: Final = 0.025
"""Half of this is the median added latency per line; spec §15 budgets 50 ms end to end."""

_GENERATOR = GeneratorInfo(name="weightroom", version=__version__)


def _now() -> float:
    return time.monotonic()


def views_for_request(request: Request, *, refresh: str | None = None) -> tuple[AppView, ...]:
    """Every application as this request sees it; ``/health`` and ``/system/status`` share it."""
    state = request.app.state
    return inventory(
        state.settings,
        controller=state.controller,
        cache=state.versions,
        client=state.http,
        now=_now(),
        refresh=refresh,
    )


def _telemetry_meters(request: Request) -> list[dict[str, object]]:
    """The strip's two WeightRoomGym-specific meters: RESIDENT and QUEUE (design brief §4).

    This is only the *initial* render, for the first paint before any SSE frame has arrived;
    ``_shell.html``'s own script updates both meters live off the same
    ``/system/telemetry/stream`` connection telemetry.js already uses for the generic fields,
    matched by their label text since MirrorWall's ``meter()`` macro has no live-update hook of
    its own for a two-field, one-consumer addition (design brief §5).
    """
    from mirrorwall import bytes_human

    service = getattr(request.app.state, "telemetry", None)
    resident_text = "—"
    queue_text = "—"
    if service is not None:
        snapshot = service.latest()
        if snapshot is not None and snapshot.gpus:
            gpu = snapshot.gpus[0]
            resident_text = bytes_human(gpu.vram_used_bytes)
        queue = service.peek_queue()  # a page render is not a reader; only a stream is
        if queue is not None and queue.get("active") is not None:
            depth = queue.get("depth_by_state") or {}
            waiting = depth.get("queued") if isinstance(depth, dict) else None
            queue_text = f"{queue['active']} active" + (
                f" · {waiting} waiting" if waiting is not None else ""
            )
    return [
        {"label": "RESIDENT", "value_text": resident_text},
        {"label": "QUEUE", "value_text": queue_text},
    ]


def render_shell_page(
    request: Request,
    template_name: str,
    /,
    *,
    nav_sections: Sequence[Mapping[str, Any]] | None = None,
    nav_footer: str | None = None,
    active_app: str | None = None,
    side_nav_stubs: Sequence[Mapping[str, str]] = (),
    **context: Any,
) -> HTMLResponse:
    """Render a page inside the shell: the tabs, the strip and the left menu (design brief §4).

    Every HTML page but login, the error page and the standalone trust page goes through this —
    those three render before or outside a session and extend ``mirrorwall/base.html`` directly,
    never the shell.
    """
    from weightroom.web.rendering import CONSOLE_SIDE_NAV

    return render_form_page(
        request,
        template_name,
        views=views_for_request(request),
        active_app=active_app,
        nav_sections=nav_sections if nav_sections is not None else CONSOLE_SIDE_NAV,
        nav_footer=nav_footer,
        side_nav_stubs=side_nav_stubs,
        show_telemetry_bar=True,
        telemetry_stream_url="/api/v1/system/telemetry/stream",
        telemetry_meters=_telemetry_meters(request),
        telemetry_field_meters=("cpu", "ram", "gpu", "vram"),
        alert_banner=_alert_banner(request),
        current_path=request.url.path,
        **context,
    )


def _alert_banner(request: Request) -> Banner | None:
    """The banner's first paint (ADR-0137); ``None`` when the database cannot say — the banner
    fragment polls again five seconds later."""
    from weightroom.services.alerts import banner

    database = getattr(request.app.state, "database", None)
    if database is None:
        return None
    try:
        return banner(database)
    except Exception:  # noqa: BLE001 — a page never fails for want of its banner
        logger.warning("alerts.banner_unreadable", exc_info=True)
        return None


def _view(request: Request, app: str, *, refresh: bool = False) -> AppView:
    state = request.app.state
    statuses = unit_statuses(state.controller, [app])
    return view_for(
        state.settings,
        app,
        status=None if statuses is None else statuses.get(unit_name(app)),
        cache=state.versions,
        client=state.http,
        now=_now(),
        refresh=refresh,
    )


def app_view(request: Request, app: str) -> AppView:
    """One application as this request sees it: its unit, its version, its verdict.

    Raises:
        AppUnknown: ``app`` is not one of the four.
    """
    return _view(request, require_app(app))


def revision_pairs(
    request: Request, apps: Sequence[str] = APPLICATIONS
) -> dict[str, tuple[str | None, bool | None]]:
    """Each application's ``(alembic_version, known)``; ``(None, None)`` where it cannot be read.

    Row W7 fills api.md §2's ``db_revision`` and ``known`` with this, through the same read-only
    reader and the same minute-long URL cache the database pages use.
    """
    from weightroom.services.db_reader import revision_summary

    state = request.app.state
    pairs: dict[str, tuple[str | None, bool | None]] = {}
    for app in apps:
        revision, _reason = revision_summary(
            state.settings, state.database, app, urls=state.database_urls, now=_now()
        )
        pairs[app] = (None, None) if revision is None else (revision.found, revision.is_known)
    return pairs


def _with_revision(
    view: AppView, revisions: Mapping[str, tuple[str | None, bool | None]]
) -> dict[str, Any]:
    payload = view.as_json()
    payload["db_revision"], payload["known"] = revisions.get(view.name, (None, None))
    return payload


@router.get("/apps", summary="The four applications")
def list_apps(request: Request, principal: CurrentOperator) -> JSONResponse:
    """Each application's install, unit, version, negotiated verdict and schema revision."""
    revisions = revision_pairs(request)
    return JSONResponse(
        content={"apps": [_with_revision(view, revisions) for view in views_for_request(request)]}
    )


@router.get("/apps/{app}", summary="One application")
def get_app(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """One application's view; ``404 APP_UNKNOWN`` for a name that is not one of the four."""
    name = require_app(app)
    return JSONResponse(
        content=_with_revision(_view(request, name), revision_pairs(request, (name,)))
    )


@router.get("/apps/{app}/health", summary="The application's own health, proxied")
def get_app_health(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """The application's own ``/api/v1/health`` verbatim, with ``source`` naming who answered."""
    name = require_app(app)
    view = _view(request, name)
    return JSONResponse(
        content=app_health(request.app.state.settings, name, view, client=request.app.state.http)
    )


def _control(request: Request, principal: CurrentOperator, app: str, verb: str) -> dict[str, Any]:
    """Run one verb against one application's unit, audit it, and report the new state.

    A ``systemctl`` call that outlives the console's limit is **not** a failure: the audit row
    carries the state the unit actually reached, and the unit is still working on it while systemd
    reports ``activating``/``deactivating``, which is a ``pending`` row rather than an invented
    failure (:func:`~weightroom.services.processes.act_and_settle`, row WPF4). At row WP6 a restart
    that succeeded ninety seconds later was audited ``failed``.

    Raises:
        AppUnknown: Not one of the four.
        AppNotInstalled: No executable, so no unit to drive.
        UnitUnsupported: This host has no systemd.
        UnitActionFailed: systemd ran and refused; its own message is carried through.
    """
    name = require_app(app)
    if verb not in CONTROL_VERBS:
        message = f"{verb!r} is not a control verb; the three are {sorted(CONTROL_VERBS)}"
        raise ValueError(message)
    state = request.app.state
    unit = unit_name(name)
    before = _view(request, name)
    if not before.installed:
        raise AppNotInstalled(
            f"{name} is not installed, so it has no unit. Set [apps.{name}] executable, then "
            f"run `wr-gym units sync`.",
            details={"app": name, "unit": unit},
        )
    report = act_and_settle(state.controller, unit, verb)
    audit_id = record(
        state.database,
        action=f"unit.{verb}",
        actor="operator",
        outcome=report.outcome,
        operator_id=principal.operator_id,
        app=name,
        target=unit,
        params={"verb": verb},
        message=report.note,
        request_id=getattr(request.state, "request_id", None),
    )
    if report.outcome == "failed":
        raise UnitActionFailed(
            f"systemctl {verb} {unit} failed: {report.note}",
            details={
                "app": name,
                "unit": unit,
                "audit_id": audit_id,
                "stderr": report.result.stderr.strip(),
            },
        )
    state.versions.forget(name)
    telemetry = getattr(state, "telemetry", None)
    if name == "loadcoach" and telemetry is not None:
        # The strip's QUEUE is a reading taken before this verb ran (WP6 §4, row WPF1).
        telemetry.forget_queue()
    after = _view(request, name, refresh=False)
    return {"audit_id": audit_id, "unit": unit, "state": after.pill, "unit_state": after.unit_state}


@router.post("/apps/{app}/start", status_code=status.HTTP_202_ACCEPTED, summary="Start")
def start_app(request: Request, principal: CurrentOperator, app: str) -> dict[str, Any]:
    """``systemctl --user start <app>.service``; ``202`` with the audit id and the new state."""
    return _control(request, principal, app, "start")


@router.post("/apps/{app}/stop", status_code=status.HTTP_202_ACCEPTED, summary="Stop")
def stop_app(request: Request, principal: CurrentOperator, app: str) -> dict[str, Any]:
    """``systemctl --user stop <app>.service``."""
    return _control(request, principal, app, "stop")


@router.post("/apps/{app}/restart", status_code=status.HTTP_202_ACCEPTED, summary="Restart")
def restart_app(request: Request, principal: CurrentOperator, app: str) -> dict[str, Any]:
    """``systemctl --user restart <app>.service``."""
    return _control(request, principal, app, "restart")


@router.get("/apps/{app}/logs", summary="Journal history")
def app_logs(
    request: Request,
    principal: CurrentOperator,
    app: str,
    since: str | None = None,
    until: str | None = None,
    level: str | None = None,
    q: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> JSONResponse:
    """One page of the application's journal, newest first, capped at 5 000 rows."""
    name = require_app(app)
    reader: JournalReader = request.app.state.journal
    page = reader.history(
        [unit_name(name)],
        since=since,
        until=until,
        level=level,
        query=q,
        limit=min(limit, JOURNAL_PAGE_CAP),
        cursor=cursor,
    )
    return JSONResponse(content={"app": name, **page.as_json()})


async def _log_frames(
    reader: JournalReader, units: Sequence[str], *, backfill: int
) -> AsyncIterator[str]:
    """Replay the tail, then stream live, telling the client whenever it fell behind.

    The subscription is MirrorWall's bounded queue: it drops the **oldest** undelivered line and
    counts it. A browser that stalls therefore costs a fixed amount of memory and loses old
    lines, and is told exactly how many — a log pane with a silent hole in it is worse than one
    that says *dropped 412 lines*.
    """
    sequence = 0
    reported_drops = 0
    try:
        with reader.follow(units, backfill=backfill) as subscription:
            last_beat = time.monotonic()
            while True:
                # Checked every pass, not only when the queue drains: a producer fast enough to
                # keep the queue full is exactly the one that drops lines, and a client that
                # only heard about it once the flood stopped would have been reading a log with
                # a silent hole for the whole flood.
                dropped = subscription.dropped
                if dropped > reported_drops:
                    sequence += 1
                    yield format_frame(
                        Event(
                            sequence=sequence,
                            type="log.dropped",
                            payload={"dropped": dropped - reported_drops, "total": dropped},
                        ),
                        generator=_GENERATOR,
                    )
                    reported_drops = dropped
                event = subscription.poll()
                if event is None:
                    now = time.monotonic()
                    if now - last_beat >= _HEARTBEAT_SECONDS:
                        yield ": heartbeat\n\n"
                        last_beat = now
                    await anyio.sleep(_POLL_SECONDS)
                    continue
                sequence += 1
                yield format_frame(
                    Event(sequence=sequence, type=event.type, payload=event.payload),
                    generator=_GENERATOR,
                )
                if event.type == "log.closed":
                    return
    except UnitUnsupported as exc:
        yield format_frame(
            Event(
                sequence=sequence + 1,
                type="error",
                payload={"code": exc.code, "message": exc.message},
            ),
            generator=_GENERATOR,
        )
        # An error ends this stream as finally as `log.closed` does, and an `EventSource` cannot
        # tell either of them from a dropped connection: without a terminal frame the client
        # reconnects, this host still has no systemd, and the pair loop for as long as the page is
        # open. The client closes on `log.closed`, so an ended stream says `log.closed` — the
        # error frame above is why it ended, not the fact that it did.
        yield format_frame(
            Event(sequence=sequence + 2, type="log.closed", payload={"reason": exc.code}),
            generator=_GENERATOR,
        )


def _stream(reader: JournalReader, units: Sequence[str], *, backfill: int) -> StreamingResponse:
    return StreamingResponse(
        _log_frames(reader, units, backfill=backfill),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/apps/{app}/logs/stream", summary="Live journal, one application")
def app_log_stream(
    request: Request, principal: CurrentOperator, app: str, backfill: int = DEFAULT_FOLLOW_BACKFILL
) -> StreamingResponse:
    """SSE of one application's journal: ``log``, ``log.dropped``, ``log.closed``."""
    name = require_app(app)
    return _stream(
        request.app.state.journal, [unit_name(name)], backfill=max(0, min(backfill, 1000))
    )


@router.get("/logs/stream", summary="Live journal, several applications at once")
def unified_log_stream(
    request: Request,
    principal: CurrentOperator,
    apps: str | None = None,
    backfill: int = DEFAULT_FOLLOW_BACKFILL,
) -> StreamingResponse:
    """SSE across several units, WeightRoomGym's own included; each frame names its ``app``.

    ``apps`` is a comma-separated list; absent means all five. An unknown name is refused rather
    than silently dropped — a unified stream missing one application looks identical to one whose
    application is quiet.
    """
    wanted = [name.strip() for name in (apps or "").split(",") if name.strip()]
    chosen = wanted or [*APPLICATIONS, "weightroom"]
    for name in chosen:
        if name != "weightroom":
            require_app(name)
    return _stream(
        request.app.state.journal,
        [unit_name(name) for name in chosen],
        backfill=max(0, min(backfill, 1000)),
    )


@ui_router.get("/apps", summary="The applications page", response_class=HTMLResponse)
def apps_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Every application with its pill, uptime, version and the three buttons."""
    return render_shell_page(request, "apps.html", page="apps", principal=principal)


def render_app_page(
    request: Request,
    principal: Principal,
    app: str,
    template_name: str,
    /,
    *,
    selected: str,
    view: AppView | None = None,
    **context: Any,
) -> HTMLResponse:
    """Render a page under one application's tab: the shell, its menu, its state (row WP1).

    Every page an application's tab opens goes through this, so the tab, the two-section menu with
    ``selected`` current, the version footer and the unbuilt-page stubs are decided once. The
    template receives ``view`` and includes ``_app_state.html`` for the stopped state.

    Args:
        request: The request.
        principal: The signed-in operator.
        app: One of the four, already checked.
        template_name: The page's template.
        selected: The menu entry to mark current (spec §7.3's label: ``"Trajectories"``).
        view: The application's view when the route already read one; read here otherwise.
        **context: The page's own context.
    """
    from weightroom.web.rendering import app_side_nav, app_side_nav_stubs

    shown = view if view is not None else _view(request, app)
    return render_shell_page(
        request,
        template_name,
        page="apps",
        principal=principal,
        app=app,
        view=shown,
        active_app=app,
        nav_sections=app_side_nav(app, selected=selected),
        nav_footer=f"{APP_LABELS.get(app, app)} {shown.version or '—'}",
        side_nav_stubs=app_side_nav_stubs(app),
        **context,
    )


def read_app_page[T](
    request: Request,
    view: AppView,
    *,
    api: Callable[[], T] | None,
    database: Callable[[AppDatabase], T] | None,
) -> Sourced[T]:
    """:func:`weightroom.services.app_pages.read`, with this request's database opener bound."""
    from weightroom.services.app_pages import read
    from weightroom.services.db_reader import open_app_database

    state = request.app.state
    return read(
        view,
        api=api,
        database=database,
        open_database=lambda: open_app_database(
            state.settings, state.database, view.name, urls=state.database_urls, now=_now()
        ),
    )


@ui_router.get("/apps/{app}", summary="One application's page", response_class=HTMLResponse)
def app_page(request: Request, principal: CurrentOperator, app: str) -> HTMLResponse:
    """One application's Overview: the pill, four figures, the primary table, the log tail.

    FreeWeight's is its own page (row WX8): the Dashboard was merged into it, so it carries the
    dashboard's cards, its filters, the heatmap and the Start form as well. Dispatched here rather
    than routed separately, because ``/apps/{app}`` is declared before FreeWeight's router and a
    later ``/apps/freeweight`` would never match.
    """
    name = require_app(app)
    if name == "freeweight":
        from weightroom.web.routes.freeweight import overview as freeweight_overview

        wanted = dict(request.query_params)
        return freeweight_overview(request, principal, filters=wanted)

    from weightroom.services.overview import overview_for

    view = _view(request, name)
    overview = overview_for(
        name,
        view,
        settings=request.app.state.settings,
        database=request.app.state.database,
        client=request.app.state.http,
        urls=request.app.state.database_urls,
        now=_now(),
    )
    return render_app_page(
        request,
        principal,
        name,
        "app.html",
        selected="Overview",
        view=view,
        overview=overview,
        applications=APPLICATIONS,
    )


@ui_router.get("/apps/{app}/logs", summary="One application's journal", response_class=HTMLResponse)
def app_logs_page(
    request: Request,
    principal: CurrentOperator,
    app: str,
    since: str | None = None,
    until: str | None = None,
    level: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
) -> HTMLResponse:
    """The journal's history for one unit, filterable and paged, above its live pane."""
    from urllib.parse import urlencode

    from baseaicore import SuiteError

    from weightroom.services.journal import PRIORITY_NAMES

    name = require_app(app)
    filters = {
        "since": since or None,
        "until": until or None,
        "level": level or None,
        "q": q or None,
    }
    reader: JournalReader = request.app.state.journal
    journal = None
    error: SuiteError | None = None
    try:
        journal = reader.history(
            [unit_name(name)],
            since=filters["since"],
            until=filters["until"],
            level=filters["level"],
            query=filters["q"],
            limit=DEFAULT_PAGE_LIMIT,
            cursor=cursor or None,
        )
    except SuiteError as exc:
        error = exc
    next_href = None
    if journal is not None and journal.next_cursor:
        query = {key: value for key, value in filters.items() if value}
        next_href = f"/apps/{name}/logs?" + urlencode({**query, "cursor": journal.next_cursor})
    return render_app_page(
        request,
        principal,
        name,
        "app_logs.html",
        selected="Logs",
        journal=journal,
        error=error,
        filters=filters,
        levels=tuple(PRIORITY_NAMES[key] for key in sorted(PRIORITY_NAMES)),
        next_href=next_href,
        cap=JOURNAL_PAGE_CAP,
    )


def back_to(app: str, next_path: str | None) -> str:
    """Where the control form returns to: ``next`` when it is a page of this application's tab.

    Anything else — another application, another host, a scheme-relative ``//`` — is the Overview,
    so the field cannot become an open redirect.
    """
    home = f"/apps/{app}"
    if next_path and (next_path == home or next_path.startswith(home + "/")):
        if "//" not in next_path and "\\" not in next_path:
            return next_path
    return home


@ui_router.post("/apps/{app}/control", summary="Start, stop or restart from the page")
def control_from_page(
    request: Request,
    principal: CurrentOperator,
    app: str,
    verb: Annotated[Literal["start", "stop", "restart"], Form()],
    next_path: Annotated[str | None, Form(alias="next")] = None,
) -> Response:
    """The one form-post control route; see this module's docstring for why there is one.

    The verb is a ``Literal``, so a field outside the three is a ``400 VALIDATION_ERROR`` from
    FastAPI's own validation rather than an exception this handler has to invent a code for.
    ``next`` returns the operator to the page under this application's tab they pressed it on.
    """
    name = require_app(app)
    _control(request, principal, name, verb)
    return RedirectResponse(back_to(name, next_path), status_code=status.HTTP_303_SEE_OTHER)


@ui_router.get("/logs", summary="The unified log page", response_class=HTMLResponse)
def logs_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """One pane over every unit's journal at once."""
    return render_shell_page(
        request,
        "logs.html",
        page="logs",
        principal=principal,
        applications=[*APPLICATIONS, "weightroom"],
    )

"""weightroom.services.overview — each application's Overview page (spec §7.3, design brief §4).

The artboard's shape is one shape for all four applications: the pill (already ``AppView``'s),
four figures, a primary table, a live log tail. What differs is *where the figures and the table
come from*, and spec §7.3 draws the same line for every application: the API when it is running
and reachable, the database when it is not, ``—`` when neither answers.

**The primary table always reads the application's own database directly**, running or not —
the one deliberate narrowing this row makes against the letter of §7.3's per-application source
column (which reads as API-when-up for "the listing" too). Two things pushed that way. First,
spec §10 and the data model's own cross-reference table (§4) already list "database" as a
legitimate read path for every application, not one reserved for the stopped case — the
narrower reading in §7.3 is about the *figures*, which do need a live number a static row
cannot give (a queue depth, an open circuit breaker), not about a *listing*, which a database
already answers exactly. Second, and decisively: each application's list endpoint has its own
JSON shape that would need reading and pinning per application before this page could render a
row of it, while every application already exposes the one shape every row here needs —
``alembic_version`` and a handful of named tables (data model §4) — through the read-only
connection this module already opens for the stopped case. Building the per-application list
parsers is real work with no shortcut, and this row's job is the shell and the strip, not a
fifth database reader per application; W7's guarded database viewer is where a *browsable* table
belongs, and this Overview table is content to be a read of the same rows, once.

Figures differ: they are read from ``GET /api/v1/system/status`` (one call, already built by
every application) when the application answers, and from ``COUNT(*)`` over the same named
tables the primary table reads when it does not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import func, select

from weightroom.services.apps import bearer_token
from weightroom.services.database import Database
from weightroom.services.db_reader import (
    effective_database_url,
    known_revision,
    open_read_only,
    read_revision,
    reflect_table,
)

if TYPE_CHECKING:
    import httpx

    from weightroom.config import Settings
    from weightroom.services.apps import AppView
    from weightroom.services.db_reader import DatabaseUrlCache

__all__ = ["Figure", "Overview", "OverviewTable", "overview_for"]

logger = logging.getLogger(__name__)

_STATUS_TIMEOUT_SECONDS: Final = 3.0
_TABLE_ROW_LIMIT: Final = 10
_TABLE_COLUMN_LIMIT: Final = 6

_PRIMARY_TABLE: Final[dict[str, str]] = {
    "freeweight": "models",
    "loadcoach": "models",
    "ideapress": "projects",
    "promptcadence": "trajectories",
}

_FIGURE_TABLES: Final[dict[str, tuple[str, ...]]] = {
    "freeweight": ("models", "runs", "capability_evidence"),
    "loadcoach": ("models", "jobs", "routing_decisions"),
    "ideapress": ("projects", "units", "stage_runs"),
    "promptcadence": ("trajectories", "approval_requests", "turns"),
}
"""The tables each application's stopped-state figures fall back to counting (data model §4)."""

_STATUS_FIGURES: Final[dict[str, tuple[tuple[str, tuple[str, ...], str], ...]]] = {
    # label -> a dotted path into GET /system/status's own body, and how to show what it holds:
    # `value` as it is, `bytes` humanised, `count` a list's length, `count:<state>` the list's
    # entries whose `state` is that word. Pinned against each application's recorded body
    # (tests/fixtures/status, row WP2).
    "freeweight": (
        ("Active run", ("active_run",), "value"),
        ("Queue depth", ("queue_depth",), "value"),
        ("Disk headroom", ("disk_headroom_bytes",), "bytes"),
    ),
    "loadcoach": (
        ("Active", ("active",), "value"),
        ("Oldest queued", ("oldest_queued_age_seconds",), "value"),
        ("Starving", ("starving",), "value"),
    ),
    "ideapress": (
        ("Active stage runs", ("active_stage_runs",), "count"),
        ("Backend", ("backend_mode",), "value"),
        ("Pinned", ("pinned",), "value"),
    ),
    "promptcadence": (
        ("Executing", ("active_trajectories",), "count:executing"),
        ("Planning", ("active_trajectories",), "count:planning"),
        ("Pending approvals", ("pending_approvals",), "count"),
    ),
}
"""The field each figure reads off each application's own status body; an absent key, or a value
that is not the shape its figure counts, is a figure nobody can read, not a zero (ADR-0016) — it
renders ``—``."""


@dataclass(frozen=True, slots=True)
class Figure:
    """One of the Overview's four cards."""

    label: str
    value: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class OverviewTable:
    """The primary table: a caption, its columns, and up to :data:`_TABLE_ROW_LIMIT` rows."""

    caption: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    empty_message: str | None = None

    def columns_for_table_macro(self) -> tuple[dict[str, str], ...]:
        """``columns`` in the shape MirrorWall's ``table()`` macro takes (spec §4)."""
        return tuple({"label": name} for name in self.columns)


@dataclass(frozen=True, slots=True)
class Overview:
    """Everything the Overview page renders beyond the pill, which is already ``AppView``'s."""

    source: str
    """``"api"``, ``"database"`` or ``"none"`` — the footer names it (spec §7.3)."""
    source_detail: str
    figures: tuple[Figure, ...]
    table: OverviewTable
    promptcadence_figures: tuple[Figure, ...] = ()
    """Row WX11: Active, Pending approvals and Spending today — PromptCadence-only, read from the
    same ``/system/status`` body ``figures`` already fetched (which embeds its own
    ``ledger_view()`` under ``"ledger"``, the same document ``GET /ledger`` answers), so this adds
    no second call. Empty for the other three applications and whenever PromptCadence did not
    answer."""


def _dash_figures(app: str) -> tuple[Figure, ...]:
    return tuple(
        Figure(label=label, value="—") for label, _path, _how in _STATUS_FIGURES.get(app, ())
    )


def _empty_table(app: str, *, message: str) -> OverviewTable:
    return OverviewTable(
        caption=_PRIMARY_TABLE.get(app, app), columns=(), rows=(), empty_message=message
    )


def _dig(body: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = body
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _shown(value: Any, how: str) -> str:  # noqa: ANN401 — whatever the status body holds
    """One figure's text, by :data:`_STATUS_FIGURES`' rule; ``—`` for anything else."""
    from mirrorwall import bytes_human

    if how.startswith("count"):
        if not isinstance(value, list):
            return "—"
        _, _, state = how.partition(":")
        return str(
            sum(
                1
                for one in value
                if not state or (isinstance(one, dict) and one.get("state") == state)
            )
        )
    if value is None:
        return "—"
    if how == "bytes" and isinstance(value, int) and not isinstance(value, bool):
        return str(bytes_human(value))
    return str(value)


def _figures_from_status(app: str, body: dict[str, Any]) -> tuple[Figure, ...]:
    return tuple(
        Figure(label=label, value=_shown(_dig(body, path), how))
        for label, path, how in _STATUS_FIGURES.get(app, ())
    )


def _promptcadence_figures(body: dict[str, Any]) -> tuple[Figure, ...]:
    """Row WX11's PromptCadence-only section: Active, Pending approvals, Spending today.

    ``body`` is the same ``GET /system/status`` document ``_figures_from_status`` already read;
    its ``ledger`` key is ``runtime.budget.ledger_view(trajectory=None).as_json()``, the same
    method ``GET /ledger`` calls, so the per-day headroom here is not re-derived (ADR-0030).
    """
    active = body.get("active_trajectories")
    pending = body.get("pending_approvals")
    day = _dig(body, ("ledger", "day"))
    display = day.get("money_remaining_display") if isinstance(day, dict) else None
    return (
        Figure(label="Active", value=str(len(active)) if isinstance(active, list) else "—"),
        Figure(
            label="Pending approvals",
            value=str(len(pending)) if isinstance(pending, list) else "—",
        ),
        Figure(
            label="Spending today",
            value=str(display) if display is not None else "—",
            note="ceiling exceeded" if isinstance(day, dict) and day.get("exceeded") else None,
        ),
    )


def _fetch_status(
    settings: Settings, app: str, view: AppView, *, client: httpx.Client
) -> dict[str, Any] | None:
    headers = {}
    token = bearer_token(settings, app)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = client.get(
            f"{view.base_url.rstrip('/')}/api/v1/system/status",
            headers=headers,
            timeout=_STATUS_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:  # noqa: BLE001 — a status call that fails degrades to "—", not an error page
        logger.info("overview.status_unreachable", extra={"app": app})
        return None
    return body if isinstance(body, dict) else None


def _figures_from_database(engine: Any, app: str) -> tuple[Figure, ...]:  # noqa: ANN401
    figures = []
    for name in _FIGURE_TABLES.get(app, ()):
        table = reflect_table(engine, name)
        count: int | None = None
        if table is not None:
            try:
                with engine.connect() as connection:
                    count = connection.execute(select(func.count()).select_from(table)).scalar_one()
            except Exception:  # noqa: BLE001 — a table this build cannot read renders "—"
                count = None
        figures.append(
            Figure(label=name.replace("_", " ").title(), value="—" if count is None else str(count))
        )
    return tuple(figures)


def _table_from_database(engine: Any, app: str) -> OverviewTable:  # noqa: ANN401
    name = _PRIMARY_TABLE.get(app, app)
    table = reflect_table(engine, name)
    if table is None:
        return _empty_table(app, message=f"{name} is not a table this build knows how to read.")
    order_columns = list(table.primary_key.columns)
    statement = select(table)
    if order_columns:
        statement = statement.order_by(order_columns[0].desc())
    statement = statement.limit(_TABLE_ROW_LIMIT)
    columns = tuple(column.name for column in table.columns)[:_TABLE_COLUMN_LIMIT]
    try:
        with engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
    except Exception:  # noqa: BLE001 — an unreadable table renders as empty, not a crash
        return _empty_table(app, message=f"{name} could not be read.")
    return OverviewTable(
        caption=name,
        columns=columns,
        rows=tuple(tuple("—" if row[c] is None else str(row[c]) for c in columns) for row in rows),
        empty_message=None if rows else f"No rows in {name} yet.",
    )


def overview_for(
    app: str,
    view: AppView,
    *,
    settings: Settings,
    database: Database,
    client: httpx.Client,
    urls: DatabaseUrlCache,
    now: float,
) -> Overview:
    """Build one application's Overview: figures, the primary table, and where they came from.

    Args:
        app: One of the four applications.
        view: Its current :class:`~weightroom.services.apps.AppView`.
        settings: The validated settings.
        database: WeightRoomGym's own database, for the :data:`known_revisions <KnownRevision>`
            check (ADR-0123 rule 3).
        client: The pooled HTTP client for the application's own ``/system/status``.
        urls: The URL cache every other database-reading page already goes through — ``config
            show --json`` is a process launch of about 0.5 s, and this page paid it on every
            render until row WPF6.
        now: A monotonic clock reading, for the cache.

    Returns:
        The Overview. Never raises: every failure path renders ``—`` or an empty table instead.
    """
    figures: tuple[Figure, ...]
    # `figures_from_api` is only true of a *successful* call — it drives both which branch fills
    # the figures below and how the footer is worded. `figures_resolved` is broader: also true
    # when the application is running and reachable but its status call failed, so that case
    # renders dashes (the API is the only source running/reachable implies) rather than quietly
    # substituting the database's numbers for what the application itself could not answer.
    promptcadence_figures: tuple[Figure, ...] = ()
    if view.running and view.reachable:
        body = _fetch_status(settings, app, view, client=client)
        figures_from_api = body is not None
        figures_resolved = True
        figures = _dash_figures(app) if body is None else _figures_from_status(app, body)
        if app == "promptcadence" and body is not None:
            promptcadence_figures = _promptcadence_figures(body)
    else:
        figures_from_api = False
        figures_resolved = False
        figures = ()  # filled from the database below, or left dashed if that fails too

    database_url, database_error = urls.get(
        app, now=now, read=lambda: effective_database_url(settings, app)
    )
    if database_url is None:
        table = _empty_table(app, message=f"No database reachable: {database_error}.")
        if not figures_resolved:
            figures = _dash_figures(app)
        return Overview(
            *_compose(figures_from_api, table_phrase=f"unavailable: {database_error}"),
            figures=figures,
            table=table,
            promptcadence_figures=promptcadence_figures,
        )

    # Read-only, like every connection to another application's database (ADR-0124).
    other = open_read_only(database_url)
    try:
        revision = read_revision(other)
        known = known_revision(database, app, revision)
        if revision is not None and not known:
            table = _empty_table(
                app,
                message=(
                    f"Schema at revision {revision} is not known to WeightRoomGym — its "
                    "database-sourced pages degrade by name; API-sourced figures are unaffected."
                ),
            )
            table_phrase = f"schema at revision {revision} is not known"
        else:
            table = _table_from_database(other, app)
            table_phrase = f"the database at revision {revision}"
        figures_from_database = known and not figures_resolved
        if not figures_resolved:
            figures = _figures_from_database(other, app) if known else _dash_figures(app)
    finally:
        other.dispose()
    return Overview(
        *_compose(
            figures_from_api, table_phrase=table_phrase, figures_from_database=figures_from_database
        ),
        figures=figures,
        table=table,
        promptcadence_figures=promptcadence_figures,
    )


def _compose(
    figures_from_api: bool, *, table_phrase: str, figures_from_database: bool = False
) -> tuple[str, str]:
    """The ``(source, source_detail)`` pair, naming both halves when they actually differ.

    The primary table is always database-sourced (this module's docstring); the figures are not,
    so a running application's footer says which is which rather than the single word "api"
    implying the table came from there too. ``table_phrase`` is a complete clause on its own
    ("the database at revision 15", "schema at revision 9999 is not known",
    "unavailable: exited 1") so it reads correctly both standalone and after "table:".
    """
    if figures_from_api:
        detail = f"figures from the API; table: {table_phrase}"
    elif figures_from_database:
        detail = f"from {table_phrase}"
    else:
        detail = table_phrase
    # Sentence-cased here, not with Jinja's `capitalize` filter, which lowercases the rest of
    # the string too and would turn "API" into "api".
    return (
        "api" if figures_from_api else "database" if figures_from_database else "none",
        detail[:1].upper() + detail[1:],
    )

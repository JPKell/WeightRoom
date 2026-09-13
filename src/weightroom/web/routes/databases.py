"""weightroom.web.routes.databases — each application's database, read, curated and guarded.

Row W7 (spec §7.8, api.md §3). **Reading**: the revision against ``known_revisions``, the tables
with their counts and locks, a page of rows, the SQL console. Every read opens the application's
database read-only for the length of the request (``services/db_reader.py``); an unknown revision
is ``409 SCHEMA_UNKNOWN`` in JSON and a page that says so by name in HTML (ADR-0123 rule 3).
**Curated operations** run the application's own ``db`` verbs and are listed first
(``services/db_curated.py``). **The guard** is the rolled-back dry run and the write under
ADR-0124's five conditions (``services/db_guard.py``); on a table's page it is a form that shows
the dry run's count, what the foreign keys reach and the five verdicts, and then asks for the typed
names and the password.

Every ``POST`` here leaves exactly one audit row whatever happens to it — ``db.query``,
``db.dry_run``, ``db.guarded_write`` or ``db.curated`` (spec §11 contract 2).

An application's database is three pages behind one page bar (row WY9): Tables (``…/database``),
Query (``…/database/query``) and Admin (``…/database/admin``, the curated operations, the delete
preview and the backups). Each ``POST`` renders back onto the page it belongs to.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Annotated, Any, Final
from urllib.parse import quote, urlencode

from baseaicore import SuiteError
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from weightroom.config import APPLICATIONS
from weightroom.domain.guard import GuardDryRunFailed, GuardStatementRefused, lock_for
from weightroom.domain.units import UNIT_APPLICATIONS
from weightroom.services.apps import require_app
from weightroom.services.audit import record
from weightroom.services.auth import Principal, require_fresh_reauth
from weightroom.services.database import postgres_bootstrap_script
from weightroom.services.db_curated import (
    RESULTS_DELETION,
    TABLE_OPERATIONS,
    CuratedResult,
    delete_results,
    run_curated,
    verbs_for,
)
from weightroom.services.db_guard import (
    DryRun,
    WriteResult,
    dry_run,
    guarded_write,
    list_backups,
)
from weightroom.services.db_reader import (
    CONSOLE_ROW_CAP,
    AppDatabase,
    AppDatabaseUnavailable,
    QueryResult,
    ReadFailed,
    SchemaUnknown,
    list_tables,
    open_app_database,
    revision_summary,
    run_query,
    table_page,
)
from weightroom.services.freeweight_pages import database_stats_api
from weightroom.services.settings_forms import config_file_path, read_schema_document
from weightroom.web.routes.apps import app_view, render_shell_page
from weightroom.web.session import CurrentOperator, now_of, reauthenticated

__all__ = ["open_for", "router", "ui_router"]

router = APIRouter(tags=["databases"])
ui_router = APIRouter(tags=["ui"], include_in_schema=False)

_SQL_MAX_CHARS: Final = 100_000
_NAME_MAX_CHARS: Final = 4096


class QueryBody(BaseModel):
    """``POST …/db/query`` and ``POST …/db/write/dry-run``: one statement."""

    model_config = ConfigDict(extra="forbid")

    sql: str = Field(max_length=_SQL_MAX_CHARS)


class WriteBody(BaseModel):
    """``POST …/db/write`` (api.md §3).

    No re-authentication field: the window is the session's, opened by ``POST /reauth`` (row W4).
    """

    model_config = ConfigDict(extra="forbid")

    sql: str = Field(max_length=_SQL_MAX_CHARS)
    tables_typed: list[str] = Field(default_factory=list, max_length=64)
    dry_run_id: str = Field(default="", max_length=64)


class RestoreBody(BaseModel):
    """``POST …/db/restore`` (api.md §3)."""

    model_config = ConfigDict(extra="forbid")

    file: str = Field(max_length=_NAME_MAX_CHARS)
    name_typed: str = Field(default="", max_length=64)


class DeleteResultsBody(BaseModel):
    """``POST …/db/delete-results`` (api.md §3): preview without ``token``, then the deletion."""

    model_config = ConfigDict(extra="forbid")

    scope: str = Field(max_length=16)
    selector: str = Field(default="", max_length=_NAME_MAX_CHARS)
    token: str = Field(default="", max_length=_NAME_MAX_CHARS)
    typed: str = Field(default="", max_length=_NAME_MAX_CHARS)


def open_for(request: Request, app: str, *, require_known: bool = True) -> AppDatabase:
    """The application's database, read-only, for this request; the caller closes it."""
    state = request.app.state
    return open_app_database(
        state.settings,
        state.database,
        app,
        urls=state.database_urls,
        now=time.monotonic(),
        require_known=require_known,
    )


def _audit(
    request: Request,
    principal: Principal,
    app: str,
    action: str,
    *,
    outcome: str,
    **fields: Any,
) -> None:
    record(
        request.app.state.database,
        action=action,
        actor="operator",
        outcome=outcome,
        now=now_of(request),
        operator_id=principal.operator_id,
        app=app,
        request_id=getattr(request.state, "request_id", None),
        **fields,
    )


def _message(exc: BaseException) -> str:
    return str(getattr(exc, "message", None) or exc)


def _audited_query(request: Request, principal: Principal, app: str, sql: str) -> QueryResult:
    """Run one console statement and leave exactly one ``db.query`` row, refused or not."""
    try:
        with open_for(request, app) as handle:
            result = run_query(handle, sql)
    except Exception as exc:
        refused = isinstance(exc, (GuardStatementRefused, SchemaUnknown))
        outcome = "refused" if refused else "failed"
        _audit(
            request,
            principal,
            app,
            "db.query",
            outcome=outcome,
            message=_message(exc),
            statement=sql,
        )
        raise
    _audit(
        request,
        principal,
        app,
        "db.query",
        outcome="ok",
        target=", ".join(result.statement.tables) or None,
        params={"rows": len(result.rows), "truncated": result.truncated},
        statement=sql,
    )
    return result


def _audited_dry_run(request: Request, principal: Principal, app: str, sql: str) -> DryRun:
    """One ``db.dry_run`` row: ``ok`` when it counted, ``refused`` when refused or while the
    application runs (nothing ran), ``failed`` when the rolled-back statement errored."""
    state = request.app.state
    try:
        dry = dry_run(
            state.settings,
            state.database,
            state.controller,
            app,
            sql,
            urls=state.database_urls,
            monotonic=time.monotonic(),
        )
    except Exception as exc:
        failed = isinstance(exc, GuardDryRunFailed) or not isinstance(exc, SuiteError)
        _audit(
            request,
            principal,
            app,
            "db.dry_run",
            outcome="failed" if failed else "refused",
            message=_message(exc),
            params={"code": getattr(exc, "code", None)},
            statement=sql,
        )
        raise
    counted = dry.counts is not None
    _audit(
        request,
        principal,
        app,
        "db.dry_run",
        outcome="ok" if counted else "refused",
        target=", ".join(dry.tables) or None,
        params={
            "unit_state": dry.observation.unit_state,
            "port_open": dry.observation.port_open,
            "reached": {} if dry.counts is None else dry.counts.changes,
        },
        message=None if counted else f"{app} is not stopped ({dry.observation.evidence}).",
        statement=sql,
        dry_run_count=None if dry.counts is None else dry.counts.rows,
    )
    return dry


def _write(
    request: Request,
    principal: Principal,
    app: str,
    sql: str,
    tables_typed: tuple[str, ...] | list[str],
    identifier: str,
) -> WriteResult:
    """The guarded write, re-authentication included; ``services/db_guard.py`` audits it."""
    state = request.app.state
    now = now_of(request)

    def authorise() -> None:
        require_fresh_reauth(principal, now=now, auth=state.settings.auth)

    return guarded_write(
        state.settings,
        state.database,
        state.controller,
        app,
        sql,
        tables_typed=tuple(tables_typed),
        dry_run_id=identifier,
        operator_id=principal.operator_id,
        urls=state.database_urls,
        now=now,
        monotonic=time.monotonic(),
        authorise=authorise,
        request_id=getattr(request.state, "request_id", None),
    )


def _audited_curated(
    request: Request,
    principal: Principal,
    app: str,
    verb: str,
    *,
    source: str = "",
    name_typed: str = "",
    scope: str = "",
    selector: str = "",
    token: str = "",
) -> CuratedResult:
    """One of the application's own operations, and one ``db.curated`` row for it.

    ``delete-results`` is FreeWeight's deletion over its API (ADR-0134 rule 2): the preview
    without ``token``; with it the deletion, typed in ``name_typed``, re-authenticated and marked
    ``security``. Every other verb is the application's ``db`` CLI; ``restore`` re-authenticates.
    """
    state = request.app.state
    deleting = verb == "delete-results"
    security = verb == "restore" or (deleting and bool(token))
    params: dict[str, Any] = (
        {"verb": verb, "scope": scope, "selector": selector}
        if deleting
        else {"verb": verb, "source": source}
    )
    try:
        if security:
            require_fresh_reauth(principal, now=now_of(request), auth=state.settings.auth)
        if deleting:
            result = delete_results(
                state.settings,
                state.http,
                app,
                scope=scope,
                selector=selector,
                token=token,
                typed=name_typed,
            )
        else:
            result = run_curated(
                state.settings, state.controller, app, verb, source=source, name_typed=name_typed
            )
    except SuiteError as exc:
        _audit(
            request,
            principal,
            app,
            "db.curated",
            outcome="refused",
            target=verb,
            params=params,
            message=exc.message,
            security=security,
        )
        raise
    answer = result.output if deleting and isinstance(result.output, dict) else {}
    if answer:
        params |= {"run_count": answer.get("run_count"), "total_rows": answer.get("total_rows")}
    _audit(
        request,
        principal,
        app,
        "db.curated",
        outcome="ok" if result.ok else "failed",
        target=result.verb,
        params={**params, "argv": list(result.argv)},
        message=result.error,
        security=security,
        backup_path=answer.get("backup_path"),
    )
    return result


# --- JSON: reading ------------------------------------------------------------------------------


@router.get("/apps/{app}/db/revision", summary="The schema revision against known_revisions")
def get_revision(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """``alembic_version``, whether this console knows it, and the revisions it does."""
    with open_for(request, require_app(app), require_known=False) as handle:
        return JSONResponse(content=handle.revision.as_json())


@router.get("/apps/{app}/db/tables", summary="Tables, row counts and locks")
def get_tables(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """Every table with its count, ``writable`` and, when locked, ``reason``."""
    with open_for(request, require_app(app)) as handle:
        tables = list_tables(handle)
        return JSONResponse(
            content={
                "revision": handle.revision.as_json(),
                "tables": [one.as_json() for one in tables],
            }
        )


@router.get("/apps/{app}/db/tables/{table}", summary="A page of rows, columns typed")
def get_rows(
    request: Request,
    principal: CurrentOperator,
    app: str,
    table: str,
    page: int = 1,
    sort: str | None = None,
    desc: bool = False,
    column: str | None = None,
    filter_text: Annotated[str | None, Query(alias="filter")] = None,
) -> JSONResponse:
    """One page of ``table``, sorted by ``sort`` (the primary key otherwise), filtered by
    ``column`` containing ``filter``."""
    with open_for(request, require_app(app)) as handle:
        grid = table_page(
            handle,
            table,
            page=page,
            sort=sort or None,
            descending=desc,
            column_name=column or None,
            contains=filter_text or None,
        )
        return JSONResponse(content=grid.as_json())


@router.post("/apps/{app}/db/query", summary="One SELECT on a read-only connection")
def post_query(
    request: Request, principal: CurrentOperator, app: str, body: QueryBody
) -> JSONResponse:
    """30 s, 10 000 rows; anything but one ``SELECT`` is ``GUARD_STATEMENT_REFUSED``."""
    result = _audited_query(request, principal, require_app(app), body.sql)
    return JSONResponse(content=result.as_json())


# --- JSON: the guard ----------------------------------------------------------------------------


@router.post("/apps/{app}/db/write/dry-run", summary="The guard's dry run, rolled back")
def post_dry_run(
    request: Request, principal: CurrentOperator, app: str, body: QueryBody
) -> JSONResponse:
    """The statement echoed, the tables it names, what its foreign keys reach, the rolled-back
    count once the application is stopped, and the five conditions' verdicts."""
    dry = _audited_dry_run(request, principal, require_app(app), body.sql)
    return JSONResponse(content=dry.as_json())


@router.post("/apps/{app}/db/write", summary="A raw write under ADR-0124's five conditions")
def post_write(
    request: Request, principal: CurrentOperator, app: str, body: WriteBody
) -> JSONResponse:
    """``GUARD_*`` naming the condition that failed, or the audit id, the backup and the count."""
    result = _write(
        request, principal, require_app(app), body.sql, body.tables_typed, body.dry_run_id
    )
    return JSONResponse(content=result.as_json())


# --- JSON: curated operations -------------------------------------------------------------------


@router.get("/apps/{app}/db/status", summary="The application's own db status")
def get_db_status(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """``<app> db status --json``, as the application printed it."""
    state = request.app.state
    result = run_curated(state.settings, state.controller, require_app(app), "status")
    return JSONResponse(content=result.as_json())


@router.get("/apps/{app}/db/backups", summary="The guarded-write backups of this database")
def get_backups(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """Every backup a guarded write took, newest first."""
    backups = list_backups(require_app(app))
    return JSONResponse(content={"backups": [one.as_json() for one in backups]})


@router.post("/apps/{app}/db/backup", summary="The application's own db backup")
def post_backup(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """``<app> db backup``; ``ok`` false with the application's words when it failed."""
    return JSONResponse(
        content=_audited_curated(request, principal, require_app(app), "backup").as_json()
    )


@router.post("/apps/{app}/db/upgrade", summary="The application's own db upgrade")
def post_upgrade(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """``<app> db upgrade``, which takes its own backup first."""
    return JSONResponse(
        content=_audited_curated(request, principal, require_app(app), "upgrade").as_json()
    )


@router.post("/apps/{app}/db/restore", summary="The application's own db restore")
def post_restore(
    request: Request, principal: CurrentOperator, app: str, body: RestoreBody
) -> JSONResponse:
    """``<app> db restore --yes FILE`` with the unit stopped, the name typed, re-authenticated."""
    result = _audited_curated(
        request,
        principal,
        require_app(app),
        "restore",
        source=body.file,
        name_typed=body.name_typed,
    )
    return JSONResponse(content=result.as_json())


@router.post(
    "/apps/{app}/db/delete-results", summary="The application's own deletion of stored results"
)
def post_delete_results(
    request: Request, principal: CurrentOperator, app: str, body: DeleteResultsBody
) -> JSONResponse:
    """FreeWeight's preview without ``token``; with it, typed and re-authenticated, the deletion."""
    result = _audited_curated(
        request,
        principal,
        require_app(app),
        "delete-results",
        name_typed=body.typed,
        scope=body.scope,
        selector=body.selector,
        token=body.token,
    )
    return JSONResponse(content=result.as_json())


# --- Pages ------------------------------------------------------------------------------------


def _page(
    request: Request,
    principal: Principal,
    app: str,
    template: str,
    /,
    **context: Any,
) -> HTMLResponse:
    from weightroom.web.rendering import app_side_nav, app_side_nav_stubs

    return render_shell_page(
        request,
        template,
        page="apps",
        principal=principal,
        app=app,
        active_app=app,
        nav_sections=app_side_nav(app, selected="Database"),
        side_nav_stubs=app_side_nav_stubs(app),
        row_cap=CONSOLE_ROW_CAP,
        **context,
    )


def _tables_context(request: Request, app: str) -> dict[str, Any]:
    """The revision and the tables, or why there are none — never an error page."""
    try:
        with open_for(request, app, require_known=False) as handle:
            tables = list_tables(handle) if handle.revision.is_known else ()
            return {"revision": handle.revision, "tables": tables, "unavailable": None}
    except AppDatabaseUnavailable as exc:
        return {"revision": None, "tables": (), "unavailable": exc.message}


def _application_stats(request: Request, app: str) -> dict[str, Any]:
    """FreeWeight's own ``GET /database/stats`` while it answers (row WP3).

    It adds what ``freeweight db status`` does not report — the backups taken and the artifacts
    beside the database — so the page shows FreeWeight's own figures for them rather than none.
    The other applications serve no such route, and a stopped FreeWeight is not called.
    """
    empty: dict[str, Any] = {"app_stats": None, "app_stats_error": None}
    if app != "freeweight":
        return empty
    view = app_view(request, app)
    if not (view.running and view.reachable):
        return empty
    try:
        stats = database_stats_api(request.app.state.http, request.app.state.settings)
    except SuiteError as exc:
        return {"app_stats": None, "app_stats_error": exc}
    return {"app_stats": stats, "app_stats_error": None}


def _database_page(
    request: Request, principal: Principal, app: str, template: str, /, **extra: Any
) -> HTMLResponse:
    context: dict[str, Any] = {
        "sql": "",
        "result": None,
        "query_error": None,
        "curated": None,
        "curated_error": None,
        **extra,
    }
    return _page(
        request,
        principal,
        app,
        template,
        verbs=verbs_for(app),
        deletion_scopes=RESULTS_DELETION.get(app, ()),
        backups=list_backups(app),
        **_tables_context(request, app),
        **_application_stats(request, app),
        **context,
    )


@ui_router.get("/database", summary="Every application's database", response_class=HTMLResponse)
def databases_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The four databases: where each is, its revision, and whether this console knows it.

    Also renders the PostgreSQL bootstrap script (row WX15) — printed, never run.
    """
    state = request.app.state
    databases = []
    for app in APPLICATIONS:
        revision, reason = revision_summary(
            state.settings, state.database, app, urls=state.database_urls, now=time.monotonic()
        )
        databases.append({"app": app, "revision": revision, "reason": reason})
    config_paths: dict[str, Path] = {}
    for app in UNIT_APPLICATIONS:
        if app == "weightroom":
            config_paths[app] = state.config_path
            continue
        document, _error = state.schemas.get(
            app,
            now=time.monotonic(),
            read=lambda app=app: read_schema_document(state.settings, app),
        )
        config_paths[app] = config_file_path(document, app=app)
    return render_shell_page(
        request,
        "databases.html",
        page="database",
        principal=principal,
        databases=databases,
        bootstrap_script=postgres_bootstrap_script(config_paths),
    )


@ui_router.get(
    "/apps/{app}/database",
    summary="An application's tables and their row counts",
    response_class=HTMLResponse,
)
def database_page(request: Request, principal: CurrentOperator, app: str) -> HTMLResponse:
    """The revision and the tables, with counts and locks."""
    return _database_page(request, principal, require_app(app), "database_tables.html")


@ui_router.get(
    "/apps/{app}/database/query",
    summary="The SQL console",
    response_class=HTMLResponse,
)
def database_query_page(
    request: Request, principal: CurrentOperator, app: str, sql: str = Query(default="")
) -> HTMLResponse:
    """The SQL console and its last result.

    ``sql`` seeds the textarea without running it — a table's own link on the Tables page
    (``…/database/query?sql=SELECT * FROM <t> LIMIT 100``) so one click both fills in the
    statement and opens this page, leaving *Run* to the operator.
    """
    return _database_page(request, principal, require_app(app), "database_query.html", sql=sql)


@ui_router.get(
    "/apps/{app}/database/admin",
    summary="The application's own operations, the guard's backups, and deletion",
    response_class=HTMLResponse,
)
def database_admin_page(request: Request, principal: CurrentOperator, app: str) -> HTMLResponse:
    """The application's own statistics, its own ``db`` verbs, the delete preview, and backups."""
    return _database_page(request, principal, require_app(app), "database_admin.html")


@ui_router.post("/apps/{app}/database/query", summary="Run the console from the page")
def query_from_page(
    request: Request,
    principal: CurrentOperator,
    app: str,
    sql: Annotated[str, Form(max_length=_SQL_MAX_CHARS)] = "",
) -> HTMLResponse:
    """The console's form post: the result, or the refusal in its own words, on the Query page."""
    name = require_app(app)
    result: QueryResult | None = None
    error: SuiteError | None = None
    try:
        result = _audited_query(request, principal, name, sql)
    except SuiteError as exc:
        error = exc
    return _database_page(
        request, principal, name, "database_query.html", sql=sql, result=result, query_error=error
    )


@ui_router.post("/apps/{app}/database/curated", summary="Run one of the application's db verbs")
def curated_from_page(
    request: Request,
    principal: CurrentOperator,
    app: str,
    verb: Annotated[str, Form(max_length=32)] = "",
    file: Annotated[str, Form(max_length=_NAME_MAX_CHARS)] = "",
    name_typed: Annotated[str, Form(max_length=_NAME_MAX_CHARS)] = "",
    password: Annotated[str, Form(max_length=_NAME_MAX_CHARS)] = "",
    scope: Annotated[str, Form(max_length=16)] = "",
    selector: Annotated[str, Form(max_length=_NAME_MAX_CHARS)] = "",
    token: Annotated[str, Form(max_length=_NAME_MAX_CHARS)] = "",
) -> HTMLResponse:
    """``db backup``, ``db vacuum``, ``db upgrade``; ``db restore`` stopped, typed and
    re-authenticated; or FreeWeight's ``delete-results`` — the preview, then the deletion typed and
    re-authenticated. What the application answered comes back on the page."""
    name = require_app(app)
    acting = (reauthenticated(request, principal, password) or principal) if password else principal
    result: CuratedResult | None = None
    error: SuiteError | None = None
    try:
        result = _audited_curated(
            request,
            acting,
            name,
            verb,
            source=file,
            name_typed=name_typed,
            scope=scope,
            selector=selector,
            token=token,
        )
    except SuiteError as exc:
        error = exc
    return _database_page(
        request, acting, name, "database_admin.html", curated=result, curated_error=error
    )


def _grid_href(base: str, **params: Any) -> str:
    kept = {key: value for key, value in params.items() if value not in (None, "", False)}
    return f"{base}?{urlencode(kept)}" if kept else base


def _table_page(
    request: Request,
    principal: Principal,
    app: str,
    table: str,
    *,
    page: int = 1,
    sort: str | None = None,
    desc: bool = False,
    column: str | None = None,
    filter_text: str | None = None,
    guard: dict[str, Any] | None = None,
) -> HTMLResponse:
    """A page of rows, the table's own operations first, and — unless it is locked — the guard."""
    base = f"/apps/{app}/database/{quote(table, safe='')}"
    context: dict[str, Any] = {
        "table_name": table,
        "lock": lock_for(app, table),
        "operations": TABLE_OPERATIONS.get(app, {}).get(table, ()),
        "grid": None,
        "grid_error": None,
        "revision": None,
        "unavailable": None,
        "previous_href": None,
        "next_href": None,
        "clear_href": base,
        "write_base": base,
        "guard": {
            # A prompt the operator completes, never run as it stands.
            "sql": f"DELETE FROM {table} WHERE ",  # noqa: S608
            "dry": None,
            "error": None,
            "result": None,
            **(guard or {}),
        },
    }
    try:
        with open_for(request, app, require_known=False) as handle:
            context["revision"] = handle.revision
            if handle.revision.is_known:
                grid = table_page(
                    handle,
                    table,
                    page=page,
                    sort=sort or None,
                    descending=desc,
                    column_name=column or None,
                    contains=filter_text or None,
                )
                context["grid"] = grid
                shared = {"sort": grid.sort, "desc": grid.descending, "column": grid.column}
                shared["filter"] = grid.contains
                if grid.page > 1:
                    context["previous_href"] = _grid_href(base, page=grid.page - 1, **shared)
                if grid.pages is not None and grid.page < grid.pages:
                    context["next_href"] = _grid_href(base, page=grid.page + 1, **shared)
    except AppDatabaseUnavailable as exc:
        context["unavailable"] = exc.message
    except ReadFailed as exc:
        context["grid_error"] = exc.message
    return _page(request, principal, app, "database_table.html", **context)


@ui_router.get(
    "/apps/{app}/database/{table}", summary="A table's rows", response_class=HTMLResponse
)
def table_rows_page(
    request: Request,
    principal: CurrentOperator,
    app: str,
    table: str,
    page: int = 1,
    sort: str | None = None,
    desc: bool = False,
    column: str | None = None,
    filter_text: Annotated[str | None, Query(alias="filter")] = None,
) -> HTMLResponse:
    """A page of rows with the sort and filter form; a lock says so above the grid."""
    return _table_page(
        request,
        principal,
        require_app(app),
        table,
        page=page,
        sort=sort,
        desc=desc,
        column=column,
        filter_text=filter_text,
    )


@ui_router.post("/apps/{app}/database/{table}/write/dry-run", summary="The guard's dry run")
def dry_run_from_page(
    request: Request,
    principal: CurrentOperator,
    app: str,
    table: str,
    sql: Annotated[str, Form(max_length=_SQL_MAX_CHARS)] = "",
) -> HTMLResponse:
    """The dry run on the table's page: the count beside the statement, the reach, the verdicts."""
    name = require_app(app)
    dry: DryRun | None = None
    error: SuiteError | None = None
    try:
        dry = _audited_dry_run(request, principal, name, sql)
    except SuiteError as exc:
        error = exc
    return _table_page(
        request, principal, name, table, guard={"sql": sql, "dry": dry, "error": error}
    )


@ui_router.post("/apps/{app}/database/{table}/write", summary="The guarded write")
def write_from_page(
    request: Request,
    principal: CurrentOperator,
    app: str,
    table: str,
    sql: Annotated[str, Form(max_length=_SQL_MAX_CHARS)] = "",
    dry_run_id: Annotated[str, Form(max_length=64)] = "",
    tables_typed: Annotated[str, Form(max_length=_NAME_MAX_CHARS)] = "",
    password: Annotated[str, Form(max_length=_NAME_MAX_CHARS)] = "",
) -> HTMLResponse:
    """The write the dry run was confirmed for; tables typed separated by spaces or commas."""
    name = require_app(app)
    acting = (reauthenticated(request, principal, password) or principal) if password else principal
    typed = tuple(one for one in re.split(r"[\s,]+", tables_typed) if one)
    result: WriteResult | None = None
    error: SuiteError | None = None
    try:
        result = _write(request, acting, name, sql, typed, dry_run_id)
    except SuiteError as exc:
        error = exc
    return _table_page(
        request, acting, name, table, guard={"sql": sql, "error": error, "result": result}
    )

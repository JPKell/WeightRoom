"""weightroom.web.app — the FastAPI application factory for the HTTPS console.

``create_app`` is a pure function of :class:`~weightroom.config.Settings` (plus the certificate
status the runtime established), so tests build an app without touching environment variables
or the filesystem — the database handle is created by the lifespan, which runs only when the
application is actually served.

Middleware, outermost first (ADR-0126 rule 5, ADR-0026 §1): request ID, the Host allowlist, the
rate limiter and login brake, the body cap, MirrorWall's double-submit CSRF on forms, the
same-origin check on JSON writes. The session is a route dependency
(:mod:`weightroom.web.session`) and therefore runs after all of them.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx
from baseaicore import SuiteError, new_id
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from mirrorwall import (
    CsrfMiddleware,
    HostValidationMiddleware,
    RequestIdMiddleware,
    error_body,
    mount_static,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from weightroom.__about__ import __version__
from weightroom.config import LOOPBACK_HOSTS, Settings, data_dir, resolve_config_path
from weightroom.services.alerts import AlertEvaluator, default_sources, sampler_temperature
from weightroom.services.apps import VersionCache
from weightroom.services.catalog import PullRegistry
from weightroom.services.chat import ChatRunner, recover_interrupted
from weightroom.services.database import Database
from weightroom.services.db_reader import DatabaseUrlCache
from weightroom.services.jobs import JobServices, JobWorker
from weightroom.services.journal import JournalReader
from weightroom.services.ollama import ollama_client
from weightroom.services.processes import SubprocessSystemdController
from weightroom.services.settings_forms import SchemaCache
from weightroom.services.telemetry import TelemetryService
from weightroom.web.csrf import render_form_page
from weightroom.web.hosts import resolve_allowed_hosts
from weightroom.web.limits import BodySizeLimitMiddleware, RateLimitMiddleware, SameOriginMiddleware
from weightroom.web.rendering import templates
from weightroom.web.routes import alerts as alerts_routes
from weightroom.web.routes import apps as apps_routes
from weightroom.web.routes import audit as audit_routes
from weightroom.web.routes import backups as backups_routes
from weightroom.web.routes import catalog as catalog_routes
from weightroom.web.routes import chat as chat_routes
from weightroom.web.routes import costs as costs_routes
from weightroom.web.routes import databases as databases_routes
from weightroom.web.routes import docs as docs_routes
from weightroom.web.routes import doctor as doctor_routes
from weightroom.web.routes import freeweight as freeweight_routes
from weightroom.web.routes import freeweight_goals as freeweight_goals_routes
from weightroom.web.routes import ideapress as ideapress_routes
from weightroom.web.routes import jobs as jobs_routes
from weightroom.web.routes import llamacpp as llamacpp_routes
from weightroom.web.routes import loadcoach as loadcoach_routes
from weightroom.web.routes import ollama as ollama_routes
from weightroom.web.routes import promptcadence as promptcadence_routes
from weightroom.web.routes import prompts as prompts_routes
from weightroom.web.routes import session as session_routes
from weightroom.web.routes import settings as settings_routes
from weightroom.web.routes import shell as shell_routes
from weightroom.web.routes import system as system_routes
from weightroom.web.routes import tokens as tokens_routes
from weightroom.web.routes import trust as trust_routes

if TYPE_CHECKING:
    from weightroom.services.tls import HostIdentity, TlsStatus

__all__ = ["APP_STATIC_DIR", "STATUS_BY_CODE", "create_app"]

logger = logging.getLogger(__name__)

APP_STATIC_DIR = Path(__file__).parent / "static"
"""WeightRoomGym's own vendored assets (mermaid) — one consumer, so it lives here, not in
MirrorWall (design brief §5)."""

STATUS_BY_CODE: dict[str, int] = {
    "VALIDATION_ERROR": status.HTTP_400_BAD_REQUEST,
    "UNAUTHORIZED": status.HTTP_401_UNAUTHORIZED,
    "FORBIDDEN": status.HTTP_403_FORBIDDEN,
    "CSRF_FAILED": status.HTTP_403_FORBIDDEN,
    "REAUTH_REQUIRED": status.HTTP_403_FORBIDDEN,
    "RATE_LIMITED": status.HTTP_429_TOO_MANY_REQUESTS,
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "AUDIT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "SETTING_CONFIG_ONLY": status.HTTP_403_FORBIDDEN,
    "SETTING_UNKNOWN": status.HTTP_400_BAD_REQUEST,
    # 409: the request was well formed and the console is fine; the *file* moved underneath it,
    # and the operator resolves it by reloading and re-applying (ADR-0117 rule 7).
    "CONFIG_CHANGED_ON_DISK": status.HTTP_409_CONFLICT,
    # 400: the application's own loader refused the candidate, in its own words.
    "CONFIG_VALIDATION_FAILED": status.HTTP_400_BAD_REQUEST,
    "APP_UNKNOWN": status.HTTP_404_NOT_FOUND,
    # 409: the application exists and the request was well formed; the *host* is in a state
    # that makes the action impossible, and the operator fixes it by installing or starting.
    "APP_NOT_INSTALLED": status.HTTP_409_CONFLICT,
    "APP_STOPPED": status.HTTP_409_CONFLICT,
    "APP_VERSION_MISMATCH": status.HTTP_409_CONFLICT,
    # 409, as the version mismatch: the database is fine and so is the request; this console was
    # not written against that schema revision, and a WeightRoomGym upgrade is the fix.
    "SCHEMA_UNKNOWN": status.HTTP_409_CONFLICT,
    # 400: the statement itself is refused by name — not one SELECT, not one DML statement.
    "GUARD_STATEMENT_REFUSED": status.HTTP_400_BAD_REQUEST,
    # ADR-0124's conditions. 409 where a fact about the host or the data is what refuses — stop the
    # application, re-run the dry run — 400 where the request is what is wrong, 403 where no
    # request could ever succeed, 500 where WeightRoomGym itself could not do its part.
    "GUARD_APP_RUNNING": status.HTTP_409_CONFLICT,
    "GUARD_DRY_RUN_FAILED": status.HTTP_409_CONFLICT,
    "GUARD_TABLE_MISMATCH": status.HTTP_400_BAD_REQUEST,
    "GUARD_TABLE_LOCKED": status.HTTP_403_FORBIDDEN,
    "GUARD_BACKUP_FAILED": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "GUARD_AUDIT_FAILED": status.HTTP_500_INTERNAL_SERVER_ERROR,
    # 502: something WeightRoomGym drives answered badly or not at all — the application's API,
    # systemd, journalctl. The console is working; the thing behind it is not.
    "APP_UNREACHABLE": status.HTTP_502_BAD_GATEWAY,
    "UNIT_ACTION_FAILED": status.HTTP_502_BAD_GATEWAY,
    # 501: this host cannot do it at all, and no retry will help (ADR-0125 rule 7).
    "UNIT_UNSUPPORTED": status.HTTP_501_NOT_IMPLEMENTED,
    "OLLAMA_RESTART_NOT_PERMITTED": status.HTTP_403_FORBIDDEN,
    # 409: the conversation is fine and still reads; its backend cannot take a message now.
    "CHAT_BACKEND_UNAVAILABLE": status.HTTP_409_CONFLICT,
    "ATTACHMENT_TOO_LARGE": status.HTTP_413_CONTENT_TOO_LARGE,
    "ATTACHMENT_TYPE_REFUSED": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "MISDIRECTED_REQUEST": 421,
    "PAYLOAD_TOO_LARGE": status.HTTP_413_CONTENT_TOO_LARGE,
    "CONFIGURATION_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "INSECURE_BINDING": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "TLS_MISSING": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "DATABASE_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "DATABASE_UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
    "INTERNAL_ERROR": status.HTTP_500_INTERNAL_SERVER_ERROR,
    # 500: a hosting problem (no root configured), not something a request parameter fixes.
    "DOCS_ROOT_MISSING": status.HTTP_500_INTERNAL_SERVER_ERROR,
    # 404: the requested or linked document does not resolve to a file this viewer will serve.
    "DOCS_PAGE_OUTSIDE_ROOT": status.HTTP_404_NOT_FOUND,
    # 404: no job or schedule by that id; 409: the job is fine and has already finished (api.md §7).
    "JOB_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "JOB_INVALID_STATE": status.HTTP_409_CONFLICT,
    # 409, as the guard's host-and-data refusals: the file (magic, size, name) or the host (no
    # llama.cpp model_directory, or two that disagree) is what refuses; the console did its part.
    "CATALOG_DROPIN_REFUSED": status.HTTP_409_CONFLICT,
    # 502, as the unreachable application: the console did its part; the application refused,
    # and its own code is carried in `details.app_code` (row WP1's API client).
    "APP_REFUSED": status.HTTP_502_BAD_GATEWAY,
}
"""Spec §13's codes to HTTP statuses, for the ones Phases 1 through 5 raise."""

_CODE_BY_HTTP_STATUS: dict[int, str] = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    421: "MISDIRECTED_REQUEST",
}


def _request_id_of(request: Request) -> str:
    state_id = getattr(request.state, "request_id", None)
    return state_id if isinstance(state_id, str) and state_id else new_id()


def _wants_html(request: Request) -> bool:
    if request.url.path.startswith("/api/"):
        return False
    return "text/html" in request.headers.get("accept", "")


def _error_response(
    *,
    request: Request,
    code: str,
    message: str,
    status_code: int,
    details: Mapping[str, Any] | None = None,
) -> Response:
    request_id = _request_id_of(request)
    if _wants_html(request):
        if status_code == status.HTTP_401_UNAUTHORIZED:
            target = "/login?next=" + quote(request.url.path, safe="/")
            return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
        response = render_form_page(
            request,
            "error.html",
            page=None,
            code=code,
            message=message,
            status_code=status_code,
            request_id=request_id,
            details=dict(details or {}),
            path=request.url.path,
        )
        response.status_code = status_code
        response.headers["X-Request-ID"] = request_id
        return response
    return JSONResponse(
        status_code=status_code,
        content=error_body(code=code, message=message, request_id=request_id, details=details),
        headers={"X-Request-ID": request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the handlers that translate every exception type into the standard envelope."""

    @app.exception_handler(SuiteError)
    async def _suite_error_handler(request: Request, exc: SuiteError) -> Response:
        status_code = STATUS_BY_CODE.get(exc.code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.error("request.failed", extra={"code": exc.code}, exc_info=exc)
        else:
            logger.warning("request.rejected", extra={"code": exc.code})
        return _error_response(
            request=request,
            code=exc.code,
            message=exc.message,
            status_code=status_code,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> Response:
        fields = [
            {
                "path": ".".join(str(part) for part in error["loc"] if part != "body"),
                "problem": error["msg"],
            }
            for error in exc.errors()
        ]
        return _error_response(
            request=request,
            code="VALIDATION_ERROR",
            message="Request body failed validation.",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        code = _CODE_BY_HTTP_STATUS.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) and exc.detail else "Request failed."
        return _error_response(
            request=request, code=code, message=message, status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        logger.error("request.unhandled_error", exc_info=exc)
        return _error_response(
            request=request,
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own one database handle for as long as the server serves."""
    settings: Settings = app.state.settings
    database_url = settings.storage.database_url
    if database_url is None:  # pragma: no cover — StorageSettings always fills this in
        message = "no database_url configured"
        raise RuntimeError(message)
    database = Database.from_url(database_url)
    app.state.database = database
    from datetime import UTC, datetime

    recovered = recover_interrupted(database, now=datetime.now(UTC))
    if recovered:
        logger.warning("chat.recovered_interrupted_replies", extra={"count": recovered})
    app.state.telemetry = TelemetryService(
        database,
        settings,
        ollama_client=app.state.ollama_http,
        app_client=app.state.http,
    )
    app.state.telemetry.start()
    # The queue's worker and lease keeper (spec §7.10): started after its own recovery pass.
    app.state.jobs = JobWorker(
        database,
        settings,
        JobServices(
            controller=app.state.controller,
            http=app.state.http,
            pulls=app.state.catalog_pulls,
            urls=app.state.database_urls,
            ollama_http=app.state.ollama_http,
            config_path=app.state.config_path,
        ),
    )
    app.state.jobs.start()
    # The alert evaluator (spec §7.10, ADR-0137): a thread of its own, never the job worker's.
    app.state.alerts = AlertEvaluator(
        database,
        settings,
        default_sources(
            settings,
            database,
            controller=app.state.controller,
            client=app.state.http,
            urls=app.state.database_urls,
            temperature=lambda: sampler_temperature(app.state.telemetry),
        ),
    )
    app.state.alerts.start()
    try:
        yield
    finally:
        app.state.alerts.stop()
        app.state.jobs.stop()
        app.state.telemetry.stop()
        app.state.chat.shutdown()
        database.close()
        app.state.database = None
        app.state.http.close()
        app.state.ollama_http.close()


def create_app(
    settings: Settings,
    *,
    tls: TlsStatus | None = None,
    identity: HostIdentity | None = None,
    config_path: Path | None = None,
    controller: Any | None = None,
    journal: Any | None = None,
) -> FastAPI:
    """Build the FastAPI application for the given settings.

    Args:
        settings: The validated configuration.
        tls: The certificate status the runtime established, for ``/health`` and ``/trust``;
            ``None`` in tests that never serve TLS.
        identity: The host's names and addresses, for the trust page's URLs.
        config_path: The file the settings came from.
        controller: The systemd boundary; the real one when ``None``. Injected so a test builds
            a console over a fake host rather than over the developer's own session manager
            (spec §20 criterion 10: the suite passes with no systemd).
        journal: The ``journalctl`` boundary, injected for the same reason.

    Returns:
        The app. Pure: opens nothing; the database handle is created by the lifespan.
    """
    app = FastAPI(
        title="WeightRoomGym",
        version=__version__,
        docs_url="/api/v1/docs" if settings.server.host in LOOPBACK_HOSTS else None,
        openapi_url="/api/v1/openapi.json" if settings.server.host in LOOPBACK_HOSTS else None,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.tls = tls
    app.state.identity = identity
    app.state.config_path = config_path if config_path is not None else resolve_config_path()
    app.state.database = None
    app.state.controller = controller if controller is not None else SubprocessSystemdController()
    app.state.journal = journal if journal is not None else JournalReader()
    app.state.versions = VersionCache()
    # Replies outlive the request that starts them (services/chat.py); attachment files live under
    # the data root with generated names (spec §14). Both overridable, so a test never writes to
    # the operator's home.
    app.state.chat = ChatRunner()
    # The live progress of the pulls this process executes as `catalog_pull` jobs (row W9); the
    # job row is the durable answer. The worker is built by the lifespan, which tests never enter.
    app.state.catalog_pulls = PullRegistry()
    app.state.jobs = None
    app.state.alerts = None
    app.state.attachments_root = data_dir() / "attachments"
    # One schema document per application, re-read every 60 s (api.md §2). Each read launches
    # `<app> config schema --json`, so without it every element of a settings page would.
    app.state.schemas = SchemaCache()
    # Each application's effective database URL, from `<app> config show --json`, for 60 s — the
    # database pages, `GET /apps` and the machine view all ask (services/db_reader.py).
    app.state.database_urls = DatabaseUrlCache()
    # Pooled, and both open nothing until the first request; the lifespan closes them. The
    # Ollama one is separate because ModelRack's provider issues relative paths against whatever
    # client it is handed, so that client must carry Ollama's own base URL.
    app.state.http = httpx.Client(follow_redirects=False, trust_env=False)
    app.state.ollama_http = ollama_client(settings)

    # Starlette wraps in reverse order of these calls; the stack from the outside in is the
    # module docstring's order.
    app.add_middleware(SameOriginMiddleware)
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.server.max_body_bytes)
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=settings.server.rate_limit_per_minute,
        burst=settings.server.rate_limit_burst,
        login_per_minute=settings.server.failed_login_per_minute,
    )
    app.add_middleware(HostValidationMiddleware, allowed_hosts=resolve_allowed_hosts(settings))
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)

    app.include_router(system_routes.router, prefix="/api/v1")
    app.include_router(session_routes.router, prefix="/api/v1")
    app.include_router(apps_routes.router, prefix="/api/v1")
    app.include_router(audit_routes.router, prefix="/api/v1")
    app.include_router(chat_routes.router, prefix="/api/v1")
    app.include_router(settings_routes.router, prefix="/api/v1")
    app.include_router(tokens_routes.router, prefix="/api/v1")
    app.include_router(doctor_routes.router, prefix="/api/v1")
    app.include_router(ollama_routes.router, prefix="/api/v1")
    app.include_router(docs_routes.router, prefix="/api/v1")
    app.include_router(databases_routes.router, prefix="/api/v1")
    app.include_router(catalog_routes.router, prefix="/api/v1")
    app.include_router(costs_routes.router, prefix="/api/v1")
    app.include_router(backups_routes.router, prefix="/api/v1")
    app.include_router(jobs_routes.router, prefix="/api/v1")
    app.include_router(alerts_routes.router, prefix="/api/v1")
    app.include_router(prompts_routes.router, prefix="/api/v1")
    app.include_router(session_routes.ui_router)
    app.include_router(shell_routes.ui_router)
    app.include_router(trust_routes.ui_router)
    app.include_router(apps_routes.ui_router)
    app.include_router(audit_routes.ui_router)
    app.include_router(chat_routes.ui_router)
    app.include_router(settings_routes.ui_router)
    app.include_router(tokens_routes.ui_router)
    app.include_router(doctor_routes.ui_router)
    app.include_router(ollama_routes.ui_router)
    app.include_router(llamacpp_routes.ui_router)
    app.include_router(system_routes.ui_router)
    app.include_router(docs_routes.ui_router)
    app.include_router(databases_routes.ui_router)
    app.include_router(catalog_routes.ui_router)
    app.include_router(costs_routes.ui_router)
    app.include_router(backups_routes.ui_router)
    app.include_router(jobs_routes.ui_router)
    app.include_router(alerts_routes.ui_router)
    app.include_router(prompts_routes.ui_router)
    app.include_router(promptcadence_routes.ui_router)
    app.include_router(loadcoach_routes.ui_router)
    app.include_router(ideapress_routes.ui_router)
    app.include_router(freeweight_routes.ui_router)
    app.include_router(freeweight_goals_routes.ui_router)

    mount_static(app, environment=templates(), extra_dirs={"/app-static": APP_STATIC_DIR})
    return app

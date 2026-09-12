"""weightroom.web.routes.tokens — each application's API tokens, listed, minted and revoked.

Spec §7.3's *Tokens* page, over :mod:`weightroom.services.tokens`, which drives each
application's own ``token`` CLI verb.

**A new token's secret is shown once, on the page that minted it, and is never stored anywhere.**
It is passed to that one render and nothing else: not to the audit row (whose ``params`` are
redacted regardless), not to a log, not to the database. That is why creating a token renders a
page rather than redirecting — a redirect would have to carry the secret in a URL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from weightroom.services.apps import require_app
from weightroom.services.audit import record
from weightroom.services.tokens import (
    MULTI_SCOPE_APPS,
    SCOPES_BY_APP,
    TokensUnsupported,
    create_token,
    list_tokens,
    revoke_token,
    token_surface,
)
from weightroom.web.session import CurrentOperator, now_of

if TYPE_CHECKING:
    from weightroom.services.tokens import TokenRecord

__all__ = ["router", "ui_router"]

router = APIRouter(tags=["tokens"])
ui_router = APIRouter(tags=["ui"], include_in_schema=False)


def _tokens(request: Request, app: str) -> tuple[tuple[TokenRecord, ...], str | None]:
    """Every token, or the reason there are none to show. Never raises: the page renders both."""
    try:
        return list_tokens(request.app.state.settings, app), None
    except TokensUnsupported as exc:
        return (), exc.message
    except Exception as exc:  # noqa: BLE001 — an application's own refusal is page content
        return (), str(exc)


def _render(
    request: Request,
    principal: CurrentOperator,
    app: str,
    *,
    secret: str = "",
    secret_name: str = "",
    notice: str = "",
    error: str = "",
) -> HTMLResponse:
    from weightroom.web.rendering import app_side_nav, app_side_nav_stubs
    from weightroom.web.routes.apps import _view, render_shell_page

    records, reason = _tokens(request, app)
    return render_shell_page(
        request,
        "tokens.html",
        page="apps",
        principal=principal,
        app=app,
        view=_view(request, app),
        tokens=records,
        surface=token_surface(app),
        reason=reason,
        secret=secret,
        secret_name=secret_name,
        notice=notice,
        error=error,
        active_app=app,
        scope_options=SCOPES_BY_APP.get(app, ()),
        multi_scope=app in MULTI_SCOPE_APPS,
        nav_sections=app_side_nav(app, selected="Tokens"),
        side_nav_stubs=app_side_nav_stubs(app),
    )


@router.get("/apps/{app}/tokens", summary="An application's API tokens")
def get_tokens(request: Request, principal: CurrentOperator) -> JSONResponse:
    """Name, scope, creation, expiry and revocation — never the token itself."""
    app = require_app(request.path_params["app"])
    records, reason = _tokens(request, app)
    return JSONResponse(
        content={
            "app": app,
            "surface": token_surface(app),
            "reason": reason,
            "tokens": [one.as_json() for one in records],
        }
    )


@ui_router.get("/apps/{app}/tokens", summary="The Tokens page", response_class=HTMLResponse)
def tokens_page(request: Request, principal: CurrentOperator, app: str) -> HTMLResponse:
    """The list, and the form that mints one."""
    return _render(request, principal, require_app(app))


@ui_router.post("/apps/{app}/tokens", summary="Mint a token")
def create_from_page(
    request: Request,
    principal: CurrentOperator,
    app: str,
    name: Annotated[str, Form()] = "",
    scope: Annotated[list[str] | None, Form()] = None,
    expires_days: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Mint one and show its secret **once**; the row that records it never carries the secret.

    ``scope`` is one or more values from the application's own vocabulary
    (:data:`~weightroom.services.tokens.SCOPES_BY_APP`) — several only for the applications in
    :data:`~weightroom.services.tokens.MULTI_SCOPE_APPS`, joined with a comma the way each
    application's own ``--scope`` reads a list; unread and unvalidated here either way, so an
    application refuses one it does not know in its own words.
    """
    from baseaicore import SuiteError

    target = require_app(app)
    state = request.app.state
    scope_text = ",".join(one.strip() for one in (scope or ()) if one.strip()) or "read"
    secret = ""
    error = ""
    notice = ""
    try:
        record_row, secret = create_token(
            state.settings,
            target,
            name.strip(),
            scope=scope_text,
            expires_days=int(expires_days) if expires_days.strip() else None,
        )
        notice = f"{record_row.name} created. The secret below is shown once."
        outcome = "ok"
    except (SuiteError, ValueError) as exc:
        error = getattr(exc, "message", str(exc))
        outcome = "refused"
    record(
        state.database,
        action="token.create",
        actor="operator",
        outcome=outcome,
        now=now_of(request),
        operator_id=principal.operator_id,
        app=target,
        target=name.strip(),
        params={"scope": scope_text, "expires_days": expires_days},
        message=error or None,
        security=True,
        request_id=getattr(request.state, "request_id", None),
    )
    return _render(
        request,
        principal,
        target,
        secret=secret,
        secret_name=name.strip(),
        notice=notice,
        error=error,
    )


@ui_router.post("/apps/{app}/tokens/revoke", summary="Revoke a token")
def revoke_from_page(
    request: Request, principal: CurrentOperator, app: str, name: Annotated[str, Form()] = ""
) -> HTMLResponse:
    """Revoke the active token with that name."""
    from baseaicore import SuiteError

    target = require_app(app)
    state = request.app.state
    error = ""
    notice = ""
    try:
        revoke_token(state.settings, target, name.strip())
        notice = f"{name.strip()} revoked."
        outcome = "ok"
    except SuiteError as exc:
        error = exc.message
        outcome = "refused"
    record(
        state.database,
        action="token.revoke",
        actor="operator",
        outcome=outcome,
        now=now_of(request),
        operator_id=principal.operator_id,
        app=target,
        target=name.strip(),
        params={},
        message=error or None,
        security=True,
        request_id=getattr(request.state, "request_id", None),
    )
    return _render(request, principal, target, notice=notice, error=error)

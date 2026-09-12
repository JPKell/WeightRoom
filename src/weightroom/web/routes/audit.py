"""weightroom.web.routes.audit — the trail (api.md §7) and its page."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from mirrorwall import clamp_limit, paginated_response

from weightroom.config import APPLICATIONS
from weightroom.domain.audit import ACTIONS
from weightroom.services.audit import get_audit, list_audit
from weightroom.web.routes.apps import render_shell_page
from weightroom.web.session import CurrentOperator

__all__ = ["router", "ui_router"]


def _blank_to_none(value: str | None) -> str | None:
    """An empty select box means *no filter*, not a filter on the empty string."""
    return value or None


def _parse_since(value: str | None) -> tuple[datetime | None, str | None]:
    """``2026-09-09`` or a full ISO timestamp; anything else is ignored, with the reason."""
    if not value:
        return None, None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, f"{value!r} is not a date or timestamp; the filter was ignored"
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)), None


router = APIRouter(tags=["audit"])
ui_router = APIRouter(tags=["ui"], include_in_schema=False)


@router.get("/audit", summary="The audit trail")
def audit_list(
    request: Request,
    principal: CurrentOperator,
    app: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> JSONResponse:
    """A page of rows, newest first, filtered by ``app``, ``action`` and ``since``."""
    effective = clamp_limit(limit)
    rows, has_more = list_audit(
        request.app.state.database,
        limit=effective,
        app=app,
        action=action,
        since=since,
        before_id=cursor,
    )
    return paginated_response(
        [row.as_json() for row in rows],
        limit=effective,
        next_cursor=rows[-1].id if has_more and rows else None,
        has_more=has_more,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/audit/{audit_id}", summary="One audit row")
def audit_detail(request: Request, principal: CurrentOperator, audit_id: str) -> JSONResponse:
    """One row by id; ``404 AUDIT_NOT_FOUND`` otherwise."""
    return JSONResponse(content=get_audit(request.app.state.database, audit_id).as_json())


@ui_router.get("/audit", summary="The audit page", response_class=HTMLResponse)
def audit_page(
    request: Request,
    principal: CurrentOperator,
    app: str | None = None,
    action: str | None = None,
    since: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> HTMLResponse:
    """A filtered page of the trail: by application, by action, and from an instant.

    ``since`` is accepted as a date or a full timestamp because that is what an operator types.
    A value that is neither is ignored with a note rather than refused: a filter box is not a
    place to make somebody re-enter a whole query over a typo. ``cursor`` continues from the
    previous page's last row id, so the trail no longer stops at one page with no way further
    back (row WX5); the default page size is ``[ui] page_rows``, not a fixed 50.
    """
    effective = clamp_limit(limit or request.app.state.settings.ui.page_rows)
    parsed_since, since_problem = _parse_since(since)
    rows, has_more = list_audit(
        request.app.state.database,
        limit=effective,
        app=_blank_to_none(app),
        action=_blank_to_none(action),
        since=parsed_since,
        before_id=cursor or None,
    )
    next_cursor = rows[-1].id if has_more and rows else None
    next_href = None
    if next_cursor:
        from urllib.parse import urlencode

        kept = {
            key: value
            for key, value in {
                "app": app or "",
                "action": action or "",
                "since": since or "",
                "limit": limit or "",
                "cursor": next_cursor,
            }.items()
            if value
        }
        next_href = f"/audit?{urlencode(kept)}"
    return render_shell_page(
        request,
        "audit.html",
        page="audit",
        rows=rows,
        has_more=has_more,
        next_href=next_href,
        principal=principal,
        applications=[*APPLICATIONS, "weightroom", "ollama", "host"],
        actions=sorted(ACTIONS),
        selected={
            "app": app or "",
            "action": action or "",
            "since": since or "",
            "limit": effective,
        },
        since_problem=since_problem,
    )

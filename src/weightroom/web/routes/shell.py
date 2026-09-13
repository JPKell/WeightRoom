"""weightroom.web.routes.shell — the console landing page, inside the real shell (row W3).

``_shell.html`` (the four tabs with status dots, the telemetry strip, the left menu) is what
every page here renders inside — this route is just what "/" shows: the bind, the certificate,
each application's live pill, and (row WY3) LoadCoach, PromptCadence and FreeWeight's live figures.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from weightroom.services.overview import overview_cards
from weightroom.web.routes.apps import render_shell_page, views_for_request
from weightroom.web.session import CurrentOperator

__all__ = ["ui_router"]

ui_router = APIRouter(tags=["ui"], include_in_schema=False)


@ui_router.get("/", summary="The shell", response_class=HTMLResponse)
def shell(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The console landing page: who is logged in, the certificate's days left, the four tabs."""
    tls = request.app.state.tls
    views = views_for_request(request)
    state = request.app.state
    cards = overview_cards(views, settings=state.settings, client=state.http)
    return render_shell_page(
        request,
        "shell.html",
        page="shell",
        principal=principal,
        views=views,
        cards=cards,
        tls_days_left=None if tls is None else tls.days_left,
        bind_host=state.settings.server.host,
    )

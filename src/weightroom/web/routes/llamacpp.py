"""weightroom.web.routes.llamacpp — the llama.cpp pane, read-only end to end.

One ``GET``, no ``POST``. See :mod:`weightroom.services.llamacpp` for why there is nothing to
post: `llama-server` belongs to the application that launched it, and the console neither starts
one nor stops one.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from weightroom.config import Settings
from weightroom.services.llamacpp import SETUP_DOCUMENT, llamacpp_report
from weightroom.services.settings_forms import forms_for
from weightroom.web.routes.apps import render_shell_page
from weightroom.web.session import CurrentOperator

__all__ = ["LAUNCHING_APPS", "ui_router"]

ui_router = APIRouter(tags=["ui"], include_in_schema=False)

LAUNCHING_APPS: tuple[str, ...] = ("freeweight", "loadcoach")
"""The two applications that launch `llama-server` (``MEMORY_SAFETY.md`` §2.2). IdeaPress and
PromptCadence reach models through LoadCoach and hold none in their own cgroup."""


@ui_router.get("/llamacpp", summary="The llama.cpp pane", response_class=HTMLResponse)
def llamacpp_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Running servers, the configured GGUF directories and the §2.2 checklist."""
    state = request.app.state
    settings: Settings = state.settings
    forms = forms_for(settings, LAUNCHING_APPS, cache=state.schemas, monotonic=time.monotonic())
    report = llamacpp_report(settings, forms=forms, controller=state.controller)
    return render_shell_page(
        request,
        "llamacpp.html",
        page="llamacpp",
        principal=principal,
        report=report,
        setup_document=SETUP_DOCUMENT,
    )

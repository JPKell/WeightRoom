"""weightroom.web.routes.ideapress — IdeaPress's pages under its tab (row WP5).

Projects (with the plan, research, stage runs, the workspace and export), Units, Workflows and
Backends, at parity with IdeaPress's own ``web/templates`` and routes, which
a browser on the LAN cannot reach: IdeaPress binds loopback (ADR-0126). Every page reads by spec
§7.3's rule (``services/app_pages``) through the readers in ``services/ideapress_pages`` and
renders through ``render_app_page``.

Every action is a form post writing exactly one audit row whether IdeaPress accepts or refuses
(spec §11 contract 2). A refusal renders on the page it came from, in IdeaPress's own words, with
what the operator typed kept. No row carries a brief, a title or author material: those are the
author's text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlencode

from baseaicore import SuiteError
from fastapi import APIRouter, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

from weightroom.services import ideapress_actions as actions
from weightroom.services import ideapress_pages as ip
from weightroom.services import loadcoach_pages as lc
from weightroom.services.app_api import outcome_of
from weightroom.services.app_api import stream as app_stream
from weightroom.services.audit import record
from weightroom.services.chat import render_reply
from weightroom.web.routes.apps import app_view, read_app_page, render_app_page
from weightroom.web.session import CurrentOperator, now_of

if TYPE_CHECKING:
    from weightroom.services.app_pages import Sourced
    from weightroom.services.apps import AppView
    from weightroom.services.auth import Principal

__all__ = ["ui_router"]

ui_router = APIRouter(tags=["ui"], include_in_schema=False)

APP = ip.APP
BASE = "/apps/ideapress"


def _audit(  # noqa: PLR0913 — every field of one audit row
    request: Request,
    principal: Principal,
    action: str,
    *,
    target: str | None,
    outcome: str,
    params: Mapping[str, Any],
    message: str | None = None,
) -> None:
    record(
        request.app.state.database,
        action=action,
        actor="operator",
        outcome=outcome,
        now=now_of(request),
        operator_id=principal.operator_id,
        app=APP,
        target=target,
        params=dict(params),
        message=message,
        request_id=getattr(request.state, "request_id", None),
    )


def _clients(request: Request) -> tuple[Any, Any]:
    return request.app.state.http, request.app.state.settings


def _href(path: str, **query: Any) -> str:
    """``path`` with the query parameters that carry a value, so a pager keeps the filters."""
    kept = {key: value for key, value in query.items() if value not in (None, "", False)}
    return f"{path}?{urlencode(kept)}" if kept else path


def _optional[T](read: Callable[[], T]) -> T | None:
    """A second read a page can live without: its refusal hides a control, never the page."""
    try:
        return read()
    except SuiteError:
        return None


NAV_ROWS = 8
"""Row WX10: the top nav names the eight most recent projects, by name."""


def _nav_projects(
    request: Request, view: AppView, client: Any, settings: Any
) -> Sourced[dict[str, Any]]:
    """The unfiltered first page of ``GET /projects``, for the top nav on every projects page.

    Its own read, never the page's own (filtered, differently paged) one — a status filter on
    Projects, or which project is open, must never make a recent project disappear from the nav.
    """
    return read_app_page(
        request,
        view,
        api=lambda: ip.projects_api(
            client, settings, status=None, content_type=None, archived=False, cursor=None,
            page_rows=NAV_ROWS,
        ),
        database=lambda handle: ip.projects_db(
            handle, status=None, content_type=None, archived=False, page=1, page_rows=NAV_ROWS
        ),
    )  # fmt: skip


# --- Projects -------------------------------------------------------------------------------------


def _projects(  # noqa: PLR0913 — the list's filters, and what the last action left
    request: Request,
    principal: Principal,
    *,
    project_status: str | None = None,
    content_type: str | None = None,
    archived: bool = False,
    cursor: str | None = None,
    page: int = 1,
    deleted: str | None = None,
    archive_path: str | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    page_rows = settings.ui.page_rows
    sourced = read_app_page(
        request,
        view,
        api=lambda: ip.projects_api(
            client, settings, status=project_status, content_type=content_type,
            archived=archived, cursor=cursor, page_rows=page_rows,
        ),
        database=lambda handle: ip.projects_db(
            handle, status=project_status, content_type=content_type, archived=archived, page=page,
            page_rows=page_rows,
        ),
    )  # fmt: skip
    data = sourced.data or {}
    filters = {"status": project_status, "content_type": content_type, "archived": archived}
    next_href = None
    if data.get("next_cursor"):
        next_href = _href(f"{BASE}/projects", **filters, cursor=data["next_cursor"])
    elif data.get("next_page"):
        next_href = _href(f"{BASE}/projects", **filters, page=data["next_page"])
    return render_app_page(
        request,
        principal,
        APP,
        "ip_projects.html",
        selected="Projects",
        view=view,
        sourced=sourced,
        nav=_nav_projects(request, view, client, settings),
        project_status=project_status or "",
        content_type=content_type or "",
        archived=archived,
        next_href=next_href,
        deleted=deleted,
        archive_path=archive_path,
    )


@ui_router.get(f"{BASE}/projects", summary="Projects", response_class=HTMLResponse)
def projects_page(  # noqa: PLR0913 — one parameter per query field
    request: Request,
    principal: CurrentOperator,
    project_status: Annotated[str | None, Query(alias="status")] = None,
    content_type: str | None = None,
    archived: bool = False,
    cursor: str | None = None,
    page: int = 1,
    deleted: str | None = None,
    archive: str | None = None,
) -> HTMLResponse:
    """Every project, newest activity first, by status and content type."""
    return _projects(
        request, principal, project_status=project_status or None,
        content_type=content_type or None, archived=archived, cursor=cursor or None, page=page,
        deleted=deleted, archive_path=archive,
    )  # fmt: skip


def _project_new(
    request: Request,
    principal: Principal,
    *,
    create_error: SuiteError | None = None,
    form: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    nav = _nav_projects(request, view, client, settings)
    workflows = _optional(lambda: ip.workflows_api(client, settings)) if nav.live else None
    return render_app_page(
        request, principal, APP, "ip_project_new.html", selected="Projects", view=view,
        sourced=nav, nav=nav, workflows=workflows, create_error=create_error,
        form=dict(form or {}),
    )  # fmt: skip


@ui_router.get(f"{BASE}/projects/new", summary="New project", response_class=HTMLResponse)
def project_new_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The create form, on its own page — reached from the top nav's *New* (row WX10)."""
    return _project_new(request, principal)


@ui_router.post(f"{BASE}/projects", summary="Create a project from the page")
def create_from_page(  # noqa: PLR0913 — one parameter per form field
    request: Request,
    principal: CurrentOperator,
    title: Annotated[str, Form()] = "",
    content_type: Annotated[str, Form()] = "article",
    workflow_id: Annotated[str, Form()] = "standard",
    brief: Annotated[str, Form()] = "",
    author_material: Annotated[str, Form()] = "",
) -> Response:
    """``POST /projects``; the new project on success, the form and its refusal otherwise."""
    form = {
        "title": title, "content_type": content_type, "workflow_id": workflow_id, "brief": brief,
        "author_material": author_material,
    }  # fmt: skip
    params = {
        "content_type": content_type or "article",
        "workflow_id": workflow_id or "standard",
        "has_brief": bool(brief.strip()),
        "has_author_material": bool(author_material.strip()),
    }
    client, settings = _clients(request)
    try:
        created = actions.create_project(
            client, settings, title=title, content_type=content_type, workflow_id=workflow_id,
            brief=brief, author_material_text=author_material,
        )  # fmt: skip
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.project_create", target=None, outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _project_new(request, principal, create_error=exc, form=form)
    project_id = str(created.get("id") or "")
    _audit(
        request, principal, "ideapress.project_create", target=project_id or None, outcome="ok",
        params=params,
    )  # fmt: skip
    location = f"{BASE}/projects/{ip.segment(project_id)}" if project_id else f"{BASE}/projects"
    return RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)


def _project(  # noqa: PLR0913 — the page, and what the last action left on it
    request: Request,
    principal: Principal,
    project_id: str,
    *,
    action_error: SuiteError | None = None,
    form: Mapping[str, Any] | None = None,
    preview: Mapping[str, Any] | None = None,
    mismatched: bool = False,
    saved: bool = False,
    run_form: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: ip.project_api(client, settings, project_id),
        database=lambda handle: ip.project_db(handle, project_id),
    )
    return render_app_page(
        request,
        principal,
        APP,
        "ip_project.html",
        selected="Projects",
        view=view,
        sourced=sourced,
        nav=_nav_projects(request, view, client, settings),
        project_id=project_id,
        action_error=action_error,
        form=dict(form or {}),
        preview=dict(preview) if preview is not None else None,
        mismatched=mismatched,
        saved=saved,
        defaults=_optional(lambda: ip.settings_api(client, settings)) if sourced.live else None,
        run_stages=ip.RUN_STAGES,
        run_form=dict(run_form or {}),
    )


@ui_router.get(
    f"{BASE}/projects/{{project_id}}", summary="One project", response_class=HTMLResponse
)
def project_page(
    request: Request, principal: CurrentOperator, project_id: str, saved: bool = False
) -> HTMLResponse:
    """One project: its fields, brief, plan summary, unit states and stage history."""
    return _project(request, principal, project_id, saved=saved)


@ui_router.post(f"{BASE}/projects/{{project_id}}/edit", summary="Edit a project from the page")
def edit_from_page(  # noqa: PLR0913 — one parameter per form field
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    title: Annotated[str, Form()] = "",
    brief: Annotated[str, Form()] = "",
    author_material: Annotated[str, Form()] = "",
    project_status: Annotated[str, Form(alias="status")] = "",
) -> Response:
    """``PUT /projects/{id}``. Saving never recompiles requirements; the plan does, when run."""
    form = {
        "title": title, "brief": brief, "author_material": author_material,
        "status": project_status,
    }  # fmt: skip
    params = {"status": project_status or None, "has_brief": bool(brief.strip())}
    client, settings = _clients(request)
    try:
        actions.update_project(
            client, settings, project_id, title=title, brief=brief,
            author_material_text=author_material, status=project_status,
        )  # fmt: skip
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.project_update", target=project_id,
            outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _project(request, principal, project_id, action_error=exc, form=form)
    _audit(
        request, principal, "ideapress.project_update", target=project_id, outcome="ok",
        params=params,
    )  # fmt: skip
    return RedirectResponse(
        _href(f"{BASE}/projects/{ip.segment(project_id)}", saved=True),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@ui_router.post(f"{BASE}/projects/{{project_id}}/delete", summary="Delete a project from the page")
def delete_from_page(
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    confirm: Annotated[str, Form()] = "",
    archive: Annotated[str, Form()] = "",
) -> Response:
    """IdeaPress's delete preview first; the delete only once the project's title is typed.

    The preview is IdeaPress's own (``DELETE`` without ``confirm``) and is a ``pending`` row. The
    title is compared with the one IdeaPress answers, never a hidden field. Archiving first writes
    the project's archive before IdeaPress removes anything, and an archive that cannot be written
    deletes nothing.
    """
    client, settings = _clients(request)
    archiving = archive == "true"
    typed = confirm.strip()
    title = ""
    try:
        current = ip.project_api(client, settings, project_id)["project"]
        title = str(current.get("title") or "")
        if not typed or typed != title:
            preview = actions.delete_project(
                client, settings, project_id, confirm=False, archive=archiving
            )
            _audit(
                request, principal, "ideapress.project_delete", target=project_id,
                outcome="pending", params={"preview": True, "archive": archiving},
            )  # fmt: skip
            return _project(request, principal, project_id, preview=preview, mismatched=bool(typed))
        result = actions.delete_project(
            client, settings, project_id, confirm=True, archive=archiving
        )
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.project_delete", target=project_id,
            outcome=outcome_of(exc),
            params={"preview": not typed, "archive": archiving}, message=exc.message,
        )  # fmt: skip
        return _project(request, principal, project_id, action_error=exc)
    written = result.get("archive")
    path = written.get("path") if isinstance(written, Mapping) else None
    _audit(
        request, principal, "ideapress.project_delete", target=project_id, outcome="ok",
        params={"preview": False, "archive": archiving, "archived": path is not None},
    )  # fmt: skip
    return RedirectResponse(
        _href(f"{BASE}/projects", deleted=title, archive=path),
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- Workflows ------------------------------------------------------------------------------------


@ui_router.get(f"{BASE}/workflows", summary="Workflows", response_class=HTMLResponse)
def workflows_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Every workflow's stage order and gates, with the limits and bindings a run would use."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: ip.workflows_api(client, settings), database=None
    )
    defaults = _optional(lambda: ip.settings_api(client, settings)) if sourced.live else None
    return render_app_page(
        request, principal, APP, "ip_workflows.html", selected="Workflows", view=view,
        sourced=sourced, defaults=defaults, workflow_id=None,
    )  # fmt: skip


@ui_router.get(
    f"{BASE}/workflows/{{workflow_id}}", summary="One workflow", response_class=HTMLResponse
)
def workflow_page(request: Request, principal: CurrentOperator, workflow_id: str) -> HTMLResponse:
    """One workflow: its stages in order, which use a model and its binding, and its gates."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: {"workflows": [ip.workflow_api(client, settings, workflow_id)["workflow"]]},
        database=None,
    )
    defaults = _optional(lambda: ip.settings_api(client, settings)) if sourced.live else None
    return render_app_page(
        request, principal, APP, "ip_workflows.html", selected="Workflows", view=view,
        sourced=sourced, defaults=defaults, workflow_id=workflow_id,
    )  # fmt: skip


# --- Backends -------------------------------------------------------------------------------------


def _backends(
    request: Request,
    principal: Principal,
    *,
    tested: Mapping[str, Any] | None = None,
    action_error: SuiteError | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: ip.backends_api(client, settings), database=None
    )
    defaults = _optional(lambda: ip.settings_api(client, settings)) if sourced.live else None
    # Row WX10: LoadCoach's own models, read beside IdeaPress's — gated on this page's own
    # liveness (not LoadCoach's), like every other secondary read on this route, so a stopped
    # IdeaPress never sends this page a second application's traffic it did not ask to make.
    loadcoach_models = _optional(lambda: lc.models_api(client, settings)) if sourced.live else None
    return render_app_page(
        request, principal, APP, "ip_backends.html", selected="Backends", view=view,
        sourced=sourced, tested=dict(tested) if tested is not None else None,
        action_error=action_error, loadcoach_models=loadcoach_models,
        stage_bindings=ip.loadcoach_bindings(defaults),
    )  # fmt: skip


@ui_router.get(f"{BASE}/backends", summary="Backends", response_class=HTMLResponse)
def backends_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Each configured backend: mode, reachability, capabilities, and where content goes."""
    return _backends(request, principal)


@ui_router.post(f"{BASE}/backends/test", summary="Test a backend from the page")
def test_from_page(
    request: Request, principal: CurrentOperator, mode: Annotated[str, Form()] = ""
) -> HTMLResponse:
    """``POST /backends/test``: the round trip's latency, model list and version, on the page."""
    client, settings = _clients(request)
    try:
        tested = actions.test_backend(client, settings, mode)
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.backend_test", target=mode or None,
            outcome=outcome_of(exc),
            params={"mode": mode or None}, message=exc.message,
        )  # fmt: skip
        return _backends(request, principal, action_error=exc)
    _audit(
        request, principal, "ideapress.backend_test", target=str(tested.get("mode") or mode or "")
        or None, outcome="ok",
        params={
            "mode": tested.get("mode"), "status": tested.get("status"),
            "latency_ms": tested.get("latency_ms"),
        },
    )  # fmt: skip
    return _backends(request, principal, tested=tested)


# --- The plan and research (Gate C) ---------------------------------------------------------------


def _project_path(project_id: str) -> str:
    return f"{BASE}/projects/{ip.segment(project_id)}"


def _task_location(project_id: str, answer: Mapping[str, Any]) -> str:
    """The console's page for the task IdeaPress answered, or the project when it named none."""
    task_id = str(answer.get("task_id") or "")
    return (
        f"{_project_path(project_id)}/tasks/{ip.segment(task_id)}"
        if task_id
        else _project_path(project_id)
    )


def _plan(  # noqa: PLR0913 — the page, and what the last action left on it
    request: Request,
    principal: Principal,
    project_id: str,
    *,
    action_error: SuiteError | None = None,
    form: Mapping[str, Any] | None = None,
    edited: str | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    plan = read_app_page(
        request,
        view,
        api=lambda: ip.plan_api(client, settings, project_id),
        database=lambda handle: ip.plan_db(handle, project_id),
    )
    research = read_app_page(
        request,
        view,
        api=lambda: ip.research_api(client, settings, project_id),
        database=lambda handle: ip.research_db(handle, project_id),
    )
    return render_app_page(
        request, principal, APP, "ip_plan.html", selected="Projects", view=view, sourced=plan,
        research=research, project_id=project_id, action_error=action_error,
        form=dict(form or {}), edited=edited,
    )  # fmt: skip


@ui_router.get(
    f"{BASE}/projects/{{project_id}}/plan", summary="A project's plan", response_class=HTMLResponse
)
def plan_page(
    request: Request, principal: CurrentOperator, project_id: str, edited: str | None = None
) -> HTMLResponse:
    """Every requirement with the material it rests on, the unit plan, its editor, research."""
    return _plan(request, principal, project_id, edited=edited)


@ui_router.post(f"{BASE}/projects/{{project_id}}/plan", summary="Run the plan from the page")
def plan_from_page(request: Request, principal: CurrentOperator, project_id: str) -> Response:
    """``POST /projects/{id}/plan``; the task's page, where the run streams."""
    client, settings = _clients(request)
    try:
        answer = actions.start_plan(client, settings, project_id)
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.plan_run", target=project_id, outcome=outcome_of(exc),
            params={}, message=exc.message,
        )  # fmt: skip
        return _plan(request, principal, project_id, action_error=exc)
    _audit(
        request, principal, "ideapress.plan_run", target=project_id, outcome="ok",
        params={"task_id": answer.get("task_id")},
    )  # fmt: skip
    return RedirectResponse(
        _task_location(project_id, answer), status_code=status.HTTP_303_SEE_OTHER
    )


@ui_router.post(f"{BASE}/projects/{{project_id}}/plan/edits", summary="Edit the plan from the page")
def plan_edit_from_page(  # noqa: PLR0913 — one parameter per form field
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    operation: Annotated[str, Form()] = "",
    unit_keys: Annotated[str, Form()] = "",
    requirement_keys: Annotated[str, Form()] = "",
    text: Annotated[str, Form()] = "",
    position: Annotated[str, Form()] = "",
) -> Response:
    """``POST …/plan/edits``; a refusal renders on the plan as IdeaPress's gate gave it."""
    form = {
        "operation": operation, "unit_keys": unit_keys, "requirement_keys": requirement_keys,
        "text": text, "position": position,
    }  # fmt: skip
    client, settings = _clients(request)
    try:
        body = actions.plan_edit_body(
            operation=operation, unit_keys=unit_keys, requirement_keys=requirement_keys,
            text=text, position=position,
        )  # fmt: skip
        actions.edit_plan(client, settings, project_id, body)
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.plan_edit", target=project_id, outcome=outcome_of(exc),
            params={"operation": operation or None}, message=exc.message,
        )  # fmt: skip
        return _plan(request, principal, project_id, action_error=exc, form=form)
    _audit(
        request, principal, "ideapress.plan_edit", target=project_id, outcome="ok",
        params={"operation": operation},
    )  # fmt: skip
    return RedirectResponse(
        _href(f"{_project_path(project_id)}/plan", edited=operation),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@ui_router.post(f"{BASE}/projects/{{project_id}}/research", summary="Run research from the page")
def research_from_page(request: Request, principal: CurrentOperator, project_id: str) -> Response:
    """The ``research`` stage: a fetch reaches only a host IdeaPress's configuration names."""
    client, settings = _clients(request)
    try:
        answer = actions.start_stage(client, settings, project_id, "research", {})
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.research_run", target=project_id,
            outcome=outcome_of(exc),
            params={}, message=exc.message,
        )  # fmt: skip
        return _plan(request, principal, project_id, action_error=exc)
    _audit(
        request, principal, "ideapress.research_run", target=project_id, outcome="ok",
        params={"task_id": answer.get("task_id")},
    )  # fmt: skip
    return RedirectResponse(
        _task_location(project_id, answer), status_code=status.HTTP_303_SEE_OTHER
    )


# --- Stage runs -----------------------------------------------------------------------------------


@ui_router.post(f"{BASE}/projects/{{project_id}}/stages", summary="Run a stage from the page")
def stage_from_page(  # noqa: PLR0913 — one parameter per form field
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    stage: Annotated[str, Form()] = "draft",
    units: Annotated[str, Form()] = "",
    resume: Annotated[str, Form()] = "",
    model_hint: Annotated[str, Form()] = "",
    max_revision_rounds: Annotated[str, Form()] = "",
) -> Response:
    """``POST …/stages/{stage}/run`` with IdeaPress's body; the task's page, where it streams.

    The audit row names the stage, how many units, resume, and which overrides were set.
    """
    form = {
        "stage": stage, "units": units, "resume": resume, "model_hint": model_hint,
        "max_revision_rounds": max_revision_rounds,
    }  # fmt: skip
    client, settings = _clients(request)
    params: dict[str, Any] = {"stage": stage, "resume": resume == "true"}
    try:
        body = actions.run_body(
            units=units, resume=resume == "true", model_hint=model_hint,
            max_revision_rounds=max_revision_rounds,
        )  # fmt: skip
        params.update(
            units=len(body.get("units") or []), overrides=sorted(body.get("overrides") or {})
        )
        answer = actions.start_stage(client, settings, project_id, stage, body)
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.stage_run", target=project_id, outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _project(request, principal, project_id, action_error=exc, run_form=form)
    _audit(
        request, principal, "ideapress.stage_run", target=project_id, outcome="ok",
        params={**params, "task_id": answer.get("task_id")},
    )  # fmt: skip
    return RedirectResponse(
        _task_location(project_id, answer), status_code=status.HTTP_303_SEE_OTHER
    )


def _task(  # noqa: PLR0913 — the page, and what the last action left on it
    request: Request,
    principal: Principal,
    project_id: str,
    task_id: str,
    *,
    action_error: SuiteError | None = None,
    cancelling: bool = False,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: ip.task_api(client, settings, project_id, task_id),
        database=lambda handle: ip.task_db(handle, project_id, task_id),
    )
    return render_app_page(
        request, principal, APP, "ip_task.html", selected="Projects", view=view,
        sourced=sourced, project_id=project_id, task_id=task_id,
        events_url=f"{_project_path(project_id)}/tasks/{ip.segment(task_id)}/events",
        action_error=action_error, cancelling=cancelling,
    )  # fmt: skip


@ui_router.get(
    f"{BASE}/projects/{{project_id}}/tasks/{{task_id}}",
    summary="One stage run",
    response_class=HTMLResponse,
)
def task_page(
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    task_id: str,
    cancelling: bool = False,
) -> HTMLResponse:
    """One stage run: its state, counts and attempts; live while it runs; its events after."""
    return _task(request, principal, project_id, task_id, cancelling=cancelling)


@ui_router.get(
    f"{BASE}/projects/{{project_id}}/tasks/{{task_id}}/events", summary="A stage run, live"
)
def task_events(
    request: Request, principal: CurrentOperator, project_id: str, task_id: str
) -> StreamingResponse:
    """IdeaPress's task stream, proxied as the console's log-pane frames."""
    chunks = app_stream(
        request.app.state.http,
        request.app.state.settings,
        APP,
        f"projects/{ip.segment(project_id)}/tasks/{ip.segment(task_id)}/stream",
        last_event_id=request.headers.get("last-event-id"),
    )
    return StreamingResponse(
        ip.task_log_frames(chunks),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@ui_router.post(
    f"{BASE}/projects/{{project_id}}/tasks/{{task_id}}/cancel", summary="Cancel from the page"
)
def cancel_from_page(
    request: Request, principal: CurrentOperator, project_id: str, task_id: str
) -> Response:
    """``POST …/cancel``; the run's page says it is honoured at the next model-call boundary."""
    client, settings = _clients(request)
    try:
        answer = actions.cancel_task(client, settings, project_id, task_id)
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.stage_cancel", target=task_id, outcome=outcome_of(exc),
            params={"project_id": project_id}, message=exc.message,
        )  # fmt: skip
        return _task(request, principal, project_id, task_id, action_error=exc)
    _audit(
        request, principal, "ideapress.stage_cancel", target=task_id, outcome="ok",
        params={"project_id": project_id, "cancelling": answer.get("cancelling")},
    )  # fmt: skip
    return RedirectResponse(
        _href(f"{_project_path(project_id)}/tasks/{ip.segment(task_id)}", cancelling=True),
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- Units ----------------------------------------------------------------------------------------


@ui_router.get(f"{BASE}/units", summary="Units", response_class=HTMLResponse)
def units_page(
    request: Request,
    principal: CurrentOperator,
    project: str | None = None,
    cursor: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """One project's units — the newest project's until another is chosen — with their states.

    The project picker itself is paged (row WX5): before this row it always showed only the
    first page of projects (``cursor=None``), so a project past ``[ui] page_rows`` could not be
    chosen here at all.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    page_rows = settings.ui.page_rows
    projects = read_app_page(
        request,
        view,
        api=lambda: ip.projects_api(
            client, settings, status=None, content_type=None, archived=False, cursor=cursor,
            page_rows=page_rows,
        ),
        database=lambda handle: ip.projects_db(
            handle, status=None, content_type=None, archived=False, page=page, page_rows=page_rows
        ),
    )  # fmt: skip
    data = projects.data or {}
    listed = data.get("items") or []
    chosen = project or (str(listed[0].get("id")) if listed else None)
    next_href = None
    if data.get("next_cursor"):
        next_href = _href(f"{BASE}/units", project=chosen, cursor=data["next_cursor"])
    elif data.get("next_page"):
        next_href = _href(f"{BASE}/units", project=chosen, page=data["next_page"])
    detail = (
        read_app_page(
            request,
            view,
            api=lambda: ip.project_api(client, settings, chosen),
            database=lambda handle: ip.project_db(handle, chosen),
        )
        if chosen
        else None
    )
    return render_app_page(
        request, principal, APP, "ip_units.html", selected="Units", view=view, sourced=projects,
        detail=detail, chosen=chosen, next_href=next_href,
    )  # fmt: skip


def _unit(  # noqa: PLR0913 — the page, and what the last action left on it
    request: Request,
    principal: Principal,
    project_id: str,
    unit_key: str,
    *,
    action_error: SuiteError | None = None,
    form: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: ip.unit_api(client, settings, project_id, unit_key),
        database=lambda handle: ip.unit_db(handle, project_id, unit_key),
    )
    unit = (sourced.data or {}).get("unit") or {}
    running = None
    if sourced.live:
        found = _optional(lambda: ip.project_api(client, settings, project_id))
        running = ((found or {}).get("project") or {}).get("running_task_id")
    content = str(unit.get("content") or "")
    return render_app_page(
        request, principal, APP, "ip_unit.html", selected="Units", view=view, sourced=sourced,
        project_id=project_id, unit_key=unit_key,
        content_html=render_reply(content) if content else None, running_task_id=running,
        action_error=action_error, form=dict(form or {}),
    )  # fmt: skip


@ui_router.get(
    f"{BASE}/projects/{{project_id}}/units/{{unit_key}}",
    summary="One unit",
    response_class=HTMLResponse,
)
def unit_page(
    request: Request, principal: CurrentOperator, project_id: str, unit_key: str
) -> HTMLResponse:
    """One unit: its content, full provenance, every version, and what IdeaPress allows next."""
    return _unit(request, principal, project_id, unit_key)


@ui_router.post(
    f"{BASE}/projects/{{project_id}}/units/{{unit_key}}/revise", summary="Revise from the page"
)
def revise_from_page(
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    unit_key: str,
    instructions: Annotated[str, Form()] = "",
) -> Response:
    """``POST …/revise`` with the author's instructions; the revision's task page.

    The audit row says whether instructions were given, never what they said. The unit is
    ``unit``, not ``unit_key``: the redaction masks any parameter whose name holds "key".
    """
    client, settings = _clients(request)
    params = {"unit": unit_key, "has_instructions": bool(instructions.strip())}
    try:
        answer = actions.revise_unit(client, settings, project_id, unit_key, instructions)
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.unit_revise", target=project_id, outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _unit(
            request, principal, project_id, unit_key, action_error=exc,
            form={"instructions": instructions},
        )  # fmt: skip
    _audit(
        request, principal, "ideapress.unit_revise", target=project_id, outcome="ok",
        params={**params, "task_id": answer.get("task_id")},
    )  # fmt: skip
    return RedirectResponse(
        _task_location(project_id, answer), status_code=status.HTTP_303_SEE_OTHER
    )


@ui_router.post(
    f"{BASE}/projects/{{project_id}}/units/{{unit_key}}/resume", summary="Resume from the page"
)
def resume_from_page(
    request: Request, principal: CurrentOperator, project_id: str, unit_key: str
) -> Response:
    """A draft run over the unit with ``resume`` — IdeaPress's own resume — and its task page."""
    client, settings = _clients(request)
    try:
        answer = actions.resume_unit(client, settings, project_id, unit_key)
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.unit_resume", target=project_id, outcome=outcome_of(exc),
            params={"unit": unit_key}, message=exc.message,
        )  # fmt: skip
        return _unit(request, principal, project_id, unit_key, action_error=exc)
    _audit(
        request, principal, "ideapress.unit_resume", target=project_id, outcome="ok",
        params={"unit": unit_key, "task_id": answer.get("task_id")},
    )  # fmt: skip
    return RedirectResponse(
        _task_location(project_id, answer), status_code=status.HTTP_303_SEE_OTHER
    )


# --- The workspace and export ---------------------------------------------------------------------


@ui_router.get(
    f"{BASE}/projects/{{project_id}}/workspace",
    summary="A project's workspace",
    response_class=HTMLResponse,
)
def workspace_page(
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    unit: str = "",
    compare: int | None = None,
) -> HTMLResponse:
    """IdeaPress's workspace: the navigator, one unit read, judged and directed, on one page."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: ip.workspace_api(client, settings, project_id, unit=unit, compare=compare),
        database=None,
    )
    focused = (sourced.data or {}).get("unit") or {}
    content = str(focused.get("content") or "")
    return render_app_page(
        request, principal, APP, "ip_workspace.html", selected="Projects", view=view,
        sourced=sourced, project_id=project_id,
        content_html=render_reply(content) if content else None,
    )  # fmt: skip


def _export(
    request: Request,
    principal: Principal,
    project_id: str,
    *,
    action_error: SuiteError | None = None,
    written: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: ip.export_api(client, settings, project_id), database=None
    )
    return render_app_page(
        request, principal, APP, "ip_export.html", selected="Projects", view=view,
        sourced=sourced, project_id=project_id, action_error=action_error,
        written=dict(written) if written is not None else None,
    )  # fmt: skip


@ui_router.get(
    f"{BASE}/projects/{{project_id}}/export", summary="Export", response_class=HTMLResponse
)
def export_page(request: Request, principal: CurrentOperator, project_id: str) -> HTMLResponse:
    """The formats and what each contains, what an export would include, download or write."""
    return _export(request, principal, project_id)


@ui_router.post(f"{BASE}/projects/{{project_id}}/export", summary="Write an export from the page")
def export_from_page(
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    fmt: Annotated[str, Form(alias="format")] = "markdown",
) -> HTMLResponse:
    """``POST /projects/{id}/export``: the page again, naming where IdeaPress wrote the file."""
    client, settings = _clients(request)
    try:
        written = actions.write_export(client, settings, project_id, fmt)
    except SuiteError as exc:
        _audit(
            request, principal, "ideapress.export_write", target=project_id,
            outcome=outcome_of(exc),
            params={"format": fmt}, message=exc.message,
        )  # fmt: skip
        return _export(request, principal, project_id, action_error=exc)
    _audit(
        request, principal, "ideapress.export_write", target=project_id, outcome="ok",
        params={"format": fmt, "units": written.get("units"), "sha256": written.get("sha256")},
    )  # fmt: skip
    return _export(request, principal, project_id, written=written)


@ui_router.get(f"{BASE}/projects/{{project_id}}/export/download", summary="Download an export")
def export_download(
    request: Request,
    principal: CurrentOperator,
    project_id: str,
    fmt: Annotated[str, Query(alias="format")] = "markdown",
) -> Response:
    """The rendered document as a download, written nowhere: an attachment, never shown inline.

    An HTML export is the author's and a model's text; served as an attachment, it never runs in
    the console's origin.
    """
    client, settings = _clients(request)
    try:
        media, body = actions.read_export(client, settings, project_id, fmt)
    except SuiteError as exc:
        return _export(request, principal, project_id, action_error=exc)
    name = project_id if project_id.isalnum() else "ideapress"
    extension = {"markdown": "md", "html": "html", "json": "json"}.get(fmt, "txt")
    return Response(
        body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}.{extension}"'},
    )

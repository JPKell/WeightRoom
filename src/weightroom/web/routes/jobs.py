"""weightroom.web.routes.jobs — the queue, its schedules and their pages (api.md §7, spec §7.10).

Every state-changing route writes exactly one audit row, success or refusal (spec §11 contract 2):
``job.enqueue``, ``job.cancel``, ``job.schedule``. The run itself is the worker's ``job.run`` row.

Two things queued here are security actions, re-authenticated the way their curated routes are:
restoring WeightRoomGym's own database, which also needs ``weightroom`` typed (ADR-0136 rule 1), and
a retention trim that deletes FreeWeight's stored results (ADR-0134 rule 2) — whether queued now or
written into a schedule, so a schedule is never the way around the password.
"""

from __future__ import annotations

from typing import Annotated, Any

from baseaicore import SuiteError
from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from mirrorwall import clamp_limit, paginated_response
from pydantic import BaseModel, ConfigDict, Field

from weightroom.domain.jobs import (
    JOB_KINDS,
    SELF_RESTORE_CONFIRMATION,
    JobParamsInvalid,
    needs_reauth,
)
from weightroom.services.audit import record
from weightroom.services.auth import Principal, require_fresh_reauth
from weightroom.services.jobs import (
    JobView,
    ScheduleView,
    enqueue,
    get_job,
    get_schedule,
    list_jobs,
    list_schedules,
    params_from_text,
    request_cancel,
    update_schedule,
)
from weightroom.web.rendering import render
from weightroom.web.routes.apps import render_shell_page
from weightroom.web.session import CurrentOperator, now_of, reauthenticated

__all__ = ["router", "ui_router"]

router = APIRouter(tags=["jobs"])
ui_router = APIRouter(tags=["ui"], include_in_schema=False)


class EnqueueBody(BaseModel):
    """``POST /jobs`` (api.md §7): a kind and its parameters, or a schedule to run now."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="", max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    schedule_id: str | None = Field(default=None, max_length=26)
    name_typed: str = Field(default="", max_length=64)


class ScheduleBody(BaseModel):
    """``PUT /jobs/schedules/{id}`` (api.md §7): any of the three; one left out is unchanged."""

    model_config = ConfigDict(extra="forbid")

    cron: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    params: dict[str, Any] | None = None


def _audit(
    request: Request,
    principal: Principal,
    action: str,
    *,
    outcome: str,
    target: str | None,
    params: dict[str, Any],
    message: str | None = None,
    security: bool = False,
) -> None:
    record(
        request.app.state.database,
        action=action,
        actor="operator",
        outcome=outcome,
        now=now_of(request),
        operator_id=principal.operator_id,
        app="weightroom",
        target=target,
        params=params,
        message=message,
        security=security,
        request_id=getattr(request.state, "request_id", None),
    )


def _wake(request: Request) -> None:
    worker = getattr(request.app.state, "jobs", None)
    if worker is not None:
        worker.wake()


def enqueue_job(
    request: Request,
    principal: Principal,
    *,
    kind: str,
    params: dict[str, Any],
    schedule_id: str | None,
    name_typed: str = "",
) -> JobView:
    """Queue one job — or a schedule's kind and parameters, run now — and audit it once.

    Also FreeWeight's Runs page's *Start* (row WP3): a run it starts is this `job.enqueue` row.
    """
    state = request.app.state
    now = now_of(request)
    security = False
    try:
        if schedule_id:
            schedule = get_schedule(state.database, schedule_id)
            kind, params = schedule.kind, schedule.params
        security = needs_reauth(kind, params)
        if security:
            require_fresh_reauth(principal, now=now, auth=state.settings.auth)
        if kind == "self_restore" and name_typed.strip() != SELF_RESTORE_CONFIRMATION:
            raise JobParamsInvalid(
                f"Type {SELF_RESTORE_CONFIRMATION} to restore WeightRoomGym's own database: the "
                "console stops for the restore, and every row written since that backup moves to "
                "a file beside it (ADR-0136).",
                details={"name_typed": name_typed},
            )
        job = enqueue(state.database, kind=kind, params=params, now=now, schedule_id=schedule_id)
    except SuiteError as exc:
        _audit(
            request,
            principal,
            "job.enqueue",
            outcome="refused",
            target=schedule_id or kind or None,
            params={"kind": kind, "params": params, "schedule_id": schedule_id},
            message=exc.message,
            security=security,
        )
        raise
    _audit(
        request,
        principal,
        "job.enqueue",
        outcome="ok",
        target=job.id,
        params={"kind": job.kind, "params": job.params, "schedule_id": job.schedule_id},
        security=security,
    )
    _wake(request)
    return job


def _cancel(request: Request, principal: Principal, job_id: str) -> JobView:
    try:
        job = request_cancel(request.app.state.database, job_id, now=now_of(request))
    except SuiteError as exc:
        _audit(
            request,
            principal,
            "job.cancel",
            outcome="refused",
            target=job_id,
            params={},
            message=exc.message,
        )
        raise
    _audit(
        request,
        principal,
        "job.cancel",
        outcome="ok",
        target=job_id,
        params={"state": job.state, "requested": job.cancel_requested_at is not None},
    )
    return job


def _update(
    request: Request,
    principal: Principal,
    schedule_id: str,
    *,
    cron: str | None,
    enabled: bool | None,
    params: dict[str, Any] | None,
) -> ScheduleView:
    state = request.app.state
    now = now_of(request)
    security = False
    try:
        current = get_schedule(state.database, schedule_id)
        security = params is not None and needs_reauth(current.kind, params)
        if security:
            require_fresh_reauth(principal, now=now, auth=state.settings.auth)
        view = update_schedule(
            state.database, schedule_id, now=now, cron=cron, enabled=enabled, params=params
        )
    except SuiteError as exc:
        _audit(
            request,
            principal,
            "job.schedule",
            outcome="refused",
            target=schedule_id,
            params={"cron": cron, "enabled": enabled, "params": params},
            message=exc.message,
            security=security,
        )
        raise
    _audit(
        request,
        principal,
        "job.schedule",
        outcome="ok",
        target=schedule_id,
        params={
            "kind": view.kind,
            "cron": view.cron,
            "enabled": view.enabled,
            "params": view.params,
        },
        security=security,
    )
    _wake(request)
    return view


# --- API ------------------------------------------------------------------------------------------


@router.get("/jobs", summary="The queue, newest first")
def get_jobs(
    request: Request,
    principal: CurrentOperator,
    state: str | None = None,
    kind: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> JSONResponse:
    """A page of jobs, filtered by ``state`` and ``kind``."""
    effective = clamp_limit(limit)
    rows, has_more = list_jobs(
        request.app.state.database, limit=effective, state=state, kind=kind, before_id=cursor
    )
    return paginated_response(
        [row.as_json() for row in rows],
        limit=effective,
        next_cursor=rows[-1].id if has_more and rows else None,
        has_more=has_more,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED, summary="Queue a job")
def post_job(request: Request, principal: CurrentOperator, body: EnqueueBody) -> JSONResponse:
    """``{kind, params}``, or ``{schedule_id}`` to run a schedule now; ``202`` with the job."""
    job = enqueue_job(
        request,
        principal,
        kind=body.kind,
        params=body.params,
        schedule_id=body.schedule_id,
        name_typed=body.name_typed,
    )
    return JSONResponse(content=job.as_json(), status_code=status.HTTP_202_ACCEPTED)


@router.get("/jobs/schedules", summary="Every schedule")
def get_schedules(request: Request, principal: CurrentOperator) -> JSONResponse:
    """Each schedule with its next and last run, in UTC."""
    return JSONResponse(
        content={
            "timezone": "UTC",
            "schedules": [one.as_json() for one in list_schedules(request.app.state.database)],
        }
    )


@router.put("/jobs/schedules/{schedule_id}", summary="Change a schedule")
def put_schedule(
    request: Request, principal: CurrentOperator, schedule_id: str, body: ScheduleBody
) -> JSONResponse:
    """The cron, the parameters or the enabled flag; enabling validates the parameters."""
    view = _update(
        request,
        principal,
        schedule_id,
        cron=body.cron,
        enabled=body.enabled,
        params=body.params,
    )
    return JSONResponse(content=view.as_json())


@router.get("/jobs/{job_id}", summary="One job, with its output")
def get_one_job(request: Request, principal: CurrentOperator, job_id: str) -> JSONResponse:
    """``404 JOB_NOT_FOUND`` for an id that is not in the queue."""
    return JSONResponse(content=get_job(request.app.state.database, job_id).as_json())


@router.post("/jobs/{job_id}/cancel", summary="Cancel a job")
def post_cancel(request: Request, principal: CurrentOperator, job_id: str) -> JSONResponse:
    """A queued job is cancelled; a running one is asked to stop; a finished one is
    ``409 JOB_INVALID_STATE``."""
    return JSONResponse(content=_cancel(request, principal, job_id).as_json())


# --- Pages ----------------------------------------------------------------------------------------


def _page(request: Request, principal: Principal, /, **overrides: Any) -> HTMLResponse:
    database = request.app.state.database
    running, _more = list_jobs(database, limit=50, state="running")
    queued, _more = list_jobs(database, limit=50, state="queued")
    history, history_more = list_jobs(database, limit=50)
    context: dict[str, Any] = {"error": None, "notice": None, **overrides}
    return render_shell_page(
        request,
        "jobs.html",
        page="jobs",
        principal=principal,
        active=[*running, *queued],
        history=history,
        history_more=history_more,
        schedules=list_schedules(database),
        kinds=JOB_KINDS,
        confirmation=SELF_RESTORE_CONFIRMATION,
        **context,
    )


def _acting(request: Request, principal: Principal, password: str) -> Principal:
    return (reauthenticated(request, principal, password) or principal) if password else principal


def _parsed(
    request: Request, principal: Principal, action: str, target: str | None, text: str
) -> dict[str, Any]:
    """A form's parameters as an object; a refusal is audited under the action it belonged to."""
    try:
        return params_from_text(text)
    except SuiteError as exc:
        _audit(
            request,
            principal,
            action,
            outcome="refused",
            target=target,
            params={"params": text[:200]},
            message=exc.message,
        )
        raise


@ui_router.get("/jobs", summary="The Jobs page", response_class=HTMLResponse)
def jobs_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """What is running and queued, the schedules, and the history."""
    return _page(request, principal)


@ui_router.post("/jobs/enqueue", summary="Queue a job from the page")
def enqueue_from_page(
    request: Request,
    principal: CurrentOperator,
    kind: Annotated[str, Form()] = "",
    params: Annotated[str, Form()] = "",
    schedule_id: Annotated[str, Form()] = "",
    name_typed: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> Response:
    """Queue a kind with JSON parameters, or run a schedule now; the job's page on success."""
    acting = _acting(request, principal, password)
    try:
        parsed = {} if schedule_id else _parsed(request, acting, "job.enqueue", kind, params)
        job = enqueue_job(
            request,
            acting,
            kind=kind,
            params=parsed,
            schedule_id=schedule_id or None,
            name_typed=name_typed,
        )
    except SuiteError as exc:
        return _page(request, acting, error=exc)
    return RedirectResponse(f"/jobs/{job.id}", status_code=status.HTTP_303_SEE_OTHER)


@ui_router.post("/jobs/schedules/{schedule_id}", summary="Change a schedule from the page")
def schedule_from_page(
    request: Request,
    principal: CurrentOperator,
    schedule_id: str,
    cron: Annotated[str, Form()] = "",
    params: Annotated[str, Form()] = "",
    enabled: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """The whole schedule as the form shows it: an unticked box disables it."""
    acting = _acting(request, principal, password)
    try:
        parsed = _parsed(request, acting, "job.schedule", schedule_id, params)
        view = _update(
            request,
            acting,
            schedule_id,
            cron=cron or None,
            enabled=enabled == "true",
            params=parsed,
        )
    except SuiteError as exc:
        return _page(request, acting, error=exc)
    when = f"next run {view.next_run_at:%Y-%m-%d %H:%M} UTC" if view.next_run_at else "disabled"
    return _page(request, acting, notice=f"{view.kind} saved: {when}.")


@ui_router.get("/jobs/{job_id}", summary="One job's page", response_class=HTMLResponse)
def job_page(request: Request, principal: CurrentOperator, job_id: str) -> HTMLResponse:
    """The job, its parameters and its output, refreshed while it runs."""
    job = get_job(request.app.state.database, job_id)
    return render_shell_page(request, "job.html", page="jobs", principal=principal, job=job)


@ui_router.get("/jobs/{job_id}/output", summary="One job's output", response_class=HTMLResponse)
def job_output(request: Request, principal: CurrentOperator, job_id: str) -> HTMLResponse:
    """The output fragment the job page swaps in every two seconds while the job runs."""
    return HTMLResponse(render("_job_output.html", job=get_job(request.app.state.database, job_id)))


@ui_router.post("/jobs/{job_id}/cancel", summary="Cancel a job from the page")
def cancel_from_page(
    request: Request,
    principal: CurrentOperator,
    job_id: str,
    next_path: Annotated[str | None, Form(alias="next")] = None,
) -> Response:
    """Cancel, then back to the job's page — or to the application page the button sat on
    (``next``: a path under ``/apps/`` only, so the redirect never leaves the console)."""
    try:
        _cancel(request, principal, job_id)
    except SuiteError as exc:
        return _page(request, principal, error=exc)
    back = f"/jobs/{job_id}"
    if next_path and next_path.startswith("/apps/") and "//" not in next_path:
        if "\\" not in next_path:
            back = next_path
    return RedirectResponse(back, status_code=status.HTTP_303_SEE_OTHER)

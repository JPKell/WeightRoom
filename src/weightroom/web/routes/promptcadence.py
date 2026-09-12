"""weightroom.web.routes.promptcadence — PromptCadence's pages under its tab (row WP1).

Trajectories, Approvals, Tiers, Tools, Ledger and Egress, at parity with PromptCadence's own console
(its ``web/routes/console.py``), which a browser on the LAN cannot reach: PromptCadence binds
loopback (ADR-0126). Every page reads by spec §7.3's rule (``services/app_pages``) through the
readers in ``services/promptcadence_pages`` and renders through ``render_app_page``.

The four actions — submit, cancel, grant, deny — are form posts, each writing exactly one audit
row whether PromptCadence accepts or refuses (spec §11 contract 2). A refusal renders on the page
it came from, in PromptCadence's words, with what the operator typed kept; a grant or a denial is a
``security`` row, as it is from a chat thread, because it authorises spend or egress.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Annotated, Any, Final

from baseaicore import SuiteError
from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

from weightroom.services import promptcadence_actions as actions
from weightroom.services import promptcadence_pages as pc
from weightroom.services.app_api import outcome_of
from weightroom.services.app_api import stream as app_stream
from weightroom.services.audit import record
from weightroom.web.routes.apps import app_view, read_app_page, render_app_page
from weightroom.web.session import CurrentOperator, now_of

if TYPE_CHECKING:
    from weightroom.services.auth import Principal

__all__ = ["ui_router"]

ui_router = APIRouter(tags=["ui"], include_in_schema=False)

APP = pc.APP
BASE = "/apps/promptcadence"
_DECISION_ACTIONS = {"approve": "trajectory.approve", "deny": "trajectory.deny"}


def _href(path: str, **query: Any) -> str:
    """``path`` with the query parameters that carry a value, so a pager keeps the filters."""
    from urllib.parse import urlencode

    kept = {key: value for key, value in query.items() if value not in (None, "")}
    return f"{path}?{urlencode(kept)}" if kept else path


def _within(next_path: str | None, default: str) -> str:
    """``next`` when it is a page of PromptCadence's tab, else ``default``: no open redirect."""
    if next_path and next_path.startswith(BASE + "/") and "//" not in next_path:
        if "\\" not in next_path:
            return next_path
    return default


def _audit(
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
        security=action in _DECISION_ACTIONS.values(),
        request_id=getattr(request.state, "request_id", None),
    )


# --- Trajectories ---------------------------------------------------------------------------------


def _trajectories(
    request: Request,
    principal: Principal,
    *,
    state: str | None,
    cursor: str | None,
    page: int,
    submit_error: SuiteError | None = None,
    form: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = request.app.state.http, request.app.state.settings
    page_rows = settings.ui.page_rows
    sourced = read_app_page(
        request,
        view,
        api=lambda: pc.trajectories_api(
            client, settings, state=state, cursor=cursor, page_rows=page_rows
        ),
        database=lambda handle: pc.trajectories_db(
            handle, state=state, page=page, page_rows=page_rows
        ),
    )
    data = sourced.data or {}
    next_href = None
    if data.get("next_cursor"):
        next_href = _href(f"{BASE}/trajectories", state=state, cursor=data["next_cursor"])
    elif data.get("next_page"):
        next_href = _href(f"{BASE}/trajectories", state=state, page=data["next_page"])
    return render_app_page(
        request,
        principal,
        APP,
        "pc_trajectories.html",
        selected="Trajectories",
        view=view,
        sourced=sourced,
        state=state or "",
        states=pc.TRAJECTORY_STATES,
        next_href=next_href,
        options=actions.submission_options(client, settings) if sourced.live else None,
        classifications=actions.CLASSIFICATIONS,
        submit_error=submit_error,
        form=dict(form or {}),
    )


@ui_router.get(f"{BASE}/trajectories", summary="Trajectories", response_class=HTMLResponse)
def trajectories_page(
    request: Request,
    principal: CurrentOperator,
    state: str | None = None,
    cursor: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """Every trajectory, newest first, filterable by state; and the New-trajectory form."""
    return _trajectories(request, principal, state=state or None, cursor=cursor or None, page=page)


@ui_router.post(f"{BASE}/trajectories", summary="Submit a trajectory from the page")
def submit_from_page(  # noqa: PLR0913 — one parameter per form field, as FastAPI reads them
    request: Request,
    principal: CurrentOperator,
    task: Annotated[str, Form()] = "",
    data_classification: Annotated[str, Form()] = "",
    project: Annotated[str, Form()] = "",
    tools: Annotated[list[str] | None, Form()] = None,
    tier: Annotated[str, Form()] = "",
    max_steps: Annotated[str, Form()] = "",
    max_turns: Annotated[str, Form()] = "",
    bypass_planning: Annotated[str, Form()] = "",
    budget_tokens: Annotated[str, Form()] = "",
    budget_money: Annotated[str, Form()] = "",
    currency: Annotated[str, Form()] = "USD",
    partial_pricing: Annotated[str, Form()] = "",
) -> Response:
    """``POST /trajectories`` with the form's body; the new trajectory's record on success.

    The audit row names the classification, the tools, the tier and whether a budget was set —
    never the task, which is the operator's text (as a chat message's row never carries it).
    """
    form = {
        "task": task,
        "data_classification": data_classification,
        "project": project,
        "tools": list(tools or []),
        "tier": tier,
        "max_steps": max_steps,
        "max_turns": max_turns,
        "bypass_planning": bypass_planning,
        "budget_tokens": budget_tokens,
        "budget_money": budget_money,
        "currency": currency,
        "partial_pricing": partial_pricing,
    }
    params = {
        "classification": data_classification or "confidential",
        "tools": sorted(form["tools"]),
        "tier": tier or None,
        "project": project or None,
        "budgeted": bool(budget_tokens or budget_money),
    }
    client, settings = request.app.state.http, request.app.state.settings
    try:
        body = actions.submission_body(
            task=task,
            classification=data_classification,
            project=project,
            tools=form["tools"],
            tier=tier,
            max_steps=max_steps,
            max_turns=max_turns,
            bypass_planning=bypass_planning,
            budget_tokens=budget_tokens,
            budget_money=budget_money,
            currency=currency,
            partial_pricing=partial_pricing,
        )
        document = actions.submit(client, settings, body)
    except SuiteError as exc:
        _audit(
            request, principal, "trajectory.submit", target=None, outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _trajectories(
            request, principal, state=None, cursor=None, page=1, submit_error=exc, form=form
        )
    trajectory_id = str(document.get("trajectory_id") or "")
    _audit(
        request, principal, "trajectory.submit", target=trajectory_id or None, outcome="ok",
        params={**params, "state": document.get("state")},
    )  # fmt: skip
    location = (
        f"{BASE}/trajectories/{pc.segment(trajectory_id)}"
        if trajectory_id
        else f"{BASE}/trajectories"
    )
    return RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)


def _trajectory(
    request: Request,
    principal: Principal,
    trajectory_id: str,
    *,
    action_error: SuiteError | None = None,
) -> HTMLResponse:
    from weightroom.services.chat_promptcadence import token_can_approve

    view = app_view(request, APP)
    client, settings = request.app.state.http, request.app.state.settings
    sourced = read_app_page(
        request,
        view,
        api=lambda: pc.trajectory_api(client, settings, trajectory_id),
        database=lambda handle: pc.trajectory_db(handle, trajectory_id),
    )
    return render_app_page(
        request,
        principal,
        APP,
        "pc_trajectory.html",
        selected="Trajectories",
        view=view,
        sourced=sourced,
        trajectory_id=trajectory_id,
        events_url=f"{BASE}/trajectories/{pc.segment(trajectory_id)}/events",
        can_approve=token_can_approve(settings) if sourced.live else None,
        action_error=action_error,
    )


@ui_router.get(
    f"{BASE}/trajectories/{{trajectory_id}}", summary="One trajectory", response_class=HTMLResponse
)
def trajectory_page(
    request: Request, principal: CurrentOperator, trajectory_id: str
) -> HTMLResponse:
    """One trajectory's whole record: request, plan, envelopes, turns, tools, debits, egress."""
    return _trajectory(request, principal, trajectory_id)


@ui_router.post(f"{BASE}/trajectories/{{trajectory_id}}/cancel", summary="Cancel from the page")
def cancel_from_page(request: Request, principal: CurrentOperator, trajectory_id: str) -> Response:
    """``POST /trajectories/{id}/cancel``; the record again, with a refusal on it if one came."""
    client, settings = request.app.state.http, request.app.state.settings
    try:
        document = actions.cancel(client, settings, trajectory_id)
    except SuiteError as exc:
        _audit(
            request, principal, "trajectory.cancel", target=trajectory_id, outcome=outcome_of(exc),
            params={}, message=exc.message,
        )  # fmt: skip
        return _trajectory(request, principal, trajectory_id, action_error=exc)
    _audit(
        request, principal, "trajectory.cancel", target=trajectory_id, outcome="ok",
        params={
            "state": document.get("state"),
            "cancel_requested": document.get("cancel_requested"),
        },
    )  # fmt: skip
    return RedirectResponse(
        f"{BASE}/trajectories/{pc.segment(trajectory_id)}", status_code=status.HTTP_303_SEE_OTHER
    )


@ui_router.get(f"{BASE}/trajectories/{{trajectory_id}}/events", summary="A trajectory, live")
def trajectory_events(
    request: Request, principal: CurrentOperator, trajectory_id: str
) -> StreamingResponse:
    """PromptCadence's trajectory stream, proxied as the console's log-pane frames."""
    chunks = app_stream(
        request.app.state.http,
        request.app.state.settings,
        APP,
        f"trajectories/{pc.segment(trajectory_id)}/stream",
        last_event_id=request.headers.get("last-event-id"),
    )
    return StreamingResponse(
        pc.event_log_frames(chunks),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


# --- Approvals ------------------------------------------------------------------------------------


_DONE: Final[dict[str, str]] = {
    "granted": "Granted. The trajectory runs on under the envelope this decision minted.",
    "granted_raised": "Granted with a new ceiling. The trajectory runs on under it.",
    "denied": "Denied. The trajectory is halted, with the reason on its record.",
}
"""What a finished decision says on the page it lands on, keyed by the redirect's ``done``.

Fixed sentences, as FreeWeight's goal pages do it: nothing a URL carries is ever rendered as prose.
The page showed the decision's new state and said nothing about it until row WPF1 (§4 of
``WP6_HANDOFF.md``)."""


def _approvals(
    request: Request,
    principal: Principal,
    *,
    cursor: str | None = None,
    page: int = 1,
    action_error: SuiteError | None = None,
    done: str | None = None,
) -> HTMLResponse:
    from weightroom.services.chat_promptcadence import token_can_approve

    view = app_view(request, APP)
    client, settings = request.app.state.http, request.app.state.settings
    page_rows = settings.ui.page_rows
    pending = read_app_page(
        request, view, api=lambda: pc.pending_api(client, settings), database=pc.pending_db
    )
    history = read_app_page(
        request,
        view,
        api=lambda: pc.requests_api(client, settings, cursor=cursor, page_rows=page_rows),
        database=lambda handle: pc.requests_db(handle, page=page, page_rows=page_rows),
    )
    history_data = history.data or {}
    next_href = None
    if history_data.get("next_cursor"):
        next_href = _href(f"{BASE}/approvals", cursor=history_data["next_cursor"])
    elif history_data.get("next_page"):
        next_href = _href(f"{BASE}/approvals", page=history_data["next_page"])
    return render_app_page(
        request,
        principal,
        APP,
        "pc_approvals.html",
        selected="Approvals",
        view=view,
        pending=pending,
        history=history,
        history_next_href=next_href,
        can_approve=token_can_approve(settings) if pending.live else None,
        action_error=action_error,
        done_message=_DONE.get(done or ""),
    )


@ui_router.get(f"{BASE}/approvals", summary="Approvals", response_class=HTMLResponse)
def approvals_page(
    request: Request,
    principal: CurrentOperator,
    done: str = "",
    cursor: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """What is waiting for a person, and every request ever raised."""
    return _approvals(request, principal, cursor=cursor or None, page=page, done=done)


def _decide(
    request: Request,
    principal: Principal,
    trajectory_id: str,
    decision: str,
    next_path: str | None,
    *,
    reason: str = "",
    budget_tokens: str = "",
    budget_money: str = "",
    currency: str = "USD",
) -> Response:
    action = _DECISION_ACTIONS[decision]
    client, settings = request.app.state.http, request.app.state.settings
    raised = bool(budget_tokens.strip() or budget_money.strip())
    try:
        actions.require_approve_scope(settings)
        budget = (
            actions.budget_raise(tokens=budget_tokens, amount=budget_money, currency=currency)
            if decision == "approve"
            else None
        )
        result = actions.decide(
            client, settings, trajectory_id, decision, reason=reason.strip() or None, budget=budget
        )
    except SuiteError as exc:
        _audit(
            request, principal, action, target=trajectory_id, outcome=outcome_of(exc),
            params={"raised": raised}, message=exc.message,
        )  # fmt: skip
        return _approvals(request, principal, action_error=exc)
    resolved = result.get("request")
    resolved = resolved if isinstance(resolved, Mapping) else {}
    _audit(
        request,
        principal,
        action,
        target=trajectory_id,
        outcome="ok",
        params={
            "request_id": resolved.get("request_id"),
            "kind": resolved.get("kind"),
            "state": result.get("state"),
            "already_resolved": result.get("already_resolved"),
            "raised": raised,
        },
    )
    done = "denied" if decision != "approve" else ("granted_raised" if raised else "granted")
    return RedirectResponse(
        _within(next_path, f"{BASE}/approvals?done={done}"), status_code=status.HTTP_303_SEE_OTHER
    )


@ui_router.post(f"{BASE}/approvals/{{trajectory_id}}/grant", summary="Grant from the page")
def grant_from_page(
    request: Request,
    principal: CurrentOperator,
    trajectory_id: str,
    budget_tokens: Annotated[str, Form()] = "",
    budget_money: Annotated[str, Form()] = "",
    currency: Annotated[str, Form()] = "USD",
    next_path: Annotated[str | None, Form(alias="next")] = None,
) -> Response:
    """Grant the trajectory's pending request with the console's ``approve`` token (ADR-0049)."""
    return _decide(
        request, principal, trajectory_id, "approve", next_path,
        budget_tokens=budget_tokens, budget_money=budget_money, currency=currency,
    )  # fmt: skip


@ui_router.post(f"{BASE}/approvals/{{trajectory_id}}/deny", summary="Deny from the page")
def deny_from_page(
    request: Request,
    principal: CurrentOperator,
    trajectory_id: str,
    reason: Annotated[str, Form()] = "",
    next_path: Annotated[str | None, Form(alias="next")] = None,
) -> Response:
    """Deny the trajectory's pending request; the reason is recorded on it and the halt's cause."""
    return _decide(request, principal, trajectory_id, "deny", next_path, reason=reason)


# --- Tiers, tools, ledger, egress -----------------------------------------------------------------


@ui_router.get(f"{BASE}/tiers", summary="Tiers", response_class=HTMLResponse)
def tiers_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Every configured tier, its ceiling, and whether it can serve right now."""
    view = app_view(request, APP)
    client, settings = request.app.state.http, request.app.state.settings
    sourced = read_app_page(
        request, view, api=lambda: pc.tiers_api(client, settings), database=None
    )
    return render_app_page(
        request, principal, APP, "pc_tiers.html", selected="Tiers", view=view, sourced=sourced
    )


@ui_router.get(f"{BASE}/tools", summary="Tools", response_class=HTMLResponse)
def tools_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The tool registry, withheld tools with their cause, and the isolation rung."""
    view = app_view(request, APP)
    client, settings = request.app.state.http, request.app.state.settings
    sourced = read_app_page(
        request, view, api=lambda: pc.tools_api(client, settings), database=None
    )
    return render_app_page(
        request, principal, APP, "pc_tools.html", selected="Tools", view=view, sourced=sourced
    )


@ui_router.get(f"{BASE}/ledger", summary="Ledger", response_class=HTMLResponse)
def ledger_page(
    request: Request,
    principal: CurrentOperator,
    trajectory_id: str | None = None,
    tag: str | None = None,
    cursor: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """Today's position against every ceiling, and the recorded debits behind it."""
    view = app_view(request, APP)
    client, settings = request.app.state.http, request.app.state.settings
    page_rows = settings.ui.page_rows
    wanted, tagged = trajectory_id or None, tag or None
    sourced = read_app_page(
        request,
        view,
        api=lambda: pc.ledger_api(
            client, settings, trajectory_id=wanted, tag=tagged, cursor=cursor, page_rows=page_rows
        ),
        database=lambda handle: pc.ledger_db(
            handle, trajectory_id=wanted, page=page, page_rows=page_rows
        ),
    )
    data = sourced.data or {}
    next_href = None
    if data.get("next_cursor"):
        next_href = _href(
            f"{BASE}/ledger", trajectory_id=wanted, tag=tagged, cursor=data["next_cursor"]
        )
    elif data.get("next_page"):
        next_href = _href(
            f"{BASE}/ledger", trajectory_id=wanted, tag=tagged, page=data["next_page"]
        )
    return render_app_page(
        request,
        principal,
        APP,
        "pc_ledger.html",
        selected="Ledger",
        view=view,
        sourced=sourced,
        trajectory_id=wanted or "",
        tag=tagged or "",
        next_href=next_href,
    )


@ui_router.get(f"{BASE}/egress", summary="Egress decisions", response_class=HTMLResponse)
def egress_page(
    request: Request,
    principal: CurrentOperator,
    verdict: str | None = None,
    trajectory_id: str | None = None,
    cursor: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """Every decision about whether data could leave, newest first, approvals and refusals alike."""
    view = app_view(request, APP)
    client, settings = request.app.state.http, request.app.state.settings
    page_rows = settings.ui.page_rows
    wanted_verdict, wanted_trajectory = verdict or None, trajectory_id or None
    sourced = read_app_page(
        request,
        view,
        api=lambda: pc.egress_api(
            client,
            settings,
            verdict=wanted_verdict,
            trajectory_id=wanted_trajectory,
            cursor=cursor,
            page_rows=page_rows,
        ),  # fmt: skip
        database=lambda handle: pc.egress_db(
            handle,
            verdict=wanted_verdict,
            trajectory_id=wanted_trajectory,
            page=page,
            page_rows=page_rows,
        ),  # fmt: skip
    )
    data = sourced.data or {}
    next_href = None
    if data.get("next_cursor"):
        next_href = _href(
            f"{BASE}/egress", verdict=wanted_verdict, trajectory_id=wanted_trajectory,
            cursor=data["next_cursor"],
        )  # fmt: skip
    elif data.get("next_page"):
        next_href = _href(
            f"{BASE}/egress", verdict=wanted_verdict, trajectory_id=wanted_trajectory,
            page=data["next_page"],
        )  # fmt: skip
    return render_app_page(
        request,
        principal,
        APP,
        "pc_egress.html",
        selected="Egress",
        view=view,
        sourced=sourced,
        verdict=wanted_verdict or "",
        verdicts=pc.VERDICTS,
        trajectory_id=wanted_trajectory or "",
        next_href=next_href,
    )


@ui_router.get(f"{BASE}/system", summary="System", response_class=HTMLResponse)
def system_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Health components, active work, pending approvals by age, today's position, the last
    recovery pass and the concurrency — PromptCadence's own System page, over its API only."""
    view = app_view(request, APP)
    client, settings = request.app.state.http, request.app.state.settings
    sourced = read_app_page(
        request, view, api=lambda: pc.system_api(client, settings), database=None
    )
    return render_app_page(
        request, principal, APP, "pc_system.html", selected="System", view=view, sourced=sourced
    )

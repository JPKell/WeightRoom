"""weightroom.web.routes.loadcoach — LoadCoach's pages under its tab (row WP2).

Models, Routing (with the task profiles), Queue and its jobs, Evidence, Reliability, Adapters and
Providers, at parity with LoadCoach's own UI (its ``web/templates``), which a browser on the LAN
cannot reach: LoadCoach binds loopback (ADR-0126). Every page reads by spec §7.3's rule
(``services/app_pages``) through the readers in ``services/loadcoach_pages`` and renders through
``render_app_page``.

Every action is a form post writing exactly one audit row whether LoadCoach accepts or refuses
(spec §11 contract 2). A refusal renders on the page it came from, in LoadCoach's own words.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal
from urllib.parse import urlencode

from baseaicore import SuiteError, new_id
from fastapi import APIRouter, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

from weightroom.services import freeweight_pages as fw
from weightroom.services import loadcoach_actions as actions
from weightroom.services import loadcoach_pages as lc
from weightroom.services.app_api import outcome_of
from weightroom.services.app_api import stream as app_stream
from weightroom.services.audit import record
from weightroom.services.auth import require_fresh_reauth
from weightroom.services.config_files import read_config
from weightroom.web.routes.apps import app_view, back_to, read_app_page, render_app_page
from weightroom.web.session import CurrentOperator, now_of, reauthenticated

if TYPE_CHECKING:
    from weightroom.services.auth import Principal

__all__ = ["ui_router"]

ui_router = APIRouter(tags=["ui"], include_in_schema=False)

APP = lc.APP
BASE = "/apps/loadcoach"


class ModelRefInvalid(SuiteError):
    """A model reference that is not a ULID or a prefix of one; nothing was sent (ADR-0024)."""

    code = "VALIDATION_ERROR"


def _model_ref(value: str) -> str:
    """``value`` when it can only name a registry row: letters and digits, as a ULID is."""
    if not value or not value.isalnum():
        message = f"{value!r} is not a model reference: LoadCoach names a model by its ULID."
        raise ModelRefInvalid(message, details={"model_ref": value})
    return value


def _audit(  # noqa: PLR0913 — every field of one audit row
    request: Request,
    principal: Principal,
    action: str,
    *,
    target: str | None,
    outcome: str,
    params: Mapping[str, Any],
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
        app=APP,
        target=target,
        params=dict(params),
        message=message,
        security=security,
        request_id=getattr(request.state, "request_id", None),
    )


def _clients(request: Request) -> tuple[Any, Any]:
    return request.app.state.http, request.app.state.settings


# --- Models ---------------------------------------------------------------------------------------


def _optional[T](read: Callable[[], T], default: T) -> tuple[T, SuiteError | None]:
    """``read()``, or ``default`` and the refusal — for a column that enriches a page.

    Ability, speed and context fit each come from a *second* read, and none of them is the page:
    the Models page is the registry, and a reader that refuses costs that page its column and a
    note, never its rows (ADR-0016 — an unavailable figure says so, it does not become a zero).
    """
    try:
        return read(), None
    except SuiteError as exc:
        return default, exc


def _by_ability(
    models: Sequence[Mapping[str, Any]],
    ability: str,
    scores: Mapping[str, Mapping[str, float]],
) -> list[Mapping[str, Any]]:
    """``models`` in the registry's own order, or ordered by one capability's bound score.

    Highest first; a model with no bound evidence for that capability sorts last and shows a dash,
    because no measurement is not a low score (ADR-0016). Registry order — LoadCoach's, newest
    seen first — is returned untouched when no ability is chosen, so the default page is exactly
    what the API said.
    """
    if not ability:
        return list(models)
    return sorted(
        models,
        key=lambda one: (
            -float(scores.get(str(one.get("canonical_id") or ""), {}).get(ability, float("-inf")))
        ),
    )


def _models(  # noqa: PLR0913 — what an action leaves on the page, plus this page's own controls
    request: Request,
    principal: Principal,
    *,
    action_error: SuiteError | None = None,
    scanned: Mapping[str, Any] | None = None,
    ability: str = "",
    applied: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: lc.models_api(client, settings), database=lc.models_db
    )
    empty: dict[str, Any] = {}
    no_abilities: dict[str, Any] = {"capabilities": [], "scores": {}}
    abilities, _abilities_error = (
        _optional(lambda: lc.abilities_api(client, settings), no_abilities)
        if sourced.live
        else (no_abilities, None)
    )
    speed, _speed_error = (
        _optional(lambda: lc.speed_api(client, settings), empty) if sourced.live else (empty, None)
    )
    # A cross-application read: FreeWeight measures the context that fits, LoadCoach never does
    # (row WX7's `GET /results/context-fit`). FreeWeight down, or older than that row, costs the
    # column its numbers and nothing else.
    context_fit, context_fit_error = (
        _optional(lambda: fw.context_fit_api(client, settings), empty)
        if sourced.data
        else (empty, None)
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_models.html",
        selected="Models",
        view=view,
        sourced=sourced,
        ordered=_by_ability(sourced.data or [], ability, abilities["scores"]),
        action_error=action_error,
        scanned=scanned,
        ability=ability,
        abilities=abilities["capabilities"],
        scores=abilities["scores"],
        speed=speed,
        context_fit=context_fit,
        context_fit_error=context_fit_error,
        configured=_configured_contexts(request),
        applied=applied,
    )


def _loadcoach_config_path(request: Request) -> Path:
    """The file LoadCoach reads, as its cached schema document states it (ADR-0127).

    The document alone, not the Settings form: the form also reads LoadCoach's live settings, which
    this page has no use for.
    """
    import time

    from weightroom.services.settings_forms import config_file_path, read_schema_document

    state = request.app.state
    document, _error = state.schemas.get(
        APP, now=time.monotonic(), read=lambda: read_schema_document(state.settings, APP)
    )
    return config_file_path(document, app=APP)


def _configured_contexts(request: Request) -> dict[str, int]:
    """The per-model contexts LoadCoach's file names; empty when it cannot be read.

    Empty offers Apply on every measured row, which is safe: the write is validated by LoadCoach.
    """
    try:
        text, _mtime = read_config(_loadcoach_config_path(request))
        return actions.configured_contexts(text)
    except ValueError:
        return {}


@ui_router.get(f"{BASE}/models", summary="Models", response_class=HTMLResponse)
def models_page(
    request: Request, principal: CurrentOperator, ability: str | None = None
) -> HTMLResponse:
    """Every model discovery has seen, with evidence, reliability, residency and its switches.

    ``ability`` is one capability id from the bound evidence this LoadCoach holds: the table gains
    that capability's score per model and is ordered by it, highest first, with every model that
    has no bound evidence for it last (no evidence is not a low score — ADR-0016).
    """
    return _models(request, principal, ability=(ability or "").strip())


@ui_router.post(f"{BASE}/models/discover", summary="Scan for models from the page")
def discover_from_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """``POST /models/discover``; the page again, with the pass's counts above the registry."""
    client, settings = _clients(request)
    try:
        outcome = actions.discover(client, settings)
    except SuiteError as exc:
        _audit(
            request, principal, "loadcoach.discover", target=None,
            outcome=outcome_of(exc), params={},
            message=exc.message,
        )  # fmt: skip
        return _models(request, principal, action_error=exc)
    counts = {key: outcome.get(key) for key in ("added", "updated", "unavailable", "total")}
    _audit(request, principal, "loadcoach.discover", target=None, outcome="ok", params=counts)
    return _models(request, principal, scanned=outcome)


@ui_router.post(f"{BASE}/models/{{model_ref}}/enabled", summary="Enable or disable from the page")
def enabled_from_page(  # noqa: PLR0913 — one parameter per form field
    request: Request,
    principal: CurrentOperator,
    model_ref: str,
    enabled: Annotated[str, Form()] = "",
    canonical_id: Annotated[str, Form()] = "",
    next_path: Annotated[str | None, Form(alias="next")] = None,
) -> Response:
    """ADR-0118's switch: a disabled model is kept, with its evidence, and routed around by name."""
    wanted = enabled == "true"
    params = {"app": APP, "enabled": wanted, "model_ref": model_ref}
    client, settings = _clients(request)
    try:
        actions.set_enabled(client, settings, _model_ref(model_ref), enabled=wanted)
    except SuiteError as exc:
        _audit(
            request, principal, "catalog.enabled", target=canonical_id or model_ref,
            outcome=outcome_of(exc), params=params, message=exc.message,
        )  # fmt: skip
        return _models(request, principal, action_error=exc)
    _audit(
        request, principal, "catalog.enabled", target=canonical_id or model_ref, outcome="ok",
        params=params,
    )  # fmt: skip
    return RedirectResponse(back_to(APP, next_path), status_code=status.HTTP_303_SEE_OTHER)


@ui_router.post(f"{BASE}/models/context-fit", summary="Apply a measured context fit from the page")
def context_fit_from_page(
    request: Request,
    principal: CurrentOperator,
    canonical_id: Annotated[str, Form()] = "",
    context_tokens: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """ADR-0149 §1: FreeWeight's measured fit written into LoadCoach's config, on operator's word.

    Never automatic — a changed context changes LoadCoach's runtime profile hash — and never
    restarts LoadCoach: the page says a restart is pending, as every settings write does.
    """
    tokens = int(context_tokens) if context_tokens.strip().isdigit() else 0
    params = {"app": APP, "canonical_id": canonical_id, "context_tokens": tokens}
    try:
        landed = actions.apply_context_fit(
            request.app.state.settings, _loadcoach_config_path(request), canonical_id, tokens
        )
    except SuiteError as exc:
        _audit(
            request, principal, "loadcoach.context_fit_applied", target=canonical_id or None,
            outcome=outcome_of(exc), params=params, message=exc.message,
        )  # fmt: skip
        return _models(request, principal, action_error=exc)
    _audit(
        request, principal, "loadcoach.context_fit_applied", target=canonical_id, outcome="ok",
        params={**params, "backup": str(landed.backup) if landed.backup else None},
    )  # fmt: skip
    return _models(request, principal, applied={"canonical_id": canonical_id, "tokens": tokens})


@ui_router.post(f"{BASE}/models/{{model_ref}}/warm", summary="Warm a model from the page")
def warm_from_page(
    request: Request,
    principal: CurrentOperator,
    model_ref: str,
    canonical_id: Annotated[str, Form()] = "",
) -> Response:
    """``POST /models/{ref}/warm``; the job it enqueued, which is where the loading shows."""
    client, settings = _clients(request)
    try:
        outcome = actions.warm(client, settings, _model_ref(model_ref))
    except SuiteError as exc:
        _audit(
            request, principal, "loadcoach.warm", target=canonical_id or model_ref,
            outcome=outcome_of(exc), params={"model_ref": model_ref}, message=exc.message,
        )  # fmt: skip
        return _models(request, principal, action_error=exc)
    job_id = str(outcome.get("job_id") or "")
    _audit(
        request, principal, "loadcoach.warm", target=canonical_id or model_ref, outcome="ok",
        params={"model_ref": model_ref, "job_id": job_id or None},
    )  # fmt: skip
    location = f"{BASE}/queue/jobs/{lc.segment(job_id)}" if job_id else f"{BASE}/models"
    return RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)


@ui_router.get(f"{BASE}/models/{{model_ref}}", summary="One model", response_class=HTMLResponse)
def model_page(request: Request, principal: CurrentOperator, model_ref: str) -> HTMLResponse:
    """One model: identity, descriptor, evidence per capability, reliability, the breaker."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: lc.model_api(client, settings, model_ref),
        database=lambda handle: lc.model_db(handle, model_ref),
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_model.html",
        selected="Models",
        view=view,
        sourced=sourced,
        model_ref=model_ref,
    )


# --- Routing --------------------------------------------------------------------------------------


def _routing(
    request: Request,
    principal: Principal,
    *,
    explained: Mapping[str, Any] | None = None,
    explain_error: SuiteError | None = None,
    form: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    profiles = read_app_page(
        request,
        view,
        api=lambda: lc.task_profiles_api(client, settings),
        database=lc.task_profiles_db,
    )
    models = read_app_page(
        request, view, api=lambda: lc.models_api(client, settings), database=None
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_routing.html",
        selected="Routing",
        view=view,
        profiles=profiles,
        models=models.data or [],
        explained=explained,
        explain_error=explain_error,
        form=dict(form or {}),
        runtime_fields=actions.RUNTIME_PROFILE_FIELDS,
    )


@ui_router.get(f"{BASE}/routing", summary="Routing", response_class=HTMLResponse)
def routing_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The explain form — always open — and the task profiles routing ranks against.

    The decision history moved to its own page at ``/routing/decisions`` (row WX9): the form is
    what an operator comes here to use, and a form behind a summary under a long table is a form
    nobody opens.
    """
    return _routing(request, principal)


@ui_router.get(f"{BASE}/routing/decisions", summary="Decisions", response_class=HTMLResponse)
def routing_decisions_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Every routing decision LoadCoach persisted, newest first.

    Persisted, not sampled — but not pageable either: ``GET /routing-decisions`` hardcodes its own
    cap of 50 with no ``limit`` the console can raise (row WX5), so a live read says *first N of
    more* rather than offering a pager that could not work. The stopped path's cap is
    ``[ui] page_rows``.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    page_rows = settings.ui.page_rows
    decisions = read_app_page(
        request,
        view,
        api=lambda: lc.decisions_api(client, settings),
        database=lambda handle: lc.decisions_db(handle, page_rows=page_rows),
    )
    # Each source is "possibly more" only against its own ceiling — a fixed 50 on the API path
    # would be the wrong number to compare a `page_rows=200` database read against.
    decisions_cap = 50 if decisions.live else page_rows
    rows = decisions.data or []
    return render_app_page(
        request,
        principal,
        APP,
        "lc_decisions.html",
        selected="Routing",
        view=view,
        decisions=decisions,
        decisions_capped=bool(rows) and len(rows) >= decisions_cap,
    )


@ui_router.post(f"{BASE}/routing", summary="Explain a route from the page")
def explain_from_page(  # noqa: PLR0913 — one parameter per form field, as FastAPI reads them
    request: Request,
    principal: CurrentOperator,
    task: Annotated[str, Form()] = "",
    estimated_input_tokens: Annotated[str, Form()] = "",
    max_output_tokens: Annotated[str, Form()] = "",
    requires_capabilities: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
    adapter: Annotated[str, Form()] = "",
    context_size: Annotated[str, Form()] = "",
    gpu_layers: Annotated[str, Form()] = "",
    threads: Annotated[str, Form()] = "",
    batch_size: Annotated[str, Form()] = "",
    kv_cache_precision: Annotated[str, Form()] = "",
    keep_alive: Annotated[str, Form()] = "",
    flash_attention: Annotated[str, Form()] = "",
    disallow_fallback: Annotated[str, Form()] = "",
    require_evidence: Annotated[str, Form()] = "",
    ignore_residency: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """``POST /route``: every candidate and every rejection by its code, nothing executed.

    LoadCoach persists the decision, so the call is an action and writes its audit row.
    """
    runtime_profile = {
        "context_size": context_size,
        "gpu_layers": gpu_layers,
        "threads": threads,
        "batch_size": batch_size,
        "kv_cache_precision": kv_cache_precision,
        "keep_alive": keep_alive,
        "flash_attention": flash_attention,
    }
    form = {
        "task": task,
        "estimated_input_tokens": estimated_input_tokens,
        "max_output_tokens": max_output_tokens,
        "requires_capabilities": requires_capabilities,
        "model": model,
        "adapter": adapter,
        **runtime_profile,
        "disallow_fallback": disallow_fallback,
        "require_evidence": require_evidence,
        "ignore_residency": ignore_residency,
    }
    params = {"task": task or None, "model": model or None, "adapter": adapter or None}
    client, settings = _clients(request)
    try:
        body = actions.route_body(
            task=task,
            estimated_input_tokens=estimated_input_tokens,
            max_output_tokens=max_output_tokens,
            requires_capabilities=requires_capabilities,
            model=model,
            adapter=adapter,
            runtime_profile=runtime_profile,
            disallow_fallback=bool(disallow_fallback),
            require_evidence=bool(require_evidence),
            ignore_residency=bool(ignore_residency),
        )
        explained = actions.explain(client, settings, body)
    except SuiteError as exc:
        _audit(
            request, principal, "loadcoach.route", target=task or None, outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _routing(request, principal, explain_error=exc, form=form)
    _audit(
        request, principal, "loadcoach.route", target=task or None, outcome="ok",
        params={**params, "decision_id": explained.get("decision_id")},
    )  # fmt: skip
    return _routing(request, principal, explained=explained, form=form)


@ui_router.get(
    f"{BASE}/routing/decisions/{{decision_id}}", summary="One decision", response_class=HTMLResponse
)
def decision_page(request: Request, principal: CurrentOperator, decision_id: str) -> HTMLResponse:
    """One stored routing explanation: the selection, every candidate's numbers, every rejection."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: lc.decision_api(client, settings, decision_id),
        database=lambda handle: lc.decision_db(handle, decision_id),
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_decision.html",
        selected="Routing",
        view=view,
        sourced=sourced,
        decision_id=decision_id,
    )


@ui_router.get(
    f"{BASE}/routing/task-profiles/{{task}}",
    summary="One task profile",
    response_class=HTMLResponse,
)
def task_profile_page(request: Request, principal: CurrentOperator, task: str) -> HTMLResponse:
    """One task profile: weights, constraints, execution and validation policy.

    The parameter is ``task``, the name ``POST /route`` gives a profile id: the checklist reads any
    parameter spelled with ``file`` in it as a filesystem path (spec §14).
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: lc.task_profile_api(client, settings, task),
        database=lambda handle: lc.task_profile_db(handle, task),
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_task_profile.html",
        selected="Routing",
        view=view,
        sourced=sourced,
        profile_id=task,
    )


# --- Reliability ----------------------------------------------------------------------------------


_PREFIXED_KEYS: Final = ("canonical_id", "subject_canonical_id", "task_profile_id")
"""The identifiers a Reliability prefix matches: the model's, and the task profile's.

Both, not one: ``tools.agent.`` is a family of task profiles and ``ollama/gemma`` a family of
models, and an operator typing either means the same thing by it.
"""


def _keep_prefix(document: Any, prefix: str) -> int:  # noqa: ANN401 — the page's own document
    """Keep only the rows whose model or task profile starts with ``prefix``; return how many went.

    Console-side ``startswith`` over the rows the page already fetched (row WX9, the operator's
    default) — LoadCoach's own ``task`` and ``model`` filters are exact, and adding a prefix
    parameter to its API for a browser control is the wrong place for it. The document is edited
    in place, so the pager, the source line and the window table all see the same rows.

    Args:
        document: The reliability document, or ``None`` when nothing was read.
        prefix: What the operator typed; empty keeps everything.

    Returns:
        The number of rows the prefix removed. Zero when nothing was removed, which is also what
        an empty prefix returns — the page uses it only to tell "nothing matched" from "nothing
        recorded".
    """
    if not prefix or not isinstance(document, dict):
        return 0
    removed = 0
    for key in ("reliability", "stats"):
        rows = document.get(key)
        if not isinstance(rows, list):
            continue
        kept = [row for row in rows if _matches_prefix(row, prefix)]
        removed += len(rows) - len(kept)
        document[key] = kept
    return removed


def _matches_prefix(row: Any, prefix: str) -> bool:  # noqa: ANN401 — one row of either shape
    """Whether this pair's model or task profile starts with ``prefix``."""
    if not isinstance(row, Mapping):
        return False
    model = row.get("model")
    named = model if isinstance(model, Mapping) else {}
    candidates = [row.get(key) for key in _PREFIXED_KEYS]
    candidates += [named.get(key) for key in _PREFIXED_KEYS]
    return any(isinstance(one, str) and one.startswith(prefix) for one in candidates)


@ui_router.get(f"{BASE}/reliability", summary="Reliability", response_class=HTMLResponse)
def reliability_page(  # noqa: PLR0913 — one parameter per control on the filter bar
    request: Request,
    principal: CurrentOperator,
    task: str | None = None,
    model: str | None = None,
    prefix: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """Production evidence per model and task profile: windows, factor, regression, breaker.

    ``task`` and ``model`` are exact and are LoadCoach's own filters. ``prefix`` is the console's:
    it matches ``startswith`` over the pairs the page already fetched, which is what makes
    ``tools.agent.`` — a family of profiles rather than one — a usable filter without a new
    endpoint (row WX9, the operator's default). It is applied **after** paging, so a page that
    the prefix empties says so rather than looking like the end of the list.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    page_rows = settings.ui.page_rows
    wanted_task, wanted_model = task or None, model or None
    wanted_prefix = (prefix or "").strip()
    sourced = read_app_page(
        request,
        view,
        api=lambda: lc.reliability_api(
            client, settings, task=wanted_task, model=wanted_model, page=page, page_rows=page_rows
        ),
        database=lambda handle: lc.reliability_db(
            handle, task=wanted_task, model=wanted_model, page=page, page_rows=page_rows
        ),
    )
    prefix_hid = _keep_prefix(sourced.data, wanted_prefix)
    next_page = (sourced.data or {}).get("next_page")
    next_href = (
        _href(
            f"{BASE}/reliability",
            task=wanted_task,
            model=wanted_model,
            prefix=wanted_prefix,
            page=next_page,
        )
        if next_page
        else None
    )
    profiles = read_app_page(
        request, view, api=lambda: lc.task_profiles_api(client, settings), database=None
    )
    models = read_app_page(
        request, view, api=lambda: lc.models_api(client, settings), database=None
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_reliability.html",
        selected="Reliability",
        view=view,
        sourced=sourced,
        task=wanted_task or "",
        model=wanted_model or "",
        prefix=wanted_prefix,
        prefix_hid=prefix_hid,
        profile_ids=[str(one.get("profile_id") or "") for one in profiles.data or []],
        model_ids=sorted({str(one.get("canonical_id") or "") for one in models.data or []} - {""}),
        next_href=next_href,
    )


# --- Queue and jobs -------------------------------------------------------------------------------

_SSE_HEADERS: Final = {"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"}
_BUNDLE_BYTES: Final = 32 * 1024 * 1024
"""The largest evidence bundle the page uploads; the console's body cap is larger (64 MiB)."""


def _href(path: str, **query: Any) -> str:
    """``path`` with the query parameters that carry a value, so a pager keeps the filters."""
    kept = {key: value for key, value in query.items() if value not in (None, "")}
    return f"{path}?{urlencode(kept)}" if kept else path


def _queue(
    request: Request,
    principal: Principal,
    *,
    confirm: str | None = None,
    action_error: SuiteError | None = None,
) -> HTMLResponse:
    """The queue as it stands *now*: its report, its controls, and the SSE region.

    Row WX9 split what was one page into three — current, a new job, history — and this is the
    only one of them that streams: two pages subscribed to the same region would be two
    connections rendering the same frames.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    report = read_app_page(request, view, api=lambda: lc.queue_api(client, settings), database=None)
    return render_app_page(
        request,
        principal,
        APP,
        "lc_queue.html",
        selected="Queue",
        view=view,
        report=report,
        confirm=confirm,
        sentences=actions.QUEUE_VERBS,
        action_error=action_error,
    )


def _queue_new(
    request: Request,
    principal: Principal,
    *,
    submit_error: SuiteError | None = None,
    form: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    """The Submit form on its own page, with the idempotency key minted at render (WP2 §2.5)."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    live = view.running and view.reachable
    profiles = (
        read_app_page(
            request, view, api=lambda: lc.task_profiles_api(client, settings), database=None
        ).data
        if live
        else None
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_queue_new.html",
        selected="Queue",
        view=view,
        live=live,
        classes=lc.JOB_CLASSES,
        submit_error=submit_error,
        form=dict(form or {}),
        profiles=profiles or [],
        classifications=actions.CLASSIFICATIONS,
        idempotency_key=new_id(),
    )


@ui_router.get(f"{BASE}/queue", summary="Queue", response_class=HTMLResponse)
def queue_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The queue's report, live, and its controls."""
    return _queue(request, principal)


@ui_router.get(f"{BASE}/queue/new", summary="Submit a job", response_class=HTMLResponse)
def queue_new_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The Submit form: one job, queued and routed like any other."""
    return _queue_new(request, principal)


@ui_router.get(f"{BASE}/queue/history", summary="Job history", response_class=HTMLResponse)
def queue_history_page(  # noqa: PLR0913 — one parameter per filter LoadCoach's Jobs page takes
    request: Request,
    principal: CurrentOperator,
    state: str | None = None,
    job_class: Annotated[str | None, Query(alias="class")] = None,
    task: str | None = None,
    source: str | None = None,
    cursor: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """Every job, filtered and paged by ``[ui] page_rows``, newest first."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    page_rows = settings.ui.page_rows
    wanted = {
        "state": state or None,
        "class": job_class or None,
        "task": task or None,
        "source": source or None,
    }
    jobs = read_app_page(
        request,
        view,
        api=lambda: lc.jobs_api(
            client, settings, state=wanted["state"], job_class=wanted["class"],
            task=wanted["task"], source=wanted["source"], cursor=cursor, page_rows=page_rows,
        ),
        database=lambda handle: lc.jobs_db(
            handle, state=wanted["state"], job_class=wanted["class"], task=wanted["task"],
            source=wanted["source"], page=page, page_rows=page_rows,
        ),
    )  # fmt: skip
    data = jobs.data or {}
    next_href = None
    if data.get("next_cursor"):
        next_href = _href(f"{BASE}/queue/history", **wanted, cursor=data["next_cursor"]) + "#jobs"
    elif data.get("next_page"):
        next_href = _href(f"{BASE}/queue/history", **wanted, page=data["next_page"]) + "#jobs"
    return render_app_page(
        request,
        principal,
        APP,
        "lc_queue_history.html",
        selected="Queue",
        view=view,
        jobs=jobs,
        filters={key: value or "" for key, value in wanted.items()},
        states=lc.JOB_STATES,
        classes=lc.JOB_CLASSES,
        next_href=next_href,
    )


@ui_router.post(f"{BASE}/queue/control", summary="Pause, resume or drain from the page")
def queue_control_from_page(
    request: Request,
    principal: CurrentOperator,
    verb: Annotated[Literal["pause", "resume", "drain"], Form()],
    confirmed: Annotated[str, Form()] = "",
) -> Response:
    """Asks first, saying what stops; sends the verb only once confirmed.

    The unconfirmed post changes nothing and writes a ``pending`` row — the trail shows what was
    about to happen, as a catalog delete's preview does (W8).
    """
    action = f"loadcoach.queue_{verb}"
    if confirmed != "yes":
        _audit(
            request, principal, action, target="queue", outcome="pending",
            params={"confirmed": False},
        )  # fmt: skip
        return _queue(request, principal, confirm=verb)
    client, settings = _clients(request)
    try:
        flags = actions.queue_control(client, settings, verb)
    except SuiteError as exc:
        _audit(
            request, principal, action, target="queue", outcome=outcome_of(exc),
            params={"confirmed": True}, message=exc.message,
        )  # fmt: skip
        return _queue(request, principal, action_error=exc)
    _audit(
        request, principal, action, target="queue", outcome="ok",
        params={
            "confirmed": True, "paused": flags.get("paused"), "draining": flags.get("draining"),
            "in_flight": flags.get("in_flight"),
        },
    )  # fmt: skip
    return RedirectResponse(f"{BASE}/queue", status_code=status.HTTP_303_SEE_OTHER)


def _queue_regions(chunks: Iterable[str]) -> Iterator[str]:
    """LoadCoach's queue stream as htmx SSE frames, each the live region rendered here.

    htmx's SSE extension swaps a frame's data in as markup, so the data is this console's own
    rendering of the report — escaped by the template — never LoadCoach's ``html``.
    """
    from weightroom.web.rendering import render

    for kind, report in lc.queue_events(chunks):
        if kind == "heartbeat":
            yield ": heartbeat\n\n"
        elif kind == "status":
            html = render("_lc_queue_live.html", report=report)
            yield (
                "event: queue.status\n"
                + "".join(f"data: {line}\n" for line in html.splitlines() or [""])
                + "\n"
            )
        else:
            yield "event: stream.closed\ndata: closed\n\n"
            return


@ui_router.get(f"{BASE}/queue/stream", summary="The queue, live")
def queue_stream(request: Request, principal: CurrentOperator) -> StreamingResponse:
    """LoadCoach's ``/queue/stream``, one rendered region per change (ADR-0128)."""
    chunks = app_stream(
        request.app.state.http,
        request.app.state.settings,
        APP,
        "queue/stream",
        last_event_id=request.headers.get("last-event-id"),
    )
    return StreamingResponse(
        _queue_regions(chunks), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@ui_router.post(f"{BASE}/queue/jobs", summary="Submit a job from the page")
def submit_job_from_page(  # noqa: PLR0913 — one parameter per form field, as FastAPI reads them
    request: Request,
    principal: CurrentOperator,
    task: Annotated[str, Form()] = "",
    prompt: Annotated[str, Form()] = "",
    system: Annotated[str, Form()] = "",
    job_class: Annotated[str, Form(alias="class")] = "normal",
    priority: Annotated[str, Form()] = "",
    max_wait_seconds: Annotated[str, Form()] = "",
    idempotent: Annotated[str, Form()] = "",
    stream: Annotated[str, Form()] = "",
    data_classification: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
    adapter: Annotated[str, Form()] = "",
    temperature: Annotated[str, Form()] = "",
    max_output_tokens: Annotated[str, Form()] = "",
    think: Annotated[str, Form()] = "",
    idempotency_key: Annotated[str, Form()] = "",
) -> Response:
    """``POST /jobs``; the new job's page. The audit row never carries the prompt or the system."""
    form = {
        "task": task, "prompt": prompt, "system": system, "class": job_class,
        "priority": priority, "max_wait_seconds": max_wait_seconds,
        "idempotent": idempotent, "stream": stream, "data_classification": data_classification,
        "model": model, "adapter": adapter, "temperature": temperature,
        "max_output_tokens": max_output_tokens, "think": think,
        "idempotency_key": idempotency_key,
    }  # fmt: skip
    params = {
        "task": task or None, "class": job_class or None, "priority": priority or None,
        "stream": stream == "true", "model": model or None, "adapter": adapter or None,
        "classification": data_classification or None,
    }  # fmt: skip
    client, settings = _clients(request)
    try:
        body = actions.job_body(
            task=task,
            prompt=prompt,
            system=system,
            job_class=job_class,
            priority=priority,
            max_wait_seconds=max_wait_seconds,
            idempotent=idempotent == "true",
            stream=stream == "true",
            data_classification=data_classification,
            model=model,
            adapter=adapter,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            think=think,
            idempotency_key=idempotency_key,
        )
        document = actions.submit_job(client, settings, body)
    except SuiteError as exc:
        _audit(
            request,
            principal,
            "loadcoach.job_submit",
            target=None,
            outcome=outcome_of(exc),
            params=params,
            message=exc.message,
        )
        return _queue_new(request, principal, submit_error=exc, form=form)
    job_id = str(document.get("job_id") or "")
    _audit(
        request, principal, "loadcoach.job_submit", target=job_id or None, outcome="ok",
        params={**params, "state": document.get("state")},
    )  # fmt: skip
    location = f"{BASE}/queue/jobs/{lc.segment(job_id)}" if job_id else f"{BASE}/queue/history"
    return RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)


def _job(
    request: Request, principal: Principal, job_id: str, *, action_error: SuiteError | None = None
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: lc.job_api(client, settings, job_id),
        database=lambda handle: lc.job_db(handle, job_id),
    )
    base = f"{BASE}/queue/jobs/{lc.segment(job_id)}"
    return render_app_page(
        request,
        principal,
        APP,
        "lc_job.html",
        selected="Queue",
        view=view,
        sourced=sourced,
        job_id=job_id,
        events_url=f"{base}/events",
        reply_url=f"{base}/reply",
        terminal=lc.TERMINAL_JOB_STATES,
        action_error=action_error,
    )


@ui_router.get(f"{BASE}/queue/jobs/{{job_id}}", summary="One job", response_class=HTMLResponse)
def job_page(request: Request, principal: CurrentOperator, job_id: str) -> HTMLResponse:
    """One job: state, attempts, routing, usage, timings, validation, output, events, feedback."""
    return _job(request, principal, job_id)


@ui_router.get(f"{BASE}/queue/jobs/{{job_id}}/events", summary="A job's events, live")
def job_events(request: Request, principal: CurrentOperator, job_id: str) -> StreamingResponse:
    """The job's stream as log-pane frames, closed on its terminal event."""
    chunks = app_stream(
        request.app.state.http,
        request.app.state.settings,
        APP,
        f"jobs/{lc.segment(job_id)}/stream",
        last_event_id=request.headers.get("last-event-id"),
    )
    return StreamingResponse(
        lc.job_log_frames(chunks), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@ui_router.get(f"{BASE}/queue/jobs/{{job_id}}/reply", summary="A job's reply, live")
def job_reply(request: Request, principal: CurrentOperator, job_id: str) -> StreamingResponse:
    """The job's stream unchanged — ``thinking`` (ADR-0132) and ``token`` deltas for the page's
    reply region, which writes each into the DOM as text."""
    chunks = app_stream(
        request.app.state.http,
        request.app.state.settings,
        APP,
        f"jobs/{lc.segment(job_id)}/stream",
        last_event_id=request.headers.get("last-event-id"),
    )
    return StreamingResponse(chunks, media_type="text/event-stream", headers=_SSE_HEADERS)


@ui_router.post(f"{BASE}/queue/jobs/{{job_id}}/cancel", summary="Cancel a job from the page")
def cancel_job_from_page(request: Request, principal: CurrentOperator, job_id: str) -> Response:
    """``POST /jobs/{id}/cancel``; the job's page again, with a refusal on it if one came."""
    client, settings = _clients(request)
    try:
        outcome = actions.cancel_job(client, settings, job_id)
    except SuiteError as exc:
        _audit(
            request, principal, "loadcoach.job_cancel", target=job_id, outcome=outcome_of(exc),
            params={}, message=exc.message,
        )  # fmt: skip
        return _job(request, principal, job_id, action_error=exc)
    _audit(
        request, principal, "loadcoach.job_cancel", target=job_id, outcome="ok",
        params={"state": outcome.get("state"), "already": outcome.get("already")},
    )  # fmt: skip
    return RedirectResponse(
        f"{BASE}/queue/jobs/{lc.segment(job_id)}", status_code=status.HTTP_303_SEE_OTHER
    )


@ui_router.post(f"{BASE}/queue/jobs/{{job_id}}/feedback", summary="Feedback from the page")
def feedback_from_page(  # noqa: PLR0913 — one parameter per form field
    request: Request,
    principal: CurrentOperator,
    job_id: str,
    accepted: Annotated[str, Form()] = "",
    quality_score: Annotated[str, Form()] = "",
    edited: Annotated[str, Form()] = "",
    validation_passed: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
) -> Response:
    """``POST /jobs/{id}/feedback``; LoadCoach attributes it to this console's token. The audit
    row carries the verdict, never the notes."""
    params = {"accepted": accepted or None, "quality_score": quality_score or None}
    client, settings = _clients(request)
    try:
        body = actions.feedback_body(
            accepted=accepted, quality_score=quality_score, edited=edited == "true",
            validation_passed=validation_passed, notes=notes,
        )  # fmt: skip
        actions.send_feedback(client, settings, job_id, body)
    except SuiteError as exc:
        _audit(
            request, principal, "loadcoach.job_feedback", target=job_id, outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _job(request, principal, job_id, action_error=exc)
    _audit(request, principal, "loadcoach.job_feedback", target=job_id, outcome="ok", params=params)
    return RedirectResponse(
        f"{BASE}/queue/jobs/{lc.segment(job_id)}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- Evidence -------------------------------------------------------------------------------------


def _evidence(
    request: Request,
    principal: Principal,
    *,
    action_error: SuiteError | None = None,
    imported: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    """The admin half: the store's overview, its sources, and Import (row WX9)."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: lc.evidence_store_api(client, settings), database=lc.evidence_db
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_evidence_admin.html",
        selected="Evidence",
        view=view,
        sourced=sourced,
        action_error=action_error,
        imported=imported,
        freeweight_url=actions.freeweight_pull(settings)["url"],
    )


@ui_router.get(f"{BASE}/evidence", summary="Evidence", response_class=HTMLResponse)
def evidence_page(
    request: Request,
    principal: CurrentOperator,
    capability: str | None = None,
    model: str | None = None,
    min_confidence: str | None = None,
) -> HTMLResponse:
    """The records, with LoadCoach's own ``capability`` / ``model`` / ``min_confidence`` filters.

    The filters are sent to LoadCoach rather than applied here: each match state is read against
    its own cap, and a console-side filter over a capped page would quietly hide records the
    filter was meant to find. The stopped path reads the rows and says the filters need the API.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    filters = {
        "capability": (capability or "").strip(),
        "model": (model or "").strip(),
        "min_confidence": (min_confidence or "").strip(),
    }
    sourced = read_app_page(
        request,
        view,
        api=lambda: lc.evidence_api(client, settings, **filters),
        database=lc.evidence_db,
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_evidence.html",
        selected="Evidence",
        view=view,
        sourced=sourced,
        filters=filters,
    )


@ui_router.get(f"{BASE}/evidence/admin", summary="Evidence admin", response_class=HTMLResponse)
def evidence_admin_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The store's summary, every source, and Import."""
    return _evidence(request, principal)


@ui_router.post(f"{BASE}/evidence/import", summary="Import evidence from the page")
def import_from_page(
    request: Request,
    principal: CurrentOperator,
    origin: Annotated[str, Form()] = "file",
    file: Annotated[UploadFile | None, File()] = None,
) -> HTMLResponse:
    """An uploaded ``benchmark.evidence_bundle``, or LoadCoach's pull from FreeWeight at this
    console's ``[apps.freeweight] base_url``; the page again with the counts, or the refusal."""
    client, settings = _clients(request)
    params: dict[str, Any] = {"origin": "freeweight" if origin == "freeweight" else "file"}
    try:
        if params["origin"] == "freeweight":
            body = actions.freeweight_pull(settings)
        else:
            raw = file.file.read(_BUNDLE_BYTES + 1) if file is not None else b""
            params["bytes"] = len(raw)
            if len(raw) > _BUNDLE_BYTES:
                message = f"The bundle is over {_BUNDLE_BYTES} bytes; import it with the CLI."
                raise actions.LoadCoachFormInvalid(message, details={"field": "file"})
            body = actions.evidence_bundle(raw)
        outcome = actions.import_evidence(client, settings, body)
    except SuiteError as exc:
        _audit(
            request, principal, "loadcoach.evidence_import", target=None, outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _evidence(request, principal, action_error=exc)
    counts = {
        key: outcome.get(key)
        for key in ("imported", "updated", "unmatched", "ambiguous_name_only", "bound")
    }
    _audit(
        request, principal, "loadcoach.evidence_import", target=outcome.get("source_id"),
        outcome="ok", params={**params, **counts, "rejected": len(outcome.get("rejected") or [])},
    )  # fmt: skip
    return _evidence(request, principal, imported=outcome)


# --- Providers, adapters --------------------------------------------------------------------------


def _serving(request: Request) -> dict[str, list[str]]:
    """Registration name → the canonical ids LoadCoach's registry says it served; ``{}`` unread."""
    client, settings = _clients(request)
    try:
        models = lc.models_api(client, settings)
    except SuiteError:
        return {}
    serving: dict[str, list[str]] = {}
    for model in models:
        serving.setdefault(str(model.get("provider_name") or ""), []).append(
            str(model.get("canonical_id"))
        )
    return serving


def _providers(  # noqa: PLR0913 — what an action leaves on the page
    request: Request,
    principal: Principal,
    *,
    action_error: SuiteError | None = None,
    preview: Mapping[str, Any] | None = None,
    form: Mapping[str, Any] | None = None,
    saved: str | None = None,
    removed: str | None = None,
    prefill: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: lc.providers_api(client, settings), database=None
    )
    return render_app_page(
        request,
        principal,
        APP,
        "lc_providers.html",
        selected="Providers",
        view=view,
        sourced=sourced,
        serving=_serving(request) if sourced.live else {},
        security_fields=actions.SECURITY_FIELDS,
        action_error=action_error,
        preview=preview,
        form=dict(form or {}),
        saved=saved,
        removed=removed,
        prefill=dict(prefill or {}),
    )


@ui_router.get(f"{BASE}/providers", summary="Providers", response_class=HTMLResponse)
def providers_page(
    request: Request,
    principal: CurrentOperator,
    saved: str | None = None,
    removed: str | None = None,
    kind: str | None = None,
) -> HTMLResponse:
    """Every ``[providers.<name>]`` registration as a form, and one to add another (ADR-0117).

    ``kind`` prefills the *Add a registration* form — the **Add llama.cpp** link's whole
    mechanism (row WX9). It is a prefill and nothing more: the form is submitted by a person, the
    password gate on a new registration is unchanged, and a kind LoadCoach does not support is
    refused by LoadCoach in its own words rather than filtered here.
    """
    wanted = (kind or "").strip()
    prefill = {"kind": wanted} if wanted else None
    if wanted == "llamacpp":
        # The one kind that launches its own server: `model_directory` is required and there is no
        # default worth guessing, so the form opens with the field empty and marked required.
        prefill = {"kind": wanted, "base_url": "", "server_path": "llama-server"}
    return _providers(
        request, principal, saved=saved or None, removed=removed or None, prefill=prefill
    )


@ui_router.post(f"{BASE}/providers", summary="Save or remove a registration from the page")
def provider_from_page(  # noqa: PLR0913 — one parameter per form field, as FastAPI reads them
    request: Request,
    principal: CurrentOperator,
    action: Annotated[Literal["save", "delete"], Form()] = "save",
    name: Annotated[str, Form()] = "",
    base_digest: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "",
    base_url: Annotated[str, Form()] = "",
    timeout_seconds: Annotated[str, Form()] = "",
    remote: Annotated[str, Form()] = "",
    model_directory: Annotated[str, Form()] = "",
    state_dir: Annotated[str, Form()] = "",
    server_path: Annotated[str, Form()] = "",
    enabled: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> Response:
    """``PUT`` or ``DELETE /providers/{name}`` through LoadCoach, which writes its own file.

    A changed security key (:data:`~weightroom.services.loadcoach_actions.SECURITY_FIELDS`), a new
    registration and a removal each need the password within the re-authentication window, and
    their audit row is a ``security`` row. A removal is previewed first with the models routing
    stops choosing; it is sent only once the name is typed. No row carries a key's value.
    """
    acting = (reauthenticated(request, principal, password) or principal) if password else principal
    client, settings = _clients(request)
    wanted = name.strip()
    audit_action = f"loadcoach.provider_{action}"
    form = {
        "name": wanted, "kind": kind, "base_url": base_url, "timeout_seconds": timeout_seconds,
        "remote": remote, "model_directory": model_directory, "state_dir": state_dir,
        "server_path": server_path, "enabled": enabled,
    }  # fmt: skip
    if action == "delete":
        if confirm != wanted or not wanted:
            _audit(
                request, principal, audit_action, target=wanted or None, outcome="pending",
                params={"preview": True},
            )  # fmt: skip
            preview = {"name": wanted, "models": _serving(request).get(wanted, [])}
            return _providers(request, acting, preview=preview)
        try:
            require_fresh_reauth(acting, now=now_of(request), auth=settings.auth)
            actions.delete_registration(client, settings, wanted)
        except SuiteError as exc:
            _audit(
                request, principal, audit_action, target=wanted, outcome=outcome_of(exc),
                params={"preview": False}, message=exc.message, security=True,
            )  # fmt: skip
            return _providers(request, acting, action_error=exc)
        _audit(
            request, principal, audit_action, target=wanted, outcome="ok",
            params={"preview": False}, security=True,
        )  # fmt: skip
        return RedirectResponse(
            _href(f"{BASE}/providers", removed=wanted), status_code=status.HTTP_303_SEE_OTHER
        )
    changed: list[str] = []
    security: list[str] = []
    created = False
    try:
        if not wanted:
            message = "A registration needs a name; routing explanations call it by that name."
            raise actions.LoadCoachFormInvalid(message, details={"field": "name"})
        current = next(
            (
                one
                for one in lc.providers_api(client, settings).get("registrations") or []
                if isinstance(one, Mapping) and one.get("name") == wanted
            ),
            None,
        )
        created = current is None
        values = actions.registration_values(
            kind=kind, base_url=base_url, timeout_seconds=timeout_seconds, remote=remote == "true",
            model_directory=model_directory, state_dir=state_dir, server_path=server_path,
            enabled=enabled == "true",
        )  # fmt: skip
        changed, security = actions.touched(current, values)
        if security:
            require_fresh_reauth(acting, now=now_of(request), auth=settings.auth)
        actions.save_registration(client, settings, wanted, values, base_digest=base_digest)
    except SuiteError as exc:
        _audit(
            request, principal, audit_action, target=wanted or None, outcome=outcome_of(exc),
            params={"created": created, "fields": changed, "touched_security": security},
            message=exc.message, security=bool(security),
        )  # fmt: skip
        return _providers(request, acting, action_error=exc, form=form)
    _audit(
        request, principal, audit_action, target=wanted, outcome="ok",
        params={"created": created, "fields": changed, "touched_security": security},
        security=bool(security),
    )  # fmt: skip
    return RedirectResponse(
        _href(f"{BASE}/providers", saved=wanted) + f"#provider-{lc.segment(wanted)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@ui_router.get(f"{BASE}/adapters", summary="Adapters", response_class=HTMLResponse)
def adapters_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Every adapter: base, classification, who holds it, where it is resident, how it routed."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: lc.adapters_api(client, settings), database=lc.adapters_db
    )
    return render_app_page(
        request, principal, APP, "lc_adapters.html", selected="Adapters", view=view, sourced=sourced
    )


@ui_router.get(f"{BASE}/system", summary="System", response_class=HTMLResponse)
def system_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Version, health components, dispatch, residency and breakers, over ``GET /health`` and
    ``GET /system/status`` (WP6's finding: health components and workers appeared nowhere).

    Dispatch latency, starving, active jobs, dispatch state, residency and breakers already have a
    home on Queue and Reliability; this page does not repeat them, and links there instead.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: lc.system_api(client, settings), database=None
    )
    return render_app_page(
        request, principal, APP, "lc_system.html", selected="System", view=view, sourced=sourced
    )

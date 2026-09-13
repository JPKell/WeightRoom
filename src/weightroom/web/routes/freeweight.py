"""weightroom.web.routes.freeweight — FreeWeight's pages under its tab (row WP3).

Models, Runs (with one run, its tests' samples and the case inspector), at parity with FreeWeight's
own UI (its ``web/templates``), which a browser on the LAN cannot reach: FreeWeight binds loopback
(ADR-0126). Every page reads by spec §7.3's rule (``services/app_pages``) through the readers in
``services/freeweight_pages`` and renders through ``render_app_page``.

Every action is a form post writing exactly one audit row whether FreeWeight accepts or refuses
(spec §11 contract 2). Starting a run is not a call to FreeWeight's ``POST /runs``: it enqueues W9's
``freeweight_suite_run`` job, which launches the run under ADR-0119's memory cap and is audited as
``job.enqueue``; the page then follows the run FreeWeight reports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Final
from urllib.parse import quote, urlencode

from baseaicore import SuiteError
from fastapi import APIRouter, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

from weightroom.services import freeweight_actions as actions
from weightroom.services import freeweight_pages as fw
from weightroom.services.app_api import outcome_of
from weightroom.services.app_api import stream as app_stream
from weightroom.services.audit import record
from weightroom.services.auth import require_fresh_reauth
from weightroom.services.catalog import set_enabled
from weightroom.web.routes.apps import app_view, back_to, read_app_page, render_app_page
from weightroom.web.routes.jobs import enqueue_job
from weightroom.web.session import CurrentOperator, now_of, reauthenticated

if TYPE_CHECKING:
    from weightroom.services.auth import Principal

__all__ = ["ui_router"]

ui_router = APIRouter(tags=["ui"], include_in_schema=False)

APP = fw.APP
BASE = "/apps/freeweight"
SUITE_RUN: Final = "freeweight_suite_run"
_SSE_HEADERS: Final = {"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"}


class ModelRefInvalid(SuiteError):
    """A model reference that is not a ULID or a prefix of one; nothing was sent (ADR-0024)."""

    code: ClassVar[str] = "VALIDATION_ERROR"


def _model_ref(value: str) -> str:
    """``value`` when it can only name a registry row: letters and digits, as a ULID is."""
    if not value or not value.isalnum():
        message = f"{value!r} is not a model reference: FreeWeight names a model by its ULID."
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


def _href(path: str, **query: Any) -> str:
    """``path`` with the query parameters that carry a value, so a pager keeps the filters."""
    kept = {key: value for key, value in query.items() if value not in (None, "")}
    return f"{path}?{urlencode(kept)}" if kept else path


# --- Models ---------------------------------------------------------------------------------------


_PARAMETERS_PER_BILLION: Final = 1_000_000_000
"""`params_b` shows `7.6B`, so the filter is typed in billions and sent in parameters."""


def _parameters(value: str | None, *, field: str) -> str | None:
    """``value`` billions of parameters as a whole number of parameters, or ``None`` when blank.

    Raises:
        ModelRefInvalid: It is not a number. Nothing is sent: a filter the console cannot read is
            not a filter FreeWeight should be asked to interpret.
    """
    text = (value or "").strip()
    if not text:
        return None
    try:
        return str(int(float(text) * _PARAMETERS_PER_BILLION))
    except ValueError as exc:
        message = f"{text!r} is not a number of billions of parameters, such as 7.6."
        raise ModelRefInvalid(message, details={"field": field, "value": text}) from exc


def _models(
    request: Request,
    principal: Principal,
    *,
    filters: Mapping[str, str | None],
    action_error: SuiteError | None = None,
    scanned: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sort = filters.get("sort") or None
    shown = {key: filters.get(key) or "" for key in (*fw.MODEL_FILTERS, "sort")}
    wanted: dict[str, str | None] = dict.fromkeys(fw.MODEL_FILTERS)
    try:
        for key in fw.MODEL_FILTERS:
            wanted[key] = (
                _parameters(filters.get(key), field=key)
                if key in {"min_parameters", "max_parameters"}
                else (filters.get(key) or None)
            )
    except SuiteError as exc:
        action_error = action_error or exc
        wanted = dict.fromkeys(fw.MODEL_FILTERS)
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.models_api(client, settings, sort=sort, filters=wanted),
        database=lambda handle: fw.models_db(handle, sort=sort),
    )
    # The three selects offer what FreeWeight *has*, which a filtered list no longer shows — pick
    # `family` and the families of every other provider vanish from the select that would undo it.
    # So a filtered page reads the list once more, unfiltered, for the vocabulary alone; an
    # unfiltered one already holds it.
    narrowed = any(value for key, value in wanted.items() if key != "has_results")
    vocabulary = sourced.data or []
    if narrowed and sourced.live:
        vocabulary = (
            read_app_page(
                request,
                view,
                api=lambda: fw.models_api(client, settings, sort=sort, filters=None),
                database=None,
            ).data
            or []
        )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_models.html",
        selected="Models",
        view=view,
        sourced=sourced,
        filters=shown,
        facets=fw.model_facets(vocabulary),
        action_error=action_error,
        scanned=scanned,
    )


@ui_router.get(f"{BASE}/models", summary="Models", response_class=HTMLResponse)
def models_page(  # noqa: PLR0913 — one parameter per filter FreeWeight's models listing takes
    request: Request,
    principal: CurrentOperator,
    has_results: str | None = None,
    provider_kind: str | None = None,
    family: str | None = None,
    quantization: str | None = None,
    min_parameters: str | None = None,
    max_parameters: str | None = None,
    sort: str | None = None,
) -> HTMLResponse:
    """Every model identity with its latest descriptor, whether it has results, and its switch."""
    return _models(
        request,
        principal,
        filters={
            "has_results": has_results,
            "provider_kind": provider_kind,
            "family": family,
            "quantization": quantization,
            "min_parameters": min_parameters,
            "max_parameters": max_parameters,
            "sort": sort,
        },  # fmt: skip
    )


@ui_router.post(f"{BASE}/models/discover", summary="Scan for models from the page")
def discover_from_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """``POST /models/discover``; the page again, with the counts FreeWeight returns above it."""
    client, settings = _clients(request)
    try:
        outcome = actions.discover(client, settings)
    except SuiteError as exc:
        _audit(
            request, principal, "freeweight.discover", target=None,
            outcome=outcome_of(exc), params={},
            message=exc.message,
        )  # fmt: skip
        return _models(request, principal, filters={}, action_error=exc)
    counts = {key: outcome.get(key) for key in ("added", "updated", "unchanged", "total")}
    _audit(request, principal, "freeweight.discover", target=None, outcome="ok", params=counts)
    return _models(request, principal, filters={}, scanned=counts)


@ui_router.post(f"{BASE}/models/{{model_ref}}/enabled", summary="Enable or disable from the page")
def enabled_from_page(  # noqa: PLR0913 — one parameter per form field
    request: Request,
    principal: CurrentOperator,
    model_ref: str,
    enabled: Annotated[str, Form()] = "",
    canonical_id: Annotated[str, Form()] = "",
    next_path: Annotated[str | None, Form(alias="next")] = None,
) -> Response:
    """ADR-0118's switch, through W8's catalog call: a disabled model keeps its results and is
    refused by name as a run's subject."""
    wanted = enabled == "true"
    params = {"app": APP, "enabled": wanted, "model_ref": model_ref}
    client, settings = _clients(request)
    try:
        set_enabled(settings, APP, _model_ref(model_ref), enabled=wanted, client=client)
    except SuiteError as exc:
        _audit(
            request, principal, "catalog.enabled", target=canonical_id or model_ref,
            outcome=outcome_of(exc), params=params, message=exc.message,
        )  # fmt: skip
        return _models(request, principal, filters={}, action_error=exc)
    _audit(
        request, principal, "catalog.enabled", target=canonical_id or model_ref, outcome="ok",
        params=params,
    )  # fmt: skip
    return RedirectResponse(back_to(APP, next_path), status_code=status.HTTP_303_SEE_OTHER)


@ui_router.get(f"{BASE}/models/{{model_ref}}", summary="One model", response_class=HTMLResponse)
def model_page(  # noqa: PLR0913 — the results filters FreeWeight takes
    request: Request,
    principal: CurrentOperator,
    model_ref: str,
    suite: str | None = None,
    runtime_hash: str | None = None,
    cursor: str | None = None,
) -> HTMLResponse:
    """One model: identity, latest descriptor, descriptor history, evidence, and its results.

    The runtime-profile filter is ``runtime_hash`` here, FreeWeight's ``runtime_profile_hash``
    there: the §14 checklist reads any parameter spelled with ``file`` in it as a filesystem path.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    wanted = {"suite": suite or None, "runtime_hash": runtime_hash or None}
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.model_api(
            client, settings, model_ref, suite=wanted["suite"],
            runtime_profile=wanted["runtime_hash"], cursor=cursor or None,
            page_rows=settings.ui.page_rows,
        ),
        database=lambda handle: fw.model_db(handle, model_ref),
    )  # fmt: skip
    following = (sourced.data or {}).get("next_cursor")
    base = f"{BASE}/models/{fw.segment(model_ref)}"
    return render_app_page(
        request,
        principal,
        APP,
        "fw_model.html",
        selected="Models",
        view=view,
        sourced=sourced,
        model_ref=model_ref,
        filters={key: value or "" for key, value in wanted.items()},
        next_href=_href(base, **wanted, cursor=following) + "#results" if following else None,
    )


# --- Runs -----------------------------------------------------------------------------------------


def _startable_adapters(catalog: object) -> list[dict[str, Any]]:
    """The adapters the Start form may offer, from ``GET /adapters`` (api.md §2a).

    Empty unless FreeWeight says an adapter can be served at all: under a provider that does not
    declare ``adapter_hot_swap`` the directory is configured and inert (ADR-0140), so offering the
    field would offer a run FreeWeight is bound to refuse. Available entries only, because an
    unavailable one — a missing artifact, a digest that no longer matches — is refused for a reason
    the operator fixes in the directory, not in this form. Compatibility with the chosen base stays
    FreeWeight's to decide: the console never filters by base.
    """
    if not isinstance(catalog, dict) or catalog.get("provider_can_serve") is not True:
        return []
    listed = catalog.get("adapters")
    if not isinstance(listed, list):
        return []
    return [
        one
        for one in listed
        if isinstance(one, dict) and one.get("available") and one.get("in_directory")
    ]


def _runs(  # noqa: PLR0913 — the filters, and what a refused start leaves on the page
    request: Request,
    principal: Principal,
    *,
    filters: Mapping[str, str | None],
    cursor: str | None = None,
    page: int = 1,
    start_error: SuiteError | None = None,
    form: Mapping[str, str] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    page_rows = settings.ui.page_rows
    wanted = {key: filters.get(key) or None for key in fw.RUN_FILTERS}
    runs = read_app_page(
        request,
        view,
        api=lambda: fw.runs_api(client, settings, wanted, cursor, page_rows),
        database=lambda handle: fw.runs_db(handle, wanted, page, page_rows),
    )
    data = runs.data or {}
    next_href = None
    if data.get("next_cursor"):
        next_href = _href(f"{BASE}/runs", **wanted, cursor=data["next_cursor"])
    elif data.get("next_page"):
        next_href = _href(f"{BASE}/runs", **wanted, page=data["next_page"])
    benchmarks: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    adapters: list[dict[str, Any]] = []
    machines: list[dict[str, Any]] = []
    if runs.live:
        benchmarks = (
            read_app_page(
                request, view, api=lambda: fw.benchmarks_api(client, settings), database=None
            ).data
            or []
        )
        models = (
            read_app_page(
                request,
                view,
                api=lambda: fw.models_api(client, settings, sort="canonical_id"),
                database=None,
            ).data
            or []
        )
        adapters = _startable_adapters(
            read_app_page(
                request, view, api=lambda: fw.adapters_api(client, settings), database=None
            ).data
        )
        # The filter bar's Machine select (row WX7). A fingerprint is not a name anyone types,
        # and the Runs page was asking for one in a text box.
        machines = (
            read_app_page(
                request, view, api=lambda: fw.machines_api(client, settings), database=None
            ).data
            or []
        )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_runs.html",
        selected="Runs",
        view=view,
        runs=runs,
        filters={key: value or "" for key, value in wanted.items()},
        statuses=fw.RUN_STATUSES,
        next_href=next_href,
        benchmarks=benchmarks,
        models=[one for one in models if one.get("enabled")],
        # The Start form offers what may be measured (ADR-0118); the filter bar offers every
        # model, because a run of a since-disabled model is still a run somebody wants to find.
        model_options=models,
        machines=machines,
        # A run names its machine by fingerprint, which is not a name anyone recognises; this is
        # how the table shows the operator's own label without a second read per row (row WX7).
        machine_names={
            str(one.get("machine_fingerprint")): one.get("display_name")
            for one in machines
            if one.get("machine_fingerprint")
        },
        adapters=adapters,
        start_error=start_error,
        form=dict(form or {}),
    )


@ui_router.get(f"{BASE}/runs", summary="Runs", response_class=HTMLResponse)
def runs_page(  # noqa: PLR0913 — one parameter per filter FreeWeight's runs listing takes
    request: Request,
    principal: CurrentOperator,
    status: str | None = None,  # noqa: A002 — FreeWeight's own parameter name
    model: str | None = None,
    suite: str | None = None,
    machine: str | None = None,
    label: str | None = None,
    adapter: str | None = None,
    since: str | None = None,
    until: str | None = None,
    cursor: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """Every run, filtered and paged, with the form that starts one as a capped job."""
    filters = {
        "status": status, "model": model, "suite": suite, "machine": machine, "label": label,
        "adapter": adapter, "since": since, "until": until,
    }  # fmt: skip
    return _runs(request, principal, filters=filters, cursor=cursor or None, page=page)


@ui_router.post(f"{BASE}/runs", summary="Start a run from the page")
def start_from_page(  # noqa: PLR0913 — one parameter per field of FreeWeight's own start form
    request: Request,
    principal: CurrentOperator,
    model: Annotated[str, Form()] = "",
    suite: Annotated[str, Form()] = "",
    label: Annotated[str, Form()] = "",
    adapter: Annotated[str, Form()] = "",
) -> Response:
    """Enqueue W9's ``freeweight_suite_run`` job (ADR-0119's cap, one ``job.enqueue`` row), then
    follow it until FreeWeight names the run.

    ``adapter`` is one more argument to the same capped command (WP3 §2 item 2): the run is served
    with that registered LoRA applied and measures a different subject (ADR-0058). FreeWeight
    refuses one it cannot serve by name, and this page renders that refusal rather than deciding
    compatibility itself.
    """
    form = {"model": model, "suite": suite, "label": label, "adapter": adapter}
    try:
        job = enqueue_job(
            request,
            principal,
            kind=SUITE_RUN,
            params={
                "model": model,
                "suite": suite,
                "label": label or None,
                "adapter": adapter or None,
            },
            schedule_id=None,
        )
    except SuiteError as exc:
        return _runs(request, principal, filters={}, start_error=exc, form=form)
    return RedirectResponse(
        f"{BASE}/runs/starting/{fw.segment(job.id)}", status_code=status.HTTP_303_SEE_OTHER
    )


@ui_router.get(
    f"{BASE}/runs/starting/{{job_id}}", summary="A run being started", response_class=HTMLResponse
)
def starting_page(request: Request, principal: CurrentOperator, job_id: str) -> Response:
    """The job that is starting a run, until its output names the run — then that run's page.

    ``freeweight run start --json`` prints the run id as soon as the run is persisted, and the job
    flushes its output while the child runs, so the page polls this route (htmx) and is sent on
    once the id appears. A job that ended without naming a run stays here with its output.
    """
    from weightroom.services.job_kinds import run_id_in
    from weightroom.services.jobs import get_job

    job = None
    error: SuiteError | None = None
    try:
        job = get_job(request.app.state.database, job_id)
        if job.kind != SUITE_RUN:
            message = f"Job {job_id} is a {job.kind} job, not a FreeWeight run."
            raise ModelRefInvalid(message, details={"job_id": job_id})
    except SuiteError as exc:
        job, error = None, exc
    run_id = run_id_in(job.output or "") if job is not None else None
    if run_id:
        location = f"{BASE}/runs/{fw.segment(run_id)}"
        if request.headers.get("hx-request"):
            return Response(status_code=status.HTTP_200_OK, headers={"HX-Redirect": location})
        return RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)
    return render_app_page(
        request, principal, APP, "fw_run_starting.html", selected="Runs", job=job, error=error
    )


def _run(
    request: Request,
    principal: Principal,
    run_id: str,
    *,
    action_error: SuiteError | None = None,
    repeat_form: Mapping[str, str] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.run_api(client, settings, run_id),
        database=lambda handle: fw.run_db(handle, run_id),
    )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_run.html",
        selected="Runs",
        view=view,
        sourced=sourced,
        run_id=run_id,
        events_url=f"{BASE}/runs/{fw.segment(run_id)}/events",
        terminal=fw.TERMINAL_RUN_STATUSES,
        action_error=action_error,
        repeat_form=dict(repeat_form or {}),
    )


@ui_router.get(f"{BASE}/runs/{{run_id}}", summary="One run", response_class=HTMLResponse)
def run_page(request: Request, principal: CurrentOperator, run_id: str) -> HTMLResponse:
    """One run: provenance, degradations, the fingerprint document, tests, metrics, telemetry,
    and its events — live while it runs."""
    return _run(request, principal, run_id)


@ui_router.get(f"{BASE}/runs/{{run_id}}/events", summary="A run's events, live")
def run_events(request: Request, principal: CurrentOperator, run_id: str) -> StreamingResponse:
    """FreeWeight's run event stream as log-pane frames, ``Last-Event-ID`` carried through."""
    chunks = app_stream(
        request.app.state.http,
        request.app.state.settings,
        APP,
        f"runs/{fw.segment(run_id)}/events",
        last_event_id=request.headers.get("last-event-id"),
    )
    return StreamingResponse(
        fw.run_log_frames(chunks), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@ui_router.post(f"{BASE}/runs/{{run_id}}/cancel", summary="Cancel a run from the page")
def cancel_from_page(request: Request, principal: CurrentOperator, run_id: str) -> Response:
    """``POST /runs/{id}/cancel``; ``409 RUN_NOT_CANCELLABLE`` renders on the run's page."""
    client, settings = _clients(request)
    try:
        outcome = actions.cancel_run(client, settings, run_id)
    except SuiteError as exc:
        _audit(
            request, principal, "freeweight.run_cancel", target=run_id, outcome=outcome_of(exc),
            params={}, message=exc.message,
        )  # fmt: skip
        return _run(request, principal, run_id, action_error=exc)
    _audit(
        request, principal, "freeweight.run_cancel", target=run_id, outcome="ok",
        params={"status": outcome.get("status")},
    )  # fmt: skip
    return RedirectResponse(
        f"{BASE}/runs/{fw.segment(run_id)}", status_code=status.HTTP_303_SEE_OTHER
    )


@ui_router.post(f"{BASE}/runs/{{run_id}}/repeat", summary="Repeat a run from the page")
def repeat_from_page(
    request: Request,
    principal: CurrentOperator,
    run_id: str,
    force: Annotated[str, Form()] = "",
    label: Annotated[str, Form()] = "",
) -> Response:
    """``POST /runs/{id}/repeat`` with ``?force`` and ``?label``; the new run's page, where a forced
    repeat's divergence is among its degradations. A refusal names every blocker.

    FreeWeight executes a repeat inside ``freeweight.service``, which carries ADR-0119's cap in its
    unit file — so a repeat stays an API call rather than a job (row WP3's handoff records the
    reference machine's reading).
    """
    forced = force == "true"
    params = {"force": forced, "label": label.strip() or None}
    client, settings = _clients(request)
    try:
        outcome = actions.repeat_run(client, settings, run_id, force=forced, label=label)
    except SuiteError as exc:
        _audit(
            request, principal, "freeweight.run_repeat", target=run_id, outcome=outcome_of(exc),
            params=params, message=exc.message,
        )  # fmt: skip
        return _run(
            request, principal, run_id, action_error=exc,
            repeat_form={"force": force, "label": label},
        )  # fmt: skip
    new_id = str(outcome.get("id") or "")
    _audit(
        request, principal, "freeweight.run_repeat", target=run_id, outcome="ok",
        params={**params, "run_id": new_id or None},
    )  # fmt: skip
    return RedirectResponse(
        f"{BASE}/runs/{fw.segment(new_id or run_id)}", status_code=status.HTTP_303_SEE_OTHER
    )


@ui_router.get(
    f"{BASE}/runs/{{run_id}}/tests/{{run_test_id}}",
    summary="One test's samples",
    response_class=HTMLResponse,
)
def samples_page(  # noqa: PLR0913 — the two pagers, FreeWeight's cursor and the database's page
    request: Request,
    principal: CurrentOperator,
    run_id: str,
    run_test_id: str,
    cursor: str | None = None,
    page: int = 1,
) -> HTMLResponse:
    """One test's raw samples, paged: the rows every headline number drills to."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    page_rows = settings.ui.page_rows
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.samples_api(
            client, settings, run_id, run_test_id, cursor or None, page_rows
        ),
        database=lambda handle: fw.samples_db(handle, run_id, run_test_id, page, page_rows),
    )
    data = sourced.data or {}
    base = f"{BASE}/runs/{fw.segment(run_id)}/tests/{fw.segment(run_test_id)}"
    next_href = None
    if data.get("next_cursor"):
        next_href = _href(base, cursor=data["next_cursor"])
    elif data.get("next_page"):
        next_href = _href(base, page=data["next_page"])
    return render_app_page(
        request,
        principal,
        APP,
        "fw_samples.html",
        selected="Runs",
        view=view,
        sourced=sourced,
        run_id=run_id,
        run_test_id=run_test_id,
        next_href=next_href,
    )


@ui_router.get(f"{BASE}/samples/{{sample_id}}", summary="One sample", response_class=HTMLResponse)
def sample_page(request: Request, principal: CurrentOperator, sample_id: str) -> HTMLResponse:
    """The case inspector: one request exactly as recorded, every model-written text escaped."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.sample_api(client, settings, sample_id),
        database=lambda handle: fw.sample_db(handle, sample_id),
    )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_sample.html",
        selected="Runs",
        view=view,
        sourced=sourced,
        sample_id=sample_id,
    )


# --- Downloads ------------------------------------------------------------------------------------


def _download(headers: Mapping[str, str], body: Iterable[bytes], name: str) -> StreamingResponse:
    """FreeWeight's download passed through as it streams, under FreeWeight's own file name."""
    return StreamingResponse(
        body,
        media_type=headers.get("content-type") or "application/octet-stream",
        headers={
            "Content-Disposition": headers.get("content-disposition")
            or f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


def _unanswered(request: Request) -> SuiteError | None:
    """Why a download is not asked for now, or ``None``.

    A FreeWeight whose unit is not running is not called at all — a page's reads already follow
    that rule through ``read_app_page``, and a download follows it here — so a stopped application
    is never reached through whatever else might answer on its port.
    """
    from weightroom.services.apps import AppUnreachable

    view = app_view(request, APP)
    if view.running and view.reachable:
        return None
    message = f"FreeWeight is {view.pill}: a download is read only from its running API."
    return AppUnreachable(message, details={"app": APP})


def _flags(**values: str | None) -> dict[str, str]:
    """A form's text fields as given, ``""`` for one left out, so a refused form renders again."""
    return {key: value or "" for key, value in values.items()}


def _console_names(filters: Mapping[str, str | None]) -> dict[str, str | None]:
    """FreeWeight's filter names as this console's query names, for a pager's link.

    ``runtime_profile`` travels as ``runtime_hash``: the §14 checklist reads any parameter spelled
    with ``file`` in it as a filesystem path.
    """
    named = dict(filters)
    if "runtime_profile" in named:
        named["runtime_hash"] = named.pop("runtime_profile")
    return named


# --- Results, compare, export ---------------------------------------------------------------------


def _results(
    request: Request,
    principal: Principal,
    *,
    filters: Mapping[str, str | None],
    cursor: str | None = None,
    export_error: SuiteError | None = None,
    export_form: Mapping[str, str] | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    wanted = {key: filters.get(key) or None for key in fw.RESULT_FILTERS}
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.results_api(client, settings, wanted, cursor, settings.ui.page_rows),
        database=None,
    )
    following = (sourced.data or {}).get("next_cursor")
    return render_app_page(
        request,
        principal,
        APP,
        "fw_results.html",
        selected="Results",
        view=view,
        sourced=sourced,
        filters={key: value or "" for key, value in wanted.items()},
        next_href=(
            _href(f"{BASE}/results", **_console_names(wanted), cursor=following)
            if following
            else None
        ),
        export_error=export_error,
        export_form=dict(export_form or {}),
        scopes=fw.EXPORT_SCOPES,
        formats=fw.EXPORT_FORMATS,
    )


@ui_router.get(f"{BASE}/results", summary="Results", response_class=HTMLResponse)
def results_page(  # noqa: PLR0913 — one parameter per filter FreeWeight's metric query takes
    request: Request,
    principal: CurrentOperator,
    model: str | None = None,
    suite: str | None = None,
    metric_key: str | None = None,
    machine: str | None = None,
    runtime_hash: str | None = None,
    adapter: str | None = None,
    since: str | None = None,
    until: str | None = None,
    status: str | None = None,  # noqa: A002 — FreeWeight's own parameter name
    cursor: str | None = None,
) -> HTMLResponse:
    """Every stored metric, filtered as FreeWeight's query allows, with Compare and Export."""
    filters = {
        "model": model, "suite": suite, "metric_key": metric_key, "machine": machine,
        "runtime_profile": runtime_hash, "adapter": adapter, "since": since, "until": until,
        "status": status,
    }  # fmt: skip
    return _results(request, principal, filters=filters, cursor=cursor or None)


@ui_router.get(f"{BASE}/results/compare", summary="Compare", response_class=HTMLResponse)
def compare_page(  # noqa: PLR0913 — the two subject forms, the guard, and what to chart
    request: Request,
    principal: CurrentOperator,
    subjects: str | None = None,
    subject: Annotated[list[str] | None, Query()] = None,
    metric: Annotated[list[str] | None, Query()] = None,
    suite: str | None = None,
) -> HTMLResponse:
    """``GET /results/compare``: every comparability verdict, the reason for each separation, and a
    refused comparison's reason in FreeWeight's words rather than an empty table.

    Two ways in, joined into the one list FreeWeight takes: ``subjects``, the free-text box that
    accepts run IDs and prefixes, and repeated ``subject`` parameters, which is what the model
    picker's checkboxes post. ``metric`` names which of the comparison's rows to draw as a bar
    chart, and is read after the answer comes back — the metrics are not known until then.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    typed = [one.strip() for one in (subjects or "").split(",") if one.strip()]
    picked = [one.strip() for one in (subject or []) if one.strip()]
    chosen = list(dict.fromkeys(typed + picked))
    wanted, guard = ",".join(chosen), (suite or "").strip() or None
    sourced = (
        read_app_page(
            request,
            view,
            api=lambda: fw.compare_api(client, settings, wanted, guard),
            database=None,
        )
        if wanted
        else None
    )
    models = (
        read_app_page(
            request,
            view,
            api=lambda: fw.models_api(client, settings, sort="canonical_id"),
            database=None,
        ).data
        or []
        if view.reachable
        else []
    )
    metrics = [one.strip() for one in (metric or []) if one.strip()]
    return render_app_page(
        request,
        principal,
        APP,
        "fw_compare.html",
        selected="Results",
        view=view,
        sourced=sourced,
        subjects=subjects or "",
        picked=picked,
        chosen=chosen,
        metrics=metrics,
        charts=fw.compare_bar_options(sourced.data or {}, metrics) if sourced else [],
        models=[one for one in models if one.get("enabled")],
        suite=guard or "",
        mirrorwall={"htmx": True, "echarts": True},
    )


@ui_router.get(f"{BASE}/results/export", summary="Export results", response_model=None)
def export_results(  # noqa: PLR0913 — one parameter per option FreeWeight's export takes
    request: Request,
    principal: CurrentOperator,
    format: str = "json",  # noqa: A002 — FreeWeight's own parameter name
    scope: str = "all",
    selector: str | None = None,
    include_samples: str | None = None,
    include_prompts: str | None = None,
    include_prompt_text: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> Response:
    """``GET /results/export`` proxied as it streams, every option FreeWeight takes passed through.

    A refusal — the 500-run limit among them — arrives before a byte of the file and renders on
    the Results page as itself, with the form kept.
    """
    from weightroom.services.app_api import download

    form = _flags(
        format=format, scope=scope, selector=selector, include_samples=include_samples,
        include_prompts=include_prompts, include_prompt_text=include_prompt_text, since=since,
        until=until,
    )  # fmt: skip
    client, settings = _clients(request)
    try:
        refused = _unanswered(request)
        if refused is not None:
            raise refused
        headers, body = download(
            client, settings, APP, "results/export", params=fw.export_params(form)
        )
    except SuiteError as exc:
        return _results(request, principal, filters={}, export_error=exc, export_form=form)
    return _download(headers, body, "freeweight-export")


# --- Evidence -------------------------------------------------------------------------------------


def _evidence(
    request: Request,
    principal: Principal,
    *,
    filters: Mapping[str, str | None],
    cursor: str | None = None,
    export_error: SuiteError | None = None,
    since: str = "",
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    wanted = {key: filters.get(key) or None for key in fw.EVIDENCE_FILTERS}
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.evidence_api(client, settings, wanted, cursor, settings.ui.page_rows),
        database=None,
    )
    following = (sourced.data or {}).get("next_cursor")
    return render_app_page(
        request,
        principal,
        APP,
        "fw_evidence.html",
        selected="Evidence",
        view=view,
        sourced=sourced,
        filters={key: value or "" for key, value in wanted.items()},
        next_href=(
            _href(f"{BASE}/evidence", **_console_names(wanted), cursor=following)
            if following
            else None
        ),
        export_error=export_error,
        since=since,
    )


@ui_router.get(f"{BASE}/evidence", summary="Evidence", response_class=HTMLResponse)
def evidence_page(  # noqa: PLR0913 — one parameter per filter FreeWeight's evidence takes
    request: Request,
    principal: CurrentOperator,
    capability: str | None = None,
    model: str | None = None,
    machine: str | None = None,
    runtime_hash: str | None = None,
    min_confidence: str | None = None,
    cursor: str | None = None,
) -> HTMLResponse:
    """FreeWeight's current ``capability.evidence`` records, a ``user.*`` record's goal, jury and
    calibration beside its score, and the ``benchmark.evidence_bundle`` download."""
    filters = {
        "capability": capability, "model": model, "machine": machine,
        "runtime_profile": runtime_hash, "min_confidence": min_confidence,
    }  # fmt: skip
    return _evidence(request, principal, filters=filters, cursor=cursor or None)


@ui_router.get(f"{BASE}/evidence/export", summary="Export the evidence bundle", response_model=None)
def export_evidence(  # noqa: PLR0913 — one parameter per filter FreeWeight's bundle takes
    request: Request,
    principal: CurrentOperator,
    since: str | None = None,
    capability: str | None = None,
    model: str | None = None,
    machine: str | None = None,
    runtime_hash: str | None = None,
    min_confidence: str | None = None,
) -> Response:
    """``GET /evidence/export`` passed through: one ``benchmark.evidence_bundle`` envelope."""
    from weightroom.services.app_api import download

    filters = {
        "capability": capability, "model": model, "machine": machine,
        "runtime_profile": runtime_hash, "min_confidence": min_confidence,
    }  # fmt: skip
    params = {**{key: value or None for key, value in filters.items()}, "since": since or None}
    client, settings = _clients(request)
    try:
        refused = _unanswered(request)
        if refused is not None:
            raise refused
        headers, body = download(client, settings, APP, "evidence/export", params=params)
    except SuiteError as exc:
        return _evidence(
            request, principal, filters=filters, export_error=exc, since=since or ""
        )  # fmt: skip
    return _download(headers, body, "freeweight-evidence.json")


# --- Machines -------------------------------------------------------------------------------------


@ui_router.get(f"{BASE}/machines", summary="Machines", response_class=HTMLResponse)
def machines_page(
    request: Request, principal: CurrentOperator, fingerprint: str | None = None
) -> HTMLResponse:
    """Every machine FreeWeight has measured on; a run or a result links here by fingerprint."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: fw.machines_api(client, settings), database=fw.machines_db
    )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_machines.html",
        selected="Runs",
        view=view,
        sourced=sourced,
        fingerprint=fingerprint or "",
    )


@ui_router.get(
    f"{BASE}/machines/{{machine_id}}", summary="One machine", response_class=HTMLResponse
)
def machine_page(request: Request, principal: CurrentOperator, machine_id: str) -> HTMLResponse:
    """One machine's static profile, the name the operator gave it, and the runs measured on it."""
    return _machine(request, principal, machine_id)


def _machine(
    request: Request,
    principal: Principal,
    machine_id: str,
    action_error: SuiteError | None = None,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.machine_api(client, settings, machine_id),
        database=lambda handle: fw.machine_db(handle, machine_id),
    )
    filters = {"machine": str((sourced.data or {}).get("machine_fingerprint") or "") or None}
    runs = (
        read_app_page(
            request,
            view,
            api=lambda: fw.runs_api(client, settings, filters, None, settings.ui.page_rows),
            database=lambda handle: fw.runs_db(handle, filters, 1, settings.ui.page_rows),
        )
        if filters["machine"]
        else None
    )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_machine.html",
        selected="Runs",
        view=view,
        sourced=sourced,
        runs=runs,
        machine_id=machine_id,
        action_error=action_error,
    )


@ui_router.post(f"{BASE}/machines/{{machine_id}}/nickname", summary="Name a machine")
def nickname_from_page(
    request: Request,
    principal: CurrentOperator,
    machine_id: str,
    nickname: Annotated[str, Form()] = "",
) -> Response:
    """``PATCH /machines/{id}`` (row WX7): the operator's own label for this machine.

    Audited like any other write the console makes through an application, and **not** security-
    relevant: a nickname identifies nothing — FreeWeight attributes every measurement to the
    fingerprint — so naming a machine cannot misdirect a measurement the way a provider's base URL
    can (`freeweight_actions.SECURITY_FIELDS`).
    """
    client, settings = _clients(request)
    params = {"app": APP, "machine_id": machine_id, "nickname": nickname.strip()}
    try:
        actions.set_machine_nickname(client, settings, machine_id, nickname=nickname)
    except SuiteError as exc:
        _audit(
            request, principal, "freeweight.machine_nickname", target=machine_id,
            outcome=outcome_of(exc), params=params, message=exc.message,
        )  # fmt: skip
        return _machine(request, principal, machine_id, action_error=exc)
    _audit(
        request, principal, "freeweight.machine_nickname", target=machine_id, outcome="ok",
        params=params,
    )  # fmt: skip
    return RedirectResponse(
        f"{BASE}/machines/{quote(machine_id, safe='')}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- Adapters, provider ---------------------------------------------------------------------------


@ui_router.get(f"{BASE}/adapters", summary="Adapters", response_class=HTMLResponse)
def adapters_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Every adapter the directory holds or FreeWeight measured under, with its base and runs."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: fw.adapters_api(client, settings), database=fw.adapters_db
    )
    return render_app_page(
        request, principal, APP, "fw_adapters.html", selected="Adapters", view=view, sourced=sourced
    )


@ui_router.get(f"{BASE}/adapters/{{adapter}}", summary="One adapter", response_class=HTMLResponse)
def adapter_page(request: Request, principal: CurrentOperator, adapter: str) -> HTMLResponse:
    """One adapter: its base, the runs and results measured under it, and on each base the scores
    measured with it beside the bare base's."""
    view = app_view(request, APP)
    client, settings = _clients(request)
    page_rows = settings.ui.page_rows
    sourced = read_app_page(
        request,
        view,
        api=lambda: fw.adapter_api(client, settings, adapter, page_rows=page_rows),
        database=lambda handle: fw.adapter_db(handle, adapter, page_rows=page_rows),
    )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_adapter.html",
        selected="Adapters",
        view=view,
        sourced=sourced,
        adapter_name=adapter,
    )


def _provider(
    request: Request,
    principal: Principal,
    *,
    action_error: SuiteError | None = None,
    form: Mapping[str, str] | None = None,
    saved: bool = False,
) -> HTMLResponse:
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: fw.provider_api(client, settings), database=None
    )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_provider.html",
        selected="Provider",
        view=view,
        sourced=sourced,
        security_fields=actions.SECURITY_FIELDS,
        action_error=action_error,
        form=dict(form or {}),
        saved=saved,
    )


@ui_router.get(f"{BASE}/provider", summary="Provider", response_class=HTMLResponse)
def provider_page(
    request: Request, principal: CurrentOperator, saved: str | None = None
) -> HTMLResponse:
    """FreeWeight's ``[provider]`` block as a form (ADR-0117), its file and what shadows it."""
    return _provider(request, principal, saved=bool(saved))


@ui_router.post(f"{BASE}/provider", summary="Save the provider block from the page")
def provider_from_page(  # noqa: PLR0913 — one parameter per form field, as FastAPI reads them
    request: Request,
    principal: CurrentOperator,
    base_digest: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "",
    base_url: Annotated[str, Form()] = "",
    timeout_seconds: Annotated[str, Form()] = "",
    model_directory: Annotated[str, Form()] = "",
    state_dir: Annotated[str, Form()] = "",
    server_path: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> Response:
    """``PUT /provider`` through FreeWeight, which validates and writes its own file.

    A changed security key (:data:`~weightroom.services.freeweight_actions.SECURITY_FIELDS`) needs
    the password within the re-authentication window, and its audit row is a ``security`` row. No
    row carries a key's value, and the password reaches none.
    """
    acting = (reauthenticated(request, principal, password) or principal) if password else principal
    client, settings = _clients(request)
    form = {
        "kind": kind, "base_url": base_url, "timeout_seconds": timeout_seconds,
        "model_directory": model_directory, "state_dir": state_dir, "server_path": server_path,
    }  # fmt: skip
    changed: list[str] = []
    security: list[str] = []
    try:
        current = fw.provider_api(client, settings).get("provider")
        values = actions.provider_values(
            kind=kind, base_url=base_url, timeout_seconds=timeout_seconds,
            model_directory=model_directory, state_dir=state_dir, server_path=server_path,
        )  # fmt: skip
        changed, security = actions.touched(current if isinstance(current, Mapping) else {}, values)
        if security:
            require_fresh_reauth(acting, now=now_of(request), auth=settings.auth)
        actions.save_provider(client, settings, values, base_digest=base_digest)
    except SuiteError as exc:
        _audit(
            request, principal, "freeweight.provider_save", target="provider",
            outcome=outcome_of(exc),
            params={"fields": changed, "touched_security": security}, message=exc.message,
            security=bool(security),
        )  # fmt: skip
        return _provider(request, acting, action_error=exc, form=form)
    _audit(
        request, principal, "freeweight.provider_save", target="provider", outcome="ok",
        params={"fields": changed, "touched_security": security}, security=bool(security),
    )  # fmt: skip
    return RedirectResponse(
        f"{BASE}/provider?saved=1#provider", status_code=status.HTTP_303_SEE_OTHER
    )


# --- Dashboard and System (row WPF5) ---------------------------------------------------------


@ui_router.get(f"{BASE}/dashboard", summary="Dashboard", response_class=HTMLResponse)
def dashboard_page(
    request: Request,
    principal: CurrentOperator,
    suite: str | None = None,
    model: str | None = None,
    machine: str | None = None,
    since: str | None = None,
) -> HTMLResponse:
    """The cross-model summary and comparison heatmap over ``GET /dashboard`` (api.md §5a).

    No console page shows this view otherwise: Results is a metric-level query and Compare works
    per subject (WP6's finding). Read-only, over the running API only — the scatter panels and
    per-metric tables stay on FreeWeight's own page.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    wanted = {"suite": suite, "model": model, "machine": machine, "since": since}
    sourced = read_app_page(
        request, view, api=lambda: fw.dashboard_api(client, settings, wanted), database=None
    )
    return render_app_page(
        request,
        principal,
        APP,
        "fw_dashboard.html",
        selected="Dashboard",
        view=view,
        sourced=sourced,
        filters={key: value or "" for key, value in wanted.items()},
    )


@ui_router.get(f"{BASE}/system", summary="System", response_class=HTMLResponse)
def system_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Version, overall status and FreeWeight's ten health components, over ``GET /health``.

    The console showed only the Overview's status and a *JSON · health* link (WP6's finding).
    Read-only, over the running API only.
    """
    view = app_view(request, APP)
    client, settings = _clients(request)
    sourced = read_app_page(
        request, view, api=lambda: fw.system_api(client, settings), database=None
    )
    return render_app_page(
        request, principal, APP, "fw_system.html", selected="System", view=view, sourced=sourced
    )

"""weightroom.services.loadcoach_pages — the data behind LoadCoach's tab (row WP2).

Each page has two readers: one over LoadCoach's own ``/api/v1`` (through
:mod:`~weightroom.services.app_api`) for while it answers, and one over its database
(``data-model.md``) for while it does not, shaping the rows into the API document's names so one
template renders both. Which one runs is :mod:`~weightroom.services.app_pages`' decision, never this
module's. A figure only LoadCoach's arithmetic produces — an evidence summary, a reliability factor,
a regression verdict, a breaker's live state — has no database reader and renders ``—`` when
stopped (ADR-0016), never a number recomputed here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Final
from urllib.parse import quote

from baseaicore import SuiteError
from mirrorwall import Event, format_frame
from setspec import GeneratorInfo

from weightroom.__about__ import __version__
from weightroom.services.app_api import AppRefused, call, lines
from weightroom.services.app_pages import rows_where
from weightroom.services.chat_loadcoach import iter_frames

if TYPE_CHECKING:
    import httpx

    from weightroom.config import Settings
    from weightroom.services.db_reader import AppDatabase

__all__ = [
    "APP",
    "JOB_CLASSES",
    "JOB_STATES",
    "MATCH_STATES",
    "TERMINAL_JOB_STATES",
    "NotRecorded",
    "abilities_api",
    "adapters_api",
    "adapters_db",
    "decision_api",
    "decision_db",
    "decisions_api",
    "decisions_db",
    "evidence_api",
    "evidence_db",
    "evidence_store_api",
    "job_api",
    "job_db",
    "job_log_frames",
    "jobs_api",
    "jobs_db",
    "model_api",
    "model_db",
    "models_api",
    "models_db",
    "providers_api",
    "queue_api",
    "queue_events",
    "reliability_api",
    "reliability_db",
    "segment",
    "speed_api",
    "system_api",
    "task_profile_api",
    "task_profile_db",
    "task_profiles_api",
    "task_profiles_db",
]

APP: Final = "loadcoach"
LIST_CAP: Final = 200
MODEL_CAP: Final = 500
"""A registry larger than this is read in part when stopped; ``GET /models`` has no cap."""


class NotRecorded(SuiteError):
    """LoadCoach's database holds no such record, or more than one matches a prefix."""

    code: ClassVar[str] = "NOT_FOUND"


def segment(value: str) -> str:
    """``value`` quoted as one path segment, so an id can never add a segment or a query."""
    return quote(value, safe="")


def _loads(value: Any) -> Any:  # noqa: ANN401 — a stored JSON column, whatever it holds
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _document(body: Any) -> dict[str, Any]:  # noqa: ANN401 — the application's JSON body
    return dict(body) if isinstance(body, Mapping) else {}


def _listed(body: Any, key: str) -> list[dict[str, Any]]:  # noqa: ANN401 — a JSON body
    found = body.get(key) if isinstance(body, Mapping) else None
    return [dict(one) for one in found or [] if isinstance(one, Mapping)]


# --- Models ---------------------------------------------------------------------------------------


def models_api(client: httpx.Client, settings: Settings) -> list[dict[str, Any]]:
    """``GET /models``: every model discovery has seen, with its three summaries and adapters.

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    return _listed(call(client, settings, APP, "GET", "models", timeout_seconds=30.0), "models")


def _model_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``models`` row under ``GET /models``' names; the summaries are LoadCoach's, so ``None``."""
    return {
        "canonical_id": row.get("canonical_id"),
        "model_ref": row.get("id"),
        "provider_kind": row.get("provider_kind"),
        "provider_name": row.get("provider_name") or "",
        "is_remote": bool(row.get("is_remote")),
        "provider_model_name": row.get("provider_model_name"),
        "identity_confidence": row.get("identity_confidence"),
        "family": row.get("family"),
        "quantization": row.get("quantization"),
        "max_context": row.get("max_context"),
        "size_bytes": row.get("size_bytes"),
        "parameter_count": row.get("parameter_count"),
        "available": bool(row.get("available")),
        "unavailable_reason": row.get("unavailable_reason"),
        "enabled": bool(row.get("enabled")),
        "declared_capabilities": _loads(row.get("declared_capabilities_json")) or {},
        "first_seen_at": row.get("first_seen_at"),
        "last_seen_at": row.get("last_seen_at"),
        "evidence_summary": None,
        "reliability": None,
        "residency": None,
        "adapters": [],
    }


def models_db(handle: AppDatabase) -> list[dict[str, Any]]:
    """The ``models`` table by canonical id.

    Raises:
        TableUnknown: The database has no ``models`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    rows = rows_where(handle, "models", order_by="canonical_id", descending=False, limit=MODEL_CAP)
    return [_model_row(row) for row in rows]


def model_api(client: httpx.Client, settings: Settings, model_ref: str) -> dict[str, Any]:
    """``GET /models/{model_ref}``: identity, descriptor, evidence per capability, the breaker.

    Raises:
        AppRefused: ``MODEL_NOT_FOUND`` for no match or an ambiguous prefix, or another refusal.
        AppUnreachable: It did not answer.
    """
    body = call(client, settings, APP, "GET", f"models/{segment(model_ref)}", timeout_seconds=30.0)
    return _document(body)


def model_db(handle: AppDatabase, model_ref: str) -> dict[str, Any]:
    """One model by ULID or unambiguous prefix (ADR-0024), with its imported evidence rows.

    Raises:
        NotRecorded: Nothing matches ``model_ref``, or more than one row does.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    wanted = model_ref.strip()
    matches = [
        row
        for row in rows_where(handle, "models", limit=MODEL_CAP)
        if wanted and str(row.get("id") or "").startswith(wanted)
    ]
    if len(matches) != 1:
        raise NotRecorded(
            f"LoadCoach's database holds no model {model_ref!r}."
            if not matches
            else f"{model_ref!r} is ambiguous: {len(matches)} models start with it.",
            details={"model_ref": model_ref},
        )
    row = matches[0]
    evidence = [
        {
            "capability_id": one.get("capability_id"),
            "score": one.get("score"),
            "confidence": one.get("confidence"),
            "sample_count": one.get("sample_count"),
            "source": "benchmark",
            "match_state": one.get("match_state"),
            "runtime_profile_hash": one.get("runtime_profile_hash"),
            "machine_fingerprint": one.get("machine_fingerprint"),
            "measured_at": one.get("measured_at"),
            "stale": bool(one.get("stale")),
            "stale_reason": one.get("stale_reason"),
        }
        for one in rows_where(
            handle,
            "capability_evidence",
            equals={"model_id": row.get("id")},
            order_by="capability_id",
            descending=False,
            limit=LIST_CAP,
        )  # fmt: skip
    ]
    return {
        **_model_row(row),
        "descriptor": _loads(row.get("descriptor_json")),
        "evidence": evidence,
        "reliability_by_task_profile": None,
        "circuit_breaker": None,
    }


# --- Routing --------------------------------------------------------------------------------------


def decisions_api(client: httpx.Client, settings: Settings) -> list[dict[str, Any]]:
    """``GET /routing-decisions``: the most recent decisions, newest first.

    LoadCoach's own route takes no ``limit`` (``recent_decisions`` hardcodes 50) — the console
    cannot ask it for a further page, so this listing is not paged by ``[ui] page_rows``; the
    page marks it incomplete and says so whenever exactly the cap comes back (row WX5).

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    return _listed(call(client, settings, APP, "GET", "routing-decisions"), "decisions")


def decisions_db(handle: AppDatabase, *, page_rows: int) -> list[dict[str, Any]]:
    """The ``routing_decisions`` table, newest first, under the API's names.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request. Unlike the
            API path, this read *could* go further with a numbered page, since it is this
            console's own database; it stays a single bounded read so the two sources agree on
            what "incomplete" means for this table, each against its own cap.

    Raises:
        TableUnknown: The database has no ``routing_decisions`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    decisions = []
    for row in rows_where(handle, "routing_decisions", order_by="requested_at", limit=page_rows):
        explanation = _document(_loads(row.get("explanation_json")))
        selected = _document(explanation.get("selected"))
        decisions.append(
            {
                "decision_id": row.get("id"),
                "task_profile": {
                    "id": row.get("task_profile_id"),
                    "version": row.get("task_profile_version"),
                },
                "requested_at": row.get("requested_at"),
                "duration_ms": row.get("duration_ms"),
                "selected": selected.get("canonical_id")
                or row.get("selected_subject_canonical_id"),
                "final_score": row.get("selected_score"),
                "flags": _loads(row.get("flags_json")) or [],
                "job_id": row.get("job_id"),
            }
        )
    return decisions


def decision_api(client: httpx.Client, settings: Settings, decision_id: str) -> dict[str, Any]:
    """``GET /routing-decisions/{id}``: one decision's explanation exactly as it was persisted.

    Raises:
        AppRefused: No such decision, or another refusal.
        AppUnreachable: It did not answer.
    """
    return _document(
        call(client, settings, APP, "GET", f"routing-decisions/{segment(decision_id)}")
    )


def decision_db(handle: AppDatabase, decision_id: str) -> dict[str, Any]:
    """One decision's stored ``explanation_json``, the document the API would have returned.

    Raises:
        NotRecorded: No such decision.
        TableUnknown: The database has no ``routing_decisions`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(handle, "routing_decisions", equals={"id": decision_id}, limit=1)
    if not found:
        raise NotRecorded(
            f"LoadCoach's database holds no routing decision {decision_id!r}.",
            details={"decision_id": decision_id},
        )
    return _document(_loads(found[0].get("explanation_json")))


def _profile_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": row.get("profile_id"),
        "version": row.get("version"),
        "description": row.get("description"),
        "weights": _loads(row.get("weights_json")) or {},
        "constraints": _loads(row.get("constraints_json")),
        "execution": _loads(row.get("execution_json")),
        "validation": _loads(row.get("validation_json")),
        "enabled": bool(row.get("enabled")),
        "updated_at": row.get("updated_at"),
    }


def task_profiles_api(client: httpx.Client, settings: Settings) -> list[dict[str, Any]]:
    """``GET /task-profiles``: every definition with its weights, constraints and policies.

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    return _listed(call(client, settings, APP, "GET", "task-profiles"), "task_profiles")


def task_profiles_db(handle: AppDatabase) -> list[dict[str, Any]]:
    """The ``task_profiles`` table by profile id.

    Raises:
        TableUnknown: The database has no ``task_profiles`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    rows = rows_where(
        handle, "task_profiles", order_by="profile_id", descending=False, limit=LIST_CAP
    )
    return [_profile_row(row) for row in rows]


def task_profile_api(client: httpx.Client, settings: Settings, profile_id: str) -> dict[str, Any]:
    """``GET /task-profiles/{id}``.

    Raises:
        AppRefused: ``TASK_PROFILE_NOT_FOUND``, or another refusal.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", f"task-profiles/{segment(profile_id)}"))


def task_profile_db(handle: AppDatabase, profile_id: str) -> dict[str, Any]:
    """The newest stored version of one task profile.

    Raises:
        NotRecorded: No such profile.
        TableUnknown: The database has no ``task_profiles`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(
        handle, "task_profiles", equals={"profile_id": profile_id}, order_by="updated_at", limit=1
    )
    if not found:
        raise NotRecorded(
            f"LoadCoach's database holds no task profile {profile_id!r}.",
            details={"profile_id": profile_id},
        )
    return _profile_row(found[0])


# --- Reliability ----------------------------------------------------------------------------------


def reliability_api(
    client: httpx.Client, settings: Settings, *, task: str | None, model: str | None, page: int,
    page_rows: int,
) -> dict[str, Any]:  # fmt: skip
    """``GET /reliability``: each pair's windows, factor, regression verdict and breaker.

    LoadCoach's route answers every pair in one call; this reader pages the console's own view
    of that list by ``page_rows`` (row WX5) rather than asking LoadCoach again, since the whole
    document — including ``regressions``, which names every pair, not only this page's — is one
    read. ``regressions`` is therefore never paged: it is a summary section of its own, and
    slicing it to match the current page of the *other* table would silently drop a regression a
    page happens not to show.

    Args:
        page: The pair-table's page number, one-based.
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    body = call(
        client, settings, APP, "GET", "reliability", params={"task": task, "model": model},
        timeout_seconds=30.0,
    )  # fmt: skip
    document = dict(_document(body))
    entries = document.get("reliability") or []
    page = max(1, page)
    start = (page - 1) * page_rows
    document["reliability"] = entries[start : start + page_rows]
    document["next_page"] = page + 1 if len(entries) > start + page_rows else None
    return document


def reliability_db(
    handle: AppDatabase, *, task: str | None, model: str | None, page: int, page_rows: int
) -> dict[str, Any]:
    """The persisted ``reliability_stats`` rows: counts per window, no factor and no verdict.

    The factor, the regression verdict and each rate's minimum are LoadCoach's arithmetic over these
    counts, so a stopped LoadCoach's page shows the counts and says the rest waits for the API.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    canonical = {
        row.get("id"): row.get("canonical_id")
        for row in rows_where(handle, "models", limit=MODEL_CAP)
    }
    rows = rows_where(
        handle, "reliability_stats", equals={"task_profile_id": task}, order_by="updated_at",
        limit=LIST_CAP * 5,
    )  # fmt: skip
    stats = [
        {
            "canonical_id": canonical.get(row.get("model_id")) or row.get("model_id"),
            "adapter_key": row.get("adapter_key") or "",
            "task_profile_id": row.get("task_profile_id"),
            "window": row.get("window"),
            "attempts": row.get("attempts"),
            "successes": row.get("successes"),
            "validation_passes": row.get("validation_passes"),
            "errors": row.get("errors"),
            "timeouts": row.get("timeouts"),
            "cancellations": row.get("cancellations"),
            "p50_latency_ms": row.get("p50_latency_ms"),
            "p95_latency_ms": row.get("p95_latency_ms"),
            "circuit_state": row.get("circuit_state"),
            "circuit_reason": row.get("circuit_reason"),
            "updated_at": row.get("updated_at"),
        }
        for row in rows
    ]
    if model:
        stats = [one for one in stats if one["canonical_id"] == model]
    page = max(1, page)
    start = (page - 1) * page_rows
    return {
        "stats": stats[start : start + page_rows],
        "next_page": page + 1 if len(stats) > start + page_rows else None,
    }


# --- Queue and jobs -------------------------------------------------------------------------------

JOB_STATES: Final[tuple[str, ...]] = (
    "queued",
    "leased",
    "admitted",
    "waiting_resources",
    "executing",
    "validating",
    "retrying",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
)
"""LoadCoach's ``JobState`` members, in its declaration order (queue §2)."""
JOB_CLASSES: Final[tuple[str, ...]] = ("interactive", "normal", "background", "batch")
TERMINAL_JOB_STATES: Final[frozenset[str]] = frozenset({"completed", "failed", "cancelled"})
TERMINAL_FRAMES: Final[frozenset[str]] = frozenset(
    {"job.completed", "job.failed", "job.cancelled", "result", "error"}
)
"""A queued job's stream ends on its terminal ``job.*`` event, a synchronous one's on ``result`` or
``error`` (LoadCoach's ``_STREAM_TERMINAL``)."""
_REPLY_FRAMES: Final[frozenset[str]] = frozenset({"token", "thinking", "tool_call"})
_WARNING_EVENTS: Final[frozenset[str]] = frozenset(
    {"job.cancelled", "job.retrying", "job.fallback", "job.degraded", "job.waiting_resources"}
)
_GENERATOR = GeneratorInfo(name="weightroom", version=__version__)


def queue_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /queue``: depth by state and class, the oldest age, dispatch latency, executions,
    residency, starvation, the breakers and the dispatch flags (queue §11).

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", "queue"))


def queue_events(chunks: Iterable[str]) -> Iterator[tuple[str, dict[str, Any] | None]]:
    """LoadCoach's ``/queue/stream`` as ``(kind, report)``: ``status`` with the whole report,
    ``heartbeat`` for each keep-alive comment, and one ``closed`` when the stream ends or fails.

    The page renders each report itself: the frame's ``html`` is LoadCoach's own markup and never
    reaches this console's DOM (arc index §2 item 4). A heartbeat is surfaced so the proxy writes
    to the browser often enough to notice it has gone.
    """
    event: str | None = None
    data: list[str] = []
    for line in lines(chunks):
        if line.startswith(":"):
            yield "heartbeat", None
            continue
        if line:
            name, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if name == "event":
                event = value
            elif name == "data":
                data.append(value)
            continue
        if event in {"error", "stream.closed"}:
            break
        if event == "queue.status" and data:
            try:
                envelope = json.loads("\n".join(data))
            except ValueError:
                envelope = None
            report = _document(_document(envelope).get("payload")).get("data")
            if isinstance(report, Mapping):
                yield "status", dict(report)
        event, data = None, []
    yield "closed", None


def jobs_api(  # noqa: PLR0913 — one keyword per filter GET /jobs takes
    client: httpx.Client,
    settings: Settings,
    *,
    state: str | None,
    job_class: str | None,
    task: str | None,
    source: str | None,
    cursor: str | None,
    page_rows: int,
) -> dict[str, Any]:
    """``GET /jobs``: one page, newest first, filtered as LoadCoach's own Jobs page filters.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    body = call(
        client, settings, APP, "GET", "jobs",
        params={"state": state, "class": job_class, "task": task, "source": source,
                "cursor": cursor, "limit": page_rows},
    )  # fmt: skip
    page = _document(_document(body).get("page"))
    return {
        "items": _listed(body, "items"),
        "next_cursor": page.get("next_cursor"),
        "next_page": None,
    }


def _canonical_by_model(handle: AppDatabase) -> dict[Any, Any]:
    return {
        row.get("id"): row.get("canonical_id")
        for row in rows_where(handle, "models", limit=MODEL_CAP)
    }


def _job_row(row: Mapping[str, Any], canonical: Mapping[Any, Any]) -> dict[str, Any]:
    """A ``jobs`` row under the job document's names (api.md §5)."""
    return {
        "job_id": row.get("id"),
        "state": row.get("state"),
        "state_reason": row.get("state_reason"),
        "class": row.get("class"),
        "priority": {"base": row.get("base_priority"), "effective": row.get("effective_priority")},
        "source": row.get("source"),
        "task": {"id": row.get("task_profile_id"), "version": row.get("task_profile_version")},
        "idempotent": bool(row.get("idempotent")),
        "cancel_requested": bool(row.get("cancel_requested")),
        "max_wait_seconds": row.get("max_wait_seconds"),
        "timestamps": {
            "created_at": row.get("created_at"),
            "queued_at": row.get("queued_at"),
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
        },
        "model": {
            "canonical_id": canonical.get(row.get("selected_model_id")),
            "subject_canonical_id": row.get("selected_subject_canonical_id"),
            "runtime_profile_hash": row.get("runtime_profile_hash"),
            "served_context": row.get("served_context"),
            "served_context_source": row.get("served_context_source"),
            "target_gpu_index": row.get("target_gpu_index"),
        },
        "attempt": row.get("attempt"),
        "max_attempts": row.get("max_attempts"),
        "error": (
            {"code": row.get("error_code"), "message": row.get("error_text")}
            if row.get("error_code")
            else None
        ),
    }


def jobs_db(  # noqa: PLR0913 — one keyword per filter
    handle: AppDatabase,
    *,
    state: str | None,
    job_class: str | None,
    task: str | None,
    source: str | None,
    page: int,
    page_rows: int,
) -> dict[str, Any]:
    """The ``jobs`` table, newest first, one page by number.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        TableUnknown: The database has no ``jobs`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    page = max(1, page)
    canonical = _canonical_by_model(handle)
    rows = rows_where(
        handle, "jobs",
        equals={"state": state, "class": job_class, "task_profile_id": task, "source": source},
        order_by="created_at", limit=page_rows + 1, offset=(page - 1) * page_rows,
    )  # fmt: skip
    return {
        "items": [_job_row(row, canonical) for row in rows[:page_rows]],
        "next_cursor": None,
        "next_page": page + 1 if len(rows) > page_rows else None,
    }


def job_api(client: httpx.Client, settings: Settings, job_id: str) -> dict[str, Any]:
    """``GET /jobs/{id}`` and its routing explanation, which a job not yet routed has none of.

    Raises:
        AppRefused: ``JOB_NOT_FOUND``, or another refusal of the job itself.
        AppUnreachable: It did not answer.
    """
    job = _document(call(client, settings, APP, "GET", f"jobs/{segment(job_id)}"))
    explanation: dict[str, Any] | None
    try:
        explanation = _document(
            call(client, settings, APP, "GET", f"jobs/{segment(job_id)}/explanation")
        )
    except AppRefused:
        explanation = None
    return {"job": job, "explanation": explanation, "events": None}


def job_db(handle: AppDatabase, job_id: str) -> dict[str, Any]:
    """One job's rows: the job, its attempts, feedback, persisted events and routing decision.

    Raises:
        NotRecorded: No such job.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(handle, "jobs", equals={"id": job_id}, limit=1)
    if not found:
        raise NotRecorded(
            f"LoadCoach's database holds no job {job_id!r}.", details={"job_id": job_id}
        )
    row = found[0]
    canonical = _canonical_by_model(handle)
    mine = {"job_id": job_id}
    attempts = rows_where(
        handle, "job_attempts", equals=mine, order_by="attempt", descending=False, limit=LIST_CAP
    )
    validation = row.get("validation_passed")
    job = _job_row(row, canonical)
    job.update(
        {
            "output": {
                "text": row.get("response_text"),
                "finish_reason": attempts[-1].get("finish_reason") if attempts else None,
                "structured": _loads(row.get("structured_output_json")),
            },
            "reasoning": {
                "available": bool(row.get("reasoning_available")),
                "summary": row.get("reasoning_summary"),
                "source": row.get("reasoning_source"),
            },
            "usage": {
                key: row.get(key)
                for key in (
                    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                    "thinking_tokens",
                )
            },
            "timing": {
                key: row.get(key)
                for key in (
                    "total_ms", "provider_ms", "loadcoach_overhead_ms", "ttft_ms", "queue_wait_ms",
                )
            },
            "validation": {
                "performed": validation is not None,
                "passed": None if validation is None else bool(validation),
                "checks": [],
            },
            "degradations": _loads(row.get("degradations_json")) or [],
            "attempts": [
                {
                    "attempt": one.get("attempt"),
                    "model": one.get("subject_canonical_id") or canonical.get(one.get("model_id")),
                    "rank": one.get("rank"),
                    "outcome": one.get("outcome"),
                    "provider_ms": one.get("provider_ms"),
                    "error_code": one.get("error_code"),
                    "prompt_id": one.get("prompt_id"),
                    "prompt_version": one.get("prompt_version"),
                }
                for one in attempts
            ],
            "feedback": [
                {
                    "source": one.get("source"),
                    "accepted": bool(one.get("accepted")),
                    "quality_score": one.get("quality_score"),
                    "edited": bool(one.get("edited")),
                    "validation": {"passed": one.get("validation_passed")},
                    "notes": one.get("notes"),
                    "updated_at": one.get("updated_at"),
                }
                for one in rows_where(handle, "feedback", equals=mine, limit=LIST_CAP)
            ],
            "retention": {"content_scrubbed_at": None},
        }
    )  # fmt: skip
    decisions = rows_where(
        handle, "routing_decisions", equals=mine, order_by="requested_at", limit=1
    )
    events = rows_where(
        handle, "job_events", equals=mine, order_by="sequence", descending=False,
        limit=LIST_CAP * 5,
    )  # fmt: skip
    return {
        "job": job,
        "explanation": _document(_loads(decisions[0].get("explanation_json")))
        if decisions
        else None,
        "events": [
            {
                "sequence": one.get("sequence"),
                "timestamp": one.get("timestamp"),
                "type": one.get("event_type"),
                "message": one.get("message"),
            }
            for one in events
        ],
    }


def _line_for(event: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    """``(level, message)`` for one of a job's frames, in the log pane's words."""
    if event == "error":
        error = _document(payload.get("error")) or payload
        return "err", f"{error.get('code')}: {error.get('message')}"
    if event == "routing":
        selected = _document(payload.get("selected"))
        chosen = selected.get("subject_canonical_id") or selected.get("canonical_id")
        return "info", f"routed to {chosen}" if chosen else "no candidate was eligible"
    if event == "result":
        output = _document(payload.get("output"))
        return "info", f"{payload.get('status') or 'result'} · finish {output.get('finish_reason')}"
    message = payload.get("message")
    if not message:
        data = _document(payload.get("data"))
        message = " ".join(
            f"{key}={value}" for key, value in data.items() if isinstance(value, (str, int, float))
        )
    level = "err" if event == "job.failed" else "warning" if event in _WARNING_EVENTS else "info"
    return level, str(message or "")


def job_log_frames(chunks: Iterable[str]) -> Iterator[str]:
    """A job's ``/jobs/{id}/stream`` as the console's log-pane frames.

    Each state event, the routing decision and the result become one ``log`` line; the reply's own
    deltas (``token``, ``thinking``, ``tool_call``) are the reply, not the log, and are left to the
    page's reply region. The pane closes with ``log.closed`` on the terminal frame, on the console's
    own ``error`` frame, or when LoadCoach closes the stream.

    Args:
        chunks: :func:`~weightroom.services.app_api.stream`'s text.

    Yields:
        SSE frames, ``log`` then one ``log.closed``.
    """
    sequence = 0

    def frame(kind: str, payload: dict[str, Any]) -> str:
        nonlocal sequence
        sequence += 1
        return format_frame(
            Event(sequence=sequence, type=kind, payload=payload), generator=_GENERATOR
        )

    for one in iter_frames(lines(chunks)):
        if one.event in _REPLY_FRAMES:
            continue
        if one.event == "stream.closed":
            break
        envelope = _document(one.data)
        payload = _document(envelope.get("payload"))
        level, message = _line_for(one.event, payload)
        yield frame(
            "log",
            {
                "at": payload.get("timestamp") or envelope.get("generated_at"),
                "app": one.event,
                "level": level,
                "message": message,
            },
        )
        if one.event in TERMINAL_FRAMES:
            break
    yield frame("log.closed", {"reason": "the job's stream ended"})


# --- Evidence -------------------------------------------------------------------------------------

MATCH_STATES: Final[tuple[str, ...]] = ("bound", "unmatched", "ambiguous_name_only")
EVIDENCE_PAGE: Final = 200


def _evidence_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """One ``capability.evidence`` payload's columns the page shows."""
    model = _document(record.get("model"))
    adapter = _document(record.get("adapter"))
    named = "/".join(
        str(part) for part in (model.get("provider_kind"), model.get("provider_model_name")) if part
    )
    return {
        "canonical_id": model.get("canonical_id") or named or None,
        "capability_id": record.get("capability_id"),
        "score": record.get("score"),
        "confidence": record.get("confidence"),
        "sample_count": record.get("sample_count"),
        "excluded_count": record.get("excluded_count"),
        "measured_at": record.get("measured_at"),
        "runtime_profile_hash": record.get("runtime_profile_hash"),
        "machine_fingerprint": record.get("machine_fingerprint"),
        "adapter": adapter.get("name") or None,
        "stale": None,
        "stale_reason": None,
        "source_id": None,
    }


def abilities_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /evidence?match_state=bound``: the capability vocabulary, and each model's score.

    One call answers both halves of the Models page's **Ability** control (row WX9): the
    vocabulary is the capability ids that actually have bound evidence here — not a list this
    console keeps, which would name capabilities nothing has measured — and the scores are those
    records' own, joined by ``canonical_id``. Only ``bound`` records are read: an unmatched record
    names no model on this machine, so it can neither fill a column nor order one.

    Returns:
        ``capabilities`` (sorted ids) and ``scores`` (``canonical_id`` → ``capability_id`` →
        score). Where a model carries several records for one capability — several runtime
        profiles, several machines — the highest is kept, which is the one routing would see at
        its best, and the page says the column is evidence rather than a promise.

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    body = call(
        client, settings, APP, "GET", "evidence",
        params={"match_state": "bound", "limit": EVIDENCE_PAGE}, timeout_seconds=30.0,
    )  # fmt: skip
    scores: dict[str, dict[str, float]] = {}
    capabilities: set[str] = set()
    for item in _listed(body, "items"):
        record = _evidence_record(_document(item.get("payload")))
        canonical, capability = record.get("canonical_id"), record.get("capability_id")
        score = record.get("score")
        if not canonical or not capability or not isinstance(score, int | float):
            continue
        capabilities.add(str(capability))
        held = scores.setdefault(str(canonical), {})
        held[str(capability)] = max(float(score), held.get(str(capability), float(score)))
    return {"capabilities": sorted(capabilities), "scores": scores}


def speed_api(client: httpx.Client, settings: Settings) -> dict[str, dict[str, Any]]:
    """``GET /reliability``: how fast each model has actually been, over the last seven days.

    Per model, the window of the **busiest** task profile — the pair with the most counted
    attempts in 7d — rather than an average across profiles: LoadCoach's arithmetic produces these
    numbers per pair, and averaging them here would be the console inventing a figure
    (``loadcoach_pages`` module docstring). The profile is carried so the page can name it; a
    number with no profile beside it does not say what it measured.

    Returns:
        ``canonical_id`` → ``mean_tokens_per_second``, ``p95_latency_ms``, ``counted`` and
        ``task_profile_id``. A model no job has run is absent, and the page renders ``—``. The two
        figures are LoadCoach's own bounded measurements — ``{value, samples, minimum, reason}``
        (ADR-0016 rule 5) — and are passed through whole: below its minimum the page must render
        the dash and the reason, not a number.

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    body = call(client, settings, APP, "GET", "reliability", timeout_seconds=30.0)
    fastest: dict[str, dict[str, Any]] = {}
    for entry in _listed(body, "reliability"):
        model = _document(entry.get("model"))
        canonical = str(model.get("subject_canonical_id") or model.get("canonical_id") or "")
        week = _document(_document(entry.get("windows")).get("7d"))
        counted = week.get("counted")
        if not canonical or not isinstance(counted, int) or counted <= 0:
            continue
        if counted <= int(fastest.get(canonical, {}).get("counted") or 0):
            continue
        fastest[canonical] = {
            "mean_tokens_per_second": week.get("mean_tokens_per_second"),
            "p95_latency_ms": week.get("p95_latency_ms"),
            "counted": counted,
            "task_profile_id": entry.get("task_profile_id"),
        }
    return fastest


def evidence_store_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /evidence/sources``: the store's overview, its sources and its configured URL.

    One call, not four: LoadCoach attaches the same ``summary`` to this route that it attaches to
    ``GET /evidence``, so the Evidence *admin* page — which shows no records — never reads them
    (row WX9 split the records off onto ``/evidence``).

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    body = _document(call(client, settings, APP, "GET", "evidence/sources"))
    return {
        "summary": _document(body.get("summary")) or None,
        "sources": _listed(body, "sources"),
        "configured_url": body.get("configured_url"),
    }


def evidence_api(
    client: httpx.Client,
    settings: Settings,
    *,
    capability: str | None = None,
    model: str | None = None,
    min_confidence: str | None = None,
) -> dict[str, Any]:
    """``GET /evidence`` once per ``match_state``, and ``GET /evidence/sources``.

    ``capability``, ``model`` and ``min_confidence`` are LoadCoach's own query parameters, passed
    through rather than filtered here (row WX9): the store is LoadCoach's, and a console-side
    filter over a capped page would hide records the filter should have reached.

    The records are the producer's own ``capability.evidence`` payloads, which carry no binding:
    ``match_state`` is LoadCoach's, so each state is read by its own filter and the record labelled
    with it. The ``summary`` is the store overview the API attaches to every page.

    Not paged by ``[ui] page_rows`` (row WX5): the API's own ``limit``/``cursor`` page one
    ``match_state`` at a time, and this reader already merges three states into one table before
    the console ever sees it, so a console-side page number would not agree with any one of the
    three cursors it would have to track. ``capped`` says whether any state's own read landed
    exactly on ``EVIDENCE_PAGE``, which is this reader's signal that state has more the merged
    list does not show.

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    records: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    capped = False
    for state in MATCH_STATES:
        body = call(
            client, settings, APP, "GET", "evidence",
            params={
                "match_state": state, "limit": EVIDENCE_PAGE, "capability": capability or None,
                "model": model or None, "min_confidence": min_confidence or None,
            },
        )  # fmt: skip
        summary = _document(_document(body).get("summary")) or summary
        items = _listed(body, "items")
        capped = capped or len(items) >= EVIDENCE_PAGE
        records.extend(
            {**_evidence_record(_document(item.get("payload"))), "match_state": state}
            for item in items
        )
    sources = _document(call(client, settings, APP, "GET", "evidence/sources"))
    return {
        "summary": summary,
        "records": records,
        "capped": capped,
        "sources": _listed(sources, "sources"),
        "configured_url": sources.get("configured_url"),
    }


def evidence_db(handle: AppDatabase) -> dict[str, Any]:
    """The ``capability_evidence`` rows, newest measurement first, and ``evidence_sources``.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    sources = rows_where(
        handle, "evidence_sources", order_by="source_key", descending=False, limit=LIST_CAP
    )
    keys = {row.get("id"): row.get("source_key") for row in sources}
    records = [
        {
            "canonical_id": row.get("canonical_id"),
            "capability_id": row.get("capability_id"),
            "score": row.get("score"),
            "confidence": row.get("confidence"),
            "sample_count": row.get("sample_count"),
            "excluded_count": row.get("excluded_count"),
            "measured_at": row.get("measured_at"),
            "runtime_profile_hash": row.get("runtime_profile_hash"),
            "machine_fingerprint": row.get("machine_fingerprint"),
            "adapter": row.get("adapter_artifact_digest") or None,
            "match_state": row.get("match_state"),
            "stale": bool(row.get("stale")),
            "stale_reason": row.get("stale_reason"),
            "source_id": keys.get(row.get("source_id")),
        }
        for row in rows_where(handle, "capability_evidence", order_by="measured_at", limit=LIST_CAP)
    ]
    return {
        "summary": None,
        "records": records,
        "capped": len(records) >= LIST_CAP,
        "sources": [
            {
                "source_id": row.get("source_key"),
                "kind": row.get("kind"),
                "url": row.get("url"),
                "last_import_at": row.get("last_import_at"),
                "last_status": row.get("last_status"),
                "schema_version": row.get("schema_version"),
                "record_count": row.get("record_count"),
                "error_text": row.get("error_text"),
                "generated_at": row.get("generated_at"),
            }
            for row in sources
        ],
        "configured_url": None,
    }


# --- Providers, adapters --------------------------------------------------------------------------


def providers_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /providers``: every registration, its file, the file's digest and what shadows each.

    The registrations live in LoadCoach's configuration file, not its database, so there is no
    stopped reader: a stopped LoadCoach's page says it reads only from the running API.

    Raises:
        AppRefused: LoadCoach refused.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", "providers"))


def adapters_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /adapters``: the directory's adapters, who holds each, residency and recent routes.

    Raises:
        AppRefused: LoadCoach refused, or is older than the route (``HTTP_404``).
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", "adapters", timeout_seconds=30.0))


def adapters_db(handle: AppDatabase) -> dict[str, Any]:
    """The ``adapters`` projection with its residency and routing candidates, by name.

    The directory is the truth (ADR-0061) and only the running LoadCoach reads it, so what a
    provider holds, the manifests that failed and the drafts are absent (``None``) here, never
    guessed; the rows are what LoadCoach last synced.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    canonical = _canonical_by_model(handle)
    adapters = []
    for row in rows_where(handle, "adapters", order_by="name", descending=False, limit=LIST_CAP):
        adapter_id = row.get("id")
        routes = []
        for candidate in rows_where(
            handle, "routing_candidates", equals={"adapter_id": adapter_id}, order_by="created_at",
            limit=20,
        ):  # fmt: skip
            found = rows_where(
                handle, "routing_decisions", equals={"id": candidate.get("decision_id")}, limit=1
            )
            decision = found[0] if found else {}
            routes.append(
                {
                    "decision_id": candidate.get("decision_id"),
                    "job_id": decision.get("job_id"),
                    "task_profile_id": decision.get("task_profile_id"),
                    "requested_at": decision.get("requested_at"),
                    "rank": candidate.get("rank"),
                    "rejected": bool(candidate.get("rejected")),
                    "rejection_reason": candidate.get("rejection_reason"),
                    "selected": decision.get("selected_adapter_id") == adapter_id
                    and decision.get("selected_model_id") == candidate.get("model_id"),
                }
            )
        adapters.append(
            {
                "name": row.get("name"),
                "artifact_sha256": row.get("artifact_sha256"),
                "artifact_path": row.get("artifact_path"),
                "manifest_path": row.get("manifest_path"),
                "base_model_name": row.get("base_model_name"),
                "base_artifact_digest": row.get("base_artifact_digest"),
                "base_confidence": row.get("base_identity_confidence"),
                "declared_capabilities": _loads(row.get("declared_capabilities_json")) or [],
                "data_classification": row.get("data_classification"),
                "available": bool(row.get("available")),
                "unavailable_reason": row.get("unavailable_reason"),
                "registered_on": None,
                "pending_on": None,
                "notes": None,
                "in_directory": None,
                "adapter_id": adapter_id,
                "resident": [
                    {
                        "gpu_index": one.get("gpu_index"),
                        "base_canonical_id": canonical.get(one.get("model_id")),
                        "last_used_at": one.get("last_used_at"),
                    }
                    for one in rows_where(
                        handle,
                        "residency",
                        equals={"adapter_id": adapter_id, "resident": True},
                        limit=LIST_CAP,
                    )  # fmt: skip
                ],
                "routes": routes,
            }
        )
    return {
        "enabled": None,
        "note": None,
        "directory": None,
        "adapters": adapters,
        "invalid": [],
        "drafts": [],
        "unmanifested": [],
    }


# --- System -----------------------------------------------------------------------------------


def system_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /health`` and ``GET /system/status`` (row WPF5): version, health components, and the
    queue report — dispatch latency, starving, active jobs, dispatch state, telemetry, residency
    and circuit breakers.

    ``/health`` answers ``503`` when a component is unavailable, and the console's client reads
    any status of 400 or above as a refusal, so that case renders the refusal beside the status
    half rather than failing the whole page (the same shape as PromptCadence's System page, WPC1).

    Raises:
        AppRefused: ``GET /system/status`` was refused.
        AppUnreachable: It did not answer.
    """
    status = call(client, settings, APP, "GET", "system/status")
    health: Any = None
    health_error: SuiteError | None = None
    try:
        health = call(client, settings, APP, "GET", "health")
    except SuiteError as exc:
        health_error = exc
    return {
        "status": dict(status) if isinstance(status, Mapping) else {},
        "health": dict(health) if isinstance(health, Mapping) else None,
        "health_error": health_error,
    }

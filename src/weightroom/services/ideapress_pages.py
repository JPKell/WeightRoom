"""weightroom.services.ideapress_pages — the data behind IdeaPress's tab (row WP5).

Each page has two readers: one over IdeaPress's own ``/api/v1`` (through
:mod:`~weightroom.services.app_api`) for while it answers, and one over its database
(``data-model.md`` §4) for while it does not, shaping the rows into the keys the API document uses
so a page renders one shape either way. Which one runs is :mod:`~weightroom.services.app_pages`'
decision, never this module's. Workflows, backends and the runtime settings exist only in the
running process — the stage table is code, reachability is a live probe — so those read the API
alone. What a row says reaches the page through the templates, escaped.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Final
from urllib.parse import quote

from baseaicore import SuiteError
from mirrorwall import Event, format_frame
from setspec import GeneratorInfo

from weightroom.__about__ import __version__
from weightroom.services.app_api import call, lines
from weightroom.services.app_pages import rows_where
from weightroom.services.chat_loadcoach import iter_frames

if TYPE_CHECKING:
    import httpx

    from weightroom.config import Settings
    from weightroom.services.db_reader import AppDatabase

__all__ = [
    "APP",
    "ProjectNotRecorded",
    "backends_api",
    "project_api",
    "project_db",
    "projects_api",
    "projects_db",
    "segment",
    "settings_api",
    "workflow_api",
    "workflows_api",
    "RUN_STAGES",
    "TaskNotRecorded",
    "UnitNotRecorded",
    "export_api",
    "plan_api",
    "plan_db",
    "research_api",
    "research_db",
    "task_api",
    "task_db",
    "task_log_frames",
    "unit_api",
    "unit_db",
    "workspace_api",
]

APP: Final = "ideapress"
LIST_CAP: Final = 200
STAGE_HISTORY: Final = 50
"""IdeaPress's ``GET /projects/{id}`` lists its newest 50 stage runs; the stopped reader too."""


class ProjectNotRecorded(SuiteError):
    """IdeaPress's database holds no project with that id."""

    code: ClassVar[str] = "PROJECT_NOT_FOUND"


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


def _items(body: Any, key: str = "items") -> list[dict[str, Any]]:  # noqa: ANN401
    items = body.get(key) if isinstance(body, Mapping) else None
    return [dict(one) for one in items or [] if isinstance(one, Mapping)]


# --- Projects -------------------------------------------------------------------------------------


def projects_api(
    client: httpx.Client,
    settings: Settings,
    *,
    status: str | None,
    content_type: str | None,
    archived: bool,
    cursor: str | None,
    page_rows: int,
) -> dict[str, Any]:
    """``GET /projects``: one page, newest activity first, with IdeaPress's own cursor.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        AppRefused: IdeaPress refused (a cursor it did not issue is its ``VALIDATION_ERROR``).
        AppUnreachable: It did not answer.
    """
    body = call(
        client, settings, APP, "GET", "projects",
        params={
            "status": status, "content_type": content_type, "cursor": cursor, "limit": page_rows,
            "include_archived": "true" if archived else None,
        },
    )  # fmt: skip
    page = body.get("page") if isinstance(body, Mapping) else None
    return {
        "items": _items(body),
        "next_cursor": page.get("next_cursor") if isinstance(page, Mapping) else None,
        "next_page": None,
    }


def _project_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A ``projects`` row under the API document's names (its columns differ: ``brief_text``)."""
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "slug": row.get("slug"),
        "content_type": row.get("content_type"),
        "content_type_version": row.get("content_type_version"),
        "workflow_id": row.get("workflow_id"),
        "workflow_version": row.get("workflow_version"),
        "status": row.get("status"),
        "brief": row.get("brief_text"),
        "author_material": _loads(row.get("author_material_json")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "completed_at": row.get("completed_at"),
        "archived_at": row.get("archived_at"),
    }


def projects_db(
    handle: AppDatabase,
    *,
    status: str | None,
    content_type: str | None,
    archived: bool,
    page: int,
    page_rows: int,
) -> dict[str, Any]:
    """The ``projects`` table, newest activity first, one page by number.

    Args:
        page_rows: The page size — ``[ui] page_rows`` (row WX5), read per request.

    Raises:
        TableUnknown: The database has no ``projects`` table.
        ReadFailed: The database refused or ran past the timeout.
    """
    page = max(1, page)
    rows = rows_where(
        handle, "projects", equals={"status": status, "content_type": content_type},
        order_by="updated_at", limit=page_rows + 1, offset=(page - 1) * page_rows,
    )  # fmt: skip
    items = [_project_row(row) for row in rows[:page_rows]]
    if not archived and not status:
        # ponytail: archived rows are dropped after the page is read, so a stopped page can come
        # back short; filter in SQL once the reader grows a not-equal condition.
        items = [one for one in items if one["status"] != "archived"]
    return {
        "items": items,
        "next_cursor": None,
        "next_page": page + 1 if len(rows) > page_rows else None,
    }


def project_api(client: httpx.Client, settings: Settings, project_id: str) -> dict[str, Any]:
    """``GET /projects/{id}``: the project, its plan summary, units and stage history.

    Raises:
        AppRefused: ``PROJECT_NOT_FOUND``, or another refusal.
        AppUnreachable: It did not answer.
    """
    body = call(client, settings, APP, "GET", f"projects/{segment(project_id)}")
    return {"project": _document(body)}


def _unit_row(row: Mapping[str, Any], version: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "unit_key": row.get("unit_key"),
        "ordinal": row.get("ordinal"),
        "title": row.get("title"),
        "goal": row.get("goal_text"),
        "state": row.get("state"),
        "paused_reason": row.get("paused_reason"),
        "requirement_keys": _loads(row.get("requirement_keys_json")) or [],
        "version": version.get("version") if version else None,
        "word_count": version.get("word_count") if version else None,
        "content_hash": version.get("content_hash") if version else None,
        # Computed by IdeaPress from coverage and validation rows; the stopped page says `—`.
        "coverage": None,
        "last_validation": None,
    }


def _stage_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": row.get("id"),
        "stage": row.get("stage"),
        "state": row.get("state"),
        "units_total": row.get("units_total"),
        "units_completed": row.get("units_completed"),
        "units_paused": row.get("units_paused"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "error_code": row.get("error_code"),
        "error_text": row.get("error_text"),
        "options": _loads(row.get("options_json")) or {},
    }


def units_db(handle: AppDatabase, project_id: str) -> list[dict[str, Any]]:
    """A project's ``units`` rows in reading order, each with its current version's figures.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    rows = rows_where(
        handle, "units", equals={"project_id": project_id}, order_by="ordinal", descending=False,
        limit=LIST_CAP,
    )  # fmt: skip
    units = []
    for row in rows:
        found = (
            rows_where(
                handle, "unit_versions", equals={"id": row.get("current_version_id")}, limit=1
            )
            if row.get("current_version_id")
            else []
        )
        units.append(_unit_row(row, found[0] if found else None))
    return units


def project_db(handle: AppDatabase, project_id: str) -> dict[str, Any]:
    """One project's row with its units, requirement counts and stage runs, as the API shapes it.

    Raises:
        ProjectNotRecorded: No such project in the database.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(handle, "projects", equals={"id": project_id}, limit=1)
    if not found:
        raise ProjectNotRecorded(
            f"IdeaPress's database holds no project {project_id!r}.",
            details={"project_id": project_id},
        )
    units = units_db(handle, project_id)
    requirements = rows_where(
        handle, "requirements", equals={"project_id": project_id}, limit=LIST_CAP
    )
    stages = rows_where(
        handle, "stage_runs", equals={"project_id": project_id}, order_by="started_at",
        limit=STAGE_HISTORY,
    )  # fmt: skip
    plan = (
        {
            "units": len(units),
            "requirements": len(requirements),
            "blocking": sum(1 for one in requirements if one.get("blocking")),
        }
        if units or requirements
        else None
    )
    project = {
        **_project_row(found[0]),
        "plan": plan,
        "units": units,
        "stages": [_stage_row(row) for row in stages],
        # Which run is in flight lives in the running process; a stopped one runs nothing.
        "running_task_id": None,
    }
    return {"project": project}


# --- Workflows, backends, settings ---------------------------------------------------------------


def workflows_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /workflows``: every definition — stage order, gates, which stages use a model.

    Raises:
        AppRefused: IdeaPress refused.
        AppUnreachable: It did not answer.
    """
    return {"workflows": _items(call(client, settings, APP, "GET", "workflows"), "workflows")}


def workflow_api(client: httpx.Client, settings: Settings, workflow_id: str) -> dict[str, Any]:
    """``GET /workflows/{id}``: one definition.

    Raises:
        AppRefused: An unknown workflow is IdeaPress's ``STAGE_PRECONDITION_FAILED``.
        AppUnreachable: It did not answer.
    """
    return {
        "workflow": _document(
            call(client, settings, APP, "GET", f"workflows/{segment(workflow_id)}")
        )
    }


def backends_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /backends``: each configured backend with mode, reachability, capabilities, egress.

    Raises:
        AppRefused: IdeaPress refused.
        AppUnreachable: It did not answer.
    """
    return {
        "backends": _items(
            call(client, settings, APP, "GET", "backends", timeout_seconds=30.0), "backends"
        )
    }


def settings_api(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    """``GET /settings``: the effective runtime values, and when each applies (api.md §6).

    The stage bindings and workflow limits a run would use are read from here, never re-derived.

    Raises:
        AppRefused: IdeaPress refused.
        AppUnreachable: It did not answer.
    """
    body = _document(call(client, settings, APP, "GET", "settings"))
    values = body.get("settings")
    definitions = body.get("definitions")
    return {
        "settings": dict(values) if isinstance(values, Mapping) else {},
        "definitions": dict(definitions) if isinstance(definitions, Mapping) else {},
    }


# --- The plan and research (Gate C) ---------------------------------------------------------------

RUN_STAGES: Final[tuple[str, ...]] = ("draft", "project_review", "research")
"""The stages a person starts from IdeaPress's workspace and CLI, beside the plan and a revision,
which have forms of their own. IdeaPress refuses by name any stage it has no body for."""


class TaskNotRecorded(SuiteError):
    """IdeaPress's database holds no such stage run for that project."""

    code: ClassVar[str] = "NOT_FOUND"


class UnitNotRecorded(SuiteError):
    """IdeaPress's database holds no such unit in that project."""

    code: ClassVar[str] = "UNIT_NOT_FOUND"


def plan_api(client: httpx.Client, settings: Settings, project_id: str) -> dict[str, Any]:
    """``GET /projects/{id}/plan``: every requirement with its source, and the unit plan.

    Raises:
        AppRefused: ``PROJECT_NOT_FOUND``, or another refusal.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", f"projects/{segment(project_id)}/plan"))


def plan_db(handle: AppDatabase, project_id: str) -> dict[str, Any]:
    """The ``requirements`` and ``units`` rows under the plan document's names.

    How a check is worded, and whether it is mechanical, is IdeaPress's own reading of the stored
    checks: the stopped page shows ``—`` for both rather than a second reading of them.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    requirements = rows_where(
        handle, "requirements", equals={"project_id": project_id}, order_by="requirement_key",
        descending=False, limit=LIST_CAP,
    )  # fmt: skip
    units = rows_where(
        handle, "units", equals={"project_id": project_id}, order_by="ordinal", descending=False,
        limit=LIST_CAP,
    )  # fmt: skip
    carried = {str(u.get("unit_key")): _loads(u.get("requirement_keys_json")) or [] for u in units}
    return {
        "project_id": project_id,
        "requirements": [
            {
                "key": one.get("requirement_key"),
                "text": one.get("text"),
                "blocking": bool(one.get("blocking")),
                "source": one.get("source_document"),
                "quote": one.get("source_quote"),
                "checks": None,
                "mechanical": None,
                "units": [
                    key for key, keys in carried.items() if one.get("requirement_key") in keys
                ],
            }
            for one in requirements
        ],
        "units": [
            {
                "key": one.get("unit_key"),
                "title": one.get("title"),
                "goal": one.get("goal_text"),
                "requirements": ", ".join(carried.get(str(one.get("unit_key")), [])),
                "state": one.get("state"),
                "target_words": one.get("target_words"),
            }
            for one in units
        ],
        "editable_states": None,
    }


def research_api(client: httpx.Client, settings: Settings, project_id: str) -> dict[str, Any]:
    """``GET /projects/{id}/research``: where a fetch may go, the notes, every call and its egress.

    Raises:
        AppRefused: ``PROJECT_NOT_FOUND``, or another refusal.
        AppUnreachable: It did not answer.
    """
    return _document(call(client, settings, APP, "GET", f"projects/{segment(project_id)}/research"))


def research_db(handle: AppDatabase, project_id: str) -> dict[str, Any]:
    """The ``sources`` and ``tool_call_records`` rows, each call joined to its egress decision.

    The join is IdeaPress's own: a research decision is recorded under the project's pseudo-run
    ``project:<id>`` with the call's ``invocation_id`` as its ``source_ref`` (data model §2).
    Where a fetch may go is configuration, which only the running process holds.

    Raises:
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    notes = rows_where(
        handle, "sources", equals={"project_id": project_id}, order_by="created_at",
        descending=False, limit=LIST_CAP,
    )  # fmt: skip
    calls = rows_where(
        handle, "tool_call_records", equals={"project_id": project_id}, order_by="started_at",
        descending=False, limit=LIST_CAP,
    )  # fmt: skip
    decisions: dict[str, Any] = {}
    for row in rows_where(
        handle, "egress_decisions", equals={"run_id": f"project:{project_id}"}, limit=LIST_CAP
    ):
        body = _document(_loads(row.get("decision_json")))
        reference = _document(body.get("request")).get("source_ref")
        if reference:
            decisions[str(reference)] = body
    return {
        "allowed_hosts": None,
        "allowed_tools": None,
        "notes": [
            {
                "kind": one.get("kind"),
                "title": one.get("title"),
                "citation": one.get("path") or one.get("title"),
                "sha256": one.get("sha256"),
                "characters": len(str(one.get("content_text") or "")),
            }
            for one in notes
        ],
        "tool_calls": [
            {
                "tool": one.get("tool_name"),
                "status": one.get("status"),
                "reason": one.get("reason"),
                "detail": one.get("reason_detail"),
                "duration_ms": one.get("duration_ms"),
                "egress": one.get("egress"),
                "started_at": one.get("started_at"),
                "invocation_id": one.get("invocation_id"),
                "egress_decision": decisions.get(str(one.get("invocation_id"))),
            }
            for one in calls
        ],
    }


# --- Stage runs -----------------------------------------------------------------------------------

TERMINAL_STAGE_EVENTS: Final = frozenset({"stage.completed", "stage.failed"})
_STATE_EVENTS: Final = frozenset(
    {"unit.paused", "unit.reset", "revision.rejected", "research.egress_denied", "stage.failed"}
)
"""States a run reached that a person should look at: coloured as a warning, never as an error
the console itself raised (`stage.failed` carries a cancellation as well as a failure)."""
_GENERATOR = GeneratorInfo(name="weightroom", version=__version__)


def _attempt_row(row: Mapping[str, Any], unit_keys: Mapping[str, str]) -> dict[str, Any]:
    return {
        "attempt_id": row.get("id"),
        "stage": row.get("stage"),
        "unit_key": unit_keys.get(str(row.get("unit_id"))),
        "attempt": row.get("attempt"),
        "round": row.get("round"),
        # `0` for the call whose answer this attempt kept, `1` and up for a call it discarded and
        # retried (IdeaPress migration 0012, row WPF7). A database older than that migration has no
        # such column at all — `rows_where` then omits the key rather than raising — and every row
        # it holds predates the concept of a discarded call, so `0` is what it always was.
        "transport_call": row.get("transport_call") or 0,
        "outcome": row.get("outcome"),
        "backend": row.get("backend"),
        "model_canonical_id": row.get("model_canonical_id"),
        "prompt_id": row.get("prompt_id"),
        "prompt_version": row.get("prompt_version"),
        "prompt_source": row.get("prompt_source"),
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
        "provider_ms": row.get("provider_ms"),
        "degradations": _loads(row.get("degradations_json")) or [],
        "error_code": row.get("error_code"),
        "routing": _loads(row.get("routing_json")),
        "egress": None,
    }


def task_api(
    client: httpx.Client, settings: Settings, project_id: str, task_id: str
) -> dict[str, Any]:
    """``GET /projects/{id}/tasks/{task}``: the run's state, counts, attempts and degradations.

    Raises:
        AppRefused: A run IdeaPress does not hold for that project (its ``PROJECT_NOT_FOUND``).
        AppUnreachable: It did not answer.
    """
    path = f"projects/{segment(project_id)}/tasks/{segment(task_id)}"
    return {"task": _document(call(client, settings, APP, "GET", path)), "events": None}


def task_db(handle: AppDatabase, project_id: str, task_id: str) -> dict[str, Any]:
    """One ``stage_runs`` row with its attempts and every persisted stage event, in sequence.

    Raises:
        TaskNotRecorded: The database holds no such run for that project.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(
        handle, "stage_runs", equals={"id": task_id, "project_id": project_id}, limit=1
    )
    if not found:
        raise TaskNotRecorded(
            f"IdeaPress's database holds no stage run {task_id!r} for project {project_id!r}.",
            details={"project_id": project_id, "task_id": task_id},
        )
    unit_keys = {
        str(one.get("id")): str(one.get("unit_key"))
        for one in rows_where(handle, "units", equals={"project_id": project_id}, limit=LIST_CAP)
    }
    attempts = rows_where(
        handle, "attempts", equals={"stage_run_id": task_id}, order_by="created_at",
        descending=False, limit=LIST_CAP,
    )  # fmt: skip
    events = rows_where(
        handle, "stage_events", equals={"stage_run_id": task_id}, order_by="sequence",
        descending=False, limit=LIST_CAP * 5,
    )  # fmt: skip
    task = {
        **_stage_row(found[0]),
        "backend": found[0].get("backend"),
        "attempts": [_attempt_row(one, unit_keys) for one in attempts],
    }
    return {
        "task": task,
        "events": [
            {
                "sequence": one.get("sequence"),
                "at": one.get("timestamp"),
                "event": one.get("event_type"),
                "message": one.get("message"),
            }
            for one in events
        ],
    }


def task_log_frames(chunks: Iterable[str]) -> Iterator[str]:
    """IdeaPress's task stream as the frames the console's log pane reads.

    Every enveloped frame becomes one ``log`` line in IdeaPress's own words (the event's
    ``message``). A bare ``token`` frame — the one frame with no envelope (ADR-0025 §3) — becomes a
    line of its text, escaped by the pane like any other. ``unit.paused`` and ``stage.failed`` are
    states the run reached: a warning line naming the state, never the proxy's own error. The pane
    closes with ``log.closed`` after IdeaPress's terminal event, on the console's own ``error``
    frame from :func:`~weightroom.services.app_api.stream`, or when IdeaPress closes the stream.

    Args:
        chunks: :func:`~weightroom.services.app_api.stream`'s text.

    Yields:
        SSE frames, ``log`` then one ``log.closed``.
    """
    # ponytail: a reconnect replays the run from its first event (the pane's own ids are not
    # IdeaPress's); forward upstream ids if a pane ever needs to resume mid-stream.
    sequence = 0

    def frame(kind: str, payload: dict[str, Any]) -> str:
        nonlocal sequence
        sequence += 1
        return format_frame(
            Event(sequence=sequence, type=kind, payload=payload), generator=_GENERATOR
        )

    for one in iter_frames(lines(chunks)):
        if one.event == "stream.closed":
            break
        if one.event == "token":
            text = one.data if isinstance(one.data, str) else _document(one.data).get("text", "")
            at = datetime.now(UTC).isoformat()
            yield frame("log", {"at": at, "app": "token", "level": "info", "message": str(text)})
            continue
        envelope = _document(one.data)
        payload = _document(envelope.get("payload"))
        if one.event == "error":
            message = f"{payload.get('code')}: {payload.get('message')}"
            when = envelope.get("generated_at")
            yield frame("log", {"at": when, "app": "error", "level": "err", "message": message})
            break
        message = str(payload.get("message") or one.event)
        if one.event == "stage.failed":
            state = _document(payload.get("data")).get("state") or "failed"
            message = f"the stage ended {state}: {message}"
        yield frame(
            "log",
            {
                "at": payload.get("occurred_at") or envelope.get("generated_at"),
                "app": one.event,
                "level": "warning" if one.event in _STATE_EVENTS else "info",
                "message": message,
            },
        )
        if one.event in TERMINAL_STAGE_EVENTS:
            break
    yield frame("log.closed", {"reason": "the stage's stream ended"})


# --- Units, the workspace, export -----------------------------------------------------------------


def unit_api(
    client: httpx.Client, settings: Settings, project_id: str, unit_key: str
) -> dict[str, Any]:
    """``GET …/units/{key}`` and its ``/history``: content, provenance, and every version.

    Raises:
        AppRefused: ``UNIT_NOT_FOUND``, or another refusal.
        AppUnreachable: It did not answer.
    """
    path = f"projects/{segment(project_id)}/units/{segment(unit_key)}"
    unit = _document(call(client, settings, APP, "GET", path))
    history = call(client, settings, APP, "GET", f"{path}/history")
    return {"unit": unit, "versions": _items(history, "versions")}


def unit_db(handle: AppDatabase, project_id: str, unit_key: str) -> dict[str, Any]:
    """One ``units`` row, its current content, its versions newest first, and its attempts.

    Coverage, validation, findings and critiques are IdeaPress's own assembly of several tables;
    the stopped page says it reads those only from the running API rather than re-assembling them.

    Raises:
        UnitNotRecorded: The database holds no such unit in that project.
        TableUnknown: A table this reader expects is absent.
        ReadFailed: The database refused or ran past the timeout.
    """
    found = rows_where(
        handle, "units", equals={"project_id": project_id, "unit_key": unit_key}, limit=1
    )
    if not found:
        raise UnitNotRecorded(
            f"IdeaPress's database holds no unit {unit_key!r} in project {project_id!r}.",
            details={"project_id": project_id, "unit_key": unit_key},
        )
    row = found[0]
    versions = rows_where(
        handle, "unit_versions", equals={"unit_id": row.get("id")}, order_by="version",
        limit=LIST_CAP,
    )  # fmt: skip
    current = next(
        (one for one in versions if one.get("id") == row.get("current_version_id")), None
    )
    attempts = rows_where(
        handle, "attempts", equals={"unit_id": row.get("id")}, order_by="created_at",
        descending=False, limit=LIST_CAP,
    )  # fmt: skip
    keys = {str(row.get("id")): unit_key}
    unit = {
        **_unit_row(row, current),
        "project_id": project_id,
        "content": (current or {}).get("content_text") or "",
        "committed_at": (current or {}).get("committed_at"),
        "attempts": [_attempt_row(one, keys) for one in attempts],
        "coverage": None,
        "validation": None,
        "findings": None,
        "critiques": None,
        "requirements": None,
        "research": None,
        "cost": None,
    }
    return {
        "unit": unit,
        "versions": [
            {
                "version": one.get("version"),
                "committed": bool(one.get("committed")),
                "committed_at": one.get("committed_at"),
                "content_hash": one.get("content_hash"),
                "word_count": one.get("word_count"),
                "created_at": one.get("created_at"),
                "coverage": None,
                "attempts": None,
                "validations": None,
                "findings": None,
                "critiques": None,
            }
            for one in versions
        ],
    }


def workspace_api(
    client: httpx.Client,
    settings: Settings,
    project_id: str,
    *,
    unit: str | None,
    compare: int | None,
) -> dict[str, Any]:
    """``GET /projects/{id}/workspace``: IdeaPress's own workspace view of one unit.

    Raises:
        AppRefused: ``PROJECT_NOT_FOUND``, or another refusal.
        AppUnreachable: It did not answer.
    """
    body = call(
        client, settings, APP, "GET", f"projects/{segment(project_id)}/workspace",
        params={"unit": unit or None, "compare": compare}, timeout_seconds=30.0,
    )  # fmt: skip
    return _document(body)


def export_api(client: httpx.Client, settings: Settings, project_id: str) -> dict[str, Any]:
    """``GET /export/formats`` and the project's units: what an export would contain.

    Raises:
        AppRefused: ``PROJECT_NOT_FOUND``, or another refusal.
        AppUnreachable: It did not answer.
    """
    formats = _items(call(client, settings, APP, "GET", "export/formats"), "formats")
    units = _items(
        call(client, settings, APP, "GET", f"projects/{segment(project_id)}/units"), "units"
    )
    return {"formats": formats, "units": units}

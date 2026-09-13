"""weightroom.services.ideapress_actions — what the IdeaPress pages ask IdeaPress to do (row WP5).

Each function turns a form into IdeaPress's own body and sends it through the shared client. The
console validates nothing IdeaPress validates: a refusal comes back as :class:`AppRefused` in
IdeaPress's own code and words, and the page renders it. The one check here is the form's own
shape — author material is a JSON object in IdeaPress's body, and a textarea is text.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, Final

from baseaicore import SuiteError

from weightroom.services.app_api import call
from weightroom.services.app_api import text as fetch_text
from weightroom.services.ideapress_pages import APP, segment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import httpx

    from weightroom.config import Settings

__all__ = [
    "IdeaPressFormInvalid",
    "author_material",
    "cancel_task",
    "create_project",
    "delete_project",
    "edit_plan",
    "plan_edit_body",
    "read_export",
    "resume_unit",
    "revise_unit",
    "run_body",
    "start_plan",
    "start_stage",
    "test_backend",
    "update_project",
    "save_workflow",
    "workflow_body",
    "write_export",
]

ACTION_TIMEOUT_SECONDS: Final = 60.0
"""A delete that archives first, or a backend round trip, can take longer than a read."""


class IdeaPressFormInvalid(SuiteError):
    """A form field IdeaPress's body cannot carry as typed; nothing was sent."""

    code: ClassVar[str] = "VALIDATION_ERROR"


def author_material(raw: str) -> dict[str, Any]:
    """The form's author material as IdeaPress's body takes it: a JSON object, or nothing.

    Args:
        raw: The textarea's text.

    Returns:
        The object; ``{}`` for blank text.

    Raises:
        IdeaPressFormInvalid: The text is not a JSON object. Nothing is sent.
    """
    text = raw.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except ValueError as exc:
        message = f"Author material must be a JSON object, as IdeaPress stores it: {exc}."
        raise IdeaPressFormInvalid(message, details={"field": "author_material"}) from exc
    if not isinstance(value, dict):
        message = "Author material must be a JSON object ({…}), as IdeaPress stores it."
        raise IdeaPressFormInvalid(message, details={"field": "author_material"})
    return value


def create_project(  # noqa: PLR0913 — one keyword per field of POST /projects' body
    client: httpx.Client,
    settings: Settings,
    *,
    title: str,
    content_type: str,
    workflow_id: str,
    brief: str,
    author_material_text: str,
) -> dict[str, Any]:
    """``POST /projects`` with the create form's fields.

    Raises:
        IdeaPressFormInvalid: The author material is not a JSON object; nothing was sent.
        AppRefused: IdeaPress refused (an empty title is its ``VALIDATION_ERROR``).
        AppUnreachable: It did not answer.
    """
    body = {
        "title": title,
        "content_type": content_type or "article",
        "workflow_id": workflow_id or "standard",
        "brief": brief,
        "author_material": author_material(author_material_text),
    }
    created = call(client, settings, APP, "POST", "projects", body=body)
    return dict(created) if isinstance(created, dict) else {}


def update_project(  # noqa: PLR0913 — one keyword per field of PUT /projects/{id}'s body
    client: httpx.Client,
    settings: Settings,
    project_id: str,
    *,
    title: str,
    brief: str,
    author_material_text: str,
    status: str,
) -> dict[str, Any]:
    """``PUT /projects/{id}``. IdeaPress never recompiles requirements on a save (api.md §2).

    Raises:
        IdeaPressFormInvalid: The author material is not a JSON object; nothing was sent.
        AppRefused: IdeaPress refused (an unknown status is its ``VALIDATION_ERROR``).
        AppUnreachable: It did not answer.
    """
    body: dict[str, Any] = {
        "title": title,
        "brief": brief,
        "author_material": author_material(author_material_text),
    }
    if status:
        body["status"] = status
    updated = call(client, settings, APP, "PUT", f"projects/{segment(project_id)}", body=body)
    return dict(updated) if isinstance(updated, dict) else {}


def delete_project(
    client: httpx.Client, settings: Settings, project_id: str, *, confirm: bool, archive: bool
) -> dict[str, Any]:
    """``DELETE /projects/{id}``: IdeaPress's preview, or the delete, archiving first when asked.

    Raises:
        AppRefused: ``PROJECT_NOT_FOUND``, or ``EXPORT_FAILED`` when the archive could not be
            written — in which case IdeaPress deleted nothing.
        AppUnreachable: It did not answer.
    """
    answer = call(
        client, settings, APP, "DELETE", f"projects/{segment(project_id)}",
        params={"confirm": "true" if confirm else None, "archive": "true" if archive else None},
        timeout_seconds=ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(answer) if isinstance(answer, dict) else {}


def test_backend(client: httpx.Client, settings: Settings, mode: str) -> dict[str, Any]:
    """``POST /backends/test``: a round trip to one backend — latency, models, version.

    Raises:
        AppRefused: IdeaPress refused (a mode it cannot build).
        AppUnreachable: It did not answer.
    """
    answer = call(
        client, settings, APP, "POST", "backends/test", body={"mode": mode or None},
        timeout_seconds=ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(answer) if isinstance(answer, dict) else {}


# --- Gate C: the plan, stage runs, units, export --------------------------------------------------


def _keys(raw: str) -> list[str]:
    """Comma-separated keys with blanks dropped, as IdeaPress's own forms read them."""
    return [part.strip() for part in raw.split(",") if part.strip()]


def _whole(label: str, field: str, raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        message = f"{label} is a whole number."
        raise IdeaPressFormInvalid(message, details={"field": field}) from exc


def start_plan(client: httpx.Client, settings: Settings, project_id: str) -> dict[str, Any]:
    """``POST /projects/{id}/plan``: compile requirements and outline the units; the task.

    Raises:
        AppRefused: ``STAGE_ALREADY_RUNNING``, a brief-less project's refusal, or another.
        AppUnreachable: It did not answer.
    """
    answer = call(
        client, settings, APP, "POST", f"projects/{segment(project_id)}/plan",
        timeout_seconds=ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(answer) if isinstance(answer, dict) else {}


def plan_edit_body(  # noqa: PLR0913 — one keyword per field of the plan editor's forms
    *, operation: str, unit_keys: str, requirement_keys: str, text: str, position: str
) -> dict[str, Any]:
    """One plan-editor form as IdeaPress's ``POST …/plan/edits`` body.

    Raises:
        IdeaPressFormInvalid: A position that is not a whole number; nothing is sent.
    """
    body: dict[str, Any] = {
        "operation": operation,
        "unit_keys": _keys(unit_keys),
        "requirement_keys": _keys(requirement_keys),
        "text": text,
    }
    if position.strip():
        body["position"] = _whole("A position", "position", position)
    return body


def edit_plan(
    client: httpx.Client, settings: Settings, project_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """``POST /projects/{id}/plan/edits``: the plan as stored after the edit.

    Raises:
        AppRefused: The gate's ``VALIDATION_ERROR``, naming an orphaned requirement or a protected
            unit in its details; the plan is unchanged.
        AppUnreachable: It did not answer.
    """
    answer = call(
        client, settings, APP, "POST", f"projects/{segment(project_id)}/plan/edits", body=body
    )
    return dict(answer) if isinstance(answer, dict) else {}


def run_body(
    *, units: str, resume: bool, model_hint: str, max_revision_rounds: str, instructions: str = ""
) -> dict[str, Any]:
    """A stage run's body (api.md §3): the units named, ``resume``, and only the overrides given.

    Raises:
        IdeaPressFormInvalid: A round limit that is not a whole number; nothing is sent.
    """
    body: dict[str, Any] = {"resume": resume}
    keys = _keys(units)
    if keys:
        body["units"] = keys
    overrides: dict[str, Any] = {}
    if model_hint.strip():
        overrides["model_hint"] = model_hint.strip()
    if max_revision_rounds.strip():
        overrides["max_revision_rounds"] = _whole(
            "A round limit", "max_revision_rounds", max_revision_rounds
        )
    if instructions.strip():
        overrides["instructions"] = instructions
    if overrides:
        body["overrides"] = overrides
    return body


def start_stage(
    client: httpx.Client, settings: Settings, project_id: str, stage: str, body: dict[str, Any]
) -> dict[str, Any]:
    """``POST /projects/{id}/stages/{stage}/run``: the task that is now running.

    Raises:
        AppRefused: ``STAGE_ALREADY_RUNNING``, ``STAGE_PRECONDITION_FAILED``, an override's
            ``VALIDATION_ERROR``, or another refusal.
        AppUnreachable: It did not answer.
    """
    answer = call(
        client, settings, APP, "POST",
        f"projects/{segment(project_id)}/stages/{segment(stage)}/run", body=body,
        timeout_seconds=ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(answer) if isinstance(answer, dict) else {}


def cancel_task(
    client: httpx.Client, settings: Settings, project_id: str, task_id: str
) -> dict[str, Any]:
    """``POST …/tasks/{task}/cancel``, honoured at the next model-call boundary.

    Raises:
        AppRefused: IdeaPress refused.
        AppUnreachable: It did not answer.
    """
    path = f"projects/{segment(project_id)}/tasks/{segment(task_id)}/cancel"
    answer = call(client, settings, APP, "POST", path)
    return dict(answer) if isinstance(answer, dict) else {}


def revise_unit(
    client: httpx.Client, settings: Settings, project_id: str, unit_key: str, instructions: str
) -> dict[str, Any]:
    """``POST …/units/{key}/revise``: a revision into a new version, within IdeaPress's bounds.

    Raises:
        AppRefused: ``STAGE_PRECONDITION_FAILED`` for a unit IdeaPress will not revise, or another.
        AppUnreachable: It did not answer.
    """
    answer = call(
        client, settings, APP, "POST",
        f"projects/{segment(project_id)}/units/{segment(unit_key)}/revise",
        body={"instructions": instructions}, timeout_seconds=ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(answer) if isinstance(answer, dict) else {}


def resume_unit(
    client: httpx.Client, settings: Settings, project_id: str, unit_key: str
) -> dict[str, Any]:
    """A draft run over one unit with ``resume``: IdeaPress's own workspace resume, as its API.

    A unit a gone run stranded mid-flight is returned to ``paused`` by IdeaPress first (row WI1).

    Raises:
        AppRefused: IdeaPress refused.
        AppUnreachable: It did not answer.
    """
    return start_stage(client, settings, project_id, "draft", {"units": [unit_key], "resume": True})


def write_export(
    client: httpx.Client, settings: Settings, project_id: str, fmt: str
) -> dict[str, Any]:
    """``POST /projects/{id}/export``: the file IdeaPress wrote into the project's directory.

    Raises:
        AppRefused: ``EXPORT_FAILED`` (a partial plan, an unknown format), or another refusal.
        AppUnreachable: It did not answer.
    """
    answer = call(
        client, settings, APP, "POST", f"projects/{segment(project_id)}/export",
        params={"format": fmt}, timeout_seconds=ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip
    return dict(answer) if isinstance(answer, dict) else {}


def read_export(
    client: httpx.Client, settings: Settings, project_id: str, fmt: str
) -> tuple[str, str]:
    """``GET /projects/{id}/export``: the rendered document, written nowhere.

    Returns:
        ``(media type, text)`` as IdeaPress served them.

    Raises:
        AppRefused: ``EXPORT_FAILED``, or another refusal.
        AppUnreachable: It did not answer.
    """
    return fetch_text(
        client, settings, APP, f"projects/{segment(project_id)}/export",
        params={"format": fmt}, timeout_seconds=ACTION_TIMEOUT_SECONDS,
    )  # fmt: skip


WORKFLOW_FIELDS: Final[tuple[str, ...]] = ("prompt_id", "max_revision_rounds", "model_hint")
"""What the editor may set on a stage beside its kind (ADR-0143 §5). Read from the form as
``prompt_id.<kind>`` and so on, because one HTML form carries every stage's fields at once."""


def workflow_body(
    *, workflow_id: str, title: str, kinds: Sequence[str], fields: Mapping[str, str]
) -> dict[str, Any]:
    """The editor's form as IdeaPress's ``POST``/``PUT /workflows`` body.

    Args:
        workflow_id: The id typed (a new workflow) or the one the page is editing.
        title: The one-line title.
        kinds: The stage kinds ticked, in the order the form listed them — which is IdeaPress's
            own ordinal order, since the form is generated from its ``vocabulary``.
        fields: Every other input, keyed ``"<field>.<kind>"``. A blank value is no value.

    Returns:
        The body. The console checks only what HTML cannot express — a round that is not a whole
        number — and leaves every workflow rule to IdeaPress, which refuses with the field's own
        path (ADR-0143 §3) and whose refusal this page renders verbatim.

    Raises:
        IdeaPressFormInvalid: A revision bound that is not a whole number; nothing was sent.
    """
    stages: list[dict[str, Any]] = []
    for kind in kinds:
        stage: dict[str, Any] = {"kind": kind}
        for field in WORKFLOW_FIELDS:
            raw = (fields.get(f"{field}.{kind}") or "").strip()
            if not raw:
                continue
            if field == "max_revision_rounds":
                stage[field] = _whole("A revision bound", f"{field}.{kind}", raw)
            else:
                stage[field] = raw
        stages.append(stage)
    return {"id": workflow_id.strip(), "title": title.strip(), "stages": stages}


def save_workflow(
    client: httpx.Client, settings: Settings, body: dict[str, Any], *, workflow_id: str | None
) -> dict[str, Any]:
    """Store a workflow: a new one, or the next version of ``workflow_id``.

    Args:
        client, settings: The shared client and this console's settings.
        body: :func:`workflow_body`'s document.
        workflow_id: The workflow being saved, or ``None`` to create the one ``body`` names.

    Returns:
        The stored definition, carrying the version IdeaPress gave it.

    Raises:
        AppRefused: IdeaPress refused the document, naming the field in its details, or refused to
            create an id that already exists. Nothing was stored.
        AppUnreachable: It did not answer.
    """
    if workflow_id is None:
        answer = call(client, settings, APP, "POST", "workflows", body=body)
    else:
        answer = call(client, settings, APP, "PUT", f"workflows/{segment(workflow_id)}", body=body)
    return dict(answer) if isinstance(answer, dict) else {}

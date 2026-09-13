"""weightroom.web.routes.prompts — each application's prompt pack and its overrides (api.md §4).

Every write is one audit row, success or refusal (spec §11 contract 2): ``prompt.override`` for a
written override, ``prompt.delete`` for a removed one. What the application does with an override
is its own rule, and every page here shows it (``services/prompts.PROMPT_SURFACES``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Annotated, Any

from baseaicore import SuiteError
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from weightroom.services.apps import require_app
from weightroom.services.audit import record
from weightroom.services.prompts import (
    PromptDetail,
    PromptOverrideInvalid,
    canonical_text,
    delete_override,
    list_pack,
    prompt_detail,
    surface_for,
    write_override,
)
from weightroom.web.routes.apps import render_shell_page
from weightroom.web.session import CurrentOperator, now_of

if TYPE_CHECKING:
    from pathlib import Path

    from weightroom.services.auth import Principal

__all__ = ["router", "ui_router"]

router = APIRouter(tags=["prompts"])
ui_router = APIRouter(tags=["ui"], include_in_schema=False)


class OverrideBody(BaseModel):
    """``PUT /apps/{app}/prompts/{id}`` (api.md §4): the whole record."""

    model_config = ConfigDict(extra="forbid")

    record: dict[str, Any]


def _audit(
    request: Request,
    principal: Principal,
    action: str,
    app: str,
    prompt_id: str,
    *,
    outcome: str,
    params: dict[str, Any] | None = None,
    message: str | None = None,
) -> None:
    record(
        request.app.state.database,
        action=action,
        actor="operator",
        outcome=outcome,
        now=now_of(request),
        operator_id=principal.operator_id,
        app=app,
        target=prompt_id,
        params=params or {},
        message=message,
        request_id=getattr(request.state, "request_id", None),
    )


def _write(
    request: Request, principal: Principal, app: str, prompt_id: str, body: dict[str, Any]
) -> PromptDetail:
    try:
        detail = write_override(request.app.state.settings, require_app(app), prompt_id, body)
    except SuiteError as exc:
        _audit(
            request, principal, "prompt.override", app, prompt_id, outcome="refused",
            message=exc.message,
        )  # fmt: skip
        raise
    _audit(
        request,
        principal,
        "prompt.override",
        app,
        prompt_id,
        outcome="ok",
        params={
            "path": str(detail.override_path),
            "version": (detail.override or {}).get("version"),
            "sha256": detail.override_sha256,
        },
    )
    return detail


def _delete(request: Request, principal: Principal, app: str, prompt_id: str) -> Path:
    try:
        path = delete_override(require_app(app), prompt_id)
    except SuiteError as exc:
        _audit(
            request, principal, "prompt.delete", app, prompt_id, outcome="refused",
            message=exc.message,
        )  # fmt: skip
        raise
    _audit(
        request, principal, "prompt.delete", app, prompt_id, outcome="ok",
        params={"path": str(path)},
    )  # fmt: skip
    return path


# --- API ------------------------------------------------------------------------------------------


@router.get("/apps/{app}/prompts", summary="An application's prompt pack and its overrides")
def get_pack(request: Request, principal: CurrentOperator, app: str) -> JSONResponse:
    """The shipped pack (``prompt_id``, version, sha256) joined with the overrides on disk."""
    return JSONResponse(content=list_pack(request.app.state.settings, require_app(app)).as_json())


@router.get("/apps/{app}/prompts/{prompt_id}", summary="One prompt: shipped, override, diff")
def get_prompt(
    request: Request, principal: CurrentOperator, app: str, prompt_id: str
) -> JSONResponse:
    """The shipped record, the override if any, and a unified diff between them."""
    detail = prompt_detail(request.app.state.settings, require_app(app), prompt_id)
    return JSONResponse(content=detail.as_json())


@router.put("/apps/{app}/prompts/{prompt_id}", summary="Write an override record")
def put_prompt(
    request: Request,
    principal: CurrentOperator,
    app: str,
    prompt_id: str,
    body: OverrideBody,
) -> JSONResponse:
    """Validated against the record schema first; says where it went and how runs are marked."""
    detail = _write(request, principal, app, prompt_id, body.record)
    return JSONResponse(
        content={
            **detail.as_json(),
            "written": str(detail.override_path),
            "marked": "user_override",
        }
    )


@router.delete("/apps/{app}/prompts/{prompt_id}/override", summary="Remove an override")
def delete_prompt_override(
    request: Request, principal: CurrentOperator, app: str, prompt_id: str
) -> JSONResponse:
    """The shipped record is what the application renders again."""
    path = _delete(request, principal, app, prompt_id)
    return JSONResponse(
        content={
            "app": app,
            "prompt_id": prompt_id,
            "deleted": str(path),
            "rule": surface_for(app).rule,
        }
    )


# --- Pages ----------------------------------------------------------------------------------------


def _page(
    request: Request, principal: Principal, app: str, template: str, /, **context: Any
) -> HTMLResponse:
    from weightroom.web.rendering import app_side_nav, app_side_nav_stubs

    return render_shell_page(
        request,
        template,
        page="apps",
        principal=principal,
        app=app,
        active_app=app,
        nav_sections=app_side_nav(app, selected="Prompts"),
        side_nav_stubs=app_side_nav_stubs(app),
        **context,
    )


@ui_router.get("/apps/{app}/prompts", summary="The Prompts page", response_class=HTMLResponse)
def pack_page(request: Request, principal: CurrentOperator, app: str) -> HTMLResponse:
    """The shipped pack, which prompts are overridden, and the application's rule."""
    name = require_app(app)
    try:
        pack, error = list_pack(request.app.state.settings, name), None
    except SuiteError as exc:
        pack, error = None, exc
    return _page(request, principal, name, "prompts.html", pack=pack, error=error)


def _named_fields(text: str) -> dict[str, Any]:
    """The three fields the editor names, read off the record it is showing (row WX8).

    ``version``, ``metadata.change_reason`` and ``template`` are what an operator actually edits;
    everything else stays in the JSON box beside them. Read defensively: the text is whatever is
    in the editor, including a record that does not parse after a refusal, and a page that cannot
    fill its three inputs still has to render.

    Args:
        text: The record as the editor holds it.

    Returns:
        ``{"version", "change_reason", "template", "variables"}`` — strings, and the declared
        variable names for the template's hint. Blank for anything the record does not hold.
    """
    try:
        parsed: Any = json.loads(text)
    except ValueError:
        parsed = None
    body: Mapping[str, Any] = parsed if isinstance(parsed, dict) else {}
    metadata = body.get("metadata")
    variables = body.get("variables")
    return {
        "version": str(body.get("version") or ""),
        "change_reason": str(
            (metadata or {}).get("change_reason") or "" if isinstance(metadata, dict) else ""
        ),
        "template": str(body.get("template") or ""),
        "variables": sorted(variables) if isinstance(variables, dict) else [],
    }


def _patched(body: dict[str, Any], fields: Mapping[str, str]) -> dict[str, Any]:
    """``body`` with the editor's named fields written into it (row WX8).

    The named inputs win over the JSON box, because they are the ones a reader is looking at; a
    **blank** one is "not given" and leaves the record's own value, so the box stays the way to
    clear a key. Nothing is validated here — the loader the application runs does that, over the
    patched record, exactly as it did over the hand-typed one.

    Args:
        body: The record as posted in the JSON box.
        fields: The form's ``version``, ``change_reason`` and ``template``.

    Returns:
        A new record; ``body`` is not mutated.
    """
    patched = dict(body)
    if fields.get("version", "").strip():
        patched["version"] = fields["version"].strip()
    if fields.get("template", ""):
        patched["template"] = fields["template"]
    reason = fields.get("change_reason", "").strip()
    if reason:
        metadata = patched.get("metadata")
        patched["metadata"] = {
            **(metadata if isinstance(metadata, dict) else {}),
            "change_reason": reason,
        }
    return patched


def _editor(  # noqa: PLR0913 — the editor's state: its record, a refusal, a notice
    request: Request,
    principal: Principal,
    app: str,
    prompt_id: str,
    *,
    notice: str | None = None,
    error: SuiteError | None = None,
    text: str | None = None,
    fields: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    detail: PromptDetail | None = None
    try:
        detail = prompt_detail(request.app.state.settings, app, prompt_id)
    except SuiteError as exc:
        error = error or exc
    if text is None and detail is not None:
        if detail.override is not None:
            text = canonical_text(detail.override)
        elif detail.has_override_file:
            text = detail.override_path.read_text(encoding="utf-8")
        else:
            text = canonical_text(detail.shipped)
    shown = _named_fields(text or "")
    if fields is not None:
        # A refusal comes back with what the operator typed, not with what is on disk — including
        # the field that caused it. The declared variables stay the record's.
        shown = {**shown, **{key: value for key, value in fields.items() if key != "variables"}}
    return _page(
        request,
        principal,
        app,
        "prompt.html",
        prompt_id=prompt_id,
        detail=detail,
        error=error,
        notice=notice,
        editor_text=text or "",
        fields=shown,
    )


@ui_router.get(
    "/apps/{app}/prompts/{prompt_id}", summary="One prompt's editor", response_class=HTMLResponse
)
def prompt_page(
    request: Request, principal: CurrentOperator, app: str, prompt_id: str
) -> HTMLResponse:
    """The shipped record, the override and its diff, and the editor."""
    return _editor(request, principal, require_app(app), prompt_id)


@ui_router.post("/apps/{app}/prompts/{prompt_id}", summary="Write an override from the editor")
def save_from_page(  # noqa: PLR0913 — the record, and the three fields named beside it
    request: Request,
    principal: CurrentOperator,
    app: str,
    prompt_id: str,
    text: Annotated[str, Form(alias="record")] = "",
    version: Annotated[str, Form()] = "",
    change_reason: Annotated[str, Form()] = "",
    template: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """The editor's whole record, with its three named fields patched in; a refusal comes back in
    the editor with what was typed kept.

    Row WX8 gave the editor named inputs for ``version``, ``metadata.change_reason`` and the
    template body. They are a convenience over the same round trip, not a second way in: the JSON
    box is still what is posted, :func:`_patched` writes the three values into it, and
    :func:`~weightroom.services.prompts.write_override` validates the result with the loader the
    application itself runs. A blank named field leaves the record's own value.
    """
    name = require_app(app)
    fields = {"version": version, "change_reason": change_reason, "template": template}
    problem: str | None
    try:
        parsed: Any = json.loads(text)
    except ValueError as exc:
        parsed, problem = None, str(exc)
    else:
        problem = None if isinstance(parsed, dict) else "it is JSON, but not an object"
    if problem is not None or not isinstance(parsed, dict):
        refusal = PromptOverrideInvalid(
            f"The record is not a JSON object: {problem}.",
            details={"app": name, "prompt_id": prompt_id},
        )
        _audit(
            request, principal, "prompt.override", name, prompt_id, outcome="refused",
            message=refusal.message,
        )  # fmt: skip
        return _editor(request, principal, name, prompt_id, error=refusal, text=text, fields=fields)
    record = _patched(parsed, fields)
    try:
        _write(request, principal, name, prompt_id, record)
    except SuiteError as exc:
        return _editor(
            request,
            principal,
            name,
            prompt_id,
            error=exc,
            text=canonical_text(record),
            fields=fields,
        )
    return _editor(
        request,
        principal,
        name,
        prompt_id,
        notice="Override written; what uses it is marked user_override.",
    )


@ui_router.post(
    "/apps/{app}/prompts/{prompt_id}/delete", summary="Delete an override from the editor"
)
def delete_from_page(
    request: Request, principal: CurrentOperator, app: str, prompt_id: str
) -> HTMLResponse:
    """Remove the override; the shipped record is back."""
    name = require_app(app)
    try:
        _delete(request, principal, name, prompt_id)
    except SuiteError as exc:
        return _editor(request, principal, name, prompt_id, error=exc)
    return _editor(
        request,
        principal,
        name,
        prompt_id,
        notice="Override deleted: the shipped record is what the application renders again.",
    )

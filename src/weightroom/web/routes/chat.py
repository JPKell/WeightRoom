"""weightroom.web.routes.chat — conversations through LoadCoach and PromptCadence (api.md §6).

Handlers resolve the request, call one service, render. The reply itself runs on
:class:`~weightroom.services.chat.ChatRunner`, never in the request: ``POST …/messages`` answers
``202`` and the page's stream carries what happens next. Every state-changing route writes one
audit row (spec §11 contract 2); message text and attachment contents are never in it.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal

from fastapi import APIRouter, File, Form, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from weightroom.services.audit import record
from weightroom.services.chat import (
    ChatBackendUnavailable,
    add_attachment,
    backend_unavailable_reason,
    create_conversation,
    delete_conversation,
    events_after,
    get_conversation,
    heartbeat_frame,
    list_conversations,
    run_reply,
    sse_frame,
    start_reply,
)
from weightroom.web.session import CurrentOperator, now_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from weightroom.services.auth import Principal
    from weightroom.services.chat import ConversationView

__all__ = ["router", "ui_router"]

router = APIRouter(tags=["chat"])
ui_router = APIRouter(tags=["ui"], include_in_schema=False)

_HEARTBEAT_SECONDS: Final = 15.0
_POLL_SECONDS: Final = 0.05
_TITLE_FROM_TEXT: Final = 80
"""How much of a first message becomes the conversation's title when none was typed."""


class NewConversation(BaseModel):
    """``POST /chat/conversations`` (api.md §6)."""

    model_config = ConfigDict(extra="forbid")

    backend: str
    title: str = Field(min_length=1, max_length=200)
    task_profile: str | None = None
    model_override: str | None = None
    classification: str | None = None
    tier: str | None = None
    tools: list[str] | None = None


class NewMessage(BaseModel):
    """``POST /chat/conversations/{id}/messages``."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)
    attachment_ids: list[str] = Field(default_factory=list)


def _audit(request: Request, principal: Principal, action: str, target: str, **params: Any) -> str:
    return record(
        request.app.state.database,
        action=action,
        actor="operator",
        outcome="ok",
        now=now_of(request),
        operator_id=principal.operator_id,
        app="weightroom",
        target=target,
        params=params,
        request_id=getattr(request.state, "request_id", None),
    )


def _root(request: Request) -> Path:
    root: Path = request.app.state.attachments_root
    return root


def _availability(request: Request, backend: str) -> str | None:
    from weightroom.web.routes.apps import _view

    return backend_unavailable_reason(backend, _view(request, backend))


def _can_approve(request: Request, backend: str) -> bool | None:
    """Whether approve/deny buttons can work: the console's PromptCadence token's scope."""
    if backend != "promptcadence":
        return None
    from weightroom.services.chat_promptcadence import token_can_approve

    return token_can_approve(request.app.state.settings)


def _tool_choices(request: Request) -> tuple[list[str], str]:
    """The tool names the composer offers, and why it offers none when it offers none.

    PromptCadence's registry is read only when its unit says it can answer, so the page that starts
    a LoadCoach conversation costs no call. Anything it refuses or fails with leaves the allowlist
    as the free-text input it has always been, with PromptCadence's own words under it.
    """
    from baseaicore import SuiteError

    from weightroom.services.chat_promptcadence import registered_tool_names

    reason = _availability(request, "promptcadence")
    if reason is not None:
        return [], reason
    try:
        names = registered_tool_names(request.app.state.http, request.app.state.settings)
    except SuiteError as exc:
        return [], exc.message
    return names, ""


def _send(request: Request, principal: Principal, conversation_id: str, text: str) -> str:
    """Store the message and start the reply; return the assistant message id.

    Raises:
        ChatBackendUnavailable: The backend cannot take a message; nothing is stored.
    """
    state = request.app.state
    conversation = get_conversation(state.database, conversation_id)
    reason = _availability(request, conversation.backend)
    if reason is not None:
        raise ChatBackendUnavailable(
            reason, details={"backend": conversation.backend, "conversation_id": conversation_id}
        )
    _user_id, assistant_id = start_reply(
        state.database, conversation_id=conversation_id, text=text, now=now_of(request)
    )
    clock = getattr(state, "clock", None) or (lambda: datetime.now(UTC))
    state.chat.submit(
        run_reply,
        state.database,
        state.http,
        settings=state.settings,
        conversation_id=conversation_id,
        message_id=assistant_id,
        attachments_root=_root(request),
        clock=clock,
    )
    _audit(
        request,
        principal,
        "chat.message",
        conversation_id,
        backend=conversation.backend,
        message_id=assistant_id,
        characters=len(text),
    )
    return assistant_id


# --- JSON --------------------------------------------------------------------------------


@router.get("/chat/conversations", summary="Conversations")
def api_list(request: Request, principal: CurrentOperator) -> JSONResponse:
    """Most recently active first."""
    return JSONResponse(content={"items": list_conversations(request.app.state.database)})


@router.post(
    "/chat/conversations", status_code=status.HTTP_201_CREATED, summary="Start a conversation"
)
def api_create(request: Request, principal: CurrentOperator, body: NewConversation) -> JSONResponse:
    """``backend`` is ``loadcoach`` or ``promptcadence``; there is no third value."""
    conversation_id = create_conversation(
        request.app.state.database,
        backend=body.backend,
        title=body.title,
        task_profile=body.task_profile,
        model_override=body.model_override,
        classification=body.classification,
        tier=body.tier,
        tools=body.tools,
        now=now_of(request),
    )
    _audit(request, principal, "chat.create", conversation_id, backend=body.backend)
    return JSONResponse(status_code=status.HTTP_201_CREATED, content={"id": conversation_id})


@router.get("/chat/conversations/{conversation_id}", summary="One conversation")
def api_get(request: Request, principal: CurrentOperator, conversation_id: str) -> JSONResponse:
    """The conversation with its messages and their metadata."""
    view = get_conversation(request.app.state.database, conversation_id)
    return JSONResponse(content=view.as_json())


@router.delete("/chat/conversations/{conversation_id}", summary="Delete a conversation")
def api_delete(request: Request, principal: CurrentOperator, conversation_id: str) -> JSONResponse:
    """Messages, events, attachment rows and files go with it; the audit trail stays."""
    delete_conversation(
        request.app.state.database, conversation_id, attachments_root=_root(request)
    )
    _audit(request, principal, "chat.delete", conversation_id)
    return JSONResponse(content={"deleted": conversation_id})


@router.post(
    "/chat/conversations/{conversation_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a message",
)
def api_send(
    request: Request, principal: CurrentOperator, conversation_id: str, body: NewMessage
) -> JSONResponse:
    """``202`` and the reply's id; the reply streams on ``…/stream``.

    ``attachment_ids`` is accepted for api.md's shape; every attachment of the conversation is
    context for every request regardless (``services/chat.py``'s ``_history``).
    """
    message_id = _send(request, principal, conversation_id, body.text)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"message_id": message_id})


@router.post(
    "/chat/conversations/{conversation_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    summary="Attach a text or markdown file",
)
def api_attach(
    request: Request,
    principal: CurrentOperator,
    conversation_id: str,
    file: Annotated[UploadFile, File()],
) -> JSONResponse:
    """Text and markdown only, at most ``[chat] max_attachment_bytes``."""
    view = _attach(request, principal, conversation_id, file)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "id": view.id,
            "filename": view.filename,
            "media_type": view.media_type,
            "size_bytes": view.size_bytes,
            "sha256": view.sha256,
        },
    )


def _attach(request: Request, principal: Principal, conversation_id: str, file: UploadFile) -> Any:  # noqa: ANN401 — an AttachmentView
    limit = request.app.state.settings.chat.max_attachment_bytes
    data = file.file.read(limit + 1)
    view = add_attachment(
        request.app.state.database,
        attachments_root=_root(request),
        conversation_id=conversation_id,
        filename=file.filename or "attachment.txt",
        data=data,
        max_bytes=limit,
        now=now_of(request),
    )
    _audit(
        request,
        principal,
        "chat.attachment",
        conversation_id,
        filename=view.filename,
        size_bytes=view.size_bytes,
        sha256=view.sha256,
    )
    return view


async def _frames(request: Request, conversation_id: str, *, after_id: int) -> AsyncIterator[str]:
    database = request.app.state.database
    last = after_id
    next_heartbeat = time.monotonic() + _HEARTBEAT_SECONDS
    while not await request.is_disconnected():
        rows = await asyncio.to_thread(events_after, database, conversation_id, after_id=last)
        for event_id, kind, payload in rows:
            yield sse_frame(event_id, kind, payload)
            last = event_id
            next_heartbeat = time.monotonic() + _HEARTBEAT_SECONDS
        if not rows:
            if time.monotonic() >= next_heartbeat:
                yield heartbeat_frame()
                next_heartbeat = time.monotonic() + _HEARTBEAT_SECONDS
            await asyncio.sleep(_POLL_SECONDS)


@router.get("/chat/conversations/{conversation_id}/stream", summary="The conversation's stream")
async def api_stream(
    request: Request,
    principal: CurrentOperator,
    conversation_id: str,
    last_event_id: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    """SSE of the persisted events, resumed from ``Last-Event-ID`` (api.md §6)."""
    await asyncio.to_thread(get_conversation, request.app.state.database, conversation_id)
    raw = request.headers.get("last-event-id") or last_event_id or "0"
    after = int(raw) if raw.isdigit() else 0
    return StreamingResponse(
        _frames(request, conversation_id, after_id=after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


# --- Pages -------------------------------------------------------------------------------


def _render_thread(
    request: Request, principal: CurrentOperator, view: ConversationView, *, error: str = ""
) -> HTMLResponse:
    from weightroom.web.routes.apps import render_shell_page

    return render_shell_page(
        request,
        "chat_thread.html",
        page="chat",
        principal=principal,
        conversation=view,
        unavailable=_availability(request, view.backend),
        max_attachment_bytes=request.app.state.settings.chat.max_attachment_bytes,
        error=error,
        can_approve=_can_approve(request, view.backend),
    )


@ui_router.get("/chat", summary="Chat", response_class=HTMLResponse)
def chat_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """The conversation rail and the composer that starts one."""
    from weightroom.web.routes.apps import render_shell_page

    settings = request.app.state.settings
    tool_names, tools_unavailable = _tool_choices(request)
    return render_shell_page(
        request,
        "chat.html",
        page="chat",
        principal=principal,
        conversations=list_conversations(request.app.state.database),
        default_task_profile=settings.chat.default_task_profile,
        default_classification=settings.chat.default_classification,
        tool_names=tool_names,
        tools_unavailable=tools_unavailable,
    )


@ui_router.get("/chat/history", summary="Chat history", response_class=HTMLResponse)
def chat_history_page(request: Request, principal: CurrentOperator) -> HTMLResponse:
    """Every conversation, newest first, as a table; a row's title opens its thread."""
    from weightroom.web.routes.apps import render_shell_page

    return render_shell_page(
        request,
        "chat_history.html",
        page="chat",
        principal=principal,
        conversations=list_conversations(request.app.state.database),
    )


def _title_from(text: str) -> str:
    """A conversation's title taken from its first message, the way a person would write one."""
    line = next((one.strip() for one in text.splitlines() if one.strip()), "")
    if len(line) <= _TITLE_FROM_TEXT:
        return line
    return line[: _TITLE_FROM_TEXT - 1].rstrip() + "\u2026"


@ui_router.post("/chat", summary="Start a conversation from the page")
def chat_create_form(
    request: Request,
    principal: CurrentOperator,
    backend: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    text: Annotated[str, Form()] = "",
    task_profile: Annotated[str, Form()] = "",
    model_override: Annotated[str, Form()] = "",
    classification: Annotated[str, Form()] = "",
    tier: Annotated[str, Form()] = "",
    tools: Annotated[str, Form()] = "",
) -> Any:  # noqa: ANN401 — a redirect, or the new thread with the refusal
    """Create the conversation, send the composer's first message if it carried one, show it.

    The composer is one control: a title is optional and taken from the message when blank, because
    a conversation named before it is had is a form, not a chat. An empty ``text`` (the JSON-shaped
    form, and the audit test's) still creates the conversation and sends nothing.
    """
    from baseaicore import SuiteError

    conversation_id = create_conversation(
        request.app.state.database,
        backend=backend,
        title=title.strip() or _title_from(text),
        task_profile=task_profile,
        model_override=model_override,
        classification=classification,
        tier=tier,
        tools=[name.strip() for name in tools.split(",") if name.strip()],
        now=now_of(request),
    )
    _audit(request, principal, "chat.create", conversation_id, backend=backend)
    if text.strip():
        try:
            _send(request, principal, conversation_id, text)
        except SuiteError as exc:
            if exc.code == "NOT_FOUND":
                raise
            view = get_conversation(request.app.state.database, conversation_id)
            return _render_thread(request, principal, view, error=exc.message)
    return RedirectResponse(f"/chat/{conversation_id}", status_code=status.HTTP_303_SEE_OTHER)


@ui_router.get("/chat/{conversation_id}", summary="A conversation", response_class=HTMLResponse)
def thread_page(request: Request, principal: CurrentOperator, conversation_id: str) -> HTMLResponse:
    """The thread: finished messages rendered here, a streaming one filled by the page's stream."""
    return _render_thread(
        request, principal, get_conversation(request.app.state.database, conversation_id)
    )


@ui_router.post("/chat/{conversation_id}/messages", summary="Send from the page")
def send_form(
    request: Request,
    principal: CurrentOperator,
    conversation_id: str,
    text: Annotated[str, Form()] = "",
) -> Any:  # noqa: ANN401 — a redirect, or the thread with the refusal
    """Send, then show the thread with the reply streaming."""
    from baseaicore import SuiteError

    try:
        _send(request, principal, conversation_id, text)
    except SuiteError as exc:
        if exc.code == "NOT_FOUND":
            raise
        view = get_conversation(request.app.state.database, conversation_id)
        return _render_thread(request, principal, view, error=exc.message)
    return RedirectResponse(f"/chat/{conversation_id}", status_code=status.HTTP_303_SEE_OTHER)


@ui_router.post("/chat/{conversation_id}/attachments", summary="Attach from the page")
def attach_form(
    request: Request,
    principal: CurrentOperator,
    conversation_id: str,
    file: Annotated[UploadFile, File()],
) -> Any:  # noqa: ANN401
    """Attach, then back to the thread; a refused file is named with the reason."""
    from baseaicore import SuiteError

    try:
        _attach(request, principal, conversation_id, file)
    except SuiteError as exc:
        if exc.code == "NOT_FOUND":
            raise
        view = get_conversation(request.app.state.database, conversation_id)
        return _render_thread(request, principal, view, error=exc.message)
    return RedirectResponse(f"/chat/{conversation_id}", status_code=status.HTTP_303_SEE_OTHER)


@ui_router.post("/chat/{conversation_id}/delete", summary="Delete from the page")
def delete_form(
    request: Request, principal: CurrentOperator, conversation_id: str
) -> RedirectResponse:
    """Delete, then back to the list."""
    delete_conversation(
        request.app.state.database, conversation_id, attachments_root=_root(request)
    )
    _audit(request, principal, "chat.delete", conversation_id)
    return RedirectResponse("/chat", status_code=status.HTTP_303_SEE_OTHER)


@ui_router.get(
    "/chat/{conversation_id}/messages/{message_id}",
    summary="One message, rendered",
    response_class=HTMLResponse,
)
def message_fragment(
    request: Request, principal: CurrentOperator, conversation_id: str, message_id: str
) -> HTMLResponse:
    """The finished message as server-rendered HTML, swapped in by the page on ``done``."""
    from weightroom.services.chat import ConversationNotFound
    from weightroom.web.csrf import render_form_page

    view = get_conversation(request.app.state.database, conversation_id)
    message = next((one for one in view.messages if one.id == message_id), None)
    if message is None:
        raise ConversationNotFound(f"No message {message_id!r}.", details={"id": message_id})
    return render_form_page(
        request,
        "_chat_message.html",
        message=message,
        conversation=view,
        can_approve=_can_approve(request, view.backend),
    )


# --- Approvals ------------------------------------------------------------------------------------


class ApprovalBody(BaseModel):
    """``POST /chat/conversations/{id}/approvals/{approval_id}`` (api.md §6)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "deny"]
    reason: str | None = Field(default=None, max_length=2000)


def _decide(
    request: Request,
    principal: Principal,
    conversation_id: str,
    approval_id: str,
    decision: str,
    reason: str | None,
) -> dict[str, Any]:
    """Resolve one approval and write its one audit row, refused or not.

    Raises:
        SuiteError: The service's refusal, after its row is written.
    """
    from baseaicore import SuiteError

    from weightroom.services.chat import decide_approval

    state = request.app.state
    action = "chat.approve" if decision == "approve" else "chat.deny"
    try:
        result = decide_approval(
            state.database,
            state.http,
            settings=state.settings,
            conversation_id=conversation_id,
            approval_request_id=approval_id,
            decision=decision,
            reason=reason,
        )
    except SuiteError as exc:
        record(
            state.database,
            action=action,
            actor="operator",
            outcome="refused",
            now=now_of(request),
            operator_id=principal.operator_id,
            app="promptcadence",
            target=approval_id,
            params={"conversation_id": conversation_id},
            message=exc.message,
            security=True,
            request_id=getattr(request.state, "request_id", None),
        )
        raise
    record(
        state.database,
        action=action,
        actor="operator",
        outcome="ok",
        now=now_of(request),
        operator_id=principal.operator_id,
        app="promptcadence",
        target=approval_id,
        params={
            "conversation_id": conversation_id,
            "trajectory_id": result.get("trajectory_id"),
            "state": result.get("state"),
        },
        security=True,
        request_id=getattr(request.state, "request_id", None),
    )
    return result


@router.post(
    "/chat/conversations/{conversation_id}/approvals/{approval_id}",
    summary="Approve or deny a pending PromptCadence approval",
)
def api_decide(
    request: Request,
    principal: CurrentOperator,
    conversation_id: str,
    approval_id: str,
    body: ApprovalBody,
) -> JSONResponse:
    """PromptCadence's ``approve``/``deny`` with the ``approve``-scoped token (ADR-0049)."""
    result = _decide(request, principal, conversation_id, approval_id, body.decision, body.reason)
    return JSONResponse(content=result)


@ui_router.post("/chat/{conversation_id}/approvals/{approval_id}", summary="Decide from the page")
def decide_form(
    request: Request,
    principal: CurrentOperator,
    conversation_id: str,
    approval_id: str,
    decision: Annotated[Literal["approve", "deny"], Form()],
    reason: Annotated[str, Form()] = "",
) -> Any:  # noqa: ANN401 — a redirect, or the thread with the refusal
    """Approve or deny, then back to the thread; a refusal is shown in PromptCadence's words."""
    from baseaicore import SuiteError

    try:
        _decide(request, principal, conversation_id, approval_id, decision, reason or None)
    except SuiteError as exc:
        if exc.code == "NOT_FOUND" and "conversation" not in exc.message.lower():
            raise
        view = get_conversation(request.app.state.database, conversation_id)
        return _render_thread(request, principal, view, error=exc.message)
    return RedirectResponse(f"/chat/{conversation_id}", status_code=status.HTTP_303_SEE_OTHER)

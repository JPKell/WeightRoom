"""Chat through PromptCadence, over the reference machine's recorded trajectories.

``promptcadence-1.3.3-completed.sse`` and its turns are a real trajectory from the reference machine
(plan drafted and approved, one step, one LoadCoach turn on gpt-oss:20b, completed);
``promptcadence-1.3.3-failed-unauthorized.sse`` is the real failure every trajectory hit before
PromptCadence had a LoadCoach token (found at W6). Both replay through respx.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select

from tests.support import (
    CHAT_FIXTURES,
    JSON_HEADERS,
    RECORDED_TRAJECTORY,
    Console,
    build_console,
    mock_promptcadence,
    promptcadence_token_cli,
)
from weightroom.infrastructure.db.models import AuditLog, Message, MessageEvent
from weightroom.services import chat_promptcadence
from weightroom.services.chat import create_conversation
from weightroom.services.processes import FakeSystemdController


@pytest.fixture(autouse=True)
def _fresh_scope_cache() -> None:
    chat_promptcadence._SCOPE_CACHE.clear()


def _console(
    tmp_path: Path,
    *,
    running: bool = True,
    scopes: list[str] | None = None,
    token: str = "pc_tok",  # noqa: S107 — a test token
) -> Console:
    executable = promptcadence_token_cli(tmp_path, scopes=scopes or ["admin", "approve"])
    token_file = tmp_path / "promptcadence.token"
    token_file.write_text(token + "\n")
    console = build_console(
        tmp_path / "console",
        extra_toml=(
            f'[apps.promptcadence]\nexecutable = "{executable}"\napi_key_file = "{token_file}"\n'
        ),
        systemd=FakeSystemdController(
            states={"promptcadence.service": "active" if running else "inactive"}
        ),
    )
    console.login()
    return console


def _state(console: Console) -> Any:  # noqa: ANN401
    return cast(Any, console.client.app).state


def _new(console: Console, **fields: Any) -> str:
    body = {"backend": "promptcadence", "title": "sky", "classification": "internal", **fields}
    response = console.client.post("/api/v1/chat/conversations", json=body, headers=JSON_HEADERS)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _send(console: Console, conversation_id: str, text: str = "Why is the sky blue?") -> Any:  # noqa: ANN401
    response = console.client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"text": text},
        headers=JSON_HEADERS,
    )
    _state(console).chat.join()
    return response


def _conversation(console: Console, conversation_id: str) -> dict[str, Any]:
    body = console.client.get(f"/api/v1/chat/conversations/{conversation_id}").json()
    return cast(dict[str, Any], body)


def test_a_recorded_trajectory_becomes_cards_an_answer_and_a_decision_line(
    tmp_path: Path, respx_mock: Any
) -> None:
    turns = json.loads((CHAT_FIXTURES / "promptcadence-1.3.3-completed-turns.json").read_text())
    answer = [t for t in turns["items"] if t["role"] == "assistant"][-1]["content"]
    console = _console(tmp_path)
    mock_promptcadence(respx_mock)
    conversation_id = _new(console)
    assert _send(console, conversation_id).status_code == 202

    body = _conversation(console, conversation_id)
    reply = body["messages"][-1]
    assert reply["text"] == answer
    assert reply["thinking"] is None  # PromptCadence streams no reasoning: no block
    assert reply["remote_job_id"] == RECORDED_TRAJECTORY
    assert body["remote_trajectory_id"] == RECORDED_TRAJECTORY
    kinds = [card["kind"] for card in reply["cards"]]
    assert "plan" in kinds and "step" in kinds
    events = {card["event"] for card in reply["cards"]}
    assert {"plan.drafted", "plan.approved", "step.started", "step.completed"} <= events
    routing = reply["routing"]
    assert routing["model"] == "ollama/gpt-oss:20b@sha256:17052f91a42e"
    assert routing["tier"] == "local_fast"
    assert routing["is_remote"] is False
    assert routing["candidates"] == 5  # LoadCoach's own explanation for the turn's job
    assert reply["usage"]["input_tokens"] == 130


def test_the_submission_always_names_its_tool_allowlist(tmp_path: Path, respx_mock: Any) -> None:
    """An omitted `tools` is every configured tool to PromptCadence; blank must mean none."""
    console = _console(tmp_path)
    routes = mock_promptcadence(respx_mock)
    blank = _new(console)
    _send(console, blank, "hello")
    assert json.loads(routes["submit"].calls.last.request.content)["tools"] == []
    allowed = _new(console, tools=["read_file"])
    _send(console, allowed, "read it")
    body = json.loads(routes["submit"].calls.last.request.content)
    assert body["tools"] == ["read_file"]
    assert body["data_classification"] == "internal"
    assert routes["submit"].calls.last.request.headers["authorization"] == "Bearer pc_tok"


def test_a_follow_up_carries_the_conversation_so_far(tmp_path: Path, respx_mock: Any) -> None:
    console = _console(tmp_path)
    routes = mock_promptcadence(respx_mock)
    conversation_id = _new(console)
    _send(console, conversation_id, "first")
    _send(console, conversation_id, "second")
    task = json.loads(routes["submit"].calls.last.request.content)["task"]
    assert "The conversation so far" in task
    assert "Operator: first" in task
    assert task.endswith("second")


def test_a_recorded_failure_halts_with_promptcadences_own_cause(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    mock_promptcadence(respx_mock, stream="promptcadence-1.3.3-failed-unauthorized.sse")
    conversation_id = _new(console)
    _send(console, conversation_id)
    reply = _conversation(console, conversation_id)["messages"][-1]
    assert reply["finish_reason"] == "error"
    assert "LoadCoach refused /api/v1/generate with UNAUTHORIZED" in reply["halt"]
    assert reply["halt"].endswith("(LOADCOACH_ERROR)")


def test_a_refused_submission_halts_in_promptcadences_words(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    mock_promptcadence(
        respx_mock,
        submit_status=422,
        submit_error={"error": {"code": "TOOL_NOT_FOUND", "message": "no tool named rm"}},
    )
    conversation_id = _new(console, tools=["rm"])
    _send(console, conversation_id)
    reply = _conversation(console, conversation_id)["messages"][-1]
    assert reply["halt"] == "PromptCadence refused: no tool named rm (TOOL_NOT_FOUND)"


def test_recorded_egress_decisions_become_cards(tmp_path: Path, respx_mock: Any) -> None:
    decision = {
        "schema": "governance.egress_decision",
        "payload": {"verdict": "approved", "target": "local_fast", "source_ref": "turn:1"},
    }
    console = _console(tmp_path)
    mock_promptcadence(respx_mock, egress=[decision])
    conversation_id = _new(console)
    _send(console, conversation_id)
    cards = _conversation(console, conversation_id)["messages"][-1]["cards"]
    egress = [card for card in cards if card["kind"] == "egress_decision"]
    assert egress and egress[0]["verdict"] == "approved"


def test_a_stopped_promptcadence_disables_sending_and_old_conversations_still_read(
    tmp_path: Path,
) -> None:
    """Plan Phase 6 criterion 3, the PromptCadence half."""
    console = _console(tmp_path, running=False)
    conversation_id = _new(console)
    response = _send(console, conversation_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHAT_BACKEND_UNAVAILABLE"
    page = console.client.get(f"/chat/{conversation_id}", headers={"Accept": "text/html"}).text
    assert "Sending is off" in page


# --- Approvals ------------------------------------------------------------------------------------


def _pending(console: Console) -> tuple[str, str]:
    """A reply parked on an approval request, as the stream leaves it."""
    conversation_id = create_conversation(
        console.database, backend="promptcadence", title="t", now=console.now
    )
    with console.database.write() as session:
        message = Message(
            conversation_id=conversation_id,
            sequence=1,
            role="assistant",
            text="",
            remote_job_id=RECORDED_TRAJECTORY,
        )
        session.add(message)
        session.flush()
        session.add(
            MessageEvent(
                message_id=message.id,
                sequence=1,
                kind="approval_pending",
                payload={
                    "message_id": message.id,
                    "event": "approval.requested",
                    "status": "requested",
                    "approval_request_id": "01APPROVALREQUEST000000001",
                    "step_ids": ["s1"],
                    "reason": "egress_at_or_above_gate",
                },
            )
        )
    return conversation_id, "01APPROVALREQUEST000000001"


def test_a_pending_approval_renders_buttons_and_the_tap_grants_it_with_the_approve_token(
    tmp_path: Path, respx_mock: Any
) -> None:
    """Plan Phase 6 criterion 2's approval half, against the fake host."""
    console = _console(tmp_path, token="pc_approver")
    routes = mock_promptcadence(respx_mock)
    conversation_id, request_id = _pending(console)
    page = console.client.get(f"/chat/{conversation_id}", headers={"Accept": "text/html"}).text
    assert f'action="/chat/{conversation_id}/approvals/{request_id}"' in page
    assert ">Approve</button>" in page

    response = console.client.post(
        f"/api/v1/chat/conversations/{conversation_id}/approvals/{request_id}",
        json={"decision": "approve"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200, response.text
    call = routes["approve"].calls.last.request
    assert call.url.path == f"/api/v1/trajectories/{RECORDED_TRAJECTORY}/approve"
    assert call.headers["authorization"] == "Bearer pc_approver"
    with console.database.read() as session:
        row = session.execute(
            select(AuditLog).where(AuditLog.action == "chat.approve")
        ).scalar_one()
    assert (row.outcome, row.security, row.target) == ("ok", True, request_id)


def test_a_denial_carries_its_reason(tmp_path: Path, respx_mock: Any) -> None:
    console = _console(tmp_path)
    routes = mock_promptcadence(respx_mock)
    conversation_id, request_id = _pending(console)
    response = console.post_form(
        f"/chat/{conversation_id}/approvals/{request_id}",
        {"decision": "deny", "reason": "not this week"},
    )
    assert response.status_code == 303
    assert json.loads(routes["deny"].calls.last.request.content) == {"reason": "not this week"}


def test_a_token_without_the_approve_scope_shows_no_button_that_fails(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path, scopes=["write"])
    routes = mock_promptcadence(respx_mock)
    conversation_id, request_id = _pending(console)
    page = console.client.get(f"/chat/{conversation_id}", headers={"Accept": "text/html"}).text
    assert "No approve scope" in page
    assert ">Approve</button>" not in page
    response = console.client.post(
        f"/api/v1/chat/conversations/{conversation_id}/approvals/{request_id}",
        json={"decision": "approve"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 403
    assert not routes["approve"].called


def test_an_unknown_approval_is_not_found_and_calls_nothing(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    routes = mock_promptcadence(respx_mock)
    conversation_id, _request_id = _pending(console)
    response = console.client.post(
        f"/api/v1/chat/conversations/{conversation_id}/approvals/01NOTAREQUEST0000000000000",
        json={"decision": "approve"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 404
    assert not routes["approve"].called


# --- The composer's tool allowlist (row WX4) ---------------------------------------------------


_TOOLS_REPORT = {
    "tools": [
        {"name": "read_file", "registered": True},
        {"name": "list_dir", "registered": True},
        {"name": "run_command", "registered": False, "withheld_cause": "no sandbox rung"},
    ],
    "isolation": {"tier": "bubblewrap"},
}


def _mock_tools(respx_mock: Any, report: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
    import httpx

    from tests.support import PROMPTCADENCE_URL

    respx_mock.get(f"{PROMPTCADENCE_URL}/api/v1/version").mock(
        return_value=httpx.Response(
            200, json={"application": "promptcadence", "version": "1.3.3", "api_version": "v1"}
        )
    )
    return respx_mock.get(f"{PROMPTCADENCE_URL}/api/v1/tools").mock(
        return_value=httpx.Response(200, json=report if report is not None else _TOOLS_REPORT)
    )


def test_the_composer_offers_the_registered_tools_and_allow_all_names_every_one(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    _mock_tools(respx_mock)
    page = console.client.get("/chat", headers={"Accept": "text/html"}).text
    assert '<select id="chat-tool-pick">' in page
    assert '<option value="list_dir">list_dir</option>' in page
    assert '<option value="read_file">read_file</option>' in page
    assert "run_command" not in page, "a withheld tool cannot run, so it is not offered"
    # "Allow all" is the snapshot written out by name — never an omitted key, which PromptCadence
    # reads as every configured tool (services/chat_promptcadence.submit_trajectory).
    assert 'data-all="list_dir, read_file"' in page
    assert '<input id="chat-tools" name="tools"' in page


def test_a_promptcadence_that_is_stopped_leaves_the_allowlist_as_free_text(tmp_path: Path) -> None:
    console = _console(tmp_path, running=False)
    page = console.client.get("/chat", headers={"Accept": "text/html"}).text
    assert '<select id="chat-tool-pick">' not in page
    assert "PromptCadence is stopped." in page
    assert '<input id="chat-tools" name="tools"' in page


def test_a_refused_tool_registry_leaves_the_allowlist_as_free_text(
    tmp_path: Path, respx_mock: Any
) -> None:
    import httpx

    from tests.support import PROMPTCADENCE_URL

    console = _console(tmp_path)
    respx_mock.get(f"{PROMPTCADENCE_URL}/api/v1/version").mock(
        return_value=httpx.Response(
            200, json={"application": "promptcadence", "version": "1.3.3", "api_version": "v1"}
        )
    )
    respx_mock.get(f"{PROMPTCADENCE_URL}/api/v1/tools").mock(
        return_value=httpx.Response(403, json={"error": {"code": "FORBIDDEN", "message": "nope"}})
    )
    page = console.client.get("/chat", headers={"Accept": "text/html"}).text
    assert '<select id="chat-tool-pick">' not in page
    assert "nope" in page


def test_a_pending_approval_stays_outside_the_collapsed_details(
    tmp_path: Path, respx_mock: Any
) -> None:
    """A decision nobody has taken is never one click away (row WX4)."""
    console = _console(tmp_path, token="pc_approver")
    mock_promptcadence(respx_mock)
    conversation_id, _request_id = _pending(console)
    page = console.client.get(f"/chat/{conversation_id}", headers={"Accept": "text/html"}).text
    assert '<details class="chat-card chat-card-approval-pending" open>' in page
    assert ">Approve</button>" in page
    if '<details class="chat-details"' in page:
        assert page.index("chat-card-approval-pending") < page.index('class="chat-details"')

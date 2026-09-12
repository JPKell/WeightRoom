"""Chat through LoadCoach, over the reference machine's recorded streams.

The two recordings in ``tests/fixtures/chat`` are real ``POST /generate/stream`` responses from
the reference machine on ``gpt-oss:20b``: one from LoadCoach 1.3.1 (no thinking frames, reasoning
only in ``result``) and one from 1.5.0 (42 live thinking frames, then the answer). They are
replayed through respx, so the whole path — request body, SSE parsing, the state machine,
persistence, coalescing — runs for real against what LoadCoach actually sends.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select

from tests.support import (
    CHAT_FIXTURES,
    JSON_HEADERS,
    Console,
    build_console,
    fake_application,
    mock_loadcoach,
)
from weightroom.domain.chat import ThinkingState
from weightroom.infrastructure.db.models import Message, MessageEvent
from weightroom.services import chat as chat_service
from weightroom.services.chat import (
    create_conversation,
    events_after,
    get_conversation,
    recover_interrupted,
    render_reply,
    sse_frame,
)
from weightroom.services.chat_loadcoach import iter_frames
from weightroom.services.processes import FakeSystemdController

SRC = Path(__file__).resolve().parents[2] / "src" / "weightroom"


def _recording(name: str) -> dict[str, Any]:
    """The routing, thinking, text and result a recording carries, read independently."""
    lines = (CHAT_FIXTURES / name).read_text(encoding="utf-8").splitlines()
    thinking, text, routing, result = [], [], None, None
    for frame in iter_frames(lines):
        payload = frame.data if frame.event == "token" else frame.data.get("payload")
        if frame.event == "thinking":
            thinking.append(payload["delta"])
        elif frame.event == "token":
            text.append(payload["delta"])
        elif frame.event == "routing":
            routing = payload
        elif frame.event == "result":
            result = payload
    return {
        "thinking": "".join(thinking),
        "text": "".join(text),
        "routing": routing,
        "result": result,
    }


def _console(tmp_path: Path, *, running: bool = True, token: str | None = None) -> Console:
    executable, _config, _document = fake_application(tmp_path, "loadcoach")
    extra = f'[apps.loadcoach]\nexecutable = "{executable}"\n'
    if token is not None:
        token_file = tmp_path / "loadcoach.token"
        token_file.write_text(token + "\n")
        extra += f'api_key_file = "{token_file}"\n'
    console = build_console(
        tmp_path / "console",
        extra_toml=extra,
        systemd=FakeSystemdController(
            states={"loadcoach.service": "active" if running else "inactive"}
        ),
    )
    console.login()
    return console


def _state(console: Console) -> Any:  # noqa: ANN401 — the app's state namespace
    return cast(Any, console.client.app).state


def _new(console: Console, **fields: Any) -> str:
    body = {"backend": "loadcoach", "title": "sky", "task_profile": "general.chat", **fields}
    response = console.client.post("/api/v1/chat/conversations", json=body, headers=JSON_HEADERS)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _send(console: Console, conversation_id: str, text: str = "Is 1001 prime?") -> str:
    response = console.client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"text": text},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 202, response.text
    _state(console).chat.join()
    return str(response.json()["message_id"])


def _reply(console: Console, conversation_id: str) -> dict[str, Any]:
    body = console.client.get(f"/api/v1/chat/conversations/{conversation_id}").json()
    return cast(dict[str, Any], body["messages"][-1])


# --- The recorded streams ------------------------------------------------------------------------


def test_a_1_5_0_reply_streams_thinking_and_keeps_it_collapsed_beside_the_answer(
    tmp_path: Path, respx_mock: Any
) -> None:
    recording = _recording("loadcoach-1.5.0-gpt-oss-thinking.sse")
    console = _console(tmp_path)
    mock_loadcoach(respx_mock, stream="loadcoach-1.5.0-gpt-oss-thinking.sse")
    conversation_id = _new(console)
    message_id = _send(console, conversation_id)

    reply = _reply(console, conversation_id)
    assert reply["id"] == message_id
    assert reply["thinking"] == recording["thinking"]
    assert reply["text"] == recording["text"] == recording["result"]["output"]["text"]
    assert reply["finish_reason"] == "stop"
    assert reply["usage"]["input_tokens"] == 80
    assert reply["cost"] is None  # a local model: no money, never a zero
    routing = reply["routing"]
    assert routing["model"] == "ollama/gpt-oss:20b@sha256:17052f91a42e"
    assert routing["candidates"] == len(recording["routing"]["candidates"])
    assert routing["rejected"] == len(recording["routing"]["rejected"])
    assert routing["is_remote"] is False


def test_completion_coalesces_the_deltas_and_keeps_the_structured_rows(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    mock_loadcoach(respx_mock, stream="loadcoach-1.5.0-gpt-oss-thinking.sse")
    conversation_id = _new(console)
    message_id = _send(console, conversation_id)
    with console.database.read() as session:
        kinds = list(
            session.execute(
                select(MessageEvent.kind)
                .where(MessageEvent.message_id == message_id)
                .order_by(MessageEvent.sequence)
            ).scalars()
        )
    assert kinds == ["thinking_done", "done"]


def test_a_1_3_1_reply_with_no_thinking_frames_fills_the_block_from_the_result(
    tmp_path: Path, respx_mock: Any
) -> None:
    """An older LoadCoach drops live thinking; the console still shows it, collapsed."""
    recording = _recording("loadcoach-1.3.1-gpt-oss-general-chat.sse")
    assert recording["thinking"] == ""
    console = _console(tmp_path)
    mock_loadcoach(respx_mock, stream="loadcoach-1.3.1-gpt-oss-general-chat.sse", version="1.3.1")
    conversation_id = _new(console)
    _send(console, conversation_id)
    reply = _reply(console, conversation_id)
    assert reply["thinking"] == recording["result"]["reasoning"]["summary"]
    assert reply["text"] == recording["result"]["output"]["text"]


def test_the_request_carries_the_task_the_history_the_token_and_the_idempotency_key(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path, token="lc_test_token")
    route = mock_loadcoach(respx_mock)
    conversation_id = _new(console, model_override="ollama/gpt-oss:20b@sha256:17052f91a42e")
    first = _send(console, conversation_id, "first question")
    second = _send(console, conversation_id, "second question")

    request = route.calls.last.request
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer lc_test_token"
    assert body["task"] == "general.chat"
    assert body["overrides"] == {"model": "ollama/gpt-oss:20b@sha256:17052f91a42e"}
    assert body["idempotency_key"] == second != first
    roles = [message["role"] for message in body["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert body["messages"][-1]["content"] == "second question"
    assert "prompt" not in body


def test_attachments_are_prepended_to_the_first_user_message_as_fenced_context(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    route = mock_loadcoach(respx_mock)
    conversation_id = _new(console)
    token = console.csrf_token()
    uploaded = console.client.post(
        f"/api/v1/chat/conversations/{conversation_id}/attachments",
        files={"file": ("notes.md", b"# Notes\n~~~~\nnot a fence escape\n", "text/markdown")},
        data={"csrf_token": token},
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert uploaded.status_code == 201, uploaded.text
    _send(console, conversation_id, "summarise the notes")
    content = json.loads(route.calls.last.request.content)["messages"][0]["content"]
    assert content.startswith("Attached file `notes.md`:")
    assert "~~~~~" in content  # a fence longer than the file's own run of tildes
    assert content.endswith("summarise the notes")


# --- Failures -------------------------------------------------------------------------------------


def test_a_stopped_loadcoach_refuses_the_send_by_name_and_old_conversations_still_read(
    tmp_path: Path,
) -> None:
    """Plan Phase 6 criterion 3, the LoadCoach half."""
    console = _console(tmp_path, running=False)
    conversation_id = _new(console)
    response = console.client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"text": "hello"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHAT_BACKEND_UNAVAILABLE"
    assert "stopped" in response.json()["error"]["message"]
    page = console.client.get(f"/chat/{conversation_id}", headers={"Accept": "text/html"})
    assert page.status_code == 200
    assert "Sending is off" in page.text
    assert re.search(r"<button type=\"submit\"\s+disabled", page.text)
    with console.database.read() as session:
        assert session.execute(select(Message)).first() is None  # nothing was stored


def test_an_error_frame_halts_the_reply_with_loadcoachs_own_words(
    tmp_path: Path, respx_mock: Any
) -> None:
    error = {
        "schema": "event.envelope",
        "schema_version": "1.0",
        "payload": {"type": "error", "code": "NO_ELIGIBLE_MODEL", "message": "no model fits"},
    }
    body = f"event: error\ndata: {json.dumps(error)}\n\n"
    console = _console(tmp_path)
    mock_loadcoach(respx_mock, stream=body)
    conversation_id = _new(console)
    _send(console, conversation_id)
    reply = _reply(console, conversation_id)
    assert reply["finish_reason"] == "error"
    assert reply["halt"] == "LoadCoach: no model fits"


def test_a_stream_that_ends_without_a_terminal_frame_is_a_halt_not_a_spinner(
    tmp_path: Path, respx_mock: Any
) -> None:
    body = 'event: token\ndata: {"delta": "partial", "index": 0}\n\n'
    console = _console(tmp_path)
    mock_loadcoach(respx_mock, stream=body)
    conversation_id = _new(console)
    _send(console, conversation_id)
    reply = _reply(console, conversation_id)
    assert reply["finish_reason"] == "error"
    assert "without a result or an error frame" in reply["halt"]
    assert reply["text"] == "partial"
    assert reply["completed_at"] is not None


def test_a_connection_failure_is_a_halt_naming_it(tmp_path: Path, respx_mock: Any) -> None:
    console = _console(tmp_path)
    mock_loadcoach(respx_mock, stream=httpx.ConnectError("connection refused"))
    conversation_id = _new(console)
    _send(console, conversation_id)
    reply = _reply(console, conversation_id)
    assert reply["finish_reason"] == "error"
    assert "LoadCoach did not answer" in reply["halt"]


def test_a_second_message_while_a_reply_streams_is_refused(tmp_path: Path) -> None:
    console = _console(tmp_path)
    conversation_id = create_conversation(
        console.database, backend="loadcoach", title="t", now=console.now
    )
    with console.database.write() as session:
        session.add(Message(conversation_id=conversation_id, sequence=1, role="assistant", text=""))
    response = console.client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        json={"text": "again"},
        headers=JSON_HEADERS,
    )
    assert response.status_code in {400, 409}


def test_a_reply_interrupted_by_a_restart_is_halted_with_what_it_had(tmp_path: Path) -> None:
    console = _console(tmp_path)
    conversation_id = create_conversation(
        console.database, backend="loadcoach", title="t", now=console.now
    )
    with console.database.write() as session:
        message = Message(conversation_id=conversation_id, sequence=1, role="assistant", text="")
        session.add(message)
        session.flush()
        for sequence, (kind, delta) in enumerate(
            [("delta.thinking", "hm"), ("delta.text", "Half an ans")], start=1
        ):
            session.add(
                MessageEvent(
                    message_id=message.id,
                    sequence=sequence,
                    kind=kind,
                    payload={"message_id": message.id, "delta": delta},
                )
            )
    assert recover_interrupted(console.database, now=console.now) == 1
    view = get_conversation(console.database, conversation_id)
    reply = view.messages[-1]
    assert not reply.in_progress
    assert (reply.text, reply.thinking, reply.finish_reason) == ("Half an ans", "hm", "error")
    assert reply.halt_message is not None
    assert "restarted" in reply.halt_message


# --- The page's stream ----------------------------------------------------------------------------


class _Request:
    """Just enough of a Starlette request to drive the route's generator once, deterministically
    (the telemetry stream tests' reason: the stream is unbounded)."""

    def __init__(self, app: Any) -> None:  # noqa: ANN401
        self.app = app
        self.headers: dict[str, str] = {}
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > 1


def test_the_stream_replays_persisted_rows_after_last_event_id(
    tmp_path: Path, respx_mock: Any
) -> None:
    from weightroom.web.routes.chat import _frames

    console = _console(tmp_path)
    mock_loadcoach(respx_mock)
    conversation_id = _new(console)
    _send(console, conversation_id)
    rows = events_after(console.database, conversation_id, after_id=0)
    assert [kind for _id, kind, _payload in rows] == ["thinking_done", "done"]

    async def collect(after: int) -> list[str]:
        request = _Request(console.client.app)
        return [frame async for frame in _frames(request, conversation_id, after_id=after)]  # type: ignore[arg-type]

    everything = "".join(asyncio.run(collect(0)))
    assert "event: done" in everything
    assert "event: thinking_done" in everything
    resumed = "".join(asyncio.run(collect(rows[0][0])))
    assert "event: thinking_done" not in resumed
    assert "event: done" in resumed
    assert sse_frame(7, "done", {"message_id": "x"}).startswith("id: 7\n")


def test_frames_are_yielded_as_they_arrive_not_when_the_stream_ends() -> None:
    """A reply is read frame by frame; buffering it to the end hid live thinking (W6 demo)."""

    def lines() -> Iterator[str]:
        yield "event: thinking"
        yield 'data: {"payload": {"delta": "a"}}'
        yield ""
        message = "iter_frames read past a complete frame before yielding it"
        raise AssertionError(message)

    assert next(iter_frames(lines())).event == "thinking"


def test_a_live_reader_past_the_deltas_still_receives_done(tmp_path: Path) -> None:
    """Dropping the deltas must not let ``done`` reuse an id a live reader was already sent.

    SQLite hands out the highest remaining rowid plus one unless the table says AUTOINCREMENT, so
    ``done`` came back numbered below the text deltas and the open thread never finished (found at
    the W6 demonstration; the replay tests read only after completion and could not see it).
    """
    console = _console(tmp_path)
    conversation_id = create_conversation(
        console.database, backend="loadcoach", title="t", now=console.now
    )
    with console.database.write() as session:
        message = Message(conversation_id=conversation_id, sequence=1, role="assistant", text="")
        session.add(message)
        session.flush()
        message_id = message.id
    body = {"message_id": message_id}
    chat_service._append_event(console.database, message_id, 1, "thinking_done", body, console.now)
    for sequence in (2, 3):
        delta = {**body, "delta": "x"}
        chat_service._append_event(
            console.database, message_id, sequence, "delta.text", delta, console.now
        )
    seen = events_after(console.database, conversation_id, after_id=0)[-1][0]
    chat_service._complete(
        console.database,
        message_id,
        state=ThinkingState(text="xx"),
        routing=None,
        usage=None,
        cost=None,
        finish_reason="stop",
        remote_job_id=None,
        halt=None,
        now=console.now,
    )
    later = events_after(console.database, conversation_id, after_id=seen)
    assert [kind for _id, kind, _payload in later] == ["done"]


# --- Attachments ----------------------------------------------------------------------------------


def _upload(console: Console, conversation_id: str, name: str, data: bytes) -> httpx.Response:
    return cast(
        httpx.Response,
        console.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/attachments",
            files={"file": (name, data, "application/octet-stream")},
            data={"csrf_token": console.csrf_token()},
            headers={"Sec-Fetch-Site": "same-origin"},
        ),
    )


def test_an_attachment_is_stored_under_a_generated_name_with_its_display_name_sanitised(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    conversation_id = _new(console)
    response = _upload(console, conversation_id, "../../etc/notes.md", b"hello")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "notes.md"
    stored = _state(console).attachments_root / conversation_id / body["id"]
    assert stored.read_bytes() == b"hello"
    assert stored.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("report.pdf", b"%PDF-1.7", 415, "ATTACHMENT_TYPE_REFUSED"),
        ("notes.md", b"\xff\xfe\x00binary", 415, "ATTACHMENT_TYPE_REFUSED"),
        ("notes.txt", b"a\x00b", 415, "ATTACHMENT_TYPE_REFUSED"),
        ("big.md", b"x" * (256 * 1024 + 1), 413, "ATTACHMENT_TOO_LARGE"),
    ],
)
def test_an_attachment_that_is_not_small_text_is_refused_by_name(
    tmp_path: Path, name: str, data: bytes, status: int, code: str
) -> None:
    console = _console(tmp_path)
    conversation_id = _new(console)
    response = _upload(console, conversation_id, name, data)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def test_deleting_a_conversation_removes_its_rows_and_files(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    mock_loadcoach(respx_mock)
    conversation_id = _new(console)
    _upload(console, conversation_id, "a.md", b"a")
    _send(console, conversation_id)
    response = console.client.delete(
        f"/api/v1/chat/conversations/{conversation_id}", headers=JSON_HEADERS
    )
    assert response.status_code == 200
    assert not (_state(console).attachments_root / conversation_id).exists()
    with console.database.read() as session:
        assert session.execute(select(Message)).first() is None
        assert session.execute(select(MessageEvent)).first() is None


# --- The page and rendering -----------------------------------------------------------------------


def test_the_thread_page_renders_the_answer_the_collapsed_thinking_and_the_decision_line(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    mock_loadcoach(respx_mock)
    conversation_id = _new(console)
    _send(console, conversation_id)
    page = console.client.get(f"/chat/{conversation_id}", headers={"Accept": "text/html"}).text
    assert '<details class="chat-thinking">' in page  # collapsed: no `open` attribute
    assert "1001 is composite" in page
    assert "candidates" in page
    assert "rejected" in page
    assert "— · local" in page


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        "[click](javascript:alert(1))",
        "![tracker](http://evil.example.net/pixel.png)",
        "<img src=x onerror=alert(1)>",
        "{{ 7 * 7 }}",
        "</td></tr></table><script>alert(1)</script>",
    ],
)
def test_model_text_renders_inert(hostile: str) -> None:
    rendered = str(render_reply(hostile))
    assert "<script" not in rendered
    assert "javascript:" not in rendered
    assert "<img" not in rendered
    assert "onerror=" not in rendered or "&lt;img" in rendered


def test_an_http_link_opens_away_from_the_console() -> None:
    rendered = str(render_reply("[docs](https://example.org/x)"))
    assert 'href="https://example.org/x"' in rendered
    assert 'rel="noopener noreferrer nofollow"' in rendered


def test_no_chat_template_marks_anything_safe() -> None:
    """Spec §14: model text reaches the page only through render_reply's escaped HTML."""
    templates = SRC / "web" / "templates"
    for name in ("chat.html", "chat_thread.html", "_chat_message.html"):
        assert "| safe" not in (templates / name).read_text(encoding="utf-8"), name
        assert "|safe" not in (templates / name).read_text(encoding="utf-8"), name


def test_chat_never_calls_a_provider_directly() -> None:
    """Spec §11 contract 6: ``modelrack.generate`` is never called, by grep."""
    offenders = []
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if re.search(
            r"\.generate\(|\bimport\s+generate\b|from modelrack[\w.]* import .*\bgenerate\b", source
        ):
            offenders.append(str(path.relative_to(SRC)))
    assert offenders == []


# --- The page's shape (row WX4) --------------------------------------------------------------


def test_the_chat_page_rails_the_conversations_and_pins_one_composer(tmp_path: Path) -> None:
    console = _console(tmp_path)
    first = _new(console, title="older")
    second = _new(console, title="newer")
    page = console.client.get("/chat", headers={"Accept": "text/html"}).text
    assert 'class="chat-rail"' in page
    assert f'href="/chat/{first}"' in page and f'href="/chat/{second}"' in page
    newest, oldest = page.index(f'href="/chat/{second}"'), page.index(f'href="/chat/{first}"')
    assert newest < oldest, "newest first"
    assert 'class="chat-composer"' in page
    assert '<select id="chat-backend" name="backend">' in page  # the mode, chosen here
    assert "/app-static/css/chat.css" in page


def test_the_thread_page_marks_the_open_conversation_and_fixes_its_mode(tmp_path: Path) -> None:
    console = _console(tmp_path)
    other = _new(console, title="other")
    conversation_id = _new(console, title="open one")
    page = console.client.get(f"/chat/{conversation_id}", headers={"Accept": "text/html"}).text
    assert f'href="/chat/{conversation_id}" aria-current="page"' in page
    assert f'href="/chat/{other}" aria-current="page"' not in page
    assert '<select id="chat-backend" disabled>' in page  # fixed per conversation
    assert 'name="backend"' not in page, "the thread page never submits a mode"


def test_the_composer_starts_the_conversation_and_sends_its_first_message(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    mock_loadcoach(respx_mock)
    response = console.post_form(
        "/chat",
        {"backend": "loadcoach", "text": "Is 1001 prime?\nsecond line", "task_profile": "general"},
    )
    assert response.status_code == 303, response.text
    conversation_id = response.headers["location"].rsplit("/", 1)[-1]
    _state(console).chat.join()
    body = console.client.get(f"/api/v1/chat/conversations/{conversation_id}").json()
    assert body["title"] == "Is 1001 prime?", "the title is taken from the first message"
    assert [one["role"] for one in body["messages"]] == ["user", "assistant"]


def test_a_long_first_message_becomes_a_title_that_fits(tmp_path: Path) -> None:
    console = _console(tmp_path)
    response = console.post_form("/chat", {"backend": "loadcoach", "text": "word " * 50})
    conversation_id = response.headers["location"].rsplit("/", 1)[-1]
    title = console.client.get(f"/api/v1/chat/conversations/{conversation_id}").json()["title"]
    assert len(title) == 80 and title.endswith("…")


def test_a_named_title_survives_the_first_message(tmp_path: Path) -> None:
    console = _console(tmp_path)
    response = console.post_form("/chat", {"backend": "loadcoach", "title": "mine", "text": "hi"})
    conversation_id = response.headers["location"].rsplit("/", 1)[-1]
    assert console.client.get(f"/api/v1/chat/conversations/{conversation_id}").json()["title"] == (
        "mine"
    )


def test_every_non_answer_frame_sits_under_one_collapsed_details(
    tmp_path: Path, respx_mock: Any
) -> None:
    console = _console(tmp_path)
    mock_loadcoach(respx_mock)
    conversation_id = _new(console)
    _send(console, conversation_id)
    page = console.client.get(f"/chat/{conversation_id}", headers={"Accept": "text/html"}).text
    assert '<details class="chat-details">' in page, "closed by default: no `open` attribute"
    # Thinking and the routing line are the two frames of a LoadCoach reply, both inside it.
    wrapper = page.index('<details class="chat-details">')
    answer = page.index('<div class="chat-answer">')
    assert wrapper < page.index('<details class="chat-thinking">') < answer
    assert wrapper < page.index('<details class="chat-decision muted">') < answer
    assert "Details · 2 steps" in page

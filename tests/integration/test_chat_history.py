"""Chat history: its own page, off ``/chat`` (row WY7).

``GET /chat/history`` is registered ahead of ``GET /chat/{conversation_id}`` in
``web/routes/chat.py``, so the literal path ``history`` is never read as a conversation id.
"""

from __future__ import annotations

from pathlib import Path

from tests.support import Console, build_console
from weightroom.services.chat import create_conversation


def _console(tmp_path: Path) -> Console:
    console = build_console(tmp_path)
    console.login()
    return console


def test_history_lists_every_conversation_newest_first_linked_to_its_thread(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    first = create_conversation(
        console.database, backend="loadcoach", title="older", now=console.now
    )
    console.advance(seconds=1)
    second = create_conversation(
        console.database, backend="promptcadence", title="newer", now=console.now
    )
    page = console.client.get("/chat/history", headers={"Accept": "text/html"}).text
    assert f'href="/chat/{first}"' in page
    assert f'href="/chat/{second}"' in page
    newest, oldest = page.index(f'href="/chat/{second}"'), page.index(f'href="/chat/{first}"')
    assert newest < oldest, "newest first"
    assert 'data-table="chat-history"' in page


def test_history_shows_the_empty_state_with_no_conversations(tmp_path: Path) -> None:
    console = _console(tmp_path)
    page = console.client.get("/chat/history", headers={"Accept": "text/html"}).text
    assert "Nothing has been asked yet." in page
    assert 'href="/chat"' in page  # the empty state's own link to start one
    assert 'data-table="chat-history"' not in page


def test_the_history_path_is_never_read_as_a_conversation_id(tmp_path: Path) -> None:
    console = _console(tmp_path)
    response = console.client.get("/chat/history", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "<h2>Chat history</h2>" in response.text  # the page itself; no NOT_FOUND refusal


def test_a_conversation_title_in_the_history_table_is_escaped(tmp_path: Path) -> None:
    console = _console(tmp_path)
    create_conversation(
        console.database, backend="loadcoach", title="<script>evil</script>", now=console.now
    )
    page = console.client.get("/chat/history", headers={"Accept": "text/html"}).text
    assert "<script>evil</script>" not in page
    assert "&lt;script&gt;evil&lt;/script&gt;" in page


def test_every_chat_page_bar_offers_a_new_conversation_under_the_selected_chat_entry(
    tmp_path: Path,
) -> None:
    """Row WY10, on the operator's decision: the bar's *New conversation* links ``/chat``, which is
    the left menu's Chat entry — allowed because every chat page now marks that entry selected
    (``console_side_nav``), the one exception `test_page_nav.py` makes (row WY9). WY7 shipped the
    bar without it because the console menu marked nothing selected (WY7_HANDOFF.md).
    """
    console = _console(tmp_path)
    conversation_id = create_conversation(
        console.database, backend="loadcoach", title="one", now=console.now
    )
    for path in ("/chat", "/chat/history", f"/chat/{conversation_id}"):
        page = console.client.get(path, headers={"Accept": "text/html"}).text
        nav = page[
            page.index('class="page-nav"') : page.index("</nav>", page.index('class="page-nav"'))
        ]
        assert '<a href="/chat"' in nav and ">New conversation</a>" in nav, path
        side = page[page.index('class="side-nav"') :]
        assert '<a href="/chat" aria-current="page">Chat</a>' in side, path

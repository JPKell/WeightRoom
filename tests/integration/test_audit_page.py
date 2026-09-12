"""The ``/audit`` page's own pager (row WX5): ``[ui] page_rows`` and a real cursor.

Before this row the page read at most 200 rows in one request with no way to see further back —
the numeric ``Rows`` field only re-asks for more of the same page, up to that fixed cap — and it
silently stopped there. It now defaults to ``[ui] page_rows`` and follows the trail's own
``before_id`` cursor with a ``Next`` link, so every row is reachable.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.support import Console, build_console
from weightroom.services.audit import record

HTML = {"Accept": "text/html"}
_NEXT_HREF = re.compile(r'href="([^"]*)" rel="next"')


def _seed(console: Console, count: int) -> None:
    """``count`` distinguishable ``login`` rows, one second apart."""
    base = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
    for i in range(count):
        record(
            console.database,
            action="login",
            actor="operator",
            outcome="ok",
            now=base + timedelta(seconds=i),
        )


def _next_href(page: str) -> str | None:
    match = _NEXT_HREF.search(page)
    return match.group(1).replace("&amp;", "&") if match else None


def _timestamps(page: str) -> set[str]:
    """Every ``At`` cell's RFC 3339 text — unique per row, one second apart."""
    return set(re.findall(r"<td>(\d{4}-\d{2}-\d{2}T[\d:.]+Z)</td>", page))


def test_page_rows_bounds_the_default_page_and_offers_a_next_link(tmp_path: Path) -> None:
    console = build_console(tmp_path, extra_toml="[ui]\npage_rows = 10\n")
    console.login()
    _seed(console, 12)  # + the login row itself = 13
    page = console.client.get("/audit", headers=HTML).text
    assert '<p class="row-count">10 rows</p>' in page
    assert _next_href(page) is not None


def test_a_page_under_the_size_names_nothing_further(tmp_path: Path) -> None:
    console = build_console(tmp_path)
    console.login()
    _seed(console, 3)
    page = console.client.get("/audit", headers=HTML).text
    assert _next_href(page) is None


def test_the_cursor_walks_every_row_once(tmp_path: Path) -> None:
    console = build_console(tmp_path, extra_toml="[ui]\npage_rows = 10\n")
    console.login()
    _seed(console, 12)  # + the login row itself = 13
    seen: set[str] = set()
    page = console.client.get("/audit", headers=HTML).text
    while True:
        stamps = _timestamps(page)
        assert seen.isdisjoint(stamps), "a later page repeated an earlier row"
        seen |= stamps
        href = _next_href(page)
        if href is None:
            break
        page = console.client.get(href, headers=HTML).text
    assert len(seen) == 13

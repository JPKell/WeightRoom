"""Row WY2: every log view is a 3 × 3 grid; settings tables right-align Value/Source/Applies."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import respx

from tests.integration.test_apps_routes import LOADCOACH_URL, StubJournal
from tests.support import build_console
from weightroom.services.processes import FakeSystemdController
from weightroom.web.rendering import _TEMPLATES_DIR

HTML = {"Accept": "text/html"}

_ROW = re.compile(r'<li class="log-row"[^>]*>(.*?)</li>', re.DOTALL)
_COL = re.compile(r'<div class="log-col ([^"]+)">(.*?)</div>', re.DOTALL)
_P = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)


def _console(tmp_path: Path) -> Any:
    executable = tmp_path / "loadcoach"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    console = build_console(
        tmp_path,
        extra_toml=f'[apps.loadcoach]\nexecutable = "{executable}"\nbase_url = "{LOADCOACH_URL}"\n',
        systemd=FakeSystemdController(states={"loadcoach.service": "active"}),
        journal=StubJournal(),
    )
    console.login()
    return console


def test_a_history_line_is_three_grid_columns_of_three_lines_each(tmp_path: Path) -> None:
    console = _console(tmp_path)
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{LOADCOACH_URL}/api/v1/version").mock(
            return_value=httpx.Response(
                200,
                json={
                    "application": {"name": "loadcoach", "version": "1.5.0"},
                    "api": {"current": "v1"},
                },
            )
        )
        page = console.client.get("/apps/loadcoach/logs", headers=HTML)
    row = _ROW.search(page.text)
    assert row is not None
    cols = _COL.findall(row.group(1))
    assert [name for name, _ in cols] == ["log-col-1", "log-col-2", "log-col-3"]
    # Left: level, date, time. Middle: app, version, pid. Right: message, logger, request id.
    left = [p.strip() for p in _P.findall(cols[0][1])]
    middle = [p.strip() for p in _P.findall(cols[1][1])]
    right = [p.strip() for p in _P.findall(cols[2][1])]
    assert len(left) == len(middle) == len(right) == 3
    assert "info" in left[0]
    assert re.match(r"\d{4}-\d{2}-\d{2}", left[1])
    assert re.match(r"\d{2}:\d{2}:\d{2}", left[2])
    assert middle[0] == "loadcoach"
    assert right[0] == "started"


def test_the_live_pane_script_builds_the_same_three_column_structure() -> None:
    source = (_TEMPLATES_DIR / "_log_pane.html").read_text()
    assert '"log-col log-col-1"' in source
    assert '"log-col log-col-2"' in source
    assert '"log-col log-col-3"' in source
    # Same order as the history: level/date/time, app/version/pid, message/logger/request id.
    first = source.index('"log-col log-col-1"')
    second = source.index('"log-col log-col-2"')
    third = source.index('"log-col log-col-3"')
    assert first < second < third


def test_settings_table_right_aligns_value_source_and_applies_and_stacks_applies() -> None:
    source = (_TEMPLATES_DIR / "settings.html").read_text()
    assert "th:nth-child(2), .settings-table td:nth-child(2)" in source
    assert "text-align: end" in source
    assert "td:nth-child(4)" in source and "flex-direction: column" in source


def test_a_settings_row_with_two_applies_pills_renders_them_stacked(
    tmp_path: Path, respx_mock: Any
) -> None:
    from tests.integration.test_settings_routes import _console as settings_console

    console, _config = settings_console(tmp_path, app="ideapress", running=True)
    console.login()
    respx_mock.get("http://127.0.0.1:8767/api/v1/version").mock(
        return_value=httpx.Response(200, json={"application": "ideapress", "version": "1.5.0"})
    )
    respx_mock.get("http://127.0.0.1:8767/api/v1/settings").mock(
        return_value=httpx.Response(
            200,
            json={
                "settings": {"workflow.max_revision_rounds": 2},
                "definitions": {
                    "workflow.max_revision_rounds": {"stored": 2, "applies": "next_stage"},
                },
            },
        )
    )
    page = console.client.get("/apps/ideapress/settings", headers=HTML).text
    row = re.search(
        r'<tr[^>]*>\s*<th scope="row">\s*<label for="f-workflow-max_revision_rounds">'
        r".*?</tr>",
        page,
        re.DOTALL,
    )
    assert row is not None
    applies_cell = re.search(r"<td>(.*?)</td>\s*</tr>", row.group(0), re.DOTALL)
    assert applies_cell is not None
    # Two things stack in the Applies cell: the "next stage" pill and the "clear" button.
    assert "next stage" in applies_cell.group(1)
    assert 'name="clear"' in applies_cell.group(1)

"""The shell (row W3, design brief §4): app tabs with dots, the telemetry strip, the left menu.

Every operator-facing page renders inside ``_shell.html``; this file proves the structural
claims the brief's artboard makes, not the pixels MirrorWall's own snapshot tests already cover.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from tests.support import (
    FREEWEIGHT_URL,
    LOADCOACH_URL,
    PROMPTCADENCE_URL,
    Console,
    build_console,
    mock_freeweight,
    mock_loadcoach,
    mock_promptcadence,
)
from weightroom.__about__ import __version__
from weightroom.services.processes import FakeSystemdController

STATUS_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "status"


def _status_body(app: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((STATUS_FIXTURES / f"{app}.json").read_text(encoding="utf-8"))
    return body


SHELL_CSS = (
    Path(__file__).resolve().parents[2] / "src/weightroom/web/static/css/weightroom-shell.css"
)
"""The shell's stylesheet, external since row WX3: a rule the shell's structure depends on is
asserted against the file, not against a `<style>` block in the page."""


def _console(tmp_path: Path, **kwargs: object) -> Console:
    return build_console(tmp_path, **kwargs)  # type: ignore[arg-type]


def test_every_page_carries_four_app_tabs_with_status_dots(tmp_path: Path) -> None:
    console = _console(tmp_path)
    console.login()
    for path in ("/", "/apps", "/ollama", "/logs", "/audit", "/trust"):
        page = console.client.get(path, headers={"Accept": "text/html"}).text
        assert page.count('class="app-tab"') == 4, path
        assert page.count("status-dot") >= 4, path
        for name in ("freeweight", "loadcoach", "ideapress", "promptcadence"):
            assert f"/apps/{name}" in page, (path, name)


def test_an_applications_own_tab_is_current_only_on_its_pages(tmp_path: Path) -> None:
    console = _console(
        tmp_path, systemd=FakeSystemdController(states={"loadcoach.service": "active"})
    )
    console.login()
    on_its_page = console.client.get("/apps/loadcoach", headers={"Accept": "text/html"}).text
    elsewhere = console.client.get("/apps", headers={"Accept": "text/html"}).text
    # On an element, not in the stylesheet — the shell's CSS names the same attribute selector.
    current = re.compile(r"<a [^>]*aria-current=\"page\"")
    assert current.search(on_its_page)
    assert not current.search(elsewhere)


def test_the_telemetry_strip_is_on_every_page_with_the_stream_url(tmp_path: Path) -> None:
    console = _console(tmp_path)
    console.login()
    page = console.client.get("/", headers={"Accept": "text/html"}).text
    assert 'data-telemetry-url="/api/v1/system/telemetry/stream"' in page
    assert "RESIDENT" in page
    assert "QUEUE" in page
    # The two WeightRoomGym-specific meters refresh live off the same stream telemetry.js uses
    # for the generic fields (meter() has no live hook of its own to wire them through).
    assert 'meterValue("RESIDENT")' in page
    assert 'meterValue("QUEUE")' in page


def test_the_strip_loads_the_modules_that_move_it(tmp_path: Path) -> None:
    """A bar whose values never change is a bar that measures nothing (design brief §4).

    MirrorWall's base template loads neither `sse.js` nor `telemetry.js` — they are opt-in per
    application — so a console that shows the strip and omits them renders four em dashes and
    keeps them forever, which is what W3 shipped.
    """
    console = _console(tmp_path)
    console.login()
    page = console.client.get("/", headers={"Accept": "text/html"}).text
    assert "js/sse.js" in page
    assert "js/telemetry.js" in page
    # One EventSource per tab: RESIDENT and QUEUE read telemetry.js's re-dispatched frame.
    assert 'addEventListener("mw:telemetry"' in page
    assert "mirrorwallSse.connect(" not in page
    # The strip can be hidden, and a hidden strip opens no stream: the toggle names the bar it
    # controls, and the remembered choice is applied in <head>, before first paint, so telemetry.js
    # never finds a rendered bar to connect.
    assert 'class="icon-button telemetry-toggle" aria-controls="mw-telemetry-bar"' in page
    css = SHELL_CSS.read_text(encoding="utf-8")
    assert ':root[data-telemetry="off"] #mw-telemetry-bar { display: none; }' in css
    assert page.index('localStorage.getItem("weightroom-telemetry")') < page.index("<body")
    # The artboard's inline meters, opted into by name; MirrorWall renders no track without them.
    for group in ("cpu", "ram", "gpu", "vram"):
        assert f'data-meter="{group}"' in page, group


def test_the_console_overview_lists_the_applications_as_a_dense_table(tmp_path: Path) -> None:
    console = _console(tmp_path)
    console.login()
    page = console.client.get("/", headers={"Accept": "text/html"}).text
    assert 'data-table="console-applications"' in page
    assert 'data-density="dense"' in page
    # Linked by the lowercase route, labelled with the display name.
    for name, label in (
        ("freeweight", "FreeWeight"),
        ("loadcoach", "LoadCoach"),
        ("ideapress", "IdeaPress"),
        ("promptcadence", "PromptCadence"),
    ):
        assert f'<a href="/apps/{name}">{label}</a>' in page, name


def test_the_top_bar_keeps_four_things_and_overflows_only_the_tabs(tmp_path: Path) -> None:
    """Row WX3: brand, the four application tabs, the alerts count, the operator menu.

    The console's own pages used to sit here too and to fold into *Menu* below 1080 px, which made
    *which pages exist* a function of the window's width; they are a left-menu section now, so the
    one collapse left is the tabs at 860 px. The widths themselves were swept in headless Chrome.
    """
    console = _console(tmp_path)
    console.login()
    page = console.client.get("/apps/loadcoach", headers={"Accept": "text/html"}).text
    masthead = page[page.index("<header") : page.index("</header>")]
    assert '<h1><a class="brand" href="/">WeightRoom</a></h1>' in masthead
    assert 'class="version"' not in page  # no version in the header
    assert f"WeightRoom {__version__}" in page[page.index('class="dropdown user-menu"') :]
    assert page.count('class="app-tab"') == 4  # the inline tabs; Menu's copies are plain links
    assert 'class="console-alerts" href="/alerts"' in masthead
    assert 'class="dropdown user-menu"' in masthead
    assert 'class="dropdown-group nav-more-apps"' in page
    # The tools are gone from the top bar — and from Menu, which now overflows the tabs alone.
    assert 'class="console-pages"' not in page
    assert "nav-more-console" not in page
    assert '<a href="/docs">Docs</a>' not in masthead
    assert re.search(r'<a href="/apps/loadcoach" aria-current="page">.*?LoadCoach</a>', page, re.S)
    # One theme control, inside the operator menu, so theme.js has exactly one select to bind.
    assert page.count("data-theme-select") == 1
    assert page.index("data-theme-select") > page.index('class="dropdown user-menu"')
    css = SHELL_CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 860px) {" in css
    assert "@media (max-width: 1080px) {" in css


def test_only_the_consoles_own_pages_list_the_console_and_the_tools(tmp_path: Path) -> None:
    """Row WX3 put Console and Tools under every menu; row WY1 reversed that on the operator's
    instruction. An application's tab and the docs viewer list only their own subject — the brand
    links home and Chat is in the top bar, so neither is a dead end.
    """
    console = _console(tmp_path)
    console.login()
    for path, listed in (
        ("/", True),
        ("/llamacpp", True),
        ("/apps/loadcoach", False),
        ("/apps/loadcoach/settings", False),
        ("/docs", False),
        ("/docs/adrs", False),
    ):
        page = console.client.get(path, headers={"Accept": "text/html"}).text
        side = page[page.index('class="shell-side"') : page.index('class="shell-main"')]
        assert ('<p class="side-nav-title">Console</p>' in side) is listed, path
        assert ('<p class="side-nav-title">Tools</p>' in side) is listed, path
        for href, label in (
            ("/ollama", "Ollama"),
            ("/llamacpp", "llama.cpp"),
            ("/doctor", "Doctor"),
            ("/docs", "Docs"),
            ("/jobs", "Jobs"),
            ("/backups", "Backups"),
            ("/chat", "Chat"),
        ):
            assert (f'<a href="{href}">{label}</a>' in side) is listed, (path, href)


def test_chat_is_in_the_top_bar_and_current_on_its_own_pages(tmp_path: Path) -> None:
    """Row WY1: Chat in the top bar, before the alerts count, as well as in the Tools section."""
    console = _console(tmp_path)
    console.login()
    for path, current in (("/apps/loadcoach", False), ("/", False), ("/chat", True)):
        page = console.client.get(path, headers={"Accept": "text/html"}).text
        masthead = page[page.index("<header") : page.index("</header>")]
        link = '<a class="console-chat" href="/chat"'
        assert link in masthead, path
        assert masthead.index(link) < masthead.index('class="console-alerts"'), path
        assert (f'{link} aria-current="page">' in masthead) is current, path


def test_an_applications_side_nav_names_its_built_pages_and_the_unbuilt_ones(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    console.login()
    page = console.client.get("/apps/loadcoach", headers={"Accept": "text/html"}).text
    assert 'aria-label="Sections"' in page  # side_nav's own landmark
    assert "Overview" in page
    # Built at W4, so they are links now, not stubs.
    assert 'href="/apps/loadcoach/settings"' in page
    assert 'href="/apps/loadcoach/tokens"' in page
    # Database is built (W7) and Logs (WP1), so links; a page not built yet names the row that
    # builds it; and a page that is still somebody else's says where it lives (W4, until WP2).
    assert 'href="/apps/loadcoach/database"' in page
    assert 'href="/apps/loadcoach/logs"' in page
    assert 'title="coming in phase W7"' not in page
    # Every LoadCoach page is built (row WP2): Providers too, which W4 left to LoadCoach's own page.
    assert 'title="coming in row' not in page
    assert 'href="/apps/loadcoach/routing"' in page
    assert 'href="/apps/loadcoach/providers"' in page
    assert "not yet scheduled" not in page
    assert "ADR-0117" not in page


def test_the_console_pages_are_named_and_inert_until_their_rows_land(tmp_path: Path) -> None:
    console = _console(tmp_path)
    console.login()
    page = console.client.get("/", headers={"Accept": "text/html"}).text
    assert '<a href="/jobs">Jobs</a>' in page  # built at W9
    assert '<a href="/database">Database</a>' in page  # built at W7
    assert 'href="/chat"' in page  # Chat is built (W6)
    # Docs (row W5) is built: a real link, not a stub — tests/integration/test_docs_routes.py
    # proves the page itself; this only guards the top-bar wiring.
    assert '<a href="/docs">Docs</a>' in page
    assert 'title="coming in phase W5"' not in page


def test_every_page_still_carries_the_shell_with_every_application_stopped(
    tmp_path: Path,
) -> None:
    """Plan Phase 3 criterion 3, the shell half: acceptance is 'stopped' with a working start
    button and the console still serving, not silence."""
    executable = tmp_path / "loadcoach"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    console = _console(
        tmp_path,
        systemd=FakeSystemdController(states={"loadcoach.service": "inactive"}),
        extra_toml=f'[apps.loadcoach]\nexecutable = "{executable}"\n',
    )
    console.login()
    for path in ("/", "/apps", "/apps/loadcoach", "/logs", "/audit"):
        response = console.client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 200, path
        assert response.text.count('class="app-tab"') == 4, path
    page = console.client.get("/apps/loadcoach", headers={"Accept": "text/html"}).text
    assert "stopped" in page


def test_only_the_page_header_is_sticky(tmp_path: Path) -> None:
    """A <header> inside page content must not inherit the top bar's sticky rule.

    A bare ``header`` selector pinned every chat message's role line over the top bar (row W6).
    """
    console = _console(tmp_path)
    console.login()
    page = console.client.get("/", headers={"Accept": "text/html"}).text
    assert '<link rel="stylesheet" href="/app-static/css/weightroom-shell.css">' in page
    assert console.client.get("/app-static/css/weightroom-shell.css").status_code == 200
    css = SHELL_CSS.read_text(encoding="utf-8")
    assert "body > header { position: sticky" in css
    assert not re.search(r"(?m)^\s*header \{ position: sticky", css)


def test_the_overview_shows_loadcoach_promptcadence_and_freeweights_live_figures(
    tmp_path: Path, respx_mock: Any
) -> None:
    """Row WY3: the same figures ``_STATUS_FIGURES`` names for the per-application Overview,
    reused on ``/`` — one card row per application, linking to its tab, no database read."""
    mock_loadcoach(respx_mock)
    mock_promptcadence(respx_mock)
    mock_freeweight(respx_mock)
    for app, base_url in (
        ("loadcoach", LOADCOACH_URL),
        ("promptcadence", PROMPTCADENCE_URL),
        ("freeweight", FREEWEIGHT_URL),
    ):
        respx_mock.get(f"{base_url}/api/v1/system/status").mock(
            return_value=httpx.Response(200, json=_status_body(app))
        )
    console = _console(
        tmp_path,
        systemd=FakeSystemdController(
            states={
                "loadcoach.service": "active",
                "promptcadence.service": "active",
                "freeweight.service": "active",
            }
        ),
    )
    console.login()
    page = console.client.get("/", headers={"Accept": "text/html"}).text
    for label, value in (
        ("Active", "0"),
        ("Starving", "0"),
        ("Executing", "0"),
        ("Pending approvals", "0"),
        ("Queue depth", "0"),
        ("Disk headroom", "482.0 GiB"),
    ):
        assert f">{label}<" in page and f">{value}<" in page, label
    assert '<a href="/apps/loadcoach">LoadCoach</a>' in page
    assert '<a href="/apps/promptcadence">PromptCadence</a>' in page
    assert '<a href="/apps/freeweight">FreeWeight</a>' in page
    # IdeaPress is out of scope for this row's cards (roadmap §3).
    assert "Active stage runs" not in page


def test_a_stopped_applications_card_dashes_every_figure_with_a_reason(tmp_path: Path) -> None:
    """ADR-0016: unsupported is not zero — a stopped application's card is ``—``, not ``0``, with
    the reason available on hover rather than silently guessed at."""
    executable = tmp_path / "loadcoach"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    console = _console(
        tmp_path,
        systemd=FakeSystemdController(states={"loadcoach.service": "inactive"}),
        extra_toml=f'[apps.loadcoach]\nexecutable = "{executable}"\n',
    )
    console.login()
    page = console.client.get("/", headers={"Accept": "text/html"}).text
    cards = page[page.index("<h2>Overview</h2>") : page.index("<h3>Applications</h3>")]
    group = cards[cards.index(">LoadCoach<") : cards.index(">PromptCadence<")]
    assert 'title="stopped."' in group
    assert group.count(">—<") == 3


def test_the_console_overview_cards_render_in_under_the_shell_budget(
    tmp_path: Path, respx_mock: Any
) -> None:
    """The three status reads run concurrently: a sequential read of three 100 ms calls would
    take ~300 ms; concurrent, the whole page renders in well under that."""
    delay_seconds = 0.1

    def _slow(request: httpx.Request) -> httpx.Response:
        time.sleep(delay_seconds)
        return httpx.Response(200, json=_status_body("loadcoach"))

    for base_url in (LOADCOACH_URL, PROMPTCADENCE_URL, FREEWEIGHT_URL):
        respx_mock.get(f"{base_url}/api/v1/system/status").mock(side_effect=_slow)
    mock_loadcoach(respx_mock)
    mock_promptcadence(respx_mock)
    mock_freeweight(respx_mock)
    console = _console(
        tmp_path,
        systemd=FakeSystemdController(
            states={
                "loadcoach.service": "active",
                "promptcadence.service": "active",
                "freeweight.service": "active",
            }
        ),
    )
    console.login()
    started = time.perf_counter()
    response = console.client.get("/", headers={"Accept": "text/html"})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed < delay_seconds * 2, f"took {elapsed:.2f}s — the three reads were not concurrent"

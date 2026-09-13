"""Spec §15, every budget, measured on the reference machine and asserted (row W10, gate B).

Marked ``performance`` and excluded from the default gate, like every budget assertion in the
suite. Each test measures WeightRoomGym's **own** work — the render, the frame, the page, the
relay — over fakes and fixtures, so the number is the console's overhead and not a peer's. The
figures are printed so a gate report can quote them beside the budget.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from mirrorwall import Event, format_frame

from tests.integration.test_db_guard import _rig
from tests.security.test_chat_isolation import _loadcoach_stream
from tests.support import (
    FREEWEIGHT_URL,
    JSON_HEADERS,
    LOADCOACH_URL,
    PROMPTCADENCE_URL,
    Console,
    api_routes,
    build_console,
    fake_application,
    fill_rows,
    fixture_database,
    mock_freeweight,
    mock_loadcoach,
    mock_promptcadence,
)
from weightroom.config import APPLICATIONS, load_settings
from weightroom.infrastructure.db.models import TelemetrySample
from weightroom.services.chat import run_loadcoach_reply
from weightroom.services.chat_loadcoach import stream_reply
from weightroom.services.database import Database, ensure_ready
from weightroom.services.db_reader import (
    CONSOLE_ROW_CAP,
    STATEMENT_TIMEOUT_SECONDS,
    DatabaseUrlCache,
    open_app_database,
    table_page,
)
from weightroom.services.docs import render_markdown
from weightroom.services.docs_index import rebuild_index, search
from weightroom.services.journal import parse_entry
from weightroom.services.processes import FakeSystemdController
from weightroom.services.telemetry import _GENERATOR, TelemetryService, read_since, sample_frame

pytestmark = pytest.mark.performance

DOCS_ROOT = Path(__file__).resolve().parents[2] / "docs"
_WARMUP = 3
_MEASURED = 15


def _median_ms(work: Callable[[], object], *, measured: int = _MEASURED) -> float:
    for _ in range(_WARMUP):
        work()
    samples = []
    for _ in range(measured):
        started = time.perf_counter()
        work()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def _report(name: str, value: float, budget: float, unit: str = "ms") -> None:
    print(f"\n{name}: {value:.1f} {unit} (budget {budget:g} {unit})")  # noqa: T201 — the gate report quotes it


CONFIG_SHOW_SECONDS = 0.5
"""What ``<app> config show --json`` costs on the reference machine — a Python interpreter start.

Row W10's budget table measured the Overview at 3.0 ms because the fake application answers in
milliseconds, so the launch the page made on every render cost nothing here while costing 0.5 s
on the reference machine (WP6 finding 7: ``loadcoach config show --json`` 576 ms, the Overview
544 ms). The fake now sleeps for it, so the budget below is only met by not launching per render.
"""


@pytest.fixture
def console(tmp_path: Path) -> Console:
    lines = [f'[docs]\nroot = "{DOCS_ROOT}"\n']
    for app in APPLICATIONS:
        # Only LoadCoach pays the realistic launch cost: it is the Overview this file measures,
        # and a sleep in all four would tax the fixture of every other budget below.
        slow = app == "loadcoach"
        executable, _config, _document = fake_application(
            tmp_path,
            app,
            database_url=f"sqlite:///{fixture_database(tmp_path, 'loadcoach-0015')}"
            if slow
            else None,
            show_delay_seconds=CONFIG_SHOW_SECONDS if slow else 0.0,
        )
        lines.append(f'[apps.{app}]\nexecutable = "{executable}"\n')
    console = build_console(
        tmp_path / "console",
        extra_toml="".join(lines),
        systemd=FakeSystemdController(states={"loadcoach.service": "active"}),
    )
    console.login()
    return console


# --- Shell render (top bar, strip, menu) on a warm process: ≤ 50 ms ------------------------------


def test_shell_render_on_a_warm_process(console: Console) -> None:
    def work() -> None:
        assert console.client.get("/", headers={"Accept": "text/html"}).status_code == 200

    median = _median_ms(work)
    _report("shell render", median, 50)
    assert median <= 50


@pytest.fixture
def three_app_console(tmp_path: Path) -> Console:
    """LoadCoach, PromptCadence and FreeWeight all installed and active — row WY3's `/` cards."""
    lines = []
    for app in ("loadcoach", "promptcadence", "freeweight"):
        executable, _config, _document = fake_application(tmp_path, app)
        lines.append(f'[apps.{app}]\nexecutable = "{executable}"\n')
    console = build_console(
        tmp_path / "console",
        extra_toml="".join(lines),
        systemd=FakeSystemdController(
            states={
                "loadcoach.service": "active",
                "promptcadence.service": "active",
                "freeweight.service": "active",
            }
        ),
    )
    console.login()
    return console


def test_the_overview_cards_read_three_applications_concurrently_not_in_series(
    three_app_console: Console, respx_mock: Any
) -> None:
    """Row WY3: a sequential read of three status calls would take three times as long as one —
    the WPF6 lesson is that the fake must cost what the real call does, so each of the three sleeps
    a deliberately unrealistic 300 ms; the assertion is that the render stays far below 3 × that,
    which only a concurrent read can manage."""
    delay_seconds = 0.3

    def _slow(request: httpx.Request) -> httpx.Response:
        time.sleep(delay_seconds)
        return httpx.Response(
            200, json={"active": 0, "oldest_queued_age_seconds": None, "starving": 0}
        )

    mock_loadcoach(respx_mock)
    mock_promptcadence(respx_mock)
    mock_freeweight(respx_mock)
    for base_url in (LOADCOACH_URL, PROMPTCADENCE_URL, FREEWEIGHT_URL):
        respx_mock.get(f"{base_url}/api/v1/system/status").mock(side_effect=_slow)

    def work() -> None:
        page = three_app_console.client.get("/", headers={"Accept": "text/html"})
        assert page.status_code == 200

    median = _median_ms(work, measured=5)
    budget_ms = delay_seconds * 1000 * 2  # well under 3x serial, comfortably above 1x concurrent
    _report("shell overview cards (three apps, concurrent)", median, budget_ms)
    assert median < budget_ms


# --- Application Overview page, application running: ≤ 300 ms -----------------------------------


def test_application_overview_with_the_application_running(
    console: Console, respx_mock: Any
) -> None:
    mock_loadcoach(respx_mock)

    def work() -> None:
        page = console.client.get("/apps/loadcoach", headers={"Accept": "text/html"})
        assert page.status_code == 200

    median = _median_ms(work)
    _report("overview page (loadcoach running)", median, 300)
    assert median <= 300
    assert median < CONFIG_SHOW_SECONDS * 1000, "a per-render config show cannot fit the budget"


# --- Telemetry sample → SSE frame ≤ 20 ms; the 1 s cadence held within ±100 ms -----------------


def test_telemetry_sample_to_frame_and_the_sampler_cadence(tmp_path: Path) -> None:
    file = tmp_path / "c.toml"
    file.write_text(
        f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/wr.sqlite3"\n'
        "[telemetry]\ninterval_ms = 1000\n",
        encoding="utf-8",
    )
    settings = load_settings(config_path=file).settings
    database = Database.from_url(settings.storage.database_url or "")
    ensure_ready(database, auto_migrate=True)
    service = TelemetryService(database, settings)
    service.start()
    try:
        time.sleep(5.2)
    finally:
        service.stop()
    rows = read_since(database, after_id=0, limit=100)
    assert len(rows) >= 4, "the sampler must have run at 1 s for five seconds"
    gaps_ms = [
        (later.at - earlier.at).total_seconds() * 1000.0
        for earlier, later in zip(rows, rows[1:], strict=False)
    ]
    worst = max(abs(gap - 1000.0) for gap in gaps_ms)
    _report("sampler cadence drift (worst)", worst, 100)
    assert worst <= 100, gaps_ms

    row = rows[-1]
    median = _median_ms(lambda: sample_frame(row, queue=None), measured=50)
    _report("telemetry sample → SSE frame", median, 20)
    assert median <= 20


# --- Journal line → SSE frame ≤ 50 ms ------------------------------------------------------------


def test_journal_line_to_frame() -> None:
    raw = {
        "__CURSOR": "s=1;i=1",
        "__REALTIME_TIMESTAMP": str(int(datetime(2026, 9, 10, tzinfo=UTC).timestamp() * 1e6)),
        "PRIORITY": "6",
        "_SYSTEMD_USER_UNIT": "loadcoach.service",
        "SYSLOG_IDENTIFIER": "loadcoach",
        "_PID": "4242",
        "MESSAGE": json.dumps(
            {
                "level": "INFO",
                "logger": "loadcoach.web",
                "message": "request.completed",
                "request_id": "01REQ",
                "path": "/api/v1/route",
                "duration_ms": 12.5,
            }
        ),
    }

    def work() -> None:
        line = parse_entry(raw)
        assert line is not None
        format_frame(Event(sequence=1, type="log", payload=line.as_json()), generator=_GENERATOR)

    median = _median_ms(work, measured=50)
    _report("journal line → SSE frame", median, 50)
    assert median <= 50


# --- Database table page, 100 rows, SQLite ≤ 150 ms; the SQL console caps ----------------------


def test_database_table_page_of_a_hundred_rows(tmp_path: Path) -> None:
    path = fixture_database(tmp_path, "freeweight-0010")
    fill_rows(
        path,
        "samples",
        [
            {
                "id": f"01SAMPLE{index:018d}",
                "run_test_id": "RT1",
                "ordinal": index,
                "status": "completed",
            }
            for index in range(1000)
        ],
    )
    executable, _config, _document = fake_application(
        tmp_path, "freeweight", database_url=f"sqlite:///{path}"
    )
    file = tmp_path / "console.toml"
    file.write_text(f'[apps.freeweight]\nexecutable = "{executable}"\n', encoding="utf-8")
    settings = load_settings(config_path=file).settings
    own = Database.from_url(f"sqlite:///{tmp_path / 'weightroom.sqlite3'}")
    ensure_ready(own, auto_migrate=True)
    handle = open_app_database(settings, own, "freeweight", urls=DatabaseUrlCache(), now=0.0)

    def work() -> None:
        page = table_page(handle, "samples", page=3)
        assert len(page.rows) == 100

    median = _median_ms(work)
    _report("table page, 100 rows, SQLite", median, 150)
    assert median <= 150


def test_the_sql_console_caps_are_the_specified_ones() -> None:
    assert STATEMENT_TIMEOUT_SECONDS == 30.0
    assert CONSOLE_ROW_CAP == 10_000


# --- Guarded write, end to end ≤ 2 s -------------------------------------------------------------


def test_guarded_write_end_to_end(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    started = time.perf_counter()
    result = rig.write()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert result.counts.rows == 3
    _report("guarded write, dry run + backup + statement + audit", elapsed_ms, 2000)
    assert elapsed_ms <= 2000


# --- Docs page render, ≥ 40 KB markdown ≤ 100 ms; search over the whole tree ≤ 200 ms ----------


def test_docs_render_and_search(tmp_path: Path) -> None:
    root = DOCS_ROOT.resolve()
    page = root / "apps" / "promptcadence" / "spec.md"
    assert page.stat().st_size >= 40 * 1024, "the fixture page must be at least 40 KB"
    median = _median_ms(lambda: render_markdown(root, page))
    _report(f"docs render ({page.stat().st_size // 1024} KB markdown)", median, 100)
    assert median <= 100

    database = Database.from_url(f"sqlite:///{tmp_path / 'wr.sqlite3'}")
    ensure_ready(database, auto_migrate=True)
    indexed = rebuild_index(database, root)
    assert indexed > 100

    def work() -> None:
        assert search(database, "guard", limit=20).hits

    median = _median_ms(work)
    _report(f"docs search over {indexed} documents", median, 200)
    assert median <= 200


# --- Chat: first token after LoadCoach's first chunk ≤ 30 ms added latency ----------------------


def test_chat_adds_at_most_thirty_milliseconds_before_the_first_token(
    console: Console, respx_mock: Any
) -> None:
    mock_loadcoach(respx_mock, stream=_loadcoach_stream("one token", thinking=""))
    created = console.client.post(
        "/api/v1/chat/conversations",
        json={"backend": "loadcoach", "title": "budget"},
        headers=JSON_HEADERS,
    )
    conversation_id = created.json()["id"]
    state = console.client.app.state  # type: ignore[attr-defined]
    base_url = state.settings.apps.loadcoach.base_url

    def raw_stream() -> None:
        with httpx.Client() as client:
            list(stream_reply(client, base_url=base_url, token=None, body={"prompt": "go"}))

    def relay() -> None:
        sent = console.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"text": "go"},
            headers=JSON_HEADERS,
        )
        message_id = sent.json()["message_id"]
        with httpx.Client() as client:
            run_loadcoach_reply(
                state.database,
                client,
                settings=state.settings,
                conversation_id=conversation_id,
                message_id=message_id,
                attachments_root=state.attachments_root,
            )

    upstream = _median_ms(raw_stream, measured=10)
    whole = _median_ms(relay, measured=10)
    added = max(whole - upstream, 0.0)
    _report("chat relay, added over the raw LoadCoach stream", added, 30)
    assert added <= 30


# --- JS per page ≤ 120 KB in total, ECharts and mermaid aside (ADR-0139) -------------------------

_SCRIPT_SRC = re.compile(r'<script[^>]+src="([^"]+)"')
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
_LOADED_WHERE_USED = ("vendor/mermaid/", "vendor/echarts/")
"""Spec §15's two exceptions, by path: they load only on the page that uses them."""
_TOTAL_BUDGET_BYTES = 120 * 1024


def _pages(console: Console) -> Iterator[str]:
    for path, route in api_routes(console.client.app):
        if "GET" not in (route.methods or set()) or path.startswith("/api/"):
            continue
        if path.replace("{app}", "").count("{") or "/stream" in path or path == "/trust/root.crt":
            continue
        if "{app}" in path:
            yield from (path.replace("{app}", app) for app in APPLICATIONS)
        else:
            yield path


def test_javascript_per_page_stays_under_the_total_budget(console: Console) -> None:
    totals: dict[str, int] = {}
    sizes: dict[str, int] = {}
    for path in sorted(set(_pages(console))):
        response = console.client.get(path, headers={"Accept": "text/html"})
        if response.status_code != 200:
            continue
        total = sum(len(script) for script in _INLINE_SCRIPT.findall(response.text))
        for src in _SCRIPT_SRC.findall(response.text):
            if any(name in src for name in _LOADED_WHERE_USED):
                continue
            name = src.split("?")[0]
            if name not in sizes:
                asset = console.client.get(src)
                assert asset.status_code == 200, (path, src)
                sizes[name] = len(asset.content)
            total += sizes[name]
        totals[path] = total
    worst_path, worst = max(totals.items(), key=lambda item: item[1])
    for name, size in sorted(sizes.items()):
        print(f"\n  {size / 1024:6.1f} KB  {name}")  # noqa: T201 — ADR-0139 rule 2
    htmx_pair = sum(size for name, size in sizes.items() if "vendor/htmx/" in name)
    print(f"\n  {htmx_pair / 1024:6.1f} KB  htmx + its SSE extension together")  # noqa: T201
    _report(f"JS in total on the heaviest page ({worst_path})", worst / 1024, 120, unit="KB")
    assert worst <= _TOTAL_BUDGET_BYTES, totals


# --- The telemetry page over a day of samples, every figure from one read: ≤ 50 ms (row WY4) ---


def test_the_telemetry_page_over_a_day_of_samples(console: Console) -> None:
    """The shell-render budget, on the page that reads the most rows: a day at the sweep's shape
    (an hour at one per second, then one per minute) is 4 980 rows, seven charts from them."""
    offsets = [timedelta(seconds=s) for s in range(3600)]
    offsets += [timedelta(minutes=m) for m in range(60, 24 * 60)]
    with console.database.write() as session:
        session.add_all(
            TelemetrySample(
                at=console.now - offset,
                interval_ms=1000,
                cpu_percent=float(index % 100),
                cpu_temperature_c=40.0 + index % 30,
                ram_used_bytes=(8 + index % 16) * 1024**3,
                ram_total_bytes=64 * 1024**3,
                gpu_index=0,
                gpu_utilization_percent=float(index % 100),
                gpu_temperature_c=35.0 + index % 40,
                gpu_power_watts=20.0 + index % 300,
                gpu_vram_used_bytes=(index % 16) * 1024**3,
                gpu_vram_total_bytes=16 * 1024**3,
            )
            for index, offset in enumerate(offsets)
        )
    sizes: list[int] = []

    def work() -> None:
        page = console.client.get("/telemetry/history", headers={"Accept": "text/html"})
        assert page.status_code == 200
        sizes.append(len(page.content))

    median = _median_ms(work)
    _report(f"telemetry page over a day ({len(offsets)} rows)", median, 50)
    print(f"\n  its HTML: {sizes[-1] / 1024:.1f} KB, not budgeted")  # noqa: T201
    assert median <= 50


# --- ECharts, named and budgeted by name, excluded from the 120 KB total above (ADR-0142) -------

_ECHARTS_BUDGET_BYTES = 1_150_000
"""Headroom over the 1 121 883 bytes ECharts 6.1.0 measures — a MirrorWall pin bump re-measures."""


def test_echarts_is_named_and_budgeted_by_name(console: Console) -> None:
    page = console.client.get("/telemetry/history", headers={"Accept": "text/html"})
    assert page.status_code == 200
    srcs = _SCRIPT_SRC.findall(page.text)
    (echarts_src,) = (src for src in srcs if "vendor/echarts/" in src)
    asset = console.client.get(echarts_src)
    assert asset.status_code == 200
    echarts_bytes = len(asset.content)

    console_only = sum(len(script) for script in _INLINE_SCRIPT.findall(page.text))
    for src in srcs:
        if "vendor/echarts/" in src:
            continue
        console_only += len(console.client.get(src).content)

    print(f"\n  {echarts_bytes / 1024:6.1f} KB  vendor/echarts/echarts.min.js")  # noqa: T201
    _report(
        "ECharts, on the one page that loads it",
        echarts_bytes / 1024,
        unit="KB",
        budget=_ECHARTS_BUDGET_BYTES / 1024,
    )
    assert echarts_bytes <= _ECHARTS_BUDGET_BYTES
    # Reported beside the part (ADR-0138 rule 3, revived here for this one library): the total a
    # phone actually downloads on this page, not only the console-JS figure the 120 KB row governs.
    _report(
        "same page, console JS + ECharts (not asserted; ADR-0139's total excludes ECharts)",
        (console_only + echarts_bytes) / 1024,
        unit="KB",
        budget=120,
    )


# --- the shell's stylesheet ≤ 32 KB (row WX3) ---------------------------------------------------

_SHELL_CSS_BUDGET_BYTES = 32 * 1024
"""The shell's own stylesheet, on every page and cached once. ADR-0139 budgets JavaScript only;
this is its sibling, so that moving the `<style>` block out of `_shell.html` cannot quietly turn
into an unbounded stylesheet the same way an unbudgeted script would."""


def test_the_shell_stylesheet_stays_under_its_budget() -> None:
    stylesheet = (
        Path(__file__).resolve().parents[2] / "src/weightroom/web/static/css/weightroom-shell.css"
    )
    size = stylesheet.stat().st_size
    _report("the shell's stylesheet", size / 1024, 32, unit="KB")
    assert size <= _SHELL_CSS_BUDGET_BYTES

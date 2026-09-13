"""``/api/v1/system/telemetry/*`` and ``/api/v1/system/resident`` (api.md §1, spec §7.7).

The stream and history routes read straight from the database — ``build_console`` never enters
the lifespan (``tests/support.py``'s own docstring), so these tests persist rows directly rather
than running a live ``TelemetryService``; that sampler's own behaviour is
``tests/unit/test_telemetry.py``'s job.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
from sqlalchemy import event

from tests.support import Console, build_console
from weightroom.infrastructure.db.models import TelemetrySample
from weightroom.services.database import Database
from weightroom.services.telemetry import FIGURE_SCALES
from weightroom.web.routes.system import _telemetry_frames

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _console(tmp_path: Path) -> Console:
    return build_console(tmp_path)


def _frames(text: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = line.removeprefix("data: ")
        if name and data:
            found.append((name, json.loads(data)))
    return found


@dataclass
class _FakeAppState:
    database: Database


@dataclass
class _FakeApp:
    state: _FakeAppState


class _FakeRequest:
    """Just enough of a ``Request`` for ``_telemetry_frames``: a database and a disconnect clock.

    The route's SSE stream is intentionally unbounded (it is live, not a finite log follow), so
    driving it through ``TestClient.stream()`` would never see its own generator return — that
    pattern works for the log stream tests only because a fake journal closes with ``log.closed``.
    Calling the generator directly, the way FreeWeight's own event-stream tests drive
    ``_event_stream`` (``web/routes/runs.py``), is the deterministic alternative: no thread, no
    portal, no open connection to close.
    """

    def __init__(self, database: Database, *, disconnect_after: int) -> None:
        self.app = _FakeApp(state=_FakeAppState(database=database))
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


async def _collect(database: Database, after_id: int, disconnect_after: int = 1) -> str:
    request = _FakeRequest(database, disconnect_after=disconnect_after)
    # `_telemetry_frames` only ever runs against a real `Request` in production; this fake
    # supplies exactly the two members it reads (`app.state.database` and `is_disconnected()`).
    frames = [
        frame
        async for frame in _telemetry_frames(request, after_id=after_id)  # type: ignore[arg-type]
    ]
    return "".join(frames)


def test_history_needs_a_known_figure(tmp_path: Path) -> None:
    console = _console(tmp_path)
    console.login()

    response = console.client.get("/api/v1/system/telemetry/history?figure=made_up")
    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_history_returns_samples_within_the_window(tmp_path: Path) -> None:
    console = _console(tmp_path)
    console.login()
    with console.database.write() as session:
        session.add(
            TelemetrySample(at=NOW, interval_ms=1000, gpu_index=0, gpu_utilization_percent=61.0)
        )
        session.add(
            TelemetrySample(
                at=NOW - timedelta(hours=48), interval_ms=1000, gpu_utilization_percent=10.0
            )
        )

    body = console.client.get(
        "/api/v1/system/telemetry/history?figure=gpu_utilization_percent&hours=24"
    ).json()
    assert body["figure"] == "gpu_utilization_percent"
    assert len(body["samples"]) == 1
    assert body["samples"][0]["value"] == 61.0


def test_the_stream_replays_persisted_rows_as_enveloped_sse_frames(tmp_path: Path) -> None:
    console = _console(tmp_path)
    with console.database.write() as session:
        session.add(
            TelemetrySample(at=NOW, interval_ms=1000, gpu_index=0, gpu_utilization_percent=61.0)
        )
        session.add(
            TelemetrySample(
                at=NOW + timedelta(seconds=1),
                interval_ms=1000,
                gpu_index=0,
                gpu_utilization_percent=62.0,
            )
        )

    collected = anyio.run(_collect, console.database, 0)
    frames = _frames(collected)
    sampled = [payload for name, payload in frames if name == "telemetry.sampled"]
    assert len(sampled) == 2
    assert sampled[0]["payload"]["gpus"][0]["utilization_percent"] == 61.0
    assert sampled[1]["payload"]["gpus"][0]["utilization_percent"] == 62.0
    # ADR-0025 §3: every non-token frame is enveloped and names its producer.
    assert sampled[0]["generator"]["name"] == "weightroom"
    assert "id: 1\n" in collected


def test_the_stream_resumes_from_last_event_id(tmp_path: Path) -> None:
    console = _console(tmp_path)
    with console.database.write() as session:
        session.add(
            TelemetrySample(at=NOW, interval_ms=1000, gpu_index=0, gpu_utilization_percent=61.0)
        )
        session.add(
            TelemetrySample(
                at=NOW + timedelta(seconds=1),
                interval_ms=1000,
                gpu_index=0,
                gpu_utilization_percent=62.0,
            )
        )

    collected = anyio.run(_collect, console.database, 1)
    frames = _frames(collected)
    sampled = [payload for name, payload in frames if name == "telemetry.sampled"]
    assert len(sampled) == 1
    assert sampled[0]["payload"]["sequence"] == 2


def test_resident_reports_a_source_and_an_error_for_each_unreachable_side(tmp_path: Path) -> None:
    # Both sides on a refused port: the defaults are the real Ollama and LoadCoach, and this test
    # failed whenever the developer's Ollama had a model loaded (found at the W6 demonstration).
    unreachable = "http://127.0.0.1:9"
    console = build_console(
        tmp_path,
        extra_toml=(
            f'[host]\nollama_base_url = "{unreachable}"\n'
            f'[apps.loadcoach]\nbase_url = "{unreachable}"\n'
        ),
    )
    console.login()

    body = console.client.get("/api/v1/system/resident").json()
    assert body["ollama"]["source"] == "ollama"
    assert body["ollama"]["models"] == []
    assert body["loadcoach"]["source"] == "loadcoach"
    assert body["loadcoach"]["models"] == []
    assert body["loadcoach"]["error"]


def _telemetry_page(console: Console, query: str = "") -> str:
    response = console.client.get(f"/telemetry/history{query}", headers={"Accept": "text/html"})
    assert response.status_code == 200
    return str(response.text)


def test_the_telemetry_page_draws_every_figure_from_one_read_with_no_svg_double(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    console.login()
    with console.database.write() as session:
        session.add(
            TelemetrySample(
                at=NOW - timedelta(minutes=1),
                interval_ms=1000,
                cpu_percent=12.0,
                ram_used_bytes=19_541_000_000,
                ram_total_bytes=64 * 1024**3,
                gpu_index=0,
                gpu_vram_used_bytes=1_000_000,
            )
        )
    statements: list[str] = []

    def record(*args: Any) -> None:  # noqa: ANN401 — SQLAlchemy's cursor-event signature
        statements.append(str(args[2]))

    event.listen(console.database.engine, "before_cursor_execute", record)
    try:
        page = _telemetry_page(console)
    finally:
        event.remove(console.database.engine, "before_cursor_execute", record)

    assert len([s for s in statements if "telemetry_samples" in s]) == 1
    for name in FIGURE_SCALES:
        assert f'id="figure-{name}"' in page
    assert page.count("data-echarts=") == 3  # CPU, RAM and VRAM measured; the rest print a dash
    assert "<span data-value>18.2 G</span>" in page and "> / 64 G</span>" in page
    content = page.split('class="shell-main"', 1)[1]
    assert "<svg" not in content and "<h2" not in content and "<select" not in content
    assert 'aria-label="RAM: now 18.2 G, minimum 18.2 G, maximum 18.2 G"' in page


def test_figure_marks_its_chart_and_a_total_marks_the_chart_it_is_printed_on(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    console.login()
    marked = re.compile(r'id="figure-([a-z_]+)"[^>]*data-marked')

    assert marked.findall(_telemetry_page(console, "?figure=gpu_power_watts")) == [
        "gpu_power_watts"
    ]
    assert marked.findall(_telemetry_page(console, "?figure=gpu_vram_total_bytes")) == [
        "gpu_vram_used_bytes"
    ]
    assert marked.findall(_telemetry_page(console, "?figure=not-a-figure")) == []
    assert marked.findall(_telemetry_page(console)) == []


def test_an_empty_window_prints_a_dash_for_every_figure_and_draws_no_chart(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    console.login()
    page = _telemetry_page(console)
    assert "data-echarts=" not in page
    assert page.count('<p class="tm-none">—</p>') == len(FIGURE_SCALES)


def test_telemetry_routes_need_a_session(tmp_path: Path) -> None:
    console = build_console(tmp_path, host="10.77.10.84")
    for path in (
        "/api/v1/system/telemetry/history?figure=cpu_percent",
        "/api/v1/system/telemetry/stream",
        "/api/v1/system/resident",
    ):
        response = console.client.get(path, headers={"Host": "jordan-main.local"})
        assert response.status_code == 401, path

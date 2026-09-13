"""Row WPF5 Gate B: FreeWeight's dashboard and System pages — judged needed at WP6 (§3).

The dashboard half moved onto the **Overview** at row WX8 (``/apps/freeweight``, with
``/apps/freeweight/dashboard`` redirecting to it), so these are the same assertions against the
page that now carries it; what WX8 added to that page is ``test_freeweight_wx8.py``.

``dashboard.json`` was re-recorded for WX8 from a FreeWeight carrying WX7's commit (FreeWeight
``60be9cd``), run against ``FakeProvider`` — no GPU, own XDG tree — after ``native.echo`` and
``native.performance`` completed: the reference machine's own FreeWeight runs 1.2.1 and emits
neither ``tests_matrix`` nor a second suite. ``health.json`` is unchanged. Both pages read the
running API only (spec §7.3 amendment, WPF5): FreeWeight's own dashboard and System pages are
HTML-only computations, so a stopped FreeWeight leaves nothing in its database that would
reproduce them faithfully.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import httpx
import respx

from tests.integration.test_freeweight_pages import (
    BASE,
    fixture,
    freeweight_console,
    mock_api,
    page,
    route_for,
)
from tests.security.test_chat_isolation import HOSTILE, _assert_inert
from weightroom.web.rendering import app_side_nav_stubs

RUN = "01M2C3PKE3RTYJWW16FW69J07V"


def gate_api(router: Any, **bodies: Any) -> dict[str, Any]:  # noqa: ANN401 — a respx router
    """Gate A's recorded reads, and the Dashboard and System recordings beside them."""
    recorded = {"dashboard": fixture("dashboard"), "health": fixture("health")}
    recorded.update(bodies)
    return mock_api(router, bodies=recorded)


def test_every_freeweight_page_is_built_and_none_is_a_stub() -> None:
    assert app_side_nav_stubs("freeweight") == ()


# --- The dashboard, on the Overview (row WX8) -----------------------------------------------------


def test_the_overview_reads_freeweights_summary_and_heatmap(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = fixture("dashboard")
    with respx.mock(assert_all_called=False) as router:
        gate_api(router)
        text = page(console, BASE)
    assert '<a href="/apps/freeweight" aria-current="page">Overview</a>' in text
    assert str(dashboard["cards"]["completed_runs"]) in text
    assert dashboard["heatmap"]["models"][0] in text
    assert dashboard["heatmap"]["suites"][0] in text
    assert f'href="/apps/freeweight/runs/{RUN}"' in text
    assert "From the API" in text
    # The latest-run figure is the date alone; the full RFC 3339 stamp overflowed the card at every
    # width (WPF5's browser check). The clock survives in the note.
    stamp = dashboard["cards"]["latest_run_at"]
    assert stamp not in text
    assert stamp[:10] in text
    assert f"Completed at {stamp[11:19]} UTC." in text


def test_the_overviews_dashboard_filters_reach_freeweights_query(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = gate_api(router)
        page(
            console,
            f"{BASE}?suite=native.echo&model=m&machine=abc&since=2026-09-01T00:00:00Z",
        )
    params = routes["dashboard"].calls.last.request.url.params
    assert (params["suite"], params["model"], params["machine"]) == ("native.echo", "m", "abc")
    assert params["since"] == "2026-09-01T00:00:00Z"


def test_a_separated_heatmap_carries_the_warning(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = copy.deepcopy(fixture("dashboard"))
    dashboard["heatmap"]["separated"] = True
    with respx.mock(assert_all_called=False) as router:
        gate_api(router, dashboard=dashboard)
        text = page(console, BASE)
    assert "Separated" in text


def test_a_refused_filter_renders_freeweights_own_refusal(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_api(router)
        route_for(router, "GET", "dashboard").mock(
            return_value=httpx.Response(
                404,
                json={
                    "error": {
                        "code": "MODEL_NOT_FOUND",
                        "message": "No model matches 'nothing'.",
                        "details": {"model": "nothing"},
                    }
                },
            )
        )
        text = page(console, f"{BASE}?model=nothing")
    assert "MODEL_NOT_FOUND" in text
    assert "No model matches" in text


def test_a_stopped_overviews_dashboard_reads_only_from_the_api(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="inactive")
    text = page(console, BASE)
    assert "reads only from its running API" in text
    # The unit's own figures and its log are still there: those are the console's own reads.
    assert "Journal history as JSON" in text


def test_the_injection_corpus_renders_inert_on_the_overview(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = copy.deepcopy(fixture("dashboard"))
    dashboard["heatmap"]["cells"][0]["unavailable_reason"] = HOSTILE
    dashboard["heatmap"]["models"][0] = HOSTILE
    with respx.mock(assert_all_called=False) as router:
        gate_api(router, dashboard=dashboard)
        text = page(console, BASE)
    _assert_inert(text)


# --- System -------------------------------------------------------------------------------------


def test_the_system_page_reads_version_status_and_health_components(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    health = fixture("health")
    with respx.mock(assert_all_called=False) as router:
        gate_api(router)
        text = page(console, f"{BASE}/system")
    assert '<a href="/apps/freeweight/system" aria-current="page">System</a>' in text
    assert health["version"] in text
    for component in (
        "database", "provider", "gpu_telemetry", "machine", "evidence",
        "prompts", "sandbox", "external_benchmarks", "goals", "judges",
    ):  # fmt: skip
        assert f">{component}<" in text, component
    assert "From the API" in text


def test_a_stopped_systems_page_reads_only_from_the_api(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="inactive")
    assert "reads only from its running API" in page(console, f"{BASE}/system")


def test_a_degraded_component_renders_its_own_detail(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    health = copy.deepcopy(fixture("health"))
    health["components"][1]["status"] = "degraded"
    health["components"][1]["detail"] = "provider is slow to answer"
    health["status"] = "degraded"
    with respx.mock(assert_all_called=False) as router:
        gate_api(router, health=health)
        text = page(console, f"{BASE}/system")
    assert "provider is slow to answer" in text


def test_the_injection_corpus_renders_inert_on_the_system_page(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    health = copy.deepcopy(fixture("health"))
    health["components"][0]["detail"] = HOSTILE
    with respx.mock(assert_all_called=False) as router:
        gate_api(router, health=health)
        text = page(console, f"{BASE}/system")
    _assert_inert(text)

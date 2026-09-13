"""Row WX8: the Overview that swallowed the Dashboard, the Goals sections, the manifest draft.

``dashboard.json`` was re-recorded for this row from a FreeWeight carrying WX7 (``60be9cd``) run
against ``FakeProvider`` — two suites over one model, so the heatmap has two columns and the tests
matrix seven — which is what makes the toggle testable at all: the reference machine's FreeWeight
runs 1.2.1 and answers no ``tests_matrix``.
"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any

import httpx
import respx

from tests.integration.test_freeweight_pages import (
    BASE,
    audit,
    fixture,
    freeweight_console,
    mock_api,
    page,
    post,
    route_for,
)
from tests.security.test_chat_isolation import HOSTILE, _assert_inert
from weightroom.services.freeweight_pages import heatmap_option

if TYPE_CHECKING:
    from pathlib import Path

ECHO_RUN = "01M2C3PKE3RTYJWW16FW69J07V"
PERFORMANCE_RUN = "01M2C3PM4G4W2XNXGG0VH314NM"
MODEL = "fake/fake-model:8b-q8_0@sha256:fa4efa4efa4e"


# --- The Overview, and the Dashboard merged into it -----------------------------------------------


def test_the_dashboards_path_still_means_what_it_meant(tmp_path: Path) -> None:
    """The menu entry went; a bookmark did not have to."""
    console, _database = freeweight_console(tmp_path, state="active")
    plain = console.client.get(f"{BASE}/dashboard", headers={"Accept": "text/html"})
    assert plain.status_code == 303
    assert plain.headers["location"] == BASE
    scoped = console.client.get(
        f"{BASE}/dashboard?suite=native.echo&model=m", headers={"Accept": "text/html"}
    )
    assert scoped.headers["location"] == f"{BASE}?suite=native.echo&model=m"


def test_the_overview_carries_the_dashboard_the_start_form_and_the_unit(tmp_path: Path) -> None:
    """One page for the tab's landing question: what has been measured, and what to measure next."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, BASE)
    # The dashboard's cards and its heatmap.
    assert "Completed runs" in text
    assert "native.performance" in text
    assert f'href="{BASE}/runs/{PERFORMANCE_RUN}"' in text
    # The Start form, moved from the Runs page.
    assert 'id="fw-start-model"' in text
    assert 'action="/apps/freeweight/runs"' in text
    # The unit's own controls and log, which the generic Overview always had.
    assert 'value="restart"' in text
    assert "Journal history as JSON" in text
    # And the Runs page keeps the way to the form.
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        runs = page(console, f"{BASE}/runs")
    assert 'href="/apps/freeweight#start"' in runs
    assert 'id="fw-start-model"' not in runs


def test_a_refused_start_comes_back_on_the_overview_with_what_was_typed(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        response = post(
            console, f"{BASE}/runs", {"model": MODEL, "suite": "not a suite", "label": "kept"}
        )
    assert response.status_code == 200
    assert "VALIDATION_ERROR" in response.text
    assert 'value="kept"' in response.text
    assert "Completed runs" in response.text  # it is the Overview, not the Runs page
    (row,) = audit(console, "job.enqueue")
    assert row["outcome"] == "refused"


# --- The heatmap ↔ matrix toggle ------------------------------------------------------------------


def test_both_views_are_rendered_and_the_switch_is_two_radios(tmp_path: Path) -> None:
    """Two sections and a native radio pair — no JavaScript decides which is showing, so a reader
    with none sees the suites view and can still reach the matrix."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, BASE)
    assert 'id="fw-view-suites"' in text
    assert 'id="fw-view-tests"' in text
    assert text.count('name="fw-view"') == 2
    # The suites view: one headline metric per suite, and the metric named in the column head.
    assert "harness_roundtrip_success" in text
    assert "decode_tokens_per_second" in text
    # The matrix: every test of both runs, sparse, with each cell's own run.
    for test in (
        "echo.short",
        "echo.long",
        "performance.cold_load",
        "performance.streaming_latency",
    ):
        assert test in text, test
    assert 'data-table="fw-tests-matrix"' in text


def test_a_skipped_test_says_why_and_a_test_that_never_ran_is_empty(tmp_path: Path) -> None:
    """The matrix exists for exactly this: a suite whose hardest test was skipped still shows a
    headline number beside it, and only this view says so (spec §13 — a reason, or nothing)."""
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = copy.deepcopy(fixture("dashboard"))
    cells = dashboard["tests_matrix"]["cells"]
    cells[0] = {**cells[0], "status": "skipped", "skip_reason": "would not fit in VRAM"}
    dashboard["tests_matrix"]["tests"].append("echo.never_ran")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"dashboard": dashboard})
        text = page(console, BASE)
    assert "would not fit in VRAM" in text
    assert "that run recorded no such test" in text


def test_freeweight_answering_no_matrix_leaves_the_suites_view_whole(tmp_path: Path) -> None:
    """1.2.1 does not emit ``tests_matrix``; the page says so where the matrix would be and
    renders every figure it did answer."""
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = copy.deepcopy(fixture("dashboard"))
    del dashboard["tests_matrix"]
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"dashboard": dashboard})
        text = page(console, BASE)
    assert "No run in this scope recorded a test outcome" in text
    assert "harness_roundtrip_success" in text


def test_the_injection_corpus_renders_inert_in_the_matrix(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = copy.deepcopy(fixture("dashboard"))
    dashboard["tests_matrix"]["tests"][0] = HOSTILE
    dashboard["tests_matrix"]["cells"][0] = {
        **dashboard["tests_matrix"]["cells"][0],
        "skip_reason": HOSTILE,
    }
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"dashboard": dashboard})
        text = page(console, BASE)
    _assert_inert(text)


# --- The heatmap's ECharts option -----------------------------------------------------------------


def test_each_column_is_scaled_on_its_own_and_an_unmeasured_cell_is_not_a_zero() -> None:
    """Two suites in two units: a colour scale over both would say the faster model is the more
    accurate one. And ``unsupported`` is not ``0`` (ADR-0016) — it draws nothing."""
    recorded = fixture("dashboard")
    option = heatmap_option(recorded)
    assert option is not None
    (series,) = option["series"]
    assert series["type"] == "heatmap"
    # One numeric cell in the recording; the other reads `unsupported`.
    assert [point["value"][2] for point in series["data"]] == [1.0]
    assert option["xAxis"]["data"] == recorded["heatmap"]["suites"]

    two_ways = {
        "heatmap": {
            "models": ["a", "b"],
            "suites": ["fast", "slow"],
            "cells": [
                {"model": "a", "suite": "fast", "value": 10.0, "higher_is_better": True},
                {"model": "b", "suite": "fast", "value": 20.0, "higher_is_better": True},
                {"model": "a", "suite": "slow", "value": 1.0, "higher_is_better": False},
                {"model": "b", "suite": "slow", "value": 5.0, "higher_is_better": False},
            ],
        }
    }
    both = heatmap_option(two_ways)
    assert both is not None
    (series,) = both["series"]
    by_cell = {
        (point["value"][0], point["value"][1]): point["value"][2] for point in series["data"]
    }
    assert by_cell[(0, 1)] == 1.0  # b is fastest, and higher is better there
    assert by_cell[(1, 0)] == 1.0  # a is lowest, and lower is better there
    assert by_cell[(0, 0)] == 0.0
    assert by_cell[(1, 1)] == 0.0


def test_no_numeric_cell_means_no_chart_and_no_echarts_on_the_landing_page(
    tmp_path: Path,
) -> None:
    """ECharts is 1.1 MB and this is the tab's landing page: it is asked for when there is a
    drawing to make, and the table is the page either way (ADR-0020 rule 5)."""
    assert heatmap_option({"heatmap": {"models": [], "suites": [], "cells": []}}) is None
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        drawn = page(console, BASE)
    assert "vendor/echarts/" in drawn
    assert "data-echarts=" in drawn

    unsupported = copy.deepcopy(fixture("dashboard"))
    for cell in unsupported["heatmap"]["cells"]:
        cell["value"] = "unsupported"
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"dashboard": unsupported})
        plain = page(console, BASE)
    assert "vendor/echarts/" not in plain
    assert "harness_roundtrip_success" in plain  # the table is still the page


# --- Goals: three sections ------------------------------------------------------------------------


def test_the_goals_page_reads_as_three_sections_and_moves_nothing_between_routes(
    tmp_path: Path,
) -> None:
    from tests.integration.test_freeweight_goals import SLUG, mock_goals

    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        text = page(console, f"{BASE}/goals")
    for anchor in ('id="results"', 'id="set-up"', 'id="runs"'):
        assert anchor in text, anchor
    assert text.index('id="results"') < text.index('id="set-up"') < text.index('id="runs"')
    # Every form the page had is still on it, posting where it posted before.
    for action in (
        f'action="{BASE}/goals/drafts"',
        f'action="{BASE}/goals"',
        f'action="{BASE}/goals/import"',
    ):
        assert action in text, action
    assert f'href="{BASE}/goals/{SLUG}"' in text


# --- Adapters: the manifest explained, and drafted ------------------------------------------------


def test_the_page_says_what_a_manifest_is_and_offers_a_draft_for_each_artifact_without_one(
    tmp_path: Path,
) -> None:
    from tests.integration.test_freeweight_adapters_provider import ADAPTERS

    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": ADAPTERS})
        text = page(console, f"{BASE}/adapters")
    assert "manifest.json" in text
    assert "artifact_sha256" in text
    assert "data_classification" in text
    # `unmanifested` carries full paths; the route names the artifact by its stem.
    assert f'action="{BASE}/adapters/stray/draft"' in text
    assert 'name="base_model_name"' in text
    # Keeping a draft is renaming it, and the page says so rather than offering a button for it.
    assert "manifest.draft.json" in text
    assert "mv " in text


def test_a_draft_is_written_audited_and_shown_with_the_review_step(tmp_path: Path) -> None:
    from tests.integration.test_freeweight_adapters_provider import ADAPTERS

    console, _database = freeweight_console(tmp_path, state="active")
    written = {
        "adapter": "stray",
        "path": "/home/jordan/models/adapters/stray.manifest.draft.json",
        "payload": {"name": "stray", "data_classification": "confidential"},
    }
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": ADAPTERS})
        drafted = route_for(router, "POST", "adapters/stray/draft").mock(
            return_value=httpx.Response(200, json=written)
        )
        response = post(console, f"{BASE}/adapters/stray/draft", {"base_model_name": "qwen3:8b"})
        sent = drafted.calls.last.request
    assert response.status_code == 200
    assert json.loads(sent.content)["base_model_name"] == "qwen3:8b"
    assert str(written["path"]) in response.text
    assert "stray.manifest.json" in response.text  # the rename that keeps it
    (row,) = audit(console, "freeweight.adapter_draft")
    assert row["outcome"] == "ok"
    assert row["params"]["base_model_name"] == "qwen3:8b"


def test_a_draft_with_no_base_is_refused_before_freeweight_is_asked(tmp_path: Path) -> None:
    """The base is the one field nobody can read off a GGUF, so a blank one is not a request."""
    from tests.integration.test_freeweight_adapters_provider import ADAPTERS

    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router, bodies={"adapters": ADAPTERS})
        drafted = route_for(router, "POST", "adapters/stray/draft").mock(
            return_value=httpx.Response(200, json={})
        )
        response = post(console, f"{BASE}/adapters/stray/draft", {"base_model_name": "  "})
    assert response.status_code == 200
    assert "A draft needs the base model" in response.text
    assert not drafted.called
    assert routes["adapters"].called  # the page came back, not an error page
    (row,) = audit(console, "freeweight.adapter_draft")
    assert row["outcome"] == "refused"


def test_freeweights_own_refusal_of_a_draft_is_what_the_page_shows(tmp_path: Path) -> None:
    from tests.integration.test_freeweight_adapters_provider import ADAPTERS

    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": ADAPTERS})
        route_for(router, "POST", "adapters/stray/draft").mock(
            return_value=httpx.Response(
                409,
                json={
                    "error": {
                        "code": "DRAFT_REFUSED",
                        "message": "A draft already claims stray; it is never overwritten.",
                        "details": {"adapter": "stray"},
                    }
                },
            )
        )
        response = post(console, f"{BASE}/adapters/stray/draft", {"base_model_name": "qwen3:8b"})
    assert "DRAFT_REFUSED" in response.text
    assert "never overwritten" in response.text
    (row,) = audit(console, "freeweight.adapter_draft")
    assert row["outcome"] == "refused"


def test_the_injection_corpus_renders_inert_in_an_unmanifested_name(tmp_path: Path) -> None:
    from tests.integration.test_freeweight_adapters_provider import ADAPTERS

    console, _database = freeweight_console(tmp_path, state="active")
    hostile: dict[str, Any] = {
        **ADAPTERS,
        "unmanifested": [f"/home/jordan/models/adapters/{HOSTILE}.gguf"],
    }
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": hostile})
        text = page(console, f"{BASE}/adapters")
    _assert_inert(text)


def test_a_chart_row_is_labelled_short_until_two_models_would_share_one_label() -> None:
    """A category that named two subjects would draw both their cells in one row."""
    distinct: dict[str, Any] = {
        "heatmap": {
            "models": ["ollama/smollm2:135m@sha256:aa", "llamacpp/Qwen2.5.Q8_0@sha256:bb"],
            "suites": ["native.echo"],
            "cells": [
                {"model": "ollama/smollm2:135m@sha256:aa", "suite": "native.echo", "value": 1.0},
                {"model": "llamacpp/Qwen2.5.Q8_0@sha256:bb", "suite": "native.echo", "value": 0.5},
            ],
        }
    }
    option = heatmap_option(distinct)
    assert option is not None
    assert option["yAxis"]["data"] == ["smollm2:135m", "Qwen2.5.Q8_0"]

    same_name = "llamacpp/smollm2:135m@sha256:bb"
    colliding: dict[str, Any] = copy.deepcopy(distinct)
    models: list[str] = colliding["heatmap"]["models"]
    cells: list[dict[str, Any]] = colliding["heatmap"]["cells"]
    models[1], cells[1]["model"] = same_name, same_name
    option = heatmap_option(colliding)
    assert option is not None
    assert option["yAxis"]["data"] == models
    # And the hover still carries the whole identity, short label or long.
    assert all("@sha256:" in point["name"] for point in option["series"][0]["data"])


def test_a_stopped_console_offers_no_draft_and_claims_nothing_about_the_directory(
    tmp_path: Path,
) -> None:
    """The directory is FreeWeight's own reading: stopped, the console knows neither what has a
    manifest nor what is waiting for review, and says neither."""
    console, _database = freeweight_console(tmp_path, state="inactive")
    text = page(console, f"{BASE}/adapters")
    assert "Draft manifest" not in text
    assert "No draft is waiting for review" not in text
    assert "Every artifact in the directory has a manifest" not in text


def test_a_refused_dashboard_filter_does_not_take_the_start_form_away(tmp_path: Path) -> None:
    """The form starts a job; the scope it is standing next to being wrong says nothing about
    whether a run can be started."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route_for(router, "GET", "dashboard").mock(
            return_value=httpx.Response(
                404,
                json={
                    "error": {
                        "code": "MODEL_NOT_FOUND",
                        "message": "No model matches 'nothing'.",
                        "details": {},
                    }
                },
            )
        )
        text = page(console, f"{BASE}?model=nothing")
    assert "MODEL_NOT_FOUND" in text
    assert 'id="fw-start-model"' in text

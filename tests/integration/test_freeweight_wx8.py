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
from weightroom.services.freeweight_pages import bar_charts_by_test, score_heatmap_option

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
    # And the Runs page's bar links to New run, which queues them.
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        runs = page(console, f"{BASE}/runs")
    assert 'href="/apps/freeweight/runs/new"' in runs
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


# --- Scores by test, and one test's bars ---------------------------------------------------------


def test_the_overview_draws_scores_by_test_and_one_tests_bars(tmp_path: Path) -> None:
    """The heatmap is models × tests on one 0–1 scale; below it a picker shows one test's bars,
    with a checkbox per metric where the test has more than one."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, BASE)
    assert 'id="fw-score-heatmap"' in text
    assert 'data-table="fw-scores"' in text
    for test in (
        "echo.short",
        "echo.long",
        "performance.cold_load",
        "performance.streaming_latency",
    ):
        assert test in text, test
    assert 'id="fw-test-pick"' in text
    assert text.count("data-test-chart=") == 2
    assert 'data-metric="decode_ms" checked>' in text
    assert 'data-metric="output_tokens">' in text
    # Summary is the first section under the header, and the controls sit in the header.
    assert 'class="kit-actions app-page-controls"' in text
    assert text.index('value="restart"') < text.index("<h3>Summary</h3>")
    assert text.index("<h3>Summary</h3>") < text.index('id="fw-dash-suite"')


def test_a_skipped_test_says_why_and_a_test_that_never_ran_is_empty(tmp_path: Path) -> None:
    """A skipped test has no score, and its reason is what the cell says (spec §13); a test that
    run never recorded is empty, never a zero."""
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = copy.deepcopy(fixture("dashboard"))
    cells = dashboard["tests_matrix"]["cells"]
    cells[0] = {
        **cells[0],
        "status": "skipped",
        "skip_reason": "would not fit in VRAM",
        "mean_score": None,
    }
    dashboard["tests_matrix"]["tests"].append("echo.never_ran")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"dashboard": dashboard})
        text = page(console, BASE)
    assert "would not fit in VRAM" in text
    assert "that run recorded no such test" in text


def test_freeweight_answering_no_matrix_still_renders_its_summary(tmp_path: Path) -> None:
    """1.2.1 does not emit ``tests_matrix``; the page says so where the scores would be and
    renders every figure it did answer."""
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = copy.deepcopy(fixture("dashboard"))
    del dashboard["tests_matrix"]
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"dashboard": dashboard})
        text = page(console, BASE)
    assert "No run in this scope recorded a test outcome" in text
    assert "Completed runs" in text


def test_the_injection_corpus_renders_inert_in_the_matrix(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    dashboard = copy.deepcopy(fixture("dashboard"))
    dashboard["tests_matrix"]["tests"][0] = HOSTILE
    dashboard["tests_matrix"]["cells"][0] = {
        **dashboard["tests_matrix"]["cells"][0],
        "skip_reason": HOSTILE,
        "mean_score": None,
    }
    dashboard["test_metrics"][0]["test"] = HOSTILE
    dashboard["test_metrics"][0]["metric_key"] = HOSTILE
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"dashboard": dashboard})
        text = page(console, BASE)
    _assert_inert(text)


# --- The charts' ECharts options ------------------------------------------------------------------


def test_the_score_heatmap_is_one_scale_and_an_unscored_cell_is_not_a_zero() -> None:
    """Mean sample scores are 0–1 in every column, so one scale; a cell with nothing scorable
    draws nothing (ADR-0016)."""
    recorded = fixture("dashboard")
    option = score_heatmap_option(recorded)
    assert option is not None
    (series,) = option["series"]
    assert series["type"] == "heatmap"
    assert (option["visualMap"]["min"], option["visualMap"]["max"]) == (0, 1)
    assert option["xAxis"]["data"] == recorded["tests_matrix"]["tests"]
    # Seven cells recorded, one of them with no score.
    assert sorted(point["value"][2] for point in series["data"]) == [0.0, 0.5, 0.8, 1.0, 1.0, 1.0]


def test_each_tests_bars_list_every_model_and_start_on_one_metric() -> None:
    """A test's metrics are in different units, so one starts shown; ``unsupported`` is no bar."""
    charts = bar_charts_by_test(fixture("dashboard"))
    assert [one["test"] for one in charts] == ["echo.short", "performance.decode_throughput"]
    decode = charts[1]
    keys = ["decode_ms", "decode_tokens_per_second", "output_tokens"]
    assert [metric["key"] for metric in decode["metrics"]] == keys
    option = decode["option"]
    assert option["legend"]["selected"] == dict(zip(keys, [True, False, False], strict=True))
    assert option["xAxis"]["data"] == ["fake-model:8b-q8_0"]
    by_name = {series["name"]: series["data"] for series in option["series"]}
    assert by_name["decode_ms"] == [None]
    assert by_name["decode_tokens_per_second"] == [42.5]
    assert decode["rows"] == [["fake-model:8b-q8_0", "—", "42.5", "128"]]


def test_nothing_to_draw_means_no_echarts_on_the_landing_page(tmp_path: Path) -> None:
    """ECharts is 1.1 MB and this is the tab's landing page: it is asked for when there is a
    drawing to make, and the table is the page either way (ADR-0020 rule 5)."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        drawn = page(console, BASE)
    assert "vendor/echarts/" in drawn
    assert "data-echarts=" in drawn

    plain_body = copy.deepcopy(fixture("dashboard"))
    for cell in plain_body["tests_matrix"]["cells"]:
        cell["mean_score"] = None
    plain_body["test_metrics"] = []
    assert score_heatmap_option(plain_body) is None
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"dashboard": plain_body})
        plain = page(console, BASE)
    assert "vendor/echarts/" not in plain
    assert 'data-table="fw-scores"' in plain


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
    first, second = "ollama/smollm2:135m@sha256:aa", "llamacpp/Qwen2.5.Q8_0@sha256:bb"
    distinct: dict[str, Any] = {
        "tests_matrix": {
            "models": [first, second],
            "tests": ["echo.short"],
            "cells": [
                {"model": first, "test": "echo.short", "mean_score": 1.0},
                {"model": second, "test": "echo.short", "mean_score": 0.5},
            ],
        }
    }
    option = score_heatmap_option(distinct)
    assert option is not None
    assert option["yAxis"]["data"] == ["smollm2:135m", "Qwen2.5.Q8_0"]

    same_name = "llamacpp/smollm2:135m@sha256:bb"
    colliding: dict[str, Any] = copy.deepcopy(distinct)
    models: list[str] = colliding["tests_matrix"]["models"]
    cells: list[dict[str, Any]] = colliding["tests_matrix"]["cells"]
    models[1], cells[1]["model"] = same_name, same_name
    option = score_heatmap_option(colliding)
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

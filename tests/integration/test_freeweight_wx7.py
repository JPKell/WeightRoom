"""Row WX7: what FreeWeight's four pages do with the API's new answers.

The recordings under ``tests/fixtures/freeweight`` are the reference machine's own FreeWeight
(see ``test_freeweight_pages``), with row WX7's keys added to the models and machines bodies —
``display_name``, ``nickname``. The list holds a real collision: two enabled models are both
called ``hk:latest``, so both must be shown by canonical ID and neither by the short name.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import httpx
import respx

from tests.integration.test_freeweight_pages import (
    BASE,
    MACHINE,
    RUN,
    audit,
    fixture,
    freeweight_console,
    mock_api,
    page,
    post,
    route_for,
)
from tests.integration.test_freeweight_results_evidence import OTHER_RUN, gate_b_api

if TYPE_CHECKING:
    from pathlib import Path

CANONICAL = "ollama/smollm2:135m@sha256:9077fe9d2ae1"
COLLIDING = "ollama/hk:latest@sha256:3bbf71189af5"


# --- Models ---------------------------------------------------------------------------------------


def test_the_models_page_shows_the_display_name_and_the_canonical_id_for_a_collision(
    tmp_path: Path,
) -> None:
    """FreeWeight decides the name; the console renders it and never re-derives it."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/models")
    assert ">smollm2:135m</a>" in text
    # Two enabled models are called `hk:latest`; a name that names two subjects names neither.
    assert ">hk:latest</a>" not in text
    assert f">{COLLIDING}</a>" in text


def test_the_filter_bar_sends_every_filter_and_converts_billions_to_parameters(
    tmp_path: Path,
) -> None:
    """The table reads `7.6B`, so the box is typed in billions and FreeWeight is asked in
    parameters — the conversion is the console's, once, not a unit FreeWeight learns."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        text = page(
            console,
            f"{BASE}/models?provider_kind=ollama&family=gemma4&quantization=Q8_0"
            "&min_parameters=7.5&max_parameters=12",
        )
    # Two calls: the filtered list, then the unfiltered read the selects' vocabulary comes from.
    params = routes["models"].calls[0].request.url.params
    assert params["provider_kind"] == "ollama"
    assert params["family"] == "gemma4"
    assert params["quantization"] == "Q8_0"
    assert (params["min_parameters"], params["max_parameters"]) == ("7500000000", "12000000000")
    assert 'name="min_parameters" value="7.5"' in text


def test_a_filtered_page_still_offers_every_family_in_its_selects(tmp_path: Path) -> None:
    """A select narrowed to what the filtered list holds is a filter that cannot be undone: the
    page reads the list once more, unfiltered, for the vocabulary alone."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        text = page(console, f"{BASE}/models?family=gemma4")
    assert routes["models"].call_count == 2
    unfiltered = routes["models"].calls[-1].request.url.params
    assert "family" not in unfiltered
    assert '<option value="qwen35"' in text
    assert '<option value="gemma4" selected' in text


def test_a_parameter_bound_that_is_not_a_number_is_refused_before_freeweight_is_asked(
    tmp_path: Path,
) -> None:
    """A filter the console cannot read is not one FreeWeight should be asked to interpret."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        text = page(console, f"{BASE}/models?min_parameters=eight")
    assert "is not a number of billions" in text
    assert "min_parameters" not in routes["models"].calls.last.request.url.params


def test_a_stopped_freeweight_says_the_filters_are_its_own(tmp_path: Path) -> None:
    """The database path can answer the list and none of the filters, and says so (WP3's rule)."""
    console, _database = freeweight_console(tmp_path, state="inactive")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/models?family=gemma4")
    assert "is not filtered by any of them" in text


# --- Runs -----------------------------------------------------------------------------------------


def test_the_runs_filter_bar_offers_machines_and_models_as_selects(tmp_path: Path) -> None:
    """A fingerprint is not a name anyone types, and the page was asking for one in a text box."""
    console, _database = freeweight_console(tmp_path, state="active")
    machine = fixture("machine")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/runs")
    assert f'<option value="{machine["machine_fingerprint"]}"' in text
    assert ">Jordan-main</option>" in text
    assert f'<option value="{CANONICAL}"' in text


def test_a_machine_being_filtered_by_that_freeweight_no_longer_lists_stays_an_option(
    tmp_path: Path,
) -> None:
    """Otherwise applying a second filter silently drops the first."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/runs?machine=retired")
    assert '<option value="retired" selected>retired</option>' in text


# --- Compare --------------------------------------------------------------------------------------


def test_the_model_picker_joins_its_ticks_into_the_subject_list(tmp_path: Path) -> None:
    """Two ways in — the free-text box and the checkboxes — one list FreeWeight is asked for."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = gate_b_api(router)
        text = page(
            console, f"{BASE}/results/compare?subjects={RUN}&subject={CANONICAL}&subject={RUN}"
        )
    sent = routes["results/compare"].calls.last.request.url.params["subjects"]
    # The typed subject first, the ticked ones after it, and no duplicate.
    assert sent == f"{RUN},{CANONICAL}"
    assert f'name="subject" value="{CANONICAL}" checked' in text


def test_a_mergeable_metric_is_drawn_and_a_separated_one_never_is(tmp_path: Path) -> None:
    """A bar chart *is* a comparison, so FreeWeight's own refusal to merge decides what is drawn."""
    console, _database = freeweight_console(tmp_path, state="active")
    comparison = copy.deepcopy(fixture("compare"))
    mergeable = comparison["metrics"][0]
    mergeable["mergeable"] = True
    separated = comparison["metrics"][1]["metric_key"]
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router, bodies={"results/compare": comparison})
        text = page(
            console,
            f"{BASE}/results/compare?subjects={RUN},{OTHER_RUN}"
            f"&metric={mergeable['metric_key']}&metric={separated}",
        )
    assert "data-echarts=" in text
    assert f"<figcaption>{mergeable['metric_key']}</figcaption>" in text
    assert f"<figcaption>{separated}</figcaption>" not in text
    anchor = f'type="checkbox" name="metric" value="{separated}"'
    checkbox = text[text.index(anchor) :][:140]
    assert "disabled" in checkbox


def test_charting_needs_no_second_comparison_and_echarts_is_asked_for(tmp_path: Path) -> None:
    """The page opts into ECharts (ADR-0142) only where it draws something."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        text = page(console, f"{BASE}/results/compare?subjects={RUN},{OTHER_RUN}")
    assert "echarts" in text


def test_a_metric_with_no_value_in_any_cell_draws_nothing_rather_than_zeroes(
    tmp_path: Path,
) -> None:
    """ADR-0016: a figure nobody could measure is absent from the series, never a bar at zero."""
    console, _database = freeweight_console(tmp_path, state="active")
    comparison = copy.deepcopy(fixture("compare"))
    row = comparison["metrics"][0]
    row["mergeable"] = True
    for cell in row["cells"]:
        cell["value"] = "unsupported"
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router, bodies={"results/compare": comparison})
        text = page(
            console,
            f"{BASE}/results/compare?subjects={RUN},{OTHER_RUN}&metric={row['metric_key']}",
        )
    assert "data-echarts=" not in text
    assert "Nothing to draw" in text


# --- Machines -------------------------------------------------------------------------------------


def test_a_machine_can_be_named_from_its_page_and_the_write_is_audited(tmp_path: Path) -> None:
    """One `PATCH`, one audit row, and back to the page (row WX7)."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        route = route_for(router, "PATCH", f"machines/{MACHINE}").mock(
            return_value=httpx.Response(200, json={"id": MACHINE, "nickname": "the workstation"})
        )
        response = post(
            console, f"{BASE}/machines/{MACHINE}/nickname", {"nickname": "the workstation"}
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/machines/{MACHINE}"
    assert route.calls.last.request.read() == b'{"nickname":"the workstation"}'
    (row,) = audit(console, "freeweight.machine_nickname")
    assert (row["outcome"], row["target"], row["security"]) == ("ok", MACHINE, False)


def test_clearing_the_name_sends_null_not_a_blank(tmp_path: Path) -> None:
    """A machine named with spaces is a machine nobody named."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        route = route_for(router, "PATCH", f"machines/{MACHINE}").mock(
            return_value=httpx.Response(200, json={"id": MACHINE, "nickname": None})
        )
        post(console, f"{BASE}/machines/{MACHINE}/nickname", {"nickname": "   "})
    assert route.calls.last.request.read() == b'{"nickname":null}'


def test_freeweights_refusal_of_a_name_renders_on_the_page_and_is_audited(tmp_path: Path) -> None:
    """A refusal is FreeWeight's, in its own words, and the page it was asked from comes back."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        route_for(router, "PATCH", f"machines/{MACHINE}").mock(
            return_value=httpx.Response(
                404,
                json={
                    "error": {
                        "code": "NOT_FOUND",
                        "message": "No machine has that id.",
                        "details": {},
                    }
                },
            )
        )
        response = post(console, f"{BASE}/machines/{MACHINE}/nickname", {"nickname": "x"})
    assert response.status_code == 200
    assert "No machine has that id." in response.text
    (row,) = audit(console, "freeweight.machine_nickname")
    assert row["outcome"] == "refused"


def test_a_stopped_freeweight_does_not_offer_the_name_form(tmp_path: Path) -> None:
    """Naming is a write, and the database path is read-only (spec §7.3)."""
    console, database = freeweight_console(tmp_path, state="inactive")
    from tests.support import fill_rows

    fill_rows(
        database,
        "machines",
        [{"id": MACHINE, "machine_fingerprint": "f" * 64, "hostname": "offline"}],
    )
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        text = page(console, f"{BASE}/machines/{MACHINE}")
    assert "not offered while FreeWeight is stopped" in text
    assert 'name="nickname"' not in text


def test_the_machines_list_names_each_one_and_keeps_the_fingerprint(tmp_path: Path) -> None:
    """A nickname identifies nothing: the fingerprint is what a figure is attributed to."""
    console, _database = freeweight_console(tmp_path, state="active")
    machine = fixture("machine")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        text = page(console, f"{BASE}/machines")
    assert ">Jordan-main</a>" in text
    assert machine["machine_fingerprint"] in text


def test_every_page_this_row_touches_carries_the_app_page_header(tmp_path: Path) -> None:
    """Row WX3's header macro, on each of the four (and the machines list beside them)."""
    console, _database = freeweight_console(tmp_path, state="active")
    paths = ["models", "runs", "results/compare", "machines", f"machines/{MACHINE}"]
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        pages: dict[str, Any] = {one: page(console, f"{BASE}/{one}") for one in paths}
    for path, text in pages.items():
        assert 'class="app-page-eyebrow"' in text, path
        assert "FreeWeight /" in text, path

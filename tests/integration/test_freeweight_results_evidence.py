"""Row WP3 Gate B: FreeWeight's Results (with Compare and Export), Evidence and Machines pages.

The recordings under ``tests/fixtures/freeweight`` are the reference machine's FreeWeight 1.2.1 on
2026-09-10 (see ``test_freeweight_pages``). The export and the bundle are proxied as they stream, a
refusal arriving before the first byte and rendering on the page it was asked from.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import mirrorwall
import pytest
import respx

from tests.integration.test_freeweight_pages import (
    API,
    BASE,
    CANONICAL,
    FIXTURES,
    RUN,
    fixture,
    freeweight_console,
    mock_api,
    page,
    route_for,
)
from tests.security.test_chat_isolation import HOSTILE, _assert_inert
from tests.support import fill_rows

OTHER_RUN = "01M22D3SAJ5KE8XZ3H4NWVWZB8"
MEMORY_RUN = "01M22J6XV0XES89J17QPATK89Q"
MACHINE = "01M1B9PNA4BK4TEJ3T5EQTFQS4"

_COMPONENTS = (
    Path(mirrorwall.__file__).parent / "templates" / "mirrorwall" / "components.html"
).read_text(encoding="utf-8")
_TABLE_SUPPORTS_HIDDEN_COLUMNS = "data-default-hidden" in _COMPONENTS
"""Row WY5's ``table()`` macro is what turns a column's ``"hidden": true`` head entry into
``data-default-hidden="true"``; until that row's branch merges, this MirrorWall renders every
column, which the roadmap (§2.2) says is expected. The two tests below skip themselves rather
than fail against a dependency that has not landed, and start asserting the real markup the day
WY10 installs a MirrorWall that has WY5 in it."""


def gate_b_api(
    router: Any,  # noqa: ANN401 — a respx router
    *,
    bodies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Gate A's recorded reads, and the Results, Evidence and Machines recordings beside them."""
    recorded = {
        "results": fixture("results"),
        "results/compare": fixture("compare"),
        "evidence": fixture("evidence"),
        "machines": fixture("machines"),
        f"machines/{MACHINE}": fixture("machine"),
    }
    recorded.update(bodies or {})
    return mock_api(router, bodies=recorded)


# --- Results --------------------------------------------------------------------------------------


def test_results_read_freeweights_metric_query_with_every_filter_and_its_cursor(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    results = fixture("results")
    cursor = results["page"]["next_cursor"]
    with respx.mock(assert_all_called=False) as router:
        routes = gate_b_api(router)
        text = page(
            console,
            f"{BASE}/results?model=m&suite=native.performance&metric_key=ttft_ms&machine=abc"
            "&runtime_hash=sha256:p&adapter=terse&since=2026-09-01T00:00:00Z&status=any",
        )
    assert results["items"][0]["metric_key"] in text
    assert f'href="{BASE}/runs/{RUN}' in text
    assert f'href="{BASE}/machines?fingerprint=' in text
    assert "runtime_hash=sha256%3Ap" in text and f"cursor={cursor}" in text  # the pager keeps them
    params = routes["results"].calls.last.request.url.params
    assert params["runtime_profile"] == "sha256:p"
    assert (params["adapter"], params["status"], params["metric_key"]) == (
        "terse",
        "any",
        "ttft_ms",
    )
    assert 'action="/apps/freeweight/results/export"' in text
    assert 'action="/apps/freeweight/results/compare"' in text


def test_results_names_the_model_rather_than_its_full_canonical_id(tmp_path: Path) -> None:
    """Row WY8: the Model column is the provider name; the full ID is the cell's title."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        text = page(console, f"{BASE}/results")
    assert ">smollm2:135m<" in text
    assert f'title="{CANONICAL}"' in text
    assert ">Compare<" in text and ">Machines<" in text  # the page bar, not the left menu


@pytest.mark.skipif(
    not _TABLE_SUPPORTS_HIDDEN_COLUMNS,
    reason="needs WY5's table() macro (data-default-hidden); this MirrorWall predates it",
)
def test_results_hides_runtime_profile_and_machine_by_default(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        text = page(console, f"{BASE}/results")
    assert '<th scope="col" data-default-hidden="true">Machine</th>' in text
    assert '<th scope="col" data-default-hidden="true">Runtime profile</th>' in text


def test_compare_renders_each_verdict_its_reason_and_the_fields_that_separate(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    comparison = fixture("compare")
    with respx.mock(assert_all_called=False) as router:
        routes = gate_b_api(router)
        text = page(
            console, f"{BASE}/results/compare?subjects={RUN},{OTHER_RUN}&suite=native.performance"
        )
    params = routes["results/compare"].calls.last.request.url.params
    assert params["subjects"] == f"{RUN},{OTHER_RUN}"
    assert params["suite"] == "native.performance"
    separation = comparison["separations"][0]
    assert separation["comparability"] in text
    assert "Different identities and no shared model family" in text
    assert separation["fingerprint_diff"][0]["path"] in text
    assert comparison["metrics"][0]["metric_key"] in text


def test_a_refused_comparison_states_its_reason_and_names_the_offending_run(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        route_for(router, "GET", "results/compare").mock(
            return_value=httpx.Response(400, json=fixture("compare-refused"))
        )
        text = page(
            console,
            f"{BASE}/results/compare?subjects={RUN},{MEMORY_RUN}&suite=native.performance",
        )
    assert "COMPARISON_REFUSED" in text
    assert "Every subject must be a run of" in text
    assert f'href="{BASE}/runs/{MEMORY_RUN}"' in text
    assert "native.memory_kv" in text


def test_compare_with_no_subjects_asks_rather_than_calling_freeweight(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = gate_b_api(router)
        text = page(console, f"{BASE}/results/compare")
    assert "Name two or more runs" in text
    assert not routes["results/compare"].called


def test_labels_on_a_comparison_render_inert(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    comparison = copy.deepcopy(fixture("compare"))
    comparison["subjects"][0]["label"] = HOSTILE
    comparison["separations"][0]["reason"] = HOSTILE
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router, bodies={"results/compare": comparison})
        text = page(console, f"{BASE}/results/compare?subjects={RUN},{OTHER_RUN}")
    _assert_inert(text)


def test_the_export_streams_through_with_freeweights_headers_and_every_option(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    chunks = [b"run_id,metric_key,value\n", b"01M26MTEM1SGTMWVB3PR6EXY8F,ttft_ms,12.5\n"]
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        route = route_for(router, "GET", "results/export").mock(
            return_value=httpx.Response(
                200,
                headers={
                    "content-type": "text/csv; charset=utf-8",
                    "content-disposition": 'attachment; filename="freeweight-run.csv"',
                },
                content=iter(chunks),
            )
        )
        response = console.client.get(
            f"{BASE}/results/export?format=csv&scope=run&selector={RUN}&include_samples=true"
            "&include_prompts=true&include_prompt_text=true&since=2026-09-01T00:00:00Z"
            "&until=2026-10-01T00:00:00Z"
        )
    assert response.status_code == 200
    assert response.content == b"".join(chunks)
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="freeweight-run.csv"'
    assert dict(route.calls.last.request.url.params) == {
        "format": "csv",
        "scope": "run",
        "selector": RUN,
        "include_samples": "true",
        "include_prompts": "true",
        "include_prompt_text": "true",
        "since": "2026-09-01T00:00:00Z",
        "until": "2026-10-01T00:00:00Z",
    }


def test_the_export_leaves_unticked_options_to_freeweights_defaults(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        route = route_for(router, "GET", "results/export").mock(
            return_value=httpx.Response(200, json={"schema": "freeweight.export"})
        )
        console.client.get(f"{BASE}/results/export?format=json&scope=all&selector=")
    assert dict(route.calls.last.request.url.params) == {"format": "json", "scope": "all"}


def test_the_500_run_refusal_renders_as_itself_on_the_results_page(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    refusal = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "That selection covers 612 runs; the limit is 500. Narrow it with since and "
            "until, which tile without overlapping.",
            "details": {"matched": 612, "limit": 500},
        }
    }
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        route_for(router, "GET", "results/export").mock(
            return_value=httpx.Response(400, json=refusal)
        )
        response = console.client.get(f"{BASE}/results/export?format=jsonl&scope=all")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "VALIDATION_ERROR" in response.text
    assert "That selection covers 612 runs; the limit is 500." in response.text
    assert '<option value="jsonl" selected>' in response.text


# --- Evidence -------------------------------------------------------------------------------------


def test_evidence_shows_each_record_and_a_user_records_goal_jury_and_calibration(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    evidence = copy.deepcopy(fixture("evidence"))
    goal = evidence["items"][0]["payload"]
    goal.update(
        {
            "capability_id": "user.house_voice",
            "goal_hash": "sha256:goalgoalgoal",
            "judge_set": {"jurors": ["ollama/judge-a:latest"], "set_hash": "sha256:jury"},
            "calibration": {"kappa_w": 0.71, "n_holdout": 6, "graded_by": "jordan"},
            "judge_validity_factor": 0.83,
            "score_method_mix": {"rule": 0.25, "judge": 0.75},
        }
    )
    # FreeWeight's own reading of the record now, beside the envelopes (api.md §6, row WP4).
    evidence["explanations"] = [
        {
            "capability_id": "user.house_voice",
            "staleness": {
                "stale": True, "freshness_factor": 0.3, "age_days": 400.0, "drift": [],
                "reasons": ["measured 400 days ago; freshness 0.30 is below 0.50."],
            },
            "confidence_factors": {
                "sample_factor": 0.9, "consistency_factor": 0.8, "freshness_factor": 0.3,
                "environment_factor": 1.0, "identity_factor": 1.0, "judge_validity_factor": 0.83,
                "confidence": 0.1793,
            },
        }
    ]  # fmt: skip
    with respx.mock(assert_all_called=False) as router:
        routes = gate_b_api(router, bodies={"evidence": evidence})
        text = page(console, f"{BASE}/evidence?capability=user.house_voice&min_confidence=0.2")
    assert "user.house_voice" in text
    assert "sha256:goalgoalgoal" in text
    assert "κw 0.71 over 6 held-out samples, graded by jordan" in text
    assert "0.83" in text
    assert "ollama/judge-a:latest" in text
    assert "rule 0.25" in text
    params = routes["evidence"].calls.last.request.url.params
    assert (params["capability"], params["min_confidence"]) == ("user.house_voice", "0.2")
    assert "are not on its API" not in text
    assert ">stale<" in text
    assert "measured 400 days ago; freshness 0.30 is below 0.50." in text
    assert "consistency_factor" in text and "0.800" in text and "0.179" in text


def test_evidence_names_the_model_rather_than_its_full_canonical_id(tmp_path: Path) -> None:
    """Row WY8: the Subject column is the provider name (+ adapter, if any); the full ID and the
    adapter are the cell's title.
    """
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        text = page(console, f"{BASE}/evidence")
    subject = fixture("evidence")["items"][0]["payload"]["model"]["canonical_id"]
    name = subject.rpartition("@")[0].partition("/")[2]
    assert f">{name}<" in text
    assert f'title="{subject}"' in text
    assert ">LoadCoach&#39;s import<" in text  # the page bar's action, Results removed as a dupe


@pytest.mark.skipif(
    not _TABLE_SUPPORTS_HIDDEN_COLUMNS,
    reason="needs WY5's table() macro (data-default-hidden); this MirrorWall predates it",
)
def test_evidence_hides_runtime_profile_and_machine_by_default(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        text = page(console, f"{BASE}/evidence")
    assert '<th scope="col" data-default-hidden="true">Machine</th>' in text
    assert '<th scope="col" data-default-hidden="true">Runtime profile</th>' in text


def test_the_evidence_bundle_downloads_with_the_pages_filters(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    bundle = b'{"schema":"benchmark.evidence_bundle","payload":{"complete":false}}'
    with respx.mock(assert_all_called=False) as router:
        gate_b_api(router)
        route = route_for(router, "GET", "evidence/export").mock(
            return_value=httpx.Response(
                200,
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "content-disposition": 'attachment; filename="freeweight-evidence.json"',
                },
                content=bundle,
            )
        )
        response = console.client.get(
            f"{BASE}/evidence/export?since=2026-09-10T00:00:00Z&capability=tool_use&model="
        )
    assert response.content == bundle
    assert "freeweight-evidence.json" in response.headers["content-disposition"]
    assert dict(route.calls.last.request.url.params) == {
        "since": "2026-09-10T00:00:00Z",
        "capability": "tool_use",
    }


# --- Machines -------------------------------------------------------------------------------------


def test_machines_list_and_one_machine_with_the_runs_measured_on_it(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    machine = fixture("machine")
    with respx.mock(assert_all_called=False) as router:
        routes = gate_b_api(router)
        listing = page(console, f"{BASE}/machines?fingerprint={machine['machine_fingerprint']}")
        one = page(console, f"{BASE}/machines/{MACHINE}")
    assert f'href="{BASE}/machines/{MACHINE}"' in listing
    assert machine["hostname"] in one
    assert routes["runs"].calls.last.request.url.params["machine"] == machine["machine_fingerprint"]
    assert f'href="{BASE}/runs/{RUN}"' in one


# --- Stopped --------------------------------------------------------------------------------------


def test_stopped_results_evidence_and_compare_say_they_read_only_from_the_api(
    tmp_path: Path,
) -> None:
    console, database = freeweight_console(tmp_path, state="inactive")
    fill_rows(
        database,
        "machines",
        [
            {
                "id": "01STOPPEDMACHINE000000000A",
                "machine_fingerprint": "a" * 64,
                "hostname": "recorded-host",
                "first_seen_at": "2026-09-10 00:00:00",
                "last_seen_at": "2026-09-10 00:00:00",
            }
        ],
    )
    for path in ("results", "evidence", f"results/compare?subjects={RUN},{OTHER_RUN}"):
        text = page(console, f"{BASE}/{path}")
        assert "reads only from its running API" in text, path
    machines = page(console, f"{BASE}/machines")
    assert "recorded-host" in machines
    assert "From the database at revision 0010" in machines
    one = page(console, f"{BASE}/machines/01STOPPEDMACHINE000000000A")
    assert "recorded-host" in one
    # A stopped FreeWeight is not called for a download: respx refuses any request made here, so a
    # call to whatever answers on FreeWeight's port would fail the test rather than pass it.
    with respx.mock(assert_all_called=False):
        refused = console.client.get(f"{BASE}/results/export?format=csv")
        bundle = console.client.get(f"{BASE}/evidence/export?capability=tool_use")
    for response in (refused, bundle):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "APP_UNREACHABLE" in response.text
        assert "a download is read only from its running API" in response.text


def test_fixtures_are_the_recorded_documents() -> None:
    """The recordings stay parseable and name the runs these tests address."""
    assert json.loads((FIXTURES / "compare.json").read_text())["subjects"][0]["run_id"] == RUN
    assert API.endswith("/api/v1")

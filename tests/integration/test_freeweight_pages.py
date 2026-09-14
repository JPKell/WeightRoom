"""Row WP3 Gate A: FreeWeight's Models and Runs pages, one run, its samples, and what they act on.

The recordings under ``tests/fixtures/freeweight`` are the reference machine's own FreeWeight 1.2.1
answering on 2026-09-10, after the row's API commit (FreeWeight ``989e5a7``) and a restart; the
telemetry series is cut to its first 40 observations. The stopped half reads a copy of the
committed ``freeweight-0010`` fixture database with rows added per test.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import httpx
import respx

from tests.security.test_chat_isolation import HOSTILE, _assert_inert
from tests.support import (
    FREEWEIGHT_URL,
    Console,
    build_console,
    fake_application,
    fill_rows,
    fixture_database,
    mock_freeweight,
)
from weightroom.services.apps import AppState
from weightroom.services.jobs import claim_next, get_job, set_output
from weightroom.services.processes import FakeSystemdController

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "freeweight"
HTML = {"Accept": "text/html"}
BASE = "/apps/freeweight"
API = f"{FREEWEIGHT_URL}/api/v1"
RUN = "01M26MTEM1SGTMWVB3PR6EXY8F"
MODEL = "01M26MN12V1DGS767ENPN75HMB"
TEST = "01M26MTJ1SAQDDVHR4ESBYCBX2"
SAMPLE = "01M26MTM5XS87ZJPG7PE51BQVH"
MACHINE = "01M1B9PNA4BK4TEJ3T5EQTFQS4"
CANONICAL = "ollama/smollm2:135m@sha256:9077fe9d2ae1"

STOPPED_MODEL = "01STOPPEDMODEL00000000000A"
STOPPED_RUN = "01STOPPEDRUN0000000000000A"
STOPPED_TEST = "01STOPPEDTEST000000000000A"
STOPPED_SAMPLE = "01STOPPEDSAMPLE0000000000A"


def fixture(name: str) -> Any:  # noqa: ANN401 — a recorded JSON document
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def freeweight_console(tmp_path: Path, *, state: AppState) -> tuple[Console, Path]:
    """A console with FreeWeight installed in ``state``, its database a copy of the fixture."""
    database = fixture_database(tmp_path, "freeweight-0010")
    executable, _config, _document = fake_application(
        tmp_path, "freeweight", database_url=f"sqlite:///{database}"
    )
    console = build_console(
        tmp_path / "console",
        extra_toml=(
            f'[apps.freeweight]\nexecutable = "{executable}"\nbase_url = "{FREEWEIGHT_URL}"\n'
        ),
        systemd=FakeSystemdController(states={"freeweight.service": state}),
    )
    console.login()
    return console, database


def route_for(router: Any, method: str, path: str) -> Any:  # noqa: ANN401 — a respx router
    """A route matching ``path`` under ``/api/v1`` whatever its query string."""
    return router.request(method, url__regex=rf"^{re.escape(API)}/{re.escape(path)}(\?.*)?$")


def mock_api(
    router: Any,  # noqa: ANN401 — a respx router
    *,
    bodies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """FreeWeight's recorded reads, by path under ``/api/v1``; ``bodies`` replaces or adds some."""
    mock_freeweight(router)
    recorded: dict[str, Any] = {
        "models": fixture("models"),
        f"models/{MODEL}": fixture("model"),
        f"models/{MODEL}/results": fixture("model-results"),
        "evidence": fixture("model-evidence"),
        "benchmarks": fixture("benchmarks"),
        # The Runs page's Start form offers an adapter where one can be served (row WPF2); the
        # recording is the reference machine's, which had no adapter directory configured.
        "adapters": fixture("adapters"),
        # The Runs page's Machine filter is a select over FreeWeight's own machines (row WX7).
        "machines": fixture("machines"),
        # The Overview carries the dashboard since row WX8, and a refused start renders there.
        "dashboard": fixture("dashboard"),
        f"machines/{MACHINE}": fixture("machine"),
        "runs": fixture("runs"),
        f"runs/{RUN}": fixture("run"),
        f"runs/{RUN}/telemetry": fixture("run-telemetry"),
        f"runs/{RUN}/tests/{TEST}/samples": fixture("samples"),
        f"samples/{SAMPLE}": fixture("sample"),
    }
    recorded.update(bodies or {})
    return {
        path: route_for(router, "GET", path).mock(return_value=httpx.Response(200, json=body))
        for path, body in recorded.items()
    }


def page(console: Console, path: str) -> str:
    response = console.client.get(path, headers=HTML)
    assert response.status_code == 200, response.text
    return str(response.text)


def post(console: Console, path: str, data: dict[str, Any]) -> httpx.Response:
    token = console.csrf_token()
    response: httpx.Response = console.client.post(
        path, data={**data, "csrf_token": token}, headers=HTML, follow_redirects=False
    )
    return response


def audit(console: Console, action: str) -> list[dict[str, Any]]:
    listing = console.client.get(
        "/api/v1/audit",
        params={"limit": "200"},
        headers={"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"},
    )
    return [row for row in listing.json()["items"] if row["action"] == action]


def _refusal(code: str, message: str, details: dict[str, Any], status: int) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": code, "message": message, "details": details}}
    )


# --- Models ---------------------------------------------------------------------------------------


def test_the_models_page_reads_freeweight_and_offers_refresh_and_the_switch(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        text = page(console, f"{BASE}/models?has_results=true&sort=-canonical_id")
    assert CANONICAL in text
    assert f'href="{BASE}/models/{MODEL}"' in text
    assert f'action="{BASE}/models/discover"' in text
    assert f'action="{BASE}/models/{MODEL}/enabled"' in text
    assert f'<a href="{BASE}/models" aria-current="page">Models</a>' in text
    assert "From the API" in text
    params = routes["models"].calls.last.request.url.params
    assert (params["has_results"], params["sort"]) == ("true", "-canonical_id")


def test_the_models_page_has_no_canonical_id_column(tmp_path: Path) -> None:
    """Row WY8: the model's link already carries the canonical ID as its title; a second column
    repeating it in full was the operator's complaint.
    """
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/models")
    assert ">Canonical ID<" not in text
    assert CANONICAL in text  # still the model link's title — the identity is one hover away


def test_refresh_shows_freeweights_counts_and_writes_one_audit_row(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    counts = {"added": 1, "updated": 2, "unchanged": 13, "total": 16}
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route_for(router, "POST", "models/discover").mock(
            return_value=httpx.Response(200, json=counts)
        )
        response = post(console, f"{BASE}/models/discover", {})
    assert response.status_code == 200
    assert "1 added, 2 updated," in response.text
    assert "13 unchanged, 16 in all" in response.text
    (row,) = audit(console, "freeweight.discover")
    assert row["outcome"] == "ok"


def test_a_refresh_slower_than_the_timeout_is_pending_not_freeweights_refusal(
    tmp_path: Path,
) -> None:
    """WP6 finding 3: *Refresh from provider* was audited ``refused`` after the console stopped
    waiting, while FreeWeight carried on hashing 195 GB and stored 27 models four minutes later.

    A timeout is what the console did, not what FreeWeight said: the row is ``pending`` and the
    page says the work may still be running.
    """
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route_for(router, "POST", "models/discover").mock(
            side_effect=httpx.ReadTimeout("timed out")
        )
        response = post(console, f"{BASE}/models/discover", {})
    assert response.status_code == 200
    assert "work may still be running" in response.text
    (row,) = audit(console, "freeweight.discover")
    assert row["outcome"] == "pending"


def test_freeweights_own_refusal_of_a_refresh_is_still_refused(tmp_path: Path) -> None:
    """The other half of finding 3: an answer FreeWeight sent stays FreeWeight's refusal."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route_for(router, "POST", "models/discover").mock(
            return_value=_refusal("PROVIDER_UNAVAILABLE", "The provider did not answer.", {}, 503)
        )
        response = post(console, f"{BASE}/models/discover", {})
    assert response.status_code == 200
    (row,) = audit(console, "freeweight.discover")
    assert row["outcome"] == "refused"


def test_disable_is_the_catalogs_call_with_a_json_body_and_returns_to_the_page(
    tmp_path: Path,
) -> None:
    """W8's catalog switch sent JSON to a FreeWeight route that did not exist until this row."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route = route_for(router, "POST", f"models/{MODEL}/enabled").mock(
            return_value=httpx.Response(200, json={"canonical_id": CANONICAL, "enabled": False})
        )
        response = post(
            console,
            f"{BASE}/models/{MODEL}/enabled",
            {"enabled": "false", "canonical_id": CANONICAL, "next": f"{BASE}/models"},
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/models"
    assert json.loads(route.calls.last.request.content) == {"enabled": False}
    (row,) = audit(console, "catalog.enabled")
    assert row["outcome"] == "ok"


def test_one_model_shows_its_descriptor_evidence_and_results_with_their_filters(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        text = page(console, f"{BASE}/models/{MODEL}?suite=native.performance")
    assert CANONICAL in text
    assert fixture("model-results")["items"][0]["metric_key"] in text
    assert routes[f"models/{MODEL}/results"].calls.last.request.url.params["suite"] == (
        "native.performance"
    )
    assert routes["evidence"].calls.last.request.url.params["model"] == MODEL
    for item in fixture("model-evidence")["items"]:
        assert item["payload"]["capability_id"] in text


# --- Runs -----------------------------------------------------------------------------------------


def test_the_runs_page_lists_runs_offers_a_start_and_passes_every_filter(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        text = page(
            console,
            f"{BASE}/runs?status=completed&label=q8&adapter=terse&machine=abc"
            "&since=2026-09-01T00:00:00Z&until=2026-10-01T00:00:00Z",
        )
    assert f'href="{BASE}/runs/{RUN}"' in text
    assert f'href="{BASE}/runs/new"' in text
    assert '<option value="native.echo"' in text
    assert f'<option value="{CANONICAL}"' in text
    params = routes["runs"].calls.last.request.url.params
    assert dict(params) | {"limit": "50"} == {
        "status": "completed",
        "label": "q8",
        "adapter": "terse",
        "machine": "abc",
        "since": "2026-09-01T00:00:00Z",
        "until": "2026-10-01T00:00:00Z",
        "limit": "50",
    }


def test_the_runs_pager_follows_freeweights_cursor_with_the_filters_kept(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    runs = fixture("runs")
    runs["page"] = {"limit": 50, "next_cursor": "eyJuZXh0IjoxfQ", "has_more": True}
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router, bodies={"runs": runs})
        text = page(console, f"{BASE}/runs?suite=native.performance")
        page(console, f"{BASE}/runs?suite=native.performance&cursor=eyJuZXh0IjoxfQ")
    assert "suite=native.performance&amp;cursor=eyJuZXh0IjoxfQ" in text
    assert routes["runs"].calls.last.request.url.params["cursor"] == "eyJuZXh0IjoxfQ"


def test_start_enqueues_the_capped_suite_run_job_and_the_page_follows_it_to_the_run(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        response = post(
            console, f"{BASE}/runs", {"model": CANONICAL, "suite": "native.echo", "label": "wp3"}
        )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"{BASE}/runs/starting/")
    job = get_job(console.database, location.rsplit("/", 1)[1])
    assert job.kind == "freeweight_suite_run"
    assert job.params == {
        "model": CANONICAL,
        "suite": "native.echo",
        "label": "wp3",
        "allow_prompt_override": False,
        "adapter": None,
        "cooldown_seconds": None,
    }
    (row,) = audit(console, "job.enqueue")
    assert row["outcome"] == "ok"

    waiting = page(console, location)
    assert 'hx-trigger="every 2s"' in waiting
    assert "native.echo" in waiting

    # The worker claims the job and its output buffer flushes while the child runs; do both here.
    assert claim_next(console.database, now=console.now, lease_seconds=60) is not None
    set_output(console.database, job.id, f'$ systemd-run --user …\n{{"run_id": "{RUN}"}}\n')
    followed = console.client.get(location, headers=HTML)
    assert followed.status_code == 303
    assert followed.headers["location"] == f"{BASE}/runs/{RUN}"
    swapped = console.client.get(location, headers={**HTML, "HX-Request": "true"})
    assert swapped.headers["hx-redirect"] == f"{BASE}/runs/{RUN}"


def test_the_start_form_offers_an_adapter_only_where_one_can_be_served(tmp_path: Path) -> None:
    """Row WPF2, decision 3 (the form moved to the Overview at WX8): the field lists what
    ``GET /adapters`` says is available *and* servable. Under a provider that cannot apply a LoRA
    the directory is inert (ADR-0140), so the field is absent rather than offering a run FreeWeight
    is bound to refuse."""
    from tests.integration.test_freeweight_adapters_provider import ADAPTERS

    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": ADAPTERS})
        servable = page(console, BASE)
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": {**ADAPTERS, "provider_can_serve": False}})
        inert = page(console, BASE)
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        off = page(console, BASE)

    assert 'name="adapter"' in servable
    assert '<option value="damaged"' in servable
    # Listed and unavailable: refused for a reason the operator fixes in the directory, not here.
    assert '<option value="retired"' not in servable
    assert 'id="fw-start-adapter"' not in inert
    assert 'id="fw-start-adapter"' not in off


def test_a_start_under_an_adapter_carries_it_into_the_jobs_parameters(tmp_path: Path) -> None:
    """The console decides nothing about compatibility: the name reaches the job, and the job
    reaches ``run start --adapter`` (tests/integration/test_job_kinds.py)."""
    from tests.integration.test_freeweight_adapters_provider import ADAPTERS

    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": ADAPTERS})
        response = post(
            console,
            f"{BASE}/runs",
            {"model": CANONICAL, "suite": "native.echo", "label": "", "adapter": "damaged"},
        )

    assert response.status_code == 303
    job = get_job(console.database, response.headers["location"].rsplit("/", 1)[1])
    assert job.params["adapter"] == "damaged"


def test_a_start_naming_an_adapter_the_console_cannot_spell_is_refused_before_the_job(
    tmp_path: Path,
) -> None:
    """The name becomes a child's argv, so it is checked against the manifest's own pattern; the
    page keeps the form and says so, and nothing is enqueued."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        response = post(
            console,
            f"{BASE}/runs",
            {"model": CANONICAL, "suite": "native.echo", "label": "", "adapter": "--fit off"},
        )

    assert response.status_code == 200
    assert "adapter" in response.text
    (row,) = audit(console, "job.enqueue")
    assert row["outcome"] == "refused"


def test_a_start_the_queue_refuses_renders_its_code_and_keeps_the_label(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        response = post(
            console, f"{BASE}/runs", {"model": CANONICAL, "suite": "not a suite", "label": "kept"}
        )
    assert response.status_code == 200
    assert "VALIDATION_ERROR" in response.text
    assert 'value="kept"' in response.text
    (row,) = audit(console, "job.enqueue")
    assert row["outcome"] == "refused"


def test_one_run_shows_its_tests_metrics_charts_and_the_live_pane(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    run = fixture("run")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/runs/{RUN}")
    assert run["tests"][0]["name"] in text
    assert f'href="{BASE}/runs/{RUN}/tests/{TEST}"' in text
    assert run["metrics"][0]["metric_key"] in text
    assert "<polyline" in text
    assert f'data-log-stream="{BASE}/runs/{RUN}/events"' in text
    assert f'action="{BASE}/runs/{RUN}/repeat"' in text
    assert f'action="{BASE}/runs/{RUN}/cancel"' not in text  # a completed run is not cancellable
    assert "MutationObserver" not in text  # nor reloaded when its stream ends


def test_a_running_run_reloads_once_its_stream_ends_to_show_its_final_figures(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    running = {**fixture("run"), "status": "running"}
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={f"runs/{RUN}": running})
        text = page(console, f"{BASE}/runs/{RUN}")
    assert f'action="{BASE}/runs/{RUN}/cancel"' in text
    assert "MutationObserver" in text
    assert 'status.textContent === "reader ended"' in text


def test_the_event_stream_keeps_freeweights_sequence_and_carries_last_event_id(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    recorded = (FIXTURES / "run-events.sse").read_bytes()
    with respx.mock(assert_all_called=False) as router:
        mock_freeweight(router)
        route = router.get(f"{API}/runs/{RUN}/events").mock(
            return_value=httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=recorded
            )
        )
        response = console.client.get(f"{BASE}/runs/{RUN}/events", headers={"Last-Event-ID": "5"})
    assert route.calls.last.request.headers["last-event-id"] == "5"
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "id: 1\nevent: log\n" in text
    assert "id: 66\nevent: log\n" in text
    assert text.count("event: log\n") == recorded.decode().count("\nevent: ")  # every frame, once
    assert text.index("run.completed") < text.index("event: log.closed")


def test_a_refused_event_stream_ends_the_pane_with_freeweights_code(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_freeweight(router)
        router.get(f"{API}/runs/01NOPE/events").mock(
            return_value=_refusal("RUN_NOT_FOUND", "No run matches '01NOPE'.", {}, 404)
        )
        text = console.client.get(f"{BASE}/runs/01NOPE/events").text
    assert "RUN_NOT_FOUND" in text
    assert "event: log.closed" in text


def test_cancelling_a_finished_run_renders_run_not_cancellable_as_itself(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route_for(router, "POST", f"runs/{RUN}/cancel").mock(
            return_value=httpx.Response(409, json=fixture("cancel-refused"))
        )
        response = post(console, f"{BASE}/runs/{RUN}/cancel", {})
    assert response.status_code == 200
    assert "RUN_NOT_CANCELLABLE" in response.text
    assert "cannot be cancelled" in response.text
    (row,) = audit(console, "freeweight.run_cancel")
    assert row["outcome"] == "refused"


def test_cancelling_a_running_run_returns_to_it(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route_for(router, "POST", f"runs/{RUN}/cancel").mock(
            return_value=httpx.Response(202, json={"id": RUN, "status": "cancelling"})
        )
        response = post(console, f"{BASE}/runs/{RUN}/cancel", {})
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/runs/{RUN}"
    (row,) = audit(console, "freeweight.run_cancel")
    assert row["outcome"] == "ok"


def test_repeat_sends_force_and_label_and_opens_the_new_run(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    new = "01NEWRUN000000000000000000"
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route = route_for(router, "POST", f"runs/{RUN}/repeat").mock(
            return_value=httpx.Response(201, json={"id": new, "status": "queued"})
        )
        response = post(console, f"{BASE}/runs/{RUN}/repeat", {"force": "true", "label": "again"})
    params = route.calls.last.request.url.params
    assert (params["force"], params["label"]) == ("true", "again")
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/runs/{new}"
    (row,) = audit(console, "freeweight.run_repeat")
    assert row["outcome"] == "ok"


def test_a_refused_repeat_names_every_blocker_and_a_forced_repeats_divergence_shows(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    blocker = {
        "field": "provider.version",
        "recorded": "0.30.1",
        "observed": "0.32.13",
        "reason": "provider_version_changed",
        "explanation": "The provider was upgraded since the original run.",
    }
    forced = fixture("run")
    forced["degradations"] = [{"kind": "repeat_forced", "detail": {"divergences": [blocker]}}]
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={f"runs/{RUN}": forced})
        route_for(router, "POST", f"runs/{RUN}/repeat").mock(
            return_value=_refusal(
                "REPEAT_REFUSED",
                f"Run {RUN} cannot be repeated here: the provider was upgraded.",
                {"run": RUN, "blockers": [blocker]},
                409,
            )
        )
        response = post(console, f"{BASE}/runs/{RUN}/repeat", {"label": "again"})
    text = response.text
    assert "REPEAT_REFUSED" in text
    assert "provider.version" in text
    assert "The provider was upgraded since the original run." in text
    assert 'value="again"' in text
    assert "repeat_forced" in text
    (row,) = audit(console, "freeweight.run_repeat")
    assert row["outcome"] == "refused"


# --- Samples --------------------------------------------------------------------------------------


def test_a_tests_samples_page_by_freeweights_cursor(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    cursor = fixture("samples")["page"]["next_cursor"]
    path = f"runs/{RUN}/tests/{TEST}/samples"
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        text = page(console, f"{BASE}/runs/{RUN}/tests/{TEST}")
        page(console, f"{BASE}/runs/{RUN}/tests/{TEST}?cursor={cursor}")
    assert f'href="{BASE}/samples/{SAMPLE}"' in text
    assert f"?cursor={cursor}" in text
    assert routes[path].calls.last.request.url.params["cursor"] == cursor


def test_the_case_inspector_renders_model_and_juror_text_inert(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    sample = copy.deepcopy(fixture("sample"))
    sample["sample"]["response_text"] = HOSTILE
    sample["criterion_scores"] = [
        {
            "criterion_key": "tone",
            "rung": "judge",
            "raw_score": 3,
            "weight": 1.0,
            "gated": False,
            "status": "scored",
            "skip_reason": None,
            "verdicts": [
                {
                    "juror_canonical_id": "ollama/judge:latest",
                    "repetition": 1,
                    "grade": 3,
                    "pairwise_choice": None,
                    "rationale": HOSTILE,
                    "refused_reason": None,
                    "remote": False,
                }
            ],
        }
    ]
    sample["tool_calls"] = [
        {
            "turn_index": 0,
            "call_index": 0,
            "tool_name": "search",
            "expected_tool": "search",
            "schema_valid": True,
            "correct_tool": True,
            "correct_arguments": None,
            "status": "ok",
            "latency_ms": 1.5,
            "arguments": {"query": HOSTILE},
        }
    ]
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={f"samples/{SAMPLE}": sample})
        text = page(console, f"{BASE}/samples/{SAMPLE}")
    _assert_inert(text)
    assert "prompt-128" in text
    assert f'href="{BASE}/runs/{RUN}"' in text


# --- Stopped --------------------------------------------------------------------------------------


def _fill_a_recorded_run(database: Path) -> None:
    fill_rows(
        database,
        "models",
        [
            {
                "id": STOPPED_MODEL,
                "canonical_id": "ollama/recorded:latest@sha256:0123456789ab",
                "provider_kind": "ollama",
                "provider_model_name": "recorded:latest",
                "identity_confidence": "digest",
                "first_seen_at": "2026-09-10 00:00:00",
                "last_seen_at": "2026-09-10 00:00:00",
                "enabled": 1,
            }
        ],
    )
    fill_rows(
        database,
        "model_descriptors",
        [
            {
                "id": "01DESCRIPTOR",
                "model_id": STOPPED_MODEL,
                "observed_at": "2026-09-10 00:00:00",
                "family": "llama",
                "quantization": "Q4_K_M",
            }
        ],
    )
    fill_rows(database, "machines", [{"id": "01MACHINE", "machine_fingerprint": "f" * 64}])
    fill_rows(database, "runtime_profiles", [{"id": "01PROFILE", "profile_hash": "sha256:prof"}])
    fill_rows(
        database,
        "benchmark_suites",
        [
            {
                "id": "01SUITE",
                "key": "native.echo",
                "name": "Echo",
                "version": "1.0.0",
                "runner": "native",
            }
        ],
    )
    fill_rows(
        database,
        "benchmark_tests",
        [{"id": "01TESTDEF", "suite_id": "01SUITE", "key": "echo.roundtrip", "name": "Round trip"}],
    )
    fill_rows(
        database,
        "runs",
        [
            {
                "id": STOPPED_RUN,
                "machine_id": "01MACHINE",
                "model_id": STOPPED_MODEL,
                "runtime_profile_id": "01PROFILE",
                "suite_id": "01SUITE",
                "status": "completed",
                "created_at": "2026-09-10 00:00:01",
                "label": "recorded before the stop",
                "fingerprint_document_json": json.dumps({"provider": {"kind": "ollama"}}),
            }
        ],
    )
    fill_rows(
        database,
        "run_tests",
        [
            {
                "id": STOPPED_TEST,
                "run_id": STOPPED_RUN,
                "test_id": "01TESTDEF",
                "status": "completed",
                "completed_cases": 1,
                "total_cases": 1,
                "repetitions": 1,
            }
        ],
    )
    fill_rows(
        database,
        "samples",
        [
            {
                "id": STOPPED_SAMPLE,
                "run_test_id": STOPPED_TEST,
                "case_id": "case-1",
                "ordinal": 0,
                "repetition": 1,
                "status": "completed",
                "score": 1.0,
                "created_at": "2026-09-10 00:00:02",
                "response_text": HOSTILE,
            }
        ],
    )
    fill_rows(
        database,
        "metric_values",
        [
            {
                "id": "01METRIC",
                "run_id": STOPPED_RUN,
                "metric_key": "harness_roundtrip_success",
                "numeric_value": 1.0,
                "unit": "ratio",
                "aggregation": "mean",
                "higher_is_better": 1,
            },
            {
                "id": "01PERSAMPLE",
                "run_id": STOPPED_RUN,
                "sample_id": STOPPED_SAMPLE,
                "metric_key": "per_sample_only",
                "unit": "ratio",
                "aggregation": "none",
            },
        ],
    )
    fill_rows(
        database,
        "run_events",
        [
            {
                "id": "01EVENT",
                "run_id": STOPPED_RUN,
                "sequence": 1,
                "timestamp": "2026-09-10 00:00:01",
                "event_type": "run.started",
                "message": "started before the stop",
            }
        ],
    )


def test_stopped_pages_read_the_database_with_a_start_beside_them(tmp_path: Path) -> None:
    console, database = freeweight_console(tmp_path, state="inactive")
    _fill_a_recorded_run(database)

    models = page(console, f"{BASE}/models")
    assert "ollama/recorded:latest@sha256:0123456789ab" in models
    assert "From the database at revision 0010" in models
    assert f'action="{BASE}/models/{STOPPED_MODEL}/enabled"' not in models
    assert 'name="next" value="/apps/freeweight/models"' in models  # the Start form

    model = page(console, f"{BASE}/models/{STOPPED_MODEL}")
    assert "Q4_K_M" in model
    assert "read only from its running API" in model

    runs = page(console, f"{BASE}/runs")
    assert f'href="{BASE}/runs/{STOPPED_RUN}"' in runs
    assert "recorded before the stop" in runs
    assert 'id="fw-start-model"' not in runs  # the Start form is the Overview's (row WX8)

    run = page(console, f"{BASE}/runs/{STOPPED_RUN}")
    assert "Round trip" in run
    assert "harness_roundtrip_success" in run
    assert "per_sample_only" not in run  # a per-sample metric row is not an aggregate
    assert "started before the stop" in run
    assert "Repeat this run" not in run

    samples = page(console, f"{BASE}/runs/{STOPPED_RUN}/tests/{STOPPED_TEST}")
    assert f'href="{BASE}/samples/{STOPPED_SAMPLE}"' in samples

    sample = page(console, f"{BASE}/samples/{STOPPED_SAMPLE}")
    _assert_inert(sample)
    assert "FreeWeight's reconstruction" in sample


def test_a_stopped_run_nobody_recorded_renders_the_refusal_not_an_error_page(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="inactive")
    text = page(console, f"{BASE}/runs/01NOSUCHRUN")
    assert "NOT_FOUND" in text
    assert "holds no run" in text

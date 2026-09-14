"""Row WP2 Gate A: LoadCoach's Models, Routing and Reliability pages, and what they act on.

The recordings under ``tests/fixtures/loadcoach`` are the reference machine's own LoadCoach 1.5.0
answering on 2026-09-10; the stopped half reads a copy of the committed ``loadcoach-0015`` fixture
database with rows added per test.
"""

from __future__ import annotations

import json
import sqlite3
import tomllib
from pathlib import Path
from typing import Any

import httpx
import respx

from tests.support import (
    FREEWEIGHT_URL,
    JSON_HEADERS,
    LOADCOACH_URL,
    Console,
    build_console,
    fake_application,
    fill_rows,
    fixture_database,
    mock_freeweight,
    mock_loadcoach,
)
from weightroom.services.apps import AppState
from weightroom.services.processes import FakeSystemdController

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loadcoach"
FW_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "freeweight"
FW_FIXTURES_DEFAULT = json.loads((FW_FIXTURES / "context-fit.json").read_text(encoding="utf-8"))
HTML = {"Accept": "text/html"}
BASE = "/apps/loadcoach"
API = f"{LOADCOACH_URL}/api/v1"
MODEL = "01M1FAMBDX3SMZN4R8PYTJYSE1"
CANONICAL = "ollama/deepseek-coder-v2:latest@sha256:63fb193b3a9b"
STOPPED_MODEL = "01STOPPEDMODEL00000000000A"
STOPPED_DECISION = "01STOPPEDDECISION00000000A"


def fixture(name: str) -> Any:  # noqa: ANN401 — a recorded JSON document
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def loadcoach_console(
    tmp_path: Path, *, state: AppState, revision: str | None = None, extra_toml: str = ""
) -> tuple[Console, Path]:
    """A console with LoadCoach installed in ``state``, its database a copy of the fixture."""
    database = fixture_database(tmp_path, "loadcoach-0015")
    if revision is not None:
        connection = sqlite3.connect(database)
        connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))
        connection.commit()
        connection.close()
    executable, _config, _document = fake_application(
        tmp_path, "loadcoach", database_url=f"sqlite:///{database}"
    )
    console = build_console(
        tmp_path / "console",
        extra_toml=(
            f'[apps.loadcoach]\nexecutable = "{executable}"\nbase_url = "{LOADCOACH_URL}"\n'
            + extra_toml
        ),
        systemd=FakeSystemdController(states={"loadcoach.service": state}),
    )
    console.login()
    return console, database


def mock_api(
    router: Any,  # noqa: ANN401 — a respx router
    *,
    version: str = "1.5.0",
    bodies: dict[str, Any] | None = None,
    context_fit: Any = None,  # noqa: ANN401 — a recorded JSON document
) -> dict[str, Any]:
    """LoadCoach's recorded reads, by path under ``/api/v1``; ``bodies`` replaces or adds some."""
    mock_loadcoach(router, version=version)
    decision = fixture("decision")
    recorded: dict[str, Any] = {
        "models": fixture("models"),
        f"models/{MODEL}": fixture("model"),
        "routing-decisions": fixture("routing-decisions"),
        f"routing-decisions/{decision['decision_id']}": decision,
        "task-profiles": fixture("task-profiles"),
        "task-profiles/general.chat": fixture("task-profile"),
        "reliability": fixture("reliability"),
        "evidence": fixture("evidence"),
    }
    recorded.update(bodies or {})
    routes = {
        path: router.get(f"{API}/{path}").mock(return_value=httpx.Response(200, json=body))
        for path, body in recorded.items()
    }
    # The Models page reads FreeWeight for its Context fit column (row WX9/WX7): a cross-
    # application read the console makes, not one LoadCoach makes.
    mock_freeweight(router)
    routes["results/context-fit"] = router.get(f"{FREEWEIGHT_URL}/api/v1/results/context-fit").mock(
        return_value=httpx.Response(200, json=context_fit or FW_FIXTURES_DEFAULT)
    )
    return routes


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
    listing = console.client.get("/api/v1/audit", params={"limit": "200"}, headers=JSON_HEADERS)
    return [row for row in listing.json()["items"] if row["action"] == action]


def _refusal(code: str, message: str, details: dict[str, Any], status: int) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": code, "message": message, "details": details}}
    )


# --- Reading--------------------------------------------------------------------------------------


def test_the_models_page_reads_the_registry_and_offers_its_switches(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    models = fixture("models")
    unnamed = next(one for one in models["models"] if one["model_ref"] != MODEL)
    unnamed["provider_name"] = ""
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"models": models})
        text = page(console, f"{BASE}/models")
    assert CANONICAL in text
    assert f'href="{BASE}/models/{MODEL}"' in text
    assert "not recorded" in text  # "" and false are never guessed at (api.md §2)
    assert f'action="{BASE}/models/discover"' in text
    assert f'action="{BASE}/models/{MODEL}/warm"' in text
    assert f'action="{BASE}/models/{MODEL}/enabled"' in text
    assert '<a href="/apps/loadcoach/models" aria-current="page">Models</a>' in text
    assert "From the API" in text


def test_the_models_page_names_the_model_the_registration_and_the_context_that_fits(
    tmp_path: Path,
) -> None:
    """Row WX9: the name column is the provider's own name, the registration is its own column,
    and Context fit is FreeWeight's measurement with the runtime profile it was measured under.
    """
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/models")
    assert "deepseek-coder-v2:latest</a>" in text  # provider_model_name, not the canonical id
    assert ">Registration<" in text and ">Context fit<" in text
    assert "32k" in text  # 32 768 measured tokens
    assert "runtime profile 8f2c1d4e · machine jordan-main · 118 MB per 1k context" in text
    assert "capped" in text  # the 16k row is capped by configuration, and says so


def test_a_long_model_name_is_cut_to_thirty_characters_with_the_full_name_in_title(
    tmp_path: Path,
) -> None:
    """Row WY8: 29 characters plus an ellipsis on both lines of the name cell, the full text kept
    as each line's own ``title`` so truncation never hides the identity.
    """
    console, _database = loadcoach_console(tmp_path, state="active")
    models = fixture("models")
    long_name = "a-very-long-provider-model-name-indeed-xy"  # 41 characters
    assert len(long_name) == 41
    long_canonical = f"ollama/{long_name}@sha256:0b34f914eac4"
    row = next(one for one in models["models"] if one["model_ref"] == MODEL)
    row["provider_model_name"] = long_name
    row["canonical_id"] = long_canonical
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"models": models})
        text = page(console, f"{BASE}/models")
    truncated_name = long_name[:29] + "…"
    truncated_canonical = long_canonical[:29] + "…"
    assert truncated_name in text
    assert f'title="{long_name}"' in text
    assert truncated_canonical in text
    assert f'title="{long_canonical}"' in text


def test_context_fit_is_a_dash_and_a_reason_when_freeweight_does_not_answer(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        router.get(f"{FREEWEIGHT_URL}/api/v1/results/context-fit").mock(
            side_effect=httpx.ConnectError("refused")
        )
        text = page(console, f"{BASE}/models")
    assert "Context fit is empty —" in text
    assert CANONICAL in text  # the registry is the page; the column is not


def test_an_ability_ranks_the_registry_by_its_bound_evidence(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    bound = fixture("evidence")
    bound["items"] = [
        _bound_record(CANONICAL, "structured_output", 0.42),
        _bound_record("ollama/gpt-oss:20b@sha256:17052f91a42e", "structured_output", 0.91),
    ]
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"evidence": bound})
        offered = page(console, f"{BASE}/models")
        ranked = page(console, f"{BASE}/models?ability=structured_output")
    assert '<option value="structured_output"' in offered
    assert "ranked by structured_output" in ranked
    assert ranked.index("0.910") < ranked.index("0.420")


def _bound_record(canonical: str, capability: str, score: float) -> dict[str, Any]:
    """One ``capability.evidence`` envelope as ``GET /evidence?match_state=bound`` returns it."""
    provider_kind, _, rest = canonical.partition("/")
    name = rest.split("@", 1)[0]
    return {
        "schema": "capability.evidence",
        "schema_version": "1.0",
        "payload": {
            "model": {
                "canonical_id": canonical,
                "provider_kind": provider_kind,
                "provider_model_name": name,
            },
            "capability_id": capability,
            "score": score,
            "confidence": 0.7,
            "sample_count": 40,
            "measured_at": "2026-09-09T00:00:00Z",
        },
    }


def test_one_model_shows_its_identity_reliability_and_breaker(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/models/{MODEL}")
    assert CANONICAL in text
    assert "deepseek2" in text
    assert "tools.agent.local_fast" in text
    assert "closed" in text


def test_routing_lists_decisions_and_profiles_and_a_decision_names_every_rejection(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    decision = fixture("decision")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        routing = page(console, f"{BASE}/routing")
        history = page(console, f"{BASE}/routing/decisions")
        one = page(console, f"{BASE}/routing/decisions/{decision['decision_id']}")
        profile = page(console, f"{BASE}/routing/task-profiles/general.chat")
    # Row WX9: the history is its own page, linked from the one carrying the form.
    assert f'href="{BASE}/routing/decisions"' in routing
    assert f'href="{BASE}/routing/decisions/{decision["decision_id"]}"' in history
    assert f'href="{BASE}/routing/task-profiles/general.chat"' in routing
    assert f'action="{BASE}/routing"' in routing
    assert "insufficient_vram" in one
    assert decision["selected"]["canonical_id"] in one
    assert "instruction_following" in profile


def test_reliability_shows_each_value_with_its_samples_or_why_it_is_absent(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        text = page(console, f"{BASE}/reliability?task=tools.agent.local_fast")
    assert "3 sample(s); 5 needed" in text
    assert "not evaluated" in text
    assert routes["reliability"].calls.last.request.url.params["task"] == "tools.agent.local_fast"


def test_routing_decisions_says_first_n_of_more_when_the_api_hands_back_its_own_cap(
    tmp_path: Path,
) -> None:
    """Row WX5: ``GET /routing-decisions`` takes no ``limit``, so 50 back means "more, maybe"."""
    console, _database = loadcoach_console(tmp_path, state="active")
    decisions = fixture("routing-decisions")
    assert len(decisions["decisions"]) == 50, "the fixture already is LoadCoach's own cap"
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"routing-decisions": decisions})
        history = page(console, f"{BASE}/routing/decisions")
    assert "First 50 of more" in history


def test_reliability_offers_the_lists_it_already_fetched_as_selects(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        text = page(console, f"{BASE}/reliability")
    assert '<select id="lc-rel-task" name="task">' in text
    assert '<option value="general.chat"' in text
    assert '<select id="lc-rel-model" name="model">' in text
    assert f'<option value="{CANONICAL}"' in text
    assert 'name="prefix"' in text


def test_a_prefix_matches_a_family_of_task_profiles_here_not_at_loadcoach(
    tmp_path: Path,
) -> None:
    """Row WX9: `startswith` over the pairs the page already fetched — LoadCoach's own `task`
    filter is exact, and a prefix parameter on its API for a browser control is the wrong place.
    """
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router)
        matched = page(console, f"{BASE}/reliability?prefix=tools.agent.")
        missed = page(console, f"{BASE}/reliability?prefix=nothing.starts.with.this")
    table = matched.split("<table", 1)[1].split("</table>", 1)[0]
    assert "tools.agent.local_fast" in table
    assert "general.chat" not in table
    assert "No pair on this page starts with nothing.starts.with.this" in missed
    # Nothing about the prefix reaches LoadCoach.
    assert "prefix" not in routes["reliability"].calls.last.request.url.params


def test_reliability_pages_by_ui_page_rows_and_the_next_link_walks_every_pair(
    tmp_path: Path,
) -> None:
    """Row WX5: ``[ui] page_rows`` bounds the reliability tables; ``Next`` reaches the rest."""
    console, _database = loadcoach_console(
        tmp_path, state="active", extra_toml="[ui]\npage_rows = 10\n"
    )
    reliability = fixture("reliability")
    entries = reliability["reliability"]
    assert len(entries) == 8
    grown = []
    for i in range(15):
        clone = json.loads(json.dumps(entries[i % len(entries)]))
        clone["model"]["canonical_id"] = f"ollama/clone-{i}@sha256:{i:064x}"
        clone["model"]["subject_canonical_id"] = clone["model"]["canonical_id"]
        grown.append(clone)
    reliability["reliability"] = grown
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"reliability": reliability})
        first = page(console, f"{BASE}/reliability")
        assert 'rel="next"' in first
        followed = page(console, f"{BASE}/reliability?page=2")
    for i in range(10):
        assert f"clone-{i}@" in first
    for i in range(10, 15):
        assert f"clone-{i}@" in followed
    for i in range(10):
        assert f"clone-{i}@" not in followed


def test_stopped_pages_read_the_database_with_a_start_beside_them(tmp_path: Path) -> None:
    console, database = loadcoach_console(tmp_path, state="inactive")
    recorded = "ollama/recorded-before-the-stop:latest@sha256:0123456789ab"
    fill_rows(
        database,
        "models",
        [
            {
                "id": STOPPED_MODEL,
                "canonical_id": recorded,
                "provider_kind": "ollama",
                "identity_confidence": "digest",
                "provider_name": "",
                "is_remote": 0,
                "available": 1,
                "enabled": 0,
                "declared_capabilities_json": json.dumps({"tool_use": 1.0}),
            }
        ],
    )
    fill_rows(
        database,
        "capability_evidence",
        [
            {
                "id": "01EVIDENCE",
                "model_id": STOPPED_MODEL,
                "capability_id": "reasoning_recorded",
                "match_state": "bound",
            }
        ],
    )
    explanation = {**fixture("decision"), "decision_id": STOPPED_DECISION}
    fill_rows(
        database,
        "routing_decisions",
        [
            {
                "id": STOPPED_DECISION,
                "task_profile_id": "general.chat",
                "task_profile_version": "1.0.0",
                "requested_at": "2026-09-10T00:00:00Z",
                "explanation_json": json.dumps(explanation),
                "flags_json": json.dumps(["low_evidence"]),
            }
        ],
    )
    fill_rows(
        database,
        "task_profiles",
        [
            {
                "id": "01PROFILE",
                "profile_id": "recorded.profile",
                "version": "1.0.0",
                "description": "a profile recorded before the stop",
                "weights_json": json.dumps({"reasoning": 1.0}),
                "enabled": 1,
                "updated_at": "2026-09-10T00:00:00Z",
            }
        ],
    )
    fill_rows(
        database,
        "reliability_stats",
        [
            {
                "id": "01STATS",
                "model_id": STOPPED_MODEL,
                "task_profile_id": "general.chat",
                "window": "7d",
                "attempts": 7,
                "successes": 6,
                "circuit_state": "closed",
            }
        ],
    )
    models = page(console, f"{BASE}/models")
    assert recorded in models
    assert "From the database at revision 0015" in models
    assert 'name="next" value="/apps/loadcoach/models"' in models  # the Start form
    assert "/warm" not in models  # API-only actions are off
    assert "reasoning_recorded" in page(console, f"{BASE}/models/{STOPPED_MODEL}")
    routing = page(console, f"{BASE}/routing")
    assert STOPPED_DECISION in page(console, f"{BASE}/routing/decisions")
    assert "a profile recorded before the stop" in routing
    assert f'action="{BASE}/routing"' not in routing
    assert "insufficient_vram" in page(console, f"{BASE}/routing/decisions/{STOPPED_DECISION}")
    assert "a profile recorded before the stop" in page(
        console, f"{BASE}/routing/task-profiles/recorded.profile"
    )
    reliability = page(console, f"{BASE}/reliability")
    assert recorded in reliability
    assert "read only from its running API" in reliability


def test_an_unknown_revision_degrades_each_database_page_by_name(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="inactive", revision="9999")
    for path in ("models", "routing", "reliability"):
        text = page(console, f"{BASE}/{path}")
        assert "SCHEMA_UNKNOWN" in text, path
        assert "9999" in text, path


def test_a_version_outside_the_range_reads_neither_source(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router, version="9.0.0")
        text = page(console, f"{BASE}/models")
    assert "APP_VERSION_MISMATCH" in text
    assert not routes["models"].called


# --- Acting---------------------------------------------------------------------------------------


def test_scan_posts_discover_and_shows_the_passes_counts(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    counts = {"added": 2, "updated": 15, "unavailable": 1, "total": 17, "unreachable": []}
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        discover = router.post(f"{API}/models/discover").mock(
            return_value=httpx.Response(200, json=counts)
        )
        response = post(console, f"{BASE}/models/discover", {})
    assert response.status_code == 200
    assert discover.called
    assert "Scanned: 2 added, 15 updated" in response.text
    (row,) = audit(console, "loadcoach.discover")
    assert row["outcome"] == "ok"
    assert row["params"]["added"] == 2


def test_disable_goes_through_the_catalog_call_and_returns_to_the_page(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        enabled = router.post(f"{API}/models/{MODEL}/enabled").mock(
            return_value=httpx.Response(200, json={})
        )
        response = post(
            console,
            f"{BASE}/models/{MODEL}/enabled",
            {"enabled": "false", "canonical_id": CANONICAL, "next": f"{BASE}/models/{MODEL}"},
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/models/{MODEL}"
    assert json.loads(enabled.calls.last.request.content) == {"enabled": False}
    (row,) = audit(console, "catalog.enabled")
    assert row["target"] == CANONICAL
    assert row["params"]["enabled"] is False


def test_a_slow_enable_is_audited_pending_not_refused(tmp_path: Path) -> None:
    """Row WPF11: LoadCoach may still be applying the change when the console gives up waiting —
    the same distinction WPF1 gave every other application call (``app_api.outcome_of``), now
    reused for the catalog's own ``set_enabled``."""
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        router.post(f"{API}/models/{MODEL}/enabled").mock(side_effect=httpx.ReadTimeout("slow"))
        response = post(
            console,
            f"{BASE}/models/{MODEL}/enabled",
            {"enabled": "false", "canonical_id": CANONICAL, "next": f"{BASE}/models/{MODEL}"},
        )
    assert response.status_code == 200, response.text  # the page re-renders with the notice
    (row,) = audit(console, "catalog.enabled")
    assert row["outcome"] == "pending"


def test_a_reference_that_is_not_a_ulid_is_refused_before_anything_is_sent(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        response = post(console, f"{BASE}/models/not-a-ulid/warm", {})
    assert response.status_code == 200
    assert "VALIDATION_ERROR" in response.text
    (row,) = audit(console, "loadcoach.warm")
    assert row["outcome"] == "refused"


def test_warm_opens_the_job_it_enqueued(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        router.post(f"{API}/models/{MODEL}/warm").mock(
            return_value=httpx.Response(200, json={"job_id": "01WARMJOB", "model_ref": MODEL})
        )
        response = post(console, f"{BASE}/models/{MODEL}/warm", {"canonical_id": CANONICAL})
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/queue/jobs/01WARMJOB"
    (row,) = audit(console, "loadcoach.warm")
    assert row["params"]["job_id"] == "01WARMJOB"


def test_explain_sends_the_forms_overrides_and_renders_every_candidate(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route = router.post(f"{API}/route").mock(
            return_value=httpx.Response(200, json=fixture("decision"))
        )
        response = post(
            console,
            f"{BASE}/routing",
            {
                "task": "general.chat",
                "max_output_tokens": "256",
                "model": "",
                "adapter": "",
                "context_size": "8192",
                "flash_attention": "true",
                "ignore_residency": "on",
            },
        )
    assert response.status_code == 200
    assert json.loads(route.calls.last.request.content) == {
        "task": "general.chat",
        "max_output_tokens": 256,
        "overrides": {
            "runtime_profile": {"context_size": 8192, "flash_attention": True},
            "ignore_residency": True,
        },
    }
    assert "insufficient_vram" in response.text
    (row,) = audit(console, "loadcoach.route")
    assert row["outcome"] == "ok"


def test_an_adapter_pin_refused_renders_loadcoachs_code_and_keeps_the_form(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route = router.post(f"{API}/route").mock(
            return_value=_refusal(
                "ADAPTER_NOT_FOUND",
                "no adapter named 'no-such-adapter' is registered on any provider",
                {"adapter": "no-such-adapter", "known_adapters": []},
                404,
            )
        )
        response = post(
            console, f"{BASE}/routing", {"task": "general.chat", "adapter": "no-such-adapter"}
        )
    assert json.loads(route.calls.last.request.content)["overrides"] == {
        "adapter": "no-such-adapter"
    }
    assert "ADAPTER_NOT_FOUND" in response.text
    assert 'value="no-such-adapter"' in response.text
    assert "Adapters LoadCoach holds: none." in response.text
    (row,) = audit(console, "loadcoach.route")
    assert row["outcome"] == "refused"


def test_no_eligible_model_lists_every_rejection_the_refusal_carries(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    decision = fixture("decision")
    details = {
        "decision_id": decision["decision_id"],
        "task_profile_id": "general.chat",
        "candidates": decision["rejected"],
    }
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        router.post(f"{API}/route").mock(
            return_value=_refusal("NO_ELIGIBLE_MODEL", "No model satisfied it.", details, 422)
        )
        response = post(console, f"{BASE}/routing", {"task": "general.chat"})
    assert "NO_ELIGIBLE_MODEL" in response.text
    assert "insufficient_vram" in response.text
    assert f'href="{BASE}/routing/decisions/{decision["decision_id"]}"' in response.text


def test_a_field_that_cannot_parse_is_refused_and_nothing_is_sent(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route = router.post(f"{API}/route").mock(return_value=httpx.Response(200, json={}))
        response = post(console, f"{BASE}/routing", {"task": "general.chat", "gpu_layers": "all"})
    assert "VALIDATION_ERROR" in response.text
    assert "gpu_layers must be a whole number" in response.text
    assert not route.called


def test_a_measured_context_fit_is_applied_to_loadcoachs_config_and_then_reads_applied(
    tmp_path: Path,
) -> None:
    """ADR-0149 §1: Apply writes ``[runtime.models."<id>"].context_size`` through LoadCoach's own
    validation, audits it, and the column then says the file serves the measured context."""
    console, _database = loadcoach_console(tmp_path, state="active")
    applied_title = "LoadCoach config serves this model at the measured context"
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        offered = page(console, f"{BASE}/models")
        answer = post(
            console,
            f"{BASE}/models/context-fit",
            {"canonical_id": CANONICAL, "context_tokens": "32768"},
        )
        reread = page(console, f"{BASE}/models")

    assert 'action="/apps/loadcoach/models/context-fit"' in offered
    assert applied_title not in offered
    assert answer.status_code == 200, answer.text
    written = tomllib.loads((tmp_path / "loadcoach" / "config.toml").read_text(encoding="utf-8"))
    assert written["runtime"]["models"][CANONICAL]["context_size"] == 32768
    (row,) = audit(console, "loadcoach.context_fit_applied")
    assert row["outcome"] == "ok"
    assert applied_title in reread

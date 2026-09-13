"""Row WP1 Gate B: PromptCadence's six pages — against its recorded API, and against its database.

The recordings under ``tests/fixtures/promptcadence`` are the reference machine's own PromptCadence
1.3.3 answering on 2026-09-10 for one trajectory ("State in one sentence what 2+2 is."); the stopped
half reads a copy of the committed ``promptcadence-0011`` fixture database with rows added per test.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import respx

from tests.security.test_chat_isolation import HOSTILE, _assert_inert
from tests.support import (
    CHAT_FIXTURES,
    PROMPTCADENCE_URL,
    RECORDED_TRAJECTORY,
    Console,
    build_console,
    fake_application,
    fill_rows,
    fixture_database,
)
from weightroom.services.apps import AppState
from weightroom.services.processes import FakeSystemdController
from weightroom.web.rendering import app_side_nav_stubs

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "promptcadence"
HTML = {"Accept": "text/html"}
TRAJECTORY = "01M273A83QK9QYQWVD07X8QHA4"
STOPPED = "01STOPPEDTRAJECTORY000001"
BASE = "/apps/promptcadence"


def _fixture(name: str) -> Any:  # noqa: ANN401 — a recorded JSON document
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _console(
    tmp_path: Path, *, state: AppState, revision: str | None = None
) -> tuple[Console, Path]:
    database = fixture_database(tmp_path, "promptcadence-0011")
    if revision is not None:
        connection = sqlite3.connect(database)
        connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))
        connection.commit()
        connection.close()
    executable, _config, _document = fake_application(
        tmp_path, "promptcadence", database_url=f"sqlite:///{database}"
    )
    console = build_console(
        tmp_path / "console",
        extra_toml=(
            f'[apps.promptcadence]\nexecutable = "{executable}"\nbase_url = "{PROMPTCADENCE_URL}"\n'
        ),
        systemd=FakeSystemdController(states={"promptcadence.service": state}),
    )
    console.login()
    return console, database


def _mock_api(router: Any, *, version: str = "1.3.3", **bodies: Any) -> dict[str, Any]:  # noqa: ANN401
    router.get(f"{PROMPTCADENCE_URL}/api/v1/version").mock(
        return_value=httpx.Response(
            200, json={"application": "promptcadence", "version": version, "api_version": "v1"}
        )
    )
    recorded: dict[str, Any] = {
        "trajectories": _fixture("trajectories"),
        f"trajectories/{TRAJECTORY}/explanation": _fixture("explanation"),
        "approvals": _fixture("approvals"),
        "tiers": _fixture("tiers"),
        "tools": _fixture("tools"),
        "ledger": _fixture("ledger"),
        "ledger/entries": _fixture("ledger-entries"),
        "approvals-all": _fixture("approvals-all"),
        "egress-decisions": _fixture("egress-newest"),
        "health": _fixture("health"),
        "system/status": _fixture("system-status"),
    }
    recorded.update({key.replace("__", "/"): value for key, value in bodies.items()})
    # Every request ever raised is the same path as the pending list with `status=all` (row WPC1);
    # registered first, so it wins for that query and the plain route answers the rest.
    router.get(f"{PROMPTCADENCE_URL}/api/v1/approvals", params={"status": "all"}).mock(
        return_value=httpx.Response(200, json=recorded.pop("approvals-all"))
    )
    return {
        path: router.get(f"{PROMPTCADENCE_URL}/api/v1/{path}").mock(
            return_value=httpx.Response(200, json=body)
        )
        for path, body in recorded.items()
    }


def _page(console: Console, path: str) -> str:
    response = console.client.get(path, headers=HTML)
    assert response.status_code == 200, response.text
    return str(response.text)


def test_every_promptcadence_page_is_built_and_none_is_a_stub() -> None:
    assert app_side_nav_stubs("promptcadence") == ()


def test_running_pages_read_promptcadences_api(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        listing = _page(console, f"{BASE}/trajectories")
        detail = _page(console, f"{BASE}/trajectories/{TRAJECTORY}")
        approvals = _page(console, f"{BASE}/approvals")
        tiers = _page(console, f"{BASE}/tiers")
        tools = _page(console, f"{BASE}/tools")
        ledger = _page(console, f"{BASE}/ledger")
    assert "State in one sentence what 2+2 is." in listing
    assert f'href="{BASE}/trajectories/{TRAJECTORY}"' in listing
    assert (
        '<a href="/apps/promptcadence/trajectories" aria-current="page">Trajectories</a>' in listing
    )
    assert "From the API" in listing
    assert "Drafting attempts" in detail
    assert "target_not_remote" in detail  # the egress decision the explanation holds
    assert "Every persisted event, in sequence order" in detail
    assert "data-log-stream" not in detail  # a completed trajectory has no live pane
    # Row WX11: a jump nav of the section ids, and the request as one two-column table.
    assert '<a href="#pc-plan">Plan</a>' in detail
    assert '<a href="#pc-events">Events</a>' in detail
    assert '<h3 id="pc-request">The request</h3>' in detail
    assert '<table data-table="pc-trajectory-0"' in detail
    assert "Nothing is waiting for a person." in approvals
    assert "From the database" not in approvals  # both halves read the API since row WPC1
    assert approvals.count("From the API") == 2
    assert "tools.agent.local_fast" in tiers
    assert "docker" in tools
    assert "read_file" in tools
    assert "at most 20 USD" in ledger
    assert "tier:local_fast" in ledger


def test_the_new_trajectory_page_is_its_own_route_with_the_history_new_nav(tmp_path: Path) -> None:
    """Row WX11: Trajectories splits into a History listing and a standalone New form."""
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        listing = _page(console, f"{BASE}/trajectories")
        new_page = _page(console, f"{BASE}/trajectories/new")
    assert 'name="task"' not in listing
    assert 'name="task"' in new_page
    # Row WY1: *History* was the left menu's Trajectories, so the bar carries only *New*.
    assert ">History</a>" not in listing
    assert '<a href="/apps/promptcadence/trajectories/new">New</a>' in listing
    assert '<a href="/apps/promptcadence/trajectories/new" aria-current="page">New</a>' in new_page
    # The left-menu entry stays "Trajectories" for both halves of the tab's own nav.
    assert (
        '<a href="/apps/promptcadence/trajectories" aria-current="page">Trajectories</a>'
        in new_page
    )


def test_a_stopped_promptcadences_new_page_says_nothing_can_be_submitted(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="inactive")
    page = _page(console, f"{BASE}/trajectories/new")
    assert "is not answering, so nothing can be submitted" in page
    assert 'name="task"' not in page


def test_the_tools_page_links_each_name_and_drops_the_inline_schema_dump(tmp_path: Path) -> None:
    """Row WX11: the tool name links to its own page; the per-row ``json_viewer`` dump leaves
    the list."""
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        tools = _page(console, f"{BASE}/tools")
    assert f'href="{BASE}/tools/read_file"' in tools
    assert '<a href="#pc-tools-registry">Registry</a>' in tools
    assert '<a href="#pc-tools-create">Create a tool</a>' in tools
    assert "read_file arguments" not in tools


def test_a_registered_tools_page_shows_its_argument_schema_as_a_table(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    tool_entry = _fixture("tools")["tools"][0]
    assert tool_entry["name"] == "read_file"
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        router.get(f"{PROMPTCADENCE_URL}/api/v1/tools/read_file").mock(
            return_value=httpx.Response(200, json=tool_entry)
        )
        page = _page(console, f"{BASE}/tools/read_file")
    assert tool_entry["description"] in page
    assert "read_only" in page
    assert "The file to read, relative to the workspace root or absolute." in page


def test_an_unknown_tool_name_renders_the_pages_not_found_state(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        router.get(f"{PROMPTCADENCE_URL}/api/v1/tools/rm").mock(
            return_value=httpx.Response(
                422,
                json={
                    "error": {
                        "code": "TOOL_NOT_FOUND",
                        "message": "no tool named 'rm' is configured",
                    }
                },
            )
        )
        page = _page(console, f"{BASE}/tools/rm")
    assert "No tool named rm is configured" in page
    assert "TOOL_NOT_FOUND" not in page  # the not-found state replaces the raw refusal box


def test_a_withheld_tool_is_found_and_says_why(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    withheld = {
        "name": "run_command",
        "description": "Run one command, isolated and without network.",
        "registered": False,
        "risk_class": None,
        "egress": None,
        "requires_isolation": False,
        "redact_args": False,
        "withheld_cause": "no isolation rung is available",
        "parameters": None,
    }
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        router.get(f"{PROMPTCADENCE_URL}/api/v1/tools/run_command").mock(
            return_value=httpx.Response(200, json=withheld)
        )
        page = _page(console, f"{BASE}/tools/run_command")
    assert "withheld" in page
    assert "no isolation rung is available" in page
    assert "No argument schema" in page


def test_the_ledger_pages_cursor_reaches_the_api_and_the_next_link(tmp_path: Path) -> None:
    """Row WX5: ``GET /ledger/entries`` gains a cursor, and the console's pager follows it."""
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = _mock_api(router)
        ledger = _page(console, f"{BASE}/ledger")
        first_call = routes["ledger/entries"].calls.last.request.url.params
        assert "cursor" not in first_call
        entries = _fixture("ledger-entries")
        next_cursor = entries["page"]["next_cursor"]
        assert next_cursor  # the fixture was vendored with a real cursor at row WX5
        assert f"cursor={next_cursor}" in ledger
        followed = _page(console, f"{BASE}/ledger?cursor={next_cursor}")
        second_call = routes["ledger/entries"].calls.last.request.url.params
    assert second_call["cursor"] == next_cursor
    assert "at most 20 USD" in followed


def test_the_approval_history_and_egress_read_the_api_while_promptcadence_runs(
    tmp_path: Path,
) -> None:
    console, _database = _console(tmp_path, state="active")
    history = _fixture("approvals-all")
    history["items"] = [
        {
            "request_id": "01REQUESTFROMTHEAPI000000A",
            "trajectory_id": TRAJECTORY,
            "kind": "ceiling_raise",
            "status": "granted",
            "reason": "budget_exceeded",
            "step_ids": ["s1"],
            "detail": {"scope": "trajectory", "step_id": "s1"},
            "created_at": "2026-09-10T00:00:00Z",
            "expires_at": "2026-09-10T00:15:00Z",
            "resolved_at": "2026-09-10T00:01:00Z",
            "approver_token_id": "weightroom",
            "resolution_reason": None,
            "age_seconds": 60.0,
        }
    ]
    history["page"] = {
        "limit": 50,
        "next_cursor": "history-cursor-1",
        "has_more": True,
        "total": None,
    }
    egress = _fixture("egress-newest")
    egress["page"]["next_cursor"] = "egress-cursor-1"
    egress["page"]["has_more"] = True
    with respx.mock(assert_all_called=False) as router:
        routes = _mock_api(router, **{"approvals-all": history, "egress-decisions": egress})
        approvals = _page(console, f"{BASE}/approvals")
        page = _page(console, f"{BASE}/egress?verdict=approved")
        followed_history = _page(console, f"{BASE}/approvals?cursor=history-cursor-1")
        followed_egress = _page(console, f"{BASE}/egress?verdict=approved&cursor=egress-cursor-1")
        # Row WX5: the console asks PromptCadence for every cursor it was handed back.
        history_calls = [
            call for call in router.calls if call.request.url.path == "/api/v1/approvals"
        ]
        history_cursor_sent = history_calls[-1].request.url.params["cursor"]
    assert "01REQU" in approvals and "granted" in approvals
    assert "From the database" not in approvals
    assert "cursor=history-cursor-1" in approvals
    assert history_cursor_sent == "history-cursor-1"
    sent = routes["egress-decisions"].calls[0].request.url.params
    # 50 is [ui] page_rows's default (row WX5); the console no longer asks for the LIST_CAP.
    assert (sent["sort"], sent["verdict"], sent["limit"]) == ("-decided_at", "approved", "50")
    assert "cursor=egress-cursor-1" in page
    assert routes["egress-decisions"].calls.last.request.url.params["cursor"] == "egress-cursor-1"
    first = egress["items"][0]
    assert first["decision_id"][:6] in page
    assert first["request"]["target"]["name"] in page
    assert "From the API" in page
    assert "From the database" not in page
    assert followed_history and followed_egress  # both cursor-continued requests answered 200


def test_stopped_egress_is_read_newest_first_from_the_database(tmp_path: Path) -> None:
    console, database = _console(tmp_path, state="inactive")
    fill_rows(
        database,
        "egress_decisions",
        [
            {
                "decision_id": f"01EGRESS00000000000000000{index}",
                "run_id": TRAJECTORY,
                "verdict": verdict,
                "target_name": "local_fast",
                "decided_at": f"2026-09-10T0{index}:00:00Z",
                "decision_json": json.dumps({"reason": reason, "policy_name": "Ordered"}),
            }
            for index, (verdict, reason) in enumerate(
                [("approved", "older_reason"), ("denied", "newer_reason")]
            )
        ],
    )
    page = _page(console, f"{BASE}/egress")
    denied = _page(console, f"{BASE}/egress?verdict=denied")
    assert page.index("newer_reason") < page.index("older_reason")
    assert "From the database at revision 0011" in page
    assert "newer_reason" in denied
    assert "older_reason" not in denied


def test_the_system_page_reads_health_active_work_the_position_and_recovery(
    tmp_path: Path,
) -> None:
    console, _database = _console(tmp_path, state="active")
    status = _fixture("system-status")
    status["active_trajectories"] = [
        {"trajectory_id": TRAJECTORY, "state": "executing", "lease_owner": "host:1:worker",
         "created_at": "2026-09-10T00:00:00Z"}
    ]  # fmt: skip
    status["pending_approvals"] = [
        {"request_id": "01PENDINGREQUEST000000000A", "trajectory_id": TRAJECTORY,
         "kind": "ceiling_raise", "reason": "budget_exceeded", "age_seconds": 125.4,
         "expires_at": "2026-09-10T00:15:00Z"}
    ]  # fmt: skip
    status["last_recovery"] = {
        "resumed": ["01RESUMED"], "finished": [], "halted": ["01HALTED"], "failed": [],
        "deferred": [], "touched": 2,
    }  # fmt: skip
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router, **{"system/status": status})
        text = _page(console, f"{BASE}/system")
    assert '<a href="/apps/promptcadence/system" aria-current="page">System</a>' in text
    for component in ("database", "loadcoach", "tiers", "tools"):
        assert f">{component}<" in text, component
    assert "125 s" in text
    assert "ceiling_raise" in text
    assert "01RESUMED" in text and "01HALTED" in text
    assert "at most 20 USD" in text
    assert 'href="/apps/promptcadence/tokens"' in text
    assert "From the API" in text
    nav = text.split('aria-label="Sections"', 1)[1].split("</nav>", 1)[0]
    assert nav.index("<hr>") < nav.index("System") < nav.index("Settings")


def test_a_503_health_keeps_the_status_and_names_the_refusal(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        router.get(f"{PROMPTCADENCE_URL}/api/v1/health").mock(
            return_value=httpx.Response(503, json=_fixture("health"))
        )
        text = _page(console, f"{BASE}/system")
    assert "HTTP_503" in text
    assert "Nothing is planning or executing." in text


def test_a_stopped_promptcadences_system_page_reads_only_from_its_api(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="inactive")
    assert "reads only from its running API" in _page(console, f"{BASE}/system")


def test_the_injection_corpus_renders_inert_on_the_system_page(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    health = _fixture("health")
    health["components"][0]["detail"] = HOSTILE
    status = _fixture("system-status")
    status["pending_approvals"] = [
        {"request_id": "01PENDING", "trajectory_id": TRAJECTORY, "kind": "plan", "reason": HOSTILE}
    ]
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router, health=health, **{"system/status": status})
        text = _page(console, f"{BASE}/system")
    _assert_inert(text)


def test_stopped_pages_read_the_database_with_a_start_beside_them(tmp_path: Path) -> None:
    console, database = _console(tmp_path, state="inactive")
    fill_rows(
        database,
        "trajectories",
        [
            {
                "id": STOPPED,
                "task": "a task recorded before the stop",
                "status": "completed",
                "data_classification": "internal",
                "created_at": "2026-09-10T00:00:00Z",
            }
        ],
    )
    fill_rows(
        database,
        "turns",
        [
            {
                "id": "01TURN0000000000000000001",
                "thread_id": "01THREAD",
                "trajectory_id": STOPPED,
                "sequence": 1,
                "role": "assistant",
                "content_text": "the answer read from the database",
                "created_at": "2026-09-10T00:00:01Z",
            }
        ],
    )
    fill_rows(
        database,
        "approval_requests",
        [
            {
                "id": "01REQUEST0000000000000009",
                "trajectory_id": STOPPED,
                "status": "pending",
                "kind": "plan",
                "reason": "the plan needs a person",
                "created_at": "2026-09-10T00:00:02Z",
            }
        ],
    )
    fill_rows(
        database,
        "ledger_entries",
        [
            {
                "entry_id": "01ENTRY",
                "run_id": STOPPED,
                "source_ref": "01TURN0000000000000000001",
                "occurred_at": "2026-09-10T00:00:03Z",
                "unpriced": 1,
                "debit_json": json.dumps({"usage": {"input": 5}, "tags": ["tier:recorded"]}),
            }
        ],
    )
    listing = _page(console, f"{BASE}/trajectories")
    assert "a task recorded before the stop" in listing
    assert "From the database at revision 0011" in listing
    assert 'name="next" value="/apps/promptcadence/trajectories"' in listing
    detail = _page(console, f"{BASE}/trajectories/{STOPPED}")
    assert "the answer read from the database" in detail
    assert "PromptCadence is not answering" in detail
    # Row WX11: the stopped branch's jump nav names its own (shorter) section set.
    assert '<a href="#pc-turns">Turns</a>' in detail
    assert '<a href="#pc-plan">Plan</a>' not in detail
    assert '<h3 id="pc-request">The request</h3>' in detail
    assert "the plan needs a person" in _page(console, f"{BASE}/approvals")
    ledger = _page(console, f"{BASE}/ledger")
    assert "tier:recorded" in ledger
    assert 'href="/costs"' in ledger
    for path in ("tiers", "tools"):
        assert "reads only from its running API" in _page(console, f"{BASE}/{path}")


def test_an_unknown_revision_degrades_each_database_page_by_name(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="inactive", revision="9999")
    for path in ("trajectories", "approvals", "ledger", "egress"):
        page = _page(console, f"{BASE}/{path}")
        assert "SCHEMA_UNKNOWN" in page, path
        assert "9999" in page, path


def test_a_version_outside_the_range_reads_neither_source(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = _mock_api(router, version="9.0.0")
        page = _page(console, f"{BASE}/trajectories")
    assert "APP_VERSION_MISMATCH" in page
    assert not routes["trajectories"].called


def test_a_live_trajectory_streams_as_log_frames_that_close_on_the_terminal_event(
    tmp_path: Path,
) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        router.get(f"{PROMPTCADENCE_URL}/api/v1/trajectories/{RECORDED_TRAJECTORY}/stream").mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(CHAT_FIXTURES / "promptcadence-1.3.3-completed.sse").read_bytes(),
            )
        )
        response = console.client.get(f"{BASE}/trajectories/{RECORDED_TRAJECTORY}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "event: log\n" in text
    assert "plan.drafted" in text
    assert text.index("trajectory.completed") < text.index("event: log.closed")


def test_the_injection_corpus_renders_inert_on_every_page_that_shows_model_or_operator_text(
    tmp_path: Path,
) -> None:
    explanation = copy.deepcopy(_fixture("explanation"))
    explanation["trajectory"]["task"] = HOSTILE
    explanation["trajectory"]["cause"] = HOSTILE
    explanation["threads"][0]["turns"][0]["content"]["text"] = HOSTILE
    hostile_list = {
        "items": [
            {"trajectory_id": TRAJECTORY, "task": HOSTILE, "state": "halted", "cause": HOSTILE}
        ],
        "page": {"next_cursor": None},
    }
    hostile_approvals = {
        "items": [
            {
                "request_id": "01REQUEST",
                "trajectory_id": TRAJECTORY,
                "kind": "reapproval",
                "reason": HOSTILE,
                "detail": {"why": HOSTILE},
            }
        ]
    }
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(
            router,
            trajectories=hostile_list,
            approvals=hostile_approvals,
            **{f"trajectories__{TRAJECTORY}__explanation": explanation},
        )
        listing = _page(console, f"{BASE}/trajectories")
        detail = _page(console, f"{BASE}/trajectories/{TRAJECTORY}")
        approvals = _page(console, f"{BASE}/approvals")
    _assert_inert(detail)
    for page in (listing, approvals):
        assert "<script>alert(1)</script>" not in page
        assert 'href="javascript:' not in page
        assert 'src="http://evil.example.net' not in page

"""Row WP1 Gate C: submit, cancel, grant and deny from PromptCadence's tab — one audit row each."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from tests.integration.test_promptcadence_pages import (
    BASE,
    TRAJECTORY,
    _console,
    _fixture,
    _mock_api,
)
from tests.support import (
    JSON_HEADERS,
    PROMPTCADENCE_URL,
    Console,
    build_console,
    promptcadence_token_cli,
)
from weightroom.services import chat_promptcadence
from weightroom.services.processes import FakeSystemdController

HTML = {"Accept": "text/html"}
TASK = "Summarise the open issues and draft a fix plan."


@pytest.fixture(autouse=True)
def _fresh_scope_cache() -> None:
    chat_promptcadence._SCOPE_CACHE.clear()


def _audit(console: Console, action: str) -> list[dict[str, Any]]:
    page = console.client.get("/api/v1/audit", params={"limit": "200"}, headers=JSON_HEADERS)
    return [row for row in page.json()["items"] if row["action"] == action]


def _post(console: Console, path: str, data: dict[str, Any]) -> httpx.Response:
    """A form post whose fields may repeat (``tools``), with the double-submit token."""
    token = console.csrf_token()
    response: httpx.Response = console.client.post(
        path, data={**data, "csrf_token": token}, headers=HTML, follow_redirects=False
    )
    return response


def _scoped(tmp_path: Path, scopes: list[str]) -> Console:
    executable = promptcadence_token_cli(tmp_path, scopes=scopes)
    console = build_console(
        tmp_path / "console",
        extra_toml=(
            f'[apps.promptcadence]\nexecutable = "{executable}"\nbase_url = "{PROMPTCADENCE_URL}"\n'
        ),
        systemd=FakeSystemdController(states={"promptcadence.service": "active"}),
    )
    console.login()
    return console


def test_the_form_becomes_promptcadences_body_and_opens_the_new_trajectory(
    tmp_path: Path,
) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        submit = router.post(f"{PROMPTCADENCE_URL}/api/v1/trajectories").mock(
            return_value=httpx.Response(
                202, json={"trajectory_id": "01NEWTRAJECTORY", "state": "queued"}
            )
        )
        response = _post(
            console,
            f"{BASE}/trajectories",
            {
                "task": TASK,
                "data_classification": "internal",
                "tools": ["read_file", "list_dir"],
                "tier": "",
                "max_turns": "4",
                "bypass_planning": "",
                "budget_tokens": "1000",
                "budget_money": "2.50",
                "currency": "usd",
                "partial_pricing": "strict",
            },
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/trajectories/01NEWTRAJECTORY"
    assert json.loads(submit.calls.last.request.content) == {
        "task": TASK,
        "data_classification": "internal",
        "tools": ["list_dir", "read_file"],
        "max_turns": 4,
        "budget": {
            "tokens": 1000,
            "money": {"currency": "USD", "nanos": 2_500_000_000},
            "partial_pricing": "strict",
        },
    }
    (row,) = _audit(console, "trajectory.submit")
    assert (row["outcome"], row["target"]) == ("ok", "01NEWTRAJECTORY")
    assert TASK not in json.dumps(row)  # the task is the operator's text; the trail names the id


def test_no_tool_ticked_is_an_empty_allowlist_never_an_omitted_one(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        submit = router.post(f"{PROMPTCADENCE_URL}/api/v1/trajectories").mock(
            return_value=httpx.Response(202, json={"trajectory_id": "01T", "state": "queued"})
        )
        _post(console, f"{BASE}/trajectories", {"task": TASK})
    assert json.loads(submit.calls.last.request.content)["tools"] == []


def test_a_refusal_comes_back_in_promptcadences_words_with_the_form_kept(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        router.post(f"{PROMPTCADENCE_URL}/api/v1/trajectories").mock(
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
        response = _post(console, f"{BASE}/trajectories", {"task": TASK, "tools": "rm"})
    assert response.status_code == 200
    assert "TOOL_NOT_FOUND" in response.text
    assert "no tool named &#39;rm&#39; is configured" in response.text
    assert TASK in response.text  # the operator's text survives the refusal
    # Row WX11: the refusal redisplays the standalone New page, not the History listing.
    assert (
        '<a href="/apps/promptcadence/trajectories/new" aria-current="page">New</a>'
        in response.text
    )
    assert '<section class="card pc-submit">' in response.text
    (row,) = _audit(console, "trajectory.submit")
    assert row["outcome"] == "refused"


def test_a_field_that_cannot_parse_is_refused_before_promptcadence_is_called(
    tmp_path: Path,
) -> None:
    console, _database = _console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        submit = router.post(f"{PROMPTCADENCE_URL}/api/v1/trajectories")
        response = _post(console, f"{BASE}/trajectories", {"task": TASK, "budget_money": "a lot"})
    assert "VALIDATION_ERROR" in response.text
    assert not submit.called
    assert _audit(console, "trajectory.submit")[0]["outcome"] == "refused"


def test_cancel_redirects_to_the_record_and_a_refusal_renders_on_it(tmp_path: Path) -> None:
    console, _database = _console(tmp_path, state="active")
    cancel_url = f"{PROMPTCADENCE_URL}/api/v1/trajectories/{TRAJECTORY}/cancel"
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        router.post(cancel_url).mock(
            side_effect=[
                httpx.Response(202, json={"trajectory_id": TRAJECTORY, "state": "cancelled"}),
                httpx.Response(
                    409,
                    json={
                        "error": {
                            "code": "TRAJECTORY_NOT_CANCELLABLE",
                            "message": "it is completed",
                        }
                    },
                ),
            ]
        )
        first = _post(console, f"{BASE}/trajectories/{TRAJECTORY}/cancel", {})
        second = _post(console, f"{BASE}/trajectories/{TRAJECTORY}/cancel", {})
    assert first.status_code == 303
    assert first.headers["location"] == f"{BASE}/trajectories/{TRAJECTORY}"
    assert second.status_code == 200
    assert "TRAJECTORY_NOT_CANCELLABLE" in second.text
    assert [row["outcome"] for row in _audit(console, "trajectory.cancel")] == ["refused", "ok"]


def test_a_grant_without_the_approve_scope_is_refused_before_any_call(tmp_path: Path) -> None:
    console = _scoped(tmp_path, ["read", "write"])
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        approve = router.post(f"{PROMPTCADENCE_URL}/api/v1/trajectories/{TRAJECTORY}/approve")
        response = _post(console, f"{BASE}/approvals/{TRAJECTORY}/grant", {})
    assert response.status_code == 200
    assert "no approve scope" in response.text
    assert not approve.called
    (row,) = _audit(console, "trajectory.approve")
    assert (row["outcome"], row["security"]) == ("refused", True)


def test_a_ceiling_raise_grant_sends_the_new_ceilings_and_returns_to_its_page(
    tmp_path: Path,
) -> None:
    console = _scoped(tmp_path, ["admin"])
    back = f"{BASE}/trajectories/{TRAJECTORY}"
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        approve = router.post(f"{PROMPTCADENCE_URL}/api/v1/trajectories/{TRAJECTORY}/approve").mock(
            return_value=httpx.Response(
                200,
                json={
                    "trajectory_id": TRAJECTORY,
                    "state": "executing",
                    "already_resolved": False,
                    "request": {"request_id": "01REQ", "kind": "ceiling_raise"},
                    "minted": [],
                },
            )
        )
        response = _post(
            console,
            f"{BASE}/approvals/{TRAJECTORY}/grant",
            {"budget_tokens": "5000", "budget_money": "", "currency": "USD", "next": back},
        )
    assert response.status_code == 303
    assert response.headers["location"] == back
    assert json.loads(approve.calls.last.request.content) == {"budget": {"tokens": 5000}}
    (row,) = _audit(console, "trajectory.approve")
    assert (row["outcome"], row["security"], row["target"]) == ("ok", True, TRAJECTORY)


def test_a_denial_sends_its_reason_and_next_cannot_leave_the_tab(tmp_path: Path) -> None:
    console = _scoped(tmp_path, ["approve"])
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        deny = router.post(f"{PROMPTCADENCE_URL}/api/v1/trajectories/{TRAJECTORY}/deny").mock(
            return_value=httpx.Response(200, json={"trajectory_id": TRAJECTORY, "state": "failed"})
        )
        response = _post(
            console,
            f"{BASE}/approvals/{TRAJECTORY}/deny",
            {"reason": "not today", "next": "//evil.example.net/x"},
        )
    # An off-tab `next` falls back to the Approvals page, which now says what was decided (WPF1).
    assert response.headers["location"] == f"{BASE}/approvals?done=denied"
    assert json.loads(deny.calls.last.request.content) == {"reason": "not today"}
    assert _audit(console, "trajectory.deny")[0]["outcome"] == "ok"
    landed = console.client.get(f"{BASE}/approvals?done=denied", headers={"Accept": "text/html"})
    assert "Denied. The trajectory is halted" in landed.text


def test_a_request_promptcadence_resolved_is_never_offered_for_a_decision(
    tmp_path: Path,
) -> None:
    """Row WPF3, against PromptCadence's own listings before and after the fix.

    WP6 finding 5: a cancelled trajectory's request stayed ``pending``, the console offered Grant
    and Deny on it, and PromptCadence refused both with ``APPROVAL_INVALID_STATE``. The console
    does not filter the pending list and does not guess which request is still decidable — so the
    proof is the pair: PromptCadence's pre-fix listing still renders both buttons here, and its
    recorded answer after the cancel (2026-09-11) puts the same request only in the history.
    """
    console = _scoped(tmp_path, ["admin"])
    resolved = _fixture("approvals-all")["items"][0]
    assert resolved["status"] == "expired", "the recorded answer after the cancel"
    pre_fix = {"items": [dict(resolved, status="pending", resolved_at=None,
                             resolution_reason=None)]}  # fmt: skip
    parked = resolved["trajectory_id"]
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router, approvals=pre_fix)
        before = console.client.get(f"{BASE}/approvals", headers=HTML).text
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router)
        after = console.client.get(f"{BASE}/approvals", headers=HTML).text
    assert f'action="{BASE}/approvals/{parked}/grant"' in before
    assert f'action="{BASE}/approvals/{parked}/deny"' in before
    assert f"/approvals/{parked}/grant" not in after
    assert f"/approvals/{parked}/deny" not in after
    assert "Nothing is waiting for a person." in after
    assert resolved["request_id"][:6] in after, "kept in Every request, never deleted"
    assert resolved["resolution_reason"] in after, "and it says why"


def test_the_pages_offer_the_forms_only_where_they_can_work(tmp_path: Path) -> None:
    console = _scoped(tmp_path, ["admin"])
    pending = {
        "items": [
            {"request_id": "01REQ", "trajectory_id": TRAJECTORY, "kind": "plan", "reason": "held"}
        ]
    }
    with respx.mock(assert_all_called=False) as router:
        _mock_api(router, approvals=pending)
        approvals = console.client.get(f"{BASE}/approvals", headers=HTML).text
        new_page = console.client.get(f"{BASE}/trajectories/new", headers=HTML).text
        record = console.client.get(f"{BASE}/trajectories/{TRAJECTORY}", headers=HTML).text
    assert f'action="{BASE}/approvals/{TRAJECTORY}/grant"' in approvals
    assert f'action="{BASE}/approvals/{TRAJECTORY}/deny"' in approvals
    assert 'name="tools" value="read_file"' in new_page  # the registered tools, from GET /tools
    assert '<option value="local_large"' in new_page  # the configured tiers, from GET /tiers
    assert "/cancel" not in record  # the recorded trajectory is completed
    stopped, _database = _console(tmp_path / "stopped", state="inactive")
    stopped_new = stopped.client.get(f"{BASE}/trajectories/new", headers=HTML).text
    assert "is not answering, so nothing can be submitted" in stopped_new
    assert 'name="task"' not in stopped_new

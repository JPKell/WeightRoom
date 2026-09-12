"""Row WP4 Gate A: FreeWeight's Goals page — goals, starters, drafts, edit, delete, import, export.

The recordings under ``tests/fixtures/freeweight/goals`` are FreeWeight's own application
(FreeWeight ``4090275``) answering in a scratch XDG tree over its fake provider: the starter
``creative_voice`` forked as ``wp4_voice``, ``brand_voice`` customised as a draft, and a calibration
measured by a deterministic two-juror jury through FreeWeight's own ``run_calibration``. The stopped
half reads a copy of the committed ``freeweight-0010`` fixture database with rows added per test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import respx

from tests.integration.test_freeweight_pages import (
    API,
    BASE,
    HTML,
    audit,
    freeweight_console,
    page,
    post,
    route_for,
)
from tests.security.test_chat_isolation import HOSTILE, _assert_inert
from tests.support import fill_rows, mock_freeweight

GOALS_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "freeweight" / "goals"
GOALS = f"{BASE}/goals"
SLUG = "wp4_voice"
DRAFT = "01M27T29YGG2WET5HN0SSF5C3E"


def recorded(name: str) -> Any:  # noqa: ANN401 — a recorded JSON document
    return json.loads((GOALS_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def mock_goals(router: Any, *, bodies: dict[str, Any] | None = None) -> dict[str, Any]:  # noqa: ANN401
    """FreeWeight's recorded goal reads, by path under ``/api/v1``; ``bodies`` replaces or adds."""
    mock_freeweight(router)
    reads: dict[str, Any] = {
        "goals": recorded("goals"),
        "goals/starters": recorded("starters"),
        "goals/drafts": recorded("drafts"),
        f"goals/{SLUG}": recorded("goal"),
        f"goals/drafts/{DRAFT}": recorded("draft"),
        "results": {"items": [], "page": {"next_cursor": None}},
    }
    reads.update(bodies or {})
    return {
        path: route_for(router, "GET", path).mock(return_value=httpx.Response(200, json=body))
        for path, body in reads.items()
    }


def _refusal(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
    return httpx.Response(
        status, json={"error": {"code": code, "message": message, "details": details or {}}}
    )


# --- Reading --------------------------------------------------------------------------------------


def test_the_goals_page_lists_goals_drafts_and_starters_from_the_api(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        text = page(console, GOALS)
    assert f'<a href="{GOALS}" aria-current="page">Goals</a>' in text
    assert f'href="{GOALS}/{SLUG}"' in text
    assert "Creative non-fiction voice" in text
    assert ">calibrated<" in text and "κ<sub>w</sub> 0.86 over 5 held out" in text
    assert ">unforked<" in text
    assert "rule 40%" in text and "judge 60%" in text
    assert f'href="{GOALS}/drafts/{DRAFT}"' in text
    assert "House style compliance" in text
    assert f'action="{GOALS}/starters/creative_voice/fork"' in text
    assert f'action="{GOALS}/starters/creative_voice/customise"' in text
    assert 'enctype="multipart/form-data"' in text
    assert "From the API" in text


def _stopped_goal(database: Path, *, passed: bool = False) -> None:
    fill_rows(
        database,
        "goals",
        [
            {
                "id": "01STOPPEDGOAL000000000000A", "slug": "house_voice", "name": "House voice",
                "goal_hash": "sha256:stoppedgoalhash", "capability_id": "user.house_voice",
                "goal_pack_version": "1.0.0", "unforked": 0, "intent": "Sounds like us.",
                "lint_json": json.dumps([{"code": "DETERMINISTIC_WEIGHT_SHARE", "severity": "info",
                                          "message": "Half by rules.", "criterion": None}]),
            }
        ],
    )  # fmt: skip
    fill_rows(
        database,
        "goal_criteria",
        [
            {"id": "01STOPPEDCRIT000000000000A", "goal_id": "01STOPPEDGOAL000000000000A",
             "key": "wit", "name": "Dry wit", "rung": "judge", "weight": 0.5, "ordinal": 1,
             "scale_points": 5, "scale_descriptors_json": json.dumps({"5": "Wry."})},
            {"id": "01STOPPEDCRIT000000000000B", "goal_id": "01STOPPEDGOAL000000000000A",
             "key": "tells", "name": "No LLM tells", "rung": "rule", "weight": 0.5, "ordinal": 0,
             "rule_json": json.dumps({"type": "forbidden_phrases"})},
        ],
    )  # fmt: skip
    fill_rows(
        database,
        "goal_tasks",
        [{"id": "01STOPPEDTASK000000000000A", "goal_id": "01STOPPEDGOAL000000000000A",
          "key": "warehouse", "name": "Warehouse night", "prompt_id": "goals.house_voice.t1",
          "prompt_version": "1.0.0", "prompt_sha256": "sha256:prompt", "is_starter": 1}],
    )  # fmt: skip
    fill_rows(
        database,
        "calibration_reports",
        [
            {"id": "01STOPPEDREPORT0000000000A", "goal_id": "01STOPPEDGOAL000000000000A",
             "goal_criterion_id": None, "goal_hash": "sha256:stoppedgoalhash", "kappa_w": 0.31,
             "n_holdout": 5, "n_anchor": 7, "passed_gate": int(passed), "min_agreement": 0.4,
             "judge_validity_factor": 0.2, "measured_at": "2026-09-10 12:00:00",
             "policy_version": "1.0", "disagreement_json": json.dumps({"warnings": ["Bunched."]})},
            {"id": "01STOPPEDREPORT0000000000B", "goal_id": "01STOPPEDGOAL000000000000A",
             "goal_criterion_id": "01STOPPEDCRIT000000000000A",
             "goal_hash": "sha256:stoppedgoalhash",
             "kappa_w": 0.31, "rho": 0.5, "mae": 1.2, "bias": 0.8, "n_holdout": 5,
             "passed_gate": 0, "min_agreement": 0.4, "judge_validity_factor": 0.2,
             "measured_at": "2026-09-10 12:00:00", "policy_version": "1.0",
             "disagreement_json": json.dumps({"band": "not_measurable", "lint": "Generous.",
                                              "samples": []})},
        ],
    )  # fmt: skip


def test_stopped_goals_read_the_database_and_say_what_only_the_api_holds(tmp_path: Path) -> None:
    console, database = freeweight_console(tmp_path, state="inactive")
    _stopped_goal(database)

    listing = page(console, GOALS)
    assert "From the database at revision 0010" in listing
    assert f'href="{GOALS}/house_voice"' in listing
    assert ">uncalibrated<" in listing and "κ<sub>w</sub> 0.31 over 5 held out" in listing
    assert "Drafts are read only from FreeWeight's running API." in listing
    assert "The starters ship inside FreeWeight" in listing

    goal = page(console, f"{GOALS}/house_voice")
    assert "From the database at revision 0010" in goal
    assert "sha256:stoppedgoalhash" in goal
    assert "Dry wit" in goal and "forbidden_phrases" in goal and "Warehouse night" in goal
    assert "DETERMINISTIC_WEIGHT_SHARE" in goal
    assert "A goal's results are FreeWeight's metric query" in goal
    assert f'href="{GOALS}/house_voice/edit"' not in goal


def test_one_goal_shows_its_hash_criteria_tasks_lint_results_and_both_exports(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    goal = recorded("goal")
    results = {
        "items": [
            {"run_id": "01M27RUNOFGOAL00000000000A", "model": "ollama/qwen3:8b",
             "metric_key": "composite_score", "value": 0.62, "created_at": "2026-09-11T08:00:00Z"}
        ]
    }  # fmt: skip
    with respx.mock(assert_all_called=False) as router:
        routes = mock_goals(router, bodies={"results": results})
        text = page(console, f"{GOALS}/{SLUG}")
    assert goal["goal_hash"] in text
    for criterion in goal["criteria"]:
        assert criterion["key"] in text
    assert "inventory_night" in text
    assert "UNFORKED_STARTER" in text
    assert "composite_score" in text and "0.62" in text
    assert f'href="{GOALS}/{SLUG}/bundle"' in text and "Round-trips:" in text
    assert f'href="{GOALS}/{SLUG}/export"' in text and "Does not round-trip:" in text
    assert f'href="{GOALS}/{SLUG}/edit"' in text
    assert routes["results"].calls.last.request.url.params["suite"] == f"goal.{SLUG}"


def test_validate_and_suggest_are_freeweights_reading_and_apply_nothing(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        validate = route_for(router, "POST", f"goals/{SLUG}/validate").mock(
            return_value=httpx.Response(200, json=recorded("goal-validate"))
        )
        suggest = route_for(router, "POST", f"goals/{SLUG}/suggest-rules").mock(
            return_value=httpx.Response(200, json=recorded("goal-suggest"))
        )
        checked = page(console, f"{GOALS}/{SLUG}?check=validate")
        proposed = page(console, f"{GOALS}/{SLUG}?check=suggest")
    assert validate.called and suggest.called
    assert ">valid<" in checked
    assert "Proposals only — FreeWeight applies none." in proposed
    assert "vocabulary_profile" in proposed
    assert "navigate the complexities" in proposed


# --- Creating, forking, drafts --------------------------------------------------------------------


def test_create_sends_the_pack_as_typed_and_lands_on_the_goal(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    pack = recorded("goal")["pack"]
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        created = route_for(router, "POST", "goals").mock(
            return_value=httpx.Response(201, json=recorded("goal-fork"))
        )
        response = post(
            console,
            GOALS,
            {"goal": json.dumps(pack["goal"]), "tasks": json.dumps(pack["tasks"])},
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{GOALS}/{SLUG}?done=created"
    assert json.loads(created.calls.last.request.content) == pack
    (row,) = audit(console, "freeweight.goal_create")
    assert (row["outcome"], row["target"]) == ("ok", SLUG)


def test_a_pack_that_is_not_json_is_refused_before_anything_is_sent(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        created = route_for(router, "POST", "goals")
        response = post(console, GOALS, {"goal": "{not json", "tasks": ""})
    assert response.status_code == 200
    assert (
        '<p class="error-state" role="alert"><strong><code>VALIDATION_ERROR</code>' in response.text
    )
    assert "goal.json is not JSON" in response.text
    assert not created.called
    (row,) = audit(console, "freeweight.goal_create")
    assert row["outcome"] == "refused"


def test_fork_and_customise_are_freeweights_calls(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        fork = route_for(router, "POST", "goals/starters/creative_voice/fork").mock(
            return_value=httpx.Response(201, json=recorded("goal-fork"))
        )
        begin = route_for(router, "POST", "goals/drafts").mock(
            return_value=httpx.Response(201, json=recorded("draft"))
        )
        forked = post(console, f"{GOALS}/starters/creative_voice/fork", {"slug": SLUG})
        customised = post(console, f"{GOALS}/starters/creative_voice/customise", {})
    assert forked.headers["location"] == f"{GOALS}/{SLUG}?done=forked"
    assert json.loads(fork.calls.last.request.content) == {"slug": SLUG}
    assert customised.headers["location"] == f"{GOALS}/drafts/{DRAFT}"
    assert json.loads(begin.calls.last.request.content) == {"starter": "creative_voice"}
    (fork_row,) = audit(console, "freeweight.goal_fork")
    (draft_row,) = audit(console, "freeweight.draft_start")
    assert fork_row["params"] == {"starter": "creative_voice"}
    assert draft_row["params"] == {"starter": "creative_voice", "has_intent": False}


def test_the_draft_page_offers_every_step_and_each_step_is_freeweights(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    draft = recorded("draft")
    base = f"{GOALS}/drafts/{DRAFT}"
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        text = page(console, base)
        criteria = route_for(router, "POST", f"goals/drafts/{DRAFT}/criteria").mock(
            return_value=httpx.Response(200, json=draft)
        )
        rules = route_for(router, "POST", f"goals/drafts/{DRAFT}/rules").mock(
            return_value=httpx.Response(200, json=draft)
        )
        tasks = route_for(router, "POST", f"goals/drafts/{DRAFT}/tasks").mock(
            return_value=httpx.Response(200, json=draft)
        )
        save = route_for(router, "POST", f"goals/drafts/{DRAFT}/save").mock(
            return_value=httpx.Response(200, json={"draft": draft, "goal": recorded("goal-fork")})
        )
        abandon = route_for(router, "DELETE", f"goals/drafts/{DRAFT}").mock(
            return_value=httpx.Response(204)
        )
        described = post(
            console, f"{base}/criteria",
            {"action": "describe", "criterion": "on_brand", "points": "5",
             "top": "Ours.", "middle": "Mixed.", "bottom": "Theirs."},
        )  # fmt: skip
        answered = post(
            console, f"{base}/criteria",
            {"action": "answer", "criterion": "on_brand", "graded_alike": "no"},
        )  # fmt: skip
        accepted = post(
            console, f"{base}/rules",
            {"criterion": "on_brand", "rule_type": "forbidden_phrases",
             "parameters": '{"phrases": ["synergy"]}'},
        )  # fmt: skip
        broken = post(
            console, f"{base}/rules",
            {"criterion": "on_brand", "rule_type": "forbidden_phrases", "parameters": "[1, 2"},
        )  # fmt: skip
        added = post(console, f"{base}/tasks", {"name": "Note", "prompt_text": "Write a note."})
        saved = post(console, f"{base}/save", {"slug": "", "name": ""})
        abandoned = post(console, f"{base}/delete", {})
    for question in draft["questions"]:
        assert question.replace("'", "&#39;") in text
    assert draft["weight_shift"]["sentence"].replace("'", "&#39;") in text
    assert ">accepted<" in text
    assert f'action="{base}/save"' in text
    assert described.headers["location"] == f"{base}#step-criteria"
    assert json.loads(criteria.calls[0].request.content) == {
        "action": "describe", "criterion": "on_brand", "points": 5,
        "top": "Ours.", "middle": "Mixed.", "bottom": "Theirs.",
    }  # fmt: skip
    assert answered.status_code == 303
    assert json.loads(criteria.calls[1].request.content) == {
        "action": "answer", "criterion": "on_brand", "graded_alike": False, "one_quality": None,
    }  # fmt: skip
    assert accepted.status_code == 303
    assert json.loads(rules.calls.last.request.content)["parameters"] == {"phrases": ["synergy"]}
    assert broken.status_code == 200 and "parameters is not JSON" in broken.text
    assert rules.call_count == 1, "a malformed edit is never sent as the proposal's parameters"
    assert added.status_code == 303 and tasks.called
    assert saved.headers["location"] == f"{GOALS}/{SLUG}?done=saved"
    assert save.called
    assert abandoned.headers["location"] == f"{GOALS}?done=draft_deleted"
    assert abandon.called
    rows = audit(console, "freeweight.draft_edit")
    assert [row["outcome"] for row in reversed(rows)] == ["ok", "ok", "ok", "refused", "ok"]
    assert all("Write a note." not in json.dumps(row) for row in rows)


# --- Editing --------------------------------------------------------------------------------------


def _edit_form(pack: dict[str, Any], **extra: str) -> dict[str, str]:
    return {"goal": json.dumps(pack["goal"]), "tasks": json.dumps(pack["tasks"]), **extra}


def test_an_edit_that_keeps_the_hash_is_saved_at_once(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    pack = recorded("goal")["pack"]
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        put = route_for(router, "PUT", f"goals/{SLUG}").mock(
            return_value=httpx.Response(200, json=recorded("goal-put-rename"))
        )
        form = page(console, f"{GOALS}/{SLUG}/edit")
        response = post(console, f"{GOALS}/{SLUG}/edit", _edit_form(pack))
    assert "&#34;slug&#34;: &#34;wp4_voice&#34;" in form
    assert response.headers["location"] == f"{GOALS}/{SLUG}?done=edited"
    assert [call.request.url.params.get("dry_run") for call in put.calls] == ["true", None]
    (row,) = audit(console, "freeweight.goal_edit")
    assert (row["outcome"], row["params"]["separates"]) == ("ok", False)


def test_a_separating_edit_names_both_hashes_and_the_runs_and_waits_for_a_confirmation(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    pack = recorded("goal")["pack"]
    separating = copy.deepcopy(recorded("goal-put-preview"))
    separating["hash_change"]["separated_runs"] = 3
    change = separating["hash_change"]
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        put = route_for(router, "PUT", f"goals/{SLUG}").mock(
            return_value=httpx.Response(200, json=separating)
        )
        shown = post(console, f"{GOALS}/{SLUG}/edit", _edit_form(pack))
        assert [call.request.url.params.get("dry_run") for call in put.calls] == ["true"]
        confirmed = post(
            console,
            f"{GOALS}/{SLUG}/edit",
            _edit_form(
                pack, confirm="yes", previous_goal_hash=change["previous_goal_hash"],
                goal_hash=change["goal_hash"],
            ),
        )  # fmt: skip
    assert shown.status_code == 200
    assert change["previous_goal_hash"] in shown.text and change["goal_hash"] in shown.text
    assert "<strong>3</strong> run(s)" in shown.text
    assert "Save, separating 3 run(s)" in shown.text
    assert confirmed.headers["location"] == f"{GOALS}/{SLUG}?done=edited"
    assert [call.request.url.params.get("dry_run") for call in put.calls] == ["true", "true", None]
    pending, applied = reversed(audit(console, "freeweight.goal_edit"))
    assert (pending["outcome"], pending["params"]["separated_runs"]) == ("pending", 3)
    assert (applied["outcome"], applied["params"]["confirmed"]) == ("ok", True)


def test_a_confirmation_for_hashes_that_have_moved_is_shown_again_and_not_applied(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    pack = recorded("goal")["pack"]
    change = recorded("goal-put-preview")["hash_change"]
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        put = route_for(router, "PUT", f"goals/{SLUG}").mock(
            return_value=httpx.Response(200, json=recorded("goal-put-preview"))
        )
        response = post(
            console,
            f"{GOALS}/{SLUG}/edit",
            _edit_form(
                pack, confirm="yes", previous_goal_hash="sha256:an-older-preview",
                goal_hash=change["goal_hash"],
            ),
        )  # fmt: skip
    assert response.status_code == 200
    assert "The goal changed after the preview you confirmed." in response.text
    assert [call.request.url.params.get("dry_run") for call in put.calls] == ["true"]


# --- Deleting, importing, exporting ---------------------------------------------------------------


def test_delete_previews_then_deletes_only_when_the_slug_is_typed(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    preview = {**recorded("goal-delete-preview"), "orphaned_runs": 2, "destroyed_grades": 24}
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        delete = route_for(router, "DELETE", f"goals/{SLUG}").mock(
            return_value=httpx.Response(200, json=preview)
        )
        first = post(console, f"{GOALS}/{SLUG}/delete", {})
        wrong = post(console, f"{GOALS}/{SLUG}/delete", {"confirm": "wp4-voice"})
        typed = post(console, f"{GOALS}/{SLUG}/delete", {"confirm": SLUG})
    assert "<strong>24</strong> of your grades are destroyed" in first.text
    assert "2 run(s) measured under it" in first.text
    assert "does not match; nothing was deleted" in wrong.text
    assert typed.headers["location"] == f"{GOALS}?done=deleted"
    assert [call.request.url.params.get("dry_run") for call in delete.calls] == [
        None,
        None,
        "false",
    ]
    outcomes = [row["outcome"] for row in reversed(audit(console, "freeweight.goal_delete"))]
    assert outcomes == ["pending", "pending", "ok"]


def test_an_import_colliding_on_a_slug_names_the_installed_goal_hash(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    collision = recorded("goal-import-collision")
    bundle = (GOALS_FIXTURES / "goal-bundle.json").read_text(encoding="utf-8")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        route_for(router, "POST", "goals/import").mock(
            return_value=httpx.Response(409, json=collision)
        )
        response = post(console, f"{GOALS}/import", {"bundle": bundle, "slug": ""})
    assert response.status_code == 200
    assert "<code>CONFLICT</code>" in response.text
    assert collision["error"]["details"]["existing_goal_hash"] in response.text
    (row,) = audit(console, "freeweight.goal_import")
    assert row["outcome"] == "refused"


def test_an_uploaded_bundle_is_freeweights_import_body(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    bundle = (GOALS_FIXTURES / "goal-bundle.json").read_text(encoding="utf-8")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        imported = route_for(router, "POST", "goals/import").mock(
            return_value=httpx.Response(201, json=recorded("goal-fork"))
        )
        token = console.csrf_token()
        response = console.client.post(
            f"{GOALS}/import",
            data={"csrf_token": token, "slug": "", "bundle": ""},
            files={"upload": ("wp4_voice.goal-bundle.json", bundle, "application/json")},
            headers=HTML,
        )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"{GOALS}/{SLUG}?done=imported"
    assert json.loads(imported.calls.last.request.content) == {
        "bundle": json.loads(bundle), "slug": None,
    }  # fmt: skip
    (row,) = audit(console, "freeweight.goal_import")
    assert row["params"]["from_upload"] is True


def test_an_uploaded_file_that_is_not_json_is_refused_before_anything_is_sent(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        imported = route_for(router, "POST", "goals/import")
        token = console.csrf_token()
        response = console.client.post(
            f"{GOALS}/import",
            data={"csrf_token": token, "slug": "", "bundle": ""},
            files={"upload": ("bundle.zip", b"PK\x03\x04 not a bundle", "application/zip")},
            headers=HTML,
        )
    assert response.status_code == 200
    assert "bundle is not JSON" in response.text
    assert not imported.called


def test_both_exports_pass_freeweights_documents_through_as_attachments(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    bundle = (GOALS_FIXTURES / "goal-bundle.json").read_text(encoding="utf-8")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        route_for(router, "GET", f"goals/{SLUG}/bundle").mock(
            return_value=httpx.Response(
                200, text=bundle,
                headers={"content-type": "application/json; charset=utf-8",
                         "content-disposition": f'attachment; filename="{SLUG}.goal-bundle.json"'},
            )
        )  # fmt: skip
        route_for(router, "GET", f"goals/{SLUG}/export").mock(
            return_value=httpx.Response(200, json={"schema": "benchmark.goal_pack"})
        )
        bundled = console.client.get(f"{GOALS}/{SLUG}/bundle")
        described = console.client.get(f"{GOALS}/{SLUG}/export")
    assert bundled.status_code == 200 and bundled.text == bundle
    assert (
        bundled.headers["content-disposition"] == f'attachment; filename="{SLUG}.goal-bundle.json"'
    )
    assert (
        described.headers["content-disposition"] == f'attachment; filename="{SLUG}.goal-pack.json"'
    )
    assert described.json() == {"schema": "benchmark.goal_pack"}


# --- Text, refusals and the kit -------------------------------------------------------------------


def test_the_injection_corpus_renders_inert_in_a_goal_and_a_draft(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    goal = copy.deepcopy(recorded("goal"))
    goal["intent"] = HOSTILE
    goal["criteria"][0]["name"] = HOSTILE
    goal["tasks"][0]["name"] = HOSTILE
    goal["findings"][0]["message"] = HOSTILE
    draft = copy.deepcopy(recorded("draft"))
    draft["intent"] = HOSTILE
    draft["criteria"][0]["name"] = HOSTILE
    draft["tasks"][0]["prompt_text"] = HOSTILE
    draft["proposals"][0]["explanation"] = HOSTILE
    listing = copy.deepcopy(recorded("goals"))
    listing["items"][0]["name"] = HOSTILE
    with respx.mock(assert_all_called=False) as router:
        mock_goals(
            router, bodies={f"goals/{SLUG}": goal, f"goals/drafts/{DRAFT}": draft, "goals": listing}
        )
        for path in (GOALS, f"{GOALS}/{SLUG}", f"{GOALS}/drafts/{DRAFT}"):
            _assert_inert(page(console, path))


def test_a_refusal_is_an_error_and_its_footer_says_the_api_answered(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_goals(router)
        route_for(router, "GET", "goals/nothing_here").mock(
            return_value=_refusal(404, "GOAL_NOT_FOUND", "No goal named 'nothing_here'.")
        )
        text = page(console, f"{GOALS}/nothing_here")
    assert '<p class="error-state" role="alert"><strong><code>GOAL_NOT_FOUND</code>' in text
    assert "From the API, which refused this page: freeweight refused" in text
    assert "The API did not answer this page" not in text


def test_a_stopped_page_that_reads_only_the_api_names_freeweight_by_its_label(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="inactive")
    text = page(console, f"{GOALS}/drafts/{DRAFT}")
    assert "FreeWeight is not answering, and this page reads only from its running API." in text
    assert "freeweight is not answering" not in text


SHELL_CSS = (
    Path(__file__).resolve().parents[2] / "src/weightroom/web/static/css/weightroom-shell.css"
)
"""The shell's stylesheet, external since row WX3."""


def test_an_export_card_that_is_itself_the_form_lays_its_fields_out_as_a_grid(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="inactive")
    assert 'class="card kit-form"' in page(console, GOALS)
    # The rule itself moved out of `_shell.html` into the shell's own stylesheet at row WX3.
    css = SHELL_CSS.read_text(encoding="utf-8")
    assert ".kit-form form, form.kit-form { display: grid;" in css


def test_every_goal_request_goes_to_freeweights_api_only(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_goals(router)
        page(console, GOALS)
        page(console, f"{GOALS}/{SLUG}")
    for route in routes.values():
        for call in route.calls:
            assert str(call.request.url).startswith(API)

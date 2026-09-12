"""Row WP5 Gate C: IdeaPress's plan, research, stage runs, units, workspace and export.

Read and act, running and stopped. The stream proxy is tested with IdeaPress's own recorded task
stream: a draft run that paused U-01 and was cancelled at U-02, so it carries ``unit.paused`` and
``stage.failed``. The injection corpus is placed in a brief and in a unit's content, and must render
inert.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import respx
from sqlalchemy import select

from tests.security.test_chat_isolation import HOSTILE, _assert_inert
from tests.support import (
    IDEAPRESS_FIXTURES,
    IDEAPRESS_URL,
    RECORDED_PROJECT,
    Console,
    ideapress_console,
    ideapress_fixture,
    mock_ideapress,
    mock_loadcoach,
)
from weightroom.infrastructure.db.models import AuditLog
from weightroom.web.rendering import app_side_nav_stubs

HTML = {"Accept": "text/html"}
BASE = "/apps/ideapress"
API = f"{IDEAPRESS_URL}/api/v1"
PROJECT = RECORDED_PROJECT
PAGES = f"{BASE}/projects/{PROJECT}"
CANCELLED = ideapress_fixture("task-cancelled")["task_id"]


def _page(console: Console, path: str) -> str:
    response = console.client.get(path, headers=HTML)
    assert response.status_code == 200, response.text
    return str(response.text)


def _rows(console: Console, action: str) -> list[AuditLog]:
    with console.database.read() as session:
        found = session.scalars(select(AuditLog).where(AuditLog.action == action)).all()
        for row in found:
            session.expunge(row)
        return list(found)


def _mock(router: Any, **bodies: Any) -> dict[str, Any]:  # noqa: ANN401 — a respx router
    mock_loadcoach(router)
    return mock_ideapress(
        router, bodies={key.replace("__", "/"): body for key, body in bodies.items()}
    )


def _sent(route: Any) -> Any:  # noqa: ANN401 — a respx route's last JSON body
    return json.loads(route.calls.last.request.content)


def test_every_ideapress_page_is_built_and_none_is_a_stub() -> None:
    assert app_side_nav_stubs("ideapress") == ()


# --- The plan and research ------------------------------------------------------------------------


def test_the_running_plan_shows_requirements_with_their_sources_the_editor_and_research(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        page = _page(console, f"{PAGES}/plan")
    assert "inference runs entirely on the reader&#39;s own machine" in page
    assert "Where the work happens" in page
    assert f'action="{PAGES}/plan/edits"' in page
    assert "Run the plan" in page
    assert "docs.example" in page, "where a fetch may go, before one is started"
    assert "https://docs.example/local-inference" in page
    assert "host_not_allowed" in page
    assert "approved" in page, "each call's egress decision"
    assert page.count("From the API") == 2


def test_a_stopped_plan_reads_requirements_and_research_from_the_database(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    page = _page(console, f"{PAGES}/plan")
    assert "The unit must be explicit about where inference happens." in page
    assert "What it costs" in page
    assert "host_not_allowed" in page
    assert "approved" in page, "the decision joined from egress_decisions by source_ref"
    assert page.count("From the database at revision 0011") == 2
    assert f'action="{PAGES}/plan/edits"' not in page


def test_a_plan_edit_sends_ideapress_body_and_returns_to_the_plan(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        edited = router.post(f"{API}/projects/{PROJECT}/plan/edits").mock(
            return_value=httpx.Response(200, json=ideapress_fixture("plan"))
        )
        response = console.post_form(
            f"{PAGES}/plan/edits", {"operation": "reorder", "unit_keys": "U-02", "position": "1"}
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{PAGES}/plan?edited=reorder"
    assert _sent(edited) == {
        "operation": "reorder",
        "unit_keys": ["U-02"],
        "requirement_keys": [],
        "text": "",
        "position": 1,
    }
    (row,) = _rows(console, "ideapress.plan_edit")
    assert (row.outcome, row.params) == ("ok", {"operation": "reorder"})


def test_the_plan_gate_refusal_names_the_protected_unit_and_changes_nothing(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    refused = ideapress_fixture("refused-plan-edit")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.post(f"{API}/projects/{PROJECT}/plan/edits").mock(
            return_value=httpx.Response(refused["status"], json=refused["body"])
        )
        response = console.post_form(
            f"{PAGES}/plan/edits", {"operation": "reorder", "unit_keys": "U-02", "position": "1"}
        )
    assert response.status_code == 200
    assert "VALIDATION_ERROR" in response.text
    assert "hold finished work" in response.text
    assert "The plan is unchanged." in response.text
    (row,) = _rows(console, "ideapress.plan_edit")
    assert row.outcome == "refused"


def test_a_position_that_is_not_a_number_is_refused_before_anything_is_sent(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        edited = router.post(f"{API}/projects/{PROJECT}/plan/edits")
        response = console.post_form(
            f"{PAGES}/plan/edits", {"operation": "reorder", "unit_keys": "U-02", "position": "one"}
        )
    assert "VALIDATION_ERROR" in response.text
    assert not edited.called


def test_running_the_plan_and_research_opens_their_task(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    planned = ideapress_fixture("plan-started")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.post(f"{API}/projects/{PROJECT}/plan").mock(
            return_value=httpx.Response(202, json=planned)
        )
        research = router.post(f"{API}/projects/{PROJECT}/stages/research/run").mock(
            return_value=httpx.Response(202, json={**planned, "stage": "research"})
        )
        plan = console.post_form(f"{PAGES}/plan", {})
        fetched = console.post_form(f"{PAGES}/research", {})
    assert plan.headers["location"] == f"{PAGES}/tasks/{planned['task_id']}"
    assert fetched.headers["location"] == f"{PAGES}/tasks/{planned['task_id']}"
    assert _sent(research) == {}
    assert [row.outcome for row in _rows(console, "ideapress.plan_run")] == ["ok"]
    assert [row.outcome for row in _rows(console, "ideapress.research_run")] == ["ok"]


# --- Stage runs -----------------------------------------------------------------------------------


def test_the_run_form_shows_the_values_the_stage_will_use(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        page = _page(console, PAGES)
    assert "Run a stage" in page
    assert "models.stages.draft" in page
    assert "workflow.max_revision_rounds" in page
    assert "next_stage" in page
    assert f'href="{PAGES}/tasks/{CANCELLED}"' in page
    assert f'href="{PAGES}/units/U-01"' in page


def test_a_stage_run_sends_ideapress_body_with_only_the_overrides_given(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    started = ideapress_fixture("stage-run-started")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        run = router.post(f"{API}/projects/{PROJECT}/stages/draft/run").mock(
            return_value=httpx.Response(202, json=started)
        )
        response = console.post_form(
            f"{PAGES}/stages",
            {
                "stage": "draft",
                "units": "U-01, U-02",
                "resume": "true",
                "model_hint": "ollama/qwen3.5:9b-q8_0",
                "max_revision_rounds": "2",
            },
        )
    assert response.headers["location"] == f"{PAGES}/tasks/{started['task_id']}"
    assert _sent(run) == {
        "resume": True,
        "units": ["U-01", "U-02"],
        "overrides": {"model_hint": "ollama/qwen3.5:9b-q8_0", "max_revision_rounds": 2},
    }
    (row,) = _rows(console, "ideapress.stage_run")
    assert row.params == {
        "stage": "draft",
        "resume": True,
        "units": 2,
        "overrides": ["max_revision_rounds", "model_hint"],
        "task_id": started["task_id"],
    }


def test_an_override_ideapress_refuses_renders_on_the_project_with_the_form_kept(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    refused = ideapress_fixture("refused-override")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.post(f"{API}/projects/{PROJECT}/stages/draft/run").mock(
            return_value=httpx.Response(refused["status"], json=refused["body"])
        )
        response = console.post_form(
            f"{PAGES}/stages", {"stage": "draft", "model_hint": "kept-as-typed"}
        )
    assert response.status_code == 200
    assert "VALIDATION_ERROR" in response.text
    assert refused["body"]["error"]["message"].replace("'", "&#39;") in response.text
    assert 'value="kept-as-typed"' in response.text


def test_a_running_task_offers_cancel_and_streams_through_the_proxy(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    started = ideapress_fixture("stage-run-started")
    task = started["task_id"]
    with respx.mock(assert_all_called=False) as router:
        _mock(router, **{f"projects__{PROJECT}__tasks__{task}": started})
        page = _page(console, f"{PAGES}/tasks/{task}")
    assert f'action="{PAGES}/tasks/{task}/cancel"' in page
    assert f'data-log-stream="{PAGES}/tasks/{task}/events"' in page
    assert "next model-call boundary" in page


def test_a_cancelled_task_is_shown_as_its_state_not_as_an_error(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    cancelled = ideapress_fixture("task-cancelled")
    with respx.mock(assert_all_called=False) as router:
        _mock(router, **{f"projects__{PROJECT}__tasks__{CANCELLED}": cancelled})
        page = _page(console, f"{PAGES}/tasks/{CANCELLED}")
    assert "cancelled at a model-call boundary" in page
    assert 'role="alert"' not in page
    assert "/cancel" not in page
    assert "stages.draft.write" in page, "its attempts"


def test_a_tasks_attempts_name_the_transport_call_of_a_discarded_retry(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    cancelled = ideapress_fixture("task-cancelled")
    with respx.mock(assert_all_called=False) as router:
        _mock(router, **{f"projects__{PROJECT}__tasks__{CANCELLED}": cancelled})
        page = _page(console, f"{PAGES}/tasks/{CANCELLED}")
    assert "transport_call</code> numbers the calls" in page, "row WPF12's one line of copy"
    assert "· round 2 · call 1" in page, "the discarded call, named within its attempt"
    assert "· round 2 · call 0" in page, "the retry that kept its answer"
    assert "provider_error" in page, "the discarded call reads as discarded, not a bare failure"
    assert "EMPTY_GENERATION" in page


def test_the_task_stream_becomes_log_lines_with_the_pause_and_the_end_as_states(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    recorded = (IDEAPRESS_FIXTURES / "task-paused-then-cancelled.sse").read_text(encoding="utf-8")
    first, rest = recorded.split("\n\n", 1)
    # A bare `token` frame (ADR-0025 §3) as IdeaPress's stream formats one, carrying hostile text.
    token = 'event: token\ndata: "streamed <script>alert(1)</script> words"'
    body = f"{first}\n\n{token}\n\n{rest}"
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        stream = router.get(f"{API}/projects/{PROJECT}/tasks/{CANCELLED}/stream").mock(
            return_value=httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=body.encode()
            )
        )
        response = console.client.get(
            f"{PAGES}/tasks/{CANCELLED}/events", headers={"Last-Event-ID": "3"}
        )
    assert stream.calls.last.request.headers["last-event-id"] == "3"
    frames = []
    for block in response.text.strip().split("\n\n"):
        event = next(line[7:] for line in block.split("\n") if line.startswith("event: "))
        data = next(line[6:] for line in block.split("\n") if line.startswith("data: "))
        frames.append((event, json.loads(data)["payload"]))
    assert frames[-1][0] == "log.closed"
    lines = {payload["app"]: payload for event, payload in frames if event == "log"}
    assert lines["unit.paused"]["level"] == "warning"
    assert lines["stage.failed"]["level"] == "warning"
    assert lines["stage.failed"]["message"] == "the stage ended cancelled: cancelled"
    assert lines["token"]["message"] == "streamed <script>alert(1)</script> words"
    assert "error" not in lines


def test_cancel_posts_and_the_page_says_when_it_lands(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    started = ideapress_fixture("stage-run-started")
    task = started["task_id"]
    with respx.mock(assert_all_called=False) as router:
        _mock(router, **{f"projects__{PROJECT}__tasks__{task}": started})
        cancel = router.post(f"{API}/projects/{PROJECT}/tasks/{task}/cancel").mock(
            return_value=httpx.Response(202, json={"task_id": task, "cancelling": True})
        )
        response = console.post_form(f"{PAGES}/tasks/{task}/cancel", {})
        page = _page(console, response.headers["location"])
    assert cancel.called
    assert response.headers["location"] == f"{PAGES}/tasks/{task}?cancelling=True"
    assert "honours it at the next model-call boundary" in page
    assert f'action="{PAGES}/tasks/{task}/cancel"' not in page
    (row,) = _rows(console, "ideapress.stage_cancel")
    assert (row.outcome, row.target) == ("ok", task)


def test_a_stopped_task_reads_its_run_attempts_and_events_from_the_database(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    page = _page(console, f"{PAGES}/tasks/{CANCELLED}")
    assert "From the database at revision 0011" in page
    assert "Recorded events" in page
    assert "unit.paused" in page
    assert "stage.failed" in page
    assert "data-log-stream" not in page


# --- Units ----------------------------------------------------------------------------------------


def test_units_lists_a_projects_units_running_and_stopped(tmp_path: Path) -> None:
    running, _database = ideapress_console(tmp_path / "running", state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        page = _page(running, f"{BASE}/units")
    assert f'href="{PAGES}/units/U-01"' in page
    assert "1 of 2" in page
    assert '<a href="/apps/ideapress/units" aria-current="page">Units</a>' in page
    stopped, _database = ideapress_console(tmp_path / "stopped", state="inactive")
    page = _page(stopped, f"{BASE}/units?project={PROJECT}")
    assert f'href="{PAGES}/units/U-02"' in page
    assert "From the database at revision 0011" in page


def test_units_project_picker_follows_a_cursor_past_its_first_page(tmp_path: Path) -> None:
    """Row WX5: before this row the picker read only ``cursor=None`` and could reach no further."""
    console, _database = ideapress_console(tmp_path, state="active")
    projects = ideapress_fixture("projects")
    projects["page"] = {
        "has_more": True,
        "limit": 50,
        "next_cursor": "more-projects",
        "total": None,
    }
    with respx.mock(assert_all_called=False) as router:
        routes = _mock(router, projects=projects)
        first = _page(console, f"{BASE}/units")
        assert "cursor=more-projects" in first
        followed = _page(console, f"{BASE}/units?cursor=more-projects")
        sent = routes["projects"].calls.last.request.url.params
    assert sent["cursor"] == "more-projects"
    assert followed  # the second page still answers 200 with no project chosen from it


def test_a_unit_shows_sanitised_content_provenance_history_and_offers_revise(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        page = _page(console, f"{PAGES}/units/U-01")
    assert "<p>Everything happens on your own machine." in page
    assert "revise, audit_fast, critique" in page, "the run that produced version 2"
    assert "stages.draft.write" in page
    assert f'action="{PAGES}/units/U-01/revise"' in page
    assert f'action="{PAGES}/units/U-01/resume"' not in page, "a committed unit is revised"


def test_a_units_provenance_names_the_transport_call_of_a_discarded_retry(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        page = _page(console, f"{PAGES}/units/U-01")
    assert "transport_call</code> numbers the calls" in page, "row WPF12's one line of copy"
    assert "· round 2 · call 1" in page, "the discarded call, named within its attempt"
    assert "· round 2 · call 0" in page, "the retry that kept its answer"
    assert "provider_error" in page, "the discarded call reads as discarded, not a bare failure"
    assert "empty_generation_retried" in page


def test_revise_sends_the_instructions_and_audits_only_that_there_were_some(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    started = ideapress_fixture("revise-started")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        revise = router.post(f"{API}/projects/{PROJECT}/units/U-01/revise").mock(
            return_value=httpx.Response(202, json=started)
        )
        response = console.post_form(
            f"{PAGES}/units/U-01/revise", {"instructions": "Say no network is involved."}
        )
    assert response.headers["location"] == f"{PAGES}/tasks/{started['task_id']}"
    assert _sent(revise) == {"instructions": "Say no network is involved."}
    (row,) = _rows(console, "ideapress.unit_revise")
    assert "network" not in json.dumps(row.params)
    assert isinstance(row.params, dict)
    assert row.params["has_instructions"] is True
    assert row.params["unit"] == "U-01", "named so the redaction leaves it readable"


def test_a_revision_ideapress_refuses_says_why_and_keeps_the_instructions(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    refusal = {
        "error": {
            "code": "STAGE_PRECONDITION_FAILED",
            "message": "Unit U-01 is 'drafting'; only a committed or paused unit is revised.",
            "details": {"unit_key": "U-01", "state": "drafting"},
        }
    }
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.post(f"{API}/projects/{PROJECT}/units/U-01/revise").mock(
            return_value=httpx.Response(409, json=refusal)
        )
        response = console.post_form(f"{PAGES}/units/U-01/revise", {"instructions": "Kept."})
    assert "STAGE_PRECONDITION_FAILED" in response.text
    assert "only a committed or paused unit is revised" in response.text
    assert ">Kept.</textarea>" in response.text


def test_a_stranded_unit_offers_only_resume_and_resume_is_ideapress_own_draft_run(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    stranded = copy.deepcopy(ideapress_fixture("unit"))
    stranded["state"] = "drafting"
    started = ideapress_fixture("stage-run-started")
    with respx.mock(assert_all_called=False) as router:
        _mock(router, **{f"projects__{PROJECT}__units__U-01": stranded})
        page = _page(console, f"{PAGES}/units/U-01")
        run = router.post(f"{API}/projects/{PROJECT}/stages/draft/run").mock(
            return_value=httpx.Response(202, json=started)
        )
        response = console.post_form(f"{PAGES}/units/U-01/resume", {})
    assert "No run owns this unit" in page
    assert f'action="{PAGES}/units/U-01/resume"' in page
    assert f'action="{PAGES}/units/U-01/revise"' not in page
    assert _sent(run) == {"units": ["U-01"], "resume": True}
    assert response.headers["location"] == f"{PAGES}/tasks/{started['task_id']}"
    (row,) = _rows(console, "ideapress.unit_resume")
    assert (row.outcome, row.params) == ("ok", {"unit": "U-01", "task_id": started["task_id"]})


def test_a_stopped_unit_reads_its_content_and_versions_and_says_what_it_cannot_assemble(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    page = _page(console, f"{PAGES}/units/U-01")
    assert "no network involved at any point" in page, "version 2's content"
    assert "reads it only from its running API" in page
    assert "From the database at revision 0011" in page
    assert f"{PAGES}/units/U-01/revise" not in page


# --- The injection corpus -------------------------------------------------------------------------


def test_the_injection_corpus_renders_inert_in_a_brief(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    project = copy.deepcopy(ideapress_fixture("project"))
    project["brief"] = HOSTILE
    project["author_material"] = {"audience": HOSTILE}
    with respx.mock(assert_all_called=False) as router:
        _mock(router, **{f"projects__{PROJECT}": project})
        page = _page(console, PAGES)
    _assert_inert(page)


def test_the_injection_corpus_renders_inert_in_unit_content_and_the_workspace(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    unit = copy.deepcopy(ideapress_fixture("unit"))
    unit["content"] = HOSTILE
    unit["paused_reason"] = HOSTILE
    workspace = copy.deepcopy(ideapress_fixture("workspace"))
    workspace["unit"]["content"] = HOSTILE
    workspace["pause"] = {"paused": True, "reason": HOSTILE, "hint": HOSTILE, "kind": "other"}
    with respx.mock(assert_all_called=False) as router:
        _mock(
            router,
            **{
                f"projects__{PROJECT}__units__U-01": unit,
                f"projects__{PROJECT}__workspace": workspace,
            },
        )
        unit_page = _page(console, f"{PAGES}/units/U-01")
        workspace_page = _page(console, f"{PAGES}/workspace?unit=U-01")
    _assert_inert(unit_page)
    _assert_inert(workspace_page)


# --- The workspace and export ---------------------------------------------------------------------


def test_the_workspace_shows_the_navigator_content_diff_and_backend(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = _mock(router)
        page = _page(console, f"{PAGES}/workspace?unit=U-01&compare=1")
    sent = routes[f"projects/{PROJECT}/workspace"].calls.last.request.url.params
    assert (sent["unit"], sent["compare"]) == ("U-01", "1")
    assert f'href="{PAGES}/workspace?unit=U-02"' in page
    assert "Version 1 → 2" in page
    assert "stays on this machine" in page
    assert "Run research" in page


def test_a_stopped_workspace_says_it_reads_only_the_api(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    page = _page(console, f"{PAGES}/workspace")
    assert "this page reads only from its running API" in page


def test_export_writes_into_the_project_directory_and_names_where(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    written = ideapress_fixture("export-written")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        page = _page(console, f"{PAGES}/export")
        write = router.post(f"{API}/projects/{PROJECT}/export").mock(
            return_value=httpx.Response(200, json=written)
        )
        response = console.post_form(f"{PAGES}/export", {"format": "markdown"})
    assert "opens with no network at all" in page
    assert "2 of 2 unit(s) are committed" in page
    assert write.calls.last.request.url.params["format"] == "markdown"
    assert written["path"] in response.text
    assert written["sha256"] in response.text
    (row,) = _rows(console, "ideapress.export_write")
    assert (row.outcome, row.params) == (
        "ok",
        {"format": "markdown", "units": 2, "sha256": written["sha256"]},
    )


def test_an_export_downloads_as_an_attachment_and_is_never_shown_inline(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    document = (IDEAPRESS_FIXTURES / "export.md").read_text(encoding="utf-8")
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.get(f"{API}/projects/{PROJECT}/export").mock(
            return_value=httpx.Response(
                200, headers={"content-type": "text/markdown; charset=utf-8"}, text=document
            )
        )
        response = console.client.get(f"{PAGES}/export/download?format=markdown")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'attachment; filename="{PROJECT}.md"'
    assert response.text == document


def test_an_export_ideapress_refuses_renders_its_code(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    refusal = {
        "error": {"code": "EXPORT_FAILED", "message": "Nothing is committed.", "details": {}}
    }
    with respx.mock(assert_all_called=False) as router:
        _mock(router)
        router.post(f"{API}/projects/{PROJECT}/export").mock(
            return_value=httpx.Response(500, json=refusal)
        )
        response = console.post_form(f"{PAGES}/export", {"format": "markdown"})
    assert "EXPORT_FAILED" in response.text
    assert "Nothing is committed." in response.text

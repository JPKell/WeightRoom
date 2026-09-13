"""Row WP5 Gate B: IdeaPress's Projects, Workflows and Backends — read and act, running and stopped.

The recordings under ``tests/fixtures/ideapress`` are IdeaPress 1.5.0's own application answering
over its scripted backend (the WP5 handoff says how they were made); the stopped half reads
``ideapress-0011-journey``, the database that recording left behind.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import respx
from sqlalchemy import select

from tests.support import (
    IDEAPRESS_URL,
    RECORDED_PROJECT,
    Console,
    ideapress_console,
    ideapress_fixture,
    mock_ideapress,
    mock_loadcoach,
)
from weightroom.infrastructure.db.models import AuditLog

HTML = {"Accept": "text/html"}
BASE = "/apps/ideapress"
API = f"{IDEAPRESS_URL}/api/v1"
PROJECT = RECORDED_PROJECT


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


# --- Projects -------------------------------------------------------------------------------------


def test_the_running_projects_page_lists_from_the_api_with_the_nav(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        page = _page(console, f"{BASE}/projects")
    assert "Local inference for writers" in page
    assert "A second project" in page
    assert f'href="{BASE}/projects/{PROJECT}"' in page
    assert "From the API" in page
    assert f'<a href="{BASE}/projects" aria-current="page">Projects</a>' in page
    # Row WX10: the top nav — the recent projects, All, New.
    assert f'href="/apps/ideapress/projects/{PROJECT}"' in page
    assert '<a href="/apps/ideapress/projects" aria-current="page">All</a>' in page
    assert '<a href="/apps/ideapress/projects/new">New</a>' in page


def test_the_new_project_page_shows_the_create_form(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        page = _page(console, f"{BASE}/projects/new")
    assert '<option value="standard"' in page, "the workflow comes from GET /workflows"
    assert 'action="/apps/ideapress/projects"' in page
    assert '<a href="/apps/ideapress/projects/new" aria-current="page">New</a>' in page
    # The nav's recent projects still show, alongside the form.
    assert "Local inference for writers" in page


def test_a_stopped_new_project_page_says_creating_needs_the_api(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    page = _page(console, f"{BASE}/projects/new")
    assert "needs IdeaPress's own API" in page
    assert 'action="/apps/ideapress/projects"' not in page


def test_the_list_sends_its_filters_and_follows_ideapress_cursor(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    listing = copy.deepcopy(ideapress_fixture("projects"))
    listing["page"].update({"next_cursor": "eyJvZmZzZXQiOjUwfQ", "has_more": True})
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        routes = mock_ideapress(router, bodies={"projects": listing})
        page = _page(console, f"{BASE}/projects?status=planning&content_type=article&archived=true")
    # The page's own (filtered) read is the first call; the top nav's unfiltered, 8-row read of
    # the same path follows it (row WX10) — `.calls[0]` is the one this test means to inspect.
    sent = routes["projects"].calls[0].request.url.params
    assert (sent["status"], sent["content_type"], sent["include_archived"], sent["limit"]) == (
        "planning",
        "article",
        "true",
        "50",
    )
    assert routes["projects"].calls[-1].request.url.params["limit"] == "8"
    assert "cursor=eyJvZmZzZXQiOjUwfQ" in page


def test_a_stopped_projects_page_reads_the_database_with_a_start_beside_it(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    page = _page(console, f"{BASE}/projects")
    assert "Local inference for writers" in page
    assert "A second project" in page
    assert "From the database at revision 0011" in page
    assert 'value="start"' in page
    # The nav's recent-projects read falls back to the database exactly like the list itself.
    assert '<a href="/apps/ideapress/projects/new">New</a>' in page


def test_one_running_project_shows_its_plan_units_stage_history_and_forms(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        page = _page(console, f"{BASE}/projects/{PROJECT}")
    assert "writers new to local models" in page, "the author material"
    assert "What it costs" in page
    assert "cancelled" in page, "the draft run the recording cancelled"
    assert "revise" in page
    assert "1 of 2" in page, "U-01's coverage from IdeaPress's unit list"
    assert f'action="{BASE}/projects/{PROJECT}/edit"' in page
    assert "never recompiles requirements" in page
    assert "Delete this project" in page
    # Row WX10: this project is the nav's current entry.
    assert f'href="/apps/ideapress/projects/{PROJECT}" aria-current="page"' in page


def test_one_stopped_project_reads_its_rows_and_offers_no_action(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    page = _page(console, f"{BASE}/projects/{PROJECT}")
    assert "From the database at revision 0011" in page
    assert "What it costs" in page
    assert "cancelled" in page
    assert f"{BASE}/projects/{PROJECT}/edit" not in page
    assert "Delete this project" not in page


def test_a_project_the_database_does_not_hold_is_named_by_its_code(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    page = _page(console, f"{BASE}/projects/01ZZZZZZZZZZZZZZZZZZZZZZZZ")
    assert "PROJECT_NOT_FOUND" in page


def test_create_sends_ideapress_body_and_opens_the_new_project(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        created = router.post(f"{API}/projects").mock(
            return_value=httpx.Response(201, json=ideapress_fixture("project-created"))
        )
        response = console.post_form(
            f"{BASE}/projects",
            {
                "title": "Local inference for writers",
                "content_type": "article",
                "workflow_id": "standard",
                "brief": "A brief the author wrote.",
                "author_material": '{"audience": "writers"}',
            },
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/projects/{PROJECT}"
    assert json.loads(created.calls.last.request.content) == {
        "title": "Local inference for writers",
        "content_type": "article",
        "workflow_id": "standard",
        "brief": "A brief the author wrote.",
        "author_material": {"audience": "writers"},
    }
    (row,) = _rows(console, "ideapress.project_create")
    assert (row.outcome, row.target) == ("ok", PROJECT)
    assert "brief the author wrote" not in json.dumps(row.params)
    assert "Local inference" not in json.dumps(row.params)


def test_author_material_that_is_not_an_object_is_refused_before_anything_is_sent(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        created = router.post(f"{API}/projects").mock(return_value=httpx.Response(201, json={}))
        response = console.post_form(
            f"{BASE}/projects", {"title": "Kept as typed", "author_material": "[1, 2]"}
        )
    assert response.status_code == 200
    assert "VALIDATION_ERROR" in response.text
    assert 'value="Kept as typed"' in response.text
    assert not created.called
    (row,) = _rows(console, "ideapress.project_create")
    assert row.outcome == "refused"


def test_an_ideapress_refusal_renders_in_its_own_words(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    refusal = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "A project title must be between 1 and 200 characters.",
            "details": {"field": "title"},
        }
    }
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        router.post(f"{API}/projects").mock(return_value=httpx.Response(400, json=refusal))
        response = console.post_form(f"{BASE}/projects", {"title": " "})
    assert "A project title must be between 1 and 200 characters." in response.text
    assert "VALIDATION_ERROR" in response.text


def test_edit_puts_the_form_and_says_nothing_was_recompiled(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        put = router.put(f"{API}/projects/{PROJECT}").mock(
            return_value=httpx.Response(200, json=ideapress_fixture("project-created"))
        )
        response = console.post_form(
            f"{BASE}/projects/{PROJECT}/edit",
            {"title": "Renamed", "brief": "A new brief.", "author_material": "", "status": ""},
        )
        followed = _page(console, response.headers["location"])
    assert response.status_code == 303
    assert json.loads(put.calls.last.request.content) == {
        "title": "Renamed",
        "brief": "A new brief.",
        "author_material": {},
    }
    assert "never recompiles requirements on a save" in followed
    (row,) = _rows(console, "ideapress.project_update")
    assert row.outcome == "ok"


def test_delete_previews_first_then_deletes_only_the_typed_title_archiving_first(
    tmp_path: Path,
) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    preview = ideapress_fixture("delete-preview")
    done = {
        **preview,
        "deleted": True,
        "archive": {
            "path": "/data/archives/local-inference-for-writers.ideapress.zip",
            "size_bytes": 1,
        },
    }
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        delete = router.delete(f"{API}/projects/{PROJECT}")
        delete.side_effect = [
            httpx.Response(200, json=preview),
            httpx.Response(200, json=preview),
            httpx.Response(200, json=done),
        ]
        asked = console.post_form(f"{BASE}/projects/{PROJECT}/delete", {})
        wrong = console.post_form(
            f"{BASE}/projects/{PROJECT}/delete", {"confirm": "Not the title", "archive": "true"}
        )
        typed = console.post_form(
            f"{BASE}/projects/{PROJECT}/delete",
            {"confirm": "Local inference for writers", "archive": "true"},
        )
    assert "Type the project's title to confirm" in asked.text
    assert preview["archive_directory"] in asked.text
    assert "does not match; nothing was deleted" in wrong.text
    assert typed.status_code == 303
    assert "archive=%2Fdata%2Farchives" in typed.headers["location"]
    sent = [call.request.url.params for call in delete.calls]
    assert [params.get("confirm") for params in sent] == [None, None, "true"]
    assert sent[2]["archive"] == "true"
    outcomes = [
        (row.outcome, row.params.get("preview") if isinstance(row.params, dict) else None)
        for row in _rows(console, "ideapress.project_delete")
    ]
    assert sorted(outcomes) == [("ok", False), ("pending", True), ("pending", True)]


# --- Workflows and backends -----------------------------------------------------------------------


def test_workflows_show_stage_order_gates_bindings_and_limits(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        listing = _page(console, f"{BASE}/workflows")
        one = _page(console, f"{BASE}/workflows/standard")
    assert f'href="{BASE}/workflows/standard"' in listing
    assert "research_synthesis" in listing
    assert "ollama/qwen3.5:9b-q8_0" in listing, "a stage's bound model from GET /settings"
    assert "workflow.max_revision_rounds" in listing
    assert "next_stage" in listing
    assert "Workflow standard" in one


LOADCOACH_MODELS = Path(__file__).resolve().parents[1] / "fixtures" / "loadcoach" / "models.json"


def _mock_loadcoach_models(router: Any, *, base_url: str = "http://127.0.0.1:8766") -> Any:
    """``GET /models`` mocked with LoadCoach's own recorded registry (row WX10)."""
    body = json.loads(LOADCOACH_MODELS.read_text(encoding="utf-8"))
    return router.get(f"{base_url}/api/v1/models").mock(return_value=httpx.Response(200, json=body))


def test_backends_show_egress_the_round_trip_test_and_loadcoachs_models(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        _mock_loadcoach_models(router)
        tested = router.post(f"{API}/backends/test").mock(
            return_value=httpx.Response(200, json=ideapress_fixture("backend-test"))
        )
        page = _page(console, f"{BASE}/backends")
        response = console.post_form(f"{BASE}/backends/test", {"mode": "ollama"})
    assert "stays on this machine" in page
    assert "Test ollama" in page
    assert json.loads(tested.calls.last.request.content) == {"mode": "ollama"}
    assert "Round trip: ollama" in response.text
    assert "26.53 ms" in response.text
    assert "smollm2:135m" in response.text
    (row,) = _rows(console, "ideapress.backend_test")
    assert isinstance(row.params, dict)
    assert (row.outcome, row.params["status"]) == ("ok", "ok")
    # Row WX10: LoadCoach's models, matched to `[models.stages]` from `GET /settings`.
    assert "Models available in LoadCoach" in page
    assert "ollama/qwen3.5:9b-q8_0@sha256:441ec31e4d2a" in page
    assert "draft" in page, "models.stages.draft binds ollama/gemma4:12b, an unavailable model"
    assert 'href="/apps/loadcoach/models/' in page
    assert "Enable in LoadCoach" in page
    assert 'href="/apps/ideapress/settings"' in page


def test_a_backend_page_with_no_binding_still_reads_loadcoach(tmp_path: Path) -> None:
    """A model LoadCoach carries but no stage binds still shows, ``Bound stage(s)`` an em dash."""
    console, _database = ideapress_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_loadcoach(router)
        mock_ideapress(router)
        _mock_loadcoach_models(router)
        page = _page(console, f"{BASE}/backends")
    assert "ollama/smollm2:135m@sha256:9077fe9d2ae1" in page


def test_stopped_workflows_and_backends_say_they_read_only_the_api(tmp_path: Path) -> None:
    console, _database = ideapress_console(tmp_path, state="inactive")
    for path in ("workflows", "backends"):
        page = _page(console, f"{BASE}/{path}")
        assert "this page reads only from its running API" in page
        assert 'value="start"' in page


def test_no_ideapress_page_is_left_a_stub() -> None:
    from weightroom.web.rendering import app_side_nav_stubs

    assert [stub["label"] for stub in app_side_nav_stubs("ideapress")] == []

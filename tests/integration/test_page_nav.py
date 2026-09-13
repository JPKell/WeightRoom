"""The page bar never repeats the left menu (row WY1; WY roadmap §2.1).

Every GET UI route in the app's own route table is rendered — discovered, not listed, so a page
added later is covered the day it lands — and the ``href``\\ s of its ``nav.page-nav`` are compared
with those of its ``nav.side-nav``. A route that cannot render as a shell page from fixtures is
named in :data:`NOT_A_SHELL_PAGE` with the reason; a route that is neither rendered nor named
fails the test, so there is no silent skip.

The applications are unreachable here (their API is a closed port, their executable a fake that
answers only ``config``): every application page renders its degraded state, which still carries
its left menu and its page bar.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from tests.support import api_routes, build_console, fake_application
from weightroom.web.rendering import templates

if TYPE_CHECKING:
    from tests.support import Console

APPS = ("freeweight", "loadcoach", "ideapress", "promptcadence")

NOT_A_SHELL_PAGE: dict[str, str] = {
    "/login": "the login page has no session and no shell",
    "/trust/root.crt": "a certificate download, not a page",
    "/alerts/banner": "an htmx fragment swapped into the shell, not a page",
    "/apps/freeweight/dashboard": "a redirect to /apps/freeweight (row WX8)",
    "/apps/freeweight/evidence/export": "a file download",
    "/apps/freeweight/results/export": "a file download",
    "/apps/loadcoach/queue/stream": "an SSE stream",
    "/apps/freeweight/adapters/{adapter}": "needs an adapter a live FreeWeight names",
    "/apps/freeweight/goals/drafts/{draft_id}": "needs a stored goal draft",
    "/apps/freeweight/goals/{slug}": "needs a goal a live FreeWeight names",
    "/apps/freeweight/goals/{slug}/bundle": "a file download",
    "/apps/freeweight/goals/{slug}/calibration": "needs a goal a live FreeWeight names",
    "/apps/freeweight/goals/{slug}/calibration/jobs/{job_id}": "needs a stored calibration job",
    "/apps/freeweight/goals/{slug}/edit": "needs a goal a live FreeWeight names",
    "/apps/freeweight/goals/{slug}/export": "a file download",
    "/apps/freeweight/goals/{slug}/grade": "needs a goal a live FreeWeight names",
    "/apps/freeweight/goals/{slug}/report": "needs a goal a live FreeWeight names",
    "/apps/freeweight/goals/{slug}/report/export": "a file download",
    "/apps/freeweight/machines/{machine_id}": "needs a machine FreeWeight's database holds",
    "/apps/freeweight/models/{model_ref}": "needs a model FreeWeight's database holds",
    "/apps/freeweight/runs/starting/{job_id}": "needs a stored suite-run job",
    "/apps/freeweight/runs/{run_id}": "needs a run FreeWeight's database holds",
    "/apps/freeweight/runs/{run_id}/events": "an SSE stream",
    "/apps/freeweight/runs/{run_id}/grade": "needs a run FreeWeight's database holds",
    "/apps/freeweight/runs/{run_id}/tests/{run_test_id}": "needs a stored run test",
    "/apps/freeweight/samples/{sample_id}": "needs a stored sample",
    "/apps/ideapress/projects/{project_id}": "needs a project a live IdeaPress names",
    "/apps/ideapress/projects/{project_id}/export": "needs a project a live IdeaPress names",
    "/apps/ideapress/projects/{project_id}/export/download": "a file download",
    "/apps/ideapress/projects/{project_id}/plan": "needs a project a live IdeaPress names",
    "/apps/ideapress/projects/{project_id}/tasks/{task_id}": "needs a task a live IdeaPress names",
    "/apps/ideapress/projects/{project_id}/tasks/{task_id}/events": "an SSE stream",
    "/apps/ideapress/projects/{project_id}/units/{unit_key}": "needs a unit a live IdeaPress names",
    "/apps/ideapress/projects/{project_id}/workspace": "needs a project a live IdeaPress names",
    "/apps/ideapress/workflows/{workflow_id}": "needs a workflow a live IdeaPress names",
    "/apps/loadcoach/models/{model_ref}": "needs a model a live LoadCoach names",
    "/apps/loadcoach/queue/jobs/{job_id}": "needs a job a live LoadCoach names",
    "/apps/loadcoach/queue/jobs/{job_id}/events": "an SSE stream",
    "/apps/loadcoach/queue/jobs/{job_id}/reply": "a fragment of a job a live LoadCoach names",
    "/apps/loadcoach/routing/decisions/{decision_id}": "needs a decision a live LoadCoach names",
    "/apps/loadcoach/routing/task-profiles/{task}": "needs a task profile a live LoadCoach names",
    "/apps/promptcadence/tools/{name}": "needs a tool a live PromptCadence names",
    "/apps/promptcadence/trajectories/{trajectory_id}": "needs a trajectory PromptCadence names",
    "/apps/promptcadence/trajectories/{trajectory_id}/events": "an SSE stream",
    "/apps/{app}/database/{table}": "needs an application database file on disk",
    "/apps/{app}/prompts/{prompt_id}": "needs a prompt an application's CLI lists",
    "/chat/{conversation_id}": "needs a stored conversation",
    "/chat/{conversation_id}/messages/{message_id}": "a fragment of a stored message",
    "/jobs/{job_id}": "needs a stored job",
    "/jobs/{job_id}/output": "a fragment of a stored job's output",
}
"""Every GET UI route this test does not render, and why. ``{app}`` routes not named here are
rendered once per application."""

QUERIES: dict[str, str] = {"/docs/page": "?path=README.md"}
"""Routes that need a query string to be a page at all."""

_NAV = re.compile(r'<nav class="([^"]*)"[^>]*>(.*?)</nav>', re.DOTALL)
_HREF = re.compile(r'href="([^"]*)"')


def _console(tmp_path: Path) -> Console:
    lines = []
    for app in APPS:
        executable, _config, _document = fake_application(tmp_path / "apps", app)
        # Port 9 (discard) refuses: no test reaches the operator's running applications.
        lines.append(
            f'[apps.{app}]\nexecutable = "{executable}"\nbase_url = "http://127.0.0.1:9"\n'
        )
    lines.append('[host]\nollama_base_url = "http://127.0.0.1:9"\n')
    console = build_console(tmp_path / "console", extra_toml="".join(lines))
    console.login()
    return console


def _ui_paths(console: Console) -> tuple[list[str], list[str]]:
    """``(paths to render, table paths neither rendered nor named)``."""
    rendered: list[str] = []
    unaccounted: list[str] = []
    for path, route in api_routes(console.client.app):
        if (
            "GET" not in (route.methods or ())
            or path.startswith("/api/")
            or path in NOT_A_SHELL_PAGE
        ):
            continue
        if "{" not in path:
            rendered.append(path + QUERIES.get(path, ""))
        elif path.startswith("/apps/{app}") and path.count("{") == 1:
            rendered.extend(path.replace("{app}", app) for app in APPS)
        else:
            unaccounted.append(path)
    return sorted(rendered), unaccounted


def _hrefs(page: str, css_class: str) -> set[str]:
    return {
        href
        for classes, body in _NAV.findall(page)
        if css_class in classes.split()
        for href in _HREF.findall(body)
    }


_CURRENT_HREF = re.compile(r'href="([^"]*)" aria-current="page"')


def _selected_href(page: str, css_class: str) -> str | None:
    """The one ``href`` of ``css_class`` marked ``aria-current="page"``, or ``None``."""
    for classes, body in _NAV.findall(page):
        if css_class in classes.split():
            match = _CURRENT_HREF.search(body)
            if match:
                return match.group(1)
    return None


def rendered_pages(console: Console) -> dict[str, str]:
    """Every renderable GET UI page, by path, as its HTML. Shared by the catalog's link test."""
    paths, unaccounted = _ui_paths(console)
    assert not unaccounted, f"render these or name them in NOT_A_SHELL_PAGE: {unaccounted}"
    pages: dict[str, str] = {}
    for path in paths:
        response = console.client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 200, (path, response.status_code)
        pages[path] = response.text
    return pages


def test_no_page_bar_link_repeats_the_left_menu(tmp_path: Path) -> None:
    pages = rendered_pages(_console(tmp_path))
    assert len(pages) > 60  # the route table was actually read
    for path, page in pages.items():
        side = _hrefs(page, "side-nav")
        assert side, f"{path} renders no left menu"
        # A bar link to the page's own (selected) left-menu entry is "you are here" twice, not a
        # repeat — e.g. every database subpage selects the left menu's single Database entry
        # (Tables' URL), so the bar's Tables link repeats it on Query and Admin too, not just on
        # Tables itself (row WY9). Allowing exactly the selected entry is the one exception this
        # rule needs. Flagged for WY10.
        repeated = (_hrefs(page, "page-nav") & side) - {_selected_href(page, "side-nav")}
        assert not repeated, f"{path}: page bar repeats the left menu: {sorted(repeated)}"


def test_every_name_in_the_skip_list_is_a_real_route(tmp_path: Path) -> None:
    """A stale entry would hide nothing today and a real page tomorrow."""
    console = build_console(tmp_path)
    table = {
        path for path, route in api_routes(console.client.app) if "GET" in (route.methods or ())
    }
    assert set(NOT_A_SHELL_PAGE) <= table, set(NOT_A_SHELL_PAGE) - table


def _macro(source: str) -> str:
    return templates().from_string('{% from "_app_page.html" import page_nav %}' + source).render()


def test_the_bar_renders_nothing_when_it_has_nothing() -> None:
    assert _macro("{{ page_nav() }}").strip() == ""


def test_the_bar_marks_the_current_link_and_puts_actions_at_its_end() -> None:
    markup = _macro(
        '{{ page_nav(links=[{"label": "Queue", "href": "/q", "current": true},'
        ' {"label": "History", "href": "/h"}], actions=[{"label": "JSON", "href": "/j"}]) }}'
    )
    assert '<nav class="page-nav" aria-label="Page sections">' in markup
    assert '<a href="/q" aria-current="page">Queue</a>' in markup
    assert '<a href="/h">History</a>' in markup
    assert markup.index('class="page-nav-links"') < markup.index('class="page-nav-actions"')
    assert '<a href="/j">JSON</a>' in markup


def test_actions_alone_render_a_bar_with_no_links_list() -> None:
    markup = _macro('{{ page_nav(actions=[{"label": "Docs", "href": "/docs"}]) }}')
    assert "page-nav-actions" in markup
    assert "page-nav-links" not in markup

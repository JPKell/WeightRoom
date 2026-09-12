"""The page kit's shared macros, rendered on their own (`_app_page.html`, row WP1 and row WX3).

`app_page_header` has no caller in this build: the rows that compose the application pages over
it are WX1, WX7 and WX8, and this row owns the macro but not those templates. A macro nothing
renders is a macro nobody has proved renders, so it is exercised here instead — including the
branch that matters most, which is that a stopped application's pill reaches the header verbatim.
"""

from __future__ import annotations

import pytest

from weightroom.services.apps import AppView
from weightroom.services.processes import UnitState
from weightroom.web.rendering import templates

HEADER = """{% from "_app_page.html" import app_page_header %}
{% call app_page_header(view, "Runs", "Workspace", "One model against one suite.") %}
<a href="/apps/freeweight/models">Models</a>
{% endcall %}"""

BARE = """{% from "_app_page.html" import app_page_header %}
{{ app_page_header(view, "Runs", "Workspace", "") }}"""


def _view(*, unit_state: UnitState, verdict: str = "ok") -> AppView:
    return AppView(
        name="freeweight",
        installed=True,
        executable="/usr/bin/freeweight",
        unit=" freeweight.service",
        unit_state=unit_state,
        uptime_seconds=None,
        restarts=0,
        base_url="http://127.0.0.1:8765",
        version="1.2.1",
        api_version="v1",
        verdict=verdict,
        supported_range=">=1.0,<2",
    )


def _render(source: str, view: AppView) -> str:
    return templates().from_string(source).render(view=view)


def test_the_header_names_where_the_page_sits_its_title_and_the_callers_actions() -> None:
    markup = _render(HEADER, _view(unit_state="active"))
    assert '<p class="app-page-eyebrow">FreeWeight / Workspace</p>' in markup
    assert '<h2 class="app-page-title">Runs</h2>' in markup
    assert "One model against one suite." in markup
    assert '<nav class="page-actions app-page-actions" aria-label="Runs actions">' in markup
    assert '<a href="/apps/freeweight/models">Models</a>' in markup


@pytest.mark.parametrize(
    ("unit_state", "pill", "tone"),
    [
        ("active", "ok", "success"),
        ("inactive", "stopped", "neutral"),
        ("failed", "failed", "danger"),
    ],
)
def test_availability_is_the_pill_and_tone(unit_state: UnitState, pill: str, tone: str) -> None:
    """Not a friendlier two-state guess: the states are operationally different answers."""
    markup = _render(HEADER, _view(unit_state=unit_state))
    assert f'<span class="badge status-{tone}" title="{unit_state}">{pill}</span>' in markup
    assert '<span class="app-page-availability-label">Availability</span>' in markup


def test_without_a_caller_the_header_renders_no_empty_action_bar() -> None:
    markup = _render(BARE, _view(unit_state="active"))
    assert "app-page-actions" not in markup
    assert "app-page-supporting" not in markup  # an empty sentence is no sentence
    assert '<h2 class="app-page-title">Runs</h2>' in markup

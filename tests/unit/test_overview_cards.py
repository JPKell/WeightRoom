"""Row WY3: the console's ``/`` cards — ``status_figures``, ``AppCard`` and ``overview_cards``.

``status_figures`` is the fetch-and-map half of :func:`overview_for`'s running branch, pulled out
so ``/`` can reuse it without a database (module docstring, §2.1 of the roadmap row). These tests
cover the wrapper's own contract (dash on down, never a crash); the field mapping itself is already
proven against the recorded bodies by ``test_overview_status_bodies.py``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import respx

from weightroom.config import load_settings
from weightroom.services.apps import AppView
from weightroom.services.overview import overview_cards, status_figures

STATUS = Path(__file__).resolve().parents[1] / "fixtures" / "status"
LOADCOACH_URL = "http://127.0.0.1:8766"
PROMPTCADENCE_URL = "http://127.0.0.1:8768"
FREEWEIGHT_URL = "http://127.0.0.1:8765"
_BASE_URL = {
    "loadcoach": LOADCOACH_URL,
    "promptcadence": PROMPTCADENCE_URL,
    "freeweight": FREEWEIGHT_URL,
    "ideapress": "http://127.0.0.1:8767",
}


def _body(app: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((STATUS / f"{app}.json").read_text(encoding="utf-8"))
    return body


def _view(
    app: str, *, installed: bool = True, running: bool, reachable: bool, error: str | None = None
) -> AppView:
    return AppView(
        name=app,
        installed=installed,
        executable="/bin/true" if installed else None,
        unit=f"{app}.service",
        unit_state="active" if running else "inactive",
        uptime_seconds=120.0 if running else None,
        restarts=0,
        base_url=_BASE_URL[app],
        version="1.0.0" if reachable else None,
        api_version="v1" if reachable else None,
        verdict="ok" if reachable else "unreadable",
        error=error,
    )


def _settings(tmp_path: Path) -> Any:
    config = tmp_path / "console.toml"
    config.write_text("")
    return load_settings(config_path=config).settings


@respx.mock
def test_running_and_reachable_reads_the_same_figures_as_the_overview_page(tmp_path: Path) -> None:
    respx.get(f"{LOADCOACH_URL}/api/v1/system/status").mock(
        return_value=httpx.Response(200, json=_body("loadcoach"))
    )
    view = _view("loadcoach", running=True, reachable=True)
    figures = {
        f.label: f.value
        for f in status_figures(
            "loadcoach", view, settings=_settings(tmp_path), client=httpx.Client()
        )
    }
    assert figures == {"Active": "0", "Oldest queued": "—", "Starving": "0"}


def test_stopped_renders_every_figure_as_a_dash_with_no_call(tmp_path: Path) -> None:
    view = _view("loadcoach", installed=True, running=False, reachable=False)
    with respx.mock:  # no routes registered — a call would raise, proving none is made
        figures = status_figures(
            "loadcoach", view, settings=_settings(tmp_path), client=httpx.Client()
        )
    assert all(f.value == "—" for f in figures)
    assert {f.label for f in figures} == {"Active", "Oldest queued", "Starving"}


@respx.mock
def test_a_failed_status_call_while_running_renders_dashes_not_a_crash(tmp_path: Path) -> None:
    respx.get(f"{LOADCOACH_URL}/api/v1/system/status").mock(
        side_effect=httpx.ConnectError("refused")
    )
    view = _view("loadcoach", running=True, reachable=True)
    figures = status_figures("loadcoach", view, settings=_settings(tmp_path), client=httpx.Client())
    assert all(f.value == "—" for f in figures)


@respx.mock
def test_overview_cards_names_loadcoach_promptcadence_freeweight_in_that_order(
    tmp_path: Path,
) -> None:
    for app in ("loadcoach", "promptcadence", "freeweight"):
        respx.get(f"{_BASE_URL[app]}/api/v1/system/status").mock(
            return_value=httpx.Response(200, json=_body(app))
        )
    views = [_view(app, running=True, reachable=True) for app in _BASE_URL]
    cards = overview_cards(views, settings=_settings(tmp_path), client=httpx.Client())
    assert [card.app for card in cards] == ["loadcoach", "promptcadence", "freeweight"]
    assert all(card.reason is None for card in cards)
    assert all(card.pill == "ok" for card in cards)


def test_a_stopped_application_gets_a_reason_naming_its_pill(tmp_path: Path) -> None:
    views = [_view("loadcoach", installed=True, running=False, reachable=False)]
    with respx.mock:
        cards = overview_cards(views, settings=_settings(tmp_path), client=httpx.Client())
    assert cards[0].reason == "stopped."
    assert all(f.value == "—" for f in cards[0].figures)


def test_an_unreachable_application_names_its_error_in_the_reason(tmp_path: Path) -> None:
    views = [_view("loadcoach", running=True, reachable=False, error="connection refused")]
    with respx.mock:
        cards = overview_cards(views, settings=_settings(tmp_path), client=httpx.Client())
    assert cards[0].reason == "connection refused."


def test_ideapress_is_not_a_card_out_of_scope(tmp_path: Path) -> None:
    views = [_view("ideapress", running=True, reachable=True, error=None)]
    cards = overview_cards(views, settings=_settings(tmp_path), client=httpx.Client())
    assert cards == ()


@respx.mock
def test_three_status_reads_run_concurrently_not_one_after_another(tmp_path: Path) -> None:
    """A sequential read of three 300 ms calls would take ~900 ms; concurrent, well under that."""
    delay_seconds = 0.3

    def _slow(request: httpx.Request) -> httpx.Response:
        time.sleep(delay_seconds)
        return httpx.Response(200, json=_body("loadcoach"))

    for app in ("loadcoach", "promptcadence", "freeweight"):
        respx.get(f"{_BASE_URL[app]}/api/v1/system/status").mock(side_effect=_slow)
    views = [_view(app, running=True, reachable=True) for app in _BASE_URL]

    started = time.perf_counter()
    overview_cards(views, settings=_settings(tmp_path), client=httpx.Client())
    elapsed = time.perf_counter() - started

    assert elapsed < delay_seconds * 2, f"took {elapsed:.2f}s — the three calls were not concurrent"

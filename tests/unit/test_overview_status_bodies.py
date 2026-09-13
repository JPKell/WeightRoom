"""Row WP2 Gate A: the Overview's figures read each application's real ``GET /system/status``.

The bodies under ``tests/fixtures/status`` are the reference machine's four applications answering
on 2026-09-10 (FreeWeight 1.2, LoadCoach 1.5.0, IdeaPress 1.4, PromptCadence 1.3.3). W3 read field
names none of them serve, so PromptCadence's *Pending approvals* rendered ``[]`` and its *Executing*
and *Planning* rendered ``—``; a list is now counted, and a field that is absent stays ``—``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from weightroom.services.overview import _figures_from_status, _promptcadence_figures

STATUS = Path(__file__).resolve().parents[1] / "fixtures" / "status"


def _body(app: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((STATUS / f"{app}.json").read_text(encoding="utf-8"))
    return body


def _figures(app: str, body: dict[str, Any]) -> dict[str, str]:
    return {figure.label: figure.value for figure in _figures_from_status(app, body)}


@pytest.mark.parametrize(
    ("app", "expected"),
    [
        ("freeweight", {"Active run": "—", "Queue depth": "0", "Disk headroom": "482.0 GiB"}),
        ("loadcoach", {"Active": "0", "Oldest queued": "—", "Starving": "0"}),
        ("ideapress", {"Active stage runs": "0", "Backend": "ollama", "Pinned": "False"}),
        ("promptcadence", {"Executing": "0", "Planning": "0", "Pending approvals": "0"}),
    ],
)
def test_every_figure_reads_a_field_the_recorded_body_serves(
    app: str, expected: dict[str, str]
) -> None:
    assert _figures(app, _body(app)) == expected


def test_promptcadence_counts_active_trajectories_by_state_and_pending_approvals() -> None:
    body = _body("promptcadence")
    body["active_trajectories"] = [
        {"trajectory_id": "a", "state": "executing"},
        {"trajectory_id": "b", "state": "planning"},
        {"trajectory_id": "c", "state": "executing"},
    ]
    body["pending_approvals"] = [{"request_id": "r1"}, {"request_id": "r2"}]
    assert _figures("promptcadence", body) == {
        "Executing": "2",
        "Planning": "1",
        "Pending approvals": "2",
    }


def test_oldest_queued_is_a_duration_row_wy3() -> None:
    """LoadCoach's Oldest queued is tagged ``duration`` (row WY3), read by both this page and the
    console's ``/`` cards; a null age still dashes (ADR-0016), never ``0``."""
    body = _body("loadcoach")
    body["oldest_queued_age_seconds"] = 125.0
    assert _figures("loadcoach", body)["Oldest queued"] == "2m 05s"
    body["oldest_queued_age_seconds"] = None
    assert _figures("loadcoach", body)["Oldest queued"] == "—"


def test_a_missing_field_or_a_shape_it_cannot_count_stays_a_dash_never_a_zero() -> None:
    body = _body("promptcadence")
    del body["active_trajectories"]
    body["pending_approvals"] = "not a list"
    assert _figures("promptcadence", body) == {
        "Executing": "—",
        "Planning": "—",
        "Pending approvals": "—",
    }


def test_promptcadence_section_reads_active_pending_and_the_embedded_ledger_view() -> None:
    """Row WX11: the PromptCadence-only Overview section, from the same status body — no second
    call — its ``ledger.day`` is ``ledger_view(trajectory=None).as_json()["day"]`` verbatim."""
    body = _body("promptcadence")
    body["active_trajectories"] = [
        {"trajectory_id": "a", "state": "executing"},
        {"trajectory_id": "b", "state": "planning"},
    ]
    body["pending_approvals"] = [{"request_id": "r1"}]
    figures = {figure.label: (figure.value, figure.note) for figure in _promptcadence_figures(body)}
    assert figures["Active"] == ("2", None)
    assert figures["Pending approvals"] == ("1", None)
    assert figures["Spending today"] == ("at most 20 USD", None)


def test_promptcadence_section_names_an_exceeded_ceiling_and_dashes_a_missing_ledger() -> None:
    body = _body("promptcadence")
    body["ledger"]["day"]["exceeded"] = True
    figures = {figure.label: figure for figure in _promptcadence_figures(body)}
    assert figures["Spending today"].note == "ceiling exceeded"
    del body["ledger"]
    figures = {figure.label: figure for figure in _promptcadence_figures(body)}
    assert figures["Spending today"].value == "—"
    assert figures["Spending today"].note is None

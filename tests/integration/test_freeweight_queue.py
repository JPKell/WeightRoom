"""FreeWeight's runs, queued in view: the New run page, the queue on Runs, the cooldown parameter,
and the Overview's name-only models table, *Active run* link and the unit on System."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import respx

from tests.integration.test_freeweight_pages import (
    BASE,
    CANONICAL,
    fixture,
    freeweight_console,
    mock_api,
    page,
    route_for,
)
from tests.support import fill_rows
from weightroom.services.jobs import list_jobs
from weightroom.services.overview import _figures_from_status

if TYPE_CHECKING:
    from pathlib import Path

    from tests.support import Console

SUITE_RUN = "freeweight_suite_run"


def _queue_one(console: Console, **fields: str) -> Any:  # noqa: ANN401 — an httpx Response
    return console.post_form(
        f"{BASE}/runs",
        {"model": CANONICAL, "suite": "native.echo", "next": "new", **fields},
    )


def test_new_run_queues_one_run_and_comes_back_to_the_queue(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        empty = page(console, f"{BASE}/runs/new")
        assert 'name="next" value="new"' in empty
        assert "Nothing is queued." in empty

        response = _queue_one(console, label="first", cooldown_seconds="45")
        (job,), _ = list_jobs(console.database, limit=5, kind=SUITE_RUN)
        assert response.status_code == 303
        assert response.headers["location"] == f"{BASE}/runs/new?queued={job.id}#queue"
        assert job.params["cooldown_seconds"] == 45

        queued = page(console, f"{BASE}/runs/new?queued={job.id}")
        runs = page(console, f"{BASE}/runs")
    assert f'action="/jobs/{job.id}/cancel"' in queued
    assert "first" in queued
    assert f'action="/jobs/{job.id}/cancel"' in runs
    assert 'href="/apps/freeweight/runs/new"' in runs


def test_a_cooldown_that_is_not_seconds_is_refused_on_the_new_run_page(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        response = _queue_one(console, label="kept", cooldown_seconds="soon")
    assert response.status_code == 200
    assert "cooldown_seconds" in response.text
    assert 'name="next" value="new"' in response.text
    assert 'value="kept"' in response.text
    assert list_jobs(console.database, limit=5, kind=SUITE_RUN)[0] == []


def test_cancel_returns_to_the_page_it_was_pressed_on_and_never_off_the_console(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        _queue_one(console)
        _queue_one(console)
    first, second = list_jobs(console.database, limit=5, kind=SUITE_RUN)[0]

    back = console.post_form(f"/jobs/{first.id}/cancel", {"next": f"{BASE}/runs/new"})
    assert back.status_code == 303
    assert back.headers["location"] == f"{BASE}/runs/new"

    away = console.post_form(f"/jobs/{second.id}/cancel", {"next": "//elsewhere.example/"})
    assert away.headers["location"] == f"/jobs/{second.id}"
    states = {job.state for job in list_jobs(console.database, limit=5, kind=SUITE_RUN)[0]}
    assert states == {"cancelled"}


def test_the_overview_shows_models_by_name_and_the_unit_moved_to_system(tmp_path: Path) -> None:
    console, database = freeweight_console(tmp_path, state="active")
    digest = "sha256:" + "ab" * 32
    fill_rows(
        database,
        "models",
        [
            {
                "id": "01MODELROW0000000000000000A",
                "provider_kind": "llamacpp",
                "provider_model_name": "Qwen2.5-1.5B-Instruct.Q8_0",
                "artifact_digest": digest,
                "canonical_id": f"llamacpp/Qwen2.5-1.5B-Instruct.Q8_0@{digest}",
                "identity_confidence": "digest",
            }
        ],
    )
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route_for(router, "GET", "health").mock(
            return_value=httpx.Response(200, json=fixture("health"))
        )
        overview = page(console, BASE)
        system = page(console, f"{BASE}/system")
    primary = overview[overview.index('data-table="overview-primary"') :]
    shown = primary[: primary.index("</table>")]
    assert ">Provider<" in shown
    assert ">Model<" in shown
    assert "Qwen2.5-1.5B-Instruct.Q8_0" in shown
    for hidden in ("artifact_digest", "identity_confidence", "canonical_id", digest, "01MODELROW"):
        assert hidden not in shown, hidden
    assert "The unit" not in overview
    assert "The unit" in system


def test_the_active_run_card_links_to_the_run() -> None:
    run_id = "01M2EGKEK7ZTW3CJ131A23Q4MT"
    active, depth, _disk = _figures_from_status(
        "freeweight", {"active_run": run_id, "queue_depth": 2}
    )
    assert active.value == run_id
    assert active.href == f"{BASE}/runs/{run_id}"
    assert depth.href is None
    assert _figures_from_status("freeweight", {"active_run": None})[0].href is None

"""The Jobs API and pages (api.md §7): queue, cancel, schedules, the two security actions, a pull.

No worker runs here — the web lifespan is never entered — so a queued job stays queued unless a test
moves it through the service functions itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select

from tests.support import JSON_HEADERS, PASSWORD, Console, build_console
from weightroom.infrastructure.db.models import AuditLog
from weightroom.services.db_reader import DatabaseUrlCache
from weightroom.services.jobs import claim_next, finish
from weightroom.services.processes import FakeSystemdController

if TYPE_CHECKING:
    from pathlib import Path

HTML = {"Accept": "text/html"}


def _console(tmp_path: Path) -> Console:
    console = build_console(tmp_path)
    console.login()
    return console


def _post(console: Console, path: str, body: dict[str, Any]) -> Any:  # noqa: ANN401 — a Response
    return console.client.post(path, json=body, headers=JSON_HEADERS)


def _schedule(console: Console, kind: str) -> dict[str, Any]:
    body = console.client.get("/api/v1/jobs/schedules").json()
    return next(one for one in body["schedules"] if one["kind"] == kind)


def _audit(console: Console, action: str) -> list[tuple[str, str | None]]:
    with console.database.read() as session:
        rows = session.execute(select(AuditLog).where(AuditLog.action == action)).scalars()
        return [(row.outcome, row.message) for row in rows]


def test_a_job_is_queued_shown_listed_and_cancelled(tmp_path: Path) -> None:
    console = _console(tmp_path)
    created = _post(console, "/api/v1/jobs", {"kind": "docs_index"})
    assert created.status_code == 202, created.text
    job = created.json()
    assert (job["kind"], job["state"], job["params"]) == ("docs_index", "queued", {})
    assert console.client.get(f"/api/v1/jobs/{job['id']}").json()["state"] == "queued"
    listed = console.client.get("/api/v1/jobs?state=queued").json()
    assert [one["id"] for one in listed["items"]] == [job["id"]]

    cancelled = _post(console, f"/api/v1/jobs/{job['id']}/cancel", {})
    assert cancelled.json()["state"] == "cancelled"
    again = _post(console, f"/api/v1/jobs/{job['id']}/cancel", {})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "JOB_INVALID_STATE"
    missing = console.client.get("/api/v1/jobs/01NOSUCHJOB000000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "JOB_NOT_FOUND"
    assert [outcome for outcome, _message in _audit(console, "job.cancel")] == ["ok", "refused"]


def test_a_job_its_kind_refuses_is_a_400_and_an_audited_refusal(tmp_path: Path) -> None:
    console = _console(tmp_path)
    refused = _post(console, "/api/v1/jobs", {"kind": "docs_index", "params": {"root": "/"}})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "VALIDATION_ERROR"
    assert [outcome for outcome, _message in _audit(console, "job.enqueue")] == ["refused"]


def test_restoring_weightroomgyms_own_database_needs_a_fresh_password_and_its_name(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    body: dict[str, Any] = {"kind": "self_restore", "params": {"file": "manual-x.sqlite3"}}
    first = _post(console, "/api/v1/jobs", body)
    assert first.status_code == 403
    assert first.json()["error"]["code"] == "REAUTH_REQUIRED"
    assert _post(console, "/api/v1/reauth", {"password": PASSWORD}).status_code == 200
    unnamed = _post(console, "/api/v1/jobs", body)
    assert unnamed.status_code == 400
    assert "Type weightroom" in unnamed.json()["error"]["message"]
    named = _post(console, "/api/v1/jobs", {**body, "name_typed": "weightroom"})
    assert named.status_code == 202, named.text
    assert [outcome for outcome, _message in _audit(console, "job.enqueue")] == [
        "refused",
        "refused",
        "ok",
    ]


def test_schedules_are_in_utc_and_enabling_one_validates_it_and_it_can_run_now(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    assert console.client.get("/api/v1/jobs/schedules").json()["timezone"] == "UTC"
    suite = _schedule(console, "freeweight_suite_run")
    path = f"/api/v1/jobs/schedules/{suite['id']}"
    refused = console.client.put(path, json={"enabled": True}, headers=JSON_HEADERS)
    assert refused.status_code == 400
    enabled = console.client.put(
        path,
        json={
            "enabled": True,
            "cron": "0 2 * * *",
            "params": {"model": "ollama/qwen3:8b", "suite": "native.performance"},
        },
        headers=JSON_HEADERS,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["next_run_at"] == "2026-09-10T02:00:00+00:00"
    now = _post(console, "/api/v1/jobs", {"schedule_id": suite["id"]})
    assert now.status_code == 202
    assert (now.json()["kind"], now.json()["schedule_id"]) == ("freeweight_suite_run", suite["id"])


def test_a_retention_schedule_that_deletes_freeweight_results_needs_a_fresh_password(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path)
    trim = _schedule(console, "retention_trim")
    body = {"params": {"guarded_backup_days": 90, "freeweight_older_than_days": 30}}
    path = f"/api/v1/jobs/schedules/{trim['id']}"
    assert console.client.put(path, json=body, headers=JSON_HEADERS).status_code == 403
    _post(console, "/api/v1/reauth", {"password": PASSWORD})
    assert console.client.put(path, json=body, headers=JSON_HEADERS).status_code == 200


def test_the_pages_render_and_a_running_jobs_output_is_polled(tmp_path: Path) -> None:
    console = _console(tmp_path)
    page = console.client.get("/jobs", headers=HTML)
    assert page.status_code == 200
    assert "Schedules" in page.text
    assert "freeweight_suite_run" in page.text
    job = _post(console, "/api/v1/jobs", {"kind": "docs_index"}).json()
    detail = console.client.get(f"/jobs/{job['id']}", headers=HTML)
    assert detail.status_code == 200
    assert f'hx-get="/jobs/{job["id"]}/output"' in detail.text
    claimed = claim_next(console.database, now=console.now, lease_seconds=60)
    assert claimed is not None
    finish(
        console.database,
        job["id"],
        state="completed",
        now=console.now,
        output="indexed 12 documents\n",
        error=None,
    )
    fragment = console.client.get(f"/jobs/{job['id']}/output", headers=HTML)
    assert "indexed 12 documents" in fragment.text
    assert "hx-trigger" not in fragment.text


def test_the_page_forms_queue_a_job_and_save_a_schedule(tmp_path: Path) -> None:
    console = _console(tmp_path)
    queued = console.post_form("/jobs/enqueue", {"kind": "docs_index", "params": ""})
    assert queued.status_code == 303
    assert queued.headers["location"].startswith("/jobs/")
    docs = _schedule(console, "docs_index")
    saved = console.post_form(
        f"/jobs/schedules/{docs['id']}", {"cron": "0 5 * * *", "params": "{}", "enabled": "true"}
    )
    assert saved.status_code == 200
    assert "docs_index saved: next run 2026-09-10 05:00 UTC" in saved.text
    bad = console.post_form("/jobs/enqueue", {"kind": "docs_index", "params": "not json"})
    assert bad.status_code == 200
    assert "not JSON" in bad.text


def test_a_stored_catalog_pull_job_still_lists_renders_and_fails_cleanly(tmp_path: Path) -> None:
    """ADR-0146: the kind can no longer be queued, and a row the catalog left behind never 500s.

    The row is written as W9 wrote it, with no route: `enqueue` now refuses the kind.
    """
    from weightroom.infrastructure.db.models import Job
    from weightroom.services.jobs import JobServices, JobWorker

    console = _console(tmp_path)
    refused = _post(console, "/api/v1/jobs", {"kind": "catalog_pull", "params": {"name": "x"}})
    assert refused.status_code == 400
    with console.database.write() as session:
        session.add(
            Job(
                id="01HISTORICALPULL0000000001",
                kind="catalog_pull",
                params={"name": "gemma3:1b"},
                state="completed",
                queued_at=console.now,
                output="pulling manifest\nsuccess",
            )
        )
        session.add(
            Job(id="01HISTORICALPULL0000000002", kind="catalog_pull", params={"name": "qwen3:8b"},
                state="queued", queued_at=console.now)
        )  # fmt: skip
    for path in ("/jobs", "/jobs/01HISTORICALPULL0000000001", "/jobs/01HISTORICALPULL0000000002"):
        page = console.client.get(path, headers={"Accept": "text/html"})
        assert page.status_code == 200, path
        assert "catalog_pull" in page.text, path
    detail = console.client.get("/api/v1/jobs/01HISTORICALPULL0000000001")
    assert detail.status_code == 200
    assert detail.json()["kind"] == "catalog_pull"
    listed = console.client.get("/api/v1/jobs")
    assert listed.status_code == 200
    assert "01HISTORICALPULL0000000002" in listed.text
    # A queued one left behind is failed by the worker with its reason, not crashed on.
    worker = JobWorker(
        console.database,
        console.settings,
        JobServices(
            controller=FakeSystemdController(), http=httpx.Client(), urls=DatabaseUrlCache()
        ),
        clock=lambda: console.now,
    )
    worker.run_once()
    failed = console.client.get("/api/v1/jobs/01HISTORICALPULL0000000002").json()
    assert failed["state"] == "failed"
    assert "no executor for kind 'catalog_pull'" in failed["error"]

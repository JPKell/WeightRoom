"""The guard and the curated operations over HTTP: JSON and the table page's forms, against a fake
FreeWeight whose `config show` names a fixture copy and whose port is closed."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tests.support import (
    JSON_HEADERS,
    PASSWORD,
    Console,
    build_console,
    fake_application,
    fill_rows,
    fixture_database,
)
from weightroom.services.audit import list_audit
from weightroom.services.processes import FakeSystemdController, UnitState

HTML = {"Accept": "text/html"}
SQL = "DELETE FROM samples WHERE run_test_id = 'RT1'"


def _console(
    tmp_path: Path,
    *,
    app: str = "freeweight",
    fixture: str = "freeweight-0009",
    state: UnitState = "inactive",
) -> Console:
    path = fixture_database(tmp_path, fixture)
    if app == "freeweight":
        fill_rows(
            path,
            "samples",
            [
                {
                    "id": f"01SAMPLE{index:018d}",
                    "run_test_id": "RT1" if index < 3 else "RT2",
                    "ordinal": index,
                    "status": "completed",
                }
                for index in range(5)
            ],
        )
    executable, _config, _document = fake_application(
        tmp_path, app, database_url=f"sqlite:///{path}"
    )
    console = build_console(
        tmp_path / "console",
        extra_toml=(
            f'[apps.{app}]\nexecutable = "{executable}"\nbase_url = "http://127.0.0.1:9"\n'
        ),
        systemd=FakeSystemdController(states={f"{app}.service": state}),
    )
    console.login()
    return console


def _post(console: Console, path: str, body: dict[str, Any]) -> Any:  # noqa: ANN401
    return console.client.post(path, json=body, headers=JSON_HEADERS)


def test_the_json_guard_dry_runs_refuses_without_reauth_then_writes(tmp_path: Path) -> None:
    console = _console(tmp_path)
    dry = _post(console, "/api/v1/apps/freeweight/db/write/dry-run", {"sql": SQL}).json()
    assert (dry["row_count"], dry["tables"], dry["unit_state"]) == (3, ["samples"], "inactive")
    assert [one["verdict"] for one in dry["checklist"]][:3] == ["pass", "pending", "pass"]
    body = {"sql": SQL, "tables_typed": ["samples"], "dry_run_id": dry["dry_run_id"]}
    stale = _post(console, "/api/v1/apps/freeweight/db/write", body)
    assert (stale.status_code, stale.json()["error"]["code"]) == (403, "REAUTH_REQUIRED")
    _post(console, "/api/v1/reauth", {"password": PASSWORD})
    written = _post(console, "/api/v1/apps/freeweight/db/write", body)
    assert written.status_code == 200, written.text
    result = written.json()
    assert result["row_count"] == 3 and Path(result["backup_path"]).is_file()
    row = console.client.get(f"/api/v1/audit/{result['audit_id']}", headers=JSON_HEADERS).json()
    assert (row["outcome"], row["dry_run_count"], row["actual_count"], row["statement"]) == (
        "ok",
        3,
        3,
        SQL,
    )
    assert row["backup_path"] == result["backup_path"]
    backups = console.client.get("/api/v1/apps/freeweight/db/backups", headers=JSON_HEADERS)
    assert backups.json()["backups"][0]["path"] == result["backup_path"]
    again = _post(console, "/api/v1/apps/freeweight/db/write", body)
    assert (again.status_code, again.json()["error"]["details"]["condition"]) == (409, 3)


def test_with_the_application_running_the_dry_run_shows_condition_one_red_and_the_write_refuses(
    tmp_path: Path,
) -> None:
    console = _console(tmp_path, state="active")
    dry = _post(console, "/api/v1/apps/freeweight/db/write/dry-run", {"sql": SQL})
    assert dry.status_code == 200
    assert (dry.json()["row_count"], dry.json()["checklist"][0]["verdict"]) == (None, "fail")
    _post(console, "/api/v1/reauth", {"password": PASSWORD})
    body = {"sql": SQL, "tables_typed": ["samples"], "dry_run_id": "x"}
    refused = _post(console, "/api/v1/apps/freeweight/db/write", body)
    error = refused.json()["error"]
    assert (refused.status_code, error["code"], error["details"]["condition"]) == (
        409,
        "GUARD_APP_RUNNING",
        1,
    )
    outcomes = [
        (row.action, row.outcome)
        for row in list_audit(console.database, limit=10, app="freeweight")[0]
    ]
    assert ("db.dry_run", "refused") in outcomes and ("db.guarded_write", "refused") in outcomes


def test_update_routing_decisions_is_refused_by_name(tmp_path: Path) -> None:
    console = _console(tmp_path, app="loadcoach", fixture="loadcoach-0015")
    refused = _post(
        console,
        "/api/v1/apps/loadcoach/db/write/dry-run",
        {"sql": "UPDATE routing_decisions SET reason = 'tidied' WHERE id = '01DECISION'"},
    )
    error = refused.json()["error"]
    assert (refused.status_code, error["code"], error["details"]["table"]) == (
        403,
        "GUARD_TABLE_LOCKED",
        "routing_decisions",
    )
    assert "never writable from WeightRoomGym (ADR-0124)" in error["message"]


def test_the_table_page_runs_the_guard_dialog_end_to_end(tmp_path: Path) -> None:
    console = _console(tmp_path)
    page = console.client.get("/apps/freeweight/database/samples", headers=HTML).text
    assert 'href="/apps/freeweight/database/admin#delete-results">Delete stored results' in page
    assert page.index("own operations for samples") < page.index("Raw write — the guard")
    dried = console.post_form("/apps/freeweight/database/samples/write/dry-run", {"sql": SQL})
    assert "<strong>3 rows</strong>, rolled back." in dried.text
    assert "1. The application is stopped" in dried.text
    identifier = re.search(r'name="dry_run_id" value="([0-9a-f]{32})"', dried.text)
    assert identifier is not None
    mistyped = console.post_form(
        "/apps/freeweight/database/samples/write",
        {
            "sql": SQL,
            "dry_run_id": identifier.group(1),
            "tables_typed": "sample",
            "password": PASSWORD,
        },
    )
    assert "GUARD_TABLE_MISMATCH</code> · condition 4" in mistyped.text
    written = console.post_form(
        "/apps/freeweight/database/samples/write",
        {
            "sql": SQL,
            "dry_run_id": identifier.group(1),
            "tables_typed": "samples",
            "password": PASSWORD,
        },
    )
    assert "Written: 3 rows." in written.text and "-guarded-write.sqlite3" in written.text
    locked = console.client.get("/apps/freeweight/database/run_events", headers=HTML).text
    assert "/apps/freeweight/database/run_events/write/dry-run" not in locked


def test_the_applications_own_operations_run_first_and_restore_is_guarded(tmp_path: Path) -> None:
    console = _console(tmp_path)
    source = str(tmp_path / "freeweight-backup.sqlite3")
    backup = _post(console, "/api/v1/apps/freeweight/db/backup", {}).json()
    assert backup["ok"] is True and backup["argv"][1:] == ["db", "backup", "--json"]
    status = console.client.get("/api/v1/apps/freeweight/db/status", headers=JSON_HEADERS).json()
    assert status["argv"][1:] == ["db", "status", "--json"]
    wrong = _post(
        console,
        "/api/v1/apps/freeweight/db/restore",
        {"file": source, "name_typed": "freeweight"},
    )
    assert wrong.json()["error"]["code"] == "REAUTH_REQUIRED"
    _post(console, "/api/v1/reauth", {"password": PASSWORD})
    mistyped = _post(
        console,
        "/api/v1/apps/freeweight/db/restore",
        {"file": source, "name_typed": "Freeweight"},
    )
    assert (mistyped.status_code, mistyped.json()["error"]["code"]) == (400, "VALIDATION_ERROR")
    restored = _post(
        console,
        "/api/v1/apps/freeweight/db/restore",
        {"file": source, "name_typed": "freeweight"},
    ).json()
    assert restored["ok"] is True and restored["argv"][-2:] == ["--yes", source]
    assert console.host is not None
    console.host.states["freeweight.service"] = "active"
    running = _post(
        console,
        "/api/v1/apps/freeweight/db/restore",
        {"file": source, "name_typed": "freeweight"},
    )
    assert running.json()["error"]["code"] == "GUARD_APP_RUNNING"
    vacuum = console.post_form("/apps/freeweight/database/curated", {"verb": "vacuum"})
    assert "db vacuum --json</code> — done." in vacuum.text
    nothing = console.post_form("/apps/freeweight/database/curated", {"verb": "drop"})
    assert "freeweight offers no `db drop`" in nothing.text
    rows, _more = list_audit(console.database, limit=20, action="db.curated")
    assert [row.outcome for row in rows] == [
        "refused",
        "ok",
        "refused",
        "ok",
        "refused",
        "refused",
        "ok",
    ]


def test_freeweights_own_deletion_is_previewed_typed_reauthenticated_and_audited(
    tmp_path: Path, respx_mock: Any
) -> None:
    import json

    import httpx

    console = _console(tmp_path, state="active")  # FreeWeight's own deletion runs with it up
    respx_mock.get("http://127.0.0.1:9/api/v1/version").mock(
        side_effect=httpx.ConnectError("closed")  # the shell's version probe
    )
    preview = {
        "selection": {"scope": "model", "selector": "qwen3"},
        "run_ids": ["01RUN"],
        "run_count": 1,
        "removed_counts": {"runs": 1, "run_events": 4},
        "preserved_counts": {"models": 1},
        "total_rows": 5,
        "token": "tok",
        "will_backup": False,
    }
    respx_mock.post("http://127.0.0.1:9/api/v1/database/delete-preview").mock(
        return_value=httpx.Response(200, json=preview)
    )
    stale_token = {"error": {"code": "DATABASE_ERROR", "message": "stale token"}}
    deleted = respx_mock.delete("http://127.0.0.1:9/api/v1/database/results").mock(
        side_effect=[
            httpx.Response(200, json={"run_count": 1, "total_rows": 5, "backup_path": None}),
            httpx.Response(400, json=stale_token),
        ]
    )
    page = console.client.get("/apps/freeweight/database/runs", headers=HTML).text
    assert page.index("Delete stored results") < page.index("Raw write — the guard")
    shown = console.post_form(
        "/apps/freeweight/database/curated",
        {"verb": "delete-results", "scope": "model", "selector": "qwen3"},
    ).text
    assert 'name="token" value="tok"' in shown and "Type <code>qwen3</code>" in shown
    route = "/api/v1/apps/freeweight/db/delete-results"
    body = {"scope": "model", "selector": "qwen3", "token": "tok", "typed": "qwen3"}
    assert _post(console, route, body).json()["error"]["code"] == "REAUTH_REQUIRED"
    _post(console, "/api/v1/reauth", {"password": PASSWORD})
    mistyped = _post(console, route, {**body, "typed": "qwen"})
    assert (mistyped.status_code, mistyped.json()["error"]["code"]) == (400, "VALIDATION_ERROR")
    done = _post(console, route, body).json()
    assert (done["verb"], done["ok"], done["output"]["total_rows"]) == ("delete-results", True, 5)
    assert json.loads(deleted.calls.last.request.content) == {
        "scope": "model",
        "selector": "qwen3",
        "token": "tok",
    }
    refused = _post(console, route, body).json()
    assert (refused["ok"], refused["error"]) == (False, "freeweight refused: stale token")
    other = _post(console, "/api/v1/apps/loadcoach/db/delete-results", {"scope": "model"})
    assert other.json()["error"]["code"] == "VALIDATION_ERROR"
    rows, _more = list_audit(console.database, limit=10, action="db.curated")
    assert [(row.app, row.target, row.outcome, row.security) for row in rows] == [
        ("loadcoach", "delete-results", "refused", False),
        ("freeweight", "delete-results", "failed", True),
        ("freeweight", "delete-results", "ok", True),
        ("freeweight", "delete-results", "refused", True),
        ("freeweight", "delete-results", "refused", True),
        ("freeweight", "delete-preview", "ok", False),
    ]

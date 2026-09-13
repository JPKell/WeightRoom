"""The database pages and routes, over a fake application whose ``config show`` names a copy of a
committed fixture database (plan Phase 7 criterion 1, against fixtures)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.support import (
    JSON_HEADERS,
    Console,
    build_console,
    fake_application,
    fill_rows,
    fixture_database,
)
from weightroom.services.audit import list_audit

HTML = {"Accept": "text/html"}


def _console(
    tmp_path: Path, *, app: str = "freeweight", fixture: str | None = "freeweight-0009"
) -> tuple[Console, Path | None]:
    path = None if fixture is None else fixture_database(tmp_path, fixture)
    executable, _config, _document = fake_application(
        tmp_path, app, database_url=None if path is None else f"sqlite:///{path}"
    )
    console = build_console(
        tmp_path / "console", extra_toml=f'[apps.{app}]\nexecutable = "{executable}"\n'
    )
    console.login()
    return console, path


def _three_samples(path: Path | None) -> None:
    assert path is not None
    fill_rows(
        path,
        "samples",
        [
            {"id": f"01SAMPLE{index:018d}", "ordinal": index, "status": status}
            for index, status in enumerate(("completed", "failed", "completed"))
        ],
    )


def test_revision_tables_and_rows_answer_in_json(tmp_path: Path) -> None:
    console, path = _console(tmp_path)
    _three_samples(path)
    client = console.client
    revision = client.get("/api/v1/apps/freeweight/db/revision", headers=JSON_HEADERS).json()
    assert (revision["alembic_version"], revision["known"]) == ("0009", True)
    tables = {
        one["name"]: one
        for one in client.get("/api/v1/apps/freeweight/db/tables", headers=JSON_HEADERS).json()[
            "tables"
        ]
    }
    assert (tables["samples"]["rows"], tables["samples"]["writable"]) == (3, True)
    assert tables["run_events"]["writable"] is False
    assert "never writable from WeightRoomGym (ADR-0124)" in tables["run_events"]["reason"]
    rows = client.get(
        "/api/v1/apps/freeweight/db/tables/samples?sort=ordinal&desc=true&column=status&filter=completed",
        headers=JSON_HEADERS,
    ).json()
    ordinal = [one["name"] for one in rows["columns"]].index("ordinal")
    assert (rows["total"], [row[ordinal] for row in rows["rows"]]) == (2, [2, 0])
    missing = client.get("/api/v1/apps/freeweight/db/tables/nope", headers=JSON_HEADERS)
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "NOT_FOUND")
    bad = client.get("/api/v1/apps/freeweight/db/tables/samples?sort=nope", headers=JSON_HEADERS)
    assert (bad.status_code, bad.json()["error"]["code"]) == (400, "VALIDATION_ERROR")
    unknown = client.get("/api/v1/apps/fourweight/db/tables", headers=JSON_HEADERS)
    assert unknown.json()["error"]["code"] == "APP_UNKNOWN"


def test_apps_and_the_machine_view_carry_the_revision(tmp_path: Path) -> None:
    console, _path = _console(tmp_path)
    apps = {
        one["name"]: one
        for one in console.client.get("/api/v1/apps", headers=JSON_HEADERS).json()["apps"]
    }
    assert (apps["freeweight"]["db_revision"], apps["freeweight"]["known"]) == ("0009", True)
    assert (apps["loadcoach"]["db_revision"], apps["loadcoach"]["known"]) == (None, None)
    one = console.client.get("/api/v1/apps/freeweight", headers=JSON_HEADERS).json()
    assert one["db_revision"] == "0009"
    status = console.client.get("/api/v1/system/status", headers=JSON_HEADERS).json()
    assert status["applications"]["freeweight"]["known"] is True
    assert status["applications"]["ideapress"]["db_revision"] is None


def test_the_console_runs_a_select_and_audits_every_attempt(tmp_path: Path) -> None:
    console, path = _console(tmp_path)
    _three_samples(path)
    ok = console.client.post(
        "/api/v1/apps/freeweight/db/query",
        json={"sql": "SELECT count(*) AS n FROM samples"},
        headers=JSON_HEADERS,
    )
    assert (ok.status_code, ok.json()["rows"]) == (200, [[3]])
    refused = console.client.post(
        "/api/v1/apps/freeweight/db/query",
        json={"sql": "DELETE FROM samples"},
        headers=JSON_HEADERS,
    )
    error = refused.json()["error"]
    assert (refused.status_code, error["code"]) == (400, "GUARD_STATEMENT_REFUSED")
    assert error["details"]["keyword"] == "DELETE"
    rows, _more = list_audit(console.database, limit=10, action="db.query")
    assert [(row.outcome, row.statement) for row in rows] == [
        ("refused", "DELETE FROM samples"),
        ("ok", "SELECT count(*) AS n FROM samples"),
    ]
    assert (rows[1].target, rows[1].params) == ("samples", {"rows": 1, "truncated": False})


def test_the_pages_list_tables_page_rows_and_show_a_query_or_its_refusal(tmp_path: Path) -> None:
    console, path = _console(tmp_path)
    _three_samples(path)
    client = console.client
    tables = client.get("/apps/freeweight/database", headers=HTML)
    assert tables.status_code == 200
    assert 'href="/apps/freeweight/database/samples"' in tables.text
    assert "locked" in tables.text and "Event logs" in tables.text
    assert 'aria-current="page"' in tables.text
    grid = client.get("/apps/freeweight/database/samples?sort=ordinal&desc=true", headers=HTML)
    assert grid.status_code == 200
    assert "VARCHAR(26)" in grid.text and "page 1 of 1 · 3 rows" in grid.text
    assert "never writable" not in grid.text
    locked = client.get("/apps/freeweight/database/run_events", headers=HTML)
    assert "run_events is never writable from WeightRoom (ADR-0124)" in locked.text
    bad_sort = client.get("/apps/freeweight/database/samples?sort=nope", headers=HTML)
    assert bad_sort.status_code == 200 and "is not a column of samples" in bad_sort.text
    posted = console.post_form(
        "/apps/freeweight/database/query", {"sql": "SELECT count(*) AS n FROM samples"}
    )
    assert posted.status_code == 200 and re.search(r"1 row\s+in [\d.]+ ms", posted.text)
    dropped = console.post_form("/apps/freeweight/database/query", {"sql": "DROP TABLE samples"})
    assert "GUARD_STATEMENT_REFUSED" in dropped.text and "DROP is refused by name" in dropped.text
    index = client.get("/database", headers=HTML)
    assert index.status_code == 200 and "0009" in index.text and "not installed" in index.text


def test_a_tables_name_seeds_the_query_and_the_page_has_a_three_anchor_nav(
    tmp_path: Path,
) -> None:
    """Row WX2: Tables / Query / Admin, and a table's own name is the seeded-query link — the
    guarded row browser stays a separate ``Browse rows`` link beside it (api.md §3's only path
    to a raw write)."""
    console, path = _console(tmp_path)
    _three_samples(path)
    page = console.client.get("/apps/freeweight/database", headers=HTML).text
    assert '<a href="#db-tables">Tables</a>' in page
    assert '<a href="#db-query">Query</a>' in page
    assert '<a href="#db-admin">Admin</a>' in page
    assert 'id="db-tables"' in page and 'id="db-query"' in page and 'id="db-admin"' in page
    assert (
        'href="/apps/freeweight/database?sql=SELECT%20%2A%20FROM%20samples%20LIMIT%20100'
        '#db-query"' in page
    )
    assert 'href="/apps/freeweight/database/samples">Browse rows</a>' in page

    seeded = console.client.get(
        "/apps/freeweight/database?sql=SELECT+%2A+FROM+samples+LIMIT+100", headers=HTML
    ).text
    assert '<textarea id="db-sql" name="sql"' in seeded
    assert "SELECT * FROM samples LIMIT 100</textarea>" in seeded


def test_an_unknown_revision_degrades_the_pages_by_name_and_refuses_in_json(
    tmp_path: Path,
) -> None:
    console, _path = _console(tmp_path, app="loadcoach", fixture="loadcoach-unknown-9999")
    client = console.client
    tables = client.get("/api/v1/apps/loadcoach/db/tables", headers=JSON_HEADERS)
    error = tables.json()["error"]
    assert (tables.status_code, error["code"]) == (409, "SCHEMA_UNKNOWN")
    assert (error["details"]["found"], error["details"]["known"]) == ("9999", ["0015"])
    query = client.post(
        "/api/v1/apps/loadcoach/db/query", json={"sql": "SELECT 1"}, headers=JSON_HEADERS
    )
    assert query.status_code == 409
    rows, _more = list_audit(console.database, limit=5, action="db.query")
    assert rows[0].outcome == "refused"
    revision = client.get("/api/v1/apps/loadcoach/db/revision", headers=JSON_HEADERS).json()
    assert (revision["alembic_version"], revision["known"]) == ("9999", False)
    for path in ("/apps/loadcoach/database", "/apps/loadcoach/database/feedback"):
        page = client.get(path, headers=HTML)
        assert page.status_code == 200
        assert "Schema at revision 9999 is not known to" in page.text
        assert "SQL console" not in page.text


def test_an_application_with_no_database_to_read_says_why(tmp_path: Path) -> None:
    console, _path = _console(tmp_path, app="ideapress", fixture=None)
    page = console.client.get("/apps/ideapress/database", headers=HTML)
    assert page.status_code == 200 and "No database to read." in page.text
    grid = console.client.get("/apps/ideapress/database/units", headers=HTML)
    assert "No database to read." in grid.text
    tables = console.client.get("/api/v1/apps/ideapress/db/tables", headers=JSON_HEADERS)
    assert (tables.status_code, tables.json()["error"]["code"]) == (502, "APP_UNREACHABLE")


def test_databases_page_prints_the_postgres_bootstrap_script(tmp_path: Path) -> None:
    """Row WX15: the console-wide page names all five apps and never a literal password."""
    console, _path = _console(tmp_path)
    page = console.client.get("/database", headers=HTML)
    assert page.status_code == 200
    text = page.text
    assert "PostgreSQL bootstrap" in text
    for app in ("freeweight", "loadcoach", "ideapress", "promptcadence"):
        assert app in text
        assert f"{app} db upgrade" in text
    assert "wr-gym db upgrade" in text
    assert "psycopg" in text
    assert "config.toml" in text
    for line in text.splitlines():
        if "PASSWORD" in line:
            assert "PG_PASSWORD" in line

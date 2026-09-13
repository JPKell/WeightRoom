"""weightroom.services.overview — figures and the primary table, API or database, never a fake 0.

No committed binary fixture: every synthetic database here is built at test time with raw
``sqlite3`` (the FreeWeight M6 lesson recorded in memory — a gitignored binary fixture is how a
CI run goes red for a reason nobody in the diff can see).
"""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import httpx
import respx

from weightroom.config import load_settings
from weightroom.services.apps import AppView
from weightroom.services.database import Database, ensure_ready
from weightroom.services.db_reader import DatabaseUrlCache
from weightroom.services.overview import overview_for

APP = "loadcoach"
BASE_URL = "http://127.0.0.1:8766"
PC_BASE_URL = "http://127.0.0.1:8768"


def _fake_cli(tmp_path: Path, *, database_url: str, name: str = "loadcoach") -> Path:
    """A one-file application stand-in that answers ``config show --json`` and nothing else.

    Every ``config show`` appends a line to ``tmp_path/show.calls``: the launch is what row WPF6
    is about, so a test counts them rather than trusting the cache's own bookkeeping.
    """
    script = tmp_path / name
    script.write_text(
        textwrap.dedent(f"""\
            #!/bin/sh
            if [ "$1 $2 $3" = "config show --json" ]; then
              echo . >> {tmp_path / "show.calls"}
              echo '{{"values": {{"storage": {{"database_url": "{database_url}"}}}}}}'
              exit 0
            fi
            exit 1
            """)
    )
    script.chmod(0o755)
    return script


def _show_calls(tmp_path: Path) -> int:
    calls = tmp_path / "show.calls"
    return len(calls.read_text().splitlines()) if calls.exists() else 0


def _synthetic_db(tmp_path: Path, *, revision: str, model_rows: int = 2) -> str:
    path = tmp_path / "loadcoach.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
    connection.execute("CREATE TABLE models (id INTEGER PRIMARY KEY, canonical_id TEXT)")
    connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY)")
    connection.execute("CREATE TABLE routing_decisions (id INTEGER PRIMARY KEY)")
    for i in range(model_rows):
        connection.execute("INSERT INTO models (canonical_id) VALUES (?)", (f"model-{i}",))
    connection.commit()
    connection.close()
    return f"sqlite:///{path}"


def _console_database(tmp_path: Path) -> Database:
    """A fresh WeightRoomGym database, migrated to head — migration 0001 already seeds
    ``loadcoach``'s known revision as ``0015`` (row W1), which every test below reuses rather
    than re-inserting it (a second row for the same ``(app, revision)`` violates the primary key).
    """
    database = Database.from_url(f"sqlite:///{tmp_path / 'weightroom.sqlite3'}")
    ensure_ready(database, auto_migrate=True)
    return database


def _view(
    *,
    installed: bool,
    running: bool,
    reachable: bool,
    executable: str | None,
    app: str = APP,
    base_url: str = BASE_URL,
) -> AppView:
    return AppView(
        name=app,
        installed=installed,
        executable=executable,
        unit=f"{app}.service",
        unit_state="active" if running else "inactive",
        uptime_seconds=120.0 if running else None,
        restarts=0,
        base_url=base_url,
        version="1.3.1" if reachable else None,
        api_version="v1" if reachable else None,
        verdict="ok" if reachable else "unreadable",
    )


def _settings(tmp_path: Path, *, executable: Path | None, app: str = APP, base_url: str = BASE_URL):  # type: ignore[no-untyped-def]
    text = ""
    if executable is not None:
        text = f'[apps.{app}]\nexecutable = "{executable}"\nbase_url = "{base_url}"\n'
    config = tmp_path / "console.toml"
    config.write_text(text)
    return load_settings(config_path=config).settings


@respx.mock
def test_running_and_reachable_reads_figures_from_the_api_and_the_table_from_the_database(
    tmp_path: Path,
) -> None:
    respx.get(f"{BASE_URL}/api/v1/system/status").mock(
        return_value=httpx.Response(
            200, json={"active": 3, "oldest_queued_age_seconds": 12.5, "starving": False}
        )
    )
    database_url = _synthetic_db(tmp_path, revision="0015")
    executable = _fake_cli(tmp_path, database_url=database_url)
    settings = _settings(tmp_path, executable=executable)
    console_db = _console_database(tmp_path)
    view = _view(installed=True, running=True, reachable=True, executable=str(executable))

    overview = overview_for(
        APP,
        view,
        settings=settings,
        database=console_db,
        client=httpx.Client(),
        urls=DatabaseUrlCache(),
        now=0.0,
    )

    assert overview.source == "api"
    # The primary table is database-sourced even while running (§2.1 of the module's own
    # docstring), so the footer names both halves rather than implying the table came from the
    # API too — and preserves "API" rather than lower-casing it.
    assert overview.source_detail == "Figures from the API; table: the database at revision 0015"
    figures = {f.label: f.value for f in overview.figures}
    assert figures["Active"] == "3"
    assert figures["Starving"] == "False"
    assert overview.table.caption == "models"
    assert len(overview.table.rows) == 2
    # Row WX11's PromptCadence-only section stays empty for the other three applications.
    assert overview.promptcadence_figures == ()


@respx.mock
def test_promptcadence_overview_gains_its_own_section(tmp_path: Path) -> None:
    """Row WX11: Active, Pending approvals and Spending today, read off the same status body —
    ``ledger.day`` is what ``ledger_view(trajectory=None).as_json()`` already puts there."""
    status_body = {
        "active_trajectories": [
            {"trajectory_id": "a", "state": "executing"},
            {"trajectory_id": "b", "state": "planning"},
        ],
        "pending_approvals": [{"request_id": "r1"}],
        "ledger": {"day": {"money_remaining_display": "at most 20 USD", "exceeded": False}},
    }
    respx.get(f"{PC_BASE_URL}/api/v1/system/status").mock(
        return_value=httpx.Response(200, json=status_body)
    )
    database_url = _synthetic_db(tmp_path, revision="0015")
    executable = _fake_cli(tmp_path, database_url=database_url, name="promptcadence")
    settings = _settings(tmp_path, executable=executable, app="promptcadence", base_url=PC_BASE_URL)
    console_db = _console_database(tmp_path)
    view = _view(
        installed=True,
        running=True,
        reachable=True,
        executable=str(executable),
        app="promptcadence",
        base_url=PC_BASE_URL,
    )

    overview = overview_for(
        "promptcadence",
        view,
        settings=settings,
        database=console_db,
        client=httpx.Client(),
        urls=DatabaseUrlCache(),
        now=0.0,
    )

    figures = {f.label: (f.value, f.note) for f in overview.promptcadence_figures}
    assert figures["Active"] == ("2", None)
    assert figures["Pending approvals"] == ("1", None)
    assert figures["Spending today"] == ("at most 20 USD", None)


def test_stopped_reads_both_figures_and_the_table_from_the_database_at_a_known_revision(
    tmp_path: Path,
) -> None:
    database_url = _synthetic_db(tmp_path, revision="0015", model_rows=1)
    executable = _fake_cli(tmp_path, database_url=database_url)
    settings = _settings(tmp_path, executable=executable)
    console_db = _console_database(tmp_path)
    view = _view(installed=True, running=False, reachable=False, executable=str(executable))

    overview = overview_for(
        APP,
        view,
        settings=settings,
        database=console_db,
        client=httpx.Client(),
        urls=DatabaseUrlCache(),
        now=0.0,
    )

    assert overview.source == "database"
    assert "revision 0015" in overview.source_detail
    figures = {f.label: f.value for f in overview.figures}
    assert figures["Models"] == "1"
    assert figures["Jobs"] == "0"
    assert overview.table.rows


def test_an_unknown_revision_degrades_the_table_by_name_never_zero(tmp_path: Path) -> None:
    database_url = _synthetic_db(tmp_path, revision="9999")
    executable = _fake_cli(tmp_path, database_url=database_url)
    settings = _settings(tmp_path, executable=executable)
    console_db = _console_database(tmp_path)  # 9999 is not in the known set
    view = _view(installed=True, running=False, reachable=False, executable=str(executable))

    overview = overview_for(
        APP,
        view,
        settings=settings,
        database=console_db,
        client=httpx.Client(),
        urls=DatabaseUrlCache(),
        now=0.0,
    )

    assert overview.source == "none"
    assert "9999" in overview.source_detail
    assert "9999" in (overview.table.empty_message or "")
    assert all(figure.value == "—" for figure in overview.figures)


def test_neither_api_nor_database_renders_every_figure_as_a_dash(tmp_path: Path) -> None:
    settings = _settings(tmp_path, executable=None)  # not installed
    console_db = _console_database(tmp_path)
    view = _view(installed=False, running=False, reachable=False, executable=None)

    overview = overview_for(
        APP,
        view,
        settings=settings,
        database=console_db,
        client=httpx.Client(),
        urls=DatabaseUrlCache(),
        now=0.0,
    )

    assert overview.source == "none"
    assert all(figure.value == "—" for figure in overview.figures)
    assert overview.table.rows == ()
    assert overview.table.empty_message is not None


@respx.mock
def test_a_status_call_that_fails_while_running_still_renders_dashes_not_a_crash(
    tmp_path: Path,
) -> None:
    respx.get(f"{BASE_URL}/api/v1/system/status").mock(side_effect=httpx.ConnectError("refused"))
    database_url = _synthetic_db(tmp_path, revision="0015")
    executable = _fake_cli(tmp_path, database_url=database_url)
    settings = _settings(tmp_path, executable=executable)
    console_db = _console_database(tmp_path)
    view = _view(installed=True, running=True, reachable=True, executable=str(executable))

    overview = overview_for(
        APP,
        view,
        settings=settings,
        database=console_db,
        client=httpx.Client(),
        urls=DatabaseUrlCache(),
        now=0.0,
    )

    assert all(figure.value == "—" for figure in overview.figures)


@respx.mock
def test_oldest_queued_renders_as_a_duration_row_wy3(tmp_path: Path) -> None:
    """Row WY3's one intentional change to this page's own rendering: LoadCoach's Oldest queued
    used to show ``oldest_queued_age_seconds`` verbatim (``"125.0"``); ``_STATUS_FIGURES`` now
    tags it ``duration`` so both this page and the console's own ``/`` cards read it in the same
    units the design brief asks the cards for. Every other figure and the table are untouched —
    the tests above, run unmodified against the refactored :func:`overview_for`, are that proof."""
    respx.get(f"{BASE_URL}/api/v1/system/status").mock(
        return_value=httpx.Response(
            200, json={"active": 1, "oldest_queued_age_seconds": 125.0, "starving": False}
        )
    )
    database_url = _synthetic_db(tmp_path, revision="0015")
    executable = _fake_cli(tmp_path, database_url=database_url)
    settings = _settings(tmp_path, executable=executable)
    console_db = _console_database(tmp_path)
    view = _view(installed=True, running=True, reachable=True, executable=str(executable))

    overview = overview_for(
        APP,
        view,
        settings=settings,
        database=console_db,
        client=httpx.Client(),
        urls=DatabaseUrlCache(),
        now=0.0,
    )

    figures = {f.label: f.value for f in overview.figures}
    assert figures["Oldest queued"] == "2m 05s"


def test_the_database_url_is_launched_once_per_ttl_not_once_per_render(tmp_path: Path) -> None:
    """Row WPF6: ``config show --json`` is a process launch, so the Overview shares the cache.

    Every other database-reading page already goes through :class:`DatabaseUrlCache`; the
    Overview called :func:`effective_database_url` directly, which is why it painted at 544 ms
    against spec §15's 300 ms budget while every other page of the tab paid 224 ms or less.
    """
    database_url = _synthetic_db(tmp_path, revision="0015")
    executable = _fake_cli(tmp_path, database_url=database_url)
    settings = _settings(tmp_path, executable=executable)
    console_db = _console_database(tmp_path)
    view = _view(installed=True, running=False, reachable=False, executable=str(executable))
    urls = DatabaseUrlCache()

    for now in (0.0, 10.0, 59.0):
        overview = overview_for(
            APP,
            view,
            settings=settings,
            database=console_db,
            client=httpx.Client(),
            urls=urls,
            now=now,
        )
        assert overview.table.rows, "the page still renders from the cached URL"
    assert _show_calls(tmp_path) == 1

    overview_for(
        APP,
        view,
        settings=settings,
        database=console_db,
        client=httpx.Client(),
        urls=urls,
        now=61.0,  # past URL_TTL_SECONDS: a configuration file may have changed
    )
    assert _show_calls(tmp_path) == 2

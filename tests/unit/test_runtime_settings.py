"""weightroom.services.settings: the runtime registry, precedence with the environment, the
overlay ``config show`` prints, and the refusals by name."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from baseaicore import ValidationError

from weightroom.config import load_settings
from weightroom.services.database import Database, ensure_ready
from weightroom.services.settings import (
    RUNTIME_SETTINGS,
    SettingConfigOnly,
    SettingUnknown,
    database_overlay,
    read_runtime_settings,
    runtime_settings_document,
    write_runtime_settings,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def ready(tmp_path: Path):  # type: ignore[no-untyped-def]  # (settings, database, config file)
    file = tmp_path / "c.toml"
    file.write_text(f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/s.sqlite3"\n')
    settings = load_settings(config_path=file).settings
    database = Database.from_url(settings.storage.database_url or "")
    ensure_ready(database, auto_migrate=True)
    return settings, database, file


def test_the_registry_is_spec_12s_keys() -> None:
    """Spec §12's six, plus ``ui.page_rows`` (row WX5)."""
    assert set(RUNTIME_SETTINGS) == {
        "telemetry.interval_ms",
        "telemetry.history_hours",
        "alerts.interval_seconds",
        "alerts.gpu_temperature_c",
        "jobs.poll_interval_ms",
        "chat.default_task_profile",
        "ui.page_rows",
    }


def test_write_then_read_and_the_document(ready) -> None:  # type: ignore[no-untyped-def]
    settings, database, _file = ready
    effective = read_runtime_settings(database, settings=settings)
    assert effective["telemetry.interval_ms"] == 1000
    written = write_runtime_settings(
        database,
        {"telemetry.interval_ms": 500, "chat.default_task_profile": "code.review"},
        settings=settings,
        now=NOW,
    )
    assert written["telemetry.interval_ms"] == 500
    assert written["chat.default_task_profile"] == "code.review"
    document = runtime_settings_document(database, settings=settings)
    assert document["definitions"]["telemetry.interval_ms"]["source"] == "database"
    assert document["definitions"]["alerts.interval_seconds"]["source"] == "configuration"
    assert "server.host" in document["security_keys"]
    assert "storage.database_url" in document["config_only"]
    overlay = database_overlay(settings)
    assert overlay["telemetry.interval_ms"] == (500, "database")


def test_the_environment_shadows_a_stored_row_and_says_so(  # type: ignore[no-untyped-def]
    ready,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, database, file = ready
    write_runtime_settings(database, {"telemetry.interval_ms": 500}, settings=settings, now=NOW)
    monkeypatch.setenv("WEIGHTROOM_TELEMETRY__INTERVAL_MS", "250")
    settings = load_settings(config_path=file).settings
    assert read_runtime_settings(database, settings=settings)["telemetry.interval_ms"] == 250
    document = runtime_settings_document(database, settings=settings)
    definition = document["definitions"]["telemetry.interval_ms"]
    assert definition["shadowed_by"] == "env WEIGHTROOM_TELEMETRY__INTERVAL_MS"
    assert definition["stored"] == 500 and definition["source"] == "configuration"
    overlay = database_overlay(settings)
    assert overlay["telemetry.interval_ms"][1].startswith("env WEIGHTROOM_TELEMETRY__INTERVAL_MS")


def test_refusals_by_name(ready) -> None:  # type: ignore[no-untyped-def]
    settings, database, _file = ready
    with pytest.raises(SettingConfigOnly) as security:
        write_runtime_settings(database, {"server.host": "0.0.0.0"}, settings=settings, now=NOW)  # noqa: S104
    assert security.value.details["security"] is True
    with pytest.raises(SettingConfigOnly) as plain:
        write_runtime_settings(database, {"docs.root": "/x"}, settings=settings, now=NOW)
    assert plain.value.details["security"] is False
    with pytest.raises(SettingUnknown):
        write_runtime_settings(database, {"nope.nope": 1}, settings=settings, now=NOW)
    for bad in (
        {"telemetry.interval_ms": 1},
        {"telemetry.interval_ms": "x"},
        {"telemetry.interval_ms": 1.5},
        {"chat.default_task_profile": ""},
    ):
        with pytest.raises(ValidationError):
            write_runtime_settings(database, bad, settings=settings, now=NOW)


def test_a_row_this_build_cannot_read_falls_back_to_configuration(ready) -> None:  # type: ignore[no-untyped-def]
    from weightsdb import upsert

    from weightroom.infrastructure.db.models import Setting

    settings, database, _file = ready
    with database.write() as session:
        upsert(
            session,
            Setting,
            values={"key": "telemetry.interval_ms", "value_json": "junk", "updated_at": NOW},
            index_elements=["key"],
        )
    assert read_runtime_settings(database, settings=settings)["telemetry.interval_ms"] == 1000


def test_overlay_is_empty_without_a_database_file(tmp_path: Path) -> None:
    file = tmp_path / "c.toml"
    file.write_text(f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/absent.sqlite3"\n')
    assert database_overlay(load_settings(config_path=file).settings) == {}
    assert not (tmp_path / "absent.sqlite3").exists()

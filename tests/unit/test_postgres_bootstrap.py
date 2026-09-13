"""The PostgreSQL bootstrap script (row WX15): a pure render, no I/O, never a password."""

from __future__ import annotations

from pathlib import Path

from weightroom.domain.units import UNIT_APPLICATIONS
from weightroom.services.database import POSTGRES_DRIVER, postgres_bootstrap_script


def _paths() -> dict[str, Path]:
    return {app: Path(f"/home/op/.config/{app}/config.toml") for app in UNIT_APPLICATIONS}


def test_names_every_application_and_its_config_path() -> None:
    script = postgres_bootstrap_script(_paths())
    for app in UNIT_APPLICATIONS:
        assert app in script
        assert f"/home/op/.config/{app}/config.toml" in script


def test_carries_the_real_driver_and_never_a_literal_password() -> None:
    script = postgres_bootstrap_script(_paths())
    assert POSTGRES_DRIVER == "psycopg"
    assert f"postgresql+{POSTGRES_DRIVER}://" in script
    assert "$PG_PASSWORD" in script
    for line in script.splitlines():
        if "PASSWORD" in line:
            assert "PG_PASSWORD" in line


def test_upgrade_and_restart_lines_cover_the_five() -> None:
    script = postgres_bootstrap_script(_paths())
    for app in ("freeweight", "loadcoach", "ideapress", "promptcadence"):
        assert f"{app} db upgrade" in script
        assert f"systemctl --user restart {app}.service" in script
    assert "wr-gym db upgrade" in script
    assert "systemctl --user restart weightroom.service" in script


def test_the_docker_line_never_runs_and_skips_when_a_server_exists() -> None:
    script = postgres_bootstrap_script(_paths())
    assert script.splitlines()[0] == "#!/bin/sh"
    assert "docker run -d --name suite-postgres" in script
    assert "postgres:16" in script
    assert "already running" in script

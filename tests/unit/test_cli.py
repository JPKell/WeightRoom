"""The CLI end to end through Typer's runner: every verb Phase 1 ships, off the real host."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from weightroom.cli.main import app
from weightroom.services.tls import HostIdentity

runner = CliRunner()
IDENTITY = HostIdentity("jordan-main", ("10.77.10.84",))


@pytest.fixture(autouse=True)
def _fixed_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``ip`` subprocess and no real hostname in the CLI tests."""
    import weightroom.services.tls as tls_module

    monkeypatch.setattr(tls_module, "host_identity", lambda **_: IDENTITY)


def _run(*args: str, input: str | None = None) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), input=input, catch_exceptions=False)
    return result.exit_code, result.stdout, result.stderr


def test_version_and_help() -> None:
    code, out, _ = _run("version", "--json")
    assert code == 0 and json.loads(out)["application"] == "weightroom"
    code, out, _ = _run("--version")
    assert code == 0 and out.startswith("wr-gym ")
    assert _run("--help")[0] == 0


def test_config_verbs(tmp_path: Path) -> None:
    file = tmp_path / "config.toml"
    code, out, _ = _run("config", "init", "--config", str(file))
    assert code == 0 and file.is_file()
    assert _run("config", "init", "--config", str(file))[0] == 3
    assert _run("config", "init", "--config", str(file), "--force")[0] == 0
    code, out, _ = _run("config", "show", "--config", str(file))
    assert code == 0 and "server.port" in out and "(file)" in out
    code, out, _ = _run("config", "show", "--config", str(file), "--json")
    assert json.loads(out)["values"]["server.port"] == 8769
    assert _run("config", "validate", "--config", str(file)) == (0, "Configuration is valid.\n", "")
    assert _run("config", "validate", "--file", str(tmp_path / "absent.toml"))[0] == 3
    bad = tmp_path / "bad.toml"
    bad.write_text('[server]\nhost = "10.0.0.5"\n')
    code, _, err = _run("config", "validate", "--file", str(bad))
    assert code == 3 and "INSECURE_BINDING" in err
    code, out, _ = _run("config", "path", "--config", str(file))
    assert out.strip() == str(file)
    code, out, _ = _run("config", "schema", "--config", str(file), "--json")
    assert code == 0 and json.loads(out)["application"] == "weightroom"
    code, out, _ = _run("config", "schema", "--config", str(file))
    assert "runtime_changeable (7)" in out  # row WX5 added ui.page_rows
    code, out, _ = _run("config", "reference")
    assert code == 0 and "## `[apps.loadcoach]`" in out
    target = tmp_path / "ref.md"
    assert _run("config", "reference", "--output", str(target))[0] == 0
    assert _run("config", "reference", "--check", "--output", str(target))[0] == 0
    target.write_text("stale")
    assert _run("config", "reference", "--check", "--output", str(target))[0] == 1


def test_db_verbs(tmp_path: Path) -> None:
    file = tmp_path / "config.toml"
    file.write_text(f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n')
    code, out, _ = _run("db", "upgrade", "--config", str(file))
    assert code == 0 and "migrated" in out
    code, out, _ = _run("db", "upgrade", "--config", str(file), "--json")
    assert json.loads(out)["from_revision"] == json.loads(out)["to_revision"]
    code, out, _ = _run("db", "status", "--config", str(file))
    assert code == 0 and "known_revisions" in out and "integrity:  ok" in out
    code, out, _ = _run("db", "status", "--config", str(file), "--json")
    assert json.loads(out)["is_at_head"] is True
    code, out, _ = _run("db", "backup", "--config", str(file))
    assert code == 0 and Path(out.strip()).is_file()
    backup = out.strip()
    assert _run("db", "restore", backup, "--config", str(file))[0] == 2
    assert _run("db", "restore", backup, "--config", str(file), "--confirm")[0] == 0


def test_tls_operator_audit_and_health(tmp_path: Path) -> None:
    file = tmp_path / "config.toml"
    file.write_text(
        f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n'
        f'[tls]\ndirectory = "{tmp_path}/tls"\n'
    )
    assert _run("tls", "show", "--config", str(file))[0] == 3
    assert _run("trust", "--config", str(file))[0] == 3
    code, out, _ = _run("tls", "init", "--config", str(file))
    assert code == 0 and "root sha256" in out
    assert _run("tls", "init", "--config", str(file))[0] == 2
    code, out, _ = _run("tls", "show", "--config", str(file), "--json")
    first = json.loads(out)
    assert first["leaf"]["days_left"] >= 397
    code, out, _ = _run("tls", "renew", "--config", str(file), "--json")
    assert json.loads(out)["ca"]["fingerprint_sha256"] == first["ca"]["fingerprint_sha256"]
    code, out, _ = _run("trust", "--config", str(file))
    assert code == 0 and "http://jordan-main.local:8770/root.crt" in out and "Android" in out
    code, out, _ = _run("trust", "--config", str(file), "--json")
    assert json.loads(out)["fingerprint_sha256"] == first["ca"]["fingerprint_sha256"]

    code, out, _ = _run(
        "operator",
        "create",
        "jordan",
        "--config",
        str(file),
        "--password-stdin",
        input="correct horse battery\n",
    )
    assert code == 0 and "created" in out
    code, _, err = _run(
        "operator",
        "create",
        "again",
        "--config",
        str(file),
        "--password-stdin",
        input="correct horse battery\n",
    )
    assert code == 2 and "already exists" in err
    code, _, err = _run(
        "operator",
        "password",
        "nobody",
        "--config",
        str(file),
        "--password-stdin",
        input="another password\n",
    )
    assert code == 2
    code, out, _ = _run(
        "operator",
        "password",
        "jordan",
        "--config",
        str(file),
        "--password-stdin",
        input="another password\n",
    )
    assert code == 0 and "0 session(s) revoked" in out
    assert (
        _run(
            "operator",
            "password",
            "jordan",
            "--config",
            str(file),
            "--password-stdin",
            input="short\n",
        )[0]
        == 2
    )

    assert _run("tls", "rotate", "--config", str(file))[0] == 2
    code, out, _ = _run("tls", "rotate", "--config", str(file), "--yes", "--json")
    assert (
        code == 0
        and json.loads(out.splitlines()[0])["ca"]["fingerprint_sha256"]
        != first["ca"]["fingerprint_sha256"]
    )

    code, out, _ = _run("audit", "list", "--config", str(file))
    assert code == 0
    actions = [line.split()[3] for line in out.splitlines()]
    assert actions == [
        "tls.rotate",
        "operator.password",
        "operator.password",
        "operator.password",
        "operator.create",
        "operator.create",
    ]
    code, out, _ = _run("audit", "list", "--config", str(file), "--json", "--action", "tls.rotate")
    rows = json.loads(out)
    assert len(rows) == 1 and rows[0]["security"] is True
    code, out, _ = _run("audit", "show", rows[0]["id"], "--config", str(file))
    assert code == 0 and json.loads(out)["action"] == "tls.rotate"
    assert _run("audit", "show", "nope", "--config", str(file))[0] == 2

    code, out, _ = _run("health", "--config", str(file))
    assert code == 0 and "status: ok" in out and "app:loadcoach: unknown" in out
    code, out, _ = _run("health", "--config", str(file), "--json")
    assert json.loads(out)["status"] == "ok"


def test_setup_unattended(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Spec §20 criterion 10: the suite passes with no systemd. The wizard's units and linger
    # steps run against a fake host, so this test drives the CLI wiring and nothing else.
    from weightroom.services import setup as setup_service
    from weightroom.services.processes import FakeSystemdController

    monkeypatch.setattr(setup_service, "SubprocessSystemdController", FakeSystemdController)
    file = tmp_path / "config.toml"
    file.write_text(
        f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n'
        f'[tls]\ndirectory = "{tmp_path}/tls"\n'
    )
    code, out, err = _run(
        "setup",
        "--config",
        str(file),
        "--username",
        "jordan",
        "--password-stdin",
        "--bind",
        "lan",
        "--lan-address",
        "10.77.10.84",
        "--no-start-console",
        input="correct horse battery\n",
    )
    assert code == 0, err
    assert "created operator 'jordan'" in out and "10.77.10.84 (one LAN interface)" in out
    assert "not installed; no token" in out
    assert "linger     " in out and "unit       loadcoach: not_installed" in out
    assert "--no-start-console" in out
    code, out, _ = _run("config", "show", "--config", str(file), "--json")
    values = json.loads(out)["values"]
    assert values["server.host"] == "10.77.10.84"
    assert "jordan-main.local" in values["server.allowed_hosts"]
    code, out, _ = _run("setup", "--config", str(file), "--bind", "nonsense")
    assert code == 2
    code, out, _ = _run("audit", "list", "--config", str(file), "--action", "setup.run", "--json")
    assert json.loads(out)[0]["params"]["bind"].startswith("10.77.10.84")


def test_serve_refuses_an_insecure_bind_before_any_socket(tmp_path: Path) -> None:
    file = tmp_path / "config.toml"
    file.write_text(
        f'[server]\nhost = "10.77.10.84"\nallowed_hosts = ["x"]\n'
        f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n'
        f'[tls]\ndirectory = "{tmp_path}/tls"\n'
    )
    code, _, err = _run("serve", "--config", str(file))
    assert code == 3 and "INSECURE_BINDING" in err


def _fake_host(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> object:
    """Point every ``SubprocessSystemdController()`` in the CLI at one fake host."""
    from weightroom.services import processes

    host = processes.FakeSystemdController(**kwargs)  # type: ignore[arg-type]
    monkeypatch.setattr(processes, "SubprocessSystemdController", lambda **_kw: host)
    return host


def test_units_sync_writes_reports_and_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "config.toml"
    application = tmp_path / "loadcoach"
    application.write_text("#!/bin/sh\nexit 0\n")
    application.chmod(0o755)
    file.write_text(
        f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n'
        f'[apps.loadcoach]\nexecutable = "{application}"\n'
    )
    _fake_host(monkeypatch)
    # `units sync` writes weightroom.service too when `wr-gym` is on PATH (an activated venv), so
    # the count below depended on the shell that ran the test (WI1 §5 item 4d). Pin the PATH.
    monkeypatch.setenv("PATH", str(tmp_path))
    code, out, err = _run("units", "sync", "--config", str(file), "--diff")
    assert code == 0, err
    assert "loadcoach      written" in out
    assert "freeweight     not installed; no unit" in out
    assert "+MemoryHigh=22G" in out
    assert "reload    systemd reloaded" in out

    code, out, _ = _run("units", "sync", "--config", str(file))
    assert code == 0
    assert "loadcoach      unchanged" in out and "reload    not needed" in out

    code, out, _ = _run("audit", "list", "--config", str(file), "--action", "unit.sync", "--json")
    rows = json.loads(out)
    assert len(rows) == 2
    assert rows[-1]["params"]["written"] == ["loadcoach.service"]


def test_units_status_and_control_write_one_row_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "config.toml"
    file.write_text(f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n')
    _fake_host(monkeypatch, states={"loadcoach.service": "inactive"})
    code, out, err = _run("units", "start", "loadcoach", "--config", str(file))
    assert code == 0, err
    assert "loadcoach.service        started" in out
    code, out, _ = _run("units", "status", "--config", str(file))
    assert "loadcoach.service        active" in out
    assert "freeweight.service       absent" in out and "up —" in out
    code, out, _ = _run("audit", "list", "--config", str(file), "--action", "unit.start", "--json")
    rows = json.loads(out)
    assert len(rows) == 1 and rows[0]["target"] == "loadcoach.service"


def test_units_control_surfaces_systemds_refusal_and_exits_four(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "config.toml"
    file.write_text(f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n')
    _fake_host(
        monkeypatch,
        refuse={
            ("loadcoach.service", "start"): "Failed to start loadcoach.service: Unit not found."
        },
    )
    code, _out, err = _run("units", "start", "loadcoach", "--config", str(file))
    assert code == 4
    assert "Unit not found" in err
    code, out, _ = _run("audit", "list", "--config", str(file), "--action", "unit.start", "--json")
    assert json.loads(out)[0]["outcome"] == "failed"


def test_units_rejects_an_application_that_has_no_unit(tmp_path: Path) -> None:
    file = tmp_path / "config.toml"
    file.write_text(f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n')
    code, _out, err = _run("units", "start", "ollama", "--config", str(file))
    assert code == 2
    assert "is not an application" in err

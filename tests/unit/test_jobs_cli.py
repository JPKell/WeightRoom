"""``wr-gym jobs`` and ``wr-gym db restore-self`` through Typer's runner, off the real host."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from weightroom.cli.main import app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def _run(*args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), catch_exceptions=False)
    return result.exit_code, result.stdout, result.stderr


def _config(tmp_path: Path) -> str:
    file = tmp_path / "config.toml"
    file.write_text(f'[storage]\ndatabase_url = "sqlite:///{tmp_path}/db.sqlite3"\n')
    return str(file)


def test_jobs_are_queued_listed_shown_and_cancelled_each_change_audited(tmp_path: Path) -> None:
    config = _config(tmp_path)
    code, out, _ = _run("jobs", "run", "docs_index", "--config", config, "--json")
    assert code == 0
    job = json.loads(out)
    assert (job["kind"], job["state"]) == ("docs_index", "queued")
    code, out, _ = _run("jobs", "list", "--config", config)
    assert code == 0
    assert job["id"] in out
    code, out, _ = _run("jobs", "show", job["id"], "--config", config, "--json")
    assert json.loads(out)["kind"] == "docs_index"
    assert _run("jobs", "show", "01NOSUCHJOB000000000000000", "--config", config)[0] == 2
    code, out, _ = _run("jobs", "cancel", job["id"], "--config", config)
    assert code == 0
    assert "cancelled" in out
    assert _run("jobs", "cancel", job["id"], "--config", config)[0] == 2
    assert _run("jobs", "run", "bogus", "--config", config)[0] == 2
    assert _run("jobs", "run", "backup", "--param", "no-equals", "--config", config)[0] == 2
    code, out, _ = _run("audit", "list", "--config", config, "--json")
    actions = [(row["action"], row["actor"], row["outcome"]) for row in json.loads(out)]
    assert ("job.enqueue", "cli", "ok") in actions
    assert ("job.cancel", "cli", "ok") in actions
    assert ("job.cancel", "cli", "refused") in actions
    assert ("job.enqueue", "cli", "refused") in actions


def test_a_schedule_is_listed_and_changed_with_parameters_merged(tmp_path: Path) -> None:
    config = _config(tmp_path)
    code, out, _ = _run("jobs", "schedule", "--config", config, "--json")
    assert code == 0
    suite = next(one for one in json.loads(out) if one["kind"] == "freeweight_suite_run")
    assert _run("jobs", "schedule", suite["id"], "--enable", "--config", config)[0] == 2
    code, out, _ = _run(
        "jobs",
        "schedule",
        suite["id"],
        "--param",
        "model=ollama/qwen3:8b",
        "--cron",
        "0 1 * * *",
        "--enable",
        "--config",
        config,
        "--json",
    )
    assert code == 0
    changed = json.loads(out)
    assert changed["enabled"] is True
    assert changed["params"] == {
        "model": "ollama/qwen3:8b",
        "suite": "native.performance",
        "allow_prompt_override": False,
        "label": None,
        "adapter": None,
        "cooldown_seconds": None,
    }
    assert changed["cron"] == "0 1 * * *"
    code, out, _ = _run("jobs", "schedule", "--config", config)
    assert "freeweight_suite_run" in out
    assert "enabled" in out


def test_waiting_on_a_job_no_worker_takes_exits_four(tmp_path: Path) -> None:
    config = _config(tmp_path)
    code, _, err = _run(
        "jobs", "run", "docs_index", "--wait", "--timeout", "0.5", "--config", config
    )
    assert code == 4
    assert "still queued" in err


def test_waiting_follows_the_job_into_a_database_file_swapped_underneath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0136's helper replaces the database file; --wait must see the completion the
    restored file carries, not the old inode's row (row W10 §4.4: 'still running' at 180 s)."""
    import sqlite3
    import time

    config = _config(tmp_path)
    live = tmp_path / "db.sqlite3"

    def swap_once(_seconds: float) -> None:
        copy = tmp_path / "restored.sqlite3"
        source, target = sqlite3.connect(live), sqlite3.connect(copy)
        source.backup(target)  # the WAL included, as weightsdb's own backup does
        target.execute("UPDATE jobs SET state = 'completed'")
        target.commit()
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        source.close()  # sqlite3's `with` ends a transaction, not the connection
        target.close()
        for sidecar in ("-wal", "-shm"):  # what weightsdb.restore removes before the swap
            (tmp_path / f"db.sqlite3{sidecar}").unlink(missing_ok=True)
        copy.replace(live)
        monkeypatch.setattr(time, "sleep", lambda _s: None)

    monkeypatch.setattr(time, "sleep", swap_once)
    code, out, _err = _run(
        "jobs", "run", "docs_index", "--wait", "--timeout", "10", "--config", config
    )
    assert code == 0, out
    assert "completed" in out


def test_restore_self_refuses_a_receipt_that_is_not_one_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEIGHTROOM_DATA_DIR", str(tmp_path / "data"))
    stray = tmp_path / "receipt.json"
    stray.write_text("{}", encoding="utf-8")
    code, _, err = _run(
        "db", "restore-self", "--receipt", str(stray), "--config", _config(tmp_path)
    )
    assert code == 2
    assert "is not a receipt" in err

"""WeightRoomGym's own migration history: up and down on both dialects, parity, the seed."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from weightsdb import MigrationRunner, ParityResult
from weightsdb.testing import temporary_postgres, temporary_sqlite

from weightroom.infrastructure.db.models import Base
from weightroom.services.database import MIGRATIONS_LOCATION, Database, ensure_ready, get_status
from weightroom.services.docs_index import FTS5_SHADOW_TABLES

EXPECTED_SEED = {
    ("freeweight", "0009"),
    ("freeweight", "0010"),  # migration 0005, row WA1
    ("freeweight", "0011"),  # migration 0009, row WY10
    ("loadcoach", "0015"),
    ("ideapress", "0010"),
    ("ideapress", "0011"),  # migration 0008, row W9
    ("promptcadence", "0011"),
}


def _head() -> str:
    with temporary_sqlite() as engine:
        heads = MigrationRunner(engine, script_location=MIGRATIONS_LOCATION).heads()
    assert len(heads) == 1, f"the history must stay linear; found {heads}"
    return heads[0]


def _assert_parity(parity: ParityResult) -> None:
    """``docs_index`` (migration 0003) is real DDL, not an ORM model — FTS5's own bookkeeping
    tables (:data:`FTS5_SHADOW_TABLES`) on SQLite and the GIN index over its ``tsvector`` on
    PostgreSQL are the expected differences from ``Base.metadata``. (The PostgreSQL one went
    unnoticed from W5 until W7 ran this leg against a real server.)"""
    if parity.matches:
        return
    remaining = [
        line
        for line in parity.diff.splitlines()
        if not any(f"'{table}'" in line for table in FTS5_SHADOW_TABLES)
        and "'ix_docs_index_search_vector'" not in line
    ]
    assert not remaining, "\n".join(remaining)


def _seed(engine: object) -> set[tuple[str, str]]:
    from sqlalchemy import Engine

    assert isinstance(engine, Engine)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT app, revision FROM known_revisions")).all()
    return {(str(app), str(rev)) for app, rev in rows}


def test_fresh_sqlite_migrates_to_head_seeds_known_revisions_and_has_parity() -> None:
    with temporary_sqlite() as engine:
        runner = MigrationRunner(engine, script_location=MIGRATIONS_LOCATION)
        assert runner.current() is None
        assert runner.upgrade(backup=False).to_revision == _head()
        assert runner.is_at_head()
        assert _seed(engine) == EXPECTED_SEED
        parity = runner.check_parity(Base.metadata)
        _assert_parity(parity)
        runner.downgrade("base")
        assert runner.current() is None
        names = {
            row[0]
            for row in engine.connect()
            .execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            .all()
        }
        # sqlite_sequence is SQLite's own bookkeeping for an AUTOINCREMENT table (message_events)
        # and cannot be dropped; every table a migration created is gone.
        assert names - {"sqlite_sequence"} <= {"alembic_version"}


@pytest.mark.integration
def test_fresh_postgres_migrates_to_head_and_back() -> None:
    with temporary_postgres() as engine:
        runner = MigrationRunner(engine, script_location=MIGRATIONS_LOCATION)
        assert runner.upgrade(backup=False).to_revision == _head()
        assert _seed(engine) == EXPECTED_SEED
        parity = runner.check_parity(Base.metadata)
        _assert_parity(parity)
        runner.downgrade("base")
        assert runner.current() is None


def test_ensure_ready_migrates_a_fresh_database_and_is_a_no_op_at_head() -> None:
    with temporary_sqlite() as engine:
        database = Database(engine)
        outcome = ensure_ready(database, auto_migrate=True)
        assert outcome is not None and outcome.to_revision == _head()
        assert ensure_ready(database, auto_migrate=True) is None
        status = get_status(database)
        assert status.is_at_head and status.integrity_ok
        assert status.table_row_counts["known_revisions"] == len(EXPECTED_SEED)


def test_ensure_ready_refuses_a_revision_this_build_does_not_know() -> None:
    from weightsdb import SchemaAhead

    with temporary_sqlite() as engine:
        runner = MigrationRunner(engine, script_location=MIGRATIONS_LOCATION)
        runner.upgrade(backup=False)
        runner.stamp(_head())
        assert ensure_ready(Database(engine), auto_migrate=False) is None
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))
        with pytest.raises(SchemaAhead, match="9999"):
            ensure_ready(Database(engine), auto_migrate=True)


def test_a_database_from_the_first_release_upgrades_to_head_with_its_rows_intact() -> None:
    """The upgrade path from ``0.x``: a database at migration ``0001`` — the schema `wr-gym 0.1.0`
    shipped — carries an operator and an audit row through every later migration to head, with the
    rows readable and ``known_revisions`` seeded (packaging standards §6.1; row W10, gate B)."""
    with temporary_sqlite() as engine:
        runner = MigrationRunner(engine, script_location=MIGRATIONS_LOCATION)
        assert runner.upgrade("0001", backup=False).to_revision == "0001"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO operators (id, username, password_hash, password_salt, "
                    "kdf_params, created_at, password_changed_at) VALUES "
                    "('01OPERATOR000000000000000', 'jordan', X'00', X'00', '{}', "
                    "'2026-09-09 12:00:00', '2026-09-09 12:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO audit_log (id, operator_id, actor, at, action, params, outcome, "
                    "security) VALUES ('01AUDIT0000000000000000000', '01OPERATOR000000000000000', "
                    "'operator', '2026-09-09 12:00:00', 'login', '{}', 'ok', 0)"
                )
            )
        assert runner.upgrade(backup=False).to_revision == _head()
        with engine.connect() as connection:
            operators = connection.execute(text("SELECT username FROM operators")).scalars().all()
            actions = connection.execute(text("SELECT action FROM audit_log")).scalars().all()
        assert operators == ["jordan"] and actions == ["login"]
        assert _seed(engine) >= EXPECTED_SEED
        _assert_parity(runner.check_parity(Base.metadata))

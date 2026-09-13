"""weightroom.services.database — engine construction, startup migration and status.

Route handlers and CLI command bodies never call :func:`weightsdb.create_engine_for` directly;
they call a function here, so ``wr-gym db status`` and ``GET /api/v1/health`` report the same
database facts by construction. The shape is LoadCoach's ``services/database.py``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from weightsdb import (
    DatabaseError,
    DatabaseUnavailable,
    MigrationOutcome,
    MigrationRequired,
    MigrationRunner,
    SchemaAhead,
    create_engine_for,
    database_size_bytes,
    integrity_check,
    session_factory,
    session_scope,
    transaction,
)
from weightsdb import backup as weightsdb_backup
from weightsdb import database_health as weightsdb_database_health
from weightsdb import restore as weightsdb_restore
from weightsdb.backup import BackupResult, RestoreResult, sqlite_path

from weightroom.config import APPLICATIONS, data_dir
from weightroom.domain.units import UNIT_APPLICATIONS, unit_name
from weightroom.infrastructure.db.models import (
    AuditLog,
    KnownRevision,
    Operator,
    Setting,
    TelemetrySample,
)
from weightroom.infrastructure.db.models import (
    Session as SessionRow,
)

__all__ = [
    "MIGRATIONS_LOCATION",
    "Database",
    "DatabaseStatus",
    "backup_database",
    "backup_directory",
    "build_engine",
    "database_health",
    "ensure_ready",
    "get_status",
    "migration_runner",
    "postgres_bootstrap_script",
    "restore_database",
    "upgrade",
]

MIGRATIONS_LOCATION = str(
    Path(__file__).resolve().parent.parent / "infrastructure" / "db" / "migrations"
)

_APPLICATION_NAME = "weightroom"

POSTGRES_DRIVER: Final = "psycopg"
"""The DBAPI ``weightsdb``'s ``postgres`` extra pins (``py/WeightsDB/pyproject.toml``:
``psycopg[binary]>=3.2,<4``) — the URL scheme it drives is ``postgresql+psycopg://``."""

_POSTGRES_IMAGE: Final = "postgres:16"
_POSTGRES_CONTAINER: Final = "suite-postgres"
_POSTGRES_VOLUME: Final = "suite-pg"


def postgres_bootstrap_script(config_paths: Mapping[str, Path]) -> str:
    """Render the PostgreSQL bootstrap script the Databases page prints — and never runs.

    Every fact in the script comes from the suite's own code, never a guess: the driver
    ``weightsdb`` pins (:data:`POSTGRES_DRIVER`), each application's real ``config.toml`` path
    (``config_paths``), the ``[storage]`` section and ``database_url`` key every one of the five
    ``config.py`` modules declares alike (with the ``<PREFIX>STORAGE__DATABASE_URL`` environment
    form each one's ``ENV_PREFIX`` produces), its ``db upgrade`` CLI verb, and its
    ``systemd --user`` unit name (:data:`~weightroom.domain.units.UNIT_APPLICATIONS`). It never
    invents or prints a password: ``${PG_PASSWORD}`` is a shell variable the operator sets first,
    the same print-never-run precedent as ``templates/ollama.html``'s memory-safety fix (this
    console is never a database administrator, ADR-0123 rule 2).

    Args:
        config_paths: Each of :data:`~weightroom.domain.units.UNIT_APPLICATIONS`'s
            ``config.toml`` path, keyed by application name.

    Returns:
        The whole script as one string, section-commented and newline-terminated, ready for a
        ``<pre>``. Names all five applications and every config path; contains no literal
        password.
    """
    lines: list[str] = [
        "#!/bin/sh",
        "# PostgreSQL bootstrap for the suite's five databases.",
        "# WeightRoomGym prints this script; it never runs it — this console is never a database",
        "# administrator (ADR-0123 rule 2). Read every line before running any of it by hand.",
        "#",
        "# Set the password once, in your own shell — never in this script:",
        "#   export PG_PASSWORD='...'",
        "",
        "# 1. A server. Skip this line if one is already running (the W7 local-PG leg used the",
        "#    same image).",
        f'docker run -d --name {_POSTGRES_CONTAINER} -e POSTGRES_PASSWORD="$PG_PASSWORD" \\',
        f"  -p 127.0.0.1:5432:5432 -v {_POSTGRES_VOLUME}:/var/lib/postgresql/data "
        f"{_POSTGRES_IMAGE}",
        "",
        "# 2. One role and one database per application, owner-scoped to it.",
        'PGPASSWORD="$PG_PASSWORD" psql -h 127.0.0.1 -U postgres <<SQL',
    ]
    for app in UNIT_APPLICATIONS:
        lines.append(f"CREATE ROLE {app} WITH LOGIN PASSWORD '$PG_PASSWORD';")
        lines.append(f"CREATE DATABASE {app} OWNER {app};")
    lines += [
        "SQL",
        "",
        "# 3. Each application's [storage] section (config.toml) or the equivalent environment",
        "#    variable — not both.",
    ]
    for app in UNIT_APPLICATIONS:
        url = f"postgresql+{POSTGRES_DRIVER}://{app}:$PG_PASSWORD@127.0.0.1:5432/{app}"
        lines.append(f"# {app}: {config_paths[app]}")
        lines.append("#   [storage]")
        lines.append(f'#   database_url = "{url}"')
        lines.append(f'#   or: {app.upper()}_STORAGE__DATABASE_URL="{url}"')
    lines += [
        "",
        "# 4. Migrate. auto_migrate defaults off the moment a URL is not sqlite:// (database",
        "#    standards §5.1), for every one of the five — so this step is not optional.",
    ]
    for app in APPLICATIONS:
        lines.append(f"{app} db upgrade")
    lines += [
        "wr-gym db upgrade",
        "",
        "# 5. Restart every application against its new database.",
    ]
    for app in UNIT_APPLICATIONS:
        lines.append(f"systemctl --user restart {unit_name(app)}")
    return "\n".join(lines) + "\n"


_ROW_COUNT_MODELS = (Operator, SessionRow, AuditLog, Setting, KnownRevision, TelemetrySample)


def build_engine(database_url: str) -> Engine:
    """Build the engine for ``database_url`` through WeightsDB's dialect-aware factory."""
    return create_engine_for(database_url, application_name=_APPLICATION_NAME)


class Database:
    """WeightRoomGym's live connection to its own database: one engine, for as long as it serves.

    Owned by the caller — the web application creates one in its lifespan and disposes it at
    shutdown; a CLI command creates one, runs, and closes it on the way out.
    """

    __slots__ = ("_engine", "_sessions")

    def __init__(self, engine: Engine) -> None:
        """Wrap an existing engine. Prefer :meth:`from_url` unless you built the engine yourself."""
        self._engine = engine
        self._sessions = session_factory(engine)

    @classmethod
    def from_url(cls, database_url: str) -> Database:
        """Build a handle for ``database_url``. Opens no connection until first use."""
        return cls(build_engine(database_url))

    @property
    def engine(self) -> Engine:
        """The underlying engine, for the file-level operations that need one directly."""
        return self._engine

    @property
    def sessions(self) -> sessionmaker[Session]:
        """The session factory bound to this handle's engine."""
        return self._sessions

    @contextmanager
    def write(self) -> Iterator[Session]:
        """One read-write unit of work, committed on success and rolled back on any exception."""
        with session_scope(self._sessions) as session:
            yield session

    @contextmanager
    def read(self) -> Iterator[Session]:
        """One read-only unit of work: a write attempted inside it is refused, not taken."""
        with session_scope(self._sessions) as session, transaction(session, immediate=False):
            yield session

    def close(self) -> None:
        """Dispose the pool. The handle must not be used afterwards."""
        self._engine.dispose()

    def __enter__(self) -> Database:
        """Support ``with Database.from_url(...) as db:`` for one-shot callers like the CLI."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Always dispose the pool, whether the body succeeded or raised."""
        self.close()


def migration_runner(engine: Engine, *, backup_retention: int = 5) -> MigrationRunner:
    """Build the :class:`~weightsdb.MigrationRunner` for WeightRoomGym's own history."""
    return MigrationRunner(
        engine, script_location=MIGRATIONS_LOCATION, backup_retention=backup_retention
    )


def backup_directory(engine: Engine) -> Path:
    """Where this database's own backups land: beside the SQLite file, or ``<data>/backups`` on
    PostgreSQL. Row W8's Backups page lists it; never the guarded-write directory
    (``services/db_guard.backups_directory``), which is a different thing at a different path."""
    if engine.dialect.name == "sqlite":
        return sqlite_path(engine).parent / "backups"
    return data_dir() / "backups"


def ensure_ready(
    database: Database, *, auto_migrate: bool, backup_retention: int = 5
) -> MigrationOutcome | None:
    """Apply the startup revision check (database standards §5.1).

    Args:
        database: The database handle.
        auto_migrate: ``settings.storage.auto_migrate``.
        backup_retention: ``settings.storage.backup_retention``.

    Returns:
        The :class:`~weightsdb.MigrationOutcome` if a migration ran, else ``None``.

    Raises:
        MigrationRequired: The database is behind head and ``auto_migrate`` is ``False``.
        SchemaAhead: The database's current revision is not one this build's migrations produce.
        DatabaseUnavailable: The database could not be reached at all.
    """
    try:
        runner = migration_runner(database.engine, backup_retention=backup_retention)
        current = runner.current()
        heads = runner.heads()
    except DatabaseError:
        raise
    except Exception as exc:  # noqa: BLE001 — translated into the suite's own error type below
        raise DatabaseUnavailable(
            f"Could not open the database to check its migration state: {exc}"
        ) from exc
    if not heads:  # pragma: no cover — the history ships with this package
        raise DatabaseError(f"No migrations are registered under {MIGRATIONS_LOCATION}.")
    head = heads[0]
    if current == head:
        return None
    if current is not None and current not in runner.known_revisions():
        raise SchemaAhead(
            f"The database is at revision {current!r}, which this build's migrations do not "
            f"produce (known head: {head!r}). It was likely written by a newer version; restore "
            f"the pre-migration backup under {backup_directory(database.engine)} and install "
            "the version that wrote it.",
            details={"current": current, "head": head},
        )
    if current is not None and not auto_migrate:
        raise MigrationRequired(
            f"The database is at revision {current!r}; head is {head!r}. Run "
            "`wr-gym db upgrade` to migrate.",
            details={"current": current, "head": head, "command": "wr-gym db upgrade"},
        )
    return runner.upgrade(backup=current is not None)


def upgrade(
    database: Database, *, revision: str = "head", backup_retention: int = 5
) -> MigrationOutcome:
    """Run ``wr-gym db upgrade``: migrate to ``revision``, taking a backup first. Idempotent."""
    runner = migration_runner(database.engine, backup_retention=backup_retention)
    return runner.upgrade(revision, backup=runner.current() is not None)


def backup_database(database: Database, *, output: Path | None, keep: int) -> BackupResult:
    """Run ``wr-gym db backup``: a consistent backup, rotating automatic ones against ``keep``."""
    engine = database.engine
    if output is not None:
        return weightsdb_backup(engine, output)
    source = sqlite_path(engine)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = source.parent / "backups" / f"manual-{stamp}{source.suffix}"
    return weightsdb_backup(engine, destination, keep=keep, prefix="manual-")


def restore_database(database: Database, *, source: Path, confirm: bool) -> RestoreResult:
    """Run ``wr-gym db restore``: restore from ``source``, overwriting the current database."""
    return weightsdb_restore(database.engine, source, confirm=confirm)


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    """The ``wr-gym db status`` snapshot."""

    dialect: str
    current_revision: str | None
    head_revision: str
    is_at_head: bool
    table_row_counts: dict[str, int]
    size_bytes: int
    integrity_ok: bool
    integrity_detail: str


def get_status(database: Database) -> DatabaseStatus:
    """Build the full ``wr-gym db status`` report.

    Raises:
        DatabaseUnavailable: The database could not be reached.
    """
    engine = database.engine
    try:
        runner = migration_runner(engine)
        current = runner.current()
        heads = runner.heads()
        row_counts: dict[str, int] = {}
        if current is not None:
            with database.read() as session:
                for model in _ROW_COUNT_MODELS:
                    count = session.execute(select(func.count()).select_from(model)).scalar_one()
                    row_counts[model.__tablename__] = count
        integrity = integrity_check(engine)
        size_bytes = database_size_bytes(engine)
    except DatabaseError:
        raise
    except Exception as exc:  # noqa: BLE001 — translated into the suite's own error type below
        raise DatabaseUnavailable(f"Could not open the database: {exc}") from exc
    head = heads[0] if heads else ""
    return DatabaseStatus(
        dialect=engine.dialect.name,
        current_revision=current,
        head_revision=head,
        is_at_head=current == head,
        table_row_counts=row_counts,
        size_bytes=size_bytes,
        integrity_ok=integrity.ok,
        integrity_detail=integrity.detail,
    )


def database_health(database: Database) -> tuple[str, str]:
    """The ``database`` health component: ``(status, detail)`` from WeightsDB's own report."""
    report = weightsdb_database_health(database.engine, migration_runner(database.engine))
    if report.status == "ok":
        return "ok", f"{report.dialect} at head"
    return report.status, "; ".join(report.degraded_reasons) or "database unreachable"

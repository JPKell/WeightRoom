"""tests/fixtures/databases/ — built ahead of W7 (see the README there); this file is the lazy
code's one runnable check that they are what they claim to be, so a later accidental edit or
regeneration is caught here rather than discovered mid-W7.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Mirrors migration 0001's own `KNOWN_REVISIONS` (infrastructure/db/migrations/versions/
# 0001_initial_schema.py) — not imported from there: a migration file's leading digit makes it
# an awkward, non-obvious import for anything outside Alembic's own loader.
KNOWN_REVISIONS: tuple[tuple[str, str], ...] = (
    ("freeweight", "0009"),
    ("freeweight", "0010"),  # migration 0005, row WA1
    ("freeweight", "0011"),  # migration 0009, row WY10
    ("loadcoach", "0015"),
    ("ideapress", "0010"),
    ("ideapress", "0011"),  # migration 0008, row W9
    ("promptcadence", "0011"),
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "databases"


def _revision(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()
    assert row is not None, f"{path.name} has no alembic_version row"
    return str(row[0])


def test_every_known_application_has_a_fixture_at_its_known_revision() -> None:
    for app, revision in KNOWN_REVISIONS:
        path = _FIXTURES / f"{app}-{revision}.sqlite3"
        assert path.exists(), f"missing fixture for {app} at its known revision {revision}"
        assert _revision(path) == revision


def test_the_unknown_revision_fixture_is_not_in_known_revisions() -> None:
    path = _FIXTURES / "loadcoach-unknown-9999.sqlite3"
    assert path.exists()
    revision = _revision(path)
    assert revision == "9999"
    assert ("loadcoach", revision) not in KNOWN_REVISIONS

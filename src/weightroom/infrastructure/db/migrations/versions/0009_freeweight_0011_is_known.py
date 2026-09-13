"""freeweight 0011 is a known revision

FreeWeight's migration ``0011`` (row WX7) adds one nullable column, ``machines.nickname``: the
operator's own label for a machine, written only by FreeWeight's ``PATCH /api/v1/machines/{id}``
and never used to identify anything. The guard refuses a revision ``known_revisions`` does not list
before it reads a table (ADR-0123 rule 3), so until this build learns it every FreeWeight database
page past the admin one was degraded by name (found at row WY10).

Nothing in the guard changes: ``machines`` is already in the *Subject identity, hashed* lock class
(ADR-0124), so a raw write to it — the new column included — stays refused, and the nickname keeps
its one audited writer. ``0009`` and ``0010`` stay known: an installation that has not upgraded
FreeWeight is still one this build reads.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-13 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_known_revisions = sa.table(
    "known_revisions",
    sa.column("app", sa.String()),
    sa.column("revision", sa.String()),
    sa.column("weightroom_version", sa.String()),
    sa.column("notes", sa.String()),
)


def upgrade() -> None:
    op.bulk_insert(
        _known_revisions,
        [
            {
                "app": "freeweight",
                "revision": "0011",
                "weightroom_version": "1.0.0",
                "notes": "machines.nickname (FreeWeight row WX7; learned at row WY10)",
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        _known_revisions.delete().where(
            (_known_revisions.c.app == "freeweight") & (_known_revisions.c.revision == "0011")
        )
    )

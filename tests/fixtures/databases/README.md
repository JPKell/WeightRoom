# Fixture databases

One SQLite file per application, migrated to the exact revision `known_revisions` seeds
(migration `0001`, row W1) — built ahead of row W7 so that row starts with the fixtures its own
kickoff already assumes exist. Each is empty (no application data, only the schema): W7 fills
them with rows as its own tests need them.

FreeWeight has three since row WY10: `0011` (migration `0009`) is its head; `0010` (migration `0005`,
row WA1) is what the never-writable guard test reads; `0009` stays, because `known_revisions` still lists it and the
database-page tests written at W7 read it.

| File | Application | Revision | Rows |
|---|---|---|---|
| `freeweight-0011.sqlite3` | FreeWeight | `0011` (known head, row WY10: `machines.nickname`) | none |
| `freeweight-0010.sqlite3` | FreeWeight | `0010` (still known; the never-writable guard test reads it) | none |
| `freeweight-0009.sqlite3` | FreeWeight | `0009` (still known) | none |
| `loadcoach-0015.sqlite3` | LoadCoach | `0015` (known head) | none |
| `ideapress-0011.sqlite3` | IdeaPress | `0011` (known head, row W9: `attempts.prompt_source`) | none |
| `ideapress-0010.sqlite3` | IdeaPress | `0010` (still known) | none |
| `ideapress-0011-journey.sqlite3` | IdeaPress | `0011` (known head) | the database IdeaPress's own app left after recording `tests/fixtures/ideapress` (row WP5): two projects, one researched, planned, drafted, paused, cancelled, resumed and revised |
| `promptcadence-0011.sqlite3` | PromptCadence | `0011` (known head) | none |
| `loadcoach-unknown-9999.sqlite3` | LoadCoach | `9999` (not a real revision) | none |

The last one is `loadcoach-0015.sqlite3` with `alembic_version` hand-stamped to `9999` — for the
"an unknown `alembic_version` degrades that application's database pages by name" test (spec §11
contract 4, ADR-0123 rule 3), which needs a schema WeightRoomGym's `known_revisions` does not
recognise, not a schema that does not exist.

## Regenerating

Built from each application's own migration history, on its own venv, against a throwaway
database — never the operator's real one:

```bash
# FreeWeight, LoadCoach, PromptCadence: db upgrade takes --config
scratch=$(mktemp -d)
printf '[storage]\ndatabase_url = "sqlite:///%s/freeweight.sqlite3"\n' "$scratch" > "$scratch/config.toml"
~/ai/suite/FreeWeight/.venv/bin/freeweight db upgrade --config "$scratch/config.toml"
cp "$scratch/freeweight.sqlite3" freeweight-0010.sqlite3

# IdeaPress: no --config on `db upgrade`; override by environment instead
IDEAPRESS_STORAGE__DATABASE_URL="sqlite:///$scratch/ideapress.sqlite3" \
  ~/ai/suite/IdeaPress/.venv/bin/ideapress db upgrade
cp "$scratch/ideapress.sqlite3" ideapress-0010.sqlite3

# the unknown-revision fixture
cp loadcoach-0015.sqlite3 loadcoach-unknown-9999.sqlite3
python3 -c "
import sqlite3
c = sqlite3.connect('loadcoach-unknown-9999.sqlite3')
c.execute(\"UPDATE alembic_version SET version_num = '9999'\")
c.commit()
"
```

Regenerate only when an application's known revision moves (a new row in `migration 0001`'s
`KNOWN_REVISIONS`, or a later migration that adds one) — check first with `git diff` that the
new file only touches the tables the new migration actually changed.

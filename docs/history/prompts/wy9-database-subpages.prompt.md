# Kickoff — Row WY9: the database page becomes Tables, Query and Admin

**Row:** `WY9` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read §1 fact 8, §2.1, §2.4, §4 and §5 first. **Written:** 2026-09-12. **Model:** Sonnet 5 · high.
**Wave:** 2.

**Repository:** WeightRoom. **Worktree:** `~/ai/worktrees/weightroom-wy9`, branch
`row/wy9-database-subpages`, from **WY1's gate A commit** (§2.4). **Throwaway console:** 8815, trust
8816.

```bash
BASE=$(git -C ~/ai/suite/WeightRoom log row/wy1-shell-nav --grep='row WY1 gate A' -1 --format=%H)
test -n "$BASE" || { echo "WY1 gate A not committed yet — stop"; exit 1; }
git -C ~/ai/suite/WeightRoom worktree add ~/ai/worktrees/weightroom-wy9 -b row/wy9-database-subpages "$BASE"
cd ~/ai/worktrees/weightroom-wy9 && python3.14 -m venv .venv
.venv/bin/pip install -q -e ".[dev]" && .venv/bin/pip install -q -e ~/ai/suite/py/MirrorWall
```

**Read before code:** ADR-0124 (the five-part write guard), ADR-0133 and ADR-0134 (cascades,
FreeWeight deletion through its API, backups), `web/routes/databases.py` (all of it),
`database.html`, `database_table.html`, `databases.html`, `services/db_reader.py`,
`services/db_guard.py`, `services/db_curated.py`, and every test that names these routes (in
`tests/security` especially).

## What the operator asked for

*"On the database page the links should be at the very top, and they do not take you to a page
showing the tables; Query just shows the admin page."* It was reported on FreeWeight's tab; the
template is shared by all four applications, so fix it for all four.

## Build

1. **Three subpages** for each application, each with the page bar as the first element:
   `page_nav(links=[Tables → /apps/{app}/database, Query → /apps/{app}/database/query,
   Admin → /apps/{app}/database/admin], actions=[JSON → /api/v1/apps/{app}/db/tables,
   Revision → /api/v1/apps/{app}/db/revision, Docs])`, with `current` set.
   * **Tables** (`/apps/{app}/database`, the existing URL): the revision block and the tables list.
   * **Query** (`/apps/{app}/database/query`, new GET): the SQL console and its results.
   * **Admin** (`/apps/{app}/database/admin`, new GET): the application's own statistics, its own
     operations (curated `db` verbs), the delete preview, and the backups.
   Split `database.html` into the three templates; shared parts go in a small include. Delete
   `database.html` if nothing still renders it.
2. **Every POST lands on its own subpage.** `POST …/database/query` renders the Query page with
   results. `POST …/database/curated` and the delete preview and confirm render the Admin page. The
   guard's dry-run and write on `…/database/{table}/write*` render the table page as today. Keep
   every POST's path, form fields, CSRF and audit rows unchanged: only what it renders changes. If a
   handler redirects today, keep the redirect and point it at the right subpage.
3. **`database_table.html`**: its heading breadcrumb stays; give it the same page bar, with *Tables*
   current.
4. **`databases.html`** (the console's `/database` index across applications): convert its strip, if
   any, to `page_nav`, and add nothing else.
5. **No anchors are needed any more.** Remove `#db-tables`, `#db-query` and `#db-admin`. Old
   bookmarks with those fragments still load the Tables page, which is acceptable.
6. **The unavailable state** (no database to read) shows on all three subpages, below the bar.
7. Drop the introductory paragraph. The read-only guarantee is already in the page source footer and
   the docs; keep a one-line `page_source`.

## Tests

Each subpage renders for each application from fixtures, with its section and without the other
two; the Query POST renders the Query page with results and the Admin POST renders Admin; the
guarded-write flow and the security tests pass unchanged (run `tests/security` explicitly and quote
the line); the `unavailable` state shows on every subpage; the page-nav duplicate test passes (the
left menu's *Database* entry is `/apps/{app}/database`, so the *Tables* link repeats it; **resolve
this**: mark the left-menu entry `selected` for all three subpages and make *Tables* the bar's
current link, then check whether the duplicate test must treat a bar link to the page's own
left-menu entry as allowed, and if so change the test with a one-line rule and a comment, and flag it
for WY10). Screenshots of the three FreeWeight subpages and the LoadCoach Admin page at 1440 px and
412 px, light and dark.

## Out of scope

The guard's logic, the SQL console's read-only enforcement, the cascades, and any file §4 gives to
another row.

Finish line, commits, `WY9_HANDOFF.md` and report: roadmap §5.

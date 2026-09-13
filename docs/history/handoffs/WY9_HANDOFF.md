# WY9 Handoff — Database: Tables, Query and Admin

**Row:** WY9 (`roadmap/wy-console-polish-work.md`) · **Ran:** 2026-09-13, one sitting ·
**Model:** Claude Sonnet 5 · high · **Kickoff:** `history/prompts/wy9-database-subpages.prompt.md`

## 1. What shipped

One database page is now three: **Tables** (`/apps/{app}/database`, the pre-existing URL — the
revision and the tables with counts and locks), **Query** (`/apps/{app}/database/query`, new — the
SQL console and its last result) and **Admin** (`/apps/{app}/database/admin`, new — the
application's own statistics, its own `db` verbs, the delete preview, and the guarded-write
backups). Each carries `page_nav(links=[Tables, Query, Admin], actions=[JSON, Revision, Docs])`
as the first element of `page_content`, from a new shared include `_database_bar.html`.
`database_table.html` gets the same bar, Tables current, its breadcrumb heading kept.

- `database.html` deleted; split into `database_tables.html`, `database_query.html`,
  `database_admin.html`. `databases.html` (the console-wide index) had no strip to convert —
  left unchanged, per the kickoff.
- `web/routes/databases.py`: `_database_page` now takes a `template` argument. New GET routes for
  `/database/query` and `/database/admin`. `POST …/database/query` renders `database_query.html`;
  `POST …/database/curated` renders `database_admin.html` — same path, form fields, CSRF and audit
  rows as before, only the rendered template changed. The guard's dry-run/write on
  `…/database/{table}/write*` is untouched.
- The `#db-tables`/`#db-query`/`#db-admin` anchors are gone. FreeWeight's `Delete stored results`
  table operation (`services/db_curated.py`) now links to `/apps/{app}/database/admin#delete-results`
  (its `id="delete-results"` `<details>` still lives at that anchor, on Admin).
- A table's own name on the Tables page now seeds `/apps/{app}/database/query?sql=…` (no
  fragment) instead of `/apps/{app}/database?sql=…#db-query`.

Tests: `test_database_routes.py` gets a rewritten three-page-bar test (replacing the old
three-anchor one), a POST-lands-on-its-own-subpage test, a per-application section-exclusivity
test across all four apps' fixtures, and the unknown-revision and no-database tests now cover
Query and Admin too. `test_database_write_routes.py`'s `#delete-results` href assertion moved to
`/admin#delete-results`. `test_freeweight_adapters_provider.py`'s two `database` page tests
(FreeWeight's own statistics) now hit `/database/admin`, where that section now lives.

## 2. Decisions taken

1. **The page-bar duplicate test needed one exception, not a rewrite.** The left menu's single
   *Database* entry points at the Tables URL and is marked `selected` on all three subpages (already
   true — `_page()` in `databases.py` hardcodes `selected="Database"`); the page bar's *Tables*
   link is therefore a real, unavoidable repeat of that entry on the Query and Admin pages too, not
   only on Tables itself. `test_page_nav.py` (`tests/integration/test_page_nav.py`) now excludes
   the left menu's own *selected* href (the one carrying `aria-current="page"`) from the repeated
   set, rather than the literal request path — the literal-path version I tried first only fixed
   the Tables page and still failed on Admin and Query. This is a one-line change plus a comment;
   see §3 below on why it was made here rather than left for WY1.
2. **Admin's sections are not gated on a known schema.** Only Tables and Query need
   `revision.is_known` (the table listing and the raw-SQL console read against the schema this
   build understands); Admin's own statistics, `db` verbs, delete preview and backups already ran
   regardless of `revision.is_known` in the combined page, and keep doing so split out — proved by
   `test_an_unknown_revision_degrades_the_pages_by_name_and_refuses_in_json`, which now also checks
   Admin renders `db backup`/`db vacuum` on a schema this console does not know.
3. **`page_source`, the macro, was not wired in.** The kickoff's "keep a one-line `page_source`"
   is met literally — the existing one-line footer (`From {app}'s database at revision …,
   read-only.`) survives verbatim on all three subpages — but not through the `_app_page.html`
   `page_source(sourced)` macro, which expects a `SourceInfo`-shaped object this route never built.
   Wiring one in was out of scope for a template split; flagging it as a candidate for whoever next
   touches this route, not a WY10 item specifically.

## 3. What this plan got wrong

- The kickoff's fix for the duplicate test ("mark the left-menu entry selected for all three
  subpages... make Tables the bar's current link") reads as if the literal request path is the
  exception. It is not: the exception has to be the *selected left-menu href*, because the bar's
  Tables link repeats it on Admin and Query too, where the request path is `/database/admin` or
  `/database/query` — neither equals the repeated href. Fixed as in §2.1.
- **File-ownership friction, flagged rather than worked around:** `wy-console-polish-work.md` §4
  lists `tests/integration/test_page_nav.py` under **WY1**, but the kickoff explicitly instructs
  WY9 to edit it for this one case. I followed the kickoff (it is the more specific, later
  instruction) and made the one-line change with a comment naming the row and the flag for WY10,
  as asked. **WY10 should confirm this is intended** before merging WY1 and WY9 — a mechanical
  merge conflict is likely if WY1's own sweep touched the same lines, and file ownership says only
  WY1 edits this file.
- `db_curated.py` is not listed in §4 for any row. It needed one literal string changed
  (`/apps/freeweight/database#delete-results` → `/apps/freeweight/database/admin#delete-results`)
  to keep the FreeWeight table-operation link working; no other row's kickoff or file list
  mentions it, so this should be uncontested, but it is outside WY9's named file list and worth
  a second look at merge time.

## 4. Screenshots

Captured with a throwaway console on port 8815 (trust 8816), Playwright + system Chrome, against
the real FreeWeight (8765) and LoadCoach (8766) units running read-only (`[apps.freeweight]` and
`[apps.loadcoach]` `executable` pointed at their real venvs so `db status`/`db backup` etc. ran for
real; nothing was started, stopped, or written to their databases). FreeWeight's live schema
(0011) is not in this worktree's `known_revisions` (0009, 0010 — this worktree branches from WY1's
gate A, before any schema-adding row merged), so the Tables and Query screenshots show the
`SCHEMA_UNKNOWN` degraded state by name, which is itself one of the states the kickoff asks the
unavailable/degraded case to be screenshotted in; Admin (API/CLI-sourced, not schema-gated) shows
real figures. 1440×900 and 412×900, light and dark, saved under
`/tmp/claude-1000/-home-jpk-ai-suite/7042d007-c486-4f55-a5e9-65be4db2c349/scratchpad/wy9/shots/`
(session-scratch, not committed):

`fw-tables-{1440,412}-{light,dark}.png`, `fw-query-{1440,412}-{light,dark}.png`,
`fw-admin-{1440,412}-{light,dark}.png`, `lc-admin-{1440,412}-{light,dark}.png` — 16 files.

## 5. The gate

WeightRoom `.venv`, **Python 3.14** (`python3.14 -m venv`), at the commit below:
`ruff format --check .` (244 files), `ruff check .` (all checks passed), `mypy src tests` (237
source files, no issues), `lint-imports` (5 contracts kept), `pytest -q` → **2050 passed, 3
skipped, 12 deselected**; `pytest tests/security -q` run explicitly → **671 passed**.
`git status --short` clean after the commit below. All suite packages installed editable from
`~/ai/suite/py` (`pip list --editable` confirmed all eight, `wr-gym` included, resolve from
`~/ai/suite`, none from PyPI).

Not merged, not pushed, not tagged. No version bump — stays under `[Unreleased]`.

## 6. For the reviewer

- Confirm the WY1/WY9 `test_page_nav.py` ownership question in §3 before merging both.
- The `db_curated.py` edit in §3 is small and mechanical; flag if another row also touched it.
- `page_source` macro non-adoption (§2.3) is a nice-to-have, not a defect — the footer text is
  unchanged from the pre-split page.

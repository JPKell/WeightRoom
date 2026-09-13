# WX15 Handoff — The PostgreSQL bootstrap script

**Row:** WX15 (`roadmap/wx-console-ux-work.md` §1, wave 3) · **Ran:** 2026-09-12/13, unattended,
one sitting · **Model:** Claude Sonnet 5 · high · **Kickoff:**
`history/prompts/wx15-the-postgresql-bootstrap-script.prompt.md` · **Branch:**
`row/wx15-postgres-script` in `~/ai/worktrees/weightroom-wx15`, branched from `main` at `b052755`
(all of wave 2). **Not merged.**

## 1. What shipped

One commit in WeightRoom only:

* **`services/database.py`** gains `postgres_bootstrap_script(config_paths: Mapping[str, Path])`
  — a pure function, no I/O — plus `POSTGRES_DRIVER: Final = "psycopg"` (read from
  `py/WeightsDB/pyproject.toml`'s `postgres` extra, `psycopg[binary]>=3.2,<4`; hardcoded rather
  than parsed at runtime — nothing else in the console reaches across into a sibling repo's
  `pyproject.toml` at runtime, and doing so here for one constant would be new coupling, not
  reuse). It renders, in order: (1) the `docker run` server line (`postgres:16`, named
  `suite-postgres`, volume `suite-pg`, commented as skippable when a server already runs — the W7
  local-PG leg's image); (2) one `psql` heredoc creating an owner-scoped role and database per
  application (`freeweight`, `loadcoach`, `ideapress`, `promptcadence`, `weightroom`, in
  `domain.units.UNIT_APPLICATIONS` order); (3) each application's real `config.toml` path (from
  `config_paths`) with its `[storage]` `database_url` line and the `<APP>_STORAGE__DATABASE_URL`
  environment-variable alternative; (4) `<app> db upgrade` for the four plus `wr-gym db upgrade`,
  with the note that `auto_migrate` defaults off once a URL is not `sqlite://`; (5)
  `systemctl --user restart <unit>` for all five, via `domain.units.unit_name`. The password is
  always the shell variable `$PG_PASSWORD` — the function's signature has no password parameter,
  so it cannot print a literal one by construction.
* **`web/routes/databases.py`**'s `databases_page` (`GET /database`, the console-wide page) now
  also resolves each of the five applications' real `config.toml` path — for the four, via the
  already-cached `state.schemas` + `settings_forms.read_schema_document`/`config_file_path` (the
  same mechanism `doctor.py` uses: a live `<app> config schema --json`, TTL-cached, degrading to
  the XDG default when the application is unreachable or too old to answer); for `weightroom`
  itself, `state.config_path` — and passes `postgres_bootstrap_script(config_paths)` into the
  template as `bootstrap_script`.
* **`databases.html`** gains a "PostgreSQL bootstrap" section: a paragraph explaining the
  print-never-run stance (ADR-0123 rule 2, the `templates/ollama.html:36-41` precedent), the
  script in a `<pre id="pg-bootstrap"><code>`, and a **Copy** button — one inline `onclick`
  guarded on `navigator.clipboard`, no separate `<script>` block, no new JS budget entry needed.

## 2. Decisions taken

1. **Config paths are read the same way `doctor.py` already reads them** (cached schema document
   → `config_file_path`), not by adding a new mechanism. The row text says "`services/config_files.py`
   knows it"; that module only edits files in place and has no path-resolution function — the
   actual authority is `settings_forms.config_file_path`, which I used. Noted as a correction, not
   silently substituted.
2. **`POSTGRES_DRIVER` is a hardcoded module constant with a docstring citing the pyproject line**,
   not a runtime parse of `py/WeightsDB/pyproject.toml`. YAGNI: nothing else in this console reaches
   into a sibling repository's packaging metadata at runtime, and the fact does not change without
   a person editing this file anyway.
3. **The env-prefix form (`<APP>_STORAGE__DATABASE_URL`) is computed as `app.upper() + "_"`**,
   not read live from each application. Verified by reading all five `config.py` modules'
   `ENV_PREFIX` constants (`FREEWEIGHT_`, `LOADCOACH_`, `IDEAPRESS_`, `PROMPTCADENCE_`,
   `WEIGHTROOM_`) — the pattern holds uniformly, so computing it is not a guess, it's the fact
   restated as code.
4. **The one-shot `docker run` uses the *same* `$PG_PASSWORD` value for the server's `postgres`
   superuser and every application role**, matching the roadmap row's own literal example line
   and the ollama-page precedent's simplicity level — a second variable would be a feature this
   row was not asked for.
5. **The Copy button is one inline `onclick` attribute**, not a new `<script>` block or a shared
   JS helper — `chat_thread.html` already has a fuller clipboard-copy pattern scoped to chat code
   blocks, but reusing it would have meant importing chat's SSE-refresh machinery for one button;
   this page's version is three lines and self-contained.

## 3. What the row text got wrong

* **The section is `[storage]` with key `database_url`, not `[database]` with key `url`.** All
  five `config.py` modules (`FreeWeight`, `LoadCoach`, `IdeaPress`, `PromptCadence`, WeightRoom's
  own) declare a `StorageSettings` class with a `database_url` field under `[storage]`; there is
  no `[database]` section anywhere in the suite. The rendered script and the CHANGELOG entry use
  the real shape.
* **The env-var form is `<APP>_STORAGE__DATABASE_URL`, not `<APP>_DATABASE__URL`** — the row's
  guessed form skips the `STORAGE` segment pydantic-settings-style nested env vars need.
* **`auto_migrate` (not `migrate_on_startup`) defaults off on PostgreSQL for *all five*
  applications, not only IdeaPress and PromptCadence.** Every one of the five `StorageSettings`
  classes has the identical `_apply_data_dir_defaults`/`_apply_data_dir_default` rule: unset
  `auto_migrate` becomes `False` the moment `database_url` does not start with `sqlite`. The
  row's narrower claim was still true of those two, just not the whole story; the script states
  the general rule.

## 4. Tests

* `tests/unit/test_postgres_bootstrap.py` (new, 4 tests): the pure function directly — every app
  named with its config path, the real driver and no literal password (every line containing
  `"PASSWORD"` also contains `"PG_PASSWORD"`), the upgrade/restart lines for all five, the
  skip-if-already-running docker comment.
* `tests/integration/test_database_routes.py`: one new test,
  `test_databases_page_prints_the_postgres_bootstrap_script`, over the existing `_console` fixture
  (which registers `freeweight` only — the other three resolve through the XDG-default fallback,
  exercising that path too) — asserts the rendered `/database` page names all five applications,
  each app's own `db upgrade` line (or `wr-gym db upgrade`), `psycopg`, `config.toml`, and again
  the no-literal-password line check.

## 5. Screenshots

Scratchpad `wx15/shots/` (4 PNGs: `databases-{1440,412}-{light,dark}.png`), Playwright + system
Chrome against a throwaway, open-loopback console on `127.0.0.1:8809` (trust `8810`, its own
scratch `XDG_*`, no `[apps.*]` config). `/database` renders correctly in both themes at both
widths — the four applications show "not installed" (nothing registered in this throwaway's
config, so their config paths fall back to the XDG default, e.g.
`.../xdg/config/freeweight/config.toml`, and WeightRoom's own resolves under
`.../xdg/config/wr-gym/config.toml`, the console's own distribution name) — and the bootstrap
script renders in full underneath with the Copy button. At 412 px the `<pre>` block wraps long
lines (no horizontal page scroll), matching `templates/ollama.html`'s own unwrapped `<pre>`
precedent — no new CSS was needed. Killed by environ-verified pid afterward; the operator's own
`weightroom.service` (port 8769) was never touched, and nothing was written anywhere (`GET` only).

## 6. Gate

Interpreter: `.venv/bin/python` → Python 3.14.4.

```
ruff format --check .   → All checks passed! (one file auto-formatted first, then clean)
ruff check .            → All checks passed!
mypy src tests          → Success: no issues found in 235 source files
lint-imports            → Contracts: 5 kept, 0 broken
pytest                  → 2003 passed, 3 skipped, 12 deselected, 172.78s
```

`git status --short` clean after the commit.

## 7. For whoever merges this

1. **Not merged, not pushed, no version bump** — everything under `## [Unreleased]`.
2. This row touches only `databases.html`, `routes/databases.py`'s console-wide route,
   `services/database.py`, and their tests — the collision rules' disjointness from WX8/WX12/WX13
   holds; `git diff --stat` shows exactly those files plus `CHANGELOG.md` and the two test files.
3. **Worth reviewing before merge:** the two corrections in §3 (the row's `[database]`/`url` and
   `migrate_on_startup` naming) — if another row or a doc elsewhere in this arc copied the same
   guessed names, they should be checked too. Also worth a glance: whether `POSTGRES_DRIVER`
   should ever be read live rather than hardcoded, should `weightsdb` ever add a second supported
   driver (currently there is exactly one, so YAGNI).
4. No GPU, no shared unit, no other row's files were touched.

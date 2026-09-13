# WX10 Handoff — IdeaPress tab

**Row:** WX10 (`roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12/13, unattended, one
sitting · **Model:** Claude Sonnet 5 · high · **Kickoff:**
`history/prompts/wx10-ideapress-tab.prompt.md` · **Branch:** `row/wx10-ideapress-tab` in
`~/ai/worktrees/weightroom-wx10`, branched from `main` at `765560c` (all of wave 1). **Not
merged.**

## 1. What shipped

One commit, `db4c7e3`, in WeightRoom only (the row's kickoff scoped it that way — no IdeaPress
repo changes):

* **The top nav** (`_ip.html`'s new `projects_nav(nav, current)` macro): the eight most recent
  projects by name, *All*, *New*, on `ip_projects.html` and `ip_project.html`. Its own read
  (`routes/ideapress._nav_projects`, unfiltered, `page_rows=8`) rather than the page's own —
  a status filter or which project is open can never make a recent project disappear from it.
  `current` is a project id, the string `"new"`, or `None`, so exactly one entry (a project link,
  *All* or *New*) carries `aria-current="page"`.
* **The create form moved to its own page**, `GET /apps/ideapress/projects/new`
  (`ip_project_new.html`, `routes/ideapress._project_new`/`project_new_page`, registered *before*
  `GET /projects/{project_id}` so `new` is never swallowed as a project id). `POST /projects`
  (`create_from_page`) is unchanged except its refusal now renders back onto this page rather than
  onto the list. `ip_projects.html` no longer reads `GET /workflows` for the create form's select
  — that read moved with the form.
* **Backends**: the three inference-mode cards became one dense table row each
  (`table_id="ip-backends"`, sortable, the egress/reachable/selected/fallback/pinned wording kept
  verbatim from the old cards so nothing an operator or a test read from them changed). Below it,
  **Models available in LoadCoach** — `loadcoach_pages.models_api` (unmodified; read directly,
  not through a wrapper) joined in the template to `ideapress_pages.loadcoach_bindings(defaults)`,
  a new pure function that inverts `GET /settings`'s `models.stages.*` keys into *binding value →
  stage name(s)*. The template matches a LoadCoach model to a binding by
  `canonical_id.split("@")[0] == binding_value` (ADR-0024: `provider/name@sha256:digest`, and
  IdeaPress's own binding string carries no digest). An available-and-enabled model renders
  plainly with its bound stage(s) and a link to `/apps/ideapress/settings` (this page never
  writes); anything else is dimmed with an *Enable in LoadCoach* link to
  `/apps/loadcoach/models/{model_ref}`.
* **`app_page_header`** (`_app_page.html`, built at WP1/WX3 with no caller): `ip_projects.html`,
  `ip_project.html`, `ip_backends.html` and `ip_project_new.html` are its first four callers.
  Cross-page links (Workflows/Backends; Plan/Workspace/Units/Export; Projects/Settings; All
  projects) moved into its `{% call %}` action slot; each page's old `<p class="muted">` lead
  sentence became the macro's `supporting` argument.

**Gate**, `.venv` **Python 3.14.4**, at `db4c7e3`: `ruff format --check .` (240 files), `ruff
check .`, `mypy src tests` (233 files, 0 issues), `lint-imports` (5 kept, 0 broken), `pytest` →
**1961 passed, 3 skipped, 12 deselected**. `git status --short` clean before and after.

## 2. Decisions taken

1. **The nav is a second, independent read, not a slice of the page's own.** `_nav_projects`
   calls `ip.projects_api`/`projects_db` with `status=None, content_type=None, archived=False,
   cursor=None, page_rows=8` regardless of what the list page's own filters are. This costs a
   second `GET /projects` on every Projects/one-project/new-project page view (three call sites);
   accepted as the price of a nav that never lies about what "recent" means because of a filter
   the operator typed. Same pattern as the existing Units page's project picker.
2. **The LoadCoach models read is gated on *this page's own* liveness (`sourced.live`, IdeaPress's
   `backends_api`), never LoadCoach's own reachability.** Every other secondary read on this route
   (`ip.settings_api` for `defaults`, `ip.workflows_api` for the create form) already follows that
   rule; I kept it rather than making the new read stand out, and it matters in practice — the
   security suite's generic `console` fixture (`tests/security/test_audit_routes.py`) only marks
   `loadcoach.service` active, so IdeaPress's own view is never "running" there and the LoadCoach
   call correctly never fires. Gating on LoadCoach's own status instead would have made backends
   pages make an unconditional external call on every render, including from that fixture where
   `GET /models` is not mocked — first found the hard way (an unhandled
   `respx.AllMockedAssertionError`, not a `SuiteError`, propagating as a 500) before I added the
   gate.
3. **Matching a binding to a model is a template-side string split, not a new service function
   with its own tests.** `loadcoach_bindings` (the settings→stages inversion) is the one branch
   worth a Python function and direct coverage; multiplying `canonical_id`'s prefix against it is
   the same one-line kind of lookup the rest of `_ip.html`/`ip_backends.html` already does inline
   (e.g. `_lc.html`'s own row-building macros). No new service function for it.
4. **Nothing else on Backends' wording changed.** The egress badges (*egress unknown* / *sends
   content off this machine* / *stays on this machine*) and each backend's *Test `<mode>`* button
   text are byte-identical to the pre-row cards, deliberately — the row asked for a layout change
   ("shrink to one line"), not a copy change, and keeping the words let the existing tests catch
   any accidental behavior change instead of needing a rewrite to match new wording.
5. **The prompts page's IdeaPress warning** (`services/prompts.py:97-106`, rendered through the
   generic `routes/prompts.py` → `prompts.html`/`prompt.html`'s `{{ pack.rule }}`/`{{ detail.rule
   }}`) is intact and unconditioned by application — WX8, which is scheduled *after* this row
   (wave 3, not wave 2 — the roadmap's own phase table has it that way), is what will touch
   `prompt.html` for FreeWeight's hybrid form. I read `prompt.html` end to end: the notice is a
   plain `{{ detail.rule }}` with no `{% if app == … %}` branch around it. **Worth a glance when
   WX8 lands**: whatever the hybrid form becomes for FreeWeight, that one line must survive
   untouched for every app `surface_for` covers, IdeaPress included, since neither `prompts.py` nor
   `routes/prompts.py` (both app-generic) are WX8's to change per its own row cell.

## 3. New routes

| Method | Path | What |
|---|---|---|
| `GET` | `/apps/ideapress/projects/new` | The create form, on its own page |

No other route added; `POST /apps/ideapress/projects` is unchanged (same path, same body, same
audit action) — only which page a refusal re-renders changed.

## 4. Screenshots

Session scratchpad, `wx10-demo/shots/` (16 PNGs: `{projects,project,project_new,backends}` ×
`{1440,412}` × `{light,dark}`), taken with Playwright + system Chrome against a throwaway,
open-loopback console on `127.0.0.1:8799` (trust `8800`, its own scratch `XDG_*`, no `[apps.*]`
config — WX1's method) reading the operator's live IdeaPress/LoadCoach over HTTP, GET only. Killed
by environ-verified pid afterward; nothing written anywhere by this row's browsing (no form was
submitted against the live console). `weightroom.service` (the operator's own, port 8769) was
never touched.

* `projects-*`: the nav renders three real projects by title (*WP6 injection corpus as a brief*,
  *WP6 verification: keeping a local LLM box out of swap*, *WP5 demo: drafting on your own
  machine*) plus *All* (current, underlined) and *New*; the create-form `<details>` is gone from
  this page.
* `project-*`: the same nav with the open project (*WP6 injection corpus as a brief*) current and
  underlined; its brief is the WP5 injection corpus, rendered inert exactly as WP5's handoff
  described (no change here — just visible in passing).
* `project_new-*`: the moved create form, *New* current in the nav, the workflow `<select>`
  populated from `GET /workflows` (`standard 1.0`).
* `backends-*`: the one (`ollama`) configured backend as a single dense table row with a
  *Columns* toggle (`sortable=true`, six-plus columns); **Models available in LoadCoach says
  "LoadCoach could not be read"** — expected and not a defect: this throwaway carries no LoadCoach
  bearer token (the kickoff's own correction says not to chase this live and to take it from
  fixtures instead), so `GET /models` there is a `401` `_optional` swallows. The mocked-fixture
  path (an available+enabled model plain with its bound stage and a Settings link; an unavailable
  one dimmed with *Enable in LoadCoach*) is what
  `test_backends_show_egress_the_round_trip_test_and_loadcoachs_models` and
  `test_a_backend_page_with_no_binding_still_reads_loadcoach` in
  `tests/integration/test_ideapress_projects.py` prove instead.
* 412 px: the nav wraps to one link per line without any page-width overflow; the backends table
  scrolls inside its own `.table-scroll`, never the page.

## 5. Tests added/changed

All in `tests/integration/test_ideapress_projects.py` (18 tests now, up from 15):

* Renamed `test_the_running_projects_page_lists_from_the_api_with_the_create_form` →
  `…_with_the_nav`; dropped its create-form assertions (moved with the form), added the nav's
  three link shapes.
* New: `test_the_new_project_page_shows_the_create_form`,
  `test_a_stopped_new_project_page_says_creating_needs_the_api`.
* `test_the_list_sends_its_filters_and_follows_ideapress_cursor`: fixed — the nav's own,
  unfiltered `GET /projects` call is now *last*, not the filtered one the test means to inspect;
  changed `.calls.last` → `.calls[0]`, with a comment, plus one new assertion on `.calls[-1]`
  naming the nav's own `limit=8`.
* `test_a_stopped_projects_page_reads_the_database_with_a_start_beside_it`: the obsolete "New
  project not in page" (the button text no longer exists on this page) replaced with the nav's
  *New* link, which the database-backed fallback renders identically to the live path.
* `test_one_running_project_shows_its_plan_units_stage_history_and_forms`: one assertion added
  (the nav's `aria-current` on the open project).
* Renamed `test_backends_show_egress_and_the_round_trip_test` →
  `…_the_round_trip_test_and_loadcoachs_models`, extended with the new table's assertions and a
  `_mock_loadcoach_models` helper (loads the real `tests/fixtures/loadcoach/models.json` — no
  change to `tests/support.py` or `test_loadcoach_pages.py`, per the row's collision rules).
* New: `test_a_backend_page_with_no_binding_still_reads_loadcoach`.

Full-suite `pytest` includes all of these; `tests/security/test_audit_routes.py` (666 tests) and
`tests/integration/test_ideapress_work.py` (31 tests) were re-run in full and pass unchanged —
confirmed the new LoadCoach read's liveness gate does not touch either.

## 6. What the row text got wrong, or left for judgment

* **"`routes/ideapress_pages.py`"** in the collision rules names a file that does not exist; the
  actual split is `web/routes/ideapress.py` (pages and actions together) and
  `services/ideapress_pages.py` (the readers) — I edited both, as the rule's intent plainly means.
* The row cell's "*Workflows editor is WX12's*" is a scope note, not a defect; I did not touch
  `ip_workflows.html` or the workflows routes at all (confirmed by `git status --short` after the
  commit showing no such files).
* "**Models available in LoadCoach**... `available` + `enabled` rows normal" doesn't say what
  "normal" means for the greying of the others; I used a `<span class="muted">` around the dimmed
  model's name plus each field's own already-toned badge (`danger`/`neutral`), rather than
  inventing a new table feature (the shared `table()` macro has no per-row class hook) — worth a
  glance if a later row wants row-level tone as a first-class table feature.

## 7. For whoever merges this

1. **Not merged, not pushed, no version bump** (`wr-gym` stays `1.0.0` under `[Unreleased]`,
   ADR-0130's later bump aside).
2. **Restart `weightroom.service` after merging** to serve these pages.
3. Nothing was written to any application's database or config by this row — reads only, both in
   tests (respx-mocked) and in the live demonstration (GET only, throwaway console).
4. **Worth reviewing before merge:** decision 2 above (the liveness gate choice) and decision 3
   (matching left as a template-side split rather than a tested service function) are the two
   judgment calls furthest from the row text's letter; both are exercised by the test suite either
   way.

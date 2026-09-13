# WX11 Handoff — PromptCadence tab

**Row:** WX11 (`roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12, one sitting ·
**Model:** Claude Sonnet 5 · high · **Kickoff:** `history/prompts/wx11-promptcadence-tab.prompt.md`
· **Repository:** WeightRoom only · **Branch:** `row/wx11-promptcadence-tab` in
`~/ai/worktrees/weightroom-wx11` · **Not merged.**

## 1. What shipped

WeightRoom only, one uncommitted-then-committed change set (see §5 for the exact commit to make):

* **Trajectories splits into History / New.** `pc_trajectories.html` is now the listing alone
  (table, filter, pagination) with a `History` / `New` nav pair at the top; the submission form
  moves to its own route and template, `GET /apps/promptcadence/trajectories/new` →
  `pc_trajectory_new.html`. `POST /apps/promptcadence/trajectories` is unchanged (same path, same
  body, same audit row); a validation refusal now redisplays the **New** page (with the operator's
  text kept) instead of the listing. The New page reads live only when
  `view.running and view.reachable`; otherwise it shows a plain notice and no form (previously the
  form was gated on the *listing's* `sourced.live`, which needed a successful `GET /trajectories`
  first — the New page no longer depends on a call it doesn't need).
* **A trajectory's detail page gets a jump nav and a two-column request table.** The ids are
  written once, as a single `sections` list computed from `sourced.live`, and reused verbatim on
  both the live (explanation-document) and stopped (database) branches — `#pc-request`,
  `#pc-tool-calls`, `#pc-debits`, `#pc-egress`, `#pc-approvals`, `#pc-events` are the same anchor
  in both, `#pc-plan`/`#pc-envelopes`/`#pc-timeline`/`#pc-compactions`/`#pc-deviations` exist only
  on the live branch, `#pc-turns` only on the stopped one. "The request" (previously a `kv_list`
  definition list) is now `table([{"label": "Field"}, {"label": "Value"}], …)`, `table_id=
  "pc-trajectory-0"`, sortable — same convention as every other table this page already had.
* **Tools gets a Registry / Create a tool anchor nav** (same one-page pattern `database.html`
  already uses for Tables/Query/Admin, not a second route — the row text names a URL for
  Trajectories' New but only "a section" for this one). *Create a tool* is a static paragraph
  (what a tool is, why there is no console form, a link to the spec) — there is genuinely nothing
  to submit here. Each tool's name in the Registry table is now a link
  (`_pc.html`'s new `tool_link` macro) to `GET /apps/promptcadence/tools/{name}` →
  `pc_tool.html`, reading PromptCadence's own `GET /tools/{name}`
  (`promptcadence_pages.tool_api`, new). That page shows the description, a `kv_list` of
  registered/risk/egress/isolation/redaction (plus withheld cause when unregistered), and the
  argument schema — `parameters.properties` — as a table (Argument, Type, Required, Description).
  A `422 TOOL_NOT_FOUND` is detected by `sourced.error.details["app_code"]` and renders
  `empty_state(...)` (the page's not-found state) instead of the raw refusal box; a withheld tool
  answers `200` (found, `registered: false`, a `withheld_cause`) and renders normally. The per-row
  `json_viewer` argument dump that used to sit under the Registry table is gone — the row text's
  "leaves the list."
* **The Overview gains a PromptCadence-only section**: Active, Pending approvals, Spending today,
  three more figure cards under a `<h3>PromptCadence</h3>` heading, `overview.py`'s new
  `_promptcadence_figures(body)`. It costs no second HTTP call: `GET /system/status` already
  embeds `runtime.budget.ledger_view(trajectory=None).as_json()` under `"ledger"` — the same
  method `GET /ledger` calls — so `ledger.day.money_remaining_display` is read straight off the
  same body `_figures_from_status` already fetched, never re-derived (ADR-0030). Populated only
  when PromptCadence answered (`figures_from_api`); an empty tuple, and no new section on the
  page, for the other three applications and whenever it did not. `app.html` renders the section
  only when `overview.promptcadence_figures` is non-empty — the other three apps' Overview is
  byte-for-byte unchanged (tested: `test_running_and_reachable_reads_figures_from_the_api_…`
  asserts `overview.promptcadence_figures == ()` for LoadCoach).
* **Every reshaped page adopts `app_page_header`** (WX3's macro, added with no caller yet) —
  Trajectories, the New page, the detail page, Tools and the new per-tool page all use it; this is
  the macro's first use anywhere in the tree.

## 2. Files touched

`src/weightroom/web/routes/promptcadence.py` (new `_trajectory_new`/`trajectories_new_page`,
`tool_page`; `_trajectories` no longer carries the submission form's context; `submit_from_page`'s
refusal path calls `_trajectory_new`), `src/weightroom/services/promptcadence_pages.py` (new
`tool_api`), `src/weightroom/web/templates/pc_trajectories.html` (History only),
`pc_trajectory_new.html` (new), `pc_trajectory.html` (jump nav + two-column request table),
`pc_tools.html` (nav, `tool_link`, drops the per-row dump), `pc_tool.html` (new), `_pc.html` (new
`tool_link` macro), `src/weightroom/services/overview.py` (`Overview.promptcadence_figures`,
`_promptcadence_figures`), `src/weightroom/web/templates/app.html` (renders the new section),
`CHANGELOG.md`. Tests: `tests/integration/test_promptcadence_pages.py` (six new tests: the
History/New split, the stopped New page's notice, the Tools page's link and dropped dump, a
registered tool's schema table, an unknown tool's not-found state, a withheld tool found with its
cause; jump-nav assertions added to the existing running/stopped detail-page tests),
`tests/integration/test_promptcadence_actions.py` (the refusal test's markup assertion updated for
the New page; `test_the_pages_offer_the_forms_only_where_they_can_work` now reads
`/trajectories/new` for the tools/tiers assertions and asserts the stopped New page's notice),
`tests/unit/test_overview_status_bodies.py` (two new tests for `_promptcadence_figures`),
`tests/unit/test_overview.py` (generalised `_fake_cli`/`_view`/`_settings` to take an `app`/
`base_url`/`name`, both defaulting to the existing LoadCoach values so every prior call is
unchanged; one new test builds a PromptCadence `overview_for` call end to end).

No route in `web/rendering.py`'s nav tuples changed — `New` and the per-tool page both pass
`selected="Trajectories"`/`"Tools"`, so the existing left-menu entries (`Trajectories` →
`/apps/{app}/trajectories`, `Tools` → `/apps/{app}/tools`) keep highlighting correctly with no new
label needed.

## 3. Gate

`.venv/bin/python` **Python 3.14.4**:

* `ruff format --check .` — 240 files already formatted.
* `ruff check .` — all checks passed.
* `mypy src tests` — success, 233 source files (one real finding fixed along the way: `Figure.value`
  must be `str`, not `Any | str | None` — `_promptcadence_figures` now does `str(display)` rather
  than passing `day.get(...)` straight through).
* `lint-imports` — 5 contracts kept, 0 broken.
* `pytest` — **1967 passed, 3 skipped, 12 deselected**.

`git status --short` clean before this handoff's own commit.

## 4. Decisions taken (review before merge)

1. **Tools' "Create a tool" is an anchor section on the existing page, not a second route.** The
   row text gives an explicit path for Trajectories' New (`/trajectories/new`) but only says "a
   section" for Tools — and `database.html`'s Tables/Query/Admin nav is the precedent for that
   exact pattern already in this tree. There is nothing to submit (a tool is code, not a console
   record), so a route would have no verb to serve.
2. **The New page's "is this live" gate is `view.running and view.reachable`, not a re-read of the
   trajectories listing.** The old code borrowed `sourced.live` from the History page's own
   `GET /trajectories` call as a proxy for "PromptCadence is up"; the New page doesn't read a
   listing at all, so it asks the same question `app_pages.read` itself asks, directly.
3. **A `422 TOOL_NOT_FOUND` is distinguished from every other refusal by `app_code`, not by
   status code alone**, matching the row text's "422 → the page's not-found state" exactly — the
   generic `refusal()` box still renders for anything else PromptCadence might say about a tool
   name.
4. **The Overview's new section reads no second endpoint.** `GET /system/status`'s `"ledger"` key
   already is `ledger_view(trajectory=None).as_json()` (`system.py:112`) — the same call
   `GET /ledger` makes — so "Spending today" is that response's `day.money_remaining_display`,
   unchanged. This was checked in the code before writing any of it; worth a second look, since it
   means the row's "from the same `/system/status` + `/ledger` bodies" is read here as "the same
   bytes, twice-named," not two calls.
5. **`test_overview.py`'s helpers were generalised (default-argument, non-breaking) rather than
   duplicated**, so the new PromptCadence-overview test reuses `_fake_cli`/`_view`/`_settings`
   instead of a parallel set of LoadCoach-shaped functions.

## 5. Screenshots

Throwaway console, port 8809/trust 8810, XDG-isolated under this session's scratchpad (never the
operator's instance, which stayed on 127.0.0.1:8768 the whole time — the throwaway's
`[apps.promptcadence]` pointed at a small fixture-serving `http.server` on 127.0.0.1:8909 instead,
answering `tests/fixtures/promptcadence/*.json` verbatim, so the six changed pages could be
screenshotted with real, varied data rather than empty/degraded state). 24 PNGs (6 pages × 1440/
412 px × light/dark) in the scratchpad's `wx11/shots/`: `pc-trajectories-history`,
`pc-trajectories-new`, `pc-trajectory-detail`, `pc-tools`, `pc-tool-detail`, `pc-overview`. No
page reported `scrollWidth > clientWidth` on `document.documentElement` at either width. Both the
throwaway console and the fixture server were stopped by pid (environ/cmdline-verified) before this
handoff was written; `ss -ltnp` confirms 8809/8810/8909 are clear.

## 6. Left for merge

Nothing GPU-related, no shared unit touched, no other row's files touched. The one thing worth a
second pair of eyes is decision 1 above (anchor-section vs. a route for "Create a tool") since nothing
in the row text rules either reading out explicitly — I read the missing path as the tell.

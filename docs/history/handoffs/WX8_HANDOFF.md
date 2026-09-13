# WX8 Handoff — FreeWeight's Overview, Goals, Adapters and the prompt editor

**Row:** WX8 (`docs/roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12 · **Model:** Claude
Fable 5.1 · **Kickoff:**
`history/prompts/wx8-freeweight-overview-goals-adapters-prompt-page.prompt.md` · **Ships:**
unreleased, no version bump (`wr-gym` stays `1.0.0` prepared) · **Branch:**
`row/wx8-freeweight-overview` in `~/ai/worktrees/weightroom-wx8`, **not merged**. WeightRoom only;
nothing in FreeWeight was touched (its WX7 API is what this consumes).

## 1. What shipped

| Where | What |
|---|---|
| `web/templates/fw_overview.html` (new) | FreeWeight's Overview: the dashboard's cards and filters, the Start-a-run form, the heatmap ↔ matrix toggle, the unit's figures, controls, kv list, primary table and live log |
| `web/templates/fw_dashboard.html` | **Deleted.** Its every assertion now runs against the Overview |
| `web/routes/freeweight.py` | `overview()` (the page), `dashboard_page()` (a 303 to `/apps/freeweight`, query preserved), `draft_from_page()`, `_adapters()`; `_runs()` lost the Start form's three reads |
| `web/routes/apps.py` | `app_page` dispatches FreeWeight to `overview()` — three lines, see §3.1 |
| `web/rendering.py` | `("freeweight", "Dashboard")` removed from `_APP_PAGES` and `_PAGE_HREF` |
| `services/freeweight_pages.py` | `heatmap_option()` — the ECharts option, column-normalised |
| `services/freeweight_actions.py` | `draft_manifest()` over `POST /adapters/{name}/draft` |
| `domain/audit.py` | `freeweight.adapter_draft` |
| `web/templates/fw_adapters.html` | *Drafts* and *Without a manifest* rewritten, a Draft form per unmanifested artifact, `app_page_header` |
| `web/templates/fw_goals.html` | Three sections — Results / Set up a run / Runs — and `app_page_header` |
| `web/templates/fw_adapter.html`, `fw_runs.html`, `fw_system.html` | `app_page_header`; the Start form replaced by a link; the dead Dashboard link |
| `web/templates/prompt.html`, `web/routes/prompts.py` | Named `version` / `change_reason` / `template` inputs, `_named_fields()`, `_patched()` |
| `tests/fixtures/freeweight/dashboard.json` | Re-recorded (§4) |

### 1.1 Gate line

`~/ai/worktrees/weightroom-wx8/.venv/bin/python` (CPython **3.14.4**): `ruff format --check .`
242 files · `ruff check .` clean · `mypy src tests` 235 files clean · `lint-imports` 5 contracts
kept · `pytest -q` **2 020 passed, 3 skipped, 12 deselected** in 182 s. `git status --short`
clean.

## 2. Decisions to review before merge

1. **The Dashboard's route redirects; it was not deleted.** The row says "the Dashboard entry
   goes". The menu entry and the template did; `GET /apps/freeweight/dashboard` answers `303` to
   `/apps/freeweight` carrying its query string, so a bookmark or an old link still lands on the
   filters it named. Say so if you would rather it 404.
2. **The heatmap's colour is a position within one suite, not a value.** A column is one suite's
   headline metric in its own unit — `tokens/s` beside a `ratio` — so each column is min-maxed on
   its own and `higher_is_better` decides which end is best; a column whose cells all read the
   same is all *best*, which is true of a single measured model. The alternative (one scale over
   every unit) paints the fast model dark and calls the accurate one pale. **The table under the
   chart is the page** — every real figure, its unit and its run link — and no figure is baked
   into the drawing.
3. **ECharts is asked for per render, not per page.** `mirrorwall={"echarts": chart is not None}`:
   the tab's landing page does not pull 1.1 MB when FreeWeight is stopped, when the scope is
   empty, or when every headline metric is `unsupported`.
4. **A chart row is labelled by the provider-side name** (`smollm2:135m`), falling back to the
   whole canonical ID the moment two models would share one label — an ECharts category that named
   two subjects would draw both their cells in one row. The hover carries the full identity either
   way. Same rule as WX7's `display_name`, applied to a chart axis rather than a table.
5. **The Start form is gated on FreeWeight being reachable, not on the dashboard read.** A
   refused filter (`MODEL_NOT_FOUND`) says nothing about whether a run can be started, and the
   run is a job rather than a dashboard call. **The Start form's refusal renders the Overview.** `POST /apps/freeweight/runs` is unchanged,
   but its refusal path now re-renders the page the form is on. The Runs page keeps a link
   (`/apps/freeweight#start`) and no longer reads `GET /adapters` at all.
6. **The draft form asks for the base model's name and nothing else.** ADR-0145 makes it required;
   `declared_capabilities` and `notes` are left to the reviewer editing the file, which is where
   the classification is set anyway. A blank name is refused by the console before FreeWeight is
   asked (`FreeWeightFormInvalid`), and that refusal is still one audit row.
7. **`freeweight.adapter_draft` is audited and not security-relevant.** The draft registers
   nothing — the `.manifest.draft.json` suffix is the enforcement — so writing one cannot
   misdirect a measurement. The row records the base the operator claimed, which is the only
   assertion in it.
8. **The prompt editor's named fields beat the JSON box, and blank means "not given".** The three
   inputs are patched into the posted record server-side (`_patched`), then the application's own
   loader validates it, so the invariant "a record the editor accepts is one the application will
   load" is untouched. Clearing a key is still done in the box. A refusal comes back with the
   patched record in the box and the typed values in the inputs.
9. **Goals is regrouped in the operator's order** — Results / Set up a run / Runs — which put
   *Drafts in progress* (the wizard's unfinished work) below the four ways to make a goal rather
   than above them, where it had been. Calibration and reports stay on a goal's own page; the
   *Runs* section says so rather than pulling them here (the row says nothing moves between
   routes).

## 3. What the row text got wrong

1. **There is no `_PAGE_HREF` override to make.** FreeWeight's Overview is `/apps/{app}` like
   every other application's, and that route is declared in `routes/apps.py` **before** the
   FreeWeight router is included — so a `/apps/freeweight` route in `routes/freeweight.py` would
   never match. `app_page` dispatches instead (`if name == "freeweight": …`), which is why
   `routes/apps.py` is in this row's diff at all. `_PAGE_HREF` only lost the Dashboard row.
2. **`fw_models.html` has no heatmap**, so "the same toggle on `fw_models.html`" could not be
   done and was not. The heatmap and the matrix are both views of `GET /dashboard`, which only
   this page reads; the Models page is a listing of model identities. Nothing was added to it.
3. **`unmanifested` carries full paths, not names.** `GET /adapters` answers
   `["/home/jpk/ai/models/adapters/llm/foo.gguf", …]` and the draft endpoint names the artifact by
   its *stem*. The template derives it (basename, `.gguf` removed) and shows the basename with the
   path as its title.

## 4. The fixture

`tests/fixtures/freeweight/dashboard.json` was re-recorded as row WX7 asked, from a FreeWeight at
`60be9cd` (WX7's API) under `FakeProvider` — its own XDG tree and its own SQLite file in the
session scratchpad, no GPU, no network, nothing of the operator's touched. Two suites were run over
the one fake model (`native.echo`, `native.performance`), which gives the recording what the old
one could not have: a `tests_matrix` (7 tests), a second heatmap column, and a headline metric that
reads **`"unsupported"`** rather than a number — the string form of ADR-0016's sentinel, which is
what proves the chart draws nothing there instead of a zero. The recording script is in the
session scratchpad (`wx8/record_dashboard.py`); it is 60 lines of `TestClient` and would be worth
keeping in `FreeWeight/scripts/` if this needs doing a third time.

The run IDs changed, so `test_freeweight_dashboard_system.py`'s `RUN` constant moved with it.
`mock_api` in `test_freeweight_pages.py` now records `dashboard` as well, because a refused start
renders the Overview.

## 5. Screenshots

`/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/wx8/shots/` —
`{overview,overview-matrix,goals,adapters,runs,prompt}-{1440,412}-{light,dark}.png`.
**`document.scrollWidth == clientWidth` on every one.** Taken against a throwaway console on
`:8779` with its own XDG tree; the *overview*, *goals*, *adapters* and *prompt* shots read the
operator's live FreeWeight 1.2.1 over HTTP (GET only), and *overview-matrix* reads the throwaway
FreeWeight of §4 on `:18765`, because 1.2.1 answers no `tests_matrix`.

Four layout defects were found by looking and fixed:

1. Two bare radios above their labels read as neither a group nor a pair. The switch now wraps each
   radio in its own `<label>` and hides the other section with `:has()` on the container, rather
   than the sibling-combinator trick that forced both inputs to the top. A browser without `:has()`
   shows **both** sections — complete, not broken.
2. A canonical ID in the first column of a seven-column dense table wrapped to one character per
   line. `white-space: nowrap` on that column; the table scrolls in its own `.table-scroll`, and
   the page still does not.
3. The chart's y axis was two thirds of the drawing — full canonical IDs. Hence §2.4.
4. The prompt editor's `version` field is 220 px wide and its hint is two sentences, so the hint
   wrapped into a column four words wide (row WX7's `.field`-as-flex-item lesson, again). The three
   named fields are `kit-wide` and the version box is capped at `12em`.

One thing was left as it is: at 412 px the heatmap is 320 px of chart whose axis labels take most
of the width, and a phone still downloads ECharts to draw it. The table under it is the content, so
this costs legibility nowhere — but if the operator would rather a phone skipped the drawing
entirely, that is a media query and a second look at the `echarts` flag, not a redesign.

One more was fixed from the dark-theme shot: the ECharts `splitArea` shading painted *unmeasured*
squares as convincingly as measured ones. It is off; an empty cell is now the page's own ground.

## 6. Tests

`tests/integration/test_freeweight_wx8.py` (16): the redirect with its query, the merged page, a
refused start landing there, both views rendered with one radio pair, a skip reason and an empty
cell, a FreeWeight with no `tests_matrix`, two injection-corpus sweeps, the per-column scaling and
the `unsupported` cell, ECharts asked for only when there is a drawing, the short-label collision
rule, Goals' three sections with every form still posting where it did, the manifest paragraph and
the per-artifact Draft form, a draft written/audited/shown with its rename, a blank base refused
before FreeWeight is asked, and FreeWeight's own `DRAFT_REFUSED` on the page.
`tests/integration/test_prompts.py` (+3): the named fields patched in, a blank one leaving the
record's value, a refusal keeping what was typed and writing nothing.
`tests/security/test_audit_routes.py` (+1): the registry row for
`POST /apps/freeweight/adapters/{adapter}/draft`.
`tests/integration/test_freeweight_dashboard_system.py`: retargeted from `/dashboard` to the
Overview.

## 7. Left for someone else

* **No GPU, no unit, no run.** The Start form was exercised through its refusal path only; nothing
  here enqueued a `freeweight_suite_run`.
* **The draft action has never written a real draft.** The operator's directory holds three
  unmanifested artifacts (`qwen2.5-1.5b-instruct-{damaged,pirate,verbose}.gguf`) and the form is
  live for them, but a console pressing it writes into the operator's adapter directory — outside
  this row's remit. Worth one press at the arc's live gate: the refusal path (a second draft) is
  the interesting one.
* **`tests_matrix` reaches the operator's console only when their FreeWeight carries WX7.** Until
  then the Matrix view is its empty state, which says so.

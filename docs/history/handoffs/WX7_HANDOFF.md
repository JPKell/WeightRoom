# WX7 Handoff — FreeWeight API additions and the Models, Runs, Compare, Machines pages

**Row:** WX7 (`docs/roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12 · **Model:** Claude
Opus 5 · **Kickoff:**
`history/prompts/wx7-freeweight-api-additions-and-the-models-runs-compare-machines-pages.prompt.md`
· **Ships:** unreleased, no version bump (`freeweight` stays `1.2.1`, `wr-gym` stays `1.0.0`
prepared) · **Branches:** `row/wx7-freeweight-api` and `row/wx7-freeweight-pages`, neither merged.

## 1. What shipped

| Repository | Commit | What |
|---|---|---|
| FreeWeight (`~/ai/worktrees/freeweight-wx7`) | `cc05f1a` | Six additive API surfaces (§2), one migration, ADR-0145's write, `docs/openapi.json` regenerated, docs mirrored byte-identical |
| WeightRoom (`~/ai/worktrees/weightroom-wx7`) | see §1.1 | The four pages that consume them, ADR-0145, `api.md`/`spec.md`/`data-model.md` (canonical) |

Nothing pushed, tagged or published. `git status --short` is clean in both worktrees.

### 1.1 Gate lines

* **FreeWeight**, `~/ai/worktrees/freeweight-wx7/.venv/bin/python` (CPython **3.14.4**):
  `ruff format --check .` 359 files · `ruff check .` clean · `mypy src tests` 328 files clean ·
  `lint-imports` 4 contracts kept · `pytest -q` **2 790 passed, 30 skipped, 31 deselected** —
  plus **4 pre-existing failures** in `tests/security/test_security_checklist.py`
  (`TestModelOutputRendersInert`), which fail identically on the branch point `bb1d56a` with the
  row's work stashed. Cause: the test asserts `"49" not in html` to prove a Jinja expression was
  not evaluated, and an asset cache-buster hash in the shell currently contains `49`
  (`…fc68607c5449`). Not this row's, not fixed by it; worth a one-line fix (assert on the
  rendered `{{ 7 * 7 }}` in context, not on the digits anywhere in the document).
* **WeightRoom**, `~/ai/worktrees/weightroom-wx7/.venv/bin/python` (CPython **3.14.4**):
  `ruff format --check .` 241 files · `ruff check .` clean · `mypy src tests` 234 files clean ·
  `lint-imports` 5 contracts kept · `pytest -q` **1 976 passed, 3 skipped, 12 deselected**.

## 2. The endpoints and the migration

| Surface | Shape |
|---|---|
| `GET /models` → `display_name` | `provider_model_name`, or `canonical_id` where two or more **enabled** models share that name — for every row carrying the name, disabled ones included. `services/models.display_names(rows)` is pure and computed once over the whole list; `display_names_of(database)` is the one-query form the detail route uses so `GET /models/{ref}` answers the list's name rather than a second rule |
| `GET /models?min_parameters=&max_parameters=` | The latest descriptor's `parameter_count`, inclusive, **in parameters**. A model that reported no count is outside every bound, `min_parameters=0` included (ADR-0016) |
| `PATCH /api/v1/machines/{id}` + `machines.nickname` | Migration `0011_machines_can_be_nicknamed` — one nullable column, no backfill, no server default, not in the profile upsert's `values` so re-profiling cannot clear it. Body `{"nickname": …}`, `null` or blank clears. Path is the **exact ULID**, never a prefix. `nickname` and `display_name` (nickname → hostname → ULID) in every machine body |
| `GET /dashboard` → `tests_matrix` | `{models, tests, cells:[{model, test, status, skip_reason, run_id}]}`, sparse, over exactly the runs the heatmap draws from (one `run_tests` query scoped to those run IDs). `TestsMatrix` is a new frozen dataclass on `Dashboard` |
| `GET /api/v1/results/context-fit` | `{items:[{model, runtime_profile_hash, machine_fingerprint, max_successful_context_tokens, capped_by_configuration, observed_mb_per_1k_context, run_id, measured_at}]}` — the latest `native.memory_kv` reading per triple, one `query_results` call folded, never averaged. This is what row WX9 reads |
| `POST /api/v1/adapters/{name}/draft` | Writes `<name>.manifest.draft.json`. `409 DRAFT_REFUSED` (new code) for a name that is not one path segment, no such unmanifested artifact, an existing manifest or draft, or adapters off |

Declared in `spec.md` §7.1 — which also gained the two paths that were **already served and never
declared**, `GET /api/v1/adapters` and `GET /api/v1/dashboard`; `tests/contract/test_declared_surface.py`
only checks declared → served, so nobody had noticed.

## 3. Decisions to review before merge

1. **ADR-0145 — FreeWeight drafts a manifest.** The row text says the endpoint wraps
   "`cli/commands/adapters.py`'s draft". **There is no such command**: ADR-0061 rule 4 gives
   drafting to `loadcoach adapters scan`, and FreeWeight's directory reader states *"FreeWeight
   writes no drafts"*. So the endpoint is new behaviour reversing a documented decision, and it
   is closed with **ADR-0145** (`0145-freeweight-drafts-an-adapter-manifest-and-still-trusts-nothing.md`),
   accepted on the operator's WX-interview default ("a **Draft manifest** action … ADR-0061's
   manifest stays hand-reviewed"). If the operator wanted only a CLI, the route comes out and the
   service function stays. **ADR numbers 0143 and 0144 are reserved by the roadmap** for WX12 and
   WX13, which is why this one is 0145.
2. **The draft's `data_classification` is `confidential`.** ADR-0065 gives the field no default so
   a person chooses; a draft must write something, so it writes the most restrictive value and
   says in `notes` that the reviewer sets it. The alternative — omitting it and writing a draft
   that cannot validate — was rejected.
3. **`display_name`'s collision rule counts only enabled models**, and then applies to *every* row
   carrying the name. The operator's own list has a real case: two `hk:latest` with different
   digests, both enabled, so both show their canonical ID.
4. **A separated metric is never charted on Compare.** FreeWeight marks a metric `mergeable:false`
   when its cells sit in groups that must not be read against each other; a bar chart is exactly
   that reading, so those metrics are listed unticked and disabled with their reason in the table
   beside them. This is a judgement the operator may want louder (a visible refusal rather than a
   disabled checkbox).
5. **`AdaptersDisabled` is translated to `DRAFT_REFUSED` in the draft route.** Its own code is
   `CONFIGURATION_ERROR`, which the suite answers `500`; an operator asking to draft with adapters
   off has made a request the route refuses, not found a fault in the server. The service still
   raises the shared error.
6. **The Models page reads the list twice when it is filtered** — once filtered, once not, for the
   three selects' vocabulary. A select narrowed to what the filtered list holds is a filter that
   cannot be undone. Unfiltered pages still make one call.
7. **The parameter filter is typed in billions and sent in parameters.** The conversion is the
   console's, in `web/routes/freeweight._parameters`, so FreeWeight never learns a second unit. A
   bound that is not a number is refused before FreeWeight is asked.
8. **`freeweight.machine_nickname` is audited and *not* security-relevant.** A nickname identifies
   nothing; the fingerprint still carries every measurement.

## 4. What the row text got wrong, and what is left

* **The manifest draft has no CLI to wrap** — see §3.1.
* **`tests/fixtures/freeweight/dashboard.json` was not re-recorded** with `tests_matrix`. The
  recordings are the operator's own FreeWeight answering, and it runs 1.2.1, which does not emit
  the key; inventing a matrix would be a recording of nothing. Nothing in WeightRoom reads
  `tests_matrix` until **WX8**, which builds the heatmap ↔ matrix toggle and should re-record
  that fixture from a FreeWeight carrying this row's commit. `models.json`, `model.json`,
  `machines.json` and `machine.json` **were** updated with `display_name` / `nickname`, computed
  by this row's own rule from the recorded rows.
* **`FreeWeight/scripts/sync_docs.py` cannot run from a worktree**: it resolves the canonical tree
  as `<repo>/../WeightRoom/docs`, which for `~/ai/worktrees/freeweight-wx7` is
  `~/ai/worktrees/WeightRoom/docs` and does not exist. The mirror was made with `cp` + `cmp`,
  which is what `render()` does; run the script itself after merge.
* **No GPU, no unit, no run.** `native.memory_kv` was never executed here; the context-fit fold is
  covered by an end-to-end test against the fake provider and by the operator's two real
  `max_successful_context_tokens` rows only through their shape. **WX14 should check
  `/results/context-fit` against the operator's real database once FreeWeight carries this
  commit** — it is the row's one figure nothing local can prove.

## 5. Screenshots

`/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/wx7/shots/` —
`{models,runs,compare,machines,machine}-{1440,412}-{light,dark}.png`, 20 files, taken against a
throwaway console on `:8779` with its own XDG tree, reading the operator's live applications over
HTTP (GET only). **`document.scrollWidth == clientWidth` on all twenty.**

Two layout defects this row introduced were found and fixed by looking:

1. A `<select>` holding canonical IDs has a 747 px option, and `.field` is a flex item whose
   default `min-width: auto` refuses to shrink — the Runs page scrolled 364 px sideways at 412 px.
   Fixed in `_fw.html`'s new `filter_styles()` macro (`.filter-bar .field { min-width: 0 }`,
   `.filter-bar select, .filter-bar input { max-width: 100% }`), used by Models, Runs and Compare.
   Kept out of `weightroom-shell.css` because only FreeWeight's bars carry options that long.
2. A `.field` is as wide as its widest child, and a `field-hint` is a sentence: the parameter
   range's hint made its field three times the width of the two inputs. `.filter-bar .field-hint
   { max-width: 34ch }` in the same macro.

The live FreeWeight the screenshots read is **1.2.1**, before this row's commit, so `display_name`
and `nickname` render their fallbacks (canonical ID, hostname) there. The rendering of the real
values is covered by `tests/integration/test_freeweight_wx7.py`, against fixtures that carry them.

## 6. Tests added

* FreeWeight: `tests/unit/test_display_names.py` (5), `tests/unit/test_adapter_draft.py` (10),
  `tests/e2e/test_wx7_endpoints.py` (13, over HTTP against the fake provider).
* WeightRoom: `tests/integration/test_freeweight_wx7.py` (17) — the filter bar's conversion and
  its two-call vocabulary, the collision shown by canonical ID, the Runs selects, the Compare
  picker joining its ticks into one subject list, a mergeable metric drawn and a separated one
  never drawn, a metric with no value drawing nothing rather than zeroes, the nickname form's
  `PATCH`/audit/refusal paths, and `app_page_header` on all five pages. Plus the audit-route
  registry row for `POST /apps/freeweight/machines/{machine_id}/nickname`
  (`tests/security/test_audit_routes.py`).

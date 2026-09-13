# WY8 Handoff — model tables name models, not identities

**Row:** WY8 (`roadmap/wy-console-polish-work.md` §3) · **Ran:** 2026-09-13, unattended ·
**Model:** Claude Sonnet 5 · medium · **Kickoff:**
`history/prompts/wy8-model-tables.prompt.md`; wave 2.

## 1. What shipped

**Repository:** WeightRoom, worktree `~/ai/worktrees/weightroom-wy8`, branch
`row/wy8-model-tables`, from WY1's gate A commit `ebc659e857c92b6a281dc66a267467be6013ded1`.
Nothing merged, pushed or tagged (branch left for WY10, per the standing rule and the W-arc
version hold).

| File | Change |
|---|---|
| `src/weightroom/web/rendering.py` | New `canonical_name` filter — the only place a canonical ID's name is recovered from ADR-0024's grammar |
| `src/weightroom/web/templates/_fw.html` | New `model_name(canonical_id, adapter=none)` macro (Results/Evidence). `model_link` untouched |
| `src/weightroom/web/templates/_lc.html` | New `model_cell(model_ref, name, canonical_id, limit=30)` macro (LoadCoach Models). `model_link` untouched |
| `fw_models.html` | Canonical ID column removed; page bar (Docs only — Runs/Provider were left-menu duplicates) |
| `fw_results.html` | Model column now a name via `model_name`; Machine and Runtime profile head entries carry `"hidden": true`; page bar (Compare, Machines — Evidence was a duplicate) |
| `fw_evidence.html` | Subject column now a name (+ adapter) via `model_name`; same two columns hidden; page bar (LoadCoach's import — Results was a duplicate) |
| `lc_models.html` | Name cell now `model_cell`, truncated at 30; page bar (Docs — Reliability/Providers were duplicates) |
| `tests/unit/test_rendering.py` | New — `canonical_name`: plain name, a name containing `/`, an `unknown` digest, an unparseable value, `None` |
| `tests/integration/test_freeweight_pages.py` | New: Models page has no `>Canonical ID<` header |
| `tests/integration/test_freeweight_results_evidence.py` | New: Results/Evidence name the model, not the ID; two `skipif`-guarded tests for the `data-default-hidden` markup |
| `tests/integration/test_loadcoach_pages.py` | New: a 41-character name renders 29 chars + `…`, full value in `title`, on both lines |
| `CHANGELOG.md` | `[Unreleased] / Changed (row WY8)`, one block at the top |

**Gate, interpreter named:** WeightRoomGym on this branch, `.venv` **Python 3.14.4** —
`ruff format --check .` (245 files), `ruff check .`, `mypy src tests` (238 files), `lint-imports`
(5 contracts kept), `pytest` → **2057 passed, 5 skipped** (2 of the 5 are this row's own
WY5-dependent skips below; the other 3 predate this row), 12 deselected; `pytest --cov` **91%**
total, against the 85% floor. `git status --short` is clean except the files above.

## 2. What the kickoff got wrong

**`baseaicore.ModelIdentity` has no parse method.** Decision 1 says a canonical ID's name should
be "parsed with BaseAiCore's `ModelIdentity` (never a hand-written split)". `ModelIdentity` builds
a canonical ID (`provider_kind/name@digest_short`) but its own docstring calls the ID lossy and
says it is "never parsed back into its parts" — there is no `ModelIdentity.parse` or equivalent
classmethod in baseaicore 0.4.2, and adding one is a domain-package change outside this row's file
ownership (§4) and outside a medium-effort console row's scope. `canonical_name` in
`rendering.py` recovers the name from the format's fixed grammar directly instead (split once on
the first `/`, once on the last `@`) — the same grammar `freeweight_pages.heatmap_option`'s
`rsplit`/`split` pair and `test_loadcoach_pages.py`'s `_bound_record` helper already rely on, now
in one place instead of three. **Follow-up worth scheduling:** add `ModelIdentity.from_canonical_id`
(or similar) to BaseAiCore and point all three call sites at it, so the grammar lives in the
package that owns the format rather than being re-derived by three unrelated readers.

**A page's own left-menu entry must not appear in its own page bar.** I first wrote Results'
`page_nav` with a `{"label": "Results", "href": "/apps/freeweight/results", "current": true}`
self-entry, reasoning from the macro docstring's "Queue · History · New job" example. FreeWeight's
own left menu already lists Results (`_APP_PAGES["freeweight"]`), so that self-entry duplicated it
and failed `tests/integration/test_page_nav.py::test_no_page_bar_link_repeats_the_left_menu` — the
one gate this row could have gotten wrong silently, since it only runs over every *rendered* page,
not per-template. Fixed by dropping the self-entry; Results' bar is `Compare · Machines` only.
Models, Evidence and LoadCoach's Models needed no self-entry for the same reason and never had one.

## 3. The `data-default-hidden` markup — proven, but skipped for now

Row WY5's `table()` macro (in `~/ai/worktrees/mirrorwall-wy5`, unmerged) is what turns a column's
`"hidden": true` head entry into `data-default-hidden="true"` on the `<th>`. The MirrorWall this
row installed from (`~/ai/suite/py/MirrorWall`, main, `707c1d0`) predates it, so today every column
still renders — expected, per roadmap §2.2. `test_results_hides_runtime_profile_and_machine_by_default`
and `test_evidence_hides_runtime_profile_and_machine_by_default` probe
`mirrorwall.__file__`'s own `components.html` for the string `data-default-hidden` and
`pytest.mark.skipif` themselves when it is absent, rather than asserting against a dependency that
is not there yet (skipped now: 2, confirmed by reading `mirrorwall-wy5`'s `components.html` that
`hidden` → `data-default-hidden="true"` is the exact contract). **WY10 will see both tests actually
execute** the moment it installs a MirrorWall with WY5 merged in — no test edit needed then, only
a re-run.

## 4. Decisions made without asking

* **FreeWeight Models' Order select keeps its two canonical-ID sort options.** Decision 4 said to
  drop them only if the API's sort does not need them; `GET /models?sort=-canonical_id` is real and
  is exercised by `test_the_models_page_reads_freeweight_and_offers_refresh_and_the_switch`, so I
  left them.
* **`page_nav` classification for the one link that fit neither category:** Evidence's "LoadCoach's
  import" is a cross-application reference, not a sibling view of Evidence's own subject and not a
  left-menu duplicate. I put it under `actions` (styled the same as a `JSON`/`Docs` link) rather
  than `links`, since it names a different application's page, not a subsection of this one.
* **`fw_compare.html` is untouched.** `results/compare` renders a separate template (not
  `fw_results.html`), and §4 does not list it under WY8 — its page bar is WY1's sweep, not this
  row's.

## 5. Screenshots

All four templates, both themes, both widths, from the **live** FreeWeight (`127.0.0.1:8765`, no
token needed) and the **live** LoadCoach (`127.0.0.1:8766`, via the operator's existing
`api_key_file` — a read-only reference to it, nothing written) — real data throughout, not
fixtures; the kickoff's fixture fallback was not needed. Throwaway console `8813`/`8814`, XDG
under this session's scratchpad, killed by its own tracked pid when done.

`/tmp/claude-1000/-home-jpk-ai-suite/69410a0f-7745-4a4a-91ad-1e4e3414f601/scratchpad/wy8/shots/`:
`{fw_models,fw_results,fw_evidence,lc_models}_{1440,412}_{light,dark}.png` (16 files).

Visually confirmed: `fw_models` has no Canonical ID column; `fw_results`/`fw_evidence` show
provider names (e.g. `smollm2:135m`, not the full `ollama/smollm2:135m@sha256:…`) with every
column still visible (WY5 not installed, as expected); `lc_models` truncates a live 45-character
name (`fredrezones55/Qwen3.6-35B-A38…` over `ollama/fredrezones55/Qwen3.6-…`) on both lines at
412 px — the truncation the operator asked for is real on today's live registry, not only in the
synthetic 41-character test.

## 6. Out of scope, confirmed untouched

`table.js` (WY5), the model detail pages (`fw_model.html`'s own template — not in §4), and every
file §4 gives to another row.

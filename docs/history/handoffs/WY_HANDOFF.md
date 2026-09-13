# WY Handoff — the console polish arc, merged and verified

**Row:** WY10 in [`roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md) ·
**Ran:** 2026-09-13 · **Model:** Opus 5 · high · **Kickoff:**
[`history/prompts/wy10-merge-and-verify.prompt.md`](../prompts/wy10-merge-and-verify.prompt.md).
Row handoffs: [WY1](WY1_HANDOFF.md) · [WY2](WY2_HANDOFF.md) · [WY3](WY3_HANDOFF.md) ·
[WY4](WY4_HANDOFF.md) · [WY5](WY5_HANDOFF.md) · [WY6](WY6_HANDOFF.md) · [WY7](WY7_HANDOFF.md) ·
[WY8](WY8_HANDOFF.md) · [WY9](WY9_HANDOFF.md).

Nothing was pushed, tagged, published or version-bumped. Every change is under `## [Unreleased]`.

## 1. What landed

`git merge --no-ff`, one merge commit per branch, in the kickoff's order. Branches are kept.

| Repository | Merge commit | Branch (head) | Row |
|---|---|---|---|
| FreeWeight | `6898f92` | `row/wy6-health-under-load` (`a502bdb`) | WY6 — health bounded and off the event loop |
| MirrorWall | `411274c` | `row/wy5-table-sort` (`677b580`) | WY5 — table sort, resize, default-hidden columns |
| MirrorWall | `7ea1ae5` | `row/wy4-chart-fill` (`9d56bd9`) | WY4 — value-mapped chart fill, unit formatter |
| WeightRoom | `4188e32` | `row/wy1-shell-nav` (`8128ec1`) | WY1 — shell navigation, page bar, catalog removed |
| WeightRoom | `35e2d10` | `row/wy4-telemetry` (`3d3de80`) | WY4 — telemetry on one page |
| WeightRoom | `56d8404` | `row/wy2-logs-settings` (`5ca6104`) | WY2 — logs grid, settings columns |
| WeightRoom | `d9c2ae5` | `row/wy3-overview` (`9924f50`) | WY3 — Overview figures |
| WeightRoom | `61ffe1e` | `row/wy7-chat-history` (`ddb0f41`) | WY7 — chat history page |
| WeightRoom | `9b1c755` | `row/wy8-model-tables` (`3482ca8`) | WY8 — model tables by name |
| WeightRoom | `094ac11` | `row/wy9-database-subpages` (`8f6d366`) | WY9 — database subpages |
| WeightRoom | `33cd84c` | — | WY10 — `app_page_header` caller slot removed (§5) |
| WeightRoom | the commit adding this file | — | WY10 — this handoff, WY5/WY6 handoffs, roadmap status |

No `row/wy6-alert-probe` branch exists: WY6 found the cause in ModelRack and fixed it in FreeWeight.

## 2. Preconditions

* WeightRoom, FreeWeight and MirrorWall `main` were clean at the start. WeightRoom `main` was at
  `4dab956`, with the operator's eight template edits committed as `f6ffb80` (roadmap §0).
  `stash@{0}` is untouched.
* Every wave-2 branch contains WY1's gate A commit `ebc659e`. WY4 branched from `f6ffb80`, as wave 1
  should.
* **Five worktree venvs were not installing the suite from `~/ai/suite`** and were reinstalled with
  the roadmap §5 command before their gates counted:

  | Worktree | From PyPI before the reinstall |
  |---|---|
  | `weightroom-wy1` | baseaicore, setspec, weightsdb, sweatmeter, modelrack, loadledger |
  | `weightroom-wy4` | the same six (MirrorWall was the WY4 worktree, editable) |
  | `freeweight-wy6` | baseaicore, weightsdb, sweatmeter, modelrack |
  | `mirrorwall-wy4`, `mirrorwall-wy5` | baseaicore, setspec |

  So the reported gates of WY1, WY4, WY5 and WY6 ran against PyPI copies. Their re-runs below are the
  ones that count. WY2, WY3, WY7, WY8 and WY9 were already correct.
* **Two production venvs, reported and not reinstalled** (kickoff §0):
  * `~/ai/suite/WeightRoom/.venv` (runs `weightroom.service`): `mirrorwall` is editable from
    `~/ai/suite/py/MirrorWall/src` (§2 item 7 holds), but baseaicore, setspec, weightsdb, sweatmeter,
    modelrack and loadledger come from PyPI.
  * `~/ai/suite/FreeWeight/.venv` (runs `freeweight.service`): baseaicore, weightsdb, **mirrorwall**
    and modelrack come from PyPI; setspec and sweatmeter are editable. FreeWeight's pages therefore
    render with PyPI MirrorWall, not `main`.
* The gates on `main` ran in scratch venvs that install every suite package editable from
  `~/ai/suite/py` plus the repository itself, so the production venvs were never touched. MirrorWall's
  own `~/ai/suite/py/MirrorWall/.venv` was already correct and was used as is.

## 3. Gates

Every run: `ruff format --check .`, `ruff check .`, `mypy src tests`, `lint-imports`, `pytest`
(markers excluded by `addopts`), all on **Python 3.14.4**. Formatting, lint, types and import contracts
were green in every run; the pytest line is quoted.

**Branches, re-run in their own worktrees before merging** (venvs from `~/ai/suite/py`, §2):

| Branch | Interpreter | pytest |
|---|---|---|
| FreeWeight `row/wy6-health-under-load` | `~/ai/worktrees/freeweight-wy6/.venv` | 2816 passed, 30 skipped, 31 deselected |
| MirrorWall `row/wy5-table-sort` | `~/ai/worktrees/mirrorwall-wy5/.venv` | 395 passed, 1 skipped, 3 deselected |
| MirrorWall `row/wy4-chart-fill` | `~/ai/worktrees/mirrorwall-wy4/.venv` | 389 passed, 1 skipped, 3 deselected |
| WeightRoom `row/wy1-shell-nav` | `~/ai/worktrees/weightroom-wy1/.venv` | 2024 passed, 3 skipped, 12 deselected |
| WeightRoom `row/wy4-telemetry` | `~/ai/worktrees/weightroom-wy4/.venv` (MirrorWall WY4 worktree) | 2066 passed, 3 skipped, 13 deselected |
| WeightRoom `row/wy2-logs-settings` | `~/ai/worktrees/weightroom-wy2/.venv` | 2052 passed, 3 skipped, 12 deselected |
| WeightRoom `row/wy3-overview` | `~/ai/worktrees/weightroom-wy3/.venv` | 2061 passed, 3 skipped, 13 deselected |
| WeightRoom `row/wy7-chat-history` | `~/ai/worktrees/weightroom-wy7/.venv` | 2053 passed, 3 skipped, 12 deselected |
| WeightRoom `row/wy8-model-tables` | `~/ai/worktrees/weightroom-wy8/.venv` | 2057 passed, 5 skipped, 12 deselected |
| WeightRoom `row/wy9-database-subpages` | `~/ai/worktrees/weightroom-wy9/.venv` | 2050 passed, 3 skipped, 12 deselected |

**On `main`, after each merge** (WeightRoom and FreeWeight in scratch venvs `wr-main` and `fw-main`
under the session scratchpad; MirrorWall in its own `~/ai/suite/py/MirrorWall/.venv`):

| After | pytest |
|---|---|
| FreeWeight WY6 (`6898f92`) | 2816 passed, 30 skipped, 31 deselected |
| MirrorWall WY5 + WY4 (`7ea1ae5`) | 400 passed, 3 deselected |
| WeightRoom WY1 (`4188e32`) | 2024 passed, 3 skipped, 12 deselected |
| WeightRoom WY4 (`35e2d10`) | 2047 passed, 3 skipped, 13 deselected |
| WeightRoom WY2 (`56d8404`) | 2051 passed, 3 skipped, 13 deselected |
| WeightRoom WY3 (`d9c2ae5`) | 2064 passed, 3 skipped, 14 deselected |
| WeightRoom WY7 (`61ffe1e`) | 2069 passed, 3 skipped, 14 deselected |
| WeightRoom WY8 (`9b1c755`) | 2080 passed, 3 skipped, 14 deselected |
| WeightRoom WY9 (`094ac11`) | 2082 passed, 3 skipped, 14 deselected |
| WeightRoom slot removal (`33cd84c`) | 2082 passed, 3 skipped, 14 deselected; then `-m performance` 14 passed (§5) |

WY4's count on `main` (2047) is below its branch's (2066) because WY1 deleted the catalog tests.
WY8's two `data-default-hidden` tests skip on its branch and run on `main` once WY5 is merged (5
skipped on the branch, 3 on `main`).

## 4. Merge conflicts and how each was resolved

Dry-run first in a detached scratch worktree, so `main` only ever saw merges whose conflicts were
known. Every conflict was textual; none was semantic.

| Merge | File | Resolution |
|---|---|---|
| MirrorWall WY4 after WY5 | `CHANGELOG.md` | Both `[Unreleased]` blocks kept, WY5's first |
| MirrorWall WY4 after WY5 | `static/ASSETS.sha256` | Auto-merged (different lines); both digests verified against the files |
| WeightRoom WY4 | `CHANGELOG.md` | Both blocks kept |
| WeightRoom WY4 | `docs/adr/README.md` | Both index rows kept, 0146 then 0147 |
| WeightRoom WY2, WY3, WY7, WY9 | `CHANGELOG.md` | Both blocks kept |
| WeightRoom WY8 | `CHANGELOG.md` | Both blocks kept |
| WeightRoom WY8 | `web/rendering.py` `__all__` | Both names kept (`docs_action` from WY1, `canonical_name` from WY8), in alphabetical order |

The expected WY1/WY9 collision on `tests/integration/test_page_nav.py` (WY9 §3) did not happen: the two
rows edited different lines, and WY9's exception is reviewed in §5. `db_curated.py` (WY9) and
`web/routes/apps.py` (WY3) were touched by no other row.

## 5. Work only this session could do

1. **`app_page_header`'s caller slot is deleted.** After the last merge three templates still called
   it with a caller:
   * `fw_runs.html` carried a whole link strip (*Models · Machines · Jobs · Docs*) that WY1's sweep
     missed. It is now `page_nav(links=[Machines], actions=[Jobs, Docs])`. *Models* was a left-menu
     duplicate; *Machines* follows WY8's Results bar; *Jobs* is a console page, so it is an action.
   * `fw_models.html` and `lc_models.html` put their *Refresh from provider* / *Scan for models*
     POST form in the caller. The form now sits under the header as `<form class="kit-actions">`,
     the pattern WY1 used for LoadCoach's queue controls.

   Then the slot left `_app_page.html`, its docstring sentence was rewritten, and
   `weightroom-shell.css` lost `.page-actions` (three rules) and
   `.app-page-intro:has(.app-page-actions) ~ .app-docs-link`, plus the comment that said the slot
   lasted until WY10. `tests/unit/test_page_kit_macros.py` no longer passes a caller and asserts that
   no `page-actions` bar renders. `grep -rn "call app_page_header"` returns nothing.
2. **The duplicate rule over the whole site.** WY9 added one exception to
   `test_no_page_bar_link_repeats_the_left_menu`: the page's own *selected* left-menu href. It is
   right — every database subpage selects the menu's single *Database* entry, which is Tables' URL —
   and it exempts exactly one href, so it was kept. The grep for `page-actions|kit-actions` in
   templates finds no link strip: the only `page-actions` was the slot, and the six remaining
   `kit-actions` blocks (`lc_job`, `_lc` model switch, `lc_providers`, `fw_run`,
   `lc_evidence_admin`, `lc_queue`) and every `<form class="kit-actions">` hold POST forms or submit
   buttons, never links. The live browser pass (§6) found no page whose bar repeats its left menu.
3. **§2.2 end to end** holds in a real browser on a fresh profile; see §6.
4. **No `/catalog`**: `grep -rn "/catalog" src tests docs/apps/weightroom` returns the ADR-0146 note in
   `api.md`, the catalog-removal test in `test_page_nav.py`, and three mentions of the file
   `services/catalog.py` (which survives for `set_enabled` and `model_refresh`, WY1 §4). `GET /catalog`
   and `GET /api/v1/catalog` answer 404 from the live throwaway console.
5. **Budgets:** `pytest -m performance tests/performance/test_budgets.py` on `main` after the slot removal, on this
   machine, `wr-main` venv (Python 3.14.4), run after the full gate so nothing shared the CPU:
   **14 passed**.

   | Budget | Measured | Limit |
   |---|---|---|
   | JS in total, heaviest page (`/telemetry/history`) | **102.0 KB** | 120 KB (ADR-0139) |
   | `table.js` (WY5) inside that total | 13.3 KB | — |
   | `charts.js` (WY4) inside that total | 6.2 KB | — |
   | ECharts, by name | 1095.6 KB | 1123.05 KB (ADR-0142) |
   | Shell stylesheet | **19.3 KB** | 32 KB |
   | Overview page, application running | **6.1 ms** | 300 ms |
   | Telemetry page over a day (4 980 rows) | **22.1 ms** | 50 ms |
   | Chat relay over the raw LoadCoach stream | 8.5 ms | 30 ms |
   | Docs render (66 KB) / search over 563 documents | 23.6 ms / 1.8 ms | 100 ms / 200 ms |
   | Table page, 100 rows | 3.0 ms | 150 ms |
   | Guarded write end to end | 52.8 ms | 2000 ms |

   The shell render and the WY3 three-application concurrency budget assert without printing a figure;
   both passed. The JS total rose from WY4's 95.2 KB to 102.0 KB because `table.js` doubled (WY5) and
   `/telemetry/history` loads both. The shell stylesheet fell from WY1's 20.1 KB to 19.3 KB with the
   slot's rules gone.
6. **Docs:** ADR-0146 and ADR-0147 are both in `docs/adr/README.md`. MirrorWall mirrors no ADRs. No
   row changed a MirrorWall or FreeWeight README or top-level doc. WeightRoom's root `README.md` changed at WY1, and its guide copy was hand-edited in the worktree because the sync script cannot run there (WY1 §5). On `main` `docs/scripts/sync_component_docs.py --check` exits 0, so the copy is what the script produces. `FreeWeight/scripts/sync_docs.py --check` exits 0 after the WY6 merge. Both checks also passed on `main` before any merge, so no drift was inherited.
7. **The production console uses MirrorWall `main`:** `~/ai/suite/WeightRoom/.venv` imports
   `mirrorwall` from `/home/jpk/ai/suite/py/MirrorWall/src/mirrorwall/__init__.py` (editable). Its
   other suite packages are PyPI copies (§2).

## 6. Live verification

### 6.1 Restarts

* **`freeweight.service` restarted at 08:20:24Z**, after the WY6 merge and FreeWeight's `main` gate.
  Before the restart, `GET 127.0.0.1:8765/api/v1/system/status` answered `active_run: null`,
  `queue_depth: 0`, and the production venv imported the merged code (`modelrack 0.8.0`,
  `PROVIDER_HEALTH_TIMEOUT_SECONDS = 0.5`). It came back in about 1 s with no error in its journal.
* **`weightroom.service` restarted at 08:46:50Z (pid 575143), and served `https://10.77.10.84:8769/login` with 200; its journal shows a clean startup. The production venv's MirrorWall is `main` (editable), its other suite packages PyPI (§2)**, after the slot-removal commit, so the console
  runs merged `main`.

### 6.2 WY6 in production

The console's own alert table (`~/.local/share/wr-gym/weightroom.sqlite3`, read-only) before and after
the FreeWeight restart:

* **Before:** FreeWeight `app_down` opened 11–12 times per hour through 2026-09-13 00:00–08:00, and
  at 08:02, 08:07, 08:12 and 08:18 in the last 20 minutes — every one `ReadTimeout: timed out`, about
  one every 5.3 minutes (the ModelRack 300 s cache TTL plus probe spacing).
* **After (08:20:24–08:53Z):** **no alert of any kind opened, and no alert history row was written** — no `app_down`, no other source. At the old rate, five or six FreeWeight `app_down` openings were due in those 32 minutes. The console itself was restarted at 08:46:50Z and probed again from startup; nothing opened after that either.
* A sampler read `/api/v1/health` every 30 s over the same window: 64 samples from 08:20:46 to 08:52:35, **all HTTP 200, none timed out**: 57 `ok` (0.15–0.32 s) and 7 `degraded` (0.76–0.94 s, provider check past its 0.5 s bound). The `degraded` answers
  fall exactly on the 5-minute cache expiries (08:20:46 cold start, then 08:25:49, 08:30:52, 08:35:55, 08:40:58, 08:46:01, 08:51:04)
  and each took under 1 s, where the old route took about 6 s. The next sample is `ok` again, because
  the background check warms the cache.

### 6.3 Browser pass

Playwright with system Chrome against a throwaway console on **8817** (trust 8818), own XDG tree under
the session scratchpad, open loopback, reading the live applications over GET. Its `config.toml` names
the four production executables and, by path only, the operator's LoadCoach and PromptCadence token
files. It ran the fully merged tree including the slot removal (a detached scratch worktree); `git diff
18f6a31 -- src tests docs` against `main` after the slot commit differs only in the order of two names
in `rendering.py`'s `__all__`, so the pass shows `main`.

* **75 screenshots**: `/`, `/telemetry/history`, `/logs`, `/settings`, `/chat`, `/chat/history`,
  `/docs`, FreeWeight Models, Runs, Results, Evidence and Database Tables, Query and Admin, LoadCoach
  Models (sorted on two columns, one column resized) and Queue, PromptCadence Trajectories and IdeaPress
  Projects, each at 1440 px and 412 px in light and dark; plus Results and Evidence with the hidden
  columns ticked, and zoomed probes of Results and LoadCoach Models.
* **Probed on every shot** (`report.json`): HTTP 200; no horizontal scroll at either width; at most one
  page bar and it is the first element; no bar `href` repeats the left menu; Chat in the masthead;
  no `/catalog` link. One console error only: a 404 on the Overview at 1440 px light (a static
  resource, not a page).
* **§2.2 end to end:** on a fresh profile, Results and Evidence render Machine and Runtime profile
  with `display: none`; ticking them in *Columns* shows them; after a reload they stay shown.
* **§2.3:** two header clicks on LoadCoach Models give `▲1` on Registry and `▼2` on Egress. A 57 px drag
  on the first column's handle works, but see L2 in §7: the table's other columns fall from 73–130 px
  to 61 px each, because the table switches to `table-layout: fixed` at its wrapper's width (1693 px
  → 1172 px).
* **Telemetry:** seven canvases, no SVG double, bars across the top, totals as values.
* **Degraded state seen:** FreeWeight Database Tables and Query show `SCHEMA_UNKNOWN` for revision
  0011 (§9).

## 7. The operator's request, item by item

Screenshots are in the WY10 session scratchpad,
`/tmp/claude-1000/-home-jpk-ai-suite/a574e04d-0651-4fa5-b50a-7974d523ee34/scratchpad/shots/`, named
`<page>_<1440|412>_<light|dark>.png` (75 files, with `report.json` holding each page's probe). They
were taken from a throwaway console on 8817 running the fully merged tree (§6).

| # | Request item | Verdict | Evidence |
|---|---|---|---|
| W1 | Chat back in the top bar and kept in the left menu | **Done** | `chat_in_masthead` true on all 72 page shots; Tools · Chat in every console menu (`overview_1440_light.png`) |
| W2 | No WeightRoom left-menu links on application pages | **Done** | `fw_models_1440_light.png`, `lc_models_1440_light.png`, `pc_trajectories_1440_dark.png`: the menu is the application's only |
| W3 | Overview shows LoadCoach Active / Oldest queued / Starving, PromptCadence Executing / Planning / Pending, FreeWeight summary | **Done** | `overview_1440_light.png`, `overview_412_dark.png`, live figures |
| W4 | Logs as 3 columns × 3 rows (level·date·time / app·version·pid / message·logger·id) | **Done** | `logs_1440_light.png` (live pane) |
| W5 | Settings: Value, Source, Applies right-aligned; Applies pills stacked at minimum width | **Done** | `settings_1440_light.png` |
| W6 | Chat history on its own page, a table whose rows open the chat; History in the bar; JSON and Delete on one line | **Done** (history table not seen with rows: the throwaway console has no conversations) | `chat_history_1440_light.png`; rows and the Delete line are in WY7's own shots |
| W7 | No WeightRoom links in the docs left menu | **Done** | `docs_1440_light.png` |
| W8 | Catalog removed: no page, no links, files deleted | **Done** | `GET /catalog` and `/api/v1/catalog` 404; `catalog_links` 0 on every shot; §5 item 4 grep |
| W9 | Telemetry: no SVG double | **Done** | 7 canvases, 0 SVG figures (`report.json`) |
| W10 | Telemetry: one page, every figure, tight, K/M/G | **Done** | `telemetry_1440_light.png`, `telemetry_412_dark.png` |
| W11 | RAM and VRAM totals as values, large current bars | **Done** | `13.6 G / 30 G`, `7.7 G / 15.9 G` beside the used figure; bars across the top |
| W12 | Shaded area under the line, green low to red high | **Done** | GPU power chart in `telemetry_1440_light.png` shows the blend (ADR-0147) |
| W13 | No explanatory text or headers on telemetry | **Done** | no heading, no intro |
| F1 | FreeWeight `app_down` alerts (`/api/v1/health` `ReadTimeout`) | **Done, observed in production** | §6: 4 FreeWeight `app_down` openings in the 20 minutes before the restart, none in the 30 minutes after |
| F2 | Models page without the canonical ID | **Done** | `fw_models_1440_light.png` |
| F3 | Sort arrows, 3-way, several columns, order number | **Done** | LoadCoach Models after two header clicks shows `▲1` and `▼2` (`report.json`) |
| F4 | Results by model name; runtime profile and machine hidden by default | **Done**, readability **partial** | Hidden on a fresh profile, shown once ticked, kept after reload (§6). Metric and Model cells still wrap per character: pre-existing `.shell-main .mono { overflow-wrap: anywhere; }`, same in WY8's pre-merge shot (`zoom_fw_results_1440_light.png`) |
| F5 | Evidence by name; runtime profile and machine hidden by default | **Done** | as F4 |
| F6 | Database links at the very top; Tables, Query, Admin as real pages | **Done** (content degraded, see §9) | `fw_db_tables_1440_light.png`, `fw_db_query_1440_light.png`, `fw_db_admin_1440_light.png` |
| L1 | LoadCoach model names cut at 30 characters | **Done** | `igorls/gemma-4-12B-it-heretic…` over its identity line |
| L2 | Resizable columns | **Partial — defect** | A drag works, but on a table wider than its wrapper the first stored width switches the table to `table-layout: fixed` at the wrapper's width, and every other column collapses to 61 px (1693 px table → 1172 px; `lc_models_fresh_1440_light.png` vs `lc_models_resized_1440_light.png`). See §9 |
| O1 | One modular page bar at the top of every page, no duplicates of the left menu | **Done** | `page_nav_first` true and `bar_repeats_side` empty on every shot; `test_page_nav.py` green; the caller slot is deleted (§5) |

## 8. What the plan got wrong (collected from every row)

* **The worktree venv recipe produced PyPI copies** in five of ten worktrees (§2), and the order of
  the original recipe failed outright for a WeightRoom worktree before MirrorWall was installed (WY4).
  The 2026-09-13 amendment to roadmap §5 came after wave 1 had built.
* **WY6's leading hypothesis was wrong.** The `app_down` alerts were not load on the event loop; they
  were ModelRack's GGUF header re-parse on metadata cache expiry, while FreeWeight was idle (WY6 §1).
* **The catalog survey was incomplete**: the OpenAPI snapshot, the `api.md` contract test, eight
  audit-route exercises, two drop-in upload routes and the root README all named it (WY1 §5).
* **`sync_component_docs.py` cannot run from a worktree** (`SUITE = DOCS.parent.parent`) (WY1 §5).
* **`charts.js` has a recorded digest** (`ASSETS.sha256`); a formatter "in the page's JS" could not
  serve chart axes (WY4 §4).
* **§2.1's "New conversation · History" example fails the duplicate rule**, because Chat stays in the
  left menu's Tools section on every console page (WY7). The chat bar ships *History* only.
* **A page's own left-menu entry cannot be a self-link in its bar** (WY8 §2), and the duplicate rule
  had to exclude the left menu's *selected* href, not the request path, for database subpages (WY9 §3).
* **`baseaicore.ModelIdentity` has no parse method**; WY8 recovers the name in `rendering.canonical_name`
  (WY8 §2).
* **File ownership had gaps**: `test_page_nav.py` (WY1's) was edited by WY9 as its kickoff instructed;
  `web/routes/apps.py` (WY3) and `services/db_curated.py` (WY9) belonged to no row. None conflicted.
* **WY1's sweep missed one strip**: `fw_runs.html` still called `app_page_header` with a link strip in
  its caller. WY10 converted it (§5).
* **The WY5 and WY6 reports did not reach WY10 verbatim**; their handoffs are rebuilt from commits,
  changelogs, code and the operator's session memory, and say so.

## 9. Left for the operator

1. **Push, tag and publish** nothing was done here: FreeWeight, MirrorWall and WeightRoom `main` are
   ahead of their remotes by the merge commits in §1 and the docs commit.
2. **The column resize defect (L2).** MirrorWall `table.js` switches a table to
   `table-layout: fixed` on the first stored width without freezing the other columns, so a wide
   table (LoadCoach Models) collapses every other column to about 61 px. The fix is to record every
   header's current `offsetWidth` and set the table's own width to their sum before switching layout,
   so the wrapper keeps scrolling. That is a MirrorWall asset change (digest, JS tests, browser loop),
   so it wants its own row rather than a merge session.
3. **FreeWeight's database pages are degraded in production.** FreeWeight's live schema is revision
   `0011`; WeightRoom 1.0.0 knows `0009` and `0010`, so Tables and Query show `SCHEMA_UNKNOWN`
   (Admin works). This predates the WY arc; WeightRoom's `known_revisions` needs the FreeWeight
   migration reviewed against the ADR-0124 guard before it is added.
4. **Results and Evidence still wrap Metric and Model per character** (F4): the shell's
   `.shell-main .mono { overflow-wrap: anywhere; }` lets auto table layout squeeze those columns to
   about 66 px. Pre-existing; a `white-space: nowrap` or a min-width on those cells would fix it.
5. **Production venvs (§2).** `~/ai/suite/WeightRoom/.venv` and `~/ai/suite/FreeWeight/.venv` install
   most suite packages from PyPI. FreeWeight's pages therefore run PyPI MirrorWall, not `main`.
   Reinstall them with the roadmap §5 command when convenient.
6. **WY6 follow-ups**: the ModelRack GGUF header re-parse on cache expiry, LoadCoach's unbounded
   `async def health`, and FreeWeight's other synchronous `async def` routes (WY6 §4).
7. **WY8 follow-up**: `baseaicore.ModelIdentity.from_canonical_id`, so `rendering.canonical_name` and
   its two sibling parsers use the package that owns the format.
8. **Decisions rows asked to have reviewed** and WY10 left as built: WY1 §4 (single-link bars with the
   current link, `catalog_entries` kept for `model_refresh`, recent projects only on Projects and New
   project); WY3 §6 (the three application groups stack rather than sit side by side);
   WY7 (no *New conversation* link, because Chat is in the left menu on every console page);
   WY9 §2.3 (`page_source` macro not adopted).
9. **`stash@{0}`** in WeightRoom is still the operator's.

## 10. Follow-ups decided with the operator and built the same day

After the arc closed, the operator was interviewed on every open item in §9 (2026-09-13). Decisions:

| §9 item | Decision | Done |
|---|---|---|
| 2 — column resize collapses a wide table | Fix now | MirrorWall `3a4ef62` |
| 3 — FreeWeight schema `0011` unknown | Review and add now | WeightRoom `9a6e137` (migration `0009`) |
| 4 — per-character wrap in table cells | Fix now in shell CSS | WeightRoom `9a6e137`, `ce25795` |
| 5 — production venvs on PyPI | Reinstall WeightRoom and FreeWeight; then LoadCoach too, restart if idle | venvs reinstalled, all suite packages editable from `~/ai/suite/py` |
| 6 — WY6 follow-ups | Build all three now | ModelRack `aa4c830`, LoadCoach `b37c966`, FreeWeight `86501fb` |
| 8 — WY3 Overview layout | Keep stacked | — |
| 8 — WY7 chat bar | Add *New conversation* | WeightRoom `9a6e137` |
| Row branches | Keep | — |
| Release hold | Keep: no version bumps, no tags | everything under `[Unreleased]` |

### 10.1 What changed

* **MirrorWall `table.js`** — before a table switches to `table-layout: fixed`, every visible column is
  pinned at the width auto layout gave it (or its stored width) and the table's width becomes their
  sum, so `.table-scroll` scrolls instead of squeezing. Hidden columns are skipped and re-pinned when
  shown; clearing the last stored width returns the table to auto layout. Two JS tests;
  `ASSETS.sha256` updated.
* **WeightRoom** — migration `0009` adds FreeWeight `0011` (`machines.nickname`, nullable, written only
  by FreeWeight's `PATCH /api/v1/machines/{id}`) to `known_revisions`; `machines` is already in the
  guard's *Subject identity, hashed* lock class, so no raw write reaches it. Fixture
  `freeweight-0011.sqlite3` was built by FreeWeight's own migrations (same tables as `0010`, no rows).
  `console_side_nav(current_path)` marks the console menu's entry for the page, which lets every chat
  page's bar offer *New conversation* under the selected Chat entry (WY9's one exception). A `.mono`
  or `code` value in a table cell uses `overflow-wrap: break-word`, which stops auto layout squeezing
  the column. Two `test_shell.py` assertions were widened to allow `aria-current` on the console menu.
* **ModelRack** `LlamaCppProvider` — an expired header whose `ArtifactStamp` still matches is put back
  with a fresh TTL after one `stat` instead of re-parsed. `refresh=True`, a changed stamp,
  `clear_metadata_cache()` and a disabled cache still re-read. This removes the root cause WY6 found.
* **LoadCoach** — `/api/v1/health` and the System page bound the provider check to 0.5 s (late →
  `degraded`, the check finishes on a daemon thread) and `/api/v1/health` is a plain `def` route.
* **FreeWeight** — the Machines page is a `def` route; the enable switch and the Provider form run
  their database write, probe and reload in the threadpool after awaiting the form.

### 10.2 Gates (Python 3.14.4; ruff, mypy and lint-imports green)

| Repository | Commit | Venv | pytest |
|---|---|---|---|
| ModelRack | `aa4c830` | scratch `mr-gate` | 1446 passed, 16 skipped, 27 deselected |
| MirrorWall | `3a4ef62` | `~/ai/suite/py/MirrorWall/.venv` | 402 passed, 3 deselected |
| FreeWeight | `86501fb` | scratch `fw-main` | 2816 passed, 30 skipped, 31 deselected |
| LoadCoach | `b37c966` | scratch `lc-gate` | 1125 passed, 5 skipped, 19 deselected |
| WeightRoom | `9a6e137` | scratch `wr-main` | 2086 passed, 3 skipped, 14 deselected |

Found on the way: the first ModelRack test counted `broken.gguf`, which is never cached and so read on
every pass by design; and a new MirrorWall test constant shadowed an existing `_WIDE_TABLE`. Both fixed
before the commits.

### 10.3 Deployed

* Production venvs of WeightRoom, FreeWeight and LoadCoach now import baseaicore, setspec, weightsdb,
  mirrorwall, sweatmeter and modelrack (and loadledger for WeightRoom) from `~/ai/suite/py`.
* `freeweight.service` and `loadcoach.service` restarted at 09:39:17Z after an idle check (FreeWeight:
  no active run, queue 0; LoadCoach: no job outside completed/failed/cancelled in its database, read
  only). `weightroom.service` restarted at the same time. All three started clean.

### 10.4 Verified

Browser pass against a throwaway console on 8817 running WeightRoom `main` (Playwright, system
Chrome, both widths, both themes; screenshots and `report.json` in the session scratchpad under
`shots2/`):

* **Resize (L2):** LoadCoach Models is a 1693 px table in a 1172 px wrapper. A 57 px drag on the
  first column now gives a 1748 px table: the first column 258 → 315 px, and every other column keeps
  its width (130, 92, 100, 101, …), where WY5's code had collapsed them to 61 px. The wrapper
  scrolls; the page does not.
* **Schema `0011` (§9 item 3):** FreeWeight Database Tables and Query no longer show
  `SCHEMA_UNKNOWN`.
* **Per-character wrap (F4):** the first CSS rule matched `.mono` inside a cell but not
  `td.mono`, which is how Results marks its metric key; the Metric column stayed at 68 px. With
  `td.mono` included (`ce25795`) Metric is 250 px, Model 125 px and Created 149 px, the 1489 px
  table scrolls inside its wrapper, and no page scrolls horizontally at 1440 or 412 px.
* **Chat bar:** `/chat` and `/chat/history` show *New conversation · History · JSON*, the current one
  marked, with Chat selected in the left menu. The throwaway console has no conversations, so a thread
  page was checked by `test_chat_history.py` (all three chat pages) rather than in the browser; the
  duplicate rule (`test_page_nav.py`) still passes over every page.
* No page in the pass scrolls horizontally at either width.

FreeWeight health after the ModelRack fix, sampled every 20 s from the 09:39:17Z restart through
at least one 300 s cache expiry: 24 samples from 09:39:47 to 09:47:32, **all HTTP 200 and `ok`** (0.18–0.27 s), with no `degraded` answer at the 300 s expiry (due about 09:44:47; the 09:44:50 and 09:45:11 samples took 0.20 s). Before the ModelRack fix every expiry answered `degraded` in 0.76–0.94 s (§6.2), and before WY6 it timed out. No console alert opened after 08:20:24Z and none is open.

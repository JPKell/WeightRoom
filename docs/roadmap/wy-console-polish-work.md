# WY Work — the console polish arc

**Started 2026-09-12** from the operator's request list of the same day
([`history/prompts/wy-operator-request-2026-09-12.md`](../history/prompts/wy-operator-request-2026-09-12.md),
verbatim). Twenty-one items, grouped into nine build rows and one merge row by **the files they
collide on**, not by the application they name. Same shape and rules as
[`wx-console-ux-work.md`](wx-console-ux-work.md); [`weightroom-work.md`](weightroom-work.md) §2 is
the standing preamble. Nothing is pushed, tagged or published. **No version bumps** — every change
goes under `## [Unreleased]`.

Read [`history/handoffs/WX_HANDOFF.md`](../history/handoffs/WX_HANDOFF.md) §2 before any row: it
records what the last arc's plan got wrong.

---

## 0. Before wave 1 — the operator's step

1. **WeightRoom `main` has eight uncommitted template edits** (`audit.html`, `doctor.html`,
   `fw_models.html`, `fw_overview.html`, `lc_models.html`, `logs.html`, `ollama.html`,
   `shell.html`) that remove explanatory copy — the same direction as this request. Five of those
   files are rewritten by rows below. **Commit them to `main` (or discard them) before any worktree
   is cut.** A worktree branches from the commit, not from the working tree, so uncommitted edits
   are invisible to every row, and WY10's merge refuses to overwrite them.
2. `stash@{0}` (the Codex shell restyle) stays untouched by every row.

---

## 1. Surveyed facts that shaped the rows (2026-09-12)

1. **The logs already carry the requested nine fields** as three stacked lines (row WX2). The
   request is a layout change, a 3 × 3 grid. It applies in two places that must match: the
   server-rendered history (`app_logs.html`) and the live pane's JavaScript (`_log_pane.html`,
   included by `/logs` and every application's Logs page).
2. **The console Overview reads none of the requested figures, but the code that reads them
   exists.** `services/overview.py` `_STATUS_FIGURES` already takes LoadCoach *Active / Oldest
   queued / Starving*, PromptCadence *Executing / Planning / Pending approvals* and FreeWeight
   *Active run / Queue depth / Disk headroom* from each application's `/system/status`, for the
   per-application Overview pages. The console's `/` (`shell.html`) must reuse it, not re-read.
3. **The telemetry double is literal**: `telemetry_history.html` puts `sparkline_svg` output
   *inside* the ECharts `chart_container`. Row WX6 kept the SVG as an accessible alternative.
4. **Two left-menu rules come from row WX3 and are reversed here by the operator**:
   `rendering.app_side_nav` appends `CONSOLE_SIDE_NAV` under every application's menu, and the four
   `docs*.html` templates append it under the documentation tree.
5. **The catalog is more than a page**: `/catalog` UI and `/api/v1/catalog` routes (W8), a
   `PullRegistry` built in the app lifespan, a `catalog_pull` job kind, `catalog.*` audit events
   (`catalog.enabled` is also reused by the LoadCoach and FreeWeight enable switches), links from
   `lc_models.html` and `fw_models.html`, and the `CONSOLE_PAGES` entry. No `wr-gym catalog` CLI
   verb exists.
6. **MirrorWall's `table.js` sorts one column at a time**, toggling asc/desc, with no indicator and
   no *off* state. Column visibility persists per `data-table` in `localStorage`; nothing is hidden
   by default and nothing resizes. The per-page JavaScript budget is **one total of 120 KB**
   (ADR-0139), measured by `tests/performance/test_budgets.py`.
7. **FreeWeight's `GET /api/v1/health` is `async def` but calls the synchronous
   `get_health_report`**, which calls `provider.health()` (HTTP) and reads the database, on the
   event loop. WeightRoom's `app_down` probe gives it 5 s (`alerts.py` `_HTTP_TIMEOUT_SECONDS`).
   This is the leading hypothesis for the `ReadTimeout` alerts, **not a proven cause**.
8. **The database page is one long page** with anchor links (`#db-tables`, `#db-query`,
   `#db-admin`) below the introduction. The admin section renders above the tables. The operator
   wants real subpages, with the links at the very top.
9. **47 templates carry an ad-hoc link strip** (`page-actions`, the `app_page_header` caller slot,
   `<p>Per application: …`). Most of these links repeat the left menu.

---

## 2. Contracts fixed by this plan

These let rows build in parallel against code that another row writes.

### 2.1 `page_nav` — written by WY1 at gate A, used by every row

In `web/templates/_app_page.html`:

```jinja
{% macro page_nav(links=(), actions=()) %}
```

* `links` — a sequence of mappings `{"label": str, "href": str, "current": bool}` (`current`
  optional). These are the **subsections of the page's own subject**: sibling views such as
  *Tables · Query · Admin*, or *New conversation · History*.
* `actions` — a sequence of `{"label": str, "href": str}`: *JSON*, *Docs*, an API link. Rendered
  at the right-hand end of the same bar, muted.
* The macro renders **nothing** when both are empty. A page with no subsections has no bar.
* Markup: `<nav class="page-nav" aria-label="Page sections">`, with child lists
  `.page-nav-links` and `.page-nav-actions`; `aria-current="page"` on the current link. The CSS
  lives in `static/css/weightroom-shell.css` (the 32 KB shell CSS budget applies).
* Placement: the **first element of `page_content`**, above the page heading.
* **Rule: no `href` in the page bar may also be in the left menu of the same page.** WY1 enforces it
  with `tests/integration/test_page_nav.py`, which renders every GET UI route with the existing
  fixtures and compares the `nav.page-nav` hrefs with the `nav.side-nav` hrefs. Every later row's
  pages must pass it.
* `app_page_header`'s caller slot keeps working until WY10 deletes it, because wave-2 templates
  still call it until they are converted.

### 2.2 A column hidden by default — written by WY5, used by WY8

A MirrorWall `table()` head entry may carry `"hidden": true`. The macro renders it as
`<th data-default-hidden="true">`. `table.js` hides such a column **only when the viewer has no
stored column choice for that table**. The *Columns* menu still lists the column. Before WY5
merges, the key is ignored and the column shows, which is correct behaviour.

### 2.3 Sorting and resizing — written by WY5

* A header click cycles **ascending → descending → off**.
* Several columns sort at once, **in the order they were first clicked**. Each sorted header shows
  ▲ or ▼ and its 1-based position in the sort order. Turning a column off removes it and
  renumbers the rest.
* Missing values (em dash) sort last in both directions, as they do now.
* Only tables with `data-complete="true"` sort on the client. This is unchanged (UI standards §5).
* Every `table[data-table]` gets a drag handle on the right edge of each header. Widths persist per
  table in `localStorage`, beside the hidden-column choice, and a double-click on the handle resets
  that column.

### 2.4 Branch bases

* **Wave 1** branches from WeightRoom `main` after §0.
* **Wave 2** branches from WY1's gate A commit:
  `git -C ~/ai/suite/WeightRoom log row/wy1-shell-nav --grep='row WY1 gate A' -1 --format=%H`.
  Merging WY1 and then a wave-2 branch is an ordinary merge, so no intermediate merge into `main`
  is needed.
* MirrorWall and FreeWeight rows branch from their own `main`.

### 2.5 Reservations

| Row | ADR | Throwaway console port / trust port | Other |
|---|---|---|---|
| WY1 | ADR-0146 (the console has no catalog) | 8801 / 8802 | |
| WY2 | — | 8803 / 8804 | |
| WY3 | — | 8805 / 8806 | |
| WY4 | ADR-0147 (value-mapped chart fill, coloured from tokens) | 8807 / 8808 | |
| WY5 | — | 8809 / 8810 | |
| WY6 | ADR-0148, only if health semantics change | — | FreeWeight serve, fake provider, 18765 |
| WY7 | — | 8811 / 8812 | |
| WY8 | — | 8813 / 8814 | |
| WY9 | — | 8815 / 8816 | |
| WY10 | — | 8817 / 8818 | |

---

## 3. Rows

| Row | Wave | Scope | Repositories · worktree · branch | Model · effort | Why this model | Kickoff |
|---|---|---|---|---|---|---|
| **WY1** | 1 | Shell and navigation: Chat in the top bar and the left menu; no console links under application tabs or on docs pages; `page_nav` (§2.1) and its duplicate test; the page-bar sweep over every template not owned by another row; the catalog removed (ADR-0146) | WeightRoom · `~/ai/worktrees/weightroom-wy1` · `row/wy1-shell-nav` | **Opus 5 · medium** | Wave 2 branches from it. The sweep needs a judgment on every strip (subsection, action or duplicate). The catalog removal must keep historical job rows and audit events readable | [wy1](../history/prompts/wy1-shell-navigation-page-nav-and-catalog-removal.prompt.md) |
| **WY4** | 1 | Telemetry: one page, every figure; large current bars; compact area charts with a green-to-red value-mapped fill; RAM and VRAM totals as values; K/M/G units; the SVG double and the explanatory copy removed | MirrorWall · `~/ai/worktrees/mirrorwall-wy4` · `row/wy4-chart-fill`; WeightRoom · `~/ai/worktrees/weightroom-wy4` · `row/wy4-telemetry` | **Opus 5 · high** | Visual design judgment with an ADR-bound colour rule (ADR-0142), a cross-repository change and a page budget. The feedback loop is screenshots, not tests | [wy4](../history/prompts/wy4-telemetry-page.prompt.md) |
| **WY5** | 1 | MirrorWall `table.js`: 3-state multi-column sort with arrows and order numbers (§2.3), resizable columns, default-hidden columns (§2.2) | MirrorWall · `~/ai/worktrees/mirrorwall-wy5` · `row/wy5-table-sort` | **Sonnet 5 · high** | A bounded state machine in one file with a tight browser loop. The effort goes to the em-dash rule, accessibility and the JS budget | [wy5](../history/prompts/wy5-mirrorwall-table-sort-hide-resize.prompt.md) |
| **WY6** | 1 | The FreeWeight `app_down` alerts: prove the cause of the `/api/v1/health` `ReadTimeout`, fix it where it lives, and prove the fix | FreeWeight · `~/ai/worktrees/freeweight-wy6` · `row/wy6-health-under-load` (a WeightRoom worktree only if the cause is there) | **Opus 5 · high** | Diagnosis before code, concurrency on an event loop, and a production alert that must not be silenced by weakening it | [wy6](../history/prompts/wy6-freeweight-health-under-load.prompt.md) |
| **WY2** | 2 | Logs as a 3 × 3 grid (history and live pane); settings tables with Value, Source and Applies right-aligned and Applies stacked at minimum width | WeightRoom · `~/ai/worktrees/weightroom-wy2` · `row/wy2-logs-settings` | **Sonnet 5 · medium** | Layout in three templates, with the target specified exactly | [wy2](../history/prompts/wy2-logs-grid-and-settings-columns.prompt.md) |
| **WY3** | 2 | Console Overview: LoadCoach, PromptCadence and FreeWeight status figures on `/`, reusing `services/overview.py` | WeightRoom · `~/ai/worktrees/weightroom-wy3` · `row/wy3-overview` | **Sonnet 5 · high** | Reuse is specified. The effort goes to the Overview's performance budget and to "unsupported is not zero" when an application is down | [wy3](../history/prompts/wy3-console-overview-figures.prompt.md) |
| **WY7** | 2 | Chat: history as its own page (a table whose rows open the conversation), a History link in the chat page bar, JSON and Delete on one line | WeightRoom · `~/ai/worktrees/weightroom-wy7` · `row/wy7-chat-history` | **Sonnet 5 · medium** | One new read-only route plus template moves | [wy7](../history/prompts/wy7-chat-history-page.prompt.md) |
| **WY8** | 2 | Model tables: FreeWeight Models without the canonical ID; Results and Evidence by model name, with runtime profile and machine hidden by default (§2.2); LoadCoach model names cut at 30 characters; page bars on these four templates | WeightRoom · `~/ai/worktrees/weightroom-wy8` · `row/wy8-model-tables` | **Sonnet 5 · medium** | Template edits against a fixed contract; the only lookup is where a model's name comes from | [wy8](../history/prompts/wy8-model-tables.prompt.md) |
| **WY9** | 2 | Database: Tables, Query and Admin as real subpages behind a page bar at the very top; every POST lands on its own subpage | WeightRoom · `~/ai/worktrees/weightroom-wy9` · `row/wy9-database-subpages` | **Sonnet 5 · high** | Route surgery around the ADR-0124 guard and its security tests; the flows are specified, but a regression is a write-path regression | [wy9](../history/prompts/wy9-database-subpages.prompt.md) |
| **WY10** | 3 | Merge all branches, remove the `app_page_header` caller slot, run every gate and budget, verify in a browser at both widths, write the arc handoff | All touched repositories, on `main` | **Opus 5 · high** | Cross-branch conflicts on shared files, the final judgment of the duplicate-link rule over the whole site, and the only session that touches `main` | [wy10](../history/prompts/wy10-merge-and-verify.prompt.md) |

No row is assigned Haiku: the smallest item (LoadCoach name truncation) shares files with WY8, and a
separate session would cost more to start than the edit.

---

## 4. File ownership

Only the owning row edits a file below. WY1's sweep **skips** every file in this table.
`CHANGELOG.md` and `tests/performance/test_budgets.py` are shared; each row writes one contiguous
block and WY10 resolves the rest.

| Row | Files it owns (WeightRoom unless named) |
|---|---|
| WY1 | `_shell.html`, `_app_page.html`, `web/rendering.py`, `static/css/weightroom-shell.css`, `docs.html`, `docs_page.html`, `docs_adrs.html`, `docs_search.html`, `_docs_tree.html`, everything catalog, `tests/integration/test_page_nav.py`, and every other template with a link strip |
| WY2 | `app_logs.html`, `logs.html`, `_log_pane.html`, `settings.html` |
| WY3 | `shell.html`, `web/routes/shell.py`, `services/overview.py` (additive only: the per-app Overviews use it) |
| WY4 | `telemetry_history.html`, `web/routes/system.py` (the page handler), `services/telemetry.py`; MirrorWall `static/js/charts.js` |
| WY5 | MirrorWall `static/js/table.js` and the `table()` macro in `templates/mirrorwall/components.html` |
| WY6 | FreeWeight `web/routes/system.py`, `services/health.py`, and whatever the diagnosis proves |
| WY7 | `chat.html`, `chat_thread.html`, `_chat_rail.html`, `static/css/chat.css`, `web/routes/chat.py`, a new `chat_history.html` |
| WY8 | `fw_models.html`, `fw_results.html`, `fw_evidence.html`, `lc_models.html` |
| WY9 | `database.html`, `database_table.html`, `databases.html`, `web/routes/databases.py`, and new database subpage templates |

**Gate A of WY1** also removes the two `/catalog` links from `fw_models.html` and `lc_models.html`
before WY8 branches, so WY8 inherits the removal.

---

## 5. Rules for every build row (WY1–WY9)

**You may:** work only inside your own worktrees; commit on your own branch; run the gate in your
worktree's own venv and name the interpreter in the report; start and stop **your own** throwaway
console on **your own** port (§2.5) with **your own** XDG tree under your scratchpad; read the
operator's running applications over HTTP with GET (`127.0.0.1:8765` FreeWeight, `8766` LoadCoach,
`8767` IdeaPress, `8768` PromptCadence, `8769` WeightRoom); read journals with `journalctl --user`
and unit state with `systemctl --user show`.

**You may never:** touch the GPU (no model load, no `llama-server`, no Ollama generate, no
`pytest -m live`); run `systemctl --user start|stop|restart` on any suite unit or `ollama`; write
to `~/.config/<app>` or `~/.local/share/<app>`; reset or use the operator's console password; merge,
rebase onto a moving `main`, `git push`, tag, bump a version, or `git add -A`; work in another row's
worktree, on `main`, or in a file another row owns (§4); edit this file or `roadmap/README.md`.

**Method:** docstring-first; `from __future__ import annotations`; `mypy --strict`; the page kit in
`history/handoffs/WP1_HANDOFF.md` §3; tests for every branch you add; fixtures recorded from the
application's own API shape. Screenshots at **1440 px and 412 px, both themes**, for every page
you change. The Playwright and throwaway-console method is in
`~/.claude/projects/-home-jpk-ai-suite/memory/browser-screenshots-for-ui-work.md`; kill servers by
environ-verified pid, never `pkill -f`. A dense `table()` needs a `table_id` or it loses its header
row at 412 px (WX9). One contiguous `CHANGELOG.md` block at the top of `## [Unreleased]`.

**Finish line:** the gate is green in every repository you touched (`ruff format --check .`,
`ruff check .`, `mypy src tests`, `lint-imports`, `pytest`), with the interpreter named;
`git status --short` is clean; commits at each gate use Conventional Commits and end with the
session's attribution line; `docs/history/handoffs/WY<N>_HANDOFF.md` is on your WeightRoom branch
(or in your report, for a row with no WeightRoom worktree), covering decisions, measurements, what
this plan got wrong, and screenshot paths. **Do not merge.** Report the branch heads, the gate
lines, and any decision you want reviewed. If you need the GPU, a shared unit or another row's
file, **stop and say so**.

**Worktree setup** (each kickoff names its own paths):

```bash
git -C ~/ai/suite/<Repo> worktree add ~/ai/worktrees/<repo>-wy<N> -b row/wy<N>-<slug> <base>
cd ~/ai/worktrees/<repo>-wy<N>
python3.14 -m venv .venv
S=~/ai/suite/py
.venv/bin/pip install -q -e $S/BaseAiCore -e $S/SetSpec -e $S/WeightsDB -e $S/MirrorWall \
  -e $S/SweatMeter -e $S/ModelRack -e "$S/LoadLedger[sql]" -e ".[dev]"
.venv/bin/pip list --editable   # must show all seven suite packages from ~/ai/suite/py, plus this repo
```

**Suite packages come from `~/ai/suite`, never from PyPI** (added 2026-09-13, after wave 1). PyPI
lags the suite: `mirrorwall 0.3.1` is not published, and the other packages have unreleased commits
on `main` that the applications already use. Install every suite dependency editable **in the same
`pip install` command as the repository itself**, so that the resolver never fetches a PyPI copy.
If `pip list --editable` does not show a suite package, or `python -c "import <pkg>;
print(<pkg>.__file__)"` points into `site-packages`, fix the venv before running anything else. A
gate result from a PyPI copy does not count. Never edit a pin in `pyproject.toml` to make an install
resolve. If an install still fails, stop and report the error. For a FreeWeight or MirrorWall
worktree, install that repository's own suite dependencies the same way; its `pyproject.toml` lists
them.

---

## 6. Waves

| Wave | Rows | Launch when | Expected length |
|---|---|---|---|
| 1 | WY1, WY4, WY5, WY6 — four sessions at once | §0 is done | WY1 gate A in about 30–45 min; the rest 1–3 h |
| 2 | WY2, WY3, WY7, WY8, WY9 — five sessions at once | WY1's gate A commit exists (§2.4) | 1–2 h each |
| 3 | WY10 | All nine rows have reported | 2–3 h |

Nine build sessions touch the shell at most once each. Wave 2 starts before WY1 finishes: wave 2
needs only gate A's macro, and WY1's later gates touch no wave-2 file.

---

## 7. Status

| Row | Status | Branch head | Handoff |
|---|---|---|---|
| WY1 | planned | — | — |
| WY2 | planned | — | — |
| WY3 | planned | — | — |
| WY4 | planned | — | — |
| WY5 | planned | — | — |
| WY6 | planned | — | — |
| WY7 | planned | — | — |
| WY8 | planned | — | — |
| WY9 | planned | — | — |
| WY10 | planned | — | — |

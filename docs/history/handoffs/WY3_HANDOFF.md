# WY3 Handoff — the console Overview shows each application's live figures

**Row:** WY3 (`roadmap/wy-console-polish-work.md` §3) · **Ran:** 2026-09-13, one sitting ·
**Model:** Claude Sonnet 5 · high · **Kickoff:**
`history/prompts/wy3-console-overview-figures.prompt.md` · **Repository:** WeightRoom only ·
**Branch:** `row/wy3-overview` in `~/ai/worktrees/weightroom-wy3`, commit `00b219c`. **Not merged.**

## 1. What shipped

* **`services/overview.py`** (additive, per §4): `status_figures(app, view, *, settings, client)`
  is the fetch-and-map half of `overview_for`'s running branch (`_fetch_status` +
  `_figures_from_status`, with `_dash_figures` on any failure), pulled into a shared private
  helper `_status_figures_and_body` so both `overview_for` and the new public wrapper call the
  same code — no logic is duplicated, only named and exposed. `AppCard` (`app`, `pill`, `figures`,
  `reason`) and `overview_cards(views, *, settings, client)` run `status_figures` for LoadCoach,
  PromptCadence and FreeWeight in a three-worker `ThreadPoolExecutor` — never a database open, never
  `config show`. `_STATUS_FIGURES["loadcoach"]`'s *Oldest queued* entry changed its `how` tag from
  `value` to a new `duration` branch in `_shown()` (`mirrorwall.duration_human`) — the one
  intentional output change in this row, since the kickoff's Build §4 asks for it explicitly on
  both pages; it is proved and called out by name in `test_overview.py` and
  `test_overview_status_bodies.py` rather than left as an unexplained diff.
* **`web/routes/shell.py`**: `/` now computes `views` once (`views_for_request`), builds the three
  cards (`overview_cards`), and passes both into `render_shell_page`.
* **`web/routes/apps.py`**: `render_shell_page` gained an optional `views` keyword — a caller that
  already has them passes them through so `inventory()` (a real `systemctl show` launch) runs once
  per render, not twice. This file is not in §4's ownership table; the change is a single
  backward-compatible optional parameter (every other of the ~25 call sites is unaffected — proved
  by the full suite), flagged here since it wasn't pre-cleared.
* **`shell.html`**: the manual `<span class="page-actions">` strip is now `page_nav()` (row WY1's
  macro), which renders nothing — Applications, Logs, Ollama and Trust are all in the left menu, so
  a bar repeating them would fail `test_page_nav.py`. The three card rows sit between the top cards
  (Bind/Certificate/Operator, kept — they show none of the same data) and the Applications table,
  each a small `<h4>` (the application's name, linking to its tab, plus its status dot) over a
  `card-grid` of its three figures. **Decision on layout**: rather than invent new CSS for a
  side-by-side "row of groups," each application's block reuses the existing `card-grid` (already
  responsive — `grid-template-columns: 1fr` under 767 px) exactly as the Bind/Certificate/Operator
  row above it does. This reads as three stacked sections rather than one wide row of three groups;
  it is compact and needs no new CSS, but is a legitimate re-reading of "one compact card row per
  application" worth a second look if the operator wants the groups side by side on a wide screen.

## 2. Down is not zero

A card's `reason` (rendered as the `card-grid`'s `title`) is computed from the same `AppView` the
rest of the console already reads, not a second probe: not running → `f"{view.pill}."`
(`"stopped."`, `"not installed."`, …); running but unreachable → `view.error` (the version probe's
own words, e.g. the live proof below shows `"ConnectError: [Errno 111] Connection refused."`);
running and reachable but every figure came back dashed anyway → `"status call failed."` (the
status call itself failed after the version probe succeeded — rare, but distinct from "never
tried"). Every other card's `reason` is `None` and the `title` attribute is omitted.

## 3. Tests

* `tests/unit/test_overview_cards.py` (new): `status_figures` against a mocked `/system/status`
  matches the same fixture-derived figures `test_overview_status_bodies.py` already pins; a
  stopped application makes no HTTP call at all (`respx.mock` with no routes registered — a call
  would raise); a failed call while running still dashes; `overview_cards` orders LoadCoach,
  PromptCadence, FreeWeight and skips IdeaPress; a stopped card's reason names its pill; an
  unreachable card's reason names `view.error`; a concurrency test (three 300 ms fakes) asserts the
  whole call finishes in under 2× one delay, not 3×.
* `tests/unit/test_overview.py` / `test_overview_status_bodies.py`: every existing test still
  passes unmodified — the refactor's byte-identical proof for everything except *Oldest queued* —
  plus one new test each pinning the duration format (`125.0` → `"2m 05s"`, `None` still `"—"`).
* `tests/integration/test_shell.py` (new tests): `/` renders all three applications' live figures
  end to end through the real route (mocked `/system/status` + `/version`, real systemd fake); a
  stopped LoadCoach's card is three dashes with `title="stopped."`; the whole page stays inside
  ~2× one delay with three concurrently-mocked 100 ms status calls.
* `tests/performance/test_budgets.py` (new `three_app_console` fixture +
  `test_the_overview_cards_read_three_applications_concurrently_not_in_series`): three 300 ms fakes
  measured **305.1 ms** median against a 600 ms budget (would be ~900 ms serial) — the WPF6 lesson
  observed: the fake costs what a slow call would, so a regression to sequential reads fails loud.
  `test_shell_render_on_a_warm_process` (the pre-existing 50 ms budget) is unaffected: its fixture's
  applications are unreachable, so `status_figures` dashes on the `running and reachable` check
  before attempting any call — confirmed unchanged (3.8 ms) in the same run.

## 4. Live proof

Throwaway console (ports 8805/8806, §2.5), `~/ai/worktrees/weightroom-wy3/.venv`, pointed at the
four real running applications (`freeweight.service`, `loadcoach.service`, `ideapress.service`,
`promptcadence.service`, all active on this machine). LoadCoach and PromptCadence's own
`/system/status` require a bearer token (`401` without one — FreeWeight's does not); the throwaway
console's `config.toml` names the operator's existing `loadcoach.token` / `promptcadence.token`
files by path (`api_key_file`, read-only, the same mechanism the real console uses) rather than
minting new ones or leaving the cards permanently dashed for want of auth.

* **All three live** (1440 px and 412 px, light and dark — four screenshots, session scratchpad
  `wy3-shell-{1440,412}-{light,dark}.png`): LoadCoach Active 0 / Oldest queued — / Starving 0;
  PromptCadence Executing 0 / Planning 0 / Pending approvals 0; FreeWeight Active run — / Queue
  depth 0 / Disk headroom 481.4 GiB. Every figure a real read, not a fixture.
* **LoadCoach down** (`wy3-shell-1440-light-loadcoach-down.png`): its `base_url` repointed to a
  closed port (9) in the throwaway config only — `loadcoach.service` itself never touched.
  LoadCoach's card renders three dashes, `title="ConnectError: [Errno 111] Connection refused."`;
  PromptCadence and FreeWeight are unaffected (still live). The Applications table's LoadCoach row
  also shows `—` for Version, from the same failed probe — pre-existing behaviour, unchanged.

All four applications show `not installed` in the Applications table pill throughout — the
throwaway console's `PATH` does not resolve their CLIs, unrelated to this row (the real
`weightroom.service` has them configured). It does not gate the cards: `status_figures` checks
`view.running` (real `systemctl show`) and `view.reachable` (the version probe), not `installed`.

## 5. What this kickoff got right, and one thing to flag

* The suggested signature (`status_figures(app, *, settings, client)`) needed `view` too — it
  can't decide `running`/`reachable`/`base_url` without it. Not a problem the kickoff's "for
  example" wording didn't already allow for.
* **Flag for review**: the `web/routes/apps.py` touch (an optional `views` parameter on
  `render_shell_page`) is outside §4's ownership table. It was the only way to avoid a second
  `systemctl show` launch per `/` render — the exact class of cost row WPF6 spent a whole row
  removing from the per-application Overview — so leaving it in `shell.py` (compute `views` twice)
  felt like reintroducing that lesson on a technicality. It's additive and backward-compatible
  (default `None` preserves every other of the ~25 call sites), but it's a shared file no row was
  handed, so it's called out rather than assumed fine.

## 6. Open, for whoever comes next

* The card-group layout decision in §1 (stacked sections vs. a side-by-side row of three groups) is
  a judgment call, not a spec reading with no alternative — worth the operator's eyes on the
  screenshots before WY10's sweep.
* Nothing else from this row. Gate is green (below); not merged, not pushed, no version bump, per
  the standing W-arc holds.

## 7. Gate

WeightRoomGym at `00b219c`, `.venv` **Python 3.14** —
`ruff format --check .` (245 files), `ruff check .`, `mypy src tests` (238 files), `lint-imports`
(5 contracts kept), `pytest` → **2061 passed, 3 skipped, 13 deselected**, `pytest --cov` **90.99%**
(floor 85%), `pytest tests/performance/test_budgets.py -m performance` → **13 passed** including
the new WY3 budget (305.1 ms / 600 ms). `git status --short` clean.

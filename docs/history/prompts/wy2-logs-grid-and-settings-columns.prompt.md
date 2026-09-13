# Kickoff — Row WY2: logs as a 3 × 3 grid, and settings columns

**Row:** `WY2` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read §1 fact 1, §2.1, §2.4, §4 and §5 first. **Written:** 2026-09-12. **Model:** Sonnet 5 · medium.
**Wave:** 2.

**Repository:** WeightRoom. **Worktree:** `~/ai/worktrees/weightroom-wy2`, branch
`row/wy2-logs-settings`, from **WY1's gate A commit** (§2.4). **Throwaway console:** 8803, trust 8804.

```bash
BASE=$(git -C ~/ai/suite/WeightRoom log row/wy1-shell-nav --grep='row WY1 gate A' -1 --format=%H)
test -n "$BASE" || { echo "WY1 gate A not committed yet — stop"; exit 1; }
git -C ~/ai/suite/WeightRoom worktree add ~/ai/worktrees/weightroom-wy2 -b row/wy2-logs-settings "$BASE"
cd ~/ai/worktrees/weightroom-wy2 && python3.14 -m venv .venv
.venv/bin/pip install -q -e ".[dev]" && .venv/bin/pip install -q -e ~/ai/suite/py/MirrorWall
```

## Part 1 — every log view is a 3 × 3 grid

The operator: *"3 columns, each with 3 rows. The left column is the log level, date, time; the
middle column is app, version, pid; the right column is the message, the logger and the id."* The
fields already exist (row WX2); this is layout.

| Left (narrow) | Middle (narrow) | Right (takes the rest) |
|---|---|---|
| level badge | app | message |
| date `YYYY-MM-DD` | version | logger |
| time `HH:MM:SS` | `pid` | request id |

* One CSS grid per line: `grid-template-columns: max-content max-content 1fr`. Each cell is a
  column of three lines. The message wraps; the other cells do not.
* **Same markup in both places**: the server-rendered history in `app_logs.html`, and the rows that
  `_log_pane.html`'s script builds for the live pane (used by `/logs` and every application's Logs
  page). Build the live rows with the same class names, so one stylesheet serves both.
* A missing value is `—`. The level colour rules on `data-level` stay.
* **412 px:** the left and middle columns merge into one narrow column of six short lines, and the
  message column keeps its width. Screenshot it.
* The notice lines (`— dropped N lines —`, `— the journal reader ended —`) span all three columns.
* `app_logs.html` and `logs.html`: convert their link strips to `page_nav`. *JSON* is an action.
  *Every unit* (`/logs`) is removed where the left menu already has Logs. The *Per application*
  sentence on `/logs` becomes `links`. Keep the filter bar.

## Part 2 — settings tables

The operator, for **every** settings page: Value, Source and Applies are right-aligned; several
pills in Applies stack; Applies and Source take only the room they need, so Key and Value get the
rest.

* Find every settings table first (`grep -rn settings-table`), including the provider-profile cards
  (WX13) inside `settings.html`.
* Value, Source and Applies are right-aligned (`text-align: end`). The inputs and selects in Value
  align to the right edge.
* Applies: pills and the `clear` or `to file` buttons stack vertically, right-aligned, one per line.
  Source and Applies use `width: 1%; white-space: nowrap` (shrink to content); Key and Value share
  the rest.
* The hint row below a field still spans every column.
* 412 px: no horizontal scroll inside the settings section. Screenshot it.
* Convert `settings.html`'s link strip, if it has one, to `page_nav`.

## Tests

Render tests: a history line has three grid columns, each with three lines, in the stated order; the
live pane's script builds the same structure (a test on the template text is enough, or Playwright);
a settings row with two Applies pills renders them stacked. The page-nav duplicate test passes for
both logs pages and every settings page. Screenshots: `/logs`, `/apps/loadcoach/logs`,
`/apps/freeweight/settings`, `/settings`, each at 1440 px and 412 px, light and dark.

## Out of scope

The journal reader, the filter semantics, settings-form logic (`settings_forms.py`), and any file
§4 gives to another row.

Finish line, commits, `WY2_HANDOFF.md` and report: roadmap §5.

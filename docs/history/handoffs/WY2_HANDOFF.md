# WY2 handoff — logs as a 3 × 3 grid, and settings columns

Branch `row/wy2-logs-settings`, worktree `~/ai/worktrees/weightroom-wy2`, from WY1's gate A commit
`ebc659e857c92b6a281dc66a267467be6013ded1`. Not merged.

## 1. What was built

**Part 1 — logs grid.** `app_logs.html`'s history rows and `_log_pane.html`'s live-pane script now
render the same three-column, three-row-per-column structure: `div.log-col.log-col-1` (level
badge, date, time), `.log-col-2` (app, version, pid), `.log-col-3` (message, logger, request id,
the one column that wraps). One CSS grid (`grid-template-columns: max-content max-content 1fr`) on
`.log-row` in `_log_pane.html`'s shared `<style>` block, since that file is `{% include %}`d by
both `app_logs.html` and `logs.html`. Missing values render `—`. At ≤480 px the left and middle
columns collapse into one column of six lines (`grid-column: 1` on both, `.log-col-3` spans both
rows) — screenshotted at 412 px.

`_log_pane.html`'s JavaScript was rewritten from a flat `row(lines)` helper (three `<p>`s) to
`row(cols)` / `col(cls, texts)`, building the same `div.log-col …` structure per SSE payload, in
the same order. `appendNotice` (dropped-lines / reader-ended) is a single `<li class="log-row
notice-line">` with one `<p>`, `display: block` — it spans all three columns because it is not a
grid at all.

`app_logs.html`'s link strip (*JSON* · *Every unit*) became `page_nav(actions=[...])`; *Every unit*
is dropped (the left menu already has *Logs*). `logs.html`'s "Per application: …" sentence became
`page_nav(links=[...])`, one per application. Verified against `test_page_nav.py`'s repeat check:
`/logs` (console page) and `/apps/{app}/logs` never share `nav_sections` entries with the app
links I added, so nothing repeats the left menu.

**Part 2 — settings columns.** One template, `settings.html`, serves `/settings` and every
`/apps/{app}/settings` (including the WX13 provider-profile cards, which reuse the same
`settings-table` class) — there is exactly one `settings-table` in the codebase, so "every settings
page" is one CSS block. Value, Source and Applies are `text-align: end`; Source and Applies are
`width: 1%; white-space: nowrap` so Key and Value get the rest.

## 2. The one real bug this row found

`display: flex; flex-direction: column` directly on the Applies `<td>` corrupts Chromium's text
painting for the *first* stacked child — a badge reading "restart" rendered as garbled overlapping
glyphs (`fidstart`-looking), confirmed by locator-screenshotting that one `<span>` alone and by
toggling the `<td>`'s `display` back to `block` (clean). The fix: the field_rows macro now wraps
the cell's badges/buttons in `<div class="applies-stack">`, and the flex box lives on that div —
the `<td>` stays a plain table cell. Screenshots below are all post-fix.

## 3. Screenshots

Rendered by fetching each page's HTML through the existing test fixtures (`tests/support`,
`StubJournal`, `respx`), rewriting `/app-static/…` and `/static/mirrorwall/…` hrefs to `file://`
paths, and opening the file with Playwright + system Chrome (`/usr/bin/google-chrome`) — no live
console, no port, no GPU. `/logs`, `/apps/loadcoach/logs`, `/apps/freeweight/settings`, `/settings`,
each at 1440 px and 412 px, light and dark: `/tmp/wy2-shots/{name}_{desktop,mobile}_{light,dark}.png`
(this machine's `/tmp`, not committed). Confirmed at 412 px: `document.documentElement.scrollWidth
=== 412` on `/settings` (no horizontal scroll).

## 4. What the kickoff got wrong

Nothing structural. `_APP_PAGES` / `settings-table` grep confirmed there is exactly one settings
template, not one per application, which simplified Part 2 to a single CSS block rather than a
per-page hunt.

## 5. Gate

Interpreter: `python3.14` (`.venv/bin/python`, this worktree). All green:

```
ruff format --check .   # 245 files already formatted
ruff check .            # All checks passed!
mypy src tests          # Success: no issues found in 238 source files
lint-imports            # Contracts: 5 kept, 0 broken.
pytest                  # 2052 passed, 3 skipped, 12 deselected
```

`git status --short` clean after the commit below.

## 6. Files touched

`src/weightroom/web/templates/{app_logs,logs,_log_pane,settings}.html`,
`tests/integration/test_wy2_logs_grid_and_settings_columns.py`, `CHANGELOG.md`, this handoff.

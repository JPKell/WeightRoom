# Kickoff — Row WY5: table sorting, default-hidden columns and resizing (MirrorWall)

**Row:** `WY5` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read §1 fact 6, §2.2, §2.3 and §5 first. **Written:** 2026-09-12. **Model:** Sonnet 5 · high.
**Wave:** 1.

**Repository:** MirrorWall. **Worktree:** `~/ai/worktrees/mirrorwall-wy5`, branch
`row/wy5-table-sort`, from MirrorWall `main`. For browser checks only, a WeightRoom worktree
`~/ai/worktrees/weightroom-wy5` (branch `row/wy5-browser-check`, from `main`, **no commits**) whose
venv installs MirrorWall from your MirrorWall worktree. **Throwaway console:** 8809, trust 8810.

```bash
git -C ~/ai/suite/py/MirrorWall worktree add ~/ai/worktrees/mirrorwall-wy5 -b row/wy5-table-sort main
cd ~/ai/worktrees/mirrorwall-wy5 && python3.14 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
git -C ~/ai/suite/WeightRoom worktree add ~/ai/worktrees/weightroom-wy5 -b row/wy5-browser-check main
cd ~/ai/worktrees/weightroom-wy5 && python3.14 -m venv .venv && .venv/bin/pip install -q -e ".[dev]" \
  && .venv/bin/pip install -q -e ~/ai/worktrees/mirrorwall-wy5
```

**Read before code:** MirrorWall `static/js/table.js` (all of it: the header comment states two
load-bearing rules), the `table()` macro in `templates/mirrorwall/components.html`, MirrorWall's UI
standards §5 and §7, ADR-0020 (progressive enhancement), ADR-0139 (the 120 KB JS total, measured by
WeightRoom `tests/performance/test_budgets.py`), and
`tests/test_no_application_vocabulary.py` (no application words in a component).

## Build

1. **Multi-column 3-state sort** (§2.3). Clicking a header cycles ascending → descending → off.
   Columns combine in first-click order. Each sorted header shows ▲ or ▼ and a small order number
   (`▲1`, `▼2`). *Off* removes the column and renumbers the rest. Turning every column off restores
   the server's order: remember the original row order on first sort. The em-dash-last rule holds
   for every key in both directions. Numeric columns (`th.numeric`) compare numerically. Ties fall
   through to the next key. Keep `data-complete="true"` as the precondition for sorting.
2. **Accessibility.** `aria-sort` goes on the first key only (ARIA allows one). Every sorted header
   button gets visually hidden text naming its direction and position. The header stays a
   `<button>`, so the keyboard works.
3. **Default-hidden columns** (§2.2). The macro renders a head entry's `"hidden": true` as
   `data-default-hidden="true"`. `table.js` applies it only when there is no stored choice for that
   table. The *Columns* menu lists the column unchecked. The column-visibility menu currently needs
   6 or more columns; a table with a default-hidden column gets the menu regardless, or the column
   could never be shown.
4. **Resizable columns** (§2.3). A thin drag handle on each header's right edge (pointer events,
   touch included) sets the column width. Widths persist per `data-table` in `localStorage`, next to
   the hidden-column choice and wrapped in `try/catch` like it. Double-clicking the handle clears
   that column's stored width. Resizing switches the table to `table-layout: fixed` only once a
   width is stored, so an untouched table lays out as it does today. Put the handle's CSS in
   MirrorWall's stylesheet, using tokens only.
5. **Keep it small.** Measure `table.js` before and after, minified and raw, and run WeightRoom's
   JS budget test against your MirrorWall worktree. Report both numbers.

## Tests

Use whatever MirrorWall already has for JavaScript. If it has no JS runner, **do not add a Node
toolchain**; drive the behaviour with Playwright from the WeightRoom browser-check worktree against
real console pages (for example LoadCoach Models and FreeWeight Models, fixtures or live GET).
Cover: a 3-click cycle on one column; two keys with ties; em dashes last in both directions;
*off* restores the server order; a default-hidden column hidden on first visit, shown after being
ticked, and still shown after reload; a width that persists across reload and resets on
double-click. Add Python tests for the macro output of `hidden`. Screenshots at 1440 px and 412 px,
light and dark, of a table sorted on two keys and with one resized column.

## Out of scope

Server-side sorting of paged tables. Every WeightRoom template: WY8 opts its columns in with
`hidden`. `charts.js` (WY4 edits it on another MirrorWall branch; do not touch it).

Finish line, commits and report: roadmap §5. There is no WeightRoom branch to carry a handoff, so put
the handoff content (decisions, byte counts, screenshot paths) in your report, and WY10 files it as
`WY5_HANDOFF.md`. Before you report, remove the browser-check WeightRoom worktree and delete its
branch.

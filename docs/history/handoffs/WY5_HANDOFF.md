# WY5 Handoff — MirrorWall table sort, hide and resize

**Row:** WY5 in [`roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md) ·
**Ran:** 2026-09-12/13 · **Model:** Sonnet 5 · high · **Kickoff:**
`history/prompts/wy5-mirrorwall-table-sort-hide-resize.prompt.md` · **Repository:** MirrorWall only.
**Branch:** `row/wy5-table-sort`, worktree `~/ai/worktrees/mirrorwall-wy5`, commit `677b580`.
Merged by WY10 (see [`WY_HANDOFF.md`](WY_HANDOFF.md)).

**Filed by WY10.** The row had no WeightRoom branch, so its handoff was its agent report, and that
report did not reach the WY10 session verbatim. This file is rebuilt from the commit message, the
`CHANGELOG.md` block, the tests on the branch and the row's note in the operator's session memory.
The row's screenshots were in its own session scratchpad and are not recoverable; WY10's browser
pass (`WY_HANDOFF.md` §6) covers the same tables.

## 1. What was built (roadmap §2.2 and §2.3)

* **Sort.** A header click cycles ascending → descending → off. Several columns combine in the order
  they were first clicked; ties fall through to the next key. Turning every column off restores the
  server's row order, captured once before the first sort. Each sorted header shows `▲`/`▼` and its
  1-based position (`▲1`, `▼2`). The em-dash-last rule holds on every key in both directions. Only
  `data-complete="true"` tables sort on the client (unchanged).
* **Accessibility.** `aria-sort` is set on the primary key only (ARIA allows one). Every sorted
  header carries a `.sr-only` description (`aria-describedby`) naming its direction and position.
  `.sr-only` is a new utility in `layout.css`.
* **Resize.** A thin pointer-events drag handle on each header's right edge. Widths persist per
  `data-table` in `localStorage`, beside the column-visibility choice. A double-click clears that
  column's stored width. A table switches to `table-layout: fixed` only once a width is stored, so an
  untouched table lays out as before.
* **Default-hidden columns.** A `table()` head entry may carry `"hidden": true`, rendered as
  `<th data-default-hidden="true">`. `table.js` hides such a column only when the viewer has no
  stored column choice for that table; an explicit choice — even "show everything" — wins. The
  *Columns* menu now also appears below six columns when a column is default-hidden, or the column
  could never be shown.

Files: `static/js/table.js`, `templates/mirrorwall/components.html`, `static/css/tables.css`,
`static/css/layout.css`, `static/ASSETS.sha256`, `tests/js/test_table.py`,
`tests/snapshot/test_components.py`, `CHANGELOG.md`.

## 2. Measurements

| Measure | Figure |
|---|---|
| `table.js` raw | 6 672 → 13 662 bytes |
| WeightRoom page-JS total against the WY5 worktree, heaviest page (`/apps/freeweight`) | 97.0 KB of 120 KB (ADR-0139) |

## 3. Decisions

1. `aria-sort` on the primary key only, the rest described for screen readers (above).
2. The *Columns* menu threshold of six columns is lifted for any table that has a default-hidden
   column.
3. Fixed table layout only once a width is stored, to leave every untouched table's layout alone.

## 4. What the plan got wrong

Nothing recorded. The kickoff's worktree setup order has the same flaw WY4 found (install the
MirrorWall worktree's suite dependencies editable in the same `pip install` as the repository).

## 5. Gate

Row's own report (Python 3.14.4): `ruff format --check .`, `ruff check .`, `mypy src tests`,
`lint-imports`, `pytest` — 395 passed, 1 skipped, 3 deselected. WY10's re-run is in
`WY_HANDOFF.md` §3.

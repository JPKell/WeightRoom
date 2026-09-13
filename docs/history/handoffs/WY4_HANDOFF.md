# WY4 handoff — the telemetry page

**Row:** WY4 in [`roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md) ·
**Date:** 2026-09-12 · **Model:** Opus 5 · high.
**Branches (not merged, not pushed):**

* MirrorWall `row/wy4-chart-fill` in `~/ai/worktrees/mirrorwall-wy4` — head **`9d56bd9`**.
* WeightRoom `row/wy4-telemetry` in `~/ai/worktrees/weightroom-wy4` — this file's commit.

## 1. What was built

**`/telemetry/history` is one page with every figure.** A row of large live bars (CPU, RAM, GPU,
VRAM, CPU temp, GPU temp, GPU power), then one compact area chart per figure — four per row at
1440 px, one per row at 412 px. No heading, no intro, no figure selector. RAM and VRAM totals are
printed small beside their used figure (`12.2 G / 30 G`) and are never charted. Each chart's fill
is mapped to its value, green low to red high, from the status tokens (ADR-0147). The inline SVG
double, `sparkline_svg` and `echarts_line_option` are gone.

* **`services/telemetry.py`**: `FIGURE_SCALES` (the one scale table, page order, `ponytail:` notes
  on both temperature ranges), `format_figure` (the Python formatter), `telemetry_panels` (one
  `SELECT` of every column, every series cut from it, at most `CHART_POINTS` = 240 points per chart),
  `FigureScale` and `FigurePanel`.
* **`web/routes/system.py`**: the page handler builds panels and marks `?figure=`; a total's name
  marks the chart it is printed on (`gpu_vram_total_bytes` → VRAM). The JSON history route is
  unchanged.
* **`telemetry_history.html`**: bars, grid, page CSS in `extra_head`, and one inline script that
  scrolls to the marked chart and updates the bars from the strip's `mw:telemetry` frames.
* **MirrorWall `charts.js`**: `visualMap` with `"mw_scale": "load"` coloured from `--mw-success` →
  `--mw-warning` → `--mw-danger`; `"mw_unit"` prints the value axis and the tooltip through
  `window.mirrorwallCharts.format`; axis rules, labels and the tooltip surface themed from tokens
  (this replaces ADR-0142's `ponytail:` note on axis colours); charts resize with the window; each
  redraw themes the caller's option afresh. `ASSETS.sha256` updated.
* **Docs**: ADR-0147 and its README row; spec §7.7 describes the one page.

## 2. Decisions a reviewer should look at

1. **The marker is `mw_scale`, not the kickoff's example `wr_scale`.** `charts.js` is MirrorWall's
   and knows no application; `mw_` matches its other names.
2. **The JavaScript formatter lives in MirrorWall `charts.js`, not in the page.** The axis labels
   and the tooltip need it inside `charts.js`, and a second copy in the page would make three
   formatters. The page's bars call `window.mirrorwallCharts.format`. One case table
   (`tests/unit/test_telemetry_page.py` `FORMAT_CASES`) runs through `format_figure` and through
   node against the installed `charts.js`.
3. **Rounding is half-up with identical float steps in both languages**
   (`floor(x * 10 + 0.5) / 10`). Python's `round()` is banker's rounding and `Math.round` is not;
   `0.25 count` is the case that proves the two agree.
4. **Format:** one decimal below 100 of a suffix, none from 100 (`18.2 G`, `100 M`, `1023 B`);
   bytes below 1 K print `B`; counts below 1 K print bare; `%` has no space, `°C` and `W` do.
5. **`chart_container()` is not used.** It always renders a `<p class="muted">` description, which
   is copy the operator asked to remove. The page writes `<figure>` itself; no MirrorWall template
   changed.
6. **Bucketing keeps the highest reading in each bucket**, so a load spike survives. A bucket of
   only `None` stays `null` (a gap). A stretch with no rows at all (the console was stopped) is
   joined across, not gapped — gapping empty buckets breaks the line past the hour boundary where
   the sweep leaves one row per minute.
7. **"Current" is the newest row's value**, so a figure the latest sample could not read prints
   `—` even if older samples exist; a figure with no reading in the whole window draws no chart.
8. **Watts scale to the window's highest sample**, and the live bar raises its own `data-high` when
   a new sample exceeds it. A byte bar's scale follows the live total.
9. **Status colours carry magnitude here** (ADR-0147 rule 5); every bar and chart prints its number,
   so colour is never the only carrier.
10. **Area opacity 0.35**, higher than the dataviz ~10 % wash, because the operator asked for the
    heatmap blend to read. Light mode reads slightly muddy (tan at mid values); dark mode is
    clean. Easy to tune in `_chart_option`.

## 3. Measurements (reference machine, Python 3.14.4, worktree venvs)

| Measure | Figure | Budget |
|---|---|---|
| `/telemetry/history` over a day of samples (4 980 rows, new budget block) | 23.7 ms median | 50 ms (shell render) |
| Its HTML | 68.1 KB | not budgeted |
| JS in total, heaviest page (now `/telemetry/history`) | 95.2 KB | 120 KB (ADR-0139) |
| `charts.js` | 6.2 KB | inside the total |
| ECharts, by name | 1 095.6 KB | 1 123.05 KB (ADR-0142) |
| Shell render | 2.3 ms | 50 ms |

## 4. What the plan and the kickoff got wrong

* **The worktree setup order fails.** `pip install -e ".[dev]"` in the WeightRoom worktree runs
  before MirrorWall is installed, and `wr-gym` requires `mirrorwall>=0.3.1`, which is not on PyPI
  (0.3.0 is). Install the MirrorWall worktree editable **first**.
* **`charts.js` has a recorded digest** (`src/mirrorwall/static/ASSETS.sha256`,
  `tests/unit/test_assets.py`). Any row editing a MirrorWall asset must update it.
* **A formatter "in the page's JS"** could not serve the chart axes; see decision 2.
* **§1 fact 3 is right, but the history route had one more caller**: the shell strip links the two
  totals too (`ram_total_bytes`, `gpu_vram_total_bytes`), which have no chart of their own now.
  They mark their used figure's chart.

## 5. Found and fixed during the row

* `_marked_figure(None)` matched the first figure whose `total` is `None`, so the CPU chart was
  marked with no `?figure=` at all. Seen in the first screenshot; fixed, and the no-query case is
  now in `test_figure_marks_its_chart_and_a_total_marks_the_chart_it_is_printed_on`.
* The first bar layout put label and value on one line; at 1440 px `1.1 G / 15.9 G` ran into the
  next bar's label. The label now sits above the value and the total prints small and muted.

## 6. Known ceilings, left as they are

* **The charts do not append live points**; only the bars are live. Reload for new history.
* **Hiding the strip while on this page stops the bars**: the toggle's `unwire()` closes the one
  stream the bars read. Loading the page with the strip hidden works (`wire()` connects anyway).

## 7. Proof

Throwaway console on 8807/8808 with its own XDG tree, sampling its own host (no model, no GPU
compute) from 06:35 to 06:47 UTC. Screenshots (session scratchpad,
`/tmp/claude-1000/-home-jpk-ai-suite/a4709a23-a52c-490a-994f-d8c183dc1e33/scratchpad/shots/`):

* `v2-1440-light.png`, `v2-1440-dark.png`, `v2-412-light.png`, `v2-412-dark.png` — eleven
  minutes of real history, no horizontal overflow at either width (`scrollWidth == clientWidth`),
  seven canvases drawn, no console errors but a favicon 404.
* `marked-{1440,412}-{light,dark}.png` — `?figure=gpu_vram_total_bytes` marks the VRAM chart. The
  412 px full-page capture shows the sticky masthead mid-page; that is the capture after
  `scrollIntoView`, not the layout.
* `v1-*.png` — the first pass, showing both bugs in §5.

Tests added: the formatter table (Python and node), the scale table, panels (scale, text, aria,
no colour key anywhere in any option), an unmeasured figure as `—` with no chart, bucketing keeps
peaks and gaps, one `telemetry_samples` read per render, `?figure=` marking (figure, total,
unknown, none), an empty window; MirrorWall: load-scale colours, unit formatter on axis and
tooltip, redraw from the caller's option, format cases.

## 8. Gates

* MirrorWall (`~/ai/worktrees/mirrorwall-wy4/.venv`, Python 3.14.4): `ruff format --check .`,
  `ruff check .`, `mypy src tests` (33 files), `lint-imports` (2 kept), `pytest` — 389 passed,
  1 skipped, 3 deselected.
* WeightRoom (`~/ai/worktrees/weightroom-wy4/.venv`, Python 3.14.4, MirrorWall editable from the
  WY4 worktree): `ruff format --check .`, `ruff check .`, `mypy src tests`, `lint-imports`
  (5 kept), `pytest` — 2066 passed, 3 skipped, 12 deselected. Budgets:
  `pytest -m performance tests/performance/test_budgets.py -k "telemetry_page or javascript or
  echarts or shell_render"` — 4 passed (figures in §3).

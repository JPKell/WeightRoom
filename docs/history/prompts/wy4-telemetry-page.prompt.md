# Kickoff — Row WY4: the telemetry page

**Row:** `WY4` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read §1 fact 3, §2.5 and §5 first. **Written:** 2026-09-12. **Model:** Opus 5 · high. **Wave:** 1.

**Repositories:** MirrorWall, then WeightRoom.
**Worktrees:** `~/ai/worktrees/mirrorwall-wy4` (branch `row/wy4-chart-fill`, from MirrorWall `main`)
and `~/ai/worktrees/weightroom-wy4` (branch `row/wy4-telemetry`, from WeightRoom `main`). The
WeightRoom venv installs MirrorWall **from your MirrorWall worktree**, not from `~/ai/suite`.
**Throwaway console:** 8807, trust 8808.

```bash
git -C ~/ai/suite/py/MirrorWall worktree add ~/ai/worktrees/mirrorwall-wy4 -b row/wy4-chart-fill main
git -C ~/ai/suite/WeightRoom worktree add ~/ai/worktrees/weightroom-wy4 -b row/wy4-telemetry main
cd ~/ai/worktrees/mirrorwall-wy4 && python3.14 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
cd ~/ai/worktrees/weightroom-wy4 && python3.14 -m venv .venv && .venv/bin/pip install -q -e ".[dev]" \
  && .venv/bin/pip install -q -e ~/ai/worktrees/mirrorwall-wy4
```

**Read before code:** ADR-0142 (ECharts vendored; colour is never in `option`), ADR-0139 (the
120 KB JavaScript total), `docs/apps/weightroom/spec.md` §7.7 and §15, `services/telemetry.py`
(`FIGURE_COLUMNS`, `history_rows`, `downsample_and_retain`, `echarts_line_option`,
`sparkline_svg`), `web/routes/system.py` (the page and the SSE stream), MirrorWall `charts.js`,
`telemetry.js` and the `telemetry_meter` and `chart_container` macros. Load the `dataviz` skill
before you write chart code.

## What the operator asked for

* **One page** with a chart for **every** measured figure. The `?figure=` choice goes away.
* **Large bars for the current values** at the top, live.
* **RAM total and VRAM total are values, not charts**: show them with their used figure
  (`18.2 G / 64 G`).
* **Tight, compact and clean.** As much on one screen as possible. **No explanatory text and no
  headers**, apart from each chart's own short label.
* **Large numbers as K, M, G.**
* Line charts **shaded under the line**, the fill coloured **by value: green low, red high,
  blending like a heatmap**.
* **Remove the double**: the inline SVG goes, and so does `sparkline_svg` if nothing else calls it.

## Decisions taken for you

1. **The path stays `/telemetry/history`.** The shell's strip still links
   `/telemetry/history?figure=<name>`; the page accepts `figure`, scrolls to that chart and marks
   it. You do not own `_shell.html`, so do not edit the strip.
2. **Colour stays out of `option`** (ADR-0142). The option carries only a value scale, for example
   a `visualMap` with `min`, `max` and a marker such as `"wr_scale": "load"`. `charts.js` fills in
   the colours at draw time from the theme tokens (success → warning → danger), so both themes stay
   correct. Record this in **ADR-0147, "A chart may map its fill to value, coloured from tokens"**.
   It extends ADR-0142 and supersedes nothing. Add it to `docs/adr/README.md`. If the vendored
   ECharts build lacks `visualMap`, stop and report; do not vendor a new build.
3. **Scales:** percentages 0–100; temperatures on a fixed range stated in `services/telemetry.py`
   (for example 30–95 °C for the GPU); bytes 0–total, using the paired total figure; watts 0 to the
   highest sample in the window, or to the power limit if the telemetry carries one. Put every range
   in one table in `services/telemetry.py`, with a `ponytail:` note wherever a range is a guess.
4. **Units:** bytes binary with the suffixes K, M, G, T (1024-based, shown as `G`, not `GiB`);
   counts SI; `%`, `°C` and `W` unchanged. One formatter in Python and one in the page's JS, tested
   against the same table of cases.
5. **One query, not one per figure.** Read the window once and build every series from it. Measure
   the page: it must not exceed the budget `test_budgets.py` sets for shell pages, and the vendored
   ECharts stays opt-in on this page only.
6. **Accessibility without the double:** each chart's figure gets an `aria-label` that states
   current, minimum and maximum. No second visual chart.
7. **Unsupported is not zero** (ADR-0016). A figure this machine cannot measure shows `—` and no
   chart, not a flat line at 0.

## Layout target

A grid of compact small multiples, about 160 px tall at 1440 px wide, three or four per row, and
one per row at 412 px. Above them, one row of large horizontal bars (CPU %, RAM, GPU %, VRAM,
temperatures, power), updated from the existing SSE stream. Reuse `telemetry.js` or the meter macro
if it fits, and write a small inline script only if it does not. No `<h2>`, no intro paragraph, no
figure selector.

## Proof

Screenshots at 1440 px and 412 px, light and dark, with real history from a throwaway console
reading its own sampler for at least 10 minutes. The console's own sampler runs no model and uses no
GPU compute. Tests: formatter cases, scale table, the option shape (no colour keys in it), one
database read per render, `?figure=` marking, and an unsupported figure rendered as `—`.
MirrorWall's gate and WeightRoom's gate both green, and the JS budget test green.

## Out of scope

`_shell.html` and the telemetry strip, `table.js` (WY5), and every other page.

Finish line, commits, handoff (`WY4_HANDOFF.md` on the WeightRoom branch; the MirrorWall branch head
in it) and report: roadmap §5.

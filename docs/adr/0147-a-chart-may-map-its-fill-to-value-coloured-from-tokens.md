# ADR-0147 — A chart may map its fill to value, coloured from tokens

**Status:** Accepted (2026-09-12)
**Extends:** [ADR-0142](0142-echarts-is-vendored-and-budgeted-by-name.md) — supersedes nothing.
**Relates to:** [ADR-0016](0016-unavailable-is-not-zero.md),
[ADR-0020](0020-server-rendered-html-with-progressive-enhancement.md),
[ADR-0139](0139-the-per-page-javascript-budget-is-a-total-of-120-kb.md).
**Source:** The operator's request list of 2026-09-12 (row WY4,
`docs/roadmap/wy-console-polish-work.md`): line charts shaded under the line, the fill coloured by
value — green low, red high, blending like a heatmap.

## Context

ADR-0142 keeps colour out of an ECharts option: MirrorWall's `charts.js` reads the palette from
the tokens at draw time and redraws on `mirrorwall:themechange`, because a canvas cannot follow a
CSS variable. The option a server builds names data and shape, never a hex value.

The telemetry page now wants a fill whose colour depends on the value it shades. ECharts does that
with a `visualMap` whose `inRange.color` lists the ramp — a list of colours, which is exactly what
ADR-0142 keeps out of the server's JSON. Writing hex values into the option would draw one theme's
greens and reds in the other theme, and would make the server the owner of a palette the tokens
already own.

## Decision

1. **A chart may map its series to value.** The option carries the scale only: a `visualMap` with
   `min`, `max`, the value `dimension` and the marker `"mw_scale": "load"`. It carries no
   `inRange`, no `color` and no other colour key.
2. **`charts.js` colours a `load` scale at draw time** from `--mw-success` → `--mw-warning` →
   `--mw-danger`, low to high, read from the computed style on every draw, so a theme change
   repaints the ramp with the rest of the chart. A `visualMap` without the marker is left as the
   caller wrote it.
3. **The scale is fixed by the figure, not fitted to the data.** A percentage runs 0–100, a
   temperature a stated range, a byte count 0 to its paired total. A fitted scale would paint the
   quietest hour of the day red. Where no bound exists (GPU power, with no power limit in the
   telemetry) the scale runs to the highest sample in the window, and that choice is written beside
   the range in WeightRoomGym's `services/telemetry.py` (`FIGURE_SCALES`).
4. **Units print through one formatter per language.** The option may carry `"mw_unit"`
   (`bytes`, `count`, `percent`, `celsius`, `watts`); `charts.js` prints the value axis and the
   tooltip through `window.mirrorwallCharts.format`, which a page's own live figures also call.
   Its Python twin (`format_figure`) paints the first frame, and one case table tests both.
5. **The status colours carry magnitude here, not state.** They are reserved for status elsewhere
   (UI standards); on a load scale they are the same meaning at finer grain — comfortable,
   pressed, at the limit — and every chart and bar still prints its number, so colour is never the
   only carrier of the value.

## Consequences

* Row WY4's telemetry page draws seven small multiples shaded by value, and its live bars use the
  same three tokens as a CSS gradient, so bar and chart agree in both themes.
* `charts.js` also themes axis rules, axis labels and a tooltip's surface from tokens, replacing
  ADR-0142's `ponytail:` note that the axes were ECharts' own defaults.
* An unavailable reading stays a gap (`null`) in the series and a figure never measured in the
  window draws no chart at all, per ADR-0016 — a value scale does not change that.
* `charts.js` grows by about 3 KB; it loads only on a page that opts into ECharts.

## Alternatives considered

* **Hex values in the option, chosen per theme on the server.** Rejected: the server would need
  the viewer's theme, a `system` theme changes without a request, and ADR-0142's redraw would
  keep the old theme's ramp.
* **A second, WeightRoomGym-side chart initialiser.** Rejected: two modules calling
  `echarts.init` on the same elements, and the token-reading code copied.
* **A plain single-colour area.** What ADR-0142 already allowed; the operator asked for the
  value-mapped fill by name.

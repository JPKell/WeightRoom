# ADR-0142 — ECharts is vendored and budgeted by name

**Status:** Accepted (2026-09-12)
**Supersedes:** [ADR-0139](0139-the-per-page-javascript-budget-is-a-total-of-120-kb.md), for
exactly one library by name — its rule 1 already named ECharts as outside the total (spec §15's
exclusion carried forward from before any chart library existed); this record is what makes that
carve-out real, states the measured size, and reinstates ADR-0138's withdrawn "budgeted by name"
rule for exactly this one library. Every other page's total-JS-budget rule (rule 1's "every
`<script src>` and every inline script, htmx included") is unchanged and ADR-0139 otherwise
stands — this is not a full supersession, and ADR-0139 says so at its own head.
**Relates to:** [ADR-0138](0138-the-per-page-javascript-budget-excludes-the-vendored-libraries-and-names-them.md),
[ADR-0128](0128-mirrorwall-vendors-htmx-and-applications-may-adopt-it.md) (the same vendored,
pinned, opt-in-per-page shape, applied to a second library), row WX6's kickoff and
`docs/roadmap/wx-console-ux-work.md` §1 row WX6.
**Source:** The operator's decision at the WX arc's interview (2026-09-12): vendor ECharts rather
than keep building server-rendered SVG charts by hand.

## Context

MirrorWall's `chart_container()` macro and `charts.css` have carried an inline-SVG chart's classes
(`series-1..6`, `axis`, `label`) since 0.3.0, and `THIRD_PARTY_NOTICES.md` explained the choice:
"No third-party chart library is vendored... A library would add a licence, a checksum to
maintain, and a second colour system to reconcile with the tokens." Spec §15 has, since before
that decision, still budgeted a line for "Charting vendor (vendored, cached) ≤ 1 MB" and excluded
it from the per-page JS total — an exception written for a library that did not yet exist,
inherited unchanged through ADR-0138 and ADR-0139.

Row WX6 vendors one: `chart_container()` gains an `option` parameter (an ECharts option dict);
omitted, the macro is byte-identical to every page rendered before this row. `charts.js`
(previously an empty stub) reads `[data-echarts]`, calls `echarts.init`, and themes the result
from `--mw-chart-1..6` / `--mw-text-muted` / a transparent background read fresh at draw time,
redrawing on `theme.js`'s existing `mirrorwall:themechange` event — a canvas chart cannot restyle
itself from a CSS variable change the way the inline-SVG classes always could.

**The pinned build is the full one, not the smaller `common` build.** ECharts 6.1.0 ships several
UMD bundles; `dist/echarts.min.js` (every chart type, 1 121 883 bytes / 1.07 MiB uncompressed,
367 915 bytes gzipped) is the one row WX6 vendors, because `dist/echarts.common.min.js` (715 020
bytes) has no heatmap component at all, and `docs/roadmap/wx-console-ux-work.md`'s row WX8 already
plans "an ECharts heatmap for the suites view." That makes the full build **71.6 KiB over** spec
§15's stated 1 MB ceiling. This ADR records the overage rather than resolving it by trimming to a
build the very next dependent row would need reversed — a real corner cut on the "precise, not
hard" scope this row was given, flagged in the handoff for the operator to accept, reduce (a
custom webpack-assembled subset, which the suite's "no build step" rule would then apply to a
vendoring step rather than a runtime one — undecided) or wave through.

## Decision

1. **ECharts 6.1.0 is vendored, pinned, offline** — `mirrorwall/static/vendor/echarts/echarts.min.js`
   with its Apache-2.0 `LICENSE` beside it, served with the same content-hash URL every MirrorWall
   asset gets. No CDN, no fetch at runtime (ADR-0020 rule 7), same as htmx.
2. **Opt-in per page, the ADR-0128 shape.** `mirrorwall.echarts` true loads both
   `vendor/echarts/echarts.min.js` and `charts.js`; a page that does not renders exactly as it did
   before this row. WeightRoomGym's own default is **off** (`web/rendering.py`'s global context);
   the one page that opts in today is `/telemetry/history`, per page, not globally — unlike htmx,
   which WeightRoomGym opts every page into at once (design brief §4), most pages have no chart at
   all and gain nothing by loading one.
3. **ECharts is named and budgeted by name, ADR-0138's withdrawn rule reinstated for this one
   library.** `tests/performance/test_budgets.py`'s ECharts case prints its own size on the page
   that loads it and asserts it stays at or under 1 150 000 bytes at the pinned version — headroom
   for the measured 1 121 883 without hiding a real regression, not a rounded-up guess. A MirrorWall
   release that moves the pin re-measures. It stays **excluded** from the 120 KB total ADR-0139
   asserts, which governs the console's own JavaScript, not a vendored library's.
4. **Spec §15's "Charting vendor ≤ 1 MB" row is corrected to the measured figure** (this ADR's own
   text and `docs/packages/mirrorwall/spec.md` §15), the same move ADR-0139 made when htmx first
   measured over its own row's old number.
5. **`THIRD_PARTY_NOTICES.md`'s "Not vendored" paragraph for charting is withdrawn**, replaced by
   an entry under "Vendored runtime assets" in the same shape htmx's entry already has.

## Consequences

* Spec §15's "Charting vendor" row reads "≤ 1 MB; ECharts 6.1.0 measures 1 121 883 bytes (1.07 MiB)
  at row WX6" rather than a bare, now-false ceiling.
* A future row that wants the smaller `common` build for a page with no heatmap chart may vendor a
  second file under `vendor/echarts/`; nothing here forbids it, and nothing here builds it.
* `tests/unit/test_assets.py`'s no-external-request scan gains a `static/vendor/` exclusion (a
  vendored bundle's own namespace-URI constants and licence-header comment are not a runtime
  fetch) — the digest and licence tests carry no such exclusion, so a vendored file still cannot
  ship unrecorded or silently changed.

## Alternatives considered

* **Keep hand-rolled inline SVG charts** (the status quo `THIRD_PARTY_NOTICES.md` defended).
  Rejected by the operator at the WX interview: WX7's per-metric bar charts and WX8's heatmap are
  more chart shapes than another round of hand-written SVG earns back.
* **Vendor `echarts.common.min.js`** (715 020 bytes, under the 1 MB row as written). Rejected here
  because it ships with no heatmap and WX8 is already scheduled to want one; re-vendoring a second,
  larger build later would mean two pinned versions to keep straight rather than one from the
  start. Flagged as the reviewable alternative in the row's handoff.
* **A custom webpack-assembled ECharts subset** (line + bar + heatmap only, likely under 1 MB).
  Not attempted: MirrorWall's own build step is a vendoring step, not the request path, so
  ADR-0020's "no build step" may not even forbid it — but assembling a tree-shaken bundle is more
  than a one-row job, and htmx's own precedent is "download upstream's own file," not "assemble
  one." Left as a real, undecided option for the operator.

## Revisit when

* WX8's heatmap is built and gate-verified against this exact vendored file — if the heatmap
  needs a component the full build's UMD entry does not register, that is this ADR's premise
  wrong, not WX8's bug.
* The operator decides the 1 MB row should bind rather than describe — then the fix is the
  `common` build plus a second heatmap-only bundle loaded only on the page that draws one, not a
  rewrite of this ADR.

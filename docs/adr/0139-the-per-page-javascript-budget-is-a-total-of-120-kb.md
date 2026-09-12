# ADR-0139 — The per-page JavaScript budget is a total of 120 KB

**Status:** Accepted (2026-09-10) — supersedes [ADR-0138](0138-the-per-page-javascript-budget-excludes-the-vendored-libraries-and-names-them.md)
**Superseded-by:** [ADR-0142](0142-echarts-is-vendored-and-budgeted-by-name.md), for ECharts by
name only (2026-09-12) — ECharts is vendored, named, and budgeted by name (excluded from this
record's total, capped on its own); every other page's total-JS-budget rule below stands.
**Relates to:** [ADR-0128](0128-weightroom-adopts-htmx-through-mirrorwall-0-3.md), [ADR-0020](0020-server-rendered-html-with-progressive-enhancement.md).
**Source:** The operator's review of ADR-0138 at row W10, the same day.

## Context

ADR-0138 kept spec §15's 60 KB figure by counting only the console's own scripts and excluding
htmx and its SSE extension by name. The operator chose the plainer rule instead: one number for
everything a page downloads, so the figure a phone sees is the figure the budget governs, with
no list of exclusions to keep honest. The measured state at W10: 89.1 KiB on the heaviest page
(`/apps/freeweight`) — htmx 50.0, its SSE extension 8.7, MirrorWall's modules 21.1, the shell's
inline script 8.6.

## Decision

1. **Every shell page loads at most 120 KB of JavaScript in total** — every `<script src>` and
   every inline script, htmx and its extension included. Only mermaid (a docs page with a fence)
   and ECharts (a telemetry history page) are outside the count, because they load only on the
   page that uses them, as spec §15 has always said.
2. **The test asserts the total and prints the breakdown** (`tests/performance/test_budgets.py`):
   each `<script src>` it counted, the heaviest page's total, and the size of the htmx pair — so
   a MirrorWall release that moves the pin, or a new module, is seen as the number it adds.
3. ADR-0138's "budgeted by name" rule for the excluded libraries is withdrawn with it; the
   headroom (about 31 KiB at W10) is the whole allowance for growth on the shell.

## Consequences

* Spec §15's row reads "≤ 120 KB in total, excluding ECharts and mermaid, which load only on
  pages that use them (ADR-0139)".
* Row WM2 inherits the rule and the test's shape for the four applications' pages.

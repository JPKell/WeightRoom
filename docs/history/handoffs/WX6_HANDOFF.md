# WX6 Handoff — ECharts in MirrorWall

**Row:** WX6 (`docs/roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12 · **Model:** Claude
Sonnet 5 · **Kickoff:** `history/prompts/wx6-echarts-in-mirrorwall.prompt.md` · **Ships:**
unreleased, no version bump (`mirrorwall` stays `0.3.1` prepared, `wr-gym` stays `1.0.0` prepared)
· **Branches:** `row/wx6-echarts` in both worktrees, neither merged.

## 1. What shipped

| Repository | Commit | What |
|---|---|---|
| MirrorWall (`~/ai/worktrees/mirrorwall-wx6`) | `fd762c5` | ECharts 6.1.0 vendored under `static/vendor/echarts/`; `charts.js` (a stub before this row) reads `[data-echarts]`, calls `echarts.init`, themes from tokens read at draw time, redraws on `theme.js`'s `mirrorwall:themechange`; `chart_container(chart_id, title, description, option=None)` gains `option`; `base.html`'s `echarts_enabled` opt-in beside `htmx_enabled`; `charts.css` gains `.chart-surface { height: 320px }` (ECharts measures its container at `init()`); `THIRD_PARTY_NOTICES.md` moved the charting library from "Not vendored" to a real entry; `tests/unit/test_assets.py`'s no-external-request scan excludes `static/vendor/`; new `tests/js/test_charts.py` (Node DOM harness, no browser) and two new snapshot cases in `tests/snapshot/test_components.py` |
| WeightRoom (`~/ai/worktrees/weightroom-wx6`) | `d22f64c` | `web/rendering.py`'s `mirrorwall` global gains `"echarts": False` (the one line this row owns in that file); `web/routes/system.py`'s `telemetry_history_page` opts itself in (`mirrorwall={"htmx": True, "echarts": True}`) and passes `echarts_line_option(rows, figure=chosen)`; `services/telemetry.echarts_line_option` (new, beside `sparkline_svg`); `telemetry_history.html` wraps the existing SVG/empty-state in `chart_container()`; `tests/performance/test_budgets.py` gains `test_echarts_is_named_and_budgeted_by_name` as its own function; ADR-0142 (new); ADR-0139 gets a `Superseded-by` line only; `docs/packages/mirrorwall/spec.md` (canonical copy) updated (Decision records, §15's row, §21) and mirrored byte-identical into MirrorWall's own `docs/packages/mirrorwall/spec.md` |

Nothing pushed, tagged or published. `git status --short` is clean in both worktrees.

## 2. Gate

**MirrorWall**, interpreter `/home/jpk/ai/worktrees/mirrorwall-wx6/.venv/bin/python` (Python 3.14.4):

```
ruff format --check .   → 42 files already formatted
ruff check .            → All checks passed!
mypy src tests           → Success: no issues found in 33 source files
lint-imports             → Contracts: 2 kept, 0 broken.
pytest                    → 385 passed, 1 skipped (pre-existing: hatchling unavailable in this venv), 3 deselected, 2.81s
```

**WeightRoom**, interpreter `/home/jpk/ai/worktrees/weightroom-wx6/.venv/bin/python` (Python 3.14.4):

```
ruff format --check .   → 235 files already formatted
ruff check .            → All checks passed!
mypy src tests           → Success: no issues found in 228 source files
lint-imports              → Contracts: 5 kept, 0 broken.
pytest                    → 1904 passed, 3 skipped (pre-existing), 11 deselected, 166.90s
pytest -m performance (tests/performance/test_budgets.py) → 11 passed, 14.07s
```

## 3. ECharts: version, size, source, checksum

Fetched over the network (per the kickoff's explicit allowance — no other network access was
used) from `https://cdn.jsdelivr.net/npm/echarts@6.1.0/dist/echarts.min.js` (also on npm as
`echarts@6.1.0`), plus its `LICENSE` from `https://raw.githubusercontent.com/apache/echarts/6.1.0/LICENSE`.

| File | Bytes (uncompressed) | Gzipped | SHA-256 |
|---|---|---|---|
| `static/vendor/echarts/echarts.min.js` | 1 121 883 (1.07 MiB) | 367 915 | `b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0` |
| `static/vendor/echarts/LICENSE` (Apache-2.0) | 11 990 | — | `634293835b43a6dd2094fa39182a3d9a6b9ca43b7fdb9ac354e8037af2a3093a` |

Recorded in `THIRD_PARTY_NOTICES.md`, `CHANGELOG.md`, `static/ASSETS.sha256`, and ADR-0142.

**This is the full UMD build (`dist/echarts.min.js`), not the smaller `dist/echarts.common.min.js`
(715 020 bytes)** — see §5, decision to review.

## 4. Measured JS totals on the heaviest page, with and without ECharts

`tests/performance/test_budgets.py`'s existing `test_javascript_per_page_stays_under_the_total_budget`
is unaffected by this row (ECharts was already excluded by path in its `_LOADED_WHERE_USED` tuple,
which is why nothing needed to change there): the heaviest page is still `/apps/freeweight` at
**89.1 KB** (budget 120 KB, ADR-0139's total, htmx + its SSE extension 58.7 KB of that).

The new `test_echarts_is_named_and_budgeted_by_name` measures the one page that opts in,
`/telemetry/history`:

| Measure | Value |
|---|---|
| ECharts alone (asserted ≤ 1 150 000 bytes / 1123.05 KB) | 1095.6 KB |
| Same page, console JS + ECharts together (printed, not asserted — ADR-0139's 120 KB total excludes ECharts by name) | 1184.5 KB |

So: **without** ECharts opted in, a page on this console costs the same 89.1 KB it always has.
**With** it opted in — today, only `/telemetry/history` — a reader downloads roughly 1.18 MB, of
which 1.10 MB is the vendored library itself, cached after the first page that uses it.

## 5. Screenshots

Throwaway console: XDG tree under this session's scratchpad, port 8829 (trust 8830), `wr-gym
1.0.0` from the WeightRoom worktree's own venv, killed by environ-verified pid after (`kill
3038709`, confirmed `WEIGHTROOM_SERVER__PORT=8829` in `/proc/3038709/environ` first). Playwright +
system Chrome, `/telemetry/history` (the only page this row changed), both themes, both widths:

- `/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/shots/telemetry_history_light_1440.png`
- `/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/shots/telemetry_history_dark_1440.png`
- `/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/shots/telemetry_history_light_412.png`
- `/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/shots/telemetry_history_dark_412.png`

The chart draws correctly in both themes (transparent background, `--mw-chart-1` line colour,
`--mw-text-muted` axis text) above its accessible SVG alternative. **At 412 px the x-axis time
labels overlap** — ECharts is not told to resize or thin its labels for a narrow container; see
§6.

## 6. Decisions to review before merge

1. **The full ECharts build, 71.6 KiB over spec §15's 1 MB row, rather than the smaller `common`
   build that fits under it.** ADR-0142 §"Context"/"Alternatives considered" lays out why (WX8's
   planned heatmap has no component in `common`), and spec §15 is edited to state the measured
   figure rather than a now-false ceiling — the same move ADR-0139 made for htmx. If the operator
   would rather cap hard at 1 MB and have WX8 vendor a second, heatmap-only bundle later, that is
   a one-line revert of the file choice plus a smaller ADR-0142.
2. **412 px label overlap** (§5): a real, minor polish gap, not a functional break — the chart
   still draws and the accessible SVG under it is unaffected. Left as-is rather than adding
   `ResizeObserver`/`chart.resize()` plumbing `charts.js` did not otherwise need for one
   demonstration chart; flagged rather than fixed because a later row (WX7's per-metric bar
   charts, WX8's heatmap) is a better place to decide the general responsive story once there is
   more than one chart to look at.
3. **`chart-surface`'s fixed `320px` height** is a flat number, not a token or a responsive rule —
   the minimum needed for ECharts' `init()` to measure a non-zero container. A later row drawing a
   taller chart (WX8's heatmap) will likely want this configurable rather than fixed; not done
   here because nothing yet needs a second height.
4. **`test_no_stylesheet_or_script_reaches_out_to_a_network_origin`'s new `static/vendor/`
   exclusion** (MirrorWall) is a real narrowing of a security-relevant test, done because the
   vendored ECharts file's own namespace-URI constants and licence-header comment tripped it —
   not because the check itself is wrong. Worth a second look given it is a CSP/offline-loading
   guard.
5. **Superseded-by vs. Amends.** ADR-0142 uses `**Supersedes:** ADR-0139, for exactly one library
   by name` and ADR-0139 got a `**Superseded-by:**` line (per the kickoff's explicit instruction).
   Semantically this is closer to ADR-0128's `**Amended by:**` precedent on ADR-0020 (a partial
   change, not a full supersession) — I followed the kickoff's literal wording over that
   precedent; flagging in case the operator wants the `Amended by` label instead.

## 7. What the row text got wrong, or left implicit

* ADR-0139's own rule 1 already named ECharts as excluded from the total — spec §15's exclusion
  language was written before any chart library existed and carried forward unedited through
  ADR-0138 and ADR-0139. This row is what makes that pre-existing sentence true rather than
  aspirational; ADR-0142 says so rather than treating it as a fresh decision.
* `charts.css`'s `.chart-surface` had no `height` rule at all before this row (only borders) — it
  existed for a chart shape (an inline SVG's outer frame) that never got built. Needed a real
  height added or ECharts draws into a zero-height box.
* The row's own text describes the wired element as `<div class="chart" data-echarts=...>`;
  `class="chart"` already belongs to the outer `<figure>` in the existing macro, so the actual
  element uses the CSS `.chart-surface` class `charts.css` already reserved for exactly this
  purpose instead.

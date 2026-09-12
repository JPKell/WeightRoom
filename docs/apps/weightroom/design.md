# WeightRoomGym — Design brief, and the MirrorWall 0.3 system it needs

**Source:** the operator's choice of the **dense dark console** artboard on the 2026-09-09 canvas
(*WeightRoom Shell*, artboard *Dense dark admin console*, 1440 × 900; the light spacious sibling
was not chosen). This page writes that artboard down as a system so that MirrorWall 0.3 (row WM)
can carry the generic parts and the four applications can adopt them in later rows.
**Governing standards:** [UI/UX Standards](../../standards/ui-ux-standards.md) §1 (tokens), §3
(shell), §4 (components), §4.1 (status vocabulary), §7 (accessibility), §9 (theme);
[ADR-0020](../../adr/0020-ui-rendering-strategy.md) (server-rendered, islands, SSE).
**One page.** Numbers are the artboard's; where the artboard and `tokens.css` disagree, the
artboard wins for WeightRoomGym and the delta below is what MirrorWall 0.3 adds.

---

## 1. The register

Grafana/Portainer, not Linear: information-dense, dark-first, tabular numerals everywhere a
number moves, 13 px body, 32 px table rows, one accent, status by dot-plus-word. Light is a
designed palette behind a toggle (UI/UX §9), not the default and not an inversion.

## 2. Token deltas against `mirrorwall/static/css/tokens.css`

The dark palette is **already MirrorWall's dark set** — the artboard uses `#0B1118`, `#111A24`,
`#172230`, `#1D2A39`, `#32425A`, `#5A6E90`, `#F8FAFC`, `#A9B6C6`, `#94A3B8`, `#6BA6F5`,
`#93BEF8`, `#16283D`, `#4ADE80`, `#FBBF24`, `#2DD4BF` exactly. What changes is scale, density and
a few names:

| Token | 0.2.2 | 0.3 | Why |
|---|---|---|---|
| `--mw-font-size-base` *(new)* | 14 px implicit | **13px**, with `--mw-font-size-sm: 12px`, `--mw-font-size-xs: 11px`, `--mw-font-size-title: 18px`, `--mw-font-size-figure: 22px` | the artboard's body/label/heading/figure scale |
| `--mw-row-h` | 36px | **32px** | dense tables |
| `--mw-row-h-comfortable` *(new)* | — | 36px | the four applications keep their current density until they adopt |
| `--mw-header-h` | 48px | 48px | unchanged |
| `--mw-telemetry-h` | 34px | 34px | unchanged |
| `--mw-sidebar-w` *(new)* | — | **200px** | the left menu |
| `--mw-font-data` | SFMono/Consolas/Menlo | **"JetBrains Mono"** first, vendored, then the existing stack | the artboard's mono; vendored per ADR-0020 (no CDN) |
| `--mw-label-tracking` *(new)* | — | `0.04em`, uppercase, `--mw-font-size-xs`, `--mw-text-subtle` | table headers, card labels, menu section titles |
| `--mw-status-ok / -degraded / -stopped / -unknown` *(new)* | — | `--mw-success` / `--mw-warning` / `--mw-text-subtle` / `--mw-border-strong` | the dot vocabulary (§3) |
| `--mw-meter-h` *(new)* | — | 6px, radius 3px, track `--mw-surface-alt` | the telemetry meter |
| `--mw-accent-soft` | `#E8F1FF` / `#16283D` | unchanged; now also the **selected** background for tabs, menu items and pills | one selected colour |
| `--mw-surface-hover` | | unchanged; row hover | |

Light values for the new tokens derive from the existing light palette (`--mw-status-stopped`
→ `--mw-text-subtle` `#6B7787`, etc.); every new pair is added to the contrast test in both
themes (Gold Standards G17).

## 3. Status-dot vocabulary

Four words, four colours, one shape — an 8 px dot beside a word, never the dot alone (UI/UX §4.1):

| Word | Meaning | Token |
|---|---|---|
| `ok` | running and healthy (`/health` 200, every component ok) | `--mw-status-ok` (green) |
| `degraded` | running, a component degraded (LoadCoach unreachable, TLS expiring, evidence stale) | `--mw-status-degraded` (amber) |
| `stopped` | unit inactive, or not installed | `--mw-status-stopped` (subtle grey) |
| `unknown` | cannot tell — no systemd, no response, no schema | `--mw-status-unknown` (border-strong grey-blue) |

Used on the app tabs (top bar), the Overview pill (`running · 2 h 14 m`), the residency column
(`● GPU 0`), and the alerts count (amber when > 0). The existing `queued`/`running`/`failed`…
vocabulary for runs and jobs is unchanged and sits beside it.

## 4. Shell

```text
┌ 48 px ─ WeightRoomGym ─ [● FreeWeight] [● LoadCoach] [● IdeaPress] [● PromptCadence] … Chat Docs Database Jobs ⚠1 │ JK jordan ┐
├ 34 px ─ GPU ▮▮▮▮▯ 61%  VRAM ▮▮▮▮▮▯ 11.2 / 16.0 GB  TEMP 63°C  POWER 148 W  RAM ▮▮▯ 9.4 / 30 GB  RESIDENT ollama/… ctx 8192  QUEUE 2 active · 0 waiting … 1 s ┤
├ 200 px left menu ─┬───────────────────────────────────────────────────────────────────────────────────────────────┤
│ LOADCOACH         │ Overview  [● running · 2 h 14 m]                     [Refresh models] [Restart] [Route explain…] │
│ Overview          │ ┌ JOBS TODAY ┐ ┌ SPEND TODAY ┐ ┌ EVIDENCE ┐ ┌ BREAKERS ┐   four figure cards, 22 px mono figure  │
│ Models            │ ┌ Models · 11 discovered · 9 enabled ─────────────────────────────────── filter… ┐             │
│ Routing           │ │ 32 px rows, uppercase 11 px headers, mono data columns, hover row                │             │
│ Queue …           │ └──────────────────────────────────────────────────────────────────────────────────┘             │
│ ─────             │ ┌ Log · journalctl --user -u loadcoach · live ─────────────────────────────────────┐             │
│ Settings …        │ │ 12 px mono, time in subtle, level-coloured event name                             │             │
│ loadcoach 1.3.0 · :8766 (footer, 11 px mono, subtle)                                                                 │
```

* **Top bar:** brand at 14 px/600; app tabs are `[dot][name]` with the selected tab on
  `--mw-surface-alt` and a 2 px accent underline (`box-shadow: inset 0 -2px`); the alerts entry
  turns amber with a count; the operator chip is a 24 px initials circle on `--mw-accent-soft`.
  The console's own pages (Chat, Docs, Database, Jobs, …) were ghosts here until row WX3, which
  moved them into the left menu as two sections (*Console*, *Tools*) appended under whatever menu
  a page already has: in the top bar they folded into a *Menu* dropdown below 1080 px, so which
  pages existed depended on the window's width. The top bar now collapses once, at 860 px, and
  only the application tabs move.
* **Telemetry strip:** mono 12 px, label in `--mw-text-subtle`, meter (§5) then value in
  `--mw-text`; the resident model and queue as text; the interval at the right edge. Values
  update in place without layout movement (UI/UX §3).
* **Left menu:** section title in the label style, 7 px/10 px items with a 6 px radius, the
  selected item on `--mw-accent-soft`, a 1 px rule between the application's pages and its
  administrative pages, then the console's own *Console* and *Tools* sections (row WX3), the
  version/port footer.
* **Main pane:** 20 px/24 px padding, 16 px gaps, an `h1` at 18 px/600 with the status pill and a
  right-aligned action group (ghost, ghost, primary).

## 5. Components WeightRoomGym needs that MirrorWall 0.2.2 lacks

| Component | What it is | Lives in |
|---|---|---|
| **App tab** | `[dot][label]` top-bar tab with selected state and an `aria-current` | **MirrorWall 0.3** — every application gains a tab strip once it links to its peers |
| **Status dot** | the 8 px dot + word from §3, `data-status` driven | **MirrorWall 0.3** |
| **Telemetry meter** | the 6 px track/fill bar with label and value, `--mw-meter-h`; the strip macro gains meters | **MirrorWall 0.3** (extends `telemetry_bar`) |
| **Figure card** | label / 22 px mono figure / 12 px note; the artboard's four-up | **MirrorWall 0.3** (extends `card`) |
| **Dense table** | `table` at `--mw-row-h` 32 px with the uppercase header style and mono data columns by `data-kind` | **MirrorWall 0.3** (a `density="dense"` argument on `table`) |
| **Log pane** | a bounded, auto-scrolling, mono list fed by SSE with level colouring, pause, and a *dropped N lines* frame | **MirrorWall 0.3** — LoadCoach's and FreeWeight's run pages want the same |
| **Left menu** | the 200 px sectioned menu with selected state and footer | **MirrorWall 0.3** (a `side_nav` macro; applications with one section use it too) |
| **DB grid** | paginated/sortable/filterable grid with typed columns, row selection and a locked-table treatment | **WeightRoomGym** — the guard vocabulary is WeightRoomGym's |
| **Chat thread** | messages, streamed markdown with copy, the collapsible thinking block, inline plan/step/tool/egress/approval cards | **WeightRoomGym** — one consumer |
| **Markdown article** | rendered docs with a heading outline, rewritten links, mermaid mount | **WeightRoomGym** — one consumer |
| **Guard dialog** | the five-condition checklist with live verdicts and the typed-name field | **WeightRoomGym** |
| **Re-auth prompt** | the password re-entry modal for security actions | **WeightRoomGym** — until a second application needs one |

Swaps and SSE regions in every component above are **htmx** attributes (`hx-get`, `hx-swap`,
`sse-connect`, `sse-swap`), vendored by MirrorWall 0.3 and opt-in per page
([ADR-0128](../../adr/0128-mirrorwall-vendors-htmx-and-applications-may-adopt-it.md)); what is
*behaviour* — the log pane's bounded buffer, the thinking collapse, code copy, the guard's typed
name — stays a small ES module on a `data-` element.

The rule for the split is [ADR-0011](../../adr/0011-shared-package-boundaries.md)'s: two
consumers or a clearly generic primitive go to MirrorWall; one consumer stays here and is written
package-shaped so a move is a move.

## 6. What the four applications adopt later

**Adopted at row WM2 (2026-09-10)** — `history/handoffs/WM2_HANDOFF.md`: each application opts in on
the pages named below, and the tab strip renders only when its `[console] url` names the console.

Rows after this arc: the 13 px scale and 32 px rows behind `data-density`, the status dot on their
health pages, the meters in their telemetry bars, the log pane on run/job pages, the top-bar tab
strip linking to WeightRoomGym and to each other. Nothing in MirrorWall 0.3 changes an application's
rendering until it opts in — the new tokens are additive and `--mw-row-h` keeps its value under a
`data-density="comfortable"` root attribute that 0.3 sets by default for a page that does not
declare dense.

## 7. Accessibility and motion

Every dot has a word; every meter has `role="meter"` with `aria-valuenow`/`min`/`max` and a text
value; the log pane announces pauses, not lines; the thinking block is a `<details>` with a
summary; contrast for every new pair is asserted in both themes; transitions 120–180 ms and none on
the strip (UI/UX §10).

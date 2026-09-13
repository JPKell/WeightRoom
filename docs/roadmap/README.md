# Roadmaps and work files

**Since 2026-09-09 each arc the operator starts has its own work file** in the master-table shape
(`# | Phase → ships | Model · effort | Runs after | Work overview — and required reading | Why this
model`), with the same status marks, the same `docs/history/handoffs/<ROW>_HANDOFF.md` rule and one kickoff
prompt per row under `docs/history/prompts/`. A person opening this directory sees the arcs first.

## Work files — the schedules

| File | Arc | Started | Status |
|---|---|---|---|
| [`weightroom-work.md`](weightroom-work.md) | **WeightRoomGym** — the fifth application, the host operator's console (rows W0–W10, WS1–WS4, WM, WM2, and the WP arc: WP1–WP6, WPC1, WPF1–WPF8) | 2026-09-09 | W0–W9, WS1–WS4, WM, WA1, WI1 done; W10 built 2026-09-10 (`1.0.0` prepared), its Gate D verification the operator's; WM2 done 2026-09-10 (versions held). **The WP arc** (every application tab at parity): WP1–WP5 and WPC1 done 2026-09-10/11; **WP6's verification, 2026-09-11: *not ready*** (`history/handoffs/WP6_HANDOFF.md`); rows WPF1–WPF8 scheduled from its findings and run in three waves 2026-09-11/12 — **WPF1–WPF8 all done and merged** (2026-09-11/12); WPF8's Gate B raised one new row, **WPF9** (a reasoning juror spends its whole output budget and answers nothing), not run |
| [`wx-console-ux-work.md`](wx-console-ux-work.md) | **WX** — the console experience arc: the operator's 2026-09-12 request list (sixty items over the five tabs) grouped by collision into rows WX1–WX14, four waves | 2026-09-12 | Planned 2026-09-12 after four surveys; **all fifteen rows done and merged 2026-09-12/13** (`history/handoffs/WX_HANDOFF.md`); WX13's live provider switch and the vLLM kind are the operator's follow-ups |
| [`wy-console-polish-work.md`](wy-console-polish-work.md) | **WY** — the console polish arc: the operator's second 2026-09-12 request list (21 items) as nine build rows in two waves plus one merge row (WY1–WY10) | 2026-09-12 | Planned 2026-09-12; **all ten rows done and merged 2026-09-13** (`history/handoffs/WY_HANDOFF.md`); the column-resize defect on wide tables, FreeWeight's schema 0011 unknown to the console and the PyPI-installed production venvs are the operator's follow-ups |
| [`outstanding-work.md`](outstanding-work.md) | The PromptCadence arc (M10–M13), the Adapter arc (LA0–LA3), M9 and the follow-up rows A1–N6 — every row before the per-arc convention | 2026-09-02 | All rows done by 2026-09-09; keeps the index of arc files in its §1.2 |

## Roadmaps — the rationale

| File | Contents |
|---|---|
| [`master-roadmap.md`](master-roadmap.md) | Milestones M1–M9, dependency graph, work streams, the version trajectory, §9 the current state of every component |
| [`promptcadence-roadmap.md`](promptcadence-roadmap.md) | M10–M13: the harness and its four packages — decisions D-1…D-13 (ADRs 0045–0057) |
| [`adapter-roadmap.md`](adapter-roadmap.md) | LA0–LA3: hot-swappable LoRA serving — decisions A-1…A-10 (ADRs 0058–0067) |
| [`model-assignment.md`](model-assignment.md) | Which model and effort per phase, what makes a phase hard, the one-model rule (§3.5), the overnight rules (§2.12) |

The WeightRoomGym arc has no separate roadmap document: its rationale is ADRs 0123–0128 and
[`apps/weightroom/`](../apps/weightroom/spec.md), and its work file's preamble says so.

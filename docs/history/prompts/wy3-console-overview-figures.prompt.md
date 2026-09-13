# Kickoff — Row WY3: the console Overview shows each application's live figures

**Row:** `WY3` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read §1 fact 2, §2.1, §2.4, §4 and §5 first. **Written:** 2026-09-12. **Model:** Sonnet 5 · high.
**Wave:** 2.

**Repository:** WeightRoom. **Worktree:** `~/ai/worktrees/weightroom-wy3`, branch
`row/wy3-overview`, from **WY1's gate A commit** (§2.4). **Throwaway console:** 8805, trust 8806.

```bash
BASE=$(git -C ~/ai/suite/WeightRoom log row/wy1-shell-nav --grep='row WY1 gate A' -1 --format=%H)
test -n "$BASE" || { echo "WY1 gate A not committed yet — stop"; exit 1; }
git -C ~/ai/suite/WeightRoom worktree add ~/ai/worktrees/weightroom-wy3 -b row/wy3-overview "$BASE"
cd ~/ai/worktrees/weightroom-wy3 && python3.14 -m venv .venv
S=~/ai/suite/py
.venv/bin/pip install -q -e $S/BaseAiCore -e $S/SetSpec -e $S/WeightsDB -e $S/MirrorWall \
  -e $S/SweatMeter -e $S/ModelRack -e "$S/LoadLedger[sql]" -e ".[dev]"
.venv/bin/pip list --editable   # all seven suite packages from ~/ai/suite/py, plus wr-gym
```

**Install the suite packages from `~/ai/suite`, never from PyPI.** PyPI does not have the versions
WeightRoom needs (`mirrorwall 0.3.1` is unpublished, and the rest have unreleased commits on
`main`). Use the one command above, so that pip never fetches a PyPI copy. Before any gate, confirm
that every suite package imports from `~/ai/suite/py/…`, not `site-packages`. Do not change a pin to
make an install resolve: stop and report the error instead. Details are in roadmap §5.

**Read before code:** `services/overview.py` (all of it, especially `_STATUS_FIGURES` and
`overview_for`), `web/routes/shell.py`, `shell.html`, `history/handoffs/WPF6_HANDOFF.md` (the
Overview budget and why `DatabaseUrlCache` exists), `tests/performance/test_budgets.py`, and
ADR-0016.

## What the operator asked for

The console's `/` shows:

* **LoadCoach:** Active, Oldest queued, Starving.
* **PromptCadence:** Executing, Planning, Pending (approvals).
* **FreeWeight:** a summary: Active run, Queue depth, Disk headroom (the three figures
  `_STATUS_FIGURES` already names for FreeWeight).

## Build

1. **Reuse, don't re-read.** Extract the part of `services/overview.py` that turns one application's
   `/system/status` body into its `_STATUS_FIGURES` into a public function, for example
   `status_figures(app, *, settings, client) -> tuple[Figure, ...]`, and have `overview_for` call it.
   The per-application Overview pages must render byte-identically before and after: prove it with
   their existing tests plus one snapshot comparison.
2. **One status read per application, concurrent, bounded.** The three `/system/status` calls run
   concurrently (a thread pool or `httpx` with a short per-call timeout, following the pattern
   already in this codebase). Never open a database or run `config show` for them. Measure `/` before
   and after, on this machine, with the live applications. If `test_budgets.py` has no case for `/`,
   add one with a fixture transport. It must not fake the slow part (WPF6 lesson): delay the fake
   transport realistically.
3. **Down is not zero** (ADR-0016). If an application is stopped, not installed or not answering,
   its group shows its pill and `—` for every figure, with the reason in a `title`. Never `0`.
4. **Layout.** Keep the Applications table. Above it, one compact card row per application (three
   figures each), with the application's name linking to its tab. At 412 px the groups stack. Units:
   *Oldest queued* is a duration (`duration_human`) and *Disk headroom* is bytes (K/M/G).
5. Convert `shell.html`'s link strip to `page_nav`. *Applications*, *Logs*, *Ollama* and *Trust* are
   all in the left menu, so the bar is probably empty and not rendered. Remove the `Bind`,
   `Certificate` and `Operator` cards only if they duplicate something now on the page; otherwise
   keep them. State what you did in the handoff.

## Tests

`status_figures` for each application against the recorded status fixtures
(`tests/fixtures/status`); an application down renders `—`; the three calls are concurrent (a fake
transport whose calls each sleep 300 ms: `/` renders in well under 900 ms); the per-app Overview
pages are unchanged; the page-nav duplicate test passes on `/`. Screenshots of `/` at 1440 px and
412 px, light and dark, with the live applications, and with one application stopped (use a
throwaway config that points one base URL at a closed port; never stop a real unit).

## Out of scope

The per-application Overview pages' layout, IdeaPress figures (not asked), and any file §4 gives to
another row.

Finish line, commits, `WY3_HANDOFF.md` and report: roadmap §5.

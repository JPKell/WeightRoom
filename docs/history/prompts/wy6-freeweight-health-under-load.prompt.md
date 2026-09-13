# Kickoff — Row WY6: FreeWeight's health check times out, and the console calls it down

**Row:** `WY6` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read §1 fact 7 and §5 first. **Written:** 2026-09-12. **Model:** Opus 5 · high. **Wave:** 1.

**Repository:** FreeWeight (and WeightRoom only if the diagnosis puts the cause there).
**Worktree:** `~/ai/worktrees/freeweight-wy6`, branch `row/wy6-health-under-load`, from FreeWeight
`main`. If needed, `~/ai/worktrees/weightroom-wy6` on branch `row/wy6-alert-probe`. **Your own
FreeWeight:** `freeweight serve` on 127.0.0.1:18765 with the **fake provider** and its own XDG tree
under your scratchpad.

```bash
git -C ~/ai/suite/FreeWeight worktree add ~/ai/worktrees/freeweight-wy6 -b row/wy6-health-under-load main
cd ~/ai/worktrees/freeweight-wy6 && python3.14 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
```

Follow the install notes in FreeWeight's README for editable suite packages (SetSpec from `main` is
editable, per the WA1 note).

## The symptom, verbatim

```
application down  freeweight.service  2026-09-13T02:10:36.946Z  2026-09-13T02:11:12.542Z  cleared
running; /api/v1/health answered ReadTimeout: timed out
```

The operator says there are **many** of these.

## Diagnose first — no fix before evidence

Load the `caveman:investigate-first` skill. Rank the hypotheses with evidence:

1. **Event-loop blocking.** `web/routes/system.py` `health` is `async def` and calls the synchronous
   `get_health_report`, which calls `provider.health()` (HTTP to Ollama or llama-server) and reads
   the database. While it runs, and while **any other** `async def` handler does synchronous work,
   the whole loop is stalled. WeightRoom's probe allows 5 s (`WeightRoom/src/weightroom/services/alerts.py`,
   `_HTTP_TIMEOUT_SECONDS`).
2. **The provider's health call is slow** during a run (llama-server busy, Ollama loading), and
   FreeWeight's own timeout on that call exceeds 5 s.
3. **Database contention** during a run (SQLite writer lock, a long transaction).
4. **Process pressure**: the unit's memory cap and swap (see the 2026-09-09 OOM notes), or CPU
   starvation from a benchmark.
5. **The probe's side**: WeightRoom's alert loop and how often a single timeout fires `app_down`
   (ADR-0137 rule 5).

Evidence you may gather read-only: `journalctl --user -u freeweight -u weightroom` around every
`app_down` firing (the WeightRoom alerts API `GET 127.0.0.1:8769/api/v1/alerts`, or its database
read-only); FreeWeight run history for the same windows (did a run, a refresh or a judge overlap each
firing?); `systemctl --user show freeweight` memory and CPU figures. Correlate: how many firings, and
what was FreeWeight doing at each one?

Reproduce on **your own** FreeWeight with the fake provider. Make the fake provider's `health()`
slow, or block a handler synchronously, and show `/api/v1/health` exceeding 5 s under a concurrent
request. No GPU and no real provider.

## Fix where the cause is

* If it is hypothesis 1: the smallest correct fix is probably `def health` (FastAPI runs it in the
  threadpool), plus a bound on the provider call inside the health report. Grep **every** `async def`
  route in FreeWeight that does synchronous I/O. Fix those on the paths that run during benchmarks,
  and list the rest in the handoff. Do not rewrite the app to async.
* If it is 2 or 3: bound that component's check so a slow provider or a locked database reports
  `degraded` quickly instead of hanging the response. Graceful Degradation §3 already says a
  provider can never make the application unavailable.
* **Do not silence the alert** by raising WeightRoom's timeout or adding a retry, unless the evidence
  shows the probe itself is wrong. That would change ADR-0137 rule 5: write ADR-0148 first and flag
  it for review in your report.
* The same pattern may exist in LoadCoach, IdeaPress or PromptCadence. Check with one grep each,
  **report** what you find, and change nothing there.

## Proof

A regression test that fails before the fix: `/api/v1/health` answers inside 1 s while a slow
provider health or a blocked handler is in progress. Before and after timings from your own
FreeWeight. The correlation table of real firings against FreeWeight activity. FreeWeight gate green,
interpreter named. `CHANGELOG.md` under `## [Unreleased]`.

## Out of scope

Restarting `freeweight.service` (WY10 or the operator does it), any GPU work, and every console
page.

Finish line, commits and report: roadmap §5. The handoff content goes in your report, unless you
opened a WeightRoom worktree, in which case `WY6_HANDOFF.md` goes on that branch.

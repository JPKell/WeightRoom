# WY6 Handoff — FreeWeight health under load

**Row:** WY6 in [`roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md) ·
**Ran:** 2026-09-12 · **Model:** Opus 5 · high · **Kickoff:**
`history/prompts/wy6-freeweight-health-under-load.prompt.md` · **Repository:** FreeWeight only
(the diagnosis did not put the cause in WeightRoom, so no `row/wy6-alert-probe` branch exists).
**Branch:** `row/wy6-health-under-load`, worktree `~/ai/worktrees/freeweight-wy6`, commit
`a502bdb`. Merged by WY10 (see [`WY_HANDOFF.md`](WY_HANDOFF.md)).

**Filed by WY10.** The row put its handoff in its agent report, as its kickoff said, and that report
did not reach the WY10 session verbatim. This file is rebuilt from the commit message, the
`CHANGELOG.md` block, the code and tests on the branch, and the row's note in the operator's
session memory. Where a figure comes from WY10's own re-run, it says so.

## 1. Cause — proven, and not the plan's hypothesis

The roadmap's leading hypothesis (§1 fact 7) was load: an `async def` route doing synchronous work
on the event loop while FreeWeight was busy. The evidence says otherwise.

* WeightRoomGym had raised `app_down` for FreeWeight **393 times** since 2026-09-10. Every one was
  `ReadTimeout: timed out` on `GET /api/v1/health`, and every one happened while FreeWeight was
  **idle** — none during a run.
* ModelRack `LlamaCppProvider.health()` calls `_entries()`. When ModelRack's `MetadataCache`
  expires (300 s), `_entries()` re-parses every GGUF header in the model directory: **5.5 s for 27
  files** in `~/ai/models/llm`. The health check then answers after about 5.9 s.
* The WeightRoom probe runs about every 31 s and allows 5 s (`alerts.py`
  `_HTTP_TIMEOUT_SECONDS`), so roughly every tenth probe lands on an expired cache and times out.
  WY10 counted the console's alert rows on 2026-09-13: 11–12 FreeWeight `app_down` openings per hour,
  one about every 5.3 minutes, which matches the 300 s TTL plus probe spacing.
* Ruled out: the database integrity check (12 ms), memory and swap pressure.

## 2. Fix

* `services/health.py`: `get_health_report(..., provider_timeout_seconds=None)`. With a bound, the
  provider check runs in a daemon thread. If it has not answered in time, the `provider` component
  is `degraded` with *"provider health check did not answer within 0.5 s"*. The thread keeps
  running, so the cache is warm for the next probe. `None` (the CLI `freeweight health` and
  `doctor`) still waits for the full answer.
* `web/routes/system.py`: `PROVIDER_HEALTH_TIMEOUT_SECONDS = 0.5`, passed by `/api/v1/health` and
  the `/system` page. `/api/v1/health`, `/api/v1/system/status` and `/system` are now plain `def`
  routes, so FastAPI runs them in its threadpool and a slow check no longer stalls other requests.
* The alert was **not** silenced: WeightRoom's 5 s timeout and its lack of retry are unchanged.
  A late provider is reported as `degraded` (HTTP 200), which is what it is; a dead FreeWeight still
  fires `app_down`.
* No health semantics changed beyond a new `degraded` detail, so ADR-0148 (reserved) was not used.
* Test: `tests/e2e/test_health_under_load.py`.

## 3. What the plan got wrong

* **The hypothesis.** It was not load and not the event loop in the first place; it was an idle
  cache expiry in ModelRack. Taking the routes off the event loop is still right and shipped, but
  it is not what fixed the alert.
* Route docstrings are the OpenAPI description, and `docs/openapi.json` is a snapshot test.
  Implementation notes belong in comments, not docstrings.

## 4. Not fixed — follow-ups for the operator to schedule

1. **ModelRack**: the GGUF header re-parse itself. A cache entry whose file stamp still matches
   should survive the TTL instead of being re-read.
2. **LoadCoach**: `async def health` has the same pattern and calls `provider.health()` without a
   bound.
3. **FreeWeight**: `machines_page`, `set_enabled` and `provider_form` still do synchronous database
   work inside `async def` routes.
4. The one daemon thread per timed-out check is marked `ponytail:`; share one in-flight check if
   they ever pile up.

## 5. Gate

Row's own report: green. **WY10 re-run** in the worktree, after reinstalling its venv so every suite
package is editable from `~/ai/suite/py` (it had `baseaicore`, `weightsdb`, `sweatmeter` and
`modelrack` from PyPI): see `WY_HANDOFF.md` §3 for the lines.

# WX1 Handoff — Kit pass

**Row:** WX1 (`roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12, unattended, one sitting ·
**Model:** Claude Sonnet 5 · **Kickoff:** `history/prompts/wx1-kit-pass.prompt.md` (arc preamble at
the top of `wx-console-ux-work.md`) · **Branch:** `row/wx1-kit-pass` in
`~/ai/worktrees/weightroom-wx1` · **Not merged.**

## 1. What shipped

One commit (see §4 for the exact head), WeightRoom only, 51 files:

- **`_app_state.html:16` and `apps.html:29`**: the process-control form's class changed from
  MirrorWall's `.field` (a form field — `flex-direction: column`, stacked full-width buttons) to
  the page kit's `.kit-actions` (already defined in `_shell.html`: `flex; flex-wrap: wrap; gap:
  4px`, auto-width buttons). This is the only change needed — `.kit-actions` already existed and
  is already used elsewhere (`fw_goals.html`, `ip_project.html`, `_lc.html`, …); no new CSS. Fixes
  all four Overviews (`_app_state.html` is shared) and the Applications table's Actions column.
  Verified with a static before/after proof (`.field` vs `.kit-actions` on identical markup,
  screenshotted) since the throwaway console's units are never installed (no `wr-gym units sync`,
  which this row may not run) so the live Overview always shows the "not installed" branch, never
  the three-button form.

- **The table kit pass**, mechanically, across every `table()` call in `fw_*.html`, `lc_*.html`,
  `ip_*.html`, `pc_*.html`, `audit.html` and `docs_adrs.html` (45 of those 58 files had at least
  one qualifying call): `sortable=true` plus a page-unique `table_id="<app>-<page>[-<n>]"` where
  the call's `complete` argument is not the **literal** `false` — i.e. every call left at the
  macro's own default (`complete=True`), an explicit `complete=true`, or a **dynamic** expression
  (`complete=next_href is none`, `complete=not has_more`, …) that can be true at render time. A
  call with a hardcoded `complete=false` (a table that only ever shows one page of a longer result:
  `lc_reliability`'s per-window table, `ip_projects`, `lc_evidence`'s bound-records table,
  `pc_ledger`'s debits, `pc_trajectories`, `pc_approvals`, `lc_routing`'s decision history,
  `lc_queue`, `pc_egress`) was left untouched — no `sortable`, no `table_id`. Two files
  (`audit.html`, `docs_adrs.html`) already had their own `table_id`; only `sortable=true` was added
  there. Done with a small paren-matching Python script (not 130 hand edits) that walks every
  `table(` call, skips ones inside quoted strings, and decides per-call from the `complete=`
  keyword text — reviewed by diff afterward, file by file.
  - **Why not gate on `complete` statically for the dynamic cases too**: `table.js`'s own
    `wireSorting` already refuses to wire a header unless the *rendered* `data-complete` attribute
    is `"true"`, and `wireColumnVisibility` doesn't care about completeness at all (it only checks
    header count). So `sortable=true` on a `complete=next_href is none` call is never wrong at
    runtime — a paged render of that same route (page 2 of Results) simply gets no sort buttons,
    exactly per UI standards §5, without the template needing to duplicate that logic. This reads
    the row's "where complete is true" as "wherever it *can* be true", which is what the JS already
    enforces; I did not add a second, static-only reading that would have left dynamically-complete
    tables (Results, Evidence, Samples, the Model page's run history, the Run page) unsortable on
    the common case (one page, nothing to paginate) — **flag if the intended reading was narrower.**
  - I did **not** add "why this table can't be sorted" copy to the untouched `complete=false`
    tables. The row cell's sentence ("a paged table stays unsortable… and the row says so on the
    page, not silently") reads to me as describing the consequence of the existing convention
    (each of those tables already carries a caption saying it's "the first page" or similar, and
    row WX5 is explicitly scheduled to add the cursor/"first N of more" copy this row would have
    duplicated) rather than a new requirement for WX1. **Flag if WX5 shouldn't have to redo this.**

- **Two macros in `_app_page.html`, appended at the end** (per the wave's collision note — WX3
  adds `app_page_header` at the top of the same file): `params_b(n)` (parameter count in billions,
  one decimal, `7.6B`; `active_parameter_count` uses the same macro, not a second one) and
  `context_k(n)` (context window in thousands, `32768` → `32k`; a value that isn't an exact
  multiple of 1024 keeps one decimal, `97.7k`, rather than rounding a real number into a
  round-looking one). Both treat a non-number (`None`, `""`, the literal string `"unsupported"`,
  a bool) as ADR-0016's unsupported sentinel and render the same muted `—` with the same tooltip
  text `_fw.html`'s `value` and `_lc.html`'s `measure` already use, so all three conventions read
  identically on screen. Wired into `fw_models.html` (Parameters, Context columns — replacing
  `value(..., fmt="%d")`), `fw_model.html` (the descriptor kv-list's Parameters/Active
  parameters/Max context, and the descriptor-history table), and `fw_compare.html` (the Subjects
  table's Context column, over `context_size` — the *served* context of that run, not a model's
  maximum, but the same unit and the same formatter). **`lc_models.html`**'s Context column also
  moved to `context_k`.
  - Confirmed live: FreeWeight's real Models page renders `8.2B` / `128k`, `13.5B` / `256k`, etc.
    (curled from the throwaway console against the operator's live FreeWeight); the Compare page
    renders `8k` for a 8192-token served context.

- **`lc_models.html`'s declared-capabilities column** (comma-joined string before) now renders one
  badge per key, via a new `capability_badges(names)` macro in `_lc.html` (next to `mapping_list`,
  same file, same convention — `names` is any iterable of capability-id strings, so it takes the
  model row's `dict.keys()` and the adapter sub-row's plain list without two macros).

- **`settings.html:83-88`**: the three `field-hint` spans (description, range, default) moved out
  of the key's `<th>` into a second `<tr class="field-hint-row">` spanning all four columns,
  self-contained CSS in `settings.html`'s own `{% block extra_head %}` (the established
  per-page-style pattern — `job.html` already does this; I did not touch `_shell.html`, which WX3
  is mid-restyling in the same wave). The description sits in a native `<details><summary>`,
  CSS-clamped to one line (`max-width: 60ch; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap` on the `<summary>`); the full text is a `<p>` inside the `<details>`, shown
  only once the reader clicks (no JavaScript — the browser's own disclosure). Range and default
  are plain `<span>`s beside it, outside the `<details>`, so they never collapse. Confirmed on
  screen: `server.host`'s description clamps to "Interface to bind. Loopback by default; anything
  else requires a valid tls…" with the ellipsis, and "default 127.0.0.1" is fully visible beside
  it, unclamped.

## 2. Gate

WeightRoom `.venv` in the worktree, **Python 3.14** (`.venv/bin/python`):

```
ruff format --check .   → 235 files already formatted
ruff check .            → All checks passed!
mypy src tests          → Success: no issues found in 228 source files
lint-imports            → 5 contracts kept, 0 broken
pytest -q               → 1904 passed, 3 skipped, 10 deselected (158.8s)
```

`git status --short` clean before and after; no stray files.

## 3. Screenshots

Throwaway console on port 8779 (trust 8780), fresh XDG tree under `/tmp/wx1-xdg`, this worktree's
`.venv/bin/wr-gym`. `ss -ltnp` confirmed both ports free before binding. Started and stopped by
verified pid (`/proc/<pid>/environ` showed `WEIGHTROOM_SERVER__PORT=8779` before `kill`), never
`pkill -f`. **This throwaway instance has no per-app configuration of its own, so its default
`[apps.<name>] base_url` points at the same `127.0.0.1:876{5,6,7,8}` the operator's real, running
FreeWeight/LoadCoach/IdeaPress/PromptCadence already listen on** — every screenshot below is a
real read (GET only) of the operator's live data through those apps' own HTTP APIs, exactly as the
kickoff's "may" list permits, not fabricated fixtures. No systemd unit is installed for this
throwaway instance, so every Overview/Applications page shows "not installed" and never the
three-button control form — expected, and the reason for the standalone `.kit-actions` proof
above (§1).

Captured at 1440 px and 412 px, light and dark (Playwright + system Chrome, `weightroom-theme` in
`localStorage`), for every page whose template this row touched, at
`/tmp/wx1-xdg/screens/<page>__<theme>__<width>.png` (192 files, in the worktree host's `/tmp`, not
committed):

`apps, audit, docs_adrs, settings_weightroom, settings_freeweight, settings_loadcoach,
settings_ideapress, settings_promptcadence, fw_models, fw_model, fw_runs, fw_run, fw_results,
fw_compare, fw_evidence, fw_machines, fw_machine, fw_adapters, fw_adapter, fw_dashboard,
fw_system, fw_goals, fw_goal, fw_goal_edit, fw_goal_calibration, fw_goal_report, fw_judges,
lc_models, lc_routing, lc_reliability, lc_evidence, lc_adapters, lc_system, ip_workflows,
ip_units, ip_projects_list, ip_project, ip_plan, ip_task, ip_unit, ip_workspace,
pc_tiers, pc_tools, pc_ledger, pc_system, pc_trajectories_list, lc_queue_list`.

**Not captured, and why** (all data-availability or auth, not template defects — confirmed by the
pytest suite's fixture-driven renders of the same templates):
- `lc_model`, `lc_task_profile`, `lc_job`: this throwaway console has no LoadCoach bearer token
  (documented limitation, `browser-screenshots-for-ui-work` memory), so every LoadCoach page read
  is refused (`UNAUTHORIZED`), and repeated unauthenticated attempts tripped LoadCoach's own
  auth-failure lockout ("too many failed authentications") partway through discovery. I stopped
  hitting LoadCoach once that appeared rather than retry through it — it self-clears, and every
  `lc_*` page below shows LoadCoach's own refusal banner rendered inside the kit chrome (proving
  no crash, not proving the populated table). `lc_models` (list) rendered before the lockout and
  is captured; the two detail pages needing a discovered id did not get the chance.
- `pc_trajectory`: no trajectory currently exists on the operator's live PromptCadence (confirmed:
  `/apps/promptcadence/trajectories` lists none) — nothing to discover, not a bug.

## 4. Files touched

CHANGELOG.md (one contiguous block, top of `## [Unreleased]`); `_app_page.html` (append-only, two
macros), `_app_state.html`, `_lc.html` (one macro added, `capability_badges`), `apps.html`,
`settings.html`, and the 45 files listed in §1's table-kit paragraph (`fw_adapter.html`,
`fw_adapters.html`, `fw_compare.html`, `fw_dashboard.html`, `fw_evidence.html`, `fw_goal.html`,
`fw_goal_calibration.html`, `fw_goal_draft.html`, `fw_goal_edit.html`, `fw_goal_report.html`,
`fw_goals.html`, `fw_judges.html`, `fw_machine.html`, `fw_machines.html`, `fw_model.html`,
`fw_models.html`, `fw_results.html`, `fw_run.html`, `fw_runs.html`, `fw_sample.html`,
`fw_samples.html`, `fw_system.html`, `ip_plan.html`, `ip_project.html`, `ip_task.html`,
`ip_unit.html`, `ip_units.html`, `ip_workflows.html`, `ip_workspace.html`, `lc_adapters.html`,
`lc_evidence.html`, `lc_job.html`, `lc_model.html`, `lc_models.html`, `lc_reliability.html`,
`lc_routing.html`, `lc_system.html`, `lc_task_profile.html`, `pc_ledger.html`, `pc_system.html`,
`pc_tiers.html`, `pc_tools.html`, `pc_trajectory.html`, `audit.html`, `docs_adrs.html`). No Python
file changed — nothing for `ruff format` to reformat, `mypy` to check beyond what already passed,
or `lint-imports` to re-evaluate; the whole row is templates plus one changelog entry.

**Not touched, deliberately**: `web/rendering.py` (WX3's), `docs/roadmap/*` (out of bounds for
every row), any other worktree, `main`.

## 5. Decisions to review before merge

1. The "where `complete` is true" reading in §1 (sortable added to dynamic-`complete` calls, not
   just static `complete=true` ones) — I'm confident it's correct given how `table.js` gates
   itself, but it's a broader footprint than a literal reading would have given.
2. No "why unsortable" copy added to the untouched `complete=false` tables — left for WX5, which
   already owns the pagination-messaging convention for those exact tables.
3. `context_k`'s base is 1024 (kibi), not 1000, matching the row's own example (`32768` → `32k`
   divides evenly at 1024, not at 1000); `params_b`'s base is 1000000000 per the row's explicit
   `1B = 1e9`. Two different bases in two macros that sit next to each other — intentional, but
   worth a second look.
4. `capability_badges` went into `_lc.html` (new macro) rather than being inlined once in
   `lc_models.html`, on the theory WX9 (LoadCoach tab, wave 2) will want the same rendering for
   the Ability column it's adding to the same table — low cost either way if that's wrong.

Nothing pushed, tagged, merged or version-bumped. Worktree left in place for review; not removed.

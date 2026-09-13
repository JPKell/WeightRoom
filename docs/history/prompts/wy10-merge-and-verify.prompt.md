# Kickoff — Row WY10: merge the WY arc, verify it, close it

**Row:** `WY10` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read the whole file, then every `WY<N>_HANDOFF.md` on the branches and the reports of WY5 and WY6.
**Written:** 2026-09-12. **Model:** Opus 5 · high. **Wave:** 3, after all nine rows have reported.

**Repositories:** FreeWeight, MirrorWall and WeightRoom, **on `main`** in `~/ai/suite/...`. This is the
only WY session that touches `main`. **Throwaway console:** 8817, trust 8818.

## Rules

The standing preamble applies (`weightroom-work.md` §2). **Never push, tag, publish, or bump a
version.** Never `git add -A`. Run `git status --short` in every repository at the start and at the
end; anything modified that you did not edit is the operator's, so stop and report it; do not
overwrite it. `stash@{0}` in WeightRoom stays. No GPU, no `pytest -m live`, and never reset or use the
operator's console password.

## 0. Preconditions — stop if any fails

* WeightRoom `main` is clean (roadmap §0: the operator's eight template edits are committed or
  discarded).
* Every branch named in the roadmap §3 exists, and each row's report says its gate was green.
  Re-run each branch's gate in its own worktree before merging (`ruff format --check .`,
  `ruff check .`, `mypy src tests`, `lint-imports`, `pytest`) and record the interpreter and the
  pass line. A red branch is not merged: report it.
* The branch bases are as planned: wave-2 branches contain WY1's gate A commit
  (`git merge-base --is-ancestor`).

## 1. Merge order

Use `git merge --no-ff`, one merge commit per branch, with the subject
`merge: row WY<N> — <scope> (row/<branch> <short hash>)`.

1. **FreeWeight:** `row/wy6-health-under-load`. Then its gate on `main`.
2. **MirrorWall:** `row/wy5-table-sort`, then `row/wy4-chart-fill`. They touch different files;
   `CHANGELOG.md` conflicts are resolved by keeping both blocks. MirrorWall gate on `main`.
3. **WeightRoom:** `row/wy1-shell-nav` → `row/wy4-telemetry` → `row/wy2-logs-settings` →
   `row/wy3-overview` → `row/wy7-chat-history` → `row/wy8-model-tables` →
   `row/wy9-database-subpages` (and `row/wy6-alert-probe` if WY6 made one). Run the WeightRoom gate
   after **each** merge, not only at the end: a failure is then attributable to one branch.

**Conflict policy:** textual conflicts in shared files (`CHANGELOG.md`, `test_budgets.py`,
`rendering.py`, `weightroom-shell.css`) are resolved by keeping both sides' intent. A semantic
conflict (two rows changing one behaviour in different ways) is **not** resolved by guessing: take
the roadmap's contract (§2) as the tiebreaker, and if the contract does not decide it, stop and
report.

## 2. After the merges — the work only this session can do

1. **Delete `app_page_header`'s caller slot.** `grep -rn "call app_page_header"` must return nothing
   first; convert any survivor to `page_nav`. Then remove the slot and its CSS.
2. **The duplicate rule over the whole site.** Run `tests/integration/test_page_nav.py`. Review any
   rule WY9 added to it. Then look for strips the sweep missed: `grep -rn "page-actions\|kit-actions"`
   in templates. Every remaining hit is either converted or justified in the handoff.
3. **The §2.2 contract end to end:** with WY5 and WY8 both merged, FreeWeight Results and Evidence
   open with runtime profile and machine hidden on a fresh browser profile, and show them after they
   are ticked.
4. **No `/catalog` anywhere:** `grep -rn "/catalog" src tests docs/apps/weightroom` returns only
   ADR-0146 references and the historical-row test; `GET /catalog` is 404.
5. **Budgets on this machine:** `pytest -m performance` in WeightRoom (the JS total of 120 KB, the
   shell CSS, Overview timing, telemetry page timing). Quote the numbers.
6. **Docs:** ADR-0146 and ADR-0147 listed in `docs/adr/README.md`; component doc copies synced where
   CLAUDE.md requires (`cmp`; `WeightRoom/docs/scripts/sync_component_docs.py --check`;
   `FreeWeight/scripts/sync_docs.py --check`); guide copies regenerated for any component README or
   top-level doc a row changed.
7. **The production console actually uses MirrorWall `main`:** check that
   `~/ai/suite/WeightRoom/.venv` imports `mirrorwall` from `~/ai/suite/py/MirrorWall/src` (editable).
   If it does not, report it and do not reinstall.

## 3. Live verification

1. **Restart `weightroom.service`** (the console only, which is safe) so it runs the merged code.
   Restart **`freeweight.service` only if** `GET 127.0.0.1:8765/api/v1/system/status` shows no active
   run and an empty queue; otherwise leave it for the operator and say so.
2. **Browser pass** with Playwright against a throwaway console on 8817 reading the live applications
   over GET (method: `browser-screenshots-for-ui-work.md` in the memory directory). Screenshots at
   1440 px and 412 px, light and dark, of: `/`, `/telemetry/history`, `/logs`, `/settings`, `/chat`,
   `/chat/history`, `/docs`, FreeWeight Models, Results, Evidence and Database (all three subpages),
   LoadCoach Models (sorted on two columns, one column resized) and Queue, and one PromptCadence and
   one IdeaPress page. Check each against the operator's request, item by item.
3. **WY6 in production:** after FreeWeight is restarted (or not), read the console's alerts for the
   next 30 minutes of normal activity, or state plainly that it could not be observed and why.

## 4. Close the arc

* `docs/history/handoffs/WY_HANDOFF.md`: what landed in each repository (merge hashes); what the plan
  got wrong (collect §2 of every row handoff); the merge conflicts and how each was resolved; the gate
  lines and interpreters; the budget numbers; a table mapping every item of
  `wy-operator-request-2026-09-12.md` to done, partial or not done, with the screenshot path; and
  what is left for the operator.
* File WY5's and WY6's report contents as `WY5_HANDOFF.md` and `WY6_HANDOFF.md`.
* Update the roadmap §7 status table and the WY row in `docs/roadmap/README.md`.
* Commit the docs. `git status --short` clean in all three repositories. Remove the WY worktrees
  whose branches are merged (`git worktree remove`; never `--force` on a dirty tree), and keep the
  branches.

**Report:** the merge hashes per repository, the final gate lines, the budget numbers, the
request-item table, and anything waiting on the operator.

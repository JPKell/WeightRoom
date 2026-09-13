# Kickoff — Row WY8: model tables name models, not identities

**Row:** `WY8` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read §2.1, §2.2, §2.4, §4 and §5 first. **Written:** 2026-09-12. **Model:** Sonnet 5 · medium.
**Wave:** 2.

**Repository:** WeightRoom. **Worktree:** `~/ai/worktrees/weightroom-wy8`, branch
`row/wy8-model-tables`, from **WY1's gate A commit** (§2.4). **Throwaway console:** 8813, trust 8814.

```bash
BASE=$(git -C ~/ai/suite/WeightRoom log row/wy1-shell-nav --grep='row WY1 gate A' -1 --format=%H)
test -n "$BASE" || { echo "WY1 gate A not committed yet — stop"; exit 1; }
git -C ~/ai/suite/WeightRoom worktree add ~/ai/worktrees/weightroom-wy8 -b row/wy8-model-tables "$BASE"
cd ~/ai/worktrees/weightroom-wy8 && python3.14 -m venv .venv
.venv/bin/pip install -q -e ".[dev]" && .venv/bin/pip install -q -e ~/ai/suite/py/MirrorWall
```

**Read before code:** `fw_models.html`, `fw_results.html`, `fw_evidence.html`, `lc_models.html`,
their macro files `_fw.html` and `_lc.html` (read only; do not change a macro other templates use,
and add a new macro instead if you need one), `services/freeweight_pages.py`,
`services/loadcoach_pages.py`, ADR-0008 and ADR-0024 (model identity is
`provider/name@sha256:digest`), and the recorded fixtures for the FreeWeight results and evidence
API.

## What the operator asked for

* **FreeWeight Models:** remove the Canonical ID column.
* **FreeWeight Results:** the model column shows the **model name**, not the canonical ID. The
  runtime profile and machine columns are **hidden by default**.
* **FreeWeight Evidence:** the same: the model name, with runtime profile and machine hidden by
  default.
* **LoadCoach Models:** the name takes far too much room. Truncate it after 30 characters.
  (Resizable columns come from WY5, for every table.)

## Decisions taken for you

1. **Where a name comes from, in order:** the row's own display name or provider model name if the
   API gives one; otherwise the `name` part of the canonical ID, parsed with BaseAiCore's
   `ModelIdentity` (never a hand-written split). If a canonical ID does not parse, show it truncated
   rather than raising. The full canonical ID stays available as the link's `title`, and the model
   detail page still shows it. Put the rule in one helper (a Jinja filter registered in
   `rendering.py`, or a function in the pages service) and test it. `rendering.py` is WY1's file, so
   if you need a filter, register it with a one-line additive change and name it in the handoff for
   WY10.
2. **Hidden by default** uses the §2.2 contract: `"hidden": true` on the head entry. Until WY5
   merges, the columns render visible. That is expected: say so in the handoff and prove the markup
   (`data-default-hidden`) with a render test that WY10 re-runs after merging WY5.
3. **Truncation at 30 characters** means 29 characters plus `…`, applied to the display text only,
   with the full value in `title`. Apply it to both lines of the LoadCoach name cell (the name and the
   muted canonical ID under it). Use the existing `cell_text(limit=…)` filter if its ellipsis
   behaviour matches; do not write a second truncator.
4. **Filters stay.** The *Model* filter inputs still accept a canonical ID, ULID or name. The FreeWeight
   Models *Order* select loses its two canonical-ID options only if the API's sort does not need them.
   Check before you remove them.
5. **Page bars:** convert each of the four templates' link strips to `page_nav`. FreeWeight *Results ·
   Compare* are subsections, so they are `links`; *Evidence*, *Runs* and *Machines* are in the left
   menu, so remove them unless the left menu lacks one (Machines has no menu entry, so it is a link).
   *JSON* and *Docs* are `actions`.
6. **Every complete table stays** `sortable=true` with a `table_id` (WX1); check all four.

## Tests

Name derivation (display name wins; canonical parse; an unparseable ID); Models has no Canonical ID
header; the Results and Evidence runtime-profile and machine headers carry `data-default-hidden`; a
41-character LoadCoach name renders as 29 characters plus `…` with the full `title`; the page-nav
duplicate test passes. Screenshots of all four pages at 1440 px and 412 px, light and dark, from the
live FreeWeight and LoadCoach over GET, or from fixtures where a page needs a token.

## Out of scope

`table.js` (WY5), the model detail pages, and any file §4 gives to another row.

Finish line, commits, `WY8_HANDOFF.md` and report: roadmap §5.

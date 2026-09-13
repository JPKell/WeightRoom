# Kickoff — Row WY1: shell navigation, the page bar, and the catalog removed

**Row:** `WY1` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md).
Read that file first: §1 (surveyed facts), §2.1 (the `page_nav` contract, which you write), §4 (file
ownership, which your sweep must respect) and §5 (rules). **Written:** 2026-09-12.
**Model:** Opus 5 · medium. **Wave:** 1.

**Repository:** WeightRoom. **Worktree:** `~/ai/worktrees/weightroom-wy1`, branch
`row/wy1-shell-nav`, from `main`. **Throwaway console:** 8801, trust 8802.

```bash
git -C ~/ai/suite/WeightRoom worktree add ~/ai/worktrees/weightroom-wy1 -b row/wy1-shell-nav main
cd ~/ai/worktrees/weightroom-wy1 && python3.14 -m venv .venv
.venv/bin/pip install -q -e ".[dev]" && .venv/bin/pip install -q -e ~/ai/suite/py/MirrorWall
```

**Read before code:** `docs/apps/weightroom/spec.md` §7 (pages; §7.9 catalog), `design.md` §4,
`history/handoffs/WX_HANDOFF.md` §2, the WX3 section of `wx-console-ux-work.md` (the left-menu
decision you are partly reversing), `web/rendering.py`, `web/templates/_shell.html`,
`_app_page.html`, ADR-0137 (alerts) and ADR-0134 (audit).

## Why this row goes first

Five wave-2 rows branch from your **gate A** commit. Keep gate A small and land it first.

## Gate A — the page bar exists (commit subject must contain `row WY1 gate A`)

1. Write `page_nav(links=(), actions=())` in `_app_page.html` exactly as §2.1 specifies, with its
   CSS in `weightroom-shell.css`. Write the docstring first.
2. Write `tests/integration/test_page_nav.py`. It renders every GET UI route that the existing
   fixtures can render and asserts that no `nav.page-nav` href appears in that page's
   `nav.side-nav`. Discover the routes from the app's route table, not from a hand list, so a page
   added later is covered. A route that cannot render from fixtures is listed in the test with the
   reason; there is no silent skip.
3. Remove the two `/catalog` links from `fw_models.html` and `lc_models.html`, and the *Catalog*
   entry from `CONSOLE_PAGES`. Touch nothing else in those two templates.
4. Gate green, then commit. Report the hash in your handoff draft at once.

## Gate B — the menus

1. **Chat in the top bar and in the left menu.** Add a *Chat* link to the masthead (in
   `masthead-end`, before the alerts count), with `aria-current` on `/chat*`. Keep Chat in the
   left menu's *Tools* section. Check 412 px: the masthead must not wrap to two rows.
2. **No console links under an application's tab.** `app_side_nav` stops appending
   `CONSOLE_SIDE_NAV`. Every caller of it must still render (the settings, tokens, prompts and
   database routes pass it). The brand links to `/` and Chat is in the top bar, so an application
   tab is not a dead end. Record in your handoff that this reverses WX3's "no dead end" rule, on the
   operator's instruction.
3. **No console links on docs pages.** The four `docs*.html` templates stop appending
   `side_nav(console_nav_sections, …)`. Delete the `console_nav_sections` global if nothing else
   reads it.

## Gate C — the catalog is gone (ADR-0146)

"Remove the catalog page from the site, no links to it, delete the files."

1. Write **ADR-0146, "The console has no catalog"**. It records the operator's decision, what
   leaves (the `/catalog` page, `/api/v1/catalog`, drop-in, pull and delete from the console), and
   what stays: model enable and disable on the LoadCoach and FreeWeight tabs; the audit event names,
   because historical audit rows keep them and `catalog.enabled` is still emitted by those two
   tabs; and job-kind names, so that a historical `catalog_pull` job row still renders on `/jobs`.
   Update `spec.md` §7.9 and `api.md` with a note that points at the ADR. Add the ADR to
   `docs/adr/README.md`.
2. Delete `web/routes/catalog.py`, `catalog.html`, and their router registration in `app.py`.
3. For each piece of `services/catalog.py`, `PullRegistry`, the `catalog_pull` job kind and
   `job_kinds.py`'s catalog join, grep every caller first. Delete what only the page used. Keep what
   `model_refresh` or any other remaining path uses. A job kind that can no longer be started stays
   *readable*: an old row must never 500. Test that with a stored `catalog_pull` row.
4. Delete `tests/*/test_catalog_*.py`, and fix every test that referenced the page. Add a test that
   `GET /catalog` is 404 and that no rendered page links to `/catalog`.

## Gate D — the page-bar sweep

Convert every template with a link strip (`page-actions`, `kit-actions` used as navigation, the
`app_page_header` caller slot, `<p>Per application: …`) to `page_nav`. **Skip every file §4 gives to
another row.** For each link, decide:

* **Duplicate of the left menu on that page** → remove it.
* **A subsection of this page's subject** (for example LoadCoach *Queue · History · New job*,
  FreeWeight *Results · Compare*, *Goals · Judges*) → a `links` entry, with `current` set.
* **JSON, Docs, API, a CLI hint** → an `actions` entry. A `<code>wr-gym …</code>` hint is not a
  link: remove it from the bar.

Convert pages that call `app_page_header` with a caller to call it **without** one and put
`page_nav` above it. Do **not** delete the caller slot from the macro: wave-2 templates still use it
until WY10 removes it. Remove any stylesheet rule the sweep left unused. The shell CSS budget
(`test_budgets.py`) must still pass.

## Proof

Screenshots at 1440 px and 412 px, light and dark, of: `/`, one page under each application tab,
`/docs`, `/chat`, a page with subsections (LoadCoach Queue), and `/jobs` with a historical
`catalog_pull` row. The page-nav test passes on every route.

## Out of scope

Any file owned by WY2–WY9 (§4). Table sorting (WY5). The Overview's figures (WY3). Do not
restyle the masthead beyond adding Chat.

Finish line, commits, handoff (`WY1_HANDOFF.md`) and report: §5.

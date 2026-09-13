# WY1 Handoff — shell navigation, the page bar, and the catalog removed

**Row:** WY1 in [`roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md).
**Branch:** `row/wy1-shell-nav` in `~/ai/worktrees/weightroom-wy1`, from `main` at `f6ffb80` (the
operator's commit of the eight template edits, §0). **Not merged.** **Date:** 2026-09-13.
**Model:** Opus 5 · medium.

## 1. Commits

| Gate | Commit | Subject |
|---|---|---|
| A | `ebc659e` | feat(web): the page bar — row WY1 gate A |
| B | `dd15522` | feat(web): Chat in the top bar, console links only on console pages — row WY1 gate B |
| C | `1a0b85b` | feat!: remove the catalog — row WY1 gate C (ADR-0146) |
| D | `2ab117d` | refactor(web): every link strip becomes the page bar — row WY1 gate D |

Wave 2 branches from gate A: **`ebc659e`**.

## 2. Gate

Interpreter: `.venv/bin/python` = Python 3.14.4, in the worktree venv (MirrorWall editable from
`~/ai/suite/py/MirrorWall`). Run at gate D's commit:

* `ruff format --check .` — 242 files already formatted
* `ruff check .` — All checks passed
* `mypy src tests` — no issues in 235 source files
* `lint-imports` — 5 kept, 0 broken
* `pytest` — 2024 passed, 3 skipped, 12 deselected
* `pytest -m performance tests/performance/test_budgets.py` — 12 passed. The shell stylesheet is
  20,148 bytes (18,789 on `main`), under its 32 KB budget.

`tests/integration/test_page_nav.py` renders 70+ GET UI routes from the route table. No page bar
repeats a left-menu `href`, and no rendered page links to `/catalog`.

## 3. What was built

### Gate A — `page_nav`

* `page_nav(links=(), actions=())` in `_app_page.html`, exactly §2.1: `nav.page-nav`, with
  `.page-nav-links` and `.page-nav-actions`, `aria-current="page"` on the current link, and no output
  when both lists are empty. `current` is read with `.get`, because the environment is
  StrictUndefined and the key is optional.
* The CSS is in `weightroom-shell.css`: one wrapping flex row, links on the left, actions muted at
  the right, and one rule under the bar.
* `test_page_nav.py` discovers routes with `tests.support.api_routes`. It renders every GET route
  outside `/api/` that has no path parameter. It renders each single-`{app}` route once per
  application. A route in neither group must be named in `NOT_A_SHELL_PAGE` with its reason, or the
  test fails. A second test fails on a stale entry in that list. Every application's API is
  `127.0.0.1:9`, and its executable is the `fake_application` script. So no test reaches the
  operator's running applications, and every application page renders its degraded state.

### Gate B — the menus

* *Chat* is in `masthead-end`, before the alerts count, with `aria-current` on `/chat*` (read from
  `current_path`). It stays in the Tools section too. At 412 px the masthead is still one row (see
  §6).
* `app_side_nav` no longer appends `CONSOLE_SIDE_NAV`. The four `docs*.html` templates no longer
  append the console sections, and the `console_nav_sections` global is deleted. **This reverses
  WX3's "no page is a dead end" rule, on the operator's instruction.** The brand links to `/`, and
  Chat is in the top bar. `test_shell.py`'s WX3 test is rewritten to say which pages list the
  console sections and which do not.

### Gate C — the catalog (ADR-0146)

* Deleted: `web/routes/catalog.py`, `catalog.html`, their two router includes,
  `app.state.catalog_pulls`, `JobServices.pulls`, `PullRegistry` and the pull worker, the GGUF
  drop-in, the delete-with-cleanup, `find_entry`, `validate_gguf`, `llamacpp_targets`, and the
  `as_json` methods only the API used.
* Kept in `services/catalog.py`: `set_enabled` (the LoadCoach and FreeWeight Models switches call
  it) and `catalog_entries` (`model_refresh` reports its count).
* `catalog_pull` is gone from `JOB_KINDS`, `IDEMPOTENT_KINDS`, the parameter table and `EXECUTORS`.
  `_audit_app` still maps it to `ollama`, for a stored row that is cancelled or failed.
* Test: `test_a_stored_catalog_pull_job_still_lists_renders_and_fails_cleanly` writes two rows the
  way W9 wrote them. `/jobs`, `/jobs/{id}` and `GET /api/v1/jobs/{id}` all answer 200. `POST /jobs`
  refuses the kind with 400. `JobWorker.run_once` fails the queued row with *"no executor for kind
  'catalog_pull' in this build"*.
* `test_the_catalog_is_gone_and_no_page_links_to_it`: `GET /catalog` and `GET /api/v1/catalog` both
  answer 404, and no rendered page contains `href="/catalog`.
* Documents changed: ADR-0146 and its index row; a note in `spec.md` §7.9 (plus the scope bullet,
  the page table row and the route list); `api.md` §5, where the six rows are gone and a note points
  at the ADR; `api.md`'s jobs row; `data-model.md` (both names marked historical);
  `docs/openapi.json`, regenerated; the root `README.md` and its `guide/` copy.

### Gate D — the sweep

One bar per page, as the first element of `page_content`. The rules applied:

* **A link whose `href` is in that page's left menu is removed.** This covers the back links:
  *Every model*, *All jobs*, *Every goal*, *All workflows*, *All trajectories*, *All tools*.
* **Links that repeat the top bar are removed too**, although the test checks only the left menu:
  PromptCadence Tiers' *LoadCoach* is an application tab, and Trajectories' *Chat* is in the
  masthead now.
* **A sibling set omits the member that is the left-menu entry, and marks the current one.** For
  example, LoadCoach Queue shows *History · New job*. History shows *History*(current) and *New job*.
  FreeWeight Compare shows *Compare*(current). The Results page, which is WY8's, should carry
  *Compare*. The same rule gives FreeWeight Machines, Judges and Goal · Calibration · Grade ·
  Report; LoadCoach Routing History and the evidence Store; PromptCadence *New*.
* **Every application page that has a bar carries *Docs*** as an action, through the new
  `docs_action(app)` global in `rendering.py`. `docs_link` uses it too, so the href is built in one
  place. `_app_state.html`'s standalone Docs link is now hidden only where a `.page-nav` precedes
  it, or where a header still has a caller (wave-2 pages until WY10). A page with no bar keeps the
  standalone link.
* **JSON** is an action on the Overview, a job, a prompt, the prompts list and tokens. The
  llama.cpp setup document is an action on `/llamacpp`.
* **Forms that shared a strip** move under the header in a `kit-actions` div: LoadCoach queue
  pause, drain and resume, and *Cancel job*. FreeWeight *Cancel run* stays in its page head.
* **IdeaPress:** the new `_ip.html` `project_bar(project_id, current, unit_key)` renders *Project ·
  Plan · Workspace · Units · Export* on the project, plan, workspace, export, task and unit pages.
  `projects_nav` (WX10's recent projects) now renders through `page_nav` and is the bar of Projects
  and New project. It lost *All*, which was the left menu's Projects.
* **PromptCadence trajectory:** its jump links (*The request · Plan · …*) and *Its debits · Its
  egress* are one bar. The `sections` list moved above the header.
* **Pages left with no bar:** FreeWeight Provider and System; IdeaPress Backends and Units;
  LoadCoach Adapters and System; PromptCadence Approvals, Egress, System, Tiers and Tool. Every link
  they had repeated a menu.
* `app_page_header` keeps its caller slot, as the kickoff says. No template outside §4's owned files
  still calls it with a caller.
* No stylesheet rule was left unused. `.page-actions` is still used by `shell.html`, `app_logs.html`,
  `fw_results.html`, `fw_evidence.html`, `database.html` and `chat_thread.html`, which are all other
  rows' files. `.kit-inline` is still used.
* **Skipped under §4:** `logs.html`'s *Per application* line (WY2), `shell.html` (WY3), `chat*.html`
  (WY7), the four model templates (WY8), and the three database templates (WY9).

## 4. Decisions to review

1. **The recent-projects strip left the single project page.** WX10 put it on every project page.
   A project page now has one bar, for that project's own subsections. Two `Page sections`
   landmarks on one page would be worse. The strip stays on Projects and New project.
2. **`catalog_entries` survives for one line of `model_refresh` output.** The kickoff said to keep
   what `model_refresh` uses. ADR-0146 decision 5 leaves the removal to a later row, if the operator
   wants it.
3. **`tests/unit/test_catalog_domain.py` was renamed, not deleted.** It is now
   `test_model_join_and_enable.py`, with the four tests of the kept code (the join and three
   `set_enabled` cases). Deleting it would have left `set_enabled`'s timeout-versus-refusal
   distinction (WPF11) untested. The drop-in, delete and pull tests are deleted.
4. **Top-bar duplicates were removed as well as left-menu duplicates**, as §3 says. The test
   enforces only the left menu, per §2.1.
5. **Single-link bars with the current link marked** (Compare, Machines, Judges, History). They
   keep sibling bars consistent from page to page, at the cost of one link that goes nowhere new.

## 5. What the plan got wrong

* **The survey's catalog list (§1 item 5) was incomplete.** Removing `/api/v1/catalog` also meant
  changing the OpenAPI snapshot and its `api.md` contract test, the eight catalog exercises in
  `tests/security/test_audit_routes.py`, and the two drop-in routes in `test_checklist.py`'s
  upload list. The root README's status line named the catalog too.
* **`docs/scripts/sync_component_docs.py` cannot run from a worktree.** `SUITE =
  DOCS.parent.parent` resolves to `~/ai/worktrees`, and the script fails on `py/`. The one guide
  copy that changed (`guide/README.md`) was edited by hand. Only link targets differ from the root
  README, and they differ as the script rewrites them. WY10 can re-run the script on `main` to
  confirm.
* **"Remove it from the bar" for a `<code>wr-gym …</code>` hint:** no strip outside §4 carried one.
* **47 templates (§1 item 9)** was about right. Gate D touched 66 templates outside §4, because a
  page-head `page-actions` div counted as a strip.

## 6. Proof

Throwaway console on 8801/8802, with its own XDG tree under the scratchpad. It is stopped now,
killed by a pid whose environment was checked. It sees the applications as *not installed*, and a
historical `catalog_pull` row was written into its database. Screenshots are under
`/tmp/claude-1000/-home-jpk-ai-suite/c79fa21e-dcc8-4047-8b1a-b01aae11b148/scratchpad/wy1/`:

* `shots-b/` (gate B): `overview`, `chat`, `apps_loadcoach`, `docs` × 1440/412 × light/dark.
* `shots-d/` (gate D): `overview`, `apps_freeweight_goals`, `apps_loadcoach_queue` (the page with
  subsections), `apps_ideapress_workflows`, `apps_promptcadence_trajectories`, `docs`, `chat`,
  `jobs`, `jobs_01HISTORICALPULL0000000001` and `jobs-history-row` (the stored `catalog_pull` row)
  × 1440/412 × light/dark. That is 40 files.

Probes on every shot: the masthead stays one row (header 83 px at 1440 px; 104 px at 412 px, where the
telemetry strip wraps to two lines), and no page scrolls horizontally.
`curl https://127.0.0.1:8801/catalog` returns 404.

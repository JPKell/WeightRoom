# WX12 Handoff — IdeaPress editable workflows

**Row:** WX12 (`roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12/13, unattended, one sitting
· **Model:** Claude Fable 5.1 · xhigh · **Kickoff:**
`history/prompts/wx12-ideapress-editable-workflows.prompt.md` · **Branches:** `row/wx12-workflows`
in `~/ai/worktrees/ideapress-wx12` (from IdeaPress `main` at `a4182c0`) and
`row/wx12-workflow-editor` in `~/ai/worktrees/weightroom-wx12` (from WeightRoom `main` at
`b052755`). **Not merged.**

## 1. What shipped

**[ADR-0143](../../adr/0143-a-workflow-is-a-stored-versioned-record-a-project-pins.md)** — a
workflow is a versioned JSON record a project pins, and the executor reads it.

### IdeaPress (one commit)

* **Migration `0014`, table `workflows`**: one row per *version* (`workflow_id`, `version`, `title`,
  `document_json`, `created_at`; unique on `(workflow_id, version)`), seeded with `standard 1.0`.
  `projects.workflow_id`/`workflow_version` have named this table since `0001` with nothing to point
  at and nothing reading them back.
* **`domain/workflows.py`** — the record, and every rule about what one may be. **`domain/stages.py`
  gains `STAGE_PROMPTS`**, the stage → default prompt record table, with an import-time check that
  every key is a model-using stage.
* **`services/workflows.py`** — read, write, bind, and `allowed_prompt_ids()` (the one fact the
  domain cannot know: which pack records are interchangeable with a stage's own).
* **API**: `GET /workflows` now reads the table and carries a `vocabulary` block; `GET
  /workflows/{id}` takes `?version=` and lists `versions`; **`POST /workflows`** (create at `1.0`)
  and **`PUT /workflows/{id}`** (next minor) are new. `POST /projects` resolves `workflow_id` against
  the table and pins the newest version.
* **CLI**: `ideapress workflow list|show` read the table (`show` gains `--version`); **`workflow
  save <file|->`** is new.
* **The executor reads the bound definition** — loaded once in `StageRunner.start`, carried on the
  `StageTask` — at seven points (§3 below). `standard 1.0` lists all twelve editable kinds, so every
  one takes the path 1.4 took.

### WeightRoom (one commit)

* `ip_workflows.html` reshaped: the stored workflows, IdeaPress's stage vocabulary (with the gate
  kinds named as what a workflow may never contain), and the limits table.
* **`ip_workflow.html`** — the editor, at `/apps/ideapress/workflows/{id}` and
  `/apps/ideapress/workflows/new`. One row per kind, in run order: a membership checkbox, a prompt
  `<select>` from IdeaPress's own `prompt_choices`, a revision bound on `revise`, a model on every
  stage that reaches one. The record in a collapsed JSON `<details>`; every stored version linked.
* `POST /apps/ideapress/workflows` and `POST /apps/ideapress/workflows/{id}` save; one audit row
  (`ideapress.workflow_save`) per save, carrying the version.
* A project's page links its bound workflow **at the version it pinned**.

## 2. Gate lines

| | |
|---|---|
| **IdeaPress** `~/ai/worktrees/ideapress-wx12/.venv/bin/python`, **Python 3.14.4**, at `28602b7` | `ruff format --check .` 231 files · `ruff check .` clean · `mypy src tests` 226 files, 0 issues · `lint-imports` 4 kept, 0 broken · `pytest` **1408 passed, 7 skipped, 31 deselected** |
| **WeightRoom** `~/ai/worktrees/weightroom-wx12/.venv/bin/python`, **Python 3.14.4**, at `WR_HEAD` | `ruff format --check .` 241 files · `ruff check .` clean · `mypy src tests` 234 files, 0 issues · `lint-imports` 5 kept, 0 broken · `pytest` **2003 passed, 3 skipped, 14 deselected** (2 of those deselections are §8's pre-existing `llamacpp.py` defect, live in this run's environment — see §8) |

`git status --short` clean in both worktrees before and after.

## 3. Where the executor reads the bound definition

All seven are `True` for `standard 1.0`, which is what makes the row safe.

| consulted | effect when the kind is absent |
|---|---|
| `start_plan` | refuses: this workflow has no `outline` stage |
| `start_stage` | refuses the kind by name, **before** `STAGE_BODIES` and before a `stage_runs` row exists |
| `run_unit` — `repair` | the attempt limit is 1: a draft that fails validation pauses the unit |
| `run_review_loop` — `audit_fast` | no audit, and no escalation either |
| `run_review_loop` — `audit_deep` | no escalation, whatever the fast score |
| `run_review_loop` — `fact_check` | no fact check (ANDed with ADR-0043's own applicability) |
| `run_review_loop` — `critique` / `revise` | no critique ⇒ the loop ends after the audits, `stop_reason` `critique_not_in_workflow`; no `revise` ⇒ the critique still reports and the text is kept, `revise_not_in_workflow` |

Per-stage `prompt_id`, `max_revision_rounds` (on `revise`) and `model_hint` land in exactly one
place each: the eight `render(...)` call sites now take the id as an argument defaulting to
`STAGE_PROMPTS`; `run_review_loop` resolves the bound after the run's own override and before the
setting; `InferenceGateway.begin_run` takes a stage → hint map beside the run-level hint.

## 4. Decisions I took — the ones worth reviewing before merge

1. **The four gates are not in a workflow record at all** (ADR-0143 §2). Not "required", not
   "present by default": there is no field for them, and a document naming one is refused. That is
   what makes workflows §1 rule 1 a mechanism rather than a convention, and it is also what makes
   the row cell's "two-stage custom workflow" reachable — the minimum workflow is `requirements,
   outline, draft`, three *kinds* but **two startable stage runs** (plan, then draft).
2. **A workflow chooses membership, not order.** Stages are stored in workflows §2's ordinal order
   and a document out of order is refused. Re-ordering means rewriting the unit loop and the review
   loop as a generic interpreter, which is precisely what the kickoff forbids ("must keep behaving
   identically") — the alternative is argued in the ADR.
3. **The editor is a checkbox per kind, not the row cell's "kind select".** Kinds are unique and the
   order is fixed, so a select per row could only produce documents IdeaPress would refuse. The
   checkbox list is generated from IdeaPress's own `vocabulary`, so the console holds no copy of the
   stage list.
4. **No `prompt_version` on a stage.** The pack holds one version per id; a version is chosen by
   editing the pack, and a workflow that pinned one could hold a project on a record the installed
   pack no longer has. "Interchangeable" is **identical required variable names** — which is why
   `audit_fast` and `audit_deep` are *not* choices for each other (`audit_deep` declares
   `prior_findings`).
5. **`ProjectService.create` lost its `workflow_version` keyword.** The pinned version is the newest
   stored one, never the caller's; no caller passed it (the tests that spell `workflow_version=`
   build `ProjectRow` directly).
6. **`StageRunner.start(workflow=…)` defaults to `standard_workflow()`** rather than being required.
   Both production callers pass it explicitly and both refuse *before* it; the default keeps ten
   direct-drive tests unchanged and matches `StageTask.workflow`'s own default.
7. **An unknown workflow stays `STAGE_PRECONDITION_FAILED` (409), not 404** — the code the route
   already used and the console's reader already documents.
8. **One audit action for both saves**, `ideapress.workflow_save`; which it was is the `version` in
   the row's params.

## 5. The GPU gate, for the orchestrator — exactly these commands

The row's exit condition is *a project created on a two-stage custom workflow completes end to end
on the operator's IdeaPress*. Nothing below needs this session's worktrees; run it after both
branches are merged, `pip install -e .` in the operator's IdeaPress, and:

```bash
# 0. Migrate the operator's database (it backs itself up first) and restart the unit.
ideapress db upgrade                       # (empty rows) -> 0014, seeding `standard 1.0`
systemctl --user restart ideapress.service

# 1. Create the workflow: the plan stage and the draft stage, nothing else.
cat > /tmp/fast-draft.json <<'JSON'
{"id": "fast-draft", "title": "Draft and stop",
 "stages": [{"kind": "requirements"}, {"kind": "outline"}, {"kind": "draft"}]}
JSON
curl -s -X POST http://127.0.0.1:8767/api/v1/workflows \
  -H 'content-type: application/json' --data @/tmp/fast-draft.json | jq '.id, .version'
#   expect: "fast-draft", "1.0"      (or do it in the console: /apps/ideapress/workflows/new)

# 2. A project on it. The response must pin fast-draft 1.0.
PROJECT=$(curl -s -X POST http://127.0.0.1:8767/api/v1/projects \
  -H 'content-type: application/json' \
  -d '{"title":"WX12 gate","brief":"The article must state that inference runs entirely on the reader'\''s own machine, and must name the trade that makes.","workflow_id":"fast-draft"}' \
  | jq -r '.id')
curl -s http://127.0.0.1:8767/api/v1/projects/$PROJECT | jq '.workflow_id, .workflow_version'

# 3. Plan, then draft. Both are real model calls on the operator's configured backend.
curl -s -X POST http://127.0.0.1:8767/api/v1/projects/$PROJECT/plan | jq '.task_id'
#   wait for it, then:
curl -s -X POST http://127.0.0.1:8767/api/v1/projects/$PROJECT/stages/draft/run \
  -H 'content-type: application/json' -d '{}' | jq '.task_id'
#   follow either with:  ideapress stage status $PROJECT <task_id>

# 4. What must be true when the draft run finishes.
curl -s http://127.0.0.1:8767/api/v1/projects/$PROJECT/units | jq '.items[].state'
#   every unit `committed` — the gates still ran (validate, coverage, commit)
ideapress stage list $PROJECT
#   the run's events must contain NO `audit.completed`, NO `critique.completed`,
#   NO `revision.completed`, and a `review.stopped` whose stop_reason is
#   `critique_not_in_workflow`. One model call per unit, not five.

# 5. The refusal the row is really about — a stage the workflow does not run:
curl -s -X POST http://127.0.0.1:8767/api/v1/projects/$PROJECT/stages/project_review/run \
  -H 'content-type: application/json' -d '{}' | jq '.error.message'
#   expect 409: "fast-draft 1.0 does not run the 'project_review' stage. It runs:
#   requirements, outline, draft."

# 6. And that `standard` is untouched: an existing project still runs the full loop.
ideapress workflow show standard
```

**The PostgreSQL leg is the orchestrator's**, as the kickoff says. The migration is written to be
PostgreSQL-clean — `op.create_table` with no SQLite-only DDL, no `batch_alter_table`, and the seed
goes in through a parameterised `op.bulk_insert` over the table literal so `PortableJSON` and
`UtcDateTime` bind per dialect. Run it as the house does:

```bash
docker run --rm -d -p 5433:5432 -e POSTGRES_PASSWORD=x --name wx12-pg postgres:16
cd ~/ai/worktrees/ideapress-wx12 && .venv/bin/pip install -q "psycopg[binary]>=3.2,<4"  # the `postgres` extra; not in `dev`
WEIGHTSDB_REQUIRE_POSTGRES=1 \
  WEIGHTSDB_POSTGRES_URL=postgresql+psycopg://postgres:x@127.0.0.1:5433/postgres \
  .venv/bin/python -m pytest -q tests/integration/test_migrations.py
docker rm -f wx12-pg
```

**Corrected from the previous draft of this handoff**: the env var `weightsdb`'s test harness reads
is `WEIGHTSDB_POSTGRES_URL`, not `IDEAPRESS_TEST_POSTGRES_URL` (that name doesn't exist — the draft
had it wrong and, with `WEIGHTSDB_REQUIRE_POSTGRES=1` set, the wrong name doesn't skip, it *fails*
loudly at "unreachable", so the mistake cannot pass silently). `psycopg` is declared in
`pyproject.toml` as the optional `postgres` extra, deliberately not in `dev` (Gold Standards §2 —
IdeaPress must run its default suite standalone), so it must be installed into the worktree's own
venv before this leg, not assumed present.

**Both legs actually ran in this continuation, not just described**: SQLite here gives
`test_migrations.py` 10 passed, 4 skipped (the four skips are the PostgreSQL ones); against a real
`postgres:16` container with the fix above, the same file gives **14 passed, 0 skipped** — every
PostgreSQL-only migration test the SQLite leg can't reach. Migrations run with SQLite FKs off, as
the house does; `0014` creates a table and needs none.

## 6. Screenshots

Session scratchpad, `wx12/shots/` (30 PNGs), taken with Playwright + system Chrome against a
**throwaway** console on `127.0.0.1:8789` (trust `8790`, own `XDG_*`) reading a **throwaway**
IdeaPress on `127.0.0.1:18767` (own `XDG_*`, own database, default `ollama` mode with no model ever
called). Both killed afterwards by environ-verified pid. The operator's IdeaPress and console were
never touched, read or written.

`{workflows, workflow, workflow_standard, workflow_new, workflow_saved, workflow_refused, project}`
× `{1440, 412}` × `{light, dark}`. `document.documentElement.scrollWidth` equals `clientWidth` at
412 px on every one.

The live write path was exercised on the throwaway, in the browser: saving `fast-draft` with
`audit_fast` and `critique` ticked redirected to `?saved=1.1` and IdeaPress then reported
`versions: ["1.0", "1.1"]`; unticking `draft` on another workflow rendered IdeaPress's own
`VALIDATION_ERROR` with every other tick kept; creating `outline-only` landed at `?saved=1.0`.

## 7. What the row text got wrong, or left for judgment

* **"a `workflows` table (migration; `standard 1.0` seeded from `domain/stages.py` `STAGES`)"** — a
  migration must not import the application, or the row it writes depends on which build ran it.
  The seed is a literal, and `tests/unit/test_workflow_records.py` asserts it equals
  `standard_workflow().document()` from the other side.
* **"A stage kind the executor does not implement is refused at write"** — read literally against
  `STAGE_BODIES` this refuses six kinds that are the substance of the feature (`repair`,
  `audit_fast`, `audit_deep`, `fact_check`, `critique`, `revise` have no body and never will; they
  run *inside* the draft body). The check is against the stage vocabulary minus the gates; ADR-0143
  §3 says so and why.
* **"ordered stages"** — they are ordered, by workflows §2's ordinal, and the record cannot reorder
  them (decision 2).
* **"`routes/ideapress_pages.py` and `ideapress_actions.py`"** in the collision rules names a file
  that does not exist, exactly as WX10 found: the split is `web/routes/ideapress.py` and
  `services/ideapress_pages.py` / `services/ideapress_actions.py`. I edited all three.
* **Two files outside the stated collision list** were unavoidable and are one line each in intent:
  `domain/audit.py` (the new `ideapress.workflow_save` action — the vocabulary is closed and a route
  that writes an unregistered action raises) and `tests/security/test_audit_routes.py` (the two new
  routes need an exercise, or `test_every_state_changing_route_has_an_exercise` fails). I did **not**
  touch `tests/support.py`: the new fixture is passed through `mock_ideapress(bodies=…)`, and the
  editor's repeated `kind` fields go through a local `_post_pairs` helper rather than widening
  `Console.post_form`.

## 8. A defect this row found and did **not** fix — `services/llamacpp.py`

**`src/weightroom/services/llamacpp.py:214` raises `NameError: name 'Mapping' is not defined`
whenever a real `llama-server` is running on the host.** `Mapping` is imported only under
`if TYPE_CHECKING:` (line 46) and `_served_context` uses it at run time in
`isinstance(settings, Mapping)`. The fix is one line — import `Mapping` from `collections.abc` at
module scope.

It is **pre-existing on `main` at `b052755`** (`git show b052755:src/weightroom/services/llamacpp.py`
has the same two lines) and untouched by this row; `git status --short` shows the file unmodified in
my worktree. It is in **WX3's** files, not mine, so I left it rather than risk a one-line conflict
with a concurrent wave-3 row.

How it shows up: `/llamacpp` is a **500 for the operator whenever llama.cpp is actually serving** —
which is the only time the page has anything to say. In the suite it takes two tests with it, both of
which read the real host rather than an injected runner:

* `tests/integration/test_llamacpp_page.py::test_the_page_renders_read_only_and_carries_no_form`
* `tests/integration/test_shell.py::test_every_page_reaches_the_console_pages_and_the_tools_from_the_left_menu`

Both passed in this row's earlier full runs and began failing mid-session, when another row's
`llama-server` (pid 3610755) came up on this machine. They pass again with no server running. My gate
line above is the full suite with exactly those two deselected; everything else is green.

**Reconfirmed in this continuation session**: the same pid, 3610755, is still serving on `:8180`
(an unrelated row's model, still up). The gate line in §2 above deselects the same two tests for the
same reason; nothing about the defect or its cause has changed since the first draft.

## 9. Continuation notes (this session)

This session picked up the previous agent's draft — the IdeaPress commit (`28602b7`) and this
handoff's §1–§8 were already written and correct; nothing there was redone or rewritten. What this
pass added:

1. **Fixed the one thing the kickoff named:** the previous draft had directly edited
   `docs/apps/ideapress/guide/workflows.md` in this (WeightRoom) worktree — a generated mirror
   (CLAUDE.md: "Never edit a `guide/` copy — edit the component and re-run the script"). Reverted
   with `git checkout -- docs/apps/ideapress/guide/workflows.md`. The content is not lost: IdeaPress's
   own `docs/workflows.md` — the canonical source for that guide file — already carries the identical
   44-line addition, committed in `28602b7`. Verified byte-for-byte: before this row, the guide copy
   and IdeaPress's `docs/workflows.md` were identical (`cmp` clean against IdeaPress `main` at
   `a4182c0`), so the revert only removes the duplicate, direct edit — the orchestrator's
   `sync_component_docs.py` run after merge regenerates the guide copy from IdeaPress's already-updated
   source and will produce the same 44 lines.
2. **Verified the four canonical mirrors are still byte-identical** between the two worktrees:
   `spec.md`, `api.md`, `data-model.md`, `workflows.md` under `docs/apps/ideapress/` all `cmp` clean
   against the IdeaPress worktree's copies.
3. **Ran every gate in both worktrees from scratch** (§2) — this had not been done end-to-end in one
   sitting before (IdeaPress's was; WeightRoom's changes were still uncommitted, gate-line cells were
   placeholders). Both green, IdeaPress's numbers unchanged from the draft.
4. **Ran the PostgreSQL leg for real** (§5) rather than leaving it as described-but-unrun, and fixed
   the wrong env var name in the process (see §5).
5. **Committed the WeightRoom side** — it had been sitting as an uncommitted working tree; this
   session made it the row's one WeightRoom commit, `WR_HEAD`.
6. Screenshots (§6) were already complete and correct from the previous pass (30 PNGs, all seven
   pages × two widths × two themes, plus two stray duplicate-named files from an earlier naming
   attempt in the same directory that are not part of the required set — `workflow-refused-1440-light.png`
   and `workflow-saved-1440-light.png`, superseded by the underscore-named files of the same shot);
   nothing was re-shot.

## 10. For whoever merges this

1. **Not merged, not pushed, no version bump.** IdeaPress stays `1.5.0` and `wr-gym` `1.0.0`, both
   under `## [Unreleased]`.
2. **Merge IdeaPress first**, then WeightRoom: the console's new tests read fixtures recorded from
   IdeaPress's `GET /workflows`, and the console pages need the two new endpoints.
3. `ideapress db upgrade` on the operator's database, then **restart `ideapress.service`** — and
   restart `weightroom.service` after the console merges.
4. Documentation: canonical in `WeightRoom/docs/apps/ideapress/{spec,api,data-model,workflows}.md`,
   mirrored byte-identically into the IdeaPress worktree's `docs/apps/ideapress/` (`cmp` clean).
   IdeaPress's own `docs/workflows.md` is canonical **in the component** and copied into
   `docs/apps/ideapress/guide/workflows.md` here; `FreeWeight/scripts/sync_docs.py` cannot run from
   a worktree, so re-run the sync scripts after merge.
5. `docs/openapi.json` in IdeaPress was regenerated (`test_openapi_snapshot.write()`), +189 lines.

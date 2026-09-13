# ADR-0143 — A workflow is a stored, versioned record; a project pins one, and the executor reads it

**Status:** Accepted (2026-09-12)
**Extends:** [ADR-0012](0012-prompt-storage-format.md) (a prompt is a versioned JSON record; this is
the same shape for the stage list, and takes up ADR-0012's own "database-backed override layer …
for IdeaPress's per-project prompt tuning" as a per-*workflow* prompt choice rather than a per-project one).
**Relates to:** [ADR-0039](0039-audit-gated-blocking-requirements.md) (a check-less blocking
requirement is satisfied only by an explicit audit attestation — which a workflow without
`audit_fast` can no longer produce), [ADR-0040](0040-routing-backend-owns-model-choice.md)
(a routing backend chooses the model; a stage hint reaches it only under `honour_stage_bindings`),
[ADR-0043](0043-grounding-is-verified-not-assumed.md) (`fact_check` applies where there are
sources and grounding to check), [ADR-0116](0116-research-runs-under-toolyard-and-fetches-only-a-named-host.md)
(`research` runs before a plan exists).
**Source:** row WX12 (`roadmap/wx-console-ux-work.md` §1), from the operator's request list of
2026-09-12 — *"IdeaPress workflows should be editable"*.

## Context

IdeaPress has always had a `workflow_id` and a `workflow_version` column on `projects`, a
`GET /workflows` endpoint and a `workflow` CLI group. All four were decoration: the endpoint and the
command rendered `domain/stages.py`'s `STAGES` table under the hard-coded name `standard 1.0`, the
route refused any other id in as many words (*"This build ships: standard"*), and the columns were
written with a caller-supplied string that nothing validated and nothing ever read back. A project
created with `workflow_id: "anything"` was accepted and ran the same sixteen stages as every other.

The operator wants to run a project that does less: draft and commit without three audits, a fact
check and a critique round per unit, on a machine where each of those is a full model call.

Two constraints bound anything built here.

* **Workflows §1 rule 1 — only Python decides progression.** A gate passes because a deterministic
  check passed or a bounded loop exhausted. Whatever an operator may edit must not be able to
  reach that.
* **`standard 1.0` must keep behaving identically.** Every project that exists on the reference
  machine is bound to it, and the review loop's shape (`audit_fast` → escalation → `fact_check` →
  `critique` → `revise`) is what four rows of measured behaviour sit on.

## Decision

### 1. A workflow is a versioned JSON record in IdeaPress's own database

A new `workflows` table, migration `0014`. One row per *version*:

| column | |
|---|---|
| `id` | ULID |
| `workflow_id` | the name a project pins — `standard`, `fast-draft`, … |
| `version` | `MAJOR.MINOR` |
| `title` | one line, for a person |
| `document_json` | the whole record, canonical |
| `created_at` | |

unique on `(workflow_id, version)`. The record's shape is ADR-0012's: an identifier, a version, and
an ordered list of stages, each carrying its `kind`, an optional `prompt_id`, an optional
`max_revision_rounds` and an optional `model_hint`.

**A row is never updated and never deleted.** `POST /workflows` creates a new `workflow_id` at
`1.0`; `PUT /workflows/{id}` writes a *new version* — the highest existing minor plus one — and
leaves every earlier one in place. A project pins `workflow_id` **and** `workflow_version`, so a
running project keeps the definition it started under no matter what is saved afterwards. That is
the same rule prompts already follow, for the same reason: a definition that can change under a run
makes the run's provenance a lie.

`standard 1.0` is seeded by the migration, transcribed from `domain/stages.py` as it stands. A unit
test asserts the seeded document equals what `standard_workflow()` builds from `STAGES`, so the two
cannot drift — the same mechanism `check_table_matches_type` already applies to the stage table
itself.

### 2. A workflow chooses **which** stages run and **how**, never the order and never the gates

Two exclusions, both load-bearing:

* **The four gate stages — `validate`, `coverage`, `commit`, `export` — are not in a workflow
  record at all.** Not "present by default", not "required": there is no field for them. A document
  naming one is refused at write, naming the rule. They are what workflows §1 rule 1 *is*; an
  operator who could drop `coverage` could commit a unit that satisfies no requirement, and an
  operator who could drop `validate` could commit text no check ever read. The editable set is
  therefore the eleven model-using stages plus `research`.
* **Stages run in workflows §2's ordinal order, always.** A record stores its stages in that order
  and a document out of order is refused at write. Re-ordering is not a data change — `draft` before
  `outline` has no meaning, and the executor's shape (a plan task, a per-unit loop, a project-wide
  review) is the order. What a workflow varies is membership, not sequence.

Four coherence rules, all checked at write, all in one function with the offending path named:

1. `draft` is required. A workflow that writes nothing is not a workflow.
2. `requirements` and `outline` go together — `POST /projects/{id}/plan` runs both as one task.
3. `revise` requires `critique`. Nothing else decides that a revision should happen.
4. `audit_deep` requires `audit_fast`, and `research_synthesis` requires `research`. Each is an
   escalation of the other.

The minimum workflow is therefore `requirements, outline, draft` — three stage *kinds*, two startable
stage *runs* (plan, then draft), which is what "a two-stage custom workflow" means in practice.

### 3. A stage kind the executor cannot run is refused at write, not at run

`kind` is validated against `domain/stages.py`'s `STAGES` — the one stage list in the suite — minus
the gates. `{"kind": "translate"}` is a `400` at `POST`/`PUT` naming the twelve kinds that exist, not
a project that plans successfully and then fails at its third stage with the operator's day gone.

This is deliberately *not* a check against `STAGE_BODIES`. Six editable kinds (`repair`,
`audit_fast`, `audit_deep`, `fact_check`, `critique`, `revise`) have no entry there and never
will: they are not separately startable, they happen **inside** the draft body, and a person who
could start `commit` on its own could commit a unit that never passed validation. Membership of the
workflow is what governs them; `STAGE_BODIES` is what governs which stage a person may *start*, and
`start_stage` refuses a kind the bound workflow does not list **before** it looks for a body.

### 4. Where the executor reads the bound definition

The bound `Workflow` is loaded once, in `StageRunner.start`, and carried on the `StageTask` — the
object every stage body, the unit loop and the review loop already hold. No signature threading, one
read per run, and nothing can run under a definition different from the one the run was started with.
Seven places consult it, and **every one of them is `True` for `standard 1.0`**:

| consulted | effect when the kind is absent |
|---|---|
| `start_plan` | refuses: this workflow has no plan stage |
| `start_stage` | refuses the kind by name, before `STAGE_BODIES` |
| `run_unit` — `repair` | a validation failure pauses the unit instead of being repaired |
| `run_review_loop` — `audit_fast` | no audit; no escalation either |
| `run_review_loop` — `audit_deep` | no escalation, whatever the fast score |
| `run_review_loop` — `fact_check` | no fact check (ANDed with ADR-0043's own applicability) |
| `run_review_loop` — `critique` / `revise` | no critique ⇒ the loop ends after the audits; no `revise` ⇒ a critique still reports and the loop stops `revise_not_in_workflow` |

`standard 1.0` lists all twelve, so every branch above takes the path 1.4 took and the measured
behaviour of four prior rows still stands.

**A workflow without `audit_fast` cannot satisfy a check-less blocking requirement.** ADR-0039 made
an explicit audit attestation the only way; with no audit there is no attestation, the requirement
stays unsatisfied and the unit pauses at the coverage gate. That is the correct outcome and it is
said in the refusal, not discovered.

### 5. Per-stage `prompt_id`, `max_revision_rounds` and `model_hint`

Each optional; absent means exactly what 1.4 did.

* **`prompt_id`** — one of the pack's records *for that stage*, where "for that stage" means: its
  declared **required variable names are identical** to the stage's shipped record's. That check is
  what makes this safe to render — a record with different variables would raise
  `PromptVariableError` mid-run, which is the failure mode this row exists to move to write time.
  The default record per stage is now a table, `STAGE_PROMPTS` in `domain/stages.py`, beside the
  stage table it is keyed by, with a check that its keys are model-using stages; the eight call
  sites that spelled their prompt id inline now take it as an argument defaulting to that table.
  **No version pin**: the pack holds one version per id, a version is chosen by editing the pack,
  and a workflow that pinned one could hold a project on a record the installed pack no longer has.
* **`max_revision_rounds`**, on the `revise` stage — the review loop's bound for projects on this
  workflow. Precedence: a run's `overrides.max_revision_rounds` > the workflow's > the
  `workflow.max_revision_rounds` setting. Same order as everywhere else in the application: the more
  specific and more recent statement wins.
* **`model_hint`**, per stage — the model that stage's calls ask for, ahead of `[models.stages]` and
  behind a run's own `overrides.model_hint`. It rides the existing mechanism exactly:
  `InferenceGateway.begin_run` takes a stage→hint map beside the run-level hint, and stamps it on a
  request that carries none, which is where a run override already wins. In `loadcoach` mode it
  reaches LoadCoach only under `honour_stage_bindings`, because ADR-0040 says a hint sent past a
  routing backend silently bypasses its routing; the workflow does not get a second door.

### 6. `POST /projects` validates and pins

`workflow_id` is resolved against the table and **the latest version is pinned** on the project.
An unknown id is refused with the ids that exist. Before this row the column took any string.

## Alternatives considered

**A workflow as a file on disk, like the prompt pack.** Rejected: the editor is the console, over
HTTP, on a machine whose config directory the console does write to (prompt overrides) but whose
*data* it must not (ADR-0123 rule 3). A workflow is a project's binding, it needs referential
integrity with `projects`, and it is read on every stage start — a table is where that lives.

**An executor driven entirely by the record — each stage a row, run in the record's order.**
Rejected, and this is the decision most worth arguing with. It is what "editable workflows" sounds
like it means, and it would make ordering and repetition real. It also means rewriting the unit loop
and the review loop as a generic interpreter, and the four gates as entries a record could omit — at
which point workflows §1 rule 1 is a convention rather than a mechanism, and every measured result
from rows K3, M1, WP5, WPF7 and WPF9 was produced by code that no longer exists. The membership model
delivers the operator's actual request (a project that does less per unit) at a seventh of the risk.

**A boolean per stage on the project, no workflows table.** Rejected: it is the same feature without
versioning or reuse, and a project's configuration would silently change meaning when the stage list
grows. The columns to pin a definition already existed; they wanted a definition to pin.

**Editing a workflow in place, with an `updated_at`.** Rejected for the reason under decision 1: a
run's provenance names `workflow_id` and `workflow_version`, and an editable version makes that pair
unable to identify what actually ran.

## Consequences

* Every existing project is bound to `standard 1.0`, which the migration seeds, and runs exactly as
  it did. The integration suites that measure the loop's shape are unchanged.
* `GET /workflows` stops being a rendering of `STAGES` and becomes a read of the table; it gains a
  `vocabulary` block (the editable kinds, the gate kinds it will refuse, and the prompt ids allowed
  per stage) so an editor needs no second endpoint and no knowledge of IdeaPress's vocabulary.
  `GET /workflows/{id}` returns the latest version by default, `?version=` for an earlier one, and
  lists the versions that exist. The `workflow` CLI group reads the same table.
* A project pinned to a version, and the versions themselves, are permanent rows. They are small
  (one JSON document each) and there is no pruning: a definition a project ran under is provenance.
* The `workflows` list is now a thing an operator can get wrong. Everything a document can get wrong
  is refused at write with the path named — a kind that is not a stage, a gate, a stage out of
  order, a duplicate, a prompt whose variables differ, a missing `draft`, a `revise` with no
  `critique` — and the console's editor renders the refusal in IdeaPress's own words.
* `fact_check`'s applicability is now an AND of two independent facts (in the workflow, and
  ADR-0043's sources-and-grounding test). A project that expects it and has no sources still does not
  get it, and the reason it does not is still the one ADR-0043 gives.

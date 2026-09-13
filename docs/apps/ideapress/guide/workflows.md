# IdeaPress — how the work happens

The complete pipeline, and the rules a model does not get to break.

## The shape of it

An idea becomes **requirements**, requirements become a **plan**, the plan becomes **units**, and
each unit is drafted, checked, criticised, revised and committed on its own. Nothing is committed
that has not passed deterministic validation, and no model decides that anything is finished.

## The sixteen stages

| Stage | What it does | Model? |
|---|---|---|
| `requirements` | Compiles the brief into checkable requirements with source quotations | yes |
| `research` | Gathers source notes | no backend ships at 1.0 |
| `research_synthesis` | Structures those notes | yes |
| `outline` | Produces the unit plan | yes |
| `draft` | Writes one unit | yes |
| `validate` | Runs every deterministic check | **no** |
| `repair` | Fixes what validation caught | yes |
| `audit_fast` | Finds problems and attests requirements | yes |
| `audit_deep` | A closer look, on escalation | yes |
| `fact_check` | Claim-level verdicts against sources | yes |
| `critique` | Judges quality; may say "leave it alone" | yes |
| `revise` | Acts on findings | yes |
| `coverage` | Decides whether every blocking requirement is satisfied | **no** |
| `commit` | Writes the version atomically | **no** |
| `project_review` | Consistency across units | yes |
| `export` | Renders the document | **no** |

**The four gates involve no model at all**: `validate`, `coverage`, `commit` and `export`. That is
not a property of the prompts — it is a property of the stage list, and it is what "Python owns the
control flow" means concretely.

## Which stages your project actually runs

Since 1.5 the sixteen above are the *vocabulary*; what a project runs is its **workflow**, a stored
record it pins by name and version. `standard 1.0` is every existing project's, and it lists
everything editable — so nothing changed for a project made before 1.5.

```bash
ideapress workflow list
ideapress workflow show standard
ideapress workflow save fast-draft.json   # a new workflow, or the next version of one
```

A workflow document is the stages it runs, in the order above, each optionally naming a prompt
record, a revision bound and a model:

```json
{
  "id": "fast-draft",
  "title": "Draft and stop",
  "stages": [
    {"kind": "requirements"},
    {"kind": "outline"},
    {"kind": "draft", "model_hint": "ollama/gemma4:12b"}
  ]
}
```

That one drafts, validates, checks coverage and commits — two stage runs, plan then draft, and no
audit, fact check, critique or revision at all. Three rules are worth knowing before you write one:

* **The four gates are not in a workflow.** `validate`, `coverage`, `commit` and `export` always
  run; naming one is refused. They are what "Python owns the control flow" means, and they are not
  yours to switch off.
* **You choose membership, not order.** The stages run in the order of the table above whatever
  order you list them in — and a document that lists them out of order is refused rather than
  quietly reordered.
* **A workflow is never edited in place.** Saving writes the next version; a project keeps the
  version it was created on, so nothing you save can change a project already under way.

Anything a run could not execute is refused when you save, with the field named: a kind that is not
a stage, a gate, a duplicate, a `revise` with no `critique`, a prompt whose variables do not match
the stage's. **Dropping `audit_fast` also drops the attestation below**, so a requirement with no
deterministic check can then never be satisfied and its unit will pause at the coverage gate.

## What a model is never allowed to do

* Decide that a stage is complete.
* Decide that a requirement is satisfied **by saying nothing about it** (see below).
* Modify requirements, the plan, or committed units.
* Choose which unit to work on next.
* Cause code execution, a filesystem path, a network call or a database query.
* Set its own retry or revision budget.

## Requirements, and the two kinds of guarantee

A requirement with **deterministic checks** is settled by Python running them. No model opinion can
overturn a check, in either direction.

A requirement the compiler could not express as a literal check — the qualitative ones, "must not
use a marketing register" — has no mechanical backstop. For those the audit returns an **explicit
verdict** per requirement: `met`, `not_met` or `cannot_judge`. Only a literal `met` satisfies one.
Silence does not. An omitted verdict, a `cannot_judge` and an invented word all leave the
requirement unsatisfied and pause the unit.

Everywhere coverage is shown — the unit page, the plan page, both exports — a requirement settled
this way is labelled **"guaranteed by model review, not a deterministic check"**, so you can always
tell the two apart.

If you want none of it:

```toml
[workflow]
allow_audit_gated_requirements = false
```

That makes the gate wholly mechanical. Requirements with no checks then cannot be satisfied at all,
which is stricter and will pause more units.

## The bounded loops

Nothing loops forever, and every bound is set by Python:

* `max_attempts_per_stage` (3) — attempts at one stage before the unit pauses.
* `max_revision_rounds` (3) — full revision rounds per unit.
* `diminishing_returns_threshold` (0.05) — revision stops early when a round improves things by
  less than this, and the report records **which** rule stopped it.
* A model returning empty text after exhausting its output budget is retried exactly **once**,
  because a cold load of a reasoning model does that; a second empty answer pauses the unit with
  the budget in the reason.

## When something fails

* A failed stage **pauses that unit**. Other units carry on.
* Committed units are never rolled back by a later failure.
* `ideapress stage run <id> <stage> --resume` continues from the first incomplete unit.
* If the process dies mid-stage, the attempt is marked `interrupted` at startup and the unit is
  resumable. No partial content is ever committed.
* Cancellation is honoured at the next model-call boundary. Partial output is kept on the attempt
  record and never committed.

## Provenance

Every committed unit records the backend, the model identity, every prompt's id and version, the
requirement coverage and the validation results. The unit's history shows every attempt, what it
produced, what was found and what changed. That record is what makes the output reviewable rather
than merely plausible.

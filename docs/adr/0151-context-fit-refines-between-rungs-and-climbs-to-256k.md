# ADR-0151 — Context fit refines between rungs, and the ladder climbs to 262 144

**Status:** Accepted (2026-09-14)
**Extends:** [ADR-0148](0148-context-fit-is-its-own-suite-and-gates-benchmarks.md) — supersedes
nothing there. **Amends:** [ADR-0121](0121-freeweight-launches-llama-server-with-fit-off-and-caps-the-max-fit-ladder.md)
§1's default ceiling.
**Source:** Operator decision, 2026-09-14 (row CF8, `docs/roadmap/context-fit-work.md`), after the
first live fit: "build #1 and set the max to 256k".

## Context

`native.context_fit`'s ladder doubles. On the reference card Ministral-3-14B Q4_K_M served 32 768
and was refused at 65 536, so its fit was reported as 32 768 while the card's real limit lies
somewhere in a 32 768-token gap — and a number the operator applies to LoadCoach (ADR-0149) is
then up to half the context the card could serve. A benchmark test's cases are a fixed list the
run engine enumerates up front; nothing let a test choose a case from the answers so far.

The ladder's ceiling, `benchmarks.max_fit_context_tokens`, defaulted to 131 072, below the trained
context of models the operator runs.

## Decision

1. **A test may choose follow-up cases.** The run engine, after a test's listed cases, calls the
   test's optional `next_cases(outcomes)` with every case tried so far — `True` served, `False`
   refused, `None` skipped — read back from the stored samples, runs whatever new cases it
   returns, and asks again until it returns none. A case id already tried is never run twice, and
   the test's `total_cases` grows with each round. Outcomes come from storage, so a resumed run
   asks the same questions and gets the same cases.
2. **`native.context_fit` halves the gap.** After the ladder it tries the rung halfway between the
   largest context that served and the smallest refused above it, on multiples of 4 096 tokens,
   until the gap is one step. Three more launches take a 32 768-token gap to 4 096.
3. **`benchmarks.max_fit_context_tokens` defaults to 262 144** (the ladder gains that rung by the
   existing doubling rule). A model trained for less still skips the rungs past its own context
   (ADR-0148 §2).

## Consequences

*Positive.* The fit is within 4 096 tokens of the card's limit, which is what makes applying it
worth doing. Large-context models are measured past 131 072.

*Negative.* A refined fit costs a few more launches, each a failed or slow start. The ceiling is
shared with `native.memory_kv`, so its default ladder — and therefore its `dataset_hashes` — change
too: `memory_kv` runs at the new default separate from earlier ones rather than averaging with
them. On Ollama, which spills instead of refusing (ADR-0121 §4), a higher ceiling climbs further
into host RAM; lower it there.

*Neutral.* `next_cases` is optional. Every other suite is unchanged, and a test without it runs
exactly its listed cases.

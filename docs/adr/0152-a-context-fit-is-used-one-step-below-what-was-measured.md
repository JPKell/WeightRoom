# ADR-0152 — A context fit is used one step below what was measured

**Status:** Accepted (2026-09-14)
**Amends:** [ADR-0148](0148-context-fit-is-its-own-suite-and-gates-benchmarks.md) §6 (the context a
benchmark runs at) and [ADR-0149](0149-the-console-applies-a-context-fit-to-loadcoach.md) §1 (the
number Apply writes). Supersedes neither. **Relates to:**
[ADR-0151](0151-context-fit-refines-between-rungs-and-climbs-to-256k.md) (the 4 096-token step).
**Source:** Operator decision, 2026-09-14 (row CF9, `docs/roadmap/context-fit-work.md`), after the
refined fit of Ministral-3-14B Q4_K_M came back at 40 960 tokens with 15.94 GB of 16.3 GB in use.

## Context

A fit is the largest context that launched and served **once**, on a card whose other tenants —
the desktop, a browser — take a varying share of its memory. Used exactly, it leaves no room for
that variation: FreeWeight launches with `--fit off` (ADR-0121), so a benchmark at the exact fit
can be refused at launch on a busier day, and LoadCoach's llama-server keeps `--fit on`, so it
spills layers to host RAM instead.

## Decision

1. **The usable context is the measured fit less one refinement step, 4 096 tokens** —
   the measurement's own resolution. It is computed in one place, `native.context_fit`'s
   `usable_context`, and never below one step.
2. **FreeWeight's benchmarks run at the usable context** (amends ADR-0148 §6). The gate is unchanged:
   it asks whether a fit exists.
3. **`GET /results/context-fit` carries `usable_context_tokens`** beside
   `max_successful_context_tokens`, which stays the measurement.
4. **The console's Apply writes `usable_context_tokens`** (amends ADR-0149 §1), and reads *applied*
   when LoadCoach's file says that number. A FreeWeight that does not send the field offers no
   Apply rather than a guessed number.

## Consequences

*Positive.* FreeWeight's benchmarks and LoadCoach serve one context per model, and both have about
a step of KV cache to spare — roughly 650 MiB on Ministral-14B. The margin lives in FreeWeight
beside the measurement, so the console never repeats the arithmetic.

*Negative.* A step of context is given up on every model, on the days the card had room for it.

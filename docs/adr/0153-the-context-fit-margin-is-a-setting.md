# ADR-0153 — The context-fit margin is a setting

**Status:** Accepted (2026-09-14)
**Amends:** [ADR-0152](0152-a-context-fit-is-used-one-step-below-what-was-measured.md) §1 — the
margin's size, not where it applies.
**Source:** Operator decision, 2026-09-14 (row CF10, `docs/roadmap/context-fit-work.md`): "put it in
settings".

## Context

ADR-0152 fixed the margin below a measured fit at one refinement step, 4 096 tokens. What that
step is worth in memory depends on the model and its KV precision (about 640 MiB on Ministral-14B
at f16, half that at `q8_0`), and how much room a card needs depends on what else runs on it —
neither is something the code can know.

## Decision

1. **`[benchmarks] context_fit_margin_tokens`** (integer, default `4096`, `0` … `65536`,
   config-only). `0` uses the fit as measured.
2. FreeWeight reads it in both places the margin is used: the context a benchmark runs at
   (`create_run`) and `usable_context_tokens` on `GET /results/context-fit`. The console applies
   that field, so it follows the setting without knowing it.
3. The usable context never drops below one refinement step unless the fit itself is smaller.

## Consequences

Changing the setting changes the context later benchmarks run at, and so their runtime profile
hash: runs before and after it are separate subjects, as any two contexts are (ADR-0023). A
number already applied to LoadCoach is not rewritten; the console shows Apply again where the file
no longer says the usable context.

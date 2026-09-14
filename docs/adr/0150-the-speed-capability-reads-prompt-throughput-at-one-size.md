# ADR-0150 — The speed capability reads prompt throughput at one prompt size

**Status:** Accepted (2026-09-13)
**Relates to:** [ADR-0148](0148-context-fit-is-its-own-suite-and-gates-benchmarks.md) (each model
runs at its own context), [ADR-0034](0034-run-level-derived-metrics.md),
[ADR-0017](0017-benchmark-confidence-and-freshness.md) (a suite version separates results).
**Source:** Operator decision, 2026-09-13 (row CF6, `docs/roadmap/context-fit-work.md`).

## Context

`capabilities.speed` weights `native.performance`'s run-level `prompt_tokens_per_second` at 0.3.
That figure is the mean over every prompt-processing case that completed, and which cases complete
depends on the served context: a 16 384-token prompt is skipped at 8 192 and run at 32 768.
Prompt throughput falls as the prompt grows, so under ADR-0148 — every model at its own fit — a
model that fits more context would score slower for being asked more.

## Decision

1. **`native.performance` `1.1.0` derives `prompt_tokens_per_second_at_4096`**: the mean, over the
   completed `prompt-4096` samples, of provider-reported prompt tokens ÷ prompt-evaluation seconds.
   4 096 is the largest catalog size every fit ladder serves (its case needs 4 352 tokens; the
   smallest rung is 8 192).
2. **`capability_weights.toml` `1.1`**: `speed`'s prompt source reads that metric. The run-level
   mean stays, and stays on every page that shows it.

## Consequences

Speed is comparable across models served at different contexts. `native.performance` runs at
`1.0.0` partition from `1.1.0` runs, so speed evidence is recomputed from new runs only, and the
mapping change is a new `policy_version`. A model whose `prompt-4096` case never completes has no
prompt half of its speed score — absent, not zero (ADR-0016).

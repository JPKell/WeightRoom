# ADR-0148 — Context fit is its own suite, one launch per rung, and a model is benchmarked at the context it fits

**Status:** Accepted (2026-09-13)
**Relates to:** [ADR-0121](0121-freeweight-launches-llama-server-with-fit-off-and-caps-the-max-fit-ladder.md)
(`--fit off`, the ladder ceiling — both kept),
[ADR-0023](0023-runtime-profile-resolution.md) (a context is part of the subject),
[ADR-0034](0034-run-level-derived-metrics.md) §6 (a derived metric is a function of one run),
[ADR-0016](0016-unavailable-is-not-zero.md).
**Source:** Operator decisions, 2026-09-13 (row CF2/CF3, `docs/roadmap/context-fit-work.md`):
measure the maximum context per model, never automatically; refuse every other benchmark of that
model until it is measured; use the measured value as the context every benchmark runs at.

## Context

`memory_kv.max_context_fit` climbs `8192 … 131072` "until something refuses". Since row WPF10 a run
is one launch: every request of a run carries the run's own profile, so llama-server is started
once at the run's `context_size`. Every rung above that context is therefore refused by the
server's own context check, not by the card — run `01M2EN0XE3A7MB5B3H5NKHVDHS` (2026-09-14,
Ministral-3-14B): `fit-8192` completed, `fit-16384` failed with *"request (13408 tokens) exceeds
the available context size (8192 tokens)"*. The derived figure is then clamped to
`min(served_context, ceiling)`, so the test reports the configured context, flagged capped, on
every model. The one number the suite exists to produce has never been measured.

Separately, a model's benchmarks run at `[runtime].context_size` — one value for every model on the
machine. A prompt-size case larger than it is skipped, so a model that could serve 32 768 tokens
is measured as if it served 8 192, and LoadCoach, serving the same model at a different context,
matches none of that evidence (ADR-0023 §3).

## Decision

1. **A new suite, `native.context_fit` `1.0.0`, with one test, `context_fit.max_context`.** Its
   cases are the ladder `max_fit_ladder(benchmarks.max_fit_context_tokens)` (ADR-0121 §1, hashed
   into `dataset_hashes` the same way). Each case declares **`serve_context_tokens`**, and the run
   engine sends that case — its warm-up included — under the run's profile with `context_size`
   replaced by that value. This is the only exception to "one run is one launch", and it is
   declared by the case, never inferred. The prompt fills the rung less 512 tokens of headroom, so
   a rung that launches is exercised rather than refused by its own prompt.
2. **A rung above the model's advertised `max_context` is skipped with a recorded reason.** A
   context the weights were not trained for is not a context anyone should serve.
3. **The figures.** `max_successful_context_tokens` is the largest rung with a completed sample; a
   launch the card refuses is a failed sample and *is* the measurement (catalog §3.2).
   `max_context_capped_by_configuration` compares against the top rung the run was allowed to
   climb, never the run's own served context. The served-context divergence degradation does not
   apply to this suite: its server is expected to end at a context other than the run's.
4. **When a fit applies.** A fit applies to a later run of the same model on the same machine when
   the two profiles hash equal once `context_size` is cleared from both — the same KV precision,
   flash attention, GPU layers, `fit_to_device`, `keep_alive` and `adapters_registered`. Any other
   profile needs its own fit. The newest completed `native.context_fit` run wins.
5. **The gate.** `[benchmarks] require_context_fit` (bool, default `true`). On a provider that
   declares `context_configurable`, creating a run of any suite other than `native.context_fit` for
   a model with no applicable fit is refused with `CONTEXT_FIT_REQUIRED`, naming the command that
   measures it. Nothing starts a fit run on its own — discovery does not, the scheduler does not.
   A provider that cannot set a context (a remote OpenAI-compatible endpoint) has nothing to fit and
   is not gated.
6. **The fit is the benchmark context.** A run created without an explicit context — no
   `--context-size`, no `runtime.context_size` in the API body — is served at the applicable fit,
   recorded `configured`. An explicit context still wins, and is still gated. The fit run itself
   records `[runtime]`'s profile.
7. **`GET /api/v1/results/context-fit` reads `native.context_fit`**, not `native.memory_kv`. Its
   response shape is unchanged.

## Consequences

*Positive.* The maximum context is measured on the card rather than read back from configuration.
Every suite of one model runs under one profile at the largest context it serves, so prompt-size
cases the model can hold are no longer skipped, and that profile is the one an operator can hand
to LoadCoach ([ADR-0149](0149-the-console-applies-a-context-fit-to-loadcoach.md)).

*Negative.* Each rung is a launch: a ladder of five rungs costs five server starts, and a refused
rung costs a failed start. A model cannot be benchmarked until someone has measured it, and a
changed launch setting (KV precision, `keep_alive`) needs a new measurement. Different models now
run at different contexts, which is why the speed capability moves to one prompt size
([ADR-0150](0150-the-speed-capability-reads-prompt-throughput-at-one-size.md)). Under Ollama there
is no `--fit off`: a rung may spill to host RAM instead of refusing, and the ladder ceiling stays
the protection (ADR-0121 §4).

*Neutral.* `native.memory_kv` is unchanged. Its own `max_context_fit` still climbs at the run's
served context — which is now the fit — and keeps feeding `memory_efficiency`.

## Alternatives considered

* **Fix `memory_kv.max_context_fit` in place.** Rejected: the gate needs a short run of its own,
  and `memory_kv`'s slope and prefix tests need the fit before they can run at a meaningful context.
* **Measure on discovery.** Rejected by the operator: a ladder of launches is not something that
  should start because a file appeared in a directory.
* **Write the fit into `config.toml` per model.** Rejected: the run is the record. A number copied
  into configuration drifts from the measurement it came from and loses the profile it applies to.

# ADR-0149 — The console applies a measured context fit to LoadCoach, and a task profile may spill past it

**Status:** Accepted (2026-09-13)
**Relates to:** [ADR-0148](0148-context-fit-is-its-own-suite-and-gates-benchmarks.md) (the fit),
[ADR-0123](0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md) (the console reads
every application and edits every `config.toml`),
[ADR-0127](0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)
(a write is validated by the application first), [ADR-0023](0023-runtime-profile-resolution.md) §1/§4,
[ADR-0121](0121-freeweight-launches-llama-server-with-fit-off-and-caps-the-max-fit-ladder.md) §3
(LoadCoach keeps `--fit on`), [ADR-0119](0119-model-servers-run-under-a-host-memory-cap.md).
**Source:** Operator decisions, 2026-09-13 (row CF4/CF5, `docs/roadmap/context-fit-work.md`): show
the measured maximum in LoadCoach and use it as a known limit; an optional flag lets a model spill
to the CPU past it when a request needs more.

## Context

FreeWeight measures how much context fits (ADR-0148). The console's LoadCoach Models page already
shows that reading beside each model (rows WX7, WX9). LoadCoach itself never learns it, and serves
each model at `[runtime.models."<canonical_id>"].context_size`, else `[runtime].context_size`, else
a task profile's `min_context_tokens` (ADR-0023 §4).

Two ways to carry the number were weighed: a SetSpec payload that LoadCoach imports with the rest
of its evidence, or the console writing it into LoadCoach's configuration on the operator's word.

## Decision

1. **No new payload; LoadCoach imports no fit.** The console shows the fit beside the context
   LoadCoach is configured to serve and offers **Apply**, which writes
   `[runtime.models."<canonical_id>"].context_size = <max_successful_context_tokens>` into
   LoadCoach's `config.toml` through the validated write path (ADR-0127), audited as
   `loadcoach.context_fit_applied`, and leaves LoadCoach's restart pending like any other settings
   write. **Nothing applies on its own:** a changed context changes LoadCoach's runtime profile
   hash, and that is a decision, not a side effect of a benchmark finishing.
2. **A configured context is LoadCoach's known limit.** A task profile gains
   `constraints.allow_cpu_spill` (bool, default `false`).
   * `false` — today's behaviour: a profile needing more than the configured context is rejected
     `context_too_small`, and a request that does not fit is rejected `context_limit_exceeded`.
   * `true`, on a provider whose context is configurable — the context is raised to what the
     profile or the request needs, rounded up to the next power of two so that a stream of
     similar requests shares one launch. LoadCoach's llama-server keeps `--fit on` (ADR-0121 §3),
     so the extra KV cache displaces layers to host RAM rather than failing, under the memory cap
     (ADR-0119).

## Consequences

*Positive.* The measured number reaches routing without a schema, an import or a migration, and
the operator sees what they are applying next to what LoadCoach serves now.

*Negative.* A spilled execution runs under a profile no benchmark measured, so its capabilities
come from priors and the explanation says `evidence_profile_mismatch` — honestly. Raising the
context restarts the server, and decode after a spill is 5–20× slower (ADR-0121).

*Recorded, not changed here.* FreeWeight evidence for llama.cpp cannot bind in LoadCoach today
whatever the context: FreeWeight's profiles carry `--fit off` and no `keep_alive`, LoadCoach's carry
`keep_alive = "5m"` and no `--fit`, and the hash covers both. This installation's LoadCoach also
has no `[evidence]` source configured, so it holds no evidence at all. Aligning the two is its own
decision.

## Alternatives considered

* **A `model.context_fit` SetSpec payload imported by LoadCoach.** Deferred, not rejected: it is
  the right shape once LoadCoach must act on a fit by itself. Today every use of the number passes
  through an operator's decision, and the console already reads it.
* **Apply automatically when a fit run completes.** Rejected: it silently changes the profile hash
  every existing measurement of that model is matched against.
* **Spill detection on Ollama** (resident VRAM below the model's size). Deferred: the operator
  serves through llama.cpp, where `--fit` is the mechanism.

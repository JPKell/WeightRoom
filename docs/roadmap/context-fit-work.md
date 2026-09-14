# CF Work — the context-fit arc

**Started 2026-09-13** from an operator conversation about `native.performance` skipping its
8 192-token prompt case. The operator's decisions, in order: fix the adapter profile mismatch (it
may already be fixed — check); measure the maximum context per model, never automatically, and
refuse every other benchmark of a model until it is measured; benchmark at that context; show it
in LoadCoach and let the operator apply it; let a task profile spill past it; score speed at one
prompt size. **Groups of co-resident models are out of scope** and left for a later arc.

Same rules as [`weightroom-work.md`](weightroom-work.md) §2: nothing pushed, tagged or published;
**no version bumps** — every change goes under `## [Unreleased]`. Decisions:
[ADR-0148](../adr/0148-context-fit-is-its-own-suite-and-gates-benchmarks.md),
[ADR-0149](../adr/0149-the-console-applies-a-context-fit-to-loadcoach.md),
[ADR-0150](../adr/0150-the-speed-capability-reads-prompt-throughput-at-one-size.md).

Built in one session on branch `row/cf-context-fit` in worktrees `~/ai/worktrees/cf-freeweight`,
`cf-loadcoach` and `cf-weightroom`. Handoff: [`history/handoffs/CF_HANDOFF.md`](../history/handoffs/CF_HANDOFF.md).

| # | Phase → ships | Model · effort | Runs after | Work overview — and required reading | Why this model |
|---|---|---|---|---|---|
| CF1 | Adapter profile mismatch → FreeWeight (verify), LoadCoach | Opus 5 · high | — | FreeWeight's `bb0047d` narrows `adapters_registered` per base; verify on the live database, then give LoadCoach's routing the same narrowing (its registration states `True` for every base). ADR-0074 rule 3 | one session |
| CF2 | `native.context_fit` → FreeWeight | Opus 5 · high | CF1 | New suite; per-case `serve_context_tokens`; ladder skips rungs past the trained context; `GET /results/context-fit` reads it. ADR-0148 §1–3, §7 | one session |
| CF3 | Gate and fit context → FreeWeight | Opus 5 · high | CF2 | `[benchmarks] require_context_fit`; `CONTEXT_FIT_REQUIRED`; a run without an explicit context is served at the fit. ADR-0148 §4–6 | one session |
| CF4 | Apply a fit → WeightRoom | Opus 5 · high | CF2 | LoadCoach Models page: configured context beside the fit, **Apply** writes `[runtime.models."<id>"].context_size`. ADR-0149 §1 | one session |
| CF5 | `allow_cpu_spill` → LoadCoach | Opus 5 · high | — | Task profile constraint; raise a configured context to the need, next power of two. ADR-0149 §2 | one session |
| CF6 | Speed at one prompt size → FreeWeight | Opus 5 · high | — | `native.performance` `1.1.0` derives `prompt_tokens_per_second_at_4096`; mapping `1.1`. ADR-0150 | one session |
| CF7 | Hash alignment → finding only | Opus 5 · high | — | Why FreeWeight evidence cannot bind in LoadCoach; recorded in ADR-0149 and the handoff, no code | one session |

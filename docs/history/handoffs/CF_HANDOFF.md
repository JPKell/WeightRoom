# CF Handoff — the context-fit arc (rows CF1–CF7)

Built 2026-09-13/14 (UTC) in one session on branch `row/cf-context-fit`, in worktrees
`~/ai/worktrees/cf-freeweight`, `cf-loadcoach` and `cf-weightroom`. Nothing pushed, tagged or
version-bumped; every change is under `## [Unreleased]`. Schedule:
[`roadmap/context-fit-work.md`](../../roadmap/context-fit-work.md). Decisions: ADR-0148, ADR-0149,
ADR-0150.

## 1. What the operator asked

A `native.performance` run skipped its 8 192-token prompt case. After a conversation about what
`runtime.context_size` does on Ollama and llama.cpp, the operator decided: fix the adapter profile
mismatch (check whether it already is); measure each model's maximum context, by hand, and refuse
every other benchmark of a model until it is measured; benchmark at that context; show it in
LoadCoach and apply it there; let a task profile spill to the CPU past it; score speed at one
prompt size. Groups of co-resident models are left for a later arc.

The skip itself was correct behaviour: `prompt-8192` needs 8 448 tokens (prompt + 256) and the run
was served 8 192.

## 2. What was built

| Row | Repo | What |
|---|---|---|
| CF1 | FreeWeight | **Already fixed** by the operator's `bb0047d` (`serves_base` narrows `adapters_registered` per base in `create_run`). Verified on the live database: the last `PROFILE_MISMATCH` run is `01M2EEFK8JQFCZKBQJ391NR3JP` (2026-09-13 22:33Z); every run from 23:00Z records `adapters_registered = 0`; `freeweight.service` restarted after the commit. |
| CF1 | LoadCoach | The same defect, latent: a registration handed adapters stated `True` for every base on it. Narrowed per base in routing's candidate build. Not live here — LoadCoach has no adapter directory configured. |
| CF2 | FreeWeight | `native.context_fit` `1.0.0` (`benchmarks/context_fit/`): one case per rung, each declaring `serve_context_tokens`; `_build_request` serves such a case at it (warm-up included); a rung past the descriptor's trained context is skipped; the fit derives from the rungs tried, read from case ids (a refused launch stores no scorer detail). `GET /results/context-fit` reads it. |
| CF3 | FreeWeight | `[benchmarks] require_context_fit` (default `true`); `create_run(require_context_fit=, context_from_fit=)`; `measured_context_fit` matches on model, machine and the profile hash with `context_size` cleared; `CONTEXT_FIT_REQUIRED` (409, CLI exit 2). CLI, API and form pass the flags; an explicit context wins. |
| CF4 | WeightRoom | LoadCoach Models page: **Apply** beside a measured fit writes `[runtime.models."<id>"].context_size` into LoadCoach's `config.toml` (validated, audited `loadcoach.context_fit_applied`), *applied* when the file already says so. `apply_changes` takes tuple keys (canonical IDs contain dots). **Also fixed:** the reader looked for `canonical_id`; FreeWeight sends `model`, so the column was empty against a live FreeWeight — only the recorded fixture had `canonical_id`. |
| CF5 | LoadCoach | `constraints.allow_cpu_spill`; `resolve_runtime_profile(spill_to_tokens=)` raises a *stated* context to the next power of two at or above the need (profile `min_context_tokens`, or input + output budget + margin), before the request override. |
| CF6 | FreeWeight | `native.performance` `1.1.0` derives `prompt_tokens_per_second_at_4096`; `capability_weights.toml` `1.1` reads it for speed. |
| CF7 | — | Finding only, §4. |
| CF8 | FreeWeight | Operator follow-up (ADR-0151): the run engine's optional `next_cases(outcomes)` hook — asked after a test's listed cases until it returns nothing, outcomes read back from stored samples, `run_tests.total_cases` grown each round; `native.context_fit` halves the gap between the largest served rung and the smallest refused on multiples of 4 096; `benchmarks.max_fit_context_tokens` default 262 144 (also moves `native.memory_kv`'s default ladder and hash). |

## 3. What the plan got wrong, and decisions made in the session

1. **The SetSpec payload and LoadCoach import were dropped.** The plan proposed a
   `model.context_fit` payload imported by LoadCoach. The survey found the console already shows
   FreeWeight's fit on LoadCoach's Models page (rows WX7/WX9) and is the component allowed to write
   LoadCoach's config (ADR-0123). ADR-0149 records the payload as deferred, not rejected.
2. **`memory_kv.max_context_fit` could never measure a fit**, for two reasons: every rung is served
   at the run's context (row WPF10's one-launch rule), and its attempts are read from sample detail,
   which a failed sample does not have — so refusals were never counted. It is left unchanged; the
   new suite is where the number comes from.
3. **Not gated:** `run repeat` (it repeats a recorded profile), jurors (they are served under the
   candidate's profile, now the fit), providers that cannot set a context.
4. **A fit does not carry across `keep_alive`.** `keep_alive` is part of the profile hash, so a fit
   taken under one value does not apply under another, although it cannot change what fits. Kept,
   because the hash is the subject (ADR-0023); noted because it surprises.
5. **Apply trusts the posted number**; LoadCoach's `config validate --file` is the check.
6. **Not updated:** `MEMORY_SAFETY.md` still describes only `memory_kv`'s ladder — it has five
   mirrors, two in repos outside this arc. Ollama spill detection is deferred (ADR-0149).

## 4. CF7 — why FreeWeight evidence cannot bind in LoadCoach today

* LoadCoach matches evidence only on an equal `runtime_profile_hash`
  (`evidence_policy.profile_admits`). FreeWeight's llama.cpp profiles carry
  `provider_options = {"--fit": "off"}` and no `keep_alive`; LoadCoach's carry `keep_alive = "5m"`
  and no `--fit`. No FreeWeight llama.cpp measurement can match, at any context.
* This installation's LoadCoach has **no `[evidence]` section** — `evidence_sources` is empty and
  `capability_evidence` holds 0 rows; routing runs on priors, production data and declarations.
* LoadCoach's `~/.config/loadcoach/config.toml` has `server_path = "jpk"` under
  `[providers.llamacpp]`, which looks like a slip. Not touched.

## 5. Gates

Run in each worktree with the production venv's interpreter (Python 3.14.4) and
`PYTHONPATH=<worktree>/src` — the packages are namespace packages, so the worktree's directory wins
while the venv's editable suite packages stay as they are. Invocation, identical in all three:
`ruff format --check . && ruff check . && mypy src tests && lint-imports && pytest -m "not live and not performance"`.

| Repo | Commit | Result |
|---|---|---|
| LoadCoach | `6b863f1` | 1127 passed, 5 skipped; the one earlier failure was the OpenAPI snapshot (`allow_cpu_spill`), regenerated |
| WeightRoom | `f576fc3` | 2094 passed, 3 skipped, 1 failed — `test_every_state_changing_route_has_an_exercise`, fixed by an exercise for the new route; `tests/security/test_audit_routes.py` then 115 passed |
| FreeWeight | `7b2cffb` | 2823 passed, 30 skipped, 1 failed — a mapping test parsing its own `1.0` body that a version bump had rewritten, restored; the two mapping test files then 49 passed |
| FreeWeight (CF8) | `6cc9c96` | 2826 passed, 30 skipped, 1 failed — the config-schema golden, stale after the `BenchmarkSettings` docstring was rewrapped (pydantic copies it into the schema); regenerated, the schema and context-fit tests then 20 passed, `generate_config_reference.py --check` current |
| FreeWeight (CF9) | `5270e63` | 2828 passed, 30 skipped, 0 failed |
| FreeWeight (CF10) | `6ed73e8` | 2829 passed, 30 skipped, 0 failed |

## 6. Live verification

Worktree code against the real llama.cpp provider, isolated from the operator's data: a copy of
`~/.config/freeweight/config.toml`, a throwaway database (`freeweight db upgrade` first) and a copy
of `llamacpp/digests.json` (without it `models refresh` re-hashes every GGUF). Run
`01M2EQXSM2VWME4MSNNMS137NF`, `native.context_fit` on `Ministral-3-14B-Reasoning-2512-Q4_K_M`,
`--repetitions 1`, 2026-09-14 01:18–01:21Z, recorded profile `context_size = 8192`:

| Rung | Outcome | Prompt tokens |
|---|---|---|
| 8 192 | completed | 6 358 |
| 16 384 | completed | 12 993 |
| 32 768 | completed | 26 268 |
| 65 536 | failed, `PROVIDER_UNAVAILABLE` — llama-server exited before healthy | — |
| 131 072 | failed, same | — |

`max_successful_context_tokens = 32768`, `max_context_capped_by_configuration = 0`; peak VRAM
14.6 GB of 16 GB; no server left behind. The launches were watched at `--ctx-size` 8192, 32768 and
16384 (the case order is shuffled by the run's seed). Before ADR-0148 the same model on the same
card reported 8 192, capped.

**Refined, row CF8** — run `01M2ERX6WXE67WF4ZC3FC6A573`, 2026-09-14 01:36–01:39Z, ceiling 262 144:
8 192, 16 384, 32 768 served; 65 536, 131 072 and 262 144 refused; then 49 152 refused, 40 960
served (32 902 prompt tokens), 45 056 refused. **`max_successful_context_tokens = 40960`**, capped 0,
9 cases, three refinement launches, three minutes in all. Peak VRAM **15.94 GB of 16.3 GB** at
40 960 — about 370 MiB spare. Applied to LoadCoach, whose llama-server keeps `--fit on`, a desktop
that takes more VRAM makes it spill layers rather than fail; under FreeWeight's `--fit off` a later
benchmark at 40 960 can be refused at launch. The operator first chose an exact Apply, then (same day) a margin of one step, applied to both
sides — row CF9, ADR-0152: benchmarks run at, and Apply writes, the fit less 4 096 (36 864 here). The margin is
`[benchmarks] context_fit_margin_tokens` — row CF10, ADR-0153.

**The refusal is the card.** The failed launch's output is not kept — the per-port stderr log is
overwritten by the next launch on that port, and the sample stores only the message. Reproduced
by hand with the same argv (`--ctx-size 65536 --fit off`): `cudaMalloc failed: out of memory`
allocating a 10 240 MiB KV cache. Caveat for a reader: `native.context_fit` counts *any* failed
launch as a refusal, so a broken server binary would read as a small fit; the run's error text is
where to look.


## 7. For the operator

1. **WeightRoom `main` has uncommitted edits** (`CHANGELOG.md`, `fw_overview.html`,
   `tests/integration/test_freeweight_wx8.py`). Commit or discard them before merging this branch;
   `CHANGELOG.md` will need a hand merge.
2. Merge `row/cf-context-fit` in FreeWeight, LoadCoach and WeightRoom, then restart
   `freeweight.service`, `loadcoach.service` and the console.
3. **After the FreeWeight restart every benchmark is refused until its model is measured.** Run
   `freeweight run start --model <ref> --suite native.context_fit` per model you benchmark, or set
   `benchmarks.require_context_fit = false`.
4. After merging, run `FreeWeight/scripts/sync_docs.py --check` and
   `WeightRoom/docs/scripts/sync_component_docs.py --check`; neither could run against the worktree
   layout. The guide copies were edited by hand with the same text as their components.
5. Decide CF7: align the two profiles (ADR), and configure LoadCoach's `[evidence]` source.

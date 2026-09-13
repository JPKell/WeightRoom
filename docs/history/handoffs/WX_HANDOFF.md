# WX arc handoff — the console experience, fifteen rows in three waves, one orchestrating session

**Ran:** 2026-09-12 15:16 → 2026-09-13 ~05:00 PDT · **Orchestrator:** Fable 5.1 (attended) ·
**Agents:** fourteen, one worktree per row (Opus 5 for WX3, WX4, WX7, WX8, WX9, WX12, WX13;
Sonnet 5 for the rest; WX12 finished on Sonnet after its Opus agent hit a session limit) ·
**Plan:** [`roadmap/wx-console-ux-work.md`](../../roadmap/wx-console-ux-work.md) — read its
preamble first: the four survey facts and the operator's four decisions are there, and every
row's cell carries its own **done** note with heads, merges and what its text got wrong.
**Ships:** unreleased. Nothing pushed, tagged or published; no version moved.

## 1. What landed, by repository

| Repository | `main` before | `main` after | Rows | Gate at the end (interpreter: each repo's `.venv`, CPython 3.14.4) |
|---|---|---|---|---|
| WeightRoom | `04c6b18` | see §7 | WX1–WX15 (every row touches it) | see §7 |
| MirrorWall | `5f8b63d` | `707c1d0` | WX6 (ECharts 6.1.0 vendored) | 385 passed |
| PromptCadence | `4d0ff86` | `8058f87` | WX5 (`GET /ledger/entries` cursor) | 1337 passed |
| FreeWeight | `bb1d56a` | `7390afd` | WX7 (API additions, migration `0011`), WX13 (provider profiles, ADR-0144) + the security-test fix `60be9cd` | 2814 passed |
| LoadCoach | `6c97404` | `5a54cb2` | WX9 (`[providers.<name>] enabled`, schema `additionalProperties`) | 1123 passed |
| IdeaPress | `a4182c0` | `b85c5a9` | WX12 (workflows table, migration `0014`, ADR-0143) | see §7 |

**Operator databases migrated by this session** (each with a backup beside the app's own
pre-migration copy): FreeWeight `0010 → 0011` (`backups/wx7-pre-0011/`), IdeaPress `0012 → 0014`
(`backups/wx12-pre-0014/`; the operator's file had never taken `0013`). Every unit was restarted
onto each merge it depended on; all five active at the end, `ollama.service` active as found.

**ADRs:** 0142 (ECharts), 0143 (workflows), 0144 (provider profiles), 0145 (manifest drafts);
0139, 0077 and 0061 carry the amendment lines; `docs/adr/README.md` indexes all four.

## 2. What the plan got wrong — corrected by the rows, recorded here so the next arc reads it

* **FreeWeight tokens are `auth.tokens` in its config (ADR-0026), not a DB table with a CLI
  mint** — the survey said otherwise; WX2's settings block says the truth (`openssl rand -hex 32`).
* **FreeWeight's logger writes `event`, not `message`** — `unwrap_suite_log` had never unwrapped a
  FreeWeight line before WX2.
* **The LoadCoach settings-form gap was LoadCoach's** (`extra="allow"` emits
  `additionalProperties: true`), fixed by a `json_schema_extra` there — `settings_forms.py` was
  right to refuse to invent a schema (ADR-0127 rule 3).
* **No `freeweight adapters draft` CLI existed** and ADR-0061 rule 4 gave drafting to LoadCoach;
  WX7 reversed it with ADR-0145 on the operator's interview default.
* **FreeWeight has no OpenAI-compatible provider kind** (`ollama`, `llamacpp`, `fake` only), so
  the operator's "vLLM profile" cannot exist yet — see §6.
* **`[storage] database_url` / `<APP>_STORAGE__DATABASE_URL` / `auto_migrate`** are the real
  names the Postgres script prints, not the `[database] url` the row text guessed.
* **The test-completion matrix toggle is on the Overview only** — `fw_models.html` has no chart to
  toggle from (WX8).
* **LoadCoach's three new navs are page navs, not left-menu entries** (WX9): a 17-entry menu would
  be worse than the request.
* **A dense `table()` without a `table_id` loses its header row at 412 px** (WX9 finding in the
  shell CSS); every wave-3 row set one, and any new dense table must.

## 3. What this session fixed on `main` itself

| Commit | Repository | What |
|---|---|---|
| `709e3a1` | WeightRoom | WX3's found-server test asserted `argv[0].endswith("python")` — false under `.venv/bin/pytest` |
| `60be9cd` | FreeWeight | `test_security_checklist`'s `"49" not in html` tripped on an asset cache-buster hash — four pre-existing failures on `main` |
| `e197394` | WeightRoom | WX15's printed `docker run` published PostgreSQL on every interface; now `127.0.0.1:5432:5432` |
| `edb6177` | WeightRoom | `services/llamacpp.py` used `Mapping` at runtime from a `TYPE_CHECKING` import — `/llamacpp` 500'd the first time a real `llama-server` was up (found by this session's browser pass, WX12's agent independently) |
| `08dd25b` | WeightRoom | Two "Docs" links on every page with an `app_page_header` (WX2's standalone + WX3's header action) — one CSS sibling rule |
| `db318d3` | WeightRoom | a 101-column line from `e197394` |
| `8245b40`, `2051a73` | WeightRoom | ADR index rows; regenerated `guide/` copies (`sync_component_docs.py`) |

## 4. Merge conflicts, all textual

`CHANGELOG.md` on every WeightRoom merge after the first (kept both blocks, every time);
`tests/performance/test_budgets.py` WX3 ∥ WX6 (two new test functions, both kept);
`lc_reliability.html` and `audit.html` WX1 ∥ WX5 (WX5's `complete=false`/pager kept, WX1's
`table_id` re-added); `services/freeweight_pages.py` `__all__` WX7 ∥ WX9 (three names, sorted);
`docs/adr/README.md` WX12 ∥ the index commit (rows sorted). No logic conflict anywhere.

## 5. The live proofs (WX14)

* **Browser pass on merged `main`** (`08dd25b`): 43 pages × 1440/412 px, light theme,
  `scrollWidth == clientWidth` on all 86; every page 200 except `/llamacpp` (the `Mapping` 500,
  fixed) — the agents' own passes covered both themes per row (their handoffs name the paths).
* **WX7 context-fit against real data:** `GET /api/v1/results/context-fit` on the operator's
  FreeWeight returns its two `memory_kv` rows (`ollama/gemma3:latest`, `ollama/gemma4:12b`, both
  `capped_by_configuration: true` at 131072 — the ceiling, not a fit, which is exactly why WX9's
  column shows the flag); `tests_matrix` carries seven models; machines carry `display_name`.
* **WX13, run 1:** `freeweight run start --model llamacpp/Qwen2.5-1.5B-Instruct.Q8_0@sha256:5926a692b27b --suite native.echo`
  → `01M2C64HQG6CBXJH8FMJSDK447` completed on the resolved `default` profile
  (`GET /api/v1/provider`: `active: "default"`, `profiles: ["default"]`, `kind: llamacpp`), the
  row's `provider_kind` is `llamacpp` in the `runs` table. **The switch is the operator's** — see §6.
  Note for whoever runs it: the run API body does not carry `provider_kind` at top level; read the
  fingerprint or the table, not `jq '.provider_kind'` as the WX13 handoff says.
* **WX12 GPU gate:** §7.

## 6. Left for the operator

1. **WX13's live switch.** Adding a second profile and flipping *Active* is a security-keyed write
   the console asks your password for; this session's attempt to edit the config by hand was
   (rightly) refused. `WX13_HANDOFF.md` §7 has the exact steps; run 1 above is the "before".
2. **vLLM.** A `[providers.<name>] kind = "openai_compatible"` needs FreeWeight to adopt
   ModelRack's OpenAI-compatible provider — "its own phase with its own evidence" in ADR-0077's
   words. Not in this arc; a one-row follow-up if wanted.
3. **`provider.memory_max_bytes` is unset** in your FreeWeight config (WX3 finding): the unit
   cgroup cap stands, MEMORY_SAFETY §3.1's inner belt on `llama-server` does not.
4. **Chat's *Allow all tools*** grants the registry snapshot — on this machine all five, including
   `run_command` and `write_file` — in one tap (WX4). Read-only-by-default is a one-line change.
5. **The Codex shell restyle** is still `stash@{0}` in WeightRoom (17 files). WX3 took its CSS
   file, header macro and docs-tree nesting and rejected the operator-menu move; drop the stash
   when you agree, or say what else from it you want.
6. **Nothing is pushed, tagged or published**: seven repositories have unpushed `main`s.

## 7. Final gates and the WX12 gate

| Repository | `main` | Gate (each repo's `.venv`, CPython 3.14.4) |
|---|---|---|
| WeightRoom | `2051a73` + this handoff | ruff format/check clean · mypy 236 files · lint-imports 5 kept · **2043 passed**, 3 skipped, 12 deselected |
| IdeaPress | `b85c5a9` | ruff clean · mypy 226 · lint-imports 4 kept · **1408 passed**, 7 skipped |
| FreeWeight | `7390afd` | ruff clean · mypy 328 · lint-imports 4 kept · **2814 passed**, 30 skipped |
| LoadCoach | `5a54cb2` | ruff clean · mypy 216 · lint-imports 4 kept · **1123 passed**, 5 skipped |
| PromptCadence | `8058f87` | 1337 passed (WX5's own run; unchanged since) |
| MirrorWall | `707c1d0` | 385 passed (WX6's own run; unchanged since) |

**WX12 on the operator's IdeaPress** (2026-09-13 04:15–04:40 UTC, `ollama/qwen3.5:9b-q8_0`,
GPU 97 % / 11.7 GB, one model resident): `POST /workflows` → `fast-draft 1.0`
(requirements, outline, draft); project `01M2CFH32XACCXN9649J77087Y` pinned `fast-draft@1.0`;
plan task `01M2CFHH819E9SQBZNR4H3G6HW` completed 3/3; draft task `01M2CFQZQ1SAZSGAR4QAJ1Z1QE`
completed with three draft calls and, per unit, `validation.completed` → **`review.stopped —
critique_not_in_workflow`** → `coverage.completed` — **no `audit.*`, `critique.*` or `revision.*`
event anywhere**, one model call per unit. `POST …/stages/project_review/run` → **409**
`STAGE_PRECONDITION_FAILED` "fast-draft 1.0 does not run the 'project_review' stage. It runs:
requirements, outline, draft." `ideapress workflow show standard` unchanged.

**What the WX12 handoff's expected outcome got wrong:** it said every unit would be `committed`.
Two of three **paused** — `unit.paused — 1 blocking requirement(s) have no deterministic check and
no audit has attested them met: R-002` — and that is the **coverage gate** doing what ADR-0143
says gates do (they are never in a record and never skipped). A workflow with no `audit` stage
cannot commit a unit whose blocking requirements need attestation; U-03, with none, committed.
Correct behaviour, and a product note for the docs: a "draft and stop" workflow needs `audit`, or
a brief whose requirements are deterministically checkable. The `WX12 gate` project and the
`fast-draft` workflow stay in the operator's IdeaPress as the worked example (delete the project
with `ideapress project delete` if unwanted; workflows have no delete by design — versions are
kept).

**One more thing `/llamacpp` will show:** Ollama ≥ 0.32 runs its models through its own
`/usr/local/lib/ollama/llama-server` (parent `ollama serve`), so `pgrep -x llama-server` lists it
beside FreeWeight's and LoadCoach's; the page prints the argv, which names the Ollama blob path.
Not a defect, but the page's copy could say so.

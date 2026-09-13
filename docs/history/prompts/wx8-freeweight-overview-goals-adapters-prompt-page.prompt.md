# Kickoff — Row WX8: FreeWeight Overview, Goals, Adapters, Prompt page

**Row:** `WX8` in [`docs/roadmap/wx-console-ux-work.md`](../../roadmap/wx-console-ux-work.md) §1 — the
row's cell there is the specification; read it first, then its **Read** list. The arc preamble
(decisions the operator took, defaults taken) is at the top of that file. **Date written:** 2026-09-12.
**Model:** as the row's `Model · effort` cell.

**Repositories:** WeightRoom. **Worktree(s):** ~/ai/worktrees/weightroom-wx8 (branch row/wx8-freeweight-overview). **Throwaway console port:** 8779 / trust 8780; a throwaway FreeWeight on 18765 (fake provider) to re-record fixtures.

## Corrections from wave 1 (2026-09-12) — read before the row text

* **`app_page_header(view, title, section, supporting)`** now exists in `_app_page.html` (WX3) with
  no caller yet; every page this row builds or reshapes uses it. `params_b` / `context_k` (WX1) and
  the docs-link macro (WX2) are in the same file; `capability_badges` is in `_lc.html`.
* **Console pages live in the left menu** (WX3): `web/rendering.py` `CONSOLE_SIDE_NAV` has two
  sections and `app_side_nav` appends them under an app's own menu. Add your app's nav entries in
  that file's tuples for your app only.
* **The shell's CSS is `static/css/weightroom-shell.css`** (32 KB budget, `test_budgets.py`). Page
  kit classes (`kit-actions`, `kit-form`, …) are there. Add page-specific rules there only if they
  are shell-wide; otherwise a `<style>` block in the template as before.
* **Every complete table is already `sortable=true` + `table_id`** (WX1); keep that on any table
  you add. `ui.page_rows` (WX5) is the page size every `*_pages.py` reads per request — use it, not
  a constant.
* **FreeWeight tokens** are `auth.tokens` in its config (ADR-0026); there is no mint command.
* **LoadCoach `[providers.<name>]` values never reach the settings form** (WX3 finding): the schema
  types them at `providers.registrations.<name>` while the file writes `providers.<name>`, so
  `settings_forms.py` files them under `undescribed` with no values. WX9 fixes this first.
* Screenshots: WX1's method works — a throwaway console with no app config reads the operator's
  live applications over HTTP (GET only). It has no bearer tokens, so token-gated LoadCoach
  detail pages return 401; do not loop on them. Take those from fixtures.

## Corrections from wave 2 (2026-09-13)

* **ADR numbers taken:** 0142 (ECharts, WX6) and 0145 (FreeWeight writes manifest drafts, WX7).
  WX12 writes **ADR-0143**, WX13 writes **ADR-0144**.
* `app_page_header` has callers now (`ip_*`, `pc_*`, `fw_models`…); use it on every page you touch.
* **A dense `table()` with no `table_id` loses its header row at 412 px** (WX9 finding, shell CSS):
  give every dense table a `table_id`.
* `tests/fixtures/freeweight/dashboard.json` lacks `tests_matrix` — WX8 re-records it from a
  throwaway FreeWeight at `faa23fc` (fake provider) or authors it in that endpoint's exact shape.
* `FreeWeight/scripts/sync_docs.py` cannot run from a worktree (it resolves `../WeightRoom/docs`):
  mirror with `cp` and prove with `cmp`; the orchestrator runs the script after merge.
* `freeweight db upgrade` writes its own pre-migration backup; migrations run with SQLite FKs off.
  IdeaPress's latest migration is `0013`; FreeWeight's is `0011`.
* WX7's Compare page disables the checkbox of a metric FreeWeight marks *separated*.
* FreeWeight's `[provider]` today: `kind = llamacpp` on the reference machine with
  `context_size = 8192`, `fit_to_device = false`, `memory_max_bytes` unset (WX3 finding — for the
  operator, not this arc).

## Standing preamble

[`outstanding-work.md` §2](../../roadmap/outstanding-work.md) and
[`weightroom-work.md` §2](../../roadmap/weightroom-work.md), by reference. Nothing is pushed,
tagged or published. **No version bumps** — every change under `## [Unreleased]`.

## What you may do, and may never do

**You may:** work only inside your own worktree(s); commit on your own branch; run the full gate
in your worktree's own venv (it is already created — `.venv/bin/python`; name the interpreter in
your gate report); start and stop **your own** throwaway servers on **your own** port with
**your own** XDG tree under your scratchpad; read the operator's running applications over HTTP
(`127.0.0.1:8765` FreeWeight, `8766` LoadCoach, `8767` IdeaPress, `8768` PromptCadence, `8769`
WeightRoom).

**You may never:** touch the GPU (no model load, no `llama-server`, no Ollama generate, no
`pytest -m live`); run `systemctl --user` against `weightroom freeweight loadcoach ideapress
promptcadence ollama`; write to `~/.config/<app>` or `~/.local/share/<app>`; merge, rebase onto a
moving `main`, `git push`, tag, or `git add -A`; work in another row's worktree or on `main` in
any repository; edit `docs/roadmap/wx-console-ux-work.md` or `docs/roadmap/README.md`.

## Method

Docstring-first, `mypy --strict`, the page kit of `history/handoffs/WP1_HANDOFF.md` §3, fixtures
recorded from the application's own API shape, tests for every branch you add. Screenshots at
1440 px and 412 px in both themes for every page you change
(`~/.claude/projects/-home-jpk-ai-suite/memory/browser-screenshots-for-ui-work.md` describes the
Playwright + throwaway-console method; kill by environ-verified pid, never `pkill -f`). Write your
`CHANGELOG.md` entry as **one contiguous block** at the top of `## [Unreleased]`.

## Finish line

Gate green in every repository you touched (`ruff format --check .`, `ruff check .`, `mypy src
tests`, `lint-imports`, `pytest`), interpreter named; `git status --short` clean; commits at each
phase boundary, Conventional Commits, ending with the attribution line the session gives you;
`WeightRoom/docs/history/handoffs/WX8_HANDOFF.md` written on **your WeightRoom branch** (or,
for a row with no WeightRoom worktree, returned in your report) — the decisions you took, the
numbers you measured, what the row text got wrong. **Do not merge.** Report back: branch head(s),
the gate line(s), what is left for the GPU or a shared unit, and any decision you want reviewed
before merge. If you need the GPU, a shared unit, or another row's files, **stop and say so**.

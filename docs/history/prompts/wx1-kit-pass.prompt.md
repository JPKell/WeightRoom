# Kickoff — Row WX1: Kit pass

**Row:** `WX1` in [`docs/roadmap/wx-console-ux-work.md`](../../roadmap/wx-console-ux-work.md) §1 — the
row's cell there is the specification; read it first, then its **Read** list. The arc preamble
(decisions the operator took, defaults taken) is at the top of that file. **Date written:** 2026-09-12.
**Model:** as the row's `Model · effort` cell.

**Repositories:** WeightRoom. **Worktree(s):** ~/ai/worktrees/weightroom-wx1 (branch row/wx1-kit-pass). **Throwaway console port:** 8779 / trust 8780.

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
`WeightRoom/docs/history/handoffs/WX1_HANDOFF.md` written on **your WeightRoom branch** (or,
for a row with no WeightRoom worktree, returned in your report) — the decisions you took, the
numbers you measured, what the row text got wrong. **Do not merge.** Report back: branch head(s),
the gate line(s), what is left for the GPU or a shared unit, and any decision you want reviewed
before merge. If you need the GPU, a shared unit, or another row's files, **stop and say so**.

# WX3 — Shell navigation and the llama.cpp page

**Row:** `WX3` in [`roadmap/wx-console-ux-work.md`](../../roadmap/wx-console-ux-work.md) §1.
**Run:** 2026-09-12, unattended, in `~/ai/worktrees/weightroom-wx3` on branch `row/wx3-shell-nav`
from `main` at `6068956`. **Repository:** WeightRoom only. Nothing pushed, tagged or published; no
version bump — every change is under `## [Unreleased]`.

## 1. What shipped

| # | Change | Files |
|---|---|---|
| 1 | The shell's `<style>` block is `static/css/weightroom-shell.css`, served from `/app-static`, budgeted at 32 KB | `_shell.html`, the new stylesheet, `tests/performance/test_budgets.py` |
| 2 | `CONSOLE_PAGES` folds into `CONSOLE_SIDE_NAV` as a *Tools* section; `NAV_ITEMS` gains llama.cpp; both sections are appended under an application's menu and under the docs tree | `web/rendering.py`, `_shell.html`, `docs*.html` |
| 3 | `app_page_header(view, title, section, supporting)` at the top of `_app_page.html` | `_app_page.html`, `tests/unit/test_page_kit_macros.py` |
| 4 | The docs tree opens to the document being read, folder by folder | `_docs_tree.html` |
| 5 | `/llamacpp` — read-only: discovered servers, the GGUF directories, `MEMORY_SAFETY.md` §2.2 | `services/llamacpp.py`, `web/routes/llamacpp.py`, `llamacpp.html`, `web/app.py`, `services/doctor.py` |

## 2. The Codex stash — what was taken and what was not

`stash@{0}` ("codex WIP 2026-09-12 10:59") is a whole B4 shell restyle across 17 files. Nothing was
`stash pop`ed; every line below was retyped, so this row owns them.

**Adopted, rewritten:**

* **The externalised stylesheet.** The *idea* and the budget test, not the file. The stash's
  `weightroom-shell.css` (664 lines) is a different shell: a fixed 246 px rail, `body > header`
  and `body > main` pushed over by `margin-left`, and `.masthead h1` visually hidden — the brand
  removed from the top bar. The arc preamble records the brand top-left as **already correct**, and
  this row's own cell says the top bar *keeps* the brand, so that file could not be taken as it
  stood. The stylesheet here is the existing `<style>` block moved out byte for byte, with the row's
  own rules appended. **18.0 KB against the 32 KB budget.**
* **`app_page_header`.** The stash's macro, with two changes: `supporting` is only rendered when it
  is non-empty (an empty `<p class="muted">` is a blank line the eye has to account for), and the
  `aria-label` duplicating the pill on the availability wrapper is gone — the badge is text in the
  reading order already, and the wrapper's label made a screen reader say the state twice.
* **The docs-tree nesting.** Taken as written (`docs_folder_menu`, the `is-current` /
  `is-ancestor` classes, the `docs-nav-depth-N` indent), because it is self-contained and correct:
  the recursion only descends the branch that contains the open document.

**Rejected, with the reason:**

* **The operator menu moving into the left column.** The row's own nav cell says *"the top bar keeps
  brand, the four app tabs, the alerts indicator and the operator menu"*. The stash also renders the
  operator controls **twice** — a desktop card in the rail and a mobile copy inside Menu — with a
  second theme `<select>` and 20 lines of JavaScript to keep the copies in step, because MirrorWall
  wires one theme control only. That is a duplicated control and a second storage listener to fix a
  problem the top bar does not have. The operator menu stays where it is; the theme select stays
  single, which is what `tests/integration/test_shell.py` has asserted since W3.
* **`app_tab` replaced by a hand-written `.app-link`.** MirrorWall owns the app tab (design brief
  §5) and WM2 adopted it. Forking it into WeightRoom-local markup for an underline is a fork of a
  shared component, and the next MirrorWall release would not reach it.
* **The telemetry changes** — the `RESIDENT` meter deleted, the icon button replaced by a
  `HIDE`/`SHOW` text toggle, a `.telemetry-row` wrapper, `mirrorwallTelemetry.wire()/unwire()`.
  None of it is this row's, and dropping RESIDENT drops a figure the design brief §4 asks for.
* **`.shell-context`** (a "WeightRoom / Console" block above the menu). It restates the top bar's
  brand and the menu's own title.
* **The `docs_page.html` rework** (breadcrumbs, a sticky outline rail, `docs-page-layout`) and the
  `fw_dashboard` / `fw_runs` / `_app_state` edits. Out of this row, and `fw_*` belongs to WX1 and
  WX8; `_app_state.html` is WX1's line 16.

## 3. Decisions I want reviewed before merge

1. **`app_page_header` has no caller in this build.** The rows that compose pages over it are WX1,
   WX7 and WX8, and this row owns neither their templates nor `fw_runs.html` (which the stash
   converted). Rather than leave an unproved macro, `tests/unit/test_page_kit_macros.py` renders it
   directly — including that a stopped application's pill reaches the header verbatim. If the
   reviewer would rather see it in use immediately, `fw_runs.html` is the stash's own example.
2. **No `GET /api/v1/llamacpp`.** The Ollama pane has one and links to it. Adding one here means an
   `api.md` entry and a spec §7.1 line for a body nothing consumes, so the page is UI-only. Say so
   if the JSON shape is wanted; `LlamaCppReport` already has `ServerView.as_json`.
3. **Which §2.2 lines are checked.** Five expectations, all of them with a single definite reading:
   the two unit caps (the doctor's own function), FreeWeight's `provider.memory_max_bytes`,
   `runtime.context_size` and `runtime.fit_to_device = false`, and LoadCoach's
   `providers.*.memory_max_bytes` and `runtime.context_size`. **`benchmarks.max_fit_context_tokens`
   is deliberately absent**: §3.2 says to set it to `32768` for Ollama and leave it at the default
   for llama.cpp, so its "right" value depends on what the machine is measuring. A line that cannot
   be failed is a line that stops being read — the same reason the doctor does not flag IdeaPress's
   uncapped unit (W4).
4. **An application on another provider kind is skipped by name, not failed.** FreeWeight on
   `ollama` gets one sentence saying so and no rows; its unit cap is still checked, because the cap
   protects the host from whatever the application launches.
5. **`doctor._unit_cap_findings` is now public** as `doctor.unit_cap_findings`. One function, two
   readers, so the doctor and this page cannot disagree about whether a unit is capped.

## 4. What the row text got wrong, and what I found

* **"the GGUF directories … via their `config schema --json` values already in
  `settings_forms.py`" — half true.** FreeWeight's `provider.model_directory` is a typed field and
  comes straight out of `SettingsForm`. **LoadCoach's registrations do not.** The model types them
  at `providers.registrations.<name>.…` while the file writes `providers.<name>.…`, so
  `_schema_for_path` cannot resolve them: on the operator's own LoadCoach they arrive as
  `SettingsForm.undescribed == ('providers.ollama.kind', 'providers.ollama.base_url', …)` — names
  with **no values**. `services/llamacpp.py` therefore reads `SettingsForm.raw_toml` as well and
  lets a typed field win where there is one (`_values`). **This is a defect worth a row of its
  own**: the console's settings page shows LoadCoach's registrations only in the raw TOML editor,
  and **WX9 wants to render a registration's `enabled` checkbox and a llama.cpp quick-add over
  exactly these keys.** Either LoadCoach's document should type the file's own shape, or
  `settings_forms` should carry values for undescribed keys.
* **`executable_for` is for the five applications only** — it does `getattr(settings.apps, app)`.
  `pgrep` and `llama-server` are found with an injected `shutil.which`.
* **The reference machine, measured through this page:** FreeWeight is on `llamacpp` with
  `runtime.context_size = 8192` and `runtime.fit_to_device = false` (both pass), **but
  `provider.memory_max_bytes` is unset** — §3.1's inner belt on `llama-server` itself is not in
  place, so only the unit's cgroup cap stands between a bad fit and the host. LoadCoach is on
  `ollama`, so it is skipped. `/home/jpk/ai/models/llm` holds 22 GGUFs, 158.6 GiB.
* **A port is never guessed.** llama.cpp documents 8080 as its default, but a server whose argv
  names no `--port` gets `port = None` and no `/props` read: filling in 8080 would print whatever
  else is listening there as if it were a model server.
* **`--fit` unset is reported as unset**, not as `on`. `on` is llama-server's default, but the page
  must not print a value it did not read.

## 5. The gate

```text
/home/jpk/ai/worktrees/weightroom-wx3/.venv/bin/python — CPython 3.14
ruff format --check .   → 239 files already formatted
ruff check .            → All checks passed!
mypy src tests          → Success: no issues found in 232 source files
lint-imports            → Contracts: 5 kept, 0 broken
pytest                  → 1935 passed, 3 skipped, 11 deselected
pytest -m performance   → the shell's stylesheet 18.0 KB (budget 32 KB);
                          JS on the heaviest page (/apps/freeweight) 89.1 KB (budget 120 KB)
```

## 6. Screenshots

Throwaway console on `:8799` with its own XDG tree (`ss -ltnp` checked first; killed by
environ-verified pid). `/llamacpp`, `/`, `/apps/loadcoach` and two docs pages, at 1440 px and
412 px, in both themes:
`/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/wx3/shots/`.
No page scrolls horizontally at either width in either theme — the probe is
`scrollWidth - clientWidth` on the document element, and it found one at first: the §2.2 table
overflowed 412 px by 127 px until it was given `data-density="dense"`, which is what the 700 px
stacking rule keys on. **`ollama.html`'s `#memory-safety` table has the same omission and the same
overflow**, unchanged here because that page is not this row's.

The throwaway console was pointed at the operator's real `freeweight` and `loadcoach` executables
(`[apps.<app>] executable`, a read of `config schema --json` and of their config files, nothing
written) so the checklist and the directory listing show real values rather than an empty page.
Note for the next session: the console's own config file is `$XDG_CONFIG_HOME/**wr-gym**/config.toml`,
not `weightroom/` — the distribution name, not the package name.

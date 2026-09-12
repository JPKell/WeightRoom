# WX2 Handoff — Generic surfaces

**Row:** WX2 (`roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12, unattended, one sitting ·
**Model:** Sonnet 5 · high · **Kickoff:** `history/prompts/wx2-generic-surfaces.prompt.md`
**Branch:** `row/wx2-generic-surfaces`, worktree `~/ai/worktrees/weightroom-wx2` · **Not merged.**

## 1. What shipped

WeightRoom only, five surfaces, one contiguous `CHANGELOG.md` block:

| Surface | What changed |
|---|---|
| **Logs** | `app_logs.html`'s history and `_log_pane.html`'s live tail both render `<ol class="log-rows">` of three stacked lines per entry (timestamp+badge; app, version, pid; message with logger and request id) instead of the `table()` macro, which cannot hold three lines per row. `services/journal.py`'s `unwrap_suite_log` now returns a 5-tuple, lifting `request_id` and a version (see §2) beside `record_level`/`logger`; `JournalLine` carries both and `as_json()` serialises them. |
| **Database** | `database.html` gets a `Tables · Query · Admin` nav over the page's own existing `#db-tables`/`#db-query`/`#db-admin` ids (the id moved from the `<table>` elements — which can be absent — to the `<h3>` headings, which are always there). A table's own name is now a link to `…/database?sql=SELECT * FROM <t> LIMIT 100#db-query`, seeded by the GET handler's new `sql` query param (pre-fills the textarea, does not run it); *Browse rows* is a second, separate link to the existing guarded row browser (`/database/{table}`), which is untouched and stays the only path to a raw write. |
| **Tokens** | `services/tokens.py` gains `SCOPES_BY_APP` (`loadcoach`: read/write/admin, one choice — its own scope is cumulative and the CLI takes one value; `promptcadence`: read/write/approve/admin, several choices — ADR-0049 rule 2 keeps `approve` independent of `write` and `admin` "contains the rest") and `MULTI_SCOPE_APPS`. `tokens.html`'s scope field is a `<select>` (multi for PromptCadence) instead of free text; the route joins several chosen scopes with a comma before calling `create_token`, which is what each application's own `--scope` already expects. FreeWeight's `Tokens` menu entry is gone (`rendering.py`, one line out of its `_APP_PAGES["freeweight"]` tuple — nothing else in that file). |
| **FreeWeight tokens on Settings** | `settings.html` gets a `Create a token` notice for FreeWeight only, explaining that there is **no minting command at all** (see §2) — `auth.tokens` is a plain list a security-key field already lets an operator edit on the same page; the block says to generate one (`openssl rand -hex 32`) and paste it in. |
| **Docs** | `services/docs.py` gains `APP_BLURBS` (one sentence per application and package, transcribed from each's own `spec.md` §1). `_docs_tree.html`'s `section_listing` macro takes an optional `blurbs` map and renders one under a folder's heading when present; `docs.html` passes `APP_BLURBS`. Every application page now links to its own entry (`/docs?section=apps#docs-apps-<name>`) through a new `docs_link(app)` macro in `_app_page.html`, used from `_app_state.html` (so ~56 of the ~62 application-tab pages get it with no per-template edit) and added directly to `database.html` and `tokens.html`, which do not include `_app_state.html`. |

**Also fixed, found live, in scope because it is the same function:** `unwrap_suite_log` only ever
matched a `"message"` key. FreeWeight's own `JsonFormatter`
(`freeweight/observability/logging.py`) writes `"event"`, not `"message"` — checked against the
operator's actual running `freeweight.service` journal (via the throwaway console, read-only,
`journalctl -u freeweight.service`), every one of its lines was landing in the pane as a raw,
un-unwrapped JSON blob, with no level, no logger and no request id recovered, since before this
row. The function now reads `message` first, falling back to `event`; a regression test pins both
shapes. This is a WeightRoom-only fix (the check lives in `services/journal.py`); FreeWeight's own
formatter is untouched and not this repository's file.

## 2. Decisions taken

1. **Version key: `version`, else the first `*_version` key.** FreeWeight's formatter writes a
   top-level `version`; LoadCoach's writes `loadcoach_version`; IdeaPress's and PromptCadence's
   write neither yet. Rather than hardcode four (and grow the list for every future logger),
   `_version_of` checks `version` first, then scans for any key ending `_version`. Confirmed live:
   WeightRoom's own journal lines actually carry `weightroom_version` this way.
2. **The `event`-vs-`message` key was not in the kickoff text at all** — found by loading the
   FreeWeight Logs page against the operator's real running service and reading the rendered page,
   not by re-reading the spec. Fixed in the same function this row already owns; flagged here
   because a fix outside the row's named scope always needs saying, even when it is one `if`.
3. **The kickoff's `freeweight token create --scope …` does not exist.** FreeWeight's CLI has no
   `token` subcommand at all (checked `~/ai/suite/FreeWeight/src/freeweight/cli/commands/*.py` —
   no `token.py`, no `token` typer app registered in `main.py`); `auth.tokens` is a bare
   `tuple[str, ...]` config field with no minting helper anywhere. The kickoff's "defaults taken
   without asking" line already anticipated this ("the settings page says to run `freeweight token
   create`") and got the same thing wrong. The Settings block says what is actually true instead:
   generate the string yourself, paste it into the existing `auth.tokens` field. No FreeWeight code
   was touched or needed to be — the ADR-0127 generic form already treats `auth.tokens` as a secret
   field behind the security-key password gate, because its leaf name matches `_SECRET_LEAF`.
4. **The docs link's mechanical placement.** The kickoff's may/may-never list permits `_app_page.html`
   changed only "at one spot" for this — read as: add one macro there, not a per-template edit
   across dozens of files. `_app_state.html` (not in the exclusion list, included un-parameterized
   in the large majority of application-tab pages right below the page's own heading) was the one
   place a single addition reaches nearly every page without touching each one; `database.html` and
   `tokens.html`, which render their own state and never include `_app_state.html`, get the link
   added directly since I was already editing both files for their own surfaces this row.
   `settings.html`, `prompt.html`/`prompts.html` and a few others do not include `_app_state.html`
   and were not otherwise being touched this row, so they do not carry the link yet — a candidate
   line item for whichever row next touches `_app_page.html`/the shared header (WX3 builds
   `app_page_header`, which is a more natural long-term home for this).
5. **Database anchor ids moved from the `<table>` elements to the `<h3>` headings.** The Tables
   list and the query-results table both already carried ids (`db-tables`, `db-query`) for
   unrelated reasons (a CSS selector on the query table). Both are conditionally rendered — an
   empty tables list or a page with no query run yet omits the element — so an anchor targeting
   either would resolve to nothing on a first visit. The headings are unconditional; the query
   results table's id moved to `db-query-results` and its CSS selector moved with it.
6. **The multi-select scope's comma join happens in the route, not in the template or in
   `services/tokens.py`.** `create_token` still takes one already-joined `scope: str` — unread and
   passed straight to the application's `--scope`, per the existing design — so nothing about what
   an application receives changed; only how the page collects it did.

## 3. Fixtures, tests

Every new branch has a test: `unwrap_suite_log`'s five return slots (`request_id` present/absent,
`version` from a literal `version` key, from `loadcoach_version`, from neither, and from
FreeWeight's `event`-keyed shape); the database page's nav anchors, seeded-query link and
`Browse rows` link; the tokens page's per-app `<select>`/`<select multiple>` rendering and the
route's comma-join, verified against a fake CLI that records its own argv (not just its stdout).
No fixture files were re-recorded — none of the three JSON fixture directories under
`tests/fixtures/` were touched.

## 4. Demonstration

Throwaway console, `127.0.0.1:8789` (trust `8790`), this row's own XDG tree under the session
scratchpad, closed by environ-verified pid both times it was restarted (once to pick up the
`event`-key fix, once for a config change). No password: fresh config is open-loopback.
Screenshots at 1440 px and 412 px, light and dark, for every page this row changed (Logs, Database,
Tokens ×3 apps, Settings/FreeWeight, Docs ×2 sections) — 36 files under the session scratchpad's
`wx2/shots/`, plus several closer single-viewport captures used to read small text during review.
FreeWeight's real Logs (§1's fix) were read against the *operator's own running* `freeweight.service`
via `journalctl` (read-only; no write, no `systemctl`, no HTTP call to it) to get real content to
screenshot and to find the `event`-key defect in the first place; LoadCoach's and PromptCadence's
Tokens pages and FreeWeight's Settings page were exercised against three small fake executables
written under the session scratchpad (never touching `~/.config/<app>` or any real installation) so
the `<select>`/`<select multiple>` and the `auth.tokens` security-key field would actually render
instead of a "not installed" stub.

## 5. Gate

WeightRoomGym `.venv`, **Python 3.14.4**: `ruff format --check .` (235 files), `ruff check .` (all clean),
`mypy src tests` (228 source files, no issues), `lint-imports` (5 contracts kept, 0 broken),
`pytest -q` → **1919 passed, 3 skipped, 10 deselected** (1909 base + 10 new: 7 in `test_journal.py`,
2 in `test_tokens_and_doctor_routes.py`, 1 in `test_database_routes.py`; the pre-existing count was
1909 before this row's tests were added, which itself is unchanged from a bare rerun, confirming no
prior test was broken).

`git status --short` — clean except the 19 files this row touched (listed in the commit); nothing
else in the tree moved.

## 6. What is left for another row, or a shared unit

* **The docs link is not on every application page yet** (§2 item 4) — `settings.html`,
  `prompt.html`, `prompts.html` and any other page that renders its own header without
  `_app_state.html` still lack it. WX3's `app_page_header` macro is the natural place to fold this
  in permanently, rather than adding it file-by-file.
* **FreeWeight's `event`-vs-`message` divergence is fixed on the reading side only.** Nothing stops
  a fifth logger from spelling its key a third way; `unwrap_suite_log`'s two-key check is not a
  contract, and the suite's Observability Standards do not currently pin one key name across the
  four loggers. Worth a standards note if a fifth application's logger ever needs unwrapping too.
* **No GPU, unit restart, or another row's file was touched.** Nothing here needs the operator's
  live instances beyond the read-only `journalctl` reads described in §4.

## 7. What the kickoff got wrong

* **"`freeweight token create --scope …`"** does not exist (§2 item 3) — corrected on the page.
* The kickoff's file list for this row did not mention `unwrap_suite_log`'s `message`/`event` key
  mismatch at all (§1, §2 item 2) — it was found by looking at the real page, not by re-reading
  the spec cell.

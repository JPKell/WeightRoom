# WY7 handoff — chat history on its own page

**Row:** `WY7` in `docs/roadmap/wy-console-polish-work.md` §3. **Branch:**
`row/wy7-chat-history`, from WY1's gate A commit `ebc659e857c92b6a281dc66a267467be6013ded1`.
**Worktree:** `~/ai/worktrees/weightroom-wy7`. **Interpreter:** `python3.14` (3.14.4) in the
worktree's own `.venv`, with `baseaicore`, `setspec`, `weightsdb`, `mirrorwall`, `sweatmeter`,
`modelrack` and `loadledger` installed editable from `~/ai/suite/py` (verified via
`pip list --editable`, not from PyPI).

## What was built

* `GET /chat/history`, registered ahead of `GET /chat/{conversation_id}` in `web/routes/chat.py`
  so the literal path is never read as an id. `chat_history.html` renders a dense, sortable
  `table()` (`table_id="chat-history"`) — Title (linked to the thread), Mode, Messages, Updated —
  from the same `list_conversations` call the rail used; an empty history shows `empty_state`
  with a link to `/chat`.
* The row's title is built safely with `('<a href="/chat/%s">%s</a>' | safe) | format(id, title)`,
  **not** `~`-concatenation with a separately `| e`-escaped title. The two are not equivalent under
  autoescape: concatenating a plain `str` with a `MarkupSafe`-escaped fragment via `~` triggers
  `Markup.__radd__`/`__add__`, which escapes the *other*, already-trusted literal parts of the
  string too (`<a href="...">` came out as `&lt;a href=...&gt;`). `| format` on a `Markup` template
  string escapes only the substituted arguments, which is what every other cell-building template
  in this app (`docs_adrs.html`) gets right by never mixing `| e` into a `~` chain — worth a
  grep across the other page-kit templates if this pattern comes up again. Covered by
  `test_a_conversation_title_in_the_history_table_is_escaped`.
* Clicking anywhere in a history row opens its conversation — a delegated click handler in
  `chat.js`, added as a second, independent IIFE (the existing one early-returns when the composer
  isn't on the page, which must not skip this). The title's own `<a>` still works with no JS and
  the keyboard.
* The rail (`_chat_rail.html`) is deleted; `chat.html` and `chat_thread.html` no longer include
  it, no longer receive a `conversations` list they don't render (chat_thread) or render one only
  for the `{% if not conversations %}` empty hint (chat.html, which still needs the count). The
  freed width goes to `.chat-pane` (no more `.chat-layout` flex row); the narrow-width rail rules
  in `chat.css` are gone with it.
* Every chat page carries `page_nav` (row WY1, `_app_page.html`) with a `JSON` action (the
  matching `/api/v1/chat/conversations[...]` URL) — **see the decision below on the `links`
  list**.
* `chat_thread.html`: JSON moved from the old `.page-actions` strip into the page bar's actions.
  Delete stays a CSRF POST form, now a sibling of the `<h2>` inside `.page-head` (already
  `display: flex; align-items: center` in `weightroom-shell.css`) with `display: inline-flex` of
  its own (`.chat-delete-inline`) so its button's box lines up on the heading's baseline instead
  of stretching to the row's height. Checked at 412 px with both a long (wraps, same as the old
  `.page-actions` did) and a short title (stays on one line) — screenshots below.

## Decision to flag: no "New conversation" link in the page bar

The kickoff's §2.1 example, and the row text itself, call for
`page_nav(links=[New conversation → /chat, History → /chat/history], …)`, reasoning "Chat is in
the top bar and the left menu (WY1), so neither link is a duplicate."

That isn't true on **this branch's own base** (WY1 gate A only, not gate B). I read gate B
(`row/wy1-shell-nav`, not merged here — file ownership forbids editing `web/rendering.py`) to
check: it adds Chat to the top bar but its own commit message says Chat "**stays in** the Tools
section" of `CONSOLE_SIDE_NAV`, and `render_shell_page`'s default `nav_sections` (used by every
chat page, since none of them pass their own) is still `CONSOLE_SIDE_NAV` even after gate B. So
`<a href="/chat">Chat</a>` is in the left menu's Tools section on **every** page, unconditionally,
including the chat pages themselves, both before and after gate B — there is no page-context
exclusion for the console's own pages, only for application tabs and the docs viewer.

Given that, a page-bar link to `/chat` — from `chat.html`, `chat_thread.html` or
`chat_history.html` — always repeats an `href` already in `nav.side-nav`, which
`tests/integration/test_page_nav.py` (row WY1, a **shared** contract) refuses on every rendered
page. I confirmed this by reproducing it directly (see `git log -p` if the diff is wanted) before
dropping the link, rather than assuming.

**What shipped instead:** `page_nav(links=[History → /chat/history], actions=[JSON → …])` — no
`New conversation` entry — on all three chat pages. The left menu's existing `Chat → /chat` link
(present on every page already) is what a caller uses to start a new conversation from
`/chat/history` or a thread; nothing is unreachable, only not repeated. Pinned by
`test_no_page_bar_link_on_any_chat_page_repeats_the_left_menu` in the new
`tests/integration/test_chat_history.py`.

**For review:** if WY10's merge changes `CONSOLE_SIDE_NAV` to exclude a console page's own entry
on itself (which neither gate A nor gate B does today), the `New conversation` link becomes safe
to add back — it wasn't dropped as an unwanted feature, only because it fails a hard, shared gate
on the branch this row builds against.

## Gate

Run from `~/ai/worktrees/weightroom-wy7`, interpreter `python3.14` (3.14.4) in `.venv`:

```
ruff format --check .    # clean (one file reformatted before commit)
ruff check .             # All checks passed!
mypy src tests           # Success: no issues found in 238 source files
lint-imports              # Contracts: 5 kept, 0 broken.
pytest                    # 2053 passed, 3 skipped, 12 deselected, 189.01s
```

`git status --short` is clean after the commit below; only WY7-owned files changed (`chat.html`,
`chat_thread.html`, `_chat_rail.html` (deleted), `static/css/chat.css`, `web/routes/chat.py`, the
new `chat_history.html`), plus one shared, one-block `CHANGELOG.md` entry and
`tests/integration/test_chat_loadcoach.py`, whose two rail-shape assertions
(`test_the_chat_page_rails_the_conversations_and_pins_one_composer`,
`test_the_thread_page_marks_the_open_conversation_and_fixes_its_mode`) were rewritten to check for
the rail's *absence* and the page bar's presence instead — the rail they asserted no longer
exists, per this row's own instructions to remove it.

## Screenshots

Throwaway console, port 8811 / trust 8812, `open loopback` (no operator account needed), seeded
with three fixture conversations (including one with `<script>alert(1)</script>` in the title, to
prove the escaping) directly into its SQLite file via `create_conversation` — no message was ever
sent, so no live LoadCoach or PromptCadence was touched. 1440 px and 412 px, light and dark, for
`/chat`, `/chat/history` and one conversation thread, plus one extra 412 px shot of a
short-titled thread to show the Delete/JSON line holds at realistic widths (the long XSS-test
title wraps, same as the old `.page-actions` strip did — not a regression).

Saved under the session's scratchpad (`wy7-console/shots/`); paths as rendered in this session:
`chat_{1440,412}_{light,dark}.png`, `chat_history_{1440,412}_{light,dark}.png`,
`chat_thread_{1440,412}_{light,dark}.png`, `chat_thread_short_412.png`.

## What this plan got wrong

The `page_nav` example pair ("New conversation · History") in roadmap §2.1, repeated in this
row's own kickoff, doesn't hold against the branch base wave 2 actually builds from — see the
decision above. Nothing else in the kickoff needed correction.

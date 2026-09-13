# Kickoff — Row WY7: chat history on its own page

**Row:** `WY7` in [`docs/roadmap/wy-console-polish-work.md`](../../roadmap/wy-console-polish-work.md)
— read §2.1, §2.4, §4 and §5 first. **Written:** 2026-09-12. **Model:** Sonnet 5 · medium.
**Wave:** 2.

**Repository:** WeightRoom. **Worktree:** `~/ai/worktrees/weightroom-wy7`, branch
`row/wy7-chat-history`, from **WY1's gate A commit** (§2.4). **Throwaway console:** 8811, trust 8812.

```bash
BASE=$(git -C ~/ai/suite/WeightRoom log row/wy1-shell-nav --grep='row WY1 gate A' -1 --format=%H)
test -n "$BASE" || { echo "WY1 gate A not committed yet — stop"; exit 1; }
git -C ~/ai/suite/WeightRoom worktree add ~/ai/worktrees/weightroom-wy7 -b row/wy7-chat-history "$BASE"
cd ~/ai/worktrees/weightroom-wy7 && python3.14 -m venv .venv
.venv/bin/pip install -q -e ".[dev]" && .venv/bin/pip install -q -e ~/ai/suite/py/MirrorWall
```

**Read before code:** `web/routes/chat.py`, `chat.html`, `chat_thread.html`, `_chat_rail.html`,
`static/css/chat.css`, `static/js/chat.js`, and `history/handoffs/WX4_HANDOFF.md`, if present, for
why the rail exists.

## What the operator asked for

* **Chat history on a different page, under Chat.** Add a *History* button in the chat page bar. It
  shows a **table** of conversations, and **clicking a row takes you back to the chat page** for that
  conversation.
* On a conversation, the **JSON link and the Delete button sit on different lines**: put them on one
  line.

## Build

1. **`GET /chat/history`** (UI router; registered before `/chat/{conversation_id}`, so the path is
   not read as an id). It renders `chat_history.html`: a dense, complete, sortable `table()` with a
   `table_id`, and columns Title, Mode (backend), Messages (numeric), Updated (mono). The data
   comes from the same service call the rail uses. Each row's title links to `/chat/<id>`; make the
   whole row clickable with a small delegated handler **in `chat.js`**, keeping the link for no-JS
   and keyboard use. An empty history uses `empty_state` with a link to a new conversation.
2. **Page bar on every chat page:** `page_nav(links=[New conversation → /chat, History →
   /chat/history], actions=[JSON → the matching API URL])`, with `current` set. Chat is in the top bar
   and the left menu (WY1), so neither link is a duplicate. Add the *History* link to the
   duplicate test's fixtures if it needs a conversation.
3. **Remove the rail** from `chat.html` and `chat_thread.html`, and delete `_chat_rail.html` if
   nothing else includes it. Give the chat pane the freed width. Remove the rail rules from
   `chat.css`. Stop passing conversation lists to pages that no longer render them. Drop the
   explanatory paragraph under *New conversation*, as the operator's uncommitted edits did on other
   pages: keep only the form.
4. **JSON and Delete on one line** in `chat_thread.html`. Put the JSON link into the page bar's
   `actions`. Delete stays a POST form (CSRF), rendered inline at the end of the heading row
   (`display: inline-flex` form, a quiet button). Its baseline must line up with the heading's text.
   Check it at 412 px.

## Tests

`/chat/history` renders every conversation newest first, links each to `/chat/<id>`, and shows the
empty state with none; `/chat/history` is not treated as a conversation id; Delete still requires
CSRF and still deletes (the existing tests pass); no page includes the rail; the page-nav duplicate
test passes. Screenshots of `/chat`, `/chat/history` and one conversation, at 1440 px and 412 px,
light and dark. Use a throwaway console with fixture conversations; do not send a message to a live
LoadCoach or PromptCadence.

## Out of scope

The conversation streaming, approvals and attachments behaviour; the top-bar Chat link (WY1); and
any file §4 gives to another row.

Finish line, commits, `WY7_HANDOFF.md` and report: roadmap §5.

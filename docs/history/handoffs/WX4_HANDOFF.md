# WX4 Handoff — Chat

**Row:** `WX4` of [`roadmap/wx-console-ux-work.md`](../../roadmap/wx-console-ux-work.md) §1
(Opus 5 · high, agentic). **Date:** 2026-09-12. **Kickoff:**
[`wx4-chat.prompt.md`](../prompts/wx4-chat.prompt.md).
**Repository:** WeightRoom only. **Worktree:** `~/ai/worktrees/weightroom-wx4`, branch
`row/wx4-chat`, branched from `main` at `6068956`. **Not merged.** No version bump — everything
under `## [Unreleased]`, in its `### Changed` section as one contiguous block.

## 1. What was built

| File | What |
|---|---|
| `web/static/css/chat.css` **(new)** | The chat pages' own stylesheet: the rail, the pinned composer, and the message rules lifted out of `chat_thread.html`'s inline `<style>`. Every rule is scoped to a `chat-` class; nothing touches the shell (WX3 owns `weightroom-shell.css`). |
| `web/static/js/chat.js` **(new)** | The new-conversation composer's two conveniences: the mode select hides the other backend's fieldset, and the tool allowlist gains a picker and an *Allow all tools* checkbox. 1.6 KB. |
| `web/templates/_chat_rail.html` **(new)** | The conversation rail, included by both pages. |
| `web/templates/chat.html` | Rail + a **New conversation** pane whose composer holds `Mode and settings` (mode select, optional title, the chosen backend's fields, the tool controls) and the message box. |
| `web/templates/chat_thread.html` | Rail + thread + the composer pinned to the bottom, with the conversation's mode shown **disabled** in its own `<details>`, the attachments block beside it, and *Delete* moved into the page head. The SSE script is unchanged but for two lines (§3.4). |
| `web/templates/_chat_message.html` | Every non-answer frame under one `<details class="chat-details">`; approvals outside it. |
| `web/routes/chat.py` | `_tool_choices`, the rail's `conversations` on the thread page, `POST /chat` now takes the first message and derives a title. |
| `services/chat_promptcadence.py` | `registered_tool_names(client, settings)`. |
| `tests/integration/test_chat_{loadcoach,promptcadence}.py` | Ten new tests (§4). |

## 2. The layout

The chat is one shape on both pages: **rail left, pane right**, the composer last in the pane and
pinned with `position: sticky; bottom: 0`. Sticky was chosen over a full-height flex column on
purpose — the shell's own grid is untouched, the document keeps one scrollbar, and the composer
un-pins at its natural place when the thread is short. It is the only layout escape hatch this row
needed, and it lives in `chat.css`, scoped to `.chat-composer`.

The rail is `<nav class="chat-rail">`: *+ New conversation*, then every conversation newest first,
each line title + `backend · message count`, the open one `aria-current="page"`. Under 900 px the
layout stacks and the rail caps at `40vh` with its own scrollbar.

## 3. Decisions taken — **the ones to review before merge**

### 3.1 "Allow all tools" writes the names, and only the registered ones

`GET /tools` reports every *configured* tool with a `registered` flag and, when withheld, the cause.
**Allow all** fills the comma list with the names PromptCadence has actually **registered**, today,
at that moment. Two deliberate consequences:

* **Never an omitted key.** PromptCadence reads a missing `tools` field as *every configured tool*
  (W6 §3.1, `chat_promptcadence.submit_trajectory`), so the console writes the names instead. What
  was allowed is auditable in `conversations.tools` and in the submission body.
* **A snapshot, not a standing grant.** A tool registered tomorrow does not join a conversation
  agreed today, and a withheld tool is never offered because it cannot run. On the reference machine
  today that snapshot is `http_fetch, list_dir, read_file, run_command, write_file` — all five,
  `run_command` and `write_file` included. **That is the edge the operator should look at:** one tap
  grants a trajectory the command runner and the file writer, by name, with no second confirmation.
  The alternative (offer only the read-only tools, make the rest one-by-one) was not taken because
  the row's default says "the registry snapshot"; say the word and it becomes read-only-by-default.

PromptCadence is asked for the registry **only when its unit says it can answer**, so a LoadCoach
conversation costs no call. Stopped, refused or silent, the page says so in PromptCadence's own
words and the allowlist stays the free-text input it has always been (three tests, §4).

### 3.2 The mode is per conversation, and the composer says so twice

`create_conversation` drops the other backend's fields, so a conversation's mode is fixed for its
life. The composer therefore renders the mode select **only enabled on `/chat`**; on a thread it is
`disabled`, shows the conversation's mode, and carries the hint *"Fixed when the conversation
started. Start a new conversation to use the other one."* The thread's settings block posts nothing
at all — the backend's fields are disabled inputs, shown so the operator can read what this thread
runs under. A per-message switch is not modelled, as the row says.

### 3.3 One composer starts the conversation **and** sends its first message

This is the one place the row left open, and the one place this row went beyond it. An OpenAI-shaped
composer that only names a conversation and then makes you type again is not a composer, so
`POST /chat` now accepts `text`: the conversation is created, the message is sent, and the thread
opens with the reply streaming. The **title is optional** and taken from the first message's first
line (80 characters, ellipsised) when blank. An empty `text` still just creates the conversation, so
the JSON API and the audit-route test are untouched. Review if the operator wants a named title back
as a requirement.

### 3.4 The frames wrapper is open while the reply streams

`<details class="chat-details">` holds thinking, the plan/step/tool-call/egress cards and the
routing-and-cost block, summarised `Details · N steps` where N counts what is inside it. It is
**closed** on a finished reply and **open** while one streams — otherwise ADR-0132's whole point
(watch the model think, live) would be behind a click. The server-rendered replacement fetched at
`done` is closed, so the fold happens by itself. While streaming the summary is just `Details`: the
count would go stale between card frames.

**Approval cards sit outside the wrapper**, all of them, requested and resolved alike, keeping their
auto-open: a decision nobody has taken is never a click away, and the granted card then appears
where the pending one was.

The SSE script's reach-ins (`chat_thread.html`) needed exactly one new line — `wrapper.open = true`
on the first thinking delta, belt and braces since the wrapper is already rendered open. Everything
else (`.chat-thinking`, `.chat-live`, `.chat-waiting`, `refresh`) still resolves by descendant
lookup. SSE itself is untouched (ADR-0004).

### 3.5 The "Sending is off" notice moved **inside** the composer

Found in the browser at 412 px: the pinned composer covered the notice, which is the one element
that always sits directly above it. It is now the composer's first child, so it travels with it.
`#chat-unavailable` keeps its id, which the script reads.

## 4. Tests

Ten added, all in the existing chat files:

* the rail lists newest-first and the page pins one composer; the thread marks the open
  conversation and renders the mode select disabled, submitting no `backend`;
* the composer creates and sends, the title comes from the message, a long message is ellipsised at
  80, a typed title survives;
* every non-answer frame is inside `<details class="chat-details">` (closed) and the answer is
  outside it, `Details · 2 steps` for a LoadCoach reply;
* the tool select offers registered tools only, `data-all` carries the snapshot, a stopped
  PromptCadence and a refused `GET /tools` both leave the free-text input with the reason;
* a pending approval stays outside the wrapper with its Approve button.

The `Allow all` / picker JavaScript is exercised in a real browser, not in pytest (§5).

## 5. Verification

```bash
cd ~/ai/worktrees/weightroom-wx4        # branch row/wx4-chat
PY=.venv/bin                             # Python 3.14.4
$PY/ruff format --check . && $PY/ruff check . && $PY/mypy src tests && $PY/lint-imports
$PY/python -m pytest -q
$PY/python -m pytest tests/performance/test_budgets.py -m performance -k javascript -s
```

Measured: `ruff format --check .` 235 files, `ruff check .` clean, `mypy src tests` clean (228
files, strict), `lint-imports` 5 contracts kept, `pytest` **1914 passed, 3 skipped, 10 deselected**
(1904 before this row). JavaScript budget: `chat.js` **1.6 KB**, heaviest page unchanged at
**89.1 KB of 120 KB** (ADR-0139) — no new budget case was needed, the existing test walks every
GET page and counts every `<script src>`, `chat.js` included, and the collision note's separate
test function would have asserted what it already asserts.

**Browser pass** (Playwright + system Chrome, throwaway console on `:8809` with its own XDG tree,
seeded database, per `browser-screenshots-for-ui-work`): `/chat`, a LoadCoach thread and a
PromptCadence thread at **1440 px and 412 px in both themes**, plus the PromptCadence composer, the
expanded `Details`, and *Allow all tools*. 21 PNGs, **outside git** at `/home/jpk/ai/evidence/WX4/`
(W6 §8.6's rule). `document.scrollWidth == clientWidth` at both widths on every shot.

Live, in that browser, against the operator's running PromptCadence (`GET /tools` only, read-only):
the picker listed `http_fetch, list_dir, read_file, run_command, write_file`; picking `read_file`
twice added it once; *Allow all tools* wrote all five; unchecking restored the previous list.

## 6. What the row text got wrong, or did not know

1. **`services/chat.py:379-385` is the right citation for the wrong reason.** The mode is not
   "fixed" by a check there; it is fixed because `create_conversation` writes `task_profile` and
   `model_override` only for `loadcoach` and `classification`/`tier`/`tools` only for
   `promptcadence`. A per-message switch would need new columns, not a new form control.
2. **`chat_thread.html:130-146`'s "selector reach-ins" needed almost nothing.** They are all
   `el.querySelector(...)` on the message element, and nesting does not break a descendant lookup.
   One line was added, not a rewrite.
3. **The composer covers the notice** (§3.5) — a consequence of "pinned to the bottom" the row
   could not have seen without a browser.
4. **The allowlist input has no place on the thread page**, so `tools_api` is fetched on `/chat`
   only. Fetching it on every thread render would have made every existing PromptCadence chat test
   mock a route it does not care about, and bought nothing: the tools are chosen once.
5. **`/chat` had no test that rendered it** before this row — only `POST /chat` (the audit-route
   test) and the shell's link assertion.

## 7. Left for someone else

* **The GPU.** No model was loaded, no trajectory submitted, no generation run. The live half —
  type into the pinned composer, watch `Details` hold the thinking open and fold at `done` — is the
  arc's verification row (WX14).
* **Merge.** Not merged, not pushed, not tagged.
* **WX3's shell** lands in the same wave: `chat.css` deliberately defines nothing the shell defines,
  and the chat pages use `{% block extra_head %}` and `{% block scripts %}`, so the two should not
  collide. Worth one look at `/chat` after both are on `main`.

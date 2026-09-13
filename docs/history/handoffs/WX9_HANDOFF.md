# WX9 Handoff — LoadCoach tab

**Row:** WX9 (`roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12, unattended, one sitting ·
**Model:** Claude Fable 5.1 · **Kickoff:** `history/prompts/wx9-loadcoach-tab.prompt.md` ·
**Branches:** `row/wx9-provider-enabled` in `~/ai/worktrees/loadcoach-wx9`,
`row/wx9-loadcoach-tab` in `~/ai/worktrees/weightroom-wx9` · **Not merged.**

## 1. What shipped

| Repository | Commit | What |
|---|---|---|
| LoadCoach | `3012ff0` | `[providers.<name>] enabled`; the `[providers]` JSON-schema fix; `model_directory` refused at write for `kind = "llamacpp"`; canonical docs mirrored; `CHANGELOG.md` |
| WeightRoom | `cf4d4e6` | The settings-form mapping (fixture + golden re-recorded, one new test) |
| WeightRoom | `466739b` | Providers *Enabled* + *Add llama.cpp*; Models' name/registration/ability/speed/context-fit |
| WeightRoom | *(third commit)* | Routing, Queue, Evidence and Reliability reshaped; the feedback hint; docs; `CHANGELOG.md` |

## 2. The settings-form fix — and where it went

WX3 found LoadCoach's `[providers.<name>]` values filed under `undescribed` with no values. The
cause is **not** in `settings_forms.py`. That module already descends a keyed table through
`additionalProperties` (`_schema_for_path`, the `extra` branch). It fails on LoadCoach because
pydantic's `extra="allow"` emits

```json
"ProvidersSettings": { "additionalProperties": true, … }
```

— a **bool**, which carries no type to descend into, so `_schema_for_path` returns `None` and the
key is listed raw. `true` is also *less than the truth*: `ProvidersSettings._collect_registrations`
refuses an extra under `[providers]` that is not a registration table, so every extra key **is** a
`ProviderRegistrationSettings`.

**So the fix is in LoadCoach**, not the console: a four-line `json_schema_extra` callable on
`ProvidersSettings` that copies the `registrations` field's own `additionalProperties` (the `$ref`,
never a written-out string, so it cannot name a definition the document does not carry) up onto the
model. `config schema --json` then types `providers.local.base_url`, and the console needed **no
LoadCoach-specific alias and no new generic rule** — zero lines changed in `settings_forms.py`.

Why not a console-side rule: any rule that turned `additionalProperties: true` into a usable type
would be the console inventing a schema the application did not state, which is exactly what
ADR-0127 rule 3 forbids. The test (`tests/unit/test_settings_forms.py`,
`…_a_named_provider_registrations_keys_are_typed_fields_not_undescribed`) asserts it against the
**vendored** document, so a LoadCoach that regresses the schema fails the console's gate.

The fixture `tests/fixtures/schemas/loadcoach.json` is re-recorded from LoadCoach at this row's
commit; it also picks up `console.url` (WM2), which the old recording predated, so
`goldens/loadcoach.txt` gains one line.

## 3. LoadCoach: `[providers.<name>] enabled`

Default `true`, so no existing file changes meaning.

* `build_registrations` skips a disabled block — **that is the whole of what disabling does**;
  every other refusal follows from the registry not holding it (no handle, no discovery, no route).
  `disabled_registration_names(settings)` is the complement, computed in one place.
* `discover_models(..., disabled_provider_names=…)` retires those models with
  `unavailable_reason = "provider_disabled"`. Without it they would stay `available` for ever —
  a disabled registration never answers, so the existing "only a kind that answered may retire its
  own models" rule leaves them alone. Three call sites pass it: `bootstrap`, `models discover`
  (CLI), `POST /models/discover`.
* **Disabling every registration is refused** — in `build_registrations` (`ConfigurationError`)
  *and* in `services/providers.save_registration`, because the second is the one a browser reaches
  and the first fires only after the file has already been written.
* `enabled` is in `WRITABLE_FIELDS`, `RegistrationView`, `GET /providers` and LoadCoach's own
  Providers page (both forms carry the checkbox — a form that omitted it would add every new
  registration disabled, since an unticked box is `false`).

**Also fixed while here** (root cause, not the symptom my new quick-add link exposes): a
`kind = "llamacpp"` registration with no `model_directory` used to be written to the file and then
refused at *re-registration* — the write landed, the request 500'd, and the next start refused a
file the browser had written. `save_registration` now refuses it against the merged table, so an
edit touching only `timeout_seconds` on a registration that already names its directory is
unaffected.

No migration: `enabled` is configuration, not schema. The PostgreSQL leg of LoadCoach's gate is
therefore the orchestrator's usual call and nothing here needs it.

## 4. WeightRoom: the pages

**Models** — the name column is `provider_model_name` (linked) with the canonical id under it;
`Registration` is its own column. New:

* **Ability** select. Vocabulary and scores come from **one** `GET /evidence?match_state=bound`
  call (`lc.abilities_api`), not one call per capability as the row text supposed: a call filtered
  to a capability cannot produce the vocabulary. Only bound records — an unmatched record names no
  model here, so it can neither fill a column nor order one. Choosing one adds its score column and
  orders by it, with "no bound evidence" **last, not lowest** (ADR-0016).
* **Tokens/s** and **p95** (`lc.speed_api`) from the 7d window of the **busiest** task profile,
  named in the cell's title. Selection, not arithmetic — averaging across profiles would be the
  console inventing a figure. Both are ADR-0016 measurements (`{value, samples, minimum, reason}`)
  and pass through `stat()`, so below their minimum they are a dash with the reason.
* **Context fit** from FreeWeight (§5 below).

Each of the three is a *second* read: one that refuses costs the page its column and a note, never
its rows (`_optional`).

**Routing** — `/routing` is the explain form, always open and first (it was behind a `<details>`
summary under a 50-row table), plus the task profiles. History moved to
`/apps/loadcoach/routing/decisions`. It still says *first N of more* rather than offering a pager:
`GET /routing-decisions` takes no `limit` (WX5).

**Queue** — three pages: `/queue` (report + controls, **the only one that streams** — two pages on
the same SSE region would be two connections rendering the same frames), `/queue/new` (the submit
form, idempotency key minted at render), `/queue/history` (filters + pager). The status block is
now a two-row table (`table_id="lc-queue-status"` — see §6).

**Evidence** — `/evidence` is the records with LoadCoach's own `capability` / `model` /
`min_confidence` filters **passed through, not applied here**: each match state is read against its
own cap, so a console-side filter over a capped page would quietly hide records the filter was
meant to find. `/evidence/admin` is the store overview, the sources and Import, and it costs **one**
call (`lc.evidence_store_api` — `GET /evidence/sources` already carries the summary) instead of the
four the merged page made.

**Reliability** — task profile and model are selects fed by the lists the page now fetches; a
**Starts with** box matches `startswith` over this page's pairs, on both the model and the task
profile (`ollama/gemma` and `tools.agent.` mean the same kind of thing to an operator). Applied
**after** paging and in the route, not a Jinja filter, so the pager, the source line and the window
table all see the same rows; a page the prefix empties says how many it hid.

**Job page** — a `field-hint` under Feedback: accepted = one acceptance, edited = half, rejected =
none; the factor bounded 0.5–1.0; neutral below `minimums.factor_attempts`.

`app_page_header` is adopted on every page this row built or reshaped.

## 5. Context fit — **the live read waits for WX7's merge**

Built against WX7's stated shape with a fixture (`tests/fixtures/freeweight/context-fit.json`), and
**not yet verified against the real endpoint** — WX7 ran in parallel and is not merged.

Assumptions the reader (`freeweight_pages.context_fit_api`) makes, to check at merge:

1. The envelope is FreeWeight's usual collection shape, `{"items": [...], "page": {...}}`.
2. Each item keys the model as `canonical_id`, and carries `runtime_profile_hash` and
   `machine_fingerprint` under those suite-wide names.
3. `max_successful_context_tokens`, `capped_by_configuration` and `observed_mb_per_1k_context` are
   plain values, **not** ADR-0016 measurement objects. If WX7 emits measurements, the cell needs
   `stat()`/`measure()` the way the speed columns do — one template line and the fixture.
4. Several rows per model (per profile, per machine) are possible; the reader keeps the **first**
   per `canonical_id` and the cell names the profile and machine it belongs to.

Until WX7 merges, the operator's FreeWeight answers `404` and the page renders
*"Context fit is empty — freeweight refused: Not Found"*, which is the intended degrade and is
what the screenshots show.

## 6. Numbers, and what the browser found

52 screenshots (13 pages × 2 themes × 1440/412 px) in
`/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/wx9/shots/`,
taken against a throwaway console on `:8789` reading a throwaway LoadCoach on `:18766` (fake
provider, two named registrations, one disabled). `scrollWidth - clientWidth` is **0 on every one**.

Two defects the browser found, both fixed here:

* **`settings.html`'s one-line hint clamp overflowed the page at 412 px** (pre-existing, WX1's
  `<details><summary>`; my fixture change added one more long description to LoadCoach's page).
  `max-width: 60ch` is wider than a phone. Fixed as `min(60ch, calc(100vw - 96px))` — clamped
  against the **viewport**, because a percentage max-width inside an auto-layout table is circular
  and blew the table out to 2117 px at 1440 when I tried `min(60ch, 100%)` first.
* **The queue status table lost its header row at 412 px.** `weightroom-shell.css:258` stacks
  `table[data-density="dense"]:not([data-table])` on phones and hides `thead` — correct for the
  hand-written settings/doctor tables it targets, wrong for a `table()` macro table with no
  `table_id`. Giving it `table_id="lc-queue-status"` restores `.table-scroll`. **Any `table()` call
  without a `table_id` is header-less on a phone** — worth a sweep in a later row.

## 7. Decisions to review before merge

1. **The schema fix is LoadCoach's, not the console's** (§2). If the architect would rather the
   console tolerated `additionalProperties: true`, that is a different change and an ADR.
2. **No new left-menu entries.** Routing/Queue/Evidence keep one menu entry each; their sub-pages
   are reached from a nav in the page header, and `selected` keeps the parent highlighted. The row
   text said "Nav entries in `web/rendering.py`", but `_APP_PAGES` has no sub-entry shape and a
   17-entry LoadCoach menu is worse than the three navs the operator actually asked for
   (*Explain/History*, *Current/New job/History*, *Table/Admin*). `docs/apps/weightroom/spec.md`
   §7.3 now says this.
3. **`POST /queue/jobs` with no `job_id` back now redirects to `/queue/history`**, not `/queue`.
4. **Disabling every registration is refused** rather than allowed-and-broken (§3). An operator who
   wants LoadCoach with no provider at all must edit the file.
5. **The llama.cpp `model_directory` refusal is a LoadCoach behaviour change** — a write the API
   used to accept (and then break on) is now a `400`. Small, but it is an API contract.
6. **Ability ordering puts "no evidence" last**, not lowest. A model with a 0.1 score sorts above a
   model with none.

## 8. What the row text got wrong

* "vocabulary from one `GET /evidence?capability=X&match_state=bound` call" — a call filtered *to*
  a capability cannot yield the vocabulary. One unfiltered `match_state=bound` call yields both.
* The row expected `settings_forms.py` to need a LoadCoach alias or a generic rule. It needed
  neither; the defect was upstream (§2).
* "Nav entries in `web/rendering.py`" — see §7.2.

## 9. Left for someone else

* **WX7's merge**: verify §5's four assumptions, then re-record the context-fit fixture from the
  real endpoint.
* **The `table_id`-less phone header defect** (§6) across every other tab's tables.
* Nothing needs the GPU, a shared unit, or another row's files.

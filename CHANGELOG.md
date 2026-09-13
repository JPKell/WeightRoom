# Changelog

All notable changes to WeightRoomGym (distribution `wr-gym`) are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added (row WX13)
- **FreeWeight's provider profiles are a card each on its settings page**
  ([ADR-0144](docs/adr/0144-freeweight-keeps-several-provider-profiles-and-runs-one.md)). Where an
  application's schema document states `provider_profiles` — the key that selects, the active
  name, the kinds it can construct, and each profile's name and dotted prefix — the settings form
  lifts those keys out of their sections into one card per profile with an **Active** radio in its
  heading. Nothing here names a key of any application (ADR-0127 rule 3): the prefixes are the
  application's and the fields are its schema's.
  - A card carries **every key the schema gives a profile**, not only the keys the file names, so
    a newly added profile is editable in full without the raw editor.
  - Switching profile is an ordinary field on the same save, and a security key: the password, an
    audit row that says so, and the restart the page already offers.
  - **Add a provider profile** (`POST /apps/{app}/settings/provider-profile`) writes one key, the
    `kind`, through the same validate-before-write, `.bak` and mtime race as every other file
    write. It switches nothing. A name that is not a TOML bare key, one already taken, or a kind
    the application did not state is refused with the reason.
  - `GET /apps/{app}/settings` carries `provider_profiles` (`null` for the other applications).

### Added (row WX10)
- **IdeaPress's Projects tab gets a top nav; Backends gets a LoadCoach-backed models table.**
  `ip_projects.html` and `ip_project.html` now carry a nav strip — the eight most recent projects
  by name, *All*, *New* — read from an unfiltered, eight-row `GET /projects`
  (`routes/ideapress._nav_projects`) kept independent of the list page's own filters, page and
  cursor, so a status filter or an open project can never make a recent project disappear from
  it. The create form moves off the list onto its own page, `GET /apps/ideapress/projects/new`
  (new template `ip_project_new.html`; `POST /projects` still creates, and still renders back onto
  this page on a refusal). Backends: the three inference-mode cards shrink to one table row each,
  and a new **Models available in LoadCoach** table (`loadcoach_pages.models_api`, read alongside
  IdeaPress's own and gated on this page's own liveness, never LoadCoach's) shows every model
  LoadCoach has discovered — available and enabled ones plainly, with the `[models.stages]`
  binding(s) that name them (`ideapress_pages.loadcoach_bindings`, matched to LoadCoach's
  `canonical_id` by IdeaPress's own reference string, ADR-0024) and a link to Settings to change
  one; any other model is dimmed with an *Enable in LoadCoach* link to its LoadCoach detail page.
  This page still writes nothing. `ip_projects.html`, `ip_project.html`, `ip_backends.html` and
  `ip_project_new.html` are the first pages to call `_app_page.html`'s `app_page_header` (row
  WP1's kit macro, built with no caller until now).
### Added (row WX11)
- **PromptCadence's tab reshaped** — Trajectories, its detail page and Tools. Trajectories'
  submission form moves off the listing onto its own page (`GET /trajectories/new`), so the
  listing (renamed *History* beside the new *New* nav link) is the table alone and a validation
  refusal redisplays the New page rather than the History one; `POST /trajectories` is unchanged.
  A trajectory's detail page gets a jump nav of its section ids at the top — the same ids
  (`#pc-request`, `#pc-tool-calls`, `#pc-debits`, `#pc-egress`, `#pc-approvals`, `#pc-events`, …)
  whichever branch renders, live explanation document or the stopped database read — and its
  request block becomes one two-column (Field, Value) sortable table in place of the definition
  list. Tools gets a *Registry* / *Create a tool* anchor nav (the latter explaining what a tool
  is, with no console form — a tool is code); each tool's name in the registry table links to its
  own page (`GET /apps/promptcadence/tools/{name}`, reading PromptCadence's own `GET
  /tools/{name}`), which shows its description, risk class, egress and its argument schema as a
  table; a `422 TOOL_NOT_FOUND` renders the page's not-found empty state, while a withheld tool
  (found, not registered) still renders with its cause. The per-row `json_viewer` argument dump
  leaves the Tools listing. Every reshaped page adopts `app_page_header` (row WX3's macro, its
  first callers). The Overview gains a PromptCadence-only section — Active, Pending approvals,
  Spending today — read off the same `GET /system/status` body the generic figures already fetch
  (its embedded `ledger.day`, the same document `GET /ledger` answers), so it costs no second
  call and is empty for the other three applications.
### Added (row WX9)
- **LoadCoach's Models page ranks by ability, and says how fast and how far each model goes.**
  The name column is the provider's own model name with the canonical id under it and the
  registration in its own column; an **Ability** select built from the bound evidence this
  LoadCoach holds re-ranks the table by that capability's score, with a model that has no bound
  evidence for it last rather than lowest; measured tokens/s and p95 come from the busiest task
  profile of the last seven days, with the profile named in the cell; and a **Context fit** column
  reads FreeWeight's `GET /api/v1/results/context-fit` (row WX7), shown with the runtime profile
  and machine it was measured under. Each is a second read, and one that refuses costs the page
  its column and a note, never its rows.
- **Three of LoadCoach's menu entries now open a page nav.** Routing is *Explain* (the form,
  always open, no longer behind a summary under a long table) and *History*
  (`/apps/loadcoach/routing/decisions`); Queue is *Current* / *New job* / *History*
  (`/queue`, `/queue/new`, `/queue/history`), with the SSE region on the first of them only and
  the queue's status block as a two-row table; Evidence is *Records* — with LoadCoach's own
  `capability`, `model` and `min_confidence` filters passed through rather than applied here — and
  *Store and import* (`/evidence/admin`).
- **Reliability offers the lists it already fetched.** Task profile and model are selects, and a
  **Starts with** box matches `startswith` over this page's pairs, so `tools.agent.` reaches a
  family of profiles without a new endpoint. Nothing about the prefix reaches LoadCoach.
- **LoadCoach's Providers page can park a registration and add a llama.cpp one.** An **Enabled**
  checkbox per registration writes LoadCoach's new `[providers.<name>] enabled`; **Add llama.cpp**
  prefills the add form and says what that kind needs. The password gate on a new registration and
  on a security key is unchanged.
- **The job page says what feedback is worth**: accepted one acceptance, edited half, rejected
  none; the factor bounded to 0.5–1.0, and neutral below `minimums.factor_attempts` attempts.

### Fixed (row WX9)
- **An operator's `[providers.<name>]` keys reach the settings form.** They were filed under
  *undescribed* with no values (WX3's finding): the form resolves a file key through the
  document's `json_schema`, and LoadCoach emitted `additionalProperties: true` for `[providers]`,
  which carries no type to descend into. Fixed in LoadCoach's schema output, so the console needed
  no application-specific rule; the vendored fixture is re-recorded.
### Added (row WX7)
- **FreeWeight's Models page filters the way the list is read**: provider, family and quantization
  as selects over the values FreeWeight's own list holds, and a parameter range typed in billions
  as the table shows them (converted to parameters once, in the console, so FreeWeight is never
  asked to learn a second unit). Every one of them is `GET /models`'s own filter, so a stopped
  FreeWeight says the list it is reading from the database file is filtered by none of them. A
  filtered page reads the list once more, unfiltered, for the selects' vocabulary alone — a select
  narrowed to what the filtered list holds is a filter that cannot be undone.
- **A model is named by FreeWeight's `display_name`** wherever the console names one — the
  provider's own name, or the canonical ID where two enabled models share it. The console renders
  the name and never re-derives it, and the canonical ID is always the link's title.
- **A machine can be given a name** from its own page: a form posting to FreeWeight's new
  `PATCH /machines/{id}`, audited as `freeweight.machine_nickname` and **not** security-relevant —
  a nickname identifies nothing, and every measurement stays attributed to the fingerprint, which
  the page keeps showing. The name appears in the machines list, on the machine's own page, and
  beside every run's machine. Not offered while FreeWeight is stopped: it is a write.
- **The Runs filter bar offers what FreeWeight lists**: Model, Suite and Machine become selects
  over its models, benchmarks and machines, with the machine shown by name rather than by a
  fingerprint nobody types. A value being filtered by that the list no longer holds stays an
  option, so applying a second filter cannot drop the first; with FreeWeight stopped each falls
  back to the text box it was.
- **Compare gets a model picker and a chart.** Checkboxes over the enabled models join with the
  free-text box into the one subject list FreeWeight is asked for, and a checkbox per metric draws
  it as a horizontal ECharts bar chart (ADR-0142) under the existing grid. **A metric FreeWeight
  marks separated is never charted** — bars on one axis *are* a comparison, and that is the
  reading it refuses; those metrics are listed unticked with their reason in the table. A cell
  with no value is left out of the series rather than drawn at zero (ADR-0016).
- Row WX3's `app_page_header` is now used: Models, Runs, Compare, Machines and one machine's page.

### Added (row WX6)
- **The telemetry history page draws an ECharts line chart** beside its existing accessible SVG
  (`GET /telemetry/history`), the console's first use of MirrorWall's newly vendored ECharts
  (ADR-0142, `mirrorwall 0.3.1`): `services/telemetry.echarts_line_option` reshapes the same rows
  `sparkline_svg` already draws, dropping a `None` value rather than plotting it at zero
  (ADR-0016), and the route opts this one page in (`mirrorwall={"htmx": True, "echarts": True}`)
  — every other page's `mirrorwall.echarts` stays the new `web/rendering.py` default, `False`,
  so nothing else changes. `tests/performance/test_budgets.py` gains
  `test_echarts_is_named_and_budgeted_by_name`: ECharts is printed and asserted under its own
  1 150 000-byte cap, and stays excluded from the 120 KB total row `test_javascript_per_page_…`
  asserts (ADR-0139's rule, unchanged for every other page).

### Added
- **The kit pass** (row WX1): every application-tab table (`fw_*`, `lc_*`, `ip_*`, `pc_*`, plus
  Audit and the ADR index) that renders its whole result set now opts into MirrorWall's
  `table.js` — `sortable=true` and a page-unique `table_id` — so it sorts client-side and, at six
  columns or more, offers a column-visibility `<details>`; a table that shows only one page of a
  longer result stays as it was (`complete=false`, no sort control, per UI standards §5) and is
  left untouched. The four Overviews' Start/Stop/Restart buttons sit side by side instead of
  stacked (`_app_state.html`'s and `apps.html`'s control forms move from MirrorWall's `.field` to
  the page kit's `.kit-actions`, already defined in `_shell.html`). Two new formatters in
  `_app_page.html`, `params_b` (a parameter count in billions, `7.6B`) and `context_k` (a context
  window in thousands, `32768` → `32k`), replace ad hoc formatting on FreeWeight's Models, Model
  and Compare pages and LoadCoach's Models page; both render ADR-0016's `—` for an unsupported
  measurement, never `0`. LoadCoach's Models page also renders declared capabilities as one badge
  per key (a new `capability_badges` macro in `_lc.html`) instead of a comma-joined string. The
  application settings page's per-key description, range and default move off the key cell into
  their own row under it, spanning the table; a long description clamps to one line in a native
  `<details><summary>` (no JavaScript) and expands on click, while the range and default stay
  visible either way.
- **Five generic-surface fixes from the operator's console-UX request list** (row WX2). **Logs**:
  a journal line renders as three stacked lines — timestamp; app, version and pid; message with its
  logger and request id — rather than a `table()` row that could not hold them (`app_logs.html`'s
  history and `_log_pane.html`'s live tail share the shape and its CSS); `journal.unwrap_suite_log`
  now lifts `request_id` and a version wherever a logger names one (`version`, or the first
  `*_version` key — FreeWeight and LoadCoach spell it differently, and IdeaPress and PromptCadence
  spell it not at all yet). **Database**: a Tables / Query / Admin nav over the existing anchors; a
  table's own name now seeds `?sql=SELECT * FROM <t> LIMIT 100#db-query`, leaving *Browse rows* as
  the one remaining path to the guarded row browser and its raw writes. **Tokens**: LoadCoach's and
  PromptCadence's scope field is a `<select>` from each application's own vocabulary
  (`services.tokens.SCOPES_BY_APP`) — a single choice for LoadCoach's cumulative scopes, several
  for PromptCadence's independent ones (ADR-0049 rule 2), joined with a comma the way its `--scope`
  reads a list. FreeWeight's **Tokens** menu entry is gone (`rendering.py`, one tuple line); its
  Settings page explains, correctly this time, that there is no minting command at all — the
  kickoff's `freeweight token create --scope …` does not exist, `auth.tokens` is a plain list a
  security key already lets an operator edit, so the page says to generate one (`openssl rand -hex
  32`) and paste it in. **Docs**: `services.docs.APP_BLURBS`, one sentence per application and
  package from its own `spec.md` §1, renders under a folder's heading in the docs tree; every
  application page links to its own entry (`/docs?section=apps#docs-apps-<name>`, via a new
  `_app_page.html` macro used from `_app_state.html` and, where a page has none, added directly).
- **A llama.cpp page, and the console's own pages move into the left menu** (row WX3). Four
  changes to the shell, one new page:

  - **`/llamacpp`**, beside `/ollama` and read-only end to end: the running `llama-server`
    processes found by `pgrep -x llama-server` (never `-f`) with the port, `--model`, `--ctx-size`
    and `--fit` read out of each one's own `/proc/<pid>/cmdline`, and the served `n_ctx` and build
    from `GET /props` where the port answers; the GGUF directories FreeWeight and LoadCoach
    configure, with the files found in them; and `MEMORY_SAFETY.md` §2.2's expectations of the two
    applications that launch a server as found/expected rows — the unit-cap half being the
    doctor's own `unit_cap_findings`, so the two pages cannot disagree. There is **no launch and
    no kill**, and the page says why: a `llama-server` belongs to the application that started it
    (ADR-0062), and ModelRack is imported for residency and discovery reads only (spec §3). An
    application configured for another provider kind is named and skipped rather than shown rows
    that could only ever fail.
  - **The console's pages and tools are a left-menu section** — *Console* (Overview, Applications,
    Ollama, llama.cpp, Logs, Audit, Doctor, Settings, Trust) and *Tools* (Chat, Docs, Database,
    Catalog, Costs, Backups, Jobs) — appended under an application's own menu and under the
    documentation tree, so they are on every page at every width. They used to sit in the top bar
    and fold into *Menu* below 1080 px, which made *which pages exist* a function of the window's
    width. The top bar now carries the brand, the four application tabs, the alerts count and the
    operator menu; *Menu* overflows the tabs alone, at 860 px.
  - **The shell's stylesheet is a file**, `static/css/weightroom-shell.css`, served from
    `/app-static` and cached once per browser instead of re-sent inside every page, with a 32 KB
    budget in `tests/performance/test_budgets.py` beside ADR-0139's JavaScript budget.
  - **`app_page_header(view, title, section, supporting)`** in `_app_page.html`: the common head
    of a page under an application's tab — where the page sits, its title, that application's
    availability pill verbatim, one supporting sentence, and the caller's own actions through
    `{% call %}`.
  - **The documentation tree opens to the document you are reading**, folder by folder, instead of
    showing one flat level of a section's top folders.
- **`[ui] page_rows`, and pagination follows it** (row WX5). A new runtime-changeable setting
  (int, 10-500, default 50) governs the page size of every table the owning API can page;
  `config.py`'s `UiSettings` and `services/settings.py`'s `RUNTIME_SETTINGS` registry are the two
  places it is declared, and the settings page picks it up with no template change (the registry
  generates the row). The four `services/*_pages.py` `PAGE_ROWS` module constants are gone —
  `freeweight_pages.py`, `loadcoach_pages.py`, `ideapress_pages.py` and `promptcadence_pages.py`
  now read the page size from the request's settings — and several tables that used to silently
  cap out gained a real pager or, where their owning API cannot page at all, an honest "First N of
  more" sentence instead of truncating without saying so:
  - **PromptCadence's `GET /ledger/entries` gains a cursor** (this row's own first commit, in
    PromptCadence), and the Ledger, Approvals-history and Egress pages follow it with a `Next`
    link, replacing a single request capped at 200 with no way to see further.
  - **The audit trail (`/audit`)** defaults its page size to `page_rows` and threads a `cursor`
    through to `list_audit`'s existing `before_id` parameter, which the UI never used; a `Next`
    link now reaches every row, not only the first page.
  - **LoadCoach's Reliability page** is genuinely paginated (LoadCoach answers the whole list in
    one call; the console pages its own view with `page_rows` and a `Next` link). **Routing**'s
    decision history and **Evidence**'s records table cannot be paged at all — `GET
    /routing-decisions` hardcodes its own 50-row cap with no `limit` parameter, and Evidence
    merges three independently-capped `GET /evidence` reads (one per `match_state`) into one
    table — so both stay `complete=false` and now say "First N of more" when the cap was
    plausibly hit, instead of the previous silent truncation.
  - **IdeaPress's Units page** — its project picker read only `cursor=None` (the first page of
    projects) with no way to reach a project past it; it now follows a cursor like every other
    paged listing.
  - FreeWeight's Models, Runs, Samples, Results, Evidence and Adapter pages already had a real
    cursor or numbered pager; only their page size becomes configurable (mechanical, no new UI).

- **IdeaPress's attempts tables name the transport call** (row WPF12). A stage run's *Attempts*
  table and a unit's *Provenance* table now fold `transport_call` (IdeaPress migration `0012`, row
  WPF7) into the attempt cell — `attempt N · round R · call C` — so two rows of one attempt are
  told apart by what they are, not by outcome alone; one line of copy above each table says a call
  above `0` is one IdeaPress discarded and retried, so its `provider_error` outcome does not read as
  a second failed attempt. IdeaPress's `ExportAttempt` is untouched — a version question, not this
  row's. The database-read path treats a schema older than migration `0012` (no such column) the
  same as `0`, since every row it holds predates the concept.

- **The Runs page starts a run under an adapter** (row WPF2). FreeWeight's `run start --adapter` was
  the only way to measure a base served with a registered LoRA, so the operator's step could not be
  done from the console at all (WP6 finding 4). The Start form's adapter field lists what
  FreeWeight's `GET /adapters` reports as available, and appears only where FreeWeight says an
  adapter can be served at all (`provider_can_serve`, ADR-0140) — the console decides no
  compatibility of its own, and renders FreeWeight's refusal. The name is one more argument to the
  same capped `freeweight_suite_run` job (ADR-0119), checked against the manifest's own name
  pattern because it reaches a child's argv, and **Repeat** keeps the adapter because FreeWeight's
  repeat now does. FreeWeight's Adapters page names a configured directory that is inert under a
  provider that cannot apply a LoRA.

- **FreeWeight's Dashboard and System pages, and LoadCoach's System page** (row WPF5), judged
  needed at row WP6 (`WP6_HANDOFF.md` §3) and specced at spec §7.3. FreeWeight's **Dashboard**
  reads its new `GET /api/v1/dashboard` (FreeWeight, `api.md` §5a): the summary cards and the
  model × suite comparison heatmap, with FreeWeight's own *separated* marking — the cross-model
  view Results and Compare do not offer. FreeWeight's and LoadCoach's **System** pages read
  `GET /health` (and, for LoadCoach, `GET /system/status`): version, overall status and every
  health component — ten for FreeWeight, five for LoadCoach — that the console showed nowhere
  before. All three pages read the running API only, exactly as the Overview's *Start* form. Not
  added: FreeWeight's **Sources** (a read-only credit list with nothing installed or actionable)
  and IdeaPress's **System** (covered by the Overview and the doctor).
- **FreeWeight's Goals page** (row WP4 Gate A), at parity with FreeWeight's own `goals` pages
  and its authoring wizard, every one over its API (FreeWeight `4090275` added the routes the
  wizard and the goal pages lacked). **Goals**: each goal with its `goal_hash`, score method mix,
  calibration state with κw and its n, calibration age and the *unforked* badge; the drafts in
  progress; the four starters in reading order, each forked unedited or customised as a draft;
  a goal created from a pack (`goal.json` and task records) with its lint shown and never
  blocking; a bundle imported by file or paste, a colliding slug rendered as FreeWeight's refusal
  naming the installed hash. **One goal**: criteria by rung, tasks with the starter badge, lint,
  FreeWeight's validate and its rule proposals (with their parameters, never applied), the goal's
  results, and both exports — the bundle, which round-trips, and `benchmark.goal_pack`, which does
  not. **Edit** is `goal.json` and the task records as on disk, always dry-run first: an edit that
  keeps `goal_hash` saves at once, one that moves it shows the old hash, the new hash and the runs
  it separates and commits only when the operator confirms those same hashes. **Delete** shows
  FreeWeight's preview (runs orphaned, grades destroyed) and needs the slug typed. **Drafts** are
  FreeWeight's rows, walked on one page: criteria with the two questions, scale descriptors and
  splits; each proposed rule accepted one at a time with its parameters as edited; tasks; save;
  abandon. Nine audit actions; no row carries an intent, a prompt or a descriptor. A stopped
  FreeWeight's goal list, one goal's criteria and tasks, and its stored report read its database.
- **FreeWeight's calibration, grading, agreement report and judges** (row WP4 Gate B).
  **Calibration**: the set counted by partition and origin with its grading progress — no sample
  listed one by one, since a row pairing a sample with its origin would unblind grading; samples
  added by pasting, by promoting a completed goal run's samples (FreeWeight reads each stored
  answer itself), or generated over a model spread by running the goal on one model after
  another through the Runs page's capped start. **Running the calibration** is the new
  `freeweight_goal_calibrate` job — `freeweight goals calibrate --progress --json` under the
  host memory cap in a `wr-gym-fwrun-` scope — whose page shows FreeWeight's progress as the jury
  works, one line per holdout sample and never a grade. **Grading**: FreeWeight's blinded view, one
  sample at a time, opening at the first unfinished sample; each criterion's grade picked from its
  scale's descriptors with a note, saved per `(sample, criterion)`; a save FreeWeight did not
  answer is audited `failed` and the page re-reads what FreeWeight holds, so a resend lands each
  grade once. A goal run's human criteria are graded the same way (`/apps/freeweight/runs/{id}/grade`).
  **Report**: the gate verdict, weighted κw with n anchor and n holdout, the judge validity factor,
  and per criterion κw, ρ, MAE, bias, inter-juror α, n and validity with the lint's read and the
  worst-diverging samples with your note and the jury's rationale; a figure FreeWeight could not
  compute is `—` with its reason. **Judges**: eligibility with each refusal's reason and each
  model's `native.judge` figures, and a jury dry run for a goal and a candidate. A stopped
  FreeWeight's calibration set and stored report read its database. Three audit actions;
  `app_side_nav_stubs("freeweight") == ()`.
- **FreeWeight's Evidence page shows each record's staleness and its six confidence factors**
  (row WP4), from the `explanations` FreeWeight now serves beside the envelopes, in place of the
  note that they were not on its API.

### Fixed
- **A slow catalog call is audited `pending`, not `refused`** (row WPF11, left open at WPF1 §6
  item 3). `set_enabled` and the delete path's two calls to Ollama's own API (`/api/tags`,
  `/api/delete`) raised `CatalogRefused` for a timeout exactly as they did for an application
  actually saying no, so `POST /catalog/{ref}/enabled`, `DELETE /catalog/{ref}` and the same
  routes under `/apps/freeweight` and `/apps/loadcoach` all audited a slow answer as a refusal —
  the same defect WPF1 fixed for every other application call. They now raise `AppTimedOut` on a
  timeout, and every route audits the outcome with `app_api.outcome_of`, the function WPF1 built
  for exactly this, rather than a bare `"refused"`. A genuine refusal, and Ollama being simply
  unreachable, audit exactly as before. `catalog_pull` itself was moved onto the job queue at row
  W9 and its own request only enqueues a row, so it was never exposed to this — the kickoff's
  premise that this row would decide whether to queue it was already settled.
- **The FreeWeight Dashboard's *Latest run* card fits its card** (row WPF5's browser check,
  2026-09-12). The full RFC 3339 stamp was rendered as a figure — mono, large, unwrappable — and
  overflowed the card at every width, scrolling the whole page sideways on a phone. The date is
  the figure now and the clock is the card's note.
- **An application's Overview renders inside its budget** (row WPF6, from WP6 finding 7). Every
  Overview render launched `<app> config show --json` — about 0.5 s — to find the application's
  database, instead of reading it through the `DatabaseUrlCache` every other database-backed page
  already shares. PromptCadence's Overview painted at 580 ms and LoadCoach's at 544 ms against
  spec §15's 300 ms, while every other page of the four tabs came in at 224 ms or less. The page
  now goes through the cache (one launch a minute per application, ADR-0133 rule 4 unchanged:
  the URL is still the application's own). The budget test no longer measures a fake that answers
  in milliseconds — its LoadCoach sleeps for a real launch, so the budget is met only by not
  launching per render.

- **A unit verb slower than the console's limit is no longer audited as a failure** (row WPF4,
  from WP6 finding 6). `systemctl` is killed after 30 s, which says nothing about the unit: at
  row WP6 a `restart` of LoadCoach that succeeded ninety seconds later was audited `failed`
  (`01M28ZA6T3HHPBQK0SFQ8V9PQD`). The console now re-reads the unit after a timeout and reports
  what it actually reached — `ok` when it is the state the verb asked for (with a message saying
  the call outlived the limit), `failed` with systemd's own `Result` when the unit failed, and
  `pending` while systemd is still `activating`/`deactivating`, with the live state on the page.
  The calls stay blocking and keep systemd's own words, since a normal verb answers in well under
  a second: only a timed-out call costs one extra `systemctl show`. `wr-gym units start|stop|
  restart` reports the same way. An *inactive* unit was never an outage to the alert evaluator,
  so a console-requested stop raises no `app_down` alert; what fired at row WP2 was the `failed`
  unit that a `SIGKILL`ed stop left behind, which LoadCoach's own fix removes.

- **The settings form could not save FreeWeight's file keys** (row WPF1, from WP6 finding 1). A
  key the application's model allows to be *unset* was rendered by a widget that cannot say so: a
  nullable boolean (`runtime.flash_attention`) as a true/false select with `false` preselected,
  and a nullable enum (`runtime.kv_cache_precision`) as its first choice. Every save therefore
  wrote two keys the operator never touched, and FreeWeight refused the whole file whenever its
  provider was `ollama` — no save through the form could land. Nullable leaves now render an
  *unset* option, an empty submission on one means *unset* for every type, and a secret whose
  value is empty (so rendered in the clear rather than as `********`) is compared like any other
  key instead of being written back on every save. Picking *unset* on a key the file names is
  refused by name as the deletion it is — that stays the raw editor's job — and only that key:
  the rest of the same save still lands. Nothing here names a key of any application (ADR-0127
  rule 3).
- **A refused settings write left no audit row** (row WPF1, from WP6 finding 2), against spec §11
  contract 2. Two refused `POST /apps/freeweight/settings` requests were answered `200` with the
  refusal rendered and neither left a `settings.write` row, while the same page's successes each
  left one. All five settings write routes now record their refusals — a stale `base_mtime`, the
  application's own validation, a wrong password, the re-authentication window, invalid TOML in
  the raw editor, and a field that will not parse — as one row with outcome `refused`, the keys
  the operator submitted as its target and the refusing party's own words as its message. The
  audit-route test gained the matching half: a route that renders a refusal now needs a refusal
  exercise beside its success exercise.
- **A call slower than its timeout was reported as the application's refusal** (row WPF1, from
  WP6 finding 3). *Refresh from provider* rendered *freeweight did not answer POST
  /api/v1/models/discover: timed out* and left a `refused` audit row, while FreeWeight carried on
  hashing 195 GB of GGUF files and stored 27 models four minutes later: the call was slow, and
  FreeWeight had refused nothing. A timeout is now its own error — the same `APP_UNREACHABLE`
  code, so a client that branches on the code sees no change — saying that the application may
  still be doing the work, that nothing was cancelled and that nothing was sent again. Its audit
  row is `pending`, the outcome vocabulary's word for *no state moved that we know of*, across
  every action of all four application tabs. A GGUF drop-in no longer reports an application as
  refreshed when its discovery pass did not answer. Spec §11 contract 2 now states both rules.
- **The raw TOML editor rewrote every line of the file it saved** (row WPF1, found live). A browser
  posts a `textarea`'s value with CRLF endings whatever it was given, so opening the editor and
  saving a file back unedited replaced every line ending in the operator's file — valid TOML they
  never typed. The editor normalises to `\n` before it validates and writes.
- A `settings.write` audit row named every key the page posted — the whole model, 85 keys for
  FreeWeight — burying the one key that moved. The row's target is now what the write did (or
  *n keys, none changed*), and a refusal names the keys the operator asked to change rather than
  every field on the form. `params` still carries each list in full.
- Polish from WP6 §4 (row WPF1). A machine fingerprint or a model identity in a `.mono` span had
  no break opportunity and stretched the page at phone width: FreeWeight's machine page scrolled
  sideways by 138 px and its adapter page by 96 px on a 412 px screen, so `.mono` now breaks where
  `code` already did. The strip's QUEUE showed the depth LoadCoach had before the operator stopped
  it; a unit verb the console runs drops the reading. A job that ended without a model read *not
  yet routed*, which invites waiting for a routing that is not coming; it now reads *never routed*
  unless the job is still queued or running. The Approvals page showed a decision's new state and
  said nothing about it; a grant or a denial now lands on a notice. A stopped FreeWeight's Compare
  offered an enabled query form for a page that has no database reading behind it, and its
  calibration page offered *Start grading* for a page that needs the API; both now say so.
- A form with a `fieldset` overflowed a phone (row WP4's phone demonstration): a fieldset's
  default `min-width: min-content` let a select whose options carry scale descriptors widen
  FreeWeight's grading form to 839 px on a 412 px screen, and taps on *Save and go on* landed on
  the sample text. Fieldsets shrink and selects stay within their column, console-wide.
- A figure FreeWeight could not compute, on FreeWeight's agreement report and judges, gave its
  reason only as a hover tooltip, which a phone cannot show; the reason is now written beside the
  `—`. A model never measured as a judge says so once in its row rather than in eight cells.
- The page kit (row WP4, from WP3's screenshots): a refusal rendered in the success-green
  `.notice` box and now renders as an error; a page whose API refused it said *The API did not
  answer this page* and now says the API answered with a refusal; the stopped notice named the
  application in lower case (*freeweight is not answering*); an export form that is itself the
  card (Results, Evidence) stacked every field full width instead of laying them out as a grid.
- **IdeaPress's plan, research, stage runs, units, workspace and export** (row WP5 Gate C), at
  parity with IdeaPress's own `plan`, `units`, `workspace` and `export` pages, every one over
  its API. **Plan**: every requirement with the material it rests on, the unit plan, the five
  plan edits (a refusal names what IdeaPress's gate protected: the orphaned requirement or the
  finished unit), running the plan, and **research** — where a fetch may go, the notes, and every
  tool call with the egress decision it ran under. **Stage runs**: a run form that sends
  IdeaPress's body with only the overrides given, beside the stage bindings and workflow limits
  the stage will use (`GET /settings`); the run's page with its state, counts and attempts,
  IdeaPress's task stream proxied into the log pane with `Last-Event-ID` carried through
  (`unit.paused` and `stage.failed` shown as states, a bare `token` frame as a line of text),
  and **cancel**, which the page says lands at the next model-call boundary. **Units** (a
  project's units with coverage and last validation) and **one unit**: its content as sanitised
  markdown, coverage, validation, findings, critiques, provenance with each attempt's egress, and
  every version with the run that produced it; **revise** with instructions, and **resume** for a
  paused unit or one a gone run stranded — offered only where IdeaPress allows. **Workspace**:
  IdeaPress's own view, with its pause guidance, coverage summary and a diff between versions.
  **Export**: the formats in IdeaPress's words, what would be included, writing into the project
  directory (naming the file, size and hash), and a download served as an attachment, never
  inline. Eight audit actions; no row carries instructions, a brief or unit text. A stopped
  IdeaPress's plan, research, runs (with their recorded events) and units read its database; the
  workspace and export say they read only its API. `app_api.text` fetches a non-JSON body.
- **IdeaPress's Projects, Workflows and Backends pages under its tab** (row WP5 Gate B), at parity
  with IdeaPress's own UI: **Projects** (newest activity first, by status and content type, with
  IdeaPress's cursor; the create form with title, content type, a workflow from
  `GET /workflows`, brief and author material as a JSON object), **one project** (its fields,
  brief and author material, the plan summary as figures, every unit with its state, version,
  coverage and last validation, and the stage history newest first), an **edit** form that says a
  save never recompiles requirements, and a **delete** that shows IdeaPress's own preview first,
  offers to archive the project before anything is removed, and deletes only once the title
  IdeaPress answers is typed. **Workflows** (stage order, which stages use a model and the model
  bound to each, gates, and the workflow limits a run uses from `GET /settings`) and **Backends**
  (mode, selected/fallback/pinned, reachability, capabilities, whether content leaves the machine,
  and the round-trip **Test** with its latency, model list and version). Each action is one audit
  row (`ideapress.project_create`, `ideapress.project_update`, `ideapress.project_delete` —
  its preview `pending` — and `ideapress.backend_test`), never carrying a title, brief or author
  material. A stopped IdeaPress's projects read its database; Workflows and Backends say they
  read only its running API. The fixtures are IdeaPress's own application answering over its
  scripted backend, with the database it left (`ideapress-0011-journey`).
- **FreeWeight's Models and Runs pages under its tab** (row WP3), at parity with FreeWeight's own
  UI: **Models** (latest descriptor, whether each has results, sort, **Refresh from provider**
  with the added/updated/unchanged counts, and ADR-0118's switch through the catalog's own call),
  **one model** (identity, aliases, latest descriptor, descriptor history, its evidence, and its
  results filtered by suite and runtime profile), **Runs** (status, model, suite, machine, label,
  adapter and date filters over FreeWeight's cursor), **Start a run** over `GET /benchmarks` —
  which enqueues W9's `freeweight_suite_run` job, so the run executes under ADR-0119's memory cap,
  and the page follows the job until FreeWeight names the run — **one run** (provenance,
  degradations, the fingerprint document, tests, metrics, telemetry charts, and its events live
  with FreeWeight's own sequence as the SSE id, so a reconnect resumes where it dropped),
  **cancel** (`409 RUN_NOT_CANCELLABLE` rendered as itself), **repeat** with force and label (a
  refusal names every blocker; a forced repeat's divergence shows among the new run's
  degradations), a test's **samples** over FreeWeight's cursor, and the **case inspector** with
  every model- and juror-written text escaped. A stopped FreeWeight's pages read its database at
  revision `0010`. Each action is one audit row (`freeweight.discover`, `catalog.enabled`,
  `job.enqueue`, `freeweight.run_cancel`, `freeweight.run_repeat`).
- `freeweight_suite_run` takes an optional `label`, passed as `run start --label`.
- **FreeWeight's Results, Evidence and Machines pages** (row WP3): **Results** over FreeWeight's
  metric query with every filter it takes (model, suite, metric key, machine, runtime profile,
  adapter, date window, run status) and its cursor; **Compare** (`?subjects=…&suite=…`) with the
  study, each subject's profile, every comparability verdict with its reason and the fingerprint
  fields that separate the runs, the metrics aligned with their groups, and a refused comparison's
  reason and offending runs rather than a blank; **Export** proxied as it streams, with every
  option FreeWeight takes and its own file name — the 500-run refusal arrives before the first
  byte and renders on the Results page as itself; **Evidence** with FreeWeight's filters, each
  record's contributing metrics, a `user.*` record's goal hash, jury, calibration and judge
  validity factor, and the `benchmark.evidence_bundle` download; **Machines** and one machine with
  the runs measured on it, linked from every run, result and comparison that names a fingerprint.
  A stopped FreeWeight is never called for a download.
- **FreeWeight's Adapters and Provider pages** (row WP3): **Adapters** over FreeWeight's new
  `GET /adapters` — the directory's reading beside FreeWeight's own `adapters` table, each adapter
  with its base and how the base is proven, availability, whether it is still in the directory,
  its runs, and the manifests FreeWeight could not read, the drafts and the unmanifested
  artifacts; **one adapter** with its runs and results (`adapter` filters on FreeWeight's runs and
  results) and, per base, the scores measured with the adapter beside the bare base's — the two
  columns FreeWeight's damaged-adapter canary compares, whose verdict FreeWeight does not store;
  **Provider**, the `[provider]` block edited through FreeWeight's `PUT /provider` with its digest,
  a changed `kind` or `base_url` asking for the password (`freeweight.provider_save`, a `security`
  row then). The Database page adds FreeWeight's own backup count, last backup and artifact size
  while it answers. No FreeWeight page is a stub but Goals (row WP4); `_PAGE_ELSEWHERE` is gone.
- **PromptCadence's System page** (row WPC1, spec §7.3 as amended 2026-09-10): its health
  components with their status, the active trajectories, every pending approval with its age,
  today's position, the last recovery pass (resumed, finished, halted, failed, deferred) and the
  configured concurrency — PromptCadence's own System page, over its `/health` and
  `/system/status` only; a `503` health keeps the rest of the page. PromptCadence's API does not
  say how it authenticates, so the page links the Tokens page instead.
- **LoadCoach's Models, Routing and Reliability pages under its tab** (row WP2), at parity with
  LoadCoach's own UI: **Models** (declared capabilities, the evidence summary, reliability,
  residency, the registration and egress class — `""` and `false` read *not recorded* — with each
  adapter subject under its base), **one model** (identity, descriptor, evidence per capability
  with its `match_state`, reliability per task profile, the breaker), **Routing** (an explain form
  over `POST /route` with the task profile, required capabilities and the model, adapter and
  runtime-profile overrides, rendering every candidate's numbers and every rejection by its code;
  the decision history; the task profiles and one profile's weights, constraints and policies),
  and **Reliability** (the `7d`/`30d`/`all` windows, each value with its samples or why it is
  absent, the factor with its reason, the regression verdict, the breaker; filtered by task and
  model). **Scan**, **enable/disable** (through the catalog's own call) and **warm** (opening the
  job it enqueued) act from the page, each one audit row (`loadcoach.discover`, `catalog.enabled`,
  `loadcoach.warm`, `loadcoach.route`). A stopped LoadCoach's pages read its database; its
  factor, verdict and live breaker say they wait for its API.
- **LoadCoach's Queue and Evidence pages** (row WP2): the queue's report — depth by state and
  class, oldest age, dispatch latency, executions, residency, starvation, breakers — updated live
  over LoadCoach's `/queue/stream` as regions this console renders; **pause, resume and drain**,
  each asking first with a sentence saying what stops (queued dispatch; synchronous generation is
  not held); **jobs** filtered as LoadCoach's own page filters, **submitted** (class, priority,
  wait bound, idempotency, sampling, model and adapter pins, streaming), **one job** (attempts,
  validation checks, usage, timings, output, the routing explanation, the event pane, and while
  it runs its reply with ADR-0132's thinking block), **cancel** and **feedback**; **Evidence**
  (every record by match state, the store's summary, the sources) with **import** of an uploaded
  `benchmark.evidence_bundle` or LoadCoach's pull from the console's own FreeWeight URL, a
  refusal such as `EVIDENCE_SOURCE_REFUSED` rendered as itself. Each action is one audit row
  (`loadcoach.queue_pause|resume|drain` — an unconfirmed ask is `pending` —
  `loadcoach.job_submit|cancel|feedback`, `loadcoach.evidence_import`); no row carries a prompt
  or a note.
- **LoadCoach's Providers and Adapters pages** (row WP2): every `[providers.<name>]` registration
  as a form — saved and removed through LoadCoach's own `PUT`/`DELETE /providers/{name}`, which
  validates and writes its file (ADR-0117) — with the models each serves; changing `kind`,
  `base_url` or `remote`, adding a registration or removing one needs the password within the
  re-authentication window, and a removal is previewed with the models routing stops choosing
  and sent only once the name is typed (`loadcoach.provider_save|delete`, `security` rows when a
  security key moves). **Adapters** reads LoadCoach's new `GET /adapters`: each adapter's base
  and its identity confidence, its classification (local only), who holds it, where it is
  resident, and the routes that selected or refused it by code; stopped, the `adapters`
  projection with its residency and candidates. LoadCoach's tab has no stub left.
- **PromptCadence's pages under its tab** (row WP1), at parity with PromptCadence's own console,
  which a browser on the LAN cannot reach: **Trajectories** (filtered by state, paged by
  PromptCadence's cursor), **one trajectory's whole record** (the explanation document PromptCadence
  renders — request, plan attempts and steps, envelopes, every thread's turns, tool calls,
  compactions, debits, egress decisions, deviations, approvals, events — with a live event pane
  while it runs), **Approvals** (pending, and every request ever raised), **Tiers** (availability
  and why not), **Tools** (withheld tools with their cause, the isolation rung), **Ledger** (today's
  position, per-project and per-tier, the debits behind it) and **Egress** (newest first, by
  verdict and trajectory). A stopped PromptCadence's pages render from its database at a known
  revision; while it runs, the approval history and the egress decisions read its API too, over
  the two listings it gained at row WPC1 (`GET /approvals?status=all` without a trajectory, and
  `GET /egress-decisions?sort=-decided_at`).
- **PromptCadence's actions from its tab** (row WP1): **submit a trajectory** (classification,
  tools ticked from the registry — none ticked sends an empty allowlist, never an omitted one —
  tier, project, step and turn caps, planning, token and money budgets and the partial-pricing
  rule), **cancel** one, and **grant or deny** a pending request from the Approvals page or the
  trajectory's own record, a ceiling raise with its new ceilings. Each writes one audit row
  (`trajectory.submit`, `trajectory.cancel`, `trajectory.approve`, `trajectory.deny`; the last two
  `security`); a grant or denial is refused before any call unless the console's token holds
  `approve` (ADR-0049); a refusal renders on the page in PromptCadence's own code and words, with
  the form kept.
- **A Logs page under every application's tab** (row WP1): the unit's journal history, filtered
  by time, level-and-worse and literal text and paged by cursor, above its live pane.
- **The page kit every application page is built on** (row WP1): `services/app_api.py`, one
  client for the applications' own APIs (the bearer from `api_key_file`, a timeout per call, a
  refusal carried through with the application's own code, SSE streams proxied with
  `Last-Event-ID`); `services/app_pages.py`, spec §7.3's source rule decided once (the API while
  the application answers, its database at a known revision while it does not, degraded by name
  outside the version range); `render_app_page` and `_app_state.html`, so a stopped
  application's page carries a Start that returns the operator to that page.

### Changed
- **Chat is a chat page** (row WX4). The conversation list left the middle of the page for a rail
  down its left side, newest first with the open one marked, and the composer is pinned to the
  bottom of the thread it belongs to. One composer starts a conversation and sends its first
  message: the title is optional and taken from that message when it is blank, because a
  conversation named before it is had is a form, not a chat. The **Mode** radio pair is a select
  inside the composer's own *Mode and settings* block, with the backend's fields beside it; on a
  thread it is disabled and shows the mode the conversation was started with, since the mode is
  fixed for a conversation's life (`services/chat.py`) and a per-message switch is not modelled.
  The chat pages carry their own `chat.css` and `chat.js` — 1.6 KB, inside ADR-0139's 120 KB — and
  work without the script: both backends' fieldsets are simply visible, and the tool allowlist is
  the free-text input it has always been.

- **The tool allowlist is picked from PromptCadence's registry** (row WX4). The composer lists what
  `GET /tools` reports as *registered* and appends a chosen name to the comma-separated list;
  **Allow all tools** writes today's registered names into that list, by name. It never leaves the
  field empty to mean "all" — PromptCadence reads an omitted allowlist as *every* configured tool
  (row W6), so what was allowed is recorded rather than implied, and a tool registered tomorrow
  joins no conversation agreed today. A tool PromptCadence withheld is not offered: it cannot run.
  The registry is read only when PromptCadence's unit says it can answer; stopped, refused or
  silent, the page says so in PromptCadence's own words and the input stays free text.

- **A reply's non-answer frames sit under one collapsed `Details`** (row WX4). Thinking, the plan,
  step, tool-call and egress cards and the routing and cost block are wrapped in a single
  `<details>` summarised `Details · N steps`, closed once the reply is finished and open while it
  streams, so the thinking the operator asked to watch is still watchable live (ADR-0132) and a
  finished thread reads as answers. A **pending approval stays outside** the wrapper with its
  auto-open intact: a decision nobody has taken is never one click away.

- An application's left menu is two sections: its own pages, a rule, then Settings, Tokens,
  Prompts, Logs and Database (design brief §4). A page not built yet names the row that builds it
  (`coming in row WP2`) instead of *not yet scheduled*.

### Fixed
- **Figure cards stack** their label, figure and note (design brief §5) instead of running them on
  one line; fixed in the console's shell CSS, so the prepared MirrorWall `0.3.1` is unchanged
  (row WP2).
- **The Overview's figures read fields the applications serve** (row WP2): PromptCadence's
  *Executing* and *Planning* count its `active_trajectories` by state and *Pending approvals*
  counts its list (they rendered `—`, `—` and `[]`); IdeaPress's *Active stage runs* counts its
  list and *Pinned* reads `pinned`; FreeWeight's disk headroom is humanised. Each application's
  status body is pinned by a recorded fixture.
- **A job's live output reaches its row while the child is quiet** (row WP3). The buffer flushed
  only when a new line arrived, so the last line before a silence waited for the next line or the
  exit. `freeweight run start --json` prints the run id and then nothing until the run ends, so
  the Runs page could not follow a run it started until that run had finished. `run_streaming`
  now flushes between polls, within `_OUTPUT_FLUSH_SECONDS`.

## [1.0.0] — 2026-09-10

One release over everything rows W1–W9 built (interview decision D15), prepared at row W10 for
the operator's tag once the independent-device verification says *ready* and MirrorWall `0.3.1`
is published (`requirements/ci.lock` is re-cut against it then). `0.1.0` is the only version on
PyPI; `0.2.0`–`0.7.0` were prepared and never tagged, and their sections below are what `1.0.0`
carries.

### Added
- **The operator documentation set** (row W10): `docs/setup.md` (the wizard end to end, what it
  leaves on the host, trusting the root on each device), `docs/security.md` (the LAN surface end
  to end, in the order a request meets it), `docs/operations.md` (units, logs, backups and
  restore — the console's own and each application's — jobs, retention, certificates,
  upgrading) and `docs/troubleshooting.md` (every doctor rule and every spec §13 code, with what
  to do); `docs/openapi.json`, the API snapshot, held byte-identical to the application by
  `tests/contract/test_openapi_snapshot.py`, which also holds `api.md`'s route list to exactly
  the routes served.
- **Spec §14 as a registry** (`tests/security/test_checklist.py`): every security row named by
  the file and test that holds it; **the redaction sweep** (`tests/security/test_redaction_sweep.py`):
  every audit exercise through one console holding the operator's password and a LoadCoach
  token, neither reaching an audit row or a log line; **a network-isolation e2e**
  (`tests/e2e/test_network_isolation.py`): every page and every id-free `GET` with the four
  applications installed and stopped and every socket refused — no internal error, every `5xx`
  a refusal by name.
- **Every spec §15 budget measured and asserted** under `-m performance`
  (`tests/performance/test_budgets.py`), the degradations the spec names each tied to its test
  (`tests/unit/test_degradations.py`), and the upgrade from the first release's schema
  (migration `0001`) to head with rows intact.
- **The doctor repeats PromptCadence's LoadCoach token check** on its card
  (`promptcadence.loadcoach_token`): *ok* when LoadCoach answers PromptCadence and accepts its
  token, a *failure* naming the re-issue when it refuses it, *unknown* while PromptCadence is
  stopped or too old to say (`history/handoffs/W6_HANDOFF.md` §8 item 4).
- **Settings:** an application's per-key `applies` (IdeaPress: *next stage*) is shown instead of
  *live* when its document states one; a stored runtime row offers **clear**, which sends
  `null` through the application's own `PUT /settings` and is audited as `cleared`
  (`history/handoffs/WI1_HANDOFF.md` §5 items 4a–4b).
- A successful `catalog_pull` queues a `model_refresh`, so a pulled model reaches the catalog
  without a second click; `freeweight_suite_run` launches under a named scope
  (`wr-gym-fwrun-<job>.scope`) that the `memory_cap` alert source watches; every child process
  runs with `PYTHONUNBUFFERED=1`, so a run id is visible while the run is going
  (`history/handoffs/W9_HANDOFF.md` §5 items 5f–5h).

### Changed
- **Spec §15's JavaScript budget is one total, 120 KB** (ADR-0139, superseding ADR-0138 the same
  day at the operator's review): everything a shell page downloads, htmx and its SSE extension
  (ADR-0128) included; only ECharts and mermaid, which load where used, are outside it. 89 KiB
  on the heaviest page at this release; the test prints the breakdown.
- `mirrorwall>=0.3.1,<0.4` (W3's `TODO` closed): the shell needs `mw:telemetry`,
  `product_href`, `theme_control`, the multipart CSRF fix and `log_pane`'s `sse-close`.
- `MEMORY_SAFETY.md` §2.3 fires a capped transient unit rather than a 131 072-token request
  to Ollama, which no longer drives `ollama.service` past its cap on Ollama 0.32 with `--fit`
  (`history/handoffs/W9_HANDOFF.md` §4.4); mirrored into the four applications.

### Fixed
- A `settings.write` audit row said `touched_security: true` for a change to an unrelated key:
  the page posts every field, and an unchanged security key counted as touched and demanded the
  password. Only a security key whose value changed counts (WI1 §5 item 4c).
- `tests/unit/test_cli.py::test_units_sync_writes_reports_and_audits` pins `PATH`, so an
  activated virtualenv (where `wr-gym` resolves and a fifth unit is written) no longer fails it
  (WI1 §5 item 4d).
- `wr-gym jobs run … --wait` follows a `self_restore` to its end: the handle that queued the job
  is closed before the wait and each poll opens its own, so the database file the helper swaps
  in (ADR-0136) is the one read — the live run at W10 showed a completed restore as *still
  running* for the whole timeout.

### Removed
- The `~/ai/suite/docs` symlink of the W0–W10 transition; every kickoff prompt and comment that
  named it says `WeightRoom/docs` now.

## [0.7.0-unreleased] — the work of rows W8, W9, WA1 (2026-09-10), carried into 1.0.0

### Added
- **The job queue** (row W9, `domain/jobs.py`, `services/jobs.py`, `services/job_kinds.py`,
  `/jobs`, `wr-gym jobs list|show|run|cancel|schedule`, migration `0006`): WeightRoomGym's own
  database-backed queue in ADR-0010/0029's shape. The claim is a compare-and-set on
  `state = 'queued'` and the only writer of `attempt`; a lease keeper thread — never the worker —
  renews every `lease_seconds / 3`; recovery runs at startup and on every tick, requeuing an
  idempotent kind whose lease expired and failing `freeweight_suite_run`/`self_restore` as
  `worker_lost`. A cancel stops a queued job at once and flags a running one, whose executor stops
  (`SIGINT` to a child). Schedules are five-field cron expressions in UTC, parsed with the standard
  library; a slot missed during downtime runs once. Five schedules are seeded disabled. Kinds:
  `freeweight_suite_run` (`freeweight run start`, inside `systemd-run --user --scope` under the host
  memory cap, refused without `systemd-run`), `backup`, `model_refresh`, `retention_trim` (finished
  jobs after 90 days; guarded-write backups after `guarded_backup_days`, which is ADR-0134 rule 3's
  expiry, first implemented here; FreeWeight's own deletion only when `freeweight_older_than_days`
  is set, re-authenticated), `docs_index`, `catalog_pull` — the pull W8 ran in a daemon thread is now
  a queued job, its live progress still streamed — and `self_restore`. Each execution is one
  `job.run` audit row, pending then completed, with its output captured to a capped tail and polled
  live on the job's page.
- **WeightRoomGym restores its own database from the console** (ADR-0136, `services/self_restore.py`,
  `wr-gym db restore-self`): a `self_restore` job, re-authenticated and typed, hands itself to a
  transient `systemd --user` unit that stops the console, takes a `pre-restore` backup, restores,
  migrates, carries the job and its audit row into the restored database and starts the console
  again — putting the database back if the restore fails. The Backups page offers it for
  WeightRoomGym's own backups; a console not running as `weightroom.service` is refused by name.
- **Alerts** (row W9, ADR-0137, `domain/alerts.py`, `services/alerts.py`, `/alerts`,
  `wr-gym alerts list|ack`, migration `0007`): an evaluator on its own thread reads five sources
  every `alerts.interval_seconds` — `app_down` (a failed or self-restarting unit, or a running one
  whose `/api/v1/health` is not `200`; an inactive unit is a choice, not an outage), `memory_cap`
  (both journals grepped for ADR-0119's kill, kept where a line names `ollama.service` or an
  application unit), `gpu_thermal`, `budget_ceiling` (LoadLedger verdicts at or over a ceiling) and
  `breaker_open` (LoadCoach's `/reliability`). An alert is an episode: one active per
  `(source, subject)`, held by a partial unique index; a condition clears itself, a kill waits for
  its acknowledgement, and a source that could not be read clears nothing. Every shell page carries
  the banner — the newest unacknowledged alert with its evidence and an acknowledge button, polled
  every five seconds — and the top bar's ⚠ count links to the Alerts page and its history, which
  is kept for ever. Nothing is sent anywhere.
- **The prompt editor** (row W9, `services/prompts.py`, `/apps/{app}/prompts`, migration `0008`):
  FreeWeight's and IdeaPress's shipped packs, read through their own `prompts list|show`, joined
  with the overrides under `$XDG_CONFIG_HOME/<app>/prompts/`. An override is a whole record: the
  editor validates it with `setspec.prompts.load_record` — the loader the application itself runs —
  on a candidate beside the real path before it replaces anything, refuses one that declares another
  `prompt_id`, names a prompt the pack does not ship, or would not load, diffs it against the shipped
  record, shows an override on disk that would not load, and deletes it to restore the shipped
  prompt. Each application's own rule is shown beside the editor (FreeWeight's
  `--allow-prompt-override`, IdeaPress's restart); LoadCoach and PromptCadence, with no `prompts`
  command, are named as such. Every write is a `prompt.override` or `prompt.delete` audit row.
  Migration `0008` makes IdeaPress `0011` (`attempts.prompt_source`, row W9) a known revision.
- **The model catalog** (row W8, `services/catalog.py`, `/catalog`): FreeWeight's and LoadCoach's
  models joined by canonical identity — the only two applications with a models table at all —
  with per-application enabled state (ADR-0118), evidence freshness (always FreeWeight's own),
  size, context and residency (LoadCoach's own `residency` table first, an Ollama `/api/ps` check
  for a row it does not carry). Enable/disable proxies to that application's own
  `POST /models/{id}/enabled`; a GGUF drop-in validates magic bytes, size and containment before
  copying into the model directory every llama.cpp-configured application shares, then refreshes
  each one; a catalog delete previews and, typed and re-authenticated, removes the Ollama tag or
  the GGUF file and FreeWeight's own stored results (Database Standards §8, ADR-0134 rule 2). A
  pull is Ollama's own streamed `/api/pull`, run in a daemon thread with its progress held in
  memory only (`PullRegistry`) until row W9 hosts it as a real job.
- **The Costs page** (row W8, `services/costs.py`, `/costs`): LoadLedger balances for
  PromptCadence and IdeaPress — the only two applications that mount its tables — read through a
  `SqlLedger` bound to the same read-only engine every application's page already opens, never a
  hand-written `select`. Today's `PER_DAY` window is populated by every debit regardless of
  configured ceilings, so it answers for IdeaPress too, which declares none; PromptCadence's own
  `daily_money_ceiling` is the one ceiling this page evaluates app-wide and carries a real verdict,
  since its other ceilings and IdeaPress's own (`per_output_*`, `per_project_*`) are `PER_RUN`/
  `PER_TAG` — meaningless without picking one run or project, and `position()` refuses `PER_RUN`
  outright.
- **The Backups page** (row W8, `/backups`): each application's own `db status`, its own
  `backups/` directory (`services/db_curated.application_backups`, never WeightRoomGym's
  guarded-write directory, a different thing at a different path) and the guarded-write undo
  copies already listed at `GET /apps/{app}/db/backups`. Backup, upgrade and restore themselves
  stay on each application's own database page (W7); WeightRoomGym's own database, which has no
  other page, gets `status`/`backup`/`upgrade` here, in-process (`services/db_curated.
  run_self_curated`, `services/database.backup_directory`) — never a subprocess launch of itself.
  **No self-restore route**: this page is served from the connection pool a live restore would
  replace out from under itself, so restore stays `wr-gym db restore <file> --confirm` from a
  terminal with the unit stopped, the way any other application's restore already requires. One
  application not installed degrades to that row's own failure, never the whole page.
- **FreeWeight `0010` is a known revision** (row WA1, ADR-0135). Migration `0005` adds it to
  `known_revisions`, beside `0009`, so a FreeWeight database carrying `0010` — whose
  `runtime_profiles` gains `adapters_registered` — is read rather than refused as unknown. `tests/fixtures/databases/`
  gains `freeweight-0010.sqlite3`, and the never-writable guard tests run against it.

## [0.7.0] — 2026-09-10

Row W7: Phase 7 of the development plan — every application's database readable, a raw write only
under ADR-0124's five conditions, and the applications' own database operations offered first.
Prepared, not tagged, not pushed, not published.

### Added
- **The guard, pure** (`domain/guard.py`): ADR-0124's five conditions as a checklist with a verdict
  per condition; the never-writable tables as data, compared by test against the record's own
  table and against the four fixture databases; a SQL lexer that reads one statement's verb, the
  tables it names and the tables it writes, and refuses `CREATE`, `ALTER`, `DROP`, `PRAGMA`,
  `VACUUM`, `ATTACH`, `BEGIN` and every other non-DML keyword by name, and any second statement;
  the foreign-key reach that makes a cascade into a locked table a write.
- **ADR-0133**: the guard follows foreign keys into the never-writable list (`DELETE FROM projects`
  is refused in IdeaPress: it cascades into `stage_runs`); `sqlite_*` and `pg_*` are never written;
  *stopped* is the unit **and** the port; the database URL is `config show --json`'s effective
  value; a write is bound to its dry run by a digest and rolled back if its counts differ; condition
  5 has its own code, `GUARD_AUDIT_FAILED`.
- **ADR-0134** (the operator's review of W7): a cascaded delete may remove an event log's rows —
  `DELETE FROM runs` takes its `run_events` with it — while a statement naming an event log, or a
  cascade that edits one, is still refused, and an edit reached by a second path is never hidden
  behind the delete. FreeWeight's own deletion of stored results (its `delete-preview` and
  `DELETE /database/results`) is offered on its database page and above the guard on `runs`,
  `run_tests`, `samples` and `metric_values` — previewed, the selector typed, re-authenticated —
  through `POST /api/v1/apps/{app}/db/delete-results`. Guarded-write backups expire after 90 days,
  from row W8.
- **The reader** (`services/db_reader.py`): each application's database opened unpooled and
  read-only (`mode=ro`; `default_transaction_read_only` with a 30 s `statement_timeout`) and
  checked against `known_revisions` (`SCHEMA_UNKNOWN` by name); tables with row counts and their
  lock; a typed, sorted, filtered page of 100 rows; the SQL console — one `SELECT`, 30 s, 10 000
  rows.
- **The guarded write** (`services/db_guard.py`): the typed names, the unit and the port, the
  repeated dry run, a backup through `weightsdb.backup` into
  `<data>/backups/<app>/<utc>-guarded-write.sqlite3` (mode 0600; expired after 90 days from row W8, ADR-0134), the `pending` audit
  row carrying the backup path, the statement on its own short-lived connection, the row completed.
  A crash between the pending row and the statement leaves the row `pending` (tested).
- **The applications' own operations** (`services/db_curated.py`): `db status|backup|upgrade|restore`
  and FreeWeight's `db vacuum`; a restore needs the unit stopped, the name typed and
  re-authentication. Per-table operations as data: LoadCoach's and PromptCadence's content
  retention, and FreeWeight's own deletion of stored results over its API (ADR-0134).
- Routes `GET …/db/revision`, `…/db/tables`, `…/db/tables/{t}`, `…/db/status`, `…/db/backups` and
  `POST …/db/query`, `…/db/write/dry-run`, `…/db/write`, `…/db/backup`, `…/db/upgrade`,
  `…/db/restore`; pages `/database`, `/apps/{app}/database` (own operations, tables, console) and
  `/apps/{app}/database/{table}` (the grid, the table's own operations first, the guard dialog).
  The Database entries in the top bar and in every application's side nav are links now.
- `db_revision` and `known` filled in `GET /apps`, `GET /apps/{app}` and `GET /system/status`.
- Audit actions `db.query` and `db.dry_run`; `statement` on every audit row the API returns;
  `services.audit.complete`, the trail's one update (`pending` to `ok` or `failed`).

### Changed
- The Overview table and the doctor's revision rule read the applications' databases through the
  read-only reader. They had opened them with `weightsdb.create_engine_for`, which sets pragmas
  and creates directories — writes against a file another application owns.
- The re-authentication restamp moved from `web/routes/settings.py` to `web/session.py`, as W4
  asked when a second caller arrived.

### Fixed
- The migration parity test's PostgreSQL leg expected FTS5's shadow tables but not `docs_index`'s
  GIN index, and had failed against a real server since row W5.

## [0.6.0] — 2026-09-10

Row W6: Phase 6 of the development plan — chat through LoadCoach and PromptCadence, thinking that
streams and collapses, the routing decision and cost under every reply, PromptCadence's plan, steps,
tools, egress and approvals inline. It also carries the shell, telemetry and docs-viewer changes
made on `main` while W6 ran on its branch (merged 2026-09-10). Prepared, not tagged, not pushed,
not published.

### Added
- **The chat model and the thinking state machine** (`domain/chat.py`, migration `0004`):
  `conversations` with a check constraint naming the two backends and no third (spec §11 contract
  6), `messages`, `message_events` and `attachments`. Thinking opens on the first thinking delta,
  collapses on the first text delta that is not whitespace or on the terminal frame, never
  reopens, fills from the result when a backend reports it only at the end, and shows no block for
  a provider with no thinking channel.
- **Chat through LoadCoach** (`services/chat_loadcoach.py`): the whole conversation as
  `messages`, the task profile and optional model pin, live `thinking` and `token` frames, the
  routing line from the stream's own `routing` frame, tokens by class with `—` for anything
  unreported and money only where priced.
- **Chat through PromptCadence** (`services/chat_promptcadence.py`): one trajectory per message
  with the conversation so far as context, the tool allowlist always sent (an omitted one is every
  tool to PromptCadence), plan/step/tool-call cards as the events arrive, recorded egress
  decisions at the end, the answer from the last assistant turn, halts in PromptCadence's own
  words, and approvals granted or denied inline with the `approve`-scoped token — a token without
  the scope shows *no approve scope* and no button that would fail.
- **Replies run beside the request** (`services/chat.py`): a small thread pool, one persisted row
  per step, and one transaction on completion that fills the message, drops the deltas and writes
  `done` or `halt` (ADR-0044). The page's stream replays by `Last-Event-ID`. A reply interrupted by
  a console restart is closed as a named halt at startup.
- **Attachments**: text and markdown only, capped, stored `0600` under a generated name, prepended
  as fenced context to every request of the conversation.
- **Nothing raw**: live deltas reach the page as `textContent`; the finished answer is rendered by
  an escape-on markdown renderer (http(s) links only, images reduced to alt text so nothing a
  model wrote is fetched) and handed to Jinja through `__html__`; no chat template marks anything
  safe. PromptCadence's own injection corpus is rendered through every path into a thread.
- `chat.create`, `chat.message`, `chat.attachment`, `chat.delete`, `chat.approve` and `chat.deny`
  join the audit vocabulary; `CHAT_BACKEND_UNAVAILABLE`, `ATTACHMENT_TOO_LARGE` and
  `ATTACHMENT_TYPE_REFUSED` join the error codes.
- A network-isolation test: a reply through either backend reaches the two configured base URLs
  and nothing else, and opens no raw socket.

### Found, and fixed where they live
- **LoadCoach dropped live thinking** (ADR-0132, `loadcoach 1.5.0`): ModelRack streamed each
  reasoning delta and LoadCoach forwarded only answer tokens, so thinking arrived after the answer.
  LoadCoach now streams a `thinking` frame; this console falls back to `result.reasoning` for an
  older LoadCoach.
- **MirrorWall refused every multipart form** as `CSRF_FAILED` — the token was searched for with a
  parser that cannot read multipart. Fixed in MirrorWall (`[Unreleased]`); attachment uploads
  depended on it.
- **PromptCadence could not run any trajectory on the reference machine**: LoadCoach requires a
  bearer token once any exists, and PromptCadence had none. A LoadCoach token was minted for it and
  configured by reference (host change, recorded in the W6 handoff).
- The security checklist's Phase 1 *no uploads* test is now an allowlist of the two attachment
  routes.
### Fixed

- The console no longer floods LoadCoach with `GET /api/v1/system/status`. Every telemetry
  stream read LoadCoach's queue on each pass of its poll loop — five a second per stream, two
  streams per tab — until LoadCoach's rate limiter answered 429 and its journal filled with
  `request.rate_limited`. The sampler now reads it once per tick and every stream, page and
  `/system/status` call shares that read.
- The per-application Overview's log pane showed raw JSON envelopes: MirrorWall's `log_pane` swaps
  each frame's data in as-is. It now uses the same pane `/logs` does, which is a classic script
  (a module script has no `document.currentScript`) with its own toolbar rather than MirrorWall's
  stacked `.field` form layout.
- The log stream stops reconnecting once it is over. An `EventSource` cannot tell a stream the
  server ended from a connection that dropped, so it retried both — and a host with no
  `journalctl` ended the stream the same way on every retry, which is the repeated `GET` on
  `…/logs/stream` in the access log. The error frame is now followed by `log.closed`, the pane
  closes on it, and MirrorWall's own pane carries `sse-close`.
- The telemetry strip is live. The shell now loads MirrorWall's `sse.js` and `telemetry.js`
  (both opt-in per application, and neither was loaded), so CPU, RAM, GPU and VRAM show
  measurements instead of the em dashes they held from first paint onwards. RESIDENT and QUEUE
  wait for `DOMContentLoaded` before looking for `mirrorwallSse`, which is deferred and did not
  exist when the inline script ran.

### Changed

- A document page no longer repeats its path under the docs side menu (the breadcrumb already
  shows it), and each top-level folder block in a section listing has space below it.
- In a docs section's listing, each application's or package's folder heading is larger and
  ruled; a folder inside it (`guide/`) keeps the plain smaller heading with no rule.
- The page body starts 16 px below the top bar and telemetry strip instead of touching them.
- Each application's and package's own README and user documents (quickstart, api, operations,
  …) appear in the docs viewer under `apps/<name>/guide/` and `packages/<name>/guide/`. They
  are copied from the components by `docs/scripts/sync_component_docs.py`; `--check` reports
  a stale copy.
- The documentation tree: `docs/history/` now holds the handoffs under `handoffs/` and the
  kickoff prompts under `prompts/`, so the docs viewer's History section lists them under
  their own headings. Every reference across the suite follows the move. `docs/inventory/` is
  removed.
- The docs viewer is organised by section. The left menu lists Home (the root's own documents),
  Apps, Packages, Standards, Architecture, ADR, Roadmap, History and Reviews, with any other
  top-level folder appended after them; the selected section expands to its folders. Choosing a
  section replaces the side menu and main pane in place (htmx), and the main pane lists that
  section's documents under one heading per folder. The page has no "Documentation" heading, no
  read-only path line and no ADR index link, and search is just the field and its button.
- A telemetry icon in the top bar shows and hides the strip, remembered per browser. Hidden, the
  page opens no telemetry stream at all: the server polls nothing for that tab, and once no tab is
  streaming, WeightRoom asks Ollama and LoadCoach nothing either. Rendering a page no longer counts
  as watching — only an open stream renews the reader window.
- Telemetry asks Ollama and LoadCoach nothing while nobody is looking. The host is still sampled
  every tick — that is local and feeds history — but the residency read (`/api/ps`) and the queue
  read (`/api/v1/system/status`) happen only while a page or stream is reading, renewed by every
  stream frame and dropped fifteen seconds after the last, and then at most every five seconds
  each. Measured before: sixty queue reads a minute in LoadCoach's journal and thirteen `/api/ps`
  in Ollama's.
- One telemetry stream per tab, not two: RESIDENT and QUEUE read the frame MirrorWall's
  `telemetry.js` re-dispatches on the bar (`mw:telemetry`) instead of opening their own
  `EventSource` to the same URL, halving the server's per-tab database polling.
- httpx no longer logs every outgoing request unless `[logging] level` is `DEBUG`.
- The header shows no version, on the login page or after it; the operator menu shows it.
- The top bar is the artboard's single 48 px row (design brief §4): brand, application tabs,
  console pages, alerts, a compact theme control with a visually hidden label, and the operator
  chip at the right edge. The strip opts into MirrorWall's inline meters for all four fields.
- The console Overview lists the four applications as a dense table with status dots, uptime,
  version and unit, in place of the bulleted links row W3 shipped.
- The shell reflows instead of scrolling sideways, verified in headless Chrome at 1440, 900 and
  390 px on `/`, `/apps/loadcoach` and `/logs` with no element scrolling horizontally. Below
  900 px the top bar's tabs, console pages and theme control collapse into a *Menu* dropdown
  (one `<details>`, open with its summary hidden above the breakpoint, closing on an outside click);
  the left menu is a disclosure named for its section; the telemetry strip wraps and shows values
  without meter tracks; the main pane stretches instead of sizing to its widest line; and the
  Overview table drops its version and unit columns below 600 px. The side menu's version footer
  now sits after the unbuilt pages rather than between them.
- The top bar collapses in two steps instead of wrapping or overlapping: below 1080 px the console
  pages (Chat, Docs, Database, Jobs, alerts) move into a *Menu* dropdown, below 860 px the
  application tabs follow. The theme control and log out moved into an operator menu at the right
  edge, which is what the theme select used to collide with. The telemetry strip wraps rather
  than scrolling at any width, and drops its meter tracks below 1080 px. Swept in headless Chrome
  from 1400 px to 320 px in 10 px steps: no horizontal scroll, no overlapping top-bar item.
- The header reads **WeightRoom** and links to the Overview; page titles and page text say
  WeightRoom too. The distribution, CLI, certificates and documentation keep WeightRoomGym and
  `wr-gym`.
- Applications are displayed by their names — FreeWeight, LoadCoach, IdeaPress, PromptCadence —
  in the tabs, the Menu, the Overview table, the side menu, and page titles and text. Routes,
  units, CLI invocations and config sections keep the lowercase identifier.
- W4's pages follow the same rule now that they sit in that shell: below 700 px the settings
  form, the doctor's findings and the token list stack each row into a card instead of scrolling
  the page, and a long config path or command wraps inside the main pane.

## [0.5.0] — 2026-09-10

Row W5: Phase 5 of the development plan — the documentation viewer. Prepared, not tagged, not
pushed, not published. The one flexible row (any time after W3); built without W4.

### Added
- **`services/docs.py`**: `[docs] root` resolution (configured, else the `docs/` beside this
  checkout, else `DOCS_ROOT_MISSING`); resolve-then-check containment mirroring ToolYard's
  `PathContainment` (read as the containment vector set, never imported — ADR-0123 rule 4); the
  directory tree; a `mistune.HTMLRenderer(escape=True)` renderer built fresh per request (never
  shared — Starlette runs sync routes in a threadpool) with stable heading ids and an outline, a
  `mermaid` fence mounted as `<pre class="mermaid">`, and relative links rewritten to
  `/docs/page` routes only when they resolve to a `.md` file inside the root — everything else
  (outside the root, a non-markdown target, an image; there is no raw-asset route in api.md §8)
  renders as plain text. `adr/README.md`'s own table is the ADR index, never the filenames.
- **`services/docs_index.py`**: migration `0003` creates `docs_index` as an FTS5 virtual table on
  SQLite when the module is compiled in, a plain three-column table otherwise (spec §13 risk T9),
  and a table with a generated `tsvector` column plus a GIN index on PostgreSQL; `search()`
  degrades to a parameterised `LIKE` query — labelled `degraded=True` — on a malformed FTS5 query
  or a missing FTS5 module alike, rather than a 500 from a search box. `wr-gym docs index`
  rebuilds it from the tree.
- `GET /docs/tree`, `GET /docs/page?path=`, `GET /docs/search?q=`, `GET /docs/adrs` (JSON,
  api.md §8) and their HTML pages inside the shell (`/docs`, `/docs/page`, `/docs/search`,
  `/docs/adrs`); the top bar's "Docs" entry is a real link now, not a stub.
- **mermaid 11.17.2 vendored** (`web/static/vendor/mermaid/`, MIT, offline, ~3.4 MB — spec §15's
  one exception to the per-page JS budget) and mounted at `/app-static/`
  (`mount_static`'s `extra_dirs`, a WeightRoomGym-owned static root distinct from MirrorWall's);
  loaded only on a page whose document contains a `mermaid` fence, with `securityLevel: "strict"`
  (a diagram's source is untrusted document content, security standards §6).

### Changed
- `services/health.py`'s `STATUS_BY_CODE` gains `DOCS_ROOT_MISSING` (500) and
  `DOCS_PAGE_OUTSIDE_ROOT` (404).
- The security checklist's "no route accepts a path-shaped parameter" test now carries a named,
  reviewed allowlist (`/docs/page`'s `path`, both the JSON and HTML routes) rather than refusing
  the documentation viewer's one legitimate, contained exception outright.

### Decided
- **`docs_index`'s FTS5 shadow tables are excluded from the migration-parity check by name**
  (`FTS5_SHADOW_TABLES`, `tests/integration/test_migrations.py`) — SQLite's FTS5 module creates
  five bookkeeping tables alongside the virtual table itself, none of which is or should be
  modelled in `Base.metadata`.
- **No raw-asset route this row.** A markdown image or a link to a non-`.md` file renders as
  plain text rather than a broken link — api.md §8 names four routes and none of them serves a
  raw file. A later row can add one if the documentation ever needs embedded images rendered.
- **The ADR index kickoff's demonstration number is stale.** The row's own prompt says "the ADR
  index of 127 rows"; the real `adr/README.md` carries 129 as of this row (ADRs 0128–0129 landed
  at W3/WM). Rendered as whatever is actually there, not force-fit to 127.

## [0.4.0] — 2026-09-09

Row W4: Phase 4 of the development plan — every application's settings editable from the console
through its own schema and its own validation, the doctor, and per-application token pages.
Prepared, not tagged, not pushed, not published.

### Added
- **Settings forms generated from each application's schema document** (`services/settings_forms.py`,
  ADR-0127 rule 3): `<app> config schema --json` is read (a subprocess for the four, in process
  for WeightRoomGym's own), cached 60 s, and turned into a form model — type, bounds, default,
  description, current value, `source`, *shadowed*, and the runtime and security sets. **No key of
  any application is named in this repository**; a field added to an application appears on the
  next read. The key list is the document's own three sets rather than a walk of `json_schema`,
  which is what makes LoadCoach's database-only `queue.paused`, IdeaPress's eleven
  `models.stages.<stage>` bindings and PromptCadence's `[tiers.<name>]` instances render at all.
- **The write paths** (`services/config_files.py`): ADR-0117's sequence applied to every key of
  every application's file from outside the process that owns it — refuse a stale `base_mtime`
  (`st_mtime_ns`, exact in JSON), round-trip with `tomlkit` so every comment and untouched line
  survives, validate the candidate through `<app> config validate --file`, then `fsync` and
  rename with the previous file kept as `config.toml.bak`.
- `GET /apps/{app}/settings/schema` · `GET|PUT /apps/{app}/settings` ·
  `POST /apps/{app}/settings/validate` · `GET /apps/{app}/config`, with per-key outcomes
  (`applied`, `written`, `unchanged`, `refused`) and the refusing party's own words;
  `GET|PUT /settings` for the console's own runtime keys (ADR-0100's shape).
- **Pages**: `/apps/{app}/settings` for each of the four, `/settings` for WeightRoomGym itself
  from its own verb, and `/apps/{app}/settings/raw` — the whole-file editor, deliberately on its
  own page because it shows the file's secrets verbatim.
- ***Pending restart*** and the restart button, derived from the file's modification time against
  the unit's uptime rather than stored, so a restart made from a terminal is seen and a console
  restart does not lose the state.
- **`wr-gym doctor` and the Doctor page** (`services/doctor.py`): one finding per rule with a
  severity, the evidence it actually read and the command that fixes it — `MEMORY_SAFETY.md` §2.1
  (Ollama's daemon) and §2.2 (each unit's memory cap), an application off loopback and Ollama on
  `0.0.0.0` (`LAN_ACCESS.md` §1 and §5), versions and schema revisions in range, TLS expiry,
  lingering, the polkit rule, free space under each data root, and the `[server]` block the
  retired `expose_on_lan.sh` left behind. **Every fix is printed and none is run**; the command
  exits `1` on a failure or a warning and `0` on a notice.
- **Tokens pages** (`services/tokens.py`): `token list|create|revoke` through each application's
  own CLI. A new token's secret is shown once, on the page that minted it, and is stored nowhere.
  LoadCoach and PromptCadence have the verb; FreeWeight's tokens are `auth.tokens` on its settings
  page and the page says so; IdeaPress has none.
- `settings.validate`, `token.create` and `token.revoke` join the closed audit vocabulary.
- **[ADR-0130](docs/adr/0130-weightroomgyms-application-tokens-carry-admin-scope.md)**: the
  wizard's tokens carry `admin` (`{"loadcoach": "admin", "promptcadence": "admin,approve"}`).
  Found demonstrating Phase 4 criterion 1 on the reference machine — ADR-0126 rule 8 chose
  `write` before the settings page existed, and both applications' `PUT /settings` requires
  `admin`, so every runtime key was readable and none was writable. `wr-gym doctor` reports an
  install whose token is narrower and prints the two commands that re-issue it.

### Changed
- **Re-authentication for a security key is the session, not a token** (ADR-0127 rule 6). api.md
  §2 sketched a `reauth` token on the write body; W1 already implements the window as a stamp on
  the session row, and a second credential in the DOM would be strictly worse on a LAN-facing
  page with nothing to gain. The page posts the password with the change; the window opens and is
  spent in the same request. `docs/apps/weightroom/api.md` is amended to match.
- An application's side nav links the pages this build serves and says where a page that is
  deliberately somebody else's lives — a provider registration stays in the application's own
  ADR-0117 form.

### Fixed
- `services/ollama.py`: a polkit-grant probe against an unmigrated or unreadable audit trail
  answers `unknown` instead of raising, so `wr-gym doctor` runs on a fresh install.
- `services/overview.py`: IdeaPress calls `config show --json`'s block `settings` where the other
  three call it `values`, so its Overview could not find its database and fell back to the dashed
  figures. Both spellings are read. Found by the doctor's revision rule on the reference machine.
- The `settings.write` audit row's flag is `touched_security`, not `security_key`: the redactor
  blanks any parameter whose name matches `key`, and a redacted boolean reads like a caught leak.

## [0.3.0] — 2026-09-09

Row W3: Phase 3 of the development plan — the telemetry sampler, the real shell over MirrorWall
0.3, and each application's Overview page. Prepared, not tagged, not pushed, not published;
MirrorWall 0.3.0 pinned as an editable path install (prepared, not yet published itself —
TODO: re-pin `mirrorwall==0.3.0` once it is).

### Added
- **`services/telemetry.py`**: `sweatmeter` in process, one `TelemetryService` owning a
  `TelemetrySampler` thread that writes one `telemetry_samples` row per tick (migration `0002`),
  every unavailable reading `NULL`, never `0` (ADR-0016). Resident models cached on a five-second
  cadence rather than asked every tick; LoadCoach's queue depth is read live per frame and never
  persisted. A background sweep keeps rows older than an hour at one per minute and drops
  anything past `[telemetry] history_hours`, grouped in Python so the same sweep runs on SQLite
  and PostgreSQL.
- `GET /system/telemetry/stream` — SSE, replaying from `Last-Event-ID` by polling the store for
  rows after the highest id already seen, the same pattern `web/routes/apps.py`'s log stream and
  FreeWeight's run event store already use, rather than an in-memory fan-out.
- `GET /system/telemetry/history?figure=&hours=` — one figure's already-downsampled series.
- `GET /system/resident` — Ollama's `/api/ps` through ModelRack and LoadCoach's own residency,
  each row naming its source.
- **The shell** (design brief §4): `_shell.html`, which every operator-facing page now extends
  instead of `mirrorwall/base.html` directly — the four app tabs with status dots
  (`render_shell_page`, reusing `services/health.py`'s own pill-to-status-dot map), the telemetry
  strip with the two WeightRoomGym-specific RESIDENT/QUEUE meters, the console's own page ghosts
  named with the row that builds them, the operator chip, and a per-application left menu with
  Overview linked and every other spec §7.3 page inert and titled with its row where one is
  scheduled.
- **Each application's Overview** (`services/overview.py`): the pill, four figures, the primary
  table, the log tail (MirrorWall's `log_pane`, replacing the pre-0.3 `_log_pane.html` on this
  page only). Figures read `GET /api/v1/system/status` when the application answers and a
  `COUNT(*)` over named tables (data model §4) when it does not; the primary table always reads
  the same tables directly, running or not (a deliberate narrowing from a literal API-when-up
  reading — see the module's own docstring); an unknown `alembic_version` degrades the table by
  name with the application's API-sourced figures unaffected (spec §11 contract 4).
- `GET /system/status` now completes its `ollama` and `telemetry` fields.

### Decided
- **The primary table is database-sourced in every state, not only when stopped.** Each
  application's list endpoint has its own JSON shape that would need reading and pinning
  per application before a row of it could render here; every application already exposes the one
  shape the table needs (`alembic_version` plus a handful of named tables) through the read-only
  connection this row already opens for the stopped case, and spec §10 already lists "database"
  as a legitimate read path generally, not one reserved for a stopped application. W7's guarded
  database viewer is where a *browsable* table belongs; this Overview table is content to be a
  read of the same rows, once.
- **RESIDENT and QUEUE do not refresh in place.** The strip's generic CPU/GPU/RAM fields are
  wired live by MirrorWall's own `telemetry.js`; these two WeightRoomGym-specific meters render
  from the last sample at page load and do not update until an operator navigates again — the one
  corner this row cut on the strip's "moving once a second" claim.
- **Not every spec §7.3 page has a row yet.** Only Settings/Tokens/Providers (W4) and Database
  (W7) are named with a phase in the side menu; Models, Runs, Routing, Queue, Evidence, Adapters
  and the rest have no row in `roadmap/weightroom-work.md` between W3 and W10 as of this row —
  recorded as a documentation gap, not invented an answer to (`W3_HANDOFF.md` §5).

## [0.2.0] — 2026-09-09

Row W2: Phase 2 of the development plan — process control, unified logs, the Ollama pane and the
audit page. Prepared, not published.

### Added
- **The five `systemd --user` units** (ADR-0125 rule 1). `domain/units.py` holds the template as
  data, renders each file whole and diffs it against what is on disk; a golden per application is
  checked in. The three `Memory*` lines are written for `freeweight` and `loadcoach` only, from
  `[host] memory_high`/`memory_max`; `weightroom.service` carries no cap. Every file names the
  WeightRoomGym version that wrote it, so a version change is a rewrite (spec §19).
- `wr-gym units sync|status|start|stop|restart <app>|all`. `sync` writes only what differs and
  reloads systemd only when something was written, so a second run is a no-op (spec §11
  contract 8); `--diff` prints exactly what a hand edit is losing; `--dry-run` writes nothing.
- **`services/processes.py`**, the `systemctl`/`loginctl` boundary: a `SystemdController` port,
  a subprocess implementation with `which` and the launcher injected, and an in-memory fake.
  Explicit argv, an allowlisted environment (gold standard G12), a timeout and an output cap;
  never a shell, never `sudo`.
- **The wizard's linger and units steps** (ADR-0125 rules 2 and 6). `wr-gym setup` enables
  lingering *before* it writes a unit and refuses to continue with the command to run by hand,
  then writes the five units and enables and starts `weightroom.service`;
  `--no-start-console` leaves it written for a foreground `wr-gym serve`.
- `GET /apps`, `/apps/{app}`, `/apps/{app}/health` (the application's own body, proxied verbatim
  with `source`), and `POST /apps/{app}/start|stop|restart` returning `202` with the audit id and
  the new unit state. The pages carry one form-post control route with the verb as a `Literal`.
- **Version negotiation per application** (spec §19): `GET /api/v1/version` on first contact,
  cached for five minutes and re-probed immediately after a control action; a version outside
  `>=1.0,<2.0` is `APP_VERSION_MISMATCH` and degrades that application by name.
- **`services/journal.py`**: history as `journalctl -o json --reverse`, newest first, capped at
  5 000 rows and paged with systemd's own cursor, with `--since`/`--until`, a level filter and a
  literal (escaped) text search; and a live follow as SSE per application and across every unit
  at once, over MirrorWall's bounded subscription, with a *dropped N lines* frame when a client
  falls behind and a ceiling of sixteen concurrent streams.
- `wr-gym apps status` (the four and Ollama in one table) and `wr-gym logs <app> [--follow]`.
- **The Ollama pane** (ADR-0125 rules 4–5): `GET /ollama` renders `MEMORY_SAFETY.md` §2.1 as
  seven findings over `systemctl show ollama.service`, `GET /ollama/ps` reads residency through
  **ModelRack's** client, and `POST /ollama/restart` restarts the system unit when polkit permits
  it or answers `OLLAMA_RESTART_NOT_PERMITTED` with the rule text, its path and the install
  command. The fix for a failing checklist is `docs/scripts/apply_memory_safety.sh`, **printed**;
  `sudo` is never invoked, asserted by a test over the source tree.
- The audit page gained filters (application, action, since, page size) over the same query the
  API takes.
- `/health` and `/system/status` now report the units and each application for real; a stopped
  application never drops the roll-up.

### Changed
- `GET /apps/*` codes map to HTTP as: `APP_UNKNOWN` 404; `APP_NOT_INSTALLED`, `APP_STOPPED` and
  `APP_VERSION_MISMATCH` 409 (the host is in a state the operator can fix); `APP_UNREACHABLE`
  and `UNIT_ACTION_FAILED` 502 (something the console drives answered badly); `UNIT_UNSUPPORTED`
  501 (this host cannot, and no retry helps); `OLLAMA_RESTART_NOT_PERMITTED` 403.
- The audit vocabulary gained `unit.sync` and `ollama.restart` (`domain/audit.py`, data model §2).

### Fixed
- A partial `[apps.<name>]` table discarded its siblings' defaults, so naming only `executable`
  left `base_url` empty and a running application was reported unreachable. Configuration
  standards §1 requires per-leaf overriding; `AppsSettings` now fills the port back in.
- `host_identity()` ran `ip -json address` with this process's whole environment; it now gets the
  same allowlist as every other child (gold standard G12).

### Decided
- **The polkit-grant probe is the recorded outcome of the last attempt** (ADR-0125 rule 5 left
  the mechanism to this row). The rule file's presence cannot be read — `/etc/polkit-1/rules.d`
  is `0750 root:polkitd` — and polkit cannot be asked: `pkcheck` refuses to evaluate an action
  with details for an untrusted caller, and the rule keys on exactly those details, while
  `systemctl --dry-run restart` exits `0` whether permitted or not. The newest `ollama.restart`
  audit row is therefore the probe, and the attempt passes `--no-ask-password` — without it the
  call blocks on the desktop's interactive polkit agent.
- **`journalctl -u ollama` is readable on the reference machine** (the operator is in `adm`).
  Where it is not, the pane says *journal not readable* by name with journalctl's own message,
  and the rest of the pane works.

## [0.1.0] — 2026-09-09

Published to PyPI on 2026-09-09 by `release.yml` from tag **`v0.1.1`** — the tag `v0.1.0` had
been placed on `9b17d0b`, before the workflow existed, and could not be moved (packaging
standards §6: a release is never re-tagged), so the next tag name was used with the package
still at `0.1.0`. The GitHub release `v0.1.1` therefore carries `wr_gym-0.1.0` artifacts. The
next release is `0.2.0` (row W2) and its tag `v0.2.0`; the name `v0.1.1` is spent.

Row W1: Phase 1 of the development plan — skeleton, configuration, database, TLS, login, `setup`.

### Added
- The standard application layout (`web` → `cli` → `services` → `domain`), with
  `.importlinter` asserting the layering, web/CLI independence, domain purity, and ADR-0123
  rules 3–4 (no application, no `toolyard`/`cutctx`/`commissioner`).
- `config.py`: spec §12 in full with the `defaults → file → env → CLI` precedence at any depth
  (`[apps.<name>]`), `wr-gym config show|validate|init|path|reference|schema` (the schema verb
  is ADR-0127 applied to WeightRoomGym itself), the security-key set (every key under `[server]`,
  `[tls]`, `[auth]`, `[apps.*]`, `[host]`), the six runtime-changeable keys, and the startup
  refusals `INSECURE_BINDING` (ADR-0126 rule 6) and `TLS_MISSING`, exit 3.
- WeightsDB wiring and Alembic `0001`: `operators`, `sessions`, `audit_log`, `settings`,
  `known_revisions` (seeded: FreeWeight `0009`, LoadCoach `0015`, IdeaPress `0010`,
  PromptCadence `0011`); `wr-gym db upgrade|status|backup|restore`.
- The certificate authority (ADR-0126 rule 2): ECDSA P-256, root 10 years with `pathlen:0`,
  leaf 398 days with the host's names and addresses as SANs, renewed at startup under 30 days or
  on an address change; `wr-gym tls init|renew|rotate|show` and `wr-gym trust`; `serve` over
  HTTPS only, plus the plain-HTTP trust listener on `server.trust_port` serving exactly
  `/root.crt` and `/trust` (rule 3).
- One operator account with `hashlib.scrypt` (`n=2**15, r=8, p=1`, parameters stored),
  server-side sessions behind `__Host-weightroom_session` (`HttpOnly`, `Secure`,
  `SameSite=Strict`), 12 h idle / 7 d absolute, a fresh id on every login, 5 login attempts a
  minute per address; `POST /login|logout` (forms) and `POST /api/v1/login|logout|reauth`
  (JSON); `wr-gym operator create|password` (the latter revokes every session). Loopback with no
  account stays open (rule 6).
- CSRF on every form (MirrorWall's double-submit token) and, for cookie authentication, the
  same-origin check on every JSON write: `application/json` + `Sec-Fetch-Site: same-origin`
  (or `none`) + a matching `Origin` (rule 5). The Host allowlist runs before everything.
- The audit trail: a closed action vocabulary, redaction of secret-shaped keys and URL
  credentials before a row exists, `GET /api/v1/audit[/{id}]`, the `/audit` page,
  `wr-gym audit list|show`, and the test that enumerates every state-changing route and asserts
  one row each.
- `wr-gym setup`: the CA, the account, `allowed_hosts` from the host's names and addresses, the
  bind choice, and a token for each installed application stored by file reference under
  `<config>/secrets/` (rule 8); the config file edited in place with comments kept. Units and
  linger are printed as Phase 2 work.
- `GET /api/v1/health` (database, TLS days to expiry, units `not_configured`, each application
  `unknown`), `GET /api/v1/version` (never authenticated), `GET /api/v1/system/status`, a
  placeholder shell behind the login, the console's `/trust` page.
- `requirements/ci.lock` cut on Python 3.13; CI in the full sibling shape (`--require-hashes`,
  `db-matrix`, `coverage`, `contracts`, `security`, `docs`, `build`, `install-check`).
- `docs/configuration.md`, generated from the settings model and diff-checked.
- `.github/workflows/release.yml` in the sibling shape: a `v*.*.*` tag builds from
  `requirements/release.lock`, tests the built wheel, publishes through Trusted Publishing and
  creates the GitHub release; a manual `workflow_dispatch` publishes to TestPyPI (the first
  release's dry run, packaging standards §6).

### Changed
- `__about__` to `0.1.0`.

## [0.0.0] — 2026-09-09

### Added
- Row W0 (2026-09-09): the repository. `OpenWeight-Gym`, formerly the suite's documentation
  repository, becomes the WeightRoomGym repository; the documentation tree moves under `docs/` and
  stays the suite's canonical copy. The package is empty at `0.0.0`; ADRs 0123–0128 and
  `docs/apps/weightroom/` specify what rows W1–W10 build.

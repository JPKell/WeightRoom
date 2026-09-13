# WeightRoomGym — Specification

**Type:** Application (host operator tool) · **Import name:** `weightroom` · **CLI and distribution:**
`wr-gym` · **Default port:** 8769 (HTTPS) · **Env prefix:** `WEIGHTROOM_`
**Status:** Specified 2026-09-09 (row W0, from the operator interview of the same day); not
implemented. Rows W1–W10 in [`roadmap/weightroom-work.md`](../../roadmap/weightroom-work.md).
**Decisions:** [ADR-0123](../../adr/0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md)
(what it is) · [ADR-0124](../../adr/0124-a-raw-write-into-another-applications-database-passes-a-five-part-guard.md)
(the write guard) · [ADR-0125](../../adr/0125-weightroom-drives-the-applications-through-systemd-user-units-it-writes.md)
(process control) · [ADR-0126](../../adr/0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md)
(LAN, TLS, login) · [ADR-0127](../../adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)
(settings schema).
**Related:** [API](api.md) · [Data Model](data-model.md) · [Design brief](design.md) ·
[Development Plan](development-plan.md) · [Risks](risks.md)

---

## 1. Purpose

Give the person who runs the machine **one place** to run it from. WeightRoomGym is the host
operator's console over the four applications: it shows what the machine is doing, starts and
stops the applications, edits their configuration, reads their databases, backs them up, keeps
their logs and its own audit trail in one view, and lets the operator talk to LoadCoach and
PromptCadence from a phone in another room — over one HTTPS port, behind one login.

It is deliberately **not** a fifth peer in the measure → manage → apply → harness chain. It is
the operator, given a console, and it sits above the layer rules by an exception scoped exactly
as [ADR-0123](../../adr/0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md) rule 2
says.

## 2. Scope

Everything below ships in one release, `1.0.0` (interview decision D15), built in internal
phases that are gated ([development plan](development-plan.md)):

* **Shell:** top bar with the four applications as tabs and a status dot each, a 34 px telemetry
  strip on every page, a left menu per application, the console's own pages (Chat, Docs,
  Database, Jobs, Alerts), dense dark by default with a light toggle ([design brief](design.md)).
* **Setup wizard and doctor:** `wr-gym setup` — the CA, the operator account, the units,
  the application tokens, linger; `wr-gym doctor` and the Doctor page — a cross-application
  health and configuration check with `MEMORY_SAFETY.md` §2 and `LAN_ACCESS.md` as its rubric.
* **Process control and logs:** start/stop/restart per application through `systemd --user`,
  the unified live log (every application's journal plus WeightRoomGym's own, filterable), and the
  audit trail of every action the console took.
* **Telemetry:** `sweatmeter` in process at 1 s over SSE; resident models from Ollama's `/api/ps`
  and LoadCoach's residency; clicking any figure opens its history page.
* **Native control surfaces for all four applications** (§7.3): models, routing, queue, evidence,
  adapters, jobs, runs, results, goals, projects, units, trajectories, approvals, ledger, egress.
* **Settings:** generated forms from each application's schema; the file edited in place with
  comments kept; runtime-changeable keys through the application without a restart; restart
  offered for the rest.
* **Docs viewer:** the suite's documentation tree rendered — navigation, ADR index, full-text
  search, mermaid diagrams, link rewriting; read-only.
* **Chat:** to LoadCoach (a task profile, a job, a routing decision with cost) and to
  PromptCadence (a trajectory, its plan, tool calls, egress decisions and approvals inline);
  streamed markdown with code blocks; thinking streams while thinking and then collapses;
  text and markdown attachments as context; conversations kept in WeightRoomGym's database.
* **Database viewer:** read of every application's database — tables, rows, a SQL console;
  curated maintenance operations first; raw writes behind the ADR-0124 guard.
* **Model catalog and downloads:** every model every application knows, `ollama pull` with
  progress, GGUF drop-in into a llama.cpp model directory, enable/disable per application
  ([ADR-0118](../../adr/0118-a-discovered-model-can-be-disabled.md)), the evidence summary,
  delete with cleanup.
* **Cost and budget dashboard:** LoadLedger balances from PromptCadence and IdeaPress against
  their ceilings; ceilings editable through the settings path.
* **Backups and migrations:** every application's `db backup`, `db status`, `db upgrade`, the
  backup listing, restore as a curated operation.
* **Scheduled jobs:** WeightRoomGym's own database-backed queue with leases; kinds: FreeWeight
  suite run, retention trim, backup, model refresh.
* **Prompt library editor:** every application's shipped prompt pack and its user overrides,
  diffed, edited as [ADR-0012](../../adr/0012-prompt-storage-format.md) records.
* **Alerts:** application down, memory cap fired, GPU thermal, budget ceiling, breaker open;
  a banner with acknowledge and history; **no outbound channel**.

## 3. Explicit non-goals

* **Not a fifth peer application.** It measures nothing, routes nothing, drafts nothing and
  plans nothing; every one of those is shown from the application that owns it.
* **Never a provider client for chat.** Chat reaches a model only through LoadCoach or
  PromptCadence ([ADR-0123](../../adr/0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md)
  rule 4). ModelRack is imported for residency and discovery reads only.
* **No tool execution, no compaction, no egress decisions of its own.** `toolyard`, `cutctx`,
  `commissioner` are forbidden imports.
* **Never imports an application.** Databases, configuration files, CLIs and HTTP APIs only.
* **No multiple users, roles or API tokens** in 1.0 ([ADR-0126](../../adr/0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md)
  rule 7). One operator account.
* **No internet exposure.** The LAN, a private CA, one password.
* **No editing of the documentation in the browser.** The docs viewer is read-only; the
  documentation is edited in its repository.
* **Does not replace any application's own UI.** Each stays, loopback-only.
* **No outbound alert channel** — no mail, no webhook, no push. A banner, an acknowledge, a history.
* **Not root.** It never runs `sudo`; every privileged host change is printed as a command.
* **No second machine.** One host, this host.

## 4. Responsibilities

| Area | Responsibility |
|---|---|
| Shell | Top bar, tabs with status dots, telemetry strip, left menus, theme, the console's own navigation |
| Setup and doctor | The wizard; the cross-application check against the host-protection and exposure rubrics; printed commands for anything root-owned |
| Processes | Unit files written and synced; start/stop/restart/enable; Ollama status and the polkit-gated restart ([ADR-0125](../../adr/0125-weightroom-drives-the-applications-through-systemd-user-units-it-writes.md)); a read-only `llama.cpp` page — discovered servers, the configured GGUF directories and `MEMORY_SAFETY.md` §2.2's expectations — which starts and stops nothing, because a `llama-server` belongs to the application that launched it ([ADR-0062](../../adr/0062-llamacpp-serves-adapters-through-a-supervised-process.md)) |
| Logs and audit | Journal streaming and history per application; WeightRoomGym's `audit_log` of every action it took |
| Telemetry | The strip, the per-figure history pages, resident models |
| Control surfaces | One native page set per application over that application's API, CLI and (read) database (§7.3) |
| Settings | Schema-driven forms; in-place file edits; runtime keys through the application; restart offers; security-key re-authentication ([ADR-0127](../../adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)) |
| Docs | Rendering, tree, ADR index, search index, mermaid, link rewriting |
| Chat | Conversations, streaming, thinking collapse, attachments, routing/cost display, PromptCadence approvals inline |
| Database viewer | Read-only browsing and SQL; curated operations; the ADR-0124 guard |
| Catalog | Models across applications; pull, drop-in, enable/disable, evidence summary, delete with cleanup |
| Costs | Balances and ceilings across the ledger-mounting applications |
| Backups | Every application's backup/status/upgrade/restore as curated operations; the listing |
| Jobs | The database-backed queue with leases; four job kinds; history |
| Prompts | Pack listing, override editing, diff, validation against the record schema |
| Alerts | Sources, evaluation, banner, acknowledge, history |
| TLS and login | The CA, the leaf, renewal and rotation; the account, sessions, rate limit ([ADR-0126](../../adr/0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md)) |

## 5. Dependencies

**Suite:** `baseaicore`, `setspec`, `weightsdb`, `mirrorwall` (0.3 from row WM; the range
admits 0.2.2 until then), `sweatmeter`, `modelrack` (read-only provider calls),
`loadledger[sql]` (the mounted ledger tables' shapes). **Forbidden:** `toolyard`, `cutctx`,
`commissioner`, and the four applications — asserted by `.importlinter`.
**Third party** (the enumerated set, [Gold Standards §1.1](../../standards/gold-standards.md)):
`fastapi`, `uvicorn[standard]`, `typer`, `pydantic`, `sqlalchemy`, `alembic`, `jinja2`, `httpx`,
`python-multipart` (attachments, GGUF drop-in), `tomlkit` (in-place config edits),
`cryptography` (the CA), `mistune` (markdown for the docs viewer and chat). Twelve names.
**Host:** Linux with systemd (`systemctl`, `journalctl`, `loginctl`) for process pages and units;
`ollama` on `PATH` for pulls; `sqlite3`/`pg_dump` through `weightsdb`. Without systemd the
process pages degrade by name and everything else works.
**Vendored assets:** MirrorWall's, including **htmx** and its SSE extension from 0.3
([ADR-0128](../../adr/0128-mirrorwall-vendors-htmx-and-applications-may-adopt-it.md)) for every
fragment swap and SSE-driven region; ECharts through MirrorWall's chart container; **mermaid**
(≈ 2.5 MB, offline, loaded only on a docs page that contains a diagram — the one exception to
the per-page JS budget, declared in §15).

**Required at startup:** none of the four applications. WeightRoomGym starts, serves the shell,
the docs, the doctor, the audit log and its own settings with every application stopped; each
application's pages show *stopped* with a start button.

## 6. Consumers

The operator, through a browser on the LAN and the `weightroom` CLI on the host. WeightRoomGym's
HTTP API exists for its own pages; it is not designed as a service other applications call, and
none does.

## 7. Public APIs

### 7.1 HTTP (`/api/v1`, session-authenticated; full detail in [API](api.md))

```text
GET  /health                     GET  /version                   GET  /system/status
GET  /system/telemetry/stream    GET  /system/telemetry/history  GET  /system/resident
GET  /apps                       GET  /apps/{app}                GET  /apps/{app}/health
POST /apps/{app}/start           POST /apps/{app}/stop           POST /apps/{app}/restart
GET  /apps/{app}/logs            GET  /apps/{app}/logs/stream    GET  /logs/stream
GET  /apps/{app}/settings        PUT  /apps/{app}/settings       GET  /apps/{app}/settings/schema
POST /apps/{app}/settings/validate                               GET  /apps/{app}/config
GET  /apps/{app}/db/tables       GET  /apps/{app}/db/tables/{t}  POST /apps/{app}/db/query
POST /apps/{app}/db/write/dry-run   POST /apps/{app}/db/write     GET  /apps/{app}/db/revision
POST /apps/{app}/db/backup       GET  /apps/{app}/db/backups     POST /apps/{app}/db/upgrade
POST /apps/{app}/db/restore      GET  /apps/{app}/db/status
GET  /apps/{app}/prompts         GET  /apps/{app}/prompts/{id}   PUT  /apps/{app}/prompts/{id}
DELETE /apps/{app}/prompts/{id}/override
GET  /ollama                     POST /ollama/restart            GET  /ollama/ps
GET  /catalog                    POST /catalog/pull              GET  /catalog/pull/{id}/stream
POST /catalog/dropin             POST /catalog/{ref}/enabled     DELETE /catalog/{ref}
GET  /costs                      GET  /costs/{app}
GET  /chat/conversations         POST /chat/conversations        GET  /chat/conversations/{id}
DELETE /chat/conversations/{id}  POST /chat/conversations/{id}/messages
GET  /chat/conversations/{id}/stream                             POST /chat/conversations/{id}/attachments
POST /chat/conversations/{id}/approvals/{approval_id}
GET  /jobs                       POST /jobs                      GET  /jobs/{id}
POST /jobs/{id}/cancel           GET  /jobs/schedules            PUT  /jobs/schedules/{id}
GET  /alerts                     POST /alerts/{id}/acknowledge   GET  /alerts/history
GET  /audit                      GET  /audit/{id}
GET  /doctor                     POST /doctor/run
GET  /docs/tree                  GET  /docs/page                 GET  /docs/search
GET  /docs/adrs
GET  /trust                      GET  /trust/root.crt
POST /login                      POST /logout                    POST /reauth
GET  /settings                   PUT  /settings
```

`GET /version` is the one route that answers without a session ([ADR-0026 §5](../../adr/0026-local-http-hardening.md)).
`GET /trust/root.crt` and the trust instructions page are additionally served, unauthenticated,
by the plain-HTTP trust listener on `server.trust_port` — and nothing else is ([ADR-0126](../../adr/0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md)
rule 3). Every state-changing route passes the CSRF and same-origin checks of ADR-0126 rule 5.
`{app}` is one of `freeweight`, `loadcoach`, `ideapress`, `promptcadence`.

### 7.2 CLI

```text
wr-gym serve | health | doctor | version
wr-gym setup                                   # the wizard: CA, account, units, tokens, linger
wr-gym config show|validate|init|path|reference|schema
wr-gym db upgrade|status|backup|restore|restore-self
wr-gym tls init|renew|rotate|show              wr-gym trust
wr-gym operator create|password
wr-gym units sync|status|start|stop|restart <app>|all
wr-gym logs <app> [--follow] [--since …]
wr-gym apps status                             # all four + Ollama, one table
wr-gym backup <app>|all                        # curated: the app's own `db backup`
wr-gym jobs list|show|run|cancel|schedule
wr-gym alerts list|ack
wr-gym audit list|show
wr-gym docs index                              # rebuild the search index
wr-gym settings list|get|set                   # WeightRoomGym's own runtime-changeable keys
```

`wr-gym config schema --json` exists here too: WeightRoomGym's own settings page is generated
the same way as the applications' ([ADR-0127](../../adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)).

### 7.3 The control surfaces, per application

Each application's tab opens a left menu whose pages are WeightRoomGym's own templates over that
application's `/api/v1`, its CLI and — where the API has no view — a read of its database.
Every page names its source (*from the API*, *from the database at revision 0015*) in the
footer, and a stopped application's pages render from the database with the API-only actions
disabled and a *start* button.

| Application | Menu | Source per page |
|---|---|---|
| **FreeWeight** | Overview · Models · Runs · Results · **Dashboard** · Evidence · Goals · Adapters · **System** · Settings · Provider · Tokens · Logs · Database | API for runs, results, evidence, goals, provider; database for the models/runs listing when stopped; CLI for `token`, `db delete --model`, `run start`; *Dashboard* (summary cards, the model × suite comparison heatmap with FreeWeight's own *separated* marking) and *System* (version, health, ten components) from the API only — judged needed at row WP6, built at row WPF5 |
| **LoadCoach** | Overview · Models · Routing · Queue · Evidence · Adapters · Reliability · **System** · Settings · Providers · Tokens · Logs · Database | API for everything it serves (`/route` explain, jobs, queue pause/resume/drain, providers, `models/{ref}/enabled`, settings); database for decisions history when stopped; CLI for `token`; *System* (version, machine fingerprint, health components; dispatch, residency and breakers link to Queue and Reliability rather than repeating them) from the API only — judged needed at row WP6, built at row WPF5. Three of its menu entries open a **page nav** rather than one page (row WX9): Routing is *Explain* / *History* (`/routing`, `/routing/decisions`), Queue is *Current* / *New job* / *History* (`/queue`, `/queue/new`, `/queue/history` — only the first streams), Evidence is *Records* / *Store and import* (`/evidence`, `/evidence/admin`). The nav is on the page, in its header actions; the left menu keeps one entry per tab and the sub-page's `selected` keeps it highlighted |
| **IdeaPress** | Overview · Projects · Units · Workflows · Backends · Settings · Logs · Database | API for projects, units, stage runs, backends; database for the listing when stopped |
| **PromptCadence** | Overview · Trajectories · Approvals · Tiers · Tools · Ledger · Egress · System · Settings · Tokens · Logs · Database | API for everything; approvals grant/deny with the `approve`-scoped token ([ADR-0049](../../adr/0049-approval-is-a-mode-with-its-own-scope.md)); database for the listing when stopped; *System* (health, active work, the last recovery pass) from the API only — added by the operator on 2026-09-10, built at row WPC1 |

**Judged at WP6 and not added.** FreeWeight's **Sources** (a read-only credit list of nine external
benchmark adapters, none installed; nothing on it is actionable from any interface — revisit when
one can be installed) and IdeaPress's **System** (three health components, already covered by the
Overview and the doctor). Neither gains a menu entry; see `history/handoffs/WP6_HANDOFF.md` §3 and
`history/handoffs/WPF5_HANDOFF.md`.

The Overview page of each application is the design brief's artboard: status and uptime,
four figures, the primary table, the live log tail. Every action on these pages is an
`audit_log` row.

### 7.4 Settings

Per application, generated from `<app> config schema --json` ([ADR-0127](../../adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)):
one section per top-level table of the model, each field with its type, bounds, default,
description, current value and source layer (*file*, *env* — shown as *shadowed* when a file
value cannot take effect — *database*, *default*). Runtime-changeable keys save through the
application's `PUT /api/v1/settings` and are marked *live*; every other key saves to the file
through `tomlkit`, is validated by `<app> config validate --file` before the rename, and
leaves the page in *pending restart* until the application restarts. Keys in `security_keys`
prompt for the operator's password (a five-minute re-authentication window) and say *security
key* on their audit row. A raw TOML editor for the whole file is one click from the form, on
`/apps/{app}/settings/raw`, under the same validate-before-write and the same re-authentication
for security keys — its own page rather than a section of the form because it shows the file
verbatim, secrets included, and this console is reachable from the LAN by design (row W4).

**Provider profiles are a card each.** Where an application's document states
`provider_profiles` ([ADR-0144](../../adr/0144-freeweight-keeps-several-provider-profiles-and-runs-one.md)
rule 7 — FreeWeight, today), the keys of each profile are lifted out of their sections into one
card per profile, with an **Active** radio in its heading. The radio posts the key the document
names, so switching profile is an ordinary field on the same save — a security key, needing the
password, and taking effect at the restart the page then offers. A card shows every key the
application's schema gives a profile, not only the ones the file names, so a profile added here is
complete without an excursion to the raw editor. *Add a provider profile* writes one key, the
`kind`, chosen from the kinds the application says it can construct; it switches nothing.

### 7.5 Docs viewer

Renders `WeightRoom/docs/` — the suite's canonical tree — from a configured root
(`[docs] root`, default: the `docs/` beside the installed package's repository if present, else
the operator's path). Tree navigation, an ADR index built from `adr/README.md`'s table, a
full-text search over an FTS5 index in WeightRoomGym's own database (rebuilt by `wr-gym docs
index` and on a schedule), mermaid fences rendered client-side, relative links rewritten to
viewer routes and links outside the root rendered as text. Read-only: no route writes a document.

### 7.6 Chat

A conversation names its **backend** — LoadCoach (with a task profile and an optional model
override, exactly the `POST /generate/stream` body) or PromptCadence (a trajectory, with the
classification, an optional tier pin and the tool allowlist) — and its messages, attachments and
every reply's metadata live in WeightRoomGym's database. Replies stream as markdown with code
blocks and a copy button; under each reply, the routing decision (model, candidates count,
rejections) and the cost (tokens by class; money where priced, `—` where local). For
PromptCadence, the plan, each step, each tool call with its result, and each egress decision
render inline as they arrive, and a pending approval renders as approve/deny buttons that call
`POST /trajectories/{id}/approve|deny` with the `approve` token. **Thinking streams while the
model thinks** (a `thinking`-class chunk from LoadCoach's stream) in its own block, then
collapses to one line when the answer starts; collapsed thinking, decisions and plans expand on
click. Attachments are text or markdown, size-capped (`[chat] max_attachment_bytes`), and are
prepended as context in the request — never executed, never fetched from.

### 7.7 Telemetry

`sweatmeter` in process, sampled at `[telemetry] interval_ms` (1000), streamed on
`/system/telemetry/stream`; the strip shows GPU utilisation, VRAM, temperature, power, RAM, the
resident model with its context, and LoadCoach's queue depth. An unavailable reading is `—`,
never `0` ([ADR-0016](../../adr/0016-unavailable-is-not-zero.md)). Samples are kept in
`telemetry_samples` for `[telemetry] history_hours` (72) at one row per interval, downsampled to
one per minute beyond an hour; clicking a figure opens its history page with a chart over that
window. Resident models are `/api/ps` (through ModelRack's Ollama client) and LoadCoach's
`/models` residency, shown together with their source.

### 7.8 Database viewer

Per application: the table list with row counts and the application's `alembic_version`
against WeightRoomGym's known-revision map ([ADR-0123](../../adr/0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md)
rule 3); a paginated, sortable, filterable row grid per table; a SQL console that runs
`SELECT`s on a read-only connection with a 30 s timeout and a 10 000-row cap. **Curated
operations** are listed first on every table that has one — retention settings, backup, vacuum,
upgrade, restore, and FreeWeight's own deletion of stored results over its API (previewed, the
selector typed, re-authenticated; [ADR-0134](../../adr/0134-event-logs-go-with-their-deleted-parent-freeweight-deletes-its-own-results-and-guarded-write-backups-expire.md)
rule 2) — and call the owning application. **Raw writes** (a statement, a row edit, a row delete) open the
guard: the unit's state and the port are checked, the dry run's count, the statement and what the
database's foreign keys reach are shown, the table names are typed, a backup is taken, the audit
row is written, the statement runs, the audit row is completed ([ADR-0124](../../adr/0124-a-raw-write-into-another-applications-database-passes-a-five-part-guard.md),
in [ADR-0133](../../adr/0133-the-guard-follows-foreign-keys-observes-stopped-twice-and-binds-a-write-to-its-dry-run.md)'s
order). Never-writable tables, named or reached by a cascade, show the lock and the reason — except
an event log whose rows a cascaded delete removes with their parent (ADR-0134 rule 1). A guarded
write's backup is kept 90 days by default, then removed (ADR-0134 rule 3, from row W8).
SQLite and PostgreSQL both, from the application's own effective `storage.database_url`
(`sqlite:///`, `postgresql+psycopg://`), printed by its own `config show --json` (ADR-0133 rule 4)
— never typed twice.

### 7.9 Catalog, costs, backups

**Catalog:** every model each application knows, joined by canonical identity where identical
(`provider/name@sha256:…`), with per-application `enabled`, evidence freshness from FreeWeight,
residency, size and context. Actions: `ollama pull <name>` as a job with streamed progress;
GGUF drop-in (a file upload or a path on the host copied into the configured llama.cpp
`model_directory`, then that application's `models refresh`); enable/disable per application
(`POST /models/{ref}/enabled` on each); delete with cleanup — `ollama rm` or the file, then
FreeWeight's own deletion of the model's results (`scope=model` through its API, ADR-0134 rule 2 —
no application has a `db delete --model` verb), previewed and confirmed per
[Database Standards §8](../../standards/database-standards.md).

**Costs:** LoadLedger balances read from PromptCadence's and IdeaPress's mounted tables
(`ledger_balances`, `ledger_balance_money`) through `loadledger.sql`'s classes, today and this
window, against the ceilings in each application's configuration; every money figure carries
its unpriced count ([ADR-0069](../../adr/0069-a-partial-price-is-a-floor-and-a-money-ceiling-chooses-how-it-binds.md));
a ceiling is edited on the application's settings page (config-only there, re-authenticated
here per [ADR-0127](../../adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)
rule 6, and never through a `ceiling_raise` approval, which stays PromptCadence's).

**Backups and migrations:** per application, `db status` (current and head revision), `db
backup` into that application's own `backups/` (a curated call to its CLI; the listing reads
that directory), `db upgrade` with the pre-migration backup the application takes itself,
`db restore <file>` as a curated operation that requires the application stopped and confirms
by typed name. WeightRoomGym's own database gets the same four verbs.

### 7.10 Jobs, alerts, prompts

**Jobs:** a `jobs` table with `state`, `lease_expires_at`, `attempt`, worked by one thread in
the server process ([ADR-0010](../../adr/0010-queue-implementation.md), [ADR-0029](../../adr/0029-queue-mechanics.md)
shape: lease, heartbeat, recovery pass at startup, ageing not needed for four kinds). The claim is
a compare-and-set on `state = 'queued'`; the lease is renewed every `lease_seconds / 3` by a lease
keeper thread of its own, never by the worker; recovery runs at startup and on every worker tick,
requeuing an idempotent kind whose lease expired and failing any other as `worker_lost` (row W9).
Kinds in 1.0: `freeweight_suite_run` (`freeweight run start --model … --suite … [--adapter …] --json`, which
executes the run and exits with its outcome, launched inside `systemd-run --user --scope` under
`[host] memory_high`/`memory_max` — ADR-0119's wrapper for a run started outside FreeWeight's unit,
refused rather than run uncapped without `systemd-run` — and followed with `freeweight run wait`
when another process holds FreeWeight's execution slot; `--adapter` is one more argument to the
same command, never a second path — row WPF2), `freeweight_goal_calibrate`
(`freeweight goals calibrate <slug> --progress --json` — a goal's jury grading its held-out samples,
model loads under the same scope, prefix and cap; FreeWeight's API calibration is synchronous and
unstreamed, so the job's output is how the Goals page follows it live, row WP4), `retention_trim` (WeightRoomGym's own
retention — finished jobs after 90 days, guarded-write backups after `guarded_backup_days`,
ADR-0134 rule 3 — and FreeWeight's own deletion of results older than
`freeweight_older_than_days` when that is set; LoadCoach and PromptCadence retain inside their own
processes and IdeaPress keeps everything), `backup` (§7.9 per application), `model_refresh` (each
application's `models refresh`, then the catalog join), plus `catalog_pull` and `docs_index`, and
`self_restore` — WeightRoomGym's own database restored by a job handed to a transient unit that
stops the console, restores, carries the job forward and starts it again
([ADR-0136](../../adr/0136-weightroom-restores-its-own-database-through-a-job-handed-to-a-transient-unit.md)).
A schedule is a row (a five-field `cron` expression evaluated in UTC, next run, last run,
enabled); a slot missed while the console was down runs once, never once per missed slot. A job's
output is its `audit_log` row plus a captured, capped stdout/stderr.

**Alerts:** evaluated on a thread of their own — not the job worker's, which spends hours inside
one run — every `[alerts] interval_seconds` (30): an application unit `failed` or restarting
itself, or running for a minute with its `/health` not `200` (an `inactive` unit is a stop the
operator chose, not an outage); the system and user journal since the last check matching the
ADR-0119 kill (`oom-kill`, the OOM killer, `MemoryMax`, `systemd-oomd`) on `ollama.service` or an
application unit; GPU temperature above `[alerts] gpu_temperature_c` (85); a LoadLedger balance at
or over a ceiling; a LoadCoach breaker open (`/reliability`). Each source produces at most one
active alert per subject. A condition clears itself when a reading finds it over; a memory-cap
kill stays until acknowledged; a source that could not be read clears nothing
([ADR-0137](../../adr/0137-an-alert-is-an-episode-a-condition-clears-itself-an-event-waits-for-acknowledgement.md)).
The banner, on every page and polled every five seconds, shows the newest unacknowledged alert
(`memory cap fired · ollama.service` with its journal line) and how many more; acknowledge records
the operator and time; history keeps every alert's events. No outbound channel.

**Prompts:** the shipped pack of each application that has one — FreeWeight, and IdeaPress, which
loads overrides and marks its attempts `prompt_source: user_override` since row W9 — read through
its own `prompts list|show` (`--shipped` on IdeaPress, whose plain listing is what a stage renders;
FreeWeight's `show --json` carries the whole record under `record`), and its overrides at
`$XDG_CONFIG_HOME/<app>/prompts/<prompt_id>.json`
([Prompt Standards §6](../../standards/prompt-management-standards.md)). LoadCoach and
PromptCadence ship prompt records but no `prompts` command and read no override directory, so their
prompts are not editable here, and the console says so by name. The editor validates a candidate
with `setspec.prompts.load_record` — the loader the application itself runs — before it writes one,
diffs it against the shipped record, and shows which prompts are overridden and any override on
disk that would not load. Deleting an override restores the shipped prompt. Each application's rule
is shown beside the editor, not bypassed: FreeWeight's benchmark refuses an overridden prompt
without `--allow-prompt-override`; IdeaPress reads its pack once and needs a restart for an
override to take effect.

## 8. Inputs

The operator's actions; each application's API responses, CLI output, database and
configuration file; the systemd journal; `sweatmeter` samples; Ollama's `/api/ps` and `/api/tags`;
the documentation tree; chat attachments (text, markdown); GGUF files.

## 9. Outputs

Rendered pages and SSE streams; unit files under `~/.config/systemd/user/`; configuration files
written in place (with `.bak`); backups under WeightRoomGym's data root (guarded writes) or the
application's (curated); prompt override files; WeightRoomGym's own database (§10); the CA and leaf
certificates; printed commands for anything root-owned; structured logs.

## 10. Data ownership

WeightRoomGym owns `weightroom.sqlite3` (or a PostgreSQL database) and nothing in any other
application's database ([data model](data-model.md)): `operators`, `sessions`, `audit_log`,
`conversations`, `messages`, `attachments`, `jobs`, `job_schedules`, `alerts`,
`telemetry_samples`, `docs_index` (FTS5), `settings`, `known_revisions` (seeded, per
application). It **reads** the four applications' databases through their own connection
strings on read-only connections, and writes to them only under the ADR-0124 guard, which it
records in its own `audit_log`. It never mounts a package table of its own.

## 11. Public contracts

1. **The exception is the list.** WeightRoomGym's reach into another application is exactly
   [ADR-0123](../../adr/0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md)
   rule 2, and `.importlinter` asserts the two things it may not do (import an application; import
   `toolyard`, `cutctx`, `commissioner`).
   A page under one application's tab may show another application's measurement where only that
   application produces it — LoadCoach's Models page carries FreeWeight's *Context fit* from
   `GET /api/v1/results/context-fit` (row WX9). It stays a console read over HTTP: neither
   application learns of the other, nothing is written back, and the column carries the runtime
   profile and machine the number was measured under, because one number per model would be a lie.
   An unreachable second application costs that page its column and a note, never its rows.
2. **Every action is an audit row.** Process control, settings writes, guarded database writes,
   curated operations, catalog changes, prompt overrides, job runs, alert acknowledgements,
   login and logout, TLS rotation. The row names the operator, the time, the target, the
   parameters (secrets redacted) and the outcome; `GET /audit` is the trail. A test enumerates
   the state-changing routes and asserts each writes one. **A refusal is an outcome, not an
   absence**: a write WeightRoomGym refused, or the application did, leaves that same one row with
   `outcome = "refused"`, and the test exercises that half beside the success. **A call
   WeightRoomGym stopped waiting for is `pending`, never `refused`** — a timeout is what the
   console did, not what the application said, and whether the work landed is exactly what is not
   known (row WPF1, from WP6 findings 2 and 3).
3. **A raw write passes the five-part guard or does not happen**, and the never-writable
   tables are refused by name ([ADR-0124](../../adr/0124-a-raw-write-into-another-applications-database-passes-a-five-part-guard.md)).
4. **A schema WeightRoomGym does not know degrades by name.** Each application's
   `alembic_version` is compared against `known_revisions`; a mismatch renders that
   application's database-sourced pages as *schema at revision X is not known to WeightRoomGym
   1.y* with the API-sourced pages unaffected.
5. **Settings forms come from the application's schema document**, and WeightRoomGym hardcodes no
   key ([ADR-0127](../../adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)).
   A key absent from the document renders raw.
6. **Chat has no provider path.** A conversation's backend is `loadcoach` or `promptcadence`;
   there is no third value, and `modelrack.generate` is never called (a grep test).
7. **The console is the only LAN service**, HTTPS only on 8769, and the trust listener serves
   two routes ([ADR-0126](../../adr/0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md)).
8. **Unit files are generated whole** from one template and WeightRoomGym's configuration
   ([ADR-0125](../../adr/0125-weightroom-drives-the-applications-through-systemd-user-units-it-writes.md));
   `units sync` is idempotent and reports which files changed.
9. **Unavailable is `—`.** No telemetry, cost or count is rendered as zero when it is
   unavailable ([ADR-0016](../../adr/0016-unavailable-is-not-zero.md)).

## 12. Configuration

`~/.config/wr-gym/config.toml`, `WEIGHTROOM_*` environment variables, CLI flags, per
[Configuration Standards](../../standards/configuration-standards.md). Principal sections:

```toml
[server]      host = "127.0.0.1"  port = 8769  allow_lan_exposure = false
              allowed_hosts = []             # required off loopback (ADR-0026); the wizard fills it
              trust_port = 8770              # plain HTTP: /root.crt and the trust page only
              rate_limit_per_minute = 600  rate_limit_burst = 100  failed_login_per_minute = 5
              max_body_bytes = 67108864      # 64 MiB — GGUF drop-in by upload; else 1 MiB
[tls]         directory = ""                 # "" = <config>/tls; ca.key, ca.crt, server.key, server.crt
              leaf_days = 398  ca_years = 10  renew_before_days = 30
[auth]        session_idle_hours = 12  session_max_days = 7  reauth_window_minutes = 5
[storage]     database_url = "sqlite:///<data>/weightroom.sqlite3"  auto_migrate = true
              backup_retention = 5
[apps.freeweight]     executable = ""        # "" = shutil.which("freeweight")
                      base_url = "http://127.0.0.1:8765"  api_key_file = ""
[apps.loadcoach]      executable = ""  base_url = "http://127.0.0.1:8766"  api_key_file = ""
[apps.ideapress]      executable = ""  base_url = "http://127.0.0.1:8767"
[apps.promptcadence]  executable = ""  base_url = "http://127.0.0.1:8768"  api_key_file = ""
[host]        memory_high = "22G"  memory_max = "24G"   # the unit-level cap (ADR-0119, ADR-0125)
              ollama_unit = "ollama.service"  ollama_base_url = "http://127.0.0.1:11434"
              llamacpp_model_directory = ""  # GGUF drop-in target; "" = read from the apps' configs
[telemetry]   interval_ms = 1000  history_hours = 72
[chat]        max_attachment_bytes = 262144  default_task_profile = "general.chat"
              default_classification = "confidential"   # PromptCadence's safe default
[docs]        root = ""                      # "" = the docs/ beside this checkout, else refuse
[jobs]        lease_seconds = 60  poll_interval_ms = 1000  output_cap_bytes = 1048576
[alerts]      interval_seconds = 30  gpu_temperature_c = 85
[logging]     level = "INFO"  include_content = false
```

**Runtime-changeable** ([ADR-0100](../../adr/0100-promptcadences-runtime-changeable-set-is-five-tuning-numbers.md)'s
test — re-read by the running process, no security surface): `telemetry.interval_ms`,
`telemetry.history_hours`, `alerts.interval_seconds`, `alerts.gpu_temperature_c`,
`jobs.poll_interval_ms`, `chat.default_task_profile`. Precedence follows Configuration
Standards §7 (a stored row is shadowed by the environment and says so). Everything in
`[server]`, `[tls]`, `[auth]`, `[storage]`, `[apps.*]`, `[host]`, `[docs]` and
`logging.include_content` is config-only, and the `[server]`/`[tls]`/`[auth]`/`[apps.*]`/`[host]`
keys are WeightRoomGym's own `security_keys` — editable on its own settings page only after
re-authentication, exactly as it treats the four applications'.

The generated `docs/configuration.md` in the repository is the field-level authority
([Configuration Standards §8](../../standards/configuration-standards.md)).

## 13. Error behaviour

```text
UNAUTHORIZED            FORBIDDEN               CSRF_FAILED             RATE_LIMITED
INSECURE_BINDING        TLS_MISSING             REAUTH_REQUIRED
APP_UNKNOWN             APP_NOT_INSTALLED       APP_STOPPED             APP_UNREACHABLE
APP_VERSION_MISMATCH    SCHEMA_UNKNOWN          UNIT_UNSUPPORTED        UNIT_ACTION_FAILED
OLLAMA_RESTART_NOT_PERMITTED                    GUARD_APP_RUNNING       GUARD_BACKUP_FAILED
GUARD_DRY_RUN_FAILED    GUARD_TABLE_MISMATCH    GUARD_TABLE_LOCKED      GUARD_STATEMENT_REFUSED
GUARD_AUDIT_FAILED
CONFIG_VALIDATION_FAILED  CONFIG_CHANGED_ON_DISK  SETTING_CONFIG_ONLY   SETTING_UNKNOWN
CHAT_BACKEND_UNAVAILABLE  ATTACHMENT_TOO_LARGE  ATTACHMENT_TYPE_REFUSED
CATALOG_PULL_FAILED     CATALOG_DROPIN_REFUSED  JOB_NOT_FOUND           JOB_INVALID_STATE
DOCS_ROOT_MISSING       DOCS_PAGE_OUTSIDE_ROOT  VALIDATION_ERROR        PAYLOAD_TOO_LARGE
```

Each is a stable code in MirrorWall's error envelope with `details` naming the application,
unit, table or key concerned. `GUARD_*` codes carry the guard condition that failed by number
(ADR-0124's 1–5; `GUARD_AUDIT_FAILED` is condition 5); `GUARD_TABLE_LOCKED` and
`GUARD_STATEMENT_REFUSED` carry `condition: null`, since no changed fact satisfies them
([ADR-0133](../../adr/0133-the-guard-follows-foreign-keys-observes-stopped-twice-and-binds-a-write-to-its-dry-run.md)
rule 6). `SCHEMA_UNKNOWN` names the revision found and the revisions known. Exit
codes follow [CLI Standards §4](../../standards/cli-standards.md); `INSECURE_BINDING` and
`TLS_MISSING` are exit 3 at startup.

## 14. Security considerations

* **The only LAN service**, HTTPS only, own CA, session login, rate-limited, idle and absolute
  session expiry, CSRF on every form, same-origin on every JSON write, `Host` allowlist before
  everything ([ADR-0126](../../adr/0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md),
  [ADR-0026](../../adr/0026-local-http-hardening.md)). The trust listener serves two routes and
  refuses every other path with 404 and no cookie.
* **A session is the operator.** Every action it can take, the operator could take at a shell;
  the console adds an audit row to each. Security keys and guarded writes additionally
  re-authenticate.
* **Subprocesses are explicit argv, never a shell**; the environment is an allowlist; output is
  capped; the executables are resolved once and recorded. `sudo` is never invoked.
* **SQL from the console runs read-only** except through the guard, with a timeout and a row
  cap; DDL is refused by name; the connection string is the application's own.
* **Model output is data.** Chat renders through the sanitising markdown pipeline (no raw HTML,
  no `| safe`); thinking, plans and tool results are rendered escaped; nothing in a reply is
  executed, fetched or used to build a path.
* **Attachments** are size-capped, type-restricted to text and markdown, stored under the data
  root with a generated name, and never interpreted.
* **GGUF drop-in** validates the file's magic bytes and size, containment-checks the target
  directory, and refuses a path outside the configured model directory.
* **Secrets by reference.** Application tokens live as files under `<config>/secrets/` (`0600`);
  the configuration names the file. Logs redact tokens, passwords and connection-string
  credentials; a test asserts it.
* **Docs viewer** serves only paths under `[docs] root` after resolution; a symlink out of the
  root is refused.
* **Prompt overrides** are validated records written under the application's own config root;
  the editor cannot write anywhere else.
* Security Standards §14 item by item in `tests/security/`, plus this component's rows: session
  fixation (a new session id on login), expiry, logout, `Sec-Fetch-Site`, the trust listener's
  route refusal, the guard's five conditions each failed in isolation, the never-writable list.

## 15. Performance considerations

Four applications' worth of pages over HTTP calls and database reads; WeightRoomGym's own
overhead is what is budgeted:

| Measure | Target |
|---|---|
| Shell render (top bar, strip, menu) on a warm process | ≤ 50 ms |
| Application Overview page, application running | ≤ 300 ms |
| Telemetry sample to SSE frame | ≤ 20 ms; 1 s cadence held within ±100 ms |
| Journal line to SSE frame | ≤ 50 ms |
| Database table page, 100 rows, SQLite | ≤ 150 ms |
| SQL console statement cap | 30 s timeout, 10 000 rows |
| Guarded write, end to end (excluding the backup copy) | ≤ 2 s |
| Docs page render, 40 KB markdown | ≤ 100 ms; search over the whole tree ≤ 200 ms |
| Chat first token after LoadCoach's first chunk | ≤ 30 ms added latency |
| JS per page | ≤ 120 KB in total, excluding ECharts and mermaid, which load only on pages that use them ([ADR-0139](../../adr/0139-the-per-page-javascript-budget-is-a-total-of-120-kb.md)) |

`sweatmeter`'s sampling overhead stays under its own 1 % budget; WeightRoomGym adds no second
sampler.

## 16. Cross-platform considerations

**Linux with systemd is the supported host for 1.0.** Process control, units, the journal and
Ollama's unit status are `systemctl`/`journalctl` calls; without them the process pages and the
Ollama pane report *unsupported on this host* by name and every other feature works
([ADR-0125](../../adr/0125-weightroom-drives-the-applications-through-systemd-user-units-it-writes.md)
rule 7). Telemetry degrades per `sweatmeter`'s own matrix. Paths follow the shared XDG handling.

## 17. Observability

Structured logs with `request_id`, `operator`, `app`, `unit`, `action`, `audit_id`. `GET /health`
reports `database`, `tls` (days to expiry), `units` (systemd reachable), and one component per
application (`ok`/`degraded`/`stopped`/`unknown`). `GET /system/status` is the machine view: the
four applications' state and version, Ollama's unit and residency, the telemetry snapshot,
today's costs, open alerts, running jobs, the last doctor run. The audit log is the record of
what the console did; the alert history is the record of what the machine did.

## 18. Test strategy

| Layer | Coverage |
|---|---|
| Unit | The guard's state machine with every condition failed alone; the never-writable list; unit-file rendering; the schema-to-form generator over each application's golden document; the CA/leaf issuer (SANs, lifetimes, renewal decision); password hashing and session expiry; thinking-chunk collapse logic; alert evaluation per source; the known-revision comparison |
| Contract | Each application's API consumed through recorded responses at its pinned version; each application's schema document golden; `setspec.prompts` record validation; the OpenAPI snapshot of WeightRoomGym's own API |
| Integration | A fake `systemctl`/`journalctl` on `PATH`; four fixture databases at their known revisions (SQLite; PostgreSQL in the db-matrix job); tomlkit round-trips over each application's example config; the jobs queue with lease expiry and recovery; migrations both dialects |
| E2E | Setup → login → start an application → change a setting → guarded write → chat, over HTTPS against fake applications |
| Security | Standards §14 plus §14's own rows above; the trust listener; the same-origin checks; redaction |
| Accessibility | MirrorWall's checklist over every page; the dark and light contrast pairs |
| Performance | Every §15 budget |
| Live (marked) | The real host: real units, real journal, real Ollama `/api/ps`, one real LoadCoach chat, one polkit-gated restart attempt reporting its outcome honestly |

The full suite passes with no application installed, no systemd, no GPU and no network.

## 19. Compatibility and versioning

* Application semver; API `v1`. WeightRoomGym `1.x` names, per application, the range of
  versions it speaks to (`GET /api/v1/version` on first contact, re-checked every five minutes,
  [ADR-0013](../../adr/0013-api-versioning.md); the payload takes either of the two shapes the
  suite currently emits — [ADR-0129](../../adr/0129-weightroom-reads-both-version-payload-shapes.md))
  and the `alembic_version`s it reads
  (`known_revisions`). An application outside either range is *degraded by name*, never
  guessed at.
* The schema document is `schema_version 1.0`; a minor adds fields, a major is a new WeightRoomGym
  minor.
* Unit files carry a header comment naming the WeightRoomGym version that wrote them; `units sync`
  rewrites on version change.
* The CA is independent of every version; `tls rotate` is the only thing that changes it.

## 20. Acceptance criteria

1. `pip install wr-gym && wr-gym setup && wr-gym serve` on the reference machine
   yields an HTTPS console on the LAN with a trusted certificate on one client device, a login,
   and all four applications running as units — with no other component changed.
2. Every state-changing action in the console writes an `audit_log` row, proven by a test that
   enumerates the routes.
3. A raw write into an application's database fails on each of the five guard conditions in
   isolation and succeeds with all five, with the backup on disk and the audit row complete;
   every never-writable table is refused by name.
4. A settings change to a runtime-changeable key takes effect without a restart; a file-only
   key round-trips through `tomlkit` with every comment intact and is validated by the owning
   application before the rename; a security key requires re-authentication.
5. The forms contain no hardcoded key: adding a field to an application's `Settings` model and
   regenerating its schema document makes the field appear.
6. Chat streams from LoadCoach and from PromptCadence with thinking collapsing, the routing
   decision and cost under each reply, and a PromptCadence approval granted inline; no
   provider is contacted (asserted by import-linter and by a network-isolation test).
7. Stopping every application leaves the console serving, with each application's pages showing
   *stopped* and a working start button.
8. An unknown `alembic_version` in any application degrades that application's database pages
   by name and nothing else.
9. The trust listener serves `/root.crt` and the instructions page and nothing else; the console
   port serves no plain HTTP.
10. The full test suite passes with no application, no systemd, no GPU and no network.
11. All WeightRoomGym gold standards in [Gold Standards §2](../../standards/gold-standards.md) are met.

## 21. Future extensions

* A second operator with a role (viewer, approver) and per-person audit attribution.
* An API token for automation against WeightRoomGym itself.
* Outbound alerts (mail, webhook) — once there is a channel the operator trusts.
* A second host: WeightRoomGym reading remote applications over their APIs only.
* Editing documentation in the browser, with the repository as the store.
* An application read-only serving mode, which would widen the guard's condition 1.

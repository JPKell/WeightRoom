# ADR-0146 — The console has no catalog

**Status:** Accepted (2026-09-12)
**Relates to:** [spec.md §7.9](../apps/weightroom/spec.md) (whose *Catalog* paragraph this record
withdraws), [ADR-0118](0118-a-discovered-model-can-be-disabled.md) (the per-application
enable flag, which stays), [ADR-0134](0134-event-logs-go-with-their-deleted-parent-freeweight-deletes-its-own-results-and-guarded-write-backups-expire.md)
(FreeWeight deletes its own results through its API, which the catalog's delete called), row W8 (which built the catalog), row W9 (which made the pull a
job) and row WY1 of [`roadmap/wy-console-polish-work.md`](../roadmap/wy-console-polish-work.md).
**Source:** The operator's request of 2026-09-12
([`history/prompts/wy-operator-request-2026-09-12.md`](../history/prompts/wy-operator-request-2026-09-12.md)),
verbatim: *"remove the catalog page from the site, no links to it, delete the files"*.

## Context

Row W8 built `/catalog`: every model FreeWeight and LoadCoach know, joined by canonical identity,
with four actions — `ollama pull` (a `catalog_pull` job since W9, its progress streamed from an
in-memory `PullRegistry`), a GGUF drop-in into the llama.cpp model directory, enable and disable per
application, and delete with cleanup. It had a JSON API under `/api/v1/catalog`, a Tools entry in
the left menu and a link from each application's Models page.

By the WX arc the same work had better homes. The LoadCoach and FreeWeight Models pages enable and
disable a model in the application that owns the flag (rows WP2 and WP3), and Ollama's own tooling
pulls and removes models. The operator asked for the page to go.

## Decision

1. **What leaves.** The `/catalog` page and its four form routes; the whole `/api/v1/catalog` API
   (`GET /catalog`, `POST /catalog/pull`, `GET /catalog/pull/{id}/stream`, `POST /catalog/dropin`,
   `POST /catalog/{ref}/enabled`, `DELETE /catalog/{ref}`); the console's pull, drop-in and delete
   of a model; `PullRegistry`; the `catalog_pull` job kind as something that can be queued; the
   Tools menu entry and every link to `/catalog`. No `wr-gym catalog` CLI verb ever existed.
2. **What stays: enable and disable.** The switch on the LoadCoach and FreeWeight Models pages keeps
   calling `services/catalog.set_enabled`, which calls the application's own
   `POST /models/{ref}/enabled` (ADR-0118).
3. **What stays: the audit event names.** `catalog.pull`, `catalog.enabled`, `catalog.dropin` and
   `catalog.delete` stay in the closed audit vocabulary. Historical audit rows carry them, and the two
   tabs above still emit `catalog.enabled`. Renaming the event would split one fact across two
   names in the audit trail.
4. **What stays: the job-kind name, read-only.** `catalog_pull` is no longer in `JOB_KINDS`, so
   `POST /jobs` refuses it and the enqueue form does not offer it. A stored row of that kind still
   lists on `/jobs`, renders at `/jobs/{id}` and answers `GET /api/v1/jobs/{id}`; nothing that reads a
   job checks its kind. A `catalog_pull` row still queued when this build starts is failed by the
   worker with *"no executor for kind 'catalog_pull' in this build"*, never crashed on.
5. **What stays: the join.** `catalog_entries` still runs after `model_refresh` and reports how many
   models it joined in that job's output. Nothing else reads it. Removing that line is a separate
   decision, not part of this one.

## Consequences

* A model is pulled or removed with Ollama's own tools, and a GGUF is placed in the llama.cpp model
  directory by hand, followed by that application's `models refresh` (or the `model_refresh` job).
* The catalog's join has one caller left, a single line of job output. The next row that touches
  `model_refresh` can remove it without a new ADR if the operator agrees.
* `spec.md` §7.9 and `api.md` §5 carry a note pointing here; the OpenAPI snapshot no longer lists the
  six routes.

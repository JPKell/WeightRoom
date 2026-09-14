# Architecture Decision Records

Every significant architectural decision in the suite is recorded here. An ADR is written **before**
the decision is implemented, and it is not edited to hide a change of mind — it is superseded by a
new ADR that references it.

## Format

Every ADR contains, in this order:

```text
Status          Proposed | Accepted | Superseded by ADR-XXXX | Deprecated
Context         The forces, constraints and evidence
Decision        What we will do, stated unambiguously
Alternatives considered   What else was evaluated, and why it lost
Consequences    What this costs, what it enables, what it forecloses
Revisit when    The concrete trigger that would reopen the decision
```

A decision without a "revisit when" trigger is a decision nobody can safely revisit.

**"Alternatives considered" has an accepted variant.** Several records argue the losing options
under a heading that names them for what they are — `## Options` and `## Recommendation` in
[0039](0039-audit-gated-blocking-requirements.md), `## What this refuses` in
[0076](0076-a-step-retry-is-a-repeat-under-the-same-intent.md),
[0099](0099-a-task-profile-may-ask-for-reduced-thinking.md),
[0100](0100-promptcadences-runtime-changeable-set-is-five-tuning-numbers.md) and
[0104](0104-an-adopted-reductions-seam-and-error-vocabulary-survive-it.md), `## Why LoadLedger` in
[0110](0110-the-pricing-file-reader-is-a-loadledger-surface.md). The section is required; its title
is not. [ADR-0037](0037-production-evidence-never-raises-capability-scores.md) is the one record
with no such section at all, found by the 2026-09-07 consistency review and left standing, because
an ADR is superseded rather than edited.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-application-and-package-separation.md) | Application and package separation | Accepted |
| [0002](0002-web-framework.md) | Web framework: FastAPI | Accepted |
| [0003](0003-sync-vs-async-strategy.md) | Sync core, async edge | Accepted |
| [0004](0004-sse-vs-websockets.md) | Server-Sent Events for streaming | Accepted |
| [0005](0005-database-strategy.md) | SQLAlchemy 2.0 + Alembic | Accepted |
| [0006](0006-sqlite-and-postgresql-roles.md) | SQLite default, PostgreSQL supported | Accepted |
| [0007](0007-provider-abstraction.md) | Provider abstraction and Ollama first | Accepted |
| [0008](0008-canonical-model-identity.md) | Canonical model identity | Accepted |
| [0009](0009-setspec-schema-strategy.md) | SetSpec schema and versioning strategy | Accepted |
| [0010](0010-queue-implementation.md) | Database-backed queue, no broker | Accepted |
| [0011](0011-shared-package-boundaries.md) | Shared package boundaries and extraction timing | Accepted |
| [0012](0012-prompt-storage-format.md) | Prompts as versioned JSON records | Accepted |
| [0013](0013-api-versioning.md) | API versioning | Accepted |
| [0014](0014-authentication-strategy.md) | Authentication strategy | Accepted |
| [0015](0015-repository-and-distribution-model.md) | Repository and distribution model | Accepted |
| [0016](0016-unavailable-is-not-zero.md) | Unavailable is not zero | Accepted |
| [0017](0017-benchmark-confidence-and-freshness.md) | Benchmark confidence and freshness | Accepted |
| [0018](0018-external-benchmark-isolation.md) | External benchmark isolation and sandboxing | Accepted |
| [0019](0019-python-baseline-and-config-format.md) | Python baseline and configuration format | Accepted |
| [0020](0020-ui-rendering-strategy.md) | UI rendering strategy | Accepted |
| [0021](0021-telemetry-collection-strategy.md) | Telemetry collection strategy | Accepted |
| [0022](0022-capability-evidence-record-contract.md) | Capability evidence record contract | Accepted |
| [0023](0023-runtime-profile-resolution.md) | Runtime profile resolution and served context | Accepted |
| [0024](0024-canonical-id-and-model-references.md) | Canonical ID format and model references in URLs | Accepted |
| [0025](0025-envelope-boundaries.md) | Envelope boundaries: what carries a SetSpec envelope | Accepted |
| [0026](0026-local-http-hardening.md) | Local HTTP hardening: Host validation, CSRF and outbound fetch | Accepted |
| [0027](0027-multi-gpu-semantics.md) | Multi-GPU semantics | Accepted |
| [0028](0028-prompt-pack-granularity.md) | Prompt attribution granularity and shared prompt tooling | Accepted |
| [0029](0029-queue-mechanics.md) | Queue mechanics: ageing, attempts, admission states and leases | Accepted |
| [0030](0030-model-cost-and-pricing.md) | Model cost: prices are dated observations, not model properties | Accepted |
| [0031](0031-user-defined-goal-benchmarks.md) | User-defined goal benchmarks and the calibrated-judge instrument | Accepted |
| [0032](0032-judge-validity-and-user-capability-namespace.md) | Judge validity in confidence, and the `user.*` capability namespace | Accepted |
| [0033](0033-benchmark-interaction-protocol.md) | Benchmark interactions: multi-turn execution and the two scorer protocols | Accepted |
| [0034](0034-run-level-derived-metrics.md) | Run-level derived metrics: the second benchmark seam | Accepted |
| [0035](0035-application-owned-document-schemas.md) | Application-owned document schemas, and `benchmark.export` | Accepted |
| [0036](0036-queue-recovery-transitions.md) | Queue state machine: recovery edges for every lease-holding state | Accepted |
| [0037](0037-production-evidence-never-raises-capability-scores.md) | Production evidence never raises capability scores; upward adaptation is post-1.0 exploration routing | Accepted |
| [0038](0038-one-model-at-a-time-per-gpu.md) | One model at a time per GPU: fit with room for context, or wait | Accepted |
| [0039](0039-audit-gated-blocking-requirements.md) | A model's silence must not settle a blocking gate | Accepted |
| [0040](0040-routing-backend-owns-model-choice.md) | A routing backend owns model choice and residency | Accepted |
| [0041](0041-caller-schemas-do-not-travel-through-a-router.md) | A caller's output schema does not travel through a router; the caller still owns it | Accepted |
| [0042](0042-a-check-may-not-restate-its-requirement.md) | A deterministic check may not be a restatement of its requirement | Accepted |
| [0043](0043-grounding-is-verified-not-assumed.md) | Grounding is verified, not assumed | Accepted |
| [0044](0044-a-state-change-and-its-event-are-one-write.md) | A state change and the event announcing it are one write | Accepted |
| [0045](0045-promptcadence-reaches-models-only-through-loadcoach.md) | PromptCadence is a fourth application, and it reaches a model only through LoadCoach | Accepted |
| [0046](0046-data-classification-is-ordered-and-defaults-closed.md) | Data classification is ordered, caller-declared, and defaults to the most restrictive | Accepted |
| [0047](0047-a-tier-is-configuration-and-a-model-never-sizes-its-own-budget.md) | A tier is configuration over a task profile, and a model's guess never sizes its own budget | Accepted |
| [0048](0048-the-bypass-removes-planning-never-governance.md) | The bypass removes planning; it never removes governance | Accepted |
| [0049](0049-approval-is-a-mode-with-its-own-scope.md) | Approval is a mode with its own scope, and silence never grants it | Accepted |
| [0050](0050-a-package-may-ship-tables-never-a-migration-history.md) | A shared package may ship tables; it may never own a migration history | Accepted |
| [0051](0051-plans-stay-internal-and-one-payload-travels.md) | A plan never leaves PromptCadence; the egress decision is the one shape that travels | Accepted |
| [0052](0052-compaction-is-a-view-and-the-package-plans-it-only.md) | Compaction is a view, and the package that plans a summary never calls a model | Accepted |
| [0053](0053-a-refused-tool-call-is-a-result-not-an-exception.md) | Tools are registered in code, refused in order, and a refusal is a result | Accepted |
| [0054](0054-commissioner-records-egress-it-does-not-enforce-it.md) | Commissioner renders and records an egress verdict; enforcing it is the caller's | Accepted |
| [0055](0055-loadcoach-registers-providers-by-name-and-kind.md) | LoadCoach registers providers by name and kind, into one tagged registry | Accepted |
| [0056](0056-every-turn-executes-under-one-execution-intent.md) | Every turn executes under exactly one immutable ExecutionIntent | Accepted |
| [0057](0057-the-explanation-is-materialized-and-the-rows-stay-authoritative.md) | The trajectory explanation is materialized; the rows stay the source of truth | Accepted |
| [0058](0058-the-execution-subject-gains-an-adapter-axis.md) | The execution subject gains an adapter axis, and an absent adapter changes nothing | Accepted |
| [0059](0059-adapter-evidence-is-measured-never-inherited.md) | Adapter evidence is measured, never inherited from its base | Accepted |
| [0060](0060-selection-lives-in-the-subject-serving-mode-in-the-profile.md) | Adapter selection lives in the subject; adapter serving mode lives in the runtime profile | Accepted |
| [0061](0061-the-adapter-registry-is-a-directory-and-a-manifest.md) | The adapter registry is an operator's directory and a reviewed manifest, not a service | Accepted |
| [0062](0062-llamacpp-serves-adapters-through-a-supervised-process.md) | llama.cpp serves adapters, through a process the suite supervises | Accepted |
| [0063](0063-one-adapter-at-a-time.md) | One adapter at a time, at a fixed scale | Accepted |
| [0064](0064-adapters-are-selected-through-the-capability-vocabulary.md) | Adapters are selected through the capability vocabulary; there is no tag channel | Accepted |
| [0065](0065-an-adapter-is-classified-and-local-only.md) | An adapter is a distillate of its training data, and it does not leave the machine | Accepted |
| [0066](0066-residency-is-two-level.md) | Residency is two-level: the base is the expensive switch, the adapter is free | Accepted |
| [0067](0067-reliability-keys-on-the-subject-not-the-base.md) | Reliability and the breaker key on the subject, never on the base | Accepted |
| [0068](0068-a-post-freeze-minor-is-a-sibling-class.md) | A post-freeze minor is a sibling class, and a bare name keeps its version | Accepted |
| [0069](0069-a-partial-price-is-a-floor-and-a-money-ceiling-chooses-how-it-binds.md) | A partial price accumulates as a floor, and a money ceiling chooses whether an unknown counts against it | Accepted |
| [0070](0070-an-absent-token-class-is-zero-only-where-the-protocol-cannot-bill-it.md) | An absent token class is zero only where the protocol cannot bill it | Accepted |
| [0071](0071-modelrack-persists-artifact-digests-in-a-json-file-the-application-names.md) | ModelRack persists artifact digests in a JSON file the application names | Accepted |
| [0072](0072-the-model-pricing-record-file.md) | The ModelPricing record file | Accepted |
| [0073](0073-egress-is-decided-on-configuration-before-availability.md) | Egress is decided on a tier's configuration, before its availability | Accepted |
| [0074](0074-adapter-enabled-serving-is-a-runtime-profile-field.md) | Adapter-enabled serving is a `RuntimeProfile` field, not a `provider_options` convention | Accepted |
| [0075](0075-a-request-carrying-tools-requires-tool-use-of-every-candidate.md) | A request carrying tools requires `tool_use` of every candidate | Accepted |
| [0076](0076-a-step-retry-is-a-repeat-under-the-same-intent.md) | A step retry is a repeat under the same intent | Accepted |
| [0077](0077-a-named-provider-block-and-the-singular-block-are-one-registry.md) | A named provider block and the singular block are one registry, and both together is a refusal | Accepted |
| [0078](0078-a-shipped-response-field-is-superseded-beside-its-replacement.md) | A shipped response field is superseded beside its replacement, never reshaped under it | Accepted |
| [0079](0079-an-adapter-classification-refusal-is-a-routing-rejection.md) | An adapter's classification refusal is a routing rejection, recorded in the explanation | Accepted |
| [0080](0080-a-persisted-decision-names-the-subject-by-reference-and-by-string.md) | A persisted decision names the subject by reference and by string | Accepted |
| [0081](0081-an-adapter-subject-inherits-no-evidence-from-its-base.md) | An adapter subject inherits no evidence from its base | Accepted |
| [0082](0082-a-migration-run-suspends-sqlite-foreign-key-enforcement.md) | A migration run suspends SQLite foreign-key enforcement | Accepted |
| [0083](0083-an-adapter-pin-is-configured-on-by-being-configured.md) | An adapter pin is configured on by being configured | Accepted |
| [0084](0084-a-producer-chooses-a-payload-version-by-content.md) | A producer chooses a payload version by content, not by build | Accepted |
| [0085](0085-the-evidence-uniqueness-key-carries-the-adapter.md) | The evidence uniqueness key carries the adapter, on both sides | Accepted |
| [0086](0086-the-consumers-adapter-key-column-is-not-nullable.md) | The consumer's adapter key column is not nullable | Accepted |
| [0087](0087-the-evidence-gate-admits-only-a-signal-that-scores.md) | The adapter evidence gate admits only a signal that scores | Accepted |
| [0088](0088-an-excluded-measurement-falls-back-to-the-prior-it-displaced.md) | An excluded measurement falls back to the prior it displaced | Accepted |
| [0089](0089-the-fixed-regression-rows-bound-their-own-output.md) | The fixed regression rows bound their own output | Accepted |
| [0090](0090-a-compaction-summary-runs-under-a-superseding-revision.md) | A compaction summary runs under a superseding revision of the step's own intent | Accepted |
| [0091](0091-a-compaction-turn-is-debited-and-does-not-spend-the-steps-advance.md) | A compaction turn is debited, and does not spend the step's advance | Accepted |
| [0092](0092-the-invalidation-entry-point-ships-before-the-sweep-that-calls-it.md) | The invalidation entry point ships before the sweep that calls it | Accepted |
| [0093](0093-materialization-follows-the-terminal-transition.md) | Materialization follows the terminal transition, and a missing revision is not a missing explanation | Accepted |
| [0094](0094-the-console-authenticates-as-the-api-does.md) | The console authenticates as the API does, and every form is CSRF-protected | Accepted |
| [0095](0095-the-injection-corpus-asserts-the-harness-never-the-model.md) | The injection corpus asserts the harness, never the model | Accepted |
| [0096](0096-replayed-tool-call-arguments-are-capped-at-the-records-bound.md) | Replayed tool-call arguments are capped at the record's bound | Accepted |
| [0097](0097-a-performance-budget-asserts-its-ceiling-and-reports-its-target.md) | A performance budget asserts its ceiling and reports its target | Accepted |
| [0098](0098-promptcadence-1-0-ships-with-remote-tiers-refusing-honestly.md) | PromptCadence 1.0 ships with remote tiers refusing honestly | Accepted |
| [0099](0099-a-task-profile-may-ask-for-reduced-thinking.md) | A task profile may ask for reduced thinking, and routing enforces that it can be asked | Accepted |
| [0100](0100-promptcadences-runtime-changeable-set-is-five-tuning-numbers.md) | PromptCadence's runtime-changeable set is five tuning numbers, and the environment still wins | Accepted |
| [0101](0101-a-runtime-setting-need-not-be-a-configuration-key.md) | A runtime setting need not be a configuration key, and the ones that are not say so | Accepted |
| [0102](0102-freeweights-settings-body-gains-the-suites-shape.md) | FreeWeight's settings body gains the suite's shape, and `items` is deprecated | Accepted |
| [0103](0103-ideapress-reacts-to-a-verdict-it-does-not-own.md) | IdeaPress reacts to a verdict it does not own: a bound ceiling pauses, an undeclared remote ceiling denies | Accepted |
| [0104](0104-an-adopted-reductions-seam-and-error-vocabulary-survive-it.md) | An adopted reduction's seam and error vocabulary survive it | Accepted |
| [0105](0105-a-shipped-usage-object-keeps-null-until-api-v2.md) | A shipped `usage` object keeps `null` on two of its five classes until `/api/v2` | Superseded by ADR-0112 |
| [0106](0106-the-provider-protocol-carries-the-adapter-inventory.md) | The `Provider` protocol carries the adapter inventory, and the `lora` field carries the complete set | Accepted |
| [0107](0107-two-loadcoach-clients-are-not-yet-one-package.md) | The second LoadCoach consumer arrived; the client package is still declined | Accepted |
| [0108](0108-the-snapshot-contracts-the-surface-and-goldens-contract-the-bodies.md) | The OpenAPI snapshot contracts the surface; captured goldens contract the bodies | Accepted |
| [0109](0109-a-stored-row-this-build-cannot-read-serves-configuration.md) | A stored settings row this build cannot read serves configuration, and the changeable set is an enumeration | Accepted |
| [0110](0110-the-pricing-file-reader-is-a-loadledger-surface.md) | The pricing-file reader is a LoadLedger surface, at ADR-0072's own second-consumer trigger | Accepted |
| [0111](0111-the-container-rung-is-proved-on-docker-and-podman-is-not-an-exit-condition.md) | The container rung is proved on docker, and podman is not an exit condition | Accepted |
| [0112](0112-the-usage-object-spells-unavailable-one-way-inside-api-v1.md) | The `usage` object spells "unavailable" one way, inside `/api/v1` | Accepted |
| [0113](0113-packages-stay-0x-at-m9-and-1-0-is-earned-per-package.md) | Packages stay `0.x` at M9; a `1.0` is earned per package | Accepted |
| [0114](0114-the-dependency-budget-is-the-enumerated-set-a-component-declares.md) | The runtime dependency budget is an enumerated set, not a count | Accepted |
| [0115](0115-ideapress-shows-no-machine-telemetry.md) | IdeaPress shows no machine telemetry | Accepted |
| [0116](0116-research-runs-under-toolyard-and-fetches-only-a-named-host.md) | IdeaPress's `research` stage runs under ToolYard, and fetches only a host the operator named | Accepted |
| [0117](0117-provider-registrations-are-edited-in-place-in-the-config-file.md) | Provider registrations are edited in place in the config file | Accepted |
| [0118](0118-a-discovered-model-can-be-disabled.md) | A discovered model can be disabled | Accepted |
| [0119](0119-model-servers-run-under-a-host-memory-cap.md) | Model servers run under a host-memory cap | Accepted |
| [0120](0120-kv-cache-precision-and-flash-attention-are-per-model-llamacpp-settings.md) | KV-cache precision and flash attention are per-model llama.cpp settings, and Ollama refuses them | Accepted |
| [0121](0121-freeweight-launches-llama-server-with-fit-off-and-caps-the-max-fit-ladder.md) | FreeWeight launches llama-server with `--fit off` and caps the max-fit ladder; LoadCoach keeps `--fit on` | Accepted |
| [0122](0122-an-empty-fetch-allowlist-means-loopback-and-no-host-is-not-registering.md) | An empty `http_fetch` allowlist means loopback, deliberately; "no host at all" is not registering the tool | Accepted |
| [0123](0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md) | WeightRoomGym is a fifth application, and it is a host operator tool above the layer rules | Accepted |
| [0124](0124-a-raw-write-into-another-applications-database-passes-a-five-part-guard.md) | A raw write into another application's database passes a five-part guard, and some tables are never written | Accepted |
| [0125](0125-weightroom-drives-the-applications-through-systemd-user-units-it-writes.md) | WeightRoomGym drives the applications through `systemd --user` units it writes; Ollama is read, and restarted only through a polkit rule | Accepted |
| [0126](0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md) | WeightRoomGym is the only service on the LAN, and it terminates TLS with its own CA behind a session login | Accepted |
| [0127](0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md) | Every application publishes its settings schema, and WeightRoomGym generates the settings form from it | Accepted |
| [0128](0128-mirrorwall-vendors-htmx-and-applications-may-adopt-it.md) | MirrorWall vendors htmx, and an application may adopt it | Accepted |
| [0129](0129-weightroom-reads-both-version-payload-shapes.md) | WeightRoomGym reads both shapes of `GET /api/v1/version`, and the suite converges on one later | Accepted |
| [0130](0130-weightroomgyms-application-tokens-carry-admin-scope.md) | WeightRoomGym's application tokens carry `admin` scope, because ADR-0127 rule 4 routes every runtime key through `PUT /settings` | Accepted |
| [0131](0131-cli-json-shapes-converge-on-values-and-items.md) | Two CLI JSON shapes converge — `config show` says `values`, a listing says `items` — released as minors by operator exception | Accepted |
| [0132](0132-loadcoach-streams-thinking-deltas-as-their-own-frame.md) | LoadCoach streams thinking deltas live as their own enveloped `thinking` frame (1.5.0) | Accepted |
| [0133](0133-the-guard-follows-foreign-keys-observes-stopped-twice-and-binds-a-write-to-its-dry-run.md) | The guard follows foreign keys into the never-writable list, observes *stopped* as unit and port, reads the URL from `config show`, and binds a write to its dry run | Accepted |
| [0134](0134-event-logs-go-with-their-deleted-parent-freeweight-deletes-its-own-results-and-guarded-write-backups-expire.md) | A cascaded delete may remove an event log's rows, FreeWeight's own deletion API is the curated path for its results, and guarded-write backups expire after 90 days | Accepted |
| [0135](0135-a-minor-that-feeds-a-checked-hash-is-read-at-its-own-minor.md) | `benchmark.result` and `benchmark.run_summary` gain a `1.1` carrying `adapters_registered`; a `1.0` reader refuses a document that states it, so a reader of one adopts the `V1_1In` name | Accepted |
| [0136](0136-weightroom-restores-its-own-database-through-a-job-handed-to-a-transient-unit.md) | WeightRoomGym restores its own database through a `self_restore` job that hands itself to a transient `systemd --user` unit, which stops the console, restores, carries the job's own rows forward and starts it again | Accepted |
| [0137](0137-an-alert-is-an-episode-a-condition-clears-itself-an-event-waits-for-acknowledgement.md) | An alert is an episode: a condition clears itself, an event (a memory-cap kill) waits for its acknowledgement, a reading that could not look clears nothing, an inactive unit is not down, and the evaluator has its own thread | Accepted |
| [0138](0138-the-per-page-javascript-budget-excludes-the-vendored-libraries-and-names-them.md) | The per-page JavaScript budget (spec §15) counts the console's own scripts and excludes the vendored, pinned libraries — htmx and its SSE extension, ECharts, mermaid — which are budgeted by name; the total is reported beside the part | Superseded by 0139 |
| [0139](0139-the-per-page-javascript-budget-is-a-total-of-120-kb.md) | The per-page JavaScript budget is one total, 120 KB, everything a shell page downloads (htmx included); only mermaid and ECharts, which load where used, are outside it; the test prints the breakdown | Accepted |
| [0140](0140-adapters-are-inert-under-a-provider-that-cannot-serve-them.md) | A configured `[adapters] directory` under a provider that cannot serve a LoRA is inert, not fatal: the directory is read and listed, nothing is offered to the provider, a run naming an adapter is still refused by name, and every listing says `provider_can_serve` | Accepted |
| [0141](0141-a-juror-that-runs-out-of-output-budget-is-named-not-a-protocol-error.md) | A juror cut off at its output limit refuses `output_truncated`, not `protocol_error`; a judge call *may* be bounded by `[judge] max_output_tokens`, unset by default because a 2048 default was measured narrowing a working juror's sample; FreeWeight never asks a reasoning juror not to reason, and eligibility stays a question of permission — the calibration report is what measures competence, and it says so in words | Accepted |
| [0142](0142-echarts-is-vendored-and-budgeted-by-name.md) | ECharts 6.1.0 is vendored by MirrorWall and loaded only on a page that opts in; it is the one named exclusion from ADR-0139's 120 KB total and is budgeted by name (row WX6) | Accepted |
| [0143](0143-a-workflow-is-a-stored-versioned-record-a-project-pins.md) | An IdeaPress workflow is a versioned JSON record in a `workflows` table, never edited in place; a project pins `workflow_id@version` and the stage executor reads the bound definition rather than the `STAGES` table; a workflow chooses which model stages run and with what prompt, rounds and model hint, never their order and never the four gates, which are not in the record at all | Accepted |
| [0144](0144-freeweight-keeps-several-provider-profiles-and-runs-one.md) | FreeWeight keeps several `[providers.<name>]` profiles and runs exactly one, named by `[provider] active`; a bare `[provider]` block is the profile `default`, so every existing file resolves unchanged (amends ADR-0077; row WX13) | Accepted |
| [0145](0145-freeweight-drafts-an-adapter-manifest-and-still-trusts-nothing.md) | FreeWeight writes an adapter manifest *draft* on request — `data_classification: confidential`, reviewed by a person before it becomes a manifest — reversing ADR-0061 rule 4's "FreeWeight writes no drafts" (row WX7) | Accepted |
| [0146](0146-the-console-has-no-catalog.md) | The console has no catalog: the `/catalog` page, its API, and the console's pull, drop-in and delete leave; enable/disable stays on the LoadCoach and FreeWeight tabs, and the `catalog.*` audit names and `catalog_pull` job-kind name stay readable (row WY1) | Accepted |
| [0147](0147-a-chart-may-map-its-fill-to-value-coloured-from-tokens.md) | A chart may map its fill to its value: the option carries only the scale (`visualMap` with `min`, `max` and `mw_scale: "load"`) and a unit (`mw_unit`), and MirrorWall's `charts.js` colours the scale success → warning → danger from the tokens at draw time and prints values through one formatter; extends ADR-0142, supersedes nothing (row WY4) | Accepted |
| [0148](0148-context-fit-is-its-own-suite-and-gates-benchmarks.md) | Context fit is its own suite, `native.context_fit`, each rung served at its own context; every other benchmark of a model waits for it (`benchmarks.require_context_fit`) and then runs at the context it measured (rows CF2, CF3) | Accepted |
| [0149](0149-the-console-applies-a-context-fit-to-loadcoach.md) | The console applies a measured context fit to LoadCoach's `[runtime.models]` on the operator's word — no payload, no import — and a task profile's `allow_cpu_spill` raises a configured context to what it needs (rows CF4, CF5) | Accepted |
| [0150](0150-the-speed-capability-reads-prompt-throughput-at-one-size.md) | The speed capability reads prompt throughput at one prompt size, `prompt_tokens_per_second_at_4096`, so models benchmarked at different contexts compare (row CF6) | Accepted |
| [0151](0151-context-fit-refines-between-rungs-and-climbs-to-256k.md) | A benchmark test may choose follow-up cases from the outcomes so far (`next_cases`); `native.context_fit` halves the gap between rungs to 4 096 tokens, and `benchmarks.max_fit_context_tokens` defaults to 262 144; amends ADR-0121 §1's default (row CF8) | Accepted |
| [0152](0152-a-context-fit-is-used-one-step-below-what-was-measured.md) | A context fit is used one step (4 096 tokens) below what was measured: FreeWeight benchmarks run at it, `GET /results/context-fit` carries `usable_context_tokens`, and the console's Apply writes it; amends ADR-0148 §6 and ADR-0149 §1 (row CF9) | Accepted |

## Writing a new ADR

1. Copy the format above; number it sequentially.
2. Record real alternatives with real reasons — an ADR whose alternatives are strawmen is worthless.
3. Link it from this index and from the documents it governs.
4. Never delete an ADR. Supersede it.

## Amendments

ADRs 0022–0029 were added by the [final architecture audit](../reviews/final_architecture_audit.md)
on 2026-08-21, before implementation began. Where one of them narrows or corrects an earlier
decision, the earlier ADR carries an **Amended by** note at its head and the amending ADR states what
it changes. No earlier decision was reversed; each was found to be under-specified at a boundary
rather than wrong.

**ADRs 0123–0127 were added on 2026-09-09** (row W0) for the fifth application, WeightRoomGym — the
host operator's console, decided at the interview of the same day. They follow the ADR-0038
precedent for amending the frozen master architecture: the fifth application is additive, and
the one thing it reverses — for itself alone — is the rule that no application reads another's
database, which [ADR-0123](0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md)
scopes by enumeration and [ADR-0124](0124-a-raw-write-into-another-applications-database-passes-a-five-part-guard.md)
prices. [ADR-0126](0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md)
amends [ADR-0014](0014-authentication-strategy.md) for one component (a session login where
ADR-0014 chose bearer tokens, because WeightRoomGym is the proxy ADR-0014 assumed in front) and
withdraws [ADR-0026](0026-local-http-hardening.md)'s JSON-API CSRF exemption for the same one
component, whose API is cookie-authenticated; both carry an *Amended by* note.
[ADR-0128](0128-mirrorwall-vendors-htmx-and-applications-may-adopt-it.md) (the same day, on the
operator's decision) withdraws [ADR-0020](0020-ui-rendering-strategy.md)'s rejection of htmx as a
dependency — MirrorWall 0.3 vendors it, opt-in per page — and supersedes the one sentence of
ADR-0123 rule 7 that repeated that rejection; both carry the note.

ADR-0033 was added on 2026-08-27, during FreeWeight Phase 7, to record a decision the phase forced
and the documentation did not contain: how a benchmark drives more than one provider call per
sample. It is the one ADR here written *after* the code rather than before it, which is a departure
from this directory's own rule; the code it describes was written first and the debt recorded, and
this ADR is that debt paid before Phases 8B and 13 build on the same seam.

ADRs 0031–0032 were added on 2026-08-26 to close the undelivered judge-scored capability
mapping in FreeWeight's benchmark catalogue (§6) and to state the oracle/instrument distinction the
testing standards implied but never wrote down. They amend ADR-0012, ADR-0017 and ADR-0022 and add
one root to the SetSpec capability vocabulary; they reverse nothing.

ADRs 0034–0035 were added on 2026-08-28, after FreeWeight Phase 10A, to close two decisions the
phases forced and recorded as debts rather than took quietly. ADR-0034 states the aggregation
seam that lets three suites compute run-level figures no scorer can see, and draws the boundary
that a derived metric is a function of one run. ADR-0035 gives applications a namespace of their
own for documents SetSpec does not describe, and amends ADR-0025 §1's "there is no third case"
to admit the case that turned up. Both are ADRs written after the code they describe, for the
same reason ADR-0033 was: the debt was recorded at the time and is paid here before the next
phase builds on either seam.

ADR-0039 was proposed and accepted on 2026-08-31, out of the M7 verification of IdeaPress
(finding M7-20): a blocking requirement with no deterministic check was satisfied by the audit's
*silence*, which let the model's default behaviour settle exactly the qualitative gates nothing
mechanical backstops. The accepted option (b) replaces silence with explicit, labelled,
per-requirement attestation — only a literal `met` satisfies, everything else (including an
invented verdict) degrades toward `cannot_judge` and pauses — with
`workflow.allow_audit_gated_requirements = false` as the wholly-mechanical opt-out.

ADR-0038 was added on 2026-08-31, during IdeaPress's M7 build, to close a gap Master Architecture
§5.2 left open: its inference-concurrency bullet gave a policy for FreeWeight and LoadCoach and
named IdeaPress nowhere, while IdeaPress's own default configuration binds two models to a card
that holds one. It states the machine-wide rule — two models contending for one GPU must both fit,
with room for their context, or the later one waits — names LoadCoach's admission as the compliant
reference implementation, gives IdeaPress the narrower serialise-and-unload obligation that needs
no queue, and records the estimator question (duplicate `estimate_vram` or extract it to
`modelrack`) with a recommendation rather than performing an extraction that touches a published
package and two 1.0 applications.

ADR-0040 was added on 2026-08-31, during IdeaPress's M8 build, before the LoadCoach adapter was
written. `InferenceGateway` resolves a `[models.stages]` binding for every request and unloads the
resident model before a switch — both correct for a backend IdeaPress drives, neither correct for
one that routes for itself. With the shipped defaults, `inference.mode = "loadcoach"` would have
pinned every request to the bound model and bypassed LoadCoach's profiles, evidence and admission
control while every stage still succeeded. It gives the port a `routes_internally` flag, makes
`[inference.loadcoach] honour_stage_bindings` the explicit opt-in spec §12's "unless overridden"
had never been given, and records an unhonoured pin as a degradation rather than a failure.

ADR-0041 was added on 2026-08-31, alongside ADR-0040 and for the same reason: the LoadCoach
adapter could not be written correctly without deciding it. LoadCoach's `response_format` is a bare
string and the schema applied is the *task profile's*, so a caller asking for `json_schema` gets a
shape it did not write. For `content.review` that shape forbids `requirements_assessment` and has
no `cannot_judge` verdict, which would make ADR-0039's attestation structurally impossible through
LoadCoach while every stage still ran. IdeaPress therefore asks for `json` and enforces its own
shape above the port, records the difference as a degradation on every affected attempt, and
reports `structured_output=False` honestly.

ADRs 0042 and 0043 were added on 2026-09-01, during IdeaPress's M8 build, from reading a real
run's output rather than from a failing test. ADR-0042 records that a `must_contain_any` check
built out of its own requirement's words is satisfied by quoting the requirement — the gate then
behaves exactly as ADR-0039 says it must and commits work its own critique called deficient.
ADR-0043 records that "grounded in the sources" was a requirement nothing verified: the compiler
wrote checks for the vocabulary of grounding, not for the grounding. Both narrow ADR-0039 without
reversing it; the asymmetry it establishes is unchanged, and what changed is which checks are
allowed to exist.

**ADRs 0045–0067 were written on 2026-09-02**, before any code, as the joint Phase 0 / LA0 of two
post-1.0 arcs: the [PromptCadence arc](../roadmap/promptcadence-roadmap.md) (a plan-approved,
tier-routed agent harness over LoadCoach, plus the four shared packages it justifies) and the
[Adapter arc](../roadmap/adapter-roadmap.md) (hot-swappable LoRA serving on a warm base via
llama.cpp). They are the suite's rule working as intended rather than a debt being paid: the
decisions were argued in the roadmaps, and these records exist so that no implementation phase has to
invent one. 0045–0057 expand the PromptCadence arc's D-1…D-13; 0058–0067 expand the Adapter arc's
A-1…A-10.

**ADR-0069 was added on 2026-09-02**, after LoadLedger Phase 1 had been built to its spec's
contract 2 as first written and the review of that build found the contract made money ceilings
unable to bind on any real adapter's output. It reverses that one line, before Phase 2 persists a
row under it, and records the operator's choice between a floor that may fire late and a strict
ceiling that never crosses. [ADR-0070](0070-an-absent-token-class-is-zero-only-where-the-protocol-cannot-bill-it.md) followed the same day and closes the question
0069 left open — which layer decides what an absent token class means. It is the adapter, per
response: zero where the protocol cannot bill the class, unavailable where it could and the
response did not say.

**ADR-0071 was added on 2026-09-03**, after ModelRack Phase 6 had been built with its artifact
digests held in memory to the letter of the spec's "no persistence" line, and the operator's
review of that build asked why a content hash that only content can invalidate should cost
forty-five seconds on every process start. It narrows spec §3 by one named exception — a
versioned, clearable `digests.json` beside the pid files ADR-0062 already placed in the
application's `state_dir` — and is the third record here written after the code rather than
before it.

**ADR-0072 was added on 2026-09-04**, after PromptCadence Phase 5 became the suite's first
consumer of `baseaicore.ModelPricing` and discovered that nothing anywhere said what a price list
looks like on disk. It is the fourth record here written after the code rather than before it, and
the reason it is an ADR rather than a line in one application's spec is
[ADR-0030](0030-model-cost-and-pricing.md)'s `pricing_hash`: that hash is only a join between a
stored usage and the price it was costed under if every application hashes the same object, and two
components that each invented a file would differ on exactly one question — whether an absent rate
means "not stated" or "free" — and produce the same hash for two different prices.

**ADR-0073 was added on 2026-09-04**, after PromptCadence Phase 6 found that spec §20 criterion 4
was unreachable as the code stood. Every remote tier reports `loadcoach_has_no_remote_provider`
until LC-E1 registers one, so a `confidential` trajectory aimed at one halted on the availability
check before any egress evaluation ran — no request left, but the refusal was not the queryable
`EgressDecision` the criterion demands, and the reason given was about the deployment rather than
about the data. It is the fifth record here written after the code rather than before it. The
reason it is an ADR and not a line in one application's spec is that it records an **ordering**:
criteria 4 and 5 are statements about *when* a refusal happens, a build that reordered the checks
would still pass every unit test of the policy itself, and the observable failure — a recorded
reason that silently changes the day infrastructure changes — appears only in a deployment nobody
has yet.

Three of them **amend earlier records additively, reversing nothing**.
[ADR-0058](0058-the-execution-subject-gains-an-adapter-axis.md) extends ADR-0008, ADR-0023 and
ADR-0024 with an optional adapter axis on the execution subject and an optional suffix on the
canonical string — a subject with no adapter is byte-for-byte what it is today.
[ADR-0051](0051-plans-stay-internal-and-one-payload-travels.md) adds `promptcadence.*` as a fourth
application namespace and `governance.*` as a SetSpec-owned root to ADR-0035's table.
[ADR-0050](0050-a-package-may-ship-tables-never-a-migration-history.md) opens a narrow door in the
storage model — a package may ship mountable table definitions, and may still never own an engine, a
session, a migration history or the data. Together they amend
[Master Architecture](../architecture/master-architecture.md) §§1.1, 1.3, 1.5, 2, 3, 8, 10, 11 and
12 through the [ADR-0038](0038-one-model-at-a-time-per-gpu.md) mechanism.

ADR-0044 was added on 2026-09-01, during the same build, after CI failed a test a fast machine
could not. It is the second ADR here written after the code rather than before it. The decision it
records — that a state change and the event announcing it commit together — was already
implemented in LoadCoach and already explained in that component's own docstrings; what did not
exist was the rule, stated once, applying to both applications. IdeaPress had written the naive
order in three places independently, which is the argument for writing it down.

**ADR-0074 was added on 2026-09-04**, after ModelRack Phase 7 built adapter serving and found that
[ADR-0060](0060-selection-lives-in-the-subject-serving-mode-in-the-profile.md)'s "serving mode lives
in the runtime profile" had no mechanism behind it: `--lora` flags come from the provider's
registration set, `RuntimeProfile` is a separate object the caller passes, and nothing joined them.
So a base on an adapter-registered server and the same base on a clean one hash to the same profile
and would merge. It is the sixth record here written after the code rather than before it, and the
reason it is an ADR rather than a convention is what the alternatives section argues: the cheapest
correct fix — a `provider_options` key — is unvalidated and unspellable-wrong-safely, so a
misspelling would not fail but would mint a second hash meaning nothing, which is the same silent
merge from the other direction. The window in which this is cheap closes the first time a base is
benchmarked on a machine with an adapters directory configured, because evidence recorded without
the field is not separable afterwards.

**ADR-0075 was added on 2026-09-04**, when LoadCoach's `/generate` gained `tools` on its request
body (row G2). G1 had shown the cost of the gap from the model's side: told about no tools, a
model invents names out of its own vocabulary and every call is refused. The record exists because
closing that gap raised a question the wire alone does not answer — what a request carrying tools
does to *routing* when the task profile requires nothing — and the two easy answers, letting the
tools reach a provider that cannot use them and dropping them silently, are both failures a caller
cannot see until after a model was chosen.

**ADR-0076 was added on 2026-09-05** (row G3), when PromptCadence's loop gained a per-step retry.
Until it, a step that could not complete ended the trajectory and the loop's only second chance was
the tier escalation — an ask for a *wider* envelope. The record exists because a repeat and an
escalation claim different things about what happened, and because every attempt becomes a row an
explanation reads back: the order of the two, the line between an accident and a decision, and
whether the attempt history lives in a counter, in the events or in a table are all decisions the
explanation inherits rather than choices an implementation can take quietly.

**ADR-0077, ADR-0078, ADR-0079 and ADR-0080 were added on 2026-09-05** (row H2), when LoadCoach
grew named provider registration and the adapter registry. Each closes a question the accepted
adapter decisions raised but did not answer, and each outlives the row that found it. **0077**: a
released configuration file gains a second, richer shape, and the half-migrated file — both shapes
present — is the case that a precedence rule would answer silently. **0078**: `output.tool_calls`
ships in a `1.0` response in a shape the first caller to consume it got wrong, and a minor is not
allowed to reshape it under the callers that read it correctly. **0079**: I19 asks for a "recorded
denial" from a component that holds no decision ledger, so what is recorded, and where, had to be
settled before the constraint was written. **0080**: an explanation is kept for ever and an adapter
directory is not, so a decision record has to name its subject in a form that later configuration
cannot revise.

**ADR-0081 and ADR-0082 were added on 2026-09-05** (row H2's second sitting), and both were found
by building rather than by planning. **0081**: expanding a candidate to an adapter subject inherits
the base's `ModelFacts`, so the base's benchmark evidence arrives with it unless it is removed —
and leaving it would let an unmeasured adapter score as measured weights, invisibly, with
`benchmark` named as the source. It is ADR-0058 §4's rule applied in the other direction, and it
decides what "no benchmark, no use" actually gates. **0082**: adding a foreign key to a table on
SQLite is a rebuild whose parent drop **cascades**, so LoadCoach's first 1.1 migration deleted
every stored routing candidate — the explainability promise itself — and reported success. The
pragma that prevents it is a documented no-op inside a transaction, which is why the exception
needs a record rather than a comment.

**ADR-0083 was added on 2026-09-05** (row H3, from its kickoff interview). IdeaPress's per-stage
adapter pin gets its own configuration table and no gating boolean, because the obvious economy —
hanging it off `[models.stages]` and `honour_stage_bindings` — makes the configuration lie. That
flag's documented meaning is "give up routing", and an adapter pin does not surrender routing; a
new default-off boolean would instead make a configured pin a silent no-op, which is the failure the
`job_stages` validator already exists to prevent.

**ADR-0084 was added on 2026-09-05** (row H4, from its kickoff §0.3 decision 3). FreeWeight 1.1 is
the first producer in the suite able to write two versions of one payload, and
[ADR-0068](0068-a-post-freeze-minor-is-a-sibling-class.md) had deliberately not said which it should
choose. It writes the **lowest version that can express the document**: a bundle with no
adapter-bearing evidence is `1.0` and byte-identical to what `freeweight 1.0.0` wrote, asserted by a
golden rather than argued. Always writing the newest would have made every consumer in the suite
move for a field almost none of them will ever see — the exact cost the sibling-class mechanism was
built to avoid — and would have destroyed the byte-identity assertion that is this release's
strongest regression test.

**ADR-0085 was added on 2026-09-06** (row H4, found by running integration verification I18 rather
than by planning it). [ADR-0022](0022-capability-evidence-record-contract.md) §3's uniqueness keys
predate the adapter axis, so a base and every adapter subject on it collapse to one key: a real
FreeWeight `1.1` bundle carrying three subjects' records imported **one** and had two rejected as
duplicates. The importer was right — refusing to merge two measurements is the rule — and the key
was stale. It is the blocker for I18, and it sits one step *before* the registry gap row H2's
handoff predicted: these records never reach binding at all.

**ADR-0086 was added on 2026-09-06** (row H5, kickoff §0.1 — found by reading
[ADR-0085](0085-the-evidence-uniqueness-key-carries-the-adapter.md) against LoadCoach's actual write
path before implementing it). ADR-0085 spelled the consumer's new key column nullable, which is
correct for FreeWeight's delete-then-insert writer and wrong for LoadCoach's: the consumer writes
`capability_evidence` through `weightsdb.upsert`, an `INSERT … ON CONFLICT` whose conflict target
**never fires on a `NULL`**, so a nullable key column would insert a second row on every re-import
of a bare-base record — silently, and for ever. The column is `NOT NULL` with `''` for the bare
base, which is the sentinel [ADR-0080](0080-a-persisted-decision-names-the-subject-by-reference-and-by-string.md)
rule 5 already chose for the same reason in the same application. The two applications therefore
spell one field differently, on purpose, and nothing crosses the wire either way.

**ADR-0087 and ADR-0088 were added on 2026-09-06** (row H6, from the H5 interview), and both come
from one live failure that neither handoff predicted. Under a profile weighting `reliability`, two
adapters whose manifests merely *declared* the capability scored `0.500 declared` and outranked the
bare base, whose real measurement had been excluded as `evidence_profile_mismatch` and scored
nothing — a claim beating a measurement, with `require_adapter_evidence` silent throughout.
**0087**: the gate read `subject.signals`, the raw list, so a signal that scoring then excluded
still satisfied it; it now reads the *resolved* capability score, so the gate and the scorer cannot
disagree about what counts as measured, and the `adapter_unmeasured` rejection carries the resolved
source, both hashes and the remedy instead of saying only "no measured evidence". **0088**: the
other half — an excluded measurement was returned *before* the parameter-band prior, so a subject
somebody had benchmarked scored strictly worse than one nobody had ever measured. It now scores the
prior it displaced and keeps its own name, note and remedy, so the explanation is unchanged and the
penalty is gone. Neither record weakens ADR-0017's or ADR-0023 §3's hard separations, and both
landed inside the unpublished `loadcoach 1.1.0`.

**ADR-0089 was added on 2026-09-06** (row H6, from the operator interview that closed it), and it
is the one decision in that row taken from a measurement rather than from a defect. A deliberately
damaged LoRA loses the instruction *to stop* along with every other instruction, so the A-2
regression panel — built to catch exactly that adapter — generates to the served context on every
case and takes forty minutes instead of one. The two fixed rows now carry a per-turn cap of 512
tokens, part of the panel's definition and versioned with the catalogue rather than configurable,
because a subject measured at 512 and one measured at 4 096 have not been measured the same way.
Nothing else in the panel is capped: a number chosen for a three-word-answer suite would truncate a
long-context benchmark and record the truncation as a capability loss. A sample that ends at the cap
is scored as the non-compliant answer it is, which sharpens rather than distorts what
`native.instruction_following` already measured.

**ADR-0090 to ADR-0094 were added on 2026-09-06** (row I1, PromptCadence Phase 8). They are the
five decisions the phase had to take before it could write the code they govern, and each one
closes a place where a built fact pulled against a specified sentence. **0090**: lifecycle §7 asks
for the compaction summary to run on "the cheapest admissible local tier", but a tier is
configuration over one task profile and no configured tier names `general.summarize`, so the
summary now runs under a *superseding revision* of the step's own intent — narrowed to that tier,
no fallbacks, no tools, the step's classification ceiling carried — with a second supersession
restoring the step's envelope. **0091**: the same turn is debited against every ceiling and does
**not** count against `max_turns`, which is the step's advance budget; the separation is
structural, because the summary lives in its own thread and would otherwise be replayed into the
transcript it replaced. **0092**: Phase 8 ships the invalidation entry point and its revision bump,
and does not ship the retention sweep that Phase 9 specifies — the entry point is tested by
scrubbing the fixture's rows directly. **0093**: materialization runs immediately *after* the
terminal transition rather than inside its transaction, because two seconds of composition inside
a write is two seconds of lock, and a missing revision is not a missing explanation — the live
composition path serves it and `rebuild-explanations` fills it in, which is what makes the
revision a genuine cache. **0094**: the console authenticates exactly as the API does, adds no
session cookie, and wires MirrorWall's double-submit CSRF in the same commit that renders the
first form, retiring `web/app.py`'s "there is no HTML UI yet" deferral.

**ADR-0095 to ADR-0098 were added on 2026-09-06** (row I2, PromptCadence Phase 9 — the 1.0
hardening). **0095**: a prompt-injection corpus case asserts a model-independent property of the
harness — which tool ran, what the workspace holds, which `EgressDecision` was written — and never
what the model said; it runs in CI against the fake and is the release gate, and a live pass is
evidence, not the gate. **0096**: the hazard G2 moved rather than removed — model-chosen tool
arguments replayed onto the wire uncapped — is bounded at ToolYard's own record bound, with the
record's size-and-digest object standing in for oversize arguments, so the wire and `args_json`
agree by construction and nothing is truncated mid-string. **0097**: every spec §15 budget is a
`performance`-marked test whose median must not exceed the **ceiling**; the target is reported,
never asserted, and a missed ceiling is a finding rather than a wider number. **0098**: 1.0 ships
with I13's recorded-transport half proven in CI — the remote-provider fact read from LoadCoach's
`is_remote`, never inferred from a kind — and the live remote run deferred; a remote tier refuses
honestly, naming `loadcoach_has_no_remote_provider` or `unpriced`, until an operator meets both.

**ADR-0099 was added on 2026-09-06** (row I3, LoadCoach 1.1.1). It closes the two halves of one
patch release: `GET /models` renders `provider_name` and `is_remote` under the names the generate
response already uses, so ADR-0098 rule 1 reads a true fact from a real LoadCoach without a
PromptCadence change; and `TaskProfileExecution.think` — ModelRack's name and its three states,
overridable by `sampling.think` — makes the thinking control G2 could only name reachable from
configuration. A set `think` requires `thinking_control` of every candidate at routing, rejected
as `capability_unsupported` with `required_by`, and travels beside `requires_capabilities` rather
than inside it, because that field is validated against the SetSpec vocabulary and
`thinking_control` is a provider flag rather than a capability.

**ADR-0100 was added on 2026-09-06** (row I5, PromptCadence 1.1.0). It fills the runtime-settings
hole spec §7.1 had promised since the specification was written: five tuning numbers move at
runtime — the retention hours, the compaction threshold, the two execution bounds and the
planner's corrective retries — and everything that decides exposure, egress, credentials,
containment, retention or spend is refused by name with `FORBIDDEN`, whole sections at a time. The
budget ceilings are refused deliberately: a form that raised one would be a second path to the
same money with no `approval_requests` row behind it, beside the `ceiling_raise` approval that
records an approver. Membership is tested by re-reading, not by plausibility — a key the running
process does not re-read is not runtime-changeable — and precedence follows configuration
standards §7 rather than LoadCoach's implementation, so the environment still beats a stored row
and a shadowed row is shown as shadowed instead of being applied or dropped in silence.

**ADR-0101 was added on 2026-09-07** (row I8/I9, LoadCoach 1.1.2). It names a shape the
configuration standards never described and LoadCoach has shipped since P5: a runtime-changeable
setting that is **not** a configuration key. `queue.paused` and `queue.draining` live only in the
`settings` table — `QueueSettings` has no such fields — so they have no environment variable, no
row in the generated reference, and a `LOADCOACH_QUEUE__PAUSED` is refused by the loader as an
unknown key rather than shadowing a stored row. The one precedence rule applies to them unchanged
and costs nothing, the reference's header now says they exist and why its tables cannot list them,
and the test for admitting another is whether setting the key in `config.toml` would mean
anything: a pause is operational state, a threshold is configuration. Adding the two to the
settings model for uniformity was refused — it would create the shadowing hazard they are
currently immune to. (This row also added 0100's missing index row.)

**ADR-0102 was added on 2026-09-07** (row I8/I9, FreeWeight 1.1). Three applications serve a
runtime-settings surface built on one idea and no shared code, and FreeWeight's wire shape was the
odd one out: `{items: [...]}` with `stored_value`/`overridden_by_env` against LoadCoach's and
PromptCadence's `{settings, definitions}` with `stored`/`shadowed_by`. Rewriting it was forbidden
— ADR-0013 makes changes additive-only inside a major version — so the body now carries **both**:
the suite's shape is added, `items` is unchanged and deprecated, and it goes when FreeWeight next
needs an `/api/v2`. `configured` became answerable again by keeping the loaded settings pristine
beside the applied ones, and `settings` applies the stored row at read time rather than reporting
what was folded in at startup, which is where the two renderings can honestly disagree.

**ADR-0103 was added on 2026-09-07** (row J1, IdeaPress's LoadLedger and Commissioner adoption).
Both packages are correctly inert — LoadLedger reports `exceeded` and decides nothing, Commissioner
records a verdict and enforces nothing — which leaves two questions only IdeaPress can answer,
answered here: a bound `per_output` ceiling pauses the in-flight unit, reusing the pause/resume
arrow an exhausted output budget already takes, rather than raising through a funnel three call
sites (two of them row J2's, untouched by this row) do not expect to fail; and a remote backend
with no declared `max_data_classification` is denied, fail closed, which is a genuine behaviour
change for an existing remote configuration that named no ceiling — the call still proceeds exactly
as before (Commissioner does not enforce; IdeaPress's own `providers.allow_remote` gate is
unchanged), but the record now shows a denial where it previously showed nothing at all. The record
also raises IdeaPress's own `setspec` floor to `>=0.5,<0.7` to match what `commissioner 0.1.1`
itself requires, closing the same "one repo's floor is another's ceiling" trap row E5 closed for
`mirrorwall`.

**ADR-0104 was added on 2026-09-07** (row J2, IdeaPress's CutCtx adoption). CutCtx's spec has
named IdeaPress's stage-context reduction as an adoption target since before CutCtx existed, but
neither document said what happens at the seam between the two — only at each side of it
separately. The record settles three things the adoption forced: `cutctx` types stay inside
`domain/context_assembly.py` rather than reaching `AssembledContext`'s callers, so the same shared
package can back two different public seams without either seam becoming the other's business;
`CompactionBudget.protected_recent_turns` is fixed at `0` and the untouchable set is expressed
entirely as `pinned`, because IdeaPress's undroppable sections are named, not a tail; and
`cutctx.BudgetUnsatisfiable` is translated into `ContextLimitExceeded` at that boundary rather than
let through, so a shared package's adoption does not silently change a caller's own error
contract. `_rank_of` and `_priority_key` survive the adoption in a narrower role — positioning
sections for CutCtx's policy to decide, then re-presenting what it decided — which the ADR records
so a reader does not mistake "the decision code goes" for "the function goes".

**ADRs 0105 to 0109 were added on 2026-09-07**, out of an audit of the whole set rather than out of
a build. Its finding was one failure repeated: a decision that was taken, argued and confirmed by
the operator, and then left out of the ADR set because the row that found it was scoped to
something else. Three of the five therefore write down an answer that already exists in the tree;
two settle a question the tree answers three different ways.

**ADR-0105** is the small record row C6's handoff asked for and no row owned. LoadCoach's `usage`
object renders `"unsupported"` on `cache_write_tokens`, `cache_read_tokens` and `thinking_tokens`
and `null` on `input_tokens` and `output_tokens`, in one object, for the same condition — and
[ADR-0016](0016-unavailable-is-not-zero.md) rule 4 forbids the second spelling in as many words.
The two older fields shipped in `loadcoach 1.0.0`, so changing their type is exactly what
[ADR-0013](0013-api-versioning.md) makes a major change; the divergence therefore stands, is named,
and ends at `/api/v2` where all five use one spelling. What the record adds beyond the exemption is
the consumer's rule — `null` on those two keys is *unavailable*, never zero — and a sentence
placing [ADR-0070](0070-an-absent-token-class-is-zero-only-where-the-protocol-cannot-bill-it.md)'s
carve-out beside it, so a reader who arrives at ADR-0016 through its header can learn from the
records alone when a zero is legitimate.

**ADR-0106** writes down two readings the operator confirmed on 2026-09-04 and explicitly declined
to have amended into their records at the time. The `Provider` protocol gained `list_adapters()`
and `register_adapters()`, against [ADR-0062](0062-llamacpp-serves-adapters-through-a-supervised-process.md)
decision 1's "the `Provider` protocol does not change", because the alternative is LoadCoach
`isinstance`-checking `LlamaCppProvider` wherever an adapter row is rendered or a rescan folded in —
importing a concrete adapter into the application the protocol exists to keep provider-agnostic.
Decision 1 is narrowed to the load/unload seam it was actually about, where it remains true and no
lifecycle method was added. And [ADR-0063](0063-one-adapter-at-a-time.md) rules 1–2 are read as
governing *enabled* entries: the wire sends every registered adapter, the selected one at `1.0` and
the rest explicitly at `0.0`, because `b10792`'s llama-server restores the launch-time set for a
request that names none — so an absent field would run the bare base under *every* adapter. At most
one is ever enabled, at exactly `1.0`, and a server with no adapters registered still sends no
`lora` key.

**ADR-0107** answers a trigger that fired and was never called. [ADR-0011](0011-shared-package-boundaries.md)
promised `LoadCoachClient` the moment a second consumer of LoadCoach's API appeared outside
IdeaPress, and [ADR-0045](0045-promptcadence-reaches-models-only-through-loadcoach.md) created one
deliberately; the record still describes IdeaPress's adapter as "~200 lines" against a tree holding
1 422 and 1 291. Extraction is **declined** anyway, for a reason the original rejection could not
have anticipated: the two clients diverge in what they bind — stage bindings, adapter pins and a
degradation vocabulary on one side, turn provenance, a strict parser and an error map on the other
— neither is thin, and the package would be a third API surface to version between two applications
that already track LoadCoach's directly. The new trigger is a third consumer, or the day LoadCoach's
OpenAPI document carries typed response bodies.

**ADR-0108** closes the one cross-cutting promise the standards make and the code does not keep. G6
says "API bodies contracted by the committed OpenAPI snapshot"; testing standards §8.4 describes
package-data snapshots, an `api_snapshot()` accessor and a schema-driven mock. None of it exists,
and none of it could work: LoadCoach's committed document describes no body at all for 32 of its 49
JSON responses, so a mock validated against it agrees with anything — which IdeaPress discovered
through three M8 defects and wrote up in a test docstring. The snapshot contracts the **surface**
(paths, methods, parameters, closed request schemas, status codes) at `docs/openapi.json`, compared
byte for byte; response **bodies** are contracted by goldens captured from a running producer plus
each consumer's contract tests. The three standards were corrected in the same commit. IdeaPress
commits no snapshot at all and owes one; a scheduled row carries it.

**ADR-0109** settles the two behavioural questions row I8/I9 recorded as findings. A stored
settings row this build cannot read is *a row this build cannot read*: the application serves the
configured value, reports the row and the reason on the settings surface, logs it once, keeps the
row, and never refuses to start — because a tuning number written by an older build must not stop a
process from serving, and a clamped or deleted row is indistinguishable from one somebody chose.
And the runtime-changeable set is an explicit enumeration: a key absent from the registry is
config-only, so a security-relevant setting nobody remembered to forbid falls closed, with the
named `FORBIDDEN` refusals a diagnostic layer above that fence rather than the fence itself. All
three applications already implement the enumeration; the log-once clause is met by FreeWeight
alone, and the surface-reporting clause by none — LoadCoach and PromptCadence render
`source: "database"` for a row whose value never took effect, which the record names as owed work
rather than describing as done.

**ADR-0111 was added on 2026-09-07** (the operator's interview). M11's exit condition had named a
podman host that never existed, and the milestone stayed formally open under a shipped beta and a
shipped 1.0. The record makes the exit "the container rung exercised on the reference machine's
runtime" — docker, done at E4 — declares M11, keeps ToolYard's probe order and its honest skip
unchanged, and hands the podman canary to whoever first installs podman beside the suite.

**ADR-0112 was added on 2026-09-07**, the same day as ADR-0105 and reversing it. The operator
found, hours after accepting ADR-0105, that `/api/v1` has no consumer yet — so the wall ADR-0105
built around `input_tokens` and `output_tokens` was protecting nobody. ADR-0112 supersedes it in
full: both fields render `"unsupported"` for an unreported count, like the other three token
classes, from `loadcoach 1.1.3`, closing ADR-0016 rule 4's exception rather than carrying it to a
`/api/v2` that nothing forces into existence. It is explicit that this is a one-time exception to
[ADR-0013](0013-api-versioning.md), argued on today's specific fact (no external consumer, both of
the workspace's own checked directly) and not a general license to break a released field — the
next such change still owes `/api/v2` or an equally explicit exception argued on its own facts.

**ADR-0110 was added on 2026-09-07** (row K4). [ADR-0072](0072-the-model-pricing-record-file.md)
fixed the price-catalogue format and left the reader in its first consumer, naming the trigger that
would move it: a second consumer needing the reader itself. Row J1 fired that trigger by
transcribing PromptCadence's 368-line module into IdeaPress as 315 lines that differed in the
docstrings, the application error raised and the container shape — and in nothing that parses. The
record puts the reader in `loadledger.pricing`, because LoadLedger already stores the
`pricing_hash` the reader's output is joined by and already decides what an untotalled estimate
means to a ceiling; `baseaicore` was declined because it would have to break its no-I/O rule to
take it, and a package of its own was declined for being a repository and a release series around
250 lines. Each application keeps its edge — where the path comes from, and reporting a broken file
in its own configuration vocabulary. The proof is that both applications' pricing tests pass
unchanged, plus a golden case in the package asserting the moved reader reproduces the exact
`pricing_hash` values both loaders produced before adoption.

**ADR-0113 was added on 2026-09-07** (row L2), out of the M9 audit's item O3 — the one item the
audit named an architect's decision it could not make. `master-roadmap` §6 promised every original
package a **1.0** in its M9 column; all ten packages sit at `0.x`, and closing the gap by bumping
them would mean ten releases, four ceiling widenings and four lock recompiles in the same week the
job that would prove any of it (the cross-repository compatibility matrix, row L6) still does not
exist. The record keeps the packages at `0.x`, makes 1.0 a per-package thing earned by two
breaking-change-free minors **and** a matrix green on both ends of every declared range, and
restates M9's O3 as that matrix property rather than as ten version numbers. It is written as the
**coordinator's recommendation on the operator's authority**, and says so in its Status: the
operator may still overrule decision 1, in which case the record's criteria are what the bump has
to satisfy or explicitly waive. Two facts corrected the audit's framing on the way: ToolYard has
one in-suite consumer, not two, and SetSpec's frozen *payloads* are not its *package* surface —
which is why the "bump only the frozen one" option loses.

**ADR-0114 was added on 2026-09-07** (row L2), out of the same audit's G16 finding. `gold-standards`
§1.1 allowed each application six direct non-suite runtime dependencies and MirrorWall two; the four
applications declare nine or ten and MirrorWall three, with no ADR justifying any of it. Reading
every `pyproject.toml` settled which way the discrepancy pointed: every name but one is imported by
the component declaring it, and three of them (`pydantic`, `sqlalchemy`, `alembic`) are declared
*because* they are imported even though they also arrive transitively — which is packaging
correctness, not appetite. So the budget becomes the enumerated set, a count becomes a consequence,
and G16's rule ("a new name needs an ADR") is untouched. The one name that does not survive the read
is `pydantic-settings`: all four applications declare it and none imports it, because each
`config.py` merges its own layers so `config show` can name the layer every value came from. §1.1
lists it as declared, unapproved and owed removal rather than pretending either way. The gate — a
test comparing `pyproject.toml` against the table — exists in three repositories and is owed by
eleven.

**ADR-0115 was added on 2026-09-07** (row M3), out of the L8 finding that `apps/ideapress/spec.md`
§16 promised an optional telemetry display nothing had built: `show_telemetry_bar`
(`web/rendering.py`) was a hard-coded `False` never wired to a `TelemetrySnapshot`, and
`sweatmeter`'s only real use was already a presence probe for the VRAM-preflight capability flag.
The row offered a build-or-remove choice; the coordinator chose removal, because IdeaPress does not
schedule or measure work on the machine itself — every call either serialises and unloads locally
(ADR-0038) or routes through LoadCoach, which owns the machine's telemetry surface for what it
accepts (ADR-0040) — so a second bar would show a state IdeaPress never acts on. The flag and its
dead branch are deleted; the `[telemetry]` extra and its presence probe survive for the VRAM
preflight, which is a real, tested capability flag; and `graceful-degradation.md`'s three affected
rows move from `untested` to `n/a — ADR-0115`.

**ADR-0116 was added on 2026-09-08** (row M1), the record workflows §2 said would decide the
`research` stage's binding when a research backend finally shipped. Its binding is `toolyard`:
IdeaPress becomes the package's second consumer, executing `read_file` and `http_fetch` through one
`ToolExecutor` per stage run rather than writing a second `httpx` fetch loop with a second, subtly
different reading of ADR-0026 §3. Four things in it are decisions rather than transcription. The
allowlist defaults **closed** and an empty `[research] allowed_hosts` means the fetch tool is not
registered at all — deliberately *not* ToolYard's own "empty means loopback", which for an
application holding the user's drafts would let a URL in a brief reach a service on their own
machine. Containment is `PathContainment` rather than `TieredSandbox`, because neither registered
tool runs a subprocess and a probe that launches a canary would buy nothing. A research note is a
`sources` row — the table `fact_check` has read since P1 and nothing has ever written — rather than
a new table, which is what makes the stage's output reach grounding, export and context assembly
without a union. And the egress verdict is rendered per host **before** the executor is entered and
enforced by the invocation's `max_egress`, so a denied host leaves both an `egress_decisions` row
and a `tool_call_records` row and raises nothing (ADR-0073, ADR-0103 decision 2, fail closed).

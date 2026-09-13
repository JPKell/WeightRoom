# ADR-0144 — FreeWeight keeps several provider profiles and runs exactly one

**Status:** Accepted (2026-09-12)
**Amends:** [ADR-0077](0077-a-named-provider-block-and-the-singular-block-are-one-registry.md) —
that record's rules stand unchanged for LoadCoach, whose named blocks are *registrations in a
routing pool*. This record adds the second, different meaning the same TOML shape carries in
FreeWeight, where the named blocks are *saved profiles* and exactly one of them is in use.
**Relates to:** [ADR-0117](0117-provider-registrations-are-edited-in-place-in-the-config-file.md)
(the provider block is edited in place, comments kept, validate before write),
[ADR-0127](0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)
(the settings-schema document WeightRoomGym renders the profile cards from),
[ADR-0019](0019-python-baseline-and-config-format.md) (config is TOML),
[FreeWeight Spec §12](../apps/freeweight/spec.md) (configuration).
**Source:** Row WX13 of [`roadmap/wx-console-ux-work.md`](../roadmap/wx-console-ux-work.md), from
the operator's request list of 2026-09-12.

## Context

FreeWeight has one provider. [ADR-0077](0077-a-named-provider-block-and-the-singular-block-are-one-registry.md)
gave LoadCoach a named registry and FreeWeight's `ProviderSettings` docstring recorded the
divergence deliberately: "One provider, not a registry. FreeWeight measures one machine's models
one run at a time: it has no candidate pool and no scoring, so it has nothing to disambiguate
between registrations."

That reasoning is still correct and this record does not reverse it. What it missed is that the
operator's *switching* cost is not the registry's cost. On the reference machine the two providers
that matter — Ollama, and llama.cpp over a directory of GGUF weights — need **disjoint keys**:
`base_url` for one, `model_directory` / `server_path` / `state_dir` / `memory_max_bytes` for the
other, and a `[runtime]` block whose `flash_attention` and `kv_cache_precision` are refused
outright under `kind = "ollama"` (ADR-0120 rule 4). Switching from one to the other is therefore
not an edit of one key; it is a rewrite of the block, with the keys of the provider being left
behind either deleted or left in the file as lies. The operator does this repeatedly — every
serving-mode A/B of the adapter arc is exactly this switch — and each time the *other* provider's
settings, which were correct and measured, are destroyed to make room.

A saved profile is the smallest thing that fixes that, and it is not a registry: nothing is
scored, nothing is routed, nothing is discovered across profiles. One profile is in use and the
rest are text in a file.

## Decision

**FreeWeight's configuration carries any number of named provider profiles, and `[provider]
active` names the one it runs. The block that exists in every file today is itself a profile, so
no existing configuration changes meaning.**

1. **`[providers.<name>]` is a provider profile** — the same keys as `[provider]`
   (`kind`, `base_url`, `timeout_seconds`, `model_directory`, `state_dir`, `server_path`,
   `memory_max_bytes`, `memory_high_bytes`), validated by the same model. Its `kind` is one this
   build can construct — `ollama`, `llamacpp` or `fake` today; `openai_compatible` remains a
   `ProviderKind` with no adapter wired in FreeWeight, and naming one is still a configuration
   error rather than a silent fallback. It shares the `[providers]` table with the existing
   cross-provider policy key `allow_remote`, exactly as LoadCoach's registrations do: a key under
   `[providers]` is either `allow_remote` or a profile table, and a scalar that is neither is
   refused by name rather than ignored.

2. **The `[provider]` block is the profile named `default`.** Not "sugar for", not "migrated to" —
   it *is* that profile, read where it has always been read. A file with `[provider] kind =
   "llamacpp"` and nothing else has exactly one profile, named `default`, and runs it. A file with
   no `[provider]` block at all has a `default` profile made of the model's own defaults, which is
   the Ollama endpoint such an installation runs today.

3. **`[provider] active` names the profile in use, and defaults to `"default"`.** Adding
   `[providers.fast]` to a file therefore changes nothing about what runs; a second edit —
   `active = "fast"` — is what switches the application. Setting `active` to a name no profile
   carries is a `ConfigurationError` at startup that lists the names that exist.

4. **`[providers.default]` beside a `[provider]` block that sets any key is refused**, naming both
   — they are two definitions of one profile. This is the only refusal, and it is
   [ADR-0077](0077-a-named-provider-block-and-the-singular-block-are-one-registry.md) rule 3's
   reasoning applied to the one case where it still bites: a name collision. The general
   both-forms refusal that record imposed on LoadCoach is **not** carried over, because the hazard
   it defends against does not exist here. In LoadCoach both forms contribute registrations to a
   pool, so a forgotten `[provider]` block silently adds a candidate; in FreeWeight `active` names
   the one profile that runs, in the file, in the operator's own words. There is no silent
   precedence rule to get wrong.

5. **The effective profile is resolved once, when the configuration is validated**, and
   `Settings.provider` *is* that profile. Every existing reader — `build_provider`, the health
   check, `runtime.refused_under(provider.kind)`, the CLI, the scheduler — keeps reading the one
   attribute it always read and is correct without knowing profiles exist.
   `Settings.providers.profiles` carries every profile beside it, `default` included, for the
   settings document and the UI. The resolution happens again wherever the file is re-read, which is
   [ADR-0117](0117-provider-registrations-are-edited-in-place-in-the-config-file.md)'s
   reload after a provider write and nowhere else: switching `active` needs a restart, like every
   other non-runtime key (ADR-0127 rule 5).

6. **FreeWeight's own `PUT /provider` and Provider page edit the active profile's table**, not
   `[provider]` unconditionally. An operator running `active = "fast"` who edits `base_url` on
   that page means `[providers.fast] base_url`; writing it to `[provider]` would edit a profile
   they are not running. The page names the profile it is editing. `active` itself is **not** in
   that page's writable set: switching provider is a restart, and the page's contract is a write
   that takes effect on the spot.

7. **The settings-schema document states the profiles**
   ([ADR-0127](0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)
   rule 1), so the console renders them without knowing a key: `provider_profiles` carries the
   key that selects (`provider.active`), the active name, the kinds this build can construct, and
   one entry per profile with its name and the dotted prefix its keys live under (`provider` for
   `default`, `providers.<name>` for the rest). `security_keys` gains each profile's own
   `base_url`, for the same reason `provider.base_url` has always been in it — it decides where
   prompts are sent — and `provider.active` joins it too, because switching profile redirects every
   prompt at once, which is the same act.

8. **A profile is configuration, not a measurement subject.** Nothing about a profile enters a
   run's identity, a hash, or the evidence: what a run records is what it always recorded — the
   provider `kind` and version on the descriptor, and the runtime profile that served it. Two runs
   on two profiles of the same kind at the same settings are the same measurement, and naming the
   profile in the result would make them look like two. The profile's *name* is never persisted.

## Alternatives considered

**Leave it at one provider; the operator keeps two config files and `--config`.** Free, and it is
what the operator does today. Rejected because it splits every other key too: two files drift on
`benchmarks.max_fit_context_tokens`, on `[judge]`, on `auth.tokens`, and a measurement taken under
the wrong copy is indistinguishable from one taken under the right one. The provider is the part
that differs; the rest must not be duplicated to say so.

**Adopt ADR-0077 wholesale — a registry, `[provider]` read as a registration named after its
kind.** Rejected on rule 2's own ground, inverted: LoadCoach names the singular block after its
kind because the name appears in explanations and routing decisions, where `ollama` says something.
FreeWeight's profile name appears in one place, the settings page, where it labels *a saved set of
settings*, and a profile named `ollama` that an operator later points at a llama.cpp server is a
worse lie than one named `default`. A registry would also have to answer what FreeWeight does with
two registrations at once, and the answer is nothing: it runs one.

**Make `active` a runtime-changeable key (`PUT /settings`), so the switch needs no restart.**
Tempting, and rejected: the provider handle is a supervised `llama-server` process holding the
card (`close_provider`'s reason for existing). Swapping it under runs in flight is not a settings
change, it is a restart with extra steps — and the one path that does rebuild the handle,
ADR-0117's provider write, already exists for the operator who wants it without a unit restart.

**Refuse `[provider]` and `[providers.<name>]` together, as ADR-0077 rule 3 does.** Rejected under
rule 4 above: the refusal exists there to prevent a silent pool member, and there is no pool here.
Carrying it over would mean an operator cannot add their second profile without in the same edit
moving the first one — a two-step migration of a file the suite otherwise refuses to rewrite for
them ([ADR-0077](0077-a-named-provider-block-and-the-singular-block-are-one-registry.md)'s
auto-migrate rejection), and a console "add a profile" button that has to rewrite the operator's
`[provider]` block to work at all.

**Name the profiles in the run record, so evidence says which profile produced it.** Rejected by
rule 8: it would make a rename look like a new subject, and every existing result — recorded
before profiles existed — would be missing a field that decides nothing.

## Consequences

* Every FreeWeight configuration that exists starts unchanged and resolves to a byte-identical
  provider: the reference machine's bare `[provider] kind = "llamacpp"` file is profile `default`,
  active, with nothing added to the file. Asserted by a test written against that exact shape, not
  argued.
* The operator keeps an Ollama profile and a llama.cpp profile, both correct, and switches with
  one key. The serving-mode A/B of the adapter arc (ADR-0078, rows H4–H6) stops destroying one
  provider's settings to run the other.
* WeightRoomGym's settings page grows a card per profile with an *Active* radio, generated from
  the document like everything else on that page; the switch is a security-key write, so it is
  re-authenticated and audited (ADR-0127 rule 6), and it is followed by a restart (rule 5).
* `config show`'s per-leaf source for a `provider.*` key says which profile table answered, so a
  value that came from `[providers.fast]` is not reported as a default.
* The two applications now read the same TOML shape with two meanings — a pool in LoadCoach, a
  saved set in FreeWeight. That is a real cost, paid deliberately: the alternative is a second
  spelling of the same thing in one suite, and `[providers.<name>]` is the spelling an operator
  already knows.

## Revisit when

**FreeWeight needs two providers at once** — a run that measures the same model on Ollama and on
llama.cpp as one unit of work, rather than two runs an operator compares. That is a scheduler
change, not a configuration change, and it would make profiles a pool after all: at that point
this record and [ADR-0077](0077-a-named-provider-block-and-the-singular-block-are-one-registry.md)
should be reconciled into one, rather than kept as two readings.

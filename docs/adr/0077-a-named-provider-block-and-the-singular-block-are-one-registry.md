# ADR-0077 — A named provider block and the singular block are one registry, and both together is a refusal

**Status:** Accepted (2026-09-05)
**Amended by:** [ADR-0144](0144-freeweight-keeps-several-provider-profiles-and-runs-one.md) — for
one application, FreeWeight, `[providers.<name>]` blocks are *saved profiles* of which `[provider]
active` runs exactly one, the `[provider]` block is itself the profile named `default`, and the two
forms together are refused only on a name collision; every rule here is unchanged for LoadCoach,
whose named blocks remain registrations in a routing pool.
**Extends:** [ADR-0055](0055-loadcoach-registers-providers-by-name-and-kind.md) (LoadCoach
registers providers by name and kind), [LoadCoach Spec §12](../apps/loadcoach/spec.md)
(configuration).
**Relates to:** [ADR-0019](0019-python-baseline-and-config-format.md) (config is TOML),
[ADR-0013](0013-api-versioning.md) (additive within `/api/v1`),
[Configuration Standards](../standards/configuration-standards.md) (defaults → file → environment
→ CLI, field by field).
**Source:** Row H2 of [`roadmap/outstanding-work.md`](../roadmap/outstanding-work.md), decision 1
of its kickoff §0.2.

## Context

[ADR-0055](0055-loadcoach-registers-providers-by-name-and-kind.md) decided *that* LoadCoach
registers providers by name and kind. It said the existing single `[provider]` block "remains valid
and is read as one registration", and stopped there. That sentence is a compatibility promise, not
a migration path, and the gap between the two is where the actual decisions live: what the single
block's registration is **called**, what its `remote` flag is when it declares none, and what
happens to a configuration that writes both forms.

LoadCoach 1.0 is published and installed. Its shipped example configuration writes
`[provider] kind = "ollama"`, and `loadcoach config init` has been writing that block since Phase 1.
Every existing deployment has one. A 1.1 that only accepted `[providers.<name>]` would be a
breaking change to a released application inside a minor, which the suite does not do.

The failure worth designing against is not the missing block; it is the **half-migrated** one. An
operator who reads the 1.1 release notes, adds `[providers.local]`, and forgets to delete
`[provider]` has written a configuration with two truths in it. Any rule that silently picks one —
newest wins, named wins, singular wins — produces a running system whose model registry does not
match what its operator believes they configured, and the symptom surfaces much later as a routing
decision nobody can explain.

## Decision

**Both forms are accepted; the singular block is exact sugar for one named registration; a
configuration carrying both is refused at startup with a message naming the conflict.**

1. **The singular `[provider]` block is read as exactly one entry in the registry, named after its
   own kind.** `[provider] kind = "ollama"` is byte-for-byte equivalent to
   `[providers.ollama] kind = "ollama"` with the same `base_url` and `timeout_seconds`. The name is
   derived, not invented: an operator who never asked for names does not have to learn one to read
   their own explanations.
2. **A singular block declares `remote = false`.** It is the only honest reading — the shipped
   default is a loopback Ollama, and every deployment that has one today is local. An operator with
   a remote endpoint under `[provider]` must move to a named block to say so, which is the same act
   as opting in.
3. **`[provider]` and `[providers.<name>]` in one configuration is a `ConfigurationError` at
   startup**, naming both the singular block and every named block, and saying which to delete.
   There is no precedence rule, because a precedence rule is a silent answer to a question the
   operator did not know they had asked.
4. **`[providers] allow_remote` keeps its meaning and its place.** It is cross-provider policy — may
   *any* remote provider be routed to at all — and it is evaluated **above** a registration's own
   `remote` flag: `allow_remote = false` with a `remote = true` registration is a valid, running
   configuration whose remote models are all rejected by the existing `excluded_by_policy`
   constraint, exactly as a `false` `allow_remote_providers` on a task profile rejects them today.
   Two levels, both declared, neither inferred.
5. **The singular form is documented as supported, not deprecated.** It is the correct way to
   configure the single-provider deployment that remains the common case, and it carries no removal
   version. Deprecating it would tax every existing installation for the benefit of a shape they do
   not need.

## Alternatives considered

**Precedence: named blocks win, the singular block is ignored when both are present.** The smallest
possible rule, and every configuration system in wide use does something like it. Rejected on the
half-migrated case above: the operator who forgot to delete `[provider]` gets a working system that
is not the one they wrote, and nothing in the UI, the logs or `doctor` is obviously wrong. A refusal
costs that operator thirty seconds; a silent precedence costs the next person an afternoon.

**Merge the two: the singular block becomes a registration alongside the named ones.** Tempting
because it never refuses anything. Rejected because it is the same failure with an extra model in
the pool: the registry acquires a provider the operator thought they had replaced, its models enter
every candidate list, and an explanation names a provider that is not in the configuration the
operator is reading.

**Deprecate `[provider]` with a warning and a removal version.** The orthodox migration. Rejected
under [ADR-0055](0055-loadcoach-registers-providers-by-name-and-kind.md) rule 2's own reasoning: the
single-provider deployment is not a legacy shape to be retired, it is the majority shape, and a
deprecation warning on every startup of a correct configuration trains operators to ignore warnings.

**Auto-migrate the file: rewrite `[provider]` into `[providers.<kind>]` on first 1.1 startup.**
Rejected outright. The suite does not edit an operator's configuration file; a configuration is
something a person owns, diffs and puts under version control (the same property that puts prompts
and adapter manifests in files, [ADR-0012](0012-prompt-storage-format.md),
[ADR-0061](0061-the-adapter-registry-is-a-directory-and-a-manifest.md)).

**Name the singular registration `"default"` rather than after its kind.** Considered seriously, and
it reads better in the abstract. Rejected because the name appears in explanations, the models UI
and `doctor` output, where `ollama` tells an operator something and `default` tells them nothing —
and because two LoadCoach installations with different providers would both call theirs `default`,
which makes shared explanations harder to read, not easier.

## Consequences

* A LoadCoach 1.0 configuration starts unchanged under 1.1 and produces a byte-identical model
  registry — asserted by a compatibility golden, not argued.
* An operator migrating incrementally hits an error message rather than a mystery. The message names
  the singular block, the named blocks, and the one-line fix.
* `doctor` reports every registration by name with its own reachability, so "which provider is
  down" is answerable for the first time.
* Explanations, the models UI and `GET /models` gain a provider *name* beside the provider kind. For
  a singular configuration that name is the kind, so the display is unchanged in the common case.
* An operator can still misconfigure `remote = false` on a hosted endpoint —
  [ADR-0055](0055-loadcoach-registers-providers-by-name-and-kind.md)'s named footgun is untouched by
  this record, and its compensating control (PromptCadence's verification contract) is unchanged.

## Revisit when

A deployment needs **two registrations of the same kind at the same address** distinguished only by
runtime settings — two `llamacpp` providers on one machine serving different model directories, say.
That works today (names are operator-chosen and nothing keys on the kind), but if it becomes the
common case, the derived name for the singular block stops being obviously right and the question of
what a registration *is* deserves a second look.

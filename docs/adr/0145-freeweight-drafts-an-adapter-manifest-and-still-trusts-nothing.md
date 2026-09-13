# ADR-0145 — FreeWeight drafts an adapter manifest, and still trusts nothing

**Status:** Accepted (2026-09-12)
**Relates to:** [ADR-0061](0061-the-adapter-registry-is-a-directory-and-a-manifest.md) (rule 4,
whose actor this record widens), [ADR-0065](0065-an-adapter-is-classified-and-local-only.md)
(`data_classification` has no default), row WX7's kickoff and
`docs/roadmap/wx-console-ux-work.md` §1 rows WX7 and WX8.
**Source:** The operator's defaults at the WX arc's interview (2026-09-12): "the adapters page
gets a **Draft manifest** action (writes a draft for a person to review — ADR-0061's manifest
stays hand-reviewed)".

## Context

ADR-0061 rule 4 reads *"`loadcoach adapters scan` drafts; a human keeps"*. The drafting half was
given to LoadCoach's CLI and nothing else; FreeWeight's own directory reader says so in its module
docstring — *"FreeWeight writes no drafts"* — and lists the `*.manifest.draft.json` files it finds
only because an operator may be sharing one directory with LoadCoach.

That leaves an operator who works from the console in an odd place. FreeWeight's `GET /adapters`
already reports `unmanifested` artifacts by name: a GGUF dropped into the directory, present and
unusable. The next step — hash it, write a proposal, review it — exists only in another
application's CLI, on another application's configuration of the same path. The console cannot
offer it, and the operator is told what is wrong with no way to act on it.

## Decision

**FreeWeight may write a draft, and only a draft.** `POST /api/v1/adapters/{name}/draft` writes
`<name>.manifest.draft.json` beside the artifact. Four properties make it safe, and each is
enforced rather than documented:

1. **The suffix is the enforcement.** `read_directory` skips `*.manifest.draft.json` when it reads
   manifests, so a draft is never an entry, never a registration, never offered to a provider and
   never a benchmark subject. Keeping is still renaming the file, and only a person renames it.
2. **Nothing is overwritten.** A name that already has a manifest or a draft is refused
   (`409 DRAFT_REFUSED`). What a second draft would destroy is a person's review of the first.
3. **What FreeWeight cannot prove, it marks unproven.** The artifact's own SHA-256 is computed —
   that is the identity (ADR-0061 rule 5). The base is recorded at `name_only` confidence with no
   digest, because a base digest nobody verified is exactly the misattribution the whole design
   exists to prevent, and the base's *name* is a required field of the request: it is the one fact
   no reader of a GGUF can establish.
4. **The classification is the most restrictive one, not a default.** ADR-0065 gives
   `data_classification` no default so that a person chooses it. A draft must write something, so
   it writes `confidential` and says in `notes` that the reviewer sets it. The conservative value
   cannot leak anything by being wrong; a permissive one could.

ADR-0061 rule 4 is unchanged in substance and widened in actor: **two components draft, a human
still keeps.**

## Consequences

The claim "nothing here writes" in `infrastructure/adapters/directory.py` is now false and has
been corrected: the one write lives in `services/adapters.py::draft_manifest`, deliberately not in
the module that decides whether a manifest may be believed.

FreeWeight now writes into a directory it had only read. The directory remains the operator's: the
write is one file, under a suffix nothing trusts, refused when anything is already there.

An operator who shares one directory between FreeWeight and LoadCoach can now have drafts from
either. They are indistinguishable by design — a draft's authority is zero whoever wrote it — and
each draft's `notes` names its writer.

## Alternatives considered

**Leave drafting to `loadcoach adapters scan`.** It works, and it is what rule 4 says. Rejected
because it makes the console's adapters page a page that reports a problem and cannot act on it,
for a workflow whose only real step is "hash this file and write down what you know".

**Let FreeWeight write the manifest itself when it can verify the base.** It can sometimes: a base
model served by the configured provider has a digest FreeWeight has already recorded. Rejected —
"the adapter was trained against the base this provider happens to serve under a similar name" is
an inference, and ADR-0061's failure mode is confidently applying a LoRA to the wrong base. The
person reviewing the draft is the check, and a path that skips them for the easy cases skips them
exactly where a mistake looks plausible.

**A `freeweight adapters draft` CLI command instead of a route.** Cheaper, and it matches
LoadCoach's shape. Rejected for the console: WeightRoomGym drives applications over HTTP and never
shells into their virtualenvs. The service function is one call, so a CLI command remains a
half-hour's work if an operator ever wants it at the terminal.

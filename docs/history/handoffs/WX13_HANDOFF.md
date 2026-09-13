# WX13 Handoff — FreeWeight provider profiles

**Row:** WX13 (`roadmap/wx-console-ux-work.md` §1) · **Ran:** 2026-09-12, unattended, one sitting ·
**Model:** Claude Fable 5.1 · xhigh · **Kickoff:** `history/prompts/wx13-freeweight-provider-profiles.prompt.md`
· **Repositories:** FreeWeight, then WeightRoom · **Branches:** `row/wx13-provider-profiles` in
`~/ai/worktrees/freeweight-wx13` and in `~/ai/worktrees/weightroom-wx13` · **Not merged.**

## 1. What shipped

| Repository | Commit | What |
|---|---|---|
| FreeWeight | `5834046` | ADR-0144's configuration: `[providers.<name>]` profiles, `[provider] active`, the resolver, the two refusals, the document's `provider_profiles`, the active-profile write, the spec mirror, `CHANGELOG.md` |
| FreeWeight | `4df7602` | The document lists the `default` profile first |
| WeightRoom | `74cc100` | ADR-0144, the FreeWeight spec, the console spec §7.4 and api.md §2, the profile cards, the *Add a profile* form, the re-recorded fixture and golden, `CHANGELOG.md` |

## 2. The configuration shape, and the back-compat rule

```toml
[provider]                       # this block IS the profile named "default"
active = "served"                # which profile runs; the default is "default"
kind = "ollama"
base_url = "http://127.0.0.1:11434"

[providers]
allow_remote = false             # policy, unchanged

[providers.served]               # a profile: the same keys as [provider]
kind = "llamacpp"
model_directory = "~/ai/models/llm"
```

**The rule, in the order it is evaluated** (`Settings._resolve_active_profile`):

1. Every extra key under `[providers]` that is a table is a profile (`ProvidersSettings.
   _collect_profiles`, the same shape LoadCoach uses). A scalar extra is refused by name — a typo
   like `allow_remot = true` is not a profile. A profile table that sets `active` is refused: a
   profile does not choose itself.
2. `[providers.default]` beside a `[provider]` block that **sets any key** is refused, naming the
   keys it sets. That is the only both-forms refusal, and it is a name collision, not ADR-0077
   rule 3's precedence hazard (there is no pool here — see ADR-0144 rule 4 for why it does not
   carry over).
3. The `default` profile is filled in from the `[provider]` block. A file with no `[provider]` at
   all gets the model's defaults under that name, which is what such an installation runs today.
4. `provider.active` (default `"default"`) selects; naming no profile is refused **with the names
   that exist**.
5. `Settings.provider` is then **the resolved profile**, so `build_provider`, the health check,
   `runtime.refused_under(provider.kind)`, the scheduler, the CLI and ADR-0117's reload are all
   correct with no change: thirteen call sites, none touched. `Settings.providers.profiles` holds
   every profile beside it and `Settings.active_profile_name` is the name.

**Proved against the operator's own file.** `test_the_reference_machines_bare_provider_block_is_the_default_profile`
loads exactly the reference machine's shape — a bare `[provider] kind = "llamacpp"` with
`[runtime] context_size`/`fit_to_device` and no `active` — and asserts the resolved provider, the
profile list and the source layer. **No migration**: this is configuration, not schema. FreeWeight's
latest migration is still `0011`.

Two smaller decisions inside the rule:

* **`active` defaults to `"default"`, not `""`.** The console's radio always posts a value, and a
  field whose stored value is `""` while the document says `"default"` would count as a change on
  every unrelated save — writing `active` into the file and, because it is a security key,
  demanding the operator's password to change `execution.max_attempts`. One default value closes
  that; there is no special case in the console.
* **A `FREEWEIGHT_PROVIDER__*` variable while another profile is active is refused by name**
  (`_refuse_inert_provider_layer`, both loaders). The variable configures the `default` profile —
  it is not wrong, it is *inert*, and Configuration Standards §7 has the environment beating the
  file field by field, so silently doing nothing is the one outcome that cannot stand.
  `FREEWEIGHT_PROVIDER__ACTIVE` is exempt, since selecting is exactly what it does.

## 3. What else moved in FreeWeight

* **`config schema --json` states `provider_profiles`** (ADR-0144 rule 7):
  `{"key": "provider.active", "active": "<name>", "kinds": [...], "profiles": [{"name", "prefix",
  "kind"}]}` — `prefix` is `provider` for `default` and `providers.<name>` for the rest, and
  `kinds` is `SUPPORTED_PROVIDER_KINDS` (`fake`, `llamacpp`, `ollama`). The console needs nothing
  else to render the cards, and hardcodes no key.
* **`security_keys` gains each profile's `base_url` and `provider.active`.** A profile's endpoint
  decides where prompts go, and switching profile redirects every prompt at once. The list is
  per-configured-profile because the model cannot enumerate operator-chosen names.
* **`ProvidersSettings` types its extras in the JSON schema** (`_profile_valued`, copied from
  LoadCoach's WX9 fix): without it `extra="allow"` emits `additionalProperties: true` and the
  console files a profile's keys under `undescribed`.
* **`leaf_keys()` excludes `DERIVED_KEYS = {"providers.profiles"}`** — a path the model carries
  that no file writes. It would otherwise be a `config_only` key, a row in
  `docs/configuration.md` with an invented environment variable, and a field on the settings page.
* **`load_settings_tolerant` no longer strips `[providers.<name>]`** (the section validates its own
  extras — the same `allows_extra` branch LoadCoach has).
* **`config show`'s per-leaf source** names the profile a `provider.*` value came from
  (`file [providers.served]`), and every `providers.<name>.<field>` the file writes is reported as
  `file`. Without this a value the operator configured reads as *default* on the settings page.
* **`save_provider` writes the active profile's table** (`_active_block`), and the Provider page
  says which profile it is editing and how many there are. `active` stays outside
  `WRITABLE_FIELDS`: switching replaces a supervised `llama-server`, which is a restart.

## 4. The console

* `settings_forms.py` gains `SettingsForm.provider_profiles` (straight from the document),
  `provider_cards()` and `provider_keys()`. A card's fields are simply this form's fields whose
  key starts with the prefix the **application** stated; nothing here names a key.
* `_profile_keys()` adds every leaf the schema gives a profile prefix, so a card shows all of a
  profile's keys and not only the ones the file happens to name — which is what makes a profile
  added from the console editable in full without the raw editor. It also gives those keys their
  order slots, so a profile's `base_url` (which arrives with the security keys) sorts inside its
  own card rather than after it.
* `settings.html`: the per-field `<tr>` block is now a `field_rows(fields, form, app)` macro called
  by both a section's table and a card's; sections skip the keys the cards render
  (`rejectattr("key", "in", carded)`) and a section left with nothing is not drawn. The *Active*
  radio posts `field:<the document's key>` on the ordinary save.
* `POST /apps/{app}/settings/provider-profile` writes one key, `providers.<name>.kind`, through
  `apply_changes` + `write_config` — the application's own validation, the `.bak`, the mtime race.
  It needs no password (the only key written is `kind`; the endpoint is edited afterwards, under
  the security-key rule) and switches nothing. Name, duplicate and kind are refused with the
  reason, each as one audit row.
* The kind select's first option is a disabled blank: a select always posts its first option, and
  there is no kind worth choosing on the operator's behalf.

**Fixtures re-recorded** from FreeWeight at this row's commit, with the reference machine's own
file shape (a bare `[provider] kind = "llamacpp"`): `tests/fixtures/schemas/freeweight.json` and
`tests/fixtures/schemas/goldens/freeweight.txt`. The recording also picks up `console.url` and
`judge.max_output_tokens`, which the previous recording predated — the same thing WX9 saw with
LoadCoach.

## 5. Gates

* **FreeWeight** (`~/ai/worktrees/freeweight-wx13/.venv/bin/python`, CPython 3.14.4):
  `ruff format --check .` · `ruff check .` · `mypy src tests` (328 files) · `lint-imports`
  (4 contracts) · `pytest -q` → **2814 passed, 30 skipped, 31 deselected** in 264 s.
* **WeightRoom** (`~/ai/worktrees/weightroom-wx13/.venv/bin/python`, CPython 3.14.4):
  `ruff format --check .` · `ruff check .` · `mypy src tests` (234 files) · `lint-imports`
  (5 contracts) · `pytest -q` → **2008 passed, 3 skipped, 12 deselected** in 179 s.
* Two WeightRoom contract tests caught the new route and were satisfied, not weakened:
  `tests/security/test_audit_routes.py` needed an exercise for it (every state-changing route must
  leave exactly one audit row), and `test_openapi_snapshot.py` required it **out** of api.md's
  route table — it is a page form, like token minting, and is described in prose instead.

## 6. Screenshots

Taken from a throwaway console on `:8799` (its own XDG tree) whose `[apps.freeweight] executable`
is a wrapper around this branch's `freeweight` with its own XDG tree and a three-profile file
(`default` ollama, `served` llamacpp, `bench` fake). The operator's installation was never read or
written. `document.documentElement.scrollWidth > clientWidth` is **false** at both widths and both
themes.

`/tmp/claude-1000/-home-jpk-ai-suite/d363193a-9b7b-4805-ada9-e4a1e66fc4a0/scratchpad/shot/png/`:

| File | What |
|---|---|
| `settings-{1440,412}-{light,dark}.png` | The page |
| `cards-{1440,412}-{light,dark}.png` | The profile cards in place |
| `card-active-{1440,412}-{light,dark}.png` | The active card alone, badges and all |
| `add-profile-{1440,412}-{light,dark}.png` | The *Add a provider profile* form |

## 7. What is left

* **Nothing here is merged, pushed or tagged.** Both branches are committed:
  FreeWeight `5834046`, `4df7602`; WeightRoom `74cc100`.
* **The GPU gate is the orchestrator's** (row WX14). Nothing in this row touched the GPU, and the
  live switch is the one thing the tests cannot prove. Exactly:

  ```bash
  # 1. Give the operator's FreeWeight a second profile, from the console (:8769),
  #    /apps/freeweight/settings → Add a provider profile → name "served", kind "llamacpp".
  #    Then on the served card: model_directory = ~/ai/models/llm  (the password: it is not a
  #    security key, but base_url on the same save is — set only model_directory to avoid it).
  #    Restart FreeWeight from the page.
  systemctl --user restart freeweight            # or the page's Restart button
  curl -s localhost:8765/api/v1/provider | jq '.provider | {active, kind, profiles}'
  #    expect active "default", kind "llamacpp" (the operator's file today is bare llamacpp)

  # 2. One small suite on the profile that is active now, and keep the run id:
  freeweight run start --model <a small installed model> --suite native.latency
  curl -s localhost:8765/api/v1/runs/<run_id> | jq '.provider_kind, .runtime_profile'

  # 3. Switch from the console: the Active radio on the other card, the operator's password
  #    (provider.active is a security key), Save, then the page's Restart button.
  grep -A2 '^\[provider\]' ~/.config/freeweight/config.toml    # active = "<other>"
  curl -s localhost:8765/api/v1/provider | jq '.provider.active'

  # 4. The same suite again, and compare:
  freeweight run start --model <the same model> --suite native.latency
  #    Both runs must carry the provider kind of the profile that was active for them.
  #    `nvidia-smi` between them: no llama-server left holding the card after the restart.
  ```

  The two profiles on the reference machine are `ollama` and `llamacpp`, so step 1 should add
  whichever the operator's file is **not**.
* **`docs/adr/README.md` has no row for 0142–0145.** WX6, WX12, WX13 and WX7 all left the index
  alone rather than collide in one table; the merge should add four rows.

## 8. Decisions to review before merge

1. **`provider.active` is a security key** (ADR-0144 rule 7, `CONFIG_ONLY_KEYS`). Switching
   profile redirects every prompt to another endpoint, which is what `provider.base_url` is in that
   list for — but it does mean the operator types their password to switch, and the GPU gate above
   has to. If that reads as friction rather than a boundary, removing it is one line and the ADR
   rule with it.
2. **The both-forms refusal of ADR-0077 rule 3 is deliberately not carried over.** A
   `[provider]` block and `[providers.<name>]` tables coexist here, because `active` says which one
   runs. ADR-0144 rule 4 argues it; if the reviewer disagrees, the alternative costs the console an
   in-place migration of the operator's `[provider]` block on the first *Add a profile*.
3. **The row text says `kind ∈ ollama / llamacpp / openai_compatible`.** FreeWeight's factory
   constructs `ollama`, `llamacpp` and `fake`; `openai_compatible` is a `ProviderKind` with no
   adapter wired here, and naming one is a configuration error today
   (`infrastructure/providers/factory.py`). The document states the three it can construct rather
   than the three the row named. Wiring `openai_compatible` is its own row.
4. **`kind` was not made a `Literal`.** It would refuse a typo at load instead of at construction,
   but it also makes `build_provider`'s own `ConfigurationError` unreachable and would fail
   `test_provider_factory`'s "quantum-oracle" case. The console now offers only the kinds the
   application states, which closes the path that mattered.
5. **The profile name is never recorded on a run** (ADR-0144 rule 8). Two runs on two profiles of
   the same kind and settings stay one measurement. If the operator wants the *name* on results,
   that is a data-model change and a new ADR, not a field.

## 9. What the row text got wrong, and one mishap

* The row says a profile's keys reach the form because `config_files.apply_changes` writes dotted
  keys "as it does today" — true for the write, but the *read* needed the two additions in §4: the
  document had to state the prefixes, and the form had to take a profile's keys from the schema
  rather than from the file. Without those, a profile shows only the keys already written.
* `wr-gym`'s config directory is `$XDG_CONFIG_HOME/wr-gym`, not `.../weightroom`. A first attempt
  at the screenshot console put the file under the wrong name, so the config was ignored and the
  process bound its defaults — `127.0.0.1:8769`/`8770`, the operator's ports — for about thirty
  seconds before it was killed by environ-verified pid. The operator's own console binds its LAN
  address and was not displaced, and nothing was written to it, but the lesson is worth the line:
  check the listener (`ss -ltn`) immediately after starting a throwaway, not after the first
  screenshot.

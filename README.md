# WeightRoomGym

**The host operator's console for the Local AI Suite** — and the repository that holds the suite's
canonical documentation under [`docs/`](docs/README.md).

WeightRoomGym (`pip install wr-gym`, CLI `wr-gym`, import `weightroom`, port 8769) is the fifth application: a
host operator tool that sits **above** the suite's layer rules. It is the one service exposed on the
LAN — with its own certificate authority, HTTPS and a login — and from it an operator runs, watches,
configures, backs up, inspects and talks to FreeWeight, LoadCoach, IdeaPress and PromptCadence,
which all stay on loopback behind it.

| | |
|---|---|
| Decisions | [ADR-0123](docs/adr/0123-weightroom-is-a-host-operator-tool-above-the-layer-rules.md) (what it is), [ADR-0124](docs/adr/0124-a-raw-write-into-another-applications-database-passes-a-five-part-guard.md) (the write guard), [ADR-0125](docs/adr/0125-weightroom-drives-the-applications-through-systemd-user-units-it-writes.md) (process control), [ADR-0126](docs/adr/0126-weightroom-is-the-only-service-on-the-lan-and-terminates-tls-with-its-own-ca.md) (LAN, TLS, login), [ADR-0127](docs/adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md) (settings schema) |
| Specification | [`docs/apps/weightroom/spec.md`](docs/apps/weightroom/spec.md) · [API](docs/apps/weightroom/api.md) · [Data model](docs/apps/weightroom/data-model.md) · [Design brief](docs/apps/weightroom/design.md) · [Risks](docs/apps/weightroom/risks.md) |
| Plan | [`docs/apps/weightroom/development-plan.md`](docs/apps/weightroom/development-plan.md); the schedule is [`docs/roadmap/weightroom-work.md`](docs/roadmap/weightroom-work.md) |
| Status | Row W10 (2026-09-10): `1.0.0` prepared, unpublished (`0.1.0` is on PyPI; `pip install wr-gym`), waiting on the operator's independent-device verification, MirrorWall `0.3.1` on PyPI and the tag. `wr-gym setup && wr-gym serve` gives an HTTPS console with a login and the audit trail; the five `systemd --user` units, start/stop/restart, the journal live and unified, the Ollama memory-safety pane, the audit page, the telemetry strip and shell, each application's Overview, its settings form generated from its own `config schema` document, its tokens page, `wr-gym doctor`, the docs viewer, chat through LoadCoach and PromptCadence, and each application's database — read-only, its own `db` verbs first, a raw write only under ADR-0124's guard — are here. Costs, backups, the job queue with its schedules, alerts and the prompt editor (rows W8–W9) too; the operator documents are [`docs/setup.md`](docs/setup.md), [`docs/security.md`](docs/security.md), [`docs/operations.md`](docs/operations.md) and [`docs/troubleshooting.md`](docs/troubleshooting.md). |

## The documentation tree

`docs/` is the **single source of truth** for the whole suite — architecture, standards, ADRs,
per-component specifications and development plans. Every other repository carries a
byte-identical mirror of the documents that concern it. Start at [`docs/README.md`](docs/README.md).

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff format --check . && ruff check . && mypy src tests && lint-imports && pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE).

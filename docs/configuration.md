# Configuration reference

**Generated** from `weightroom.config.Settings` by `wr-gym config reference`; do not edit by
hand — `tests/unit/test_config_reference.py` fails when this file differs from the model.

Precedence, field by field (configuration standards §1): built-in defaults, then `config.toml`
(`wr-gym config path` prints where), then `WEIGHTROOM_*` environment variables, then CLI flags.
Sections and fields are joined with a double underscore in the environment: `[server] port` is
`WEIGHTROOM_SERVER__PORT` and `[apps.loadcoach] base_url` is `WEIGHTROOM_APPS__LOADCOACH__BASE_URL`.
Lists are comma-separated in the environment.

**Runtime-changeable** keys (spec §12: six of them) may also be set while the server runs, through
`PUT /api/v1/settings` or the Settings page. Their stored value sits *between* the file and the
environment (configuration standards §7): `defaults -> file -> database -> env -> CLI`; a stored
value whose key is set in the environment is kept but does nothing until that variable is unset,
and `wr-gym config show` says so. **Security keys** — every key under `[server]`, `[tls]`,
`[auth]`, `[apps.*]` and `[host]` — are config-only and editable on WeightRoomGym's own settings
page only after re-authentication (ADR-0127 rule 6).


## `[server]`

Bind address, the two ports and the HTTP-level limits.

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `server.host` | `WEIGHTROOM_SERVER__HOST` | `str` | `'127.0.0.1'` | — | no | **security key** (config-only) | `'127.0.0.1'` | Interface to bind. Loopback by default; anything else requires a valid tls/ directory, an operator account and allowed_hosts (ADR-0126 rule 6). |
| `server.port` | `WEIGHTROOM_SERVER__PORT` | `int` | `8769` | ≥ 1, ≤ 65535 | no | **security key** (config-only) | `8769` | TCP port for the HTTPS console. Plain HTTP is never served on it. |
| `server.allow_lan_exposure` | `WEIGHTROOM_SERVER__ALLOW_LAN_EXPOSURE` | `bool` | `False` | — | no | **security key** (config-only) | `False` | Acknowledges a deliberate bind to every interface (0.0.0.0). Without it such a bind refuses to start. |
| `server.allowed_hosts` | `WEIGHTROOM_SERVER__ALLOWED_HOSTS` | `tuple[str, Ellipsis]` | `()` | — | no | **security key** (config-only) | `['jordan-main', 'jordan-main.local', '10.77.10.84']` | Host header values accepted on a non-loopback bind, against DNS rebinding (ADR-0026 §1). The wizard fills it from the host's names and addresses. Comma-separated in the environment. |
| `server.trust_port` | `WEIGHTROOM_SERVER__TRUST_PORT` | `int` | `8770` | ≥ 1, ≤ 65535 | no | **security key** (config-only) | `8770` | The plain-HTTP trust listener: serves /root.crt and the trust page, nothing else (ADR-0126 rule 3). |
| `server.rate_limit_per_minute` | `WEIGHTROOM_SERVER__RATE_LIMIT_PER_MINUTE` | `int` | `600` | ≥ 0 | no | **security key** (config-only) | `600` | Requests per minute one address may make to /api/v1, sustained. A token bucket: rate_limit_burst may arrive at once, then this rate. 0 disables. At the limit a caller gets 429 RATE_LIMITED with Retry-After. |
| `server.rate_limit_burst` | `WEIGHTROOM_SERVER__RATE_LIMIT_BURST` | `int` | `100` | ≥ 1 | no | **security key** (config-only) | `100` | How many requests one address may make at once before the rate applies. |
| `server.failed_login_per_minute` | `WEIGHTROOM_SERVER__FAILED_LOGIN_PER_MINUTE` | `int` | `5` | ≥ 0 | no | **security key** (config-only) | `5` | Login attempts one address may make per minute before it is refused with 429 for the rest of the minute (ADR-0126 rule 4). 0 disables. |
| `server.max_body_bytes` | `WEIGHTROOM_SERVER__MAX_BODY_BYTES` | `int` | `67108864` | ≥ 1024 | no | **security key** (config-only) | `67108864` | The largest request body accepted, refused with 413 before buffering. 64 MiB admits a GGUF drop-in by upload (spec §12). |

## `[tls]`

The certificate authority and the leaf it signs (ADR-0126 rule 2).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `tls.directory` | `WEIGHTROOM_TLS__DIRECTORY` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.config/wr-gym/tls'` | Where ca.key, ca.crt, server.key and server.crt live. Empty means <config>/tls. |
| `tls.leaf_days` | `WEIGHTROOM_TLS__LEAF_DAYS` | `int` | `398` | ≥ 1, ≤ 825 | no | **security key** (config-only) | `398` | The leaf certificate's lifetime; 398 days is the browser ceiling. |
| `tls.ca_years` | `WEIGHTROOM_TLS__CA_YEARS` | `int` | `10` | ≥ 1, ≤ 30 | no | **security key** (config-only) | `10` | The root's lifetime. |
| `tls.renew_before_days` | `WEIGHTROOM_TLS__RENEW_BEFORE_DAYS` | `int` | `30` | ≥ 1 | no | **security key** (config-only) | `30` | Serve renews the leaf at startup when fewer days than this remain. |

## `[auth]`

Session lifetimes and the re-authentication window (ADR-0126 rule 4, ADR-0127 rule 6).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `auth.session_idle_hours` | `WEIGHTROOM_AUTH__SESSION_IDLE_HOURS` | `int` | `12` | ≥ 1 | no | **security key** (config-only) | `12` | A session ends this long after its last request. |
| `auth.session_max_days` | `WEIGHTROOM_AUTH__SESSION_MAX_DAYS` | `int` | `7` | ≥ 1 | no | **security key** (config-only) | `7` | A session ends this long after login, whatever happens. |
| `auth.reauth_window_minutes` | `WEIGHTROOM_AUTH__REAUTH_WINDOW_MINUTES` | `int` | `5` | ≥ 1 | no | **security key** (config-only) | `5` | How long a successful POST /reauth authorises a security action. |

## `[storage]`

Database location, resolved through WeightsDB (ADR-0006).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `storage.database_url` | `WEIGHTROOM_STORAGE__DATABASE_URL` | `str \| None` | `None` | — | no | — | `'sqlite:////var/lib/wr-gym/weightroom.sqlite3'` | SQLAlchemy URL. Unset resolves to a SQLite file under the XDG data directory; PostgreSQL is the other supported dialect (ADR-0006). |
| `storage.auto_migrate` | `WEIGHTROOM_STORAGE__AUTO_MIGRATE` | `bool` | `True` | — | no | — | `True` | Migrate on startup. Unset means true on SQLite and false on PostgreSQL, where a failed migration cannot be rolled back automatically (database standards §5.1). |
| `storage.backup_retention` | `WEIGHTROOM_STORAGE__BACKUP_RETENTION` | `int` | `5` | ≥ 0 | no | — | `5` | Automatic pre-migration backups kept before the oldest is rotated away. |

## `[apps]`

One block per application, ``[apps.<name>]``.


## `[apps.freeweight]`

How WeightRoomGym reaches one application: its executable, its API, its token file.

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `apps.freeweight.executable` | `WEIGHTROOM_APPS__FREEWEIGHT__EXECUTABLE` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.local/bin/loadcoach'` | The application's CLI. Empty means shutil.which(<app>) at startup. |
| `apps.freeweight.base_url` | `WEIGHTROOM_APPS__FREEWEIGHT__BASE_URL` | `str` | `''` | — | no | **security key** (config-only) | `'http://127.0.0.1:8766'` | The application's own HTTP API, loopback (ADR-0126 rule 1). |
| `apps.freeweight.api_key_file` | `WEIGHTROOM_APPS__FREEWEIGHT__API_KEY_FILE` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.config/wr-gym/secrets/loadcoach.token'` | A file holding the bearer token the wizard created for WeightRoomGym, mode 0600 (ADR-0126 rule 8). Never the value itself. Empty for an application without tokens. |

## `[apps.loadcoach]`

How WeightRoomGym reaches one application: its executable, its API, its token file.

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `apps.loadcoach.executable` | `WEIGHTROOM_APPS__LOADCOACH__EXECUTABLE` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.local/bin/loadcoach'` | The application's CLI. Empty means shutil.which(<app>) at startup. |
| `apps.loadcoach.base_url` | `WEIGHTROOM_APPS__LOADCOACH__BASE_URL` | `str` | `''` | — | no | **security key** (config-only) | `'http://127.0.0.1:8766'` | The application's own HTTP API, loopback (ADR-0126 rule 1). |
| `apps.loadcoach.api_key_file` | `WEIGHTROOM_APPS__LOADCOACH__API_KEY_FILE` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.config/wr-gym/secrets/loadcoach.token'` | A file holding the bearer token the wizard created for WeightRoomGym, mode 0600 (ADR-0126 rule 8). Never the value itself. Empty for an application without tokens. |

## `[apps.ideapress]`

How WeightRoomGym reaches one application: its executable, its API, its token file.

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `apps.ideapress.executable` | `WEIGHTROOM_APPS__IDEAPRESS__EXECUTABLE` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.local/bin/loadcoach'` | The application's CLI. Empty means shutil.which(<app>) at startup. |
| `apps.ideapress.base_url` | `WEIGHTROOM_APPS__IDEAPRESS__BASE_URL` | `str` | `''` | — | no | **security key** (config-only) | `'http://127.0.0.1:8766'` | The application's own HTTP API, loopback (ADR-0126 rule 1). |
| `apps.ideapress.api_key_file` | `WEIGHTROOM_APPS__IDEAPRESS__API_KEY_FILE` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.config/wr-gym/secrets/loadcoach.token'` | A file holding the bearer token the wizard created for WeightRoomGym, mode 0600 (ADR-0126 rule 8). Never the value itself. Empty for an application without tokens. |

## `[apps.promptcadence]`

How WeightRoomGym reaches one application: its executable, its API, its token file.

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `apps.promptcadence.executable` | `WEIGHTROOM_APPS__PROMPTCADENCE__EXECUTABLE` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.local/bin/loadcoach'` | The application's CLI. Empty means shutil.which(<app>) at startup. |
| `apps.promptcadence.base_url` | `WEIGHTROOM_APPS__PROMPTCADENCE__BASE_URL` | `str` | `''` | — | no | **security key** (config-only) | `'http://127.0.0.1:8766'` | The application's own HTTP API, loopback (ADR-0126 rule 1). |
| `apps.promptcadence.api_key_file` | `WEIGHTROOM_APPS__PROMPTCADENCE__API_KEY_FILE` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/.config/wr-gym/secrets/loadcoach.token'` | A file holding the bearer token the wizard created for WeightRoomGym, mode 0600 (ADR-0126 rule 8). Never the value itself. Empty for an application without tokens. |

## `[host]`

The host: the unit-level memory cap, Ollama's unit, the GGUF drop-in directory.

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `host.memory_high` | `WEIGHTROOM_HOST__MEMORY_HIGH` | `str` | `'22G'` | — | no | **security key** (config-only) | `'22G'` | MemoryHigh written into the application units (ADR-0119, ADR-0125). |
| `host.memory_max` | `WEIGHTROOM_HOST__MEMORY_MAX` | `str` | `'24G'` | — | no | **security key** (config-only) | `'24G'` | MemoryMax written into the application units (ADR-0119, ADR-0125). |
| `host.ollama_unit` | `WEIGHTROOM_HOST__OLLAMA_UNIT` | `str` | `'ollama.service'` | — | no | **security key** (config-only) | `'ollama.service'` | Ollama's system unit name. |
| `host.ollama_base_url` | `WEIGHTROOM_HOST__OLLAMA_BASE_URL` | `str` | `'http://127.0.0.1:11434'` | — | no | **security key** (config-only) | `'http://127.0.0.1:11434'` | Ollama's API, for residency and pulls. |
| `host.llamacpp_model_directory` | `WEIGHTROOM_HOST__LLAMACPP_MODEL_DIRECTORY` | `str` | `''` | — | no | **security key** (config-only) | `'/home/op/ai/models/gguf'` | Where a GGUF drop-in lands. Empty means the directory the applications' configs name. |

## `[telemetry]`

The in-process sweatmeter sampler (spec §7.7).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `telemetry.interval_ms` | `WEIGHTROOM_TELEMETRY__INTERVAL_MS` | `int` | `1000` | ≥ 100, ≤ 60000 | yes | — | `1000` | Sampling interval. Runtime-changeable. |
| `telemetry.history_hours` | `WEIGHTROOM_TELEMETRY__HISTORY_HOURS` | `int` | `72` | ≥ 1, ≤ 720 | yes | — | `72` | How long telemetry_samples are kept. Runtime-changeable. |

## `[chat]`

Chat defaults and the attachment cap (spec §7.6).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `chat.max_attachment_bytes` | `WEIGHTROOM_CHAT__MAX_ATTACHMENT_BYTES` | `int` | `262144` | ≥ 1024 | no | — | `262144` | The largest text or markdown attachment accepted. |
| `chat.default_task_profile` | `WEIGHTROOM_CHAT__DEFAULT_TASK_PROFILE` | `str` | `'general.chat'` | — | yes | — | `'general.chat'` | The LoadCoach task profile a new chat starts with. Runtime-changeable. |
| `chat.default_classification` | `WEIGHTROOM_CHAT__DEFAULT_CLASSIFICATION` | `'public' \| 'internal' \| 'confidential'` | `'confidential'` | — | no | — | `'confidential'` | The PromptCadence classification a new conversation starts with. |

## `[docs]`

The documentation tree the viewer renders (spec §7.5).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `docs.root` | `WEIGHTROOM_DOCS__ROOT` | `str` | `''` | — | no | — | `'/home/op/ai/suite/WeightRoom/docs'` | The docs/ directory. Empty means the docs/ beside this checkout when one exists, else the viewer refuses by name. |

## `[jobs]`

The database-backed queue (spec §7.10, ADR-0029 shape).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `jobs.lease_seconds` | `WEIGHTROOM_JOBS__LEASE_SECONDS` | `int` | `60` | ≥ 5 | no | — | `60` | A claimed job's lease. |
| `jobs.poll_interval_ms` | `WEIGHTROOM_JOBS__POLL_INTERVAL_MS` | `int` | `1000` | ≥ 100, ≤ 60000 | yes | — | `1000` | How often the worker looks for work. Runtime-changeable. |
| `jobs.output_cap_bytes` | `WEIGHTROOM_JOBS__OUTPUT_CAP_BYTES` | `int` | `1048576` | ≥ 1024 | no | — | `1048576` | Captured stdout/stderr kept per job. |

## `[alerts]`

The alert evaluator (spec §7.10).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `alerts.interval_seconds` | `WEIGHTROOM_ALERTS__INTERVAL_SECONDS` | `int` | `30` | ≥ 5, ≤ 3600 | yes | — | `30` | How often the five sources are evaluated. Runtime-changeable. |
| `alerts.gpu_temperature_c` | `WEIGHTROOM_ALERTS__GPU_TEMPERATURE_C` | `int` | `85` | ≥ 40, ≤ 120 | yes | — | `85` | GPU temperature that opens a gpu_thermal alert. Runtime-changeable. |

## `[ui]`

The console's own display defaults (row WX5).

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `ui.page_rows` | `WEIGHTROOM_UI__PAGE_ROWS` | `int` | `50` | ≥ 10, ≤ 500 | yes | — | `50` | Rows per page on every table the owning API can page. Runtime-changeable. |

## `[logging]`

Log level and content policy.

| Key | Environment variable | Type | Default | Range | Runtime-changeable | Security | Example | Description |
|---|---|---|---|---|---|---|---|---|
| `logging.level` | `WEIGHTROOM_LOGGING__LEVEL` | `'DEBUG' \| 'INFO' \| 'WARNING' \| 'ERROR'` | `'INFO'` | — | no | — | `'INFO'` | Root log level. |
| `logging.format` | `WEIGHTROOM_LOGGING__FORMAT` | `'auto' \| 'text' \| 'json'` | `'auto'` | — | no | — | `'auto'` | text on a TTY, json otherwise, unless forced. |
| `logging.include_content` | `WEIGHTROOM_LOGGING__INCLUDE_CONTENT` | `bool` | `False` | — | no | — | `False` | Log chat text and attachment bodies. Off by default; config-only. |

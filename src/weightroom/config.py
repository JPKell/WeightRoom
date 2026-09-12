"""weightroom.config — typed settings, source-tracked, per Configuration Standards.

Precedence, lowest to highest: built-in defaults, ``config.toml``, ``WEIGHTROOM_``-prefixed
environment variables, then explicit overrides (the CLI's highest layer). Overriding is per leaf
field, not per section (configuration standards §1): setting one field of ``[server]`` never
discards its siblings. The shape is LoadCoach's ``config.py``, the precedent the W1 kickoff
names, with one generalisation: sections nest one level deeper here (``[apps.loadcoach]``), so
every walk over the model is recursive and a leaf is a dotted path of any depth.

The refusals a bind combination earns are split by what they need to see. Those checkable from
the settings alone (``allow_lan_exposure``, ``allowed_hosts``) raise here, in
:func:`load_settings`; the two that need the filesystem and the database — a valid ``tls/``
directory and an operator account — raise in :mod:`weightroom.bootstrap` (ADR-0126 rule 6).
"""

from __future__ import annotations

import difflib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

from baseaicore import ConfigurationError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

__all__ = [
    "APPLICATIONS",
    "DEFAULT_APP_PORTS",
    "EXAMPLE_CONFIG_TOML",
    "ENV_PREFIX",
    "LOOPBACK_HOSTS",
    "SECURITY_SECTIONS",
    "AlertsSettings",
    "AppSettings",
    "AppsSettings",
    "AuthSettings",
    "ChatSettings",
    "ConfigurationError",
    "DocsSettings",
    "HostSettings",
    "InsecureBindingError",
    "JobsSettings",
    "LoadedSettings",
    "LoggingSettings",
    "ServerSettings",
    "Settings",
    "StorageSettings",
    "TelemetrySettings",
    "TlsMissingError",
    "TlsSettings",
    "UiSettings",
    "config_dir",
    "data_dir",
    "env_var_for",
    "leaf_keys",
    "load_settings",
    "load_settings_tolerant",
    "resolve_config_path",
    "secrets_dir",
    "security_keys",
    "state_dir",
    "tls_dir",
]

ENV_PREFIX = "WEIGHTROOM_"
"""ADR-0123 rule 1: the environment prefix follows the import name."""

_ROOT_NAME = "wr-gym"
"""The config, data and state directory name follows the command (ADR-0123 rule 1)."""

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
APPLICATIONS: tuple[str, ...] = ("freeweight", "loadcoach", "ideapress", "promptcadence")
"""The four applications, in the suite's own order; ``{app}`` in every route is one of these."""

APP_LABELS: dict[str, str] = {
    "freeweight": "FreeWeight",
    "loadcoach": "LoadCoach",
    "ideapress": "IdeaPress",
    "promptcadence": "PromptCadence",
    "weightroom": "WeightRoom",
}
"""How each application's name is displayed. Its route, unit, CLI and config section keep the
lowercase name; this is the word an operator reads, never an identifier anything parses."""

SECURITY_SECTIONS: frozenset[str] = frozenset({"server", "tls", "auth", "apps", "host"})
"""Spec §12: every key under these sections is a security key — editable on WeightRoomGym's own
settings page only after re-authentication, never through ``PUT /settings``."""

_ALL_INTERFACES_HOST = "0.0.0.0"  # noqa: S104 — compared against, never bound to, by this module
_RESERVED_ENV_SUFFIXES = frozenset({"CONFIG", "DATA_DIR", "LOG_LEVEL"})
_DEFAULT_PORT = 8769
_DEFAULT_TRUST_PORT = 8770


class InsecureBindingError(ConfigurationError):
    """A configured bind/auth combination would expose the service unsafely (ADR-0126 rule 6).

    Raised by :func:`load_settings` for the two rules checkable without I/O, and by
    :mod:`weightroom.bootstrap` for the two that need the TLS directory and the operator table.
    Every rule has a documented, deliberate acknowledgement that lifts it; none can be satisfied
    by accident. Exit code 3 at startup (spec §13).
    """

    code: ClassVar[str] = "INSECURE_BINDING"


class TlsMissingError(ConfigurationError):
    """The TLS directory is present but incomplete or unreadable, on any bind (spec §13).

    Distinct from :class:`InsecureBindingError`: an *absent* directory on loopback is initialised
    silently (zero-configuration start is a gold standard, and HTTPS is the only protocol the
    console speaks), while a half-written one is refused on every bind rather than guessed at.
    Exit code 3 at startup.
    """

    code: ClassVar[str] = "TLS_MISSING"


def _split_csv(value: Any) -> Any:
    """Accept a comma-separated string for a tuple field, as environment variables must (§3)."""
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return value


class ServerSettings(BaseModel):
    """Bind address, the two ports and the HTTP-level limits."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        default="127.0.0.1",
        description=(
            "Interface to bind. Loopback by default; anything else requires a valid tls/ "
            "directory, an operator account and allowed_hosts (ADR-0126 rule 6)."
        ),
        examples=["127.0.0.1"],
    )
    port: int = Field(
        default=_DEFAULT_PORT,
        ge=1,
        le=65535,
        description="TCP port for the HTTPS console. Plain HTTP is never served on it.",
        examples=[_DEFAULT_PORT],
    )
    allow_lan_exposure: bool = Field(
        default=False,
        description=(
            "Acknowledges a deliberate bind to every interface (0.0.0.0). Without it such a bind "
            "refuses to start."
        ),
        examples=[False],
    )
    allowed_hosts: tuple[str, ...] = Field(
        default=(),
        description=(
            "Host header values accepted on a non-loopback bind, against DNS rebinding "
            "(ADR-0026 §1). The wizard fills it from the host's names and addresses. "
            "Comma-separated in the environment."
        ),
        examples=[["jordan-main", "jordan-main.local", "10.77.10.84"]],
    )
    trust_port: int = Field(
        default=_DEFAULT_TRUST_PORT,
        ge=1,
        le=65535,
        description=(
            "The plain-HTTP trust listener: serves /root.crt and the trust page, nothing else "
            "(ADR-0126 rule 3)."
        ),
        examples=[_DEFAULT_TRUST_PORT],
    )
    rate_limit_per_minute: int = Field(
        default=600,
        ge=0,
        description=(
            "Requests per minute one address may make to /api/v1, sustained. A token bucket: "
            "rate_limit_burst may arrive at once, then this rate. 0 disables. At the limit a "
            "caller gets 429 RATE_LIMITED with Retry-After."
        ),
        examples=[600],
    )
    rate_limit_burst: int = Field(
        default=100,
        ge=1,
        description="How many requests one address may make at once before the rate applies.",
        examples=[100],
    )
    failed_login_per_minute: int = Field(
        default=5,
        ge=0,
        description=(
            "Login attempts one address may make per minute before it is refused with 429 for "
            "the rest of the minute (ADR-0126 rule 4). 0 disables."
        ),
        examples=[5],
    )
    max_body_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1024,
        description=(
            "The largest request body accepted, refused with 413 before buffering. 64 MiB "
            "admits a GGUF drop-in by upload (spec §12)."
        ),
        examples=[67108864],
    )

    _split_allowed_hosts = field_validator("allowed_hosts", mode="before")(_split_csv)


class TlsSettings(BaseModel):
    """The certificate authority and the leaf it signs (ADR-0126 rule 2)."""

    model_config = ConfigDict(extra="forbid")

    directory: str = Field(
        default="",
        description=(
            "Where ca.key, ca.crt, server.key and server.crt live. Empty means <config>/tls."
        ),
        examples=["/home/op/.config/wr-gym/tls"],
    )
    leaf_days: int = Field(
        default=398,
        ge=1,
        le=825,
        description="The leaf certificate's lifetime; 398 days is the browser ceiling.",
        examples=[398],
    )
    ca_years: int = Field(
        default=10, ge=1, le=30, description="The root's lifetime.", examples=[10]
    )
    renew_before_days: int = Field(
        default=30,
        ge=1,
        description="Serve renews the leaf at startup when fewer days than this remain.",
        examples=[30],
    )


class AuthSettings(BaseModel):
    """Session lifetimes and the re-authentication window (ADR-0126 rule 4, ADR-0127 rule 6)."""

    model_config = ConfigDict(extra="forbid")

    session_idle_hours: int = Field(
        default=12,
        ge=1,
        description="A session ends this long after its last request.",
        examples=[12],
    )
    session_max_days: int = Field(
        default=7,
        ge=1,
        description="A session ends this long after login, whatever happens.",
        examples=[7],
    )
    reauth_window_minutes: int = Field(
        default=5,
        ge=1,
        description="How long a successful POST /reauth authorises a security action.",
        examples=[5],
    )


class StorageSettings(BaseModel):
    """Database location, resolved through WeightsDB (ADR-0006)."""

    model_config = ConfigDict(extra="forbid")

    database_url: str | None = Field(
        default=None,
        description=(
            "SQLAlchemy URL. Unset resolves to a SQLite file under the XDG data directory; "
            "PostgreSQL is the other supported dialect (ADR-0006)."
        ),
        examples=["sqlite:////var/lib/wr-gym/weightroom.sqlite3"],
    )
    auto_migrate: bool = Field(
        default=True,
        description=(
            "Migrate on startup. Unset means true on SQLite and false on PostgreSQL, where a "
            "failed migration cannot be rolled back automatically (database standards §5.1)."
        ),
        examples=[True],
    )
    backup_retention: int = Field(
        default=5,
        ge=0,
        description="Automatic pre-migration backups kept before the oldest is rotated away.",
        examples=[5],
    )

    @model_validator(mode="after")
    def _apply_data_dir_defaults(self) -> StorageSettings:
        """Fill in the zero-configuration defaults, resolved against the XDG data directory."""
        if self.database_url is None:
            self.database_url = f"sqlite:///{data_dir()}/weightroom.sqlite3"
        if "auto_migrate" not in self.model_fields_set:
            self.auto_migrate = self.database_url.startswith("sqlite")
        return self


class AppSettings(BaseModel):
    """How WeightRoomGym reaches one application: its executable, its API, its token file."""

    model_config = ConfigDict(extra="forbid")

    executable: str = Field(
        default="",
        description="The application's CLI. Empty means shutil.which(<app>) at startup.",
        examples=["/home/op/.local/bin/loadcoach"],
    )
    base_url: str = Field(
        default="",
        description="The application's own HTTP API, loopback (ADR-0126 rule 1).",
        examples=["http://127.0.0.1:8766"],
    )
    api_key_file: str = Field(
        default="",
        description=(
            "A file holding the bearer token the wizard created for WeightRoomGym, mode 0600 "
            "(ADR-0126 rule 8). Never the value itself. Empty for an application without tokens."
        ),
        examples=["/home/op/.config/wr-gym/secrets/loadcoach.token"],
    )


DEFAULT_APP_PORTS: dict[str, int] = {
    "freeweight": 8765,
    "loadcoach": 8766,
    "ideapress": 8767,
    "promptcadence": 8768,
}
"""Each application's own loopback port, as its spec fixes it."""


def _app_defaults(port: int) -> AppSettings:
    return AppSettings(base_url=f"http://127.0.0.1:{port}")


class AppsSettings(BaseModel):
    """One block per application, ``[apps.<name>]``."""

    model_config = ConfigDict(extra="forbid")

    freeweight: AppSettings = Field(default_factory=lambda: _app_defaults(8765))
    loadcoach: AppSettings = Field(default_factory=lambda: _app_defaults(8766))
    ideapress: AppSettings = Field(default_factory=lambda: _app_defaults(8767))
    promptcadence: AppSettings = Field(default_factory=lambda: _app_defaults(8768))

    @model_validator(mode="after")
    def _fill_default_base_urls(self) -> AppsSettings:
        """Give every application its own port back when the file named only its siblings.

        Configuration standards §1: overriding is per **leaf**, not per section. A default that
        lives only in a section's ``default_factory`` breaks that rule silently — writing
        ``[apps.loadcoach] executable = "…"`` would otherwise leave ``base_url`` empty, and the
        console would report LoadCoach as unreachable while the operator looked at a file that
        never mentioned a URL. Found at row W2 against a partial ``[apps.loadcoach]`` table.
        """
        for name, port in DEFAULT_APP_PORTS.items():
            block: AppSettings = getattr(self, name)
            if not block.base_url:
                setattr(
                    self, name, block.model_copy(update={"base_url": f"http://127.0.0.1:{port}"})
                )
        return self


class HostSettings(BaseModel):
    """The host: the unit-level memory cap, Ollama's unit, the GGUF drop-in directory."""

    model_config = ConfigDict(extra="forbid")

    memory_high: str = Field(
        default="22G",
        description="MemoryHigh written into the application units (ADR-0119, ADR-0125).",
        examples=["22G"],
    )
    memory_max: str = Field(
        default="24G",
        description="MemoryMax written into the application units (ADR-0119, ADR-0125).",
        examples=["24G"],
    )
    ollama_unit: str = Field(
        default="ollama.service",
        description="Ollama's system unit name.",
        examples=["ollama.service"],
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        description="Ollama's API, for residency and pulls.",
        examples=["http://127.0.0.1:11434"],
    )
    llamacpp_model_directory: str = Field(
        default="",
        description=(
            "Where a GGUF drop-in lands. Empty means the directory the applications' configs name."
        ),
        examples=["/home/op/ai/models/gguf"],
    )


class TelemetrySettings(BaseModel):
    """The in-process sweatmeter sampler (spec §7.7)."""

    model_config = ConfigDict(extra="forbid")

    interval_ms: int = Field(
        default=1000,
        ge=100,
        le=60_000,
        description="Sampling interval. Runtime-changeable.",
        examples=[1000],
    )
    history_hours: int = Field(
        default=72,
        ge=1,
        le=24 * 30,
        description="How long telemetry_samples are kept. Runtime-changeable.",
        examples=[72],
    )


class ChatSettings(BaseModel):
    """Chat defaults and the attachment cap (spec §7.6)."""

    model_config = ConfigDict(extra="forbid")

    max_attachment_bytes: int = Field(
        default=256 * 1024,
        ge=1024,
        description="The largest text or markdown attachment accepted.",
        examples=[262144],
    )
    default_task_profile: str = Field(
        default="general.chat",
        description="The LoadCoach task profile a new chat starts with. Runtime-changeable.",
        examples=["general.chat"],
    )
    default_classification: Literal["public", "internal", "confidential"] = Field(
        default="confidential",
        description="The PromptCadence classification a new conversation starts with.",
        examples=["confidential"],
    )


class DocsSettings(BaseModel):
    """The documentation tree the viewer renders (spec §7.5)."""

    model_config = ConfigDict(extra="forbid")

    root: str = Field(
        default="",
        description=(
            "The docs/ directory. Empty means the docs/ beside this checkout when one exists, "
            "else the viewer refuses by name."
        ),
        examples=["/home/op/ai/suite/WeightRoom/docs"],
    )


class JobsSettings(BaseModel):
    """The database-backed queue (spec §7.10, ADR-0029 shape)."""

    model_config = ConfigDict(extra="forbid")

    lease_seconds: int = Field(
        default=60, ge=5, description="A claimed job's lease.", examples=[60]
    )
    poll_interval_ms: int = Field(
        default=1000,
        ge=100,
        le=60_000,
        description="How often the worker looks for work. Runtime-changeable.",
        examples=[1000],
    )
    output_cap_bytes: int = Field(
        default=1024 * 1024,
        ge=1024,
        description="Captured stdout/stderr kept per job.",
        examples=[1048576],
    )


class AlertsSettings(BaseModel):
    """The alert evaluator (spec §7.10)."""

    model_config = ConfigDict(extra="forbid")

    interval_seconds: int = Field(
        default=30,
        ge=5,
        le=3600,
        description="How often the five sources are evaluated. Runtime-changeable.",
        examples=[30],
    )
    gpu_temperature_c: int = Field(
        default=85,
        ge=40,
        le=120,
        description="GPU temperature that opens a gpu_thermal alert. Runtime-changeable.",
        examples=[85],
    )


class UiSettings(BaseModel):
    """The console's own display defaults (row WX5)."""

    model_config = ConfigDict(extra="forbid")

    page_rows: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Rows per page on every table the owning API can page. Runtime-changeable.",
        examples=[50],
    )


class LoggingSettings(BaseModel):
    """Log level and content policy."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Root log level.", examples=["INFO"]
    )
    format: Literal["auto", "text", "json"] = Field(
        default="auto",
        description="text on a TTY, json otherwise, unless forced.",
        examples=["auto"],
    )
    include_content: bool = Field(
        default=False,
        description="Log chat text and attachment bodies. Off by default; config-only.",
        examples=[False],
    )


class Settings(BaseModel):
    """The complete, validated WeightRoomGym configuration (spec §12).

    Constructed only by :func:`load_settings`, which resolves the precedence chain first — never
    call ``Settings(**raw_dict)`` directly on unmerged input, or the file/env/CLI layering in
    configuration standards §1 is bypassed.
    """

    model_config = ConfigDict(extra="forbid")

    server: ServerSettings = Field(default_factory=ServerSettings)
    tls: TlsSettings = Field(default_factory=TlsSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    apps: AppsSettings = Field(default_factory=AppsSettings)
    host: HostSettings = Field(default_factory=HostSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
    docs: DocsSettings = Field(default_factory=DocsSettings)
    jobs: JobsSettings = Field(default_factory=JobsSettings)
    alerts: AlertsSettings = Field(default_factory=AlertsSettings)
    ui: UiSettings = Field(default_factory=UiSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


@dataclass(frozen=True, slots=True)
class LoadedSettings:
    """The result of resolving configuration: the settings, and where every value came from."""

    settings: Settings
    config_path: Path
    config_file_used: bool
    sources: dict[str, str]


def config_dir() -> Path:
    """Return ``$XDG_CONFIG_HOME/wr-gym``, falling back to ``~/.config/wr-gym``."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / _ROOT_NAME


def data_dir() -> Path:
    """Return ``$WEIGHTROOM_DATA_DIR``, else ``$XDG_DATA_HOME/wr-gym``, else the XDG default."""
    override = os.environ.get(f"{ENV_PREFIX}DATA_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return root / _ROOT_NAME


def state_dir() -> Path:
    """Return ``$XDG_STATE_HOME/wr-gym``, falling back to ``~/.local/state/wr-gym``."""
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / _ROOT_NAME


def tls_dir(settings: Settings) -> Path:
    """The directory holding the CA and the leaf: ``[tls] directory``, else ``<config>/tls``."""
    if settings.tls.directory:
        return Path(settings.tls.directory).expanduser()
    return config_dir() / "tls"


def secrets_dir() -> Path:
    """Where the wizard keeps application tokens by file (ADR-0126 rule 8)."""
    return config_dir() / "secrets"


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    """Resolve the configuration file location per Configuration Standards §2.

    Order: an explicit path (``--config``), then ``WEIGHTROOM_CONFIG``, then a project-local
    ``./wr-gym.toml`` if one exists in the current directory, then the XDG default. A missing
    file at the resolved path is not an error — :func:`load_settings` falls back to defaults.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    env_path = os.environ.get(f"{ENV_PREFIX}CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    local = Path.cwd() / f"{_ROOT_NAME}.toml"
    if local.is_file():
        return local
    return config_dir() / "config.toml"


def _read_env(prefix: str) -> dict[str, Any]:
    """Parse ``<prefix>SECTION__FIELD`` environment variables into a nested dict."""
    nested: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix) :]
        if suffix in _RESERVED_ENV_SUFFIXES:
            continue
        path = suffix.lower().split("__")
        node = nested
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value

    log_level = os.environ.get(f"{prefix}LOG_LEVEL")
    if log_level and "level" not in nested.get("logging", {}):
        nested.setdefault("logging", {})["level"] = log_level
    return nested


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge ``override`` onto ``base``, recursively, per leaf field rather than per section."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _walk(model: type[BaseModel], prefix: str = "") -> list[str]:
    """Every dotted path under ``model`` — sections and leaves, any depth."""
    paths: list[str] = []
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        paths.append(path)
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths.extend(_walk(annotation, f"{path}."))
    return paths


def _is_section(path: str) -> bool:
    """Whether ``path`` names a nested model rather than a leaf."""
    node: type[BaseModel] = Settings
    for part in path.split("."):
        annotation = node.model_fields[part].annotation
        if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
            return False
        node = annotation
    return True


def leaf_keys() -> tuple[str, ...]:
    """Every dotted leaf path :class:`Settings` recognizes, ``apps.loadcoach.base_url`` included.

    The schema document (ADR-0127), the configuration reference and the security-key set all
    read this one walk, so none of them keeps a second copy of the key list.
    """
    return tuple(path for path in _walk(Settings) if not _is_section(path))


def security_keys() -> frozenset[str]:
    """The keys under :data:`SECURITY_SECTIONS`: WeightRoomGym's own security keys (spec §12)."""
    return frozenset(key for key in leaf_keys() if key.split(".", 1)[0] in SECURITY_SECTIONS)


def _lookup(data: dict[str, Any], path: str) -> bool:
    """Whether the layer ``data`` sets the leaf at dotted ``path``."""
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _translate_validation_error(
    exc: PydanticValidationError, config_path: Path
) -> ConfigurationError:
    """Turn a pydantic ``ValidationError`` into a :class:`ConfigurationError` naming the field."""
    known_keys = _walk(Settings)
    problems: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        if error["type"] == "extra_forbidden":
            suggestion = difflib.get_close_matches(loc, known_keys, n=1)
            hint = f" (did you mean '{suggestion[0]}'?)" if suggestion else ""
            problems.append(f"unknown configuration key '{loc}'{hint}")
        else:
            problems.append(f"{loc}: {error['msg']} (got {error.get('input')!r})")
    message = f"Configuration invalid ({config_path}): " + "; ".join(problems)
    return ConfigurationError(message, details={"file": str(config_path), "problems": problems})


def _validate_security(settings: Settings) -> None:
    """Refuse the unsafe bind combinations checkable without I/O (ADR-0126 rule 6).

    The other two members of the refusal set — a valid ``tls/`` directory and an operator account
    on a non-loopback bind — need the filesystem and the database and are checked in
    :mod:`weightroom.bootstrap`.
    """
    server = settings.server
    if server.host == _ALL_INTERFACES_HOST and not server.allow_lan_exposure:
        raise InsecureBindingError(
            "server.host is '0.0.0.0' (all interfaces) but server.allow_lan_exposure is false. "
            "Exposing the console beyond this machine must be a deliberate act: set "
            "server.allow_lan_exposure = true if that is intended.",
            details={"field": "server.allow_lan_exposure", "host": server.host},
        )
    if server.host not in LOOPBACK_HOSTS and not server.allowed_hosts:
        raise InsecureBindingError(
            "server.host is not loopback but server.allowed_hosts is empty. A non-loopback bind "
            "must name every hostname it will accept, or DNS rebinding can reach it "
            "(`wr-gym setup` fills it from the host's names and addresses).",
            details={"field": "server.allowed_hosts", "host": server.host},
        )
    if server.trust_port == server.port:
        raise ConfigurationError(
            "server.trust_port equals server.port; the trust listener needs its own port.",
            details={"field": "server.trust_port", "port": server.port},
        )


def env_var_for(path: str) -> str:
    """The environment variable that sets the leaf at dotted ``path``.

    Args:
        path: A dotted path, as :attr:`LoadedSettings.sources` keys them.

    Returns:
        The full variable name — ``apps.loadcoach.base_url`` is
        ``WEIGHTROOM_APPS__LOADCOACH__BASE_URL``.

    Raises:
        ValueError: ``path`` names no field (no ``.`` in it).
    """
    if "." not in path:
        message = f"{path!r} is not a section.field path"
        raise ValueError(message)
    return ENV_PREFIX + path.upper().replace(".", "__")


def _track_sources(
    file_data: dict[str, Any], env_data: dict[str, Any], cli_data: dict[str, Any]
) -> dict[str, str]:
    """Report, for every leaf field, which layer produced its effective value."""
    sources: dict[str, str] = {}
    for path in leaf_keys():
        if _lookup(cli_data, path):
            sources[path] = "cli"
        elif _lookup(env_data, path):
            sources[path] = f"env {env_var_for(path)}"
        elif _lookup(file_data, path):
            sources[path] = "file"
        else:
            sources[path] = "default"
    return sources


def _read_file(resolved_path: Path) -> tuple[dict[str, Any], bool]:
    """Parse ``resolved_path`` as TOML, or return an empty mapping when it does not exist."""
    if not resolved_path.is_file():
        return {}, False
    try:
        with resolved_path.open("rb") as handle:
            return tomllib.load(handle), True
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(
            f"Configuration file {resolved_path} is not valid TOML: {exc}",
            details={"file": str(resolved_path)},
        ) from exc


def _validate(merged: dict[str, Any], resolved_path: Path) -> Settings:
    """Validate a merged, layered configuration dict into a :class:`Settings`."""
    try:
        settings = Settings.model_validate(merged)
    except PydanticValidationError as exc:
        raise _translate_validation_error(exc, resolved_path) from exc
    _validate_security(settings)
    return settings


def load_settings(
    *,
    config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> LoadedSettings:
    """Resolve configuration through the full precedence chain and validate it.

    Args:
        config_path: An explicit ``--config`` path. See :func:`resolve_config_path` for the
            fallback order when this is ``None``.
        cli_overrides: Explicit values from CLI flags, nested the same way as the TOML file
            (``{"server": {"port": 9000}}``). This is the highest-precedence layer.

    Returns:
        The validated :class:`LoadedSettings`.

    Raises:
        ConfigurationError: The file is not valid TOML, a key is unrecognized, a value fails a
            field's type or range, or an unsafe bind combination is configured
            (:class:`InsecureBindingError`, a subclass). Does **not** check the TLS directory or
            the operator account — see :mod:`weightroom.bootstrap`.
    """
    resolved_path = resolve_config_path(config_path)
    file_data, file_used = _read_file(resolved_path)
    env_data = _read_env(ENV_PREFIX)
    cli_data = cli_overrides or {}
    merged = _deep_merge(_deep_merge(file_data, env_data), cli_data)
    settings = _validate(merged, resolved_path)
    sources = _track_sources(file_data, env_data, cli_data)
    return LoadedSettings(
        settings=settings, config_path=resolved_path, config_file_used=file_used, sources=sources
    )


def _strip_unknown(
    data: dict[str, Any], model: type[BaseModel], prefix: str
) -> tuple[dict[str, Any], list[str]]:
    """Drop every key ``model`` does not declare, reporting each as a problem (any depth)."""
    clean: dict[str, Any] = {}
    problems: list[str] = []
    for name, value in data.items():
        path = f"{prefix}{name}"
        info = model.model_fields.get(name)
        if info is None:
            problems.append(f"unknown configuration key '{path}'")
            continue
        annotation = info.annotation
        if (
            isinstance(value, dict)
            and isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
        ):
            nested, nested_problems = _strip_unknown(value, annotation, f"{path}.")
            clean[name] = nested
            problems.extend(nested_problems)
        else:
            clean[name] = value
    return clean, problems


def load_settings_tolerant(
    config_path: str | Path | None = None,
) -> tuple[LoadedSettings, tuple[str, ...]]:
    """Like :func:`load_settings`, but an unknown key in the file is reported, never fatal.

    Built for ``config schema`` (ADR-0127 rule 1): the tool that describes why a configuration
    file doesn't load cannot itself refuse to load it. Every other kind of problem — a bad type,
    an out-of-range value, an unsafe bind — still raises exactly as :func:`load_settings` does.

    Args:
        config_path: As :func:`load_settings`.

    Returns:
        The validated :class:`LoadedSettings` (built with unknown keys removed) and a tuple of
        ``"unknown configuration key '…'"`` messages, empty when the file had none.

    Raises:
        ConfigurationError: The file is not valid TOML, a *known* key fails validation, or an
            unsafe bind combination is configured.
    """
    resolved_path = resolve_config_path(config_path)
    file_data, file_used = _read_file(resolved_path)
    clean_file, problems = _strip_unknown(file_data, Settings, "")
    env_data = _read_env(ENV_PREFIX)
    merged = _deep_merge(clean_file, env_data)
    settings = _validate(merged, resolved_path)
    sources = _track_sources(clean_file, env_data, {})
    loaded = LoadedSettings(
        settings=settings, config_path=resolved_path, config_file_used=file_used, sources=sources
    )
    return loaded, tuple(problems)


EXAMPLE_CONFIG_TOML = """\
# WeightRoomGym configuration (wr-gym).
# Every key below is optional; a fresh install with no file at all serves HTTPS on loopback.
# Precedence: defaults -> this file -> WEIGHTROOM_* environment variables -> CLI flags.
# `wr-gym setup` writes the bind, the allowed hosts and the token references for you.

[server]
host = "127.0.0.1"           # non-loopback needs tls/, an operator account and allowed_hosts
port = 8769                  # HTTPS only; plain HTTP is never served here
allow_lan_exposure = false   # required, together with the above, for host = "0.0.0.0"
allowed_hosts = []           # Host header allowlist off loopback; the wizard fills it
trust_port = 8770            # plain HTTP: /root.crt and the trust page only
rate_limit_per_minute = 600
rate_limit_burst = 100
failed_login_per_minute = 5
max_body_bytes = 67108864    # 64 MiB, for a GGUF drop-in by upload

[tls]
directory = ""               # "" = <config>/tls: ca.key, ca.crt, server.key, server.crt
leaf_days = 398
ca_years = 10
renew_before_days = 30

[auth]
session_idle_hours = 12
session_max_days = 7
reauth_window_minutes = 5

[storage]
# database_url = "sqlite:////home/op/.local/share/wr-gym/weightroom.sqlite3"
# auto_migrate = true        # default: true on SQLite, false on PostgreSQL
backup_retention = 5

[apps.freeweight]
executable = ""              # "" = shutil.which("freeweight")
base_url = "http://127.0.0.1:8765"
api_key_file = ""

[apps.loadcoach]
executable = ""
base_url = "http://127.0.0.1:8766"
api_key_file = ""            # the wizard writes <config>/secrets/loadcoach.token

[apps.ideapress]
executable = ""
base_url = "http://127.0.0.1:8767"

[apps.promptcadence]
executable = ""
base_url = "http://127.0.0.1:8768"
api_key_file = ""

[host]
memory_high = "22G"          # the unit-level cap (ADR-0119, ADR-0125)
memory_max = "24G"
ollama_unit = "ollama.service"
ollama_base_url = "http://127.0.0.1:11434"
llamacpp_model_directory = ""

[telemetry]
interval_ms = 1000           # runtime-changeable
history_hours = 72           # runtime-changeable

[chat]
max_attachment_bytes = 262144
default_task_profile = "general.chat"       # runtime-changeable
default_classification = "confidential"

[docs]
root = ""                    # "" = the docs/ beside this checkout, else refuse

[jobs]
lease_seconds = 60
poll_interval_ms = 1000      # runtime-changeable
output_cap_bytes = 1048576

[alerts]
interval_seconds = 30        # runtime-changeable
gpu_temperature_c = 85       # runtime-changeable

[ui]
page_rows = 50                # runtime-changeable; rows per page, 10-500

[logging]
level = "INFO"
format = "auto"              # text on a TTY, json otherwise
include_content = false
"""

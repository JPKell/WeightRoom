"""weightroom.services.settings — the runtime-changeable registry and the schema document.

Spec §12 names six runtime-changeable keys, plus ``ui.page_rows`` since row WX5 (ADR-0100's test:
re-read by the running process, no security surface) and makes every key under ``[server]``,
``[tls]``, ``[auth]``, ``[apps.*]`` and ``[host]`` a security key. Both sets are data here, read
by ``config show``, ``config
schema``, the configuration reference and — at W4 — WeightRoomGym's own settings page, so none of
them can disagree. Precedence follows configuration standards §7: a stored row sits between the
file and the environment, and a row the environment shadows is reported as such.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final

from baseaicore import SuiteError, ValidationError
from sqlalchemy import select
from weightsdb import upsert

from weightroom.config import (
    ENV_PREFIX,
    Settings,
    env_var_for,
    leaf_keys,
    load_settings_tolerant,
    security_keys,
)
from weightroom.infrastructure.db.models import Setting

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from weightroom.services.database import Database

__all__ = [
    "RUNTIME_SETTINGS",
    "SCHEMA_VERSION",
    "RuntimeSetting",
    "SettingConfigOnly",
    "config_schema_document",
    "database_overlay",
    "read_runtime_settings",
    "runtime_settings_document",
    "shadowing_source",
    "write_runtime_settings",
]


class SettingConfigOnly(SuiteError):
    """A config-only key was sent to ``PUT /settings`` (spec §13 ``SETTING_CONFIG_ONLY``)."""

    code: ClassVar[str] = "SETTING_CONFIG_ONLY"


class SettingUnknown(SuiteError):
    """A key that is neither runtime-changeable nor config-only (spec §13 ``SETTING_UNKNOWN``)."""

    code: ClassVar[str] = "SETTING_UNKNOWN"


@dataclass(frozen=True, slots=True)
class RuntimeSetting:
    """One runtime-changeable key: where it lives in ``Settings``, its type and its bounds."""

    key: str
    kind: type[bool] | type[int] | type[float] | type[str]
    description: str
    minimum: float | None = None
    maximum: float | None = None

    @property
    def section(self) -> str:
        """The ``Settings`` section the key belongs to."""
        return self.key.split(".", 1)[0]

    @property
    def field(self) -> str:
        """The field within the section."""
        return self.key.split(".", 1)[1]

    def coerce(self, value: object) -> bool | int | float | str:
        """Validate ``value`` for this key.

        Raises:
            ValidationError: Wrong type, or outside the bounds.
        """
        problem = {"fields": [{"path": self.key, "problem": ""}]}
        if self.kind is str:
            if not isinstance(value, str) or not value.strip():
                problem["fields"][0]["problem"] = "expected a non-empty string"
                raise ValidationError(f"{self.key} must be a non-empty string.", details=problem)
            return value
        if self.kind is bool:
            if not isinstance(value, bool):
                problem["fields"][0]["problem"] = "expected a boolean"
                raise ValidationError(f"{self.key} must be true or false.", details=problem)
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problem["fields"][0]["problem"] = "expected a number"
            raise ValidationError(f"{self.key} must be a number.", details=problem)
        number: int | float = int(value) if self.kind is int else float(value)
        if self.kind is int and float(value) != number:
            problem["fields"][0]["problem"] = "expected an integer"
            raise ValidationError(f"{self.key} must be a whole number.", details=problem)
        if (self.minimum is not None and number < self.minimum) or (
            self.maximum is not None and number > self.maximum
        ):
            problem["fields"][0]["problem"] = f"outside [{self.minimum}, {self.maximum}]"
            raise ValidationError(
                f"{self.key} must be between {self.minimum} and {self.maximum}.", details=problem
            )
        return number


RUNTIME_SETTINGS: Final[dict[str, RuntimeSetting]] = {
    setting.key: setting
    for setting in (
        RuntimeSetting(
            "telemetry.interval_ms",
            int,
            "Telemetry sampling interval.",
            minimum=100,
            maximum=60_000,
        ),
        RuntimeSetting(
            "telemetry.history_hours", int, "Telemetry retention.", minimum=1, maximum=24 * 30
        ),
        RuntimeSetting(
            "alerts.interval_seconds", int, "Alert evaluation interval.", minimum=5, maximum=3600
        ),
        RuntimeSetting(
            "alerts.gpu_temperature_c", int, "GPU thermal alert threshold.", minimum=40, maximum=120
        ),
        RuntimeSetting(
            "jobs.poll_interval_ms", int, "Job worker poll interval.", minimum=100, maximum=60_000
        ),
        RuntimeSetting(
            "chat.default_task_profile", str, "The LoadCoach task profile a new chat starts with."
        ),
        RuntimeSetting(
            "ui.page_rows",
            int,
            "Rows per page on every table the owning API can page.",
            minimum=10,
            maximum=500,
        ),
    )
}
"""Spec §12's runtime-changeable keys (row WX5 adds ``ui.page_rows``)."""


def shadowing_source(key: str) -> str | None:
    """The environment variable pinning ``key``, or ``None`` when nothing shadows a stored row."""
    name = env_var_for(key)
    return f"env {name}" if name in os.environ else None


def _configured(settings: Settings, setting: RuntimeSetting) -> bool | int | float | str:
    section = getattr(settings, setting.section)
    value: bool | int | float | str = getattr(section, setting.field)
    return value


def _stored(database: Database) -> dict[str, Any]:
    with database.read() as session:
        return {
            str(key): value
            for key, value in session.execute(
                select(Setting.key, Setting.value_json).where(
                    Setting.key.in_(list(RUNTIME_SETTINGS))
                )
            ).all()
        }


def read_runtime_settings(database: Database, *, settings: Settings) -> dict[str, Any]:
    """Every runtime-changeable key's effective value: the stored row unless the environment
    pins the key or the row is one this build cannot read (which falls back to configuration).
    """
    stored = _stored(database)
    effective: dict[str, Any] = {}
    for key, setting in RUNTIME_SETTINGS.items():
        if key in stored and shadowing_source(key) is None:
            try:
                effective[key] = setting.coerce(stored[key])
                continue
            except ValidationError:
                pass
        effective[key] = _configured(settings, setting)
    return effective


def write_runtime_settings(
    database: Database, changes: Mapping[str, Any], *, settings: Settings, now: datetime
) -> dict[str, Any]:
    """Validate and store ``changes``, returning every effective value afterwards.

    Raises:
        SettingConfigOnly: A config-only key (a security key included), named.
        SettingUnknown: A key the model does not have at all.
        ValidationError: A value of the wrong type or outside its bounds.
    """
    known = set(leaf_keys())
    for key in changes:
        if key in RUNTIME_SETTINGS:
            continue
        if key in known:
            raise SettingConfigOnly(
                f"{key} is config-only; set it in config.toml or the environment"
                + (
                    " after re-authentication on the settings page"
                    if key in security_keys()
                    else ""
                )
                + ".",
                details={"key": key, "security": key in security_keys()},
            )
        raise SettingUnknown(
            f"{key} is not a WeightRoomGym setting.",
            details={"key": key, "runtime_changeable": sorted(RUNTIME_SETTINGS)},
        )
    validated = {key: RUNTIME_SETTINGS[key].coerce(value) for key, value in changes.items()}
    if validated:
        with database.write() as session:
            for key, value in validated.items():
                upsert(
                    session,
                    Setting,
                    values={"key": key, "value_json": value, "updated_at": now},
                    index_elements=["key"],
                )
    return read_runtime_settings(database, settings=settings)


def runtime_settings_document(database: Database, *, settings: Settings) -> dict[str, Any]:
    """The ``GET /settings`` body: effective values, per-key definitions, the config-only set."""
    effective = read_runtime_settings(database, settings=settings)
    stored = _stored(database)
    definitions: dict[str, Any] = {}
    for key, setting in RUNTIME_SETTINGS.items():
        shadowed_by = shadowing_source(key) if key in stored else None
        definitions[key] = {
            "type": setting.kind.__name__,
            "description": setting.description,
            "minimum": setting.minimum,
            "maximum": setting.maximum,
            "configured": _configured(settings, setting),
            "stored": stored.get(key),
            "source": "database" if key in stored and shadowed_by is None else "configuration",
            "shadowed_by": shadowed_by,
        }
    return {
        "settings": effective,
        "definitions": definitions,
        "config_only": sorted(set(leaf_keys()) - set(RUNTIME_SETTINGS)),
        "security_keys": sorted(security_keys()),
    }


def database_overlay(settings: Settings) -> dict[str, tuple[Any, str]]:
    """The runtime-changeable values the ``settings`` table decides, and how to label them.

    Never raises and never creates a database file: an absent, unmigrated or unreadable database
    means the configured values are the answer, which is what ``config show`` should print then.
    """
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import SQLAlchemyError

    from weightroom.services.database import Database

    database_url = settings.storage.database_url
    if database_url is None:  # pragma: no cover — StorageSettings always fills this in
        return {}
    url = make_url(database_url)
    if (
        url.drivername.startswith("sqlite")
        and url.database not in (None, ":memory:")
        and not Path(str(url.database)).is_file()
    ):
        return {}
    try:
        with Database.from_url(database_url) as database:
            document = runtime_settings_document(database, settings=settings)
    except (SQLAlchemyError, SuiteError, OSError):
        return {}
    overlay: dict[str, tuple[Any, str]] = {}
    for key, definition in document["definitions"].items():
        if definition["source"] == "database":
            overlay[key] = (document["settings"][key], "database")
        elif definition["shadowed_by"] is not None:
            overlay[key] = (
                document["settings"][key],
                f"{definition['shadowed_by']}; database row {definition['stored']} shadowed",
            )
    return overlay


SCHEMA_VERSION: Final = "1.0"
"""The version of the settings-schema document :func:`config_schema_document` emits (ADR-0127)."""


def config_schema_document(config_path: str | Path | None = None) -> dict[str, Any]:
    """Build the ADR-0127 rule 1 settings-schema document for WeightRoomGym itself.

    Args:
        config_path: As :func:`~weightroom.config.load_settings`.

    Returns:
        ``schema_version``, ``application``, ``version``, ``env_prefix``, ``config_path``,
        ``json_schema``, ``runtime_changeable``, ``security_keys``, ``config_only``, ``sources``
        (database overlay included) and ``problems`` (unknown keys in the file, never dropped).

    Raises:
        ConfigurationError: A known key fails validation or the bind combination is unsafe.
    """
    from weightroom import __about__

    loaded, problems = load_settings_tolerant(config_path)
    sources = dict(loaded.sources)
    for path, (_value, source) in database_overlay(loaded.settings).items():
        sources[path] = source
    runtime_keys = set(RUNTIME_SETTINGS)
    security = security_keys()
    return {
        "schema_version": SCHEMA_VERSION,
        "application": "weightroom",
        "version": __about__.__version__,
        "env_prefix": ENV_PREFIX,
        "config_path": str(loaded.config_path),
        "json_schema": Settings.model_json_schema(),
        "runtime_changeable": [
            {
                "key": setting.key,
                "kind": setting.kind.__name__,
                "minimum": setting.minimum,
                "maximum": setting.maximum,
                "description": setting.description,
            }
            for setting in RUNTIME_SETTINGS.values()
        ],
        "security_keys": sorted(security),
        "config_only": sorted(set(leaf_keys()) - runtime_keys - security),
        "sources": sources,
        "problems": list(problems),
    }

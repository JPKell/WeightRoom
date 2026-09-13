"""weightroom.services.settings_forms — every application's settings form, from its own schema.

[ADR-0127](../../../docs/adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)
rule 3: **no key is hardcoded here.** An application publishes one document from
``<app> config schema --json`` — pydantic's own ``json_schema`` plus the three key sets
(``runtime_changeable``, ``security_keys``, ``config_only``) and ``config show``'s per-leaf
``sources`` — and this module turns that document into a form model the templates render. A key
the document does not describe is listed as raw TOML, never invented; a field added to an
application appears here on the next read, with no change in this repository.

Three sources are composed per field, and the form says which answered:

1. **The document** — the field's type, bounds, description, default and layer.
2. **The file** — what ``config.toml`` actually says, parsed with ``tomllib``. This is the value
   the form edits; a runtime key's file value is what the operator configured, not what is running.
3. **The running application** — ``GET /api/v1/settings`` for the runtime-changeable keys only,
   which is what is *running* right now (ADR-0100). A stopped application has no such answer and
   the form says so rather than showing the file value as if it were live.

WeightRoomGym's own document is built in process rather than by launching ``wr-gym`` as a child
of itself: it is the same function the verb prints
(:func:`~weightroom.services.settings.config_schema_document`), so the page is generated from the
document exactly as the other four are.

Nothing here raises for an application that is missing, stopped or too old to carry the verbs:
the development plan's Phase 4 prerequisite is that such an application *degrades to the raw
editor with the reason*, so a failure is :attr:`SettingsForm.document_error` and an empty section
list, which is a page, not a stack trace.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import httpx
import tomlkit

from weightroom.config import APPLICATIONS
from weightroom.services.apps import bearer_token
from weightroom.services.processes import child_environment, executable_for, run_command

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from weightroom.config import Settings
    from weightroom.services.apps import AppView
    from weightroom.services.processes import Runner

__all__ = [
    "REDACTED",
    "KeyOutcome",
    "SaveResult",
    "SCHEMA_TIMEOUT_SECONDS",
    "SCHEMA_TTL_SECONDS",
    "FormField",
    "FormSection",
    "SchemaCache",
    "SettingsForm",
    "config_file_path",
    "is_secret_key",
    "live_settings",
    "live_settings_with_definitions",
    "read_schema_document",
    "save_settings",
    "settings_form",
]

SCHEMA_TTL_SECONDS: Final = 60.0
"""How long one application's schema document is held (api.md §2: cached for 60 s)."""

SCHEMA_TIMEOUT_SECONDS: Final = 30.0
"""How long ``<app> config schema --json`` may take; the same cap process control uses."""

_LIVE_TIMEOUT_SECONDS: Final = 3.0

REDACTED: Final = "********"
"""What a secret-shaped field shows instead of its value; a write of this exact text is a no-op."""

_SECRET_LEAF: Final = re.compile(
    r"(?i)^(?:(?:api_|auth_|bearer_)?(?:tokens?|secrets?|password|key)|.*_(?:password|secret|api_key))$"
)
"""A field whose **value** is the secret, matched against the key's last segment only.

Deliberately narrower than :func:`~weightroom.domain.audit.redact_params`' rule, twice over.
That rule matches ``key`` and ``token`` *anywhere*, which here would redact two kinds of field
an operator must be able to read and edit: ``api_key_file`` and ``api_key_env``, which ADR-0126
rule 8 configures *instead of* the secret, and PromptCadence's ``tiers.<name>.…_tokens``, which
are token **counts**. Redaction of the audit trail stays deliberately over-broad; a form that
will not show you what you are editing is a form you cannot use.
"""


def is_secret_key(key: str) -> bool:
    """Whether ``key``'s value is itself a secret and must never be rendered.

    Args:
        key: A dotted key path (``auth.tokens``).

    Returns:
        True for a field that holds a credential; False for one that only *references* one
        (``…_file``, ``…_env``), which the form shows and edits normally.
    """
    return _SECRET_LEAF.search(key.rsplit(".", 1)[-1]) is not None


@dataclass(frozen=True, slots=True)
class FormField:
    """One editable leaf of an application's configuration.

    Attributes:
        key: The dotted path (``server.port``).
        label: The leaf's own name (``port``).
        kind: ``boolean``, ``integer``, ``number``, ``string``, ``array``, ``object`` or
            ``unknown`` — read from the document's ``json_schema``, never guessed from the value.
        description: The field's own description, or ``""``.
        default: What the model defaults to.
        value: The effective value: the running application's for a live key, else the file's,
            else the default. :data:`REDACTED` for a secret-shaped field.
        source: ``config show``'s own word for the layer that decided it (``file``, ``default``,
            ``env WEIGHTROOM_SERVER__PORT``, ``database``, …).
        shadowed: Whether the environment or a CLI flag pins the key, so a file edit here would
            not take effect. The form says so rather than letting the write look successful.
        runtime: Whether the key is in ``runtime_changeable`` — saved through the application.
        security: Whether the key is in ``security_keys`` — saved only after ``POST /reauth``.
        secret: Whether the value is a credential; see :func:`is_secret_key`.
        minimum: The lower bound, when the schema states one.
        maximum: The upper bound.
        choices: The permitted values, when the schema states an ``enum``.
        live: Whether ``value`` came from the running application rather than the file.
        in_file: Whether the file names this key at all.
        applies: When a stored value takes effect, in the application's own word (IdeaPress:
            ``next_stage``), or ``""`` when its document states none — then a runtime key is
            applied live (row W10; ``history/handoffs/WI1_HANDOFF.md`` §5 item 4a).
        stored: Whether the running application holds a stored row for this key — one a
            *clear* hands back to configuration (WI1 §5 item 4b).
        nullable: Whether the model allows the key to be **unset** (``bool | None``). A widget
            that cannot say *unset* has to invent a value, and an untouched form then writes a
            key the operator never touched (row WPF1; ``WP6_HANDOFF.md`` finding 1).
    """

    key: str
    label: str
    kind: str
    description: str
    default: Any
    value: Any
    source: str
    shadowed: bool
    runtime: bool
    security: bool
    secret: bool
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    live: bool = False
    in_file: bool = False
    applies: str = ""
    stored: bool = False
    nullable: bool = False

    @property
    def value_text(self) -> str:
        """The value as the form's text input carries it — TOML for anything but a scalar."""
        return _as_text(self.value)

    @property
    def default_text(self) -> str:
        """The default, rendered the same way."""
        return _as_text(self.default)

    def parse(self, raw: str) -> Any:  # noqa: ANN401 — TOML in, JSON-shaped out
        """One submitted form string as this field's own type.

        A browser posts text; the file and the application both want a typed value, and the type
        is the one the document stated. Anything but a scalar is parsed as the TOML value it is
        written as, so an array or an inline table can be edited in a single-line input exactly
        as it appears in the file.

        Args:
            raw: What the form posted.

        Returns:
            The typed value.

        Raises:
            ValueError: The text is not a value of this field's type.
        """
        text = raw.strip()
        if raw == "" and self.nullable:
            # The model says this key may be unset, so an empty box or a select's *unset* option
            # is *unset* for every kind — never a written `false`, `""` or the first choice of a
            # list the operator never opened (row WPF1).
            return None
        if self.kind == "string":
            # An empty box on a string the model has no value for means *leave it unset*, not
            # "set it to the empty string" — otherwise submitting an untouched form would write
            # `database_url = ""` over every optional path in the file. Where the field's value
            # already **is** the empty string, that is a real value and emptying stays an edit.
            return None if raw == "" and self.value is None else raw
        if not text:
            # TOML has no null, so an empty box on a non-string field means *leave it alone*.
            # `save_settings` compares this against the current value: it is `unchanged` for a
            # field that has no value, and a refusal for one that does — clearing a key is the
            # raw editor's job, because it is a deletion and not an edit.
            return None
        if self.kind == "boolean":
            if text.lower() in {"true", "on", "yes", "1"}:
                return True
            if text.lower() in {"false", "off", "no", "0"}:
                return False
            message = f"{self.key} is true or false, not {raw!r}"
            raise ValueError(message)
        if self.kind == "integer":
            try:
                return int(text, 10)
            except ValueError as exc:
                message = f"{self.key} is a whole number, not {raw!r}"
                raise ValueError(message) from exc
        if self.kind == "number":
            try:
                return float(text)
            except ValueError as exc:
                message = f"{self.key} is a number, not {raw!r}"
                raise ValueError(message) from exc
        try:
            parsed = tomllib.loads(f"value = {text}")
        except tomllib.TOMLDecodeError as exc:
            message = f"{self.key} needs a TOML value, and {raw!r} is not one"
            raise ValueError(message) from exc
        if "value" not in parsed:
            message = f"{self.key} needs a TOML value, and {raw!r} is not one"
            raise ValueError(message)
        return parsed["value"]

    @property
    def bounds_text(self) -> str:
        """``100 … 60000``, ``≥ 1``, ``≤ 100`` or ``""`` — whichever bounds exist."""
        if self.minimum is not None and self.maximum is not None:
            return f"{_number_text(self.minimum)} … {_number_text(self.maximum)}"
        if self.minimum is not None:
            return f"≥ {_number_text(self.minimum)}"
        if self.maximum is not None:
            return f"≤ {_number_text(self.maximum)}"
        return ""

    def as_json(self) -> dict[str, Any]:
        """The ``GET /apps/{app}/settings`` shape for one key (api.md §2)."""
        return {
            "key": self.key,
            "type": self.kind,
            "description": self.description,
            "default": self.default,
            "value": self.value,
            "source": self.source,
            "shadowed": self.shadowed,
            "shadowed_by": self.source if self.shadowed else None,
            "runtime": self.runtime,
            "security": self.security,
            "secret": self.secret,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "choices": list(self.choices),
            "live": self.live,
        }


@dataclass(frozen=True, slots=True)
class FormSection:
    """One top-level table of the model — ``[server]``, ``[storage]`` — and its fields."""

    name: str
    title: str
    description: str
    fields: tuple[FormField, ...]


@dataclass(frozen=True, slots=True)
class ProviderCard:
    """One saved provider profile, as the settings page renders it.

    Built from what the application's own document states under ``provider_profiles``
    (ADR-0144 rule 7) — the name, the dotted prefix its keys live under, its kind, and whether it
    is the one running. Nothing here knows a key of any application: the fields are simply this
    form's own fields whose key starts with the stated prefix.

    Attributes:
        name: The profile's name (``default``, ``served``).
        prefix: Where its keys live (``provider``, ``providers.served``).
        kind: What the application says it is, for the card's badge.
        active: Whether the application is running it.
        fields: Its editable leaves, in the model's order.
    """

    name: str
    prefix: str
    kind: str
    active: bool
    fields: tuple[FormField, ...]


@dataclass(frozen=True, slots=True)
class SettingsForm:
    """One application's whole settings page.

    Attributes:
        app: The application.
        version: What its schema document reports, or ``""``.
        config_path: The file the application reads.
        config_exists: Whether that file is there. A first write creates it.
        base_mtime: The file's modification time, echoed back on the write to close the
            ADR-0117 rule 7 race; ``None`` when there is no file yet.
        sections: The form, in the model's own order.
        undescribed: Keys the file carries that the document does not describe — shown raw
            (ADR-0127 rule 3), never dropped and never invented.
        problems: What the application itself reported about its own file.
        provider_form: LoadCoach's ``singular``/``plural`` (ADR-0077), or ``None``.
        provider_profiles: FreeWeight's saved provider profiles as its own document states them
            (ADR-0144 rule 7) — ``key`` (the leaf that selects), ``active``, ``kinds`` and one
            ``name``/``prefix``/``kind`` entry per profile — or ``None`` for an application that
            states none.
        document_error: Why the document could not be read, when it could not. The page then
            degrades to the raw TOML editor with this as the reason.
        running: Whether the application answered, so runtime keys have a live path.
        pending_restart: Whether the file changed after the unit started (rule 5).
        raw_toml: The file's text, for the raw editor.
    """

    app: str
    version: str
    config_path: str
    config_exists: bool
    base_mtime: int | None
    sections: tuple[FormSection, ...] = ()
    undescribed: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    provider_form: str | None = None
    provider_profiles: Mapping[str, Any] | None = None
    document_error: str | None = None
    running: bool = False
    pending_restart: bool = False
    raw_toml: str = ""
    security_keys: frozenset[str] = field(default_factory=frozenset)
    runtime_keys: frozenset[str] = field(default_factory=frozenset)

    def fields(self) -> Iterator[FormField]:
        """Every field of every section, in order."""
        for section in self.sections:
            yield from section.fields

    def field_for(self, key: str) -> FormField | None:
        """The field with that dotted key, or ``None``."""
        return next((one for one in self.fields() if one.key == key), None)

    def provider_cards(self) -> tuple[ProviderCard, ...]:
        """One card per provider profile the application's document states, or ``()``.

        Returns:
            The cards, in the order the application listed them. Empty for an application whose
            document says nothing about profiles, which is every application but FreeWeight.
        """
        stated = self.provider_profiles or {}
        entries = stated.get("profiles") or ()
        selector = str(stated.get("key") or "")
        active = str(stated.get("active") or "")
        cards: list[ProviderCard] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            prefix = str(entry.get("prefix") or "")
            name = str(entry.get("name") or "")
            if not prefix or not name:
                continue
            cards.append(
                ProviderCard(
                    name=name,
                    prefix=prefix,
                    kind=str(entry.get("kind") or ""),
                    active=name == active,
                    fields=tuple(
                        one
                        for one in self.fields()
                        if one.key.startswith(f"{prefix}.") and one.key != selector
                    ),
                )
            )
        return tuple(cards)

    def provider_keys(self) -> frozenset[str]:
        """Every key a provider card renders, so its section does not render it twice."""
        stated = self.provider_profiles or {}
        keys = {str(stated.get("key") or "")} - {""}
        for card in self.provider_cards():
            keys.update(one.key for one in card.fields)
        return frozenset(keys)

    def as_json(self) -> dict[str, Any]:
        """The ``GET /apps/{app}/settings`` body (api.md §2)."""
        return {
            "app": self.app,
            "version": self.version,
            "config_path": self.config_path,
            "config_exists": self.config_exists,
            "base_mtime": self.base_mtime,
            "running": self.running,
            "pending_restart": self.pending_restart,
            "provider_form": self.provider_form,
            "provider_profiles": dict(self.provider_profiles) if self.provider_profiles else None,
            "document_error": self.document_error,
            "problems": list(self.problems),
            "undescribed": list(self.undescribed),
            "runtime_changeable": sorted(self.runtime_keys),
            "security_keys": sorted(self.security_keys),
            "sections": [
                {
                    "name": section.name,
                    "title": section.title,
                    "description": section.description,
                    "fields": [one.as_json() for one in section.fields],
                }
                for section in self.sections
            ],
        }


class SchemaCache:
    """One schema document per application, re-read every :data:`SCHEMA_TTL_SECONDS`.

    Thread-safe for the same reason :class:`~weightroom.services.apps.VersionCache` is: the
    console's synchronous routes run in a threadpool and two tabs can ask at once. A *failed*
    read is cached too, briefly — an application that is not installed would otherwise cost one
    process launch per page element.
    """

    __slots__ = ("_entries", "_lock", "_ttl")

    def __init__(self, *, ttl_seconds: float = SCHEMA_TTL_SECONDS) -> None:
        """Build an empty cache."""
        self._entries: dict[str, tuple[float, dict[str, Any] | None, str | None]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def get(
        self,
        app: str,
        *,
        now: float,
        read: Callable[[], tuple[dict[str, Any] | None, str | None]],
        refresh: bool = False,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """The cached ``(document, error)`` pair, re-reading when it is stale or ``refresh``."""
        with self._lock:
            held = self._entries.get(app)
            if held is not None and not refresh and (now - held[0]) < self._ttl:
                return held[1], held[2]
        document, error = read()
        with self._lock:
            self._entries[app] = (now, document, error)
        return document, error

    def forget(self, app: str) -> None:
        """Drop ``app``'s entry, so the next read asks the application again."""
        with self._lock:
            self._entries.pop(app, None)


def read_schema_document(
    settings: Settings,
    app: str,
    *,
    config_path: Path | None = None,
    runner: Runner = run_command,
    which: Callable[[str], str | None] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read one application's ADR-0127 document, or say why it could not be read.

    Args:
        settings: The validated settings, for the executable and the console's own file.
        app: One of the four, or ``weightroom`` for the console itself.
        config_path: WeightRoomGym's own configuration file; ignored for the other four, which
            resolve their own.
        runner: The process-launch boundary, injected as everywhere else in this repository.
        which: Executable lookup, injected.

    Returns:
        ``(document, None)`` or ``(None, reason)``. Never raises: an application that cannot
        answer degrades its page rather than failing the request (development plan Phase 4).
    """
    if app == "weightroom":
        from weightroom.services.settings import config_schema_document

        try:
            return config_schema_document(config_path), None
        except Exception as exc:  # noqa: BLE001 — the page degrades; it never 500s on its own file
            return None, f"wr-gym could not describe its own configuration: {exc}"
    executable = (
        executable_for(settings, app)
        if which is None
        else executable_for(settings, app, which=which)
    )
    if executable is None:
        return None, f"{app} is not installed: no executable was found for it."
    argv = [executable, "config", "schema", "--json"]
    result = runner(argv, child_environment(), SCHEMA_TIMEOUT_SECONDS)
    if not result.ok:
        return None, f"`{app} config schema --json` failed: {result.failure_text}"
    try:
        document = json.loads(result.stdout)
    except ValueError as exc:
        return None, f"`{app} config schema --json` did not print JSON: {exc}"
    if not isinstance(document, dict) or "json_schema" not in document:
        return None, (
            f"{app} answered a document without a json_schema — it predates ADR-0127's "
            f"`config schema` verb. Upgrade it, or edit the file below."
        )
    return document, None


def config_file_path(
    document: Mapping[str, Any] | None, *, app: str = "", fallback: Path | None = None
) -> Path:
    """The file the application reads.

    Args:
        document: Its schema document, which states ``config_path`` — the authority.
        app: The application, for the fallback below.
        fallback: An explicit path (WeightRoomGym's own, which the runtime already resolved).

    Returns:
        The document's path; failing that ``fallback``; failing that the XDG default the whole
        suite uses. The last is what makes the *degrade to the raw editor* path work at all: an
        application too old or too broken to publish a document still has a file, and it is
        there (configuration standards §2).
    """
    stated = str((document or {}).get("config_path") or "")
    if stated:
        return Path(stated)
    if fallback is not None:
        return fallback
    root = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return root / (app or "unknown") / "config.toml"


def _as_text(value: Any) -> str:
    """A value as the form's single-line text input carries it: TOML, not Python."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return _number_text(value)
    # TOML, not JSON: an inline table is `{a = 1}`, and this text is posted straight back to
    # :meth:`FormField.parse`, which reads it as the TOML value it will be written as.
    try:
        return str(tomlkit.item(value).as_string())
    except (TypeError, ValueError):  # pragma: no cover — a value pydantic could not express
        return json.dumps(value)


def _number_text(value: float) -> str:
    if isinstance(value, bool):  # pragma: no cover — bool is not a bound
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return str(value)


_NULLABLE: Final = "wr_gym_nullable"
"""Where :func:`_resolve` records that it unwrapped a ``null`` member, so the field can still say
the model allows *unset* after the union is gone. A private marker on the resolved copy, never on
the application's own document, and read only through :func:`_is_nullable`."""


def _resolve(schema: Mapping[str, Any], defs: Mapping[str, Any]) -> dict[str, Any]:
    """Follow ``$ref`` and unwrap a nullable ``anyOf``/``allOf`` to the field's real schema."""
    seen = 0
    current: dict[str, Any] = dict(schema)
    nullable = False
    while seen < 8:
        seen += 1
        reference = current.get("$ref")
        if isinstance(reference, str):
            name = reference.rsplit("/", 1)[-1]
            merged = dict(defs.get(name, {}))
            merged.update({k: v for k, v in current.items() if k != "$ref"})
            current = merged
            continue
        for keyword in ("allOf", "anyOf", "oneOf"):
            members = current.get(keyword)
            if isinstance(members, list):
                real = [
                    one for one in members if isinstance(one, Mapping) and one.get("type") != "null"
                ]
                if len(real) == 1:
                    nullable = nullable or len(real) != len(members)
                    merged = dict(real[0])
                    merged.update({k: v for k, v in current.items() if k != keyword})
                    current = merged
                    break
        else:
            break
    if nullable:
        current[_NULLABLE] = True
    return current


def _is_nullable(schema: Mapping[str, Any]) -> bool:
    """Whether the model says this leaf may be unset — ``bool | None``, ``type: [ …, "null"]``."""
    declared = schema.get("type")
    if isinstance(declared, list):
        return "null" in declared
    return bool(schema.get(_NULLABLE))


_KINDS: Final[dict[str, str]] = {
    "boolean": "boolean",
    "integer": "integer",
    "number": "number",
    "string": "string",
    "array": "array",
    "object": "object",
}


_REGISTRY_KINDS: Final[dict[str, str]] = {
    "bool": "boolean",
    "int": "integer",
    "float": "number",
    "str": "string",
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
}
"""``runtime_changeable[].kind`` as the four applications spell it, mapped to the form's word."""


def _kind_of(schema: Mapping[str, Any]) -> str:
    declared = schema.get("type")
    if isinstance(declared, str):
        return _KINDS.get(declared, "unknown")
    if isinstance(declared, list):
        for one in declared:
            if isinstance(one, str) and one != "null":
                return _KINDS.get(one, "unknown")
    if "enum" in schema:
        return "string"
    return "unknown"


def _choices_of(schema: Mapping[str, Any], defs: Mapping[str, Any]) -> tuple[str, ...]:
    values = schema.get("enum")
    if isinstance(values, list):
        return tuple(str(one) for one in values)
    constant = schema.get("const")
    if constant is not None:
        return (str(constant),)
    # A `Literal[...]`/`Enum` field is a `$ref` to a `$defs` entry carrying the enum.
    resolved = _resolve(schema, defs)
    if resolved is not schema and isinstance(resolved.get("enum"), list):
        return tuple(str(one) for one in resolved["enum"])
    return ()


def _bounds_of(schema: Mapping[str, Any]) -> tuple[float | None, float | None]:
    def number(*names: str) -> float | None:
        for name in names:
            value = schema.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None

    return number("minimum", "exclusiveMinimum"), number("maximum", "exclusiveMaximum")


def _stated_number(stated: Any, fallback: float | None) -> float | None:  # noqa: ANN401 — JSON
    """``stated`` as a float when the document states one, else ``fallback``."""
    if isinstance(stated, (int, float)) and not isinstance(stated, bool):
        return float(stated)
    return fallback


def _leaf_of(key: str) -> str:
    """The last segment of a dotted key; the whole key when it has no dot."""
    return key.rsplit(".", 1)[-1] if "." in key else key


def _schema_order(json_schema: Mapping[str, Any], defs: Mapping[str, Any]) -> dict[str, int]:
    """Every dotted path the model declares, in the model's own order, path to position.

    Only for ordering the fields within a section — the *key list* comes from the document's own
    sets, which is where the application says a leaf ends.
    """
    order: dict[str, int] = {}

    def walk(schema: Mapping[str, Any], prefix: str, depth: int) -> None:
        properties = schema.get("properties")
        if depth > 6 or not isinstance(properties, Mapping):
            return
        for name, raw in properties.items():
            path = f"{prefix}{name}"
            order.setdefault(path, len(order))
            walk(_resolve(raw, defs), f"{path}.", depth + 1)

    walk(_resolve(json_schema, defs), "", 0)
    return order


def _schema_for_path(
    json_schema: Mapping[str, Any], defs: Mapping[str, Any], key: str
) -> dict[str, Any] | None:
    """The resolved schema of one dotted key, descending keyed tables through
    ``additionalProperties``; ``None`` when the model does not describe it at all.
    """
    current = _resolve(json_schema, defs)
    for part in key.split("."):
        properties = current.get("properties")
        if isinstance(properties, Mapping) and part in properties:
            current = _resolve(properties[part], defs)
            continue
        extra = current.get("additionalProperties")
        if isinstance(extra, Mapping):
            current = _resolve(extra, defs)
            continue
        return None
    return current


def _provider_profiles(document: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The document's ``provider_profiles`` block, when it states one of the right shape."""
    stated = (document or {}).get("provider_profiles")
    if not isinstance(stated, Mapping) or not stated.get("profiles"):
        return None
    return stated


def _profile_keys(
    document: Mapping[str, Any] | None,
    json_schema: Mapping[str, Any],
    defs: Mapping[str, Any],
) -> list[str]:
    """Every leaf of every provider profile the document states, in the model's own order.

    A profile's keys are not in the document's three key sets — the application cannot enumerate
    operator-chosen names in a static list — and a profile the operator has only half filled in
    names few of them in the file. Asking the *schema* what a profile has, at the prefix the
    application itself stated (ADR-0144 rule 7), is what makes every key of every profile editable
    without this module knowing one of them.

    Args:
        document: The application's schema document.
        json_schema: Its ``json_schema`` block.
        defs: That block's ``$defs``.

    Returns:
        Every profile's dotted keys, profile by profile, in the model's order.
    """
    stated = _provider_profiles(document)
    if stated is None:
        return []
    selector = str(stated.get("key") or "")
    selector_parent, _, selector_leaf = selector.rpartition(".")
    found: list[str] = []
    for entry in stated.get("profiles") or ():
        if not isinstance(entry, Mapping) or not entry.get("prefix"):
            continue
        prefix = str(entry["prefix"])
        schema = _schema_for_path(json_schema, defs, prefix) or {}
        for leaf in schema.get("properties") or {}:
            if leaf == selector_leaf and prefix != selector_parent:
                # Only the selector's own block may carry it: a profile does not choose itself.
                continue
            found.append(f"{prefix}.{leaf}")
    return found


def _lookup(data: Mapping[str, Any], key: str) -> tuple[bool, Any]:
    """``(present, value)`` for a dotted key in a nested mapping."""
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _file_keys(data: Mapping[str, Any], prefix: str = "") -> list[str]:
    """Every dotted leaf the file names, tables descended into."""
    found: list[str] = []
    for name, value in data.items():
        path = f"{prefix}{name}"
        if isinstance(value, Mapping):
            found.extend(_file_keys(value, f"{path}."))
        else:
            found.append(path)
    return found


def _read_toml(path: Path) -> tuple[str, dict[str, Any], str | None]:
    """The file's text, its parsed data and the parse error, if any. Never raises."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "", {}, None
    try:
        return text, tomllib.loads(text), None
    except tomllib.TOMLDecodeError as exc:
        return text, {}, f"{path} is not valid TOML: {exc}"


def live_settings(
    settings: Settings, app: str, view: AppView, *, client: httpx.Client
) -> tuple[dict[str, Any], str | None]:
    """The running application's own runtime-changeable values (``GET /api/v1/settings``).

    Args:
        settings: The validated settings, for the bearer token.
        app: The application.
        view: Its view; a stopped or unreachable application is asked nothing.
        client: The HTTP client.

    Returns:
        ``({key: value}, None)``, or ``({}, reason)``. Never raises: the file path is always
        offered instead (ADR-0127 rule 4).
    """
    values, _definitions, error = live_settings_with_definitions(settings, app, view, client=client)
    return values, error


def live_settings_with_definitions(
    settings: Settings, app: str, view: AppView, *, client: httpx.Client
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]], str | None]:
    """:func:`live_settings`, keeping the document's per-key ``definitions`` beside the values.

    A definition is what the application says about one runtime key — IdeaPress's carry
    ``stored`` (the row, or ``null``) and ``applies`` (``next_stage``); LoadCoach's and
    PromptCadence's documents carry none. Only those two fields are read here.

    Returns:
        ``(values, definitions, error)`` — ``definitions`` is ``{}`` when the document has none.
    """
    if app == "weightroom" or not view.running or not view.reachable:
        return {}, {}, None
    headers = {}
    token = bearer_token(settings, app)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = client.get(
            f"{view.base_url.rstrip('/')}/api/v1/settings",
            headers=headers,
            timeout=_LIVE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return {}, {}, f"{app} is running but did not answer GET /api/v1/settings: {exc}"
    if response.status_code >= 400:  # noqa: PLR2004 — the HTTP error boundary
        # The application's own words, never a rewrite: a `401 UNAUTHORIZED` here means this
        # console has no token for it ([apps.<app>] api_key_file, ADR-0126 rule 8), which is a
        # different fix from a malformed answer and must not be reported as one.
        return {}, {}, f"{app} refused GET /api/v1/settings: {_error_message(response)}"
    try:
        body = response.json()
    except ValueError as exc:
        return {}, {}, f"{app}'s GET /api/v1/settings did not answer JSON: {exc}"
    values = body.get("settings") if isinstance(body, Mapping) else None
    if not isinstance(values, Mapping):
        return {}, {}, f"{app}'s GET /api/v1/settings answered an unexpected shape."
    raw_definitions = body.get("definitions") if isinstance(body, Mapping) else None
    definitions = {
        str(key): entry
        for key, entry in (raw_definitions or {}).items()
        if isinstance(raw_definitions, Mapping) and isinstance(entry, Mapping)
    }
    return {str(key): value for key, value in values.items()}, definitions, None


def _error_message(response: httpx.Response) -> str:
    """An application's own refusal text out of the suite's error envelope."""
    try:
        body = response.json()
    except ValueError:
        return f"{response.status_code} {response.text[:200]}"
    error = body.get("error") if isinstance(body, Mapping) else None
    if isinstance(error, Mapping) and error.get("message"):
        return f"{response.status_code} {error['message']}"
    return str(response.status_code)


def _pending_restart(path: Path, view: AppView | None, *, now: float) -> bool:
    """Whether ``config.toml`` changed after the unit started (ADR-0127 rule 5).

    Derived rather than stored. A stored flag would survive a restart the operator made from a
    terminal and would be lost when the console itself restarts; the two timestamps are the fact
    itself, and they are right however the restart happened.
    """
    if view is None or not view.running or view.uptime_seconds is None:
        return False
    try:
        changed_seconds_ago = now - path.stat().st_mtime
    except OSError:
        return False
    return changed_seconds_ago < view.uptime_seconds


def settings_form(
    settings: Settings,
    app: str,
    *,
    document: Mapping[str, Any] | None,
    document_error: str | None,
    view: AppView | None = None,
    live: Mapping[str, Any] | None = None,
    live_definitions: Mapping[str, Mapping[str, Any]] | None = None,
    config_path: Path | None = None,
    now: float | None = None,
) -> SettingsForm:
    """Build one application's form from its schema document, its file and its running process.

    Args:
        settings: The validated settings.
        app: The application.
        document: What :func:`read_schema_document` returned, or ``None``.
        document_error: Why it is ``None``.
        view: The application's view, for *running* and *pending restart*.
        live: The running application's runtime values, from :func:`live_settings`.
        config_path: The file, when the document did not say (WeightRoomGym's own page).
        now: Wall-clock seconds, injected for the pending-restart comparison.

    Returns:
        The form. Every field comes from ``document``; nothing in this function names a key of
        any application (ADR-0127 rule 3).
    """
    path = config_file_path(document, app=app, fallback=config_path)
    text, file_data, parse_error = _read_toml(path)
    live_values = dict(live or {})
    definitions = dict(live_definitions or {})
    problems = [str(one) for one in (document or {}).get("problems", []) or []]
    if parse_error:
        problems.append(parse_error)
    runtime_entries = {
        str(entry.get("key")): entry
        for entry in (document or {}).get("runtime_changeable", []) or []
        if isinstance(entry, Mapping) and entry.get("key")
    }
    security = frozenset(str(one) for one in (document or {}).get("security_keys", []) or [])
    sources = {
        str(key): str(value) for key, value in ((document or {}).get("sources") or {}).items()
    }
    json_schema = (document or {}).get("json_schema") or {}
    defs = json_schema.get("$defs") or {}
    # The key list is the document's own three sets — the application's `leaf_keys()`,
    # partitioned — not a walk of `json_schema`. The application decides where a leaf ends:
    # PromptCadence's `approval.gate_step_cost` is one Money leaf, and walking the schema would
    # split it into `.currency`/`.nanos` *and* keep the whole, which is the same key twice.
    keys = list(runtime_entries) + sorted(
        security | {str(one) for one in (document or {}).get("config_only") or []}
    )
    order = _schema_order(json_schema, defs)
    grouped: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for key in dict.fromkeys(keys):
        grouped.setdefault(key.split(".", 1)[0], []).append(key)
    seen = set(keys)
    for key in _profile_keys(document, json_schema, defs):
        # Ordered even where the key is already collected: a profile's `base_url` arrives with the
        # security keys, and without a slot here it would sort to the end of its own card.
        order.setdefault(key, len(order))
        if key not in seen:
            seen.add(key)
            grouped.setdefault(key.split(".", 1)[0], []).append(key)
            keys.append(key)
    for key in _file_keys(file_data):
        if any(key in group for group in grouped.values()):
            continue
        # A registration the operator typed (`[providers.local]`, ADR-0077) is not in the sets
        # but the model still types it, through `additionalProperties`; anything the model
        # cannot type at all is listed raw rather than invented (rule 3).
        if _schema_for_path(json_schema, defs, key) is None:
            unresolved.append(key)
        else:
            grouped.setdefault(key.split(".", 1)[0], []).append(key)
    sections: list[FormSection] = []
    for name in dict.fromkeys([*(json_schema.get("properties") or {}), *sorted(grouped)]):
        section_keys = grouped.pop(name, None)
        if not section_keys:
            continue
        section = _resolve((json_schema.get("properties") or {}).get(name, {}), defs)
        section_keys.sort(key=lambda key: (order.get(key, len(order)), key))
        sections.append(
            FormSection(
                name=str(name),
                title=str(section.get("title") or name),
                description=str(section.get("description") or ""),
                fields=tuple(
                    _build_field(
                        key,
                        _leaf_of(key),
                        _schema_for_path(json_schema, defs, key) or {},
                        runtime_entry=runtime_entries.get(key),
                        security=key in security,
                        source=sources.get(key, "default"),
                        file_data=file_data,
                        live_values=live_values,
                        definition=definitions.get(key),
                        defs=defs,
                    )
                    for key in section_keys
                ),
            )
        )
    undescribed = tuple(unresolved)
    return SettingsForm(
        app=app,
        version=str((document or {}).get("version") or ""),
        config_path=str(path),
        config_exists=path.is_file(),
        base_mtime=path.stat().st_mtime_ns if path.is_file() else None,
        sections=tuple(sections),
        undescribed=undescribed,
        problems=tuple(problems),
        provider_form=(document or {}).get("provider_form"),
        provider_profiles=_provider_profiles(document),
        document_error=document_error,
        running=bool(view is not None and view.running and view.reachable),
        pending_restart=_pending_restart(path, view, now=now if now is not None else time.time()),
        raw_toml=text,
        security_keys=security,
        runtime_keys=frozenset(runtime_entries),
    )


def _build_field(
    key: str,
    label: str,
    schema: Mapping[str, Any],
    *,
    defs: Mapping[str, Any],
    runtime_entry: Mapping[str, Any] | None,
    security: bool,
    source: str,
    file_data: Mapping[str, Any],
    live_values: Mapping[str, Any],
    definition: Mapping[str, Any] | None = None,
) -> FormField:
    """One leaf, composed from the document, the file and the running application."""
    minimum, maximum = _bounds_of(schema)
    if runtime_entry is not None:
        # The registry's own bounds win where it states them: they are what the application's
        # `PUT /settings` enforces, and a pydantic field may carry none at all.
        minimum = _stated_number(runtime_entry.get("minimum"), minimum)
        maximum = _stated_number(runtime_entry.get("maximum"), maximum)
    description = str(schema.get("description") or (runtime_entry or {}).get("description") or "")
    default = schema.get("default")
    in_file, file_value = _lookup(file_data, key)
    runtime = runtime_entry is not None
    live = runtime and key in live_values
    if live:
        value = live_values[key]
    elif in_file:
        value = file_value
    else:
        value = default
    secret = is_secret_key(key)
    kind = _kind_of(schema)
    if kind == "unknown" and runtime_entry is not None:
        kind = _REGISTRY_KINDS.get(str(runtime_entry.get("kind")), "unknown")
    return FormField(
        key=key,
        label=str(label),
        kind=kind,
        description=description,
        default=REDACTED if (secret and default) else default,
        value=REDACTED if (secret and value) else value,
        source=source,
        shadowed=source.startswith(("env ", "cli")) or "shadowed" in source,
        runtime=runtime,
        security=security,
        secret=secret,
        minimum=minimum,
        maximum=maximum,
        choices=_choices_of(schema, defs),
        live=live,
        in_file=in_file,
        nullable=_is_nullable(schema),
        applies=str((definition or {}).get("applies") or "") if runtime else "",
        stored=bool(runtime and definition is not None and definition.get("stored") is not None),
    )


def forms_for(
    settings: Settings,
    apps: Sequence[str] = APPLICATIONS,
    *,
    cache: SchemaCache,
    monotonic: float,
    config_path: Path | None = None,
) -> dict[str, SettingsForm]:
    """Every named application's form, documents only — no HTTP, for ``wr-gym doctor``.

    Args:
        settings: The validated settings.
        apps: Which applications.
        cache: The 60-second document cache.
        monotonic: A monotonic clock reading.
        config_path: WeightRoomGym's own configuration file.

    Returns:
        One form per application, in the order given.
    """
    built: dict[str, SettingsForm] = {}
    for app in apps:
        document, error = cache.get(
            app,
            now=monotonic,
            read=lambda app=app: read_schema_document(  # type: ignore[misc]
                settings, app, config_path=config_path
            ),
        )
        built[app] = settings_form(
            settings,
            app,
            document=document,
            document_error=error,
            config_path=config_path if app == "weightroom" else None,
        )
    return built


# --- Saving -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KeyOutcome:
    """What happened to one submitted key (api.md §2's per-key answer).

    Attributes:
        key: The dotted key.
        outcome: ``applied`` (live on the running application), ``written`` (in the file, pending
            restart), ``unchanged`` (the submitted value is what it already was) or ``refused``.
        message: Why it was refused, in the refusing party's own words.
        code: The spec §13 code behind a refusal, for a client that branches on it.
    """

    key: str
    outcome: str
    message: str | None = None
    code: str | None = None

    def as_json(self) -> dict[str, Any]:
        """The wire shape."""
        return {
            "key": self.key,
            "outcome": self.outcome,
            "message": self.message,
            "code": self.code,
        }


@dataclass(frozen=True, slots=True)
class SaveResult:
    """The answer to one ``PUT /apps/{app}/settings``."""

    outcomes: tuple[KeyOutcome, ...]
    base_mtime: int | None
    backup: str | None = None
    pending_restart: bool = False

    def keys_with(self, outcome: str) -> tuple[str, ...]:
        """Every key whose outcome was ``outcome``, sorted."""
        return tuple(sorted(one.key for one in self.outcomes if one.outcome == outcome))

    @property
    def refused(self) -> tuple[KeyOutcome, ...]:
        """Every refusal, for the page's error list."""
        return tuple(one for one in self.outcomes if one.outcome == "refused")

    def as_json(self) -> dict[str, Any]:
        """The wire shape."""
        return {
            "outcomes": {one.key: one.as_json() for one in self.outcomes},
            "base_mtime": self.base_mtime,
            "backup": self.backup,
            "pending_restart": self.pending_restart,
            "applied": list(self.keys_with("applied")),
            "written": list(self.keys_with("written")),
        }


def save_settings(
    settings: Settings,
    app: str,
    changes: Mapping[str, Any],
    *,
    form: SettingsForm,
    base_mtime: int | None,
    to_file: frozenset[str] = frozenset(),
    apply_runtime: Callable[[Mapping[str, Any]], tuple[bool, str | None]] | None = None,
    runner: Runner = run_command,
) -> SaveResult:
    """Route each submitted key to the file or to the running application, and report each.

    The file is written **first** and as one transaction: it is the only half that can be refused
    wholesale (a stale base, the application's own validation), so a refusal there must leave
    nothing applied anywhere. Runtime keys follow, and each carries its own outcome.

    Args:
        settings: The validated settings.
        app: The application.
        changes: Dotted key to new value, already typed (see :meth:`FormField.parse` for the
            form-post path that turns strings into these).
        form: The form the operator was looking at, for the fields and their current values.
        base_mtime: The ``st_mtime_ns`` that form was rendered from.
        to_file: Runtime keys the operator explicitly chose to write to the file instead —
            what the page offers when the application is stopped (ADR-0127 rule 4).
        apply_runtime: How to reach the application's ``PUT /api/v1/settings``; ``None`` when it
            is not running, which refuses every runtime key by name rather than guessing.
        runner: The process-launch boundary, injected.

    Returns:
        One outcome per submitted key.

    Raises:
        ConfigChangedOnDisk: The file moved since ``base_mtime``; nothing was written.
        ConfigValidationFailed: The application refused the candidate; nothing was written.
    """
    from weightroom.services.config_files import apply_changes, write_config

    outcomes: list[KeyOutcome] = []
    file_changes: dict[str, Any] = {}
    runtime_changes: dict[str, Any] = {}
    for key, value in changes.items():
        one = form.field_for(key)
        if one is None:
            outcomes.append(
                KeyOutcome(
                    key,
                    "refused",
                    f"{key} is not a setting {app} recognises.",
                    "SETTING_UNKNOWN",
                )
            )
        elif one.secret and value == REDACTED:
            outcomes.append(KeyOutcome(key, "unchanged"))
        elif value == one.value:
            # `one.secret` is not a carve-out here: a secret whose value is *empty* is rendered
            # in the clear (`REDACTED` stands in only for a value there is one of), so it comes
            # back as itself and is as unchanged as any other key (row WPF1).
            outcomes.append(KeyOutcome(key, "unchanged"))
        elif one.runtime and key not in to_file:
            runtime_changes[key] = value
        elif value is None:
            # The file names the key and the form says *unset*. TOML has no null, so that is a
            # deletion, not an edit — refused by name, and only this key, rather than failing
            # every other change in the same save inside `apply_changes` (row WPF1).
            outcomes.append(
                KeyOutcome(
                    key,
                    "refused",
                    f"{key} is set in {form.config_path}, and TOML has no null: unsetting it is a "
                    f"deletion. Remove the line in the raw editor.",
                    "CONFIG_VALIDATION_FAILED",
                )
            )
        else:
            file_changes[key] = value

    written: tuple[str, ...] = ()
    backup: str | None = None
    new_mtime = base_mtime
    if file_changes:
        path = Path(form.config_path)
        text, _ = _read_toml(path)[:2]
        try:
            candidate = apply_changes(text, file_changes)
        except ValueError as exc:
            for key in file_changes:
                outcomes.append(KeyOutcome(key, "refused", str(exc), "CONFIG_VALIDATION_FAILED"))
        else:
            landed = write_config(
                settings,
                app,
                path,
                candidate,
                base_mtime=base_mtime,
                keys=tuple(file_changes),
                runner=runner,
            )
            written = landed.keys
            backup = str(landed.backup) if landed.backup else None
            new_mtime = landed.base_mtime
            outcomes.extend(KeyOutcome(key, "written") for key in written)

    if runtime_changes:
        if apply_runtime is None:
            for key in runtime_changes:
                outcomes.append(
                    KeyOutcome(
                        key,
                        "refused",
                        f"{key} is applied by the running {app}, which is not running. Start it, "
                        f"or save the key to {form.config_path} instead.",
                        "APP_STOPPED",
                    )
                )
        else:
            ok, message = apply_runtime(runtime_changes)
            outcomes.extend(
                KeyOutcome(key, "applied") if ok else KeyOutcome(key, "refused", message, None)
                for key in runtime_changes
            )

    return SaveResult(
        outcomes=tuple(outcomes),
        base_mtime=new_mtime,
        backup=backup,
        pending_restart=form.pending_restart or bool(written),
    )

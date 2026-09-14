"""weightroom.services.config_files — editing another application's ``config.toml`` in place.

[ADR-0127](../../../docs/adr/0127-every-application-publishes-its-settings-schema-and-weightroom-generates-the-form.md)
rule 3 generalises **ADR-0117** — provider registrations are edited in place in the config file —
from LoadCoach's own provider block to every key of every application's file, edited from
*outside* the process that owns it. The sequence is that record's, in this order and for its
reasons:

1. **Refuse a stale base.** The form carries the file's modification time; a file that has moved
   since is not the file the operator was looking at, and the write is refused whole rather than
   merged (rule 7's race). Byte-level: ``st_mtime_ns``, which is exact in JSON, rather than the
   float seconds a language's ``stat`` prints.
2. **Round-trip with ``tomlkit``.** Every comment, every blank line and the order of every
   untouched key survive, because the operator's file is a document they wrote, not a serialised
   dictionary. A test round-trips each application's own ``EXAMPLE_CONFIG_TOML`` one key at a
   time and asserts the rest is byte-identical.
3. **Validate with the application's own loader**, never a reimplementation of it: the candidate
   is written beside the file and handed to ``<app> config validate --file`` (rule 2). A file
   WeightRoomGym writes is therefore a file the application would have accepted from ``$EDITOR``,
   and a refusal is the application's own words.
4. **Land it atomically**, keeping the previous file as ``config.toml.bak``: ``fsync`` the
   candidate, ``fsync`` the directory, rename over the original. A crash mid-write leaves either
   the old file or the new one, never half of either.

The one thing this module does **not** do is write a runtime-changeable key. Those go to the
running application's ``PUT /api/v1/settings`` and never touch the file (rule 4), so the file
keeps saying what the operator configured and the application keeps saying what it is running.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final

import tomlkit
from baseaicore import SuiteError

from weightroom.services.processes import child_environment, executable_for, run_command

if TYPE_CHECKING:
    from collections.abc import Mapping

    from weightroom.config import Settings
    from weightroom.services.processes import Runner

__all__ = [
    "BACKUP_SUFFIX",
    "VALIDATE_TIMEOUT_SECONDS",
    "ConfigChangedOnDisk",
    "ConfigValidationFailed",
    "WriteOutcome",
    "apply_changes",
    "base_mtime_of",
    "parse_or_reason",
    "read_config",
    "validate_candidate",
    "write_config",
]

BACKUP_SUFFIX: Final = ".bak"
"""``config.toml.bak`` — the previous file, kept by every write (ADR-0127 rule 3)."""

VALIDATE_TIMEOUT_SECONDS: Final = 30.0

_CANDIDATE_SUFFIX: Final = ".wr-gym.new"


class ConfigChangedOnDisk(SuiteError):
    """The file moved since the form was read; the write is refused whole (spec §13)."""

    code: ClassVar[str] = "CONFIG_CHANGED_ON_DISK"


class ConfigValidationFailed(SuiteError):
    """The application refused the candidate file; ``details['output']`` is its own message."""

    code: ClassVar[str] = "CONFIG_VALIDATION_FAILED"


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """What one landed write did.

    Attributes:
        path: The file written.
        backup: The previous file, or ``None`` when there was no file to keep.
        base_mtime: The new modification time, for the next write's race check.
        keys: The keys that changed, sorted.
    """

    path: Path
    backup: Path | None
    base_mtime: int
    keys: tuple[str, ...]


def base_mtime_of(path: Path) -> int | None:
    """The file's ``st_mtime_ns``, or ``None`` when there is no file yet."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def read_config(path: Path) -> tuple[str, int | None]:
    """The file's text and its base modification time; ``("", None)`` when it is not there."""
    try:
        return path.read_text(encoding="utf-8"), base_mtime_of(path)
    except OSError:
        return "", None


def apply_changes(text: str, changes: Mapping[str, Any] | Mapping[tuple[str, ...], Any]) -> str:
    """Return ``text`` with each dotted key set, and every untouched line byte-identical.

    Args:
        text: The file's current text; ``""`` for a file that does not exist yet.
        changes: Dotted key to new value. A missing intermediate table is created. A tuple names
            the path part by part, for a part that itself holds a dot — a canonical model ID.

    Returns:
        The new text.

    Raises:
        ValueError: ``text`` is not valid TOML, or a key's path runs through a value that is
            not a table (``server.port.extra`` where ``port`` is a number) — refused rather
            than silently replacing the operator's value with a table.
    """
    try:
        document = tomlkit.parse(text) if text else tomlkit.document()
    except Exception as exc:  # noqa: BLE001 — tomlkit raises several unrelated parse types
        message = f"not valid TOML: {exc}"
        raise ValueError(message) from exc
    for key, value in changes.items():
        parts = list(key) if isinstance(key, tuple) else key.split(".")
        table: Any = document
        for part in parts[:-1]:
            existing = table.get(part) if hasattr(table, "get") else None
            if existing is None:
                new_table = tomlkit.table()
                table[part] = new_table
                table = new_table
            elif hasattr(existing, "get"):
                table = existing
            else:
                message = f"{key} runs through {part}, which is a value and not a table"
                raise ValueError(message)
        table[parts[-1]] = _toml_value(value)
    return tomlkit.dumps(document)


def _toml_value(value: Any) -> Any:  # noqa: ANN401 — JSON in, TOML item out
    """A JSON-shaped value as a tomlkit item; ``None`` is not expressible and is refused."""
    if value is None:
        message = "TOML has no null: remove the key rather than setting it to nothing"
        raise ValueError(message)
    return tomlkit.item(value)


def validate_candidate(
    settings: Settings,
    app: str,
    candidate: Path,
    *,
    runner: Runner = run_command,
    config_path: Path | None = None,
) -> None:
    """Hand ``candidate`` to the application's own loader (ADR-0127 rule 2).

    Args:
        settings: The validated settings, for the executable.
        app: The application, or ``weightroom`` for the console's own file.
        candidate: The file to validate.
        runner: The process-launch boundary, injected.
        config_path: Unused for the four; present so the caller need not branch.

    Raises:
        ConfigValidationFailed: The application refused it, with its own message. An application
            that is not installed cannot validate, and that is a refusal too: writing a file no
            loader has seen is the one thing this whole path exists to prevent.
    """
    del config_path
    if app == "weightroom":
        from weightroom.config import ConfigurationError, load_settings

        try:
            load_settings(config_path=candidate)
        except ConfigurationError as exc:
            raise ConfigValidationFailed(
                f"wr-gym refused the new configuration: {exc.message}",
                details={"app": app, "output": exc.message, "file": str(candidate)},
            ) from exc
        return
    executable = executable_for(settings, app)
    if executable is None:
        raise ConfigValidationFailed(
            f"{app} is not installed, so its own validation cannot run — and a file no loader "
            f"has accepted is not written (ADR-0127 rule 2).",
            details={"app": app, "output": "", "file": str(candidate)},
        )
    argv = [executable, "config", "validate", "--file", str(candidate)]
    result = runner(argv, child_environment(), VALIDATE_TIMEOUT_SECONDS)
    if not result.ok:
        output = (result.stderr.strip() or result.stdout.strip()) or result.failure_text
        raise ConfigValidationFailed(
            f"{app} refused the new configuration: {output}",
            details={"app": app, "output": output, "file": str(candidate)},
        )


def write_config(
    settings: Settings,
    app: str,
    path: Path,
    text: str,
    *,
    base_mtime: int | None,
    keys: tuple[str, ...] = (),
    runner: Runner = run_command,
) -> WriteOutcome:
    """Validate ``text`` through the application and land it atomically, keeping a ``.bak``.

    Args:
        settings: The validated settings.
        app: The application whose file this is.
        path: The file.
        text: Its new whole text.
        base_mtime: The ``st_mtime_ns`` the form was rendered from, or ``None`` for a file that
            did not exist then. Checked before anything is written.
        keys: What changed, for the outcome and the audit row.
        runner: The process-launch boundary, injected.

    Returns:
        The outcome.

    Raises:
        ConfigChangedOnDisk: The file changed since ``base_mtime``.
        ConfigValidationFailed: The application refused the candidate; nothing was written.
        OSError: The file could not be written.
    """
    current = base_mtime_of(path)
    if current != base_mtime:
        raise ConfigChangedOnDisk(
            f"{path} changed since this page was loaded, so the write was refused rather than "
            f"overwriting an edit made elsewhere. Reload the page and apply the change again.",
            details={"file": str(path), "app": app, "base_mtime": base_mtime, "found": current},
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path.with_name(path.name + _CANDIDATE_SUFFIX)
    _write_durably(candidate, text)
    try:
        validate_candidate(settings, app, candidate, runner=runner)
    except ConfigValidationFailed:
        candidate.unlink(missing_ok=True)
        raise
    backup: Path | None = None
    if path.is_file():
        backup = path.with_name(path.name + BACKUP_SUFFIX)
        # `copy2` rather than `replace`: the original stays in place until the rename below, so
        # a crash between the two leaves the file the application is running on, not a gap.
        shutil.copy2(path, backup)
    candidate.replace(path)
    _fsync_directory(path.parent)
    return WriteOutcome(
        path=path, backup=backup, base_mtime=base_mtime_of(path) or 0, keys=tuple(sorted(keys))
    )


def _write_durably(path: Path, text: str) -> None:
    """Write and ``fsync`` one file, so the rename that follows cannot publish a partial one."""
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _fsync_directory(directory: Path) -> None:
    """``fsync`` the directory so the rename itself survives a power loss."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover — the directory was just written into
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def parse_or_reason(text: str) -> str | None:
    """``None`` when ``text`` is valid TOML, else the parser's own message.

    The raw editor checks this before anything else, so a typo is one message under the textarea
    rather than a subprocess launch and an application's less specific refusal.
    """
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return str(exc)
    return None

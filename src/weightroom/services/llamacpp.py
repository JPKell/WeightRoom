"""weightroom.services.llamacpp — what is running, what is installed, what §2.2 expects.

The `llama.cpp` pane is **read-only**, and more strictly so than the Ollama pane beside it: that
one has a polkit-gated restart button, this one has no button at all. `llama-server` is not a
unit — it is a child of FreeWeight or LoadCoach, launched by ModelRack's provider and supervised
by the application that launched it (ADR-0062). A console that killed one would be taking a model
away from a run the owning application still believes it has, and a console that *launched* one
would be a fifth peer application (ADR-0123 rule 4, spec §3: ModelRack is imported for residency
and discovery reads only). So this module discovers, reads and compares, and that is all it does.

Three reads make the page:

* **Running servers** — ``pgrep -x llama-server`` for the pids, then ``/proc/<pid>/cmdline`` for
  each one's argv. ``-x`` and never ``-f``: a pattern match over whole command lines would find
  this console's own processes and any editor holding the string, and killing on the strength of
  such a match is how the wrong process dies (a standing rule of this workspace). The port,
  model, context and ``--fit`` are read out of the argv the server was actually launched with,
  not out of what a configuration file says it would launch with.
* **The served context** — ``GET /props`` on the port that argv names, where it answers. This is
  the *reported* served context (ADR-0023 §4): a server launched under ``--fit on`` with no
  ``--ctx-size`` serves whatever fitted, and only the server can say what that was.
* **The GGUF directories** — the ``model_directory`` keys FreeWeight and LoadCoach configure,
  read from their own ``config schema --json`` documents through :mod:`settings_forms` rather
  than from a path this module knows. Nothing here names a key of any application except through
  that document (ADR-0127 rule 3 in spirit: the application decides where its models live).

And one comparison: ``MEMORY_SAFETY.md`` §2.2's expectations of the two applications that launch
`llama-server`, as found/expected rows. The unit half is the doctor's own
:func:`~weightroom.services.doctor.unit_cap_findings`, unchanged — the doctor and this page must
never disagree about whether a unit is capped.
"""

from __future__ import annotations

import logging
import shutil
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from weightroom.services.processes import child_environment, run_command

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from weightroom.config import Settings
    from weightroom.services.doctor import Finding
    from weightroom.services.processes import Runner, SystemdController
    from weightroom.services.settings_forms import SettingsForm

__all__ = [
    "DOCUMENT",
    "MAX_GGUF_FILES",
    "PROPS_TIMEOUT_SECONDS",
    "SETUP_DOCUMENT",
    "Check",
    "DirectoryView",
    "GgufFile",
    "LlamaCppReport",
    "ServerView",
    "find_servers",
    "llamacpp_report",
    "read_props",
]

logger = logging.getLogger(__name__)

DOCUMENT: Final = "MEMORY_SAFETY.md §2.2"
"""What the checklist on this page is quoting; every row names it, as the Ollama pane does."""

SETUP_DOCUMENT: Final = "LLAMACPP_SETUP.md"
"""How the binary and the models get onto this host in the first place; linked from the page."""

PROPS_TIMEOUT_SECONDS: Final = 2.0
"""A server that is busy generating still answers ``/props`` promptly; one that does not is a
figure this page reports as unavailable rather than a page that hangs."""

MAX_GGUF_FILES: Final = 200
"""How many files one directory listing shows. A model directory is a handful of files; a
directory that holds hundreds is being used for something else, and the page says how many it
did not list rather than rendering them all."""

_LLAMACPP_KIND: Final = "llamacpp"
"""The provider kind both applications spell the same way (ADR-0077)."""


# --- running servers ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServerView:
    """One running ``llama-server``, as its own command line and its own ``/props`` describe it.

    Attributes:
        pid: The process id ``pgrep -x llama-server`` returned.
        port: ``--port`` from the argv, or ``None`` when the argv does not name one. Never
            llama.cpp's documented 8080 default filled in: a guessed port would be read from
            whatever else is listening there, and an invented figure is worse than a missing one.
        model: ``--model``'s path, or ``None``.
        context_size: ``--ctx-size`` as launched, or ``None`` when it was left unset — which is
            the case ``--fit`` then decides (``MEMORY_SAFETY.md`` §5).
        fit: ``--fit``'s value as launched, or ``None`` when the flag is absent — absent means
            llama-server's own default, ``on``, and the page says so rather than printing ``on``
            as though it had been read.
        argv: The whole command line, for an operator who wants to see it.
        served_context_tokens: ``/props``'s ``default_generation_settings.n_ctx`` — what the
            server reports it is actually serving.
        build_info: ``/props``'s ``build_info``.
        props_error: Why ``/props`` could not be read, when it could not.
    """

    pid: int
    port: int | None
    model: str | None
    context_size: int | None
    fit: str | None
    argv: tuple[str, ...]
    served_context_tokens: int | None = None
    build_info: str | None = None
    props_error: str | None = None

    @property
    def model_name(self) -> str:
        """The GGUF's file name, which is what identifies it to a person; ``—`` when unknown."""
        return Path(self.model).name if self.model else "—"

    def as_json(self) -> dict[str, Any]:
        """The shape the page renders from."""
        return {
            "pid": self.pid,
            "port": self.port,
            "model": self.model,
            "context_size": self.context_size,
            "fit": self.fit,
            "argv": list(self.argv),
            "served_context_tokens": self.served_context_tokens,
            "build_info": self.build_info,
            "props_error": self.props_error,
        }


def _argv_of(pid: int) -> tuple[str, ...]:
    """The process's own command line from ``/proc``, or ``()`` when it cannot be read.

    A process that exited between ``pgrep`` and this read is gone, not an error: the row simply
    carries no argv. No second process is launched to ask — ``/proc`` is a file.
    """
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ()
    return tuple(part for part in raw.decode("utf-8", "replace").split("\0") if part)


def _option(argv: Sequence[str], *names: str) -> str | None:
    """The value of the last occurrence of any of ``names``, in either spelling.

    ``--ctx-size 32768`` and ``--ctx-size=32768`` are the same launch; llama.cpp accepts both and
    ModelRack has used both spellings across versions. The *last* occurrence wins because that is
    what the server itself does with a repeated flag.
    """
    found: str | None = None
    for index, token in enumerate(argv):
        if token in names:
            if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
                found = argv[index + 1]
            continue
        for name in names:
            if token.startswith(f"{name}="):
                found = token[len(name) + 1 :]
    return found


def _as_int(value: str | None) -> int | None:
    """``value`` as an integer, or ``None`` — a flag whose value is not a number is not a number."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def read_props(port: int) -> tuple[Mapping[str, Any] | None, str | None]:
    """Read one server's ``/props``, or say why it could not be read.

    Args:
        port: The port the server's own argv named.

    Returns:
        ``(props, None)`` or ``(None, reason)``. Never raises: a server that is loading, busy or
        already gone is a state this page renders, not an exception the request fails on.
    """
    import httpx

    try:
        with httpx.Client(timeout=PROPS_TIMEOUT_SECONDS, trust_env=False) as client:
            response = client.get(f"http://127.0.0.1:{port}/props")
            response.raise_for_status()
            body = response.json()
    except Exception as exc:  # noqa: BLE001 — every failure here is a fact the page shows
        logger.info("llamacpp.props_unavailable", extra={"port": port, "detail": str(exc)})
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(body, dict):
        return None, "/props did not answer a JSON object."
    return body, None


def _served_context(props: Mapping[str, Any]) -> int | None:
    """``default_generation_settings.n_ctx`` — the per-slot context the server actually built."""
    settings = props.get("default_generation_settings")
    if not isinstance(settings, Mapping):
        return None
    value = settings.get("n_ctx")
    return int(value) if isinstance(value, int) else None


def find_servers(
    settings: Settings,
    *,
    runner: Runner = run_command,
    which: Callable[[str], str | None] = shutil.which,
    props: Callable[[int], tuple[Mapping[str, Any] | None, str | None]] = read_props,
) -> tuple[tuple[ServerView, ...], str | None]:
    """Every running ``llama-server``, with what its argv and its ``/props`` say.

    Args:
        settings: The validated settings, for the executable lookup.
        runner: The process-launch boundary, injected as everywhere else in this repository.
        which: Executable lookup, injected.
        props: The ``/props`` reader, injected so a test needs no server.

    Returns:
        ``(servers, None)``, or ``((), reason)`` when ``pgrep`` itself could not be run — a host
        with no ``pgrep`` reports that by name rather than showing an empty list that would read
        as *nothing is running*. An empty tuple with no reason means exactly what it says.
    """
    del settings  # the binary is found on PATH, not configured: nothing here is a unit
    pgrep = which("pgrep")
    if pgrep is None:
        return (), "`pgrep` was not found on PATH, so running servers cannot be discovered."
    result = runner([pgrep, "-x", "llama-server"], child_environment(), 5.0)
    if result.timed_out:
        return (), "`pgrep -x llama-server` timed out."
    if result.returncode == 1:
        return (), None  # pgrep's own word for "nothing matched"
    if result.returncode != 0:
        return (), f"`pgrep -x llama-server` failed: {result.stderr.strip() or result.returncode}"
    servers = []
    for line in result.stdout.split():
        pid = _as_int(line)
        if pid is None:
            continue
        argv = _argv_of(pid)
        port = _as_int(_option(argv, "--port"))
        view = ServerView(
            pid=pid,
            port=port,
            model=_option(argv, "--model", "-m"),
            context_size=_as_int(_option(argv, "--ctx-size", "-c")),
            fit=_option(argv, "--fit"),
            argv=argv,
        )
        if port is not None:
            body, error = props(port)
            view = ServerView(
                pid=view.pid,
                port=view.port,
                model=view.model,
                context_size=view.context_size,
                fit=view.fit,
                argv=view.argv,
                served_context_tokens=None if body is None else _served_context(body),
                build_info=None if body is None else str(body.get("build_info") or "") or None,
                props_error=error,
            )
        servers.append(view)
    return tuple(sorted(servers, key=lambda one: one.pid)), None


# --- the GGUF directories -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GgufFile:
    """One ``.gguf`` in a configured directory."""

    name: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class DirectoryView:
    """One ``model_directory`` an application configures, and what is in it.

    Attributes:
        app: Which application configures it.
        key: The dotted key it is configured under, so the operator can find it on the settings
            page — ``provider.model_directory``, ``providers.local.model_directory``.
        path: The directory, with ``~`` already expanded as the application expands it.
        exists: Whether it is there.
        error: Why it could not be listed, when it could not.
        files: The GGUFs found, largest first, capped at :data:`MAX_GGUF_FILES`.
        omitted: How many more there were.
    """

    app: str
    key: str
    path: str
    exists: bool
    error: str | None = None
    files: tuple[GgufFile, ...] = ()
    omitted: int = 0

    @property
    def total_bytes(self) -> int:
        """How much disk the listed GGUFs take."""
        return sum(one.size_bytes for one in self.files)


def _values(form: SettingsForm) -> dict[str, str]:
    """One application's whole configuration as dotted key to text.

    Two sources, because one is not enough. :class:`SettingsForm`'s typed fields carry the
    *effective* value — the running application's, else the file's, else the default — which is
    what a check should be read against. But LoadCoach's ``[providers.<name>]`` registrations are
    typed through ``additionalProperties`` at a path (``providers.registrations.<name>``) that is
    not the path the file writes (``providers.<name>``), so the document cannot type them and they
    reach the form as :attr:`SettingsForm.undescribed` — names with no values (measured on the
    operator's own LoadCoach at row WX3). The file behind the form is therefore read as well, and
    a typed field wins wherever there is one.
    """
    values: dict[str, str] = {}
    try:
        _flatten(tomllib.loads(form.raw_toml), "", values)
    except (tomllib.TOMLDecodeError, ValueError):
        pass  # the form already carries the parse error as a problem; this page shows what it can
    for one in form.fields():
        values[one.key] = one.value_text
    return values


def _flatten(data: Mapping[str, Any], prefix: str, into: dict[str, str]) -> None:
    """Every leaf of a parsed TOML document, as ``a.b.c`` to the value written as TOML again.

    TOML rather than Python's ``repr``, so that a value read from the file and the same value read
    from a typed field compare as the same text: ``true``, not ``True``.
    """
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            _flatten(value, f"{path}.", into)
        elif isinstance(value, bool):
            into[path] = "true" if value else "false"
        else:
            into[path] = "" if value is None else str(value)


def _directories(forms: Mapping[str, SettingsForm]) -> tuple[DirectoryView, ...]:
    """Every ``model_directory`` the given forms describe, listed."""
    views = []
    for app, form in forms.items():
        for key, value in sorted(_values(form).items()):
            if key.rsplit(".", 1)[-1] != "model_directory" or not value.strip():
                continue
            views.append(_list_directory(app, key, Path(value.strip()).expanduser()))
    return tuple(views)


def _list_directory(app: str, key: str, path: Path) -> DirectoryView:
    """One directory's GGUFs, largest first; a directory that cannot be read says why."""
    try:
        entries = sorted(
            (one for one in path.iterdir() if one.suffix == ".gguf" and one.is_file()),
            key=lambda one: one.stat().st_size,
            reverse=True,
        )
    except FileNotFoundError:
        return DirectoryView(app=app, key=key, path=str(path), exists=False)
    except OSError as exc:
        return DirectoryView(app=app, key=key, path=str(path), exists=True, error=str(exc))
    return DirectoryView(
        app=app,
        key=key,
        path=str(path),
        exists=True,
        files=tuple(
            GgufFile(name=one.name, size_bytes=one.stat().st_size)
            for one in entries[:MAX_GGUF_FILES]
        ),
        omitted=max(len(entries) - MAX_GGUF_FILES, 0),
    )


# --- the §2.2 checklist ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    """One found/expected line, in the shape the Ollama pane's checklist already renders.

    Attributes:
        app: Which application it concerns.
        subject: What was read — a dotted configuration key, or a unit and its properties.
        found: What is actually set.
        expected: What the document asks for.
        outcome: ``pass``, ``fail`` or ``unknown``. Never a guess: a key nobody has configured
            and a key configured wrongly are different answers.
        why: What the setting protects against, in the operator's terms.
        document: Where the expectation comes from.
    """

    app: str
    subject: str
    found: str
    expected: str
    outcome: str
    why: str
    document: str = DOCUMENT


@dataclass(frozen=True, slots=True)
class _Expect:
    """One expectation of a configuration key, matched by :func:`fnmatch` pattern.

    The pattern is why a LoadCoach *registration* can be checked at all: FreeWeight has one
    ``[provider]`` table and LoadCoach has as many ``[providers.<name>]`` tables as the operator
    wrote (ADR-0077), so the same rule has to reach ``providers.*.memory_max_bytes``.
    """

    app: str
    pattern: str
    expected: str
    why: str


_SET: Final = "(set)"
"""An expectation satisfied by any value at all — the key being unset is the hazard."""

_EXPECTATIONS: Final[tuple[_Expect, ...]] = (
    _Expect(
        "freeweight",
        "provider.memory_max_bytes",
        _SET,
        "an uncapped llama-server: the unit caps FreeWeight, this caps the server itself "
        "(§3.1's inner belt). Without it a context that does not fit takes the host's RAM.",
    ),
    _Expect(
        "freeweight",
        "runtime.context_size",
        _SET,
        "the server's own default context. Unset is what put a 112 k KV cache on a 16 GB card "
        "(§1 fact 1); a measurement should state the context it measured.",
    ),
    _Expect(
        "freeweight",
        "runtime.fit_to_device",
        "false",
        "a fitted launch recorded as an unfitted profile. FreeWeight launches with `--fit off` "
        "so that a context which does not fit refuses instead of silently spilling into host "
        "RAM, which `max_context_fit` needs in order to have anything to measure (ADR-0121 §2).",
    ),
    _Expect(
        "loadcoach",
        "providers.*.memory_max_bytes",
        _SET,
        "an uncapped llama-server under LoadCoach (§3.1). LoadCoach keeps `--fit on` by design, "
        "so the cap is the only thing standing between a bad fit and the host.",
    ),
    _Expect(
        "loadcoach",
        "runtime.context_size",
        _SET,
        "the server's own default context (§1 fact 1), which for an agent loop is the size every "
        "unsized request gets.",
    ),
)
"""What ``MEMORY_SAFETY.md`` asks of the two applications that launch `llama-server`.

Every row is a definite expectation with a definite reading. A conditional one — §3.2's
``benchmarks.max_fit_context_tokens``, whose right value depends on which provider the machine is
measuring — is deliberately absent: a checklist line that cannot be failed is a line that stops
being read, which is the same reason the doctor does not flag IdeaPress's uncapped unit.
"""


def _uses_llamacpp(form: SettingsForm) -> tuple[bool, str]:
    """Whether the application is configured to launch `llama-server`, and what it says instead.

    Both spellings of the provider block are read the same way: FreeWeight's single
    ``provider.kind`` and every LoadCoach ``providers.<name>.kind``.
    """
    kinds = [
        value.strip()
        for key, value in _values(form).items()
        if key == "provider.kind" or fnmatch(key, "providers.*.kind")
    ]
    named = sorted({kind for kind in kinds if kind})
    return (_LLAMACPP_KIND in named, ", ".join(named))


def _checks(forms: Mapping[str, SettingsForm]) -> tuple[tuple[Check, ...], dict[str, str]]:
    """The configuration half of the checklist, and why an application was skipped.

    Returns:
        The checks, and a map of application to the provider kinds it is configured for where
        that kind is not llama.cpp — the page says *this does not apply to FreeWeight, which is
        configured for ollama* rather than showing rows that can only ever fail.
    """
    checks: list[Check] = []
    skipped: dict[str, str] = {}
    for app, form in forms.items():
        uses, kinds = _uses_llamacpp(form)
        if not uses:
            skipped[app] = kinds
            continue
        values = _values(form)
        for expectation in _EXPECTATIONS:
            if expectation.app != app:
                continue
            matched = sorted(key for key in values if fnmatch(key, expectation.pattern))
            if not matched:
                checks.append(
                    Check(
                        app=app,
                        subject=expectation.pattern,
                        found="not configured",
                        expected=expectation.expected,
                        outcome="unknown",
                        why=expectation.why,
                    )
                )
                continue
            checks.extend(
                Check(
                    app=app,
                    subject=key,
                    found=values[key] or "unset",
                    expected=expectation.expected,
                    outcome=_outcome(values[key], expectation.expected),
                    why=expectation.why,
                )
                for key in matched
            )
    return tuple(checks), skipped


def _outcome(found: str, expected: str) -> str:
    """``pass`` or ``fail`` for one value against one expectation."""
    text = (found or "").strip()
    if expected == _SET:
        return "pass" if text and text.lower() not in ("none", "null") else "fail"
    return "pass" if text.lower() == expected.lower() else "fail"


# --- the report -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LlamaCppReport:
    """Everything the ``/llamacpp`` page renders.

    Attributes:
        servers: Running ``llama-server`` processes.
        servers_error: Why discovery could not run, when it could not.
        directories: The configured GGUF directories and what is in them.
        checks: The configuration half of ``MEMORY_SAFETY.md`` §2.2.
        unit_findings: The unit half, from the doctor, so the two pages cannot disagree.
        skipped: Applications not configured for llama.cpp, with the kind they use instead.
        binary: ``llama-server`` on ``PATH``, or ``None`` — the applications launch it by
            configured path, so an absent binary here is information, not a failure.
    """

    servers: tuple[ServerView, ...] = ()
    servers_error: str | None = None
    directories: tuple[DirectoryView, ...] = ()
    checks: tuple[Check, ...] = ()
    unit_findings: tuple[Finding, ...] = ()
    skipped: Mapping[str, str] = field(default_factory=dict)
    binary: str | None = None

    @property
    def passing(self) -> int:
        """How many checklist lines pass — both halves."""
        return sum(1 for one in self.checks if one.outcome == "pass") + sum(
            1 for one in self.unit_findings if one.severity == "ok"
        )

    @property
    def total(self) -> int:
        """How many checklist lines there are."""
        return len(self.checks) + len(self.unit_findings)

    @property
    def safe(self) -> bool:
        """Whether every line passes; a page with nothing to check is not *safe*, it is empty."""
        return self.total > 0 and self.passing == self.total


def llamacpp_report(
    settings: Settings,
    *,
    forms: Mapping[str, SettingsForm],
    controller: SystemdController,
    runner: Runner = run_command,
    which: Callable[[str], str | None] = shutil.which,
    props: Callable[[int], tuple[Mapping[str, Any] | None, str | None]] = read_props,
) -> LlamaCppReport:
    """Build the whole pane: running servers, configured directories and the §2.2 checklist.

    Args:
        settings: The validated settings.
        forms: FreeWeight's and LoadCoach's settings forms — the only place any key of any
            application is named, and they come from those applications' own documents.
        controller: The systemd boundary, for the unit half of the checklist.
        runner: The process-launch boundary, injected.
        which: Executable lookup, injected.
        props: The ``/props`` reader, injected.

    Returns:
        The report. Nothing here launches, stops or signals anything, and nothing here writes.
    """
    from weightroom.services.doctor import unit_cap_findings

    servers, servers_error = find_servers(settings, runner=runner, which=which, props=props)
    checks, skipped = _checks(forms)
    return LlamaCppReport(
        servers=servers,
        servers_error=servers_error,
        directories=_directories(forms),
        checks=checks,
        unit_findings=tuple(unit_cap_findings(settings, controller=controller)),
        skipped=skipped,
        binary=which("llama-server"),
    )

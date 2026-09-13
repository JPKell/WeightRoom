"""The llama.cpp pane (row WX3): discovery, the GGUF directories and the §2.2 checklist.

Nothing here mocks a subprocess either: :func:`tests.support.fake_application` gives the two
applications real executables answering their own committed schema documents, and the ``pgrep``
boundary is the same injected runner every other process read in this repository goes through.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests.support import Console, build_console, fake_application
from weightroom.services.llamacpp import (
    LlamaCppReport,
    ServerView,
    find_servers,
    llamacpp_report,
)
from weightroom.services.processes import CommandResult, FakeSystemdController
from weightroom.services.settings_forms import SchemaCache, forms_for

CAPPED = {"MemoryHigh": "22G", "MemoryMax": "24G", "MemorySwapMax": "0"}
"""A unit that carries MEMORY_SAFETY.md §2.2's three lines."""

FREEWEIGHT_SAFE = """
[provider]
kind = "llamacpp"
model_directory = "{directory}"
memory_max_bytes = 25769803776

[runtime]
context_size = 8192
fit_to_device = false
"""

LOADCOACH_SAFE = """
[providers.local]
kind = "llamacpp"
model_directory = "{directory}"
memory_max_bytes = 25769803776

[runtime]
context_size = 8192
"""


def _runner(pids: str, *, returncode: int = 0) -> Any:  # noqa: ANN401 — the injected Runner
    def run(argv: Any, env: Any, timeout_seconds: float = 0.0) -> CommandResult:
        assert list(argv)[1:] == ["-x", "llama-server"], argv  # never -f
        return CommandResult(tuple(argv), returncode=returncode, stdout=pids, stderr="")

    return run


def _console(
    tmp_path: Path,
    *,
    freeweight: str = "",
    loadcoach: str = "",
    capped: bool = True,
) -> Console:
    extra = []
    for app, toml in (("freeweight", freeweight), ("loadcoach", loadcoach)):
        executable, _config, _document = fake_application(tmp_path, app, config_toml=toml)
        extra.append(f'[apps.{app}]\nexecutable = "{executable}"\n')
    properties = {f"{app}.service": dict(CAPPED) for app in ("freeweight", "loadcoach")}
    return build_console(
        tmp_path / "console",
        extra_toml="".join(extra),
        systemd=FakeSystemdController(
            states={"freeweight.service": "active", "loadcoach.service": "active"},
            properties=properties if capped else {},
        ),
    )


def _report(console: Console, **kwargs: Any) -> LlamaCppReport:
    assert console.host is not None
    forms = forms_for(
        console.settings, ("freeweight", "loadcoach"), cache=SchemaCache(), monotonic=0.0
    )
    return llamacpp_report(console.settings, forms=forms, controller=console.host, **kwargs)


# --- discovery -------------------------------------------------------------------------------


def test_discovery_matches_the_process_name_exactly_and_never_a_command_line(
    tmp_path: Path,
) -> None:
    """`pgrep -x`, never `-f`: the runner asserts the argv it is handed."""
    console = _console(tmp_path)
    servers, error = find_servers(
        console.settings,
        runner=_runner(""),
        which=lambda name: f"/usr/bin/{name}",
        props=lambda _port: (None, "not called"),
    )
    assert error is None
    assert servers == ()


def test_nothing_running_is_not_an_error_but_no_pgrep_is(tmp_path: Path) -> None:
    console = _console(tmp_path)
    settings = console.settings
    empty, error = find_servers(
        settings,
        runner=_runner("", returncode=1),  # pgrep's own word for "nothing matched"
        which=lambda name: f"/usr/bin/{name}",
    )
    assert (empty, error) == ((), None)
    _none, reason = find_servers(settings, runner=_runner(""), which=lambda _name: None)
    assert reason is not None
    assert "pgrep" in reason


def test_a_found_server_is_described_by_its_own_argv_and_its_own_props(tmp_path: Path) -> None:
    """The row's contract: pid, port, --model, --ctx-size, --fit, and /props' n_ctx."""
    console = _console(tmp_path)
    props = {
        "build_info": "b10792-3e1f9a2c",
        "default_generation_settings": {"n_ctx": 8192},
    }
    servers, error = find_servers(
        console.settings,
        runner=_runner(f"{os.getpid()}\n"),
        which=lambda name: f"/usr/bin/{name}",
        props=lambda _port: (props, None),
    )
    assert error is None
    assert len(servers) == 1
    # This process's own /proc entry is the argv read; it is pytest's, which names no llama.cpp
    # flag — the point proved here is that the read happened and invented nothing.
    assert servers[0].pid == os.getpid()
    # Whatever launched this test (`python -m pytest`, `.venv/bin/pytest`, …) is argv[0]; the read
    # is proved by matching this process's own cmdline, not by guessing the launcher's name.
    own_argv = Path("/proc/self/cmdline").read_bytes().split(b"\0")[0].decode()
    assert servers[0].argv[0] == own_argv
    assert servers[0].port is None
    assert servers[0].served_context_tokens is None  # no port: /props was not asked
    assert servers[0].build_info is None


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("llama-server", "--ctx-size", "32768"), 32768),
        (("llama-server", "--ctx-size=32768"), 32768),
        (("llama-server", "-c", "16384"), 16384),
        (("llama-server", "--ctx-size", "8192", "--ctx-size", "32768"), 32768),
        (("llama-server", "--ctx-size", "--fit"), None),
        (("llama-server",), None),
    ],
)
def test_both_spellings_of_a_flag_are_read_and_the_last_one_wins(
    argv: tuple[str, ...], expected: int | None
) -> None:
    from weightroom.services.llamacpp import _as_int, _option

    assert _as_int(_option(argv, "--ctx-size", "-c")) == expected


def test_an_unset_fit_flag_is_reported_as_unset_not_as_on() -> None:
    """llama-server defaults to `--fit on`; the page must not print a value it never read."""
    view = ServerView(pid=1, port=None, model=None, context_size=None, fit=None, argv=())
    assert view.fit is None
    assert view.model_name == "—"


# --- the checklist ----------------------------------------------------------------------------


def test_a_correctly_configured_pair_passes_every_line(tmp_path: Path) -> None:
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "qwen3.5-9b-q8_0.gguf").write_bytes(b"0" * 2048)
    console = _console(
        tmp_path,
        freeweight=FREEWEIGHT_SAFE.format(directory=directory),
        loadcoach=LOADCOACH_SAFE.format(directory=directory),
    )
    report = _report(console, runner=_runner(""), which=lambda name: f"/usr/bin/{name}")
    assert report.skipped == {}
    assert report.safe, [
        (one.subject, one.found, one.expected) for one in report.checks if one.outcome != "pass"
    ]
    assert report.total == len(report.checks) + 2  # the two unit caps
    listed = {(one.app, one.key) for one in report.directories}
    assert listed == {
        ("freeweight", "provider.model_directory"),
        ("loadcoach", "providers.local.model_directory"),
    }
    assert [one.name for one in report.directories[0].files] == ["qwen3.5-9b-q8_0.gguf"]


def test_fit_on_under_freeweight_and_an_uncapped_launcher_both_fail(tmp_path: Path) -> None:
    """ADR-0121 §2 and §3.1: the two settings a measurement and the host each depend on."""
    console = _console(
        tmp_path,
        freeweight=FREEWEIGHT_SAFE.format(directory=tmp_path)
        .replace("fit_to_device = false", "fit_to_device = true")
        .replace("memory_max_bytes = 25769803776\n", ""),
    )
    report = _report(console, runner=_runner(""), which=lambda name: f"/usr/bin/{name}")
    failed = {one.subject: one for one in report.checks if one.outcome == "fail"}
    assert failed["runtime.fit_to_device"].found == "true"
    assert failed["runtime.fit_to_device"].expected == "false"
    assert "provider.memory_max_bytes" in failed
    assert not report.safe


def test_an_application_not_on_llamacpp_is_skipped_by_name_rather_than_failed(
    tmp_path: Path,
) -> None:
    """A checklist line that can only ever fail is a line that stops being read (doctor, W4)."""
    console = _console(tmp_path, freeweight='[provider]\nkind = "ollama"\n')
    report = _report(console, runner=_runner(""), which=lambda name: f"/usr/bin/{name}")
    assert dict(report.skipped)["freeweight"] == "ollama"
    assert [one for one in report.checks if one.app == "freeweight"] == []
    # The unit cap still applies: it protects the host from whatever the application launches.
    assert {one.app for one in report.unit_findings} == {"freeweight", "loadcoach"}


def test_a_registration_with_no_memory_cap_is_found_through_the_wildcard(tmp_path: Path) -> None:
    """LoadCoach has as many `[providers.<name>]` tables as the operator wrote (ADR-0077)."""
    console = _console(
        tmp_path,
        loadcoach=LOADCOACH_SAFE.format(directory=tmp_path).replace(
            "memory_max_bytes = 25769803776\n", ""
        ),
    )
    report = _report(console, runner=_runner(""), which=lambda name: f"/usr/bin/{name}")
    caps = [one for one in report.checks if one.subject.endswith("memory_max_bytes")]
    assert [one.outcome for one in caps] == ["unknown"]
    assert caps[0].found == "not configured"


def test_a_missing_model_directory_says_so_rather_than_listing_nothing(tmp_path: Path) -> None:
    console = _console(
        tmp_path,
        freeweight=FREEWEIGHT_SAFE.format(directory=tmp_path / "gone"),
    )
    report = _report(console, runner=_runner(""), which=lambda name: f"/usr/bin/{name}")
    directory = next(one for one in report.directories if one.app == "freeweight")
    assert directory.exists is False
    assert directory.files == ()


# --- the page ---------------------------------------------------------------------------------


def test_the_page_renders_read_only_and_carries_no_form(tmp_path: Path) -> None:
    """The row's rule, on the page itself: no launch, no kill, and it says so."""
    directory = tmp_path / "models"
    directory.mkdir()
    (directory / "gemma-4-12b.q4_k_m.gguf").write_bytes(b"0" * 4096)
    console = _console(
        tmp_path,
        freeweight=FREEWEIGHT_SAFE.format(directory=directory),
        loadcoach=LOADCOACH_SAFE.format(directory=directory),
    )
    console.login()
    response = console.client.get("/llamacpp", headers={"Accept": "text/html"})
    assert response.status_code == 200
    page = response.text
    body = page[page.index('class="shell-main"') :]
    assert "<form" not in body  # read-only: no button reaches a model server
    assert "This page reads and never acts" in body
    assert "residency and discovery reads only" in body
    assert "gemma-4-12b.q4_k_m.gguf" in body
    assert "MEMORY_SAFETY.md" in body
    assert "/docs/page?path=LLAMACPP_SETUP.md" in body
    assert 'id="llamacpp-memory-safety"' in body


def test_the_page_is_reachable_from_the_console_menu_and_needs_a_session(tmp_path: Path) -> None:
    console = _console(tmp_path)
    assert console.client.get("/llamacpp", follow_redirects=False).status_code == 401
    console.login()
    page = console.client.get("/", headers={"Accept": "text/html"}).text
    assert '<a href="/llamacpp">llama.cpp</a>' in page


def test_served_context_reads_a_live_props_body() -> None:
    """A running server's ``/props`` is read at runtime — ``Mapping`` must exist there, not only
    under ``TYPE_CHECKING`` (WX14 found the page 500 the first time a llama-server was up)."""
    from weightroom.services.llamacpp import _served_context

    assert _served_context({"default_generation_settings": {"n_ctx": 8192}}) == 8192
    assert _served_context({"default_generation_settings": "no"}) is None
    assert _served_context({}) is None

"""The settings write paths, over a real executable that answers ADR-0127's two verbs.

Nothing here mocks a subprocess: :func:`tests.support.fake_application` writes a shell script
that prints one of the four committed schema documents and refuses a marked candidate file, so
the argv, the exit code and the application's own refusal text are all exercised.
"""

from __future__ import annotations

import json
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from tests.support import (
    JSON_HEADERS,
    PASSWORD,
    REFUSAL_MARKER,
    Console,
    build_console,
    fake_application,
)
from weightroom.services.processes import FakeSystemdController, UnitState

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXAMPLES = FIXTURES / "config" / "examples"
SCHEMAS = FIXTURES / "schemas"


def _state(running: bool) -> UnitState:  # noqa: FBT001 — a test helper, not a public boundary
    return "active" if running else "inactive"


def _console(
    tmp_path: Path,
    app: str = "loadcoach",
    *,
    config_toml: str = "",
    running: bool = False,
    document: dict[str, Any] | None = None,
    schema_exit: int = 0,
) -> tuple[Console, Path]:
    executable, config_path, _document = fake_application(
        tmp_path, app, config_toml=config_toml, document=document, schema_exit=schema_exit
    )
    console = build_console(
        tmp_path / "console",
        extra_toml=f'[apps.{app}]\nexecutable = "{executable}"\n',
        systemd=FakeSystemdController(states={f"{app}.service": _state(running)}),
    )
    return console, config_path


def _put(console: Console, app: str, changes: dict[str, Any], **extra: Any) -> Any:  # noqa: ANN401
    return console.client.put(
        f"/api/v1/apps/{app}/settings",
        json={"changes": changes, **extra},
        headers=JSON_HEADERS,
    )


def _base_mtime(console: Console, app: str) -> int | None:
    body = console.client.get(f"/api/v1/apps/{app}/settings", headers=JSON_HEADERS).json()
    mtime: int | None = body["base_mtime"]
    return mtime


# --- Reading -------------------------------------------------------------------------------


def test_the_schema_route_answers_the_applications_own_document(tmp_path: Path) -> None:
    console, _config = _console(tmp_path)
    console.login()
    body = console.client.get("/api/v1/apps/loadcoach/settings/schema").json()
    assert body["application"] == "loadcoach"
    assert body["schema_version"] == "1.0"


def test_an_application_that_cannot_describe_itself_answers_the_reason(tmp_path: Path) -> None:
    console, _config = _console(tmp_path, schema_exit=2)
    console.login()
    response = console.client.get("/api/v1/apps/loadcoach/settings/schema")
    assert response.status_code == 409
    assert "config schema --json` failed" in response.json()["reason"]


def test_the_settings_route_names_every_keys_source_and_sets(tmp_path: Path) -> None:
    console, _config = _console(tmp_path, config_toml="[server]\nport = 9001\n")
    console.login()
    body = console.client.get("/api/v1/apps/loadcoach/settings", headers=JSON_HEADERS).json()
    fields = {one["key"]: one for section in body["sections"] for one in section["fields"]}
    assert fields["server.port"]["value"] == 9001
    assert "queue.paused" in body["runtime_changeable"]
    assert "server.host" in body["security_keys"]


def test_the_config_route_carries_the_text_and_the_base_mtime(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="# mine\n[server]\nport = 8766\n")
    console.login()
    body = console.client.get("/api/v1/apps/loadcoach/config", headers=JSON_HEADERS).json()
    assert body["text"] == "# mine\n[server]\nport = 8766\n"
    assert body["base_mtime"] == config.stat().st_mtime_ns


# --- Writing to the file --------------------------------------------------------------------


def test_a_file_key_is_written_and_the_comment_above_it_survives(tmp_path: Path) -> None:
    original = '# the port the operator chose\n[server]\nport = 8766\nhost = "127.0.0.1"\n'
    console, config = _console(tmp_path, config_toml=original)
    console.login()
    console.client.post("/api/v1/reauth", json={"password": PASSWORD}, headers=JSON_HEADERS)
    body = _put(
        console, "loadcoach", {"server.port": 9100}, base_mtime=_base_mtime(console, "loadcoach")
    ).json()
    assert body["outcomes"]["server.port"]["outcome"] == "written"
    text = config.read_text()
    assert "# the port the operator chose" in text
    assert "port = 9100" in text
    assert 'host = "127.0.0.1"' in text
    assert config.with_name("config.toml.bak").read_text() == original


def test_the_previous_file_is_kept_as_bak(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="[execution]\nmax_attempts = 3\n")
    console.login()
    body = _put(
        console,
        "loadcoach",
        {"execution.max_attempts": 5},
        base_mtime=_base_mtime(console, "loadcoach"),
    ).json()
    assert body["backup"] == str(config.with_name("config.toml.bak"))
    assert tomllib.loads(config.read_text())["execution"]["max_attempts"] == 5


def test_a_stale_base_mtime_is_refused_whole(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="[execution]\nmax_attempts = 3\n")
    console.login()
    response = _put(console, "loadcoach", {"execution.max_attempts": 5}, base_mtime=1)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFIG_CHANGED_ON_DISK"
    assert tomllib.loads(config.read_text())["execution"]["max_attempts"] == 3


def test_the_applications_own_refusal_is_surfaced_verbatim_and_nothing_lands(
    tmp_path: Path,
) -> None:
    # A key the fake application's validator refuses by name, in its own words. Prepared before
    # the console reads anything, since the document is cached for 60 s (api.md §2).
    document = json.loads(
        (
            Path(__file__).resolve().parents[1] / "fixtures" / "schemas" / "loadcoach.json"
        ).read_text()
    )
    document["json_schema"]["$defs"]["ExecutionSettings"]["properties"]["refuse_me"] = {
        "type": "boolean",
        "default": False,
    }
    document["config_only"].append("execution.refuse_me")
    console, config = _console(
        tmp_path, config_toml="[execution]\nmax_attempts = 3\n", document=document
    )
    console.login()
    response = _put(
        console,
        "loadcoach",
        {"execution.refuse_me": True},
        base_mtime=_base_mtime(console, "loadcoach"),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CONFIG_VALIDATION_FAILED"
    assert "refuse_me is not a configuration key" in response.json()["error"]["message"]
    assert config.read_text() == "[execution]\nmax_attempts = 3\n"
    assert not config.with_name("config.toml.bak").exists()
    # And it left the one row a successful write leaves (spec §11 contract 2; WP6 finding 2).
    rows = console.client.get("/api/v1/audit?action=settings.write", headers=JSON_HEADERS).json()
    newest = rows["items"][0] if isinstance(rows, dict) else rows[0]
    assert newest["outcome"] == "refused"
    assert newest["target"] == "execution.refuse_me"
    assert "refuse_me is not a configuration key" in newest["message"]


def test_an_unknown_key_is_refused_by_name_and_the_rest_still_lands(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="[execution]\nmax_attempts = 3\n")
    console.login()
    body = _put(
        console,
        "loadcoach",
        {"execution.max_attempts": 4, "nowhere.at_all": 1},
        base_mtime=_base_mtime(console, "loadcoach"),
    ).json()
    assert body["outcomes"]["nowhere.at_all"]["code"] == "SETTING_UNKNOWN"
    assert body["outcomes"]["execution.max_attempts"]["outcome"] == "written"
    assert tomllib.loads(config.read_text())["execution"]["max_attempts"] == 4


def test_a_value_that_did_not_change_is_reported_unchanged_and_not_written(
    tmp_path: Path,
) -> None:
    console, config = _console(tmp_path, config_toml="[execution]\nmax_attempts = 3\n")
    console.login()
    before = config.stat().st_mtime_ns
    body = _put(
        console,
        "loadcoach",
        {"execution.max_attempts": 3},
        base_mtime=_base_mtime(console, "loadcoach"),
    ).json()
    assert body["outcomes"]["execution.max_attempts"]["outcome"] == "unchanged"
    assert config.stat().st_mtime_ns == before


# --- Security keys and re-authentication ------------------------------------------------------


def test_a_security_key_without_a_fresh_reauth_is_refused(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml='[server]\nhost = "127.0.0.1"\n')
    console.login()
    response = _put(
        console,
        "loadcoach",
        {"server.host": "0.0.0.0"},  # noqa: S104 — the value under test, never a bind here
        base_mtime=_base_mtime(console, "loadcoach"),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REAUTH_REQUIRED"
    assert 'host = "127.0.0.1"' in config.read_text()


def test_a_security_key_lands_inside_the_window_and_the_audit_row_says_security_key(
    tmp_path: Path,
) -> None:
    console, config = _console(tmp_path, config_toml='[server]\nhost = "127.0.0.1"\n')
    console.login()
    console.client.post("/api/v1/reauth", json={"password": PASSWORD}, headers=JSON_HEADERS)
    body = _put(
        console,
        "loadcoach",
        {"server.host": "10.77.10.84"},
        base_mtime=_base_mtime(console, "loadcoach"),
    ).json()
    assert body["outcomes"]["server.host"]["outcome"] == "written"
    row = console.client.get(f"/api/v1/audit/{body['audit_id']}", headers=JSON_HEADERS).json()
    assert row["action"] == "settings.write"
    assert row["security"] is True
    assert 'host = "10.77.10.84"' in config.read_text()


def test_the_window_expires(tmp_path: Path) -> None:
    console, _config = _console(tmp_path, config_toml='[server]\nhost = "127.0.0.1"\n')
    console.login()
    console.client.post("/api/v1/reauth", json={"password": PASSWORD}, headers=JSON_HEADERS)
    console.advance(minutes=6)
    response = _put(
        console,
        "loadcoach",
        {"server.host": "10.77.10.84"},
        base_mtime=_base_mtime(console, "loadcoach"),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REAUTH_REQUIRED"


# --- Runtime keys ----------------------------------------------------------------------------


def test_a_runtime_key_on_a_stopped_application_is_refused_and_offers_the_file(
    tmp_path: Path,
) -> None:
    console, config = _console(tmp_path, running=False)
    console.login()
    body = _put(
        console, "loadcoach", {"queue.paused": True}, base_mtime=_base_mtime(console, "loadcoach")
    ).json()
    outcome = body["outcomes"]["queue.paused"]
    assert outcome["outcome"] == "refused"
    assert outcome["code"] == "APP_STOPPED"
    assert str(config) in outcome["message"]


def test_a_runtime_key_can_be_forced_to_the_file(tmp_path: Path) -> None:
    console, config = _console(tmp_path, running=False)
    console.login()
    body = _put(
        console,
        "loadcoach",
        {"queue.paused": True},
        base_mtime=_base_mtime(console, "loadcoach"),
        to_file=["queue.paused"],
    ).json()
    assert body["outcomes"]["queue.paused"]["outcome"] == "written"
    assert tomllib.loads(config.read_text())["queue"]["paused"] is True


def test_a_runtime_key_on_a_running_application_goes_to_its_api_not_the_file(
    tmp_path: Path, respx_mock: Any
) -> None:
    import httpx

    console, config = _console(tmp_path, running=True)
    console.login()
    respx_mock.get("http://127.0.0.1:8766/api/v1/version").mock(
        return_value=httpx.Response(200, json={"application": "loadcoach", "version": "1.3.1"})
    )
    respx_mock.get("http://127.0.0.1:8766/api/v1/settings").mock(
        return_value=httpx.Response(200, json={"settings": {"queue.paused": False}})
    )
    route = respx_mock.put("http://127.0.0.1:8766/api/v1/settings").mock(
        return_value=httpx.Response(200, json={"settings": {"queue.paused": True}})
    )
    body = _put(
        console, "loadcoach", {"queue.paused": True}, base_mtime=_base_mtime(console, "loadcoach")
    ).json()
    assert body["outcomes"]["queue.paused"]["outcome"] == "applied"
    assert route.called
    assert json.loads(route.calls.last.request.content) == {"queue.paused": True}
    assert config.read_text() == ""  # the file is never touched for a runtime key (rule 4)


def test_the_applications_refusal_of_a_runtime_key_is_carried_through(
    tmp_path: Path, respx_mock: Any
) -> None:
    import httpx

    console, _config = _console(tmp_path, running=True)
    console.login()
    respx_mock.get("http://127.0.0.1:8766/api/v1/version").mock(
        return_value=httpx.Response(200, json={"application": "loadcoach", "version": "1.3.1"})
    )
    respx_mock.get("http://127.0.0.1:8766/api/v1/settings").mock(
        return_value=httpx.Response(200, json={"settings": {}})
    )
    respx_mock.put("http://127.0.0.1:8766/api/v1/settings").mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": "VALIDATION_ERROR", "message": "queue.paused must be a bool"}},
        )
    )
    body = _put(
        console, "loadcoach", {"queue.paused": True}, base_mtime=_base_mtime(console, "loadcoach")
    ).json()
    assert body["outcomes"]["queue.paused"]["outcome"] == "refused"
    assert "queue.paused must be a bool" in body["outcomes"]["queue.paused"]["message"]


# --- Every application's EXAMPLE_CONFIG_TOML, one key at a time -------------------------------


@pytest.mark.parametrize(
    ("app", "key", "value"),
    [
        ("freeweight", "benchmarks.long_context_max_tokens", 16000),
        ("loadcoach", "execution.max_attempts", 7),
        ("ideapress", "execution.max_concurrent_stages", 2),
        ("promptcadence", "execution.max_steps", 11),
    ],
)
def test_each_applications_example_config_round_trips_one_key_byte_identically(
    tmp_path: Path, app: str, key: str, value: Any
) -> None:
    """Development plan Phase 4: comments, order and every untouched line survive."""
    from weightroom.services.config_files import apply_changes

    original = (EXAMPLES / f"{app}.toml").read_text(encoding="utf-8")
    written = apply_changes(original, {key: value})
    section, leaf = key.split(".")
    assert tomllib.loads(written)[section][leaf] == value
    before = [line for line in original.splitlines() if not line.strip().startswith(f"{leaf} ")]
    after = [line for line in written.splitlines() if not line.strip().startswith(f"{leaf} ")]
    assert before == after


@pytest.mark.parametrize("app", ["freeweight", "loadcoach", "ideapress", "promptcadence"])
def test_a_key_the_example_config_never_mentions_is_appended_without_disturbing_it(
    tmp_path: Path, app: str
) -> None:
    from weightroom.services.config_files import apply_changes

    original = (EXAMPLES / f"{app}.toml").read_text(encoding="utf-8")
    written = apply_changes(original, {"logging.level": "DEBUG"})
    assert tomllib.loads(written)["logging"]["level"] == "DEBUG"
    assert written.startswith(original.split("\n[logging]")[0])


# --- The pages --------------------------------------------------------------------------------


def test_the_settings_page_renders_every_section_and_the_raw_editor(tmp_path: Path) -> None:
    console, _config = _console(tmp_path)
    console.login()
    page = console.client.get("/apps/loadcoach/settings", headers={"Accept": "text/html"}).text
    assert 'name="field:server.port"' in page
    assert 'name="field:queue.paused"' in page
    assert "config schema --json" in page
    assert 'name="text"' not in page  # the raw editor is its own page (secrets)
    editor = console.client.get(
        "/apps/loadcoach/settings/raw", headers={"Accept": "text/html"}
    ).text
    assert 'name="text"' in editor


class _BrowserForm(HTMLParser):
    """What a browser would post back from a rendered page, left exactly as it was served.

    The console's own tests had always built the post by hand, so WP6's finding 1 — a select with
    no *unset* option posting ``false`` for a key nobody touched — could not be seen from a test
    (row WPF1). This reads the markup instead: a text input posts its ``value``, and a select
    posts its ``selected`` option, or its first when none is marked, exactly as a browser does.
    """

    def __init__(self) -> None:
        super().__init__()
        self.data: dict[str, str] = {}
        self._select = ""
        self._selected: str | None = None
        self._first: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        one = dict(attrs)
        name = one.get("name") or ""
        if tag == "input" and name and one.get("type") not in {"submit", "button"}:
            self.data[name] = one.get("value") or ""
        elif tag == "select" and name:
            self._select, self._selected, self._first = name, None, None
        elif tag == "option" and self._select:
            value = one.get("value") or ""
            self._first = value if self._first is None else self._first
            if "selected" in one:
                self._selected = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self._select:
            chosen = self._selected if self._selected is not None else self._first
            self.data[self._select] = chosen or ""
            self._select = ""


def _as_a_browser_would_post(page: str) -> dict[str, str]:
    """The settings form's own controls out of ``page`` — the other forms' fields left behind."""
    parser = _BrowserForm()
    parser.feed(page)
    return {
        name: value
        for name, value in parser.data.items()
        if name.startswith("field:") or name in {"base_mtime", "to_file"}
    }


def test_the_page_posted_back_untouched_writes_nothing(tmp_path: Path) -> None:
    """WP6 findings 1: on FreeWeight's own default provider, no save through the form could land.

    Its `runtime.flash_attention` (a nullable boolean) and `runtime.kv_cache_precision` (a
    nullable enum) had no *unset* option, so an untouched save posted `false` and `f16`, wrote
    two keys the operator never touched, and FreeWeight refused the whole file.
    """
    console, config = _console(
        tmp_path, app="freeweight", config_toml="[runtime]\ncontext_size = 8192\n"
    )
    console.login()
    before = config.read_text()
    page = console.client.get("/apps/freeweight/settings", headers={"Accept": "text/html"}).text
    posted = _as_a_browser_would_post(page)
    assert posted["field:runtime.flash_attention"] == ""
    assert posted["field:runtime.kv_cache_precision"] == ""
    response = console.post_form("/apps/freeweight/settings", posted)
    assert response.status_code == 200
    assert "Nothing changed." in response.text
    assert config.read_text() == before
    assert not config.with_name("config.toml.bak").exists()


def test_the_page_saves_one_changed_key_beside_the_unset_ones(tmp_path: Path) -> None:
    """The other half of WP6 finding 1: the save the operator actually meant still lands."""
    console, config = _console(
        tmp_path, app="freeweight", config_toml="[runtime]\ncontext_size = 8192\n"
    )
    console.login()
    page = console.client.get("/apps/freeweight/settings", headers={"Accept": "text/html"}).text
    posted = _as_a_browser_would_post(page)
    posted["field:adapters.directory"] = str(tmp_path / "adapters")
    response = console.post_form("/apps/freeweight/settings", posted)
    assert response.status_code == 200
    assert "1 written to the file" in response.text
    written = tomllib.loads(config.read_text())
    assert written["adapters"]["directory"] == str(tmp_path / "adapters")
    assert "flash_attention" not in written["runtime"]
    assert "kv_cache_precision" not in written["runtime"]


def test_a_nullable_key_set_through_the_form_is_written_and_can_be_seen_again(
    tmp_path: Path,
) -> None:
    """*unset* is a rendering, not a ceiling: the key still saves when the operator picks one."""
    console, config = _console(
        tmp_path, app="freeweight", config_toml="[runtime]\ncontext_size = 8192\n"
    )
    console.login()
    page = console.client.get("/apps/freeweight/settings", headers={"Accept": "text/html"}).text
    posted = _as_a_browser_would_post(page)
    posted["field:runtime.kv_cache_precision"] = "q8_0"
    assert console.post_form("/apps/freeweight/settings", posted).status_code == 200
    assert tomllib.loads(config.read_text())["runtime"]["kv_cache_precision"] == "q8_0"
    again = console.client.get("/apps/freeweight/settings", headers={"Accept": "text/html"}).text
    posted = _as_a_browser_would_post(again)
    assert posted["field:runtime.kv_cache_precision"] == "q8_0"
    # Back to *unset* is a deletion the raw editor owns: that key alone is refused, and the other
    # change in the same save still lands (row WPF1).
    posted["field:runtime.kv_cache_precision"] = ""
    posted["field:runtime.context_size"] = "4096"
    response = console.post_form("/apps/freeweight/settings", posted)
    assert "deletion" in response.text
    written = tomllib.loads(config.read_text())["runtime"]
    assert (written["kv_cache_precision"], written["context_size"]) == ("q8_0", 4096)


def test_a_secret_is_never_rendered_on_the_page(tmp_path: Path) -> None:
    console, _config = _console(
        tmp_path, app="freeweight", config_toml='[auth]\ntokens = ["hunter2"]\n'
    )
    console.login()
    page = console.client.get("/apps/freeweight/settings", headers={"Accept": "text/html"}).text
    assert "hunter2" not in page
    assert "********" in page
    # The raw editor is the file, secrets included — which is why it is its own page.
    editor = console.client.get(
        "/apps/freeweight/settings/raw", headers={"Accept": "text/html"}
    ).text
    assert "hunter2" in editor


def test_the_page_saves_a_key_and_says_what_it_did(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="[execution]\nmax_attempts = 3\n")
    console.login()
    base = _base_mtime(console, "loadcoach")
    response = console.post_form(
        "/apps/loadcoach/settings",
        {"field:execution.max_attempts": "9", "base_mtime": str(base)},
    )
    assert response.status_code == 200
    assert "1 written to the file" in response.text
    assert tomllib.loads(config.read_text())["execution"]["max_attempts"] == 9


def test_the_page_takes_the_password_and_writes_a_security_key_in_one_post(
    tmp_path: Path,
) -> None:
    """Plan Phase 4 criterion 2, without the restart half (a fake host has no process)."""
    console, config = _console(tmp_path, config_toml='[server]\nhost = "127.0.0.1"\n')
    console.login()
    base = _base_mtime(console, "loadcoach")
    response = console.post_form(
        "/apps/loadcoach/settings",
        {
            "field:server.host": "10.77.10.84",
            "base_mtime": str(base),
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    assert 'host = "10.77.10.84"' in config.read_text()


def test_a_wrong_password_writes_nothing(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml='[server]\nhost = "127.0.0.1"\n')
    console.login()
    base = _base_mtime(console, "loadcoach")
    response = console.post_form(
        "/apps/loadcoach/settings",
        {"field:server.host": "10.77.10.84", "base_mtime": str(base), "password": "wrong"},
    )
    assert "not the operator" in response.text  # Jinja escapes the apostrophe
    assert 'host = "127.0.0.1"' in config.read_text()


def test_the_raw_editor_saves_a_browsers_crlf_back_as_the_file_it_was_given(
    tmp_path: Path,
) -> None:
    """A browser posts a ``textarea``'s value with CRLF endings whatever it was given, so saving a
    file back unedited rewrote every line of it (found live at row WPF1)."""
    original = "# mine\n[execution]\nmax_attempts = 3\n"
    console, config = _console(tmp_path, config_toml=original)
    console.login()
    body = console.client.get("/api/v1/apps/loadcoach/config", headers=JSON_HEADERS).json()
    response = console.post_form(
        "/apps/loadcoach/settings/raw",
        {
            "text": body["text"].replace("\n", "\r\n"),
            "base_mtime": str(body["base_mtime"] or ""),
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    assert config.read_text() == original


def test_the_raw_editor_refuses_broken_toml_before_launching_anything(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="[server]\nport = 8766\n")
    console.login()
    base = _base_mtime(console, "loadcoach")
    response = console.post_form(
        "/apps/loadcoach/settings/raw",
        {"text": "[server\n", "base_mtime": str(base), "password": PASSWORD},
    )
    assert "Not valid TOML" in response.text
    assert config.read_text() == "[server]\nport = 8766\n"


def test_the_raw_editor_writes_the_whole_file_under_the_same_rules(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="[server]\nport = 8766\n")
    console.login()
    base = _base_mtime(console, "loadcoach")
    response = console.post_form(
        "/apps/loadcoach/settings/raw",
        {
            "text": "# rewritten\n[server]\nport = 8767\n",
            "base_mtime": str(base),
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    assert config.read_text() == "# rewritten\n[server]\nport = 8767\n"


def test_the_raw_editor_is_refused_by_the_applications_own_validation(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="[server]\nport = 8766\n")
    console.login()
    base = _base_mtime(console, "loadcoach")
    response = console.post_form(
        "/apps/loadcoach/settings/raw",
        {"text": f"{REFUSAL_MARKER}\n", "base_mtime": str(base), "password": PASSWORD},
    )
    assert "refuse_me is not a configuration key" in response.text
    assert config.read_text() == "[server]\nport = 8766\n"


def test_validate_answers_the_applications_verdict_and_writes_nothing(tmp_path: Path) -> None:
    console, config = _console(tmp_path, config_toml="[server]\nport = 8766\n")
    console.login()
    good = console.client.post(
        "/api/v1/apps/loadcoach/settings/validate",
        json={"text": "[server]\nport = 1\n"},
        headers=JSON_HEADERS,
    ).json()
    assert good["valid"] is True
    bad = console.client.post(
        "/api/v1/apps/loadcoach/settings/validate",
        json={"text": f"{REFUSAL_MARKER}\n"},
        headers=JSON_HEADERS,
    ).json()
    assert bad["valid"] is False
    assert "refuse_me" in bad["message"]
    assert config.read_text() == "[server]\nport = 8766\n"


# --- WeightRoomGym's own page -----------------------------------------------------------------


def test_the_console_generates_its_own_settings_page_from_its_own_verb(tmp_path: Path) -> None:
    console = build_console(tmp_path)
    console.login()
    page = console.client.get("/settings", headers={"Accept": "text/html"}).text
    assert "wr-gym config schema --json" in page
    assert 'name="field:telemetry.interval_ms"' in page
    assert 'name="field:server.host"' in page


def test_the_consoles_own_runtime_key_is_applied_live(tmp_path: Path) -> None:
    console = build_console(tmp_path)
    console.login()
    response = console.post_form(
        "/settings", {"field:telemetry.interval_ms": "2500", "base_mtime": ""}
    )
    assert response.status_code == 200
    body = console.client.get("/api/v1/settings", headers=JSON_HEADERS).json()
    assert body["settings"]["telemetry.interval_ms"] == 2500


def test_the_consoles_own_security_key_needs_the_password_too(tmp_path: Path) -> None:
    console = build_console(tmp_path)
    console.login()
    response = console.client.put(
        "/api/v1/apps/weightroom/settings",
        json={"changes": {"server.port": 8790}},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REAUTH_REQUIRED"


# --- Row W10: what the application says about a stored row (WI1 §5 items 4a–4c) ------------------


def test_a_stored_row_shows_when_it_applies_and_the_page_can_clear_it(
    tmp_path: Path, respx_mock: Any
) -> None:
    """IdeaPress's document states ``applies`` and ``stored`` per key: the page shows the word
    rather than *live*, offers *clear* for a stored row, and clearing sends ``null`` through the
    application's own ``PUT /settings`` — the one audited path (ADR-0124)."""
    import httpx

    console, config = _console(tmp_path, app="ideapress", running=True)
    console.login()
    respx_mock.get("http://127.0.0.1:8767/api/v1/version").mock(
        return_value=httpx.Response(200, json={"application": "ideapress", "version": "1.5.0"})
    )
    respx_mock.get("http://127.0.0.1:8767/api/v1/settings").mock(
        return_value=httpx.Response(
            200,
            json={
                "settings": {
                    "workflow.max_revision_rounds": 2,
                    "workflow.max_attempts_per_stage": 3,
                },
                "definitions": {
                    "workflow.max_revision_rounds": {"stored": 2, "applies": "next_stage"},
                    "workflow.max_attempts_per_stage": {"stored": None, "applies": "next_stage"},
                },
            },
        )
    )
    route = respx_mock.put("http://127.0.0.1:8767/api/v1/settings").mock(
        return_value=httpx.Response(200, json={"settings": {"workflow.max_revision_rounds": 3}})
    )
    page = console.client.get("/apps/ideapress/settings", headers={"Accept": "text/html"}).text
    assert "next stage" in page and 'value="workflow.max_revision_rounds"' in page
    assert page.count('name="clear"') == 1  # only the key with a stored row offers it

    response = console.post_form(
        "/apps/ideapress/settings",
        {
            "field:workflow.max_revision_rounds": "2",
            "field:workflow.max_attempts_per_stage": "3",
            "clear": "workflow.max_revision_rounds",
            "base_mtime": str(_base_mtime(console, "ideapress") or ""),
        },
    )
    assert response.status_code == 200
    assert "workflow.max_revision_rounds cleared" in response.text
    assert json.loads(route.calls.last.request.content) == {"workflow.max_revision_rounds": None}
    assert config.read_text() == ""
    rows = console.client.get("/api/v1/audit?action=settings.write", headers=JSON_HEADERS).json()
    newest = rows["items"][0] if isinstance(rows, dict) else rows[0]
    assert newest["params"]["cleared"] == "workflow.max_revision_rounds"
    assert newest["params"]["touched_security"] is False


def test_a_security_key_posted_unchanged_is_not_a_touched_security_key(tmp_path: Path) -> None:
    """The page posts every field; a security key left as it was neither needs the password nor
    marks the audit row ``touched_security`` (WI1 §5 item 4c)."""
    console, config = _console(
        tmp_path, config_toml='[server]\nhost = "127.0.0.1"\n[execution]\nmax_attempts = 3\n'
    )
    console.login()
    response = console.post_form(
        "/apps/loadcoach/settings",
        {
            "field:server.host": "127.0.0.1",
            "field:execution.max_attempts": "9",
            "base_mtime": str(_base_mtime(console, "loadcoach")),
        },
    )
    assert response.status_code == 200
    assert "1 written to the file" in response.text
    assert tomllib.loads(config.read_text())["execution"]["max_attempts"] == 9
    rows = console.client.get("/api/v1/audit?action=settings.write", headers=JSON_HEADERS).json()
    newest = rows["items"][0] if isinstance(rows, dict) else rows[0]
    assert newest["params"]["touched_security"] is False
    assert newest["security"] is False


# --- Row WX13: FreeWeight's provider profiles (ADR-0144) ---------------------------------------


_PROFILE_TOML = """\
[provider]
active = "default"
kind = "ollama"

[providers.served]
kind = "llamacpp"
"""


def _profile_document() -> dict[str, Any]:
    """FreeWeight's own document as it reads with a second profile configured."""
    document: dict[str, Any] = json.loads((SCHEMAS / "freeweight.json").read_text(encoding="utf-8"))
    document["provider_profiles"] = {
        "key": "provider.active",
        "active": "default",
        "kinds": ["fake", "llamacpp", "ollama"],
        "profiles": [
            {"name": "default", "prefix": "provider", "kind": "ollama"},
            {"name": "served", "prefix": "providers.served", "kind": "llamacpp"},
        ],
    }
    document["security_keys"] = sorted({*document["security_keys"], "providers.served.base_url"})
    return document


def test_every_profile_is_a_card_and_every_key_of_it_is_editable(tmp_path: Path) -> None:
    """The file names one key of `served`; the schema describes the rest, so the card carries
    them all (ADR-0144 rule 7, ADR-0127 rule 3)."""
    console, _config = _console(
        tmp_path, app="freeweight", config_toml=_PROFILE_TOML, document=_profile_document()
    )
    console.login()
    page = console.client.get("/apps/freeweight/settings", headers={"Accept": "text/html"}).text

    assert 'name="field:provider.active" value="default"' in page
    assert 'name="field:provider.active" value="served"' in page
    assert 'value="served"\n               checked' in page.replace("\r", "") or (
        'value="default"' in page and "checked" in page
    )
    for leaf in ("kind", "base_url", "timeout_seconds", "model_directory", "server_path"):
        assert f"field:providers.served.{leaf}" in page
    # The selector is the radio, not a second text input beside it.
    assert 'name="field:provider.active"\n           type="text"' not in page
    # A profile does not choose itself.
    assert "providers.served.active" not in page


def test_an_application_that_states_no_profiles_renders_no_cards(tmp_path: Path) -> None:
    console, _config = _console(tmp_path, config_toml="[execution]\nmax_attempts = 3\n")
    console.login()
    page = console.client.get("/apps/loadcoach/settings", headers={"Accept": "text/html"}).text

    assert "Provider profiles" not in page
    assert "Add a provider profile" not in page


def test_switching_the_active_profile_is_a_security_key_write(tmp_path: Path) -> None:
    console, config = _console(
        tmp_path, app="freeweight", config_toml=_PROFILE_TOML, document=_profile_document()
    )
    console.login()
    base = _base_mtime(console, "freeweight")

    refused = console.post_form(
        "/apps/freeweight/settings",
        {"field:provider.active": "served", "base_mtime": str(base)},
    )
    assert refused.status_code == 200
    assert tomllib.loads(config.read_text())["provider"]["active"] == "default"

    response = console.post_form(
        "/apps/freeweight/settings",
        {"field:provider.active": "served", "base_mtime": str(base), "password": PASSWORD},
    )
    assert response.status_code == 200
    assert tomllib.loads(config.read_text())["provider"]["active"] == "served"


def test_adding_a_profile_writes_one_key_and_switches_nothing(tmp_path: Path) -> None:
    console, config = _console(
        tmp_path, app="freeweight", config_toml=_PROFILE_TOML, document=_profile_document()
    )
    console.login()
    response = console.post_form(
        "/apps/freeweight/settings/provider-profile",
        {
            "profile_name": "remote",
            "profile_kind": "ollama",
            "base_mtime": str(_base_mtime(console, "freeweight")),
        },
    )

    assert response.status_code == 200
    written = tomllib.loads(config.read_text())
    assert written["providers"]["remote"] == {"kind": "ollama"}
    assert written["provider"]["active"] == "default"
    rows = console.client.get("/api/v1/audit?action=settings.write", headers=JSON_HEADERS).json()
    newest = rows["items"][0] if isinstance(rows, dict) else rows[0]
    assert newest["params"]["written"] == ["providers.remote.kind"]
    assert newest["params"]["touched_security"] is False


@pytest.mark.parametrize(
    ("name", "kind", "reason"),
    [
        ("served", "ollama", "already a profile"),
        ("Not A Name", "ollama", "is not a profile name"),
        ("remote", "vllm", "is not a provider kind"),
    ],
)
def test_a_profile_this_application_would_not_accept_is_refused_by_name(
    tmp_path: Path, name: str, kind: str, reason: str
) -> None:
    console, config = _console(
        tmp_path, app="freeweight", config_toml=_PROFILE_TOML, document=_profile_document()
    )
    console.login()
    response = console.post_form(
        "/apps/freeweight/settings/provider-profile",
        {
            "profile_name": name,
            "profile_kind": kind,
            "base_mtime": str(_base_mtime(console, "freeweight")),
        },
    )

    assert response.status_code == 200
    assert reason in response.text
    assert config.read_text() == _PROFILE_TOML

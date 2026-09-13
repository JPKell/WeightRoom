"""The prompt editor (spec §7.10, api.md §4, prompt standards §6): packs, overrides, validation,
the diff, deletion — over applications that answer ``prompts list|show`` from fixture files.

The conftest points ``XDG_CONFIG_HOME`` at the test's own tree, so every override written here lands
there and nowhere an installed application would read it.
"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select

from tests.support import HELLO_RECORD, JSON_HEADERS, Console, build_console, prompt_application
from weightroom.config import Settings, load_settings
from weightroom.infrastructure.db.models import AuditLog
from weightroom.services.apps import AppNotInstalled, AppUnknown
from weightroom.services.prompts import (
    PromptOverrideInvalid,
    PromptsCommandFailed,
    PromptsUnavailable,
    delete_override,
    list_pack,
    override_directory,
    override_path,
    prompt_detail,
    write_override,
)

if TYPE_CHECKING:
    from pathlib import Path

HTML = {"Accept": "text/html"}


def _settings(tmp_path: Path, app: str, executable: Path | str) -> Settings:
    file = tmp_path / f"{app}.toml"
    file.write_text(f'[apps.{app}]\nexecutable = "{executable}"\n', encoding="utf-8")
    return load_settings(config_path=file).settings


def _ideapress(tmp_path: Path) -> Settings:
    return _settings(
        tmp_path, "ideapress", prompt_application(tmp_path, "ideapress", [HELLO_RECORD])
    )


def _override(**changes: Any) -> dict[str, Any]:  # noqa: ANN401 — record fields
    body = copy.deepcopy(HELLO_RECORD)
    body["version"] = "1.1.0"
    body["template"] = "Welcome the reader of a document titled {{ title }} in one sentence."
    body["metadata"]["change_reason"] = "The operator's own greeting."
    body.update(changes)
    return body


# --- The service ----------------------------------------------------------------------------------


def test_an_override_lives_in_the_applications_own_directory_under_its_own_id(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "config" / "ideapress" / "prompts"
    assert override_directory("ideapress") == directory
    assert override_path("ideapress", "stages.hello") == directory / "stages.hello.json"
    for refused in ("../escape", "stages/hello", "Stages.Hello", "", ".hidden", "-x"):
        with pytest.raises(PromptOverrideInvalid):
            override_path("ideapress", refused)


def test_an_override_is_written_listed_diffed_and_deleted(tmp_path: Path) -> None:
    settings = _ideapress(tmp_path)
    pack = list_pack(settings, "ideapress")
    assert [(one.prompt_id, one.version, one.overridden) for one in pack.entries] == [
        ("stages.hello", "1.0.0", False)
    ]
    assert "restart IdeaPress" in pack.rule

    detail = write_override(settings, "ideapress", "stages.hello", _override())

    path = override_path("ideapress", "stages.hello")
    assert detail.override_path == path
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == "1.1.0"
    assert detail.override_problem is None
    assert detail.shipped_sha256 != detail.override_sha256
    assert '-  "version": "1.0.0"' in detail.diff
    assert '+  "version": "1.1.0"' in detail.diff
    assert list(path.parent.iterdir()) == [path]  # the validated candidate is not left behind
    entry = list_pack(settings, "ideapress").entries[0]
    assert (entry.overridden, entry.override_version) == (True, "1.1.0")

    assert delete_override("ideapress", "stages.hello") == path
    assert not path.exists()
    assert prompt_detail(settings, "ideapress", "stages.hello").override is None
    with pytest.raises(PromptsUnavailable):
        delete_override("ideapress", "stages.hello")


@pytest.mark.parametrize(
    ("record", "fragment"),
    [
        (_override(prompt_id="stages.other"), "must declare the same prompt_id"),
        (_override(template="Welcome {{ reader }}."), "undeclared"),
        ({**_override(), "metadata": {"owner": "ideapress"}}, "change_reason"),
        ({**_override(), "schema_version": "9.9"}, "record schema"),
    ],
)
def test_an_override_the_application_would_not_load_is_refused_and_nothing_is_written(
    tmp_path: Path, record: dict[str, Any], fragment: str
) -> None:
    settings = _ideapress(tmp_path)
    with pytest.raises(PromptOverrideInvalid) as raised:
        write_override(settings, "ideapress", "stages.hello", record)
    assert fragment in raised.value.message
    directory = override_directory("ideapress")
    assert not directory.exists() or list(directory.iterdir()) == []


def test_a_prompt_the_pack_does_not_ship_cannot_be_overridden(tmp_path: Path) -> None:
    settings = _ideapress(tmp_path)
    with pytest.raises(PromptsUnavailable, match="has no prompt stages.unknown"):
        write_override(
            settings, "ideapress", "stages.unknown", _override(prompt_id="stages.unknown")
        )
    with pytest.raises(PromptsUnavailable):
        prompt_detail(settings, "ideapress", "stages.unknown")


def test_an_override_on_disk_that_would_not_load_is_shown_as_such(tmp_path: Path) -> None:
    settings = _ideapress(tmp_path)
    path = override_path("ideapress", "stages.hello")
    path.parent.mkdir(parents=True)
    path.write_text('{"prompt_id": "stages.hello", "version": "2.0.0"}', encoding="utf-8")
    entry = list_pack(settings, "ideapress").entries[0]
    assert entry.overridden
    assert entry.override_problem is not None
    detail = prompt_detail(settings, "ideapress", "stages.hello")
    assert detail.override_problem is not None
    assert detail.has_override_file


def test_freeweight_needs_its_whole_record_and_carries_its_benchmark_rule(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path, "freeweight", prompt_application(tmp_path, "freeweight", [HELLO_RECORD])
    )
    assert "--allow-prompt-override" in list_pack(settings, "freeweight").rule
    assert prompt_detail(settings, "freeweight", "stages.hello").shipped == HELLO_RECORD
    before_w9 = prompt_application(
        tmp_path / "old", "freeweight", [HELLO_RECORD], whole_record=False
    )
    old = _settings(tmp_path / "old", "freeweight", before_w9)
    with pytest.raises(PromptsCommandFailed, match="no whole record"):
        prompt_detail(old, "freeweight", "stages.hello")


def test_applications_with_no_pack_here_are_named_and_an_uninstalled_one_says_so(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, "ideapress", tmp_path / "absent")
    for app in ("loadcoach", "promptcadence"):
        with pytest.raises(PromptsUnavailable, match="no prompts command"):
            list_pack(settings, app)
    with pytest.raises(AppUnknown):
        list_pack(settings, "hermes")
    with pytest.raises(AppNotInstalled):
        list_pack(settings, "ideapress")


# --- The routes and pages -------------------------------------------------------------------------


def _console(tmp_path: Path) -> Console:
    ideapress = prompt_application(tmp_path, "ideapress", [HELLO_RECORD])
    freeweight = prompt_application(tmp_path, "freeweight", [HELLO_RECORD])
    console = build_console(
        tmp_path / "console",
        extra_toml=(
            f'[apps.ideapress]\nexecutable = "{ideapress}"\n'
            f'[apps.freeweight]\nexecutable = "{freeweight}"\n'
        ),
    )
    console.login()
    return console


def _outcomes(console: Console, action: str) -> list[str]:
    with console.database.read() as session:
        rows = session.execute(select(AuditLog).where(AuditLog.action == action)).scalars()
        return [row.outcome for row in rows]


def test_the_api_lists_shows_writes_and_deletes_an_override_each_audited(tmp_path: Path) -> None:
    console = _console(tmp_path)
    base = "/api/v1/apps/ideapress/prompts"
    pack = console.client.get(base).json()
    assert [(one["prompt_id"], one["overridden"]) for one in pack["prompts"]] == [
        ("stages.hello", False)
    ]

    written = console.client.put(
        f"{base}/stages.hello", json={"record": _override()}, headers=JSON_HEADERS
    )

    assert written.status_code == 200, written.text
    assert written.json()["marked"] == "user_override"
    assert written.json()["written"].endswith("ideapress/prompts/stages.hello.json")
    shown = console.client.get(f"{base}/stages.hello").json()
    assert shown["override"]["version"] == "1.1.0"
    assert '+  "version": "1.1.0"' in shown["diff"]
    refused = console.client.put(
        f"{base}/stages.hello",
        json={"record": _override(template="{{ nope }}")},
        headers=JSON_HEADERS,
    )
    assert refused.status_code == 400
    assert (
        console.client.delete(f"{base}/stages.hello/override", headers=JSON_HEADERS)
        .json()["deleted"]
        .endswith("stages.hello.json")
    )
    again = console.client.delete(f"{base}/stages.hello/override", headers=JSON_HEADERS)
    assert again.status_code == 404
    assert _outcomes(console, "prompt.override") == ["ok", "refused"]
    assert _outcomes(console, "prompt.delete") == ["ok", "refused"]
    assert console.client.get("/api/v1/apps/loadcoach/prompts").status_code == 404


def test_the_pages_show_the_rule_write_diff_and_delete(tmp_path: Path) -> None:
    console = _console(tmp_path)
    listed = console.client.get("/apps/freeweight/prompts", headers=HTML).text
    assert "stages.hello" in listed
    assert "--allow-prompt-override" in listed
    editor = console.client.get("/apps/ideapress/prompts/stages.hello", headers=HTML)
    assert editor.status_code == 200
    assert "restart IdeaPress" in editor.text
    assert "No override" in editor.text

    saved = console.post_form(
        "/apps/ideapress/prompts/stages.hello", {"record": json.dumps(_override())}
    )

    assert saved.status_code == 200
    assert "Override written" in saved.text
    assert "Diff against the shipped record" in saved.text
    garbled = console.post_form("/apps/ideapress/prompts/stages.hello", {"record": "{not json"})
    assert "not a JSON object" in garbled.text
    removed = console.post_form("/apps/ideapress/prompts/stages.hello/delete", {})
    assert "Override deleted" in removed.text
    assert _outcomes(console, "prompt.override") == ["ok", "refused"]
    overview = console.client.get("/apps/ideapress", headers=HTML).text
    assert 'href="/apps/ideapress/prompts"' in overview


# --- The editor's named fields (row WX8) ----------------------------------------------------------


def test_the_editor_names_the_three_fields_anyone_edits_and_patches_them_into_the_record(
    tmp_path: Path,
) -> None:
    """The JSON box is still what is posted — the loader validates the patched record, not a
    hand-typed one — so the named inputs are a convenience over the same round trip."""
    console = _console(tmp_path)
    editor = console.client.get("/apps/ideapress/prompts/stages.hello", headers=HTML).text
    assert 'name="version" value="1.0.0"' in editor
    assert 'name="change_reason" value="First version."' in editor
    assert HELLO_RECORD["template"] in editor
    assert "title" in editor  # the declared variables, in the template's hint
    assert 'name="record"' in editor

    saved = console.post_form(
        "/apps/ideapress/prompts/stages.hello",
        {
            "record": json.dumps(HELLO_RECORD),
            "version": "1.2.0",
            "change_reason": "The operator's own greeting.",
            "template": "Welcome the reader of {{ title }} in one sentence.",
        },
    )

    assert saved.status_code == 200, saved.text
    assert "Override written" in saved.text
    written = json.loads(
        (tmp_path / "config" / "ideapress" / "prompts" / "stages.hello.json").read_text()
    )
    assert written["version"] == "1.2.0"
    assert written["metadata"]["change_reason"] == "The operator's own greeting."
    assert written["template"] == "Welcome the reader of {{ title }} in one sentence."
    # Everything the form does not name is the record's own.
    assert written["system"] == HELLO_RECORD["system"]
    assert written["metadata"]["owner"] == "ideapress"


def test_a_blank_named_field_leaves_the_records_own_value(tmp_path: Path) -> None:
    """Blank is "not given", not "clear it": the JSON box is where a key is removed."""
    console = _console(tmp_path)
    saved = console.post_form(
        "/apps/ideapress/prompts/stages.hello",
        {"record": json.dumps(_override()), "version": "", "change_reason": "", "template": ""},
    )
    assert "Override written" in saved.text
    written = json.loads(
        (tmp_path / "config" / "ideapress" / "prompts" / "stages.hello.json").read_text()
    )
    assert written["version"] == "1.1.0"
    assert written["template"] == _override()["template"]


def test_a_refused_patch_comes_back_with_what_was_typed_and_writes_nothing(tmp_path: Path) -> None:
    console = _console(tmp_path)
    refused = console.post_form(
        "/apps/ideapress/prompts/stages.hello",
        {
            "record": json.dumps(HELLO_RECORD),
            "version": "1.3.0",
            "change_reason": "A variable nobody declared.",
            "template": "Greet {{ nobody }}.",
        },
    )
    assert refused.status_code == 200
    assert "nobody" in refused.text
    assert 'name="version" value="1.3.0"' in refused.text
    assert not (tmp_path / "config" / "ideapress" / "prompts" / "stages.hello.json").exists()
    assert _outcomes(console, "prompt.override") == ["refused"]

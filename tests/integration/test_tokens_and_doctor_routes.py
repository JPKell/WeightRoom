"""The Tokens pages and the Doctor page, over a real executable rather than a mock."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.support import JSON_HEADERS, Console, build_console, fake_application
from weightroom.services.processes import FakeSystemdController


def _token_cli(tmp_path: Path, app: str, *, records: list[dict[str, Any]]) -> Path:
    """An executable whose ``token`` verb answers, so the argv and the JSON are exercised."""
    directory = tmp_path / app
    directory.mkdir(parents=True, exist_ok=True)
    listing = directory / "tokens.json"
    listing.write_text(json.dumps(records), encoding="utf-8")
    executable = directory / app
    executable.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "token" ] && [ "$2" = "list" ]; then\n'
        f"  cat {listing}\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "token" ] && [ "$2" = "create" ]; then\n'
        '  printf \'{"name": "%s", "scope": "read", "token": "lc_secret_value"}\' "$3"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "token" ] && [ "$2" = "revoke" ]; then\n'
        '  if [ "$3" = "absent" ]; then echo "no such active token: absent" >&2; exit 5; fi\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _console(tmp_path: Path, app: str, executable: Path) -> Console:
    return build_console(
        tmp_path / "console",
        extra_toml=f'[apps.{app}]\nexecutable = "{executable}"\n',
        systemd=FakeSystemdController(states={f"{app}.service": "active"}),
    )


def test_tokens_are_listed_from_the_applications_own_verb(tmp_path: Path) -> None:
    executable = _token_cli(
        tmp_path,
        "loadcoach",
        records=[
            {"name": "laptop", "scope": "read", "created_at": "2026-09-01", "revoked": False},
            # PromptCadence's shape: `scopes` as a list, and `active` rather than `revoked`.
            {"name": "old", "scopes": ["read", "write"], "active": False},
        ],
    )
    console = _console(tmp_path, "loadcoach", executable)
    console.login()
    body = console.client.get("/api/v1/apps/loadcoach/tokens", headers=JSON_HEADERS).json()
    assert body["surface"] == "cli"
    names = [one["name"] for one in body["tokens"]]
    assert names == ["laptop", "old"]
    assert body["tokens"][1]["scope"] == "read, write"  # a list of scopes, as it came
    assert body["tokens"][1]["revoked"] is True


def test_the_paginated_envelope_promptcadence_answers_with_is_read_too(tmp_path: Path) -> None:
    """PromptCadence wraps its list in `{"items": …}`; LoadCoach in `{"tokens": …}`."""
    directory = tmp_path / "promptcadence"
    directory.mkdir(parents=True)
    executable = directory / "promptcadence"
    executable.write_text(
        "#!/bin/sh\n"
        'printf \'{"items": [{"name": "weightroom", "scopes": ["admin"], "active": true}]}\'\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    console = _console(tmp_path, "promptcadence", executable)
    console.login()
    body = console.client.get("/api/v1/apps/promptcadence/tokens", headers=JSON_HEADERS).json()
    assert [one["name"] for one in body["tokens"]] == ["weightroom"]
    assert body["tokens"][0]["scope"] == "admin"
    assert body["tokens"][0]["revoked"] is False


def test_a_new_tokens_secret_is_shown_once_and_stored_nowhere(tmp_path: Path) -> None:
    executable = _token_cli(tmp_path, "loadcoach", records=[])
    console = _console(tmp_path, "loadcoach", executable)
    console.login()
    page = console.post_form("/apps/loadcoach/tokens", {"name": "phone", "scope": "read"})
    assert "lc_secret_value" in page.text
    # It is on that render and nowhere else: not the audit row, not a later page.
    rows = console.client.get("/api/v1/audit?action=token.create", headers=JSON_HEADERS).json()[
        "items"
    ]
    assert rows and rows[0]["app"] == "loadcoach"
    assert "lc_secret_value" not in json.dumps(rows)
    again = console.client.get("/apps/loadcoach/tokens", headers={"Accept": "text/html"}).text
    assert "lc_secret_value" not in again


def test_the_scope_field_is_a_select_of_the_applications_own_vocabulary(tmp_path: Path) -> None:
    """LoadCoach's single value versus PromptCadence's several, several apart (row WX2)."""
    lc_executable = _token_cli(tmp_path / "lc", "loadcoach", records=[])
    lc = _console(tmp_path / "lc", "loadcoach", lc_executable)
    lc.login()
    lc_page = lc.client.get("/apps/loadcoach/tokens", headers={"Accept": "text/html"}).text
    assert '<select id="token-scope" name="scope">' in lc_page  # not `multiple`
    assert '<option value="read" selected>read</option>' in lc_page
    assert '<option value="admin">admin</option>' in lc_page

    pc_executable = _token_cli(tmp_path / "pc", "promptcadence", records=[])
    pc = _console(tmp_path / "pc", "promptcadence", pc_executable)
    pc.login()
    pc_page = pc.client.get("/apps/promptcadence/tokens", headers={"Accept": "text/html"}).text
    assert 'name="scope" multiple size="4"' in pc_page
    assert '<option value="approve">approve</option>' in pc_page


def test_several_chosen_scopes_are_joined_with_a_comma(tmp_path: Path) -> None:
    """PromptCadence reads `--scope` as a comma list (ADR-0049 rule 2); the select joins it."""
    directory = tmp_path / "promptcadence"
    directory.mkdir(parents=True)
    argv_log = directory / "argv.log"
    executable = directory / "promptcadence"
    executable.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {argv_log}\n'
        'if [ "$2" = "create" ]; then\n'
        '  printf \'{"name": "%s", "scope": "%s", "token": "pc_secret"}\' "$3" "$5"\n'
        "fi\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    console = _console(tmp_path, "promptcadence", executable)
    console.login()
    payload: dict[str, Any] = {"name": "ci", "scope": ["read", "write", "approve"]}
    page = console.post_form("/apps/promptcadence/tokens", payload)
    assert "pc_secret" in page.text
    assert "read,write,approve" in argv_log.read_text(encoding="utf-8")


def test_a_revocation_the_application_refuses_is_reported_in_its_own_words(
    tmp_path: Path,
) -> None:
    executable = _token_cli(tmp_path, "loadcoach", records=[])
    console = _console(tmp_path, "loadcoach", executable)
    console.login()
    page = console.post_form("/apps/loadcoach/tokens/revoke", {"name": "absent"})
    assert "no such active token" in page.text


def test_freeweights_tokens_page_points_at_its_configuration_key(tmp_path: Path) -> None:
    executable, _config, _document = fake_application(tmp_path, "freeweight")
    console = _console(tmp_path, "freeweight", executable)
    console.login()
    page = console.client.get("/apps/freeweight/tokens", headers={"Accept": "text/html"}).text
    assert "auth.tokens" in page
    assert "/apps/freeweight/settings" in page


def test_ideapress_has_no_token_surface_and_the_page_says_so(tmp_path: Path) -> None:
    executable, _config, _document = fake_application(tmp_path, "ideapress")
    console = _console(tmp_path, "ideapress", executable)
    console.login()
    body = console.client.get("/api/v1/apps/ideapress/tokens", headers=JSON_HEADERS).json()
    assert body["surface"] == "none"
    page = console.client.get("/apps/ideapress/tokens", headers={"Accept": "text/html"}).text
    assert "no API tokens at all" in page


def test_the_doctor_page_lists_findings_with_their_evidence_and_commands(
    tmp_path: Path,
) -> None:
    executable, config, _document = fake_application(
        tmp_path,
        "loadcoach",
        config_toml='[server]\nhost = "0.0.0.0"\n',  # noqa: S104 — the finding under test
    )
    console = _console(tmp_path, "loadcoach", executable)
    console.login()
    body = console.client.get("/api/v1/doctor", headers=JSON_HEADERS).json()
    rules = {one["rule"]: one for one in body["findings"]}
    assert rules["lan.bind.loadcoach"]["severity"] == "warning"
    assert rules["memory.unit.loadcoach"]["command"] == "wr-gym units sync"
    page = console.client.get("/doctor", headers={"Accept": "text/html"}).text
    assert "LAN_ACCESS.md §1" in page
    assert "wr-gym units sync" in page
    assert str(config) in json.dumps(body) or "loadcoach" in page


def test_the_doctor_reads_nothing_it_cannot_read_and_says_unknown(tmp_path: Path) -> None:
    """A host with no systemd degrades every unit rule to `unknown`, never to a failure."""
    executable, _config, _document = fake_application(tmp_path, "loadcoach")
    console = build_console(
        tmp_path / "console",
        extra_toml=f'[apps.loadcoach]\nexecutable = "{executable}"\n',
        systemd=FakeSystemdController(supported=False),
    )
    console.login()
    body = console.client.get("/api/v1/doctor", headers=JSON_HEADERS).json()
    units = [one for one in body["findings"] if one["rule"].startswith("memory.unit.")]
    assert units
    assert {one["severity"] for one in units} == {"unknown"}

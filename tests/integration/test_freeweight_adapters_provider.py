"""Row WP3 Gate C: FreeWeight's Adapters and Provider pages, its database's own figures, no stub.

Adapters reads FreeWeight's ``GET /adapters`` (added for this row, FreeWeight ``989e5a7``) or,
stopped, its ``adapters`` table; Provider edits the ``[provider]`` block through FreeWeight's own
``PUT /provider`` (ADR-0117) with spec §7.4's re-authentication for ``kind`` and ``base_url``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import respx

from tests.integration.test_freeweight_pages import (
    BASE,
    RUN,
    audit,
    fixture,
    freeweight_console,
    mock_api,
    page,
    post,
    route_for,
)
from tests.support import PASSWORD, fill_rows
from weightroom.web.rendering import app_side_nav_stubs

DIGEST = "sha256:" + "c3" * 32
RETIRED = "sha256:" + "d4" * 32
BASE_MODEL = "llamacpp/Qwen2.5-1.5B-Instruct.Q8_0@sha256:bbbbbbbbbbbb"

ADAPTERS: dict[str, Any] = {
    "enabled": True,
    "directory": "/home/jordan/models/adapters",
    "note": None,
    "provider_can_serve": True,
    "adapters": [
        {
            "name": "damaged",
            "artifact_sha256": DIGEST,
            "artifact_path": "/home/jordan/models/adapters/damaged.gguf",
            "manifest_path": "/home/jordan/models/adapters/damaged.manifest.json",
            "source_sha256": None,
            "base_model_name": "Qwen2.5-1.5B-Instruct.Q8_0",
            "base_artifact_digest": "sha256:" + "b" * 64,
            "base_confidence": "digest",
            "declared_capabilities": ["instruction_following"],
            "data_classification": "internal",
            "notes": None,
            "available": True,
            "unavailable_reason": None,
            "in_directory": True,
            "measured": True,
            "run_count": 2,
            "last_run_at": "2026-09-06T12:00:00.000Z",
            "subjects": [
                {
                    "base": BASE_MODEL,
                    "subject": f"{BASE_MODEL}+damaged",
                    "measured": {"instruction_following": 0.182, "structured_output": 0.0},
                    "base_measured": {"instruction_following": 0.727, "structured_output": 1.0},
                }
            ],
        },
        {
            "name": "retired",
            "artifact_sha256": RETIRED,
            "artifact_path": "/home/jordan/models/adapters/retired.gguf",
            "manifest_path": None,
            "source_sha256": None,
            "base_model_name": "Qwen2.5-1.5B-Instruct.Q8_0",
            "base_artifact_digest": None,
            "base_confidence": "name_only",
            "declared_capabilities": [],
            "data_classification": "internal",
            "notes": None,
            "available": False,
            "unavailable_reason": "no longer in the adapter directory",
            "in_directory": False,
            "measured": True,
            "run_count": 1,
            "last_run_at": "2026-09-05T12:00:00.000Z",
            "subjects": [
                {
                    "base": BASE_MODEL,
                    "subject": None,
                    "measured": {},
                    "base_measured": {"instruction_following": 0.727},
                }
            ],
        },
    ],
    "invalid": [
        {"path": "/home/jordan/models/adapters/broken.manifest.json", "problem": "not JSON"}
    ],
    "drafts": ["/home/jordan/models/adapters/new.manifest.draft.json"],
    "unmanifested": ["/home/jordan/models/adapters/stray.gguf"],
}
"""One healthy measured adapter and one measured and removed, as FreeWeight's own
``test_adapter_catalog`` pins the shape; the reference machine's FreeWeight has no adapter
directory configured (the recorded ``adapters.json``)."""


def _form(**overrides: str) -> dict[str, str]:
    """The provider block's form exactly as the recorded ``GET /provider`` renders it."""
    return {
        "base_digest": fixture("provider")["config_digest"],
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "timeout_seconds": "300.0",
        "model_directory": "",
        "state_dir": "",
        "server_path": "llama-server",
        **overrides,
    }


def _provider(router: Any) -> Any:  # noqa: ANN401 — a respx router, its route
    mock_api(router, bodies={"provider": fixture("provider")})
    return route_for(router, "PUT", "provider").mock(
        return_value=httpx.Response(200, json=fixture("provider"))
    )


def test_no_freeweight_page_is_a_stub() -> None:
    # Goals was the last, built by row WP4.
    assert app_side_nav_stubs("freeweight") == ()


# --- Adapters -------------------------------------------------------------------------------------


def test_adapters_list_each_with_its_base_its_runs_and_the_directorys_problems(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": ADAPTERS})
        text = page(console, f"{BASE}/adapters")
    assert f'href="{BASE}/adapters/damaged"' in text
    assert f'href="{BASE}/adapters/retired"' in text
    assert "no longer in the adapter directory" in text
    assert "not JSON" in text
    assert "new.manifest.draft.json" in text
    assert "stray.gguf" in text
    assert "/home/jordan/models/adapters" in text
    assert f'<a href="{BASE}/adapters" aria-current="page">Adapters</a>' in text


def test_adapters_off_says_which_key_turns_them_on(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": fixture("adapters")})
        text = page(console, f"{BASE}/adapters")
    assert "Adapters are off." in text
    assert "[adapters] directory" in text


def test_a_directory_under_a_provider_that_cannot_serve_one_is_named_as_inert(
    tmp_path: Path,
) -> None:
    """ADR-0140: configured and inert is a state, and the page says so rather than listing adapters
    that will never be used (WP6 finding 9)."""
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": {**ADAPTERS, "provider_can_serve": False}})
        text = page(console, f"{BASE}/adapters")
    assert "inert" in text
    assert 'provider.kind = "llamacpp"' in text
    assert f'href="{BASE}/adapters/damaged"' in text


def test_one_adapter_sets_its_scores_beside_the_bare_bases_with_its_runs_and_results(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        routes = mock_api(router, bodies={"adapters": ADAPTERS, "results": fixture("results")})
        text = page(console, f"{BASE}/adapters/damaged")
    assert "-0.545" in text and "-1.000" in text
    assert "0.727" in text and "0.182" in text
    assert "test_the_panel_still_separates_a_known_damaged_adapter" in text
    assert "retired" not in text  # only the adapter the page names
    assert routes["runs"].calls.last.request.url.params["adapter"] == "damaged"
    results = routes["results"].calls.last.request.url.params
    assert (results["adapter"], results["status"]) == ("damaged", "any")
    assert f'href="{BASE}/runs/{RUN}"' in text


def test_an_adapter_by_its_digest_and_one_nobody_knows(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": ADAPTERS, "results": fixture("results")})
        by_digest = page(console, f"{BASE}/adapters/{RETIRED}")
        unknown = page(console, f"{BASE}/adapters/no-such-adapter")
    assert "not measured yet" in by_digest
    assert "NOT_FOUND" in unknown
    assert "FreeWeight knows no adapter" in unknown


def test_a_stopped_freeweights_adapters_read_its_table(tmp_path: Path) -> None:
    console, database = freeweight_console(tmp_path, state="inactive")
    fill_rows(
        database,
        "adapters",
        [
            {
                "id": "01ADAPTERROW",
                "name": "terse",
                "artifact_sha256": DIGEST,
                "base_model_name": "Qwen2.5-1.5B-Instruct.Q8_0",
                "base_confidence": "digest",
                "data_classification": "internal",
                "declared_capabilities_json": json.dumps(["instruction_following"]),
            }
        ],
    )
    fill_rows(
        database,
        "runs",
        [{"id": "01ADAPTERRUN", "status": "completed", "adapter_id": "01ADAPTERROW"}],
    )
    listing = page(console, f"{BASE}/adapters")
    one = page(console, f"{BASE}/adapters/terse")
    assert "terse" in listing
    assert "From the database at revision 0010" in listing
    assert f'href="{BASE}/runs/01ADAPTERRUN"' in one
    assert "read only from FreeWeight's running API" in one


# --- Provider -------------------------------------------------------------------------------------


def test_the_provider_page_is_the_block_its_file_and_its_digest(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    document = fixture("provider")
    with respx.mock(assert_all_called=False) as router:
        _provider(router)
        text = page(console, f"{BASE}/provider")
    assert document["config_path"] in text
    assert f'name="base_digest" value="{document["config_digest"]}"' in text
    assert 'name="password" type="password"' in text
    assert f'<a href="{BASE}/provider" aria-current="page">Provider</a>' in text
    assert "From the API" in text


def test_a_timeout_change_saves_without_the_password(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _provider(router)
        response = post(console, f"{BASE}/provider", _form(timeout_seconds="301"))
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"{BASE}/provider?saved=1")
    assert json.loads(put.calls.last.request.content) == {
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model_directory": "",
        "state_dir": "",
        "server_path": "llama-server",
        "timeout_seconds": 301.0,
        "base_digest": fixture("provider")["config_digest"],
    }
    (row,) = audit(console, "freeweight.provider_save")
    assert (row["outcome"], row["params"]["fields"], row["params"]["touched_security"]) == (
        "ok",
        ["timeout_seconds"],
        [],
    )


def test_a_base_url_change_without_a_fresh_reauth_is_refused_and_nothing_is_sent(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _provider(router)
        response = post(console, f"{BASE}/provider", _form(base_url="http://127.0.0.1:11435"))
    assert response.status_code == 200
    assert "REAUTH_REQUIRED" in response.text
    assert 'value="http://127.0.0.1:11435"' in response.text  # what the operator typed is kept
    assert not put.called
    (row,) = audit(console, "freeweight.provider_save")
    assert (row["outcome"], row["params"]["touched_security"]) == ("refused", ["base_url"])


def test_a_kind_change_with_the_password_is_sent_and_the_password_is_nowhere_in_the_row(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _provider(router)
        response = post(
            console,
            f"{BASE}/provider",
            _form(kind="llamacpp", model_directory="/models", password=PASSWORD),
        )
    assert response.status_code == 303
    body = json.loads(put.calls.last.request.content)
    assert (body["kind"], body["model_directory"]) == ("llamacpp", "/models")
    (row,) = audit(console, "freeweight.provider_save")
    assert (row["outcome"], row["params"]["touched_security"]) == ("ok", ["kind"])
    assert row["security"] is True
    assert PASSWORD not in json.dumps(row)


def test_a_wrong_password_is_refused_and_nothing_is_sent(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _provider(router)
        response = post(console, f"{BASE}/provider", _form(kind="fake", password="not it"))
    assert "REAUTH_REQUIRED" in response.text
    assert not put.called


def test_freeweights_own_refusal_renders_as_itself_with_the_form_kept(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    conflict = {"error": {"code": "CONFLICT", "message": "the file changed since it was read"}}
    with respx.mock(assert_all_called=False) as router:
        _provider(router).mock(return_value=httpx.Response(409, json=conflict))
        response = post(console, f"{BASE}/provider", _form(timeout_seconds="42"))
    assert "CONFLICT" in response.text
    assert "the file changed since it was read" in response.text
    assert 'value="42"' in response.text


def test_a_timeout_that_is_not_a_number_is_refused_before_anything_is_sent(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _provider(router)
        response = post(console, f"{BASE}/provider", _form(timeout_seconds="soon"))
    assert "VALIDATION_ERROR" in response.text
    assert not put.called


def test_a_stopped_freeweights_provider_page_reads_only_from_its_api(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="inactive")
    text = page(console, f"{BASE}/provider")
    assert "reads only from its running API" in text
    assert 'name="base_digest"' not in text


# --- Database -------------------------------------------------------------------------------------


def test_the_database_page_adds_freeweights_backups_and_artifacts_while_it_answers(
    tmp_path: Path,
) -> None:
    console, _database = freeweight_console(tmp_path, state="active")
    stats = fixture("database-stats")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"database/stats": stats})
        text = page(console, f"{BASE}/database/admin")
    assert "FreeWeight's own statistics" in text
    assert stats["last_backup_path"] in text
    assert "no artifact directory configured" in text


def test_a_stopped_freeweights_database_page_does_not_call_it(tmp_path: Path) -> None:
    console, _database = freeweight_console(tmp_path, state="inactive")
    with respx.mock(assert_all_called=False):  # any request would fail the page
        text = page(console, f"{BASE}/database/admin")
    assert "own statistics" not in text


def test_an_adapters_name_and_a_machines_fingerprint_render_inert(tmp_path: Path) -> None:
    """Both reach an anchor: its text and its title are escaped, never concatenated into markup."""
    import copy

    from tests.security.test_chat_isolation import HOSTILE, _assert_inert

    console, _database = freeweight_console(tmp_path, state="active")
    adapters = copy.deepcopy(ADAPTERS)
    adapters["adapters"][0]["name"] = HOSTILE
    machines = copy.deepcopy(fixture("machines"))
    machines["items"][0]["machine_fingerprint"] = HOSTILE
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": adapters, "machines": machines})
        _assert_inert(page(console, f"{BASE}/adapters"))
        _assert_inert(page(console, f"{BASE}/machines"))

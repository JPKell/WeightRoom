"""Row WP2 Gate C: LoadCoach's Providers and Adapters under its tab, and no stub left.

Providers edits LoadCoach's registrations through its own ``PUT``/``DELETE /providers/{name}``
(ADR-0117), with spec §7.4's re-authentication for a security key; Adapters reads LoadCoach's
``GET /adapters`` (added for this row) or, stopped, its ``adapters`` projection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import respx

from tests.integration.test_loadcoach_pages import (
    API,
    BASE,
    CANONICAL,
    audit,
    fixture,
    loadcoach_console,
    mock_api,
    page,
    post,
)
from tests.support import PASSWORD, fill_rows
from weightroom.web.rendering import app_side_nav_stubs

ADAPTERS: dict[str, Any] = {
    "enabled": True,
    "note": None,
    "directory": "/home/jordan/models/adapters",
    "adapters": [
        {
            "name": "fact-check",
            "artifact_sha256": "sha256:" + "a" * 64,
            "artifact_path": "/home/jordan/models/adapters/fact-check.gguf",
            "manifest_path": "/home/jordan/models/adapters/fact-check.adapter.json",
            "base_model_name": "qwen3.5:9b",
            "base_artifact_digest": "sha256:" + "b" * 64,
            "base_confidence": "digest",
            "declared_capabilities": ["auditing.fact_check"],
            "data_classification": "confidential",
            "available": True,
            "unavailable_reason": None,
            "registered_on": ["llamacpp-local"],
            "pending_on": [],
            "notes": None,
            "in_directory": True,
            "adapter_id": "01ADAPTER",
            "resident": [
                {
                    "gpu_index": 0,
                    "base_canonical_id": "llamacpp/qwen3.5:9b@sha256:bbbb",
                    "last_used_at": "2026-09-10T00:00:00Z",
                }
            ],
            "routes": [
                {
                    "decision_id": "01DECISIONSELECTED",
                    "job_id": "01JOBSELECTED",
                    "task_profile_id": "auditing.fact_check",
                    "requested_at": "2026-09-10T00:00:00Z",
                    "rank": 1,
                    "rejected": False,
                    "rejection_reason": None,
                    "selected": True,
                },
                {
                    "decision_id": "01DECISIONREFUSED",
                    "job_id": None,
                    "task_profile_id": "auditing.fact_check",
                    "requested_at": "2026-09-09T23:00:00Z",
                    "rank": None,
                    "rejected": True,
                    "rejection_reason": "adapter_classification_conflict",
                    "selected": False,
                },
            ],
        }
    ],
    "invalid": [
        {"path": "/home/jordan/models/adapters/broken.adapter.json", "problem": "not JSON"}
    ],
    "drafts": [],
    "unmanifested": [],
}
"""The shape LoadCoach's ``tests/integration/test_adapters_api.py`` pins, for a directory holding
one adapter; the reference machine's LoadCoach has no adapter directory configured."""


def _form(**overrides: str) -> dict[str, str]:
    """The ``ollama`` registration's form exactly as the recorded ``GET /providers`` renders it."""
    return {
        "action": "save",
        "name": "ollama",
        "base_digest": "",
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "timeout_seconds": "300.0",
        "remote": "",
        "model_directory": "",
        "state_dir": "",
        "server_path": "llama-server",
        "enabled": "true",
        **overrides,
    }


def _providers(router: Any) -> Any:  # noqa: ANN401 — a respx router, its routes
    mock_api(router, bodies={"providers": fixture("providers")})
    return router.put(f"{API}/providers/ollama").mock(
        return_value=httpx.Response(200, json=fixture("providers"))
    )


def test_every_loadcoach_page_is_built_and_none_is_a_stub() -> None:
    assert app_side_nav_stubs("loadcoach") == ()


# --- Providers ------------------------------------------------------------------------------------


def test_providers_renders_each_registration_as_a_form_with_the_models_it_serves(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    serving = sum(1 for one in fixture("models")["models"] if one["provider_name"] == "ollama")
    with respx.mock(assert_all_called=False) as router:
        _providers(router)
        text = page(console, f"{BASE}/providers")
    assert 'id="provider-ollama"' in text
    assert "/home/jpk/.config/loadcoach/config.toml" in text
    assert f"Serves {serving} models in the registry." in text
    assert 'name="password" type="password"' in text
    assert '<a href="/apps/loadcoach/providers" aria-current="page">Providers</a>' in text
    assert "From the API" in text


def test_a_non_security_key_saves_without_the_password(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _providers(router)
        response = post(console, f"{BASE}/providers", _form(timeout_seconds="301"))
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"{BASE}/providers?saved=ollama")
    assert json.loads(put.calls.last.request.content) == {
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model_directory": "",
        "state_dir": "",
        "server_path": "llama-server",
        "remote": False,
        "enabled": True,
        "timeout_seconds": 301.0,
    }
    (row,) = audit(console, "loadcoach.provider_save")
    assert (row["outcome"], row["params"]["fields"], row["params"]["touched_security"]) == (
        "ok",
        ["timeout_seconds"],
        [],
    )


def test_a_security_key_without_a_fresh_reauth_is_refused_and_nothing_is_sent(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _providers(router)
        response = post(console, f"{BASE}/providers", _form(base_url="http://127.0.0.1:11435"))
    assert response.status_code == 200
    assert "REAUTH_REQUIRED" in response.text
    assert 'value="http://127.0.0.1:11435"' in response.text  # what the operator typed is kept
    assert not put.called
    (row,) = audit(console, "loadcoach.provider_save")
    assert (row["outcome"], row["params"]["touched_security"]) == ("refused", ["base_url"])


def test_a_security_key_with_the_password_is_sent_and_the_password_is_nowhere_in_the_row(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _providers(router)
        response = post(
            console,
            f"{BASE}/providers",
            _form(base_url="http://127.0.0.1:11435", remote="true", password=PASSWORD),
        )
    assert response.status_code == 303
    body = json.loads(put.calls.last.request.content)
    assert (body["base_url"], body["remote"]) == ("http://127.0.0.1:11435", True)
    (row,) = audit(console, "loadcoach.provider_save")
    assert (row["outcome"], row["params"]["touched_security"]) == ("ok", ["base_url", "remote"])
    assert PASSWORD not in json.dumps(row)


def test_a_wrong_password_is_refused_and_nothing_is_sent(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _providers(router)
        response = post(
            console, f"{BASE}/providers", _form(kind="llamacpp", password="not the password")
        )
    assert "REAUTH_REQUIRED" in response.text
    assert not put.called


def test_removal_is_previewed_then_sent_only_typed_and_reauthenticated(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _providers(router)
        delete = router.delete(f"{API}/providers/ollama").mock(
            return_value=httpx.Response(200, json=fixture("providers"))
        )
        preview = post(console, f"{BASE}/providers", {"action": "delete", "name": "ollama"})
        assert preview.status_code == 200
        assert "Remove <code>ollama</code>?" in preview.text
        assert "Routing stops choosing the" in preview.text
        assert CANONICAL in preview.text
        assert not delete.called
        untyped = post(
            console,
            f"{BASE}/providers",
            {"action": "delete", "name": "ollama", "confirm": "ollama"},
        )
        assert "REAUTH_REQUIRED" in untyped.text
        assert not delete.called
        sent = post(
            console,
            f"{BASE}/providers",
            {"action": "delete", "name": "ollama", "confirm": "ollama", "password": PASSWORD},
        )
    assert sent.status_code == 303
    assert sent.headers["location"] == f"{BASE}/providers?removed=ollama"
    assert delete.called
    outcomes = sorted(row["outcome"] for row in audit(console, "loadcoach.provider_delete"))
    assert outcomes == ["ok", "pending", "refused"]


def test_loadcoachs_own_refusal_renders_as_itself(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    conflict = {"error": {"code": "CONFLICT", "message": "the file changed since it was read"}}
    with respx.mock(assert_all_called=False) as router:
        _providers(router).mock(return_value=httpx.Response(409, json=conflict))
        response = post(console, f"{BASE}/providers", _form(timeout_seconds="42"))
    assert "CONFLICT" in response.text
    assert "the file changed since it was read" in response.text


def test_a_stopped_loadcoachs_providers_page_reads_only_from_its_api(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="inactive")
    text = page(console, f"{BASE}/providers")
    assert "reads only from its running API" in text
    assert 'id="provider-' not in text


# --- `enabled` and the llama.cpp quick-add (row WX9) ---------------------------------------------


def test_a_registration_can_be_disabled_from_the_page(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        put = _providers(router)
        response = post(console, f"{BASE}/providers", _form(enabled=""))
    assert response.status_code == 303
    assert json.loads(put.calls.last.request.content)["enabled"] is False
    (row,) = audit(console, "loadcoach.provider_save")
    assert (row["outcome"], row["params"]["fields"]) == ("ok", ["enabled"])


def test_the_enabled_box_is_ticked_for_a_registration_that_carries_no_such_key(
    tmp_path: Path,
) -> None:
    """A LoadCoach that predates the key answers without it, and true is its default."""
    document = fixture("providers")
    document["registrations"][0].pop("enabled")
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"providers": document})
        text = page(console, f"{BASE}/providers")
    assert 'name="enabled" value="true" checked' in text


def test_the_llamacpp_quick_add_prefills_the_form_and_says_what_it_needs(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        _providers(router)
        listing = page(console, f"{BASE}/providers")
        prefilled = page(console, f"{BASE}/providers?kind=llamacpp")
    assert 'href="/apps/loadcoach/providers?kind=llamacpp#provider-new"' in listing
    assert 'id="lc-new-kind" name="kind" value="llamacpp"' in prefilled
    assert "model_directory</code> is required" in prefilled
    # The password gate on a new registration is unchanged by the shortcut.
    assert 'id="lc-new-password" name="password" type="password"' in prefilled


# --- Adapters -------------------------------------------------------------------------------------


def test_adapters_shows_base_classification_holder_residency_and_routes(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": ADAPTERS})
        text = page(console, f"{BASE}/adapters")
    assert "fact-check" in text
    assert "local only" in text
    assert "llamacpp-local" in text
    assert "GPU 0" in text
    assert "1 selected · 1 refused" in text
    assert "adapter_classification_conflict" in text
    assert f'href="{BASE}/routing/decisions/01DECISIONSELECTED"' in text
    assert "not JSON" in text


def test_adapters_off_says_which_key_turns_them_on(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    off = {
        "enabled": False,
        "note": "adapters are not configured: set [adapters] directory to the directory holding "
        "your adapter artifacts and their reviewed manifests. Empty means off, deliberately.",
        "directory": None,
        "adapters": [],
        "invalid": [],
        "drafts": [],
        "unmanifested": [],
    }
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"adapters": off})
        text = page(console, f"{BASE}/adapters")
    assert "Adapters are off" in text
    assert "[adapters] directory" in text


def test_stopped_adapters_read_the_projection_its_residency_and_candidates(tmp_path: Path) -> None:
    console, database = loadcoach_console(tmp_path, state="inactive")
    fill_rows(
        database,
        "adapters",
        [
            {
                "id": "01ADAPTER",
                "name": "recorded-adapter",
                "base_identity_confidence": "digest",
                "data_classification": "internal",
                "available": 1,
            }
        ],
    )
    fill_rows(
        database,
        "residency",
        [{"id": "01RESIDENCY", "model_id": "01MODEL", "adapter_id": "01ADAPTER", "resident": 1}],
    )
    fill_rows(
        database,
        "routing_decisions",
        [
            {
                "id": "01DECISION",
                "selected_model_id": "01MODEL",
                "selected_adapter_id": "01ADAPTER",
                "requested_at": "2026-09-10T00:00:00Z",
            }
        ],
    )
    fill_rows(
        database,
        "routing_candidates",
        [
            {
                "id": "01CANDIDATE",
                "decision_id": "01DECISION",
                "model_id": "01MODEL",
                "adapter_id": "01ADAPTER",
                "rank": 1,
                "rejected": 0,
            }
        ],
    )
    text = page(console, f"{BASE}/adapters")
    assert "recorded-adapter" in text
    assert "GPU 0" in text
    assert "1 selected · 0 refused" in text
    assert "From the database at revision 0015" in text

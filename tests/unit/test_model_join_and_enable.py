"""services/catalog.py after ADR-0146: the model join ``model_refresh`` reports, and enable/disable.

The join runs over copies of the committed fixture databases (real schema, ``tests/support.py``),
the same way ``services/db_reader.py`` itself is tested — never a hand-built in-memory schema that
could drift from what FreeWeight and LoadCoach actually ship.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from tests.support import fake_application, fill_rows, fixture_database
from weightroom.config import Settings, load_settings
from weightroom.services.app_api import AppTimedOut, outcome_of
from weightroom.services.catalog import CatalogRefused, catalog_entries, set_enabled
from weightroom.services.database import Database, ensure_ready
from weightroom.services.db_reader import DatabaseUrlCache

FW_URL = "http://127.0.0.1:8765"
LC_URL = "http://127.0.0.1:8766"


def _own(tmp_path: Path) -> Database:
    database = Database.from_url(f"sqlite:///{tmp_path / 'weightroom.sqlite3'}")
    ensure_ready(database, auto_migrate=True)
    return database


def _settings(tmp_path: Path, *, freeweight_url: str, loadcoach_url: str) -> Settings:
    fw_executable, _cfg, _doc = fake_application(
        tmp_path, "freeweight", database_url=freeweight_url
    )
    lc_executable, _cfg, _doc = fake_application(tmp_path, "loadcoach", database_url=loadcoach_url)
    console = tmp_path / "console.toml"
    console.write_text(
        f'[apps.freeweight]\nexecutable = "{fw_executable}"\nbase_url = "{FW_URL}"\n'
        f'[apps.loadcoach]\nexecutable = "{lc_executable}"\nbase_url = "{LC_URL}"\n'
        '[host]\nollama_base_url = "http://127.0.0.1:11434"\n',
        encoding="utf-8",
    )
    return load_settings(config_path=console).settings


def _seed_freeweight(url: str) -> None:
    fill_rows(
        Path(url.removeprefix("sqlite:///")),
        "models",
        [
            {
                "id": "01FW0000000000000000000001",
                "provider_kind": "ollama",
                "provider_model_name": "gemma3:12b",
                "canonical_id": "ollama/gemma3:12b@sha256:aaa",
                "identity_confidence": "digest",
                "first_seen_at": "2026-01-01T00:00:00+00:00",
                "last_seen_at": "2026-01-01T00:00:00+00:00",
                "enabled": 1,
            },
            {
                "id": "01FW0000000000000000000002",
                "provider_kind": "llamacpp",
                "provider_model_name": "only-freeweight.gguf",
                "canonical_id": "llamacpp/only-freeweight@sha256:ccc",
                "identity_confidence": "digest",
                "first_seen_at": "2026-01-01T00:00:00+00:00",
                "last_seen_at": "2026-01-01T00:00:00+00:00",
                "enabled": 0,
            },
        ],
    )
    fill_rows(
        Path(url.removeprefix("sqlite:///")),
        "model_descriptors",
        [
            {
                "id": "01FWD000000000000000000001",
                "model_id": "01FW0000000000000000000001",
                "observed_at": "2026-01-02T00:00:00+00:00",
                "family": "gemma",
                "quantization": "q8_0",
                "size_bytes": 123_456,
                "max_context": 8192,
                "descriptor_hash": "hash1",
            },
        ],
    )
    fill_rows(
        Path(url.removeprefix("sqlite:///")),
        "capability_evidence",
        [
            {
                "id": "01FWE000000000000000000001",
                "model_id": "01FW0000000000000000000001",
                "runtime_profile_id": "01RP0000000000000000000001",
                "machine_id": "01MC0000000000000000000001",
                "capability_id": "reasoning",
                "score": 0.8,
                "confidence": 0.9,
                "sample_count": 10,
                "excluded_count": 0,
                "identity_confidence": "digest",
                "measured_at": "2026-02-01T00:00:00+00:00",
                "computed_at": "2026-02-01T00:00:00+00:00",
                "policy_version": "v1",
                "vocabulary_version": "v1",
                "judge_validity_factor": 1.0,
                "created_at": "2026-02-01T00:00:00+00:00",
                "subject_canonical_id": "ollama/gemma3:12b@sha256:aaa",
            },
        ],
    )


def _seed_loadcoach(url: str) -> None:
    path = Path(url.removeprefix("sqlite:///"))
    fill_rows(
        path,
        "models",
        [
            {
                "id": "01LC0000000000000000000001",
                "provider_kind": "ollama",
                "provider_model_name": "gemma3:12b",
                "canonical_id": "ollama/gemma3:12b@sha256:aaa",
                "identity_confidence": "digest",
                "max_context": 8192,
                "size_bytes": 123_456,
                "quantization": "q8_0",
                "family": "gemma",
                "first_seen_at": "2026-01-01T00:00:00+00:00",
                "last_seen_at": "2026-01-01T00:00:00+00:00",
                "available": 1,
                "enabled": 1,
            },
            {
                "id": "01LC0000000000000000000002",
                "provider_kind": "ollama",
                "provider_model_name": "only-loadcoach",
                "canonical_id": "ollama/only-loadcoach@sha256:bbb",
                "identity_confidence": "digest",
                "first_seen_at": "2026-01-01T00:00:00+00:00",
                "last_seen_at": "2026-01-01T00:00:00+00:00",
                "available": 1,
                "enabled": 1,
            },
        ],
    )
    fill_rows(
        path,
        "residency",
        [
            {
                "id": "01RES000000000000000000001",
                "model_id": "01LC0000000000000000000001",
                "gpu_index": 0,
                "loaded_at": "2026-02-01T00:00:00+00:00",
                "last_used_at": "2026-02-01T00:00:00+00:00",
                "resident": 1,
            },
        ],
    )


def _prepare(tmp_path: Path) -> Settings:
    fw_path = fixture_database(tmp_path, "freeweight-0010")
    lc_path = fixture_database(tmp_path, "loadcoach-0015")
    fw_url = f"sqlite:///{fw_path}"
    lc_url = f"sqlite:///{lc_path}"
    _seed_freeweight(fw_url)
    _seed_loadcoach(lc_url)
    return _settings(tmp_path, freeweight_url=fw_url, loadcoach_url=lc_url)


def test_the_join_reads_both_fixture_databases_by_canonical_identity(tmp_path: Path) -> None:
    settings = _prepare(tmp_path)
    entries = catalog_entries(
        settings, _own(tmp_path), urls=DatabaseUrlCache(), monotonic=0.0, ollama_client=None
    )
    by_id = {entry.canonical_id: entry for entry in entries}
    assert set(by_id) == {
        "ollama/gemma3:12b@sha256:aaa",
        "llamacpp/only-freeweight@sha256:ccc",
        "ollama/only-loadcoach@sha256:bbb",
    }

    joined = by_id["ollama/gemma3:12b@sha256:aaa"]
    assert set(joined.apps) == {"freeweight", "loadcoach"}
    assert joined.apps["freeweight"].enabled is True
    assert joined.apps["freeweight"].size_bytes == 123_456
    assert joined.apps["freeweight"].max_context == 8192
    assert joined.apps["freeweight"].evidence_measured_at is not None
    assert joined.apps["loadcoach"].resident is True
    assert joined.apps["loadcoach"].available is True

    fw_only = by_id["llamacpp/only-freeweight@sha256:ccc"]
    assert set(fw_only.apps) == {"freeweight"}
    assert fw_only.apps["freeweight"].enabled is False
    assert fw_only.apps["freeweight"].size_bytes is None
    assert fw_only.apps["freeweight"].evidence_measured_at is None

    lc_only = by_id["ollama/only-loadcoach@sha256:bbb"]
    assert set(lc_only.apps) == {"loadcoach"}
    assert lc_only.apps["loadcoach"].resident is False  # a known fact, not "unknown"


@respx.mock
def test_enable_disable_calls_the_applications_own_endpoint(tmp_path: Path) -> None:
    settings = _prepare(tmp_path)
    route = respx.post(f"{LC_URL}/api/v1/models/01LC0000000000000000000001/enabled").mock(
        return_value=httpx.Response(200, json={"enabled": False})
    )
    result = set_enabled(
        settings, "loadcoach", "01LC0000000000000000000001", enabled=False, client=httpx.Client()
    )
    assert route.called
    assert b"false" in route.calls.last.request.content
    assert result == {"enabled": False}


@respx.mock
def test_enable_disable_raises_on_refusal(tmp_path: Path) -> None:
    settings = _prepare(tmp_path)
    respx.post(f"{LC_URL}/api/v1/models/nope/enabled").mock(
        return_value=httpx.Response(404, json={"error": {"message": "unknown model"}})
    )
    with pytest.raises(CatalogRefused):
        set_enabled(settings, "loadcoach", "nope", enabled=True, client=httpx.Client())
    # A refusal still audits `refused` through the same function a timeout audits `pending` with.
    assert outcome_of(CatalogRefused("no", details={})) == "refused"


@respx.mock
def test_enable_disable_raises_apptimedout_on_a_timeout_not_catalogrefused(
    tmp_path: Path,
) -> None:
    """Row WPF11: a slow ``enabled`` call is not a refusal — LoadCoach may still be applying it.

    ``outcome_of`` (WPF1) reads ``AppTimedOut`` as ``pending``; before this row every failure here
    was ``CatalogRefused``, which every caller (``catalog.py``, ``freeweight.py``, ``loadcoach.py``)
    audits `refused` whatever the cause.
    """
    settings = _prepare(tmp_path)
    respx.post(f"{LC_URL}/api/v1/models/01LC0000000000000000000001/enabled").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )
    with pytest.raises(AppTimedOut) as excinfo:
        set_enabled(
            settings,
            "loadcoach",
            "01LC0000000000000000000001",
            enabled=False,
            client=httpx.Client(),
        )
    assert outcome_of(excinfo.value) == "pending"

"""Security Standards §14, item by item, plus spec §14's own rows and ADR-0126's.

Every bullet is either held here, held by a named test elsewhere (asserted to exist at the
bottom), or does not apply to WeightRoomGym at Phase 1 for a reason stated beside it.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path

import pytest

from tests.support import JSON_HEADERS, PASSWORD, USERNAME, Console, api_routes, build_console
from weightroom.config import InsecureBindingError, load_settings
from weightroom.domain import auth as auth_domain
from weightroom.observability.logging import _JsonFormatter, _TextFormatter
from weightroom.web.session import SESSION_COOKIE_NAME

HOSTILE = "{{ 7 * 7 }} <script>alert('x')</script> ../../etc/passwd '; DROP TABLE audit_log; --"


@pytest.fixture
def console(tmp_path: Path) -> Console:
    return build_console(tmp_path)


# §14: path traversal — no route accepts a filesystem path without going through
# services/docs.py's resolve-then-check containment (security standards §5); every route below
# was reviewed against that discipline before being added to this allowlist.
_REVIEWED_PATH_PARAMETERS = frozenset(
    {
        # resolve_doc_path: resolved, then checked against [docs] root — the JSON route and its
        # HTML page both take the same parameter.
        ("/api/v1/docs/page", "path"),
        ("/docs/page", "path"),
    }
)


def test_no_route_accepts_a_path_shaped_parameter(console: Console) -> None:
    suspicious = []
    for path, route in api_routes(console.client.app):
        for parameter in route.dependant.query_params + route.dependant.path_params:
            if any(word in parameter.name for word in ("path", "file", "dir")):
                if (path, parameter.name) in _REVIEWED_PATH_PARAMETERS:
                    continue
                suspicious.append((path, parameter.name))
    assert suspicious == []


# §14: oversize body rejected before buffering


def test_an_oversize_body_is_413_before_it_is_read(tmp_path: Path) -> None:
    console = build_console(tmp_path, extra_toml="max_body_bytes = 1024\n")
    console.login()
    declared = console.client.post(
        "/api/v1/reauth",
        content=b"x" * 4096,
        headers={**JSON_HEADERS, "Content-Length": "4096"},
    )
    assert declared.status_code == 413
    assert declared.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


# §14: non-loopback bind without a credential refuses to start — ADR-0126 rule 6 translated


def test_non_loopback_bind_refusals(tmp_path: Path) -> None:
    file = tmp_path / "c.toml"
    file.write_text('[server]\nhost = "10.77.10.84"\n')
    with pytest.raises(InsecureBindingError):
        load_settings(config_path=file)
    # the account and TLS members are tests/integration/test_runtime_refusals.py


# §14: authenticated endpoints reject a missing, malformed and revoked credential


def test_missing_malformed_and_revoked_sessions_are_401(console: Console) -> None:
    assert console.client.get("/api/v1/audit").status_code == 401
    console.client.cookies.set(SESSION_COOKIE_NAME, "not-a-session\x00", domain="localhost")
    assert console.client.get("/api/v1/audit").status_code == 401
    console.client.cookies.clear()
    console.login()
    assert console.client.get("/api/v1/audit").status_code == 200
    console.post_form("/logout", {})
    assert console.client.get("/api/v1/audit").status_code == 401


# §14: constant-time comparison; the stored value is a hash (row inspected in test_auth_flow)


def test_password_comparison_is_constant_time_by_construction() -> None:
    source = inspect.getsource(auth_domain.verify_password)
    assert "hmac.compare_digest" in source
    assert "==" not in source.split("return")[-1]


# §14: log output contains no secret for a request that carried one


def test_log_formatters_redact_secret_shaped_fields() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "auth.failed", (), None)
    record.password = "hunter22"
    record.cookie = "abc"
    record.username = "jordan"
    for formatter in (_JsonFormatter(), _TextFormatter()):
        text = formatter.format(record)
        assert "hunter22" not in text and "abc" not in text.split("cookie")[-1][:10]
        assert "jordan" in text


def test_a_failed_login_logs_the_address_never_the_password(
    console: Console, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        console.login(password="the wrong secret")
    assert "the wrong secret" not in caplog.text


# §14: archive handling — W6's chat attachments (text and markdown, capped, never unpacked:
# tests/integration/test_chat_loadcoach.py refuses a .pdf, binary and oversize), and the bundles
# below. W8's GGUF drop-in left with the catalog (ADR-0146).

UPLOAD_ROUTES = frozenset(
    {
        "/api/v1/chat/conversations/{conversation_id}/attachments",
        "/chat/{conversation_id}/attachments",
        # WP2: an evidence bundle, parsed as JSON and handed to LoadCoach, which validates it
        # (tests/integration/test_loadcoach_queue_evidence.py refuses a file that is not JSON).
        "/apps/loadcoach/evidence/import",
        # WP4: a goal bundle, parsed as JSON and handed to FreeWeight's import, which checks its
        # size, members and hash before writing (tests/integration/test_freeweight_goals.py refuses
        # a file that is not JSON before anything is sent).
        "/apps/freeweight/goals/import",
    }
)


def test_only_the_named_routes_accept_an_uploaded_file(console: Console) -> None:
    accepting = set()
    for path, route in api_routes(console.client.app):
        for body_field in route.dependant.body_params:
            if "UploadFile" in str(body_field.field_info.annotation):
                accepting.add(path)
    assert accepting == UPLOAD_ROUTES


# §14: hostile model output — Phase 1 renders no model output; the audit page escapes everything


def test_hostile_text_in_an_audit_row_renders_escaped(console: Console) -> None:
    console.login(username=HOSTILE, password="whatever password")  # a refused login row
    console.login()
    page = console.client.get("/audit", headers={"Accept": "text/html"})
    assert page.status_code == 200
    assert "<script>alert" not in page.text and "&lt;script&gt;alert" in page.text
    assert "{{ 7 * 7 }}" in page.text  # rendered as text, never evaluated


# §14 / ADR-0026 §1: an unexpected Host is 421 on both binds, before authentication


def test_wrong_host_is_421_on_loopback_and_lan_binds(tmp_path: Path) -> None:
    loopback = build_console(tmp_path / "a")
    assert loopback.client.get("/api/v1/version", headers={"Host": "evil"}).status_code == 421
    lan = build_console(tmp_path / "b", host="10.77.10.84")
    assert lan.client.get("/api/v1/version", headers={"Host": "evil"}).status_code == 421
    ok = lan.client.get("/api/v1/version", headers={"Host": "jordan-main.local:8769"})
    assert ok.status_code == 200
    unauthenticated = lan.client.get("/api/v1/audit", headers={"Host": "evil"})
    assert unauthenticated.status_code == 421  # before authentication, not 401


# §14 / ADR-0026 §2 / ADR-0126 rule 5: forged form refused, cross-origin JSON refused


def test_a_forged_form_post_is_csrf_failed_and_a_valid_one_succeeds(console: Console) -> None:
    forged = console.client.post(
        "/login", data={"username": USERNAME, "password": PASSWORD}, headers={"Accept": "text/html"}
    )
    assert forged.status_code == 403 and forged.json()["error"]["code"] == "CSRF_FAILED"
    assert console.login().status_code == 303


def test_json_writes_need_same_origin_and_a_matching_origin(console: Console) -> None:
    body = {"username": USERNAME, "password": PASSWORD}
    no_site = console.client.post(
        "/api/v1/login", json=body, headers={"Content-Type": "application/json"}
    )
    assert no_site.status_code == 403 and no_site.json()["error"]["code"] == "CSRF_FAILED"
    cross = console.client.post(
        "/api/v1/login",
        json=body,
        headers={"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"},
    )
    assert cross.status_code == 403
    bad_origin = console.client.post(
        "/api/v1/login",
        json=body,
        headers={**JSON_HEADERS, "Origin": "https://attacker.example"},
    )
    assert bad_origin.status_code == 403
    typed = console.client.post(
        "/api/v1/login",
        json=body,
        headers={"Content-Type": "application/json", "Sec-Fetch-Site": "none"},
    )
    assert typed.status_code == 201
    console.client.cookies.clear()
    same = console.client.post(
        "/api/v1/login", json=body, headers={**JSON_HEADERS, "Origin": "https://localhost"}
    )
    assert same.status_code == 201


# §14: /version answers without a credential while /health does not


def test_version_is_open_and_health_is_not(console: Console) -> None:
    assert console.client.get("/api/v1/version").status_code == 200
    assert console.client.get("/api/v1/health").status_code == 401
    console.login()
    assert console.client.get("/api/v1/health").status_code == 200


# spec §14's own rows, each held by a named test elsewhere. The registry below is the row's
# checklist made executable (row W10): a renamed or deleted test fails here by name.

SPEC_14_ROWS: dict[str, tuple[str, ...]] = {
    # session fixation, idle and absolute expiry, logout, the login brake
    "integration/test_auth_flow.py": (
        "test_a_new_session_id_on_every_login",
        "test_idle_expiry_ends_the_session",
        "test_absolute_expiry_ends_the_session",
        "test_logout_deletes_the_row",
        "test_the_login_brake_is_five_per_minute",
        "test_the_stored_password_is_a_hash_with_its_parameters",
        "test_a_lan_bind_with_no_account_is_never_open",
    ),
    # the trust listener serves two routes and refuses every other, never with a cookie
    "integration/test_trust_listener.py": (
        "test_root_crt_and_trust_answer_200_without_any_cookie",
        "test_every_other_path_is_404",
    ),
    # the startup refusals off loopback
    "integration/test_runtime_refusals.py": ("without_an_account_is_insecure_binding",),
    # the guard's five conditions, each failed alone; the never-writable list by name
    "unit/test_guard_domain.py": (
        "test_each_condition_fails_alone",
        "test_a_write_to_every_never_writable_table_is_refused_by_name",
        "test_ddl_pragma_vacuum_and_everything_but_select_and_dml_are_refused_by_name",
    ),
    "integration/test_db_guard.py": (
        "test_each_condition_failed_alone_refuses_with_its_code_and_writes_nothing",
        "test_a_write_that_passes_all_five_conditions_lands_with_its_backup_and_its_row",
    ),
    # model output is data: the injection corpus against chat, and no host but the two backends
    "security/test_chat_isolation.py": (
        "test_the_injection_corpus_renders_inert_in_a_loadcoach_answer_and_its_thinking",
        "test_the_injection_corpus_renders_inert_in_promptcadence_cards_and_halts",
        "test_chat_contacts_no_host_but_the_two_configured_base_urls",
    ),
    # sudo is never invoked; subprocesses are argv lists over an allowlisted environment
    "security/test_subprocess_discipline.py": (
        "test_sudo_is_never_shaped_like_an_executable",
        "test_no_module_runs_a_shell",
        "test_every_subprocess_call_passes_a_list_and_an_environment",
    ),
    # every state-changing route audited; no audit row or log line carries a secret
    "security/test_audit_routes.py": (
        "test_each_state_changing_route_writes_exactly_one_audit_row",
    ),
    # a LoadCoach registration's security keys, a new one and a removal re-authenticate (row WP2)
    # FreeWeight's provider block re-authenticates on kind and base_url (row WP3)
    "integration/test_freeweight_adapters_provider.py": (
        "test_a_base_url_change_without_a_fresh_reauth_is_refused_and_nothing_is_sent",
        "test_a_wrong_password_is_refused_and_nothing_is_sent",
    ),
    # a sample's response, a juror's rationale and a comparison's labels render inert (row WP3)
    "integration/test_freeweight_pages.py": (
        "test_the_case_inspector_renders_model_and_juror_text_inert",
    ),
    "integration/test_freeweight_results_evidence.py": (
        "test_labels_on_a_comparison_render_inert",
    ),
    # a goal's intent, criteria and tasks, and a draft's, render inert on the Goals pages (row WP4)
    "integration/test_freeweight_goals.py": (
        "test_the_injection_corpus_renders_inert_in_a_goal_and_a_draft",
    ),
    # a sample's text, a grader's note and a juror's rationale render inert when grading and in
    # the agreement report (row WP4)
    "integration/test_freeweight_calibration.py": (
        "test_the_injection_corpus_renders_inert_in_grading_and_the_report",
    ),
    "integration/test_loadcoach_providers_adapters.py": (
        "test_a_security_key_without_a_fresh_reauth_is_refused_and_nothing_is_sent",
        "test_a_wrong_password_is_refused_and_nothing_is_sent",
        "test_removal_is_previewed_then_sent_only_typed_and_reauthenticated",
    ),
    "security/test_redaction_sweep.py": (
        "test_no_audit_row_and_no_log_line_carries_a_secret_after_every_exercise",
    ),
    # an author's brief and a model's unit text on IdeaPress's pages render inert (row WP5)
    "integration/test_ideapress_work.py": (
        "test_the_injection_corpus_renders_inert_in_a_brief",
        "test_the_injection_corpus_renders_inert_in_unit_content_and_the_workspace",
        "test_an_export_downloads_as_an_attachment_and_is_never_shown_inline",
    ),
    # the docs viewer serves only under [docs] root; a symlink out is refused
    "unit/test_docs.py": ("test_a_symlinked_file_pointing_out_of_the_root_is_refused",),
    # the console serves with no network at all
    "e2e/test_network_isolation.py": (
        "test_every_page_renders_with_every_application_stopped_and_no_socket",
    ),
}


@pytest.mark.parametrize(("file", "names"), sorted(SPEC_14_ROWS.items()))
def test_the_named_tests_exist(file: str, names: tuple[str, ...]) -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / file).read_text(encoding="utf-8")
    for name in names:
        assert name in text, f"{file} no longer holds {name}"

"""Row WP2 Gate B: LoadCoach's Queue with its jobs, and its Evidence — read, streamed and acted on.

Recordings are the reference machine's LoadCoach 1.5.0 (``tests/fixtures/loadcoach``). A job's
stream with thinking in it is written out below frame by frame, in LoadCoach's own frame shapes
(``services/job_events.py``): the recorded job ran synchronously and streamed no thinking.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from tests.integration.test_loadcoach_pages import (
    API,
    BASE,
    HTML,
    audit,
    fixture,
    loadcoach_console,
    mock_api,
    page,
    post,
)
from tests.security.test_chat_isolation import HOSTILE, _assert_inert
from tests.support import fill_rows

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loadcoach"
JOB = "01M277XCSBNY229K1SESEFCJ0A"
STOPPED_JOB = "01STOPPEDJOB0000000000000A"


def _frame(event: str, payload: dict[str, Any], ident: int, *, bare: bool = False) -> str:
    data = (
        payload
        if bare
        else {
            "generated_at": "2026-09-10T00:00:00Z",
            "generator": {"name": "loadcoach", "version": "1.5.0"},
            "payload": payload,
        }
    )
    return f"id: {ident}\nevent: {event}\ndata: {json.dumps(data)}\n\n"


def _state(message: str) -> dict[str, Any]:
    return {"timestamp": "2026-09-10T00:00:01Z", "message": message, "data": {}}


JOB_STREAM = "".join(
    [
        _frame("job.queued", _state("queued at priority 500"), 1),
        _frame("job.executing", _state("executing on ollama/gpt-oss:20b"), 2),
        _frame("thinking", {"delta": "Weighing the request", "index": 0}, 3),
        _frame("token", {"delta": "Ready", "index": 0}, 4, bare=True),
        _frame("job.completed", _state("completed"), 5),
        _frame("job.queued", _state("a frame after the terminal one"), 6),
    ]
)


def _stream(router: Any, path: str, body: str) -> Any:  # noqa: ANN401 — a respx router and route
    return router.get(f"{API}/{path}").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode()
        )
    )


def _queue_bodies() -> dict[str, Any]:
    return {"queue": fixture("queue"), "jobs": fixture("jobs")}


# --- The queue ------------------------------------------------------------------------------------


def test_the_queue_page_reads_the_report_and_the_jobs_and_offers_the_controls(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies=_queue_bodies())
        text = page(console, f"{BASE}/queue")
        history = page(console, f"{BASE}/queue/history")
        new = page(console, f"{BASE}/queue/new")
    # Row WX9: current / new job / history are three pages, and only the first one streams.
    assert "0 of at most 1000" in text
    assert "ollama/deepseek-coder-v2:latest@sha256:63fb193b3a9b" in text  # its breaker
    assert f'sse-connect="{BASE}/queue/stream"' in text
    assert text.count(f'action="{BASE}/queue/control"') == 3
    assert f'href="{BASE}/queue/jobs/{JOB}"' in history
    assert f'sse-connect="{BASE}/queue/stream"' not in history
    assert f'action="{BASE}/queue/jobs"' in new
    assert "From the API" in text


def test_pause_asks_first_saying_what_stops_and_sends_only_once_confirmed(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies=_queue_bodies())
        pause = router.post(f"{API}/queue/pause").mock(
            return_value=httpx.Response(202, json={"paused": True, "draining": False})
        )
        asked = post(console, f"{BASE}/queue/control", {"verb": "pause"})
        assert asked.status_code == 200
        assert not pause.called
        assert "Pause LoadCoach's queue?" in asked.text
        assert "Synchronous generation is not held" in asked.text
        assert 'name="confirmed" value="yes"' in asked.text
        sent = post(console, f"{BASE}/queue/control", {"verb": "pause", "confirmed": "yes"})
    assert sent.status_code == 303
    assert sent.headers["location"] == f"{BASE}/queue"
    assert pause.called
    done, pending = sorted(audit(console, "loadcoach.queue_pause"), key=lambda row: row["outcome"])
    assert (done["outcome"], done["params"]["confirmed"]) == ("ok", True)
    assert (pending["outcome"], pending["params"]["confirmed"]) == ("pending", False)


@pytest.mark.parametrize("verb", ["resume", "drain"])
def test_resume_and_drain_send_their_verb_once_confirmed(tmp_path: Path, verb: str) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies=_queue_bodies())
        control = router.post(f"{API}/queue/{verb}").mock(return_value=httpx.Response(202, json={}))
        response = post(console, f"{BASE}/queue/control", {"verb": verb, "confirmed": "yes"})
    assert response.status_code == 303
    assert control.called
    (row,) = audit(console, f"loadcoach.queue_{verb}")
    assert row["outcome"] == "ok"


def test_a_refused_control_renders_loadcoachs_code(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    refusal = {"error": {"code": "FORBIDDEN", "message": "queue control needs admin"}}
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies=_queue_bodies())
        router.post(f"{API}/queue/drain").mock(return_value=httpx.Response(403, json=refusal))
        response = post(console, f"{BASE}/queue/control", {"verb": "drain", "confirmed": "yes"})
    assert response.status_code == 200
    assert "FORBIDDEN" in response.text
    (row,) = audit(console, "loadcoach.queue_drain")
    assert row["outcome"] == "refused"


def test_the_queue_stream_becomes_regions_rendered_here_and_closes_with_loadcoachs(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    recorded = (FIXTURES / "queue-stream.sse").read_text(encoding="utf-8")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        _stream(router, "queue/stream", ": heartbeat\n\n" + recorded)
        text = console.client.get(f"{BASE}/queue/stream").text
    assert text.startswith(": heartbeat\n\n")
    assert "event: queue.status\ndata: " in text
    assert "0 of at most 1000" in text
    assert '\\"kv-list\\"' not in text  # LoadCoach's own escaped html never passes through
    assert text.endswith("event: stream.closed\ndata: closed\n\n")


def test_a_stopped_queue_lists_jobs_from_the_database_and_offers_no_control(
    tmp_path: Path,
) -> None:
    console, database = loadcoach_console(tmp_path, state="inactive")
    fill_rows(
        database,
        "jobs",
        [
            {
                "id": STOPPED_JOB,
                "task_profile_id": "recorded.task",
                "task_profile_version": "1.0.0",
                "state": "completed",
                "class": "normal",
                "source": "promptcadence",
                "created_at": "2026-09-10T00:00:00Z",
            }
        ],
    )
    text = page(console, f"{BASE}/queue")
    history = page(console, f"{BASE}/queue/history")
    assert STOPPED_JOB in history
    assert "recorded.task" in history
    assert "reads only from its running API" in text
    assert f'action="{BASE}/queue/control"' not in text
    assert "From the database at revision 0015" in history


# --- Jobs -----------------------------------------------------------------------------------------


def test_submit_builds_the_jobs_body_opens_the_job_and_never_audits_the_prompt(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies=_queue_bodies())
        submit = router.post(f"{API}/jobs").mock(
            return_value=httpx.Response(202, json={"job_id": "01NEWJOB", "state": "queued"})
        )
        response = post(
            console,
            f"{BASE}/queue/jobs",
            {
                "task": "general.chat",
                "prompt": "A prompt that must stay out of the trail.",
                "system": "",
                "class": "background",
                "priority": "150",
                "max_wait_seconds": "",
                "idempotent": "true",
                "stream": "true",
                "data_classification": "internal",
                "model": "",
                "adapter": "",
                "temperature": "0.2",
                "max_output_tokens": "64",
                "think": "false",
                "idempotency_key": "01KEYFROMTHEPAGE",
            },
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"{BASE}/queue/jobs/01NEWJOB"
    assert json.loads(submit.calls.last.request.content) == {
        "task": "general.chat",
        "prompt": "A prompt that must stay out of the trail.",
        "class": "background",
        "idempotent": True,
        "stream": True,
        "priority": 150,
        "data_classification": "internal",
        "sampling": {"temperature": 0.2, "max_output_tokens": 64, "think": False},
        "idempotency_key": "01KEYFROMTHEPAGE",
    }
    (row,) = audit(console, "loadcoach.job_submit")
    assert row["target"] == "01NEWJOB"
    assert "must stay out" not in json.dumps(row)


def test_a_refused_submission_keeps_the_form_and_names_the_code(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    refusal = {"error": {"code": "VALIDATION_ERROR", "message": "priority 900 is outside batch"}}
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies=_queue_bodies())
        router.post(f"{API}/jobs").mock(return_value=httpx.Response(400, json=refusal))
        response = post(
            console,
            f"{BASE}/queue/jobs",
            {
                "task": "general.chat",
                "prompt": "kept on the page",
                "class": "batch",
                "priority": "900",
            },
        )
    assert "VALIDATION_ERROR" in response.text
    assert "kept on the page" in response.text
    assert 'value="900"' in response.text


def test_a_job_page_shows_its_attempts_validation_output_and_explanation(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(
            router,
            bodies={f"jobs/{JOB}": fixture("job"), f"jobs/{JOB}/explanation": fixture("decision")},
        )
        text = page(console, f"{BASE}/queue/jobs/{JOB}")
    assert "The result of the arithmetic expression 3 + 4 is 7." in text
    assert "<code>stop</code>" in text
    assert ">length<" in text  # the validation check
    assert "insufficient_vram" in text  # the explanation's rejections
    assert f'data-log-stream="{BASE}/queue/jobs/{JOB}/events"' in text
    assert "data-reply-stream" not in text  # a finished job has no live reply
    assert f'action="{BASE}/queue/jobs/{JOB}/feedback"' in text
    assert f'action="{BASE}/queue/jobs/{JOB}/cancel"' not in text


def test_the_injection_corpus_renders_inert_in_a_jobs_output_and_thinking(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    job = fixture("job")
    job["output"]["text"] = HOSTILE
    job["reasoning"] = {"available": True, "summary": HOSTILE, "source": "provider"}
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={f"jobs/{JOB}": job})
        router.get(f"{API}/jobs/{JOB}/explanation").mock(
            return_value=httpx.Response(404, json={"error": {"code": "JOB_NOT_FOUND"}})
        )
        text = page(console, f"{BASE}/queue/jobs/{JOB}")
    _assert_inert(text)
    assert "No routing decision is recorded for this job yet." in text


def test_a_running_job_offers_cancel_and_its_live_reply(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    job = {**fixture("job"), "state": "executing"}
    with respx.mock(assert_all_called=False) as router:
        mock_api(
            router, bodies={f"jobs/{JOB}": job, f"jobs/{JOB}/explanation": fixture("decision")}
        )
        text = page(console, f"{BASE}/queue/jobs/{JOB}")
    assert f'data-reply-stream="{BASE}/queue/jobs/{JOB}/reply"' in text
    assert f'action="{BASE}/queue/jobs/{JOB}/cancel"' in text
    assert 'class="chat-thinking" hidden' in text


def test_a_jobs_stream_becomes_log_lines_and_closes_on_the_terminal_event(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        _stream(router, f"jobs/{JOB}/stream", JOB_STREAM)
        text = console.client.get(f"{BASE}/queue/jobs/{JOB}/events").text
    assert text.count("event: log\n") == 3
    assert "executing on ollama/gpt-oss:20b" in text
    assert "Weighing the request" not in text  # thinking is the reply's, not the log's
    assert "after the terminal one" not in text
    assert text.rstrip().split("\n\n")[-1].count("event: log.closed") == 1


def test_the_reply_stream_carries_thinking_and_tokens_unchanged(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router)
        route = _stream(router, f"jobs/{JOB}/stream", JOB_STREAM)
        text = console.client.get(
            f"{BASE}/queue/jobs/{JOB}/reply", headers={"Last-Event-ID": "2"}
        ).text
    assert text == JOB_STREAM
    assert route.calls.last.request.headers["last-event-id"] == "2"


def test_cancel_and_feedback_send_loadcoachs_bodies(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={f"jobs/{JOB}": fixture("job")})
        cancel = router.post(f"{API}/jobs/{JOB}/cancel").mock(
            return_value=httpx.Response(202, json={"state": "cancelling", "already": False})
        )
        feedback = router.post(f"{API}/jobs/{JOB}/feedback").mock(
            return_value=httpx.Response(201, json={})
        )
        cancelled = post(console, f"{BASE}/queue/jobs/{JOB}/cancel", {})
        sent = post(
            console,
            f"{BASE}/queue/jobs/{JOB}/feedback",
            {
                "accepted": "true",
                "quality_score": "0.8",
                "edited": "true",
                "validation_passed": "",
                "notes": "notes that stay out of the trail",
            },
        )
    assert cancelled.status_code == sent.status_code == 303
    assert cancel.called
    assert json.loads(feedback.calls.last.request.content) == {
        "accepted": True,
        "edited": True,
        "quality_score": 0.8,
        "notes": "notes that stay out of the trail",
    }
    (row,) = audit(console, "loadcoach.job_feedback")
    assert "stay out" not in json.dumps(row)
    assert audit(console, "loadcoach.job_cancel")[0]["params"]["state"] == "cancelling"


def test_a_stopped_job_reads_its_rows_events_and_decision(tmp_path: Path) -> None:
    console, database = loadcoach_console(tmp_path, state="inactive")
    fill_rows(
        database,
        "jobs",
        [
            {
                "id": STOPPED_JOB,
                "task_profile_id": "general.chat",
                "state": "completed",
                "class": "normal",
                "response_text": "text read from the database",
                "created_at": "2026-09-10T00:00:00Z",
            }
        ],
    )
    fill_rows(
        database,
        "job_attempts",
        [{"id": "01ATTEMPT", "job_id": STOPPED_JOB, "attempt": 1, "outcome": "completed_recorded"}],
    )
    fill_rows(
        database,
        "job_events",
        [
            {
                "id": "01EVENT",
                "job_id": STOPPED_JOB,
                "sequence": 1,
                "event_type": "job.completed",
                "message": "completed, as the database recorded it",
            }
        ],
    )
    fill_rows(
        database,
        "routing_decisions",
        [
            {
                "id": "01DECISIONFORTHEJOB",
                "job_id": STOPPED_JOB,
                "requested_at": "2026-09-10T00:00:00Z",
                "explanation_json": json.dumps(fixture("decision")),
            }
        ],
    )
    text = page(console, f"{BASE}/queue/jobs/{STOPPED_JOB}")
    assert "text read from the database" in text
    assert "completed_recorded" in text
    assert "completed, as the database recorded it" in text
    assert "insufficient_vram" in text
    assert "data-log-stream" not in text


# --- Evidence -------------------------------------------------------------------------------------


def _evidence_envelope(capability: str) -> dict[str, Any]:
    return {
        "schema": "capability.evidence",
        "schema_version": "1.0",
        "generated_at": "2026-09-10T00:00:00Z",
        "generator": {"name": "loadcoach", "version": "1.5.0"},
        "payload": {
            "model": {"provider_kind": "ollama", "provider_model_name": "qwen3.5:9b-q8_0"},
            "runtime_profile_hash": "8f2c",
            "machine_fingerprint": "jordan-main",
            "capability_id": capability,
            "score": 0.81,
            "confidence": 0.62,
            "sample_count": 40,
            "excluded_count": 2,
            "measured_at": "2026-09-09T00:00:00Z",
        },
    }


def test_evidence_reads_each_match_state_the_summary_and_the_sources(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")

    def by_state(request: httpx.Request) -> httpx.Response:
        body = fixture("evidence")
        state = request.url.params["match_state"]
        body["items"] = [_evidence_envelope(f"capability_{state}")]
        return httpx.Response(200, json=body)

    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"evidence/sources": fixture("evidence-sources")})
        router.get(f"{API}/evidence").mock(side_effect=by_state)
        text = page(console, f"{BASE}/evidence")
        admin = page(console, f"{BASE}/evidence/admin")
    # Row WX9: the records are one page, the store and Import another.
    assert "capability_bound" in text
    assert "capability_ambiguous_name_only" in text
    assert "ollama/qwen3.5:9b-q8_0" in text
    assert 'name="min_confidence"' in text
    assert "not_configured" in admin
    assert 'enctype="multipart/form-data"' in admin
    assert "Pull from FreeWeight at http://127.0.0.1:8765" in admin


def test_the_records_filters_are_loadcoachs_own_query_parameters(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=fixture("evidence"))

    with respx.mock(assert_all_called=False) as router:
        mock_api(router, bodies={"evidence/sources": fixture("evidence-sources")})
        router.get(f"{API}/evidence").mock(side_effect=record)
        page(
            console,
            f"{BASE}/evidence?capability=structured_output&model=ollama%2Fx&min_confidence=0.5",
        )
    params = seen[0].url.params
    assert params["capability"] == "structured_output"
    assert params["model"] == "ollama/x"
    assert params["min_confidence"] == "0.5"


def test_import_uploads_a_bundle_and_renders_loadcoachs_counts(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    bundle = {"schema": "benchmark.evidence_bundle", "schema_version": "1.0", "payload": {}}
    outcome = {
        "source_id": "freeweight@jordan-main",
        "imported": 3,
        "updated": 1,
        "bound": 2,
        "unmatched": 2,
        "ambiguous_name_only": 0,
        "superseded": 0,
        "rejected": [{"index": 4, "reason": "INVALID_RECORD", "detail": "score above 1"}],
    }
    with respx.mock(assert_all_called=False) as router:
        mock_api(
            router,
            bodies={
                "evidence": fixture("evidence"),
                "evidence/sources": fixture("evidence-sources"),
            },
        )
        imported = router.post(f"{API}/evidence/import").mock(
            return_value=httpx.Response(200, json=outcome)
        )
        token = console.csrf_token()
        response = console.client.post(
            f"{BASE}/evidence/import",
            data={"origin": "file", "csrf_token": token},
            files={"file": ("bundle.json", json.dumps(bundle).encode(), "application/json")},
            headers=HTML,
        )
    assert response.status_code == 200
    assert json.loads(imported.calls.last.request.content) == bundle
    assert "3 new" in response.text
    assert "INVALID_RECORD" in response.text
    (row,) = audit(console, "loadcoach.evidence_import")
    assert (row["params"]["origin"], row["params"]["imported"], row["params"]["rejected"]) == (
        "file",
        3,
        1,
    )


def test_the_pull_sends_the_consoles_freeweight_url_and_a_refusal_renders_as_itself(
    tmp_path: Path,
) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    refusal = {"error": {"code": "EVIDENCE_SOURCE_REFUSED", "message": "host is not allowed"}}
    with respx.mock(assert_all_called=False) as router:
        mock_api(
            router,
            bodies={
                "evidence": fixture("evidence"),
                "evidence/sources": fixture("evidence-sources"),
            },
        )
        imported = router.post(f"{API}/evidence/import").mock(
            return_value=httpx.Response(400, json=refusal)
        )
        response = post(console, f"{BASE}/evidence/import", {"origin": "freeweight"})
    assert json.loads(imported.calls.last.request.content) == {"url": "http://127.0.0.1:8765"}
    assert "EVIDENCE_SOURCE_REFUSED" in response.text
    (row,) = audit(console, "loadcoach.evidence_import")
    assert row["outcome"] == "refused"


def test_a_file_that_is_not_json_is_refused_and_nothing_is_sent(tmp_path: Path) -> None:
    console, _database = loadcoach_console(tmp_path, state="active")
    with respx.mock(assert_all_called=False) as router:
        mock_api(
            router,
            bodies={
                "evidence": fixture("evidence"),
                "evidence/sources": fixture("evidence-sources"),
            },
        )
        imported = router.post(f"{API}/evidence/import").mock(
            return_value=httpx.Response(200, json={})
        )
        token = console.csrf_token()
        response = console.client.post(
            f"{BASE}/evidence/import",
            data={"origin": "file", "csrf_token": token},
            files={"file": ("bundle.json", b"not json at all", "application/json")},
            headers=HTML,
        )
    assert "VALIDATION_ERROR" in response.text
    assert not imported.called


def test_stopped_evidence_reads_the_records_and_sources_from_the_database(tmp_path: Path) -> None:
    console, database = loadcoach_console(tmp_path, state="inactive")
    fill_rows(
        database,
        "evidence_sources",
        [{"id": "01SOURCE", "source_key": "freeweight@recorded", "kind": "freeweight_api"}],
    )
    fill_rows(
        database,
        "capability_evidence",
        [
            {
                "id": "01EVIDENCE",
                "canonical_id": "ollama/recorded:latest@sha256:0123",
                "capability_id": "recorded_capability",
                "match_state": "unmatched",
                "stale": 1,
                "source_id": "01SOURCE",
                "identity_confidence": "digest",
            }
        ],
    )
    text = page(console, f"{BASE}/evidence")
    assert "recorded_capability" in text
    assert "freeweight@recorded" in text
    assert "From the database at revision 0015" in text
    assert 'action="/apps/loadcoach/evidence/import"' not in text

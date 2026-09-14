"""weightroom.domain.jobs: the cron parser, catch-up, transitions, recovery and parameters.

The catch-up test is first on purpose (the W9 kickoff: *write the test first*): a daily schedule
that missed three nights while the console was down fires **once** when it comes back, and its
next run is the next future slot — never three queued runs, and never a next run in the past.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from weightroom.domain.jobs import (
    IDEMPOTENT_KINDS,
    JOB_KINDS,
    TERMINAL_STATES,
    CronInvalid,
    JobInvalidState,
    JobParamsInvalid,
    cancel_action,
    cap_output,
    heartbeat_seconds,
    lease_until,
    next_fire,
    parse_cron,
    recovery_action,
    require_transition,
    schedule_tick,
    validate_params,
)

T0 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


# --- Catch-up: once, never N times ---------------------------------------------------------------


def test_a_schedule_missed_during_downtime_fires_once_and_moves_to_the_next_future_slot() -> None:
    nightly = parse_cron("0 2 * * *")
    missed = datetime(2026, 9, 7, 2, 0, tzinfo=UTC)  # three nights before the console came back
    now = datetime(2026, 9, 10, 9, 30, tzinfo=UTC)
    tick = schedule_tick(nightly, next_run_at=missed, now=now)
    assert tick.fire is True
    assert tick.next_run_at == datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    # The next evaluation a second later sees a future slot and fires nothing more.
    again = schedule_tick(nightly, next_run_at=tick.next_run_at, now=now + timedelta(seconds=1))
    assert again.fire is False
    assert again.next_run_at == tick.next_run_at


def test_a_newly_enabled_schedule_waits_for_its_first_slot() -> None:
    tick = schedule_tick(parse_cron("*/15 * * * *"), next_run_at=None, now=T0)
    assert tick.fire is False
    assert tick.next_run_at == datetime(2026, 9, 10, 12, 15, tzinfo=UTC)


def test_a_slot_due_exactly_now_fires_and_the_next_is_strictly_later() -> None:
    tick = schedule_tick(parse_cron("0 12 * * *"), next_run_at=T0, now=T0)
    assert tick.fire is True
    assert tick.next_run_at == datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


# --- The cron parser ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "after", "expected"),
    [
        ("* * * * *", T0, datetime(2026, 9, 10, 12, 1, tzinfo=UTC)),
        ("*/15 * * * *", datetime(2026, 9, 10, 12, 14, 59, tzinfo=UTC), T0.replace(minute=15)),
        ("0 2 * * *", T0, datetime(2026, 9, 11, 2, 0, tzinfo=UTC)),
        ("30 3 * * 0", T0, datetime(2026, 9, 13, 3, 30, tzinfo=UTC)),  # 2026-09-13 is a Sunday
        ("30 3 * * 7", T0, datetime(2026, 9, 13, 3, 30, tzinfo=UTC)),  # 7 is Sunday too
        (
            "0 9 * * mon-fri",
            datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
            datetime(2026, 9, 14, 9, 0, tzinfo=UTC),
        ),
        ("5,35 8-9 * * *", T0, datetime(2026, 9, 11, 8, 5, tzinfo=UTC)),
        ("0 0 1 jan *", T0, datetime(2027, 1, 1, 0, 0, tzinfo=UTC)),
        ("0 0 29 2 *", T0, datetime(2028, 2, 29, 0, 0, tzinfo=UTC)),
        ("10-50/20 * * * *", T0, datetime(2026, 9, 10, 12, 10, tzinfo=UTC)),
        ("0 */6 * * *", T0, datetime(2026, 9, 10, 18, 0, tzinfo=UTC)),
    ],
)
def test_next_fire_goldens(text: str, after: datetime, expected: datetime) -> None:
    assert next_fire(parse_cron(text), after=after) == expected


def test_day_of_month_and_day_of_week_both_restricted_match_either() -> None:
    """Vixie cron's rule: ``0 9 1 * mon`` is the 1st *or* a Monday, not the 1st only on Mondays."""
    expression = parse_cron("0 9 1 * mon")
    assert next_fire(expression, after=T0) == datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
    assert next_fire(expression, after=datetime(2026, 9, 28, 10, 0, tzinfo=UTC)) == datetime(
        2026, 10, 1, 9, 0, tzinfo=UTC
    )


def test_a_non_utc_instant_is_read_in_utc() -> None:
    from zoneinfo import ZoneInfo

    local = datetime(2026, 9, 10, 5, 0, tzinfo=ZoneInfo("America/Los_Angeles"))  # 12:00 UTC
    assert next_fire(parse_cron("0 13 * * *"), after=local) == datetime(
        2026, 9, 10, 13, 0, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * * 13 *",
        "* * * * 8",
        "*/0 * * * *",
        "5-1 * * * *",
        "a * * * *",
        "0 0 31 2 *",  # never fires
        "0 0 31 4,6,9,11 *",  # never fires
    ],
)
def test_invalid_expressions_are_refused_by_name(text: str) -> None:
    with pytest.raises(CronInvalid):
        parse_cron(text)


# --- States, leases, recovery ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("queued", "running"),
        ("queued", "cancelled"),
        ("running", "completed"),
        ("running", "failed"),
        ("running", "cancelled"),
        ("running", "queued"),
    ],
)
def test_every_legal_transition_is_allowed(current: str, target: str) -> None:
    require_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("queued", "completed"),
        ("queued", "failed"),
        ("completed", "queued"),
        ("completed", "running"),
        ("failed", "running"),
        ("cancelled", "queued"),
        ("running", "running"),
    ],
)
def test_every_illegal_transition_is_refused(current: str, target: str) -> None:
    with pytest.raises(JobInvalidState):
        require_transition(current, target)


def test_cancel_is_immediate_when_queued_a_request_when_running_and_refused_when_finished() -> None:
    assert cancel_action("queued") == "cancel"
    assert cancel_action("running") == "request"
    for state in TERMINAL_STATES:
        with pytest.raises(JobInvalidState) as raised:
            cancel_action(state)
        assert raised.value.code == "JOB_INVALID_STATE"


def test_the_heartbeat_is_a_third_of_the_lease_and_a_lease_runs_from_now() -> None:
    assert heartbeat_seconds(60) == 20
    assert lease_until(T0, 60) == T0 + timedelta(seconds=60)


def test_recovery_requeues_idempotent_kinds_fails_the_rest_and_leaves_live_leases_alone() -> None:
    expired = T0 - timedelta(seconds=1)
    live = T0 + timedelta(seconds=1)
    for kind in JOB_KINDS:
        assert recovery_action(kind=kind, lease_expires_at=live, now=T0) is None
        expected = "requeue" if kind in IDEMPOTENT_KINDS else "fail"
        assert recovery_action(kind=kind, lease_expires_at=expired, now=T0) == expected
    assert "freeweight_suite_run" not in IDEMPOTENT_KINDS
    assert "self_restore" not in IDEMPOTENT_KINDS


def test_output_is_capped_to_its_tail_and_says_how_much_went() -> None:
    assert cap_output("short", 100) == "short"
    capped = cap_output("a" * 100 + "the end", 80)
    assert capped.endswith("the end")
    assert "output dropped" in capped
    assert len(capped.encode()) <= 80
    # A multi-byte character cut in half is dropped, never rendered as a replacement glyph.
    assert "�" not in cap_output("é" * 100, 81)


# --- Parameters -----------------------------------------------------------------------------------


def test_parameters_are_filled_with_defaults_and_unknown_keys_refused() -> None:
    assert validate_params("backup", {})["apps"] == [
        "freeweight",
        "loadcoach",
        "ideapress",
        "promptcadence",
        "weightroom",
    ]
    assert validate_params("docs_index", None) == {}
    assert validate_params(
        "freeweight_suite_run", {"model": "ollama/qwen3:8b", "suite": "native.performance"}
    ) == {
        "model": "ollama/qwen3:8b",
        "suite": "native.performance",
        "allow_prompt_override": False,
        "label": None,
        "adapter": None,
        "cooldown_seconds": None,
    }
    assert (
        validate_params(
            "freeweight_suite_run", {"model": "m", "suite": "native.x", "label": " q8 "}
        )["label"]
        == "q8"
    )
    assert (
        validate_params(
            "freeweight_suite_run", {"model": "m", "suite": "native.x", "adapter": " terse "}
        )["adapter"]
        == "terse"
    )
    with pytest.raises(JobParamsInvalid):
        validate_params("docs_index", {"root": "/"})
    with pytest.raises(JobParamsInvalid):
        validate_params("nope", {})


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("freeweight_suite_run", {"suite": "native.performance"}),
        ("freeweight_suite_run", {"model": "m", "suite": "not a suite"}),
        ("freeweight_suite_run", {"model": "m", "suite": "native.x", "allow_prompt_override": 1}),
        # Row WPF2: the adapter reaches a child's argv, so its name is checked against the pattern
        # `model.adapter_manifest` 1.0 states. Whether it *exists* is FreeWeight's answer.
        ("freeweight_suite_run", {"model": "m", "suite": "native.x", "adapter": "Terse"}),
        ("freeweight_suite_run", {"model": "m", "suite": "native.x", "adapter": "--fit"}),
        ("backup", {"apps": []}),
        ("backup", {"apps": ["hermes"]}),
        ("model_refresh", {"apps": ["ideapress"]}),
        ("retention_trim", {"freeweight_older_than_days": 0}),
        ("retention_trim", {"freeweight_older_than_days": True}),
        ("catalog_pull", {"name": "gemma3:1b"}),  # ADR-0146: no longer a kind at all
        ("self_restore", {"file": ""}),
    ],
)
def test_bad_parameters_are_refused(kind: str, params: dict[str, object]) -> None:
    with pytest.raises(JobParamsInvalid):
        validate_params(kind, params)

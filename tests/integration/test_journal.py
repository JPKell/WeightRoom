"""``journalctl`` history and follow, against a fake ``journalctl`` on ``PATH``.

The fake writes the argv it was given and prints ``-o json`` entries in journalctl's own shape,
so the tests assert what was asked for as well as what came back.
"""

from __future__ import annotations

import json
import stat
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from mirrorwall import Event, Subscription

from weightroom.services.journal import (
    JOURNAL_PAGE_CAP,
    MAX_CONCURRENT_FOLLOWS,
    JournalReader,
    JournalUnreadable,
    TooManyFollowers,
    parse_entry,
    priority_for_level,
)
from weightroom.services.processes import UnitUnsupported

HISTORY_FAKE = """#!{python}
import json, os, sys, time
argv = sys.argv[1:]
with open({log!r}, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(argv) + "\\n")
if {fail!r}:
    sys.stderr.write({fail!r})
    sys.exit(1)
count = int(os.environ.get("FAKE_COUNT", "0")) or {count}
after = None
if "--cursor" in argv:
    after = argv[argv.index("--cursor") + 1]
start = 0
if after is not None:
    start = int(after.split("=")[-1])
wanted = int(argv[argv.index("-n") + 1]) if "-n" in argv else 10
follow = "-f" in argv
for offset in range(wanted):
    index = start + offset
    if index >= count:
        break
    entry = {{
        "__CURSOR": "s=abc;i=%d" % index,
        "__REALTIME_TIMESTAMP": str(1789000000000000 - index * 1000000),
        "PRIORITY": "6",
        "MESSAGE": "line %d" % index,
        "_PID": "4242",
        "SYSLOG_IDENTIFIER": "loadcoach",
        "_SYSTEMD_USER_UNIT": "loadcoach.service",
    }}
    sys.stdout.write(json.dumps(entry) + "\\n")
    sys.stdout.flush()
if follow:
    time.sleep({linger})
"""


@pytest.fixture
def host(tmp_path: Path) -> Path:
    (tmp_path / "bin").mkdir()
    return tmp_path


def _install(
    host: Path, *, count: int = 50, fail: str = "", linger: float = 30.0
) -> tuple[JournalReader, Path]:
    log = host / "journalctl.log"
    script = host / "bin" / "journalctl"
    script.write_text(
        HISTORY_FAKE.format(
            python=sys.executable, log=str(log), count=count, fail=fail, linger=linger
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return JournalReader(which={"journalctl": str(script)}.get), log


def _argvs(log: Path) -> list[list[str]]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_history_asks_for_json_the_user_scope_and_the_unit(host: Path) -> None:
    reader, log = _install(host)
    page = reader.history(["loadcoach.service"], limit=5)
    argv = _argvs(log)[0]
    assert argv[:3] == ["--no-pager", "-o", "json"]
    assert "--user" in argv
    assert argv[argv.index("-u") + 1] == "loadcoach.service"
    assert "--reverse" in argv
    assert len(page.lines) == 5
    assert page.lines[0].message == "line 0"
    assert page.lines[0].level == "info"
    assert page.lines[0].app == "loadcoach"


def test_a_page_carries_a_cursor_and_the_next_page_does_not_repeat_its_first_row(
    host: Path,
) -> None:
    reader, log = _install(host, count=12)
    first = reader.history(["loadcoach.service"], limit=5)
    assert first.next_cursor == first.lines[-1].cursor
    second = reader.history(["loadcoach.service"], limit=5, cursor=first.next_cursor)
    # `--cursor` is inclusive, so the reader asks for one extra row and drops the duplicate.
    assert _argvs(log)[1][_argvs(log)[1].index("-n") + 1] == "6"
    assert second.lines[0].cursor != first.lines[-1].cursor
    assert [line.message for line in second.lines] == [f"line {n}" for n in range(5, 10)]


def test_the_last_page_reports_no_cursor(host: Path) -> None:
    reader, _log = _install(host, count=3)
    page = reader.history(["loadcoach.service"], limit=10)
    assert len(page.lines) == 3
    assert page.next_cursor is None
    assert page.as_json()["has_more"] is False


def test_a_request_over_the_cap_is_clamped_and_says_so(host: Path) -> None:
    reader, log = _install(host, count=1)
    page = reader.history(["loadcoach.service"], limit=999_999)
    assert _argvs(log)[0][_argvs(log)[0].index("-n") + 1] == str(JOURNAL_PAGE_CAP)
    assert page.capped is True
    assert page.as_json()["capped_at"] == JOURNAL_PAGE_CAP


def test_filters_become_journalctl_options_and_the_query_is_matched_literally(host: Path) -> None:
    reader, log = _install(host)
    reader.history(
        ["loadcoach.service"], since="-1h", until="now", level="warning", query="a[0]", limit=3
    )
    argv = _argvs(log)[0]
    assert argv[argv.index("--since") + 1] == "-1h"
    assert argv[argv.index("--until") + 1] == "now"
    assert argv[argv.index("--grep") + 1] == r"a\[0\]"
    assert "--case-sensitive=no" in argv
    # The severity filter is applied here, not by journalctl: see `history`'s docstring.
    assert "-p" not in argv
    assert argv[argv.index("-n") + 1] == "30"  # three wanted, over-fetched ten to one


def test_several_units_become_several_u_options(host: Path) -> None:
    reader, log = _install(host)
    reader.history(["loadcoach.service", "freeweight.service", "weightroom.service"], limit=1)
    argv = _argvs(log)[0]
    assert argv.count("-u") == 3


def test_a_system_scope_read_omits_user(host: Path) -> None:
    reader, log = _install(host)
    reader.history(["ollama.service"], scope="system", limit=1)
    assert "--user" not in _argvs(log)[0]


def test_an_unknown_level_is_refused_before_journalctl_runs(host: Path) -> None:
    reader, log = _install(host)
    with pytest.raises(ValueError, match="is not a journal level"):
        reader.history(["loadcoach.service"], level="chatty")
    assert _argvs(log) == []


@pytest.mark.parametrize(
    ("level", "expected"), [("err", 3), ("warning", 4), ("3", 3), (None, None), ("", None)]
)
def test_level_names_and_numbers(level: str | None, expected: int | None) -> None:
    assert priority_for_level(level) == expected


def test_a_journal_the_operator_may_not_read_is_refused_in_journalctls_own_words(
    host: Path,
) -> None:
    reader, _log = _install(
        host, fail="No journal files were opened due to insufficient permissions."
    )
    with pytest.raises(JournalUnreadable) as caught:
        reader.history(["ollama.service"], scope="system")
    assert "insufficient permissions" in caught.value.message
    assert caught.value.details["units"] == ["ollama.service"]


def test_without_journalctl_the_host_is_unsupported_by_name() -> None:
    reader = JournalReader(which=lambda _name: None)
    assert not reader.available()
    with pytest.raises(UnitUnsupported) as caught:
        reader.history(["loadcoach.service"])
    assert caught.value.code == "UNIT_UNSUPPORTED"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"MESSAGE": "hello"}, "hello"),
        ({"MESSAGE": [104, 105]}, "hi"),
        ({"MESSAGE": None}, ""),
        ({}, ""),
    ],
)
def test_a_binary_message_is_rendered_not_dropped(raw: dict[str, Any], expected: str) -> None:
    entry = parse_entry({"__CURSOR": "s=1;i=1", "__REALTIME_TIMESTAMP": "1789000000000000", **raw})
    assert entry is not None
    assert entry.message == expected


def test_an_entry_without_a_cursor_is_not_an_entry() -> None:
    assert parse_entry({"MESSAGE": "orphan"}) is None


def test_follow_streams_lines_into_a_bounded_subscription(host: Path) -> None:
    reader, log = _install(host, count=5, linger=2.0)
    with reader.follow(["loadcoach.service"], backfill=5) as subscription:
        seen: list[Event] = []
        deadline = time.monotonic() + 5.0
        while len(seen) < 5 and time.monotonic() < deadline:
            event = subscription.poll()
            if event is None:
                time.sleep(0.01)
                continue
            seen.append(event)
    argv = _argvs(log)[0]
    assert "-f" in argv
    assert argv[argv.index("-n") + 1] == "5"
    assert [event.payload["message"] for event in seen] == [f"line {n}" for n in range(5)]
    assert [event.type for event in seen] == ["log"] * 5


def test_the_follower_is_stopped_when_the_block_ends(host: Path) -> None:
    reader, _log = _install(host, count=1, linger=60.0)
    started = time.monotonic()
    with reader.follow(["loadcoach.service"], backfill=1):
        pass
    # The child lingers for a minute; leaving the block must not wait for it.
    assert time.monotonic() - started < 5.0


def test_the_reader_ending_publishes_a_closing_event(host: Path) -> None:
    reader, _log = _install(host, count=2, linger=0.0)
    with reader.follow(["loadcoach.service"], backfill=2) as subscription:
        types: list[str] = []
        deadline = time.monotonic() + 5.0
        while "log.closed" not in types and time.monotonic() < deadline:
            event = subscription.poll()
            if event is None:
                time.sleep(0.01)
                continue
            types.append(event.type)
    assert types == ["log", "log", "log.closed"]


def test_a_slow_consumer_loses_the_oldest_lines_and_the_count_says_how_many() -> None:
    """MirrorWall's bounded queue is what the *dropped N lines* frame is built on."""
    subscription = Subscription(maxlen=4)
    for sequence in range(10):
        subscription.publish(
            Event(sequence=sequence, type="log", payload={"message": str(sequence)})
        )
    assert subscription.dropped == 6
    delivered = []
    while (event := subscription.poll()) is not None:
        delivered.append(event.payload["message"])
    assert delivered == ["6", "7", "8", "9"]


def test_too_many_live_streams_are_refused_rather_than_forked(host: Path) -> None:
    reader, _log = _install(host, count=1, linger=30.0)
    import contextlib

    with contextlib.ExitStack() as stack:
        for _ in range(MAX_CONCURRENT_FOLLOWS):
            stack.enter_context(reader.follow(["loadcoach.service"], backfill=0))
        with pytest.raises(TooManyFollowers) as caught:
            stack.enter_context(reader.follow(["loadcoach.service"], backfill=0))
    assert caught.value.details["limit"] == MAX_CONCURRENT_FOLLOWS


def test_a_refused_follow_does_not_consume_a_slot(host: Path) -> None:
    reader, _log = _install(host, count=1, linger=0.5)
    for _ in range(MAX_CONCURRENT_FOLLOWS + 4):
        with reader.follow(["loadcoach.service"], backfill=0):
            pass
    with reader.follow(["loadcoach.service"], backfill=0) as subscription:
        assert subscription is not None


def test_a_suite_json_log_line_is_unwrapped_and_keeps_its_own_severity() -> None:
    """Every application logs JSON to stdout, so the journal files even an ERROR at priority 6."""
    entry = parse_entry(
        {
            "__CURSOR": "s=1;i=1",
            "__REALTIME_TIMESTAMP": "1789000000000000",
            "PRIORITY": "6",
            "_SYSTEMD_USER_UNIT": "loadcoach.service",
            "MESSAGE": json.dumps(
                {
                    "timestamp": "2026-09-10T01:44:28.581Z",
                    "level": "ERROR",
                    "logger": "uvicorn.error",
                    "message": "[Errno 98] address already in use",
                    "loadcoach_version": "1.3.1",
                    "request_id": "01REQ",
                }
            ),
        }
    )
    assert entry is not None
    assert entry.text == "[Errno 98] address already in use"
    assert entry.level == "err"  # the record's own severity, not the transport's
    assert entry.priority == 6  # the journal's, unchanged and still reported
    assert entry.logger == "uvicorn.error"
    assert entry.request_id == "01REQ"
    assert entry.version == "1.3.1"  # lifted from `loadcoach_version`, not a literal "version" key
    body = entry.as_json()
    assert body["message"] == "[Errno 98] address already in use"
    assert body["raw"] is not None and body["raw"].startswith("{")
    assert body["request_id"] == "01REQ"
    assert body["version"] == "1.3.1"


def test_freeweights_own_event_key_is_unwrapped_same_as_everyone_elses_message() -> None:
    """FreeWeight's `JsonFormatter` writes `event`, not `message` (found live, row WX2) — the
    other three loggers' shape must keep working unchanged."""
    entry = parse_entry(
        {
            "__CURSOR": "s=1;i=1",
            "__REALTIME_TIMESTAMP": "1789000000000000",
            "_SYSTEMD_USER_UNIT": "freeweight.service",
            "MESSAGE": json.dumps(
                {
                    "ts": "2026-09-12T23:02:18.969Z",
                    "level": "INFO",
                    "event": '127.0.0.1:1 - "GET /api/v1/version HTTP/1.1" 200',
                    "logger": "uvicorn.access",
                    "app": "freeweight",
                    "version": "1.2.1",
                    "pid": 1820162,
                    "request_id": "01M2BXPZ2RKG4S48ZCVK85B599",
                }
            ),
        }
    )
    assert entry is not None
    assert entry.text == '127.0.0.1:1 - "GET /api/v1/version HTTP/1.1" 200'
    assert entry.logger == "uvicorn.access"
    assert entry.request_id == "01M2BXPZ2RKG4S48ZCVK85B599"
    assert entry.version == "1.2.1"


def test_a_top_level_version_key_wins_over_an_app_prefixed_one() -> None:
    """FreeWeight's formatter writes a plain `version`; a record carrying both is unambiguous."""
    entry = parse_entry(
        {
            "__CURSOR": "s=1;i=1",
            "__REALTIME_TIMESTAMP": "1789000000000000",
            "MESSAGE": json.dumps(
                {"level": "INFO", "logger": "x", "message": "m", "version": "1.2.1"}
            ),
        }
    )
    assert entry is not None
    assert entry.version == "1.2.1"


def test_a_record_with_neither_shape_of_version_reports_none() -> None:
    """IdeaPress and PromptCadence do not (yet) log a version at all — this stays a page."""
    entry = parse_entry(
        {
            "__CURSOR": "s=1;i=1",
            "__REALTIME_TIMESTAMP": "1789000000000000",
            "MESSAGE": json.dumps({"level": "INFO", "logger": "x", "message": "m"}),
        }
    )
    assert entry is not None
    assert entry.version is None
    assert entry.request_id is None


def test_a_line_that_is_not_ours_is_left_exactly_as_the_journal_holds_it() -> None:
    for message in ("Started loadcoach.service.", "{not json", '{"a": 1}', "{}"):
        entry = parse_entry(
            {"__CURSOR": "s=1;i=1", "__REALTIME_TIMESTAMP": "1789000000000000", "MESSAGE": message}
        )
        assert entry is not None
        assert entry.text == message
        assert entry.record_level is None
        assert entry.as_json()["raw"] is None


def test_the_severity_filter_matches_an_applications_own_error(host: Path) -> None:
    """`journalctl -p err` would return none of these; the filter is applied on the true level."""
    reader, log = _install(host, count=0)
    script = host / "bin" / "journalctl"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "for index, level in enumerate(['INFO', 'ERROR', 'INFO', 'WARNING', 'ERROR']):\n"
        "    body = json.dumps({'level': level, 'logger': 'x', 'message': level.lower()})\n"
        "    print(json.dumps({'__CURSOR': 's=a;i=%d' % index,\n"
        "                      '__REALTIME_TIMESTAMP': '1789000000000000',\n"
        "                      'PRIORITY': '6', '_SYSTEMD_USER_UNIT': 'loadcoach.service',\n"
        "                      'MESSAGE': body}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    page = reader.history(["loadcoach.service"], level="err", limit=10)
    assert [line.text for line in page.lines] == ["error", "error"]
    unfiltered = reader.history(["loadcoach.service"], limit=10)
    assert len(unfiltered.lines) == 5

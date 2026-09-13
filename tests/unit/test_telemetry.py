"""weightroom.services.telemetry — the sampler, persistence, downsampling and the wire shapes.

Phase 3's own test list (development plan): a fault-injecting reader proves ``—`` (``None`` on
the wire, never ``0``); the sweep downsamples and retains; the sampler starts, ticks and stops
cleanly with no thread leak.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

from baseaicore import UNSUPPORTED
from sweatmeter import GpuSample, TelemetryCollector
from sweatmeter.testing import (
    FaultInjectingReader,
    HostReading,
    NullGpuReader,
    NullHostReader,
    ScriptedGpuReader,
    ScriptedHostReader,
)
from sweatmeter.types import MemoryReading

from weightroom.infrastructure.db.models import TelemetrySample
from weightroom.services.database import Database, ensure_ready
from weightroom.services.telemetry import (
    TelemetryService,
    build_collector,
    downsample_and_retain,
    format_heartbeat,
    history_rows,
    read_since,
    sample_frame,
    sample_to_json,
    snapshot_to_row,
)

_SAMPLER_THREAD_NAME = "sweatmeter-sampler"


def _sampler_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == _SAMPLER_THREAD_NAME]


def _memory_db(tmp_path_factory) -> Database:  # type: ignore[no-untyped-def]
    path = tmp_path_factory.mktemp("telemetry") / "weightroom.sqlite3"
    database = Database.from_url(f"sqlite:///{path}")
    ensure_ready(database, auto_migrate=True)
    return database


def test_build_collector_never_raises() -> None:
    collector = build_collector()
    snapshot = collector.snapshot()
    assert snapshot.timestamp is not None


class TestSnapshotToRowDegradesHonestly:
    """The fault-injecting reader proves one failing field never becomes a fake ``0``."""

    def test_a_failing_gpu_reader_degrades_only_gpu_fields(self) -> None:
        host = ScriptedHostReader(
            [
                HostReading(
                    cpu_percent=41.5,
                    cpu_temperature_c=52.0,
                    memory=MemoryReading(
                        total_bytes=32 * 1024**3,
                        available_bytes=8 * 1024**3,
                        used_bytes=24 * 1024**3,
                    ),
                )
            ]
        )
        gpu = FaultInjectingReader(NullGpuReader(), fail="sample")
        collector = TelemetryCollector(host=host, gpu=gpu)
        row = snapshot_to_row(collector.snapshot(), interval_ms=1000, resident=None)

        assert row.cpu_percent == 41.5
        assert row.ram_used_bytes == 24 * 1024**3
        assert row.gpu_index is None
        assert row.gpu_utilization_percent is None
        assert row.gpu_vram_used_bytes is None

    def test_a_failing_host_reader_degrades_only_host_fields_gpu_still_reads(self) -> None:
        host = FaultInjectingReader(NullHostReader(), fail="cpu_percent")
        gpu = ScriptedGpuReader(
            [[GpuSample(index=0, utilization_percent=77.0, vram_used_bytes=1024)]]
        )
        collector = TelemetryCollector(host=host, gpu=gpu)
        row = snapshot_to_row(collector.snapshot(), interval_ms=1000, resident=None)

        assert row.cpu_percent is None
        assert row.gpu_index == 0
        assert row.gpu_utilization_percent == 77.0
        assert row.gpu_vram_used_bytes == 1024

    def test_unsupported_never_serializes_as_zero(self) -> None:
        host = ScriptedHostReader([HostReading(cpu_percent=UNSUPPORTED)])
        collector = TelemetryCollector(host=host, gpu=NullGpuReader())
        row = snapshot_to_row(collector.snapshot(), interval_ms=1000, resident=None)
        payload = sample_to_json(row)

        assert row.cpu_percent is None
        assert payload["cpu_percent"] is None
        assert payload["gpus"] == []


def test_sample_to_json_carries_one_gpu_entry_when_present() -> None:
    row = TelemetrySample(
        at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        interval_ms=1000,
        gpu_index=0,
        gpu_utilization_percent=61.0,
        gpu_vram_used_bytes=11_000_000_000,
        gpu_vram_total_bytes=16_000_000_000,
        resident_json=[{"name": "llama3"}],
    )
    payload = sample_to_json(row)

    assert payload["gpus"] == [
        {
            "index": 0,
            "utilization_percent": 61.0,
            "temperature_c": None,
            "power_watts": None,
            "vram_used_bytes": 11_000_000_000,
            "vram_total_bytes": 16_000_000_000,
        }
    ]
    assert payload["resident"] == [{"name": "llama3"}]


def test_sample_frame_carries_the_row_id_as_the_sse_sequence() -> None:
    row = TelemetrySample(id=42, at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC), interval_ms=1000)
    frame = sample_frame(row, queue={"active": 2})

    assert frame.startswith("id: 42\nevent: telemetry.sampled\n")
    assert '"active":2' in frame.replace(" ", "")


def test_format_heartbeat_is_an_sse_comment() -> None:
    assert format_heartbeat().startswith(": heartbeat ")


class TestDownsampleAndRetain:
    def test_rows_within_the_last_hour_are_untouched(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
        with database.write() as session:
            for minute in range(5):
                session.add(TelemetrySample(at=now - timedelta(minutes=minute), interval_ms=1000))
        deleted = downsample_and_retain(database, history_hours=72, now=now)
        with database.read() as session:
            from sqlalchemy import func, select

            count = session.execute(select(func.count()).select_from(TelemetrySample)).scalar_one()
        assert deleted == 0
        assert count == 5

    def test_rows_older_than_an_hour_are_reduced_to_one_per_minute(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
        aging_minute = now - timedelta(hours=2)
        with database.write() as session:
            for second in range(0, 60, 5):  # twelve rows in one aging minute
                session.add(
                    TelemetrySample(at=aging_minute + timedelta(seconds=second), interval_ms=1000)
                )
        deleted = downsample_and_retain(database, history_hours=72, now=now)
        with database.read() as session:
            from sqlalchemy import select

            remaining = session.execute(select(TelemetrySample)).scalars().all()
        assert deleted == 11
        assert len(remaining) == 1
        assert remaining[0].at == aging_minute + timedelta(seconds=55)  # the newest in the minute

    def test_rows_past_history_hours_are_dropped_outright(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
        with database.write() as session:
            session.add(TelemetrySample(at=now - timedelta(hours=100), interval_ms=1000))
            session.add(TelemetrySample(at=now - timedelta(minutes=1), interval_ms=1000))
        deleted = downsample_and_retain(database, history_hours=72, now=now)
        with database.read() as session:
            from sqlalchemy import select

            remaining = session.execute(select(TelemetrySample)).scalars().all()
        assert deleted == 1
        assert len(remaining) == 1


class TestReadSinceAndHistory:
    def test_read_since_is_strictly_after_and_ascending(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
        with database.write() as session:
            for i in range(3):
                session.add(TelemetrySample(at=now + timedelta(seconds=i), interval_ms=1000))
        first_batch = read_since(database, after_id=0)
        assert [row.id for row in first_batch] == [1, 2, 3]
        assert read_since(database, after_id=3) == []

    def test_history_rows_project_one_figure_over_the_window(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
        with database.write() as session:
            session.add(TelemetrySample(at=now, interval_ms=1000, gpu_utilization_percent=61.0))
            session.add(
                TelemetrySample(
                    at=now - timedelta(hours=48), interval_ms=1000, gpu_utilization_percent=10.0
                )
            )
        rows = history_rows(database, figure="gpu_utilization_percent", hours=24, now=now)
        assert len(rows) == 1
        assert rows[0][1] == 61.0

    def test_history_rows_refuses_an_unknown_figure(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        try:
            history_rows(
                database, figure="not_a_figure", hours=24, now=datetime(2026, 9, 9, tzinfo=UTC)
            )
        except ValueError as exc:
            assert "not_a_figure" in str(exc)
        else:
            raise AssertionError("expected a ValueError")


class TestTelemetryServiceLifecycle:
    """Mirrors FreeWeight's own ``TelemetryService`` lifecycle tests (this package's design)."""

    def _service(self, database: Database) -> TelemetryService:
        from weightroom.config import load_settings

        settings = load_settings(config_path=None).settings
        settings.telemetry.interval_ms = 10
        collector = TelemetryCollector(host=NullHostReader(), gpu=NullGpuReader())
        return TelemetryService(database, settings, collector=collector)

    def test_latest_is_none_before_start(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        service = self._service(database)
        assert service.latest() is None

    def test_start_ticks_and_persists_then_stop_leaves_no_thread(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        service = self._service(database)
        service.start()
        deadline = time.monotonic() + 2.0
        while service.latest() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert service.latest() is not None
        # Give the writer a moment to catch up with the sampler tick that set `latest()`.
        deadline = time.monotonic() + 2.0
        rows: list[TelemetrySample] = []
        while not rows and time.monotonic() < deadline:
            rows = read_since(database, after_id=0)
            time.sleep(0.01)
        assert rows

        service.stop()

        assert _sampler_threads() == []

    def test_repeated_start_stop_cycles_leave_no_thread_leak(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        service = self._service(database)
        for _ in range(3):
            service.start()
            service.stop()
        assert _sampler_threads() == []

    def test_queue_snapshot_is_none_with_no_app_client(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        database = _memory_db(tmp_path_factory)
        service = self._service(database)
        assert service.queue_snapshot() is None

    def test_peeking_at_the_queue_does_not_count_as_reading(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        """A page render peeks; only a stream reads. A page whose strip is hidden opens no stream,
        so however often it is rendered, the sampler asks LoadCoach nothing."""
        from weightroom.config import load_settings

        database = _memory_db(tmp_path_factory)
        settings = load_settings(config_path=None).settings
        collector = TelemetryCollector(host=NullHostReader(), gpu=NullGpuReader())
        now = [1000.0]
        reads: list[float] = []
        service = TelemetryService(database, settings, collector=collector, clock=lambda: now[0])

        def fake_read() -> dict[str, int]:
            reads.append(now[0])
            return {"active": 0}

        service._read_queue = fake_read  # type: ignore[method-assign]  # stand-in for the HTTP read
        for _ in range(20):
            now[0] += 1
            assert service.peek_queue() is None
            service._on_sample(collector.snapshot())
        assert reads == []

        service.queue_snapshot()  # a stream frame: now it is read
        service._on_sample(collector.snapshot())
        assert reads == [now[0]]

    def test_upstream_reads_follow_readers_and_are_capped(self, tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
        """Upstream calls scale with time while someone reads, never with readers, and stop when
        nobody does.

        Every open telemetry stream used to read LoadCoach's queue on each pass of its poll loop,
        five a second per stream, until LoadCoach's rate limiter answered 429; after that the
        sampler still read it on every tick with no tab open at all.
        """
        import httpx
        import respx

        from weightroom.config import load_settings
        from weightroom.services.telemetry import QUEUE_REFRESH_SECONDS, READER_IDLE_SECONDS

        database = _memory_db(tmp_path_factory)
        settings = load_settings(config_path=None).settings
        base_url = settings.apps.loadcoach.base_url.rstrip("/")
        collector = TelemetryCollector(host=NullHostReader(), gpu=NullGpuReader())
        now = [1000.0]
        status = {"active": 2, "depth_by_state": {"queued": 1}}

        def tick(*, reader: bool) -> None:
            now[0] += 1
            if reader:
                service.queue_snapshot()
            service._on_sample(collector.snapshot())

        with respx.mock(assert_all_called=True) as router:
            route = router.get(f"{base_url}/api/v1/system/status").mock(
                return_value=httpx.Response(200, json=status)
            )
            with httpx.Client() as client:
                service = TelemetryService(
                    database, settings, collector=collector, app_client=client, clock=lambda: now[0]
                )
                for _ in range(5):  # nobody reading: the host is sampled, LoadCoach is not asked
                    tick(reader=False)
                assert route.call_count == 0

                tick(reader=True)  # a reader arrives: one read on the next tick ...
                assert route.call_count == 1
                for _ in range(50):  # ... shared by every reader
                    assert service.queue_snapshot() == status

                for _ in range(int(QUEUE_REFRESH_SECONDS) - 1):  # still reading: capped per window
                    tick(reader=True)
                assert route.call_count == 1
                tick(reader=True)
                assert route.call_count == 2

                now[0] += READER_IDLE_SECONDS  # the reader leaves
                for _ in range(10):
                    tick(reader=False)
                assert route.call_count == 2
                assert service.queue_snapshot() is None

"""The telemetry page's figures (row WY4): the formatter, the scale table, the chart option.

The formatter has two implementations — :func:`format_figure` for the server's first paint and
MirrorWall ``charts.js``'s ``format`` for the live bars and the chart axes — so one case table
runs through both, and a difference between them is a failure here rather than a figure that
changes its text the second the stream's first frame arrives.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from mirrorwall import PACKAGE_STATIC_DIR

from weightroom.infrastructure.db.models import TelemetrySample
from weightroom.services.database import Database, ensure_ready
from weightroom.services.telemetry import (
    FIGURE_COLUMNS,
    FIGURE_SCALES,
    format_figure,
    telemetry_panels,
)

NODE = shutil.which("node") or shutil.which("nodejs")
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)

FORMAT_CASES: list[tuple[float | None, str, str]] = [
    (None, "bytes", "—"),
    (None, "percent", "—"),
    (0, "bytes", "0 B"),
    (1023, "bytes", "1023 B"),
    (1024, "bytes", "1 K"),
    (1536, "bytes", "1.5 K"),
    (104_815_656, "bytes", "100 M"),  # 99.96 M rounds up into three digits, no decimal
    (1_048_576 * 1023.96, "bytes", "1 G"),  # 1023.96 M rounds to 1024, which is the next suffix
    (19_541_000_000, "bytes", "18.2 G"),
    (68_719_476_736, "bytes", "64 G"),
    (2 * 1024**5, "bytes", "2048 T"),  # T is the last suffix
    (999, "count", "999"),
    (1500, "count", "1.5 K"),
    (2_500_000, "count", "2.5 M"),
    (0.25, "count", "0.3"),  # a tie rounds up in both languages (Python's round() would say 0.2)
    (42.5, "percent", "43%"),
    (0.4, "percent", "0%"),
    (100, "percent", "100%"),
    (67.49, "celsius", "67 °C"),
    (212.6, "watts", "213 W"),
]


@pytest.mark.parametrize(("value", "unit", "text"), FORMAT_CASES)
def test_format_figure(value: float | None, unit: str, text: str) -> None:
    assert format_figure(value, unit) == text


@pytest.mark.skipif(NODE is None, reason="no JavaScript runtime on this machine")
def test_the_javascript_formatter_prints_the_same_table() -> None:
    assert NODE is not None
    source = (PACKAGE_STATIC_DIR / "js" / "charts.js").read_text(encoding="utf-8")
    script = (
        f"{source}\nconst cases = {json.dumps(FORMAT_CASES)};\n"
        "const format = globalThis.mirrorwallCharts.format;\n"
        "console.log(JSON.stringify(cases.map((c) => format(c[0], c[1]))));"
    )
    completed = subprocess.run(  # noqa: S603 — fixed argv, script on the command line
        [NODE, "-e", script], capture_output=True, text=True, check=False, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [text for _value, _unit, text in FORMAT_CASES]


def test_every_measured_figure_is_charted_or_printed_as_a_total() -> None:
    totals = {scale.total for scale in FIGURE_SCALES.values() if scale.total is not None}
    assert set(FIGURE_SCALES) | totals == set(FIGURE_COLUMNS)
    assert not totals & set(FIGURE_SCALES), "a total is a value, never its own chart"


def test_the_scale_table() -> None:
    for name, scale in FIGURE_SCALES.items():
        assert scale.unit in {"percent", "celsius", "watts", "bytes"}, name
        if scale.unit == "percent":
            assert (scale.low, scale.high) == (0.0, 100.0), name
        if scale.unit == "celsius":
            assert scale.high is not None and scale.low < scale.high, name
        if scale.unit == "bytes":
            assert scale.high is None and scale.total is not None, name
        if scale.unit == "watts":
            assert (scale.low, scale.high, scale.total) == (0.0, None, None), name


def _database(tmp_path: Path) -> Database:
    database = Database.from_url(f"sqlite:///{tmp_path / 'wr.sqlite3'}")
    ensure_ready(database, auto_migrate=True)
    return database


def _colour_keys(value: object, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if "color" in key.lower() or "colour" in key.lower():
                found.append(f"{path}.{key}")
            found.extend(_colour_keys(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_colour_keys(item, f"{path}[{index}]"))
    elif isinstance(value, str) and (value.startswith("#") or value.startswith("rgb")):
        found.append(f"{path}={value}")
    return found


def test_panels_scale_print_and_carry_no_colour(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with database.write() as session:
        for seconds, used in ((-120, 8 * 1024**3), (-60, 18 * 1024**3)):
            session.add(
                TelemetrySample(
                    at=NOW + timedelta(seconds=seconds),
                    interval_ms=1000,
                    cpu_percent=40.0,
                    ram_used_bytes=used,
                    ram_total_bytes=64 * 1024**3,
                    gpu_index=0,
                    gpu_power_watts=200.0 if seconds == -120 else 100.0,
                )
            )
    panels = {panel.name: panel for panel in telemetry_panels(database, hours=1, now=NOW)}
    assert list(panels) == list(FIGURE_SCALES)

    ram = panels["ram_used_bytes"]
    assert (ram.text, ram.total_text) == ("18 G", "64 G")
    assert ram.high == 64 * 1024**3
    assert ram.percent == 28.1
    assert ram.aria_label == "RAM: now 18 G, minimum 8 G, maximum 18 G"
    assert ram.option is not None
    assert ram.option["mw_unit"] == "bytes"
    assert ram.option["visualMap"]["mw_scale"] == "load"
    assert (ram.option["yAxis"]["min"], ram.option["yAxis"]["max"]) == (0.0, 64 * 1024**3)
    assert ram.option["series"][0]["areaStyle"] == {"opacity": 0.35}

    power = panels["gpu_power_watts"]
    assert power.high == 200.0, "watts run to the highest sample in the window"
    assert power.percent == 50.0

    for panel in panels.values():
        assert _colour_keys(panel.option) == [], panel.name


def test_a_figure_this_machine_cannot_measure_prints_a_dash_and_draws_nothing(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with database.write() as session:
        session.add(TelemetrySample(at=NOW, interval_ms=1000, cpu_percent=5.0))
    panels = {panel.name: panel for panel in telemetry_panels(database, hours=1, now=NOW)}
    vram = panels["gpu_vram_used_bytes"]
    assert (vram.text, vram.total_text, vram.option, vram.percent) == ("—", "—", None, None)
    assert vram.aria_label == "VRAM: not measured"
    assert (panels["gpu_temperature_c"].text, panels["gpu_temperature_c"].total_text) == ("—", None)
    assert panels["cpu_percent"].option is not None


def test_a_long_window_is_bucketed_keeping_each_buckets_peak_and_its_gaps(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    with database.write() as session:
        for index in range(100):
            session.add(
                TelemetrySample(
                    at=NOW - timedelta(seconds=100 - index),
                    interval_ms=1000,
                    cpu_percent=None if index >= 90 else (99.0 if index == 7 else 1.0),
                )
            )
    (cpu,) = [
        p
        for p in telemetry_panels(database, hours=1, now=NOW, max_points=10)
        if p.name == "cpu_percent"
    ]
    assert cpu.option is not None
    data = cpu.option["series"][0]["data"]
    assert len(data) == 10
    assert max(value for _at, value in data if value is not None) == 99.0
    assert data[-1][1] is None, "a bucket of unavailable readings is a gap, not a zero"
    assert cpu.text == "—"

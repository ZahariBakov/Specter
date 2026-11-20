from __future__ import annotations

from specter.core.models import Reading
from specter.ui.panel import tile_sort_key
from specter.ui.widgets import (
    PRIMARY,
    SECONDARY,
    format_rate,
    format_secondary,
    pick_primary,
    slim_parts,
)


def test_format_rate():
    assert format_rate(0.0) == "0 KB/s"
    assert format_rate(0.5) == "512 KB/s"
    assert format_rate(12.44) == "12.4 MB/s"
    assert format_rate(340.2) == "340 MB/s"


def test_percent_wins_over_maximum():
    mem = Reading("gpu.mem", "GPU", 0.9, "GB", 3.8)
    load = Reading("gpu.load", "GPU", 12, "%", 100.0)
    temp = Reading("gpu.temp", "GPU", 59, "°C")
    assert pick_primary([mem, temp, load]) is load
    assert pick_primary([temp, mem]) is mem
    assert pick_primary([temp]) is None


def test_secondary_shows_used_of_total():
    assert format_secondary(Reading("gpu.mem", "GPU", 0.87, "GB", 3.81)) == "0.9/3.8GB"
    assert format_secondary(Reading("gpu.temp", "GPU", 59, "°C")) == "59°C"


def test_tile_order():
    groups = ["fan", "net", "ram", "gpu1", "zzz", "gpu0", "disk", "cpu"]
    assert sorted(groups, key=tile_sort_key) == [
        "cpu", "gpu0", "gpu1", "ram", "disk", "net", "fan", "zzz"
    ]


def test_slim_parts_primary_then_others():
    load = Reading("cpu.load", "CPU", 8, "%", 100.0)
    temp = Reading("cpu.temp", "CPU", 35, "°C")
    assert slim_parts([temp, load]) == [("8%", PRIMARY), ("35°C", SECONDARY)]


def test_slim_parts_rates_keep_their_marks():
    down = Reading("net.down", "Net", 0.011, "MB/s", short="↓")
    up = Reading("net.up", "Net", 2.0, "MB/s", short="↑")
    fan = Reading("fan.rpm", "Fan", 2683, "RPM")
    assert slim_parts([down, up]) == [("↓ 11 KB/s", PRIMARY), ("↑ 2.0 MB/s", PRIMARY)]
    assert slim_parts([fan]) == [("2683 rpm", PRIMARY)]

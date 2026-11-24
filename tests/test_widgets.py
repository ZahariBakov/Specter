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


def test_temperature_colours():
    from specter.ui.widgets import GREEN, RED, TEMP_HOT, TEMP_WARN, YELLOW, reading_colour, temp_colour

    assert temp_colour(TEMP_WARN - 1, GREEN) == GREEN
    assert temp_colour(TEMP_WARN, GREEN) == YELLOW
    assert temp_colour(TEMP_HOT - 1, GREEN) == YELLOW
    assert temp_colour(TEMP_HOT, GREEN) == RED
    assert reading_colour(Reading("cpu.temp", "CPU", 90, "°C"), "x") == RED
    assert reading_colour(Reading("cpu.load", "CPU", 99, "%", 100.0), "x") == "x"  # only °C warns


def test_slim_items_keep_the_reading():
    from specter.ui.widgets import slim_items

    load = Reading("cpu.load", "CPU", 8, "%", 100.0)
    temp = Reading("cpu.temp", "CPU", 35, "°C")
    assert [(t, k, r) for t, k, r in slim_items([temp, load])] == [
        ("8%", PRIMARY, load),
        ("35°C", SECONDARY, temp),
    ]


def test_sparkline_points_grow_from_the_right():
    from specter.ui.widgets import HISTORY, sparkline_points

    assert sparkline_points([0.5], 100, 20) == []  # one value is no line
    points = sparkline_points([0.0, 1.0], 100, 20)
    assert points[2] == 99  # newest at the right edge
    assert points[0] == 99 - 99 / (HISTORY - 1)  # one slot to the left, not stretched
    assert points[3] < points[1]  # a higher value is higher up (smaller y)
    assert all(0 <= y <= 20 for y in points[1::2])


def test_sparkline_keeps_only_the_last_values_and_clamps():
    from specter.ui.widgets import HISTORY, sparkline_points

    points = sparkline_points([0.1] * 200 + [5.0], 120, 30)
    assert len(points) == 2 * HISTORY
    assert points[0] == 0.0 and points[-2] == 119
    assert points[-1] == sparkline_points([0.0, 1.0], 120, 30)[3]  # 5.0 is clamped to 1.0


def test_cursor_names_per_platform():
    from specter.ui.panel import move_cursor, resize_cursor

    assert resize_cursor((1, 1), "linux") == "bottom_right_corner"
    assert resize_cursor((1, 1), "win32") == "size_nw_se"
    assert resize_cursor((-1, 1), "win32") == "size_ne_sw"
    assert resize_cursor((0, -1), "win32") == "size_ns"
    assert resize_cursor((0, 0), "win32") == "" and resize_cursor((0, 0), "linux") == ""
    assert (move_cursor("linux"), move_cursor("win32")) == ("fleur", "size")


def test_every_edge_has_a_cursor_on_both_platforms():
    from specter.ui.panel import _RESIZE_CURSORS, _WINDOWS_RESIZE_CURSORS

    assert set(_RESIZE_CURSORS) == set(_WINDOWS_RESIZE_CURSORS)


def test_primary_shows_its_mark_before_the_number():
    from specter.ui.widgets import format_primary, slim_items

    freq = Reading("gpu.freq", "GPU", 45, "%", 100.0, short="~")
    temp = Reading("gpu.temp", "GPU", 50, "°C")
    assert format_primary(freq) == "~45%"
    assert format_primary(Reading("gpu.load", "GPU", 45, "%", 100.0)) == "45%"
    assert slim_items([temp, freq])[0] == ("~45%", PRIMARY, freq)


def test_secondary_order_is_stable():
    import random

    from specter.ui.widgets import secondary_sort_key, slim_parts

    mem = Reading("gpu.mem", "GPU", 0.9, "GB", 3.8)
    temp = Reading("gpu.temp", "GPU", 59, "°C")
    fan = Reading("gpu.fan", "GPU", 1500, "RPM")
    other = Reading("gpu.power", "GPU", 30, "W")
    load = Reading("gpu.load", "GPU", 12, "%", 100.0)
    expected = [mem, temp, fan, other]
    shuffled = expected[:]
    for seed in range(5):
        random.Random(seed).shuffle(shuffled)
        assert sorted(shuffled, key=secondary_sort_key) == expected
        assert [t for t, _k in slim_parts(shuffled + [load])] == [
            "12%", "0.9GB", "59°C", "1500 rpm", "30.0W"
        ]


def test_fan_percent_is_labelled():
    from specter.ui.widgets import secondary_sort_key, slim_parts

    fanpct = Reading("gpu.fanpct", "GPU", 42, "%", 100.0)
    temp = Reading("gpu.temp", "GPU", 59, "°C")
    load = Reading("gpu.load", "GPU", 12, "%", 100.0)
    assert format_secondary(fanpct) == "fan 42%"
    assert secondary_sort_key(temp) < secondary_sort_key(fanpct)
    assert slim_parts([fanpct, temp, load]) == [
        ("12%", PRIMARY), ("59°C", SECONDARY), ("fan 42%", SECONDARY)
    ]
    assert slim_parts([fanpct, temp])[0] == ("42%", PRIMARY)  # alone it is the big number

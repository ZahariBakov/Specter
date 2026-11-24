"""Small building blocks for the panel."""

from __future__ import annotations

import tkinter as tk
from collections import deque
from typing import Deque, List, Optional, Tuple

from specter.core.models import Reading

# Colours
BG = "#101215"
BORDER = "#262a31"
LABEL_FG = "#8a93a0"
VALUE_FG = "#f2f4f7"
SUB_FG = "#9aa4b2"
SEG_OFF = "#252930"
GREEN = "#3ddc84"
YELLOW = "#f5c542"
RED = "#ff5b5b"

SEGMENTS = 8
HISTORY = 60  # values kept for the sparkline
SPARK_HEIGHT = 22  # px
SPARK_PAD = 4  # px above the sparkline
SPARK_EXTRA = SPARK_HEIGHT + SPARK_PAD  # how much taller a tile gets with its sparkline
TEMP_WARN = 70  # °C: yellow from here
TEMP_HOT = 85  # °C: red from here


def level_colour(fraction: float) -> str:
    if fraction >= 0.85:
        return RED
    if fraction >= 0.60:
        return YELLOW
    return GREEN


def temp_colour(celsius: float, default: str) -> str:
    """`default` while cool, yellow from TEMP_WARN, red from TEMP_HOT."""
    if celsius >= TEMP_HOT:
        return RED
    if celsius >= TEMP_WARN:
        return YELLOW
    return default


def reading_colour(reading: Reading, default: str) -> str:
    """Text colour for a value: temperatures warn, everything else keeps `default`."""
    return temp_colour(reading.value, default) if reading.unit == "°C" else default


def format_value(reading: Reading) -> str:
    if reading.unit == "%":
        return f"{reading.value:.0f}%"
    if reading.unit == "°C":
        return f"{reading.value:.0f}°C"
    if reading.unit == "RPM":
        return f"{reading.value:.0f} rpm"
    if reading.unit == "MB/s":
        return format_rate(reading.value)
    return f"{reading.value:.1f}{reading.unit}"


def format_rate(mb_per_s: float) -> str:
    """12.4 MB/s, 340 MB/s, or 512 KB/s below 1 MB/s."""
    if mb_per_s < 1:
        return f"{mb_per_s * 1024:.0f} KB/s"
    if mb_per_s < 100:
        return f"{mb_per_s:.1f} MB/s"
    return f"{mb_per_s:.0f} MB/s"


def is_fan_percent(reading: Reading) -> bool:
    """A fan speed given in % (key ending ".fanpct"), not a load."""
    return reading.key.endswith(".fanpct")


def format_primary(reading: Reading) -> str:
    """The big number, with the reading's mark in front: "45%", "~45%" (approximate)."""
    return f"{reading.short}{format_value(reading)}" if reading.short else format_value(reading)


def secondary_sort_key(reading: Reading) -> Tuple[int, str]:
    """Order of the small values: memory-like (has a maximum, not %), °C, fan, the rest."""
    if reading.maximum is not None and reading.unit != "%":
        group = 0
    elif reading.unit == "°C":
        group = 1
    elif reading.unit == "RPM" or is_fan_percent(reading):
        group = 2
    else:
        group = 3
    return group, reading.key


def format_secondary(reading: Reading) -> str:
    """Value for the small line under the big number: "0.9/3.8GB", "59°C", "fan 42%"."""
    if is_fan_percent(reading):
        return f"fan {format_value(reading)}"
    if reading.maximum is not None and reading.unit != "%":
        return f"{reading.value:.1f}/{reading.maximum:.1f}{reading.unit}"
    return format_value(reading)


def pick_primary(readings: list[Reading]) -> Optional[Reading]:
    """The reading that gets the big number and the bar: a % first, then one with a maximum.

    None means the tile has no bar (fan speed, disk and network rates).
    """
    for reading in readings:
        if reading.unit == "%" and not is_fan_percent(reading):
            return reading
    for reading in readings:
        if reading.maximum is not None and not is_fan_percent(reading):
            return reading
    for reading in readings:  # fan % only when there is nothing else
        if is_fan_percent(reading):
            return reading
    return None


def reading_fraction(reading: Reading) -> float:
    """How full a reading is (0..1): % / 100 or value / maximum. 0 if neither."""
    if reading.unit == "%":
        return reading.value / 100
    if reading.maximum:
        return reading.value / reading.maximum
    return 0.0


def sparkline_points(values: List[float], width: int, height: int) -> List[float]:
    """Flat [x0, y0, x1, y1, ...] for a line through `values` (each 0..1, newest last).

    The newest value sits at the right edge and the line grows from there, one slot per
    sample out of HISTORY, so the graph doesn't stretch while it is filling up.
    Fewer than two values: nothing to draw.
    """
    if len(values) < 2 or width <= 1 or height <= 1:
        return []
    step = (width - 1) / (HISTORY - 1)
    top, bottom = 2, height - 3  # keep the 2 px line inside the canvas
    points: List[float] = []
    for i, value in enumerate(values[-HISTORY:]):
        age = min(len(values), HISTORY) - 1 - i
        value = min(1.0, max(0.0, value))
        points += [(width - 1) - age * step, bottom - value * (bottom - top)]
    return points


# Kinds of text in a slim tile.
PRIMARY, SECONDARY = "primary", "secondary"


def slim_items(readings: list[Reading]) -> List[Tuple[str, str, Reading]]:
    """Texts for a one-line tile, as (text, kind, reading it comes from)."""
    primary = pick_primary(readings)
    if primary is None:
        return [(f"{r.short} {format_value(r)}".strip(), PRIMARY, r) for r in readings]
    others = sorted((r for r in readings if r is not primary), key=secondary_sort_key)
    texts = [
        (f"fan {format_value(r)}" if is_fan_percent(r) else format_value(r), SECONDARY, r)
        for r in others
    ]
    return [(format_primary(primary), PRIMARY, primary)] + texts


def slim_parts(readings: list[Reading]) -> List[Tuple[str, str]]:
    """Texts for a one-line tile, as (text, kind).

    CPU: [("8%", PRIMARY), ("35°C", SECONDARY)]. A device without a primary (fan,
    disk, net) shows every value as primary, with its mark: [("↓ 11 KB/s", PRIMARY), ...].
    """
    return [(text, kind) for text, kind, _reading in slim_items(readings)]


class SegmentBar(tk.Canvas):
    """A bar made of small blocks: ▮▮▮▯▯▯▯▯"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, width="22m", height="1.4m", bg=BG, highlightthickness=0, bd=0)
        self._fraction = 0.0
        self.bind("<Configure>", lambda _e: self._draw())

    def set_fraction(self, fraction: float) -> None:
        self._fraction = min(1.0, max(0.0, fraction))
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1:
            return
        gap = max(2, width // 60)
        seg_w = (width - gap * (SEGMENTS - 1)) / SEGMENTS
        lit = round(self._fraction * SEGMENTS)
        if self._fraction > 0 and lit == 0:
            lit = 1  # show that something is happening
        colour = level_colour(self._fraction)
        for i in range(SEGMENTS):
            x0 = i * (seg_w + gap)
            self.create_rectangle(
                x0, 0, x0 + seg_w, height, width=0, fill=colour if i < lit else SEG_OFF
            )


class Sparkline(tk.Canvas):
    """A thin line of the recent values, coloured like the bar."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(
            master, width="22m", height=SPARK_HEIGHT, bg=BG, highlightthickness=0, bd=0
        )
        self._values: Deque[float] = deque(maxlen=HISTORY)
        self.bind("<Configure>", lambda _e: self._draw())

    def add(self, fraction: float) -> None:
        self._values.append(fraction)
        if self.winfo_ismapped():
            self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        self.create_line(0, height - 1, width, height - 1, fill=SEG_OFF)  # baseline
        points = sparkline_points(list(self._values), width, height)
        if points:
            self.create_line(*points, fill=level_colour(self._values[-1]), width=2)


class MetricTile(tk.Frame):
    """One device (CPU, RAM, GPU...): label, big value, segment bar, small sub line."""

    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master, bg=BG)
        self._title = tk.Label(
            self, text=title.upper(), bg=BG, fg=LABEL_FG, font=("TkDefaultFont", 8, "bold")
        )
        self._value = tk.Label(self, text="—", bg=BG, fg=VALUE_FG, font=("TkDefaultFont", 17, "bold"))
        self._bar = SegmentBar(self)
        self._spark = Sparkline(self)  # only packed while sparklines are on; keeps its history
        self._sub = tk.Frame(self, bg=BG)  # one label per value, so a temperature can warn
        self._sub_labels: list[tk.Label] = []

        self._title.pack(anchor="w")
        self._value.pack(anchor="w", pady=(0, 3))
        self._bar.pack(anchor="w")
        self._sub.pack(anchor="w", pady=(3, 0))

    spark_on = False  # is the sparkline showing?

    def set_sparkline(self, on: bool) -> None:
        self.spark_on = on
        if on:
            self._spark.pack(anchor="w", pady=(SPARK_PAD, 0), before=self._sub)
        else:
            self._spark.pack_forget()

    def update_readings(self, readings: list[Reading]) -> None:
        primary = pick_primary(readings) or readings[0]
        others = sorted((r for r in readings if r is not primary), key=secondary_sort_key)

        self._value.config(text=format_primary(primary))

        fraction = reading_fraction(primary)
        self._bar.set_fraction(fraction)
        self._spark.add(fraction)
        self._value.config(fg=level_colour(fraction) if fraction >= 0.6 else VALUE_FG)

        sub_parts = [(format_secondary(r), reading_colour(r, SUB_FG)) for r in others]
        if primary.maximum is not None and primary.unit != "%":
            sub_parts.insert(0, (f"of {primary.maximum:.1f}{primary.unit}", SUB_FG))
        sub_parts = sub_parts or [(" ", SUB_FG)]  # keep the line's height
        while len(self._sub_labels) < len(sub_parts):
            label = tk.Label(self._sub, bg=BG, padx=0, font=("TkFixedFont", 8))
            label.pack(side="left")
            self._sub_labels.append(label)
        for i, label in enumerate(self._sub_labels):
            if i < len(sub_parts):
                text, colour = sub_parts[i]
                gap = "  " if i < len(sub_parts) - 1 else ""
                label.config(text=text + gap, fg=colour)
                label.pack(side="left")
            else:
                label.pack_forget()


class RateTile(tk.Frame):
    """A device without a bar (fan, disk, network): label and one row per value.

    One value is shown big ("2667 rpm"); two or more as rows ("↓ 1.2 MB/s" / "↑ 80 KB/s").
    """

    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master, bg=BG)
        tk.Label(
            self, text=title.upper(), bg=BG, fg=LABEL_FG, font=("TkDefaultFont", 8, "bold")
        ).pack(anchor="w")
        self._rows: dict[str, tuple[tk.Label, tk.Label]] = {}

    def update_readings(self, readings: list[Reading]) -> None:
        size = 17 if len(readings) == 1 else 12
        for reading in readings:
            row = self._rows.get(reading.key)
            if row is None:
                frame = tk.Frame(self, bg=BG)
                frame.pack(anchor="w", pady=(2, 0))
                mark = tk.Label(
                    frame, text=reading.short, bg=BG, fg=LABEL_FG, font=("TkFixedFont", 10, "bold")
                )
                if reading.short:
                    mark.pack(side="left", padx=(0, 6))
                value = tk.Label(frame, bg=BG, fg=VALUE_FG, font=("TkDefaultFont", size, "bold"))
                value.pack(side="left")
                row = self._rows[reading.key] = (mark, value)
            row[1].config(text=format_value(reading), fg=reading_colour(reading, VALUE_FG))


class SlimTile(tk.Frame):
    """A device on one line, for the slim strip: "CPU 8% 35°C", "NET ↓ 11 KB/s ↑ 1 KB/s"."""

    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master, bg=BG)
        tk.Label(
            self, text=title.upper(), bg=BG, fg=LABEL_FG, font=("TkDefaultFont", 8, "bold")
        ).pack(side="left", padx=(0, 6))
        self._labels: list[tk.Label] = []

    def update_readings(self, readings: list[Reading]) -> None:
        primary = pick_primary(readings)
        fraction = reading_fraction(primary) if primary else 0.0
        for i, (text, kind, reading) in enumerate(slim_items(readings)):
            if i == len(self._labels):
                label = tk.Label(self, bg=BG, padx=0)
                label.pack(side="left", padx=(0 if i == 0 else 6, 0))
                self._labels.append(label)
            if kind == PRIMARY:
                fg = level_colour(fraction) if fraction >= 0.6 else VALUE_FG
                font = ("TkDefaultFont", 10, "bold")
            else:
                fg, font = reading_colour(reading, SUB_FG), ("TkDefaultFont", 9)
            self._labels[i].config(text=text, fg=fg, font=font)


def tile_heights(tile: tk.Frame) -> Tuple[int, int]:
    """(height without a sparkline, height with one), whichever way the tile is showing now."""
    height = tile.winfo_reqheight()
    if not hasattr(tile, "set_sparkline"):  # this kind of tile never has one
        return height, height
    if getattr(tile, "spark_on", False):
        return height - SPARK_EXTRA, height
    return height, height + SPARK_EXTRA


def make_tile(master: tk.Misc, readings: list[Reading]) -> tk.Frame:
    """MetricTile (big number + bar) if the device has a % or a maximum, else RateTile."""
    cls = MetricTile if pick_primary(readings) else RateTile
    return cls(master, readings[0].label)

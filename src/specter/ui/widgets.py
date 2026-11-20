"""Small building blocks for the panel."""

from __future__ import annotations

import tkinter as tk
from typing import List, Optional, Tuple

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


def level_colour(fraction: float) -> str:
    if fraction >= 0.85:
        return RED
    if fraction >= 0.60:
        return YELLOW
    return GREEN


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


def format_secondary(reading: Reading) -> str:
    """Value for the small line under the big number: "0.9/3.8GB", "59°C"."""
    if reading.maximum is not None and reading.unit != "%":
        return f"{reading.value:.1f}/{reading.maximum:.1f}{reading.unit}"
    return format_value(reading)


def pick_primary(readings: list[Reading]) -> Optional[Reading]:
    """The reading that gets the big number and the bar: a % first, then one with a maximum.

    None means the tile has no bar (fan speed, disk and network rates).
    """
    for reading in readings:
        if reading.unit == "%":
            return reading
    for reading in readings:
        if reading.maximum is not None:
            return reading
    return None


def reading_fraction(reading: Reading) -> float:
    """How full a reading is (0..1): % / 100 or value / maximum. 0 if neither."""
    if reading.unit == "%":
        return reading.value / 100
    if reading.maximum:
        return reading.value / reading.maximum
    return 0.0


# Kinds of text in a slim tile.
PRIMARY, SECONDARY = "primary", "secondary"


def slim_parts(readings: list[Reading]) -> List[Tuple[str, str]]:
    """Texts for a one-line tile, as (text, kind).

    CPU: [("8%", PRIMARY), ("35°C", SECONDARY)]. A device without a primary (fan,
    disk, net) shows every value as primary, with its mark: [("↓ 11 KB/s", PRIMARY), ...].
    """
    primary = pick_primary(readings)
    if primary is None:
        return [(f"{r.short} {format_value(r)}".strip(), PRIMARY) for r in readings]
    others = [(format_value(r), SECONDARY) for r in readings if r is not primary]
    return [(format_value(primary), PRIMARY)] + others


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


class MetricTile(tk.Frame):
    """One device (CPU, RAM, GPU...): label, big value, segment bar, small sub line."""

    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master, bg=BG)
        self._title = tk.Label(
            self, text=title.upper(), bg=BG, fg=LABEL_FG, font=("TkDefaultFont", 8, "bold")
        )
        self._value = tk.Label(self, text="—", bg=BG, fg=VALUE_FG, font=("TkDefaultFont", 17, "bold"))
        self._bar = SegmentBar(self)
        self._sub = tk.Label(self, text="", bg=BG, fg=SUB_FG, font=("TkFixedFont", 8))

        self._title.pack(anchor="w")
        self._value.pack(anchor="w", pady=(0, 3))
        self._bar.pack(anchor="w")
        self._sub.pack(anchor="w", pady=(3, 0))

    def update_readings(self, readings: list[Reading]) -> None:
        primary = pick_primary(readings) or readings[0]
        others = [r for r in readings if r is not primary]

        self._value.config(text=format_value(primary))

        fraction = reading_fraction(primary)
        self._bar.set_fraction(fraction)
        self._value.config(fg=level_colour(fraction) if fraction >= 0.6 else VALUE_FG)

        sub_parts = [format_secondary(r) for r in others]
        if primary.maximum is not None and primary.unit != "%":
            sub_parts.insert(0, f"of {primary.maximum:.1f}{primary.unit}")
        self._sub.config(text="  ".join(sub_parts) or " ")


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
            row[1].config(text=format_value(reading))


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
        for i, (text, kind) in enumerate(slim_parts(readings)):
            if i == len(self._labels):
                label = tk.Label(self, bg=BG, padx=0)
                label.pack(side="left", padx=(0 if i == 0 else 6, 0))
                self._labels.append(label)
            if kind == PRIMARY:
                fg = level_colour(fraction) if fraction >= 0.6 else VALUE_FG
                font = ("TkDefaultFont", 10, "bold")
            else:
                fg, font = SUB_FG, ("TkDefaultFont", 9)
            self._labels[i].config(text=text, fg=fg, font=font)


def make_tile(master: tk.Misc, readings: list[Reading]) -> tk.Frame:
    """MetricTile (big number + bar) if the device has a % or a maximum, else RateTile."""
    cls = MetricTile if pick_primary(readings) else RateTile
    return cls(master, readings[0].label)

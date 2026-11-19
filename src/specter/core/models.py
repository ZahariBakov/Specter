"""Plain data structures shared by every layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Reading:
    """One sensor value, e.g. CPU load = 23.5 %."""

    key: str  # stable id, e.g. "cpu.load"
    label: str  # text shown in the panel, e.g. "CPU"
    value: float
    unit: str  # "%", "°C", "MB/s" ...
    maximum: float | None = None  # for bars; None = no bar


@dataclass
class Snapshot:
    """All readings collected in one polling cycle."""

    time: float
    readings: dict[str, Reading] = field(default_factory=dict)

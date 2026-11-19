"""CPU and RAM via psutil (works on Linux and Windows)."""

from __future__ import annotations

import psutil

from specter.core.models import Reading
from specter.sensors.base import SensorProvider

_GIB = 1024**3


class SystemProvider(SensorProvider):
    name = "system"

    def __init__(self) -> None:
        # The first cpu_percent() call always returns 0.0; prime it here.
        psutil.cpu_percent(interval=None)

    def read(self) -> list[Reading]:
        mem = psutil.virtual_memory()
        return [
            Reading("cpu.load", "CPU", psutil.cpu_percent(interval=None), "%", 100.0),
            Reading("ram.used", "RAM", mem.used / _GIB, "GB", mem.total / _GIB),
        ]

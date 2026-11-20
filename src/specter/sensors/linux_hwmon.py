"""CPU temperature and fan speed from Linux hwmon (via psutil)."""

from __future__ import annotations

import sys

import psutil

from specter.core.models import Reading
from specter.sensors.base import SensorProvider

# (chip, label) pairs to try, in order: Intel first, then AMD.
_CPU_TEMP_SOURCES = [("coretemp", "Package id 0"), ("k10temp", "Tctl"), ("k10temp", "Tdie")]


class LinuxHwmonProvider(SensorProvider):
    name = "linux_hwmon"

    def is_available(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        return bool(self.read())

    def read(self) -> list[Reading]:
        readings: list[Reading] = []
        temp = self._cpu_temp()
        if temp is not None:
            readings.append(Reading("cpu.temp", "CPU", temp, "°C"))
        rpm = self._fan_rpm()
        if rpm is not None:
            readings.append(Reading("fan.rpm", "Fan", rpm, "RPM"))
        return readings

    def _cpu_temp(self) -> float | None:
        temps = psutil.sensors_temperatures()
        for chip, label in _CPU_TEMP_SOURCES:
            for entry in temps.get(chip, []):
                if entry.label == label:
                    return float(entry.current)
        return None

    def _fan_rpm(self) -> float | None:
        # sensors_fans() doesn't exist on Windows.
        sensors_fans = getattr(psutil, "sensors_fans", None)
        if sensors_fans is None:
            return None
        # Skip 0 RPM: those are usually empty fan headers.
        spinning = [f.current for chip in sensors_fans().values() for f in chip if f.current > 0]
        return float(max(spinning)) if spinning else None

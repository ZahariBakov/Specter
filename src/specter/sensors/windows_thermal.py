"""CPU temperature on Windows from ACPI thermal zones (no admin needed).

Low quality fallback: ``\\Thermal Zone Information(*)\\Temperature`` reports whole Kelvin
for each ACPI zone. Only a zone whose name contains "CPU" is used.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any, List, Optional

from specter.core.models import Reading
from specter.sensors.base import SensorProvider
from specter.sensors.windows_pdh import PdhReader

log = logging.getLogger(__name__)

PATH = r"\Thermal Zone Information(*)\Temperature"
MIN_C = 1.0
MAX_C = 150.0


class WindowsThermalProvider(SensorProvider):
    name = "windows_thermal"
    priority = 70

    def __init__(self, reader: Optional[Any] = None, probe_delay: float = 0.25) -> None:
        self._reader = reader if reader is not None else PdhReader()
        self._probe_delay = probe_delay

    def _cpu_temp(self) -> Optional[float]:
        zones = self._reader.read(PATH)
        best: Optional[float] = None
        for zone, kelvin in zones.items():
            if "cpu" not in str(zone).lower():
                continue
            try:
                celsius = float(kelvin) - 273.15
            except (TypeError, ValueError):
                continue
            if not (MIN_C <= celsius <= MAX_C):
                continue
            if best is None or celsius > best:
                best = celsius
        return best

    def is_available(self) -> bool:
        try:
            if not sys.platform.startswith("win"):
                self.unavailable_reason = "not Windows"
                return False
            if not PdhReader.supported():
                self.unavailable_reason = "Performance counters (pdh.dll) not available"
                return False
            self._reader.read(PATH)  # priming read: the first one returns nothing
            if self._probe_delay > 0:
                time.sleep(self._probe_delay)
            if self._cpu_temp() is None:
                self.unavailable_reason = "no ACPI thermal zone named like a CPU"
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            self.unavailable_reason = "%s: %s" % (type(exc).__name__, exc)
            return False

    def read(self) -> List[Reading]:
        try:
            temp = self._cpu_temp()
        except Exception:  # noqa: BLE001
            log.debug("thermal read failed", exc_info=True)
            return []
        if temp is None:
            return []
        return [Reading(key="cpu.temp", label="CPU", value=temp, unit="°C")]

    def close(self) -> None:
        try:
            self._reader.close()
        except Exception:  # noqa: BLE001
            pass

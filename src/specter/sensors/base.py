"""Common interface for all data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from specter.core.models import Reading


class SensorProvider(ABC):
    """A source of readings (psutil, hwmon, NVML, ...)."""

    name: str = "provider"

    def is_available(self) -> bool:
        """Return False if this provider can't work on this machine."""
        return True

    @abstractmethod
    def read(self) -> list[Reading]:
        """Return the current readings. Called from the poller thread."""

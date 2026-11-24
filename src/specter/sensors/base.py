"""Common interface for all data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from specter.core.models import Reading


class SensorProvider(ABC):
    """A source of readings (psutil, hwmon, NVML, ...)."""

    name: str = "provider"
    #: LOWER number = better source. Providers run in priority order and the
    #: first one that returns a reading key wins.
    priority: int = 50
    #: Set by the provider when `is_available()` is False.
    unavailable_reason: str = ""

    def is_available(self) -> bool:
        """Return False if this provider can't work on this machine."""
        return True

    @abstractmethod
    def read(self) -> list[Reading]:
        """Return the current readings. Called from the poller thread."""

    def close(self) -> None:
        """Free resources (e.g. shut down a driver library). Called once at exit."""

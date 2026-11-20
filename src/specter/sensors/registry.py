"""Decides which providers run on this machine."""

from __future__ import annotations

import logging

from specter.sensors.base import SensorProvider
from specter.sensors.linux_hwmon import LinuxHwmonProvider
from specter.sensors.system import SystemProvider

log = logging.getLogger(__name__)


def create_providers() -> list[SensorProvider]:
    """Instantiate every provider that works here.

    New providers (hwmon temps, NVIDIA, Windows/LHM) get added to this list.
    """
    candidates: list[type[SensorProvider]] = [SystemProvider, LinuxHwmonProvider]

    providers: list[SensorProvider] = []
    for cls in candidates:
        try:
            provider = cls()
            if provider.is_available():
                providers.append(provider)
        except Exception:  # a broken sensor must not stop the app
            log.exception("Provider %s failed to start", cls.__name__)
    return providers

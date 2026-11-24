"""Decides which providers run on this machine."""

from __future__ import annotations

import logging
from typing import List, Tuple

from specter.sensors.base import SensorProvider
from specter.sensors.gpu_hub import GpuHubProvider
from specter.sensors.io_rates import IoRatesProvider
from specter.sensors.lhm import LhmGpuBackend, LhmProvider
from specter.sensors.linux_drm_gpu import LinuxDrmGpuProvider
from specter.sensors.linux_sysfs import LinuxSysfsProvider
from specter.sensors.nvidia import NvidiaProvider
from specter.sensors.system import SystemProvider
from specter.sensors.windows_gpu import WindowsGpuProvider
from specter.sensors.windows_thermal import WindowsThermalProvider

log = logging.getLogger(__name__)


def _gpu_backends() -> list:
    """GPU backends; they run inside the GPU hub, never as providers of their own."""
    backends = []
    for cls in (NvidiaProvider, LinuxDrmGpuProvider, WindowsGpuProvider, LhmGpuBackend):
        try:
            backends.append(cls())
        except Exception:  # a broken backend must not stop the others
            log.exception("GPU backend %s failed to start", cls.__name__)
    return backends


def _gpu_hub() -> SensorProvider:
    return GpuHubProvider(_gpu_backends())


def _candidates() -> list:
    """Factories (classes or functions) of all providers. New providers get added here."""
    return [
        SystemProvider,
        LhmProvider,
        LinuxSysfsProvider,
        _gpu_hub,
        IoRatesProvider,
        WindowsThermalProvider,
    ]


def _probe() -> List[Tuple[str, SensorProvider, bool, str]]:
    """Instantiate every candidate. Returns (name, provider, available, reason).

    `provider` is None if it failed to start (reason = the exception text).
    """
    results = []  # type: List[Tuple[str, SensorProvider, bool, str]]
    for cls in _candidates():
        name = getattr(cls, "name", cls.__name__)
        try:
            provider = cls()
            name = provider.name
            available = bool(provider.is_available())
            reason = "" if available else (provider.unavailable_reason or "not available")
            if not available:
                log.info("Provider %s unavailable: %s", name, reason)
            results.append((name, provider, available, reason))
        except Exception as exc:  # a broken sensor must not stop the app
            log.exception("Provider %s failed to start", cls.__name__)
            results.append((name, None, False, str(exc) or exc.__class__.__name__))
    return results


def sort_providers(providers: list[SensorProvider]) -> list[SensorProvider]:
    """Best source first (lowest priority number); stable for equal priorities."""
    return sorted(providers, key=lambda p: p.priority)


def create_providers() -> list[SensorProvider]:
    """Instantiate every provider that works here, best priority first."""
    providers: list[SensorProvider] = []
    for _name, provider, available, _reason in _probe():
        if provider is None:
            continue
        if available:
            providers.append(provider)
        else:
            try:
                provider.close()
            except Exception:
                log.exception("Provider %s failed to close", provider.name)
    return sort_providers(providers)


def provider_report() -> list[tuple[str, bool, str]]:
    """(provider name, available, reason) for every candidate, including ones
    that failed to start. Instantiated providers are closed again."""
    report: list[tuple[str, bool, str]] = []
    for name, provider, available, reason in _probe():
        report.append((name, available, reason))
        if provider is not None:
            try:
                provider.close()
            except Exception:
                log.exception("Provider %s failed to close", name)
    return report

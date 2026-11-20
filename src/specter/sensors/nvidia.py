"""NVIDIA GPUs via NVML (optional: pip install "specter[nvidia]")."""

from __future__ import annotations

import logging
from typing import Any, Callable

from specter.core.models import Reading
from specter.sensors.base import SensorProvider

log = logging.getLogger(__name__)

_GIB = 1024**3


class NvidiaProvider(SensorProvider):
    """`gpu.load` (%), `gpu.mem` (GB of total), `gpu.temp` (°C).

    With more than one GPU the keys become `gpu0.*`, `gpu1.*` (one tile each).
    """

    name = "nvidia"

    def __init__(self) -> None:
        self._nvml: Any = None
        self._handles: list = []
        try:
            import pynvml
        except ImportError:
            log.info("nvidia-ml-py is not installed; NVIDIA sensors are off")
            return
        try:
            pynvml.nvmlInit()
        except pynvml.NVMLError as exc:
            log.info("NVML is not available (%s); NVIDIA sensors are off", exc)
            return
        self._nvml = pynvml
        try:
            count = pynvml.nvmlDeviceGetCount()
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
        except pynvml.NVMLError as exc:
            log.warning("Could not list NVIDIA GPUs: %s", exc)
            self._handles = []

    def is_available(self) -> bool:
        return bool(self._handles)

    def read(self) -> list[Reading]:
        readings: list[Reading] = []
        several = len(self._handles) > 1
        for index, handle in enumerate(self._handles):
            device = f"gpu{index}" if several else "gpu"
            label = f"GPU {index}" if several else "GPU"
            readings.extend(self._read_gpu(handle, device, label))
        return readings

    def close(self) -> None:
        if self._nvml is not None:
            self._nvml.nvmlShutdown()
            self._nvml = None
            self._handles = []

    def _read_gpu(self, handle: Any, device: str, label: str) -> list[Reading]:
        nvml = self._nvml
        readings: list[Reading] = []

        load = self._try(lambda: nvml.nvmlDeviceGetUtilizationRates(handle).gpu)
        if load is not None:
            readings.append(Reading(f"{device}.load", label, float(load), "%", 100.0))

        mem = self._try(lambda: nvml.nvmlDeviceGetMemoryInfo(handle))
        if mem is not None and mem.total:
            readings.append(Reading(f"{device}.mem", label, mem.used / _GIB, "GB", mem.total / _GIB))

        temp = self._try(lambda: nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU))
        if temp is not None:
            readings.append(Reading(f"{device}.temp", label, float(temp), "°C"))
        return readings

    def _try(self, call: Callable[[], Any]) -> Any:
        """Some GPUs don't support every query; skip just that value."""
        try:
            return call()
        except self._nvml.NVMLError:
            return None

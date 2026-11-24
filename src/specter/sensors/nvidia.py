"""NVIDIA GPUs via NVML (optional: pip install "specter[nvidia]")."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from specter.core.models import Reading
from specter.sensors.base import SensorProvider
from specter.sensors.gpu_types import (
    FAN_PCT,
    LOAD,
    MEM,
    TEMP,
    VENDOR_NVIDIA,
    GpuDevice,
    normalize_pci,
)

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
            self.unavailable_reason = "nvidia-ml-py is not installed"
            return
        try:
            pynvml.nvmlInit()
        except pynvml.NVMLError as exc:
            self.unavailable_reason = "NVML not available (%s): no NVIDIA driver" % exc
            return
        self._nvml = pynvml
        try:
            count = pynvml.nvmlDeviceGetCount()
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
        except pynvml.NVMLError as exc:
            log.warning("Could not list NVIDIA GPUs: %s", exc)
            self._handles = []

    def is_available(self) -> bool:
        if not self._handles and not self.unavailable_reason:
            self.unavailable_reason = "no NVIDIA GPU found"
        return bool(self._handles)

    def read(self) -> list[Reading]:
        readings: list[Reading] = []
        devices = self.devices()
        several = len(devices) > 1
        for index, gpu in enumerate(devices):
            device = f"gpu{index}" if several else "gpu"
            label = f"GPU {index}" if several else "GPU"
            for metric in _READ_METRICS:  # read() keeps its old keys (no fan %)
                r = gpu.metrics.get(metric)
                if r is not None:
                    readings.append(Reading(f"{device}.{metric}", label, r.value, r.unit, r.maximum, r.short))
        return readings

    def devices(self) -> List[GpuDevice]:
        """One GpuDevice per NVML handle; never raises."""
        out: List[GpuDevice] = []
        if self._nvml is None:
            return out
        for handle in list(self._handles):
            try:
                out.append(self._device(handle))
            except Exception:  # noqa: BLE001
                log.debug("NVIDIA device read failed", exc_info=True)
        return out

    def close(self) -> None:
        if self._nvml is not None:
            self._nvml.nvmlShutdown()
            self._nvml = None
            self._handles = []

    def _device(self, handle: Any) -> GpuDevice:
        nvml = self._nvml
        name = _text(self._try(lambda: nvml.nvmlDeviceGetName(handle))) or "NVIDIA GPU"
        bus = _text(self._try(lambda: nvml.nvmlDeviceGetPciInfo(handle).busId))
        return GpuDevice(
            name=name,
            vendor=VENDOR_NVIDIA,
            pci=normalize_pci(bus) if bus else None,
            integrated=False,
            metrics=self._metrics(handle),
        )

    def _metrics(self, handle: Any) -> Dict[str, Reading]:
        nvml = self._nvml
        metrics: Dict[str, Reading] = {}

        load = self._try(lambda: nvml.nvmlDeviceGetUtilizationRates(handle).gpu)
        if load is not None:
            metrics[LOAD] = Reading(LOAD, "", float(load), "%", 100.0)

        mem = self._try(lambda: nvml.nvmlDeviceGetMemoryInfo(handle))
        if mem is not None and mem.total:
            metrics[MEM] = Reading(MEM, "", mem.used / _GIB, "GB", mem.total / _GIB)

        temp = self._try(lambda: nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU))
        if temp is not None:
            metrics[TEMP] = Reading(TEMP, "", float(temp), "°C")

        fan = self._try(lambda: nvml.nvmlDeviceGetFanSpeed(handle))  # laptops: NVMLError
        if fan is not None:
            metrics[FAN_PCT] = Reading(FAN_PCT, "", float(fan), "%", 100.0)
        return metrics

    def _try(self, call: Callable[[], Any]) -> Any:
        """Some GPUs don't support every query; skip just that value."""
        try:
            return call()
        except self._nvml.NVMLError:
            return None
        except Exception:  # noqa: BLE001  (old pynvml without the function, odd values)
            log.debug("NVML query failed", exc_info=True)
            return None


_READ_METRICS = (LOAD, MEM, TEMP)


def _text(value: Any) -> str:
    """NVML returns bytes in old versions and str in new ones."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip("\x00 ").strip()
    return str(value).strip()

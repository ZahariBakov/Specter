"""GPU load and memory on Windows from performance counters (works for any vendor)."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from specter.core.models import Reading
from specter.sensors.base import SensorProvider
from specter.sensors.gpu_types import LOAD, MEM, VENDOR_IDS, GpuDevice

log = logging.getLogger(__name__)

_GIB = 1024**3

ENGINE_PATH = r"\GPU Engine(*)\Utilization Percentage"
DEDICATED_PATH = r"\GPU Adapter Memory(*)\Dedicated Usage"
SHARED_PATH = r"\GPU Adapter Memory(*)\Shared Usage"

_ENGINE_RE = re.compile(r"luid_(0x[0-9a-f]+_0x[0-9a-f]+).*?engtype_(.*)$", re.IGNORECASE)
_MEM_RE = re.compile(r"luid_(0x[0-9a-f]+_0x[0-9a-f]+)", re.IGNORECASE)


def _luid_of(key: str) -> str:
    """'luid_0x00000000_0x00015d4d' -> '0x00000000_0x00015d4d' (lower case)."""
    return key[len("luid_"):].lower()


class WindowsGpuProvider(SensorProvider):
    """`gpu.load` (%), `gpu.mem` (GB of total). Several GPUs -> `gpu0.*`, `gpu1.*`."""

    name = "windows_gpu"
    priority = 60  # worse than NVML

    def __init__(self, reader: Any = None, adapters_fn: Optional[Callable[[], list]] = None) -> None:
        self._reader = reader
        self._adapters_fn = adapters_fn
        self._adapters: List[Any] = []
        #: device key ("gpu", "gpu0", ...) -> real adapter name
        self.names: Dict[str, str] = {}
        self._checked = False
        self._ok = False

    # -- setup -----------------------------------------------------------------
    def _setup(self) -> bool:
        if self._checked:
            return self._ok
        self._checked = True
        try:
            if self._reader is None:
                if sys.platform != "win32":
                    self.unavailable_reason = "GPU counters need Windows"
                    return False
                from specter.sensors.windows_pdh import PdhReader

                if not PdhReader.supported():
                    self.unavailable_reason = "Windows performance counters (PDH) are not available"
                    return False
                self._reader = PdhReader()
            if self._adapters_fn is None:
                from specter.sensors.windows_dxgi import list_adapters

                self._adapters_fn = list_adapters
            self._adapters = [a for a in self._adapters_fn() if not a.software]
        except Exception as exc:  # noqa: BLE001
            log.debug("GPU setup failed", exc_info=True)
            self.unavailable_reason = "GPU setup failed: %s" % exc
            return False
        if not self._adapters:
            self.unavailable_reason = "no GPU adapter found"
            return False
        several = len(self._adapters) > 1
        for index, adapter in enumerate(self._adapters):
            self.names["gpu%d" % index if several else "gpu"] = adapter.name
        self._ok = True
        return True

    def is_available(self) -> bool:
        return self._setup()

    # -- reading ---------------------------------------------------------------
    def read(self) -> List[Reading]:
        readings: List[Reading] = []
        devices = self.devices()
        several = len(devices) > 1
        for index, gpu in enumerate(devices):
            device = "gpu%d" % index if several else "gpu"
            label = "GPU %d" % index if several else "GPU"
            for metric, r in gpu.metrics.items():
                readings.append(Reading(device + "." + metric, label, r.value, r.unit, r.maximum, r.short))
        return readings

    def devices(self) -> List[GpuDevice]:
        """One GpuDevice per hardware adapter (software renderers skipped); never raises."""
        try:
            if not self._setup():
                return []
            return self._devices()
        except Exception:  # noqa: BLE001
            log.debug("GPU read failed", exc_info=True)
            return []

    def _devices(self) -> List[GpuDevice]:
        from specter.sensors.windows_dxgi import luid_key

        engines = self._safe_read(ENGINE_PATH)
        dedicated = self._safe_read(DEDICATED_PATH)
        shared = self._safe_read(SHARED_PATH)

        # engine load: sum over pids per (luid, engtype)
        sums: Dict[Tuple[str, str], float] = {}
        for instance, value in engines.items():
            m = _ENGINE_RE.search(instance)
            if not m or not m.group(2):
                continue
            k = (m.group(1).lower(), m.group(2).lower())
            sums[k] = sums.get(k, 0.0) + float(value)
        ded = self._by_luid(dedicated)
        sha = self._by_luid(shared)

        devices: List[GpuDevice] = []
        for adapter in self._adapters:
            luid = _luid_of(luid_key(adapter.luid))
            integrated = adapter.dedicated_bytes < _GIB
            metrics: Dict[str, Reading] = {}

            loads = [v for (lu, _t), v in sums.items() if lu == luid]
            if loads:
                load = max(0.0, min(100.0, max(loads)))
                metrics[LOAD] = Reading(LOAD, "", load, "%", 100.0)

            if luid in ded or luid in sha:
                if not integrated:
                    used = ded.get(luid, 0.0)
                    total = float(adapter.dedicated_bytes)
                else:
                    used = sha.get(luid, 0.0) + ded.get(luid, 0.0)
                    total = float(adapter.shared_bytes + adapter.dedicated_bytes)
                if total > 0:
                    metrics[MEM] = Reading(MEM, "", used / _GIB, "GB", total / _GIB)

            devices.append(
                GpuDevice(
                    name=adapter.name,
                    vendor=VENDOR_IDS.get(adapter.vendor_id, ""),
                    pci=None,
                    integrated=integrated,
                    metrics=metrics,
                )
            )
        return devices

    @staticmethod
    def _by_luid(values: Dict[str, float]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for instance, value in values.items():
            m = _MEM_RE.search(instance)
            if m:
                k = m.group(1).lower()
                out[k] = out.get(k, 0.0) + float(value)
        return out

    def _safe_read(self, path: str) -> Dict[str, float]:
        try:
            return dict(self._reader.read(path) or {})
        except Exception:  # noqa: BLE001
            log.debug("GPU counter %s failed", path, exc_info=True)
            return {}

    def close(self) -> None:
        reader, self._reader = self._reader, None
        try:
            if reader is not None and hasattr(reader, "close"):
                reader.close()
        except Exception:  # noqa: BLE001
            pass

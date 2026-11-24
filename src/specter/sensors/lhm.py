"""CPU temperature, fans and GPU extras from LibreHardwareMonitor (Windows, Step 22b).

LibreHardwareMonitor (or the older OpenHardwareMonitor) must run as administrator with
"Options -> Remote Web Server" enabled. `LhmProvider` gives `cpu.temp` and `fan.rpm`;
`LhmGpuBackend` feeds the GPU hub, mostly to fill in GPU temperature and fan speed. Both share
one `LhmClient`, so one poll makes one HTTP request.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from typing import Dict, List, Optional

from specter.core.models import Reading
from specter.sensors.base import SensorProvider
from specter.sensors.gpu_types import (
    FAN,
    FAN_PCT,
    LOAD,
    MEM,
    TEMP,
    VENDOR_AMD,
    VENDOR_INTEL,
    VENDOR_NVIDIA,
    GpuDevice,
)
from specter.sensors.lhm_client import ENV_URL, LhmClient, LhmSensor

log = logging.getLogger(__name__)

TEMP_MIN = 1.0
TEMP_MAX = 150.0

#: Non-GPU hardware kinds whose fans count for `fan.rpm`.
FAN_KINDS = ("superio", "mainboard", "cpu", "other")
GPU_VENDORS = {"gpu-nvidia": VENDOR_NVIDIA, "gpu-amd": VENDOR_AMD, "gpu-intel": VENDOR_INTEL}

#: CPU temperature sensor names, best first (compared case-insensitively).
CPU_TEMP_NAMES = ("cpu package", "core (tctl/tdie)", "tctl/tdie", "tctl", "tdie", "package")
_CORE_RE = re.compile(r"^(cpu )?core( #\d+| max)$", re.IGNORECASE)

UNAVAILABLE = "LibreHardwareMonitor is Windows only (set %s to use a remote one)" % ENV_URL

_shared: Optional[LhmClient] = None
_shared_lock = threading.Lock()


def shared_client() -> LhmClient:
    """The one LhmClient that the CPU provider and the GPU backend share (created lazily)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = LhmClient()
        return _shared


def _platform_ok() -> bool:
    return sys.platform == "win32" or bool(os.environ.get(ENV_URL, "").strip())


def _status(client: Optional[LhmClient]) -> str:
    url = getattr(client, "url", "") or "?"
    if client is not None and getattr(client, "reachable", False):
        return "connected to %s" % url
    return (
        "not reachable at %s: start LibreHardwareMonitor as administrator and enable "
        "Options -> Remote Web Server (port 8085)" % url
    )


def _sensors(client: Optional[LhmClient]) -> List[LhmSensor]:
    if client is None:
        return []
    try:
        return list(client.sensors() or [])
    except Exception:  # noqa: BLE001 - the client should not raise, but never trust it
        log.debug("lhm: sensors() failed", exc_info=True)
        return []


def _valid_temp(value: float) -> bool:
    return TEMP_MIN <= value <= TEMP_MAX


def cpu_temp(sensors: List[LhmSensor]) -> Optional[float]:
    """Best CPU temperature: package / Tctl first, else the hottest core."""
    temps = [
        s for s in sensors
        if s.kind == "cpu" and s.type == "Temperature" and _valid_temp(s.value)
    ]
    by_name: Dict[str, float] = {}
    for s in temps:
        by_name.setdefault(s.name.strip().lower(), s.value)
    for name in CPU_TEMP_NAMES:
        if name in by_name:
            return by_name[name]
    cores = [s.value for s in temps if _CORE_RE.match(s.name.strip())]
    return max(cores) if cores else None


def _to_gb(value: float, unit: str) -> float:
    unit = (unit or "").strip().upper()
    if unit in ("MB", "MIB"):
        return value / 1024.0
    if unit in ("KB", "KIB"):
        return value / (1024.0 * 1024.0)
    if unit in ("TB", "TIB"):
        return value * 1024.0
    if unit in ("GB", "GIB"):
        return value
    return value / 1024.0  # LHM reports GPU memory in MB


class LhmProvider(SensorProvider):
    """`cpu.temp` and `fan.rpm` from LibreHardwareMonitor's web server."""

    name = "lhm"
    priority = 20

    def __init__(self, client: Optional[LhmClient] = None) -> None:
        self._client = client
        self.fans: Dict[str, float] = {}

    @property
    def client(self) -> LhmClient:
        if self._client is None:
            self._client = shared_client()
        return self._client

    @property
    def status(self) -> str:
        try:
            return _status(self.client)
        except Exception:  # noqa: BLE001
            return _status(None)

    def is_available(self) -> bool:
        if _platform_ok():
            return True
        self.unavailable_reason = UNAVAILABLE
        return False

    def read(self) -> List[Reading]:
        try:
            sensors = _sensors(self.client)
        except Exception:  # noqa: BLE001
            sensors = []
        readings: List[Reading] = []
        temp = cpu_temp(sensors)
        if temp is not None:
            readings.append(Reading("cpu.temp", "CPU", temp, "°C"))
        fans: Dict[str, float] = {}
        for s in sensors:
            if s.kind in FAN_KINDS and s.type == "Fan" and s.value > 0:
                fans["%s/%s" % (s.hardware, s.name)] = s.value
        self.fans = fans
        if fans:
            readings.append(Reading("fan.rpm", "Fan", max(fans.values()), "RPM"))
        return readings


class LhmGpuBackend:
    """GPU backend for the hub: one GpuDevice per GPU that LibreHardwareMonitor lists."""

    name = "lhm"
    priority = 65
    unavailable_reason = ""

    def __init__(self, client: Optional[LhmClient] = None) -> None:
        self._client = client

    @property
    def client(self) -> LhmClient:
        if self._client is None:
            self._client = shared_client()
        return self._client

    @property
    def status(self) -> str:
        try:
            return _status(self.client)
        except Exception:  # noqa: BLE001
            return _status(None)

    def is_available(self) -> bool:
        if _platform_ok():
            return True
        self.unavailable_reason = UNAVAILABLE
        return False

    def devices(self) -> List[GpuDevice]:
        try:
            sensors = _sensors(self.client)
            groups: Dict[str, List[LhmSensor]] = {}
            order: List[str] = []
            for s in sensors:
                if s.kind not in GPU_VENDORS:
                    continue
                if s.hardware not in groups:
                    groups[s.hardware] = []
                    order.append(s.hardware)
                groups[s.hardware].append(s)
            out = []
            for hw in order:
                items = groups[hw]
                out.append(
                    GpuDevice(
                        name=hw,
                        vendor=GPU_VENDORS.get(items[0].kind, ""),
                        integrated=None,
                        metrics=self._metrics(items),
                    )
                )
            return out
        except Exception:  # noqa: BLE001 - never raise into the hub
            log.debug("lhm: GPU devices failed", exc_info=True)
            return []

    @staticmethod
    def _metrics(items: List[LhmSensor]) -> Dict[str, Reading]:
        def find(stype: str, name: str) -> Optional[LhmSensor]:
            for s in items:
                if s.type == stype and s.name.strip().lower() == name:
                    return s
            return None

        metrics: Dict[str, Reading] = {}
        load = find("Load", "gpu core")
        if load is not None:
            metrics[LOAD] = Reading(LOAD, "", max(0.0, min(100.0, load.value)), "%", 100.0)

        temps = [s for s in items if s.type == "Temperature" and _valid_temp(s.value)]
        temp = None
        for s in temps:
            if s.name.strip().lower() == "gpu core":
                temp = s
                break
        if temp is None:
            others = [s for s in temps if s.name.strip().lower() != "gpu hot spot"]
            temp = others[0] if others else (temps[0] if temps else None)
        if temp is not None:
            metrics[TEMP] = Reading(TEMP, "", temp.value, "°C")

        fans = [s.value for s in items if s.type == "Fan" and s.value > 0]
        if fans:
            metrics[FAN] = Reading(FAN, "", max(fans), "RPM")

        fan_pct = find("Control", "gpu fan")
        if fan_pct is not None and 0 <= fan_pct.value <= 100:
            metrics[FAN_PCT] = Reading(FAN_PCT, "", fan_pct.value, "%", 100.0)

        mem = _memory(items)
        if mem is not None:
            metrics[MEM] = mem
        return metrics

    def close(self) -> None:
        pass


def _memory(items: List[LhmSensor]) -> Optional[Reading]:
    data: Dict[str, LhmSensor] = {}
    for s in items:
        if s.type in ("SmallData", "Data"):
            data.setdefault(s.name.strip().lower(), s)
    total_s = data.get("gpu memory total") or data.get("d3d dedicated memory total")
    total = _to_gb(total_s.value, total_s.unit) if total_s is not None else None
    used_s = data.get("gpu memory used")
    if total is None and used_s is not None and "gpu memory free" in data:
        free_s = data["gpu memory free"]
        total = _to_gb(used_s.value, used_s.unit) + _to_gb(free_s.value, free_s.unit)
    if used_s is None and total is not None:
        used_s = data.get("d3d dedicated memory used")
    if used_s is None or used_s.value < 0:
        return None
    used = _to_gb(used_s.value, used_s.unit)
    if total is not None and total <= 0:
        total = None
    return Reading(MEM, "", used, "GB", total)

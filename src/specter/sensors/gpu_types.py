"""Shared contract between the GPU backends and the GPU hub (Step 21).

Every GPU backend (NVML, Linux DRM, Windows counters, later LibreHardwareMonitor) describes the
GPUs it sees as `GpuDevice`s. The hub (`gpu_hub.py`) merges devices that are the same physical GPU,
gives them the final keys (`gpu.*` for one GPU, `gpu0.*`, `gpu1.*` for several) and labels, and is
the only GPU provider the registry runs. So keys never collide and one GPU = one tile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from specter.core.models import Reading

# Metric names a backend may put in `GpuDevice.metrics` (the part after the dot in the final key).
LOAD = "load"  # %, maximum 100
MEM = "mem"  # GB, maximum = total GB
TEMP = "temp"  # °C
FAN = "fan"  # RPM
FAN_PCT = "fanpct"  # % of the fan's maximum speed (NVML gives only this)
FREQ = "freq"  # % of max clock, an approximate load (Intel on Linux), short "~"

VENDOR_NVIDIA, VENDOR_AMD, VENDOR_INTEL = "nvidia", "amd", "intel"
VENDOR_IDS = {0x10DE: VENDOR_NVIDIA, 0x1002: VENDOR_AMD, 0x8086: VENDOR_INTEL}


@dataclass
class GpuDevice:
    """One GPU as one backend sees it.

    `metrics` maps a metric name (LOAD, MEM, ...) to a Reading whose key and label the hub
    replaces; only value, unit, maximum and short matter.
    """

    name: str  # as the driver reports it, e.g. "NVIDIA GeForce RTX 3060", "Intel(R) Iris(R) Xe Graphics"
    vendor: str = ""  # VENDOR_* or "" if unknown
    pci: Optional[str] = None  # PCI slot, lower case "0000:01:00.0", if the backend knows it
    integrated: Optional[bool] = None  # None = unknown
    metrics: Dict[str, Reading] = field(default_factory=dict)


def normalize_pci(slot: str) -> str:
    """"00000000:01:00.0" (NVML) or "0000:01:00.0" (sysfs) -> "0000:01:00.0"."""
    try:
        slot = str(slot).strip().lower()
        if slot.count(":") < 2:  # no domain part, e.g. "01:00.0": assume domain 0
            return "0000:" + slot if ":" in slot else slot
        domain, rest = slot.split(":", 1)
        return "%04x:%s" % (int(domain or "0", 16) & 0xFFFF, rest) if _is_hex(domain) else slot
    except Exception:  # never let a strange bus id break a sensor
        return str(slot)


def _is_hex(text: str) -> bool:
    try:
        int(text or "0", 16)
    except ValueError:
        return False
    return True

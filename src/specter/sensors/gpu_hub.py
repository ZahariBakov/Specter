"""The GPU hub: the only GPU provider the registry runs (Step 21).

Every GPU backend (NVML, Linux DRM, Windows counters, ...) reports `GpuDevice`s. The hub merges
devices that are the same physical GPU (same PCI slot, or same vendor + name when that is
unambiguous), gives them stable keys (`gpu.*` for one GPU, `gpu0.*`, `gpu1.*` for several) and
short labels, and drops metrics that would make the tile ambiguous.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Dict, List, Optional, Set, Tuple

from specter.core.models import Reading
from specter.sensors.base import SensorProvider
from specter.sensors.gpu_types import FAN_PCT, FREQ, LOAD, MEM, GpuDevice, normalize_pci

log = logging.getLogger(__name__)

MAX_SHORT = 12

_MARKS = re.compile(r"\((?:r|tm)\)|®|™", re.IGNORECASE)
_PARENS = re.compile(r"\([^)]*\)")
_DROP_WORDS = {
    "nvidia", "geforce", "corporation", "corp", "corp.", "inc", "inc.", "amd", "intel",
    "graphics", "microsoft", "gpu",
}
_VENDOR_WORDS = (("nvidia", "NVIDIA"), ("amd", "AMD"), ("intel", "Intel"))


def short_name(name: str) -> str:
    """Compact tile title from a driver name: "NVIDIA GeForce RTX 3060" -> "RTX 3060"."""
    text = _PARENS.sub(" ", _MARKS.sub(" ", name or ""))
    words = [w for w in text.split() if w.lower() not in _DROP_WORDS]
    if len(words) > 1:
        # "Radeon RX 6600" -> "RX 6600", but a lone "Radeon" stays.
        words = [w for w in words if w.lower() != "radeon"] or words
    if not words:
        lower = (name or "").lower()
        for word, shown in _VENDOR_WORDS:
            if word in lower:
                return shown
        return "GPU"
    out = words[0][:MAX_SHORT]
    for word in words[1:]:
        if len(out) + 1 + len(word) > MAX_SHORT:
            break
        out += " " + word
    return out


def _norm_name(name: str) -> str:
    return " ".join(_MARKS.sub(" ", name or "").lower().split())


def _name_id(dev: GpuDevice) -> Optional[Tuple[str, str]]:
    if not dev.vendor:
        return None
    return (dev.vendor, _norm_name(dev.name))


def _pci(dev: GpuDevice) -> Optional[str]:
    if not dev.pci:
        return None
    try:
        return normalize_pci(dev.pci)
    except Exception:  # noqa: BLE001 - a strange slot string must not crash the hub
        return dev.pci.strip().lower()


def _same(a: GpuDevice, b: GpuDevice, a_unique: bool, b_unique: bool) -> bool:
    pa, pb = _pci(a), _pci(b)
    if pa and pb:
        return pa == pb
    na = _name_id(a)
    return na is not None and na == _name_id(b) and a_unique and b_unique


def merge_devices(per_backend: List[List[GpuDevice]]) -> List[GpuDevice]:
    """Merge the backends' device lists (best backend first) into one list of physical GPUs."""
    merged: List[GpuDevice] = []
    for devices in per_backend:
        counts: Dict[Tuple[str, str], int] = {}
        for dev in devices:
            nid = _name_id(dev)
            if nid is not None:
                counts[nid] = counts.get(nid, 0) + 1
        merged_counts: Dict[Tuple[str, str], int] = {}
        for dev in merged:
            nid = _name_id(dev)
            if nid is not None:
                merged_counts[nid] = merged_counts.get(nid, 0) + 1
        taken: Set[int] = set()  # merged entries that already got a device from this backend
        for dev in devices:
            nid = _name_id(dev)
            dev_unique = nid is not None and counts.get(nid) == 1
            target = None
            for i, existing in enumerate(merged):
                if i in taken:
                    continue
                eid = _name_id(existing)
                ex_unique = eid is not None and merged_counts.get(eid) == 1
                if _same(existing, dev, ex_unique, dev_unique):
                    target = i
                    break
            if target is None:
                merged.append(GpuDevice(dev.name, dev.vendor, _pci(dev), dev.integrated,
                                        dict(dev.metrics)))
                taken.add(len(merged) - 1)
                continue
            taken.add(target)
            best = merged[target]
            if not best.name:
                best.name = dev.name
            if not best.vendor:
                best.vendor = dev.vendor
            if not best.pci:
                best.pci = _pci(dev)
            if best.integrated is None:
                best.integrated = dev.integrated
            for metric, reading in dev.metrics.items():
                best.metrics.setdefault(metric, reading)
    if merged and all(d.pci for d in merged):
        merged.sort(key=lambda d: d.pci or "")
    return merged


def tile_metrics(metrics: Dict[str, Reading]) -> Tuple[Dict[str, Reading], Dict[str, Reading]]:
    """Split a device's metrics into (shown on the tile, extra for diagnostics).

    The tile's big number is the reading with unit "%" (else one with a maximum), so only one
    "%" reading may be shown: a real LOAD beats the FREQ approximation, and fan percent is only
    shown when there is no LOAD, FREQ or MEM to be the primary value.
    """
    shown = dict(metrics)
    extra: Dict[str, Reading] = {}
    if LOAD in shown and FREQ in shown:
        extra[FREQ] = shown.pop(FREQ)
    if FAN_PCT in shown and (LOAD in shown or FREQ in shown or MEM in shown):
        extra[FAN_PCT] = shown.pop(FAN_PCT)
    return shown, extra


def device_labels(devices: List[GpuDevice]) -> List[Tuple[str, str]]:
    """(key prefix, label) per device: one GPU -> ("gpu", "GPU"), else "gpu0", "gpu1", ..."""
    if len(devices) == 1:
        return [("gpu", "GPU")]
    labels = []
    for i, dev in enumerate(devices):
        label = short_name(dev.name) if dev.name else ""
        labels.append(label if label and label != "GPU" else "GPU %d" % i)
    seen: Dict[str, int] = {}
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
    out = []
    for i, label in enumerate(labels):
        if seen[label] > 1 and not label.startswith("GPU "):
            label = "%s %d" % (label, i)
        out.append(("gpu%d" % i, label))
    return out


def device_readings(dev: GpuDevice, prefix: str, label: str) -> List[Reading]:
    shown, _extra = tile_metrics(dev.metrics)
    return [replace(r, key=prefix + "." + metric, label=label) for metric, r in shown.items()]


def assign_keys(devices: List[GpuDevice]) -> List[Reading]:
    """Final readings for a merged device list (no memory between reads)."""
    out: List[Reading] = []
    for dev, (prefix, label) in zip(devices, device_labels(devices)):
        out.extend(device_readings(dev, prefix, label))
    return out


def _identities(dev: GpuDevice) -> Set[str]:
    ids = set()
    pci = _pci(dev)
    if pci:
        ids.add("pci:" + pci)
    nid = _name_id(dev)
    if nid is not None:
        ids.add("name:%s:%s" % nid)
    elif dev.name:
        ids.add("name::" + _norm_name(dev.name))
    return ids


class GpuHubProvider(SensorProvider):
    """Runs the GPU backends, merges what they see and emits one tile per physical GPU."""

    name = "gpu"
    priority = 40

    def __init__(self, backends) -> None:
        self.backend_report: List[Tuple[str, bool, str]] = []
        usable = []
        for backend in backends:
            bname = getattr(backend, "name", type(backend).__name__)
            try:
                ok = bool(backend.is_available())
            except Exception as exc:  # noqa: BLE001 - a broken backend is just unavailable
                ok = False
                reason = "error: %s" % exc
            else:
                reason = "" if ok else (getattr(backend, "unavailable_reason", "") or "not available")
            self.backend_report.append((bname, ok, reason))
            if ok:
                usable.append(backend)
            else:
                self._close(backend)
        usable.sort(key=lambda b: getattr(b, "priority", 50))
        self.backends = usable
        if not usable:
            reasons = ["%s: %s" % (n, r) for n, _ok, r in self.backend_report]
            self.unavailable_reason = "; ".join(reasons) or "no GPU backends"
        # Devices in the order their keys were first given: (identities, last full name).
        self._known: List[Tuple[Set[str], GpuDevice]] = []
        self.names: Dict[str, str] = {}
        self.extra: Dict[str, Dict[str, Reading]] = {}

    def is_available(self) -> bool:
        return bool(self.backends)

    def read(self) -> List[Reading]:
        per_backend: List[List[GpuDevice]] = []
        for backend in self.backends:
            try:
                per_backend.append(list(backend.devices() or []))
            except Exception:  # noqa: BLE001 - one backend failing must not hide the others
                log.debug("GPU backend %s failed", getattr(backend, "name", backend), exc_info=True)
        devices = merge_devices(per_backend)
        current: Dict[int, GpuDevice] = {}
        for dev in devices:
            ids = _identities(dev)
            slot = None
            for i, (known_ids, _dev) in enumerate(self._known):
                if i not in current and known_ids & ids:
                    slot = i
                    break
            if slot is None:
                self._known.append((ids, dev))
                slot = len(self._known) - 1
            else:
                self._known[slot][0].update(ids)
                self._known[slot] = (self._known[slot][0], dev)
            current[slot] = dev
        labels = device_labels([dev for _ids, dev in self._known])
        out: List[Reading] = []
        self.names = {}
        self.extra = {}
        for i, (prefix, label) in enumerate(labels):
            self.names[prefix] = self._known[i][1].name
            dev = current.get(i)
            if dev is None:
                continue
            _shown, extra = tile_metrics(dev.metrics)
            if extra:
                self.extra[prefix] = extra
            out.extend(device_readings(dev, prefix, label))
        return out

    def close(self) -> None:
        for backend in self.backends:
            self._close(backend)

    @staticmethod
    def _close(backend) -> None:
        try:
            close = getattr(backend, "close", None)
            if close is not None:
                close()
        except Exception:  # noqa: BLE001
            log.debug("closing GPU backend failed", exc_info=True)

"""AMD and Intel GPUs on Linux from /sys/class/drm (no root, no extra libraries).

NVIDIA cards are skipped: NVML (`nvidia.py`) covers them.

* AMD (`amdgpu`, `radeon`): real load (`gpu_busy_percent`), VRAM, hwmon temp and fan.
* Intel (`i915`, `xe`): there is no load counter without root, so the tile shows the
  current / maximum GPU frequency as `<dev>.freq` (marked "~"), never as `<dev>.load`.
  Discrete Intel (Arc) may also have hwmon temp/fan; integrated Intel has no VRAM.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import sys
from typing import Dict, List, Optional

from specter.core.models import Reading
from specter.sensors.base import SensorProvider
from specter.sensors.gpu_types import FAN, FREQ, LOAD, MEM, TEMP, VENDOR_IDS, GpuDevice, normalize_pci

log = logging.getLogger(__name__)

_GIB = 1024**3

_CARD_RE = re.compile(r"^card(\d+)$")
AMD_DRIVERS = ("amdgpu", "radeon")
INTEL_DRIVERS = ("i915", "xe")
SUPPORTED_DRIVERS = AMD_DRIVERS + INTEL_DRIVERS


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except Exception:  # noqa: BLE001
        return None


def _read_float(path: str) -> Optional[float]:
    text = _read_text(path)
    if not text:
        return None
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


def _read_uevent(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    text = _read_text(path)
    if not text:
        return out
    for line in text.splitlines():
        if "=" in line:
            k, _sep, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


class _Card:
    def __init__(self, path: str, index: int, driver: str) -> None:
        self.path = path  # {root}/class/drm/cardN
        self.index = index
        self.driver = driver
        self.pci = ""
        self.vendor: Optional[int] = None
        self.device_id: Optional[int] = None

    @property
    def device_dir(self) -> str:
        return os.path.join(self.path, "device")

    @property
    def is_amd(self) -> bool:
        return self.driver in AMD_DRIVERS


class LinuxDrmGpuProvider(SensorProvider):
    """`gpu.load`/`gpu.mem`/`gpu.temp`/`gpu.fan` (AMD), `gpu.freq` (Intel, approximate).

    Several supported cards -> `gpu0.*`, `gpu1.*` in card order.
    """

    name = "linux_drm_gpu"
    priority = 40

    def __init__(self, root: str = "/sys", check_platform: bool = True) -> None:
        self._root = root
        self._check_platform = check_platform
        self._cards: List[_Card] = []
        #: device key ("gpu", "gpu0", ...) -> driver-based name
        self.names: Dict[str, str] = {}
        #: device key -> PCI slot ("0000:03:00.0"), for merging with other providers
        self.pci: Dict[str, str] = {}
        self._checked = False
        self._ok = False

    # -- setup -----------------------------------------------------------------
    def _setup(self) -> bool:
        if self._checked:
            return self._ok
        self._checked = True
        if self._check_platform and not sys.platform.startswith("linux"):
            self.unavailable_reason = "DRM GPU sensors need Linux"
            return False
        try:
            self._cards = self._find_cards()
        except Exception as exc:  # noqa: BLE001
            log.debug("DRM card scan failed", exc_info=True)
            self.unavailable_reason = "DRM card scan failed: %s" % exc
            return False
        if not self._cards:
            self.unavailable_reason = "no AMD or Intel GPU found in /sys/class/drm"
            return False
        for card, device in zip(self._cards, self._device_keys()):
            vendor = "AMD" if card.is_amd else "Intel"
            self.names[device] = "%s GPU (%s)" % (vendor, card.driver)
            if card.pci:
                self.pci[device] = card.pci
        self._ok = True
        return True

    def is_available(self) -> bool:
        return self._setup()

    def _find_cards(self) -> List[_Card]:
        drm = os.path.join(self._root, "class", "drm")
        try:
            entries = os.listdir(drm)
        except OSError:
            return []
        found: List[_Card] = []
        for entry in entries:
            m = _CARD_RE.match(entry)
            if not m:
                continue  # connectors like card0-HDMI-A-1, renderD128, version
            path = os.path.join(drm, entry)
            try:
                uevent = _read_uevent(os.path.join(path, "device", "uevent"))
                driver = self._driver_of(path, uevent)
                if driver not in SUPPORTED_DRIVERS:
                    continue
                card = _Card(path, int(m.group(1)), driver)
                card.pci = uevent.get("PCI_SLOT_NAME", "")
                card.vendor = self._read_hex(os.path.join(path, "device", "vendor"))
                card.device_id = self._read_hex(os.path.join(path, "device", "device"))
                found.append(card)
            except Exception:  # noqa: BLE001
                log.debug("Skipping DRM entry %s", path, exc_info=True)
        found.sort(key=lambda c: c.index)
        return found

    @staticmethod
    def _driver_of(card_path: str, uevent: Dict[str, str]) -> str:
        try:
            target = os.readlink(os.path.join(card_path, "device", "driver"))
            name = os.path.basename(target.rstrip("/\\"))
            if name:
                return name
        except (OSError, ValueError, NotImplementedError):
            pass
        return uevent.get("DRIVER", "")

    @staticmethod
    def _read_hex(path: str) -> Optional[int]:
        text = _read_text(path)
        if not text:
            return None
        try:
            return int(text, 16)
        except ValueError:
            return None

    def _device_keys(self) -> List[str]:
        if len(self._cards) > 1:
            return ["gpu%d" % i for i in range(len(self._cards))]
        return ["gpu"] * len(self._cards)

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
        """One GpuDevice per kept (AMD / Intel) card, in card order; never raises."""
        try:
            if not self._setup():
                return []
            keys = self._device_keys()
            out: List[GpuDevice] = []
            for card, key in zip(self._cards, keys):
                metrics: Dict[str, Reading] = {}
                try:
                    metrics = self._read_card(card)
                except Exception:  # noqa: BLE001
                    log.debug("DRM GPU read failed for %s", card.path, exc_info=True)
                pci: Optional[str] = None
                try:
                    pci = normalize_pci(card.pci) if card.pci else None
                except Exception:  # noqa: BLE001
                    pci = None
                out.append(
                    GpuDevice(
                        name=self.names.get(key, "GPU (%s)" % card.driver),
                        vendor=VENDOR_IDS.get(card.vendor, "") if card.vendor is not None else "",
                        pci=pci,
                        integrated=self._integrated(card),
                        metrics=metrics,
                    )
                )
            return out
        except Exception:  # noqa: BLE001
            log.debug("DRM GPU read failed", exc_info=True)
            return []

    @staticmethod
    def _integrated(card: _Card) -> Optional[bool]:
        """i915/xe without VRAM -> True, amdgpu with >= 1 GiB VRAM -> False, else unknown."""
        vram = _read_float(os.path.join(card.device_dir, "mem_info_vram_total"))
        if card.driver in INTEL_DRIVERS and not vram:
            return True
        if card.driver == "amdgpu" and vram is not None and vram >= _GIB:
            return False
        return None

    def _read_card(self, card: _Card) -> Dict[str, Reading]:
        out: Dict[str, Reading] = {}
        dev = card.device_dir
        if card.is_amd:
            load = _read_float(os.path.join(dev, "gpu_busy_percent"))
            if load is not None:
                out[LOAD] = Reading(LOAD, "", max(0.0, min(100.0, load)), "%", 100.0)
            used = _read_float(os.path.join(dev, "mem_info_vram_used"))
            total = _read_float(os.path.join(dev, "mem_info_vram_total"))
            if used is not None and total:
                out[MEM] = Reading(MEM, "", used / _GIB, "GB", total / _GIB)
        else:
            freq = self._intel_freq(card)
            if freq is not None:
                out[FREQ] = Reading(FREQ, "", freq, "%", 100.0, "~")
        out.update(self._hwmon(card))
        return out

    @staticmethod
    def _intel_freq(card: _Card) -> Optional[float]:
        if card.driver == "xe":
            base = os.path.join(card.device_dir, "tile0", "gt0", "freq0")
            act = _read_float(os.path.join(base, "act_freq"))
            top = _read_float(os.path.join(base, "max_freq"))
        else:
            act = _read_float(os.path.join(card.path, "gt_act_freq_mhz"))
            if act is None:
                act = _read_float(os.path.join(card.path, "gt_cur_freq_mhz"))
            top = _read_float(os.path.join(card.path, "gt_max_freq_mhz"))
        if act is None or not top or top <= 0:
            return None
        return max(0.0, min(100.0, act / top * 100.0))

    @staticmethod
    def _hwmon(card: _Card) -> Dict[str, Reading]:
        out: Dict[str, Reading] = {}
        dirs = sorted(glob.glob(os.path.join(glob.escape(card.device_dir), "hwmon", "hwmon*")))
        for hw in dirs:
            temp_file = os.path.join(hw, "temp1_input")
            for label_file in sorted(glob.glob(os.path.join(glob.escape(hw), "temp*_label"))):
                if (_read_text(label_file) or "").lower() == "edge":
                    temp_file = label_file[: -len("_label")] + "_input"
                    break
            temp = _read_float(temp_file)
            if temp is not None and -50000 < temp < 200000:
                out[TEMP] = Reading(TEMP, "", temp / 1000.0, "°C")
            rpm = _read_float(os.path.join(hw, "fan1_input"))
            if rpm is not None and rpm > 0:
                out[FAN] = Reading(FAN, "", rpm, "RPM")
            if out:
                break
        return out

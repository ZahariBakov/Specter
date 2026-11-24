"""CPU temperature and fan speed read straight from Linux /sys (hwmon + thermal zones)."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from specter.core.models import Reading
from specter.sensors.base import SensorProvider

log = logging.getLogger(__name__)

#: hwmon chips that belong to a GPU; their fans are left to the GPU provider.
GPU_CHIPS = ("amdgpu", "nouveau", "i915", "xe", "radeon")
#: ARM / Raspberry Pi CPU thermal chips.
ARM_CHIPS = ("cpu_thermal", "cpu-thermal", "soc_thermal")

TEMP_MIN = 1.0
TEMP_MAX = 150.0

_NUM = re.compile(r"(\d+)")


def _natural_key(path: Path) -> list:
    return [int(p) if p.isdigit() else p for p in _NUM.split(path.name)]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text().strip()
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _read_number(path: Path) -> Optional[float]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _valid_temp(millideg: Optional[float]) -> Optional[float]:
    if millideg is None:
        return None
    value = millideg / 1000.0
    if TEMP_MIN <= value <= TEMP_MAX:
        return value
    return None


class _Chip:
    """One hwmon directory: its name, temperatures and fans."""

    def __init__(self, path: Path) -> None:
        self.path = path
        # Some drivers keep their files under device/ instead of the hwmon dir.
        self.dirs = [path, path / "device"]
        self.name = ""
        for d in self.dirs:
            name = _read_text(d / "name")
            if name:
                self.name = name
                break

    def _inputs(self, kind: str) -> List[Tuple[int, Path]]:
        """(index, input file) for `kind` ("temp"/"fan"); hwmon dir wins over device/."""
        found: Dict[int, Path] = {}
        pattern = re.compile(r"^%s(\d+)_input$" % kind)
        for d in self.dirs:
            try:
                entries = list(d.iterdir())
            except OSError:
                continue
            for entry in entries:
                m = pattern.match(entry.name)
                if m:
                    found.setdefault(int(m.group(1)), entry)
        return sorted(found.items())

    def _label(self, input_path: Path) -> str:
        label_path = input_path.with_name(input_path.name.replace("_input", "_label"))
        return _read_text(label_path) or ""

    def temps(self) -> List[Tuple[int, str, float]]:
        """(index, label, °C) for every valid temperature."""
        out = []
        for index, path in self._inputs("temp"):
            value = _valid_temp(_read_number(path))
            if value is not None:
                out.append((index, self._label(path), value))
        return out

    def fans(self) -> List[Tuple[int, str, float]]:
        """(index, label, RPM) for every spinning fan."""
        out = []
        for index, path in self._inputs("fan"):
            rpm = _read_number(path)
            if rpm is not None and rpm > 0:
                out.append((index, self._label(path), rpm))
        return out


def _by_label(temps: List[Tuple[int, str, float]], label: str) -> Optional[float]:
    for _, lab, value in temps:
        if lab == label:
            return value
    return None


def _hottest(temps: List[Tuple[int, str, float]], prefix: str) -> Optional[float]:
    values = [v for _, lab, v in temps if lab.startswith(prefix)]
    return max(values) if values else None


def _temp1(temps: List[Tuple[int, str, float]]) -> Optional[float]:
    for index, _, value in temps:
        if index == 1:
            return value
    return temps[0][2] if temps else None


class LinuxSysfsProvider(SensorProvider):
    name = "linux_sysfs"
    priority = 40

    def __init__(self, root: str = "/sys", check_platform: bool = True) -> None:
        self.root = Path(root)
        self.check_platform = check_platform
        #: Every spinning fan, "chip/fanN (label)" -> RPM (for diagnostics).
        self.fans: Dict[str, float] = {}

    def is_available(self) -> bool:
        if self.check_platform and not sys.platform.startswith("linux"):
            self.unavailable_reason = "not Linux"
            return False
        try:
            found = bool(self.read())
        except Exception as exc:  # never crash on a strange /sys
            log.debug("linux_sysfs read failed: %s", exc)
            found = False
        if not found:
            self.unavailable_reason = "no CPU temperature or fan sensor in /sys"
            return False
        self.unavailable_reason = ""
        return True

    def read(self) -> list[Reading]:
        chips = self._chips()
        readings: list[Reading] = []
        temp = self._cpu_temp(chips)
        if temp is not None:
            readings.append(Reading("cpu.temp", "CPU", temp, "°C"))
        rpm = self._fan_rpm(chips)
        if rpm is not None:
            readings.append(Reading("fan.rpm", "Fan", rpm, "RPM"))
        return readings

    # -- discovery -------------------------------------------------------

    def _chips(self) -> List[_Chip]:
        base = self.root / "class" / "hwmon"
        try:
            paths = sorted(base.glob("hwmon*"), key=_natural_key)
        except OSError:
            return []
        return [_Chip(p) for p in paths]

    def _thermal_zone(self, zone_type: str) -> Optional[float]:
        base = self.root / "class" / "thermal"
        try:
            zones = sorted(base.glob("thermal_zone*"), key=_natural_key)
        except OSError:
            return None
        for zone in zones:
            if _read_text(zone / "type") == zone_type:
                value = _valid_temp(_read_number(zone / "temp"))
                if value is not None:
                    return value
        return None

    # -- CPU temperature -------------------------------------------------

    def _cpu_temp(self, chips: List[_Chip]) -> Optional[float]:
        def chip_temps(*names: str) -> List[List[Tuple[int, str, float]]]:
            return [c.temps() for c in chips if c.name in names]

        for temps in chip_temps("coretemp"):
            value = _hottest(temps, "Package id ")
            if value is None:
                value = _hottest(temps, "Core ")
            if value is not None:
                return value
        for temps in chip_temps("k10temp"):
            for value in (_by_label(temps, "Tctl"), _by_label(temps, "Tdie"), _hottest(temps, "Tccd")):
                if value is not None:
                    return value
        for temps in chip_temps("zenpower"):
            for value in (_by_label(temps, "Tdie"), _by_label(temps, "Tctl")):
                if value is not None:
                    return value
        for temps in chip_temps(*ARM_CHIPS):
            value = _temp1(temps)
            if value is not None:
                return value
        value = self._thermal_zone("x86_pkg_temp")
        if value is not None:
            return value
        for temps in chip_temps("acpitz"):
            value = _temp1(temps)
            if value is not None:
                return value
        return self._thermal_zone("acpitz")

    # -- fans ------------------------------------------------------------

    def _fan_rpm(self, chips: List[_Chip]) -> Optional[float]:
        fans: Dict[str, float] = {}
        for chip in chips:
            if chip.name in GPU_CHIPS:
                continue
            for index, label, rpm in chip.fans():
                key = "%s/fan%d" % (chip.name or chip.path.name, index)
                if label:
                    key += " (%s)" % label
                fans[key] = rpm
        self.fans = fans
        return max(fans.values()) if fans else None

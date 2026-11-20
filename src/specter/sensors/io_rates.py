"""Disk and network speed (MB/s) from psutil's byte counters.

Each read compares the counters with the previous read, so the first read
returns nothing and the tiles appear one interval later.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Dict, Optional, Tuple

import psutil

from specter.core.models import Reading
from specter.sensors.base import SensorProvider

_MIB = 1024**2

# Not real disks, or devices whose traffic is already counted on the disks below them.
_SKIP_DISK = re.compile(r"^(loop|ram|zram|dm-|md|sr|fd)")
# Partitions: sda1, vdb2, nvme0n1p1, mmcblk0p1. Their bytes are in the whole disk already.
_PARTITION = re.compile(r"^((sd|hd|vd|xvd)[a-z]+\d+|(nvme\d+n\d+|mmcblk\d+)p\d+)$")
# Loopback and virtual interfaces (containers, bridges, VPN tunnels) would count traffic twice.
_SKIP_NIC = re.compile(r"^(lo$|docker|veth|br-|virbr|vmnet|vboxnet|tun|tap|wg)|loopback", re.I)

Pair = Tuple[int, int]


def is_physical_disk(name: str) -> bool:
    return not _SKIP_DISK.match(name) and not _PARTITION.match(name)


def is_physical_nic(name: str) -> bool:
    return not _SKIP_NIC.search(name)


class IoRatesProvider(SensorProvider):
    """`disk.read` / `disk.write` and `net.down` / `net.up` in MB/s."""

    name = "io_rates"

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last: Optional[Tuple[float, Dict[str, Optional[Pair]]]] = None

    def is_available(self) -> bool:
        totals = self._totals()
        return totals["disk"] is not None or totals["net"] is not None

    def read(self) -> list[Reading]:
        now, totals = self._clock(), self._totals()
        previous, self._last = self._last, (now, totals)
        if previous is None:
            return []
        elapsed = now - previous[0]
        if elapsed <= 0:
            return []

        def rates(device: str) -> Optional[Tuple[float, float]]:
            before, after = previous[1].get(device), totals[device]
            if before is None or after is None:
                return None
            # A counter can go down (device removed, wrap-around): count that as 0.
            return tuple(max(0, a - b) / elapsed / _MIB for a, b in zip(after, before))

        readings: list[Reading] = []
        net = rates("net")
        if net is not None:
            readings.append(Reading("net.down", "Net", net[0], "MB/s", short="↓"))
            readings.append(Reading("net.up", "Net", net[1], "MB/s", short="↑"))
        disk = rates("disk")
        if disk is not None:
            readings.append(Reading("disk.read", "Disk", disk[0], "MB/s", short="R"))
            readings.append(Reading("disk.write", "Disk", disk[1], "MB/s", short="W"))
        return readings

    def _totals(self) -> Dict[str, Optional[Pair]]:
        return {"disk": self._disk_totals(), "net": self._net_totals()}

    @staticmethod
    def _disk_totals() -> Optional[Pair]:
        try:
            disks = psutil.disk_io_counters(perdisk=True)
        except (OSError, RuntimeError):
            return None
        chosen = [c for name, c in (disks or {}).items() if is_physical_disk(name)]
        if not chosen:
            return None
        return sum(c.read_bytes for c in chosen), sum(c.write_bytes for c in chosen)

    @staticmethod
    def _net_totals() -> Optional[Pair]:
        try:
            nics = psutil.net_io_counters(pernic=True)
            stats = psutil.net_if_stats()
        except (OSError, RuntimeError):
            return None
        chosen = [
            c
            for name, c in (nics or {}).items()
            if is_physical_nic(name) and (name not in stats or stats[name].isup)
        ]
        if not chosen:
            return None
        return sum(c.bytes_recv for c in chosen), sum(c.bytes_sent for c in chosen)

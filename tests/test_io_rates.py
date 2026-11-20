from __future__ import annotations

from collections import namedtuple

from specter.sensors import io_rates
from specter.sensors.io_rates import IoRatesProvider, is_physical_disk, is_physical_nic

MIB = 1024**2
Disk = namedtuple("Disk", "read_bytes write_bytes")
Nic = namedtuple("Nic", "bytes_recv bytes_sent")
Stat = namedtuple("Stat", "isup")


class Fake:
    """Counters and a clock that the test moves forward."""

    def __init__(self, monkeypatch):
        self.now = 100.0
        self.disks = {}
        self.nics = {}
        self.up = {}
        ps = io_rates.psutil
        monkeypatch.setattr(ps, "disk_io_counters", lambda perdisk: dict(self.disks))
        monkeypatch.setattr(ps, "net_io_counters", lambda pernic: dict(self.nics))
        monkeypatch.setattr(ps, "net_if_stats", lambda: {n: Stat(u) for n, u in self.up.items()})

    def provider(self):
        return IoRatesProvider(clock=lambda: self.now)


def values(provider):
    return {r.key: round(r.value, 3) for r in provider.read()}


def test_first_read_is_empty_then_rates(monkeypatch):
    fake = Fake(monkeypatch)
    fake.disks = {"nvme0n1": Disk(0, 0), "nvme0n1p1": Disk(0, 0), "loop3": Disk(0, 0)}
    fake.nics = {"enp2s0": Nic(0, 0), "lo": Nic(0, 0)}
    fake.up = {"enp2s0": True, "lo": True}
    provider = fake.provider()
    assert provider.is_available()
    assert provider.read() == []

    fake.now += 2
    # Partition and loop bytes must be ignored (they'd be counted twice / aren't real disks).
    fake.disks = {
        "nvme0n1": Disk(20 * MIB, 4 * MIB),
        "nvme0n1p1": Disk(20 * MIB, 4 * MIB),
        "loop3": Disk(500 * MIB, 0),
    }
    fake.nics = {"enp2s0": Nic(10 * MIB, 1 * MIB), "lo": Nic(900 * MIB, 900 * MIB)}
    assert values(provider) == {
        "net.down": 5.0,
        "net.up": 0.5,
        "disk.read": 10.0,
        "disk.write": 2.0,
    }


def test_counter_going_down_counts_as_zero(monkeypatch):
    fake = Fake(monkeypatch)
    fake.nics = {"eth0": Nic(50 * MIB, 50 * MIB)}
    provider = fake.provider()
    provider.read()
    fake.now += 1
    fake.nics = {"eth0": Nic(1 * MIB, 51 * MIB)}
    assert values(provider) == {"net.down": 0.0, "net.up": 1.0}


def test_down_interfaces_are_skipped(monkeypatch):
    fake = Fake(monkeypatch)
    fake.nics = {"enp2s0": Nic(0, 0), "enp3s0": Nic(0, 0)}
    fake.up = {"enp2s0": True, "enp3s0": False}
    provider = fake.provider()
    provider.read()
    fake.now += 1
    fake.nics = {"enp2s0": Nic(MIB, 0), "enp3s0": Nic(100 * MIB, 0)}
    assert values(provider)["net.down"] == 1.0


def test_nothing_to_measure_means_unavailable(monkeypatch):
    fake = Fake(monkeypatch)
    fake.disks = {"loop0": Disk(0, 0)}
    fake.nics = {"lo": Nic(0, 0)}
    assert not fake.provider().is_available()


def test_disk_and_nic_filters():
    for name in ("sda", "sdh", "nvme0n1", "mmcblk0", "vda", "PhysicalDrive0"):
        assert is_physical_disk(name), name
    for name in ("sda1", "nvme0n1p2", "mmcblk0p1", "loop12", "dm-0", "zram0", "sr0", "md127"):
        assert not is_physical_disk(name), name
    for name in ("enp2s0", "wlp3s0", "eth0", "Ethernet", "Wi-Fi"):
        assert is_physical_nic(name), name
    for name in ("lo", "docker0", "veth12ab", "br-1234", "virbr0", "tun0", "wg0",
                 "Loopback Pseudo-Interface 1"):
        assert not is_physical_nic(name), name

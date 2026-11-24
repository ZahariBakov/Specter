from __future__ import annotations

import pytest

from specter.core.models import Reading
from specter.sensors.gpu_hub import GpuHubProvider, assign_keys, merge_devices, short_name
from specter.sensors.gpu_types import FAN_PCT, FREQ, LOAD, MEM, TEMP, GpuDevice


def r(value, unit="%", maximum=None, short=""):
    return Reading("x", "x", value, unit, maximum, short)


class FakeBackend:
    def __init__(self, name, priority, devices=None, available=True, reason=""):
        self.name = name
        self.priority = priority
        self._devices = devices or []
        self._available = available
        self.unavailable_reason = reason
        self.fail = False
        self.closed = False

    def is_available(self):
        return self._available

    def devices(self):
        if self.fail:
            raise RuntimeError("boom")
        return self._devices

    def close(self):
        self.closed = True


def by_key(readings):
    return {x.key: x for x in readings}


@pytest.mark.parametrize("name, short", [
    ("NVIDIA GeForce RTX 3060", "RTX 3060"),
    ("NVIDIA T600", "T600"),
    ("Intel(R) Iris(R) Xe Graphics", "Iris Xe"),
    ("Intel(R) UHD Graphics 620", "UHD 620"),
    ("Intel(R) Arc(TM) A770 Graphics", "Arc A770"),
    ("AMD Radeon RX 6600", "RX 6600"),
    ("AMD Radeon(TM) Graphics", "Radeon"),
    ("AMD GPU (amdgpu)", "AMD"),
    ("", "GPU"),
    ("NVIDIA GeForce RTX 4090 Laptop GPU", "RTX 4090"),
])
def test_short_name(name, short):
    assert short_name(name) == short
    assert len(short_name(name)) <= 12


def test_single_gpu_keys():
    dev = GpuDevice("NVIDIA T600", "nvidia", "0000:01:00.0", False,
                    {LOAD: r(10, maximum=100), TEMP: r(40, "°C")})
    hub = GpuHubProvider([FakeBackend("nvml", 10, [dev])])
    out = by_key(hub.read())
    assert set(out) == {"gpu.load", "gpu.temp"}
    assert out["gpu.load"].label == "GPU"
    assert out["gpu.temp"].value == 40
    assert hub.names == {"gpu": "NVIDIA T600"}


def test_nvml_and_counters_same_card_merge():
    nvml = GpuDevice("NVIDIA GeForce RTX 3060", "nvidia", "00000000:01:00.0", False,
                     {LOAD: r(50, maximum=100), MEM: r(2, "GB", 12)})
    counters = GpuDevice("NVIDIA GeForce RTX 3060", "nvidia", None, None,
                         {LOAD: r(99, maximum=100), TEMP: r(60, "°C")})
    merged = merge_devices([[nvml], [counters]])
    assert len(merged) == 1
    m = merged[0]
    assert m.pci == "0000:01:00.0" and m.integrated is False
    assert m.metrics[LOAD].value == 50  # NVML wins
    assert m.metrics[TEMP].value == 60  # filled from the counters


def test_igpu_and_dgpu_get_numbered_keys():
    intel = GpuDevice("Intel(R) Iris(R) Xe Graphics", "intel", None, True, {LOAD: r(5)})
    nvidia = GpuDevice("NVIDIA GeForce RTX 3060", "nvidia", None, False, {LOAD: r(7)})
    out = by_key(assign_keys(merge_devices([[intel, nvidia]])))
    assert out["gpu0.load"].label == "Iris Xe"
    assert out["gpu1.load"].label == "RTX 3060"


def test_drm_amd_and_nvml_nvidia_stay_two_devices():
    amd = GpuDevice("AMD GPU (amdgpu)", "amd", "0000:05:00.0", True, {FREQ: r(30, short="~")})
    nv = GpuDevice("NVIDIA T600", "nvidia", "00000000:01:00.0", False, {LOAD: r(1)})
    merged = merge_devices([[nv], [amd]])
    assert [d.vendor for d in merged] == ["nvidia", "amd"]  # sorted by PCI slot


def test_same_pci_merges_even_with_different_names():
    a = GpuDevice("NVIDIA T600", "nvidia", "00000000:01:00.0", None, {LOAD: r(1)})
    b = GpuDevice("GPU 0", "", "0000:01:00.0", False, {TEMP: r(40, "°C")})
    merged = merge_devices([[a], [b]])
    assert len(merged) == 1 and set(merged[0].metrics) == {LOAD, TEMP}


def test_ambiguous_name_does_not_merge():
    a1 = GpuDevice("NVIDIA T600", "nvidia", "0000:01:00.0", None, {LOAD: r(1)})
    a2 = GpuDevice("NVIDIA T600", "nvidia", "0000:02:00.0", None, {LOAD: r(2)})
    c = GpuDevice("NVIDIA T600", "nvidia", None, None, {TEMP: r(40, "°C")})
    merged = merge_devices([[a1, a2], [c]])
    assert len(merged) == 3
    labels = [x.label for x in assign_keys(merged)]
    assert labels == ["T600 0", "T600 1", "T600 2"]


def test_load_drops_freq_and_fan_pct():
    dev = GpuDevice("NVIDIA T600", "nvidia", None, None,
                    {LOAD: r(10), FREQ: r(20), FAN_PCT: r(30)})
    hub = GpuHubProvider([FakeBackend("nvml", 10, [dev])])
    out = by_key(hub.read())
    assert set(out) == {"gpu.load"}
    assert set(hub.extra["gpu"]) == {FREQ, FAN_PCT}


def test_freq_drops_fan_pct():
    dev = GpuDevice("x", "intel", None, None, {FREQ: r(20), FAN_PCT: r(30)})
    assert {x.key for x in assign_keys([dev])} == {"gpu.freq"}


def test_mem_drops_fan_pct():
    dev = GpuDevice("x", "nvidia", None, None, {MEM: r(1, "GB", 4), FAN_PCT: r(30)})
    assert {x.key for x in assign_keys([dev])} == {"gpu.mem"}


def test_fan_pct_kept_when_nothing_else():
    dev = GpuDevice("x", "nvidia", None, None, {FAN_PCT: r(30), TEMP: r(50, "°C")})
    out = by_key(assign_keys([dev]))
    assert set(out) == {"gpu.fanpct", "gpu.temp"}
    assert out["gpu.fanpct"].unit == "%"


def test_keys_stable_when_a_backend_fails():
    intel = GpuDevice("Intel(R) UHD Graphics 620", "intel", None, True, {LOAD: r(5)})
    nv = GpuDevice("NVIDIA T600", "nvidia", "0000:01:00.0", False, {LOAD: r(7)})
    win = FakeBackend("windows", 30, [intel])
    nvml = FakeBackend("nvml", 10, [nv])
    hub = GpuHubProvider([win, nvml])
    first = by_key(hub.read())
    assert first["gpu0.load"].label == "T600" and first["gpu1.load"].label == "UHD 620"
    nvml.fail = True
    second = by_key(hub.read())
    assert set(second) == {"gpu1.load"}
    assert second["gpu1.load"].label == "UHD 620"
    nvml.fail = False
    third = by_key(hub.read())
    assert third["gpu0.load"].value == 7 and third["gpu1.load"].value == 5


def test_single_gpu_missing_then_back_keeps_key():
    nv = GpuDevice("NVIDIA T600", "nvidia", None, None, {LOAD: r(7)})
    b = FakeBackend("nvml", 10, [nv])
    hub = GpuHubProvider([b])
    assert {x.key for x in hub.read()} == {"gpu.load"}
    b.fail = True
    assert hub.read() == []
    b.fail = False
    assert {x.key for x in hub.read()} == {"gpu.load"}


def test_availability_and_report():
    ok = FakeBackend("nvml", 10, [])
    bad = FakeBackend("drm", 20, available=False, reason="no amdgpu")
    hub = GpuHubProvider([bad, ok])
    assert hub.is_available()
    assert hub.backends == [ok]
    assert ("drm", False, "no amdgpu") in hub.backend_report
    assert bad.closed

    none = GpuHubProvider([FakeBackend("drm", 20, available=False, reason="no amdgpu")])
    assert not none.is_available()
    assert "no amdgpu" in none.unavailable_reason


def test_is_available_raising_is_unavailable():
    class Broken(FakeBackend):
        def is_available(self):
            raise OSError("dll missing")

    hub = GpuHubProvider([Broken("pdh", 30)])
    assert not hub.is_available()
    assert "dll missing" in hub.unavailable_reason


def test_backend_raising_does_not_crash():
    good = FakeBackend("windows", 30, [GpuDevice("NVIDIA T600", "nvidia", None, None, {TEMP: r(40, "°C")})])
    bad = FakeBackend("nvml", 10)
    bad.fail = True
    hub = GpuHubProvider([bad, good])
    assert {x.key for x in hub.read()} == {"gpu.temp"}
    hub.close()
    assert good.closed and bad.closed

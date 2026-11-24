from __future__ import annotations

import json
from pathlib import Path

from specter.core.models import Reading
from specter.sensors import lhm
from specter.sensors.gpu_hub import GpuHubProvider
from specter.sensors.gpu_types import FAN, LOAD, MEM, TEMP, VENDOR_INTEL, GpuDevice
from specter.sensors.lhm import LhmGpuBackend, LhmProvider
from specter.sensors.lhm_client import LhmClient, LhmSensor, parse_tree

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    def __init__(self, sensors, reachable=True, url="http://localhost:8085/data.json"):
        self._sensors = list(sensors)
        self.reachable = reachable
        self.url = url
        self.last_error = None

    def sensors(self):
        return list(self._sensors) if self.reachable else []


def fixture(name):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return FakeClient(parse_tree(data))


def by_key(readings):
    return {r.key: r for r in readings}


def test_intel_nvidia_cpu_temp_and_fan():
    provider = LhmProvider(fixture("lhm_intel_nvidia.json"))
    out = by_key(provider.read())
    assert out["cpu.temp"].value == 45.0
    assert out["cpu.temp"].unit == "°C"
    assert out["fan.rpm"].value == 1123.0
    # GPU fan (1350 RPM) is not a system fan; 0 RPM fans are left out.
    assert provider.fans == {"Nuvoton NCT6798D/Fan #1": 1123.0, "Nuvoton NCT6798D/Fan #2": 842.0}
    assert "connected to" in provider.status


def test_intel_nvidia_gpu_device():
    devices = LhmGpuBackend(fixture("lhm_intel_nvidia.json")).devices()
    assert len(devices) == 1
    dev = devices[0]
    assert dev.name == "NVIDIA GeForce RTX 3060"
    assert dev.vendor == "nvidia"
    assert dev.metrics[LOAD].value == 7.0
    assert dev.metrics[TEMP].value == 52.0
    assert dev.metrics[FAN].value == 1350.0
    assert abs(dev.metrics[MEM].value - 1234.0 / 1024) < 1e-6
    assert dev.metrics[MEM].unit == "GB"


def test_gpu_memory_total_and_fan_percent():
    sensors = [
        LhmSensor("Radeon", "gpu-amd", "SmallData", "GPU Memory Used", 2048.0, "MB"),
        LhmSensor("Radeon", "gpu-amd", "SmallData", "GPU Memory Total", 8192.0, "MB"),
        LhmSensor("Radeon", "gpu-amd", "Control", "GPU Fan", 40.0, "%"),
    ]
    dev = LhmGpuBackend(FakeClient(sensors)).devices()[0]
    assert dev.metrics[MEM].value == 2.0
    assert dev.metrics[MEM].maximum == 8.0
    assert dev.metrics["fanpct"].value == 40.0


def test_amd_tctl_and_gpu_hot_spot_not_preferred():
    out = by_key(LhmProvider(fixture("lhm_amd.json")).read())
    assert out["cpu.temp"].value == 48.3
    assert out["fan.rpm"].value == 1034.0
    dev = LhmGpuBackend(fixture("lhm_amd.json")).devices()[0]
    assert dev.vendor == "amd"
    assert dev.metrics[TEMP].value == 55.0
    assert FAN not in dev.metrics  # 0 RPM


def test_hottest_core_fallback_and_range():
    sensors = [
        LhmSensor("CPU", "cpu", "Temperature", "CPU Core #1", 50.0, "°C"),
        LhmSensor("CPU", "cpu", "Temperature", "CPU Core #2", 57.0, "°C"),
        LhmSensor("CPU", "cpu", "Temperature", "CPU Core #3", 200.0, "°C"),
        LhmSensor("CPU", "cpu", "Temperature", "CPU Package", 0.0, "°C"),
    ]
    out = by_key(LhmProvider(FakeClient(sensors)).read())
    assert out["cpu.temp"].value == 57.0


def test_old_ohm_fixture():
    out = by_key(LhmProvider(fixture("lhm_old_ohm.json")).read())
    assert out["cpu.temp"].value == 41.0
    assert out["fan.rpm"].value == 1012.0
    dev = LhmGpuBackend(fixture("lhm_old_ohm.json")).devices()[0]
    assert dev.metrics[TEMP].value == 33.0


def test_unreachable_returns_nothing():
    def fail(url, timeout):
        raise OSError("connection refused")

    client = LhmClient(url="http://localhost:8085/data.json", fetch=fail)
    provider = LhmProvider(client)
    assert provider.read() == []
    assert provider.fans == {}
    assert provider.status.startswith("not reachable at http://localhost:8085/data.json")
    assert "Remote Web Server" in provider.status
    assert LhmGpuBackend(client).devices() == []


def test_platform_rule(monkeypatch):
    monkeypatch.setattr(lhm.sys, "platform", "linux")
    monkeypatch.delenv("SPECTER_LHM_URL", raising=False)
    provider = LhmProvider(FakeClient([]))
    backend = LhmGpuBackend(FakeClient([]))
    assert not provider.is_available()
    assert "Windows only" in provider.unavailable_reason
    assert not backend.is_available()
    monkeypatch.setenv("SPECTER_LHM_URL", "http://box:8085/data.json")
    assert provider.is_available()
    assert backend.is_available()
    monkeypatch.setattr(lhm.sys, "platform", "win32")
    monkeypatch.delenv("SPECTER_LHM_URL", raising=False)
    assert provider.is_available()


def test_shared_client_is_shared(monkeypatch):
    monkeypatch.setattr(lhm, "_shared", None)
    assert LhmProvider().client is LhmGpuBackend().client
    monkeypatch.setattr(lhm, "_shared", None)


class FakeCountersBackend:
    name = "windows"
    priority = 60

    def is_available(self):
        return True

    def devices(self):
        return [
            GpuDevice(
                "Intel(R) Iris(R) Xe Graphics",
                VENDOR_INTEL,
                integrated=True,
                metrics={LOAD: Reading(LOAD, "", 12.0, "%", 100.0)},
            )
        ]

    def close(self):
        pass


def test_hub_merges_lhm_temp_into_counters_gpu():
    lhm_sensors = [
        LhmSensor("Intel(R) Iris(R) Xe Graphics", "gpu-intel", "Load", "GPU Core", 99.0, "%"),
        LhmSensor("Intel(R) Iris(R) Xe Graphics", "gpu-intel", "Temperature", "GPU Core", 48.0, "°C"),
    ]
    hub = GpuHubProvider([LhmGpuBackend(FakeClient(lhm_sensors)), FakeCountersBackend()])
    out = by_key(hub.read())
    assert set(out) == {"gpu.load", "gpu.temp"}
    assert out["gpu.load"].value == 12.0
    assert out["gpu.temp"].value == 48.0

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from specter.sensors.nvidia import NvidiaProvider

GIB = 1024**3


class FakeNVMLError(Exception):
    pass


def fake_pynvml(monkeypatch, gpus: int = 1, init_fails: bool = False, no_temp: bool = False):
    calls = {"shutdown": 0}
    nvml = types.ModuleType("pynvml")
    nvml.NVMLError = FakeNVMLError
    nvml.NVML_TEMPERATURE_GPU = 0

    def init():
        if init_fails:
            raise FakeNVMLError("Driver Not Loaded")

    def temperature(handle, _sensor):
        if no_temp:
            raise FakeNVMLError("Not Supported")
        return 50 + handle

    def shutdown():
        calls["shutdown"] += 1

    nvml.nvmlInit = init
    nvml.nvmlShutdown = shutdown
    nvml.nvmlDeviceGetCount = lambda: gpus
    nvml.nvmlDeviceGetHandleByIndex = lambda i: i
    nvml.nvmlDeviceGetUtilizationRates = lambda h: SimpleNamespace(gpu=10 + h)
    nvml.nvmlDeviceGetMemoryInfo = lambda h: SimpleNamespace(used=1 * GIB, total=4 * GIB)
    nvml.nvmlDeviceGetTemperature = temperature
    monkeypatch.setitem(sys.modules, "pynvml", nvml)
    return calls


def test_one_gpu(monkeypatch):
    calls = fake_pynvml(monkeypatch)
    provider = NvidiaProvider()
    assert provider.is_available()
    got = {r.key: r for r in provider.read()}
    assert got["gpu.load"].value == 10 and got["gpu.load"].unit == "%"
    assert (got["gpu.mem"].value, got["gpu.mem"].maximum) == (1.0, 4.0)
    assert got["gpu.temp"].value == 50 and got["gpu.temp"].label == "GPU"
    provider.close()
    assert calls["shutdown"] == 1


def test_two_gpus_get_numbered_keys(monkeypatch):
    fake_pynvml(monkeypatch, gpus=2)
    got = {r.key: r for r in NvidiaProvider().read()}
    assert got["gpu0.load"].value == 10 and got["gpu1.load"].value == 11
    assert got["gpu1.temp"].label == "GPU 1"


def test_unsupported_query_skips_only_that_value(monkeypatch):
    fake_pynvml(monkeypatch, no_temp=True)
    assert sorted(r.key for r in NvidiaProvider().read()) == ["gpu.load", "gpu.mem"]


def test_driver_missing_means_unavailable(monkeypatch):
    fake_pynvml(monkeypatch, init_fails=True)
    provider = NvidiaProvider()
    assert not provider.is_available()
    assert provider.read() == []
    provider.close()  # must not raise


def test_library_missing_means_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)  # makes "import pynvml" fail
    assert not NvidiaProvider().is_available()


def test_no_gpus_means_unavailable(monkeypatch):
    fake_pynvml(monkeypatch, gpus=0)
    assert not NvidiaProvider().is_available()

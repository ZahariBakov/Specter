from __future__ import annotations

import psutil

from specter import app, diagnostics
from specter.core.models import Reading
from specter.sensors import registry
from specter.sensors.base import SensorProvider


class _Fake(SensorProvider):
    def __init__(self, name, priority, value):
        self.name = name
        self.priority = priority
        self._value = value

    def read(self):
        return [Reading("cpu.temp", "CPU", self._value, "°C")]


def test_sensors_report_shows_supplier_and_off_reason(monkeypatch):
    good = _Fake("good", 10, 42.0)
    worse = _Fake("worse", 50, 99.0)
    monkeypatch.setattr(registry, "create_providers", lambda: [good, worse])
    monkeypatch.setattr(
        registry,
        "provider_report",
        lambda: [("good", True, ""), ("worse", True, ""), ("lhm", False, "service missing")],
    )
    text = diagnostics.sensors_report(delay=0)
    assert "lhm" in text and "off (service missing)" in text
    line = [ln for ln in text.splitlines() if ln.strip().startswith("cpu.temp")][0]
    assert "42.0" in line and "from good" in line
    assert "99.0" not in text


def test_sensors_report_survives_failing_provider(monkeypatch):
    class Bad(_Fake):
        def read(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(registry, "create_providers", lambda: [Bad("bad", 1, 0)])
    monkeypatch.setattr(registry, "provider_report", lambda: [("bad", True, "")])
    assert "boom" in diagnostics.sensors_report(delay=0)


class _Backend:
    def __init__(self, name, priority):
        self.name = name
        self.priority = priority


class _Hub(SensorProvider):
    name = "gpu"
    priority = 40

    def __init__(self):
        self.backend_report = [
            ("nvidia", False, "NVML not available"),
            ("windows_gpu", True, ""),
        ]
        self.backends = [_Backend("windows_gpu", 60)]
        self.names = {}
        self.extra = {}

    def read(self):
        self.names = {"gpu": "NVIDIA GeForce RTX 3060"}
        self.extra = {"gpu": {"fan": Reading("gpu.fan", "GPU", 37.0, "%")}}
        return [Reading("gpu.load", "GPU", 12.0, "%")]


class _FanProvider(_Fake):
    def __init__(self):
        super().__init__("sysfs", 20, 40.0)
        self.fans = {}

    def read(self):
        self.fans = {"nct6775/fan2 (CPU)": 1200.0}
        return super().read()


def test_sensors_report_shows_backends_gpus_and_fans(monkeypatch):
    monkeypatch.setattr(registry, "create_providers", lambda: [_Hub(), _FanProvider()])
    monkeypatch.setattr(
        registry, "provider_report", lambda: [("gpu", True, ""), ("sysfs", True, "")]
    )
    lines = diagnostics.sensors_report(delay=0).splitlines()
    assert "    gpu/nvidia       off (NVML not available)" in lines
    assert "    gpu/windows_gpu  running priority 60" in lines
    assert lines.index("    gpu/nvidia       off (NVML not available)") > lines.index("Providers:")
    gpus = lines.index("GPUs:")
    assert gpus > lines.index("Readings (first provider in priority order wins):")
    assert "NVIDIA GeForce RTX 3060" in lines[gpus + 1]
    assert "fan" in lines[gpus + 2] and "37.0" in lines[gpus + 2]
    fans = lines.index("Fans:")
    assert "nct6775/fan2 (CPU)" in lines[fans + 1] and "1200.0" in lines[fans + 1]


def test_sensors_report_omits_empty_sections(monkeypatch):
    monkeypatch.setattr(registry, "create_providers", lambda: [_Fake("good", 10, 42.0)])
    monkeypatch.setattr(registry, "provider_report", lambda: [("good", True, "")])
    text = diagnostics.sensors_report(delay=0)
    assert "GPUs:" not in text and "Fans:" not in text and "good/" not in text


def test_dump_report_without_psutil_attributes(monkeypatch):
    monkeypatch.delattr(psutil, "sensors_temperatures", raising=False)
    monkeypatch.delattr(psutil, "sensors_fans", raising=False)
    assert isinstance(diagnostics.dump_report(), str)


def test_main_sensors_flag(monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "sensors_report", lambda delay=1.2: "REPORT")
    assert app.main(["--sensors"]) == 0
    assert "REPORT" in capsys.readouterr().out

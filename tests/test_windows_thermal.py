from __future__ import annotations

import pytest

from specter.sensors import windows_thermal
from specter.sensors.windows_thermal import WindowsThermalProvider


class FakeReader:
    def __init__(self, data=None, raises=False):
        self.data = data or {}
        self.raises = raises

    def read(self, path):
        if self.raises:
            raise RuntimeError("boom")
        return dict(self.data)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _windows(monkeypatch):
    monkeypatch.setattr(windows_thermal.sys, "platform", "win32")
    monkeypatch.setattr(windows_thermal.PdhReader, "supported", staticmethod(lambda: True))


def make(data=None, **kw):
    return WindowsThermalProvider(reader=FakeReader(data, **kw), probe_delay=0)


def test_cpu_zone_converted():
    p = make({r"\_TZ.CPUZ": 327.0})
    assert p.is_available()
    (r,) = p.read()
    assert r.key == "cpu.temp" and r.unit == "°C" and r.label == "CPU"
    assert r.value == pytest.approx(53.85)


def test_hottest_cpu_zone_case_insensitive():
    p = make({r"\_TZ.CPUZ": 320.0, r"\_TZ.cpu1": 335.0})
    (r,) = p.read()
    assert r.value == pytest.approx(335.0 - 273.15)


def test_gfx_and_bat_ignored():
    p = make({r"\_TZ.GFXZ": 340.0, r"\_TZ.BATZ": 310.0, r"\_TZ.CPUZ": 300.0})
    (r,) = p.read()
    assert r.value == pytest.approx(300.0 - 273.15)
    assert len(p.read()) == 1


def test_junk_values_filtered():
    p = make({r"\_TZ.CPUZ": 0.0, r"\_TZ.CPU2": 5000.0})
    assert p.read() == []
    assert not p.is_available()


def test_no_cpu_zone_unavailable():
    p = make({r"\_TZ.GFXZ": 330.0})
    assert not p.is_available()
    assert p.unavailable_reason
    assert p.read() == []


def test_reader_raises():
    p = make(raises=True)
    assert p.read() == []
    assert not p.is_available()
    assert p.unavailable_reason


def test_not_windows(monkeypatch):
    monkeypatch.setattr(windows_thermal.sys, "platform", "linux")
    p = make({r"\_TZ.CPUZ": 327.0})
    assert not p.is_available()
    assert "Windows" in p.unavailable_reason


def test_pdh_unsupported(monkeypatch):
    monkeypatch.setattr(windows_thermal.PdhReader, "supported", staticmethod(lambda: False))
    p = make({r"\_TZ.CPUZ": 327.0})
    assert not p.is_available()
    assert p.unavailable_reason


def test_priority_and_name():
    p = make()
    assert p.name == "windows_thermal" and p.priority == 70

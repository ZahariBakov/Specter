from __future__ import annotations

from collections import namedtuple

from specter.sensors import linux_hwmon
from specter.sensors.linux_hwmon import LinuxHwmonProvider

Temp = namedtuple("Temp", "label current high critical")
Fan = namedtuple("Fan", "label current")


def _fake(monkeypatch, temps, fans):
    monkeypatch.setattr(linux_hwmon.psutil, "sensors_temperatures", lambda: temps)
    monkeypatch.setattr(linux_hwmon.psutil, "sensors_fans", lambda: fans, raising=False)
    monkeypatch.setattr(linux_hwmon.sys, "platform", "linux")


def _values(provider):
    return {r.key: r.value for r in provider.read()}


def test_intel_coretemp_and_spinning_fan(monkeypatch):
    _fake(
        monkeypatch,
        temps={
            "acpitz": [Temp("", 27.8, None, None)],
            "coretemp": [Temp("Core 0", 40.0, 80, 100), Temp("Package id 0", 47.0, 80, 100)],
        },
        fans={"nct6106": [Fan("", 2694), Fan("", 0), Fan("", 0)]},
    )
    provider = LinuxHwmonProvider()
    assert provider.is_available()
    assert _values(provider) == {"cpu.temp": 47.0, "fan.rpm": 2694.0}


def test_amd_tctl_without_fans(monkeypatch):
    _fake(monkeypatch, temps={"k10temp": [Temp("Tctl", 61.5, None, None)]}, fans={})
    assert _values(LinuxHwmonProvider()) == {"cpu.temp": 61.5}


def test_fastest_fan_wins(monkeypatch):
    _fake(monkeypatch, temps={}, fans={"it8728": [Fan("", 900), Fan("", 1500)]})
    assert _values(LinuxHwmonProvider()) == {"fan.rpm": 1500.0}


def test_nothing_found_means_unavailable(monkeypatch):
    _fake(monkeypatch, temps={}, fans={"nct6106": [Fan("", 0)]})
    assert not LinuxHwmonProvider().is_available()


def test_unavailable_off_linux(monkeypatch):
    _fake(monkeypatch, temps={"coretemp": [Temp("Package id 0", 50.0, None, None)]}, fans={})
    monkeypatch.setattr(linux_hwmon.sys, "platform", "win32")
    assert not LinuxHwmonProvider().is_available()

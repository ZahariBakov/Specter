from __future__ import annotations

import json
import os

import pytest

from specter.sensors import lhm_client
from specter.sensors.lhm_client import LhmClient, LhmSensor, parse_tree, parse_value

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def raw(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def find(sensors, hardware, type_, name):
    hits = [s for s in sensors if s.hardware == hardware and s.type == type_ and s.name == name]
    assert len(hits) == 1, (hardware, type_, name, hits)
    return hits[0]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("45.0 °C", (45.0, "°C")),
        ("45,0 °C", (45.0, "°C")),
        ("1234 RPM", (1234.0, "RPM")),
        ("1 234 RPM", (1234.0, "RPM")),
        ("1 234 RPM", (1234.0, "RPM")),
        ("12.3 %", (12.3, "%")),
        ("1.2 GB", (1.2, "GB")),
        ("1,234.5 MHz", (1234.5, "MHz")),
        ("1.234,5 MHz", (1234.5, "MHz")),
        ("-12.5 °C", (-12.5, "°C")),
        ("0 RPM", (0.0, "RPM")),
        ("7", (7.0, "")),
        ("  3.3 V  ", (3.3, "V")),
    ],
)
def test_parse_value(text, expected):
    value, unit = parse_value(text)
    assert value == pytest.approx(expected[0])
    assert unit == expected[1]


@pytest.mark.parametrize("text", ["-", "", "   ", "n/a", None, "°C", [1]])
def test_parse_value_rejects(text):
    assert parse_value(text) is None


def test_parse_intel_nvidia():
    sensors = parse_tree(load("lhm_intel_nvidia.json"))
    assert all(isinstance(s, LhmSensor) for s in sensors)

    pkg = find(sensors, "Intel Core i7-12700K", "Temperature", "CPU Package")
    assert (pkg.kind, pkg.value, pkg.unit) == ("cpu", 45.0, "°C")
    assert find(sensors, "Intel Core i7-12700K", "Load", "CPU Total").value == 12.3
    assert find(sensors, "Intel Core i7-12700K", "Power", "CPU Package").unit == "W"

    gpu = find(sensors, "NVIDIA GeForce RTX 3060", "Temperature", "GPU Core")
    assert (gpu.kind, gpu.value) == ("gpu-nvidia", 52.0)
    assert find(sensors, "NVIDIA GeForce RTX 3060", "Fan", "GPU Fan 1").value == 1350.0
    mem = find(sensors, "NVIDIA GeForce RTX 3060", "SmallData", "GPU Memory Used")
    assert (mem.value, mem.unit) == (1234.0, "MB")
    # "-" value is skipped
    assert not [s for s in sensors if s.name == "GPU Hot Spot"]

    # Super-I/O child keeps its own name and kind
    fans = [s for s in sensors if s.type == "Fan" and s.kind == "superio"]
    assert {s.hardware for s in fans} == {"Nuvoton NCT6798D"}
    assert sorted(s.value for s in fans) == [0.0, 842.0, 1123.0]
    assert find(sensors, "Nuvoton NCT6798D", "Control", "Fan #1").value == 45.1
    assert find(sensors, "Nuvoton NCT6798D", "Voltage", "Vcore").unit == "V"

    assert find(sensors, "Generic Memory", "Data", "Memory Used").kind == "memory"
    assert find(sensors, "Samsung SSD 980 PRO 1TB", "Temperature", "Temperature").kind == "storage"
    # Root / computer / group nodes never become sensors
    assert not [s for s in sensors if s.hardware in ("Sensor", "DESKTOP-TEST")]


def test_parse_amd_decimal_comma():
    sensors = parse_tree(load("lhm_amd.json"))
    tctl = find(sensors, "AMD Ryzen 7 5800X", "Temperature", "Core (Tctl/Tdie)")
    assert (tctl.kind, tctl.value, tctl.unit) == ("cpu", pytest.approx(48.3), "°C")
    assert find(sensors, "AMD Ryzen 7 5800X", "Temperature", "CCD1 (Tdie)").value == 44.8
    assert find(sensors, "AMD Ryzen 7 5800X", "Load", "CPU Total").value == 21.6

    hot = find(sensors, "AMD Radeon RX 6700 XT", "Temperature", "GPU Hot Spot")
    assert (hot.kind, hot.value) == ("gpu-amd", 61.0)
    assert find(sensors, "AMD Radeon RX 6700 XT", "Fan", "GPU Fan").value == 0.0

    cpu_fan = find(sensors, "Nuvoton NCT6795D", "Fan", "CPU Fan")
    assert (cpu_fan.kind, cpu_fan.value) == ("superio", 1034.0)


def test_parse_old_ohm_without_ids():
    sensors = parse_tree(load("lhm_old_ohm.json"))
    pkg = find(sensors, "Intel Core i5-4460", "Temperature", "CPU Package")
    assert (pkg.kind, pkg.value) == ("cpu", 41.0)
    assert find(sensors, "Intel Core i5-4460", "Load", "CPU Total").value == 9.4
    gpu = find(sensors, "NVIDIA GeForce GTX 750 Ti", "Clock", "GPU Core")
    assert (gpu.kind, gpu.value, gpu.unit) == ("gpu-nvidia", 135.0, "MHz")
    fan = find(sensors, "ITE IT8620E", "Fan", "Fan #1")
    assert (fan.kind, fan.value) == ("superio", 1012.0)
    assert find(sensors, "WDC WD10EZEX-08WN4A0", "Temperature", "Temperature").kind == "storage"


def test_kind_from_sensor_id_beats_image():
    tree = {
        "Text": "Sensor",
        "Children": [
            {
                "Text": "PC",
                "ImageURL": "images_icon/computer.png",
                "Children": [
                    {
                        "Text": "Mystery GPU",
                        "ImageURL": "images_icon/unknown.png",
                        "Children": [
                            {
                                "Text": "Temperatures",
                                "Children": [
                                    {"Text": "A", "Value": "50 °C", "SensorId": "/atigpu/0/temperature/0"},
                                    {"Text": "B", "Value": "51 °C", "SensorId": "/nvidiagpu/0/temperature/0"},
                                    {"Text": "C", "Value": "52 °C", "SensorId": "/gpu-intel/0/temperature/0"},
                                    {"Text": "D", "Value": "53 °C"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    kinds = {s.name: s.kind for s in parse_tree(tree)}
    assert kinds == {"A": "gpu-amd", "B": "gpu-nvidia", "C": "gpu-intel", "D": "other"}


@pytest.mark.parametrize("bad", [None, [], "x", 3, {"Children": "nope"}, {"Children": [1, None]}])
def test_parse_tree_garbage(bad):
    assert parse_tree(bad) == []


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeFetch:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_client_caches_for_ttl():
    clock = FakeClock()
    fetch = FakeFetch(raw("lhm_intel_nvidia.json"))
    client = LhmClient(url="http://x/data.json", ttl=0.5, clock=clock, fetch=fetch)
    first = client.sensors()
    assert first and client.reachable and client.last_error is None
    clock.t += 0.3
    assert client.sensors() == first
    assert len(fetch.calls) == 1
    clock.t += 0.3
    client.sensors()
    assert len(fetch.calls) == 2
    assert fetch.calls[0] == ("http://x/data.json", 0.5)


def test_client_backoff_and_recovery():
    clock = FakeClock()
    fetch = FakeFetch(OSError("connection refused"))
    client = LhmClient(url="http://x/", retry_after=15.0, clock=clock, fetch=fetch)
    assert client.sensors() == []
    assert client.reachable is False
    assert "connection refused" in client.last_error
    clock.t += 10
    assert client.sensors() == []
    assert len(fetch.calls) == 1  # no retry inside the back-off window

    fetch.payload = raw("lhm_amd.json")
    clock.t += 5.1
    sensors = client.sensors()
    assert len(fetch.calls) == 2
    assert sensors and client.reachable and client.last_error is None


def test_client_failure_drops_cache():
    clock = FakeClock()
    fetch = FakeFetch(raw("lhm_amd.json"))
    client = LhmClient(url="http://x/", ttl=0.5, clock=clock, fetch=fetch)
    assert client.sensors()
    fetch.payload = OSError("gone")
    clock.t += 1
    assert client.sensors() == []
    assert client.reachable is False


@pytest.mark.parametrize("payload", [b"{not json", b"[1, 2]", b"\xff\xfe", b""])
def test_client_bad_payload(payload):
    client = LhmClient(url="http://x/", clock=FakeClock(), fetch=FakeFetch(payload))
    assert client.sensors() == []
    assert client.reachable is False
    assert client.last_error


def test_client_never_raises_on_broken_clock():
    def clock():
        raise RuntimeError("boom")

    client = LhmClient(url="http://x/", clock=clock, fetch=FakeFetch(b"{}"))
    assert client.sensors() == []


def test_client_utf8_bom():
    data = b"\xef\xbb\xbf" + raw("lhm_old_ohm.json")
    client = LhmClient(url="http://x/", clock=FakeClock(), fetch=FakeFetch(data))
    assert client.sensors()


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("SPECTER_LHM_URL", "http://192.168.1.5:9000/data.json")
    fetch = FakeFetch(b"{}")
    client = LhmClient(clock=FakeClock(), fetch=fetch)
    client.sensors()
    assert fetch.calls[0][0] == "http://192.168.1.5:9000/data.json"


def test_default_url(monkeypatch):
    monkeypatch.delenv("SPECTER_LHM_URL", raising=False)
    assert LhmClient().url == lhm_client.DEFAULT_URL == "http://localhost:8085/data.json"


def test_default_fetch_unreachable_does_not_raise(monkeypatch):
    monkeypatch.delenv("SPECTER_LHM_URL", raising=False)
    # Port 9 on localhost is almost never served; any error must be swallowed.
    client = LhmClient(url="http://127.0.0.1:9/data.json", timeout=0.2)
    assert client.sensors() == []
    assert client.reachable is False

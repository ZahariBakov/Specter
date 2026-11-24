from __future__ import annotations

from specter.core.models import Reading
from specter.core.poller import Poller
from specter.sensors import registry
from specter.sensors.base import SensorProvider


def _reading(value: float) -> Reading:
    return Reading(key="cpu.temp", label="CPU", value=value, unit="C")


class Good(SensorProvider):
    name = "good"
    priority = 10

    def read(self):
        return [_reading(1.0)]


class Meh(SensorProvider):
    name = "meh"
    priority = 60

    def read(self):
        return [_reading(2.0)]


class Missing(SensorProvider):
    name = "missing"

    def is_available(self) -> bool:
        self.unavailable_reason = "driver not installed"
        return False

    def read(self):
        return []


class Broken(SensorProvider):
    name = "broken"

    def __init__(self) -> None:
        raise RuntimeError("boom")

    def read(self):
        return []


def test_sort_by_priority_is_stable():
    meh, good, meh2 = Meh(), Good(), Meh()
    assert registry.sort_providers([meh, good, meh2]) == [good, meh, meh2]


def test_create_providers_sorts(monkeypatch):
    monkeypatch.setattr(registry, "_candidates", lambda: [Meh, Missing, Good])
    providers = registry.create_providers()
    assert [p.name for p in providers] == ["good", "meh"]


def test_poll_once_first_wins():
    poller = Poller([Good(), Meh()], lambda s: None)
    assert poller.poll_once().readings["cpu.temp"].value == 1.0
    poller = Poller([Meh(), Good()], lambda s: None)
    assert poller.poll_once().readings["cpu.temp"].value == 2.0


def test_registry_order_then_poll_prefers_better(monkeypatch):
    monkeypatch.setattr(registry, "_candidates", lambda: [Meh, Good])
    poller = Poller(registry.create_providers(), lambda s: None)
    assert poller.poll_once().readings["cpu.temp"].value == 1.0


def test_provider_report_reasons(monkeypatch):
    monkeypatch.setattr(registry, "_candidates", lambda: [Good, Missing, Broken])
    report = registry.provider_report()
    assert report[0] == ("good", True, "")
    assert report[1] == ("missing", False, "driver not installed")
    assert report[2][0] == "broken"
    assert report[2][1] is False
    assert "boom" in report[2][2]

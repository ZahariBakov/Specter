from specter.config import Config
from specter.sensors import create_providers


def test_system_provider_returns_cpu_and_ram():
    providers = create_providers()
    readings = {r.key: r for p in providers for r in p.read()}
    assert "cpu.load" in readings
    assert "ram.used" in readings
    assert 0 <= readings["cpu.load"].value <= 100
    assert 0 < readings["ram.used"].value <= readings["ram.used"].maximum


def test_config_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    Config(opacity=0.5, pos_x=10, pos_y=20).save(path)
    loaded = Config.load(path)
    assert (loaded.opacity, loaded.pos_x, loaded.pos_y) == (0.5, 10, 20)


def test_config_clamps_bad_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"opacity": 5, "interval_ms": 1, "unknown": true}')
    loaded = Config.load(path)
    assert loaded.opacity == 1.0
    assert loaded.interval_ms == 250


def test_poller_collects_from_all_providers():
    from specter.core.models import Reading
    from specter.core.poller import Poller
    from specter.sensors.base import SensorProvider

    class Fake(SensorProvider):
        name = "fake"

        def read(self):
            return [Reading("fake.temp", "Fake", 42.0, "°C")]

    class Broken(SensorProvider):
        name = "broken"

        def read(self):
            raise RuntimeError("sensor gone")

    snapshot = Poller([Fake(), Broken()], on_snapshot=lambda s: None).poll_once()
    assert snapshot.readings["fake.temp"].value == 42.0

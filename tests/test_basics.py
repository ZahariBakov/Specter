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


def test_config_size_needs_both_values(tmp_path):
    path = tmp_path / "config.json"
    Config(width=300, height=120).save(path)
    assert (Config.load(path).width, Config.load(path).height) == (300, 120)
    path.write_text('{"width": 300}')
    assert (Config.load(path).width, Config.load(path).height) == (None, None)


def test_config_new_settings_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    Config(hidden_tiles=["net"], locked=True, topmost=False, sparklines=True).save(path)
    loaded = Config.load(path)
    assert (loaded.hidden_tiles, loaded.locked, loaded.topmost) == (["net"], True, False)
    assert loaded.sparklines is True


def test_old_config_without_new_settings_uses_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"opacity": 0.7, "pos_x": 5, "pos_y": 6}')
    loaded = Config.load(path)
    assert loaded.opacity == 0.7
    assert loaded.hidden_tiles == ["disk", "fan"]
    assert (loaded.locked, loaded.topmost, loaded.sparklines) == (False, True, False)


def test_config_ignores_bad_new_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"hidden_tiles": "cpu", "locked": 1}')
    assert Config.load(path).hidden_tiles == ["disk", "fan"]
    path.write_text('{"hidden_tiles": ["cpu", 3, null]}')
    assert Config.load(path).hidden_tiles == ["cpu"]
    path.write_text("[1, 2]")
    assert Config.load(path) == Config()


def test_poller_interval_can_change():
    from specter.core.poller import Poller

    poller = Poller([], on_snapshot=lambda s: None, interval_ms=1000)
    poller.set_interval(500)
    assert poller._interval == 0.5
    poller.set_interval(10)  # too fast: limited to 250 ms
    assert poller._interval == 0.25


def test_config_first_tile(tmp_path):
    path = tmp_path / "config.json"
    assert Config.load(path).first_tile is None
    Config(first_tile="ram").save(path)
    assert Config.load(path).first_tile == "ram"
    path.write_text('{"first_tile": 5}')
    assert Config.load(path).first_tile is None

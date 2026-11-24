from __future__ import annotations

from specter.sensors import linux_sysfs
from specter.sensors.linux_sysfs import LinuxSysfsProvider


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text))


def _hwmon(root, n, name, temps=None, fans=None, sub=""):
    """temps/fans: {index: (label or "", value)}; values are raw sysfs numbers."""
    base = "class/hwmon/hwmon%d/" % n
    _write(root, base + sub + "name", name + "\n")
    for i, (label, value) in (temps or {}).items():
        _write(root, base + sub + "temp%d_input" % i, value)
        if label:
            _write(root, base + sub + "temp%d_label" % i, label + "\n")
    for i, (label, value) in (fans or {}).items():
        _write(root, base + sub + "fan%d_input" % i, value)
        if label:
            _write(root, base + sub + "fan%d_label" % i, label)


def _zone(root, n, zone_type, millideg):
    _write(root, "class/thermal/thermal_zone%d/type" % n, zone_type + "\n")
    _write(root, "class/thermal/thermal_zone%d/temp" % n, millideg)


def _provider(root):
    return LinuxSysfsProvider(str(root), check_platform=False)


def _values(root):
    return {r.key: r.value for r in _provider(root).read()}


def test_intel_coretemp_package(tmp_path):
    _hwmon(tmp_path, 0, "coretemp", {1: ("Package id 0", 47000), 2: ("Core 0", 52000)})
    readings = _provider(tmp_path).read()
    assert [(r.key, r.label, r.value, r.unit) for r in readings] == [("cpu.temp", "CPU", 47.0, "°C")]


def test_coretemp_hottest_package(tmp_path):
    _hwmon(tmp_path, 0, "coretemp", {1: ("Package id 0", 47000), 5: ("Package id 1", 55000)})
    assert _values(tmp_path) == {"cpu.temp": 55.0}


def test_coretemp_without_package_uses_hottest_core(tmp_path):
    _hwmon(tmp_path, 0, "coretemp", {2: ("Core 0", 40000), 3: ("Core 1", 44000)})
    assert _values(tmp_path) == {"cpu.temp": 44.0}


def test_amd_k10temp_tctl(tmp_path):
    _hwmon(tmp_path, 1, "k10temp", {1: ("Tctl", 61500), 3: ("Tccd1", 70000)})
    assert _values(tmp_path) == {"cpu.temp": 61.5}


def test_k10temp_tccd_only(tmp_path):
    _hwmon(tmp_path, 1, "k10temp", {3: ("Tccd1", 50000), 4: ("Tccd2", 58000)})
    assert _values(tmp_path) == {"cpu.temp": 58.0}


def test_zenpower(tmp_path):
    _hwmon(tmp_path, 0, "zenpower", {1: ("Tctl", 60000), 2: ("Tdie", 50000)})
    assert _values(tmp_path) == {"cpu.temp": 50.0}


def test_raspberry_pi_cpu_thermal(tmp_path):
    _hwmon(tmp_path, 0, "cpu_thermal", {1: ("", 48300)})
    assert _values(tmp_path) == {"cpu.temp": 48.3}


def test_x86_pkg_temp_thermal_zone(tmp_path):
    _zone(tmp_path, 0, "acpitz", 27800)
    _zone(tmp_path, 1, "x86_pkg_temp", 45000)
    assert _values(tmp_path) == {"cpu.temp": 45.0}


def test_acpitz_last_resort(tmp_path):
    _hwmon(tmp_path, 0, "acpitz", {1: ("", 27800)})
    assert _values(tmp_path) == {"cpu.temp": 27.8}


def test_acpitz_thermal_zone_last_resort(tmp_path):
    _zone(tmp_path, 0, "acpitz", 30000)
    assert _values(tmp_path) == {"cpu.temp": 30.0}


def test_coretemp_beats_acpitz(tmp_path):
    _hwmon(tmp_path, 0, "acpitz", {1: ("", 27800)})
    _hwmon(tmp_path, 1, "nvme", {1: ("Composite", 38000)})
    _hwmon(tmp_path, 2, "coretemp", {1: ("Package id 0", 47000)})
    _zone(tmp_path, 0, "x86_pkg_temp", 46000)
    assert _values(tmp_path) == {"cpu.temp": 47.0}


def test_files_under_device(tmp_path):
    _hwmon(tmp_path, 0, "coretemp", {1: ("Package id 0", 47000)}, sub="device/")
    assert _values(tmp_path) == {"cpu.temp": 47.0}


def test_junk_values_ignored(tmp_path):
    _hwmon(tmp_path, 0, "coretemp", {1: ("Package id 0", 255000), 2: ("Core 0", 41000), 3: ("Core 1", "junk")})
    _hwmon(tmp_path, 1, "nct6106", fans={1: ("", "garbage")})
    assert _values(tmp_path) == {"cpu.temp": 41.0}


def test_fans_fastest_wins_zero_ignored_gpu_excluded(tmp_path):
    _hwmon(tmp_path, 0, "nct6106", fans={1: ("", 900), 2: ("", 0), 3: ("CPU fan", 1500)})
    _hwmon(tmp_path, 1, "amdgpu", temps={1: ("edge", 50000)}, fans={1: ("", 3000)})
    _hwmon(tmp_path, 2, "thinkpad", fans={1: ("", 2100)})
    provider = _provider(tmp_path)
    assert {r.key: r.value for r in provider.read()} == {"fan.rpm": 2100.0}
    assert provider.fans == {
        "nct6106/fan1": 900.0,
        "nct6106/fan3 (CPU fan)": 1500.0,
        "thinkpad/fan1": 2100.0,
    }
    reading = provider.read()[0]
    assert (reading.label, reading.unit) == ("Fan", "RPM")


def test_nothing_found_means_unavailable(tmp_path):
    _hwmon(tmp_path, 0, "nct6106", fans={1: ("", 0)})
    _hwmon(tmp_path, 1, "amdgpu", fans={1: ("", 2000)})
    provider = _provider(tmp_path)
    assert not provider.is_available()
    assert provider.unavailable_reason == "no CPU temperature or fan sensor in /sys"


def test_missing_root_means_unavailable(tmp_path):
    assert not _provider(tmp_path / "nope").is_available()


def test_available_with_sensor(tmp_path):
    _hwmon(tmp_path, 0, "coretemp", {1: ("Package id 0", 47000)})
    provider = _provider(tmp_path)
    assert provider.is_available()
    assert provider.unavailable_reason == ""


def test_unavailable_off_linux(tmp_path, monkeypatch):
    _hwmon(tmp_path, 0, "coretemp", {1: ("Package id 0", 47000)})
    monkeypatch.setattr(linux_sysfs.sys, "platform", "win32")
    provider = LinuxSysfsProvider(str(tmp_path))
    assert not provider.is_available()
    assert provider.unavailable_reason


def test_unreadable_file_does_not_crash(tmp_path):
    _hwmon(tmp_path, 0, "coretemp", {2: ("Core 0", 40000)})
    # A directory where a file should be: reading it raises OSError.
    (tmp_path / "class/hwmon/hwmon0/temp1_input").mkdir()
    _write(tmp_path, "class/hwmon/hwmon0/temp1_label", "Package id 0")
    (tmp_path / "class/hwmon/hwmon1/name").mkdir(parents=True)
    (tmp_path / "class/thermal/thermal_zone0/type").mkdir(parents=True)
    assert _values(tmp_path) == {"cpu.temp": 40.0}

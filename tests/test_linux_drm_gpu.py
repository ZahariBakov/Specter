from __future__ import annotations

import os

from specter.sensors.gpu_types import FAN, FREQ, LOAD, MEM, TEMP, VENDOR_AMD, VENDOR_INTEL
from specter.sensors.linux_drm_gpu import LinuxDrmGpuProvider

GIB = 1024**3


def _w(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w") as fh:
        fh.write(text)


def _card(root, n, driver, slot="0000:03:00.0", vendor="0x1002", device="0x73bf"):
    card = root / "class" / "drm" / ("card%d" % n)
    _w(card / "device" / "uevent", "DRIVER=%s\nPCI_SLOT_NAME=%s\n" % (driver, slot))
    _w(card / "device" / "vendor", vendor + "\n")
    _w(card / "device" / "device", device + "\n")
    return card


def _amd(root, n=0, slot="0000:03:00.0", hwmon=True):
    card = _card(root, n, "amdgpu", slot)
    dev = card / "device"
    _w(dev / "gpu_busy_percent", "42\n")
    _w(dev / "mem_info_vram_used", str(2 * GIB))
    _w(dev / "mem_info_vram_total", str(8 * GIB))
    if hwmon:
        hw = dev / "hwmon" / "hwmon3"
        _w(hw / "temp1_input", "99000")
        _w(hw / "temp1_label", "junction")
        _w(hw / "temp2_input", "55000")
        _w(hw / "temp2_label", "edge")
        _w(hw / "fan1_input", "1200")
    return card


def _provider(root):
    return LinuxDrmGpuProvider(root=str(root), check_platform=False)


def _by_key(readings):
    return {r.key: r for r in readings}


def test_amd_full_set(tmp_path):
    _amd(tmp_path)
    p = _provider(tmp_path)
    assert p.is_available()
    r = _by_key(p.read())
    assert set(r) == {"gpu.load", "gpu.mem", "gpu.temp", "gpu.fan"}
    assert r["gpu.load"].value == 42.0 and r["gpu.load"].unit == "%"
    assert r["gpu.mem"].value == 2.0 and r["gpu.mem"].maximum == 8.0
    assert r["gpu.temp"].value == 55.0  # "edge", not junction
    assert r["gpu.fan"].value == 1200.0 and r["gpu.fan"].unit == "RPM"
    assert r["gpu.load"].label == "GPU"
    assert p.names == {"gpu": "AMD GPU (amdgpu)"}
    assert p.pci == {"gpu": "0000:03:00.0"}


def test_amd_without_hwmon(tmp_path):
    _amd(tmp_path, hwmon=False)
    r = _by_key(_provider(tmp_path).read())
    assert set(r) == {"gpu.load", "gpu.mem"}


def test_amd_temp1_fallback_and_zero_fan(tmp_path):
    card = _amd(tmp_path, hwmon=False)
    hw = card / "device" / "hwmon" / "hwmon0"
    _w(hw / "temp1_input", "61000")
    _w(hw / "fan1_input", "0")
    r = _by_key(_provider(tmp_path).read())
    assert r["gpu.temp"].value == 61.0
    assert "gpu.fan" not in r


def test_intel_i915_freq_approximation(tmp_path):
    card = _card(tmp_path, 0, "i915", "0000:00:02.0", "0x8086", "0x9a49")
    _w(card / "gt_act_freq_mhz", "650")
    _w(card / "gt_cur_freq_mhz", "900")
    _w(card / "gt_max_freq_mhz", "1300")
    p = _provider(tmp_path)
    r = _by_key(p.read())
    assert set(r) == {"gpu.freq"}  # no load, no mem
    f = r["gpu.freq"]
    assert f.value == 50.0 and f.unit == "%" and f.maximum == 100.0 and f.short == "~"
    assert p.names == {"gpu": "Intel GPU (i915)"}


def test_intel_i915_cur_freq_fallback(tmp_path):
    card = _card(tmp_path, 0, "i915")
    _w(card / "gt_cur_freq_mhz", "325")
    _w(card / "gt_max_freq_mhz", "1300")
    assert _by_key(_provider(tmp_path).read())["gpu.freq"].value == 25.0


def test_intel_xe_paths_and_hwmon(tmp_path):
    card = _card(tmp_path, 0, "xe", "0000:03:00.0", "0x8086", "0x56a0")
    freq = card / "device" / "tile0" / "gt0" / "freq0"
    _w(freq / "act_freq", "1200")
    _w(freq / "max_freq", "2400")
    _w(card / "device" / "hwmon" / "hwmon2" / "temp1_input", "48000")
    r = _by_key(_provider(tmp_path).read())
    assert r["gpu.freq"].value == 50.0
    assert r["gpu.temp"].value == 48.0
    assert "gpu.load" not in r and "gpu.mem" not in r


def test_intel_igpu_plus_amd_dgpu(tmp_path):
    card = _card(tmp_path, 0, "i915", "0000:00:02.0", "0x8086", "0x9a49")
    _w(card / "gt_act_freq_mhz", "300")
    _w(card / "gt_max_freq_mhz", "1200")
    _amd(tmp_path, n=1, slot="0000:03:00.0")
    p = _provider(tmp_path)
    r = _by_key(p.read())
    assert r["gpu0.freq"].value == 25.0 and r["gpu0.freq"].label == "GPU 0"
    assert r["gpu1.load"].value == 42.0 and r["gpu1.load"].label == "GPU 1"
    assert p.names == {"gpu0": "Intel GPU (i915)", "gpu1": "AMD GPU (amdgpu)"}
    assert p.pci == {"gpu0": "0000:00:02.0", "gpu1": "0000:03:00.0"}


def test_devices_filled(tmp_path):
    card = _card(tmp_path, 0, "i915", "0000:00:02.0", "0x8086", "0x9a49")
    _w(card / "gt_act_freq_mhz", "300")
    _w(card / "gt_max_freq_mhz", "1200")
    _amd(tmp_path, n=1, slot="00000000:03:00.0")
    igpu, dgpu = _provider(tmp_path).devices()
    assert (igpu.name, igpu.vendor, igpu.pci, igpu.integrated) == (
        "Intel GPU (i915)",
        VENDOR_INTEL,
        "0000:00:02.0",
        True,
    )
    assert set(igpu.metrics) == {FREQ}
    f = igpu.metrics[FREQ]
    assert (f.value, f.unit, f.maximum, f.short) == (25.0, "%", 100.0, "~")
    assert (dgpu.name, dgpu.vendor, dgpu.pci, dgpu.integrated) == (
        "AMD GPU (amdgpu)",
        VENDOR_AMD,
        "0000:03:00.0",
        False,
    )
    m = dgpu.metrics
    assert set(m) == {LOAD, MEM, TEMP, FAN}
    assert m[LOAD].value == 42.0 and (m[MEM].value, m[MEM].maximum) == (2.0, 8.0)
    assert m[TEMP].value == 55.0 and (m[FAN].value, m[FAN].unit) == (1200.0, "RPM")


def test_devices_integrated_unknown(tmp_path):
    card = _amd(tmp_path, hwmon=False)
    _w(card / "device" / "mem_info_vram_total", str(512 * 1024**2))  # APU carve-out
    (dev,) = _provider(tmp_path).devices()
    assert dev.integrated is None


def test_devices_garbage_and_nothing(tmp_path):
    assert _provider(tmp_path).devices() == []
    _card(tmp_path, 0, "amdgpu", vendor="zzz", device="")
    (dev,) = _provider(tmp_path).devices()
    assert dev.vendor == "" and dev.metrics == {} and dev.integrated is None


def test_nvidia_card_skipped(tmp_path):
    _card(tmp_path, 0, "nvidia", "0000:01:00.0", "0x10de", "0x1fb1")
    _amd(tmp_path, n=1)
    p = _provider(tmp_path)
    r = _by_key(p.read())
    assert "gpu.load" in r  # the only kept card -> plain "gpu"
    assert not any(k.startswith("gpu0") or k.startswith("gpu1") for k in r)


def test_only_nvidia_or_nouveau_is_unavailable(tmp_path):
    _card(tmp_path, 0, "nvidia")
    _card(tmp_path, 1, "nouveau")
    p = _provider(tmp_path)
    assert not p.is_available()
    assert p.unavailable_reason
    assert p.read() == []


def test_connector_dirs_ignored(tmp_path):
    _amd(tmp_path)
    drm = tmp_path / "class" / "drm"
    _w(drm / "card0-HDMI-A-1" / "device" / "uevent", "DRIVER=amdgpu\n")
    _w(drm / "renderD128" / "device" / "uevent", "DRIVER=amdgpu\n")
    _w(drm / "version", "drm 1.1.0\n")
    p = _provider(tmp_path)
    assert set(_by_key(p.read())) == {"gpu.load", "gpu.mem", "gpu.temp", "gpu.fan"}


def test_garbage_contents(tmp_path):
    card = _card(tmp_path, 0, "amdgpu", vendor="zzz", device="")
    dev = card / "device"
    _w(dev / "gpu_busy_percent", "busy\n")
    _w(dev / "mem_info_vram_used", "")
    _w(dev / "mem_info_vram_total", "0")
    hw = dev / "hwmon" / "hwmon0"
    _w(hw / "temp1_input", "hot")
    _w(hw / "fan1_input", "-")
    os.makedirs(str(dev / "hwmon" / "hwmon1" / "temp1_input"))  # a dir, not a file
    p = _provider(tmp_path)
    assert p.is_available()
    assert p.read() == []


def test_nothing_is_unavailable(tmp_path):
    p = _provider(tmp_path)
    assert not p.is_available()
    assert "no AMD or Intel GPU" in p.unavailable_reason
    assert p.read() == []


def test_platform_check(tmp_path, monkeypatch):
    _amd(tmp_path)
    monkeypatch.setattr("specter.sensors.linux_drm_gpu.sys.platform", "win32")
    p = LinuxDrmGpuProvider(root=str(tmp_path))
    assert not p.is_available()
    assert "Linux" in p.unavailable_reason

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from specter.sensors import windows_dxgi as dx


def _desc(name="GPU", high=0, low=1, flags=0, vendor=0x8086):
    return SimpleNamespace(
        Description=name,
        VendorId=vendor,
        DedicatedVideoMemory=1024,
        SharedSystemMemory=2048,
        AdapterLuid=SimpleNamespace(HighPart=high, LowPart=low),
        Flags=flags,
    )


def test_luid_key():
    assert dx.luid_key(0xD6A1) == "luid_0x00000000_0x0000d6a1"
    assert dx.luid_key((0x1 << 32) | 0xABCD) == "luid_0x00000001_0x0000abcd"


def test_vendor_name():
    assert dx.vendor_name(0x10DE) == "NVIDIA"
    assert dx.vendor_name(0x1002) == "AMD"
    assert dx.vendor_name(0x8086) == "Intel"
    assert dx.vendor_name(0x1234) == "0x1234"


def test_parse_desc_fields_and_luid():
    a = dx.parse_desc(_desc("Intel(R) Iris(R) Xe\x00", high=2, low=0xD6A1))
    assert a.name == "Intel(R) Iris(R) Xe"
    assert a.luid == (2 << 32) | 0xD6A1
    assert dx.luid_key(a.luid) == "luid_0x00000002_0x0000d6a1"
    assert (a.dedicated_bytes, a.shared_bytes, a.software) == (1024, 2048, False)


def test_software_flag():
    assert dx.parse_desc(_desc(flags=2)).software
    assert dx.parse_desc(_desc(name="Microsoft Basic Render Driver")).software
    assert not dx.parse_desc(_desc(flags=1)).software


def test_negative_luid_high_is_unsigned():
    a = dx.parse_desc(_desc(high=-1, low=0))
    assert a.luid == 0xFFFFFFFF00000000


def test_list_adapters_never_raises(monkeypatch):
    def boom():
        raise OSError("nope")

    monkeypatch.setattr(dx, "_list_adapters_win", boom)
    monkeypatch.setattr(dx, "supported", lambda: True)
    assert dx.list_adapters() == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_live_adapters():
    adapters = dx.list_adapters()
    assert adapters
    assert adapters[0].name

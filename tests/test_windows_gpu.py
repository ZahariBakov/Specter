from __future__ import annotations

import pytest

from specter.sensors.gpu_types import LOAD, MEM, VENDOR_INTEL, VENDOR_NVIDIA
from specter.sensors.windows_dxgi import Adapter
from specter.sensors.windows_gpu import DEDICATED_PATH, ENGINE_PATH, SHARED_PATH, WindowsGpuProvider

GIB = 1024**3


class FakeReader:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def read(self, path):
        self.calls.append(path)
        return dict(self.data.get(path, {}))


class BoomReader:
    def read(self, path):
        raise RuntimeError("boom")


def eng(pid, luid, typ):
    return "pid_%d_luid_%s_phys_0_eng_0_engtype_%s" % (pid, luid, typ)


IGPU = Adapter("Intel Iris Xe", 0x15D4D, 0x8086, 128 * 1024**2, 8 * GIB, False)
DGPU = Adapter("NVIDIA T600", 0x20000, 0x10DE, 4 * GIB, 16 * GIB, False)
SOFT = Adapter("Microsoft Basic Render Driver", 0x1, 0x1414, 0, 8 * GIB, True)


def make(adapters, data):
    reader = FakeReader(data)
    return WindowsGpuProvider(reader=reader, adapters_fn=lambda: adapters), reader


def by_key(readings):
    return {r.key: r for r in readings}


def test_igpu_sum_pids_max_types_shared_memory():
    l = "0x00000000_0x00015D4D"
    data = {
        ENGINE_PATH: {
            eng(1, l, "3D"): 10.0,
            eng(2, l, "3D"): 15.0,
            eng(3, l, "VideoDecode"): 20.0,
            eng(4, l, ""): 99.0,
        },
        DEDICATED_PATH: {"luid_0x00000000_0x00015D4D_phys_0": 1 * GIB},
        SHARED_PATH: {"luid_0x00000000_0x00015D4D_phys_0": 2 * GIB},
    }
    p, reader = make([IGPU], data)
    assert p.is_available()
    r = by_key(p.read())
    assert r["gpu.load"].value == 25.0 and r["gpu.load"].unit == "%" and r["gpu.load"].maximum == 100.0
    assert r["gpu.load"].label == "GPU"
    assert r["gpu.mem"].value == pytest.approx(3.0)
    assert r["gpu.mem"].maximum == pytest.approx(8.125)
    assert p.names == {"gpu": "Intel Iris Xe"}
    assert sorted(reader.calls) == sorted([ENGINE_PATH, DEDICATED_PATH, SHARED_PATH])


def test_dgpu_dedicated_memory_and_clamp():
    l = "0x00000000_0x00020000"
    data = {
        ENGINE_PATH: {eng(1, l, "3D"): 80.0, eng(2, l, "3D"): 70.0},
        DEDICATED_PATH: {"luid_0x00000000_0x00020000_phys_0": 2 * GIB},
        SHARED_PATH: {"luid_0x00000000_0x00020000_phys_0": 5 * GIB},
    }
    p, _ = make([DGPU], data)
    r = by_key(p.read())
    assert r["gpu.load"].value == 100.0
    assert r["gpu.mem"].value == pytest.approx(2.0)
    assert r["gpu.mem"].maximum == pytest.approx(4.0)


def test_two_adapters_case_insensitive_luid():
    data = {
        ENGINE_PATH: {
            eng(1, "0x00000000_0x00015d4d", "3D"): 12.0,  # lower case
            eng(2, "0x00000000_0x00020000", "Compute_0"): 40.0,
        },
        DEDICATED_PATH: {"luid_0x00000000_0x00020000_phys_0": 1 * GIB},
    }
    p, _ = make([IGPU, DGPU], data)
    r = by_key(p.read())
    assert r["gpu0.load"].value == 12.0 and r["gpu0.load"].label == "GPU 0"
    assert r["gpu1.load"].value == 40.0 and r["gpu1.load"].label == "GPU 1"
    assert "gpu1.mem" in r and "gpu0.mem" not in r
    assert p.names == {"gpu0": "Intel Iris Xe", "gpu1": "NVIDIA T600"}


def test_devices_filled():
    data = {
        ENGINE_PATH: {
            eng(1, "0x00000000_0x00015D4D", "3D"): 12.0,
            eng(2, "0x00000000_0x00020000", "3D"): 40.0,
        },
        DEDICATED_PATH: {"luid_0x00000000_0x00020000_phys_0": 1 * GIB},
    }
    p, _ = make([SOFT, IGPU, DGPU], data)
    igpu, dgpu = p.devices()
    assert (igpu.name, igpu.vendor, igpu.pci, igpu.integrated) == ("Intel Iris Xe", VENDOR_INTEL, None, True)
    assert (dgpu.name, dgpu.vendor, dgpu.pci, dgpu.integrated) == ("NVIDIA T600", VENDOR_NVIDIA, None, False)
    assert set(igpu.metrics) == {LOAD} and igpu.metrics[LOAD].value == 12.0
    assert dgpu.metrics[LOAD].value == 40.0 and dgpu.metrics[LOAD].maximum == 100.0
    assert dgpu.metrics[MEM].value == pytest.approx(1.0) and dgpu.metrics[MEM].maximum == pytest.approx(4.0)
    assert dgpu.metrics[MEM].unit == "GB"


def test_devices_unknown_vendor_and_errors():
    other = Adapter("Some GPU", 0x30000, 0x1234, 2 * GIB, 0, False)
    p, _ = make([other], {})
    (dev,) = p.devices()
    assert dev.vendor == "" and dev.integrated is False and dev.metrics == {}
    assert WindowsGpuProvider(reader=BoomReader(), adapters_fn=lambda: [IGPU]).devices()[0].metrics == {}
    assert make([SOFT], {})[0].devices() == []


def test_software_adapter_ignored():
    p, _ = make([SOFT, IGPU], {})
    assert p.is_available()
    assert p.names == {"gpu": "Intel Iris Xe"}


def test_only_software_adapter_unavailable():
    p, _ = make([SOFT], {})
    assert not p.is_available()
    assert p.unavailable_reason
    assert p.read() == []


def test_first_read_empty():
    p, _ = make([IGPU], {})
    assert p.read() == []


def test_reader_raises():
    p = WindowsGpuProvider(reader=BoomReader(), adapters_fn=lambda: [IGPU])
    assert p.read() == []


def test_adapters_fn_raises():
    def boom():
        raise OSError("x")

    p = WindowsGpuProvider(reader=FakeReader({}), adapters_fn=boom)
    assert not p.is_available()
    assert p.read() == []

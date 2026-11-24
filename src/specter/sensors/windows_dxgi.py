"""Enumerate GPU adapters on Windows with DXGI (ctypes, no dependencies)."""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Any, List

DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ADAPTER_FLAG_SOFTWARE = 2

_VENDORS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}


@dataclass(frozen=True)
class Adapter:
    name: str
    luid: int
    vendor_id: int
    dedicated_bytes: int
    shared_bytes: int
    software: bool


def supported() -> bool:
    return sys.platform == "win32"


def luid_key(luid: int) -> str:
    """Instance-name form used by Windows performance counters."""
    return "luid_0x%08x_0x%08x" % ((luid >> 32) & 0xFFFFFFFF, luid & 0xFFFFFFFF)


def vendor_name(vendor_id: int) -> str:
    return _VENDORS.get(vendor_id, "0x%04X" % vendor_id)


def parse_desc(raw: Any) -> Adapter:
    """Build an Adapter from a DXGI_ADAPTER_DESC1-like object (attribute access)."""
    name = str(raw.Description).rstrip("\x00").strip()
    high = int(raw.AdapterLuid.HighPart) & 0xFFFFFFFF
    low = int(raw.AdapterLuid.LowPart) & 0xFFFFFFFF
    software = bool(int(raw.Flags) & DXGI_ADAPTER_FLAG_SOFTWARE) or name.startswith(
        "Microsoft Basic Render"
    )
    return Adapter(
        name=name,
        luid=(high << 32) | low,
        vendor_id=int(raw.VendorId),
        dedicated_bytes=int(raw.DedicatedVideoMemory),
        shared_bytes=int(raw.SharedSystemMemory),
        software=software,
    )


def _list_adapters_win() -> List[Adapter]:
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", ctypes.c_wchar * 128),
            ("VendorId", wintypes.UINT),
            ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT),
            ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", LUID),
            ("Flags", wintypes.UINT),
        ]

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def method(obj: ctypes.c_void_p, index: int, *argtypes: Any) -> Any:
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return proto(vtbl[index])

    def release(obj: ctypes.c_void_p) -> None:
        try:
            vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(obj)
        except Exception:
            pass

    dxgi = ctypes.WinDLL("dxgi")
    iid = GUID(
        0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87)
    )
    create = dxgi.CreateDXGIFactory1
    create.restype = ctypes.c_long
    create.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    factory = ctypes.c_void_p()
    if create(ctypes.byref(iid), ctypes.byref(factory)) < 0 or not factory.value:
        return []

    result: List[Adapter] = []
    try:
        enum = method(factory, 12, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while index < 64:
            adapter = ctypes.c_void_p()
            hr = enum(factory, index, ctypes.byref(adapter))
            if (hr & 0xFFFFFFFF) == DXGI_ERROR_NOT_FOUND or hr < 0 or not adapter.value:
                break
            try:
                desc = DESC1()
                get_desc = method(adapter, 10, ctypes.POINTER(DESC1))
                if get_desc(adapter, ctypes.byref(desc)) >= 0:
                    result.append(parse_desc(desc))
            finally:
                release(adapter)
            index += 1
    finally:
        release(factory)
    return result


def list_adapters() -> List[Adapter]:
    """All DXGI adapters; [] on non-Windows or any error. Never raises."""
    if not supported():
        return []
    try:
        return _list_adapters_win()
    except Exception:
        return []

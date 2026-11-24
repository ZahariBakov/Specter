"""Windows Performance Counters (PDH) through ctypes, no dependencies.

`PdhReader.read(path)` returns ``{instance_name: value}`` for a counter path that may
contain a wildcard instance, e.g. ``\\GPU Engine(*)\\Utilization Percentage``.

Instance names are returned exactly as Windows gives them (no case change), e.g.
``_Total`` for ``\\Processor(_Total)\\% Processor Time`` or
``pid_1234_luid_0x00000000_0x0000A1B2_phys_0_eng_0_engtype_3D`` for GPU Engine.
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# --- constants ------------------------------------------------------------------
PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000  # don't clamp percentages at 100
PDH_MORE_DATA = 0x800007D2
ERROR_SUCCESS = 0
# CStatus: 0 = PDH_CSTATUS_VALID_DATA, 1 = PDH_CSTATUS_NEW_DATA
_GOOD_STATUS = (0, 1)

#: Re-add a wildcard counter after this many seconds so new instances (processes that
#: started later) show up. Only used when `REEXPAND_SECONDS` > 0 (see module notes).
REEXPAND_SECONDS = 0.0


# --- structures -----------------------------------------------------------------
class _CounterValueUnion(ctypes.Union):
    # Only the double member is used (PDH_FMT_DOUBLE). The union is 8 bytes.
    _fields_ = [
        ("longValue", ctypes.c_long),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_longlong),
        ("AnsiStringValue", ctypes.c_char_p),
        ("WideStringValue", ctypes.c_wchar_p),
    ]


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    # DWORD CStatus; (4 bytes padding on the 8-byte-aligned union); union value
    _fields_ = [("CStatus", wintypes.DWORD), ("value", _CounterValueUnion)]


class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", PDH_FMT_COUNTERVALUE)]


def _load_pdh():
    try:
        dll = ctypes.WinDLL("pdh.dll")  # type: ignore[attr-defined]
    except (AttributeError, OSError):  # not Windows, or no pdh.dll
        return None
    try:
        h = ctypes.c_void_p
        dll.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(h)]
        dll.PdhOpenQueryW.restype = wintypes.DWORD
        dll.PdhAddEnglishCounterW.argtypes = [h, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(h)]
        dll.PdhAddEnglishCounterW.restype = wintypes.DWORD
        dll.PdhRemoveCounter.argtypes = [h]
        dll.PdhRemoveCounter.restype = wintypes.DWORD
        dll.PdhCollectQueryData.argtypes = [h]
        dll.PdhCollectQueryData.restype = wintypes.DWORD
        dll.PdhGetFormattedCounterArrayW.argtypes = [
            h,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),  # in: buffer bytes, out: needed bytes
            ctypes.POINTER(wintypes.DWORD),  # out: item count
            ctypes.c_void_p,  # buffer
        ]
        dll.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD
        dll.PdhCloseQuery.argtypes = [h]
        dll.PdhCloseQuery.restype = wintypes.DWORD
    except AttributeError:
        return None
    return dll


_pdh = _load_pdh()


class PdhReader:
    """One PDH query; counter paths are added lazily on first use."""

    def __init__(self) -> None:
        self.last_error: str = ""
        self._query = ctypes.c_void_p()
        self._counters: Dict[str, ctypes.c_void_p] = {}
        self._added_at: Dict[str, float] = {}
        self._failed: Dict[str, bool] = {}
        self._closed = False
        if _pdh is None:
            self.last_error = "pdh.dll not available"
            self._closed = True
            return
        status = _pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query))
        if status != ERROR_SUCCESS:
            self.last_error = "PdhOpenQueryW failed: 0x%08X" % status
            self._closed = True

    @staticmethod
    def supported() -> bool:
        return _pdh is not None

    # -- context manager ---------------------------------------------------------
    def __enter__(self) -> "PdhReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            _pdh.PdhCloseQuery(self._query)
        except Exception:  # noqa: BLE001
            pass
        self._counters.clear()
        self._added_at.clear()

    # -- internals ---------------------------------------------------------------
    def _add(self, path: str) -> Optional[ctypes.c_void_p]:
        handle = ctypes.c_void_p()
        status = _pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(handle))
        if status != ERROR_SUCCESS:
            self.last_error = "PdhAddEnglishCounterW(%s) failed: 0x%08X" % (path, status)
            return None
        self._counters[path] = handle
        self._added_at[path] = time.monotonic()
        return handle

    def _remove(self, path: str) -> None:
        handle = self._counters.pop(path, None)
        self._added_at.pop(path, None)
        if handle is not None:
            _pdh.PdhRemoveCounter(handle)

    def _format(self, handle: ctypes.c_void_p) -> Optional[Dict[str, float]]:
        flags = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        status = _pdh.PdhGetFormattedCounterArrayW(handle, flags, ctypes.byref(size), ctypes.byref(count), None)
        if status != PDH_MORE_DATA:
            # Typically PDH_CALC_NEGATIVE_DENOMINATOR / "no data yet" on the first sample.
            self.last_error = "PdhGetFormattedCounterArrayW: 0x%08X" % status
            return None
        # Retry a few times: the needed size can grow between the two calls.
        for _ in range(3):
            buf = ctypes.create_string_buffer(size.value)
            status = _pdh.PdhGetFormattedCounterArrayW(
                handle, flags, ctypes.byref(size), ctypes.byref(count), buf
            )
            if status == ERROR_SUCCESS:
                break
            if status != PDH_MORE_DATA:
                self.last_error = "PdhGetFormattedCounterArrayW: 0x%08X" % status
                return None
        else:
            self.last_error = "PdhGetFormattedCounterArrayW: buffer kept growing"
            return None
        items = ctypes.cast(buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
        result: Dict[str, float] = {}
        for i in range(count.value):
            item = items[i]
            if item.FmtValue.CStatus not in _GOOD_STATUS or item.szName is None:
                continue
            result[item.szName] = float(item.FmtValue.value.doubleValue)
        return result

    # -- public ------------------------------------------------------------------
    def read(self, path: str) -> "dict[str, float]":
        """Return {instance_name: value}. Never raises; {} on error (see `last_error`).

        The first read of a path returns {} for rate/utilisation counters (they need
        two samples). Call it again later.
        """
        try:
            if self._closed or _pdh is None:
                return {}
            fresh = False
            if path not in self._counters:
                if self._failed.get(path):
                    return {}
                if self._add(path) is None:
                    self._failed[path] = True
                    return {}
                fresh = True
            elif REEXPAND_SECONDS > 0 and (
                time.monotonic() - self._added_at.get(path, 0.0) > REEXPAND_SECONDS
            ):
                self._remove(path)
                if self._add(path) is None:
                    return {}
                fresh = True
            status = _pdh.PdhCollectQueryData(self._query)
            if status != ERROR_SUCCESS:
                self.last_error = "PdhCollectQueryData: 0x%08X" % status
                return {}
            if fresh:
                return {}  # no second sample yet
            result = self._format(self._counters[path])
            if result is None:
                return {}
            self.last_error = ""
            return result
        except Exception as exc:  # noqa: BLE001
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            log.debug("PDH read failed", exc_info=True)
            return {}


__all__: List[str] = ["PdhReader"]

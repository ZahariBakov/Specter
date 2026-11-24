"""Click-through for the panel: mouse clicks go to the window underneath.

X11 (`ClickThrough`): done with the X Fixes extension: the window gets an *input shape*. Only the
small grip rectangle keeps taking clicks (so the menu can still be opened to switch this off);
everywhere else the mouse goes to whatever is below.

Windows (`WindowsClickThrough`): a window with WS_EX_LAYERED | WS_EX_TRANSPARENT ignores *all*
mouse input, so the grip has to be a separate small window (the panel makes it).

Both are called through ctypes, so there is nothing to install.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import sys
from typing import Iterable, List, Optional, Tuple

log = logging.getLogger(__name__)

SHAPE_INPUT = 2  # which shape of the window we change (X Shape extension)
Rect = Tuple[int, int, int, int]  # x, y, width, height


class _XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


class ClickThrough:
    """Sets and clears the input shape of windows. Not thread-safe: use it from the Tk thread."""

    def __init__(self) -> None:
        self._x11: Optional[ctypes.CDLL] = None
        self._xfixes: Optional[ctypes.CDLL] = None
        self._display: Optional[int] = None

    @staticmethod
    def supported() -> bool:
        return sys.platform.startswith("linux") and bool(os.environ.get("DISPLAY"))

    def _open(self) -> bool:
        """Connect to the X server (own connection; the shape lives in the server)."""
        if self._display:
            return True
        try:
            x11_name = ctypes.util.find_library("X11")
            fixes_name = ctypes.util.find_library("Xfixes")
            if not x11_name or not fixes_name:
                log.info("Click-through needs libX11 and libXfixes")
                return False
            x11, xfixes = ctypes.CDLL(x11_name), ctypes.CDLL(fixes_name)
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XFlush.argtypes = [ctypes.c_void_p]
            x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            x11.XQueryTree.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                ctypes.POINTER(ctypes.c_uint),
            ]
            x11.XQueryTree.restype = ctypes.c_int
            x11.XFree.argtypes = [ctypes.c_void_p]
            xfixes.XFixesQueryExtension.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
            ]
            xfixes.XFixesQueryExtension.restype = ctypes.c_int
            xfixes.XFixesCreateRegion.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(_XRectangle), ctypes.c_int
            ]
            xfixes.XFixesCreateRegion.restype = ctypes.c_ulong
            xfixes.XFixesDestroyRegion.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            xfixes.XFixesSetWindowShapeRegion.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_ulong,
            ]
            display = x11.XOpenDisplay(None)
            if not display:
                return False
            event, error = ctypes.c_int(), ctypes.c_int()
            if not xfixes.XFixesQueryExtension(display, ctypes.byref(event), ctypes.byref(error)):
                x11.XCloseDisplay(display)
                log.info("The X server has no XFixes extension; click-through is off")
                return False
        except (OSError, AttributeError):
            log.exception("Could not load the X11 libraries for click-through")
            return False
        self._x11, self._xfixes, self._display = x11, xfixes, display
        return True

    def window_chain(self, window: int) -> List[int]:
        """`window` and its parents up to (not including) the root window.

        Tk puts every top-level window inside a wrapper window of its own, and that wrapper is
        what the mouse really hits, so the shape has to be set on all of them.
        """
        if not self._open():
            return [window]
        assert self._x11
        chain = [window]
        for _ in range(8):  # a real chain is 2 long; the limit only guards against surprises
            root, parent = ctypes.c_ulong(), ctypes.c_ulong()
            children = ctypes.POINTER(ctypes.c_ulong)()
            count = ctypes.c_uint()
            ok = self._x11.XQueryTree(
                self._display, chain[-1], ctypes.byref(root), ctypes.byref(parent),
                ctypes.byref(children), ctypes.byref(count),
            )
            if children:
                self._x11.XFree(children)
            if not ok or not parent.value or parent.value == root.value:
                break
            chain.append(parent.value)
        return chain

    def set_input_rects(self, windows: Iterable[int], rects: List[Rect]) -> bool:
        """Only `rects` (window coordinates) take mouse input; the rest of each window is
        transparent to the mouse. Returns False if it could not be done."""
        if not self._open():
            return False
        assert self._x11 and self._xfixes
        array = (_XRectangle * max(1, len(rects)))(*[_XRectangle(*r) for r in rects])
        region = self._xfixes.XFixesCreateRegion(self._display, array, len(rects))
        try:
            for window in windows:
                self._xfixes.XFixesSetWindowShapeRegion(
                    self._display, window, SHAPE_INPUT, 0, 0, region
                )
        finally:
            self._xfixes.XFixesDestroyRegion(self._display, region)
        self._x11.XSync(self._display, 0)
        return True

    def reset(self, windows: Iterable[int]) -> bool:
        """The whole window takes mouse input again."""
        if not self._open():
            return False
        assert self._x11 and self._xfixes
        for window in windows:
            self._xfixes.XFixesSetWindowShapeRegion(self._display, window, SHAPE_INPUT, 0, 0, 0)
        self._x11.XSync(self._display, 0)
        return True

    def close(self) -> None:
        if self._display and self._x11:
            self._x11.XCloseDisplay(self._display)
        self._display = None


GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
LWA_ALPHA = 0x00000002


class WindowsClickThrough:
    """Toggles WS_EX_TRANSPARENT on a top-level window. Use it from the Tk thread.

    Which window: `root.winfo_id()` is Tk's inner child window; the real top-level is its parent
    (`GetParent`, the same as `wm frame`). That outer window is the one Tk gives WS_EX_LAYERED for
    `-alpha` (checked on Windows 11), so `top_level()` returns it and the style goes there.
    """

    def __init__(self) -> None:
        self._user32: Optional[object] = None
        self._get_long: Optional[object] = None  # GetWindowLongPtrW (or GetWindowLongW)
        self._set_long: Optional[object] = None

    @staticmethod
    def supported() -> bool:
        return sys.platform == "win32"

    def _api(self) -> Optional[object]:
        if self._user32 is not None:
            return self._user32
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore
            hwnd, long_ptr = ctypes.c_void_p, ctypes.c_ssize_t
            if hasattr(user32, "GetWindowLongPtrW"):  # 64-bit
                get_long, set_long = user32.GetWindowLongPtrW, user32.SetWindowLongPtrW
            else:  # 32-bit Windows only has the plain versions
                get_long, set_long = user32.GetWindowLongW, user32.SetWindowLongW
                long_ptr = ctypes.c_long
            get_long.argtypes = [hwnd, ctypes.c_int]
            get_long.restype = long_ptr
            set_long.argtypes = [hwnd, ctypes.c_int, long_ptr]
            set_long.restype = long_ptr
            user32.GetParent.argtypes = [hwnd]
            user32.GetParent.restype = hwnd
            user32.SetWindowPos.argtypes = [
                hwnd, hwnd, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint
            ]
            user32.SetWindowPos.restype = ctypes.c_int
            user32.SetLayeredWindowAttributes.argtypes = [
                hwnd, ctypes.c_uint32, ctypes.c_ubyte, ctypes.c_uint32
            ]
            user32.SetLayeredWindowAttributes.restype = ctypes.c_int
        except (OSError, AttributeError):
            log.exception("Could not load user32 for click-through")
            return None
        self._get_long, self._set_long = get_long, set_long
        self._user32 = user32
        return user32

    def top_level(self, window: int) -> int:
        """The real top-level window for Tk's `winfo_id()` (its parent), or `window` itself."""
        user32 = self._api()
        if user32 is None:
            return window
        try:
            parent = user32.GetParent(window)  # type: ignore
        except Exception:  # noqa: BLE001 - never crash over click-through
            return window
        return parent or window

    def ex_style(self, hwnd: int) -> int:
        """The window's extended style bits (0 if it can't be read)."""
        user32 = self._api()
        if user32 is None:
            return 0
        try:
            return int(self._get_long(hwnd, GWL_EXSTYLE)) & 0xFFFFFFFF  # type: ignore
        except Exception:  # noqa: BLE001
            return 0

    def set_transparent(self, hwnd: int, on: bool) -> bool:
        """Mouse input passes through `hwnd` (on) or not (off). Keeps WS_EX_LAYERED (Tk needs it
        for the opacity), adding it if missing. Returns False if it could not be done."""
        user32 = self._api()
        if user32 is None or not hwnd:
            return False
        try:
            ctypes.set_last_error(0)
            style = self._get_long(hwnd, GWL_EXSTYLE)  # type: ignore
            if style == 0 and ctypes.get_last_error():
                return False
            if on:
                new = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            else:
                new = style & ~WS_EX_TRANSPARENT
            if new != style:
                ctypes.set_last_error(0)
                old = self._set_long(hwnd, GWL_EXSTYLE, new)  # type: ignore
                if old == 0 and ctypes.get_last_error():
                    return False
                if on and not style & WS_EX_LAYERED:
                    # A layered window stays invisible until it gets its attributes: full opacity.
                    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)  # type: ignore
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, flags)  # type: ignore
            return bool(self.ex_style(hwnd) & WS_EX_TRANSPARENT) == on
        except Exception:  # noqa: BLE001 - never crash over click-through
            log.exception("Could not change click-through")
            return False

    def close(self) -> None:
        """Nothing to release; here so both classes look the same to the panel."""

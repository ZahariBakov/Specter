"""Click-through for the panel on X11: mouse clicks go to the window underneath.

Done with the X Fixes extension: the window gets an *input shape*. Only the small grip rectangle
keeps taking clicks (so the menu can still be opened to switch this off); everywhere else the
mouse goes to whatever is below. Called through ctypes, so there is nothing to install.

Windows would use WS_EX_TRANSPARENT instead (not done yet), so `supported()` is False there.
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

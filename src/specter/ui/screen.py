"""Where on the desktop a window may sit (no Tk in `clamp`, so it is easy to test).

The limit is the whole desktop: all monitors together. So the panel can be dragged from one
screen to the next, but never off the outer edge of the desktop.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Tuple

Bounds = Tuple[int, int, int, int]  # left, top, right, bottom (right and bottom are exclusive)

# GetSystemMetrics() indexes for the virtual screen (all monitors) on Windows.
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN, _SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 76, 77, 78, 79


def clamp(x: int, y: int, width: int, height: int, bounds: Bounds) -> tuple[int, int]:
    """Move a width x height window at (x, y) the shortest way to lie inside `bounds`.

    A window bigger than the bounds is pinned to the left / top edge.
    """
    left, top, right, bottom = bounds
    return max(left, min(x, right - width)), max(top, min(y, bottom - height))


def clamp_point(x: int, y: int, bounds: Bounds) -> tuple[int, int]:
    """The nearest point inside `bounds`."""
    left, top, right, bottom = bounds
    return max(left, min(x, right - 1)), max(top, min(y, bottom - 1))


def _windows_bounds() -> Bounds | None:
    try:
        import ctypes

        metrics = ctypes.windll.user32.GetSystemMetrics  # type: ignore[attr-defined]
        left, top = metrics(_SM_XVIRTUALSCREEN), metrics(_SM_YVIRTUALSCREEN)
        width, height = metrics(_SM_CXVIRTUALSCREEN), metrics(_SM_CYVIRTUALSCREEN)
    except Exception:
        return None
    return (left, top, left + width, top + height) if width > 0 and height > 0 else None


def screen_bounds(widget: tk.Misc) -> Bounds:
    """The desktop rectangle covering every monitor.

    X11: Tk's screen is already all monitors together (Xinerama / RandR).
    Windows: Tk only reports the primary monitor, so ask the OS for the virtual screen.
    """
    if sys.platform == "win32":
        bounds = _windows_bounds()
        if bounds is not None:
            return bounds
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()

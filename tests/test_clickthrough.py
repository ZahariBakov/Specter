from __future__ import annotations

import ctypes.util
import sys

import pytest

from specter.ui import clickthrough
from specter.ui.clickthrough import (
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    ClickThrough,
    WindowsClickThrough,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows click-through")


def test_not_supported_without_a_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    assert ClickThrough.supported() is False


def test_missing_libraries_mean_false_not_a_crash(monkeypatch):
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
    clicker = ClickThrough()
    assert clicker.set_input_rects([1], [(0, 0, 14, 14)]) is False
    assert clicker.reset([1]) is False
    clicker.close()  # nothing was opened; must not raise


@pytest.mark.parametrize(
    "platform, expected", [("win32", True), ("linux", False), ("darwin", False)]
)
def test_windows_supported_per_platform(monkeypatch, platform, expected):
    monkeypatch.setattr(clickthrough.sys, "platform", platform)
    assert WindowsClickThrough.supported() is expected


def test_windows_click_through_is_off_on_other_platforms(monkeypatch):
    monkeypatch.setattr(clickthrough.sys, "platform", "win32")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert ClickThrough.supported() is False  # so the panel picks the Windows version


def test_windows_without_user32_returns_false(monkeypatch):
    clicker = WindowsClickThrough()
    monkeypatch.setattr(clicker, "_api", lambda: None)
    assert clicker.set_transparent(1234, True) is False
    assert clicker.ex_style(1234) == 0
    assert clicker.top_level(1234) == 1234
    clicker.close()


@windows_only
def test_windows_bad_window_returns_false():
    clicker = WindowsClickThrough()
    assert clicker.set_transparent(0, True) is False
    assert clicker.set_transparent(0x7FFFFFF0, True) is False  # no such window


@windows_only
def test_windows_set_transparent_on_and_off():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no Tk")
    try:
        root.overrideredirect(True)
        root.withdraw()
        root.attributes("-alpha", 0.85)
        root.update_idletasks()
        clicker = WindowsClickThrough()
        hwnd = clicker.top_level(root.winfo_id())
        assert hwnd != root.winfo_id()  # the outer window, not Tk's inner child
        assert hwnd == int(root.wm_frame(), 16)
        assert clicker.ex_style(hwnd) & WS_EX_LAYERED  # Tk put it there for -alpha

        assert clicker.set_transparent(hwnd, True) is True
        style = clicker.ex_style(hwnd)
        assert style & WS_EX_TRANSPARENT and style & WS_EX_LAYERED

        assert clicker.set_transparent(hwnd, False) is True
        style = clicker.ex_style(hwnd)
        assert not style & WS_EX_TRANSPARENT
        assert style & WS_EX_LAYERED  # the opacity keeps working
    finally:
        root.destroy()

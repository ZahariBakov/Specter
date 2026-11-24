from __future__ import annotations

import ctypes.util

from specter.ui.clickthrough import ClickThrough


def test_not_supported_without_a_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    assert ClickThrough.supported() is False


def test_missing_libraries_mean_false_not_a_crash(monkeypatch):
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
    clicker = ClickThrough()
    assert clicker.set_input_rects([1], [(0, 0, 14, 14)]) is False
    assert clicker.reset([1]) is False
    clicker.close()  # nothing was opened; must not raise

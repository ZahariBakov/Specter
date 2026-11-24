from __future__ import annotations

import time

import pytest

from specter.sensors import windows_pdh
from specter.sensors.windows_pdh import PdhReader

needs_pdh = pytest.mark.skipif(not PdhReader.supported(), reason="needs Windows pdh.dll")


@needs_pdh
def test_live_total_processor_time():
    # Instance names are returned exactly as Windows gives them: "_Total".
    with PdhReader() as reader:
        reader.read(r"\Processor(_Total)\% Processor Time")  # first sample: {}
        time.sleep(0.3)
        values = reader.read(r"\Processor(_Total)\% Processor Time")
    assert "_Total" in values
    assert isinstance(values["_Total"], float)
    assert 0.0 <= values["_Total"] <= 100.0


@needs_pdh
def test_invalid_path_returns_empty_and_sets_error():
    reader = PdhReader()
    try:
        assert reader.read(r"\No Such Object(*)\Nothing") == {}
        assert reader.last_error
        assert reader.read(r"\No Such Object(*)\Nothing") == {}  # still no raise
    finally:
        reader.close()


def test_unsupported_returns_empty(monkeypatch):
    monkeypatch.setattr(windows_pdh, "_pdh", None)
    assert PdhReader.supported() is False
    reader = PdhReader()
    assert reader.read(r"\Processor(_Total)\% Processor Time") == {}
    assert reader.last_error
    reader.close()  # must not raise

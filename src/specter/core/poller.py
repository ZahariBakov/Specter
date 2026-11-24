"""Reads all providers on a background thread and hands out Snapshots.

The poller knows nothing about the UI. It calls `on_snapshot` from its own
thread, so the UI must pass the data to its main thread (see app.py).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from specter.core.models import Snapshot
from specter.sensors.base import SensorProvider

log = logging.getLogger(__name__)


class Poller:
    def __init__(
        self,
        providers: list[SensorProvider],
        on_snapshot: Callable[[Snapshot], None],
        interval_ms: int = 1000,
    ) -> None:
        self._providers = providers
        self._on_snapshot = on_snapshot
        self._interval = interval_ms / 1000
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="specter-poller", daemon=True)

    def set_interval(self, interval_ms: int) -> None:
        """Change the polling interval. Safe from any thread (it only swaps a float);
        the new value is used from the next wait on."""
        self._interval = max(250, interval_ms) / 1000

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        for provider in self._providers:
            try:
                provider.close()
            except Exception:
                log.exception("Provider %s failed to close", provider.name)

    def poll_once(self) -> Snapshot:
        snapshot = Snapshot(time=time.time())
        for provider in self._providers:
            try:
                for reading in provider.read():
                    # the first provider (best priority) that gives a key wins
                    snapshot.readings.setdefault(reading.key, reading)
            except Exception:
                log.exception("Provider %s failed to read", provider.name)
        return snapshot

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self._on_snapshot(self.poll_once())
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, self._interval - elapsed))

"""Creates the app and wires providers -> poller -> panel."""

from __future__ import annotations

import logging
import queue
import sys
import tkinter as tk

from specter.config import Config
from specter.core.models import Snapshot
from specter.core.poller import Poller
from specter.sensors import create_providers
from specter.ui.panel import PanelWindow
from specter.ui.screen import screen_bounds

UI_CHECK_MS = 100  # how often the UI picks up new snapshots


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = Config.load()
    root = tk.Tk()

    # Tk is not thread-safe: the poller thread only puts data in a queue,
    # and the UI thread takes it out with root.after().
    snapshots: queue.Queue[Snapshot] = queue.Queue()
    poller = Poller(create_providers(), snapshots.put, interval_ms=config.interval_ms)

    def on_interval(interval_ms: int) -> None:
        config.interval_ms = interval_ms
        poller.set_interval(interval_ms)

    def save_settings() -> None:
        """Called whenever a setting changes and on quit, so a crash loses nothing."""
        config.opacity = panel.opacity()
        config.hidden_tiles = panel.hidden_tiles()
        config.locked = panel.locked
        config.topmost = panel.topmost
        config.pos_x, config.pos_y = panel.position()
        config.width, config.height = panel.size() or (None, None)
        config.save()

    def on_quit() -> None:
        save_settings()
        poller.stop()
        root.destroy()

    size = (config.width, config.height) if config.width and config.height else None
    panel = PanelWindow(
        root,
        opacity=config.opacity,
        size=size,
        hidden_tiles=config.hidden_tiles,
        locked=config.locked,
        topmost=config.topmost,
        interval_ms=config.interval_ms,
        on_interval=on_interval,
        on_change=save_settings,
        on_quit=on_quit,
    )

    has_saved_pos = config.pos_x is not None and config.pos_y is not None
    if has_saved_pos:
        panel.move_to(config.pos_x, config.pos_y)
    else:
        root.withdraw()  # stay hidden until we know the size, then go top-right
    placed = has_saved_pos

    def pump() -> None:
        nonlocal placed
        latest = None
        while True:
            try:
                latest = snapshots.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            panel.show_snapshot(latest)
            if not placed:
                root.update_idletasks()
                left, top, right, _bottom = screen_bounds(root)
                panel.move_to(right - panel.current_size()[0] - 20, top + 20)
                root.deiconify()
                placed = True
        root.after(UI_CHECK_MS, pump)

    poller.start()
    pump()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        on_quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())

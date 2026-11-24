"""Creates the app and wires providers -> poller -> panel."""

from __future__ import annotations

import logging
import queue
import sys
import tkinter as tk
from pathlib import Path

from specter import autostart
from specter.config import Config
from specter.core.models import Snapshot
from specter.core.poller import Poller
from specter.sensors import create_providers
from specter.ui.panel import PanelWindow
from specter.ui.screen import screen_bounds

ICON = Path(__file__).parent / "assets" / "icon.png"
UI_CHECK_MS = 100  # how often the UI picks up new snapshots


def _set_dpi_aware() -> None:
    """Windows: draw at the real screen resolution instead of a blurry bitmap stretched by the OS.

    Must run before the first Tk window. "System aware" (1), not per-monitor: Tk does not rescale a
    window that moves to a monitor with another scale, so per-monitor would look wrong there.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]  # Windows 7/8
    except Exception:  # never stop the app over this
        logging.getLogger(__name__).info("Could not set DPI awareness", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="specter", description="Small hardware monitor panel.")
    parser.add_argument("--sensors", action="store_true", help="print which sensors work and exit")
    parser.add_argument("--dump", action="store_true", help="print raw platform sensor data and exit")
    args = parser.parse_args(argv)
    if args.sensors or args.dump:
        from specter import diagnostics

        if args.sensors:
            print(diagnostics.sensors_report())
        if args.dump:
            print(diagnostics.dump_report())
        return 0

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = Config.load()
    _set_dpi_aware()
    root = tk.Tk()
    try:  # the icon task switchers and window lists show (the panel has no title bar)
        icon = tk.PhotoImage(master=root, file=str(ICON))
        root.iconphoto(True, icon)
        root._specter_icon = icon  # type: ignore[attr-defined]  # keep it alive
    except tk.TclError:
        logging.getLogger(__name__).info("Could not load the app icon %s", ICON)

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
        config.first_tile = panel.first_tile()
        config.sparklines = panel.sparklines
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
        first_tile=config.first_tile,
        sparklines=config.sparklines,
        locked=config.locked,
        topmost=config.topmost,
        interval_ms=config.interval_ms,
        on_interval=on_interval,
        get_autostart=autostart.is_enabled if autostart.supported() else None,
        on_autostart=autostart.set_enabled if autostart.supported() else None,
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

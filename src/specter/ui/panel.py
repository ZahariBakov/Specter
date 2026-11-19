"""The floating, transparent, always-on-top panel (Tkinter)."""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable

from specter.core.models import Snapshot
from specter.ui.popup import PopupMenu
from specter.ui.widgets import BG, BORDER, MetricTile

OPACITY_STEPS = [1.0, 0.85, 0.7, 0.55, 0.4]
COLUMNS = 2

class PanelWindow:
    """Frameless panel. Drag with the left mouse button, right-click for the menu."""

    def __init__(
        self,
        root: tk.Tk,
        opacity: float = 0.85,
        on_opacity: Callable[[float], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self._on_opacity = on_opacity
        self._on_quit = on_quit

        root.title("Specter")
        root.configure(bg=BG)
        root.overrideredirect(True)  # no title bar / borders
        root.attributes("-topmost", True)
        if sys.platform.startswith("linux"):
            root.attributes("-type", "utility")  # hint: no taskbar entry

        self._frame = tk.Frame(
            root, bg=BG, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER
        )
        self._frame.pack(fill="both", expand=True)

        self._tiles: dict[str, MetricTile] = {}
        self._drag_start: tuple[int, int] | None = None
        self._opacity = tk.DoubleVar(value=opacity)

        self._menu = PopupMenu(
            root,
            OPACITY_STEPS,
            get_opacity=self._opacity.get,
            on_opacity=self.set_opacity,
            on_quit=self._quit,
        )

        self._bind_mouse(self._frame)
        self.set_opacity(opacity)

    # --- data ---------------------------------------------------------------

    def show_snapshot(self, snapshot: Snapshot) -> None:
        # Group readings by device: "cpu.load" and "cpu.temp" share the CPU tile.
        groups: dict[str, list] = {}
        for key, reading in snapshot.readings.items():
            groups.setdefault(key.split(".", 1)[0], []).append(reading)

        for group, readings in groups.items():
            tile = self._tiles.get(group)
            if tile is None:
                tile = MetricTile(self._frame, readings[0].label)
                index = len(self._tiles)
                tile.grid(
                    row=index // COLUMNS,
                    column=index % COLUMNS,
                    sticky="nw",
                    padx=(0 if index % COLUMNS == 0 else 16, 0),
                    pady=(0 if index < COLUMNS else 12, 0),
                )
                self._bind_mouse(tile)
                self._tiles[group] = tile
            tile.update_readings(readings)

    # --- opacity ------------------------------------------------------------

    def set_opacity(self, value: float) -> None:
        value = min(1.0, max(0.2, value))
        self._opacity.set(value)
        # Linux/X11 needs a running compositor for this to have any effect.
        self.root.attributes("-alpha", value)
        if self._on_opacity:
            self._on_opacity(value)

    # --- position -----------------------------------------------------------

    def move_to(self, x: int, y: int) -> None:
        self.root.geometry(f"+{x}+{y}")

    def position(self) -> tuple[int, int]:
        return self.root.winfo_x(), self.root.winfo_y()

    # --- mouse --------------------------------------------------------------

    def _bind_mouse(self, widget: tk.Misc) -> None:
        targets = widget.widgets() if isinstance(widget, MetricTile) else (widget,)
        for target in targets:
            target.bind("<ButtonPress-1>", self._drag_begin)
            target.bind("<B1-Motion>", self._drag_move)
            target.bind("<ButtonRelease-1>", self._drag_end)
            target.bind("<Button-3>", self._show_menu)

    def _drag_begin(self, event: tk.Event) -> None:
        self._hide_menu()
        self._drag_start = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        self.root.configure(cursor="fleur")  # 4-way "move" cursor while dragging

    def _drag_move(self, event: tk.Event) -> None:
        if self._drag_start is not None:
            dx, dy = self._drag_start
            self.move_to(event.x_root - dx, event.y_root - dy)

    def _drag_end(self, _event: tk.Event) -> None:
        self._drag_start = None
        self.root.configure(cursor="")  # back to the normal arrow

    def _show_menu(self, event: tk.Event) -> None:
        self._menu.open(event.x_root, event.y_root)

    def _hide_menu(self, _event: tk.Event | None = None) -> None:
        self._menu.close()

    def _quit(self) -> None:
        if self._on_quit:
            self._on_quit()
        else:
            self.root.destroy()

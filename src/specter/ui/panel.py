"""The floating, transparent, always-on-top panel (Tkinter)."""

from __future__ import annotations

import re
import sys
import tkinter as tk
from typing import Callable, Tuple

from specter.core.models import Snapshot
from specter.ui.layout import GAP_X, GAP_Y, choose_layout, grid_size
from specter.ui.popup import PopupMenu
from specter.ui.widgets import BG, BORDER, LABEL_FG, VALUE_FG, make_tile

OPACITY_STEPS = [1.0, 0.85, 0.7, 0.55, 0.4]
DEFAULT_COLUMNS = 2  # layout used until the user resizes the panel
PAD_X, PAD_Y = 14, 12  # frame padding
CHROME_W, CHROME_H = 2 * (PAD_X + 1), 2 * (PAD_Y + 1)  # padding + 1 px border
TILE_ORDER = ("cpu", "gpu", "ram", "disk", "net", "fan")  # unknown devices go last
EDGE = 6  # px along the window edge that start a resize instead of a move
ARROW_GAP = 8

# (horizontal edge, vertical edge) -> cursor. -1 = left/top, 1 = right/bottom.
_RESIZE_CURSORS = {
    (-1, -1): "top_left_corner",
    (1, -1): "top_right_corner",
    (-1, 1): "bottom_left_corner",
    (1, 1): "bottom_right_corner",
    (-1, 0): "left_side",
    (1, 0): "right_side",
    (0, -1): "top_side",
    (0, 1): "bottom_side",
}

Size = Tuple[int, int]


def tile_sort_key(group: str) -> tuple[int, str]:
    """CPU, GPU (gpu0, gpu1 ...), RAM, DISK, NET, FAN, then anything else by name."""
    base = re.sub(r"\d+$", "", group)
    rank = TILE_ORDER.index(base) if base in TILE_ORDER else len(TILE_ORDER)
    return rank, group


class PanelWindow:
    """Frameless panel.

    Drag with the left mouse button to move, drag an edge or corner to resize,
    right-click for the menu. The tiles rearrange to fit the window: one row,
    one column or a grid. When not all fit, fewer are shown (down to one) with
    ‹ › arrows to cycle through them.
    """

    def __init__(
        self,
        root: tk.Tk,
        opacity: float = 0.85,
        size: Size | None = None,
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
            root, bg=BG, padx=PAD_X, pady=PAD_Y, highlightthickness=1, highlightbackground=BORDER
        )
        self._frame.pack(fill="both", expand=True)

        self._tiles: dict[str, tk.Frame] = {}
        self._cell: Size = (1, 1)  # largest tile seen so far (only grows, so the layout doesn't flicker)
        self._size: Size | None = size  # None = fit the content (user never resized)
        self._applied: Size | None = None  # size last given to the window
        self._layout: Size | None = None  # (visible tiles, columns)
        self._first = 0  # first visible tile when not all fit
        self._arrows = (self._make_arrow("‹", -1), self._make_arrow("›", 1))

        self._drag_start: tuple[int, int] | None = None
        self._resize_start: tuple | None = None
        self._cursor = ""
        self._opacity = tk.DoubleVar(value=opacity)

        self._menu = PopupMenu(
            root,
            OPACITY_STEPS,
            get_opacity=self._opacity.get,
            on_opacity=self.set_opacity,
            on_quit=self._quit,
        )

        # Bound on the root window, so they fire for every widget inside it
        # (tiles added later included). The popup is its own toplevel and is not affected.
        root.bind("<Motion>", self._hover)
        root.bind("<ButtonPress-1>", self._press)
        root.bind("<B1-Motion>", self._motion)
        root.bind("<ButtonRelease-1>", self._release)
        root.bind("<Button-3>", self._show_menu)

        self.set_opacity(opacity)

    # --- data ---------------------------------------------------------------

    def show_snapshot(self, snapshot: Snapshot) -> None:
        # Group readings by device: "cpu.load" and "cpu.temp" share the CPU tile.
        groups: dict[str, list] = {}
        for key, reading in snapshot.readings.items():
            groups.setdefault(key.split(".", 1)[0], []).append(reading)

        added = False
        for group, readings in groups.items():
            tile = self._tiles.get(group)
            if tile is None:
                tile = make_tile(self._frame, readings)
                self._tiles[group] = tile
                added = True
            tile.update_readings(readings)

        if not self._tiles:
            return
        self._frame.update_idletasks()  # so the tiles report their new size
        cell = (
            max(self._cell[0], max(t.winfo_reqwidth() for t in self._tiles.values())),
            max(self._cell[1], max(t.winfo_reqheight() for t in self._tiles.values())),
        )
        if added or cell != self._cell:
            self._cell = cell
            self._relayout(force=added)

    # --- size and layout ----------------------------------------------------

    def size(self) -> Size | None:
        """Size chosen by the user, or None if the panel still fits its content."""
        return self._size

    def current_size(self) -> Size:
        return self._applied or (self.root.winfo_reqwidth(), self.root.winfo_reqheight())

    def set_size(self, width: int, height: int) -> None:
        self._size = (width, height)
        self._relayout()

    def _arrows_width(self) -> int:
        return 2 * (max(a.winfo_reqwidth() for a in self._arrows) + ARROW_GAP)

    def min_size(self) -> Size:
        """One tile, plus the arrows if there is more than one tile."""
        cell_w, cell_h = self._cell
        if len(self._tiles) > 1:
            cell_w += self._arrows_width()
        return cell_w + CHROME_W, cell_h + CHROME_H

    def _relayout(self, force: bool = False) -> None:
        count = len(self._tiles)
        if count == 0:
            return
        cell_w, cell_h = self._cell
        if self._size is None:
            columns = min(DEFAULT_COLUMNS, count)
            need_w, need_h = grid_size(count, columns, cell_w, cell_h)
            size = (need_w + CHROME_W, need_h + CHROME_H)
            layout = (count, columns)
        else:
            min_w, min_h = self.min_size()
            size = (max(self._size[0], min_w), max(self._size[1], min_h))
            self._size = size
            layout = choose_layout(
                count,
                cell_w,
                cell_h,
                size[0] - CHROME_W,
                size[1] - CHROME_H,
                self._arrows_width(),
            )

        if size != self._applied:
            self._applied = size
            self.root.geometry(f"{size[0]}x{size[1]}")
        if force or layout != self._layout:
            self._layout = layout
            self._place_tiles()

    def _place_tiles(self) -> None:
        tiles = [self._tiles[group] for group in sorted(self._tiles, key=tile_sort_key)]
        frame = self._frame
        for widget in tiles + list(self._arrows):
            widget.grid_forget()
        for i in range(len(tiles) + 3):
            frame.columnconfigure(i, weight=0)
            frame.rowconfigure(i, weight=0)

        visible, columns = self._layout or (len(tiles), 1)
        rows = -(-visible // columns)
        cycling = visible < len(tiles)
        # With arrows, column 0 and the last column hold them and the tiles sit in between.
        offset = 1 if cycling else 0
        if cycling:
            self._first %= len(tiles)
            shown = [tiles[(self._first + i) % len(tiles)] for i in range(visible)]
            self._arrows[0].grid(row=0, column=0, rowspan=rows, padx=(0, ARROW_GAP))
            self._arrows[1].grid(row=0, column=columns + 1, rowspan=rows, padx=(ARROW_GAP, 0))
        else:
            shown = tiles

        for i, tile in enumerate(shown):
            row, column = divmod(i, columns)
            tile.grid(
                row=row,
                column=column + offset,
                sticky="" if cycling else "nw",  # centred between the arrows
                padx=(0 if column == 0 else GAP_X, 0),
                pady=(0 if row == 0 else GAP_Y, 0),
            )
        # Spread any extra space evenly between the tiles.
        for column in range(columns):
            frame.columnconfigure(column + offset, weight=1)
        for row in range(rows):
            frame.rowconfigure(row, weight=1)

    def _make_arrow(self, text: str, step: int) -> tk.Label:
        arrow = tk.Label(
            self._frame,
            text=text,
            bg=BG,
            fg=LABEL_FG,
            font=("TkDefaultFont", 16, "bold"),
            padx=2,
            cursor="hand2",
        )

        def click(_event: tk.Event) -> str:
            self._cycle(step)
            return "break"  # don't start a window drag

        arrow.bind("<ButtonPress-1>", click)
        arrow.bind("<Enter>", lambda _e: arrow.config(fg=VALUE_FG))
        arrow.bind("<Leave>", lambda _e: arrow.config(fg=LABEL_FG))
        return arrow

    def _cycle(self, step: int) -> None:
        if self._layout and self._layout[0] < len(self._tiles):
            self._first = (self._first + step) % len(self._tiles)
            self._place_tiles()

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

    # --- mouse: move and resize ---------------------------------------------

    def _edges(self, event: tk.Event) -> tuple[int, int]:
        """Which window edges the pointer is on: -1 left/top, 1 right/bottom, 0 none."""
        x = event.x_root - self.root.winfo_rootx()
        y = event.y_root - self.root.winfo_rooty()
        width, height = self.root.winfo_width(), self.root.winfo_height()
        ex = -1 if x < EDGE else 1 if x >= width - EDGE else 0
        ey = -1 if y < EDGE else 1 if y >= height - EDGE else 0
        return ex, ey

    def _set_cursor(self, cursor: str) -> None:
        if cursor != self._cursor:
            self._cursor = cursor
            self.root.configure(cursor=cursor)

    def _hover(self, event: tk.Event) -> None:
        self._set_cursor(_RESIZE_CURSORS.get(self._edges(event), ""))

    def _press(self, event: tk.Event) -> None:
        self._hide_menu()
        edges = self._edges(event)
        if edges != (0, 0):
            self._resize_start = (
                edges,
                event.x_root,
                event.y_root,
                self.root.winfo_x(),
                self.root.winfo_y(),
                self.root.winfo_width(),
                self.root.winfo_height(),
            )
        else:
            self._drag_start = (
                event.x_root - self.root.winfo_x(),
                event.y_root - self.root.winfo_y(),
            )
            self._set_cursor("fleur")  # 4-way "move" cursor while dragging

    def _motion(self, event: tk.Event) -> None:
        if self._drag_start is not None:
            dx, dy = self._drag_start
            self.move_to(event.x_root - dx, event.y_root - dy)
        elif self._resize_start is not None:
            self._resize_to(event)

    def _resize_to(self, event: tk.Event) -> None:
        (ex, ey), px, py, x, y, width, height = self._resize_start
        dx, dy = event.x_root - px, event.y_root - py
        min_w, min_h = self.min_size()
        if ex == 1:
            width = max(min_w, width + dx)
        elif ex == -1:
            new_w = max(min_w, width - dx)
            x += width - new_w  # the left edge moves, the right edge stays
            width = new_w
        if ey == 1:
            height = max(min_h, height + dy)
        elif ey == -1:
            new_h = max(min_h, height - dy)
            y += height - new_h
            height = new_h
        self._size = self._applied = (width, height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self._relayout()

    def _release(self, event: tk.Event) -> None:
        self._drag_start = None
        self._resize_start = None
        self._hover(event)  # back to the normal arrow (or an edge cursor)

    # --- menu ---------------------------------------------------------------

    def _show_menu(self, event: tk.Event) -> None:
        self._menu.open(event.x_root, event.y_root)

    def _hide_menu(self, _event: tk.Event | None = None) -> None:
        self._menu.close()

    def _quit(self) -> None:
        if self._on_quit:
            self._on_quit()
        else:
            self.root.destroy()

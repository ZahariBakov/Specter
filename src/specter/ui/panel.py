"""The floating, transparent, always-on-top panel (Tkinter)."""

from __future__ import annotations

import re
import sys
import tkinter as tk
from typing import Callable, Iterable, Tuple

from specter.core.models import Snapshot
from specter.ui.layout import GAP_X, GAP_Y, choose_layout, fit_row, grid_size
from specter.ui.popup import MenuHooks, PopupMenu
from specter.ui.screen import clamp, clamp_point, screen_bounds
from specter.ui.widgets import BG, BORDER, LABEL_FG, VALUE_FG, SlimTile, make_tile

OPACITY_STEPS = [1.0, 0.85, 0.7, 0.55, 0.4]
INTERVAL_STEPS = [500, 1000, 2000]  # ms between sensor reads
DEFAULT_COLUMNS = 2  # layout used until the user resizes the panel
PAD_X, PAD_Y = 14, 12  # frame padding
CHROME_W, CHROME_H = 2 * (PAD_X + 1), 2 * (PAD_Y + 1)  # padding + 1 px border
SLIM_PAD_X, SLIM_PAD_Y = 8, 3  # frame padding in the slim strip
SLIM_CHROME_W, SLIM_CHROME_H = 2 * (SLIM_PAD_X + 1), 2 * (SLIM_PAD_Y + 1)
TILE_ORDER = ("cpu", "gpu", "ram", "disk", "net", "fan")  # unknown devices go last
EDGE = 6  # px along the window edge that start a resize instead of a move
SLIM_EDGE = 4  # the same in the slim strip, which is only ~26 px tall
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

    Made shorter than one tile, the panel turns into a slim strip (about taskbar
    height) with one line per device: "CPU 8% 35°C   RAM 9.9GB ...".
    """

    def __init__(
        self,
        root: tk.Tk,
        opacity: float = 0.85,
        size: Size | None = None,
        hidden_tiles: Iterable[str] = (),
        first_tile: str | None = None,
        locked: bool = False,
        topmost: bool = True,
        interval_ms: int = 1000,
        on_interval: Callable[[int], None] | None = None,
        on_change: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        """`on_change` is called after the user changes a setting in the menu (so the
        app can save it right away)."""
        self.root = root
        self._on_interval = on_interval
        self._on_change = on_change
        self._on_quit = on_quit
        self._hidden: set[str] = set(hidden_tiles)
        self._locked = locked
        self._topmost = topmost
        self._interval = interval_ms
        self._pos: Size | None = None  # where we last put the window

        root.title("Specter")
        root.configure(bg=BG)
        root.overrideredirect(True)  # no title bar / borders
        root.attributes("-topmost", topmost)
        if sys.platform.startswith("linux"):
            root.attributes("-type", "utility")  # hint: no taskbar entry

        self._frame = tk.Frame(
            root, bg=BG, padx=PAD_X, pady=PAD_Y, highlightthickness=1, highlightbackground=BORDER
        )
        self._frame.pack(fill="both", expand=True)

        self._tiles: dict[str, tk.Frame] = {}
        self._labels: dict[str, str] = {}  # tile group -> name shown in the menu
        self._slim_tiles: dict[str, SlimTile] = {}  # the same devices, one line each
        self._cell: Size = (1, 1)  # largest tile seen so far (only grows, so the layout doesn't flicker)
        self._slim_widths: dict[str, int] = {}  # widest each slim tile has been
        self._slim_h = 1  # tallest slim tile
        self._slim = False  # showing the slim strip
        self._size: Size | None = size  # None = fit the content (user never resized)
        self._applied: Size | None = None  # size last given to the window
        self._layout: Size | None = None  # (visible tiles, columns)
        self._first_tile = first_tile  # group of the first visible tile when not all fit
        self._big_arrows = (self._make_arrow("‹", -1, 16), self._make_arrow("›", 1, 16))
        self._slim_arrows = (self._make_arrow("‹", -1, 11), self._make_arrow("›", 1, 11))

        self._drag_start: tuple[int, int] | None = None
        self._resize_start: tuple | None = None
        self._cursor = ""
        self._opacity = tk.DoubleVar(value=opacity)

        self._menu = PopupMenu(
            root,
            MenuHooks(
                opacity_steps=OPACITY_STEPS,
                get_opacity=self._opacity.get,
                on_opacity=self._choose_opacity,
                interval_steps=INTERVAL_STEPS,
                get_interval=lambda: self._interval,
                on_interval=self._choose_interval,
                get_tiles=self.tile_choices,
                on_tile=self.set_tile_shown,
                get_locked=lambda: self._locked,
                on_locked=self.set_locked,
                get_topmost=lambda: self._topmost,
                on_topmost=self.set_topmost,
                on_reset_size=self.reset_size,
                on_quit=self._quit,
            ),
        )

        # Bound on the root window, so they fire for every widget inside it
        # (tiles added later included). The popup is its own toplevel and is not affected.
        root.bind("<Motion>", self._hover)
        root.bind("<ButtonPress-1>", self._press)
        root.bind("<B1-Motion>", self._motion)
        root.bind("<ButtonRelease-1>", self._release)
        root.bind("<Button-3>", self._show_menu)
        root.bind("<Button-4>", self._wheel)  # X11 wheel
        root.bind("<Button-5>", self._wheel)
        root.bind("<MouseWheel>", self._wheel)  # Windows wheel

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
                self._slim_tiles[group] = SlimTile(self._frame, readings[0].label)
                added = True
            tile.update_readings(readings)
            self._slim_tiles[group].update_readings(readings)
            self._labels[group] = readings[0].label

        self._measure(force=added)

    def _measure(self, force: bool = False, reset: bool = False) -> None:
        """Re-measure the shown tiles and lay out again if their size changed.

        `reset` forgets the sizes seen so far (the biggest cell only ever grows), for when
        the set of shown tiles changes.
        """
        shown = self._shown()
        if not shown:
            return
        self._frame.update_idletasks()  # so the tiles report their new size
        old = (1, 1) if reset else self._cell
        old_slim = {} if reset else self._slim_widths
        old_slim_h = 1 if reset else self._slim_h
        cell = (
            max(old[0], max(self._tiles[g].winfo_reqwidth() for g in shown)),
            max(old[1], max(self._tiles[g].winfo_reqheight() for g in shown)),
        )
        slim_widths = {
            g: max(old_slim.get(g, 0), self._slim_tiles[g].winfo_reqwidth()) for g in shown
        }
        slim_h = max(old_slim_h, max(self._slim_tiles[g].winfo_reqheight() for g in shown))
        if force or (cell, slim_widths, slim_h) != (self._cell, self._slim_widths, self._slim_h):
            self._cell, self._slim_widths, self._slim_h = cell, slim_widths, slim_h
            self._relayout(force=force)

    # --- tiles the user can hide ----------------------------------------------

    def _shown(self) -> list[str]:
        """Tile groups on the panel, in display order. If everything is hidden (an edited
        config file), show everything rather than an empty panel."""
        groups = sorted(self._tiles, key=tile_sort_key)
        shown = [g for g in groups if g not in self._hidden]
        return shown or groups

    def tile_choices(self) -> list[tuple[str, str, bool]]:
        """(group, label, shown) for every tile, for the menu."""
        shown = set(self._shown())
        return [(g, self._labels.get(g, g.upper()), g in shown) for g in sorted(self._tiles, key=tile_sort_key)]

    def hidden_tiles(self) -> list[str]:
        return sorted(self._hidden)

    def set_tile_shown(self, group: str, shown: bool) -> None:
        """Show or hide one tile. The last shown tile can't be hidden."""
        if group not in self._tiles:
            return
        if shown:
            self._hidden.discard(group)
        elif group in self._shown():
            if len(self._shown()) == 1:
                return
            self._hidden.add(group)
        else:
            return
        self._measure(force=True, reset=True)
        self._changed()

    # --- size and layout ----------------------------------------------------

    def size(self) -> Size | None:
        """Size chosen by the user, or None if the panel still fits its content."""
        return self._size

    def current_size(self) -> Size:
        return self._applied or (self.root.winfo_reqwidth(), self.root.winfo_reqheight())

    def set_size(self, width: int, height: int) -> None:
        self._size = (width, height)
        self._relayout()

    def reset_size(self) -> None:
        """Back to fitting the content."""
        self._size = None
        self._relayout()
        self._changed()

    def _is_slim(self, height: int) -> bool:
        """Too short for one normal tile: show the slim strip."""
        return height < self._cell[1] + CHROME_H

    def _arrows_width(self, slim: bool) -> int:
        arrows = self._slim_arrows if slim else self._big_arrows
        return 2 * (max(a.winfo_reqwidth() for a in arrows) + ARROW_GAP)

    def min_size(self, height: int | None = None) -> Size:
        """Smallest window: one slim tile high, and one tile (plus the arrows if there
        is more than one tile) wide. With `height`, the smallest width at that height.
        """
        slim = height is None or self._is_slim(height)
        cell_w = max(self._slim_widths.values(), default=1) if slim else self._cell[0]
        if len(self._shown()) > 1:
            cell_w += self._arrows_width(slim)
        chrome_w = SLIM_CHROME_W if slim else CHROME_W
        return cell_w + chrome_w, self._slim_h + SLIM_CHROME_H

    def _relayout(self, force: bool = False) -> None:
        count = len(self._shown())
        if count == 0:
            return
        if self._size is None:
            slim = False
            cell_w, cell_h = self._cell
            columns = min(DEFAULT_COLUMNS, count)
            need_w, need_h = grid_size(count, columns, cell_w, cell_h)
            size = (need_w + CHROME_W, need_h + CHROME_H)
            layout = (count, columns)
        else:
            _, min_h = self.min_size()
            height = max(self._size[1], min_h)
            min_w, _ = self.min_size(height)
            size = (max(self._size[0], min_w), height)
            self._size = size
            slim = self._is_slim(height)
            if slim:  # one row, each tile as wide as it needs
                widths = [self._slim_widths[g] for g in self._shown()]
                visible = fit_row(
                    widths, size[0] - SLIM_CHROME_W, self._arrows_width(True), self._first_index()
                )
                layout = (visible, visible)
            else:
                layout = choose_layout(
                    count,
                    self._cell[0],
                    self._cell[1],
                    size[0] - CHROME_W,
                    size[1] - CHROME_H,
                    self._arrows_width(False),
                )

        if slim != self._slim:
            self._slim = slim
            if slim:
                self._frame.configure(padx=SLIM_PAD_X, pady=SLIM_PAD_Y)
            else:
                self._frame.configure(padx=PAD_X, pady=PAD_Y)
            force = True
        if size != self._applied:
            self._applied = size
            self.root.geometry(f"{size[0]}x{size[1]}")
            self._keep_on_screen()  # a bigger window may now stick out
        if force or layout != self._layout:
            self._layout = layout
            self._place_tiles()

    def _place_tiles(self) -> None:
        frame = self._frame
        for widget in frame.grid_slaves():
            widget.grid_forget()
        source = self._slim_tiles if self._slim else self._tiles
        tiles = [source[group] for group in self._shown()]
        arrows = self._slim_arrows if self._slim else self._big_arrows
        for i in range(len(tiles) + 3):
            frame.columnconfigure(i, weight=0)
            frame.rowconfigure(i, weight=0)

        visible, columns = self._layout or (len(tiles), 1)
        rows = -(-visible // columns)
        cycling = visible < len(tiles)
        # With arrows, column 0 and the last column hold them and the tiles sit in between.
        offset = 1 if cycling else 0
        if cycling:
            first = self._first_index()
            shown = [tiles[(first + i) % len(tiles)] for i in range(visible)]
            arrows[0].grid(row=0, column=0, rowspan=rows, padx=(0, ARROW_GAP))
            arrows[1].grid(row=0, column=columns + 1, rowspan=rows, padx=(ARROW_GAP, 0))
        else:
            shown = tiles

        for i, tile in enumerate(shown):
            row, column = divmod(i, columns)
            tile.grid(
                row=row,
                column=column + offset,
                # Centred between the arrows; slim tiles centred vertically in the strip.
                sticky="" if cycling else "w" if self._slim else "nw",
                padx=(0 if column == 0 else GAP_X, 0),
                pady=(0 if row == 0 else GAP_Y, 0),
            )
        # Spread any extra space evenly between the tiles.
        for column in range(columns):
            frame.columnconfigure(column + offset, weight=1)
        for row in range(rows):
            frame.rowconfigure(row, weight=1)

    def _make_arrow(self, text: str, step: int, font_size: int) -> tk.Label:
        arrow = tk.Label(
            self._frame,
            text=text,
            bg=BG,
            fg=LABEL_FG,
            font=("TkDefaultFont", font_size, "bold"),
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
        groups = self._shown()
        if self._layout and self._layout[0] < len(groups):
            self._first_tile = groups[(self._first_index() + step) % len(groups)]
            self._relayout(force=True)  # the slim strip may fit a different number of tiles
            self._changed()

    def _first_index(self) -> int:
        """Position of the first visible tile among the shown ones (0 if it is gone)."""
        groups = self._shown()
        return groups.index(self._first_tile) if self._first_tile in groups else 0

    def first_tile(self) -> str | None:
        """Group of the tile the panel starts cycling from (saved in the config)."""
        return self._first_tile

    def _wheel(self, event: tk.Event) -> None:
        """Mouse wheel cycles the tiles when the arrows are showing: up = back, down = forward."""
        up = event.num == 4 or getattr(event, "delta", 0) > 0  # X11 buttons 4/5, Windows delta
        self._cycle(-1 if up else 1)

    # --- opacity ------------------------------------------------------------

    def set_opacity(self, value: float) -> None:
        value = min(1.0, max(0.2, value))
        self._opacity.set(value)
        # Linux/X11 needs a running compositor for this to have any effect.
        self.root.attributes("-alpha", value)

    def opacity(self) -> float:
        return self._opacity.get()

    def _choose_opacity(self, value: float) -> None:
        self.set_opacity(value)
        self._changed()

    # --- other settings -------------------------------------------------------

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def topmost(self) -> bool:
        return self._topmost

    def set_locked(self, locked: bool) -> None:
        """Locked: the panel can't be moved or resized (the menu still works)."""
        self._locked = locked
        self._drag_start = self._resize_start = None
        self._set_cursor("")
        self._changed()

    def set_topmost(self, topmost: bool) -> None:
        self._topmost = topmost
        self.root.attributes("-topmost", topmost)
        self._changed()

    def _choose_interval(self, interval_ms: int) -> None:
        self._interval = interval_ms
        if self._on_interval:
            self._on_interval(interval_ms)
        self._changed()

    def _changed(self) -> None:
        if self._on_change:
            self._on_change()

    # --- position -----------------------------------------------------------

    def move_to(self, x: int, y: int) -> None:
        """Move the window, but never off the desktop (all monitors together)."""
        width, height = self.current_size()
        x, y = clamp(x, y, width, height, screen_bounds(self.root))
        self._pos = (x, y)
        self.root.geometry(f"+{x}+{y}")

    def _keep_on_screen(self) -> None:
        """After a size change, pull the window back in if it now sticks out."""
        if self._pos is not None:
            self.move_to(*self._pos)

    def position(self) -> tuple[int, int]:
        return self.root.winfo_x(), self.root.winfo_y()

    # --- mouse: move and resize ---------------------------------------------

    def _edges(self, event: tk.Event) -> tuple[int, int]:
        """Which window edges the pointer is on: -1 left/top, 1 right/bottom, 0 none."""
        x = event.x_root - self.root.winfo_rootx()
        y = event.y_root - self.root.winfo_rooty()
        width, height = self.root.winfo_width(), self.root.winfo_height()
        edge = SLIM_EDGE if self._slim else EDGE
        ex = -1 if x < edge else 1 if x >= width - edge else 0
        ey = -1 if y < edge else 1 if y >= height - edge else 0
        return ex, ey

    def _set_cursor(self, cursor: str) -> None:
        if cursor != self._cursor:
            self._cursor = cursor
            self.root.configure(cursor=cursor)

    def _hover(self, event: tk.Event) -> None:
        self._set_cursor("" if self._locked else _RESIZE_CURSORS.get(self._edges(event), ""))

    def _press(self, event: tk.Event) -> None:
        self._hide_menu()
        if self._locked:
            return
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
        # The pointer can't drag an edge out of the desktop.
        pointer_x, pointer_y = clamp_point(event.x_root, event.y_root, screen_bounds(self.root))
        dx, dy = pointer_x - px, pointer_y - py
        _, min_h = self.min_size()
        if ey == 1:
            height = max(min_h, height + dy)
        elif ey == -1:
            new_h = max(min_h, height - dy)
            y += height - new_h
            height = new_h
        min_w, _ = self.min_size(height)  # the slim strip can be narrower
        if ex == 1:
            width = max(min_w, width + dx)
        elif ex == -1:
            new_w = max(min_w, width - dx)
            x += width - new_w  # the left edge moves, the right edge stays
            width = new_w
        self._size = self._applied = (width, height)
        self._pos = (x, y)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self._relayout()

    def _release(self, event: tk.Event) -> None:
        self._keep_on_screen()  # e.g. the minimum size made the window stick out
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

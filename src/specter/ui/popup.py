"""Custom right-click popup (prettier than Tk's built-in menu)."""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

from specter.ui.screen import clamp, screen_bounds

BG = "#1a1d22"
BORDER = "#323843"
FG = "#e6e8eb"
MUTED = "#7d8794"
HOVER = "#272c34"
ACCENT = "#2f6fec"
PILL_BG = "#22262d"
DANGER = "#ff6b6b"

SAFETY_TIMEOUT_MS = 20_000  # close by itself if left open and untouched
TILE_COLUMNS = 3  # tile toggles per row

TileChoice = Tuple[str, str, bool]  # (group, label, shown)


@dataclass
class MenuHooks:
    """Everything the menu reads and changes. The panel fills it in."""

    opacity_steps: Sequence[float]
    get_opacity: Callable[[], float]
    on_opacity: Callable[[float], None]
    interval_steps: Sequence[int]  # ms
    get_interval: Callable[[], int]
    on_interval: Callable[[int], None]
    get_tiles: Callable[[], List[TileChoice]]
    on_tile: Callable[[str, bool], None]
    get_sparklines: Callable[[], bool]
    on_sparklines: Callable[[bool], None]
    get_locked: Callable[[], bool]
    on_locked: Callable[[bool], None]
    get_topmost: Callable[[], bool]
    on_topmost: Callable[[bool], None]
    on_reset_size: Callable[[], None]
    on_quit: Callable[[], None]
    # "Start at login": left out (None) where it isn't supported.
    get_autostart: Optional[Callable[[], bool]] = None
    on_autostart: Optional[Callable[[bool], object]] = None
    # "Click-through": left out (None) where it isn't supported.
    get_click_through: Optional[Callable[[], bool]] = None
    on_click_through: Optional[Callable[[bool], None]] = None


class PopupMenu:
    """
    OPACITY / TILES / UPDATE pills, two toggles, Reset size and Quit.

    While open it holds a global mouse grab, like a normal menu, so a click
    anywhere outside closes it. Esc closes it too.
    """

    def __init__(self, master: tk.Misc, hooks: MenuHooks) -> None:
        self._master = master
        self._hooks = hooks
        self._win: tk.Toplevel | None = None
        self._timer: str | None = None

    # --- public -------------------------------------------------------------

    def is_open(self) -> bool:
        return self._win is not None

    def open(self, x: int, y: int) -> None:
        self.close()
        hooks = self._hooks
        win = tk.Toplevel(self._master, bg=BORDER, padx=1, pady=1)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        self._win = win

        body = tk.Frame(win, bg=BG, padx=6, pady=6)
        body.pack(fill="both", expand=True)

        self._heading(body, "OPACITY", first=True)
        self._pills(
            body,
            [(f"{round(step * 100)}", step) for step in hooks.opacity_steps],
            is_on=lambda step: abs(step - hooks.get_opacity()) < 0.03,
            choose=hooks.on_opacity,
        )

        tiles = hooks.get_tiles()
        if tiles:
            self._heading(body, "TILES")
            self._pills(
                body,
                [(label, group) for group, label, _on in tiles],
                is_on=lambda group: any(on for g, _l, on in hooks.get_tiles() if g == group),
                choose=lambda group: hooks.on_tile(
                    group, not any(on for g, _l, on in hooks.get_tiles() if g == group)
                ),
                columns=TILE_COLUMNS,
            )

        self._heading(body, "UPDATE")
        self._pills(
            body,
            [(f"{ms / 1000:g}s", ms) for ms in hooks.interval_steps],
            is_on=lambda ms: ms == hooks.get_interval(),
            choose=hooks.on_interval,
        )

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", padx=2, pady=(0, 4))
        self._toggle(body, "Sparklines", hooks.get_sparklines, hooks.on_sparklines)
        self._toggle(body, "Lock position", hooks.get_locked, hooks.on_locked)
        self._toggle(body, "Always on top", hooks.get_topmost, hooks.on_topmost)
        if hooks.get_click_through and hooks.on_click_through:
            self._toggle(body, "Click-through", hooks.get_click_through, hooks.on_click_through)
        if hooks.get_autostart and hooks.on_autostart:
            self._toggle(body, "Start at login", hooks.get_autostart, hooks.on_autostart)
        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", padx=2, pady=4)
        self._item(body, "Reset size", self._reset_size)
        self._item(body, "Quit Specter", self._quit, fg=DANGER)

        win.bind("<ButtonPress>", self._on_press, add="+")
        win.bind("<Escape>", lambda _e: self.close())
        if sys.platform == "win32":
            # Windows has no global grab, so clicks in other apps never reach us: close
            # when the menu loses focus instead.
            win.bind("<FocusOut>", lambda e: self.close() if e.widget is win else None)
        win.bind("<Motion>", lambda _e: self._restart_timer(), add="+")

        # Keep it on screen (any monitor).
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x, y = clamp(x, y, w, h, screen_bounds(win))
        win.geometry(f"+{x}+{y}")
        win.deiconify()
        win.wait_visibility()
        win.focus_force()
        try:
            win.grab_set_global()
        except tk.TclError:
            win.grab_set()  # another app holds the mouse; fall back to a local grab
        self._restart_timer()

    def close(self) -> None:
        if self._timer is not None:
            self._master.after_cancel(self._timer)
            self._timer = None
        if self._win is not None:
            try:
                self._win.grab_release()
            finally:
                self._win.destroy()
                self._win = None

    # --- building blocks ----------------------------------------------------

    def _heading(self, parent: tk.Misc, text: str, first: bool = False) -> None:
        tk.Label(
            parent, text=text, bg=BG, fg=MUTED, font=("TkDefaultFont", 8, "bold"), anchor="w"
        ).pack(fill="x", padx=8, pady=(4 if first else 0, 6))

    def _pills(
        self,
        parent: tk.Misc,
        items: Sequence[Tuple[str, Any]],
        is_on: Callable[[Any], bool],
        choose: Callable[[Any], None],
        columns: int = 0,
    ) -> None:
        """A row (or a grid, with `columns`) of small buttons; the ones that are on turn blue."""
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="x", padx=8, pady=(0, 8))
        pills: list[tuple[tk.Label, Any]] = []

        def refresh() -> None:
            for pill, value in pills:
                on = is_on(value)
                pill.config(bg=ACCENT if on else PILL_BG, fg="#ffffff" if on else FG)

        def click(value: Any) -> None:
            choose(value)
            refresh()
            self._restart_timer()

        def hover(pill: tk.Label, value: Any, entering: bool) -> None:
            if not is_on(value):  # keep the "on" colour
                pill.config(bg=HOVER if entering else PILL_BG)

        for i, (text, value) in enumerate(items):
            pill = tk.Label(
                frame,
                text=text,
                bg=PILL_BG,
                fg=FG,
                font=("TkDefaultFont", 9),
                padx=8,
                pady=4,
                cursor="hand2",
            )
            row, column = divmod(i, columns) if columns else (0, i)
            pill.grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 4, 0),
                pady=(0 if row == 0 else 4, 0),
            )
            pill.bind("<ButtonRelease-1>", lambda _e, v=value: click(v))
            pill.bind("<Enter>", lambda _e, p=pill, v=value: hover(p, v, True))
            pill.bind("<Leave>", lambda _e, p=pill, v=value: hover(p, v, False))
            pills.append((pill, value))
        refresh()

    def _toggle(
        self,
        parent: tk.Misc,
        text: str,
        get: Callable[[], bool],
        set_: Callable[[bool], None],
    ) -> None:
        """A row with a check box on the left."""
        row = tk.Frame(parent, bg=BG, cursor="hand2")
        row.pack(fill="x")
        box = tk.Label(row, width=2, font=("TkDefaultFont", 9, "bold"), cursor="hand2")
        box.pack(side="left", padx=(10, 0), pady=6)
        label = tk.Label(
            row, text=text, bg=BG, fg=FG, font=("TkDefaultFont", 10), anchor="w", padx=8,
            cursor="hand2",
        )
        label.pack(side="left", fill="x", expand=True, pady=6)

        def refresh() -> None:
            on = get()
            box.config(text="✓" if on else "", bg=ACCENT if on else PILL_BG, fg="#ffffff")

        def paint(color: str) -> None:
            row.config(bg=color)
            label.config(bg=color)

        def click(_event: tk.Event) -> None:
            set_(not get())
            refresh()
            self._restart_timer()

        for widget in (row, box, label):
            widget.bind("<ButtonRelease-1>", click)
            widget.bind("<Enter>", lambda _e: paint(HOVER))
            widget.bind("<Leave>", lambda _e: paint(BG))
        refresh()

    def _item(self, parent: tk.Misc, text: str, command: Callable[[], None], fg: str = FG) -> None:
        row = tk.Label(
            parent,
            text=text,
            bg=BG,
            fg=fg,
            font=("TkDefaultFont", 10),
            anchor="w",
            padx=10,
            pady=6,
            cursor="hand2",
        )
        row.pack(fill="x")
        row.bind("<Enter>", lambda _e: row.config(bg=HOVER))
        row.bind("<Leave>", lambda _e: row.config(bg=BG))
        row.bind("<ButtonRelease-1>", lambda _e: command())

    # --- internals ----------------------------------------------------------

    def _on_press(self, event: tk.Event) -> None:
        win = self._win
        if win is None:
            return
        x0, y0 = win.winfo_rootx(), win.winfo_rooty()
        inside = x0 <= event.x_root < x0 + win.winfo_width() and y0 <= event.y_root < y0 + win.winfo_height()
        if not inside:
            self.close()

    def _reset_size(self) -> None:
        self.close()
        self._hooks.on_reset_size()

    def _quit(self) -> None:
        self.close()
        self._hooks.on_quit()

    def _restart_timer(self) -> None:
        if self._timer is not None:
            self._master.after_cancel(self._timer)
        self._timer = self._master.after(SAFETY_TIMEOUT_MS, self.close)

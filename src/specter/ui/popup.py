"""Custom right-click popup (prettier than Tk's built-in menu)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Sequence

BG = "#1a1d22"
BORDER = "#323843"
FG = "#e6e8eb"
MUTED = "#7d8794"
HOVER = "#272c34"
ACCENT = "#2f6fec"
PILL_BG = "#22262d"
DANGER = "#ff6b6b"

SAFETY_TIMEOUT_MS = 20_000  # close by itself if left open and untouched


class PopupMenu:
    """
    Opacity row (one-click buttons) + Quit.

    While open it holds a global mouse grab, like a normal menu, so a click
    anywhere outside closes it. Esc closes it too.
    """

    def __init__(
        self,
        master: tk.Misc,
        opacity_steps: Sequence[float],
        get_opacity: Callable[[], float],
        on_opacity: Callable[[float], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._master = master
        self._steps = list(opacity_steps)
        self._get_opacity = get_opacity
        self._on_opacity = on_opacity
        self._on_quit = on_quit
        self._win: tk.Toplevel | None = None
        self._pills: dict[float, tk.Label] = {}
        self._timer: str | None = None

    # --- public -------------------------------------------------------------

    def is_open(self) -> bool:
        return self._win is not None

    def open(self, x: int, y: int) -> None:
        self.close()
        win = tk.Toplevel(self._master, bg=BORDER, padx=1, pady=1)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        self._win = win

        body = tk.Frame(win, bg=BG, padx=6, pady=6)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="OPACITY", bg=BG, fg=MUTED, font=("TkDefaultFont", 8, "bold"), anchor="w"
        ).pack(fill="x", padx=8, pady=(4, 6))

        pills = tk.Frame(body, bg=BG)
        pills.pack(fill="x", padx=8, pady=(0, 8))
        self._pills.clear()
        for i, step in enumerate(self._steps):
            pill = tk.Label(
                pills,
                text=f"{int(step * 100)}",
                bg=PILL_BG,
                fg=FG,
                font=("TkDefaultFont", 9),
                padx=8,
                pady=4,
                cursor="hand2",
            )
            pill.grid(row=0, column=i, padx=(0 if i == 0 else 4, 0))
            pill.bind("<ButtonRelease-1>", lambda _e, s=step: self._choose_opacity(s))
            pill.bind("<Enter>", lambda _e, p=pill, s=step: self._pill_hover(p, s, True))
            pill.bind("<Leave>", lambda _e, p=pill, s=step: self._pill_hover(p, s, False))
            self._pills[step] = pill
        self._refresh_pills()

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", padx=2, pady=(0, 4))

        self._item(body, "Quit Specter", self._quit, fg=DANGER)

        win.bind("<ButtonPress>", self._on_press, add="+")
        win.bind("<Escape>", lambda _e: self.close())
        win.bind("<Motion>", lambda _e: self._restart_timer(), add="+")

        # Keep it on screen.
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = min(x, win.winfo_screenwidth() - w - 4)
        y = min(y, win.winfo_screenheight() - h - 4)
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

    # --- internals ----------------------------------------------------------

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

    def _on_press(self, event: tk.Event) -> None:
        win = self._win
        if win is None:
            return
        x0, y0 = win.winfo_rootx(), win.winfo_rooty()
        inside = x0 <= event.x_root < x0 + win.winfo_width() and y0 <= event.y_root < y0 + win.winfo_height()
        if not inside:
            self.close()

    def _choose_opacity(self, step: float) -> None:
        self._on_opacity(step)
        self._refresh_pills()
        self._restart_timer()

    def _refresh_pills(self) -> None:
        current = self._get_opacity()
        for step, pill in self._pills.items():
            selected = abs(step - current) < 0.03
            pill.config(bg=ACCENT if selected else PILL_BG, fg="#ffffff" if selected else FG)

    def _pill_hover(self, pill: tk.Label, step: float, entering: bool) -> None:
        if abs(step - self._get_opacity()) < 0.03:
            return  # keep the selected colour
        pill.config(bg=HOVER if entering else PILL_BG)

    def _quit(self) -> None:
        self.close()
        self._on_quit()

    def _restart_timer(self) -> None:
        if self._timer is not None:
            self._master.after_cancel(self._timer)
        self._timer = self._master.after(SAFETY_TIMEOUT_MS, self.close)

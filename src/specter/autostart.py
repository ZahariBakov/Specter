"""Start Specter when the user logs in (Linux: an XDG autostart entry).

Windows is not done yet: `supported()` is False there, so the menu hides the toggle.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

ENTRY_NAME = "specter.desktop"


def supported() -> bool:
    return sys.platform.startswith("linux")


def entry_path() -> Path:
    """~/.config/autostart/specter.desktop (honours XDG_CONFIG_HOME)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / ENTRY_NAME


def command() -> list[str]:
    """How to start this copy of Specter: the built binary, or this Python running the package."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return [sys.executable]
    return [sys.executable, "-m", "specter"]


def _quote(arg: str) -> str:
    # The Exec key of a .desktop file: quote arguments with spaces or special characters
    # in double quotes, and escape the few characters that stay special inside them.
    if arg and all(c.isalnum() or c in "-_./:=+@," for c in arg):
        return arg
    escaped = (
        arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    )
    return '"' + escaped.replace("%", "%%") + '"'


def desktop_entry(cmd: list[str] | None = None) -> str:
    exec_line = " ".join(_quote(a) for a in (cmd or command()))
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Specter\n"
        "Comment=Hardware monitor panel\n"
        f"Exec={exec_line}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def is_enabled() -> bool:
    return supported() and entry_path().is_file()


def set_enabled(enabled: bool) -> bool:
    """Create or remove the autostart entry. Returns False if it could not be done."""
    if not supported():
        return False
    path = entry_path()
    try:
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(desktop_entry(), encoding="utf-8")
        else:
            path.unlink()
    except FileNotFoundError:
        pass  # already off
    except OSError:
        log.warning("Could not %s %s", "write" if enabled else "remove", path)
        return False
    return True

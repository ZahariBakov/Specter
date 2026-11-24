"""Start Specter when the user logs in.

Linux: an XDG autostart entry (~/.config/autostart/specter.desktop).
Windows: a value in the per-user Run key (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run),
no admin rights needed.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

ENTRY_NAME = "specter.desktop"

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Specter"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _is_windows() -> bool:
    return sys.platform == "win32"


def supported() -> bool:
    return _is_linux() or _is_windows()


def entry_path() -> Path:
    """~/.config/autostart/specter.desktop (honours XDG_CONFIG_HOME)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / ENTRY_NAME


def command() -> list[str]:
    """How to start this copy of Specter: the built binary, or this Python running the package."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return [sys.executable]
    return [sys.executable, "-m", "specter"]


def windows_command() -> list[str]:
    """Like `command()`, but prefer pythonw.exe so no console window opens at login."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw) if pythonw.is_file() else sys.executable
    return [exe, "-m", "specter"]


def run_value(cmd: list[str] | None = None) -> str:
    """The Run key value: a Windows command line with arguments quoted where needed."""
    return subprocess.list2cmdline(cmd or windows_command())


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


# --- Windows registry helpers (small so tests can replace them) ---------------------------

def _reg_get(name: str) -> str | None:
    """The Run value `name`, or None if it doesn't exist."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _type = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    return str(value)


def _reg_set(name: str, value: str) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _reg_delete(name: str) -> None:
    """Remove the Run value `name`; a missing value is fine."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def is_enabled() -> bool:
    if _is_windows():
        try:
            return _reg_get(VALUE_NAME) is not None
        except OSError:
            log.warning("Could not read the Run registry key")
            return False
    return _is_linux() and entry_path().is_file()


def set_enabled(enabled: bool) -> bool:
    """Create or remove the autostart entry. Returns False if it could not be done."""
    if _is_windows():
        try:
            if enabled:
                _reg_set(VALUE_NAME, run_value())
            else:
                _reg_delete(VALUE_NAME)
        except OSError:
            log.warning("Could not %s the Run registry value", "write" if enabled else "remove")
            return False
        return True
    if not _is_linux():
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

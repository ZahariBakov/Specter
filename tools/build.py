"""Builds a single-file Specter program with PyInstaller.

    pip install -e ".[nvidia,build]"
    python tools/build.py          # -> dist/specter  (dist/specter.exe on Windows)

Build on the oldest system you want it to run on: the program needs at least the glibc of the
machine that built it. Windows builds must be made on Windows (not tried yet).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ASSETS = SRC / "specter" / "assets"


def main() -> int:
    try:
        import PyInstaller.__main__ as pyinstaller
    except ImportError:
        print('PyInstaller is missing: pip install -e ".[build]"', file=sys.stderr)
        return 1

    args = [
        str(SRC / "specter" / "__main__.py"),
        "--name", "specter",
        "--onefile",
        "--windowed",  # no console window on Windows; harmless on Linux
        "--noconfirm",
        "--clean",
        "--paths", str(SRC),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--add-data", f"{ASSETS}{os.pathsep}specter/assets",
        "--icon", str(ASSETS / ("icon.ico" if sys.platform == "win32" else "icon.png")),
    ]
    # The NVIDIA library is imported inside a try block, so PyInstaller can't see it.
    if importlib.util.find_spec("pynvml") is not None:
        args += ["--hidden-import", "pynvml"]
    else:
        print('Note: nvidia-ml-py is not installed, so this build has no GPU sensors. '
              'Install the "nvidia" extra first to include them.')
    pyinstaller.run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

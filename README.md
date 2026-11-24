# Specter

A small hardware monitor for **Linux** and **Windows**: a compact, frameless, always-on-top panel
with adjustable opacity, so it can sit on your desktop without getting in the way.
Inspired by Speccy and GPU Temp.

![The panel](docs/images/panel.png)

## What it shows

| Tile | Values |
|---|---|
| CPU | load, temperature (Linux) |
| GPU | load, memory, temperature (NVIDIA, through NVML) |
| RAM | used / total |
| DISK | read and write speed |
| NET | download and upload speed |
| FAN | fastest spinning fan (Linux) |

Values turn yellow and red when they get high (load from 60 %, temperatures from 70 °C).
A tile with a bar can also draw a short history graph (sparkline).

## Using it

- **Move:** drag the panel with the left mouse button. It stops at the edge of the desktop but
  can cross from one monitor to the next.
- **Resize:** drag an edge or a corner. The tiles rearrange into a row, a column or a grid. When
  not all fit, you get fewer tiles with ‹ › arrows (or the mouse wheel) to cycle through them.
  Make it only about as tall as a taskbar and it becomes a one-line strip:

  ![The slim strip](docs/images/slim.png)

- **Right-click** for the menu:

  ![The menu](docs/images/menu.png)

  Opacity, which tiles to show, how often to read the sensors, sparklines, lock the position,
  click-through (X11), always on top, start at login (Linux), reset the size, quit.
  Settings are saved when you change them, in `config.json` in your user config folder
  (`~/.config/specter/` on Linux).

**Click-through** lets mouse clicks go to the window under the panel (handy over a video or a
game). A small blue dot appears in the panel's top-left corner: click it to get the menu back and
switch click-through off. It is not saved, so a restart is always clickable.

## Install and run

Requires Python 3.8+ with Tkinter. On Linux, prefer the system Python (`python3-tk`): its Tk draws
smooth fonts and uses your cursor theme, while the Tk bundled with uv-managed Pythons does not.

```bash
python -m venv .venv            # or: uv venv --python /usr/bin/python3
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[nvidia]"      # or: uv pip install -e ".[nvidia]"
specter                         # or: python -m specter
```

The `nvidia` extra installs `nvidia-ml-py` for NVIDIA GPU sensors. Without it, or without an
NVIDIA driver, the GPU tile is simply not shown (a line in the log says why).

### A single-file program

```bash
pip install -e ".[nvidia,build]"
python tools/build.py           # -> dist/specter
```

The result runs without Python. Build it on the oldest Linux you want it to run on: it needs at
least the glibc of the machine that built it.

## Known limits

- **Opacity needs a compositor.** On Linux/X11 that is KWin, Mutter, Picom and so on. Without one
  the panel stays fully opaque.
- CPU temperature and fan speed are Linux only for now. On Windows they need a different source
  (planned).
- Only NVIDIA GPUs are read. AMD is planned.
- Windows support is written but has not been tried yet. Expect rough edges.
- "Start at login" and click-through only work on Linux (X11) so far.

## Development

```bash
pip install -e ".[dev,nvidia]"
pytest
```

Project notes for contributors are in `CLAUDE.md`, the roadmap is in `PLAN.md`.
The icon is drawn by `tools/make_icon.py`.

## Roadmap

Windows testing, CPU temperature on Windows, alerts, AMD GPUs, themes, a detailed hardware specs
view. See `PLAN.md`.

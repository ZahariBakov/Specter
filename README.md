# Specter

A small cross-platform hardware monitor for **Linux** and **Windows**.

Specter shows your machine's parameters (CPU, GPU, RAM, temperatures and more) in a compact,
always-on-top panel with **adjustable transparency**, so it can sit over your desktop without
getting in the way.

Inspired by tools like Speccy and GPU Temp, but cross-platform and focused on a lightweight overlay panel.

## Status

🚧 Early development. The panel shows CPU load and temperature, NVIDIA GPU load / memory /
temperature, RAM, disk and network speed, and fan speed (Linux).

## Running from source

Requires Python 3.8+ with Tkinter. On Linux, prefer the system Python (`python3-tk`): its Tk draws smooth fonts and uses your cursor theme, while the Tk bundled with uv-managed Pythons does not.

```bash
python -m venv .venv            # or: uv venv --python /usr/bin/python3
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev,nvidia]"  # or: uv pip install -e ".[dev,nvidia]"
specter                         # or: python -m specter
```

The `nvidia` extra installs `nvidia-ml-py` for NVIDIA GPU sensors. Without it, or without an
NVIDIA driver, the GPU tile is simply not shown.

Drag the panel with the left mouse button, or drag its edges to resize it: the tiles rearrange
into a row, a column or a grid, and a small panel shows fewer tiles with ‹ › arrows to cycle.
Right-click it to change opacity or quit.
Run the tests with `pytest`.

## Planned features

- Live sensor values: CPU / GPU load and temperature, RAM usage, and more
- Small floating panel with adjustable opacity
- Works on Linux and Windows
- Detailed hardware specs view (later)

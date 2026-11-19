# Specter

A small cross-platform hardware monitor for **Linux** and **Windows**.

Specter shows your machine's parameters (CPU, GPU, RAM, temperatures and more) in a compact,
always-on-top panel with **adjustable transparency**, so it can sit over your desktop without
getting in the way.

Inspired by tools like Speccy and GPU Temp, but cross-platform and focused on a lightweight overlay panel.

## Status

🚧 Early development: a minimal panel shows CPU load and RAM usage.

## Running from source

Requires Python 3.8+ with Tkinter. On Linux, prefer the system Python (`python3-tk`): its Tk draws smooth fonts and uses your cursor theme, while the Tk bundled with uv-managed Pythons does not.

```bash
python -m venv .venv            # or: uv venv --python /usr/bin/python3
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"         # or: uv pip install -e ".[dev]"
specter                         # or: python -m specter
```

Drag the panel with the left mouse button. Right-click it to change opacity or quit.
Run the tests with `pytest`.

## Planned features

- Live sensor values: CPU / GPU load and temperature, RAM usage, and more
- Small floating panel with adjustable opacity
- Works on Linux and Windows
- Detailed hardware specs view (later)

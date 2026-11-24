# Specter — instructions for Claude

Small hardware monitor for **Linux and Windows**: a compact, frameless, always-on-top panel
with adjustable opacity (like Speccy + GPU Temp). Repo: https://github.com/ZahariBakov/Specter

## Rules (always follow)

- **The user runs all git commands.** Never commit, push, add or branch. Edit files, then
  suggest a commit message.
- **Qt / PySide6 is not allowed on the user's PC.** The UI is **Tkinter**. Don't propose Qt.
- **Keep Python 3.8 compatible** (`requires-python = ">=3.8"`). Start every module with
  `from __future__ import annotations`. Don't use 3.9+ runtime features: `match`,
  `str.removeprefix`, `list[int]` / `X | Y` outside annotations, `zoneinfo`, etc.
- Tk is not thread-safe: only the main thread touches widgets. Background threads pass data
  through a `queue.Queue` (see `app.py`).
- A broken or missing sensor must never crash the app. Providers return nothing or log, and the
  registry and poller already catch exceptions.

## Dev environment (user's machine)

- Ubuntu 20.04-era system with **KDE Plasma on X11** (display `:1`), glibc 2.31, NVIDIA T600. The OS can't be upgraded.
- Use the **system Python 3.8** (its Tk 8.6 has Xft fonts and themed cursors). Don't use
  uv-downloaded Pythons: their bundled Tk is `no-xft` (pixel fonts, old X cursors).
- `python3 -m venv` is broken (no `python3-venv`), so create venvs with uv:
  ```bash
  uv venv --python /usr/bin/python3        # creates .venv/ (gitignored)
  uv pip install -e ".[dev,nvidia]"
  .venv/bin/specter                        # run
  .venv/bin/pytest                         # tests
  ```
  Don't use `uv sync` / `uv run` (they create `uv.lock`). Don't leave `uv.lock` in the repo.
- Opacity needs KWin compositing. It was off (`OpenGLIsUnsafe=true` in `~/.config/kwinrc`) and
  was re-enabled. If opacity "stops working", check
  `qdbus org.kde.KWin /Compositor org.kde.kwin.Compositing.active`.
- For your own testing, use a venv in the scratchpad, not the repo. GUI screenshots: run on
  `DISPLAY=:1`, capture with `xwd -root -silent` in a thread with a timeout, wait about 1 s after
  opening a window (KWin fades windows in). Don't use ImageMagick `import` while a menu holds a grab
  (it hung). Clean up `__pycache__` afterwards.

## Architecture

```
sensors/ (providers) ──► core/poller.py (thread) ──► queue ──► ui/panel.py (Tk main thread)
        each returns list[Reading]      builds Snapshot       app.py pumps queue every 100 ms
```

| Path | Role |
|---|---|
| `src/specter/core/models.py` | `Reading(key, label, value, unit, maximum, short)`, `Snapshot(time, readings)` |
| `src/specter/core/poller.py` | Background thread. Calls every provider each `interval_ms` and passes the result to a callback |
| `src/specter/sensors/base.py` | `SensorProvider`: `is_available()`, `read() -> list[Reading]`, `priority` (lower = better, runs first), `unavailable_reason` |
| `src/specter/sensors/registry.py` | `create_providers()` (sorted by priority; the poller keeps the **first** value per key), `provider_report()`. Register providers in `_candidates()`, GPU backends in `_gpu_backends()` |
| `src/specter/diagnostics.py` | `specter --sensors` (who supplies which key, why providers are off) and `--dump` (raw platform data for bug reports) |
| `src/specter/sensors/system.py` | psutil: `cpu.load`, `ram.used` |
| `src/specter/sensors/linux_sysfs.py` | Linux `/sys` directly: `cpu.temp` (coretemp, k10temp, zenpower, ARM, x86_pkg_temp, acpitz), `fan.rpm` (fastest non-GPU fan), `fans` dict |
| `src/specter/sensors/gpu_types.py`, `gpu_hub.py` | `GpuDevice` contract; `GpuHubProvider` (name "gpu") is the only GPU provider: merges devices from all backends (PCI slot, else vendor + name), assigns `gpu.*` / `gpuN.*`, short labels ("RTX 3060") |
| `src/specter/sensors/nvidia.py` | GPU backend, optional `[nvidia]` extra (`pynvml`): load, mem, temp, fan %. `close()` = `nvmlShutdown` |
| `src/specter/sensors/linux_drm_gpu.py` | GPU backend: AMD (`amdgpu`: load, VRAM, temp, fan), Intel (`i915`/`xe`: approximate load from clocks as `freq`, shown "~NN%") |
| `src/specter/sensors/windows_pdh.py`, `windows_dxgi.py` | ctypes: Performance Counters reader (English names), DXGI adapter list (name, LUID, memory) |
| `src/specter/sensors/windows_gpu.py`, `windows_thermal.py` | Windows, no admin: GPU load/memory for any vendor from counters; `cpu.temp` from an ACPI thermal zone named like a CPU (approximate) |
| `src/specter/sensors/lhm_client.py`, `lhm.py` | LibreHardwareMonitor web server (`localhost:8085/data.json`, `SPECTER_LHM_URL`): best Windows source for `cpu.temp`, fans, GPU temp/fan. Shared client, 15 s backoff when not running |
| `src/specter/sensors/io_rates.py` | `disk.read/write`, `net.down/up` in MB/s from counter deltas. Skips loop/dm/partitions and lo/docker/veth/tun |
| `src/specter/ui/panel.py` | Frameless, top-most window. Drag to move, drag edges/corners (6 px) to resize, right-click popup. Mouse bindings live on the root window, so they cover every tile |
| `src/specter/ui/layout.py` | Pure layout maths: `choose_columns()` picks row / column / grid by window shape; `choose_layout()` shows fewer tiles (3 → 2 → 1) with ‹ › arrows when not all fit |
| `src/specter/ui/widgets.py` | `MetricTile` (big number + bar, optional `Sparkline`), `RateTile` (rows, no bar), `make_tile()` picks one; `SlimTile` (one line, for the slim strip); `SegmentBar`, colours (green <60 %, yellow ≥60, red ≥85) |
| `src/specter/ui/popup.py` | Custom right-click menu: OPACITY / TILES / UPDATE pills, Lock position, Always on top, Reset size, Quit. `MenuHooks` holds its callbacks. Global grab, closes on outside click, Esc or after 20 s idle |
| `src/specter/ui/screen.py` | `screen_bounds()` = all monitors together; `clamp()` keeps the panel (and menu) on the desktop |
| `src/specter/autostart.py` | "Start at login": XDG autostart entry on Linux (`supported()` is False elsewhere) |
| `src/specter/ui/clickthrough.py` | X11 click-through: empty input shape except a corner grip, via ctypes + libXfixes |
| `tools/build.py`, `tools/make_icon.py` | PyInstaller one-file build; draws `assets/icon.png`/`.ico` (no dependencies) |
| `src/specter/config.py` | JSON config (opacity, position, size, interval, `hidden_tiles` (default disk, fan), `locked`, `topmost`) in the platformdirs config dir. Saved on every menu change and on Quit |
| `src/specter/app.py` | Wires everything together. Shows the panel top-right on first start |

**Reading keys are `<device>.<metric>`.** Tiles group by the part before the dot, so
`cpu.load` + `cpu.temp` share the CPU tile. The primary reading (unit `%` or has `maximum`) gets
the big number and bar (`%` wins over `maximum`). Others go on the small line under it. A device
with no primary reading gets a `RateTile` (`Reading.short` = mark like `↓`). Tile order:
CPU, GPU, RAM, DISK, NET, FAN (`TILE_ORDER` in `panel.py`). Providers may implement `close()`.

## Current state (2026-11-19)

Working: CPU load + RAM tiles, drag, opacity (100/85/70/55/40), custom popup, config persistence.
2026-11-20: Phase 1 step 1 done: `sensors/linux_hwmon.py` (`cpu.temp` on the CPU tile's sub line,
`fan.rpm` = fastest spinning fan, own tile).
9 pytest tests.
2026-11-20: resizable panel. Auto-fit 2 columns until the user resizes; then the size is saved
(`width`/`height`) and the layout follows the window shape. When not all tiles fit: 2 tiles + arrows, then 1. Minimum size = 1 tile + arrows. 21 tests.
2026-11-20: **Phase 1 done** (NVIDIA, rate tiles, disk/net speed, 6-tile layout check). 36 tests.
2026-11-20: slim strip (taskbar height, ~30 px). Resizing shorter than one tile switches to one
row of `SlimTile`s (`CPU 8% 35°C  RAM 9.9GB …`), each as wide as it needs (`fit_row()` in
`layout.py`), with small ‹ › arrows when not all fit. Taller again = normal tiles. 41 tests.
2026-11-24: **Phase 2 Step 5 done**: popup settings (hide tiles, update interval, lock, always on top,
reset size), config saved right away, panel limited to the desktop (all monitors, can cross between
them). `Poller.set_interval()`. 51 tests. Not checked visually (screen was locked); logic checked on :1.
2026-11-24: **Step 6 done**: mouse wheel cycles tiles (when arrows show), `°C` values turn yellow at
70 / red at 85 (`TEMP_WARN`/`TEMP_HOT` in `widgets.py`; the MetricTile sub line is now one label per
value), `Config.first_tile` remembers where cycling stopped. 54 tests.
2026-11-24: **Step 7 done**: optional sparklines (`Sparkline` in `widgets.py`, 60 samples, only `MetricTile`,
toggle in the menu, `Config.sparklines`, off by default). **Step 9 code written but never run on Windows**
(cursor names, `-toolwindow`, popup closes on focus loss, `screen_bounds()` via `GetSystemMetrics`). 58 tests.
2026-11-24: Linux part of **Steps 8, 11, 12**: click-through (X11, session only), PyInstaller build +
icon, autostart toggle, README with screenshots in `docs/images/`. 65 tests.
Screenshots: use `import -window root -crop ...` (`xwd` failed with BadColor); open the menu with a
local grab (`Toplevel.grab_set_global = Toplevel.grab_set`) or `import` may hang; put the panel on a
plain backdrop window so no private windows are captured. A locked screen shows only the lock greeter.
2026-11-24: shrinking goes in three steps when sparklines are on: tiles with graphs, then tiles with the
graphs hidden (`height_step()` in `layout.py`, `_compact` in `panel.py`; the setting stays on), then the
slim strip. The tallest tile height without/with graph is tracked as `_plain_h`/`_full_h`. 67 tests.
2026-11-24: **First Windows run** (Windows 11 laptop, Intel Iris Xe, no NVIDIA, python.org Python 3.14,
Tk 9.0): panel works; GPU, CPU temp and fan were missing. **Phase 5 (Steps 18-24) implemented**: provider
priority + first-wins, `--sensors`/`--dump`, Linux sysfs rewrite (`linux_hwmon.py` removed), AMD/Intel GPUs,
Windows counters/DXGI GPU + ACPI temp, GPU hub, LibreHardwareMonitor client, tile polish, `docs/sensors.md`.
216 tests. Live on Windows: `gpu.load`/`gpu.mem` and `cpu.temp` (~55 °C) work. Linux code is tested only
with fake `/sys` trees: re-test on the Ubuntu box.
Windows dev setup: `py -m venv .venv`, `.venv\Scripts\pip install -e ".[dev,nvidia]"`, `.venv\Scripts\pytest`,
`.venv\Scripts\python -m specter [--sensors]`. Run from the repo folder, not an admin shell.

# Plan

The step-by-step plan is in **`PLAN.md`** (read it at the start of a session). Do the next
unfinished step, then mark it done in `PLAN.md` and update "Current state" above.

**Next:** Phase 5 code is done. Left: re-test Linux on the Ubuntu box after the sensor rewrite, finish the
Step 9 Windows checklist, Windows build/autostart/click-through (Steps 11, 12, 8), the user tags `v0.2.0`,
and the "Later" list (alerts, themes, specs view).

Machine facts for the plan: NVIDIA T600 4 GB, driver 495 (NVML works). Network interfaces
`enp2s0`, `enp3s0`, `lo`. Disks `nvme0n1`, `sdh`, plus ~26 snap `loop*` devices that disk rates
must ignore.

Open decisions (defaults are in `PLAN.md`; ask the user before the step that needs them): default
tiles, full specs view in v1 or later, tray icon yes/no.

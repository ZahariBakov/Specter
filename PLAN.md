# Specter — implementation plan

Written 2026-11-20. Each step is small enough for one session, ends with passing tests and a
screenshot check, and is committed by the user before the next one starts.

**Done so far:** CPU load + RAM, CPU temperature + fan (`linux_hwmon.py`), drag, opacity, popup
menu, config, resizable panel (row / column / grid, then 2 → 1 tiles with ‹ › arrows),
Phase 1 (NVIDIA GPU, rate tiles, disk and network speed), slim strip at taskbar height,
Step 5 (popup settings, screen-edge limit), Step 6 (wheel, temperature colours).

Defaults used below for the open decisions (change them before the step that needs them):

| Decision | Default in this plan | Needed by |
|---|---|---|
| Tiles shown by default | CPU, GPU, RAM, NET (DISK and FAN available, off by default) | Step 5 |
| Full specs view | Later (Step 13, after the first release) | Step 13 |
| Tray icon | No for v1. The right-click menu is enough | — |

---

## Phase 1 — more sensors (Linux) ✅ done 2026-11-20

### Step 1. NVIDIA GPU ✅
**Files:** new `sensors/nvidia.py`, `sensors/registry.py`, `pyproject.toml`, new `tests/test_nvidia.py`

- Optional dependency: `[project.optional-dependencies] nvidia = ["nvidia-ml-py"]`. Pin a version
  that still installs on Python 3.8 (check with `uv pip install` on the system Python).
- `NvidiaProvider.__init__`: `import pynvml` inside a `try`, then `nvmlInit()` and get the device
  handles. On `ImportError` or `NVMLError` → remember it and `is_available()` returns `False`.
- `read()` per GPU: `nvmlDeviceGetUtilizationRates().gpu` → `gpu.load` (%),
  `nvmlDeviceGetTemperature(h, NVML_TEMPERATURE_GPU)` → `gpu.temp` (°C),
  `nvmlDeviceGetMemoryInfo()` → `gpu.mem` (GB, `maximum` = total). Label "GPU".
- More than one GPU: keys `gpu0.*`, `gpu1.*` and labels "GPU 0", "GPU 1". One GPU keeps `gpu.*`.
- `nvmlShutdown()` at exit: add an optional `close()` to `SensorProvider` (default does nothing)
  and call it from `Poller.stop()`.
- The GPU tile would have two primary readings (load and mem). The tile shows load as the big
  number. Change `is_primary` so `%` wins over `maximum`, and put mem on the sub line
  (`0.6/3.8GB  56°C`).
- **Tests:** fake `pynvml` module in `sys.modules` (monkeypatch) for 1 GPU, 2 GPUs, `ImportError`,
  and `nvmlInit` raising.
- **Check:** real T600 values against `nvidia-smi`.

### Step 2. "Rate" tile style (two values, no bar) ✅
**Files:** `ui/widgets.py`, `core/models.py`, tests

- A tile whose readings have no `%` and no `maximum` (fan, disk, net) gets a different look: two
  rows of medium-size values (`↓ 12.4 MB/s` / `↑ 0.8 MB/s`) and no segment bar. FAN uses it too,
  which removes today's empty bar.
- Keep the tile size close to the normal tile, so the layout maths (one cell size) still works.
- Optional `Reading.icon` / prefix (`↓`, `↑`, `R`, `W`) so the widget doesn't guess from keys.
- Unit formatting: show KB/s under 1 MB/s, MB/s above. Function `format_rate()`, unit tested.

### Step 3. Disk and network speed ✅
**Files:** `sensors/system.py` (or new `sensors/io_rates.py`), tests

- Keep the previous counters plus `time.monotonic()`. Rate = (now − before) / elapsed.
  The first `read()` only stores counters and returns nothing.
- Network: `psutil.net_io_counters(pernic=True)`, skip `lo` and interfaces that are down
  (`psutil.net_if_stats()`). Sum the rest → `net.down`, `net.up` (MB/s).
- Disk: `psutil.disk_io_counters(perdisk=True)`, **skip `loop*`, `ram*`, `zram*`, `dm-*` and
  partitions** (this machine has 26 snap loop devices). Sum whole disks → `disk.read`,
  `disk.write`.
- Counters can reset (sleep, device removed): a negative difference counts as 0.
- **Tests:** fake counters over two reads with a fake clock; reset case; loop devices ignored.

### Step 4. Panel check with 6 tiles ✅
- CPU, GPU, RAM, FAN, DISK, NET: check every layout (row, column, grid, 2 → 1 with arrows),
  first placement top-right, and that the cell size does not jump while values change.
- Fix whatever looks wrong. Likely candidates: a too-wide cell because of long rate strings, and
  the arrows' cycling order.

---

## Phase 2 — panel usability

### Step 5. Settings in the popup menu ✅ (2026-11-24)
**Files:** `ui/popup.py`, `config.py`, `ui/panel.py`, `app.py`

- New `Config` fields: `hidden_tiles: list[str]`, `locked: bool`, `topmost: bool`,
  `interval_ms` (exists). Keep loading old config files (missing keys = defaults).
- Popup sections, under OPACITY:
  - **TILES:** a check row per known tile group (CPU, GPU, RAM, …). Hiding one re-runs the layout.
  - **UPDATE:** pills `0.5s / 1s / 2s` → `Poller.set_interval()` (new, thread-safe: just a float).
  - Toggles: **Lock position**, **Always on top**.
  - **Reset size** (back to auto-fit), then **Quit**.
- Locked: no move, no resize, edge cursors off. The menu still works.
- Save the config right away when a setting changes, not only on Quit (a crash loses nothing).
- **Added:** the panel can't leave the desktop (all monitors together, `ui/screen.py`), so it stops
  at the outer edges but still moves across 2–3 screens. Resizing and the menu are kept inside too.
  Windows uses `GetSystemMetrics` for the virtual screen (untested, Step 9).
- **Tests:** config round-trip with the new fields; old config file without them still loads.

### Step 6. Small panel improvements ✅ (2026-11-24)
- Mouse wheel cycles tiles when the arrows are visible (`<Button-4/5>` on X11, `<MouseWheel>` on
  Windows).
- Temperature colours: `°C` values turn yellow at ≥ 70 and red at ≥ 85 (the big number or the
  sub line). Thresholds as constants in `widgets.py`.
- Remember the first shown tile when cycling (`Config.first_tile`).

### Step 7. Sparkline (optional)
- Each tile keeps the last 60 primary values (`collections.deque(maxlen=60)`) and draws a thin
  line on a small Canvas under the bar. Off by default, toggle in the popup.

### Step 8. Click-through mode (optional, needs research)
- X11: empty input shape with Xfixes via `ctypes` (`XFixesSetWindowShapeRegion`). Windows:
  `WS_EX_LAYERED | WS_EX_TRANSPARENT` via `ctypes.windll.user32`.
- Problem: in click-through mode the panel can't receive the right-click. Exit it with a global
  hotkey, or by leaving a small grip that still takes clicks. Prototype first, then decide.

---

## Phase 3 — Windows

### Step 9. Panel on Windows
- Skip `-type utility`. Use `-toolwindow` to hide the panel from the taskbar.
- Check `-alpha`, `-topmost`, the popup's global grab, and the resize cursors (Windows has
  `size_nw_se` etc. if the X names look wrong).
- `linux_hwmon` turns itself off. CPU load, RAM, disk, net and NVIDIA work through
  psutil / NVML.
- Set up the dev environment on Windows (python.org Python 3.8+ has a good Tk).

### Step 10. CPU and motherboard temperatures on Windows
- New optional `sensors/windows_lhm.py`: `pythonnet` + `LibreHardwareMonitorLib.dll`, needs admin.
  Without admin or without the DLL → `is_available()` returns `False` and a log line explains why.
- Decide how the DLL is shipped (bundled in the build, or the user downloads it).

---

## Phase 4 — release

### Step 11. Builds
- PyInstaller one-file builds, with a `build.py` or a short section in the README.
- Linux: build on this machine (glibc 2.31 → runs on newer distros). Test on a newer distro
  (live USB or VM).
- Windows: build on Windows. Optional: a GitHub Actions workflow for both.
- An app icon (`.png` for Linux, `.ico` for Windows).

### Step 12. Start with the system
- Popup toggle **Start at login**.
- Linux: write or remove `~/.config/autostart/specter.desktop`.
- Windows: a shortcut in the Startup folder, or the `HKCU\...\Run` registry key.
- README: install, run, screenshots, known limits (opacity needs a compositor).
- Tag `v0.2.0` (the user creates the tag).

---

## Later
13. **Full specs view** (like Speccy): a separate window from the menu with CPU model, RAM, disks,
    GPU and OS (`platform`, psutil, `/proc/cpuinfo`, `lsblk`, NVML; WMI on Windows).
14. **Alerts:** a desktop notification when a temperature goes over a limit you choose.
15. **AMD GPU on Linux:** `/sys/class/drm/card*/device/gpu_busy_percent` + hwmon.
16. **Themes:** light / dark, accent colour.
17. **Tray icon** (`pystray` + Pillow), only if the decision changes.

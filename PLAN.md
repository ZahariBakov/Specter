# Specter — implementation plan

Written 2026-11-20. Each step is small enough for one session, ends with passing tests and a
screenshot check, and is committed by the user before the next one starts.

**Done so far:** CPU load + RAM, CPU temperature + fan (`linux_hwmon.py`), drag, opacity, popup
menu, config, resizable panel (row / column / grid, then 2 → 1 tiles with ‹ › arrows),
Phase 1 (NVIDIA GPU, rate tiles, disk and network speed), slim strip at taskbar height,
Step 5 (popup settings, screen-edge limit), Step 6 (wheel, temperature colours), Step 7 (sparklines), Step 9 code (still to test on Windows).

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

### Step 7. Sparkline (optional) ✅ (2026-11-24)
- Each tile keeps the last 60 primary values (`collections.deque(maxlen=60)`) and draws a thin
  line on a small Canvas under the bar. Off by default, toggle in the popup.

### Step 8. Click-through mode (optional) ✅ X11 done 2026-11-24, Windows later
Done: `ui/clickthrough.py` (X Fixes input shape through ctypes). Only a 14 px grip in the top-left
corner takes clicks (a blue dot marks it); a click on it opens the menu to switch off. Session only,
not saved. Windows: `WS_EX_TRANSPARENT` still to do (same grip idea needs `SetWindowRgn` or a
second small window). Original notes:
- X11: empty input shape with Xfixes via `ctypes` (`XFixesSetWindowShapeRegion`). Windows:
  `WS_EX_LAYERED | WS_EX_TRANSPARENT` via `ctypes.windll.user32`.
- Problem: in click-through mode the panel can't receive the right-click. Exit it with a global
  hotkey, or by leaving a small grip that still takes clicks. Prototype first, then decide.

---

## Phase 3 — Windows

### Step 9. Panel on Windows (code done 2026-11-24, **not yet run on Windows**)
Done in code: `-toolwindow` on Windows, Windows resize/move cursors (`resize_cursor()`,
`move_cursor()` in `panel.py`), popup closes on focus loss (no global grab on Windows),
virtual-screen bounds via `GetSystemMetrics` (`ui/screen.py`).

**Test checklist on a Windows PC** (then fix whatever fails):
1. Set up: python.org Python 3.8+, `py -m venv .venv`, `.venv\Scripts\pip install -e ".[dev,nvidia]"`,
   `.venv\Scripts\pytest`, `.venv\Scripts\specter`.
2. No taskbar button; panel stays on top; opacity pills work (`-alpha`).
3. Drag, resize (right cursors at edges and corners), slim strip, arrows and wheel.
4. Right-click menu: opens, closes on outside click / Esc / switching to another app.
5. Two monitors: drag across, stops at the outer edges (also with a monitor left of the primary).
6. Tiles: CPU, RAM, DISK, NET work. GPU only with an NVIDIA card. No CPU temperature or fan yet (Step 10).
7. Blurry text on a high-DPI screen? Then set DPI awareness (`SetProcessDpiAwareness`) and re-check 5.
- Skip `-type utility`. Use `-toolwindow` to hide the panel from the taskbar.
- Check `-alpha`, `-topmost`, the popup's global grab, and the resize cursors (Windows has
  `size_nw_se` etc. if the X names look wrong).
- `linux_hwmon` turns itself off. CPU load, RAM, disk, net and NVIDIA work through
  psutil / NVML.
- Set up the dev environment on Windows (python.org Python 3.8+ has a good Tk).

### Step 10. CPU and motherboard temperatures on Windows → replaced by Phase 5 (Steps 20, 22)
- New optional `sensors/windows_lhm.py`: `pythonnet` + `LibreHardwareMonitorLib.dll`, needs admin.
  Without admin or without the DLL → `is_available()` returns `False` and a log line explains why.
- Decide how the DLL is shipped (bundled in the build, or the user downloads it).

---

## Phase 4 — release

### Step 11. Builds (Linux done 2026-11-24, Windows later)
Done: `tools/build.py` (PyInstaller one-file, `pip install -e ".[build]"`), icon `src/specter/assets/icon.png`
+ `icon.ico` from `tools/make_icon.py`, the app sets it as window icon. Linux build ran fine here
(10 MB). Still to do: test it on a newer distro, Windows build, optional GitHub Actions.
Original notes:
- PyInstaller one-file builds, with a `build.py` or a short section in the README.
- Linux: build on this machine (glibc 2.31 → runs on newer distros). Test on a newer distro
  (live USB or VM).
- Windows: build on Windows. Optional: a GitHub Actions workflow for both.
- An app icon (`.png` for Linux, `.ico` for Windows).

### Step 12. Start with the system (Linux + README done 2026-11-24, Windows later)
Done: `autostart.py` (XDG `~/.config/autostart/specter.desktop`), menu toggle **Start at login**, README
with screenshots (`docs/images/`). Still to do: Windows autostart; the `v0.2.0` tag (user).
Original notes:
- Popup toggle **Start at login**.
- Linux: write or remove `~/.config/autostart/specter.desktop`.
- Windows: a shortcut in the Startup folder, or the `HKCU\...\Run` registry key.
- README: install, run, screenshots, known limits (opacity needs a compositor).
- Tag `v0.2.0` (the user creates the tag).

---

## Phase 5 — sensor coverage (added 2026-11-24) ✅ code done 2026-11-24

All steps 18-24 are implemented and unit tested (216 tests). Checked live on Windows 11 + Intel Iris Xe:
GPU load/memory (counters), CPU temperature (ACPI zone), LibreHardwareMonitor client not reachable
(not installed). **Still to check on real hardware:** the Linux rewrite (`linux_sysfs.py`,
`linux_drm_gpu.py`) on the Ubuntu/T600 box, LibreHardwareMonitor running, and an iGPU + dGPU PC.

Goal: Specter shows CPU, GPU, temperature and fan values on **any** Linux or Windows PC that exposes
them, whatever the vendor. Found on the first Windows run (Intel Iris Xe laptop, no admin):
only `cpu.load`, `ram.used`, disk and net worked. The GPU tile was missing (NVML only), and CPU
temperature and fan were missing (hwmon is Linux only). Step 10 is replaced by Steps 18-24 below.

Design rules for the whole phase:
- **One source per reading, best first.** Several providers can offer the same key (NVML and the
  Windows counters both know `gpu.load`). The registry orders them by quality and the first one
  that returns a key wins. Today the last one wins.
- **"No sensor" is a normal answer.** A tile only appears when some source delivers it. A machine
  with no fan sensor simply has no FAN tile. Nothing ever crashes (existing rule).
- **No admin rights by default.** Admin-only sources (LibreHardwareMonitor) are an optional upgrade
  and Specter says so in the diagnostics instead of failing silently.
- **Everything testable without the hardware:** sysfs roots, counters and JSON are injected, tests
  use fake trees (like `test_io_rates.py`).

### Step 18. Foundation: priority, diagnostics, injectable sources ✅
**Files:** `sensors/base.py`, `sensors/registry.py`, `core/poller.py`, `app.py`, tests

- `SensorProvider.unavailable_reason: str` (set when `is_available()` is False) and `priority: int`.
- `Poller.poll_once`: first provider to give a key wins (`setdefault`), providers run in priority order.
- `python -m specter --sensors`: prints every provider (running / why not), and for every key which
  provider supplies it. Also `--dump`: raw platform data (psutil temperatures and fans, the hwmon
  tree, DXGI adapters, PDH counter names) so a user with odd hardware can paste it into an issue.
- Log a warning when one provider takes longer than the interval (slow sensors must not stall the rest).
- **Tests:** two fake providers with the same key; priority order; reason strings.

### Step 19. Linux: direct hwmon / sysfs provider (replaces `linux_hwmon.py`) ✅ (fake /sys only)
Done as `linux_sysfs.py` (CPU temp, fans) + `linux_drm_gpu.py` (AMD, Intel). NVIDIA fan % comes from
NVML. Intel load is `<gpu>.freq`, shown as "~NN%".
**Files:** `sensors/linux_sysfs.py`, tests with a fake `/sys` tree

- Read `/sys/class/hwmon/*` directly (psutil stays a fallback). Chips and labels to cover:
  Intel `coretemp` (Package id 0, else hottest Core N), AMD `k10temp` (Tctl, Tdie, Tccd*),
  `zenpower`, Raspberry Pi and ARM (`cpu_thermal`, `/sys/class/thermal/thermal_zone*`),
  `x86_pkg_temp`, last resort `acpitz`.
- Fans: every `fan*_input` (ThinkPad `thinkpad_acpi`, `dell_smm`, `nct*`/`it87`, `asus`, `applesmc`).
  Keep "fastest spinning fan" for the tile; list all fans in `--sensors`.
- AMD GPU (`amdgpu`): `gpu_busy_percent`, `mem_info_vram_used/total`, hwmon `temp1_input`,
  `fan1_input`, `pwm1`. Absorbs old item 15.
- Intel GPU: `i915` / `xe` hwmon (temperature and fan on Arc); iGPU load is not exposed without
  root, so use `gt_cur_freq_mhz / gt_max_freq_mhz` as an approximate load and mark it in the label.
- NVIDIA: stays in `nvidia.py`; add `gpu.fan` (`nvmlDeviceGetFanSpeed`, %) when it exists.
- **Check:** this Linux box (coretemp, nct6106 fan, T600). Volunteers or VMs for AMD and Arc.

### Step 20. Windows: Performance Counters provider (no admin, any GPU) ✅
Done as `windows_pdh.py`, `windows_dxgi.py`, `windows_gpu.py`, `windows_thermal.py`.
**Files:** `sensors/windows_pdh.py` (ctypes over `pdh.dll`, no dependency), `sensors/windows_gpu.py`

- GPU load: `\GPU Engine(*)\Utilization Percentage`, summed per engine type per adapter (LUID),
  take the busiest engine type (3D, compute, video) like Task Manager does.
- GPU memory: `\GPU Adapter Memory(*)\Dedicated Usage` and `Shared Usage`; total from DXGI
  (`DedicatedVideoMemory`). Integrated GPUs show shared memory.
- Adapter names and LUIDs from DXGI (`EnumAdapters1` through ctypes) so tiles can be named
  "Intel Iris Xe" and an iGPU plus a dGPU never mix. Skip "Microsoft Basic Render Driver".
- CPU temperature, no-admin tier: `\Thermal Zone Information(*)\Temperature` (Kelvin). It is an
  ACPI zone, not the exact CPU package, so label it honestly in `--sensors`. Absent on some PCs.
- Counter names are localized on non-English Windows: use `PdhAddEnglishCounterW`.
- **Tests:** fake PDH reader with real counter-name samples; LUID grouping; multi-adapter.
- **Check:** this PC (Intel Iris Xe), compare with Task Manager.

### Step 21. GPU naming and merging (all vendors together) ✅
Done as `gpu_types.py` (contract) + `gpu_hub.py` (the only GPU provider; backends run inside it).
Decision: iGPU and dGPU are both shown by default (the TILES menu can hide either).
**Files:** `sensors/registry.py`, `ui/panel.py`, `ui/widgets.py`, tests

- One GPU = one tile whatever the backend: NVML, amdgpu, i915, PDH. Merge by PCI id (Linux) or
  LUID / name (Windows). Keys `gpu.*` for one GPU, `gpu0.*`, `gpu1.*` for several (as now).
- Tile title from the real name when there are several ("GPU 0 Intel", "GPU 1 RTX 3060").
- Menu: an option to hide integrated GPUs by default when a discrete one exists.

### Step 22. Windows: temperatures and fans through LibreHardwareMonitor ✅ (web server client)
Done as `lhm_client.py` + `lhm.py`. Decision: web server client only; the pythonnet route is not planned.
**Files:** `sensors/windows_lhm.py`, `README.md`, tests with a fake JSON

LibreHardwareMonitor reads the CPU package temperature, per-core temperatures, motherboard
fans, and AMD and Intel GPU temperatures on Windows. Two ways to use it, in this order:
1. **Web server client (no dependencies, recommended first):** the user runs LibreHardwareMonitor
   (or OpenHardwareMonitor) with its remote web server on, and Specter reads
   `http://localhost:8085/data.json` with `urllib`. Admin rights stay in that other program, and
   Specter itself runs unelevated. Detect it, and say in `--sensors` how to switch it on.
2. **In-process (optional extra `[windows-sensors]`):** `pythonnet` + `LibreHardwareMonitorLib.dll`,
   needs admin. Only if step 1 proves too clumsy. Decide later how the DLL is shipped.
- Map LHM sensor types to our keys: `cpu.temp` (CPU Package, else Tctl/Tdie, else the hottest core),
  `fan.rpm` (fastest), `gpu*.temp`, `gpu*.fan`.
- Priority above the counters tier for temperatures. Without LHM running, tier 20 still applies.

### Step 23. Fan tile and temperature polish ✅
Done: `--sensors` lists GPU backends, GPU names, all fans and notes; tiles show "~" for the approximate
load, a fixed sub-line order (memory, °C, fan) and "fan 42%". GPU fans stay on the GPU tile, not FAN.
- `fan.rpm`: also take GPU fans; show "GPU fan 42 %" on the GPU tile when only a percentage exists.
- Several fans: optional second line (CPU / chassis / GPU) once the readings carry a `source` hint.
- Temperature fallbacks documented in the README ("which sensors do I get on my PC").

### Step 24. Hardware matrix and release notes ✅ (`docs/sensors.md`, README)
- Matrix in `docs/sensors.md`: OS × CPU (Intel, AMD, ARM) × GPU (NVIDIA, AMD, Intel) × what is
  read, and which tier supplies it. Fill it from `--sensors` output people send in.
- Tested so far: Linux + Intel + NVIDIA T600 (done), Windows + Intel Iris Xe (Step 20).
  Needed: AMD CPU/GPU on both systems, Intel Arc, a laptop with a ThinkPad or Dell fan.
- README "Known limits" updated; this is what the `v0.2.0` / `v0.3.0` notes should say.

**Order:** 18 → 20 (the Windows GPU, fixes this PC first) → 19 → 21 → 22 → 23 → 24.
Step 18 comes first because 19-22 all depend on "first provider wins" and the diagnostics.

---

## Later
13. **Full specs view** (like Speccy): a separate window from the menu with CPU model, RAM, disks,
    GPU and OS (`platform`, psutil, `/proc/cpuinfo`, `lsblk`, NVML; WMI on Windows).
14. **Alerts:** a desktop notification when a temperature goes over a limit you choose.
15. ~~AMD GPU on Linux~~ → now Step 19 (Phase 5).
16. **Themes:** light / dark, accent colour.
17. **Tray icon** (`pystray` + Pillow), only if the decision changes.

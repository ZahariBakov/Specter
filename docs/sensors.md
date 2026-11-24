# Which sensors do I get?

Specter asks several sources for each value and uses the best one that works on your machine.
A missing source never stops the app: the value (or its tile) is simply not shown.
Run `specter --sensors` to see what was found on your PC (see [Reporting a missing
sensor](#reporting-a-missing-sensor)).

The tables list the sources in priority order: the first one that gives a value wins.

## Linux

| Value | Sources (best first) |
|---|---|
| CPU load | psutil |
| RAM | psutil |
| CPU temperature | hwmon `coretemp` (Intel package / hottest core) -> `k10temp` / `zenpower` (AMD Tctl / Tdie) -> ARM `cpu_thermal` (Raspberry Pi) -> thermal zone `x86_pkg_temp` -> ACPI `acpitz` -> none |
| Fans (FAN tile) | fastest spinning fan of any hwmon chip that is not a GPU -> none (many laptops expose no fans) |
| GPU load | NVIDIA: NVML. AMD: `gpu_busy_percent`. Intel: **approximate** "~" value from the GPU clock (see below) |
| GPU memory | NVIDIA: NVML. AMD: VRAM from `/sys/class/drm`. Intel: none (integrated GPUs share RAM) |
| GPU temperature | NVIDIA: NVML. AMD and Intel Arc: the GPU's hwmon chip. Integrated Intel: none |
| GPU fan | AMD and Intel Arc: hwmon RPM. NVIDIA: NVML gives only a fan percentage, listed by `--sensors` but not shown on the tile |
| Disk | psutil counters (loop, device-mapper and partitions are skipped) |
| Network | psutil counters (lo, docker, veth and tun are skipped) |

### Per GPU vendor on Linux

| Vendor | Source | Load | Memory | Temperature | Fan |
|---|---|---|---|---|---|
| NVIDIA | NVML (`[nvidia]` extra + NVIDIA driver) | yes | yes | yes | % (diagnostics only) |
| AMD | `/sys/class/drm` (`amdgpu`, `radeon`) | yes | yes | yes | RPM, if the card reports it |
| Intel integrated | `/sys/class/drm` (`i915`, `xe`) | approximate "~" | no | no | no |
| Intel Arc | `/sys/class/drm` (`i915`, `xe`) | approximate "~" | no | if hwmon has it | if hwmon has it |

No root and no extra libraries are needed for AMD and Intel. The open `nouveau` driver is not
read; NVIDIA cards need the NVIDIA driver and `pip install "specter[nvidia]"`.

### Why Intel GPU load shows "~" on Linux

The Intel kernel drivers have no GPU load counter that a normal user can read (tools like
`intel_gpu_top` need root). Specter shows the current GPU clock as a percentage of its maximum
clock instead, marked with "~". It rises and falls with GPU work, but it is not real load: an
idle GPU can sit at a high clock for a moment, and a busy GPU may run below its top clock.

## Windows

| Value | Sources (best first) |
|---|---|
| CPU load | psutil |
| RAM | psutil |
| CPU temperature | LibreHardwareMonitor web server -> ACPI thermal zone counter (approximate, only zones named like a CPU, not on every PC) -> none |
| Fans (FAN tile) | LibreHardwareMonitor (fastest mainboard / CPU fan) -> none |
| GPU load | NVML (NVIDIA) -> Windows GPU performance counters (any vendor) -> LibreHardwareMonitor |
| GPU memory | NVML (NVIDIA) -> Windows GPU performance counters (any vendor) -> LibreHardwareMonitor |
| GPU temperature | NVML (NVIDIA) -> LibreHardwareMonitor -> none |
| GPU fan | LibreHardwareMonitor (RPM) -> none. NVML's fan percentage is listed by `--sensors` only |
| Disk | psutil counters |
| Network | psutil counters |

### Per GPU vendor on Windows

| Vendor | Without LibreHardwareMonitor | With LibreHardwareMonitor |
|---|---|---|
| NVIDIA | load, memory, temperature (NVML, needs the `[nvidia]` extra); load and memory from counters without it | adds fan RPM |
| AMD | load, memory (performance counters) | adds temperature, fan |
| Intel (integrated or Arc) | load, memory (performance counters) | adds temperature (and fan on Arc) where LibreHardwareMonitor sees them |

When several sources see the same GPU, Specter merges them into one tile: the best source gives
each value, the others only fill in what is missing.

## Set up LibreHardwareMonitor

On Windows, CPU and GPU temperatures and fan speeds need a driver that only runs with
administrator rights. Specter itself does not need (and should not get) admin rights; instead
it reads [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor)'s
built-in web server.

1. Download LibreHardwareMonitor and start it **as administrator**.
2. Enable **Options -> Remote Web Server**. Keep the default port **8085**.
3. Optional: enable "Start Minimized", "Minimize To Tray" and "Run On Windows Startup" in its
   Options menu so it is always there.
4. Start Specter normally (not elevated).

Order does not matter: if LibreHardwareMonitor is started after Specter, the values appear as
soon as it answers. If it runs on another address or port, set the `SPECTER_LHM_URL`
environment variable to the full `data.json` address, for example
`SPECTER_LHM_URL=http://192.168.1.20:8085/data.json` (this also lets Specter on Linux read a
LibreHardwareMonitor on another PC). The older
OpenHardwareMonitor works the same way.

Without LibreHardwareMonitor, `specter --sensors` shows a note like `lhm not reachable at
http://localhost:8085/data.json`. That is fine: Specter then falls back to the sources above.

## Tested hardware

| OS | CPU | GPU | Status |
|---|---|---|---|
| Linux (Ubuntu 20.04, KDE/X11) | Intel Core i-series | NVIDIA T600 | Tested before the sensor rewrite (CPU load and temperature, RAM, fan, disk, net, GPU load/memory/temperature). **Needs a re-test.** |
| Windows 11 (laptop) | Intel Core | Intel Iris Xe | Tested: CPU load, RAM, disk, net, GPU load and memory, CPU temperature via the thermal zone. LibreHardwareMonitor not tried yet. |
| Linux / Windows | AMD Ryzen | - | Not tested yet |
| Linux / Windows | - | AMD Radeon | Not tested yet |
| Linux / Windows | - | Intel Arc | Not tested yet |
| Windows | - | NVIDIA | Not tested yet |
| Linux | ThinkPad / Dell laptop fans | - | Not tested yet |
| Raspberry Pi OS | ARM (Raspberry Pi) | - | Not tested yet |

If your hardware is missing here, a report (working or not) is very welcome.

## Reporting a missing sensor

Run both commands and paste their output into a
[GitHub issue](https://github.com/ZahariBakov/Specter/issues):

```bash
specter --sensors     # which sources run, which values they give, and why others are off
specter --dump        # raw data: hwmon, /sys/class/drm, psutil, Windows video adapters
```

If `specter` is not on your PATH, use `python -m specter --sensors` (on Windows from the venv:
`.venv\Scripts\python -m specter --sensors`). Mention your CPU, GPU and what you expected to see.
The output contains no personal data apart from your hardware and OS version.

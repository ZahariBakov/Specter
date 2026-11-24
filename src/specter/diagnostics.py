"""Plain-text diagnostics for bug reports: `specter --sensors` and `specter --dump`."""

from __future__ import annotations

import glob
import os
import platform
import subprocess
import sys
import time
from typing import Callable, Dict, List, Tuple


def _tk_version() -> str:
    try:
        import tkinter

        return str(tkinter.TkVersion)
    except Exception as exc:
        return "unavailable (%s)" % exc


def _fmt_value(value: object) -> str:
    return "%.1f" % value if isinstance(value, float) else str(value)


def _backend_lines(pname: str, provider: object) -> List[str]:
    """Indented backend lines for a hub provider (one with `backend_report`)."""
    out: List[str] = []
    try:
        report = list(getattr(provider, "backend_report", None) or [])
        active = {}  # type: Dict[str, object]
        for b in getattr(provider, "backends", None) or []:
            active[getattr(b, "name", b.__class__.__name__)] = b
        for bname, ok, reason in report:
            label = "%s/%s" % (pname, bname)
            if ok:
                prio = getattr(active.get(bname), "priority", None)
                prio_txt = " priority %s" % prio if prio is not None else ""
                out.append("    %-16s running%s" % (label, prio_txt))
            else:
                out.append("    %-16s off (%s)" % (label, reason or "not available"))
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
        out.append("    (backend report failed: %s)" % exc)
    return out


def _details_lines(providers: list) -> List[str]:
    """Optional "GPUs:" and "Fans:" sections from providers that expose `names`/`extra`/`fans`."""
    gpus: List[str] = []
    fans: List[str] = []
    for p in providers:
        try:
            names = getattr(p, "names", None) or {}
            extra = getattr(p, "extra", None) or {}
            if isinstance(names, dict) and isinstance(extra, dict):
                for prefix in sorted(set(names) | set(extra)):
                    gpus.append("  %-14s %s" % (prefix, names.get(prefix) or "(unknown name)"))
                    for metric, r in sorted((extra.get(prefix) or {}).items()):
                        gpus.append("    %-12s %10s %-5s (not on tile)"
                                    % (metric, _fmt_value(getattr(r, "value", r)),
                                       getattr(r, "unit", "") or ""))
            pfans = getattr(p, "fans", None) or {}
            if isinstance(pfans, dict):
                pname = getattr(p, "name", p.__class__.__name__)
                for fname, rpm in sorted(pfans.items()):
                    fans.append("  %-28s %8s RPM  from %s" % (fname, _fmt_value(rpm), pname))
        except Exception as exc:  # noqa: BLE001
            gpus.append("  (details failed: %s)" % exc)
    out: List[str] = []
    if gpus:
        out.extend(["", "GPUs:"] + gpus)
    if fans:
        out.extend(["", "Fans:"] + fans)
    return out


def sensors_report(delay: float = 1.2) -> str:
    """Providers (running/off), then every reading key of one poll and who supplied it."""
    from specter.sensors.registry import create_providers, provider_report

    lines: List[str] = []
    lines.append("Platform: %s" % platform.platform())
    lines.append("Python:   %s" % sys.version.split()[0])
    lines.append("Tk:       %s" % _tk_version())
    lines.append("")

    providers = []
    try:
        providers = list(create_providers())
    except Exception as exc:
        lines.append("create_providers failed: %s" % exc)

    running = {}  # type: Dict[str, object]
    for p in providers:
        running[getattr(p, "name", p.__class__.__name__)] = p

    lines.append("Providers:")
    try:
        report = provider_report()
    except Exception as exc:
        report = []
        lines.append("  provider_report failed: %s" % exc)
    seen = set()
    for name, available, reason in report:
        seen.add(name)
        prio = getattr(running.get(name), "priority", None)
        prio_txt = "  priority %s" % prio if prio is not None else ""
        if name in running:
            lines.append("  %-16s running%s" % (name, prio_txt))
            lines.extend(_backend_lines(name, running[name]))
        else:
            lines.append("  %-16s off (%s)" % (name, reason or "not available"))
    for name, p in running.items():
        if name not in seen:
            lines.append("  %-16s running  priority %s" % (name, getattr(p, "priority", "?")))
            lines.extend(_backend_lines(name, p))
    lines.append("")

    # Two reads so rate providers (disk/net) have a previous sample.
    results = []  # type: List[Tuple[str, list]]
    for i in range(2):
        results = []
        for p in providers:
            pname = getattr(p, "name", p.__class__.__name__)
            try:
                results.append((pname, list(p.read())))
            except Exception as exc:
                results.append((pname, []))
                lines.append("  (%s.read() raised %s: %s)" % (pname, exc.__class__.__name__, exc))
        if i == 0 and delay > 0:
            time.sleep(delay)

    lines.append("Readings (first provider in priority order wins):")
    supplied = {}  # type: Dict[str, Tuple[str, object]]
    order = []  # type: List[str]
    for pname, readings in results:
        for r in readings:
            if r.key not in supplied:
                supplied[r.key] = (pname, r)
                order.append(r.key)
    if not order:
        lines.append("  (none)")
    for key in order:
        pname, r = supplied[key]
        value = r.value
        txt = "%.1f" % value if isinstance(value, float) else str(value)
        lines.append("  %-14s %10s %-5s from %s" % (key, txt, r.unit or "", pname))

    lines.extend(_details_lines(providers))

    notes = []  # providers that explain their state, e.g. LibreHardwareMonitor not running
    for p in providers:
        try:
            status = getattr(p, "status", "")
        except Exception:  # noqa: BLE001
            status = ""
        if status:
            notes.append("  %-16s %s" % (getattr(p, "name", "?"), status))
    if notes:
        lines.extend(["", "Notes:"] + notes)

    for p in providers:
        try:
            p.close()
        except Exception:
            pass
    return "\n".join(lines)


def _read_file(path: str) -> str:
    try:
        with open(path, "r") as fh:
            return fh.read().strip()
    except Exception as exc:
        return "<%s>" % exc.__class__.__name__


def _section(title: str, fn: Callable[[], str]) -> str:
    try:
        body = fn()
    except Exception as exc:
        body = "failed: %s: %s" % (exc.__class__.__name__, exc)
    return "== %s ==\n%s\n" % (title, body)


def _psutil_attr(attr: str) -> str:
    import psutil

    func = getattr(psutil, attr, None)
    if func is None:
        return "psutil.%s not available on this platform" % attr
    data = func()
    if not data:
        return "(empty)"
    out = []
    for name, entries in sorted(data.items()):
        out.append("%s:" % name)
        for e in entries:
            out.append("  " + repr(e))
    return "\n".join(out)


def _hwmon() -> str:
    if not sys.platform.startswith("linux"):
        return "not Linux"
    out = []
    for d in sorted(glob.glob("/sys/class/hwmon/*")):
        out.append("%s  name=%s" % (d, _read_file(os.path.join(d, "name"))))
        files = sorted(
            glob.glob(os.path.join(d, "temp*_input"))
            + glob.glob(os.path.join(d, "fan*_input"))
            + glob.glob(os.path.join(d, "*_label"))
        )
        for f in files:
            out.append("  %s = %s" % (os.path.basename(f), _read_file(f)))
    return "\n".join(out) or "(no hwmon devices)"


def _drm() -> str:
    if not sys.platform.startswith("linux"):
        return "not Linux"
    out = []
    for d in sorted(glob.glob("/sys/class/drm/card*/device")):
        out.append(d)
        try:
            for entry in sorted(os.listdir(d)):
                out.append("  " + entry)
        except Exception as exc:
            out.append("  <%s>" % exc.__class__.__name__)
    return "\n".join(out) or "(no drm cards)"


def _video_controllers() -> str:
    if not sys.platform.startswith("win"):
        return "not Windows"
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=10,
    )
    return proc.stdout.strip() or "(no output) " + proc.stderr.strip()


def dump_report() -> str:
    """Raw platform sensor data for bug reports. Never raises."""
    parts = [
        _section("platform", lambda: "%s\nPython %s" % (platform.platform(), sys.version)),
        _section("psutil.sensors_temperatures", lambda: _psutil_attr("sensors_temperatures")),
        _section("psutil.sensors_fans", lambda: _psutil_attr("sensors_fans")),
        _section("hwmon", _hwmon),
        _section("drm", _drm),
        _section("Win32_VideoController", _video_controllers),
    ]
    return "\n".join(parts)

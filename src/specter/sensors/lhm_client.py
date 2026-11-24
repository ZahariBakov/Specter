"""Client for the LibreHardwareMonitor / OpenHardwareMonitor remote web server.

LHM ("Options -> Remote Web Server") serves ``http://localhost:8085/data.json``: a tree of
nodes ``{"id", "Text", "Min", "Value", "Max", "ImageURL", "Children"}``. Newer LHM versions
also put ``SensorId`` (e.g. ``/intelcpu/0/temperature/6``) and ``Type`` (``Temperature``,
``Fan``...) on sensor nodes. The tree is::

    Sensor -> <computer> -> <hardware> [-> <super-I/O chip>] -> <group> -> <sensor>

``parse_tree()`` flattens it into ``LhmSensor`` records. ``LhmClient`` fetches and caches
them so several providers can share one client. A missing server never raises: the client
returns ``[]`` and waits ``retry_after`` seconds before trying again.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:8085/data.json"
ENV_URL = "SPECTER_LHM_URL"


@dataclass(frozen=True)
class LhmSensor:
    hardware: str  # Text of the hardware node, e.g. "Intel Core i7-12700K", "Nuvoton NCT6798D"
    kind: str  # cpu, gpu-nvidia, gpu-amd, gpu-intel, mainboard, superio, storage, ...
    type: str  # Temperature, Fan, Load, Control, Clock, Power, Data, SmallData, Voltage, ...
    name: str  # sensor Text, e.g. "CPU Package"
    value: float
    unit: str  # e.g. "°C", "RPM", "%", "GB"; may be ""


# First path segment of SensorId / HardwareId -> kind.
_ID_KINDS = {
    "intelcpu": "cpu",
    "amdcpu": "cpu",
    "cpu": "cpu",
    "gpu-nvidia": "gpu-nvidia",
    "nvidiagpu": "gpu-nvidia",
    "gpu-amd": "gpu-amd",
    "atigpu": "gpu-amd",
    "gpu-intel": "gpu-intel",
    "lpc": "superio",
    "mainboard": "mainboard",
    "hdd": "storage",
    "nvme": "storage",
    "ssd": "storage",
    "storage": "storage",
    "ram": "memory",
    "memory": "memory",
    "nic": "network",
    "battery": "battery",
}

# ImageURL file name -> kind (hardware nodes only; group/sensor icons are not listed).
_IMAGE_KINDS = {
    "cpu.png": "cpu",
    "nvidia.png": "gpu-nvidia",
    "ati.png": "gpu-amd",
    "amd.png": "gpu-amd",
    "intel.png": "gpu-intel",
    "mainboard.png": "mainboard",
    "chip.png": "superio",
    "hdd.png": "storage",
    "ram.png": "memory",
    "nic.png": "network",
    "battery.png": "battery",
}

# Group node Text -> sensor type (used when the sensor node has no "Type").
_GROUP_TYPES = {
    "Temperatures": "Temperature",
    "Fans": "Fan",
    "Load": "Load",
    "Controls": "Control",
    "Data": "Data",
    "SmallData": "SmallData",
    "Small Data": "SmallData",
    "Clocks": "Clock",
    "Powers": "Power",
    "Voltages": "Voltage",
    "Currents": "Current",
    "Levels": "Level",
    "Factors": "Factor",
    "Flows": "Flow",
    "Throughput": "Throughput",
    "Energy": "Energy",
    "Noise": "Noise",
    "Timing": "Timing",
}

_VALUE_RE = re.compile(r"^\s*([-+]?\d[\d\s  .,]*\d|[-+]?\d)\s*(.*?)\s*$")


def parse_value(text: Any) -> Optional[Tuple[float, str]]:
    """``"45,0 °C"`` -> ``(45.0, "°C")``. Returns None for "-", "" or anything unparsable."""
    if not isinstance(text, str):
        if isinstance(text, (int, float)) and not isinstance(text, bool):
            return float(text), ""
        return None
    match = _VALUE_RE.match(text)
    if match is None:
        return None
    number = re.sub(r"[\s  ]", "", match.group(1))
    unit = match.group(2)
    if "," in number and "." in number:
        # The later separator is the decimal one: "1,234.5" or "1.234,5".
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif "," in number:
        number = number.replace(",", "") if number.count(",") > 1 else number.replace(",", ".")
    elif number.count(".") > 1:
        number = number.replace(".", "")
    try:
        return float(number), unit
    except ValueError:
        return None


def _id_kind(ident: Any) -> Optional[str]:
    if not isinstance(ident, str) or not ident.startswith("/"):
        return None
    head = ident[1:].split("/", 1)[0].lower()
    return _ID_KINDS.get(head)


def _image_kind(url: Any) -> Optional[str]:
    if not isinstance(url, str) or not url:
        return None
    name = url.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return _IMAGE_KINDS.get(name)


def _children(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    kids = node.get("Children")
    if not isinstance(kids, list):
        return []
    return [k for k in kids if isinstance(k, dict)]


def _is_group(node: Dict[str, Any]) -> bool:
    return str(node.get("Text", "")) in _GROUP_TYPES and bool(_children(node))


def _is_hardware(node: Dict[str, Any]) -> bool:
    kids = _children(node)
    if not kids or _is_group(node):
        return False
    if _image_kind(node.get("ImageURL")) or _id_kind(node.get("HardwareId")):
        return True
    return any(_is_group(k) for k in kids)


def parse_tree(data: Any) -> List[LhmSensor]:
    """Flatten a data.json tree into sensors. Never raises; bad nodes are skipped."""
    out: List[LhmSensor] = []
    if not isinstance(data, dict):
        return out

    def walk(node: Dict[str, Any], hw: str, hw_kind: str, group: str, depth: int) -> None:
        if depth > 32:
            return
        kids = _children(node)
        if not kids:
            if not hw:
                return
            parsed = parse_value(node.get("Value"))
            if parsed is None:
                return
            kind = _id_kind(node.get("SensorId")) or hw_kind or "other"
            stype = node.get("Type")
            if not isinstance(stype, str) or not stype:
                stype = _GROUP_TYPES.get(group, group)
            out.append(
                LhmSensor(
                    hardware=hw,
                    kind=kind,
                    type=stype,
                    name=str(node.get("Text", "")),
                    value=parsed[0],
                    unit=parsed[1],
                )
            )
            return
        if _is_group(node):
            group = str(node.get("Text", ""))
        elif _is_hardware(node):
            hw = str(node.get("Text", ""))
            hw_kind = (
                _id_kind(node.get("HardwareId")) or _image_kind(node.get("ImageURL")) or "other"
            )
            group = ""
        for kid in kids:
            try:
                walk(kid, hw, hw_kind, group, depth + 1)
            except Exception:  # noqa: BLE001 - one odd node must not lose the rest
                log.debug("lhm: skipped node", exc_info=True)

    walk(data, "", "", "", 0)
    return out


def _default_fetch(url: str, timeout: float) -> bytes:
    # No proxy: the server is local, and a system proxy would only add delay or fail.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as resp:
        return resp.read()


class LhmClient:
    """Fetches data.json with a short cache and a back-off after failures."""

    def __init__(
        self,
        url: Optional[str] = None,
        timeout: float = 0.5,
        ttl: float = 0.5,
        retry_after: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
        fetch: Optional[Callable[[str, float], bytes]] = None,
    ) -> None:
        env = os.environ.get(ENV_URL, "").strip()
        self.url = url or env or DEFAULT_URL
        self.timeout = timeout
        self.ttl = ttl
        self.retry_after = retry_after
        self._clock = clock
        self._fetch = fetch if fetch is not None else _default_fetch
        self._cache: List[LhmSensor] = []
        self._fetched_at: Optional[float] = None
        self._failed_at: Optional[float] = None
        self.reachable = False
        self.last_error: Optional[str] = None

    def sensors(self) -> List[LhmSensor]:
        """Current sensors, or ``[]`` when the server is unreachable. Never raises."""
        try:
            now = self._clock()
            failed_at = self._failed_at
            if failed_at is not None and now - failed_at < self.retry_after:
                return []
            fetched_at = self._fetched_at
            if fetched_at is not None and now - fetched_at < self.ttl:
                return list(self._cache)
            return self._refresh(now)
        except Exception as exc:  # noqa: BLE001 - must never raise
            self._fail(exc)
            return []

    def _refresh(self, now: float) -> List[LhmSensor]:
        try:
            raw = self._fetch(self.url, self.timeout)
            if isinstance(raw, bytes):
                text = raw.decode("utf-8-sig", errors="replace")
            else:
                text = str(raw)
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("data.json root is not an object")
            sensors = parse_tree(data)
        except Exception as exc:  # noqa: BLE001
            self._fail(exc, now)
            return []
        self._cache = sensors
        self._fetched_at = now
        self._failed_at = None
        self.reachable = True
        self.last_error = None
        return list(sensors)

    def _fail(self, exc: BaseException, now: Optional[float] = None) -> None:
        if now is None:
            try:
                now = self._clock()
            except Exception:  # noqa: BLE001
                now = 0.0
        if self.reachable or self.last_error is None:
            log.info("LibreHardwareMonitor not reachable at %s: %s", self.url, exc)
        self.last_error = "%s: %s" % (type(exc).__name__, exc)
        self.reachable = False
        self._failed_at = now
        self._cache = []
        self._fetched_at = None

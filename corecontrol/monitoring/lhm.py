"""Sensorwerte aus LibreHardwareMonitor (optional, kostenlos, MPL-2.0).

Windows bietet keine offizielle Schnittstelle für CPU-Temperatur, Lüfter und
Spannungen. CoreControl lädt deshalb keinen eigenen Treiber, sondern liest die
Werte von LibreHardwareMonitor, falls der Benutzer es gestartet hat:

1. WMI-Namensraum root\\LibreHardwareMonitor (LibreHardwareMonitor läuft)
2. Alternativ der eingebaute Webserver (Options → Remote Web Server), Standard-Port 8085

Läuft LibreHardwareMonitor nicht, werden diese Werte als „nicht verfügbar“ angezeigt.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Any

from corecontrol.monitoring.models import SensorReading

log = logging.getLogger(__name__)

UNITS = {
    "temperature": "°C", "fan": "RPM", "voltage": "V", "power": "W", "clock": "MHz", "load": "%",
    "control": "%", "data": "GB", "smalldata": "MB", "throughput": "B/s", "level": "%", "current": "A",
    "energy": "mWh", "frequency": "Hz", "flow": "L/h", "factor": "", "timespan": "s", "noise": "dBA",
}

GROUP_KINDS = {
    "temperatures": "temperature", "fans": "fan", "voltages": "voltage", "powers": "power", "clocks": "clock",
    "load": "load", "controls": "control", "data": "data", "levels": "level", "currents": "current",
    "throughput": "throughput", "factors": "factor", "energies": "energy", "noises": "noise",
}

_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def hw_kind_from_identifier(identifier: str) -> str:
    ident = identifier.lower()
    if ident.startswith(("/amdcpu", "/intelcpu", "/cpu")):
        return "cpu"
    if ident.startswith(("/gpu", "/nvidiagpu", "/atigpu", "/amdgpu")):
        return "gpu"
    if ident.startswith(("/lpc", "/mainboard", "/motherboard", "/ec")):
        return "board"
    if ident.startswith(("/hdd", "/nvme", "/ssd", "/storage")):
        return "storage"
    if ident.startswith(("/ram", "/memory")):
        return "memory"
    return "other"


def parse_value(text: Any) -> float | None:
    if isinstance(text, (int, float)):
        return float(text)
    if not isinstance(text, str):
        return None
    m = _NUM.search(text.replace(" ", "").replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def parse_data_json(data: dict) -> list[SensorReading]:
    """Wertet die data.json des LibreHardwareMonitor-Webservers aus."""
    out: list[SensorReading] = []

    def walk(node: dict, hardware: str, hw_kind: str, group_kind: str | None, depth: int) -> None:
        children = node.get("Children") or []
        text = str(node.get("Text", ""))
        sensor_id = node.get("SensorId")
        if sensor_id or (not children and depth >= 3 and node.get("Value")):
            kind = str(node.get("Type") or group_kind or "other").lower()
            value = node.get("RawValue") if isinstance(node.get("RawValue"), (int, float)) else parse_value(node.get("Value"))
            if value is not None:
                ident = str(sensor_id or "")
                hk = hw_kind_from_identifier(ident) if ident else hw_kind
                out.append(SensorReading(hardware, hk, text, kind, value, UNITS.get(kind, ""), ident))
            return
        # Hardware-Ebene erkennen (Ebene 2 = Gerät, z. B. CPU / GPU)
        new_hw, new_kind, new_group = hardware, hw_kind, group_kind
        lowered = text.lower()
        if lowered in GROUP_KINDS:
            new_group = GROUP_KINDS[lowered]
        elif depth >= 2:
            new_hw = text
            new_kind = _kind_from_image(str(node.get("ImageURL", "")), hw_kind)
        for ch in children:
            if isinstance(ch, dict):
                walk(ch, new_hw, new_kind, new_group, depth + 1)

    if isinstance(data, dict):
        walk(data, "", "other", None, 0)
    return out


def _kind_from_image(url: str, default: str) -> str:
    u = url.lower()
    if "cpu" in u:
        return "cpu"
    if any(x in u for x in ("nvidia", "ati", "amd", "intel", "gpu")):
        return "gpu"
    if "mainboard" in u or "chip" in u:
        return "board"
    if "hdd" in u or "nvme" in u or "ssd" in u:
        return "storage"
    if "ram" in u:
        return "memory"
    return default


def parse_wmi_rows(sensors: list[dict], hardware: list[dict]) -> list[SensorReading]:
    names = {h.get("Identifier"): h.get("Name", "") for h in hardware}
    out = []
    for s in sensors:
        kind = str(s.get("SensorType", "other")).lower()
        try:
            value = float(s.get("Value"))
        except (TypeError, ValueError):
            continue
        ident = str(s.get("Identifier", ""))
        parent = s.get("Parent", "")
        out.append(SensorReading(names.get(parent, parent or ""), hw_kind_from_identifier(ident),
                                 str(s.get("Name", "")), kind, value, UNITS.get(kind, ""), ident))
    return out


def pick_cpu_temp(sensors: list[SensorReading]) -> float | None:
    """Wählt die aussagekräftigste CPU-Temperatur (Package bzw. Tctl/Tdie)."""
    cpu = [s for s in sensors if s.hw_kind == "cpu" and s.kind == "temperature" and 0 < s.value < 150]
    if not cpu:
        return None
    for pref in ("cpu package", "package", "core (tctl/tdie)", "tctl/tdie", "tdie", "tctl", "core average", "cpu"):
        for s in cpu:
            if s.name.lower() == pref:
                return s.value
    real = [s for s in cpu if "distance" not in s.name.lower()]
    return max(s.value for s in real) if real else None


def pick_cpu_power(sensors: list[SensorReading]) -> float | None:
    for s in sensors:
        if s.hw_kind == "cpu" and s.kind == "power" and s.name.lower() in ("cpu package", "package"):
            return s.value
    return None


def pick_gpu_temp(sensors: list[SensorReading], gpu_name: str = "") -> float | None:
    cand = [s for s in sensors if s.hw_kind == "gpu" and s.kind == "temperature" and 0 < s.value < 150]
    if gpu_name:
        named = [s for s in cand if gpu_name.lower()[:12] in s.hardware.lower() or s.hardware.lower()[:12] in gpu_name.lower()]
        cand = named or cand
    for s in cand:
        if s.name.lower() in ("gpu core", "gpu", "core", "edge"):
            return s.value
    # Hotspot-Werte bewusst nicht als Haupttemperatur verwenden
    rest = [s for s in cand if "hot" not in s.name.lower() and "junction" not in s.name.lower() and "memory" not in s.name.lower()]
    return rest[0].value if rest else None


class LhmReader:
    """Liest LibreHardwareMonitor über WMI, sonst über HTTP."""

    def __init__(self, port: int = 8085):
        self.port = port
        self.method: str | None = None
        self._wmi = None

    def read(self) -> tuple[str, list[SensorReading]]:
        """Gibt (Status, Sensoren) zurück. Status: ok, not_running, error."""
        if self.method in (None, "wmi"):
            try:
                rows = self._read_wmi()
                if rows:
                    self.method = "wmi"
                    return "ok", rows
            except Exception as exc:
                log.debug("LHM-WMI nicht erreichbar: %s", exc)
                self._wmi = None
        try:
            rows = self._read_http()
            self.method = "http"
            return ("ok" if rows else "not_running"), rows
        except Exception as exc:
            log.debug("LHM-Webserver nicht erreichbar: %s", exc)
            self.method = None
            return "not_running", []

    def _read_wmi(self) -> list[SensorReading]:
        from corecontrol.system import wmi

        if self._wmi is None:
            self._wmi = wmi.connect("root\\LibreHardwareMonitor")
        sensors = wmi.query_conn(self._wmi, "SELECT Name, Identifier, SensorType, Parent, Value FROM Sensor",
                                 ["Name", "Identifier", "SensorType", "Parent", "Value"])
        hardware = wmi.query_conn(self._wmi, "SELECT Name, Identifier FROM Hardware", ["Name", "Identifier"])
        return parse_wmi_rows(sensors, hardware)

    def _read_http(self) -> list[SensorReading]:
        url = f"http://127.0.0.1:{self.port}/data.json"
        handler = urllib.request.ProxyHandler({})  # lokaler Zugriff, nie über Proxy
        opener = urllib.request.build_opener(handler)
        with opener.open(url, timeout=0.6) as resp:
            data = json.loads(resp.read(5_000_000).decode("utf-8", errors="replace"))
        return parse_data_json(data)

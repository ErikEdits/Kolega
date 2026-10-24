"""AMD-Grafikkarten: Live-Werte direkt aus dem AMD-Treiber (AMD Display Library, atiadlxx.dll).

Das sind dieselben Treiberwerte, die auch „AMD Software: Adrenalin Edition“ anzeigt:
Auslastung, Temperaturen (GPU, Hotspot, Speicher), Platinenleistung, Takt, Lüfter,
belegter Grafikspeicher. Die DLL gehört zum installierten AMD-Grafiktreiber;
CoreControl liefert sie nicht mit und installiert nichts.

Funktionsnamen, Strukturen und Sensornummern entsprechen den Headern des
AMD Display Library SDK (adl_defines.h, adl_structures.h; MIT-Lizenz, © AMD).
Das neuere ADLX wird bewusst nicht verwendet: Seine Lizenz schließt Open-Source-
Programme unter GPL aus.
"""

from __future__ import annotations

import ctypes
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from corecontrol.core.platform import IS_WINDOWS

log = logging.getLogger(__name__)

ADL_OK = 0
ADL_MAX_PATH = 256
ADL_PMLOG_MAX_SENSORS = 256
AMD_VENDOR_ID = 1002  # ADL meldet die PCI-Hersteller-ID 0x1002 als Dezimalzahl 1002

# Sensornummern aus ADL_PMLOG_SENSORS (adl_defines.h)
PMLOG = {
    "gfx_clock": 1,          # ADL_PMLOG_CLK_GFXCLK, MHz
    "mem_clock": 2,          # ADL_PMLOG_CLK_MEMCLK, MHz
    "temp_edge": 8,          # ADL_PMLOG_TEMPERATURE_EDGE, °C
    "temp_mem": 9,           # ADL_PMLOG_TEMPERATURE_MEM, °C
    "fan_rpm": 14,           # ADL_PMLOG_FAN_RPM
    "fan_pct": 15,           # ADL_PMLOG_FAN_PERCENTAGE
    "activity_gfx": 19,      # ADL_PMLOG_INFO_ACTIVITY_GFX, %
    "asic_power": 23,        # ADL_PMLOG_ASIC_POWER, W
    "temp_hotspot": 27,      # ADL_PMLOG_TEMPERATURE_HOTSPOT, °C
    "temp_cpu": 32,          # ADL_PMLOG_TEMPERATURE_CPU, °C (nur bei manchen Systemen)
    "board_power": 73,       # ADL_PMLOG_BOARD_POWER, W
}

# Werte außerhalb dieser Grenzen gelten als ungültig und werden nicht angezeigt.
_PLAUSIBLE = {
    "gfx_clock": (1, 10000), "mem_clock": (1, 20000),
    "temp_edge": (1, 150), "temp_mem": (1, 150), "temp_hotspot": (1, 150), "temp_cpu": (1, 150),
    "fan_rpm": (0, 10000), "fan_pct": (0, 100), "activity_gfx": (0, 100),
    "asic_power": (0, 1500), "board_power": (1, 1500),
}


class _AdapterInfo(ctypes.Structure):
    _fields_ = [
        ("iSize", ctypes.c_int),
        ("iAdapterIndex", ctypes.c_int),
        ("strUDID", ctypes.c_char * ADL_MAX_PATH),
        ("iBusNumber", ctypes.c_int),
        ("iDeviceNumber", ctypes.c_int),
        ("iFunctionNumber", ctypes.c_int),
        ("iVendorID", ctypes.c_int),
        ("strAdapterName", ctypes.c_char * ADL_MAX_PATH),
        ("strDisplayName", ctypes.c_char * ADL_MAX_PATH),
        ("iPresent", ctypes.c_int),
        ("iExist", ctypes.c_int),
        ("strDriverPath", ctypes.c_char * ADL_MAX_PATH),
        ("strDriverPathExt", ctypes.c_char * ADL_MAX_PATH),
        ("strPNPString", ctypes.c_char * ADL_MAX_PATH),
        ("iOSDisplayIndex", ctypes.c_int),
    ]


class _SingleSensorData(ctypes.Structure):
    _fields_ = [("supported", ctypes.c_int), ("value", ctypes.c_int)]


class _PMLogDataOutput(ctypes.Structure):
    _fields_ = [("size", ctypes.c_int), ("sensors", _SingleSensorData * ADL_PMLOG_MAX_SENSORS)]


@dataclass
class AmdGpu:
    name: str
    index: int          # ADL-Adapterindex
    bus: int
    overdrive: int      # Overdrive-Version (8 = Navi/RDNA)


def parse_pmlog(sensors: list[tuple[int, int]]) -> dict[str, float]:
    """Wandelt die Sensorliste (unterstützt, Wert) in benannte, plausible Werte um."""
    out: dict[str, float] = {}
    for key, idx in PMLOG.items():
        if idx >= len(sensors):
            continue
        supported, value = sensors[idx]
        if not supported:
            continue
        lo, hi = _PLAUSIBLE[key]
        if lo <= value <= hi:
            out[key] = float(value)
    return out


def pick_adapters(infos: list[dict]) -> list[dict]:
    """Ein Eintrag pro AMD-Grafikkarte (ADL meldet je Bildschirmausgang einen Adapterindex)."""
    seen: set[tuple] = set()
    out = []
    for a in infos:
        if a.get("vendor") != AMD_VENDOR_ID or not a.get("present", 1):
            continue
        key = (a.get("bus"), a.get("device"), a.get("function"))
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def same_gpu(a: str, b: str) -> bool:
    def norm(s: str) -> str:
        return " ".join(s.lower().replace("(tm)", "").replace("amd", "").split())

    na, nb = norm(a), norm(b)
    return bool(na) and bool(nb) and (na == nb or na in nb or nb in na)


class AdlReader:
    """Liest AMD-Treiberwerte. Alle Aufrufe aus demselben Thread (Messthread)."""

    def __init__(self, dll_path: str | None = None):
        if not IS_WINDOWS:
            raise OSError("nur unter Windows")
        system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        path = dll_path or os.path.join(system32, "atiadlxx.dll")
        if not os.path.isfile(path):
            raise FileNotFoundError("AMD-Treiber (atiadlxx.dll) nicht installiert")
        # Voller Pfad: keine DLL aus dem Programmordner o. Ä. laden
        self._dll = ctypes.CDLL(path)
        self._msvcrt = ctypes.CDLL("msvcrt")
        self._msvcrt.malloc.restype = ctypes.c_void_p
        self._msvcrt.malloc.argtypes = [ctypes.c_size_t]
        alloc_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int)
        self._alloc = alloc_type(lambda size: self._msvcrt.malloc(max(1, size)))  # Referenz halten!
        self._ctx = ctypes.c_void_p()
        self._fn = {}
        for name, args in (
            ("ADL2_Main_Control_Create", [alloc_type, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]),
            ("ADL2_Main_Control_Destroy", [ctypes.c_void_p]),
            ("ADL2_Adapter_NumberOfAdapters_Get", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]),
            ("ADL2_Adapter_AdapterInfo_Get", [ctypes.c_void_p, ctypes.POINTER(_AdapterInfo), ctypes.c_int]),
            ("ADL2_Overdrive_Caps", [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]),
            ("ADL2_New_QueryPMLogData_Get", [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(_PMLogDataOutput)]),
            ("ADL2_Adapter_VRAMUsage_Get", [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]),
        ):
            f = getattr(self._dll, name, None)
            if f is not None:
                f.argtypes = args
                f.restype = ctypes.c_int
            self._fn[name] = f
        for required in ("ADL2_Main_Control_Create", "ADL2_Main_Control_Destroy", "ADL2_Adapter_NumberOfAdapters_Get",
                         "ADL2_Adapter_AdapterInfo_Get"):
            if self._fn[required] is None:
                raise OSError(f"{required} fehlt im AMD-Treiber")
        rc = self._fn["ADL2_Main_Control_Create"](self._alloc, 1, ctypes.byref(self._ctx))
        if rc != ADL_OK:
            raise OSError(f"ADL2_Main_Control_Create: Fehler {rc}")
        self.gpus: list[AmdGpu] = self._enumerate()
        self.errors: dict[str, int] = {}

    def _enumerate(self) -> list[AmdGpu]:
        n = ctypes.c_int(0)
        if self._fn["ADL2_Adapter_NumberOfAdapters_Get"](self._ctx, ctypes.byref(n)) != ADL_OK or n.value <= 0:
            return []
        count = min(n.value, 64)
        arr = (_AdapterInfo * count)()
        for a in arr:
            a.iSize = ctypes.sizeof(_AdapterInfo)
        if self._fn["ADL2_Adapter_AdapterInfo_Get"](self._ctx, arr, ctypes.sizeof(arr)) != ADL_OK:
            return []
        infos = [{
            "index": a.iAdapterIndex, "name": a.strAdapterName.decode("utf-8", "replace").strip(),
            "vendor": a.iVendorID, "bus": a.iBusNumber, "device": a.iDeviceNumber, "function": a.iFunctionNumber,
            "present": a.iPresent,
        } for a in arr]
        gpus = []
        for a in pick_adapters(infos):
            od = 0
            caps = self._fn["ADL2_Overdrive_Caps"]
            if caps is not None:
                sup, en, ver = ctypes.c_int(0), ctypes.c_int(0), ctypes.c_int(0)
                if caps(self._ctx, a["index"], ctypes.byref(sup), ctypes.byref(en), ctypes.byref(ver)) == ADL_OK:
                    od = ver.value
            gpus.append(AmdGpu(a["name"], a["index"], a["bus"], od))
        return gpus

    def read(self, gpu: AmdGpu) -> dict[str, float]:
        """Aktuelle Werte einer Grafikkarte; fehlende Werte fehlen im Ergebnis."""
        out: dict[str, float] = {}
        q = self._fn["ADL2_New_QueryPMLogData_Get"]
        # Ältere Karten (Overdrive 5–7) kennen die Sensorliste nicht; 0 = Version unbekannt → versuchen.
        if q is not None and not 0 < gpu.overdrive < 8:
            data = _PMLogDataOutput()
            data.size = ctypes.sizeof(_PMLogDataOutput)
            rc = q(self._ctx, gpu.index, ctypes.byref(data))
            if rc == ADL_OK:
                out.update(parse_pmlog([(s.supported, s.value) for s in data.sensors]))
            else:
                self._note("pmlog", rc)
        vram = self._fn["ADL2_Adapter_VRAMUsage_Get"]
        if vram is not None:
            mb = ctypes.c_int(-1)
            rc = vram(self._ctx, gpu.index, ctypes.byref(mb))
            if rc == ADL_OK and mb.value >= 0:
                out["vram_used_mb"] = float(mb.value)
            elif rc != ADL_OK:
                self._note("vram", rc)
        return out

    def _note(self, what: str, rc: int) -> None:
        n = self.errors.get(what, 0) + 1
        self.errors[what] = n
        if n <= 2:
            log.info("AMD-Treiber: %s nicht verfügbar (Fehler %s)", what, rc)

    def close(self) -> None:
        if self._ctx:
            try:
                self._fn["ADL2_Main_Control_Destroy"](self._ctx)
            except Exception:
                pass
            self._ctx = ctypes.c_void_p()


def open_guarded(probe_file: Path | None) -> AdlReader | None:
    """Öffnet den AMD-Treiberzugang mit Absturzschutz.

    Vor dem ersten Zugriff wird eine Markierungsdatei angelegt und nach einem
    erfolgreichen Lesen wieder gelöscht. Stürzt CoreControl dazwischen ab (z. B. wegen
    eines fehlerhaften Treibers), findet der nächste Start die Datei und lässt die
    AMD-Treiberwerte aus. Wieder einschalten: Einstellungen → Messung & Sensoren.
    """
    if probe_file is not None and probe_file.exists():
        log.warning("AMD-Treiberwerte ausgelassen: Der letzte Versuch wurde nicht abgeschlossen (%s).", probe_file)
        return None
    try:
        if probe_file is not None:
            probe_file.parent.mkdir(parents=True, exist_ok=True)
            probe_file.write_text("ADL-Zugriff begonnen", encoding="utf-8")
        reader = AdlReader()
        for g in reader.gpus:
            reader.read(g)
        log.info("AMD-Treiber: %s", ", ".join(f"{g.name} (Overdrive {g.overdrive})" for g in reader.gpus) or "keine AMD-GPU")
        if not reader.gpus:
            reader.close()
            reader = None
    except Exception as exc:
        log.info("AMD-Treiberwerte nicht verfügbar: %s", exc)
        reader = None
    if probe_file is not None:
        try:
            probe_file.unlink()
        except OSError:
            pass
    return reader

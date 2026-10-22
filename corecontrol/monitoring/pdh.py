"""Windows-Leistungsindikatoren (PDH) über ctypes.

Wird für Werte genutzt, die psutil nicht liefert: GPU-Auslastung und Grafikspeicher
(alle Hersteller, WDDM 2.0+), aktuelle CPU-Taktrate (wie im Task-Manager) und
Datenträger-Aktivzeit. Es werden die englischen Zählernamen verwendet
(PdhAddEnglishCounterW), damit es auch auf deutschem Windows funktioniert.
Keine Adminrechte nötig.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_LARGE = 0x00000400
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2
ERROR_SUCCESS = 0


class _FmtValueUnion(ctypes.Union):
    _fields_ = [("longValue", ctypes.c_long), ("doubleValue", ctypes.c_double), ("largeValue", ctypes.c_longlong)]


class _FmtValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("u", _FmtValueUnion)]


class _ItemW(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _FmtValue)]


class PdhQuery:
    """Eine PDH-Abfrage mit mehreren (auch Platzhalter-)Zählern."""

    def __init__(self):
        if sys.platform != "win32":
            raise OSError("PDH ist nur unter Windows verfügbar")
        self._pdh = ctypes.WinDLL("pdh.dll")
        self._pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self._pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                                                    ctypes.POINTER(ctypes.c_void_p)]
        self._pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        self._pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                           ctypes.POINTER(wintypes.DWORD),
                                                           ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self._pdh.PdhGetFormattedCounterValue.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                          ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_FmtValue)]
        self._pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        self._query = ctypes.c_void_p()
        rc = self._pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query))
        if rc != ERROR_SUCCESS:
            raise OSError(f"PdhOpenQuery: 0x{rc & 0xFFFFFFFF:08X}")
        self._counters: dict[str, ctypes.c_void_p] = {}

    def add(self, name: str, path: str) -> bool:
        h = ctypes.c_void_p()
        rc = self._pdh.PdhAddEnglishCounterW(self._query, path, None, ctypes.byref(h))
        if rc != ERROR_SUCCESS:
            log.info("PDH-Zähler nicht verfügbar: %s (0x%08X)", path, rc & 0xFFFFFFFF)
            return False
        self._counters[name] = h
        return True

    def has(self, name: str) -> bool:
        return name in self._counters

    def collect(self) -> bool:
        return self._pdh.PdhCollectQueryData(self._query) == ERROR_SUCCESS

    def value(self, name: str, fmt: int = PDH_FMT_DOUBLE) -> float | None:
        h = self._counters.get(name)
        if h is None:
            return None
        val = _FmtValue()
        rc = self._pdh.PdhGetFormattedCounterValue(h, fmt | PDH_FMT_NOCAP100, None, ctypes.byref(val))
        if rc != ERROR_SUCCESS or val.CStatus not in (0, 1):
            return None
        return float(val.u.largeValue) if fmt == PDH_FMT_LARGE else float(val.u.doubleValue)

    def array(self, name: str, fmt: int = PDH_FMT_DOUBLE) -> dict[str, float]:
        """Werte aller Instanzen eines Platzhalter-Zählers (z. B. GPU Engine(*))."""
        h = self._counters.get(name)
        if h is None:
            return {}
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        rc = self._pdh.PdhGetFormattedCounterArrayW(h, fmt | PDH_FMT_NOCAP100, ctypes.byref(size), ctypes.byref(count), None)
        if (rc & 0xFFFFFFFF) != PDH_MORE_DATA or size.value == 0:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        rc = self._pdh.PdhGetFormattedCounterArrayW(h, fmt | PDH_FMT_NOCAP100, ctypes.byref(size), ctypes.byref(count), buf)
        if rc != ERROR_SUCCESS:
            return {}
        items = ctypes.cast(buf, ctypes.POINTER(_ItemW))
        out: dict[str, float] = {}
        for i in range(count.value):
            it = items[i]
            if it.FmtValue.CStatus not in (0, 1):
                continue
            v = float(it.FmtValue.u.largeValue) if fmt == PDH_FMT_LARGE else float(it.FmtValue.u.doubleValue)
            key = it.szName or ""
            out[key] = out.get(key, 0.0) + v
        return out

    def close(self) -> None:
        try:
            self._pdh.PdhCloseQuery(self._query)
        except Exception:
            pass


def parse_gpu_engine_instance(name: str) -> tuple[str, str] | None:
    """'pid_123_luid_0x00000000_0x0000D1B2_phys_0_eng_3_engtype_3D' -> ('0x00000000_0x0000D1B2', 'phys_0_eng_3')."""
    low = name.lower()
    try:
        i = low.index("luid_")
        rest = low[i + 5:]
        parts = rest.split("_")
        luid = f"{parts[0]}_{parts[1]}"
        j = low.index("phys_")
        k = low.index("_engtype")
        engine = low[j:k]
        return luid, engine
    except (ValueError, IndexError):
        return None


def gpu_util_by_luid(engine_values: dict[str, float]) -> dict[str, float]:
    """Wie der Task-Manager: Summe pro Engine über alle Prozesse, davon das Maximum pro Grafikkarte."""
    per_engine: dict[tuple[str, str], float] = {}
    for inst, v in engine_values.items():
        parsed = parse_gpu_engine_instance(inst)
        if not parsed:
            continue
        per_engine[parsed] = per_engine.get(parsed, 0.0) + v
    out: dict[str, float] = {}
    for (luid, _eng), v in per_engine.items():
        out[luid] = max(out.get(luid, 0.0), min(v, 100.0))
    return out


def parse_adapter_memory_instance(name: str) -> str | None:
    """'luid_0x00000000_0x0000D1B2_phys_0' -> '0x00000000_0x0000d1b2'."""
    low = name.lower()
    if "luid_" not in low:
        return None
    parts = low[low.index("luid_") + 5:].split("_")
    if len(parts) < 2:
        return None
    return f"{parts[0]}_{parts[1]}"

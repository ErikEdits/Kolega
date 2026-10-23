"""Grafikkarten: Erkennung über DXGI (alle Hersteller) und Zusatzwerte über NVIDIA NVML.

- DXGI liefert Name, Hersteller, Grafikspeicher und die LUID jeder Grafikkarte.
  Über die LUID werden die Windows-Leistungsindikatoren (Auslastung, Speicher)
  der richtigen Karte zugeordnet.
- NVML (Teil des NVIDIA-Treibers) liefert bei NVIDIA zusätzlich Temperatur,
  Takt, Leistungsaufnahme und Lüfter. Für AMD/Intel-Temperaturen wird
  LibreHardwareMonitor benötigt (siehe sensors/lhm.py).
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

VENDORS = {0x10DE: "nvidia", 0x1002: "amd", 0x1022: "amd", 0x8086: "intel", 0x1414: "microsoft", 0x5143: "qualcomm"}


@dataclass
class GpuAdapter:
    name: str
    vendor: str
    vendor_id: int
    device_id: int
    dedicated_vram: int
    shared_mem: int
    luid: str  # Format wie in PDH: 0x{high:08x}_0x{low:08x}
    software: bool = False


def enumerate_adapters() -> list[GpuAdapter]:
    if sys.platform != "win32":
        return []
    try:
        return _enum_dxgi()
    except Exception as exc:
        log.info("DXGI-Abfrage fehlgeschlagen: %s", exc)
        return []


def _enum_dxgi() -> list[GpuAdapter]:
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class DXGI_ADAPTER_DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", wintypes.WCHAR * 128),
            ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t), ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t), ("AdapterLuid", LUID), ("Flags", wintypes.UINT),
        ]

    # IID_IDXGIFactory1 {770aae78-f26f-4dba-a829-253c83d1b387}
    iid = GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    dxgi = ctypes.WinDLL("dxgi.dll")
    factory = ctypes.c_void_p()
    hr = dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory))
    if hr != 0 or not factory:
        raise OSError(f"CreateDXGIFactory1 hr=0x{hr & 0xFFFFFFFF:08X}")

    def vcall(obj, index, restype, *argtypes):
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return proto(vtbl[index])

    adapters: list[GpuAdapter] = []
    try:
        enum_adapters1 = vcall(factory, 12, ctypes.c_long, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
        i = 0
        while i < 16:
            adapter = ctypes.c_void_p()
            hr = enum_adapters1(factory, i, ctypes.byref(adapter))
            if hr != 0 or not adapter:
                break  # DXGI_ERROR_NOT_FOUND
            try:
                desc = DXGI_ADAPTER_DESC1()
                get_desc1 = vcall(adapter, 10, ctypes.c_long, ctypes.POINTER(DXGI_ADAPTER_DESC1))
                if get_desc1(adapter, ctypes.byref(desc)) == 0:
                    luid = f"0x{desc.AdapterLuid.HighPart & 0xFFFFFFFF:08x}_0x{desc.AdapterLuid.LowPart:08x}"
                    adapters.append(GpuAdapter(
                        name=desc.Description.strip(),
                        vendor=VENDORS.get(desc.VendorId, "other"),
                        vendor_id=desc.VendorId,
                        device_id=desc.DeviceId,
                        dedicated_vram=int(desc.DedicatedVideoMemory),
                        shared_mem=int(desc.SharedSystemMemory),
                        luid=luid,
                        software=bool(desc.Flags & 0x2),
                    ))
            finally:
                vcall(adapter, 2, ctypes.c_ulong)(adapter)  # Release
            i += 1
    finally:
        vcall(factory, 2, ctypes.c_ulong)(factory)
    return adapters


class Nvml:
    """Dünner Wrapper um nvidia-ml-py. Ist kein NVIDIA-Treiber vorhanden, bleibt alles „nicht verfügbar“."""

    def __init__(self):
        self.ok = False
        self.handles: list = []
        self.names: list[str] = []
        try:
            import pynvml

            self._n = pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(h)
                self.handles.append(h)
                self.names.append(name.decode() if isinstance(name, bytes) else str(name))
            self.ok = count > 0
        except Exception as exc:
            log.info("NVML nicht verfügbar: %s", exc)

    def read(self, index: int) -> dict:
        n = self._n
        h = self.handles[index]
        out: dict = {}

        def safe(key, fn):
            try:
                out[key] = fn()
            except Exception:
                out[key] = None

        safe("temp", lambda: float(n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU)))
        safe("util", lambda: float(n.nvmlDeviceGetUtilizationRates(h).gpu))
        safe("mem", lambda: n.nvmlDeviceGetMemoryInfo(h))
        safe("clock", lambda: float(n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_GRAPHICS)))
        safe("power", lambda: n.nvmlDeviceGetPowerUsage(h) / 1000.0)
        safe("fan", lambda: float(n.nvmlDeviceGetFanSpeed(h)))
        mem = out.pop("mem", None)
        out["vram_used"] = int(mem.used) if mem is not None else None
        out["vram_total"] = int(mem.total) if mem is not None else None
        return out

    def close(self) -> None:
        if self.ok:
            try:
                self._n.nvmlShutdown()
            except Exception:
                pass

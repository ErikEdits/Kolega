"""Hardware- und Systeminformationen (einmalig bzw. auf Anfrage, im Hintergrund).

Jeder Bereich wird einzeln abgefragt. Schlägt ein Bereich fehl, wird das in
`errors` vermerkt und die übrigen Informationen bleiben verfügbar.
"""

from __future__ import annotations

import logging
import os
import platform
import socket
import time
from datetime import datetime
from typing import Any

import psutil

from corecontrol.core.platform import IS_WINDOWS, is_admin

log = logging.getLogger(__name__)

GPU_CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"

MEDIA_TYPES = {3: "HDD", 4: "SSD", 5: "SCM"}
BUS_TYPES = {1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "IEEE 1394", 5: "SSA", 6: "Fibre Channel", 7: "USB", 8: "RAID",
             9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC", 15: "File Backed Virtual", 16: "Storage Spaces",
             17: "NVMe", 18: "SCM", 19: "UFS"}
HEALTH = {0: "healthy", 1: "warning", 2: "unhealthy", 5: "unknown"}


def to_int(v: Any) -> int | None:
    try:
        if v is None or v == "":
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _clean(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    return "" if s.lower() in ("to be filled by o.e.m.", "default string", "system product name",
                               "system manufacturer", "not applicable", "none", "o.e.m.") else s


def collect_hardware() -> dict[str, Any]:
    hw: dict[str, Any] = {"collected_at": time.time(), "errors": {}, "admin": is_admin(), "platform": "windows" if IS_WINDOWS else "other"}
    sections = [("os", _os), ("cpu", _cpu), ("board", _board), ("memory", _memory), ("gpus", _gpus),
                ("disks", _disks), ("volumes", _volumes), ("problem_devices", _problem_devices),
                ("pending_reboot", _pending_reboot)]
    if IS_WINDOWS:
        from corecontrol.system.wmi import com_thread

        with com_thread():
            for name, fn in sections:
                _run(hw, name, fn)
    else:
        for name, fn in sections:
            _run(hw, name, fn)
    return hw


def _run(hw: dict, name: str, fn) -> None:
    try:
        hw[name] = fn()
    except Exception as exc:
        log.warning("Hardwarebereich %s nicht verfügbar: %s", name, exc)
        hw["errors"][name] = f"{type(exc).__name__}: {exc}"
        hw[name] = None


# --------------------------------------------------------------------------
def _reg(root, path: str, name: str) -> Any:
    import winreg

    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _os() -> dict:
    boot = psutil.boot_time()
    info: dict[str, Any] = {
        "computer_name": socket.gethostname(),
        "boot_time": boot,
        "uptime_s": time.time() - boot,
        "arch": platform.machine(),
    }
    if not IS_WINDOWS:
        info.update(name=f"{platform.system()} {platform.release()}", version=platform.version(), build=None,
                    display_version="", edition="", install_date=None, family="other")
        return info
    import winreg

    from corecontrol.system import wmi

    rows = wmi.query("SELECT Caption, Version, BuildNumber, OSArchitecture, InstallDate FROM Win32_OperatingSystem",
                     ["Caption", "Version", "BuildNumber", "OSArchitecture", "InstallDate"])
    r = rows[0] if rows else {}
    nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    build = to_int(r.get("BuildNumber")) or to_int(_reg(winreg.HKEY_LOCAL_MACHINE, nt, "CurrentBuildNumber"))
    caption = _clean(r.get("Caption")) or _reg(winreg.HKEY_LOCAL_MACHINE, nt, "ProductName") or "Windows"
    # Registry meldet auf Windows 11 teils noch „Windows 10“ – Build-Nummer ist maßgeblich.
    if build and build >= 22000 and "Windows 10" in caption:
        caption = caption.replace("Windows 10", "Windows 11")
    info.update(
        name=caption.replace("Microsoft ", ""),
        version=r.get("Version") or "",
        build=build,
        ubr=_reg(winreg.HKEY_LOCAL_MACHINE, nt, "UBR"),
        display_version=_reg(winreg.HKEY_LOCAL_MACHINE, nt, "DisplayVersion") or _reg(winreg.HKEY_LOCAL_MACHINE, nt, "ReleaseId") or "",
        edition=_reg(winreg.HKEY_LOCAL_MACHINE, nt, "EditionID") or "",
        arch=r.get("OSArchitecture") or platform.machine(),
        install_date=wmi.parse_datetime(r.get("InstallDate")),
        family="win11" if build and build >= 22000 else "win10" if build and build >= 10240 else "older",
    )
    return info


def _cpu() -> dict:
    info: dict[str, Any] = {
        "cores": psutil.cpu_count(logical=False),
        "threads": psutil.cpu_count(logical=True),
        "name": "",
        "base_mhz": None,
        "max_mhz": None,
    }
    if IS_WINDOWS:
        import winreg

        key = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        info["name"] = (_reg(winreg.HKEY_LOCAL_MACHINE, key, "ProcessorNameString") or "").strip()
        info["base_mhz"] = _reg(winreg.HKEY_LOCAL_MACHINE, key, "~MHz")
        info["vendor"] = _reg(winreg.HKEY_LOCAL_MACHINE, key, "VendorIdentifier") or ""
        try:
            from corecontrol.system import wmi

            rows = wmi.query("SELECT MaxClockSpeed, SocketDesignation FROM Win32_Processor", ["MaxClockSpeed", "SocketDesignation"])
            if rows:
                info["max_mhz"] = to_int(rows[0].get("MaxClockSpeed"))
                info["socket"] = _clean(rows[0].get("SocketDesignation"))
                info["sockets"] = len(rows)
        except Exception as exc:
            log.info("Win32_Processor: %s", exc)
    else:
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        info["name"] = line.split(":", 1)[1].strip()
                        break
        except OSError:
            info["name"] = platform.processor()
        f = psutil.cpu_freq()
        if f:
            info["max_mhz"] = f.max or None
    return info


def _board() -> dict:
    if not IS_WINDOWS:
        out = {}
        for k, f in (("manufacturer", "board_vendor"), ("product", "board_name"), ("bios_version", "bios_version"),
                     ("system_manufacturer", "sys_vendor"), ("system_model", "product_name")):
            try:
                with open(f"/sys/class/dmi/id/{f}", encoding="utf-8") as fh:
                    out[k] = _clean(fh.read())
            except OSError:
                out[k] = ""
        return out
    from corecontrol.system import wmi

    b = (wmi.query("SELECT Manufacturer, Product FROM Win32_BaseBoard", ["Manufacturer", "Product"]) or [{}])[0]
    bios = (wmi.query("SELECT Manufacturer, SMBIOSBIOSVersion, ReleaseDate FROM Win32_BIOS",
                      ["Manufacturer", "SMBIOSBIOSVersion", "ReleaseDate"]) or [{}])[0]
    cs = (wmi.query("SELECT Manufacturer, Model, PCSystemType FROM Win32_ComputerSystem",
                    ["Manufacturer", "Model", "PCSystemType"]) or [{}])[0]
    return {
        "manufacturer": _clean(b.get("Manufacturer")),
        "product": _clean(b.get("Product")),
        "bios_vendor": _clean(bios.get("Manufacturer")),
        "bios_version": _clean(bios.get("SMBIOSBIOSVersion")),
        "bios_date": wmi.parse_datetime(bios.get("ReleaseDate")),
        "system_manufacturer": _clean(cs.get("Manufacturer")),
        "system_model": _clean(cs.get("Model")),
        "is_laptop": to_int(cs.get("PCSystemType")) == 2,
    }


def _memory() -> dict:
    vm = psutil.virtual_memory()
    out: dict[str, Any] = {"total": int(vm.total), "modules": [], "slots": None}
    if IS_WINDOWS:
        from corecontrol.system import wmi

        rows = wmi.query(
            "SELECT Capacity, Speed, ConfiguredClockSpeed, Manufacturer, PartNumber, DeviceLocator, SMBIOSMemoryType "
            "FROM Win32_PhysicalMemory",
            ["Capacity", "Speed", "ConfiguredClockSpeed", "Manufacturer", "PartNumber", "DeviceLocator", "SMBIOSMemoryType"])
        types = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 30: "LPDDR4", 35: "LPDDR5"}
        for r in rows:
            out["modules"].append({
                "slot": _clean(r.get("DeviceLocator")),
                "capacity": to_int(r.get("Capacity")),
                "speed": to_int(r.get("Speed")),
                "configured_speed": to_int(r.get("ConfiguredClockSpeed")),
                "manufacturer": _clean(r.get("Manufacturer")),
                "part": _clean(r.get("PartNumber")),
                "type": types.get(to_int(r.get("SMBIOSMemoryType")) or 0, ""),
            })
        arr = wmi.query("SELECT MemoryDevices FROM Win32_PhysicalMemoryArray", ["MemoryDevices"])
        slots = sum(to_int(a.get("MemoryDevices")) or 0 for a in arr)
        out["slots"] = slots or None
    return out


def _gpus() -> list[dict]:
    if not IS_WINDOWS:
        return []
    import winreg

    from corecontrol.monitoring.gpu import enumerate_adapters
    from corecontrol.system import wmi

    adapters = {a.name: a for a in enumerate_adapters() if not a.software}
    out = []
    rows = wmi.query(
        "SELECT Name, DriverVersion, DriverDate, AdapterCompatibility, Status, CurrentHorizontalResolution, "
        "CurrentVerticalResolution, CurrentRefreshRate, PNPDeviceID FROM Win32_VideoController",
        ["Name", "DriverVersion", "DriverDate", "AdapterCompatibility", "Status", "CurrentHorizontalResolution",
         "CurrentVerticalResolution", "CurrentRefreshRate", "PNPDeviceID"])
    reg_vram = _registry_vram()
    for r in rows:
        name = _clean(r.get("Name"))
        if not name or "basic render" in name.lower() or "basic display" in name.lower():
            continue
        a = adapters.get(name)
        vram = a.dedicated_vram if a else reg_vram.get(name)
        vendor = a.vendor if a else _vendor_from_name(name + " " + _clean(r.get("AdapterCompatibility")))
        res = None
        if r.get("CurrentHorizontalResolution"):
            res = f"{r['CurrentHorizontalResolution']} × {r['CurrentVerticalResolution']} @ {r.get('CurrentRefreshRate') or '?'} Hz"
        out.append({
            "name": name,
            "vendor": vendor,
            "driver_version": _clean(r.get("DriverVersion")),
            "driver_date": wmi.parse_datetime(r.get("DriverDate")),
            "vram": vram,
            "status": _clean(r.get("Status")),
            "resolution": res,
        })
    _ = winreg
    return out


def _registry_vram() -> dict[str, int]:
    import winreg

    out: dict[str, int] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, GPU_CLASS_KEY) as root:
            for i in range(32):
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        desc = winreg.QueryValueEx(k, "DriverDesc")[0]
                        try:
                            size = int(winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0])
                        except OSError:
                            raw = winreg.QueryValueEx(k, "HardwareInformation.MemorySize")[0]
                            size = int.from_bytes(raw[:8], "little") if isinstance(raw, bytes) else int(raw)
                        out[desc] = size
                except OSError:
                    continue
    except OSError:
        pass
    return out


def _vendor_from_name(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n or "rtx" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n or "advanced micro" in n or "ati " in n:
        return "amd"
    if "intel" in n:
        return "intel"
    return "other"


def _disks() -> list[dict]:
    if not IS_WINDOWS:
        out = []
        base = "/sys/block"
        try:
            for dev in sorted(os.listdir(base)):
                if dev.startswith(("loop", "ram", "zram", "dm-")):
                    continue
                model = ""
                try:
                    with open(f"{base}/{dev}/device/model", encoding="utf-8") as fh:
                        model = fh.read().strip()
                except OSError:
                    pass
                size = 0
                try:
                    with open(f"{base}/{dev}/size", encoding="utf-8") as fh:
                        size = int(fh.read().strip()) * 512
                except (OSError, ValueError):
                    pass
                rot = None
                try:
                    with open(f"{base}/{dev}/queue/rotational", encoding="utf-8") as fh:
                        rot = fh.read().strip() == "1"
                except OSError:
                    pass
                out.append({"number": dev, "model": model or dev, "size": size,
                            "media": "HDD" if rot else "SSD" if rot is False else "", "bus": "",
                            "health": "unknown", "operational": "", "reliability": None})
        except OSError:
            pass
        return out
    from corecontrol.system import wmi

    out = []
    try:
        rows = wmi.query(
            "SELECT DeviceId, FriendlyName, MediaType, BusType, Size, HealthStatus, OperationalStatus FROM MSFT_PhysicalDisk",
            ["DeviceId", "FriendlyName", "MediaType", "BusType", "Size", "HealthStatus", "OperationalStatus"],
            namespace="root\\Microsoft\\Windows\\Storage")
    except Exception as exc:
        log.info("MSFT_PhysicalDisk nicht verfügbar: %s", exc)
        rows = []
    reliability = _reliability()
    for r in rows:
        op = r.get("OperationalStatus")
        op_list = op if isinstance(op, list) else [op]
        dev_id = str(r.get("DeviceId") or "")
        out.append({
            "number": dev_id,
            "model": _clean(r.get("FriendlyName")),
            "media": MEDIA_TYPES.get(to_int(r.get("MediaType")) or 0, ""),
            "bus": BUS_TYPES.get(to_int(r.get("BusType")) or 0, ""),
            "size": to_int(r.get("Size")),
            "health": HEALTH.get(to_int(r.get("HealthStatus")) if r.get("HealthStatus") is not None else 5, "unknown"),
            "operational": ",".join(str(x) for x in op_list if x is not None),
            "reliability": reliability.get(dev_id) if reliability is not None else None,
            "reliability_needs_admin": reliability is None,
        })
    if not out:
        rows = wmi.query("SELECT Index, Model, Size, Status, InterfaceType FROM Win32_DiskDrive",
                         ["Index", "Model", "Size", "Status", "InterfaceType"])
        for r in rows:
            status = _clean(r.get("Status")).lower()
            out.append({"number": str(r.get("Index")), "model": _clean(r.get("Model")), "media": "",
                        "bus": _clean(r.get("InterfaceType")), "size": to_int(r.get("Size")),
                        "health": "healthy" if status == "ok" else "warning" if status in ("pred fail", "degraded") else "unknown",
                        "operational": status, "reliability": None})
    return out


def _reliability() -> dict[str, dict] | None:
    """SMART-ähnliche Werte (Temperatur, Verschleiß). Benötigt meist Adminrechte → sonst None."""
    from corecontrol.system import wmi

    try:
        rows = wmi.query(
            "SELECT DeviceId, Temperature, TemperatureMax, Wear, ReadErrorsUncorrected, WriteErrorsUncorrected, PowerOnHours "
            "FROM MSFT_StorageReliabilityCounter",
            ["DeviceId", "Temperature", "TemperatureMax", "Wear", "ReadErrorsUncorrected", "WriteErrorsUncorrected",
             "PowerOnHours"], namespace="root\\Microsoft\\Windows\\Storage")
    except Exception as exc:
        log.info("Zuverlässigkeitszähler nicht lesbar (oft Adminrechte nötig): %s", exc)
        return None
    if not rows:
        return None
    return {str(r.get("DeviceId")): {
        "temperature": to_int(r.get("Temperature")) or None,
        "temperature_max": to_int(r.get("TemperatureMax")) or None,
        "wear": to_int(r.get("Wear")),
        "read_errors": to_int(r.get("ReadErrorsUncorrected")),
        "write_errors": to_int(r.get("WriteErrorsUncorrected")),
        "power_on_hours": to_int(r.get("PowerOnHours")),
    } for r in rows}


def _volumes() -> list[dict]:
    out = []
    disk_of: dict[str, str] = {}
    if IS_WINDOWS:
        try:
            from corecontrol.system import wmi

            for r in wmi.query("SELECT DiskNumber, DriveLetter FROM MSFT_Partition", ["DiskNumber", "DriveLetter"],
                               namespace="root\\Microsoft\\Windows\\Storage"):
                letter = r.get("DriveLetter")
                if isinstance(letter, int):
                    letter = chr(letter) if letter else ""
                if letter and str(letter).strip("\x00"):
                    disk_of[f"{str(letter).upper()}:\\"] = str(r.get("DiskNumber"))
        except Exception as exc:
            log.info("MSFT_Partition: %s", exc)
    system_drive = (os.environ.get("SystemDrive", "C:") + "\\").upper() if IS_WINDOWS else "/"
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts or not p.fstype:
            continue
        if not IS_WINDOWS and (p.mountpoint.startswith(("/snap", "/boot/efi", "/proc", "/sys")) or p.fstype in ("squashfs", "overlay")):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except Exception:
            continue
        label = ""
        if IS_WINDOWS:
            label = _volume_label(p.mountpoint)
        out.append({
            "mount": p.mountpoint, "fs": p.fstype, "label": label,
            "total": int(u.total), "used": int(u.used), "free": int(u.free), "percent": float(u.percent),
            "disk": disk_of.get(p.mountpoint.upper()),
            "system": p.mountpoint.upper() == system_drive,
            "removable": "removable" in p.opts,
        })
    return out


def _volume_label(root: str) -> str:
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(261)
        if ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0):
            return buf.value
    except Exception:
        pass
    return ""


CM_ERRORS = {
    1: "not_configured", 3: "driver_corrupt", 10: "cannot_start", 12: "no_resources", 14: "restart_required",
    18: "reinstall", 19: "registry", 21: "removing", 22: "disabled", 24: "not_present", 28: "no_driver",
    29: "firmware_disabled", 31: "not_working", 32: "service_disabled", 37: "driver_failed", 39: "driver_missing",
    41: "driver_loaded_no_device", 43: "stopped_reported_problem", 45: "not_connected", 47: "safe_removal",
    48: "blocked", 52: "signature",
}


def _problem_devices() -> list[dict]:
    if not IS_WINDOWS:
        return []
    from corecontrol.system import wmi

    rows = wmi.query("SELECT Name, ConfigManagerErrorCode, PNPClass, DeviceID, Present FROM Win32_PnPEntity "
                     "WHERE ConfigManagerErrorCode <> 0",
                     ["Name", "ConfigManagerErrorCode", "PNPClass", "DeviceID", "Present"])
    out = []
    for r in rows:
        code = to_int(r.get("ConfigManagerErrorCode")) or 0
        if code in (24, 45):  # Gerät nicht angeschlossen – kein Problem
            continue
        out.append({"name": _clean(r.get("Name")) or _clean(r.get("DeviceID")), "code": code,
                    "class": _clean(r.get("PNPClass")), "reason": CM_ERRORS.get(code, "other")})
    return out


def _pending_reboot() -> dict:
    if not IS_WINDOWS:
        return {"pending": False, "reasons": []}
    import winreg

    reasons = []
    checks = [
        (r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired", "windows_update"),
        (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending", "component_servicing"),
    ]
    for path, reason in checks:
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path))
            reasons.append(reason)
        except OSError:
            pass
    return {"pending": bool(reasons), "reasons": reasons}


def collect_drivers() -> list[dict]:
    """Alle signierten Treiber (kann einige Sekunden dauern)."""
    if not IS_WINDOWS:
        return []
    from corecontrol.system import wmi

    rows = wmi.query("SELECT DeviceName, DeviceClass, DriverVersion, DriverDate, DriverProviderName, Manufacturer "
                     "FROM Win32_PnPSignedDriver",
                     ["DeviceName", "DeviceClass", "DriverVersion", "DriverDate", "DriverProviderName", "Manufacturer"])
    out = []
    for r in rows:
        name = _clean(r.get("DeviceName"))
        if not name:
            continue
        out.append({"device": name, "class": _clean(r.get("DeviceClass")), "version": _clean(r.get("DriverVersion")),
                    "date": wmi.parse_datetime(r.get("DriverDate")), "provider": _clean(r.get("DriverProviderName")),
                    "manufacturer": _clean(r.get("Manufacturer"))})
    out.sort(key=lambda d: (d["class"], d["device"]))
    return out


def age_days(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    return (datetime.now() - dt).days

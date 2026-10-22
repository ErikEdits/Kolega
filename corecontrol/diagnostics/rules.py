"""Diagnoseregeln.

Jede Regel bekommt die gesammelten Daten (DiagInput) und liefert Befunde.
Grundsätze:
- Nur Aussagen über tatsächlich gemessene Werte. Fehlen Werte, wird der Bereich
  als „nicht geprüft“ gemeldet – es wird nichts geraten.
- Grenzwerte sind konservativ und im Code nachvollziehbar.
- Vermutungen werden über `confidence` und `uncertainty` als solche gekennzeichnet.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from corecontrol.core.fmt import Bytes, Date, Dur, Ms, Num, Pct, Temp
from corecontrol.diagnostics.models import Finding
from corecontrol.i18n import T, has

# --------------------------------------------------------------------------------
# Eingabedaten


@dataclass
class LiveSummary:
    samples: int = 0
    seconds: float = 0.0
    cpu_avg: float | None = None
    cpu_max: float | None = None
    ram_percent: float | None = None
    ram_total: int | None = None
    ram_used: int | None = None
    cpu_temp: float | None = None
    cpu_temp_max: float | None = None
    gpu_name: str = ""
    gpu_temp: float | None = None
    gpu_temp_max: float | None = None
    gpu_util_avg: float | None = None
    disk_active_avg: float | None = None
    lhm_status: str = "off"


@dataclass
class ProcInfo:
    name: str
    pid: int
    cpu: float = 0.0      # % der Gesamt-CPU
    mem: int = 0          # Bytes


@dataclass
class DiagInput:
    settings: dict[str, Any]
    live: LiveSummary
    hw: dict[str, Any] | None = None
    events: Any = None
    net: Any = None
    top_cpu: list[ProcInfo] = field(default_factory=list)
    top_mem: list[ProcInfo] = field(default_factory=list)
    autostart_enabled: int | None = None
    temp_size: int | None = None
    power_scheme: str | None = None
    now: float = field(default_factory=time.time)
    skipped: list[tuple[str, T]] = field(default_factory=list)

    def s(self, key: str) -> Any:
        return self.settings.get(key)


# --------------------------------------------------------------------------------
# Hilfen


def make(fid: str, key: str, category: str, severity: str, *, confidence: str = "high",
         params: dict | None = None, extra_causes: list[T] | None = None, extra_recs: list[T] | None = None,
         extra_detected: list[T] | None = None, actions: list[tuple[str, str]] | None = None,
         evidence: dict | None = None) -> Finding:
    p = params or {}
    base = f"diag.{key}"
    causes = [T(f"{base}.causes", **p)] if has(f"{base}.causes") else []
    recs = [T(f"{base}.recs", **p)] if has(f"{base}.recs") else []
    detected = T(f"{base}.detected", **p)
    f = Finding(
        id=fid,
        category=category,
        severity=severity,
        title=T(f"{base}.title", **p),
        detected=detected,
        causes=causes + (extra_causes or []),
        recommendations=(extra_recs or []) + recs,
        risks=T(f"{base}.risks", **p) if has(f"{base}.risks") else None,
        confidence=confidence,
        uncertainty=T(f"{base}.uncertainty", **p) if has(f"{base}.uncertainty") else None,
        evidence=evidence or {},
        actions=actions or [],
    )
    if extra_detected:
        f.evidence["extra_detected"] = extra_detected
    return f


def proc_lines(procs: list[ProcInfo], kind: str) -> list[T]:
    out = []
    for p in procs[:3]:
        if kind == "cpu":
            out.append(T("diag.proc_cpu_line", name=p.name, value=Pct(p.cpu)))
        else:
            out.append(T("diag.proc_mem_line", name=p.name, value=Bytes(p.mem)))
    return out


# --------------------------------------------------------------------------------
# Temperaturen


def rule_cpu_temp(d: DiagInput) -> list[Finding]:
    lv = d.live
    if lv.cpu_temp is None:
        d.skipped.append(("thermal_cpu", T("diag.skip.cpu_temp")))
        return []
    warn, crit = d.s("thresholds.cpu_temp_warn"), d.s("thresholds.cpu_temp_crit")
    cur, mx = lv.cpu_temp, lv.cpu_temp_max or lv.cpu_temp
    params = dict(value=Temp(cur), max=Temp(mx), warn=Temp(warn), crit=Temp(crit), load=Pct(lv.cpu_avg or 0))
    ev = {"cpu_temp": cur, "cpu_temp_max": mx, "cpu_load_avg": lv.cpu_avg}
    if mx >= crit:
        return [make("cpu_temp", "cpu_temp_crit", "thermal", "critical", params=params, evidence=ev,
                     confidence="medium", actions=[("action.open_monitoring", "nav:monitoring")])]
    if mx >= warn:
        return [make("cpu_temp", "cpu_temp_warn", "thermal", "warning", params=params, evidence=ev,
                     confidence="medium", actions=[("action.open_monitoring", "nav:monitoring")])]
    if lv.cpu_avg is not None and lv.cpu_avg < 15 and cur >= 75:
        return [make("cpu_temp", "cpu_temp_idle", "thermal", "warning", params=params, evidence=ev, confidence="medium",
                     actions=[("action.open_processes", "nav:processes")])]
    return [make("cpu_temp", "cpu_temp_ok", "thermal", "ok", params=params, evidence=ev)]


def rule_gpu_temp(d: DiagInput) -> list[Finding]:
    lv = d.live
    if lv.gpu_temp is None:
        d.skipped.append(("thermal_gpu", T("diag.skip.gpu_temp")))
        return []
    warn, crit = d.s("thresholds.gpu_temp_warn"), d.s("thresholds.gpu_temp_crit")
    cur, mx = lv.gpu_temp, lv.gpu_temp_max or lv.gpu_temp
    params = dict(value=Temp(cur), max=Temp(mx), warn=Temp(warn), crit=Temp(crit), gpu=lv.gpu_name or "GPU",
                  load=Pct(lv.gpu_util_avg or 0))
    ev = {"gpu_temp": cur, "gpu_temp_max": mx}
    if mx >= crit:
        return [make("gpu_temp", "gpu_temp_crit", "thermal", "critical", params=params, evidence=ev, confidence="medium")]
    if mx >= warn:
        return [make("gpu_temp", "gpu_temp_warn", "thermal", "warning", params=params, evidence=ev, confidence="medium")]
    return [make("gpu_temp", "gpu_temp_ok", "thermal", "ok", params=params, evidence=ev)]


# --------------------------------------------------------------------------------
# Auslastung


def rule_cpu_load(d: DiagInput) -> list[Finding]:
    lv = d.live
    if lv.cpu_avg is None:
        d.skipped.append(("cpu_load", T("diag.skip.no_live")))
        return []
    lim = d.s("thresholds.cpu_load_warn")
    params = dict(avg=Pct(lv.cpu_avg), max=Pct(lv.cpu_max or lv.cpu_avg), limit=Pct(lim), seconds=Num(max(1, lv.seconds)))
    if lv.cpu_avg >= lim:
        return [make("cpu_load", "cpu_load_high", "cpu", "warning", params=params, confidence="high",
                     extra_detected=proc_lines(d.top_cpu, "cpu"), actions=[("action.open_processes", "nav:processes")],
                     evidence={"cpu_avg": lv.cpu_avg})]
    return [make("cpu_load", "cpu_load_ok", "cpu", "ok", params=params, evidence={"cpu_avg": lv.cpu_avg})]


def rule_ram(d: DiagInput) -> list[Finding]:
    lv = d.live
    out: list[Finding] = []
    if lv.ram_percent is None:
        d.skipped.append(("ram", T("diag.skip.no_live")))
        return out
    lim = d.s("thresholds.ram_warn")
    params = dict(pct=Pct(lv.ram_percent), used=Bytes(lv.ram_used), total=Bytes(lv.ram_total), limit=Pct(lim))
    if lv.ram_percent >= lim:
        out.append(make("ram", "ram_high", "memory", "warning", params=params, extra_detected=proc_lines(d.top_mem, "mem"),
                        actions=[("action.open_processes", "nav:processes")], evidence={"ram_percent": lv.ram_percent}))
    else:
        out.append(make("ram", "ram_ok", "memory", "ok", params=params, evidence={"ram_percent": lv.ram_percent}))
    if lv.ram_total and lv.ram_total < 7.5 * 1024**3:
        out.append(make("ram_small", "ram_small", "memory", "info", params=params, confidence="medium"))
    return out


# --------------------------------------------------------------------------------
# Speicherplatz und Laufwerke


def rule_disk_space(d: DiagInput) -> list[Finding]:
    hw = d.hw or {}
    vols = hw.get("volumes")
    if not vols:
        d.skipped.append(("disk_space", T("diag.skip.volumes")))
        return []
    out: list[Finding] = []
    wp, cp = d.s("thresholds.disk_free_warn_pct"), d.s("thresholds.disk_free_crit_pct")
    wg, cg = d.s("thresholds.disk_free_warn_gb"), d.s("thresholds.disk_free_crit_gb")
    ok_count = 0
    for v in vols:
        if v.get("removable") or (v.get("total") or 0) < 2 * 1024**3:
            continue
        free, total = v["free"], v["total"]
        pct = 100.0 * free / total if total else 0
        gb = free / 1024**3
        params = dict(drive=v["mount"], free=Bytes(free), total=Bytes(total), pct=Pct(pct))
        key = "disk_space_system" if v.get("system") else "disk_space"
        if pct < cp or gb < cg:
            out.append(make(f"disk_space:{v['mount']}", f"{key}_crit", "storage", "critical", params=params,
                            actions=[("action.open_storage", "nav:storage"), ("action.storage_sense", "url:ms-settings:storagesense")],
                            evidence={"free": free, "total": total}))
        elif pct < wp or gb < wg:
            out.append(make(f"disk_space:{v['mount']}", f"{key}_warn", "storage", "warning", params=params,
                            actions=[("action.open_storage", "nav:storage")], evidence={"free": free, "total": total}))
        else:
            ok_count += 1
    if not out and ok_count:
        out.append(make("disk_space", "disk_space_ok", "storage", "ok", params=dict(n=ok_count)))
    return out


def rule_disk_health(d: DiagInput) -> list[Finding]:
    hw = d.hw or {}
    disks = hw.get("disks")
    if disks is None:
        d.skipped.append(("disk_health", T("diag.skip.disks")))
        return []
    out: list[Finding] = []
    known = 0
    needs_admin = False
    for disk in disks:
        name = disk.get("model") or disk.get("number")
        health = disk.get("health", "unknown")
        params = dict(disk=name, media=disk.get("media") or "?")
        if health in ("unhealthy", "warning"):
            out.append(make(f"disk_health:{name}", f"disk_{health}", "storage", "critical", params=params,
                            actions=[("action.open_hardware", "nav:hardware")]))
        elif health == "healthy":
            known += 1
        rel = disk.get("reliability")
        if disk.get("reliability_needs_admin"):
            needs_admin = True
        if rel:
            wear = rel.get("wear")
            if wear is not None and wear >= 90:
                out.append(make(f"disk_wear:{name}", "disk_wear", "storage", "warning", params=dict(params, wear=Pct(wear))))
            errs = (rel.get("read_errors") or 0) + (rel.get("write_errors") or 0)
            if errs > 0:
                out.append(make(f"disk_errors:{name}", "disk_uncorrected", "storage", "warning", params=dict(params, n=errs)))
            t = rel.get("temperature")
            limit = 55 if disk.get("media") == "HDD" else 70
            if t and t >= limit:
                out.append(make(f"disk_temp:{name}", "disk_temp", "thermal", "warning",
                                params=dict(params, value=Temp(t), limit=Temp(limit)), confidence="medium"))
    if needs_admin:
        d.skipped.append(("disk_smart", T("diag.skip.smart_admin")))
    if not any(f.severity != "ok" for f in out) and known:
        out.append(make("disk_health", "disk_ok", "storage", "ok", params=dict(n=known)))
    elif not out and not known:
        d.skipped.append(("disk_health", T("diag.skip.disk_health_unknown")))
    # Systemlaufwerk auf HDD?
    sys_vol = next((v for v in hw.get("volumes") or [] if v.get("system")), None)
    if sys_vol and sys_vol.get("disk") is not None:
        disk = next((x for x in disks if str(x.get("number")) == str(sys_vol["disk"])), None)
        if disk and disk.get("media") == "HDD":
            out.append(make("system_hdd", "system_hdd", "storage", "info", params=dict(disk=disk.get("model", "")),
                            confidence="high"))
    return out


# --------------------------------------------------------------------------------
# Ereignisprotokolle

BUGCHECK_AREA_KEYS = {
    "driver": "diag.bsod.area.driver", "ram": "diag.bsod.area.ram", "ram_driver": "diag.bsod.area.ram_driver",
    "disk": "diag.bsod.area.disk", "hardware": "diag.bsod.area.hardware", "driver_power": "diag.bsod.area.driver_power",
    "driver_ram": "diag.bsod.area.ram_driver", "system_files": "diag.bsod.area.system_files", "cpu": "diag.bsod.area.cpu",
    "gpu": "diag.bsod.area.gpu", "driver_storage": "diag.bsod.area.driver_storage",
}


def rule_events(d: DiagInput) -> list[Finding]:
    from corecontrol.diagnostics.eventlog import BUGCHECKS

    ev = d.events
    if ev is None or not getattr(ev, "available", False):
        d.skipped.append(("events", T("diag.skip.events")))
        return []
    days = ev.days
    out: list[Finding] = []
    act_events = [("action.open_events", "nav:events"), ("action.reliability", "tool:reliability")]

    def g(cat):
        return ev.get(cat)

    bs = g("bluescreen")
    kp = g("unexpected_shutdown")
    # Bluescreens (auch aus Kernel-Power-41 mit Bugcheck-Code)
    codes = dict(bs.details) if bs else {}
    if kp:
        for code, n in kp.details.items():
            codes.setdefault(code, n)
    if bs or codes:
        lines = []
        areas = set()
        for code_s, n in sorted(codes.items(), key=lambda x: -x[1]):
            try:
                code = int(code_s, 16)
            except ValueError:
                continue
            name, area = BUGCHECKS.get(code, ("", ""))
            if area:
                areas.add(area)
            lines.append(T("diag.bsod.code_line", code=code_s, name=name or "?", n=n,
                           area=T(BUGCHECK_AREA_KEYS[area]) if area in BUGCHECK_AREA_KEYS else T("diag.bsod.area.unknown")))
        extra_recs = []
        if areas & {"ram", "ram_driver"}:
            extra_recs.append(T("diag.bsod.rec_ram"))
        if areas & {"disk", "driver_storage"}:
            extra_recs.append(T("diag.bsod.rec_disk"))
        if "gpu" in areas:
            extra_recs.append(T("diag.bsod.rec_gpu"))
        if areas & {"hardware", "cpu"}:
            extra_recs.append(T("diag.bsod.rec_hardware"))
        if "system_files" in areas:
            extra_recs.append(T("diag.bsod.rec_sfc"))
        n = bs.count if bs else sum(codes.values())
        out.append(make("events:bluescreen", "bsod", "events", "critical",
                        params=dict(n=n, days=days, last=Date(bs.last if bs else kp.last)),
                        extra_detected=lines, extra_recs=extra_recs, confidence="high", actions=act_events,
                        evidence={"count": n, "codes": codes}))
    if kp:
        sev = "critical" if kp.count >= 5 else "warning"
        out.append(make("events:kernel_power", "kernel_power", "events", sev,
                        params=dict(n=kp.count, days=days, last=Date(kp.last)), confidence="medium", actions=act_events,
                        evidence={"count": kp.count}))
    for cat, key, sev in (("whea_fatal", "whea_fatal", "critical"), ("whea_corrected", "whea_corrected", "warning"),
                          ("whea_other", "whea_corrected", "warning")):
        grp = g(cat)
        if grp:
            out.append(make(f"events:{cat}", key, "events", sev, params=dict(n=grp.count, days=days, last=Date(grp.last)),
                            confidence="medium", actions=act_events, evidence={"count": grp.count}))
    disk_crit = sum(x.count for x in (g("disk_bad_block"), g("disk_controller"), g("ntfs_corruption")) if x)
    if disk_crit:
        out.append(make("events:disk_errors", "disk_events_crit", "events", "critical",
                        params=dict(n=disk_crit, days=days), actions=act_events + [("action.open_hardware", "nav:hardware")],
                        evidence={"count": disk_crit}))
    disk_warn = sum(x.count for x in (g("disk_io_retry"), g("storage_reset"), g("ntfs_check")) if x)
    if disk_warn:
        out.append(make("events:disk_warn", "disk_events_warn", "events", "warning", params=dict(n=disk_warn, days=days),
                        confidence="medium", actions=act_events, evidence={"count": disk_warn}))
    gpu_n = sum(x.count for x in (g("gpu_tdr"), g("gpu_driver_nvidia"), g("gpu_driver_amd")) if x)
    if gpu_n:
        out.append(make("events:gpu", "gpu_events", "events", "warning", params=dict(n=gpu_n, days=days),
                        confidence="medium", actions=act_events, evidence={"count": gpu_n}))
    thr = g("cpu_throttled")
    if thr and thr.count >= 3:
        out.append(make("events:throttle", "cpu_throttle_events", "events", "info", params=dict(n=thr.count, days=days),
                        confidence="low", actions=act_events))
    low = g("low_memory")
    if low:
        out.append(make("events:low_memory", "low_memory_events", "events", "warning", params=dict(n=low.count, days=days),
                        actions=[("action.open_processes", "nav:processes")]))
    upd = g("update_failed")
    if upd:
        out.append(make("events:update", "update_failed", "events", "warning", params=dict(n=upd.count, days=days),
                        confidence="medium", actions=[("action.windows_update", "url:ms-settings:windowsupdate")]))
    crashes = g("app_crash")
    if crashes:
        frequent = [(app, n) for app, n in crashes.details.most_common(5) if n >= 3]
        if frequent:
            lines = [T("diag.app_line", app=a, n=n) for a, n in frequent]
            out.append(make("events:app_crash", "app_crashes", "software", "info",
                            params=dict(n=sum(n for _, n in frequent), days=days, apps=len(frequent)),
                            extra_detected=lines, actions=act_events))
    svc = g("service_failure")
    if svc:
        frequent = [(s, n) for s, n in svc.details.most_common(5) if n >= 3]
        if frequent:
            lines = [T("diag.service_line", service=s, n=n) for s, n in frequent]
            out.append(make("events:services", "service_failures", "software", "info",
                            params=dict(n=sum(n for _, n in frequent), days=days), extra_detected=lines,
                            confidence="low", actions=act_events))
    serious = [f for f in out if f.severity in ("critical", "warning")]
    if not serious:
        out.append(make("events", "events_ok", "events", "ok", params=dict(days=days, total=ev.total)))
    return out


# --------------------------------------------------------------------------------
# Treiber und Geräte

VENDOR_DRIVER_URLS = {
    "nvidia": "https://www.nvidia.com/drivers",
    "amd": "https://www.amd.com/support/download/drivers.html",
    "intel": "https://www.intel.com/content/www/us/en/support/detect.html",
}


def rule_devices(d: DiagInput) -> list[Finding]:
    hw = d.hw or {}
    devs = hw.get("problem_devices")
    if devs is None:
        d.skipped.append(("devices", T("diag.skip.devices")))
        return []
    out: list[Finding] = []
    disabled = [x for x in devs if x.get("code") == 22]
    broken = [x for x in devs if x.get("code") != 22]
    if broken:
        lines = [T("diag.device_line", name=x["name"], code=x["code"], reason=T(f"cm.{x.get('reason', 'other')}"))
                 for x in broken[:8]]
        out.append(make("devices", "devices_problem", "drivers", "warning", params=dict(n=len(broken)),
                        extra_detected=lines, actions=[("action.device_manager", "tool:devmgmt")],
                        evidence={"devices": broken}))
    if disabled:
        lines = [T("diag.device_line", name=x["name"], code=22, reason=T("cm.disabled")) for x in disabled[:8]]
        out.append(make("devices_disabled", "devices_disabled", "drivers", "info", params=dict(n=len(disabled)),
                        extra_detected=lines, actions=[("action.device_manager", "tool:devmgmt")]))
    if not out:
        out.append(make("devices", "devices_ok", "drivers", "ok"))
    return out


def rule_gpu_driver(d: DiagInput) -> list[Finding]:
    hw = d.hw or {}
    gpus = hw.get("gpus")
    if gpus is None:
        return []
    out: list[Finding] = []
    if not gpus and hw.get("platform") == "windows":
        out.append(make("gpu_driver_missing", "gpu_basic_driver", "drivers", "warning",
                        actions=[("action.device_manager", "tool:devmgmt")]))
        return out
    for gpu in gpus:
        dt = gpu.get("driver_date")
        if not isinstance(dt, datetime):
            continue
        age = (datetime.fromtimestamp(d.now) - dt).days
        vendor = gpu.get("vendor", "")
        url = VENDOR_DRIVER_URLS.get(vendor)
        params = dict(gpu=gpu.get("name", ""), version=gpu.get("driver_version", ""), date=Date(dt), days=age)
        acts = [("action.driver_page", f"url:{url}")] if url else []
        if age > 365:
            out.append(make(f"gpu_driver:{gpu.get('name')}", "gpu_driver_old", "drivers", "info", params=params,
                            confidence="low", actions=acts))
        else:
            out.append(make(f"gpu_driver:{gpu.get('name')}", "gpu_driver_ok", "drivers", "ok", params=params, actions=acts))
    return out


# --------------------------------------------------------------------------------
# Windows

# Ende des Supports für Home/Pro laut Microsoft-Lebenszyklus (Stand: Oktober 2026).
# Enterprise/Education haben teils längeren Support.
WINDOWS_EOS = {
    19045: date(2025, 10, 14),  # Windows 10 22H2 (letzte Win-10-Version)
    22000: date(2023, 10, 10),  # Windows 11 21H2
    22621: date(2024, 10, 8),   # Windows 11 22H2
    22631: date(2025, 11, 11),  # Windows 11 23H2
    26100: date(2026, 10, 13),  # Windows 11 24H2
}


def rule_windows(d: DiagInput) -> list[Finding]:
    hw = d.hw or {}
    os_ = hw.get("os")
    if not os_ or hw.get("platform") != "windows":
        return []
    out: list[Finding] = []
    build = os_.get("build") or 0
    today = datetime.fromtimestamp(d.now).date()
    params = dict(name=os_.get("name", "Windows"), version=os_.get("display_version", ""), build=build)
    acts = [("action.windows_update", "url:ms-settings:windowsupdate")]
    if os_.get("family") == "win10" or (build and build < 22000):
        out.append(make("windows_version", "win10_eos", "system", "warning", params=params, confidence="high", actions=acts))
    else:
        eos = WINDOWS_EOS.get(build)
        if eos and today > eos:
            out.append(make("windows_version", "win11_eos", "system", "warning", params=dict(params, date=Date(datetime.combine(eos, datetime.min.time()))),
                            confidence="medium", actions=acts))
        else:
            out.append(make("windows_version", "windows_ok", "system", "ok", params=params))
    pr = hw.get("pending_reboot") or {}
    if pr.get("pending"):
        out.append(make("pending_reboot", "pending_reboot", "system", "info", actions=acts))
    uptime = os_.get("uptime_s")
    if uptime and uptime > 14 * 86400:
        out.append(make("uptime", "uptime_long", "system", "info", params=dict(uptime=Dur(uptime)), confidence="medium"))
    return out


def rule_autostart(d: DiagInput) -> list[Finding]:
    n = d.autostart_enabled
    if n is None:
        return []
    if n > 12:
        return [make("autostart", "autostart_many", "software", "info", params=dict(n=n), confidence="medium",
                     actions=[("action.open_autostart", "nav:autostart")])]
    return [make("autostart", "autostart_ok", "software", "ok", params=dict(n=n))]


def rule_temp_files(d: DiagInput) -> list[Finding]:
    if d.temp_size is None:
        return []
    if d.temp_size > 2 * 1024**3:
        return [make("temp_files", "temp_large", "storage", "info", params=dict(size=Bytes(d.temp_size)),
                     actions=[("action.open_storage", "nav:storage")])]
    return []


def rule_power(d: DiagInput) -> list[Finding]:
    hw = d.hw or {}
    if d.power_scheme == "a1841308-3541-4fab-bc81-f71556f20b4a" and not (hw.get("board") or {}).get("is_laptop"):
        return [make("power_saver", "power_saver", "system", "info", confidence="medium",
                     actions=[("action.power_options", "tool:powercfg")])]
    return []


# --------------------------------------------------------------------------------
# Netzwerk


def rule_network(d: DiagInput) -> list[Finding]:
    net = d.net
    if net is None:
        d.skipped.append(("network", T("diag.skip.network")))
        return []
    out: list[Finding] = []
    acts = [("action.open_network", "nav:network")]
    if not net.any_adapter_up:
        return [make("net", "net_no_adapter", "network", "critical", actions=acts + [("action.network_settings", "url:ms-settings:network")])]
    gw = net.gateway_ping
    inet = net.best_internet
    wifi = net.wifi
    gw_ok = gw.reachable if gw else None
    if gw is not None and not gw.reachable and not net.internet_ok:
        out.append(make("net", "net_gateway_down", "network", "critical", params=dict(gw=net.gateway), actions=acts))
        return out
    if net.http is not None and net.http.captive_portal:
        out.append(make("net_captive", "net_captive", "network", "warning", actions=acts))
    if not net.internet_ok:
        out.append(make("net", "net_no_internet", "network", "critical", params=dict(gw=net.gateway or "?"),
                        confidence="medium" if gw_ok else "low", actions=acts))
        return out
    pings_ok = any(p.reachable for p in net.internet_pings)
    if net.dns_ok is False:
        out.append(make("net_dns", "net_dns_fail", "network", "critical", actions=acts))
    else:
        ok_dns = [x.ms for x in net.dns if x.ok and x.ms is not None]
        if ok_dns and min(ok_dns) > 300:
            out.append(make("net_dns", "net_dns_slow", "network", "info", params=dict(ms=Ms(min(ok_dns))), confidence="medium"))
    if gw is not None and gw.reachable and (gw.loss_pct or 0) > 2:
        out.append(make("net_loss_local", "net_loss_local", "network", "warning",
                        params=dict(loss=Pct(gw.loss_pct), gw=net.gateway, wifi=T("diag.net_wifi_hint") if wifi and wifi.available else ""),
                        confidence="medium", actions=acts))
    elif pings_ok and inet is not None and (inet.loss_pct or 0) > 2:
        out.append(make("net_loss_inet", "net_loss_inet", "network", "warning",
                        params=dict(loss=Pct(inet.loss_pct), host=inet.host), confidence="medium", actions=acts))
    if gw is not None and gw.avg is not None:
        lim = 50 if (wifi and wifi.available) else 15
        if gw.avg > lim:
            out.append(make("net_latency_local", "net_latency_local", "network", "info",
                            params=dict(ms=Ms(gw.avg), limit=Ms(lim)), confidence="medium", actions=acts))
    if pings_ok and inet is not None and inet.avg is not None and inet.avg > 100:
        out.append(make("net_latency", "net_latency_inet", "network", "info", params=dict(ms=Ms(inet.avg), host=inet.host),
                        confidence="medium"))
    if pings_ok and inet is not None and inet.jitter is not None and inet.jitter > 30:
        out.append(make("net_jitter", "net_jitter", "network", "info", params=dict(ms=Ms(inet.jitter)), confidence="medium"))
    if not pings_ok:
        out.append(make("net_ping_blocked", "net_ping_blocked", "network", "info", confidence="medium"))
    if wifi is not None and wifi.available and wifi.signal_pct is not None:
        if wifi.signal_pct < 40:
            out.append(make("wifi_signal", "wifi_weak", "network", "warning", params=dict(pct=Pct(wifi.signal_pct), ssid=wifi.ssid),
                            confidence="high", actions=acts))
        elif wifi.signal_pct < 60:
            out.append(make("wifi_signal", "wifi_medium", "network", "info", params=dict(pct=Pct(wifi.signal_pct), ssid=wifi.ssid)))
    if not any(f.severity in ("critical", "warning") for f in out):
        out.append(make("net", "net_ok", "network", "ok",
                        params=dict(ms=Ms(inet.avg) if inet and inet.avg is not None else "–",
                                    loss=Pct(inet.loss_pct) if inet and inet.loss_pct is not None else "–")))
    return out


ALL_RULES: list[Callable[[DiagInput], list[Finding]]] = [
    rule_cpu_temp, rule_gpu_temp, rule_cpu_load, rule_ram, rule_disk_space, rule_disk_health, rule_events,
    rule_devices, rule_gpu_driver, rule_windows, rule_autostart, rule_temp_files, rule_power, rule_network,
]


def temp_dir_size(limit_files: int = 200_000, ctx=None) -> int | None:
    base = os.environ.get("TEMP") or os.environ.get("TMP")
    if not base or not os.path.isdir(base):
        return None
    total = 0
    count = 0
    stack = [base]
    while stack and count < limit_files:
        if ctx is not None and ctx.cancelled:
            break
        p = stack.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    count += 1
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total

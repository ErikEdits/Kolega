"""Ablauf der Systemdiagnose: Daten sammeln → Regeln anwenden → Ergebnis.

Alles hier ist nur lesend. Es wird nichts verändert, gelöscht oder repariert.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import psutil

from corecontrol import __version__
from corecontrol.core.logging_setup import record_error
from corecontrol.core.platform import IS_WINDOWS, decode_console, run_hidden
from corecontrol.diagnostics.models import DiagnosisResult, Finding
from corecontrol.diagnostics.rules import ALL_RULES, DiagInput, LiveSummary, ProcInfo, temp_dir_size
from corecontrol.i18n import T

log = logging.getLogger(__name__)

STEPS = ("live", "hardware", "events", "network", "extras", "rules")


def summarize_live(samples: list) -> LiveSummary:
    ls = LiveSummary(samples=len(samples))
    if not samples:
        return ls
    ls.seconds = max(1.0, samples[-1].ts - samples[0].ts)
    cpu = [s.cpu_percent for s in samples if s.cpu_percent is not None]
    if cpu:
        ls.cpu_avg, ls.cpu_max = sum(cpu) / len(cpu), max(cpu)
    last = samples[-1]
    ls.ram_percent, ls.ram_total, ls.ram_used = last.ram_percent, last.ram_total, last.ram_used
    temps = [s.cpu_temp for s in samples if s.cpu_temp is not None]
    if temps:
        ls.cpu_temp, ls.cpu_temp_max = temps[-1], max(temps)
    gtemps, gutil = [], []
    for s in samples:
        g = s.primary_gpu
        if g is not None:
            ls.gpu_name = g.name
            if g.temp is not None:
                gtemps.append(g.temp)
            if g.util is not None:
                gutil.append(g.util)
    if gtemps:
        ls.gpu_temp, ls.gpu_temp_max = gtemps[-1], max(gtemps)
    if gutil:
        ls.gpu_util_avg = sum(gutil) / len(gutil)
    da = [s.disk_active_pct for s in samples if s.disk_active_pct is not None]
    if da:
        ls.disk_active_avg = sum(da) / len(da)
    ls.lhm_status = last.lhm_status
    return ls


def quick_live() -> LiveSummary:
    """Falls (noch) keine Live-Daten vorliegen: kurze eigene Messung."""
    ls = LiveSummary()
    cpu = psutil.cpu_percent(interval=1.5)
    vm = psutil.virtual_memory()
    ls.samples, ls.seconds = 1, 1.5
    ls.cpu_avg = ls.cpu_max = float(cpu)
    ls.ram_percent, ls.ram_total, ls.ram_used = float(vm.percent), int(vm.total), int(vm.total - vm.available)
    return ls


def top_processes(wait: float = 1.0) -> tuple[list[ProcInfo], list[ProcInfo]]:
    procs = []
    ncpu = psutil.cpu_count() or 1
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except (psutil.Error, OSError):
            continue
    time.sleep(wait)
    infos = []
    for p in procs:
        try:
            if p.pid == 0:
                continue
            name = p.info.get("name") or str(p.pid)
            infos.append(ProcInfo(name, p.pid, p.cpu_percent(None) / ncpu, p.memory_info().rss))
        except (psutil.Error, OSError):
            continue
    # Gleichnamige Prozesse zusammenfassen (z. B. viele Browser-Prozesse)
    merged: dict[str, ProcInfo] = {}
    for i in infos:
        m = merged.get(i.name)
        if m is None:
            merged[i.name] = ProcInfo(i.name, i.pid, i.cpu, i.mem)
        else:
            m.cpu += i.cpu
            m.mem += i.mem
    vals = list(merged.values())
    return (sorted(vals, key=lambda x: -x.cpu)[:5], sorted(vals, key=lambda x: -x.mem)[:5])


def active_power_scheme() -> str | None:
    if not IS_WINDOWS:
        return None
    res = run_hidden(["powercfg", "/getactivescheme"], timeout=5)
    if res is None or res.returncode != 0:
        return None
    import re

    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", decode_console(res.stdout), re.I)
    return m.group(1).lower() if m else None


def run_full_diagnosis(settings: dict[str, Any], live_store=None, include_network: bool = True,
                       hardware: dict | None = None, ctx=None) -> DiagnosisResult:
    started = time.time()
    skipped: list[tuple[str, T]] = []

    def progress(step: str):
        if ctx is not None:
            ctx.progress(step)

    # 1. Live-Werte (letzte 60 Sekunden aus der laufenden Messung)
    progress("live")
    samples = live_store.window(60) if live_store is not None else []
    live = summarize_live(samples) if len(samples) >= 3 else quick_live()
    if len(samples) >= 3 and samples[-1].lhm_status != "ok":
        live.lhm_status = samples[-1].lhm_status
    try:
        top_cpu, top_mem = top_processes()
    except Exception as exc:
        record_error("diagnosis:processes", exc)
        top_cpu, top_mem = [], []

    # 2. Hardware (einmal geladen, Speicherplatz immer aktuell)
    progress("hardware")
    from corecontrol.monitoring import hardware as hwmod

    try:
        if hardware is None:
            hw = hwmod.collect_hardware()
        else:
            hw = dict(hardware)
            for name, fn in (("volumes", hwmod._volumes), ("problem_devices", hwmod._problem_devices),
                             ("pending_reboot", hwmod._pending_reboot), ("os", hwmod._os)):
                hwmod._run(hw, name, fn)
    except Exception as exc:
        record_error("diagnosis:hardware", exc)
        hw = None

    # 3. Ereignisprotokolle
    progress("events")
    events = None
    try:
        from corecontrol.diagnostics.eventlog import read_events

        events = read_events(days=int(settings.get("events.days", 30)), ctx=ctx)
    except Exception as exc:
        record_error("diagnosis:events", exc)

    # 4. Netzwerk
    net = None
    if include_network:
        progress("network")
        try:
            from corecontrol.network.tests import run_network_test

            net = run_network_test(settings.get("network.ping_targets") or ["1.1.1.1"],
                                   settings.get("network.dns_domains") or ["www.microsoft.com"], ping_count=8, ctx=ctx)
        except Exception as exc:
            record_error("diagnosis:network", exc)
    else:
        skipped.append(("network", T("diag.skip.network_off")))

    # 5. Weitere Prüfungen
    progress("extras")
    autostart_enabled = None
    try:
        from corecontrol.system.autostart import list_items

        if IS_WINDOWS:
            autostart_enabled = sum(1 for i in list_items() if i.enabled)
    except Exception as exc:
        record_error("diagnosis:autostart", exc)
    temp_size = None
    try:
        temp_size = temp_dir_size(ctx=ctx)
    except Exception as exc:
        record_error("diagnosis:temp", exc)
    power = None
    try:
        power = active_power_scheme()
    except Exception as exc:
        record_error("diagnosis:power", exc)

    # 6. Regeln
    progress("rules")
    d = DiagInput(settings=settings, live=live, hw=hw, events=events, net=net, top_cpu=top_cpu, top_mem=top_mem,
                  autostart_enabled=autostart_enabled, temp_size=temp_size, power_scheme=power, skipped=skipped)
    findings = apply_rules(d)
    return DiagnosisResult(started_at=started, finished_at=time.time(), findings=findings, hardware=hw, events=events,
                           network=net, live=live.__dict__, skipped=d.skipped, app_version=__version__)


def apply_rules(d: DiagInput) -> list[Finding]:
    findings: list[Finding] = []
    for rule in ALL_RULES:
        try:
            findings.extend(rule(d))
        except Exception as exc:
            record_error(f"rule:{rule.__name__}", exc)
            d.skipped.append((rule.__name__.replace("rule_", ""), T("diag.skip.rule_error")))
    return findings

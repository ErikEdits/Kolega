"""Selbsttest der Windows-Schnittstellen (läuft in der automatischen Prüfung auf GitHub).

Ruft alle Messquellen einmal auf und gibt die Ergebnisse lesbar aus. So lässt sich
nachvollziehen, welche Werte auf einem echten Windows tatsächlich ankommen.
Exit-Code 1, wenn ein Bereich mit einer unerwarteten Ausnahme abbricht.
"""

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corecontrol import i18n  # noqa: E402

i18n.set_language("de")
failures: list[str] = []


def section(name):
    def deco(fn):
        print(f"\n===== {name} =====", flush=True)
        t0 = time.perf_counter()
        try:
            fn()
            print(f"--> OK ({(time.perf_counter() - t0) * 1000:.0f} ms)")
        except Exception:
            failures.append(name)
            traceback.print_exc()
            print("--> FEHLER")
        return fn
    return deco


@section("Hardware")
def _hw():
    from corecontrol.monitoring.hardware import collect_hardware

    hw = collect_hardware()
    for k in ("os", "cpu", "board", "memory", "gpus", "disks", "volumes", "problem_devices", "pending_reboot"):
        print(f"{k}: {hw.get(k)!r}"[:600])
    print("errors:", hw.get("errors"))


@section("Live-Messung (3 Proben)")
def _live():
    from corecontrol.monitoring.collector import Collector

    c = Collector(lhm_enabled=True)
    for _ in range(3):
        s = c.sample()
        time.sleep(1)
    print(f"cpu={s.cpu_percent} freq={s.cpu_freq_mhz} ram={s.ram_percent} disk_active={s.disk_active_pct} "
          f"net_down={s.net_down_bps} procs={s.process_count} lhm={s.lhm_status}")
    for g in s.gpus:
        print("  gpu:", g)
    c.close()


@section("GPU-Adapter (DXGI)")
def _dxgi():
    from corecontrol.monitoring.gpu import enumerate_adapters

    for a in enumerate_adapters():
        print("  ", a)


@section("Ereignisprotokolle (7 Tage)")
def _events():
    from corecontrol.diagnostics.eventlog import read_events

    s = read_events(7)
    print(f"available={s.available} total={s.total} errors={s.read_errors}")
    for g in s.groups[:15]:
        ex = g.examples[0]
        print(f"  {g.severity:8} {g.category:22} {g.count:4}x  {g.provider}/{g.event_id}  msg={ex.message[:90]!r}")


@section("Netzwerk")
def _net():
    from corecontrol.network.tests import run_network_test

    r = run_network_test(["1.1.1.1", "8.8.8.8"], ["www.microsoft.com"], ping_count=4)
    print("gateway:", r.gateway, r.gateway_ping)
    for p in r.internet_pings:
        print(f"  ping {p.host}: {p.received}/{p.sent} avg={p.avg} err={p.error}")
    print("  dns:", r.dns)
    print("  http:", r.http)
    print("  wifi:", r.wifi)
    for a in r.adapters[:6]:
        print("  adapter:", a.name, a.kind, a.up, a.speed_mbps, a.gateway, a.dns)


@section("Autostart")
def _autostart():
    from corecontrol.system.autostart import list_items

    for i in list_items()[:20]:
        print(f"  {i.name}: enabled={i.enabled} loc={i.location} admin={i.needs_admin} target={i.target}")


@section("Installierte Programme")
def _programs():
    from corecontrol.system.programs import list_programs

    progs = list_programs()
    print("anzahl:", len(progs))
    for p in progs[:10]:
        print("  ", p.name, p.version, p.publisher, p.size)


@section("Prozesse")
def _procs():
    from corecontrol.system.processes import ProcessMonitor

    pm = ProcessMonitor()
    pm.refresh()
    time.sleep(1)
    rows = pm.refresh()
    print("anzahl:", len(rows))
    for r in sorted(rows, key=lambda r: -r.mem)[:5]:
        print(f"  {r.name} pid={r.pid} mem={r.mem} protected={r.protected}")


@section("Speicher-Bereinigung (nur Analyse, löscht nichts)")
def _cleanup():
    from corecontrol.storage.cleanup import scan_categories

    for c in scan_categories(min_age_days=2):
        print(f"  {c.id}: {len(c.files)} Dateien, {c.total} Bytes, zugriff_verweigert={c.denied}")


@section("Steam/Epic-Spiele")
def _games():
    from corecontrol.gaming.library import detect_games

    for g in detect_games()[:10]:
        print("  ", g)


@section("Komplette Diagnose (mit Netzwerk)")
def _diag():
    from corecontrol.core.settings import defaults
    from corecontrol.diagnostics.engine import run_full_diagnosis

    r = run_full_diagnosis(defaults(), None, include_network=True)
    for f in r.sorted():
        print(f"  [{f.severity}] {f.title} | {f.detected}")
    for area, reason in r.skipped:
        print(f"  (nicht geprüft) {area}: {reason}")
    from corecontrol.reports.report import build_report, make_redactor

    rep = build_report(r, None, None, "Selbsttest", make_redactor(True, r, defaults()))
    print("  Bericht TXT:", len(rep.text()), "Zeichen, HTML:", len(rep.html()), "Zeichen")


print("\n\nZUSAMMENFASSUNG: Fehler in:", failures or "keinem Bereich")
sys.exit(1 if failures else 0)

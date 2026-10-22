"""Diagnoseregeln: richtige Befunde für typische Situationen, keine Befunde ohne Messwerte."""

import time
from collections import Counter
from datetime import datetime, timedelta

from corecontrol.core.settings import defaults
from corecontrol.diagnostics import rules
from corecontrol.diagnostics.engine import apply_rules, summarize_live
from corecontrol.diagnostics.eventlog import EventGroup, EventRecord, EventSummary
from corecontrol.diagnostics.rules import DiagInput, LiveSummary, ProcInfo
from corecontrol.monitoring.models import GpuSample, Sample
from corecontrol.network.tests import DnsResult, HttpResult, NetworkResult, PingStats, WifiInfo


def mk(live=None, **kw) -> DiagInput:
    return DiagInput(settings=defaults(), live=live or LiveSummary(samples=60, seconds=60, cpu_avg=10, cpu_max=20,
                                                                    ram_percent=40, ram_total=16 * 1024**3,
                                                                    ram_used=6 * 1024**3), **kw)


def ids(findings):
    return {(f.id.split(":")[0], f.severity) for f in findings}


def test_missing_temperatures_are_reported_as_not_checked_not_as_problem():
    d = mk()
    out = rules.rule_cpu_temp(d) + rules.rule_gpu_temp(d)
    assert out == []
    areas = [a for a, _ in d.skipped]
    assert "thermal_cpu" in areas and "thermal_gpu" in areas


def test_cpu_temperature_levels():
    lv = LiveSummary(samples=60, cpu_avg=80, cpu_max=100, cpu_temp=97, cpu_temp_max=98)
    assert rules.rule_cpu_temp(mk(lv))[0].severity == "critical"
    lv = LiveSummary(samples=60, cpu_avg=80, cpu_temp=86, cpu_temp_max=87)
    f = rules.rule_cpu_temp(mk(lv))[0]
    assert f.severity == "warning" and f.confidence == "medium" and f.uncertainty is not None
    lv = LiveSummary(samples=60, cpu_avg=5, cpu_temp=78, cpu_temp_max=79)
    assert rules.rule_cpu_temp(mk(lv))[0].id == "cpu_temp" and "idle" in rules.rule_cpu_temp(mk(lv))[0].title.key
    lv = LiveSummary(samples=60, cpu_avg=30, cpu_temp=55, cpu_temp_max=60)
    assert rules.rule_cpu_temp(mk(lv))[0].severity == "ok"


def test_cpu_load_lists_top_processes():
    lv = LiveSummary(samples=60, seconds=60, cpu_avg=95, cpu_max=100)
    d = mk(lv, top_cpu=[ProcInfo("miner.exe", 1, 80.0, 0), ProcInfo("chrome.exe", 2, 10.0, 0)])
    f = rules.rule_cpu_load(d)[0]
    assert f.severity == "warning"
    lines = [str(x) for x in f.evidence["extra_detected"]]
    assert lines[0].startswith("miner.exe")


def test_disk_space_rules():
    gb = 1024**3
    hw = {"volumes": [
        {"mount": "C:\\", "total": 500 * gb, "free": 3 * gb, "percent": 99.4, "system": True},
        {"mount": "D:\\", "total": 1000 * gb, "free": 80 * gb, "percent": 92, "system": False},
        {"mount": "E:\\", "total": 1000 * gb, "free": 600 * gb, "percent": 40, "system": False},
        {"mount": "F:\\", "total": 32 * gb, "free": 1 * gb, "percent": 97, "removable": True},
    ]}
    out = rules.rule_disk_space(mk(hw=hw))
    sev = {f.id: f.severity for f in out}
    assert sev["disk_space:C:\\"] == "critical"
    assert sev["disk_space:D:\\"] == "warning"
    assert "disk_space:E:\\" not in sev and "disk_space:F:\\" not in sev


def test_disk_health():
    hw = {"disks": [{"number": "0", "model": "Samsung SSD", "media": "SSD", "health": "warning",
                     "reliability": {"wear": 95, "read_errors": 2, "write_errors": 0, "temperature": 72}}],
          "volumes": [{"mount": "C:\\", "system": True, "disk": "0", "total": 1, "free": 1}]}
    out = rules.rule_disk_health(mk(hw=hw))
    keys = {f.title.key for f in out}
    assert "diag.disk_warning.title" in keys
    assert "diag.disk_wear.title" in keys
    assert "diag.disk_uncorrected.title" in keys
    assert "diag.disk_temp.title" in keys


def test_system_on_hdd_note():
    hw = {"disks": [{"number": "1", "model": "WD Blue", "media": "HDD", "health": "healthy"}],
          "volumes": [{"mount": "C:\\", "system": True, "disk": "1", "total": 1, "free": 1}]}
    out = rules.rule_disk_health(mk(hw=hw))
    assert ("system_hdd", "info") in ids(out)
    assert ("disk_health", "ok") in ids(out)


def _ev(groups, days=30):
    return EventSummary(days=days, groups=groups, total=sum(g.count for g in groups), available=True)


def test_bluescreen_and_kernel_power_findings():
    now = datetime.now()
    bs = EventGroup("bluescreen", "critical", 2, now - timedelta(days=3), now, details=Counter({"0x0000001A": 2}))
    kp = EventGroup("unexpected_shutdown", "warning", 6, now - timedelta(days=5), now, details=Counter())
    out = rules.rule_events(mk(events=_ev([bs, kp])))
    found = {f.id: f for f in out}
    assert found["events:bluescreen"].severity == "critical"
    lines = [str(x) for x in found["events:bluescreen"].evidence["extra_detected"]]
    assert "MEMORY_MANAGEMENT" in lines[0]
    assert any("mdsched" in str(r) for r in found["events:bluescreen"].recommendations)
    assert found["events:kernel_power"].severity == "critical"  # >= 5


def test_kernel_power_with_bugcheck_counts_as_bluescreen():
    now = datetime.now()
    kp = EventGroup("unexpected_shutdown", "warning", 1, now, now, details=Counter({"0x00000116": 1}))
    out = rules.rule_events(mk(events=_ev([kp])))
    assert ("events", "critical") in ids(out)


def test_events_ok_and_unavailable():
    out = rules.rule_events(mk(events=_ev([EventGroup("app_crash", "info", 1, datetime.now(), datetime.now())])))
    assert ("events", "ok") in ids(out)
    d = mk(events=EventSummary(days=30, available=False))
    assert rules.rule_events(d) == []
    assert d.skipped[0][0] == "events"


def test_frequent_app_crashes_only_when_repeated():
    now = datetime.now()
    g = EventGroup("app_crash", "info", 5, now, now, details=Counter({"game.exe": 4, "tool.exe": 1}))
    out = rules.rule_events(mk(events=_ev([g])))
    f = next(f for f in out if f.id == "events:app_crash")
    assert [str(x) for x in f.evidence["extra_detected"]] == ["game.exe: 4×"]


def test_problem_devices():
    hw = {"problem_devices": [{"name": "USB Gerät", "code": 43, "reason": "stopped_reported_problem"},
                              {"name": "Bluetooth", "code": 22, "reason": "disabled"}]}
    out = rules.rule_devices(mk(hw=hw))
    assert ("devices", "warning") in ids(out)
    assert ("devices_disabled", "info") in ids(out)


def test_windows_versions():
    base = {"platform": "windows"}
    d = mk(hw={**base, "os": {"name": "Windows 10 Pro", "build": 19045, "family": "win10"}})
    assert rules.rule_windows(d)[0].title.key == "diag.win10_eos.title"
    d = mk(hw={**base, "os": {"name": "Windows 11 Pro", "build": 22631, "family": "win11"}},
           now=datetime(2026, 1, 1).timestamp())
    assert rules.rule_windows(d)[0].title.key == "diag.win11_eos.title"
    d = mk(hw={**base, "os": {"name": "Windows 11 Pro", "build": 26200, "family": "win11", "uptime_s": 20 * 86400},
               "pending_reboot": {"pending": True}})
    keys = {f.title.key for f in rules.rule_windows(d)}
    assert keys == {"diag.windows_ok.title", "diag.pending_reboot.title", "diag.uptime_long.title"}


def test_gpu_driver_age_is_low_confidence_info():
    hw = {"gpus": [{"name": "GeForce RTX", "vendor": "nvidia", "driver_version": "1.0",
                    "driver_date": datetime.now() - timedelta(days=500)}]}
    f = rules.rule_gpu_driver(mk(hw=hw))[0]
    assert f.severity == "info" and f.confidence == "low"
    assert f.actions and f.actions[0][1].startswith("url:https://www.nvidia.com")


# ---- Netzwerk ------------------------------------------------------------------

def ping(host, rtts, sent=10):
    p = PingStats(host, sent=sent, received=len(rtts), rtts=list(rtts))
    return p


def net(**kw):
    base = dict(started=time.time(), gateway="192.168.1.1", gateway_ping=ping("192.168.1.1", [2] * 10),
                internet_pings=[ping("1.1.1.1", [15] * 10)], dns=[DnsResult("www.microsoft.com", True, 20)],
                http=HttpResult(True, False, 50), any_adapter_up=True)
    base.update(kw)
    return NetworkResult(**base)


def test_network_ok():
    out = rules.rule_network(mk(net=net()))
    assert ids(out) == {("net", "ok")}


def test_network_offline_cases():
    assert ids(rules.rule_network(mk(net=net(any_adapter_up=False)))) == {("net", "critical")}
    out = rules.rule_network(mk(net=net(gateway_ping=ping("192.168.1.1", []), internet_pings=[ping("1.1.1.1", [])],
                                        http=HttpResult(False))))
    assert out[0].title.key == "diag.net_gateway_down.title"
    out = rules.rule_network(mk(net=net(internet_pings=[ping("1.1.1.1", [])], http=HttpResult(False))))
    assert out[0].title.key == "diag.net_no_internet.title"


def test_dns_failure_detected_separately():
    out = rules.rule_network(mk(net=net(dns=[DnsResult("a", False, error="timeout"), DnsResult("b", False)])))
    assert any(f.title.key == "diag.net_dns_fail.title" for f in out)


def test_ping_blocked_but_web_ok_is_not_offline():
    out = rules.rule_network(mk(net=net(internet_pings=[ping("1.1.1.1", [])])))
    keys = {f.title.key for f in out}
    assert "diag.net_ping_blocked.title" in keys
    assert "diag.net_no_internet.title" not in keys


def test_packet_loss_local_vs_internet():
    out = rules.rule_network(mk(net=net(gateway_ping=ping("gw", [2] * 7))))
    assert any(f.title.key == "diag.net_loss_local.title" for f in out)
    out = rules.rule_network(mk(net=net(internet_pings=[ping("1.1.1.1", [20] * 8)])))
    assert any(f.title.key == "diag.net_loss_inet.title" for f in out)


def test_captive_portal_and_weak_wifi():
    out = rules.rule_network(mk(net=net(http=HttpResult(False, True), wifi=WifiInfo(True, ssid="Hotel", signal_pct=30))))
    keys = {f.title.key for f in out}
    assert "diag.net_captive.title" in keys and "diag.wifi_weak.title" in keys


# ---- Gesamtablauf ----------------------------------------------------------------

def test_rule_exception_does_not_stop_diagnosis(monkeypatch):
    def broken(_d):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(rules, "ALL_RULES", [broken, rules.rule_ram])
    import corecontrol.diagnostics.engine as engine

    monkeypatch.setattr(engine, "ALL_RULES", [broken, rules.rule_ram])
    d = mk()
    out = apply_rules(d)
    assert ("ram", "ok") in ids(out)
    assert ("broken", ) == (d.skipped[-1][0],)


def test_summarize_live_handles_missing_values():
    s1 = Sample(ts=1.0, cpu_percent=10, ram_percent=50)
    s2 = Sample(ts=3.0, cpu_percent=30, ram_percent=55, cpu_temp=60, gpus=[GpuSample("RTX", "x", "nvidia", util=50, temp=70)])
    ls = summarize_live([s1, s2])
    assert ls.cpu_avg == 20 and ls.cpu_max == 30
    assert ls.cpu_temp == 60 and ls.gpu_temp == 70
    assert ls.seconds == 2.0
    assert summarize_live([]).cpu_avg is None


def test_every_finding_has_texts_in_both_languages():
    from corecontrol import i18n

    d = mk(hw={"volumes": [{"mount": "C:\\", "total": 100 * 1024**3, "free": 1 * 1024**3, "percent": 99, "system": True}]},
           net=net(gateway_ping=ping("gw", [2] * 7), http=HttpResult(False, True)))
    out = apply_rules(d)
    for lang in ("de", "en"):
        i18n.set_language(lang)
        for f in out:
            assert not str(f.title).startswith("diag."), f.title
            assert not str(f.detected).startswith("diag."), f.detected

"""Berichte (Export, Bereinigung persönlicher Daten, HTML-Sicherheit) und Verlauf (Aufbewahrung)."""

import time

from corecontrol.core.settings import defaults
from corecontrol.diagnostics.models import DiagnosisResult
from corecontrol.diagnostics.rules import DiagInput, LiveSummary, rule_ram
from corecontrol.history.store import METRICS, HistoryRecorder, HistoryStore
from corecontrol.monitoring.models import Sample
from corecontrol.reports.redact import Redactor
from corecontrol.reports.report import build_report, save_report


def test_redactor_removes_personal_data():
    r = Redactor(user="maxmuster", host="MAX-PC", ssids=["FRITZ!Box 7590"])
    text = ("Pfad C:\\Users\\maxmuster\\Desktop, PC MAX-PC, IP 192.168.178.20, Ziel 1.1.1.1, "
            "MAC 00:1A:2B:3C:4D:5E, IPv6 fe80::1c2b:3a4d:5e6f:7a8b, Mail max@example.org, WLAN FRITZ!Box 7590, "
            "Zeit 12:30:45")
    out = r(text)
    for secret in ("maxmuster", "MAX-PC", "192.168.178.20", "00:1A:2B:3C:4D:5E", "fe80::", "max@example.org", "FRITZ!Box"):
        assert secret not in out, secret
    assert "1.1.1.1" in out
    assert "12:30:45" in out
    assert "C:\\Users\\<USER>\\Desktop" in out


def _result():
    d = DiagInput(settings=defaults(), live=LiveSummary(samples=10, ram_percent=95, ram_total=8 * 1024**3, ram_used=7 * 1024**3))
    findings = rule_ram(d)
    return DiagnosisResult(started_at=time.time() - 5, finished_at=time.time(), findings=findings, skipped=[("x", "Grund")])


def test_report_text_and_html(tmp_path):
    res = _result()
    rep = build_report(res, {"os": {"name": "Windows 11 Pro <script>alert(1)</script>"}}, None, "Mein Problem")
    txt = rep.text()
    assert "Arbeitsspeicher fast voll" in txt and "Mein Problem" in txt
    assert "Nicht verfügbar" in txt  # fehlende Werte werden benannt, nicht erfunden
    html = rep.html()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    p = save_report(rep, tmp_path / "bericht.html")
    assert p.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    p2 = save_report(rep, tmp_path / "bericht.txt")
    assert "CoreControl" in p2.read_text(encoding="utf-8")


def test_report_without_diagnosis():
    rep = build_report(None, None, Sample(ts=time.time(), cpu_percent=5.0))
    txt = rep.text()
    assert "Keine Diagnose durchgeführt" in txt


def test_report_redaction_applies_everywhere():
    res = _result()
    rep = build_report(res, {"os": {"name": "Win", "computer_name": "GEHEIM-PC"}}, None, "Ich heiße geheimuser",
                       redactor=Redactor(user="geheimuser", host="GEHEIM-PC"))
    assert "geheimuser" not in rep.text() and "geheimuser" not in rep.html()


def test_history_store_retention_and_downsampling(tmp_path):
    st = HistoryStore(tmp_path / "h.db")
    now = time.time()
    day = 86400
    vals = {m: (10.0, 20.0) for m in METRICS}
    for ts in (now - 40 * day, now - 10 * day, now - 10 * day + 60, now - 60):
        st.insert("minute", int(ts) // 60 * 60, vals)
    st.purge(retention_days=30, now=now)
    s = st.stats()
    assert s["minute_rows"] == 1      # nur der aktuelle Minutenwert
    assert s["hour_rows"] == 1        # 10 Tage alte Werte zu einer Stunde zusammengefasst, 40 Tage alt gelöscht
    ts, avg, mx = st.query("cpu", now - 31 * day)
    assert len(ts) == 2 and all(a == 10.0 for a in avg) and all(m == 20.0 for m in mx)
    st.clear()
    assert st.stats()["minute_rows"] == 0
    st.close()


def test_history_recorder_aggregates_per_minute(tmp_path):
    st = HistoryStore(tmp_path / "h.db")
    rec = HistoryRecorder(st, lambda: True)
    base = 1_700_000_000 // 60 * 60
    for i, v in enumerate((10.0, 30.0, None)):
        rec.add(Sample(ts=base + i, cpu_percent=v))
    rec.add(Sample(ts=base + 61, cpu_percent=50.0))  # neue Minute -> erste wird geschrieben
    ts, avg, mx = st.query("cpu", base - 10, base + 30)
    assert ts == [base] and avg == [20.0] and mx == [30.0]
    _, ram_avg, _ = st.query("ram", base - 10, base + 30)
    assert ram_avg == [None]  # nicht gemessen -> nicht erfunden
    st.close()


def test_history_disabled_writes_nothing(tmp_path):
    st = HistoryStore(tmp_path / "h.db")
    rec = HistoryRecorder(st, lambda: False)
    rec.add(Sample(ts=1000, cpu_percent=10))
    rec.add(Sample(ts=1100, cpu_percent=10))
    assert st.stats()["minute_rows"] == 0
    st.close()

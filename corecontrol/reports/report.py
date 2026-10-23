"""Diagnosebericht als TXT oder HTML.

Der Bericht wird aus den vorhandenen Daten zusammengestellt (letzte Diagnose,
Hardware, aktuelle Messwerte). Es werden keine Werte erfunden: Fehlendes wird
als „Nicht verfügbar“ ausgewiesen.
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from corecontrol import APP_NAME, __version__
from corecontrol.core import fmt
from corecontrol.i18n import current_language, tr
from corecontrol.reports.redact import Redactor


@dataclass
class Block:
    kind: str  # kv, text, findings, table, list
    data: Any
    headers: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Report:
    title: str
    created: datetime
    sections: list[Section]

    def text(self) -> str:
        return render_text(self)

    def html(self) -> str:
        return render_html(self)


def _lines(items) -> list[str]:
    out: list[str] = []
    for t in items or []:
        out.extend(t.lines() if hasattr(t, "lines") else [str(t)])
    return out


def build_report(result=None, hardware: dict | None = None, sample=None, user_note: str = "",
                 redactor: Callable[[str], str] | None = None) -> Report:
    na = tr("common.na")
    red = redactor or (lambda s: s)
    hw = hardware or (result.hardware if result is not None else None) or {}
    sections: list[Section] = []

    # Kopf
    head = Section(tr("rep.sec.meta"))
    meta = [
        (tr("rep.app"), f"{APP_NAME} {__version__}"),
        (tr("rep.created"), fmt.datetime_(time.time(), with_seconds=True)),
        (tr("rep.language"), current_language()),
    ]
    if result is not None:
        meta.append((tr("rep.diag_time"), fmt.datetime_(result.finished_at, with_seconds=True)))
    else:
        meta.append((tr("rep.diag_time"), tr("rep.no_diag")))
    head.blocks.append(Block("kv", meta))
    if user_note.strip():
        head.blocks.append(Block("text", tr("rep.user_note") + "\n" + user_note.strip()))
    sections.append(head)

    # Zusammenfassung
    if result is not None:
        s = Section(tr("rep.sec.summary"))
        s.blocks.append(Block("kv", [
            (tr("severity.critical"), str(result.count("critical"))),
            (tr("severity.warning"), str(result.count("warning"))),
            (tr("severity.info"), str(result.count("info"))),
            (tr("rep.checked_ok"), str(result.count("ok"))),
        ]))
        sections.append(s)
        f = Section(tr("rep.sec.findings"))
        f.blocks.append(Block("findings", result.sorted()))
        sections.append(f)
        if result.skipped:
            sk = Section(tr("diagp.skipped"))
            sk.blocks.append(Block("list", [str(r) for _, r in result.skipped]))
            sections.append(sk)

    # System
    os_ = hw.get("os") or {}
    cpu = hw.get("cpu") or {}
    board = hw.get("board") or {}
    mem = hw.get("memory") or {}
    sysrows = [
        (tr("hw.os"), f"{os_.get('name', na)} {os_.get('display_version') or ''}".strip()),
        (tr("hw.build"), str(os_.get("build") or na) + (f".{os_.get('ubr')}" if os_.get("ubr") else "")),
        (tr("hw.uptime"), fmt.duration(os_.get("uptime_s"))),
        (tr("hw.cpu"), cpu.get("name") or na),
        (tr("hw.cores"), f"{cpu.get('cores') or '?'} / {cpu.get('threads') or '?'}"),
        (tr("hw.system_maker"), " ".join(x for x in (board.get("system_manufacturer"), board.get("system_model")) if x) or na),
        (tr("hw.board"), " ".join(x for x in (board.get("manufacturer"), board.get("product")) if x) or na),
        (tr("hw.bios"), " ".join(x for x in (board.get("bios_vendor"), board.get("bios_version")) if x) or na),
        (tr("hw.ram_total"), fmt.bytes_(mem.get("total")) if mem.get("total") else na),
    ]
    for m in mem.get("modules") or []:
        sysrows.append((m.get("slot") or "RAM", " ".join(str(x) for x in (fmt.bytes_(m.get("capacity")), m.get("type"),
                                                                           m.get("configured_speed") or m.get("speed") or "",
                                                                           m.get("manufacturer"), m.get("part")) if x)))
    for g in hw.get("gpus") or []:
        sysrows.append((tr("hw.gpus"), f"{g.get('name')} · {tr('hw.driver')} {g.get('driver_version') or na} "
                                       f"({fmt.date_(g['driver_date']) if g.get('driver_date') else na})"))
    sec = Section(tr("rep.sec.system"))
    sec.blocks.append(Block("kv", sysrows))
    sections.append(sec)

    # Aktuelle Werte
    if sample is not None:
        gp = sample.primary_gpu
        live = Section(tr("rep.sec.live"))
        live.blocks.append(Block("kv", [
            (tr("dash.cpu"), f"{fmt.pct(sample.cpu_percent)} · {fmt.mhz(sample.cpu_freq_mhz)} · {fmt.temp(sample.cpu_temp)}"),
            (tr("dash.ram"), f"{fmt.pct(sample.ram_percent)} ({fmt.bytes_(sample.ram_used)} / {fmt.bytes_(sample.ram_total)})"),
            (tr("dash.gpu"), f"{gp.name}: {fmt.pct(gp.util)} · {fmt.temp(gp.temp)}" if gp else na),
            (tr("dash.disk"), tr("dash.disk_rw", read=fmt.rate_bytes(sample.disk_read_bps), write=fmt.rate_bytes(sample.disk_write_bps))),
            (tr("dash.network"), tr("dash.net_line", down=fmt.rate_bits(sample.net_down_bps), up=fmt.rate_bits(sample.net_up_bps))),
            (tr("rep.sensor_source"), tr(f"rep.lhm.{sample.lhm_status}")),
        ]))
        sens = [s for s in sample.sensors if s.kind in ("temperature", "fan", "power", "voltage")]
        if sens:
            live.blocks.append(Block("table", [[s.hardware, s.name, f"{fmt.number(s.value, 1)} {s.unit}"] for s in sens[:60]],
                                     [tr("mon.col.hardware"), tr("mon.col.sensor"), tr("mon.col.value")]))
        sections.append(live)

    # Laufwerke
    disks, vols = hw.get("disks") or [], hw.get("volumes") or []
    if disks or vols:
        st = Section(tr("rep.sec.storage"))
        if disks:
            st.blocks.append(Block("table", [[d.get("model") or "?", d.get("media") or "–", d.get("bus") or "–",
                                              fmt.bytes_(d.get("size")) if d.get("size") else "–",
                                              tr(f"hw.health.{d.get('health', 'unknown')}")] for d in disks],
                                   [tr("common.name"), tr("hw.media"), tr("hw.bus"), tr("common.size"), tr("hw.health")]))
        if vols:
            st.blocks.append(Block("table", [[v["mount"], v.get("fs") or "", fmt.bytes_(v["total"]), fmt.bytes_(v["free"]),
                                              fmt.pct(100 - v["percent"])] for v in vols],
                                   [tr("rep.col.drive"), tr("rep.col.fs"), tr("rep.col.total"), tr("rep.col.free"),
                                    tr("rep.col.free_pct")]))
        sections.append(st)

    # Netzwerk
    net = result.network if result is not None else None
    if net is not None:
        ns = Section(tr("rep.sec.network"))
        rows = []
        gp = net.gateway_ping
        rows.append((tr("net.gateway"), net.gateway or na))
        if gp is not None:
            rows.append((tr("net.gateway_ping"), _ping_text(gp)))
        for p in net.internet_pings:
            rows.append((f"Ping {p.host}", _ping_text(p)))
        for d in net.dns:
            rows.append((f"DNS {d.domain}", fmt.ms(d.ms) if d.ok else tr("net.failed", error=d.error)))
        if net.http is not None:
            rows.append((tr("net.http"), tr("net.http_ok") if net.http.ok else
                         (tr("net.http_captive") if net.http.captive_portal else tr("net.failed", error=net.http.error))))
        if net.wifi is not None and net.wifi.available:
            rows.append((tr("net.wifi"), f"{net.wifi.ssid} · {fmt.pct(net.wifi.signal_pct)} · {net.wifi.radio} {net.wifi.band}".strip()))
        ns.blocks.append(Block("kv", rows))
        ad = [[a.name, a.kind, tr("common.yes") if a.up else tr("common.no"), f"{a.speed_mbps} Mbit/s" if a.speed_mbps else "–",
               ", ".join(a.ipv4) or "–"] for a in net.adapters if a.kind != "loopback"]
        if ad:
            ns.blocks.append(Block("table", ad, [tr("common.name"), tr("common.type"), tr("net.connected"), tr("net.speed"), "IPv4"]))
        ns.blocks.append(Block("text", tr("rep.network_note")))
        sections.append(ns)

    # Ereignisse
    ev = result.events if result is not None else None
    if ev is not None and getattr(ev, "available", False):
        es = Section(tr("rep.sec.events", days=ev.days))
        rows = []
        for g in ev.groups[:40]:
            title = tr(f"ev.cat.{g.category}.title") if g.category != "other" else f"{g.provider} ({g.event_id})"
            details = ", ".join(f"{k} ({n}×)" for k, n in g.details.most_common(5))
            rows.append([tr(f"severity.{g.severity}"), title, str(g.count), fmt.datetime_(g.last), details])
        es.blocks.append(Block("table", rows, [tr("rep.col.severity"), tr("rep.col.event"), tr("common.count"),
                                               tr("rep.col.last"), tr("rep.col.details")]))
        sections.append(es)

    # Grenzen
    lim = Section(tr("rep.sec.limits"))
    lim.blocks.append(Block("list", tr_list_safe("rep.limits")))
    sections.append(lim)

    report = Report(tr("rep.title"), datetime.now(), sections)
    return redact_report(report, red)


def tr_list_safe(key: str) -> list[str]:
    from corecontrol.i18n import tr_list

    return tr_list(key)


def _ping_text(p) -> str:
    if not p.sent:
        return tr("common.na")
    if not p.reachable:
        return tr("net.ping_none", sent=p.sent)
    return tr("net.ping_stats", avg=fmt.ms(p.avg), min=fmt.ms(p.min), max=fmt.ms(p.max), loss=fmt.pct(p.loss_pct),
              jitter=fmt.ms(p.jitter))


def redact_report(report: Report, red: Callable[[str], str]) -> Report:
    """Wandelt alle Inhalte in Text um und wendet die Bereinigung an."""
    for sec in report.sections:
        sec.title = red(sec.title)
        for b in sec.blocks:
            if b.kind == "kv":
                b.data = [(red(str(k)), red(str(v))) for k, v in b.data]
            elif b.kind == "text":
                b.data = red(str(b.data))
            elif b.kind == "list":
                b.data = [red(str(x)) for x in b.data]
            elif b.kind == "table":
                b.data = [[red(str(c)) for c in row] for row in b.data]
                b.headers = [red(h) for h in b.headers]
            elif b.kind == "findings":
                b.data = [{
                    "severity": f.severity,
                    "title": red(str(f.title)),
                    "detected": red(str(f.detected)),
                    "extra": [red(x) for x in _lines(f.evidence.get("extra_detected"))],
                    "causes": [red(x) for x in _lines(f.causes)],
                    "recs": [red(x) for x in _lines(f.recommendations)],
                    "risks": red(str(f.risks)) if f.risks else "",
                    "confidence": tr(f"confidence.{f.confidence}"),
                    "uncertainty": red(str(f.uncertainty)) if f.uncertainty else "",
                } if not isinstance(f, dict) else f for f in b.data]
    return report


# ---- Ausgabe ------------------------------------------------------------------
def render_text(r: Report) -> str:
    out = [r.title, "=" * len(r.title), ""]
    for sec in r.sections:
        out += [sec.title, "-" * len(sec.title)]
        for b in sec.blocks:
            if b.kind == "kv":
                w = max((len(k) for k, _ in b.data), default=0)
                out += [f"{k.ljust(w)} : {v}" for k, v in b.data]
            elif b.kind == "text":
                out.append(b.data)
            elif b.kind == "list":
                out += [f"- {x}" for x in b.data]
            elif b.kind == "table":
                rows = [b.headers] + b.data if b.headers else b.data
                widths = [min(48, max(len(str(row[i])) for row in rows if i < len(row))) for i in range(len(rows[0]))] if rows else []
                for j, row in enumerate(rows):
                    out.append(" | ".join(str(c)[:48].ljust(widths[i]) for i, c in enumerate(row)))
                    if j == 0 and b.headers:
                        out.append("-+-".join("-" * w for w in widths))
            elif b.kind == "findings":
                for f in b.data:
                    out.append(f"[{tr('severity.' + f['severity']).upper()}] {f['title']}")
                    out.append(f"    {f['detected']}")
                    out += [f"      · {x}" for x in f["extra"]]
                    if f["causes"]:
                        out.append(f"    {tr('finding.causes')}:")
                        out += [f"      - {x}" for x in f["causes"]]
                    if f["recs"]:
                        out.append(f"    {tr('finding.recommendations')}:")
                        out += [f"      {i}. {x}" for i, x in enumerate(f["recs"], 1)]
                    if f["risks"]:
                        out.append(f"    {tr('finding.risks')}: {f['risks']}")
                    if f["severity"] != "ok":
                        out.append(f"    {tr('finding.confidence')}: {f['confidence']}" + (f" – {f['uncertainty']}" if f["uncertainty"] else ""))
                    out.append("")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


SEV_COLOR = {"critical": "#d42f35", "warning": "#b77400", "info": "#1a6fdc", "ok": "#1e9b52"}


def render_html(r: Report) -> str:
    e = html.escape
    parts = [f"""<!DOCTYPE html>
<html lang="{e(current_language())}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(r.title)}</title>
<style>
body {{ font-family: "Segoe UI", system-ui, -apple-system, sans-serif; color: #1a1c20; background: #f3f4f6; margin: 0; }}
main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 60px; }}
h1 {{ font-size: 26px; margin: 0 0 4px; }}
.sub {{ color: #545a64; margin-bottom: 24px; }}
section {{ background: #fff; border: 1px solid #e0e3e8; border-radius: 12px; padding: 18px 22px; margin-bottom: 16px; }}
h2 {{ font-size: 17px; margin: 0 0 12px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
td, th {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #eceef1; vertical-align: top; }}
th {{ color: #545a64; font-weight: 600; }}
table.kv td:first-child {{ color: #545a64; width: 34%; }}
.finding {{ border: 1px solid #e0e3e8; border-left: 4px solid #888; border-radius: 10px; padding: 12px 14px; margin: 10px 0; }}
.finding h3 {{ font-size: 15px; margin: 0 0 4px; }}
.chip {{ display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 9px; color: #fff; margin-left: 6px; vertical-align: middle; }}
.muted {{ color: #545a64; }}
.cap {{ font-size: 11px; font-weight: 700; color: #878d97; letter-spacing: .3px; margin-top: 8px; text-transform: uppercase; }}
ul, ol {{ margin: 4px 0 0 0; padding-left: 22px; }}
li {{ margin: 2px 0; }}
footer {{ color: #878d97; font-size: 12px; text-align: center; margin-top: 24px; }}
@media print {{ body {{ background: #fff; }} section {{ break-inside: avoid; }} }}
</style></head><body><main>
<h1>{e(r.title)}</h1><div class="sub">{e(APP_NAME)} {e(__version__)} · {e(fmt.datetime_(r.created.timestamp(), with_seconds=True))}</div>
"""]
    for sec in r.sections:
        parts.append(f"<section><h2>{e(sec.title)}</h2>")
        for b in sec.blocks:
            if b.kind == "kv":
                parts.append("<table class='kv'>" + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in b.data) + "</table>")
            elif b.kind == "text":
                parts.append("<p>" + e(b.data).replace("\n", "<br>") + "</p>")
            elif b.kind == "list":
                parts.append("<ul>" + "".join(f"<li>{e(x)}</li>" for x in b.data) + "</ul>")
            elif b.kind == "table":
                head = "<tr>" + "".join(f"<th>{e(h)}</th>" for h in b.headers) + "</tr>" if b.headers else ""
                body = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in row) + "</tr>" for row in b.data)
                parts.append(f"<table>{head}{body}</table>")
            elif b.kind == "findings":
                for f in b.data:
                    col = SEV_COLOR.get(f["severity"], "#888")
                    parts.append(f"<div class='finding' style='border-left-color:{col}'>"
                                 f"<h3>{e(f['title'])}<span class='chip' style='background:{col}'>{e(tr('severity.' + f['severity']))}</span></h3>"
                                 f"<div class='muted'>{e(f['detected'])}</div>")
                    if f["extra"]:
                        parts.append("<ul>" + "".join(f"<li>{e(x)}</li>" for x in f["extra"]) + "</ul>")
                    if f["causes"]:
                        parts.append(f"<div class='cap'>{e(tr('finding.causes'))}</div><ul>" + "".join(f"<li>{e(x)}</li>" for x in f["causes"]) + "</ul>")
                    if f["recs"]:
                        parts.append(f"<div class='cap'>{e(tr('finding.recommendations'))}</div><ol>" + "".join(f"<li>{e(x)}</li>" for x in f["recs"]) + "</ol>")
                    if f["risks"]:
                        parts.append(f"<div class='cap'>{e(tr('finding.risks'))}</div><div>{e(f['risks'])}</div>")
                    if f["severity"] != "ok":
                        unc = f" – {e(f['uncertainty'])}" if f["uncertainty"] else ""
                        parts.append(f"<div class='cap'>{e(tr('finding.confidence'))}</div><div><b>{e(f['confidence'])}</b>{unc}</div>")
                    parts.append("</div>")
        parts.append("</section>")
    parts.append(f"<footer>{e(tr('rep.footer'))}</footer></main></body></html>")
    return "".join(parts)


def save_report(report: Report, path: Path) -> Path:
    path = Path(path)
    content = report.html() if path.suffix.lower() in (".html", ".htm") else report.text()
    path.write_text(content, encoding="utf-8")
    return path


def make_redactor(enabled: bool, result=None, settings: dict | None = None) -> Callable[[str], str]:
    if not enabled:
        return lambda s: s
    keep = list((settings or {}).get("network.ping_targets") or [])
    ssids = []
    if result is not None and result.network is not None and result.network.wifi is not None:
        ssids.append(result.network.wifi.ssid)
    return Redactor.for_this_pc(keep, ssids)

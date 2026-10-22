"""Startseite (Dashboard) im CoreControl-Design: Metrikkarten mit Ringanzeigen, Auslastungsdiagramm,
Temperaturen, Lüfter, Schnellaktionen, letzte Ereignisse und Netzwerk. Kacheln sind in den
Einstellungen ein-/ausblendbar und sortierbar. Fehlende Werte werden als „Nicht verfügbar“ gezeigt."""

from __future__ import annotations

import socket
import time
from datetime import datetime, timedelta

import psutil
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from corecontrol.core import fmt
from corecontrol.i18n import tr
from corecontrol.ui import anim
from corecontrol.ui.bus import bus, on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.theme import theme
from corecontrol.ui.widgets.charts import LineChart, Sparkline
from corecontrol.ui.widgets.common import Card, button, icon_label, label, set_role
from corecontrol.ui.widgets.controls import BarRow, GaugeRing, IconBadge

SPANS = {"cpu": 3, "gpu": 3, "ram": 3, "storage": 3, "load": 6, "temps": 3, "fans": 3,
         "actions": 4, "events": 4, "network": 4, "diagnosis": 6, "system": 6}


def _vline() -> QFrame:
    f = QFrame()
    f.setFixedWidth(1)
    set_role(f, "separator")
    f.setStyleSheet("max-height: 10000px;")
    return f


class MetricCard(Card):
    """CPU / GPU / RAM / Speicher: Symbol, Name, Modell, Ring, zwei Kennzahlen, Verlaufslinie."""

    def __init__(self, title_key: str, icon: str, color_role: str, target: str, spark_ymax: float | None = 100.0):
        super().__init__(None, role="tile", margins=18, spacing=10, hover=True)
        self.target = target
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(IconBadge(icon, color_role, 44))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(title_key, "h2"))
        self.subtitle = label(None, "faint", text="")
        col.addWidget(self.subtitle)
        head.addLayout(col, 1)
        self.add_layout(head)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.ring = GaugeRing(112, 9, color_role)
        body.addWidget(self.ring)
        body.addWidget(_vline())
        stats = QVBoxLayout()
        stats.setSpacing(10)
        self.v1, self.c1 = label(None, "statValue", text="–"), label(None, "faint", text="")
        self.v2, self.c2 = label(None, "statValue", text="–"), label(None, "faint", text="")
        for v, c in ((self.v1, self.c1), (self.v2, self.c2)):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(v)
            box.addWidget(c)
            stats.addLayout(box)
        stats.addStretch(1)
        body.addLayout(stats, 1)
        self.add_layout(body)
        self.spark = Sparkline(color_role, 60, spark_ymax, 46)
        self.add(self.spark)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            bus.navigate.emit(self.target)
        super().mouseReleaseEvent(ev)

    def set_stats(self, v1: str, c1: str, v2: str, c2: str) -> None:
        self.v1.setText(v1)
        self.c1.setText(c1)
        self.v2.setText(v2)
        self.c2.setText(c2)


class ActionRow(Card):
    def __init__(self, icon: str, title_key: str, sub_key: str, on_click):
        super().__init__(None, role="actionRow", margins=12, spacing=0, hover=True)
        self.on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(IconBadge(icon, "accent", 36))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(title_key, "h3"))
        col.addWidget(label(sub_key, "faint"))
        row.addLayout(col, 1)
        row.addWidget(icon_label("chevron-right", "text3", 16))
        self.add_layout(row)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.on_click()
        super().mouseReleaseEvent(ev)


def when_text(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    today = datetime.now().date()
    hm = d.strftime("%H:%M")
    if d.date() == today:
        return tr("time.today", time=hm)
    if d.date() == today - timedelta(days=1):
        return tr("time.yesterday", time=hm)
    return fmt.datetime_(d)


LEVEL_ICON = {"ok": ("circle-check", "ok"), "info": ("info", "info"), "warning": ("triangle-alert", "warn"),
              "critical": ("octagon-x", "crit")}


class EventsCard(Card):
    def __init__(self, ctx):
        super().__init__("dash.events", "scroll-text", role="tile", hover=True, badge="accent")
        self.ctx = ctx
        self.add_header_widget(button("dash.events_all", "ghost", None, self._show_all))
        self.rows = QVBoxLayout()
        self.rows.setSpacing(2)
        self.add_layout(self.rows)
        self.body.addStretch(1)
        ctx.activity.on_add(lambda *_: QTimer.singleShot(0, self.refresh))
        on_refresh(self, self.refresh)
        self.refresh()

    def refresh(self):
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        items = self.ctx.activity.recent(5)
        if not items:
            self.rows.addWidget(label("dash.events_none", "muted", wrap=True))
            return
        for a in items:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 5, 0, 5)
            h.setSpacing(10)
            name, role = LEVEL_ICON.get(a.level, LEVEL_ICON["info"])
            h.addWidget(icon_label(name, role, 18))
            t = QLabel(tr(a.key, **a.params))
            t.setWordWrap(True)
            h.addWidget(t, 1)
            h.addWidget(label(None, "faint", text=when_text(a.ts)))
            self.rows.addWidget(w)

    def _show_all(self):
        from corecontrol.ui.dialogs import show_text_dialog

        lines = [f"{when_text(a.ts):>18}   {tr('severity.' + a.level) if a.level != 'ok' else 'OK':10}  {tr(a.key, **a.params)}"
                 for a in self.ctx.activity.all()]
        show_text_dialog(self, tr("dash.events"), "\n".join(lines) or tr("dash.events_none"))


class NetworkCard(Card):
    def __init__(self, ctx):
        super().__init__("dash.network", "wifi", role="tile", hover=True, badge="cat_net")
        self.ctx = ctx
        self.kv = QGridLayout()
        self.kv.setHorizontalSpacing(10)
        self.kv.setVerticalSpacing(7)
        self.vals = {}
        for i, (key, icon) in enumerate((("conn", "wifi"), ("ip", "globe"), ("down", "download"), ("up", "upload"),
                                         ("ping", "timer"), ("loss", "activity"))):
            self.kv.addWidget(icon_label(icon, "text3", 15), i, 0)
            self.kv.addWidget(label(f"dash.net.{key}", "muted"), i, 1)
            v = label(None, None, text="–")
            v.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.kv.addWidget(v, i, 2)
            self.vals[key] = v
        self.kv.setColumnStretch(1, 1)
        self.add_layout(self.kv)
        self.spark = Sparkline("cat_net", 60, None, 40)
        self.add(self.spark)
        self.add(label("dash.net_hint", "faint", wrap=True))
        self._last_if = 0.0
        self._conn = ("–", "")

    def update_sample(self, s):
        if time.time() - self._last_if > 10:
            self._last_if = time.time()
            self._conn = self._connection()
        conn, ip = self._conn
        self.vals["conn"].setText(conn)
        self.vals["conn"].setStyleSheet(f"color: {theme.palette.accent_fg};")
        self.vals["ip"].setText(ip or tr("common.na"))
        self.vals["down"].setText(fmt.rate_bits(s.net_down_bps))
        self.vals["up"].setText(fmt.rate_bits(s.net_up_bps))
        net = getattr(self.ctx, "last_network", None)
        best = net.best_internet if net is not None else None
        self.vals["ping"].setText(fmt.ms(best.avg) if best is not None and best.avg is not None else tr("dash.net.not_tested"))
        self.vals["loss"].setText(fmt.pct(best.loss_pct) if best is not None and best.loss_pct is not None else "–")
        self.spark.push(s.net_down_bps)

    def _connection(self) -> tuple[str, str]:
        from corecontrol.network.tests import _kind

        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
        except Exception:
            return tr("common.na"), ""
        best = None
        for name, st in stats.items():
            if not st.isup:
                continue
            kind = _kind(name, "")
            if kind in ("loopback", "virtual"):
                continue
            ips = [a.address for a in addrs.get(name, []) if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254."))]
            if not ips:
                continue
            rank = {"ethernet": 0, "wifi": 1}.get(kind, 2)
            if best is None or rank < best[0]:
                best = (rank, kind, ips[0])
        if best is None:
            return tr("dash.net.disconnected"), ""
        return tr(f"dash.net.kind.{best[1]}" if best[1] in ("ethernet", "wifi") else "dash.net.kind.other"), best[2]


class DashboardPage(Page):
    page_id = "dashboard"
    title_key = "dash.welcome"
    subtitle_key = "dash.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._build_header_tiles()
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        for i in range(12):
            self.grid.setColumnStretch(i, 1)
        self.body.addWidget(self.grid_host)
        foot = label("dash.footer", "faint")
        foot.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.body.addWidget(foot)
        self.tiles: dict[str, QWidget] = {}
        self._mode = ""
        self._first_show = True
        self._build_tiles()
        self.finish()
        ctx.setting_changed.connect(self._setting_changed)
        ctx.hardware_ready.connect(lambda *_: self._update_static())
        ctx.load_hardware()
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()

    # ---- Kopfbereich -------------------------------------------------------
    def _build_header_tiles(self):
        clock = QFrame()
        set_role(clock, "headTile")
        cl = QHBoxLayout(clock)
        cl.setContentsMargins(16, 10, 18, 10)
        cl.setSpacing(12)
        cl.addWidget(IconBadge("clock", "accent", 38))
        col = QVBoxLayout()
        col.setSpacing(0)
        self.time_lbl = label(None, "midValue", text="")
        self.date_lbl = label(None, "faint", text="")
        col.addWidget(self.time_lbl)
        col.addWidget(self.date_lbl)
        cl.addLayout(col)
        procs = QFrame()
        set_role(procs, "headTile")
        pl = QHBoxLayout(procs)
        pl.setContentsMargins(16, 10, 18, 10)
        pl.setSpacing(12)
        pl.addWidget(IconBadge("chart-no-axes-column", "cat_cpu", 38))
        col2 = QVBoxLayout()
        col2.setSpacing(0)
        col2.addWidget(label("dash.active_procs", "faint"))
        self.proc_lbl = label(None, "midValue", text="–")
        col2.addWidget(self.proc_lbl)
        pl.addLayout(col2)
        self.header.add_action(clock)
        self.header.add_action(procs)

    def _tick_clock(self):
        now = datetime.now()
        self.time_lbl.setText(now.strftime("%H:%M"))
        months_de = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                     "November", "Dezember"]
        from corecontrol import i18n

        if i18n.current_language() == "de":
            self.date_lbl.setText(f"{now.day}. {months_de[now.month - 1]} {now.year}")
        else:
            self.date_lbl.setText(now.strftime("%B %d, %Y"))

    # ---- Kacheln -------------------------------------------------------------
    def _build_tiles(self):
        for t in self.tiles.values():
            t.deleteLater()
        self.tiles = {}
        for tid in self.ctx.settings.get("dashboard.tiles"):
            t = self._make_tile(tid)
            if t is not None:
                self.tiles[tid] = t
        self._mode = ""
        self._relayout()
        self._update_static()

    def _make_tile(self, tid: str):
        if tid == "cpu":
            return MetricCard("dash.cpu", "cpu", "cat_cpu", "monitoring")
        if tid == "gpu":
            return MetricCard("dash.gpu", "monitor", "cat_gpu", "monitoring")
        if tid == "ram":
            return MetricCard("dash.ram", "memory-stick", "cat_ram", "processes")
        if tid == "storage":
            return MetricCard("dash.storage", "hard-drive", "cat_storage", "storage", spark_ymax=None)
        if tid == "load":
            c = Card("dash.load", "chart-line", role="tile", hover=True, badge="accent")
            c.chart = LineChart(120, 100, "%", lambda v: f"{v:.0f}%", show_legend=True, min_height=210,
                                time_axis=True, legend_right=True)
            c.chart.add_series("CPU", "cat_cpu")
            c.chart.add_series("GPU", "cat_gpu")
            c.chart.add_series("RAM", "cat_ram")
            c.add(c.chart, 1)
            return c
        if tid == "temps":
            c = Card("dash.temps", "thermometer", role="tile", hover=True, badge="cat_temp")
            c.bars = [BarRow(r) for r in ("cat_cpu", "cat_gpu", "cat_storage", "cat_ram")]
            for b in c.bars:
                c.add(b)
            c.hint = label("dash.sensors_hint", "faint", wrap=True)
            c.add(c.hint)
            c.body.addStretch(1)
            return c
        if tid == "fans":
            c = Card("dash.fans", "fan", role="tile", hover=True, badge="cat_gpu")
            c.bars = [BarRow(r) for r in ("cat_cpu", "cat_gpu", "cat_gpu", "cat_gpu")]
            for b in c.bars:
                c.add(b)
            c.hint = label("dash.fans_hint", "faint", wrap=True)
            c.add(c.hint)
            c.body.addStretch(1)
            return c
        if tid == "actions":
            c = Card("dash.actions", "sparkles", role="tile", badge="accent")
            c.add(ActionRow("play", "dash.act.diag", "dash.act.diag_sub",
                            lambda: (bus.navigate.emit("diagnosis"), self.ctx.run_diagnosis())))
            c.add(ActionRow("download", "dash.act.report", "dash.act.report_sub", lambda: bus.navigate.emit("reports")))
            c.add(ActionRow("settings", "dash.act.settings", "dash.act.settings_sub", lambda: bus.navigate.emit("settings")))
            c.body.addStretch(1)
            return c
        if tid == "events":
            return EventsCard(self.ctx)
        if tid == "network":
            return NetworkCard(self.ctx)
        if tid == "diagnosis":
            from corecontrol.ui.pages.dashboard_extra import DiagnosisTile

            return DiagnosisTile(self.ctx)
        if tid == "system":
            from corecontrol.ui.pages.dashboard_extra import SystemTile

            return SystemTile(self.ctx)
        return None

    def _relayout(self):
        w = self.width() or 1300
        mode = "wide" if w >= 1100 else "medium" if w >= 760 else "narrow"
        if mode == self._mode:
            return
        self._mode = mode
        while self.grid.count():
            self.grid.takeAt(0)
        r = c = 0
        for tid, tile in self.tiles.items():
            span = SPANS.get(tid, 4)
            if mode == "medium":
                span = 6 if span <= 4 else 12
            elif mode == "narrow":
                span = 12
            if c + span > 12:
                r, c = r + 1, 0
            self.grid.addWidget(tile, r, c, 1, span)
            c += span
            if c >= 12:
                r, c = r + 1, 0

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    def _setting_changed(self, key, _value):
        if key == "dashboard.tiles":
            self._build_tiles()
            s = self.ctx.sampler.store.latest() if self.ctx.sampler else None
            if s:
                self.on_sample(s)

    def _update_static(self):
        hw = self.ctx.hardware or {}
        cpu = hw.get("cpu") or {}
        gpus = hw.get("gpus") or []
        mem = hw.get("memory") or {}
        if "cpu" in self.tiles:
            self.tiles["cpu"].subtitle.setText(cpu.get("name") or tr("common.loading" if self.ctx.hardware is None else "common.na"))
        if "gpu" in self.tiles:
            self.tiles["gpu"].subtitle.setText(gpus[0]["name"] if gpus else tr("common.loading" if self.ctx.hardware is None else "common.na"))
        if "ram" in self.tiles:
            mtype = next((m.get("type") for m in mem.get("modules") or [] if m.get("type")), "")
            self.tiles["ram"].subtitle.setText(f"{fmt.bytes_(psutil.virtual_memory().total, digits=0)} {mtype}".strip())
        if "storage" in self.tiles:
            vol = next((v for v in hw.get("volumes") or [] if v.get("system")), None)
            disk = None
            if vol is not None:
                disk = next((d for d in hw.get("disks") or [] if str(d.get("number")) == str(vol.get("disk"))), None)
            if disk:
                self.tiles["storage"].subtitle.setText(f"{disk.get('model')} · {disk.get('media') or ''}".strip(" ·"))
            else:
                self.tiles["storage"].subtitle.setText(self._system_mount())

    @staticmethod
    def _system_mount() -> str:
        import os

        from corecontrol.core.platform import IS_WINDOWS

        return (os.environ.get("SystemDrive", "C:") + "\\") if IS_WINDOWS else "/"

    # ---- Anzeigen ------------------------------------------------------------
    def on_show(self) -> None:
        if self.ctx.sampler:
            hist = self.ctx.sampler.store.window(120)
            for s in hist[:-1]:
                self._push_series(s, animate=False)
            s = self.ctx.sampler.store.latest()
            if s:
                self.on_sample(s)
        if self._first_show:
            self._first_show = False
            for i, t in enumerate(self.tiles.values()):
                anim.fade_in(t, 300, 40 * i)

    def _push_series(self, s, animate=True):
        g = s.primary_gpu
        tiles = self.tiles
        if "cpu" in tiles:
            tiles["cpu"].spark.push(s.cpu_percent, animate)
        if "gpu" in tiles:
            tiles["gpu"].spark.push(g.util if g else None, animate)
        if "ram" in tiles:
            tiles["ram"].spark.push(s.ram_percent, animate)
        if "storage" in tiles:
            tiles["storage"].spark.push((s.disk_read_bps or 0) + (s.disk_write_bps or 0) if s.disk_read_bps is not None else None, animate)
        if "load" in tiles:
            tiles["load"].chart.push(s.cpu_percent, g.util if g else None, s.ram_percent, ts=s.ts, animate=animate)
        if "network" in tiles and not animate:
            tiles["network"].spark.push(s.net_down_bps, False)

    def on_sample(self, s) -> None:
        st = self.ctx.settings
        self._push_series(s)
        self.proc_lbl.setText(str(s.process_count or "–"))
        t = self.tiles
        na = tr("common.na")
        if "cpu" in t:
            lvl = "critical" if (s.cpu_temp or 0) >= st.get("thresholds.cpu_temp_crit") else "normal"
            t["cpu"].ring.set_value(s.cpu_percent, fmt.pct(s.cpu_percent), tr("dash.load_caption"), lvl)
            t["cpu"].set_stats(fmt.mhz(s.cpu_freq_mhz), tr("dash.clock"), fmt.temp(s.cpu_temp), tr("dash.temperature"))
        if "gpu" in t:
            g = s.primary_gpu
            if g is None:
                t["gpu"].ring.set_value(None, "–", na)
                t["gpu"].set_stats(na, tr("dash.clock"), na, tr("dash.temperature"))
            else:
                t["gpu"].ring.set_value(g.util, fmt.pct(g.util), tr("dash.load_caption"))
                if g.clock_mhz is not None:
                    v1, c1 = fmt.mhz(g.clock_mhz), tr("dash.clock")
                else:
                    v1, c1 = (fmt.bytes_(g.vram_used) if g.vram_used is not None else na), tr("dash.vram")
                t["gpu"].set_stats(v1, c1, fmt.temp(g.temp), tr("dash.temperature"))
        if "ram" in t:
            lvl = "warning" if (s.ram_percent or 0) >= st.get("thresholds.ram_warn") else "normal"
            t["ram"].ring.set_value(s.ram_percent, fmt.pct(s.ram_percent), tr("dash.load_caption"), lvl)
            free = (s.ram_total - s.ram_used) if s.ram_total is not None and s.ram_used is not None else None
            t["ram"].set_stats(fmt.bytes_(s.ram_used), tr("dash.used"), fmt.bytes_(free), tr("dash.free"))
        if "storage" in t and int(s.ts) % 5 == 0 or "storage" in t and t["storage"].v1.text() == "–":
            try:
                u = psutil.disk_usage(self._system_mount())
                lvl = "critical" if 100 - u.percent < st.get("thresholds.disk_free_crit_pct") else \
                    "warning" if 100 - u.percent < st.get("thresholds.disk_free_warn_pct") else "normal"
                t["storage"].ring.set_value(u.percent, fmt.pct(u.percent), tr("dash.occupied"), lvl)
                t["storage"].set_stats(fmt.bytes_(u.used), tr("dash.used"), fmt.bytes_(u.free), tr("dash.free"))
            except Exception:
                t["storage"].ring.set_value(None, "–", na)
        if "temps" in t:
            self._update_temps(t["temps"], s)
        if "fans" in t:
            self._update_fans(t["fans"], s)
        if "network" in t:
            t["network"].update_sample(s)

    def _update_temps(self, card, s):
        g = s.primary_gpu
        board = next((x.value for x in s.sensors if x.hw_kind == "board" and x.kind == "temperature" and 0 < x.value < 120), None)
        drive = next((x.value for x in s.sensors if x.hw_kind == "storage" and x.kind == "temperature" and 0 < x.value < 120), None)
        if drive is None:
            for d in (self.ctx.hardware or {}).get("disks") or []:
                rel = d.get("reliability") or {}
                if rel.get("temperature"):
                    drive = rel["temperature"]
                    break
        rows = [("CPU", s.cpu_temp), ("GPU", g.temp if g else None), (tr("dash.board"), board), (tr("dash.drive"), drive)]
        for bar, (name, val) in zip(card.bars, rows):
            bar.set(name, fmt.temp(val), None if val is None else val / 100.0)
        card.hint.setVisible(s.lhm_status != "ok")

    def _update_fans(self, card, s):
        fans = [x for x in s.sensors if x.kind == "fan" and x.value > 0]
        g = s.primary_gpu
        rows: list[tuple[str, str, float | None]] = []
        mx = max([f.value for f in fans] + [2000.0])
        for f in fans[:4]:
            rows.append((f.name, f"{fmt.number(f.value)} RPM", f.value / (mx * 1.15)))
        if g is not None and g.fan_pct is not None and len(rows) < 4:
            rows.append((tr("dash.gpu_fan"), fmt.pct(g.fan_pct), g.fan_pct / 100))
        for i, bar in enumerate(card.bars):
            if i < len(rows):
                bar.setVisible(True)
                bar.set(rows[i][0], rows[i][1], rows[i][2])
            else:
                bar.setVisible(i == 0 and not rows)
                if i == 0 and not rows:
                    bar.set(tr("dash.fans"), tr("common.na"), None)
        card.hint.setVisible(not rows)

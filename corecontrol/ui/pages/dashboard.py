"""Startseite mit anpassbaren Dashboard-Kacheln."""

from __future__ import annotations

import time

import psutil
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from corecontrol.core import fmt
from corecontrol.i18n import tr
from corecontrol.ui.bus import bind_text, bus, on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.charts import Ring, Sparkline
from corecontrol.ui.widgets.common import Chip, button, icon_label, label, set_prop, set_role


class Tile(QFrame):
    def __init__(self, title_key: str, icon: str, target: str | None = None):
        super().__init__()
        set_role(self, "tile")
        self.target = target
        self.setMinimumHeight(170)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(icon_label(icon, "text2", 17))
        self.title = label(title_key, "h3")
        head.addWidget(self.title)
        head.addStretch(1)
        self.chip = Chip("", "neutral")
        self.chip.setVisible(False)
        head.addWidget(self.chip)
        lay.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(4)
        lay.addLayout(self.body, 1)
        if target:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, ev):
        if self.target and ev.button() == Qt.MouseButton.LeftButton:
            bus.navigate.emit(self.target)
        super().mouseReleaseEvent(ev)

    def set_chip(self, text: str | None, level: str = "neutral") -> None:
        self.chip.setVisible(bool(text))
        if text:
            self.chip.setText(text)
            self.chip.set_level(level)


class MetricTile(Tile):
    """Große Zahl + Unterzeilen + Verlaufslinie."""

    def __init__(self, title_key, icon, target=None, ring=False, y_max=100.0, color="accent"):
        super().__init__(title_key, icon, target)
        row = QHBoxLayout()
        row.setSpacing(14)
        self.ring = Ring(58, 7) if ring else None
        if self.ring:
            row.addWidget(self.ring)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.value = label(None, "bigValue", text="–")
        self.sub1 = label(None, "muted", text="")
        self.sub2 = label(None, "faint", text="")
        col.addWidget(self.value)
        col.addWidget(self.sub1)
        col.addWidget(self.sub2)
        row.addLayout(col, 1)
        self.body.addLayout(row)
        self.body.addStretch(1)
        self.spark = Sparkline(color, 60, y_max)
        self.body.addWidget(self.spark)


def _level(value: float | None, warn: float, crit: float | None = None) -> str:
    if value is None:
        return "accent"
    if crit is not None and value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "accent"


class DiagnosisTile(Tile):
    def __init__(self, ctx):
        super().__init__("dash.diagnosis", "stethoscope", "diagnosis")
        self.ctx = ctx
        row = QHBoxLayout()
        row.setSpacing(14)
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(46, 46)
        row.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.headline = label(None, "midValue", text="")
        self.headline.setWordWrap(True)
        self.detail = label(None, "muted", text="", wrap=True)
        col.addWidget(self.headline)
        col.addWidget(self.detail)
        row.addLayout(col, 1)
        self.body.addLayout(row)
        self.top = QVBoxLayout()
        self.top.setSpacing(3)
        self.body.addLayout(self.top)
        self.body.addStretch(1)
        btns = QHBoxLayout()
        self.run_btn = button("dash.run_diagnosis", "primary", "play", ctx.run_diagnosis)
        btns.addWidget(self.run_btn)
        btns.addStretch(1)
        self.when = label(None, "faint", text="")
        btns.addWidget(self.when)
        self.body.addLayout(btns)
        ctx.diagnosis_started.connect(self.refresh)
        ctx.diagnosis_finished.connect(lambda *_: self.refresh())
        on_refresh(self, self.refresh)
        self.refresh()

    def refresh(self) -> None:
        from corecontrol.ui import icons
        from corecontrol.ui.theme import theme

        res = self.ctx.diagnosis_result
        while self.top.count():
            w = self.top.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.run_btn.setEnabled(not self.ctx.diagnosis_running)
        if self.ctx.diagnosis_running:
            self.headline.setText(tr("dash.diag_running"))
            self.detail.setText(tr("dash.diag_running_text"))
            self.status_icon.setPixmap(icons.pixmap("refresh-cw", theme.palette.accent_fg, 40))
            self.set_chip(None)
            return
        if res is None:
            self.headline.setText(tr("dash.diag_none"))
            self.detail.setText(tr("dash.diag_none_text"))
            self.status_icon.setPixmap(icons.pixmap("circle-help", theme.palette.text3, 40))
            self.when.setText("")
            self.set_chip(None)
            return
        crit, warn, info = res.count("critical"), res.count("warning"), res.count("info")
        if crit:
            name, role, head, lvl = "octagon-x", "crit", tr("dash.diag_crit", n=crit), "critical"
        elif warn:
            name, role, head, lvl = "triangle-alert", "warn", tr("dash.diag_warn", n=warn), "warning"
        else:
            name, role, head, lvl = "circle-check", "ok", tr("dash.diag_ok"), "ok"
        self.status_icon.setPixmap(icons.pixmap(name, theme.palette.color(role), 40))
        self.headline.setText(head)
        self.detail.setText(tr("dash.diag_summary", crit=crit, warn=warn, info=info, ok=res.count("ok")))
        self.set_chip(tr(f"severity.{lvl}"), lvl)
        for f in res.problems()[:3]:
            row = QHBoxLayout()
            dot = QLabel("●")
            set_role(dot, {"critical": "crit", "warning": "warn"}.get(f.severity, "info"))
            t = QLabel(str(f.title))
            t.setWordWrap(True)
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            hl.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            hl.addWidget(t, 1)
            self.top.addWidget(w)
        self.when.setText(tr("dash.diag_when", when=fmt.datetime_(res.finished_at)))


class StorageTile(Tile):
    def __init__(self):
        super().__init__("dash.storage", "hard-drive", "storage")
        self.rows = QVBoxLayout()
        self.rows.setSpacing(8)
        self.body.addLayout(self.rows)
        self.body.addStretch(1)
        self._widgets: list = []
        self._last = 0.0

    def refresh(self, force: bool = False) -> None:
        if not force and time.time() - self._last < 30:
            return
        self._last = time.time()
        for w in self._widgets:
            w.deleteLater()
        self._widgets = []
        parts = []
        try:
            parts = [p for p in psutil.disk_partitions(all=False) if p.fstype and "cdrom" not in p.opts]
        except Exception:
            pass
        shown = 0
        for p in parts:
            if p.mountpoint.startswith(("/snap", "/boot", "/proc", "/sys")) or p.fstype in ("squashfs", "overlay"):
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue
            if u.total < 1024**3:
                continue
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(3)
            top = QHBoxLayout()
            name = QLabel(p.mountpoint)
            name.setStyleSheet("font-weight: 600;")
            top.addWidget(name)
            top.addStretch(1)
            free = label(None, "muted", text=tr("dash.free_of", free=fmt.bytes_(u.free), total=fmt.bytes_(u.total)))
            top.addWidget(free)
            v.addLayout(top)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(u.percent * 10))
            bar.setFixedHeight(8)
            free_pct = 100 - u.percent
            set_prop(bar, "level", "critical" if free_pct < 5 else "warning" if free_pct < 10 else "")
            v.addWidget(bar)
            self.rows.addWidget(w)
            self._widgets.append(w)
            shown += 1
            if shown >= 4:
                break
        if shown == 0:
            w = label("common.na", "muted")
            self.rows.addWidget(w)
            self._widgets.append(w)


class SystemTile(Tile):
    def __init__(self, ctx):
        super().__init__("dash.system", "monitor", "hardware")
        self.ctx = ctx
        from corecontrol.ui.widgets.common import KeyValueGrid

        self.grid = KeyValueGrid()
        self.body.addWidget(self.grid)
        self.body.addStretch(1)
        ctx.hardware_ready.connect(lambda *_: self.refresh())
        on_refresh(self, self.refresh)

    def refresh(self, sample=None) -> None:
        hw = self.ctx.hardware or {}
        os_ = hw.get("os") or {}
        cpu = hw.get("cpu") or {}
        gpus = hw.get("gpus") or []
        uptime = time.time() - psutil.boot_time()
        rows = [
            (tr("dash.sys.os"), f"{os_.get('name') or fmt.or_na(None)} {os_.get('display_version') or ''}".strip()),
            (tr("dash.sys.cpu"), cpu.get("name") or tr("common.loading")),
            (tr("dash.sys.gpu"), ", ".join(g["name"] for g in gpus) if gpus else (tr("common.loading") if self.ctx.hardware is None else tr("common.na"))),
            (tr("dash.sys.ram"), fmt.bytes_(psutil.virtual_memory().total)),
            (tr("dash.sys.uptime"), fmt.duration(uptime)),
        ]
        if sample is not None and sample.process_count:
            rows.append((tr("dash.sys.processes"), str(sample.process_count)))
        self.grid.set_rows(rows)


class SensorsTile(Tile):
    def __init__(self):
        super().__init__("dash.sensors", "thermometer", "monitoring")
        from corecontrol.ui.widgets.common import KeyValueGrid

        self.grid = KeyValueGrid()
        self.body.addWidget(self.grid)
        self.hint = label("dash.sensors_hint", "faint", wrap=True)
        self.body.addWidget(self.hint)
        self.body.addStretch(1)

    def update_sample(self, s) -> None:
        rows = []
        if s.cpu_temp is not None:
            rows.append((tr("dash.cpu_temp"), fmt.temp(s.cpu_temp)))
        g = s.primary_gpu
        if g is not None and g.temp is not None:
            rows.append((tr("dash.gpu_temp"), fmt.temp(g.temp)))
        fans = [x for x in s.sensors if x.kind == "fan" and x.value > 0][:3]
        for f in fans:
            rows.append((f.name, f"{fmt.number(f.value)} RPM"))
        if s.cpu_power_w is not None:
            rows.append((tr("dash.cpu_power"), f"{fmt.number(s.cpu_power_w, 1)} W"))
        self.grid.set_rows(rows)
        self.hint.setVisible(s.lhm_status != "ok")


class DashboardPage(Page):
    page_id = "dashboard"
    title_key = "dash.title"
    subtitle_key = "dash.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header.add_action(button("dash.customize", None, "layout-grid", lambda: bus.navigate.emit("settings")))
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(16)
        self.body.addWidget(self.grid_host)
        self.lhm_hint = None
        self.tiles: dict[str, QWidget] = {}
        self._columns = 0
        self._build_tiles()
        self.finish()
        ctx.setting_changed.connect(self._setting_changed)
        ctx.load_hardware()
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._refresh_slow())
        self._timer.start(30000)

    def _build_tiles(self) -> None:
        for t in self.tiles.values():
            t.deleteLater()
        self.tiles = {}
        order = self.ctx.settings.get("dashboard.tiles")
        for tid in order:
            tile = self._make_tile(tid)
            if tile is not None:
                self.tiles[tid] = tile
        self._columns = 0
        self._relayout()

    def _make_tile(self, tid: str):
        if tid == "diagnosis":
            return DiagnosisTile(self.ctx)
        if tid == "cpu":
            return MetricTile("dash.cpu", "cpu", "monitoring", ring=True)
        if tid == "ram":
            return MetricTile("dash.ram", "memory-stick", "processes", ring=True, color="info")
        if tid == "gpu":
            return MetricTile("dash.gpu", "monitor", "monitoring", ring=True, color="ok")
        if tid == "disk":
            return MetricTile("dash.disk", "hard-drive", "monitoring", y_max=None, color="warn")
        if tid == "network":
            return MetricTile("dash.network", "wifi", "network", y_max=None, color="info")
        if tid == "storage":
            t = StorageTile()
            t.refresh(force=True)
            return t
        if tid == "system":
            t = SystemTile(self.ctx)
            t.refresh()
            return t
        if tid == "sensors":
            return SensorsTile()
        return None

    def _columns_for_width(self, w: int) -> int:
        return 3 if w >= 1080 else 2 if w >= 700 else 1

    def _relayout(self) -> None:
        cols = self._columns_for_width(self.width() or 1200)
        if cols == self._columns:
            return
        self._columns = cols
        while self.grid.count():
            self.grid.takeAt(0)
        r = c = 0
        for tid, tile in self.tiles.items():
            span = 2 if tid == "diagnosis" and cols >= 2 else 1
            if c + span > cols:
                r, c = r + 1, 0
            self.grid.addWidget(tile, r, c, 1, span)
            c += span
            if c >= cols:
                r, c = r + 1, 0
        for i in range(3):
            self.grid.setColumnStretch(i, 1 if i < cols else 0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    def _setting_changed(self, key, _value):
        if key == "dashboard.tiles":
            self._build_tiles()
            s = self.ctx.sampler.store.latest() if self.ctx.sampler else None
            if s:
                self.on_sample(s)

    def _refresh_slow(self):
        t = self.tiles.get("storage")
        if t:
            t.refresh()

    def on_show(self) -> None:
        if self.ctx.sampler:
            for s in self.ctx.sampler.store.window(60):
                self._push(s, sparks_only=True)
            s = self.ctx.sampler.store.latest()
            if s:
                self.on_sample(s)
        t = self.tiles.get("storage")
        if t:
            t.refresh(force=True)

    def _push(self, s, sparks_only=False) -> None:
        g = s.primary_gpu
        for tid, val in (("cpu", s.cpu_percent), ("ram", s.ram_percent), ("gpu", g.util if g else None),
                         ("disk", (s.disk_read_bps or 0) + (s.disk_write_bps or 0) if s.disk_read_bps is not None else None),
                         ("network", s.net_down_bps)):
            t = self.tiles.get(tid)
            if isinstance(t, MetricTile):
                t.spark.push(val)

    def on_sample(self, s) -> None:
        st = self.ctx.settings
        self._push(s)
        t = self.tiles.get("cpu")
        if isinstance(t, MetricTile):
            t.value.setText(fmt.pct(s.cpu_percent))
            t.ring.set_value(s.cpu_percent, _level(s.cpu_percent, st.get("thresholds.cpu_load_warn")))
            t.sub1.setText(tr("dash.cpu_clock", clock=fmt.mhz(s.cpu_freq_mhz)))
            t.sub2.setText(tr("dash.cpu_temp_line", temp=fmt.temp(s.cpu_temp)))
            self._temp_chip(t, s.cpu_temp, st.get("thresholds.cpu_temp_warn"), st.get("thresholds.cpu_temp_crit"))
        t = self.tiles.get("ram")
        if isinstance(t, MetricTile):
            t.value.setText(fmt.pct(s.ram_percent))
            t.ring.set_value(s.ram_percent, _level(s.ram_percent, st.get("thresholds.ram_warn")))
            t.sub1.setText(tr("dash.used_of", used=fmt.bytes_(s.ram_used), total=fmt.bytes_(s.ram_total)))
            t.sub2.setText(tr("dash.swap_line", used=fmt.bytes_(s.swap_used)) if s.swap_total else "")
        t = self.tiles.get("gpu")
        if isinstance(t, MetricTile):
            g = s.primary_gpu
            if g is None:
                t.value.setText(tr("common.na"))
                t.ring.set_value(None)
                t.sub1.setText(tr("dash.gpu_none"))
                t.sub2.setText("")
                t.set_chip(None)
            else:
                t.value.setText(fmt.pct(g.util))
                t.ring.set_value(g.util)
                vram = tr("dash.vram_line", used=fmt.bytes_(g.vram_used), total=fmt.bytes_(g.vram_total)) \
                    if g.vram_used is not None else tr("dash.vram_na")
                t.sub1.setText(f"{g.name}")
                t.sub2.setText(f"{vram} · {fmt.temp(g.temp)}")
                self._temp_chip(t, g.temp, st.get("thresholds.gpu_temp_warn"), st.get("thresholds.gpu_temp_crit"))
        t = self.tiles.get("disk")
        if isinstance(t, MetricTile):
            total = None if s.disk_read_bps is None else (s.disk_read_bps or 0) + (s.disk_write_bps or 0)
            t.value.setText(fmt.rate_bytes(total))
            t.sub1.setText(tr("dash.disk_rw", read=fmt.rate_bytes(s.disk_read_bps), write=fmt.rate_bytes(s.disk_write_bps)))
            t.sub2.setText(tr("dash.disk_active", pct=fmt.pct(s.disk_active_pct)))
        t = self.tiles.get("network")
        if isinstance(t, MetricTile):
            t.value.setText(fmt.rate_bits(s.net_down_bps))
            t.sub1.setText(tr("dash.net_line", down=fmt.rate_bits(s.net_down_bps), up=fmt.rate_bits(s.net_up_bps)))
            t.sub2.setText(tr("dash.net_hint"))
        t = self.tiles.get("system")
        if isinstance(t, SystemTile) and int(s.ts) % 10 == 0:
            t.refresh(s)
        t = self.tiles.get("sensors")
        if isinstance(t, SensorsTile):
            t.update_sample(s)

    def _temp_chip(self, tile: Tile, value, warn, crit) -> None:
        if value is None:
            tile.set_chip(None)
        elif value >= crit:
            tile.set_chip(fmt.temp(value), "critical")
        elif value >= warn:
            tile.set_chip(fmt.temp(value), "warning")
        else:
            tile.set_chip(fmt.temp(value), "ok")

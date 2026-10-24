"""Live-Monitoring mit Diagrammen und Sensortabelle."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from corecontrol.core import fmt
from corecontrol.i18n import tr
from corecontrol.ui.bus import on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.charts import LineChart
from corecontrol.ui.widgets.common import Card, KeyValueGrid, label

KIND_ORDER = ["temperature", "fan", "load", "clock", "power", "voltage", "control", "data", "other"]



def _nowrap(text: str) -> str:
    """Kurze Werte wie „84,8 MB / 5,5 GB“ nicht mitten im Wert umbrechen."""
    return text.replace(" ", "\u00a0")

class MonitoringPage(Page):
    page_id = "monitoring"
    title_key = "mon.title"
    subtitle_key = "mon.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)

        self.cpu_card = Card("mon.cpu", "cpu", badge="cat_cpu", hover=True)
        self.cpu_chart = LineChart(120, 100, "%", lambda v: f"{v:.0f}%", time_axis=True)
        self.cpu_chart.add_series(tr("mon.load"), "cat_cpu")
        self.cpu_card.add(self.cpu_chart)
        self.cpu_info = KeyValueGrid(2)
        self.cpu_card.add(self.cpu_info)

        self.ram_card = Card("mon.ram", "memory-stick", badge="cat_ram", hover=True)
        self.ram_chart = LineChart(120, 100, "%", lambda v: f"{v:.0f}%", time_axis=True)
        self.ram_chart.add_series(tr("mon.used"), "cat_ram")
        self.ram_card.add(self.ram_chart)
        self.ram_info = KeyValueGrid(2)
        self.ram_card.add(self.ram_info)

        self.gpu_card = Card("mon.gpu", "monitor", badge="cat_gpu", hover=True)
        self.gpu_chart = LineChart(120, 100, "%", lambda v: f"{v:.0f}%", time_axis=True)
        self.gpu_chart.add_series(tr("mon.load"), "cat_gpu")
        self.gpu_card.add(self.gpu_chart)
        self.gpu_info = KeyValueGrid(2)
        self.gpu_card.add(self.gpu_info)

        self.temp_card = Card("mon.temps", "thermometer", badge="cat_temp", hover=True)
        self.temp_chart = LineChart(120, 100, "°C", lambda v: f"{v:.0f} °C", time_axis=True)
        self.temp_chart.add_series("CPU", "crit", fill=False)
        self.temp_chart.add_series("GPU", "warn", fill=False)
        self.temp_card.add(self.temp_chart)
        self.temp_hint = label("mon.temp_hint", "faint", wrap=True)
        self.temp_card.add(self.temp_hint)

        self.disk_card = Card("mon.disk", "hard-drive", badge="cat_storage", hover=True)
        self.disk_chart = LineChart(120, None, "", lambda v: fmt.rate_bytes(v), time_axis=True)
        self.disk_chart.add_series(tr("mon.read"), "cat_storage")
        self.disk_chart.add_series(tr("mon.write"), "warn")
        self.disk_card.add(self.disk_chart)

        self.net_card = Card("mon.net", "wifi", badge="cat_net", hover=True)
        self.net_chart = LineChart(120, None, "", lambda v: fmt.rate_bits(v), time_axis=True)
        self.net_chart.add_series(tr("mon.down"), "cat_net")
        self.net_chart.add_series(tr("mon.up"), "ok")
        self.net_card.add(self.net_chart)
        self.net_card.add(label("mon.net_hint", "faint", wrap=True))

        self.cards = [self.cpu_card, self.ram_card, self.gpu_card, self.temp_card, self.disk_card, self.net_card]
        self.grid = grid
        self._cols = 0
        self.body.addWidget(grid_host)

        self.sensor_card = Card("mon.sensors", "gauge", badge="accent")
        self.sensor_status = label(None, "muted", text="", wrap=True)
        self.sensor_card.add(self.sensor_status)
        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(320)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sensor_card.add(self.table)
        self.body.addWidget(self.sensor_card)
        self.finish()
        self._relayout()
        on_refresh(self, self._retranslate)
        self._retranslate()
        self._sensor_tick = 0

    def _retranslate(self):
        self.table.setHorizontalHeaderLabels([tr("mon.col.hardware"), tr("mon.col.sensor"), tr("mon.col.type"),
                                              tr("mon.col.value")])
        for chart, names in ((self.cpu_chart, ["mon.load"]), (self.ram_chart, ["mon.used"]), (self.gpu_chart, ["mon.load"]),
                             (self.disk_chart, ["mon.read", "mon.write"]), (self.net_chart, ["mon.down", "mon.up"])):
            for s, n in zip(chart.series, names):
                s.name = tr(n)

    def _relayout(self):
        cols = 2 if self.width() >= 900 or self.width() == 0 else 1
        if cols == self._cols:
            return
        self._cols = cols
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    def on_show(self):
        if self.ctx.sampler is None:
            return
        for c in (self.cpu_chart, self.ram_chart, self.gpu_chart, self.temp_chart, self.disk_chart, self.net_chart):
            c.clear()
        for s in self.ctx.sampler.store.window(120)[:-1]:
            self._push(s, animate=False)
        s = self.ctx.sampler.store.latest()
        if s:
            self.on_sample(s)

    def _push(self, s, animate=True):
        g = s.primary_gpu
        kw = dict(ts=s.ts, animate=animate)
        self.cpu_chart.push(s.cpu_percent, **kw)
        self.ram_chart.push(s.ram_percent, **kw)
        self.gpu_chart.push(g.util if g else None, **kw)
        self.temp_chart.push(s.cpu_temp, g.temp if g else None, **kw)
        self.disk_chart.push(s.disk_read_bps, s.disk_write_bps, **kw)
        self.net_chart.push(s.net_down_bps, s.net_up_bps, **kw)

    def on_sample(self, s):
        self._push(s)
        hw = self.ctx.hardware or {}
        cpu = hw.get("cpu") or {}
        self.cpu_info.set_rows([
            (tr("mon.load"), fmt.pct(s.cpu_percent)),
            (tr("mon.clock"), fmt.mhz(s.cpu_freq_mhz)),
            (tr("mon.temp"), fmt.temp(s.cpu_temp)),
            (tr("mon.power"), f"{fmt.number(s.cpu_power_w, 1)} W" if s.cpu_power_w is not None else tr("common.na")),
            (tr("mon.cores"), f"{cpu.get('cores') or '?'} / {cpu.get('threads') or len(s.cpu_per_core) or '?'}"),
            (tr("mon.processes"), str(s.process_count or tr("common.na"))),
        ])
        self.ram_info.set_rows([
            (tr("mon.used"), fmt.bytes_(s.ram_used)),
            (tr("mon.total"), fmt.bytes_(s.ram_total)),
            (tr("mon.swap"), _nowrap(f"{fmt.bytes_(s.swap_used)} / {fmt.bytes_(s.swap_total)}") if s.swap_total else tr("common.na")),
            (tr("mon.load"), fmt.pct(s.ram_percent)),
        ])
        g = s.primary_gpu
        if g is None:
            self.gpu_info.set_rows([(tr("mon.gpu"), tr("common.na"))])
        else:
            self.gpu_info.set_rows([
                (tr("common.name"), g.name),
                (tr("mon.load"), fmt.pct(g.util)),
                (tr("mon.vram"), _nowrap(f"{fmt.bytes_(g.vram_used)} / {fmt.bytes_(g.vram_total)}") if g.vram_used is not None else tr("common.na")),
                (tr("mon.temp"), fmt.temp(g.temp)),
                (tr("mon.clock"), fmt.mhz(g.clock_mhz)),
                (tr("mon.power"), f"{fmt.number(g.power_w, 0)} W" if g.power_w is not None else tr("common.na")),
                (tr("mon.fan"), fmt.pct(g.fan_pct)),
                (tr("mon.source"), g.source.upper() if g.source else tr("common.na")),
            ])
        self.temp_hint.setVisible(s.cpu_temp is None)
        self._sensor_tick += 1
        if self._sensor_tick % 2 == 1:
            self._update_sensors(s)

    def _update_sensors(self, s):
        if s.lhm_status == "ok":
            self.sensor_status.setText(tr("mon.sensors_ok", n=len(s.sensors)))
        elif s.lhm_status == "off":
            self.sensor_status.setText(tr("mon.sensors_disabled"))
        else:
            self.sensor_status.setText(tr("mon.sensors_missing"))
        rows = sorted(s.sensors, key=lambda x: (x.hardware, KIND_ORDER.index(x.kind) if x.kind in KIND_ORDER else 99, x.name))
        self.table.setVisible(bool(rows))
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            unit = r.unit
            val = f"{fmt.number(r.value, 0 if r.kind in ('fan', 'clock') else 1)} {unit}".strip()
            for j, txt in enumerate((r.hardware, r.name, tr(f"mon.kind.{r.kind}") if r.kind in KIND_ORDER else r.kind, val)):
                item = self.table.item(i, j)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(i, j, item)
                item.setText(txt)
                if j == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

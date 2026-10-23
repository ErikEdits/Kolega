"""Verlaufsdiagramme aus der lokalen Verlaufsdatenbank."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout

from corecontrol.core import fmt
from corecontrol.i18n import tr
from corecontrol.ui.bus import bind_text, bus, on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.controls import AnimatedButton
from corecontrol.ui.widgets.charts import HistoryChart
from corecontrol.ui.widgets.common import Card, KeyValueGrid, button, label, set_role

RANGES = [("1h", 3600), ("24h", 86400), ("7d", 7 * 86400), ("30d", 30 * 86400), ("all", 730 * 86400)]
METRICS = [
    ("cpu", 100.0, "pct", "accent"), ("ram", 100.0, "pct", "info"), ("gpu", 100.0, "pct", "ok"),
    ("cpu_temp", None, "temp", "crit"), ("gpu_temp", None, "temp", "warn"),
    ("disk_read", None, "bytes", "accent"), ("disk_write", None, "bytes", "warn"),
    ("net_down", None, "bits", "info"), ("net_up", None, "bits", "ok"),
]


def _fmt(kind):
    return {"pct": lambda v: fmt.pct(v), "temp": lambda v: fmt.temp(v), "bytes": lambda v: fmt.rate_bytes(v),
            "bits": lambda v: fmt.rate_bits(v)}[kind]


class HistoryPage(Page):
    page_id = "history"
    title_key = "hist.title"
    subtitle_key = "hist.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header.add_action(button("nav.settings", None, "settings", lambda: bus.navigate.emit("settings")))
        self._range = "24h"
        self._metric = "cpu"
        self.disabled_note = label("hist.disabled", "warn", wrap=True)
        self.body.addWidget(self.disabled_note)

        card = Card(None)
        rr = QHBoxLayout()
        self.range_group = QButtonGroup(self)
        for key, _ in RANGES:
            b = AnimatedButton()
            bind_text(b, f"hist.range.{key}")
            set_role(b, "filter")
            b.setCheckable(True)
            b.setChecked(key == self._range)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda *_, k=key: self._set_range(k))
            self.range_group.addButton(b)
            rr.addWidget(b)
        rr.addStretch(1)
        card.add_layout(rr)
        mr = QHBoxLayout()
        self.metric_group = QButtonGroup(self)
        for key, *_ in METRICS:
            b = AnimatedButton()
            bind_text(b, f"hist.metric.{key}")
            set_role(b, "filter")
            b.setCheckable(True)
            b.setChecked(key == self._metric)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda *_, k=key: self._set_metric(k))
            self.metric_group.addButton(b)
            mr.addWidget(b)
        mr.addStretch(1)
        card.add_layout(mr)
        self.chart = HistoryChart()
        self.chart.setMinimumHeight(320)
        card.add(self.chart)
        self.summary = KeyValueGrid(3)
        card.add(self.summary)
        self.empty = label("hist.empty", "muted", wrap=True)
        card.add(self.empty)
        self.body.addWidget(card)
        self.body.addWidget(label("hist.explain", "faint", wrap=True))
        self.finish()
        on_refresh(self, self.load)

    def _set_range(self, k):
        self._range = k
        self.load()

    def _set_metric(self, k):
        self._metric = k
        self.load()

    def on_show(self):
        self.load()

    def load(self):
        self.disabled_note.setVisible(not self.ctx.settings.get("history.enabled"))
        h = self.ctx.history
        if h is None:
            self.empty.setText(tr("set.history_unavailable"))
            self.empty.setVisible(True)
            return
        seconds = dict(RANGES)[self._range]
        meta = next(m for m in METRICS if m[0] == self._metric)
        ts, avg, mx = h.query(self._metric, time.time() - seconds)
        f = _fmt(meta[2])
        self.chart.set_data(ts, avg, mx, meta[1], f, meta[3])
        vals = [v for v in avg if v is not None]
        maxs = [v for v in mx if v is not None]
        self.empty.setVisible(len(vals) < 2)
        self.empty.setText(tr("hist.empty"))
        if vals:
            self.summary.set_rows([
                (tr("hist.avg"), f(sum(vals) / len(vals))),
                (tr("hist.max"), f(max(maxs)) if maxs else tr("common.na")),
                (tr("hist.points"), str(len(vals))),
            ])
        else:
            self.summary.set_rows([(tr("hist.avg"), tr("common.na"))])

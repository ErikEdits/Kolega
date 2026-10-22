"""Zusätzliche, optionale Dashboard-Kacheln (in den Einstellungen einblendbar)."""

from __future__ import annotations

import time

import psutil
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from corecontrol.core import fmt
from corecontrol.i18n import tr
from corecontrol.ui import icons
from corecontrol.ui.bus import on_refresh
from corecontrol.ui.theme import theme
from corecontrol.ui.widgets.common import Card, KeyValueGrid, button, label, set_role


class DiagnosisTile(Card):
    def __init__(self, ctx):
        super().__init__("dash.diagnosis", "stethoscope", role="tile", hover=True, badge="accent")
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
        self.add_layout(row)
        self.top = QVBoxLayout()
        self.top.setSpacing(3)
        self.add_layout(self.top)
        self.body.addStretch(1)
        btns = QHBoxLayout()
        self.run_btn = button("dash.run_diagnosis", "primary", "play", ctx.run_diagnosis)
        btns.addWidget(self.run_btn)
        btns.addStretch(1)
        self.when = label(None, "faint", text="")
        btns.addWidget(self.when)
        self.add_layout(btns)
        ctx.diagnosis_started.connect(self.refresh)
        ctx.diagnosis_finished.connect(lambda *_: self.refresh())
        on_refresh(self, self.refresh)
        self.refresh()

    def refresh(self) -> None:
        res = self.ctx.diagnosis_result
        while self.top.count():
            w = self.top.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.run_btn.setEnabled(not self.ctx.diagnosis_running)
        p = theme.palette
        if self.ctx.diagnosis_running:
            self.headline.setText(tr("dash.diag_running"))
            self.detail.setText(tr("dash.diag_running_text"))
            self.status_icon.setPixmap(icons.pixmap("refresh-cw", p.accent_fg, 40))
            return
        if res is None:
            self.headline.setText(tr("dash.diag_none"))
            self.detail.setText(tr("dash.diag_none_text"))
            self.status_icon.setPixmap(icons.pixmap("circle-help", p.text3, 40))
            self.when.setText("")
            return
        crit, warn, info = res.count("critical"), res.count("warning"), res.count("info")
        if crit:
            name, role, head = "octagon-x", "crit", tr("dash.diag_crit", n=crit)
        elif warn:
            name, role, head = "triangle-alert", "warn", tr("dash.diag_warn", n=warn)
        else:
            name, role, head = "circle-check", "ok", tr("dash.diag_ok")
        self.status_icon.setPixmap(icons.pixmap(name, p.color(role), 40))
        self.headline.setText(head)
        self.detail.setText(tr("dash.diag_summary", crit=crit, warn=warn, info=info, ok=res.count("ok")))
        for f in res.problems()[:3]:
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


class SystemTile(Card):
    def __init__(self, ctx):
        super().__init__("dash.system", "monitor", role="tile", hover=True, badge="cat_net")
        self.ctx = ctx
        self.grid = KeyValueGrid()
        self.add(self.grid)
        self.body.addStretch(1)
        ctx.hardware_ready.connect(lambda *_: self.refresh())
        on_refresh(self, self.refresh)
        self.refresh()

    def refresh(self) -> None:
        hw = self.ctx.hardware or {}
        os_ = hw.get("os") or {}
        cpu = hw.get("cpu") or {}
        gpus = hw.get("gpus") or []
        loading = tr("common.loading") if self.ctx.hardware is None else tr("common.na")
        self.grid.set_rows([
            (tr("dash.sys.os"), f"{os_.get('name') or loading} {os_.get('display_version') or ''}".strip()),
            (tr("dash.sys.cpu"), cpu.get("name") or loading),
            (tr("dash.sys.gpu"), ", ".join(g["name"] for g in gpus) if gpus else loading),
            (tr("dash.sys.ram"), fmt.bytes_(psutil.virtual_memory().total)),
            (tr("dash.sys.uptime"), fmt.duration(time.time() - psutil.boot_time())),
        ])

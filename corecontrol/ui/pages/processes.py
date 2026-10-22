"""Prozesse anzeigen, suchen, sortieren und nach Bestätigung beenden."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QMessageBox

from corecontrol.core import fmt
from corecontrol.core.platform import IS_WINDOWS, show_in_explorer
from corecontrol.i18n import tr
from corecontrol.system.processes import CAUTION, ProcessMonitor, end_process
from corecontrol.system.tools import run_tool
from corecontrol.ui.bus import on_refresh
from corecontrol.ui.dialogs import ConfirmDialog
from corecontrol.ui import msg
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.common import Card, Chip, button, label
from corecontrol.ui.widgets.table import DataTable
from corecontrol.ui.workers import run_task


class ProcessesPage(Page):
    page_id = "processes"
    title_key = "proc.title"
    subtitle_key = "proc.subtitle"
    scrollable = False

    def __init__(self, ctx):
        super().__init__(ctx)
        if IS_WINDOWS:
            self.header.add_action(button("proc.taskmgr", None, "activity", lambda: run_tool("taskmgr")))
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("proc.search"))
        self.search.textChanged.connect(lambda t: self.table.set_filter(t))
        top.addWidget(self.search, 1)
        self.chip_count = Chip("", "neutral")
        self.chip_cpu = Chip("", "neutral")
        self.chip_ram = Chip("", "neutral")
        for c in (self.chip_count, self.chip_cpu, self.chip_ram):
            top.addWidget(c)
        self.body.addLayout(top)
        self.table = DataTable([], stretch_col=0, min_height=200)
        self.body.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.end_btn = button("proc.end", "danger", "circle-x", self._end)
        self.loc_btn = button("proc.location", None, "folder-open", self._location)
        actions.addWidget(self.end_btn)
        actions.addWidget(self.loc_btn)
        actions.addStretch(1)
        self.hint = label("proc.hint", "faint", wrap=True)
        actions.addWidget(self.hint, 2)
        self.body.addLayout(actions)
        self.monitor = ProcessMonitor()
        self.rows = {}
        self._busy = False
        self._sorted_once = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        on_refresh(self, self._headers)
        self._headers()

    def _headers(self):
        self.table.set_headers([tr("proc.col.name"), "PID", tr("proc.col.cpu"), tr("proc.col.ram"), tr("proc.col.user"),
                                tr("proc.col.path")])

    def on_show(self):
        self.refresh()
        self.timer.start(2000)
        if not self._sorted_once:
            self._sorted_once = True
            self.table.sortByColumn(2, Qt.SortOrder.DescendingOrder)

    def on_hide(self):
        self.timer.stop()

    def refresh(self):
        if self._busy:
            return
        self._busy = True

        def done(rows):
            self._busy = False
            self._render(rows)

        def failed(_):
            self._busy = False

        run_task(self.monitor.refresh, on_done=done, on_error=failed, context="processes")

    def _render(self, rows):
        self.rows = {(r.pid, r.create_time): r for r in rows}
        data, keys = [], []
        total_cpu = 0.0
        for r in rows:
            total_cpu += r.cpu
            name = r.name + (f"  ({tr('proc.protected_tag')})" if r.protected else "")
            data.append([(name, r.name.lower()), (str(r.pid), r.pid), (fmt.pct(r.cpu, 1), r.cpu),
                         (fmt.bytes_(r.mem), r.mem), (r.user, r.user.lower()), (r.exe, r.exe.lower())])
            keys.append((r.pid, r.create_time))
        self.table.set_rows(data, keys)
        self.chip_count.setText(tr("proc.count", n=len(rows)))
        self.chip_cpu.setText(tr("proc.cpu_total", pct=fmt.pct(min(total_cpu, 100))))
        s = self.ctx.sampler.store.latest() if self.ctx.sampler else None
        self.chip_ram.setText(tr("proc.ram_total", pct=fmt.pct(s.ram_percent)) if s else "")

    def _selected(self):
        key = self.table.selected_key()
        return self.rows.get(key) if key else None

    def _location(self):
        r = self._selected()
        if r and r.exe and os.path.exists(r.exe):
            show_in_explorer(r.exe)

    def _end(self):
        r = self._selected()
        if r is None:
            msg.info(self, tr("proc.end"), tr("proc.select_first"))
            return
        if r.protected:
            msg.warn(self, tr("proc.protected_title"), tr("proc.protected_text", name=r.name))
            return
        details = tr("proc.confirm_details", name=r.name, pid=r.pid, path=r.exe or tr("common.na"), user=r.user or tr("common.na"),
                     ram=fmt.bytes_(r.mem))
        msg = tr("proc.confirm_text")
        caution = CAUTION.get(r.name.lower())
        if caution:
            msg += "\n\n" + tr(caution)
        if not ConfirmDialog.ask(self, tr("proc.confirm_title", name=r.name), msg, details,
                                 confirm_text=tr("proc.end_now"), danger=True):
            return
        result = end_process(r.pid, r.name, r.create_time, confirmed=True)
        text = tr(f"proc.result.{result}", name=r.name)
        if result in ("terminated", "killed"):
            self.ctx.activity.add("info", "act.process_ended", "processes", name=r.name)
            msg.info(self, tr("proc.end"), text)
        else:
            msg.warn(self, tr("proc.end"), text)
        self.refresh()

"""Installierte Programme und nützliche Windows-Werkzeuge."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from corecontrol.core import fmt
from corecontrol.core.platform import IS_WINDOWS, open_path, open_url
from corecontrol.i18n import tr
from corecontrol.system.programs import list_programs
from corecontrol.system.tools import TOOLS, run_tool
from corecontrol.ui.bus import bind_text, on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.common import button, icon_label, label, set_role
from corecontrol.ui.widgets.table import DataTable
from corecontrol.ui.workers import run_task


class ProgramsPage(Page):
    page_id = "programs"
    title_key = "prog.title"
    subtitle_key = "prog.subtitle"
    scrollable = False

    def __init__(self, ctx):
        super().__init__(ctx)
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)

        # Programme
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 10, 0, 0)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("prog.search"))
        self.search.textChanged.connect(lambda t: self.table.set_filter(t))
        top.addWidget(self.search, 1)
        self.count = label(None, "muted", text="")
        top.addWidget(self.count)
        v.addLayout(top)
        self.table = DataTable([], stretch_col=0, min_height=200)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(button("prog.uninstall", "primary", "trash-2", lambda: open_url("ms-settings:appsfeatures")))
        row.addWidget(button("prog.open_folder", None, "folder-open", self._open_folder))
        row.addStretch(1)
        row.addWidget(label("prog.uninstall_hint", "faint", wrap=True), 2)
        v.addLayout(row)
        self.tabs.addTab(w, "")

        # Werkzeuge
        tw = QWidget()
        grid = QGridLayout(tw)
        grid.setContentsMargins(0, 12, 0, 0)
        grid.setSpacing(12)
        for i, t in enumerate(TOOLS):
            card = QFrame()
            set_role(card, "card")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 12, 12, 12)
            cl.addWidget(icon_label(t.icon, "accent_fg", 22), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(label(f"tool.{t.id}.name", "h3"))
            col.addWidget(label(f"tool.{t.id}.desc", "faint", wrap=True))
            cl.addLayout(col, 1)
            b = button("common.open", None, None, lambda tid=t.id: run_tool(tid))
            b.setEnabled(IS_WINDOWS)
            cl.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(card, i // 2, i % 2)
        grid.setRowStretch(len(TOOLS) // 2 + 1, 1)
        from PySide6.QtWidgets import QScrollArea

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(tw)
        self.tabs.addTab(sc, "")
        self.programs = []
        on_refresh(self, self._retranslate)
        self._retranslate()

    def _retranslate(self):
        self.tabs.setTabText(0, tr("prog.tab_installed"))
        self.tabs.setTabText(1, tr("prog.tab_tools"))
        self._render()

    def on_show(self):
        if not self.programs:
            if not IS_WINDOWS:
                self.count.setText(tr("common.only_windows"))
                return

            def done(progs):
                self.programs = progs
                self._render()

            run_task(list_programs, on_done=done, context="programs")

    def _render(self):
        self.table.set_headers([tr("common.name"), tr("common.version"), tr("common.publisher"), tr("prog.col.installed"),
                                tr("common.size")])
        rows, keys = [], []
        for i, p in enumerate(self.programs):
            rows.append([(p.name, p.name.lower()), (p.version, p.version), (p.publisher, p.publisher.lower()),
                         (fmt.date_(p.install_date) if p.install_date else "", p.install_date.timestamp() if p.install_date else 0),
                         (fmt.bytes_(p.size) if p.size else "", p.size or 0)])
            keys.append(i)
        self.table.set_rows(rows, keys)
        if self.programs:
            self.count.setText(tr("prog.count", n=len(self.programs)))

    def _open_folder(self):
        k = self.table.selected_key()
        if k is None:
            return
        p = self.programs[k]
        if p.location and os.path.isdir(p.location):
            open_path(p.location)

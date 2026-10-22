"""Autostart-Programme anzeigen und umkehrbar aktivieren/deaktivieren."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QHBoxLayout, QMessageBox

from corecontrol.core.platform import IS_WINDOWS, is_admin, relaunch_as_admin, show_in_explorer
from corecontrol.i18n import tr
from corecontrol.system.autostart import list_items, set_enabled
from corecontrol.system.tools import run_tool
from corecontrol.ui.bus import on_refresh
from corecontrol.ui.dialogs import ConfirmDialog
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.common import Banner, Card, button, label
from corecontrol.ui.widgets.table import DataTable
from corecontrol.ui.workers import run_task


class AutostartPage(Page):
    page_id = "autostart"
    title_key = "auto.title"
    subtitle_key = "auto.subtitle"
    scrollable = False

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header.add_action(button("common.refresh", None, "refresh-cw", self.load))
        if IS_WINDOWS:
            self.header.add_action(button("proc.taskmgr", None, "activity", lambda: run_tool("taskmgr")))
        info = Banner("info")
        info.set_content("info", tr("auto.info_title"), tr("auto.info_text"))
        self.body.addWidget(info)
        self.table = DataTable([], stretch_col=3, min_height=200)
        self.body.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.toggle_btn = button("auto.toggle", "primary", "power", self._toggle)
        row.addWidget(self.toggle_btn)
        row.addWidget(button("proc.location", None, "folder-open", self._location))
        row.addStretch(1)
        self.status = label(None, "faint", text="", wrap=True)
        row.addWidget(self.status, 2)
        self.body.addLayout(row)
        self.body.addWidget(label("auto.limits", "faint", wrap=True))
        self.items = []
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_button())
        on_refresh(self, self._render)

    def on_show(self):
        if not self.items:
            self.load()

    def load(self):
        if not IS_WINDOWS:
            self.status.setText(tr("common.only_windows"))
            return

        def done(items):
            self.items = items
            self._render()

        run_task(list_items, on_done=done, context="autostart")

    def _render(self):
        self.table.set_headers([tr("common.name"), tr("common.status"), tr("auto.col.scope"), tr("auto.col.command")])
        rows, keys = [], []
        for i, it in enumerate(self.items):
            status = tr("common.enabled") if it.enabled else tr("common.disabled")
            scope = tr(f"auto.loc.{it.location}")
            rows.append([(it.name, it.name.lower()), (status, 0 if it.enabled else 1), (scope, scope),
                         (it.command or it.path, None)])
            keys.append(i)
        self.table.set_rows(rows, keys)
        n = sum(1 for i in self.items if i.enabled)
        self.status.setText(tr("auto.summary", enabled=n, total=len(self.items)))
        self._update_button()

    def _selected(self):
        k = self.table.selected_key()
        return self.items[k] if k is not None and k < len(self.items) else None

    def _update_button(self):
        it = self._selected()
        self.toggle_btn.setEnabled(it is not None)
        self.toggle_btn.setText(tr("auto.disable") if (it is None or it.enabled) else tr("auto.enable"))

    def _location(self):
        it = self._selected()
        if it and it.target and os.path.exists(it.target):
            show_in_explorer(it.target)

    def _toggle(self):
        it = self._selected()
        if it is None:
            return
        enable = not it.enabled
        if it.needs_admin and not is_admin():
            r = QMessageBox.question(self, tr("common.admin_required"), tr("auto.needs_admin"))
            if r == QMessageBox.StandardButton.Yes:
                relaunch_as_admin()
            return
        key = "auto.confirm_enable" if enable else "auto.confirm_disable"
        if not ConfirmDialog.ask(self, tr(f"{key}_title", name=it.name), tr(key, name=it.name),
                                 tr("auto.confirm_details", name=it.name, command=it.command or it.path,
                                    scope=tr(f"auto.loc.{it.location}")),
                                 confirm_text=tr("auto.enable" if enable else "auto.disable"), icon="rocket"):
            return
        try:
            set_enabled(it, enable)
        except PermissionError:
            QMessageBox.warning(self, tr("common.error"), tr("common.admin_required"))
            return
        except OSError as exc:
            QMessageBox.warning(self, tr("common.error"), tr("common.action_failed", error=str(exc)))
            return
        QMessageBox.information(self, tr("auto.title"), tr("auto.done_enabled" if enable else "auto.done_disabled", name=it.name))
        self._render()

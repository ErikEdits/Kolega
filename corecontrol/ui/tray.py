"""Symbol im Windows-Infobereich (neben der Uhr) mit Schnellmenü und Benachrichtigungen."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from corecontrol.i18n import tr
from corecontrol.ui.bus import bus
from corecontrol.ui.logo import app_icon


class Tray:
    def __init__(self, ctx):
        self.ctx = ctx
        self.icon: QSystemTrayIcon | None = None
        self._hidden_hint_shown = False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.icon = QSystemTrayIcon(app_icon())
        self.menu = QMenu()
        self.a_open = QAction(self.menu)
        self.a_diag = QAction(self.menu)
        self.a_mini = QAction(self.menu)
        self.a_quit = QAction(self.menu)
        self.a_open.triggered.connect(self._open)
        self.a_diag.triggered.connect(self._diagnose)
        self.a_mini.triggered.connect(self._mini)
        self.a_quit.triggered.connect(self._quit)
        self.menu.addAction(self.a_open)
        self.menu.addAction(self.a_diag)
        self.menu.addAction(self.a_mini)
        self.menu.addSeparator()
        self.menu.addAction(self.a_quit)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self.retranslate()
        bus.language_changed.connect(self.retranslate)

    def available(self) -> bool:
        return self.icon is not None and self.icon.isVisible()

    def set_enabled(self, enabled: bool) -> None:
        if self.icon is not None:
            self.icon.setVisible(enabled)

    def retranslate(self) -> None:
        if self.icon is None:
            return
        self.icon.setToolTip("CoreControl")
        self.a_open.setText(tr("tray.open"))
        self.a_diag.setText(tr("tray.diagnose"))
        self.a_mini.setText(tr("tray.mini"))
        self.a_quit.setText(tr("tray.quit"))

    def notify(self, title: str, text: str, critical: bool = False) -> None:
        if self.icon is not None and self.icon.isVisible():
            icon = QSystemTrayIcon.MessageIcon.Critical if critical else QSystemTrayIcon.MessageIcon.Warning
            self.icon.showMessage(title, text, icon, 8000)

    def notify_once_hidden(self) -> None:
        if not self._hidden_hint_shown and self.icon is not None:
            self._hidden_hint_shown = True
            self.icon.showMessage("CoreControl", tr("tray.still_running"), QSystemTrayIcon.MessageIcon.Information, 5000)

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._open()

    def _open(self) -> None:
        if self.ctx.main_window:
            self.ctx.main_window.bring_to_front()

    def _diagnose(self) -> None:
        self._open()
        bus.navigate.emit("diagnosis")
        self.ctx.run_diagnosis()

    def _mini(self) -> None:
        from corecontrol.ui.mini_monitor import toggle_mini_monitor

        toggle_mini_monitor(self.ctx)

    def _quit(self) -> None:
        if self.ctx.main_window:
            self.ctx.main_window.quit_app()

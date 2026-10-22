"""Suche nach Funktionen und Einstellungen (Kopfzeile).

Durchsucht Seiten, Einstellungsbereiche, Windows-Werkzeuge und Aktionen. Dateien werden
hier bewusst nicht durchsucht – dafür gibt es die Speicheranalyse.
"""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter, QLineEdit

from corecontrol.i18n import has, tr
from corecontrol.system.tools import TOOLS, run_action
from corecontrol.ui import icons
from corecontrol.ui.bus import bus
from corecontrol.ui.theme import theme

ACTION_ROLE = Qt.ItemDataRole.UserRole + 1
MATCH_ROLE = Qt.ItemDataRole.UserRole + 2

SETTING_SECTIONS = [
    ("appearance", "set.appearance", "palette"), ("dashboard", "set.dashboard", "layout-grid"),
    ("monitoring", "set.monitoring", "activity"), ("thresholds", "set.thresholds", "bell"),
    ("history", "set.history", "history"), ("startup", "set.startup", "power"), ("auto", "set.auto", "sparkles"),
    ("privacy", "set.privacy", "shield-check"), ("about", "set.about", "info"),
]
ACTIONS = [
    ("act:diagnose", "search.act.diagnose", "stethoscope"),
    ("nav:reports", "search.act.report", "file-text"),
    ("act:nettest", "search.act.nettest", "wifi"),
    ("nav:storage", "search.act.storage", "hard-drive"),
    ("act:mini", "search.act.mini", "maximize-2"),
    ("act:theme", "search.act.theme", "sun"),
    ("nav:settings#about", "search.act.updates", "refresh-cw"),
]


class _Filter(QSortFilterProxyModel):
    """Findet Einträge, die alle eingegebenen Wörter enthalten (Titel + Stichwörter)."""

    def __init__(self):
        super().__init__()
        self.words: list[str] = []

    def set_text(self, text: str) -> None:
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            self.words = [w for w in text.lower().split() if w]
            self.endFilterChange()
        else:
            self.words = [w for w in text.lower().split() if w]
            self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        if not self.words:
            return False
        idx = self.sourceModel().index(row, 0, parent)
        hay = str(idx.data(MATCH_ROLE) or "").lower()
        return all(w in hay for w in self.words)


class SearchBox(QLineEdit):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("search")
        self.setClearButtonEnabled(True)
        self._icon_action = self.addAction(icons.icon("search", theme.palette.text3, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.model = QStandardItemModel()
        self.proxy = _Filter()
        self.proxy.setSourceModel(self.model)
        self.completer = QCompleter(self)
        self.completer.setModel(self.proxy)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setMaxVisibleItems(9)
        self.completer.setWidget(self)
        self.completer.popup().setObjectName("searchList")
        self.completer.activated.connect(self._activated_text)
        self.textEdited.connect(self._edited)
        self.returnPressed.connect(self._enter)
        theme.changed.connect(self._retheme)
        self.retranslate()

    def _retheme(self):
        self.removeAction(self._icon_action)
        self._icon_action = self.addAction(icons.icon("search", theme.palette.text3, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.retranslate()

    def retranslate(self):
        from corecontrol.ui.main_window import NAV

        self.setPlaceholderText(tr("search.placeholder"))
        m = self.model
        m.clear()
        col = theme.palette.accent_fg

        def add(text: str, icon: str, action: str, keywords: str = ""):
            it = QStandardItem(icons.icon(icon, col, 16), text)
            it.setData(action, ACTION_ROLE)
            it.setData(f"{text} {keywords}", MATCH_ROLE)
            m.appendRow(it)

        for pid, key, icon, _ in NAV:
            sub = tr(f"search.kw.{pid}") if has(f"search.kw.{pid}") else ""
            add(tr("search.page", name=tr(key)), icon, f"nav:{pid}", sub)
        for sec, key, icon in SETTING_SECTIONS:
            add(tr("search.setting", name=tr(key)), icon, f"nav:settings#{sec}", tr("nav.settings"))
        for t in TOOLS:
            add(tr("search.tool", name=tr(f"tool.{t.id}.name")), t.icon, f"tool:{t.id}", tr(f"tool.{t.id}.desc"))
        for action, key, icon in ACTIONS:
            add(tr(key), icon, action)

    def _edited(self, text: str):
        self.proxy.set_text(text)
        if self.proxy.rowCount() > 0:
            self.completer.complete()
            self.completer.popup().setCurrentIndex(self.proxy.index(0, 0))
        else:
            self.completer.popup().hide()

    def _enter(self):
        idx = self.completer.popup().currentIndex()
        if not idx.isValid() and self.proxy.rowCount() > 0:
            idx = self.proxy.index(0, 0)
        if idx.isValid():
            self._activated_index(idx)

    def _activated_text(self, text: str):
        idx = self.completer.popup().currentIndex()
        if idx.isValid():
            self._activated_index(idx)

    def _activated_index(self, idx):
        action = idx.data(ACTION_ROLE)
        self.completer.popup().hide()
        self.clear()
        self.proxy.set_text("")
        if action:
            self.execute(action)

    def execute(self, action: str):
        kind, _, target = action.partition(":")
        if kind == "act":
            if target == "diagnose":
                bus.navigate.emit("diagnosis")
                self.ctx.run_diagnosis()
            elif target == "nettest":
                bus.navigate.emit("network")
                page = self.ctx.main_window.page("network") if self.ctx.main_window else None
                if page is not None and hasattr(page, "run_test"):
                    page.run_test()
            elif target == "mini":
                from corecontrol.ui.mini_monitor import toggle_mini_monitor

                toggle_mini_monitor(self.ctx)
            elif target == "theme":
                self.ctx.settings.set("ui.theme", "light" if theme.palette.dark else "dark")
            return
        run_action(action)


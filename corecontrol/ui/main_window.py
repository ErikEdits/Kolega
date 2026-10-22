"""Hauptfenster: Seitenleiste, Seiteninhalt und globale Warnleiste."""

from __future__ import annotations

import importlib
import logging

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from corecontrol import APP_NAME, __version__
from corecontrol.core.logging_setup import record_error
from corecontrol.i18n import tr
from corecontrol.ui.bus import bind_icon, bind_text, bus
from corecontrol.ui.logo import app_icon, render_logo
from corecontrol.ui.theme import set_dark_titlebar, theme
from corecontrol.ui.widgets.common import Banner, EmptyState, button, label, set_role

log = logging.getLogger(__name__)

# (ID, Übersetzungsschlüssel, Symbol, Modul:Klasse) – None = Abschnittsüberschrift
NAV = [
    (None, "nav.section.overview", None, None),
    ("dashboard", "nav.dashboard", "layout-dashboard", "corecontrol.ui.pages.dashboard:DashboardPage"),
    ("diagnosis", "nav.diagnosis", "stethoscope", "corecontrol.ui.pages.diagnosis:DiagnosisPage"),
    (None, "nav.section.system", None, None),
    ("monitoring", "nav.monitoring", "activity", "corecontrol.ui.pages.monitoring:MonitoringPage"),
    ("hardware", "nav.hardware", "cpu", "corecontrol.ui.pages.hardware:HardwarePage"),
    ("events", "nav.events", "scroll-text", "corecontrol.ui.pages.events:EventsPage"),
    ("history", "nav.history", "chart-line", "corecontrol.ui.pages.history:HistoryPage"),
    (None, "nav.section.maintenance", None, None),
    ("storage", "nav.storage", "hard-drive", "corecontrol.ui.pages.storage:StoragePage"),
    ("processes", "nav.processes", "list", "corecontrol.ui.pages.processes:ProcessesPage"),
    ("autostart", "nav.autostart", "rocket", "corecontrol.ui.pages.autostart:AutostartPage"),
    ("programs", "nav.programs", "package", "corecontrol.ui.pages.programs:ProgramsPage"),
    (None, "nav.section.more", None, None),
    ("network", "nav.network", "wifi", "corecontrol.ui.pages.network:NetworkPage"),
    ("gaming", "nav.gaming", "gamepad-2", "corecontrol.ui.pages.gaming:GamingPage"),
    ("reports", "nav.reports", "file-text", "corecontrol.ui.pages.reports:ReportsPage"),
]
NAV_BOTTOM = [("settings", "nav.settings", "settings", "corecontrol.ui.pages.settings:SettingsPage")]

COMPACT_WIDTH = 1020


class ErrorPage(QWidget):
    """Wird angezeigt, wenn eine Seite nicht geladen werden konnte – die App läuft weiter."""

    def __init__(self, page_id: str, exc: BaseException):
        super().__init__()
        self.setObjectName("pageRoot")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.addStretch(1)
        lay.addWidget(EmptyState("circle-alert", "error.page_failed.title", "error.page_failed.text"))
        details = QLabel(f"{page_id}: {type(exc).__name__}: {exc}")
        set_role(details, "faint")
        details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        details.setWordWrap(True)
        lay.addWidget(details)
        btn = button("error.open_reports", "primary", "file-text", lambda: bus.navigate.emit("reports"))
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(2)
        self.page_id = page_id

    def on_show(self):
        pass

    def on_hide(self):
        pass

    def on_sample(self, _):
        pass


class Sidebar(QFrame):
    def __init__(self, on_select):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(232)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 16, 0, 12)
        lay.setSpacing(0)

        brand = QHBoxLayout()
        brand.setContentsMargins(18, 0, 14, 10)
        brand.setSpacing(10)
        self.logo = QLabel()
        self.logo.setPixmap(render_logo(30))
        brand.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.app_name = QLabel(APP_NAME)
        self.app_name.setObjectName("appName")
        self.app_tag = QLabel()
        self.app_tag.setObjectName("appTag")
        bind_text(self.app_tag, "app.tagline")
        names.addWidget(self.app_name)
        names.addWidget(self.app_tag)
        brand.addLayout(names, 1)
        lay.addLayout(brand)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        self.sections: list[QLabel] = []
        self.texts: dict[str, str] = {}
        for pid, key, icon, _ in NAV:
            if pid is None:
                sec = QLabel()
                bind_text(sec, key)
                sec.setProperty("role", "navSection")
                self.sections.append(sec)
                lay.addWidget(sec)
            else:
                lay.addWidget(self._make_btn(pid, key, icon, on_select))
        lay.addStretch(1)
        for pid, key, icon, _ in NAV_BOTTOM:
            lay.addWidget(self._make_btn(pid, key, icon, on_select))
        self.version = QLabel(f"v{__version__}")
        self.version.setObjectName("appTag")
        self.version.setContentsMargins(20, 8, 0, 0)
        lay.addWidget(self.version)
        self.compact = False

    def _make_btn(self, pid, key, icon, on_select) -> QToolButton:
        b = QToolButton()
        b.setProperty("role", "nav")
        b.setCheckable(True)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.setMinimumHeight(36)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_icon(b, icon, "text2", 18)
        bind_text(b, key)
        bind_text(b, key, "setToolTip")
        b.clicked.connect(lambda *_: on_select(pid))
        self.group.addButton(b)
        self.buttons[pid] = b
        self.texts[pid] = key
        return b

    def select(self, pid: str) -> None:
        if pid in self.buttons:
            self.buttons[pid].setChecked(True)

    def set_compact(self, compact: bool) -> None:
        if compact == self.compact:
            return
        self.compact = compact
        self.setFixedWidth(64 if compact else 232)
        for b in self.buttons.values():
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for s in self.sections:
            s.setVisible(not compact)
        self.app_name.setVisible(not compact)
        self.app_tag.setVisible(not compact)
        self.version.setVisible(not compact)


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        ctx.main_window = self
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(760, 560)
        self.resize(1320, 840)
        self._pages: dict[str, QWidget] = {}
        self._current: str | None = None
        self._quitting = False

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = Sidebar(self.navigate)
        root.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.banner_wrap = QWidget()
        bw = QVBoxLayout(self.banner_wrap)
        bw.setContentsMargins(32, 14, 32, 0)
        self.banner = Banner("critical", closable=True)
        self.banner.action_clicked.connect(self._banner_action)
        bw.addWidget(self.banner)
        self.banner_wrap.setVisible(False)
        self.banner_wrap.setObjectName("pageRoot")
        self._banner_target = "diagnosis"
        self.banner.closed.connect(lambda: self.banner_wrap.setVisible(False))
        right.addWidget(self.banner_wrap)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        root.addLayout(right, 1)
        self.setCentralWidget(central)

        bus.navigate.connect(self.navigate)
        if ctx.sampler is not None:
            ctx.sampler.sampled.connect(self._on_sample)
        geom = ctx.settings.get("ui.window_geometry")
        if geom:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geom.encode()))
            except Exception:
                pass
        theme.changed.connect(lambda: set_dark_titlebar(self, theme.palette.dark))
        self.navigate("dashboard")

    # ---- Navigation --------------------------------------------------------
    def page(self, pid: str) -> QWidget | None:
        if pid in self._pages:
            return self._pages[pid]
        spec = next((n for n in NAV + NAV_BOTTOM if n[0] == pid), None)
        if spec is None:
            return None
        mod_name, cls_name = spec[3].split(":")
        try:
            mod = importlib.import_module(mod_name)
            page = getattr(mod, cls_name)(self.ctx)
        except Exception as exc:
            record_error(f"page:{pid}", exc)
            page = ErrorPage(pid, exc)
        self._pages[pid] = page
        self.stack.addWidget(page)
        return page

    def navigate(self, pid: str) -> None:
        page = self.page(pid)
        if page is None:
            return
        if self._current and self._current in self._pages and self._current != pid:
            try:
                self._pages[self._current].on_hide()
            except Exception as exc:
                record_error(f"page:{self._current}:hide", exc)
        self._current = pid
        self.stack.setCurrentWidget(page)
        self.sidebar.select(pid)
        try:
            page.on_show()
        except Exception as exc:
            record_error(f"page:{pid}:show", exc)

    def current_page_id(self) -> str | None:
        return self._current

    def _on_sample(self, s) -> None:
        if not self.isVisible() or self.isMinimized():
            return
        page = self._pages.get(self._current or "")
        if page is not None:
            try:
                page.on_sample(s)
            except Exception as exc:
                record_error(f"page:{self._current}:sample", exc)

    # ---- Warnleiste --------------------------------------------------------
    def show_banner(self, level: str, title: str, text: str, action: str | None, target: str = "diagnosis") -> None:
        self._banner_target = target
        self.banner.set_content(level, title, text, action)
        self.banner.setVisible(True)
        self.banner_wrap.setVisible(True)

    def hide_banner(self) -> None:
        self.banner_wrap.setVisible(False)

    def _banner_action(self) -> None:
        self.navigate(self._banner_target)

    # ---- Fenster -----------------------------------------------------------
    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self.sidebar.set_compact(self.width() < COMPACT_WIDTH)

    def changeEvent(self, ev) -> None:
        super().changeEvent(ev)
        if ev.type() == ev.Type.WindowStateChange:
            minimized = self.isMinimized()
            self._update_sampling(not minimized)
            if minimized and self.ctx.tray is not None and self.ctx.tray.available() and \
                    self.ctx.settings.get("tray.minimize_to_tray"):
                QTimer.singleShot(0, self.hide)

    def _update_sampling(self, visible: bool) -> None:
        if self.ctx.sampler is None:
            return
        key = "monitor.interval_ms" if visible else "monitor.background_interval_ms"
        self.ctx.sampler.set_interval(self.ctx.settings.get(key))

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        set_dark_titlebar(self, theme.palette.dark)
        self._update_sampling(True)

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self._update_sampling(False)

    def bring_to_front(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, ev: QCloseEvent) -> None:
        self.ctx.settings.set("ui.window_geometry", bytes(self.saveGeometry().toBase64()).decode())
        if (not self._quitting and self.ctx.tray is not None and self.ctx.tray.available()
                and self.ctx.settings.get("tray.close_to_tray")):
            ev.ignore()
            self.hide()
            self.ctx.tray.notify_once_hidden()
            return
        for p in self._pages.values():
            try:
                p.on_hide()
            except Exception:
                pass
        ev.accept()
        from PySide6.QtWidgets import QApplication

        QApplication.instance().quit()

"""Hauptfenster: Hintergrund mit Lichtakzenten, Seitenleiste mit Statuskarte, Kopfzeile
(Suche, Hell/Dunkel, Sprache), Warnleiste und Seiteninhalt mit weichen Übergängen."""

from __future__ import annotations

import importlib
import logging

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from corecontrol import APP_NAME, __version__
from corecontrol.core.logging_setup import record_error
from corecontrol.i18n import tr
from corecontrol.ui import anim
from corecontrol.ui.bus import bind_text, bus, on_refresh
from corecontrol.ui.logo import app_icon, render_logo
from corecontrol.ui.theme import render_background, set_dark_titlebar, theme
from corecontrol.ui.widgets.common import Banner, EmptyState, button, set_role
from corecontrol.ui.widgets.controls import AnimatedButton, NavButton, flag_pixmap

log = logging.getLogger(__name__)

# (ID, Übersetzungsschlüssel, Symbol, Modul:Klasse) – None = Abstand zwischen Gruppen
NAV = [
    ("dashboard", "nav.dashboard", "house", "corecontrol.ui.pages.dashboard:DashboardPage"),
    ("diagnosis", "nav.diagnosis", "stethoscope", "corecontrol.ui.pages.diagnosis:DiagnosisPage"),
    ("hardware", "nav.hardware", "cpu", "corecontrol.ui.pages.hardware:HardwarePage"),
    ("monitoring", "nav.monitoring", "thermometer", "corecontrol.ui.pages.monitoring:MonitoringPage"),
    ("processes", "nav.processes", "list", "corecontrol.ui.pages.processes:ProcessesPage"),
    ("autostart", "nav.autostart", "power", "corecontrol.ui.pages.autostart:AutostartPage"),
    ("programs", "nav.programs", "package", "corecontrol.ui.pages.programs:ProgramsPage"),
    ("storage", "nav.storage", "hard-drive", "corecontrol.ui.pages.storage:StoragePage"),
    ("network", "nav.network", "wifi", "corecontrol.ui.pages.network:NetworkPage"),
    ("events", "nav.events", "scroll-text", "corecontrol.ui.pages.events:EventsPage"),
    ("history", "nav.history", "history", "corecontrol.ui.pages.history:HistoryPage"),
    ("gaming", "nav.gaming", "gamepad-2", "corecontrol.ui.pages.gaming:GamingPage"),
    ("reports", "nav.reports", "file-text", "corecontrol.ui.pages.reports:ReportsPage"),
    ("settings", "nav.settings", "settings", "corecontrol.ui.pages.settings:SettingsPage"),
]
NAV_BOTTOM: list = []

COMPACT_WIDTH = 1060


class Background(QWidget):
    """Zeichnet den Fensterhintergrund aus einem zwischengespeicherten Bild."""

    def __init__(self):
        super().__init__()
        self._pm: QPixmap | None = None
        theme.changed.connect(self._invalidate)

    def _invalidate(self):
        self._pm = None
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._pm = None

    def paintEvent(self, ev):
        if self._pm is None or self._pm.size() != self.size():
            self._pm = render_background(self.width(), self.height(), theme.palette)
        qp = QPainter(self)
        qp.drawPixmap(ev.rect(), self._pm, ev.rect())
        qp.end()


class TransitionStack(QStackedWidget):
    """Seitenwechsel mit kurzer Überblendung und leichtem Gleiten (ca. 260 ms).
    Die bisherige (fertig gezeichnete) Seite wird als Bild ausgeblendet, die neue Seite
    gleitet darunter an ihren Platz. So wird nie eine noch nicht angezeigte Seite abfotografiert."""

    def __init__(self):
        super().__init__()
        self._overlay: _TransitionOverlay | None = None

    def switch_to(self, page: QWidget) -> None:
        old = self.currentWidget()
        if old is None or old is page or not anim.allow("transition") or not self.isVisible() or not old.isVisible():
            self.setCurrentWidget(page)
            return
        if self._overlay is not None:
            self._overlay.finish()
        old_pm = old.grab()
        self.setCurrentWidget(page)
        self._overlay = _TransitionOverlay(self, old_pm, page)
        self._overlay.finished = lambda: setattr(self, "_overlay", None)


class _TransitionOverlay(QWidget):
    SLIDE = 16

    def __init__(self, parent: QWidget, old: QPixmap, page: QWidget):
        super().__init__(parent)
        self.old, self.page = old, page
        self.t = 0.0
        self.finished = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())
        self.page.move(0, self.SLIDE)
        self.show()
        self.raise_()
        anim.ticker().add(self, self._tick)

    def _tick(self, dt: float) -> bool:
        self.t = min(1.0, self.t + dt / 0.26)
        e = 1 - (1 - self.t) ** 3
        try:
            self.page.move(0, round(self.SLIDE * (1 - e)))
        except RuntimeError:
            pass
        self.update()
        if self.t >= 1.0:
            QTimer.singleShot(0, self.finish)
            return False
        return True

    def finish(self):
        anim.ticker().remove(self)
        try:
            self.page.move(0, 0)
        except RuntimeError:
            pass
        if self.finished:
            self.finished()
            self.finished = None
        self.hide()
        self.deleteLater()

    def paintEvent(self, _):
        e = 1 - (1 - self.t) ** 3
        if e >= 1:
            return
        qp = QPainter(self)
        qp.setOpacity(1 - e)
        qp.drawPixmap(QPointF(0, -8 * e), self.old)
        qp.end()


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


class StatusCard(QFrame):
    """Karte unten in der Seitenleiste: Ergebnis der letzten Diagnose (anklickbar)."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("statusCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(12)
        self.dot = QLabel()
        self.dot.setFixedSize(18, 18)
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.title.setWordWrap(True)
        self.sub = QLabel()
        set_role(self.sub, "faint")
        self.sub.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        lay.addLayout(col, 1)
        ctx.diagnosis_started.connect(self.refresh)
        ctx.diagnosis_finished.connect(lambda *_: self.refresh())
        on_refresh(self, self.refresh)
        self.refresh()

    def mouseReleaseEvent(self, ev):
        bus.navigate.emit("diagnosis")
        super().mouseReleaseEvent(ev)

    def refresh(self):
        p = theme.palette
        res = self.ctx.diagnosis_result
        if self.ctx.diagnosis_running:
            role, t, s = "info", tr("status.running"), tr("status.running_sub")
        elif res is None:
            role, t, s = "text3", tr("status.none"), tr("status.none_sub")
        elif res.count("critical"):
            role, t, s = "crit", tr("status.crit", n=res.count("critical")), tr("status.details")
        elif res.count("warning"):
            role, t, s = "warn", tr("status.warn", n=res.count("warning")), tr("status.details")
        else:
            role, t, s = "ok", tr("status.ok"), tr("status.ok_sub")
        self.title.setText(t)
        self.sub.setText(s)
        pm = QPixmap(18, 18)
        pm.fill(Qt.GlobalColor.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(p.color(role))
        glow = QColor(c)
        glow.setAlphaF(0.30)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(glow)
        qp.drawEllipse(QRectF(1, 1, 16, 16))
        qp.setBrush(c)
        qp.drawEllipse(QRectF(5, 5, 8, 8))
        qp.end()
        self.dot.setPixmap(pm)


class Sidebar(QFrame):
    def __init__(self, ctx, on_select):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(262)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 18, 0, 14)
        lay.setSpacing(6)

        brand = QHBoxLayout()
        brand.setContentsMargins(22, 0, 14, 14)
        brand.setSpacing(12)
        self.logo = QLabel()
        self.logo.setPixmap(render_logo(36))
        brand.addWidget(self.logo)
        self.app_name = QLabel(APP_NAME)
        self.app_name.setObjectName("appName")
        brand.addWidget(self.app_name, 1)
        lay.addLayout(brand)

        nav_host = QWidget()
        nav_host.setObjectName("pageRoot")
        nl = QVBoxLayout(nav_host)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, NavButton] = {}
        for pid, key, icon, _ in NAV:
            b = NavButton(icon)
            bind_text(b, key)
            bind_text(b, key, "setToolTip")
            b.clicked.connect(lambda *_, p=pid: on_select(p))
            self.group.addButton(b)
            self.buttons[pid] = b
            nl.addWidget(b)
        nl.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("navScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(nav_host)
        lay.addWidget(scroll, 1)

        self.status = StatusCard(ctx)
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(16, 6, 16, 0)
        sl.addWidget(self.status)
        lay.addWidget(sw)
        self.version = QLabel(f"{APP_NAME} v{__version__}")
        self.version.setObjectName("appTag")
        self.version.setContentsMargins(24, 6, 0, 0)
        lay.addWidget(self.version)
        self.compact = False

    def select(self, pid: str) -> None:
        if pid in self.buttons:
            self.buttons[pid].setChecked(True)

    def set_compact(self, compact: bool) -> None:
        if compact == self.compact:
            return
        self.compact = compact
        self.setFixedWidth(78 if compact else 262)
        for b in self.buttons.values():
            b.compact = compact
            b.update()
        self.app_name.setVisible(not compact)
        self.status.setVisible(not compact)
        self.version.setVisible(not compact)


class TopBar(QWidget):
    """Suche, Hell/Dunkel-Umschalter und Sprachauswahl."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("topBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(32, 16, 32, 0)
        lay.setSpacing(10)
        from corecontrol.ui.search import SearchBox

        self.search = SearchBox(ctx)
        self.search.setMaximumWidth(560)
        self.search.setMinimumWidth(220)
        lay.addWidget(self.search, 1)
        lay.addStretch(0)
        self.theme_btn = AnimatedButton()
        self.theme_btn.setIconSize(QSize(18, 18))
        self.theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self.theme_btn)
        self.lang = QComboBox()
        self.lang.setMinimumWidth(130)
        self.lang.setIconSize(QSize(20, 14))
        self.lang.addItem(flag_pixmap("de"), "Deutsch", "de")
        self.lang.addItem(flag_pixmap("en"), "English", "en")
        self.lang.currentIndexChanged.connect(lambda *_: ctx.settings.set("ui.language", self.lang.currentData()))
        lay.addWidget(self.lang)
        theme.changed.connect(self._sync)
        bus.language_changed.connect(self._sync)
        self._sync()

    def _toggle_theme(self):
        self.ctx.settings.set("ui.theme", "light" if theme.palette.dark else "dark")

    def _sync(self):
        from corecontrol import i18n
        from corecontrol.ui import icons

        dark = theme.palette.dark
        self.theme_btn.setIcon(icons.icon("sun" if dark else "moon", theme.palette.text, 18))
        self.theme_btn.setToolTip(tr("top.light" if dark else "top.dark"))
        self.lang.blockSignals(True)
        self.lang.setCurrentIndex(max(0, self.lang.findData(i18n.current_language())))
        self.lang.blockSignals(False)
        self.search.retranslate()


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        ctx.main_window = self
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(820, 600)
        self.resize(1440, 920)
        self._pages: dict[str, QWidget] = {}
        self._current: str | None = None
        self._quitting = False

        central = Background()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = Sidebar(ctx, self.navigate)
        root.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.topbar = TopBar(ctx)
        right.addWidget(self.topbar)
        self.banner_wrap = QWidget()
        self.banner_wrap.setObjectName("pageRoot")
        bw = QVBoxLayout(self.banner_wrap)
        bw.setContentsMargins(32, 14, 32, 0)
        self.banner = Banner("critical", closable=True)
        self.banner.action_clicked.connect(self._banner_action)
        bw.addWidget(self.banner)
        self.banner_wrap.setVisible(False)
        self._banner_target = "diagnosis"
        self.banner.closed.connect(lambda: self.banner_wrap.setVisible(False))
        right.addWidget(self.banner_wrap)
        self.stack = TransitionStack()
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
        spec = next((n for n in NAV if n[0] == pid), None)
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
        target, _, section = pid.partition("#")
        page = self.page(target)
        if page is None:
            return
        if self._current and self._current in self._pages and self._current != target:
            try:
                self._pages[self._current].on_hide()
            except Exception as exc:
                record_error(f"page:{self._current}:hide", exc)
        self._current = target
        try:
            page.on_show()
        except Exception as exc:
            record_error(f"page:{target}:show", exc)
        self.stack.switch_to(page)
        self.sidebar.select(target)
        if section and hasattr(page, "scroll_to"):
            QTimer.singleShot(300, lambda: page.scroll_to(section))

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
        was_visible = self.banner_wrap.isVisible()
        self.banner.setVisible(True)
        self.banner_wrap.setVisible(True)
        if not was_visible:
            anim.fade_in(self.banner, 260)

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

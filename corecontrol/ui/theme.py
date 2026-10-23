"""Farben, Schriften und Stylesheet: dunkles „Midnight“-Design mit Lichtakzenten und heller Modus.

Farben mit Transparenz werden als #AARRGGBB gespeichert (versteht QColor) und für das
Stylesheet in rgba(...) umgewandelt. Der Fensterhintergrund (Verlauf + weiche Lichtflecken)
wird einmal pro Größenänderung in ein Bild gezeichnet und danach nur noch kopiert.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication

from corecontrol.core.platform import IS_WINDOWS

log = logging.getLogger(__name__)

ACCENT_PRESETS = [
    "#2f7bff",  # Blau (Standard)
    "#06b6d4",  # Cyan
    "#22c55e",  # Grün
    "#8b5cf6",  # Violett
    "#ec4899",  # Pink
    "#f97316",  # Orange
    "#eab308",  # Gold
    "#64748b",  # Schiefer
]
DEFAULT_ACCENT = "#2f7bff"


@dataclass(frozen=True)
class Palette:
    dark: bool
    bg: str
    bg2: str
    glow1: str
    glow2: str
    sidebar: str
    surface: str
    surface2: str
    surface3: str
    border: str
    border_hi: str
    text: str
    text2: str
    text3: str
    ok: str
    warn: str
    crit: str
    info: str
    cat_cpu: str = "#3b82f6"
    cat_gpu: str = "#a855f7"
    cat_ram: str = "#22c55e"
    cat_storage: str = "#06b6d4"
    cat_net: str = "#38bdf8"
    cat_temp: str = "#f97316"
    accent: str = DEFAULT_ACCENT
    accent2: str = "#22d3ee"
    accent_hover: str = "#4a8dff"
    accent_pressed: str = "#2563eb"
    accent_text: str = "#ffffff"
    accent_soft: str = "#332f7bff"
    accent_fg: str = DEFAULT_ACCENT

    def color(self, role: str) -> str:
        return getattr(self, role)

    def qcolor(self, role: str, alpha: float | None = None) -> QColor:
        c = QColor(role if role.startswith("#") else self.color(role))
        if alpha is not None:
            c.setAlphaF(alpha)
        return c

    def soft(self, role: str, alpha: float = 0.14) -> str:
        c = QColor(self.color(role))
        return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


DARK = Palette(
    dark=True,
    bg="#080d1c",
    bg2="#0c1230",
    glow1="#2e3b82f6",   # Blau, links unten
    glow2="#2a8b5cf6",   # Violett, rechts oben
    sidebar="#b3060a18",
    surface="#c4111a36",
    surface2="#a01a2548",
    surface3="#c0263460",
    border="#2e7896ff",
    border_hi="#5a7896ff",
    text="#eef2ff",
    text2="#a3add0",
    text3="#6c779c",
    ok="#34d399",
    warn="#fbbf24",
    crit="#f87171",
    info="#60a5fa",
)

LIGHT = Palette(
    dark=False,
    bg="#eef2fb",
    bg2="#f7f8fd",
    glow1="#223b82f6",
    glow2="#1e8b5cf6",
    sidebar="#c0ffffff",
    surface="#e6ffffff",
    surface2="#f0eef2fa",
    surface3="#ffe3e8f4",
    border="#1f1e3a8a",
    border_hi="#4d2f6bff",
    text="#0f172a",
    text2="#475069",
    text3="#7b84a0",
    ok="#059669",
    warn="#b45309",
    crit="#dc2626",
    info="#2563eb",
    cat_cpu="#2563eb",
    cat_gpu="#9333ea",
    cat_ram="#16a34a",
    cat_storage="#0891b2",
    cat_net="#0284c7",
    cat_temp="#ea580c",
)


def css(value: str) -> str:
    """#AARRGGBB → rgba(...) für Stylesheets; andere Werte unverändert."""
    if isinstance(value, str) and value.startswith("#") and len(value) == 9:
        c = QColor(value)
        return f"rgba({c.red()},{c.green()},{c.blue()},{c.alphaF():.3f})"
    return value


def _luminance(c: QColor) -> float:
    def ch(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def _contrast(a: QColor, b: QColor) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _mix(c: QColor, other: QColor, t: float) -> QColor:
    return QColor(
        round(c.red() + (other.red() - c.red()) * t),
        round(c.green() + (other.green() - c.green()) * t),
        round(c.blue() + (other.blue() - c.blue()) * t),
    )


def with_accent(base: Palette, accent_hex: str) -> Palette:
    a = QColor(accent_hex)
    if not a.isValid():
        a = QColor(DEFAULT_ACCENT)
    white, black = QColor("#ffffff"), QColor("#000000")
    accent_text = "#ffffff" if _contrast(a, white) >= 2.6 else "#0b1020"
    # Zweite Verlaufsfarbe: Farbton leicht verschoben und heller (für Verläufe und Lichtakzente)
    h, s, v, _ = a.getHsvF()
    a2 = QColor.fromHsvF((h + 0.06) % 1.0 if h >= 0 else 0.0, max(0.0, s * 0.85), min(1.0, v * 1.1 + 0.05))
    bg = QColor(base.bg)
    fg = QColor(a)
    for _ in range(12):
        if _contrast(fg, bg) >= 3.4:
            break
        fg = _mix(fg, white if base.dark else black, 0.15)
    soft = QColor(a)
    soft.setAlphaF(0.22 if base.dark else 0.14)
    return replace(
        base,
        accent=a.name(),
        accent2=a2.name(),
        accent_hover=_mix(a, white, 0.15).name(),
        accent_pressed=_mix(a, black, 0.18).name(),
        accent_text=accent_text,
        accent_soft=soft.name(QColor.NameFormat.HexArgb),
        accent_fg=fg.name(),
    )


def windows_accent() -> str | None:
    if not IS_WINDOWS:
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
            val, _ = winreg.QueryValueEx(k, "AccentColor")
        val = int(val) & 0xFFFFFFFF
        r, g, b = val & 0xFF, (val >> 8) & 0xFF, (val >> 16) & 0xFF
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return None


def system_prefers_dark() -> bool:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception:
        pass
    if IS_WINDOWS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                val, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return int(val) == 0
        except Exception:
            pass
    return True


def pick_font_family() -> str:
    families = set(QFontDatabase.families())
    for fam in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"):
        if fam in families:
            return fam
    return QApplication.font().family()


def render_background(w: int, h: int, p: Palette) -> QPixmap:
    """Hintergrundverlauf mit zwei weichen Lichtflecken (wird zwischengespeichert)."""
    pm = QPixmap(max(1, w), max(1, h))
    qp = QPainter(pm)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(p.bg))
    grad.setColorAt(1, QColor(p.bg2))
    qp.fillRect(pm.rect(), grad)
    for center, radius, color in ((QPointF(w * 0.12, h * 0.95), max(w, h) * 0.55, p.glow1),
                                  (QPointF(w * 0.92, h * 0.05), max(w, h) * 0.50, p.glow2)):
        rg = QRadialGradient(center, radius)
        c = QColor(color)
        rg.setColorAt(0, c)
        c2 = QColor(c)
        c2.setAlpha(0)
        rg.setColorAt(1, c2)
        qp.fillRect(pm.rect(), rg)
    qp.end()
    return pm


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.palette: Palette = with_accent(DARK, DEFAULT_ACCENT)
        self.font_family = "Segoe UI"
        self.mode = "system"
        self.accent_setting = DEFAULT_ACCENT

    def resolved_accent(self) -> str:
        if self.accent_setting == "windows":
            return windows_accent() or DEFAULT_ACCENT
        return self.accent_setting

    def apply(self, mode: str, accent: str) -> None:
        self.mode, self.accent_setting = mode, accent
        dark = system_prefers_dark() if mode == "system" else mode == "dark"
        self.palette = with_accent(DARK if dark else LIGHT, self.resolved_accent())
        app = QApplication.instance()
        if app is None:
            return
        self.font_family = pick_font_family()
        font = QFont(self.font_family, 10)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        app.setFont(font)
        app.setPalette(self._qpalette())
        app.setStyleSheet(build_stylesheet(self.palette, self.font_family))
        for w in app.topLevelWidgets():
            set_dark_titlebar(w, self.palette.dark)
        self.changed.emit()

    def _qpalette(self) -> QPalette:
        p = self.palette
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(p.bg))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(p.text))
        pal.setColor(QPalette.ColorRole.Base, QColor(p.bg2) if p.dark else QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(p.surface2))
        pal.setColor(QPalette.ColorRole.Text, QColor(p.text))
        pal.setColor(QPalette.ColorRole.Button, QColor(p.surface2))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(p.accent_text))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.bg2))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(p.text))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text3))
        pal.setColor(QPalette.ColorRole.Link, QColor(p.accent_fg))
        return pal


theme = ThemeManager()


def set_dark_titlebar(widget, dark: bool) -> None:
    """Titelleiste an das Design anpassen: dunkler Modus (Windows 10/11) und – unter
    Windows 11 – Titelleistenfarbe = Hintergrundfarbe, damit sie nahtlos wirkt."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (neu / alt)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        bg = QColor(theme.palette.bg)
        text = QColor(theme.palette.text)
        caption = ctypes.c_uint(bg.red() | (bg.green() << 8) | (bg.blue() << 16))
        txt = ctypes.c_uint(text.red() | (text.green() << 8) | (text.blue() << 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))  # DWMWA_CAPTION_COLOR
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt), ctypes.sizeof(txt))  # DWMWA_TEXT_COLOR
    except Exception:
        pass


def _cached_svg(name: str, color: str, svg: str | None = None) -> str:
    """Schreibt ein eingefärbtes Symbol in den Cache und gibt den Pfad für Stylesheets zurück."""
    from corecontrol.core import paths
    from corecontrol.core.platform import resource_path

    color = QColor(color).name()
    d = paths.data_dir() / "cache"
    try:
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{name}_{color.strip('#')}.svg"
        if not f.exists():
            if svg is None:
                with open(resource_path("assets", "icons", f"{name}.svg"), encoding="utf-8") as fh:
                    svg = fh.read()
            f.write_text(svg.replace("currentColor", color), encoding="utf-8")
        return f.as_posix()
    except OSError:
        return ""


CHECK_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
             'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>')


def build_stylesheet(p: Palette, font: str) -> str:
    c = css
    check = _cached_svg("check", p.accent_text, CHECK_SVG)
    down = _cached_svg("chevron-down", p.text2)
    up = _cached_svg("chevron-up", p.text2)
    popup_bg = QColor(p.bg2).lighter(125).name() if p.dark else "#ffffff"
    return f"""
* {{ font-family: "{font}"; }}
QWidget {{ color: {p.text}; }}
QMainWindow, QDialog {{ background: {p.bg}; }}
#pageRoot, QStackedWidget, #topBar, #contentArea {{ background: transparent; }}
QToolTip {{ background: {popup_bg}; color: {p.text}; border: 1px solid {c(p.border_hi)}; padding: 6px 9px; border-radius: 8px; }}

/* ---------- Seitenleiste ---------- */
#sidebar {{ background: {c(p.sidebar)}; border-right: 1px solid {c(p.border)}; }}
#sidebar QLabel#appName {{ font-size: 19px; font-weight: 700; color: {p.text}; }}
#sidebar QLabel#appTag {{ font-size: 11px; color: {p.text3}; }}
QScrollArea#navScroll, QScrollArea#navScroll > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame#statusCard {{ background: {c(p.surface2)}; border: 1px solid {c(p.border)}; border-radius: 12px; }}

/* ---------- Kopfzeile ---------- */
QLineEdit#search {{ background: {c(p.surface2)}; border: 1px solid {c(p.border)}; border-radius: 14px; padding: 8px 14px 8px 38px; font-size: 13px; }}
QLineEdit#search:focus {{ border: 1px solid {p.accent}; }}
QFrame#searchPopup {{ background: {popup_bg}; border: 1px solid {c(p.border_hi)}; border-radius: 12px; }}
QListWidget#searchList {{ background: transparent; border: none; padding: 4px; }}
QListWidget#searchList::item {{ padding: 8px 10px; border-radius: 8px; }}
QListWidget#searchList::item:selected {{ background: {c(p.accent_soft)}; color: {p.text}; }}
QFrame[role="headTile"] {{ background: {c(p.surface)}; border: 1px solid {c(p.border)}; border-radius: 14px; }}

/* ---------- Texte ---------- */
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 27px; font-weight: 700; color: {p.text}; }}
QLabel[role="h2"] {{ font-size: 16px; font-weight: 600; color: {p.text}; }}
QLabel[role="h3"] {{ font-size: 13px; font-weight: 600; color: {p.text}; }}
QLabel[role="subtitle"] {{ font-size: 14px; color: {p.text2}; }}
QLabel[role="muted"] {{ color: {p.text2}; }}
QLabel[role="faint"] {{ color: {p.text3}; font-size: 12px; }}
QLabel[role="caption"] {{ color: {p.text3}; font-size: 11px; font-weight: 600; letter-spacing: 0.3px; }}
QLabel[role="bigValue"] {{ font-size: 30px; font-weight: 650; color: {p.text}; }}
QLabel[role="midValue"] {{ font-size: 20px; font-weight: 600; color: {p.text}; }}
QLabel[role="statValue"] {{ font-size: 17px; font-weight: 600; color: {p.text}; }}
QLabel[role="ok"] {{ color: {p.ok}; }}
QLabel[role="warn"] {{ color: {p.warn}; }}
QLabel[role="crit"] {{ color: {p.crit}; }}
QLabel[role="info"] {{ color: {p.info}; }}
QLabel[role="link"] {{ color: {p.accent_fg}; }}

/* ---------- Karten ---------- */
QFrame[role="card"], QFrame[role="tile"] {{ background: {c(p.surface)}; border: 1px solid {c(p.border)}; border-radius: 16px; }}
QFrame[role="cardFlat"] {{ background: {c(p.surface2)}; border: none; border-radius: 12px; }}
QFrame[role="actionRow"] {{ background: {c(p.surface2)}; border: 1px solid {c(p.border)}; border-radius: 12px; }}
QFrame[role="separator"] {{ background: {c(p.border)}; max-height: 1px; min-height: 1px; border: none; }}
QFrame[role="banner"] {{ border-radius: 12px; border: 1px solid transparent; }}
QFrame[role="banner"][level="critical"] {{ background: {p.soft("crit", 0.14)}; border-color: {p.soft("crit", 0.40)}; }}
QFrame[role="banner"][level="warning"] {{ background: {p.soft("warn", 0.12)}; border-color: {p.soft("warn", 0.38)}; }}
QFrame[role="banner"][level="info"] {{ background: {p.soft("info", 0.12)}; border-color: {p.soft("info", 0.32)}; }}
QFrame[role="banner"][level="ok"] {{ background: {p.soft("ok", 0.12)}; border-color: {p.soft("ok", 0.32)}; }}
QFrame[role="finding"] {{ background: {c(p.surface)}; border: 1px solid {c(p.border)}; border-radius: 14px; }}
QFrame[role="finding"][level="critical"] {{ border-left: 4px solid {p.crit}; }}
QFrame[role="finding"][level="warning"] {{ border-left: 4px solid {p.warn}; }}
QFrame[role="finding"][level="info"] {{ border-left: 4px solid {p.info}; }}
QFrame[role="finding"][level="ok"] {{ border-left: 4px solid {p.ok}; }}
QLabel[role="chip"] {{ border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600; }}
QLabel[role="chip"][level="critical"] {{ background: {p.soft("crit", 0.18)}; color: {p.crit}; }}
QLabel[role="chip"][level="warning"] {{ background: {p.soft("warn", 0.18)}; color: {p.warn}; }}
QLabel[role="chip"][level="info"] {{ background: {p.soft("info", 0.16)}; color: {p.info}; }}
QLabel[role="chip"][level="ok"] {{ background: {p.soft("ok", 0.16)}; color: {p.ok}; }}
QLabel[role="chip"][level="neutral"] {{ background: {c(p.surface2)}; color: {p.text2}; }}

/* ---------- Standard-Schaltflächen (Dialoge); eigene Schaltflächen zeichnen sich selbst ---------- */
QPushButton {{ background: {c(p.surface2)}; color: {p.text}; border: 1px solid {c(p.border)}; border-radius: 10px; padding: 7px 16px; }}
QPushButton:hover {{ background: {c(p.surface3)}; border-color: {c(p.border_hi)}; }}
QPushButton:default {{ border-color: {p.accent}; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 4px; }}
QToolButton:hover {{ background: {c(p.surface2)}; }}
QToolButton[role="swatch"] {{ border-radius: 14px; border: 2px solid transparent; }}
QToolButton[role="swatch"]:checked {{ border: 2px solid {p.text}; }}

/* ---------- Eingaben ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {c(p.surface2)}; border: 1px solid {c(p.border)}; border-radius: 10px; padding: 6px 10px;
    selection-background-color: {p.accent}; selection-color: {p.accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {popup_bg}; border: 1px solid {c(p.border_hi)}; selection-background-color: {c(p.accent_soft)};
    selection-color: {p.text}; outline: none; padding: 4px; border-radius: 8px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 11px; height: 11px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 11px; height: 11px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 18px; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QListWidget::indicator, QTreeView::indicator, QTableView::indicator {{
    width: 16px; height: 16px; border-radius: 5px; border: 1px solid {p.text3}; background: {c(p.surface2)}; }}
QCheckBox::indicator:checked, QListWidget::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked {{
    background: {p.accent}; border-color: {p.accent}; image: url("{check}"); }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {p.text3}; background: {c(p.surface2)}; }}
QRadioButton::indicator:checked {{ background: {p.accent}; border: 3px solid {p.bg2}; }}

/* ---------- Tabellen und Listen ---------- */
QTableView, QTreeView, QListView, QListWidget {{
    background: {c(p.surface)}; alternate-background-color: {c(p.surface2)}; border: 1px solid {c(p.border)}; border-radius: 12px;
    gridline-color: transparent; selection-background-color: {c(p.accent_soft)}; selection-color: {p.text}; outline: none;
}}
QTableView::item, QTreeView::item {{ padding: 4px 6px; border: none; }}
QListWidget::item {{ padding: 6px 6px; border-radius: 8px; }}
QTreeView::item:selected, QTableView::item:selected, QListWidget::item:selected {{ background: {c(p.accent_soft)}; color: {p.text}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {p.text2}; border: none; border-bottom: 1px solid {c(p.border)};
    padding: 8px 8px; font-weight: 600; font-size: 12px; }}
QHeaderView::section:hover {{ color: {p.text}; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

/* ---------- Tabs ---------- */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {p.text2}; padding: 9px 16px; margin-right: 4px; border: none;
    border-bottom: 2px solid transparent; font-size: 13px; }}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.accent}; font-weight: 600; }}

/* ---------- Fortschritt ---------- */
QProgressBar {{ background: {c(p.surface3)}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent}, stop:1 {p.accent2}); }}
QProgressBar[level="warning"]::chunk {{ background: {p.warn}; }}
QProgressBar[level="critical"]::chunk {{ background: {p.crit}; }}

/* ---------- Scrollbalken ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c(p.surface3)}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text3}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c(p.surface3)}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- Menüs ---------- */
QMenu {{ background: {popup_bg}; border: 1px solid {c(p.border_hi)}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c(p.accent_soft)}; }}
QMenu::separator {{ height: 1px; background: {c(p.border)}; margin: 4px 6px; }}
QSplitter::handle {{ background: {c(p.border)}; }}
QSlider::groove:horizontal {{ height: 4px; background: {c(p.surface3)}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.accent}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
"""

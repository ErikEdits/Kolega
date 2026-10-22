"""Farben, Schriften und Stylesheet für Hell- und Dunkelmodus mit frei wählbarer Akzentfarbe."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from corecontrol.core.platform import IS_WINDOWS

log = logging.getLogger(__name__)

ACCENT_PRESETS = [
    "#2d7ff9",  # Blau
    "#0ea5a4",  # Türkis
    "#22a35a",  # Grün
    "#8b5cf6",  # Violett
    "#e0457b",  # Pink
    "#f06a2b",  # Orange
    "#d4a106",  # Gold
    "#64748b",  # Schiefer
]


@dataclass(frozen=True)
class Palette:
    dark: bool
    bg: str
    sidebar: str
    surface: str
    surface2: str
    surface3: str
    border: str
    text: str
    text2: str
    text3: str
    ok: str
    warn: str
    crit: str
    info: str
    accent: str = "#2d7ff9"
    accent_hover: str = "#4a91fa"
    accent_pressed: str = "#2168d0"
    accent_text: str = "#ffffff"
    accent_soft: str = "rgba(45,127,249,0.16)"
    accent_fg: str = "#2d7ff9"  # Akzent als Textfarbe (lesbar auf Hintergrund)

    def color(self, role: str) -> str:
        return getattr(self, role)

    def soft(self, role: str, alpha: float = 0.14) -> str:
        c = QColor(self.color(role))
        return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


DARK = Palette(
    dark=True,
    bg="#16171a",
    sidebar="#1b1c20",
    surface="#212328",
    surface2="#2a2d33",
    surface3="#33363d",
    border="#2f3238",
    text="#eceef1",
    text2="#a7adb7",
    text3="#737985",
    ok="#3fc979",
    warn="#f5b237",
    crit="#ff5d62",
    info="#5ea8ff",
)

LIGHT = Palette(
    dark=False,
    bg="#f3f4f6",
    sidebar="#eaecef",
    surface="#ffffff",
    surface2="#f1f2f5",
    surface3="#e5e7eb",
    border="#e0e3e8",
    text="#1a1c20",
    text2="#545a64",
    text3="#878d97",
    ok="#1e9b52",
    warn="#b77400",
    crit="#d42f35",
    info="#1a6fdc",
)


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
        a = QColor("#2d7ff9")
    white, black = QColor("#ffffff"), QColor("#000000")
    accent_text = "#ffffff" if _contrast(a, white) >= 3.0 else "#111111"
    # Akzent als Schriftfarbe muss auf dem Hintergrund lesbar sein
    bg = QColor(base.surface)
    fg = QColor(a)
    for _ in range(10):
        if _contrast(fg, bg) >= 3.2:
            break
        fg = _mix(fg, white if base.dark else black, 0.15)
    return replace(
        base,
        accent=a.name(),
        accent_hover=_mix(a, white, 0.15).name(),
        accent_pressed=_mix(a, black, 0.18).name(),
        accent_text=accent_text,
        accent_soft=f"rgba({a.red()},{a.green()},{a.blue()},{0.20 if base.dark else 0.13})",
        accent_fg=fg.name(),
    )


def windows_accent() -> str | None:
    """Liest die Windows-Akzentfarbe (falls verfügbar)."""
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

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as k:
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


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.palette: Palette = with_accent(DARK, "#2d7ff9")
        self.font_family = "Segoe UI"
        self.mode = "system"
        self.accent_setting = "#2d7ff9"

    def resolved_accent(self) -> str:
        if self.accent_setting == "windows":
            return windows_accent() or "#2d7ff9"
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
        pal.setColor(QPalette.ColorRole.Base, QColor(p.surface))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(p.surface2))
        pal.setColor(QPalette.ColorRole.Text, QColor(p.text))
        pal.setColor(QPalette.ColorRole.Button, QColor(p.surface2))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(p.text))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(p.accent))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(p.accent_text))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.surface3))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(p.text))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(p.text3))
        pal.setColor(QPalette.ColorRole.Link, QColor(p.accent_fg))
        return pal


theme = ThemeManager()


def set_dark_titlebar(widget, dark: bool) -> None:
    """Färbt die Windows-Titelleiste passend zum Modus (Windows 10 20H1+ / 11)."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (neu / alt)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def _cached_svg(name: str, color: str, svg: str | None = None) -> str:
    """Schreibt ein eingefärbtes Symbol in den Cache und gibt den Pfad für Stylesheets zurück."""
    from corecontrol.core import paths
    from corecontrol.core.platform import resource_path

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
    check = _cached_svg("check", p.accent_text, CHECK_SVG)
    down = _cached_svg("chevron-down", p.text2)
    up = _cached_svg("chevron-up", p.text2)
    return f"""
* {{ font-family: "{font}"; }}
QWidget {{ color: {p.text}; }}
QMainWindow, QDialog, #pageRoot, QStackedWidget {{ background: {p.bg}; }}
QToolTip {{ background: {p.surface3}; color: {p.text}; border: 1px solid {p.border}; padding: 6px 8px; border-radius: 6px; }}

/* ---------- Seitenleiste ---------- */
#sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
#sidebar QLabel#appName {{ font-size: 16px; font-weight: 700; color: {p.text}; }}
#sidebar QLabel#appTag {{ font-size: 11px; color: {p.text3}; }}
#sidebar QLabel[role="navSection"] {{ color: {p.text3}; font-size: 11px; font-weight: 600; padding: 12px 14px 4px 14px; letter-spacing: 0.4px; }}
QToolButton[role="nav"] {{
    background: transparent; border: none; border-radius: 7px; padding: 7px 10px; margin: 1px 8px;
    color: {p.text2}; text-align: left; font-size: 13px;
}}
QToolButton[role="nav"]:hover {{ background: {p.surface2}; color: {p.text}; }}
QToolButton[role="nav"]:checked {{ background: {p.accent_soft}; color: {p.text}; font-weight: 600; }}

/* ---------- Seitenkopf ---------- */
QLabel[role="h1"] {{ font-size: 24px; font-weight: 700; color: {p.text}; }}
QLabel[role="h2"] {{ font-size: 16px; font-weight: 600; color: {p.text}; }}
QLabel[role="h3"] {{ font-size: 13px; font-weight: 600; color: {p.text}; }}
QLabel[role="subtitle"] {{ font-size: 13px; color: {p.text2}; }}
QLabel[role="muted"] {{ color: {p.text2}; }}
QLabel[role="faint"] {{ color: {p.text3}; font-size: 12px; }}
QLabel[role="caption"] {{ color: {p.text3}; font-size: 11px; font-weight: 600; letter-spacing: 0.3px; }}
QLabel[role="bigValue"] {{ font-size: 30px; font-weight: 650; color: {p.text}; }}
QLabel[role="midValue"] {{ font-size: 20px; font-weight: 600; color: {p.text}; }}
QLabel[role="ok"] {{ color: {p.ok}; }}
QLabel[role="warn"] {{ color: {p.warn}; }}
QLabel[role="crit"] {{ color: {p.crit}; }}
QLabel[role="info"] {{ color: {p.info}; }}
QLabel[role="link"] {{ color: {p.accent_fg}; }}
QLabel {{ background: transparent; }}

/* ---------- Karten ---------- */
QFrame[role="card"] {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame[role="cardFlat"] {{ background: {p.surface2}; border: none; border-radius: 10px; }}
QFrame[role="tile"] {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame[role="tile"]:hover {{ border: 1px solid {p.surface3}; }}
QFrame[role="separator"] {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}
QFrame[role="banner"] {{ border-radius: 10px; border: 1px solid transparent; }}
QFrame[role="banner"][level="critical"] {{ background: {p.soft("crit", 0.14)}; border-color: {p.soft("crit", 0.35)}; }}
QFrame[role="banner"][level="warning"] {{ background: {p.soft("warn", 0.14)}; border-color: {p.soft("warn", 0.35)}; }}
QFrame[role="banner"][level="info"] {{ background: {p.soft("info", 0.12)}; border-color: {p.soft("info", 0.30)}; }}
QFrame[role="banner"][level="ok"] {{ background: {p.soft("ok", 0.12)}; border-color: {p.soft("ok", 0.30)}; }}
QFrame[role="finding"] {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame[role="finding"]:hover {{ border-color: {p.surface3}; }}
QLabel[role="chip"] {{ border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600; }}
QLabel[role="chip"][level="critical"] {{ background: {p.soft("crit", 0.18)}; color: {p.crit}; }}
QLabel[role="chip"][level="warning"] {{ background: {p.soft("warn", 0.18)}; color: {p.warn}; }}
QLabel[role="chip"][level="info"] {{ background: {p.soft("info", 0.16)}; color: {p.info}; }}
QLabel[role="chip"][level="ok"] {{ background: {p.soft("ok", 0.16)}; color: {p.ok}; }}
QLabel[role="chip"][level="neutral"] {{ background: {p.surface2}; color: {p.text2}; }}

/* ---------- Schaltflächen ---------- */
QPushButton {{
    background: {p.surface2}; color: {p.text}; border: 1px solid {p.border};
    border-radius: 8px; padding: 7px 14px; font-size: 13px;
}}
QPushButton:hover {{ background: {p.surface3}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.text3}; background: {p.surface2}; border-color: {p.border}; }}
QPushButton[role="primary"] {{ background: {p.accent}; color: {p.accent_text}; border: 1px solid {p.accent}; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[role="primary"]:pressed {{ background: {p.accent_pressed}; }}
QPushButton[role="primary"]:disabled {{ background: {p.surface3}; color: {p.text3}; border-color: {p.surface3}; }}
QPushButton[role="danger"] {{ background: {p.crit}; color: #ffffff; border: 1px solid {p.crit}; font-weight: 600; }}
QPushButton[role="danger"]:hover {{ background: {p.soft("crit", 0.85)}; }}
QPushButton[role="ghost"] {{ background: transparent; border: none; color: {p.accent_fg}; padding: 6px 8px; }}
QPushButton[role="ghost"]:hover {{ background: {p.accent_soft}; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 4px; }}
QToolButton:hover {{ background: {p.surface2}; }}
QToolButton[role="swatch"] {{ border-radius: 14px; border: 2px solid transparent; }}
QToolButton[role="swatch"]:checked {{ border: 2px solid {p.text}; }}

/* ---------- Eingaben ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px; padding: 6px 9px;
    selection-background-color: {p.accent}; selection-color: {p.accent_text};
}}
QPlainTextEdit, QTextEdit {{ background: {p.surface}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 14px; height: 14px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 11px; height: 11px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 11px; height: 11px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 18px; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border}; selection-background-color: {p.accent_soft}; selection-color: {p.text}; outline: none; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QListWidget::indicator, QTreeView::indicator, QTableView::indicator {{
    width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p.text3}; background: {p.surface}; }}
QCheckBox::indicator:checked, QListWidget::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked {{
    background: {p.accent}; border-color: {p.accent}; image: url("{check}"); }}
QCheckBox::indicator:indeterminate {{ background: {p.accent_soft}; border-color: {p.accent}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {p.text3}; background: {p.surface}; }}
QRadioButton::indicator:checked {{ background: {p.accent}; border: 3px solid {p.surface}; outline: 1px solid {p.accent}; }}

/* ---------- Tabellen und Listen ---------- */
QTableView, QTreeView, QListView, QListWidget {{
    background: {p.surface}; alternate-background-color: {p.surface2}; border: 1px solid {p.border}; border-radius: 10px;
    gridline-color: transparent; selection-background-color: {p.accent_soft}; selection-color: {p.text}; outline: none;
}}
QTableView::item, QTreeView::item {{ padding: 4px 6px; border: none; }}
QListWidget::item {{ padding: 6px 6px; border-radius: 6px; }}
QTreeView::item:selected, QTableView::item:selected, QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {p.surface}; color: {p.text2}; border: none; border-bottom: 1px solid {p.border};
    padding: 7px 8px; font-weight: 600; font-size: 12px;
}}
QHeaderView::section:hover {{ color: {p.text}; }}
QTableCornerButton::section {{ background: {p.surface}; border: none; }}

/* ---------- Tabs ---------- */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {p.text2}; padding: 8px 14px; margin-right: 4px; border: none; border-bottom: 2px solid transparent; font-size: 13px; }}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.accent}; font-weight: 600; }}

/* ---------- Fortschritt ---------- */
QProgressBar {{ background: {p.surface2}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}
QProgressBar[level="warning"]::chunk {{ background: {p.warn}; }}
QProgressBar[level="critical"]::chunk {{ background: {p.crit}; }}

/* ---------- Scrollbalken ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.surface3}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text3}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.surface3}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- Menüs ---------- */
QMenu {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {p.accent_soft}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}
QSplitter::handle {{ background: {p.border}; }}
QMessageBox {{ background: {p.surface}; }}
QSlider::groove:horizontal {{ height: 4px; background: {p.surface3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.accent}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
"""

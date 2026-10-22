"""Wiederverwendbare Oberflächen-Bausteine."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from corecontrol.i18n import tr
from corecontrol.ui.bus import bind_icon, bind_text, on_refresh
from corecontrol.ui.theme import theme


def set_role(widget: QWidget, role: str, **props: Any) -> QWidget:
    widget.setProperty("role", role)
    for k, v in props.items():
        widget.setProperty(k, v)
    repolish(widget)
    return widget


def set_prop(widget: QWidget, name: str, value: Any) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


def repolish(widget: QWidget) -> None:
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)


def label(text_key: str | None = None, role: str | None = None, text: str | None = None, wrap: bool = False, **params) -> QLabel:
    lbl = QLabel()
    if text_key:
        bind_text(lbl, text_key, **params)
    elif text is not None:
        lbl.setText(text)
    if role:
        set_role(lbl, role)
    if wrap:
        lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse if wrap else Qt.TextInteractionFlag.NoTextInteraction)
    return lbl


def button(text_key: str | None = None, role: str | None = None, icon: str | None = None,
           on_click: Callable | None = None, text: str | None = None, icon_role: str | None = None) -> QPushButton:
    btn = QPushButton()
    if text_key:
        bind_text(btn, text_key)
    elif text:
        btn.setText(text)
    if role:
        set_role(btn, role)
    if icon:
        ir = icon_role or ("accent_text" if role == "primary" else "accent_fg" if role == "ghost" else "text")
        bind_icon(btn, icon, ir, 16)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        btn.clicked.connect(lambda *_: on_click())
    return btn


def tool_button(icon: str, tooltip_key: str | None = None, on_click: Callable | None = None, size: int = 18) -> QToolButton:
    btn = QToolButton()
    bind_icon(btn, icon, "text2", size)
    if tooltip_key:
        bind_text(btn, tooltip_key, "setToolTip")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        btn.clicked.connect(lambda *_: on_click())
    return btn


def icon_label(name: str, role: str = "text2", size: int = 18) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(size + 2, size + 2)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    bind_icon(lbl, name, role, size, setter="setPixmap")
    return lbl


class Card(QFrame):
    def __init__(self, title_key: str | None = None, icon: str | None = None, role: str = "card",
                 margins: int = 18, spacing: int = 12, parent: QWidget | None = None):
        super().__init__(parent)
        set_role(self, role)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(margins, margins - 2, margins, margins)
        self.outer.setSpacing(spacing)
        self.header = None
        if title_key:
            self.header = QHBoxLayout()
            self.header.setSpacing(8)
            if icon:
                self.header.addWidget(icon_label(icon, "text2", 17))
            self.title = label(title_key, "h2")
            self.header.addWidget(self.title)
            self.header.addStretch(1)
            self.outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(spacing)
        self.outer.addLayout(self.body)

    def add(self, w: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(w, stretch)
        return w

    def add_layout(self, lay) -> None:
        self.body.addLayout(lay)

    def add_header_widget(self, w: QWidget) -> None:
        if self.header is not None:
            self.header.addWidget(w)


def separator() -> QFrame:
    f = QFrame()
    set_role(f, "separator")
    f.setFixedHeight(1)
    return f


class Chip(QLabel):
    def __init__(self, text: str = "", level: str = "neutral"):
        super().__init__(text)
        set_role(self, "chip", level=level)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_level(self, level: str) -> None:
        set_prop(self, "level", level)


class PageHeader(QWidget):
    def __init__(self, title_key: str, subtitle_key: str | None = None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.title = label(title_key, "h1")
        left.addWidget(self.title)
        if subtitle_key:
            self.subtitle = label(subtitle_key, "subtitle", wrap=True)
            left.addWidget(self.subtitle)
        lay.addLayout(left, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)

    def add_action(self, w: QWidget) -> QWidget:
        self.actions.addWidget(w, 0, Qt.AlignmentFlag.AlignBottom)
        return w


class ScrollPage(QScrollArea):
    """Scrollbarer Seiteninhalt mit einheitlichen Abständen."""

    def __init__(self, max_width: int | None = None):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("pageRoot")
        self.content = QVBoxLayout(inner)
        self.content.setContentsMargins(32, 26, 32, 32)
        self.content.setSpacing(18)
        if max_width:
            inner.setMaximumWidth(max_width)
        self.setWidget(inner)


class EmptyState(QWidget):
    def __init__(self, icon: str, title_key: str, text_key: str | None = None):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 30, 20, 30)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = icon_label(icon, "text3", 34)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = label(title_key, "h3")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)
        if text_key:
            self.text = label(text_key, "muted", wrap=True)
            self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.text.setMaximumWidth(520)
            lay.addWidget(self.text, 0, Qt.AlignmentFlag.AlignHCenter)


class Banner(QFrame):
    """Farbiger Hinweisbalken (kritisch / Warnung / Info / OK)."""

    action_clicked = Signal()
    closed = Signal()

    ICONS = {"critical": ("octagon-x", "crit"), "warning": ("triangle-alert", "warn"),
             "info": ("info", "info"), "ok": ("circle-check", "ok")}

    def __init__(self, level: str = "info", closable: bool = False):
        super().__init__()
        set_role(self, "banner", level=level)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(22, 22)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: 600;")
        self.text = QLabel()
        self.text.setWordWrap(True)
        set_role(self.text, "muted")
        texts.addWidget(self.title)
        texts.addWidget(self.text)
        lay.addLayout(texts, 1)
        self.action = QPushButton()
        self.action.setVisible(False)
        self.action.clicked.connect(self.action_clicked)
        lay.addWidget(self.action, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_btn = None
        if closable:
            self.close_btn = tool_button("x", "common.close", lambda: (self.hide(), self.closed.emit()), 16)
            lay.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.level = level
        self._update_icon()
        on_refresh(self, self._update_icon)

    def _update_icon(self) -> None:
        from corecontrol.ui import icons

        name, role = self.ICONS.get(self.level, self.ICONS["info"])
        self.icon.setPixmap(icons.pixmap(name, theme.palette.color(role), 20))

    def set_content(self, level: str, title: str, text: str = "", action: str | None = None) -> None:
        self.level = level
        set_prop(self, "level", level)
        self.title.setText(title)
        self.text.setText(text)
        self.text.setVisible(bool(text))
        self.action.setVisible(bool(action))
        if action:
            self.action.setText(action)
        self._update_icon()


class KeyValueGrid(QWidget):
    """Zweispaltige Liste „Bezeichnung: Wert“."""

    def __init__(self, columns: int = 1):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(8)
        self.columns = columns
        self._rows: list[tuple[QLabel, QLabel]] = []

    def set_rows(self, rows: Iterable[tuple[str, str]]) -> None:
        rows = list(rows)
        while len(self._rows) > len(rows):
            k, v = self._rows.pop()
            k.deleteLater()
            v.deleteLater()
        for i, (key, value) in enumerate(rows):
            if i < len(self._rows):
                k, v = self._rows[i]
            else:
                k, v = QLabel(), QLabel()
                set_role(k, "muted")
                v.setWordWrap(True)
                v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                r, c = divmod(i, self.columns)
                self.grid.addWidget(k, r, c * 2, Qt.AlignmentFlag.AlignTop)
                self.grid.addWidget(v, r, c * 2 + 1, Qt.AlignmentFlag.AlignTop)
                self._rows.append((k, v))
            k.setText(key)
            v.setText(value)
        for c in range(self.columns):
            self.grid.setColumnStretch(c * 2 + 1, 1)


class Toggle(QAbstractButton):
    """Schalter im Windows-11-Stil."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)
        theme.changed.connect(self.update)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get(self) -> float:
        return self._pos

    def _set(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def paintEvent(self, _):
        p = theme.palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        on = self.isChecked()
        enabled = self.isEnabled()
        if on:
            painter.setBrush(QColor(p.accent if enabled else p.surface3))
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setBrush(QColor(p.surface2))
            painter.setPen(QColor(p.text3))
        painter.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 8 if on else r.height() - 10
        x = r.left() + 5 + self._pos * (r.width() - 10 - d)
        y = r.center().y() - d / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.accent_text if on else p.text2))
        painter.drawEllipse(QRectF(x, y, d, d))


class SettingRow(QWidget):
    """Eine Zeile in den Einstellungen: Titel, Beschreibung und Bedienelement."""

    def __init__(self, title_key: str, desc_key: str | None, control: QWidget, icon: str | None = None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(12)
        if icon:
            lay.addWidget(icon_label(icon, "text2", 18), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(label(title_key))
        if desc_key:
            texts.addWidget(label(desc_key, "faint", wrap=True))
        lay.addLayout(texts, 1)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.control = control


def flow_row(*widgets: QWidget, spacing: int = 8, stretch_end: bool = True) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    if stretch_end:
        lay.addStretch(1)
    return lay


def level_color(level: str) -> str:
    return theme.palette.color({"critical": "crit", "warning": "warn", "info": "info", "ok": "ok"}.get(level, "text2"))


def na() -> str:
    return tr("common.na")

"""Animierte Bedienelemente im CoreControl-Stil.

AnimatedButton  – Schaltfläche: beim Überfahren weich heller, dezenter Glow, hebt sich leicht an;
                  beim Klicken kurze Skalierung als Rückmeldung.
NavButton       – Eintrag der Seitenleiste mit weicher Hervorhebung und leuchtender Auswahl.
GaugeRing       – Ringanzeige mit Farbverlauf; neue Werte werden weich angefahren.
IconBadge       – farbige Symbol-Kachel (CPU blau, GPU violett, RAM grün …).
BarRow          – beschriftete Balkenanzeige (Temperaturen, Lüfter) mit weicher Animation.
BusyBar         – Ladeanzeige mit gleitendem Lichtstreifen (läuft nur, solange sichtbar).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QConicalGradient, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QPushButton, QSizePolicy, QWidget

from corecontrol.ui import anim, icons
from corecontrol.ui.theme import theme


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


class _Animated:
    """Mischklasse: weich animierte Werte (hover, press, check …) ohne eigene Timer pro Wert."""

    def _anim_init(self):
        self._vals: dict[str, float] = {}
        self._targets: dict[str, float] = {}
        self._speeds: dict[str, float] = {}

    def _animate(self, name: str, target: float, duration_ms: int, kind: str = "hover") -> None:
        cur = self._vals.get(name, 0.0)
        self._targets[name] = target
        if not anim.allow(kind) or duration_ms <= 0 or not self.isVisible():
            self._vals[name] = target
            self.update()
            return
        self._speeds[name] = 1000.0 / duration_ms
        if abs(cur - target) > 1e-3:
            anim.ticker().add(self, self._step)

    def _step(self, dt: float) -> bool:
        busy = False
        for name, target in self._targets.items():
            cur = self._vals.get(name, 0.0)
            if abs(cur - target) < 1e-3:
                continue
            step = self._speeds.get(name, 6.0) * dt
            cur = min(target, cur + step) if target > cur else max(target, cur - step)
            self._vals[name] = cur
            busy = busy or abs(cur - target) >= 1e-3
        self.update()
        return busy

    @staticmethod
    def _ease(t: float) -> float:
        return 1 - (1 - t) ** 3


class AnimatedButton(QPushButton, _Animated):
    M = 4  # Rand für Glow und Anheben

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self._anim_init()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setIconSize(QSize(16, 16))
        self.toggled.connect(lambda on: self._animate("check", 1.0 if on else 0.0, 160, "fade"))
        theme.changed.connect(self.update)

    def role(self) -> str:
        return self.property("role") or "secondary"

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._font())
        text = self.text().replace("&&", "&")
        w = fm.horizontalAdvance(text) + 2 * 15
        if not self.icon().isNull():
            w += self.iconSize().width() + (7 if text else 0)
        if not text:
            w = self.iconSize().width() + 18
        h = max(fm.height(), self.iconSize().height()) + 2 * 8
        return QSize(w + 2 * self.M, h + 2 * self.M)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(13)
        if self.role() in ("primary", "danger") or (self.role() == "filter" and self.isChecked()):
            f.setWeight(QFont.Weight.DemiBold)
        return f

    def enterEvent(self, ev):
        self._animate("hover", 1.0, 180, "hover")
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._animate("hover", 0.0, 240, "hover")
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        self._animate("press", 1.0, 90, "press")
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._animate("press", 0.0, 200, "press")
        super().mouseReleaseEvent(ev)

    def changeEvent(self, ev):
        super().changeEvent(ev)
        self.update()

    def paintEvent(self, _):
        p = theme.palette
        role = self.role()
        hover = self._ease(self._vals.get("hover", 0.0)) if self.isEnabled() else 0.0
        press = self._vals.get("press", 0.0)
        check = self._vals.get("check", 1.0 if self.isChecked() else 0.0)
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.M
        r = QRectF(self.rect()).adjusted(m, m, -m, -m)
        radius = min(10.0, r.height() / 2)
        lift = 1.5 * hover if anim.allow("hover") else 0.0
        scale = 1.0 - 0.04 * press
        qp.translate(r.center())
        qp.scale(scale, scale)
        qp.translate(-r.center())
        qp.translate(0, -lift)
        white = QColor(255, 255, 255)
        enabled = self.isEnabled()

        if role in ("primary", "danger"):
            base1 = QColor(p.accent if role == "primary" else p.crit)
            base2 = QColor(p.accent2 if role == "primary" else QColor(p.crit).lighter(115))
            if not enabled:
                base1, base2 = p.qcolor("surface3"), p.qcolor("surface3")
            # Glow (nur bei Hover, sehr dezent)
            if hover > 0.01 and anim.allow("glow") and enabled:
                for i in range(4):
                    g = QColor(base1)
                    g.setAlphaF(0.07 * hover * (4 - i) / 4)
                    qp.setPen(QPen(g, 2 + i * 2))
                    qp.setBrush(Qt.BrushStyle.NoBrush)
                    qp.drawRoundedRect(r.adjusted(-i * 0.5, -i * 0.5, i * 0.5, i * 0.5), radius + i, radius + i)
            grad = QLinearGradient(r.topLeft(), r.topRight())
            # Lichtakzent: der Verlauf verschiebt sich beim Überfahren leicht
            grad.setColorAt(0, _mix(base1, white, 0.10 * hover))
            grad.setColorAt(min(1.0, 0.85 + 0.15 * hover), _mix(base2, white, 0.14 * hover))
            grad.setColorAt(1, _mix(base2, white, 0.10 * hover))
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(grad)
            qp.drawRoundedRect(r, radius, radius)
            # Glanzkante oben
            hl = QLinearGradient(r.topLeft(), r.bottomLeft())
            hl.setColorAt(0, QColor(255, 255, 255, int(40 + 30 * hover)))
            hl.setColorAt(0.5, QColor(255, 255, 255, 0))
            qp.setBrush(hl)
            qp.drawRoundedRect(r, radius, radius)
            fg = QColor(p.accent_text if role == "primary" else "#ffffff") if enabled else p.qcolor("text3")
        elif role == "ghost":
            bg = p.qcolor("accent_soft")
            bg.setAlphaF(bg.alphaF() * hover)
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(bg)
            qp.drawRoundedRect(r, radius, radius)
            fg = QColor(p.accent_fg) if enabled else p.qcolor("text3")
        else:
            checked = role == "filter" and check > 0
            bg = _mix(p.qcolor("surface2"), p.qcolor("surface3"), hover)
            border = _mix(p.qcolor("border"), p.qcolor("border_hi"), hover)
            if role == "filter":
                bg = _mix(QColor(0, 0, 0, 0), p.qcolor("surface2"), hover)
                if checked:
                    bg = _mix(bg, p.qcolor("accent_soft"), check)
                    border = _mix(border, QColor(p.accent), check)
                radius = r.height() / 2
            qp.setPen(QPen(border, 1))
            qp.setBrush(bg)
            qp.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
            fg = QColor(p.text) if enabled else p.qcolor("text3")
            if role == "filter" and not checked:
                fg = _mix(p.qcolor("text2"), QColor(p.text), hover)

        # Inhalt
        text = self.text().replace("&&", "&")
        font = self._font()
        qp.setFont(font)
        fm = QFontMetrics(font)
        isz = self.iconSize().width() if not self.icon().isNull() else 0
        gap = 7 if (isz and text) else 0
        content_w = isz + gap + fm.horizontalAdvance(text)
        x = r.center().x() - content_w / 2
        if isz:
            pm = self.icon().pixmap(self.iconSize(), QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled)
            qp.drawPixmap(QPointF(x, r.center().y() - isz / 2), pm)
        qp.setPen(fg)
        qp.drawText(QRectF(x + isz + gap, r.top(), content_w, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
        qp.end()


class NavButton(QAbstractButton, _Animated):
    def __init__(self, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._anim_init()
        self.icon_name = icon_name
        self.compact = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggled.connect(lambda on: self._animate("sel", 1.0 if on else 0.0, 220, "fade"))
        theme.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(200, 46)

    def enterEvent(self, ev):
        self._animate("hover", 1.0, 160, "hover")
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._animate("hover", 0.0, 220, "hover")
        super().leaveEvent(ev)

    def paintEvent(self, _):
        p = theme.palette
        sel = self._ease(self._vals.get("sel", 1.0 if self.isChecked() else 0.0))
        hover = self._vals.get("hover", 0.0)
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(10, 3, -10, -3)
        if hover > 0.01 and sel < 0.99:
            hb = p.qcolor("surface2")
            hb.setAlphaF(hb.alphaF() * hover * (1 - sel))
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(hb)
            qp.drawRoundedRect(r, 11, 11)
        if sel > 0.01:
            a1, a2 = QColor(p.accent), QColor(p.accent).darker(135)
            if anim.allow("glow"):
                for i in range(3):
                    g = QColor(p.accent)
                    g.setAlphaF(0.10 * sel * (3 - i) / 3)
                    qp.setPen(QPen(g, 2 + 2 * i))
                    qp.setBrush(Qt.BrushStyle.NoBrush)
                    qp.drawRoundedRect(r, 11 + i, 11 + i)
            grad = QLinearGradient(r.topLeft(), r.topRight())
            a1.setAlphaF(0.95 * sel)
            a2.setAlphaF(0.75 * sel)
            grad.setColorAt(0, a1)
            grad.setColorAt(1, a2)
            qp.setPen(QPen(QColor(255, 255, 255, int(45 * sel)), 1))
            qp.setBrush(grad)
            qp.drawRoundedRect(r, 11, 11)
        fg = _mix(_mix(p.qcolor("text2"), QColor(p.text), hover), QColor("#ffffff"), sel)
        pm = icons.pixmap(self.icon_name, fg.name(), 20)
        if self.compact:
            qp.drawPixmap(QPointF(r.center().x() - 10, r.center().y() - 10), pm)
        else:
            qp.drawPixmap(QPointF(r.left() + 14, r.center().y() - 10), pm)
            f = QFont(self.font())
            f.setPixelSize(14)
            f.setWeight(QFont.Weight.DemiBold if sel > 0.5 else QFont.Weight.Normal)
            qp.setFont(f)
            qp.setPen(fg)
            qp.drawText(QRectF(r.left() + 46, r.top(), r.width() - 50, r.height()), Qt.AlignmentFlag.AlignVCenter,
                        QFontMetrics(f).elidedText(self.text().replace("&&", "&"), Qt.TextElideMode.ElideRight,
                                                   int(r.width() - 52)))
        qp.end()


class IconBadge(QWidget):
    def __init__(self, icon_name: str, color_role: str = "accent", size: int = 40):
        super().__init__()
        self.icon_name, self.color_role = icon_name, color_role
        self.setFixedSize(size, size)
        theme.changed.connect(self.update)

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        c = QColor(p.color(self.color_role))
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        c1, c2 = QColor(c), QColor(c)
        c1.setAlphaF(0.95 if p.dark else 0.9)
        c2 = c2.darker(150)
        c2.setAlphaF(0.85)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        qp.setPen(QPen(QColor(255, 255, 255, 50), 1))
        qp.setBrush(grad)
        qp.drawRoundedRect(r, r.width() * 0.28, r.width() * 0.28)
        s = int(self.width() * 0.52)
        qp.drawPixmap(QPointF((self.width() - s) / 2, (self.height() - s) / 2), icons.pixmap(self.icon_name, "#ffffff", s))
        qp.end()


class GaugeRing(QWidget, _Animated):
    """Ringanzeige 0–100 % mit Verlauf, weichem Anfahren neuer Werte und Beschriftung in der Mitte."""

    def __init__(self, size: int = 112, thickness: int = 9, color_role: str = "accent"):
        super().__init__()
        self._anim_init()
        self.color_role = color_role
        self.thickness = thickness
        self.value: float | None = None
        self.center_text = "–"
        self.caption = ""
        self.level = "normal"  # normal / warning / critical
        self.setFixedSize(size, size)
        theme.changed.connect(self.update)

    def set_value(self, v: float | None, text: str, caption: str = "", level: str = "normal") -> None:
        self.value, self.center_text, self.caption, self.level = v, text, caption, level
        target = max(0.0, min(100.0, v)) / 100 if v is not None else 0.0
        cur = self._vals.get("v", 0.0)
        if abs(cur - target) > 0.004:
            self._animate("v", target, 600, "gauge")
        else:
            self.update()

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.thickness
        r = QRectF(t / 2 + 3, t / 2 + 3, self.width() - t - 6, self.height() - t - 6)
        track = p.qcolor("surface3")
        qp.setPen(QPen(track, t, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        qp.drawArc(r, 0, 360 * 16)
        frac = self._vals.get("v", 0.0) if self.value is not None else 0.0
        role = {"warning": "warn", "critical": "crit"}.get(self.level, self.color_role)
        col = QColor(p.color(role))
        if frac > 0.002:
            grad = QConicalGradient(r.center(), 90)
            light = QColor(col).lighter(135)
            grad.setColorAt(0.0, light)
            grad.setColorAt(max(0.01, 1 - frac), col)
            grad.setColorAt(1.0, light)
            # Glow unter dem Bogen
            if anim.allow("glow"):
                g = QColor(col)
                g.setAlphaF(0.18)
                qp.setPen(QPen(g, t + 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                qp.drawArc(r, 90 * 16, -int(360 * 16 * frac))
            qp.setPen(QPen(grad, t, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            qp.drawArc(r, 90 * 16, -int(360 * 16 * frac))
        f = QFont(theme.font_family)
        f.setPixelSize(int(self.height() * 0.19))
        f.setWeight(QFont.Weight.Bold)
        qp.setFont(f)
        qp.setPen(QColor(p.text))
        cy = self.height() / 2
        qp.drawText(QRectF(0, cy - self.height() * 0.17 - (6 if self.caption else 0), self.width(), self.height() * 0.3),
                    Qt.AlignmentFlag.AlignCenter, self.center_text)
        if self.caption:
            f2 = QFont(theme.font_family)
            f2.setPixelSize(max(9, int(self.height() * 0.095)))
            qp.setFont(f2)
            qp.setPen(QColor(p.text2))
            qp.drawText(QRectF(4, cy + 4, self.width() - 8, self.height() * 0.16), Qt.AlignmentFlag.AlignCenter,
                        QFontMetrics(f2).elidedText(self.caption, Qt.TextElideMode.ElideRight, self.width() - 26))
        qp.end()


class BarRow(QWidget, _Animated):
    """Name links, Wert rechts, darunter ein dünner Verlaufsbalken."""

    def __init__(self, color_role: str = "accent"):
        super().__init__()
        self._anim_init()
        self.color_role = color_role
        self.name = ""
        self.value_text = ""
        self.na = False
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.update)

    def set(self, name: str, value_text: str, frac: float | None, color_role: str | None = None) -> None:
        self.name, self.value_text = name, value_text
        if color_role:
            self.color_role = color_role
        self.na = frac is None
        target = 0.0 if frac is None else max(0.0, min(1.0, frac))
        if abs(self._vals.get("f", 0.0) - target) > 0.003:
            self._animate("f", target, 500, "gauge")
        else:
            self.update()

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(theme.font_family)
        f.setPixelSize(13)
        qp.setFont(f)
        qp.setPen(QColor(p.text2))
        qp.drawText(QRectF(0, 0, self.width() * 0.65, 22), Qt.AlignmentFlag.AlignVCenter, self.name)
        qp.setPen(QColor(p.text) if not self.na else QColor(p.text3))
        qp.drawText(QRectF(0, 0, self.width(), 22), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    self.value_text)
        track = QRectF(0, 29, self.width(), 6)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(p.qcolor("surface3"))
        qp.drawRoundedRect(track, 3, 3)
        frac = self._vals.get("f", 0.0)
        if frac > 0.003:
            col = QColor(p.color(self.color_role))
            grad = QLinearGradient(track.topLeft(), track.topRight())
            grad.setColorAt(0, col)
            grad.setColorAt(1, QColor(col).lighter(140))
            qp.setBrush(grad)
            qp.drawRoundedRect(QRectF(track.left(), track.top(), max(6.0, track.width() * frac), track.height()), 3, 3)
        qp.end()


class BusyBar(QWidget):
    """Unbestimmte Ladeanzeige: ein Lichtstreifen gleitet über die Leiste (nur solange sichtbar)."""

    def __init__(self):
        super().__init__()
        self._pos = 0.0
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.update)

    def showEvent(self, ev):
        super().showEvent(ev)
        if anim.allow("fade"):
            anim.ticker().add(self, self._tick)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        anim.ticker().remove(self)

    def _tick(self, dt: float) -> bool:
        self._pos = (self._pos + dt / 1.3) % 1.0
        self.update()
        return self.isVisible()

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(p.qcolor("surface3"))
        qp.drawRoundedRect(r, 3, 3)
        if not anim.allow("fade"):
            qp.setBrush(QColor(p.accent))
            qp.drawRoundedRect(r, 3, 3)
            return
        w = r.width() * 0.35
        x = -w + (r.width() + w) * (0.5 - 0.5 * math.cos(math.pi * self._pos))
        grad = QLinearGradient(x, 0, x + w, 0)
        c = QColor(p.accent)
        c0 = QColor(c)
        c0.setAlpha(0)
        grad.setColorAt(0, c0)
        grad.setColorAt(0.5, QColor(p.accent2))
        grad.setColorAt(1, c0)
        qp.setBrush(grad)
        path = QPainterPath()
        path.addRoundedRect(r, 3, 3)
        qp.setClipPath(path)
        qp.drawRect(QRectF(x, 0, w, r.height()))
        qp.end()


def flag_pixmap(lang: str, w: int = 20, h: int = 14) -> QPixmap:
    """Kleine Flagge für die Sprachauswahl (gezeichnet, keine Bilddateien)."""
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), 2.5, 2.5)
    qp.setClipPath(path)
    if lang == "de":
        for i, col in enumerate(("#000000", "#dd0000", "#ffce00")):
            qp.fillRect(QRectF(0, i * h / 3, w, h / 3 + 0.5), QColor(col))
    else:
        qp.fillRect(QRectF(0, 0, w, h), QColor("#012169"))
        qp.setPen(QPen(QColor("#ffffff"), h * 0.22))
        qp.drawLine(QPointF(0, 0), QPointF(w, h))
        qp.drawLine(QPointF(w, 0), QPointF(0, h))
        qp.setPen(QPen(QColor("#c8102e"), h * 0.09))
        qp.drawLine(QPointF(0, 0), QPointF(w, h))
        qp.drawLine(QPointF(w, 0), QPointF(0, h))
        qp.fillRect(QRectF(w / 2 - h * 0.17, 0, h * 0.34, h), QColor("#ffffff"))
        qp.fillRect(QRectF(0, h / 2 - h * 0.17, w, h * 0.34), QColor("#ffffff"))
        qp.fillRect(QRectF(w / 2 - h * 0.1, 0, h * 0.2, h), QColor("#c8102e"))
        qp.fillRect(QRectF(0, h / 2 - h * 0.1, w, h * 0.2), QColor("#c8102e"))
    qp.end()
    return pm


class HoverCard:
    """Mischklasse für Karten: Rahmen leuchtet beim Überfahren weich auf."""

    def _hover_init(self):
        self._anim_init()
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, ev):
        self._animate("hover", 1.0, 200, "hover")
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._animate("hover", 0.0, 260, "hover")
        super().leaveEvent(ev)

    def paint_hover(self):
        h = self._vals.get("hover", 0.0)
        if h < 0.01:
            return
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        c1, c2 = QColor(p.accent), QColor(p.accent2)
        c1.setAlphaF(0.55 * h)
        c2.setAlphaF(0.15 * h)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        qp.setPen(QPen(grad, 1.2))
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawRoundedRect(r, 16, 16)
        qp.end()

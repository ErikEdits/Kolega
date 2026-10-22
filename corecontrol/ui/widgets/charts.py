"""Leichtgewichtige Diagramme (QPainter) – ohne zusätzliche Bibliotheken."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from corecontrol.ui.theme import theme


@dataclass
class Series:
    name: str
    color: str  # Farbrolle (z. B. "accent") oder Hex-Wert
    values: deque = field(default_factory=lambda: deque(maxlen=120))
    fill: bool = True


def _start_slide(widget, animate: bool) -> None:
    """Startet das weiche Einschieben eines neuen Wertes (nur wenn sichtbar und erlaubt)."""
    from corecontrol.ui import anim

    if animate and widget.isVisible() and anim.allow("chart"):
        widget._phase = 0.0
        anim.ticker().add(widget, widget._tick)
    else:
        widget._phase = 1.0
        widget.update()


def _resolve(color: str) -> QColor:
    if color.startswith("#"):
        return QColor(color)
    return QColor(theme.palette.color(color))


class LineChart(QWidget):
    """Live-Liniendiagramm mit Raster, Achsenbeschriftung und Legende."""

    def __init__(self, points: int = 60, y_max: float | None = 100.0, unit: str = "%",
                 value_fmt: Callable[[float], str] | None = None, show_legend: bool = True,
                 show_axes: bool = True, min_height: int = 150, time_axis: bool = False, legend_right: bool = False):
        super().__init__()
        self.points = points
        self.y_max = y_max
        self.unit = unit
        self.value_fmt = value_fmt or (lambda v: f"{v:.0f}{unit}")
        self.series: list[Series] = []
        self.show_legend = show_legend
        self.show_axes = show_axes
        self.time_axis = time_axis
        self.legend_right = legend_right
        self.times: deque = deque(maxlen=points)
        self._phase = 1.0
        self._dur = 0.4
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme.changed.connect(self.update)

    def add_series(self, name: str, color: str, fill: bool = True) -> Series:
        s = Series(name, color, deque(maxlen=self.points), fill)
        self.series.append(s)
        return s

    def push(self, *values: float | None, ts: float | None = None, animate: bool = True) -> None:
        import time as _t

        now = ts if ts is not None else _t.time()
        if self.times:
            self._dur = max(0.15, min(0.45, (now - self.times[-1]) * 0.6))
        self.times.append(now)
        for s, v in zip(self.series, values):
            s.values.append(v)
        _start_slide(self, animate)

    def clear(self) -> None:
        for s in self.series:
            s.values.clear()
        self.times.clear()
        self.update()

    def _tick(self, dt: float) -> bool:
        self._phase = min(1.0, self._phase + dt / self._dur)
        self.update()
        return self._phase < 1.0

    def _ymax(self) -> float:
        if self.y_max is not None:
            return self.y_max
        m = max((v for s in self.series for v in s.values if v is not None), default=0.0)
        if m <= 0:
            return 1.0
        mag = 10 ** math.floor(math.log10(m))
        for step in (1, 2, 2.5, 5, 10):
            if m <= step * mag:
                return step * mag
        return m

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        ymax = self._ymax()
        font = QFont(theme.font_family, 8)
        qp.setFont(font)
        left = 2
        if self.show_axes:
            fm = qp.fontMetrics()
            left = max(fm.horizontalAdvance(self.value_fmt(ymax * i / 4)) for i in range(5)) + 14
        top = 26 if self.show_legend else 6
        bottom = 24 if self.time_axis else 8
        right = 6
        plot = QRectF(left, top, max(10, w - left - right), max(10, h - top - bottom))
        # Raster
        if self.show_axes:
            grid_pen = QPen(QColor(p.border))
            grid_pen.setWidthF(1)
            for i in range(5):
                y = plot.top() + plot.height() * i / 4
                qp.setPen(grid_pen)
                qp.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
                qp.setPen(QColor(p.text3))
                val = ymax * (4 - i) / 4
                qp.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                            self.value_fmt(val))
        # Linien (neue Werte gleiten von rechts herein)
        ease = 1 - (1 - self._phase) ** 3
        step = plot.width() / max(1, self.points - 1)
        shift = (1 - ease) * step
        qp.save()
        qp.setClipRect(plot.adjusted(0, -4, 0, 4))
        for s in self.series:
            col = _resolve(s.color)
            n = self.points
            vals = list(s.values)
            if len(vals) >= 2 and vals[-1] is not None and vals[-2] is not None and ease < 1:
                vals[-1] = vals[-2] + (vals[-1] - vals[-2]) * ease
            offset = n - len(vals)
            segments: list[list[QPointF]] = [[]]
            for i, v in enumerate(vals):
                if v is None:
                    if segments[-1]:
                        segments.append([])
                    continue
                x = plot.left() + plot.width() * (offset + i) / max(1, n - 1) + shift
                y = plot.bottom() - plot.height() * min(max(v, 0.0), ymax) / ymax
                segments[-1].append(QPointF(x, y))
            for pts in segments:
                if len(pts) < 2:
                    continue
                path = QPainterPath(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                if s.fill:
                    fill = QPainterPath(path)
                    fill.lineTo(pts[-1].x(), plot.bottom())
                    fill.lineTo(pts[0].x(), plot.bottom())
                    fill.closeSubpath()
                    grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
                    c1 = QColor(col)
                    c1.setAlphaF(0.30 if p.dark else 0.22)
                    c2 = QColor(col)
                    c2.setAlphaF(0.0)
                    grad.setColorAt(0, c1)
                    grad.setColorAt(1, c2)
                    qp.fillPath(fill, grad)
                pen = QPen(col)
                pen.setWidthF(2.0)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                qp.setPen(pen)
                qp.drawPath(path)
        qp.restore()
        # Zeitachse
        if self.time_axis and len(self.times) >= 2:
            from datetime import datetime as _dt

            qp.setFont(QFont(theme.font_family, 8))
            qp.setPen(QColor(p.text3))
            n = self.points
            times = list(self.times)
            interval = (times[-1] - times[0]) / max(1, len(times) - 1)
            fm = qp.fontMetrics()
            span_s = interval * (n - 1)
            fmt_s = "%H:%M" if span_s >= 240 else "%H:%M:%S"
            label_w = fm.horizontalAdvance("00:00:00") + 16
            ticks = max(2, min(7, int(plot.width() // label_w)))
            for k in range(ticks + 1):
                frac = k / ticks
                x = plot.left() + plot.width() * frac
                t_at = times[-1] - (1 - frac) * span_s
                if t_at < times[0] - interval * 0.5:
                    continue  # für diesen Zeitpunkt gibt es noch keine Messwerte
                txt = _dt.fromtimestamp(t_at).strftime(fmt_s)
                align = Qt.AlignmentFlag.AlignLeft if k == 0 else Qt.AlignmentFlag.AlignRight if k == ticks else Qt.AlignmentFlag.AlignHCenter
                rx = x if k == 0 else x - label_w if k == ticks else x - label_w / 2
                qp.drawText(QRectF(rx, plot.bottom() + 4, label_w, 16), align, txt)
        # Legende
        if self.show_legend and self.legend_right:
            lf = QFont(theme.font_family, 9)
            qp.setFont(lf)
            fm = qp.fontMetrics()
            x = plot.right()
            for s in reversed(self.series):
                tw = fm.horizontalAdvance(s.name)
                x -= tw + 22
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(_resolve(s.color))
                qp.drawEllipse(QRectF(x, 8, 8, 8))
                qp.setPen(QColor(p.text2))
                qp.drawText(QRectF(x + 12, 2, tw + 4, 20), Qt.AlignmentFlag.AlignVCenter, s.name)
        elif self.show_legend:
            x = plot.left()
            lf = QFont(theme.font_family, 9)
            qp.setFont(lf)
            for s in self.series:
                col = _resolve(s.color)
                last = next((v for v in reversed(s.values) if v is not None), None)
                txt = f"{s.name}: {self.value_fmt(last) if last is not None else '–'}"
                qp.setPen(Qt.PenStyle.NoPen)
                qp.setBrush(col)
                qp.drawRoundedRect(QRectF(x, 7, 10, 10), 3, 3)
                qp.setPen(QColor(p.text2))
                tw = qp.fontMetrics().horizontalAdvance(txt)
                qp.drawText(QRectF(x + 15, 2, tw + 4, 20), Qt.AlignmentFlag.AlignVCenter, txt)
                x += tw + 34
        qp.end()


class Sparkline(QWidget):
    def __init__(self, color: str = "accent", points: int = 60, y_max: float | None = 100.0, height: int = 38,
                 max_height: int = 96):
        super().__init__()
        self.color = color
        self.values: deque = deque(maxlen=points)
        self.points = points
        self.y_max = y_max
        self.setMinimumHeight(height)
        self.setMaximumHeight(max(height, max_height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme.changed.connect(self.update)

    _phase = 1.0
    _dur = 0.4

    def push(self, v: float | None, animate: bool = True) -> None:
        self.values.append(v)
        _start_slide(self, animate)

    def _tick(self, dt: float) -> bool:
        self._phase = min(1.0, self._phase + dt / self._dur)
        self.update()
        return self._phase < 1.0

    def paintEvent(self, _):
        vals = [v for v in self.values]
        if sum(1 for v in vals if v is not None) < 2:
            return
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = _resolve(self.color)
        w, h = self.width(), self.height() - 2
        ymax = self.y_max or max((v for v in vals if v is not None), default=1) or 1
        offset = self.points - len(vals)
        ease = 1 - (1 - self._phase) ** 3
        shift = (1 - ease) * w / max(1, self.points - 1)
        if len(vals) >= 2 and vals[-1] is not None and vals[-2] is not None and ease < 1:
            vals[-1] = vals[-2] + (vals[-1] - vals[-2]) * ease
        pts = []
        for i, v in enumerate(vals):
            if v is None:
                continue
            x = w * (offset + i) / max(1, self.points - 1) + shift
            y = 1 + h - h * min(max(v, 0), ymax) / ymax
            pts.append(QPointF(x, y))
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(pts[-1].x(), h + 1)
        fill.lineTo(pts[0].x(), h + 1)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c1 = QColor(col)
        c1.setAlphaF(0.28)
        c2 = QColor(col)
        c2.setAlphaF(0.0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        qp.fillPath(fill, grad)
        pen = QPen(col)
        pen.setWidthF(1.8)
        qp.setPen(pen)
        qp.drawPath(path)
        qp.end()


class Ring(QWidget):
    """Ringanzeige (z. B. Auslastung in %)."""

    def __init__(self, size: int = 64, thickness: int = 7):
        super().__init__()
        self.value: float | None = None
        self.level = "accent"
        self.thickness = thickness
        self.setFixedSize(size, size)
        theme.changed.connect(self.update)

    def set_value(self, v: float | None, level: str = "accent") -> None:
        self.value, self.level = v, level
        self.update()

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.thickness / 2 + 1
        r = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        pen = QPen(QColor(p.surface3))
        pen.setWidthF(self.thickness)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        qp.setPen(pen)
        qp.drawArc(r, 0, 360 * 16)
        if self.value is not None:
            pen.setColor(_resolve(self.level))
            qp.setPen(pen)
            span = -int(360 * 16 * max(0, min(self.value, 100)) / 100)
            qp.drawArc(r, 90 * 16, span)
        qp.end()


class BarList(QWidget):
    """Horizontale Balken (z. B. Ordnergrößen oder Dateitypen)."""

    def __init__(self, value_fmt: Callable[[float], str] = str, max_rows: int = 12):
        super().__init__()
        self.items: list[tuple[str, float, str]] = []
        self.value_fmt = value_fmt
        self.max_rows = max_rows
        self.row_h = 30
        theme.changed.connect(self.update)

    def set_items(self, items: Sequence[tuple[str, float, str]]) -> None:
        self.items = list(items)[: self.max_rows]
        self.setMinimumHeight(max(30, len(self.items) * self.row_h))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(400, max(30, len(self.items) * self.row_h))

    def paintEvent(self, _):
        if not self.items:
            return
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.setFont(QFont(theme.font_family, 9))
        fm = qp.fontMetrics()
        w = self.width()
        label_w = min(int(w * 0.38), 260)
        val_w = 80
        bar_w = max(20, w - label_w - val_w - 16)
        mx = max((v for _, v, _ in self.items), default=1) or 1
        for i, (name, val, color) in enumerate(self.items):
            y = i * self.row_h
            qp.setPen(QColor(p.text))
            qp.drawText(QRectF(0, y, label_w, self.row_h), Qt.AlignmentFlag.AlignVCenter,
                        fm.elidedText(name, Qt.TextElideMode.ElideMiddle, label_w - 6))
            bx = label_w + 6
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QColor(p.surface2))
            qp.drawRoundedRect(QRectF(bx, y + 10, bar_w, 10), 5, 5)
            qp.setBrush(_resolve(color))
            qp.drawRoundedRect(QRectF(bx, y + 10, max(4, bar_w * val / mx), 10), 5, 5)
            qp.setPen(QColor(p.text2))
            qp.drawText(QRectF(bx + bar_w + 6, y, val_w, self.row_h),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.value_fmt(val))
        qp.end()


class Donut(QWidget):
    """Ringdiagramm für Anteile (z. B. Speicher nach Dateityp)."""

    def __init__(self, size: int = 170):
        super().__init__()
        self.parts: list[tuple[str, float, str]] = []
        self.setFixedSize(size, size)
        self.center_text = ""
        self.center_sub = ""
        theme.changed.connect(self.update)

    def set_parts(self, parts: Sequence[tuple[str, float, str]], center: str = "", sub: str = "") -> None:
        self.parts = [x for x in parts if x[1] > 0]
        self.center_text, self.center_sub = center, sub
        self.update()

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        th = 20
        r = QRectF(th / 2 + 2, th / 2 + 2, self.width() - th - 4, self.height() - th - 4)
        pen = QPen(QColor(p.surface2))
        pen.setWidthF(th)
        qp.setPen(pen)
        qp.drawArc(r, 0, 360 * 16)
        total = sum(v for _, v, _ in self.parts)
        if total > 0:
            start = 90 * 16
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            for _, v, color in self.parts:
                span = -int(round(360 * 16 * v / total))
                pen.setColor(_resolve(color))
                qp.setPen(pen)
                qp.drawArc(r, start, span)
                start += span
        qp.setPen(QColor(p.text))
        qp.setFont(QFont(theme.font_family, 13, QFont.Weight.DemiBold))
        qp.drawText(QRectF(0, self.height() / 2 - 20, self.width(), 24), Qt.AlignmentFlag.AlignCenter, self.center_text)
        qp.setPen(QColor(p.text3))
        qp.setFont(QFont(theme.font_family, 8))
        qp.drawText(QRectF(0, self.height() / 2 + 4, self.width(), 18), Qt.AlignmentFlag.AlignCenter, self.center_sub)
        qp.end()


class HistoryChart(QWidget):
    """Verlaufsdiagramm mit Zeitachse, Mittelwert-Linie und Maximal-Band. Zeigt Werte beim Darüberfahren."""

    def __init__(self, value_fmt: Callable[[float], str] = lambda v: f"{v:.0f}", y_max: float | None = 100.0):
        super().__init__()
        self.value_fmt = value_fmt
        self.y_max = y_max
        self.ts: list[float] = []
        self.avg: list[float | None] = []
        self.max: list[float | None] = []
        self.color = "accent"
        self.hover_x: float | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        theme.changed.connect(self.update)

    def set_data(self, ts: list[float], avg: list[float | None], mx: list[float | None], y_max: float | None,
                 value_fmt: Callable[[float], str], color: str = "accent") -> None:
        self.ts, self.avg, self.max = ts, avg, mx
        self.y_max, self.value_fmt, self.color = y_max, value_fmt, color
        self.update()

    def mouseMoveEvent(self, ev):
        self.hover_x = ev.position().x()
        self.update()

    def leaveEvent(self, _):
        self.hover_x = None
        self.update()

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.setFont(QFont(theme.font_family, 8))
        vals = [v for v in self.max + self.avg if v is not None]
        ymax = self.y_max or (max(vals) * 1.15 if vals else 1.0) or 1.0
        fm = qp.fontMetrics()
        left = max(fm.horizontalAdvance(self.value_fmt(ymax * i / 4)) for i in range(5)) + 14
        top, right, bottom = 10, 10, 26
        plot = QRectF(left, top, max(10, self.width() - left - right), max(10, self.height() - top - bottom))
        for i in range(5):
            y = plot.top() + plot.height() * i / 4
            qp.setPen(QPen(QColor(p.border)))
            qp.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            qp.setPen(QColor(p.text3))
            qp.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        self.value_fmt(ymax * (4 - i) / 4))
        if len(self.ts) < 2:
            qp.end()
            return
        t0, t1 = self.ts[0], self.ts[-1]
        span = max(1.0, t1 - t0)

        def xy(t, v):
            return QPointF(plot.left() + plot.width() * (t - t0) / span,
                           plot.bottom() - plot.height() * min(max(v, 0), ymax) / ymax)

        col = _resolve(self.color)
        # Max-Band
        band = QColor(col)
        band.setAlphaF(0.16)
        pen = QPen(band)
        pen.setWidthF(1.2)
        qp.setPen(pen)
        prev = None
        for t, v in zip(self.ts, self.max):
            if v is None:
                prev = None
                continue
            pt = xy(t, v)
            if prev is not None:
                qp.drawLine(prev, pt)
            prev = pt
        # Mittelwert
        pen = QPen(col)
        pen.setWidthF(1.8)
        qp.setPen(pen)
        prev = None
        gap = span / max(1, len(self.ts)) * 3
        last_t = None
        for t, v in zip(self.ts, self.avg):
            if v is None or (last_t is not None and t - last_t > max(gap, 180)):
                prev = None
            if v is None:
                last_t = t
                continue
            pt = xy(t, v)
            if prev is not None:
                qp.drawLine(prev, pt)
            prev, last_t = pt, t
        # Zeitachse
        qp.setPen(QColor(p.text3))
        fmt = "%H:%M" if span <= 2 * 86400 else "%d.%m."
        for i in range(5):
            t = t0 + span * i / 4
            x = plot.left() + plot.width() * i / 4
            txt = datetime.fromtimestamp(t).strftime(fmt)
            align = Qt.AlignmentFlag.AlignLeft if i == 0 else Qt.AlignmentFlag.AlignRight if i == 4 else Qt.AlignmentFlag.AlignHCenter
            rx = x if i == 0 else x - 80 if i == 4 else x - 40
            qp.drawText(QRectF(rx, plot.bottom() + 4, 80, 18), align, txt)
        # Hover
        if self.hover_x is not None and plot.left() <= self.hover_x <= plot.right():
            t = t0 + span * (self.hover_x - plot.left()) / plot.width()
            idx = min(range(len(self.ts)), key=lambda i: abs(self.ts[i] - t))
            x = plot.left() + plot.width() * (self.ts[idx] - t0) / span
            qp.setPen(QPen(QColor(p.text3), 1, Qt.PenStyle.DashLine))
            qp.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            a, m = self.avg[idx], self.max[idx]
            txt = datetime.fromtimestamp(self.ts[idx]).strftime("%d.%m. %H:%M")
            txt += f"  Ø {self.value_fmt(a) if a is not None else '–'}  ↑ {self.value_fmt(m) if m is not None else '–'}"
            qp.setFont(QFont(theme.font_family, 9))
            tw = qp.fontMetrics().horizontalAdvance(txt) + 16
            bx = min(max(plot.left(), x - tw / 2), plot.right() - tw)
            box = QRectF(bx, plot.top() + 2, tw, 24)
            qp.setPen(QPen(QColor(p.border)))
            qp.setBrush(QColor(p.surface3))
            qp.drawRoundedRect(box, 6, 6)
            qp.setPen(QColor(p.text))
            qp.drawText(box, Qt.AlignmentFlag.AlignCenter, txt)
        qp.end()

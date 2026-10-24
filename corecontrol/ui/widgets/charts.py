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
    values: deque = field(default_factory=deque)
    fill: bool = True


# Größere Lücken zwischen zwei Messungen (z. B. Ruhezustand) werden nicht als Linie verbunden.
GAP_S = 15.0
_NICE_STEPS = (1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800, 3600)


def time_ticks(t_end: float, window_s: float, width_px: float, min_gap_px: float) -> list[tuple[float, float]]:
    """Uhrzeit-Markierungen auf runden Zeitpunkten, mindestens min_gap_px auseinander.

    Gibt (Zeitpunkt, Anteil 0..1 von links) zurück.
    """
    if width_px <= 0 or window_s <= 0:
        return []
    px_per_s = width_px / window_s
    step = next((st for st in _NICE_STEPS if st * px_per_s >= min_gap_px), None)
    if step is None:
        return []
    t0 = t_end - window_s
    out = []
    t = math.ceil(t0 / step) * step
    while t <= t_end + 1e-6:
        out.append((t, (t - t0) / window_s))
        t += step
    return out


def _segments(times, values, x_of, y_of) -> list[list[QPointF]]:
    """Punkte als zusammenhängende Linienstücke; fehlende Werte und große Lücken trennen."""
    segments: list[list[QPointF]] = [[]]
    last_t = None
    for t, v in zip(times, values):
        if v is None or (last_t is not None and t - last_t > GAP_S):
            if segments[-1]:
                segments.append([])
        if v is not None:
            segments[-1].append(QPointF(x_of(t), y_of(v)))
        last_t = t
    return [seg for seg in segments if len(seg) >= 2]


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


class _TimeWindow:
    """Gemeinsame Logik: Messpunkte mit Zeitstempel über ein festes Zeitfenster.

    Die x-Position ergibt sich aus der Uhrzeit, nicht aus der Anzahl der Punkte. So
    stimmt die Zeitachse bei jedem Messtakt (0,25 s bis 10 s) und auch dann, wenn im
    Hintergrund seltener gemessen wurde. Neue Werte gleiten von rechts herein.
    """

    window_s: float
    times: deque
    _phase = 1.0
    _dur = 0.4
    _prev_end: float | None = None

    def _append_time(self, ts: float | None) -> float:
        import time as _t

        now = ts if ts is not None else _t.time()
        if self.times and now < self.times[-1]:
            self.clear()  # Uhr wurde zurückgestellt
        if self.times:
            self._dur = max(0.15, min(0.45, (now - self.times[-1]) * 0.6))
            self._prev_end = self.times[-1]
        else:
            self._prev_end = None
        self.times.append(now)
        return now

    def _prune(self, now: float, columns: list[deque]) -> None:
        # Ein Punkt vor dem Fensteranfang bleibt, damit die Linie bis zum linken Rand reicht.
        limit = now - self.window_s
        while len(self.times) >= 2 and self.times[1] <= limit:
            self.times.popleft()
            for col in columns:
                col.popleft()

    def _view_end(self) -> float:
        """Rechter Rand des sichtbaren Fensters (gleitet beim Einschieben mit)."""
        end = self.times[-1]
        if self._prev_end is None or self._phase >= 1.0:
            return end
        ease = 1 - (1 - self._phase) ** 3
        return self._prev_end + (end - self._prev_end) * ease

    def _tick(self, dt: float) -> bool:
        self._phase = min(1.0, self._phase + dt / self._dur)
        self.update()
        return self._phase < 1.0


class LineChart(_TimeWindow, QWidget):
    """Live-Liniendiagramm mit Raster, Achsenbeschriftung und Legende über window_s Sekunden."""

    def __init__(self, window_s: float = 60, y_max: float | None = 100.0, unit: str = "%",
                 value_fmt: Callable[[float], str] | None = None, show_legend: bool = True,
                 show_axes: bool = True, min_height: int = 150, time_axis: bool = False, legend_right: bool = False):
        super().__init__()
        self.window_s = float(window_s)
        self.y_max = y_max
        self.unit = unit
        self.value_fmt = value_fmt or (lambda v: f"{v:.0f}{unit}")
        self.series: list[Series] = []
        self.show_legend = show_legend
        self.show_axes = show_axes
        self.time_axis = time_axis
        self.legend_right = legend_right
        self.times: deque = deque()
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme.changed.connect(self.update)

    def add_series(self, name: str, color: str, fill: bool = True) -> Series:
        s = Series(name, color, deque([None] * len(self.times)), fill)
        self.series.append(s)
        return s

    def push(self, *values: float | None, ts: float | None = None, animate: bool = True) -> None:
        now = self._append_time(ts)
        for i, s in enumerate(self.series):
            s.values.append(values[i] if i < len(values) else None)
        self._prune(now, [s.values for s in self.series])
        _start_slide(self, animate)

    def clear(self) -> None:
        for s in self.series:
            s.values.clear()
        self.times.clear()
        self._prev_end = None
        self.update()

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
        view_end = self._view_end() if self.times else 0.0

        def x_of(t: float) -> float:
            return plot.right() - (view_end - t) / self.window_s * plot.width()

        def y_of(v: float) -> float:
            return plot.bottom() - plot.height() * min(max(v, 0.0), ymax) / ymax

        # Linien (neue Werte gleiten von rechts herein)
        qp.save()
        qp.setClipRect(plot.adjusted(0, -4, 0, 4))
        times = list(self.times)
        for s in self.series:
            col = _resolve(s.color)
            for pts in _segments(times, s.values, x_of, y_of):
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
        # Zeitachse: runde Uhrzeiten, die mit den Werten mitlaufen und sich nie überlappen
        if self.time_axis and times:
            qp.setFont(QFont(theme.font_family, 8))
            qp.setPen(QColor(p.text3))
            fm = qp.fontMetrics()
            tw = fm.horizontalAdvance("00:00:00")
            ticks = time_ticks(view_end, self.window_s, plot.width(), tw + 18)
            fmt_s = "%H:%M:%S"
            if len(ticks) >= 2 and ticks[1][0] - ticks[0][0] >= 60:
                fmt_s = "%H:%M"
            for t, frac in ticks:
                if t < times[0]:
                    continue  # für diesen Zeitpunkt gibt es noch keine Messwerte
                x = plot.left() + plot.width() * frac
                rect = QRectF(x - tw / 2 - 4, plot.bottom() + 4, tw + 8, 16)
                if rect.left() < 0 or rect.right() > w:
                    continue
                qp.drawText(rect, Qt.AlignmentFlag.AlignHCenter, datetime.fromtimestamp(t).strftime(fmt_s))
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


class Sparkline(_TimeWindow, QWidget):
    """Kleine Verlaufslinie ohne Achsen über window_s Sekunden."""

    def __init__(self, color: str = "accent", window_s: float = 60, y_max: float | None = 100.0, height: int = 38,
                 max_height: int = 96):
        super().__init__()
        self.color = color
        self.window_s = float(window_s)
        self.times: deque = deque()
        self.values: deque = deque()
        self.y_max = y_max
        self.setMinimumHeight(height)
        self.setMaximumHeight(max(height, max_height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme.changed.connect(self.update)

    def push(self, v: float | None, animate: bool = True, ts: float | None = None) -> None:
        now = self._append_time(ts)
        self.values.append(v)
        self._prune(now, [self.values])
        _start_slide(self, animate)

    def clear(self) -> None:
        self.values.clear()
        self.times.clear()
        self._prev_end = None
        self.update()

    def paintEvent(self, _):
        if sum(1 for v in self.values if v is not None) < 2:
            return
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = _resolve(self.color)
        w, h = self.width(), self.height() - 2
        ymax = self.y_max or max((v for v in self.values if v is not None), default=1) or 1
        view_end = self._view_end()
        segments = _segments(list(self.times), self.values,
                             lambda t: w - (view_end - t) / self.window_s * w,
                             lambda v: 1 + h - h * min(max(v, 0), ymax) / ymax)
        qp.setClipRect(QRectF(0, 0, w, h + 2))
        pen = QPen(col)
        pen.setWidthF(1.8)
        grad = QLinearGradient(0, 0, 0, h)
        c1 = QColor(col)
        c1.setAlphaF(0.28)
        c2 = QColor(col)
        c2.setAlphaF(0.0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        for pts in segments:
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            fill = QPainterPath(path)
            fill.lineTo(pts[-1].x(), h + 1)
            fill.lineTo(pts[0].x(), h + 1)
            fill.closeSubpath()
            qp.fillPath(fill, grad)
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

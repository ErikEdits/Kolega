"""Das CoreControl-Logo wird gezeichnet statt als Bild mitgeliefert (scharf in jeder Größe)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


def render_logo(size: int, c1: str = "#3b8cff", c2: str = "#1d4fd1") -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    rect = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0, QColor(c1))
    grad.setColorAt(1, QColor(c2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(rect, s * 0.24, s * 0.24)
    # Innerer Ring („Core“)
    ring = QPen(QColor(255, 255, 255, 70))
    ring.setWidthF(max(1.0, s * 0.07))
    p.setPen(ring)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(s / 2, s / 2), s * 0.27, s * 0.27)
    # Pulslinie
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(1.2, s * 0.075))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(s * 0.18, s * 0.53))
    for x, y in ((0.36, 0.53), (0.44, 0.33), (0.55, 0.70), (0.63, 0.47), (0.82, 0.47)):
        path.lineTo(QPointF(s * x, s * y))
    p.drawPath(path)
    p.end()
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        ic.addPixmap(render_logo(sz))
    return ic

"""SVG-Symbole (Lucide, ISC-Lizenz) in beliebiger Farbe."""

from __future__ import annotations

import functools
import logging

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from corecontrol.core.platform import resource_path

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=256)
def _svg_source(name: str) -> str | None:
    try:
        with open(resource_path("assets", "icons", f"{name}.svg"), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        log.warning("Symbol fehlt: %s", name)
        return None


@functools.lru_cache(maxsize=1024)
def pixmap(name: str, color: str, size: int = 18, stroke: float | None = None) -> QPixmap:
    app = QApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0
    ratio = max(ratio, 1.0)
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.GlobalColor.transparent)
    src = _svg_source(name)
    if src:
        data = src.replace("currentColor", color)
        if stroke is not None:
            data = data.replace('stroke-width="2"', f'stroke-width="{stroke}"')
        renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, pm.width(), pm.height()))
        p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str, size: int = 18) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size))
    return ic


def qsize(size: int) -> QSize:
    return QSize(size, size)

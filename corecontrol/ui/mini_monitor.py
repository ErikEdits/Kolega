"""Mini-Monitor: kleines, verschiebbares Fenster, das über anderen Fenstern bleibt.

Ersatz für ein Ingame-Overlay: Es greift nicht in Spiele ein (kein Anti-Cheat-Risiko)
und ist über Spielen im Fenster- bzw. randlosen Vollbildmodus sichtbar.
Bei exklusivem Vollbild kann Windows es verdecken.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from corecontrol.core import fmt
from corecontrol.i18n import tr
from corecontrol.ui.theme import theme

_instance: "MiniMonitor | None" = None


class MiniMonitor(QWidget):
    def __init__(self, ctx):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if ctx.settings.get("gaming.mini_on_top"):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.ctx = ctx
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("CoreControl Mini")
        self.setFixedSize(230, 150)
        self.setWindowOpacity(ctx.settings.get("gaming.mini_opacity"))
        self.rows: list[tuple[str, str, str]] = []
        self._drag: QPoint | None = None
        pos = ctx.settings.get("gaming.mini_pos")
        if pos:
            self.move(pos[0], pos[1])
        else:
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.right() - self.width() - 24, scr.top() + 24)
        ctx.sampler.sampled.connect(self.on_sample)
        ctx.setting_changed.connect(self._setting)
        s = ctx.sampler.store.latest()
        if s:
            self.on_sample(s)

    def _setting(self, key, value):
        if key == "gaming.mini_opacity":
            self.setWindowOpacity(value)

    def on_sample(self, s) -> None:
        g = s.primary_gpu
        self.rows = [
            ("CPU", fmt.pct(s.cpu_percent), fmt.temp(s.cpu_temp) if s.cpu_temp is not None else ""),
            ("GPU", fmt.pct(g.util) if g else "–", fmt.temp(g.temp) if g and g.temp is not None else ""),
            ("RAM", fmt.pct(s.ram_percent), fmt.bytes_(s.ram_used)),
            ("VRAM", fmt.bytes_(g.vram_used) if g and g.vram_used is not None else "–", ""),
            ("NET", fmt.rate_bits(s.net_down_bps), ""),
        ]
        self.update()

    def paintEvent(self, _):
        p = theme.palette
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(14, 15, 18, 225) if p.dark else QColor(255, 255, 255, 235)
        qp.setBrush(bg)
        qp.setPen(QColor(p.border))
        qp.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)
        qp.setFont(QFont(theme.font_family, 8, QFont.Weight.DemiBold))
        qp.setPen(QColor(p.accent_fg))
        qp.drawText(14, 20, "CoreControl")
        y = 42
        for name, v1, v2 in self.rows:
            qp.setFont(QFont(theme.font_family, 9, QFont.Weight.DemiBold))
            qp.setPen(QColor(p.text2))
            qp.drawText(14, y, name)
            qp.setFont(QFont(theme.font_family, 10, QFont.Weight.Bold))
            qp.setPen(QColor(p.text))
            qp.drawText(70, y, v1)
            qp.setFont(QFont(theme.font_family, 9))
            qp.setPen(QColor(p.text2))
            qp.drawText(150, y, v2)
            y += 22
        qp.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif ev.button() == Qt.MouseButton.RightButton:
            self.close()

    def mouseMoveEvent(self, ev):
        if self._drag is not None:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            self._drag = None
            self.ctx.settings.set("gaming.mini_pos", [self.x(), self.y()])

    def closeEvent(self, ev):
        global _instance
        try:
            self.ctx.sampler.sampled.disconnect(self.on_sample)
        except Exception:
            pass
        _instance = None
        super().closeEvent(ev)


def toggle_mini_monitor(ctx) -> bool:
    """Öffnet bzw. schließt den Mini-Monitor. Gibt True zurück, wenn er jetzt offen ist."""
    global _instance
    if _instance is not None:
        _instance.close()
        _instance = None
        return False
    _instance = MiniMonitor(ctx)
    _instance.setToolTip(tr("gaming.mini_tooltip"))
    _instance.show()
    return True


def is_open() -> bool:
    return _instance is not None

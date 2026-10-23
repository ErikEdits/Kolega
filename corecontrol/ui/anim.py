"""Animationen: zentral gesteuert, kurz und sparsam.

Stufen (Einstellung „Animationen & Effekte“):
- full:    Hover-Effekte (aufhellen, Glow, Anheben), Klick-Rückmeldung, Seitenübergänge,
           Einblenden, weiche Diagramme und Ringanzeigen
- reduced: nur Seitenübergänge und Überblendungen (kein Glow, keine Diagramm-Animation)
- off:     keine Animationen
- system:  „full“, außer Windows-Animationen sind ausgeschaltet → „off“

Technik (ehrlich): Qt-Widgets werden auf der CPU gezeichnet. Darum sind Animationen
kurz (150–400 ms), laufen nur bei Bedarf und teilen sich einen Taktgeber mit 30 Bildern/s.
Das Ein-/Ausblenden ganzer Fenster (Dialoge, Mini-Monitor) übernimmt der Windows-
Compositor (GPU). Dauerhafte Animationen gibt es nicht.
"""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, QTimer, QVariantAnimation
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget

from corecontrol.core.platform import IS_WINDOWS

_level = "full"

EASE = QEasingCurve.Type.OutCubic
EASE_IN_OUT = QEasingCurve.Type.InOutCubic


def windows_animations_enabled() -> bool:
    if not IS_WINDOWS:
        return True
    try:
        import ctypes

        val = ctypes.c_int(1)
        SPI_GETCLIENTAREAANIMATION = 0x1042
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(val), 0):
            return bool(val.value)
    except Exception:
        pass
    return True


def set_level(setting: str) -> None:
    global _level
    if setting == "system":
        _level = "full" if windows_animations_enabled() else "off"
    elif setting in ("full", "reduced", "off"):
        _level = setting
    else:
        _level = "full"
    app = QApplication.instance()
    if app is not None:
        on = _level != "off"
        for eff in (Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu, Qt.UIEffect.UI_AnimateCombo,
                    Qt.UIEffect.UI_AnimateTooltip, Qt.UIEffect.UI_FadeTooltip):
            QApplication.setEffectEnabled(eff, on)


def level() -> str:
    return _level


def allow(kind: str) -> bool:
    """kind: hover, glow, press, transition, fade, chart, gauge"""
    if _level == "off":
        return False
    if _level == "reduced":
        return kind in ("transition", "fade")
    return True


def ms(full: int) -> int:
    return 0 if _level == "off" else full


# ---- Gemeinsamer Taktgeber (30 Bilder/s, nur aktiv solange etwas animiert) ----------
class Ticker(QObject):
    def __init__(self):
        super().__init__()
        self._subs: dict[int, Callable[[float], bool]] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._last = time.perf_counter()

    def add(self, key: object, fn: Callable[[float], bool]) -> None:
        """fn(dt) gibt True zurück, solange weiter animiert werden soll."""
        self._subs[id(key)] = fn
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def remove(self, key: object) -> None:
        self._subs.pop(id(key), None)
        if not self._subs:
            self._timer.stop()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = now - self._last
        self._last = now
        for k, fn in list(self._subs.items()):
            try:
                keep = fn(dt)
            except RuntimeError:  # Widget bereits gelöscht
                keep = False
            if not keep:
                self._subs.pop(k, None)
        if not self._subs:
            self._timer.stop()


_ticker: Ticker | None = None


def ticker() -> Ticker:
    global _ticker
    if _ticker is None:
        _ticker = Ticker()
    return _ticker


# ---- Hilfen -------------------------------------------------------------------------
def value_anim(parent: QObject, duration: int, on_value: Callable[[float], None], start: float = 0.0,
               end: float = 1.0, curve=EASE) -> QVariantAnimation:
    a = QVariantAnimation(parent)
    a.setStartValue(float(start))
    a.setEndValue(float(end))
    a.setDuration(duration)
    a.setEasingCurve(curve)
    a.valueChanged.connect(lambda v: on_value(float(v)))
    return a


def fade_in(widget: QWidget, duration: int = 220, delay: int = 0) -> None:
    """Weiches Einblenden. Der Effekt wird danach entfernt (kostet dann nichts mehr)."""
    if not allow("fade") or not widget.isVisible() and not widget.parentWidget():
        return
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(EASE)

    def done():
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass

    anim.finished.connect(done)
    if delay:
        QTimer.singleShot(delay, anim.start)
    else:
        anim.start()


def fade_window(win: QWidget, duration: int = 180) -> None:
    """Blendet ein Fenster weich ein. Die Fenster-Deckkraft setzt der Windows-Compositor (GPU) um."""
    if not allow("fade"):
        return
    win.setWindowOpacity(0.0)
    a = QPropertyAnimation(win, b"windowOpacity", win)
    a.setDuration(duration)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(EASE)
    QTimer.singleShot(0, a.start)


def install(app: QApplication, setting: str) -> None:
    set_level(setting)

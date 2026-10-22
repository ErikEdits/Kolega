"""Zentrale Signale und automatische Aktualisierung bei Sprach- oder Designwechsel.

bind_text(widget, "schluessel") sorgt dafür, dass der Text eines Widgets bei
einem Sprachwechsel automatisch neu gesetzt wird. bind_icon(...) macht dasselbe
für Symbole bei einem Designwechsel.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import shiboken6
from PySide6.QtCore import QObject, Signal

from corecontrol.i18n import tr
from corecontrol.ui import icons
from corecontrol.ui.theme import theme

log = logging.getLogger(__name__)


class UiBus(QObject):
    language_changed = Signal()
    navigate = Signal(str)  # Seiten-ID
    diagnosis_updated = Signal(object)  # DiagnosisResult
    status_message = Signal(str)


bus = UiBus()

_text_bindings: list[tuple[Any, str, str, dict]] = []
_icon_bindings: list[tuple[Any, str, str, int, str]] = []
_callbacks: list[tuple[Any, Callable[[], None]]] = []


def _apply_text(widget: Any, setter: str, key: str, params: dict) -> None:
    text = tr(key, **params)
    if setter == "setText" and hasattr(widget, "setAutoRepeat"):  # Schaltflächen: & ist sonst ein Tastenkürzel
        text = text.replace("&", "&&")
    getattr(widget, setter)(text)


def bind_text(widget: Any, key: str, setter: str = "setText", **params: Any):
    _text_bindings.append((widget, setter, key, params))
    _apply_text(widget, setter, key, params)
    return widget


def bind_icon(widget: Any, name: str, role: str = "text2", size: int = 18, setter: str = "setIcon"):
    _icon_bindings.append((widget, name, role, size, setter))
    _apply_icon(widget, name, role, size, setter)
    return widget


def _apply_icon(widget, name, role, size, setter):
    color = theme.palette.color(role)
    if setter == "setPixmap":
        widget.setPixmap(icons.pixmap(name, color, size))
    else:
        widget.setIcon(icons.icon(name, color, size))
        if hasattr(widget, "setIconSize"):
            widget.setIconSize(icons.qsize(size))


def on_refresh(owner: Any, cb: Callable[[], None]) -> None:
    """Ruft cb bei Sprach- und Designwechsel auf, solange owner existiert."""
    _callbacks.append((owner, cb))


def _alive(w: Any) -> bool:
    try:
        return shiboken6.isValid(w)
    except Exception:
        return True


def _refresh_texts() -> None:
    alive = []
    for b in _text_bindings:
        w, setter, key, params = b
        if _alive(w):
            try:
                _apply_text(w, setter, key, params)
                alive.append(b)
            except RuntimeError:
                pass
    _text_bindings[:] = alive
    _run_callbacks()


def _refresh_icons() -> None:
    alive = []
    for b in _icon_bindings:
        if _alive(b[0]):
            try:
                _apply_icon(*b)
                alive.append(b)
            except RuntimeError:
                pass
    _icon_bindings[:] = alive
    _run_callbacks()


def _run_callbacks() -> None:
    alive = []
    for owner, cb in _callbacks:
        if _alive(owner):
            try:
                cb()
            except Exception:
                log.exception("Fehler beim Aktualisieren der Oberfläche")
            alive.append((owner, cb))
    _callbacks[:] = alive


bus.language_changed.connect(_refresh_texts)
theme.changed.connect(_refresh_icons)

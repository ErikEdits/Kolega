"""Meldungsfenster mit weichem Einblenden (statt der statischen QMessageBox-Funktionen)."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from corecontrol.ui.anim import fade_window


def _box(parent, icon, title: str, text: str, buttons) -> QMessageBox:
    box = QMessageBox(icon, title, text, buttons, parent)
    fade_window(box)
    return box


def info(parent, title: str, text: str) -> None:
    _box(parent, QMessageBox.Icon.Information, title, text, QMessageBox.StandardButton.Ok).exec()


def warn(parent, title: str, text: str) -> None:
    _box(parent, QMessageBox.Icon.Warning, title, text, QMessageBox.StandardButton.Ok).exec()


def ask(parent, title: str, text: str) -> bool:
    box = _box(parent, QMessageBox.Icon.Question, title, text,
               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes

"""Hilfsfunktion für Entwickler: speichert Bilder aller Seiten (für Dokumentation und Tests)."""

from __future__ import annotations

import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from corecontrol.ui.main_window import NAV, NAV_BOTTOM


def take_screenshots(ctx, window, folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    pages = [n[0] for n in NAV + NAV_BOTTOM if n[0]]
    only = os.environ.get("CC_SHOTS")
    if only:
        pages = [p for p in pages if p in only.split(",")]
    window.resize(int(os.environ.get("CC_SHOT_W", "1320")), int(os.environ.get("CC_SHOT_H", "860")))
    window.show()
    wait = int(os.environ.get("CC_SHOT_WAIT", "2500"))
    state = {"i": 0}

    def step():
        if state["i"] >= len(pages):
            QApplication.instance().quit()
            return
        pid = pages[state["i"]]
        window.navigate(pid)
        QTimer.singleShot(wait, lambda: shot(pid))

    def shot(pid):
        window.grab().save(os.path.join(folder, f"{pid}.png"))
        state["i"] += 1
        step()

    QTimer.singleShot(int(os.environ.get("CC_SHOT_START", "2500")), step)

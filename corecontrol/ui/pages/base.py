"""Basisklasse für alle Seiten."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from corecontrol.ui.widgets.common import PageHeader, ScrollPage


class Page(QWidget):
    page_id = ""
    title_key = ""
    subtitle_key: str | None = None
    scrollable = True

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("pageRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = PageHeader(self.title_key, self.subtitle_key)
        if self.scrollable:
            self.scroll = ScrollPage()
            outer.addWidget(self.scroll)
            self.body = self.scroll.content
            self.body.addWidget(self.header)
        else:
            self.scroll = None
            container = QWidget()
            container.setObjectName("pageRoot")
            self.body = QVBoxLayout(container)
            self.body.setContentsMargins(32, 26, 32, 24)
            self.body.setSpacing(16)
            self.body.addWidget(self.header)
            outer.addWidget(container)

    def finish(self) -> None:
        """Am Ende des Aufbaus aufrufen, damit Inhalte oben bleiben."""
        if self.scrollable:
            self.body.addStretch(1)

    # Hooks ---------------------------------------------------------------
    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass

    def on_sample(self, sample) -> None:
        pass

"""Windows-Fehlerprotokolle verständlich zusammengefasst."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from corecontrol.core import fmt
from corecontrol.core.platform import IS_WINDOWS
from corecontrol.diagnostics.eventlog import BUGCHECKS, read_events
from corecontrol.i18n import has, tr
from corecontrol.system.tools import run_tool
from corecontrol.ui import icons
from corecontrol.ui.bus import on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.theme import theme
from corecontrol.ui.widgets.common import Chip, EmptyState, button, label, set_role
from corecontrol.ui.widgets.finding import SEV_ICON
from corecontrol.ui.workers import run_task


class EventGroupCard(QFrame):
    def __init__(self, g):
        super().__init__()
        self.g = g
        set_role(self, "finding", level=g.severity if g.severity != "ok" else "ok")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(10)
        ic = QLabel()
        name, role = SEV_ICON.get(g.severity, SEV_ICON["info"])
        ic.setPixmap(icons.pixmap(name, theme.palette.color(role), 20))
        ic.setFixedSize(22, 22)
        head.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(self._title())
        t.setWordWrap(True)
        t.setStyleSheet("font-weight: 600; font-size: 14px;")
        col.addWidget(t)
        sub = label(None, "muted", text=tr("ev.count_line", n=g.count, first=fmt.datetime_(g.first), last=fmt.datetime_(g.last)),
                    wrap=True)
        col.addWidget(sub)
        head.addLayout(col, 1)
        head.addWidget(Chip(tr(f"severity.{g.severity}"), g.severity if g.severity != "ok" else "neutral"), 0, Qt.AlignmentFlag.AlignTop)
        self.tbtn = QToolButton()
        self.tbtn.setIcon(icons.icon("chevron-down", theme.palette.text2, 18))
        self.tbtn.clicked.connect(self._toggle)
        head.addWidget(self.tbtn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setContentsMargins(32, 4, 0, 0)
        self.details.setText(self._details_html())
        self.details.setVisible(False)
        lay.addWidget(self.details)

    def _title(self) -> str:
        g = self.g
        key = f"ev.cat.{g.category}.title"
        if g.category != "other" and has(key):
            return tr(key)
        return tr("ev.other_title", provider=g.provider, id=g.event_id)

    def _details_html(self) -> str:
        g = self.g
        parts = []
        key = f"ev.cat.{g.category}.text"
        parts.append(escape(tr(key) if has(key) else tr("ev.other_text")))
        if g.details:
            items = []
            for k, n in g.details.most_common(8):
                label_txt = k
                if g.category in ("bluescreen", "unexpected_shutdown"):
                    try:
                        name = BUGCHECKS.get(int(k, 16), ("", ""))[0]
                        label_txt = f"{k} {name}".strip()
                    except ValueError:
                        pass
                items.append(f"<li>{escape(label_txt)}: {n}×</li>")
            parts.append(f"<b>{escape(tr('ev.details'))}</b><ul style='margin:0 0 0 -22px'>{''.join(items)}</ul>")
        ex = []
        for rec in g.examples[:3]:
            msg = (rec.message or "").strip().replace("\r", "")
            if len(msg) > 600:
                msg = msg[:600] + " …"
            ex.append(f"<p style='margin:4px 0'><b>{escape(fmt.datetime_(rec.time))}</b> · {escape(rec.provider)} · "
                      f"ID {rec.event_id}<br>{escape(msg) if msg else '<i>' + escape(tr('ev.no_message')) + '</i>'}</p>")
        if ex:
            parts.append(f"<b>{escape(tr('ev.examples'))}</b>{''.join(ex)}")
        return "<br>".join(parts)

    def _toggle(self):
        v = not self.details.isVisible()
        self.details.setVisible(v)
        self.tbtn.setIcon(icons.icon("chevron-up" if v else "chevron-down", theme.palette.text2, 18))


class EventsPage(Page):
    page_id = "events"
    title_key = "ev.title"
    subtitle_key = "ev.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.days = QComboBox()
        for d in (1, 7, 30, 90):
            self.days.addItem(tr("ev.days", n=d), d)
        self.days.setCurrentIndex(2)
        self.days.currentIndexChanged.connect(lambda *_: self.load())
        self.header.add_action(self.days)
        self.header.add_action(button("common.refresh", None, "refresh-cw", self.load))
        if IS_WINDOWS:
            self.header.add_action(button("ev.reliability", None, "chart-line", lambda: run_tool("reliability")))
            self.header.add_action(button("ev.viewer", None, "scroll-text", lambda: run_tool("eventvwr")))
        self.status = label(None, "muted", text="", wrap=True)
        self.body.addWidget(self.status)
        self.hide_harmless = True
        self.list_host = QWidget()
        self.list = QVBoxLayout(self.list_host)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(10)
        self.body.addWidget(self.list_host)
        self.empty = EmptyState("scroll-text", "ev.empty_title", "ev.empty_text")
        self.empty.setVisible(False)
        self.body.addWidget(self.empty)
        self.body.addWidget(label("ev.note", "faint", wrap=True))
        self.finish()
        self.summary = None
        self._loading = False
        on_refresh(self, self.render)

    def on_show(self):
        if self.summary is None:
            res = self.ctx.diagnosis_result
            if res is not None and res.events is not None and getattr(res.events, "days", None) == self.days.currentData():
                self.summary = res.events
                self.render()
            else:
                self.load()

    def load(self):
        if self._loading:
            return
        self._loading = True
        self.status.setText(tr("ev.loading"))

        def done(summary):
            self._loading = False
            self.summary = summary
            self.render()

        def failed(exc):
            self._loading = False
            self.status.setText(tr("common.action_failed", error=str(exc)))

        run_task(read_events, self.days.currentData(), on_done=done, on_error=failed, context="events")

    def render(self):
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        s = self.summary
        if s is None:
            return
        if not s.available:
            self.status.setText(tr("common.only_windows"))
            self.empty.setVisible(False)
            return
        groups = [g for g in s.groups if not (self.hide_harmless and g.category == "harmless_dcom")]
        harmless = sum(g.count for g in s.groups if g.category == "harmless_dcom")
        txt = tr("ev.status", total=s.total, days=s.days, groups=len(groups))
        if harmless:
            txt += " " + tr("ev.harmless", n=harmless)
        if s.read_errors:
            txt += " " + tr("ev.read_errors", errors="; ".join(s.read_errors))
        self.status.setText(txt)
        self.empty.setVisible(not groups)
        for g in groups:
            self.list.addWidget(EventGroupCard(g))

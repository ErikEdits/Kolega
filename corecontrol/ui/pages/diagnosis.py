"""Seite „Systemdiagnose“ – das Herzstück von CoreControl."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from corecontrol.core import fmt
from corecontrol.diagnostics.engine import STEPS
from corecontrol.i18n import tr
from corecontrol.ui import icons
from corecontrol.ui.bus import bind_text, bus, on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.controls import AnimatedButton
from corecontrol.ui.theme import theme
from corecontrol.ui.widgets.common import Card, Chip, EmptyState, button, icon_label, label, set_role
from corecontrol.ui.widgets.finding import FindingCard


class DiagnosisPage(Page):
    page_id = "diagnosis"
    title_key = "diagp.title"
    subtitle_key = "diagp.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.run_btn = button("diagp.run", "primary", "play", self._run)
        self.report_btn = button("diagp.report", None, "file-text", lambda: bus.navigate.emit("reports"))
        self.header.add_action(self.report_btn)
        self.header.add_action(self.run_btn)

        # Fortschritt
        self.progress_card = Card("diagp.running", "refresh-cw")
        self.bar = QProgressBar()
        self.bar.setRange(0, len(STEPS) * 100)
        self.progress_card.add(self.bar)
        from corecontrol.ui import anim
        from PySide6.QtCore import QPropertyAnimation

        self._bar_anim = QPropertyAnimation(self.bar, b"value", self)
        self._bar_anim.setDuration(400)
        self._bar_anim.setEasingCurve(anim.EASE)
        self.step_label = label(None, "muted", text="")
        self.progress_card.add(self.step_label)
        self.progress_card.setVisible(False)
        self.body.addWidget(self.progress_card)

        # Zusammenfassung
        self.summary = Card(None)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.sum_icon = QLabel()
        self.sum_icon.setFixedSize(52, 52)
        row.addWidget(self.sum_icon, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.sum_title = label(None, "h2", text="")
        self.sum_text = label(None, "muted", text="", wrap=True)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chips = {lvl: Chip("", lvl) for lvl in ("critical", "warning", "info", "ok")}
        for c in self.chips.values():
            chips.addWidget(c)
        chips.addStretch(1)
        col.addWidget(self.sum_title)
        col.addWidget(self.sum_text)
        col.addLayout(chips)
        row.addLayout(col, 1)
        self.summary.add_layout(row)
        self.body.addWidget(self.summary)

        # Filter
        frow = QHBoxLayout()
        frow.setSpacing(6)
        self.filter_group = QButtonGroup(self)
        self.filter = "problems"
        for key, text_key in (("problems", "diagp.filter_problems"), ("all", "diagp.filter_all"), ("ok", "diagp.filter_ok")):
            b = AnimatedButton()
            bind_text(b, text_key)
            set_role(b, "filter")
            b.setCheckable(True)
            b.setChecked(key == self.filter)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda *_, k=key: self._set_filter(k))
            self.filter_group.addButton(b)
            frow.addWidget(b)
        frow.addStretch(1)
        self.filter_row = QWidget()
        self.filter_row.setLayout(frow)
        self.body.addWidget(self.filter_row)

        self.list_host = QWidget()
        self.list = QVBoxLayout(self.list_host)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(10)
        self.body.addWidget(self.list_host)

        self.skipped_card = Card("diagp.skipped", "circle-help")
        self.skipped_text = label(None, "muted", text="", wrap=True)
        self.skipped_card.add(label("diagp.skipped_desc", "faint", wrap=True))
        self.skipped_card.add(self.skipped_text)
        self.body.addWidget(self.skipped_card)

        self.empty = EmptyState("stethoscope", "diagp.empty_title", "diagp.empty_text")
        self.body.addWidget(self.empty)
        self.disclaimer = label("diagp.disclaimer", "faint", wrap=True)
        self.body.addWidget(self.disclaimer)
        self.finish()

        ctx.diagnosis_started.connect(self._started)
        ctx.diagnosis_progress.connect(self._progress)
        self._animate_next = False
        ctx.diagnosis_finished.connect(self._finished)
        on_refresh(self, self.render)
        self.render()

    def _run(self):
        self.ctx.run_diagnosis()

    def _finished(self, *_):
        self._animate_next = True
        self.render()

    def _set_filter(self, key):
        self.filter = key
        self.render()

    def _started(self):
        self.bar.setValue(0)
        self.step_label.setText(tr("diagp.step.live"))
        self.render()

    def _progress(self, step):
        from corecontrol.ui import anim

        if step in STEPS:
            target = STEPS.index(step) * 100
            if anim.allow("fade"):
                self._bar_anim.stop()
                self._bar_anim.setStartValue(self.bar.value())
                self._bar_anim.setEndValue(target)
                self._bar_anim.start()
            else:
                self.bar.setValue(target)
            self.step_label.setText(tr(f"diagp.step.{step}"))

    def render(self):
        running = self.ctx.diagnosis_running
        res = self.ctx.diagnosis_result
        self.run_btn.setEnabled(not running)
        self.progress_card.setVisible(running)
        self.empty.setVisible(res is None and not running)
        self.summary.setVisible(res is not None)
        self.filter_row.setVisible(res is not None)
        self.skipped_card.setVisible(bool(res and res.skipped))
        self.report_btn.setEnabled(res is not None)
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        if res is None:
            return
        crit, warn, info, ok = (res.count(x) for x in ("critical", "warning", "info", "ok"))
        if crit:
            ic, role, title = "octagon-x", "crit", tr("diagp.sum_crit", n=crit)
        elif warn:
            ic, role, title = "triangle-alert", "warn", tr("diagp.sum_warn", n=warn)
        else:
            ic, role, title = "circle-check", "ok", tr("diagp.sum_ok")
        self.sum_icon.setPixmap(icons.pixmap(ic, theme.palette.color(role), 48))
        self.sum_title.setText(title)
        self.sum_text.setText(tr("diagp.sum_text", when=fmt.datetime_(res.finished_at),
                                 secs=fmt.number(res.finished_at - res.started_at, 0)))
        for lvl, n in (("critical", crit), ("warning", warn), ("info", info), ("ok", ok)):
            self.chips[lvl].setText(f"{n} {tr(f'diagp.chip.{lvl}')}")
            self.chips[lvl].setVisible(n > 0 or lvl == "ok")
        items = res.sorted()
        if self.filter == "problems":
            problems = [f for f in items if f.severity != "ok"]
            if not problems:
                self.list.addWidget(label("diagp.no_problems_checked", "muted", wrap=True))
                problems = items
            items = problems
        elif self.filter == "ok":
            items = [f for f in items if f.severity == "ok"]
        if not items:
            self.list.addWidget(label("diagp.no_items", "muted"))
        from corecontrol.ui import anim

        for i, f in enumerate(items):
            card = FindingCard(f, expanded=f.severity == "critical")
            self.list.addWidget(card)
            if self._animate_next and i < 12:
                anim.fade_in(card, 240, 35 * i)
        self._animate_next = False
        self.skipped_text.setText("\n".join(f"• {reason}" for _, reason in res.skipped))

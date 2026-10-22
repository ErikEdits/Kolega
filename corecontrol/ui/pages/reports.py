"""Berichte und Fehlerfeedback."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QMessageBox, QPlainTextEdit

from corecontrol import REPO_URL
from corecontrol.core import paths
from corecontrol.core.logging_setup import add_error_listener, read_log_tail, recent_errors
from corecontrol.core.platform import open_path, open_url
from corecontrol.i18n import tr
from corecontrol.reports.feedback import build_feedback
from corecontrol.reports.report import build_report, make_redactor, save_report
from corecontrol.ui.bus import bind_text, on_refresh
from corecontrol.ui.dialogs import show_text_dialog
from corecontrol.ui import msg
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.common import Card, button, label


class ReportsPage(Page):
    page_id = "reports"
    title_key = "rep.page_title"
    subtitle_key = "rep.page_subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        # Diagnosebericht
        card = Card("rep.card_report", "file-text")
        card.add(label("rep.card_report_desc", "muted", wrap=True))
        self.diag_state = label(None, "faint", text="", wrap=True)
        card.add(self.diag_state)
        self.redact = QCheckBox()
        bind_text(self.redact, "rep.redact")
        self.redact.setChecked(ctx.settings.get("report.redact"))
        self.redact.toggled.connect(lambda v: ctx.settings.set("report.redact", bool(v)))
        card.add(self.redact)
        card.add(label("rep.note_label", "h3"))
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText(tr("rep.note_placeholder"))
        self.note.setFixedHeight(80)
        card.add(self.note)
        row = QHBoxLayout()
        self.run_btn = button("dash.run_diagnosis", None, "play", lambda: ctx.run_diagnosis())
        row.addWidget(self.run_btn)
        row.addWidget(button("rep.preview", None, "eye", self._preview))
        row.addWidget(button("rep.save_html", "primary", "save", lambda: self._save("html")))
        row.addWidget(button("rep.save_txt", None, "file-down", lambda: self._save("txt")))
        row.addStretch(1)
        card.add_layout(row)
        self.body.addWidget(card)

        # Fehlerfeedback
        fb = Card("rep.card_feedback", "bug")
        fb.add(label("rep.card_feedback_desc", "muted", wrap=True))
        self.err_state = label(None, "faint", text="", wrap=True)
        fb.add(self.err_state)
        fb.add(label("rep.fb_label", "h3"))
        self.fb_text = QPlainTextEdit()
        self.fb_text.setPlaceholderText(tr("rep.fb_placeholder"))
        self.fb_text.setFixedHeight(90)
        fb.add(self.fb_text)
        r2 = QHBoxLayout()
        r2.addWidget(button("rep.show_log", None, "scroll-text", self._show_log))
        r2.addWidget(button("rep.export_feedback", "primary", "save", self._export_feedback))
        r2.addWidget(button("rep.open_logs", None, "folder-open", lambda: open_path(str(paths.log_dir()))))
        r2.addWidget(button("rep.github", "ghost", "external-link", lambda: open_url(f"{REPO_URL}/issues")))
        r2.addStretch(1)
        fb.add_layout(r2)
        fb.add(label("rep.privacy", "faint", wrap=True))
        self.body.addWidget(fb)
        self.finish()
        ctx.diagnosis_finished.connect(lambda *_: self._update_state())
        ctx.diagnosis_started.connect(self._update_state)
        add_error_listener(lambda _rec: None)
        on_refresh(self, self._update_state)
        self._update_state()

    def on_show(self):
        self._update_state()

    def _update_state(self):
        res = self.ctx.diagnosis_result
        if self.ctx.diagnosis_running:
            self.diag_state.setText(tr("dash.diag_running"))
        elif res is None:
            self.diag_state.setText(tr("rep.state_none"))
        else:
            from corecontrol.core import fmt

            self.diag_state.setText(tr("rep.state_ok", when=fmt.datetime_(res.finished_at)))
        self.run_btn.setEnabled(not self.ctx.diagnosis_running)
        n = len(recent_errors())
        self.err_state.setText(tr("rep.errors_none") if n == 0 else tr("rep.errors_some", n=n))

    def _build(self):
        res = self.ctx.diagnosis_result
        hw = self.ctx.hardware
        sample = self.ctx.sampler.store.latest() if self.ctx.sampler else None
        red = make_redactor(self.redact.isChecked(), res, self.ctx.settings.all())
        return build_report(res, hw, sample, self.note.toPlainText(), red)

    def _preview(self):
        show_text_dialog(self, tr("rep.preview"), self._build().text())

    def _save(self, kind: str):
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        default = str(Path.home() / "Documents" / f"CoreControl-Bericht_{stamp}.{kind}")
        if not Path(default).parent.exists():
            default = str(Path.home() / f"CoreControl-Bericht_{stamp}.{kind}")
        flt = "HTML (*.html)" if kind == "html" else "Text (*.txt)"
        path, _ = QFileDialog.getSaveFileName(self, tr("rep.save_html" if kind == "html" else "rep.save_txt"), default, flt)
        if not path:
            return
        try:
            saved = save_report(self._build(), Path(path))
        except OSError as exc:
            msg.warn(self, tr("common.error"), tr("rep.save_failed", error=str(exc)))
            return
        self.ctx.activity.add("ok", "act.report", "reports", kind=kind.upper())
        if msg.ask(self, tr("rep.saved_title"), tr("rep.saved", path=str(saved))):
            open_path(str(saved))

    def _show_log(self):
        text = read_log_tail(500) or tr("rep.log_empty")
        show_text_dialog(self, tr("rep.show_log"), text)

    def _export_feedback(self):
        red = make_redactor(True, self.ctx.diagnosis_result, self.ctx.settings.all())
        text = build_feedback(self.fb_text.toPlainText(), self.ctx.settings.all(), red)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        path, _ = QFileDialog.getSaveFileName(self, tr("rep.export_feedback"),
                                              str(Path.home() / f"CoreControl-Fehlerbericht_{stamp}.txt"), "Text (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            msg.warn(self, tr("common.error"), tr("rep.save_failed", error=str(exc)))
            return
        msg.info(self, tr("rep.saved_title"), tr("rep.feedback_saved", path=path))

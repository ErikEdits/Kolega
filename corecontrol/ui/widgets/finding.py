"""Darstellung eines Diagnose-Befunds als aufklappbare Karte."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from corecontrol.diagnostics.models import Finding
from corecontrol.i18n import tr
from corecontrol.system.tools import run_action
from corecontrol.ui import icons
from corecontrol.ui.theme import theme
from corecontrol.ui.widgets.common import Chip, set_role

SEV_ICON = {"critical": ("octagon-x", "crit"), "warning": ("triangle-alert", "warn"), "info": ("info", "info"),
            "ok": ("circle-check", "ok")}


def finding_lines(items) -> list[str]:
    out: list[str] = []
    for t in items or []:
        out.extend(t.lines() if hasattr(t, "lines") else [str(t)])
    return out


class FindingCard(QFrame):
    def __init__(self, finding: Finding, expanded: bool = False):
        super().__init__()
        self.f = finding
        set_role(self, "finding")
        self.setProperty("level", finding.severity)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(22, 22)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.detected = QLabel()
        self.detected.setWordWrap(True)
        set_role(self.detected, "muted")
        self.detected.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tcol.addWidget(self.title)
        tcol.addWidget(self.detected)
        head.addLayout(tcol, 1)
        self.sev_chip = Chip("", finding.severity)
        head.addWidget(self.sev_chip, 0, Qt.AlignmentFlag.AlignTop)
        self.toggle = QToolButton()
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.clicked.connect(self._toggle)
        head.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        self.details = QWidget()
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(32, 6, 0, 2)
        dl.setSpacing(10)
        self.extra = self._section(dl)
        self.causes = self._section(dl)
        self.recs = self._section(dl)
        self.risks = self._section(dl)
        self.conf = self._section(dl)
        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(8)
        dl.addLayout(self.actions_row)
        lay.addWidget(self.details)
        self._expanded = expanded
        self.details.setVisible(expanded)
        self.has_details = bool(finding.causes or finding.recommendations or finding.risks or finding.uncertainty
                                or finding.evidence.get("extra_detected") or finding.actions)
        self.toggle.setVisible(self.has_details)
        if finding.severity == "ok" and not finding.actions:
            self.toggle.setVisible(False)
        self.render()
        theme.changed.connect(self._update_icons)

    def _section(self, parent_layout) -> tuple[QLabel, QLabel]:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        cap = QLabel()
        set_role(cap, "caption")
        body = QLabel()
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(cap)
        v.addWidget(body)
        parent_layout.addWidget(w)
        return cap, body, w  # type: ignore[return-value]

    @staticmethod
    def _bullets(lines: list[str], numbered: bool = False) -> str:
        from html import escape

        if not lines:
            return ""
        tag = "ol" if numbered else "ul"
        items = "".join(f"<li style='margin-bottom:3px'>{escape(x)}</li>" for x in lines)
        return f"<{tag} style='margin:0 0 0 -22px;'>{items}</{tag}>"

    def _fill(self, sec, caption: str, html: str) -> None:
        cap, body, w = sec
        w.setVisible(bool(html))
        cap.setText(caption.upper())
        body.setText(html)

    def render(self) -> None:
        from html import escape

        f = self.f
        self.title.setText(str(f.title))
        self.detected.setText(str(f.detected))
        self.sev_chip.setText(tr(f"severity.{f.severity}"))
        self._fill(self.extra, tr("finding.measured"), self._bullets(finding_lines(f.evidence.get("extra_detected"))))
        self._fill(self.causes, tr("finding.causes"), self._bullets(finding_lines(f.causes)))
        self._fill(self.recs, tr("finding.recommendations"), self._bullets(finding_lines(f.recommendations), numbered=True))
        self._fill(self.risks, tr("finding.risks"), escape(str(f.risks)) if f.risks else "")
        conf = tr(f"confidence.{f.confidence}")
        unc = f" – {escape(str(f.uncertainty))}" if f.uncertainty else ""
        self._fill(self.conf, tr("finding.confidence"), f"<b>{escape(conf)}</b>{unc}" if f.severity != "ok" else "")
        while self.actions_row.count():
            it = self.actions_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for key, action in f.actions:
            b = QPushButton(tr(key))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda *_, a=action: run_action(a))
            self.actions_row.addWidget(b)
        self.actions_row.addStretch(1)
        self._update_icons()

    def _update_icons(self) -> None:
        name, role = SEV_ICON.get(self.f.severity, SEV_ICON["info"])
        self.icon.setPixmap(icons.pixmap(name, theme.palette.color(role), 20))
        self.toggle.setIcon(icons.icon("chevron-up" if self._expanded else "chevron-down", theme.palette.text2, 18))
        self.toggle.setToolTip(tr("finding.collapse" if self._expanded else "finding.expand"))

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self.details.setVisible(self._expanded)
        self._update_icons()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.has_details and self.toggle.isVisible() \
                and ev.position().y() < 60:
            self._toggle()
        super().mouseReleaseEvent(ev)

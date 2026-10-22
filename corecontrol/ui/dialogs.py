"""Dialoge: Text anzeigen und Bestätigungen mit genauer Auflistung, was passieren wird."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from corecontrol.i18n import tr
from corecontrol.ui.widgets.common import icon_label, set_role


def show_text_dialog(parent, title: str, text: str, copy: bool = True) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(760, 560)
    lay = QVBoxLayout(dlg)
    edit = QPlainTextEdit(text)
    edit.setReadOnly(True)
    lay.addWidget(edit)
    btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    if copy:
        cbtn = QPushButton(tr("common.copy"))
        cbtn.clicked.connect(lambda: QApplication.clipboard().setText(text))
        btns.addButton(cbtn, QDialogButtonBox.ButtonRole.ActionRole)
    btns.rejected.connect(dlg.reject)
    btns.accepted.connect(dlg.accept)
    lay.addWidget(btns)
    dlg.exec()


class ConfirmDialog(QDialog):
    """Bestätigung mit Überschrift, Erklärung, Details (z. B. Dateiliste) und optionaler Häkchen-Pflicht."""

    def __init__(self, parent, title: str, message: str, details: str = "", confirm_text: str | None = None,
                 danger: bool = False, require_check: str | None = None, icon: str = "triangle-alert"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(icon_label(icon, "crit" if danger else "warn", 26), 0, Qt.AlignmentFlag.AlignTop)
        t = QLabel(title)
        set_role(t, "h2")
        t.setWordWrap(True)
        head.addWidget(t, 1)
        lay.addLayout(head)
        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(msg)
        if details:
            box = QPlainTextEdit(details)
            box.setReadOnly(True)
            box.setMinimumHeight(180)
            lay.addWidget(box, 1)
        self.check = None
        if require_check:
            self.check = QCheckBox(require_check)
            lay.addWidget(self.check)
        btns = QDialogButtonBox()
        self.ok = QPushButton(confirm_text or tr("common.ok"))
        set_role(self.ok, "danger" if danger else "primary")
        cancel = QPushButton(tr("common.cancel"))
        btns.addButton(self.ok, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        cancel.setDefault(True)
        cancel.setFocus()
        lay.addWidget(btns)
        if self.check is not None:
            self.ok.setEnabled(False)
            self.check.toggled.connect(self.ok.setEnabled)

    @staticmethod
    def ask(parent, *args, **kwargs) -> bool:
        return ConfirmDialog(parent, *args, **kwargs).exec() == QDialog.DialogCode.Accepted

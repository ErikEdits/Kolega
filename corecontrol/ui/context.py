"""Gemeinsamer Zustand der Anwendung (Einstellungen, Messung, Diagnose, Verlauf)."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal

from corecontrol.core.settings import Settings

log = logging.getLogger(__name__)


class AppContext(QObject):
    diagnosis_started = Signal()
    diagnosis_progress = Signal(object)
    diagnosis_finished = Signal(object)
    hardware_ready = Signal(object)
    setting_changed = Signal(str, object)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.sampler = None
        self.history = None
        self.alerts = None
        self.main_window = None
        self.tray = None
        self.diagnosis_result = None
        self.diagnosis_running = False
        self.last_network = None
        self.hardware: dict[str, Any] | None = None
        self._hardware_loading = False
        from corecontrol.core import paths
        from corecontrol.core.activity import ActivityLog

        try:
            self.activity = ActivityLog(paths.data_dir() / "activity.json")
        except Exception:
            self.activity = ActivityLog(None)
        settings.on_change(lambda k, v: self.setting_changed.emit(k, v))

    # ---- Diagnose ---------------------------------------------------------
    def run_diagnosis(self, include_network: bool | None = None) -> bool:
        if self.diagnosis_running:
            return False
        from corecontrol.diagnostics.engine import run_full_diagnosis
        from corecontrol.ui.workers import run_task

        if include_network is None:
            include_network = self.settings.get("network.include_in_diagnosis")
        self.diagnosis_running = True
        self.diagnosis_started.emit()
        live = self.sampler.store if self.sampler else None

        def done(result):
            self.diagnosis_running = False
            self.diagnosis_result = result
            if result is not None and result.hardware:
                self.hardware = result.hardware
            if result is not None and result.network is not None:
                self.last_network = result.network
            if result is not None:
                crit, warn = result.count("critical"), result.count("warning")
                if crit:
                    self.activity.add("critical", "act.diag_crit", "diagnosis", n=crit)
                elif warn:
                    self.activity.add("warning", "act.diag_warn", "diagnosis", n=warn)
                else:
                    self.activity.add("ok", "act.diag_ok", "diagnosis")
            self.diagnosis_finished.emit(result)

        def failed(exc):
            self.diagnosis_running = False
            self.diagnosis_finished.emit(None)

        run_task(run_full_diagnosis, self.settings.all(), live, include_network, self.hardware,
                 on_done=done, on_error=failed, on_progress=self.diagnosis_progress.emit, context="diagnosis")
        return True

    # ---- Hardware ----------------------------------------------------------
    def load_hardware(self, force: bool = False) -> None:
        if self._hardware_loading or (self.hardware is not None and not force):
            if self.hardware is not None and not force:
                self.hardware_ready.emit(self.hardware)
            return
        from corecontrol.monitoring.hardware import collect_hardware
        from corecontrol.ui.workers import run_task

        self._hardware_loading = True

        def done(hw):
            self._hardware_loading = False
            self.hardware = hw
            self.hardware_ready.emit(hw)

        def failed(_):
            self._hardware_loading = False
            self.hardware_ready.emit(None)

        run_task(collect_hardware, on_done=done, on_error=failed, context="hardware")

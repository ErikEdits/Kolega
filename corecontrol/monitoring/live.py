"""Live-Messung in einem eigenen Thread. Die Oberfläche erhält Werte per Signal."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from corecontrol.monitoring.collector import Collector
from corecontrol.monitoring.models import Sample

log = logging.getLogger(__name__)


class LiveStore:
    """Thread-sicherer Ringpuffer der letzten Messungen (Standard: 10 Minuten bei 0,5 s)."""

    def __init__(self, maxlen: int = 1200):
        self._buf: deque[Sample] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, s: Sample) -> None:
        with self._lock:
            self._buf.append(s)

    def latest(self) -> Sample | None:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def window(self, seconds: float) -> list[Sample]:
        with self._lock:
            if not self._buf:
                return []
            end = self._buf[-1].ts
            return [s for s in self._buf if end - s.ts <= seconds]

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


class _Worker(QObject):
    sampled = Signal(object)

    def __init__(self, interval_ms: int, lhm_enabled: bool, lhm_port: int, amd_enabled: bool = True, amd_probe=None):
        super().__init__()
        self.interval_ms = interval_ms
        self.lhm_enabled, self.lhm_port = lhm_enabled, lhm_port
        self.amd_enabled, self.amd_probe = amd_enabled, amd_probe
        self.collector: Collector | None = None
        self.timer: QTimer | None = None
        self.consumers: list[Callable[[Sample], None]] = []

    @Slot()
    def start(self) -> None:
        try:
            self.collector = Collector(self.lhm_enabled, self.lhm_port, self.amd_enabled, self.amd_probe)
        except Exception:
            log.exception("Messung konnte nicht gestartet werden")
            return
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)  # gleichmäßiger Takt auch bei 0,25–0,5 s
        self.timer.timeout.connect(self.tick)
        self.timer.start(self.interval_ms)
        self.tick()

    @Slot()
    def tick(self) -> None:
        if self.collector is None:
            return
        try:
            s = self.collector.sample()
        except Exception:
            log.exception("Messfehler")
            return
        for c in list(self.consumers):
            try:
                c(s)
            except Exception:
                log.exception("Fehler bei der Weiterverarbeitung einer Messung")
        self.sampled.emit(s)

    @Slot(int)
    def set_interval(self, ms: int) -> None:
        self.interval_ms = ms
        if self.timer is not None:
            self.timer.setInterval(ms)

    @Slot(bool, int)
    def set_lhm(self, enabled: bool, port: int) -> None:
        if self.collector is not None:
            self.collector.set_lhm(enabled, port)

    @Slot(bool)
    def set_amd(self, enabled: bool) -> None:
        self.amd_enabled = enabled
        if self.collector is not None:
            self.collector.set_amd(enabled)

    @Slot()
    def stop(self) -> None:
        if self.timer:
            self.timer.stop()
            self.timer = None  # Timer im eigenen Thread freigeben
        if self.collector:
            self.collector.close()
            self.collector = None


class Sampler(QObject):
    sampled = Signal(object)
    _set_interval = Signal(int)
    _set_lhm = Signal(bool, int)
    _set_amd = Signal(bool)
    _stop = Signal()

    def __init__(self, interval_ms: int = 500, lhm_enabled: bool = True, lhm_port: int = 8085,
                 amd_enabled: bool = True, amd_probe=None):
        super().__init__()
        self.store = LiveStore()
        self.thread = QThread()
        self.thread.setObjectName("sampler")
        self.worker = _Worker(interval_ms, lhm_enabled, lhm_port, amd_enabled, amd_probe)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.sampled.connect(self._on_sample)
        self._set_interval.connect(self.worker.set_interval)
        self._set_lhm.connect(self.worker.set_lhm)
        self._set_amd.connect(self.worker.set_amd)
        self._stop.connect(self.worker.stop, Qt.ConnectionType.BlockingQueuedConnection)
        self.worker.consumers.append(self.store.add)

    def add_consumer(self, fn: Callable[[Sample], None]) -> None:
        """fn wird im Messthread aufgerufen (z. B. für den Verlauf)."""
        self.worker.consumers.append(fn)

    def start(self) -> None:
        self.thread.start()

    def _on_sample(self, s: Sample) -> None:
        self.sampled.emit(s)

    def set_interval(self, ms: int) -> None:
        self._set_interval.emit(int(ms))

    def set_lhm(self, enabled: bool, port: int) -> None:
        self._set_lhm.emit(bool(enabled), int(port))

    def set_amd(self, enabled: bool) -> None:
        self._set_amd.emit(bool(enabled))

    def stop(self) -> None:
        if self.thread.isRunning():
            self._stop.emit()
        self.thread.quit()
        self.thread.wait(3000)

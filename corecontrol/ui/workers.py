"""Hintergrundaufgaben, damit die Oberfläche nie einfriert.

run_task(funktion, on_done=..., on_error=...) führt die Funktion in einem
Thread-Pool aus. Ergebnisse kommen über Qt-Signale sicher im Hauptthread an.
Funktionen, die einen Parameter `ctx` annehmen, erhalten einen TaskContext für
Fortschrittsmeldungen und Abbruch.
"""

from __future__ import annotations

import inspect
import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from corecontrol.core.logging_setup import record_error

log = logging.getLogger(__name__)


class TaskContext:
    def __init__(self, signals: "_Signals"):
        self._signals = signals
        self._cancel = threading.Event()

    def progress(self, value: Any) -> None:
        self._signals.progress.emit(value)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(object)


class TaskHandle:
    def __init__(self, ctx: TaskContext):
        self.ctx = ctx
        self.finished = False

    def cancel(self) -> None:
        self.ctx.cancel()


_active: set["_Runnable"] = set()
_lock = threading.Lock()


class _Runnable(QRunnable):
    def __init__(self, fn: Callable, args, kwargs, context: str):
        super().__init__()
        self.setAutoDelete(False)
        self.fn, self.args, self.kwargs, self.context = fn, args, kwargs, context
        self.signals = _Signals()
        self.ctx = TaskContext(self.signals)
        self.handle = TaskHandle(self.ctx)

    def run(self) -> None:
        try:
            kwargs = dict(self.kwargs)
            try:
                if "ctx" in inspect.signature(self.fn).parameters:
                    kwargs["ctx"] = self.ctx
            except (TypeError, ValueError):
                pass
            result = self.fn(*self.args, **kwargs)
        except Exception as exc:  # Fehler werden gemeldet, nicht weitergeworfen
            record_error(self.context, exc)
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)
        finally:
            self.handle.finished = True


def run_task(
    fn: Callable,
    *args: Any,
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    on_progress: Callable[[Any], None] | None = None,
    context: str = "task",
    **kwargs: Any,
) -> TaskHandle:
    r = _Runnable(fn, args, kwargs, context)

    def _cleanup(*_):
        with _lock:
            _active.discard(r)

    if on_done:
        r.signals.done.connect(on_done)
    if on_error:
        r.signals.failed.connect(on_error)
    if on_progress:
        r.signals.progress.connect(on_progress)
    r.signals.done.connect(_cleanup)
    r.signals.failed.connect(_cleanup)
    with _lock:
        _active.add(r)
    QThreadPool.globalInstance().start(r)
    return r.handle


def wait_all(timeout_ms: int = 3000) -> None:
    QThreadPool.globalInstance().waitForDone(timeout_ms)

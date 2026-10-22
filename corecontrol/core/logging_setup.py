"""Protokollierung in eine lokale Datei (rotierend, max. ca. 3 MB)."""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Callable

from corecontrol.core import paths


@dataclass
class ErrorRecord:
    time: datetime
    context: str
    message: str
    details: str


_errors: deque[ErrorRecord] = deque(maxlen=200)
_listeners: list[Callable[[ErrorRecord], None]] = []
_lock = threading.Lock()


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        fh = RotatingFileHandler(paths.log_file(), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass  # Ohne Schreibrechte läuft die App trotzdem weiter.
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.setLevel(logging.WARNING)
        root.addHandler(sh)


def record_error(context: str, exc: BaseException | None = None, message: str | None = None) -> ErrorRecord:
    """Speichert einen Fehler im Protokoll und benachrichtigt die Oberfläche."""
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else ""
    rec = ErrorRecord(datetime.now(), context, message or (str(exc) if exc else ""), details)
    logging.getLogger("corecontrol.errors").error("%s: %s\n%s", context, rec.message, details)
    with _lock:
        _errors.append(rec)
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(rec)
        except Exception:
            pass
    return rec


def recent_errors() -> list[ErrorRecord]:
    with _lock:
        return list(_errors)


def add_error_listener(cb: Callable[[ErrorRecord], None]) -> None:
    with _lock:
        _listeners.append(cb)


def read_log_tail(max_lines: int = 300) -> str:
    try:
        with open(paths.log_file(), encoding="utf-8", errors="replace") as fh:
            return "".join(deque(fh, maxlen=max_lines))
    except OSError:
        return ""


def install_excepthooks() -> None:
    """Unbehandelte Fehler werden protokolliert statt die App zu beenden."""

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        exc.__traceback__ = tb
        record_error("unhandled", exc)

    def thread_hook(args):
        if args.exc_value is not None:
            record_error(f"thread:{getattr(args.thread, 'name', '?')}", args.exc_value)

    sys.excepthook = hook
    threading.excepthook = thread_hook

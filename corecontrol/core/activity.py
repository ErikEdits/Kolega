"""Verlauf der Aktivitäten in CoreControl („Letzte Ereignisse“ auf dem Dashboard).

Es werden nur tatsächlich passierte Vorgänge festgehalten (Diagnose abgeschlossen,
Warnung erkannt, Bereinigung durchgeführt …). Texte werden als Übersetzungsschlüssel
gespeichert, damit sie nach einem Sprachwechsel in der neuen Sprache erscheinen.
Gespeichert in activity.json (max. 100 Einträge), nur lokal.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

MAX_ENTRIES = 100


@dataclass
class Activity:
    ts: float
    level: str          # ok, info, warning, critical
    key: str            # Übersetzungsschlüssel
    params: dict = field(default_factory=dict)
    target: str = ""    # Seite, die beim Anklicken geöffnet wird


class ActivityLog:
    def __init__(self, path: Path | None = None):
        self.path = path
        self._items: list[Activity] = []
        self._lock = threading.Lock()
        self._listeners: list[Callable[[Activity], None]] = []
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for d in data if isinstance(data, list) else []:
                if isinstance(d, dict) and isinstance(d.get("key"), str) and isinstance(d.get("ts"), (int, float)):
                    params = d.get("params") if isinstance(d.get("params"), dict) else {}
                    self._items.append(Activity(float(d["ts"]), str(d.get("level", "info")), d["key"],
                                                {k: v for k, v in params.items() if isinstance(v, (str, int, float))},
                                                str(d.get("target", ""))))
            self._items = self._items[-MAX_ENTRIES:]
        except (OSError, ValueError) as exc:
            log.info("Aktivitätsverlauf nicht lesbar (%s) – wird neu angelegt.", exc)
            self._items = []

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            from corecontrol.core.settings import write_json_atomic

            write_json_atomic(self.path, [asdict(a) for a in self._items])
        except Exception as exc:
            log.info("Aktivitätsverlauf konnte nicht gespeichert werden: %s", exc)

    def add(self, level: str, key: str, target: str = "", **params) -> Activity:
        safe = {k: (v if isinstance(v, (str, int, float)) else str(v)) for k, v in params.items()}
        a = Activity(time.time(), level, key, safe, target)
        with self._lock:
            self._items.append(a)
            self._items = self._items[-MAX_ENTRIES:]
            self._save()
        for cb in list(self._listeners):
            try:
                cb(a)
            except Exception:
                log.exception("Fehler im Aktivitäts-Listener")
        return a

    def recent(self, n: int = 5) -> list[Activity]:
        with self._lock:
            return list(reversed(self._items[-n:]))

    def all(self) -> list[Activity]:
        with self._lock:
            return list(reversed(self._items))

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._save()

    def on_add(self, cb: Callable[[Activity], None]) -> None:
        self._listeners.append(cb)

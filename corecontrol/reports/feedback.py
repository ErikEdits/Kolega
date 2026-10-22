"""Technischer Fehlerbericht für die Fehlersuche.

Wird nur auf ausdrücklichen Wunsch als Datei gespeichert und nie automatisch
hochgeladen. Persönliche Angaben werden vorher entfernt (siehe redact.py).
Enthält keine Passwörter, keine Zugangsdaten und keine persönlichen Dateien.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from typing import Callable

from corecontrol import APP_NAME, __version__
from corecontrol.core import fmt
from corecontrol.core.logging_setup import read_log_tail, recent_errors


def build_feedback(description: str, settings: dict, redact: Callable[[str], str], log_lines: int = 300) -> str:
    try:
        from PySide6 import __version__ as qt_version
    except Exception:
        qt_version = "?"
    safe_settings = {k: v for k, v in settings.items() if k not in ("ui.window_geometry", "gaming.games", "gaming.mini_pos")}
    lines = [
        f"{APP_NAME} – technischer Fehlerbericht / technical error report",
        "=" * 60,
        f"App-Version     : {__version__}",
        f"Erstellt        : {fmt.datetime_(time.time(), with_seconds=True)}",
        f"Windows/OS      : {platform.platform()}",
        f"Python          : {sys.version.split()[0]} ({platform.architecture()[0]})",
        f"PySide6         : {qt_version}",
        f"EXE             : {'ja' if getattr(sys, 'frozen', False) else 'nein'}",
        "",
        "Beschreibung des Benutzers / user description:",
        description.strip() or "(keine / none)",
        "",
        "Fehler in dieser Sitzung / errors in this session:",
    ]
    errs = recent_errors()
    if not errs:
        lines.append("(keine / none)")
    for e in errs[-30:]:
        lines.append(f"- {e.time:%Y-%m-%d %H:%M:%S} [{e.context}] {e.message}")
        if e.details:
            lines.extend("    " + x for x in e.details.rstrip().splitlines()[-25:])
    lines += ["", "Einstellungen / settings:", json.dumps(safe_settings, indent=2, ensure_ascii=False, default=str), "",
              f"Protokoll (letzte {log_lines} Zeilen) / log tail:", read_log_tail(log_lines)]
    return redact("\n".join(lines))

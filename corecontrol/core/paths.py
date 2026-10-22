"""Speicherorte von Einstellungen, Verlauf und Protokollen.

Windows:
  Einstellungen: %APPDATA%\\CoreControl\\settings.json
  Daten/Logs:    %LOCALAPPDATA%\\CoreControl\\
Mit der Umgebungsvariable CORECONTROL_HOME lässt sich alles in einen Ordner umleiten
(z. B. für Tests oder eine USB-Stick-Nutzung).
"""

from __future__ import annotations

import os
from pathlib import Path

from corecontrol.core.platform import IS_WINDOWS


def _base_dirs() -> tuple[Path, Path]:
    override = os.environ.get("CORECONTROL_HOME")
    if override:
        p = Path(override)
        return p, p
    if IS_WINDOWS:
        roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return roaming / "CoreControl", local / "CoreControl"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return config / "corecontrol", data / "corecontrol"


def config_dir() -> Path:
    d = _base_dirs()[0]
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_dir() -> Path:
    d = _base_dirs()[1]
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_file() -> Path:
    return config_dir() / "settings.json"


def history_db() -> Path:
    return data_dir() / "history.db"


def log_file() -> Path:
    return log_dir() / "corecontrol.log"

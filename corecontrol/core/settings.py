"""Einstellungen mit Prüfung aller Werte.

Jeder Eintrag hat einen Standardwert und Regeln (Typ, erlaubte Werte, Grenzen).
Fehlerhafte, unvollständige oder unbekannte Werte führen nie zum Absturz:
ungültige Werte werden auf den Standard zurückgesetzt bzw. auf die Grenzen begrenzt,
und es entsteht eine verständliche Warnung.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SETTINGS_VERSION = 2

TILE_IDS = ("cpu", "gpu", "ram", "storage", "load", "temps", "fans", "actions", "events", "network", "diagnosis", "system")
DEFAULT_TILES = ["cpu", "gpu", "ram", "storage", "load", "temps", "fans", "actions", "events", "network"]

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _valid_tiles(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for v in value:
        if isinstance(v, str) and v in TILE_IDS and v not in out:
            out.append(v)
    return out


def _valid_accent(value: Any) -> str | None:
    if value == "windows":
        return value
    if isinstance(value, str) and _HEX.match(value):
        return value.lower()
    return None


def _valid_str_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out = [v.strip() for v in value if isinstance(v, str) and v.strip() and len(v) < 256]
    return out[:20]


def _valid_games(value: Any) -> list[dict] | None:
    if not isinstance(value, list):
        return None
    games = []
    for g in value:
        if not isinstance(g, dict):
            continue
        name, target = g.get("name"), g.get("target")
        if not isinstance(name, str) or not isinstance(target, str) or not name.strip() or not target.strip():
            continue
        source = g.get("source") if g.get("source") in ("manual", "steam", "epic") else "manual"
        games.append({"name": name.strip()[:200], "target": target.strip()[:1000], "source": source})
    return games[:500]


def _valid_pos(value: Any) -> list[int] | None:
    if value is None:
        return None
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        return value
    return None


@dataclass(frozen=True)
class Field:
    default: Any
    kind: type | tuple
    choices: tuple | None = None
    min: float | None = None
    max: float | None = None
    validator: Callable[[Any], Any] | None = None
    allow_none: bool = False


SCHEMA: dict[str, Field] = {
    # Darstellung
    "ui.theme": Field("system", str, choices=("system", "light", "dark")),
    "ui.accent": Field("#2f7bff", str, validator=_valid_accent),
    "ui.language": Field("system", str, choices=("system", "de", "en")),
    "ui.window_geometry": Field("", str),
    "ui.animations": Field("system", str, choices=("system", "full", "reduced", "off")),
    # Dashboard
    "dashboard.tiles": Field(list(DEFAULT_TILES), list, validator=_valid_tiles),
    # Messung
    "monitor.interval_ms": Field(500, int, min=250, max=10000),
    "monitor.background_interval_ms": Field(5000, int, min=1000, max=60000),
    "sensors.amd_enabled": Field(True, bool),
    "sensors.lhm_enabled": Field(True, bool),
    "sensors.lhm_port": Field(8085, int, min=1, max=65535),
    # Warnschwellen
    "thresholds.cpu_temp_warn": Field(85, int, min=40, max=110),
    "thresholds.cpu_temp_crit": Field(95, int, min=40, max=115),
    "thresholds.gpu_temp_warn": Field(83, int, min=40, max=110),
    "thresholds.gpu_temp_crit": Field(90, int, min=40, max=115),
    "thresholds.cpu_load_warn": Field(90, int, min=50, max=100),
    "thresholds.ram_warn": Field(90, int, min=50, max=100),
    "thresholds.disk_free_warn_pct": Field(10, int, min=1, max=50),
    "thresholds.disk_free_crit_pct": Field(5, int, min=1, max=50),
    "thresholds.disk_free_warn_gb": Field(15, int, min=1, max=1000),
    "thresholds.disk_free_crit_gb": Field(5, int, min=1, max=1000),
    # Benachrichtigungen
    "notify.enabled": Field(True, bool),
    "notify.cooldown_min": Field(15, int, min=1, max=1440),
    # Verlauf
    "history.enabled": Field(True, bool),
    "history.retention_days": Field(30, int, min=1, max=730),
    # Start und Hintergrund
    "startup.with_windows": Field(False, bool),
    "startup.minimized": Field(False, bool),
    "tray.enabled": Field(True, bool),
    "tray.minimize_to_tray": Field(False, bool),
    "tray.close_to_tray": Field(False, bool),
    # Automatische Aktionen (nur ungefährliche Analysen)
    "auto.diagnosis_on_start": Field(True, bool),
    "auto.diagnosis_interval_h": Field(0, int, min=0, max=168),
    "updates.check_on_start": Field(False, bool),
    # Diagnose / Netzwerk / Ereignisse
    "events.days": Field(30, int, min=1, max=90),
    "network.ping_targets": Field(["1.1.1.1", "8.8.8.8"], list, validator=_valid_str_list),
    "network.dns_domains": Field(["www.microsoft.com", "www.wikipedia.org", "www.google.com"], list, validator=_valid_str_list),
    "network.include_in_diagnosis": Field(True, bool),
    # Speicher
    "storage.cleanup_min_age_days": Field(2, int, min=0, max=365),
    # Bericht
    "report.redact": Field(True, bool),
    # Gaming
    "gaming.games": Field([], list, validator=_valid_games),
    "gaming.mini_opacity": Field(0.9, float, min=0.3, max=1.0),
    "gaming.mini_pos": Field(None, list, validator=_valid_pos, allow_none=True),
    "gaming.mini_on_top": Field(True, bool),
}


@dataclass
class LoadResult:
    values: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def defaults() -> dict[str, Any]:
    return {k: _copy(f.default) for k, f in SCHEMA.items()}


def _copy(v: Any) -> Any:
    return json.loads(json.dumps(v))


def validate_value(key: str, value: Any) -> tuple[Any, str | None]:
    """Gibt (gültiger Wert, Warnung oder None) zurück."""
    f = SCHEMA.get(key)
    if f is None:
        return None, f"unknown:{key}"
    if value is None and f.allow_none:
        return None, None
    if f.validator is not None:
        res = f.validator(value)
        if res is None:
            return _copy(f.default), f"invalid:{key}"
        return res, None
    if f.kind is bool:
        if isinstance(value, bool):
            return value, None
        return f.default, f"invalid:{key}"
    if f.kind in (int, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f.default, f"invalid:{key}"
        if value != value:  # NaN
            return f.default, f"invalid:{key}"
        v = int(round(value)) if f.kind is int else float(value)
        warn = None
        if f.min is not None and v < f.min:
            v, warn = type(v)(f.min), f"clamped:{key}"
        if f.max is not None and v > f.max:
            v, warn = type(v)(f.max), f"clamped:{key}"
        return v, warn
    if f.kind is str:
        if not isinstance(value, str):
            return f.default, f"invalid:{key}"
        if f.choices and value not in f.choices:
            return f.default, f"invalid:{key}"
        return value[:20000], None
    if f.kind is list:
        if not isinstance(value, list):
            return _copy(f.default), f"invalid:{key}"
        return _copy(value), None
    return f.default, f"invalid:{key}"


def _migrate(data: dict[str, Any], version: Any) -> dict[str, Any]:
    """Passt Dateien älterer Versionen an. Nur unveränderte alte Standardwerte werden ersetzt."""
    if not isinstance(version, int) or version < 2:
        # Version 2: Live-Messung standardmäßig alle 0,5 s statt 1 s
        if data.get("monitor.interval_ms") == 1000:
            data = dict(data, **{"monitor.interval_ms": SCHEMA["monitor.interval_ms"].default})
    return data


def validate_dict(raw: Any) -> LoadResult:
    result = LoadResult(defaults())
    if not isinstance(raw, dict):
        result.warnings.append("invalid:file")
        return result
    data = raw.get("values", raw) if isinstance(raw.get("values"), dict) else raw
    data = _migrate(data, raw.get("version"))
    for key, value in data.items():
        if key in ("version", "values"):
            continue
        if key not in SCHEMA:
            result.warnings.append(f"unknown:{key}")
            continue
        v, warn = validate_value(key, value)
        result.values[key] = v
        if warn:
            result.warnings.append(warn)
    # Zusammenhänge prüfen: kritische Schwelle muss über der Warnschwelle liegen
    for warn_key, crit_key, higher_is_worse in (
        ("thresholds.cpu_temp_warn", "thresholds.cpu_temp_crit", True),
        ("thresholds.gpu_temp_warn", "thresholds.gpu_temp_crit", True),
        ("thresholds.disk_free_warn_pct", "thresholds.disk_free_crit_pct", False),
        ("thresholds.disk_free_warn_gb", "thresholds.disk_free_crit_gb", False),
    ):
        w, c = result.values[warn_key], result.values[crit_key]
        if (higher_is_worse and c < w) or (not higher_is_worse and c > w):
            result.values[crit_key] = w
            result.warnings.append(f"adjusted:{crit_key}")
    return result


class Settings:
    """Thread-sichere Einstellungen mit Änderungsbenachrichtigung."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self._values = defaults()
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str, Any], None]] = []
        self.load_warnings: list[str] = []

    # --- Laden / Speichern -------------------------------------------------
    def load(self) -> list[str]:
        if self.path is None or not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Einstellungen unlesbar (%s) – Standardwerte werden verwendet.", exc)
            self._backup_broken()
            self.load_warnings = ["invalid:file"]
            return self.load_warnings
        res = validate_dict(raw)
        with self._lock:
            self._values = res.values
        self.load_warnings = res.warnings
        if res.warnings:
            log.info("Einstellungen korrigiert: %s", ", ".join(res.warnings))
        return res.warnings

    def _backup_broken(self) -> None:
        try:
            assert self.path is not None
            backup = self.path.with_suffix(".broken.json")
            os.replace(self.path, backup)
        except OSError:
            pass

    def save(self) -> bool:
        if self.path is None:
            return False
        with self._lock:
            data = {"version": SETTINGS_VERSION, "values": _copy(self._values)}
        return write_json_atomic(self.path, data)

    # --- Zugriff -------------------------------------------------------------
    def get(self, key: str) -> Any:
        with self._lock:
            return _copy(self._values[key]) if isinstance(self._values[key], (list, dict)) else self._values[key]

    def set(self, key: str, value: Any, save: bool = True) -> str | None:
        v, warn = validate_value(key, value)
        if warn and warn.startswith("unknown"):
            raise KeyError(key)
        with self._lock:
            changed = self._values.get(key) != v
            self._values[key] = v
        if changed:
            if save:
                self.save()
            for cb in list(self._listeners):
                try:
                    cb(key, v)
                except Exception:
                    log.exception("Fehler in Einstellungs-Listener")
        return warn

    def all(self) -> dict[str, Any]:
        with self._lock:
            return _copy(self._values)

    def on_change(self, cb: Callable[[str, Any], None]) -> None:
        self._listeners.append(cb)

    def reset(self) -> None:
        for k, v in defaults().items():
            self.set(k, v, save=False)
        self.save()

    # --- Export / Import ---------------------------------------------------
    def export_to(self, path: Path) -> bool:
        with self._lock:
            data = {"app": "CoreControl", "version": SETTINGS_VERSION, "values": _copy(self._values)}
        data["values"].pop("ui.window_geometry", None)
        return write_json_atomic(path, data)

    def import_from(self, path: Path) -> list[str]:
        """Liest eine exportierte Datei. Ungültige Einträge werden ignoriert."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("invalid file")
        res = validate_dict(raw)
        provided = raw.get("values", raw) if isinstance(raw.get("values"), dict) else raw
        for key in provided:
            if key in SCHEMA and key != "ui.window_geometry":
                self.set(key, res.values[key], save=False)
        self.save()
        return res.warnings


def write_json_atomic(path: Path, data: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.warning("Speichern nach %s fehlgeschlagen: %s", path, exc)
        return False

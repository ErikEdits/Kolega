"""Übersetzungen (Deutsch / Englisch).

tr("schluessel", name=wert) liefert den Text in der aktuellen Sprache.
T("schluessel", ...) ist ein „verzögerter“ Text: Er wird erst beim Anzeigen
übersetzt. So können Diagnoseergebnisse nach einem Sprachwechsel sofort
in der neuen Sprache erscheinen.
"""

from __future__ import annotations

import locale
import logging
import sys
from typing import Any

from corecontrol.i18n import de, en

log = logging.getLogger(__name__)

LANGUAGES = {"de": de.STRINGS, "en": en.STRINGS}
_current = "de"
_missing_logged: set[str] = set()


def resolve_language(setting: str) -> str:
    if setting in LANGUAGES:
        return setting
    return detect_system_language()


def detect_system_language() -> str:
    try:
        if sys.platform == "win32":
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "de" if (lang_id & 0x3FF) == 0x07 else "en"
        loc = locale.getlocale()[0] or ""
        return "de" if loc.lower().startswith("de") else "en"
    except Exception:
        return "en"


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in LANGUAGES else "en"


def current_language() -> str:
    return _current


def _raw(key: str) -> Any:
    val = LANGUAGES[_current].get(key)
    if val is None:
        val = LANGUAGES["en"].get(key)
        if key not in _missing_logged:
            _missing_logged.add(key)
            log.warning("Übersetzung fehlt: %s (%s)", key, _current)
    return val


def _fmt(text: str, params: dict) -> str:
    if not params:
        return text
    try:
        return text.format(**{k: (str(v) if isinstance(v, T) else v) for k, v in params.items()})
    except (KeyError, IndexError, ValueError) as exc:
        log.warning("Formatfehler in Übersetzung: %s (%s)", text[:60], exc)
        return text


def tr(key: str, **params: Any) -> str:
    val = _raw(key)
    if val is None:
        return key
    if isinstance(val, (list, tuple)):
        val = "\n".join(val)
    return _fmt(val, params)


def tr_list(key: str, **params: Any) -> list[str]:
    val = _raw(key)
    if val is None:
        return []
    if isinstance(val, str):
        val = [val]
    return [_fmt(v, params) for v in val]


def has(key: str) -> bool:
    return key in LANGUAGES[_current] or key in LANGUAGES["en"]


class T:
    """Verzögert übersetzter Text."""

    __slots__ = ("key", "params")

    def __init__(self, key: str, **params: Any):
        self.key = key
        self.params = params

    def __str__(self) -> str:
        return tr(self.key, **self.params)

    def __format__(self, spec: str) -> str:
        return str(self)

    def lines(self) -> list[str]:
        return tr_list(self.key, **self.params)

    def __repr__(self) -> str:
        return f"T({self.key!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, T) and self.key == other.key and self.params == other.params

    def __hash__(self) -> int:
        return hash(self.key)


def text(value: Any) -> str:
    """Wandelt T, Strings oder None in anzeigbaren Text um."""
    if value is None:
        return tr("common.na")
    return str(value)

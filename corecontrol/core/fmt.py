"""Sprachabhängige Formatierung von Zahlen, Größen, Temperaturen und Zeiten.

Die Klassen (Bytes, Pct, Temp …) werden in Diagnosetexten als Platzhalter verwendet.
Sie werden erst beim Anzeigen formatiert, damit ein Sprachwechsel auch Zahlen
(Komma vs. Punkt) korrekt umstellt.
"""

from __future__ import annotations

from datetime import datetime

NA = None  # Marker für „nicht verfügbar“


def _lang() -> str:
    from corecontrol import i18n

    return i18n.current_language()


def number(value: float, digits: int = 0, lang: str | None = None) -> str:
    lang = lang or _lang()
    s = f"{value:,.{digits}f}"
    if lang == "de":
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return s


def bytes_(value: float | None, lang: str | None = None, digits: int | None = None) -> str:
    if value is None:
        return _na(lang)
    v = float(value)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while abs(v) >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    d = digits if digits is not None else (0 if i == 0 or abs(v) >= 100 else 1)
    return f"{number(v, d, lang)} {units[i]}"


def rate_bytes(value: float | None, lang: str | None = None) -> str:
    if value is None:
        return _na(lang)
    return f"{bytes_(value, lang)}/s"


def rate_bits(bytes_per_sec: float | None, lang: str | None = None) -> str:
    """Netzwerkraten in Bit/s – so wie im Task-Manager."""
    if bytes_per_sec is None:
        return _na(lang)
    v = float(bytes_per_sec) * 8
    units = ["bit/s", "Kbit/s", "Mbit/s", "Gbit/s"]
    i = 0
    while v >= 1000 and i < len(units) - 1:
        v /= 1000
        i += 1
    d = 0 if i == 0 or v >= 100 else 1
    return f"{number(v, d, lang)} {units[i]}"


def pct(value: float | None, digits: int = 0, lang: str | None = None) -> str:
    if value is None:
        return _na(lang)
    lang = lang or _lang()
    sep = " " if lang == "de" else ""
    return f"{number(value, digits, lang)}{sep}%"


def temp(value: float | None, lang: str | None = None) -> str:
    if value is None:
        return _na(lang)
    return f"{number(value, 0, lang)} °C"


def mhz(value: float | None, lang: str | None = None) -> str:
    if value is None:
        return _na(lang)
    if value >= 1000:
        return f"{number(value / 1000, 2, lang)} GHz"
    return f"{number(value, 0, lang)} MHz"


def ms(value: float | None, lang: str | None = None) -> str:
    if value is None:
        return _na(lang)
    return f"{number(value, 0 if value >= 10 else 1, lang)} ms"


def duration(seconds: float | None, lang: str | None = None) -> str:
    if seconds is None:
        return _na(lang)
    lang = lang or _lang()
    s = int(seconds)
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    minutes = s // 60
    if lang == "de":
        d, h, m = "T", "Std.", "Min."
    else:
        d, h, m = "d", "h", "min"
    if days:
        return f"{days} {d} {hours} {h}"
    if hours:
        return f"{hours} {h} {minutes} {m}"
    return f"{minutes} {m}"


def datetime_(value: datetime | float | None, lang: str | None = None, with_seconds: bool = False) -> str:
    if value is None:
        return _na(lang)
    lang = lang or _lang()
    if not isinstance(value, datetime):
        value = datetime.fromtimestamp(float(value))
    sec = ":%S" if with_seconds else ""
    if lang == "de":
        return value.strftime(f"%d.%m.%Y %H:%M{sec}")
    return value.strftime(f"%Y-%m-%d %H:%M{sec}")


def date_(value: datetime | None, lang: str | None = None) -> str:
    if value is None:
        return _na(lang)
    lang = lang or _lang()
    return value.strftime("%d.%m.%Y" if lang == "de" else "%Y-%m-%d")


def _na(lang: str | None = None) -> str:
    from corecontrol import i18n

    return i18n.tr("common.na")


def or_na(value, formatter=str) -> str:
    return _na() if value is None or value == "" else formatter(value)


# ---- Lazy formatierte Werte für Übersetzungs-Platzhalter ---------------------
class _Q:
    __slots__ = ("v", "d")

    def __init__(self, v, d=None):
        self.v, self.d = v, d

    def __format__(self, spec):
        return str(self)

    def __repr__(self):
        return f"{type(self).__name__}({self.v!r})"

    def __eq__(self, other):
        return type(self) is type(other) and self.v == other.v


class Bytes(_Q):
    def __str__(self):
        return bytes_(self.v)


class Pct(_Q):
    def __str__(self):
        return pct(self.v, self.d or 0)


class Temp(_Q):
    def __str__(self):
        return temp(self.v)


class Num(_Q):
    def __str__(self):
        return number(self.v, self.d or 0)


class Ms(_Q):
    def __str__(self):
        return ms(self.v)


class Dur(_Q):
    def __str__(self):
        return duration(self.v)


class When(_Q):
    def __str__(self):
        return datetime_(self.v)


class Date(_Q):
    def __str__(self):
        return date_(self.v)

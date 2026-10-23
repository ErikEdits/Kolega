"""WMI-Abfragen über pywin32 (COM). Nur unter Windows; sonst leere Ergebnisse.

Jeder Thread, der WMI nutzt, muss COM initialisieren – das übernimmt com_thread().
"""

from __future__ import annotations

import contextlib
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from corecontrol.core.platform import IS_WINDOWS

log = logging.getLogger(__name__)

_tls = threading.local()


@contextlib.contextmanager
def com_thread() -> Iterator[None]:
    if not IS_WINDOWS:
        yield
        return
    import pythoncom

    depth = getattr(_tls, "depth", 0)
    if depth == 0:
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    _tls.depth = depth + 1
    try:
        yield
    finally:
        _tls.depth -= 1
        if _tls.depth == 0:
            pythoncom.CoUninitialize()


def ensure_com() -> None:
    """Initialisiert COM für einen langlebigen Thread (ohne Aufräumen)."""
    if IS_WINDOWS and not getattr(_tls, "inited", False):
        import pythoncom

        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        except Exception:
            pass
        _tls.inited = True


def connect(namespace: str = "root\\cimv2"):
    if not IS_WINDOWS:
        raise OSError("WMI ist nur unter Windows verfügbar")
    import win32com.client

    ensure_com()
    locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    return locator.ConnectServer(".", namespace)


def _convert(v: Any) -> Any:
    if isinstance(v, tuple):
        return [_convert(x) for x in v]
    return v


def query_conn(conn, wql: str, props: list[str]) -> list[dict]:
    rows = []
    for obj in conn.ExecQuery(wql):
        row = {}
        for p in props:
            try:
                row[p] = _convert(getattr(obj, p))
            except Exception:
                row[p] = None
        rows.append(row)
    return rows


def query(wql: str, props: list[str], namespace: str = "root\\cimv2") -> list[dict]:
    """Führt eine WQL-Abfrage aus. Fehler werden protokolliert und als leere Liste gemeldet."""
    if not IS_WINDOWS:
        return []
    with com_thread():
        conn = connect(namespace)
        return query_conn(conn, wql, props)


def parse_datetime(value: Any) -> datetime | None:
    """WMI-Datum '20240115123000.000000+060' → datetime (lokale Zeit)."""
    if not value or not isinstance(value, str) or len(value) < 14:
        return None
    try:
        dt = datetime.strptime(value[:14], "%Y%m%d%H%M%S")
        if len(value) >= 22 and value[21] in "+-":
            offset = int(value[22:25]) * (1 if value[21] == "+" else -1)
            dt = dt.replace(tzinfo=timezone(timedelta(minutes=offset))).astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None

"""Verlaufsspeicherung in SQLite mit begrenzter Datenmenge.

Gespeichert werden nur zusammengefasste Messwerte (keine Prozesse, keine Dateien):
- pro Minute: Durchschnitt und Maximum von CPU, RAM, GPU, Temperaturen, Datenträger, Netzwerk
- Minutenwerte älter als 7 Tage werden zu Stundenwerten zusammengefasst
- Daten älter als die eingestellte Aufbewahrungsdauer werden automatisch gelöscht

Größenordnung: ca. 0,1 MB pro Tag in den ersten 7 Tagen, danach ca. 4 KB pro Tag.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from corecontrol.monitoring.models import Sample

log = logging.getLogger(__name__)

METRICS = ("cpu", "ram", "gpu", "cpu_temp", "gpu_temp", "disk_read", "disk_write", "net_down", "net_up")
MINUTE_KEEP_DAYS = 7


def sample_values(s: Sample) -> dict[str, float | None]:
    g = s.primary_gpu
    return {
        "cpu": s.cpu_percent,
        "ram": s.ram_percent,
        "gpu": g.util if g else None,
        "cpu_temp": s.cpu_temp,
        "gpu_temp": g.temp if g else None,
        "disk_read": s.disk_read_bps,
        "disk_write": s.disk_write_bps,
        "net_down": s.net_down_bps,
        "net_up": s.net_up_bps,
    }


class HistoryStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        cols = ", ".join(f"{m}_avg REAL, {m}_max REAL" for m in METRICS)
        for table in ("minute", "hour"):
            self._conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (ts INTEGER PRIMARY KEY, {cols})")
        self._conn.commit()

    def insert(self, table: str, ts: int, values: dict[str, tuple[float | None, float | None]]) -> None:
        assert table in ("minute", "hour")
        cols = ["ts"]
        params: list = [int(ts)]
        for m in METRICS:
            avg, mx = values.get(m, (None, None))
            cols += [f"{m}_avg", f"{m}_max"]
            params += [avg, mx]
        sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def query(self, metric: str, since: float, until: float | None = None) -> tuple[list[float], list, list]:
        """Liefert (Zeitpunkte, Durchschnitt, Maximum). Für lange Zeiträume werden Stundenwerte genutzt."""
        if metric not in METRICS:
            raise ValueError(metric)
        until = until or time.time()
        rows: list = []
        with self._lock:
            if until - since > 2 * 86400:
                rows += self._conn.execute(
                    f"SELECT ts, {metric}_avg, {metric}_max FROM hour WHERE ts >= ? AND ts <= ? ORDER BY ts",
                    (since, until)).fetchall()
                start_min = max(since, rows[-1][0] + 3600) if rows else since
                minute_rows = self._conn.execute(
                    f"SELECT ts, {metric}_avg, {metric}_max FROM minute WHERE ts >= ? AND ts <= ? ORDER BY ts",
                    (start_min, until)).fetchall()
                rows += _bucket(minute_rows, 3600)
            else:
                rows = self._conn.execute(
                    f"SELECT ts, {metric}_avg, {metric}_max FROM minute WHERE ts >= ? AND ts <= ? ORDER BY ts",
                    (since, until)).fetchall()
                if until - since > 6 * 3600:
                    rows = _bucket(rows, 600)
        return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]

    def purge(self, retention_days: int, now: float | None = None) -> None:
        """Fasst alte Minutenwerte zusammen und löscht Daten außerhalb der Aufbewahrungsdauer."""
        now = now or time.time()
        cutoff_minutes = now - MINUTE_KEEP_DAYS * 86400
        cutoff_all = now - retention_days * 86400
        with self._lock:
            old = self._conn.execute("SELECT * FROM minute WHERE ts < ? ORDER BY ts", (cutoff_minutes,)).fetchall()
            if old:
                buckets: dict[int, list] = {}
                for r in old:
                    buckets.setdefault(int(r[0]) // 3600 * 3600, []).append(r)
                for hour_ts, rows in buckets.items():
                    vals = []
                    for i, _m in enumerate(METRICS):
                        avgs = [r[1 + 2 * i] for r in rows if r[1 + 2 * i] is not None]
                        maxs = [r[2 + 2 * i] for r in rows if r[2 + 2 * i] is not None]
                        vals += [sum(avgs) / len(avgs) if avgs else None, max(maxs) if maxs else None]
                    self._conn.execute(
                        f"INSERT OR REPLACE INTO hour VALUES ({', '.join('?' * (1 + 2 * len(METRICS)))})",
                        [hour_ts, *vals])
                self._conn.execute("DELETE FROM minute WHERE ts < ?", (cutoff_minutes,))
            self._conn.execute("DELETE FROM minute WHERE ts < ?", (cutoff_all,))
            self._conn.execute("DELETE FROM hour WHERE ts < ?", (cutoff_all,))
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM minute")
            self._conn.execute("DELETE FROM hour")
            self._conn.commit()
            self._conn.execute("VACUUM")

    def stats(self) -> dict:
        with self._lock:
            n_min = self._conn.execute("SELECT COUNT(*), MIN(ts) FROM minute").fetchone()
            n_hour = self._conn.execute("SELECT COUNT(*), MIN(ts) FROM hour").fetchone()
        size = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(self.path + suffix)
            if p.exists():
                size += p.stat().st_size
        oldest = min([t for t in (n_min[1], n_hour[1]) if t is not None], default=None)
        return {"minute_rows": n_min[0], "hour_rows": n_hour[0], "size": size, "oldest": oldest}

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


def _bucket(rows: list, seconds: int) -> list:
    out = []
    cur = None
    group: list = []
    for r in rows:
        b = int(r[0]) // seconds * seconds
        if cur is not None and b != cur:
            out.append(_agg(cur, group))
            group = []
        cur = b
        group.append(r)
    if group:
        out.append(_agg(cur, group))
    return out


def _agg(ts: int, group: list) -> tuple:
    avgs = [r[1] for r in group if r[1] is not None]
    maxs = [r[2] for r in group if r[2] is not None]
    return ts, (sum(avgs) / len(avgs) if avgs else None), (max(maxs) if maxs else None)


class HistoryRecorder:
    """Sammelt Messwerte und schreibt einmal pro Minute einen zusammengefassten Datensatz."""

    def __init__(self, store: HistoryStore, enabled: Callable[[], bool]):
        self.store = store
        self.enabled = enabled
        self._minute: int | None = None
        self._acc: dict[str, list[float]] = {m: [] for m in METRICS}

    def add(self, s: Sample) -> None:
        minute = int(s.ts) // 60 * 60
        if self._minute is not None and minute != self._minute:
            self.flush()
        self._minute = minute
        for k, v in sample_values(s).items():
            if v is not None:
                self._acc[k].append(float(v))

    def flush(self) -> None:
        if self._minute is None or not any(self._acc.values()):
            return
        values = {k: ((sum(v) / len(v)), max(v)) if v else (None, None) for k, v in self._acc.items()}
        self._acc = {m: [] for m in METRICS}
        if not self.enabled():
            return
        try:
            self.store.insert("minute", self._minute, values)
        except Exception as exc:
            log.warning("Verlauf konnte nicht gespeichert werden: %s", exc)

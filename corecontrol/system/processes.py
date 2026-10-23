"""Prozesse anzeigen und – nur nach ausdrücklicher Bestätigung – beenden.

Kritische Windows-Prozesse sind geschützt und können über CoreControl nicht
beendet werden. Vor dem Beenden wird geprüft, ob es noch derselbe Prozess ist
(Prozess-IDs werden von Windows wiederverwendet). Das Ergebnis wird überprüft
und ehrlich gemeldet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psutil

# Prozesse, deren Beenden Windows abstürzen lässt oder Sicherheitsfunktionen abschaltet
PROTECTED = {
    "system", "system idle process", "idle", "registry", "memory compression", "secure system", "smss.exe",
    "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe",
    "fontdrvhost.exe", "dwm.exe", "sihost.exe", "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe",
    "wudfhost.exe", "conhost.exe", "spoolsv.exe", "audiodg.exe", "ctfmon.exe", "searchindexer.exe",
    "taskhostw.exe", "dllhost.exe", "runtimebroker.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
    "textinputhost.exe", "lsm.exe", "wlanext.exe", "dashost.exe",
    # Linux (Entwicklung)
    "init", "systemd", "kthreadd",
}
# Erlaubt, aber mit besonderem Hinweis
CAUTION = {"explorer.exe": "proc.caution.explorer"}


@dataclass
class ProcessRow:
    pid: int
    name: str
    cpu: float          # % der Gesamt-CPU (wie im Task-Manager)
    mem: int            # Bytes (Arbeitssatz)
    user: str
    exe: str
    status: str
    create_time: float
    protected: bool


def is_protected(name: str, pid: int) -> bool:
    if pid in (0, 4) or pid == os.getpid():
        return True
    return (name or "").lower() in PROTECTED


class ProcessMonitor:
    def __init__(self):
        self._procs: dict[int, psutil.Process] = {}
        self._ncpu = psutil.cpu_count() or 1

    def refresh(self) -> list[ProcessRow]:
        rows: list[ProcessRow] = []
        seen = set()
        for p in psutil.process_iter(["pid", "name", "username", "exe", "memory_info", "status", "create_time"], ad_value=None):
            info = p.info
            pid = info["pid"]
            seen.add(pid)
            cached = self._procs.get(pid)
            if cached is None or cached.create_time() != info.get("create_time"):
                self._procs[pid] = p
                cached = p
                try:
                    cached.cpu_percent(None)  # erste Messung initialisieren
                except (psutil.Error, OSError):
                    pass
                cpu = 0.0
            else:
                try:
                    cpu = cached.cpu_percent(None) / self._ncpu
                except (psutil.Error, OSError):
                    cpu = 0.0
            name = info.get("name") or str(pid)
            mem = info.get("memory_info")
            user = info.get("username") or ""
            if "\\" in user:
                user = user.split("\\", 1)[1]
            rows.append(ProcessRow(pid, name, cpu, int(mem.rss) if mem else 0, user, info.get("exe") or "",
                                   info.get("status") or "", info.get("create_time") or 0.0, is_protected(name, pid)))
        for pid in list(self._procs):
            if pid not in seen:
                del self._procs[pid]
        return rows


def end_process(pid: int, name: str, create_time: float, confirmed: bool = False, timeout: float = 4.0) -> str:
    """Beendet einen Prozess. Ergebnis: not_confirmed, protected, not_found, changed, access_denied,
    terminated, killed, still_running."""
    if not confirmed:
        return "not_confirmed"
    if is_protected(name, pid):
        return "protected"
    try:
        p = psutil.Process(pid)
        if abs(p.create_time() - create_time) > 0.5 or (p.name() or "").lower() != (name or "").lower():
            return "changed"  # PID inzwischen von einem anderen Prozess belegt
        p.terminate()
        try:
            p.wait(timeout)
            return "terminated"
        except psutil.TimeoutExpired:
            p.kill()
            p.wait(2)
            return "killed"
    except psutil.NoSuchProcess:
        return "not_found"
    except psutil.AccessDenied:
        return "access_denied"
    except psutil.TimeoutExpired:
        return "still_running"
    except OSError:
        return "access_denied"

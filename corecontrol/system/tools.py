"""Verknüpfungen zu nützlichen Windows-Werkzeugen und Ausführung von Aktions-Kennungen.

Aktions-Kennungen (in Diagnose-Befunden):
  nav:<seite>   → Seite in CoreControl öffnen
  tool:<id>     → Windows-Werkzeug starten
  url:<adresse> → Adresse bzw. ms-settings:-Seite öffnen
"""

from __future__ import annotations

from dataclasses import dataclass

from corecontrol.core.platform import IS_WINDOWS, launch, open_url


@dataclass(frozen=True)
class Tool:
    id: str
    command: tuple[str, ...]
    icon: str
    needs_admin: bool = False
    url: str | None = None  # Alternativ: über URL/Protokoll öffnen


TOOLS: list[Tool] = [
    Tool("taskmgr", ("taskmgr.exe",), "activity"),
    Tool("devmgmt", ("mmc.exe", "devmgmt.msc"), "cpu"),
    Tool("eventvwr", ("mmc.exe", "eventvwr.msc"), "scroll-text"),
    Tool("reliability", ("perfmon.exe", "/rel"), "chart-line"),
    Tool("resmon", ("resmon.exe",), "gauge"),
    Tool("msinfo32", ("msinfo32.exe",), "info"),
    Tool("diskmgmt", ("mmc.exe", "diskmgmt.msc"), "hard-drive", needs_admin=True),
    Tool("services", ("mmc.exe", "services.msc"), "server"),
    Tool("cleanmgr", ("cleanmgr.exe",), "trash-2"),
    Tool("storagesense", (), "database", url="ms-settings:storagesense"),
    Tool("windowsupdate", (), "refresh-cw", url="ms-settings:windowsupdate"),
    Tool("security", (), "shield-check", url="windowsdefender:"),
    Tool("apps", (), "package", url="ms-settings:appsfeatures"),
    Tool("powercfg", ("control.exe", "powercfg.cpl"), "power"),
    Tool("ncpa", ("control.exe", "ncpa.cpl"), "network"),
    Tool("dxdiag", ("dxdiag.exe",), "monitor"),
    Tool("mdsched", ("mdsched.exe",), "memory-stick", needs_admin=True),
    Tool("control", ("control.exe",), "settings"),
]

TOOLS_BY_ID = {t.id: t for t in TOOLS}


def run_tool(tool_id: str) -> bool:
    t = TOOLS_BY_ID.get(tool_id)
    if t is None or not IS_WINDOWS:
        return False
    if t.url:
        return open_url(t.url)
    if t.needs_admin:
        # Werkzeuge, die Adminrechte brauchen, über ShellExecute starten – Windows fragt dann per UAC nach.
        import ctypes

        exe, *args = t.command
        rc = ctypes.windll.shell32.ShellExecuteW(None, "open", exe, " ".join(args) or None, None, 1)
        return rc > 32
    return launch(list(t.command))


def run_action(action: str) -> bool:
    """Führt eine Aktions-Kennung aus. Navigationsaktionen werden von der Oberfläche behandelt."""
    kind, _, target = action.partition(":")
    if kind == "tool":
        return run_tool(target)
    if kind == "url":
        return open_url(target)
    if kind == "nav":
        from corecontrol.ui.bus import bus

        bus.navigate.emit(target)
        return True
    return False

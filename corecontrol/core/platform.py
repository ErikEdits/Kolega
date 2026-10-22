"""Plattform-Hilfen: Windows-Erkennung, Adminrechte, Öffnen von Dateien und Tools."""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import webbrowser

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_FROZEN = bool(getattr(sys, "frozen", False))

# Verhindert aufblitzende Konsolenfenster bei Hilfsprogrammen.
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def relaunch_as_admin() -> bool:
    """Startet CoreControl mit Adminrechten neu (UAC-Abfrage). Gibt True zurück, wenn
    Windows den Start angenommen hat. Der Benutzer kann die Abfrage ablehnen."""
    if not IS_WINDOWS:
        return False
    import ctypes

    if IS_FROZEN:
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe = sys.executable
        params = "-m corecontrol " + " ".join(f'"{a}"' for a in sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def open_path(path: str) -> bool:
    """Öffnet Datei oder Ordner mit dem Standardprogramm."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: S606 - bewusst: Öffnen durch den Benutzer
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception as exc:
        log.warning("Konnte %s nicht öffnen: %s", path, exc)
        return False


def show_in_explorer(path: str) -> bool:
    """Zeigt eine Datei im Explorer an (markiert)."""
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or path])
        return True
    except Exception as exc:
        log.warning("Explorer-Start fehlgeschlagen: %s", exc)
        return False


def open_url(url: str) -> bool:
    """Öffnet eine URL oder ein Windows-Protokoll (z. B. ms-settings:)."""
    try:
        if IS_WINDOWS:
            os.startfile(url)  # noqa: S606
            return True
        return webbrowser.open(url)
    except Exception as exc:
        log.warning("Konnte %s nicht öffnen: %s", url, exc)
        return False


def launch(command: list[str]) -> bool:
    """Startet ein Windows-Werkzeug, ohne auf dessen Ende zu warten."""
    try:
        subprocess.Popen(command, close_fds=True)
        return True
    except Exception as exc:
        log.warning("Start von %s fehlgeschlagen: %s", command, exc)
        return False


def run_hidden(command: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess | None:
    """Führt ein Kommandozeilenwerkzeug ohne Fenster aus und gibt die Ausgabe zurück."""
    try:
        return subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )
    except Exception as exc:
        log.info("Befehl %s fehlgeschlagen: %s", command[0], exc)
        return None


def decode_console(data: bytes) -> str:
    """Dekodiert Ausgaben von Windows-Konsolenprogrammen (OEM-Codepage)."""
    if not data:
        return ""
    for enc in ("utf-8", "cp850", "cp1252", "latin-1"):
        with contextlib.suppress(UnicodeDecodeError):
            return data.decode(enc)
    return data.decode("utf-8", errors="replace")


def resource_path(*parts: str) -> str:
    """Pfad zu mitgelieferten Dateien – funktioniert im Quellcode und in der EXE."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, "_MEIPASS", None):
        base = os.path.join(base, "corecontrol")
    return os.path.join(base, *parts)

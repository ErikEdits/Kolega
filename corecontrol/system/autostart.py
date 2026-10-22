"""Autostart-Programme anzeigen und umkehrbar aktivieren/deaktivieren.

Quellen (wie im Task-Manager):
- Registry: HKCU/HKLM ...\\CurrentVersion\\Run (auch 32-Bit-Zweig)
- Autostart-Ordner des Benutzers und aller Benutzer

Deaktivieren erfolgt genau wie im Task-Manager über die Schlüssel
„StartupApproved“ – der Eintrag selbst bleibt erhalten und kann jederzeit
wieder aktiviert werden. Es wird nichts gelöscht.
Einträge für alle Benutzer (HKLM, gemeinsamer Ordner) erfordern Adminrechte.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
import time
from dataclasses import dataclass

from corecontrol.core.platform import IS_WINDOWS

log = logging.getLogger(__name__)

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
SELF_NAME = "CoreControl"


@dataclass
class StartupItem:
    name: str
    command: str
    location: str      # hkcu_run, hklm_run, hklm_run32, user_folder, common_folder
    enabled: bool
    needs_admin: bool
    approved_key: str  # Unterschlüssel unter StartupApproved
    hive: str          # HKCU / HKLM
    path: str = ""     # Datei (bei Ordner-Einträgen)

    @property
    def target(self) -> str:
        return extract_executable(self.command) if self.command else self.path


def extract_executable(command: str) -> str:
    """Programmpfad aus einer Befehlszeile ermitteln."""
    c = command.strip()
    if c.startswith('"'):
        end = c.find('"', 1)
        return c[1:end] if end > 0 else c.strip('"')
    lower = c.lower()
    for ext in (".exe", ".bat", ".cmd", ".com", ".lnk"):
        i = lower.find(ext)
        if i > 0:
            return c[: i + len(ext)]
    return c.split(" ")[0]


def is_enabled_flag(data: bytes | None) -> bool:
    """StartupApproved: erstes Byte gerade (02/06) = aktiv, ungerade (03/07) = deaktiviert."""
    if not data:
        return True
    return data[0] % 2 == 0


def disabled_blob(now: float | None = None) -> bytes:
    ft = int(((now or time.time()) + 11644473600) * 10_000_000)
    return struct.pack("<I", 3) + struct.pack("<Q", ft)


ENABLED_BLOB = struct.pack("<I", 2) + b"\x00" * 8


def _folders() -> list[tuple[str, str, bool]]:
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    return [
        (os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup"), "user_folder", False),
        (os.path.join(programdata, r"Microsoft\Windows\Start Menu\Programs\StartUp"), "common_folder", True),
    ]


def list_items() -> list[StartupItem]:
    if not IS_WINDOWS:
        return []
    import winreg

    items: list[StartupItem] = []
    sources = [
        (winreg.HKEY_CURRENT_USER, "HKCU", RUN, "hkcu_run", "Run", False),
        (winreg.HKEY_LOCAL_MACHINE, "HKLM", RUN, "hklm_run", "Run", True),
        (winreg.HKEY_LOCAL_MACHINE, "HKLM", RUN32, "hklm_run32", "Run32", True),
    ]
    for root, hive, path, loc, approved, admin in sources:
        try:
            with winreg.OpenKey(root, path) as k:
                i = 0
                while True:
                    try:
                        name, value, _t = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if not name:
                        continue
                    flag = _read_approved(root, approved, name)
                    items.append(StartupItem(name, str(value), loc, is_enabled_flag(flag), admin, approved, hive))
        except OSError:
            continue
    for folder, loc, admin in _folders():
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        root = winreg.HKEY_LOCAL_MACHINE if admin else winreg.HKEY_CURRENT_USER
        for f in entries:
            if f.lower() == "desktop.ini":
                continue
            full = os.path.join(folder, f)
            flag = _read_approved(root, "StartupFolder", f)
            items.append(StartupItem(os.path.splitext(f)[0], "", loc, is_enabled_flag(flag), admin, "StartupFolder",
                                     "HKLM" if admin else "HKCU", full))
    items.sort(key=lambda x: x.name.lower())
    return items


def _read_approved(root, sub: str, name: str) -> bytes | None:
    import winreg

    try:
        with winreg.OpenKey(root, f"{APPROVED}\\{sub}") as k:
            data, _ = winreg.QueryValueEx(k, name)
            return bytes(data) if data is not None else None
    except OSError:
        return None


def set_enabled(item: StartupItem, enabled: bool) -> None:
    """Aktiviert/deaktiviert einen Eintrag (umkehrbar). Wirft PermissionError ohne nötige Rechte."""
    if not IS_WINDOWS:
        raise OSError("only windows")
    import winreg

    root = winreg.HKEY_LOCAL_MACHINE if item.hive == "HKLM" else winreg.HKEY_CURRENT_USER
    key_name = os.path.basename(item.path) if item.path else item.name
    try:
        with winreg.CreateKeyEx(root, f"{APPROVED}\\{item.approved_key}", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, key_name, 0, winreg.REG_BINARY, ENABLED_BLOB if enabled else disabled_blob())
    except PermissionError:
        raise
    except OSError as exc:
        if getattr(exc, "winerror", None) == 5:
            raise PermissionError(str(exc)) from exc
        raise
    # Prüfen, ob die Änderung wirklich angekommen ist
    if is_enabled_flag(_read_approved(root, item.approved_key, key_name)) != enabled:
        raise OSError("verification failed")
    item.enabled = enabled


# ---- CoreControl selbst -----------------------------------------------------
def self_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{exe}" -m corecontrol --minimized'


def set_self_autostart(enabled: bool) -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, SELF_NAME, 0, winreg.REG_SZ, self_command())
            else:
                try:
                    winreg.DeleteValue(k, SELF_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.warning("Autostart von CoreControl konnte nicht geändert werden: %s", exc)
        return False

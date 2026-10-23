"""Installierte Programme aus der Windows-Registry (wie in „Apps & Features“)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from corecontrol.core.platform import IS_WINDOWS

log = logging.getLogger(__name__)

UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
UNINSTALL32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass
class Program:
    name: str
    version: str = ""
    publisher: str = ""
    install_date: datetime | None = None
    size: int | None = None
    location: str = ""
    scope: str = ""  # machine / user
    arch: str = ""   # 64 / 32


def parse_install_date(v) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    for f in ("%Y%m%d", "%d.%m.%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def list_programs() -> list[Program]:
    if not IS_WINDOWS:
        return []
    import winreg

    out: dict[tuple[str, str], Program] = {}
    for root, scope in ((winreg.HKEY_LOCAL_MACHINE, "machine"), (winreg.HKEY_CURRENT_USER, "user")):
        for path, arch in ((UNINSTALL, "64"), (UNINSTALL32, "32")):
            try:
                key = winreg.OpenKey(root, path)
            except OSError:
                continue
            with key:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(key, sub) as k:
                            vals = {}
                            j = 0
                            while True:
                                try:
                                    n, v, _t = winreg.EnumValue(k, j)
                                except OSError:
                                    break
                                vals[n] = v
                                j += 1
                    except OSError:
                        continue
                    name = str(vals.get("DisplayName") or "").strip()
                    if not name or vals.get("SystemComponent") == 1 or vals.get("ParentKeyName") or \
                            str(vals.get("ReleaseType", "")).lower() in ("update", "hotfix", "security update"):
                        continue
                    size = vals.get("EstimatedSize")
                    p = Program(
                        name=name,
                        version=str(vals.get("DisplayVersion") or ""),
                        publisher=str(vals.get("Publisher") or ""),
                        install_date=parse_install_date(vals.get("InstallDate")),
                        size=int(size) * 1024 if isinstance(size, int) and size > 0 else None,
                        location=str(vals.get("InstallLocation") or ""),
                        scope=scope,
                        arch=arch if root == winreg.HKEY_LOCAL_MACHINE else "",
                    )
                    out.setdefault((name.lower(), p.version), p)
    return sorted(out.values(), key=lambda p: p.name.lower())

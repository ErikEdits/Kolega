"""Einordnung von Dateien und Schutzregeln für das Löschen.

Grundsatz: Im Zweifel nicht löschen. Systemdateien, Programmordner und
unbekannte Bereiche werden nie zum Löschen vorgeschlagen und sind gesperrt.
"""

from __future__ import annotations

import os
from pathlib import PureWindowsPath

from corecontrol.core.platform import IS_WINDOWS

SYSTEM_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log", "dumpstack.log.tmp", "bootmgr",
                "bootnxt", "ntldr", "desktop.ini", "thumbs.db"}

EXT_CATEGORY = {
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv", ".mpg", ".mpeg", ".ts", ".m2ts"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff", ".raw", ".cr2", ".nef", ".arw", ".dng", ".psd", ".svg"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"},
    "document": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".txt", ".rtf", ".csv", ".md", ".epub"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".cab"},
    "installer": {".exe", ".msi", ".msix", ".appx", ".msixbundle"},
    "disk_image": {".iso", ".img", ".vhd", ".vhdx", ".vmdk", ".vdi", ".wim", ".esd"},
    "temp": {".tmp", ".temp", ".log", ".dmp", ".bak", ".old", ".etl", ".cache"},
    "program": {".dll", ".sys", ".pak", ".bin", ".dat", ".asset", ".bundle", ".vpk", ".ucas", ".utoc", ".pck"},
}


def ext_category(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    for cat, exts in EXT_CATEGORY.items():
        if ext in exts:
            return cat
    return "other"


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def _env_dirs() -> dict[str, str]:
    e = os.environ
    windir = e.get("WINDIR") or e.get("SystemRoot") or r"C:\Windows"
    return {
        "windows": windir,
        "program_files": e.get("ProgramFiles") or r"C:\Program Files",
        "program_files_x86": e.get("ProgramFiles(x86)") or r"C:\Program Files (x86)",
        "program_data": e.get("ProgramData") or r"C:\ProgramData",
        "user_profile": e.get("USERPROFILE") or os.path.expanduser("~"),
        "appdata": e.get("APPDATA") or "",
        "local_appdata": e.get("LOCALAPPDATA") or "",
        "temp": e.get("TEMP") or "",
    }


def _rel_parts(path: str, base: str) -> list[str]:
    """Pfadbestandteile unterhalb von base (kleingeschrieben)."""
    rel = os.path.relpath(_norm(path), _norm(base))
    return [x.lower() for x in rel.replace("\\", "/").split("/") if x and x != "."]


def _under(path: str, base: str) -> bool:
    if not base:
        return False
    p, b = _norm(path), _norm(base)
    return p == b or p.startswith(b.rstrip("\\/") + os.sep)


def classify(path: str) -> str:
    """Einordnung: system, program, appdata, temp, user, recycle, unknown."""
    d = _env_dirs()
    name = os.path.basename(path).lower()
    parts = [x.lower() for x in (PureWindowsPath(path).parts if IS_WINDOWS else path.split("/"))]
    if name in SYSTEM_FILES or "system volume information" in parts or "$windows.~bt" in parts or "$windows.~ws" in parts:
        return "system"
    if "$recycle.bin" in parts:
        return "recycle"
    if _under(path, d["temp"]):
        return "temp"
    if _under(path, d["windows"]):
        return "temp" if _rel_parts(path, d["windows"])[:1] == ["temp"] else "system"
    if _under(path, d["program_files"]) or _under(path, d["program_files_x86"]):
        return "program"
    if _under(path, d["program_data"]):
        return "appdata"
    for key in ("local_appdata", "appdata"):
        if _under(path, d[key]):
            rel = _rel_parts(path, d[key])[:-1]  # nur Ordner, nicht der Dateiname
            if any(x in ("temp", "cache", "cache_data", "crashdumps", "cache2") for x in rel):
                return "temp"
            return "appdata"
    if _under(path, d["user_profile"]):
        return "user"
    if ext_category(path) == "temp":
        return "temp"
    return "unknown"


def is_protected_path(path: str) -> bool:
    """True = darf von CoreControl nicht gelöscht werden."""
    p = _norm(path)
    d = _env_dirs()
    # Laufwerkswurzeln und wichtige Ordner selbst
    if len(p.rstrip("\\/")) <= 3:
        return True
    for key in ("windows", "program_files", "program_files_x86", "program_data", "user_profile", "appdata", "local_appdata"):
        if d[key] and p == _norm(d[key]):
            return True
    cls = classify(path)
    return cls in ("system", "program", "recycle")


def is_within(path: str, roots: list[str]) -> bool:
    return any(_under(path, r) for r in roots if r)


def is_link_or_reparse(path: str) -> bool:
    """Verknüpfungen/Junctions werden nie verfolgt oder gelöscht."""
    try:
        if os.path.islink(path):
            return True
        st = os.lstat(path)
        attrs = getattr(st, "st_file_attributes", 0)
        return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False

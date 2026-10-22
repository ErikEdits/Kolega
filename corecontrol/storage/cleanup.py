"""Sichere Bereinigung von temporären Dateien und Caches.

Sicherheitsregeln (fest eingebaut):
- Es wird nichts ohne ausdrückliche Bestätigung gelöscht (confirmed=True nötig).
- Vorgeschlagen werden nur bekannte, wiederherstellbare Bereiche (Temp, Caches, Absturzberichte).
- Persönliche Ordner (Downloads, Dokumente …) werden nie automatisch ausgewählt.
- Standardmäßig nur Dateien, die älter als X Tage sind (gerade benutzte Dateien bleiben).
- Jede Datei wird vor dem Löschen erneut geprüft: existiert sie, liegt sie im
  erlaubten Bereich, ist sie keine Verknüpfung, ist sie nicht geschützt?
- Standard: in den Papierkorb verschieben (rückgängig machbar).
- Nach dem Löschen wird überprüft, ob die Datei wirklich weg ist.
"""

from __future__ import annotations

import glob
import logging
import os
import time
from dataclasses import dataclass, field

from corecontrol.core.platform import IS_WINDOWS
from corecontrol.storage.safety import is_link_or_reparse, is_protected_path, is_within

log = logging.getLogger(__name__)

MAX_FILES_PER_CATEGORY = 50_000


@dataclass
class CleanupFile:
    path: str
    size: int
    mtime: float


@dataclass
class CleanupCategory:
    id: str
    roots: list[str]
    patterns: list[str] | None = None      # nur diese Dateimuster (z. B. thumbcache_*.db)
    default_selected: bool = False
    needs_admin: bool = False
    risk: str = "low"                       # low / medium
    min_age: bool = True                    # Altersgrenze anwenden?
    files: list[CleanupFile] = field(default_factory=list)
    total: int = 0
    denied: int = 0
    truncated: bool = False
    exists: bool = False


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name) or default


def category_definitions() -> list[CleanupCategory]:
    if not IS_WINDOWS:
        tmp = _env("TMPDIR", "/tmp")
        return [CleanupCategory("user_temp", [tmp], default_selected=True)]
    local = _env("LOCALAPPDATA")
    windir = _env("WINDIR", r"C:\Windows")
    progdata = _env("PROGRAMDATA", r"C:\ProgramData")
    cats = [
        CleanupCategory("user_temp", [_env("TEMP")], default_selected=True),
        CleanupCategory("windows_temp", [os.path.join(windir, "Temp")], default_selected=True, needs_admin=True),
        CleanupCategory("crash_dumps", [os.path.join(local, "CrashDumps")], default_selected=True, min_age=False),
        CleanupCategory("wer", [os.path.join(local, r"Microsoft\Windows\WER\ReportArchive"),
                                os.path.join(local, r"Microsoft\Windows\WER\ReportQueue"),
                                os.path.join(progdata, r"Microsoft\Windows\WER\ReportArchive"),
                                os.path.join(progdata, r"Microsoft\Windows\WER\ReportQueue")],
                        default_selected=True, min_age=False),
        CleanupCategory("thumbnails", [os.path.join(local, r"Microsoft\Windows\Explorer")],
                        patterns=["thumbcache_*.db", "iconcache_*.db"], min_age=False, risk="low"),
        CleanupCategory("shader_cache", [os.path.join(local, "D3DSCache"), os.path.join(local, r"NVIDIA\DXCache"),
                                         os.path.join(local, r"NVIDIA\GLCache"), os.path.join(local, r"AMD\DxCache"),
                                         os.path.join(local, r"AMD\DxcCache"), os.path.join(local, r"AMD\VkCache"),
                                         os.path.join(local, r"Intel\ShaderCache")], min_age=False, risk="medium"),
        CleanupCategory("browser_cache", _browser_cache_dirs(local), min_age=False, risk="medium"),
    ]
    return cats


def _browser_cache_dirs(local: str) -> list[str]:
    out: list[str] = []
    for base in (r"Google\Chrome\User Data", r"Microsoft\Edge\User Data", r"BraveSoftware\Brave-Browser\User Data"):
        for prof in glob.glob(os.path.join(local, base, "*")):
            for sub in (r"Cache\Cache_Data", "Code Cache", "GPUCache"):
                p = os.path.join(prof, sub)
                if os.path.isdir(p):
                    out.append(p)
    for prof in glob.glob(os.path.join(local, r"Mozilla\Firefox\Profiles", "*")):
        p = os.path.join(prof, "cache2")
        if os.path.isdir(p):
            out.append(p)
    return out


def safe_root(root: str, category_id: str = "") -> bool:
    r"""Schutz vor ungewöhnlichen Umgebungen (z. B. TEMP=C:\ oder TEMP=Benutzerordner):
    Solche Ordner werden nie als Bereinigungsbereich akzeptiert."""
    if not root or not os.path.isabs(root):
        return False
    norm = os.path.normcase(os.path.normpath(root))
    if len(norm.rstrip("\\/")) <= 3:
        return False
    important = [os.environ.get(k) for k in ("USERPROFILE", "WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)",
                                             "ProgramData", "APPDATA", "LOCALAPPDATA", "HOME")]
    important.append(os.path.expanduser("~"))
    for imp in important:
        if imp and norm == os.path.normcase(os.path.normpath(imp)):
            return False
    if category_id in ("user_temp", "windows_temp"):
        # Der Temp-Ordner endet üblicherweise auf „Temp“ (bei Remotesitzungen „Temp\2“)
        tail = [x.lower() for x in norm.replace("/", "\\").split("\\")[-2:]]
        if not any(x in ("temp", "tmp") for x in tail):
            return False
    return True


def _collect(cat: CleanupCategory, min_age_days: int, ctx=None) -> None:
    cutoff = time.time() - min_age_days * 86400 if cat.min_age else None
    import fnmatch

    cat.roots = [r for r in cat.roots if safe_root(r, cat.id)]
    for root in cat.roots:
        if not os.path.isdir(root):
            continue
        cat.exists = True
        stack = [root]
        while stack:
            if ctx is not None and ctx.cancelled:
                return
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                cat.denied += 1
                continue
            with it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        st = e.stat(follow_symlinks=False)
                        if getattr(st, "st_file_attributes", 0) & 0x400:
                            continue
                        if e.is_dir(follow_symlinks=False):
                            if cat.patterns is None:
                                stack.append(e.path)
                            continue
                        if cat.patterns is not None and not any(fnmatch.fnmatch(e.name.lower(), p) for p in cat.patterns):
                            continue
                        if cutoff is not None and st.st_mtime > cutoff:
                            continue
                    except OSError:
                        continue
                    if len(cat.files) >= MAX_FILES_PER_CATEGORY:
                        cat.truncated = True
                        return
                    cat.files.append(CleanupFile(e.path, st.st_size, st.st_mtime))
                    cat.total += st.st_size


def scan_categories(min_age_days: int = 2, ctx=None) -> list[CleanupCategory]:
    cats = category_definitions()
    for c in cats:
        if ctx is not None and ctx.cancelled:
            break
        if ctx is not None:
            ctx.progress(c.id)
        try:
            _collect(c, min_age_days, ctx)
        except Exception as exc:
            log.warning("Bereinigungskategorie %s: %s", c.id, exc)
    return cats


@dataclass
class DeleteResult:
    deleted: int = 0
    deleted_bytes: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    to_trash: bool = True


def validate_for_delete(path: str, allowed_roots: list[str]) -> str | None:
    """Gibt einen Grund zurück, warum NICHT gelöscht werden darf – oder None."""
    if not os.path.isabs(path):
        return "not_absolute"
    if not os.path.lexists(path):
        return "missing"
    if is_link_or_reparse(path):
        return "link"
    if os.path.isdir(path):
        return "directory"
    if allowed_roots and not is_within(path, allowed_roots):
        return "outside"
    if is_protected_path(path) and not (allowed_roots and is_within(path, allowed_roots)):
        return "protected"
    return None


def delete_files(files: list[tuple[str, int]], allowed_roots: list[str], confirmed: bool, permanent: bool = False,
                 ctx=None, trash_func=None) -> DeleteResult:
    """Löscht die übergebenen Dateien (Pfad, Größe). Nur mit confirmed=True."""
    res = DeleteResult(to_trash=not permanent)
    if not confirmed:
        raise PermissionError("Löschen ohne Bestätigung ist nicht erlaubt")
    requested_roots = list(allowed_roots)
    allowed_roots = [r for r in allowed_roots if safe_root(r)]
    if requested_roots and not allowed_roots:
        res.skipped = [(p, "outside") for p, _ in files]
        return res
    if trash_func is None and not permanent:
        from send2trash import send2trash as trash_func  # noqa: N813
    for i, (path, size) in enumerate(files):
        if ctx is not None and ctx.cancelled:
            break
        reason = validate_for_delete(path, allowed_roots)
        if reason:
            res.skipped.append((path, reason))
            continue
        try:
            if permanent:
                os.remove(path)
            else:
                trash_func(path)
        except PermissionError:
            res.failed.append((path, "access_denied"))
            continue
        except OSError as exc:
            res.failed.append((path, "in_use" if getattr(exc, "winerror", None) == 32 else type(exc).__name__))
            continue
        except Exception as exc:  # send2trash kann eigene Fehler werfen
            res.failed.append((path, type(exc).__name__))
            continue
        if os.path.lexists(path):
            res.failed.append((path, "still_exists"))
            continue
        res.deleted += 1
        res.deleted_bytes += size
        if ctx is not None and i % 200 == 0:
            ctx.progress(i)
    return res


# ---- Papierkorb --------------------------------------------------------------
def recycle_bin_info() -> tuple[int, int] | None:
    """(Größe in Bytes, Anzahl Elemente) aller Papierkörbe – oder None."""
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]

    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    hr = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if hr != 0:
        return None
    return int(info.i64Size), int(info.i64NumItems)


def empty_recycle_bin(confirmed: bool) -> bool:
    """Leert den Papierkorb endgültig (nicht rückgängig zu machen). Nur mit Bestätigung."""
    if not confirmed:
        raise PermissionError("Bestätigung erforderlich")
    if not IS_WINDOWS:
        return False
    import ctypes

    SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
    return hr in (0, -2147418113)  # S_OK oder E_UNEXPECTED (bereits leer)

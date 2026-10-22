"""Spiele erkennen (Steam, Epic Games) und starten.

Erkennung: Es werden nur die Bibliotheksdateien der Launcher gelesen.
Starten: über die offiziellen Startadressen der Launcher (steam://, com.epicgames.launcher://)
oder bei manuell hinzugefügten Spielen über die angegebene EXE/Verknüpfung.
CoreControl verändert dabei keine Spieldateien und startet keine Launcher-Updates.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
from dataclasses import dataclass

from corecontrol.core.platform import IS_WINDOWS, open_path, open_url

log = logging.getLogger(__name__)

STEAM_SKIP_APPIDS = {"228980", "1070560", "1391110", "1628350", "1826330", "2180100", "250820", "1493710"}
STEAM_SKIP_NAMES = ("steamworks common", "proton", "steam linux runtime", "steamvr")


@dataclass
class Game:
    name: str
    target: str
    source: str  # steam, epic, manual
    install_dir: str = ""


# ---- VDF (Steam KeyValues) -----------------------------------------------------
_TOKEN = re.compile(r'"((?:\\.|[^"\\])*)"|(\{)|(\})')


def parse_vdf(text: str) -> dict:
    """Minimaler Parser für Steams Textformat (libraryfolders.vdf, appmanifest_*.acf)."""
    root: dict = {}
    stack = [root]
    key: str | None = None
    for m in _TOKEN.finditer(text):
        s, open_b, close_b = m.groups()
        if open_b:
            new: dict = {}
            if key is not None:
                stack[-1][key] = new
            stack.append(new)
            key = None
        elif close_b:
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            s = s.replace('\\\\', '\\').replace('\\"', '"')
            if key is None:
                key = s
            else:
                stack[-1][key] = s
                key = None
    return root


def _steam_root() -> str | None:
    if not IS_WINDOWS:
        return None
    import winreg

    for root, path, name in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(root, path) as k:
                v = winreg.QueryValueEx(k, name)[0]
                if v and os.path.isdir(v):
                    return os.path.normpath(v)
        except OSError:
            continue
    return None


def steam_games(steam_root: str | None = None) -> list[Game]:
    root = steam_root or _steam_root()
    if not root:
        return []
    libs = {os.path.normpath(root)}
    lf = os.path.join(root, "steamapps", "libraryfolders.vdf")
    try:
        with open(lf, encoding="utf-8", errors="replace") as fh:
            data = parse_vdf(fh.read())
        folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
        for k, v in folders.items():
            if isinstance(v, dict) and v.get("path"):
                libs.add(os.path.normpath(v["path"]))
            elif isinstance(v, str) and k.isdigit():
                libs.add(os.path.normpath(v))
    except OSError:
        pass
    games: list[Game] = []
    for lib in libs:
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                with open(acf, encoding="utf-8", errors="replace") as fh:
                    st = parse_vdf(fh.read()).get("AppState", {})
            except OSError:
                continue
            appid, name = st.get("appid", ""), st.get("name", "")
            if not appid or not name or appid in STEAM_SKIP_APPIDS or name.lower().startswith(STEAM_SKIP_NAMES):
                continue
            games.append(Game(name, f"steam://rungameid/{appid}", "steam",
                              os.path.join(lib, "steamapps", "common", st.get("installdir", ""))))
    return games


def epic_games(manifest_dir: str | None = None) -> list[Game]:
    if manifest_dir is None:
        if not IS_WINDOWS:
            return []
        manifest_dir = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Epic\EpicGamesLauncher\Data\Manifests")
    games: list[Game] = []
    for item in glob.glob(os.path.join(manifest_dir, "*.item")):
        try:
            with open(item, encoding="utf-8", errors="replace") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        name = d.get("DisplayName")
        app = d.get("AppName")
        if not name or not app or d.get("bIsIncompleteInstall"):
            continue
        cats = [c.lower() for c in d.get("AppCategories") or []]
        if cats and "games" not in cats:
            continue
        ns, cid = d.get("CatalogNamespace"), d.get("CatalogItemId")
        ident = f"{ns}%3A{cid}%3A{app}" if ns and cid else app
        games.append(Game(name, f"com.epicgames.launcher://apps/{ident}?action=launch&silent=true", "epic",
                          d.get("InstallLocation", "")))
    return games


def detect_games() -> list[Game]:
    out: list[Game] = []
    for fn in (steam_games, epic_games):
        try:
            out.extend(fn())
        except Exception as exc:
            log.warning("Spieleerkennung (%s) fehlgeschlagen: %s", fn.__name__, exc)
    return sorted(out, key=lambda g: g.name.lower())


ALLOWED_PREFIXES = ("steam://rungameid/", "com.epicgames.launcher://apps/")
ALLOWED_EXT = (".exe", ".lnk", ".url")


def validate_target(target: str) -> str | None:
    """Gibt einen Fehlergrund zurück oder None, wenn das Ziel gestartet werden darf."""
    t = (target or "").strip()
    if t.startswith(ALLOWED_PREFIXES):
        return None
    if "://" in t:
        return "unsupported_url"
    if not os.path.isabs(t):
        return "not_absolute"
    if os.path.splitext(t)[1].lower() not in ALLOWED_EXT:
        return "bad_extension"
    if not os.path.isfile(t):
        return "missing"
    return None


def launch(target: str) -> bool:
    reason = validate_target(target)
    if reason:
        raise ValueError(reason)
    if target.startswith(ALLOWED_PREFIXES):
        return open_url(target)
    if target.lower().endswith(".exe"):
        import subprocess

        # Viele Spiele erwarten ihren eigenen Ordner als Arbeitsverzeichnis
        subprocess.Popen([target], cwd=os.path.dirname(target), close_fds=True)
        return True
    return open_path(target)

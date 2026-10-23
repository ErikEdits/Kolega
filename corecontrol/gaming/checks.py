"""Gaming-Prüfungen: nur Anzeige und nachvollziehbare Hinweise, keine automatischen Änderungen.

Bewusst NICHT enthalten: Registry-„Tweaks“, Deaktivieren von Diensten, „FPS-Booster“.
Solche Eingriffe bringen meist keinen messbaren Vorteil und können Probleme verursachen.
"""

from __future__ import annotations

from dataclasses import dataclass

from corecontrol.core.platform import IS_WINDOWS


@dataclass
class GamingCheck:
    id: str
    state: str          # ok, hint, unknown
    value: str = ""     # Zusatzinfo (z. B. Prozessname)
    action: str = ""    # Aktions-Kennung (url:/tool:/nav:)


def _reg_dword(root, path: str, name: str):
    import winreg

    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def run_checks(power_scheme: str | None, top_cpu: list | None = None, ram_percent: float | None = None) -> list[GamingCheck]:
    out: list[GamingCheck] = []
    if IS_WINDOWS:
        import winreg

        gm = _reg_dword(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
        # Fehlt der Wert, ist der Spielmodus unter Windows 10/11 standardmäßig an.
        out.append(GamingCheck("game_mode", "hint" if gm == 0 else "ok", action="url:ms-settings:gaming-gamemode"))
        hags = _reg_dword(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
        out.append(GamingCheck("hags", "unknown" if hags is None else ("ok" if hags == 2 else "info"),
                               value="on" if hags == 2 else "off" if hags is not None else "",
                               action="url:ms-settings:display-advancedgraphics"))
    if power_scheme is not None:
        out.append(GamingCheck("power_plan", "hint" if power_scheme == "a1841308-3541-4fab-bc81-f71556f20b4a" else "ok",
                               action="tool:powercfg"))
    if top_cpu:
        heavy = [p for p in top_cpu if p.cpu >= 15]
        out.append(GamingCheck("background", "hint" if heavy else "ok",
                               value=", ".join(f"{p.name}" for p in heavy[:3]), action="nav:processes"))
    if ram_percent is not None:
        out.append(GamingCheck("ram_free", "hint" if ram_percent >= 85 else "ok", value=f"{ram_percent:.0f}",
                               action="nav:processes"))
    return out

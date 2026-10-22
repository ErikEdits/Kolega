"""Update-Prüfung über die GitHub-Releases des offiziellen Projekts.

Sicherheitsprinzip: CoreControl lädt und startet NIE automatisch etwas aus dem Internet.
Es wird nur geprüft, ob eine neuere Version existiert, und auf Wunsch die
offizielle Release-Seite im Browser geöffnet. Der Download erfolgt manuell.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from corecontrol import REPO_SLUG, REPO_URL, __version__
from corecontrol.i18n import tr

API_URL = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"
ALLOWED_PAGE_PREFIX = f"{REPO_URL}/releases"


def parse_version(v: str) -> tuple[int, ...] | None:
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", v or "")
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


@dataclass
class UpdateResult:
    status: str  # update, current, no_release, offline, error
    latest_version: str = ""
    url: str = ""
    notes: str = ""
    error: str = ""

    @property
    def update_available(self) -> bool:
        return self.status == "update"

    def describe(self) -> str:
        if self.status == "update":
            return tr("updates.available", version=self.latest_version, current=__version__)
        if self.status == "current":
            return tr("updates.current", version=__version__)
        if self.status == "no_release":
            return tr("updates.no_release")
        if self.status == "offline":
            return tr("updates.offline")
        return tr("updates.failed", error=self.error)


def check_for_update(timeout: float = 8.0, opener=None) -> UpdateResult:
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"CoreControl/{__version__}"})
    try:
        open_fn = opener or urllib.request.urlopen
        with open_fn(req, timeout=timeout) as resp:
            data = json.loads(resp.read(1_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return UpdateResult("no_release")
        return UpdateResult("error", error=f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return UpdateResult("offline", error=str(exc))
    except ValueError as exc:
        return UpdateResult("error", error=str(exc))
    tag = str(data.get("tag_name") or "")
    page = str(data.get("html_url") or "")
    # Nur die offizielle Release-Seite zulassen
    if not page.startswith(ALLOWED_PAGE_PREFIX):
        page = f"{REPO_URL}/releases"
    if data.get("draft") or data.get("prerelease"):
        return UpdateResult("current", latest_version=tag)
    if is_newer(tag):
        return UpdateResult("update", latest_version=tag.lstrip("v"), url=page, notes=str(data.get("body") or "")[:4000])
    return UpdateResult("current", latest_version=tag.lstrip("v"))

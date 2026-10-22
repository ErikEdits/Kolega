"""Entfernt persönliche Angaben aus Berichten, bevor sie geteilt werden.

Ersetzt werden: Benutzername (auch in Pfaden), Computername, IP-Adressen,
MAC-Adressen, E-Mail-Adressen und WLAN-Namen (SSID). Der Benutzer sieht den
bereinigten Bericht vor dem Speichern in der Vorschau und kann ihn prüfen.
"""

from __future__ import annotations

import getpass
import os
import re
import socket
from dataclasses import dataclass, field

IPV4 = re.compile(r"(?<![\d.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\d.])")
IPV6 = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4}(?:%\w+)?(?![0-9A-Fa-f:])")
MAC = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass
class Redactor:
    user: str = ""
    host: str = ""
    ssids: list[str] = field(default_factory=list)
    keep_ips: set[str] = field(default_factory=lambda: {"127.0.0.1", "0.0.0.0", "1.1.1.1", "8.8.8.8", "8.8.4.4", "9.9.9.9"})
    labels: dict[str, str] = field(default_factory=lambda: {"user": "<USER>", "host": "<PC>", "ip": "<IP>", "ipv6": "<IPv6>",
                                                            "mac": "<MAC>", "email": "<E-MAIL>", "ssid": "<WLAN>"})

    @classmethod
    def for_this_pc(cls, extra_keep_ips: list[str] | None = None, ssids: list[str] | None = None) -> "Redactor":
        try:
            user = getpass.getuser()
        except Exception:
            user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        r = cls(user=user, host=socket.gethostname(), ssids=[s for s in (ssids or []) if s])
        r.keep_ips |= set(extra_keep_ips or [])
        return r

    def __call__(self, text: str) -> str:
        if not text:
            return text
        out = text
        for s in sorted(self.ssids, key=len, reverse=True):
            if len(s) >= 2:
                out = out.replace(s, self.labels["ssid"])
        out = EMAIL.sub(self.labels["email"], out)
        out = MAC.sub(self.labels["mac"], out)
        out = IPV4.sub(lambda m: m.group(0) if m.group(0) in self.keep_ips else self.labels["ip"], out)
        out = IPV6.sub(lambda m: m.group(0) if m.group(0).count(":") < 2 or _looks_like_time(m.group(0)) else self.labels["ipv6"], out)
        if self.host and len(self.host) >= 2:
            out = re.sub(re.escape(self.host), self.labels["host"], out, flags=re.IGNORECASE)
        if self.user and len(self.user) >= 2:
            # Benutzername in Pfaden (C:\Users\Name) und als ganzes Wort
            out = re.sub(r"(?i)(\\Users\\|/home/|/Users/)" + re.escape(self.user), lambda m: m.group(1) + self.labels["user"], out)
            out = re.sub(r"(?i)(?<![A-Za-z0-9])" + re.escape(self.user) + r"(?![A-Za-z0-9])", self.labels["user"], out)
        return out


def _looks_like_time(s: str) -> bool:
    """Uhrzeiten wie 12:30:45 nicht als IPv6 behandeln."""
    return bool(re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", s))

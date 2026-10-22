"""Datenmodell der Diagnose.

Jeder Befund (Finding) beantwortet:
- Was wurde erkannt?           → title, detected (mit Messwerten)
- Wie wichtig ist es?          → severity (critical / warning / info / ok)
- Was könnte die Ursache sein? → causes
- Was kann ich tun?            → recommendations (+ actions als Schaltflächen)
- Welche Risiken bestehen?     → risks
- Wie sicher ist die Aussage?  → confidence (high / medium / low) + uncertainty
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from corecontrol.i18n import T

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
CATEGORIES = ("thermal", "cpu", "memory", "gpu", "storage", "events", "drivers", "network", "system", "software")


@dataclass
class Finding:
    id: str
    category: str
    severity: str
    title: T
    detected: T
    causes: list[T] = field(default_factory=list)
    recommendations: list[T] = field(default_factory=list)
    risks: T | None = None
    confidence: str = "high"
    uncertainty: T | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    actions: list[tuple[str, str]] = field(default_factory=list)  # (Übersetzungsschlüssel, Aktion)

    @property
    def is_problem(self) -> bool:
        return self.severity in ("critical", "warning", "info")


@dataclass
class DiagnosisResult:
    started_at: float
    finished_at: float
    findings: list[Finding]
    hardware: dict | None = None
    events: Any = None
    network: Any = None
    live: dict | None = None
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (Bereich, Grund)
    app_version: str = ""

    def sorted(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.category))

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)

    def problems(self) -> list[Finding]:
        return [f for f in self.sorted() if f.severity in ("critical", "warning")] + \
               [f for f in self.sorted() if f.severity == "info"]

    @property
    def overall(self) -> str:
        for sev in ("critical", "warning"):
            if self.count(sev):
                return sev
        return "ok"

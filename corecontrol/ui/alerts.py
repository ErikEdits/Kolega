"""Live-Warnungen (Temperatur, Auslastung, Speicherplatz) mit Verzögerung gegen Fehlalarme
und Pause zwischen wiederholten Benachrichtigungen."""

from __future__ import annotations

import time
from dataclasses import dataclass

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from corecontrol.core import fmt
from corecontrol.i18n import tr


@dataclass
class Alert:
    key: str
    level: str  # warning / critical
    title: str
    text: str
    target: str


class AlertMonitor(QObject):
    changed = Signal(object)  # Liste aktiver Alerts

    # Wie lange muss ein Zustand anhalten, bevor gewarnt wird (Sekunden)
    HOLD = {"cpu_temp": 20, "gpu_temp": 20, "ram": 60, "cpu_load": 120}

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._since: dict[str, float] = {}
        self._active: dict[str, Alert] = {}
        self._last_notify: dict[str, float] = {}
        self._disk_timer = QTimer(self)
        self._disk_timer.timeout.connect(self.check_disks)
        self._disk_timer.start(5 * 60 * 1000)
        QTimer.singleShot(3000, self.check_disks)

    def active(self) -> list[Alert]:
        order = {"critical": 0, "warning": 1}
        return sorted(self._active.values(), key=lambda a: order.get(a.level, 2))

    def _set(self, key: str, cond: bool, level: str, title: str, text: str, target: str, now: float) -> None:
        if cond:
            start = self._since.setdefault(key, now)
            if now - start >= self.HOLD.get(key.split(":")[0], 0):
                is_new = key not in self._active or self._active[key].level != level
                self._active[key] = Alert(key, level, title, text, target)
                if is_new:
                    self._notify(self._active[key], now)
                    self.changed.emit(self.active())
        else:
            self._since.pop(key, None)
            if self._active.pop(key, None) is not None:
                self.changed.emit(self.active())

    def _notify(self, a: Alert, now: float) -> None:
        st = self.ctx.settings
        if not st.get("notify.enabled") or self.ctx.tray is None:
            return
        cooldown = st.get("notify.cooldown_min") * 60
        if now - self._last_notify.get(a.key, 0) < cooldown:
            return
        self._last_notify[a.key] = now
        self.ctx.tray.notify(a.title, a.text, a.level == "critical")

    def on_sample(self, s) -> None:
        st = self.ctx.settings
        now = s.ts
        if s.cpu_temp is not None:
            crit, warn = st.get("thresholds.cpu_temp_crit"), st.get("thresholds.cpu_temp_warn")
            level = "critical" if s.cpu_temp >= crit else "warning"
            self._set("cpu_temp", s.cpu_temp >= warn, level, tr("alert.cpu_temp.title"),
                      tr("alert.cpu_temp.text", value=fmt.temp(s.cpu_temp), limit=fmt.temp(warn)), "monitoring", now)
        g = s.primary_gpu
        if g is not None and g.temp is not None:
            crit, warn = st.get("thresholds.gpu_temp_crit"), st.get("thresholds.gpu_temp_warn")
            level = "critical" if g.temp >= crit else "warning"
            self._set("gpu_temp", g.temp >= warn, level, tr("alert.gpu_temp.title"),
                      tr("alert.gpu_temp.text", value=fmt.temp(g.temp), limit=fmt.temp(warn)), "monitoring", now)
        if s.ram_percent is not None:
            lim = st.get("thresholds.ram_warn")
            self._set("ram", s.ram_percent >= lim, "warning", tr("alert.ram.title"),
                      tr("alert.ram.text", value=fmt.pct(s.ram_percent), limit=fmt.pct(lim)), "processes", now)
        if s.cpu_percent is not None:
            lim = st.get("thresholds.cpu_load_warn")
            self._set("cpu_load", s.cpu_percent >= lim, "warning", tr("alert.cpu_load.title"),
                      tr("alert.cpu_load.text", value=fmt.pct(s.cpu_percent), limit=fmt.pct(lim)), "processes", now)

    def check_disks(self) -> None:
        st = self.ctx.settings
        now = time.time()
        seen = set()
        try:
            parts = psutil.disk_partitions(all=False)
        except Exception:
            return
        for p in parts:
            if "cdrom" in p.opts or not p.fstype:
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue
            if u.total < 2 * 1024**3:
                continue
            free_pct = 100 - u.percent
            free_gb = u.free / 1024**3
            crit = free_pct < st.get("thresholds.disk_free_crit_pct") or free_gb < st.get("thresholds.disk_free_crit_gb")
            warn = free_pct < st.get("thresholds.disk_free_warn_pct") or free_gb < st.get("thresholds.disk_free_warn_gb")
            key = f"disk:{p.mountpoint}"
            seen.add(key)
            self._set(key, warn or crit, "critical" if crit else "warning", tr("alert.disk.title", drive=p.mountpoint),
                      tr("alert.disk.text", free=fmt.bytes_(u.free), pct=fmt.pct(free_pct)), "storage", now)
        for key in [k for k in self._active if k.startswith("disk:") and k not in seen]:
            self._set(key, False, "", "", "", "", now)

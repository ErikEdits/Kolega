"""Sammelt Live-Messwerte. Jede Quelle ist einzeln abgesichert:
fällt eine aus, bleiben ihre Werte „nicht verfügbar“, der Rest läuft weiter."""

from __future__ import annotations

import logging
import threading
import time

import psutil

from pathlib import Path

from corecontrol.core.platform import IS_WINDOWS
from corecontrol.monitoring import amd, lhm
from corecontrol.monitoring.models import GpuSample, Sample

log = logging.getLogger(__name__)


class LhmPoller:
    """Liest LibreHardwareMonitor in einem eigenen Thread.

    Eine langsame oder fehlende Verbindung hält die Live-Messung dadurch nie auf
    (unter Windows dauert schon der Versuch, einen geschlossenen lokalen Port zu
    erreichen, bis zu ~1 s). Gelesen wird nur, wenn die Messung nach Werten fragt:
    höchstens jede Sekunde, solange LibreHardwareMonitor antwortet, sonst alle 10 s.
    """

    OK_EVERY = 1.0
    RETRY_EVERY = 10.0

    def __init__(self, port: int, reader=None):
        self.port = port
        self._reader = reader if reader is not None else lhm.LhmReader(port)
        self._lock = threading.Lock()
        self._latest: tuple[str, list] = ("not_running", [])
        self._read_at = float("-inf")
        self._busy = False
        self._stop = False
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="lhm-poller", daemon=True)
        self._thread.start()

    def latest(self) -> tuple[str, list]:
        """Letztes Ergebnis sofort zurückgeben; bei Bedarf im Hintergrund neu lesen."""
        with self._lock:
            res = self._latest
            due = time.monotonic() - self._read_at >= (self.OK_EVERY if res[0] == "ok" else self.RETRY_EVERY)
            if due and not self._busy:
                self._busy = True
                self._wake.set()
        return res

    def retry_now(self) -> None:
        with self._lock:
            self._read_at = float("-inf")

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            if self._stop:
                return
            try:
                res = self._reader.read()
            except Exception as exc:
                log.debug("LibreHardwareMonitor: %s", exc)
                res = ("not_running", [])
            with self._lock:
                self._latest = res
                self._read_at = time.monotonic()
                self._busy = False

    def close(self) -> None:
        self._stop = True
        self._wake.set()
        self._thread.join(timeout=1.5)


class Collector:
    def __init__(self, lhm_enabled: bool = True, lhm_port: int = 8085, amd_enabled: bool = True,
                 amd_probe: Path | None = None):
        self._last_disk = None
        self._last_net = None
        self._last_ts = None
        self._pdh = None
        self._adapters = []
        self._nvml = None
        self._base_mhz: float | None = None
        self.lhm_enabled = lhm_enabled
        self._lhm_port = lhm_port
        self._lhm: LhmPoller | None = LhmPoller(lhm_port) if lhm_enabled else None
        self.amd_enabled = amd_enabled
        self._amd_probe = amd_probe
        self._amd: amd.AdlReader | None = None
        self._errors: dict[str, int] = {}
        self._init_sources()

    # ---------------------------------------------------------------------
    def _init_sources(self) -> None:
        try:
            psutil.cpu_percent(None)
            psutil.cpu_percent(None, percpu=True)
        except Exception:
            pass
        if IS_WINDOWS:
            self._init_windows()
        try:
            from corecontrol.monitoring.gpu import Nvml

            n = Nvml()
            self._nvml = n if n.ok else None
        except Exception as exc:
            log.info("NVML: %s", exc)

    def _init_windows(self) -> None:
        from corecontrol.monitoring import gpu, pdh

        self._adapters = [a for a in gpu.enumerate_adapters() if not a.software]
        try:
            q = pdh.PdhQuery()
            q.add("cpu_perf", r"\Processor Information(_Total)\% Processor Performance")
            q.add("disk_idle", r"\PhysicalDisk(_Total)\% Idle Time")
            if self._adapters:
                q.add("gpu_engine", r"\GPU Engine(*)\Utilization Percentage")
                q.add("gpu_mem", r"\GPU Adapter Memory(*)\Dedicated Usage")
            q.collect()
            self._pdh = q
        except Exception as exc:
            log.info("PDH nicht verfügbar: %s", exc)
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                self._base_mhz = float(winreg.QueryValueEx(k, "~MHz")[0])
        except Exception:
            self._base_mhz = None
        if self.amd_enabled and any(a.vendor == "amd" for a in self._adapters):
            self._amd = amd.open_guarded(self._amd_probe)

    def set_amd(self, enabled: bool) -> None:
        """AMD-Treiberwerte ein-/ausschalten. Einschalten hebt auch den Absturzschutz auf."""
        self.amd_enabled = enabled
        if self._amd is not None and not enabled:
            self._amd.close()
            self._amd = None
        if enabled and self._amd is None and IS_WINDOWS:
            if self._amd_probe is not None:
                try:
                    self._amd_probe.unlink()
                except OSError:
                    pass
            if any(a.vendor == "amd" for a in self._adapters):
                self._amd = amd.open_guarded(self._amd_probe)

    def set_lhm(self, enabled: bool, port: int) -> None:
        self.lhm_enabled = enabled
        if self._lhm is not None and (not enabled or port != self._lhm.port):
            self._lhm.close()
            self._lhm = None
        if enabled and self._lhm is None:
            self._lhm = LhmPoller(port)
        elif self._lhm is not None:
            self._lhm.retry_now()
        self._lhm_port = port

    # ---------------------------------------------------------------------
    def _guard(self, name: str, fn) -> None:
        try:
            fn()
        except Exception as exc:
            n = self._errors.get(name, 0) + 1
            self._errors[name] = n
            if n <= 3:
                log.warning("Messquelle %s fehlgeschlagen: %s", name, exc)

    def sample(self) -> Sample:
        now = time.time()
        s = Sample(ts=now)
        dt = (now - self._last_ts) if self._last_ts else None
        self._last_ts = now

        def cpu():
            s.cpu_percent = float(psutil.cpu_percent(None))
            s.cpu_per_core = [float(x) for x in psutil.cpu_percent(None, percpu=True)]

        def mem():
            vm = psutil.virtual_memory()
            s.ram_total, s.ram_used, s.ram_percent = int(vm.total), int(vm.total - vm.available), float(vm.percent)
            sw = psutil.swap_memory()
            s.swap_total, s.swap_used = int(sw.total), int(sw.used)

        def disk():
            io = psutil.disk_io_counters()
            if io is None:
                return
            if self._last_disk is not None and dt:
                s.disk_read_bps = max(0.0, (io.read_bytes - self._last_disk.read_bytes) / dt)
                s.disk_write_bps = max(0.0, (io.write_bytes - self._last_disk.write_bytes) / dt)
            self._last_disk = io

        def net():
            io = psutil.net_io_counters()
            if io is None:
                return
            if self._last_net is not None and dt:
                s.net_down_bps = max(0.0, (io.bytes_recv - self._last_net.bytes_recv) / dt)
                s.net_up_bps = max(0.0, (io.bytes_sent - self._last_net.bytes_sent) / dt)
            self._last_net = io

        def procs():
            s.process_count = len(psutil.pids())

        self._guard("cpu", cpu)
        self._guard("memory", mem)
        self._guard("disk", disk)
        self._guard("network", net)
        self._guard("processes", procs)
        if self._pdh is not None:
            self._guard("pdh", lambda: self._sample_pdh(s))
        elif not IS_WINDOWS:
            self._guard("cpufreq", lambda: self._cpu_freq_generic(s))
        if self._nvml is not None:
            self._guard("nvml", lambda: self._sample_nvml(s))
        if self._amd is not None:
            self._guard("amd", lambda: self._sample_amd(s))
        if self.lhm_enabled and self._lhm is not None:
            status, sensors = self._lhm.latest()
            s.lhm_status, s.sensors = status, list(sensors)
            self._guard("lhm", lambda: self._apply_lhm(s))
        else:
            s.lhm_status = "off"
        return s

    def _cpu_freq_generic(self, s: Sample) -> None:
        f = psutil.cpu_freq()
        if f and f.current:
            s.cpu_freq_mhz = float(f.current)

    def _sample_pdh(self, s: Sample) -> None:
        from corecontrol.monitoring import pdh

        q = self._pdh
        q.collect()
        perf = q.value("cpu_perf")
        if perf is not None and self._base_mhz:
            s.cpu_freq_mhz = self._base_mhz * perf / 100.0
        idle = q.value("disk_idle")
        if idle is not None:
            s.disk_active_pct = max(0.0, min(100.0, 100.0 - idle))
        if self._adapters:
            util = pdh.gpu_util_by_luid(q.array("gpu_engine")) if q.has("gpu_engine") else {}
            mem_raw = q.array("gpu_mem", pdh.PDH_FMT_LARGE) if q.has("gpu_mem") else {}
            mem: dict[str, float] = {}
            for inst, v in mem_raw.items():
                luid = pdh.parse_adapter_memory_instance(inst)
                if luid:
                    mem[luid] = mem.get(luid, 0.0) + v
            for a in self._adapters:
                s.gpus.append(GpuSample(
                    name=a.name, key=a.luid, vendor=a.vendor,
                    util=util.get(a.luid) if util else None,
                    vram_used=int(mem[a.luid]) if a.luid in mem else None,
                    vram_total=a.dedicated_vram or None,
                    source="pdh",
                ))

    def _sample_nvml(self, s: Sample) -> None:
        n = self._nvml
        for i, name in enumerate(n.names):
            vals = n.read(i)
            target = next((g for g in s.gpus if g.vendor == "nvidia" and _same_gpu(g.name, name)), None)
            if target is None:
                target = GpuSample(name=name, key=f"nvml{i}", vendor="nvidia", source="nvml")
                s.gpus.append(target)
            target.temp = vals.get("temp")
            target.clock_mhz = vals.get("clock")
            target.power_w = vals.get("power")
            target.fan_pct = vals.get("fan")
            if vals.get("util") is not None:
                target.util = vals["util"]
            if vals.get("vram_used") is not None:
                target.vram_used, target.vram_total = vals["vram_used"], vals["vram_total"]
            target.source = "nvml"

    def _sample_amd(self, s: Sample) -> None:
        r = self._amd
        for gpu in r.gpus:
            vals = r.read(gpu)
            if not vals:
                continue
            target = next((g for g in s.gpus if g.vendor == "amd" and amd.same_gpu(g.name, gpu.name)), None)
            if target is None:
                amd_gpus = [g for g in s.gpus if g.vendor == "amd"]
                if len(r.gpus) == 1 and len(amd_gpus) == 1:
                    target = amd_gpus[0]
            if target is None:
                target = GpuSample(name=gpu.name, key=f"adl{gpu.index}", vendor="amd")
                s.gpus.append(target)
            apply_amd_values(target, vals)
            if s.cpu_temp is None and "temp_cpu" in vals:
                s.cpu_temp = vals["temp_cpu"]

    def _apply_lhm(self, s: Sample) -> None:
        if not s.sensors:
            return
        cpu_temp = lhm.pick_cpu_temp(s.sensors)
        if cpu_temp is not None:
            s.cpu_temp = cpu_temp
        s.cpu_power_w = lhm.pick_cpu_power(s.sensors)
        for g in s.gpus:
            if g.temp is None:
                g.temp = lhm.pick_gpu_temp(s.sensors, g.name)
        if not s.gpus:
            t = lhm.pick_gpu_temp(s.sensors)
            if t is not None:
                gpu_hw = next((x.hardware for x in s.sensors if x.hw_kind == "gpu"), "GPU")
                s.gpus.append(GpuSample(name=gpu_hw, key="lhm", temp=t, source="lhm"))

    def close(self) -> None:
        if self._amd is not None:
            self._amd.close()
            self._amd = None
        if self._lhm is not None:
            self._lhm.close()
            self._lhm = None
        if self._pdh:
            self._pdh.close()
        if self._nvml:
            self._nvml.close()


def apply_amd_values(target: GpuSample, vals: dict[str, float]) -> None:
    """Überträgt Werte aus dem AMD-Treiber; fehlende Werte lassen vorhandene (z. B. aus PDH) stehen."""
    def put(attr: str, value: float | None) -> None:
        if value is not None:
            setattr(target, attr, value)

    put("util", vals.get("activity_gfx"))
    put("temp", vals.get("temp_edge"))
    put("hotspot_temp", vals.get("temp_hotspot"))
    put("mem_temp", vals.get("temp_mem"))
    put("power_w", vals.get("board_power", vals.get("asic_power")))
    put("clock_mhz", vals.get("gfx_clock"))
    put("mem_clock_mhz", vals.get("mem_clock"))
    put("fan_rpm", vals.get("fan_rpm"))
    put("fan_pct", vals.get("fan_pct"))
    if "vram_used_mb" in vals:
        target.vram_used = int(vals["vram_used_mb"] * 1024 * 1024)
    if any(k in vals for k in amd.PMLOG):
        target.source = "adl"  # nur, wenn wirklich Sensorwerte aus dem Treiber kamen


def _same_gpu(a: str, b: str) -> bool:
    a, b = a.lower().replace("nvidia", "").strip(), b.lower().replace("nvidia", "").strip()
    return a in b or b in a

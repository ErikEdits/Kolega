"""Sammelt Live-Messwerte. Jede Quelle ist einzeln abgesichert:
fällt eine aus, bleiben ihre Werte „nicht verfügbar“, der Rest läuft weiter."""

from __future__ import annotations

import logging
import time

import psutil

from corecontrol.core.platform import IS_WINDOWS
from corecontrol.monitoring import lhm
from corecontrol.monitoring.models import GpuSample, Sample

log = logging.getLogger(__name__)


class Collector:
    def __init__(self, lhm_enabled: bool = True, lhm_port: int = 8085):
        self._last_disk = None
        self._last_net = None
        self._last_ts = None
        self._pdh = None
        self._adapters = []
        self._nvml = None
        self._base_mhz: float | None = None
        self.lhm_enabled = lhm_enabled
        self._lhm = lhm.LhmReader(lhm_port)
        self._lhm_every = 2  # nur jede 2. Messung, um die Last gering zu halten
        self._tick = 0
        self._last_lhm: tuple[str, list] = ("off", [])
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

    def set_lhm(self, enabled: bool, port: int) -> None:
        self.lhm_enabled = enabled
        if port != self._lhm.port:
            self._lhm = lhm.LhmReader(port)
        if not enabled:
            self._last_lhm = ("off", [])

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
        self._tick += 1

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
        if self.lhm_enabled:
            if self._tick % self._lhm_every == 1 or self._lhm_every == 1:
                self._guard("lhm", lambda: self._sample_lhm())
            s.lhm_status, s.sensors = self._last_lhm[0], list(self._last_lhm[1])
            self._apply_lhm(s)
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

    def _sample_lhm(self) -> None:
        self._last_lhm = self._lhm.read()

    def _apply_lhm(self, s: Sample) -> None:
        if not s.sensors:
            return
        s.cpu_temp = lhm.pick_cpu_temp(s.sensors)
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
        if self._pdh:
            self._pdh.close()
        if self._nvml:
            self._nvml.close()


def _same_gpu(a: str, b: str) -> bool:
    a, b = a.lower().replace("nvidia", "").strip(), b.lower().replace("nvidia", "").strip()
    return a in b or b in a

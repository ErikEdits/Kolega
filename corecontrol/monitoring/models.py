"""Datenstrukturen für Live-Messwerte. None bedeutet immer „nicht verfügbar“."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SensorReading:
    hardware: str          # z. B. "AMD Ryzen 7 5800X"
    hw_kind: str           # cpu, gpu, board, storage, memory, other
    name: str              # z. B. "Core (Tctl/Tdie)"
    kind: str              # temperature, fan, voltage, power, clock, load, control, data, other
    value: float
    unit: str
    identifier: str = ""


@dataclass
class GpuSample:
    name: str
    key: str                       # eindeutige Kennung (LUID oder NVML-Index)
    vendor: str = ""               # nvidia, amd, intel, other
    util: float | None = None      # %
    vram_used: int | None = None   # Bytes
    vram_total: int | None = None  # Bytes
    temp: float | None = None      # °C
    clock_mhz: float | None = None
    power_w: float | None = None
    fan_pct: float | None = None
    source: str = ""               # pdh, nvml, lhm


@dataclass
class Sample:
    ts: float
    cpu_percent: float | None = None
    cpu_per_core: list[float] = field(default_factory=list)
    cpu_freq_mhz: float | None = None
    cpu_temp: float | None = None
    cpu_power_w: float | None = None
    ram_used: int | None = None
    ram_total: int | None = None
    ram_percent: float | None = None
    swap_used: int | None = None
    swap_total: int | None = None
    disk_read_bps: float | None = None
    disk_write_bps: float | None = None
    disk_active_pct: float | None = None
    net_down_bps: float | None = None
    net_up_bps: float | None = None
    process_count: int | None = None
    gpus: list[GpuSample] = field(default_factory=list)
    sensors: list[SensorReading] = field(default_factory=list)
    lhm_status: str = "off"  # off, not_running, ok, error

    @property
    def primary_gpu(self) -> GpuSample | None:
        if not self.gpus:
            return None
        return max(self.gpus, key=lambda g: ((g.vendor in ("nvidia", "amd")), g.vram_total or 0, g.util or 0))

    def sensors_of(self, kind: str) -> list[SensorReading]:
        return [s for s in self.sensors if s.kind == kind]

    @property
    def max_fan_rpm(self) -> float | None:
        fans = [s.value for s in self.sensors if s.kind == "fan" and s.value is not None]
        return max(fans) if fans else None

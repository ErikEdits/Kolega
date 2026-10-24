"""AMD-Treiberwerte (ADL): Auswertung der Sensorliste, Zuordnung, Absturzschutz.

Echte AMD-Hardware gibt es in der automatischen Prüfung nicht; der Treiber wird simuliert.
"""

import ctypes
import sys

import pytest

from corecontrol.monitoring import amd
from corecontrol.monitoring.collector import Collector, apply_amd_values
from corecontrol.monitoring.models import GpuSample


def _sensors(**values):
    s = [(0, 0)] * amd.ADL_PMLOG_MAX_SENSORS
    for key, v in values.items():
        s[amd.PMLOG[key]] = (1, v)
    return s


def test_struct_layout_matches_adl_headers():
    assert ctypes.sizeof(amd._SingleSensorData) == 8
    assert ctypes.sizeof(amd._PMLogDataOutput) == 4 + 256 * 8
    # AdapterInfo (Windows-Variante): 9 int-Felder + 6 Zeichenketten zu je 256 Byte
    assert ctypes.sizeof(amd._AdapterInfo) == 9 * 4 + 6 * 256


def test_parse_pmlog_values_like_adrenalin():
    vals = amd.parse_pmlog(_sensors(activity_gfx=6, board_power=47, temp_edge=51, gfx_clock=2505, temp_mem=52,
                                    temp_hotspot=63, fan_rpm=0, mem_clock=1259))
    assert vals == {"activity_gfx": 6.0, "board_power": 47.0, "temp_edge": 51.0, "gfx_clock": 2505.0, "temp_mem": 52.0,
                    "temp_hotspot": 63.0, "fan_rpm": 0.0, "mem_clock": 1259.0}


def test_parse_pmlog_ignores_unsupported_and_implausible():
    s = _sensors(temp_edge=255, activity_gfx=140, board_power=0, gfx_clock=1800)
    s[amd.PMLOG["temp_hotspot"]] = (0, 70)  # nicht unterstützt
    assert amd.parse_pmlog(s) == {"gfx_clock": 1800.0}
    assert amd.parse_pmlog([]) == {}


def test_pick_adapters_one_entry_per_card():
    infos = [
        {"index": 0, "name": "AMD Radeon RX 9070 XT", "vendor": 1002, "bus": 3, "device": 0, "function": 0, "present": 1},
        {"index": 1, "name": "AMD Radeon RX 9070 XT", "vendor": 1002, "bus": 3, "device": 0, "function": 0, "present": 1},
        {"index": 2, "name": "NVIDIA", "vendor": 4318, "bus": 5, "device": 0, "function": 0, "present": 1},
        {"index": 3, "name": "AMD Radeon(TM) Graphics", "vendor": 1002, "bus": 9, "device": 0, "function": 0, "present": 0},
    ]
    assert [a["index"] for a in amd.pick_adapters(infos)] == [0]


def test_gpu_name_matching():
    assert amd.same_gpu("AMD Radeon RX 9070 XT", "AMD Radeon RX 9070 XT")
    assert amd.same_gpu("Radeon RX 9070 XT", "AMD Radeon RX 9070 XT")
    assert not amd.same_gpu("AMD Radeon RX 9070 XT", "AMD Radeon RX 7600")
    assert not amd.same_gpu("", "AMD Radeon RX 7600")


def test_apply_values_prefers_board_power_and_keeps_missing():
    g = GpuSample(name="AMD Radeon RX 9070 XT", key="luid", vendor="amd", util=12.0, vram_total=16 * 1024**3, source="pdh")
    apply_amd_values(g, {"asic_power": 30.0, "board_power": 47.0, "temp_edge": 51.0, "vram_used_mb": 1590.0, "fan_rpm": 0.0})
    assert g.power_w == 47.0 and g.temp == 51.0 and g.fan_rpm == 0.0
    assert g.vram_used == 1590 * 1024 * 1024
    assert g.util == 12.0  # Auslastung fehlte im Treiber → Wert aus PDH bleibt
    assert g.source == "adl"
    g2 = GpuSample(name="x", key="k", vendor="amd")
    apply_amd_values(g2, {"asic_power": 30.0})
    assert g2.power_w == 30.0
    g3 = GpuSample(name="x", key="k", vendor="amd", source="pdh")
    apply_amd_values(g3, {"vram_used_mb": 100.0})  # nur Speicher, keine Sensoren
    assert g3.source == "pdh" and g3.vram_used == 100 * 1024 * 1024


class _FakeReader:
    def __init__(self, vals):
        self.gpus = [amd.AmdGpu("AMD Radeon RX 9070 XT", 0, 3, 8)]
        self.vals = vals
        self.closed = False

    def read(self, gpu):
        return dict(self.vals)

    def close(self):
        self.closed = True


def test_collector_uses_driver_values():
    c = Collector(lhm_enabled=False, amd_enabled=False)
    try:
        c._amd = _FakeReader({"activity_gfx": 9.0, "temp_edge": 51.0, "temp_hotspot": 60.0, "board_power": 47.0,
                              "temp_cpu": 52.0})
        s = c.sample()
        g = next(g for g in s.gpus if g.source == "adl")
        assert (g.util, g.temp, g.hotspot_temp, g.power_w) == (9.0, 51.0, 60.0, 47.0)
        assert s.primary_gpu is g or len(s.gpus) > 1
        assert s.cpu_temp == 52.0  # nur, wenn der Treiber sie meldet
        reader = c._amd
        c.set_amd(False)
        assert reader.closed and c._amd is None
    finally:
        c.close()


def test_guard_skips_after_unfinished_attempt(tmp_path, caplog):
    probe = tmp_path / "amd_adl.probe"
    probe.write_text("x", encoding="utf-8")
    assert amd.open_guarded(probe) is None
    assert probe.exists()  # bleibt bis zum bewussten Wiedereinschalten
    assert "nicht abgeschlossen" in caplog.text


@pytest.mark.skipif(sys.platform == "win32", reason="prüft das Verhalten ohne AMD-Treiber")
def test_guard_without_driver_cleans_up(tmp_path):
    probe = tmp_path / "amd_adl.probe"
    assert amd.open_guarded(probe) is None
    assert not probe.exists()

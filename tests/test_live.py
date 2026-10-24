"""Live-Messung: kein Warten auf LibreHardwareMonitor, zeitbasierte Diagramme, saubere Zeitachse."""

import threading
import time

import pytest

from corecontrol.monitoring.collector import Collector, LhmPoller
from corecontrol.ui.widgets.charts import GAP_S, time_ticks


class _SlowReader:
    """Simuliert LibreHardwareMonitor, das nicht läuft: jeder Versuch dauert lange."""

    def __init__(self, delay=0.8, result=("not_running", [])):
        self.delay, self.result = delay, result
        self.calls = 0
        self.done = threading.Event()

    def read(self):
        self.calls += 1
        time.sleep(self.delay)
        self.done.set()
        return self.result


def test_lhm_poller_never_blocks_and_backs_off():
    reader = _SlowReader()
    poller = LhmPoller(8085, reader=reader)
    try:
        t0 = time.perf_counter()
        for _ in range(20):
            assert poller.latest() == ("not_running", [])
        assert time.perf_counter() - t0 < 0.1  # 20 Abfragen, kein Warten
        assert reader.done.wait(3)
        time.sleep(0.05)
        for _ in range(20):
            poller.latest()
        time.sleep(0.2)
        assert reader.calls == 1  # läuft nicht → erst nach 10 s erneut versuchen
    finally:
        poller.close()


def test_lhm_poller_delivers_result_and_retry_now():
    reader = _SlowReader(delay=0.0, result=("ok", ["sensor"]))
    poller = LhmPoller(8085, reader=reader)
    try:
        poller.latest()
        assert reader.done.wait(2)
        end = time.time() + 2
        while poller.latest()[0] != "ok" and time.time() < end:
            time.sleep(0.01)
        assert poller.latest() == ("ok", ["sensor"])
    finally:
        poller.close()


def test_collector_sample_is_fast_even_if_lhm_hangs(monkeypatch):
    from corecontrol.monitoring import lhm

    monkeypatch.setattr(lhm.LhmReader, "read", lambda self: (time.sleep(1.0), ("not_running", []))[1])
    c = Collector(lhm_enabled=True)
    try:
        c.sample()
        t0 = time.perf_counter()
        for _ in range(5):
            s = c.sample()
        assert (time.perf_counter() - t0) / 5 < 0.25
        assert s.lhm_status == "not_running" and s.cpu_percent is not None
    finally:
        t0 = time.perf_counter()
        c.close()
        assert time.perf_counter() - t0 < 2.0


@pytest.mark.parametrize("width", [180, 260, 420, 640, 900, 1400])
@pytest.mark.parametrize("window", [60, 120, 600])
def test_time_ticks_never_overlap(width, window):
    label = 70
    ticks = time_ticks(1_792_700_000.37, window, width, label + 18)
    xs = [frac * width for _, frac in ticks]
    assert all(b - a >= label + 18 - 1e-6 for a, b in zip(xs, xs[1:]))
    assert all(0 <= f <= 1 for _, f in ticks)
    # runde Zeitpunkte (z. B. :00, :10, :20 Sekunden)
    if len(ticks) >= 2:
        step = ticks[1][0] - ticks[0][0]
        assert all(abs(t / step - round(t / step)) < 1e-6 for t, _ in ticks)


@pytest.mark.gui
def test_line_chart_is_time_based(qapp):
    from corecontrol.ui.widgets.charts import LineChart, Sparkline

    c = LineChart(120, time_axis=True)
    c.add_series("A", "accent")
    c.add_series("B", "ok")
    t = 1_000_000.0
    for i in range(1000):  # 250 s bei 0,25 s Takt
        c.push(i % 100, None, ts=t + i * 0.25, animate=False)
    assert c.times[-1] - c.times[1] <= 120 and c.times[-1] - c.times[0] >= 120
    assert len(c.times) == len(c.series[0].values) == len(c.series[1].values)
    # Fehlende Werte für eine Reihe werden mit „nicht verfügbar“ aufgefüllt
    c.push(5, ts=t + 300, animate=False)
    assert c.series[1].values[-1] is None
    # Rückwärts laufende Uhr leert das Diagramm statt Linien zu verdrehen
    c.push(1, 1, ts=t, animate=False)
    assert len(c.times) == 1
    c.resize(600, 200)
    c.grab()  # zeichnen ohne Fehler

    sp = Sparkline("accent", 60)
    for i in range(400):
        sp.push(float(i % 10), False, ts=t + i * 0.5)
    assert sp.times[-1] - sp.times[1] <= 60
    sp.resize(200, 50)
    sp.grab()
    assert GAP_S > 5  # Hintergrundtakt (5 s) wird noch als Linie verbunden

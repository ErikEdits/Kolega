"""Netzwerkdiagnose: Verbindungstest, Adapter, WLAN und lokale Aktivität."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from corecontrol.core import fmt
from corecontrol.core.platform import IS_WINDOWS, open_url
from corecontrol.diagnostics.rules import DiagInput, LiveSummary, rule_network
from corecontrol.i18n import tr
from corecontrol.network.tests import list_adapters, run_network_test, wifi_info
from corecontrol.ui.bus import on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.charts import LineChart
from corecontrol.ui.widgets.common import Card, KeyValueGrid, button, label
from corecontrol.ui.widgets.finding import FindingCard
from corecontrol.ui.workers import run_task

STEP_KEYS = ("adapters", "gateway", "internet", "dns", "http")


class NetworkPage(Page):
    page_id = "network"
    title_key = "net.title"
    subtitle_key = "net.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        if IS_WINDOWS:
            self.header.add_action(button("action.network_settings", None, "settings", lambda: open_url("ms-settings:network")))
        self.test_btn = button("net.run", "primary", "play", self.run_test)
        self.header.add_action(self.test_btn)

        self.test_card = Card("net.test", "stethoscope")
        self.test_card.add(label("net.test_desc", "muted", wrap=True))
        self.bar = QProgressBar()
        self.bar.setRange(0, len(STEP_KEYS))
        self.bar.setVisible(False)
        self.test_card.add(self.bar)
        self.step = label(None, "faint", text="")
        self.test_card.add(self.step)
        self.results = KeyValueGrid()
        self.test_card.add(self.results)
        self.findings_host = QWidget()
        self.findings = QVBoxLayout(self.findings_host)
        self.findings.setContentsMargins(0, 0, 0, 0)
        self.findings.setSpacing(8)
        self.test_card.add(self.findings_host)
        self.body.addWidget(self.test_card)

        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)
        self.act_card = Card("net.activity", "activity")
        self.chart = LineChart(120, None, "", lambda v: fmt.rate_bits(v))
        self.chart.add_series(tr("mon.down"), "info")
        self.chart.add_series(tr("mon.up"), "ok")
        self.act_card.add(self.chart)
        self.act_card.add(label("net.activity_hint", "faint", wrap=True))
        self.wifi_card = Card("net.wifi", "wifi")
        self.wifi_kv = KeyValueGrid()
        self.wifi_card.add(self.wifi_kv)
        self.wifi_note = label(None, "faint", text="", wrap=True)
        self.wifi_card.add(self.wifi_note)
        self.wifi_card.align_top()
        grid.addWidget(self.act_card, 0, 0)
        grid.addWidget(self.wifi_card, 0, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        self.body.addWidget(host)

        self.ad_card = Card("net.adapters", "network")
        self.ad_box = QWidget()
        self.ad_grid = QGridLayout(self.ad_box)
        self.ad_grid.setContentsMargins(0, 0, 0, 0)
        self.ad_grid.setHorizontalSpacing(24)
        self.ad_grid.setVerticalSpacing(14)
        self.ad_card.add(self.ad_box)
        self.body.addWidget(self.ad_card)
        self.body.addWidget(label("net.speedtest_note", "faint", wrap=True))
        self.finish()
        self.result = None
        self.adapters = []
        self.wifi = None
        on_refresh(self, self._render_all)

    def on_show(self):
        if self.ctx.sampler:
            self.chart.clear()
            for s in self.ctx.sampler.store.window(120):
                self.chart.push(s.net_down_bps, s.net_up_bps)
        if self.result is None and self.ctx.diagnosis_result is not None and self.ctx.diagnosis_result.network is not None:
            self.result = self.ctx.diagnosis_result.network
            self.adapters = self.result.adapters
            self.wifi = self.result.wifi
            self._render_all()
        elif not self.adapters:
            def done(res):
                self.adapters, self.wifi = res
                self._render_all()

            run_task(lambda: (list_adapters(), wifi_info()), on_done=done, context="network")

    def on_sample(self, s):
        self.chart.push(s.net_down_bps, s.net_up_bps)

    def run_test(self):
        self.test_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        st = self.ctx.settings

        def progress(step):
            if step in STEP_KEYS:
                self.bar.setValue(STEP_KEYS.index(step))
                self.step.setText(tr(f"net.step.{step}"))

        def job(ctx):
            return run_network_test(st.get("network.ping_targets"), st.get("network.dns_domains"), ping_count=10,
                                    ctx=ctx, progress=ctx.progress)

        def done(res):
            self.test_btn.setEnabled(True)
            self.bar.setVisible(False)
            self.step.setText(tr("net.done", when=fmt.datetime_(res.started)))
            self.result = res
            self.adapters = res.adapters
            self.wifi = res.wifi
            self._render_all()

        def failed(exc):
            self.test_btn.setEnabled(True)
            self.bar.setVisible(False)
            self.step.setText(tr("common.action_failed", error=str(exc)))

        run_task(job, on_done=done, on_error=failed, on_progress=progress, context="network_test")

    def _render_all(self):
        self._render_result()
        self._render_wifi()
        self._render_adapters()

    def _render_result(self):
        while self.findings.count():
            w = self.findings.takeAt(0).widget()
            if w:
                w.deleteLater()
        r = self.result
        if r is None:
            self.results.set_rows([])
            return
        from corecontrol.reports.report import _ping_text

        rows = [(tr("net.gateway"), r.gateway or tr("common.na"))]
        if r.gateway_ping is not None:
            rows.append((tr("net.gateway_ping"), _ping_text(r.gateway_ping)))
        for p in r.internet_pings:
            rows.append((f"Ping {p.host}", _ping_text(p)))
        for d in r.dns:
            rows.append((f"DNS {d.domain}", fmt.ms(d.ms) if d.ok else tr("net.failed", error=d.error)))
        if r.http is not None:
            rows.append((tr("net.http"), tr("net.http_ok") if r.http.ok else
                         (tr("net.http_captive") if r.http.captive_portal else tr("net.failed", error=r.http.error))))
        self.results.set_rows(rows)
        d = DiagInput(settings=self.ctx.settings.all(), live=LiveSummary(), net=r)
        for f in rule_network(d):
            self.findings.addWidget(FindingCard(f, expanded=f.severity in ("critical", "warning")))

    def _render_wifi(self):
        w = self.wifi
        if w is None or not w.available:
            self.wifi_kv.set_rows([])
            if w is not None and w.location_denied:
                self.wifi_note.setText(tr("net.wifi_location"))
            elif not IS_WINDOWS:
                self.wifi_note.setText(tr("common.only_windows"))
            else:
                self.wifi_note.setText(tr("net.wifi_none"))
            return
        self.wifi_note.setText("")
        self.wifi_kv.set_rows([
            ("SSID", w.ssid or tr("common.na")),
            (tr("net.signal"), fmt.pct(w.signal_pct)),
            (tr("net.rx"), f"{fmt.number(w.rx_mbps, 0)} Mbit/s" if w.rx_mbps else tr("common.na")),
            (tr("net.tx"), f"{fmt.number(w.tx_mbps, 0)} Mbit/s" if w.tx_mbps else tr("common.na")),
            (tr("net.channel"), w.channel or tr("common.na")),
            (tr("net.standard"), " ".join(x for x in (w.radio, w.band) if x) or tr("common.na")),
        ])

    def _render_adapters(self):
        while self.ad_grid.count():
            it = self.ad_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        shown = [a for a in self.adapters if a.kind != "loopback"]
        if not shown:
            self.ad_grid.addWidget(label("common.na", "muted"), 0, 0)
            return
        for i, a in enumerate(shown[:8]):
            box = QVBoxLayout()
            title = label(None, "h3", text=f"{a.name}")
            sub = label(None, "faint", text=f"{tr('net.kind.' + a.kind)} · {tr('net.up') if a.up else tr('net.down')}")
            kv = KeyValueGrid()
            kv.set_rows([
                (tr("net.speed"), f"{a.speed_mbps} Mbit/s" if a.speed_mbps else tr("common.na")),
                ("IPv4", ", ".join(a.ipv4) or "–"),
                (tr("net.gateway"), ", ".join(a.gateway) or "–"),
                ("DNS", ", ".join(a.dns) or "–"),
                ("DHCP", (tr("common.yes") if a.dhcp else tr("common.no")) if a.dhcp is not None else "–"),
                ("MAC", a.mac or "–"),
            ])
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(4)
            wl.addWidget(title)
            wl.addWidget(sub)
            wl.addWidget(kv)
            wl.addStretch(1)
            self.ad_grid.addWidget(w, i // 2, i % 2, Qt.AlignmentFlag.AlignTop)

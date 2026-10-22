"""Hardware- und Treiberinformationen."""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QHeaderView, QLineEdit, QTableView, QWidget

from corecontrol.core import fmt
from corecontrol.core.platform import IS_WINDOWS, is_admin, open_url, relaunch_as_admin
from corecontrol.diagnostics.rules import VENDOR_DRIVER_URLS
from corecontrol.i18n import tr
from corecontrol.monitoring.hardware import age_days, collect_drivers
from corecontrol.system.tools import run_tool
from corecontrol.ui.bus import on_refresh
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.common import Card, Chip, KeyValueGrid, button, label
from corecontrol.ui.workers import run_task


class HardwarePage(Page):
    page_id = "hardware"
    title_key = "hw.title"
    subtitle_key = "hw.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.header.add_action(button("common.refresh", None, "refresh-cw", lambda: self.ctx.load_hardware(force=True)))
        if IS_WINDOWS:
            self.header.add_action(button("hw.device_manager", None, "cpu", lambda: run_tool("devmgmt")))
        self.loading = label("common.loading", "muted")
        self.body.addWidget(self.loading)

        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(16)
        self.cards: dict[str, tuple[Card, KeyValueGrid]] = {}
        for i, (key, icon) in enumerate((("system", "monitor"), ("cpu", "cpu"), ("board", "server"), ("memory", "memory-stick"))):
            card = Card(f"hw.{key}", icon)
            kv = KeyValueGrid()
            card.add(kv)
            card.align_top()
            self.cards[key] = (card, kv)
            self.grid.addWidget(card, i // 2, i % 2)
        self.body.addWidget(host)

        self.gpu_card = Card("hw.gpus", "monitor")
        self.gpu_box = QWidget()
        self.gpu_lay = QGridLayout(self.gpu_box)
        self.gpu_lay.setContentsMargins(0, 0, 0, 0)
        self.gpu_card.add(self.gpu_box)
        self.body.addWidget(self.gpu_card)

        self.disk_card = Card("hw.disks", "hard-drive")
        self.disk_box = QWidget()
        self.disk_lay = QGridLayout(self.disk_box)
        self.disk_lay.setContentsMargins(0, 0, 0, 0)
        self.disk_lay.setHorizontalSpacing(18)
        self.disk_lay.setVerticalSpacing(10)
        self.disk_card.add(self.disk_box)
        self.smart_hint = label(None, "faint", text="", wrap=True)
        self.disk_card.add(self.smart_hint)
        self.admin_btn = button("common.restart_admin", None, "shield-check", relaunch_as_admin)
        self.admin_btn.setVisible(False)
        row = QHBoxLayout()
        row.addWidget(self.admin_btn)
        row.addStretch(1)
        self.disk_card.add_layout(row)
        self.body.addWidget(self.disk_card)

        self.dev_card = Card("hw.problem_devices", "triangle-alert")
        self.dev_text = label(None, "muted", text="", wrap=True)
        self.dev_card.add(self.dev_text)
        self.body.addWidget(self.dev_card)

        # Treiberliste (auf Anfrage, da die Abfrage einige Sekunden dauert)
        self.drv_card = Card("hw.drivers", "package")
        self.drv_card.add(label("hw.drivers_desc", "faint", wrap=True))
        r = QHBoxLayout()
        self.drv_btn = button("hw.drivers_load", None, "download", self._load_drivers)
        r.addWidget(self.drv_btn)
        self.drv_search = QLineEdit()
        self.drv_search.setPlaceholderText(tr("common.search"))
        self.drv_search.setVisible(False)
        r.addWidget(self.drv_search, 1)
        self.drv_card.add_layout(r)
        self.drv_model = QStandardItemModel(0, 5)
        self.drv_proxy = QSortFilterProxyModel()
        self.drv_proxy.setSourceModel(self.drv_model)
        self.drv_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.drv_proxy.setFilterKeyColumn(-1)
        self.drv_search.textChanged.connect(self.drv_proxy.setFilterFixedString)
        self.drv_table = QTableView()
        self.drv_table.setModel(self.drv_proxy)
        self.drv_table.setSortingEnabled(True)
        self.drv_table.verticalHeader().setVisible(False)
        self.drv_table.setAlternatingRowColors(True)
        self.drv_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.drv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.drv_table.setMinimumHeight(380)
        self.drv_table.setVisible(False)
        self.drv_card.add(self.drv_table)
        self.body.addWidget(self.drv_card)
        self.body.addWidget(label("hw.driver_policy", "faint", wrap=True))
        self.finish()
        ctx.hardware_ready.connect(self.render)
        on_refresh(self, lambda: self.render(self.ctx.hardware))

    def on_show(self):
        self.ctx.load_hardware()

    def render(self, hw):
        self.loading.setVisible(hw is None)
        if hw is None:
            return
        os_ = hw.get("os") or {}
        cpu = hw.get("cpu") or {}
        board = hw.get("board") or {}
        mem = hw.get("memory") or {}
        na = tr("common.na")
        win = f"{os_.get('name', na)} {os_.get('display_version') or ''}".strip()
        build = f"{os_.get('build')}.{os_.get('ubr')}" if os_.get("ubr") else str(os_.get("build") or na)
        self.cards["system"][1].set_rows([
            (tr("hw.os"), win),
            (tr("hw.build"), build),
            (tr("hw.edition"), os_.get("edition") or na),
            (tr("hw.arch"), os_.get("arch") or na),
            (tr("hw.installed"), fmt.date_(os_.get("install_date")) if os_.get("install_date") else na),
            (tr("hw.uptime"), fmt.duration(os_.get("uptime_s"))),
            (tr("hw.computer"), os_.get("computer_name") or na),
            (tr("hw.admin"), tr("common.yes") if hw.get("admin") else tr("common.no")),
        ])
        self.cards["cpu"][1].set_rows([
            (tr("common.name"), cpu.get("name") or na),
            (tr("hw.cores"), f"{cpu.get('cores') or '?'} {tr('hw.cores_unit')} / {cpu.get('threads') or '?'} {tr('hw.threads_unit')}"),
            (tr("hw.base_clock"), fmt.mhz(cpu.get("base_mhz"))),
            (tr("hw.max_clock"), fmt.mhz(cpu.get("max_mhz"))),
            (tr("hw.socket"), cpu.get("socket") or na),
        ])
        self.cards["board"][1].set_rows([
            (tr("hw.system_maker"), " ".join(x for x in (board.get("system_manufacturer"), board.get("system_model")) if x) or na),
            (tr("hw.board"), " ".join(x for x in (board.get("manufacturer"), board.get("product")) if x) or na),
            (tr("hw.bios"), " ".join(x for x in (board.get("bios_vendor"), board.get("bios_version")) if x) or na),
            (tr("hw.bios_date"), fmt.date_(board.get("bios_date")) if board.get("bios_date") else na),
        ])
        rows = [(tr("hw.ram_total"), fmt.bytes_(mem.get("total")))]
        mods = mem.get("modules") or []
        if mem.get("slots"):
            rows.append((tr("hw.ram_slots"), tr("hw.ram_slots_val", used=len(mods), total=mem["slots"])))
        for m in mods:
            speed = m.get("configured_speed") or m.get("speed")
            desc = " ".join(str(x) for x in (fmt.bytes_(m.get("capacity")), m.get("type"), f"{speed} MT/s" if speed else "",
                                              m.get("manufacturer"), m.get("part")) if x)
            rows.append((m.get("slot") or "RAM", desc))
        self.cards["memory"][1].set_rows(rows)

        self._render_gpus(hw.get("gpus"))
        self._render_disks(hw)
        devs = hw.get("problem_devices")
        if devs is None:
            self.dev_text.setText(tr("common.na") if not IS_WINDOWS else tr("hw.devices_failed"))
        elif not devs:
            self.dev_text.setText(tr("hw.devices_none"))
        else:
            self.dev_text.setText("\n".join(
                f"• {d['name']} – {tr('hw.code')} {d['code']}: {tr('cm.' + d.get('reason', 'other'))}" for d in devs))
        errs = hw.get("errors") or {}
        if errs:
            self.dev_card.setToolTip("\n".join(f"{k}: {v}" for k, v in errs.items()))

    def _clear(self, lay):
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _render_gpus(self, gpus):
        self._clear(self.gpu_lay)
        if not gpus:
            self.gpu_lay.addWidget(label("hw.gpus_none", "muted", wrap=True), 0, 0)
            return
        for i, g in enumerate(gpus):
            kv = KeyValueGrid()
            age = age_days(g.get("driver_date"))
            kv.set_rows([
                (tr("common.name"), g.get("name") or tr("common.na")),
                (tr("hw.vram"), fmt.bytes_(g.get("vram")) if g.get("vram") else tr("common.na")),
                (tr("hw.driver"), g.get("driver_version") or tr("common.na")),
                (tr("hw.driver_date"), (fmt.date_(g["driver_date"]) + (f" ({tr('hw.days_old', n=age)})" if age is not None else ""))
                 if g.get("driver_date") else tr("common.na")),
                (tr("hw.resolution"), g.get("resolution") or tr("common.na")),
            ])
            self.gpu_lay.addWidget(kv, i, 0)
            url = VENDOR_DRIVER_URLS.get(g.get("vendor", ""))
            if url:
                b = button("hw.driver_page", "ghost", "external-link", lambda u=url: open_url(u))
                self.gpu_lay.addWidget(b, i, 1, Qt.AlignmentFlag.AlignTop)
        self.gpu_lay.setColumnStretch(0, 1)

    def _render_disks(self, hw):
        self._clear(self.disk_lay)
        disks = hw.get("disks") or []
        vols = hw.get("volumes") or []
        r = 0
        for col, key in enumerate(("common.name", "hw.media", "hw.bus", "common.size", "hw.health", "hw.wear_temp")):
            self.disk_lay.addWidget(label(key, "caption"), r, col)
        for d in disks:
            r += 1
            health = d.get("health", "unknown")
            lvl = {"healthy": "ok", "warning": "warning", "unhealthy": "critical"}.get(health, "neutral")
            rel = d.get("reliability") or {}
            extra = []
            if rel.get("wear") is not None:
                extra.append(tr("hw.wear", pct=fmt.pct(rel["wear"])))
            if rel.get("temperature"):
                extra.append(fmt.temp(rel["temperature"]))
            if rel.get("power_on_hours"):
                extra.append(tr("hw.hours", n=fmt.number(rel["power_on_hours"])))
            self.disk_lay.addWidget(label(None, None, text=d.get("model") or "?"), r, 0)
            self.disk_lay.addWidget(label(None, "muted", text=d.get("media") or "–"), r, 1)
            self.disk_lay.addWidget(label(None, "muted", text=d.get("bus") or "–"), r, 2)
            self.disk_lay.addWidget(label(None, "muted", text=fmt.bytes_(d.get("size")) if d.get("size") else "–"), r, 3)
            self.disk_lay.addWidget(Chip(tr(f"hw.health.{health}"), lvl), r, 4, Qt.AlignmentFlag.AlignLeft)
            self.disk_lay.addWidget(label(None, "muted", text=" · ".join(extra) or "–"), r, 5)
        self.disk_lay.setColumnStretch(0, 1)
        r += 1
        if vols:
            self.disk_lay.addWidget(label("hw.volumes", "caption"), r, 0)
            for v in vols:
                r += 1
                name = f"{v['mount']} {v.get('label') or ''}".strip()
                self.disk_lay.addWidget(label(None, None, text=name), r, 0)
                self.disk_lay.addWidget(label(None, "muted", text=v.get("fs") or ""), r, 1)
                self.disk_lay.addWidget(label(None, "muted", text=tr("dash.free_of", free=fmt.bytes_(v["free"]), total=fmt.bytes_(v["total"]))), r, 2, 1, 3)
        needs_admin = any(d.get("reliability_needs_admin") for d in disks)
        self.smart_hint.setText(tr("hw.smart_admin") if needs_admin and IS_WINDOWS else "")
        self.smart_hint.setVisible(bool(needs_admin and IS_WINDOWS))
        self.admin_btn.setVisible(bool(needs_admin and IS_WINDOWS and not is_admin()))

    def _load_drivers(self):
        if not IS_WINDOWS:
            self.drv_btn.setText(tr("common.only_windows"))
            self.drv_btn.setEnabled(False)
            return
        self.drv_btn.setEnabled(False)
        self.drv_btn.setText(tr("common.loading"))

        def done(rows):
            self.drv_btn.setVisible(False)
            self.drv_search.setVisible(True)
            self.drv_table.setVisible(True)
            self.drv_model.clear()
            self.drv_model.setHorizontalHeaderLabels([tr("hw.col.device"), tr("hw.col.class"), tr("hw.col.version"),
                                                      tr("hw.col.date"), tr("hw.col.provider")])
            for d in rows:
                date_item = QStandardItem(fmt.date_(d["date"]) if d["date"] else "")
                date_item.setData(d["date"].timestamp() if d["date"] else 0, Qt.ItemDataRole.UserRole)
                self.drv_model.appendRow([QStandardItem(d["device"]), QStandardItem(d["class"]), QStandardItem(d["version"]),
                                          date_item, QStandardItem(d["provider"])])
            self.drv_proxy.setSortRole(Qt.ItemDataRole.DisplayRole)

        def failed(exc):
            self.drv_btn.setEnabled(True)
            self.drv_btn.setText(tr("hw.drivers_load"))

        run_task(collect_drivers, on_done=done, on_error=failed, context="drivers")

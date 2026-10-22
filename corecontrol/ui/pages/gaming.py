"""Gaming: Monitoring beim Spielen, Mini-Monitor, Spiele-Starter und ehrliche Hinweise."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox, QSlider, QVBoxLayout, QWidget

from corecontrol.core import fmt
from corecontrol.gaming import library
from corecontrol.gaming.checks import run_checks
from corecontrol.i18n import tr
from corecontrol.system.tools import run_action
from corecontrol.ui.bus import on_refresh
from corecontrol.ui.dialogs import ConfirmDialog
from corecontrol.ui.mini_monitor import is_open, toggle_mini_monitor
from corecontrol.ui import msg
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.common import Card, Chip, SettingRow, Toggle, button, icon_label, label
from corecontrol.ui.widgets.table import DataTable
from corecontrol.ui.workers import run_task


class GamingPage(Page):
    page_id = "gaming"
    title_key = "game.title"
    subtitle_key = "game.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.mini_btn = button("game.mini_open", "primary", "maximize-2", self._toggle_mini)
        self.header.add_action(self.mini_btn)

        # Live-Werte
        live = Card("game.live", "gauge")
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        self.vals = {}
        for i, key in enumerate(("cpu", "cpu_temp", "gpu", "gpu_temp", "ram", "vram", "gpu_power", "fan")):
            box = QVBoxLayout()
            box.setSpacing(0)
            cap = label(f"game.v.{key}", "caption")
            val = label(None, "midValue", text="–")
            box.addWidget(cap)
            box.addWidget(val)
            self.vals[key] = val
            grid.addLayout(box, i // 4, i % 4)
        live.add(grid_host)
        live.add(label("game.fps_note", "faint", wrap=True))
        self.body.addWidget(live)

        # Mini-Monitor-Einstellungen
        mini = Card("game.mini", "maximize-2")
        mini.add(label("game.mini_desc", "muted", wrap=True))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(30, 100)
        self.opacity.setValue(int(ctx.settings.get("gaming.mini_opacity") * 100))
        self.opacity.setFixedWidth(200)
        self.opacity.valueChanged.connect(lambda v: ctx.settings.set("gaming.mini_opacity", v / 100))
        mini.add(SettingRow("game.opacity", None, self.opacity))
        t = Toggle(ctx.settings.get("gaming.mini_on_top"))
        t.toggled.connect(lambda v: ctx.settings.set("gaming.mini_on_top", bool(v)))
        mini.add(SettingRow("game.on_top", "game.on_top_desc", t))
        self.body.addWidget(mini)

        # Spiele
        games = Card("game.library", "gamepad-2")
        games.add(label("game.library_desc", "muted", wrap=True))
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("game.search"))
        self.search.textChanged.connect(lambda txt: self.table.set_filter(txt))
        top.addWidget(self.search, 1)
        top.addWidget(button("game.detect", None, "folder-search", self._detect))
        top.addWidget(button("game.add", None, "plus", self._add))
        games.add_layout(top)
        self.table = DataTable([], stretch_col=0, min_height=260)
        self.table.doubleClicked.connect(lambda *_: self._launch())
        games.add(self.table)
        row = QHBoxLayout()
        row.addWidget(button("game.launch", "primary", "play", self._launch))
        row.addWidget(button("game.remove", None, "minus", self._remove))
        row.addStretch(1)
        self.games_status = label(None, "faint", text="")
        row.addWidget(self.games_status)
        games.add_layout(row)
        self.body.addWidget(games)

        # Hinweise
        self.checks_card = Card("game.checks", "list-checks")
        self.checks_card.add(label("game.checks_desc", "muted", wrap=True))
        self.checks_host = QWidget()
        self.checks_lay = QVBoxLayout(self.checks_host)
        self.checks_lay.setContentsMargins(0, 0, 0, 0)
        self.checks_lay.setSpacing(8)
        self.checks_card.add(self.checks_host)
        r2 = QHBoxLayout()
        r2.addWidget(button("game.run_checks", None, "refresh-cw", self._run_checks))
        r2.addStretch(1)
        self.checks_card.add_layout(r2)
        self.body.addWidget(self.checks_card)
        self.finish()
        self.checks = []
        on_refresh(self, self._retranslate)
        self._retranslate()

    def _retranslate(self):
        self.table.set_headers([tr("common.name"), tr("game.col.source"), tr("game.col.target")])
        self._render_games()
        self._render_checks()
        self._update_mini_btn()

    # ---- Live --------------------------------------------------------------
    def on_show(self):
        s = self.ctx.sampler.store.latest() if self.ctx.sampler else None
        if s:
            self.on_sample(s)
        self._update_mini_btn()
        if not self.checks:
            self._run_checks()

    def on_sample(self, s):
        g = s.primary_gpu
        v = self.vals
        v["cpu"].setText(fmt.pct(s.cpu_percent))
        v["cpu_temp"].setText(fmt.temp(s.cpu_temp))
        v["gpu"].setText(fmt.pct(g.util) if g else tr("common.na"))
        v["gpu_temp"].setText(fmt.temp(g.temp) if g else tr("common.na"))
        v["ram"].setText(f"{fmt.pct(s.ram_percent)}")
        v["vram"].setText(fmt.bytes_(g.vram_used) if g and g.vram_used is not None else tr("common.na"))
        v["gpu_power"].setText(f"{fmt.number(g.power_w, 0)} W" if g and g.power_w is not None else tr("common.na"))
        rpm = s.max_fan_rpm
        v["fan"].setText(f"{fmt.number(rpm)} RPM" if rpm else (fmt.pct(g.fan_pct) if g and g.fan_pct is not None else tr("common.na")))

    def _toggle_mini(self):
        toggle_mini_monitor(self.ctx)
        self._update_mini_btn()

    def _update_mini_btn(self):
        self.mini_btn.setText(tr("game.mini_close") if is_open() else tr("game.mini_open"))

    # ---- Spiele ------------------------------------------------------------
    def _games(self):
        return self.ctx.settings.get("gaming.games")

    def _render_games(self):
        games = self._games()
        rows, keys = [], []
        for i, g in enumerate(games):
            rows.append([(g["name"], g["name"].lower()), (tr(f"game.src.{g['source']}"), g["source"]), (g["target"], None)])
            keys.append(i)
        self.table.set_rows(rows, keys)
        self.games_status.setText(tr("game.count", n=len(games)))

    def _detect(self):
        def done(found):
            existing = {g["target"] for g in self._games()}
            new = [{"name": g.name, "target": g.target, "source": g.source} for g in found if g.target not in existing]
            if new:
                self.ctx.settings.set("gaming.games", self._games() + new)
            self._render_games()
            msg.info(self, tr("game.detect"), tr("game.detected", found=len(found), new=len(new)))

        run_task(library.detect_games, on_done=done, context="games")

    def _add(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("game.add"), os.path.expanduser("~"),
                                              tr("game.file_filter") + " (*.exe *.lnk *.url)")
        if not path:
            return
        path = os.path.normpath(path)
        reason = library.validate_target(path)
        if reason:
            msg.warn(self, tr("game.add"), tr(f"game.invalid.{reason}"))
            return
        name = os.path.splitext(os.path.basename(path))[0]
        self.ctx.settings.set("gaming.games", self._games() + [{"name": name, "target": path, "source": "manual"}])
        self._render_games()

    def _selected(self):
        k = self.table.selected_key()
        games = self._games()
        return (k, games[k]) if k is not None and k < len(games) else (None, None)

    def _launch(self):
        k, g = self._selected()
        if g is None:
            msg.info(self, tr("game.launch"), tr("game.select_first"))
            return
        try:
            library.launch(g["target"])
        except ValueError as exc:
            msg.warn(self, tr("game.launch"), tr(f"game.invalid.{exc}"))
        except OSError as exc:
            msg.warn(self, tr("game.launch"), tr("common.action_failed", error=str(exc)))

    def _remove(self):
        k, g = self._selected()
        if g is None:
            return
        if not ConfirmDialog.ask(self, tr("game.remove"), tr("game.remove_confirm", name=g["name"]), icon="minus"):
            return
        games = self._games()
        games.pop(k)
        self.ctx.settings.set("gaming.games", games)
        self._render_games()

    # ---- Hinweise ------------------------------------------------------------
    def _run_checks(self):
        from corecontrol.diagnostics.engine import active_power_scheme, top_processes

        ram = self.ctx.sampler.store.latest().ram_percent if self.ctx.sampler and self.ctx.sampler.store.latest() else None

        def job():
            top, _ = top_processes(1.0)
            return run_checks(active_power_scheme(), top, ram)

        def done(checks):
            self.checks = checks
            self._render_checks()

        run_task(job, on_done=done, context="gaming_checks")

    def _render_checks(self):
        while self.checks_lay.count():
            it = self.checks_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for c in self.checks:
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 4, 0, 4)
            icon, role = {"ok": ("circle-check", "ok"), "hint": ("info", "warn"), "info": ("info", "info")}.get(
                c.state, ("circle-help", "text3"))
            row.addWidget(icon_label(icon, role, 18), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(None, "h3", text=tr(f"game.check.{c.id}.title")))
            col.addWidget(label(None, "faint", text=tr(f"game.check.{c.id}.{c.state}", value=c.value), wrap=True))
            row.addLayout(col, 1)
            if c.action:
                b = button("common.open", None, None, lambda a=c.action: run_action(a))
                row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            self.checks_lay.addWidget(w)

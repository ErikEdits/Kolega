"""Einstellungen."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from corecontrol import REPO_URL, __version__
from corecontrol.core import fmt, paths
from corecontrol.core.platform import IS_WINDOWS, open_path, open_url
from corecontrol.core.settings import TILE_IDS
from corecontrol.i18n import tr
from corecontrol.ui.bus import bind_text, bus, on_refresh
from corecontrol.ui import msg
from corecontrol.ui.pages.base import Page
from corecontrol.ui.theme import ACCENT_PRESETS, theme
from corecontrol.ui.widgets.common import Card, SettingRow, Toggle, button, label, separator, tool_button

LHM_URL = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases"


class SettingsPage(Page):
    page_id = "settings"
    title_key = "set.title"
    subtitle_key = "set.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.st = ctx.settings
        self.sections: dict = {}
        self._build_appearance()
        self._build_dashboard()
        self._build_monitoring()
        self._build_thresholds()
        self._build_history()
        self._build_startup()
        self._build_automation()
        self._build_privacy()
        self._build_about()
        self.finish()

    # ---- Hilfen ------------------------------------------------------------
    def _add_section(self, name: str, card) -> None:
        self.sections[name] = card
        self.body.addWidget(card)

    def scroll_to(self, name: str) -> None:
        card = self.sections.get(name)
        if card is not None and self.scroll_area is not None:
            from corecontrol.ui import anim
            from PySide6.QtCore import QPropertyAnimation

            bar = self.scroll_area.verticalScrollBar()
            target = max(0, card.y() - 12)
            if anim.allow("transition"):
                a = QPropertyAnimation(bar, b"value", self)
                a.setDuration(350)
                a.setStartValue(bar.value())
                a.setEndValue(target)
                a.setEasingCurve(anim.EASE)
                a.start()
            else:
                bar.setValue(target)

    def _toggle(self, key: str) -> Toggle:
        t = Toggle(self.st.get(key))
        t.toggled.connect(lambda v: self.st.set(key, bool(v)))
        return t

    def _spin(self, key: str, lo: int, hi: int, suffix: str = "", step: int = 1) -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setValue(self.st.get(key))
        if suffix:
            sp.setSuffix(f" {suffix}")
        sp.setFixedWidth(120)
        timer = QTimer(sp)
        timer.setSingleShot(True)
        timer.setInterval(400)
        timer.timeout.connect(lambda: self.st.set(key, sp.value()))
        sp.valueChanged.connect(lambda *_: timer.start())
        return sp

    def _seconds(self, key: str, lo: float, hi: float) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(2)
        sp.setSingleStep(0.25)
        sp.setValue(self.st.get(key) / 1000)
        sp.setSuffix(" s")
        sp.setFixedWidth(120)
        timer = QTimer(sp)
        timer.setSingleShot(True)
        timer.setInterval(400)
        timer.timeout.connect(lambda: self.st.set(key, int(round(sp.value() * 1000))))
        sp.valueChanged.connect(lambda *_: timer.start())
        return sp

    def _combo(self, key: str, options: list[tuple[str, str]]) -> QComboBox:
        cb = QComboBox()
        cb.setMinimumWidth(170)

        def fill():
            cb.blockSignals(True)
            cb.clear()
            for value, text_key in options:
                cb.addItem(tr(text_key), value)
            idx = cb.findData(self.st.get(key))
            cb.setCurrentIndex(max(0, idx))
            cb.blockSignals(False)

        fill()
        cb.currentIndexChanged.connect(lambda *_: self.st.set(key, cb.currentData()))
        on_refresh(cb, fill)
        return cb

    # ---- Darstellung -------------------------------------------------------
    def _build_appearance(self):
        card = Card("set.appearance", "palette")
        card.add(SettingRow("set.theme", "set.theme_desc",
                            self._combo("ui.theme", [("system", "set.theme_system"), ("light", "set.theme_light"),
                                                     ("dark", "set.theme_dark")]), "sun"))
        card.add(separator())
        accent_box = QWidget()
        al = QVBoxLayout(accent_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.swatches = QButtonGroup(self)
        self.swatches.setExclusive(True)
        for color in ACCENT_PRESETS:
            b = QToolButton()
            b.setCheckable(True)
            b.setFixedSize(28, 28)
            b.setProperty("role", "swatch")
            b.setStyleSheet(f"QToolButton {{ background: {color}; }}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(color)
            b.clicked.connect(lambda *_, c=color: self.st.set("ui.accent", c))
            self.swatches.addButton(b)
            row.addWidget(b)
            b.setChecked(self.st.get("ui.accent") == color)
        row.addSpacing(8)
        row.addWidget(button("set.accent_custom", None, "palette", self._pick_color))
        if IS_WINDOWS:
            row.addWidget(button("set.accent_windows", None, "monitor", lambda: self.st.set("ui.accent", "windows")))
        row.addStretch(1)
        al.addLayout(row)
        card.add(SettingRow("set.accent", "set.accent_desc", QWidget(), "palette"))
        card.add(accent_box)
        card.add(separator())
        card.add(SettingRow("set.language", "set.language_desc",
                            self._combo("ui.language", [("system", "set.lang_system"), ("de", "set.lang_de"),
                                                        ("en", "set.lang_en")]), "languages"))
        card.add(separator())
        card.add(SettingRow("set.animations", "set.animations_desc",
                            self._combo("ui.animations", [("system", "set.anim_system"), ("full", "set.anim_full"),
                                                          ("reduced", "set.anim_reduced"), ("off", "set.anim_off")]),
                            "sparkle"))
        self._add_section("appearance", card)

    def _pick_color(self):
        current = QColor(theme.palette.accent)
        c = QColorDialog.getColor(current, self, tr("set.accent_custom"))
        if c.isValid():
            self.st.set("ui.accent", c.name())
            for b in self.swatches.buttons():
                b.setChecked(False)

    # ---- Dashboard ---------------------------------------------------------
    def _build_dashboard(self):
        card = Card("set.dashboard", "layout-grid")
        card.add(label("set.dashboard_desc", "muted", wrap=True))
        lay = QHBoxLayout()
        self.tile_list = QListWidget()
        self.tile_list.setMinimumHeight(250)
        self.tile_list.setMaximumHeight(300)
        self._fill_tiles()
        self.tile_list.itemChanged.connect(lambda *_: self._save_tiles())
        lay.addWidget(self.tile_list, 1)
        btns = QVBoxLayout()
        btns.addWidget(tool_button("chevron-up", "set.move_up", lambda: self._move_tile(-1)))
        btns.addWidget(tool_button("chevron-down", "set.move_down", lambda: self._move_tile(1)))
        btns.addStretch(1)
        lay.addLayout(btns)
        card.add_layout(lay)
        on_refresh(self.tile_list, self._fill_tiles)
        self._add_section("dashboard", card)

    def _fill_tiles(self):
        self.tile_list.blockSignals(True)
        self.tile_list.clear()
        active = self.st.get("dashboard.tiles")
        order = active + [t for t in TILE_IDS if t not in active]
        for tid in order:
            it = QListWidgetItem(tr(f"tile.{tid}"))
            it.setData(Qt.ItemDataRole.UserRole, tid)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if tid in active else Qt.CheckState.Unchecked)
            self.tile_list.addItem(it)
        self.tile_list.blockSignals(False)

    def _save_tiles(self):
        tiles = []
        for i in range(self.tile_list.count()):
            it = self.tile_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                tiles.append(it.data(Qt.ItemDataRole.UserRole))
        self.st.set("dashboard.tiles", tiles)

    def _move_tile(self, d: int):
        row = self.tile_list.currentRow()
        if row < 0:
            return
        new = row + d
        if not 0 <= new < self.tile_list.count():
            return
        self.tile_list.blockSignals(True)
        it = self.tile_list.takeItem(row)
        self.tile_list.insertItem(new, it)
        self.tile_list.setCurrentRow(new)
        self.tile_list.blockSignals(False)
        self._save_tiles()

    # ---- Messung -----------------------------------------------------------
    def _build_monitoring(self):
        card = Card("set.monitoring", "activity")
        card.add(SettingRow("set.interval", "set.interval_desc", self._seconds("monitor.interval_ms", 0.25, 10), "timer"))
        card.add(SettingRow("set.bg_interval", "set.bg_interval_desc",
                            self._seconds("monitor.background_interval_ms", 1, 60), "timer"))
        card.add(separator())
        card.add(SettingRow("set.lhm", "set.lhm_desc", self._toggle("sensors.lhm_enabled"), "thermometer"))
        card.add(SettingRow("set.lhm_port", "set.lhm_port_desc", self._spin("sensors.lhm_port", 1, 65535), "plug"))
        self.lhm_status = label(None, "faint", text="", wrap=True)
        row = QHBoxLayout()
        row.addWidget(self.lhm_status, 1)
        row.addWidget(button("set.lhm_download", "ghost", "external-link", lambda: open_url(LHM_URL)))
        card.add_layout(row)
        card.add(label("set.lhm_help", "faint", wrap=True))
        self._add_section("monitoring", card)

    def on_sample(self, s):
        key = {"ok": "set.lhm_status_ok", "not_running": "set.lhm_status_off", "off": "set.lhm_status_disabled"}.get(
            s.lhm_status, "set.lhm_status_off")
        self.lhm_status.setText(tr(key, n=len(s.sensors)))

    # ---- Schwellen ---------------------------------------------------------
    def _build_thresholds(self):
        card = Card("set.thresholds", "bell")
        card.add(label("set.thresholds_desc", "muted", wrap=True))
        for key, lo, hi, unit in (
            ("thresholds.cpu_temp_warn", 40, 110, "°C"), ("thresholds.cpu_temp_crit", 40, 115, "°C"),
            ("thresholds.gpu_temp_warn", 40, 110, "°C"), ("thresholds.gpu_temp_crit", 40, 115, "°C"),
            ("thresholds.cpu_load_warn", 50, 100, "%"), ("thresholds.ram_warn", 50, 100, "%"),
            ("thresholds.disk_free_warn_pct", 1, 50, "%"), ("thresholds.disk_free_crit_pct", 1, 50, "%"),
            ("thresholds.disk_free_warn_gb", 1, 1000, "GB"), ("thresholds.disk_free_crit_gb", 1, 1000, "GB"),
        ):
            card.add(SettingRow(f"set.{key}", None, self._spin(key, lo, hi, unit)))
        card.add(separator())
        card.add(SettingRow("set.notify", "set.notify_desc", self._toggle("notify.enabled"), "bell"))
        card.add(SettingRow("set.cooldown", "set.cooldown_desc", self._spin("notify.cooldown_min", 1, 1440, "min"), "clock"))
        self._add_section("thresholds", card)

    # ---- Verlauf -----------------------------------------------------------
    def _build_history(self):
        card = Card("set.history", "history")
        card.add(SettingRow("set.history_enabled", "set.history_enabled_desc", self._toggle("history.enabled"), "database"))
        card.add(SettingRow("set.retention", "set.retention_desc", self._spin("history.retention_days", 1, 730, tr("set.days")), "clock"))
        self.history_info = label(None, "faint", text="", wrap=True)
        card.add(self.history_info)
        card.add(label("set.history_what", "faint", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("set.history_clear", "danger", "trash-2", self._clear_history))
        row.addStretch(1)
        card.add_layout(row)
        self._add_section("history", card)

    def _update_history_info(self):
        h = self.ctx.history
        if h is None:
            self.history_info.setText(tr("set.history_unavailable"))
            return
        try:
            s = h.stats()
        except Exception:
            self.history_info.setText(tr("set.history_unavailable"))
            return
        self.history_info.setText(tr("set.history_info", size=fmt.bytes_(s["size"]),
                                     rows=s["minute_rows"] + s["hour_rows"],
                                     oldest=fmt.datetime_(s["oldest"]) if s["oldest"] else tr("common.na")))

    def _clear_history(self):
        if self.ctx.history is None:
            return
        if msg.ask(self, tr("set.history_clear"), tr("set.history_clear_confirm")):
            self.ctx.history.clear()
            self._update_history_info()

    # ---- Start -------------------------------------------------------------
    def _build_startup(self):
        card = Card("set.startup", "power")
        card.add(SettingRow("set.with_windows", "set.with_windows_desc", self._toggle("startup.with_windows"), "power"))
        card.add(SettingRow("set.start_min", "set.start_min_desc", self._toggle("startup.minimized"), "minus"))
        card.add(separator())
        card.add(SettingRow("set.tray", "set.tray_desc", self._toggle("tray.enabled"), "pin"))
        card.add(SettingRow("set.min_tray", "set.min_tray_desc", self._toggle("tray.minimize_to_tray"), "minus"))
        card.add(SettingRow("set.close_tray", "set.close_tray_desc", self._toggle("tray.close_to_tray"), "x"))
        self._add_section("startup", card)

    # ---- Automatik ---------------------------------------------------------
    def _build_automation(self):
        card = Card("set.auto", "sparkles")
        card.add(SettingRow("set.auto_diag", "set.auto_diag_desc", self._toggle("auto.diagnosis_on_start"), "stethoscope"))
        card.add(SettingRow("set.auto_interval", "set.auto_interval_desc",
                            self._spin("auto.diagnosis_interval_h", 0, 168, "h"), "timer"))
        card.add(SettingRow("set.net_in_diag", "set.net_in_diag_desc", self._toggle("network.include_in_diagnosis"), "wifi"))
        card.add(SettingRow("set.update_check", "set.update_check_desc", self._toggle("updates.check_on_start"), "download"))
        card.add(separator())
        card.add(SettingRow("set.never_auto", "set.never_auto_desc", label("set.locked", "faint"), "lock"))
        self._add_section("auto", card)

    # ---- Datenschutz -------------------------------------------------------
    def _build_privacy(self):
        card = Card("set.privacy", "shield-check")
        card.add(label("set.privacy_text", "muted", wrap=True))
        card.add(label(None, "faint", text=tr("set.data_paths", config=str(paths.config_dir()), data=str(paths.data_dir())),
                       wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("set.open_data", None, "folder-open", lambda: open_path(str(paths.data_dir()))))
        row.addWidget(button("set.export", None, "upload", self._export))
        row.addWidget(button("set.import", None, "download", self._import))
        row.addWidget(button("set.reset", None, "refresh-cw", self._reset))
        row.addStretch(1)
        card.add_layout(row)
        self._add_section("privacy", card)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("set.export"), str(Path.home() / "CoreControl-Einstellungen.json"),
                                              "JSON (*.json)")
        if not path:
            return
        ok = self.st.export_to(Path(path))
        msg.info(self, tr("set.export"), tr("set.export_ok" if ok else "set.export_failed", path=path))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("set.import"), str(Path.home()), "JSON (*.json)")
        if not path:
            return
        try:
            warnings = self.st.import_from(Path(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            msg.warn(self, tr("set.import"), tr("set.import_failed", error=str(exc)))
            return
        msg = tr("set.import_ok")
        if warnings:
            msg += "\n\n" + tr("set.import_warnings", n=len(warnings))
        msg.info(self, tr("set.import"), msg)
        self._fill_tiles()

    def _reset(self):
        if msg.ask(self, tr("set.reset"), tr("set.reset_confirm")):
            self.st.reset()
            msg.info(self, tr("set.reset"), tr("set.reset_done"))

    # ---- Über --------------------------------------------------------------
    def _build_about(self):
        card = Card("set.about", "info")
        card.add(label(None, "h3", text=f"CoreControl {__version__}"))
        card.add(label("set.about_text", "muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("set.project_page", None, "external-link", lambda: open_url(REPO_URL)))
        self.update_btn = button("set.check_updates", None, "refresh-cw", self._check_updates)
        row.addWidget(self.update_btn)
        row.addWidget(button("set.licenses", None, "file-text", self._licenses))
        row.addStretch(1)
        card.add_layout(row)
        self.update_result = label(None, "faint", text="", wrap=True)
        card.add(self.update_result)
        self._add_section("about", card)

    def _check_updates(self):
        from corecontrol.ui.workers import run_task
        from corecontrol.updates.checker import check_for_update

        self.update_btn.setEnabled(False)
        self.update_result.setText(tr("updates.checking"))

        def done(res):
            self.update_btn.setEnabled(True)
            self.update_result.setText(res.describe())
            if res.update_available and res.url:
                if msg.ask(self, tr("updates.title"), tr("updates.open_page", version=res.latest_version)):
                    open_url(res.url)

        def failed(exc):
            self.update_btn.setEnabled(True)
            self.update_result.setText(tr("updates.failed", error=str(exc)))

        run_task(check_for_update, on_done=done, on_error=failed, context="updates")

    def _licenses(self):
        from corecontrol.ui.dialogs import show_text_dialog
        from corecontrol.core.platform import resource_path

        try:
            text = Path(resource_path("assets", "THIRD_PARTY_LICENSES.md")).read_text(encoding="utf-8")
        except OSError:
            text = tr("set.licenses_missing")
        show_text_dialog(self, tr("set.licenses"), text)

    def on_show(self):
        self._update_history_info()
        s = self.ctx.sampler.store.latest() if self.ctx.sampler else None
        if s:
            self.on_sample(s)

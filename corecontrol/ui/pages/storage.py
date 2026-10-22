"""Speicher: Laufwerke, Analyse großer Ordner/Dateien und sichere Bereinigung."""

from __future__ import annotations

import os

import psutil
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QRadioButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from corecontrol.core import fmt
from corecontrol.core.platform import IS_WINDOWS, is_admin, open_path, open_url, show_in_explorer
from corecontrol.i18n import has, tr
from corecontrol.storage import cleanup, scanner
from corecontrol.storage.safety import classify, ext_category, is_protected_path
from corecontrol.system.tools import run_tool
from corecontrol.ui.bus import bind_text, on_refresh
from corecontrol.ui.dialogs import ConfirmDialog
from corecontrol.ui.pages.base import Page
from corecontrol.ui.widgets.charts import Donut
from corecontrol.ui.widgets.common import Card, Chip, KeyValueGrid, button, label, set_prop
from corecontrol.ui.widgets.table import DataTable
from corecontrol.ui.workers import run_task

TYPE_COLORS = {"video": "#e0457b", "image": "#f06a2b", "audio": "#d4a106", "document": "#22a35a", "archive": "#0ea5a4",
               "installer": "#2d7ff9", "disk_image": "#8b5cf6", "temp": "#94a3b8", "program": "#64748b", "other": "#475569"}
def reason_text(r: str) -> str:
    return tr(f"sto.reason.{r}") if has(f"sto.reason.{r}") else r


CLASS_LEVEL = {"system": "critical", "program": "warning", "appdata": "warning", "temp": "ok", "user": "info",
               "recycle": "neutral", "unknown": "neutral"}


class StoragePage(Page):
    page_id = "storage"
    title_key = "sto.title"
    subtitle_key = "sto.subtitle"

    def __init__(self, ctx):
        super().__init__(ctx)
        if IS_WINDOWS:
            self.header.add_action(button("sto.storage_sense", None, "database", lambda: open_url("ms-settings:storagesense")))
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs)
        self.tabs.addTab(self._build_drives(), "")
        self.tabs.addTab(self._build_analysis(), "")
        self.tabs.addTab(self._build_cleanup(), "")
        self.finish()
        self.scan_result = None
        self.scan_handle = None
        self.cats = []
        self.clean_handle = None
        on_refresh(self, self._retranslate)
        self._retranslate()

    def _retranslate(self):
        self.tabs.setTabText(0, tr("sto.tab_drives"))
        self.tabs.setTabText(1, tr("sto.tab_analysis"))
        self.tabs.setTabText(2, tr("sto.tab_cleanup"))
        self.files_table.set_headers([tr("common.name"), tr("common.size"), tr("sto.col.type"), tr("sto.col.assessment"),
                                      tr("common.path")])
        self.tree.setHeaderLabels([tr("sto.col.folder"), tr("common.size"), tr("sto.col.share"), tr("sto.col.files")])
        if self.scan_result:
            self._render_scan()
        if self.cats:
            self._render_cats()

    # ---- Laufwerke ---------------------------------------------------------
    def _build_drives(self) -> QWidget:
        w = QWidget()
        self.drives_lay = QVBoxLayout(w)
        self.drives_lay.setContentsMargins(0, 14, 0, 0)
        self.drives_lay.setSpacing(12)
        return w

    def _render_drives(self):
        while self.drives_lay.count():
            it = self.drives_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        hw = self.ctx.hardware or {}
        disks = {str(d.get("number")): d for d in hw.get("disks") or []}
        disk_of = {v["mount"]: v.get("disk") for v in hw.get("volumes") or []}
        for p in psutil.disk_partitions(all=False):
            if not p.fstype or "cdrom" in p.opts:
                continue
            if not IS_WINDOWS and (p.mountpoint.startswith(("/snap", "/boot", "/proc", "/sys")) or p.fstype in ("squashfs", "overlay")):
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue
            card = Card(None)
            top = QHBoxLayout()
            name = label(None, "h2", text=p.mountpoint)
            top.addWidget(name)
            disk = disks.get(str(disk_of.get(p.mountpoint)))
            if disk:
                top.addWidget(label(None, "muted", text=f"{disk.get('model', '')} · {disk.get('media') or ''}"))
                h = disk.get("health", "unknown")
                top.addWidget(Chip(tr(f"hw.health.{h}"), {"healthy": "ok", "warning": "warning", "unhealthy": "critical"}.get(h, "neutral")))
            top.addStretch(1)
            top.addWidget(button("sto.analyze_drive", "primary", "folder-search", lambda m=p.mountpoint: self._start_scan(m)))
            card.add_layout(top)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(u.percent * 10))
            free_pct = 100 - u.percent
            set_prop(bar, "level", "critical" if free_pct < 5 else "warning" if free_pct < 10 else "")
            card.add(bar)
            card.add(label(None, "muted", text=tr("sto.drive_line", used=fmt.bytes_(u.used), total=fmt.bytes_(u.total),
                                                  free=fmt.bytes_(u.free), pct=fmt.pct(free_pct), fs=p.fstype)))
            self.drives_lay.addWidget(card)
        rb = cleanup.recycle_bin_info()
        if rb is not None:
            card = Card("sto.recycle", "trash-2")
            card.add(label(None, "muted", text=tr("sto.recycle_info", size=fmt.bytes_(rb[0]), n=rb[1])))
            row = QHBoxLayout()
            b = button("sto.recycle_empty", "danger", "trash-2", self._empty_recycle)
            b.setEnabled(rb[1] > 0)
            row.addWidget(b)
            row.addStretch(1)
            card.add_layout(row)
            self.drives_lay.addWidget(card)
        self.drives_lay.addStretch(1)

    def _empty_recycle(self):
        rb = cleanup.recycle_bin_info()
        if not rb:
            return
        if not ConfirmDialog.ask(self, tr("sto.recycle_empty"), tr("sto.recycle_confirm", size=fmt.bytes_(rb[0]), n=rb[1]),
                                 confirm_text=tr("sto.recycle_empty"), danger=True,
                                 require_check=tr("sto.recycle_check"), icon="trash-2"):
            return
        ok = cleanup.empty_recycle_bin(confirmed=True)
        after = cleanup.recycle_bin_info()
        if ok and after is not None and after[1] == 0:
            QMessageBox.information(self, tr("sto.recycle"), tr("sto.recycle_done"))
        else:
            QMessageBox.warning(self, tr("sto.recycle"), tr("sto.recycle_partial", n=after[1] if after else "?"))
        self._render_drives()

    # ---- Analyse -------------------------------------------------------------
    def _build_analysis(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 14, 0, 0)
        v.setSpacing(12)
        row = QHBoxLayout()
        self.root_combo = QComboBox()
        self.root_combo.setMinimumWidth(260)
        self.root_combo.setEditable(False)
        row.addWidget(self.root_combo)
        row.addWidget(button("sto.choose_folder", None, "folder-open", self._choose_folder))
        self.scan_btn = button("sto.scan", "primary", "play", lambda: self._start_scan(self.root_combo.currentData()))
        self.cancel_btn = button("common.cancel", None, "square", self._cancel_scan)
        self.cancel_btn.setVisible(False)
        row.addWidget(self.scan_btn)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.scan_status = label(None, "muted", text="", wrap=True)
        v.addWidget(self.scan_status)
        self.scan_bar = QProgressBar()
        self.scan_bar.setRange(0, 0)
        self.scan_bar.setVisible(False)
        v.addWidget(self.scan_bar)

        self.res_host = QWidget()
        rl = QVBoxLayout(self.res_host)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(16)
        types_card = Card("sto.by_type", "chart-pie")
        tl = QHBoxLayout()
        self.donut = Donut(170)
        tl.addWidget(self.donut)
        self.legend = QGridLayout()
        self.legend.setVerticalSpacing(4)
        tl.addLayout(self.legend, 1)
        types_card.add_layout(tl)
        top.addWidget(types_card, 3)
        sum_card = Card("sto.summary", "info")
        self.sum_kv = KeyValueGrid()
        sum_card.add(self.sum_kv)
        sum_card.align_top()
        top.addWidget(sum_card, 2)
        rl.addLayout(top)

        folders = Card("sto.folders", "folder")
        folders.add(label("sto.folders_desc", "faint", wrap=True))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setMinimumHeight(320)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemExpanded.connect(self._expand_item)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.Stretch)
        folders.add(self.tree)
        frow = QHBoxLayout()
        frow.addWidget(button("sto.open_folder", None, "folder-open", self._open_tree_folder))
        frow.addStretch(1)
        folders.add_layout(frow)
        rl.addWidget(folders)

        files = Card("sto.largest", "file")
        files.add(label("sto.largest_desc", "faint", wrap=True))
        self.files_table = DataTable([], stretch_col=4, min_height=340)
        files.add(self.files_table)
        frow2 = QHBoxLayout()
        frow2.addWidget(button("sto.show_in_explorer", None, "folder-open", self._show_file))
        frow2.addWidget(button("sto.delete_file", "danger", "trash-2", self._delete_file))
        frow2.addStretch(1)
        files.add_layout(frow2)
        rl.addWidget(files)

        self.denied_card = Card("sto.denied", "lock")
        self.denied_text = label(None, "faint", text="", wrap=True)
        self.denied_card.add(self.denied_text)
        rl.addWidget(self.denied_card)
        self.res_host.setVisible(False)
        v.addWidget(self.res_host)
        v.addStretch(1)
        return w

    def _fill_roots(self):
        current = self.root_combo.currentData()
        self.root_combo.clear()
        home = os.path.expanduser("~")
        self.root_combo.addItem(tr("sto.user_folder", path=home), home)
        for p in psutil.disk_partitions(all=False):
            if p.fstype and "cdrom" not in p.opts:
                if not IS_WINDOWS and p.mountpoint != "/":
                    continue
                self.root_combo.addItem(p.mountpoint, p.mountpoint)
        if current:
            i = self.root_combo.findData(current)
            if i < 0:
                self.root_combo.addItem(current, current)
                i = self.root_combo.count() - 1
            self.root_combo.setCurrentIndex(i)

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("sto.choose_folder"), os.path.expanduser("~"))
        if d:
            d = os.path.normpath(d)
            i = self.root_combo.findData(d)
            if i < 0:
                self.root_combo.addItem(d, d)
                i = self.root_combo.count() - 1
            self.root_combo.setCurrentIndex(i)

    def _start_scan(self, root):
        if not root or self.scan_handle is not None:
            return
        self.tabs.setCurrentIndex(1)
        i = self.root_combo.findData(root)
        if i < 0:
            self.root_combo.addItem(root, root)
            i = self.root_combo.count() - 1
        self.root_combo.setCurrentIndex(i)
        self.scan_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.scan_bar.setVisible(True)
        self.scan_status.setText(tr("sto.scanning", root=root))

        def progress(p):
            self.scan_status.setText(tr("sto.scan_progress", files=fmt.number(p["files"]), size=fmt.bytes_(p["size"]),
                                        dir=p["dir"][-90:]))

        def done(res):
            self.scan_handle = None
            self.scan_btn.setEnabled(True)
            self.cancel_btn.setVisible(False)
            self.scan_bar.setVisible(False)
            self.scan_result = res
            self._render_scan()

        def failed(exc):
            self.scan_handle = None
            self.scan_btn.setEnabled(True)
            self.cancel_btn.setVisible(False)
            self.scan_bar.setVisible(False)
            self.scan_status.setText(tr("common.action_failed", error=str(exc)))

        self.scan_handle = run_task(scanner.scan, root, on_done=done, on_error=failed, on_progress=progress, context="scan")

    def _cancel_scan(self):
        if self.scan_handle:
            self.scan_handle.cancel()

    def _render_scan(self):
        r = self.scan_result
        if r is None:
            return
        self.res_host.setVisible(True)
        state = tr("sto.scan_cancelled") if r.cancelled else tr("sto.scan_done", secs=fmt.number(r.seconds, 1))
        self.scan_status.setText(state)
        self.sum_kv.set_rows([
            (tr("sto.sum.root"), r.root),
            (tr("sto.sum.total"), fmt.bytes_(r.total)),
            (tr("sto.sum.files"), fmt.number(r.files)),
            (tr("sto.sum.dirs"), fmt.number(r.dirs)),
            (tr("sto.sum.denied"), fmt.number(r.denied_count)),
            (tr("sto.sum.cloud"), tr("sto.sum.cloud_val", n=fmt.number(r.cloud_only), size=fmt.bytes_(r.cloud_only_size))
             if r.cloud_only else "0"),
            (tr("sto.sum.links"), fmt.number(r.links_skipped)),
        ])
        parts = sorted(((tr(f"sto.type.{k}"), v, TYPE_COLORS.get(k, "#888")) for k, v in r.by_type.items() if v > 0),
                       key=lambda x: -x[1])
        self.donut.set_parts(parts, fmt.bytes_(r.total), tr("sto.in_files", n=fmt.number(r.files)))
        while self.legend.count():
            it = self.legend.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, (name, v, color) in enumerate(parts[:9]):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 14px;")
            self.legend.addWidget(dot, i, 0)
            self.legend.addWidget(QLabel(name), i, 1)
            pct = 100 * v / r.total if r.total else 0
            self.legend.addWidget(label(None, "muted", text=f"{fmt.bytes_(v)} · {fmt.pct(pct)}"), i, 2)
        # Ordnerbaum
        self.tree.clear()
        root_item = self._tree_item(r.root, r.dir_sizes.get(r.root, r.total), r.total)
        self.tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        # Größte Dateien
        rows, keys = [], []
        for size, path in r.largest:
            cls = classify(path)
            rows.append([(os.path.basename(path), os.path.basename(path).lower()), (fmt.bytes_(size), size),
                         (tr(f"sto.type.{ext_category(path)}"), ext_category(path)),
                         (tr(f"sto.class.{cls}"), cls), (path, path.lower())])
            keys.append(path)
        self.files_table.set_rows(rows, keys)
        self.files_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self._sizes = {p: s for s, p in r.largest}
        self.denied_card.setVisible(r.denied_count > 0)
        more = f"\n… (+{r.denied_count - len(r.denied)})" if r.denied_count > len(r.denied) else ""
        self.denied_text.setText(tr("sto.denied_desc") + "\n" + "\n".join(r.denied[:30]) + more)

    def _tree_item(self, path, size, total) -> QTreeWidgetItem:
        r = self.scan_result
        name = os.path.basename(path.rstrip("\\/")) or path
        it = QTreeWidgetItem([name, fmt.bytes_(size), fmt.pct(100 * size / total if total else 0, 1),
                              fmt.number(r.dir_files.get(path, 0))])
        it.setData(0, Qt.ItemDataRole.UserRole, path)
        it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        it.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        it.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | it.textAlignment(3))
        if r.children(path):
            it.addChild(QTreeWidgetItem(["…"]))  # Platzhalter für Aufklappen
        return it

    def _expand_item(self, item):
        r = self.scan_result
        if r is None or item.childCount() != 1 or item.child(0).data(0, Qt.ItemDataRole.UserRole):
            return
        item.takeChildren()
        path = item.data(0, Qt.ItemDataRole.UserRole)
        for child, size in r.children(path)[:200]:
            item.addChild(self._tree_item(child, size, r.total))

    def _open_tree_folder(self):
        it = self.tree.currentItem()
        if it is not None:
            p = it.data(0, Qt.ItemDataRole.UserRole)
            if p and os.path.isdir(p):
                open_path(p)

    def _show_file(self):
        p = self.files_table.selected_key()
        if p and os.path.exists(p):
            show_in_explorer(p)

    def _delete_file(self):
        path = self.files_table.selected_key()
        if not path:
            QMessageBox.information(self, tr("sto.delete_file"), tr("sto.select_file"))
            return
        if not os.path.exists(path):
            QMessageBox.information(self, tr("sto.delete_file"), tr("sto.file_gone"))
            return
        cls = classify(path)
        if is_protected_path(path):
            QMessageBox.warning(self, tr("sto.delete_file"), tr("sto.protected", path=path, cls=tr(f"sto.class.{cls}")))
            return
        size = self._sizes.get(path, 0)
        msg = tr("sto.delete_confirm", cls=tr(f"sto.class.{cls}"), advice=tr(f"sto.advice.{cls}"))
        details = tr("sto.delete_details", path=path, size=fmt.bytes_(size), type=tr(f"sto.type.{ext_category(path)}"))
        need_check = cls in ("appdata", "unknown", "user")
        if not ConfirmDialog.ask(self, tr("sto.delete_title"), msg, details, confirm_text=tr("sto.to_trash"),
                                 danger=False, require_check=tr("sto.delete_check") if need_check else None, icon="trash-2"):
            return
        res = cleanup.delete_files([(path, size)], [], confirmed=True, permanent=False)
        if res.deleted:
            QMessageBox.information(self, tr("sto.delete_file"), tr("sto.moved_to_trash", path=path))
            self.scan_result.largest = [(s, p) for s, p in self.scan_result.largest if p != path]
            self._render_scan()
        else:
            reason = (res.failed or res.skipped or [("", "unknown")])[0][1]
            QMessageBox.warning(self, tr("sto.delete_file"), tr("sto.delete_failed", reason=reason_text(reason)))

    # ---- Bereinigung -------------------------------------------------------
    def _build_cleanup(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 14, 0, 0)
        v.setSpacing(12)
        v.addWidget(label("sto.clean_desc", "muted", wrap=True))
        row = QHBoxLayout()
        self.clean_scan_btn = button("sto.clean_scan", "primary", "folder-search", self._scan_cleanup)
        row.addWidget(self.clean_scan_btn)
        if IS_WINDOWS:
            row.addWidget(button("sto.cleanmgr", None, "trash-2", lambda: run_tool("cleanmgr")))
        row.addStretch(1)
        v.addLayout(row)
        self.clean_status = label(None, "faint", text="", wrap=True)
        v.addWidget(self.clean_status)
        self.cat_host = QWidget()
        self.cat_lay = QVBoxLayout(self.cat_host)
        self.cat_lay.setContentsMargins(0, 0, 0, 0)
        self.cat_lay.setSpacing(8)
        v.addWidget(self.cat_host)
        opt = QHBoxLayout()
        self.mode_trash = QRadioButton()
        bind_text(self.mode_trash, "sto.mode_trash")
        self.mode_perm = QRadioButton()
        bind_text(self.mode_perm, "sto.mode_permanent")
        self.mode_trash.setChecked(True)
        opt.addWidget(self.mode_trash)
        opt.addWidget(self.mode_perm)
        opt.addStretch(1)
        self.mode_row = QWidget()
        self.mode_row.setLayout(opt)
        self.mode_row.setVisible(False)
        v.addWidget(self.mode_row)
        crow = QHBoxLayout()
        self.clean_btn = button("sto.clean_selected", "danger", "trash-2", self._clean)
        self.clean_btn.setVisible(False)
        crow.addWidget(self.clean_btn)
        self.clean_sum = label(None, "muted", text="")
        crow.addWidget(self.clean_sum)
        crow.addStretch(1)
        v.addLayout(crow)
        v.addWidget(label("sto.clean_rules", "faint", wrap=True))
        v.addStretch(1)
        self.cat_checks: dict[str, QCheckBox] = {}
        return w

    def _scan_cleanup(self):
        self.clean_scan_btn.setEnabled(False)
        self.clean_status.setText(tr("sto.clean_scanning"))
        days = self.ctx.settings.get("storage.cleanup_min_age_days")

        def done(cats):
            self.clean_scan_btn.setEnabled(True)
            self.cats = cats
            self._render_cats()

        def failed(exc):
            self.clean_scan_btn.setEnabled(True)
            self.clean_status.setText(tr("common.action_failed", error=str(exc)))

        run_task(cleanup.scan_categories, days, on_done=done, on_error=failed, context="cleanup_scan")

    def _render_cats(self):
        prev = {k: c.isChecked() for k, c in self.cat_checks.items()}
        while self.cat_lay.count():
            it = self.cat_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.cat_checks = {}
        admin = is_admin()
        for c in self.cats:
            if not c.exists:
                continue
            card = Card(None, margins=14, spacing=4)
            top = QHBoxLayout()
            cb = QCheckBox(tr(f"sto.cat.{c.id}.name"))
            cb.setStyleSheet("font-weight: 600;")
            cb.setChecked(prev.get(c.id, c.default_selected) and c.total > 0)
            cb.setEnabled(c.total > 0)
            cb.toggled.connect(lambda *_: self._update_clean_sum())
            self.cat_checks[c.id] = cb
            top.addWidget(cb)
            top.addStretch(1)
            if c.risk == "medium":
                top.addWidget(Chip(tr("sto.risk_medium"), "warning"))
            if c.needs_admin and not admin:
                top.addWidget(Chip(tr("sto.admin_partial"), "neutral"))
            top.addWidget(label(None, "h3", text=fmt.bytes_(c.total)))
            card.add_layout(top)
            card.add(label(f"sto.cat.{c.id}.desc", "muted", wrap=True))
            info = tr("sto.cat_files", n=fmt.number(len(c.files)))
            if c.denied:
                info += " · " + tr("sto.cat_denied", n=c.denied)
            if c.truncated:
                info += " · " + tr("sto.cat_truncated")
            card.add(label(None, "faint", text=info))
            self.cat_lay.addWidget(card)
        total = sum(c.total for c in self.cats)
        self.clean_status.setText(tr("sto.clean_found", size=fmt.bytes_(total),
                                     days=self.ctx.settings.get("storage.cleanup_min_age_days")))
        self.mode_row.setVisible(True)
        self.clean_btn.setVisible(True)
        self._update_clean_sum()

    def _selected_files(self):
        files, roots = [], []
        for c in self.cats:
            cb = self.cat_checks.get(c.id)
            if cb is not None and cb.isChecked():
                files.extend((f.path, f.size) for f in c.files)
                roots.extend(c.roots)
        return files, roots

    def _update_clean_sum(self):
        files, _ = self._selected_files()
        self.clean_sum.setText(tr("sto.clean_sum", n=fmt.number(len(files)), size=fmt.bytes_(sum(s for _, s in files))))
        self.clean_btn.setEnabled(bool(files))

    def _clean(self):
        files, roots = self._selected_files()
        if not files:
            return
        permanent = self.mode_perm.isChecked()
        total = sum(s for _, s in files)
        cats = [tr(f"sto.cat.{c.id}.name") for c in self.cats if self.cat_checks.get(c.id) and self.cat_checks[c.id].isChecked()]
        listing = "\n".join(f"{fmt.bytes_(s):>10}  {p}" for p, s in files[:3000])
        if len(files) > 3000:
            listing += "\n" + tr("sto.list_more", n=len(files) - 3000)
        msg = tr("sto.clean_confirm", n=fmt.number(len(files)), size=fmt.bytes_(total), cats=", ".join(cats),
                 mode=tr("sto.mode_permanent") if permanent else tr("sto.mode_trash"))
        if permanent:
            msg += "\n\n" + tr("sto.permanent_warning")
        if not ConfirmDialog.ask(self, tr("sto.clean_title"), msg, listing,
                                 confirm_text=tr("sto.clean_now"), danger=permanent,
                                 require_check=tr("sto.clean_check"), icon="trash-2"):
            return
        self.clean_btn.setEnabled(False)
        self.clean_status.setText(tr("sto.cleaning"))

        def done(res):
            self.clean_btn.setEnabled(True)
            failed_reasons = {}
            for _, reason in res.failed + res.skipped:
                failed_reasons[reason] = failed_reasons.get(reason, 0) + 1
            details = "\n".join(f"{reason_text(k)}: {v}" for k, v in failed_reasons.items())
            text = tr("sto.clean_result", n=fmt.number(res.deleted), size=fmt.bytes_(res.deleted_bytes),
                      failed=fmt.number(len(res.failed) + len(res.skipped)))
            if res.to_trash and res.deleted:
                text += "\n\n" + tr("sto.clean_trash_hint")
            if details:
                text += "\n\n" + tr("sto.clean_not_deleted") + "\n" + details
            QMessageBox.information(self, tr("sto.clean_title"), text)
            self._scan_cleanup()

        def failed(exc):
            self.clean_btn.setEnabled(True)
            self.clean_status.setText(tr("common.action_failed", error=str(exc)))

        run_task(cleanup.delete_files, files, roots, True, permanent, on_done=done, on_error=failed, context="cleanup")

    def on_show(self):
        self._render_drives()
        self._fill_roots()

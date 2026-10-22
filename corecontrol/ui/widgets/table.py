"""Sortier- und filterbare Tabelle (Zahlen werden numerisch sortiert)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
KEY_ROLE = Qt.ItemDataRole.UserRole + 2


class _Proxy(QSortFilterProxyModel):
    def lessThan(self, left, right):
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        if a is not None and b is not None:
            try:
                return a < b
            except TypeError:
                pass
        return str(left.data() or "").lower() < str(right.data() or "").lower()


class DataTable(QTableView):
    def __init__(self, headers: list[str], stretch_col: int = 0, min_height: int = 300):
        super().__init__()
        self.model_ = QStandardItemModel(0, len(headers))
        self.model_.setHorizontalHeaderLabels(headers)
        self.proxy = _Proxy()
        self.proxy.setSourceModel(self.model_)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(False)
        self.setMinimumHeight(min_height)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
        hh.setHighlightSections(False)
        self.stretch_col = stretch_col

    def set_headers(self, headers: list[str]) -> None:
        self.model_.setHorizontalHeaderLabels(headers)

    def set_rows(self, rows: list[list[tuple[str, Any]]], keys: list[Any] | None = None) -> None:
        """rows: Liste von Zeilen, jede Zelle (Anzeigetext, Sortierwert oder None). keys: Kennung je Zeile."""
        selected = self.selected_key()
        sort_col = self.horizontalHeader().sortIndicatorSection()
        sort_order = self.horizontalHeader().sortIndicatorOrder()
        self.setSortingEnabled(False)
        m = self.model_
        m.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (text, sort) in enumerate(row):
                it = m.item(r, c)
                if it is None:
                    it = QStandardItem()
                    m.setItem(r, c, it)
                if it.text() != text:
                    it.setText(text)
                it.setData(sort, SORT_ROLE)
                if isinstance(sort, (int, float)) and not isinstance(sort, bool):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c == 0:
                    it.setData(keys[r] if keys else r, KEY_ROLE)
        self.setSortingEnabled(True)
        self.sortByColumn(sort_col, sort_order)
        if selected is not None:
            self.select_key(selected)

    def selected_key(self) -> Any:
        idx = self.selectionModel().selectedRows() if self.selectionModel() else []
        if not idx:
            return None
        src = self.proxy.mapToSource(idx[0])
        item = self.model_.item(src.row(), 0)
        return item.data(KEY_ROLE) if item else None

    def select_key(self, key: Any) -> None:
        for r in range(self.model_.rowCount()):
            it = self.model_.item(r, 0)
            if it is not None and it.data(KEY_ROLE) == key:
                idx = self.proxy.mapFromSource(self.model_.index(r, 0))
                self.selectRow(idx.row())
                return

    def set_filter(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)

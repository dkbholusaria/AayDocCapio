"""GST ▸ Proceedings workspace.

A GST-specific view over the notice/order records written by
:mod:`automation.gst.notices`. Kept separate from the Income Tax
``EProceedingsWorkspace`` because GST notices use a flat list, a different set
of dates/statuses and their own metadata schema.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui._theme import _t
from ui.gst_proceedings_model import (
    GstCase,
    amount_value,
    build_cases,
    filter_cases,
    kpis,
)
from ui.helpers import _btn, _lbl

_KPIS = (
    ("total", "Total"),
    ("open", "Open"),
    ("overdue", "Overdue"),
    ("replied", "Replied"),
    ("orders", "Orders"),
    ("files", "Attachments"),
)

_STATUS_FILTERS = ("All", "Open", "Overdue", "Replied", "Closed")


class GstProceedingsWorkspace(QWidget):
    def __init__(self, vault, assessees_provider, parent=None):
        super().__init__(parent)
        self._vault = vault
        self._assessees_provider = assessees_provider
        self._cases: list[GstCase] = []
        self._case_by_id: dict[str, GstCase] = {}
        self._row_cases: dict[int, GstCase] = {}
        self._selected_id = ""
        self._kpi_values: dict[str, QLabel] = {}

        self._build_shell()
        self._render_detail()

    def refresh(self) -> None:
        root = self._vault.get_setting("download_root_dir", "") or ""
        try:
            assessees = self._assessees_provider() or []
        except Exception:
            assessees = []
        self._cases = build_cases(root, assessees)
        self._case_by_id = {case.id: case for case in self._cases}
        self._refresh_kpis()
        self._render_list()

    def goto_case(self, case_id: str) -> None:
        if case_id in self._case_by_id:
            self._selected_id = case_id
            self._select_row_for_case(case_id)

    def _build_shell(self) -> None:
        t = _t()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(_lbl("GST Notices & Orders", 15, bold=True))
        header.addStretch(1)
        refresh_btn = _btn("Refresh", "secondary", height=32)
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(6)
        for key, caption in _KPIS:
            card = QFrame()
            card.setStyleSheet(
                f"QFrame{{background:{t.bg_table_alt};border:1px solid {t.border};"
                f"border-radius:8px;}}")
            box = QVBoxLayout(card)
            box.setContentsMargins(10, 5, 10, 5)
            box.setSpacing(0)
            box.addWidget(_lbl(caption, 9, color=t.text_muted))
            value = _lbl("0", 14, bold=True)
            box.addWidget(value)
            self._kpi_values[key] = value
            kpi_row.addWidget(card, 1)
        outer.addLayout(kpi_row)

        filters = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Search client, GSTIN, notice type, reference, description…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._render_list)
        filters.addWidget(self._search, 1)
        self._status_filter = QComboBox()
        self._status_filter.addItems(_STATUS_FILTERS)
        self._status_filter.currentTextChanged.connect(self._render_list)
        filters.addWidget(self._status_filter)
        outer.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Client", "Notice / Order", "Reference", "Issued", "Due", "Status"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selection)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self._table)

        self._detail = QWidget()
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(12, 4, 4, 4)
        detail_layout.setSpacing(6)
        self._detail_title = _lbl("Select a notice", 14, bold=True)
        self._detail_title.setWordWrap(True)
        detail_layout.addWidget(self._detail_title)
        self._detail_meta = QLabel("")
        self._detail_meta.setWordWrap(True)
        self._detail_meta.setStyleSheet(
            f"color:{t.text_muted};background:transparent;")
        detail_layout.addWidget(self._detail_meta)
        self._detail_body = QLabel("")
        self._detail_body.setWordWrap(True)
        self._detail_body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_layout.addWidget(self._detail_body)

        detail_layout.addWidget(_lbl("Attachments", 11, bold=True))
        self._files = QListWidget()
        self._files.itemDoubleClicked.connect(self._open_item)
        detail_layout.addWidget(self._files, 1)

        buttons = QHBoxLayout()
        self._open_file_btn = _btn("Open File", "primary", height=32)
        self._open_file_btn.clicked.connect(self._open_selected_file)
        self._open_folder_btn = _btn("Open Folder", "secondary", height=32)
        self._open_folder_btn.clicked.connect(self._open_case_folder)
        buttons.addWidget(self._open_file_btn)
        buttons.addWidget(self._open_folder_btn)
        buttons.addStretch(1)
        detail_layout.addLayout(buttons)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

    def _refresh_kpis(self) -> None:
        counts = kpis(self._cases)
        for key, label in self._kpi_values.items():
            label.setText(str(counts.get(key, 0)))

    def _filtered(self) -> list[GstCase]:
        status = self._status_filter.currentText() if hasattr(self, "_status_filter") else "All"
        search = self._search.text() if hasattr(self, "_search") else ""
        return filter_cases(self._cases, search, "" if status == "All" else status)

    def _render_list(self) -> None:
        cases = self._filtered()
        self._table.setRowCount(0)
        self._row_cases = {}
        for row, case in enumerate(cases):
            self._table.insertRow(row)
            values = (
                case.client_name,
                case.notice_type or "Notice",
                case.ref_id,
                case.issued,
                case.due,
                case.status,
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value or "")
                item.setToolTip(value or "")
                if col == 5:
                    item.setForeground(self._status_color(case.status))
                self._table.setItem(row, col, item)
            self._row_cases[row] = case
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)

        if self._selected_id in {case.id for case in cases}:
            self._select_row_for_case(self._selected_id)
        elif cases:
            self._selected_id = cases[0].id
            self._select_row_for_case(self._selected_id)
        else:
            self._selected_id = ""
            self._render_detail()

    def _status_color(self, status: str) -> QColor:
        t = _t()
        return {
            "Open": QColor(t.accent_it),
            "Overdue": QColor(t.error),
            "Replied": QColor(t.success),
            "Closed": QColor(t.text_muted),
        }.get(status, QColor(t.text_primary))

    def _select_row_for_case(self, case_id: str) -> None:
        for row, case in self._row_cases.items():
            if case.id == case_id:
                self._table.blockSignals(True)
                self._table.selectRow(row)
                self._table.blockSignals(False)
                self._selected_id = case_id
                self._render_detail()
                return

    def _on_selection(self) -> None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if not rows:
            return
        case = self._row_cases.get(min(rows))
        if case is not None:
            self._selected_id = case.id
            self._render_detail()

    def _selected_case(self) -> GstCase | None:
        return self._case_by_id.get(self._selected_id)

    def _render_detail(self) -> None:
        case = self._selected_case()
        self._files.clear()
        if case is None:
            self._detail_title.setText("No GST notices downloaded yet")
            self._detail_meta.setText(
                "Use GST ▸ Download Documents to fetch notices and orders, or "
                "enable GST in the auto-fetch settings.")
            self._detail_body.setText("")
            return
        self._detail_title.setText(f"{case.title} — {case.client_name}")
        meta_bits = []
        if case.gstin:
            meta_bits.append(f"GSTIN: {case.gstin}")
        if case.trade_name:
            meta_bits.append(f"Trade name: {case.trade_name}")
        if case.ref_id:
            meta_bits.append(f"Reference: {case.ref_id}")
        if case.issued:
            meta_bits.append(f"Issued: {case.issued}")
        if case.due:
            meta_bits.append(f"Due: {case.due}")
        meta_bits.append(f"Status: {case.status}")
        if case.raw_status and case.raw_status != case.status:
            meta_bits.append(f"Portal status: {case.raw_status}")
        if amount_value(case):
            meta_bits.append(f"Amount: ₹{case.amount}")
        if case.doc_id:
            meta_bits.append(f"Document ID: {case.doc_id}")
        if case.case_id:
            meta_bits.append(f"Case ID: {case.case_id}")
        if case.order_id:
            meta_bits.append(f"Order ID: {case.order_id}")
        if case.reply_id:
            meta_bits.append(f"Reply ID: {case.reply_id}")
        self._detail_meta.setText("  ·  ".join(meta_bits))
        body = case.description or "No description shown by the portal."
        self._detail_body.setText(body)

        for doc in case.docs:
            for rel in doc.files:
                item = QListWidgetItem(f"[{doc.kind.title()}] {os.path.basename(rel)}")
                item.setData(Qt.ItemDataRole.UserRole, os.path.join(case.root, rel))
                item.setToolTip(os.path.join(case.root, rel))
                self._files.addItem(item)
        if self._files.count() == 0:
            self._files.addItem("No attachments were downloaded for this record.")

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_selected_file(self) -> None:
        item = self._files.currentItem()
        if item is not None:
            self._open_item(item)

    def _open_case_folder(self) -> None:
        case = self._selected_case()
        if case and os.path.isdir(case.root):
            QDesktopServices.openUrl(QUrl.fromLocalFile(case.root))

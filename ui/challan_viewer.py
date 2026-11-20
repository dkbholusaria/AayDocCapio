"""
ui/challan_viewer.py
====================
Read-only browser for challans already saved on disk (F-12).

The E-Pay Tax flows save generated (unpaid/payable) and downloaded (paid)
challans under the client/year folder, but until now there was no way back to
them without running a download or generation again. This dialog lists those
files, filters them by client / status / year, and opens the file or its
folder. It never logs in to the portal and never changes anything on disk.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from automation.challan_index import (
    format_size,
    format_timestamp,
    scan_saved_challans,
)
from config import _open_path
from themes import MONO_FONT_NAME as _MONO_FONT
from ui._theme import _t
from ui.helpers import _btn, _lbl


class ViewChallansDialog(QDialog):
    """Browse saved challans: filter by client, Paid/Unpaid, and year."""

    COLUMNS = ("Client", "Year", "Status", "Type", "File", "Date", "Size")

    def __init__(self, parent, root_dir: str, clients=None):
        super().__init__(parent)
        self._root_dir = root_dir or ""
        self._clients = clients or []
        self._records: list[dict] = []
        self._row_records: list[dict] = []

        self.setWindowTitle("View Challans")
        self.setMinimumSize(920, 560)
        self._build_ui()
        self.refresh()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        t = _t()
        self.setStyleSheet(
            f"QDialog{{background:{t.bg_window};}}"
            f"QLabel{{color:{t.text_primary};background:transparent;}}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(9)

        head = QHBoxLayout()
        head.addWidget(_lbl("Saved Challans", 15, bold=True))
        head.addStretch(1)
        self._summary = _lbl("", 10, color=t.text_muted)
        head.addWidget(self._summary)
        outer.addLayout(head)

        sub = QLabel(
            "Challans already generated or downloaded in an earlier session. "
            "Nothing is fetched from the portal — open a saved file directly.")
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color:{t.text_muted};font-size:11px;background:transparent;")
        outer.addWidget(sub)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        filters.addWidget(_lbl("Client", 10, color=t.text_muted))
        self._client_combo = QComboBox()
        self._client_combo.setMinimumWidth(220)
        self._client_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self._client_combo)

        filters.addSpacing(6)
        filters.addWidget(_lbl("Status", 10, color=t.text_muted))
        self._status_combo = QComboBox()
        self._status_combo.addItem("All challans", "")
        self._status_combo.addItem("Paid", "Paid")
        self._status_combo.addItem("Unpaid (Payable)", "Unpaid")
        self._status_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self._status_combo)

        filters.addSpacing(6)
        filters.addWidget(_lbl("Year", 10, color=t.text_muted))
        self._year_combo = QComboBox()
        self._year_combo.setMinimumWidth(120)
        self._year_combo.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self._year_combo)

        filters.addSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search file, CRN, client…")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(180)
        self._search.textChanged.connect(self._apply_filters)
        filters.addWidget(self._search, 1)
        outer.addLayout(filters)

        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setStyleSheet(
            f"QTableWidget{{border:1px solid {t.border};border-radius:8px;"
            f"background:{t.bg_table};outline:0;gridline-color:{t.grid};}}"
            f"QTableWidget::item{{border-bottom:1px solid {t.grid};padding:0 8px;}}"
            f"QTableWidget::item:selected{{background:{t.accent};color:{t.accent_text};}}")
        header = self._table.horizontalHeader()
        header.setStyleSheet(
            f"QHeaderView::section{{background-color:{t.bg_header};border:none;"
            f"border-right:1px solid {t.border};border-bottom:1px solid {t.border};"
            f"font-weight:bold;color:{t.text_muted};font-size:10px;height:32px;"
            f"padding:0 8px;}}")
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(lambda _idx: self._open_file())
        self._table.itemSelectionChanged.connect(self._update_actions)
        outer.addWidget(self._table, 1)

        self._empty = QLabel("")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(
            f"color:{t.text_muted};font-size:12px;background:{t.bg_panel};"
            f"border:1px dashed {t.border};border-radius:8px;padding:24px;")
        self._empty.hide()
        outer.addWidget(self._empty, 1)

        footer = QHBoxLayout()
        footer.addWidget(_lbl(f"From: {self._root_dir}", 10, color=t.text_muted))
        footer.addStretch(1)
        self._refresh_btn = _btn("Refresh", "outline", height=30, min_width=80)
        self._refresh_btn.clicked.connect(self.refresh)
        self._open_file_btn = _btn("Open File", "secondary", height=30, min_width=90)
        self._open_file_btn.clicked.connect(self._open_file)
        self._open_folder_btn = _btn("Open Folder", "secondary", height=30, min_width=100)
        self._open_folder_btn.clicked.connect(self._open_folder)
        close_btn = _btn("Close", "primary", height=30, min_width=80)
        close_btn.clicked.connect(self.accept)
        for b in (self._refresh_btn, self._open_file_btn,
                  self._open_folder_btn, close_btn):
            footer.addWidget(b)
        outer.addLayout(footer)
        self._update_actions()

    # ── Data ──────────────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Rescan the download folder and rebuild the filter choices."""
        client_filter = self._client_combo.currentData()
        status_filter = self._status_combo.currentData()
        year_filter = self._year_combo.currentData()

        self._records = scan_saved_challans(self._root_dir, self._clients)
        self._rebuild_filters(client_filter, status_filter, year_filter)
        self._apply_filters()

    def _rebuild_filters(self, client_filter, status_filter, year_filter) -> None:
        self._client_combo.blockSignals(True)
        self._year_combo.blockSignals(True)
        self._status_combo.blockSignals(True)
        try:
            self._client_combo.clear()
            self._client_combo.addItem("All clients", "")
            seen_ids: set[str] = set()
            for rec in self._records:
                cid = rec["client_id"] or rec["client_label"]
                if not cid or cid in seen_ids:
                    continue
                seen_ids.add(cid)
                label = cid
                if rec["client_name"]:
                    label = f"{cid} — {rec['client_name']}"
                self._client_combo.addItem(label, cid)
            self._restore_combo(self._client_combo, client_filter)

            self._year_combo.clear()
            self._year_combo.addItem("All years", "")
            for year in sorted({r["year"] for r in self._records if r["year"]},
                               reverse=True):
                self._year_combo.addItem(year, year)
            self._restore_combo(self._year_combo, year_filter)

            self._restore_combo(self._status_combo, status_filter)
        finally:
            self._client_combo.blockSignals(False)
            self._year_combo.blockSignals(False)
            self._status_combo.blockSignals(False)

    @staticmethod
    def _restore_combo(combo: QComboBox, value) -> None:
        idx = combo.findData(value) if value not in (None, "") else 0
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    @staticmethod
    def _matches_search(rec: dict, needle: str) -> bool:
        if not needle:
            return True
        haystack = " ".join(str(rec.get(k, "")) for k in (
            "client_id", "client_name", "year", "status", "doc_type",
            "payment_type", "filename"))
        return needle in haystack.casefold()

    def _filtered_records(self) -> list[dict]:
        client_id = self._client_combo.currentData() or ""
        status = self._status_combo.currentData() or ""
        year = self._year_combo.currentData() or ""
        needle = self._search.text().strip().casefold()
        return [
            r for r in self._records
            if (not client_id
                or r["client_id"] == client_id
                or r["client_label"] == client_id)
            and (not status or r["status"] == status)
            and (not year or r["year"] == year)
            and self._matches_search(r, needle)
        ]

    def _apply_filters(self) -> None:
        t = _t()
        rows = self._filtered_records()
        self._row_records = rows

        self._table.setRowCount(len(rows))
        for row, rec in enumerate(rows):
            client_text = rec["client_id"] or rec["client_label"]
            if rec["client_name"]:
                client_text = f"{client_text} — {rec['client_name']}"
            type_text = rec["doc_type"]
            if rec["payment_type"] and rec["payment_type"] != rec["doc_type"]:
                type_text = f"{type_text} — {rec['payment_type']}"

            values = (
                client_text,
                rec["year"],
                rec["status"],
                type_text,
                rec["filename"],
                format_timestamp(rec["mtime"]),
                format_size(rec["size"]),
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(rec["path"])
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, rec["path"])
                if col in (0, 2, 4):
                    font = QFont()
                    if col == 0:
                        font.setBold(True)
                    if col in (0, 4):
                        font.setFamily(_MONO_FONT)
                    item.setFont(font)
                if col == 2:
                    color = t.success if rec["status"] == "Paid" else t.warning
                    item.setForeground(QColor(color))
                self._table.setItem(row, col, item)
            self._table.setRowHeight(row, 30)

        self._table.setVisible(bool(rows))
        self._empty.setVisible(not rows)
        if not rows:
            if not self._records:
                self._empty.setText(
                    "No saved challans found in this folder yet.\n\n"
                    "Generate or download a challan first — it will appear here "
                    "next time without needing to fetch it again.")
            else:
                self._empty.setText(
                    "No challans match the selected filters.\n\n"
                    "Try a different client, status, or year.")
        self._update_summary(rows)
        self._update_actions()

    def _update_summary(self, rows: list[dict]) -> None:
        n = len(rows)
        clients = len({r["client_id"] or r["client_label"] for r in rows})
        unpaid = sum(1 for r in rows if r["status"] == "Unpaid")
        size = format_size(sum(r["size"] for r in rows))
        parts = [f"{n} challan{'s' if n != 1 else ''}",
                 f"{clients} client{'s' if clients != 1 else ''}"]
        if unpaid:
            parts.append(f"{unpaid} unpaid")
        if size:
            parts.append(size)
        self._summary.setText(" • ".join(parts))

    # ── Actions ───────────────────────────────────────────────────────────
    def _selected_record(self) -> dict | None:
        row = self._table.currentRow()
        if 0 <= row < len(self._row_records):
            return self._row_records[row]
        return None

    def _update_actions(self) -> None:
        has_rows = self._table.rowCount() > 0 and self._table.currentRow() >= 0
        self._open_file_btn.setEnabled(has_rows)
        self._open_folder_btn.setEnabled(has_rows)

    def _open_file(self) -> None:
        rec = self._selected_record()
        if rec:
            _open_path(rec["path"])

    def _open_folder(self) -> None:
        rec = self._selected_record()
        if rec:
            _open_path(rec["folder"])


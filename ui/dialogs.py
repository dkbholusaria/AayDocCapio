import sys, os, json, datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QRadioButton, QLineEdit, QScrollArea, QWidget,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QProgressBar, QSizePolicy, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from ui._theme import _t
from ui.helpers import _btn, _lbl, _status_style, _UI_FONT
from config import _open_path
from themes import MONO_FONT_NAME as _MONO_FONT


# ── Manage Years Dialog ───────────────────────────────────────────────────────

class ManageYearsDialog(QDialog):
    def __init__(self, parent, json_path: str, on_save):
        super().__init__(parent)
        self.setWindowTitle("Manage Assessment / Tax Years")
        self.setFixedSize(500, 560)
        self.setModal(True)
        self._json_path = json_path
        self._on_save = on_save
        self._checkboxes = []

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

        self._build_ui(entries)

    def _build_ui(self, entries):
        t = _t()
        self.setStyleSheet(
            f"QDialog{{background:{t.bg_window};}}"
            f"QLabel{{color:{t.text_primary};background:transparent;}}"
            f"QRadioButton{{color:{t.text_primary};background:transparent;spacing:6px;}}"
            f"QRadioButton::indicator{{width:14px;height:14px;border:1.5px solid {t.border};"
            f"border-radius:7px;background:{t.bg_checkbox};}}"
            f"QRadioButton::indicator:checked{{background:{t.accent};border-color:{t.accent};}}"
            f"QScrollArea{{background:{t.bg_input};border:1px solid {t.border};border-radius:6px;}}"
            f"QScrollArea > QWidget > QWidget{{background:{t.bg_input};}}"
        )
        main = QVBoxLayout(self)
        main.setContentsMargins(20, 16, 20, 16)
        main.setSpacing(8)

        main.addWidget(_lbl("Manage Assessment / Tax Years", 13, bold=True))
        main.addWidget(_lbl("Toggle enabled/disabled or add new years.", 10, color=t.text_muted))
        main.addWidget(_lbl("Existing Entries", 11, bold=True, color=t.text_muted))

        scroll = QScrollArea()
        scroll.setFixedHeight(180)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        inner.setStyleSheet(f"QWidget{{background:{t.bg_input};}}")
        self._list_layout = QVBoxLayout(inner)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        scroll.setWidget(inner)
        main.addWidget(scroll)

        for e in entries:
            self._add_row(e)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background:{t.border};border:none;max-height:1px;")
        main.addWidget(sep)

        main.addWidget(_lbl("Add New Year", 11, bold=True, color=t.text_muted))

        type_row = QHBoxLayout()
        type_row.addWidget(_lbl("Type:", 11))
        self._type_ay = QRadioButton("AY (Assessment Year)"); self._type_ay.setChecked(True)
        self._type_ty = QRadioButton("TY (Tax Year)")
        self._type_ay.toggled.connect(self._auto_fy)
        type_row.addWidget(self._type_ay); type_row.addWidget(self._type_ty)
        type_row.addStretch(); main.addLayout(type_row)

        yr_row = QHBoxLayout()
        yr_row.addWidget(_lbl("Year:", 11))
        self._year_edit = QLineEdit(); self._year_edit.setPlaceholderText("e.g. 2027-28")
        self._year_edit.setFixedWidth(120); self._year_edit.textChanged.connect(self._auto_fy)
        yr_row.addWidget(self._year_edit)
        yr_row.addWidget(_lbl("FY:", 11))
        self._fy_edit = QLineEdit(); self._fy_edit.setPlaceholderText("auto-filled")
        self._fy_edit.setFixedWidth(120)
        yr_row.addWidget(self._fy_edit)
        yr_row.addWidget(_lbl("(editable)", 10, color=t.text_muted))
        yr_row.addStretch(); main.addLayout(yr_row)

        add_btn = _btn("＋ Add to List", "outline", height=32, min_width=130)
        add_btn.clicked.connect(self._add_entry)
        main.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background:{t.border};border:none;max-height:1px;")
        main.addWidget(sep2)

        btns_row = QHBoxLayout()
        save_btn = _btn("💾 Save & Close", "primary", height=36)
        save_btn.clicked.connect(self._save)
        cancel_btn = _btn("Cancel", "secondary", height=36)
        cancel_btn.clicked.connect(self.reject)
        btns_row.addWidget(save_btn); btns_row.addWidget(cancel_btn)
        main.addLayout(btns_row)

    def _add_row(self, entry):
        t = _t()
        cb = QCheckBox(entry["label"])
        cb.setChecked(entry.get("enabled", True))
        cb.setStyleSheet(
            f"QCheckBox{{color:{t.text_primary};background:transparent;spacing:6px;}}"
            f"QCheckBox::indicator{{width:15px;height:15px;border:1.5px solid {t.border};"
            f"border-radius:3px;background:{t.bg_checkbox};}}"
            f"QCheckBox::indicator:checked{{background:{t.accent};border-color:{t.accent};}}"
        )
        self._checkboxes.append((entry, cb))
        self._list_layout.insertWidget(self._list_layout.count() - 1, cb)

    def _auto_fy(self):
        import re
        year = self._year_edit.text().strip()
        m = re.match(r"(\d{4})-(\d{2}|\d{4})$", year)
        if not m:
            return
        y1 = int(m.group(1)); suffix = m.group(2)
        y2 = int(str(y1)[:2] + suffix) if len(suffix) == 2 else int(suffix)
        fy = f"{y1}-{str(y2)[-2:]}" if self._type_ty.isChecked() else f"{y1-1}-{str(y2-1)[-2:]}"
        self._fy_edit.setText(fy)

    def _add_entry(self):
        year_type = "TY" if self._type_ty.isChecked() else "AY"
        year = self._year_edit.text().strip()
        fy = self._fy_edit.text().strip()
        if not year or not fy:
            QMessageBox.warning(self, "Missing Fields", "Please fill in Year and FY.")
            return
        label = f"{year_type} {year} (FY {fy})"
        if any(e["label"] == label for e, _ in self._checkboxes):
            QMessageBox.warning(self, "Duplicate", f'"{label}" already exists.')
            return
        year_obj = {"TY": year, "FY": fy} if year_type == "TY" else {"AY": year, "FY": fy}
        self._add_row({"label": label, "enabled": True, "year": year_obj})
        self._year_edit.clear(); self._fy_edit.clear()

    def _save(self):
        final = [{**e, "enabled": cb.isChecked()} for e, cb in self._checkboxes]
        def _sort_key(e):
            y = e.get("year", {})
            label_year = y.get("AY") or y.get("TY") or y.get("FY") or "0000-00"
            try:
                return (0 if not e.get("enabled", True) else 1, -int(label_year[:4]))
            except ValueError:
                return (1, 0)
        final.sort(key=_sort_key)
        try:
            with open(self._json_path, "w", encoding="utf-8") as f:
                json.dump(final, f, indent=2, ensure_ascii=False)
            self._on_save()
            self.accept()
        except Exception as ex:
            QMessageBox.critical(self, "Save Error", str(ex))


# ── Batch Progress Dialog ─────────────────────────────────────────────────────

class BatchProgressDialog(QDialog):
    """
    Live progress popup shown during any batch run.
    Columns: Name | PAN | Status | Save Path (clickable link)
    Status and path updates arrive from the worker thread via Qt signals.
    """
    _update_signal = pyqtSignal(str, str)
    _path_signal   = pyqtSignal(str, str)
    _resume_signal = pyqtSignal(list)

    _COL_NAME   = 0
    _COL_PAN    = 1
    _COL_STATUS = 2
    _COL_PATH   = 3

    def __init__(self, targets: list, mode: str, ay: str = "",
                 stop_callback=None, resume_callback=None,
                 output_dir: str = "", parent=None):
        super().__init__(parent)
        self._stop_callback   = stop_callback
        self._resume_callback = resume_callback
        self._output_dir      = output_dir
        self._mode            = mode
        self._ay              = ay
        self._targets         = targets
        self._pan_to_path     = {}

        mode_label = {
            "26as":        "Downloading 26AS",
            "request_ais": "Requesting AIS Generation",
            "ais_tis":     "Downloading AIS / TIS",
        }.get(mode, "Batch Run")
        self._mode_label = mode_label

        self.setWindowTitle(f"{mode_label} — Batch Progress")
        self.setMinimumSize(900, 500)
        self.resize(1060, min(160 + len(targets) * 42, 720))
        self.setSizeGripEnabled(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint)
        _bt = _t()
        self.setStyleSheet(f"QDialog{{background:{_bt.bg_window};}}")

        self._pan_to_row = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        # ── Title bar ─────────────────────────────────────────────────────────
        ay_tag = (f" &nbsp;·&nbsp; <span style='color:{_bt.accent}'>{ay}</span>") if ay else ""
        title = QLabel(f"<b>{mode_label}</b> — {len(targets)} client(s){ay_tag}")
        title.setStyleSheet(f"font-size:14px; color:{_bt.text_primary}; background:transparent;")
        layout.addWidget(title)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget(len(targets), 4)
        self._table.setHorizontalHeaderLabels(["Name", "PAN", "Status", "Save Path"])

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(self._COL_NAME,   QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(self._COL_PAN,    QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(self._COL_STATUS, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(self._COL_PATH,   QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(self._COL_NAME,   180)
        self._table.setColumnWidth(self._COL_PAN,    120)
        self._table.setColumnWidth(self._COL_STATUS, 260)

        hdr.setStyleSheet(
            f"QHeaderView::section{{"
            f"background-color:{_bt.bg_header};"
            f"border:none;"
            f"border-right:1px solid {_bt.border};"
            f"border-bottom:1px solid {_bt.border};"
            f"font-weight:bold;color:{_bt.text_muted};"
            f"font-size:11px;height:34px;"
            f"padding:0 8px;}}")
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.setWordWrap(False)
        self._table.setStyleSheet(
            f"QTableWidget{{border:1.5px solid {_bt.border};border-radius:8px;"
            f"background:{_bt.bg_table};outline:0;gridline-color:{_bt.grid};}}"
            f"QTableWidget::item{{border-bottom:1px solid {_bt.grid};padding:0 8px;}}"
            f"QPushButton{{border:none;background:transparent;font-size:14px;}}"
            f"QPushButton:hover{{background:{_bt.bg_table_alt};border-radius:4px;}}")
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        for row, tgt in enumerate(targets):
            pan  = tgt.get("pan", "")
            name = tgt.get("name", "—")
            self._pan_to_row[pan] = row
            self._table.setRowHeight(row, 40)

            name_item = QTableWidgetItem(name)
            name_item.setForeground(QColor(_bt.text_primary))
            self._table.setItem(row, self._COL_NAME, name_item)

            pan_item = QTableWidgetItem(pan)
            pan_item.setForeground(QColor(_bt.text_muted))
            pan_item.setFont(QFont(_MONO_FONT, 10))
            pan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, self._COL_PAN, pan_item)

            self._set_status_item(row, "⬜ Waiting")

            path_lbl = QLabel("—")
            path_lbl.setStyleSheet(
                f"color:{_bt.text_muted};font-size:11px;padding:0 8px;background:transparent;")
            path_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            path_lbl.setWordWrap(False)
            path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            path_lbl.setOpenExternalLinks(False)
            path_lbl.linkActivated.connect(lambda url: _open_path(url))
            self._table.setCellWidget(row, self._COL_PATH, path_lbl)

        layout.addWidget(self._table, stretch=1)

        # ── Progress bar ──────────────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, len(targets))
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(18)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat(f"0 / {len(targets)} done")
        self._progress_bar.setStyleSheet(
            f"QProgressBar{{border:1px solid {_bt.border};border-radius:9px;"
            f"background:{_bt.scrollbar_handle};text-align:center;font-size:11px;"
            f"font-weight:600;color:{_bt.accent_text};}}"
            f"QProgressBar::chunk{{background:#16A34A;border-radius:9px;}}")
        layout.addWidget(self._progress_bar)

        # ── Footer ────────────────────────────────────────────────────────────
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.setContentsMargins(0, 0, 0, 0)

        loc_cap = QLabel("📁")
        loc_cap.setStyleSheet("font-size:13px;background:transparent;")
        loc_cap.setFixedWidth(18)
        footer.addWidget(loc_cap)

        self._loc_val = QLabel(output_dir or "—")
        self._loc_val.setStyleSheet(f"color:{_bt.text_muted};font-size:11px;background:transparent;")
        self._loc_val.setWordWrap(False)
        self._loc_val.setMinimumWidth(0)
        self._loc_val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._loc_val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        footer.addWidget(self._loc_val, stretch=1)

        self._open_folder_btn = QPushButton("📂  Open Folder")
        self._open_folder_btn.setFixedHeight(32)
        self._open_folder_btn.setStyleSheet(
            f"QPushButton{{background:{_bt.bg_table_alt};color:{_bt.text_primary};border:1px solid {_bt.border};"
            f"border-radius:6px;font-size:12px;padding:0 12px;}}"
            f"QPushButton:hover{{background:{_bt.bg_input};}}"
            f"QPushButton:disabled{{color:{_bt.text_muted};border-color:{_bt.border};}}")
        self._open_folder_btn.clicked.connect(lambda: _open_path(self._output_dir))
        footer.addWidget(self._open_folder_btn)

        self._report_btn = QPushButton("⬇  Download Report")
        self._report_btn.setFixedHeight(32)
        self._report_btn.setEnabled(False)
        self._report_btn.setStyleSheet(
            f"QPushButton{{background:{_bt.bg_table_alt};color:{_bt.text_primary};border:1px solid {_bt.border};"
            f"border-radius:6px;font-size:12px;padding:0 12px;}}"
            f"QPushButton:enabled:hover{{background:{_bt.bg_input};}}"
            f"QPushButton:disabled{{color:{_bt.text_muted};border-color:{_bt.border};}}")
        self._report_btn.clicked.connect(self._export_report)
        footer.addWidget(self._report_btn)

        self._stop_btn = QPushButton("⏹  Stop")
        self._stop_btn.setFixedHeight(32)
        self._stop_btn.setMinimumWidth(90)
        self._stop_btn.setStyleSheet(
            "QPushButton{background:#EF4444;color:#FFFFFF;border:none;"
            "border-radius:6px;font-size:12px;font-weight:600;padding:0 12px;}"
            "QPushButton:hover{background:#DC2626;}"
            "QPushButton:disabled{background:#E2E8F0;color:#94A3B8;}")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        footer.addWidget(self._stop_btn)

        self._resume_btn = QPushButton("▶  Resume")
        self._resume_btn.setFixedHeight(32)
        self._resume_btn.setMinimumWidth(100)
        self._resume_btn.setVisible(False)
        self._resume_btn.setStyleSheet(
            "QPushButton{background:#16A34A;color:#FFFFFF;border:none;"
            "border-radius:6px;font-size:12px;font-weight:600;padding:0 12px;}"
            "QPushButton:hover{background:#15803D;}")
        self._resume_btn.clicked.connect(self._on_resume_clicked)
        footer.addWidget(self._resume_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.setFixedSize(80, 32)
        self._close_btn.setEnabled(False)
        self._close_btn.setStyleSheet(
            f"QPushButton{{background:{_bt.border};color:{_bt.text_muted};border:none;"
            f"border-radius:6px;font-size:12px;}}"
            f"QPushButton:enabled{{background:{_bt.accent};color:{_bt.accent_text};}}"
            f"QPushButton:enabled:hover{{background:{_bt.accent_hover};}}")
        self._close_btn.clicked.connect(self.accept)
        footer.addWidget(self._close_btn)

        layout.addLayout(footer)

        self._done_count = 0
        self._total      = len(targets)
        self._rows_data  = {}

        for tgt in targets:
            self._rows_data[tgt.get("pan", "")] = {
                "name": tgt.get("name", ""), "path": "", "status": "Waiting", "ts": ""}

        self._update_signal.connect(self._on_update)
        self._path_signal.connect(self._on_path_update)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _set_status_item(self, row: int, text: str):
        _bt = _t()
        _, light_fg, dark_fg = _status_style(text)
        fg = dark_fg if getattr(_bt, "name", "").lower() != "light" else light_fg
        item = QTableWidgetItem(text)
        item.setForeground(QColor(fg))
        item.setFont(QFont(_UI_FONT, 10))
        item.setToolTip(text)
        self._table.setItem(row, self._COL_STATUS, item)

    def _on_update(self, pan: str, status: str):
        row = self._pan_to_row.get(pan)
        if row is None:
            return
        self._set_status_item(row, status)
        if pan in self._rows_data:
            self._rows_data[pan]["status"] = status
            self._rows_data[pan]["ts"] = datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S")
        terminal = ("✅", "❌", "🕐", "⬜", "⏹")
        if any(status.startswith(p) for p in terminal):
            self._done_count += 1
            self._progress_bar.setValue(self._done_count)
            self._progress_bar.setFormat(f"{self._done_count} / {self._total} done")
        if self._done_count >= self._total:
            self._close_btn.setEnabled(True)
            self._report_btn.setEnabled(True)
            self._progress_bar.setFormat(f"All {self._total} done")

    def _on_path_update(self, pan: str, folder: str):
        row = self._pan_to_row.get(pan)
        if row is None:
            return
        self._pan_to_path[pan] = folder
        if pan in self._rows_data:
            self._rows_data[pan]["path"] = folder
        lbl = self._table.cellWidget(row, self._COL_PATH)
        if isinstance(lbl, QLabel):
            lbl.setText(
                f'<a href="{folder}" style="color:#2563EB;text-decoration:underline;">'
                f'{folder}</a>')
            lbl.setToolTip(folder)
            lbl.setStyleSheet("font-size:11px;padding:0 8px;background:transparent;")

    def _on_stop_clicked(self):
        if self._stop_callback:
            self._stop_callback()
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("⏹  Stopping...")

    # ── Excel report ──────────────────────────────────────────────────────────

    def _export_report(self):
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"BatchReport_{self._ay.replace(' ','_')}_{timestamp}.xlsx"
        default_path = os.path.join(self._output_dir or os.path.expanduser("~"), default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Download Report", default_path, "Excel Files (*.xlsx)")
        if not path:
            return

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Download Report"

        hdr_fill  = PatternFill("solid", fgColor="0F172A")
        hdr_font  = Font(bold=True, color="FFFFFF", size=11)
        link_font = Font(color="2563EB", underline="single", size=10)
        body_font = Font(size=10)
        center    = Alignment(horizontal="center", vertical="center")
        left      = Alignment(horizontal="left",   vertical="center", wrap_text=False)
        thin      = Side(style="thin", color="CBD5E1")
        border    = Border(left=thin, right=thin, top=thin, bottom=thin)

        headers    = ["#", "Client Name", "Save Folder", "Status", "Timestamp"]
        col_widths = [5, 30, 60, 40, 22]

        for col_idx, (h, w) in enumerate(zip(headers, col_widths), start=1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font      = hdr_font
            cell.fill      = hdr_fill
            cell.alignment = center
            cell.border    = border
            ws.column_dimensions[get_column_letter(col_idx)].width = w

        ws.row_dimensions[1].height = 22

        for seq, tgt in enumerate(self._targets, start=1):
            pan     = tgt.get("pan", "")
            data    = self._rows_data.get(pan, {})
            row_num = seq + 1
            folder  = data.get("path", "")
            status  = data.get("status", "—")
            name    = data.get("name", tgt.get("name", ""))
            row_ts  = data.get("ts", "")

            ws.cell(row=row_num, column=1, value=seq).alignment = center
            ws.cell(row=row_num, column=2, value=name).alignment = left

            if folder and os.path.exists(folder):
                cell = ws.cell(row=row_num, column=3, value=folder)
                cell.hyperlink = folder
                cell.font      = link_font
                cell.alignment = left
            else:
                ws.cell(row=row_num, column=3, value=folder or "—").alignment = left

            import re as _re
            status_clean = _re.sub(r'[^\x00-\x7F✅❌🕐⬜⏹⏳]+', '', status).strip()
            ws.cell(row=row_num, column=4, value=status_clean).alignment = left
            ws.cell(row=row_num, column=5, value=row_ts or "—").alignment = center

            for col_idx in range(1, 6):
                cell = ws.cell(row=row_num, column=col_idx)
                cell.border = border
                if not cell.font or cell.font == Font():
                    cell.font = body_font
            ws.row_dimensions[row_num].height = 18

        ws.freeze_panes = "A2"

        try:
            wb.save(path)
            _open_path(path)
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    # ── public API ────────────────────────────────────────────────────────────

    def set_status(self, pan: str, status: str):
        """Thread-safe status update."""
        self._update_signal.emit(pan, status)

    def set_client_path(self, pan: str, folder: str):
        """Thread-safe path update — call once the client folder is known."""
        self._path_signal.emit(pan, folder)

    def batch_finished(self, aborted: bool = False):
        """Enable Close/Report and hide Stop. If aborted, sweeps non-terminal rows to ⏹ Stopped."""
        terminal = ("✅", "❌", "🕐", "⏹", "⬜ Skipped")
        if aborted:
            for pan, row in self._pan_to_row.items():
                item = self._table.item(row, self._COL_STATUS)
                current = item.text() if item else ""
                if not any(current.startswith(t) for t in terminal):
                    self._set_status_item(row, "⏹ Stopped")
                    if pan in self._rows_data:
                        self._rows_data[pan]["status"] = "⏹ Stopped"
        self._stop_btn.setVisible(False)
        self._resume_btn.setVisible(aborted)
        self._close_btn.setEnabled(True)
        self._report_btn.setEnabled(True)
        n = self._done_count
        self._progress_bar.setValue(n)
        label = "Stopped" if aborted else "All done"
        self._progress_bar.setFormat(f"{label} — {n} / {self._total} processed")

    def batch_resumed(self):
        """Reset UI back to running state after Resume is clicked."""
        self._resume_btn.setVisible(False)
        self._stop_btn.setText("⏹  Stop")
        self._stop_btn.setEnabled(True)
        self._stop_btn.setVisible(True)
        self._close_btn.setEnabled(False)
        self._report_btn.setEnabled(False)
        self._progress_bar.setFormat(f"{self._done_count} / {self._total} done")

    def _on_resume_clicked(self):
        remaining = []
        for tgt in self._targets:
            pan = tgt.get("pan", "")
            status = (self._rows_data.get(pan) or {}).get("status", "")
            if status.startswith("⏹"):
                remaining.append(tgt)
                row = self._pan_to_row.get(pan)
                if row is not None:
                    self._set_status_item(row, "⬜ Waiting")
                    self._rows_data[pan]["status"] = "⬜ Waiting"
        if remaining and self._resume_callback:
            self._resume_callback(remaining)

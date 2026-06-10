"""
app_qt.py — PyQt6 port of AayDocCapio
Install: pip install PyQt6
Run:     python3 app_qt.py
"""
import sys, os, json, asyncio, threading, datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QFileDialog, QScrollArea,
    QTabWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QMessageBox, QTextEdit, QDialog, QRadioButton, QSplitter, QSizePolicy,
    QGraphicsDropShadowEffect, QListView, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QToolButton, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMetaObject, Q_ARG, QModelIndex
from PyQt6.QtGui import QFont, QTextCursor, QColor, QRegularExpressionValidator, QPalette, QAction, QIcon, QPixmap
from PyQt6.QtCore import QRegularExpression

def _app_dir() -> str:
    """
    Writable user-data directory for vault, settings, and outputs.
    - Windows compiled .exe : %LOCALAPPDATA%\\AayDocCapio
    - Linux/WSL compiled    : ~/.local/share/AayDocCapio
    - Running as script     : folder containing app.py
    """
    # sys.frozen = PyInstaller; __compiled__ = Nuitka
    if getattr(sys, "frozen", False) or globals().get("__compiled__"):
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        else:
            base = os.path.join(os.path.expanduser("~"), ".local", "share")
        data_dir = os.path.join(base, "AayDocCapio")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    return os.path.dirname(os.path.abspath(__file__))


def _bundled_dir() -> str:
    """
    Directory for read-only assets bundled inside the .exe.
    PyInstaller uses _MEIPASS; Nuitka uses the exe directory.
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    if globals().get("__compiled__"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


sys.path.append(_bundled_dir())
from vault import VaultManager
from automation.browser import browser_manager
from automation.auth import login_itd, logout_itd
from automation.downloader_26as import download_26as
from automation.downloader_ais_tis import run_request_ais, run_download_ais_tis


class _HoverDelegate(QStyledItemDelegate):
    """Paints hover highlight without relying on QSS :hover pseudo-state."""
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)

    def paint(self, painter, option, index):
        from PyQt6.QtWidgets import QStyle
        painter.save()
        is_hover   = bool(option.state & QStyle.StateFlag.State_MouseOver)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if is_selected or is_hover:
            painter.fillRect(option.rect, QColor("#DBEAFE" if is_selected else "#EFF6FF"))
            painter.setPen(QColor("#1E40AF"))
        else:
            painter.fillRect(option.rect, QColor("#FFFFFF"))
            painter.setPen(QColor("#1a1a1a"))
        painter.drawText(
            option.rect.adjusted(12, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter,
            index.data())
        painter.restore()


class _ComboListView(QListView):
    """QListView that closes its parent ComboBox popup on mouse release."""
    def __init__(self, combo: 'StyledComboBox'):
        super().__init__()
        self._combo = combo
        self.setMouseTracking(True)
        self.setItemDelegate(_HoverDelegate(self))
        self.setStyleSheet(
            "QListView { border:1px solid #CBD5E1; background:#FFFFFF; outline:none; }"
            "QListView::item { padding:6px 12px; min-height:26px; }"
        )

    def mouseReleaseEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            self._combo.setCurrentIndex(index.row())
            self._combo.hidePopup()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class StyledComboBox(QComboBox):
    """QComboBox with reliable hover + click-closes behaviour."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_was_open = False
        self.setView(_ComboListView(self))

    def showPopup(self):
        self._popup_was_open = True
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        # Keep flag set for one event cycle so row click guard can read it
        QTimer.singleShot(150, self._clear_popup_flag)

    def _clear_popup_flag(self):
        self._popup_was_open = False


def get_timestamp():
    import datetime
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    return now.strftime("%d-%m-%Y %H:%M:%S")


# ── Stylesheet ────────────────────────────────────────────────────────────────
APP_STYLE = """
QMainWindow, QDialog { background: #FFFFFF; }
QWidget { font-family: 'Segoe UI', 'Avenir Next', Arial, sans-serif; font-size: 13px; }
QLabel { color: #1a1a1a; font-size: 13px; }

QLineEdit {
    background: #FFFFFF;
    border: 1.5px solid #E2E8F0;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 13px;
    color: #1a1a1a;
    min-height: 28px;
    selection-background-color: #BFDBFE;
}
QLineEdit:hover { border-color: #CBD5E1; }
QLineEdit:focus { border: 1.5px solid #3B82F6; background: #FAFBFF; outline: none; }
QLineEdit:disabled { background: #F8FAFC; color: #94A3B8; border-color: #F1F5F9; }
QLineEdit::placeholder { color: #94A3B8; }

QComboBox {
    background: #FFFFFF;
    border: 1.5px solid #E2E8F0;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 13px;
    color: #1a1a1a;
    min-height: 26px;
    min-width: 120px;
}
QComboBox:hover { border-color: #CBD5E1; }
QComboBox:focus { border: 1.5px solid #3B82F6; }
QComboBox::drop-down {
    border: none;
    width: 28px;
    subcontrol-origin: padding;
    subcontrol-position: right center;
}
QComboBox::down-arrow {
    image: url(resources/chevron_down.png);
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    border: 1px solid #CBD5E1;
    background: #FFFFFF;
    outline: none;
    selection-background-color: #DBEAFE;
    selection-color: #1E40AF;
}

QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: transparent; qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent;
    color: #64748B;
    padding: 10px 18px;
    border: none;
    font-size: 13px;
    font-weight: 600;
    border-bottom: 2px solid transparent;
    margin-bottom: 0px;
}
QTabBar::tab:selected { color: #1D4ED8; border-bottom: 2px solid #2563EB; }
QTabBar::tab:hover:!selected { color: #334155; }

QCheckBox { font-size: 13px; color: #1a1a1a; spacing: 8px; background: transparent; }
QCheckBox::indicator {
    width: 17px; height: 17px;
    border: 1.5px solid #CBD5E1;
    border-radius: 4px;
    background: #FFFFFF;
}
QCheckBox::indicator:hover { border-color: #3B82F6; }
QCheckBox::indicator:checked {
    background: #2563EB;
    border-color: #2563EB;
    image: url(resources/check.png);
}
QCheckBox::indicator:disabled { background: #F1F5F9; border-color: #E2E8F0; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background: transparent; width: 6px; border-radius: 3px; margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: #CBD5E1; border-radius: 3px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QTextEdit {
    background: #0F172A;
    border: none;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
    color: #7DD3FC;
    padding: 8px 12px;
}

QToolTip {
    background: #1E293B; color: #F1F5F9;
    border: none; border-radius: 4px;
    padding: 5px 9px; font-size: 11px;
}
"""


def _shadow(blur=18, offset_y=3, alpha=22):
    e = QGraphicsDropShadowEffect()
    e.setBlurRadius(blur)
    e.setOffset(0, offset_y)
    e.setColor(QColor(0, 0, 0, alpha))
    return e


def _btn(text, style="secondary", height=36, min_width=None):
    b = QPushButton(text)
    b.setMinimumHeight(height)
    if min_width:
        b.setMinimumWidth(min_width)
    COLORS = {
        "primary":   ("#2563EB", "#1D4ED8", "white"),
        "success":   ("#16A34A", "#15803D", "white"),
        "danger":    ("#EF4444", "#DC2626", "white"),
        "secondary": ("#64748B", "#475569", "white"),
        "warning":   ("#EAB308", "#CA8A04", "white"),
        "outline":   ("transparent", "#F1F5F9", "#475569"),
        "edit":      ("#0284C7", "#0369A1", "white"),
        "delete":    ("#DC2626", "#991B1B", "white"),
    }
    bg, hov, fg = COLORS.get(style, COLORS["secondary"])
    border = "1px solid #CBD5E1" if style == "outline" else "none"
    b.setStyleSheet(
        f"QPushButton {{ background:{bg}; color:{fg}; border:{border}; "
        f"border-radius:6px; padding:6px 14px; font-weight:bold; font-size:12px; }}"
        f"QPushButton:hover {{ background:{hov}; }}"
        f"QPushButton:disabled {{ background:#CBD5E1; color:#94A3B8; }}"
    )
    return b


def _lbl(text, size=12, bold=False, color="#0F172A"):
    l = QLabel(text)
    l.setStyleSheet(f"color:{color}; font-size:{size}px;" + (" font-weight:bold;" if bold else ""))
    return l


# ── Manage Years Dialog ───────────────────────────────────────────────────────
class ManageYearsDialog(QDialog):
    def __init__(self, parent, json_path: str, on_save):
        super().__init__(parent)
        self.setWindowTitle("Manage Assessment / Tax Years")
        self.setFixedSize(500, 560)
        self.setModal(True)
        self._json_path = json_path
        self._on_save = on_save
        self._checkboxes = []  # [(entry_dict, QCheckBox)]

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

        self._build_ui(entries)

    def _build_ui(self, entries):
        main = QVBoxLayout(self)
        main.setContentsMargins(20, 16, 20, 16)
        main.setSpacing(8)

        main.addWidget(_lbl("Manage Assessment / Tax Years", 13, bold=True))
        main.addWidget(_lbl("Toggle enabled/disabled or add new years.", 10, color="#64748B"))
        main.addWidget(_lbl("Existing Entries", 11, bold=True, color="#475569"))

        scroll = QScrollArea()
        scroll.setFixedHeight(180)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._list_layout = QVBoxLayout(inner)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        scroll.setWidget(inner)
        main.addWidget(scroll)

        for e in entries:
            self._add_row(e)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#E2E8F0;"); main.addWidget(sep)

        main.addWidget(_lbl("Add New Year", 11, bold=True, color="#475569"))

        # Type radio
        type_row = QHBoxLayout()
        type_row.addWidget(_lbl("Type:", 11))
        self._type_ay = QRadioButton("AY (Assessment Year)"); self._type_ay.setChecked(True)
        self._type_ty = QRadioButton("TY (Tax Year)")
        self._type_ay.toggled.connect(self._auto_fy)
        type_row.addWidget(self._type_ay); type_row.addWidget(self._type_ty)
        type_row.addStretch(); main.addLayout(type_row)

        # Year + FY
        yr_row = QHBoxLayout()
        yr_row.addWidget(_lbl("Year:", 11))
        self._year_edit = QLineEdit(); self._year_edit.setPlaceholderText("e.g. 2027-28")
        self._year_edit.setFixedWidth(120); self._year_edit.textChanged.connect(self._auto_fy)
        yr_row.addWidget(self._year_edit)
        yr_row.addWidget(_lbl("FY:", 11))
        self._fy_edit = QLineEdit(); self._fy_edit.setPlaceholderText("auto-filled")
        self._fy_edit.setFixedWidth(120)
        yr_row.addWidget(self._fy_edit)
        yr_row.addWidget(_lbl("(editable)", 10, color="#94A3B8"))
        yr_row.addStretch(); main.addLayout(yr_row)

        add_btn = _btn("＋ Add to List", "outline", height=32, min_width=130)
        add_btn.clicked.connect(self._add_entry)
        main.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#E2E8F0;"); main.addWidget(sep2)

        btns_row = QHBoxLayout()
        save_btn = _btn("💾 Save & Close", "primary", height=36)
        save_btn.clicked.connect(self._save)
        cancel_btn = _btn("Cancel", "secondary", height=36)
        cancel_btn.clicked.connect(self.reject)
        btns_row.addWidget(save_btn); btns_row.addWidget(cancel_btn)
        main.addLayout(btns_row)

    def _add_row(self, entry):
        cb = QCheckBox(entry["label"])
        cb.setChecked(entry.get("enabled", True))
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

# Status → (icon prefix, background colour, text colour)
_STATUS_STYLE = {
    "waiting":  ("⬜", "#F8FAFC", "#64748B"),
    "running":  ("⏳", "#EFF6FF", "#1D4ED8"),
    "success":  ("✅", "#F0FDF4", "#15803D"),
    "queued":   ("🕐", "#FFFBEB", "#92400E"),
    "failed":   ("❌", "#FEF2F2", "#B91C1C"),
}

def _status_style(text: str):
    t = text.lower()
    if any(x in t for x in ("waiting",)):          return _STATUS_STYLE["waiting"]
    if any(x in t for x in ("✅", "downloaded")):  return _STATUS_STYLE["success"]
    if any(x in t for x in ("🕐", "queued", "pls use")):  return _STATUS_STYLE["queued"]
    if any(x in t for x in ("❌", "failed", "error")): return _STATUS_STYLE["failed"]
    return _STATUS_STYLE["running"]  # ⏳ anything in-progress


class BatchProgressDialog(QDialog):
    """
    Live progress popup shown during any batch run.
    One row per assessee: Name | Status
    Status updates arrive from the worker thread via Qt signal.
    """
    _update_signal = pyqtSignal(str, str)   # (pan, status_text)

    def __init__(self, targets: list, mode: str, stop_callback=None, parent=None):
        super().__init__(parent)
        self._stop_callback = stop_callback
        self.setWindowTitle("Batch Progress")
        self.setMinimumSize(620, 400)
        self.resize(680, min(100 + len(targets) * 38, 600))
        # Dialog (not Window) so it stays attached to the parent and renders an
        # active title bar when modal.
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet("QDialog{background:#F8FAFC;}")

        self._pan_to_row = {}   # pan → table row index

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        # Title
        mode_label = {
            "26as":        "Downloading 26AS",
            "request_ais": "Requesting AIS Generation",
            "ais_tis":     "Downloading AIS / TIS",
        }.get(mode, "Batch Run")
        title = QLabel(f"<b>{mode_label}</b> — {len(targets)} client(s)")
        title.setStyleSheet("font-size:14px; color:#0F172A; background:transparent;")
        layout.addWidget(title)

        # Table
        self._table = QTableWidget(len(targets), 2)
        self._table.setHorizontalHeaderLabels(["Name", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 250)
        self._table.horizontalHeader().setStyleSheet(
            "QHeaderView::section{background:#E2E8F0;color:#475569;"
            "font-size:11px;font-weight:600;padding:6px;border:none;}")
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget{border:1.5px solid #E2E8F0;border-radius:8px;"
            "background:#FFFFFF;outline:0;gridline-color:#E2E8F0;"
            "alternate-background-color:#FAFCFF;}"
            "QTableWidget::item{padding:6px 10px;border-bottom:1px solid #F1F5F9;}")
        self._table.setRowHeight(0, 36)

        for row, t in enumerate(targets):
            pan  = t.get("pan", "")
            name = t.get("name", "—")
            self._pan_to_row[pan] = row
            self._table.setRowHeight(row, 36)

            name_item = QTableWidgetItem(name)
            name_item.setForeground(QColor("#1E293B"))
            self._table.setItem(row, 0, name_item)

            self._set_status_item(row, "⬜ Waiting")

        layout.addWidget(self._table)

        # Footer: progress counter + stop + close buttons
        footer = QHBoxLayout()
        self._progress_lbl = QLabel(f"0 / {len(targets)} done")
        self._progress_lbl.setStyleSheet(
            "color:#64748B; font-size:11px; background:transparent;")
        footer.addWidget(self._progress_lbl)
        footer.addStretch()

        self._stop_btn = QPushButton("⏹  Stop")
        self._stop_btn.setFixedSize(90, 30)
        self._stop_btn.setStyleSheet(
            "QPushButton{background:#EF4444;color:#FFFFFF;border:none;"
            "border-radius:6px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:#DC2626;}"
            "QPushButton:disabled{background:#E2E8F0;color:#94A3B8;}")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        footer.addWidget(self._stop_btn)
        footer.addSpacing(8)

        self._close_btn = QPushButton("Close")
        self._close_btn.setFixedSize(80, 30)
        self._close_btn.setEnabled(False)  # disabled until batch finishes
        self._close_btn.setStyleSheet(
            "QPushButton{background:#E2E8F0;color:#475569;border:none;"
            "border-radius:6px;font-size:12px;}"
            "QPushButton:enabled{background:#2563EB;color:#FFFFFF;}"
            "QPushButton:enabled:hover{background:#1D4ED8;}")
        self._close_btn.clicked.connect(self.accept)
        footer.addWidget(self._close_btn)
        layout.addLayout(footer)

        self._done_count = 0
        self._total = len(targets)

        # Wire signal — always called on the Qt main thread
        self._update_signal.connect(self._on_update)

    def _set_status_item(self, row: int, text: str):
        _, bg, fg = _status_style(text)
        item = QTableWidgetItem(text)
        item.setForeground(QColor(fg))
        item.setBackground(QColor(bg))
        item.setFont(QFont("Segoe UI", 10))
        self._table.setItem(row, 1, item)

    def _on_update(self, pan: str, status: str):
        row = self._pan_to_row.get(pan)
        if row is None:
            return
        self._set_status_item(row, status)
        # Count terminal states
        terminal = ("✅", "❌", "🕐")
        if any(status.startswith(p) for p in terminal):
            self._done_count += 1
            self._progress_lbl.setText(f"{self._done_count} / {self._total} done")
        if self._done_count >= self._total:
            self._close_btn.setEnabled(True)
            self._progress_lbl.setText(
                f"All {self._total} done — review results above")

    def _on_stop_clicked(self):
        if self._stop_callback:
            self._stop_callback()
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("⏹  Stopping...")

    def set_status(self, pan: str, status: str):
        """Thread-safe: called from worker thread."""
        self._update_signal.emit(pan, status)

    def batch_finished(self):
        """Called when batch ends (even if aborted) to enable Close and hide Stop."""
        self._stop_btn.setVisible(False)
        self._close_btn.setEnabled(True)


# ── Main Window ───────────────────────────────────────────────────────────────
class AayDocCapioApp(QMainWindow):
    _log_signal = pyqtSignal(str)
    _batch_done_signal = pyqtSignal()
    _show_progress_signal = pyqtSignal(list, str)   # (targets, mode)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AayDocCapio — Tax Documents. Delivered to You.")
        self.setMinimumSize(1100, 720)
        self.resize(1200, 780)

        self.vault = VaultManager(
            vault_path=os.path.join(_app_dir(), "tax_vault.json"))
        self.selected_ids = set()
        self.editing_id = None
        self.is_running = False
        self._checkbox_map = {}
        
        # Generate checkmark image for custom check box styling
        self.checkmark_path = os.path.join(_app_dir(), "checkmark.png")
        if not os.path.exists(self.checkmark_path):
            try:
                from PIL import Image, ImageDraw
                img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.line([(3, 8), (7, 12), (13, 4)], fill=(255, 255, 255, 255), width=2)
                img.save(self.checkmark_path, "PNG")
            except Exception as e:
                print(f"Error generating checkmark: {e}")

        self._ais_requested_time = None   # datetime when Request AIS last completed
        self._last_mode = None            # mode of last completed batch
        self._ais_results = {}            # pan → "instant" | "queued" | "failed" | "skipped"
        self._last_errors = {}            # pan → error message string

        self._log_signal.connect(self._append_log)
        self._batch_done_signal.connect(self._on_batch_done)
        self._show_progress_signal.connect(self._show_progress_dialog)
        self._progress_dialog = None   # BatchProgressDialog instance

        try:
            log_path = os.path.join(_app_dir(), "app.log")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== Session Started {get_timestamp()} ===\n")
        except Exception:
            pass

        self._build_ui()
        self.refresh_grid()

        # Check Chromium on startup in background — installs silently if missing
        QTimer.singleShot(1500, self._check_browser)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Menu bar ──────────────────────────────────────────────────────────
        menubar = self.menuBar()
        menubar.setStyleSheet(
            "QMenuBar { background:#FFFFFF; color:#334155; font-size:13px; border-bottom:1px solid #E2E8F0; }"
            "QMenuBar::item { background:transparent; padding:4px 10px; }"
            "QMenuBar::item:selected { background:#F1F5F9; border-radius:4px; }"
            "QMenu { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:6px; }"
            "QMenu::item { padding:8px 24px; color:#334155; }"
            "QMenu::item:selected { background:#DBEAFE; color:#1D4ED8; }")
        help_menu = menubar.addMenu("Help")
        about_action = QAction("About AayDocCapio", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        root = QVBoxLayout(root_widget)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self._mk_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(0)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet("QSplitter::handle{background:transparent;}")
        left = self._mk_left_panel()
        left.setFixedWidth(340)
        splitter.addWidget(left)
        splitter.addWidget(self._mk_right_panel())
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        root.addWidget(self._mk_footer())

    def _show_about(self):
        import webbrowser
        dlg = QDialog(self)
        dlg.setWindowTitle("About AayDocCapio")
        dlg.setFixedSize(500, 520)
        dlg.setStyleSheet(
            "QDialog { background:#FFFFFF; }"
            "QLabel { border:none; background:transparent; }"
            "QLabel[link=true] { color:#1A8FE3; }"
        )

        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(36, 28, 36, 28)
        vl.setSpacing(0)

        # ── App logo + name ───────────────────────────────────────────────────
        logo_row = QHBoxLayout(); logo_row.setSpacing(14)
        icon_lbl = QLabel()
        icon_path = os.path.join(_bundled_dir(), "resources", "app_icon.png")
        if os.path.exists(icon_path):
            icon_lbl.setPixmap(QPixmap(icon_path).scaled(52, 52, Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation))
        logo_row.addWidget(icon_lbl)
        name_col = QVBoxLayout(); name_col.setSpacing(2)
        name_lbl = QLabel('<span style="color:#0D1F4E;font-family:\'Avenir Next\';font-size:22px;font-weight:700;">AayDoc </span>'
                          '<span style="color:#1A8FE3;font-family:\'Avenir Next\';font-size:22px;font-weight:700;">Capio™</span>')
        ver_lbl = QLabel("Version 1.0.0")
        ver_lbl.setStyleSheet("color:#94A3B8; font-size:12px;")
        name_col.addWidget(name_lbl); name_col.addWidget(ver_lbl)
        logo_row.addLayout(name_col); logo_row.addStretch()
        vl.addLayout(logo_row)
        vl.addSpacing(14)

        desc = QLabel("Automates the secure bulk retrieval of Form 26AS, AIS and TIS directly from the Income Tax e-Filing Portal.")
        desc.setStyleSheet("color:#334155; font-size:13px;")
        desc.setWordWrap(True)
        vl.addWidget(desc)
        vl.addSpacing(12)

        # Name explanation
        name_box = QFrame()
        name_box.setStyleSheet("QFrame { background:#F0F7FF; border-radius:6px; border:1px solid #DBEAFE; }")
        nb_l = QVBoxLayout(name_box)
        nb_l.setContentsMargins(14, 10, 14, 10)
        nb_l.setSpacing(6)
        name_head = QLabel("Why AayDoc Capio?")
        name_head.setStyleSheet("color:#1A8FE3; font-size:11px; font-weight:700; letter-spacing:0.5px; background:transparent; border:none;")
        name_exp = QLabel(
            '<b style="color:#0D1F4E;">Aay</b> (Income) · '
            '<b style="color:#0D1F4E;">Doc</b> (Documents) · '
            '<b style="color:#1A8FE3;">Capio</b> <span style="color:#64748B;">(Latin: To Obtain)</span>'
        )
        name_exp.setStyleSheet("font-size:13px; background:transparent; border:none;")
        name_sub = QLabel("AayDoc Capio is designed to securely retrieve and deliver income tax documents, "
                          "eliminating repetitive manual downloads and improving efficiency for tax professionals.")
        name_sub.setStyleSheet("color:#64748B; font-size:12px; background:transparent; border:none;")
        name_sub.setWordWrap(True)
        nb_l.addWidget(name_head)
        nb_l.addWidget(name_exp)
        nb_l.addWidget(name_sub)
        vl.addWidget(name_box)
        vl.addSpacing(16)

        # ── Divider ───────────────────────────────────────────────────────────
        div1 = QFrame(); div1.setFrameShape(QFrame.Shape.HLine)
        div1.setStyleSheet("background:#E2E8F0; border:none; max-height:1px;")
        vl.addWidget(div1)
        vl.addSpacing(16)

        # ── Developer info ────────────────────────────────────────────────────
        dev_title = QLabel("Contact Us")
        dev_title.setStyleSheet("color:#94A3B8; font-size:10px; font-weight:700; letter-spacing:1px;")
        vl.addWidget(dev_title)
        vl.addSpacing(8)

        def _link_row(icon_file, display_text, url=None):
            row = QHBoxLayout(); row.setSpacing(10); row.setContentsMargins(0,0,0,0)
            icon_l = QLabel()
            icon_l.setFixedSize(22, 22)
            icon_path = os.path.join(_bundled_dir(), "resources", icon_file)
            if os.path.exists(icon_path):
                icon_l.setPixmap(QPixmap(icon_path).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio,
                                                            Qt.TransformationMode.SmoothTransformation))
            icon_l.setStyleSheet("background:transparent; border:none;")
            row.addWidget(icon_l)
            if url:
                lbl = QLabel(f'<a href="{url}" style="color:#1A8FE3; text-decoration:none;">{display_text}</a>')
                lbl.setOpenExternalLinks(True)
                lbl.setStyleSheet("background:transparent; border:none; font-size:13px;")
            else:
                lbl = QLabel(display_text)
                lbl.setStyleSheet("color:#334155; font-size:13px; font-weight:600; background:transparent; border:none;")
            row.addWidget(lbl)
            row.addStretch()
            return row

        vl.addLayout(_link_row("icon_person.png",   "CA. Deepak Bhholusaria"))
        vl.addSpacing(6)
        vl.addLayout(_link_row("icon_email.png",    "deepak@ailearrning.guru",          "mailto:deepak@ailearrning.guru"))
        vl.addSpacing(6)
        vl.addLayout(_link_row("icon_linkedin.png", "linkedin.com/in/bhholusaria",      "https://www.linkedin.com/in/bhholusaria/"))
        vl.addSpacing(6)
        vl.addLayout(_link_row("icon_vcard.png",    "Virtual Card",                     "https://www.qrcodechimp.com/page/deepakb?chk1668183417"))
        vl.addSpacing(16)

        # ── Divider ───────────────────────────────────────────────────────────
        div2 = QFrame(); div2.setFrameShape(QFrame.Shape.HLine)
        div2.setStyleSheet("background:#E2E8F0; border:none; max-height:1px;")
        vl.addWidget(div2)
        vl.addSpacing(12)

        copy = QLabel("© 2026 Deepak Bhholusaria. All rights reserved.")
        copy.setStyleSheet("color:#94A3B8; font-size:11px;")
        vl.addWidget(copy)
        vl.addStretch()

        # ── Close button ──────────────────────────────────────────────────────
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.setStyleSheet(
            "QPushButton { background:#1A8FE3; color:#FFFFFF; border:none; border-radius:6px; padding:8px 16px; font-size:13px; }"
            "QPushButton:hover { background:#1570C4; }")
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout(); btn_row.addStretch(); btn_row.addWidget(close_btn)
        vl.addLayout(btn_row)

        dlg.exec()

    def _mk_header(self):
        hdr = QFrame()
        hdr.setFixedHeight(80)
        hdr.setStyleSheet("QFrame#header { background: #FFFFFF; border: none; } QLabel { border: none; text-decoration: none; }")
        hdr.setObjectName("header")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(32, 0, 32, 0)
        hl.setSpacing(0)

        # App icon — large enough to anchor the header
        icon_label = QLabel()
        icon_path = os.path.join(_bundled_dir(), "resources", "app_icon.png")
        if os.path.exists(icon_path):
            icon_label.setPixmap(
                QPixmap(icon_path).scaled(62, 62, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
            )
        hl.addWidget(icon_label)
        hl.addSpacing(18)

        # Name + tagline stacked
        name_block = QWidget()
        name_block.setStyleSheet("background:transparent;")
        vl = QVBoxLayout(name_block)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(3)

        title_row = QWidget()
        title_row.setStyleSheet("background:transparent;")
        tl = QHBoxLayout(title_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        aay = QLabel("AayDoc ")
        aay.setStyleSheet("color:#0D1F4E; font-family:'Avenir Next'; font-size:36px; font-weight:700; background:transparent; text-decoration:none; border:none;")
        tl.addWidget(aay)

        capio = QLabel("Capio")
        capio.setStyleSheet("color:#1A8FE3; font-family:'Avenir Next'; font-size:36px; font-weight:700; background:transparent; text-decoration:none; border:none;")
        tl.addWidget(capio)

        tm = QLabel("™")
        tm.setStyleSheet("color:#1A8FE3; font-family:'Avenir Next'; font-size:14px; font-weight:700; background:transparent; padding-bottom:18px; text-decoration:none; border:none;")
        tl.addWidget(tm)

        # Separator + tagline inline with title
        sep = QLabel("  |  ")
        sep.setStyleSheet("color:#CBD5E1; font-size:22px; background:transparent; border:none;")
        sep.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        tl.addWidget(sep)

        tagline = QLabel("Tax Documents. Delivered to You.")
        tagline.setStyleSheet("color:#64748B; font-family:'Arial'; font-size:13px; font-weight:400; background:transparent; border:none;")
        tagline.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        tl.addWidget(tagline)
        tl.addStretch()

        title = title_row

        vl.addStretch()
        vl.addWidget(title)
        vl.addStretch()

        hl.addWidget(name_block)
        hl.addStretch()

        # Copyright + version on the right
        meta_block = QWidget()
        meta_block.setStyleSheet("background:transparent;")
        ml = QVBoxLayout(meta_block)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(2)
        ml.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        version_lbl = QLabel("v1.0.0")
        version_lbl.setStyleSheet("color:#94A3B8; font-family:'Arial'; font-size:11px; background:transparent; border:none;")
        version_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        copy_lbl = QLabel("© 2026 Deepak Bhholusaria")
        copy_lbl.setStyleSheet("color:#94A3B8; font-family:'Arial'; font-size:11px; background:transparent; border:none;")
        copy_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        ml.addStretch()
        ml.addWidget(version_lbl)
        ml.addWidget(copy_lbl)
        ml.addStretch()

        hl.addWidget(meta_block)
        hl.addSpacing(12)

        # ⓘ About button
        about_btn = QPushButton("ⓘ")
        about_btn.setFixedSize(32, 32)
        about_btn.setToolTip("About AayDocCapio")
        about_btn.setStyleSheet(
            "QPushButton { background:transparent; border:none; font-size:20px; color:#DC2626; }"
            "QPushButton:hover { color:#B91C1C; }")
        about_btn.clicked.connect(self._show_about)
        hl.addWidget(about_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        return hdr

    def _mk_left_panel(self):
        panel = QWidget()
        panel.setStyleSheet("background:#FFFFFF;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane{border:none; background:transparent;}"
                           "QTabBar{background:#FFFFFF; border-bottom:1px solid #E2E8F0;}"
                           "QTabBar::tab{background:transparent;color:#64748B;padding:11px 20px;"
                           "border:none;font-size:12px;font-weight:600;"
                           "border-bottom:2px solid transparent;}"
                           "QTabBar::tab:selected{color:#1D4ED8;border-bottom:2px solid #2563EB;}"
                           "QTabBar::tab:hover:!selected{color:#334155;}")
        layout.addWidget(tabs)

        # ── Tab 1: Single Profile ─────────────────────────────────────────────
        t1 = QWidget(); t1.setStyleSheet("background:transparent;")
        fl = QVBoxLayout(t1); fl.setSpacing(3); fl.setContentsMargins(14, 10, 14, 10)

        section_lbl = QLabel("CLIENT PROFILE")
        section_lbl.setStyleSheet(
            "color:#94A3B8; font-size:10px; font-weight:700; letter-spacing:1px;")
        fl.addWidget(section_lbl)
        fl.addSpacing(2)

        for attr, label, ph, is_pwd in [
            ("entry_name", "Full Name",       "e.g. John Doe", False),
            ("entry_pan",  "PAN Number",      "e.g. AAAPT0001A",       False),
            ("entry_dob",  "Date of Birth",   "DD-MM-YYYY",            False),
            ("entry_pwd",  "Portal Password", "Enter password",         True),
        ]:
            lbl_w = QLabel(label)
            lbl_w.setStyleSheet("color:#1a1a1a; font-size:11px; font-weight:600;")
            fl.addWidget(lbl_w)
            e = QLineEdit(); e.setPlaceholderText(ph)
            if is_pwd:
                e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
            setattr(self, attr, e)
            fl.addWidget(e)
            fl.addSpacing(1)

        # PAN: max 10 chars, uppercase alphanumeric only, auto-uppercase
        self.entry_pan.setMaxLength(10)
        self.entry_pan.setValidator(
            QRegularExpressionValidator(QRegularExpression("[A-Za-z0-9]{0,10}")))
        self.entry_pan.textChanged.connect(
            lambda t: self.entry_pan.setText(t.upper()) if t != t.upper() else None)

        show_pwd = QCheckBox("Show password")
        show_pwd.setStyleSheet("color:#64748B; font-size:11px; background:transparent;")
        show_pwd.toggled.connect(
            lambda v: self.entry_pwd.setEchoMode(
                QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password))
        fl.addWidget(show_pwd)
        fl.addSpacing(6)

        self.btn_save = _btn("💾  Save Profile", "primary", height=32)
        self.btn_save.clicked.connect(self.save_assessee)
        fl.addWidget(self.btn_save)

        self.btn_clear = _btn("✕  Clear Fields", "secondary", height=28)
        self.btn_clear.clicked.connect(self.clear_form)
        fl.addWidget(self.btn_clear)
        fl.addStretch()
        tabs.addTab(t1, "👤  Single Profile")

        # ── Tab 2: Bulk Operations ────────────────────────────────────────────
        t2 = QWidget(); t2.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(t2); bl.setSpacing(10); bl.setContentsMargins(18, 14, 18, 14)

        section_lbl2 = QLabel("BULK OPERATIONS")
        section_lbl2.setStyleSheet(
            "color:#94A3B8; font-size:10px; font-weight:700; letter-spacing:1px;")
        bl.addWidget(section_lbl2)
        bl.addSpacing(4)

        hint = QFrame()
        hint.setStyleSheet("QFrame{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;}")
        hl2 = QVBoxLayout(hint); hl2.setContentsMargins(14, 12, 14, 12)
        hl2.addWidget(_lbl(
            "1. Generate an Excel template.\n"
            "2. Fill Name, PAN, DOB, Password.\n"
            "3. Import to batch-load all records.",
            11, color="#64748B"))
        bl.addWidget(hint)

        self.btn_bulk_import = _btn("📥  Import CSV / Excel", "success", height=38)
        self.btn_bulk_import.clicked.connect(self.bulk_import)
        bl.addWidget(self.btn_bulk_import)

        self.btn_template = _btn("📄  Generate Upload Template", "outline", height=34)
        self.btn_template.clicked.connect(self.generate_template)
        bl.addWidget(self.btn_template)

        self.btn_export = _btn("💾  Export Saved Data", "outline", height=34)
        self.btn_export.clicked.connect(self.export_data)
        bl.addWidget(self.btn_export)
        bl.addStretch()
        tabs.addTab(t2, "📂  Bulk Operations")

        return panel

    def _mk_right_panel(self):
        panel = QWidget()
        panel.setStyleSheet("background:#FFFFFF;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(6)

        settings = self._mk_settings_bar()
        settings.setGraphicsEffect(_shadow(18, 3, 18))
        layout.addWidget(settings)

        # Grid label row
        grid_hdr_row = QHBoxLayout()
        grid_hdr_row.addWidget(_lbl("CLIENTS", 10, bold=True, color="#94A3B8"))
        grid_hdr_row.addStretch()
        self.lbl_selected = _lbl("0 selected", 11, bold=True, color="#2563EB")
        grid_hdr_row.addWidget(self.lbl_selected)
        layout.addLayout(grid_hdr_row)

        # Search / filter bar
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  Search by name or PAN...")
        self.search_box.setFixedHeight(28)
        self.search_box.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.search_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_box)

        # True Table Widget instead of Col Header & Client Scroll Area
        layout.addWidget(self._mk_client_table(), 1)

        ctrl = self._mk_control_bar()
        ctrl.setGraphicsEffect(_shadow(18, 3, 18))
        layout.addWidget(ctrl)
        return panel

    def _mk_settings_bar(self):
        bar = QFrame()
        bar.setFixedHeight(68)
        bar.setStyleSheet("QFrame{background:#FFFFFF;border-radius:10px;}")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(0)
        hl.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        def _cap(text):
            l = QLabel(text)
            l.setStyleSheet("color:#94A3B8;font-size:10px;font-weight:700;"
                            "letter-spacing:0.8px;background:transparent;")
            return l

        def _divider():
            d = QFrame(); d.setFrameShape(QFrame.Shape.VLine)
            d.setFixedSize(1, 32)
            d.setStyleSheet("background:#E2E8F0;border:none;")
            return d

        # ── Assessment Year ───────────────────────────────────────────────────
        self._ay_entries = self._load_ay_list()
        ay_labels = [e["label"] for e in self._ay_entries if e.get("enabled", True)]
        saved_ay = self.vault.get_setting("assessment_year", "Select AY/TY")
        self.ay_combo = StyledComboBox()
        self.ay_combo.addItem("Select AY/TY")
        self.ay_combo.addItems(ay_labels)
        self.ay_combo.setCurrentText(saved_ay if saved_ay in ay_labels else "Select AY/TY")
        self.ay_combo.setFixedWidth(220)
        self.ay_combo.currentTextChanged.connect(self.save_ay_setting)

        manage_btn = QPushButton("⚙")
        manage_btn.setFixedSize(24, 24)
        manage_btn.setToolTip("Manage Years")
        manage_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;font-size:14px;color:#94A3B8;}"
            "QPushButton:hover{color:#2563EB;}")
        manage_btn.clicked.connect(self.open_manage_years)

        ay_col = QWidget(); ay_col.setStyleSheet("background:transparent;")
        ay_vl = QVBoxLayout(ay_col); ay_vl.setContentsMargins(0,0,0,0); ay_vl.setSpacing(2)
        ay_vl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        ay_vl.addWidget(_cap("ASSESSMENT YEAR"))
        ay_hl = QHBoxLayout(); ay_hl.setContentsMargins(0,0,0,0); ay_hl.setSpacing(5)
        ay_hl.addWidget(self.ay_combo); ay_hl.addWidget(manage_btn)
        ay_vl.addLayout(ay_hl)
        hl.addWidget(ay_col)

        hl.addSpacing(28); hl.addWidget(_divider()); hl.addSpacing(28)

        # ── Output Directory ──────────────────────────────────────────────────
        default_dir = self.vault.get_setting(
            "download_root_dir",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs"))
        self.dir_lbl = QLabel(default_dir)
        self.dir_lbl.setStyleSheet("color:#334155;font-size:12px;background:transparent;")
        self.dir_lbl.setWordWrap(False)
        self.dir_lbl.setMaximumWidth(320)
        self.dir_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        browse_btn = _btn("📂  Browse", "outline", height=26)
        browse_btn.clicked.connect(self.browse_output_dir)

        dir_row = QHBoxLayout(); dir_row.setContentsMargins(0,0,0,0); dir_row.setSpacing(8)
        dir_row.addWidget(self.dir_lbl); dir_row.addWidget(browse_btn)

        dir_col = QWidget(); dir_col.setStyleSheet("background:transparent;")
        dir_col.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        dir_vl = QVBoxLayout(dir_col); dir_vl.setContentsMargins(0,0,0,0); dir_vl.setSpacing(2)
        dir_vl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        dir_vl.addWidget(_cap("OUTPUT DIRECTORY"))
        dir_vl.addLayout(dir_row)
        hl.addWidget(dir_col)
        hl.addStretch()

        return bar

    def _mk_client_table(self):
        # Create Table Widget with 0 rows and 5 columns
        self.client_table = QTableWidget(0, 5)
        self.client_table.setHorizontalHeaderLabels(["", "Name  ⇅", "PAN  ⇅", "Date of Birth", "Actions"])
        
        # Style the header section
        self.client_table.horizontalHeader().setStyleSheet(
            "QHeaderView::section { background-color: #FFFFFF; border: none; border-right: 1px solid #CBD5E1; border-bottom: 1px solid #CBD5E1; font-weight: bold; color: #64748B; font-size: 11px; height: 34px; }"
        )
        self.client_table.verticalHeader().setVisible(False)
        self.client_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.client_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.client_table.setShowGrid(True)
        self.client_table.setAlternatingRowColors(False)
        
        # Style checkboxes and table
        chk_path = self.checkmark_path.replace("\\", "/")
        checkbox_style = (
            "QCheckBox { background: transparent; }"
            "QCheckBox::indicator { width: 15px; height: 15px; border: 1.5px solid #475569; border-radius: 3px; background: #FFFFFF; }"
            "QCheckBox::indicator:hover { border-color: #0284C7; }"
            f"QCheckBox::indicator:checked {{ background-color: #0284C7; border-color: #0284C7; image: url('{chk_path}'); }}"
        )
        
        self.client_table.setStyleSheet(
            "QTableWidget { border: 1.5px solid #CBD5E1; border-radius: 8px; background: #FFFFFF; outline: 0; gridline-color: #E2E8F0; }"
            "QTableWidget::item { border-bottom: 1px solid #E2E8F0; padding: 5px; }"
            + checkbox_style
        )
        
        # Set alignments for header items
        for col, align in [
            (1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            (2, Qt.AlignmentFlag.AlignCenter),
            (3, Qt.AlignmentFlag.AlignCenter),
            (4, Qt.AlignmentFlag.AlignCenter),
        ]:
            item = self.client_table.horizontalHeaderItem(col)
            if item:
                item.setTextAlignment(align)
                
        # Column width settings
        self.client_table.setColumnWidth(0, 45)
        self.client_table.setColumnWidth(2, 140)
        self.client_table.setColumnWidth(3, 130)
        self.client_table.setColumnWidth(4, 90)
        
        # Resize behaviors
        header = self.client_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        
        # Interactive sorting
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._on_header_clicked)
        self._current_sort_col = -1
        self._current_sort_order = Qt.SortOrder.AscendingOrder
        
        # Cell click listener
        self.client_table.cellClicked.connect(self._on_cell_clicked)
        
        # Create Header Checkbox
        self.header_cb = QCheckBox(header)
        self.header_cb.setFixedSize(18, 18)
        self.header_cb.setStyleSheet(checkbox_style)
        self.header_cb.toggled.connect(self.toggle_select_all)
        header.geometriesChanged.connect(self._position_header_checkbox)
        
        self.client_table.setMinimumHeight(200)
        return self.client_table

    def _position_header_checkbox(self):
        if not hasattr(self, "client_table") or not hasattr(self, "header_cb"):
            return
        header = self.client_table.horizontalHeader()
        x = header.sectionPosition(0)
        w = header.sectionSize(0)
        h = header.height()
        cb_x = x + (w - 18) // 2
        cb_y = (h - 18) // 2
        self.header_cb.move(cb_x, cb_y)

    def _on_cell_clicked(self, row, col):
        # Ignore columns 0 (checkbox) and 4 (actions) since they have their own click handlers
        if col in (0, 4):
            return
        # Guard: check if combo popup is open
        if hasattr(self, "ay_combo") and self.ay_combo._popup_was_open:
            return
        # Toggle checkbox in column 0
        cb_container = self.client_table.cellWidget(row, 0)
        if cb_container:
            cb = cb_container.findChild(QCheckBox)
            if cb:
                cb.setChecked(not cb.isChecked())

    def _on_header_clicked(self, logical_index):
        if logical_index not in (1, 2):  # Only sort on Name (1) and PAN (2)
            return
            
        header = self.client_table.horizontalHeader()
        
        # Toggle or initialize sort
        if self._current_sort_col == logical_index:
            self._current_sort_order = (
                Qt.SortOrder.DescendingOrder 
                if self._current_sort_order == Qt.SortOrder.AscendingOrder 
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._current_sort_col = logical_index
            self._current_sort_order = Qt.SortOrder.AscendingOrder
            
        # Visually show active sort indicator
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self._current_sort_col, self._current_sort_order)
        
        # Perform sort
        self.client_table.setSortingEnabled(True)
        self.client_table.sortByColumn(self._current_sort_col, self._current_sort_order)
        self.client_table.setSortingEnabled(False)
        
        # Re-apply alternating colors after sort
        for row_idx in range(self.client_table.rowCount()):
            item = self.client_table.item(row_idx, 1)
            if item:
                row_id = item.data(Qt.ItemDataRole.UserRole)
                row_selected = row_id in self.selected_ids
                self._apply_row_style(row_idx, row_selected, row_idx)

    def _mk_control_bar(self):
        bar = QFrame()
        bar.setFixedHeight(54)
        bar.setStyleSheet("QFrame{background:#FFFFFF;border-radius:10px;}")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(22, 0, 16, 0)

        # Headless toggle — when checked, the automation browser runs hidden.
        # Default ON; uncheck to watch progress or handle a CAPTCHA.
        self.chk_headless = QCheckBox("Run in background (hide browser)")
        self.chk_headless.setChecked(True)
        self.chk_headless.setToolTip(
            "When ON, the automation Chrome window is hidden (headless).\n"
            "Keep OFF to watch progress or handle any CAPTCHA.")
        self.chk_headless.setStyleSheet(
            "QCheckBox{font-size:12px;color:#475569;background:transparent;spacing:6px;}"
            "QCheckBox::indicator{width:15px;height:15px;border:1.5px solid #94A3B8;"
            "border-radius:3px;background:#FFFFFF;}"
            "QCheckBox::indicator:checked{background:#2563EB;border-color:#2563EB;}")
        hl.addWidget(self.chk_headless)

        hl.addStretch()

        self.btn_delete_sel = _btn("🗑  Delete Selected", "danger", height=34, min_width=130)
        self.btn_delete_sel.setEnabled(False)
        self.btn_delete_sel.clicked.connect(self.delete_selected)
        hl.addWidget(self.btn_delete_sel)
        hl.addSpacing(8)

        # ── Run dropdown (split-style: label + arrow) ─────────────────────────
        self.btn_run = QToolButton()
        self.btn_run.setText("▶  Run")
        self.btn_run.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_run.setFixedHeight(34)
        self.btn_run.setMinimumWidth(110)
        self.btn_run.setStyleSheet(
            "QToolButton{"
            "  background:#16A34A; color:#FFFFFF; border:none;"
            "  border-radius:8px; font-size:13px; font-weight:600; padding:0 14px;"
            "}"
            "QToolButton:hover{ background:#15803D; }"
            "QToolButton:disabled{ background:#D1FAE5; color:#6EE7B7; }"
            "QToolButton::menu-button{"
            "  border-left:1px solid rgba(255,255,255,0.35);"
            "  border-radius:0 8px 8px 0; width:20px;"
            "}"
            "QToolButton::menu-arrow{ image:none; }"
        )

        run_menu = QMenu(self.btn_run)
        run_menu.setStyleSheet(
            "QMenu{ background:#FFFFFF; border:1px solid #E2E8F0;"
            "       border-radius:8px; padding:4px 0; }"
            "QMenu::item{ padding:8px 18px; font-size:13px; color:#1E293B; }"
            "QMenu::item:selected{ background:#F1F5F9; }"
            "QMenu::separator{ height:1px; background:#E2E8F0; margin:4px 0; }"
        )

        act_26as = QAction("▶  Download 26AS", self)
        act_26as.setToolTip("Downloads Form 26AS PDF + TXT for selected clients.")
        act_26as.triggered.connect(lambda: self.start_automation("26as"))

        act_request_ais = QAction("📋  Download / Request TIS & AIS", self)
        act_request_ais.setToolTip(
            "Opens AIS portal for each client.\n"
            "• If AIS is ready — downloads instantly.\n"
            "• If not ready — places generation request (~5 min on ITD servers).")
        act_request_ais.triggered.connect(lambda: self.start_automation("request_ais"))

        act_dl_ais = QAction("⬇  Download Previously Requested AIS", self)
        act_dl_ais.setToolTip(
            "Fetches AIS PDF from Activity History for clients\n"
            "whose AIS was requested earlier and is now ready.")
        act_dl_ais.triggered.connect(lambda: self.start_automation("ais_tis"))

        run_menu.addAction(act_26as)
        run_menu.addSeparator()
        run_menu.addAction(act_request_ais)
        run_menu.addAction(act_dl_ais)

        self.btn_run.setMenu(run_menu)
        self.btn_run.clicked.connect(lambda: self.btn_run.showMenu())
        hl.addWidget(self.btn_run)

        # ── AIS status line (hidden until Request AIS runs) ───────────────────
        self.ais_status_bar = QFrame()
        self.ais_status_bar.setFixedHeight(28)
        self.ais_status_bar.setStyleSheet(
            "QFrame{background:#FFF7ED;border-top:1px solid #FED7AA;}")
        self.ais_status_bar.setVisible(False)
        asl = QHBoxLayout(self.ais_status_bar)
        asl.setContentsMargins(22, 0, 16, 0)
        self.ais_status_lbl = QLabel()
        self.ais_status_lbl.setStyleSheet(
            "color:#92400E; font-size:11px; background:transparent;")
        asl.addWidget(self.ais_status_lbl)
        asl.addStretch()
        ais_dismiss = QPushButton("✕")
        ais_dismiss.setFixedSize(18, 18)
        ais_dismiss.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            "color:#92400E;font-size:10px;}"
            "QPushButton:hover{color:#78350F;}")
        ais_dismiss.clicked.connect(lambda: self.ais_status_bar.setVisible(False))
        asl.addWidget(ais_dismiss)

        # Wrap bar + status into a column so status sits just below the bar
        container = QWidget()
        container.setStyleSheet("background:transparent;")
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(bar)
        col.addWidget(self.ais_status_bar)
        return container

    def _mk_footer(self):
        footer = QFrame()
        footer.setFixedHeight(190)
        footer.setStyleSheet("QFrame{background:#0F172A;}")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        log_hdr = QFrame()
        log_hdr.setFixedHeight(32)
        log_hdr.setStyleSheet("QFrame{background:#1E293B;}")
        hhl = QHBoxLayout(log_hdr); hhl.setContentsMargins(16, 0, 12, 0)
        dot = QLabel("●")
        dot.setStyleSheet("color:#22C55E; font-size:9px; margin-right:4px;")
        hhl.addWidget(dot)
        hhl.addWidget(_lbl("LIVE LOGS", 10, bold=True, color="#64748B"))
        hhl.addStretch()
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedHeight(22)
        copy_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#475569;border:1px solid #334155;"
            "border-radius:4px;padding:0 10px;font-size:10px;}"
            "QPushButton:hover{color:#94A3B8;border-color:#475569;}")
        copy_btn.clicked.connect(self.copy_logs_to_clipboard)
        hhl.addWidget(copy_btn)
        fl.addWidget(log_hdr)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet(
            "QTextEdit{background:#0F172A;border:none;"
            "font-family:'Cascadia Code','Consolas',monospace;"
            "font-size:11px;color:#7DD3FC;padding:8px 16px;}")
        fl.addWidget(self.log_box)
        return footer

    # ── Grid ──────────────────────────────────────────────────────────────────

    def _apply_row_style(self, row_idx, selected, index=0):
        # Selected rows are highlighted with RED text (always readable, never
        # white-on-white). Background stays the normal alternating colour.
        bg = "#FFFFFF" if index % 2 == 0 else "#F8FAFC"
        fg = "#DC2626" if selected else "#0F172A"
        
        # Apply style to all items in the row
        for col in range(self.client_table.columnCount()):
            item = self.client_table.item(row_idx, col)
            if item:
                item.setBackground(QColor(bg))
                item.setForeground(QColor(fg))
                # Set font
                font = item.font()
                # PAN (col 2) is bold by default, or bold if selected
                font.setBold(col == 2 or selected)
                item.setFont(font)
        
        # Apply background to cell widgets
        cb_container = self.client_table.cellWidget(row_idx, 0)
        if cb_container:
            cb_container.setStyleSheet(f"background:{bg}; border:none;")
            cb = cb_container.findChild(QCheckBox)
            if cb:
                cb.setStyleSheet("background:transparent;")
                
        acts_container = self.client_table.cellWidget(row_idx, 4)
        if acts_container:
            acts_container.setStyleSheet(f"background:{bg}; border:none;")

    def _apply_filter(self, text=""):
        if not hasattr(self, "client_table"):
            return
        q = text.strip().lower()
        for row_idx in range(self.client_table.rowCount()):
            name_item = self.client_table.item(row_idx, 1)
            pan_item = self.client_table.item(row_idx, 2)
            if not name_item or not pan_item:
                continue
            visible = (not q
                       or q in name_item.text().lower()
                       or q in pan_item.text().lower())
            self.client_table.setRowHidden(row_idx, not visible)

    def refresh_grid(self):
        self._checkbox_map.clear()
        self.assessee_list = self.vault.get_all_assessees()
        
        if not hasattr(self, "client_table"):
            return
            
        # Block signals on header_cb during refresh
        if hasattr(self, "header_cb"):
            self.header_cb.blockSignals(True)
            self.header_cb.setEnabled(False)
            
        self.client_table.setRowCount(0)
        
        if not self.assessee_list:
            if hasattr(self, "header_cb"):
                self.header_cb.setChecked(False)
                self.header_cb.blockSignals(False)
            self._update_count()
            return

        if hasattr(self, "header_cb"):
            self.header_cb.setEnabled(True)
            
        for i, a in enumerate(self.assessee_list):
            a_id = a.get("id")
            is_selected = a_id in self.selected_ids
            
            self.client_table.insertRow(i)
            
            # Col 0: Checkbox inside a centered widget
            cb_container = QWidget()
            cb_layout = QHBoxLayout(cb_container)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox()
            cb.setChecked(is_selected)
            cb.toggled.connect(lambda checked, id_=a_id: self._on_check(id_, checked))
            self._checkbox_map[a_id] = cb
            cb_layout.addWidget(cb)
            self.client_table.setCellWidget(i, 0, cb_container)
            
            # Col 1: Name item
            name_item = QTableWidgetItem(a.get("name", ""))
            name_item.setData(Qt.ItemDataRole.UserRole, a_id)
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.client_table.setItem(i, 1, name_item)
            
            # Col 2: PAN item
            pan_item = QTableWidgetItem(a.get("pan", ""))
            pan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.client_table.setItem(i, 2, pan_item)
            
            # Col 3: Date of Birth item
            dob_item = QTableWidgetItem(a.get("dob", ""))
            dob_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.client_table.setItem(i, 3, dob_item)
            
            # Col 4: Action buttons
            edit_btn = QPushButton("✏")
            edit_btn.setFixedSize(28, 28)
            edit_btn.setToolTip("Edit")
            edit_btn.setStyleSheet(
                "QPushButton { background:transparent; border:none; font-size:16px; }"
                "QPushButton:hover { color:#0284C7; }")
            edit_btn.clicked.connect(lambda _, av=a: self.load_for_editing(av))
            
            del_btn = QPushButton("🗑")
            del_btn.setFixedSize(28, 28)
            del_btn.setToolTip("Delete")
            del_btn.setStyleSheet(
                "QPushButton { background:transparent; border:none; font-size:16px; }"
                "QPushButton:hover { color:#DC2626; }")
            del_btn.clicked.connect(lambda _, id_=a_id: self.delete_assessee(id_))
            
            acts_container = QWidget()
            acts_layout = QHBoxLayout(acts_container)
            acts_layout.setContentsMargins(0, 0, 0, 0)
            acts_layout.setSpacing(6)
            acts_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            acts_layout.addWidget(edit_btn)
            acts_layout.addWidget(del_btn)
            self.client_table.setCellWidget(i, 4, acts_container)
            
            # Apply row colors and styles
            self._apply_row_style(i, is_selected, i)
            
        # Re-apply active sort if any
        if self._current_sort_col in (1, 2):
            self.client_table.setSortingEnabled(True)
            self.client_table.sortByColumn(self._current_sort_col, self._current_sort_order)
            self.client_table.setSortingEnabled(False)
            
            # Re-apply alternating colors after sort
            for row_idx in range(self.client_table.rowCount()):
                item = self.client_table.item(row_idx, 1)
                if item:
                    row_id = item.data(Qt.ItemDataRole.UserRole)
                    row_selected = row_id in self.selected_ids
                    self._apply_row_style(row_idx, row_selected, row_idx)
                    
        if hasattr(self, "header_cb"):
            self.header_cb.blockSignals(False)
            
        self._update_count()
        if hasattr(self, "search_box"):
            self._apply_filter(self.search_box.text())

    def _on_check(self, id_, checked):
        if checked:
            self.selected_ids.add(id_)
        else:
            self.selected_ids.discard(id_)
            
        # Find the row in table widget and apply selection style
        if hasattr(self, "client_table"):
            for row_idx in range(self.client_table.rowCount()):
                item = self.client_table.item(row_idx, 1)
                if item and item.data(Qt.ItemDataRole.UserRole) == id_:
                    self._apply_row_style(row_idx, checked, row_idx)
                    break
                    
        self._update_count()

    def toggle_select_all(self, checked):
        for a_id, cb in self._checkbox_map.items():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
            if checked:
                self.selected_ids.add(a_id)
            else:
                self.selected_ids.discard(a_id)
                
        # Re-apply styling to all rows
        if hasattr(self, "client_table"):
            for row_idx in range(self.client_table.rowCount()):
                item = self.client_table.item(row_idx, 1)
                if item:
                    row_id = item.data(Qt.ItemDataRole.UserRole)
                    self._apply_row_style(row_idx, checked, row_idx)
                    
        self._update_count()

    def _update_count(self):
        n = len(self.selected_ids)
        self.lbl_selected.setText(f"{n} selected" if n else "")
        total = len(self._checkbox_map)
        if hasattr(self, "header_cb"):
            self.header_cb.blockSignals(True)
            self.header_cb.setChecked(total > 0 and n == total)
            self.header_cb.blockSignals(False)
        if hasattr(self, "btn_delete_sel"):
            self.btn_delete_sel.setEnabled(n > 0)

    # ── Form Operations ───────────────────────────────────────────────────────

    def load_for_editing(self, a):
        self.editing_id = a.get("id")
        self.entry_name.setText(a.get("name", ""))
        self.entry_pan.setText(a.get("pan", ""))
        self.entry_dob.setText(a.get("dob", ""))
        self.entry_pwd.setText(a.get("password", ""))
        self.btn_save.setText("💾 Update Profile")
        self.btn_save.setStyleSheet(
            "QPushButton{background:#EAB308;color:white;border:none;border-radius:6px;"
            "padding:6px 16px;font-weight:bold;font-size:12px;}"
            "QPushButton:hover{background:#CA8A04;}")

    def clear_form(self):
        self.editing_id = None
        for e in (self.entry_name, self.entry_pan, self.entry_dob, self.entry_pwd):
            e.clear()
        self.btn_save.setText("💾 Save Profile")
        self.btn_save.setStyleSheet(
            "QPushButton{background:#2563EB;color:white;border:none;border-radius:6px;"
            "padding:6px 16px;font-weight:bold;font-size:12px;}"
            "QPushButton:hover{background:#1D4ED8;}")

    def save_assessee(self):
        try:
            self.vault.add_update_assessee(
                self.entry_name.text(), self.entry_pan.text(),
                self.entry_dob.text(), self.entry_pwd.text(), self.editing_id)
            action = "updated" if self.editing_id else "added"
            self.log(f"[Vault] Profile {self.entry_pan.text()} successfully {action}.")
            self.clear_form(); self.refresh_grid()
        except ValueError as ve:
            QMessageBox.critical(self, "Validation Error", str(ve))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save profile: {e}")

    def delete_assessee(self, assessee_id):
        if QMessageBox.question(self, "Confirm Delete",
            "Delete this assessee from the vault?") == QMessageBox.StandardButton.Yes:
            try:
                self.vault.delete_assessee(assessee_id)
                self.selected_ids.discard(assessee_id)
                self.log("[Vault] Assessee deleted.")
                self.refresh_grid()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete: {e}")

    def delete_selected(self):
        n = len(self.selected_ids)
        if not n:
            return
        if QMessageBox.question(self, "Confirm Bulk Delete",
                f"Delete {n} selected assessee{'s' if n > 1 else ''} from the vault?\n\nThis cannot be undone."
                ) != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for a_id in list(self.selected_ids):
            try:
                self.vault.delete_assessee(a_id)
            except Exception as e:
                errors.append(str(e))
        self.selected_ids.clear()
        self.log(f"[Vault] {n} assessee{'s' if n > 1 else ''} deleted.")
        if errors:
            QMessageBox.warning(self, "Partial Delete", f"{len(errors)} deletion(s) failed:\n" + "\n".join(errors))
        self.refresh_grid()

    # ── Settings ──────────────────────────────────────────────────────────────

    def browse_output_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Output Directory",
            self.dir_lbl.text())
        if chosen:
            self.dir_lbl.setText(chosen)
            self.vault.update_setting("download_root_dir", chosen)
            self.log(f"[Settings] Output folder: {chosen}")

    def _ay_json_path(self) -> str:
        """
        Writable path for assessment_years.json next to the exe / script.
        On first run when frozen, seeds the file from the bundled read-only copy.
        """
        writable = os.path.join(_app_dir(), "assessment_years.json")
        if not os.path.exists(writable):
            bundled = os.path.join(_bundled_dir(), "assessment_years.json")
            if os.path.exists(bundled):
                import shutil
                shutil.copy2(bundled, writable)
        return writable

    def _load_ay_list(self):
        path = self._ay_json_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)
            # Sort: disabled (future TY) first, then descending by year
            def _sort_key(e):
                y = e.get("year", {})
                label_year = (y.get("AY") or y.get("TY") or y.get("FY") or "0000-00")
                try:
                    return (0 if not e.get("enabled", True) else 1, -int(label_year[:4]))
                except ValueError:
                    return (1, 0)
            return sorted(entries, key=_sort_key)
        except Exception:
            return [
                {"label": "AY 2025-26 (FY 2024-25)", "enabled": True, "year": {"AY": "2025-26", "FY": "2024-25"}},
                {"label": "AY 2024-25 (FY 2023-24)", "enabled": True, "year": {"AY": "2024-25", "FY": "2023-24"}},
            ]

    def _resolve_ay_fy(self, label: str):
        for e in self._ay_entries:
            if e["label"] == label:
                y = e["year"]
                return (y.get("AY") or y.get("TY")), y.get("FY")
        return None, None

    def open_manage_years(self):
        ManageYearsDialog(self, self._ay_json_path(), on_save=self.refresh_ay_combo).exec()

    def refresh_ay_combo(self):
        self._ay_entries = self._load_ay_list()
        ay_labels = [e["label"] for e in self._ay_entries if e.get("enabled", True)]
        current = self.ay_combo.currentText()
        self.ay_combo.blockSignals(True)
        self.ay_combo.clear()
        self.ay_combo.addItem("Select AY/TY")
        self.ay_combo.addItems(ay_labels)
        self.ay_combo.setCurrentText(current if current in ay_labels else "Select AY/TY")
        self.ay_combo.blockSignals(False)
        self.log("[Settings] Assessment Year list refreshed.")

    def save_ay_setting(self, val):
        if val and val != "Select AY/TY":
            self.vault.update_setting("assessment_year", val)
            self.log(f"[Settings] Assessment Year → {val}")

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, message):
        text = f"[{get_timestamp()}] {message}"
        self._log_signal.emit(text)
        try:
            with open("app.log", "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def _append_log(self, text):
        self.log_box.append(text)
        self.log_box.moveCursor(QTextCursor.MoveOperation.End)

    def copy_logs_to_clipboard(self):
        QApplication.clipboard().setText(self.log_box.toPlainText())
        self.log("[System] Logs copied to clipboard.")

    # ── Bulk Import ───────────────────────────────────────────────────────────

    def bulk_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import File", "",
            "Excel / CSV files (*.xlsx *.csv)")
        if not path:
            return
        self.log(f"[Vault] Importing {os.path.basename(path)}...")
        added, updated, errors = self.vault.import_bulk(path)
        total = added + updated
        parts = []
        if added:
            parts.append(f"{added} new record{'s' if added != 1 else ''} added")
        if updated:
            parts.append(f"{updated} existing record{'s' if updated != 1 else ''} updated")
        summary = ", ".join(parts) if parts else "No records imported"
        self.log(f"[Vault] Import complete — {summary}.")
        if errors:
            for err in errors:
                self.log(f"  - {err}")
            QMessageBox.warning(self, "Import Complete",
                f"{summary}.\n\n{len(errors)} row(s) had errors — see logs for details.")
        else:
            QMessageBox.information(self, "Import Complete", f"{summary}.")
        self.refresh_grid()

    def generate_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Template",
            "Assessee_Import_Template", "Excel Workbook (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        try:
            self.vault.generate_template(path)
            self.log(f"[Vault] Template generated: {path}")
            QMessageBox.information(self, "Success", f"Template generated at:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed: {e}")

    def export_data(self):
        assessees = self.vault.get_all_assessees()
        if not assessees:
            QMessageBox.information(self, "No Data", "No assessees saved yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Saved Data",
            "Assessee_Export", "Excel Workbook (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        if not (path.endswith('.xlsx') or path.endswith('.csv')):
            path += ".xlsx"
        try:
            self.vault.export_data(path)
            self.log(f"[Vault] Data exported: {path}")
            QMessageBox.information(self, "Export Complete",
                f"{len(assessees)} record(s) exported to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed: {e}")

    # ── Browser health check ──────────────────────────────────────────────────

    def _check_browser(self):
        """Run silently on startup; installs Chromium if missing."""
        def _run():
            import asyncio
            from automation.browser import _playwright_browsers_dir, _install_chromium
            import os
            # Check if chromium executable already exists in our browsers dir
            browsers_dir = _playwright_browsers_dir()
            chromium_exists = any(
                f.startswith("chromium") for f in os.listdir(browsers_dir)
            ) if os.path.exists(browsers_dir) else False
            if not chromium_exists:
                self.log("[Browser] Chromium not found — installing in background...")
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(_install_chromium(self.log))
                except Exception as e:
                    self.log(f"[Browser] Auto-install failed: {e}")
                    self.log("[Browser] Run 'playwright install chromium' manually if downloads fail.")
                finally:
                    loop.close()
            else:
                self.log("[Browser] Chromium ready.")
        threading.Thread(target=_run, daemon=True).start()

    # ── Automation ────────────────────────────────────────────────────────────

    def _lock_ui(self, lock: bool):
        widgets = [self.entry_name, self.entry_pan, self.entry_dob, self.entry_pwd,
                   self.btn_save, self.btn_clear, self.btn_bulk_import, self.btn_template,
                   self.btn_export, self.ay_combo, self.btn_delete_sel, self.btn_run,
                   self.chk_headless]
        if hasattr(self, "header_cb"):
            widgets.append(self.header_cb)
        for w in widgets:
            w.setEnabled(not lock)

    def start_automation(self, mode: str):
        """
        mode: "26as"        — download 26AS only
              "request_ais" — fire AIS generation request (Phase 1)
              "ais_tis"     — download AIS (from Activity History) + TIS (Phase 2)
        """
        if self.is_running:
            return
        if not self.selected_ids:
            QMessageBox.warning(self, "Selection Required",
                "Please select at least one client.")
            return
        ay_label = self.ay_combo.currentText()
        if not ay_label or ay_label == "Select AY/TY":
            QMessageBox.warning(self, "Selection Required",
                "Please select an Assessment / Tax Year.")
            return
        ay, fy = self._resolve_ay_fy(ay_label)
        if not ay:
            QMessageBox.warning(self, "Invalid", f"Cannot resolve year: {ay_label}")
            return

        self.is_running = True
        self._lock_ui(True)
        self.log_box.clear()

        targets = [a for a in self.assessee_list if a.get("id") in self.selected_ids]

        self.btn_run.setText("⏳ Running...")

        mode_log = {"26as": "26AS download",
                    "request_ais": "AIS generation requests",
                    "ais_tis": "AIS/TIS download"}
        self.log(f"[System] Starting {mode_log[mode]}...")

        # Show progress dialog (on main thread via signal)
        self._show_progress_signal.emit(targets, mode)

        threading.Thread(
            target=self._run_wrapper,
            args=(targets, ay, fy, self.dir_lbl.text(), mode),
            daemon=True).start()

    def _show_progress_dialog(self, targets: list, mode: str):
        """Called on main thread to create and show the progress dialog."""
        self._progress_dialog = BatchProgressDialog(
            targets, mode, stop_callback=self.stop_automation, parent=self)
        # Window-modal: blocks the parent window (so it can't be clicked behind
        # the dialog) but still allows the worker thread's Qt-signal updates.
        # We use show() rather than exec() so the event loop keeps processing
        # the live status signals.
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.show()
        self._progress_dialog.raise_()
        self._progress_dialog.activateWindow()

    def stop_automation(self):
        if not self.is_running:
            return
        if QMessageBox.question(self, "Stop",
            "Abort the active batch?") == QMessageBox.StandardButton.Yes:
            self.log("[System] Abort requested...")
            self.is_running = False

    def _run_wrapper(self, targets, ay, fy, root_dir, mode):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self._execute_batch(targets, ay, fy, root_dir, mode))
        except Exception as e:
            self.log(f"[System Error] Batch crashed: {e}")
        finally:
            loop.close()
            self.is_running = False
            self._last_mode = mode
            if self._progress_dialog:
                self._progress_dialog.batch_finished()
            self._batch_done_signal.emit()

    def _on_batch_done(self):
        import datetime
        self.btn_run.setText("▶  Run")
        self._lock_ui(False)
        self.log("[System] Engine Idle.")

        mode = self._last_mode

        if mode == "request_ais":
            results = self._ais_results
            n_instant = sum(1 for v in results.values() if v == "instant")
            n_queued  = sum(1 for v in results.values() if v == "queued")
            n_failed  = sum(1 for v in results.values() if v == "failed")

            self._ais_requested_time = datetime.datetime.now()
            t = self._ais_requested_time.strftime("%I:%M %p")

            # Build status line text — only mention what actually happened
            parts = []
            if n_instant:
                parts.append(f"{n_instant} downloaded instantly")
            if n_queued:
                parts.append(f"{n_queued} queued on ITD servers")
            if n_failed:
                parts.append(f"{n_failed} failed")
            status_summary = " · ".join(parts) if parts else "no results"

            if n_queued:
                self.ais_status_lbl.setText(
                    f"⏳  AIS at {t}: {status_summary} — "
                    f"wait ~5 min then click ⬇ Download AIS/TIS for the {n_queued} queued client(s).")
                self.ais_status_bar.setVisible(True)
            else:
                # All instant or failed — no need to show the waiting reminder
                self.ais_status_bar.setVisible(False)

            # Build dialog text based on actual breakdown
            lines = ["<b>AIS Request Results:</b><br>"]
            if n_instant:
                lines.append(
                    f"✅ <b>{n_instant} client(s)</b> — AIS file was small, "
                    f"downloaded instantly. No further action needed for these.")
            if n_queued:
                lines.append(
                    f"⏳ <b>{n_queued} client(s)</b> — AIS file is large, "
                    f"generation request queued on ITD servers.<br>"
                    f"&nbsp;&nbsp;Wait <b>~5 minutes</b>, then select these clients "
                    f"and click <b>⬇ Download AIS/TIS</b>.")
            if n_failed:
                # Show the distinct error reasons so the user knows WHY.
                reasons = sorted(set(self._last_errors.values()))
                reason_html = ""
                if reasons:
                    reason_html = "<br>" + "<br>".join(
                        f"&nbsp;&nbsp;• {r}" for r in reasons[:5])
                lines.append(
                    f"❌ <b>{n_failed} client(s)</b> — Request failed.{reason_html}")

            msg = QMessageBox(self)
            msg.setWindowTitle("AIS Request Complete")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("<br><br>".join(lines))
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()

        elif mode == "ais_tis":
            # Hide the status line once download is done
            self.ais_status_bar.setVisible(False)
            self._ais_requested_time = None

    async def _execute_batch(self, targets, ay, fy, root_dir, mode):
        self.log(f"[System] Batch: {len(targets)} client(s) | AY: {ay} | Mode: {mode}")
        self._ais_results = {}
        self._last_errors = {}

        def set_status(pan, text):
            """Update the progress dialog row for this client (thread-safe)."""
            if self._progress_dialog:
                self._progress_dialog.set_status(pan, text)

        try:
            interactive = not self.chk_headless.isChecked()
            context = await browser_manager.get_context(
                log_callback=self.log, interactive=interactive)
        except Exception as e:
            self.log(f"[System Error] Browser init failed: {e}"); return

        for i, target in enumerate(targets):
            if not self.is_running:
                self.log("[System] Aborted."); break

            pan  = target.get("pan", "")
            name = target.get("name", "")
            dob  = target.get("dob", "")
            self.log("──────────────────────────────────────────────────")
            self.log(f"[{i+1}/{len(targets)}] {name}")

            name_safe = "".join(c if c.isalnum() or c in " _-" else "" for c in name)
            out = os.path.join(root_dir, f"{pan}-{name_safe}", f"AY_{ay.replace('-','_')}")

            page = None
            try:
                # ── Login ────────────────────────────────────────────────────
                set_status(pan, "⏳ Logging in to ITD...")
                page = await login_itd(pan, target.get("password"), self.log, context)
                set_status(pan, "⏳ Logged in to ITD")

                # ── 26AS ─────────────────────────────────────────────────────
                if mode == "26as" and self.is_running:
                    set_status(pan, "⏳ Downloading 26AS...")
                    await download_26as(page, ay, out, self.log, pan=pan, dob=dob)
                    set_status(pan, "✅ 26AS Downloaded")

                # ── Request AIS ───────────────────────────────────────────────
                elif mode == "request_ais" and self.is_running:
                    await self._ensure_dashboard(page)
                    set_status(pan, "⏳ Opening AIS portal...")
                    result = await run_request_ais(
                        page, fy, out, self.log, pan=pan, dob=dob,
                        status_callback=lambda t, _p=pan: set_status(_p, t))
                    ais_status = result.get("status")

                    if ais_status in ("instant", "downloaded"):
                        self._ais_results[pan] = "instant"
                        set_status(pan, "✅ AIS Downloaded instantly")
                    elif ais_status == "requested":
                        self._ais_results[pan] = "queued"
                        ref = result.get("ref_id", "")
                        ref_txt = f" (Ref: {ref})" if ref else ""
                        set_status(pan,
                            f"🕐 AIS request placed{ref_txt} — use Download AIS/TIS after ~5 min")
                        self.log(f"[AIS] Generation queued — Ref ID: {ref or 'N/A'}")
                    elif ais_status == "skipped":
                        self._ais_results[pan] = "skipped"
                        set_status(pan, "⬜ Skipped — AIS not available for this FY")
                    else:
                        self._ais_results[pan] = "failed"
                        set_status(pan, "❌ AIS request failed — check logs")
                        self.log("[Warning] AIS request did not complete — check portal.")

                # ── Download AIS/TIS ──────────────────────────────────────────
                elif mode == "ais_tis" and self.is_running:
                    # "Download Previously Requested AIS" — fetch ONLY the AIS PDF
                    # from Activity History. TIS is not re-downloaded here (it was
                    # already grabbed during the Request step).
                    await self._ensure_dashboard(page)
                    set_status(pan, "⏳ Downloading AIS from Activity History...")

                    status = await run_download_ais_tis(
                        page, fy, out, self.log, pan=pan, dob=dob,
                        dl_ais=True, dl_tis=False,
                        should_continue=lambda: self.is_running,
                        status_callback=lambda t, _p=pan: set_status(_p, t))

                    if status == "downloaded":
                        set_status(pan, "✅ AIS Downloaded")
                    elif status == "not_found":
                        set_status(pan,
                            "⬜ No queued AIS for this FY — run Download / Request TIS & AIS first")
                    elif status == "timeout":
                        set_status(pan,
                            "🕐 AIS still generating — try again in a few minutes")
                    elif status == "aborted":
                        set_status(pan, "⏹ Stopped")
                    else:
                        set_status(pan, "❌ AIS download incomplete — check logs")

                if self.is_running:
                    await logout_itd(page, self.log)
                    page = None

                pan_masked = pan[:3] + "XXXXXXX" if pan and len(pan) >= 3 else "UNKNOWN"
                self.log(f"[Victory] {pan_masked} done.")

            except Exception as e:
                pan_masked = pan[:3] + "XXXXXXX" if pan and len(pan) >= 3 else "UNKNOWN"
                self.log(f"[Error] {pan_masked}: {e}")
                # Record the failure so the summary dialog/counts reflect it.
                self._ais_results[pan] = "failed"
                self._last_errors[pan] = str(e)
                err_short = str(e)
                if len(err_short) > 60:
                    err_short = err_short[:57] + "..."
                set_status(pan, f"❌ Failed — {err_short}")
                if page:
                    try: await logout_itd(page, self.log)
                    except Exception: pass
            await asyncio.sleep(3)

        await browser_manager.close()
        self.log("[System] Batch finished.")

    async def _ensure_dashboard(self, page):
        """Navigate back to ITD dashboard if not already there."""
        try:
            if "dashboard" not in page.url.lower():
                await page.goto(
                    "https://eportal.incometax.gov.in/iec/fo/dashboard",
                    wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
        except Exception:
            pass


def _fatal(msg: str):
    """Show a visible error dialog even before QApplication exists, then exit."""
    try:
        # Try Qt dialog first (works if Qt DLLs loaded successfully)
        _a = QApplication.instance() or QApplication(sys.argv)
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox()
        box.setWindowTitle("AayDocCapio — Startup Error")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText("AayDocCapio could not start.")
        box.setDetailedText(msg)
        box.exec()
    except Exception:
        # Qt itself failed — fall back to Windows MessageBox via ctypes
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"AayDocCapio could not start.\n\n{msg}\n\n"
                "If this persists, install the Microsoft Visual C++ Redistributable:\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe",
                "AayDocCapio — Startup Error",
                0x10  # MB_ICONERROR
            )
        except Exception:
            pass
    sys.exit(1)


if __name__ == "__main__":
    # Called by Inno Setup [Run] step to pre-install Chromium silently
    if "--install-browsers" in sys.argv:
        from automation.browser import _install_chromium
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_install_chromium())
        except Exception as e:
            print(f"Browser install failed: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            loop.close()
        sys.exit(0)

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("AayDocCapio")
        app.setDesktopFileName("aay-doc-capio")
        app.setStyle("Fusion")
        from PyQt6.QtGui import QFontDatabase
        _fonts_dir = os.path.join(_bundled_dir(), "resources", "fonts")
        if os.path.isdir(_fonts_dir):
            for _ttf in os.listdir(_fonts_dir):
                if _ttf.endswith(".ttf"):
                    QFontDatabase.addApplicationFont(os.path.join(_fonts_dir, _ttf))
        app.setStyleSheet(APP_STYLE)
        window = AayDocCapioApp()
        _app_icon_path = os.path.join(_bundled_dir(), "resources", "app_icon.png")
        if os.path.exists(_app_icon_path):
            _icon = QIcon(_app_icon_path)
            app.setWindowIcon(_icon)
            window.setWindowIcon(_icon)
        window.show()
        sys.exit(app.exec())
    except Exception as _startup_err:
        import traceback
        _fatal(traceback.format_exc())

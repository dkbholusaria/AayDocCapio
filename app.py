"""
app_qt.py — PyQt6 port of Tax Downloader
Install: pip install PyQt6
Run:     python3 app_qt.py
"""
import sys, os, json, asyncio, threading
import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QFileDialog, QScrollArea,
    QTabWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QMessageBox, QTextEdit, QDialog, QRadioButton, QSplitter, QSizePolicy,
    QGraphicsDropShadowEffect, QListView, QStyledItemDelegate,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QMetaObject, Q_ARG, QModelIndex
from PyQt6.QtGui import QFont, QTextCursor, QColor, QRegularExpressionValidator, QPalette
from PyQt6.QtCore import QRegularExpression

def _app_dir() -> str:
    """
    Writable user-data directory for vault, settings, and outputs.
    - Windows frozen .exe : %LOCALAPPDATA%\\ITDDocsDownloader
    - Linux/WSL frozen    : ~/.local/share/ITDDocsDownloader
    - Running as script   : folder containing app.py
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        else:
            base = os.path.join(os.path.expanduser("~"), ".local", "share")
        data_dir = os.path.join(base, "ITDDocsDownloader")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    return os.path.dirname(os.path.abspath(__file__))


def _bundled_dir() -> str:
    """
    Directory for read-only assets bundled inside the .exe (_MEIPASS).
    Falls back to _app_dir() when running as a script.
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


sys.path.append(_bundled_dir())
from vault import VaultManager
from automation.browser import browser_manager
from automation.auth import login_itd, logout_itd
from automation.downloader_26as import download_26as
from automation.downloader_ais_tis import download_ais_tis


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
QMainWindow, QDialog { background: #F5F7FA; }
QWidget { font-family: 'Roboto', 'Segoe UI', Arial, sans-serif; }
QLabel { color: #1a1a1a; font-size: 12px; }

QLineEdit {
    background: #FFFFFF;
    border: 1.5px solid #E2E8F0;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
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
    font-size: 12px;
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
    font-size: 12px;
    font-weight: 600;
    border-bottom: 2px solid transparent;
    margin-bottom: 0px;
}
QTabBar::tab:selected { color: #1D4ED8; border-bottom: 2px solid #2563EB; }
QTabBar::tab:hover:!selected { color: #334155; }

QCheckBox { font-size: 12px; color: #1a1a1a; spacing: 8px; background: transparent; }
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


# ── Main Window ───────────────────────────────────────────────────────────────
class TaxDownloaderApp(QMainWindow):
    _log_signal = pyqtSignal(str)
    _batch_done_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tax Downloader — Standalone Secure Utility")
        self.setMinimumSize(1100, 720)
        self.resize(1200, 780)

        self.vault = VaultManager(
            vault_path=os.path.join(_app_dir(), "tax_vault.json"))
        self.selected_ids = set()
        self.editing_id = None
        self.is_running = False
        self._checkbox_map = {}

        self._log_signal.connect(self._append_log)
        self._batch_done_signal.connect(self._on_batch_done)

        try:
            with open("app.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== Session Started {get_timestamp()} ===\n")
        except Exception:
            pass

        self._build_ui()
        self.refresh_grid()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        root = QVBoxLayout(root_widget)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self._mk_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet("QSplitter::handle{background:#E2E8F0;}")
        left = self._mk_left_panel()
        left.setFixedWidth(340)
        splitter.addWidget(left)
        splitter.addWidget(self._mk_right_panel())
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        root.addWidget(self._mk_footer())

    def _mk_header(self):
        hdr = QFrame()
        hdr.setFixedHeight(58)
        hdr.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                          "stop:0 #0F2056, stop:0.45 #1E3A8A, stop:1 #2563EB); }")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 0, 24, 0)
        hl.setSpacing(0)

        # Accent bar on left
        accent = QFrame()
        accent.setFixedSize(4, 32)
        accent.setStyleSheet("background:#60A5FA; border-radius:2px;")
        hl.addWidget(accent)
        hl.addSpacing(14)

        title = QLabel("TAX DOWNLOADER")
        title.setStyleSheet("color:#F8FAFC; font-size:16px; font-weight:700; letter-spacing:1px;")
        hl.addWidget(title)
        hl.addSpacing(16)

        sep = QFrame()
        sep.setFixedSize(1, 22)
        sep.setStyleSheet("background:#3B5EA6;")
        hl.addWidget(sep)
        hl.addSpacing(16)

        sub = QLabel("ITD Bulk Document Downloader  —  Form 26AS · AIS · TIS")
        sub.setStyleSheet("color:#93C5FD; font-size:12px;")
        hl.addWidget(sub)
        hl.addStretch()
        return hdr

    def _mk_left_panel(self):
        panel = QWidget()
        panel.setStyleSheet("background:#FFFFFF;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane{border:none; background:transparent;}"
                           "QTabBar{background:#F8FAFC; border-bottom:1px solid #E2E8F0;}"
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
        panel.setStyleSheet("background:#F5F7FA;")
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

        layout.addWidget(self._mk_col_header())
        layout.addWidget(self._mk_client_scroll(), 1)

        ctrl = self._mk_control_bar()
        ctrl.setGraphicsEffect(_shadow(18, 3, 18))
        layout.addWidget(ctrl)
        return panel

    def _mk_settings_bar(self):
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setStyleSheet("QFrame{background:#FFFFFF;border-radius:10px;}")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(0)
        hl.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        def _cap(text):
            l = QLabel(text)
            l.setStyleSheet("color:#94A3B8;font-size:9px;font-weight:700;"
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
        self.ay_combo.setFixedWidth(185)
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

        hl.addSpacing(20); hl.addWidget(_divider()); hl.addSpacing(20)

        # ── Documents ─────────────────────────────────────────────────────────
        doc_w = QFrame()
        doc_w.setStyleSheet(
            "QFrame{border:1px solid #D1D5DB;border-radius:6px;background:transparent;}"
            "QCheckBox{border:none;background:transparent;font-size:12px;"
            "font-weight:600;color:#1a1a1a;spacing:5px;}"
            "QCheckBox::indicator{border:1.5px solid #CBD5E1;border-radius:3px;"
            "background:#FFF;width:14px;height:14px;}"
            "QCheckBox::indicator:checked{background:#2563EB;border-color:#2563EB;"
            "image:url(resources/check.png);}"
        )
        doc_l = QHBoxLayout(doc_w)
        doc_l.setContentsMargins(10, 4, 10, 4); doc_l.setSpacing(12)
        self.chk_26as = QCheckBox("26AS"); self.chk_26as.setChecked(True)
        self.chk_ais  = QCheckBox("AIS");  self.chk_ais.setChecked(True)
        self.chk_tis  = QCheckBox("TIS");  self.chk_tis.setChecked(True)
        for c in (self.chk_26as, self.chk_ais, self.chk_tis):
            doc_l.addWidget(c)

        doc_col = QWidget(); doc_col.setStyleSheet("background:transparent;")
        doc_vl = QVBoxLayout(doc_col); doc_vl.setContentsMargins(0,0,0,0); doc_vl.setSpacing(2)
        doc_vl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        doc_vl.addWidget(_cap("DOCUMENTS"))
        doc_vl.addWidget(doc_w)
        hl.addWidget(doc_col)

        hl.addSpacing(20); hl.addWidget(_divider()); hl.addSpacing(20)

        # ── Output Directory ──────────────────────────────────────────────────
        default_dir = self.vault.get_setting(
            "download_root_dir",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs"))
        self.dir_lbl = QLabel(default_dir)
        self.dir_lbl.setStyleSheet("color:#334155;font-size:11px;background:transparent;")
        self.dir_lbl.setWordWrap(False)
        self.dir_lbl.setMaximumWidth(220)
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

    def _mk_col_header(self):
        hdr = QFrame()
        hdr.setFixedHeight(34)
        hdr.setStyleSheet(
            "QFrame{"
            "background:#F1F5F9;"
            "border:1.5px solid #CBD5E1;"
            "border-radius:7px;"
            "}"
        )
        hl = QHBoxLayout(hdr); hl.setContentsMargins(36, 0, 15, 0); hl.setSpacing(6)
        for text, width in [("Name", 0),
                             ("PAN", 120), ("Date of Birth", 110), ("Actions", 62)]:
            l = QLabel(text)
            l.setStyleSheet("color:#64748B; font-size:10px; font-weight:700; letter-spacing:0.8px; background:transparent; border:none;")
            if width:
                l.setFixedWidth(width)
            else:
                l.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            hl.addWidget(l)
        return hdr

    def _mk_client_scroll(self):
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.clients_widget = QWidget()
        self.clients_widget.setStyleSheet("background:transparent;")
        self.clients_layout = QVBoxLayout(self.clients_widget)
        self.clients_layout.setSpacing(3)
        self.clients_layout.setContentsMargins(0, 0, 0, 0)
        self.clients_layout.addStretch()

        self.scroll_area.setWidget(self.clients_widget)
        return self.scroll_area

    def _mk_control_bar(self):
        bar = QFrame()
        bar.setFixedHeight(54)
        bar.setStyleSheet("QFrame{background:#FFFFFF;border-radius:10px;}")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(22, 0, 16, 0)

        self.select_all_cb = QCheckBox("Select / Deselect All")
        self.select_all_cb.setStyleSheet("font-size:12px; font-weight:600; color:#334155; background:transparent;")
        self.select_all_cb.toggled.connect(self.toggle_select_all)
        hl.addWidget(self.select_all_cb)
        hl.addStretch()

        self.btn_delete_sel = _btn("🗑  Delete Selected", "danger", height=34, min_width=130)
        self.btn_delete_sel.setEnabled(False)
        self.btn_delete_sel.clicked.connect(self.delete_selected)
        hl.addWidget(self.btn_delete_sel)
        hl.addSpacing(8)

        self.btn_stop = _btn("⏹  Stop", "danger", height=34, min_width=90)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_automation)
        hl.addWidget(self.btn_stop)
        hl.addSpacing(8)

        self.btn_run = _btn("▶   Start Download", "success", height=34, min_width=160)
        self.btn_run.setStyleSheet(
            self.btn_run.styleSheet().replace("font-size:12px", "font-size:13px"))
        self.btn_run.clicked.connect(self.start_automation)
        hl.addWidget(self.btn_run)

        return bar

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

    def _apply_row_style(self, row, selected, index=0):
        if selected:
            row.setStyleSheet(
                "QFrame#row_frame{background:#1E3A8A;border-radius:6px;border:none;}"
                "QLabel{color:#FFFFFF; background:transparent;}"
                "QCheckBox{color:#FFFFFF;background:transparent;}"
                "QPushButton{color:#93C5FD; background:transparent; border:none;}"
                "QPushButton:hover{color:#FFFFFF;}")
        else:
            bg = "#FFFFFF" if index % 2 == 0 else "#F8FAFC"
            row.setStyleSheet(
                f"QFrame#row_frame{{background:{bg};border-radius:6px;border:none;}}"
                f"QFrame#row_frame:hover{{background:#EFF6FF;}}"
                "QLabel{color:#0F172A;}"
                "QCheckBox{background:transparent;}")

    def _apply_filter(self, text=""):
        q = text.strip().lower()
        for a_id, row in self._row_frames.items():
            a = next((x for x in self.assessee_list if x.get("id") == a_id), None)
            if not a:
                continue
            visible = (not q
                       or q in a.get("name", "").lower()
                       or q in a.get("pan", "").lower())
            row.setVisible(visible)

    def refresh_grid(self):
        while self.clients_layout.count() > 1:
            item = self.clients_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._checkbox_map.clear()
        self.assessee_list = self.vault.get_all_assessees()

        if not self.assessee_list:
            empty = _lbl(
                "No clients registered. Use the profile form or bulk upload to add assessees.",
                11, color="#475569")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self.clients_layout.insertWidget(0, empty)
            self.select_all_cb.setEnabled(False)
            self._update_count()
            return

        self.select_all_cb.setEnabled(True)
        self._row_frames = {}
        for i, a in enumerate(self.assessee_list):
            a_id = a.get("id")
            is_selected = a_id in self.selected_ids
            row = QFrame()
            row.setObjectName("row_frame")
            row.setFixedHeight(38)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            self._row_frames[a_id] = row
            self._apply_row_style(row, is_selected, i)
            hl = QHBoxLayout(row); hl.setContentsMargins(10, 0, 15, 0); hl.setSpacing(6)

            cb = QCheckBox()
            cb.setFixedWidth(20)
            cb.setChecked(a_id in self.selected_ids)
            cb.toggled.connect(lambda checked, id_=a_id: self._on_check(id_, checked))
            self._checkbox_map[a_id] = cb
            hl.addWidget(cb)

            # Clicking anywhere on the row (except action buttons) toggles selection.
            # Guard: ignore if a combo popup is open anywhere in the window.
            def _row_click(_, id_=a_id, c=cb):
                if self.ay_combo._popup_was_open:
                    return
                c.setChecked(not c.isChecked())
            row.mousePressEvent = _row_click

            name_l = QLabel(a.get("name", ""))
            name_l.setObjectName("name_l")
            name_l.setStyleSheet("font-size:13px;")
            name_l.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            hl.addWidget(name_l, 1)

            pan_l = QLabel(a.get("pan", ""))
            pan_l.setObjectName("pan_l")
            pan_l.setFixedWidth(120)
            pan_l.setStyleSheet("font-size:13px; font-weight:bold;")
            hl.addWidget(pan_l)

            dob_l = QLabel(a.get("dob", ""))
            dob_l.setFixedWidth(110)
            dob_l.setStyleSheet("font-size:13px;")
            hl.addWidget(dob_l)

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
            acts = QWidget(); acts.setFixedWidth(62)
            acts.setStyleSheet("background:transparent;")
            al = QHBoxLayout(acts); al.setContentsMargins(0,0,0,0); al.setSpacing(6)
            al.addWidget(edit_btn); al.addWidget(del_btn)
            hl.addWidget(acts)

            self.clients_layout.insertWidget(self.clients_layout.count() - 1, row)

        self._update_count()
        if hasattr(self, "search_box"):
            self._apply_filter(self.search_box.text())

    def _on_check(self, id_, checked):
        if checked:
            self.selected_ids.add(id_)
        else:
            self.selected_ids.discard(id_)
        if hasattr(self, "_row_frames") and id_ in self._row_frames:
            idx = next((i for i, a in enumerate(self.assessee_list) if a.get("id") == id_), 0)
            self._apply_row_style(self._row_frames[id_], checked, idx)
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
        self._update_count()

    def _update_count(self):
        n = len(self.selected_ids)
        self.lbl_selected.setText(f"{n} selected" if n else "")
        total = len(self._checkbox_map)
        self.select_all_cb.blockSignals(True)
        self.select_all_cb.setChecked(total > 0 and n == total)
        self.select_all_cb.blockSignals(False)
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

    # ── Automation ────────────────────────────────────────────────────────────

    def _lock_ui(self, lock: bool):
        for w in (self.entry_name, self.entry_pan, self.entry_dob, self.entry_pwd,
                  self.btn_save, self.btn_clear, self.btn_bulk_import, self.btn_template,
                  self.btn_export, self.ay_combo, self.chk_26as, self.chk_ais, self.chk_tis,
                  self.select_all_cb, self.btn_delete_sel):
            w.setEnabled(not lock)

    def start_automation(self):
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
        if not (self.chk_26as.isChecked() or self.chk_ais.isChecked() or self.chk_tis.isChecked()):
            QMessageBox.warning(self, "Selection Required",
                "Select at least one document type.")
            return

        self.is_running = True
        self.btn_run.setEnabled(False); self.btn_run.setText("⏳ RUNNING...")
        self.btn_stop.setEnabled(True)
        self._lock_ui(True)
        self.log_box.clear()
        self.log("[System] Launching automation session...")

        targets = [a for a in self.assessee_list if a.get("id") in self.selected_ids]
        threading.Thread(
            target=self._run_wrapper,
            args=(targets, ay, fy, self.dir_lbl.text(),
                  self.chk_26as.isChecked(), self.chk_ais.isChecked(), self.chk_tis.isChecked()),
            daemon=True
        ).start()

    def stop_automation(self):
        if not self.is_running:
            return
        if QMessageBox.question(self, "Stop",
            "Abort the active batch?") == QMessageBox.StandardButton.Yes:
            self.log("[System] Abort requested...")
            self.is_running = False

    def _run_wrapper(self, targets, ay, fy, root_dir, dl_26as, dl_ais, dl_tis):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self._execute_batch(targets, ay, fy, root_dir, dl_26as, dl_ais, dl_tis))
        except Exception as e:
            self.log(f"[System Error] Batch crashed: {e}")
        finally:
            loop.close()
            self.is_running = False
            self._batch_done_signal.emit()

    def _on_batch_done(self):
        self.btn_run.setEnabled(True); self.btn_run.setText("▶  START AUTO DOWNLOAD")
        self.btn_stop.setEnabled(False)
        self._lock_ui(False)
        self.log("[System] Engine Idle.")

    async def _execute_batch(self, targets, ay, fy, root_dir, dl_26as, dl_ais, dl_tis):
        self.log(f"[System] Batch: {len(targets)} assessees | AY: {ay}")
        try:
            context = await browser_manager.get_context(log_callback=self.log, interactive=True)
        except Exception as e:
            self.log(f"[System Error] Browser init failed: {e}"); return

        for i, target in enumerate(targets):
            if not self.is_running:
                self.log("[System] Aborted."); break

            pan = target.get("pan"); name = target.get("name"); dob = target.get("dob", "")
            self.log("──────────────────────────────────────────────────")
            self.log(f"[{i+1}/{len(targets)}] {name} ({pan})")

            name_safe = "".join(c if c.isalnum() or c in " _-" else "" for c in name)
            out = os.path.join(root_dir, f"{pan}-{name_safe}", f"AY_{ay.replace('-','_')}")

            page = None
            try:
                page = await login_itd(pan, target.get("password"), self.log, context)
                if dl_26as and self.is_running:
                    await download_26as(page, ay, out, self.log, pan=pan, dob=dob)
                if (dl_ais or dl_tis) and self.is_running:
                    try:
                        await page.bring_to_front()
                        if "dashboard" not in page.url.lower():
                            await page.goto(
                                "https://eportal.incometax.gov.in/iec/fo/dashboard",
                                wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(2)
                    except Exception:
                        pass
                    await download_ais_tis(page, fy, out, self.log, pan=pan)
                if self.is_running:
                    await logout_itd(page, self.log); page = None
                self.log(f"[Victory] {pan} complete.")
            except Exception as e:
                self.log(f"[Error] {pan}: {e}")
                if page:
                    try: await logout_itd(page, self.log)
                    except Exception: pass
            await asyncio.sleep(3)

        await browser_manager.close()
        self.log("[System] Batch finished.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    window = TaxDownloaderApp()
    window.show()
    sys.exit(app.exec())

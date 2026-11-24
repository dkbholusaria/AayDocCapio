"""
AayDocCapio — ITD Bulk Document Downloader (Form 26AS, AIS, TIS)
Run:  python3 app.py
"""
from version import __version__ as APP_VERSION

import sys, os, json, asyncio, threading, datetime, logging, time, re, html
from urllib.parse import urlencode

# Force XCB (X11) backend on Linux/WSL2 — must be set before Qt initialises.
# WSLg sets WAYLAND_DISPLAY which Qt6 prefers; unsetting it prevents the
# "Wayland connection broke" hang that requires WSL restart to fix.
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    if os.environ.get("QT_QPA_PLATFORM") == "xcb":
        os.environ.pop("WAYLAND_DISPLAY", None)
from themes import THEMES, ThemeColors, build_stylesheet, get_theme, MONO_FONT_NAME as _MONO_FONT
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QFileDialog,
    QHBoxLayout, QVBoxLayout,
    QMessageBox, QTextEdit, QDialog, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QToolButton, QMenu, QCalendarWidget, QSystemTrayIcon, QButtonGroup,
    QGraphicsDropShadowEffect, QStackedWidget, QRadioButton,
    QGridLayout, QAbstractButton, QScrollArea,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, pyqtSlot, QTimer, QMetaObject, Q_ARG, QUrl,
    QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import (
    QFont, QTextCursor, QColor, QRegularExpressionValidator, QPalette, QAction,
    QIcon, QPixmap, QDesktopServices, QKeySequence,
)
from ui import shortcuts as _shortcuts
from PyQt6.QtCore import QRegularExpression

from config import _app_dir, _default_download_dir, _bundled_dir
from utils import get_timestamp, notify_windows
from ui._theme import _t
from ui.helpers import _btn, _lbl, _shadow
from ui.nav_shell import NavShell, _svg_pixmap
from ui.widgets import StyledComboBox, CheckableComboBox, ClickableCard
from ui.dialogs import (
    ManageYearsDialog, BatchProgressDialog, DownloadPickerDialog,
    GenerateChallansDialog, ChallanGenerationProgressDialog,
    ReturnStatusDialog, ReturnStatusProgressDialog, ReturnStatusTab, EmailLogDialog,
    EProceedingsDialog, EAutoFetchSettingsDialog,
)
from ui.log_history import LogHistoryDialog, LogStore
from ui.eproceedings import EProceedingsWorkspace
from ui.litigation import LitigationPage
from automation.errors import _friendly_error

sys.path.insert(0, _bundled_dir())

try:
    from vault import VaultManager
    from automation.browser import browser_manager
    from automation.auth import login_itd, logout_itd
    from automation.batch_handlers import HANDLERS, DOC_TYPE_LABELS, ordered_doc_types
    from forms import form_for, DEFAULT_FORM
except Exception as _import_err:
    import traceback
    _msg = (
        f"Failed to load required modules.\n\n"
        f"{traceback.format_exc()}\n\n"
        f"bundled_dir: {_bundled_dir()}\n"
        f"sys.path: {sys.path[:5]}"
    )
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, _msg, "AayDocCapio — Startup Error", 0x10)
    except Exception:
        pass
    sys.exit(1)



# ── Client Picker Dialog ──────────────────────────────────────────────────────
class _ClientPickerDialog(QDialog):
    """Reusable popup for selecting one or more clients before Edit / Delete.

    mode='edit'   — single-select
    mode='delete' — multi-select with table layout and selected count
    """

    def __init__(self, parent, clients, mode):
        super().__init__(parent)
        self._mode    = mode
        self._clients = clients          # list of {id, name, pan}

        t = _t()
        self.setWindowTitle("Select Client to Edit" if mode == "edit"
                            else "Select Client(s) to Delete")
        self.setMinimumWidth(560)
        self.setMinimumHeight(460)
        self.resize(620, 520)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(
            f"QDialog{{background:{t.bg_window};}}"
            f"QLabel{{background:transparent;border:none;color:{t.text_primary};font-size:12px;}}"
            f"QLineEdit{{border:1px solid {t.border};border-radius:6px;padding:5px 10px;"
            f"font-size:12px;background:{t.bg_input};color:{t.text_primary};}}"
            f"QTableWidget{{border:1px solid {t.border};border-radius:6px;"
            f"background:{t.bg_table};gridline-color:{t.grid};outline:0;}}"
            f"QTableWidget::item{{padding:4px 8px;border:none;}}"
            f"QTableWidget::item:selected{{background:{t.accent};color:{t.accent_text};}}"
            f"QHeaderView::section{{background:{t.bg_header};color:{t.text_muted};"
            f"border:none;border-right:1px solid {t.border};"
            f"border-bottom:1px solid {t.border};font-weight:bold;"
            f"font-size:11px;height:30px;padding:0 8px;}}"
            f"QCheckBox::indicator{{width:14px;height:14px;border:1.5px solid {t.border};"
            f"border-radius:3px;background:{t.bg_checkbox};}}"
            f"QCheckBox::indicator:checked{{background:{t.accent};border-color:{t.accent};"
            f"image:url(resources/check_white.png);}}"
        )

        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(8)

        # Header row: subtitle + selected count
        hdr_row = QHBoxLayout()
        sub = "Select one client to edit:" if mode == "edit" else "Select clients to delete:"
        sub_lbl = QLabel(sub)
        sub_lbl.setStyleSheet(f"color:{t.text_muted};font-size:11px;")
        hdr_row.addWidget(sub_lbl)
        hdr_row.addStretch()
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(f"color:{t.accent};font-size:11px;font-weight:bold;")
        hdr_row.addWidget(self._count_lbl)
        vl.addLayout(hdr_row)

        # Search box
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name or PAN…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        vl.addWidget(self._search)

        # Table
        self._table = QTableWidget(len(clients), 3)
        self._table.setHorizontalHeaderLabels(["", "Name", "PAN"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setSectionsClickable(True)
        self._table.setSortingEnabled(True)
        self._table.setColumnWidth(0, 36)
        self._table.setColumnWidth(1, 280)
        self._table.setColumnWidth(2, 120)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            f"QTableWidget{{alternate-background-color:{t.bg_table_alt};}}")

        self._checks = []   # (client_id, QCheckBox)
        for row, c in enumerate(clients):
            self._table.setRowHeight(row, 34)

            cb_widget = QWidget()
            cb_widget.setStyleSheet("background:transparent;")
            cb_lay = QHBoxLayout(cb_widget)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox()
            cb.stateChanged.connect(self._on_check_changed)
            cb_lay.addWidget(cb)
            self._table.setCellWidget(row, 0, cb_widget)
            self._checks.append((c["id"], cb))

            name_item = QTableWidgetItem(c["name"])
            name_item.setForeground(QColor(t.text_primary))
            self._table.setItem(row, 1, name_item)

            pan_item = QTableWidgetItem(c["pan"])
            pan_item.setForeground(QColor(t.text_muted))
            pan_item.setFont(QFont(_MONO_FONT, 10))
            pan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 2, pan_item)

        # Click on row toggles checkbox
        self._table.cellClicked.connect(self._on_cell_clicked)
        vl.addWidget(self._table, stretch=1)

        # Footer
        from ui.helpers import _btn as _hbtn
        btn_row = QHBoxLayout()
        if mode == "delete":
            sel_all_btn = _hbtn("Select All", "outline", height=30, icon="btn_select_all.png")
            sel_all_btn.clicked.connect(self._select_all)
            btn_row.addWidget(sel_all_btn)
            sel_none_btn = _hbtn("Select None", "outline", height=30, icon="btn_select_none.png")
            sel_none_btn.clicked.connect(self._select_none)
            btn_row.addWidget(sel_none_btn)
        btn_row.addStretch()
        cancel_btn = _hbtn("Cancel", "secondary", height=32, icon="btn_cancel.png")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addSpacing(8)
        ok_style = "delete" if mode == "delete" else "primary"
        ok_icon  = "btn_delete.png" if mode == "delete" else "icon_edit.png"
        self._ok_btn = _hbtn("Edit" if mode == "edit" else "Delete", ok_style, height=32, icon=ok_icon)
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._ok_btn)
        vl.addLayout(btn_row)

    def _on_cell_clicked(self, row, col):
        _, cb = self._checks[row]
        cb.setChecked(not cb.isChecked())

    def _select_all(self):
        for row, (_, cb) in enumerate(self._checks):
            if not self._table.isRowHidden(row):
                cb.setChecked(True)

    def _select_none(self):
        for _, cb in self._checks:
            cb.setChecked(False)

    def _on_search(self, text):
        q = text.strip().lower()
        for row, (c, (_, cb)) in enumerate(zip(self._clients, self._checks)):
            match = not q or q in c["name"].lower() or q in c["pan"].lower()
            self._table.setRowHidden(row, not match)
            if not match:
                cb.setChecked(False)

    def _on_check_changed(self, _state):
        if self._mode == "edit":
            sender = self.sender()
            if sender and sender.isChecked():
                for _, cb in self._checks:
                    if cb is not sender:
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
        n = sum(1 for _, cb in self._checks if cb.isChecked())
        self._ok_btn.setEnabled(n == 1 if self._mode == "edit" else n >= 1)
        if self._mode == "delete":
            self._count_lbl.setText(f"{n} selected" if n else "")

    @property
    def selected_ids(self):
        return [id_ for id_, cb in self._checks if cb.isChecked()]


# ── Main Window ───────────────────────────────────────────────────────────────
class AayDocCapioApp(QMainWindow):
    _log_signal = pyqtSignal(str)
    _batch_done_signal = pyqtSignal()
    _show_progress_signal = pyqtSignal(list, object, list, str, str)   # (targets, selected_docs: set, year_specs, output_dir, year_tag)
    _challan_done_signal = pyqtSignal()
    _show_challan_progress_signal = pyqtSignal(list, str, str, str)   # (targets, fy_value, type_label, output_dir)
    _tds_challan_done_signal = pyqtSignal()
    _show_tds_challan_progress_signal = pyqtSignal(list, str, str, str)
    _return_status_done_signal = pyqtSignal()
    _show_return_status_progress_signal = pyqtSignal(list, str)   # (targets, ay_value)
    _eproc_auto_done_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AayDocCapio — Tax Documents. Delivered to You.")
        self.setMinimumSize(1100, 720)
        self.resize(1200, 780)
        from automation.emailer import log_session_start
        log_session_start()

        self.vault = VaultManager(
            vault_path=os.path.join(_app_dir(), "tax_vault.json"))
        self.log_store = LogStore()
        self.selected_ids = set()
        self.editing_id = None
        self.is_running = False
        self._checkbox_map = {}
        self._id_to_row: dict = {}
        
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
        self._last_selected_docs = set()  # selected_docs of last completed batch
        self._ais_results = {}            # pan → "instant" | "queued" | "failed" | "skipped"
        self._last_errors = {}            # pan → error message string
        self._batch_loop = None           # asyncio event loop for the running batch
        self._batch_task = None           # asyncio Task for the running batch
        self._batch_aborted = False       # True if user clicked Stop
        self._skip_current  = False       # True when user clicks Skip for current client
        self._last_batch_params = None    # (year_specs, root_dir, selected_docs) for resume

        self._log_signal.connect(self._append_log)
        self._batch_done_signal.connect(self._on_batch_done)
        self._show_progress_signal.connect(self._show_progress_dialog)
        self._progress_dialog = None   # BatchProgressDialog instance

        # F-64: separate running/progress state from the download batch above
        # — a challan-generation run and a download run are different
        # in-flight flows, each with their own is_running-style guard.
        self._challan_running = False
        self._challan_loop = None
        self._challan_task = None
        self._challan_aborted = False
        self._challan_progress_dialog = None
        self._challan_done_signal.connect(self._on_challan_batch_done)
        self._show_challan_progress_signal.connect(self._show_challan_progress_dialog)

        # F-4: TDS/TCS challans run as their own flow (TAN clients, section-wise
        # amounts) with the same threading/progress pattern as F-64 above.
        self._tds_challan_running = False
        self._tds_challan_loop = None
        self._tds_challan_task = None
        self._tds_challan_aborted = False
        self._tds_challan_progress_dialog = None
        self._tds_challan_done_signal.connect(self._on_tds_challan_batch_done)
        self._show_tds_challan_progress_signal.connect(self._show_tds_challan_progress_dialog)
        # F-8: which column label the generic batch progress dialog uses.
        self._progress_id_label = "PAN"

        self._retstatus_running = False
        self._retstatus_loop = None
        self._retstatus_task = None
        self._retstatus_aborted = False
        self._retstatus_progress_dialog = None
        self._retstatus_on_done = None
        self._return_status_done_signal.connect(self._on_return_status_batch_done)
        self._show_return_status_progress_signal.connect(self._show_return_status_progress_dialog)

        self._eproc_auto_running = False
        self._eproc_auto_loop = None
        self._eproc_auto_task = None
        self._eproc_auto_aborted = False
        self._eproc_auto_paused = False
        self._eproc_auto_skip_current = False
        self._eproc_auto_skip_future = False
        self._eproc_auto_restart = False
        self._eproc_auto_stop_keeps = None
        self._eproc_auto_cfg = {}
        self._eproc_auto_run_clients = []
        self._eproc_auto_pending = []
        self._eproc_auto_tail = []
        self._eproc_auto_paths = {}
        self._eproc_auto_counts = {}
        self._eproc_auto_started_at = None
        self._eproc_auto_dialog = None
        self._eproc_auto_timer = None
        self._eproc_auto_done_signal.connect(self._on_eproc_auto_done)

        try:
            log_path = os.path.join(_app_dir(), "app.log")
            _MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB
            if os.path.exists(log_path) and os.path.getsize(log_path) > _MAX_LOG_BYTES:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(content[len(content) // 2:])
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n=== Session Started {get_timestamp()} ===\n")
            # Route stdlib logging (used by config._open_path etc.) to app.log
            _fh = logging.FileHandler(log_path, encoding="utf-8")
            _fh.setFormatter(logging.Formatter("%(asctime)s %(message)s",
                                               datefmt="%d-%m-%Y %H:%M:%S"))
            logging.getLogger().addHandler(_fh)
            logging.getLogger().setLevel(logging.INFO)
        except Exception:
            pass

        self._theme_pref = self.vault.get_setting("theme", "light")
        if self._theme_pref not in (*THEMES, "system"):
            self._theme_pref = "light"
        self._current_theme = self._resolve_theme(self._theme_pref)
        # F-17: widgets capture _t() while they are constructed, so the active
        # theme MUST be set before _build_ui(). Otherwise every inline style
        # baked into a page uses the light palette (white cards, dark text).
        import ui._theme as _theme_mod_build
        _theme_mod_build._active_theme = get_theme(self._current_theme)
        self._apply_palette(get_theme(self._current_theme))
        self._build_ui()
        self.refresh_grid()
        # Re-sync menu checks and widgets after the UI exists (no rebuild on
        # the first pass — construction already used the resolved theme).
        QTimer.singleShot(
            0, lambda: self._apply_theme(self._theme_pref, persist=False, rebuild_ui=False))
        self._watch_system_theme()
        self._setup_tray()

        client_count = len(self.vault.get_all_assessees())
        self.log(f"[System] AayDocCapio v{APP_VERSION} started — {client_count} client(s) in vault.")

        # Check Chromium on startup in background — installs silently if missing
        QTimer.singleShot(1500, self._check_browser)

        # Check for app updates 3s after startup
        QTimer.singleShot(3000, self._check_for_update)

        self._eproc_auto_init_timer()

    # ── System Tray ───────────────────────────────────────────────────────────

    def _setup_tray(self):
        """Create a persistent system-tray icon (always present, used during batch)."""
        # Prefer .ico on Windows — it contains all sizes (16/24/32/48…256px) for
        # pixel-perfect rendering at every DPI. Fall back to PNG on other platforms.
        res = os.path.join(_bundled_dir(), "resources")
        ico = os.path.join(res, "app_icon.ico")
        png = os.path.join(res, "app_icon.png")
        icon_path = ico if (sys.platform == "win32" and os.path.isfile(ico)) else png
        tray_icon = QIcon(icon_path) if os.path.isfile(icon_path) else self.windowIcon()

        self._tray = QSystemTrayIcon(tray_icon, self)
        self._tray.setToolTip("AayDocCapio")

        menu = QMenu()
        self._tray_restore_act = QAction("Restore", self)
        self._tray_restore_act.triggered.connect(self._tray_restore)
        self._tray_send_act = QAction("Send to Tray", self)
        self._tray_send_act.triggered.connect(self._tray_to_system_manual)
        self._tray_send_act.setVisible(False)
        self._tray_stop_act = QAction("Stop Batch", self)
        self._tray_stop_act.triggered.connect(self._tray_stop_active)
        self._tray_stop_act.setEnabled(False)
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(self._tray_restore_act)
        menu.addAction(self._tray_send_act)
        menu.addAction(self._tray_stop_act)
        menu.addSeparator()
        menu.addAction(quit_act)
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_tray_activated)
        # Don't show() the tray icon until we actually send to tray

    def _tray_to_system(self, n_clients: int):
        """Auto-hide to tray at batch start (called with client count)."""
        self._tray.setToolTip(f"AayDocCapio — Running ({n_clients} client(s)…)")
        self._tray_stop_act.setEnabled(True)
        self._tray_send_act.setVisible(False)  # hidden while already in tray
        self._tray.show()
        if self._progress_dialog:
            self._progress_dialog.hide()
        self.hide()
        self._tray_show_hint()

    def _tray_to_system_manual(self):
        """Send to tray on demand (from either progress dialog's Tray button,
        or the tray menu) — whichever batch is actually running (download or
        challan generation) is the one whose dialog gets hidden/counted."""
        if self._challan_running and self._challan_progress_dialog:
            n = len(self._challan_progress_dialog._targets)
        elif self._progress_dialog:
            n = len(self._progress_dialog._targets)
        else:
            n = 0
        self._tray.setToolTip(f"AayDocCapio — Running ({n} client(s)…)")
        self._tray_stop_act.setEnabled(True)
        self._tray_send_act.setVisible(False)  # hidden while already in tray
        self._tray.show()
        if self._progress_dialog:
            self._progress_dialog.hide()
        if self._challan_progress_dialog:
            self._challan_progress_dialog.hide()
        self.hide()
        self._tray_show_hint()

    def _tray_show_hint(self):
        """Show a Windows toast every time the app hides to tray."""
        notify_windows(
            "AayDocCapio is running in the background",
            "Click the tray icon to restore the window, or right-click for options.")

    def _tray_restore(self):
        """Restore main window and whichever progress dialog(s) from tray."""
        self._tray.hide()
        self._tray_send_act.setVisible(self.is_running or self._challan_running)
        self.show()
        self.showNormal()
        self.activateWindow()
        self.raise_()
        if self._progress_dialog:
            self._progress_dialog.show()
            self._progress_dialog.raise_()
            self._progress_dialog.activateWindow()
        if self._challan_progress_dialog:
            self._challan_progress_dialog.show()
            self._challan_progress_dialog.raise_()
            self._challan_progress_dialog.activateWindow()

    def _tray_stop_active(self):
        """Routes the tray menu's "Stop Batch" to whichever batch is
        actually running — download and challan generation each have their
        own stop function and own running flag."""
        if self.is_running:
            self.stop_automation()
        if self._challan_running:
            self.stop_challan_generation()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._tray_restore()

    def closeEvent(self, event):
        self.log("[System] AayDocCapio closed.")
        from automation.emailer import log_session_end
        log_session_end()
        if hasattr(self, "_tray"):
            self._tray.hide()
        super().closeEvent(event)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Menu bar ──────────────────────────────────────────────────────────
        menubar = self.menuBar()

        # Client Master menu
        cm_menu = menubar.addMenu("Client Master")
        def _micon(f):
            p = os.path.join(_bundled_dir(), "resources", "icons", f)
            return QIcon(QPixmap(p).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)) if os.path.isfile(p) else QIcon()
        act_add      = QAction(_micon("menu_add_client.png"), "Add New Client",           self); act_add.triggered.connect(self._open_add_client)
        act_edit_cl  = QAction(_micon("icon_edit.png"),       "Edit Client\u2026",        self); act_edit_cl.triggered.connect(self._pick_and_edit_client)
        act_del_cl   = QAction(_micon("icon_delete.png"),     "Delete Client(s)\u2026",   self); act_del_cl.triggered.connect(self._pick_and_delete_clients)
        act_imp      = QAction(_micon("menu_import.png"),     "Import from CSV / Excel",  self); act_imp.triggered.connect(self.bulk_import)
        act_exp      = QAction(_micon("menu_export.png"),     "Export Client Data",       self); act_exp.triggered.connect(self.export_data)
        act_tpl      = QAction(_micon("menu_template.png"),   "Download Import Template", self); act_tpl.triggered.connect(self.generate_template)
        act_groups   = QAction(_micon("btn_scan.png"),        "Manage Groups…",      self); act_groups.triggered.connect(self.open_manage_groups)
        self._act_add     = act_add
        self._act_edit_cl = act_edit_cl
        self._act_del_cl  = act_del_cl
        self._act_import  = act_imp
        self._act_export  = act_exp
        cm_menu.addAction(act_add)
        cm_menu.addSeparator()
        cm_menu.addAction(act_edit_cl)
        cm_menu.addAction(act_del_cl)
        cm_menu.addSeparator()
        cm_menu.addAction(act_groups)
        cm_menu.addSeparator()
        cm_menu.addAction(act_imp)
        cm_menu.addAction(act_exp)
        cm_menu.addSeparator()
        cm_menu.addAction(act_tpl)

        # Settings menu
        st_menu = menubar.addMenu("Settings")
        act_yr   = QAction(_micon("btn_scan.png"),          "Manage Assessment Years", self); act_yr.triggered.connect(self.open_manage_years)
        act_dir  = QAction(_micon("btn_browse_folder.png"), "Change Output Folder",    self); act_dir.triggered.connect(self.browse_output_dir)
        act_open = QAction(_micon("btn_browse.png"),        "Open Output Folder",      self); act_open.triggered.connect(self._open_output_folder)
        st_menu.addAction(act_yr)
        st_menu.addAction(act_dir)
        st_menu.addAction(act_open)
        st_menu.addSeparator()
        act_email = QAction(_micon("icon_email.png"), "Email Settings…", self); act_email.triggered.connect(self._open_email_settings)
        st_menu.addAction(act_email)
        st_menu.addSeparator()

        # Appearance submenu — built dynamically from THEMES registry, plus
        # the F-17 "Follow system" preference.
        appear_menu = st_menu.addMenu(_micon("menu_appearance.png"), "Appearance")
        _icons = {"light": "☀", "dark": "🌙"}
        for theme_key, theme_colors in THEMES.items():
            icon = _icons.get(theme_key, "●")
            act = QAction(f"{icon}  {theme_colors.name}", self)
            act.setCheckable(True)
            act.triggered.connect(lambda _, k=theme_key: self._apply_theme(k))
            setattr(self, f"_theme_{theme_key}_act", act)
            appear_menu.addAction(act)
        appear_menu.addSeparator()
        _sys_act = QAction("🖥  Follow system", self)
        _sys_act.setCheckable(True)
        _sys_act.setToolTip("Switch automatically with the operating system's light/dark setting")
        _sys_act.triggered.connect(lambda: self._apply_theme("system"))
        self._theme_system_act = _sys_act
        appear_menu.addAction(_sys_act)

        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        act_convert = QAction(_micon("menu_export.png"),   "Convert 26AS TXT → Excel + HTML…", self)
        act_convert.triggered.connect(self._convert_26as_manual)
        tools_menu.addAction(act_convert)
        act_ais_convert = QAction(_micon("menu_template.png"), "Convert AIS JSON → Excel…", self)
        act_ais_convert.triggered.connect(self._convert_ais_json_manual)
        tools_menu.addAction(act_ais_convert)
        tools_menu.addSeparator()
        act_mail = QAction(_micon("btn_send.png"), "Mail Docs to Clients…", self)
        act_mail.triggered.connect(self._open_mail_docs)
        tools_menu.addAction(act_mail)
        tools_menu.addSeparator()
        act_eproc = QAction(_micon("icon_preview.png"), "View e-Proceedings", self)
        act_eproc.triggered.connect(self._open_eproceedings_viewer)
        tools_menu.addAction(act_eproc)
        self._tools_menu = tools_menu

        # E-Pay Tax menu (F-64) — home for challan-generation features;
        # future Type-of-Payment additions (Demand Payment, Block Assessment,
        # etc.) get new items here rather than new toolbar buttons each time.
        epay_menu = menubar.addMenu("E-Pay Tax")
        act_gen_challans = QAction("Generate Tax Challans…", self)
        act_gen_challans.triggered.connect(self._open_generate_challans_dialog)
        epay_menu.addAction(act_gen_challans)
        act_gen_tds_challans = QAction("Generate TDS/TCS Challans…", self)
        act_gen_tds_challans.triggered.connect(self._open_generate_tds_challans_dialog)
        epay_menu.addAction(act_gen_tds_challans)
        act_dl_tds_challans = QAction("Download TDS/TCS Challans…", self)
        act_dl_tds_challans.triggered.connect(self._open_download_tds_challans_dialog)
        epay_menu.addAction(act_dl_tds_challans)
        epay_menu.addSeparator()
        act_view_challans = QAction("View Challans…", self)
        act_view_challans.triggered.connect(self._open_view_challans_dialog)
        epay_menu.addAction(act_view_challans)
        act_challan_template = QAction("Download Import Template…", self)
        act_challan_template.triggered.connect(self._download_challan_template)
        epay_menu.addAction(act_challan_template)
        self._epay_menu = epay_menu

        # Return Status menu (F-67) — a review/tracking screen opened
        # occasionally, not a per-run action like Downloads/E-Pay Tax, so it
        # only gets a menu entry, no toolbar button.
        return_status_menu = menubar.addMenu("Return Status")
        act_return_status = QAction("Check Processing Status…", self)
        act_return_status.triggered.connect(self._open_return_status_dialog)
        return_status_menu.addAction(act_return_status)
        self._return_status_menu = return_status_menu

        # Help menu
        help_menu = menubar.addMenu("Help")
        self._help_menu = help_menu
        act_manual = QAction(_micon("menu_about.png"), "User Manual", self)
        act_manual.triggered.connect(self._open_user_manual)
        help_menu.addAction(act_manual)
        self._act_manual = act_manual
        act_shortcuts = QAction("⌨  Keyboard Shortcuts…", self)
        act_shortcuts.triggered.connect(self._open_shortcut_editor)
        help_menu.addAction(act_shortcuts)
        self._act_shortcuts = act_shortcuts
        help_menu.addSeparator()
        smtp_help_action = QAction(_micon("btn_send_test.png"), "Email Setup Help…", self)
        smtp_help_action.triggered.connect(self._open_smtp_help)
        help_menu.addAction(smtp_help_action)
        help_menu.addSeparator()
        act_feedback = QAction(_micon("btn_view_log.png"), "Report Bug / Request Feature…", self)
        act_feedback.triggered.connect(self._open_feedback_picker)
        help_menu.addAction(act_feedback)
        help_menu.addSeparator()
        act_update = QAction(_micon("menu_about.png"), "Check for Updates…", self)
        act_update.triggered.connect(lambda: self._check_for_update(manual=True))
        help_menu.addAction(act_update)
        help_menu.addSeparator()
        about_action = QAction(_micon("menu_about.png"), "About AayDocCapio", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        root_widget = QWidget()
        self.setCentralWidget(root_widget)
        root = QVBoxLayout(root_widget)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self._mk_header())

        # F-77a Phase 1: rail hubs wired around the existing functionality.
        # The menu bar above stays fully functional in parallel throughout,
        # so every action remains reachable both ways (full retirement is a
        # later phase, per the approved plan).
        self._nav_shell = NavShell()
        self._nav_shell.add_hub("home", "Home / Clients", self._mk_main_panel(),
                                 accent_key="accent_home", section="top")
        self._nav_shell.add_hub("it", "Income Tax", self._mk_income_tax_page(),
                                 accent_key="accent_it", section="top")
        self._nav_shell.add_hub("gst", "GST", self._mk_placeholder_page(
            "GST", "Coming soon — see F-70 for the GST vs. Income Tax turnover reconciliation roadmap."),
            accent_key="accent_gst", section="top")
        self._nav_shell.add_hub("tds", "TDS", self._mk_tds_page(),
                                 accent_key="accent_tds", section="top")
        self._nav_shell.add_hub("litigation", "Litigation", self._mk_litigation_page(),
                                 accent_key="accent_litigation", section="top")
        self._nav_shell.add_hub("mca", "MCA", self._mk_placeholder_page(
            "MCA / ROC", "Coming soon — see F-72 for the MCA/ROC filings roadmap."),
            accent_key="accent_mca", section="top")
        self._nav_shell.add_hub("team", "Team", self._mk_placeholder_page(
            "Team", "Coming soon — see F-74 for CA staff / client-assignment management."),
            accent_key="accent_home", section="bottom")
        self._nav_shell.add_hub("mail", "Mail Docs to Clients", self._mk_mail_docs_page(),
                                 accent_key="accent_home", section="bottom")
        self._nav_shell.add_hub("activity", "Activity Log", self._mk_activity_log_page(),
                                 accent_key="accent_home", section="bottom")
        self._nav_shell.add_hub("settings", "Settings", self._mk_settings_page(),
                                 accent_key="accent_home", section="bottom")
        self._nav_shell.add_hub("help", "Help", self._mk_help_page(),
                                 accent_key="accent_home", section="bottom")
        root.addWidget(self._build_eproc_dashboard_strip())
        root.addWidget(self._nav_shell, 1)

        self._nav_shell.hubChanged.connect(self._on_hub_changed)
        self._nav_shell.go("home")
        # Populate the global e-Proceedings dashboard once the vault/assessees
        # are available (deferred — tabs are built before the vault loads).
        QTimer.singleShot(0, self._eproc_update_dashboard)

        # F-17: keyboard navigation + customizable shortcuts (defaults are
        # applied here; user overrides come from the vault).
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """Create/attach the shortcut action map and apply saved bindings."""
        self._shortcut_actions: dict[str, QAction] = {}
        self._shortcut_user = _shortcuts.load_user_bindings(self.vault)

        def _action(action_id: str, handler) -> QAction:
            act = QAction(self)
            act.setObjectName(action_id)
            act.triggered.connect(lambda _=False: handler())
            self.addAction(act)
            self._shortcut_actions[action_id] = act
            return act

        # Reuse the existing menu actions so hints show up in the menus.
        for action_id, act in (
            ("app.add_client", getattr(self, "_act_add", None)),
            ("app.edit_client", getattr(self, "_act_edit_cl", None)),
            ("app.delete_clients", getattr(self, "_act_del_cl", None)),
            ("app.import", getattr(self, "_act_import", None)),
            ("app.export", getattr(self, "_act_export", None)),
            ("app.user_manual", getattr(self, "_act_manual", None)),
            ("app.open_shortcuts", getattr(self, "_act_shortcuts", None)),
        ):
            if act is not None:
                self._shortcut_actions[action_id] = act

        for action_id, hub in (
            ("nav.home", "home"),
            ("nav.income_tax", "it"),
            ("nav.tds", "tds"),
            ("nav.litigation", "litigation"),
            ("nav.mail", "mail"),
            ("nav.activity", "activity"),
            ("nav.settings", "settings"),
            ("nav.help", "help"),
        ):
            _action(action_id, lambda h=hub: self._nav_shell.go(h))

        _action("app.focus_search", self._shortcut_focus_search)
        _action("app.refresh_clients", self.refresh_grid)
        _action("app.start_batch", self._open_download_picker)
        _action("app.stop_batch", self.stop_automation)
        _action("app.open_output_folder", self._open_output_folder)
        _action("app.toggle_theme", self._toggle_theme)

        self._apply_shortcut_bindings()

        # Accessibility pass for the primary controls (F-17).
        effective = _shortcuts.merge_user_bindings(self._shortcut_user)
        if hasattr(self, "search_box"):
            self.search_box.setAccessibleName("Search clients")
            self.search_box.setAccessibleDescription(
                "Filter the client list by name or PAN. Shortcut: "
                + _shortcuts.format_binding(effective.get("app.focus_search", "")))
        if hasattr(self, "status_filter"):
            self.status_filter.setAccessibleName("Filter by download status")
        if hasattr(self, "client_table"):
            self.client_table.setAccessibleName("Client list")
            self.client_table.setAccessibleDescription(
                "Tab to a client's checkbox and press Space to select or clear it. "
                "Arrow keys move through the rows; Ctrl+F searches. "
                "Use the Downloads button or Ctrl+Enter to start.")
        if hasattr(self, "btn_run"):
            self.btn_run.setAccessibleName("Download documents")
            self.btn_run.setToolTip("Choose document types and start downloading")
        # Predictable keyboard path through the Home screen.
        try:
            QWidget.setTabOrder(self.search_box, self.status_filter)
            QWidget.setTabOrder(self.status_filter, self.group_filter)
            QWidget.setTabOrder(self.group_filter, self.source_filter)
            QWidget.setTabOrder(self.source_filter, self.client_table)
            QWidget.setTabOrder(self.client_table, self.btn_run)
        except Exception:
            pass
        self._apply_generic_accessibility()

    def _apply_generic_accessibility(self):
        """Give any remaining interactive control a sensible accessible name."""
        for button in self.findChildren(QAbstractButton):
            if button.accessibleName():
                continue
            name = (button.text() or "").strip() or (button.toolTip() or "").strip()
            if name:
                button.setAccessibleName(name)
        for field in self.findChildren(QLineEdit):
            if not field.accessibleName():
                name = field.placeholderText().strip() or field.toolTip().strip()
                if name:
                    field.setAccessibleName(name)
        for combo in self.findChildren(QComboBox):
            if not combo.accessibleName():
                name = combo.toolTip().strip() or combo.currentText().strip()
                if name:
                    combo.setAccessibleName(name)

    def _shortcut_focus_search(self):
        try:
            self._nav_shell.go("home")
        except Exception:
            pass
        if hasattr(self, "search_box"):
            self.activateWindow()
            self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.search_box.selectAll()

    def _toggle_theme(self):
        self._apply_theme("light" if self._current_theme == "dark" else "dark")

    def _apply_shortcut_bindings(self):
        effective = _shortcuts.merge_user_bindings(self._shortcut_user)
        for action_id, act in self._shortcut_actions.items():
            seq = effective.get(action_id, "")
            act.setShortcut(QKeySequence(seq) if seq else QKeySequence())
            act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            act.setShortcutVisibleInContextMenu(True)

    def _open_shortcut_editor(self):
        from ui.shortcuts_dialog import ShortcutEditorDialog
        dlg = ShortcutEditorDialog(self, self.vault, on_saved=self._on_shortcuts_saved)
        dlg.exec()

    def _on_shortcuts_saved(self, user_bindings):
        self._shortcut_user = user_bindings
        self._apply_shortcut_bindings()
        self.log("[Settings] Keyboard shortcuts updated.")

    def _build_eproc_dashboard_strip(self):
        """GLOBAL e-Proceedings dashboard: Last Sync / Failed Clients / Latest
        Fetched cards, visible on every hub and tab (sits above the nav
        stack). Clicking a card jumps to the e-Proceedings tab of the Income
        Tax hub; the Latest Fetched card opens the newest file's folder."""
        t = _t()
        strip = QFrame()
        strip.setStyleSheet(
            f"QFrame#eprocDash{{background:{t.bg_panel};border:none;"
            f"border-bottom:1px solid {t.border};}}")
        strip.setObjectName("eprocDash")
        row = QHBoxLayout(strip)
        row.setContentsMargins(24, 6, 24, 6)
        row.setSpacing(10)

        self._eproc_dash = {}
        for key, caption in (("sync", "Last Sync"), ("failed", "Failed Clients"),
                             ("latest", "Latest Fetched")):
            card = QFrame()
            card.setObjectName("eprocDashCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet(
                f"QFrame#eprocDashCard{{background:{t.bg_table_alt};"
                f"border:1px solid {t.border};border-radius:8px;}}"
                f"QFrame#eprocDashCard:hover{{border-color:{t.accent_it};}}")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(10, 4, 10, 4)
            cv.setSpacing(0)
            cv.addWidget(_lbl(caption, 9, color=t.text_muted))
            val = _lbl("—", 12, bold=True)
            cv.addWidget(val)
            row.addWidget(card, 1 if key != "latest" else 2)
            self._eproc_dash[key] = {"card": card, "value": val}

            def _card_click(event, _k=key):
                if event.button() == Qt.MouseButton.LeftButton:
                    if _k == "latest":
                        self._eproc_open_latest_folder()
                    else:
                        self._goto_eproceedings_tab()

            card.mousePressEvent = _card_click
        row.addStretch(0)
        return strip

    def _goto_eproceedings_tab(self):
        """Jump to Income Tax hub ▸ e-Proceedings (dashboard card click)."""
        try:
            self._nav_shell.go("it")
            self._switch_it_tab(5)
        except Exception:
            pass

    def _eproc_scan_all_only(self):
        """Populate self._eproc_cases without touching any widgets — used by
        the global dashboard refresh (the tab may never have been opened)."""
        root = self.vault.get_setting("download_root_dir", "")
        if not (root and os.path.isdir(root)):
            self._eproc_cases = []
            return
        self._eproc_rescan_into_cases(root)

    def _on_hub_changed(self, hub_label: str, sub_label: str):
        """NavShell.hubChanged handler — breadcrumb lives on the header
        itself (self._hdr_crumb), not a separate ribbon strip."""
        if hasattr(self, "_hdr_crumb"):
            self._hdr_crumb.setText(f"{hub_label} › {sub_label}" if sub_label else hub_label)

    def _resolve_theme(self, theme: str) -> str:
        """Map a preference (light/dark/system) to a concrete theme name."""
        if theme == "system":
            return "dark" if self._system_is_dark() else "light"
        return theme if theme in THEMES else "light"

    def _system_is_dark(self) -> bool:
        try:
            app = QApplication.instance()
            if app:
                scheme = app.styleHints().colorScheme()
                if scheme == Qt.ColorScheme.Dark:
                    return True
                if scheme == Qt.ColorScheme.Light:
                    return False
        except Exception:
            pass
        return False

    def _watch_system_theme(self):
        """Follow the OS light/dark scheme while the preference is "system"."""
        try:
            self._style_hints = QApplication.instance().styleHints()
            self._style_hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        except Exception:
            self._style_hints = None

    def _on_system_scheme_changed(self, *_):
        if getattr(self, "_theme_pref", "light") == "system":
            self._apply_theme("system", persist=False)

    def _apply_theme(self, theme: str, persist: bool = True, rebuild_ui: bool = True):
        """Switch theme by preference name and (optionally) persist it."""
        if theme not in (*THEMES, "system"):
            theme = "light"
        previous = self._current_theme
        self._theme_pref = theme
        resolved = self._resolve_theme(theme)
        self._current_theme = resolved
        if persist:
            self.vault.update_setting("theme", theme)
        suffix = f" ({resolved})" if theme == "system" else ""
        self.log(f"[System] Theme set to: {theme}{suffix}")
        t = get_theme(resolved)
        import ui._theme as _theme_mod
        _theme_mod._active_theme = t
        if QApplication.instance():
            self._apply_palette(t)
        self._sync_theme_actions()
        if (rebuild_ui and resolved != previous
                and hasattr(self, "_nav_shell")
                and not getattr(self, "_theme_rebuild_pending", False)):
            # Inline styles capture the theme at construction time, so a live
            # theme change rebuilds the pages instead of leaving white cards
            # behind. Deferred so we never delete the widget that fired the
            # shortcut/menu action.
            self._theme_rebuild_pending = True
            QTimer.singleShot(0, self._rebuild_ui_for_theme)
        else:
            self._repaint_theme(t)
            self._repaint_open_windows(t)

    def _rebuild_ui_for_theme(self):
        """Rebuild the main UI so every inline style uses the new theme."""
        self._theme_rebuild_pending = False
        if not hasattr(self, "_nav_shell"):
            return
        nav_key = self._nav_shell.current_key() or "home"
        search_text = self.search_box.text() if hasattr(self, "search_box") else ""
        status_idx = self.status_filter.currentIndex() if hasattr(self, "status_filter") else 0
        group_idx = self.group_filter.currentIndex() if hasattr(self, "group_filter") else 0
        source_idx = self.source_filter.currentIndex() if hasattr(self, "source_filter") else 0
        it_tab_idx = self._it_stack.currentIndex() if hasattr(self, "_it_stack") else 0

        for act in getattr(self, "_shortcut_actions", {}).values():
            self.removeAction(act)
            act.deleteLater()
        self._shortcut_actions = {}

        menubar = self.menuBar()
        menubar.clear()
        for menu in menubar.findChildren(QMenu):
            menu.deleteLater()

        self._build_ui()
        self.refresh_grid()

        if hasattr(self, "status_filter"):
            self.status_filter.setCurrentIndex(status_idx)
        if hasattr(self, "group_filter"):
            self.group_filter.setCurrentIndex(group_idx)
        if hasattr(self, "source_filter"):
            self.source_filter.setCurrentIndex(source_idx)
        if hasattr(self, "search_box") and search_text:
            self.search_box.setText(search_text)
        if (nav_key == "it" and hasattr(self, "_it_stack")
                and hasattr(self, "_it_tab_btns")):
            self._switch_it_tab(it_tab_idx)
        self._nav_shell.go(nav_key)
        self._repaint_theme(get_theme(self._current_theme))
        self._repaint_open_windows(get_theme(self._current_theme))

    def _sync_theme_actions(self):
        for name in (*THEMES, "system"):
            act = getattr(self, f"_theme_{name}_act", None)
            if act:
                act.setChecked(name == self._theme_pref)

    def _apply_palette(self, t: ThemeColors):
        """Theme Qt-painted surfaces that QSS cannot reach reliably."""
        app = QApplication.instance()
        if not app:
            return
        pal = app.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(t.bg_window))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(t.text_primary))
        pal.setColor(QPalette.ColorRole.Base, QColor(t.bg_input))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t.bg_table_alt))
        pal.setColor(QPalette.ColorRole.Text, QColor(t.text_primary))
        pal.setColor(QPalette.ColorRole.Button, QColor(t.bg_panel))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(t.text_primary))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.bg_tooltip))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text_primary))
        pal.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.accent_text))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.text_muted))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                     QPalette.ColorRole.ButtonText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.text_disabled))
        app.setPalette(pal)
        app.setStyleSheet(build_stylesheet(t))

    def _repaint_open_windows(self, t: ThemeColors):
        """Best-effort live re-theme for windows that opt into repaint_theme."""
        app = QApplication.instance()
        if not app:
            return
        for widget in app.topLevelWidgets():
            if widget is self or not widget.isVisible():
                continue
            repaint = getattr(widget, "repaint_theme", None)
            if callable(repaint):
                try:
                    repaint(t)
                except Exception:
                    pass

    def _repaint_theme(self, t: ThemeColors = None):
        """Repaint widgets whose colours are set imperatively (not via QSS)."""
        if t is None:
            t = get_theme(self._current_theme)

        # ── Header ────────────────────────────────────────────────────────────
        if hasattr(self, "_hdr_frame"):
            self._hdr_frame.setStyleSheet(
                f"QFrame#header {{ background: {t.bg_menubar}; border: none; }}"
                f" QLabel {{ border: none; text-decoration: none; }}"
            )
        if hasattr(self, "_hdr_logo"):
            _logo_file = "AayDoc_Header_Dark.png" if self._current_theme == "dark" else "AayDoc_Header_Light.png"
            _logo_path = os.path.join(_bundled_dir(), "resources", _logo_file)
            if os.path.exists(_logo_path):
                self._hdr_logo.setPixmap(
                    QPixmap(_logo_path).scaledToHeight(66, Qt.TransformationMode.SmoothTransformation)
                )
        if hasattr(self, "_hdr_crumb"):
            self._hdr_crumb.setStyleSheet(
                f"color:{t.text_muted}; font-size:12px; font-weight:600;"
                f" background:transparent; border:none;")
        for lbl in (getattr(self, "_hdr_version", None), getattr(self, "_hdr_copy", None)):
            if lbl:
                # No font-family override — inherits the app's theme font
                # (UI_FONT, themes.py) like every other label, instead of
                # hardcoding Arial and rendering in a visibly different
                # typeface from the rest of the header.
                lbl.setStyleSheet(
                    f"color:{t.text_muted}; font-size:11px;"
                    f" background:transparent; border:none;")

        # ── Nav shell (rail + breadcrumb, F-77a) ──────────────────────────────
        if hasattr(self, "_nav_shell"):
            self._nav_shell.repaint_theme(t)
        if getattr(self, "_litigation_page", None) is not None:
            try:
                self._litigation_page.repaint_theme(t)
            except Exception:
                pass

        # ── Main panel + settings/control bar backgrounds ─────────────────────
        if hasattr(self, "_main_panel"):
            self._main_panel.setStyleSheet(f"background:{t.bg_window};")
        for bar in (getattr(self, "_settings_bar", None), getattr(self, "_control_bar", None)):
            if bar:
                bar.setStyleSheet(f"QFrame{{background:{t.bg_panel};border-radius:10px;}}")

        # ── Settings bar caption labels ───────────────────────────────────────
        for lbl in getattr(self, "_settings_caps", []):
            lbl.setStyleSheet(
                f"color:{t.text_muted};font-size:10px;font-weight:700;"
                f"letter-spacing:0.8px;background:transparent;")

        # ── Search box + status filter ────────────────────────────────────────
        if hasattr(self, "search_box"):
            self.search_box.setStyleSheet(
                f"QLineEdit{{background:{t.bg_input};border:1.5px solid {t.border};"
                f"border-radius:6px;padding:4px 10px;font-size:12px;"
                f"color:{t.text_primary};min-height:28px;}}"
                f"QLineEdit:focus{{border-color:{t.border_focus};background:{t.bg_input_focus};}}"
                f"QLineEdit::placeholder{{color:{t.text_muted};}}"
            )

        # ── dir_lbl + browse button ───────────────────────────────────────────
        if hasattr(self, "dir_lbl"):
            self.dir_lbl.setStyleSheet(
                f"color:{t.text_primary};font-size:12px;background:transparent;")
        _dir_btn_style = (
            f"QPushButton{{background:transparent;color:{t.text_primary};"
            f"border:1px solid {t.border};border-radius:6px;"
            f"padding:4px 12px;font-weight:bold;font-size:12px;}}"
            f"QPushButton:hover{{background:{t.bg_table_alt};}}"
            f"QPushButton:disabled{{color:{t.text_muted};border-color:{t.border};}}"
        )
        if hasattr(self, "_browse_btn"):
            self._browse_btn.setStyleSheet(_dir_btn_style)
        if hasattr(self, "_open_btn"):
            self._open_btn.setStyleSheet(_dir_btn_style)

        # ── chk_headless ──────────────────────────────────────────────────────
        if hasattr(self, "chk_headless"):
            self.chk_headless.setStyleSheet(
                f"QCheckBox{{font-size:12px;color:{t.text_muted};background:transparent;spacing:6px;}}"
                f"QCheckBox::indicator{{width:15px;height:15px;border:1.5px solid {t.border};"
                f"border-radius:3px;background:{t.bg_checkbox};}}"
                f"QCheckBox::indicator:checked{{background:{t.accent};border-color:{t.accent};"
                f"image:url(resources/check_white.png);}}")

        # ── Run button ────────────────────────────────────────────────────────
        if hasattr(self, "btn_run"):
            self.btn_run.setStyleSheet(
                f"QToolButton{{background:{t.accent};color:{t.accent_text};border:none;"
                f"border-radius:6px;font-size:12px;font-weight:600;padding:0 14px;}}"
                f"QToolButton:hover{{background:{t.accent_hover};}}"
                f"QToolButton::menu-button{{border:none;width:20px;}}"
                f"QToolButton:disabled{{background:{t.border};color:{t.text_muted};}}")
            if hasattr(self.btn_run, "menu") and self.btn_run.menu():
                self.btn_run.menu().setStyleSheet(
                    f"QMenu{{background:{t.bg_menu};border:1.5px solid {t.border_menu};"
                    f"border-radius:8px;padding:4px 0;}}"
                    f"QMenu::item{{padding:8px 18px;font-size:12px;color:{t.text_primary};}}"
                    f"QMenu::item:selected{{background:{t.accent};color:{t.accent_text};}}"
                    f"QMenu::separator{{height:1px;background:{t.border_menu};margin:4px 0;}}")

        # ── CLIENTS caption + selected count label ────────────────────────────
        if hasattr(self, "_lbl_clients_cap"):
            self._lbl_clients_cap.setStyleSheet(
                f"color:{t.text_muted};font-size:10px;font-weight:700;"
                f"letter-spacing:0.8px;background:transparent;")
        if hasattr(self, "lbl_selected"):
            self.lbl_selected.setStyleSheet(
                f"color:{t.accent};font-size:11px;font-weight:bold;background:transparent;")

        # ── Header checkbox (select-all) ──────────────────────────────────────
        if hasattr(self, "header_cb"):
            _chk_path2 = self.checkmark_path.replace("\\", "/")
            self.header_cb.setStyleSheet(
                f"QCheckBox{{background:transparent;}}"
                f"QCheckBox::indicator{{width:15px;height:15px;border:1.5px solid {t.border};"
                f"border-radius:3px;background:{t.bg_checkbox};}}"
                f"QCheckBox::indicator:hover{{border-color:{t.border_focus};}}"
                f"QCheckBox::indicator:checked{{background:{t.accent};border-color:{t.accent};"
                f"image:url('{_chk_path2}');}}"
            )

        # ── Table widget stylesheet + header ──────────────────────────────────
        if hasattr(self, "client_table"):
            chk_path = self.checkmark_path.replace("\\", "/")
            chk_ss = (
                "QCheckBox { background: transparent; }"
                f"QCheckBox:focus {{ background: {t.accent_light}; border-radius: 4px; }}"
                f"QCheckBox::indicator {{ width: 15px; height: 15px; border: 1.5px solid {t.border};"
                f" border-radius: 3px; background: {t.bg_checkbox}; }}"
                f"QCheckBox::indicator:hover {{ border-color: {t.border_focus}; }}"
                f"QCheckBox::indicator:checked {{ background-color: {t.accent}; border-color: {t.accent};"
                f" image: url('{chk_path}'); }}"
            )
            self.client_table.setStyleSheet(
                f"QTableWidget {{ border: 1.5px solid {t.border}; border-radius: 8px;"
                f" background: {t.bg_table}; outline: 0; gridline-color: {t.grid}; }}"
                f"QTableWidget:focus {{ border: 2px solid {t.border_focus}; }}"
                f"QTableWidget::item {{ border-bottom: 1px solid {t.grid}; padding: 5px; color: {t.text_primary}; }}"
                + chk_ss
            )
            self.client_table.horizontalHeader().setStyleSheet(
                f"QHeaderView::section {{ background-color: {t.bg_header}; border: none;"
                f" border-right: 1px solid {t.border}; border-bottom: 1px solid {t.border};"
                f" font-weight: bold; color: {t.text_muted}; font-size: 11px; height: 34px; }}"
            )
            self.refresh_grid()

        # ── Log box ───────────────────────────────────────────────────────────
        if hasattr(self, "log_box"):
            self.log_box.setStyleSheet(
                f"QTextEdit {{ background: {t.bg_log}; border: none;"
                f" font-family: '{_MONO_FONT}', monospace;"
                f" font-size: 11px; color: {t.text_log}; padding: 8px 16px; }}"
            )

    def _open_user_manual(self):
        import webbrowser
        from ui.user_manual import _write_user_manual_html
        path = _write_user_manual_html()
        webbrowser.open("file:///" + path.replace(os.sep, "/"))

    def _open_smtp_help(self):
        import webbrowser
        from ui.smtp_help import _write_smtp_help_html
        path = _write_smtp_help_html()
        webbrowser.open("file:///" + path.replace(os.sep, "/"))

    def _open_feedback_picker(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Report Bug / Request Feature")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("What would you like to send?")
        msg.setInformativeText(
            "AayDocCapio will open GitHub in your browser with a structured form. "
            "Review the details before submitting, and do not paste passwords or client PANs."
        )
        bug_btn = msg.addButton("Report Bug", QMessageBox.ButtonRole.AcceptRole)
        feature_btn = msg.addButton("Request Feature", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == bug_btn:
            self._open_github_issue("bug_report.yml", "[Bug] ")
        elif clicked == feature_btn:
            self._open_github_issue("feature_request.yml", "[Feature] ")

    def _open_github_issue(self, template_name: str, title_prefix: str):
        query = urlencode({
            "template": template_name,
            "title": title_prefix,
        })
        QDesktopServices.openUrl(QUrl(f"https://github.com/dkbholusaria/AayDocCapio/issues/new?{query}"))

    def _show_about(self):
        import webbrowser
        dlg = QDialog(self)
        dlg.setWindowTitle("About AayDocCapio")
        dlg.setFixedSize(500, 520)
        _ab = _t()
        dlg.setStyleSheet(
            f"QDialog {{ background:{_ab.bg_window}; }}"
            f"QLabel {{ border:none; background:transparent; color:{_ab.text_primary}; }}"
            f"QLabel[link=true] {{ color:{_ab.accent}; }}"
        )

        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(36, 28, 36, 28)
        vl.setSpacing(0)

        # ── App logo + version ─────────────────────────────────────────────────
        logo_row = QVBoxLayout(); logo_row.setSpacing(6)
        logo_lbl = QLabel()
        _logo_file = "AayDoc_Header_Dark.png" if self._current_theme == "dark" else "AayDoc_Header_Light.png"
        _logo_path = os.path.join(_bundled_dir(), "resources", _logo_file)
        if os.path.exists(_logo_path):
            logo_lbl.setPixmap(QPixmap(_logo_path).scaledToHeight(56, Qt.TransformationMode.SmoothTransformation))
        logo_row.addWidget(logo_lbl)
        ver_lbl = QLabel(f"Version {APP_VERSION}")
        ver_lbl.setStyleSheet(f"color:{_ab.text_muted}; font-size:12px;")
        logo_row.addWidget(ver_lbl)
        vl.addLayout(logo_row)
        vl.addSpacing(14)

        desc = QLabel("Automates day-to-day Income Tax compliance work for CAs — bulk document retrieval, "
                      "E-Pay Tax challans, return processing status and client document delivery — all from "
                      "one secure desktop app, directly against the e-Filing Portal.")
        desc.setStyleSheet(f"color:{_ab.text_primary}; font-size:12px;")
        desc.setWordWrap(True)
        vl.addWidget(desc)
        vl.addSpacing(12)

        # Name explanation
        name_box = QFrame()
        name_box.setStyleSheet(f"QFrame {{ background:{_ab.bg_panel}; border-radius:6px; border:1px solid {_ab.accent}; }}")
        nb_l = QVBoxLayout(name_box)
        nb_l.setContentsMargins(14, 10, 14, 10)
        nb_l.setSpacing(6)
        name_head = QLabel("Why AayDoc Capio?")
        name_head.setStyleSheet(f"color:{_ab.accent}; font-size:11px; font-weight:700; letter-spacing:0.5px; background:transparent; border:none;")
        name_exp = QLabel(
            f'<b style="color:{_ab.text_primary};">Aay</b> (Income) · '
            f'<b style="color:{_ab.text_primary};">Doc</b> (Documents) · '
            f'<b style="color:{_ab.accent};">Capio</b> <span style="color:{_ab.text_muted};">(Latin: To Obtain)</span>'
        )
        name_exp.setStyleSheet("font-size:12px; background:transparent; border:none;")
        name_sub = QLabel("AayDoc Capio automates the repetitive, manual side of Income Tax portal work — "
                          "so tax professionals spend less time on downloads and data entry, and more time "
                          "on the advisory work that actually needs them.")
        name_sub.setStyleSheet(f"color:{_ab.text_primary}; font-size:12px; background:transparent; border:none;")
        name_sub.setWordWrap(True)
        nb_l.addWidget(name_head)
        nb_l.addWidget(name_exp)
        nb_l.addWidget(name_sub)
        vl.addWidget(name_box)
        vl.addSpacing(16)

        # ── Divider ───────────────────────────────────────────────────────────
        div1 = QFrame(); div1.setFrameShape(QFrame.Shape.HLine)
        div1.setStyleSheet(f"background:{_ab.border}; border:none; max-height:1px;")
        vl.addWidget(div1)
        vl.addSpacing(16)

        # ── Developer info ────────────────────────────────────────────────────
        dev_title = QLabel("Contact Us")
        dev_title.setStyleSheet(f"color:{_ab.text_muted}; font-size:10px; font-weight:700; letter-spacing:1px;")
        vl.addWidget(dev_title)
        vl.addSpacing(8)

        def _link_row(icon_file, display_text, url=None):
            row = QHBoxLayout(); row.setSpacing(10); row.setContentsMargins(0,0,0,0)
            icon_l = QLabel()
            icon_l.setFixedSize(22, 22)
            icon_path = os.path.join(_bundled_dir(), "resources", "icons", icon_file)
            if os.path.exists(icon_path):
                icon_l.setPixmap(QPixmap(icon_path).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio,
                                                            Qt.TransformationMode.SmoothTransformation))
            icon_l.setStyleSheet("background:transparent; border:none;")
            row.addWidget(icon_l)
            if url:
                lbl = QLabel(f'<a href="{url}" style="color:{_ab.accent}; text-decoration:none;">{display_text}</a>')
                lbl.setOpenExternalLinks(True)
                lbl.setStyleSheet("background:transparent; border:none; font-size:12px;")
            else:
                lbl = QLabel(display_text)
                lbl.setStyleSheet(f"color:{_ab.text_primary}; font-size:12px; font-weight:600; background:transparent; border:none;")
            row.addWidget(lbl)
            row.addStretch()
            return row

        vl.addLayout(_link_row("icon_person.png",   "CA. Deepak Bhholusaria"))
        vl.addSpacing(6)
        vl.addLayout(_link_row("icon_email.png",    "deepak@ailearrning.guru",          "mailto:deepak@ailearrning.guru"))
        vl.addSpacing(6)
        vl.addLayout(_link_row("icon_linkedin.png", "linkedin.com/in/bhholusaria",      "https://www.linkedin.com/in/bhholusaria/"))
        vl.addSpacing(6)
        vl.addLayout(_link_row("icon_vcard.png",    "www.ailearrning.guru",             "https://www.ailearrning.guru"))
        vl.addSpacing(6)
        vl.addLayout(_link_row("icon_virtualcard.png", "E-Visiting Card",               "https://deepak.bholusaria.com"))
        vl.addSpacing(16)

        # ── Divider ───────────────────────────────────────────────────────────
        div2 = QFrame(); div2.setFrameShape(QFrame.Shape.HLine)
        div2.setStyleSheet(f"background:{_ab.border}; border:none; max-height:1px;")
        vl.addWidget(div2)
        vl.addSpacing(12)

        copy = QLabel("© 2026 Deepak Bhholusaria. All rights reserved.")
        copy.setStyleSheet(f"color:{_ab.text_muted}; font-size:11px;")
        vl.addWidget(copy)
        vl.addStretch()

        # ── Close button ──────────────────────────────────────────────────────
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{_ab.accent}; color:{_ab.accent_text}; border:none; border-radius:6px; padding:8px 16px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{_ab.accent_hover}; }}")
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout(); btn_row.addStretch(); btn_row.addWidget(close_btn)
        vl.addLayout(btn_row)

        dlg.exec()

    def _mk_header(self):
        hdr = QFrame()
        hdr.setFixedHeight(84)
        hdr.setObjectName("header")
        self._hdr_frame = hdr
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(32, 0, 32, 0)
        hl.setSpacing(0)

        # Combined logo (icon + "aaydoc CAPIO" wordmark) — swapped Light/Dark
        # per theme in _repaint_theme(), since each variant is coloured for
        # its own background contrast.
        logo_label = QLabel()
        self._hdr_logo = logo_label
        hl.addWidget(logo_label)
        hl.addSpacing(24)

        # Breadcrumb — updated from NavShell.hubChanged once the nav shell
        # exists (see _build_ui()); lives on the header itself, not a
        # separate ribbon strip below it.
        crumb = QLabel("")
        self._hdr_crumb = crumb
        hl.addWidget(crumb)
        hl.addStretch()

        # Copyright + version on the right
        meta_block = QWidget()
        meta_block.setStyleSheet("background:transparent;")
        ml = QVBoxLayout(meta_block)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(2)
        ml.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        version_lbl = QLabel(f"v{APP_VERSION}")
        self._hdr_version = version_lbl
        version_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        copy_lbl = QLabel("© 2026 Deepak Bhholusaria")
        self._hdr_copy = copy_lbl
        copy_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

        ml.setSpacing(1)
        ml.addStretch()
        ml.addWidget(version_lbl)
        ml.addWidget(copy_lbl)

        self._hdr_update_lnk = QLabel()
        self._hdr_update_lnk.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._hdr_update_lnk.setOpenExternalLinks(False)
        self._hdr_update_lnk.linkActivated.connect(self._on_update_link_clicked)
        self._hdr_update_lnk.setFixedHeight(16)
        ml.addWidget(self._hdr_update_lnk)

        ml.addStretch()

        hl.addWidget(meta_block)
        hl.addSpacing(12)

        # ⓘ About button
        about_btn = QPushButton("ⓘ")
        about_btn.setFixedSize(32, 32)
        about_btn.setToolTip("About AayDocCapio")
        about_btn.setStyleSheet(
            # Icon glyph size, not part of the text type scale
            f"QPushButton {{ background:transparent; border:none; font-size:20px; color:{_t().error}; }}"
            f"QPushButton:hover {{ color:{_t().error}; }}")
        about_btn.clicked.connect(self._show_about)
        hl.addWidget(about_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        return hdr

    def _mk_main_panel(self):
        panel = QWidget()
        self._main_panel = panel
        panel.setStyleSheet(f"background:{_t().bg_window};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(6)

        settings = self._mk_settings_bar()
        settings.setGraphicsEffect(_shadow(18, 3, 18))
        layout.addWidget(settings)

        # Grid label row
        grid_hdr_row = QHBoxLayout()
        self._lbl_clients_cap = _lbl("CLIENTS", 10, bold=True, color=_t().text_muted)
        grid_hdr_row.addWidget(self._lbl_clients_cap)
        grid_hdr_row.addStretch()
        self.lbl_selected = _lbl("0 selected", 11, bold=True, color=_t().accent)
        grid_hdr_row.addWidget(self.lbl_selected)
        layout.addLayout(grid_hdr_row)

        # Search / filter bar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.setContentsMargins(0, 0, 0, 0)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  Search by name, PAN, status or GST...")
        self.search_box.setMinimumHeight(30)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.search_box.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.search_box, 1)

        self.status_filter = StyledComboBox()
        self.status_filter.addItems([
            "All statuses",
            "✅  Downloaded",
            "⚠  Partially Completed",
            "❌  Failed",
            "🕐  Queued / Pending",
            "—  Not run yet",
        ])
        self.status_filter.setMinimumHeight(30)
        self.status_filter.setMinimumWidth(185)
        self.status_filter.currentIndexChanged.connect(lambda _: self._apply_filter(self.search_box.text()))
        filter_row.addWidget(self.status_filter)

        # F-11: Group filter — populated/refreshed by _refresh_group_filter()
        # (called from refresh_grid()) so it never drifts from what clients
        # are actually tagged with.
        self.group_filter = StyledComboBox()
        self.group_filter.addItem("All Groups")
        self.group_filter.setMinimumHeight(30)
        self.group_filter.setMinimumWidth(160)
        self.group_filter.currentIndexChanged.connect(lambda _: self._apply_filter(self.search_box.text()))
        filter_row.addWidget(self.group_filter)

        # Credential-source filter — lets the GST client base be listed at a
        # glance, which is the first thing the GST reconciliation work needs.
        self.source_filter = StyledComboBox()
        self.source_filter.addItems([
            "All sources", "Has GST", "Has TDS", "Has Income Tax", "Has no credentials",
        ])
        self.source_filter.setMinimumHeight(30)
        self.source_filter.setMinimumWidth(150)
        self.source_filter.setAccessibleName("Filter by portal credentials")
        self.source_filter.currentIndexChanged.connect(
            lambda _: self._apply_filter(self.search_box.text()))
        filter_row.addWidget(self.source_filter)

        layout.addLayout(filter_row)

        layout.addWidget(self._mk_client_table(), 1)

        ctrl = self._mk_control_bar()
        ctrl.setGraphicsEffect(_shadow(18, 3, 18))
        layout.addWidget(ctrl)
        return panel

    def _mk_settings_bar(self):
        bar = QFrame()
        self._settings_bar = bar
        bar.setMinimumHeight(68)
        bar.setStyleSheet(f"QFrame{{background:{_t().bg_panel};border-radius:10px;}}")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(0)
        hl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._settings_caps = []

        def _cap(text):
            l = QLabel(text)
            self._settings_caps.append(l)
            return l

        def _divider():
            d = QFrame(); d.setFrameShape(QFrame.Shape.VLine)
            d.setFixedSize(1, 32)
            d.setStyleSheet(f"background:{_t().border};border:none;")
            return d

        # ── Assessment Year (F-14: multi-select, one batch can cover several
        # years) ────────────────────────────────────────────────────────────
        # Deliberately NOT restored from a saved setting — starts unchecked
        # on every launch so a stale multi-year selection from a previous
        # session can't silently apply to a new run.
        self._ay_entries = self._load_ay_list()
        ay_labels = [e["label"] for e in self._ay_entries if e.get("enabled", True)]
        self.ay_combo = CheckableComboBox(placeholder="Select AY/TY")
        for _label in ay_labels:
            self.ay_combo.add_item(_label, checked=False)
        self.ay_combo.setFixedWidth(220)
        self.ay_combo.model_.itemChanged.connect(lambda _item: self._log_ay_selection())
        self.ay_combo.model_.itemChanged.connect(lambda _item: self.refresh_grid())
        self.ay_combo.model_.itemChanged.connect(lambda _item: self._sync_ay_to_dl())

        manage_btn = QPushButton("⚙")
        manage_btn.setFixedSize(24, 24)
        manage_btn.setToolTip("Manage Years")
        manage_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;font-size:14px;color:{_t().text_muted};}}"
            f"QPushButton:hover{{color:{_t().accent};}}")
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
        # Prefer Windows path whenever USERPROFILE is set (native Windows or WSL).
        # Use saved path if it exists and is reachable — regardless of format
        # (Windows drive, UNC //wsl.localhost/..., SUBST, junction, etc.).
        # Only fall back to the Windows default when running on Windows and the
        # saved path is a bare Linux path (/home/...) that Windows cannot reach.
        _saved_dir = self.vault.get_setting("download_root_dir", "")
        _on_windows = sys.platform == "win32"
        _is_bare_linux = (
            _saved_dir.startswith("/")
            and not _saved_dir.startswith("//")
            and not _saved_dir.startswith("\\\\")
        )
        if _saved_dir and not (_on_windows and _is_bare_linux) and os.path.isdir(_saved_dir):
            default_dir = _saved_dir
        else:
            default_dir = _default_download_dir()
            self.vault.update_setting("download_root_dir", default_dir)
        if sys.platform == "win32":
            default_dir = default_dir.replace("/", "\\")
        self.dir_lbl = QLabel(default_dir)
        self.dir_lbl.setStyleSheet(f"color:{_t().text_primary};font-size:12px;background:transparent;")
        self.dir_lbl.setWordWrap(False)
        self.dir_lbl.setMaximumWidth(320)
        self.dir_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        browse_btn = _btn("Browse", "outline", height=26, icon="btn_browse.png")
        self._browse_btn = browse_btn
        browse_btn.clicked.connect(self.browse_output_dir)

        open_btn = _btn("Open", "outline", height=26, icon="btn_open.png")
        open_btn.clicked.connect(self._open_output_folder)
        self._open_btn = open_btn

        dir_row = QHBoxLayout(); dir_row.setContentsMargins(0,0,0,0); dir_row.setSpacing(8)
        dir_row.addWidget(self.dir_lbl); dir_row.addWidget(browse_btn); dir_row.addWidget(open_btn)

        dir_col = QWidget(); dir_col.setStyleSheet("background:transparent;")
        dir_col.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        dir_vl = QVBoxLayout(dir_col); dir_vl.setContentsMargins(0,0,0,0); dir_vl.setSpacing(2)
        dir_vl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        dir_vl.addWidget(_cap("OUTPUT DIRECTORY"))
        dir_vl.addLayout(dir_row)
        hl.addWidget(dir_col)
        hl.addStretch()

        return bar

    # Column indices for client table
    _TC_CHK    = 0
    _TC_NAME   = 1
    _TC_GROUP  = 2
    _TC_PAN    = 3
    _TC_DOB    = 4
    _TC_SRCS   = 5   # Credential sources (Income Tax / TDS / GST)
    _TC_STATUS = 6
    _TC_TS     = 7   # Last Download Time
    _TC_PATH   = 8
    _TC_ACTS   = 9

    def _mk_client_table(self):
        self.client_table = QTableWidget(0, 10)
        self.client_table.setHorizontalHeaderLabels([
            "", "Name  ⇅", "Group  ⇅", "PAN  ⇅", "Date of Birth", "Sources",
            "Last Download Status", "Last Download Time", "Last Saved Location", ""
        ])

        _tbl = _t()
        self.client_table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{ background-color: {_tbl.bg_header}; border: none; "
            f"border-right: 1px solid {_tbl.border}; border-bottom: 1px solid {_tbl.border}; "
            f"font-weight: bold; color: {_tbl.text_muted}; font-size: 11px; height: 34px; }}"
        )
        self.client_table.verticalHeader().setVisible(False)
        self.client_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.client_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.client_table.setShowGrid(True)
        self.client_table.setAlternatingRowColors(False)

        chk_path = self.checkmark_path.replace("\\", "/")
        checkbox_style = (
            "QCheckBox { background: transparent; }"
            f"QCheckBox:focus {{ background: {_tbl.accent_light}; border-radius: 4px; }}"
            f"QCheckBox::indicator {{ width: 15px; height: 15px; border: 1.5px solid {_tbl.border}; border-radius: 3px; background: {_tbl.bg_checkbox}; }}"
            f"QCheckBox::indicator:hover {{ border-color: {_tbl.border_focus}; }}"
            f"QCheckBox::indicator:checked {{ background-color: {_tbl.accent}; border-color: {_tbl.accent}; image: url('{chk_path}'); }}"
        )
        self.client_table.setStyleSheet(
            f"QTableWidget {{ border: 1.5px solid {_tbl.border}; border-radius: 8px; background: {_tbl.bg_table}; outline: 0; gridline-color: {_tbl.grid}; }}"
            f"QTableWidget:focus {{ border: 2px solid {_tbl.border_focus}; }}"
            f"QTableWidget::item {{ border-bottom: 1px solid {_tbl.grid}; padding: 5px; }}"
            + checkbox_style
        )

        for col, align in [
            (self._TC_NAME,   Qt.AlignmentFlag.AlignCenter),
            (self._TC_GROUP,  Qt.AlignmentFlag.AlignCenter),
            (self._TC_PAN,    Qt.AlignmentFlag.AlignCenter),
            (self._TC_DOB,    Qt.AlignmentFlag.AlignCenter),
            (self._TC_STATUS, Qt.AlignmentFlag.AlignCenter),
            (self._TC_TS,     Qt.AlignmentFlag.AlignCenter),
            (self._TC_PATH,   Qt.AlignmentFlag.AlignCenter),
            (self._TC_ACTS,   Qt.AlignmentFlag.AlignCenter),
        ]:
            item = self.client_table.horizontalHeaderItem(col)
            if item:
                item.setTextAlignment(align)

        self.client_table.setColumnWidth(self._TC_CHK,    45)
        self.client_table.setColumnWidth(self._TC_GROUP, 140)
        self.client_table.setColumnWidth(self._TC_PAN,   130)
        self.client_table.setColumnWidth(self._TC_SRCS,  200)
        self.client_table.setColumnWidth(self._TC_STATUS, 170)
        self.client_table.setColumnWidth(self._TC_TS,    155)
        self.client_table.setColumnWidth(self._TC_ACTS,   52)
        self.client_table.setColumnHidden(self._TC_DOB, True)   # F-39: DOB is PII, hidden

        header = self.client_table.horizontalHeader()
        header.setSectionResizeMode(self._TC_CHK,    QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self._TC_NAME,   QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self._TC_GROUP,  QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self._TC_PAN,    QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self._TC_DOB,    QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self._TC_STATUS, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self._TC_TS,     QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self._TC_PATH,   QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self._TC_ACTS,   QHeaderView.ResizeMode.Interactive)

        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._on_header_clicked)
        self._current_sort_col = -1
        self._current_sort_order = Qt.SortOrder.AscendingOrder

        self.client_table.cellClicked.connect(self._on_cell_clicked)
        self.client_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.client_table.setMouseTracking(True)
        self.client_table.viewport().setMouseTracking(True)
        self.client_table.cellEntered.connect(self._on_cell_entered)
        self._hovered_acts_row = -1

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

    def _on_cell_double_clicked(self, row, col):
        if col == self._TC_STATUS:
            item = self.client_table.item(row, self._TC_STATUS)
            if not item:
                return
            full_text = item.toolTip() or item.text()
            if not full_text:
                return
            name_item = self.client_table.item(row, self._TC_NAME)
            name = name_item.text() if name_item else ""
            mb = QMessageBox(self)
            mb.setWindowTitle("Last Download Status")
            mb.setText(f"<b>{name}</b>" if name else "Status Detail")
            mb.setInformativeText(full_text)
            mb.setStandardButtons(QMessageBox.StandardButton.Ok)
            # Force a minimum width via a hidden spacer in the grid layout
            from PyQt6.QtWidgets import QSpacerItem, QSizePolicy
            spacer = QSpacerItem(420, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
            layout = mb.layout()
            layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())
            mb.exec()

    def _on_cell_clicked(self, row, col):
        if hasattr(self, "ay_combo") and self.ay_combo._popup_was_open:
            return

        if col == self._TC_ACTS:
            item = self.client_table.item(row, self._TC_ACTS)
            if not item:
                return
            a = item.data(Qt.ItemDataRole.UserRole + 1)
            if not a:
                return
            a_id = a.get("id")
            _mt = _t()
            menu = QMenu(self)
            menu.setStyleSheet(
                f"QMenu {{ background:{_mt.bg_menu}; border:1.5px solid {_mt.border_menu}; border-radius:6px; padding:4px 0; }}"
                f"QMenu::item {{ padding:8px 20px; font-size:12px; color:{_mt.text_primary}; }}"
                f"QMenu::item:selected {{ background:{_mt.accent}; color:{_mt.accent_text}; }}"
                f"QMenu::separator {{ height:1px; background:{_mt.border_menu}; margin:3px 0; }}"
            )
            def _cicon(f):
                p = os.path.join(_bundled_dir(), "resources", "icons", f)
                return QIcon(QPixmap(p).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)) if os.path.isfile(p) else QIcon()
            menu.addAction(_cicon("icon_edit.png"),   "Edit Client",   lambda av=a:     self._open_edit_client(av))
            menu.addSeparator()
            menu.addAction(_cicon("icon_delete.png"), "Delete Client", lambda id_=a_id: self.delete_assessee(id_))
            menu.addSeparator()
            act_log = menu.addAction(_cicon("btn_scan.png"), "View Log")
            act_log.triggered.connect(lambda checked=False, _a=a: self._show_log_history(_a))
            act_eproc = menu.addAction(_cicon("icon_preview.png"), "View e-Proceedings")
            act_eproc.triggered.connect(lambda checked=False, _a=a: self._open_eproceedings_viewer(_a))
            # Right-align menu: top-right of menu anchored to bottom-right of … cell
            from PyQt6.QtCore import QPoint
            rect    = self.client_table.visualItemRect(item)
            cell_br = self.client_table.viewport().mapToGlobal(rect.bottomRight())
            menu_w  = menu.sizeHint().width()
            menu.exec(QPoint(cell_br.x() - menu_w, cell_br.y()))
            return

        if col in (self._TC_CHK, self._TC_PATH):
            return
        # Toggle checkbox for any other column click
        cb_container = self.client_table.cellWidget(row, self._TC_CHK)
        if cb_container:
            cb = cb_container.findChild(QCheckBox)
            if cb:
                cb.setChecked(not cb.isChecked())

    def _on_cell_entered(self, row, col):
        pass

    def _on_header_clicked(self, logical_index):
        if logical_index not in (self._TC_NAME, self._TC_GROUP, self._TC_PAN):
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
        
        for row_idx in range(self.client_table.rowCount()):
            item = self.client_table.item(row_idx, self._TC_NAME)
            if item:
                row_id = item.data(Qt.ItemDataRole.UserRole)
                row_selected = row_id in self.selected_ids
                self._apply_row_style(row_idx, row_selected, row_idx)

    def _mk_control_bar(self):
        bar = QFrame()
        self._control_bar = bar
        bar.setMinimumHeight(54)
        bar.setStyleSheet(f"QFrame{{background:{_t().bg_panel};border-radius:10px;}}")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(22, 0, 16, 0)

        # F-77a: "Run in background (hide browser)" and "Send to system tray"
        # checkboxes now live in the Settings hub (see _mk_settings_page) —
        # they're app-global behavior, not Home-specific. Still constructed
        # as self.chk_headless / self.chk_auto_minimise so every existing
        # read site (automation call sites, _repaint_theme) is unaffected.
        hl.addStretch()



        # ── Assign to Group button (F-11) ─────────────────────────────────────
        self.btn_assign_group = _btn("Assign to Group…", "secondary", height=34)
        self.btn_assign_group.setToolTip("Set the Group for every currently checked client")
        self.btn_assign_group.clicked.connect(self._open_assign_group)
        hl.addWidget(self.btn_assign_group)
        hl.addSpacing(8)

        # ── Email Docs button ─────────────────────────────────────────────────
        self.btn_email_docs = _btn("Email Docs", "secondary", height=34, icon="btn_send.png")
        self.btn_email_docs.setToolTip("Mail downloaded tax documents to clients")
        self.btn_email_docs.clicked.connect(self._open_mail_docs)
        hl.addWidget(self.btn_email_docs)
        hl.addSpacing(8)

        # ── Download dropdown (split-style: label + arrow) ────────────────────
        # F-56 Phase 3: a single "Download" button opens a checkbox picker
        # (DownloadPickerDialog) instead of a dropdown menu with one action
        # per document type — lets a user select any combination for one run.
        self.btn_run = QToolButton()
        self.btn_run.setText("  Downloads")
        self.btn_run.setMinimumHeight(34)
        self.btn_run.setMinimumWidth(130)
        from ui.helpers import _icon_path
        from PyQt6.QtGui import QIcon, QPixmap
        from PyQt6.QtCore import QSize, Qt
        _run_icon_p = _icon_path("btn_run.png")
        if _run_icon_p:
            _run_px = QPixmap(_run_icon_p).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.btn_run.setIcon(QIcon(_run_px))
            self.btn_run.setIconSize(QSize(20, 20))
            self.btn_run.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_run.setStyleSheet(
            "QToolButton{"
            f"  background:{_t().success}; color:{_t().accent_text}; border:none;"
            "  border-radius:8px; font-size:12px; font-weight:600; padding:0 14px;"
            "}"
            f"QToolButton:hover{{ background:{_t().success}; }}"
            f"QToolButton:disabled{{ background:{_t().success_bg}; color:{_t().text_muted}; }}"
        )
        self.btn_run.clicked.connect(self._open_download_picker)
        hl.addWidget(self.btn_run)
        hl.addSpacing(8)

        # F-64: separate button for the "active" (record-creating) e-Pay Tax
        # flow — styled distinctly from Downloads' green since this one
        # generates real portal records rather than just fetching files.
        self.btn_epay = QToolButton()
        self.btn_epay.setText("  🧾 E-Pay Tax")
        self.btn_epay.setMinimumHeight(34)
        self.btn_epay.setMinimumWidth(130)
        self.btn_epay.setStyleSheet(
            "QToolButton{"
            f"  background:{_t().accent}; color:{_t().accent_text}; border:none;"
            "  border-radius:8px; font-size:12px; font-weight:600; padding:0 14px;"
            "}"
            f"QToolButton:hover{{ background:{_t().accent_hover}; }}"
            f"QToolButton:disabled{{ background:{_t().accent_light}; color:{_t().text_muted}; }}"
        )
        self.btn_epay.clicked.connect(self._open_generate_challans_dialog)
        hl.addWidget(self.btn_epay)
        hl.addSpacing(8)

        self.lbl_eproc_auto_status = QLabel("")
        self.lbl_eproc_auto_status.setStyleSheet(
            f"color:{_t().text_muted};font-size:10px;background:transparent;")
        self.lbl_eproc_auto_status.setWordWrap(False)
        self.lbl_eproc_auto_status.setMaximumWidth(240)
        hl.addWidget(self.lbl_eproc_auto_status)
        hl.addSpacing(8)

        # ── Exit button ───────────────────────────────────────────────────────
        self.btn_exit = _btn("Exit", "danger", height=34, icon="btn_cancel.png")
        self.btn_exit.setToolTip("Close AayDocCapio")
        self.btn_exit.clicked.connect(self.close)
        hl.addWidget(self.btn_exit)

        # ── AIS status line (hidden until Request AIS runs) ───────────────────
        self.ais_status_bar = QFrame()
        self.ais_status_bar.setFixedHeight(28)
        self.ais_status_bar.setStyleSheet(
            f"QFrame{{background:{_t().warning_bg};border-top:1px solid {_t().warning};}}")
        self.ais_status_bar.setVisible(False)
        asl = QHBoxLayout(self.ais_status_bar)
        asl.setContentsMargins(22, 0, 16, 0)
        self.ais_status_lbl = QLabel()
        self.ais_status_lbl.setStyleSheet(
            f"color:{_t().warning}; font-size:11px; background:transparent;")
        asl.addWidget(self.ais_status_lbl)
        asl.addStretch()
        ais_dismiss = QPushButton("✕")
        ais_dismiss.setFixedSize(18, 18)
        ais_dismiss.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            f"color:{_t().warning};font-size:10px;}}"
            f"QPushButton:hover{{color:{_t().warning};}}")
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

    def _mk_settings_page(self):
        """F-77a Settings hub page — General/Email/Appearance grouped on one
        page (not the mockup's tabbed dialog; that consolidation is a later
        phase). Buttons open the same dialogs/handlers the old Settings menu
        used, unchanged."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        def _section(title):
            layout.addWidget(_lbl(title, 10, bold=True, color=_t().text_muted))

        _section("GENERAL")
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        btn_yr = _btn("Manage Assessment Years", "secondary", height=34, icon="btn_scan.png")
        btn_yr.clicked.connect(self.open_manage_years)
        row1.addWidget(btn_yr)
        btn_groups = _btn("Manage Groups…", "secondary", height=34, icon="btn_scan.png")
        btn_groups.clicked.connect(self.open_manage_groups)
        row1.addWidget(btn_groups)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        btn_change_dir = _btn("Change Output Folder", "secondary", height=34, icon="btn_browse_folder.png")
        btn_change_dir.clicked.connect(self.browse_output_dir)
        row2.addWidget(btn_change_dir)
        btn_open_dir = _btn("Open Output Folder", "secondary", height=34, icon="btn_browse.png")
        btn_open_dir.clicked.connect(self._open_output_folder)
        row2.addWidget(btn_open_dir)
        row2.addStretch()
        layout.addLayout(row2)

        # Relocated from _mk_control_bar (F-77a) — same attribute names,
        # same vault-persisted keys, only the parent page changed.
        self.chk_headless = QCheckBox("Run in background (hide browser)")
        self.chk_headless.setChecked(True)
        self.chk_headless.setToolTip(
            "When ON, the automation Chrome window is hidden (headless).\n"
            "Keep OFF to watch progress or handle any CAPTCHA.")
        _ck = _t()
        self.chk_headless.setStyleSheet(
            f"QCheckBox{{font-size:12px;color:{_ck.text_muted};background:transparent;spacing:6px;}}"
            f"QCheckBox::indicator{{width:15px;height:15px;border:1.5px solid {_ck.border};"
            f"border-radius:3px;background:{_ck.bg_checkbox};}}"
            f"QCheckBox::indicator:checked{{background:{_ck.accent};border-color:{_ck.accent};"
            f"image:url(resources/check_white.png);}}")
        layout.addWidget(self.chk_headless)

        _auto_min_saved = self.vault.get_setting("auto_minimise", False) if hasattr(self, "vault") else False
        self.chk_auto_minimise = QCheckBox("Send to system tray when download starts")
        self.chk_auto_minimise.setChecked(bool(_auto_min_saved))
        self.chk_auto_minimise.setToolTip(
            "Hide the app to the system tray when a batch download begins.\n"
            "Click the tray icon or right-click → Restore to bring it back.\n"
            "The app restores automatically when the batch finishes.")
        self.chk_auto_minimise.setStyleSheet(self.chk_headless.styleSheet())
        self.chk_auto_minimise.stateChanged.connect(
            lambda v: self.vault.update_setting("auto_minimise", bool(v)))
        layout.addWidget(self.chk_auto_minimise)

        _show_splash_saved = self.vault.get_setting("show_splash", True)
        self.chk_show_splash = QCheckBox("Show splash screen on startup")
        self.chk_show_splash.setChecked(bool(_show_splash_saved))
        self.chk_show_splash.setToolTip(
            "The AayDoc Capio logo screen shown briefly while the app starts up.")
        self.chk_show_splash.setStyleSheet(self.chk_headless.styleSheet())
        self.chk_show_splash.stateChanged.connect(
            lambda v: self.vault.update_setting("show_splash", bool(v)))
        layout.addWidget(self.chk_show_splash)

        _section("E-PROCEEDINGS AUTO-FETCH")
        _auto_cfg = self.vault.get_eproc_autofetch_config()
        self.chk_eproc_autofetch = QCheckBox("Enable scheduled e-Proceedings auto-fetch")
        self.chk_eproc_autofetch.setChecked(bool(_auto_cfg["enabled"]))
        self.chk_eproc_autofetch.setToolTip(
            "Sync e-Proceedings automatically at the configured time.\n"
            "Clients whose portal password changed are skipped until the password is updated.")
        self.chk_eproc_autofetch.setStyleSheet(self.chk_headless.styleSheet())
        self.chk_eproc_autofetch.stateChanged.connect(self._on_eproc_autofetch_toggle)
        layout.addWidget(self.chk_eproc_autofetch)

        _eproc_row = QHBoxLayout()
        _eproc_row.setSpacing(8)
        btn_eproc_settings = _btn("Auto-Fetch Settings…", "secondary", height=34, icon="btn_scan.png")
        btn_eproc_settings.clicked.connect(self._open_eproc_autofetch_settings)
        _eproc_row.addWidget(btn_eproc_settings)
        self.lbl_eproc_autofetch_summary = QLabel("")
        self.lbl_eproc_autofetch_summary.setStyleSheet(
            f"color:{_t().text_muted};font-size:11px;background:transparent;")
        self.lbl_eproc_autofetch_summary.setWordWrap(True)
        _eproc_row.addWidget(self.lbl_eproc_autofetch_summary, stretch=1)
        btn_clear_flags = _btn("Clear Password Warnings", "outline", height=34)
        btn_clear_flags.setToolTip("Clear the password warning from all clients after you have updated them.")
        btn_clear_flags.clicked.connect(self._clear_eproc_credential_flags)
        _eproc_row.addWidget(btn_clear_flags)
        layout.addLayout(_eproc_row)
        self._refresh_eproc_autofetch_summary()

        _section("EMAIL")
        btn_email = _btn("Email Settings…", "secondary", height=34, icon="icon_email.png")
        btn_email.clicked.connect(self._open_email_settings)
        layout.addWidget(btn_email)

        _section("APPEARANCE")
        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        _icons = {"light": "☀", "dark": "🌙"}
        for theme_key, theme_colors in THEMES.items():
            icon = _icons.get(theme_key, "●")
            b = _btn(f"{icon}  {theme_colors.name}", "outline", height=34)
            b.setAccessibleName(f"Use {theme_colors.name} theme")
            b.clicked.connect(lambda _, k=theme_key: self._apply_theme(k))
            theme_row.addWidget(b)
        b_system = _btn("🖥  Follow system", "outline", height=34)
        b_system.setToolTip("Switch automatically with the operating system's light/dark setting")
        b_system.setAccessibleName("Follow the operating system theme")
        b_system.clicked.connect(lambda: self._apply_theme("system"))
        theme_row.addWidget(b_system)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        _section("KEYBOARD SHORTCUTS")
        kb_row = QHBoxLayout()
        kb_row.setSpacing(8)
        btn_shortcuts = _btn("Edit Shortcuts…", "secondary", height=34)
        btn_shortcuts.setToolTip("View, change or reset keyboard shortcuts for actions and pages")
        btn_shortcuts.setAccessibleName("Edit keyboard shortcuts")
        btn_shortcuts.clicked.connect(self._open_shortcut_editor)
        kb_row.addWidget(btn_shortcuts)
        _kb = _lbl(
            "Every action and page can be reached from the keyboard. "
            "Shortcuts are saved automatically and can be reset here.",
            11, color=_t().text_muted)
        _kb.setWordWrap(True)
        kb_row.addWidget(_kb, stretch=1)
        layout.addLayout(kb_row)

        layout.addStretch(1)
        return page

    def _mk_help_page(self):
        """F-77a Help hub page — same handlers the old Help menu used."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        items = [
            ("Keyboard Shortcuts…", "menu_about.png", self._open_shortcut_editor),
            ("User Manual", "menu_about.png", self._open_user_manual),
            ("Email Setup Help…", "btn_send_test.png", self._open_smtp_help),
            ("Report Bug / Request Feature…", "btn_view_log.png", self._open_feedback_picker),
            ("Check for Updates…", "menu_about.png", lambda: self._check_for_update(manual=True)),
            ("About AayDocCapio", "menu_about.png", self._show_about),
        ]
        for label, icon, handler in items:
            b = _btn(label, "secondary", height=34, icon=icon)
            b.clicked.connect(handler)
            layout.addWidget(b)

        layout.addStretch(1)
        return page

    def _mk_action_card(self, title: str, desc: str, icon_key: str, handler):
        """Icon + title + description card, matching the approved mockup's
        Income Tax landing screen. Reuses the rail's own SVG icon set
        (ui.nav_shell._svg_pixmap) for visual consistency."""
        t = _t()
        accent = t.accent_it

        card = ClickableCard()
        card.setMinimumWidth(200)
        # Scoped to #actionCard, NOT a bare "QFrame" type selector — QLabel
        # is itself a QFrame subclass, so an unscoped "QFrame{border:...}"
        # rule cascades onto every child label inside this card too,
        # individually boxing each one instead of just the card itself.
        card.setObjectName("actionCard")
        card.setStyleSheet(
            f"QFrame#actionCard{{background:{t.bg_panel};border:1px solid {t.border};border-radius:12px;}}"
            f"QFrame#actionCard:hover{{border-color:{accent};}}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 18, 18, 16)
        cl.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setPixmap(_svg_pixmap(icon_key, accent, 20))
        icon_lbl.setStyleSheet(f"background:{accent}22; border-radius:10px;")
        cl.addWidget(icon_lbl)

        title_lbl = _lbl(title, 12, bold=True)
        cl.addWidget(title_lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color:{t.text_muted}; font-size:11px; background:transparent;")
        cl.addWidget(desc_lbl)
        cl.addStretch(1)

        card.clicked.connect(handler)
        return card

    def _mk_it_tab_btn(self, label: str, idx: int):
        t = _t()
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setFixedHeight(30)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:7px;"
            f"padding:0 14px;font-size:12px;font-weight:600;color:{t.text_muted};}}"
            f"QPushButton:hover{{background:{t.accent_light};color:{t.text_primary};}}"
            f"QPushButton:focus{{border:2px solid {t.border_focus};}}"
            f"QPushButton:checked{{color:{t.accent_it};background:{t.accent_it}1A;}}"
        )
        btn.clicked.connect(lambda: self._switch_it_tab(idx))
        return btn

    def _switch_it_tab(self, idx: int):
        self._it_stack.setCurrentIndex(idx)
        for i, b in enumerate(self._it_tab_btns):
            b.setChecked(i == idx)
        if idx == 5:
            # Refresh the case workspace each time the tab is shown (the old
            # flat-table scan is kept but no longer drives the tab).
            ws = getattr(self, "_eproc_ws", None)
            if ws is not None:
                try:
                    ws.refresh()
                except Exception as exc:
                    self.log(f"[Error] e-Proceedings refresh failed: {exc}")
            else:
                self._eproc_rescan()
        if idx > 0 and hasattr(self, "_it_tab_btns"):
            self._on_hub_changed("Income Tax", self._it_tab_btns[idx].text())
        else:
            self._on_hub_changed("Income Tax", "")

    def _mk_it_dialog_tab(self, title: str, desc: str, btn_text: str, icon_key: str, handler,
                          extra_actions=None):
        """Sub-tab for an action that still opens its existing modal dialog
        (Download Documents / E-Pay Tax / Return Status) rather than being
        embedded inline — that's a larger later phase (F-77c).

        `extra_actions`: optional list of (label, icon_key, handler) shown as
        secondary buttons under the primary action (F-12's View Challans)."""
        t = _t()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addWidget(_lbl(title, 14, bold=True))
        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color:{t.text_muted}; font-size:12px; background:transparent;")
        layout.addWidget(desc_lbl)
        layout.addSpacing(6)
        btn = _btn(btn_text, "primary", height=36, icon=icon_key)
        btn.setMaximumWidth(260)
        btn.clicked.connect(handler)
        layout.addWidget(btn)
        for label, icon, action in (extra_actions or []):
            extra = _btn(label, "secondary", height=34, icon=icon)
            extra.setMaximumWidth(260)
            extra.clicked.connect(action)
            layout.addWidget(extra)
        layout.addStretch(1)
        return page

    def _mk_dl_doc_card(self, key: str, title: str, sub: str) -> QFrame:
        """One checkable document-type card for the Download Documents tab —
        clicking anywhere on the card toggles its checkbox, matching the
        mockup's doc-card interaction."""
        t = _t()
        card = QFrame()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setMinimumHeight(72)
        card.setObjectName("docCard")  # scoped selector — see _mk_action_card for why
        card.setStyleSheet(
            f"QFrame#docCard{{background:{t.bg_panel};border:1px solid {t.border};border-radius:10px;}}"
        )
        hl = QHBoxLayout(card)
        hl.setContentsMargins(14, 12, 14, 12)
        hl.setSpacing(10)

        cb = QCheckBox()
        cb.setStyleSheet(
            f"QCheckBox::indicator{{width:16px;height:16px;border:1.5px solid {t.border};"
            f"border-radius:4px;background:{t.bg_checkbox};}}"
            f"QCheckBox::indicator:checked{{background:{t.accent_it};border-color:{t.accent_it};"
            f"image:url(resources/check_white.png);}}")
        hl.addWidget(cb, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_lbl = _lbl(title, 12, bold=True)
        text_col.addWidget(title_lbl)
        sub_lbl = QLabel(sub)
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(f"color:{t.text_muted}; font-size:11px; background:transparent;")
        text_col.addWidget(sub_lbl)
        hl.addLayout(text_col, 1)

        def _toggle_border(checked):
            card.setStyleSheet(
                f"QFrame#docCard{{background:{t.bg_panel};"
                f"border:1px solid {t.accent_it if checked else t.border};border-radius:10px;}}")
        cb.toggled.connect(_toggle_border)

        def _mouse_press(event):
            if event.button() == Qt.MouseButton.LeftButton:
                cb.toggle()
            QFrame.mousePressEvent(card, event)
        card.mousePressEvent = _mouse_press

        self._dl_doc_cbs[key] = cb
        return card

    def _dl_toggle_all_clients(self, checked: bool):
        """Check/uncheck only the clients currently visible (matching the
        active search filter) — so a filtered "Select all" can't silently
        touch rows the user can't see."""
        for cb in self._dl_client_cbs.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        visible_ids = set(self._dl_client_cbs.keys())
        if checked:
            self._dl_selected_ids |= visible_ids
        else:
            self._dl_selected_ids -= visible_ids
        self._dl_update_summary()

    def _dl_on_client_toggle(self, client_id: str, checked: bool):
        if checked:
            self._dl_selected_ids.add(client_id)
        else:
            self._dl_selected_ids.discard(client_id)
        self._dl_update_summary()

    def _dl_apply_client_filter(self, text: str):
        """Rebuild Section A's rows filtered by `text` (name / PAN / group).
        Selection state lives in self._dl_selected_ids so filtering never
        loses which clients were already ticked."""
        self._dl_refresh_clients()

    def _dl_refresh_clients(self):
        """(Re)build Section A's client rows from self.assessee_list. Called
        once when the tab is first built (assessee_list doesn't exist yet
        at that point — _build_ui() runs before the first refresh_grid())
        and again every time refresh_grid() runs (including on every theme
        switch, since _repaint_theme() calls refresh_grid() for the main
        client_table too), so add/edit/delete/import stay reflected here.

        Uses a real QTableWidget — matching self.client_table's own
        pattern exactly (QTableWidgetItem cells + a WA_StyledBackground
        checkbox container) — rather than hand-rolled QLabel/QFrame rows.
        The earlier hand-rolled version rendered every cell wrapped in a
        stray bordered box in practice: plain QWidget/QFrame children only
        honour a stylesheet `background` once WA_StyledBackground is set,
        which client_table's own checkbox cells already do (see
        refresh_grid()) and the old version of this method didn't.
        QTableWidgetItem sidesteps the whole issue — its painting isn't
        stylesheet-cascaded child-widget painting at all. This is also
        far cheaper to rebuild than ~400 individual QWidgets, which is
        what made theme switches feel like a hang before."""
        if not hasattr(self, "_dl_table"):
            return
        t = _t()
        table = self._dl_table
        table.setRowCount(0)
        self._dl_client_cbs = {}
        assessees = getattr(self, "assessee_list", [])

        q = ""
        search = getattr(self, "_dl_search", None)
        if search is not None:
            q = search.text().strip().lower()
        if not hasattr(self, "_dl_selected_ids"):
            self._dl_selected_ids = {a.get("id") for a in assessees}
        else:
            known = {a.get("id") for a in assessees}
            self._dl_selected_ids &= known

        if q:
            assessees = [a for a in assessees
                         if q in (a.get("name") or "").lower()
                         or q in (a.get("pan") or "").lower()
                         or q in (a.get("group") or "").lower()]

        table.setRowCount(len(assessees))
        for i, a in enumerate(assessees):
            cb_container = QWidget()
            cb_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            cb_container.setStyleSheet(f"QWidget{{background:{t.bg_table};}}")
            cl = QHBoxLayout(cb_container)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox()
            cb.setStyleSheet(
                f"QCheckBox{{background:transparent;}}"
                f"QCheckBox::indicator{{width:15px;height:15px;border:1.5px solid {t.border};"
                f"border-radius:3px;background:{t.bg_checkbox};}}"
                f"QCheckBox::indicator:checked{{background:{t.accent_it};border-color:{t.accent_it};"
                f"image:url(resources/check_white.png);}}")
            cid = a.get("id")
            cb.setChecked(cid in self._dl_selected_ids)
            cb.toggled.connect(lambda checked, _cid=cid: self._dl_on_client_toggle(_cid, checked))
            self._dl_client_cbs[cid] = cb
            cl.addWidget(cb)
            table.setCellWidget(i, 0, cb_container)

            name_item = QTableWidgetItem(a.get("name", ""))
            table.setItem(i, 1, name_item)
            pan_item = QTableWidgetItem(a.get("pan", "—"))
            table.setItem(i, 2, pan_item)
            group_item = QTableWidgetItem(a.get("group") or "—")
            table.setItem(i, 3, group_item)
        if hasattr(self, "_dl_summary_lbl"):
            self._dl_update_summary()

    def _dl_update_summary(self):
        if not hasattr(self, "_dl_summary_lbl"):
            return
        n_clients = sum(1 for cb in self._dl_client_cbs.values() if cb.isChecked())
        n_docs = sum(1 for cb in self._dl_doc_cbs.values() if cb.isChecked())
        self._dl_summary_lbl.setText(
            f"{n_clients} client{'s' if n_clients != 1 else ''} × "
            f"{n_docs} document{'s' if n_docs != 1 else ''} selected")
        if (hasattr(self, "_dl_scope_panel")
                and "filed_returns" in self._dl_doc_cbs):
            self._dl_scope_panel.setVisible(
                self._dl_doc_cbs["filed_returns"].isChecked())

    def _populate_dl_ay_combo(self):
        """(Re)fill the Download Documents tab's AY/TY selector from the same
        year list the Home selector uses, carrying over whatever is currently
        checked there. Never re-checked from a saved setting — same
        deliberate "starts empty every launch" rule as self.ay_combo."""
        if not hasattr(self, "_dl_ay_combo"):
            return
        enabled = [e["label"] for e in self._load_ay_list() if e.get("enabled", True)]
        current = set(self.ay_combo.checked_labels()) if hasattr(self, "ay_combo") else set()
        self._dl_ay_combo.blockSignals(True)
        self._dl_ay_combo.clear_items()
        for _label in enabled:
            self._dl_ay_combo.add_item(_label, checked=(_label in current))
        self._dl_ay_combo.blockSignals(False)

    def _sync_ay_to_dl(self):
        """Mirror self.ay_combo's checked years onto the tab's selector.
        Guarded against re-entrancy so the two selectors' itemChanged
        signals can't ping-pong forever."""
        if not hasattr(self, "_dl_ay_combo") or getattr(self, "_ay_syncing", False):
            return
        self._ay_syncing = True
        try:
            self._dl_ay_combo.blockSignals(True)
            self._dl_ay_combo.set_checked_labels(self.ay_combo.checked_labels())
            self._dl_ay_combo.blockSignals(False)
        finally:
            self._ay_syncing = False

    def _sync_dl_to_ay(self):
        """Mirror the tab selector's checked years back onto self.ay_combo,
        which start_automation() reads as the source of truth."""
        if not hasattr(self, "_dl_ay_combo") or getattr(self, "_ay_syncing", False):
            return
        self._ay_syncing = True
        try:
            self.ay_combo.blockSignals(True)
            self.ay_combo.set_checked_labels(self._dl_ay_combo.checked_labels())
            self.ay_combo.blockSignals(False)
        finally:
            self._ay_syncing = False
        self._log_ay_selection()
        self.refresh_grid()

    def _dl_run(self):
        n_docs = sum(1 for cb in self._dl_doc_cbs.values() if cb.isChecked())
        if n_docs == 0:
            QMessageBox.warning(self, "Nothing Selected", "Please select at least one document type.")
            return
        known_ids = {a.get("id") for a in getattr(self, "assessee_list", [])}
        checked_ids = set(getattr(self, "_dl_selected_ids", set())) & known_ids
        if not checked_ids:
            QMessageBox.warning(self, "Selection Required", "Please select at least one client.")
            return
        self.selected_ids = checked_ids
        scope = "latest" if getattr(self, "_dl_rb_latest", None) and self._dl_rb_latest.isChecked() else "all"
        self.vault.update_setting("filed_returns_scope", scope)
        selected_docs = {key for key, cb in self._dl_doc_cbs.items() if cb.isChecked()}
        self.start_automation(selected_docs)

    def _mk_it_download_tab(self):
        """Download Documents tab — the mockup's real 3-section form
        (Select Clients / Select Documents / Execute), inline instead of
        the DownloadPickerDialog modal. Feeds the exact same
        self.selected_ids + start_automation(selected_docs) pipeline the
        Home hub's grid + dialog already use — this is a new front end
        for that pipeline, not a parallel implementation of it. Document
        types and their keys match DownloadPickerDialog exactly (26as/
        request_ais/ais_tis/filed_returns/challans), including the
        conditional Filing Scope panel."""
        t = _t()
        self._dl_client_cbs: dict[str, QCheckBox] = {}
        self._dl_doc_cbs: dict[str, QCheckBox] = {}

        page = QWidget()
        page.setObjectName("dlDocPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.setStyleSheet(f"QWidget#dlDocPage{{background:{t.bg_window};}}")
        page_v = QVBoxLayout(page)
        page_v.setContentsMargins(0, 0, 0, 0)

        # Whole tab body scrolls as one page so short windows degrade
        # gracefully instead of clipping the footer / doc grid.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{background:transparent;border:none;}}"
            f"QScrollArea > QWidget > QWidget{{background:transparent;}}")
        content = QWidget()
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setStyleSheet(f"QWidget{{background:{t.bg_window};}}")
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(12)
        scroll.setWidget(content)
        page_v.addWidget(scroll)

        outer.addWidget(_lbl("Download Documents", 14, bold=True))
        sub = QLabel("Pick clients, pick documents, then run — one batch, unattended.")
        sub.setStyleSheet(f"color:{t.text_muted}; font-size:12px; background:transparent;")
        outer.addWidget(sub)

        # ── Section A: Select Clients ────────────────────────────────────────
        sec_a = QVBoxLayout()
        sec_a.setSpacing(8)
        a_hdr = QHBoxLayout()
        a_hdr.setSpacing(8)
        a_hdr.addWidget(_lbl("A   Select Clients", 12, bold=True, color=t.accent_it))
        self._dl_search = QLineEdit()
        self._dl_search.setPlaceholderText("🔍  Search by name, PAN or group…")
        self._dl_search.setMinimumHeight(30)
        self._dl_search.setClearButtonEnabled(True)
        self._dl_search.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self._dl_search.textChanged.connect(self._dl_apply_client_filter)
        a_hdr.addWidget(self._dl_search, 1)
        select_all_cb = QCheckBox("Select all")
        select_all_cb.setChecked(True)
        select_all_cb.toggled.connect(self._dl_toggle_all_clients)
        a_hdr.addWidget(select_all_cb)
        sec_a.addLayout(a_hdr)

        # Assessment Year / Tax Year (B-1) — the Home hub's own selector is
        # not reachable from this hub (hubs are one-per-screen), so this tab
        # needs its own. Both selectors are kept mirror-identical via
        # _sync_ay_to_dl / _sync_dl_to_ay so a year picked here also applies
        # on Home (and vice versa), and start_automation() keeps reading
        # self.ay_combo as the single source of truth.
        ay_hdr = QHBoxLayout()
        ay_hdr.setSpacing(8)
        ay_cap = _lbl("ASSESSMENT / TAX YEAR", 10, bold=True, color=t.text_muted)
        ay_hdr.addWidget(ay_cap)
        self._dl_ay_combo = CheckableComboBox(placeholder="Select AY/TY")
        self._dl_ay_combo.setFixedWidth(220)
        self._dl_ay_combo.model_.itemChanged.connect(lambda _item: self._sync_dl_to_ay())
        ay_hdr.addWidget(self._dl_ay_combo)
        dl_manage_btn = QPushButton("⚙")
        dl_manage_btn.setFixedSize(24, 24)
        dl_manage_btn.setToolTip("Manage Years")
        dl_manage_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;font-size:14px;color:{t.text_muted};}}"
            f"QPushButton:hover{{color:{t.accent_it};}}")
        dl_manage_btn.clicked.connect(self.open_manage_years)
        ay_hdr.addWidget(dl_manage_btn)
        ay_hdr.addStretch(1)
        sec_a.addLayout(ay_hdr)
        self._populate_dl_ay_combo()

        self._dl_table = QTableWidget()
        self._dl_table.setColumnCount(4)
        self._dl_table.setHorizontalHeaderLabels(["", "Name", "PAN", "Group"])
        self._dl_table.verticalHeader().setVisible(False)
        self._dl_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._dl_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._dl_table.setShowGrid(False)
        self._dl_table.setMinimumHeight(260)
        self._dl_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._dl_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._dl_table.setColumnWidth(0, 34)
        self._dl_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._dl_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._dl_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._dl_table.setStyleSheet(
            f"QTableWidget{{border:1px solid {t.border};border-radius:10px;"
            f"background:{t.bg_table};outline:0;gridline-color:{t.grid};}}"
            f"QTableWidget::item{{border-bottom:1px solid {t.grid};padding:6px;color:{t.text_primary};}}")
        self._dl_table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section{{background-color:{t.bg_header};border:none;"
            f"border-bottom:1px solid {t.border};font-weight:bold;color:{t.text_muted};"
            f"font-size:10px;height:28px;padding-left:4px;}}")
        sec_a.addWidget(self._dl_table, 1)
        outer.addLayout(sec_a, 1)
        self._dl_refresh_clients()

        # ── Section B: Select Documents ──────────────────────────────────────
        sec_b = QVBoxLayout()
        sec_b.setSpacing(8)
        sec_b.addWidget(_lbl("B   Select Documents", 12, bold=True, color=t.accent_it))
        doc_grid = QGridLayout()
        doc_grid.setHorizontalSpacing(12)
        doc_grid.setVerticalSpacing(12)
        doc_cards = [
            self._mk_dl_doc_card("26as", "26AS / Form 168", "PDF + Excel/TXT — form picked automatically by year"),
            self._mk_dl_doc_card("request_ais", "AIS + TIS", "Requests generation if not ready yet, downloads instantly if it is"),
            self._mk_dl_doc_card("ais_tis", "Previously Requested AIS", "For AIS requested earlier that should be ready now"),
            self._mk_dl_doc_card("filed_returns", "ITR Return + Intimation", "Form, Receipt/ITR-V, JSON, and any Intimation Orders"),
            self._mk_dl_doc_card("challans", "Tax Payment Challans", "From e-Pay Tax Payment History for the selected year"),
            self._mk_dl_doc_card("e_proceedings", "e-Proceedings Documents", "Notices, orders and submitted responses — all proceedings"),
            self._mk_dl_doc_card("filed_forms", "Filed IT Forms", "All forms filed under Income Tax Forms — 15CA, 3CD, 10IE, 35 and others"),
        ]
        for i, card in enumerate(doc_cards):
            doc_grid.addWidget(card, i // 3, i % 3)
        for col in range(3):
            doc_grid.setColumnStretch(col, 1)
        sec_b.addLayout(doc_grid)
        for cb in self._dl_doc_cbs.values():
            cb.toggled.connect(self._dl_update_summary)

        # Filing scope — only relevant once "ITR Return + Intimation" is checked
        scope_panel = QFrame()
        self._dl_scope_panel = scope_panel
        scope_panel.setObjectName("scopePanel")  # scoped selector — see _mk_action_card
        scope_panel.setStyleSheet(
            f"QFrame#scopePanel{{background:{t.bg_table_alt};border:1px solid {t.border};"
            f"border-left:3px solid {t.accent_it};border-radius:6px;}}")
        scope_v = QVBoxLayout(scope_panel)
        scope_v.setContentsMargins(12, 10, 12, 10)
        scope_v.setSpacing(4)
        scope_v.addWidget(_lbl("FILING SCOPE", 10, bold=True, color=t.text_muted))
        self._dl_rb_all = QRadioButton("All filings for the year")
        self._dl_rb_latest = QRadioButton("Latest filing only")
        saved_scope = self.vault.get_setting("filed_returns_scope", "all")
        (self._dl_rb_latest if saved_scope == "latest" else self._dl_rb_all).setChecked(True)
        scope_v.addWidget(self._dl_rb_all)
        scope_v.addWidget(self._dl_rb_latest)
        scope_panel.setVisible(False)
        sec_b.addWidget(scope_panel)
        outer.addLayout(sec_b)

        # ── Section C: Execute ───────────────────────────────────────────────
        sec_c = QFrame()
        sec_c.setObjectName("execBar")  # scoped selector — see _mk_action_card
        sec_c.setStyleSheet(
            f"QFrame#execBar{{background:{t.bg_panel};border:1px solid {t.border};border-radius:10px;}}")
        c_layout = QHBoxLayout(sec_c)
        c_layout.setContentsMargins(14, 6, 14, 6)
        c_layout.setSpacing(12)
        self._dl_summary_lbl = _lbl("", 11, bold=True)
        c_layout.addWidget(self._dl_summary_lbl)
        c_layout.addStretch(1)
        run_btn = _btn("Download Selected", "primary", height=30, icon="btn_run.png")
        run_btn.clicked.connect(self._dl_run)
        c_layout.addWidget(run_btn)
        outer.addWidget(sec_c)

        self._dl_update_summary()
        return page

    def _mk_it_tools_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(14)
        outer.addWidget(_lbl("Tools", 14, bold=True))
        desc = QLabel("Manual conversions for when a full batch run isn't what you need.")
        desc.setStyleSheet(f"color:{_t().text_muted}; font-size:12px; background:transparent;")
        outer.addWidget(desc)
        grid = QHBoxLayout()
        grid.setSpacing(14)
        grid.addWidget(self._mk_action_card(
            "Convert 26AS to Excel",
            "Turn a downloaded 26AS/168 TXT into the same Excel + HTML report a batch run produces.",
            "document", self._convert_26as_manual))
        grid.addWidget(self._mk_action_card(
            "Convert AIS JSON to Excel",
            "Per-category sheets, capital market consolidation, auto-computed STCG & LTCG.",
            "document", self._convert_ais_json_manual))
        outer.addLayout(grid)
        outer.addStretch(1)
        return page

    def _mk_it_return_status_tab(self):
        """Income Tax hub ▸ Return Status (F-121) — inline FY selector + a
        filterable table of every client with Income Tax credentials, built
        from the persisted return-status data. "Fetch Selected" re-checks the
        ticked clients live from the portal via start_return_status_check()
        (the same worker/progress-dialog flow as before); this tab refreshes
        itself when that batch finishes. Replaces the old ReturnStatusDialog.
        """
        def _root_getter():
            try:
                return self.dir_lbl.text()
            except Exception:
                return ""

        self._retstatus_tab = ReturnStatusTab(
            self.vault, self._ay_entries,
            download_root_getter=_root_getter,
            start_fetch=self._on_retstatus_tab_fetch,
            log_callback=self.log,
            parent=self,
        )
        return self._retstatus_tab

    def _on_retstatus_tab_fetch(self, ay_value, targets):
        """ReturnStatusTab 'Fetch Selected' → run the live scan, then
        refresh the tab when the batch is done."""
        tab = getattr(self, "_retstatus_tab", None)
        self.start_return_status_check(
            ay_value, targets, on_done=(tab.refresh if tab else None))

    def _mk_it_eproceedings_tab(self):
        """Income Tax hub ▸ e-Proceedings (F-60 v3 — case workspace).

        Replaces the earlier flat-table view with ui.eproceedings.
        EProceedingsWorkspace: KPI row, left case list (one card per
        proceeding), right detail workspace with Overview / Case Timeline /
        Appeals / Limitations tabs and the cross-linking document modal.

        The previous implementation's helper methods (_eproc_rescan,
        _eproc_populate, the table, chips, etc.) are intentionally LEFT IN
        PLACE below but unused — kept until the new workspace has proven
        itself in daily use, per the user's instruction not to delete yet.
        """
        # Build the workspace defensively: a UI regression here must never
        # take the whole app down at startup — fall back to a readable error
        # page and keep the rest of the program usable.
        try:
            self._eproc_ws = EProceedingsWorkspace(
                self.vault,
                lambda: getattr(self, "assessee_list", []) or [],
                self,
            )
            return self._eproc_ws
        except Exception as exc:
            self._eproc_ws = None
            self.log(f"[Error] e-Proceedings workspace failed to build: {exc}")
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(24, 24, 24, 24)
            lay.addStretch(1)
            lay.addWidget(_lbl("e-Proceedings view could not load.", 14, bold=True))
            lay.addWidget(_lbl(str(exc), 11, color=_t().text_muted))
            lay.addWidget(_lbl(
                "The rest of the app is unaffected. Check the activity log.",
                11, color=_t().text_muted))
            lay.addStretch(1)
            return page

    # ── e-Proceedings tab: chips / dashboard cards ────────────────────────────

    def _eproc_set_chip(self, key: str):
        """Chip clicked → remember state, re-apply the row filter. Exclusive
        QButtonGroup keeps only one chip checked; state drives the predicate
        in _eproc_apply_filter."""
        self._eproc_chip = key
        self._eproc_apply_filter()

    def _eproc_update_dashboard(self):
        """Refresh the GLOBAL dashboard cards (shown above the nav stack, so
        they stay visible on every hub/tab — not just e-Proceedings).
        Last Sync = newest downloaded_at across all _meta.json files (or
        newest file mtime); Failed Clients = union of vault download_history
        entries whose worst status looks failed; Latest Fetched = newest
        file across all e-Proceedings downloads with click-through to its
        folder."""
        cards = getattr(self, "_eproc_dash", None)
        if not cards:
            return
        t = _t()
        today = datetime.date.today()
        now = datetime.datetime.now()

        if not getattr(self, "_eproc_cases", None):
            self._eproc_scan_all_only()

        # Last Sync: max downloaded_at across cases, fallback newest mtime.
        latest_dt = None
        newest_file = None
        for c in self._eproc_cases:
            if c.get("downloaded_at"):
                try:
                    dt = datetime.datetime.strptime(c["downloaded_at"],
                                                    "%Y-%m-%d %H:%M:%S")
                    if latest_dt is None or dt > latest_dt:
                        latest_dt = dt
                except ValueError:
                    pass
            for r in c.get("_file_rows", []):
                try:
                    m = datetime.datetime.fromtimestamp(os.path.getmtime(r["path"]))
                except OSError:
                    continue
                if latest_dt is None or m > latest_dt:
                    latest_dt = m
                    newest_file = r
        sync_lbl = self._eproc_dash["sync"]["value"]
        if latest_dt is None:
            sync_lbl.setText("—")
            sync_lbl.setStyleSheet(f"color:{t.text_primary}; font-size:13px; font-weight:bold;")
            sync_lbl.setToolTip("")
        else:
            delta = now - latest_dt
            days = delta.days
            rel = ("just now" if delta < datetime.timedelta(minutes=1)
                   else f"{int(delta.total_seconds() // 60)}m ago" if delta < datetime.timedelta(hours=1)
                   else f"{days}d ago" if days < 7
                   else f"{days // 7}w ago" if days < 30
                   else f"{days // 30}mo ago")
            sync_text = f"{rel} · {latest_dt.strftime('%d %b %Y')}"
            sync_lbl.setText(sync_text)
            stale = latest_dt.date() < today - datetime.timedelta(days=7)
            sync_lbl.setStyleSheet(
                f"color:{t.warning if stale else t.text_primary}; "
                f"font-size:13px; font-weight:bold;")
            if newest_file:
                sync_lbl.setToolTip(newest_file["path"])

        # Failed Clients: for every AY label present in the scanned rows, ask
        # the vault's download history which clients failed — union across
        # years, dedupe by PAN.
        failed = {}   # pan → worst status text
        for c in self._eproc_cases:
            m = re.match(r"^(A[YZ]|TY)_(\d{4})_(\d{2})$", c["year_dir"])
            if not m:
                continue
            ay_label = f"{m.group(1)[0]}Y {m.group(2)[-2:]}-{m.group(3)}"
            try:
                summary = self.vault.get_download_history_summary(ay_label)
            except Exception:
                continue
            for pan, info in summary.items():
                status = (info or {}).get("status", "")
                if "❌" in status or "failed" in status.lower():
                    if pan not in failed or self.vault._status_rank(status) > \
                            self.vault._status_rank(failed[pan]):
                        failed[pan] = status
        fail_lbl = self._eproc_dash["failed"]["value"]
        if failed:
            fail_lbl.setText(str(len(failed)))
            fail_lbl.setStyleSheet(
                f"color:{t.error}; font-size:13px; font-weight:bold;")
            lines = [f"{pan} — {failed[pan]}" for pan in sorted(failed)]
            fail_lbl.setToolTip("\n".join(lines[:10]))
        else:
            fail_lbl.setText("0")
            fail_lbl.setStyleSheet(
                f"color:{t.success}; font-size:13px; font-weight:bold;")
            fail_lbl.setToolTip("")

        # Latest Fetched: 3 newest files (newest first).
        latest_lbl = self._eproc_dash["latest"]["value"]
        all_files = [r for c in self._eproc_cases for r in c.get("_file_rows", [])]
        all_files.sort(key=lambda r: r.get("_dt") or datetime.datetime.min, reverse=True)
        if all_files:
            first = all_files[0]
            name = first["file"]
            shown = name if len(name) <= 28 else name[:27] + "…"
            latest_lbl.setText(f"{shown}" + (f" +{len(all_files) - 1} more"
                                             if len(all_files) > 1 else ""))
            latest_lbl.setStyleSheet(
                f"color:{t.text_primary}; font-size:13px; font-weight:bold;")
            tips = [f"{r['client']} — {r['file']}" for r in all_files[:10]]
            latest_lbl.setToolTip("\n".join(tips))
        else:
            latest_lbl.setText("—")
            latest_lbl.setStyleSheet(
                f"color:{t.text_muted}; font-size:13px; font-weight:bold;")
            latest_lbl.setToolTip("")

    def _eproc_open_latest_folder(self):
        """Latest Fetched card click → open the folder holding the newest
        file (or its year folder when the file itself is gone)."""
        if not self._eproc_cases:
            return
        all_files = [r for c in self._eproc_cases for r in c.get("_file_rows", [])]
        if not all_files:
            return
        newest = max(all_files, key=lambda r: r.get("_dt") or datetime.datetime.min)
        folder = os.path.dirname(newest["path"]) or newest.get("folder", "")
        self._eproc_open_path(folder if os.path.isdir(folder) else newest.get("folder"))

    # ── e-Proceedings tab: scan / populate / filter / open ────────────────────

    @staticmethod
    def _eproc_human_size(n: int) -> str:
        """Same formatting as EProceedingsDialog._human_size."""
        if n >= 1024 * 1024:
            return f"{n / (1024 * 1024):.1f} MB"
        if n >= 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n} B"

    def _eproc_rescan_into_cases(self, root: str):
        """Filesystem walk shared by the tab and the global dashboard: builds
        self._eproc_cases (+ per-case _file_rows) with no widget side effects.
        <root>/<PAN>-<NameSafe>/<AY_*|TY_*>/e-Proceedings/<NN>-<Proc>/{notice-*,response-*}/<files>.
        Each proceeding dir with a _meta.json contributes its parsed notices;
        legacy trees are inferred (kind from subfolder, responded = any
        response file, issue date from a trailing _DDMMYYYY in the filename).
        Year is NOT a filter — every year folder counts."""
        from ui.dialogs import EProceedingsDialog
        by_pan = {a.get("pan", "").upper(): a for a in self.assessee_list}
        cases = []
        if root and os.path.isdir(root):
            for entry in sorted(os.listdir(root)):
                client_dir = os.path.join(root, entry)
                if not os.path.isdir(client_dir) or "-" not in entry:
                    continue
                pan = entry.split("-", 1)[0].strip().upper()
                match = by_pan.get(pan)
                client_name = (match or {}).get("name") or entry
                for year_name in sorted(os.listdir(client_dir)):
                    year_dir = os.path.join(client_dir, year_name)
                    if not os.path.isdir(year_dir):
                        continue
                    if not (year_name.startswith("AY_") or year_name.startswith("TY_")):
                        continue
                    eproc_root = os.path.join(year_dir, "e-Proceedings")
                    if not os.path.isdir(eproc_root):
                        continue
                    for proc in EProceedingsDialog._scan_proceedings(eproc_root):
                        pname = proc["name"]
                        nd = 0
                        while nd < len(pname) and pname[nd].isdigit():
                            nd += 1
                        proc_display = pname[nd:].lstrip("-").strip() if nd else pname
                        meta = self._eproc_load_proc_meta(proc["dir"])
                        notices = self._eproc_case_notices(
                            proc, meta, proc_display or proc["name"])
                        case = {
                            "client": client_name,
                            "pan": pan,
                            "year_dir": year_dir,
                            "year_name": year_name,
                            "proc_dir": proc["dir"],
                            "proc_display": proc_display or proc["name"],
                            "proc_raw": proc["name"],
                            "proc_num": proc["num"],
                            "meta": meta,
                            "notices": notices,
                            "downloaded_at": (meta or {}).get("downloaded_at", ""),
                            "_proc_files": proc["files"],
                            "_file_rows": [],
                        }
                        cases.append(case)
        cases.sort(key=lambda c: (c["client"].lower(), c["proc_num"],
                                  c["proc_raw"].lower()))
        for case in cases:
            self._eproc_build_file_rows(case)
            self._eproc_classify_case(case)
        self._eproc_cases = cases

    def _eproc_rescan(self):
        """Refresh the GLOBAL dashboard + the tab's chips/summary/table after
        a fresh disk scan (Refresh button, or opening the tab)."""
        root = self.vault.get_setting("download_root_dir", "")
        self._eproc_rescan_into_cases(root)
        cases = self._eproc_cases

        self._eproc_update_dashboard()
        self._eproc_update_chip_counts()
        n_clients = len({c["pan"] for c in cases})
        n_procs = len(cases)
        n_notices = sum(len(c["notices"]) for c in cases)
        n_resp = sum(1 for c in cases for n in c["notices"] if n["responded"])
        n_files = 0
        total_size = 0
        for c in cases:
            for r in c.get("_file_rows", []):
                n_files += 1
                total_size += r["size"]
        self._eproc_summary.setText(
            f"{n_clients} client{'s' if n_clients != 1 else ''} • "
            f"{n_procs} proceeding{'s' if n_procs != 1 else ''} • "
            f"{n_notices} notice{'s' if n_notices != 1 else ''} "
            f"({n_resp} responded) • "
            f"{n_files} file{'s' if n_files != 1 else ''} • "
            f"{self._eproc_human_size(total_size)}")
        self._eproc_populate()
        self._eproc_apply_filter()
        return

    # ── e-Proceedings tab: metadata helpers ───────────────────────────────────

    @staticmethod
    def _eproc_load_proc_meta(proc_dir: str):
        """Read <proc_dir>/_meta.json (schema written by
        automation/downloader_e_proceedings._build_proc_meta). Returns {} when
        absent/unreadable — callers then fall back to legacy inference."""
        path = os.path.join(proc_dir, "_meta.json")
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _eproc_parse_ddmmyyyy(name: str):
        """Trailing _DDMMYYYY in a filename → datetime.date (display
        DD-Mon-YYYY), else None. Legacy inference only."""
        m = re.search(r"_(\d{2})(\d{2})(\d{4})(?:\.\w+)?$", name)
        if not m:
            return None
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    @staticmethod
    def _eproc_fmt_date(d) -> str:
        if isinstance(d, str):
            return d or "—"
        return d.strftime("%d-%b-%Y") if isinstance(d, datetime.date) else "—"

    @staticmethod
    def _eproc_parse_disp_date(s: str):
        """DD-Mon-YYYY (portal style, e.g. '26-Nov-2024') → date, else None."""
        try:
            return datetime.datetime.strptime(s, "%d-%b-%Y").date()
        except (ValueError, TypeError):
            return None

    @classmethod
    def _eproc_case_notices(cls, proc: dict, meta: dict, proc_display: str) -> list:
        """Build the notice list for one proceeding. With _meta.json the
        portal metadata is authoritative; without it (legacy download) each
        file becomes its own synthesized notice — kind from subfolder,
        responded = any response-* file exists in the proceeding, issue date
        from a trailing _DDMMYYYY, due/section unknown → '—', is_order from
        the filename. Every notice carries a files/response_files list so
        each file row can find its notice metadata."""
        if meta:
            out = []
            for n in meta.get("notices", []):
                entry = {
                    "index": n.get("index", 0),
                    "ref_id": n.get("ref_id", ""),
                    "description": n.get("description", ""),
                    "issued_on": n.get("issued_on", ""),
                    "response_due": n.get("response_due", ""),
                    "responded": bool(n.get("responded", False)),
                    "section": n.get("section", ""),
                    "viewed_by_ao": n.get("viewed_by_ao", ""),
                    "is_order": bool(n.get("is_order", False)),
                    "files": list(n.get("files", [])),
                    "response_files": list(n.get("response_files", [])),
                    "legacy": False,
                }
                out.append(entry)
            return out
        # Legacy: infer per file. responded = ANY response file in proc.
        has_response = any(
            os.path.dirname(os.path.relpath(f["path"], proc["dir"])).lower().startswith("response")
            for f in proc["files"])
        out = []
        for f in proc["files"]:
            rel = os.path.relpath(f["path"], proc["dir"]).replace(os.sep, "/")
            issued = cls._eproc_parse_ddmmyyyy(f["name"])
            out.append({
                "index": 0,
                "ref_id": "",
                "description": "",
                "issued_on": cls._eproc_fmt_date(issued),
                "response_due": "",
                "responded": has_response if f["kind"] == "Notice" else True,
                "section": "",
                "viewed_by_ao": "",
                "is_order": "order" in f["name"].lower(),
                "files": [rel] if f["kind"] != "Response" else [],
                "response_files": [rel] if f["kind"] == "Response" else [],
                "legacy": True,
            })
        return out

    def _eproc_build_file_rows(self, case: dict):
        """Materialise the flat file rows for one case: every scanned file
        joins its notice (files/response_files membership by relative path;
        legacy notices each own exactly one file) and its computed display
        fields. Row dicts feed _eproc_populate and the dashboard cards."""
        rows = []
        for f in case.get("_proc_files", []):
            rel = os.path.relpath(f["path"], case["proc_dir"]).replace(os.sep, "/")
            notice = None
            for n in case["notices"]:
                if rel in n["files"] or rel in n["response_files"]:
                    notice = n
                    break
            if notice is None:
                continue
            kind = f["kind"]
            if kind == "Notice" and notice["is_order"]:
                kind = "Order"
            issue = notice["issued_on"] or "—"
            due = notice["response_due"] or "—"
            responded_txt = ("Yes" if notice["responded"] else
                             "No" if f["kind"] != "Response" else "Yes")
            appeal_filed, appeal_none = self._eproc_classify_case(case)
            appeal_txt = ("Appeal" if appeal_filed else
                          "None" if appeal_none else "—")
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f["path"]))
            except OSError:
                mtime = datetime.datetime.min
            dl = None
            if case.get("downloaded_at"):
                try:
                    dl = datetime.datetime.strptime(
                        case["downloaded_at"], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dl = None
            rows.append({
                "client": case["client"],
                "pan": case["pan"],
                "proc": case["proc_display"],
                "file": f["name"],
                "kind": kind,
                "size": f["size"],
                "folder": case["year_dir"],
                "path": f["path"],
                "notice": notice,
                "issue": issue,
                "due": due,
                "responded_txt": responded_txt,
                "appeal_txt": appeal_txt,
                "_dt": dl or mtime,
                "_mtime": mtime,
                "_from_meta": bool(case.get("meta")),
            })
        rows.sort(key=lambda r: r["path"].lower())
        case["_file_rows"] = rows

    def _eproc_classify_case(self, case: dict):
        """Appeal classification for one case (spec):
        appeal_case  — proceeding display name or any notice description
                       matches r"appeal" (re.I);
        appeal_filed — appeal_case AND the case has any response file;
        appeal_none  — appeal_case AND no response files.
        Orders-without-appeal are NOT counted in the appeal chips. Returns
        (appeal_filed, appeal_none)."""
        name_hit = re.search(r"appeal", case["proc_display"] or "", re.I)
        desc_hit = any(re.search(r"appeal", n["description"] or "", re.I)
                       for n in case["notices"])
        appeal_case = bool(name_hit or desc_hit)
        has_resp = any(n["response_files"] for n in case["notices"])
        return (appeal_case and has_resp, appeal_case and not has_resp)

    def _eproc_update_chip_counts(self):
        """Recount notice-level hits for every chip and set the labels:
        'Open Notices (n)' etc. Counts are at NOTICE level (a notice with 3
        files counts once), per spec."""
        today = datetime.date.today()

        def due_within(n, days):
            d = self._eproc_parse_disp_date(n["response_due"])
            if d is None:
                return False
            delta = (d - today).days
            return 0 <= delta <= days

        counts = {"all": 0, "open": 0, "due7": 0, "due15": 0,
                  "orders": 0, "appeal": 0, "noappeal": 0}
        for case in self._eproc_cases:
            appeal_filed, appeal_none = self._eproc_classify_case(case)
            for n in case["notices"]:
                counts["all"] += 1
                if not n["responded"]:
                    counts["open"] += 1
                    if due_within(n, 7):
                        counts["due7"] += 1
                    if due_within(n, 15):
                        counts["due15"] += 1
                if n["is_order"] or "order" in (n["description"] or "").lower():
                    counts["orders"] += 1
            if appeal_filed:
                counts["appeal"] += sum(1 for _n in case["notices"])
            if appeal_none:
                counts["noappeal"] += sum(1 for _n in case["notices"])
        labels = {"all": "All", "open": "Open Notices", "due7": "Due ≤7d",
                  "due15": "Due ≤15d", "orders": "Orders",
                  "appeal": "Appeal Filed", "noappeal": "No Appeal"}
        for key, chip in self._eproc_chips.items():
            chip.setText(f"{labels[key]} ({counts[key]})")

    def _eproc_populate(self):
        """Build the grouped table: one spanned group header row per case
        (proceeding), then one file row per file. File rows carry their
        notice metadata (dates/responded/appeal classification); group rows
        toggle collapse on single click. Chip/search filtering is applied
        afterwards by _eproc_apply_filter."""
        t = _t()
        self._eproc_table.setRowCount(0)
        self._eproc_groups = []          # group header row index per case
        self._eproc_row_meta = {}        # row idx → row dict
        for case in self._eproc_cases:
            g_idx = self._eproc_table.rowCount()
            self._eproc_table.insertRow(g_idx)
            self._eproc_table.setSpan(g_idx, 0, 1, 11)
            collapsed = self._eproc_collapsed.get(case["proc_dir"], False)
            chevron = "▸" if collapsed else "▾"
            g_item = QTableWidgetItem(
                f"{chevron} {case['proc_display']} — {case['client']} "
                f"({self._eproc_ay_label(case)})")
            font = g_item.font()
            font.setBold(True)
            g_item.setFont(font)
            g_item.setForeground(QColor(t.text_primary))
            g_item.setData(Qt.ItemDataRole.UserRole + 1, "group")
            self._eproc_table.setItem(g_idx, 0, g_item)
            self._eproc_groups.append(g_idx)
            self._eproc_row_meta[g_idx] = {
                "type": "group", "case": case,
                "file_row_idxs": [], "children": []}
            for r in case.get("_file_rows", []):
                row_idx = self._eproc_table.rowCount()
                self._eproc_table.insertRow(row_idx)
                self._eproc_row_meta[row_idx] = {
                    "type": "file", "row": r, "case": case}
                self._eproc_row_meta[g_idx]["children"].append(row_idx)
                self._eproc_table.setItem(row_idx, 0, QTableWidgetItem(r["client"]))
                self._eproc_table.setItem(row_idx, 1, QTableWidgetItem(r["pan"]))
                self._eproc_table.setItem(row_idx, 2, QTableWidgetItem(r["proc"]))
                doc_item = QTableWidgetItem(r["file"])
                doc_item.setData(Qt.ItemDataRole.UserRole, r["path"])
                self._eproc_table.setItem(row_idx, 3, doc_item)
                # Kind colours: Notice=accent_it, Response=success, Order
                # (notice that is an order)=warning, none=text_muted.
                kind_item = QTableWidgetItem(r["kind"])
                kind_item.setForeground(QColor(
                    t.accent_it if r["kind"] == "Notice"
                    else t.success if r["kind"] == "Response"
                    else t.warning if r["kind"] == "Order"
                    else t.text_muted))
                self._eproc_table.setItem(row_idx, 4, kind_item)
                self._eproc_table.setItem(row_idx, 5, QTableWidgetItem(r["issue"]))
                due_item = QTableWidgetItem(r["due"])
                n = r["notice"]
                if r["due"] != "—":
                    due_date = self._eproc_parse_disp_date(r["due"])
                    overdue = (due_date is not None and due_date < datetime.date.today()
                               and not n["responded"])
                    soon = (due_date is not None and not n["responded"] and
                            0 <= (due_date - datetime.date.today()).days <= 7)
                    due_item.setForeground(QColor(
                        t.error if overdue else t.warning if soon else t.text_primary))
                self._eproc_table.setItem(row_idx, 6, due_item)
                resp_item = QTableWidgetItem(r["responded_txt"])
                resp_item.setForeground(QColor(
                    t.success if r["responded_txt"] == "Yes"
                    else t.warning if r["responded_txt"] == "No"
                    else t.text_muted))
                if r["responded_txt"] == "No":
                    rf = resp_item.font()
                    rf.setBold(True)
                    resp_item.setFont(rf)
                self._eproc_table.setItem(row_idx, 7, resp_item)
                ap_item = QTableWidgetItem(r["appeal_txt"])
                ap_item.setForeground(QColor(
                    t.accent_it if r["appeal_txt"] == "Appeal"
                    else t.text_muted if r["appeal_txt"] == "None"
                    else t.text_primary))
                self._eproc_table.setItem(row_idx, 8, ap_item)
                self._eproc_table.setItem(row_idx, 9, QTableWidgetItem(
                    self._eproc_human_size(r["size"])))
                folder_text = ("…" + r["folder"][-60:]) if len(r["folder"]) > 60 else r["folder"]
                folder_item = QTableWidgetItem(folder_text)
                folder_item.setToolTip(r["folder"])
                folder_item.setData(Qt.ItemDataRole.UserRole, r["folder"])
                self._eproc_table.setItem(row_idx, 10, folder_item)
        self._eproc_stack.setCurrentIndex(1 if self._eproc_cases else 0)

    @staticmethod
    def _eproc_ay_label(case) -> str:
        """AY_2025_26 → 'AY 2025-26' (TY_* → 'TY …') for group headers and
        vault lookups."""
        m = re.match(r"^(A[YZ]|TY)_(\d{4})_(\d{2})$", case["year_name"])
        if not m:
            return case["year_name"].replace("_", " ")
        return f"{m.group(1)} {m.group(2)[-2:]}-{m.group(3)}"

    def _eproc_apply_filter(self, *_):
        """Hide/show rows already loaded — never rescans. Composes the active
        chip predicate, the search text, and group collapse: file rows hide
        unless notice+search match AND their group is expanded; group header
        rows hide when ALL their file rows are hidden."""
        query = self._eproc_search.text().strip().lower()
        today = datetime.date.today()

        def notice_matches(n) -> bool:
            chip = self._eproc_chip
            if chip == "all":
                return True
            if chip == "open":
                return not n["responded"]
            if chip in ("due7", "due15"):
                if n["responded"]:
                    return False
                d = self._eproc_parse_disp_date(n["response_due"])
                if d is None:
                    return False
                delta = (d - today).days
                return 0 <= delta <= (7 if chip == "due7" else 15)
            if chip == "orders":
                return bool(n["is_order"]) or "order" in (n["description"] or "").lower()
            # appeal / noappeal chips are decided per case below.
            return True

        # Pre-compute per-case appeal flags once.
        case_flags = {}
        for case in self._eproc_cases:
            case_flags[id(case)] = self._eproc_classify_case(case)

        for row_idx in range(self._eproc_table.rowCount()):
            meta = self._eproc_row_meta.get(row_idx)
            if not meta:
                continue
            if meta["type"] == "group":
                continue   # groups decided after their children
            r = meta["row"]
            case = meta["case"]
            n = r["notice"]
            hay = " ".join((r["pan"], r["client"], r["proc"], r["file"],
                            r["kind"], r["folder"])).lower()
            visible = query in hay if query else True
            if visible:
                if self._eproc_chip in ("appeal", "noappeal"):
                    af, an = case_flags[id(case)]
                    visible = af if self._eproc_chip == "appeal" else an
                elif not notice_matches(n):
                    visible = False
            # Collapse: expanded group keeps children; collapsed hides all.
            collapsed = self._eproc_collapsed.get(case["proc_dir"], False)
            visible = visible and not collapsed
            self._eproc_table.setRowHidden(row_idx, not visible)
            meta["visible"] = visible
        # Group header visible only when at least one child row is visible;
        # a collapsed group with all-children-hidden is still shown so the
        # user can find and re-expand it.
        for g_idx in self._eproc_groups:
            meta = self._eproc_row_meta.get(g_idx)
            if not meta:
                continue
            kids = meta["children"]
            collapsed = self._eproc_collapsed.get(meta["case"]["proc_dir"], False)
            any_visible = any(not self._eproc_table.isRowHidden(k) for k in kids)
            hide = not (any_visible or (collapsed and bool(kids)))
            self._eproc_table.setRowHidden(g_idx, hide)

    def _eproc_on_group_click(self, row: int, _column: int):
        """Single click on a group header row toggles collapse (chevron
        ▸/▾) and re-applies the filter so hidden children follow."""
        meta = self._eproc_row_meta.get(row)
        if not meta or meta["type"] != "group":
            return
        case = meta["case"]
        collapsed = not self._eproc_collapsed.get(case["proc_dir"], False)
        self._eproc_collapsed[case["proc_dir"]] = collapsed
        item = self._eproc_table.item(row, 0)
        if item:
            txt = item.text()
            item.setText(("▸ " if collapsed else "▾ ") + txt[2:])
        self._eproc_apply_filter()

    def _eproc_on_double_click(self, row: int, column: int):
        """Double-click Folder cell → open the year folder; any other cell →
        open the document itself. Group rows open nothing."""
        meta = self._eproc_row_meta.get(row)
        if not meta or meta["type"] != "file":
            return
        if column == 10:
            folder = self._eproc_table.item(row, 10)
            if folder:
                self._eproc_open_path(folder.data(Qt.ItemDataRole.UserRole))
            return
        doc = self._eproc_table.item(row, 3)
        if doc:
            self._eproc_open_path(doc.data(Qt.ItemDataRole.UserRole))

    def _eproc_open_selected(self):
        row = self._eproc_table.currentRow()
        if row < 0:
            return
        doc = self._eproc_table.item(row, 3)
        if doc and self._eproc_row_meta.get(row, {}).get("type") == "file":
            self._eproc_open_path(doc.data(Qt.ItemDataRole.UserRole))

    def _eproc_open_path(self, path):
        from config import _open_path
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Not Found",
                f"This file or folder no longer exists:\n{path or '(unknown)'}\n\n"
                "It may have been moved or deleted — try Refresh.")
            return
        _open_path(path)

    def _mk_income_tax_page(self):
        """F-77b: Income Tax hub — mockup's tab-row navigation (Actions /
        Download Documents / E-Pay Tax / Return Status / Tools /
        e-Proceedings) over a QStackedWidget. The Actions tab is the
        action-card landing screen; clicking a card switches tabs (mirrors
        the mockup's onclick="activeTabIdx=N; render()") instead of opening
        a dialog directly. Download Documents/E-Pay Tax/Return Status tabs
        still open their existing modal dialogs — full inline embedding is a
        later phase (F-77c). Tools is fully inline since it's just two
        one-shot conversions, no client/year selection needed; e-Proceedings
        (F-60) is inline too — one flat table of every downloaded notice /
        response across ALL clients and ALL year folders."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        tab_row = QWidget()
        tab_row.setFixedHeight(46)
        tr = QHBoxLayout(tab_row)
        tr.setContentsMargins(24, 8, 24, 8)
        tr.setSpacing(4)
        labels = ["Actions", "Download Documents", "E-Pay Tax", "Return Status", "Tools", "e-Proceedings"]
        self._it_tab_btns = [self._mk_it_tab_btn(l, i) for i, l in enumerate(labels)]
        for b in self._it_tab_btns:
            tr.addWidget(b)
        tr.addStretch(1)
        outer.addWidget(tab_row)

        self._it_stack = QStackedWidget()
        outer.addWidget(self._it_stack, 1)

        # ── Tab 0: Actions (card grid) ──────────────────────────────────────
        actions_page = QWidget()
        av = QVBoxLayout(actions_page)
        av.setContentsMargins(24, 20, 24, 20)
        av.setSpacing(14)
        av.addWidget(_lbl("What do you want to do?", 11, bold=True, color=_t().text_muted))
        # 5 cards now → QGridLayout 2x3 (with 3 stretches so rows share width
        # evenly) instead of the old 4-card QHBoxLayout.
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.addWidget(self._mk_action_card(
            "Download Documents",
            "26AS, Form 168, AIS, TIS & Filed Returns — bulk, unattended, for every selected client.",
            "document", lambda: self._switch_it_tab(1)), 0, 0)
        grid.addWidget(self._mk_action_card(
            "E-Pay Tax",
            "Generate tax payment challans against the ITD portal, or import a prepared batch.",
            "rupee", lambda: self._switch_it_tab(2)), 0, 1)
        grid.addWidget(self._mk_action_card(
            "Check Processing Status",
            "See where every client's return actually stands, straight from the portal.",
            "list", lambda: self._switch_it_tab(3)), 0, 2)
        grid.addWidget(self._mk_action_card(
            "Tools",
            "Convert an already-downloaded 26AS or AIS file to Excel, outside a full batch run.",
            "gear", lambda: self._switch_it_tab(4)), 1, 0)
        grid.addWidget(self._mk_action_card(
            "e-Proceedings",
            "All notices and responses downloaded for every client, in one place.",
            "list", lambda: self._switch_it_tab(5)), 1, 1)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        av.addLayout(grid)
        av.addStretch(1)
        self._it_stack.addWidget(actions_page)

        # ── Tab 1: Download Documents — inline 3-section form ────────────────
        self._it_stack.addWidget(self._mk_it_download_tab())

        # ── Tabs 2-3: still open their existing modal dialogs ────────────────
        self._it_stack.addWidget(self._mk_it_dialog_tab(
            "E-Pay Tax",
            "Generate tax payment challans against the ITD portal, or import a prepared batch. "
            "Already saved a challan? Open it without fetching it again.",
            "Generate Tax Challans…", "", self._open_generate_challans_dialog,
            extra_actions=[
                ("View Challans…", "document", self._open_view_challans_dialog),
            ]))
        self._it_stack.addWidget(self._mk_it_return_status_tab())

        # ── Tab 4: Tools (fully inline) ──────────────────────────────────────
        self._it_stack.addWidget(self._mk_it_tools_tab())

        # ── Tab 5: e-Proceedings (F-60) — all clients, all years, one table ──
        self._it_stack.addWidget(self._mk_it_eproceedings_tab())

        self._switch_it_tab(0)
        return page

    def _mk_litigation_page(self):
        """F-26: Litigation hub - unified e-proceedings across modules."""
        try:
            self._litigation_page = LitigationPage(
                self.vault,
                lambda: getattr(self, "assessee_list", []) or [],
                self,
            )
            self._litigation_page.dataChanged.connect(self._on_litigation_changed)
            self._litigation_page.openCaseRequested.connect(self._open_litigation_case)
            return self._litigation_page
        except Exception as exc:
            self._litigation_page = None
            self.log(f"[Error] Litigation hub failed to build: {exc}")
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(24, 24, 24, 24)
            lay.addStretch(1)
            lay.addWidget(_lbl("Litigation view could not load.", 14, bold=True))
            lay.addWidget(_lbl(str(exc), 11, color=_t().text_muted))
            lay.addStretch(1)
            return page

    def _on_litigation_changed(self):
        ws = getattr(self, "_eproc_ws", None)
        if ws is not None:
            try:
                ws.refresh()
            except Exception as exc:
                self.log(f"[Error] e-Proceedings refresh failed: {exc}")

    def _open_litigation_case(self, module, native_id):
        if module == "it":
            self._nav_shell.go("it")
            try:
                self._switch_it_tab(5)
            except Exception:
                pass
            ws = getattr(self, "_eproc_ws", None)
            if ws is not None:
                try:
                    ws.refresh()
                    ws.goto_case(native_id)
                except Exception as exc:
                    self.log(f"[Error] Opening case {native_id}: {exc}")

    def _mk_mail_docs_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        b = _btn("Mail Docs to Clients…", "secondary", height=34, icon="btn_send.png")
        b.clicked.connect(self._open_mail_docs)
        layout.addWidget(b)
        layout.addStretch(1)
        return page

    def _open_activity_log(self):
        """Activity Log hub's primary entry point — the email send log.
        Per-client download-run history stays reachable the existing way
        (right-click a client row → View Log → _show_log_history)."""
        from automation.emailer import _email_log_path
        path = _email_log_path()
        if not os.path.exists(path):
            QMessageBox.information(self, "No Log Yet",
                "No email activity has been logged yet.\n"
                "Send documents to a client first, then check the log.")
            return
        EmailLogDialog(self, path).exec()

    def _mk_activity_log_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 0)
        layout.setSpacing(10)
        b = _btn("View Email Log…", "secondary", height=34, icon="btn_view_log.png")
        b.clicked.connect(self._open_activity_log)
        layout.addWidget(b)
        layout.addWidget(_lbl(
            "Per-client download history is available by right-clicking a client row on the Home hub.",
            11, color=_t().text_muted))
        layout.addSpacing(6)
        # F-77a: Live Logs now lives here instead of as a permanent bottom
        # strip on every hub — self.log_box keeps receiving updates from
        # background batch runs regardless of which hub is on screen.
        layout.addWidget(self._mk_footer(), 1)
        return page

    def _mk_placeholder_page(self, title: str, body: str):
        """Static empty-state page for hubs with no real feature yet
        (GST/TDS/MCA, Team) — validates rail/ribbon accent-color theming
        end-to-end without pretending the feature exists."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 40, 24, 20)
        layout.setSpacing(8)
        layout.addWidget(_lbl(title, 14, bold=True))
        lbl_body = QLabel(body)
        lbl_body.setWordWrap(True)
        lbl_body.setStyleSheet(f"color:{_t().text_muted}; font-size:12px; background:transparent;")
        layout.addWidget(lbl_body)
        layout.addStretch(1)
        return page

    def _mk_tds_page(self):
        """TDS hub — deductor-side (TAN) actions. F-4 adds TDS/TCS challan
        generation; the rest of the TDS roadmap remains a placeholder."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(_lbl("TDS / TCS — Deductor (TAN)", 11, bold=True, color=_t().text_muted))
        layout.addWidget(self._mk_action_card(
            "TDS / TCS Challan",
            "Generate Challan 281 under Income-tax Act, 2025 for a deductor TAN, "
            "with section-wise tax, surcharge and cess.",
            "rupee", self._open_generate_tds_challans_dialog))
        layout.addWidget(self._mk_action_card(
            "Download TDS / TCS Challans",
            "Download already-paid challans from e-Pay Tax Payment History "
            "for the selected TAN clients and years.",
            "document", self._open_download_tds_challans_dialog))
        layout.addWidget(self._mk_action_card(
            "View Challans",
            "Browse challans already generated or downloaded in an earlier "
            "session — filter by client and Paid / Unpaid, then open the "
            "file or its folder.",
            "list", self._open_view_challans_dialog))
        layout.addStretch(1)
        return page

    _LOG_HEADER_HEIGHT = 32

    def _mk_footer(self):
        """Live Logs — embedded in the Activity Log hub page, styled to
        match iBench's Activity Log view (WindowsProject/iBench App.tsx):
        a deliberately dark panel in both themes, with per-line severity
        colouring instead of icons, no wrap (horizontal scroll), and
        always-on auto-scroll.

        B-101: all colours come from the theme-invariant ``log_*`` tokens,
        so this file has no unexplained raw hex literals."""
        t = _t()
        footer = QFrame()
        footer.setStyleSheet(f"QFrame{{background:{t.log_panel};}}")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        self._log_footer = footer

        log_hdr = QFrame()
        log_hdr.setFixedHeight(self._LOG_HEADER_HEIGHT)
        log_hdr.setStyleSheet(
            f"QFrame{{background:{t.log_header};"
            f"border-bottom:1px solid {t.log_header_border};}}")
        hhl = QHBoxLayout(log_hdr); hhl.setContentsMargins(16, 0, 12, 0)
        hhl.addWidget(_lbl("Activity Log", 11, bold=True, color=t.log_header_text))
        hhl.addStretch()
        self._log_count_lbl = QLabel("0 lines")
        self._log_count_lbl.setStyleSheet(
            f"color:{t.log_muted};font-size:10px;background:transparent;")
        hhl.addWidget(self._log_count_lbl)
        hhl.addSpacing(12)

        def _hdr_btn(text):
            b = QPushButton(text)
            b.setFixedHeight(22)
            b.setStyleSheet(
                f"QPushButton{{background:{t.log_button_bg};color:{t.log_button_fg};"
                "border:none;border-radius:4px;padding:0 10px;font-size:10px;}"
                f"QPushButton:hover{{background:{t.log_button_hover_bg};"
                f"color:{t.log_button_hover_fg};}}"
                f"QPushButton:focus{{border:2px solid {t.border_focus};}}")
            return b

        open_folder_btn = _hdr_btn("Open Logs Folder")
        open_folder_btn.clicked.connect(self._open_logs_folder)
        hhl.addWidget(open_folder_btn)
        copy_btn = _hdr_btn("Copy")
        copy_btn.setStyleSheet(copy_btn.styleSheet() + "QPushButton{margin-left:6px;}")
        copy_btn.clicked.connect(self.copy_logs_to_clipboard)
        hhl.addWidget(copy_btn)
        fl.addWidget(log_hdr)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_box.setStyleSheet(
            f"QTextEdit{{background:{t.log_panel};border:none;"
            f"font-family:'{_MONO_FONT}',monospace;"
            "font-size:12px;padding:8px 16px;}")
        fl.addWidget(self.log_box)
        self._log_line_count = 0

        return footer

    def _open_logs_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(_app_dir()))

    # ── Grid ──────────────────────────────────────────────────────────────────

    def _apply_row_style(self, row_idx, selected, index=0):
        t  = get_theme(getattr(self, "_current_theme", "light"))
        bg = t.bg_table if index % 2 == 0 else t.bg_table_alt
        fg = t.row_selected_fg if selected else t.text_primary
        
        # Apply style to all items in the row
        for col in range(self.client_table.columnCount()):
            item = self.client_table.item(row_idx, col)
            if item:
                item.setBackground(QColor(bg))
                item.setForeground(QColor(fg))
                # Set font
                font = item.font()
                # PAN is bold by default, or bold if selected
                font.setBold(col == self._TC_PAN or selected)
                item.setFont(font)
        
        cb_container = self.client_table.cellWidget(row_idx, self._TC_CHK)
        if cb_container:
            cb_container.setStyleSheet(f"background:{bg}; border:none;")
            cb = cb_container.findChild(QCheckBox)
            if cb:
                cb.setStyleSheet("background:transparent;")

        # _TC_ACTS is a plain QTableWidgetItem — styled via item background/foreground above

    def _apply_filter(self, text=""):
        if not hasattr(self, "client_table"):
            return
        q = text.strip().lower()
        sf_idx = self.status_filter.currentIndex() if hasattr(self, "status_filter") else 0
        # Map dropdown index → status prefix(es) to match
        _sf_map = {
            0: None,              # All statuses
            1: ("✅",),           # Downloaded
            2: ("⚠",),           # Partially Completed
            3: ("❌",),           # Failed
            4: ("🕐", "⏹"),      # Queued / Pending
            5: ("—",),            # Not run yet
        }
        status_prefixes = _sf_map.get(sf_idx)
        # F-11: "All Groups" is always index 0 — anything else is an exact
        # group name to match against the Group column's cell text.
        group_wanted = (self.group_filter.currentText()
                        if hasattr(self, "group_filter") and self.group_filter.currentIndex() > 0
                        else None)
        _src_wanted = (self.source_filter.currentIndex()
                       if hasattr(self, "source_filter") else 0)
        for row_idx in range(self.client_table.rowCount()):
            name_item   = self.client_table.item(row_idx, self._TC_NAME)
            pan_item    = self.client_table.item(row_idx, self._TC_PAN)
            status_item = self.client_table.item(row_idx, self._TC_STATUS)
            group_item  = self.client_table.item(row_idx, self._TC_GROUP)
            if not name_item or not pan_item:
                continue
            st_text = status_item.text().lower() if status_item else ""
            text_match = (not q
                          or q in name_item.text().lower()
                          or q in pan_item.text().lower()
                          or q in st_text)
            if status_prefixes is None:
                status_match = True
            else:
                st = (status_item.text() if status_item else "—")
                status_match = any(st.startswith(p) for p in status_prefixes)
            group_match = (group_wanted is None
                           or (group_item is not None and group_item.text() == group_wanted))
            src_item = self.client_table.item(row_idx, self._TC_SRCS)
            srcs = (src_item.data(Qt.ItemDataRole.UserRole + 2)
                    if src_item is not None else None) or []
            if _src_wanted == 1:
                src_match = "GST" in srcs
            elif _src_wanted == 2:
                src_match = "TDS" in srcs
            elif _src_wanted == 3:
                src_match = "Income Tax" in srcs
            elif _src_wanted == 4:
                src_match = not srcs
            else:
                src_match = True
            hidden = not (text_match and status_match and group_match and src_match)
            self.client_table.setRowHidden(row_idx, hidden)
            if not hidden:
                a_id = name_item.data(Qt.ItemDataRole.UserRole)
                if a_id:
                    is_selected = a_id in self.selected_ids
                    cb_container = self.client_table.cellWidget(row_idx, self._TC_CHK)
                    if cb_container:
                        cb = cb_container.findChild(QCheckBox)
                        if cb and cb.isChecked() != is_selected:
                            cb.blockSignals(True)
                            cb.setChecked(is_selected)
                            cb.blockSignals(False)
                    self._apply_row_style(row_idx, is_selected, row_idx)
        self._update_count()

    def _refresh_group_filter(self):
        """Keeps the Group filter dropdown in sync with what clients are
        actually tagged with — same reasoning as refresh_ay_combo() for
        the Assessment Year list. Preserves the current selection when
        that group still exists, otherwise falls back to "All Groups"."""
        if not hasattr(self, "group_filter"):
            return
        current = self.group_filter.currentText()
        groups = self.vault.get_all_groups()
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem("All Groups")
        self.group_filter.addItems(groups)
        idx = self.group_filter.findText(current)
        self.group_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.group_filter.blockSignals(False)

    def refresh_grid(self):
        self._checkbox_map.clear()
        self._id_to_row.clear()
        self.assessee_list = self.vault.get_all_assessees()
        self._refresh_group_filter()
        self._dl_refresh_clients()

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
            
        # Load download history for the first checked AY — summarized across
        # doc types (a batch can now cover several per client/AY), worst
        # status wins for the glyph shown, full breakdown goes in the tooltip.
        # (F-14: the combo can have multiple years checked; the grid preview
        # only shows one at a time, so it uses whichever is checked first.)
        _checked_ays = self.ay_combo.checked_labels() if hasattr(self, "ay_combo") else []
        current_ay = _checked_ays[0] if _checked_ays else ""
        dl_history = {}
        if current_ay and current_ay != "Select AY/TY":
            try:
                dl_history = self.vault.get_download_history_summary(current_ay)
            except Exception:
                pass

        for i, a in enumerate(self.assessee_list):
            a_id = a.get("id")
            pan  = a.get("pan", "")
            is_selected = a_id in self.selected_ids

            self.client_table.insertRow(i)

            # Col 0: Checkbox
            _ct = _t()
            _chk_path = self.checkmark_path.replace("\\", "/")
            cb_container = QWidget()
            cb_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            cb_container.setStyleSheet(f"QWidget{{background:{_ct.bg_table};}}")
            cb_layout = QHBoxLayout(cb_container)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb = QCheckBox()
            cb.setStyleSheet(
                f"QCheckBox{{background:transparent;}}"
                f"QCheckBox::indicator{{width:15px;height:15px;border:1.5px solid {_ct.border};"
                f"border-radius:3px;background:{_ct.bg_checkbox};}}"
                f"QCheckBox::indicator:hover{{border-color:{_ct.border_focus};}}"
                f"QCheckBox::indicator:checked{{background:{_ct.accent};border-color:{_ct.accent};"
                f"image:url('{_chk_path}');}}"
            )
            cb.setChecked(is_selected)
            cb.setAccessibleName(f"Select {a.get('name', pan)}")
            cb.toggled.connect(lambda checked, id_=a_id: self._on_check(id_, checked))
            self._checkbox_map[a_id] = cb
            self._id_to_row[a_id] = i
            cb_layout.addWidget(cb)
            self.client_table.setCellWidget(i, self._TC_CHK, cb_container)

            # Col 1: Name
            name_item = QTableWidgetItem(a.get("name", ""))
            name_item.setData(Qt.ItemDataRole.UserRole, a_id)
            name_item.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"Client {a.get('name', '')}, PAN {pan}")
            name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.client_table.setItem(i, self._TC_NAME, name_item)

            # Col 2: Group (F-11) — blank, not a "—" placeholder, when
            # ungrouped, consistent with how other optional fields render.
            group_item = QTableWidgetItem(a.get("group", ""))
            group_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.client_table.setItem(i, self._TC_GROUP, group_item)

            # Col 3: PAN (monospace)
            pan_item = QTableWidgetItem(pan)
            pan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            f = pan_item.font(); f.setFamily(_MONO_FONT); pan_item.setFont(f)
            self.client_table.setItem(i, self._TC_PAN, pan_item)

            # Col 3: Date of Birth
            dob_item = QTableWidgetItem(a.get("dob", ""))
            dob_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.client_table.setItem(i, self._TC_DOB, dob_item)

            # Col: Credential sources — Income Tax / TDS / GST tags
            sources = self.vault.credential_sources(a)
            src_item = QTableWidgetItem(" · ".join(sources))
            src_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            src_item.setData(Qt.ItemDataRole.UserRole + 2, sources)
            if sources:
                src_item.setForeground(QColor(_t().accent_hover))
                src_item.setToolTip("Credentials saved for: " + ", ".join(sources))
            else:
                src_item.setForeground(QColor(_t().text_muted))
                src_item.setToolTip("No portal credentials saved for this client yet.")
            src_item.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"Credentials for {a.get('name', pan)}: "
                + (", ".join(sources) if sources else "none"))
            self.client_table.setItem(i, self._TC_SRCS, src_item)

            # Col 4: Last Download Status (from history) — one glyph summarizing
            # the worst outcome across doc types, tooltip breaks down each one.
            hist = dl_history.get(pan, {})
            status_text = hist.get("status", "—")
            breakdown = hist.get("breakdown", [])
            credential_invalid = bool(a.get("credential_invalid"))
            if credential_invalid:
                status_text = "⚠ Password needs update — auto-fetch paused"
                breakdown = []
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if len(breakdown) > 1:
                _doc_labels = {"26as": "26AS/Form 168", "request_ais": "AIS Request",
                               "ais_tis": "AIS/TIS", "filed_returns": "Filed Returns",
                               "challans": "Tax Challans", "legacy": "Download",
                               "e_proceedings": "e-Proceedings",
                               "filed_forms": "Filed IT Forms"}
                tooltip_text = "\n".join(
                    f"{_doc_labels.get(dt, dt)}: {st}" for dt, st in breakdown
                )
            else:
                tooltip_text = status_text
            if credential_invalid:
                tooltip_text = ("The portal rejected this client's saved password. "
                                "Update it in Client Master to resume automatic sync.")
            status_item.setToolTip(tooltip_text)
            # F-17: never make colour the only signal — screen readers get the
            # status text and the per-document breakdown too.
            status_item.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"Status for {a.get('name', pan)}: {status_text}. {tooltip_text}")
            if status_text.startswith("✅"):
                status_item.setForeground(QColor(_t().success))
            elif status_text.startswith("❌"):
                status_item.setForeground(QColor(_t().error))
            elif status_text.startswith("⚠"):
                status_item.setForeground(QColor(_t().warning))
            else:
                status_item.setForeground(QColor(_t().text_muted))
            self.client_table.setItem(i, self._TC_STATUS, status_item)

            # Col 5: Last Download Time
            ts_text = hist.get("ts", "")
            ts_item = QTableWidgetItem(ts_text if ts_text else "—")
            ts_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ts_item.setForeground(QColor(_t().text_muted))
            self.client_table.setItem(i, self._TC_TS, ts_item)

            # Col 6: Last Saved Location (hyperlink QLabel)
            saved_path = hist.get("path", "")
            path_lbl = QLabel()
            path_lbl.setContentsMargins(6, 0, 6, 0)
            path_lbl.setStyleSheet("background:transparent; border:none; font-size:11px;")
            if saved_path and os.path.exists(saved_path):
                path_lbl.setText(
                    f'<a href="{saved_path}" style="color:{_t().accent_hover};text-decoration:underline;">'
                    f'{saved_path}</a>'
                )
                path_lbl.setToolTip(saved_path)
                path_lbl.linkActivated.connect(
                    lambda p=saved_path: self._open_saved_path(p))
            else:
                path_lbl.setText(f'<span style="color:{_t().text_muted};">—</span>')
            self.client_table.setCellWidget(i, self._TC_PATH, path_lbl)

            # Col 6: Actions
            dots_item = QTableWidgetItem("• • •")
            dots_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dots_item.setToolTip("Click for actions")
            dots_item.setForeground(QColor(_t().text_muted))
            f = dots_item.font()
            f.setPointSize(9)
            f.setBold(True)
            dots_item.setFont(f)
            dots_item.setData(Qt.ItemDataRole.UserRole + 1, a)
            self.client_table.setItem(i, self._TC_ACTS, dots_item)

            self._apply_row_style(i, is_selected, i)

        # Re-apply active sort if any
        if self._current_sort_col in (self._TC_NAME, self._TC_GROUP, self._TC_PAN):
            self.client_table.setSortingEnabled(True)
            self.client_table.sortByColumn(self._current_sort_col, self._current_sort_order)
            self.client_table.setSortingEnabled(False)

            for row_idx in range(self.client_table.rowCount()):
                item = self.client_table.item(row_idx, self._TC_NAME)
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
                item = self.client_table.item(row_idx, self._TC_NAME)
                if item and item.data(Qt.ItemDataRole.UserRole) == id_:
                    self._apply_row_style(row_idx, checked, row_idx)
                    break
                    
        self._update_count()

    def toggle_select_all(self, checked):
        for a_id, cb in self._checkbox_map.items():
            row_idx = self._id_to_row.get(a_id)
            if row_idx is None or self.client_table.isRowHidden(row_idx):
                continue
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
            if checked:
                self.selected_ids.add(a_id)
            else:
                self.selected_ids.discard(a_id)
            self._apply_row_style(row_idx, checked, row_idx)
        self._update_count()

    def _update_count(self):
        visible_ids = {
            a_id for a_id, row in self._id_to_row.items()
            if not self.client_table.isRowHidden(row)
        } if hasattr(self, "client_table") else set(self._checkbox_map)
        n = len(self.selected_ids & visible_ids)
        total = len(visible_ids)
        self.lbl_selected.setText(f"{n} selected" if n else "")
        if hasattr(self, "header_cb"):
            self.header_cb.blockSignals(True)
            self.header_cb.setChecked(total > 0 and n == total)
            self.header_cb.blockSignals(False)


    # ── Form Operations ───────────────────────────────────────────────────────

    _ADD_NEW_GROUP = "➕ Add New Group…"

    def _make_group_combo(self, current: str = ""):
        """F-11 group picker, shared by the Add/Edit Client dialog and
        "Assign to Group…". Deliberately NOT editable — confirmed live,
        twice: first that an editable combo's "just type a new name" path
        wasn't discoverable at all (the user asked "how will I create
        group"), and second, after adding an explicit "Add New Group…"
        item, that free typing should be blocked outright rather than left
        as a second, inconsistent way to add a group (a typo becomes its
        own group with no warning). The dropdown list is now the only way
        to pick or add a value."""
        combo = StyledComboBox()
        combo.setEditable(False)
        combo.setFixedHeight(34)
        combo.addItem("")  # blank = ungrouped, always selectable
        combo.addItems(self.vault.get_all_groups())
        combo.addItem(self._ADD_NEW_GROUP)
        if current:
            # A client's existing group might not be in get_all_groups() at
            # all yet (e.g. this is the very first client in it, so no
            # OTHER client's row would surface it) — add it so the current
            # value is always selectable, not silently dropped.
            if combo.findText(current) < 0:
                combo.insertItem(combo.count() - 1, current)
            combo.setCurrentIndex(combo.findText(current))

        def _on_index_changed(idx):
            if combo.itemText(idx) != self._ADD_NEW_GROUP:
                return
            from PyQt6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "Add New Group", "Group name:")
            name = name.strip() if ok else ""
            if name:
                if combo.findText(name) < 0:
                    combo.insertItem(combo.count() - 1, name)  # before the sentinel
                combo.setCurrentIndex(combo.findText(name))
            else:
                combo.setCurrentIndex(0)  # back to blank/ungrouped, not stuck on the sentinel

        combo.currentIndexChanged.connect(_on_index_changed)
        return combo

    # ── Client Dialog (Add / Edit popup) ─────────────────────────────────────

    def _open_add_client(self):
        self._client_dialog(None)

    def _open_edit_client(self, a):
        self._client_dialog(a)

    def _pick_and_edit_client(self):
        """Client Master → Edit Client… — picker popup then edit dialog."""
        clients = [{"id": a["id"], "name": a["name"], "pan": a["pan"]}
                   for a in self.vault.get_all_assessees()]
        if not clients:
            QMessageBox.information(self, "No Clients", "No clients in vault.")
            return
        dlg = _ClientPickerDialog(self, clients, mode="edit")
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_ids:
            a_id = dlg.selected_ids[0]
            for row in range(self.client_table.rowCount()):
                item = self.client_table.item(row, self._TC_NAME)
                if item and item.data(Qt.ItemDataRole.UserRole) == a_id:
                    acts_item = self.client_table.item(row, self._TC_ACTS)
                    if acts_item:
                        a = acts_item.data(Qt.ItemDataRole.UserRole + 1)
                        if a:
                            self._open_edit_client(a)
                    break

    def _pick_and_delete_clients(self):
        """Client Master → Delete Client(s)… — picker popup then confirmed delete."""
        all_clients = self.vault.get_all_assessees()
        clients = [{"id": a["id"], "name": a["name"], "pan": a["pan"]}
                   for a in all_clients]
        if not clients:
            QMessageBox.information(self, "No Clients", "No clients in vault.")
            return
        dlg = _ClientPickerDialog(self, clients, mode="delete")
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_ids:
            ids   = set(dlg.selected_ids)
            names = [a["name"] for a in all_clients if a["id"] in ids]
            msg   = f"Permanently delete {len(ids)} client(s)?\n\n" + "\n".join(f"\u2022 {n}" for n in names)
            if QMessageBox.question(
                    self, "Confirm Delete", msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
               ) == QMessageBox.StandardButton.Yes:
                for a_id in ids:
                    self.vault.delete_assessee(a_id)
                    self.selected_ids.discard(a_id)
                    self._checkbox_map.pop(a_id, None)
                self.refresh_grid()
                self._update_count()
                self.log(f"[Vault] {len(ids)} client(s) deleted.")


    def _client_dialog(self, a=None):
        editing = a is not None
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Client" if editing else "Add New Client")
        t = _t()
        dlg.setStyleSheet(
            f"QDialog{{background:{t.bg_window};}}"
            f"QLabel{{background:transparent;border:none;color:{t.text_primary};font-size:12px;}}"
            f"QLineEdit{{border:1px solid {t.border};border-radius:6px;padding:6px 10px;"
            f"font-size:12px;background:{t.bg_input};color:{t.text_primary};}}"
            f"QLineEdit:focus{{border-color:{t.border_focus};background:{t.bg_input_focus};}}"
            f"QFrame#clientSep{{background:{t.border};border:none;}}"
        )

        # Two columns side by side so the dialog stays short and wide instead of
        # becoming a long single strip that overflows a laptop screen.
        root = QVBoxLayout(dlg)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(0)

        title_lbl = QLabel("Edit Client" if editing else "Add New Client")
        title_lbl.setStyleSheet(f"font-size:14px;font-weight:700;color:{t.text_primary};")
        root.addWidget(title_lbl)
        root.addSpacing(16)

        cols = QHBoxLayout()
        cols.setSpacing(28)
        cols.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        right = QVBoxLayout()
        for col in (left, right):
            col.setSpacing(0)
            col.setContentsMargins(0, 0, 0, 0)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        root.addLayout(cols)

        fields = {}

        def _field_label(text):
            l = QLabel(text)
            l.setStyleSheet(f"font-size:11px;font-weight:600;color:{t.text_muted};margin-bottom:3px;")
            return l

        def _line_edit(ph):
            e = QLineEdit()
            e.setPlaceholderText(ph)
            e.setFixedHeight(34)
            e.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
            return e

        def _section_head(text):
            lbl = QLabel(text.upper())
            lbl.setStyleSheet(
                f"font-size:10px;font-weight:700;color:{t.text_muted};"
                f"letter-spacing:0.6px;background:transparent;border:none;")
            return lbl

        # ── LEFT COLUMN — identity ────────────────────────────────────────────
        left.addWidget(_section_head("Client"))
        left.addSpacing(8)

        left.addWidget(_field_label("Full Name"))
        fields["name"] = _line_edit("e.g. Deepak Bholusaria")
        left.addWidget(fields["name"])
        left.addSpacing(10)

        left.addWidget(_field_label("Group (optional — e.g. a family or firm name)"))
        fields["group"] = self._make_group_combo(a.get("group", "") if editing else "")
        left.addWidget(fields["group"])
        left.addSpacing(10)

        left.addWidget(_field_label("PAN / TAN"))
        fields["pan"] = _line_edit("PAN AABCP1234F  ·  TAN ABCD12345E")
        fields["pan"].setMaxLength(10)
        fields["pan"].setValidator(
            QRegularExpressionValidator(QRegularExpression("[A-Za-z0-9]{0,10}")))
        fields["pan"].textChanged.connect(
            lambda txt, e=fields["pan"]: e.setText(txt.upper()) if txt != txt.upper() else None)
        left.addWidget(fields["pan"])
        left.addSpacing(10)

        # ── Date of Birth — text input + calendar picker + live hint ─────────
        left.addWidget(_field_label("Date of Birth (required for PAN, optional for TAN)"))
        dob_row = QHBoxLayout()
        dob_row.setSpacing(6)
        dob_row.setContentsMargins(0, 0, 0, 0)

        dob_edit = QLineEdit()
        dob_edit.setPlaceholderText("DD-MM-YYYY  or type digits freely")
        dob_edit.setFixedHeight(34)
        dob_edit.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        fields["dob"] = dob_edit

        cal_btn = QPushButton("📅")
        cal_btn.setFixedSize(34, 34)
        cal_btn.setToolTip("Pick date from calendar")
        cal_btn.setStyleSheet(
            f"QPushButton{{background:{t.bg_input};border:1px solid {t.border};"
            f"border-radius:6px;font-size:14px;}}"
            f"QPushButton:hover{{border-color:{t.border_focus};}}")

        dob_row.addWidget(dob_edit, 1)
        dob_row.addWidget(cal_btn)
        left.addLayout(dob_row)

        dob_hint = QLabel("")
        dob_hint.setStyleSheet("font-size:10px;background:transparent;border:none;")
        dob_hint.setFixedHeight(16)
        left.addWidget(dob_hint)
        left.addStretch(1)

        # ── RIGHT COLUMN — contact then each credential set ──────────────────
        right.addWidget(_section_head("Contact"))
        right.addSpacing(8)

        right.addWidget(_field_label("Email Address (optional)"))
        fields["email"] = _line_edit("client@example.com")
        right.addWidget(fields["email"])
        right.addSpacing(10)

        right.addWidget(_field_label("CC (optional — separate multiple with  ;)"))
        fields["cc"] = _line_edit("spouse@example.com;accountant@firm.com")
        right.addWidget(fields["cc"])
        right.addSpacing(16)

        # Each portal is opt-in. The tick box decides whether this client is
        # part of that portal's flows at all, and reveals its credential
        # boxes only when ticked — so a GST-only client never appears in the
        # income-tax lists, and a TDS client only in the TDS flows.
        def _enable_row(text):
            cb = QCheckBox(text)
            cb.setStyleSheet(
                f"QCheckBox{{color:{t.text_primary};font-size:12px;"
                f"font-weight:600;background:transparent;}}")
            return cb

        def _pw_cb(label):
            cb = QCheckBox(label)
            cb.setStyleSheet(
                f"color:{t.text_muted};font-size:11px;background:transparent;")
            return cb

        def _inset_box():
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(20, 0, 0, 0)
            lay.setSpacing(0)
            return box, lay

        hosts = {}

        # ── Income Tax (PAN) ─────────────────────────────────────────────────
        enable_it = _enable_row("Enable Income Tax (26AS · AIS/TIS · returns)")
        right.addWidget(enable_it)
        right.addSpacing(8)
        it_box, it_lay = _inset_box()
        it_lay.addWidget(_field_label("Portal Password"))
        fields["pwd"] = _line_edit("Enter password")
        fields["pwd"].setEchoMode(QLineEdit.EchoMode.Password)
        it_lay.addWidget(fields["pwd"])
        show_cb = _pw_cb("Show password")
        it_lay.addWidget(show_cb)
        right.addWidget(it_box)
        right.addSpacing(12)

        # ── TDS / TRACES ─────────────────────────────────────────────────────
        enable_tds = _enable_row("Enable TDS (TDS / TRACES login)")
        right.addWidget(enable_tds)
        right.addSpacing(8)
        tds_box, tds_lay = _inset_box()
        tds_lay.addWidget(_field_label("TDS / TRACES Username"))
        fields["tds_user"] = _line_edit("TDS / TRACES user id")
        tds_lay.addWidget(fields["tds_user"])
        tds_lay.addSpacing(8)
        tds_lay.addWidget(_field_label("TDS / TRACES Password"))
        fields["tds_pwd"] = _line_edit("TDS password")
        fields["tds_pwd"].setEchoMode(QLineEdit.EchoMode.Password)
        tds_lay.addWidget(fields["tds_pwd"])
        tds_show = _pw_cb("Show TDS password")
        tds_lay.addWidget(tds_show)
        hosts["tds_show"] = tds_show
        right.addWidget(tds_box)
        right.addSpacing(12)

        # ── GST ──────────────────────────────────────────────────────────────
        enable_gst = _enable_row("Enable GST")
        right.addWidget(enable_gst)
        right.addSpacing(8)
        gst_box, gst_lay = _inset_box()
        gst_lay.addWidget(_field_label("GST Username"))
        fields["gst_user"] = _line_edit("GST portal login")
        gst_lay.addWidget(fields["gst_user"])
        gst_lay.addSpacing(8)
        gst_lay.addWidget(_field_label("GST Password"))
        fields["gst_pwd"] = _line_edit("GST password")
        fields["gst_pwd"].setEchoMode(QLineEdit.EchoMode.Password)
        gst_lay.addWidget(fields["gst_pwd"])
        gst_show = _pw_cb("Show GST password")
        gst_lay.addWidget(gst_show)
        hosts["gst_show"] = gst_show
        right.addWidget(gst_box)
        right.addStretch(1)

        def _sync_enable(_checked: bool = False):
            it_box.setVisible(enable_it.isChecked())
            tds_box.setVisible(enable_tds.isChecked())
            gst_box.setVisible(enable_gst.isChecked())
            dlg.adjustSize()

        enable_it.toggled.connect(_sync_enable)
        enable_tds.toggled.connect(_sync_enable)
        enable_gst.toggled.connect(_sync_enable)

        def _toggle_echo(_checked: bool = False):
            fields["pwd"].setEchoMode(
                QLineEdit.EchoMode.Normal if show_cb.isChecked()
                else QLineEdit.EchoMode.Password)
            fields["tds_pwd"].setEchoMode(
                QLineEdit.EchoMode.Normal if hosts["tds_show"].isChecked()
                else QLineEdit.EchoMode.Password)
            fields["gst_pwd"].setEchoMode(
                QLineEdit.EchoMode.Normal if hosts["gst_show"].isChecked()
                else QLineEdit.EchoMode.Password)

        show_cb.toggled.connect(_toggle_echo)
        hosts["tds_show"].toggled.connect(_toggle_echo)
        hosts["gst_show"].toggled.connect(_toggle_echo)

        def _smart_normalise(text: str) -> str:
            """Pre-process raw text before vault normalisation.
            Handles pure digit strings: 8 digits → DD-MM-YYYY, 6 digits → DD-MM-YY.
            """
            import re as _re
            from vault import _normalise_dob
            s = text.strip()
            # Pure digits only — insert dashes
            if _re.fullmatch(r"\d{8}", s):          # 12121975 → 12-12-1975
                s = f"{s[:2]}-{s[2:4]}-{s[4:]}"
            elif _re.fullmatch(r"\d{6}", s):         # 121275  → 12-12-75
                s = f"{s[:2]}-{s[2:4]}-{s[4:]}"
            return _normalise_dob(s)

        def _normalise_and_hint(text):
            """Show a live ✓/✗ hint as the user types."""
            from vault import _DOB_RE
            raw = text.strip()
            if not raw:
                dob_hint.setText("")
                dob_edit.setStyleSheet(
                    f"QLineEdit{{border:1px solid {t.border};border-radius:6px;"
                    f"padding:6px 10px;font-size:12px;background:{t.bg_input};color:{t.text_primary};}}"
                    f"QLineEdit:focus{{border-color:{t.border_focus};}}")
                return
            # Only validate when enough chars typed (avoid red flash on first keystrokes)
            if len(raw) < 6:
                dob_hint.setText("")
                dob_edit.setStyleSheet(
                    f"QLineEdit{{border:1px solid {t.border};border-radius:6px;"
                    f"padding:6px 10px;font-size:12px;background:{t.bg_input};color:{t.text_primary};}}"
                    f"QLineEdit:focus{{border-color:{t.border_focus};}}")
                return
            normed = _smart_normalise(raw)
            if _DOB_RE.match(normed):
                dob_hint.setText(f"✓  Will save as: {normed}")
                dob_hint.setStyleSheet(f"font-size:10px;color:{t.success};background:transparent;border:none;")
                dob_edit.setStyleSheet(
                    f"QLineEdit{{border:1.5px solid {t.success};border-radius:6px;"
                    f"padding:6px 10px;font-size:12px;background:{t.bg_input};color:{t.text_primary};}}"
                    f"QLineEdit:focus{{border-color:{t.success};}}")
            else:
                dob_hint.setText("✗  Use DDMMYYYY or DD-MM-YYYY  e.g. 06071974")
                dob_hint.setStyleSheet(f"font-size:10px;color:{t.error};background:transparent;border:none;")
                dob_edit.setStyleSheet(
                    f"QLineEdit{{border:1.5px solid {t.error};border-radius:6px;"
                    f"padding:6px 10px;font-size:12px;background:{t.bg_input};color:{t.text_primary};}}"
                    f"QLineEdit:focus{{border-color:{t.error};}}")

        def _on_dob_commit():
            """On Tab/Enter/focus-out, rewrite the field to canonical DD-MM-YYYY."""
            from vault import _DOB_RE
            raw = dob_edit.text().strip()
            if not raw:
                return
            normed = _smart_normalise(raw)
            if _DOB_RE.match(normed):
                # Block signal to avoid recursive hint update while rewriting
                dob_edit.blockSignals(True)
                dob_edit.setText(normed)
                dob_edit.blockSignals(False)
                _normalise_and_hint(normed)

        dob_edit.textChanged.connect(_normalise_and_hint)
        dob_edit.editingFinished.connect(_on_dob_commit)

        # Calendar popup
        def _show_calendar():
            from PyQt6.QtCore import QDate
            from PyQt6.QtGui import QPalette, QColor
            from vault import _normalise_dob, _DOB_RE

            popup = QDialog(dlg)
            popup.setWindowTitle("Pick Date of Birth")
            popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            popup.setStyleSheet(
                f"QDialog{{background:{t.bg_panel};border:2px solid {t.border};border-radius:8px;}}"
                f"QToolButton{{color:{t.text_primary};background:transparent;border:none;"
                f"border-radius:4px;padding:3px 8px;font-size:12px;font-weight:600;}}"
                f"QToolButton:hover{{background:{t.accent};color:{t.accent_text};}}"
                f"QToolButton::menu-indicator{{image:none;}}"
                f"QSpinBox{{color:{t.text_primary};background:{t.bg_input};"
                f"border:1px solid {t.border};border-radius:4px;padding:2px 6px;}}"
                f"QSpinBox::up-button,QSpinBox::down-button{{background:transparent;border:none;}}"
                f"QMenu{{background:{t.bg_menu};color:{t.text_primary};border:1.5px solid {t.border_menu};}}"
                f"QMenu::item:selected{{background:{t.accent};color:{t.accent_text};}}"
                f"QHeaderView::section{{background:{t.bg_header};color:{t.text_muted};"
                f"border:none;font-size:11px;font-weight:600;padding:4px 0;}}"
                f"#qt_calendar_navigationbar{{background:{t.bg_header};padding:6px 8px;}}"
                f"QAbstractItemView{{background:{t.bg_table};color:{t.text_primary};"
                f"selection-background-color:{t.accent};selection-color:{t.accent_text};"
                f"outline:none;border:none;}}"
            )

            pl = QVBoxLayout(popup)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(0)

            cal = QCalendarWidget(popup)
            cal.setGridVisible(False)
            cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)

            # Set QPalette on the calendar so Qt's internal painter uses theme colours
            pal = QPalette()
            pal.setColor(QPalette.ColorRole.Window,      QColor(t.bg_table))
            pal.setColor(QPalette.ColorRole.Base,        QColor(t.bg_table))
            pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t.bg_table_alt))
            pal.setColor(QPalette.ColorRole.Text,        QColor(t.text_primary))
            pal.setColor(QPalette.ColorRole.BrightText,  QColor(t.accent_text))
            pal.setColor(QPalette.ColorRole.Highlight,   QColor(t.accent))
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.accent_text))
            pal.setColor(QPalette.ColorRole.ButtonText,  QColor(t.text_primary))
            pal.setColor(QPalette.ColorRole.Button,      QColor(t.bg_input))
            pal.setColor(QPalette.ColorRole.WindowText,  QColor(t.text_primary))
            pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.bg_menu))
            pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text_primary))

            # Disabled role — other-month days
            pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
                         QColor(t.text_muted))
            cal.setPalette(pal)

            # Apply palette to all child widgets (nav bar, table view, header)
            for child in cal.findChildren(QWidget):
                child.setPalette(pal)
                child.setAutoFillBackground(True)

            # Pre-select current value if valid
            raw = dob_edit.text().strip()
            normed = _normalise_dob(raw) if raw else ""
            if _DOB_RE.match(normed):
                try:
                    d, m, y = normed.split("-")
                    cal.setSelectedDate(QDate(int(y), int(m), int(d)))
                except Exception:
                    pass

            cal.setMaximumDate(QDate.currentDate())
            pl.addWidget(cal)

            def _picked(date):
                dob_edit.setText(f"{date.day():02d}-{date.month():02d}-{date.year()}")
                popup.accept()

            cal.clicked.connect(_picked)
            pos = cal_btn.mapToGlobal(cal_btn.rect().bottomLeft())
            popup.move(pos)
            popup.exec()

        def _show_calendar():
            from PyQt6.QtCore import QDate
            from PyQt6.QtGui import QPalette, QColor
            from vault import _normalise_dob, _DOB_RE

            popup = QDialog(dlg)
            popup.setWindowTitle("Pick Date of Birth")
            popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            popup.setStyleSheet(
                f"QDialog{{background:{t.bg_panel};border:2px solid {t.border};border-radius:8px;}}"
                f"QToolButton{{color:{t.text_primary};background:transparent;border:none;"
                f"border-radius:4px;padding:3px 8px;font-size:12px;font-weight:600;}}"
                f"QToolButton:hover{{background:{t.accent};color:{t.accent_text};}}"
                f"QToolButton::menu-indicator{{image:none;}}"
                f"QSpinBox{{color:{t.text_primary};background:{t.bg_input};"
                f"border:1px solid {t.border};border-radius:4px;padding:2px 6px;}}"
                f"QSpinBox::up-button,QSpinBox::down-button{{background:transparent;border:none;}}"
                f"QMenu{{background:{t.bg_menu};color:{t.text_primary};border:1.5px solid {t.border_menu};}}"
                f"QMenu::item:selected{{background:{t.accent};color:{t.accent_text};}}"
                f"QHeaderView::section{{background:{t.bg_header};color:{t.text_muted};"
                f"border:none;font-size:11px;font-weight:600;padding:4px 0;}}"
                f"#qt_calendar_navigationbar{{background:{t.bg_header};padding:6px 8px;}}"
                f"QAbstractItemView{{background:{t.bg_table};color:{t.text_primary};"
                f"selection-background-color:{t.accent};selection-color:{t.accent_text};"
                f"outline:none;border:none;}}"
            )

            pl = QVBoxLayout(popup)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(0)

            cal = QCalendarWidget(popup)
            cal.setGridVisible(False)
            cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)

            # Set QPalette on the calendar so Qt's internal painter uses theme colours
            pal = QPalette()
            pal.setColor(QPalette.ColorRole.Window,      QColor(t.bg_table))
            pal.setColor(QPalette.ColorRole.Base,        QColor(t.bg_table))
            pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t.bg_table_alt))
            pal.setColor(QPalette.ColorRole.Text,        QColor(t.text_primary))
            pal.setColor(QPalette.ColorRole.BrightText,  QColor(t.accent_text))
            pal.setColor(QPalette.ColorRole.Highlight,   QColor(t.accent))
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.accent_text))
            pal.setColor(QPalette.ColorRole.ButtonText,  QColor(t.text_primary))
            pal.setColor(QPalette.ColorRole.Button,      QColor(t.bg_input))
            pal.setColor(QPalette.ColorRole.WindowText,  QColor(t.text_primary))
            pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.bg_menu))
            pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text_primary))

            # Disabled role — other-month days
            pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
                         QColor(t.text_muted))
            cal.setPalette(pal)

            # Apply palette to all child widgets (nav bar, table view, header)
            for child in cal.findChildren(QWidget):
                child.setPalette(pal)
                child.setAutoFillBackground(True)

            # Pre-select current value if valid
            raw = dob_edit.text().strip()
            normed = _normalise_dob(raw) if raw else ""
            if _DOB_RE.match(normed):
                try:
                    d, m, y = normed.split("-")
                    cal.setSelectedDate(QDate(int(y), int(m), int(d)))
                except Exception:
                    pass

            cal.setMaximumDate(QDate.currentDate())
            pl.addWidget(cal)

            def _picked(date):
                dob_edit.setText(f"{date.day():02d}-{date.month():02d}-{date.year()}")
                popup.accept()

            cal.clicked.connect(_picked)
            pos = cal_btn.mapToGlobal(cal_btn.rect().bottomLeft())
            popup.move(pos)
            popup.exec()

        cal_btn.clicked.connect(_show_calendar)

        # ── Footer ────────────────────────────────────────────────────────────
        root.addSpacing(16)
        sep = QFrame(); sep.setObjectName("clientSep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)
        root.addSpacing(14)

        # Pre-fill if editing
        if editing:
            fields["name"].setText(a.get("name", ""))
            fields["pan"].setText(a.get("pan", ""))
            fields["dob"].setText(a.get("dob", ""))
            fields["pwd"].setText(a.get("password", ""))
            fields["email"].setText(a.get("email", ""))
            fields["cc"].setText(a.get("cc", ""))
            fields["tds_user"].setText(a.get("tds_username", ""))
            fields["tds_pwd"].setText(a.get("tds_password", ""))
            fields["gst_user"].setText(a.get("gst_username", ""))
            fields["gst_pwd"].setText(a.get("gst_password", ""))
            from vault import credential_sources as _sources
            _src = _sources(a)
            enable_it.setChecked(bool(a.get("enable_income_tax", "Income Tax" in _src)))
            enable_gst.setChecked(bool(a.get("enable_gst", "GST" in _src)))
            enable_tds.setChecked(bool(a.get("enable_tds", "TDS" in _src)))
        else:
            enable_it.setChecked(True)   # a new client starts as a PAN client
        _sync_enable()

        # Buttons
        btn_row = QHBoxLayout()
        btn_cancel = _btn("Cancel", "secondary", height=34, icon="btn_cancel.png")
        btn_save   = _btn("Update Client" if editing else "Add Client", "primary", height=34, icon="btn_add_client.png")
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

        btn_cancel.clicked.connect(dlg.reject)

        def _save():
            try:
                edit_id = a.get("id") if editing else None
                it_on = enable_it.isChecked()
                tds_on = enable_tds.isChecked()
                gst_on = enable_gst.isChecked()
                if not (it_on or tds_on or gst_on):
                    raise ValueError("Tick at least one portal for this client.")
                if gst_on and not (fields["gst_user"].text().strip()
                                   and fields["gst_pwd"].text()):
                    raise ValueError(
                        "GST is enabled — enter the GST username and password.")
                if tds_on and not (fields["tds_user"].text().strip()
                                   and fields["tds_pwd"].text()):
                    raise ValueError(
                        "TDS is enabled — enter the TDS / TRACES username and password.")
                self.vault.add_update_assessee(
                    fields["name"].text(), fields["pan"].text(),
                    fields["dob"].text(),
                    fields["pwd"].text() if it_on else "", edit_id,
                    email=fields["email"].text(),
                    cc=fields["cc"].text(),
                    group=fields["group"].currentText(),
                    gst_username=fields["gst_user"].text() if gst_on else "",
                    gst_password=fields["gst_pwd"].text() if gst_on else "",
                    tds_username=fields["tds_user"].text() if tds_on else "",
                    tds_password=fields["tds_pwd"].text() if tds_on else "",
                    enable_income_tax=it_on,
                    enable_gst=gst_on,
                    enable_tds=tds_on)
                action = "updated" if editing else "added"
                self.log(f"[Vault] Client {action}: {fields['pan'].text()} — {fields['name'].text()}")
                dlg.accept()
                self.refresh_grid()
            except ValueError as ve:
                QMessageBox.critical(dlg, "Validation Error", str(ve))
            except Exception as ex:
                QMessageBox.critical(dlg, "Error", str(ex))

        btn_save.clicked.connect(_save)
        dlg.exec()

    def save_assessee(self):
        self._open_add_client()

    def _open_assign_group(self):
        """F-11 — control bar 'Assign to Group…': sets the Group field for
        every currently checked client (self.selected_ids), same
        "select clients in the grid, then act on them" pattern already
        used by Downloads/Email Docs."""
        if not self.selected_ids:
            QMessageBox.warning(self, "Selection Required",
                "Please select at least one client.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Assign to Group")
        dlg.setFixedWidth(360)
        t = _t()
        dlg.setStyleSheet(
            f"QDialog{{background:{t.bg_window};}}"
            f"QLabel{{background:transparent;border:none;color:{t.text_primary};font-size:12px;}}")
        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(8)

        vl.addWidget(QLabel(f"Set the Group for {len(self.selected_ids)} selected client(s):"))
        combo = self._make_group_combo()
        vl.addWidget(combo)
        vl.addSpacing(12)

        btn_row = QHBoxLayout()
        btn_cancel = _btn("Cancel", "secondary", height=34)
        btn_apply = _btn("Apply", "primary", height=34)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_apply)
        vl.addLayout(btn_row)

        btn_cancel.clicked.connect(dlg.reject)

        def _apply():
            group = combo.currentText().strip()
            for a_id in self.selected_ids:
                self.vault.set_client_group(a_id, group)
            if group:
                self.log(f"[Vault] {len(self.selected_ids)} client(s) assigned to group: '{group}'")
            else:
                self.log(f"[Vault] {len(self.selected_ids)} client(s) ungrouped.")
            dlg.accept()
            self.refresh_grid()

        btn_apply.clicked.connect(_apply)
        dlg.exec()

    # ── Email menu handlers ───────────────────────────────────────────────────

    def _clear_eproc_credential_flags(self):
        flagged = sorted(self.vault.get_credential_invalid())
        if not flagged:
            QMessageBox.information(self, "No Warnings",
                                    "No client is currently blocked for a password update.")
            return
        answer = QMessageBox.question(
            self, "Clear Password Warnings",
            f"Clear the password warning for {len(flagged)} client(s)?\n\n"
            "Only do this after updating their passwords.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        for pan in flagged:
            self.vault.set_client_credential_invalid(pan, False)
        self.log(f"[Auto-Fetch] Cleared password warning for {len(flagged)} client(s).")
        self.refresh_grid()

    def _open_eproc_autofetch_settings(self):
        dlg = EAutoFetchSettingsDialog(self, self.vault, self.vault.get_all_assessees())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg = self.vault.get_eproc_autofetch_config()
            if cfg["enabled"] and not self._eproc_auto_running:
                from automation.eproc_scheduler import compute_next_run
                nxt = compute_next_run(datetime.datetime.now(), cfg)
                cfg["next_run_at"] = nxt.isoformat(timespec="seconds") if nxt else ""
                cfg = self.vault.save_eproc_autofetch_config(cfg)
            self._refresh_eproc_autofetch_summary()
            self.log("[Auto-Fetch] Settings saved.")

    def _on_eproc_autofetch_toggle(self, state):
        cfg = self.vault.get_eproc_autofetch_config()
        cfg["enabled"] = bool(state)
        if cfg["enabled"] and not cfg.get("next_run_at"):
            from automation.eproc_scheduler import compute_next_run
            next_run = compute_next_run(datetime.datetime.now(), cfg)
            cfg["next_run_at"] = next_run.isoformat(timespec="seconds") if next_run else ""
        self.vault.save_eproc_autofetch_config(cfg)
        self._refresh_eproc_autofetch_summary()
        self.log(f"[Auto-Fetch] {'Enabled' if cfg['enabled'] else 'Disabled'}.")

    def _refresh_eproc_autofetch_summary(self):
        label = getattr(self, "lbl_eproc_autofetch_summary", None)
        compact = getattr(self, "lbl_eproc_auto_status", None)
        cfg = self.vault.get_eproc_autofetch_config()
        if not cfg["enabled"]:
            if label is not None:
                label.setText("Auto-fetch is off.")
            if compact is not None:
                compact.setText("Auto-fetch off")
            return
        parts = []
        backoff = cfg.get("backoff_until") or ""
        if backoff:
            try:
                when = datetime.datetime.fromisoformat(backoff)
                if when > datetime.datetime.now():
                    parts.append(f"Backing off until {when.strftime('%d %b %H:%M')}")
            except ValueError:
                pass
        next_run = cfg.get("next_run_at") or ""
        if next_run:
            try:
                when = datetime.datetime.fromisoformat(next_run)
                parts.append(f"Next run {when.strftime('%d %b %H:%M')}")
            except ValueError:
                pass
        summary = cfg.get("last_run_summary") or {}
        if summary:
            parts.append(
                f"Last: {summary.get('synced', 0)} synced, "
                f"{summary.get('failed', 0)} failed, "
                f"{summary.get('flagged', 0)} password issue(s)")
        if not parts:
            parts.append(f"Scheduled daily at {cfg['run_time']}")
        text = " · ".join(parts)
        if label is not None:
            label.setText(text)
        if compact is not None:
            compact.setText(text)

    def _open_email_settings(self):
        from ui.dialogs import SmtpSettingsDialog
        SmtpSettingsDialog(self, self.vault).exec()

    def _open_mail_docs(self):
        from ui.dialogs import MailDocsDialog
        # F-14: Mail Docs works against one year at a time — uses whichever
        # checked year is first if the combo has more than one checked.
        _checked = self.ay_combo.checked_labels() if hasattr(self, "ay_combo") else []
        ay_label = _checked[0] if _checked else ""
        MailDocsDialog(self, self.vault, ay_label).exec()

    def _open_eproceedings_viewer(self, a=None):
        """Tools > View e-Proceedings, and the grid row context menu's own
        "View e-Proceedings" entry (which passes the clicked client in `a`).

        `a` is the clicked client dict from the grid context menu — OR the
        QAction `checked` boolean when triggered from the Tools menu
        (Qt passes it as the first positional arg), so anything that isn't
        a dict is treated as "no explicit client" and the grid selection is
        used instead.

        Client comes from the grid selection (self.selected_ids, same source
        of truth every other single-client flow uses) unless a row was
        explicitly clicked. Year folder is resolved exactly like
        _execute_batch's _out_for_year: <root>/<PAN>-<name_safe>/<AY|TY_value>,
        using the first checked year of the combo (e-Proceedings downloads are
        not year-scoped — batch_handlers.handle_e_proceedings anchors them to
        the FIRST selected year's folder too). A missing folder still opens
        the dialog; it shows its own empty state."""
        if not isinstance(a, dict):
            a = None
        if a is None:
            if not self.selected_ids:
                QMessageBox.warning(self, "Selection Required",
                    "Please select at least one client.")
                return
            matches = [x for x in self.assessee_list if x.get("id") in self.selected_ids]
            if not matches:
                QMessageBox.warning(self, "Selection Required",
                    "Please select at least one client.")
                return
            a = matches[0]
        pan = a.get("pan", "")
        name = a.get("name", "")
        _checked = self.ay_combo.checked_labels() if hasattr(self, "ay_combo") else []
        ay_label = _checked[0] if _checked else ""
        _ay, _fy, year_type, _form = self._resolve_ay_fy(ay_label) if ay_label else (None, None, "AY", None)
        value = _ay if year_type == "AY" else (_fy if year_type == "TY" else None)
        if not value:
            QMessageBox.warning(self, "Selection Required",
                "Please select at least one Assessment / Tax Year.")
            return
        name_safe = "".join(c if c.isalnum() or c in " _-" else "" for c in name)
        root_dir = self.dir_lbl.text()
        year_dir = os.path.join(root_dir, f"{pan}-{name_safe}", f"{year_type}_{value.replace('-','_')}")
        eproc_root = os.path.join(year_dir, "e-Proceedings")
        EProceedingsDialog(self, name or pan, pan, eproc_root).exec()

    def _show_log_history(self, a: dict):
        history  = self.log_store.get(a.get("pan", ""))
        _checked = self.ay_combo.checked_labels() if hasattr(self, "ay_combo") else []
        ay_label = _checked[0] if _checked else ""
        LogHistoryDialog(self, name=a.get("name", ""), pan=a.get("pan", ""),
                         history=history, active_ay=ay_label).exec()

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

    def _open_saved_path(self, path: str):
        from config import _open_path, _log_open
        _log_open(f"[OpenFolder] Grid link clicked: {path!r}")
        _open_path(path)

    def _open_output_folder(self):
        from config import _open_path, _log_open
        path = self.dir_lbl.text()
        _log_open(f"[OpenFolder] Main window Open button: {path!r}")
        _open_path(path)

    def browse_output_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Output Directory",
            self.dir_lbl.text())
        if chosen:
            if sys.platform == "win32":
                chosen = chosen.replace("/", "\\")
            self.dir_lbl.setText(chosen)
            self.vault.update_setting("download_root_dir", chosen)
            self.log(f"[Settings] Output folder: {chosen}")

    def _ay_json_path(self) -> str:
        """
        Writable path for assessment_years.json in the user data dir.

        The bundled copy lists the years shipped with the release; the writable
        copy holds the user's enable/disable choices and any years they added.
        Both are merged on every launch so years introduced by a new release
        show up for existing installs while their edits survive. Seeding only
        when the file was missing left upgraded installs pinned to the year
        list from whenever the app first ran.
        """
        writable = os.path.join(_app_dir(), "assessment_years.json")
        bundled = os.path.join(_bundled_dir(), "assessment_years.json")

        # Running from source: both resolve to the repo file — nothing to merge.
        if os.path.abspath(writable) == os.path.abspath(bundled):
            return writable

        try:
            with open(bundled, "r", encoding="utf-8") as f:
                bundled_entries = json.load(f)
        except Exception:
            return writable

        if not os.path.exists(writable):
            try:
                import shutil
                shutil.copy2(bundled, writable)
            except Exception:
                pass
            return writable

        try:
            with open(writable, "r", encoding="utf-8") as f:
                user_entries = json.load(f)
            known = {e.get("label") for e in user_entries}
            missing = [e for e in bundled_entries if e.get("label") not in known]
            if missing:
                user_entries.extend(missing)
                with open(writable, "w", encoding="utf-8") as f:
                    json.dump(user_entries, f, indent=2)
        except Exception:
            # Runs during UI construction, before the log widget exists — a bad
            # merge must never block startup; the user keeps their existing list.
            pass

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
        """
        Returns (ay_or_ty_value, fy_value, year_type, form_type) where year_type
        is 'AY' or 'TY'. The form is derived from the year type (see forms.py),
        not read from the year entry, so an installed copy of
        assessment_years.json written by an older release can't disagree with
        the code about which form to fetch.
        """
        for e in self._ay_entries:
            if e["label"] == label:
                y = e["year"]
                if y.get("AY"):
                    return y["AY"], y.get("FY"), "AY", form_for("AY", y["AY"])
                if y.get("TY"):
                    return y["TY"], y.get("FY"), "TY", form_for("TY", y["TY"])
        return None, None, "AY", DEFAULT_FORM

    def open_manage_years(self):
        ManageYearsDialog(self, self._ay_json_path(), on_save=self.refresh_ay_combo).exec()

    def open_manage_groups(self):
        from ui.dialogs import ManageGroupsDialog
        ManageGroupsDialog(self, self.vault).exec()
        self.refresh_grid()

    def refresh_ay_combo(self):
        self._ay_entries = self._load_ay_list()
        ay_labels = [e["label"] for e in self._ay_entries if e.get("enabled", True)]
        current = set(self.ay_combo.checked_labels())
        self.ay_combo.blockSignals(True)
        self.ay_combo.clear_items()
        for _label in ay_labels:
            self.ay_combo.add_item(_label, checked=(_label in current))
        self.ay_combo.blockSignals(False)
        self._populate_dl_ay_combo()
        self.log("[Settings] Assessment Year list refreshed.")

    def _log_ay_selection(self):
        labels = self.ay_combo.checked_labels()
        if labels:
            self.log(f"[Settings] Assessment Year(s) → {', '.join(labels)}")

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, message):
        text = f"[{get_timestamp()}] {message}"
        self._log_signal.emit(text)
        try:
            with open(os.path.join(_app_dir(), "app.log"), "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    _LOG_TS_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$", re.S)

    def _log_level_color(self, message: str) -> str:
        """Classify a log line the same way iBench does — by scanning for
        a status marker already present in the message text — and return
        the matching theme-invariant log severity colour."""
        t = _t()
        m = message.lower()
        if "✅" in message or "done" in m:
            return t.log_success
        if "❌" in message or "error" in m or "failed" in m or "timeout" in m:
            return t.log_error
        if "⚠" in message or "🕐" in message or "warn" in m:
            return t.log_warning
        if "[debug]" in m:
            return t.log_debug
        return t.log_info

    def _append_log(self, text):
        m = self._LOG_TS_RE.match(text)
        ts, message = (m.group(1), m.group(2)) if m else ("", text)
        color = self._log_level_color(message)
        ts_color = _t().log_timestamp
        row = (
            '<div style="white-space:pre;line-height:20px;">'
            f'<span style="color:{ts_color};">{html.escape(ts)}</span>'
            f'<span style="color:{ts_color};">&nbsp;&nbsp;</span>'
            f'<span style="color:{color};">{html.escape(message)}</span>'
            '</div>'
        )
        self.log_box.append(row)
        self.log_box.moveCursor(QTextCursor.MoveOperation.End)
        self._log_line_count += 1
        if hasattr(self, "_log_count_lbl"):
            self._log_count_lbl.setText(f"{self._log_line_count} line{'s' if self._log_line_count != 1 else ''}")

    def _clear_log(self):
        self.log_box.clear()
        self._log_line_count = 0
        if hasattr(self, "_log_count_lbl"):
            self._log_count_lbl.setText("0 lines")

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
        _out_dir = self.vault.get_setting("download_root_dir", "")
        _default = os.path.join(_out_dir, "Assessee_Export") if _out_dir and os.path.isdir(_out_dir) else "Assessee_Export"
        path, _ = QFileDialog.getSaveFileName(self, "Export Saved Data",
            _default, "Excel Workbook (*.xlsx);;CSV (*.csv)")
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

    def _check_for_update(self, manual=False):
        if manual:
            self._update_check_manual = True
        from updater import check_for_update
        def _cb(tag, _url):
            QMetaObject.invokeMethod(
                self, "_on_update_result",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, tag or ""),
            )
        check_for_update(_cb)

    @pyqtSlot(str)
    def _on_update_result(self, tag: str):
        manual = getattr(self, "_update_check_manual", False)
        self._update_check_manual = False
        if tag:
            # Stop any existing blink timer before starting a new one
            if hasattr(self, "_update_blink_timer"):
                self._update_blink_timer.stop()
            self._update_link_text = f'<a href="#" style="color:{_t().accent};font-size:11px;">&#11015; v{tag} available</a>'
            self._update_link_visible = True
            self._hdr_update_lnk.setText(self._update_link_text)
            self._update_blink_timer = QTimer(self)
            def _blink():
                self._update_link_visible = not self._update_link_visible
                self._hdr_update_lnk.setText(
                    self._update_link_text if self._update_link_visible else ""
                )
            self._update_blink_timer.timeout.connect(_blink)
            self._update_blink_timer.start(600)
            if manual:
                from PyQt6.QtWidgets import QMessageBox
                res = QMessageBox.question(
                    self, "Update Available",
                    f"Version {tag} is available.\n\nOpen the download page?",
                )
                if res == QMessageBox.StandardButton.Yes:
                    self._on_update_link_clicked()
        elif manual:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Up to Date",
                f"You're on the latest version (v{APP_VERSION})."
            )

    def _on_update_link_clicked(self):
        if hasattr(self, "_update_blink_timer"):
            self._update_blink_timer.stop()
        self._hdr_update_lnk.setText(getattr(self, "_update_link_text", ""))
        QDesktopServices.openUrl(QUrl("https://download.aaydoccapio.com/"))

    # ── Automation ────────────────────────────────────────────────────────────

    def _lock_ui(self, lock: bool):
        widgets = [self.ay_combo, self.btn_run, self.chk_headless]
        if hasattr(self, "_dl_ay_combo"):
            widgets.append(self._dl_ay_combo)
        for _act in (getattr(self, "_act_edit_cl", None), getattr(self, "_act_del_cl", None)):
            if _act:
                _act.setEnabled(not lock)
        if hasattr(self, "header_cb"):
            widgets.append(self.header_cb)
        for w in widgets:
            w.setEnabled(not lock)
        # Disable Client Master / Settings menus during batch
        menubar = self.menuBar()
        for action in menubar.actions():
            if action.text() in ("Client Master", "Settings"):
                if action.menu():
                    action.menu().setEnabled(not lock)

    def _open_download_picker(self):
        """F-56 Phase 3 — the Download button opens a checkbox picker instead
        of the old dropdown menu; on confirm, kicks off start_automation with
        whatever combination of document types the user selected."""
        if self.is_running:
            return
        dlg = DownloadPickerDialog(self, self.vault)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.start_automation(dlg.selected_docs)

    def start_automation(self, selected_docs):
        """
        selected_docs: set/collection of doc-type strings to run, any of
        "26as", "request_ais", "ais_tis", "filed_returns", "filed_forms" —
        one batch run can now cover several at once (F-56 Phase 2).

        F-14 (multi-year): the AY/TY combo is now a multi-select — every
        checked year runs for every selected client. `year_specs` (built
        below) is the single list threaded through the rest of the batch:
        one dict per checked year, each carrying its own resolved AY/TY
        value, FY, year type, and form (26AS vs Form 168).
        """
        selected_docs = set(selected_docs) if not isinstance(selected_docs, set) else selected_docs
        if self.is_running:
            return
        if getattr(self, "_eproc_auto_running", False):
            QMessageBox.warning(self, "Auto-Fetch Running",
                "Scheduled e-Proceedings auto-fetch is running. Stop it before starting another batch.")
            return
        if not selected_docs:
            return
        if not self.selected_ids:
            QMessageBox.warning(self, "Selection Required",
                "Please select at least one client.")
            return
        ay_labels = self.ay_combo.checked_labels()
        if not ay_labels:
            QMessageBox.warning(self, "Selection Required",
                "Please select at least one Assessment / Tax Year.")
            return

        year_specs = []
        for ay_label in ay_labels:
            ay, fy, year_type, form_type = self._resolve_ay_fy(ay_label)
            if not ay:
                self.log(f"[Warning] Skipping unresolvable year: {ay_label}")
                continue
            year_specs.append({
                "ay_label": ay_label, "value": ay, "fy": fy,
                "year_type": year_type, "form_type": form_type,
            })
        if not year_specs:
            QMessageBox.warning(self, "Invalid", "None of the selected years could be resolved.")
            return

        self.is_running = True
        self._batch_aborted = False
        self._batch_filing_scope = self.vault.get_setting("filed_returns_scope", "all")
        self._lock_ui(True)
        self._clear_log()

        targets = [a for a in self.assessee_list if a.get("id") in self.selected_ids]
        output_dir = self.dir_lbl.text()
        self._last_batch_params = (year_specs, output_dir, selected_docs)

        self.btn_run.setText("⏳ Downloading...")

        run_label = " + ".join(DOC_TYPE_LABELS.get(d, d) for d in sorted(selected_docs))
        years_desc = ", ".join(ay_labels)
        self.log(f"[System] Starting {run_label} — {len(targets)} client(s) | Year(s): {years_desc} | Output: {output_dir}")

        # Year tag shown in progress dialog title
        year_tag = years_desc if len(ay_labels) <= 3 else f"{len(ay_labels)} years"

        # Show progress dialog (on main thread via signal)
        self._progress_id_label = "PAN"
        self._show_progress_signal.emit(targets, selected_docs, year_specs, output_dir, year_tag)

        # Enable "Send to Tray" in tray menu while batch is running
        if hasattr(self, "_tray_send_act"):
            self._tray_send_act.setVisible(True)

        # F-35: send to system tray if auto-minimise enabled
        if getattr(self, "chk_auto_minimise", None) and self.chk_auto_minimise.isChecked():
            QTimer.singleShot(800, lambda: self._tray_to_system(len(targets)))

        threading.Thread(
            target=self._run_wrapper,
            args=(targets, year_specs, output_dir, selected_docs),
            daemon=True).start()

    def _show_progress_dialog(self, targets: list, selected_docs: set, year_specs: list,
                               output_dir: str = "", year_tag: str = ""):
        """Called on main thread to create and show the progress dialog."""
        self._progress_dialog = BatchProgressDialog(
            targets, selected_docs, year_specs=year_specs, ay=year_tag,
            stop_callback=self.stop_automation,
            resume_callback=self.resume_batch, skip_callback=self.skip_client,
            tray_callback=self._tray_to_system_manual,
            output_dir=output_dir, parent=self,
            id_label=getattr(self, "_progress_id_label", "PAN"))
        # Window-modal: blocks the parent window but allows live signal updates.
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.show()
        self._progress_dialog.raise_()
        self._progress_dialog.activateWindow()

    # ── F-12: View saved challans (Paid / Unpaid) ────────────────────────────

    def _open_view_challans_dialog(self):
        """Read-only browser for challans already saved on disk. No portal
        login — the files are the source of truth, since generation does not
        write a download-history record into the vault."""
        from ui.challan_viewer import ViewChallansDialog
        root = self.dir_lbl.text() or self.vault.get_setting("download_root_dir", "")
        dlg = ViewChallansDialog(self, root, self.vault.get_all_assessees())
        dlg.exec()

    # ── F-64: Generate Tax Challans ──────────────────────────────────────────

    def _open_generate_challans_dialog(self):
        """Toolbar/menu entry point for bulk challan generation — a separate
        flow from the Downloads batch above, since each row here carries its
        own amount breakup (not just client identity), which the existing
        HANDLERS/DownloadPickerDialog/BatchProgressDialog pipeline has no
        room for. See PlansofThisProject/F-64_bulk_tax_challan_generation.md."""
        if self._challan_running:
            return
        dlg = GenerateChallansDialog(self, self.vault, self._ay_entries, output_dir=self.dir_lbl.text())
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.start_challan_generation(dlg.fy_value, dlg.rows)

    def _download_challan_template(self):
        """E-Pay Tax > Download Import Template — lets a user get the blank
        template straight away, without opening the full Generate Tax
        Challans dialog first just to reach its own template button."""
        from ui.dialogs import download_challan_template
        path, _ = QFileDialog.getSaveFileName(self, "Save Template",
            "Challan_Rows_Template", "Excel Workbook (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        try:
            download_challan_template(path)
            QMessageBox.information(self, "Success", f"Template generated at:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed: {e}")

    def start_challan_generation(self, fy_value: str, rows: list):
        from automation.challan_generator import resolve_tax_type, TAX_TYPES
        try:
            tax_type, portal_year_label = resolve_tax_type(fy_value, self._ay_entries)
        except Exception as e:
            QMessageBox.critical(self, "Year Not Ready", str(e))
            return

        # Match each row's PAN against the vault once, up front, so a client
        # removed/renamed between dialog-open and Generate-click can't crash
        # the batch mid-run — same defensiveness as start_automation's
        # targets list build.
        by_pan = {a.get("pan", "").upper(): a for a in self.assessee_list}
        targets = []
        for row in rows:
            client = by_pan.get(row["pan"].upper())
            if not client:
                self.log(f"[Warning] Skipping {row['pan']} — no longer in Client Master.")
                continue
            targets.append({**client, "_amounts": row})
        if not targets:
            QMessageBox.warning(self, "Nothing to Generate", "None of the selected clients could be matched.")
            return

        self._challan_running = True
        self._challan_aborted = False
        self._clear_log()
        if hasattr(self, "_tray_send_act"):
            self._tray_send_act.setVisible(True)

        output_dir = self.dir_lbl.text()
        type_label = TAX_TYPES[tax_type]["label"]
        # portal_year_label alone is just a bare "2026-27" — prefix with
        # AY/TY so it's clear which Act/year convention it is, same as the
        # dialog's own combo already shows (e.g. "TY 2026-27 (FY 2026-27)").
        year_prefix = "TY" if tax_type == "advance" else "AY"
        year_display = f"{year_prefix} {portal_year_label}"
        self.log(f"[System] Starting Tax Challan generation — {len(targets)} client(s) | "
                 f"FY {fy_value} → {type_label} | Output: {output_dir}")

        self._show_challan_progress_signal.emit(targets, year_display, type_label, output_dir)

        threading.Thread(
            target=self._run_challan_wrapper,
            args=(targets, fy_value, portal_year_label, tax_type, output_dir),
            daemon=True).start()

    def _show_challan_progress_dialog(self, targets: list, year_display: str, type_label: str, output_dir: str):
        self._challan_progress_dialog = ChallanGenerationProgressDialog(
            targets, year_display, type_label,
            stop_callback=self.stop_challan_generation,
            tray_callback=self._tray_to_system_manual,
            output_dir=output_dir, parent=self)
        self._challan_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._challan_progress_dialog.show()
        self._challan_progress_dialog.raise_()
        self._challan_progress_dialog.activateWindow()

    def stop_challan_generation(self):
        if not self._challan_running:
            return
        self.log("[System] Abort requested (Tax Challan generation)...")
        self._challan_running = False
        self._challan_aborted = True
        if self._challan_task and self._challan_loop:
            self._challan_loop.call_soon_threadsafe(self._challan_task.cancel)

    def _run_challan_wrapper(self, targets, fy_value, portal_year_label, tax_type, output_dir):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._challan_loop = loop
        try:
            self._challan_task = loop.create_task(
                self._execute_challan_generation(targets, fy_value, portal_year_label, tax_type, output_dir))
            loop.run_until_complete(self._challan_task)
        except asyncio.CancelledError:
            self.log("[System] Tax Challan generation cancelled.")
        except Exception as e:
            self.log(f"[System Error] Tax Challan generation crashed: {e}")
        finally:
            self._challan_task = None
            self._challan_loop = None
            loop.close()
            self._challan_running = False
            if self._challan_progress_dialog:
                self._challan_progress_dialog.batch_finished()
            self._challan_done_signal.emit()

    async def _execute_challan_generation(self, targets, fy_value, portal_year_label, tax_type, output_dir):
        from automation.challan_generator import generate_challan, TAX_TYPES

        def set_status(row_index, text):
            if self._challan_progress_dialog:
                self._challan_progress_dialog.set_status(row_index, text)

        try:
            interactive = not self.chk_headless.isChecked()
            context = await browser_manager.get_context(log_callback=self.log, interactive=interactive)
        except Exception as e:
            self.log(f"[System Error] Browser init failed: {e}"); return

        results = []
        processed_indices = set()
        try:
            for i, target in enumerate(targets):
                if not self._challan_running:
                    self.log("[System] Aborted."); break

                pan = target.get("pan", "")
                name = target.get("name", "")
                dob = target.get("dob", "")
                row = target.get("_amounts", {})
                payment_mode = row.get("payment_mode", "")
                bank = row.get("bank", "")
                drawee_bank = row.get("drawee_bank", "")
                amounts = {k: row.get(k, 0) for k in
                           ("tax", "surcharge", "cess", "interest", "penalty", "others")}
                self.log("──────────────────────────────────────────────────")
                self.log(f"[{i+1}/{len(targets)}] {name}")

                # Same "{PAN}-{Name}/AY_2026_27/" convention used for
                # 26AS/AIS/Filed Returns/downloaded Tax Challans, so
                # "Tax Challans (Payable)" lands under the client's own
                # PAN+Year folder instead of a flat top-level folder.
                name_safe = "".join(c if c.isalnum() or c in " _-" else "" for c in name)
                year_type = TAX_TYPES[tax_type]["act_year_type"]
                client_year_dir = os.path.join(
                    output_dir, f"{pan}-{name_safe}",
                    f"{year_type}_{portal_year_label.replace('-', '_')}")
                set_status(i, "⏳ Logging in to ITD...")

                page = None
                try:
                    page = await login_itd(pan, target.get("password"), self.log, context,
                                            is_running=lambda: self._challan_running)
                    set_status(i, "⏳ Navigating to e-Pay Tax...")
                    from automation.downloader_challans import navigate_to_epay_tax_act
                    await navigate_to_epay_tax_act(page, self.log, TAX_TYPES[tax_type]["act_year_type"])

                    set_status(i, "⏳ Generating challan...")
                    result = await generate_challan(
                        page, fy_value, portal_year_label, tax_type, amounts,
                        payment_mode, bank, drawee_bank,
                        client_year_dir, self.log, pan=pan, dob=dob)
                    result["pan"] = pan
                    result["name"] = name
                    results.append(result)
                    processed_indices.add(i)

                    if result["status"] == "generated":
                        set_status(i, f"✅ Generated — CRN {result['crn']}")
                        if self._challan_progress_dialog and result.get("artifact_path"):
                            self._challan_progress_dialog.set_artifact_path(i, result["artifact_path"])
                    elif result["status"] == "unavailable":
                        set_status(i, f"⚠ Unavailable — {result['reason']}")
                    else:
                        set_status(i, f"❌ Failed — {result['reason']}")
                except Exception as e:
                    self.log(f"[Error] {name}: {e}")
                    set_status(i, f"❌ Failed — {e}")
                    results.append({
                        "pan": pan, "name": name, "fy_value": fy_value,
                        "portal_year_label": portal_year_label, "tax_type": tax_type,
                        "crn": "", "total_amount": sum(amounts.get(k, 0) or 0 for k in
                            ("tax", "surcharge", "cess", "interest", "penalty", "others")),
                        "valid_till": "", "payment_mode": payment_mode, "bank": bank,
                        "drawee_bank": drawee_bank,
                        "status": "failed", "reason": str(e), "artifact_path": "",
                    })
                    processed_indices.add(i)
                finally:
                    if page:
                        try:
                            await logout_itd(page, self.log)
                        except Exception:
                            pass
        except asyncio.CancelledError:
            # stop_challan_generation() cancels this task directly —
            # CancelledError isn't an Exception subclass (Python 3.8+), so
            # the per-client `except Exception` above never sees it and the
            # in-flight client's row was otherwise left frozen on whatever
            # status it last had ("Logging in...", etc.), making the
            # progress dialog look stuck even though the run did stop.
            self.log("[System] Tax Challan generation stopped by user.")
        finally:
            # Mark the in-flight client (if any) and every not-yet-started
            # one as stopped, rather than leaving their rows on a stale
            # "Logging in..."/"Waiting" status forever. Tracked by row
            # index, not PAN — the same PAN can appear in multiple rows
            # (e.g. a split Cash + Cheque challan pair for one client).
            for idx in range(len(targets)):
                if idx not in processed_indices:
                    set_status(idx, "⏹ Stopped")
            try:
                report_path = self._write_challan_summary(results, output_dir, fy_value, tax_type)
                if report_path and self._challan_progress_dialog:
                    self._challan_progress_dialog.set_report_path(report_path)
            except Exception as e:
                self.log(f"[Warning] Could not write challan summary: {e}")

    def _write_challan_summary(self, results: list, output_dir: str, fy_value: str, tax_type: str) -> str:
        from automation.challan_fields import CHALLAN_SUMMARY_COLUMNS
        from automation.challan_generator import TAX_TYPES
        from openpyxl import Workbook
        import datetime as _dt

        os.makedirs(output_dir, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(output_dir, f"Tax_Challans_Summary_{ts}.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.append(CHALLAN_SUMMARY_COLUMNS)
        # BUG FIX (2026-09-02): "Portal Year Label" showed a bare "2025-26"
        # with no way to tell AY vs TY from the sheet alone — same issue
        # fixed in generate_challan()'s artifact filenames. Prefix it the
        # same way, using TAX_TYPES' act_year_type ("AY" or "TY").
        year_prefix = TAX_TYPES.get(tax_type, {}).get("act_year_type", "")
        for r in results:
            portal_year_label = r.get("portal_year_label", "")
            year_label_display = f"{year_prefix} {portal_year_label}".strip() if portal_year_label else ""
            ws.append([
                r.get("pan", ""), r.get("name", ""), fy_value,
                TAX_TYPES.get(tax_type, {}).get("label", tax_type),
                year_label_display, r.get("payment_mode", ""), r.get("bank", ""),
                r.get("drawee_bank", ""), r.get("total_amount", 0), r.get("crn", ""),
                r.get("valid_till", ""), r.get("status", ""), r.get("reason", ""),
                r.get("artifact_path", ""),
            ])
        wb.save(path)
        self.log(f"[System] Challan summary written: {path}")
        return path

    def _on_challan_batch_done(self):
        self.log("[System] Tax Challan generation idle.")
        if hasattr(self, "_tray_send_act") and not self.is_running:
            self._tray_send_act.setVisible(False)
        self.refresh_grid()


    # ── F-4: Generate TDS/TCS Challans ───────────────────────────────────────

    def _open_generate_tds_challans_dialog(self):
        if self._tds_challan_running:
            return
        from ui.dialogs import GenerateTdsChallansDialog
        dlg = GenerateTdsChallansDialog(self, self.vault, self._ay_entries,
                                        output_dir=self.dir_lbl.text())
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.start_tds_challan_generation(dlg.year_label, dlg.rows)

    def start_tds_challan_generation(self, year_label: str, rows: list):
        from vault import identify_type
        by_tan = {a.get("pan", "").upper(): a for a in self.assessee_list
                  if identify_type(a.get("pan", "")) == "TAN"}
        targets = []
        for row in rows:
            client = by_tan.get(row.get("tan", "").upper())
            if not client:
                self.log(f"[Warning] Skipping {row.get('tan')} — no matching TAN client in the vault.")
                continue
            targets.append({**client, "_tds_row": row})
        if not targets:
            QMessageBox.warning(self, "Nothing to Generate",
                                "None of the TDS rows matched a TAN client in the vault.")
            return

        self._tds_challan_running = True
        self._tds_challan_aborted = False
        self._clear_log()
        if hasattr(self, "_tray_send_act"):
            self._tray_send_act.setVisible(True)

        output_dir = self.dir_lbl.text()
        self.log(f"[System] Starting TDS/TCS challan generation — {len(targets)} row(s) | "
                 f"TY {year_label} | Output: {output_dir}")
        self._show_tds_challan_progress_signal.emit(
            targets, f"TY {year_label}", "TDS/TCS (Act 2025)", output_dir)
        threading.Thread(
            target=self._run_tds_challan_wrapper,
            args=(targets, year_label, output_dir), daemon=True).start()

    def _show_tds_challan_progress_dialog(self, targets, year_display, type_label, output_dir):
        from ui.dialogs import ChallanGenerationProgressDialog
        self._tds_challan_progress_dialog = ChallanGenerationProgressDialog(
            targets, year_display, type_label,
            stop_callback=self.stop_tds_challan_generation,
            tray_callback=self._tray_to_system_manual,
            output_dir=output_dir, parent=self, id_label="TAN")
        self._tds_challan_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._tds_challan_progress_dialog.show()
        self._tds_challan_progress_dialog.raise_()
        self._tds_challan_progress_dialog.activateWindow()

    def stop_tds_challan_generation(self):
        if not self._tds_challan_running:
            return
        self.log("[System] Abort requested (TDS/TCS challan generation)...")
        self._tds_challan_running = False
        self._tds_challan_aborted = True
        if self._tds_challan_task and self._tds_challan_loop:
            self._tds_challan_loop.call_soon_threadsafe(self._tds_challan_task.cancel)

    def _run_tds_challan_wrapper(self, targets, year_label, output_dir):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._tds_challan_loop = loop
        try:
            self._tds_challan_task = loop.create_task(
                self._execute_tds_challan_generation(targets, year_label, output_dir))
            loop.run_until_complete(self._tds_challan_task)
        except asyncio.CancelledError:
            self.log("[System] TDS/TCS challan generation cancelled.")
        except Exception as e:
            self.log(f"[System Error] TDS/TCS challan generation crashed: {e}")
        finally:
            self._tds_challan_task = None
            self._tds_challan_loop = None
            loop.close()
            self._tds_challan_running = False
            if self._tds_challan_progress_dialog:
                self._tds_challan_progress_dialog.batch_finished()
            self._tds_challan_done_signal.emit()

    async def _execute_tds_challan_generation(self, targets, year_label, output_dir):
        from automation.challan_generator_tds import generate_tds_challan

        def set_status(row_index, text):
            if self._tds_challan_progress_dialog:
                self._tds_challan_progress_dialog.set_status(row_index, text)

        try:
            interactive = not self.chk_headless.isChecked()
            context = await browser_manager.get_context(log_callback=self.log, interactive=interactive)
        except Exception as e:
            self.log(f"[System Error] Browser init failed: {e}")
            return

        results = []
        processed = set()
        try:
            for i, target in enumerate(targets):
                if not self._tds_challan_running:
                    self.log("[System] Aborted.")
                    break
                tan = target.get("pan", "")
                name = target.get("name", "")
                row = dict(target.get("_tds_row", {}))
                row["tan"] = tan
                row["name"] = name
                self.log("──────────────────────────────────────────────────")
                self.log(f"[{i+1}/{len(targets)}] {name} ({tan})")

                name_safe = "".join(c if c.isalnum() or c in " _-" else "" for c in name)
                client_year_dir = os.path.join(
                    output_dir, f"{tan}-{name_safe}", f"TY_{year_label.replace('-', '_')}")
                set_status(i, "⏳ Logging in to ITD...")
                page = None
                try:
                    page = await login_itd(tan, target.get("password"), self.log, context,
                                           is_running=lambda: self._tds_challan_running)
                    set_status(i, "⏳ Navigating to e-Pay Tax...")
                    result = await generate_tds_challan(
                        page, year_label, row, client_year_dir, self.log)
                    results.append(result)
                    processed.add(i)
                    if result["status"] == "generated":
                        set_status(i, f"✅ Generated — CRN {result['crn']}")
                        if self._tds_challan_progress_dialog and result.get("artifact_path"):
                            self._tds_challan_progress_dialog.set_artifact_path(
                                i, result["artifact_path"])
                    else:
                        set_status(i, f"❌ Failed — {result['reason']}")
                except Exception as e:
                    self.log(f"[Error] {name}: {e}")
                    set_status(i, f"❌ Failed — {e}")
                    results.append({
                        "tan": tan, "name": name, "portal_year_label": year_label,
                        "sections": row.get("sections", []), "total_amount": 0,
                        "payment_mode": row.get("payment_mode", ""), "bank": row.get("bank", ""),
                        "drawee_bank": row.get("drawee_bank", ""), "crn": "", "valid_till": "",
                        "status": "failed", "reason": str(e), "artifact_path": "",
                    })
                    processed.add(i)
                finally:
                    if page:
                        try:
                            await logout_itd(page, self.log)
                        except Exception:
                            pass
        except asyncio.CancelledError:
            self.log("[System] TDS/TCS challan generation stopped by user.")
        finally:
            for idx in range(len(targets)):
                if idx not in processed:
                    set_status(idx, "⏹ Stopped")
            try:
                report_path = self._write_tds_challan_summary(results, output_dir, year_label)
                if report_path and self._tds_challan_progress_dialog:
                    self._tds_challan_progress_dialog.set_report_path(report_path)
            except Exception as e:
                self.log(f"[Warning] Could not write TDS challan summary: {e}")

    def _write_tds_challan_summary(self, results, output_dir, year_label):
        from automation.challan_fields import TDS_SUMMARY_COLUMNS
        from openpyxl import Workbook
        import datetime as _dt

        os.makedirs(output_dir, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(output_dir, f"TDS_Challans_Summary_{ts}.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.append(TDS_SUMMARY_COLUMNS)
        for r in results:
            secs = r.get("sections", []) or []
            codes = ", ".join(str(s.get("section_code", "")) for s in secs)
            ws.append([
                r.get("tan", ""), r.get("name", ""), r.get("portal_year_label", ""),
                "Other than Company", "Resident", codes, r.get("total_amount", 0),
                r.get("payment_mode", ""), r.get("bank", ""), r.get("drawee_bank", ""),
                r.get("crn", ""), r.get("valid_till", ""), r.get("status", ""),
                r.get("reason", ""), r.get("artifact_path", ""),
            ])
        wb.save(path)
        self.log(f"[System] TDS challan summary written: {path}")
        return path

    def _on_tds_challan_batch_done(self):
        self.log("[System] TDS/TCS challan generation idle.")
        if hasattr(self, "_tray_send_act") and not self.is_running:
            self._tray_send_act.setVisible(False)
        self.refresh_grid()

    # ── F-8: Download TDS/TCS Challans ───────────────────────────────────────

    def _open_download_tds_challans_dialog(self):
        if self.is_running:
            return
        from ui.dialogs import DownloadTdsChallansDialog
        dlg = DownloadTdsChallansDialog(self, self.vault, self._ay_entries)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.start_tds_challan_download(dlg.selected_clients, dlg.year_labels)

    def start_tds_challan_download(self, targets: list, year_labels: list):
        """Same batch pipeline as the Income Tax downloads, restricted to the
        TAN clients/years picked on the TDS hub. handle_challans() is
        identity-agnostic, so no portal code changes are involved."""
        if self.is_running:
            return
        if not targets:
            return
        year_specs = []
        for ay_label in year_labels:
            ay, fy, year_type, form_type = self._resolve_ay_fy(ay_label)
            if not ay:
                self.log(f"[Warning] Skipping unresolvable year: {ay_label}")
                continue
            year_specs.append({
                "ay_label": ay_label, "value": ay, "fy": fy,
                "year_type": year_type, "form_type": form_type,
            })
        if not year_specs:
            QMessageBox.warning(self, "Invalid", "None of the selected years could be resolved.")
            return

        selected_docs = {"tds_challans"}
        self.is_running = True
        self._batch_aborted = False
        self._batch_filing_scope = "all"
        self._lock_ui(True)
        self._clear_log()

        output_dir = self.dir_lbl.text()
        self._last_batch_params = (year_specs, output_dir, selected_docs)
        self.btn_run.setText("⏳ Downloading...")

        years_desc = ", ".join(year_labels)
        self.log(f"[System] Starting TDS/TCS challan download — {len(targets)} client(s) | "
                 f"Year(s): {years_desc} | Output: {output_dir}")
        year_tag = years_desc if len(year_labels) <= 3 else f"{len(year_labels)} years"

        self._progress_id_label = "TAN"
        self._show_progress_signal.emit(targets, selected_docs, year_specs, output_dir, year_tag)
        if hasattr(self, "_tray_send_act"):
            self._tray_send_act.setVisible(True)
        if getattr(self, "chk_auto_minimise", None) and self.chk_auto_minimise.isChecked():
            QTimer.singleShot(800, lambda: self._tray_to_system(len(targets)))

        threading.Thread(
            target=self._run_wrapper,
            args=(targets, year_specs, output_dir, selected_docs),
            daemon=True).start()

    # ── F-67: ITR Processing Status ──────────────────────────────────────────

    def _open_return_status_dialog(self):
        """Menu entry point — opens the browse/filter/select window. The
        dialog itself calls back into start_return_status_check() below
        when the user actually wants to re-check something; it never runs
        Playwright itself."""
        ReturnStatusDialog(self, self.vault, self._ay_entries).exec()

    def start_return_status_check(self, ay_value: str, targets: list, on_done=None):
        """Called by ReturnStatusDialog with the clients/AY the user picked
        and checked. `on_done` is a plain callback (not a Qt signal) —
        _on_return_status_batch_done invokes it once the batch actually
        finishes, safely on the main thread, since that method is itself
        only ever reached via _return_status_done_signal."""
        if not targets:
            return
        if self._retstatus_running:
            QMessageBox.information(self, "Already Running",
                                     "A status check is already in progress.")
            return
        self._retstatus_running = True
        self._retstatus_aborted = False
        self._retstatus_on_done = on_done
        self.log(f"[System] Starting ITR Processing Status check — {len(targets)} client(s) | AY {ay_value}")
        self._show_return_status_progress_signal.emit(targets, ay_value)
        threading.Thread(
            target=self._run_return_status_wrapper,
            args=(targets, ay_value), daemon=True).start()

    def _show_return_status_progress_dialog(self, targets: list, ay_value: str):
        self._retstatus_progress_dialog = ReturnStatusProgressDialog(
            targets, ay_value, stop_callback=self.stop_return_status_check, parent=self)
        self._retstatus_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._retstatus_progress_dialog.show()
        self._retstatus_progress_dialog.raise_()
        self._retstatus_progress_dialog.activateWindow()

    def stop_return_status_check(self):
        if not self._retstatus_running:
            return
        self.log("[System] Abort requested (ITR Processing Status check)...")
        self._retstatus_running = False
        self._retstatus_aborted = True
        if self._retstatus_task and self._retstatus_loop:
            self._retstatus_loop.call_soon_threadsafe(self._retstatus_task.cancel)

    def _run_return_status_wrapper(self, targets, ay_value):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._retstatus_loop = loop
        try:
            self._retstatus_task = loop.create_task(
                self._execute_return_status_check(targets, ay_value))
            loop.run_until_complete(self._retstatus_task)
        except asyncio.CancelledError:
            self.log("[System] ITR Processing Status check cancelled.")
        except Exception as e:
            self.log(f"[System Error] ITR Processing Status check crashed: {e}")
        finally:
            self._retstatus_task = None
            self._retstatus_loop = None
            loop.close()
            self._retstatus_running = False
            if self._retstatus_progress_dialog:
                self._retstatus_progress_dialog.batch_finished()
            self._return_status_done_signal.emit()

    async def _execute_return_status_check(self, targets, ay_value):
        from automation.return_status import check_return_status

        def set_status(row_index, text):
            if self._retstatus_progress_dialog:
                self._retstatus_progress_dialog.set_status(row_index, text)

        try:
            interactive = not self.chk_headless.isChecked()
            context = await browser_manager.get_context(log_callback=self.log, interactive=interactive)
        except Exception as e:
            self.log(f"[System Error] Browser init failed: {e}"); return

        processed_indices = set()
        try:
            for i, target in enumerate(targets):
                if not self._retstatus_running:
                    self.log("[System] Aborted."); break

                pan = target.get("pan", "")
                name = target.get("name", "")
                dob = target.get("dob", "")
                self.log("──────────────────────────────────────────────────")
                self.log(f"[{i+1}/{len(targets)}] {name}")
                set_status(i, "⏳ Logging in to ITD...")

                page = None
                try:
                    page = await login_itd(pan, target.get("password"), self.log, context,
                                            is_running=lambda: self._retstatus_running)
                    set_status(i, "⏳ Checking status...")
                    result = await check_return_status(page, ay_value, self.log, pan=pan, dob=dob)
                    processed_indices.add(i)

                    if result["ok"]:
                        self.vault.record_return_status(
                            pan, ay_value, result["status"],
                            status_date=result.get("status_date", ""),
                            filing_date=result.get("filing_date", ""),
                            ack_no=result.get("ack_no", ""),
                            filed=result.get("filed"),
                            section=result.get("section", ""),
                            revised=result.get("revised"),
                            revised_section=result.get("revised_section", ""),
                            rectified=result.get("rectified"),
                            e_verified=result.get("e_verified"),
                            processed=result.get("processed"),
                            refund_status=result.get("refund_status", ""))
                        status_display = result["status"]
                        if result.get("status_date"):
                            status_display += f" ({result['status_date']})"
                        set_status(i, f"✅ {status_display}")
                    else:
                        set_status(i, f"❌ {result['reason']}")
                except Exception as e:
                    self.log(f"[Error] {name}: {e}")
                    set_status(i, f"❌ Failed — {e}")
                    processed_indices.add(i)
                finally:
                    if page:
                        try:
                            await logout_itd(page, self.log)
                        except Exception:
                            pass
        except asyncio.CancelledError:
            self.log("[System] ITR Processing Status check stopped by user.")
        finally:
            for idx in range(len(targets)):
                if idx not in processed_indices:
                    set_status(idx, "⏹ Stopped")

    def _on_return_status_batch_done(self):
        self.log("[System] ITR Processing Status check idle.")
        cb = self._retstatus_on_done
        self._retstatus_on_done = None
        if cb:
            cb()

    def skip_client(self):
        """Signal the batch runner to skip the currently-downloading client."""
        self._skip_current = True

    def stop_automation(self):
        if not self.is_running:
            return
        _sm = _t()
        _mb = QMessageBox(self)
        _mb.setWindowTitle("Stop")
        _mb.setText("Abort the active batch?")
        _mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        _mb.setDefaultButton(QMessageBox.StandardButton.No)
        _mb.setStyleSheet(
            f"QMessageBox{{background:{_sm.bg_window};color:{_sm.text_primary};}}"
            f"QLabel{{color:{_sm.text_primary};background:transparent;}}"
            f"QPushButton{{background:{_sm.accent};color:{_sm.accent_text};border:none;"
            f"border-radius:5px;padding:6px 18px;font-size:12px;}}"
            f"QPushButton:hover{{background:{_sm.accent_hover};}}"
            f"QPushButton[text='No']{{background:{_sm.border};color:{_sm.text_primary};}}"
        )
        if _mb.exec() == QMessageBox.StandardButton.Yes:
            self.log("[System] Abort requested...")
            self.is_running = False
            self._batch_aborted = True
            # Cancel the asyncio task immediately — raises CancelledError into
            # whatever await is currently blocking (goto, wait_for_selector, sleep…)
            if self._batch_task and self._batch_loop:
                self._batch_loop.call_soon_threadsafe(self._batch_task.cancel)

    def resume_batch(self, remaining_targets: list):
        """Called from the dialog Resume button — restart batch with unfinished clients."""
        if not self._last_batch_params or not remaining_targets:
            return
        year_specs, root_dir, selected_docs = self._last_batch_params
        self.is_running = True
        self._batch_aborted = False
        self._lock_ui(True)
        self.btn_run.setText("⏳ Downloading...")
        self.log(f"[System] Resuming — {len(remaining_targets)} client(s) remaining...")
        if self._progress_dialog:
            self._progress_dialog.batch_resumed()
        threading.Thread(
            target=self._run_wrapper,
            args=(remaining_targets, year_specs, root_dir, selected_docs),
            daemon=True).start()

    # ── Scheduled e-Proceedings auto-fetch (F-13) ─────────────────────────────

    def _eproc_auto_init_timer(self):
        from automation.eproc_scheduler import compute_next_run
        self._eproc_auto_timer = QTimer(self)
        self._eproc_auto_timer.setInterval(60_000)
        self._eproc_auto_timer.timeout.connect(self._eproc_auto_tick)
        self._eproc_auto_timer.start()
        cfg = self.vault.get_eproc_autofetch_config()
        if cfg["enabled"] and not cfg.get("next_run_at"):
            nxt = compute_next_run(datetime.datetime.now(), cfg)
            cfg["next_run_at"] = nxt.isoformat(timespec="seconds") if nxt else ""
            self.vault.save_eproc_autofetch_config(cfg)
            self._refresh_eproc_autofetch_summary()

    def _eproc_auto_tick(self):
        if getattr(self, "_eproc_auto_running", False):
            return
        if self.is_running or self._challan_running or self._tds_challan_running or self._retstatus_running:
            return
        from automation.eproc_scheduler import is_due
        cfg = self.vault.get_eproc_autofetch_config()
        if not cfg["enabled"]:
            return
        if not is_due(datetime.datetime.now(), cfg):
            return
        self._eproc_auto_start(cfg)

    def _eproc_auto_year_spec(self):
        labels = []
        try:
            labels = self.ay_combo.checked_labels()
        except Exception:
            labels = []
        if not labels:
            labels = [e["label"] for e in self._ay_entries if e.get("enabled", True)]
        for label in labels:
            ay, fy, year_type, form_type = self._resolve_ay_fy(label)
            if ay:
                return {"ay_label": label, "value": ay, "fy": fy,
                        "year_type": year_type, "form_type": form_type}
        return None

    def _eproc_auto_token(self, pan: str) -> str:
        return pan[:3] + "XXXXXXX" if pan and len(pan) >= 3 else "UNKNOWN"

    def _eproc_auto_client_dir(self, target: dict, output_dir: str, spec: dict) -> str:
        pan = target.get("pan", "")
        name_safe = "".join(c if c.isalnum() or c in " _-" else "" for c in target.get("name", ""))
        return os.path.join(
            output_dir, f"{pan}-{name_safe}",
            f"{spec['year_type']}_{spec['value'].replace('-', '_')}")

    def _eproc_auto_start(self, cfg=None, clients_override=None):
        from automation.eproc_scheduler import build_queue
        if getattr(self, "_eproc_auto_running", False):
            return
        if self.is_running or self._challan_running or self._tds_challan_running or self._retstatus_running:
            return
        cfg = dict(cfg or self.vault.get_eproc_autofetch_config())
        all_clients = self.vault.get_all_assessees()
        if clients_override is None:
            clients, cfg = build_queue(all_clients, cfg)
        else:
            blocked = self.vault.get_credential_invalid()
            clients = [c for c in clients_override
                       if str(c.get("pan", "")).upper() not in blocked]
            cfg["queue_remaining"] = []
        if not clients:
            self.log("[Auto-Fetch] No clients in scope or queue is empty.")
            self._eproc_auto_schedule_next(cfg)
            return
        spec = self._eproc_auto_year_spec()
        if spec is None:
            self.log("[Auto-Fetch] No enabled Assessment/Tax Year is available.")
            self._eproc_auto_schedule_next(cfg)
            return

        output_dir = self.dir_lbl.text() or self.vault.get_setting("download_root_dir", "")
        pending = [str(c.get("pan", "")).upper() for c in clients if str(c.get("pan", "")).strip()]
        tail = list(cfg.get("queue_remaining") or [])
        cfg["queue_remaining"] = pending + tail
        self.vault.save_eproc_autofetch_config(cfg)

        self._eproc_auto_cfg = cfg
        self._eproc_auto_run_clients = list(clients)
        self._eproc_auto_pending = pending
        self._eproc_auto_tail = tail
        self._eproc_auto_paths = {}
        self._eproc_auto_counts = {"synced": 0, "failed": 0, "skipped": 0,
                                   "flagged": 0, "timeouts": 0}
        self._eproc_auto_running = True
        self._eproc_auto_aborted = False
        self._eproc_auto_paused = False
        self._eproc_auto_skip_current = False
        self._eproc_auto_skip_future = False
        self._eproc_auto_restart = False
        self._eproc_auto_stop_keeps = None
        self._eproc_auto_started_at = datetime.datetime.now()

        self._eproc_auto_dialog = BatchProgressDialog(
            clients, {"e_proceedings"}, year_specs=[spec],
            ay="e-Proceedings Auto-Fetch",
            stop_callback=self._eproc_auto_stop,
            skip_callback=self._eproc_auto_skip_client,
            tray_callback=self._tray_to_system_manual,
            output_dir=output_dir, parent=self,
            pause_callback=self._eproc_auto_pause,
            resume_pause_callback=self._eproc_auto_resume_pause,
            restart_callback=self._eproc_auto_restart_run,
            skip_future_callback=self._eproc_auto_skip_future_clients)
        self._eproc_auto_dialog.show()
        self._eproc_auto_dialog.raise_()

        for client in clients:
            key = (client.get("pan", ""), spec["ay_label"])
            path = os.path.join(self._eproc_auto_client_dir(client, output_dir, spec), "e-Proceedings")
            self._eproc_auto_paths[key] = path
            self._eproc_auto_dialog.set_client_path(client.get("pan", ""), spec["ay_label"], path)

        self.log(f"[Auto-Fetch] Starting — {len(clients)} client(s), "
                 f"run time {cfg['run_time']}, mode {cfg['distribution']}.")
        threading.Thread(target=self._eproc_auto_worker,
                         args=(clients, [spec], output_dir),
                         daemon=True).start()

    def _eproc_auto_worker(self, clients, year_specs, output_dir):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._eproc_auto_loop = loop

        def _exc_handler(loop, ctx):
            exc = ctx.get("exception")
            if exc is not None and type(exc).__name__ in (
                    "TargetClosedError", "ConnectionClosedError", "CancelledError"):
                return
            loop.default_exception_handler(ctx)

        loop.set_exception_handler(_exc_handler)
        try:
            self._eproc_auto_task = loop.create_task(
                self._eproc_auto_run(clients, year_specs, output_dir))
            loop.run_until_complete(self._eproc_auto_task)
        except asyncio.CancelledError:
            self.log("[Auto-Fetch] Run cancelled.")
        except Exception as exc:
            self.log(f"[Auto-Fetch] Run crashed: {exc}")
        finally:
            self._eproc_auto_task = None
            self._eproc_auto_loop = None
            loop.close()
            self._eproc_auto_done_signal.emit()

    async def _eproc_auto_run(self, clients, year_specs, output_dir):
        from automation.eproc_scheduler import cooldown_for
        context = None
        try:
            interactive = not self.chk_headless.isChecked()
            context = await browser_manager.get_context(
                log_callback=self.log, interactive=interactive)
            for index, target in enumerate(clients):
                if not self._eproc_auto_running or self._eproc_auto_skip_future:
                    break
                if self._eproc_auto_budget_used():
                    self.log("[Auto-Fetch] Run time budget reached — stopping.")
                    self._eproc_auto_aborted = True
                    break
                pan = str(target.get("pan", "")).upper()
                if pan in self.vault.get_credential_invalid():
                    self._eproc_auto_counts["flagged"] += 1
                    self._eproc_auto_set_status(
                        pan, year_specs[0]["ay_label"],
                        "⚠ Password needs update — skipped")
                    self._eproc_auto_mark_processed(pan)
                    if self._eproc_auto_dialog is not None:
                        self._eproc_auto_dialog.client_finished(pan, year_specs[0]["ay_label"])
                    continue
                self._eproc_auto_skip_current = False
                processed = await self._eproc_auto_sync_client(
                    context, target, year_specs, output_dir, self._eproc_auto_cfg)
                if processed:
                    self._eproc_auto_mark_processed(pan)
                    if self._eproc_auto_dialog is not None:
                        self._eproc_auto_dialog.client_finished(pan, year_specs[0]["ay_label"])
                if index < len(clients) - 1 and self._eproc_auto_running and not self._eproc_auto_skip_future:
                    seconds = cooldown_for(
                        self._eproc_auto_cfg["client_cooldown_sec"],
                        self._eproc_auto_cfg["jitter_sec"])
                    await self._eproc_auto_wait(seconds, "Next client in")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.log(f"[Auto-Fetch] Error: {exc}")
        finally:
            if context is not None:
                try:
                    await browser_manager.close()
                except Exception:
                    pass

    async def _eproc_auto_sync_client(self, context, target, year_specs, output_dir, cfg):
        from automation.batch_handlers import handle_e_proceedings
        from automation.eproc_scheduler import cooldown_for, is_timeout, should_backoff

        pan = str(target.get("pan", "")).upper()
        name = target.get("name", "")
        spec = year_specs[0]
        ay_label = spec["ay_label"]
        token = self._eproc_auto_token(pan)
        attempts = int(cfg["timeout_retries"]) + 1

        def _out_for_year(year_type, value, _root=output_dir, _pan=pan,
                          _name_safe="".join(c if c.isalnum() or c in " _-" else ""
                                             for c in name)):
            return os.path.join(_root, f"{_pan}-{_name_safe}",
                                f"{year_type}_{value.replace('-', '_')}")

        for attempt in range(attempts):
            if not self._eproc_auto_running or self._eproc_auto_skip_future:
                return False
            page = None
            last_status = {}
            try:
                self._eproc_auto_set_status(pan, ay_label, "⏳ Logging in to ITD...")
                page = await login_itd(
                    pan, target.get("password"), self.log, context,
                    is_running=lambda: (self._eproc_auto_running
                                        and not self._eproc_auto_skip_current
                                        and not self._eproc_auto_skip_future))
                if self._eproc_auto_skip_current:
                    self._eproc_auto_counts["skipped"] += 1
                    self._eproc_auto_set_status(pan, ay_label, "⬜ Skipped")
                    return True

                def _set_status(pan_, ay_, text_):
                    last_status[ay_] = text_
                    self._eproc_auto_set_status(pan_, ay_, text_)

                async def _doc_delay():
                    seconds = cooldown_for(cfg["doc_cooldown_sec"], cfg["jitter_sec"])
                    if seconds:
                        await self._eproc_auto_wait(seconds, "Next document in")

                await handle_e_proceedings(
                    page, pan, target.get("dob", ""), year_specs,
                    _out_for_year, self.log, _set_status,
                    filing_scope="all",
                    is_running=lambda: (self._eproc_auto_running
                                        and not self._eproc_auto_skip_future
                                        and not self._eproc_auto_skip_current),
                    doc_delay=_doc_delay)

                if self._eproc_auto_skip_current:
                    self._eproc_auto_counts["skipped"] += 1
                    self._eproc_auto_set_status(pan, ay_label, "⬜ Skipped")
                elif any(str(v).startswith("❌") for v in last_status.values()):
                    self._eproc_auto_counts["failed"] += 1
                else:
                    self._eproc_auto_counts["synced"] += 1
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                text = str(exc)
                if self._eproc_auto_skip_current or self._eproc_auto_skip_future:
                    self._eproc_auto_counts["skipped"] += 1
                    self._eproc_auto_set_status(pan, ay_label, "⬜ Skipped")
                    return True
                if not self._eproc_auto_running:
                    return False
                if self._eproc_auto_is_credential_error(text):
                    self.vault.set_client_credential_invalid(pan, True)
                    self._eproc_auto_counts["flagged"] += 1
                    self._eproc_auto_set_status(pan, ay_label, "⚠ Password needs update")
                    self.log(f"[Auto-Fetch] {token} needs a password update — "
                             f"auto-fetch will skip this client until it is updated.")
                    notify_windows("AayDocCapio — Password needs update",
                                   f"{name or token}: portal login failed. Update the password; "
                                   f"auto-fetch will skip this client until then.")
                    return True
                if should_backoff(text):
                    self._eproc_auto_set_backoff()
                    self._eproc_auto_counts["failed"] += 1
                    self._eproc_auto_set_status(pan, ay_label, "❌ Portal rate limit — backing off")
                    self._eproc_auto_aborted = True
                    self._eproc_auto_running = False
                    self.log("[Auto-Fetch] Portal rate-limit signal — run stopped and back-off applied.")
                    return False
                if is_timeout(text) and attempt < attempts - 1:
                    self._eproc_auto_counts["timeouts"] += 1
                    self.log(f"[Auto-Fetch] {token} timed out — retry "
                             f"{attempt + 1}/{attempts - 1}.")
                    self._eproc_auto_set_status(pan, ay_label, "🕐 Timed out — retrying...")
                    seconds = cooldown_for(
                        cfg["client_cooldown_sec"], cfg["jitter_sec"])
                    await self._eproc_auto_wait(seconds, "Retry in")
                    continue
                self._eproc_auto_counts["failed"] += 1
                self._eproc_auto_set_status(pan, ay_label, f"❌ Failed — {_friendly_error(text)}")
                self.log(f"[Auto-Fetch] {token} failed: {text}")
                return False
            finally:
                if page is not None:
                    try:
                        await logout_itd(page, self.log)
                    except Exception:
                        pass

    async def _eproc_auto_wait(self, seconds, label):
        from automation.eproc_scheduler import format_countdown, interruptible_sleep
        if seconds <= 0:
            return True

        def _tick(remaining, paused):
            dialog = self._eproc_auto_dialog
            if dialog is None:
                return
            if paused:
                dialog.set_countdown("Paused — press Resume to continue.")
            else:
                dialog.set_countdown(f"{label} {format_countdown(remaining)}")

        return await interruptible_sleep(
            seconds,
            should_continue=lambda: self._eproc_auto_running and not self._eproc_auto_skip_future,
            is_paused=lambda: self._eproc_auto_paused,
            on_tick=_tick)

    def _eproc_auto_budget_used(self) -> bool:
        if self._eproc_auto_started_at is None:
            return False
        minutes = (datetime.datetime.now() - self._eproc_auto_started_at).total_seconds() / 60
        return minutes >= self._eproc_auto_cfg.get("run_budget_min", 60)

    def _eproc_auto_set_status(self, pan, ay_label, text):
        dialog = self._eproc_auto_dialog
        if dialog is not None:
            dialog.set_status(pan, ay_label, text)
        terminal = ("✅", "❌", "🕐", "⏹", "⬜", "⚠")
        if ay_label and any(text.startswith(p) for p in terminal):
            try:
                self.vault.record_download(
                    pan, ay_label, "e_proceedings", text,
                    self._eproc_auto_paths.get((pan, ay_label), ""))
            except Exception:
                pass

    def _eproc_auto_mark_processed(self, pan):
        pan = str(pan).upper()
        if pan in self._eproc_auto_pending:
            self._eproc_auto_pending.remove(pan)
        cfg = self.vault.get_eproc_autofetch_config()
        cfg["queue_remaining"] = self._eproc_auto_pending + self._eproc_auto_tail
        self.vault.save_eproc_autofetch_config(cfg)
        self._eproc_auto_cfg = cfg

    def _eproc_auto_set_backoff(self):
        cfg = self.vault.get_eproc_autofetch_config()
        until = datetime.datetime.now() + datetime.timedelta(minutes=cfg["backoff_min"])
        cfg["backoff_until"] = until.isoformat(timespec="seconds")
        cfg["queue_remaining"] = self._eproc_auto_pending + self._eproc_auto_tail
        self.vault.save_eproc_autofetch_config(cfg)
        self._eproc_auto_cfg = cfg

    def _eproc_auto_schedule_next(self, cfg):
        from automation.eproc_scheduler import compute_next_run
        now = datetime.datetime.now()
        backoff = cfg.get("backoff_until") or ""
        next_run = None
        if backoff:
            try:
                until = datetime.datetime.fromisoformat(backoff)
            except ValueError:
                until = None
            if until is not None and until > now:
                same_day = cfg["on_backoff_action"] == "resume_same_evening"
                if same_day and until.date() == now.date() and now.weekday() in cfg["active_days"]:
                    next_run = until
                else:
                    next_run = compute_next_run(until, cfg)
        if next_run is None:
            next_run = compute_next_run(now, cfg)
        cfg["next_run_at"] = next_run.isoformat(timespec="seconds") if next_run else ""
        self.vault.save_eproc_autofetch_config(cfg)
        self._refresh_eproc_autofetch_summary()

    @staticmethod
    def _eproc_auto_is_credential_error(text: str) -> bool:
        low = str(text).lower()
        return any(marker in low for marker in (
            "authentication failed", "2fa", "otp", "account locked"))

    def _eproc_auto_cancel_task(self):
        if self._eproc_auto_task is not None and self._eproc_auto_loop is not None:
            try:
                self._eproc_auto_loop.call_soon_threadsafe(self._eproc_auto_task.cancel)
            except Exception:
                pass

    def _eproc_auto_stop(self):
        if not self._eproc_auto_running:
            return
        cfg = self.vault.get_eproc_autofetch_config()
        mb = QMessageBox(self)
        mb.setWindowTitle("Stop Auto-Fetch")
        mb.setText("Stop the scheduled e-Proceedings sync?")
        mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        mb.setDefaultButton(QMessageBox.StandardButton.No)
        keep = QCheckBox("Keep the remaining clients for the next run")
        keep.setChecked(bool(cfg["stop_keeps_remainder"]))
        mb.setCheckBox(keep)
        if mb.exec() != QMessageBox.StandardButton.Yes:
            return
        self._eproc_auto_stop_keeps = keep.isChecked()
        self._eproc_auto_aborted = True
        self._eproc_auto_running = False
        self.log("[Auto-Fetch] Stop requested.")
        self._eproc_auto_cancel_task()

    def _eproc_auto_skip_client(self):
        self._eproc_auto_skip_current = True
        self.log("[Auto-Fetch] Skip current client requested.")

    def _eproc_auto_skip_future_clients(self):
        self._eproc_auto_skip_future = True
        self._eproc_auto_skip_current = True
        self.log("[Auto-Fetch] Remaining clients will be skipped.")

    def _eproc_auto_pause(self):
        self._eproc_auto_paused = True
        self.log("[Auto-Fetch] Paused.")

    def _eproc_auto_resume_pause(self):
        self._eproc_auto_paused = False
        self.log("[Auto-Fetch] Resumed.")

    def _eproc_auto_restart_run(self):
        if not self._eproc_auto_running:
            return
        self._eproc_auto_restart = True
        self._eproc_auto_running = False
        self._eproc_auto_cancel_task()
        self.log("[Auto-Fetch] Restart requested.")

    def _on_eproc_auto_done(self):
        was_aborted = self._eproc_auto_aborted
        restart = self._eproc_auto_restart
        self._eproc_auto_running = False
        dialog = self._eproc_auto_dialog
        self._eproc_auto_dialog = None
        if dialog is not None:
            try:
                dialog.batch_finished(aborted=was_aborted)
            except Exception:
                pass

        if restart:
            clients = list(self._eproc_auto_run_clients)
            cfg = self.vault.get_eproc_autofetch_config()
            if dialog is not None:
                dialog.accept()
            self._eproc_auto_restart = False
            self._eproc_auto_start(cfg, clients_override=clients)
            return

        cfg = self.vault.get_eproc_autofetch_config()
        cfg["last_run_finished"] = datetime.datetime.now().isoformat(timespec="seconds")
        cfg["last_run_summary"] = dict(self._eproc_auto_counts)
        keep_remaining = cfg["stop_keeps_remainder"]
        if self._eproc_auto_stop_keeps is not None:
            keep_remaining = self._eproc_auto_stop_keeps
        if self._eproc_auto_skip_future or (was_aborted and not keep_remaining):
            cfg["queue_remaining"] = []
        else:
            cfg["queue_remaining"] = self._eproc_auto_pending + self._eproc_auto_tail
        self._eproc_auto_schedule_next(cfg)
        counts = self._eproc_auto_counts
        self.log(f"[Auto-Fetch] Finished — {counts.get('synced', 0)} synced, "
                 f"{counts.get('failed', 0)} failed, {counts.get('flagged', 0)} password issue(s), "
                 f"{counts.get('skipped', 0)} skipped.")
        if not was_aborted:
            notify_windows(
                "AayDocCapio — Auto-Fetch Complete",
                f"{counts.get('synced', 0)} client(s) synced, "
                f"{counts.get('failed', 0)} failed, {counts.get('flagged', 0)} password issue(s).")

    def _run_wrapper(self, targets, year_specs, root_dir, selected_docs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._batch_loop = loop

        # Suppress "Future exception was never retrieved" noise from Playwright
        # futures that are orphaned when the browser closes mid-await after Stop.
        def _exc_handler(loop, ctx):
            exc = ctx.get("exception")
            if exc is not None:
                name = type(exc).__name__
                msg  = str(exc).lower()
                # Suppress orphaned futures from browser close / abort
                if name in ("TargetClosedError", "ConnectionClosedError",
                            "CancelledError"):
                    return
                # Playwright base Error with net:: abort codes that appear when
                # the browser is closed mid-navigation after Stop
                if name == "Error" and any(code in msg for code in (
                        "err_aborted", "err_empty_response",
                        "err_connection_reset", "err_connection_refused",
                        "target page, context or browser has been closed")):
                    return
            loop.default_exception_handler(ctx)

        loop.set_exception_handler(_exc_handler)

        try:
            self._batch_task = loop.create_task(
                self._execute_batch(targets, year_specs, root_dir, selected_docs))
            loop.run_until_complete(self._batch_task)
        except asyncio.CancelledError:
            self.log("[System] Batch cancelled.")
        except Exception as e:
            self.log(f"[System Error] Batch crashed: {e}")
        finally:
            self._batch_task = None
            self._batch_loop = None
            loop.close()
            self.is_running = False
            self._last_selected_docs = selected_docs
            if self._progress_dialog:
                self._progress_dialog.batch_finished(aborted=self._batch_aborted)
            self._batch_done_signal.emit()

    def _on_batch_done(self):
        import datetime
        self.btn_run.setText("  Downloads")
        self._lock_ui(False)
        self.log("[System] Engine Idle.")
        # Refresh grid so Last Download Status / Last Saved Location columns update
        QTimer.singleShot(200, self.refresh_grid)
        selected_docs = self._last_selected_docs
        run_label = " + ".join(DOC_TYPE_LABELS.get(d, d) for d in sorted(selected_docs)) or "Batch"

        # F-35: restore from tray if we were hidden there, and show tray balloon
        if hasattr(self, "_tray") and self._tray.isVisible():
            notify_windows("AayDocCapio — Download Complete",
                           f"{run_label} batch finished. Click the tray icon to restore.")
            if not self._challan_running:
                self._tray_stop_act.setEnabled(False)
                self._tray_send_act.setVisible(False)
            self._tray.setToolTip("AayDocCapio — Batch complete")
            # Auto-restore after balloon (small delay so user sees the notification)
        # F-35: Windows native toast — only when NOT using tray (tray has its own balloon)
        if not self._batch_aborted and not (hasattr(self, "_tray") and self._tray.isVisible()):
            notify_windows("AayDocCapio — Download Complete",
                           f"{run_label} batch run finished. Click to open the app.")

        if self._batch_aborted:
            self._ais_results = {}
            return

        if "request_ais" in selected_docs:
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
                    f"wait ~5 min then click ▶ Run → Download Previously Requested AIS for the {n_queued} queued client(s).")
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
                    f"and click <b>▶ Run → ⬇ Download Previously Requested AIS</b>.")
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

        if "ais_tis" in selected_docs:
            # Hide the status line once download is done
            self.ais_status_bar.setVisible(False)
            self._ais_requested_time = None

        if "26as" in selected_docs and not self._batch_aborted:
            pass  # conversion now happens inline per-client in _execute_batch

    def _convert_26as_manual(self):
        from automation.as26_converter import convert_26as_txt
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select 26AS TXT file(s)",
            self.vault.get_setting("download_root_dir", ""),
            "Text Files (*.txt);;All Files (*)")
        if not paths:
            return
        ok, fail = 0, 0
        locked_warnings = []  # collect "saved as alternate" warnings for the dialog

        def _log_capturing(msg):
            self.log(msg)
            if msg.startswith("[Warning]") and "was open in Excel" in msg:
                locked_warnings.append(msg[len("[Warning] "):])

        for p in paths:
            try:
                xlsx, html = convert_26as_txt(p, log_callback=_log_capturing)
                self.log(f"[Victory] Converted: {os.path.basename(xlsx)} + {os.path.basename(html)}")
                ok += 1
            except Exception as e:
                self.log(f"[Error] Convert failed for {os.path.basename(p)}: {e}")
                fail += 1
        msg = f"Converted {ok} file(s) — Excel + HTML saved alongside each TXT."
        if locked_warnings:
            msg += "\n\nNote — the following file(s) were open in Excel and saved under an alternate name:\n"
            msg += "\n".join(f"  • {w}" for w in locked_warnings)
        if fail:
            msg += f"\n\n{fail} file(s) failed — check the log for details."
        QMessageBox.information(self, "Convert Complete", msg)

    def _convert_ais_json_manual(self):
        from PyQt6.QtWidgets import (
            QFileDialog, QMessageBox, QDialog, QVBoxLayout,
            QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QFrame,
        )
        from ui.helpers import _lbl, _btn

        # ── Step 1: pick JSON file ────────────────────────────────────────
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select AIS JSON file(s)",
            self.vault.get_setting("download_root_dir", ""),
            "AIS JSON Files (*.json);;All Files (*)")
        if not paths:
            return

        # ── Step 2: credentials dialog ────────────────────────────────────
        clients = self.vault.get_all_assessees()

        dlg = QDialog(self)
        dlg.setWindowTitle("AIS JSON — Credentials")
        dlg.setFixedWidth(420)
        dlg.setModal(True)
        t = _t()
        dlg.setStyleSheet(
            f"QDialog{{background:{t.bg_window};}}"
            f"QLabel{{color:{t.text_primary};background:transparent;}}"
            f"QLineEdit{{border:1px solid {t.border};border-radius:6px;"
            f"padding:5px 10px;font-size:12px;background:{t.bg_input};"
            f"color:{t.text_primary};}}"
            f"QComboBox{{border:1px solid {t.border};border-radius:6px;"
            f"padding:4px 10px;font-size:12px;background:{t.bg_input};"
            f"color:{t.text_primary};}}"
            f"QComboBox::drop-down{{border:none;width:20px;}}"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        lay.addWidget(_lbl("Enter PAN and Date of Birth to decrypt the AIS JSON.", 11,
                           color=t.text_muted))

        # Vault shortcut — sorted, searchable combo
        sorted_clients = sorted(clients, key=lambda x: x.get("name", "").lower()) if clients else []

        if sorted_clients:
            from PyQt6.QtCore import Qt
            from PyQt6.QtWidgets import QCompleter

            combo_lbl = QLabel("Select from vault (optional):")
            combo_lbl.setStyleSheet("font-size:11px;font-weight:600;")
            lay.addWidget(combo_lbl)

            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.setMaxVisibleItems(12)
            combo.setFixedHeight(34)
            combo.addItem("", None)
            for c in sorted_clients:
                combo.addItem(f"{c['name']}  ({c['pan']})", c)

            completer = QCompleter([f"{c['name']}  ({c['pan']})" for c in sorted_clients])
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.popup().setStyleSheet(
                f"QListView{{background:{t.bg_input};color:{t.text_primary};"
                f"border:1px solid {t.border};border-radius:4px;"
                f"padding:2px;font-size:12px;}}"
                f"QListView::item{{padding:4px 8px;}}"
                f"QListView::item:hover{{background:{t.accent_light};color:{t.text_primary};}}"
                f"QListView::item:selected{{background:{t.accent};color:{t.accent_text};}}"
            )
            combo.setCompleter(completer)
            combo.lineEdit().setPlaceholderText("Type name or PAN to search…")
            combo.setCurrentIndex(-1)
            lay.addWidget(combo)

            sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"background:{t.border};border:none;max-height:1px;")
            lay.addWidget(sep)

        pan_lbl = QLabel("PAN:")
        pan_lbl.setStyleSheet("font-size:11px;font-weight:600;")
        lay.addWidget(pan_lbl)
        pan_edit = QLineEdit()
        pan_edit.setPlaceholderText("e.g. AABCP1234F")
        pan_edit.setFixedHeight(34)
        lay.addWidget(pan_edit)

        dob_lbl = QLabel("Date of Birth:")
        dob_lbl.setStyleSheet("font-size:11px;font-weight:600;")
        lay.addWidget(dob_lbl)
        dob_edit = QLineEdit()
        dob_edit.setPlaceholderText("DD-MM-YYYY  (e.g. 01-01-1980)")
        dob_edit.setFixedHeight(34)
        lay.addWidget(dob_edit)

        if sorted_clients:
            def _on_client_selected(idx):
                c = combo.itemData(idx)
                if c:
                    pan_edit.setText(c.get("pan", ""))
                    dob_edit.setText(c.get("dob", ""))
                else:
                    pan_edit.clear(); dob_edit.clear()
            combo.currentIndexChanged.connect(_on_client_selected)

            def _on_text_activated(text):
                idx = combo.findText(text)
                if idx >= 0:
                    _on_client_selected(idx)
            combo.lineEdit().editingFinished.connect(
                lambda: _on_text_activated(combo.currentText())
            )

        btn_row = QHBoxLayout()
        ok_btn = _btn("Convert", "primary", height=36)
        cancel_btn = _btn("Cancel", "secondary", height=36)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        pan_val = pan_edit.text().strip().upper()
        dob_val = dob_edit.text().strip()
        if not pan_val or not dob_val:
            QMessageBox.warning(self, "Missing Credentials",
                                "Please enter both PAN and Date of Birth.")
            return

        # ── Step 3: convert each file ─────────────────────────────────────
        from automation.ais_converter import convert_ais_json
        ok_files, fail_files = [], []

        for p in paths:
            try:
                xlsx = convert_ais_json(p, log_callback=self.log,
                                        pan=pan_val, dob=dob_val)
                self.log(f"[Victory] AIS converted: {os.path.basename(xlsx)}")
                ok_files.append(os.path.basename(xlsx))
            except ValueError:
                self.log(f"[Error] AIS decrypt failed for {os.path.basename(p)} "
                         f"— check PAN / DOB.")
                fail_files.append(os.path.basename(p))
            except Exception as e:
                self.log(f"[Error] AIS convert failed for {os.path.basename(p)}: {e}")
                fail_files.append(os.path.basename(p))

        msg = f"Converted {len(ok_files)} AIS JSON file(s) to Excel."
        if ok_files:
            msg += "\n\nSaved alongside source JSON:\n"
            msg += "\n".join(f"  • {f}" for f in ok_files)
        if fail_files:
            msg += f"\n\n{len(fail_files)} file(s) failed — check PAN / DOB and the log."
            msg += "\n" + "\n".join(f"  • {f}" for f in fail_files)
        QMessageBox.information(self, "AIS Convert Complete", msg)

    def _auto_convert_26as(self, set_status=None):
        from automation.as26_converter import convert_26as_txt
        items = getattr(self, "_batch_26as_txts", [])
        if not items:
            return
        converted = 0
        for pan, txt in items:
            if not os.path.exists(txt):
                continue
            if set_status:
                set_status(pan, "⏳ Converting to Excel...")
            try:
                convert_26as_txt(txt, log_callback=self.log)
                converted += 1
                if set_status:
                    set_status(pan, "✅ 26AS + Excel + HTML")
            except Exception as e:
                self.log(f"[Warning] Auto-convert failed for {os.path.basename(txt)}: {e}")
                if set_status:
                    set_status(pan, "⚠ Excel convert failed")
        if converted:
            self.log(f"[Victory] Auto-converted {converted} 26AS TXT file(s) to Excel + HTML.")

    async def _execute_batch(self, targets, year_specs, root_dir, selected_docs):
        selected_docs = set(selected_docs)
        years_desc = ", ".join(s["ay_label"] for s in year_specs)
        self.log(f"[System] Batch: {len(targets)} client(s) | Year(s): {years_desc} | Docs: {', '.join(sorted(selected_docs))}")
        self._ais_results = {}
        self._last_errors = {}
        self._batch_26as_txts = []

        _client_out      = {}   # (pan, ay_label) → out path, populated below
        _last_terminal   = {}   # (pan, ay_label) → last terminal status text this run
        _retried:  dict  = {}   # pan → True if already retried once
        _retry_queue     = []   # targets queued for one retry after main loop

        def _is_transient(err: str) -> bool:
            e = err.lower()
            return any(x in e for x in [
                "timeout", "assessmentyear", "could not find asses",
                "ais failed", "tis failed", "navigation", "net::",
            ])

        def set_status(pan, ay_label, text, doc_type=None):
            """Update progress dialog and persist terminal status to vault,
            keyed per (pan, ay_label, doc_type) so one document type's status
            can't overwrite another's, and one year can't overwrite another's,
            within a multi-select multi-year batch."""
            if self._progress_dialog:
                self._progress_dialog.set_status(pan, ay_label, text)
            terminal = ("✅", "❌", "🕐", "⏹", "⬜", "⚠")
            if ay_label and any(text.startswith(p) for p in terminal):
                key = (pan, ay_label)
                _last_terminal[key] = text
                if doc_type:
                    try:
                        self.vault.record_download(
                            pan, ay_label, doc_type, text, _client_out.get(key, ""))
                    except Exception:
                        pass

        try:
            interactive = not self.chk_headless.isChecked()
            context = await browser_manager.get_context(
                log_callback=self.log, interactive=interactive)
        except Exception as e:
            self.log(f"[System Error] Browser init failed: {e}"); return

        # Warm up the ITD portal before the first client — loads the Angular bundle,
        # CDN assets and sets session cookies so the first client's dashboard renders
        # at the same speed as subsequent clients.
        try:
            self.log("[System] Warming up ITD portal...")
            _warmup_page = await context.new_page()
            await _warmup_page.goto(
                "https://eportal.incometax.gov.in/iec/foservices/#/login",
                wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)
            await _warmup_page.close()
            self.log("[System] Portal warm-up done.")
        except Exception as _wu_err:
            self.log(f"[System] Portal warm-up skipped: {_wu_err}")

        try:
            for i, target in enumerate(targets):
                if not self.is_running:
                    self.log("[System] Aborted."); break

                pan  = target.get("pan", "")
                name = target.get("name", "")
                dob  = target.get("dob", "")
                self._skip_current = False   # reset skip flag for each new client
                if self._progress_dialog:
                    self._progress_dialog.client_started()
                self.log("──────────────────────────────────────────────────")
                self.log(f"[{i+1}/{len(targets)}] {name}")

                name_safe = "".join(c if c.isalnum() or c in " _-" else "" for c in name)

                def _out_for_year(year_type, value, _root=root_dir, _pan=pan, _name_safe=name_safe):
                    return os.path.join(_root, f"{_pan}-{_name_safe}", f"{year_type}_{value.replace('-','_')}")

                # Tell the progress dialog each year's save folder immediately
                for _spec in year_specs:
                    _out = _out_for_year(_spec["year_type"], _spec["value"])
                    _client_out[(pan, _spec["ay_label"])] = _out
                    if self._progress_dialog:
                        self._progress_dialog.set_client_path(pan, _spec["ay_label"], _out)

                page = None
                try:
                    # ── Login ────────────────────────────────────────────────────
                    for _spec in year_specs:
                        set_status(pan, _spec["ay_label"], "⏳ Logging in to ITD...")
                    page = await login_itd(pan, target.get("password"), self.log, context,
                                           is_running=lambda: self.is_running and not self._skip_current)
                    for _spec in year_specs:
                        set_status(pan, _spec["ay_label"], "⏳ Logged in to ITD")

                    # ── Skip check ───────────────────────────────────────────────
                    if self._skip_current:
                        # Update progress dialog only — do NOT persist to vault or log history
                        if self._progress_dialog:
                            for _spec in year_specs:
                                self._progress_dialog.set_status(pan, _spec["ay_label"], "⬜ Skipped")
                                self._progress_dialog.client_finished(pan, _spec["ay_label"])
                        self.log(f"[Skip] {pan[:3]}XXXXXXX skipped by user.")
                        if page:
                            try: await logout_itd(page, self.log)
                            except Exception: pass
                        page = None
                        await asyncio.sleep(1)
                        continue

                    # ── Selected document types, one client fully before the next ──
                    # Dispatch order is deterministic (not raw set iteration)
                    # so Filed Returns always runs before 26AS — see
                    # ordered_doc_types() docstring for why. Every doc type
                    # runs once per client and loops all selected years
                    # internally (F-14: doc-type-by-doc-type across years).
                    for doc_type in ordered_doc_types(selected_docs):
                        if not self.is_running:
                            break
                        handler = HANDLERS.get(doc_type)
                        if handler is None:
                            continue
                        doc_set_status = (lambda p, yl, t, _dt=doc_type: set_status(p, yl, t, _dt))
                        result = await handler(
                            page, pan, dob, year_specs, _out_for_year, self.log, doc_set_status,
                            filing_scope=getattr(self, "_batch_filing_scope", "all"),
                            is_running=(lambda: self.is_running),
                        ) or {}

                        if doc_type == "26as":
                            for _txt_path in (result.get("txt_paths") or {}).values():
                                self._batch_26as_txts.append((pan, _txt_path))
                        elif doc_type == "filed_returns":
                            # F-67 "kill two birds": persist whatever ITR
                            # processing status handle_filed_returns()
                            # already read while downloading, so a
                            # Downloads run also keeps the ITR Processing
                            # Status window's data fresh without a
                            # separate Check Processing Status pass.
                            for _ay_value, _status_info in (result.get("return_statuses") or {}).items():
                                try:
                                    self.vault.record_return_status(
                                        pan, _ay_value, _status_info.get("status", ""),
                                        status_date=_status_info.get("status_date", ""),
                                        filing_date=_status_info.get("filing_date", ""),
                                        ack_no=_status_info.get("ack_no", ""))
                                except Exception as _rs_err:
                                    self.log(f"[Warning] Could not save processing status for AY {_ay_value}: {_rs_err}")
                        elif doc_type == "request_ais":
                            for _ay_lbl, _ais_status in (result.get("ais_statuses") or {}).items():
                                _key = (pan, _ay_lbl)
                                if _ais_status == "downloaded":
                                    self._ais_results[_key] = "instant"
                                elif _ais_status == "requested":
                                    self._ais_results[_key] = "queued"
                                elif _ais_status == "skipped":
                                    self._ais_results[_key] = "skipped"
                                else:
                                    self._ais_results[_key] = "failed"

                    if self.is_running:
                        await logout_itd(page, self.log)
                        page = None

                    pan_masked = pan[:3] + "XXXXXXX" if pan and len(pan) >= 3 else "UNKNOWN"
                    self.log(f"[Victory] {pan_masked} done.")

                except Exception as e:
                    pan_masked = pan[:3] + "XXXXXXX" if pan and len(pan) >= 3 else "UNKNOWN"
                    self.log(f"[Error] {pan_masked}: {e}")
                    if _is_transient(str(e)) and not _retried.get(pan) and self.is_running:
                        # Transient error — logout cleanly and queue for one retry
                        _retried[pan] = True
                        self.log(f"[Retry] Transient error detected — will retry {pan_masked} after batch.")
                        for _spec in year_specs:
                            set_status(pan, _spec["ay_label"], f"🕐 Queued for retry — {_friendly_error(str(e))}")
                        if page:
                            try: await logout_itd(page, self.log)
                            except Exception: pass
                        _retry_queue.append(target)
                    else:
                        # Permanent failure or already retried
                        friendly = _friendly_error(str(e))
                        for _spec in year_specs:
                            _key = (pan, _spec["ay_label"])
                            self._ais_results[_key] = "failed"
                            self._last_errors[_key] = str(e)
                            if self._batch_aborted or friendly == "Stopped by user":
                                # Batch was stopped — do NOT overwrite last saved status in vault
                                if self._progress_dialog:
                                    self._progress_dialog.set_status(pan, _spec["ay_label"], f"⏹ Stopped")
                            else:
                                set_status(pan, _spec["ay_label"], f"❌ Failed — {friendly}")
                        if page:
                            try: await logout_itd(page, self.log)
                            except Exception: pass

                # Append the final status (whatever the main grid now shows) to log history
                for _spec in year_specs:
                    _key = (pan, _spec["ay_label"])
                    if _key in _last_terminal:
                        try:
                            self.log_store.record(pan, _spec["ay_label"], _last_terminal.pop(_key))
                        except Exception:
                            pass

                # This client's turn in the main loop is over — ALL its selected
                # doc types have now run (success, failure, or queued for retry)
                # for EVERY selected year. This is the only correct signal that
                # the progress dialog should count each (client, year) row as
                # done; a multi-select batch produces several terminal-looking
                # status updates per client along the way (one per doc type per
                # year), so those can no longer be used to infer "done".
                if self._progress_dialog:
                    for _spec in year_specs:
                        self._progress_dialog.client_finished(pan, _spec["ay_label"])

                await asyncio.sleep(3)

            # ── Retry pass — one attempt per transient-failed client ──────────
            if _retry_queue and self.is_running:
                self.log(f"[Retry] Retrying {len(_retry_queue)} client(s) that had transient errors...")
                for target in _retry_queue:
                    if not self.is_running:
                        break
                    pan  = target.get("pan", "")
                    name = target.get("name", "")
                    dob  = target.get("dob", "")
                    pan_masked = pan[:3] + "XXXXXXX" if pan and len(pan) >= 3 else "UNKNOWN"
                    self.log("──────────────────────────────────────────────────")
                    self.log(f"[Retry] {name}")
                    name_safe = "".join(c if c.isalnum() or c in " _-" else "" for c in name)

                    def _out_for_year(year_type, value, _root=root_dir, _pan=pan, _name_safe=name_safe):
                        return os.path.join(_root, f"{_pan}-{_name_safe}", f"{year_type}_{value.replace('-','_')}")

                    page = None
                    try:
                        for _spec in year_specs:
                            set_status(pan, _spec["ay_label"], "⏳ Logging in to ITD (retry)...")
                        page = await login_itd(pan, target.get("password"), self.log, context,
                                               is_running=lambda: self.is_running)

                        for doc_type in ordered_doc_types(selected_docs):
                            if not self.is_running:
                                break
                            handler = HANDLERS.get(doc_type)
                            if handler is None:
                                continue
                            doc_set_status = (lambda p, yl, t, _dt=doc_type: set_status(p, yl, t, _dt))
                            result = await handler(
                                page, pan, dob, year_specs, _out_for_year, self.log, doc_set_status,
                                filing_scope=getattr(self, "_batch_filing_scope", "all"),
                                is_running=(lambda: self.is_running),
                            ) or {}
                            if doc_type == "26as":
                                for _txt_path in (result.get("txt_paths") or {}).values():
                                    self._batch_26as_txts.append((pan, _txt_path))
                            elif doc_type == "filed_returns":
                                for _ay_value, _status_info in (result.get("return_statuses") or {}).items():
                                    try:
                                        self.vault.record_return_status(
                                            pan, _ay_value, _status_info.get("status", ""),
                                            status_date=_status_info.get("status_date", ""),
                                            filing_date=_status_info.get("filing_date", ""),
                                            ack_no=_status_info.get("ack_no", ""))
                                    except Exception as _rs_err:
                                        self.log(f"[Warning] Could not save processing status for AY {_ay_value}: {_rs_err}")
                            elif doc_type == "request_ais":
                                for _ay_lbl, _ais_status in (result.get("ais_statuses") or {}).items():
                                    self._ais_results[(pan, _ay_lbl)] = (
                                        "instant" if _ais_status == "downloaded"
                                        else "queued" if _ais_status == "requested"
                                        else "skipped" if _ais_status == "skipped"
                                        else "failed")

                        if self.is_running:
                            await logout_itd(page, self.log)
                        self.log(f"[Retry] {pan_masked} done.")
                    except Exception as e:
                        self.log(f"[Retry Error] {pan_masked}: {e}")
                        for _spec in year_specs:
                            _key = (pan, _spec["ay_label"])
                            self._ais_results[_key] = "failed"
                            self._last_errors[_key] = str(e)
                            set_status(pan, _spec["ay_label"], f"❌ Failed — {_friendly_error(str(e))}")
                        if page:
                            try: await logout_itd(page, self.log)
                            except Exception: pass

                    for _spec in year_specs:
                        _key = (pan, _spec["ay_label"])
                        if _key in _last_terminal:
                            try:
                                self.log_store.record(pan, _spec["ay_label"], _last_terminal.pop(_key))
                            except Exception:
                                pass
                    await asyncio.sleep(3)

        finally:
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


class _SplashScreen(QWidget):
    """Startup splash — the wordmark logo with a pulsing gold glow behind
    it, an animated "Starting AayDocCapio..." dot cycle, and fade in/out,
    shown while AayDocCapioApp() (imports Playwright, builds the full main
    window) is still constructing. Deliberately a plain QWidget rather than
    QSplashScreen — QSplashScreen has no easy way to layer a QGraphicsEffect
    or animate its own opacity, both needed here."""

    def __init__(self, pixmap: QPixmap):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 36, 40, 28)
        outer.setSpacing(12)

        logo_label = QLabel()
        logo_label.setPixmap(pixmap)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Soft gold glow (brand accent) behind the logo — pulses via the
        # blurRadius animation below rather than sitting static.
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setColor(QColor(_t().warning))
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(20)
        logo_label.setGraphicsEffect(self._glow)
        outer.addWidget(logo_label)

        self._status_label = QLabel("Starting AayDocCapio")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            f"color:{_t().text_muted};font-size:12px;background:transparent;")
        outer.addWidget(self._status_label)

        self.setFixedSize(pixmap.width() + 80, pixmap.height() + 96)
        self.setWindowOpacity(0.0)

        self._dot_count = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._tick_dots)
        self._dot_timer.start(450)

        # Pulse: one QPropertyAnimation loop, low -> high -> low blur, so
        # it reads as breathing rather than a static halo.
        self._glow_anim = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._glow_anim.setDuration(1400)
        self._glow_anim.setKeyValueAt(0.0, 18)
        self._glow_anim.setKeyValueAt(0.5, 55)
        self._glow_anim.setKeyValueAt(1.0, 18)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._glow_anim.setLoopCount(-1)
        self._glow_anim.start()

        self._fade_anim = None  # kept alive on self so it isn't GC'd mid-animation

    def _tick_dots(self):
        self._dot_count = (self._dot_count + 1) % 4
        self._status_label.setText("Starting AayDocCapio" + "." * self._dot_count)

    def fade_in(self):
        self.show()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(350)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._fade_anim = anim

    def finish(self, window):
        """Fades out and closes — named/shaped like QSplashScreen.finish()
        for a familiar call site, but doesn't block: the fade plays out
        during app.exec()'s own event loop instead of freezing startup."""
        self._dot_timer.stop()
        self._glow_anim.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(300)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self.close)
        anim.start()
        self._fade_anim = anim


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
    # Suppress harmless "unclosed transport" ResourceWarning noise on Windows
    # caused by asyncio ProactorEventLoop GC during shutdown.
    if sys.platform == "win32":
        import warnings
        warnings.filterwarnings("ignore", category=ResourceWarning,
                                message=".*unclosed transport.*")

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

    # Write a startup trace log using only builtins — before any Qt call
    _diag_path = os.path.join(_app_dir(), "startup_diag.log")
    def _diag(msg):
        try:
            os.makedirs(os.path.dirname(_diag_path), exist_ok=True)
            with open(_diag_path, "a", encoding="utf-8") as _f:
                _f.write(msg + "\n")
        except Exception:
            pass

    _diag(f"\n=== Startup {datetime.datetime.now()} ===")
    _diag(f"bundled_dir : {_bundled_dir()}")
    _diag(f"app_dir     : {_app_dir()}")
    _diag(f"sys.argv    : {sys.argv}")
    _diag(f"platform    : {sys.platform}")

    try:
        _diag("Step 1: QApplication()")
        # Suppress harmless font-db OpenType warnings from QFontComboBox scanning
        from PyQt6.QtCore import qInstallMessageHandler
        def _qt_msg_filter(msg_type, context, msg):
            if "OpenType support missing" in msg or "qt.text.font.db" in msg:
                return
            import sys as _sys
            _sys.stderr.write(msg + "\n")
        qInstallMessageHandler(_qt_msg_filter)
        app = QApplication(sys.argv)
        _diag("Step 1b: splash screen")
        # Shown immediately, before the (noticeably slower) font/theme/
        # AayDocCapioApp() construction steps below — those import
        # Playwright and build the full main window, which can take a
        # visible moment with nothing else on screen otherwise.
        splash = None
        _splash_shown_at = None
        _theme_pref_early = "light"
        try:
            # Read the "show splash screen" setting before AayDocCapioApp()
            # (and its own VaultManager) exists yet — a throwaway early
            # VaultManager just for this one read; harmless to construct
            # twice (idempotent _ensure_vault() migration check).
            _early_vault = VaultManager()
            _show_splash = _early_vault.get_setting("show_splash", True)
            _theme_pref_early = _early_vault.get_setting("theme", "light")
        except Exception:
            _show_splash = True
        # F-17: apply the saved theme (including "system") before the splash
        # paints, so there is no light flash before the main window appears.
        _resolved_early = _theme_pref_early
        if _resolved_early == "system":
            try:
                _resolved_early = (
                    "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark
                    else "light")
            except Exception:
                _resolved_early = "light"
        if _resolved_early not in THEMES:
            _resolved_early = "light"
        try:
            import ui._theme as _theme_mod_early
            _theme_mod_early._active_theme = get_theme(_resolved_early)
            app.setStyleSheet(build_stylesheet(get_theme(_resolved_early)))
        except Exception:
            pass
        try:
            _splash_logo_path = os.path.join(_bundled_dir(), "resources", "AayDoc_FullLogo.png")
            if _show_splash and os.path.exists(_splash_logo_path):
                _splash_pix = QPixmap(_splash_logo_path).scaledToWidth(
                    560, Qt.TransformationMode.SmoothTransformation)
                splash = _SplashScreen(_splash_pix)
                splash.fade_in()
                app.processEvents()
                _splash_shown_at = time.monotonic()
        except Exception as _splash_err:
            _diag(f"Splash screen skipped: {_splash_err}")
            splash = None
        _diag("Step 2: setApplicationName")
        app.setApplicationName("AayDocCapio")
        app.setDesktopFileName("aay-doc-capio")
        app.setStyle("Fusion")
        # Match the native palette to the saved preference. "system" is left
        # alone so the OS scheme is honoured; light/dark are pinned so macOS
        # dark mode does not corrupt unstyled native widgets.
        try:
            if _theme_pref_early == "dark":
                app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
            elif _theme_pref_early == "light":
                app.styleHints().setColorScheme(Qt.ColorScheme.Light)
        except AttributeError:
            pass  # Qt < 6.8
        _diag("Step 3: font loading")
        from PyQt6.QtGui import QFontDatabase
        _fonts_dir = os.path.join(_bundled_dir(), "resources", "fonts")
        if os.path.isdir(_fonts_dir):
            for _ttf in os.listdir(_fonts_dir):
                if _ttf.endswith(".ttf"):
                    QFontDatabase.addApplicationFont(os.path.join(_fonts_dir, _ttf))
        _diag("Step 4: setStyleSheet")
        app.setStyleSheet(build_stylesheet(get_theme(_resolved_early)))
        _diag("Step 5: AayDocCapioApp()")
        window = AayDocCapioApp()
        _diag("Step 6: setWindowIcon")
        _app_icon_path = os.path.join(_bundled_dir(), "resources", "app_icon.png")
        if os.path.exists(_app_icon_path):
            _icon = QIcon(_app_icon_path)
            app.setWindowIcon(_icon)
            window.setWindowIcon(_icon)
        # Confirmed live: on a fast startup, AayDocCapioApp() construction
        # can finish well inside the splash's own 350ms fade-in, so
        # finish()'s fade-out started almost immediately after — the splash
        # (and its glow/dot animations) barely registered before vanishing.
        # Hold it on screen for at least this long regardless of how fast
        # startup actually was. Uses a processEvents() pump rather than
        # time.sleep() so the fade-in/glow/dot animations keep rendering
        # during the wait instead of freezing mid-motion.
        _MIN_SPLASH_SECONDS = 3.0
        if splash is not None and _splash_shown_at is not None:
            _deadline = _splash_shown_at + _MIN_SPLASH_SECONDS
            while time.monotonic() < _deadline:
                app.processEvents()
                time.sleep(0.01)
        _diag("Step 7: window.show()")
        window.show()
        if splash is not None:
            # finish() closes the splash the moment `window` is shown/
            # active rather than needing a manual timer to guess when
            # startup is "done".
            splash.finish(window)
        _diag("Step 8: app.exec() — entering event loop")
        sys.exit(app.exec())
    except Exception as _startup_err:
        import traceback
        _tb = traceback.format_exc()
        _diag(f"CRASH:\n{_tb}")
        _fatal(_tb)

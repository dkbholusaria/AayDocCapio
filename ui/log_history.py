import os, json, datetime, threading

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QLabel, QTextEdit,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from config import _app_dir
from ui._theme import _t
from ui.helpers import _btn, _lbl
from themes import MONO_FONT_NAME as _MONO_FONT


# ── LogStore ─────────────────────────────────────────────────────────────────

class LogStore:
    """
    Plain-JSON store for per-client per-AY download status history.
    File: <_app_dir()>/log_history.json
    Schema: { PAN: { ay_label: [ {ts, status}, ... ] } }
    Entries are stored oldest-first; capped at 20 per PAN/AY.
    One entry is written per batch run (the final terminal status).
    """
    MAX_ENTRIES = 20

    def __init__(self):
        self._path = os.path.join(_app_dir(), "log_history.json")
        self._lock = threading.Lock()

    def record(self, pan: str, ay_label: str, status: str):
        with self._lock:
            data = self._load()
            pan = pan.strip().upper()
            entries = data.setdefault(pan, {}).setdefault(ay_label, [])
            entries.append({
                "ts":     datetime.datetime.now().strftime("%d-%b-%Y %H:%M:%S"),
                "status": status,
            })
            if len(entries) > self.MAX_ENTRIES:
                data[pan][ay_label] = entries[-self.MAX_ENTRIES:]
            self._save(data)

    def get(self, pan: str) -> dict:
        """Return {ay_label: [{ts, status}, ...]} for a PAN."""
        with self._lock:
            return dict(self._load().get(pan.strip().upper(), {}))

    def _load(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ── LogHistoryDialog ──────────────────────────────────────────────────────────

class LogHistoryDialog(QDialog):
    """
    F-13 — Shows the last 20 download statuses per AY for a given client.
    Opened from the right-click context menu → View Log.
    """

    def __init__(self, parent, name: str, pan: str, history: dict, active_ay: str = ""):
        super().__init__(parent)
        self._name      = name
        self._pan       = pan
        self._history   = history
        self._active_ay = active_ay
        self.setWindowTitle(f"Run History — {name} ({pan})")
        self.resize(640, 420)
        self.setMinimumSize(480, 300)
        self.setSizeGripEnabled(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint)
        self._build_ui()

    def _build_ui(self):
        t = _t()
        self.setStyleSheet(
            f"QDialog{{background:{t.bg_window};}}"
            f"QLabel{{color:{t.text_primary};background:transparent;}}"
            f"QTableWidget{{border:none;background:{t.bg_table};gridline-color:{t.border};"
            f"color:{t.text_primary};font-family:{_MONO_FONT};font-size:11px;outline:none;}}"
            f"QTableWidget::item{{padding:6px 10px;border:none;text-decoration:none;}}"
            f"QTableWidget::item:selected{{background:{t.accent};color:white;}}"
            f"QHeaderView::section{{background:{t.bg_header};color:{t.text_muted};"
            f"border:none;border-right:1px solid {t.border};"
            f"border-bottom:1px solid {t.border};"
            f"font-weight:bold;font-size:11px;height:32px;padding:0 10px;}}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Title strip ───────────────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setStyleSheet(
            f"QWidget{{background:{t.bg_table_alt};"
            f"border-bottom:1px solid {t.border};}}")
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(20, 10, 16, 10)
        tb.addWidget(_lbl("Run History", 13, bold=True))
        tb.addSpacing(10)
        tb.addWidget(_lbl(f"{self._name}  ·  {self._pan}", 11, color=t.text_muted))
        if self._active_ay:
            tb.addSpacing(6)
            tb.addWidget(_lbl(f"·  {self._active_ay}", 11, color=t.accent))
        tb.addStretch()
        outer.addWidget(title_bar)

        # ── Content ───────────────────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet(f"QWidget{{background:{t.bg_window};}}")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(16, 12, 16, 8)
        cv.setSpacing(0)

        entries = list(reversed(self._history.get(self._active_ay, [])))
        if not entries:
            msg = "No history yet for this AY." if self._active_ay else "No history yet for this client."
            empty = QLabel(msg)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color:{t.text_muted};font-size:12px;")
            cv.addStretch()
            cv.addWidget(empty, alignment=Qt.AlignmentFlag.AlignCenter)
            cv.addStretch()
        else:
            cv.addWidget(self._make_table(entries, t))

        outer.addWidget(content, stretch=1)

        # ── Footer ────────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background:{t.border};border:none;max-height:1px;")
        outer.addWidget(sep)

        footer = QWidget()
        footer.setStyleSheet(f"QWidget{{background:{t.bg_table_alt};}}")
        ft = QHBoxLayout(footer)
        ft.setContentsMargins(16, 10, 16, 10)
        ft.addStretch()
        close_btn = _btn("Close", "secondary", height=34)
        close_btn.clicked.connect(self.accept)
        ft.addWidget(close_btn)
        outer.addWidget(footer)

    @staticmethod
    def _make_table(entries: list, t) -> QTableWidget:
        tbl = QTableWidget(len(entries), 2)
        tbl.setHorizontalHeaderLabels(["Date & Time", "Last Download Status"])
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tbl.setAlternatingRowColors(True)
        tbl.setShowGrid(False)
        tbl.setStyleSheet(
            f"QTableWidget{{background:{t.bg_table};alternate-background-color:{t.bg_table_alt};}}"
        )
        for row, entry in enumerate(entries):
            ts_item = QTableWidgetItem(entry.get("ts", ""))
            ts_item.setForeground(QColor(t.text_muted))
            tbl.setItem(row, 0, ts_item)

            status_item = QTableWidgetItem(entry.get("status", ""))
            status_item.setForeground(QColor(t.text_primary))
            tbl.setItem(row, 1, status_item)

        tbl.resizeRowsToContents()
        tbl.cellDoubleClicked.connect(
            lambda row, _col, _tbl=tbl, _entries=entries, _t=t:
                _StatusDetailDialog(_tbl, _entries[row], _t).exec()
            if row < len(_entries) else None
        )
        return tbl


class _StatusDetailDialog(QDialog):
    def __init__(self, parent, entry: dict, t):
        super().__init__(parent)
        self.setWindowTitle("Status Detail")
        self.resize(480, 200)
        self.setMinimumWidth(380)
        self.setSizeGripEnabled(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint)
        self.setStyleSheet(f"QDialog{{background:{t.bg_window};}}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)

        ts = entry.get("ts", "")
        status = entry.get("status", "")

        outer.addWidget(_lbl(ts, 10, color=t.text_muted))

        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(status)
        te.setStyleSheet(
            f"QTextEdit{{background:{t.bg_table};color:{t.text_primary};"
            f"border:1px solid {t.border};border-radius:6px;"
            f"padding:10px;font-size:12px;font-family:{_MONO_FONT};}}"
        )
        te.setMinimumHeight(80)
        outer.addWidget(te, stretch=1)

        close_btn = _btn("Close", "secondary", height=34)
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

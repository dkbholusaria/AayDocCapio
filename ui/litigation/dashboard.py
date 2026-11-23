"""ui/litigation/dashboard.py — F-26 cross-module litigation dashboard."""

from __future__ import annotations

from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QMenu, QFrame, QLabel, QLineEdit,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor

from ui._theme import _t
from core.litigation.model import MODULE_LABELS

_COLS = ("Module", "Client", "Matter", "Type", "AY", "Status", "Urgency", "Case")

_URGENCY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "": 3}


class LitigationDashboard(QWidget):
    """Rich cross-module case table with filters and row actions."""

    openCaseRequested = pyqtSignal(str, str)   # (module, native_id)

    def __init__(self, handlers, parent=None):
        super().__init__(parent)
        self._h = handlers
        self._cases = []
        self._events = []
        self._rows = []
        self._matter_names = {}
        self._build()

    def _build(self):
        t = _t()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 12, 24, 16)
        outer.setSpacing(10)

        self._kpi_row = QHBoxLayout()
        self._kpi_row.setSpacing(10)
        self._kpi_labels = {}
        for key, caption in (
                ("total", "Total Cases"), ("open", "Open"),
                ("overdue", "Overdue"), ("due7", "Due in 7 days"),
                ("hearing", "Upcoming Hearings"), ("closed", "Closed")):
            card, num = self._mk_kpi(caption, t)
            self._kpi_labels[key] = num
            self._kpi_row.addWidget(card)
        outer.addLayout(self._kpi_row)

        filt = QHBoxLayout()
        filt.setSpacing(8)
        self._module_filter = QComboBox()
        self._module_filter.addItem("All modules", "")
        for key, label in MODULE_LABELS.items():
            self._module_filter.addItem(label, key)
        self._module_filter.currentIndexChanged.connect(self._apply_filter)
        self._module_filter.setStyleSheet(self._combo_qss(t))
        filt.addWidget(self._module_filter)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by client or case…")
        self._search.textChanged.connect(self._apply_filter)
        self._search.setStyleSheet(self._search_qss(t))
        filt.addWidget(self._search, 1)
        outer.addLayout(filt)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(list(_COLS))
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_menu)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        self._table.setStyleSheet(self._table_qss(t))
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(0, 100)
        self._table.setColumnWidth(1, 200)
        self._table.setColumnWidth(2, 160)
        self._table.setColumnWidth(3, 90)
        self._table.setColumnWidth(4, 120)
        self._table.setColumnWidth(5, 110)
        self._table.setColumnWidth(6, 80)
        hdr.setStretchLastSection(True)
        outer.addWidget(self._table, 1)

    def _mk_kpi(self, caption, t):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background:{t.bg_panel}; border:1px solid {t.border};"
            " border-radius:10px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        num = QLabel("0")
        num.setStyleSheet(
            f"color:{t.accent_litigation}; font-size:22px; font-weight:bold;"
            " border:none;")
        cap = QLabel(caption)
        cap.setStyleSheet(
            f"color:{t.text_muted}; font-size:11px; border:none;")
        lay.addWidget(num)
        lay.addWidget(cap)
        return card, num

    # -- data -----------------------------------------------------------

    def set_matter_names(self, names):
        self._matter_names = dict(names)

    def set_data(self, cases, events):
        self._cases = cases
        self._events = events
        self._refresh_kpis()
        self._apply_filter()

    def _refresh_kpis(self):
        today = date.today()
        visible = [e for e in self._events if getattr(e, "visible", True)]
        overdue = sum(1 for e in visible if isinstance(e.date, date) and e.date < today)
        due7 = sum(1 for e in visible
                   if isinstance(e.date, date) and today <= e.date
                   and (e.date - today).days <= 7)
        hearing = sum(1 for e in visible
                      if e.kind == "hearing" and isinstance(e.date, date)
                      and e.date >= today)
        values = {
            "total": len(self._cases),
            "open": sum(1 for c in self._cases if c.is_open and not c.ignored),
            "overdue": overdue,
            "due7": due7,
            "hearing": hearing,
            "closed": sum(1 for c in self._cases if c.closed),
        }
        for key, num in self._kpi_labels.items():
            num.setText(str(values.get(key, 0)))

    def _apply_filter(self, *_):
        module = self._module_filter.currentData() or ""
        needle = self._search.text().strip().lower()
        rows = []
        for case in self._cases:
            if module and case.module != module:
                continue
            if needle and needle not in (
                    case.client_name + " " + case.title + " " + case.client_pan
            ).lower():
                continue
            rows.append(case)
        rows.sort(key=lambda c: (
            _URGENCY_ORDER.get(c.urgency, 3),
            0 if not c.closed else 1,
            c.client_name.lower(), c.title.lower()))
        self._render(rows)

    def _render(self, cases):
        t = _t()
        self._rows = cases
        self._table.setRowCount(len(cases))
        for row, case in enumerate(cases):
            matter = self._matter_names.get(case.matter_id, "") if case.matter_id else ""
            values = (
                case.module_label,
                case.client_name or case.client_pan,
                matter or "—",
                case.case_type.title(),
                case.assessment_year or "—",
                case.status,
                case.urgency or "—",
                case.title,
            )
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                item.setForeground(QColor(t.text_primary))
                if col == 6:
                    colmap = {"High": t.error, "Medium": t.warning,
                              "Low": t.success}
                    item.setForeground(QColor(colmap.get(case.urgency,
                                                         t.text_muted)))
                if case.closed:
                    item.setForeground(QColor(t.text_muted))
                self._table.setItem(row, col, item)
        self._table.resizeRowsToContents()

    # -- interaction ----------------------------------------------------

    def _case_at(self, row):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def _on_double_click(self, row, _col):
        case = self._case_at(row)
        if case:
            self.openCaseRequested.emit(case.module, case.native_id)

    def _on_menu(self, pos):
        row = self._table.rowAt(pos.y())
        case = self._case_at(row)
        if case is None:
            return
        menu = QMenu(self)
        menu.addAction("Open case", lambda: self.openCaseRequested.emit(
            case.module, case.native_id))
        menu.addSeparator()
        reply = menu.addAction("Mark replied")
        reply.setEnabled(bool(case.is_open) and not case.replied)
        reply.triggered.connect(lambda: self._mark_replied(case))
        if case.closed:
            menu.addAction("Reopen case", lambda: self._do(
                self._h.reopen_case, case.uid))
        else:
            menu.addAction("Close case", lambda: self._do(
                self._h.close_case, case.uid))
        menu.addAction(
            "Unignore case" if case.ignored else "Ignore case",
            lambda: self._do(self._h.set_case_ignored, case.uid, not case.ignored))
        menu.addSeparator()
        menu.addAction("Link to matter…", lambda: self._link_dialog(case))
        menu.addAction("Add hearing date…", lambda: self._hearing_dialog(case))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _mark_replied(self, case):
        for ev in self._events:
            if ev.case_uid == case.uid and ev.kind == "reply_due" and ev.visible:
                self._h.mark_replied(case.uid, f"it:{ev.native_doc_id}")
        self._h.on_changed()

    def _do(self, fn, *args):
        fn(*args)
        self._h.on_changed()

    def _link_dialog(self, case):
        from PyQt6.QtWidgets import QInputDialog
        options = self._h.matter_options() if self._h else []
        if not options:
            return
        labels = [f"{m[1]} — {m[2]}" for m in options]
        chosen, ok = QInputDialog.getItem(
            self, "Link to matter", "Matter:", labels, 0, False)
        if ok and chosen:
            idx = labels.index(chosen)
            self._h.link_matter(case.uid, options[idx][0])
            self._h.on_changed()

    def _hearing_dialog(self, case):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Add hearing date",
            "Hearing date (DD-Mon-YYYY):", text="")
        if ok and text.strip():
            self._h.add_hearing(case.uid, text.strip())
            self._h.on_changed()

    # -- theme ----------------------------------------------------------

    def repaint_theme(self, t):
        self._table.setStyleSheet(self._table_qss(t))
        self._module_filter.setStyleSheet(self._combo_qss(t))
        self._search.setStyleSheet(self._search_qss(t))

    @staticmethod
    def _table_qss(t):
        return (
            "QTableWidget {"
            f" background:{t.bg_table}; alternate-background-color:{t.bg_table_alt};"
            f" gridline-color:{t.grid}; border:1.5px solid {t.border};"
            " border-radius:8px; outline:0; }"
            "QHeaderView::section {"
            f" background:{t.bg_header}; color:{t.text_muted}; font-weight:bold;"
            f" border:none; border-bottom:1px solid {t.border}; padding:6px; }}"
            "QTableWidget::item:selected {"
            f" background:{t.row_selected_bg}; color:{t.row_selected_fg}; }}"
        )

    @staticmethod
    def _combo_qss(t):
        return (
            "QComboBox {"
            f" background:{t.bg_input}; color:{t.text_primary};"
            f" border:1px solid {t.border}; border-radius:6px; padding:4px 8px; }}"
        )
    @staticmethod
    def _search_qss(t):
        return (
            "QLineEdit {"
            f" background:{t.bg_input}; color:{t.text_primary};"
            f" border:1px solid {t.border}; border-radius:6px; padding:5px 8px; }}"
            f"QLineEdit:focus {{ border:1px solid {t.border_focus}; }}"
        )

"""ui/litigation/dashboard.py — F-26 cross-module litigation dashboard."""

from __future__ import annotations

from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QMenu, QFrame, QLabel, QLineEdit,
    QPushButton, QSizePolicy,
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
        self._selected_case = None
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

        split = QHBoxLayout()
        split.setSpacing(12)

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
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
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
        split.addWidget(self._table, 1)

        self._side = self._mk_side(t)
        split.addWidget(self._side)

        outer.addLayout(split, 1)
        self._render_detail(None)

    def _mk_side(self, t):
        side = QFrame()
        side.setObjectName("litSide")
        side.setFixedWidth(300)
        side.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        side.setStyleSheet(self._side_qss(t))
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(6)

        head = QHBoxLayout()
        heading = QLabel("Case detail")
        heading.setStyleSheet(
            f"color:{t.text_muted}; font-size:11px; font-weight:bold;"
            " border:none; background:transparent;")
        head.addWidget(heading)
        head.addStretch(1)
        self._side_module = QLabel("")
        self._side_module.setStyleSheet(
            f"color:{t.accent_litigation}; font-size:11px; font-weight:bold;"
            " border:none; background:transparent;")
        head.addWidget(self._side_module)
        lay.addLayout(head)

        self._side_title = QLabel("")
        self._side_title.setWordWrap(True)
        self._side_title.setStyleSheet(
            f"color:{t.text_primary}; font-size:13px; font-weight:bold;"
            " border:none; background:transparent;")
        lay.addWidget(self._side_title)

        self._side_client = QLabel("")
        self._side_client.setWordWrap(True)
        self._side_client.setStyleSheet(
            f"color:{t.text_muted}; font-size:11px;"
            " border:none; background:transparent;")
        lay.addWidget(self._side_client)

        self._side_badges = QLabel("")
        self._side_badges.setWordWrap(True)
        self._side_badges.setTextFormat(Qt.TextFormat.RichText)
        self._side_badges.setStyleSheet("border:none; background:transparent;")
        lay.addWidget(self._side_badges)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{t.border}; background:{t.border}; border:none;")
        line.setFixedHeight(1)
        lay.addWidget(line)

        self._side_meta = QLabel("")
        self._side_meta.setWordWrap(True)
        self._side_meta.setTextFormat(Qt.TextFormat.RichText)
        self._side_meta.setStyleSheet(
            f"color:{t.text_primary}; font-size:11px;"
            " border:none; background:transparent;")
        lay.addWidget(self._side_meta)

        self._side_milestone = QLabel("")
        self._side_milestone.setWordWrap(True)
        self._side_milestone.setStyleSheet(
            f"color:{t.text_primary}; font-size:11.5px;"
            " border:none; background:transparent;")
        lay.addWidget(self._side_milestone)

        lay.addStretch(1)

        self._side_open = QPushButton("Open case")
        self._side_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._side_open.setStyleSheet(self._open_btn_qss(t))
        self._side_open.clicked.connect(self._open_selected)
        lay.addWidget(self._side_open)
        return side

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
        self._table.blockSignals(True)
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
        self._table.clearSelection()
        self._table.blockSignals(False)
        self._selected_case = None
        self._render_detail(None)

    # -- side panel -----------------------------------------------------

    def _next_milestone(self, case):
        today = date.today()
        candidates = [
            e for e in self._events
            if e.case_uid == case.uid and getattr(e, "visible", True)
            and isinstance(e.date, date)
        ]
        upcoming = [e for e in candidates if e.date >= today]
        pool = upcoming or candidates
        if not pool:
            return ""
        ev = min(pool, key=lambda e: e.date)
        delta = (ev.date - today).days
        when = ev.date.strftime("%d %b %Y")
        if delta < 0:
            rel = f"overdue {abs(delta)}d"
        elif delta == 0:
            rel = "today"
        else:
            rel = f"in {delta}d"
        return f"{ev.kind_label} · {when} ({rel})"

    def _render_detail(self, case):
        t = _t()
        self._selected_case = case
        if case is None:
            self._side_module.setText("")
            self._side_title.setText("No case selected")
            self._side_client.setText(
                "Select a row to see case detail and its next milestone.")
            self._side_badges.setText("")
            self._side_meta.setText("")
            self._side_milestone.setText("")
            self._side_open.setEnabled(False)
            return
        self._side_module.setText(case.module_label)
        self._side_title.setText(case.title or "Untitled case")
        client = case.client_name or case.client_pan or "—"
        if case.client_pan and case.client_name:
            client = f"{case.client_name} · {case.client_pan}"
        self._side_client.setText(client)

        st_color = t.success if case.is_open else t.text_muted
        urg_color = {"High": t.error, "Medium": t.warning,
                     "Low": t.success}.get(case.urgency, t.text_muted)
        badges = [f'<span style="color:{st_color}; font-weight:bold;">'
                  f"{self._esc(case.status or '—')}</span>"]
        if case.urgency:
            badges.append(f'<span style="color:{urg_color}; font-weight:bold;">'
                          f"{self._esc(case.urgency)} urgency</span>")
        self._side_badges.setText(" &nbsp;·&nbsp; ".join(badges))

        matter = self._matter_names.get(case.matter_id, "") if case.matter_id else ""
        rows = [
            ("Type", case.case_type.title() if case.case_type else "—"),
            ("AY / Period", case.assessment_year or "—"),
            ("Matter", matter or "—"),
        ]
        meta_lines = []
        for label, val in rows:
            meta_lines.append(
                f'<span style="color:{t.text_muted};">{self._esc(label)}</span>'
                f"&nbsp;&nbsp;{self._esc(str(val))}")
        self._side_meta.setText("<br>".join(meta_lines))

        milestone = self._next_milestone(case)
        if milestone:
            self._side_milestone.setText(
                f'<span style="color:{t.text_muted};">Next milestone</span><br>'
                f'<span style="font-weight:bold; color:{t.text_primary};">'
                f"{self._esc(milestone)}</span>")
        else:
            self._side_milestone.setText(
                f'<span style="color:{t.text_muted};">Next milestone</span><br>'
                f'<span style="color:{t.text_muted};">No open deadlines</span>')
        self._side_open.setEnabled(True)

    @staticmethod
    def _esc(text):
        return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    def _on_selection_changed(self):
        case = self._case_at(self._table.currentRow())
        self._render_detail(case)

    def _open_selected(self):
        if self._selected_case is not None:
            self.openCaseRequested.emit(
                self._selected_case.module, self._selected_case.native_id)

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
        self._side.setStyleSheet(self._side_qss(t))
        self._side_open.setStyleSheet(self._open_btn_qss(t))
        self._render_detail(self._selected_case)

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

    @staticmethod
    def _side_qss(t):
        return (
            "QFrame#litSide {"
            f" background:{t.bg_panel}; border:1px solid {t.border};"
            " border-radius:10px; }"
        )

    @staticmethod
    def _open_btn_qss(t):
        return (
            "QPushButton {"
            f" background:{t.accent_litigation}; color:{t.accent_text};"
            " border:none; border-radius:6px; padding:7px 14px;"
            " font-weight:bold; font-size:12px; }"
            f"QPushButton:disabled {{ background:{t.border};"
            f" color:{t.text_muted}; }}"
        )

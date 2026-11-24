"""ui/litigation/calendar_view.py — F-26 litigation calendar.

A month calendar that marks days carrying open deadlines, plus a day-detail
list below. Reply-due, hearing and limitation events are shown as distinct,
colour-coded kinds; replied / ignored / closed / satisfied events are hidden
(see ``core.litigation.calendar.visible_events``).
"""

from __future__ import annotations

from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCalendarWidget, QListWidget,
    QListWidgetItem, QLabel, QMenu,
)
from PyQt6.QtCore import pyqtSignal, Qt, QDate
from PyQt6.QtGui import QColor, QTextCharFormat, QBrush, QFont

from ui._theme import _t
from ui.helpers import _lbl
from core.litigation.calendar import events_by_day

_KIND_COLORS = {
    "reply_due": ("#2563EB", "#60A5FA"),
    "hearing": ("#7E22CE", "#C084FC"),
    "limitation": ("#B45309", "#FBBF24"),
}


class LitigationCalendar(QWidget):
    """Month grid + day-detail list of litigation deadlines."""

    openCaseRequested = pyqtSignal(str, str)

    def __init__(self, handlers, parent=None):
        super().__init__(parent)
        self._h = handlers
        self._cases = {}
        self._events = []
        self._by_day = {}
        self._selected = date.today()
        self._build()

    def _build(self):
        t = _t()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 12, 24, 16)
        outer.setSpacing(10)

        legend = QHBoxLayout()
        legend.addWidget(_lbl("Deadlines:", 11, bold=True, color=t.text_muted))
        for kind, label in (("reply_due", "Reply due"),
                            ("hearing", "Hearing"),
                            ("limitation", "Limitation")):
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color:{self._kind_color(kind, t)}; font-size:14px;")
            legend.addWidget(dot)
            legend.addWidget(_lbl(label, 11, color=t.text_muted))
            legend.addSpacing(10)
        legend.addStretch(1)
        outer.addLayout(legend)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._cal = QCalendarWidget()
        self._cal.setGridVisible(True)
        self._cal.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._cal.selectionChanged.connect(self._on_select)
        self._cal.setStyleSheet(self._cal_qss(t))
        body.addWidget(self._cal, 3)

        right = QVBoxLayout()
        right.setSpacing(6)
        self._day_title = _lbl("", 13, bold=True)
        right.addWidget(self._day_title)
        self._list = QListWidget()
        self._list.setStyleSheet(self._list_qss(t))
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_menu)
        self._list.itemDoubleClicked.connect(self._on_double)
        right.addWidget(self._list, 1)
        body.addLayout(right, 2)

        outer.addLayout(body, 1)

    def build_month(self):
        """Repaint the current month (called when the tab is shown)."""
        self._apply_formats()
        self._on_select()

    # -- data -----------------------------------------------------------

    def set_data(self, cases, events):
        self._cases = {c.uid: c for c in cases}
        self._events = events
        self._by_day = events_by_day(events, include_hidden=False)
        self._apply_formats()
        self._on_select()

    def _apply_formats(self):
        t = _t()
        self._cal.setDateTextFormat(QDate(), QTextCharFormat())  # clear
        for day, evs in self._by_day.items():
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Bold)
            kinds = {e.kind for e in evs}
            primary = next(iter(kinds))
            color = self._kind_color(primary, t)
            fmt.setForeground(QBrush(QColor(color)))
            fmt.setBackground(QBrush(QColor(color + "22")))
            fmt.setToolTip(", ".join(sorted({e.kind_label for e in evs})))
            self._cal.setDateTextFormat(
                QDate(day.year, day.month, day.day), fmt)

    def _on_select(self):
        qd = self._cal.selectedDate()
        day = date(qd.year(), qd.month(), qd.day())
        self._selected = day
        self._day_title.setText(day.strftime("%A, %d %b %Y"))
        self._list.clear()
        for ev in sorted(self._by_day.get(day, []), key=lambda e: e.kind):
            t = _t()
            color = self._kind_color(ev.kind, t)
            text = f"[{ev.kind_label}]  {ev.title}"
            item = QListWidgetItem(text)
            item.setForeground(QColor(color))
            item.setData(Qt.ItemDataRole.UserRole, ev)
            self._list.addItem(item)
        if not self._list.count():
            placeholder = QListWidgetItem("No open deadlines on this day.")
            placeholder.setForeground(QColor(_t().text_muted))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)

    # -- interaction ----------------------------------------------------

    def _event_at(self, item):
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_double(self, item):
        ev = self._event_at(item)
        if ev:
            case = self._cases.get(ev.case_uid)
            if case:
                self.openCaseRequested.emit(case.module, case.native_id)

    def _on_menu(self, pos):
        item = self._list.itemAt(pos)
        ev = self._event_at(item)
        if ev is None:
            return
        menu = QMenu(self)
        case = self._cases.get(ev.case_uid)
        if case:
            menu.addAction("Open case", lambda: self.openCaseRequested.emit(
                case.module, case.native_id))
        menu.addAction("Ignore this deadline (hide)", lambda: self._ignore(ev))
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _ignore(self, ev):
        self._h.ignore_event(ev.eid, True)
        self._h.on_changed()

    # -- theme ----------------------------------------------------------

    @staticmethod
    def _kind_color(kind, t):
        light, dark = _KIND_COLORS.get(kind, ("#64748B", "#94A3B8"))
        if getattr(t, "name", "").lower() == "light":
            return light
        return dark

    def repaint_theme(self, t):
        self._cal.setStyleSheet(self._cal_qss(t))
        self._list.setStyleSheet(self._list_qss(t))
        self._apply_formats()

    @staticmethod
    def _cal_qss(t):
        return (
            "QCalendarWidget QWidget {"
            f" background:{t.bg_panel}; color:{t.text_primary}; }}"
            "QCalendarWidget QAbstractItemView:enabled {"
            f" background:{t.bg_table}; color:{t.text_primary};"
            f" selection-background-color:{t.accent_litigation};"
            f" selection-color:{t.accent_text}; }}"
            "QCalendarWidget QToolButton {"
            f" color:{t.text_primary}; background:transparent; }}"
        )

    @staticmethod
    def _list_qss(t):
        return (
            "QListWidget {"
            f" background:{t.bg_table}; border:1.5px solid {t.border};"
            " border-radius:8px; outline:0; }"
            "QListWidget::item { padding:6px; }"
        )

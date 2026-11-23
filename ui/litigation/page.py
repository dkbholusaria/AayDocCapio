"""ui/litigation/page.py — F-26 Litigation hub page shell.

Composes three views over a tab row (Dashboard · Calendar · Matters) and owns
the shared data pipeline: adapter scan -> store overrides -> views. Every
action performed in a sub-view calls back here to persist through the store and
re-scan, then emits ``dataChanged`` so the host window can refresh the source
module view (Income Tax e-Proceedings) too.
"""

from __future__ import annotations

from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget,
)
from PyQt6.QtCore import pyqtSignal, Qt

from ui._theme import _t

from core.litigation.store import LitigationStore
from core.litigation.adapters import collect_all

from ui.litigation.dashboard import LitigationDashboard
from ui.litigation.calendar_view import LitigationCalendar
from ui.litigation.matters import LitigationMatters

_TABS = ("Dashboard", "Calendar", "Matters")


class LitigationPage(QWidget):
    """Top-level Litigation hub widget."""

    dataChanged = pyqtSignal()
    openCaseRequested = pyqtSignal(str, str)   # (module, native_id)

    def __init__(self, vault, assessees_provider, parent=None):
        super().__init__(parent)
        self._vault = vault
        self._assessees_provider = assessees_provider
        self._store = LitigationStore(vault)

        self._cases = []
        self._events = []
        self._tab_btns = []
        self._loaded = False

        self._build_shell()
        self.refresh()

    # -- data -----------------------------------------------------------

    def _scan(self):
        root = self._vault.get_setting("download_root_dir", "") or ""
        try:
            assessees = self._assessees_provider() or []
        except Exception:
            assessees = []
        self._cases, self._events = collect_all(
            root, assessees, self._store, today=date.today())

    def refresh(self):
        """Rescan sources, reapply store overrides, rebuild every view."""
        self._scan()
        matters = {m.id: m.title for m in self._store.matters()}
        self._dashboard.set_matter_names(matters)
        self._dashboard.set_data(self._cases, self._events)
        self._calendar.set_data(self._cases, self._events)
        self._matters.set_data(self._cases)
        # Keep the dashboard's link dialog options in sync with the store.
        self._h.matter_options = lambda: [
            (m.id, m.client_name or m.client_pan, m.title)
            for m in self._store.matters()]
        self._loaded = True

    def matter_options(self):
        return [(m.id, m.client_name or m.client_pan, m.title)
                for m in self._store.matters()]

    # -- shell ----------------------------------------------------------

    def _build_shell(self):
        t = _t()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        tab_row = QWidget()
        tab_row.setFixedHeight(46)
        tr = QHBoxLayout(tab_row)
        tr.setContentsMargins(24, 8, 24, 8)
        tr.setSpacing(4)
        for idx, label in enumerate(_TABS):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(30)
            btn.setStyleSheet(self._tab_qss(t))
            btn.clicked.connect(lambda _=False, i=idx: self._switch(i))
            self._tab_btns.append(btn)
            tr.addWidget(btn)
        tr.addStretch(1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setFixedHeight(30)
        self._refresh_btn.setStyleSheet(self._refresh_qss(t))
        self._refresh_btn.clicked.connect(self.refresh)
        tr.addWidget(self._refresh_btn)
        outer.addWidget(tab_row)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        handlers = _Callbacks(
            mark_replied=self._mark_replied,
            close_case=self._close_case,
            reopen_case=self._reopen_case,
            set_case_ignored=self._set_case_ignored,
            ignore_event=self._ignore_event,
            link_matter=self._link_matter,
            add_hearing=self._add_hearing,
            on_changed=self._after_change,
            matter_options=lambda: [],
        )
        self._h = handlers
        self._dashboard = LitigationDashboard(handlers)
        self._dashboard.openCaseRequested.connect(self.openCaseRequested)
        self._calendar = LitigationCalendar(handlers)
        self._calendar.openCaseRequested.connect(self.openCaseRequested)
        self._matters = LitigationMatters(self._store, handlers)

        self._stack.addWidget(self._dashboard)
        self._stack.addWidget(self._calendar)
        self._stack.addWidget(self._matters)
        self._switch(0)

    @staticmethod
    def _tab_qss(t):
        return (
            "QPushButton { border:none; padding:4px 14px; border-radius:8px;"
            f" color:{t.text_muted}; font-size:12px; font-weight:bold; }}"
            "QPushButton:hover {"
            f" color:{t.text_primary}; background:{t.bg_table_alt}; }}"
            "QPushButton:checked {"
            f" color:{t.accent_text}; background:{t.accent_litigation}; }}"
        )

    @staticmethod
    def _refresh_qss(t):
        return (
            "QPushButton { border:1px solid " + t.border + "; padding:4px 14px;"
            " border-radius:8px; font-size:12px; font-weight:bold;"
            f" background:{t.bg_panel}; color:{t.text_primary}; }}"
            "QPushButton:hover {"
            f" background:{t.bg_table_alt}; }}"
        )

    def _switch(self, idx):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_btns):
            btn.setChecked(i == idx)
        if idx == 1:
            self._calendar.build_month()

    # -- action plumbing ------------------------------------------------

    def _after_change(self):
        self.refresh()
        self.dataChanged.emit()

    def _mark_replied(self, case_uid, doc_uid):
        self._store.set_doc_replied(doc_uid, True)

    def _close_case(self, case_uid):
        self._store.set_case_closed(case_uid, True)

    def _reopen_case(self, case_uid):
        self._store.set_case_closed(case_uid, False)

    def _set_case_ignored(self, case_uid, ignored):
        self._store.set_case_ignored(case_uid, ignored)

    def _ignore_event(self, eid, ignored):
        # The eid is "<case_uid>|<kind>|<native>". Reply events map to the doc
        # override used by the Income Tax adapter; every other kind is stored
        # under its own eid so only that deadline is hidden.
        case_uid, _, rest = eid.partition("|")
        kind, _, native_key = rest.partition("|")
        if kind == "reply_due":
            self._store.set_doc_ignored(f"it:{native_key}", ignored)
        else:
            self._store.set_doc_ignored(eid, ignored)

    def _link_matter(self, case_uid, matter_id):
        self._store.link_case(case_uid, matter_id)

    def _add_hearing(self, case_uid, date_label):
        self._store.add_hearing(case_uid, date_label)

    # -- theme ----------------------------------------------------------

    def repaint_theme(self, t):
        for btn in self._tab_btns:
            btn.setStyleSheet(self._tab_qss(t))
        self._refresh_btn.setStyleSheet(self._refresh_qss(t))
        self._dashboard.repaint_theme(t)
        self._calendar.repaint_theme(t)
        self._matters.repaint_theme(t)


class _Callbacks:
    """Small bundle of action callbacks handed to the sub-views."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

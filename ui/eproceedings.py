"""e-Proceedings case workspace for the Income Tax hub.

The workspace replaces the old flat document table with a case-centric view:
KPI cards, a filterable case list, and a detail area with Overview, Timeline,
Appeals and Limitations tabs.  All data comes from
:mod:`ui.eproceedings_model`; this module is presentation-only.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui._theme import _t
from ui.eproc_doc_modal import EprocDocModal
from ui.eproc_timeline import EprocTimeline
from ui.eproceedings_model import (
    _parse_date,
    build_cases,
    compute_limitations,
    derive_status,
    filter_cases,
    kpis,
    sections_in,
    sort_cases,
    visible_docs,
)
from ui.helpers import _btn, _lbl
from ui.nav_shell import _svg_pixmap
from ui.widgets import ClickableCard, StyledComboBox


_TAB_KEYS = ("overview", "timeline", "appeals", "limitations")
_TAB_LABELS = ("Overview", "Case Timeline", "Appeals", "Limitations")

_KPI_TABS = {
    "fresh_notices": "timeline",
    "due7": "timeline",
    "due15": "timeline",
    "under_appeal": "appeals",
    "closed_by_order": "overview",
    "remanded": "timeline",
    "overdue_limitations": "limitations",
}

_KPI_LABELS = {
    "cases": "All cases",
    "open_cases": "Open cases",
    "fresh_notices": "Fresh notices",
    "due7": "Due within 7 days",
    "due15": "Due within 15 days",
    "under_appeal": "Under appeal",
    "closed_by_order": "Closed by order",
    "remanded": "Remanded",
    "overdue_limitations": "Overdue limitations",
}

# Eight cards, four per row. Colours map onto the theme's existing tokens —
# there are no separate indigo/sky/violet tokens.
_KPI_SPECS = (
    ("cases", "Cases", "Mapped matters", "accent", "document"),
    ("open_cases", "Open Cases", "Actively tracked", "success", "list"),
    ("fresh_notices", "Fresh Notices",
     "Newly received, not yet urgent", "accent_mca", "mail"),
    ("due7", "Due \u2264 7 days", "Reply deadline this week",
     "error", "help"),
    ("due15", "Due \u2264 15 days", "Reply deadline this fortnight",
     "warning", "gear"),
    ("under_appeal", "Under Appeal",
     "Open cases with a pending appeal", "accent_mca", "columns"),
    ("closed_by_order", "Closed by Order",
     "Order passed, no appeal filed", "success", "document"),
    ("remanded", "Remanded", "Set aside, back to AO",
     "warning", "building"),
)

_DOC_MIX = (
    ("notice", "Notices"),
    ("reply", "Replies"),
    ("order", "Assessment orders"),
    ("penalty", "Penalties / demands"),
    ("appeal-order", "Appeal orders"),
    ("remand", "Remands"),
)

_KIND_DOT = {
    "notice": "accent",
    "reply": "success",
    "order": "accent_mca",
    "penalty": "error",
    "appeal-order": "warning",
    "remand": "warning",
}


# ---------------------------------------------------------------------------
# Small presentation helpers
# ---------------------------------------------------------------------------

def _short(text: str, limit: int = 34) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\u2026"


def _initials(name: str) -> str:
    words = [word for word in (name or "").split() if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _avatar_bg(pan: str) -> str:
    t = _t()
    palette = [t.accent, t.accent_mca, t.success, t.warning, t.error,
               t.accent_home]
    key = sum(ord(char) for char in (pan or ""))
    return palette[key % len(palette)]


def _avatar(name: str, pan: str, size: int = 34) -> QLabel:
    label = QLabel(_initials(name))
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        f"background:{_avatar_bg(pan)}; color:{_t().accent_text};"
        f"border:none; border-radius:{size // 2}px;"
        f"font-size:{max(10, size // 3)}px; font-weight:bold;")
    return label


def _pill(text: str, bg: str, fg: str, size: int = 9) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"background:{bg}; color:{fg}; border:none; border-radius:8px;"
        f"padding:2px 7px; font-size:{size}px; font-weight:600;")
    # The badge is sized by its own text — without an explicit size policy Qt
    # lets the parent layout squash it, which clipped the "3d ov" countdown at
    # the card's right edge. Fixed horizontal policy keeps the full text.
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    label.setMinimumWidth(label.fontMetrics().horizontalAdvance(text) + 16)
    return label


def _status_tint(status: str):
    t = _t()
    key = (status or "").strip().lower()
    if key in ("replied", "closed", "satisfied"):
        return t.success_bg, t.success
    if key in ("overdue", "limitation expired"):
        return t.error_bg, t.error
    if key in ("under appeal", "remanded"):
        return t.accent_light, t.accent
    if key in ("open", "appeal window", "2nd appeal window", "pending",
               "window open", "due soon"):
        return t.warning_bg, t.warning
    return t.bg_table_alt, t.text_muted


def _limitation_tint(status: str):
    t = _t()
    key = (status or "").strip().lower()
    if key == "satisfied":
        return t.success_bg, t.success
    if key == "overdue":
        return t.error_bg, t.error
    if key == "due soon":
        return t.warning_bg, t.warning
    return t.bg_table_alt, t.text_muted


def _urgency_color(urgency: str) -> str:
    t = _t()
    key = (urgency or "").strip().lower()
    if key == "high":
        return t.error
    if key == "medium":
        return t.warning
    return t.text_muted


def _countdown(days) -> tuple[str, str, str]:
    t = _t()
    if days is None:
        return "", t.bg_table_alt, t.text_muted
    if days < 0:
        return f"{abs(days)}d ov", t.error_bg, t.error
    if days <= 7:
        return f"{days}d", t.error_bg, t.error
    if days <= 30:
        return f"{days}d", t.warning_bg, t.warning
    return f"{days}d", t.bg_table_alt, t.text_muted


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
            continue
        child = item.layout()
        if child is not None:
            _clear_layout(child)
            child.deleteLater()


def _panel(object_name: str = "EprocPanel") -> tuple[QFrame, QVBoxLayout]:
    t = _t()
    frame = QFrame()
    frame.setObjectName(object_name)
    frame.setStyleSheet(
        f"QFrame#{object_name} {{ background:{t.bg_panel};"
        f"border:1px solid {t.border}; border-radius:10px; }}")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 11, 12, 11)
    layout.setSpacing(6)
    return frame, layout


def _muted(text: str, size: int = 10) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"background:transparent; border:none; color:{_t().text_muted};"
        f"font-size:{size}px;")
    return label


def _scroll_panel() -> tuple[QScrollArea, QVBoxLayout]:
    t = _t()
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setStyleSheet(
        f"QScrollArea {{ background:{t.bg_window}; border:none; }}")
    content = QWidget()
    content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    content.setStyleSheet(f"background:{t.bg_window};")
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 2, 0)
    layout.setSpacing(8)
    area.setWidget(content)
    return area, layout


def _link(target: str, text: str) -> str:
    accent = _t().accent
    return (
        f'<a href="{html.escape(target, quote=True)}" '
        f'style="color:{accent}; text-decoration:none;">'
        f"{html.escape(text)}</a>"
    )


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

class EProceedingsWorkspace(QWidget):
    """Case-centric e-Proceedings workspace."""

    def __init__(self, vault, assessees_provider, parent=None):
        super().__init__(parent)
        self._vault = vault
        self._assessees_provider = assessees_provider

        self._cases = []
        self._case_index = {}
        self._case_by_key = {}
        self._status_map = {}
        self._selected_id = ""
        self._selected_key = ""
        self._active_tab = "overview"
        self._kpi_filter = None

        self._case_cards = []
        self._kpi_cards = {}
        self._kpi_numbers = {}
        self._kpi_pill = None
        self._kpi_pill_label = None
        self._kpi_clear_btn = None

        self._tab_buttons = []
        self._stack = None
        self._timeline = None
        self._detail_name_label = None
        self._doc_mix_counts = {}
        self._limitation_rows = []

        self._toast_label = None
        self._toast_seq = 0

        self._build_shell()
        self._render_detail()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Rescan the download root and rebuild every view."""
        root = self._vault.get_setting("download_root_dir", "") or ""
        state = self._vault.get_setting("eproc_case_state", {}) or {}
        try:
            assessees = self._assessees_provider() or []
        except Exception:
            assessees = []

        self._cases = build_cases(root, assessees, state)
        self._case_index = {}
        for case in self._cases:
            self._case_index.setdefault(case.id, case)
        self._case_by_key = {case.proc_dir: case for case in self._cases}
        self._status_map = {
            doc.id: derive_status(doc, case)
            for case in self._cases for doc in case.docs
        }

        self._refresh_kpis()
        self._refresh_section_filter()

        filtered = self._filtered_cases()
        if self._selected_key in self._case_by_key:
            self._selected_id = self._case_by_key[self._selected_key].id
        else:
            chosen = filtered[0] if filtered else (
                self._cases[0] if self._cases else None)
            self._selected_key = chosen.proc_dir if chosen is not None else ""
            self._selected_id = chosen.id if chosen is not None else ""

        self._render_case_list(filtered)
        self._render_detail()

    def kpi_snapshot(self) -> dict:
        """Return model.kpis() for the currently loaded cases."""
        return kpis(self._cases)

    def _selected_case(self):
        case = self._case_by_key.get(self._selected_key)
        if case is not None:
            return case
        return self._case_index.get(self._selected_id)

    def goto_case(self, case_id: str, tab: str = "overview") -> None:
        """Select the first case matching ``case_id`` and switch tabs."""
        case = self._case_index.get(case_id)
        if case is None:
            return
        filtered = self._filtered_cases()
        if case_id not in {item.id for item in filtered}:
            self._reset_case_filters()
            filtered = self._filtered_cases()
        match = next((item for item in filtered if item.id == case_id), None)
        if match is not None:
            case = match
        self._select_case(case)
        self._switch_tab(tab if tab in _TAB_KEYS else "overview")

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def _build_shell(self) -> None:
        t = _t()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 8)
        outer.setSpacing(7)

        # Eight compact cards in a single row — the previous 4x2 grid ate
        # ~200px of vertical space that the case list needs.
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(7)
        for position, (key, caption, sub, token, icon) in enumerate(_KPI_SPECS):
            _row = _col = 0
            accent = getattr(t, token)
            card = ClickableCard()
            card.setObjectName("EprocKpi")
            card.setFixedHeight(62)
            card.setToolTip(sub)
            card.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.setStyleSheet(
                f"QFrame#EprocKpi {{ background:{t.bg_panel};"
                f"border:1px solid {t.border}; border-radius:9px; }}"
                f"QFrame#EprocKpi:hover {{ border-color:{accent}; }}")
            card.clicked.connect(
                lambda clicked=False, k=key: self._on_kpi(k))

            body = QHBoxLayout(card)
            body.setContentsMargins(10, 6, 8, 6)
            body.setSpacing(6)

            text_col = QVBoxLayout()
            text_col.setSpacing(0)
            text_col.addWidget(_lbl(caption, 9, color=t.text_muted))
            number = _lbl("0", 18, bold=True, color=accent)
            text_col.addWidget(number)
            body.addLayout(text_col, 1)

            chip = QLabel()
            chip.setFixedSize(24, 24)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setPixmap(_svg_pixmap(icon, accent, 15))
            chip.setStyleSheet(
                f"background:{accent}22; border:none; border-radius:7px;")
            body.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)

            self._kpi_cards[key] = card
            self._kpi_numbers[key] = number
            kpi_row.addWidget(card, 1)
        outer.addLayout(kpi_row)

        split = QHBoxLayout()
        split.setSpacing(14)
        self._case_panel = self._build_case_panel()
        self._detail_panel = self._build_detail_panel()
        split.addWidget(self._case_panel, 0)
        split.addWidget(self._detail_panel, 1)
        outer.addLayout(split, 1)
        # Browse mode first: the case list owns the page and the detail pane
        # stays hidden until a case is clicked (saves a lot of empty space).
        self._enter_browse()

        self._toast_label = QLabel("", self)
        self._toast_label.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        self._toast_label.setStyleSheet(
            f"background:{t.bg_panel}; border:1px solid {t.border};"
            f"border-radius:8px; padding:6px 14px; color:{t.text_primary};"
            f"font-size:11px; font-weight:600;")
        self._toast_label.setVisible(False)
        self._toast_label.raise_()

    def _build_case_panel(self) -> QWidget:
        t = _t()
        panel = QFrame()
        panel.setObjectName("EprocCasePanel")
        panel.setMinimumWidth(300)
        panel.setStyleSheet(
            f"QFrame#EprocCasePanel {{ background:{t.bg_panel};"
            f"border:1px solid {t.border}; border-radius:10px; }}")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._cases_title = _lbl("Cases (0 / 0)", 12, bold=True)
        header.addWidget(self._cases_title)
        header.addStretch(1)
        layout.addLayout(header)

        self._kpi_pill = QFrame()
        self._kpi_pill.setObjectName("EprocKpiPill")
        self._kpi_pill.setStyleSheet(
            f"QFrame#EprocKpiPill {{ background:{t.accent_light};"
            f"border:none; border-radius:9px; }}")
        pill = QHBoxLayout(self._kpi_pill)
        pill.setContentsMargins(8, 2, 4, 2)
        pill.setSpacing(4)
        self._kpi_pill_label = _lbl("", 9, bold=True, color=t.accent)
        pill.addWidget(self._kpi_pill_label)
        pill.addStretch(1)
        self._kpi_clear_btn = QPushButton("\u2715")
        self._kpi_clear_btn.setFlat(True)
        self._kpi_clear_btn.setFixedSize(18, 18)
        self._kpi_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._kpi_clear_btn.setToolTip("Clear KPI filter")
        self._kpi_clear_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; border:none;"
            f"color:{t.accent}; font-size:10px; padding:0; }}"
            f"QPushButton:hover {{ color:{t.accent_hover}; }}")
        self._kpi_clear_btn.clicked.connect(self._clear_kpi_filter)
        pill.addWidget(self._kpi_clear_btn)
        self._kpi_pill.setVisible(False)
        layout.addWidget(self._kpi_pill)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search name, PAN, case ID, AY, ward\u2026")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(26)
        self._search.setStyleSheet(
            f"QLineEdit {{ background:{t.bg_input}; border:1px solid {t.border};"
            f"border-radius:6px; padding:4px 9px; font-size:12px;"
            f"color:{t.text_primary}; }}"
            f"QLineEdit:focus {{ border-color:{t.border_focus}; }}")
        self._search.textChanged.connect(self._apply_filters)
        layout.addWidget(self._search)

        self._status_combo = self._filter_combo(
            (("All", "all"), ("Open", "open"), ("Closed", "closed")))
        self._tag_combo = self._filter_combo(
            (("All", "all"), ("Multi-year", "Multi-year"),
             ("Remanded", "Remanded"), ("Under appeal", "Under appeal")))
        self._section_combo = self._filter_combo((("All", "all"),))
        self._urgency_combo = self._filter_combo(
            (("All", "all"), ("High", "High"), ("Medium", "Medium"),
             ("Low", "Low")))
        self._sort_combo = self._filter_combo(
            (("Next deadline", "deadline"), ("Urgency", "urgency"),
             ("Assessee", "assessee"), ("Case ID", "id")),
            emit=False)

        self._filters_box = QWidget()
        filters_lay = QVBoxLayout(self._filters_box)
        filters_lay.setContentsMargins(0, 0, 0, 0)
        filters_lay.setSpacing(7)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(self._status_combo, 1)
        row1.addWidget(self._tag_combo, 1)
        row1.addWidget(self._section_combo, 1)
        row1.addWidget(self._urgency_combo, 1)
        row1.addWidget(self._sort_combo, 1)
        reset = _btn("Reset", "outline", height=26, min_width=54)
        reset.clicked.connect(self._reset_filters)
        row1.addWidget(reset)
        filters_lay.addLayout(row1)

        layout.addWidget(self._filters_box, 0)

        self._list_scroll, self._list_layout = _scroll_panel()
        layout.addWidget(self._list_scroll, 1)
        return panel

    def _filter_combo(self, items, emit: bool = True) -> StyledComboBox:
        combo = StyledComboBox()
        combo.setFixedHeight(26)
        combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setStyleSheet(
            f"QComboBox {{ font-size:11px; padding:2px 6px; min-width:0; }}")
        for label, data in items:
            combo.addItem(label, data)
        if emit:
            combo.currentIndexChanged.connect(self._apply_filters)
        return combo

    def _enter_browse(self) -> None:
        """No case selected: the case list owns the page. The detail pane is
        hidden and the filter row is shown full width (it is hidden in the
        narrow split view to save room for the list)."""
        self._detail_visible = False
        self._selected_key = ""
        self._selected_id = ""
        for card in getattr(self, "_case_cards", []) or []:
            card.setStyleSheet(self._case_card_qss(False))
        if getattr(self, "_detail_panel", None) is not None:
            self._detail_panel.setVisible(False)
        if getattr(self, "_case_panel", None) is not None:
            self._case_panel.setMaximumWidth(16777215)
            self._case_panel.setMinimumWidth(300)
        if getattr(self, "_filters_box", None) is not None:
            self._filters_box.setMaximumWidth(16777215)
            self._filters_box.setVisible(True)

    def _back_to_browse(self) -> None:
        """Detail header's 'Back to cases' button."""
        self._enter_browse()
        self._render_case_list(self._filtered_cases())

    def _enter_workspace(self) -> None:
        """A case is selected: show the detail pane, give the case list a
        comfortable width, and drop the 5-control filter row that would not
        fit beside it (search stays)."""
        self._detail_visible = True
        if getattr(self, "_detail_panel", None) is not None:
            self._detail_panel.setVisible(True)
        if getattr(self, "_case_panel", None) is not None:
            self._case_panel.setMaximumWidth(470)
            self._case_panel.setMinimumWidth(420)
        if getattr(self, "_filters_box", None) is not None:
            self._filters_box.setVisible(False)

    def _build_detail_panel(self) -> QWidget:
        t = _t()
        host = QFrame()
        host.setObjectName("EprocDetail")
        host.setStyleSheet(
            f"QFrame#EprocDetail {{ background:{t.bg_window}; border:none; }}")
        host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._detail_layout = QVBoxLayout(host)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_layout.setSpacing(10)
        return host

    # ------------------------------------------------------------------
    # KPIs and filters
    # ------------------------------------------------------------------

    def _refresh_kpis(self) -> None:
        snapshot = kpis(self._cases)
        for key, label in self._kpi_numbers.items():
            label.setText(str(snapshot.get(key, 0)))

    def _refresh_section_filter(self) -> None:
        current = self._section_combo.currentData() or "all"
        sections = sections_in(self._cases)
        self._section_combo.blockSignals(True)
        self._section_combo.clear()
        self._section_combo.addItem("All sections", "all")
        for section in sections:
            self._section_combo.addItem(f"Section {section}", section)
        index = self._section_combo.findData(current)
        self._section_combo.setCurrentIndex(index if index >= 0 else 0)
        self._section_combo.blockSignals(False)

    def _on_kpi(self, key: str) -> None:
        self._kpi_filter = key
        self._update_kpi_pill()
        filtered = self._filtered_cases()
        if filtered:
            self._selected_id = filtered[0].id
            self._selected_key = filtered[0].proc_dir
        self._render_case_list(filtered)
        self._enter_workspace()
        # Re-render the list so it collapses from two columns to one.
        self._render_case_list(self._filtered_cases())
        self._render_detail()
        self._switch_tab(_KPI_TABS.get(key, "overview"))

    def _clear_kpi_filter(self) -> None:
        self._kpi_filter = None
        self._update_kpi_pill()
        self._apply_filters()

    def _update_kpi_pill(self) -> None:
        if self._kpi_pill is None:
            return
        if self._kpi_filter:
            self._kpi_pill_label.setText(
                f"KPI: {_KPI_LABELS.get(self._kpi_filter, 'Filter')}")
            self._kpi_pill.setVisible(True)
        else:
            self._kpi_pill.setVisible(False)

    def _reset_filters(self) -> None:
        self._kpi_filter = None
        self._update_kpi_pill()
        self._search.clear()
        for combo in (self._status_combo, self._tag_combo,
                      self._section_combo, self._urgency_combo,
                      self._sort_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._apply_filters()

    def _reset_case_filters(self) -> None:
        self._kpi_filter = None
        self._update_kpi_pill()
        self._search.clear()
        for combo in (self._status_combo, self._tag_combo,
                      self._section_combo, self._urgency_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)

    def _apply_filters(self) -> None:
        filtered = self._filtered_cases()
        keys = {case.proc_dir for case in filtered}
        if self._selected_key not in keys and filtered:
            self._selected_key = filtered[0].proc_dir
            self._selected_id = filtered[0].id
            self._render_detail()
        self._render_case_list(filtered)

    def _filtered_cases(self):
        status = self._status_combo.currentData() or "all"
        tag = self._tag_combo.currentData() or "all"
        section = self._section_combo.currentData() or "all"
        urgency = self._urgency_combo.currentData() or "all"
        mode = self._sort_combo.currentData() or "deadline"

        cases = filter_cases(self._cases, status, tag, section, urgency)
        cases = [case for case in cases if self._matches_kpi(case)]

        query = (self._search.text() or "").strip().lower()
        if query:
            cases = [case for case in cases if self._matches_query(case, query)]

        return sort_cases(cases, mode)

    @staticmethod
    def _matches_query(case, query: str) -> bool:
        haystack = " ".join([
            case.name, case.pan, case.id, case.proc_name,
            case.assessee.ward or "",
        ] + list(case.ays)).lower()
        return query in haystack

    def _matches_kpi(self, case) -> bool:
        key = self._kpi_filter
        if not key:
            return True
        if key == "open_cases":
            return bool(case.case_open)
        if key == "awaiting_reply":
            return any(doc.kind in ("notice", "penalty")
                       and doc.status in ("Open", "Overdue")
                       for doc in case.docs)
        if key == "fresh_notices":
            return any(self._notice_bucket(doc) == "fresh" for doc in case.docs)
        if key == "due7":
            return any(self._notice_bucket(doc) == "due7" for doc in case.docs)
        if key == "due15":
            return any(self._notice_bucket(doc) == "due15"
                       for doc in case.docs)
        if key == "under_appeal":
            # "In appeal" only applies while the case is still OPEN.
            return bool(case.case_open) and any(
                appeal.status == "Pending" for appeal in case.appeals)
        if key == "closed_by_order":
            return self._has_closed_by_order(case)
        if key == "remanded":
            return bool(case.remanded)
        if key == "overdue_limitations":
            return any(row.status == "Overdue"
                       for row in compute_limitations(case))
        return True

    @staticmethod
    def _notice_bucket(doc) -> str:
        """Classify an unreplied notice for the Fresh / Due-7 / Due-15 cards.

        fresh   -> more than 15 days left (or no deadline given)
        due7    -> deadline within 0..7 days
        due15   -> deadline within 8..15 days (so the three buckets never
                   double-count the same notice)
        """
        if doc.kind not in ("notice", "penalty"):
            return ""
        if doc.status not in ("Open", "Overdue"):
            return ""
        parsed = _parse_date(doc.reply_deadline)
        if parsed is None:
            return "fresh"
        days = (parsed - date.today()).days
        if days < 0:
            return ""          # overdue is surfaced separately
        if days <= 7:
            return "due7"
        if days <= 15:
            return "due15"
        return "fresh"

    @staticmethod
    def _has_closed_by_order(case) -> bool:
        """A case counts as 'closed by order' when an order closed its
        notices/appeal and nothing further is pending."""
        if case.case_open:
            return False
        return any(doc.kind in ("order", "appeal-order") and doc.status
                   in ("Closed", "Limitation expired", "Resolved")
                   for doc in case.docs)

    # ------------------------------------------------------------------
    # Case list
    # ------------------------------------------------------------------

    def _render_case_list(self, cases) -> None:
        _clear_layout(self._list_layout)
        self._case_cards = []
        self._cases_title.setText(
            f"Cases ({len(cases)} / {len(self._cases)})")

        if not cases:
            empty = _muted("No cases match the current filters.", 10)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 20, 0, 0)
            self._list_layout.addWidget(empty)
            self._list_layout.addStretch(1)
            return

        section = self._section_combo.currentData() or "all"
        urgency = self._urgency_combo.currentData() or "all"

        # Browse mode uses two columns so a full-width page isn't one long
        # sparse strip; the split workspace keeps a single column.
        if getattr(self, "_detail_visible", False):
            columns = 1
        else:
            columns = 3 if self.width() >= 1500 else 2
        row_layout = None
        for position, case in enumerate(cases):
            card = self._build_case_card(case, section, urgency)
            self._case_cards.append(card)
            if columns == 1:
                self._list_layout.addWidget(card, 0)
                continue
            if position % columns == 0:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(10)
                self._list_layout.addLayout(row_layout)
            row_layout.addWidget(card, 1)
            if position % columns == columns - 1:
                row_layout = None
        self._list_layout.addStretch(1)
        # Force an immediate layout pass. Without this the freshly-built
        # cards keep their pre-layout geometry (a few pixels tall) until the
        # user happens to resize the window — which visually clipped the
        # countdown badge and lock button on every card.
        self._list_layout.activate()
        content = self._list_scroll.widget()
        if content is not None and content.layout() is not None:
            content.layout().activate()

    def _case_card_qss(self, selected: bool) -> str:
        t = _t()
        border = f"2px solid {t.accent}" if selected \
            else f"1px solid {t.border}"
        return (
            f"QFrame#EprocCaseCard {{ background:{t.bg_panel};"
            f"border:{border}; border-radius:9px; }}"
            f"QFrame#EprocCaseCard:hover {{ border-color:{t.accent}; }}")

    def _build_case_card(self, case, section: str, urgency: str) -> ClickableCard:
        t = _t()
        card = ClickableCard()
        card.setObjectName("EprocCaseCard")
        card.setProperty("caseId", case.id)
        card.setProperty("caseKey", case.proc_dir)
        selected = case.proc_dir == self._selected_key
        card.setStyleSheet(self._case_card_qss(selected))
        card.clicked.connect(
            lambda c=case: self._select_case(c))

        body = QVBoxLayout(card)
        body.setContentsMargins(9, 8, 9, 8)
        body.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(7)
        top.addWidget(_avatar(case.name, case.pan, 34),
                      0, Qt.AlignmentFlag.AlignTop)

        middle = QVBoxLayout()
        middle.setSpacing(3)

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(4)
        name_label = _lbl(_short(case.name, 20), 11, bold=True)
        name_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                 QSizePolicy.Policy.Preferred)
        name_label.setMinimumWidth(0)
        name_row.addWidget(name_label, 1)
        if case.case_open:
            name_row.addWidget(_pill("O", t.success_bg, t.success))
        else:
            name_row.addWidget(_pill("C", t.bg_table_alt, t.text_muted))
        name_row.addStretch(1)
        middle.addLayout(name_row)

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(3)
        chips.addWidget(_pill(case.pan, t.bg_table_alt, t.text_primary))
        for ay in case.ays[:1]:
            chips.addWidget(_pill(ay, t.bg_table_alt, t.text_muted))
        if case.remanded:
            chips.addWidget(_pill("RE", t.warning_bg, t.warning))
        chips.addStretch(1)
        middle.addLayout(chips)
        top.addLayout(middle, 1)

        # Fixed-width right rail: keeps the countdown badge and lock button
        # at their natural size instead of letting the flexible name column
        # squeeze them to zero width (that clipping bug was visible on
        # narrow case cards).
        right_host = QWidget()
        right_host.setFixedWidth(62)
        right = QVBoxLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(3)
        right.setAlignment(Qt.AlignmentFlag.AlignTop)
        days = self._case_deadline_days(case)
        text, bg, fg = _countdown(days)
        if text:
            right.addWidget(_pill(text, bg, fg), 0,
                            Qt.AlignmentFlag.AlignRight)
        lock = QPushButton("Lock" if case.case_open else "Open")
        lock.setFlat(True)
        lock.setCursor(Qt.CursorShape.PointingHandCursor)
        lock.setFixedHeight(18)
        lock.setStyleSheet(
            f"QPushButton {{ background:transparent; border:none;"
            f"color:{t.text_muted}; font-size:9px; padding:0 2px; }}"
            f"QPushButton:hover {{ color:{t.accent}; }}")
        lock.setToolTip("Close this case" if case.case_open
                        else "Reopen this case")
        lock.clicked.connect(
            lambda clicked=False, cid=case.id, closed=case.case_open:
            self._set_case_closed(cid, closed))
        right.addWidget(lock, 0, Qt.AlignmentFlag.AlignRight)
        top.addWidget(right_host, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(top)

        for doc in visible_docs(case, section, urgency):
            if doc.kind not in ("notice", "penalty"):
                continue
            body.addWidget(self._build_doc_row(case, doc))

        # The scroll content widget does not propagate natural heights
        # (setWidgetResizable + trailing stretch collapsed every card to a
        # few pixels, hiding the countdown badge and lock button). Pin each
        # card to its own layout's height so it always renders in full.
        card.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Fixed)
        card.setMinimumWidth(0)
        body.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        card.setMinimumHeight(0)
        return card

    def _build_doc_row(self, case, doc) -> ClickableCard:
        t = _t()
        row = ClickableCard()
        row.setObjectName("EprocDocRow")
        unreplied = (doc.kind in ("notice", "penalty")
                     and doc.status in ("Open", "Overdue"))
        bg = t.accent_light if unreplied else t.bg_table_alt
        row.setStyleSheet(
            f"QFrame#EprocDocRow {{ background:{bg}; border:none;"
            f"border-radius:6px; }}"
            f"QFrame#EprocDocRow:hover {{ background:{t.accent_light}; }}")
        row.clicked.connect(
            lambda c=case, doc_id=doc.id: self._open_doc(c, doc_id))

        line = QHBoxLayout(row)
        line.setContentsMargins(6, 4, 6, 4)
        line.setSpacing(5)
        if doc.section:
            line.addWidget(_pill(doc.section, t.bg_panel, t.text_muted))
        title = QLabel(_short(doc.title, 34))
        title.setStyleSheet(
            f"background:transparent; border:none; color:{t.text_primary};"
            f"font-size:10px;")
        # Let the layout squeeze this label instead of widening the card —
        # the text is already truncated by _short(); without this the row's
        # minimumSizeHint equals the full text width and the countdown pill
        # on the right got pushed outside the panel.
        title.setSizePolicy(QSizePolicy.Policy.Ignored,
                            QSizePolicy.Policy.Preferred)
        title.setMinimumWidth(0)
        title.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        line.addWidget(title, 1)

        dot = QLabel()
        dot.setFixedSize(6, 6)
        dot.setStyleSheet(
            f"background:{_urgency_color(doc.urg)}; border:none;"
            f"border-radius:3px;")
        dot.setToolTip(f"{doc.urg or 'Low'} urgency")
        line.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        if doc.status:
            bg2, fg2 = _status_tint(doc.status)
            line.addWidget(_pill(doc.status, bg2, fg2))

        days = self._doc_deadline_days(doc)
        text, bg3, fg3 = _countdown(days)
        if text:
            line.addWidget(_pill(text, bg3, fg3))
        return row

    def _select_case(self, case) -> None:
        if case is None:
            return
        self._selected_key = case.proc_dir
        self._selected_id = case.id
        for card in self._case_cards:
            card.setStyleSheet(
                self._case_card_qss(
                    card.property("caseKey") == case.proc_dir))
        self._enter_workspace()
        # Re-render so the list collapses from two columns to one now that
        # the detail pane is taking half the page.
        self._render_case_list(self._filtered_cases())
        self._render_detail()

    @staticmethod
    def _doc_deadline_days(doc):
        parsed = _parse_date(doc.reply_deadline)
        if parsed is None or doc.status in ("Replied", "Closed", "Satisfied"):
            return None
        return (parsed - date.today()).days

    def _case_deadline_days(self, case):
        dates = []
        for doc in case.docs:
            parsed = _parse_date(doc.reply_deadline)
            if parsed is not None and doc.status not in (
                    "Replied", "Closed", "Satisfied"):
                dates.append(parsed)
        for row in compute_limitations(case):
            if row.status == "Satisfied":
                continue
            parsed = _parse_date(row.due_date)
            if parsed is not None:
                dates.append(parsed)
        if not dates:
            return None
        return (min(dates) - date.today()).days

    # ------------------------------------------------------------------
    # Detail shell
    # ------------------------------------------------------------------

    def _render_detail(self) -> None:
        if not getattr(self, "_detail_visible", False):
            # Browse mode — nothing to render until a case is clicked.
            return
        _clear_layout(self._detail_layout)
        self._tab_buttons = []
        self._stack = None
        self._timeline = None
        self._detail_name_label = None
        self._doc_mix_counts = {}
        self._limitation_rows = []

        case = self._selected_case()
        if case is None:
            holder = QWidget()
            lay = QVBoxLayout(holder)
            lay.addStretch(1)
            empty = _muted(
                "No e-Proceedings downloaded yet.\n"
                "Run Download \u2192 e-Proceedings Documents first.", 12)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(empty)
            lay.addStretch(1)
            self._detail_layout.addWidget(holder, 1)
            return

        t = _t()
        header = QFrame()
        header.setObjectName("EprocDetailHeader")
        header.setStyleSheet(
            f"QFrame#EprocDetailHeader {{ background:{t.bg_panel};"
            f"border:1px solid {t.border}; border-radius:10px; }}")
        head = QHBoxLayout(header)
        head.setContentsMargins(14, 11, 12, 11)
        head.setSpacing(11)

        back = QPushButton("Back to cases")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFlat(True)
        back.setStyleSheet(
            f"QPushButton {{ background:transparent; border:none;"
            f"color:{t.accent}; font-size:10px; font-weight:600;"
            f"padding:0 4px 0 0; }}"
            f"QPushButton:hover {{ color:{t.accent_hover}; }}")
        back.setToolTip("Back to the full case list")
        back.clicked.connect(lambda clicked=False: self._back_to_browse())
        head.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)

        head.addWidget(_avatar(case.name, case.pan, 44),
                       0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)
        self._detail_name_label = _lbl(case.name, 17, bold=True)
        self._detail_name_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        name_row.addWidget(self._detail_name_label)
        if case.case_open:
            name_row.addWidget(_pill("CASE OPEN", t.success_bg, t.success, 9))
        else:
            name_row.addWidget(_pill("CASE CLOSED", t.bg_table_alt,
                                     t.text_muted, 9))
        if case.remanded:
            name_row.addWidget(_pill("REMANDED", t.warning_bg, t.warning, 9))
        name_row.addStretch(1)
        text_col.addLayout(name_row)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(4)
        case_chip = QPushButton(case.id)
        case_chip.setFlat(True)
        case_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        case_chip.setToolTip("Copy case id")
        case_chip.setStyleSheet(
            f"QPushButton {{ background:{t.bg_table_alt}; color:{t.text_muted};"
            f"border:none; border-radius:8px; padding:2px 7px;"
            f"font-size:9px; font-weight:600; text-align:left; }}"
            f"QPushButton:hover {{ color:{t.accent}; }}")
        case_chip.clicked.connect(
            lambda clicked=False, cid=case.id: self._copy_case_id(cid))
        meta.addWidget(case_chip)
        for ay in case.ays:
            meta.addWidget(_pill(ay, t.bg_table_alt, t.text_muted))
        if case.assessee.ward:
            meta.addWidget(_lbl(case.assessee.ward, 9, color=t.text_muted))
        meta.addStretch(1)
        text_col.addLayout(meta)
        head.addLayout(text_col, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        ai = _btn("AI Draft", "primary", height=32, min_width=76)
        ai.clicked.connect(
            lambda: self._toast("AI drafting is not available in this build"))
        actions.addWidget(ai)
        if case.case_open:
            toggle = _btn("Close Case", "danger", height=32, min_width=86)
        else:
            toggle = _btn("Reopen Case", "success", height=32, min_width=86)
        toggle.clicked.connect(
            lambda clicked=False, cid=case.id, closed=case.case_open:
            self._set_case_closed(cid, closed))
        actions.addWidget(toggle)
        export = _btn("Export", "outline", height=32, min_width=70)
        export.clicked.connect(
            lambda: self._toast("Export is not available in this build"))
        actions.addWidget(export)
        head.addLayout(actions)
        self._detail_layout.addWidget(header)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(2, 0, 0, 0)
        tab_row.setSpacing(4)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (key, label) in enumerate(zip(_TAB_KEYS, _TAB_LABELS)):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background:transparent; border:none;"
                f"border-radius:7px; padding:0 14px; font-size:12px;"
                f"font-weight:600; color:{t.text_muted}; }}"
                f"QPushButton:hover {{ background:{t.bg_table_alt};"
                f"color:{t.text_primary}; }}"
                f"QPushButton:checked {{ color:{t.accent};"
                f"background:{t.accent_light}; }}")
            btn.clicked.connect(
                lambda clicked=False, k=key: self._switch_tab(k))
            group.addButton(btn)
            tab_row.addWidget(btn)
            self._tab_buttons.append(btn)
        tab_row.addStretch(1)
        self._detail_layout.addLayout(tab_row)

        self._active_tab = self._active_tab if self._active_tab in _TAB_KEYS \
            else "overview"
        stack = QStackedWidget()
        stack.setStyleSheet(f"QStackedWidget {{ background:{t.bg_window}; }}")
        stack.addWidget(self._build_overview(case))
        stack.addWidget(self._build_timeline_tab(case))
        stack.addWidget(self._build_appeals_tab(case))
        stack.addWidget(self._build_limitations_tab(case))
        self._stack = stack
        self._detail_layout.addWidget(stack, 1)
        self._switch_tab(self._active_tab)

    def _switch_tab(self, key: str) -> None:
        if key not in _TAB_KEYS:
            key = "overview"
        self._active_tab = key
        index = _TAB_KEYS.index(key)
        if self._stack is not None:
            self._stack.setCurrentIndex(index)
        for position, button in enumerate(self._tab_buttons):
            button.blockSignals(True)
            button.setChecked(position == index)
            button.blockSignals(False)

    def _copy_case_id(self, case_id: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(case_id)
        self._toast("Case ID copied")

    def _set_case_closed(self, case_id: str, closed: bool) -> None:
        state = self._vault.get_setting("eproc_case_state", {}) or {}
        state = dict(state)
        entry = dict(state.get(case_id) or {})
        entry["closed"] = bool(closed)
        state[case_id] = entry
        self._vault.update_setting("eproc_case_state", state)
        self.refresh()
        self._toast("Case closed" if closed else "Case reopened")

    # ------------------------------------------------------------------
    # Overview tab
    # ------------------------------------------------------------------

    def _build_overview(self, case) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background:{_t().bg_window};")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        columns.addWidget(self._build_assessee_card(case), 1)
        columns.addWidget(self._build_doc_mix_card(case), 1)
        columns.addWidget(self._build_linked_card(case), 1)
        outer.addLayout(columns)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(self._build_spotlight_card(case), 2)
        bottom.addWidget(self._build_closure_card(), 1)
        outer.addLayout(bottom)
        outer.addStretch(1)
        return page

    def _build_assessee_card(self, case) -> QFrame:
        t = _t()
        frame, body = _panel()

        top = QHBoxLayout()
        top.setSpacing(9)
        top.addWidget(_avatar(case.assessee.name, case.assessee.pan, 40))
        who = QVBoxLayout()
        who.setSpacing(1)
        who.addWidget(_lbl(case.assessee.name, 12, bold=True))
        who.addWidget(_lbl(f"PAN {case.assessee.pan}", 10,
                           color=t.text_muted))
        top.addLayout(who, 1)
        body.addLayout(top)

        details = []
        if case.assessee.email:
            details.append(
                f"Email: <a href='mailto:{html.escape(case.assessee.email, quote=True)}'"
                f" style='color:{t.accent}; text-decoration:none;'>"
                f"{html.escape(case.assessee.email)}</a>")
        if case.assessee.phone:
            details.append(
                f"Phone: <a href='tel:{html.escape(case.assessee.phone, quote=True)}'"
                f" style='color:{t.accent}; text-decoration:none;'>"
                f"{html.escape(case.assessee.phone)}</a>")
        if case.assessee.ward:
            details.append(f"Ward: {html.escape(case.assessee.ward)}")
        if details:
            rich = QLabel("<br>".join(details))
            rich.setTextFormat(Qt.TextFormat.RichText)
            rich.setOpenExternalLinks(True)
            rich.setWordWrap(True)
            rich.setStyleSheet(
                f"background:transparent; border:none;"
                f"color:{t.text_primary}; font-size:10px;")
            body.addWidget(rich)

        body.addSpacing(2)
        stats = QHBoxLayout()
        stats.setSpacing(6)
        live = len([row for row in compute_limitations(case)
                    if row.status != "Satisfied"])
        stats.addWidget(self._mini_stat(
            "Docs", len(case.docs), t.text_primary), 1)
        stats.addWidget(self._mini_stat(
            "Appeals", len(case.appeals), t.accent,
            lambda: self._switch_tab("appeals")), 1)
        stats.addWidget(self._mini_stat(
            "Live limits", live, t.warning,
            lambda: self._switch_tab("limitations")), 1)
        body.addLayout(stats)
        body.addStretch(1)
        return frame

    def _mini_stat(self, label: str, value, color: str, on_click=None) -> QFrame:
        t = _t()
        if on_click is not None:
            box = ClickableCard()
            box.setObjectName("EprocMiniStat")
            box.setStyleSheet(
                f"QFrame#EprocMiniStat {{ background:{t.bg_table_alt};"
                f"border:none; border-radius:7px; }}"
                f"QFrame#EprocMiniStat:hover {{ background:{t.accent_light}; }}")
            box.clicked.connect(on_click)
        else:
            box = QFrame()
            box.setObjectName("EprocMiniStat")
            box.setStyleSheet(
                f"QFrame#EprocMiniStat {{ background:{t.bg_table_alt};"
                f"border:none; border-radius:7px; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(0)
        number = _lbl(str(value), 14, bold=True, color=color)
        number.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        caption = _lbl(label, 9, color=t.text_muted)
        caption.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(number)
        lay.addWidget(caption)
        return box

    def _build_doc_mix_card(self, case) -> QFrame:
        t = _t()
        frame, body = _panel()
        body.addWidget(_lbl("Document mix", 11, bold=True))

        counts = {kind: 0 for kind, _label in _DOC_MIX}
        for doc in case.docs:
            counts[doc.kind] = counts.get(doc.kind, 0) + 1
        self._doc_mix_counts = counts

        for kind, label in _DOC_MIX:
            row = QHBoxLayout()
            row.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(
                f"background:{getattr(t, _KIND_DOT.get(kind, 'text_muted'))};"
                f"border:none; border-radius:4px;")
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(_lbl(label, 10, color=t.text_primary))
            row.addStretch(1)
            row.addWidget(_lbl(str(counts.get(kind, 0)), 10, bold=True))
            body.addLayout(row)

        body.addStretch(1)
        return frame

    def _build_linked_card(self, case) -> QFrame:
        t = _t()
        frame, body = _panel()
        body.addWidget(_lbl("Linked chain", 11, bold=True))

        docs = [doc for doc in case.docs
                if doc.kind in ("order", "appeal-order", "remand")]
        if not docs:
            body.addWidget(_muted("No orders or appeal links recorded."))
            body.addStretch(1)
            return frame

        by_id = {doc.id: doc for doc in case.docs}
        for doc in docs:
            block = QVBoxLayout()
            block.setSpacing(1)
            block.addWidget(_lbl(_short(doc.title, 44), 10, bold=True))

            links = []
            if doc.kind in ("order", "appeal-order"):
                for number, appeal in enumerate(case.appeals, start=1):
                    if appeal.against == doc.id:
                        links.append(
                            f"Appeal: {_link(appeal.against, f'{appeal.forum} APL-{number}')}")
                for other in case.docs:
                    if other.kind == "penalty" and other.triggered_by == doc.id:
                        provision = (f" ({html.escape(other.section)})"
                                     if other.section else "")
                        links.append(
                            f"Penalty: {_link(other.id, _short(other.title, 22))}"
                            f"{provision}")
            if doc.kind == "remand" and doc.remands:
                target = by_id.get(doc.remands)
                label = _short(target.title if target else doc.remands, 26)
                links.append(f"Remand: {_link(doc.remands, label)}")

            if links:
                rich = QLabel(" \u00b7 ".join(links))
                rich.setTextFormat(Qt.TextFormat.RichText)
                rich.setWordWrap(True)
                rich.setOpenExternalLinks(False)
                rich.setStyleSheet(
                    f"background:transparent; border:none;"
                    f"color:{t.text_muted}; font-size:9px;")
                rich.linkActivated.connect(
                    lambda doc_id, c=case: self._open_doc(c, doc_id))
                block.addWidget(rich)
            else:
                block.addWidget(_muted("No links yet.", 9))
            body.addLayout(block)

        body.addStretch(1)
        return frame

    def _build_spotlight_card(self, case) -> ClickableCard:
        t = _t()
        card = ClickableCard()
        card.setObjectName("EprocSpotlight")
        card.setStyleSheet(
            f"QFrame#EprocSpotlight {{ background:{t.accent_light};"
            f"border:none; border-radius:10px; }}"
            f"QFrame#EprocSpotlight:hover {{ border:1px solid {t.accent}; }}")
        card.clicked.connect(lambda: self._switch_tab("limitations"))
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(2)
        lay.addWidget(_lbl("NEXT LIMITATION", 9, bold=True, color=t.accent))

        rows = [row for row in compute_limitations(case)
                if row.status != "Satisfied"]
        rows.sort(key=lambda row: _parse_date(row.due_date) or date.max)
        if not rows:
            lay.addWidget(_lbl("No live limitation clocks for this case.",
                               12, bold=True, color=t.text_primary))
            lay.addWidget(_muted("See the Limitations tab for the full list.", 9))
            return card

        nearest = rows[0]
        lay.addWidget(_lbl(_short(nearest.title, 48), 13, bold=True,
                           color=t.text_primary))
        days = None
        parsed = _parse_date(nearest.due_date)
        if parsed is not None:
            days = (parsed - date.today()).days
        detail = f"Due {nearest.due_date}"
        if days is not None:
            detail += f" \u00b7 {days} days" if days >= 0 \
                else f" \u00b7 {abs(days)} days overdue"
        detail += f" \u00b7 {nearest.provision}"
        lay.addWidget(_lbl(detail, 10, color=t.text_primary))
        return card

    def _build_closure_card(self) -> QFrame:
        t = _t()
        frame, body = _panel()
        body.addWidget(_lbl("Closure rules", 11, bold=True))
        body.addWidget(_muted(
            "A case stays open until the portal marks it closed or you "
            "close it here; a manual close is saved and reused on every "
            "rescan.", 10))
        body.addStretch(1)
        return frame

    # ------------------------------------------------------------------
    # Timeline tab
    # ------------------------------------------------------------------

    def _build_timeline_tab(self, case) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background:{_t().bg_window};")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        timeline = EprocTimeline()
        timeline.set_case(case, self._status_map)
        timeline.docActivated.connect(
            lambda doc_id, c=case: self._open_doc(c, doc_id))
        self._timeline = timeline
        lay.addWidget(timeline, 1)
        return page

    # ------------------------------------------------------------------
    # Appeals tab
    # ------------------------------------------------------------------

    def _build_appeals_tab(self, case) -> QWidget:
        t = _t()
        area, layout = _scroll_panel()
        if not case.appeals:
            empty = _muted("No appeals recorded for this case yet.", 11)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addSpacing(30)
            layout.addWidget(empty)
            layout.addStretch(1)
            return area

        for number, appeal in enumerate(case.appeals, start=1):
            layout.addWidget(self._build_appeal_card(case, appeal, number))
        layout.addStretch(1)
        return area

    def _build_appeal_card(self, case, appeal, number: int) -> QFrame:
        t = _t()
        frame, body = _panel()
        by_id = {doc.id: doc for doc in case.docs}

        head = QHBoxLayout()
        head.setSpacing(7)
        icon = QLabel()
        icon.setFixedSize(20, 20)
        icon.setPixmap(_svg_pixmap("columns", t.accent_mca, 18))
        head.addWidget(icon)
        head.addWidget(_lbl(f"APL-{number} \u2014 {appeal.forum}", 11,
                            bold=True))
        target = by_id.get(appeal.against)
        if target is not None:
            tagged = QLabel(f"Tagged to {_link(target.id, _short(target.title, 34))}")
            tagged.setTextFormat(Qt.TextFormat.RichText)
            tagged.setOpenExternalLinks(False)
            tagged.setStyleSheet(
                f"background:transparent; border:none;"
                f"color:{t.text_muted}; font-size:9px;")
            tagged.linkActivated.connect(
                lambda doc_id, c=case: self._open_doc(c, doc_id))
            head.addWidget(tagged)
        head.addStretch(1)
        bg, fg = _status_tint(appeal.status)
        head.addWidget(_pill(appeal.status, bg, fg))
        body.addLayout(head)

        columns = QHBoxLayout()
        columns.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(_lbl("GROUNDS", 9, bold=True, color=t.text_muted))
        grounds = _muted(appeal.grounds or "No grounds recorded yet.", 10)
        left.addWidget(grounds)
        left.addWidget(_lbl("PROGRESS", 9, bold=True, color=t.text_muted))
        left.addLayout(self._appeal_stepper(appeal))
        columns.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(6)
        if target is not None:
            linked = ClickableCard()
            linked.setObjectName("EprocLinkedOrder")
            linked.setStyleSheet(
                f"QFrame#EprocLinkedOrder {{ background:{t.bg_table_alt};"
                f"border:1px solid {t.border}; border-radius:7px; }}"
                f"QFrame#EprocLinkedOrder:hover {{ border-color:{t.accent}; }}")
            linked.clicked.connect(
                lambda c=case, doc_id=target.id: self._open_doc(c, doc_id))
            link_lay = QVBoxLayout(linked)
            link_lay.setContentsMargins(9, 7, 9, 7)
            link_lay.setSpacing(1)
            link_lay.addWidget(_lbl("LINKED ORDER", 8, bold=True,
                                    color=t.text_muted))
            link_lay.addWidget(_lbl(_short(target.title, 30), 10, bold=True))
            if target.issued:
                link_lay.addWidget(_lbl(f"Issued {target.issued}", 9,
                                        color=t.text_muted))
            right.addWidget(linked)

        if appeal.status == "Window open" and target is not None:
            issued = _parse_date(target.issued) or _parse_date(target.served)
            if issued is not None:
                # CIT(A) has 30 days from service (s.246A r/w s.249(2));
                # ITAT has 60 days from receipt (s.253(3)). The old code used
                # the ITAT window and provision for every appeal.
                is_itat = (appeal.forum or "").upper() == "ITAT"
                window_days = 60 if is_itat else 30
                provision = ("s.253(3)" if is_itat
                             else "s.246A r/w s.249(2)")
                due = issued + timedelta(days=window_days)
                remaining = (due - date.today()).days
                expired = remaining < 0
                bg = t.error_bg if expired else t.warning_bg
                fg = t.error if expired else t.warning
                headline = (f"Appeal window expired {abs(remaining)} days ago"
                            if expired
                            else f"File within {remaining} days")
                box = QFrame()
                box.setObjectName("EprocAppealClock")
                box.setStyleSheet(
                    f"QFrame#EprocAppealClock {{ background:{bg};"
                    f"border:none; border-radius:7px; }}")
                box_lay = QVBoxLayout(box)
                box_lay.setContentsMargins(9, 7, 9, 7)
                box_lay.setSpacing(1)
                box_lay.addWidget(_lbl(headline, 10, bold=True, color=fg))
                box_lay.addWidget(_lbl(
                    f"{due.strftime('%d-%b-%Y')} ({provision})", 9,
                    color=t.text_muted))
                right.addWidget(box)
        right.addStretch(1)
        columns.addLayout(right, 0)
        body.addLayout(columns)
        return frame

    def _appeal_stepper(self, appeal) -> QVBoxLayout:
        t = _t()
        holder = QVBoxLayout()
        holder.setSpacing(3)
        for step in appeal.steps:
            row = QHBoxLayout()
            row.setSpacing(6)
            circle = QLabel("\u2713" if step.done else "")
            circle.setFixedSize(16, 16)
            circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if step.done:
                circle.setStyleSheet(
                    f"background:{t.accent}; color:{t.accent_text};"
                    f"border:none; border-radius:8px; font-size:9px;"
                    f"font-weight:bold;")
            else:
                circle.setStyleSheet(
                    f"background:transparent; border:1px solid {t.border};"
                    f"border-radius:8px;")
            row.addWidget(circle, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(_lbl(step.label, 10, color=t.text_primary))
            if step.date:
                row.addWidget(_lbl(step.date, 9, color=t.text_muted))
            row.addStretch(1)
            holder.addLayout(row)
        return holder

    # ------------------------------------------------------------------
    # Limitations tab
    # ------------------------------------------------------------------

    def _build_limitations_tab(self, case) -> QWidget:
        t = _t()
        area, layout = _scroll_panel()

        intro, intro_body = _panel()
        intro_body.addWidget(_lbl("Statutory limitation clocks", 11, bold=True))
        intro_body.addWidget(_muted(
            "These are the filing and compliance deadlines that follow from "
            "this case's notices and orders. A row turns red once the "
            "statutory date has passed, amber when it is due within a week, "
            "and green when the milestone has been met.", 10))
        layout.addWidget(intro)

        rows = compute_limitations(case)
        self._limitation_rows = rows
        if not rows:
            empty = _muted("No limitation clocks for this case.", 11)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addSpacing(20)
            layout.addWidget(empty)
            layout.addStretch(1)
            return area

        for row in rows:
            layout.addWidget(self._build_limitation_row(case, row))
        layout.addStretch(1)
        return area

    def _build_limitation_row(self, case, row) -> QFrame:
        t = _t()
        frame = QFrame()
        frame.setObjectName("EprocLimitRow")
        frame.setStyleSheet(
            f"QFrame#EprocLimitRow {{ background:{t.bg_panel};"
            f"border:1px solid {t.border}; border-radius:8px; }}")
        line = QHBoxLayout(frame)
        line.setContentsMargins(10, 8, 10, 8)
        line.setSpacing(9)

        bg, fg = _limitation_tint(row.status)
        icon = QLabel()
        icon.setFixedSize(20, 20)
        icon.setPixmap(_svg_pixmap("help", fg, 18))
        line.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(_lbl(row.title, 10, bold=True))
        text_col.addWidget(_lbl(row.provision, 9, color=t.text_muted))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(row.elapsed_pct))
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setStyleSheet(
            f"QProgressBar {{ background:{t.bg_table_alt}; border:none;"
            f"border-radius:2px; }}"
            f"QProgressBar::chunk {{ background:{fg}; border-radius:2px; }}")
        text_col.addWidget(bar)
        line.addLayout(text_col, 1)

        line.addWidget(_pill(row.status, bg, fg))

        due = QLabel(f"Due {row.due_date}")
        due.setStyleSheet(
            f"background:transparent; border:none; color:{t.text_muted};"
            f"font-size:9px;")
        line.addWidget(due, 0, Qt.AlignmentFlag.AlignVCenter)

        if row.source_doc:
            view = QPushButton("View doc")
            view.setFlat(True)
            view.setCursor(Qt.CursorShape.PointingHandCursor)
            view.setStyleSheet(
                f"QPushButton {{ background:transparent; border:none;"
                f"color:{t.accent}; font-size:9px; padding:0; }}"
                f"QPushButton:hover {{ color:{t.accent_hover};"
                f"text-decoration:underline; }}")
            view.clicked.connect(
                lambda clicked=False, c=case, doc_id=row.source_doc:
                self._open_doc(c, doc_id))
            line.addWidget(view, 0, Qt.AlignmentFlag.AlignVCenter)
        return frame

    # ------------------------------------------------------------------
    # Modals / toast
    # ------------------------------------------------------------------

    def _open_doc(self, case, doc_id: str) -> None:
        modal = EprocDocModal(case, doc_id, self)
        modal.tabRequested.connect(self._on_modal_tab)
        modal.exec()

    def _on_modal_tab(self, tab: str) -> None:
        if tab in _TAB_KEYS:
            self._switch_tab(tab)

    def _toast(self, text: str, duration: int = 2500) -> None:
        if self._toast_label is None:
            return
        self._toast_seq += 1
        seq = self._toast_seq
        self._toast_label.setText(text)
        self._toast_label.adjustSize()
        self._position_toast()
        self._toast_label.raise_()
        self._toast_label.setVisible(True)
        QTimer.singleShot(duration, lambda: self._hide_toast(seq))

    def _hide_toast(self, seq: int) -> None:
        if seq == self._toast_seq and self._toast_label is not None:
            self._toast_label.setVisible(False)

    def _position_toast(self) -> None:
        if self._toast_label is None or not self._toast_label.isVisible():
            return
        label = self._toast_label
        width = min(label.width(), max(0, self.width() - 40))
        x = max(0, (self.width() - width) // 2)
        y = max(0, self.height() - label.height() - 18)
        label.move(x, y)

    def resizeEvent(self, event):  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        self._position_toast()

"""Chronological document timeline for the e-Proceedings case workspace.

The widget is deliberately presentation-only: it consumes a ``Case`` and an
optional status map produced by :func:`ui.eproceedings_model.derive_status`,
then renders one node per document, oldest first.
"""

from __future__ import annotations

import html
import os
from datetime import date, timedelta

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui._theme import _t
from ui.eproceedings_model import _parse_date
from ui.widgets import ClickableCard


_KIND_TINT = {
    "notice": ("accent_light", "accent"),
    "reply": ("success_bg", "success"),
    "order": ("accent_light", "accent_mca"),
    "penalty": ("error_bg", "error"),
    "appeal-order": ("warning_bg", "warning"),
    "remand": ("warning_bg", "warning"),
}

_KIND_DOT = {
    "notice": "accent",
    "reply": "success",
    "order": "accent_mca",
    "penalty": "error",
    "appeal-order": "warning",
    "remand": "warning",
}


class _Gutter(QWidget):
    """Tiny painted column: a connector line with a centred status dot."""

    def __init__(self, color: str, first: bool, last: bool, parent=None):
        super().__init__(parent)
        self._color = color
        self._first = first
        self._last = last
        self.setFixedWidth(20)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Expanding)

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = _t()
        width = self.width()
        height = self.height()
        x = width / 2.0
        centre = height / 2.0

        painter.setPen(QPen(QColor(t.grid), 1))
        if self._first and self._last:
            pass
        elif self._first:
            painter.drawLine(QPointF(x, centre), QPointF(x, height))
        elif self._last:
            painter.drawLine(QPointF(x, 0), QPointF(x, centre))
        else:
            painter.drawLine(QPointF(x, 0), QPointF(x, height))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(QPointF(x, centre), 4, 4)


def _lookup(case, doc_id: str):
    for item in getattr(case, "docs", []) or []:
        if item.id == doc_id:
            return item
    return None


def _short(text: str, limit: int = 30) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _kind_tint(kind: str):
    t = _t()
    bg_name, fg_name = _KIND_TINT.get(
        kind, ("bg_table_alt", "text_muted"))
    return getattr(t, bg_name), getattr(t, fg_name)


def _status_tint(status: str):
    t = _t()
    key = (status or "").strip().lower()
    if key in ("replied", "closed"):
        return t.success_bg, t.success
    if key in ("overdue", "limitation expired"):
        return t.error_bg, t.error
    if key in ("open", "appeal window", "2nd appeal window"):
        return t.warning_bg, t.warning
    if key in ("under appeal", "remanded"):
        return t.accent_light, t.accent
    return t.bg_table_alt, t.text_muted


def _chip(text: str, bg: str, fg: str) -> QLabel:
    label = QLabel((text or "").upper())
    label.setStyleSheet(
        f"background:{bg}; color:{fg}; border:none; border-radius:8px;"
        f"padding:2px 7px; font-size:9px; font-weight:600;")
    return label


def _muted_label(text: str, size: int = 10) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"background:transparent; border:none; color:{_t().text_muted};"
        f"font-size:{size}px;")
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return label


def _link(target: str, text: str) -> str:
    accent = _t().accent
    return (
        f'<a href="{html.escape(target, quote=True)}" '
        f'style="color:{accent}; text-decoration:none;">'
        f"{html.escape(text)}</a>"
    )


class EprocTimeline(QScrollArea):
    """Vertical oldest-to-newest timeline of a case's documents."""

    docActivated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        self._case = None
        self._status_map: dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_case(self, case, status_map: dict) -> None:
        """Render ``case`` using ``status_map`` ({doc_id: status_text})."""
        self._case = case
        self._status_map = dict(status_map or {})
        self._rebuild()

    # ------------------------------------------------------------------
    # Content construction
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        old = self.takeWidget()
        if old is not None:
            old.deleteLater()

        t = _t()
        content = QWidget()
        content.setStyleSheet(f"background:{t.bg_window};")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(0)

        docs = list(getattr(self._case, "docs", []) or []) if self._case else []
        if not docs:
            empty = QLabel("No documents in this case yet.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                f"color:{t.text_muted}; font-size:11px;"
                f"background:transparent; border:none; padding:32px 0;")
            layout.addWidget(empty)
            layout.addStretch(1)
            self.setWidget(content)
            return

        ordered = self._chronological(docs)
        last = len(ordered) - 1
        for index, doc in enumerate(ordered):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            gutter = _Gutter(
                getattr(t, _KIND_DOT.get(doc.kind, "text_muted")),
                first=(index == 0), last=(index == last))
            row.addWidget(gutter)
            row.addWidget(self._make_card(doc), 1)
            layout.addLayout(row)

        layout.addStretch(1)
        self.setWidget(content)

    @staticmethod
    def _chronological(docs):
        def key(doc):
            parsed = _parse_date(doc.issued) or _parse_date(doc.served)
            return (0, parsed) if parsed is not None else (1, date.max)

        return sorted(docs, key=key)

    def _make_card(self, doc) -> ClickableCard:
        t = _t()
        card = ClickableCard()
        card.setObjectName("EprocTimelineCard")
        card.setStyleSheet(
            f"QFrame#EprocTimelineCard {{"
            f"background:{t.bg_panel}; border:1px solid {t.border};"
            f"border-radius:8px; }}"
            f"QFrame#EprocTimelineCard:hover {{"
            f"border:1px solid {t.accent}; }}")
        card.clicked.connect(
            lambda doc_id=doc.id: self.docActivated.emit(doc_id))

        body = QVBoxLayout(card)
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        kind_bg, kind_fg = _kind_tint(doc.kind)
        top.addWidget(_chip(doc.kind.replace("-", " "), kind_bg, kind_fg))

        status_text = self._status_map.get(doc.id, doc.status or "")
        if status_text:
            status_bg, status_fg = _status_tint(status_text)
            top.addWidget(_chip(status_text, status_bg, status_fg))

        top.addStretch(1)
        if (doc.urg or "").strip().lower() == "high":
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(
                f"background:{t.error}; border:none; border-radius:4px;")
            dot.setToolTip("High urgency")
            top.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(top)

        title = QLabel(doc.title)
        title.setWordWrap(True)
        title.setStyleSheet(
            f"background:transparent; border:none; color:{t.text_primary};"
            f"font-size:11px; font-weight:bold;")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.addWidget(title)

        sub_parts = []
        if (doc.section or "").strip():
            sub_parts.append(f"Section {doc.section.strip()}")
        if (doc.issued or "").strip():
            sub_parts.append(f"Issued {doc.issued.strip()}")
        if sub_parts:
            sub = _muted_label(" · ".join(sub_parts))
            body.addWidget(sub)

        annotation = self._annotation(doc)
        if annotation:
            body.addWidget(annotation)

        if doc.files:
            path = self._file_path(doc.files[0])
            open_btn = QPushButton("Open file")
            open_btn.setFlat(True)
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{t.accent};"
                f"border:none; font-size:9px; padding:0; text-align:left; }}"
                f"QPushButton:hover {{ color:{t.accent_hover};"
                f"text-decoration:underline; }}")
            open_btn.clicked.connect(
                lambda _checked=False, target=path: self._open_file(target))
            file_row = QHBoxLayout()
            file_row.setContentsMargins(0, 0, 0, 0)
            file_row.addWidget(open_btn)
            file_row.addStretch(1)
            body.addLayout(file_row)

        return card

    def _annotation(self, doc):
        t = _t()
        pieces = []

        if doc.kind == "penalty" and doc.triggered_by:
            target = _lookup(self._case, doc.triggered_by)
            short = _short(target.title if target else doc.triggered_by)
            text = f"Issued subsequent to {_link(doc.triggered_by, short)}"
            if (doc.inferred or {}).get("triggered_by"):
                text += " (inferred)"
            pieces.append(text)

        elif doc.kind == "reply" and doc.parent:
            target = _lookup(self._case, doc.parent)
            short = _short(target.title if target else doc.parent)
            pieces.append(f"Reply to {_link(doc.parent, short)}")

        elif doc.kind == "remand" and doc.remands:
            target = _lookup(self._case, doc.remands)
            short = _short(target.title if target else doc.remands)
            pieces.append(
                f"Set aside and remanded {_link(doc.remands, short)}"
                " — fresh phase")

        elif doc.kind in ("order", "appeal-order"):
            appeals = getattr(self._case, "appeals", []) or []
            filed = any(appeal.against == doc.id for appeal in appeals)
            if filed:
                pieces.append("Appeal filed")
            else:
                issued = _parse_date(doc.issued) or _parse_date(doc.served)
                if issued is not None:
                    days = 30 if doc.kind == "order" else 60
                    deadline = issued + timedelta(days=days)
                    remaining = (deadline - date.today()).days
                    if remaining > 0:
                        pieces.append(f"{remaining}d left")

        if not pieces:
            return None

        label = QLabel(" · ".join(pieces))
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(False)
        label.setStyleSheet(
            f"background:transparent; border:none; color:{t.text_muted};"
            f"font-size:10px;")
        label.linkActivated.connect(self.docActivated.emit)
        if "<a " not in label.text():
            label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        return label

    def _file_path(self, rel: str) -> str:
        rel = (rel or "").strip()
        if not rel:
            return ""
        if os.path.isabs(rel):
            return rel
        proc_dir = getattr(self._case, "proc_dir", "") or ""
        if not proc_dir:
            return rel
        joined = os.path.join(proc_dir, rel.replace("/", os.sep))
        norm_rel = os.path.normpath(rel)
        norm_dir = os.path.normpath(proc_dir)
        if norm_rel == norm_dir or norm_rel.startswith(norm_dir + os.sep):
            return norm_rel
        return joined

    @staticmethod
    def _open_file(path: str) -> None:
        if not path:
            return
        try:
            from config import _open_path
        except Exception:
            return
        _open_path(path)

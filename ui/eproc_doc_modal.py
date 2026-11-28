"""Cross-linking document modal for the e-Proceedings case workspace."""

from __future__ import annotations

import html
import os

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from automation.doc_types import e_proceeding_doc_label
from ui._theme import _t
from ui.helpers import _btn, _lbl


class EprocDocModal(QDialog):
    """Document detail modal that can swap between linked documents in place."""

    tabRequested = pyqtSignal(str)

    def __init__(self, case, doc_id: str, parent=None):
        super().__init__(parent)
        self._case = case
        self._current = doc_id
        self._history: list[str] = []
        self._related_ids: list[str] = []
        self.attachment_rows: list[str] = []
        self._toast_seq = 0
        self._content_layout: QVBoxLayout | None = None

        self.setWindowTitle("Document")
        self.setModal(True)
        self.setMinimumSize(640, 620)
        self.resize(640, 620)
        self.setSizeGripEnabled(True)

        t = _t()
        self.setStyleSheet(f"QDialog {{ background:{t.bg_window}; }}")
        self._build_shell()
        self._render(doc_id)

    # -- shell -----------------------------------------------------------

    def _build_shell(self) -> None:
        t = _t()
        main = QVBoxLayout(self)
        main.setContentsMargins(18, 16, 18, 14)
        main.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)

        icon = QLabel()
        icon.setFixedSize(36, 36)
        icon.setStyleSheet("background:transparent;")
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "resources",
            "app_icon.png",
        )
        if os.path.isfile(icon_path):
            icon.setPixmap(QPixmap(icon_path).scaled(
                36, 36,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        header.addWidget(icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._kind_lbl = _lbl("", 10, bold=True, color=t.text_muted)
        self._title_lbl = _lbl("", 15, bold=True)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        text_col.addWidget(self._kind_lbl)
        text_col.addWidget(self._title_lbl)
        header.addLayout(text_col, 1)

        self._back_btn = _btn("Back", "outline", height=28, min_width=56)
        self._back_btn.clicked.connect(self._go_back)
        self._back_btn.setVisible(False)
        header.addWidget(self._back_btn)

        close_btn = _btn("✕", "outline", height=28, min_width=32)
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)
        main.addLayout(header)

        main.addWidget(self._separator())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:transparent; border:none; }}")

        content = QWidget()
        content.setObjectName("docContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setStyleSheet(
            f"#docContent {{ background:transparent; }}")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 6, 0)
        self._content_layout.setSpacing(10)
        scroll.setWidget(content)
        main.addWidget(scroll, 1)

        main.addWidget(self._separator())

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._toast_label = _lbl("", 11, bold=True, color=t.success)
        self._toast_label.setStyleSheet(
            f"color:{t.success}; background:{t.success_bg}; "
            f"border-radius:4px; padding:4px 8px; font-size:11px; "
            f"font-weight:bold;")
        self._toast_label.setVisible(False)
        footer.addWidget(self._toast_label, 0)
        footer.addStretch(1)

        download_btn = _btn("Download", "outline", height=34)
        download_btn.clicked.connect(self._show_download_toast)
        footer.addWidget(download_btn)

        limitations_btn = _btn("Limitations", "outline", height=34)
        limitations_btn.clicked.connect(
            lambda: self._go_to_tab("limitations"))
        footer.addWidget(limitations_btn)

        timeline_btn = _btn("View in timeline", "primary", height=34)
        timeline_btn.clicked.connect(
            lambda: self._go_to_tab("timeline"))
        footer.addWidget(timeline_btn)
        main.addLayout(footer)

    def _separator(self) -> QFrame:
        t = _t()
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            f"background:{t.border}; border:none; max-height:1px;")
        return sep

    # -- rendering -------------------------------------------------------

    def _find(self, doc_id: str):
        for doc in self._case.docs:
            if doc.id == doc_id:
                return doc
        return None

    @staticmethod
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
                EprocDocModal._clear_layout(child)
                child.deleteLater()

    def _render(self, doc_id: str) -> None:
        doc = self._find(doc_id)
        if doc is None or self._content_layout is None:
            return

        t = _t()
        kind = (doc.kind or "").replace("-", " ").upper()
        subject = f"{kind} · {doc.section}" if doc.section else kind
        self._kind_lbl.setText(subject)

        title = doc.title or kind.title()
        short_id = doc.id.rsplit("#", 1)[-1]
        if title == (self._case.proc_name or ""):
            title = f"{title} · {short_id}"
        self._title_lbl.setText(title)
        self.setWindowTitle(title)
        self._back_btn.setVisible(bool(self._history))

        self._clear_layout(self._content_layout)
        self.attachment_rows = []

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for label, value in (
            ("Issued", doc.issued),
            ("Served", doc.served),
            ("Reply deadline", doc.reply_deadline),
            ("Response viewed by AO", doc.viewed_by_ao),
        ):
            if value:
                chips.addWidget(self._date_chip(f"{label} {value}"))
        if doc.status:
            chips.addWidget(self._status_chip(doc.status))
        chips.addStretch(1)
        self._content_layout.addLayout(chips)

        if doc.note:
            self._content_layout.addWidget(self._note_block(doc.note))

        self._content_layout.addWidget(self._section_label("Assessee"))
        self._content_layout.addWidget(self._assessee_block())

        self._add_documents_section(doc)

        self._content_layout.addWidget(self._section_label("Related documents"))
        entries = self._related_entries(doc)
        self._related_ids = [target_id for target_id, _label in entries]
        if entries:
            for target_id, label in entries:
                self._content_layout.addWidget(
                    self._linked_button(target_id, label))
        else:
            self._content_layout.addWidget(
                _lbl("No linked documents.", 11, color=t.text_muted))

        self._content_layout.addStretch(1)

    def _add_documents_section(self, doc) -> None:
        """List every file saved for this document.

        Order folders can carry an Order/Assessment Order, a Demand Notice and
        a Computation Sheet together, so one doc may own several attachments.
        """
        files = [rel for rel in (doc.files or []) if (rel or "").strip()]
        if not files:
            return

        self._content_layout.addWidget(self._section_label("Documents"))
        for rel in files:
            name = os.path.basename(rel)
            label = e_proceeding_doc_label(name)
            self.attachment_rows.append(label)
            self._content_layout.addWidget(self._attachment_row(rel, label, name))

    def _attachment_row(self, rel: str, label: str, name: str) -> QFrame:
        t = _t()
        frame = QFrame()
        frame.setObjectName("docAttachment")
        frame.setStyleSheet(
            f"#docAttachment {{ background:{t.bg_panel}; "
            f"border:1px solid {t.border}; border-radius:6px; }}")

        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 8, 10, 8)
        row.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.addWidget(_lbl(label, 12, bold=True))
        filename_lbl = _lbl(name, 10, color=t.text_muted)
        filename_lbl.setWordWrap(True)
        text_col.addWidget(filename_lbl)
        row.addLayout(text_col, 1)

        open_btn = _btn("Open", "outline", height=28, min_width=56)
        open_btn.clicked.connect(
            lambda _checked=False, target=rel: self._open_file(
                self._file_path(target)))
        row.addWidget(open_btn, 0)
        return frame

    def _file_path(self, rel: str) -> str:
        rel = (rel or "").strip()
        if not rel:
            return ""
        if os.path.isabs(rel):
            return rel
        proc_dir = getattr(self._case, "proc_dir", "") or ""
        if not proc_dir:
            return rel
        return os.path.join(proc_dir, rel.replace("/", os.sep))

    @staticmethod
    def _open_file(path: str) -> None:
        if not path:
            return
        try:
            from config import _open_path
        except Exception:
            return
        _open_path(path)

    def _date_chip(self, text: str) -> QLabel:
        t = _t()
        chip = QLabel(text)
        chip.setStyleSheet(
            f"QLabel {{ color:{t.text_primary}; background:{t.bg_table_alt}; "
            f"border:1px solid {t.border}; border-radius:10px; "
            f"padding:3px 9px; font-size:11px; }}")
        return chip

    def _status_chip(self, status: str) -> QLabel:
        t = _t()
        key = status.strip().lower()
        if key in ("replied", "closed", "satisfied"):
            fg, bg = t.success, t.success_bg
        elif key in ("overdue", "limitation expired") or "overdue" in key \
                or "expired" in key:
            fg, bg = t.error, t.error_bg
        elif key in ("open", "appeal window", "2nd appeal window") \
                or "window" in key:
            fg, bg = t.warning, t.warning_bg
        elif key in ("under appeal", "remanded"):
            fg, bg = t.accent, t.accent_light
        else:
            fg, bg = t.text_muted, t.bg_table_alt

        chip = QLabel(status)
        chip.setStyleSheet(
            f"QLabel {{ color:{fg}; background:{bg}; "
            f"border:1px solid {fg}; border-radius:10px; "
            f"padding:3px 9px; font-size:11px; font-weight:bold; }}")
        return chip

    def _note_block(self, note: str) -> QFrame:
        t = _t()
        frame = QFrame()
        frame.setObjectName("docNote")
        frame.setStyleSheet(
            f"#docNote {{ background:{t.bg_table_alt}; border:none; "
            f"border-left:3px solid {t.accent}; border-radius:4px; }}")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        label = QLabel(note)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setStyleSheet(
            f"color:{t.text_primary}; background:transparent; font-size:12px;")
        lay.addWidget(label, 1)
        return frame

    def _section_label(self, text: str) -> QLabel:
        return _lbl(text.upper(), 10, bold=True, color=_t().text_muted)

    def _assessee_block(self) -> QFrame:
        t = _t()
        assessee = self._case.assessee
        frame = QFrame()
        frame.setObjectName("assesseeBlock")
        frame.setStyleSheet(
            f"#assesseeBlock {{ background:{t.bg_panel}; "
            f"border:1px solid {t.border}; border-radius:6px; }}")

        lay = QHBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)

        name = html.escape(assessee.name or "")
        pan = html.escape(assessee.pan or "")
        email = html.escape(assessee.email or "")
        phone = html.escape(assessee.phone or "")
        ward = html.escape(assessee.ward or "")

        lines = [
            f"<span style='font-size:13px; font-weight:bold;'>{name}</span>"
        ]
        if pan:
            lines.append(f"PAN: {pan}")
        if email:
            lines.append(
                f"Email: <a href='mailto:{html.escape(assessee.email, quote=True)}'"
                f" style='color:{t.accent}; text-decoration:none;'>{email}</a>")
        if phone:
            lines.append(
                f"Phone: <a href='tel:{html.escape(assessee.phone, quote=True)}'"
                f" style='color:{t.accent}; text-decoration:none;'>{phone}</a>")
        if ward:
            lines.append(f"Ward: {ward}")

        label = QLabel("<br>".join(lines))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        label.setStyleSheet(
            f"color:{t.text_primary}; background:transparent; font-size:12px;")
        lay.addWidget(label, 1)
        return frame

    def _doc_label(self, doc, with_kind: bool = True) -> str:
        title = doc.title or doc.id
        marker = doc.issued or doc.served or doc.id.rsplit("#", 1)[-1]
        if not with_kind:
            return f"{title} · {marker}"
        kind = (doc.kind or "").replace("-", " ").title()
        return f"{kind} · {title} · {marker}"

    def _related_entries(self, doc) -> list[tuple[str, str]]:
        by_id = {item.id: item for item in self._case.docs}
        entries: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add_doc(target_id: str, prefix: str = "",
                    inferred: bool = False) -> None:
            if not target_id or target_id == doc.id:
                return
            target = by_id.get(target_id)
            if target is None:
                return
            key = ("doc", target_id)
            if key in seen:
                return
            seen.add(key)
            label = f"{prefix}{self._doc_label(target, with_kind=not prefix)}"
            if inferred:
                label += " (inferred)"
            entries.append((target_id, label))

        def add_appeal(appeal) -> None:
            key = ("appeal", appeal.id)
            if key in seen:
                return
            seen.add(key)
            entries.append((
                appeal.against,
                f"Appeal: {appeal.forum} {appeal.id}",
            ))

        if doc.kind == "penalty" and doc.triggered_by:
            add_doc(doc.triggered_by, "Triggered by order: ",
                    bool(doc.inferred.get("triggered_by")))

        if doc.kind == "reply" and doc.parent:
            add_doc(doc.parent, "Parent notice: ",
                    bool(doc.inferred.get("parent")))

        if doc.kind in ("notice", "penalty"):
            for other in self._case.docs:
                if other.kind == "reply" and other.parent == doc.id:
                    add_doc(other.id, "Reply: ")

        if doc.kind in ("order", "appeal-order"):
            for appeal in self._case.appeals:
                if appeal.against == doc.id:
                    add_appeal(appeal)
            for other in self._case.docs:
                if other.kind == "penalty" and other.triggered_by == doc.id:
                    add_doc(other.id, "Penalty: ",
                            bool(other.inferred.get("triggered_by")))

        if doc.kind == "remand" and doc.remands:
            add_doc(doc.remands, "Remanded order: ",
                    bool(doc.inferred.get("remands")))

        return entries

    def _linked_button(self, target_id: str, label: str) -> QPushButton:
        t = _t()
        btn = QPushButton(label)
        btn.setMinimumHeight(32)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(label)
        btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(
            f"QPushButton {{ background:{t.bg_input}; color:{t.accent}; "
            f"border:1px solid {t.border}; border-radius:6px; "
            f"padding:7px 10px; text-align:left; font-size:12px; "
            f"font-weight:600; }}"
            f"QPushButton:hover {{ background:{t.accent_light}; "
            f"border-color:{t.accent}; }}"
            f"QPushButton:pressed {{ background:{t.bg_table_alt}; }}")
        btn.clicked.connect(
            lambda _checked=False, tid=target_id: self.show_doc(tid))
        return btn

    # -- navigation / actions -------------------------------------------

    def show_doc(self, doc_id: str) -> None:
        """Swap the modal content to another doc in the same case (in place)."""
        if self._find(doc_id) is None:
            return
        if doc_id == self._current:
            self._render(doc_id)
            return

        self._history.append(self._current)
        self._current = doc_id
        self._render(doc_id)

    def _go_back(self) -> None:
        if not self._history:
            return
        self._current = self._history.pop()
        self._render(self._current)

    def _go_to_tab(self, tab: str) -> None:
        self.tabRequested.emit(tab)
        self.accept()

    def _show_download_toast(self) -> None:
        self._toast_seq += 1
        seq = self._toast_seq
        self._toast_label.setText("Download not available in this preview")
        self._toast_label.setVisible(True)
        QTimer.singleShot(2000, lambda: self._hide_toast(seq))

    def _hide_toast(self, seq: int) -> None:
        if seq == self._toast_seq:
            self._toast_label.setVisible(False)

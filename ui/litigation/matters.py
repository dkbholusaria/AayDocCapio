"""ui/litigation/matters.py — F-26 Clients / Matters with fee tracking.

Master–detail view: matters on the left, the selected matter's linked cases and
fee/billing/reimbursement ledger on the right, with running totals.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QComboBox, QLineEdit, QTextEdit, QDialog,
    QDialogButtonBox, QFormLayout, QMessageBox, QDoubleSpinBox, QListWidget,
    QListWidgetItem,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ui._theme import _t
from ui.helpers import _lbl, _btn
from core.litigation.model import (
    FEE_KINDS, FEE_KIND_LABELS, FEE_STATUSES, FEE_STATUS_LABELS, matter_totals,
)

_FEE_COLS = ("Kind", "Label", "Amount (₹)", "Status", "Date", "Note")


class LitigationMatters(QWidget):
    """Clients / Matters master-detail with a fee ledger."""

    def __init__(self, store, handlers, parent=None):
        super().__init__(parent)
        self._store = store
        self._h = handlers
        self._cases = []
        self._matters = []
        self._current_matter = None
        self._build()

    def _build(self):
        t = _t()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 12, 24, 16)
        outer.setSpacing(10)

        bar = QHBoxLayout()
        self._new_btn = _btn("New Matter", "primary", height=32)
        self._new_btn.clicked.connect(self._new_matter)
        bar.addWidget(self._new_btn)
        self._edit_btn = _btn("Edit", "secondary", height=32)
        self._edit_btn.clicked.connect(self._edit_matter)
        bar.addWidget(self._edit_btn)
        self._delete_btn = _btn("Delete", "secondary", height=32)
        self._delete_btn.clicked.connect(self._delete_matter)
        bar.addWidget(self._delete_btn)
        bar.addStretch(1)
        outer.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(_lbl("Matters", 11, bold=True, color=t.text_muted))
        self._matter_list = QListWidget()
        self._matter_list.setStyleSheet(self._list_qss(t))
        self._matter_list.currentRowChanged.connect(self._on_matter_selected)
        left.addWidget(self._matter_list, 1)
        body.addLayout(left, 2)

        right = QVBoxLayout()
        right.setSpacing(8)
        self._detail_title = _lbl("Select a matter", 14, bold=True)
        right.addWidget(self._detail_title)
        self._rollup = _lbl("", 11, color=t.text_muted)
        right.addWidget(self._rollup)

        right.addWidget(_lbl("Linked cases", 11, bold=True, color=t.text_muted))
        self._cases_list = QListWidget()
        self._cases_list.setStyleSheet(self._list_qss(t))
        self._cases_list.setMaximumHeight(130)
        right.addWidget(self._cases_list)
        self._link_btn = _btn("Link a case…", "secondary", height=30)
        self._link_btn.clicked.connect(self._link_case)
        right.addWidget(self._link_btn)

        right.addWidget(_lbl("Fees / Billing / Reimbursements", 11, bold=True,
                             color=t.text_muted))
        self._fee_table = QTableWidget(0, len(_FEE_COLS))
        self._fee_table.setHorizontalHeaderLabels(list(_FEE_COLS))
        self._fee_table.verticalHeader().setVisible(False)
        self._fee_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._fee_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._fee_table.horizontalHeader().setStretchLastSection(True)
        self._fee_table.setStyleSheet(self._table_qss(t))
        right.addWidget(self._fee_table, 1)

        fee_bar = QHBoxLayout()
        self._add_fee_btn = _btn("Add entry", "primary", height=30)
        self._add_fee_btn.clicked.connect(self._add_fee)
        fee_bar.addWidget(self._add_fee_btn)
        self._del_fee_btn = _btn("Delete entry", "secondary", height=30)
        self._del_fee_btn.clicked.connect(self._delete_fee)
        fee_bar.addWidget(self._del_fee_btn)
        fee_bar.addStretch(1)
        self._totals_lbl = _lbl("", 11, color=t.text_primary)
        fee_bar.addWidget(self._totals_lbl)
        right.addLayout(fee_bar)

        body.addLayout(right, 5)
        outer.addLayout(body, 1)

    # -- data -----------------------------------------------------------

    def set_data(self, cases):
        self._cases = cases
        self._reload_matters()

    def _reload_matters(self):
        self._matters = sorted(
            self._store.matters(), key=lambda m: (
                m.client_name.lower(), m.title.lower()))
        self._matter_list.blockSignals(True)
        self._matter_list.clear()
        for m in self._matters:
            item = QListWidgetItem(f"{m.client_name or m.client_pan} — {m.title}")
            item.setData(Qt.ItemDataRole.UserRole, m.id)
            self._matter_list.addItem(item)
        self._matter_list.blockSignals(False)
        if self._matters:
            self._matter_list.setCurrentRow(0)
        else:
            self._current_matter = None
            self._detail_title.setText("No matters yet — create one above.")
            self._rollup.setText("")
            self._cases_list.clear()
            self._fee_table.setRowCount(0)
            self._totals_lbl.setText("")

    def matter_options(self):
        return [(m.id, m.client_name or m.client_pan, m.title)
                for m in self._matters]

    def _on_matter_selected(self, row):
        if 0 <= row < len(self._matters):
            self._current_matter = self._matters[row]
        else:
            self._current_matter = None
        self._render_detail()

    def _render_detail(self):
        m = self._current_matter
        if m is None:
            return
        self._detail_title.setText(f"{m.client_name or m.client_pan} — {m.title}")
        self._rollup.setText(m.description or "")
        self._render_cases()
        self._render_fees()

    def _render_cases(self):
        self._cases_list.clear()
        linked = [c for c in self._cases if c.matter_id == self._current_matter.id]
        for c in linked:
            item = QListWidgetItem(
                f"{c.module_label} · {c.title} · {c.status}")
            item.setData(Qt.ItemDataRole.UserRole, c.uid)
            self._cases_list.addItem(item)
        if not linked:
            item = QListWidgetItem("No cases linked yet.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor(_t().text_muted))
            self._cases_list.addItem(item)

    def _render_fees(self):
        t = _t()
        fees = self._store.fees(self._current_matter.id)
        self._fee_table.setRowCount(len(fees))
        for row, f in enumerate(fees):
            values = (
                FEE_KIND_LABELS.get(f.kind, f.kind),
                f.label,
                f"{f.amount:,.2f}",
                FEE_STATUS_LABELS.get(f.status, f.status),
                f.date or "—",
                f.note or "",
            )
            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                item.setForeground(QColor(t.text_primary))
                if col == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                self._fee_table.setItem(row, col, item)
        self._fee_table.resizeColumnsToContents()
        totals = matter_totals(fees)
        self._totals_lbl.setText(
            f"Agreed ₹{totals['agreed']:,.0f}  ·  "
            f"Billed ₹{totals['billed']:,.0f}  ·  "
            f"Received ₹{totals['received']:,.0f}  ·  "
            f"Outstanding ₹{totals['outstanding']:,.0f}  ·  "
            f"Reimbursed ₹{totals['reimbursed']:,.0f}")

    # -- matter actions -------------------------------------------------

    def _new_matter(self):
        dlg = _MatterDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        self._store.add_matter(
            data["client_pan"], data["client_name"], data["title"],
            data["description"])
        self._h.on_changed()

    def _edit_matter(self):
        if self._current_matter is None:
            return
        m = self._current_matter
        dlg = _MatterDialog(self, client_pan=m.client_pan,
                            client_name=m.client_name, title=m.title,
                            description=m.description)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        self._store.update_matter(
            m.id, client_pan=data["client_pan"],
            client_name=data["client_name"], title=data["title"],
            description=data["description"])
        self._h.on_changed()

    def _delete_matter(self):
        if self._current_matter is None:
            return
        ok = QMessageBox.question(
            self, "Delete matter",
            f"Delete “{self._current_matter.title}” and its fee entries?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ok != QMessageBox.StandardButton.Yes:
            return
        self._store.delete_matter(self._current_matter.id)
        self._h.on_changed()

    def _link_case(self):
        if self._current_matter is None:
            return
        unlinked = [c for c in self._cases if not c.matter_id]
        if not unlinked:
            QMessageBox.information(self, "Link a case",
                                    "Every case is already linked to a matter.")
            return
        labels = [f"{c.module_label} · {c.client_name} · {c.title}"
                  for c in unlinked]
        from PyQt6.QtWidgets import QInputDialog
        chosen, ok = QInputDialog.getItem(
            self, "Link a case", "Case:", labels, 0, False)
        if ok and chosen:
            idx = labels.index(chosen)
            self._store.link_case(unlinked[idx].uid, self._current_matter.id)
            self._h.on_changed()

    # -- fee actions ----------------------------------------------------

    def _add_fee(self):
        if self._current_matter is None:
            return
        dlg = _FeeDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result_data()
        self._store.add_fee(
            self._current_matter.id, data["kind"], data["label"],
            data["amount"], data["status"], data["date"], data["note"])
        self._h.on_changed()

    def _delete_fee(self):
        row = self._fee_table.currentRow()
        if row < 0 or self._current_matter is None:
            return
        fees = self._store.fees(self._current_matter.id)
        if 0 <= row < len(fees):
            self._store.delete_fee(fees[row].id)
            self._h.on_changed()

    # -- theme ----------------------------------------------------------

    def repaint_theme(self, t):
        self._matter_list.setStyleSheet(self._list_qss(t))
        self._cases_list.setStyleSheet(self._list_qss(t))
        self._fee_table.setStyleSheet(self._table_qss(t))

    @staticmethod
    def _list_qss(t):
        return (
            "QListWidget {"
            f" background:{t.bg_table}; border:1.5px solid {t.border};"
            " border-radius:8px; outline:0; }"
            "QListWidget::item { padding:6px; }"
            f"QListWidget::item:selected {{ background:{t.row_selected_bg};"
            f" color:{t.row_selected_fg}; }}"
        )

    @staticmethod
    def _table_qss(t):
        return (
            "QTableWidget {"
            f" background:{t.bg_table}; gridline-color:{t.grid};"
            f" border:1.5px solid {t.border}; border-radius:8px; outline:0; }}"
            "QHeaderView::section {"
            f" background:{t.bg_header}; color:{t.text_muted};"
            f" border:none; border-bottom:1px solid {t.border}; padding:6px; }}"
        )


class _MatterDialog(QDialog):
    def __init__(self, parent=None, client_pan="", client_name="", title="",
                 description=""):
        super().__init__(parent)
        self.setWindowTitle("Matter")
        self.setMinimumWidth(420)
        self._pan = QLineEdit(client_pan)
        self._name = QLineEdit(client_name)
        self._title = QLineEdit(title)
        self._desc = QTextEdit()
        self._desc.setPlainText(description)
        self._desc.setFixedHeight(80)
        form = QFormLayout(self)
        form.addRow("Client PAN", self._pan)
        form.addRow("Client name", self._name)
        form.addRow("Matter title", self._title)
        form.addRow("Description", self._desc)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def result_data(self):
        return {
            "client_pan": self._pan.text().strip().upper(),
            "client_name": self._name.text().strip(),
            "title": self._title.text().strip() or "Untitled matter",
            "description": self._desc.toPlainText().strip(),
        }


class _FeeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fee entry")
        self.setMinimumWidth(380)
        self._kind = QComboBox()
        for k in FEE_KINDS:
            self._kind.addItem(FEE_KIND_LABELS[k], k)
        self._label = QLineEdit()
        self._amount = QDoubleSpinBox()
        self._amount.setMaximum(1_000_000_000)
        self._amount.setGroupSeparatorShown(True)
        self._status = QComboBox()
        for s in FEE_STATUSES:
            self._status.addItem(FEE_STATUS_LABELS[s], s)
        self._date = QLineEdit()
        self._date.setPlaceholderText("DD-Mon-YYYY")
        self._note = QLineEdit()
        form = QFormLayout(self)
        form.addRow("Kind", self._kind)
        form.addRow("Label", self._label)
        form.addRow("Amount (₹)", self._amount)
        form.addRow("Status", self._status)
        form.addRow("Date", self._date)
        form.addRow("Note", self._note)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def result_data(self):
        return {
            "kind": self._kind.currentData(),
            "label": self._label.text().strip(),
            "amount": self._amount.value(),
            "status": self._status.currentData(),
            "date": self._date.text().strip(),
            "note": self._note.text().strip(),
        }

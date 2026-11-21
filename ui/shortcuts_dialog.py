"""ui/shortcuts_dialog.py — F-17 shortcut editor.

Lists every registered action, captures a new key sequence, blocks duplicate or
unsafe bindings, and persists only user overrides in the vault.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QKeySequenceEdit,
    QAbstractItemView, QMessageBox, QWidget,
)

from ui._theme import _t
from ui.helpers import _btn
from ui import shortcuts as sc


class ShortcutEditorDialog(QDialog):
    def __init__(self, parent=None, vault=None, on_saved=None):
        super().__init__(parent)
        self._vault = vault
        self._on_saved = on_saved
        self._bindings = sc.merge_user_bindings(sc.load_user_bindings(vault))
        self._row_by_action: dict[str, int] = {}
        self._loading = False

        t = _t()
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(720, 560)
        self.resize(760, 620)
        self.setStyleSheet(
            f"QDialog{{background:{t.bg_window};}}"
            f"QLabel{{background:transparent;color:{t.text_primary};}}"
            f"QLineEdit{{background:{t.bg_input};color:{t.text_primary};"
            f"border:1.5px solid {t.border};border-radius:6px;padding:5px 9px;}}"
            f"QLineEdit:focus{{border-color:{t.border_focus};}}"
            f"QKeySequenceEdit{{background:{t.bg_input};color:{t.text_primary};"
            f"border:1.5px solid {t.border};border-radius:6px;padding:3px 6px;}}"
            f"QKeySequenceEdit:focus{{border-color:{t.border_focus};}}"
            f"QTableWidget{{background:{t.bg_table};color:{t.text_primary};"
            f"border:1px solid {t.border};border-radius:6px;gridline-color:{t.grid};}}"
            f"QTableWidget::item{{padding:4px 8px;}}"
            f"QTableWidget::item:selected{{background:{t.accent};color:{t.accent_text};}}"
            f"QHeaderView::section{{background:{t.bg_header};color:{t.text_primary};"
            f"border:none;border-bottom:1px solid {t.border};padding:6px;font-weight:bold;}}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        intro = QLabel(
            "Choose an action, then press the new key combination. "
            "A shortcut needs Ctrl, Alt or Shift (function keys are fine on their own).")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{t.text_muted};font-size:12px;")
        root.addWidget(intro)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search actions…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search actions")
        self.search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search)
        root.addLayout(search_row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAccessibleName("Keyboard shortcut list")
        self.table.setAccessibleDescription(
            "Each row is an action and its current shortcut. "
            "Move with the arrow keys, then use Change Shortcut to edit.")
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.itemDoubleClicked.connect(lambda *_: self._focus_editor())
        root.addWidget(self.table, 1)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)
        self.edit_label = QLabel("New shortcut:")
        edit_row.addWidget(self.edit_label)
        self.editor = QKeySequenceEdit()
        self.editor.setMaximumSequenceLength(1)
        self.editor.setAccessibleName("New shortcut key combination")
        self.editor.keySequenceChanged.connect(self._on_sequence_changed)
        edit_row.addWidget(self.editor, 1)
        self.btn_change = QPushButton("Change Shortcut")
        self.btn_change.clicked.connect(self._focus_editor)
        edit_row.addWidget(self.btn_change)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self._clear_selected)
        edit_row.addWidget(self.btn_clear)
        self.btn_reset_one = QPushButton("Reset This")
        self.btn_reset_one.clicked.connect(self._reset_selected)
        edit_row.addWidget(self.btn_reset_one)
        root.addLayout(edit_row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Shortcut conflicts and validation")
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_reset_all = QPushButton("Reset All")
        self.btn_reset_all.clicked.connect(self._reset_all)
        buttons.addWidget(self.btn_reset_all)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_cancel)
        self.btn_save = QPushButton("Save")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save)
        buttons.addWidget(self.btn_save)
        root.addLayout(buttons)

        self._populate()
        for action in sc.ACTIONS:
            row = self._row_by_action.get(action.id)
            if row is not None:
                self.table.selectRow(row)
                break

    # ── table helpers ────────────────────────────────────────────────────────

    def _populate(self):
        t = _t()
        self._loading = True
        self.table.setRowCount(0)
        self._row_by_action.clear()
        current_group = None
        for action in sc.ACTIONS:
            if action.group != current_group:
                current_group = action.group
                row = self.table.rowCount()
                self.table.insertRow(row)
                group_item = QTableWidgetItem(current_group.upper())
                group_item.setFlags(Qt.ItemFlag.NoItemFlags)
                group_item.setForeground(QColor(t.text_muted))
                self.table.setItem(row, 0, group_item)
                self.table.setItem(row, 1, QTableWidgetItem(""))
                self.table.setSpan(row, 0, 1, 2)
            row = self.table.rowCount()
            self.table.insertRow(row)
            label = QTableWidgetItem(action.label)
            label.setData(Qt.ItemDataRole.UserRole, action.id)
            self.table.setItem(row, 0, label)
            self.table.setItem(row, 1, QTableWidgetItem(self._display(action.id)))
            self._row_by_action[action.id] = row
        self._loading = False
        self._validate()

    def _display(self, action_id: str) -> str:
        seq = self._bindings.get(action_id, "")
        if not seq:
            return "Unassigned"
        return QKeySequence(seq).toString(QKeySequence.SequenceFormat.NativeText)

    def _selected_action(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        if not item:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _on_row_selected(self):
        action_id = self._selected_action()
        if not action_id:
            return
        self._loading = True
        seq = self._bindings.get(action_id, "")
        self.editor.setKeySequence(QKeySequence(seq) if seq else QKeySequence())
        self._loading = False
        action = sc.ACTIONS_BY_ID.get(action_id)
        self.edit_label.setText(f"New shortcut for “{action.label}”:" if action else "New shortcut:")
        self.btn_change.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.btn_reset_one.setEnabled(True)

    def _focus_editor(self):
        if self._selected_action():
            self.editor.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _on_sequence_changed(self, sequence: QKeySequence):
        if self._loading:
            return
        action_id = self._selected_action()
        if not action_id:
            return
        portable = sequence.toString(QKeySequence.SequenceFormat.PortableText)
        self._bindings[action_id] = sc.normalize(portable)
        self._refresh_row(action_id)
        self._validate()

    def _clear_selected(self):
        action_id = self._selected_action()
        if not action_id:
            return
        self._bindings[action_id] = ""
        self._loading = True
        self.editor.clear()
        self._loading = False
        self._refresh_row(action_id)
        self._validate()

    def _reset_selected(self):
        action_id = self._selected_action()
        if not action_id:
            return
        self._bindings[action_id] = sc.defaults().get(action_id, "")
        self._loading = True
        seq = self._bindings[action_id]
        self.editor.setKeySequence(QKeySequence(seq) if seq else QKeySequence())
        self._loading = False
        self._refresh_row(action_id)
        self._validate()

    def _reset_all(self):
        if QMessageBox.question(
            self, "Reset all shortcuts",
            "Restore every shortcut to its default?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._bindings = sc.defaults()
        self._populate()
        self._validate()

    def _refresh_row(self, action_id: str):
        row = self._row_by_action.get(action_id)
        if row is None:
            return
        item = self.table.item(row, 1)
        if item:
            item.setText(self._display(action_id))

    def _apply_filter(self, text: str):
        needle = text.strip().lower()
        for action in sc.ACTIONS:
            row = self._row_by_action.get(action.id)
            if row is None:
                continue
            haystack = f"{action.label} {action.group}".lower()
            self.table.setRowHidden(row, bool(needle) and needle not in haystack)

    def _validate(self):
        t = _t()
        conflicts = sc.find_conflicts(self._bindings)
        conflict_ids = sc.conflict_actions(conflicts)
        invalid: list[str] = []
        for action_id, seq in self._bindings.items():
            ok, reason = sc.is_acceptable(seq)
            item = self.table.item(self._row_by_action.get(action_id, -1), 1) \
                if action_id in self._row_by_action else None
            if item is not None:
                item.setForeground(QColor(t.text_primary))
                item.setToolTip("")
            if not ok:
                invalid.append(f"{sc.ACTIONS_BY_ID[action_id].label}: {reason}")
                if item is not None:
                    item.setForeground(QColor(t.error))
                    item.setToolTip(reason)

        for seq, ids in conflicts.items():
            for action_id in ids:
                row = self._row_by_action.get(action_id)
                item = self.table.item(row, 1) if row is not None else None
                if item is not None:
                    item.setForeground(QColor(t.error))
                    item.setToolTip(f"{seq} is used by more than one action.")

        messages = []
        if conflicts:
            pairs = "; ".join(
                f"{seq}: " + ", ".join(sc.ACTIONS_BY_ID[i].label for i in ids)
                for seq, ids in conflicts.items()
            )
            messages.append("Conflict — " + pairs)
        messages.extend(invalid)
        if messages:
            self.status.setText("\n".join(messages))
            self.status.setStyleSheet(f"color:{t.error};font-size:11px;")
            self.btn_save.setEnabled(False)
        else:
            self.status.setText("No conflicts.")
            self.status.setStyleSheet(f"color:{t.success};font-size:11px;")
            self.btn_save.setEnabled(True)

    # ── persistence ─────────────────────────────────────────────────────────

    def _save(self):
        self._validate()
        if not self.btn_save.isEnabled():
            return
        overrides = sc.overrides_from_bindings(self._bindings)
        sc.save_user_bindings(self._vault, self._bindings)
        if callable(self._on_saved):
            self._on_saved(overrides)
        self.accept()

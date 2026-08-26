import time
from PyQt6.QtWidgets import (
    QComboBox, QListView, QStyledItemDelegate, QStyle,
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QStandardItemModel, QStandardItem


from ui._theme import _t


class _ComboDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        from PyQt6.QtWidgets import QStyle
        text = index.data() or ""
        painter.save()
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover    = bool(option.state & QStyle.StateFlag.State_MouseOver)
        t = _t()
        if is_selected:
            painter.fillRect(option.rect, QColor(t.accent))
            painter.setPen(QColor(t.accent_text))
        elif is_hover:
            painter.fillRect(option.rect, QColor(t.accent_light))
            painter.setPen(QColor(t.accent))
        else:
            painter.fillRect(option.rect, QColor(t.bg_input))
            painter.setPen(QColor(t.text_primary))
        painter.drawText(option.rect.adjusted(12, 0, -8, 0),
                         Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        return sh.__class__(sh.width(), max(sh.height(), 28))


class _ComboListView(QListView):
    """QListView that closes its parent ComboBox popup on mouse release."""
    def __init__(self, combo: 'StyledComboBox'):
        super().__init__()
        self._combo = combo
        self.setMouseTracking(True)
        self.setItemDelegate(_ComboDelegate(self))
        t = _t()
        self.setStyleSheet(
            f"QListView {{ border:1px solid {t.border}; background:{t.bg_input}; outline:none; color:{t.text_primary}; }}"
            f"QListView::item {{ padding:0px; color:{t.text_primary}; }}"
        )

    def mouseReleaseEvent(self, event):
        # macOS opens the popup on mouse-press, so the release of that same
        # click can land inside the popup and would instantly select + close
        # it ("vanishing" dropdown). Ignore releases right after opening.
        if time.monotonic() - getattr(self._combo, "_popup_opened_at", 0.0) < 0.30:
            super().mouseReleaseEvent(event)
            return
        index = self.indexAt(event.pos())
        if index.isValid():
            self._combo.setCurrentIndex(index.row())
            self._combo.hidePopup()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class StyledComboBox(QComboBox):
    """QComboBox with reliable hover + click-closes behaviour."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_was_open = False
        self.setView(_ComboListView(self))

    def showPopup(self):
        self._popup_was_open = True
        self._popup_opened_at = time.monotonic()
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        QTimer.singleShot(150, self._clear_popup_flag)

    def _clear_popup_flag(self):
        self._popup_was_open = False


class _CheckableComboDelegate(QStyledItemDelegate):
    """Paints a checkbox + label per row, themed to match _ComboDelegate."""
    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        # PyQt6 doesn't reliably hand back a Qt.CheckState enum instance from
        # index.data(CheckStateRole) — comparing it directly to Qt.CheckState.Checked
        # silently evaluates False even when the item really is checked, so every
        # box painted as empty regardless of actual state. Normalize to int first.
        raw_state = index.data(Qt.ItemDataRole.CheckStateRole)
        checked = raw_state is not None and int(raw_state) == int(Qt.CheckState.Checked.value)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        t = _t()
        painter.save()
        painter.fillRect(option.rect, QColor(t.accent_light if is_hover else t.bg_input))
        box_size = 16
        box_y = option.rect.top() + (option.rect.height() - box_size) // 2
        box_rect = option.rect.adjusted(12, box_y - option.rect.top(), 0, 0)
        box_rect.setSize(box_rect.size().__class__(box_size, box_size))
        painter.setPen(QColor(t.accent if checked else t.text_muted))
        painter.drawRect(box_rect)
        if checked:
            painter.fillRect(box_rect.adjusted(3, 3, -3, -3), QColor(t.accent))
        painter.setPen(QColor(t.text_primary))
        painter.drawText(option.rect.adjusted(12 + box_size + 8, 0, -8, 0),
                          Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        return sh.__class__(sh.width(), max(sh.height(), 30))


class _CheckablePopupFrame(QFrame):
    """The dropdown itself — a real top-level Qt::Popup window, not part of
    QComboBox's machinery. Qt auto-closes any Popup-flagged window the
    instant a click lands outside its geometry, which is exactly the
    click-away-to-close behaviour we want, for free."""
    def __init__(self, combo: 'CheckableComboBox'):
        super().__init__(combo, Qt.WindowType.Popup)
        self._combo = combo

    def hideEvent(self, event):
        super().hideEvent(event)
        # Clear the "just closed" flags shortly after hiding rather than
        # instantly — the same click that auto-closes this popup (a click
        # on the combo box itself, to toggle it shut) can otherwise be
        # seen a second time by the combo's own mousePressEvent and
        # immediately reopen it.
        QTimer.singleShot(150, lambda: setattr(self._combo, "_popup_was_open", False))
        self._combo._popup_closed_at = time.monotonic()


class CheckableComboBox(QWidget):
    """A combo-box look-alike with a checkbox-per-row multi-select dropdown.
    Used for the AY/TY selector so a batch can target multiple years in one
    run; selecting exactly one year displays the same as a plain combo box.

    Deliberately NOT a QComboBox subclass. QComboBox's built-in popup
    container watches its view's viewport for mouse-release events and
    always closes the popup on any row click (baked-in single-select
    semantics) — every attempt to fight that from the outside (subclassing
    the view, installing eventFilters on the viewport, routing clicks
    around the internal lineEdit) either got overridden by Qt's own
    internal handling or broke the click-to-open path entirely. Owning a
    plain QFrame popup instead sidesteps that machinery altogether, so
    opening/closing and row-toggling are fully under our own control."""

    def __init__(self, parent=None, placeholder: str = "Select AY/TY"):
        super().__init__(parent)
        self._placeholder = placeholder
        self._popup_was_open = False
        self._popup_closed_at = 0.0
        self.model_ = QStandardItemModel(self)

        t = _t()
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("CheckableComboBox")
        # A plain QWidget ignores background/border from its stylesheet
        # unless this is set — without it the box paints with no fill or
        # border at all, in either theme.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#CheckableComboBox {{ background:{t.bg_input}; border:1px solid {t.border}; border-radius:6px; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(4)
        self._label = QLabel(placeholder)
        self._label.setStyleSheet(f"color:{t.text_primary}; background:transparent; border:none;")
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._arrow = QLabel("▾")
        self._arrow.setFixedWidth(14)
        self._arrow.setStyleSheet(f"color:{t.text_muted}; background:transparent; border:none;")
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._label, stretch=1)
        lay.addWidget(self._arrow)

        self._popup = _CheckablePopupFrame(self)
        self._popup.setStyleSheet(
            f"QFrame {{ background:{t.bg_input}; border:1px solid {t.border}; border-radius:6px; }}")
        pop_lay = QVBoxLayout(self._popup)
        pop_lay.setContentsMargins(0, 4, 0, 4)
        pop_lay.setSpacing(0)
        self._list = QListView()
        self._list.setMouseTracking(True)
        self._list.setModel(self.model_)
        self._list.setItemDelegate(_CheckableComboDelegate(self._list))
        self._list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setStyleSheet(
            f"QListView {{ border:none; background:{t.bg_input}; outline:none; color:{t.text_primary}; }}")
        self._list.clicked.connect(self._on_row_clicked)
        pop_lay.addWidget(self._list)

        self._refresh_display_text()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Ignore the click that's just an echo of the same physical
            # click that made the popup auto-close a moment ago (clicking
            # the box again while open counts as "outside" the popup, so
            # Qt closes it before this press handler even runs).
            if time.monotonic() - self._popup_closed_at < 0.25:
                return
            self._toggle_popup()
            return
        super().mousePressEvent(event)

    def _toggle_popup(self):
        if self._popup.isVisible():
            self._popup.hide()
        else:
            self._show_popup()

    def _show_popup(self):
        self._popup_was_open = True
        row_h = 30
        n = max(self.model_.rowCount(), 1)
        width = max(self.width(), 220)
        height = min(n * row_h + 8, 320)
        self._popup.setFixedWidth(width)
        self._popup.setFixedHeight(height)
        self._popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        self._popup.show()

    def _on_row_clicked(self, index):
        item = self.model_.itemFromIndex(index)
        if item is None:
            return
        item.setCheckState(
            Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked)
        self._refresh_display_text()

    def clear_items(self) -> None:
        self.model_.clear()
        self._refresh_display_text()

    def add_item(self, label: str, checked: bool = False) -> None:
        item = QStandardItem(label)
        item.setCheckable(True)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.model_.appendRow(item)
        self._refresh_display_text()

    def checked_labels(self) -> list[str]:
        labels = []
        for row in range(self.model_.rowCount()):
            item = self.model_.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                labels.append(item.text())
        return labels

    def set_checked_labels(self, labels) -> None:
        wanted = set(labels)
        for row in range(self.model_.rowCount()):
            item = self.model_.item(row)
            item.setCheckState(Qt.CheckState.Checked if item.text() in wanted else Qt.CheckState.Unchecked)
        self._refresh_display_text()

    def _refresh_display_text(self) -> None:
        labels = self.checked_labels()
        if not labels:
            text = self._placeholder
        elif len(labels) == 1:
            text = labels[0]
        else:
            text = f"{len(labels)} years selected"
        self._label.setText(text)

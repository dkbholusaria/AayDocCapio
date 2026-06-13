import time
from PyQt6.QtWidgets import QComboBox, QListView, QStyledItemDelegate
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor


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

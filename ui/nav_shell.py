"""
ui/nav_shell.py — F-77a Phase 1: left-rail + breadcrumb navigation shell.

Not yet wired into app.py (see PlansofThisProject/F-77a_nav_shell_phase1.md,
PR 1). Provides three reusable widgets:

  NavRail          — vertical icon-only rail of hub buttons.
  BreadcrumbRibbon — thin "Hub / Sub-label" breadcrumb bar.
  NavShell         — composes the two above around a QStackedWidget.

Existing screens/dialogs are unchanged by this module — hubs registered
via NavShell.add_hub() just decide what to show; this file only owns
navigation chrome.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QButtonGroup,
    QFrame, QLabel, QStackedWidget, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal

from ui._theme import _t
from ui.helpers import _icon_path
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtCore import QSize


class NavRail(QWidget):
    """64px-wide icon-only rail. Top group + bottom group, exclusive selection."""

    hubSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(64)
        self._buttons: dict[str, QToolButton] = {}
        self._accent_keys: dict[str, str] = {}  # hub key -> ThemeColors attr name

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 14, 0, 14)
        outer.setSpacing(4)

        self._top = QVBoxLayout()
        self._top.setSpacing(4)
        outer.addLayout(self._top)

        outer.addStretch(1)

        self._bottom = QVBoxLayout()
        self._bottom.setSpacing(4)
        outer.addLayout(self._bottom)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

    def add_divider(self, section: str = "top"):
        line = QFrame()
        line.setFixedHeight(1)
        line.setFixedWidth(28)
        line.setStyleSheet(f"background:{_t().border};")
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 6, 0, 6)
        wrap.addStretch(1)
        wrap.addWidget(line)
        wrap.addStretch(1)
        target = self._top if section == "top" else self._bottom
        target.addLayout(wrap)

    def add_hub(self, key: str, label: str, icon: str = "", accent_key: str = "accent_home",
                section: str = "top"):
        """Add a rail button. `icon` is a resources/icons/<name> filename, or
        falls back to the first letter of `label` as a glyph if not found."""
        btn = QToolButton()
        btn.setCheckable(True)
        btn.setFixedSize(42, 42)
        btn.setToolTip(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        icon_path = _icon_path(icon) if icon else ""
        if icon_path:
            px = QPixmap(icon_path).scaled(19, 19, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
            btn.setIcon(QIcon(px))
            btn.setIconSize(QSize(19, 19))
        else:
            btn.setText(label[:1])

        btn.clicked.connect(lambda checked, k=key: self._on_clicked(k))

        self._group.addButton(btn)
        self._buttons[key] = btn
        self._accent_keys[key] = accent_key

        target = self._top if section == "top" else self._bottom
        wrap = QHBoxLayout()
        wrap.setContentsMargins(11, 0, 11, 0)
        wrap.addWidget(btn)
        target.addLayout(wrap)

        self.repaint_theme(_t())
        return btn

    def _on_clicked(self, key: str):
        self.hubSelected.emit(key)

    def set_active(self, key: str):
        btn = self._buttons.get(key)
        if btn:
            btn.setChecked(True)

    def repaint_theme(self, t):
        """Re-apply per-button colours for the current theme (mirrors
        AayDocCapioApp._repaint_theme's pattern of imperative re-styling)."""
        self.setStyleSheet(f"background:{_t().bg_menubar};")
        for key, btn in self._buttons.items():
            accent = getattr(t, self._accent_keys.get(key, "accent_home"), t.accent)
            btn.setStyleSheet(
                "QToolButton {"
                f"  background: transparent; border: none; border-radius: 10px;"
                f"  color: {t.text_muted};"
                "}"
                "QToolButton:hover {"
                f"  background: rgba(255,255,255,0.06); color: {t.text_primary};"
                "}"
                "QToolButton:checked {"
                f"  background: {accent}22; color: {accent};"
                "}"
            )


class BreadcrumbRibbon(QWidget):
    """Thin breadcrumb bar: 'Hub / Sub-label'. No tab strip in Phase 1."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 0, 22, 0)
        layout.setSpacing(7)

        self._hub_lbl = QLabel("")
        self._sep_lbl = QLabel("›")
        self._sub_lbl = QLabel("")
        self._sep_lbl.setVisible(False)
        self._sub_lbl.setVisible(False)

        layout.addWidget(self._hub_lbl)
        layout.addWidget(self._sep_lbl)
        layout.addWidget(self._sub_lbl)
        layout.addStretch(1)

        self.repaint_theme(_t())

    def setPath(self, hub: str, sub: str | None = None):
        self._hub_lbl.setText(hub)
        has_sub = bool(sub)
        self._sep_lbl.setVisible(has_sub)
        self._sub_lbl.setVisible(has_sub)
        self._sub_lbl.setText(sub or "")

    def repaint_theme(self, t):
        self.setStyleSheet(f"background:{t.bg_panel}; border-bottom:1px solid {t.border};")
        self._hub_lbl.setStyleSheet(f"color:{t.text_primary}; font-size:12px; font-weight:600; background:transparent;")
        self._sep_lbl.setStyleSheet(f"color:{t.border_menu}; font-size:11px; background:transparent;")
        self._sub_lbl.setStyleSheet(f"color:{t.text_muted}; font-size:12px; font-weight:600; background:transparent;")


class NavShell(QWidget):
    """Composes NavRail + BreadcrumbRibbon + QStackedWidget."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._rail = NavRail(self)
        self._ribbon = BreadcrumbRibbon(self)
        self._stack = QStackedWidget(self)

        self._hub_labels: dict[str, str] = {}
        self._hub_pages: dict[str, QWidget] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._rail)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._ribbon)
        right.addWidget(self._stack, 1)
        root.addLayout(right, 1)

        self._rail.hubSelected.connect(self.go)

    def add_hub(self, key: str, label: str, page_widget: QWidget, icon: str = "",
                accent_key: str = "accent_home", section: str = "top"):
        self._rail.add_hub(key, label, icon=icon, accent_key=accent_key, section=section)
        self._hub_labels[key] = label
        self._hub_pages[key] = page_widget
        self._stack.addWidget(page_widget)

    def add_divider(self, section: str = "top"):
        self._rail.add_divider(section)

    def go(self, key: str, sub: str | None = None):
        page = self._hub_pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        self._rail.set_active(key)
        self._ribbon.setPath(self._hub_labels.get(key, key), sub)

    def repaint_theme(self, t):
        self._rail.repaint_theme(t)
        self._ribbon.repaint_theme(t)

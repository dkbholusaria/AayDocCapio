"""
ui/nav_shell.py — F-77a Phase 1: left-rail + breadcrumb navigation shell.

Visual design follows KarOrbis's HubSidebar (portals/common/components.py):
a 100px rail of icon-above-label buttons, square corners, zero gap between
buttons, and a thin left accent bar (not a filled pill) marking the active
hub. AayDocCapio's rail is a single persistent strip spanning every hub
(KarOrbis instead opens one colored sidebar per hub window), so the rail
background stays a fixed theme color and each hub's own accent colors the
active bar/hover tint instead of the whole rail.

Provides three reusable widgets:

  NavRail          — the rail of hub buttons described above.
  BreadcrumbRibbon — thin "Hub / Sub-label" breadcrumb bar.
  NavShell         — composes the two above around a QStackedWidget.

Existing screens/dialogs are unchanged by this module — hubs registered
via NavShell.add_hub() just decide what to show; this file only owns
navigation chrome.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QButtonGroup,
    QLabel, QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont

from ui._theme import _t
from ui.helpers import _icon_path

RAIL_WIDTH = 100
BUTTON_HEIGHT = 60
ICON_SIZE = 26


def _badge_icon(text: str, color: str, size: int = ICON_SIZE) -> QIcon:
    """A small filled-circle monogram, used when a hub has no real icon
    asset yet — replaces the old "one giant letter as the whole button"
    look with a real icon-shaped element plus a label below it."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setPen(QColor("#FFFFFF"))
    f = QFont()
    f.setPointSize(max(7, int(size * 0.34)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, text[:2].upper())
    p.end()
    return QIcon(px)


class NavRail(QWidget):
    """100px-wide rail of icon-above-label buttons (KarOrbis HubSidebar
    proportions). Top group + bottom group, exclusive selection, no
    dividers — matches KarOrbis's flush edge-to-edge button stacking."""

    hubSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(RAIL_WIDTH)
        self._buttons: dict[str, QToolButton] = {}
        self._accent_keys: dict[str, str] = {}  # hub key -> ThemeColors attr name

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._top = QVBoxLayout()
        self._top.setSpacing(0)
        outer.addLayout(self._top)

        outer.addStretch(1)

        self._bottom = QVBoxLayout()
        self._bottom.setSpacing(0)
        outer.addLayout(self._bottom)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

    def add_hub(self, key: str, label: str, icon: str = "", accent_key: str = "accent_home",
                section: str = "top", glyph: str = "", rail_label: str = ""):
        """Add a rail button. `icon` is a resources/icons/<name> filename; if
        not found, a colored monogram badge is drawn instead (using `glyph`
        or the first two letters of `label`). `rail_label` is the short
        (optionally two-line, via "\\n") text shown under the icon — falls
        back to `label` if not given."""
        btn = QToolButton()
        btn.setCheckable(True)
        btn.setFixedSize(RAIL_WIDTH, BUTTON_HEIGHT)
        btn.setToolTip(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setText(rail_label or label)
        btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))

        icon_path = _icon_path(icon) if icon else ""
        accent = getattr(_t(), accent_key, _t().accent)
        if icon_path:
            px = QPixmap(icon_path).scaled(ICON_SIZE, ICON_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
            btn.setIcon(QIcon(px))
        else:
            btn.setIcon(_badge_icon(glyph or label, accent))

        btn.clicked.connect(lambda checked, k=key: self._on_clicked(k))

        self._group.addButton(btn)
        self._buttons[key] = btn
        self._accent_keys[key] = accent_key

        target = self._top if section == "top" else self._bottom
        target.addWidget(btn)

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
        self.setStyleSheet(f"background:{t.bg_menubar}; border-right:1px solid {t.border};")
        for key, btn in self._buttons.items():
            accent = getattr(t, self._accent_keys.get(key, "accent_home"), t.accent)
            btn.setStyleSheet(
                "QToolButton {"
                "  background: transparent; border: none; border-left: 4px solid transparent;"
                f"  color: {t.text_muted}; font-size: 9px; font-weight: 700;"
                "}"
                "QToolButton:hover {"
                f"  background: {accent}1A; color: {t.text_primary};"
                "}"
                "QToolButton:checked {"
                f"  background: {accent}26; color: {t.text_primary};"
                f"  border-left: 4px solid {accent};"
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
                accent_key: str = "accent_home", section: str = "top", glyph: str = "",
                rail_label: str = ""):
        self._rail.add_hub(key, label, icon=icon, accent_key=accent_key, section=section,
                            glyph=glyph, rail_label=rail_label)
        self._hub_labels[key] = label
        self._hub_pages[key] = page_widget
        self._stack.addWidget(page_widget)

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

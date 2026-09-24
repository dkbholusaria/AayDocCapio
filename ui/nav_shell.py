"""
ui/nav_shell.py — F-77a Phase 1: left-rail + breadcrumb navigation shell.

Ports the approved HTML/CSS Artifact mockup's rail as closely as Qt/QSS
allows: a 64px icon-only rail, 42x42 rounded buttons, tooltip on hover,
and a tinted pill (not a left bar) marking the active hub. Icons are the
mockup's own inline SVG paths, rendered via QSvgRenderer and tinted per
theme/state at runtime (muted when inactive, the hub's accent color when
active) — not flat PNG art, so they always match the current theme.

Provides two reusable pieces:

  NavRail   — the rail of hub buttons described above.
  NavShell  — composes NavRail with a QStackedWidget; emits `hubChanged`
              (hub_label, sub_label) on navigation so the host window can
              show a breadcrumb wherever it likes (the main header, per
              user preference — not a separate ribbon strip here).

Existing screens/dialogs are unchanged by this module — hubs registered
via NavShell.add_hub() just decide what to show; this file only owns
navigation chrome.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QButtonGroup,
    QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QByteArray
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor

from ui._theme import _t

try:
    from PyQt6.QtSvg import QSvgRenderer
    _HAVE_SVG = True
except ImportError:
    _HAVE_SVG = False

RAIL_WIDTH = 64
BUTTON_SIZE = 42
ICON_SIZE = 20

# Same path data as the approved HTML mockup's rail icons (Lucide-style,
# 24x24 viewBox, stroke-based). Keying by icon name, not per-hub, so any
# hub can reuse an icon if needed.
_ICON_SVGS = {
    "home": '<path d="M17 21v-8H7v8M3 10l9-7 9 7v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "document": ('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
                 '<polyline points="14 2 14 8 20 8"/>'),
    "building": ('<rect x="3" y="7" width="18" height="13" rx="2"/>'
                 '<path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
                 '<line x1="3" y1="12" x2="21" y2="12"/>'),
    "rupee": '<path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "columns": ('<path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m4 0h1m-6 4h1m4 0h1m-6 4h1m4 0h1"/>'),
    "people": ('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
               '<circle cx="9" cy="7" r="4"/>'
               '<path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'),
    "mail": '<path d="M4 4h16v16H4z"/><path d="m4 6 8 7 8-7"/>',
    "list": ('<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>'
             '<line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>'
             '<line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>'),
    "gear": ('<circle cx="12" cy="12" r="3"/>'
             '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 '
             '1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
    "help": ('<circle cx="12" cy="12" r="10"/>'
             '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
             '<line x1="12" y1="17" x2="12.01" y2="17"/>'),
}

# Which icon each hub uses — matches the approved mockup's rail 1:1.
HUB_ICONS = {
    "home": "home", "it": "document", "gst": "building", "tds": "rupee",
    "mca": "columns", "team": "people", "mail": "mail", "activity": "list",
    "settings": "gear", "help": "help",
}


def _svg_pixmap(icon_key: str, color: str, size: int) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    body = _ICON_SVGS.get(icon_key, "")
    if _HAVE_SVG and body:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        p = QPainter(px)
        renderer.render(p)
        p.end()
    else:
        # No QtSvg available — fall back to a plain tinted circle so the
        # rail still renders sensibly rather than showing nothing.
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(2, 2, size - 4, size - 4)
        p.end()
    return px


def _hub_icon(icon_key: str, muted_color: str, accent_color: str, size: int = ICON_SIZE) -> QIcon:
    """QIcon with two states: muted (Off, i.e. inactive) and accent-tinted
    (On, i.e. checked/active) — QToolButton picks the right one automatically
    from its checked state, no manual icon-swapping needed."""
    icon = QIcon()
    icon.addPixmap(_svg_pixmap(icon_key, muted_color, size), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_svg_pixmap(icon_key, accent_color, size), QIcon.Mode.Normal, QIcon.State.On)
    return icon


class NavRail(QWidget):
    """64px-wide icon-only rail — proportions and interaction match the
    approved HTML mockup: 42x42 rounded buttons, tooltip on hover, a
    tinted pill (not a bar) for the active hub."""

    hubSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(RAIL_WIDTH)
        self._buttons: dict[str, QToolButton] = {}
        self._accent_keys: dict[str, str] = {}
        self._icon_keys: dict[str, str] = {}

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

    def add_hub(self, key: str, label: str, accent_key: str = "accent_home", section: str = "top"):
        """Add a rail button. The icon is looked up from HUB_ICONS[key]
        (falling back to a plain circle if the key isn't mapped)."""
        btn = QToolButton()
        btn.setCheckable(True)
        btn.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        btn.setToolTip(label)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIconSize(QSize(ICON_SIZE, ICON_SIZE))

        self._group.addButton(btn)
        self._buttons[key] = btn
        self._accent_keys[key] = accent_key
        self._icon_keys[key] = HUB_ICONS.get(key, "home")

        target = self._top if section == "top" else self._bottom
        wrap = QHBoxLayout()
        wrap.setContentsMargins(11, 0, 11, 0)
        wrap.addWidget(btn)
        target.addLayout(wrap)

        btn.clicked.connect(lambda checked, k=key: self._on_clicked(k))
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
        self.setStyleSheet(f"background:{t.bg_menubar};")
        for key, btn in self._buttons.items():
            accent = getattr(t, self._accent_keys.get(key, "accent_home"), t.accent)
            btn.setIcon(_hub_icon(self._icon_keys.get(key, "home"), t.text_muted, accent))
            btn.setStyleSheet(
                "QToolButton {"
                "  background: transparent; border: none; border-radius: 10px;"
                "}"
                "QToolButton:hover {"
                f"  background: {accent}1A;"
                "}"
                "QToolButton:checked {"
                f"  background: {accent}29;"
                "}"
            )


class NavShell(QWidget):
    """Composes NavRail + QStackedWidget. Emits `hubChanged(hub_label,
    sub_label)` on navigation — the host window owns where/how that's
    displayed (the main header, per user preference)."""

    hubChanged = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._rail = NavRail(self)
        self._stack = QStackedWidget(self)

        self._hub_labels: dict[str, str] = {}
        self._hub_pages: dict[str, QWidget] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._rail)
        root.addWidget(self._stack, 1)

        self._rail.hubSelected.connect(self.go)

    def add_hub(self, key: str, label: str, page_widget: QWidget,
                accent_key: str = "accent_home", section: str = "top"):
        self._rail.add_hub(key, label, accent_key=accent_key, section=section)
        self._hub_labels[key] = label
        self._hub_pages[key] = page_widget
        self._stack.addWidget(page_widget)

    def go(self, key: str, sub: str | None = None):
        page = self._hub_pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        self._rail.set_active(key)
        self.hubChanged.emit(self._hub_labels.get(key, key), sub or "")

    def repaint_theme(self, t):
        self._rail.repaint_theme(t)

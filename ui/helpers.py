import sys
from PyQt6.QtWidgets import QPushButton, QLabel, QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor


# Font name used for PyQt6 QFont() calls — full stacks live in themes.py
_UI_FONT = "Segoe UI" if sys.platform == "win32" else "Avenir Next"


from ui._theme import _t


def _shadow(blur=18, offset_y=3, alpha=22):
    e = QGraphicsDropShadowEffect()
    e.setBlurRadius(blur)
    e.setOffset(0, offset_y)
    e.setColor(QColor(0, 0, 0, alpha))
    return e


def _btn(text, style="secondary", height=36, min_width=None):
    b = QPushButton(text)
    b.setMinimumHeight(height)
    if min_width:
        b.setMinimumWidth(min_width)
    t = _t()
    COLORS = {
        "primary":   ("#2563EB",      "#1D4ED8",      "white"),
        "success":   ("#16A34A",      "#15803D",      "white"),
        "danger":    ("#EF4444",      "#DC2626",      "white"),
        "secondary": ("#64748B",      "#475569",      "white"),
        "warning":   ("#EAB308",      "#CA8A04",      "white"),
        "outline":   ("transparent",  t.bg_table_alt, t.text_primary),
        "edit":      ("#0284C7",      "#0369A1",      "white"),
        "delete":    ("#DC2626",      "#991B1B",      "white"),
    }
    bg, hov, fg = COLORS.get(style, COLORS["secondary"])
    border = f"1px solid {t.border}" if style == "outline" else "none"
    b.setStyleSheet(
        f"QPushButton {{ background:{bg}; color:{fg}; border:{border}; "
        f"border-radius:6px; padding:6px 14px; font-weight:bold; font-size:12px; }}"
        f"QPushButton:hover {{ background:{hov}; }}"
        f"QPushButton:disabled {{ background:{t.border}; color:{t.text_muted}; }}"
    )
    return b


def _lbl(text, size=12, bold=False, color=None):
    l = QLabel(text)
    c = color or _t().text_primary
    l.setStyleSheet(f"color:{c}; font-size:{size}px;" + (" font-weight:bold;" if bold else ""))
    return l


# Status → text colour tuples (light_fg, dark_fg)
_STATUS_FG = {
    "waiting": ("#64748B", "#94A3B8"),
    "running": ("#92400E", "#FCD34D"),
    "success": ("#15803D", "#4ADE80"),
    "queued":  ("#92400E", "#FCD34D"),
    "failed":  ("#B91C1C", "#F87171"),
}


def _status_style(text: str):
    """Return (key, light_fg, dark_fg) for the given status text."""
    t = text.lower()
    if "waiting" in t:                                      key = "waiting"
    elif any(x in t for x in ("✅", "downloaded")):        key = "success"
    elif any(x in t for x in ("🕐", "queued", "pls use")): key = "queued"
    elif any(x in t for x in ("❌", "failed", "error")):   key = "failed"
    else:                                                   key = "running"
    light_fg, dark_fg = _STATUS_FG[key]
    return key, light_fg, dark_fg

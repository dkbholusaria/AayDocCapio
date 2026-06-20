"""
themes.py — Centralised colour/font definitions for AayDocCapio.

Adding a new theme:
  1. Add an entry to THEMES dict with a ThemeColors instance.
  2. Wire it in the Settings → Appearance menu in app.py.
  No other file needs to change.
"""

import sys
from dataclasses import dataclass


# ── Font stacks (platform-aware) ──────────────────────────────────────────────

if sys.platform == "win32":
    UI_FONT   = "'Segoe UI', Arial, sans-serif"
    MONO_FONT = "'Cascadia Code', 'Consolas', monospace"
elif sys.platform == "darwin":
    UI_FONT   = "'Avenir Next', Arial"
    MONO_FONT = "'Menlo', monospace"
else:
    UI_FONT   = "Arial, sans-serif"
    MONO_FONT = "monospace"

# Single-name versions used for QFont() calls in Python code
UI_FONT_NAME   = "Segoe UI"   if sys.platform == "win32" else "Avenir Next"
MONO_FONT_NAME = "Cascadia Code" if sys.platform == "win32" else "Menlo"


# ── ThemeColors dataclass ─────────────────────────────────────────────────────

@dataclass
class ThemeColors:
    name: str

    # Backgrounds
    bg_window:    str   # main window / dialog background
    bg_panel:     str   # card / settings bar background
    bg_input:     str   # text inputs, combos
    bg_input_focus: str # focused input background
    bg_table:     str   # table background
    bg_table_alt: str   # alternating row colour
    bg_header:    str   # table / settings bar header
    bg_log:       str   # live log panel
    bg_log_hdr:   str   # log panel header bar
    bg_menu:      str   # popup menu background
    bg_menubar:   str   # menu bar background
    bg_checkbox:  str   # checkbox indicator background

    # Foreground / text
    text_primary:  str  # main body text
    text_muted:    str  # captions, placeholders, column headers
    text_disabled: str  # disabled widget text
    text_log:      str  # log panel text colour

    # Borders
    border:       str   # default border colour
    border_focus: str   # focused input border
    border_menu:  str   # popup menu border (stronger in light theme for visibility)
    grid:         str   # table grid lines

    # Accent / interactive
    accent:       str   # primary accent (buttons, links)
    accent_hover: str   # accent on hover
    accent_light: str   # light accent (selected row background)
    accent_text:  str   # text on accent background

    # Row selection highlight
    row_selected_bg: str
    row_selected_fg: str

    # Scrollbar
    scrollbar_handle:       str
    scrollbar_handle_hover: str


# ── Theme definitions ─────────────────────────────────────────────────────────

THEMES: dict[str, ThemeColors] = {

    "light": ThemeColors(
        name            = "Light",

        bg_window       = "#FFFFFF",
        bg_panel        = "#FFFFFF",
        bg_input        = "#FFFFFF",
        bg_input_focus  = "#FAFBFF",
        bg_table        = "#FFFFFF",
        bg_table_alt    = "#F8FAFC",
        bg_header       = "#FFFFFF",
        bg_log          = "#0F172A",
        bg_log_hdr      = "#1E293B",
        bg_menu         = "#FFFFFF",
        bg_menubar      = "#FFFFFF",
        bg_checkbox     = "#FFFFFF",

        text_primary    = "#0F172A",
        text_muted      = "#94A3B8",
        text_disabled   = "#94A3B8",
        text_log        = "#7DD3FC",

        border          = "#E2E8F0",
        border_focus    = "#3B82F6",
        border_menu     = "#94A3B8",
        grid            = "#E2E8F0",

        accent          = "#2563EB",
        accent_hover    = "#1D4ED8",
        accent_light    = "#DBEAFE",
        accent_text     = "#FFFFFF",

        row_selected_bg = "#FFFFFF",
        row_selected_fg = "#DC2626",

        scrollbar_handle       = "#CBD5E1",
        scrollbar_handle_hover = "#94A3B8",
    ),

    "dark": ThemeColors(
        name            = "Dark Navy",

        bg_window       = "#0A1628",
        bg_panel        = "#0D1F3C",
        bg_input        = "#0F2040",
        bg_input_focus  = "#0D1F3C",
        bg_table        = "#0A1628",
        bg_table_alt    = "#0D1F3C",
        bg_header       = "#0D1F3C",
        bg_log          = "#060F1E",
        bg_log_hdr      = "#0F2040",
        bg_menu         = "#0F2040",
        bg_menubar      = "#060F1E",
        bg_checkbox     = "#0F2040",

        text_primary    = "#E2E8F0",
        text_muted      = "#94A3B8",
        text_disabled   = "#475569",
        text_log        = "#7DD3FC",

        border          = "#1E3A5F",
        border_focus    = "#3B82F6",
        border_menu     = "#2E5A8E",
        grid            = "#1E3A5F",

        accent          = "#2563EB",
        accent_hover    = "#1D4ED8",
        accent_light    = "#1E3A5F",
        accent_text     = "#FFFFFF",

        row_selected_bg = "#0D1F3C",
        row_selected_fg = "#60A5FA",

        scrollbar_handle       = "#1E3A5F",
        scrollbar_handle_hover = "#2563EB",
    ),
}


# ── Stylesheet builder ────────────────────────────────────────────────────────

def build_stylesheet(t: ThemeColors) -> str:
    return f"""
QMainWindow, QDialog {{ background: {t.bg_window}; }}
QMessageBox {{ background: {t.bg_window}; }}
QMessageBox QLabel {{ color: {t.text_primary}; background: transparent; }}
QMessageBox QPushButton {{
    background: {t.accent}; color: {t.accent_text}; border: none;
    border-radius: 5px; padding: 6px 18px; font-size: 13px; min-width: 70px;
}}
QMessageBox QPushButton:hover {{ background: {t.accent_hover}; }}
QWidget {{ font-family: {UI_FONT}; font-size: 13px; color: {t.text_primary}; }}
QLabel  {{ color: {t.text_primary}; font-size: 13px; }}

QLineEdit {{
    background: {t.bg_input};
    border: 1.5px solid {t.border};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 13px;
    color: {t.text_primary};
    min-height: 28px;
    selection-background-color: {t.accent_light};
}}
QLineEdit:hover  {{ border-color: {t.accent}; }}
QLineEdit:focus  {{ border: 1.5px solid {t.border_focus}; background: {t.bg_input_focus}; outline: none; }}
QLineEdit:disabled {{ background: {t.bg_window}; color: {t.text_disabled}; border-color: {t.border}; }}
QLineEdit::placeholder {{ color: {t.text_muted}; }}

QComboBox {{
    background: {t.bg_input};
    border: 1.5px solid {t.border};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 13px;
    color: {t.text_primary};
    min-height: 26px;
    min-width: 120px;
}}
QComboBox:hover {{ border-color: {t.accent}; }}
QComboBox:focus {{ border: 1.5px solid {t.border_focus}; }}
QComboBox::drop-down {{ border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: right center; }}
QComboBox::down-arrow {{ image: url(resources/icons/chevron_down.png); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {t.border};
    background: {t.bg_input};
    color: {t.text_primary};
    outline: none;
    selection-background-color: {t.accent};
    selection-color: {t.accent_text};
    show-decoration-selected: 1;
}}

QCheckBox {{ font-size: 13px; color: {t.text_primary}; spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1.5px solid {t.border};
    border-radius: 4px;
    background: {t.bg_checkbox};
}}
QCheckBox::indicator:hover   {{ border-color: {t.border_focus}; }}
QCheckBox::indicator:checked {{
    background: {t.accent};
    border-color: {t.accent};
    image: url(resources/check.png);
}}
QCheckBox::indicator:disabled {{ background: {t.bg_window}; border-color: {t.border}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 6px; border-radius: 3px; margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.scrollbar_handle}; border-radius: 3px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.scrollbar_handle_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QTextEdit {{
    background: {t.bg_log};
    border: none;
    font-family: {MONO_FONT};
    font-size: 11px;
    color: {t.text_log};
    padding: 8px 12px;
}}

QToolTip {{
    background-color: #FFFDE7; color: #1E293B;
    border: 1px solid #CBD5E1; border-radius: 4px;
    padding: 5px 9px; font-size: 11px;
    opacity: 255;
}}

QMenu {{
    background: {t.bg_menu};
    border: 1.5px solid {t.border_menu};
    border-radius: 6px;
    padding: 4px 0;
    icon-size: 20px;
}}
QMenu::item {{ padding: 7px 20px 7px 12px; color: {t.text_primary}; }}
QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
QMenu::separator {{ height: 1px; background: {t.border_menu}; margin: 4px 0; }}
QMenu::icon {{ padding-left: 6px; }}

QMenuBar {{
    background: {t.bg_menubar};
    color: {t.text_primary};
    border-bottom: 1px solid {t.border};
    font-size: 13px;
}}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {t.bg_input}; border-radius: 4px; }}
"""


def get_theme(name: str) -> ThemeColors:
    """Return theme by name, falling back to light if unknown."""
    return THEMES.get(name, THEMES["light"])

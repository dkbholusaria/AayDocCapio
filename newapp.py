"""
newapp.py — F-77a nav-shell PREVIEW, not the real app.

Lets you eyeball the new rail/breadcrumb navigation shell without
installing the full app's dependencies (Playwright, pikepdf, cryptography,
etc.) — this only needs PyQt6.

    pip install PyQt6
    python newapp.py

Every hub page here is a static placeholder (no vault, no dialogs, no
automation) — it exists purely to preview the shell's look, the rail's
active-hub highlighting, per-hub accent colours, and the light/dark theme
toggle. To test the REAL app (actual dialogs, actual client data), run
`python app.py` with the full requirements installed as usual.

Delete this file once F-77a's shell is fully wired into app.py and you no
longer need a lightweight way to preview it.
"""

import sys

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton,
)
from PyQt6.QtCore import Qt

from themes import THEMES, build_stylesheet, get_theme
import ui._theme as _theme_mod
from ui._theme import _t
from ui.nav_shell import NavShell


def _placeholder_page(title: str, body: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 40, 24, 20)
    layout.setSpacing(8)
    hdr = QLabel(title)
    hdr.setStyleSheet(f"font-size:16px;font-weight:700;color:{_t().text_primary};background:transparent;")
    layout.addWidget(hdr)
    lbl = QLabel(body)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color:{_t().text_muted};font-size:12px;background:transparent;")
    layout.addWidget(lbl)
    layout.addStretch(1)
    return page


class PreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AayDocCapio — Nav Shell Preview (F-77a)")
        self.resize(1200, 760)
        self._current_theme = "dark"

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Simple top strip standing in for the real app's brand header.
        strip = QWidget()
        strip.setFixedHeight(40)
        strip_l = QHBoxLayout(strip)
        strip_l.setContentsMargins(16, 0, 16, 0)
        note = QLabel("Nav shell preview — placeholder pages only, not the real app")
        strip_l.addWidget(note)
        strip_l.addStretch(1)
        self._theme_btn = QPushButton("☀ Light / 🌙 Dark")
        self._theme_btn.clicked.connect(self._toggle_theme)
        strip_l.addWidget(self._theme_btn)
        outer.addWidget(strip)

        self._nav_shell = NavShell()
        self._build_hubs()
        outer.addWidget(self._nav_shell, 1)

        self._nav_shell.go("home")
        self._apply_theme(self._current_theme)

    def _build_hubs(self):
        ns = self._nav_shell
        ns.add_hub("home", "Home / Clients",
                   _placeholder_page("Home / Clients", "Real app: client grid + settings bar."),
                   accent_key="accent_home", section="top")
        ns.add_hub("it", "Income Tax",
                   _placeholder_page("Income Tax", "Real app: Download Documents, E-Pay Tax, Return Status, Tools."),
                   icon="icon_person.png", accent_key="accent_it", section="top")
        ns.add_hub("gst", "GST",
                   _placeholder_page("GST", "Coming soon — F-70."),
                   accent_key="accent_gst", section="top")
        ns.add_hub("tds", "TDS",
                   _placeholder_page("TDS", "Coming soon — F-71."),
                   accent_key="accent_tds", section="top")
        ns.add_hub("mca", "MCA",
                   _placeholder_page("MCA / ROC", "Coming soon — F-72."),
                   accent_key="accent_mca", section="top")
        ns.add_divider("bottom")
        ns.add_hub("team", "Team",
                   _placeholder_page("Team", "Coming soon — F-74."),
                   accent_key="accent_home", section="bottom", glyph="👥")
        ns.add_hub("mail", "Mail Docs to Clients",
                   _placeholder_page("Mail Docs to Clients", "Real app: MailDocsDialog."),
                   icon="btn_send.png", accent_key="accent_home", section="bottom")
        ns.add_hub("activity", "Activity Log",
                   _placeholder_page("Activity Log", "Real app: email send log."),
                   icon="btn_view_log.png", accent_key="accent_home", section="bottom")
        ns.add_hub("settings", "Settings",
                   _placeholder_page("Settings", "Real app: Manage Years/Groups, Output Folder, Email, Appearance."),
                   icon="menu_appearance.png", accent_key="accent_home", section="bottom")
        ns.add_hub("help", "Help",
                   _placeholder_page("Help", "Real app: User Manual, Email Setup Help, Report Bug, Updates, About."),
                   icon="menu_about.png", accent_key="accent_home", section="bottom")

    def _toggle_theme(self):
        self._apply_theme("light" if self._current_theme == "dark" else "dark")

    def _apply_theme(self, theme: str):
        self._current_theme = theme
        t = get_theme(theme)
        _theme_mod._active_theme = t
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_stylesheet(t))
        self.centralWidget().setStyleSheet(f"background:{t.bg_window};")
        self._nav_shell.repaint_theme(t)


def main():
    app = QApplication(sys.argv)
    win = PreviewWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

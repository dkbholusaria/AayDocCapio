# Thin module holding the active theme reference.
# Kept separate so ui/widgets.py, ui/helpers.py, ui/dialogs.py
# and app.py can all share it without circular imports.
from themes import get_theme, ThemeColors

_active_theme: ThemeColors = get_theme("light")


def _t() -> ThemeColors:
    return _active_theme

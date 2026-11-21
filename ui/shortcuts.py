"""ui/shortcuts.py — F-17 shortcut registry, persistence and conflict logic.

This module is deliberately Qt-free so the normalisation, default merging and
conflict detection can be unit-tested without a display server.

Bindings are stored in the vault under ``settings.keybindings`` as a mapping of
``action_id -> portable key sequence``. Only user overrides are stored: an empty
string means "explicitly unbound", and a missing ID means "use the default".
"""

from __future__ import annotations

from dataclasses import dataclass


VAULT_SETTING_KEY = "keybindings"
DEFAULTS_VERSION = 1


@dataclass(frozen=True)
class ShortcutAction:
    id: str
    label: str
    group: str
    default: str
    destructive: bool = False


# Order here is the order shown in the shortcut editor. Keep `default` strings
# in portable form (Ctrl/Alt/Shift/Meta + key) — Qt displays the native glyphs.
ACTIONS: tuple[ShortcutAction, ...] = (
    ShortcutAction("nav.home", "Home / Clients", "Pages", "Ctrl+1"),
    ShortcutAction("nav.income_tax", "Income Tax", "Pages", "Ctrl+2"),
    ShortcutAction("nav.tds", "TDS", "Pages", "Ctrl+3"),
    ShortcutAction("nav.mail", "Mail Docs to Clients", "Pages", "Ctrl+4"),
    ShortcutAction("nav.activity", "Activity Log", "Pages", "Ctrl+5"),
    ShortcutAction("nav.settings", "Settings", "Pages", "Ctrl+,"),
    ShortcutAction("nav.help", "Help", "Pages", "F1"),

    ShortcutAction("app.add_client", "Add New Client", "Clients", "Ctrl+N"),
    ShortcutAction("app.edit_client", "Edit selected client", "Clients", "Ctrl+E"),
    ShortcutAction("app.delete_clients", "Delete selected clients…", "Clients", "",
                   destructive=True),
    ShortcutAction("app.import", "Import from CSV / Excel", "Clients", "Ctrl+I"),
    ShortcutAction("app.export", "Export client data", "Clients", "Ctrl+Shift+E"),
    ShortcutAction("app.focus_search", "Focus search / filter", "Clients", "Ctrl+F"),
    ShortcutAction("app.refresh_clients", "Refresh client list", "Clients", "F5"),

    ShortcutAction("app.start_batch", "Start selected downloads", "Downloads", "Ctrl+Return"),
    ShortcutAction("app.stop_batch", "Stop current batch", "Downloads", "Ctrl+Shift+Return"),
    ShortcutAction("app.open_output_folder", "Open output folder", "Downloads", "Ctrl+Shift+O"),

    ShortcutAction("app.toggle_theme", "Toggle light/dark theme", "Appearance", "Ctrl+Shift+D"),
    ShortcutAction("app.open_shortcuts", "Keyboard shortcuts editor", "Help", "Ctrl+Shift+K"),
    ShortcutAction("app.user_manual", "User Manual", "Help", "Shift+F1"),
)

ACTIONS_BY_ID: dict[str, ShortcutAction] = {a.id: a for a in ACTIONS}

_MODIFIER_CANON = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "cmd": "Meta",
    "command": "Meta",
    "meta": "Meta",
    "super": "Meta",
    "win": "Meta",
    "alt": "Alt",
    "option": "Alt",
    "opt": "Alt",
    "shift": "Shift",
}
_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift", "Meta")

_KEY_ALIASES = {
    "return": "Return",
    "enter": "Return",
    "esc": "Esc",
    "escape": "Esc",
    "del": "Del",
    "delete": "Del",
    "ins": "Ins",
    "insert": "Ins",
    "pgup": "PgUp",
    "pageup": "PgUp",
    "pgdown": "PgDown",
    "pagedown": "PgDown",
    "space": "Space",
    "tab": "Tab",
    "backspace": "Backspace",
    "comma": ",",
    "plus": "+",
}

# OS/session keys we never let the user bind.
_RESERVED = {"Alt+F4"}


def defaults() -> dict[str, str]:
    return {a.id: a.default for a in ACTIONS}


def normalize(sequence: str | None) -> str:
    """Return a canonical portable key sequence.

    ``"shift+ctrl+e"`` and ``"Ctrl+Shift+E"`` both become ``"Ctrl+Shift+E"``.
    Empty/whitespace returns ``""`` (unbound). Unknown text is kept verbatim so
    the caller can reject it via :func:`is_acceptable`.
    """
    if sequence is None:
        return ""
    text = str(sequence).strip()
    if not text:
        return ""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        return ""
    modifiers: list[str] = []
    key = ""
    for part in parts:
        low = part.lower()
        if low in _MODIFIER_CANON:
            mod = _MODIFIER_CANON[low]
            if mod not in modifiers:
                modifiers.append(mod)
        else:
            key = part
    ordered = [m for m in _MODIFIER_ORDER if m in modifiers]
    if key.lower() in _KEY_ALIASES:
        key = _KEY_ALIASES[key.lower()]
    elif len(key) == 1:
        key = key.upper()
    elif key.lower().startswith("f") and key[1:].isdigit():
        key = "F" + key[1:]
    if not key:
        return ""
    return "+".join(ordered + [key])


def merge_user_bindings(user: dict | None) -> dict[str, str]:
    """Effective bindings: defaults, then valid user overrides.

    Unknown action IDs are ignored. A user value of ``""`` explicitly unbinds.
    """
    effective = defaults()
    if not isinstance(user, dict):
        return effective
    for action_id, value in user.items():
        if action_id in ACTIONS_BY_ID and isinstance(value, str):
            effective[action_id] = normalize(value)
    return effective


def find_conflicts(bindings: dict[str, str]) -> dict[str, list[str]]:
    """Return ``{normalized_sequence: [action_id, ...]}`` for duplicates.

    Unbound actions (``""``) never conflict.
    """
    seen: dict[str, list[str]] = {}
    for action_id, seq in bindings.items():
        norm = normalize(seq)
        if not norm:
            continue
        seen.setdefault(norm, []).append(action_id)
    return {seq: ids for seq, ids in seen.items() if len(ids) > 1}


def conflict_actions(conflicts: dict[str, list[str]]) -> set[str]:
    return {action_id for ids in conflicts.values() for action_id in ids}


def is_acceptable(sequence: str) -> tuple[bool, str]:
    """Reject bindings that would make typing or the OS unreliable.

    Returns ``(ok, reason)``. Unbound sequences are always acceptable.
    """
    norm = normalize(sequence)
    if not norm:
        return True, ""
    if norm in _RESERVED:
        return False, f"{norm} is reserved by the operating system."
    parts = norm.split("+")
    key = parts[-1]
    mods = set(parts[:-1])
    if key in {"Tab", "Esc", "Backspace", "Del", "Space", "Return"} and not mods:
        return False, f"{key} on its own is needed for normal keyboard use."
    if len(key) == 1 and key.isalnum() and not mods:
        return False, "Single letters and digits need Ctrl, Alt or Shift."
    return True, ""


def overrides_from_bindings(bindings: dict[str, str]) -> dict[str, str]:
    """Keep only values that differ from the current defaults."""
    base = defaults()
    out: dict[str, str] = {}
    for action_id, seq in bindings.items():
        if action_id not in ACTIONS_BY_ID:
            continue
        norm = normalize(seq)
        if norm != normalize(base.get(action_id, "")):
            out[action_id] = norm
    return out


def load_user_bindings(vault) -> dict[str, str]:
    raw = vault.get_setting(VAULT_SETTING_KEY, {}) if vault is not None else {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        str(k): normalize(v) if isinstance(v, str) else ""
        for k, v in raw.items()
        if k in ACTIONS_BY_ID
    }


def effective_normalized(vault) -> dict[str, str]:
    """Effective bindings for a vault, with every value canonicalised."""
    return merge_user_bindings(load_user_bindings(vault))


def save_user_bindings(vault, user_bindings: dict[str, str]) -> None:
    if vault is None:
        return
    vault.update_setting(VAULT_SETTING_KEY, overrides_from_bindings(user_bindings))


def reset_one(user_bindings: dict[str, str], action_id: str) -> dict[str, str]:
    out = dict(user_bindings)
    out.pop(action_id, None)
    return out


def reset_all() -> dict[str, str]:
    return {}


def format_binding(sequence: str) -> str:
    """Human-readable fallback for docs/tests; the UI uses QKeySequence."""
    return normalize(sequence) or "Unassigned"

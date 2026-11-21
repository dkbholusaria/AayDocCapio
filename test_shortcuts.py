"""F-17 — shortcut registry, persistence and conflict detection."""

from ui import shortcuts
from ui.shortcuts import (
    ACTIONS,
    defaults,
    effective_normalized,
    find_conflicts,
    is_acceptable,
    merge_user_bindings,
    normalize,
    overrides_from_bindings,
    reset_all,
    reset_one,
    save_user_bindings,
    load_user_bindings,
)


class FakeVault:
    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def update_setting(self, key, value):
        self.settings[key] = value


def test_defaults_cover_every_action():
    base = defaults()
    assert set(base) == {a.id for a in ACTIONS}
    assert base["app.add_client"] == "Ctrl+N"
    assert base["app.delete_clients"] == ""


def test_defaults_have_no_conflicts():
    assert find_conflicts(defaults()) == {}


def test_normalize_modifier_order_case_and_aliases():
    assert normalize("shift+ctrl+e") == "Ctrl+Shift+E"
    assert normalize("control+return") == "Ctrl+Return"
    assert normalize("cmd+shift+k") == "Shift+Meta+K"
    assert normalize("esc") == "Esc"
    assert normalize("f1") == "F1"
    assert normalize("  ") == ""
    assert normalize(None) == ""


def test_merge_ignores_unknown_and_allows_explicit_unbind():
    merged = merge_user_bindings({
        "app.add_client": "ctrl+alt+n",
        "app.delete_clients": "",
        "nope.not.real": "Ctrl+Z",
    })
    assert merged["app.add_client"] == "Ctrl+Alt+N"
    assert merged["app.delete_clients"] == ""
    assert "nope.not.real" not in merged
    assert merged["app.import"] == "Ctrl+I"


def test_conflict_detection_treats_order_and_case_as_same():
    bindings = defaults()
    bindings["app.import"] = "ctrl+n"
    conflicts = find_conflicts(bindings)
    assert conflicts["Ctrl+N"] == ["app.add_client", "app.import"]


def test_unbound_actions_never_conflict():
    bindings = {a.id: "" for a in ACTIONS}
    assert find_conflicts(bindings) == {}


def test_acceptability_rules():
    assert is_acceptable("") == (True, "")
    assert is_acceptable("Ctrl+N")[0]
    assert not is_acceptable("N")[0]
    assert not is_acceptable("Tab")[0]
    assert not is_acceptable("Alt+F4")[0]
    assert is_acceptable("F5")[0]


def test_overrides_only_store_changes():
    bindings = defaults()
    bindings["app.add_client"] = "Ctrl+Alt+N"
    bindings["app.delete_clients"] = ""
    over = overrides_from_bindings(bindings)
    assert over == {"app.add_client": "Ctrl+Alt+N"}


def test_persistence_round_trip_and_reset():
    vault = FakeVault()
    user = {"app.import": "Ctrl+Alt+I"}
    save_user_bindings(vault, user)
    assert load_user_bindings(vault) == user
    assert shortcuts.VAULT_SETTING_KEY in vault.settings

    reloaded = load_user_bindings(vault)
    assert reset_one(reloaded, "app.import") == {}
    assert reset_all() == {}


def test_persistence_drops_default_equivalent_values():
    vault = FakeVault()
    save_user_bindings(vault, defaults())
    assert vault.settings[shortcuts.VAULT_SETTING_KEY] == {}


def test_effective_normalized_helper_matches_merge():
    vault = FakeVault({shortcuts.VAULT_SETTING_KEY: {"app.import": "ctrl+alt+i"}})
    merged = merge_user_bindings(load_user_bindings(vault))
    assert merged == effective_normalized(vault)

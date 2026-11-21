import sys
import os
import random
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vault import VaultManager
from automation.eproc_scheduler import (
    DEFAULT_CONFIG,
    assign_rotation,
    assign_split,
    build_queue,
    cooldown_for,
    compute_next_run,
    estimate_nights,
    format_countdown,
    in_scope,
    is_due,
    is_timeout,
    normalise_config,
    should_backoff,
)


def _clients(count, groups=None):
    result = []
    for index in range(count):
        group = ""
        if groups:
            group = groups[index % len(groups)]
        result.append({"pan": f"PAN{index:07d}", "name": f"Client {index}", "group": group})
    return result


def _cfg(**overrides):
    base = {
        "enabled": True,
        "run_time": "21:00",
        "active_days": [0, 1, 2, 3, 4, 5, 6],
        "alternate_cases": False,
        "clients_per_day": 20,
        "distribution": "every_day",
    }
    base.update(overrides)
    return normalise_config(base)


def test_normalise_fills_defaults():
    cfg = normalise_config({})
    for key in DEFAULT_CONFIG:
        assert key in cfg, key
    assert cfg["enabled"] is False
    assert cfg["distribution"] == "every_day"
    assert cfg["distribute_days"] == 1
    assert cfg["split_boundary"] == "client_count"
    assert cfg["on_backoff_action"] == "resume_same_evening"


def test_normalise_clamps_values():
    cfg = normalise_config({
        "client_cooldown_sec": -30,
        "doc_cooldown_sec": -1,
        "jitter_sec": -5,
        "clients_per_day": 0,
        "distribution": "sometimes",
        "distribute_days": 9,
        "split_boundary": "alphabetical",
        "on_backoff_action": "later",
        "timeout_retries": 99,
    })
    assert cfg["client_cooldown_sec"] == 0
    assert cfg["doc_cooldown_sec"] == 0
    assert cfg["jitter_sec"] == 0
    assert cfg["clients_per_day"] == 1
    assert cfg["distribution"] == "every_day"
    assert cfg["distribute_days"] == 1
    assert cfg["split_boundary"] == "client_count"
    assert cfg["on_backoff_action"] == "resume_same_evening"
    assert cfg["timeout_retries"] == 5


def test_is_due_respects_time():
    cfg = _cfg()
    friday = datetime(2026, 11, 20)
    assert is_due(friday.replace(hour=20, minute=59), cfg) is False
    assert is_due(friday.replace(hour=21, minute=0), cfg) is True
    assert is_due(friday.replace(hour=22, minute=0), _cfg(active_days=[0])) is False


def test_is_due_respects_backoff():
    now = datetime(2026, 11, 20, 22, 0)
    cfg = _cfg(next_run_at="2026-11-20T21:00:00",
               backoff_until="2026-11-20T23:00:00")
    assert is_due(now, cfg) is False
    cfg["backoff_until"] = "2026-11-20T21:30:00"
    assert is_due(now, cfg) is True


def test_compute_next_run_skips_inactive_days():
    now = datetime(2026, 11, 20, 22, 0)
    assert compute_next_run(now, _cfg()) == datetime(2026, 11, 21, 21, 0)
    assert compute_next_run(now, _cfg(active_days=[5])) == datetime(2026, 11, 21, 21, 0)
    assert compute_next_run(now, _cfg(active_days=[0])) == datetime(2026, 11, 23, 21, 0)
    assert compute_next_run(now, _cfg(active_days=[])) is None


def test_in_scope_all_group_pan():
    clients = [
        {"pan": "AAA1111111", "group": "Family"},
        {"pan": "BBB2222222", "group": "Firm"},
        {"pan": "CCC3333333", "group": ""},
    ]
    assert len(in_scope(clients, _cfg(scope="all"))) == 3
    assert [c["pan"] for c in in_scope(clients, _cfg(scope="group", scope_groups=["family"]))] == ["AAA1111111"]
    assert [c["pan"] for c in in_scope(clients, _cfg(scope="pan", scope_pans=["bbb2222222"]))] == ["BBB2222222"]
    assert in_scope(clients, _cfg(scope="group", scope_groups=[])) == []


def test_in_scope_excludes_credential_invalid():
    clients = _clients(3)
    clients[1]["credential_invalid"] = True
    result = in_scope(clients, _cfg())
    assert [c["pan"] for c in result] == [clients[0]["pan"], clients[2]["pan"]]


def test_assign_split_client_count_1_2_3_days():
    clients = _clients(10)
    for parts in (1, 2, 3):
        collected = []
        sizes = []
        for phase in range(parts):
            cfg = _cfg(distribution="distribute", distribute_days=parts, split_phase=phase)
            part = assign_split(clients, cfg)
            collected.extend(c["pan"] for c in part)
            sizes.append(len(part))
        assert collected == [c["pan"] for c in clients], (parts, collected)
        assert max(sizes) - min(sizes) <= 1, (parts, sizes)


def test_assign_split_group_boundary():
    clients = _clients(9, groups=["A", "A", "A", "B", "B", "C", "C", "C", "C"])
    for phase in range(2):
        cfg = _cfg(distribution="distribute", distribute_days=2,
                   split_boundary="group", split_phase=phase)
        part = assign_split(clients, cfg)
        groups = {c["group"] for c in part}
        for group in groups:
            group_pans = {c["pan"] for c in clients if c["group"] == group}
            part_pans = {c["pan"] for c in part}
            assert group_pans <= part_pans, (phase, group, group_pans, part_pans)


def test_clients_per_day_caps_queue():
    clients = _clients(500)
    cfg = _cfg(clients_per_day=100)
    first, state = build_queue(clients, cfg)
    assert len(first) == 100
    assert len(state["queue_remaining"]) == 400
    second, state2 = build_queue(clients, state)
    assert len(second) == 100
    assert {c["pan"] for c in first}.isdisjoint({c["pan"] for c in second})
    assert len(state2["queue_remaining"]) == 300


def test_every_day_continues_queue():
    clients = _clients(6)
    cfg = _cfg(clients_per_day=2)
    first, state = build_queue(clients, cfg)
    second, state = build_queue(clients, state)
    third, state = build_queue(clients, state)
    assert [c["pan"] for c in first + second + third] == [c["pan"] for c in clients]
    assert state["queue_remaining"] == []


def test_assign_rotation_wraps():
    clients = _clients(5)
    selected, cursor = assign_rotation(clients, 0, 2)
    assert [c["pan"] for c in selected] == [clients[0]["pan"], clients[1]["pan"]]
    assert cursor == 2
    selected, cursor = assign_rotation(clients, cursor, 2)
    assert [c["pan"] for c in selected] == [clients[2]["pan"], clients[3]["pan"]]
    assert cursor == 4
    selected, cursor = assign_rotation(clients, cursor, 2)
    assert [c["pan"] for c in selected] == [clients[4]["pan"], clients[0]["pan"]]
    assert cursor == 1


def test_alternate_cases_rotates_start():
    clients = _clients(5)
    cfg = _cfg(clients_per_day=2, alternate_cases=True)
    starts = []
    state = cfg
    for _ in range(6):
        selected, state = build_queue(clients, state)
        starts.append(selected[0]["pan"])
    assert starts[:5] == [
        clients[0]["pan"], clients[2]["pan"], clients[4]["pan"],
        clients[1]["pan"], clients[3]["pan"],
    ]
    assert len(set(starts[:5])) > 1


def test_alternate_off_keeps_order():
    clients = _clients(10)
    cfg = _cfg(clients_per_day=3, alternate_cases=False, distribution="distribute",
               distribute_days=2)
    selected, _state = build_queue(clients, cfg)
    assert [c["pan"] for c in selected] == [c["pan"] for c in clients[:3]]


def test_cooldown_within_jitter_range():
    rng = random.Random(42)
    for _ in range(50):
        value = cooldown_for(90, 20, rng)
        assert 90 <= value <= 110
    assert cooldown_for(90, 0) == 90
    assert cooldown_for(-5, -10) == 0


def test_should_backoff_detects_rate_limit():
    for text in ("rate limit exceeded", "Too Many Requests", "error 429",
                 "your IP has been blocked", "Access Denied", "unusual traffic"):
        assert should_backoff(text) is True, text
    assert should_backoff("incorrect password") is False
    assert should_backoff("timeout while loading") is False


def test_is_timeout_detects_timeout():
    for text in ("Timeout 30000ms exceeded", "operation timed out",
                 "net::ERR_TIMED_OUT", "time out"):
        assert is_timeout(text) is True, text
    assert is_timeout("incorrect password") is False


def test_estimate_nights():
    clients = _clients(500)
    assert estimate_nights(clients, _cfg(clients_per_day=100)) == 5
    assert estimate_nights(clients, _cfg(clients_per_day=100, distribution="distribute",
                                         distribute_days=3)) == 6
    assert estimate_nights([], _cfg()) == 0


def test_format_countdown():
    assert format_countdown(42) == "0:42"
    assert format_countdown(90) == "1:30"
    assert format_countdown(3661) == "1:01:01"


def test_vault_credential_flag_and_password_update():
    with tempfile.TemporaryDirectory() as tmp:
        vault = VaultManager(vault_path=os.path.join(tmp, "vault.json"))
        client_id = vault.add_update_assessee(
            "Test Client", "ABCPE1234F", "01-01-1990", "old-password")
        assert vault.get_credential_invalid() == set()
        assert vault.set_client_credential_invalid("abcpe1234f", True) is True
        assert vault.get_credential_invalid() == {"ABCPE1234F"}

        vault.add_update_assessee(
            "Test Client", "ABCPE1234F", "01-01-1990", "old-password",
            assessee_id=client_id)
        assert vault.get_credential_invalid() == {"ABCPE1234F"}

        vault.add_update_assessee(
            "Test Client", "ABCPE1234F", "01-01-1990", "new-password",
            assessee_id=client_id)
        assert vault.get_credential_invalid() == set()


def test_vault_eproc_autofetch_config_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        vault = VaultManager(vault_path=os.path.join(tmp, "vault.json"))
        cfg = vault.get_eproc_autofetch_config()
        assert cfg["enabled"] is False
        assert cfg["clients_per_day"] == 20
        saved = vault.save_eproc_autofetch_config({
            "enabled": True,
            "distribution": "distribute",
            "distribute_days": 3,
            "clients_per_day": 500,
            "stop_keeps_remainder": False,
        })
        assert saved["enabled"] is True
        assert saved["distribution"] == "distribute"
        assert saved["distribute_days"] == 3
        assert saved["clients_per_day"] == 500
        assert saved["stop_keeps_remainder"] is False
        assert vault.get_setting("eproc_autofetch")["enabled"] is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

"""Tests for F-121 — Return Status tab (issue #121).

Covers the pure helpers in automation/return_status.py used to populate the
table (refund / e-verification decomposition, section extraction, audit-report
lookup), the audit-report portal probe (against a fake page), the
vault return_status_history round-trip, and an offscreen smoke test of
ReturnStatusTab itself (rows, columns, filters).

Run with:
    <venv>/python -m pytest tests/test_return_status.py -q
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from automation.return_status import (
    _derive_refund_status,
    _extract_section,
    _is_everify_pending,
    compute_everify_pending,
    has_audit_report,
    probe_audit_report,
)


# ── refund / status decomposition ────────────────────────────────────────────

@pytest.mark.parametrize("timeline,expected", [
    ("ITR Filed | Successfully e-Verified | Refund paid", "paid"),
    ("ITR Filed | Refund credited to bank account", "paid"),
    ("ITR Filed | Refund adjusted against demand", "adjusted"),
    ("Demand adjusted against refund", "adjusted"),
    ("ITR Filed | Refund is pending", "pending"),
    ("ITR Filed | Successfully e-Verified", ""),
    ("", ""),
    (None, ""),
])
def test_derive_refund_status(timeline, expected):
    assert _derive_refund_status(timeline) == expected


def test_compute_everify_pending_explicit_flag_wins():
    assert compute_everify_pending(True, False) is True
    assert compute_everify_pending(True, True) is False
    assert compute_everify_pending(False, False) is False


def test_compute_everify_pending_derived_from_status():
    assert compute_everify_pending(
        True, None, "Your return has been successfully e-Verified") is False
    assert compute_everify_pending(
        True, None, "ITR Processed with no demand/refund") is False
    assert compute_everify_pending(
        True, None, "Pending for e-Verification") is True
    # Filed, status inconclusive -> treat as still pending
    assert compute_everify_pending(True, None, "ITR Filed") is True


def test_compute_everify_pending_not_filed():
    assert compute_everify_pending(False, None, "") is False
    assert compute_everify_pending(None, None, "Pending for e-Verification") is False


def test_is_everify_pending_never_raises_on_junk():
    for junk in [None, "", 0, "irrelevant"]:
        assert isinstance(_is_everify_pending(junk), bool)


# ── section extraction ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("ITR-1 filed u/s 139(1) for AY 2026-27", "139(1)"),
    ("Filed under section 139(4)", "139(4)"),
    ("Return filed u/s. 142(1)", "142(1)"),
    ("139(1) original return", "139(1)"),
    ("Ack 123456789012345 on 31-Oct-2026", ""),
    ("", ""),
    (None, ""),
])
def test_extract_section(text, expected):
    assert _extract_section(text) == expected


# ── audit report lookup (local disk) ─────────────────────────────────────────

def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("x")


def test_has_audit_report_true_when_file_present():
    with tempfile.TemporaryDirectory() as root:
        _touch(os.path.join(
            root, "AAAAA0000A-Client", "Filed IT Forms",
            "3CB-3CD", "2025-26", "Form_3CB-3CD_2025-26.pdf"))
        assert has_audit_report(root, "AAAAA0000A", "2025-26") is True


def test_has_audit_report_false_when_dir_exists_but_no_file():
    with tempfile.TemporaryDirectory() as root:
        _touch(os.path.join(
            root, "AAAAA0000A-Client", "Filed IT Forms",
            "15CA", "2025-26", "Form_15CA.pdf"))
        assert has_audit_report(root, "AAAAA0000A", "2025-26") is False


def test_has_audit_report_none_when_nothing_downloaded():
    with tempfile.TemporaryDirectory() as root:
        assert has_audit_report(root, "AAAAA0000A", "2025-26") is None
    assert has_audit_report("/does/not/exist", "AAAAA0000A", "2025-26") is None


def test_has_audit_report_year_scoped():
    with tempfile.TemporaryDirectory() as root:
        _touch(os.path.join(
            root, "AAAAA0000A-Client", "Filed IT Forms",
            "3CB-3CD", "2024-25", "Form_3CB-3CD_2024-25.pdf"))
        assert has_audit_report(root, "AAAAA0000A", "2025-26") is False
        assert has_audit_report(root, "AAAAA0000A", "2024-25") is True


# ── audit report on the portal (fake page) ───────────────────────────────────

class _FakePage:
    def __init__(self, cards):
        self._cards = cards

    async def evaluate(self, script):
        return list(self._cards)


def _step(_msg):
    pass


def test_probe_audit_report_returns_true_when_category_present():
    page = _FakePage([
        "Information for payment to Non-Resident Form 15CA ...",
        "Audit report under section 44AB Form 3CB-3CD 13Filings till date",
    ])
    assert asyncio.run(probe_audit_report(page, _step)) is True


def test_probe_audit_report_returns_true_for_3ca_3cd():
    page = _FakePage(["Audited under Income-tax Act Form 3CA-3CD 2Filings"])
    assert asyncio.run(probe_audit_report(page, _step)) is True


def test_probe_audit_report_returns_false_when_no_audit_category():
    page = _FakePage([
        "Form 15CA Certain information",
        "Form 35 Appeal to JCIT",
        "Form 10IE intimation",
    ])
    assert asyncio.run(probe_audit_report(page, _step)) is False


# ── vault round trip ─────────────────────────────────────────────────────────

def test_vault_return_status_roundtrip_persists_rich_fields():
    from vault import VaultManager

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "vault.json")
        vm = VaultManager(path)
        vm.record_return_status(
            "aaaaa0000a", "2025-26", "ITR Processed",
            status_date="Aug 3, 2026", filing_date="31-Oct-2026",
            ack_no="174315830311026", filed=True, section="139(1)",
            revised=False, revised_section="", rectified=False,
            e_verified=True, processed=True, refund_status="paid",
            everify_pending=False)

        entry = vm.get_return_status("2025-26")["AAAAA0000A"]
        assert entry["status"] == "ITR Processed"
        assert entry["filed"] is True
        assert entry["section"] == "139(1)"
        assert entry["e_verified"] is True
        assert entry["processed"] is True
        assert entry["refund_status"] == "paid"
        assert entry["everify_pending"] is False

        # survives a reload from disk
        vm2 = VaultManager(path)
        assert vm2.get_return_status("2025-26")["AAAAA0000A"]["refund_status"] == "paid"


# ── offscreen GUI smoke test ─────────────────────────────────────────────────

class _FakeVault:
    def __init__(self, clients, status, audit_years):
        self._clients = clients
        self._status = status
        self._audit_years = audit_years
        self.saved = []

    def get_all_assessees(self):
        return self._clients

    def credential_sources(self, c):
        return c.get("_sources", [])

    def get_all_groups(self):
        return sorted({(c.get("group") or "").strip()
                       for c in self._clients if (c.get("group") or "").strip()})

    def get_return_status(self, ay):
        return self._status.get(ay, {})

    def get_audit_applicable_for_year(self, ay):
        return self._audit_years.get(ay, {})

    def set_audit_applicable(self, pan, ay, value):
        self._audit_years.setdefault(ay, {})[pan] = value
        self.saved.append((pan, ay, value))


def _entries():
    return [{"label": "2025-26", "year": {"AY": "2025-26"}},
            {"label": "2024-25", "year": {"AY": "2024-25"}}]


def _build_tab(qapp, vault):
    from ui.dialogs import ReturnStatusTab

    tab = ReturnStatusTab(
        vault, _entries(), lambda: "", lambda *a, **k: None, log_callback=None)
    tab.resize(1200, 600)
    return tab


@pytest.mark.gui
def test_tab_lists_only_income_tax_clients(qapp):
    clients = [
        {"name": "Alpha", "pan": "AAAAA0000A", "group": "G1",
         "_sources": ["Income Tax", "TDS"]},
        {"name": "Beta", "pan": "BBBBB0000B", "group": "G1",
         "_sources": ["TDS"]},
        {"name": "Gamma", "pan": "CCCCC0000C", "group": "G2",
         "_sources": ["GST"]},
    ]
    tab = _build_tab(qapp, _FakeVault(clients, {"2025-26": {}}, {}))
    pans = {r["pan"] for r in tab._row_data}
    assert pans == {"AAAAA0000A"}
    assert tab._table.rowCount() == 1


@pytest.mark.gui
def test_tab_columns_render_decomposed_status(qapp):
    from ui.dialogs import ReturnStatusTab as T

    status = {"2025-26": {"AAAAA0000A": {
        "status": "ITR Processed", "status_date": "Aug 3, 2026",
        "filed": True, "section": "139(1)", "revised": False,
        "rectified": False, "e_verified": True, "processed": True,
        "refund_status": "paid", "everify_pending": False,
    }}}
    clients = [{"name": "Alpha", "pan": "AAAAA0000A", "group": "G1",
                "_sources": ["Income Tax"]}]
    tab = _build_tab(qapp, _FakeVault(clients, status, {}))
    t = tab._table

    def cell(col):
        item = t.item(0, col)
        return item.text() if item else ""

    assert cell(T._COL_FILED) == "Yes"
    assert cell(T._COL_SECTION) == "139(1)"
    assert cell(T._COL_REFUND) == "Refund paid"
    assert "ITR Processed" in cell(T._COL_STATUS)
    assert cell(T._COL_EVERIFY) == "Done"


@pytest.mark.gui
def test_tab_pending_everify_filter(qapp):
    status = {"2025-26": {
        "AAAAA0000A": {"filed": True, "processed": False, "e_verified": False,
                       "everify_pending": True, "status": "Pending for e-Verification"},
        "BBBBB0000B": {"filed": True, "processed": True, "e_verified": True,
                       "everify_pending": False, "status": "ITR Processed"},
    }}
    clients = [
        {"name": "Alpha", "pan": "AAAAA0000A", "_sources": ["Income Tax"]},
        {"name": "Beta", "pan": "BBBBB0000B", "_sources": ["Income Tax"]},
    ]
    tab = _build_tab(qapp, _FakeVault(clients, status, {}))
    tab._chk_pending_everify.setChecked(True)
    assert {r["pan"] for r in tab._row_data} == {"AAAAA0000A"}


@pytest.mark.gui
def test_tab_audit_report_filter(qapp):
    clients = [
        {"name": "Alpha", "pan": "AAAAA0000A", "_sources": ["Income Tax"]},
        {"name": "Beta", "pan": "BBBBB0000B", "_sources": ["Income Tax"]},
    ]
    audit = {"2025-26": {"AAAAA0000A": True, "BBBBB0000B": True}}
    tab = _build_tab(qapp, _FakeVault(clients, {}, audit))
    tab._audit_report_by_pan = {"AAAAA0000A": True, "BBBBB0000B": False}
    tab._chk_audit_report_filed.setChecked(True)
    assert {r["pan"] for r in tab._row_data} == {"AAAAA0000A"}
    tab._chk_audit_report_filed.setChecked(False)
    tab._chk_audit_report_not_filed.setChecked(True)
    assert {r["pan"] for r in tab._row_data} == {"BBBBB0000B"}


@pytest.mark.gui
def test_tab_audit_probe_callback_invoked_for_applicable_clients(qapp):
    clients = [
        {"name": "Alpha", "pan": "AAAAA0000A", "_sources": ["Income Tax"]},
        {"name": "Beta", "pan": "BBBBB0000B", "_sources": ["Income Tax"]},
    ]
    calls = []

    def _probe(ay, pans):
        calls.append((ay, sorted(pans)))

    from ui.dialogs import ReturnStatusTab

    tab = ReturnStatusTab(
        _FakeVault(clients, {}, {"2025-26": {"AAAAA0000A": True}}),
        _entries(), lambda: "", lambda *a, **k: None,
        log_callback=None, audit_probe=_probe)
    tab.probe_audit()
    assert calls == [("2025-26", ["AAAAA0000A"])]

    # results applied from the background probe filter as expected
    tab.set_audit_report_results({"AAAAA0000A": False})
    assert tab._audit_report_by_pan["AAAAA0000A"] is False

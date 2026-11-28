"""Tests for the litigation store (F-26)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.litigation.store import LitigationStore
from core.litigation.model import matter_totals
from vault import VaultManager


def _store():
    tmp = tempfile.TemporaryDirectory()
    vault = VaultManager(vault_path=os.path.join(tmp.name, "v.json"))
    return tmp, LitigationStore(vault), vault


def test_case_close_mirrors_into_eproc_case_state():
    tmp, store, vault = _store()
    try:
        uid = "it:AABCP1234F:01:AY_2024_25"
        assert store.case_closed(uid) is False
        store.set_case_closed(uid, True)
        assert store.case_closed(uid) is True
        state = vault.get_setting("eproc_case_state", {})
        assert state["AABCP1234F:01:AY_2024_25"]["closed"] is True
        store.set_case_closed(uid, False)
        assert vault.get_setting("eproc_case_state", {})[
            "AABCP1234F:01:AY_2024_25"]["closed"] is False
    finally:
        tmp.cleanup()


def test_doc_overrides_round_trip():
    tmp, store, _ = _store()
    try:
        store.set_doc_replied("it:case#n1", True)
        store.set_doc_ignored("it:case#n2", True)
        ov = store.doc_overrides()
        assert ov["it:case#n1"]["replied"] is True
        assert ov["it:case#n2"]["ignored"] is True
    finally:
        tmp.cleanup()


def test_manual_hearings_dedup():
    tmp, store, _ = _store()
    try:
        uid = "it:AABCP1234F:01:AY_2024_25"
        store.add_hearing(uid, "15-Dec-2026")
        store.add_hearing(uid, "15-Dec-2026")
        assert store.hearings(uid) == ["15-Dec-2026"]
        store.remove_hearing(uid, "15-Dec-2026")
        assert store.hearings(uid) == []
    finally:
        tmp.cleanup()


def test_matter_crud_and_case_link():
    tmp, store, _ = _store()
    try:
        matter = store.add_matter("aabcp1234f", "Sample Client", "GST SCN 2026")
        assert matter.client_pan == "AABCP1234F"
        assert store.matter(matter.id) is not None

        uid = "it:AABCP1234F:01:AY_2024_25"
        store.link_case(uid, matter.id)
        assert store.case_matter_id(uid) == matter.id
        assert store.case_matter_map()[uid] == matter.id

        assert store.update_matter(matter.id, title="Renamed matter") is True
        assert store.matter(matter.id).title == "Renamed matter"

        store.delete_matter(matter.id)
        assert store.matter(matter.id) is None
        assert store.case_matter_id(uid) == ""
    finally:
        tmp.cleanup()


def test_fee_entries_and_totals():
    tmp, store, _ = _store()
    try:
        matter = store.add_matter("AABCP1234F", "Sample Client", "Matter")
        store.add_fee(matter.id, "fee", "Professional fee", 50000,
                      "agreed", "01-Apr-2026")
        store.add_fee(matter.id, "billing", "Invoice 1", 25000,
                      "billed", "01-May-2026")
        store.add_fee(matter.id, "reimbursement", "Portal fee", 2000,
                      "outstanding", "01-May-2026")
        fees = store.fees(matter.id)
        assert len(fees) == 3
        totals = matter_totals(fees)
        assert totals["fee"] == 50000
        assert totals["reimbursement"] == 2000
        assert totals["billed"] == 25000

        fee_id = fees[0].id
        assert store.update_fee(fee_id, amount=60000, status="received") is True
        assert store.fees(matter.id)[0].amount == 60000
        store.delete_fee(fee_id)
        assert len(store.fees(matter.id)) == 2
    finally:
        tmp.cleanup()


def test_delete_matter_removes_its_fees():
    tmp, store, _ = _store()
    try:
        matter = store.add_matter("AABCP1234F", "Sample Client", "Matter")
        store.add_fee(matter.id, "fee", "Fee", 1000, "agreed")
        store.delete_matter(matter.id)
        assert store.fees() == []
    finally:
        tmp.cleanup()

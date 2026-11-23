"""Tests for the Income Tax litigation adapter (F-26)."""

import json
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.litigation.adapters import collect_all
from core.litigation.model import EVENT_REPLY, MODULE_IT
from core.litigation.store import LitigationStore
from vault import VaultManager


def _make_root(tmp, meta):
    """Lay out <root>/<PAN>-<Name>/AY_2024_25/e-Proceedings/1 - Scrutiny/."""
    pan = "AABCP1234F"
    client = os.path.join(tmp, f"{pan}-Sample Client")
    year = os.path.join(client, "AY_2024_25")
    eproc = os.path.join(year, "e-Proceedings")
    proc = os.path.join(eproc, "1 - Scrutiny")
    os.makedirs(proc)
    with open(os.path.join(proc, "_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
    return tmp


def _vault_and_store(tmp):
    vault = VaultManager(vault_path=os.path.join(tmp, "v.json"))
    return vault, LitigationStore(vault)


META = {
    "proceeding": {"name": "Scrutiny", "ay": "2024-25"},
    "notices": [
        {
            "index": 1,
            "description": "Notice under section 143(2)",
            "section": "143(2)",
            "issued_on": "01-Oct-2026",
            "response_due": "15-Nov-2026",
        },
    ],
}


def test_adapter_builds_unified_case_and_reply_event():
    tmp = tempfile.mkdtemp()
    _make_root(tmp, META)
    _, store = _vault_and_store(tmp)
    assessees = [{"pan": "AABCP1234F", "name": "Sample Client"}]

    cases, events = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    assert len(cases) == 1
    case = cases[0]
    assert case.module == MODULE_IT
    assert case.client_pan == "AABCP1234F"
    assert case.case_type == "notice"

    replies = [e for e in events if e.kind == EVENT_REPLY]
    assert replies and replies[0].date == date(2026, 11, 15)
    assert replies[0].visible is True


def test_closing_case_from_litigation_updates_it_model_status():
    tmp = tempfile.mkdtemp()
    _make_root(tmp, META)
    _, store = _vault_and_store(tmp)
    assessees = [{"pan": "AABCP1234F", "name": "Sample Client"}]

    cases, _ = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    uid = cases[0].uid
    store.set_case_closed(uid, True)

    cases2, events2 = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    assert cases2[0].closed is True
    assert cases2[0].status == "Closed"
    replies = [e for e in events2 if e.kind == EVENT_REPLY]
    assert replies and replies[0].visible is False


def test_manual_hearing_creates_separate_calendar_event():
    tmp = tempfile.mkdtemp()
    _make_root(tmp, META)
    _, store = _vault_and_store(tmp)
    assessees = [{"pan": "AABCP1234F", "name": "Sample Client"}]

    cases, _ = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    uid = cases[0].uid
    store.add_hearing(uid, "20-Nov-2026")

    _, events = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    hearings = [e for e in events if e.kind == "hearing"]
    assert len(hearings) == 1
    assert hearings[0].date == date(2026, 11, 20)


def test_replied_doc_override_hides_reply_event():
    tmp = tempfile.mkdtemp()
    _make_root(tmp, META)
    _, store = _vault_and_store(tmp)
    assessees = [{"pan": "AABCP1234F", "name": "Sample Client"}]

    _, events = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    reply_event = next(e for e in events if e.kind == EVENT_REPLY)
    store.set_doc_replied(f"it:{reply_event.native_doc_id}", True)

    _, events2 = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    replies = [e for e in events2 if e.kind == EVENT_REPLY]
    assert replies and replies[0].visible is False


def test_event_level_ignore_hides_deadline():
    tmp = tempfile.mkdtemp()
    _make_root(tmp, META)
    _, store = _vault_and_store(tmp)
    assessees = [{"pan": "AABCP1234F", "name": "Sample Client"}]

    _, events = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    reply_event = next(e for e in events if e.kind == EVENT_REPLY)
    assert reply_event.visible is True

    store.set_doc_ignored(reply_event.eid, True)

    _, events2 = collect_all(tmp, assessees, store, today=date(2026, 10, 20))
    replies = [e for e in events2 if e.kind == EVENT_REPLY]
    assert replies and replies[0].visible is False

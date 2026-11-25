"""Unit tests for the GST notices downloader pure functions + model + adapter."""
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.gst.notices import (
    normalise_rows,
    notice_key,
    merge_meta,
    load_meta,
    _field_for_header,
    _responded,
    _is_order,
    sanitize_name,
    dedupe_path,
)
from ui.gst_proceedings_model import (
    build_cases,
    filter_cases,
    kpis,
    _parse_date,
)
from core.litigation.adapters.gst import GstAdapter
from core.litigation.model import MODULE_GST


def _row(**cells):
    headers = {
        "notice_type": "Notice/Order Type",
        "ref_id": "Reference No",
        "gstin": "GSTIN",
        "trade_name": "Trade Name",
        "section": "Section",
        "description": "Description",
        "issued_on": "Notice/Order Date",
        "due_date": "Due Date",
        "status": "Status",
    }
    mapped = {headers[key]: value for key, value in cells.items()}
    return {"cells": mapped, "actions": [], "table_index": 0, "row_index": 0}


def test_header_mapping_aliases():
    assert _field_for_header("Notice/Order Date") == "issued_on"
    assert _field_for_header("Ref. No.") == "ref_id"
    assert _field_for_header("GSTIN/UIN") == "gstin"
    assert _field_for_header("Unknown Column") == ""


def test_normalise_rows_basic():
    rows = normalise_rows([
        _row(notice_type="ASMT-10", ref_id="AA000000000000A", gstin="00AAAAA0000A0Z0",
             issued_on="01-Jan-2026", due_date="15-Jan-2026", status="Pending",
             description="Show cause notice"),
        {"cells": {"Column 1": "x"}, "actions": []},
    ])
    assert len(rows) == 1
    notice = rows[0]
    assert notice["notice_type"] == "ASMT-10"
    assert notice["ref_id"] == "AA000000000000A"
    assert notice["gstin"] == "00AAAAA0000A0Z0"
    assert notice["due_date"] == "15-Jan-2026"
    assert notice["is_order"] is False
    assert notice["index"] == 1


def test_is_order_and_responded():
    assert _is_order("DRC-07", "Demand order") is True
    assert _is_order("ASMT-10", "Scrutiny notice") is False
    assert _is_order("DRC-01", "Show cause") is False
    assert _responded("Replied", []) is True
    assert _responded("Pending", [{"text": "Reply"}]) is True
    assert _responded("Pending", []) is False


def test_notice_key_fallbacks():
    assert notice_key({"ref_id": "AA1", "issued_on": "01-Jan-2026"}) == "AA1|01-Jan-2026"
    assert notice_key({"gstin": "00X", "notice_type": "DRC-01",
                       "issued_on": "01-Jan-2026"}) == "00X|DRC-01|01-Jan-2026"
    assert notice_key({}) == ""


def test_sanitize_and_dedupe():
    assert sanitize_name("a/b:c") == "a_b_c"
    with tempfile.TemporaryDirectory() as tmp:
        first = dedupe_path(tmp, "x.pdf")
        open(first, "w").close()
        second = dedupe_path(tmp, "x.pdf")
        assert os.path.basename(second) == "x (1).pdf"


def test_merge_meta_preserves_and_numbers():
    old = {"notices": [
        {"ref_id": "OLD1", "issued_on": "01-Jan-2026", "files": ["notice-01/old1.pdf"],
         "notice_type": "DRC-01"},
    ]}
    rows = normalise_rows([_row(notice_type="DRC-01", ref_id="NEW1",
                                issued_on="02-Feb-2026")])
    key = notice_key(rows[0])
    meta = merge_meta(old, rows, {key: {"files": ["notice-01/new1.pdf"]}},
                      "2026-02-02 10:00:00")
    refs = [entry["ref_id"] for entry in meta["notices"]]
    assert refs == ["NEW1", "OLD1"]
    assert meta["notices"][0]["files"] == ["notice-01/new1.pdf"]
    assert meta["notices"][1]["files"] == ["notice-01/old1.pdf"]
    assert meta["module"] == "gst"
    assert meta["downloaded_at"] == "2026-02-02 10:00:00"


def _write_meta(root, client_folder, notices):
    import json
    base = os.path.join(root, client_folder, "GST-Proceedings")
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "_meta.json"), "w", encoding="utf-8") as handle:
        json.dump({"schema": 1, "module": "gst",
                   "downloaded_at": "2026-02-02 10:00:00",
                   "notices": notices}, handle)


def test_model_build_cases_statuses():
    with tempfile.TemporaryDirectory() as tmp:
        _write_meta(tmp, "GSTLOGIN01-Sample Client", [
            {"index": 1, "notice_type": "DRC-01", "ref_id": "A", "section": "61",
             "issued_on": "01-Jan-2026", "due_date": "01-Feb-2026",
             "status": "Pending", "responded": False, "is_order": False,
             "files": ["notice-01/a.pdf"], "reply_files": [], "order_files": []},
            {"index": 2, "notice_type": "DRC-07", "ref_id": "B", "section": "",
             "issued_on": "01-Jan-2026", "due_date": "01-Feb-2026",
             "status": "Order passed", "responded": True, "is_order": True,
             "files": ["notice-02/b.pdf"],
             "order_files": ["notice-02/b.pdf"], "reply_files": []},
        ])
        cases = build_cases(tmp, [], today=date(2026, 3, 1))
        assert len(cases) == 2
        by_ref = {case.ref_id: case for case in cases}
        assert by_ref["A"].status == "Overdue"
        assert by_ref["B"].status == "Closed"
        assert by_ref["B"].is_order is True
        counts = kpis(cases)
        assert counts["total"] == 2
        assert counts["orders"] == 1


def test_filter_cases_search_and_status():
    with tempfile.TemporaryDirectory() as tmp:
        _write_meta(tmp, "GSTLOGIN01-Sample Client", [
            {"index": 1, "notice_type": "DRC-01", "ref_id": "A",
             "issued_on": "01-Jan-2026", "due_date": "01-Feb-2026",
             "status": "Pending", "responded": False, "is_order": False,
             "files": ["notice-01/a.pdf"]},
        ])
        cases = build_cases(tmp, [], today=date(2026, 1, 15))
        assert len(filter_cases(cases, "sample", "")) == 1
        assert len(filter_cases(cases, "", "Open")) == 1
        assert len(filter_cases(cases, "", "Replied")) == 0


def test_parse_date_formats():
    assert _parse_date("01-Jan-2026") == date(2026, 1, 1)
    assert _parse_date("2026-01-01") == date(2026, 1, 1)
    assert _parse_date("") is None


def test_gst_adapter_builds_case_and_reply_event():
    with tempfile.TemporaryDirectory() as tmp:
        _write_meta(tmp, "GSTLOGIN01-Sample Client", [
            {"index": 1, "notice_type": "DRC-01", "ref_id": "A", "section": "61",
             "issued_on": "01-Jan-2026", "due_date": "01-Mar-2026",
             "status": "Pending", "responded": False, "is_order": False,
             "files": ["notice-01/a.pdf"]},
        ])
        adapter = GstAdapter()
        cases = adapter.collect_cases(tmp, [], store=_FakeStore(), today=date(2026, 2, 1))
        assert len(cases) == 1
        assert cases[0].module == MODULE_GST
        events = adapter.collect_events(cases, _FakeStore(), today=date(2026, 2, 1))
        assert len(events) == 1
        assert events[0].date == date(2026, 3, 1)
        assert events[0].visible is True


class _FakeStore:
    def case_matter_map(self):
        return {}

    def case_ignored(self, uid):
        return False


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


def test_classify_error_lockout():
    from automation.gst.login import classify_error
    assert classify_error("Your account has been locked. Kindly access Forgot Password") == "locked"
    assert classify_error("Enter valid Letters shown") == "wrong"
    assert classify_error("Invalid Username or Password") == "credentials"


def test_merge_api_rows_dedupes_dom_rows():
    from automation.gst.notices import merge_api_rows
    rows = normalise_rows([
        _row(notice_type="Notice", ref_id="AA1", issued_on="01-Jan-2026"),
        _row(notice_type="Notice", ref_id="STALE", issued_on="01-Jan-2026"),
        _row(notice_type="Notice", ref_id="STALE", issued_on="01-Jan-2026"),
    ])
    api_rows = [{"noticeOrderId": "AA1", "type": "Notice", "descr": "",
                 "dtOfIssue": "01/01/2026", "dueDate": "10/01/2026",
                 "amount": "NA", "addtnlDocs": None}]
    merged = merge_api_rows(rows, api_rows)
    # Duplicate DOM rows collapse to one; a unique DOM-only row is preserved.
    refs = [r["ref_id"] for r in merged]
    assert refs.count("STALE") == 1
    assert refs[0] == "AA1"


def test_merge_api_rows_includes_case_tasks():
    from automation.gst.notices import merge_api_rows
    rows = normalise_rows([_row(notice_type="Notice", ref_id="AA1",
                                issued_on="01-Jan-2026")])
    notices = [{"noticeOrderId": "AA1", "type": "Notice", "descr": "x",
                "dtOfIssue": "01/01/2026", "dueDate": "10/01/2026",
                "amount": "NA", "addtnlDocs": None}]
    cases = [{"refId": "CASE1", "taskDesc": "Appeal order uploaded",
              "caseTypeName": "First Appeal", "assignmentDt": "2026-02-01",
              "caseId": 123, "caseFolderItemId": 456, "caseTpeCd": "APLAC"}]
    merged = merge_api_rows(rows, notices, cases)
    by_ref = {r["ref_id"]: r for r in merged}
    assert "CASE1" in by_ref
    assert by_ref["CASE1"]["source"] == "case"
    assert by_ref["CASE1"]["case_id"] == "123"
    assert by_ref["CASE1"]["is_order"] is True


def test_merge_api_rows_attaches_ids_and_amounts():
    from automation.gst.notices import merge_api_rows
    rows = normalise_rows([
        _row(notice_type="Order", ref_id="AA000000000001",
             issued_on="17-Nov-2025", due_date="NA"),
        _row(notice_type="Notice", ref_id="AA000000000002",
             issued_on="15-Nov-2025", due_date="15-Dec-2025"),
    ])
    api_rows = [
        {"noticeOrderId": "AA000000000001", "type": "Order", "amount": "NA",
         "docId": 11111111, "appDefId": None, "pdfDownloadURL": None,
         "applnCd": "CNREG", "issuedBy": "System Generated", "isRead": "N",
         "status": None, "action": None, "insertTmstmp": "17/11/2025 10:00:00",
         "suppDocId": None, "addtnlDocs": None},
        {"noticeOrderId": "AA000000000002", "type": "Notice", "amount": "1,234.00",
         "docId": None, "appDefId": "36856209",
         "pdfDownloadURL": "/returns/auth/gstr3a", "applnCd": "APL3A",
         "issuedBy": "System Generated", "isRead": "Y", "status": "Replied",
         "action": None, "insertTmstmp": "15/11/2025 10:00:00",
         "suppDocId": None, "addtnlDocs": []},
    ]
    merged = merge_api_rows(rows, api_rows)
    assert merged[0]["doc_id"] == "11111111"
    assert merged[0]["is_order"] is True
    assert merged[1]["app_def_id"] == "36856209"
    assert merged[1]["amount"] == "1,234.00"
    assert merged[1]["pdf_download_url"] == "/returns/auth/gstr3a"
    assert merged[1]["responded"] is True


def test_merge_meta_carries_api_fields():
    rows = normalise_rows([_row(notice_type="Order", ref_id="AA1",
                                issued_on="17-Nov-2025")])
    rows = __import__("automation.gst.notices", fromlist=["merge_api_rows"]).merge_api_rows(
        rows, [{"noticeOrderId": "AA1", "type": "Order", "amount": "500",
                "docId": 222, "addtnlDocs": []}])
    meta = merge_meta({}, rows, {notice_key(rows[0]): {"files": ["notice-01/x.pdf"]}},
                      "2026-01-01 00:00:00")
    entry = meta["notices"][0]
    assert entry["amount"] == "500"
    assert entry["doc_id"] == "222"
    assert entry["is_order"] is True


def test_amount_value_parsing():
    from ui.gst_proceedings_model import GstCase, amount_value
    def case(amount):
        return GstCase(id="x", client_key="GSTLOGIN01", client_name="S",
                       gstin="", trade_name="", notice_type="Order", ref_id="A",
                       description="", section="", issued="", due="", raw_status="",
                       status="Open", responded=False, is_order=True, amount=amount)
    assert amount_value(case("1,234.50")) == 1234.5
    assert amount_value(case("₹ 2,000")) == 2000.0
    assert amount_value(case("NA")) == 0.0
    assert amount_value(case("")) == 0.0

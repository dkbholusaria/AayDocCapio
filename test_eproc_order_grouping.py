import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.eproceedings_model import build_cases


FILES = [
    "order-01/AABCP1234F_Order us 147_1003(1)_01042025.pdf",
    "order-01/AABCP1234F_Demand Notice_1002(1)_01042025.pdf",
    "order-01/AABCP1234F_Computation Sheet_1001(1)_01042025.pdf",
]


def _make_tree(tmp_path, notices):
    base = (
        tmp_path / "AABCP1234F-Sample Client" / "AY_2025_26"
        / "e-Proceedings" / "01-Assessment Proceeding u_s 147"
    )
    (base / "order-01").mkdir(parents=True)
    for rel in FILES:
        (base / rel).write_bytes(b"")
    meta = {
        "proceeding": {
            "name": "Assessment Proceeding u/s 147",
            "ay": "2025-26",
            "status": "Closed",
        },
        "closed": True,
        "downloaded_at": "2026-11-24 10:00:00",
        "notices": notices,
        "orders": [{
            "title": "Order u/s 147",
            "filename": os.path.basename(FILES[0]),
            "files": FILES,
        }],
        "hearings": [],
    }
    (base / "_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def _orders(cases):
    return [doc for case in cases for doc in case.docs if doc.kind == "order"]


def test_order_with_multiple_files_is_one_document(tmp_path):
    root = _make_tree(tmp_path, notices=[
        {"index": 1, "ref_id": "R1", "description": "Notice u/s 143(2)",
         "issued_on": "01-Jan-2025", "response_due": "15-Jan-2025",
         "responded": True, "section": "143(2)", "viewed_by_ao": "",
         "is_order": False, "files": [], "response_files": []},
    ])
    cases = build_cases(str(root), [])
    orders = _orders(cases)
    assert len(orders) == 1
    assert len(orders[0].files) == 3


def test_order_without_notices_is_one_document(tmp_path):
    root = _make_tree(tmp_path, notices=[])
    orders = _orders(build_cases(str(root), []))
    assert len(orders) == 1
    assert len(orders[0].files) == 3

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.downloader_e_proceedings import _order_download_targets


def _row(index, filename):
    return {"row_index": index, "filename": filename}


def test_all_distinct_modal_rows_become_targets():
    rows = [
        _row(0, "AABCP1234F_Order us 147_1(1)_01012025.pdf"),
        _row(1, "AABCP1234F_Demand Notice us 156_1(1)_01012025.pdf"),
        _row(2, "AABCP1234F_Computation Sheet_1(1)_01012025.pdf"),
    ]
    targets = _order_download_targets(rows)
    assert [t["row_index"] for t in targets] == [0, 1, 2]
    assert [t["filename"] for t in targets] == [r["filename"] for r in rows]


def test_single_modal_row_is_kept():
    rows = [_row(0, "AABCP1234F_Order us 250_1(1)_01012025.pdf")]
    assert _order_download_targets(rows) == rows


def test_duplicate_filename_is_kept_once():
    rows = [
        _row(0, "AABCP1234F_Order us 147_1(1).pdf"),
        _row(1, "AABCP1234F_Order us 147_1(1).pdf"),
        _row(2, "AABCP1234F_Demand Notice_1(1).pdf"),
    ]
    targets = _order_download_targets(rows)
    assert [t["row_index"] for t in targets] == [0, 2]


def test_blank_filenames_are_skipped():
    rows = [_row(0, "  "), _row(1, ""), _row(2, "AABCP1234F_Order us 147_1.pdf")]
    assert [t["row_index"] for t in _order_download_targets(rows)] == [2]


def test_empty_input():
    assert _order_download_targets([]) == []


from automation.downloader_e_proceedings import _diff_build_meta

_ORDER_ONE = "order-01/AABCP1234F_Order us 147_1(1)_01012025.pdf"
_ORDER_TWO = "order-01/AABCP1234F_Demand Notice us 156_1(1)_01012025.pdf"
_ORDER_THREE = "order-01/AABCP1234F_Computation Sheet_1(1)_01012025.pdf"


def test_meta_records_every_downloaded_order_document():
    meta = _diff_build_meta(
        {"name": "Assessment Proceeding u/s 147", "ay": "2025-26", "status": "Closed"},
        [], {}, {}, {}, "now",
        orders=[{"title": "Order u/s 147", "filename": "Order us 147.pdf",
                 "files": [_ORDER_ONE, _ORDER_TWO, _ORDER_THREE]}],
    )
    assert len(meta["orders"]) == 1
    assert meta["orders"][0]["files"] == [_ORDER_ONE, _ORDER_TWO, _ORDER_THREE]


def test_meta_merge_drops_dict_duplicate_files():
    old = {"orders": [{"title": "Order u/s 147", "filename": "Order us 147.pdf",
                       "files": [_ORDER_ONE, _ORDER_ONE]}]}
    meta = _diff_build_meta(
        {"name": "P", "ay": "2025-26", "status": "Closed"},
        [], {}, {}, old, "now",
        orders=[{"title": "Order u/s 147", "filename": "Order us 147.pdf",
                 "files": [_ORDER_ONE, _ORDER_TWO, _ORDER_THREE]}],
    )
    assert meta["orders"] == [{"title": "Order u/s 147",
                              "filename": "Order us 147.pdf",
                              "files": [_ORDER_ONE, _ORDER_TWO, _ORDER_THREE]}]


def test_meta_keeps_old_order_files_the_modal_no_longer_lists():
    old = {"orders": [{"title": "Order u/s 147", "filename": "Order us 147.pdf",
                       "files": [_ORDER_ONE, _ORDER_TWO, _ORDER_THREE]}]}
    meta = _diff_build_meta(
        {"name": "P", "ay": "2025-26", "status": "Closed"},
        [], {}, {}, old, "now",
        orders=[{"title": "Order u/s 147", "filename": "Order us 147.pdf",
                 "files": [_ORDER_ONE, _ORDER_TWO, _ORDER_THREE]}],
    )
    files = meta["orders"][0]["files"]
    assert files == [_ORDER_ONE, _ORDER_TWO, _ORDER_THREE]

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.challan_index import (
    classify_status,
    format_size,
    parse_identity,
    parse_year,
    scan_saved_challans,
)


def _touch(path: str, mtime: float):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4\n")
    os.utime(path, (mtime, mtime))


def _build_tree(root: str):
    files = {
        "AABCP1234F-Sample Client/TY_2026_27/Tax Challans (Payable)/"
        "AABCP1234F-Challan-TY_2026_27-Advance_Tax-111111.pdf": 1_000,
        "AABCP1234F-Sample Client/TY_2026_27/Tax Challans (Paid)/"
        "AABCP1234F-Challan-2026_27-CIN123-Advance_Tax.pdf": 2_000,
        "AMRA12345D-Sample Client/TY_2026_27/Tax Challans (Payable)/"
        "AMRA12345D-TDS-Challan-TY_2026_27-222222.pdf": 3_000,
        "AABCP1235G-Legacy/Challans/"
        "AABCP1235G-Challan-2025_26-old-Self_Assessment.pdf": 4_000,
        "AABCP1236H-Old/Tax Challans (Generated)/"
        "AABCP1236H-Challan-AY_2025_26-Self_Assessment-333333.pdf": 5_000,
        "Unrelated/random.pdf": 6_000,
        "AABCP1234F-Sample Client/TY_2026_27/Tax Challans (Paid)/notes.txt": 7_000,
    }
    for rel, mtime in files.items():
        _touch(os.path.join(root, rel), mtime)


CLIENTS = [
    {"pan": "AABCP1234F", "name": "Sample Client"},
    {"pan": "ABCD12345E", "name": "Sample Client"},
]


def test_classification_helpers():
    assert classify_status("Tax Challans (Paid)") == "Paid"
    assert classify_status("Challans") == "Paid"
    assert classify_status("Tax Challans") == "Paid"
    assert classify_status("Tax Challans (Payable)") == "Unpaid"
    assert classify_status("tax challans (generated)") == "Unpaid"
    assert classify_status("26AS") is None
    assert parse_year("TY_2026_27") == "TY 2026-27"
    assert parse_year("AY_2025_26") == "AY 2025-26"
    assert parse_year("AABCP1234F-Challan-2026_27-CIN-Advance.pdf") == "2026-27"
    assert parse_year("nothing here") == ""
    assert parse_identity("AABCP1234F-Sample Client") == "AABCP1234F"
    assert parse_identity("", "AMRA12345D-TDS-Challan-TY.pdf") == "AMRA12345D"
    assert parse_identity("random-folder") == ""
    assert format_size(999) == "999 B"
    assert format_size(1500) == "1.5 KB"


def test_scan_saved_challans():
    with tempfile.TemporaryDirectory() as tmp:
        _build_tree(tmp)
        rows = scan_saved_challans(tmp, CLIENTS)

        assert len(rows) == 5
        assert [r["filename"] for r in rows][0].startswith("AABCP1236H")  # newest first
        assert {r["status"] for r in rows} == {"Paid", "Unpaid"}
        assert sum(1 for r in rows if r["status"] == "Paid") == 2
        assert sum(1 for r in rows if r["status"] == "Unpaid") == 3

        by_name = {r["filename"]: r for r in rows}
        sample_paid = by_name["AABCP1234F-Challan-2026_27-CIN123-Advance_Tax.pdf"]
        assert sample_paid["client_name"] == "Sample Client"
        assert sample_paid["year"] == "TY 2026-27"
        assert sample_paid["status"] == "Paid"
        assert sample_paid["payment_type"] == "Advance Tax"
        assert sample_paid["doc_type"] == "Income Tax"

        tds = by_name["AMRA12345D-TDS-Challan-TY_2026_27-222222.pdf"]
        assert tds["client_name"] == "Sample Client"
        assert tds["doc_type"] == "TDS/TCS"
        assert tds["payment_type"] == "TDS/TCS"
        assert tds["status"] == "Unpaid"

        legacy_paid = by_name["AABCP1235G-Challan-2025_26-old-Self_Assessment.pdf"]
        assert legacy_paid["status"] == "Paid"
        assert legacy_paid["payment_type"] == "Self Assessment"

        legacy_generated = by_name[
            "AABCP1236H-Challan-AY_2025_26-Self_Assessment-333333.pdf"]
        assert legacy_generated["status"] == "Unpaid"
        assert legacy_generated["year"] == "AY 2025-26"

        names = {r["filename"] for r in rows}
        assert "random.pdf" not in names
        assert "notes.txt" not in names


def test_scan_missing_root():
    assert scan_saved_challans("") == []
    assert scan_saved_challans("/definitely/not/a/real/folder") == []


def test_view_dialog_filters_and_actions():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui.challan_viewer as viewer

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        _build_tree(tmp)
        dlg = viewer.ViewChallansDialog(None, tmp, CLIENTS)
        try:
            assert dlg._table.rowCount() == 5
            assert dlg._summary.text().startswith("5 challans")

            dlg._status_combo.setCurrentIndex(dlg._status_combo.findData("Paid"))
            assert dlg._table.rowCount() == 2

            dlg._status_combo.setCurrentIndex(0)
            idx = dlg._client_combo.findData("AABCP1234F")
            assert idx > 0
            dlg._client_combo.setCurrentIndex(idx)
            assert dlg._table.rowCount() == 2

            dlg._client_combo.setCurrentIndex(0)
            dlg._year_combo.setCurrentIndex(dlg._year_combo.findData("TY 2026-27"))
            assert dlg._table.rowCount() == 3

            dlg._year_combo.setCurrentIndex(0)
            dlg._search.setText("TDS")
            assert dlg._table.rowCount() == 1
            dlg._search.setText("no-such-file")
            assert dlg._table.rowCount() == 0
            assert "No challans match" in dlg._empty.text()
            dlg._search.clear()
            assert dlg._table.rowCount() == 5

            opened = []
            original = viewer._open_path
            viewer._open_path = lambda p: opened.append(p)
            try:
                dlg._table.selectRow(0)
                dlg._open_file()
                dlg._open_folder()
            finally:
                viewer._open_path = original
            assert len(opened) == 2
            assert opened[0].endswith(".pdf")
            assert os.path.isdir(opened[1])
            assert os.path.dirname(opened[0]) == opened[1]
        finally:
            dlg.deleteLater()
            app.processEvents()


def test_view_dialog_empty_state():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from ui.challan_viewer import ViewChallansDialog

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        dlg = ViewChallansDialog(None, tmp, CLIENTS)
        try:
            assert dlg._table.rowCount() == 0
            assert "No saved challans" in dlg._empty.text()
            assert not dlg._open_file_btn.isEnabled()
        finally:
            dlg.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    test_classification_helpers()
    test_scan_saved_challans()
    test_scan_missing_root()
    test_view_dialog_filters_and_actions()
    test_view_dialog_empty_state()
    print("PASS")

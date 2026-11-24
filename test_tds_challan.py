import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vault import VaultManager, identify_type, _validate_fields


def test_identify_type():
    assert identify_type("AABCP1234F") == "PAN"
    assert identify_type("ABCD12345E") == "TAN"
    assert identify_type("") == ""
    assert identify_type("ABCDE1234") == ""


def test_vault_accepts_tan_without_dob():
    with tempfile.TemporaryDirectory() as tmp:
        v = VaultManager(vault_path=os.path.join(tmp, "v.json"))
        v.add_update_assessee("Sample Deductor", "ABCD12345E", "", "testpass")
        clients = v.get_all_assessees()
        assert len(clients) == 1
        assert clients[0]["pan"] == "ABCD12345E"
        assert clients[0]["id_type"] == "TAN"


def test_vault_still_accepts_pan_with_dob():
    with tempfile.TemporaryDirectory() as tmp:
        v = VaultManager(vault_path=os.path.join(tmp, "v.json"))
        v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980", "testpass")
        assert v.get_all_assessees()[0]["id_type"] == "PAN"


def test_pan_still_requires_dob():
    try:
        _validate_fields("Sample Client", "AABCP1234F", "", "testpass")
    except ValueError as e:
        assert "Date of Birth" in str(e)
    else:
        raise AssertionError("PAN without DOB should be rejected")


def test_bad_identity_rejected():
    try:
        _validate_fields("Sample Client", "ABCDE1234", "01-01-1980", "testpass")
    except ValueError as e:
        assert "PAN / TAN" in str(e)
    else:
        raise AssertionError("Invalid identity should be rejected")


from automation.tds_sections import SECTIONS, section_by_code, description_for


def test_section_catalogue():
    assert len(SECTIONS) == 64
    assert len({s["code"] for s in SECTIONS}) == 64
    assert section_by_code("1002")["label"].startswith("Payment of Employees")
    assert section_by_code("9999") is None
    assert description_for("1002") == section_by_code("1002")["label"]


from automation.challan_generator_tds import tds_row_total, validate_tds_row


def _row(**over):
    row = {
        "tan": "ABCD12345E",
        "deductee_type": "other_than_company",
        "residence": "resident",
        "sections": [{"section_code": "1002", "tax": 1000, "surcharge": 0, "cess": 0}],
        "interest": 0, "fee": 0, "penalty": 0, "others": 0,
        "payment_mode": "Pay at Bank Counter",
        "bank": "Cheque",
        "drawee_bank": "Kotak Mahindra Bank",
    }
    row.update(over)
    return row


def test_tds_total():
    r = _row(sections=[
        {"section_code": "1002", "tax": 1000, "surcharge": 100, "cess": 18},
        {"section_code": "1006", "tax": 500, "surcharge": 0, "cess": 9},
    ], interest=10, fee=20, penalty=30, others=40)
    assert tds_row_total(r) == 1727


def test_valid_row_passes():
    assert validate_tds_row(_row()) == ""


def test_rejects_bad_tan():
    assert "TAN" in validate_tds_row(_row(tan="AABCP1234F"))


def test_rejects_empty_sections():
    assert "section" in validate_tds_row(_row(sections=[])).lower()


def test_rejects_too_many_sections():
    secs = [{"section_code": "1002", "tax": 1, "surcharge": 0, "cess": 0}] * 21
    assert "20" in validate_tds_row(_row(sections=secs))


def test_rejects_unknown_section_code():
    assert "9999" in validate_tds_row(
        _row(sections=[{"section_code": "9999", "tax": 1, "surcharge": 0, "cess": 0}]))


def test_rejects_zero_total():
    assert "zero" in validate_tds_row(
        _row(sections=[{"section_code": "1002", "tax": 0, "surcharge": 0, "cess": 0}])).lower()


def test_rejects_cash_over_ten_thousand():
    r = _row(bank="Cash", sections=[{"section_code": "1002", "tax": 10001, "surcharge": 0, "cess": 0}])
    assert "10,000" in validate_tds_row(r)


def test_rejects_missing_drawee_bank():
    assert "Drawn on Bank" in validate_tds_row(_row(drawee_bank=""))


def test_rejects_unsupported_deductee_type():
    assert "Company" in validate_tds_row(_row(deductee_type="company"))


def test_tds_challans_is_registered_alias():
    from automation.batch_handlers import HANDLERS, DOC_TYPE_LABELS, ordered_doc_types
    assert HANDLERS["tds_challans"] is HANDLERS["challans"]
    assert DOC_TYPE_LABELS["tds_challans"] == "TDS/TCS Challans"
    assert "tds_challans" in ordered_doc_types({"tds_challans"})


def test_download_dialog_lists_only_tan_clients():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from ui.dialogs import DownloadTdsChallansDialog

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        v = VaultManager(vault_path=os.path.join(tmp, "v.json"))
        v.add_update_assessee("Sample Deductor", "ABCD12345E", "", "testpass")
        v.add_update_assessee("Sample Client", "AABCP1234F", "01-01-1980", "testpass")
        years = [
            {"label": "TY 2026-27 (FY 2026-27)", "enabled": True,
             "year": {"TY": "2026-27", "FY": "2026-27"}},
            {"label": "AY 2025-26 (FY 2024-25)", "enabled": True,
             "year": {"AY": "2025-26", "FY": "2024-25"}},
        ]
        dlg = DownloadTdsChallansDialog(None, v, years)
        assert [c["pan"] for c in dlg._all_clients] == ["ABCD12345E"]
        assert dlg._year_combo.model_.rowCount() == 2
        # Tick the TAN row + first year, then confirm selection.
        dlg._table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        dlg._year_combo.set_checked_labels([years[0]["label"]])
        dlg._on_download()
        assert [c["pan"] for c in dlg.selected_clients] == ["ABCD12345E"]
        assert dlg.year_labels == [years[0]["label"]]
        dlg.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    test_identify_type()
    test_vault_accepts_tan_without_dob()
    test_vault_still_accepts_pan_with_dob()
    test_pan_still_requires_dob()
    test_bad_identity_rejected()
    test_section_catalogue()
    test_tds_total()
    test_valid_row_passes()
    test_rejects_bad_tan()
    test_rejects_empty_sections()
    test_rejects_too_many_sections()
    test_rejects_unknown_section_code()
    test_rejects_zero_total()
    test_rejects_cash_over_ten_thousand()
    test_rejects_missing_drawee_bank()
    test_rejects_unsupported_deductee_type()
    test_tds_challans_is_registered_alias()
    test_download_dialog_lists_only_tan_clients()
    print("PASS")

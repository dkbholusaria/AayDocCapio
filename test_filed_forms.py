import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.downloader_filed_forms import (
    form_code_from_text,
    filing_year_from_text,
    parse_filing_text,
    filing_stem,
    artifact_path,
    existing_artifact,
    safe_name,
)

CATEGORY_3CB = (
    "Audit report under section 44AB [Audited under Income-tax Act]"
    "Statement of particulars under section 44AB Form 3CB-3CD "
    "13Filings till date Recently filed A.Y. 2026-27 View All"
)
CATEGORY_15CA = (
    "Information for payment to Non-Resident Form 15CA 1Filings till date "
    "Recently filed F.Y. View All"
)
CATEGORY_35 = (
    "Appeal to the Joint Commissioner (Appeals) or the Commissioner "
    "(Appeals) Form 35 2Filings till date Recently filed A.Y. 2015-16 View All"
)

FILING_3CB = (
    "A.Y.2026-27 View Details Filing Date 31-Oct-2026 1 Form submitted "
    "31-Oct-2026 Filing Type : Revised Status : Successfully e-Verified "
    "Acknowledgement No : 174315830311026 Filed By : CA Download Form "
    "Download Receipt Download Attachments Download JSON"
)
FILING_15CA = (
    "Acknowledgement No :491579970140922 14-Sep-2022 Filing Date "
    "Financial Year : 2022-23 Remittee Name : ess ess consultancy ltd "
    "Status : Successfully e-Verified Filed By : AAAPL1234C "
    "Filing mode : Online Filing Type : Original Part : D "
    "Country of Remittance : BANGLADESH Download Form Download Receipt"
)
FILING_35 = (
    "A.Y.2015-16 View Details Filing Date 19-Mar-2025 1 Form submitted "
    "19-Mar-2025 Filing Type : Original Status : Successfully e-Verified "
    "Acknowledgement No : 905820100190325 Filed By : SELF Download Form "
    "Download Receipt Download Attachments"
)


def test_form_code_from_category_text():
    assert form_code_from_text(CATEGORY_3CB) == "3CB-3CD"
    assert form_code_from_text(CATEGORY_15CA) == "15CA"
    assert form_code_from_text(CATEGORY_35) == "35"
    # Alphanumeric suffixes must survive intact (10-IC is not "10").
    assert form_code_from_text(
        "Application ... Form 10-IC 1Filings till date") == "10-IC"
    assert form_code_from_text("Form 146 3Filings") == "146"
    assert form_code_from_text("Form 3CD") == "3CD"
    assert form_code_from_text("No form here") == "Unknown_Form"


def test_filing_year_prefers_fy_for_15ca():
    assert filing_year_from_text(FILING_15CA) == "2022-23"
    assert filing_year_from_text(FILING_3CB) == "2026-27"
    assert filing_year_from_text(FILING_35) == "2015-16"


def test_parse_filing_text():
    parsed = parse_filing_text(FILING_3CB)
    assert parsed["ack"] == "174315830311026"
    assert parsed["year"] == "2026-27"
    assert parsed["filing_date"] == "31-Oct-2026"
    assert parsed["filing_type"] == "Revised"

    parsed = parse_filing_text(FILING_15CA)
    assert parsed["ack"] == "491579970140922"
    assert parsed["year"] == "2022-23"
    assert parsed["filing_type"] == "Original"


def test_filing_stem_is_unique_and_filesystem_safe():
    parsed = parse_filing_text(FILING_3CB)
    assert filing_stem("3CB-3CD", parsed) == "Form_3CB-3CD_174315830311026"
    assert safe_name("Form 3CB/3CD: test") == "Form_3CB_3CD_test"


def test_artifact_path_drops_portal_form_prefix():
    parsed = parse_filing_text(FILING_3CB)
    stem = filing_stem("3CB-3CD", parsed)
    p = artifact_path("/tmp/x", stem, "3CB-3CD",
                      "Form 3CB-3CD_Filed Form.zip")
    assert os.path.basename(p) == f"{stem}_Filed_Form.zip"

    p = artifact_path("/tmp/x", stem, "3CB-3CD",
                      "Form 3CB-3CD_ARN.pdf")
    assert os.path.basename(p) == f"{stem}_ARN.pdf"

    p = artifact_path("/tmp/x", stem, "3CB-3CD", "174315830311026.json")
    assert os.path.basename(p) == f"{stem}.json"


def test_artifact_path_for_form_35():
    parsed = parse_filing_text(FILING_35)
    stem = filing_stem("35", parsed)
    p = artifact_path("/tmp/x", stem, "35", "Form 35_Filed Form.pdf")
    assert os.path.basename(p) == f"{stem}_Filed_Form.pdf"


def test_existing_artifact_detects_saved_kinds():
    with tempfile.TemporaryDirectory() as tmp:
        stem = "Form_35_905820100190325"
        open(os.path.join(tmp, f"{stem}_Filed_Form.pdf"), "w").close()
        open(os.path.join(tmp, f"{stem}_ARN.pdf"), "w").close()
        open(os.path.join(tmp, f"{stem}.json"), "w").close()
        assert existing_artifact(tmp, stem, "Filed_Form")
        assert existing_artifact(tmp, stem, "ARN")
        assert existing_artifact(tmp, stem, "JSON")
        assert existing_artifact(tmp, stem, "XML") is None
        open(os.path.join(tmp, f"{stem}_Attachments.zip"), "w").close()
        assert any(
            n.startswith(stem + "_Attachments") for n in os.listdir(tmp))


def test_filed_forms_registered_as_doc_type():
    from automation.batch_handlers import (
        HANDLERS, DOC_TYPE_LABELS, ordered_doc_types)
    assert DOC_TYPE_LABELS["filed_forms"] == "Filed IT Forms"
    assert "filed_forms" in HANDLERS
    assert "filed_forms" in ordered_doc_types({"filed_forms"})
    # Must run before 26AS, immediately after Filed Returns (same e-File menu).
    order = ordered_doc_types(
        {"filed_forms", "filed_returns", "26as", "e_proceedings"})
    assert order.index("filed_returns") < order.index("filed_forms")
    assert order.index("filed_forms") < order.index("26as")


def test_download_picker_offers_filed_forms():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from ui.dialogs import DownloadPickerDialog
    from vault import VaultManager

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        vault = VaultManager(vault_path=os.path.join(tmp, "v.json"))
        dlg = DownloadPickerDialog(None, vault)
        assert "filed_forms" in dlg._cbs
        assert dlg._cbs["filed_forms"].text() == "Filed IT Forms"
        dlg.close()

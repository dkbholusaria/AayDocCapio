import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from ui.eproc_doc_modal import EprocDocModal
from ui.eproceedings_model import Assessee, Case, Doc


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _case(files):
    doc = Doc(
        id="PAN:01:AY_2025_26#o901",
        kind="order",
        title="Order u/s 147",
        section="147",
        issued="01-Apr-2025",
        served="01-Apr-2025",
        reply_deadline="",
        urg="",
        files=list(files),
    )
    return Case(
        id="PAN:01:AY_2025_26",
        pan="AABCP1234F",
        name="Sample Client",
        ays=["2025-26"],
        case_open=False,
        remanded=False,
        assessee=Assessee(name="Sample Client", pan="AABCP1234F"),
        docs=[doc],
        appeals=[],
        proc_name="Assessment Proceeding u/s 147",
        year_label="AY 2025-26",
        proc_dir="/tmp/eproc-sample",
        downloaded_at="2026-11-24 10:00:00",
    ), doc


def test_modal_lists_every_attached_file(app):
    files = [
        "order-01/AABCP1234F_Order us 147_1003(1)_01042025.pdf",
        "order-01/AABCP1234F_Demand Notice_1002(1)_01042025.pdf",
        "order-01/AABCP1234F_Computation Sheet_1001(1)_01042025.pdf",
    ]
    case, doc = _case(files)
    modal = EprocDocModal(case, doc.id)
    try:
        assert len(modal.attachment_rows) == 3
        labels = " ".join(modal.attachment_rows)
        assert "Order" in labels
        assert "Demand Notice" in labels
        assert "Computation Sheet" in labels
    finally:
        modal.deleteLater()


def test_modal_single_attachment(app):
    case, doc = _case(["order-01/AABCP1234F_Order us 147_1003(1).pdf"])
    modal = EprocDocModal(case, doc.id)
    try:
        assert len(modal.attachment_rows) == 1
    finally:
        modal.deleteLater()


def test_modal_without_attachments_has_no_rows(app):
    case, doc = _case([])
    modal = EprocDocModal(case, doc.id)
    try:
        assert modal.attachment_rows == []
    finally:
        modal.deleteLater()

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.doc_types import e_proceeding_doc_label


def test_computation_sheet_label():
    assert e_proceeding_doc_label(
        "AABCP1234F_Computation Sheet_1001(1)_01042025.pdf"
    ) == "Computation Sheet"


def test_demand_notice_label():
    assert e_proceeding_doc_label(
        "AABCP1234F_Demand Notice_1002(1)_01042025.pdf"
    ) == "Demand Notice"


def test_order_with_section_label():
    assert e_proceeding_doc_label(
        "AABCP1234F_Order us 147_1003(1)_01042025.pdf"
    ) == "Order u/s 147"


def test_order_without_section_label():
    assert e_proceeding_doc_label(
        "AABCP1234F_Order_1004(1)_01042025.pdf"
    ) == "Order"


def test_unknown_filename_falls_back_to_filename():
    name = "AABCP1234F_Some Letter_1005(1)_01042025.pdf"
    assert e_proceeding_doc_label(name) == name


def test_empty_filename_returns_default():
    assert e_proceeding_doc_label("") == "Document"


from automation.doc_types import e_proceeding_attachment_text


def test_attachment_text_lists_all_types():
    text = e_proceeding_attachment_text([
        "order-01/AABCP1234F_Order us 147_1003(1).pdf",
        "order-01/AABCP1234F_Demand Notice_1002(1).pdf",
        "order-01/AABCP1234F_Computation Sheet_1001(1).pdf",
    ])
    assert text == (
        "3 documents: Order u/s 147 · Demand Notice · Computation Sheet"
    )


def test_attachment_text_single_document():
    text = e_proceeding_attachment_text([
        "order-01/AABCP1234F_Order us 147_1003(1).pdf",
    ])
    assert text == "1 document: Order u/s 147"


def test_attachment_text_empty():
    assert e_proceeding_attachment_text([]) == ""

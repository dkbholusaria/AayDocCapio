import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.eproceedings_model import Doc, _build_meta_docs


def _meta(viewed_by_ao="", response_files=None):
    return {
        "notices": [
            {
                "index": 1,
                "ref_id": "100045020270",
                "description": "Notice u/s 142(1) of Income Tax Act 1961.",
                "issued_on": "04-Mar-2022",
                "response_due": "10-Mar-2022",
                "responded": bool(response_files),
                "section": "142(1)",
                "viewed_by_ao": viewed_by_ao,
                "is_order": False,
                "files": ["notice-01/n.pdf"],
                "response_files": response_files or [],
            }
        ]
    }


def test_viewed_by_ao_populated_on_notice_and_reply():
    docs = _build_meta_docs(
        "PAN:01:AY_2020-21", "Assessment Proceeding",
        _meta("18-Mar-2022", ["response-01/r_15032022.pdf"]))

    by_kind = {doc.kind: doc for doc in docs}
    assert by_kind["notice"].viewed_by_ao == "18-Mar-2022"
    assert by_kind["reply"].viewed_by_ao == "18-Mar-2022"


def test_viewed_by_ao_blank_when_absent():
    docs = _build_meta_docs(
        "PAN:01:AY_2020-21", "Assessment Proceeding",
        _meta("", ["response-01/r_15032022.pdf"]))

    by_kind = {doc.kind: doc for doc in docs}
    assert by_kind["notice"].viewed_by_ao == ""
    assert by_kind["reply"].viewed_by_ao == ""


def test_viewed_by_ao_defaults_empty_on_plain_doc():
    doc = Doc(id="x", kind="notice", title="t", section="", issued="",
              served="", reply_deadline="", urg="")
    assert doc.viewed_by_ao == ""


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")

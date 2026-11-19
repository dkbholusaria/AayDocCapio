import sys
import os
import re
import tempfile

# Add the project root to python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.downloader_e_proceedings import (
    _parse_proceeding_card_text,
    _parse_notices_page_text,
    _sanitize_name,
    _dedupe_path,
)

F60 = "/tmp/f60_explore"


def _html_to_text(html: str) -> str:
    """Minimal regex-based innerText extraction (matches playwright's
    innerText closely enough for block-level portal markup)."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>|</(p|div|td|th|tr|li|span|a|button|h[1-6]|mat-card[^>]*)>",
                  "\n", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = (html.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&#x27;", "'").replace("&#39;", "'").replace("&quot;", '"'))
    lines = [ln.strip() for ln in html.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ---------------------------------------------------------------- card parse

CARD_1 = """Proceeding Name :
Issue Letter
Assessment Year :
Not Available
PAN
[REDACTED_PAN]
Name of Assessee
[REDACTED_NAME]
Proceeding Status
Open"""

CARD_2 = """Proceeding Name :
Assessment Proceeding u/s 147
Assessment Year :
2016-17
PAN
[REDACTED_PAN]
Proceeding Status
Blocked"""


def test_card_parse_basic():
    r = _parse_proceeding_card_text(CARD_1)
    assert r == {"name": "Issue Letter", "ay": "Not Available", "status": "Open"}, r

    r = _parse_proceeding_card_text(CARD_2)
    assert r == {"name": "Assessment Proceeding u/s 147", "ay": "2016-17",
                 "status": "Blocked"}, r


def test_card_parse_missing_proceeding_name():
    assert _parse_proceeding_card_text("PAN\n[REDACTED_PAN]\nProceeding Status\nOpen") is None
    assert _parse_proceeding_card_text("") is None


def test_card_parse_missing_lines():
    # Empty value line after label, and trailing labels with nothing after
    r = _parse_proceeding_card_text("Proceeding Name :\n\nAssessment Year :\nProceeding Status")
    assert r is not None
    assert r["name"] == ""
    assert r["ay"] == ""
    assert r["status"] == ""


# ------------------------------------------------------------- notices parse

NOTICES_PAGE = """Notice/ Communication Reference ID : 100087682387
Notice u/s
ITBA/COM/F/17/2024-25/1070632290(1)
Document reference ID
Description : [ITBA]Issue Letter
Issued On : 26-Nov-2024
Submit Response
Notice/Letter Pdf
Notice/ Communication Reference ID : 100045020270
142(1)
Notice u/s
Description : [ITBA]Notice u/s 142(1)of Income Tax Act 1961.
Issued On : 04-Mar-2022
Response Due Date : 10-Mar-2022"""


def test_notices_parse_multiple():
    ns = _parse_notices_page_text(NOTICES_PAGE)
    assert len(ns) == 2, ns
    n1, n2 = ns
    assert n1["ref_id"] == "100087682387"
    assert n1["description"] == "Issue Letter"
    assert n1["issued_on"] == "26-Nov-2024"
    assert n1["response_due"] == ""
    assert n2["ref_id"] == "100045020270"
    assert n2["description"] == "Notice u/s 142(1)of Income Tax Act 1961."
    assert n2["issued_on"] == "04-Mar-2022"
    assert n2["response_due"] == "10-Mar-2022"


def test_notices_parse_empty():
    assert _parse_notices_page_text("") == []
    assert _parse_notices_page_text("no notices here at all") == []


# ------------------------------------------------------------ sanitize/dedupe

def test_sanitize_name():
    assert _sanitize_name("Notice us 142(1)") == "Notice us 142(1)"
    assert _sanitize_name("Issue Letter_1070632290(1)") == "Issue Letter_1070632290(1)"
    assert _sanitize_name("") == "document"
    assert _sanitize_name("a/b\\c:d*e?f\"g<h>i|j") == "a_b_c_d_e_f_g_h_i_j"
    assert _sanitize_name(None) == "document"
    assert _sanitize_name("  spaced  ") == "spaced"
    assert len(_sanitize_name("x" * 400)) == 150


def test_dedupe_path():
    with tempfile.TemporaryDirectory() as d:
        assert _dedupe_path(d, "Notice.pdf").endswith("Notice.pdf")
        open(os.path.join(d, "Notice.pdf"), "w").close()
        assert _dedupe_path(d, "Notice.pdf").endswith("Notice (1).pdf")
        open(os.path.join(d, "Notice (1).pdf"), "w").close()
        assert _dedupe_path(d, "Notice.pdf").endswith("Notice (2).pdf")
        # different extension does not collide
        assert _dedupe_path(d, "Notice.txt").endswith("Notice.txt")


# --------------------------------------------------- real captured fixtures

def test_real_landing_page_cards():
    """30_bvqpr_landing.html — 9 'For your Action' proceedings."""
    p = os.path.join(F60, "30_bvqpr_landing.html")
    if not os.path.exists(p):
        print("SKIP real fixtures: /tmp/f60_explore missing")
        return
    text = _html_to_text(open(p, encoding="utf-8", errors="replace").read())

    # Split the body text into card-sized chunks on each 'Proceeding Name :'
    # marker and parse each chunk (cards carry their label-value pairs).
    chunks = re.split(r"(?=Proceeding Name\s*:)", text)
    parsed = [c for c in (_parse_proceeding_card_text(ch) for ch in chunks) if c]
    names = [r["name"] for r in parsed]
    print(f"  landing cards parsed: {len(parsed)} -> {names}")
    assert len(parsed) >= 9, f"expected >=9 proceedings, got {len(parsed)}"
    assert names.count("Issue Letter") >= 3
    assert "Assessment Proceeding u/s 147" in names
    assert "Notice u/s 142(1)" in names
    assert all(r["name"] for r in parsed)
    # AY extraction on the same-line variant too: 'Assessment Year : 2016-17'
    ays = [r["ay"] for r in parsed]
    assert "2016-17" in ays and "2017-18" in ays


def test_real_147_notices():
    """40_p6_Assessment_Proceedin_body.txt — 3 notices for the s.147 case."""
    p = os.path.join(F60, "40_p6_Assessment_Proceedin_body.txt")
    if not os.path.exists(p):
        print("SKIP real fixtures: /tmp/f60_explore missing")
        return
    text = open(p, encoding="utf-8", errors="replace").read()
    ns = _parse_notices_page_text(text)
    print(f"  s147 notices parsed: {len(ns)} -> {[n['ref_id'] for n in ns]}")
    assert len(ns) == 3, ns
    assert [n["ref_id"] for n in ns] == ["100045020270", "100040712598", "100034251294"]
    assert ns[0]["response_due"] == "10-Mar-2022"
    assert ns[2]["response_due"] == ""          # s.148 notice has no due date
    assert ns[2]["description"] == "Notice u/s 148of Income Tax Act 1961."
    assert all(n["issued_on"] for n in ns)


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
    sys.exit(1 if failed else 0)

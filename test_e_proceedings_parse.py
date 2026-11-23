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
    _notice_key,
    _load_existing_meta,
    _meta_entries_by_key,
    _files_present,
    _synced_keys,
    _merge_rel_files,
    _diff_build_meta,
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


# ------------------------------------------------------- incremental sync diff

def _notice(ref, issued, desc="Notice"):
    return {"ref_id": ref, "issued_on": issued, "description": desc,
            "response_due": "", "responded": False, "section": "",
            "viewed_by_ao": "", "is_order": False}


def test_notice_key():
    assert _notice_key(_notice("100", "26-Nov-2024")) == "100|26-Nov-2024"
    assert _notice_key(_notice("", "26-Nov-2024")) == ""     # unknown -> never skip
    assert _notice_key({}) == ""


def test_load_existing_meta_missing_or_corrupt():
    with tempfile.TemporaryDirectory() as d:
        assert _load_existing_meta(d) == {}
        with open(os.path.join(d, "_meta.json"), "w") as f:
            f.write("{not json")
        assert _load_existing_meta(d) == {}
        with open(os.path.join(d, "_meta.json"), "w") as f:
            f.write("[1, 2]")
        assert _load_existing_meta(d) == {}


def test_files_present_and_synced_keys():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "notice-01"))
        open(os.path.join(d, "notice-01", "a.pdf"), "w").close()
        assert _files_present(d, ["notice-01/a.pdf"]) is True
        assert _files_present(d, ["notice-01/missing.pdf"]) is False
        assert _files_present(d, []) is False
        meta = {"notices": [
            dict(_notice("1", "d1"), index=1, files=["notice-01/a.pdf"]),
            dict(_notice("2", "d2"), index=2, files=[]),
        ]}
        assert _synced_keys(d, meta, "files") == {"1|d1"}
        assert _synced_keys(d, meta, "response_files") == set()


def test_meta_entries_by_key():
    meta = {"notices": [dict(_notice("1", "d1"), index=1)]}
    by = _meta_entries_by_key(meta)
    assert set(by) == {"1|d1"}


def test_merge_rel_files_keeps_old_appends_new():
    assert _merge_rel_files([], []) == []
    assert _merge_rel_files(["notice-01/a.pdf"],
                            ["notice-03/a.pdf", "notice-03/b.pdf"]) == \
        ["notice-01/a.pdf", "notice-03/b.pdf"]


def test_diff_build_meta_downloads_only_new_and_preserves_old():
    old = {
        "proceeding": {"name": "P", "ay": "2020-21", "status": "Open"},
        "downloaded_at": "old",
        "notices": [
            dict(_notice("1", "d1", "Old seen"), index=1,
                 files=["notice-01/old.pdf"], response_files=["response-01/r.pdf"]),
            dict(_notice("9", "d9", "Hidden now"), index=9,
                 files=["notice-09/hidden.pdf"]),
        ],
    }
    current = [_notice("1", "d1", "Old seen"), _notice("2", "d2", "Brand new")]
    meta = _diff_build_meta(
        {"name": "P", "ay": "2020-21", "status": "Open"},
        current,
        notice_files={1: ["/tmp/new-notice.pdf"]},   # only notice #2 downloaded
        response_files={},
        old_meta=old,
        downloaded_at="now",
    )
    by_key = {_notice_key(e): e for e in meta["notices"]}
    # reused notice keeps its old file paths
    assert by_key["1|d1"]["files"] == ["notice-01/old.pdf"]
    assert by_key["1|d1"]["response_files"] == ["response-01/r.pdf"]
    # new notice carries the fresh download, numbered by its position
    assert by_key["2|d2"]["files"] == ["notice-02/new-notice.pdf"]
    # portal-hidden notice is preserved (renumbered past current portal list)
    assert "9|d9" in by_key
    assert by_key["9|d9"]["index"] == 3
    # metadata refreshed from portal
    assert by_key["1|d1"]["description"] == "Old seen"
    assert meta["downloaded_at"] == "now"


def test_diff_build_meta_merges_new_response_attachment():
    old = {"notices": [dict(_notice("1", "d1"), index=1,
                            files=["notice-01/a.pdf"],
                            response_files=["response-01/r1.pdf"])]}
    meta = _diff_build_meta({}, [_notice("1", "d1")], {},
                            {0: ["/tmp/r2.pdf"]}, old, "now")
    assert meta["notices"][0]["response_files"] == [
        "response-01/r1.pdf", "response-01/r2.pdf"]


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


# ----------------------------------------------------------- VC / hearings

def _vc_row():
    return {
        "date": {"text": "07-Feb-2024", "links": []},
        "rfsvca": {"text": "Matter requires explanation due to complexity",
                   "links": [{"txt": "Matter requires explanation due to complexity"}]},
        "vcdt": {"text": "10-Feb-2024 12:30 PM", "links": []},
        "sa": {"text": "Completed", "links": []},
        "itdrd": {"text": "09-Feb-2024", "links": []},
        "vcld": {"text": "VC Recording", "links": [{"txt": "VC Recording"}]},
        "itdR": {"text": "VC Schedule Notice\nStatus and VC recording",
                 "links": [{"txt": "VC Schedule Notice"},
                           {"txt": "Status and VC recording"}]},
    }


def test_parse_vc_table_basic():
    from automation.downloader_e_proceedings import _parse_vc_table
    rows = _parse_vc_table([_vc_row()])
    assert len(rows) == 1
    r = rows[0]
    assert r["vc_datetime"] == "10-Feb-2024 12:30 PM"
    assert r["status"] == "Completed"
    assert r["request_date"] == "07-Feb-2024"
    assert r["itd_response_date"] == "09-Feb-2024"
    assert "VC Recording" in r["links"]
    assert "Status and VC recording" in r["links"]
    assert "VC Schedule Notice" in r["links"]


def test_parse_vc_table_empty():
    from automation.downloader_e_proceedings import _parse_vc_table
    assert _parse_vc_table([]) == []
    assert _parse_vc_table([{}]) == []


def test_hearing_key():
    from automation.downloader_e_proceedings import _hearing_key
    assert _hearing_key({"notice_ref": "1", "vc_datetime": "X"}) == "1|X"
    assert _hearing_key({"notice_ref": "", "vc_datetime": "X"}) == ""
    assert _hearing_key({"notice_ref": "1", "vc_datetime": ""}) == ""


def test_synced_hearing_helpers():
    from automation.downloader_e_proceedings import (
        _synced_hearing_keys, _synced_hearing_notice_refs)
    meta = {"hearings": [
        {"notice_ref": "1", "vc_datetime": "D1", "recording_url": "u"},
        {"notice_ref": "2", "vc_datetime": "D2", "files": ["vc-01/a.pdf"]},
        {"notice_ref": "3", "vc_datetime": "", "recording_url": "u"},
    ]}
    assert _synced_hearing_keys(meta) == {"1|D1", "2|D2"}
    assert _synced_hearing_notice_refs(meta) == {"1", "2"}


def test_merge_hearings_keeps_cached():
    from automation.downloader_e_proceedings import _merge_hearings
    old = {"hearings": [
        {"notice_ref": "1", "vc_datetime": "D1",
         "recording_url": "http://old", "files": ["vc-01/a.pdf"]},
    ]}
    # Fresh entry lacks recording url + files — cached values are kept.
    merged = _merge_hearings(old, [
        {"notice_ref": "1", "vc_datetime": "D1", "status": "Completed"}])
    assert len(merged) == 1
    assert merged[0]["recording_url"] == "http://old"
    assert merged[0]["files"] == ["vc-01/a.pdf"]
    assert merged[0]["status"] == "Completed"


def test_diff_build_meta_includes_hearings():
    meta = _diff_build_meta(
        {"name": "Assessment Proceeding u/s 147", "ay": "2015-16",
         "status": "Open"},
        [], {}, {}, {}, "2026-11-23 10:00:00",
        orders=[],
        hearings=[{"notice_ref": "1", "vc_datetime": "10-Feb-2024 12:30 PM",
                   "recording_url": "http://x/webcams.webm",
                   "files": ["vc-01/sched.pdf"]}],
        vc_requestable=True)
    assert meta["hearings"][0]["recording_url"] == "http://x/webcams.webm"
    assert meta["vc_requestable"] is True


def test_model_build_hearings():
    from ui.eproceedings_model import _build_hearings, Hearing
    hs = _build_hearings({"hearings": [
        {"notice_ref": "1", "vc_datetime": "10-Feb-2024 12:30 PM",
         "status": "Completed", "recording_url": "http://x",
         "files": ["vc-01/a.pdf"]}]})
    assert len(hs) == 1
    assert isinstance(hs[0], Hearing)
    assert hs[0].recording_url == "http://x"
    assert hs[0].files == ["vc-01/a.pdf"]
    # Legacy meta (no hearings key) -> empty
    assert _build_hearings({}) == []


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

"""Tests for GST proceeding grouping (F-129)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.gst_proceedings_model import (
    GstCase,
    history_key,
    proceedings_groups,
    group_for_case,
)


def _case(cid, case_id, ref, issued, client="Sample Client",
          gstin="00AAAAA0000A0Z0"):
    return GstCase(
        id=cid, client_key="GSTLOGIN01", client_name=client, gstin=gstin,
        trade_name="", notice_type="DRC-01", ref_id=ref,
        description="Sample notice", section="", issued=issued, due="",
        raw_status="Open", status="Open", responded=False, is_order=False,
        case_id=case_id,
    )


def test_missing_case_and_ref_falls_back_to_id():
    assert history_key(_case("1", "CASE1", "REF1", "01-Nov-2026")) == "CASE1"
    assert history_key(_case("2", "", "REF2", "01-Nov-2026")) == "REF2"
    assert history_key(_case("3", "", "", "01-Nov-2026")) == "3"


def test_groups_by_case_id_newest_first():
    cases = [
        _case("1", "CASE1", "REF1", "01-Nov-2026"),
        _case("2", "CASE1", "REF2", "20-Nov-2026"),
        _case("3", "CASE2", "REF3", "10-Nov-2026"),
    ]
    groups = proceedings_groups(cases)
    assert len(groups) == 2
    assert groups[0]["key"] == "CASE1"
    assert [c.id for c in groups[0]["cases"]] == ["2", "1"]
    assert groups[0]["latest"].id == "2"
    assert groups[0]["count"] == 2
    assert groups[1]["key"] == "CASE2"


def test_separate_ids_stay_separate():
    cases = [
        _case("1", "", "", "01-Nov-2026"),
        _case("2", "CASE1", "REF2", "02-Nov-2026"),
    ]
    groups = proceedings_groups(cases)
    assert len(groups) == 2
    assert {g["key"] for g in groups} == {"1", "CASE1"}


def test_group_for_case_returns_matching_group():
    a = _case("1", "CASE1", "REF1", "01-Nov-2026")
    b = _case("2", "CASE1", "REF2", "20-Nov-2026")
    group = group_for_case([a, b], a)
    assert group is not None
    assert group["key"] == "CASE1"
    assert len(group["cases"]) == 2

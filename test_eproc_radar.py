"""Tests for the e-Proceedings deadline radar + related proceedings (F-129)."""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.eproceedings_model import (
    Assessee,
    Case,
    Doc,
    deadline_radar,
    related_proceedings,
)

TODAY = date(2026, 11, 26)


def _doc(did, kind, issued="", deadline="", status="Open", served=""):
    return Doc(
        id=did, kind=kind, title=did, section="", issued=issued,
        served=served, reply_deadline=deadline, urg="Medium", status=status,
    )


def _case(cid, pan, docs, proc="P", year="AY_2024_25"):
    return Case(
        id=cid, pan=pan, name="Sample Client", ays=["2024-25"],
        case_open=True, remanded=False,
        assessee=Assessee(name="Sample Client", pan=pan),
        docs=docs, appeals=[], proc_name=proc, year_label="AY 2024-25",
        proc_dir=cid,
    )


def test_radar_buckets_are_narrowest_window_only():
    case = _case("c1", "AABCP1234F", [
        _doc("n1", "notice", issued="25 Nov 2026",
             deadline="03 Dec 2026"),          # notices today; due d7
        _doc("n2", "notice", issued="12 Nov 2026",
             deadline="20 Dec 2026"),          # issued d15; due d30
        _doc("n3", "notice", issued="01 Oct 2026",
             deadline="01 Nov 2026"),          # old; overdue (excluded)
    ])
    radar = deadline_radar([case], today=TODAY)
    # 25 Nov (1 day ago) -> d7 bucket; 12 Nov (14 days) -> d15; 01 Oct -> past
    assert radar["notices_issued"] == {"today": 0, "d7": 1, "d15": 1, "d30": 0}
    # only the two future deadlines count; overdue n3 is excluded
    assert radar["replies_due"] == {"today": 0, "d7": 1, "d15": 0, "d30": 1}


def test_radar_counts_replies_and_orders():
    case = _case("c1", "AABCP1234F", [
        _doc("r1", "reply", issued="24 Nov 2026", status="Replied"),
        _doc("o1", "order", issued="18 Nov 2026", status="Closed"),
        _doc("ao1", "appeal-order", issued="01 Nov 2026", status="Closed"),
    ])
    radar = deadline_radar([case], today=TODAY)
    assert radar["replies_filed"]["d7"] == 1
    assert radar["orders_passed"]["d15"] == 1   # 18 Nov -> 8 days
    assert radar["orders_passed"]["d30"] == 1   # 01 Nov -> 25 days


def test_radar_empty_is_zeroed():
    radar = deadline_radar([], today=TODAY)
    assert set(radar) == {"notices_issued", "replies_due",
                          "replies_filed", "orders_passed"}
    for row in radar.values():
        assert row == {"today": 0, "d7": 0, "d15": 0, "d30": 0}


def test_related_proceedings_same_pan_only():
    a = _case("c1", "AABCP1234F", [_doc("n1", "notice")])
    b = _case("c2", "AABCP1234F", [_doc("n2", "notice")])
    c = _case("c3", "AAACD5678K", [_doc("n3", "notice")])
    related = related_proceedings(a, [a, b, c])
    assert [x.id for x in related] == ["c2"]


def test_related_proceedings_blank_pan_returns_empty():
    a = _case("c1", "", [_doc("n1", "notice")])
    b = _case("c2", "", [_doc("n2", "notice")])
    assert related_proceedings(a, [a, b]) == []

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.eproceedings_model import _case_open_from_meta


def _meta(status="", closed=None, orders=None):
    meta = {"proceeding": {"status": status}}
    if closed is not None:
        meta["closed"] = closed
    if orders is not None:
        meta["orders"] = orders
    return meta


def test_open_statuses_are_open():
    for status in ("Open", "Blocked", "open", "Blocked for non-compliance"):
        assert _case_open_from_meta(_meta(status)) is True, status


def test_known_closed_statuses():
    for status in ("Closed", "Disposed", "Completed", "Concluded",
                   "closed", "DISPOSED"):
        assert _case_open_from_meta(_meta(status)) is False, status


def test_closed_by_officer_is_closed():
    for status in ("Closed by officer", "CLOSED BY OFFICER",
                   " closed   by officer ", "Closed By Officer"):
        assert _case_open_from_meta(_meta(status)) is False, status


def test_extinguished_is_closed():
    for status in ("Extinguished", "EXTINGUISHED", " extinguished "):
        assert _case_open_from_meta(_meta(status)) is False, status


def test_blank_status_is_open():
    assert _case_open_from_meta(_meta("")) is True
    assert _case_open_from_meta({"proceeding": {}}) is True
    assert _case_open_from_meta({}) is True


def test_explicit_closed_flag_wins_even_with_open_status():
    assert _case_open_from_meta(_meta("Open", closed=True)) is False


def test_recorded_orders_close_even_with_open_status():
    orders = [{"files": ["closure_order.pdf"]}]
    assert _case_open_from_meta(_meta("Open", orders=orders)) is False
    # An order entry without files does not force closure.
    assert _case_open_from_meta(_meta("Open", orders=[{"files": []}])) is True

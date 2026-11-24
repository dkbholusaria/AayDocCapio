"""Tests for the litigation calendar helpers (F-26)."""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.litigation.model import (
    EVENT_HEARING,
    EVENT_REPLY,
    UnifiedEvent,
    event_uid,
)
from core.litigation.calendar import (
    events_by_day,
    month_days,
    overdue,
    upcoming,
    visible_events,
)


def _ev(kind, day, state="open", key="k"):
    return UnifiedEvent(
        eid=event_uid("it:c1", kind, key),
        case_uid="it:c1", module="it", kind=kind, title=kind,
        date=day, state=state, urgency="Medium",
    )


def test_visible_hides_replied_ignored_closed_satisfied():
    evs = [
        _ev(EVENT_REPLY, date(2026, 1, 1), "open", "a"),
        _ev(EVENT_REPLY, date(2026, 1, 2), "replied", "b"),
        _ev(EVENT_REPLY, date(2026, 1, 3), "ignored", "c"),
        _ev(EVENT_REPLY, date(2026, 1, 4), "closed", "d"),
        _ev(EVENT_REPLY, date(2026, 1, 5), "satisfied", "e"),
    ]
    assert len(visible_events(evs)) == 1


def test_reply_and_hearing_are_separate_events():
    day = date(2026, 2, 10)
    evs = [
        _ev(EVENT_REPLY, day, "open", "reply"),
        _ev(EVENT_HEARING, day, "open", "hearing"),
    ]
    grouped = events_by_day(evs)
    assert len(grouped[day]) == 2


def test_month_days_pads_to_whole_weeks():
    cells = month_days(2026, 2)
    assert len(cells) % 7 == 0
    assert date(2026, 2, 1) in cells
    assert date(2026, 2, 28) in cells


def test_upcoming_and_overdue():
    today = date(2026, 3, 10)
    evs = [
        _ev(EVENT_REPLY, date(2026, 3, 5), "open", "late"),
        _ev(EVENT_REPLY, date(2026, 3, 12), "open", "soon"),
        _ev(EVENT_REPLY, date(2026, 3, 25), "open", "later"),
        _ev(EVENT_REPLY, date(2026, 3, 12), "ignored", "hidden"),
    ]
    assert [e.date for e in upcoming(evs, today, 7)] == [date(2026, 3, 12)]
    assert [e.date for e in overdue(evs, today)] == [date(2026, 3, 5)]

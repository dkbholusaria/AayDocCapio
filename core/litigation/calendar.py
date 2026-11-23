"""core/litigation/calendar.py — F-26 calendar event helpers.

Turns the shared event list into calendar-friendly structures. The rule that
matters most: a deadline is only shown when its state is *open* — replied,
ignored, closed and satisfied events are hidden (unless the caller asks for
them explicitly).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def visible_events(events) -> list:
    """Events that belong on the calendar (state still open)."""
    return [e for e in events if getattr(e, "visible", True)]


def events_by_day(events, include_hidden: bool = False) -> dict:
    """Group events into ``{date: [event, ...]}``."""
    out: dict = {}
    for event in events:
        if not include_hidden and not getattr(event, "visible", True):
            continue
        day = event.date
        if not isinstance(day, date):
            continue
        out.setdefault(day, []).append(event)
    for bucket in out.values():
        bucket.sort(key=lambda e: (e.kind, e.title))
    return out


def month_bounds(year: int, month: int) -> tuple:
    """Return ``(first_day, last_day)`` for a calendar month."""
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    return first, date(year, month, last_day)


def month_days(year: int, month: int) -> list:
    """List of dates for a month, padded to whole weeks (Mon-first).

    Returns a flat list whose length is a multiple of 7; ``None`` marks a pad
    cell before/after the real month so a 7-column grid renders cleanly.
    """
    first, _ = month_bounds(year, month)
    last_day = calendar.monthrange(year, month)[1]
    lead = first.weekday()  # Monday == 0
    cells: list = [None] * lead
    for day in range(1, last_day + 1):
        cells.append(date(year, month, day))
    while len(cells) % 7:
        cells.append(None)
    return cells


def upcoming(events, today: date, days: int = 7) -> list:
    """Visible events due within ``days`` from ``today`` (inclusive)."""
    horizon = today + timedelta(days=days)
    return sorted(
        (e for e in visible_events(events)
         if isinstance(e.date, date) and today <= e.date <= horizon),
        key=lambda e: (e.date, e.kind),
    )


def overdue(events, today: date) -> list:
    """Visible events whose date is before ``today``."""
    return sorted(
        (e for e in visible_events(events)
         if isinstance(e.date, date) and e.date < today),
        key=lambda e: e.date,
    )


__all__ = [
    "visible_events",
    "events_by_day",
    "month_bounds",
    "month_days",
    "upcoming",
    "overdue",
]

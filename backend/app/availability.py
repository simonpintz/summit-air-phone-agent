"""Mocked appointment-slot generator.

Summit Air doesn't have a real scheduling system wired up for this demo (see
README "what we skipped"). Instead of hardcoding fake-sounding times, this
generates plausible business-hours windows relative to "now", with same-day /
next-available slots surfaced first for urgent cases. A real implementation
would replace this module with a call to ServiceTitan, Housecall Pro, or
whatever the customer's actual dispatch system is.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

BUSINESS_START_HOUR = 8
BUSINESS_END_HOUR = 18
WINDOW_HOURS = 2


def _format_window(start: datetime, end: datetime) -> str:
    day_label = start.strftime("%A, %B %-d")
    start_label = start.strftime("%-I:%M %p").lstrip("0")
    end_label = end.strftime("%-I:%M %p").lstrip("0")
    return f"{day_label}, {start_label}-{end_label}"


def _next_business_windows(after: datetime, count: int) -> List[Tuple[datetime, datetime]]:
    windows: List[Tuple[datetime, datetime]] = []
    cursor = after

    # Round up to the next 2-hour boundary within business hours.
    if cursor.hour < BUSINESS_START_HOUR:
        cursor = cursor.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
    else:
        cursor = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    while len(windows) < count:
        # Skip Sundays (day 6) - Summit Air techs work Mon-Sat.
        if cursor.weekday() == 6 or cursor.hour >= BUSINESS_END_HOUR:
            cursor = (cursor + timedelta(days=1)).replace(hour=BUSINESS_START_HOUR, minute=0)
            continue
        if cursor.hour < BUSINESS_START_HOUR:
            cursor = cursor.replace(hour=BUSINESS_START_HOUR, minute=0)

        window_start = cursor
        window_end = cursor + timedelta(hours=WINDOW_HOURS)
        windows.append((window_start, window_end))
        cursor = window_end

    return windows


def _is_within_business_hours(moment: datetime) -> bool:
    return moment.weekday() != 6 and BUSINESS_START_HOUR <= moment.hour < BUSINESS_END_HOUR


def get_available_slots(urgency_level: str, now: Optional[datetime] = None) -> List[str]:
    """Return human-readable appointment windows, ordered soonest-first.

    Emergency/priority calls get a real "as soon as possible" option that's
    accurate to the current time of day (same-day dispatch during business
    hours, on-call after-hours dispatch otherwise) plus a couple of standard
    windows as backup. Routine calls get the next few standard business-hours
    windows a bit further out so techs on emergency calls aren't
    double-booked in the mock data.
    """
    now = now or datetime.now()

    if urgency_level in ("emergency", "priority"):
        windows = _next_business_windows(now, 2)
        labels = [_format_window(start, end) for start, end in windows]
        if _is_within_business_hours(now):
            asap_label = "As soon as possible today, within the next 2-4 hours"
        else:
            asap_label = (
                "An on-call emergency technician can be there within the next 2-3 hours tonight "
                "(after-hours dispatch)"
            )
        return [asap_label] + labels

    # Routine: start looking a bit further out to keep emergency slots free.
    routine_start = now + timedelta(hours=6)
    windows = _next_business_windows(routine_start, 3)
    return [_format_window(start, end) for start, end in windows]

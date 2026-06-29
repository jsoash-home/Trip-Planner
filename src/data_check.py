"""Detect bookings-data inconsistencies the trip guide should surface.

Currently covers one case: a night with no hotel coverage but with at
least one itinerary item that day — usually a hotel booking that ended a
day early or an un-booked night between two stays. The trip guide
surfaces these as a `.data-check-note` callout so the user can verify
their bookings.
"""
from dataclasses import dataclass
from datetime import date, timedelta
import logging
from typing import Iterable, List

from src.trip_helpers import hotel_for_night

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HotelNightGap:
    day_date: date
    day_number: int
    reason: str


def find_hotel_night_gaps(
    bookings: Iterable,
    itinerary_items: Iterable,
    trip_start: date,
    trip_end: date,
) -> List[HotelNightGap]:
    """Return the list of trip nights with no hotel + at least one non-transit itinerary item.

    A gap satisfies ALL of:
    1. `trip_start <= day_date < trip_end` (nights only, last day excluded)
    2. `hotel_for_night(bookings, day_date)` returns `None`
    3. The day has >=1 itinerary item with `day_date == day_date`
       AND `category != 'transit'`. Transit-only days (in-flight nights,
       ferry crossings) are legitimately unbooked.

    Duck-typed on bookings (passes through to `hotel_for_night`) and on
    itinerary_items (uses `.day_date` and `.category` attributes).
    """
    bookings_list = list(bookings)
    activity_dates = {
        item.day_date
        for item in itinerary_items
        if getattr(item, "category", None) != "transit"
    }

    gaps: List[HotelNightGap] = []
    current = trip_start
    while current < trip_end:
        if current in activity_dates and hotel_for_night(bookings_list, current) is None:
            day_number = (current - trip_start).days + 1
            gaps.append(HotelNightGap(
                day_date=current,
                day_number=day_number,
                reason=(
                    f"Day {day_number} ({current.isoformat()}) has itinerary items "
                    f"but no hotel covers the night."
                ),
            ))
        current += timedelta(days=1)
    return gaps

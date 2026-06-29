"""Tests for `src/data_check.find_hotel_night_gaps`.

Detects nights where:
- the trip's bookings provide no hotel coverage, AND
- the day has at least one itinerary item.

These are usually data holes: a hotel booking that ends a day early, or
an un-booked night between two stays. True transit days (no hotel + no
activity) are NOT gaps.
"""
from datetime import date, datetime
from types import SimpleNamespace

from src.data_check import HotelNightGap, find_hotel_night_gaps


def _hotel(start: date, end: date):
    """A hotel booking covering nights [start, end) per hotel_for_night semantics."""
    return SimpleNamespace(
        type="hotel",
        start_datetime=datetime.combine(start, datetime.min.time()),
        end_datetime=datetime.combine(end, datetime.min.time()),
    )


def _item(day: date):
    return SimpleNamespace(day_date=day)


def test_returns_empty_when_all_nights_covered():
    bookings = [_hotel(date(2026, 8, 14), date(2026, 8, 20))]
    items = [_item(date(2026, 8, 14)), _item(date(2026, 8, 17))]
    gaps = find_hotel_night_gaps(bookings, items, date(2026, 8, 14), date(2026, 8, 20))
    assert gaps == []


def test_returns_empty_when_no_bookings_no_itinerary():
    gaps = find_hotel_night_gaps([], [], date(2026, 8, 14), date(2026, 8, 20))
    assert gaps == []


def test_detects_single_hotel_gap_with_itinerary_on_that_day():
    # Bergen-08-28 scenario: hotel A ends 08-28 morning, but the user clearly
    # had Bergen activity that day (itinerary items present). No hotel covers
    # the night of 08-28. Hotel B picks up on 08-29.
    bookings = [
        _hotel(date(2026, 8, 14), date(2026, 8, 28)),
        _hotel(date(2026, 8, 29), date(2026, 9, 5)),
    ]
    items = [_item(date(2026, 8, 28))]
    gaps = find_hotel_night_gaps(bookings, items, date(2026, 8, 14), date(2026, 9, 5))
    assert len(gaps) == 1
    assert gaps[0].day_date == date(2026, 8, 28)


def test_skips_transit_day_with_no_activity():
    # No hotel covers this night, and no itinerary items either → not a gap.
    # User is in the air / on a ferry / otherwise legitimately unbooked.
    bookings = [
        _hotel(date(2026, 8, 14), date(2026, 8, 20)),
        _hotel(date(2026, 8, 22), date(2026, 8, 28)),
    ]
    items = [_item(date(2026, 8, 15)), _item(date(2026, 8, 23))]
    gaps = find_hotel_night_gaps(bookings, items, date(2026, 8, 14), date(2026, 8, 28))
    # No itinerary item on 08-20 or 08-21 → not gaps
    assert gaps == []


def test_skips_check_out_morning_when_user_actually_left():
    # Hotel ends 08-20 morning; user truly departed that day (no itinerary).
    # Even though hotel_for_night returns None for 08-20, this is expected.
    bookings = [_hotel(date(2026, 8, 14), date(2026, 8, 20))]
    items = [_item(date(2026, 8, 14)), _item(date(2026, 8, 19))]
    gaps = find_hotel_night_gaps(bookings, items, date(2026, 8, 14), date(2026, 8, 21))
    # 08-20 has no hotel and no itinerary → not a gap.
    assert gaps == []


def test_detects_multiple_gaps_returned_in_date_order():
    bookings = [
        _hotel(date(2026, 8, 14), date(2026, 8, 18)),
        _hotel(date(2026, 8, 22), date(2026, 8, 28)),
    ]
    # Two separate gap days, each with an itinerary item.
    items = [_item(date(2026, 8, 19)), _item(date(2026, 8, 20))]
    gaps = find_hotel_night_gaps(bookings, items, date(2026, 8, 14), date(2026, 8, 28))
    assert len(gaps) == 2
    assert gaps[0].day_date == date(2026, 8, 19)
    assert gaps[1].day_date == date(2026, 8, 20)


def test_day_number_correct_relative_to_trip_start():
    # Trip starts 08-14 (day 1). 08-19 is day 6.
    bookings = [_hotel(date(2026, 8, 14), date(2026, 8, 18))]
    items = [_item(date(2026, 8, 19))]
    gaps = find_hotel_night_gaps(bookings, items, date(2026, 8, 14), date(2026, 8, 22))
    assert len(gaps) == 1
    assert gaps[0].day_number == 6


def test_reason_string_mentions_the_day_and_why():
    bookings = [_hotel(date(2026, 8, 14), date(2026, 8, 18))]
    items = [_item(date(2026, 8, 19))]
    gaps = find_hotel_night_gaps(bookings, items, date(2026, 8, 14), date(2026, 8, 22))
    assert "2026-08-19" in gaps[0].reason
    assert "hotel" in gaps[0].reason.lower()


def test_handles_empty_bookings_iterable():
    items = [_item(date(2026, 8, 15))]
    gaps = find_hotel_night_gaps([], items, date(2026, 8, 14), date(2026, 8, 20))
    # Every day with an itinerary item is a gap (no hotel covers any night).
    assert len(gaps) == 1
    assert gaps[0].day_date == date(2026, 8, 15)


def test_inclusive_exclusive_boundary_correct():
    # Last day of trip (trip_end) is NOT a night — user leaves that day.
    # Even if there's an itinerary item AND no hotel covers it, it's not a gap.
    bookings = [_hotel(date(2026, 8, 14), date(2026, 8, 20))]
    items = [_item(date(2026, 8, 20))]  # check-out day itinerary
    gaps = find_hotel_night_gaps(bookings, items, date(2026, 8, 14), date(2026, 8, 20))
    # 08-20 is trip_end (exclusive); not a gap candidate even with itinerary
    assert gaps == []

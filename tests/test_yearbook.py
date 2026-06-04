"""Unit tests for src/yearbook.py."""

from dataclasses import dataclass, field
from datetime import date, time
from typing import Any, List, Optional

from src.yearbook import (
    DayOverview,
    TripStats,
    compute_country_list,
    compute_highlight_items,
    compute_trip_stats,
    days_overview,
    derive_yearbook_view,
    generate_share_token,
    sanitize_public_view,
)


# ─────────────────────────────  fakes  ────────────────────────────────


@dataclass
class FakeTrip:
    start_date: date
    end_date: date
    primary_currency: str = "USD"
    notes: Optional[str] = None
    status: str = "planning"


@dataclass
class FakeBooking:
    id: int = 1
    type: str = "other"
    title: str = ""
    vendor: Optional[str] = None
    confirmation_number: Optional[str] = None
    cost: Optional[float] = None
    currency: str = "USD"
    location: Optional[str] = None
    start_datetime: Any = None
    end_datetime: Any = None
    geocoded_country_code: Optional[str] = None
    geocoded_city: Optional[str] = None


@dataclass
class FakeItem:
    id: int = 1
    day_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    title: str = ""
    category: str = "other"
    location: Optional[str] = None
    notes: Optional[str] = None
    starred: bool = False
    order_within_day: int = 0
    geocoded_country_code: Optional[str] = None
    geocoded_city: Optional[str] = None


# ─────────────────────────────  compute_trip_stats  ───────────────────


def test_compute_trip_stats_basic_shape():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 8))
    stats = compute_trip_stats(trip, [], [])
    assert isinstance(stats, TripStats)
    assert stats.days_away == 8
    assert stats.country_count == 0
    assert stats.city_count == 0
    assert stats.bookings_by_type == {}
    assert stats.spend_by_category == {}
    assert stats.biggest_spend_category is None
    assert stats.starred_count == 0


def test_compute_trip_stats_empty_inputs():
    trip = FakeTrip(date(2026, 1, 1), date(2026, 1, 1))
    stats = compute_trip_stats(trip, None, None)
    assert stats.days_away == 1
    assert stats.bookings_by_type == {}


def test_compute_trip_stats_multi_currency_no_cross_sum():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 5))
    bookings = [
        FakeBooking(type="hotel", cost=500.0, currency="USD"),
        FakeBooking(type="hotel", cost=400.0, currency="EUR"),
    ]
    stats = compute_trip_stats(trip, bookings, [])
    assert stats.spend_by_category == {"hotel": {"USD": 500.0, "EUR": 400.0}}


def test_compute_trip_stats_days_away_one_day_trip():
    trip = FakeTrip(date(2026, 8, 4), date(2026, 8, 4))
    stats = compute_trip_stats(trip, [], [])
    assert stats.days_away == 1


def test_compute_trip_stats_days_away_eight_day_trip():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 8))
    stats = compute_trip_stats(trip, [], [])
    assert stats.days_away == 8


def test_compute_trip_stats_country_dedup():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 8))
    bookings = [
        FakeBooking(geocoded_country_code="NO"),
        FakeBooking(geocoded_country_code="NO"),
        FakeBooking(geocoded_country_code="SE"),
    ]
    items = [FakeItem(geocoded_country_code="NO")]
    stats = compute_trip_stats(trip, bookings, items)
    assert stats.country_count == 2


def test_compute_trip_stats_city_dedup():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 8))
    bookings = [
        FakeBooking(geocoded_city="Oslo", geocoded_country_code="NO"),
        FakeBooking(geocoded_city="Oslo", geocoded_country_code="NO"),
        FakeBooking(geocoded_city="Stockholm", geocoded_country_code="SE"),
    ]
    stats = compute_trip_stats(trip, bookings, [])
    assert stats.city_count == 2


def test_compute_trip_stats_starred_count():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 8))
    items = [
        FakeItem(starred=True),
        FakeItem(starred=False),
        FakeItem(starred=True),
    ]
    stats = compute_trip_stats(trip, [], items)
    assert stats.starred_count == 2


def test_compute_trip_stats_biggest_spend_category_single_currency():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 8), primary_currency="USD")
    bookings = [
        FakeBooking(type="hotel", cost=900.0, currency="USD"),
        FakeBooking(type="flight", cost=500.0, currency="USD"),
        FakeBooking(type="activity", cost=100.0, currency="USD"),
    ]
    stats = compute_trip_stats(trip, bookings, [])
    assert stats.biggest_spend_category == "hotel"


def test_compute_trip_stats_biggest_spend_category_none_when_no_costs():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 8), primary_currency="USD")
    bookings = [FakeBooking(type="hotel", cost=None)]
    stats = compute_trip_stats(trip, bookings, [])
    assert stats.biggest_spend_category is None


# ────────────────────────  compute_highlight_items  ───────────────────


def test_compute_highlight_items_only_starred():
    items = [
        FakeItem(id=1, day_date=date(2026, 8, 1), starred=True, title="A"),
        FakeItem(id=2, day_date=date(2026, 8, 1), starred=False, title="B"),
    ]
    out = compute_highlight_items(items, date(2026, 8, 1))
    flat = [it.id for day in out.values() for it in day]
    assert flat == [1]


def test_compute_highlight_items_grouped_by_day():
    items = [
        FakeItem(id=1, day_date=date(2026, 8, 1), starred=True),
        FakeItem(id=2, day_date=date(2026, 8, 3), starred=True),
        FakeItem(id=3, day_date=date(2026, 8, 1), starred=True),
    ]
    out = compute_highlight_items(items, date(2026, 8, 1))
    assert set(out.keys()) == {1, 3}
    assert {it.id for it in out[1]} == {1, 3}


def test_compute_highlight_items_empty_days_absent():
    items = [FakeItem(id=1, day_date=date(2026, 8, 3), starred=True)]
    out = compute_highlight_items(items, date(2026, 8, 1))
    # Day 2 had no starred items — should not appear as a key
    assert 2 not in out
    assert 3 in out


def test_compute_highlight_items_sorted_within_day_by_time():
    items = [
        FakeItem(id=1, day_date=date(2026, 8, 1), start_time=time(15, 0), starred=True),
        FakeItem(id=2, day_date=date(2026, 8, 1), start_time=time(9, 0), starred=True),
        FakeItem(id=3, day_date=date(2026, 8, 1), start_time=None, starred=True),
    ]
    out = compute_highlight_items(items, date(2026, 8, 1))
    # Untimed first, then 9:00, then 15:00 — sort_within_day order
    assert [it.id for it in out[1]] == [3, 2, 1]


# ─────────────────────────  compute_country_list  ─────────────────────


def test_compute_country_list_dedup():
    bookings = [
        FakeBooking(geocoded_country_code="NO"),
        FakeBooking(geocoded_country_code="NO"),
        FakeBooking(geocoded_country_code="SE"),
    ]
    assert compute_country_list(bookings, []) == ["NO", "SE"]


def test_compute_country_list_first_appearance_order():
    bookings = [
        FakeBooking(geocoded_country_code="SE"),
        FakeBooking(geocoded_country_code="NO"),
    ]
    items = [FakeItem(geocoded_country_code="DK")]
    assert compute_country_list(bookings, items) == ["SE", "NO", "DK"]


def test_compute_country_list_skips_null_country_iso():
    bookings = [
        FakeBooking(geocoded_country_code=None),
        FakeBooking(geocoded_country_code="NO"),
    ]
    assert compute_country_list(bookings, []) == ["NO"]


# ──────────────────────────  derive_yearbook_view  ────────────────────


def test_derive_yearbook_view_planning_hidden():
    trip = FakeTrip(date(2027, 1, 1), date(2027, 1, 5))
    assert derive_yearbook_view(trip, date(2026, 6, 1)) == "hidden"


def test_derive_yearbook_view_upcoming_hidden():
    # "upcoming" means future trip — derive_status returns "planning" for both.
    trip = FakeTrip(date(2026, 12, 1), date(2026, 12, 5))
    assert derive_yearbook_view(trip, date(2026, 6, 1)) == "hidden"


def test_derive_yearbook_view_in_progress_preview():
    trip = FakeTrip(date(2026, 6, 1), date(2026, 6, 8))
    assert derive_yearbook_view(trip, date(2026, 6, 3)) == "preview"


def test_derive_yearbook_view_completed_final():
    trip = FakeTrip(date(2026, 5, 1), date(2026, 5, 8))
    assert derive_yearbook_view(trip, date(2026, 6, 1)) == "final"


# ──────────────────────────  sanitize_public_view  ────────────────────


def _vm(**overrides):
    """Helper to build a minimal view_model dict for sanitize tests."""
    base = {
        "trip": FakeTrip(date(2026, 5, 1), date(2026, 5, 5)),
        "stats": TripStats(
            days_away=5,
            country_count=1,
            city_count=1,
            spend_by_category={"hotel": {"USD": 500.0}},
            biggest_spend_category="hotel",
            starred_count=2,
        ),
    }
    base.update(overrides)
    return base


def test_sanitize_public_view_always_strips_confirmation_number():
    vm = _vm(bookings=[FakeBooking(confirmation_number="ABC123", title="Hotel A")])
    out = sanitize_public_view(vm, show_notes=True, show_spend=True)
    assert "confirmation_number" not in out["bookings"][0]


def test_sanitize_public_view_always_strips_booking_cost():
    vm = _vm(bookings=[FakeBooking(cost=900.0, currency="USD", title="Flight")])
    out = sanitize_public_view(vm, show_notes=True, show_spend=True)
    assert "cost" not in out["bookings"][0]
    assert "currency" not in out["bookings"][0]


def test_sanitize_public_view_strips_notes_when_show_notes_false():
    out = sanitize_public_view(_vm(), show_notes=False, show_spend=True)
    assert out["show_notes"] is False


def test_sanitize_public_view_keeps_notes_when_show_notes_true():
    out = sanitize_public_view(_vm(), show_notes=True, show_spend=True)
    assert out["show_notes"] is True


def test_sanitize_public_view_strips_spend_when_show_spend_false():
    out = sanitize_public_view(_vm(), show_notes=True, show_spend=False)
    assert out["show_spend"] is False
    assert out["stats"].spend_by_category == {}
    assert out["stats"].biggest_spend_category is None


def test_sanitize_public_view_keeps_spend_when_show_spend_true():
    out = sanitize_public_view(_vm(), show_notes=True, show_spend=True)
    assert out["stats"].spend_by_category == {"hotel": {"USD": 500.0}}
    assert out["stats"].biggest_spend_category == "hotel"


# ───────────────────────────  generate_share_token  ───────────────────


def test_generate_share_token_is_url_safe_32_chars():
    tok = generate_share_token()
    # token_urlsafe(24) → 32 chars, alphabet [A-Za-z0-9_-]
    assert len(tok) == 32
    assert all(c.isalnum() or c in "-_" for c in tok)


def test_generate_share_token_returns_unique_values():
    tokens = {generate_share_token() for _ in range(50)}
    assert len(tokens) == 50


# ─────────────────────────────  days_overview  ────────────────────────


def test_days_overview_returns_one_per_day_in_range():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 5))
    out = days_overview(trip, [])
    assert len(out) == 5
    assert all(isinstance(d, DayOverview) for d in out)
    assert [d.number for d in out] == [1, 2, 3, 4, 5]
    assert out[0].date == date(2026, 8, 1)
    assert out[-1].date == date(2026, 8, 5)


def test_days_overview_empty_day_has_empty_items_list():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 3))
    items = [FakeItem(id=1, day_date=date(2026, 8, 2))]
    out = days_overview(trip, items)
    assert out[0].items == []
    assert len(out[1].items) == 1
    assert out[2].items == []


def test_days_overview_groups_items_by_day_date():
    trip = FakeTrip(date(2026, 8, 1), date(2026, 8, 2))
    items = [
        FakeItem(id=1, day_date=date(2026, 8, 1)),
        FakeItem(id=2, day_date=date(2026, 8, 1)),
        FakeItem(id=3, day_date=date(2026, 8, 2)),
    ]
    out = days_overview(trip, items)
    assert {it.id for it in out[0].items} == {1, 2}
    assert {it.id for it in out[1].items} == {3}

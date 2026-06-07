"""Unit tests for src/yearbook.py."""

from dataclasses import dataclass, field
from datetime import date, time
from typing import Any, List, Optional

from src.yearbook import (
    DayOverview,
    LifetimeStats,
    OnThisDayEntry,
    TripStats,
    YearBar,
    compute_country_list,
    compute_highlight_items,
    compute_lifetime_stats,
    compute_trip_stats,
    compute_trips_per_year,
    days_overview,
    derive_yearbook_view,
    generate_share_token,
    on_this_day,
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
    id: int = 1
    bookings: list = field(default_factory=list)
    itinerary_items: list = field(default_factory=list)


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


# ─────────────────────────────  on_this_day  ──────────────────────────


def test_on_this_day_empty_trips_returns_empty():
    assert on_this_day([], date(2026, 6, 6)) == []


def test_on_this_day_past_trip_overlap_returns_entry():
    # Trip ran Jun 1–10, 2025. Today is Jun 6, 2026 → matches Jun 6, 2025.
    trip = FakeTrip(date(2025, 6, 1), date(2025, 6, 10), id=1)
    out = on_this_day([trip], date(2026, 6, 6))
    assert len(out) == 1
    entry = out[0]
    assert isinstance(entry, OnThisDayEntry)
    assert entry.trip is trip
    assert entry.matched_date == date(2025, 6, 6)
    assert entry.day_number == 6  # Jun 6 is day 6 of a trip starting Jun 1
    assert entry.years_ago == 1


def test_on_this_day_past_trip_no_overlap_returns_empty():
    # Trip ran Jul 1–10, 2025. Today is Jun 6, 2026 → no overlap.
    trip = FakeTrip(date(2025, 7, 1), date(2025, 7, 10))
    assert on_this_day([trip], date(2026, 6, 6)) == []


def test_on_this_day_current_year_trip_excluded():
    # Trip in same year as today must not appear, even if range covers today.
    trip = FakeTrip(date(2026, 6, 1), date(2026, 6, 10))
    assert on_this_day([trip], date(2026, 6, 6)) == []


def test_on_this_day_future_trip_excluded():
    # Trip starts after today's year — never qualifies.
    trip = FakeTrip(date(2027, 6, 1), date(2027, 6, 10))
    assert on_this_day([trip], date(2026, 6, 6)) == []


def test_on_this_day_feb_29_today_matches_feb_28_in_non_leap_year():
    # Today is Feb 29, 2028 (leap year). Last year 2027 isn't leap →
    # candidate match date becomes Feb 28, 2027.
    trip = FakeTrip(date(2027, 2, 20), date(2027, 3, 5))
    out = on_this_day([trip], date(2028, 2, 29))
    assert len(out) == 1
    assert out[0].matched_date == date(2027, 2, 28)
    assert out[0].years_ago == 1


def test_on_this_day_multiple_matches_sorted_most_recent_first():
    # Three past trips, all covering Jun 6 in their respective years.
    trip_2023 = FakeTrip(date(2023, 6, 1), date(2023, 6, 10), id=23)
    trip_2024 = FakeTrip(date(2024, 6, 1), date(2024, 6, 10), id=24)
    trip_2025 = FakeTrip(date(2025, 6, 1), date(2025, 6, 10), id=25)
    out = on_this_day([trip_2023, trip_2025, trip_2024], date(2026, 6, 6))
    assert [e.trip.id for e in out] == [25, 24, 23]
    assert [e.years_ago for e in out] == [1, 2, 3]


def test_on_this_day_years_ago_computed_correctly():
    # Trip from 5 years ago.
    trip = FakeTrip(date(2021, 6, 1), date(2021, 6, 10))
    out = on_this_day([trip], date(2026, 6, 6))
    assert len(out) == 1
    assert out[0].years_ago == 5
    assert out[0].matched_date == date(2021, 6, 6)


def test_on_this_day_year_boundary_trip_matches_both_calendar_years():
    # Trip spans Dec 28, 2024 → Jan 5, 2025. Today is Jan 2, 2026.
    # Candidate match Jan 2, 2025 falls inside the range → entry for 2025.
    # Candidate match Jan 2, 2024 (years_ago=2) is NOT inside the range
    # (range starts Dec 28, 2024), so we expect exactly one entry.
    trip = FakeTrip(date(2024, 12, 28), date(2025, 1, 5))
    out = on_this_day([trip], date(2026, 1, 2))
    assert len(out) == 1
    assert out[0].matched_date == date(2025, 1, 2)
    assert out[0].years_ago == 1
    # Day number: Jan 2, 2025 is the 6th day of a trip starting Dec 28, 2024.
    assert out[0].day_number == 6


# ───────────────────────  compute_lifetime_stats  ─────────────────────


def test_lifetime_stats_empty_trips_returns_zeros():
    stats = compute_lifetime_stats([])
    assert isinstance(stats, LifetimeStats)
    assert stats.trip_count == 0
    assert stats.country_count == 0
    assert stats.city_count == 0
    assert stats.days_away == 0
    assert stats.flight_count == 0
    assert stats.longest_trip_days == 0


def test_lifetime_stats_single_trip_counts():
    trip = FakeTrip(
        date(2024, 8, 1), date(2024, 8, 8),
        bookings=[
            FakeBooking(type="flight", geocoded_country_code="FR",
                        geocoded_city="Paris"),
            FakeBooking(type="hotel", geocoded_country_code="FR",
                        geocoded_city="Paris"),
        ],
    )
    stats = compute_lifetime_stats([trip])
    assert stats.trip_count == 1
    assert stats.country_count == 1
    assert stats.city_count == 1
    assert stats.days_away == 8
    assert stats.flight_count == 1
    assert stats.longest_trip_days == 8


def test_lifetime_stats_days_away_sums_across_trips():
    t1 = FakeTrip(date(2024, 8, 1), date(2024, 8, 8))   # 8 days
    t2 = FakeTrip(date(2025, 3, 1), date(2025, 3, 10))  # 10 days
    stats = compute_lifetime_stats([t1, t2])
    assert stats.days_away == 18
    assert stats.trip_count == 2


def test_lifetime_stats_country_dedup_across_trips():
    t1 = FakeTrip(
        date(2024, 8, 1), date(2024, 8, 8),
        bookings=[FakeBooking(geocoded_country_code="FR")],
    )
    t2 = FakeTrip(
        date(2025, 3, 1), date(2025, 3, 10),
        bookings=[
            FakeBooking(geocoded_country_code="FR"),
            FakeBooking(geocoded_country_code="JP"),
        ],
    )
    stats = compute_lifetime_stats([t1, t2])
    assert stats.country_count == 2


def test_lifetime_stats_city_dedup_across_trips():
    t1 = FakeTrip(
        date(2024, 8, 1), date(2024, 8, 8),
        bookings=[FakeBooking(geocoded_country_code="FR",
                              geocoded_city="Paris")],
    )
    t2 = FakeTrip(
        date(2025, 3, 1), date(2025, 3, 10),
        bookings=[FakeBooking(geocoded_country_code="FR",
                              geocoded_city="Paris")],
    )
    stats = compute_lifetime_stats([t1, t2])
    assert stats.city_count == 1


def test_lifetime_stats_same_city_different_country_counts_twice():
    t1 = FakeTrip(
        date(2024, 8, 1), date(2024, 8, 8),
        bookings=[FakeBooking(geocoded_country_code="FR",
                              geocoded_city="Paris")],
    )
    t2 = FakeTrip(
        date(2025, 3, 1), date(2025, 3, 10),
        bookings=[FakeBooking(geocoded_country_code="US",
                              geocoded_city="Paris")],
    )
    stats = compute_lifetime_stats([t1, t2])
    assert stats.country_count == 2
    assert stats.city_count == 2


def test_lifetime_stats_flight_count_only_counts_flights():
    trip = FakeTrip(
        date(2024, 8, 1), date(2024, 8, 8),
        bookings=[
            FakeBooking(type="flight"),
            FakeBooking(type="flight"),
            FakeBooking(type="hotel"),
            FakeBooking(type="activity"),
            FakeBooking(type="other"),
        ],
    )
    stats = compute_lifetime_stats([trip])
    assert stats.flight_count == 2


def test_lifetime_stats_longest_trip_days_picks_max():
    t1 = FakeTrip(date(2024, 8, 1), date(2024, 8, 8))    # 8 days
    t2 = FakeTrip(date(2025, 3, 1), date(2025, 3, 21))   # 21 days
    t3 = FakeTrip(date(2026, 1, 1), date(2026, 1, 5))    # 5 days
    stats = compute_lifetime_stats([t1, t2, t3])
    assert stats.longest_trip_days == 21


def test_lifetime_stats_trip_with_no_rows_counts_for_days_and_trip_count():
    trip = FakeTrip(date(2024, 8, 1), date(2024, 8, 8))  # no bookings/items
    stats = compute_lifetime_stats([trip])
    assert stats.trip_count == 1
    assert stats.days_away == 8
    assert stats.longest_trip_days == 8
    assert stats.country_count == 0
    assert stats.city_count == 0
    assert stats.flight_count == 0


# ──────────────────────  compute_trips_per_year  ──────────────────────


def test_trips_per_year_empty_trips_returns_empty_list():
    assert compute_trips_per_year([]) == []


def test_trips_per_year_single_year():
    t1 = FakeTrip(date(2024, 8, 1), date(2024, 8, 8))
    t2 = FakeTrip(date(2024, 3, 1), date(2024, 3, 5))
    bars = compute_trips_per_year([t1, t2])
    assert len(bars) == 1
    assert bars[0] == YearBar(year=2024, trip_count=2)


def test_trips_per_year_multiple_years_fills_gaps_with_zero():
    t1 = FakeTrip(date(2018, 8, 1), date(2018, 8, 8))
    t2 = FakeTrip(date(2020, 3, 1), date(2020, 3, 5))
    bars = compute_trips_per_year([t1, t2])
    assert [b.year for b in bars] == [2018, 2019, 2020]
    assert [b.trip_count for b in bars] == [1, 0, 1]


def test_trips_per_year_keyed_by_start_date_year():
    # Trip straddles Dec 28 2024 → Jan 5 2025: counts for 2024 only.
    trip = FakeTrip(date(2024, 12, 28), date(2025, 1, 5))
    bars = compute_trips_per_year([trip])
    assert bars == [YearBar(year=2024, trip_count=1)]


def test_trips_per_year_two_trips_in_same_year():
    t1 = FakeTrip(date(2024, 3, 1), date(2024, 3, 5))
    t2 = FakeTrip(date(2024, 9, 1), date(2024, 9, 7))
    bars = compute_trips_per_year([t1, t2])
    assert bars == [YearBar(year=2024, trip_count=2)]

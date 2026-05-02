"""Unit tests for src/itinerary.py."""

from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

from src.itinerary import (
    ITINERARY_CATEGORIES,
    ITINERARY_CATEGORY_CODES,
    category_css,
    category_emoji,
    category_label,
    format_time_range,
    group_items_by_day,
    itinerary_form_values,
    parse_itinerary_form,
    sort_within_day,
)


@dataclass
class FakeItem:
    """Stand-in for ItineraryItem — same field names, no DB needed."""

    id: int
    title: str
    day_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    category: str = "other"
    location: Optional[str] = None
    notes: Optional[str] = None
    order_within_day: int = 0


# ─────────────────────────────  metadata  ──────────────────────────────────


def test_categories_codes_set_matches_tuple():
    assert ITINERARY_CATEGORY_CODES == frozenset(c for c, _, _, _ in ITINERARY_CATEGORIES)


def test_category_helpers_known_and_unknown():
    assert category_label("meal") == "Meal"
    assert category_label("zzz") == "zzz"
    assert category_emoji("transit") == "🚆"
    assert category_emoji("zzz") == "📌"
    assert category_css("break") == "is-break"
    assert category_css("zzz") == "is-other"


# ─────────────────────────────  parse_itinerary_form  ──────────────────────


_TRIP_START = date(2026, 6, 1)
_TRIP_END = date(2026, 6, 7)


def _valid_form(**overrides):
    base = {
        "title": "Colosseum tour",
        "category": "sightseeing",
        "day_date": "2026-06-02",
        "start_time": "09:30",
        "end_time": "11:45",
        "location": "Piazza del Colosseo",
        "notes": "skip-the-line tickets",
    }
    base.update(overrides)
    return base


def test_parse_itinerary_form_valid_no_errors():
    data, errors = parse_itinerary_form(_valid_form(), _TRIP_START, _TRIP_END)
    assert errors == []
    assert data["title"] == "Colosseum tour"
    assert data["category"] == "sightseeing"
    assert data["day_date"] == date(2026, 6, 2)
    assert data["start_time"] == time(9, 30)
    assert data["end_time"] == time(11, 45)


def test_parse_itinerary_form_missing_title_errors():
    _, errors = parse_itinerary_form(_valid_form(title=""), _TRIP_START, _TRIP_END)
    assert any("Title" in e for e in errors)


def test_parse_itinerary_form_missing_day_errors():
    _, errors = parse_itinerary_form(_valid_form(day_date=""), _TRIP_START, _TRIP_END)
    assert any("Day" in e for e in errors)


def test_parse_itinerary_form_invalid_day_errors():
    _, errors = parse_itinerary_form(_valid_form(day_date="not-a-date"), _TRIP_START, _TRIP_END)
    assert any("Day" in e and "valid" in e for e in errors)


def test_parse_itinerary_form_day_before_trip_start_errors():
    _, errors = parse_itinerary_form(
        _valid_form(day_date="2026-05-30"), _TRIP_START, _TRIP_END
    )
    assert any("between" in e for e in errors)


def test_parse_itinerary_form_day_after_trip_end_errors():
    _, errors = parse_itinerary_form(
        _valid_form(day_date="2026-06-08"), _TRIP_START, _TRIP_END
    )
    assert any("between" in e for e in errors)


def test_parse_itinerary_form_unknown_category_errors_and_falls_back():
    data, errors = parse_itinerary_form(_valid_form(category="zzz"), _TRIP_START, _TRIP_END)
    assert any("Category" in e for e in errors)
    assert data["category"] == "other"


def test_parse_itinerary_form_blank_times_are_ok():
    data, errors = parse_itinerary_form(
        _valid_form(start_time="", end_time=""), _TRIP_START, _TRIP_END
    )
    assert errors == []
    assert data["start_time"] is None
    assert data["end_time"] is None


def test_parse_itinerary_form_invalid_time_errors():
    _, errors = parse_itinerary_form(
        _valid_form(start_time="25:99"), _TRIP_START, _TRIP_END
    )
    assert any("Start time" in e for e in errors)


def test_parse_itinerary_form_end_before_start_errors():
    _, errors = parse_itinerary_form(
        _valid_form(start_time="14:00", end_time="13:00"),
        _TRIP_START, _TRIP_END,
    )
    assert any("on or after" in e for e in errors)


def test_parse_itinerary_form_blank_optional_fields_become_none():
    data, errors = parse_itinerary_form(
        _valid_form(location="", notes=""), _TRIP_START, _TRIP_END
    )
    assert errors == []
    assert data["location"] is None
    assert data["notes"] is None


def test_parse_itinerary_form_strips_whitespace():
    data, errors = parse_itinerary_form(
        _valid_form(title="  Colosseum  "), _TRIP_START, _TRIP_END
    )
    assert errors == []
    assert data["title"] == "Colosseum"


# ─────────────────────────────  itinerary_form_values  ─────────────────────


def test_itinerary_form_values_none_returns_empty_dict():
    assert itinerary_form_values(None) == {}


def test_itinerary_form_values_renders_iso_date_and_24h_time():
    item = FakeItem(
        id=1,
        title="Brunch",
        category="meal",
        day_date=date(2026, 6, 3),
        start_time=time(11, 0),
        end_time=time(12, 30),
    )
    out = itinerary_form_values(item)
    assert out["day_date"] == "2026-06-03"
    assert out["start_time"] == "11:00"
    assert out["end_time"] == "12:30"
    assert out["category"] == "meal"


def test_itinerary_form_values_blank_when_times_missing():
    item = FakeItem(id=1, title="Free walk", day_date=date(2026, 6, 1))
    out = itinerary_form_values(item)
    assert out["start_time"] == ""
    assert out["end_time"] == ""


# ─────────────────────────────  sort_within_day  ───────────────────────────


def test_sort_within_day_untimed_first_then_timed():
    a = FakeItem(id=1, title="A", start_time=time(9, 0))
    b = FakeItem(id=2, title="B", start_time=None)
    c = FakeItem(id=3, title="C", start_time=time(13, 0))
    out = sort_within_day([a, b, c])
    assert [it.title for it in out] == ["B", "A", "C"]


def test_sort_within_day_uses_order_within_day_for_untimed():
    a = FakeItem(id=1, title="A", start_time=None, order_within_day=2)
    b = FakeItem(id=2, title="B", start_time=None, order_within_day=1)
    out = sort_within_day([a, b])
    assert [it.title for it in out] == ["B", "A"]


def test_sort_within_day_uses_id_as_stable_tiebreaker():
    a = FakeItem(id=2, title="A", start_time=time(9, 0))
    b = FakeItem(id=1, title="B", start_time=time(9, 0))
    out = sort_within_day([a, b])
    assert [it.title for it in out] == ["B", "A"]


def test_sort_within_day_empty_input():
    assert sort_within_day([]) == []


# ─────────────────────────────  group_items_by_day  ────────────────────────


def test_group_items_by_day_emits_every_day_even_empty():
    items = [
        FakeItem(id=1, title="A", day_date=date(2026, 6, 1), start_time=time(9, 0)),
        FakeItem(id=2, title="B", day_date=date(2026, 6, 3), start_time=None),
    ]
    out = group_items_by_day(items, date(2026, 6, 1), date(2026, 6, 3))
    days = [d for d, _ in out]
    assert days == [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)]
    # Day 2 has no items but is still present
    assert out[1][1] == []


def test_group_items_by_day_drops_items_outside_range():
    items = [
        FakeItem(id=1, title="In",   day_date=date(2026, 6, 2), start_time=time(9, 0)),
        FakeItem(id=2, title="Out1", day_date=date(2026, 5, 31)),
        FakeItem(id=3, title="Out2", day_date=date(2026, 6, 5)),
    ]
    out = group_items_by_day(items, date(2026, 6, 1), date(2026, 6, 3))
    titles_for_day_2 = [it.title for it in out[1][1]]
    assert titles_for_day_2 == ["In"]
    # Out1 and Out2 don't appear anywhere
    all_titles = [it.title for _, items in out for it in items]
    assert all_titles == ["In"]


def test_group_items_by_day_orders_within_day_correctly():
    d = date(2026, 6, 1)
    items = [
        FakeItem(id=1, title="Late",   day_date=d, start_time=time(15, 0)),
        FakeItem(id=2, title="Anytime", day_date=d, start_time=None),
        FakeItem(id=3, title="Early",  day_date=d, start_time=time(9, 0)),
    ]
    out = group_items_by_day(items, d, d)
    assert [it.title for it in out[0][1]] == ["Anytime", "Early", "Late"]


def test_group_items_by_day_handles_empty_items():
    out = group_items_by_day([], date(2026, 6, 1), date(2026, 6, 2))
    assert len(out) == 2
    assert all(items == [] for _, items in out)


def test_group_items_by_day_returns_empty_when_dates_inverted():
    out = group_items_by_day([], date(2026, 6, 5), date(2026, 6, 1))
    assert out == []


# ─────────────────────────────  format_time_range  ─────────────────────────


def test_format_time_range_both_present():
    assert format_time_range(time(9, 30), time(11, 45)) == "9:30 AM – 11:45 AM"


def test_format_time_range_start_only():
    assert format_time_range(time(9, 30), None) == "9:30 AM"


def test_format_time_range_end_only():
    assert format_time_range(None, time(17, 0)) == "→ 5:00 PM"


def test_format_time_range_neither_returns_anytime():
    assert format_time_range(None, None) == "Anytime"


def test_format_time_range_strips_zero_padded_hour():
    out = format_time_range(time(9, 30), time(11, 45))
    assert "09:30" not in out
    assert "9:30 AM" in out

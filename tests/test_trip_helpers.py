"""Unit tests for src/trip_helpers.py."""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.trip_helpers import (
    countdown_label,
    days_remaining,
    days_until,
    derive_status,
    emoji_theme,
    group_trips_by_state,
    is_valid_status,
    parse_trip_form,
    progress_fraction,
    status_label,
    trip_form_values,
)


@dataclass
class FakeTrip:
    """Tiny stand-in for a SQLAlchemy Trip — same field names, no DB needed."""

    id: int
    start_date: Optional[date]
    end_date: Optional[date]


# ─────────────────────────────  derive_status  ─────────────────────────────


def test_derive_status_before_trip_returns_planning():
    assert derive_status(date(2026, 6, 1), date(2026, 6, 7), date(2026, 5, 1)) == "planning"


def test_derive_status_during_trip_returns_in_progress():
    assert derive_status(date(2026, 6, 1), date(2026, 6, 7), date(2026, 6, 4)) == "in_progress"


def test_derive_status_first_day_is_in_progress():
    assert derive_status(date(2026, 6, 1), date(2026, 6, 7), date(2026, 6, 1)) == "in_progress"


def test_derive_status_last_day_is_in_progress():
    assert derive_status(date(2026, 6, 1), date(2026, 6, 7), date(2026, 6, 7)) == "in_progress"


def test_derive_status_after_trip_returns_completed():
    assert derive_status(date(2026, 6, 1), date(2026, 6, 7), date(2026, 7, 1)) == "completed"


def test_derive_status_handles_inverted_dates_without_crashing():
    # Defensive — a corrupt DB row should not crash the dashboard.
    assert derive_status(date(2026, 6, 7), date(2026, 6, 1), date(2026, 6, 4)) == "planning"


# ─────────────────────────────  days_until / days_remaining  ─────────────────


def test_days_until_future():
    assert days_until(date(2026, 6, 1), date(2026, 5, 22)) == 10


def test_days_until_past_is_negative():
    assert days_until(date(2026, 5, 1), date(2026, 5, 22)) == -21


def test_days_remaining_future():
    assert days_remaining(date(2026, 6, 7), date(2026, 6, 1)) == 6


def test_days_remaining_past_is_negative():
    assert days_remaining(date(2026, 5, 1), date(2026, 6, 1)) == -31


# ─────────────────────────────  group_trips_by_state  ─────────────────────


def test_group_trips_splits_into_three_buckets():
    today = date(2026, 6, 15)
    trips = [
        FakeTrip(id=1, start_date=date(2026, 6, 10), end_date=date(2026, 6, 20)),  # active
        FakeTrip(id=2, start_date=date(2026, 7, 1), end_date=date(2026, 7, 10)),   # upcoming
        FakeTrip(id=3, start_date=date(2026, 5, 1), end_date=date(2026, 5, 10)),   # past
    ]
    out = group_trips_by_state(trips, today)
    assert [t.id for t in out["active"]] == [1]
    assert [t.id for t in out["upcoming"]] == [2]
    assert [t.id for t in out["past"]] == [3]


def test_group_trips_sorts_upcoming_by_start_ascending():
    today = date(2026, 6, 1)
    trips = [
        FakeTrip(id=1, start_date=date(2026, 8, 1), end_date=date(2026, 8, 5)),
        FakeTrip(id=2, start_date=date(2026, 7, 1), end_date=date(2026, 7, 5)),
    ]
    out = group_trips_by_state(trips, today)
    assert [t.id for t in out["upcoming"]] == [2, 1]


def test_group_trips_sorts_past_most_recent_first():
    today = date(2026, 6, 1)
    trips = [
        FakeTrip(id=1, start_date=date(2026, 1, 1), end_date=date(2026, 1, 10)),
        FakeTrip(id=2, start_date=date(2026, 3, 1), end_date=date(2026, 3, 10)),
    ]
    out = group_trips_by_state(trips, today)
    assert [t.id for t in out["past"]] == [2, 1]


def test_group_trips_drops_rows_with_null_dates():
    today = date(2026, 6, 1)
    trips = [
        FakeTrip(id=1, start_date=None, end_date=date(2026, 7, 1)),
        FakeTrip(id=2, start_date=date(2026, 7, 1), end_date=None),
        FakeTrip(id=3, start_date=date(2026, 7, 1), end_date=date(2026, 7, 5)),
    ]
    out = group_trips_by_state(trips, today)
    assert [t.id for t in out["upcoming"]] == [3]


def test_group_trips_drops_rows_with_inverted_dates():
    today = date(2026, 6, 1)
    trips = [
        FakeTrip(id=1, start_date=date(2026, 7, 5), end_date=date(2026, 7, 1)),  # corrupt
        FakeTrip(id=2, start_date=date(2026, 7, 1), end_date=date(2026, 7, 5)),
    ]
    out = group_trips_by_state(trips, today)
    assert [t.id for t in out["upcoming"]] == [2]


# ─────────────────────────────  countdown_label  ──────────────────────────


def test_countdown_label_far_future():
    assert countdown_label(date(2026, 7, 1), date(2026, 7, 7), date(2026, 6, 8)) == "23 days to go"


def test_countdown_label_tomorrow():
    assert countdown_label(date(2026, 7, 1), date(2026, 7, 7), date(2026, 6, 30)) == "Tomorrow!"


def test_countdown_label_first_day():
    assert countdown_label(date(2026, 7, 1), date(2026, 7, 7), date(2026, 7, 1)) == "Today!"


def test_countdown_label_last_day():
    assert countdown_label(date(2026, 7, 1), date(2026, 7, 7), date(2026, 7, 7)) == "Last day"


def test_countdown_label_mid_trip():
    assert countdown_label(date(2026, 7, 1), date(2026, 7, 7), date(2026, 7, 3)) == "On day 3 of 7"


def test_countdown_label_yesterday_ended():
    assert countdown_label(date(2026, 6, 1), date(2026, 6, 7), date(2026, 6, 8)) == "Ended yesterday"


def test_countdown_label_recent_past():
    assert countdown_label(date(2026, 6, 1), date(2026, 6, 7), date(2026, 6, 12)) == "Ended 5 days ago"


def test_countdown_label_long_past_uses_month_format():
    assert (
        countdown_label(date(2026, 1, 1), date(2026, 1, 7), date(2026, 4, 30))
        == "Ended Jan 07, 2026"
    )


# ─────────────────────────────  is_valid_status  ──────────────────────────


def test_is_valid_status_accepts_known_values():
    assert is_valid_status("planning")
    assert is_valid_status("booked")
    assert is_valid_status("in_progress")
    assert is_valid_status("completed")


def test_is_valid_status_rejects_other_strings():
    assert not is_valid_status("active")
    assert not is_valid_status("")
    assert not is_valid_status(None)


# ─────────────────────────────  status_label  ──────────────────────────────


def test_status_label_known():
    assert status_label("planning") == "Planning"
    assert status_label("in_progress") == "On the trip"
    assert status_label("completed") == "Completed"
    assert status_label("booked") == "Booked"


def test_status_label_unknown_passes_through():
    assert status_label("anything") == "anything"


# ─────────────────────────────  parse_trip_form  ───────────────────────────


def _valid_form_dict(**overrides):
    base = {
        "name": "Italy 2026",
        "destination": "Rome, Florence",
        "cover_emoji": "🇮🇹",
        "primary_currency": "EUR",
        "notes": "passport renewed",
        "start_date": "2026-06-01",
        "end_date": "2026-06-10",
    }
    base.update(overrides)
    return base


def test_parse_trip_form_valid_no_errors():
    data, errors = parse_trip_form(_valid_form_dict())
    assert errors == []
    assert data["name"] == "Italy 2026"
    assert data["start_date"] == date(2026, 6, 1)
    assert data["end_date"] == date(2026, 6, 10)
    assert data["primary_currency"] == "EUR"


def test_parse_trip_form_missing_name_errors():
    _, errors = parse_trip_form(_valid_form_dict(name=""))
    assert any("name" in e.lower() for e in errors)


def test_parse_trip_form_strips_whitespace():
    data, errors = parse_trip_form(_valid_form_dict(name="  Italy 2026  "))
    assert errors == []
    assert data["name"] == "Italy 2026"


def test_parse_trip_form_uppercases_currency():
    data, errors = parse_trip_form(_valid_form_dict(primary_currency="usd"))
    assert errors == []
    assert data["primary_currency"] == "USD"


def test_parse_trip_form_empty_optional_fields_become_none():
    data, errors = parse_trip_form(_valid_form_dict(destination="", notes="", cover_emoji=""))
    assert errors == []
    assert data["destination"] is None
    assert data["notes"] is None
    assert data["cover_emoji"] is None


def test_parse_trip_form_missing_dates_errors():
    _, errors = parse_trip_form(_valid_form_dict(start_date="", end_date=""))
    assert any("Start date" in e for e in errors)
    assert any("End date" in e for e in errors)


def test_parse_trip_form_invalid_date_string_errors():
    _, errors = parse_trip_form(_valid_form_dict(start_date="not-a-date"))
    assert any("Start date" in e and "valid" in e for e in errors)


def test_parse_trip_form_start_after_end_errors():
    _, errors = parse_trip_form(
        _valid_form_dict(start_date="2026-06-10", end_date="2026-06-01")
    )
    assert any("on or before" in e for e in errors)


def test_parse_trip_form_blank_currency_defaults_to_usd():
    data, errors = parse_trip_form(_valid_form_dict(primary_currency=""))
    assert errors == []
    assert data["primary_currency"] == "USD"


# ─────────────────────────────  trip_form_values  ──────────────────────────


def test_trip_form_values_none_returns_empty_dict():
    assert trip_form_values(None) == {}


def test_trip_form_values_renders_dates_iso():
    @dataclass
    class T:
        name: str
        destination: Optional[str]
        cover_emoji: Optional[str]
        start_date: date
        end_date: date
        primary_currency: str
        notes: Optional[str]

    trip = T(
        name="Italy",
        destination="Rome",
        cover_emoji="🇮🇹",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 10),
        primary_currency="EUR",
        notes="hello",
    )
    out = trip_form_values(trip)
    assert out["start_date"] == "2026-06-01"
    assert out["end_date"] == "2026-06-10"
    assert out["name"] == "Italy"
    assert out["primary_currency"] == "EUR"


def test_trip_form_values_handles_null_optional_fields():
    @dataclass
    class T:
        name: str
        destination: Optional[str]
        cover_emoji: Optional[str]
        start_date: date
        end_date: date
        primary_currency: str
        notes: Optional[str]

    trip = T(
        name="Trip",
        destination=None,
        cover_emoji=None,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        primary_currency="USD",
        notes=None,
    )
    out = trip_form_values(trip)
    assert out["destination"] == ""
    assert out["cover_emoji"] == ""
    assert out["notes"] == ""


# ─────────────────────────────  progress_fraction  ──────────────────────────


def test_progress_fraction_at_start_returns_one():
    # Day-of trip → ring fully filled.
    assert progress_fraction(date(2026, 8, 17), date(2026, 8, 17)) == 1.0


def test_progress_fraction_after_start_clamps_to_one():
    # Mid-trip → ring stays full (we don't represent overshoot).
    assert progress_fraction(date(2026, 8, 17), date(2026, 8, 20)) == 1.0


def test_progress_fraction_at_window_boundary_returns_zero():
    # 90 days out → ring empty.
    assert progress_fraction(date(2026, 8, 17), date(2026, 5, 19)) == 0.0


def test_progress_fraction_beyond_window_clamps_to_zero():
    # 200 days out → still 0.0, not negative.
    assert progress_fraction(date(2026, 8, 17), date(2026, 1, 1)) == 0.0


def test_progress_fraction_mid_window():
    # 45 days out → halfway through the 90-day window.
    result = progress_fraction(date(2026, 8, 17), date(2026, 7, 3))
    assert abs(result - 0.5) < 0.01


def test_progress_fraction_close_to_start():
    # 9 days out → 90% filled.
    result = progress_fraction(date(2026, 8, 17), date(2026, 8, 8))
    assert abs(result - 0.9) < 0.01


def test_progress_fraction_custom_window():
    # 30-day window, 15 days out → 50%.
    result = progress_fraction(date(2026, 8, 17), date(2026, 8, 2), window_days=30)
    assert abs(result - 0.5) < 0.01


# ─────────────────────────────  emoji_theme  ─────────────────────────────


def test_emoji_theme_beach_emojis():
    assert emoji_theme("🏝️") == "the beach"
    assert emoji_theme("🌴") == "the beach"
    assert emoji_theme("🌊") == "the beach"


def test_emoji_theme_takeoff():
    assert emoji_theme("✈️") == "takeoff"


def test_emoji_theme_mountains():
    assert emoji_theme("🏔️") == "the mountains"
    assert emoji_theme("⛷️") == "the mountains"


def test_emoji_theme_food():
    assert emoji_theme("🍝") == "the next great meal"
    assert emoji_theme("🍜") == "the next great meal"


def test_emoji_theme_history():
    assert emoji_theme("🏛️") == "history"


def test_emoji_theme_road():
    assert emoji_theme("🚗") == "the open road"


def test_emoji_theme_hotel():
    assert emoji_theme("🏨") == "check-in"


def test_emoji_theme_city():
    assert emoji_theme("🗽") == "the city"


def test_emoji_theme_default_suitcase_returns_none():
    # 🧳 is the default fallback emoji — keep it unthemed.
    assert emoji_theme("🧳") is None


def test_emoji_theme_unknown_returns_none():
    assert emoji_theme("🎉") is None


def test_emoji_theme_none_returns_none():
    assert emoji_theme(None) is None


def test_emoji_theme_empty_string_returns_none():
    assert emoji_theme("") is None

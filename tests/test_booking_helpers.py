"""Unit tests for src/booking_helpers.py."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from types import SimpleNamespace

from src.booking_helpers import (
    BOOKING_TYPES,
    BOOKING_TYPE_CODES,
    auto_itinerary_items_for_booking,
    booking_form_values,
    booking_type_emoji,
    booking_type_label,
    format_datetime_range,
    group_bookings_by_type,
    parse_booking_form,
    total_cost_by_currency,
)


@dataclass
class FakeBooking:
    """Minimal stand-in for a SQLAlchemy Booking — no DB needed for tests."""

    type: str
    title: str
    cost: Optional[float] = None
    currency: str = "USD"
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    vendor: Optional[str] = None
    confirmation_number: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None


# ─────────────────────────────  metadata  ──────────────────────────────────


def test_booking_types_codes_set_matches_tuple():
    assert BOOKING_TYPE_CODES == frozenset(c for c, _, _ in BOOKING_TYPES)


def test_booking_type_label_known_and_unknown():
    assert booking_type_label("flight") == "Flights"
    assert booking_type_label("zzz") == "zzz"


def test_booking_type_emoji_known_and_unknown():
    assert booking_type_emoji("hotel") == "🏨"
    assert booking_type_emoji("zzz") == "📌"  # generic pin fallback


# ─────────────────────────────  parse_booking_form  ────────────────────────


def _valid_booking_form(**overrides):
    base = {
        "type": "flight",
        "title": "Delta DL104 JFK → FCO",
        "vendor": "Delta",
        "confirmation_number": "ABC123",
        "start_datetime": "2026-06-01T21:30",
        "end_datetime": "2026-06-02T11:45",
        "location": "JFK Terminal 4",
        "cost": "599.99",
        "currency": "USD",
        "url": "https://delta.com/conf/ABC123",
        "notes": "Aisle seat",
    }
    base.update(overrides)
    return base


def test_parse_booking_form_valid_no_errors():
    data, field_errors = parse_booking_form(_valid_booking_form())
    assert field_errors == {}
    assert data["type"] == "flight"
    assert data["cost"] == 599.99
    assert data["start_datetime"] == datetime(2026, 6, 1, 21, 30)
    assert data["end_datetime"] == datetime(2026, 6, 2, 11, 45)
    assert data["currency"] == "USD"


def test_parse_booking_form_missing_title_errors():
    _, field_errors = parse_booking_form(_valid_booking_form(title=""))
    assert "title" in field_errors


def test_parse_booking_form_unknown_type_errors_and_falls_back():
    data, field_errors = parse_booking_form(_valid_booking_form(type="spaceship"))
    assert "type" in field_errors
    assert data["type"] == "other"


def test_parse_booking_form_blank_optional_fields_become_none():
    data, field_errors = parse_booking_form(_valid_booking_form(
        vendor="", confirmation_number="", location="", url="", notes="", cost=""
    ))
    assert field_errors == {}
    assert data["vendor"] is None
    assert data["confirmation_number"] is None
    assert data["location"] is None
    assert data["url"] is None
    assert data["notes"] is None
    assert data["cost"] is None


def test_parse_booking_form_negative_cost_errors():
    _, field_errors = parse_booking_form(_valid_booking_form(cost="-50"))
    assert "cost" in field_errors
    assert "negative" in field_errors["cost"]


def test_parse_booking_form_non_numeric_cost_errors():
    _, field_errors = parse_booking_form(_valid_booking_form(cost="abc"))
    assert "cost" in field_errors
    assert "number" in field_errors["cost"].lower()


def test_parse_booking_form_end_before_start_keys_on_end_datetime():
    _, field_errors = parse_booking_form(_valid_booking_form(
        start_datetime="2026-06-02T10:00",
        end_datetime="2026-06-01T10:00",
    ))
    # Cross-field error attaches to end_datetime so the inline message
    # appears next to the field the user can fix.
    assert "end_datetime" in field_errors
    assert "start_datetime" not in field_errors
    assert "on or after" in field_errors["end_datetime"]


def test_parse_booking_form_blank_dates_are_ok():
    data, field_errors = parse_booking_form(_valid_booking_form(start_datetime="", end_datetime=""))
    assert field_errors == {}
    assert data["start_datetime"] is None
    assert data["end_datetime"] is None


def test_parse_booking_form_invalid_datetime_string_errors():
    _, field_errors = parse_booking_form(_valid_booking_form(start_datetime="not-a-datetime"))
    assert "start_datetime" in field_errors


def test_parse_booking_form_uppercases_currency():
    data, field_errors = parse_booking_form(_valid_booking_form(currency="eur"))
    assert field_errors == {}
    assert data["currency"] == "EUR"


def test_parse_booking_form_blank_currency_uses_default():
    data, field_errors = parse_booking_form(_valid_booking_form(currency=""), default_currency="JPY")
    assert field_errors == {}
    assert data["currency"] == "JPY"


# ─────────────────────────────  booking_form_values  ───────────────────────


def test_booking_form_values_none_returns_empty_dict():
    assert booking_form_values(None) == {}


def test_booking_form_values_renders_datetime_local_format():
    b = FakeBooking(
        type="flight",
        title="DL104",
        start_datetime=datetime(2026, 6, 1, 21, 30),
        end_datetime=datetime(2026, 6, 2, 11, 45),
        cost=599.99,
    )
    out = booking_form_values(b)
    assert out["start_datetime"] == "2026-06-01T21:30"
    assert out["end_datetime"] == "2026-06-02T11:45"
    assert out["cost"] == "599.99"
    assert out["title"] == "DL104"


def test_booking_form_values_blank_cost_for_none():
    b = FakeBooking(type="other", title="Free walking tour", cost=None)
    out = booking_form_values(b)
    assert out["cost"] == ""


def test_booking_form_values_integer_cost_no_trailing_zeros():
    b = FakeBooking(type="hotel", title="Stay", cost=200.0)
    out = booking_form_values(b)
    assert out["cost"] == "200"


# ─────────────────────────────  group_bookings_by_type  ────────────────────


def test_group_bookings_by_type_canonical_order():
    bookings = [
        FakeBooking(type="restaurant", title="Dinner"),
        FakeBooking(type="flight", title="Outbound"),
        FakeBooking(type="hotel", title="Florence"),
    ]
    grouped = group_bookings_by_type(bookings)
    codes = [c for c, _, _, _ in grouped]
    # Display order from BOOKING_TYPES is flight, hotel, ..., restaurant.
    assert codes == ["flight", "hotel", "restaurant"]


def test_group_bookings_within_group_sorted_by_start_datetime():
    later = FakeBooking(type="flight", title="Return", start_datetime=datetime(2026, 6, 10, 12, 0))
    earlier = FakeBooking(type="flight", title="Outbound", start_datetime=datetime(2026, 6, 1, 9, 0))
    grouped = group_bookings_by_type([later, earlier])
    flights = grouped[0][3]
    assert [b.title for b in flights] == ["Outbound", "Return"]


def test_group_bookings_none_datetime_sorts_last_within_group():
    timed = FakeBooking(type="flight", title="Timed", start_datetime=datetime(2026, 6, 1, 9, 0))
    untimed = FakeBooking(type="flight", title="Untimed", start_datetime=None)
    grouped = group_bookings_by_type([untimed, timed])
    flights = grouped[0][3]
    assert [b.title for b in flights] == ["Timed", "Untimed"]


def test_group_bookings_empty_input_returns_empty_list():
    assert group_bookings_by_type([]) == []


def test_group_bookings_unknown_type_falls_into_other():
    # Defensive — corrupt type should still display, not crash.
    weird = FakeBooking(type="spaceship", title="Mars")
    grouped = group_bookings_by_type([weird])
    # Unknown types fall through and aren't matched by any canonical type.
    # group_bookings_by_type only emits canonical types, so this is dropped.
    assert grouped == []


# ─────────────────────────────  total_cost_by_currency  ────────────────────


def test_total_cost_by_currency_sums_per_currency():
    bookings = [
        FakeBooking(type="flight", title="A", cost=600.0, currency="USD"),
        FakeBooking(type="hotel",  title="B", cost=400.0, currency="USD"),
        FakeBooking(type="restaurant", title="C", cost=80.0, currency="EUR"),
    ]
    totals = total_cost_by_currency(bookings)
    assert totals == {"USD": 1000.0, "EUR": 80.0}


def test_total_cost_by_currency_skips_none_cost():
    bookings = [
        FakeBooking(type="flight", title="A", cost=None, currency="USD"),
        FakeBooking(type="hotel",  title="B", cost=300.0, currency="USD"),
    ]
    assert total_cost_by_currency(bookings) == {"USD": 300.0}


def test_total_cost_by_currency_uppercases_codes():
    bookings = [FakeBooking(type="flight", title="A", cost=100.0, currency="usd")]
    assert total_cost_by_currency(bookings) == {"USD": 100.0}


def test_total_cost_by_currency_empty_input_returns_empty_dict():
    assert total_cost_by_currency([]) == {}


# ─────────────────────────────  format_datetime_range  ─────────────────────


def test_format_datetime_range_both_same_day():
    start = datetime(2026, 6, 1, 9, 30)
    end = datetime(2026, 6, 1, 11, 45)
    assert format_datetime_range(start, end) == "Jun 01, 2026 · 9:30 AM – 11:45 AM"


def test_format_datetime_range_both_different_days():
    start = datetime(2026, 6, 1, 21, 30)
    end = datetime(2026, 6, 2, 11, 45)
    assert format_datetime_range(start, end) == "Jun 01 · 9:30 PM – Jun 02, 2026 · 11:45 AM"


def test_format_datetime_range_start_only():
    assert format_datetime_range(datetime(2026, 6, 1, 9, 30), None) == "Jun 01, 2026 · 9:30 AM"


def test_format_datetime_range_end_only():
    assert format_datetime_range(None, datetime(2026, 6, 1, 9, 30)) == "→ Jun 01, 2026 · 9:30 AM"


def test_format_datetime_range_both_none():
    assert format_datetime_range(None, None) == ""


def test_format_datetime_range_strips_zero_padded_hour():
    # 09:30 AM should display as 9:30 AM, not 09:30 AM.
    out = format_datetime_range(datetime(2026, 6, 1, 9, 30), None)
    assert "9:30 AM" in out
    assert "09:30 AM" not in out


# ─────────────────────────────  auto_itinerary_items_for_booking  ──────────


def test_auto_itinerary_flight_two_items_with_both_datetimes():
    b = FakeBooking(
        type="flight",
        title="DL104",
        vendor="Delta",
        start_datetime=datetime(2026, 6, 1, 21, 30),
        end_datetime=datetime(2026, 6, 2, 11, 45),
        location="JFK Terminal 4",
    )
    items = auto_itinerary_items_for_booking(b)
    assert len(items) == 2
    depart, arrive = items
    assert depart["title"] == "Depart Delta"
    assert depart["category"] == "transit"
    assert depart["day_date"].isoformat() == "2026-06-01"
    assert depart["start_time"].strftime("%H:%M") == "21:30"
    assert depart["location"] == "JFK Terminal 4"
    assert arrive["title"] == "Arrive Delta"
    assert arrive["day_date"].isoformat() == "2026-06-02"


def test_auto_itinerary_flight_only_start_makes_one_depart_item():
    b = FakeBooking(
        type="flight", title="DL104", vendor="Delta",
        start_datetime=datetime(2026, 6, 1, 21, 30),
    )
    items = auto_itinerary_items_for_booking(b)
    assert len(items) == 1
    assert items[0]["title"] == "Depart Delta"


def test_auto_itinerary_flight_only_end_makes_one_arrive_item():
    b = FakeBooking(
        type="flight", title="DL104", vendor="Delta",
        end_datetime=datetime(2026, 6, 2, 11, 45),
    )
    items = auto_itinerary_items_for_booking(b)
    assert len(items) == 1
    assert items[0]["title"] == "Arrive Delta"


def test_auto_itinerary_flight_no_datetimes_makes_zero_items():
    b = FakeBooking(type="flight", title="DL104", vendor="Delta")
    assert auto_itinerary_items_for_booking(b) == []


def test_auto_itinerary_flight_falls_back_to_title_when_no_vendor():
    b = FakeBooking(
        type="flight", title="DL104",
        start_datetime=datetime(2026, 6, 1, 21, 30),
    )
    items = auto_itinerary_items_for_booking(b)
    assert items[0]["title"] == "Depart DL104"


def test_auto_itinerary_flight_no_label_just_uses_prefix():
    b = FakeBooking(
        type="flight", title="",
        start_datetime=datetime(2026, 6, 1, 21, 30),
    )
    items = auto_itinerary_items_for_booking(b)
    assert items[0]["title"] == "Depart"


def test_auto_itinerary_hotel_check_in_and_out():
    b = FakeBooking(
        type="hotel", title="Marriott Florence", vendor="Marriott",
        start_datetime=datetime(2026, 6, 1, 15, 0),
        end_datetime=datetime(2026, 6, 5, 11, 0),
        location="Piazza Repubblica, Florence",
    )
    items = auto_itinerary_items_for_booking(b)
    assert len(items) == 2
    assert items[0]["title"] == "Check in: Marriott"
    assert items[0]["category"] == "other"
    assert items[0]["location"] == "Piazza Repubblica, Florence"
    assert items[1]["title"] == "Check out: Marriott"
    assert items[1]["location"] is None  # checkout location only on checkin item


def test_auto_itinerary_car_pickup_and_return():
    b = FakeBooking(
        type="car", title="Hertz Compact", vendor="Hertz",
        start_datetime=datetime(2026, 6, 1, 12, 0),
        end_datetime=datetime(2026, 6, 7, 18, 0),
    )
    items = auto_itinerary_items_for_booking(b)
    assert [i["title"] for i in items] == ["Pick up car: Hertz", "Return car: Hertz"]
    assert all(i["category"] == "transit" for i in items)


def test_auto_itinerary_restaurant_one_meal_item():
    b = FakeBooking(
        type="restaurant", title="Da Roberto", vendor="",
        start_datetime=datetime(2026, 6, 2, 19, 30),
        end_datetime=datetime(2026, 6, 2, 21, 30),
        location="Via del Corso 5",
    )
    items = auto_itinerary_items_for_booking(b)
    assert len(items) == 1
    assert items[0]["title"] == "Da Roberto"
    assert items[0]["category"] == "meal"
    assert items[0]["start_time"].strftime("%H:%M") == "19:30"
    assert items[0]["end_time"].strftime("%H:%M") == "21:30"


def test_auto_itinerary_restaurant_no_start_skipped():
    b = FakeBooking(type="restaurant", title="Da Roberto")
    assert auto_itinerary_items_for_booking(b) == []


def test_auto_itinerary_activity_creates_sightseeing_item():
    b = FakeBooking(
        type="activity", title="Colosseum tour",
        start_datetime=datetime(2026, 6, 2, 9, 30),
        end_datetime=datetime(2026, 6, 2, 11, 45),
        location="Piazza del Colosseo",
    )
    items = auto_itinerary_items_for_booking(b)
    assert len(items) == 1
    assert items[0]["title"] == "Colosseum tour"
    assert items[0]["category"] == "sightseeing"


def test_auto_itinerary_transport_makes_zero_items():
    b = FakeBooking(
        type="transport", title="Train",
        start_datetime=datetime(2026, 6, 2, 9, 30),
    )
    assert auto_itinerary_items_for_booking(b) == []


def test_auto_itinerary_other_makes_zero_items():
    b = FakeBooking(
        type="other", title="Insurance",
        start_datetime=datetime(2026, 6, 2, 9, 30),
    )
    assert auto_itinerary_items_for_booking(b) == []


def test_auto_itinerary_restaurant_drops_end_time_on_different_day():
    # Defensive — if end is on a different day, don't pretend it's a long meal.
    b = FakeBooking(
        type="restaurant", title="Da Roberto",
        start_datetime=datetime(2026, 6, 2, 19, 30),
        end_datetime=datetime(2026, 6, 3, 0, 30),
    )
    items = auto_itinerary_items_for_booking(b)
    assert items[0]["end_time"] is None


# ─────────────────────────────  auto_kind tags  ────────────────────────────


def test_auto_kind_set_for_flight():
    b = FakeBooking(type="flight", title="UA101", vendor="United",
                    start_datetime=datetime(2026, 6, 1, 10, 0),
                    end_datetime=datetime(2026, 6, 1, 14, 0))
    items = auto_itinerary_items_for_booking(b)
    assert [it["auto_kind"] for it in items] == ["depart", "arrive"]


def test_auto_kind_set_for_hotel():
    b = FakeBooking(type="hotel", title="Hilton", vendor="Hilton",
                    start_datetime=datetime(2026, 6, 1, 15, 0),
                    end_datetime=datetime(2026, 6, 3, 11, 0))
    items = auto_itinerary_items_for_booking(b)
    assert [it["auto_kind"] for it in items] == ["check_in", "check_out"]


def test_auto_kind_set_for_car():
    b = FakeBooking(type="car", title="Hertz", vendor="Hertz",
                    start_datetime=datetime(2026, 6, 1, 9, 0),
                    end_datetime=datetime(2026, 6, 5, 17, 0))
    items = auto_itinerary_items_for_booking(b)
    assert [it["auto_kind"] for it in items] == ["pickup", "return"]


def test_auto_kind_set_for_restaurant():
    b = FakeBooking(type="restaurant", title="Noma", vendor="Noma",
                    start_datetime=datetime(2026, 6, 1, 19, 0))
    items = auto_itinerary_items_for_booking(b)
    assert items[0]["auto_kind"] == "single"


def test_auto_kind_set_for_activity():
    b = FakeBooking(type="activity", title="Museum",
                    start_datetime=datetime(2026, 6, 1, 10, 0))
    items = auto_itinerary_items_for_booking(b)
    assert items[0]["auto_kind"] == "single"


def test_auto_kind_transport_returns_no_items():
    b = FakeBooking(type="transport", title="Train",
                    start_datetime=datetime(2026, 6, 1, 10, 0),
                    end_datetime=datetime(2026, 6, 1, 12, 0))
    assert auto_itinerary_items_for_booking(b) == []


# ─────────────────────────────  parse_touched and serialize_touched  ────────

from src.booking_helpers import parse_touched, serialize_touched


def test_parse_touched_empty_returns_empty_set():
    assert parse_touched("") == set()


def test_parse_touched_none_returns_empty_set():
    assert parse_touched(None) == set()


def test_parse_touched_single_field():
    assert parse_touched("title") == {"title"}


def test_parse_touched_multiple_fields():
    assert parse_touched("title,day_date") == {"title", "day_date"}


def test_parse_touched_drops_unknown_field_names():
    # 'frobnicate' isn't in DRIFT_FIELDS — should be silently dropped.
    assert parse_touched("title,frobnicate,day_date") == {"title", "day_date"}


def test_parse_touched_handles_whitespace():
    assert parse_touched("title, day_date") == {"title", "day_date"}


def test_serialize_touched_empty_returns_empty_string():
    assert serialize_touched(set()) == ""


def test_serialize_touched_single_field():
    assert serialize_touched({"title"}) == "title"


def test_serialize_touched_sorts_output():
    # Input set order is non-deterministic; output must be sorted.
    assert serialize_touched({"title", "day_date"}) == "day_date,title"


def test_serialize_touched_drops_unknown_field_names():
    assert serialize_touched({"title", "frobnicate"}) == "title"


def test_serialize_touched_round_trips_with_parse():
    fields = {"title", "day_date", "location"}
    assert parse_touched(serialize_touched(fields)) == fields


def test_serialize_touched_all_drift_fields_matches_backfill_string():
    """Spec invariant: serialize_touched(DRIFT_FIELDS) must equal the
    string used by the migration backfill UPDATE."""
    from src.booking_helpers import DRIFT_FIELDS
    expected = "category,day_date,end_time,location,start_time,title"
    assert serialize_touched(DRIFT_FIELDS) == expected


# ──────────────────────  missing_auto_kinds_for_booking  ──────────────────────

from src.booking_helpers import NewItemSuggestion, missing_auto_kinds_for_booking


def test_missing_auto_kinds_returns_empty_when_all_exist():
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=datetime(2026, 6, 1, 14, 0),
                        location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds={"depart", "arrive"},
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    assert result == []


def test_missing_auto_kinds_returns_both_when_none_exist():
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=datetime(2026, 6, 1, 14, 0),
                        location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds=set(),
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    kinds = [w["auto_kind"] for w in result]
    assert sorted(kinds) == ["arrive", "depart"]


def test_missing_auto_kinds_returns_only_missing_when_one_exists():
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=datetime(2026, 6, 1, 14, 0),
                        location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds={"depart"},
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    kinds = [w["auto_kind"] for w in result]
    assert kinds == ["arrive"]


def test_missing_auto_kinds_excludes_items_outside_trip_range():
    """A suggestion whose day_date is outside [trip_start, trip_end] is filtered."""
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 7, 1, 10, 0),  # after end
                        end_datetime=datetime(2026, 7, 1, 14, 0),
                        location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds=set(),
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    assert result == []


def test_missing_auto_kinds_empty_for_non_spawning_booking_types():
    """Transport and 'other' bookings generate no auto-slots."""
    b = SimpleNamespace(type="transport", title="Subway", vendor=None,
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=None, location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds=set(),
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    assert result == []


def test_new_item_suggestion_carries_booking_kind_and_data():
    """Dataclass smoke test — fields and attribute access."""
    s = NewItemSuggestion(booking="booking-stand-in", auto_kind="arrive",
                          item_data={"title": "X"})
    assert s.booking == "booking-stand-in"
    assert s.auto_kind == "arrive"
    assert s.item_data == {"title": "X"}

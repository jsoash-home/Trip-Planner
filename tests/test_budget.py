"""Unit tests for src/budget.py."""

from dataclasses import dataclass
from typing import Optional

from src.budget import (
    category_emoji,
    category_label,
    format_money_totals,
    rollup_bookings_by_category,
)


@dataclass
class FakeBooking:
    """Minimal stand-in for a Booking row."""

    type: str
    cost: Optional[float] = None
    currency: str = "USD"


# ─────────────────────────────  rollup_bookings_by_category  ───────────────


def test_rollup_empty_input_returns_empty_list():
    assert rollup_bookings_by_category([]) == []


def test_rollup_single_costed_booking():
    bookings = [FakeBooking(type="flight", cost=600.0, currency="USD")]
    out = rollup_bookings_by_category(bookings)
    assert len(out) == 1
    cat = out[0]
    assert cat["code"] == "flight"
    assert cat["label"] == "Flights"
    assert cat["emoji"] == "✈️"
    assert cat["count"] == 1
    assert cat["uncosted_count"] == 0
    assert cat["totals_by_currency"] == {"USD": 600.0}


def test_rollup_sums_within_category_same_currency():
    bookings = [
        FakeBooking(type="hotel", cost=400.0, currency="EUR"),
        FakeBooking(type="hotel", cost=200.0, currency="EUR"),
    ]
    out = rollup_bookings_by_category(bookings)
    assert out[0]["count"] == 2
    assert out[0]["totals_by_currency"] == {"EUR": 600.0}


def test_rollup_separates_currencies_within_category():
    bookings = [
        FakeBooking(type="hotel", cost=400.0, currency="EUR"),
        FakeBooking(type="hotel", cost=200.0, currency="USD"),
    ]
    out = rollup_bookings_by_category(bookings)
    assert out[0]["totals_by_currency"] == {"EUR": 400.0, "USD": 200.0}


def test_rollup_multiple_categories_in_canonical_order():
    bookings = [
        FakeBooking(type="restaurant", cost=80, currency="USD"),
        FakeBooking(type="flight",     cost=600, currency="USD"),
        FakeBooking(type="hotel",      cost=400, currency="USD"),
    ]
    out = rollup_bookings_by_category(bookings)
    # Display order: flight, hotel, ..., restaurant.
    codes = [c["code"] for c in out]
    assert codes == ["flight", "hotel", "restaurant"]


def test_rollup_uncosted_bookings_counted_separately():
    bookings = [
        FakeBooking(type="flight", cost=600, currency="USD"),
        FakeBooking(type="flight", cost=None, currency="USD"),
        FakeBooking(type="flight", cost=None, currency="USD"),
    ]
    out = rollup_bookings_by_category(bookings)
    cat = out[0]
    assert cat["count"] == 3
    assert cat["uncosted_count"] == 2
    assert cat["totals_by_currency"] == {"USD": 600.0}


def test_rollup_all_uncosted_category_has_empty_totals():
    bookings = [
        FakeBooking(type="hotel", cost=None, currency="USD"),
        FakeBooking(type="hotel", cost=None, currency="USD"),
    ]
    out = rollup_bookings_by_category(bookings)
    assert out[0]["count"] == 2
    assert out[0]["uncosted_count"] == 2
    assert out[0]["totals_by_currency"] == {}


def test_rollup_uppercases_currency_codes():
    bookings = [FakeBooking(type="flight", cost=100.0, currency="usd")]
    out = rollup_bookings_by_category(bookings)
    assert out[0]["totals_by_currency"] == {"USD": 100.0}


def test_rollup_falls_back_to_other_for_unknown_type():
    # Defensive — a booking row with a corrupt type string should still appear.
    # rollup currently drops unknown types because BOOKING_TYPES is the source
    # of truth for ordering; the test documents the behaviour.
    bookings = [FakeBooking(type="spaceship", cost=100, currency="USD")]
    out = rollup_bookings_by_category(bookings)
    # Unknown types aren't in BOOKING_TYPES, so they're not in the output.
    assert out == []


# ─────────────────────────────  format_money_totals  ───────────────────────


def test_format_money_totals_empty_returns_em_dash():
    assert format_money_totals({}) == "—"


def test_format_money_totals_empty_uses_custom_empty_string():
    assert format_money_totals({}, empty="No cost") == "No cost"


def test_format_money_totals_single_currency():
    assert format_money_totals({"USD": 1234.5}) == "$1,234.50"


def test_format_money_totals_multiple_currencies_alphabetical():
    out = format_money_totals({"USD": 100, "EUR": 200, "GBP": 50})
    # Alphabetical order: EUR, GBP, USD
    assert out == "€200.00 + £50.00 + $100.00"


def test_format_money_totals_handles_jpy_no_decimals():
    out = format_money_totals({"JPY": 50000})
    assert out == "¥50,000"


# ─────────────────────────────  category helpers  ──────────────────────────


def test_category_label_known():
    assert category_label("flight") == "Flights"


def test_category_label_unknown_passes_through():
    assert category_label("zzz") == "zzz"


def test_category_emoji_known():
    assert category_emoji("hotel") == "🏨"


def test_category_emoji_unknown_returns_pin():
    assert category_emoji("zzz") == "📌"

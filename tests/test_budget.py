"""Unit tests for src/budget.py."""

from dataclasses import dataclass
from typing import Optional

import pytest

from src.budget import (
    category_emoji,
    category_label,
    convert_totals,
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


# ─────────────────────────  rollup with primary_currency  ──────────────────


def test_rollup_without_primary_currency_omits_share_keys():
    """Backward compat: existing callers see no new keys."""
    bookings = [FakeBooking(type="flight", cost=600, currency="USD")]
    out = rollup_bookings_by_category(bookings)
    assert "share_fraction" not in out[0]
    assert "primary_total" not in out[0]


def test_rollup_single_category_primary_currency_share_is_one():
    bookings = [FakeBooking(type="flight", cost=600, currency="USD")]
    out = rollup_bookings_by_category(bookings, primary_currency="USD")
    assert out[0]["primary_total"] == 600.0
    assert out[0]["share_fraction"] == 1.0


def test_rollup_two_categories_same_currency_shares_sum_to_one():
    bookings = [
        FakeBooking(type="flight", cost=600, currency="USD"),
        FakeBooking(type="hotel",  cost=400, currency="USD"),
    ]
    out = rollup_bookings_by_category(bookings, primary_currency="USD")
    by_code = {c["code"]: c for c in out}
    assert by_code["flight"]["share_fraction"] == 0.6
    assert by_code["hotel"]["share_fraction"] == 0.4
    assert by_code["flight"]["share_fraction"] + by_code["hotel"]["share_fraction"] == 1.0


def test_rollup_foreign_currency_category_has_zero_share():
    """Category with only non-primary currency contributes nothing to share."""
    bookings = [
        FakeBooking(type="flight",     cost=600, currency="USD"),
        FakeBooking(type="restaurant", cost=200, currency="EUR"),
    ]
    out = rollup_bookings_by_category(bookings, primary_currency="USD")
    by_code = {c["code"]: c for c in out}
    assert by_code["flight"]["share_fraction"] == 1.0
    assert by_code["restaurant"]["primary_total"] == 0.0
    assert by_code["restaurant"]["share_fraction"] == 0.0


def test_rollup_all_foreign_currency_all_shares_zero():
    bookings = [
        FakeBooking(type="flight", cost=600, currency="EUR"),
        FakeBooking(type="hotel",  cost=400, currency="EUR"),
    ]
    out = rollup_bookings_by_category(bookings, primary_currency="USD")
    for cat in out:
        assert cat["primary_total"] == 0.0
        assert cat["share_fraction"] == 0.0


def test_rollup_uncosted_only_category_has_zero_share():
    bookings = [
        FakeBooking(type="flight", cost=600, currency="USD"),
        FakeBooking(type="hotel",  cost=None, currency="USD"),
    ]
    out = rollup_bookings_by_category(bookings, primary_currency="USD")
    by_code = {c["code"]: c for c in out}
    assert by_code["hotel"]["primary_total"] == 0.0
    assert by_code["hotel"]["share_fraction"] == 0.0
    assert by_code["flight"]["share_fraction"] == 1.0


def test_rollup_mixed_currency_category_counts_only_primary_in_share():
    """A category with both USD and EUR rows contributes only its USD slice."""
    bookings = [
        FakeBooking(type="flight", cost=600, currency="USD"),
        FakeBooking(type="hotel",  cost=400, currency="USD"),
        FakeBooking(type="hotel",  cost=500, currency="EUR"),
    ]
    out = rollup_bookings_by_category(bookings, primary_currency="USD")
    by_code = {c["code"]: c for c in out}
    # hotel's primary_total is 400 (the EUR row doesn't count).
    # Denominator is 600 + 400 = 1000.
    assert by_code["hotel"]["primary_total"] == 400.0
    assert by_code["hotel"]["share_fraction"] == 0.4
    assert by_code["flight"]["share_fraction"] == 0.6


def test_rollup_primary_currency_lowercased_still_matches():
    """Robust to lowercase primary_currency input."""
    bookings = [FakeBooking(type="flight", cost=100, currency="USD")]
    out = rollup_bookings_by_category(bookings, primary_currency="usd")
    assert out[0]["share_fraction"] == 1.0


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


# ─────────────────────────────  convert_totals  ────────────────────────────


def test_convert_totals_empty_input_returns_empty():
    assert convert_totals({}, "USD", {}) == {}


def test_convert_totals_same_currency_passthrough():
    # No rates needed when source == target.
    out = convert_totals({"USD": 100.0}, "USD", {})
    assert out == {"USD": 100.0}


def test_convert_totals_single_foreign_converts():
    # EUR at rate 0.909 (USD per EUR) → 100 EUR ≈ 90.91 USD
    out = convert_totals({"EUR": 100.0}, "USD", {"EUR": 0.909})
    assert out["USD"] == pytest.approx(90.9)


def test_convert_totals_multiple_foreign_sum_to_target():
    # 100 EUR @ 0.909 + 50 GBP @ 1.27 = 90.9 + 63.5 = 154.4 USD
    out = convert_totals(
        {"EUR": 100.0, "GBP": 50.0}, "USD",
        {"EUR": 0.909, "GBP": 1.27},
    )
    assert out == {"USD": pytest.approx(154.4)}


def test_convert_totals_mixed_target_and_foreign():
    # Target USD + foreign EUR fold into one USD entry.
    out = convert_totals(
        {"USD": 50.0, "EUR": 100.0}, "USD",
        {"EUR": 0.909},
    )
    assert out["USD"] == pytest.approx(140.9)
    assert len(out) == 1


def test_convert_totals_missing_rate_passes_through():
    # BRL has no rate — it passes through unconverted alongside USD total.
    out = convert_totals(
        {"EUR": 100.0, "BRL": 200.0}, "USD",
        {"EUR": 0.909},
    )
    assert out["USD"] == pytest.approx(90.9)
    assert out["BRL"] == 200.0


def test_convert_totals_negative_amounts_handled():
    # Refund-style negative entry: -100 EUR @ 0.909 → -90.9 USD
    out = convert_totals({"EUR": -100.0}, "USD", {"EUR": 0.909})
    assert out["USD"] == pytest.approx(-90.9)

"""Unit tests for src/booking_parser.py — dataclasses + extraction helpers.

Task 1 of paste-and-parse-booking: pure helpers only, no DB / Flask / network.
"""

from datetime import datetime

from src.booking_parser import (
    ParsedBooking,
    extract_confirmation_number,
    extract_dates,
    extract_money,
    extract_url,
    score_confidence,
)


# ─────────────────────────────  extract_dates  ─────────────────────────────


def test_extract_dates_finds_iso():
    text = "Departs 2026-08-17T14:30 and lands 2026-08-17 18:45. Trip starts 2026-08-17."
    out = extract_dates(text)
    assert datetime(2026, 8, 17, 14, 30) in out
    assert datetime(2026, 8, 17, 18, 45) in out
    assert datetime(2026, 8, 17, 0, 0) in out
    # Sorted chronologically.
    assert out == sorted(out)


def test_extract_dates_finds_human_format():
    text = "Reservation on Mon, Aug 17 2026 3:45 PM at the bistro. Also see August 17, 2026 at 3:45 PM. Earlier: Aug 17, 2026."
    out = extract_dates(text)
    assert datetime(2026, 8, 17, 15, 45) in out
    assert datetime(2026, 8, 17, 0, 0) in out


def test_extract_dates_finds_us_slash_format():
    text = "Pickup 08/17/2026 3:45 PM, return 8/17/26."
    out = extract_dates(text)
    assert datetime(2026, 8, 17, 15, 45) in out
    assert datetime(2026, 8, 17, 0, 0) in out


def test_extract_dates_returns_empty_on_no_match():
    assert extract_dates("just words, no dates whatsoever") == []
    assert extract_dates("") == []


# ─────────────────────────────  extract_money  ─────────────────────────────


def test_extract_money_usd_dollar_sign():
    assert extract_money("Total: $123.45 for the night.") == (123.45, "USD")


def test_extract_money_iso_prefix():
    assert extract_money("Charged USD 123.45 to your card.") == (123.45, "USD")
    assert extract_money("Cost: EUR 45.50") == (45.50, "EUR")


def test_extract_money_euro_comma_decimal():
    assert extract_money("Total €45,00 including tax.") == (45.0, "EUR")


def test_extract_money_returns_none_on_no_match():
    assert extract_money("No prices here, just words.") is None
    assert extract_money("") is None


# ──────────────────────  extract_confirmation_number  ──────────────────────


def test_extract_confirmation_number_with_anchor():
    assert extract_confirmation_number("Confirmation #: ABC123XYZ") == "ABC123XYZ"
    assert extract_confirmation_number("Booking reference: ZZ9988") == "ZZ9988"
    assert extract_confirmation_number("Record locator: PNR42K") == "PNR42K"


def test_extract_confirmation_number_no_anchor_fallback():
    # 6–10 alphanumeric chars with at least one letter AND one digit.
    assert extract_confirmation_number("Your reservation AB12CD has been booked.") == "AB12CD"
    # Plain words and plain numbers should NOT match.
    assert extract_confirmation_number("just plain words here today") is None
    assert extract_confirmation_number("the year 123456 came and went") is None


# ─────────────────────────────  extract_url  ───────────────────────────────


def test_extract_url_first_https():
    text = "Manage at https://airline.example.com/abc?x=1 or https://other.example.com"
    assert extract_url(text) == "https://airline.example.com/abc?x=1"


def test_extract_url_returns_none_if_absent():
    assert extract_url("no links here, sorry") is None
    assert extract_url("") is None


# ─────────────────────────────  score_confidence  ──────────────────────────


def test_score_confidence_full_match_is_1():
    p = ParsedBooking(
        type="flight",
        title="DL123 SFO→JFK",
        vendor="Delta",
        start_datetime=datetime(2026, 8, 17, 14, 30),
        location="SFO",
    )
    assert score_confidence(p) == 1.0


def test_score_confidence_empty_is_0():
    # No type, no title — but type is a required field that's empty.
    # Use an unknown type code to force 0.0 path.
    p = ParsedBooking(type="zzz_unknown", title="")
    assert score_confidence(p) == 0.0


def test_score_confidence_partial_flight():
    # flight requires (type, title, vendor, start_datetime, location) — 5 fields.
    # Populate type, title, vendor → 3/5 = 0.6.
    p = ParsedBooking(type="flight", title="DL123", vendor="Delta")
    assert score_confidence(p) == 0.6

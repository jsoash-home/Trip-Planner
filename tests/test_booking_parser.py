"""Unit tests for src/booking_parser.py — dataclasses + extraction helpers.

Task 1 of paste-and-parse-booking: pure helpers only, no DB / Flask / network.
"""

from datetime import datetime
from pathlib import Path

from src.booking_parser import (
    ParsedBooking,
    extract_confirmation_number,
    extract_dates,
    extract_flight,
    extract_money,
    extract_url,
    score_confidence,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "booking_emails"


def load_fixture(rel_path: str) -> str:
    return (FIXTURE_DIR / rel_path).read_text(encoding="utf-8")


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


# ─────────────────────────────  extract_flight  ────────────────────────────


def test_flight_single_segment_united_style():
    p = extract_flight(load_fixture("flight/united_single.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "flight"
    assert p.vendor == "United Airlines"
    assert "SFO" in p.title and "LHR" in p.title and "→" in p.title
    assert "UA 423" in p.title or "UA423" in p.title
    assert p.start_datetime == datetime(2026, 8, 17, 22, 30)
    assert p.end_datetime == datetime(2026, 8, 18, 17, 15)
    assert p.location == "SFO"
    assert p.confirmation_number == "ABC123"


def test_flight_single_segment_with_iata_dash_form():
    p = extract_flight(load_fixture("flight/iata_dash.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "flight"
    assert p.location == "AMS"
    assert "AMS" in p.title and "JFK" in p.title
    assert p.start_datetime == datetime(2026, 9, 4, 13, 45)
    assert p.end_datetime == datetime(2026, 9, 4, 16, 10)
    assert p.confirmation_number == "XK9P2T"


def test_flight_multi_segment_returns_list():
    out = extract_flight(load_fixture("flight/round_trip.txt"))
    assert isinstance(out, list)
    assert len(out) == 2
    # Sorted by start_datetime ascending.
    assert out[0].start_datetime == datetime(2026, 9, 21, 16, 15)
    assert out[1].start_datetime == datetime(2026, 10, 5, 14, 0)
    # Outbound + return have opposite origins.
    assert out[0].location == "SFO"
    assert out[1].location == "LHR"
    # Confirmation number is shared (global to the email).
    assert out[0].confirmation_number == "BA8M2P"
    assert out[1].confirmation_number == "BA8M2P"
    # Each segment scored independently — both should be reasonable.
    assert out[0].confidence >= 0.6
    assert out[1].confidence >= 0.6
    # Per-segment flight-no + vendor (guards segment-local search).
    assert "BA 286" in out[0].title
    assert "BA 285" in out[1].title
    assert out[0].vendor == "British Airways"
    assert out[1].vendor == "British Airways"


def test_flight_multi_segment_same_date_returns_list():
    # Two-leg same-day connection JFK → ATL → LAX. Both legs share Sep 17.
    text = """Delta — itinerary

Flight DL 100
JFK → ATL
Depart: Thu, Sep 17 2026 at 8:00 AM
Arrive: Thu, Sep 17 2026 at 10:45 AM

Flight DL 200
ATL → LAX
Depart: Thu, Sep 17 2026 at 12:15 PM
Arrive: Thu, Sep 17 2026 at 2:30 PM

Confirmation: DL77AB
"""
    out = extract_flight(text)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0].location == "JFK"
    assert out[1].location == "ATL"
    assert "DL 100" in out[0].title
    assert "DL 200" in out[1].title


def test_flight_anchor_does_not_match_department():
    # "Department of Transportation" must NOT pollute the start_datetime;
    # the real "Depart: Sep 17 2026" line is what should win.
    text = """American Airlines

Flight AA 100
JFK → LAX
Department of Transportation notice: see https://transportation.gov for details.
Depart: Sep 17 2026 at 9:00 AM
Arrive: Sep 17 2026 at 12:30 PM

Confirmation: AA99XY
"""
    p = extract_flight(text)
    assert isinstance(p, ParsedBooking)
    assert p.start_datetime == datetime(2026, 9, 17, 9, 0)


def test_flight_extracts_confirmation_number():
    p = extract_flight(load_fixture("flight/united_single.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.confirmation_number == "ABC123"


def test_flight_extracts_cost_and_currency():
    p = extract_flight(load_fixture("flight/united_single.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.cost == 1245.00
    assert p.currency == "USD"


def test_flight_missing_arrival_time_still_returns_booking():
    p = extract_flight(load_fixture("flight/only_dep.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.start_datetime == datetime(2026, 10, 12, 6, 0)
    assert p.end_datetime is None
    assert p.location == "FLL"


def test_flight_returns_none_for_hotel_confirmation():
    assert extract_flight(load_fixture("flight/_negative/marriott.txt")) is None


def test_flight_returns_none_for_restaurant_confirmation():
    assert extract_flight(load_fixture("flight/_negative/opentable.txt")) is None


def test_flight_confidence_high_when_all_fields_present():
    p = extract_flight(load_fixture("flight/united_single.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.confidence >= 0.8


def test_flight_confidence_low_when_only_iata_pair():
    # Bare IATA pair, no vendor / date / flight number → low score.
    p = extract_flight("Trip leg: SFO → JFK and that's all we know.")
    assert isinstance(p, ParsedBooking)
    assert p.confidence < 0.6

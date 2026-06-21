"""Unit tests for src/booking_parser.py — dataclasses + extraction helpers.

Task 1 of paste-and-parse-booking: pure helpers only, no DB / Flask / network.
"""

from datetime import datetime
from pathlib import Path

from src.booking_parser import (
    ParsedBooking,
    extract_car,
    extract_confirmation_number,
    extract_dates,
    extract_flight,
    extract_hotel,
    extract_money,
    extract_restaurant,
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


# ─────────────────────────────  extract_hotel  ─────────────────────────────


def test_hotel_marriott_style():
    p = extract_hotel(load_fixture("hotel/marriott.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "hotel"
    assert p.vendor == "Marriott Times Square"
    assert p.title == "Marriott Times Square"
    assert p.start_datetime == datetime(2026, 8, 8, 16, 0)
    assert p.end_datetime == datetime(2026, 8, 10, 11, 0)
    assert p.location is not None and "1535 Broadway" in p.location
    assert p.cost == 682.00
    assert p.currency == "USD"
    assert p.confirmation_number == "88842310"
    # All 5 required fields populated → confidence should be near 1.0.
    assert p.confidence >= 0.8


def test_hotel_booking_com_style():
    p = extract_hotel(load_fixture("hotel/booking_dot_com.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "hotel"
    # Aggregator name stripped; hotel name extracted.
    assert p.vendor is not None and "Saint-Germain" in p.vendor
    assert p.start_datetime == datetime(2026, 9, 12, 15, 0)
    assert p.end_datetime == datetime(2026, 9, 15, 11, 0)
    assert p.cost == 1245.00
    assert p.currency == "EUR"


def test_hotel_airbnb_style():
    p = extract_hotel(load_fixture("hotel/airbnb.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "hotel"
    assert p.vendor is not None and "Loft" in p.vendor
    # No times in fixture — defaults apply (3pm in, 11am out).
    assert p.start_datetime == datetime(2026, 10, 17, 15, 0)
    assert p.end_datetime == datetime(2026, 10, 23, 11, 0)
    assert p.cost == 2184.00


def test_hotel_extracts_nightly_total():
    # Itemised nightly rates — the Total: line (largest amount) wins.
    p = extract_hotel(load_fixture("hotel/hampton.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "hotel"
    assert p.cost == 400.00
    assert p.currency == "USD"


def test_hotel_check_in_time_defaults_3pm():
    # Date-only check-in / check-out → 15:00 / 11:00 defaults.
    p = extract_hotel(load_fixture("hotel/airbnb.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.start_datetime is not None
    assert p.start_datetime.hour == 15
    assert p.end_datetime is not None
    assert p.end_datetime.hour == 11


def test_hotel_returns_none_for_flight_confirmation():
    assert extract_hotel(load_fixture("hotel/_negative/united_flight.txt")) is None


def test_hotel_returns_none_for_car_rental():
    assert extract_hotel(load_fixture("hotel/_negative/hertz_rental.txt")) is None


def test_hotel_unknown_vendor_title_falls_back_to_hotel_stay():
    """Hotel with check-in/check-out anchors but no recognizable vendor name
    should still parse, with title='Hotel stay'."""
    text = """
    Booking Confirmation #12345

    Check-in: Saturday, March 7 2026
    Check-out: Sunday, March 8 2026

    Total: $250.00
    """
    p = extract_hotel(text)
    assert p is not None
    assert p.type == "hotel"
    assert p.title == "Hotel stay"
    assert p.vendor is None
    assert p.confidence <= 0.8  # missing vendor → lower than full (4/5 = 0.8)


# ─────────────────────────────  extract_car  ───────────────────────────────


def test_car_hertz_style():
    p = extract_car(load_fixture("car/hertz.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "car"
    assert p.vendor == "Hertz"
    assert p.title == "Hertz car rental"
    assert p.start_datetime == datetime(2026, 6, 14, 10, 0)
    assert p.end_datetime == datetime(2026, 6, 18, 9, 0)
    assert p.location is not None and "LAX Hertz Counter" in p.location
    assert p.cost == 385.00
    assert p.currency == "USD"


def test_car_enterprise_style():
    p = extract_car(load_fixture("car/enterprise.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "car"
    assert p.vendor == "Enterprise"
    assert p.start_datetime == datetime(2026, 7, 22, 14, 0)
    assert p.end_datetime == datetime(2026, 7, 25, 11, 0)
    assert p.location is not None and "Enterprise Downtown San Francisco" in p.location
    assert p.cost == 245.00


def test_car_extracts_pickup_dropoff_times():
    # Hertz fixture has explicit non-default hours (10:00 AM pickup, 9:00 AM return).
    p = extract_car(load_fixture("car/hertz.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.start_datetime is not None
    assert p.end_datetime is not None
    assert p.start_datetime.hour == 10
    assert p.end_datetime.hour == 9


def test_car_returns_none_for_taxi_receipt():
    assert extract_car(load_fixture("car/_negative/taxi.txt")) is None


def test_car_returns_none_for_hotel_confirmation():
    text = load_fixture("car/_negative/hotel.txt")
    assert extract_car(text) is None


# ──────────────────────────  extract_restaurant  ──────────────────────────


def test_restaurant_opentable_style():
    p = extract_restaurant(load_fixture("restaurant/opentable.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "restaurant"
    assert p.vendor == "Eleven Madison Park"
    assert p.title == "Reservation at Eleven Madison Park"
    assert p.start_datetime == datetime(2026, 7, 4, 20, 0)
    assert p.end_datetime is None
    assert p.location is not None and "11 Madison Ave" in p.location
    # 4 required fields all present → confidence 1.0.
    assert p.confidence == 1.0


def test_restaurant_resy_style():
    p = extract_restaurant(load_fixture("restaurant/resy.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "restaurant"
    assert p.vendor == "Le Bernardin"
    assert p.title == "Reservation at Le Bernardin"
    assert p.start_datetime == datetime(2026, 9, 18, 19, 30)
    assert p.end_datetime is None
    assert p.location is not None and "155 W 51st St" in p.location


def test_restaurant_captures_party_size_in_notes():
    p = extract_restaurant(load_fixture("restaurant/opentable.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.notes is not None
    assert "Party of 4" in p.notes


def test_restaurant_returns_none_for_hotel():
    assert extract_restaurant(load_fixture("restaurant/_negative/hotel.txt")) is None

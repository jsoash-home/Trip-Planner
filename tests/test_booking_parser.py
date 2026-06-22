"""Unit tests for src/booking_parser.py — dataclasses + extraction helpers.

Task 1 of paste-and-parse-booking: pure helpers only, no DB / Flask / network.
"""

import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from src.booking_parser import (
    MAX_BOOKINGS_PER_PARSE,
    MAX_PASTE_BYTES,
    MIN_CONFIDENCE,
    ParsedBooking,
    _llm_gates_pass,
    extract_activity,
    extract_car,
    extract_confirmation_number,
    extract_dates,
    extract_flight,
    extract_hotel,
    extract_money,
    extract_other,
    extract_restaurant,
    extract_transport,
    extract_url,
    parse_booking_email,
    parse_rules,
    parse_with_llm,
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


def test_restaurant_unknown_vendor_title_falls_back():
    """A reservation paste with `Reservation:` anchor but no recognizable
    `at <X>` should still parse, with title='Restaurant reservation'."""
    text = """Reservation: confirmed for Saturday, March 7 2026 at 7:30 PM
Party of 2

Confirmation: RSV-99001
"""
    p = extract_restaurant(text)
    assert p is not None
    assert p.type == "restaurant"
    assert p.title == "Restaurant reservation"
    assert p.vendor is None


# ──────────────────────────  extract_activity  ──────────────────────────────


def test_activity_viator_tour():
    p = extract_activity(load_fixture("activity/viator.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "activity"
    assert "Louvre" in p.title
    assert p.start_datetime == datetime(2026, 8, 14, 10, 30)
    assert p.end_datetime is None
    assert p.cost == 89.00
    assert p.currency == "EUR"


def test_activity_eventbrite_concert():
    p = extract_activity(load_fixture("activity/eventbrite.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "activity"
    assert "Beyoncé" in p.title or "Renaissance" in p.title
    assert p.start_datetime == datetime(2026, 7, 19, 20, 0)
    assert p.location is not None and "Madison Square Garden" in p.location
    assert p.cost == 549.00
    assert p.currency == "USD"


def test_activity_museum_tickets():
    # Date-only fixture — exercises "no default hour" rule.
    p = extract_activity(load_fixture("activity/museum.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "activity"
    # Title should fall back to first-line "The Metropolitan Museum of Art".
    assert "Metropolitan" in p.title
    assert p.start_datetime == datetime(2026, 10, 8, 0, 0)
    assert p.location is not None and "1000 Fifth Ave" in p.location
    assert p.cost == 60.00


def test_activity_returns_none_for_flight():
    assert extract_activity(load_fixture("activity/_negative/flight.txt")) is None


def test_activity_refundable_until_does_not_set_end_datetime():
    """Task 6 cleanup: 'Refundable until <date>' is refund policy, not end time."""
    text = """Eventbrite

Your tickets for: Beyoncé — Renaissance World Tour
Sunday, July 19 2026 at 8:00 PM

Venue: Madison Square Garden, 4 Pennsylvania Plaza, New York, NY 10001
Refundable until July 17 2026 at 11:59 PM

Order #: EB-7172-RWT
Total: $549.00
"""
    p = extract_activity(text)
    assert isinstance(p, ParsedBooking)
    assert p.start_datetime == datetime(2026, 7, 19, 20, 0)
    assert p.end_datetime is None


def test_activity_tickets_for_title_stops_at_venue():
    """Task 6 cleanup: 'Tickets for: <Event> at <Venue>' — title is just the event,
    venue stays in location."""
    text = """Ticketmaster

Tickets for: Beyoncé at Madison Square Garden
Sunday, July 19 2026 at 8:00 PM
Venue: Madison Square Garden, 4 Pennsylvania Plaza, New York, NY 10001

Order #: TM-9000
Total: $300.00
"""
    p = extract_activity(text)
    assert isinstance(p, ParsedBooking)
    assert p.title == "Beyoncé"
    assert p.location is not None and "Madison Square Garden" in p.location


# ──────────────────────────  extract_transport  ──────────────────────────────


def test_transport_amtrak_style():
    p = extract_transport(load_fixture("transport/amtrak.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "transport"
    assert p.vendor == "Amtrak"
    assert p.title == "Amtrak: New York Penn Station → Washington Union Station"
    assert p.start_datetime == datetime(2026, 6, 11, 7, 0)
    assert p.end_datetime == datetime(2026, 6, 11, 10, 25)
    assert p.location == "New York Penn Station"
    assert p.cost == 89.00
    assert p.currency == "USD"
    assert p.confirmation_number == "AMT-7721-NER"
    assert p.confidence >= 0.8


def test_transport_eurostar_style():
    p = extract_transport(load_fixture("transport/eurostar.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "transport"
    assert p.vendor == "Eurostar"
    assert p.title == "Eurostar: London St Pancras → Paris Gare du Nord"
    assert p.start_datetime == datetime(2026, 8, 15, 11, 31)
    assert p.end_datetime == datetime(2026, 8, 15, 14, 47)
    assert p.location == "London St Pancras"
    assert p.cost == 320.00
    assert p.currency == "GBP"


def test_transport_ferry_style():
    p = extract_transport(load_fixture("transport/ferry.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "transport"
    assert p.vendor == "Stena Line"
    assert p.title == "Stena Line: Harwich → Hook of Holland"
    assert p.start_datetime == datetime(2026, 7, 5, 21, 0)
    assert p.end_datetime == datetime(2026, 7, 6, 7, 45)
    assert p.location == "Harwich"
    assert p.cost == 285.00
    assert p.currency == "EUR"


def test_transport_returns_none_for_flight_with_iata():
    assert extract_transport(load_fixture("transport/_negative/united_flight.txt")) is None


def test_transport_returns_none_for_hotel_confirmation():
    assert extract_transport(load_fixture("transport/_negative/hotel.txt")) is None


# ──────────────────────────  extract_other  ──────────────────────────────────


def test_other_generic_confirmation_captures_title_and_date():
    p = extract_other(load_fixture("other/generic.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.type == "other"
    assert p.title == "Your booking is confirmed!"
    assert p.start_datetime == datetime(2026, 8, 19, 0, 0)
    assert p.confirmation_number == "BK-99214"
    assert p.cost == 125.00
    assert p.currency == "USD"
    assert p.url == "https://example.com/booking/BK-99214"


def test_other_returns_none_for_truly_empty_text():
    assert extract_other("\n\n   \n") is None


def test_other_confidence_capped_at_half():
    p = extract_other(load_fixture("other/spa.txt"))
    assert isinstance(p, ParsedBooking)
    assert p.confidence <= 0.5


# ──────────────────────────  parse_rules  ───────────────────────────────────


def test_parse_rules_one_flight_returns_one_booking():
    # The united_single fixture is unambiguously a flight email. The flight
    # extractor must produce exactly one segment for it, and the catch-all
    # `other` result must be suppressed when a typed extractor matched —
    # otherwise the UI flow routes to the multi-booking review screen.
    result = parse_rules(load_fixture("flight/united_single.txt"))
    assert len(result) == 1
    assert result[0].type == "flight"


def test_parse_rules_other_only_when_no_typed_extractor_matches():
    """The catch-all extractor should not pollute results when a real
    type extractor (flight/hotel/etc.) already matched."""
    text = load_fixture("flight/united_single.txt")
    result = parse_rules(text)
    types = {b.type for b in result}
    assert "flight" in types
    assert "other" not in types


def test_parse_rules_returns_other_when_only_generic_signals_present():
    """When nothing typed matches but dates/money/conf are present,
    parse_rules should still return the other-extractor result."""
    text = load_fixture("other/generic.txt")
    result = parse_rules(text)
    assert len(result) == 1
    assert result[0].type == "other"


def test_parse_rules_round_trip_returns_two_bookings():
    bookings = parse_rules(load_fixture("flight/round_trip.txt"))
    flights = [b for b in bookings if b.type == "flight"]
    assert len(flights) == 2
    # Sorted by start_datetime ascending (within equal confidence).
    assert flights[0].start_datetime == datetime(2026, 9, 21, 16, 15)
    assert flights[1].start_datetime == datetime(2026, 10, 5, 14, 0)


def test_parse_rules_garbage_text_returns_empty():
    assert parse_rules("hello world this is not a booking") == []


def test_parse_rules_drops_low_confidence_results():
    # Every returned booking must clear the MIN_CONFIDENCE threshold. Use a
    # flight fixture (high-confidence path) and assert the filter contract
    # holds for every entry returned.
    bookings = parse_rules(load_fixture("flight/united_single.txt"))
    assert bookings, "expected at least one booking"
    for b in bookings:
        assert b.confidence >= MIN_CONFIDENCE


def test_parse_rules_caps_at_max_bookings():
    # Synthetic text with many IATA pairs — the flight extractor will fan
    # them out into many segments. parse_rules must cap the returned list.
    text = "\n".join(
        f"Flight UA {100 + i}\nSFO → JFK\n" for i in range(8)
    )
    bookings = parse_rules(text)
    assert len(bookings) <= MAX_BOOKINGS_PER_PARSE


def test_parse_rules_flight_wins_over_other_fallback():
    # The united_single.txt fixture has flight + dates + money, so
    # extract_other ALSO fires internally. parse_rules suppresses the
    # catch-all `other` whenever any typed extractor matched, so the
    # returned list should lead with flight (and not contain other).
    bookings = parse_rules(load_fixture("flight/united_single.txt"))
    assert bookings, "expected at least one booking"
    assert bookings[0].type == "flight"


# ──────────────────────  _llm_gates_pass / parse_with_llm  ──────────────────


def _install_fake_anthropic(monkeypatch, parse_return=None, parse_raises=None):
    """Inject a fake `anthropic` module with an Anthropic class whose
    client.messages.parse() returns or raises whatever the test wants.

    Returns the FakeAnthropic class so tests can assert call shape if needed.
    """
    fake_module = types.ModuleType("anthropic")

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = MagicMock()
            if parse_raises is not None:
                self.messages.parse = MagicMock(side_effect=parse_raises)
            else:
                self.messages.parse = MagicMock(return_value=parse_return)

    fake_module.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    return FakeAnthropic


def test_llm_gates_pass_false_when_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PASTE_PARSER_LLM_ENABLED", "1")
    assert _llm_gates_pass() is False


def test_llm_gates_pass_false_when_flag_unset(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("PASTE_PARSER_LLM_ENABLED", raising=False)
    assert _llm_gates_pass() is False


def test_llm_gates_pass_false_when_sdk_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PASTE_PARSER_LLM_ENABLED", "1")
    # Force `import anthropic` to fail by stubbing the module to None.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert _llm_gates_pass() is False


def test_llm_gates_pass_true_when_all_three_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PASTE_PARSER_LLM_ENABLED", "1")
    # Inject a fake anthropic module so the import succeeds without the real SDK.
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    assert _llm_gates_pass() is True


def test_parse_with_llm_returns_empty_when_gates_off(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert parse_with_llm("anything") == []


def test_parse_with_llm_returns_bookings_when_mocked(monkeypatch):
    # Bypass the env-var gate; the gate only checks env + import-ability.
    monkeypatch.setattr("src.booking_parser._llm_gates_pass", lambda: True)

    # Build a fake parsed_output that mirrors what client.messages.parse()
    # returns: a BatchedParsedBookings-shaped object with a `bookings` list.
    fake_booking = MagicMock()
    fake_booking.type = "flight"
    fake_booking.title = "Test flight"
    fake_booking.vendor = None
    fake_booking.confirmation_number = None
    fake_booking.start_datetime = "2026-08-17T14:30:00"
    fake_booking.end_datetime = None
    fake_booking.location = None
    fake_booking.cost = None
    fake_booking.currency = None
    fake_booking.url = None
    fake_booking.notes = None

    fake_response = MagicMock()
    fake_response.parsed_output = MagicMock(bookings=[fake_booking])

    _install_fake_anthropic(monkeypatch, parse_return=fake_response)

    result = parse_with_llm("anything")
    assert len(result) == 1
    booking = result[0]
    assert booking.type == "flight"
    assert booking.title == "Test flight"
    assert booking.start_datetime == datetime(2026, 8, 17, 14, 30)
    assert booking.confidence == 1.0
    assert booking.source == "llm"


def test_parse_with_llm_returns_empty_on_api_error(monkeypatch):
    monkeypatch.setattr("src.booking_parser._llm_gates_pass", lambda: True)
    _install_fake_anthropic(monkeypatch, parse_raises=RuntimeError("boom"))
    assert parse_with_llm("anything") == []


def test_parse_with_llm_handles_invalid_datetime(monkeypatch):
    monkeypatch.setattr("src.booking_parser._llm_gates_pass", lambda: True)

    fake_booking = MagicMock()
    fake_booking.type = "flight"
    fake_booking.title = "Test flight"
    fake_booking.vendor = None
    fake_booking.confirmation_number = None
    fake_booking.start_datetime = "not-a-date"
    fake_booking.end_datetime = None
    fake_booking.location = None
    fake_booking.cost = None
    fake_booking.currency = None
    fake_booking.url = None
    fake_booking.notes = None

    fake_response = MagicMock()
    fake_response.parsed_output = MagicMock(bookings=[fake_booking])

    _install_fake_anthropic(monkeypatch, parse_return=fake_response)

    result = parse_with_llm("anything")
    assert len(result) == 1
    assert result[0].start_datetime is None


# ─────────────────────────  parse_booking_email  ──────────────────────────


def test_parse_booking_email_rules_path():
    # Real flight fixture — rules path matches and short-circuits before LLM.
    result = parse_booking_email(load_fixture("flight/united_single.txt"))
    assert result.source == "rules"
    assert len(result.bookings) == 1
    assert result.bookings[0].type == "flight"


def test_parse_booking_email_llm_path(monkeypatch):
    # Force rules to return nothing, gates to pass, LLM to return one booking.
    monkeypatch.setattr("src.booking_parser.parse_rules", lambda text: [])
    monkeypatch.setattr("src.booking_parser._llm_gates_pass", lambda: True)
    fake_booking = ParsedBooking(
        type="flight",
        title="Test flight",
        confidence=1.0,
        source="llm",
    )
    monkeypatch.setattr(
        "src.booking_parser.parse_with_llm", lambda text: [fake_booking]
    )

    result = parse_booking_email("anything")
    assert result.source == "llm"
    assert len(result.bookings) == 1


def test_parse_booking_email_none_path(monkeypatch):
    # Gates off → no LLM. Garbage input → rules also returns []. Notes set.
    monkeypatch.setattr("src.booking_parser._llm_gates_pass", lambda: False)
    result = parse_booking_email("hello this is not a booking")
    assert result.source == "none"
    assert result.bookings == []
    assert result.notes.startswith("Couldn't extract")


def test_parse_booking_email_truncates_huge_input(monkeypatch):
    # Stuff > MAX_PASTE_BYTES into the front so the real fixture is past the
    # cap. parse_rules should receive a string whose UTF-8 byte length is
    # ≤ MAX_PASTE_BYTES.
    seen_lengths = []

    def fake_parse_rules(text):
        seen_lengths.append(len(text.encode("utf-8")))
        return []

    monkeypatch.setattr("src.booking_parser.parse_rules", fake_parse_rules)
    monkeypatch.setattr("src.booking_parser._llm_gates_pass", lambda: False)

    huge = "x" * (MAX_PASTE_BYTES + 1000) + load_fixture("flight/united_single.txt")
    parse_booking_email(huge)

    assert len(seen_lengths) == 1
    assert seen_lengths[0] <= MAX_PASTE_BYTES


def test_parse_booking_email_empty_string_returns_none_source(monkeypatch):
    monkeypatch.setattr("src.booking_parser._llm_gates_pass", lambda: False)
    result = parse_booking_email("")
    assert result.source == "none"
    assert result.bookings == []

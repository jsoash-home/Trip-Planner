"""Tests for src/ical_feed.py — the iCal calendar-feed builder."""

import re
from datetime import date, datetime, time, timedelta

import pytest

from app import app as flask_app
from models import Booking, ItineraryItem, Trip, TripCollaborator, User, db
from src import ical_feed


@pytest.fixture
def app():
    """Fresh in-memory DB per test. Mirrors tests/test_routes.py."""
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def owner(app):
    u = User(google_id="g-ical", email="owner@example.com", name="Owner")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def trip(app, owner):
    t = Trip(owner_id=owner.id, name="Paris trip",
             start_date=date(2026, 8, 10), end_date=date(2026, 8, 15))
    db.session.add(t)
    db.session.commit()
    return t


# ─── event_from_itinerary ────────────────────────────────────────────────────


def test_all_day_item_emits_date_only(app, trip):
    """An item with only day_date becomes an all-day (VALUE=DATE) VEVENT."""
    item = ItineraryItem(
        trip_id=trip.id, day_date=date(2026, 8, 11), title="Louvre",
    )
    db.session.add(item)
    db.session.commit()

    ev = ical_feed.event_from_itinerary(item)
    assert ev is not None

    # An all-day event's DTSTART is a plain date, not a datetime.
    dtstart = ev["dtstart"].dt
    assert isinstance(dtstart, date) and not isinstance(dtstart, datetime)
    assert dtstart == date(2026, 8, 11)

    # DTEND is exclusive → next day for a one-day all-day event.
    dtend = ev["dtend"].dt
    assert dtend == date(2026, 8, 12)

    # And when serialized, the property carries VALUE=DATE.
    ics = ev.to_ical().decode("utf-8")
    assert "DTSTART;VALUE=DATE:20260811" in ics
    assert "DTEND;VALUE=DATE:20260812" in ics


def test_timed_item_emits_dtstart_dtend(app, trip):
    """Both start_time and end_time set → timed VEVENT with datetime pair."""
    item = ItineraryItem(
        trip_id=trip.id,
        day_date=date(2026, 8, 11),
        start_time=time(19, 0),
        end_time=time(21, 30),
        title="Dinner reservation",
        location="Le Comptoir",
        notes="Ask for terrace seat",
    )
    db.session.add(item)
    db.session.commit()

    ev = ical_feed.event_from_itinerary(item)
    assert ev is not None

    dtstart = ev["dtstart"].dt
    dtend = ev["dtend"].dt
    assert dtstart == datetime(2026, 8, 11, 19, 0)
    assert dtend == datetime(2026, 8, 11, 21, 30)
    # Floating — no tzinfo on either end.
    assert dtstart.tzinfo is None
    assert dtend.tzinfo is None

    assert str(ev["location"]) == "Le Comptoir"
    assert str(ev["description"]) == "Ask for terrace seat"


# ─── event_from_booking ──────────────────────────────────────────────────────


def test_untimed_flight_returns_none(app, trip):
    """A flight missing either datetime → no VEVENT."""
    flight = Booking(
        trip_id=trip.id, type="flight", title="UA101",
        start_datetime=None, end_datetime=None,
    )
    db.session.add(flight)
    db.session.commit()

    assert ical_feed.event_from_booking(flight) is None

    # And with only one side set — still None.
    flight.start_datetime = datetime(2026, 8, 10, 6, 0)
    db.session.commit()
    assert ical_feed.event_from_booking(flight) is None


def test_flight_with_both_datetimes_emits_event(app, trip):
    """A flight with start + end datetimes → floating timed VEVENT."""
    flight = Booking(
        trip_id=trip.id, type="flight", title="UA101 SFO→CDG",
        start_datetime=datetime(2026, 8, 10, 18, 0),
        end_datetime=datetime(2026, 8, 11, 13, 30),
    )
    db.session.add(flight)
    db.session.commit()

    ev = ical_feed.event_from_booking(flight)
    assert ev is not None
    assert ev["dtstart"].dt == datetime(2026, 8, 10, 18, 0)
    assert ev["dtend"].dt == datetime(2026, 8, 11, 13, 30)
    assert ev["dtstart"].dt.tzinfo is None


def test_hotel_emits_multi_day_event(app, trip):
    """A hotel booking is a single VEVENT spanning check-in → check-out."""
    hotel = Booking(
        trip_id=trip.id, type="hotel", title="Hôtel Lutetia",
        start_datetime=datetime(2026, 8, 11, 15, 0),
        end_datetime=datetime(2026, 8, 14, 11, 0),
    )
    db.session.add(hotel)
    db.session.commit()

    ev = ical_feed.event_from_booking(hotel)
    assert ev is not None
    assert ev["dtstart"].dt == datetime(2026, 8, 11, 15, 0)
    assert ev["dtend"].dt == datetime(2026, 8, 14, 11, 0)
    # Same span crosses multiple calendar days — single event, not one per night.
    span = ev["dtend"].dt - ev["dtstart"].dt
    assert span > timedelta(days=2)


# ─── summary + uid ───────────────────────────────────────────────────────────


def test_summary_prefixes_trip_name(app, trip):
    """SUMMARY is '<trip name>: <title>' so calendar picks read well."""
    item = ItineraryItem(
        trip_id=trip.id, day_date=date(2026, 8, 11), title="Louvre",
    )
    db.session.add(item)
    db.session.commit()

    ev = ical_feed.event_from_itinerary(item)
    assert str(ev["summary"]) == "Paris trip: Louvre"

    flight = Booking(
        trip_id=trip.id, type="flight", title="UA101",
        start_datetime=datetime(2026, 8, 10, 18, 0),
        end_datetime=datetime(2026, 8, 11, 13, 30),
    )
    db.session.add(flight)
    db.session.commit()

    ev2 = ical_feed.event_from_booking(flight)
    assert str(ev2["summary"]) == "Paris trip: UA101"


def test_uid_stable_across_calls(app, trip):
    """Regenerating an event for the same row produces the same UID."""
    item = ItineraryItem(
        trip_id=trip.id, day_date=date(2026, 8, 11), title="Louvre",
    )
    db.session.add(item)
    db.session.commit()

    uid1 = str(ical_feed.event_from_itinerary(item)["uid"])
    uid2 = str(ical_feed.event_from_itinerary(item)["uid"])
    assert uid1 == uid2
    assert uid1.endswith("@vacation-planner.local")
    assert uid1 == f"{trip.id}-itinerary-{item.id}@vacation-planner.local"

    flight = Booking(
        trip_id=trip.id, type="flight", title="UA101",
        start_datetime=datetime(2026, 8, 10, 18, 0),
        end_datetime=datetime(2026, 8, 11, 13, 30),
    )
    db.session.add(flight)
    db.session.commit()

    fuid = str(ical_feed.event_from_booking(flight)["uid"])
    assert fuid == f"{trip.id}-flight-{flight.id}@vacation-planner.local"


# ─── token helpers ───────────────────────────────────────────────────────────


def test_generate_token_is_urlsafe_and_unique():
    """generate_token returns urlsafe base64 and doesn't collide."""
    t1 = ical_feed.generate_token()
    t2 = ical_feed.generate_token()

    # urlsafe base64 alphabet: A-Z, a-z, 0-9, -, _
    assert re.match(r"^[A-Za-z0-9_-]+$", t1)
    assert re.match(r"^[A-Za-z0-9_-]+$", t2)
    # secrets.token_urlsafe(24) → 32 chars.
    assert len(t1) == 32
    assert len(t2) == 32
    # Two consecutive calls differ.
    assert t1 != t2


def test_user_by_token_returns_none_for_empty_or_missing(app, owner):
    assert ical_feed.user_by_token("") is None
    assert ical_feed.user_by_token("no-such-token") is None
    owner.ical_token = "abc123"
    db.session.commit()
    found = ical_feed.user_by_token("abc123")
    assert found is not None
    assert found.id == owner.id


# ─── build_feed ──────────────────────────────────────────────────────────────


def test_build_feed_includes_owned_and_collaborator_trips(app, owner):
    """A user's feed contains events from trips they own AND trips shared with them."""
    other = User(google_id="g-other", email="other@example.com", name="Other")
    db.session.add(other)
    db.session.commit()

    owned = Trip(owner_id=owner.id, name="Owned",
                 start_date=date(2026, 8, 10), end_date=date(2026, 8, 15))
    shared = Trip(owner_id=other.id, name="Shared",
                  start_date=date(2026, 9, 1), end_date=date(2026, 9, 5))
    db.session.add_all([owned, shared])
    db.session.commit()

    db.session.add(TripCollaborator(
        trip_id=shared.id, email="owner@example.com", role="viewer"))
    db.session.add(ItineraryItem(
        trip_id=owned.id, day_date=date(2026, 8, 11), title="Owned event"))
    db.session.add(ItineraryItem(
        trip_id=shared.id, day_date=date(2026, 9, 2), title="Shared event"))
    db.session.commit()

    ics = ical_feed.build_feed(owner, datetime(2026, 7, 8, 12, 0)).decode()
    assert "Owned event" in ics
    assert "Shared event" in ics


def test_build_feed_dedupes_when_owner_is_also_collaborator(app, owner, trip):
    """Owner who also has a TripCollaborator row on their own trip
    should see each event once, not twice."""
    db.session.add(TripCollaborator(
        trip_id=trip.id, email="owner@example.com", role="editor"))
    db.session.add(ItineraryItem(
        trip_id=trip.id, day_date=date(2026, 8, 11), title="Louvre"))
    db.session.commit()

    ics = ical_feed.build_feed(owner, datetime(2026, 7, 8, 12, 0)).decode()
    # The itinerary item should appear exactly once, not duplicated because
    # the owner also matches the collaborator email filter.
    assert ics.count("Louvre") == 1

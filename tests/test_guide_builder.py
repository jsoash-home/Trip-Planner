"""Tests for src/guide_builder."""

from datetime import date, datetime, time

import pytest

from app import app as flask_app
from models import Booking, ItineraryItem, Trip, TripCollaborator, User, db
from src.guide_builder import TripNotFound, load_trip_data


def test_module_imports():
    from src import guide_builder  # noqa: F401


# ─── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def owner(app):
    u = User(google_id="g_guide", email="guide_owner@example.com", name="Guide Owner")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def trip(app, owner):
    t = Trip(
        owner_id=owner.id,
        name="Rome 2026",
        destination="Rome, Italy",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
        status="planning",
        cover_emoji="✈️",
    )
    db.session.add(t)
    db.session.commit()
    return t


# ─── tests ─────────────────────────────────────────────────────────────────


def test_load_trip_data_happy_path(app, trip):
    """Seed Trip + 2 Bookings + 4 ItineraryItems; assert shape and counts."""
    b1 = Booking(trip_id=trip.id, type="hotel", title="Hotel Roma", vendor="Hotel Roma",
                 start_datetime=datetime(2026, 7, 1, 14, 0),
                 end_datetime=datetime(2026, 7, 4, 11, 0))
    b2 = Booking(trip_id=trip.id, type="activity", title="Colosseum tour",
                 start_datetime=datetime(2026, 7, 2, 9, 0))
    db.session.add_all([b1, b2])
    db.session.commit()

    db.session.add_all([
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 1),
                      title="Check in: Hotel Roma", category="other",
                      linked_booking_id=b1.id),
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 2),
                      title="Colosseum tour", category="sightseeing",
                      start_time=time(9, 0), linked_booking_id=b2.id),
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 3),
                      title="Vatican Museums", category="sightseeing",
                      start_time=time(10, 0)),
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 4),
                      title="Check out: Hotel Roma", category="other",
                      linked_booking_id=b1.id),
    ])
    db.session.commit()

    result = load_trip_data(trip.id)

    assert set(result.keys()) == {"trip", "bookings", "itinerary", "collaborators"}

    t = result["trip"]
    assert t["id"] == trip.id
    assert t["title"] == "Rome 2026"
    assert t["destination"] == "Rome, Italy"
    assert t["start_date"] == "2026-07-01"
    assert t["end_date"] == "2026-07-05"
    assert t["status"] == "planning"
    assert t["emoji_theme"] is not None  # ✈️ maps to a theme phrase

    assert len(result["bookings"]) == 2
    assert len(result["itinerary"]) == 4
    assert result["collaborators"] == []


def test_load_trip_data_raises_trip_not_found(app):
    """Unknown trip_id raises TripNotFound."""
    with pytest.raises(TripNotFound):
        load_trip_data(999999)


def test_load_trip_data_itinerary_sorted_by_day_then_time(app, trip):
    """Items are returned chronologically regardless of insert order."""
    # Insert in reverse day order, with varying times within days
    db.session.add_all([
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 3),
                      title="Day 3 afternoon", category="other",
                      start_time=time(14, 0)),
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 1),
                      title="Day 1 morning", category="other",
                      start_time=time(9, 0)),
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 2),
                      title="Day 2 untimed", category="other"),
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 1),
                      title="Day 1 untimed", category="other"),
        ItineraryItem(trip_id=trip.id, day_date=date(2026, 7, 2),
                      title="Day 2 morning", category="other",
                      start_time=time(8, 30)),
    ])
    db.session.commit()

    itinerary = load_trip_data(trip.id)["itinerary"]

    titles = [i["title"] for i in itinerary]
    dates = [i["day_date"] for i in itinerary]

    # All day 1 items come before day 2 items, which come before day 3
    assert dates.index("2026-07-01") < dates.index("2026-07-02")
    assert dates.index("2026-07-02") < dates.index("2026-07-03")

    # Within day 1: untimed first, then timed (sort_within_day rule)
    day1 = [i for i in itinerary if i["day_date"] == "2026-07-01"]
    assert day1[0]["title"] == "Day 1 untimed"
    assert day1[1]["title"] == "Day 1 morning"

    # Within day 2: untimed first, then timed
    day2 = [i for i in itinerary if i["day_date"] == "2026-07-02"]
    assert day2[0]["title"] == "Day 2 untimed"
    assert day2[1]["title"] == "Day 2 morning"


def test_load_trip_data_bookings_include_linked_itinerary_ids(app, trip):
    """A flight booking linked to Depart + Arrive items lists both item ids."""
    flight = Booking(trip_id=trip.id, type="flight", title="UA 101",
                     start_datetime=datetime(2026, 7, 1, 8, 0),
                     end_datetime=datetime(2026, 7, 1, 12, 0))
    db.session.add(flight)
    db.session.commit()

    depart = ItineraryItem(trip_id=trip.id, linked_booking_id=flight.id,
                           auto_kind="depart", day_date=date(2026, 7, 1),
                           title="Depart UA 101", category="transit")
    arrive = ItineraryItem(trip_id=trip.id, linked_booking_id=flight.id,
                           auto_kind="arrive", day_date=date(2026, 7, 1),
                           title="Arrive UA 101", category="transit",
                           start_time=time(12, 0))
    db.session.add_all([depart, arrive])
    db.session.commit()

    result = load_trip_data(trip.id)
    booking_dict = result["bookings"][0]

    assert booking_dict["id"] == flight.id
    assert sorted(booking_dict["linked_itinerary_ids"]) == sorted([depart.id, arrive.id])


def test_load_trip_data_no_collaborators_returns_empty_list(app, trip):
    """A solo trip with no collaborators returns collaborators == []."""
    result = load_trip_data(trip.id)
    assert result["collaborators"] == []


def test_load_trip_data_with_collaborator_returns_role(app, trip):
    """A viewer collaborator appears in the collaborators list with role 'viewer'."""
    collab = TripCollaborator(trip_id=trip.id, email="friend@example.com", role="viewer")
    db.session.add(collab)
    db.session.commit()

    result = load_trip_data(trip.id)
    assert result["collaborators"] == [{"email": "friend@example.com", "role": "viewer"}]

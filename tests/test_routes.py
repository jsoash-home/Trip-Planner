"""Integration tests — exercise routes + DB end-to-end with an
in-memory SQLite database. Uses Flask's test_client and a fresh DB
per test via a pytest fixture."""

from datetime import date, datetime

import pytest

from app import app as flask_app
from models import Booking, ItineraryItem, Trip, User, db


@pytest.fixture
def app():
    """Bind the app to an in-memory SQLite DB for this test."""
    flask_app.config["TESTING"] = True
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def owner(app):
    u = User(google_id="g1", email="owner@example.com", name="Owner")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def trip(app, owner):
    t = Trip(owner_id=owner.id, name="Test trip",
             start_date=date(2026, 6, 1), end_date=date(2026, 6, 10))
    db.session.add(t)
    db.session.commit()
    return t


def test_delete_booking_cascades_linked_items(app, trip):
    """Deleting a booking removes its auto-linked itinerary items."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()

    db.session.add_all([
        ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="depart", day_date=date(2026, 6, 1),
                      title="Depart UA"),
        ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="arrive", day_date=date(2026, 6, 1),
                      title="Arrive UA"),
        # A stand-alone item with no linked_booking — should survive.
        ItineraryItem(trip_id=trip.id, linked_booking_id=None,
                      day_date=date(2026, 6, 1), title="Coffee"),
    ])
    db.session.commit()

    assert ItineraryItem.query.filter_by(trip_id=trip.id).count() == 3

    db.session.delete(b)
    db.session.commit()

    remaining = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    assert len(remaining) == 1
    assert remaining[0].title == "Coffee"
    assert db.session.get(Booking, b.id) is None


def test_itinerary_edit_marks_customized(app, trip, owner):
    """Editing a linked itinerary item flips customized_by_user to True."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 2, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="check_in", day_date=date(2026, 6, 2),
                         title="Check in: Hilton", category="other")
    db.session.add(item)
    db.session.commit()
    assert item.customized_by_user is False

    with flask_app.test_client() as client:
        # Bypass login by stuffing the session.
        with client.session_transaction() as sess:
            sess["_user_id"] = str(owner.id)
            sess["_fresh"] = True
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{item.id}/edit",
            data={
                "title": "Check in: Hilton (front desk)",
                "category": "other",
                "day_date": "2026-06-02",
                "start_time": "15:00",
                "end_time": "",
                "location": "",
                "notes": "",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.customized_by_user is True
    assert item.title == "Check in: Hilton (front desk)"


def _make_flight_with_arrive(trip):
    """Helper: make a flight booking + its 'arrive' linked item (already drifted).

    The item's title is intentionally stale ('Arrive Delta') so resync
    has something to do.
    """
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta",  # stale — booking now says United
                         category="transit")
    db.session.add(item)
    db.session.commit()
    return b, item


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_resync_updates_fields_from_booking(app, trip, owner):
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.title == "Arrive United"
    assert item.customized_by_user is False


def test_keep_mine_marks_customized(app, trip, owner):
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/keep-mine")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.customized_by_user is True
    assert item.title == "Arrive Delta"  # unchanged


def test_unlink_clears_linked_booking(app, trip, owner):
    b, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/unlink")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.linked_booking_id is None
    assert item.auto_kind is None
    # The booking still exists.
    assert db.session.get(Booking, b.id) is not None

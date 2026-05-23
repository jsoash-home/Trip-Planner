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

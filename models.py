"""
models.py

SQLAlchemy tables for the Vacation Planner.

Step 8 state — six tables:

  - User             one row per Google account
  - Trip             one row per planned vacation, owned by a User
  - Booking          one row per flight / hotel / car / etc. on a trip
  - ItineraryItem    one row per scheduled activity on a trip day
  - PackingItem      one row per packing-list item on a trip
  - TripCollaborator one row per (trip, email) sharing entry
"""

from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """A logged-in person. Created on first Google OAuth sign-in."""

    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String, unique=True, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    name = db.Column(db.String, nullable=False)
    avatar_url = db.Column(db.String, nullable=True)

    trips = db.relationship("Trip", backref="owner", lazy=True)


class Trip(db.Model):
    """A single planned (or completed) vacation."""

    __tablename__ = "trip"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(300), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    # status stored as a string so it can be overridden by the user, even though
    # we mostly derive it from today vs. start_date / end_date.
    # Allowed values: "planning", "booked", "in_progress", "completed".
    status = db.Column(db.String(20), nullable=False, default="planning")

    cover_emoji = db.Column(db.String(10), nullable=True)
    primary_currency = db.Column(db.String(3), nullable=False, default="USD")
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    bookings = db.relationship(
        "Booking",
        backref="trip",
        lazy=True,
        cascade="all, delete-orphan",
    )
    itinerary_items = db.relationship(
        "ItineraryItem",
        backref="trip",
        lazy=True,
        cascade="all, delete-orphan",
    )
    packing_items = db.relationship(
        "PackingItem",
        backref="trip",
        lazy=True,
        cascade="all, delete-orphan",
    )
    collaborators = db.relationship(
        "TripCollaborator",
        backref="trip",
        lazy=True,
        cascade="all, delete-orphan",
    )


class Booking(db.Model):
    """
    A single reservation on a trip — flight, hotel, car, restaurant,
    activity, transport, or other.

    Costs are stored as Float for v1 simplicity. Sub-cent rounding is
    fine for budget rollups; revisit with Numeric(10, 2) if precision
    becomes important.
    """

    __tablename__ = "booking"

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)

    # One of: flight, hotel, car, activity, restaurant, transport, other
    type = db.Column(db.String(20), nullable=False, default="other")

    title = db.Column(db.String(300), nullable=False)
    vendor = db.Column(db.String(200), nullable=True)
    confirmation_number = db.Column(db.String(120), nullable=True)

    # Naive datetimes — the user enters local time; we don't translate timezones in v1.
    start_datetime = db.Column(db.DateTime, nullable=True)
    end_datetime = db.Column(db.DateTime, nullable=True)

    location = db.Column(db.String(300), nullable=True)
    cost = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="USD")

    url = db.Column(db.String(500), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # When a booking is deleted, its auto-linked itinerary items go with it.
    # We don't use delete-orphan because linked_booking_id is nullable —
    # an item being un-linked (set to NULL) shouldn't trigger deletion.
    itinerary_items = db.relationship(
        "ItineraryItem",
        backref="linked_booking",
        lazy=True,
        cascade="save-update, merge, delete",
    )


class ItineraryItem(db.Model):
    """
    A single scheduled activity on a trip day.

    Time is stored as date + time (not a single datetime) so an item can
    be "anytime that day" — a None start_time means the user hasn't
    pinned it to a specific time. The day column groups by `day_date`
    regardless.
    """

    __tablename__ = "itinerary_item"

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)

    day_date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)

    title = db.Column(db.String(300), nullable=False)
    # One of: sightseeing, meal, transit, break, other
    category = db.Column(db.String(20), nullable=False, default="other")
    location = db.Column(db.String(300), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Sort order for items at the same time / untimed items on the same day.
    order_within_day = db.Column(db.Integer, nullable=False, default=0)

    # Populated when an itinerary entry is auto-created from a Booking
    # (e.g. hotel check-in). NULL means a stand-alone item.
    linked_booking_id = db.Column(
        db.Integer, db.ForeignKey("booking.id"), nullable=True, index=True
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PackingItem(db.Model):
    """A single thing on the packing list for a trip."""

    __tablename__ = "packing_item"

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    # One of: clothing, electronics, documents, toiletries, other
    category = db.Column(db.String(20), nullable=False, default="other")
    packed = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TripCollaborator(db.Model):
    """
    A person — by Google email address — who can see (and optionally edit)
    a trip they don't own.

    We key by email rather than user_id so the owner can invite people who
    haven't logged in yet. The first time that person signs in with this
    Google address, the trip just appears on their dashboard. There is no
    invite-token / email-sending dance in v1.

    The (trip_id, email) pair is unique — one role per (trip, email).
    """

    __tablename__ = "trip_collaborator"
    __table_args__ = (
        db.UniqueConstraint("trip_id", "email", name="uq_trip_collaborator_trip_email"),
    )

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)

    # Always stored lowercase + stripped. See sharing.normalize_email().
    email = db.Column(db.String(254), nullable=False, index=True)

    # Either "viewer" (read-only) or "editor" (can add / change / remove
    # bookings, itinerary items, and packing items). The trip owner role
    # is always implicit via Trip.owner_id and never stored here.
    role = db.Column(db.String(20), nullable=False, default="viewer")

    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

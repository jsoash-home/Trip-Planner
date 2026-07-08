"""
src/ical_feed.py

Pure builder for the user-level iCal subscription feed.

Every user has one opaque `ical_token` on their User row. That token
grants read access to `/ical/<token>.ics`, which emits VEVENTs for
every itinerary item and every timed booking on every trip the user
owns or collaborates on.

Design notes:

- **Floating times.** The app stores naive local datetimes throughout,
  so we emit VEVENTs as floating events — no ``TZID``, no ``Z``. Google
  and Apple render floating times at the device's local timezone, which
  is what a traveler wants ("my 6pm dinner is 6pm wherever I am").
- **Stable UIDs.** ``<trip_id>-<kind>-<row_id>@vacation-planner.local``.
  Regenerating the feed for the same rows produces the same UIDs, so
  calendar clients update existing events in place instead of duplicating.
- **Booking scope.** Only ``flight``, ``hotel``, and ``car`` bookings
  produce booking-level events (and only when both start and end
  datetimes are set). ``restaurant``/``activity``/``transport``/``other``
  events are already covered by the auto-linked itinerary items that
  the booking-new route creates, so emitting them here would double up.
"""

import logging
import re
import secrets
from datetime import date, datetime, timedelta
from typing import List, Optional

from icalendar import Calendar, Event

from models import Booking, ItineraryItem, Trip, TripCollaborator, User, db

logger = logging.getLogger(__name__)

# Floating events — no TZID emitted, calendar clients render in the
# device's local timezone. Kept as a module-level sentinel so callers
# can key off "we're intentionally floating" instead of guessing at None.
FLOATING_TZ: Optional[str] = None

# UID host component. Stable — don't change without a migration plan for
# existing subscribers' calendars.
UID_HOST = "vacation-planner.local"

# Booking types that get their own VEVENT. Everything else is expected
# to appear via auto-linked itinerary items.
BOOKING_EVENT_TYPES = ("flight", "hotel", "car")

# Regex for validating a urlsafe base64 token. Used only in tests, but
# defined here so the token shape lives with the generator.
_URLSAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ─── token helpers ───────────────────────────────────────────────────────────


def generate_token() -> str:
    """Return a fresh 32-char urlsafe base64 token.

    ``secrets.token_urlsafe(24)`` gives 24 bytes of randomness encoded
    as base64url, which comes out to 32 characters. Fits comfortably in
    the ``String(36)`` column.
    """
    return secrets.token_urlsafe(24)


def user_by_token(token: str) -> Optional[User]:
    """Look up a user by their ical_token. Case-sensitive."""
    if not token:
        return None
    return User.query.filter_by(ical_token=token).first()


# ─── event builders ──────────────────────────────────────────────────────────


def _uid(trip_id: int, kind: str, row_id: int) -> str:
    return f"{trip_id}-{kind}-{row_id}@{UID_HOST}"


def event_from_itinerary(item: ItineraryItem) -> Optional[Event]:
    """Convert an ItineraryItem into a VEVENT.

    Timed items (both ``start_time`` and ``end_time`` set) become
    floating timed VEVENTs. Items with only ``day_date`` become
    all-day VEVENTs (``VALUE=DATE``).

    Returns None only if the item is malformed enough that we can't
    place it on any day. In practice ``day_date`` is required by the
    schema, so this never happens today — the return type stays
    ``Optional`` so callers can uniformly filter.
    """
    if item.day_date is None:
        return None

    ev = Event()
    ev.add("uid", _uid(item.trip_id, "itinerary", item.id))
    summary_prefix = item.trip.name if item.trip is not None else ""
    ev.add(
        "summary",
        f"{summary_prefix}: {item.title}" if summary_prefix else item.title,
    )

    if item.start_time is not None and item.end_time is not None:
        # Timed VEVENT — combine day + time into a naive local datetime.
        ev.add("dtstart", datetime.combine(item.day_date, item.start_time))
        ev.add("dtend", datetime.combine(item.day_date, item.end_time))
    else:
        # All-day VEVENT. icalendar detects a bare `date` and emits
        # VALUE=DATE automatically. Per RFC 5545, all-day DTEND is
        # exclusive, so a one-day event ends on the next day.
        ev.add("dtstart", item.day_date)
        ev.add("dtend", item.day_date + timedelta(days=1))

    if item.location:
        ev.add("location", item.location)
    if item.notes:
        ev.add("description", item.notes)

    return ev


def event_from_booking(booking: Booking) -> Optional[Event]:
    """Convert a Booking into a VEVENT.

    Only ``flight``/``hotel``/``car`` bookings with BOTH datetimes set
    produce an event. Anything else returns None — the caller filters.
    """
    if booking.type not in BOOKING_EVENT_TYPES:
        return None
    if booking.start_datetime is None or booking.end_datetime is None:
        return None

    ev = Event()
    ev.add("uid", _uid(booking.trip_id, booking.type, booking.id))

    summary_prefix = booking.trip.name if booking.trip is not None else ""
    ev.add(
        "summary",
        f"{summary_prefix}: {booking.title}" if summary_prefix else booking.title,
    )

    ev.add("dtstart", booking.start_datetime)
    ev.add("dtend", booking.end_datetime)

    if booking.location:
        ev.add("location", booking.location)
    if booking.notes:
        ev.add("description", booking.notes)

    return ev


def build_events_for_trip(trip: Trip) -> List[Event]:
    """Return every VEVENT for a single trip (bookings + itinerary items).

    Order: bookings first (they set the trip's outer frame), then
    itinerary items. Skipped rows (missing datetimes, etc.) are
    silently filtered.
    """
    events: List[Event] = []

    for booking in trip.bookings:
        ev = event_from_booking(booking)
        if ev is not None:
            events.append(ev)

    for item in trip.itinerary_items:
        ev = event_from_itinerary(item)
        if ev is not None:
            events.append(ev)

    return events


# ─── trip lookup ─────────────────────────────────────────────────────────────


def _trips_for_user(user: User) -> List[Trip]:
    """Return every trip the user owns or collaborates on (any role).

    De-duplicated by trip.id — a user who was somehow both owner and
    collaborator on the same trip shouldn't get double events.
    """
    owned = Trip.query.filter_by(owner_id=user.id).all()

    email = (user.email or "").strip().lower()
    if email:
        collab_trip_ids = [
            row.trip_id
            for row in TripCollaborator.query.filter_by(email=email).all()
        ]
        collab_trips = (
            Trip.query.filter(Trip.id.in_(collab_trip_ids)).all()
            if collab_trip_ids
            else []
        )
    else:
        collab_trips = []

    by_id = {t.id: t for t in owned}
    for t in collab_trips:
        by_id.setdefault(t.id, t)
    return list(by_id.values())


# ─── top-level feed ──────────────────────────────────────────────────────────


def build_feed(user: User, now: datetime) -> bytes:
    """Build the iCal feed body for a user. Returns encoded bytes.

    ``now`` is accepted so callers (and tests) can inject a deterministic
    ``DTSTAMP`` if they want; today the icalendar library sets DTSTAMP
    on each Event automatically, so ``now`` is unused inside the body.
    Kept in the signature for future use — request-time timestamps in
    ``X-WR-*`` headers, for instance.
    """
    del now  # reserved for future use — see docstring

    cal = Calendar()
    cal.add("prodid", "-//Vacation Planner//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "My Trips")

    for trip in _trips_for_user(user):
        for ev in build_events_for_trip(trip):
            cal.add_component(ev)

    return cal.to_ical()

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

    # "metric" (default) or "imperial". Drives temperature display app-wide.
    weather_units = db.Column(
        db.String(10), nullable=False, default="metric",
    )

    # ISO 4217 code (e.g. "USD"). Default target for budget-page conversion.
    home_currency = db.Column(
        db.String(3), nullable=False, default="USD",
    )

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
    cover_image_url = db.Column(db.String(800), nullable=True)
    primary_currency = db.Column(db.String(3), nullable=False, default="USD")
    # IANA timezone (e.g. "Europe/Paris") used by the destination-clock feature.
    timezone_iana = db.Column(db.String(64), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # ── Yearbook public-share (Phase 3) ───────────────────────────────
    # Opaque token that grants read access to /yearbook/<token>. NULL
    # means the yearbook is private. Generated/rotated/revoked from the
    # share UI on the authenticated yearbook page.
    yearbook_share_token = db.Column(db.String(32), unique=True, nullable=True, index=True)
    # Per-trip toggles that gate what the public view exposes.
    yearbook_public_show_notes = db.Column(db.Boolean, nullable=False, default=False)
    yearbook_public_show_spend = db.Column(db.Boolean, nullable=False, default=True)

    # ── Trip Guide public-share (Phase 3) ──────────────────────────────
    # Opaque token that grants read access to /guide/<token>. NULL means
    # the guide is private. Generated/rotated/revoked from the share UI
    # on the authenticated guide page.
    guide_share_token = db.Column(db.String(36), unique=True, nullable=True, index=True)

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

    # ── Geocoding (added by map-view feature) ─────────────────────────
    geocoded_lat = db.Column(db.Float, nullable=True)
    geocoded_lng = db.Column(db.Float, nullable=True)
    geocoded_at = db.Column(db.DateTime, nullable=True)
    geocoded_manually = db.Column(db.Boolean, nullable=False, default=False)
    geocoded_city = db.Column(db.String(120), nullable=True)
    geocoded_country_code = db.Column(db.String(2), nullable=True)

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

    # Yearbook ★ highlight flag — set from the itinerary page, surfaced
    # in the Highlights section of /yearbook.
    starred = db.Column(db.Boolean, nullable=False, default=False)

    # Sort order for items at the same time / untimed items on the same day.
    order_within_day = db.Column(db.Integer, nullable=False, default=0)

    # Populated when an itinerary entry is auto-created from a Booking
    # (e.g. hotel check-in). NULL means a stand-alone item.
    linked_booking_id = db.Column(
        db.Integer, db.ForeignKey("booking.id"), nullable=True, index=True
    )

    # When this item was auto-spawned from a booking, this records which
    # "slot" it was: depart/arrive/check_in/check_out/pickup/return/single.
    # NULL for stand-alone items and for legacy linked items predating
    # this column.
    auto_kind = db.Column(db.String(20), nullable=True)

    # DEPRECATED in phase 3: will be replaced by auto_fields_touched.
    # Still read and written by some routes until Tasks 3–6 of the
    # phase-3 plan land. Column will be dropped in a later phase.
    customized_by_user = db.Column(db.Boolean, nullable=False, default=False)

    # Set of DRIFT_FIELDS the user has personally edited on this item.
    # Stored as a sorted comma-separated string (e.g. "day_date,title").
    # Empty string means nothing touched. Replaces customized_by_user.
    auto_fields_touched = db.Column(db.String(255), nullable=False, default="")

    # ── Geocoding (added by map-view feature) ─────────────────────────
    geocoded_lat = db.Column(db.Float, nullable=True)
    geocoded_lng = db.Column(db.Float, nullable=True)
    geocoded_at = db.Column(db.DateTime, nullable=True)
    geocoded_manually = db.Column(db.Boolean, nullable=False, default=False)
    geocoded_city = db.Column(db.String(120), nullable=True)
    geocoded_country_code = db.Column(db.String(2), nullable=True)

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


class TripView(db.Model):
    """
    One row per (trip, user) recording the last time that user opened the
    trip overview. Used to drive the "what changed since your last visit"
    banner — the route compares Booking / ItineraryItem `created_at` against
    `last_seen_at`, then bumps `last_seen_at` to now.

    Both the owner and collaborators get tracked here uniformly. First
    visit creates the row with `last_seen_at = now` so no banner appears.
    """

    __tablename__ = "trip_view"
    __table_args__ = (
        db.UniqueConstraint("trip_id", "user_id", name="uq_trip_view_trip_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class GeocodeCache(db.Model):
    """De-duplicates geocoding API calls across the whole app.

    `location_text_normalized` is the input text after strip + lower +
    whitespace collapse — see `src.map_helpers.normalize_location`.
    A miss writes here; a hit copies the cached coords onto the row
    without calling the API.
    """

    __tablename__ = "geocode_cache"

    id = db.Column(db.Integer, primary_key=True)
    location_text_normalized = db.Column(db.String(255), nullable=False, unique=True, index=True)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    city = db.Column(db.String(120), nullable=True)
    country_code = db.Column(db.String(2), nullable=True)
    provider = db.Column(db.String(40), nullable=False, default="mapbox")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class WeatherCache(db.Model):
    """De-duplicates Open-Meteo forecast lookups.

    Keyed by (lat_rounded, lng_rounded, forecast_date, temp_unit). The
    rounded coords coalesce nearby items in the same city to one row.
    Rows are TTL-based — see CACHE_TTL_SECONDS in src/weather.py.
    """

    __tablename__ = "weather_cache"
    __table_args__ = (
        db.UniqueConstraint(
            "lat_rounded", "lng_rounded", "forecast_date", "temp_unit",
            name="uq_weather_cache_key",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    lat_rounded = db.Column(db.Float, nullable=False)
    lng_rounded = db.Column(db.Float, nullable=False)
    forecast_date = db.Column(db.Date, nullable=False)
    temp_unit = db.Column(db.String(10), nullable=False)  # "celsius" | "fahrenheit"
    high_temp = db.Column(db.Float, nullable=False)
    low_temp = db.Column(db.Float, nullable=False)
    precipitation_probability = db.Column(db.Integer, nullable=True)
    humidity = db.Column(db.Integer, nullable=True)
    wmo_code = db.Column(db.Integer, nullable=False)
    hourly_json = db.Column(db.Text, nullable=True)
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ExchangeRateCache(db.Model):
    """De-duplicates exchangerate.host calls.

    Keyed by (base_currency, target_currency, rate_date). In v1 the
    base is always "USD" — cross-rates are computed via USD in
    src/exchange_rates.cross_rates_via_usd. Rows are TTL-based —
    see CACHE_TTL_SECONDS in src/exchange_rates.py.
    """

    __tablename__ = "exchange_rate_cache"
    __table_args__ = (
        db.UniqueConstraint(
            "base_currency", "target_currency", "rate_date",
            name="uq_exchange_rate_cache_pair_date",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    base_currency = db.Column(db.String(3), nullable=False)
    target_currency = db.Column(db.String(3), nullable=False)
    rate = db.Column(db.Float, nullable=False)
    rate_date = db.Column(db.Date, nullable=False)
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class TripPrepItem(db.Model):
    """A single trip-prep to-do owned by a user.

    Lives at user level — `trip_id` is nullable so an item can be
    cross-trip ("renew passport") or pinned to a specific trip. A
    cross-trip item can additionally be linked to one or more specific
    trips via the TripPrepLink association rows (with per-link due
    offsets), without losing its user-level identity.
    """

    __tablename__ = "trip_prep_item"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=True, index=True)

    title = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    # One of: documents, health, packing, home, transport, other (see prep_helpers).
    category = db.Column(db.String(20), nullable=False, default="other")

    # Optional URL the user pasted; link_image_url is the og:image
    # extracted from it (populated by src/url_metadata.py).
    link_url = db.Column(db.String(800), nullable=True)
    link_image_url = db.Column(db.String(800), nullable=True)

    done = db.Column(db.Boolean, nullable=False, default=False)
    done_at = db.Column(db.DateTime, nullable=True)

    # Days before trip start_date when this item is "due" — positive
    # means before, negative means after. NULL = no specific due date.
    due_offset_days = db.Column(db.Integer, nullable=True)

    # When the user dismissed the "add to packing list?" prompt for
    # this item — keeps the prompt from re-appearing after each
    # done-toggle.
    packing_prompt_dismissed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    owner = db.relationship("User", backref=db.backref("trip_prep_items", lazy=True))
    # Trip-side cascade: a per-trip prep item (trip_id set) dies with the
    # trip. Cross-trip items (trip_id NULL) are user-level and unaffected
    # by this relationship — they're reached via owner / TripPrepLink.
    # Without this cascade, deleting a Trip with per-trip prep items
    # 500s on Postgres (FK violation); SQLite hides it because FKs are
    # off by default.
    trip = db.relationship(
        "Trip",
        backref=db.backref("prep_items", lazy=True, cascade="all, delete-orphan"),
    )
    links = db.relationship(
        "TripPrepLink",
        backref="item",
        cascade="all, delete-orphan",
        lazy=True,
    )


class TripPrepLink(db.Model):
    """Association row linking a TripPrepItem to a specific Trip.

    Lets one cross-trip prep item ("renew passport") appear on more
    than one trip's per-trip prep tab without duplicating the row.
    Each link can carry its own `due_offset_days` so the same item
    can be "30 days before Italy" and "60 days before Japan".
    """

    __tablename__ = "trip_prep_link"
    __table_args__ = (
        db.UniqueConstraint("trip_prep_item_id", "trip_id", name="uq_prep_link_item_trip"),
    )

    id = db.Column(db.Integer, primary_key=True)
    trip_prep_item_id = db.Column(
        db.Integer, db.ForeignKey("trip_prep_item.id"), nullable=False, index=True,
    )
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)

    due_offset_days = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Link rows die with the trip — the link is the per-trip association,
    # so once the trip is gone the link is meaningless. The cross-trip
    # TripPrepItem on the other end of the link survives independently.
    trip = db.relationship(
        "Trip",
        backref=db.backref("prep_links", lazy=True, cascade="all, delete-orphan"),
    )

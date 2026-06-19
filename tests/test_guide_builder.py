"""Tests for src/guide_builder."""

import json
import logging
import os
from datetime import date, datetime, time

import pytest

from app import app as flask_app
from models import Booking, ItineraryItem, Trip, TripCollaborator, User, db
from src import guide_builder
from src.guide_builder import (
    CONFIG_SCHEMA_VERSION,
    GuideConfig,
    TripNotFound,
    load_or_init_config,
    load_trip_data,
    save_config,
)


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


# ─── config sidecar helpers ────────────────────────────────────────────────


@pytest.fixture(autouse=False)
def patch_guides_dir(tmp_path, monkeypatch):
    """Redirect GUIDES_DIR to a temp directory so tests never touch data/guides/."""
    guides = tmp_path / "guides"
    monkeypatch.setattr(guide_builder, "GUIDES_DIR", guides)
    return guides


def test_load_or_init_config_returns_fresh_when_missing(patch_guides_dir):
    """No file present → returns a fresh empty GuideConfig."""
    cfg = load_or_init_config(42)
    assert cfg.trip_id == 42
    assert cfg.schema_version == CONFIG_SCHEMA_VERSION
    assert cfg.sections == []
    assert cfg.palette == {}
    assert cfg.last_generated_at is None


def test_load_or_init_config_returns_fresh_when_corrupt_json(patch_guides_dir, caplog):
    """Corrupt JSON file → returns fresh config and logs a warning."""
    guides = patch_guides_dir
    guides.mkdir(parents=True, exist_ok=True)
    (guides / "7.config.json").write_text("this is not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="src.guide_builder"):
        cfg = load_or_init_config(7)

    assert cfg.trip_id == 7
    assert cfg.sections == []
    assert any("corrupt" in rec.message.lower() for rec in caplog.records)


def test_load_or_init_config_returns_fresh_when_schema_version_mismatched(
    patch_guides_dir, caplog
):
    """schema_version mismatch → returns fresh config and logs a warning."""
    guides = patch_guides_dir
    guides.mkdir(parents=True, exist_ok=True)
    bad = {
        "schema_version": 999,
        "trip_id": 5,
        "sections": ["day_by_day"],
        "palette": {},
        "last_generated_at": None,
    }
    (guides / "5.config.json").write_text(json.dumps(bad), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="src.guide_builder"):
        cfg = load_or_init_config(5)

    assert cfg.trip_id == 5
    assert cfg.sections == []
    assert any("schema_version" in rec.message.lower() for rec in caplog.records)


def test_load_or_init_config_returns_saved_when_valid(patch_guides_dir):
    """Round-trip: save then load returns an equal GuideConfig."""
    original = GuideConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        trip_id=10,
        sections=["day_by_day", "food"],
        palette={"primary": "#ff5500"},
        last_generated_at="2026-06-19T12:00:00",
    )
    save_config(10, original)
    loaded = load_or_init_config(10)

    assert loaded.schema_version == original.schema_version
    assert loaded.trip_id == original.trip_id
    assert loaded.sections == original.sections
    assert loaded.palette == original.palette
    assert loaded.last_generated_at == original.last_generated_at


def test_save_config_creates_directory_if_missing(tmp_path, monkeypatch):
    """save_config creates the guides directory when it does not yet exist."""
    guides = tmp_path / "new_guides"
    monkeypatch.setattr(guide_builder, "GUIDES_DIR", guides)
    assert not guides.exists()

    cfg = GuideConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        trip_id=3,
        sections=[],
        palette={},
        last_generated_at=None,
    )
    written = save_config(3, cfg)

    assert guides.exists()
    assert written == guides / "3.config.json"
    assert written.exists()


def test_save_config_atomic_write(patch_guides_dir, monkeypatch):
    """If os.replace raises, the existing destination file is untouched
    and the .tmp scratch file is cleaned up.
    """
    guides = patch_guides_dir
    guides.mkdir(parents=True, exist_ok=True)

    # Write an existing good config first
    good_cfg = GuideConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        trip_id=99,
        sections=["food"],
        palette={},
        last_generated_at=None,
    )
    save_config(99, good_cfg)
    original_text = (guides / "99.config.json").read_text()

    # Now make os.replace raise on the next call
    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)

    new_cfg = GuideConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        trip_id=99,
        sections=["day_by_day"],
        palette={},
        last_generated_at=None,
    )
    with pytest.raises(OSError, match="disk full"):
        save_config(99, new_cfg)

    # The destination file must be untouched — this is the atomic-write guarantee
    assert (guides / "99.config.json").read_text() == original_text
    # The .tmp scratch file must be cleaned up — no leftover debris
    assert not (guides / "99.config.json.tmp").exists()

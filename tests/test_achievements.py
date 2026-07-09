"""Tests for src/achievements.py — user-stats aggregation + badge registry.

Dates are pinned far in the past so ``derive_status`` returns
"completed" without needing to freeze ``date.today()``.
"""

from datetime import date, timedelta

import pytest

from app import app as flask_app
from models import Booking, ItineraryItem, Trip, TripCollaborator, User, db
from src import achievements


# ─── fixtures (same style as tests/test_ical_feed.py) ────────────────────────


@pytest.fixture
def app():
    """Fresh in-memory DB per test."""
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def owner(app):
    u = User(google_id="g-ach", email="owner@example.com", name="Owner")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def client(app):
    """Flask test client bound to the same app context."""
    return app.test_client()


# ─── helpers ─────────────────────────────────────────────────────────────────


def _past_completed_trip(
    owner_id: int, name: str = "Past trip",
    start: date = date(2024, 6, 1), end: date = date(2024, 6, 8),
) -> Trip:
    """Create + persist a trip whose end date is safely in the past."""
    t = Trip(owner_id=owner_id, name=name, start_date=start, end_date=end)
    db.session.add(t)
    db.session.commit()
    return t


# ─── compute_stats ───────────────────────────────────────────────────────────


def test_compute_stats_empty_user(app, owner):
    """No trips → every stat is zero / empty."""
    stats = achievements.compute_stats(owner)
    assert stats["trips_completed"] == 0
    assert stats["trips_in_year"] == {}
    assert stats["countries_visited"] == set()
    assert stats["continents_visited"] == set()
    assert stats["total_nights"] == 0
    assert stats["solo_trips"] == 0
    assert stats["group_trips"] == 0


def test_compute_stats_counts_only_completed_trips(app, owner):
    """Planning + in-progress trips are excluded; only completed trips count."""
    today = date.today()

    # Completed (past).
    _past_completed_trip(owner.id, name="Done",
                         start=date(2024, 6, 1), end=date(2024, 6, 8))

    # Planning (future).
    db.session.add(Trip(
        owner_id=owner.id, name="Future",
        start_date=today + timedelta(days=30),
        end_date=today + timedelta(days=37),
    ))
    # In-progress (spans today).
    db.session.add(Trip(
        owner_id=owner.id, name="Now",
        start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=1),
    ))
    db.session.commit()

    stats = achievements.compute_stats(owner)
    assert stats["trips_completed"] == 1
    assert stats["total_nights"] == 7  # 8 June − 1 June


def test_countries_from_geocoded_country_codes(app, owner):
    """Booking + itinerary-item country codes union into countries_visited."""
    trip = _past_completed_trip(owner.id)

    db.session.add(Booking(
        trip_id=trip.id, type="flight", title="UA1",
        geocoded_country_code="fr",   # stored lowercase — should upper-case
    ))
    db.session.add(Booking(
        trip_id=trip.id, type="hotel", title="Lutetia",
        geocoded_country_code="FR",   # duplicate — dedup
    ))
    db.session.add(ItineraryItem(
        trip_id=trip.id, day_date=date(2024, 6, 2),
        title="Louvre", geocoded_country_code="FR",
    ))
    db.session.add(ItineraryItem(
        trip_id=trip.id, day_date=date(2024, 6, 3),
        title="Colosseum", geocoded_country_code="IT",
    ))
    # Null code — should be skipped, not raise.
    db.session.add(ItineraryItem(
        trip_id=trip.id, day_date=date(2024, 6, 4),
        title="Wander", geocoded_country_code=None,
    ))
    db.session.commit()

    stats = achievements.compute_stats(owner)
    assert stats["countries_visited"] == {"FR", "IT"}


def test_continents_derived_from_countries(app, owner):
    """Country codes in two different continents → both continents show up.

    Also exercises the unknown-code fallback: ``ZZ`` isn't in the map;
    ``compute_stats`` should log-debug and skip without raising.
    """
    trip = _past_completed_trip(owner.id)
    db.session.add(ItineraryItem(
        trip_id=trip.id, day_date=date(2024, 6, 2),
        title="Paris", geocoded_country_code="FR",  # EU
    ))
    db.session.add(ItineraryItem(
        trip_id=trip.id, day_date=date(2024, 6, 3),
        title="Tokyo", geocoded_country_code="JP",  # AS
    ))
    db.session.add(ItineraryItem(
        trip_id=trip.id, day_date=date(2024, 6, 4),
        title="Mystery", geocoded_country_code="ZZ",  # unknown → skip
    ))
    db.session.commit()

    stats = achievements.compute_stats(owner)
    assert stats["continents_visited"] == {"EU", "AS"}
    # ZZ still shows up as a "visited country" even though it has no continent.
    assert "ZZ" in stats["countries_visited"]


def test_trips_in_year_groups_by_start_date(app, owner):
    """Two completed trips in 2025, one in 2026 → {2025: 2, 2026: 1}."""
    _past_completed_trip(owner.id, name="A",
                         start=date(2025, 3, 1), end=date(2025, 3, 5))
    _past_completed_trip(owner.id, name="B",
                         start=date(2025, 9, 10), end=date(2025, 9, 15))
    _past_completed_trip(owner.id, name="C",
                         start=date(2026, 1, 1), end=date(2026, 1, 3))

    stats = achievements.compute_stats(owner)
    assert stats["trips_in_year"] == {2025: 2, 2026: 1}


def test_solo_vs_group_split(app, owner):
    """One completed trip with 0 collaborators + one with 1 →
    solo_trips=1, group_trips=1."""
    solo = _past_completed_trip(owner.id, name="Solo trip",
                                start=date(2024, 5, 1), end=date(2024, 5, 3))
    group = _past_completed_trip(owner.id, name="Group trip",
                                 start=date(2024, 7, 1), end=date(2024, 7, 5))
    del solo  # no collaborators for the solo one
    db.session.add(TripCollaborator(
        trip_id=group.id, email="pal@example.com", role="viewer",
    ))
    db.session.commit()

    stats = achievements.compute_stats(owner)
    assert stats["solo_trips"] == 1
    assert stats["group_trips"] == 1


# ─── earned / near_earned ────────────────────────────────────────────────────


def test_earned_first_trip_after_one_completed(app, owner):
    """One completed trip earns first_trip and nothing else."""
    _past_completed_trip(owner.id)
    ids = {a.id for a in achievements.earned(owner)}
    assert "first_trip" in ids
    assert "countries_5" not in ids
    assert "countries_10" not in ids
    assert "continents_all" not in ids


def test_earned_countries_10(app, owner):
    """10 country codes → countries_10 earned; 9 → not earned."""
    trip = _past_completed_trip(owner.id)

    ten = ["FR", "IT", "ES", "DE", "GB", "JP", "US", "MX", "BR", "AU"]
    for i, cc in enumerate(ten):
        db.session.add(ItineraryItem(
            trip_id=trip.id, day_date=date(2024, 6, 1),
            title=f"Stop {i}", geocoded_country_code=cc,
        ))
    db.session.commit()
    ids = {a.id for a in achievements.earned(owner)}
    assert "countries_10" in ids
    assert "countries_5" in ids

    # Remove one → should drop back to only countries_5.
    dropped = ItineraryItem.query.filter_by(
        trip_id=trip.id, geocoded_country_code="AU").first()
    db.session.delete(dropped)
    db.session.commit()

    ids_after = {a.id for a in achievements.earned(owner)}
    assert "countries_10" not in ids_after
    assert "countries_5" in ids_after


def test_near_earned_returns_progress_tuples(app, owner):
    """3 countries → near_earned includes (countries_5, 3, 5)."""
    trip = _past_completed_trip(owner.id)
    for cc in ("FR", "IT", "ES"):
        db.session.add(ItineraryItem(
            trip_id=trip.id, day_date=date(2024, 6, 1),
            title=cc, geocoded_country_code=cc,
        ))
    db.session.commit()

    near = achievements.near_earned(owner, limit=10)
    matches = [
        (ach.id, cur, tgt) for (ach, cur, tgt) in near
        if ach.id == "countries_5"
    ]
    assert matches == [("countries_5", 3, 5)]


def test_near_earned_excludes_already_earned(app, owner):
    """10 countries → countries_5 and countries_10 are NOT in near_earned."""
    trip = _past_completed_trip(owner.id)
    for cc in ["FR", "IT", "ES", "DE", "GB", "JP", "US", "MX", "BR", "AU"]:
        db.session.add(ItineraryItem(
            trip_id=trip.id, day_date=date(2024, 6, 1),
            title=cc, geocoded_country_code=cc,
        ))
    db.session.commit()

    near_ids = {ach.id for (ach, _, _) in achievements.near_earned(owner, limit=10)}
    assert "countries_5" not in near_ids
    assert "countries_10" not in near_ids
    # countries_25 is still open with current=10 target=25 → should appear.
    assert "countries_25" in near_ids


# ─── /achievements route ─────────────────────────────────────────────────────


def test_route_requires_login(client):
    """Unauthenticated GET should redirect to login (not 200)."""
    resp = client.get("/achievements", follow_redirects=False)
    assert resp.status_code in (302, 401), \
        f"expected redirect/unauth, got {resp.status_code}"


def test_route_renders_all_achievements_in_grid(client, app, owner):
    """Signed-in GET renders the page + at least one achievement name."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
        sess["_fresh"] = True

    resp = client.get("/achievements")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # First Trip appears in the Locked catalog for a brand-new user.
    assert "First Trip" in body
    # Hero counter renders.
    total = len(achievements.all_achievements())
    assert f"of {total} earned" in body

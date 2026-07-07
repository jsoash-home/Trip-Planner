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
    GuideMissing,
    GuideConfig,
    TripNotFound,
    clear_share_token,
    guide_exists,
    guide_path,
    inject_print_affordance,
    load_or_init_config,
    load_trip_data,
    read_guide,
    save_config,
    save_guide,
    set_share_token,
    trip_by_share_token,
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


# ─── GuideConfig depth_tier / archetype / narrator_angle ───────────────────


def _base_kwargs(**overrides):
    """Minimal positional-equivalent kwargs for GuideConfig used by these tests."""
    base = dict(
        schema_version=CONFIG_SCHEMA_VERSION,
        trip_id=1,
        sections=[],
        palette={},
        last_generated_at=None,
    )
    base.update(overrides)
    return base


def test_guide_config_defaults_new_fields_to_none():
    """All four new fields default cleanly when not provided."""
    cfg = GuideConfig(**_base_kwargs())
    assert cfg.depth_tier is None
    assert cfg.section_depth_overrides == {}
    assert cfg.archetype is None
    assert cfg.narrator_angle is None


def test_guide_config_roundtrip_with_depth_tier(patch_guides_dir):
    """depth_tier survives save → load round-trip."""
    original = GuideConfig(**_base_kwargs(trip_id=11, depth_tier="souvenir_grade"))
    save_config(11, original)
    loaded = load_or_init_config(11)
    assert loaded.depth_tier == "souvenir_grade"


def test_guide_config_roundtrip_with_section_overrides(patch_guides_dir):
    """section_depth_overrides survives save → load (flat shape: section → tier)."""
    overrides = {"history": "souvenir_grade", "food": "deep"}
    original = GuideConfig(
        **_base_kwargs(trip_id=12, section_depth_overrides=overrides)
    )
    save_config(12, original)
    loaded = load_or_init_config(12)
    assert loaded.section_depth_overrides == overrides


def test_guide_config_roundtrip_with_archetype(patch_guides_dir):
    """archetype survives save → load round-trip."""
    original = GuideConfig(**_base_kwargs(trip_id=13, archetype="history_stacked"))
    save_config(13, original)
    loaded = load_or_init_config(13)
    assert loaded.archetype == "history_stacked"


def test_guide_config_roundtrip_with_narrator_angle(patch_guides_dir):
    """narrator_angle (free-form short string) survives save → load round-trip."""
    angle = "First-timer with a history obsession"
    original = GuideConfig(**_base_kwargs(trip_id=14, narrator_angle=angle))
    save_config(14, original)
    loaded = load_or_init_config(14)
    assert loaded.narrator_angle == angle


def test_guide_config_back_compat_missing_fields_load_as_none(patch_guides_dir):
    """A sidecar JSON written before Task 1 (no depth/archetype/narrator keys)
    must load with sensible defaults so existing trips keep working."""
    guides = patch_guides_dir
    guides.mkdir(parents=True, exist_ok=True)
    legacy = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "trip_id": 15,
        "sections": ["history", "food"],
        "palette": {"primary": "#112233"},
        "last_generated_at": "2026-06-19T12:00:00",
        # NOTE: depth_tier, section_depth_overrides, archetype, narrator_angle absent.
    }
    (guides / "15.config.json").write_text(json.dumps(legacy), encoding="utf-8")

    cfg = load_or_init_config(15)
    assert cfg.depth_tier is None
    assert cfg.section_depth_overrides == {}
    assert cfg.archetype is None
    assert cfg.narrator_angle is None


def test_guide_config_invalid_depth_tier_rejected_or_normalized():
    """depth_tier is normalized: whitespace + case are tolerated, unknown values
    silently drop to None so a typo in an existing sidecar JSON doesn't crash."""
    # Whitespace + uppercase → canonical lowercase form
    cfg_a = GuideConfig(**_base_kwargs(depth_tier="  Deep  "))
    assert cfg_a.depth_tier == "deep"

    # Mixed case souvenir_grade still normalizes
    cfg_b = GuideConfig(**_base_kwargs(depth_tier="Souvenir_Grade"))
    assert cfg_b.depth_tier == "souvenir_grade"

    # Unknown value silently dropped to None (does not raise)
    cfg_c = GuideConfig(**_base_kwargs(depth_tier="extreme"))
    assert cfg_c.depth_tier is None

    # None stays None (no-op for the default case)
    cfg_d = GuideConfig(**_base_kwargs(depth_tier=None))
    assert cfg_d.depth_tier is None


# ─── guide_path / guide_exists / save_guide / read_guide ───────────────────


def test_guide_path_computes_expected_path(patch_guides_dir):
    """guide_path returns GUIDES_DIR / '<trip_id>.html'."""
    expected = patch_guides_dir / "42.html"
    assert guide_path(42) == expected


def test_guide_exists_returns_false_when_missing(patch_guides_dir):
    """guide_exists is False when no HTML file is on disk."""
    assert guide_exists(1) is False


def test_guide_exists_returns_true_when_present(patch_guides_dir):
    """guide_exists is True after the HTML file has been written."""
    guides = patch_guides_dir
    guides.mkdir(parents=True, exist_ok=True)
    (guides / "5.html").write_text("<html/>", encoding="utf-8")
    assert guide_exists(5) is True


def test_save_guide_writes_file(patch_guides_dir):
    """save_guide writes the HTML content to the expected path."""
    html = "<html><body>Rome Guide</body></html>"
    written = save_guide(7, html)
    assert written == patch_guides_dir / "7.html"
    assert written.read_text(encoding="utf-8") == html


def test_save_guide_creates_directory_if_missing(tmp_path, monkeypatch):
    """save_guide creates GUIDES_DIR when it does not yet exist."""
    guides = tmp_path / "nonexistent_guides"
    monkeypatch.setattr(guide_builder, "GUIDES_DIR", guides)
    assert not guides.exists()
    save_guide(8, "<html/>")
    assert guides.exists()
    assert (guides / "8.html").exists()


def test_save_guide_rotates_previous_to_bak(patch_guides_dir):
    """Calling save_guide a second time rotates the old file to .html.bak."""
    save_guide(9, "<html>v1</html>")
    save_guide(9, "<html>v2</html>")

    bak = patch_guides_dir / "9.html.bak"
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == "<html>v1</html>"
    assert (patch_guides_dir / "9.html").read_text(encoding="utf-8") == "<html>v2</html>"


def test_save_guide_no_bak_on_first_run(patch_guides_dir):
    """No .bak file is created on the very first save."""
    save_guide(11, "<html>first</html>")
    assert not (patch_guides_dir / "11.html.bak").exists()


def test_save_guide_bumps_last_generated_at(patch_guides_dir):
    """save_guide updates last_generated_at in the config sidecar."""
    save_guide(12, "<html/>")
    cfg = load_or_init_config(12)
    assert cfg.last_generated_at is not None
    # Sanity-check it parses as an ISO datetime string with timezone info.
    dt = datetime.fromisoformat(cfg.last_generated_at)
    assert dt.tzinfo is not None


def test_read_guide_returns_bytes_when_present(patch_guides_dir):
    """read_guide returns bytes of the saved HTML."""
    html = "<html><body>hello</body></html>"
    save_guide(20, html)
    result = read_guide(20)
    assert isinstance(result, bytes)
    assert result == html.encode("utf-8")


def test_read_guide_raises_guide_missing_when_absent(patch_guides_dir):
    """read_guide raises GuideMissing when no file exists."""
    with pytest.raises(GuideMissing):
        read_guide(999)


def test_save_guide_unknown_storage_raises_value_error(patch_guides_dir, monkeypatch):
    """GUIDE_STORAGE='whatever' → ValueError."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "whatever")
    with pytest.raises(ValueError, match="unknown GUIDE_STORAGE"):
        save_guide(31, "<html/>")


# ─── DB-mode storage tests (GUIDE_STORAGE=database) ─────────────────────────


def test_db_save_and_read_guide_roundtrip(app, trip, monkeypatch):
    """DB mode: save_guide writes bytes to Trip.guide_html; read_guide returns them."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")

    html = "<html><body>Rome guide</body></html>"
    result = save_guide(trip.id, html)
    assert result is None  # DB mode has no on-disk path to return

    assert read_guide(trip.id) == html.encode("utf-8")


def test_db_guide_exists_false_before_save_true_after(app, trip, monkeypatch):
    """DB mode: guide_exists tracks Trip.guide_html IS NOT NULL."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")

    assert guide_exists(trip.id) is False
    save_guide(trip.id, "<html/>")
    assert guide_exists(trip.id) is True


def test_db_read_guide_raises_guide_missing_when_null(app, trip, monkeypatch):
    """DB mode: NULL guide_html column → GuideMissing on read."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")
    with pytest.raises(GuideMissing):
        read_guide(trip.id)


def test_db_save_guide_bumps_last_generated_at_in_config_column(app, trip, monkeypatch):
    """DB mode: save_guide writes an ISO UTC timestamp into guide_config_json.last_generated_at."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")

    save_guide(trip.id, "<html/>")

    db.session.refresh(trip)
    assert trip.guide_config_json is not None
    cfg = json.loads(trip.guide_config_json)
    assert cfg["last_generated_at"] is not None
    # ISO-8601 UTC has a trailing "+00:00"
    assert cfg["last_generated_at"].endswith("+00:00")


def test_db_save_guide_raises_trip_not_found_when_no_row(app, monkeypatch):
    """DB mode: save_guide on a nonexistent trip id → TripNotFound."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")
    with pytest.raises(TripNotFound):
        save_guide(999, "<html/>")


def test_db_load_or_init_config_returns_fresh_when_column_is_null(app, trip, monkeypatch):
    """DB mode: NULL guide_config_json column → fresh empty GuideConfig."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")

    cfg = load_or_init_config(trip.id)
    assert cfg.schema_version == CONFIG_SCHEMA_VERSION
    assert cfg.trip_id == trip.id
    assert cfg.sections == []
    assert cfg.palette == {}
    assert cfg.last_generated_at is None


def test_db_save_config_and_load_or_init_roundtrip_full_config(app, trip, monkeypatch):
    """DB mode: save + load returns every field intact."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")

    original = GuideConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        trip_id=trip.id,
        sections=["day_by_day", "field_guide", "food"],
        palette={"primary": "#d68949", "accent": "#4b7d99"},
        last_generated_at="2026-07-07T12:00:00+00:00",
        depth_tier="deep",
        section_depth_overrides={"field_guide": "souvenir_grade"},
        archetype="mixed_leisure",
        narrator_angle="curious-outsider",
    )
    save_config(trip.id, original)

    loaded = load_or_init_config(trip.id)
    assert loaded.schema_version == original.schema_version
    assert loaded.trip_id == original.trip_id
    assert loaded.sections == original.sections
    assert loaded.palette == original.palette
    assert loaded.last_generated_at == original.last_generated_at
    assert loaded.depth_tier == original.depth_tier
    assert loaded.section_depth_overrides == original.section_depth_overrides
    assert loaded.archetype == original.archetype
    assert loaded.narrator_angle == original.narrator_angle


def test_db_load_or_init_config_returns_fresh_on_schema_version_mismatch(app, trip, monkeypatch, caplog):
    """DB mode: mismatched schema_version → warning + fresh empty config."""
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")

    trip.guide_config_json = json.dumps({
        "schema_version": 99,
        "trip_id": trip.id,
        "sections": ["day_by_day"],
        "palette": {},
        "last_generated_at": None,
    })
    db.session.commit()

    with caplog.at_level(logging.WARNING):
        cfg = load_or_init_config(trip.id)

    assert cfg.schema_version == CONFIG_SCHEMA_VERSION  # fresh, not 99
    assert cfg.sections == []
    assert "schema_version mismatch" in caplog.text


# ─── share-token helpers ────────────────────────────────────────────────────


def test_set_share_token_generates_36_char_token(app, trip):
    """set_share_token returns a 36-character hyphenated UUID string."""
    token = set_share_token(trip.id)
    assert len(token) == 36


def test_set_share_token_persists_to_trip(app, trip):
    """Trip.guide_share_token equals the returned value after set_share_token."""
    token = set_share_token(trip.id)
    db.session.expire(trip)
    assert trip.guide_share_token == token


def test_set_share_token_idempotent_returns_existing(app, trip):
    """Calling set_share_token twice returns the same token without rotating."""
    token_first = set_share_token(trip.id)
    token_second = set_share_token(trip.id)
    assert token_first == token_second


def test_set_share_token_unknown_trip_raises_trip_not_found(app):
    """set_share_token raises TripNotFound for an unknown trip_id."""
    with pytest.raises(TripNotFound):
        set_share_token(99999)


def test_clear_share_token_clears_field(app, trip):
    """clear_share_token sets guide_share_token back to None."""
    set_share_token(trip.id)
    clear_share_token(trip.id)
    db.session.expire(trip)
    assert trip.guide_share_token is None


def test_clear_share_token_idempotent_on_already_null(app, trip):
    """clear_share_token on a trip with no token is a no-op (no error)."""
    assert trip.guide_share_token is None
    clear_share_token(trip.id)  # must not raise
    db.session.expire(trip)
    assert trip.guide_share_token is None


def test_clear_share_token_unknown_trip_raises_trip_not_found(app):
    """clear_share_token raises TripNotFound for an unknown trip_id."""
    with pytest.raises(TripNotFound):
        clear_share_token(99999)


def test_trip_by_share_token_finds_correct_trip(app, owner):
    """Two trips with two tokens; lookup returns the right Trip by token."""
    t1 = Trip(owner_id=owner.id, name="Trip A", destination="Paris",
              start_date=date(2026, 8, 1), end_date=date(2026, 8, 5), status="planning")
    t2 = Trip(owner_id=owner.id, name="Trip B", destination="Tokyo",
              start_date=date(2026, 9, 1), end_date=date(2026, 9, 5), status="planning")
    db.session.add_all([t1, t2])
    db.session.commit()

    token_a = set_share_token(t1.id)
    set_share_token(t2.id)

    found = trip_by_share_token(token_a)
    assert found is not None
    assert found.id == t1.id


def test_trip_by_share_token_returns_none_for_unknown_token(app):
    """trip_by_share_token returns None when no trip has that token."""
    result = trip_by_share_token("00000000-0000-0000-0000-000000000000")
    assert result is None


def test_trip_by_share_token_case_sensitive(app, trip):
    """Uppercase version of a valid token returns None (UUID tokens are lowercase)."""
    token = set_share_token(trip.id)
    upper_token = token.upper()
    assert trip_by_share_token(upper_token) is None


# ─── inject_print_affordance ───────────────────────────────────────────────


def test_inject_print_affordance_inserts_before_body_close():
    """The button + print CSS land just before </body>."""
    html = b"<!doctype html><html><body><h1>Hi</h1></body></html>"
    result = inject_print_affordance(html)
    assert b"vp-print-btn" in result
    assert b"window.print()" in result
    assert b"@media print" in result
    # Affordance is positioned before the closing body, not after it.
    assert result.index(b"vp-print-btn") < result.index(b"</body>")


def test_inject_print_affordance_appends_when_no_body_close():
    """Falls back to appending if </body> is missing — never drops the button."""
    html = b"<div>just a fragment</div>"
    result = inject_print_affordance(html)
    assert result.startswith(html)
    assert b"vp-print-btn" in result


def test_inject_print_affordance_uses_last_body_close():
    """If a guide contains escaped '</body>' in text, only the real one is targeted."""
    html = b"<html><body><pre>example: &lt;/body&gt;</pre></body></html>"
    result = inject_print_affordance(html)
    # Affordance should land just before the final </body>, not inside the <pre>.
    last_close = result.rfind(b"</body>")
    btn_pos = result.index(b"vp-print-btn")
    assert btn_pos < last_close
    # And the <pre> content should still be intact.
    assert b"<pre>example: &lt;/body&gt;</pre>" in result

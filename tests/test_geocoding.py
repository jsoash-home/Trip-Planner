"""Unit tests for src/geocoding.py. Mocks all Mapbox HTTP calls."""

from unittest.mock import MagicMock, patch

import pytest

from src.geocoding import GeocodeResult, geocode_one


MAPBOX_RESPONSE_OK = {
    "features": [
        {
            "center": [18.0686, 59.3293],  # [lng, lat]
            "context": [
                {"id": "place.123", "short_code": None, "text": "Stockholm"},
                {"id": "country.456", "short_code": "SE", "text": "Sweden"},
            ],
        }
    ]
}

MAPBOX_RESPONSE_EMPTY = {"features": []}


@patch("src.geocoding.requests.get")
def test_geocode_one_success(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MAPBOX_RESPONSE_OK,
    )
    result = geocode_one("Hotel Skansen", token="pk.test")
    assert isinstance(result, GeocodeResult)
    assert result.lat == 59.3293
    assert result.lng == 18.0686
    assert result.city == "Stockholm"
    assert result.country_code == "SE"


@patch("src.geocoding.requests.get")
def test_geocode_one_no_results(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MAPBOX_RESPONSE_EMPTY,
    )
    result = geocode_one("Asdfqwerty Nowhere", token="pk.test")
    assert result is None


@patch("src.geocoding.requests.get")
def test_geocode_one_5xx_returns_none(mock_get):
    mock_get.return_value = MagicMock(status_code=503)
    result = geocode_one("Anywhere", token="pk.test")
    assert result is None


@patch("src.geocoding.requests.get")
def test_geocode_one_timeout_returns_none(mock_get):
    import requests as _requests
    mock_get.side_effect = _requests.exceptions.Timeout()
    result = geocode_one("Anywhere", token="pk.test")
    assert result is None


def test_geocode_one_empty_text_returns_none():
    # Should not call the API at all.
    result = geocode_one("   ", token="pk.test")
    assert result is None


@patch("src.geocoding.requests.get")
def test_geocode_one_malformed_center_returns_none(mock_get):
    """Malformed Mapbox response — feature is missing center — must not crash."""
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"features": [{"context": []}]},  # no center key
    )
    result = geocode_one("Anywhere", token="pk.test")
    assert result is None


@patch("src.geocoding.requests.get")
def test_geocode_one_non_numeric_center_returns_none(mock_get):
    """Mapbox returns center with non-numeric values — must not crash."""
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"features": [{"center": ["not", "a number"]}]},
    )
    result = geocode_one("Anywhere", token="pk.test")
    assert result is None


@patch("src.geocoding.requests.get")
def test_geocode_one_non_json_200_returns_none(mock_get):
    """Mapbox returns 200 with HTML / non-JSON body — must not crash."""
    resp = MagicMock(status_code=200)
    resp.json.side_effect = ValueError("not JSON")
    mock_get.return_value = resp
    result = geocode_one("Anywhere", token="pk.test")
    assert result is None


@patch("src.geocoding.requests.get")
def test_geocode_one_4xx_returns_none(mock_get):
    """4xx HTTP (e.g. 401 invalid token) returns None like 5xx does."""
    mock_get.return_value = MagicMock(status_code=401)
    result = geocode_one("Anywhere", token="pk.test")
    assert result is None


# ────────────────────────── geocode_with_cache ──────────────────────────

from datetime import date

from app import app as flask_app
from models import GeocodeCache, db
from src.geocoding import geocode_with_cache


@pytest.fixture
def app():
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@patch("src.geocoding.requests.get")
def test_geocode_with_cache_miss_then_hit(mock_get, app):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MAPBOX_RESPONSE_OK,
    )

    r1 = geocode_with_cache("Hotel Skansen", db_session=db.session, token="pk.test")
    assert r1.lat == 59.3293
    assert mock_get.call_count == 1

    # Cache row was written.
    row = GeocodeCache.query.filter_by(location_text_normalized="hotel skansen").first()
    assert row is not None
    assert row.lat == 59.3293

    # Same input the second time: HIT — no API call.
    r2 = geocode_with_cache("HOTEL skansen  ", db_session=db.session, token="pk.test")
    assert r2.lat == 59.3293
    assert mock_get.call_count == 1  # still 1, not 2


@patch("src.geocoding.requests.get")
def test_geocode_with_cache_zero_results_writes_nothing(mock_get, app):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MAPBOX_RESPONSE_EMPTY,
    )
    r = geocode_with_cache("Nowhereville", db_session=db.session, token="pk.test")
    assert r is None
    assert GeocodeCache.query.count() == 0


def test_geocode_with_cache_empty_input_returns_none(app):
    r = geocode_with_cache("   ", db_session=db.session, token="pk.test")
    assert r is None
    assert GeocodeCache.query.count() == 0


# ────────────────────────── ensure_geocoded ─────────────────────────────

from datetime import datetime as _dt

from models import Booking, Trip, User
from src.geocoding import ensure_geocoded


@pytest.fixture
def owner(app):
    u = User(google_id="g1", email="o@e.com", name="Owner")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def trip(app, owner):
    t = Trip(owner_id=owner.id, name="T", start_date=date(2026, 6, 1), end_date=date(2026, 6, 10))
    db.session.add(t)
    db.session.commit()
    return t


@patch("src.geocoding.requests.get")
def test_ensure_geocoded_writes_coords_to_rows(mock_get, app, trip):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MAPBOX_RESPONSE_OK,
    )
    b1 = Booking(trip_id=trip.id, type="hotel", title="X", location="Hotel Skansen")
    b2 = Booking(trip_id=trip.id, type="hotel", title="Y", location="Hotel Skansen")
    b3 = Booking(trip_id=trip.id, type="hotel", title="Z", location="")  # no location
    db.session.add_all([b1, b2, b3])
    db.session.commit()

    ensure_geocoded([b1, b2, b3], db_session=db.session, token="pk.test")
    db.session.refresh(b1)
    db.session.refresh(b2)
    db.session.refresh(b3)

    assert b1.geocoded_lat == 59.3293
    assert b1.geocoded_country_code == "SE"
    assert b1.geocoded_city == "Stockholm"
    assert b1.geocoded_at is not None
    assert b1.geocoded_manually is False

    assert b2.geocoded_lat == 59.3293          # same coords (cache hit)
    assert b3.geocoded_lat is None              # no location ⇒ skipped

    # Only ONE Mapbox API call total (b1 → API; b2 → cache; b3 → skipped).
    assert mock_get.call_count == 1


@patch("src.geocoding.requests.get")
def test_ensure_geocoded_skips_already_geocoded_rows(mock_get, app, trip):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: MAPBOX_RESPONSE_OK)
    b = Booking(
        trip_id=trip.id, type="hotel", title="X", location="Already Done",
        geocoded_lat=1.0, geocoded_lng=2.0, geocoded_at=_dt(2026, 5, 1, 12, 0),
    )
    db.session.add(b)
    db.session.commit()

    ensure_geocoded([b], db_session=db.session, token="pk.test")

    assert mock_get.call_count == 0   # didn't even try.
    assert b.geocoded_lat == 1.0      # unchanged.

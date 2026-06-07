"""Unit tests for src/weather.py."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from app import app as flask_app
from models import WeatherCache, db
from src.weather import (
    CACHE_TTL_SECONDS,
    DEFAULT_EMOJI,
    DayForecast,
    cache_key_for,
    fetch_forecast,
    format_temperature,
    get_forecast_for_day,
    is_in_forecast_window,
    pick_day_coords,
    wmo_code_to_emoji,
)


@pytest.fixture
def app():
    """Fresh in-memory DB schema for cache-layer tests."""
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


# ─────────────────────────────  fakes  ────────────────────────────────


@dataclass
class FakeRow:
    """Stand-in for an itinerary item / booking with geocode columns."""

    geocoded_lat: Optional[float] = None
    geocoded_lng: Optional[float] = None


# ─────────────────────────  wmo_code_to_emoji  ────────────────────────


def test_wmo_code_to_emoji_known_code():
    assert wmo_code_to_emoji(0) == "☀️"
    assert wmo_code_to_emoji(61) == "🌧️"


def test_wmo_code_to_emoji_unknown_returns_default():
    assert wmo_code_to_emoji(999) == DEFAULT_EMOJI


def test_wmo_code_to_emoji_boundary_codes():
    # Both ends of the lookup table should map (not the default).
    assert wmo_code_to_emoji(0) != DEFAULT_EMOJI
    assert wmo_code_to_emoji(99) != DEFAULT_EMOJI


# ────────────────────────  is_in_forecast_window  ─────────────────────


def test_is_in_forecast_window_today_is_in():
    today = date(2026, 6, 7)
    assert is_in_forecast_window(today, today) is True


def test_is_in_forecast_window_last_day_in_window():
    today = date(2026, 6, 7)
    assert is_in_forecast_window(date(2026, 6, 20), today) is True  # +13


def test_is_in_forecast_window_one_past_window_excluded():
    today = date(2026, 6, 7)
    assert is_in_forecast_window(date(2026, 6, 21), today) is False  # +14


def test_is_in_forecast_window_yesterday_excluded():
    today = date(2026, 6, 7)
    assert is_in_forecast_window(date(2026, 6, 6), today) is False


# ──────────────────────────  cache_key_for  ───────────────────────────


def test_cache_key_for_rounds_to_two_decimals():
    key = cache_key_for(48.85661, 2.35222, date(2026, 6, 7), "celsius")
    assert key == (48.86, 2.35, date(2026, 6, 7), "celsius")


def test_cache_key_for_includes_unit():
    k1 = cache_key_for(0.0, 0.0, date(2026, 6, 7), "celsius")
    k2 = cache_key_for(0.0, 0.0, date(2026, 6, 7), "fahrenheit")
    assert k1 != k2
    assert k1[3] == "celsius"
    assert k2[3] == "fahrenheit"


def test_cache_key_for_negative_coords():
    key = cache_key_for(-22.911, -43.179, date(2026, 6, 7), "celsius")
    assert key[0] == -22.91
    assert key[1] == -43.18


# ────────────────────────  format_temperature  ────────────────────────


def test_format_temperature_celsius_integer():
    assert format_temperature(14.0, "celsius") == "14°"


def test_format_temperature_fahrenheit_integer():
    assert format_temperature(57.0, "fahrenheit") == "57°"


def test_format_temperature_fractional_rounds():
    assert format_temperature(14.6, "celsius") == "15°"
    assert format_temperature(14.4, "celsius") == "14°"


def test_format_temperature_subzero():
    assert format_temperature(-3.0, "celsius") == "-3°"
    assert format_temperature(-0.4, "celsius") == "0°"


# ─────────────────────────  pick_day_coords  ──────────────────────────


def test_pick_day_coords_first_item_wins():
    items = [
        FakeRow(geocoded_lat=48.85, geocoded_lng=2.35),
        FakeRow(geocoded_lat=40.71, geocoded_lng=-74.00),
    ]
    assert pick_day_coords(items, None) == (48.85, 2.35)


def test_pick_day_coords_skips_items_without_coords():
    items = [
        FakeRow(geocoded_lat=None, geocoded_lng=None),
        FakeRow(geocoded_lat=48.85, geocoded_lng=2.35),
    ]
    assert pick_day_coords(items, None) == (48.85, 2.35)


def test_pick_day_coords_falls_back_to_trip_coords():
    items = [FakeRow()]
    assert pick_day_coords(items, (51.5, -0.1)) == (51.5, -0.1)


def test_pick_day_coords_returns_none_when_nothing_available():
    items = [FakeRow()]
    assert pick_day_coords(items, None) is None


def test_pick_day_coords_uses_tuple_fallback():
    # Empty item list + tuple fallback.
    assert pick_day_coords([], (10.0, 20.0)) == (10.0, 20.0)


# ───────────────────────────  DayForecast  ────────────────────────────


def test_day_forecast_dataclass_shape():
    fc = DayForecast(
        date=date(2026, 6, 7),
        high=22.0,
        low=14.0,
        temp_unit="celsius",
        wmo_code=2,
        emoji="⛅",
        precipitation_probability=20,
        humidity=64,
        hourly=[{"hour": 12, "temp": 18.0, "code": 0}],
    )
    assert fc.high == 22.0
    assert fc.emoji == "⛅"


# ──────────────────────────  fetch_forecast  ──────────────────────────


@patch("src.weather.requests.get")
def test_fetch_forecast_success_returns_dict(mock_get):
    payload = {
        "daily": {
            "time": ["2026-06-07"],
            "temperature_2m_max": [22.0],
            "temperature_2m_min": [14.0],
            "weather_code": [2],
        },
    }
    mock_get.return_value = MagicMock(status_code=200, json=lambda: payload)
    result = fetch_forecast(
        48.85, 2.35, unit="metric",
        start_date=date(2026, 6, 7), end_date=date(2026, 6, 7),
    )
    assert result == payload
    assert mock_get.called
    # Verify the call passed the right unit param.
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["params"]["temperature_unit"] == "celsius"


@patch("src.weather.requests.get")
def test_fetch_forecast_5xx_returns_none(mock_get):
    mock_get.return_value = MagicMock(status_code=503, json=lambda: {})
    result = fetch_forecast(
        48.85, 2.35, unit="metric",
        start_date=date(2026, 6, 7), end_date=date(2026, 6, 7),
    )
    assert result is None


@patch("src.weather.requests.get")
def test_fetch_forecast_network_error_returns_none(mock_get):
    mock_get.side_effect = requests.RequestException("boom")
    result = fetch_forecast(
        48.85, 2.35, unit="imperial",
        start_date=date(2026, 6, 7), end_date=date(2026, 6, 7),
    )
    assert result is None


# ─────────────────────────  get_forecast_for_day  ─────────────────────


def _ok_payload(d: date) -> dict:
    """Build a minimal Open-Meteo response covering one day."""
    iso = d.isoformat()
    hours = [
        f"{iso}T{h:02d}:00" for h in range(24)
    ]
    return {
        "daily": {
            "time": [iso],
            "weather_code": [2],
            "temperature_2m_max": [22.0],
            "temperature_2m_min": [14.0],
            "precipitation_probability_max": [20],
            "relative_humidity_2m_mean": [64],
        },
        "hourly": {
            "time": hours,
            "temperature_2m": [h + 10.0 for h in range(24)],
            "weather_code": [0] * 24,
        },
    }


@patch("src.weather.fetch_forecast")
def test_get_forecast_for_day_cache_hit_no_api_call(mock_fetch, app):
    # Pre-seed a fresh cache row.
    db.session.add(WeatherCache(
        lat_rounded=48.85, lng_rounded=2.35,
        forecast_date=date(2026, 6, 7),
        temp_unit="celsius",
        high_temp=22.0, low_temp=14.0,
        precipitation_probability=20, humidity=64,
        wmo_code=2, hourly_json="[]",
        fetched_at=datetime.utcnow(),
    ))
    db.session.commit()

    fc = get_forecast_for_day(
        48.85, 2.35, date(2026, 6, 7),
        unit="metric", db_session=db.session,
    )
    assert fc is not None
    assert fc.high == 22.0
    assert fc.emoji == "⛅"  # WMO 2 = partly cloudy
    assert mock_fetch.called is False


@patch("src.weather.fetch_forecast")
def test_get_forecast_for_day_cache_miss_fetches_and_writes(mock_fetch, app):
    mock_fetch.return_value = _ok_payload(date(2026, 6, 7))
    fc = get_forecast_for_day(
        48.85, 2.35, date(2026, 6, 7),
        unit="metric", db_session=db.session,
    )
    assert fc is not None
    assert fc.high == 22.0
    assert mock_fetch.called

    rows = WeatherCache.query.all()
    assert len(rows) == 1
    assert rows[0].temp_unit == "celsius"


@patch("src.weather.fetch_forecast")
def test_get_forecast_for_day_stale_cache_refetches(mock_fetch, app):
    # Insert a stale row (older than TTL).
    stale_time = datetime.utcnow() - timedelta(seconds=CACHE_TTL_SECONDS + 60)
    db.session.add(WeatherCache(
        lat_rounded=48.85, lng_rounded=2.35,
        forecast_date=date(2026, 6, 7),
        temp_unit="celsius",
        high_temp=1.0, low_temp=0.0,  # obviously bogus / old
        precipitation_probability=0, humidity=0,
        wmo_code=0, hourly_json="[]",
        fetched_at=stale_time,
    ))
    db.session.commit()

    mock_fetch.return_value = _ok_payload(date(2026, 6, 7))
    fc = get_forecast_for_day(
        48.85, 2.35, date(2026, 6, 7),
        unit="metric", db_session=db.session,
    )
    assert fc is not None
    assert fc.high == 22.0  # refreshed, not the stale 1.0
    assert mock_fetch.called

    rows = WeatherCache.query.all()
    assert len(rows) == 1
    assert rows[0].high_temp == 22.0


@patch("src.weather.fetch_forecast")
def test_get_forecast_for_day_api_failure_returns_none(mock_fetch, app):
    mock_fetch.return_value = None  # simulate failure
    fc = get_forecast_for_day(
        48.85, 2.35, date(2026, 6, 7),
        unit="metric", db_session=db.session,
    )
    assert fc is None
    assert WeatherCache.query.count() == 0


@patch("src.weather.fetch_forecast")
def test_get_forecast_for_day_different_unit_separate_cache(mock_fetch, app):
    payload = _ok_payload(date(2026, 6, 7))
    mock_fetch.return_value = payload

    fc_m = get_forecast_for_day(
        48.85, 2.35, date(2026, 6, 7),
        unit="metric", db_session=db.session,
    )
    fc_i = get_forecast_for_day(
        48.85, 2.35, date(2026, 6, 7),
        unit="imperial", db_session=db.session,
    )
    assert fc_m is not None and fc_i is not None
    assert mock_fetch.call_count == 2  # one per unit

    units = {r.temp_unit for r in WeatherCache.query.all()}
    assert units == {"celsius", "fahrenheit"}

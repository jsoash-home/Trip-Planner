"""
src/weather.py — Open-Meteo forecast client + WeatherCache helpers.

Mix of pure helpers (testable without network/DB) and impure helpers
(API + cache layer). Tests in tests/test_weather.py mock requests.get
so the suite never hits the network.

Pattern mirrored on src/geocoding.py: external API + cache table +
freshness check. No API key required — Open-Meteo is free and
non-authenticated.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 5.0
HOURLY_SLOT_HOURS = (6, 12, 18, 22)


# Map Open-Meteo WMO weather codes → display emoji. Source:
# https://open-meteo.com/en/docs (Weather variable documentation).
WMO_TO_EMOJI: Dict[int, str] = {
    0: "☀️",      # Clear sky
    1: "🌤️",      # Mainly clear
    2: "⛅",       # Partly cloudy
    3: "☁️",      # Overcast
    45: "🌫️",     # Fog
    48: "🌫️",     # Depositing rime fog
    51: "🌦️",     # Drizzle: light
    53: "🌦️",     # Drizzle: moderate
    55: "🌧️",     # Drizzle: dense
    56: "🌧️",     # Freezing drizzle: light
    57: "🌧️",     # Freezing drizzle: dense
    61: "🌧️",     # Rain: slight
    63: "🌧️",     # Rain: moderate
    65: "🌧️",     # Rain: heavy
    66: "🌧️",     # Freezing rain: light
    67: "🌧️",     # Freezing rain: heavy
    71: "🌨️",     # Snow fall: slight
    73: "🌨️",     # Snow fall: moderate
    75: "🌨️",     # Snow fall: heavy
    77: "🌨️",     # Snow grains
    80: "🌦️",     # Rain showers: slight
    81: "🌧️",     # Rain showers: moderate
    82: "⛈️",     # Rain showers: violent
    85: "🌨️",     # Snow showers: slight
    86: "🌨️",     # Snow showers: heavy
    95: "⛈️",     # Thunderstorm
    96: "⛈️",     # Thunderstorm w/ slight hail
    99: "⛈️",     # Thunderstorm w/ heavy hail
}
DEFAULT_EMOJI = "🌡️"
DEFAULT_WINDOW_DAYS = 14
CACHE_TTL_SECONDS = 6 * 60 * 60


@dataclass
class DayForecast:
    """One day's forecast — what the chip + popover render from."""

    date: date
    high: float
    low: float
    temp_unit: str            # "celsius" | "fahrenheit"
    wmo_code: int
    emoji: str
    precipitation_probability: Optional[int]
    humidity: Optional[int]
    hourly: List[Dict]        # 4-slot [{"hour": int, "temp": float, "code": int}]


# ──────────────────────────  pure helpers  ────────────────────────────


def wmo_code_to_emoji(code: int) -> str:
    """Return the emoji for an Open-Meteo WMO weather code, or the
    default thermometer when the code isn't in the lookup table."""
    return WMO_TO_EMOJI.get(code, DEFAULT_EMOJI)


def is_in_forecast_window(
    d: date, today: date, window_days: int = DEFAULT_WINDOW_DAYS,
) -> bool:
    """True iff `today <= d <= today + window_days - 1` (inclusive)."""
    if d < today:
        return False
    return (d - today).days <= window_days - 1


def cache_key_for(
    lat: float, lng: float, d: date, unit: str,
) -> Tuple[float, float, date, str]:
    """Build the four-part cache key: rounded coords, date, unit.

    2 decimal places ≈ 1.1 km — fine for daily weather. Coalesces
    items in the same city to a single cache row.
    """
    return (round(lat, 2), round(lng, 2), d, unit)


def format_temperature(value: float, unit: str) -> str:
    """Format as `"14°"`. The unit (C/F) is implied by page context."""
    # `unit` is part of the signature so callers can't accidentally
    # forget which way to read the value; we don't print a suffix.
    _ = unit
    return f"{int(round(value))}°"


def pick_day_coords(items_for_day, trip_fallback_coords):
    """Return `(lat, lng)` for the first item with geocoded coords,
    or the trip fallback tuple, or `None` if neither is available."""
    for item in items_for_day or []:
        lat = getattr(item, "geocoded_lat", None)
        lng = getattr(item, "geocoded_lng", None)
        if lat is not None and lng is not None:
            return (lat, lng)
    return trip_fallback_coords or None


# ──────────────────────────  Open-Meteo API  ──────────────────────────


def _unit_to_temperature_param(unit: str) -> str:
    """Map our internal 'metric'/'imperial' label to Open-Meteo's API
    `temperature_unit` parameter value."""
    return "fahrenheit" if unit == "imperial" else "celsius"


def fetch_forecast(
    lat: float,
    lng: float,
    *,
    unit: str,
    start_date: date,
    end_date: date,
) -> Optional[dict]:
    """Single Open-Meteo API call. Returns the raw JSON dict on 200;
    `None` on network failure, non-200, or malformed JSON. Five-second
    timeout. Never raises.

    `unit` is "metric" or "imperial"; we translate to Open-Meteo's
    own `temperature_unit` query param at call time.
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,relative_humidity_2m_mean"
        ),
        "hourly": "temperature_2m,weather_code",
        "temperature_unit": _unit_to_temperature_param(unit),
        "timezone": "auto",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logger.warning("Open-Meteo network error for (%s, %s): %s", lat, lng, e)
        return None
    if resp.status_code != 200:
        logger.warning(
            "Open-Meteo returned %s for (%s, %s)", resp.status_code, lat, lng,
        )
        return None
    try:
        return resp.json()
    except ValueError as e:
        logger.warning("Open-Meteo returned non-JSON for (%s, %s): %s", lat, lng, e)
        return None


# ──────────────────────────  cache wrapper  ───────────────────────────


def _extract_hourly_micro_strip(payload: dict, d: date) -> List[Dict]:
    """Pick 4 hourly samples (06/12/18/22 local) from an Open-Meteo
    response. Returns [] when the hourly arrays are missing or
    incomplete — callers persist this as an empty list."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    iso_prefix = d.isoformat() + "T"
    out: List[Dict] = []
    for i, t in enumerate(times):
        if not isinstance(t, str) or not t.startswith(iso_prefix):
            continue
        try:
            hour = int(t.split("T", 1)[1].split(":", 1)[0])
        except (ValueError, IndexError):
            continue
        if hour in HOURLY_SLOT_HOURS:
            if i >= len(temps) or i >= len(codes):
                continue
            out.append({"hour": hour, "temp": temps[i], "code": codes[i]})
    return out


def _row_to_forecast(row) -> DayForecast:
    """Build a DayForecast from a WeatherCache row."""
    try:
        hourly = json.loads(row.hourly_json) if row.hourly_json else []
    except ValueError:
        hourly = []
    return DayForecast(
        date=row.forecast_date,
        high=row.high_temp,
        low=row.low_temp,
        temp_unit=row.temp_unit,
        wmo_code=row.wmo_code,
        emoji=wmo_code_to_emoji(row.wmo_code),
        precipitation_probability=row.precipitation_probability,
        humidity=row.humidity,
        hourly=hourly,
    )


def get_forecast_for_day(
    lat: float,
    lng: float,
    d: date,
    *,
    unit: str,
    db_session,
) -> Optional[DayForecast]:
    """Cache-first day forecast. Returns `None` on cache miss whose
    upstream API call also fails. Imported lazily inside the function
    so this module doesn't require Flask at import time.

    Side effect: writes a fresh `WeatherCache` row on successful fetch.
    Stale rows are overwritten, not deleted.
    """
    from models import WeatherCache  # avoid circular import at module load
    from sqlalchemy.exc import IntegrityError

    temp_unit = _unit_to_temperature_param(unit)
    lat_r, lng_r, _, _ = cache_key_for(lat, lng, d, temp_unit)
    cutoff = datetime.utcnow() - timedelta(seconds=CACHE_TTL_SECONDS)

    existing = WeatherCache.query.filter_by(
        lat_rounded=lat_r,
        lng_rounded=lng_r,
        forecast_date=d,
        temp_unit=temp_unit,
    ).one_or_none()

    if existing and existing.fetched_at >= cutoff:
        return _row_to_forecast(existing)

    payload = fetch_forecast(
        lat_r, lng_r, unit=unit, start_date=d, end_date=d,
    )
    if not payload:
        return None

    daily = payload.get("daily") or {}
    try:
        high = float(daily["temperature_2m_max"][0])
        low = float(daily["temperature_2m_min"][0])
        wmo = int(daily["weather_code"][0])
    except (KeyError, IndexError, ValueError, TypeError) as e:
        logger.warning("Open-Meteo daily missing core fields for (%s, %s): %s", lat, lng, e)
        return None

    precip = daily.get("precipitation_probability_max") or [None]
    humid = daily.get("relative_humidity_2m_mean") or [None]
    precip_val = precip[0] if precip else None
    humid_val = humid[0] if humid else None
    hourly = _extract_hourly_micro_strip(payload, d)
    hourly_json = json.dumps(hourly)

    now = datetime.utcnow()
    if existing:
        existing.high_temp = high
        existing.low_temp = low
        existing.precipitation_probability = (
            int(precip_val) if precip_val is not None else None
        )
        existing.humidity = (
            int(humid_val) if humid_val is not None else None
        )
        existing.wmo_code = wmo
        existing.hourly_json = hourly_json
        existing.fetched_at = now
        row = existing
    else:
        row = WeatherCache(
            lat_rounded=lat_r, lng_rounded=lng_r,
            forecast_date=d, temp_unit=temp_unit,
            high_temp=high, low_temp=low,
            precipitation_probability=(
                int(precip_val) if precip_val is not None else None
            ),
            humidity=(
                int(humid_val) if humid_val is not None else None
            ),
            wmo_code=wmo,
            hourly_json=hourly_json,
            fetched_at=now,
        )
        db_session.add(row)
    try:
        db_session.commit()
    except IntegrityError:
        # Race condition: another request inserted the same key first.
        # Rollback and re-query — return whatever's there.
        db_session.rollback()
        winner = WeatherCache.query.filter_by(
            lat_rounded=lat_r, lng_rounded=lng_r,
            forecast_date=d, temp_unit=temp_unit,
        ).one_or_none()
        if winner is None:
            return None
        return _row_to_forecast(winner)

    return _row_to_forecast(row)

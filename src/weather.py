"""
src/weather.py — Open-Meteo forecast client + WeatherCache helpers.

Mix of pure helpers (testable without network/DB) and impure helpers
(API + cache layer). Tests in tests/test_weather.py mock requests.get
so the suite never hits the network.

Pattern mirrored on src/geocoding.py: external API + cache table +
freshness check. No API key required — Open-Meteo is free and
non-authenticated.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 5.0


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

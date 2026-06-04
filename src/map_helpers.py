"""Pure helpers for the map-view feature.

NO DB or network calls — pure functions and dataclasses only.
Anything that touches Mapbox lives in src/geocoding.py.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────── Pin dataclass ────────────────────────


@dataclass
class Pin:
    """One pin on a map, irrespective of which surface (in-trip or lifetime).

    Built by routes from Booking / ItineraryItem rows that have non-empty
    location + geocoded_lat. Consumed by `pins_to_geojson`.
    """

    row_type: str                          # "booking" or "item"
    row_id: int
    trip_id: int
    trip_name: str
    title: str
    location_text: str
    lat: float
    lng: float
    geocoded_city: Optional[str]
    geocoded_country_code: Optional[str]   # ISO Alpha-2
    year: int                              # trip.start_date.year
    category: str                          # transit / meal / sightseeing / break / other
    datetime_iso: Optional[str]            # ISO 8601 string, or None
    day_index: Optional[int]               # 1-based, or None for "Anytime"


# ─────────────────────────── normalize_location ──────────────────────


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_location(text: str) -> str:
    """Strip, lowercase, collapse all whitespace runs to single spaces.

    Used both for the GeocodeCache key and for comparing whether two
    user-facing strings refer to the same logical location.
    """
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text.strip().lower())


# ─────────────────────────── should_clear_geocode ────────────────────


def should_clear_geocode(
    old_text: str,
    new_text: str,
    manually_pinned: bool,
) -> bool:
    """When a row's location text is edited, decide whether to clear the
    stored coords (forcing a re-geocode on next map view).

    Rules:
    - If user drag-pinned this row, the user's coords win. Never clear.
    - If the normalized text is unchanged (just whitespace / case),
      don't clear — same logical location.
    - Otherwise, clear.
    """
    if manually_pinned:
        return False
    return normalize_location(old_text) != normalize_location(new_text)


# ─────────────────────────────── palettes ────────────────────────────


# Okabe-Ito-derived 12-color palette. Colorblind-safe.
YEAR_PALETTE: tuple = (
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#999999",  # gray
    "#8C564B",  # brown
    "#9467BD",  # purple
    "#17BECF",  # teal
    "#BCBD22",  # olive
)


# Matches the existing --vp-cat-{name}-fg tokens in static/css/app.css.
CATEGORY_PALETTE: dict = {
    "transit":     "#5B6BC0",
    "meal":        "#E07B5B",
    "sightseeing": "#4CAF82",
    "break":       "#B58CDB",
    "other":       "#7E8AA0",
}


def color_for_year(year: int) -> str:
    """Return a hex color for the given year, cycling through YEAR_PALETTE."""
    return YEAR_PALETTE[year % len(YEAR_PALETTE)]


def color_for_category(category: str) -> str:
    """Return a hex color for an itinerary category. Unknown → 'other'."""
    return CATEGORY_PALETTE.get(category, CATEGORY_PALETTE["other"])


# ───────────────────────────── aggregation helpers ──────────────────


def years_present(pins: List[Pin]) -> List[int]:
    """Return sorted unique years, most recent first."""
    return sorted({p.year for p in pins}, reverse=True)


def stats_for_pins(pins: List[Pin]) -> dict:
    """Compute country / city / trip counts for the lifetime map stats bar."""
    countries = {p.geocoded_country_code for p in pins if p.geocoded_country_code}
    cities = {
        (p.geocoded_city, p.geocoded_country_code)
        for p in pins
        if p.geocoded_city
    }
    trips = {p.trip_id for p in pins}
    return {"countries": len(countries), "cities": len(cities), "trips": len(trips)}


# ───────────────────────────── GeoJSON builder ───────────────────────


def build_static_map_url(
    pins: List[Pin],
    width: int = 600,
    height: int = 360,
    style: str = "streets-v12",
    token: Optional[str] = None,
) -> Optional[str]:
    """Build a Mapbox Static Images API URL with one marker per pin.

    Returns None when there are no pins OR no Mapbox token — both cases
    mean there's nothing to show, and the caller should hide the image.

    URL shape (Mapbox Static Images, ``auto`` viewport):

        https://api.mapbox.com/styles/v1/mapbox/{style}/static
          /{markers}/auto/{width}x{height}@2x?access_token={token}

    `markers` is a comma-separated list of ``pin-s+{color}(lng,lat)``
    entries, where ``color`` is the category color (hex without the
    leading ``#``). The whole markers segment is URL-encoded so the
    parens and commas survive the path.
    """
    if not pins or not token:
        return None

    from urllib.parse import quote

    parts: List[str] = []
    for p in pins:
        hexcolor = color_for_category(p.category).lstrip("#")
        parts.append(f"pin-s+{hexcolor}({p.lng},{p.lat})")
    markers = ",".join(parts)
    markers_enc = quote(markers, safe="")

    return (
        f"https://api.mapbox.com/styles/v1/mapbox/{style}/static/"
        f"{markers_enc}/auto/{width}x{height}@2x?access_token={token}"
    )


def pins_to_geojson(pins: List[Pin], color_fn: Callable[[Pin], str]) -> dict:
    """Build a GeoJSON FeatureCollection. `color_fn` is called per pin.

    For the in-trip map, pass `lambda p: color_for_category(p.category)`.
    For the lifetime map, pass `lambda p: color_for_year(p.year)`.
    """
    features = []
    for p in pins:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [p.lng, p.lat],  # GeoJSON spec: [lng, lat]
            },
            "properties": {
                "row_type": p.row_type,
                "row_id": p.row_id,
                "trip_id": p.trip_id,
                "trip_name": p.trip_name,
                "title": p.title,
                "location_text": p.location_text,
                "geocoded_city": p.geocoded_city,
                "geocoded_country_code": p.geocoded_country_code,
                "year": p.year,
                "category": p.category,
                "datetime_iso": p.datetime_iso,
                "day_index": p.day_index,
                "color": color_fn(p),
            },
        })
    return {"type": "FeatureCollection", "features": features}

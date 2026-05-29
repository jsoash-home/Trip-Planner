"""Mapbox forward-geocoding client + GeocodeCache pipeline.

NOT a pure helper — calls the Mapbox API. Tests in
tests/test_geocoding.py mock `requests.get` so the suite never hits
the network.
"""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

import requests

from src.map_helpers import normalize_location

logger = logging.getLogger(__name__)


MAPBOX_GEOCODE_URL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{q}.json"
REQUEST_TIMEOUT_SECONDS = 5.0


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    city: Optional[str]
    country_code: Optional[str]


def _extract_city_and_country(feature: dict) -> tuple:
    """Pull city + ISO-Alpha-2 country code from a Mapbox feature's context."""
    city = None
    country = None
    for ctx in feature.get("context", []):
        ctx_id = ctx.get("id", "")
        if ctx_id.startswith("place.") and city is None:
            city = ctx.get("text")
        elif ctx_id.startswith("country."):
            short = ctx.get("short_code")
            if short:
                country = short.upper()
    return city, country


def geocode_one(text: str, *, token: str) -> Optional[GeocodeResult]:
    """Call Mapbox forward geocoding for one location string.

    Returns a GeocodeResult, or None on: empty input, zero results,
    API 5xx, network error, missing token.
    """
    if not text or not text.strip():
        return None
    if not token:
        logger.error("geocode_one called without a token")
        return None

    encoded = urllib.parse.quote(text.strip(), safe="")
    url = MAPBOX_GEOCODE_URL.format(q=encoded)
    params = {"access_token": token, "limit": 1, "types": "place,poi,address,locality"}

    logger.info("geocoding: %s", text)
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        logger.error("geocode network error for %r: %s", text, e)
        return None

    if resp.status_code != 200:
        logger.error("geocode HTTP %s for %r", resp.status_code, text)
        return None

    payload = resp.json()
    features = payload.get("features", [])
    if not features:
        logger.warning("geocode 0 results for: %s", text)
        return None

    feat = features[0]
    lng, lat = feat["center"]
    city, country = _extract_city_and_country(feat)
    return GeocodeResult(lat=lat, lng=lng, city=city, country_code=country)


def geocode_with_cache(text: str, *, db_session, token: str) -> Optional[GeocodeResult]:
    """Check GeocodeCache; on miss, call Mapbox and write the result.

    Returns the result (cache hit OR fresh API call), or None on failure.
    """
    from models import GeocodeCache  # local import to avoid a circular import on app boot

    normalized = normalize_location(text)
    if not normalized:
        return None

    cached = GeocodeCache.query.filter_by(location_text_normalized=normalized).first()
    if cached is not None:
        return GeocodeResult(
            lat=cached.lat,
            lng=cached.lng,
            city=cached.city,
            country_code=cached.country_code,
        )

    result = geocode_one(text, token=token)
    if result is None:
        return None

    db_session.add(GeocodeCache(
        location_text_normalized=normalized,
        lat=result.lat,
        lng=result.lng,
        city=result.city,
        country_code=result.country_code,
        provider="mapbox",
        created_at=datetime.utcnow(),
    ))
    db_session.commit()
    return result


def ensure_geocoded(rows: Iterable, *, db_session, token: str) -> None:
    """For each row with non-empty location and missing geocoded_lat,
    look it up in GeocodeCache; on miss, call Mapbox; write coords +
    city + country onto the row. Mutates rows in place. Commits once
    at the end.
    """
    touched = False
    for row in rows:
        loc = (row.location or "").strip()
        if not loc:
            continue
        if row.geocoded_lat is not None and row.geocoded_lng is not None:
            continue

        result = geocode_with_cache(loc, db_session=db_session, token=token)
        if result is None:
            continue

        row.geocoded_lat = result.lat
        row.geocoded_lng = result.lng
        row.geocoded_city = result.city
        row.geocoded_country_code = result.country_code
        row.geocoded_at = datetime.utcnow()
        row.geocoded_manually = False
        touched = True

    if touched:
        db_session.commit()

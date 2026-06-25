"""Walking distance from a hotel to a venue, formatted as an HTML chip.

Pure helpers. No network, no dependencies beyond stdlib `math` and `html`.

The math: haversine_km returns straight-line distance; walking_chip multiplies
by 1.3 to approximate routed walking on a city street grid, divides by 5 km/h
(walking) or 30 km/h (in-city driving), and emits one of three adaptive
formats per the distance band. See
`docs/superpowers/specs/2026-06-25-trip-guide-phase2a-editorial-spine-design.md`
§"Locked design decisions" 2 + 4 for the locked numbers.
"""

import html
import logging
import math
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0  # mean radius; standard for haversine approximation
STREET_MULTIPLIER = 1.3   # straight-line km × 1.3 ≈ routed walking km
WALKING_KMH = 5.0
DRIVING_KMH = 30.0        # in-city driving pace


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def walking_chip(
    venue_coords: Optional[Tuple[float, float]],
    hotel_coords: Optional[Tuple[float, float]],
    hotel_name: str,
) -> str:
    """Return chip HTML or '' when either coord is None."""
    if venue_coords is None or hotel_coords is None:
        return ""

    km_straight = haversine_km(
        venue_coords[0], venue_coords[1], hotel_coords[0], hotel_coords[1]
    )
    km_route = km_straight * STREET_MULTIPLIER
    walk_min = math.ceil(km_route / WALKING_KMH * 60)
    drive_min = math.ceil(km_route / DRIVING_KMH * 60)
    hotel = html.escape(hotel_name)

    if km_route <= 2.0:
        body = f"{walk_min} min walk · {km_route:.1f}km from {hotel}"
    elif km_route <= 5.0:
        body = (
            f"{walk_min} min walk · {km_route:.1f}km · "
            f"or {drive_min} min by car from {hotel}"
        )
    else:
        body = f"{drive_min} min by car · {km_route:.1f}km from {hotel}"

    return f'<span class="walkchip">{body}</span>'

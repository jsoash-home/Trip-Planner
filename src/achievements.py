"""
src/achievements.py

Pure aggregation + badge registry for the user "achievements" view.

Reads across every trip a user owns or collaborates on and produces a
``UserStats`` bundle plus a static list of ``Achievement`` records whose
``predicate(stats)`` decides whether the badge is earned.

Only completed trips (per ``derive_status``) contribute to any stat —
you haven't actually traveled anywhere until the trip's over.

The route in Task 5 renders ``earned(user)`` and ``near_earned(user)``;
nothing here touches Flask, sessions, or templates.
"""

import logging
from datetime import date
from typing import Callable, Dict, List, NamedTuple, Set, Tuple, TypedDict

from models import Booking, ItineraryItem, Trip, TripCollaborator, User
from src.sharing import normalize_email
from src.trip_helpers import derive_status

logger = logging.getLogger(__name__)


# ─── types ───────────────────────────────────────────────────────────────────


class UserStats(TypedDict):
    trips_completed: int
    trips_in_year: Dict[int, int]        # {2026: 5, 2025: 3}
    countries_visited: Set[str]          # 2-letter codes (upper)
    continents_visited: Set[str]         # derived via COUNTRY_TO_CONTINENT
    total_nights: int                    # sum of (end - start).days for completed trips
    solo_trips: int                      # completed trips with 0 collaborators
    group_trips: int                     # completed trips with >=1 collaborator


class Achievement(NamedTuple):
    id: str
    name: str
    description: str
    icon: str                            # single emoji
    predicate: Callable[[UserStats], bool]
    progress: Callable[[UserStats], Tuple[int, int]]  # (current, target)


# ─── country → continent map ─────────────────────────────────────────────────
#
# 7-continent model: AF, AN, AS, EU, NA, OC, SA. Errs on the side of
# completeness for common travel destinations. Missing codes fall
# through to a debug log — see compute_stats().

COUNTRY_TO_CONTINENT: Dict[str, str] = {
    # North America
    "US": "NA", "CA": "NA", "MX": "NA", "GT": "NA", "BZ": "NA", "SV": "NA",
    "HN": "NA", "NI": "NA", "CR": "NA", "PA": "NA", "CU": "NA", "JM": "NA",
    "HT": "NA", "DO": "NA", "PR": "NA", "BS": "NA", "BB": "NA", "TT": "NA",
    "GL": "NA",
    # South America
    "BR": "SA", "AR": "SA", "CL": "SA", "PE": "SA", "CO": "SA", "VE": "SA",
    "EC": "SA", "BO": "SA", "PY": "SA", "UY": "SA", "GY": "SA", "SR": "SA",
    "GF": "SA",
    # Europe
    "GB": "EU", "IE": "EU", "FR": "EU", "DE": "EU", "IT": "EU", "ES": "EU",
    "PT": "EU", "NL": "EU", "BE": "EU", "LU": "EU", "CH": "EU", "AT": "EU",
    "DK": "EU", "SE": "EU", "NO": "EU", "FI": "EU", "IS": "EU", "PL": "EU",
    "CZ": "EU", "SK": "EU", "HU": "EU", "RO": "EU", "BG": "EU", "GR": "EU",
    "HR": "EU", "SI": "EU", "RS": "EU", "BA": "EU", "ME": "EU", "MK": "EU",
    "AL": "EU", "EE": "EU", "LV": "EU", "LT": "EU", "BY": "EU", "UA": "EU",
    "MD": "EU", "RU": "EU", "MT": "EU", "CY": "EU", "VA": "EU", "SM": "EU",
    "MC": "EU", "LI": "EU", "AD": "EU", "XK": "EU", "TR": "EU",
    # Asia
    "JP": "AS", "CN": "AS", "KR": "AS", "KP": "AS", "TW": "AS", "HK": "AS",
    "MO": "AS", "MN": "AS", "VN": "AS", "TH": "AS", "LA": "AS", "KH": "AS",
    "MM": "AS", "MY": "AS", "SG": "AS", "ID": "AS", "PH": "AS", "BN": "AS",
    "TL": "AS", "IN": "AS", "PK": "AS", "BD": "AS", "NP": "AS", "BT": "AS",
    "LK": "AS", "MV": "AS", "AF": "AS", "IR": "AS", "IQ": "AS", "SY": "AS",
    "LB": "AS", "JO": "AS", "IL": "AS", "PS": "AS", "SA": "AS", "YE": "AS",
    "OM": "AS", "AE": "AS", "QA": "AS", "BH": "AS", "KW": "AS", "KZ": "AS",
    "UZ": "AS", "TM": "AS", "KG": "AS", "TJ": "AS", "AZ": "AS", "AM": "AS",
    "GE": "AS",
    # Africa
    "EG": "AF", "LY": "AF", "TN": "AF", "DZ": "AF", "MA": "AF", "EH": "AF",
    "SD": "AF", "SS": "AF", "ET": "AF", "ER": "AF", "DJ": "AF", "SO": "AF",
    "KE": "AF", "UG": "AF", "TZ": "AF", "RW": "AF", "BI": "AF", "MZ": "AF",
    "MW": "AF", "ZM": "AF", "ZW": "AF", "BW": "AF", "NA": "AF", "ZA": "AF",
    "LS": "AF", "SZ": "AF", "MG": "AF", "MU": "AF", "SC": "AF", "KM": "AF",
    "AO": "AF", "CD": "AF", "CG": "AF", "GA": "AF", "GQ": "AF", "CM": "AF",
    "CF": "AF", "TD": "AF", "NE": "AF", "NG": "AF", "BJ": "AF", "TG": "AF",
    "GH": "AF", "CI": "AF", "LR": "AF", "SL": "AF", "GN": "AF", "GW": "AF",
    "SN": "AF", "GM": "AF", "ML": "AF", "BF": "AF", "MR": "AF", "CV": "AF",
    "ST": "AF",
    # Oceania
    "AU": "OC", "NZ": "OC", "PG": "OC", "FJ": "OC", "SB": "OC", "VU": "OC",
    "NC": "OC", "PF": "OC", "WS": "OC", "TO": "OC", "KI": "OC", "TV": "OC",
    "NR": "OC", "PW": "OC", "FM": "OC", "MH": "OC", "GU": "OC", "MP": "OC",
    "AS": "OC", "CK": "OC", "NU": "OC",
    # Antarctica
    "AQ": "AN",
}


# ─── aggregation ─────────────────────────────────────────────────────────────


def _trips_for_user(user: User) -> List[Trip]:
    """Every trip the user owns OR collaborates on, deduped by trip.id.

    Mirrors ``src/ical_feed._trips_for_user`` — kept as a small local
    helper rather than importing the private one so a change to iCal's
    scoping doesn't silently shift what counts toward a badge.
    """
    owned = Trip.query.filter_by(owner_id=user.id).all()

    email = normalize_email(user.email or "")
    if email:
        collab_ids = [
            row.trip_id
            for row in TripCollaborator.query.filter_by(email=email).all()
        ]
        collab_trips = (
            Trip.query.filter(Trip.id.in_(collab_ids)).all()
            if collab_ids
            else []
        )
    else:
        collab_trips = []

    by_id: Dict[int, Trip] = {t.id: t for t in owned}
    for t in collab_trips:
        by_id.setdefault(t.id, t)
    return list(by_id.values())


def _country_codes_for_trip(trip: Trip) -> Set[str]:
    """Union of geocoded_country_code across a trip's bookings + itinerary items.

    Codes are upper-cased. NULLs are skipped. Uses tight per-trip queries
    so the caller doesn't have to load every row across every trip up
    front. For a beginner-owned app with <100 trips this readability
    beats a single-query micro-optimization.
    """
    codes: Set[str] = set()

    booking_rows = (
        Booking.query
        .with_entities(Booking.geocoded_country_code)
        .filter(Booking.trip_id == trip.id)
        .filter(Booking.geocoded_country_code.isnot(None))
        .all()
    )
    for (code,) in booking_rows:
        if code:
            codes.add(code.upper())

    item_rows = (
        ItineraryItem.query
        .with_entities(ItineraryItem.geocoded_country_code)
        .filter(ItineraryItem.trip_id == trip.id)
        .filter(ItineraryItem.geocoded_country_code.isnot(None))
        .all()
    )
    for (code,) in item_rows:
        if code:
            codes.add(code.upper())

    return codes


def compute_stats(user: User) -> UserStats:
    """Aggregate lifetime travel stats for one user.

    Only trips whose ``derive_status(start, end, today) == "completed"``
    contribute. Planning / booked / in-progress trips are skipped — the
    user hasn't traveled yet, so no badge yet.
    """
    today = date.today()

    trips_completed = 0
    trips_in_year: Dict[int, int] = {}
    countries_visited: Set[str] = set()
    continents_visited: Set[str] = set()
    total_nights = 0
    solo_trips = 0
    group_trips = 0

    for trip in _trips_for_user(user):
        if derive_status(trip.start_date, trip.end_date, today) != "completed":
            continue

        trips_completed += 1

        year = trip.start_date.year
        trips_in_year[year] = trips_in_year.get(year, 0) + 1

        codes = _country_codes_for_trip(trip)
        for code in codes:
            countries_visited.add(code)
            continent = COUNTRY_TO_CONTINENT.get(code)
            if continent is None:
                logger.debug(
                    "no continent mapping for country code %r (trip %s)",
                    code, trip.id,
                )
                continue
            continents_visited.add(continent)

        total_nights += (trip.end_date - trip.start_date).days

        # N+1 per trip — fine for <100 trips and reads clearly.
        collab_count = TripCollaborator.query.filter_by(trip_id=trip.id).count()
        if collab_count == 0:
            solo_trips += 1
        else:
            group_trips += 1

    return {
        "trips_completed": trips_completed,
        "trips_in_year": trips_in_year,
        "countries_visited": countries_visited,
        "continents_visited": continents_visited,
        "total_nights": total_nights,
        "solo_trips": solo_trips,
        "group_trips": group_trips,
    }


# ─── registry ────────────────────────────────────────────────────────────────


def _max_year_count(s: UserStats) -> int:
    """Peak trips-in-a-single-year. 0 when the user has no completed trips."""
    return max(s["trips_in_year"].values(), default=0)


def all_achievements() -> List[Achievement]:
    """Every badge, in stable render order. Predicates read UserStats only."""
    return [
        Achievement(
            id="first_trip",
            name="First Trip",
            description="Completed your first trip",
            icon="🎒",
            predicate=lambda s: s["trips_completed"] >= 1,
            progress=lambda s: (min(s["trips_completed"], 1), 1),
        ),
        Achievement(
            id="countries_5",
            name="Five Countries",
            description="Visited 5 different countries",
            icon="🌍",
            predicate=lambda s: len(s["countries_visited"]) >= 5,
            progress=lambda s: (min(len(s["countries_visited"]), 5), 5),
        ),
        Achievement(
            id="countries_10",
            name="Ten and Counting",
            description="Visited 10 different countries",
            icon="🗺️",
            predicate=lambda s: len(s["countries_visited"]) >= 10,
            progress=lambda s: (min(len(s["countries_visited"]), 10), 10),
        ),
        Achievement(
            id="countries_25",
            name="Quarter-Century Club",
            description="Visited 25 different countries",
            icon="🌐",
            predicate=lambda s: len(s["countries_visited"]) >= 25,
            progress=lambda s: (min(len(s["countries_visited"]), 25), 25),
        ),
        Achievement(
            id="continents_all",
            name="All Seven",
            description="Visited all 7 continents",
            icon="🏆",
            predicate=lambda s: len(s["continents_visited"]) >= 7,
            progress=lambda s: (len(s["continents_visited"]), 7),
        ),
        Achievement(
            id="five_trip_year",
            name="Road Warrior",
            description="Completed 5 trips in a single year",
            icon="✈️",
            predicate=lambda s: _max_year_count(s) >= 5,
            progress=lambda s: (min(_max_year_count(s), 5), 5),
        ),
        Achievement(
            id="nights_30",
            name="Month on the Road",
            description="Spent 30 nights traveling",
            icon="🌙",
            predicate=lambda s: s["total_nights"] >= 30,
            progress=lambda s: (min(s["total_nights"], 30), 30),
        ),
        Achievement(
            id="nights_100",
            name="Century of Nights",
            description="Spent 100 nights traveling",
            icon="💯",
            predicate=lambda s: s["total_nights"] >= 100,
            progress=lambda s: (min(s["total_nights"], 100), 100),
        ),
        Achievement(
            id="solo_5",
            name="Lone Wanderer",
            description="Completed 5 solo trips",
            icon="🚶",
            predicate=lambda s: s["solo_trips"] >= 5,
            progress=lambda s: (min(s["solo_trips"], 5), 5),
        ),
        Achievement(
            id="group_5",
            name="Squad Traveler",
            description="Completed 5 group trips",
            icon="🎉",
            predicate=lambda s: s["group_trips"] >= 5,
            progress=lambda s: (min(s["group_trips"], 5), 5),
        ),
    ]


def earned(user: User) -> List[Achievement]:
    """Every achievement the user has already earned, in registry order."""
    stats = compute_stats(user)
    return [a for a in all_achievements() if a.predicate(stats)]


def near_earned(
    user: User, limit: int = 3
) -> List[Tuple[Achievement, int, int]]:
    """Up to ``limit`` not-yet-earned achievements the user is closest to.

    Ranked by ``current / target`` descending. Skips achievements the
    user is at 0 progress on (nothing to show — user is nowhere near it).
    """
    stats = compute_stats(user)
    candidates: List[Tuple[Achievement, int, int]] = []
    for ach in all_achievements():
        if ach.predicate(stats):
            continue
        current, target = ach.progress(stats)
        if current <= 0:
            continue
        candidates.append((ach, current, target))

    candidates.sort(key=lambda triple: triple[1] / triple[2], reverse=True)
    return candidates[:limit]

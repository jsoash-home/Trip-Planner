"""guide_builder — DB read + file IO + share-token plumbing for the trip-guide skill.

The skill (.claude/skills/trip-guide/SKILL.md) calls into this module. Helpers
are deliberately small and tested. HTML composition lives in the skill, not here.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GUIDES_DIR = Path("data/guides")
CONFIG_SCHEMA_VERSION = 1
SECTION_KEYS = (
    "day_by_day",
    "field_guide",
    "things_to_do",
    "weather",
    "history",
    "fun_facts",
    "food",
)
GUIDE_STORAGE = os.getenv("GUIDE_STORAGE", "filesystem")


class GuideError(Exception):
    """Base error for guide_builder."""


class TripNotFound(GuideError):
    """Trip ID does not exist."""


class GuideMissing(GuideError):
    """No guide HTML found for this trip."""


@dataclass
class GuideConfig:
    schema_version: int
    trip_id: int
    sections: List[str]
    palette: Dict[str, Any]
    last_generated_at: Optional[str]


def _fresh_config(trip_id: int) -> "GuideConfig":
    return GuideConfig(
        schema_version=CONFIG_SCHEMA_VERSION,
        trip_id=trip_id,
        sections=[],
        palette={},
        last_generated_at=None,
    )


def load_or_init_config(trip_id: int) -> "GuideConfig":
    """
    Read data/guides/<trip_id>.config.json; return a fresh empty
    GuideConfig if the file is missing, corrupt, or has a mismatched
    schema_version (logs a warning in the latter two cases).
    """
    path = GUIDES_DIR / f"{trip_id}.config.json"
    if not path.exists():
        return _fresh_config(trip_id)

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("guide_builder: corrupt config for trip %s: %s", trip_id, exc)
        return _fresh_config(trip_id)

    if data.get("schema_version") != CONFIG_SCHEMA_VERSION:
        logger.warning(
            "guide_builder: schema_version mismatch for trip %s (got %s, expected %s)",
            trip_id,
            data.get("schema_version"),
            CONFIG_SCHEMA_VERSION,
        )
        return _fresh_config(trip_id)

    return GuideConfig(
        schema_version=data["schema_version"],
        trip_id=data["trip_id"],
        sections=data.get("sections", []),
        palette=data.get("palette", {}),
        last_generated_at=data.get("last_generated_at"),
    )


def save_config(trip_id: int, config: "GuideConfig") -> Path:
    """
    Write the config to data/guides/<trip_id>.config.json.
    Atomic write (temp file + os.replace). Creates the directory if
    needed. Returns the written path.
    """
    path = GUIDES_DIR / f"{trip_id}.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.parent / f"{trip_id}.config.json.tmp"
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(asdict(config), fh, indent=2)

    os.replace(tmp_path, path)
    return path


def load_trip_data(trip_id: int) -> Dict[str, Any]:
    """
    Return {"trip": dict, "bookings": [dict, ...], "itinerary": [dict, ...],
            "collaborators": [dict, ...]} for the given trip.

    Itinerary is pre-sorted by day_date ascending, then by sort_within_day
    rules. Bookings include a "linked_itinerary_ids" field listing any
    ItineraryItem.id rows whose linked_booking_id points back at the booking.

    Raises TripNotFound if no row exists.
    """
    # Deferred imports — top-level would cause a circular import via models → app → src/guide_builder.
    from models import Booking, ItineraryItem, Trip, TripCollaborator
    from src.itinerary import sort_within_day
    from src.trip_helpers import emoji_theme

    trip = Trip.query.get(trip_id)
    if trip is None:
        raise TripNotFound(f"Trip {trip_id} not found")

    trip_dict: Dict[str, Any] = {
        "id": trip.id,
        "title": trip.name,
        "destination": trip.destination,
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "status": trip.status,
        "emoji_theme": emoji_theme(trip.cover_emoji),
    }

    raw_bookings = Booking.query.filter_by(trip_id=trip_id).all()

    linked_ids_by_booking: Dict[int, List[int]] = {b.id: [] for b in raw_bookings}
    all_items = ItineraryItem.query.filter_by(trip_id=trip_id).all()
    for item in all_items:
        if item.linked_booking_id is not None and item.linked_booking_id in linked_ids_by_booking:
            linked_ids_by_booking[item.linked_booking_id].append(item.id)

    bookings: List[Dict[str, Any]] = []
    for b in raw_bookings:
        bookings.append({
            "id": b.id,
            "type": b.type,
            "vendor": b.vendor,
            "title": b.title,
            "start_datetime": b.start_datetime.isoformat() if b.start_datetime else None,
            "end_datetime": b.end_datetime.isoformat() if b.end_datetime else None,
            "location": b.location,
            "notes": b.notes,
            "cost": b.cost,
            "currency": b.currency,
            "linked_itinerary_ids": sorted(linked_ids_by_booking[b.id]),
        })

    items_by_day: Dict[date, List] = {}
    for item in all_items:
        items_by_day.setdefault(item.day_date, []).append(item)

    sorted_days = sorted(items_by_day.keys())
    itinerary: List[Dict[str, Any]] = []
    for day in sorted_days:
        for item in sort_within_day(items_by_day[day]):
            itinerary.append({
                "id": item.id,
                "day_date": item.day_date.isoformat() if item.day_date else None,
                "category": item.category,
                "title": item.title,
                "start_time": item.start_time.strftime("%H:%M") if item.start_time else None,
                "end_time": item.end_time.strftime("%H:%M") if item.end_time else None,
                "location": item.location,
                "notes": item.notes,
                "linked_booking_id": item.linked_booking_id,
            })

    collaborator_rows = TripCollaborator.query.filter_by(trip_id=trip_id).all()
    collaborators: List[Dict[str, str]] = [
        {"email": c.email, "role": c.role} for c in collaborator_rows
    ]

    return {
        "trip": trip_dict,
        "bookings": bookings,
        "itinerary": itinerary,
        "collaborators": collaborators,
    }

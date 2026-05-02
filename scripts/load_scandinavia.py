"""
scripts/load_scandinavia.py

One-off loader for the "Scandinavia '26" trip. Hand-translated from a
spreadsheet. Creates the Trip, all bookings, the linked itinerary chips
they auto-generate (via auto_itinerary_items_for_booking), and the
default packing list (via _seed_default_packing).

Usage:
    cd "/Users/jeff_s/Projects/Vacation Planner"
    .venv/bin/python scripts/load_scandinavia.py [--force]

--force deletes any existing trip with the same name owned by the same
user before reloading. Without --force, the script aborts if it finds
an existing trip.
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make the project root importable when this file is run directly as
# `.venv/bin/python scripts/load_scandinavia.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import _seed_default_packing, app  # noqa: E402
from models import Booking, ItineraryItem, Trip, User, db  # noqa: E402
from src.booking_helpers import auto_itinerary_items_for_booking  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

OWNER_EMAIL = "jeffsoash@gmail.com"
TRIP_NAME = "Scandinavia '26"
TRIP_START = date(2026, 8, 17)
TRIP_END = date(2026, 9, 5)
TRIP_CURRENCY = "USD"
TRIP_EMOJI = "🇳🇴"
TRIP_DESTINATION = "Norway, Finland, Estonia, Sweden, Denmark"
TRIP_NOTES = (
    "Scandinavia trip 8/17/26 – 9/5/26: Minneapolis → Oslo → Svalbard → "
    "Tromsø → Narvik → Lofoten → Bergen → Flåm → Oslo → Helsinki → "
    "Tallinn → Stockholm → Copenhagen → Minneapolis.\n\n"
    "Bulk-loaded from spreadsheet — several costs are interpretations "
    "and are flagged in the relevant booking notes; adjust via the UI "
    "as needed."
)


# Each entry maps directly to Booking constructor kwargs (minus trip_id,
# which is filled in at insert time). Keep this list in chronological
# order so reading the script tells the trip's story.
BOOKINGS: List[Dict[str, Any]] = [
    # ─── Flights (6) ──────────────────────────────────────────────────
    {
        "type": "flight",
        "title": "MSP → Oslo (overnight)",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 17, 15, 5),
        "end_datetime": datetime(2026, 8, 18, 8, 45),
        "location": "MSP",
        "cost": 2920.0,
        "notes": (
            "Round-trip total covering 8/17 outbound and 9/5 CPH→MSP "
            "return ($730 × 4 pax). Adjust split if needed."
        ),
    },
    {
        "type": "flight",
        "title": "Oslo → Longyearbyen (Svalbard)",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 18, 11, 15),
        "end_datetime": datetime(2026, 8, 18, 14, 10),
        "location": "OSL",
        "cost": 239.0,
        "notes": "Cost from spreadsheet 'Cost Transport' column — likely per-pax; verify.",
    },
    {
        "type": "flight",
        "title": "Longyearbyen → Tromsø",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 21, 12, 35),
        "end_datetime": datetime(2026, 8, 21, 14, 10),
        "location": "LYR",
        "cost": 500.0,
        "notes": None,
    },
    {
        "type": "flight",
        "title": "Northern Norway → Bergen (Widerøe)",
        "vendor": "Widerøe",
        "start_datetime": datetime(2026, 8, 25, 9, 35),
        "end_datetime": datetime(2026, 8, 25, 12, 35),
        "location": None,
        "cost": 500.0,
        "notes": (
            "Alt: 07:20 → 10:15. Departure airport TBD — Evenes (EVE) "
            "is closest to Lofoten."
        ),
    },
    {
        "type": "flight",
        "title": "Oslo → Helsinki",
        "vendor": "Finnair",
        "start_datetime": datetime(2026, 8, 29, 8, 35),
        "end_datetime": datetime(2026, 8, 29, 10, 55),
        "location": "OSL",
        "cost": 0.0,
        "notes": "Alt: 12:50 → 15:15. $0 per spreadsheet — possibly an award flight.",
    },
    {
        "type": "flight",
        "title": "Copenhagen → MSP",
        "vendor": None,
        "start_datetime": datetime(2026, 9, 5, 13, 0),
        "end_datetime": None,
        "location": "CPH",
        "cost": 0.0,
        "notes": (
            "~10–12 hr flight. Return leg of MSP↔OSL/CPH round-trip — "
            "see the 8/17 flight booking for the round-trip cost."
        ),
    },

    # ─── Hotels (9) ───────────────────────────────────────────────────
    {
        "type": "hotel",
        "title": "Funken Hotel Svalbard",
        "vendor": "Funken Hotel",
        "start_datetime": datetime(2026, 8, 18, 15, 0),
        "end_datetime": datetime(2026, 8, 21, 11, 0),
        "location": "Longyearbyen, Svalbard",
        "cost": 2900.0,
        "notes": "Funken option chosen over Radisson Blu ($2,500). 3 nights.",
    },
    {
        "type": "hotel",
        "title": "Scandic Narvik",
        "vendor": "Scandic",
        "start_datetime": datetime(2026, 8, 21, 18, 0),
        "end_datetime": datetime(2026, 8, 22, 11, 0),
        "location": "Narvik, Norway",
        "cost": 327.0,
        "notes": "2-bedroom apartment.",
    },
    {
        "type": "hotel",
        "title": "Reine Rorbuer (Lofoten)",
        "vendor": "Reine Rorbuer",
        "start_datetime": datetime(2026, 8, 22, 16, 0),
        "end_datetime": datetime(2026, 8, 25, 10, 0),
        "location": "Reine, Lofoten, Norway",
        "cost": 2648.25,
        "url": "https://reinerorbuer.no/",
        "notes": "Per-night rate $882.75 × 3 nights = $2,648.25.",
    },
    {
        "type": "hotel",
        "title": "Bergen hotel",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 25, 15, 0),
        "end_datetime": datetime(2026, 8, 26, 9, 0),
        "location": "Bergen, Norway",
        "cost": 406.0,
        "notes": None,
    },
    {
        "type": "hotel",
        "title": "Flåm hotel",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 26, 14, 30),
        "end_datetime": datetime(2026, 8, 27, 11, 0),
        "location": "Flåm, Norway",
        "cost": 1745.92,
        "notes": (
            "Cost may include the Norway-in-a-Nutshell train + ferry + "
            "bus package per spreadsheet note. Verify breakdown."
        ),
    },
    {
        "type": "hotel",
        "title": "Oslo hotel",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 27, 19, 30),
        "end_datetime": datetime(2026, 8, 29, 8, 0),
        "location": "Oslo, Norway",
        "cost": 1800.0,
        "notes": (
            "$1,800 was in the 8/28 'Cost Transport' cell, but 8/28 has "
            "no transport activity — interpreted as 2-night Oslo hotel total."
        ),
    },
    {
        "type": "hotel",
        "title": "Helsinki hotel",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 29, 14, 0),
        "end_datetime": datetime(2026, 8, 31, 7, 0),
        "location": "Helsinki, Finland",
        "cost": None,
        "notes": "Cost not listed in spreadsheet.",
    },
    {
        "type": "hotel",
        "title": "Mälardrottningen Yacht Hotel",
        "vendor": "Mälardrottningen",
        "start_datetime": datetime(2026, 9, 2, 14, 0),
        "end_datetime": datetime(2026, 9, 3, 10, 0),
        "location": "Stockholm, Sweden",
        "cost": None,
        "notes": (
            "Single bunk + sofa + double bed; couldn't book 4 at "
            "cancellable rate. May need a second room for Sarah."
        ),
    },
    {
        "type": "hotel",
        "title": "Copenhagen hotel",
        "vendor": None,
        "start_datetime": datetime(2026, 9, 3, 18, 30),
        "end_datetime": datetime(2026, 9, 5, 11, 0),
        "location": "Copenhagen, Denmark",
        "cost": 1254.80,
        "notes": (
            "Cost was in the 9/3 'Cost Lodging' cell. If this was actually "
            "the Stockholm→Copenhagen train fare, swap it onto that "
            "booking via the UI."
        ),
    },

    # ─── Car rental (1) ───────────────────────────────────────────────
    {
        "type": "car",
        "title": "Hertz car rental",
        "vendor": "Hertz",
        "start_datetime": datetime(2026, 8, 21, 14, 30),
        "end_datetime": datetime(2026, 8, 25, 9, 0),
        "location": "Tromsø Airport",
        "cost": 1400.0,
        "notes": (
            "5-seater intermediate SUV. Alt: 7-seater $2,348. "
            "Drop-off airport TBD (Evenes/Bodø)."
        ),
    },

    # ─── Trains (3) ───────────────────────────────────────────────────
    {
        "type": "transport",
        "title": "Bergen → Flåm scenic train",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 26, 8, 30),
        "end_datetime": datetime(2026, 8, 26, 14, 10),
        "location": "Bergen station",
        "cost": 1200.0,
        "notes": (
            "Possibly part of a Norway-in-a-Nutshell package — verify "
            "against the Flåm hotel cost."
        ),
    },
    {
        "type": "transport",
        "title": "Flåm → Oslo scenic train",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 27, 12, 10),
        "end_datetime": datetime(2026, 8, 27, 19, 5),
        "location": "Flåm station",
        "cost": None,
        "notes": None,
    },
    {
        "type": "transport",
        "title": "Stockholm → Copenhagen train",
        "vendor": None,
        "start_datetime": datetime(2026, 9, 3, 10, 0),
        "end_datetime": datetime(2026, 9, 3, 15, 30),
        "location": "Stockholm Central",
        "cost": None,
        "notes": "5.5 hr per spreadsheet; exact times TBD.",
    },

    # ─── Ferries (2) ──────────────────────────────────────────────────
    {
        "type": "transport",
        "title": "Tallink ferry Helsinki → Tallinn",
        "vendor": "Tallink",
        "start_datetime": datetime(2026, 8, 31, 7, 30),
        "end_datetime": datetime(2026, 8, 31, 9, 30),
        "location": "Helsinki West Terminal",
        "cost": 500.0,
        "notes": (
            "Departures roughly every 3 hr starting 07:30 (~2 hr crossing). "
            "Std $37/pax, Comfort lounge $62.50/pax, Business $125/pax."
        ),
    },
    {
        "type": "transport",
        "title": "Tallink Baltic Queen overnight ferry Tallinn → Stockholm",
        "vendor": "Tallink",
        "start_datetime": datetime(2026, 9, 1, 18, 0),
        "end_datetime": datetime(2026, 9, 2, 10, 30),
        "location": "Tallinn D-Terminal",
        "cost": 788.89,
        "notes": "Executive suite with balcony — €628 ≈ $788.89.",
    },

    # ─── Activities (3) ───────────────────────────────────────────────
    {
        "type": "activity",
        "title": "Walrus excursion",
        "vendor": None,
        "start_datetime": None,
        "end_datetime": None,
        "location": "Svalbard",
        "cost": 1000.0,
        "notes": "Add a start time in the UI to get a day-by-day chip.",
    },
    {
        "type": "activity",
        "title": "Polar bear excursion",
        "vendor": None,
        "start_datetime": None,
        "end_datetime": None,
        "location": "Svalbard",
        "cost": 1000.0,
        "notes": "Add a start time in the UI to get a day-by-day chip.",
    },
    {
        "type": "activity",
        "title": "Flåm zipline",
        "vendor": None,
        "start_datetime": datetime(2026, 8, 26, 15, 30),
        "end_datetime": None,
        "location": "Flåm",
        "cost": None,
        "notes": "Alt: bike back to town from 17:45.",
    },
]


def _next_order_within_day(trip_id: int, day_date: date) -> int:
    """Mirror app.py:_next_order_within_day so ordering matches the web UI."""
    rows = ItineraryItem.query.filter_by(trip_id=trip_id, day_date=day_date).all()
    if not rows:
        return 0
    return max(r.order_within_day or 0 for r in rows) + 1


def _delete_existing_trip(user: User) -> Optional[int]:
    """Delete any trip with TRIP_NAME owned by user. Returns deleted trip id, or None."""
    existing = (
        Trip.query.filter_by(owner_id=user.id, name=TRIP_NAME).one_or_none()
    )
    if existing is None:
        return None
    deleted_id = existing.id
    db.session.delete(existing)  # cascades to bookings, items, packing
    db.session.flush()
    logger.info("Deleted existing trip id=%d (cascaded its bookings/items/packing).", deleted_id)
    return deleted_id


def _create_trip(user: User) -> Trip:
    trip = Trip(
        owner_id=user.id,
        name=TRIP_NAME,
        destination=TRIP_DESTINATION,
        start_date=TRIP_START,
        end_date=TRIP_END,
        primary_currency=TRIP_CURRENCY,
        cover_emoji=TRIP_EMOJI,
        notes=TRIP_NOTES,
    )
    db.session.add(trip)
    db.session.flush()  # populate trip.id
    return trip


def _create_bookings(trip: Trip) -> tuple:
    """Create every booking and its auto-itinerary chips. Returns (n_bookings, n_items)."""
    n_bookings = 0
    n_items = 0
    for data in BOOKINGS:
        # Default currency to the trip's primary currency, like the web form does.
        booking = Booking(
            trip_id=trip.id,
            currency=data.get("currency", trip.primary_currency),
            **{k: v for k, v in data.items() if k != "currency"},
        )
        db.session.add(booking)
        db.session.flush()  # populate booking.id
        n_bookings += 1

        for item_data in auto_itinerary_items_for_booking(booking):
            day = item_data["day_date"]
            if day < trip.start_date or day > trip.end_date:
                logger.warning(
                    "Skipping auto-itinerary item '%s' on %s — outside trip range.",
                    item_data.get("title"),
                    day,
                )
                continue
            item_data["order_within_day"] = _next_order_within_day(trip.id, day)
            db.session.add(
                ItineraryItem(
                    trip_id=trip.id,
                    linked_booking_id=booking.id,
                    **item_data,
                )
            )
            n_items += 1
    return n_bookings, n_items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete any existing 'Scandinavia '26' trip before reloading.",
    )
    args = parser.parse_args()

    with app.app_context():
        user = User.query.filter_by(email=OWNER_EMAIL).one_or_none()
        if user is None:
            logger.error(
                "User %s not found. Sign in to the app at least once first.",
                OWNER_EMAIL,
            )
            return 1

        existing = Trip.query.filter_by(owner_id=user.id, name=TRIP_NAME).one_or_none()
        if existing is not None and not args.force:
            logger.error(
                "Trip '%s' already exists (id=%d). Re-run with --force to replace it.",
                TRIP_NAME,
                existing.id,
            )
            return 2

        if existing is not None and args.force:
            _delete_existing_trip(user)

        trip = _create_trip(user)
        _seed_default_packing(trip.id)
        n_bookings, n_items = _create_bookings(trip)
        db.session.commit()

        from models import PackingItem

        n_packing = PackingItem.query.filter_by(trip_id=trip.id).count()
        logger.info(
            "Loaded trip id=%d '%s' for %s: %d bookings, %d itinerary items, %d packing items.",
            trip.id,
            trip.name,
            user.email,
            n_bookings,
            n_items,
            n_packing,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

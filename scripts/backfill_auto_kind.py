"""
scripts/backfill_auto_kind.py

One-off helper that walks every existing linked itinerary item and
fills in its auto_kind by matching the item's title prefix to the
shape the auto-generator would produce now. Skips items whose
auto_kind is already set.

Usage:
    cd "/Users/jeff_s/Projects/Vacation Planner"
    .venv/bin/python scripts/backfill_auto_kind.py [--dry-run]

The script reports how many items it updated. It commits at the end —
if you want a dry run, pass --dry-run.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402
from models import Booking, ItineraryItem, db  # noqa: E402
from src.booking_helpers import auto_itinerary_items_for_booking  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


def backfill(dry_run: bool = False) -> int:
    updated = 0
    with app.app_context():
        candidates = ItineraryItem.query.filter(
            ItineraryItem.linked_booking_id.isnot(None),
            ItineraryItem.auto_kind.is_(None),
        ).all()
        logger.info("Found %d linked items missing auto_kind", len(candidates))

        for item in candidates:
            booking = db.session.get(Booking, item.linked_booking_id)
            if booking is None:
                logger.warning("Item id=%s links to gone booking id=%s — skipped",
                               item.id, item.linked_booking_id)
                continue
            would_be = auto_itinerary_items_for_booking(booking)
            best = None
            for w in would_be:
                if (w.get("title") == item.title
                        and w.get("day_date") == item.day_date):
                    best = w
                    break
            if best is None:
                logger.warning(
                    "Item id=%s title=%r — no auto_kind match in booking id=%s",
                    item.id, item.title, booking.id,
                )
                continue
            item.auto_kind = best["auto_kind"]
            updated += 1
            logger.info("Set auto_kind=%s on item id=%s", item.auto_kind, item.id)

        if dry_run:
            logger.info("DRY RUN — rolling back. Would have updated %d items.", updated)
            db.session.rollback()
        else:
            db.session.commit()
            logger.info("Committed. Updated %d items.", updated)
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without committing.")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)

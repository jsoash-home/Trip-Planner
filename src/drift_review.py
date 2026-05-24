"""
src/drift_review.py

Pure helpers for the drift review wizard — chronological ordering of
itinerary items so the wizard can walk them in trip-day order. No DB,
no Flask imports.
"""

import logging
from typing import Iterable, List

from src.itinerary import sort_within_day

logger = logging.getLogger(__name__)


def chronological_order(items: Iterable) -> List:
    """
    Return `items` sorted in trip-display order: day_date ascending,
    then within each day using the same rule as `sort_within_day`
    (untimed first by order_within_day, then timed by start_time).

    Items with no `day_date` are dropped with a debug log line — those
    only arise from in-memory test fixtures, real DB rows always have
    one because the column is NOT NULL.
    """
    by_day = {}
    for it in items:
        d = getattr(it, "day_date", None)
        if d is None:
            logger.debug("chronological_order skipping item without day_date: %r", it)
            continue
        by_day.setdefault(d, []).append(it)

    out: List = []
    for d in sorted(by_day):
        out.extend(sort_within_day(by_day[d]))
    return out

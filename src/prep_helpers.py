"""
src/prep_helpers.py

Pure helpers for trip prep to-dos — category metadata, due-date math,
and urgency bucketing. No DB, no Flask imports.
"""

import logging
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# (code, label, emoji) — order is the display order on the prep page.
PREP_CATEGORIES: Tuple[Tuple[str, str, str], ...] = (
    ("gear",     "Gear",     "🎒"),
    ("buy",      "Buy",      "🛒"),
    ("research", "Research", "🔍"),
    ("book",     "Book",     "📅"),
    ("admin",    "Admin",    "📋"),
    ("other",    "Other",    "📦"),
)

PREP_CATEGORY_CODES = frozenset(c for c, _, _ in PREP_CATEGORIES)
PREP_CATEGORY_LABELS: Dict[str, str] = {c: lbl for c, lbl, _ in PREP_CATEGORIES}
PREP_CATEGORY_EMOJIS: Dict[str, str] = {c: emoji for c, _, emoji in PREP_CATEGORIES}


# Urgency bucket constants — used by templates + CSS for colour-coding.
URGENCY_OVERDUE = "overdue"
URGENCY_URGENT = "urgent"      # ≤ 7 days
URGENCY_SOON = "soon"          # ≤ 30 days
URGENCY_LATER = "later"
URGENCY_NONE = "none"


def category_label(code: str) -> str:
    """Return the human label for a category code, or the code itself if unknown."""
    return PREP_CATEGORY_LABELS.get(code, code)


def category_emoji(code: str) -> str:
    """
    Return the emoji for a category code, falling back to the "other" emoji
    for unknown codes so the UI always has something to render.
    """
    return PREP_CATEGORY_EMOJIS.get(code, PREP_CATEGORY_EMOJIS["other"])


def due_date(trip_start: Optional[date], offset_days: Optional[int]) -> Optional[date]:
    """
    Compute a to-do's due date from the trip start and an offset.

    Positive offset means "N days before trip start." Negative offset
    would mean N days after trip start; we accept it rather than forbid.
    Returns None if either input is missing.
    """
    if trip_start is None or offset_days is None:
        return None
    return trip_start - timedelta(days=offset_days)


def urgency_bucket(today: date, due: Optional[date]) -> str:
    """
    Classify how soon a to-do is due relative to today.

      - None due       → URGENCY_NONE
      - due < today    → URGENCY_OVERDUE
      - due in 0..7 d  → URGENCY_URGENT  (inclusive both ends)
      - due in 8..30 d → URGENCY_SOON
      - else           → URGENCY_LATER
    """
    if due is None:
        return URGENCY_NONE
    if due < today:
        return URGENCY_OVERDUE
    delta_days = (due - today).days
    if delta_days <= 7:
        return URGENCY_URGENT
    if delta_days <= 30:
        return URGENCY_SOON
    return URGENCY_LATER

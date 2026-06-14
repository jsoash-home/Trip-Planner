"""
src/prep_helpers.py

Pure helpers for trip prep to-dos — category metadata, due-date math,
and urgency bucketing. No DB, no Flask imports.
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

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


# Rank table for the urgency tier of `sort_key`. Lower sorts earlier.
_URGENCY_RANK: Dict[str, int] = {
    URGENCY_OVERDUE: 0,
    URGENCY_URGENT: 1,
    URGENCY_SOON: 2,
    URGENCY_LATER: 3,
    URGENCY_NONE: 4,
}


def sort_key(item: Any, today: date) -> Tuple:
    """
    Sort key for a prep to-do item.

    Order:
      1. open items before done items
      2. urgency rank (overdue < urgent < soon < later < none)
      3. due date asc (None → date.max sentinel so it sorts last in its bucket)
      4. `sort_order` asc
      5. `created_at` asc

    Duck-typed: expects `item.done`, `item.trip` (with `.start_date`,
    may be None for cross-trip items), `item.due_offset_days`,
    `item.sort_order`, `item.created_at`.
    """
    trip = getattr(item, "trip", None)
    trip_start = getattr(trip, "start_date", None) if trip is not None else None
    due = due_date(trip_start, getattr(item, "due_offset_days", None))
    bucket = urgency_bucket(today, due)
    rank = _URGENCY_RANK[bucket]

    due_sortable = due if due is not None else date.max
    sort_order = getattr(item, "sort_order", 0) or 0
    created_at = getattr(item, "created_at", None)

    return (
        int(bool(getattr(item, "done", False))),
        rank,
        due_sortable,
        sort_order,
        created_at,
    )


def parse_prep_form(form: Mapping[str, str]) -> Dict[str, Any]:
    """
    Pull and validate trip-prep to-do fields from a submitted HTML form.

    Returns a dict with exactly these keys:
      title, notes, category, due_offset_days, trip_id

    Defaults / coercion:
      - title         → stripped; ValueError if empty after strip
      - notes         → stripped, or None if missing/blank
      - category      → "other" when missing or not a known code
      - due_offset_days → int, or None on blank/invalid
      - trip_id       → int, or None on blank or literal "none" or invalid
    """
    title = (form.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")

    notes = (form.get("notes") or "").strip() or None

    category = (form.get("category") or "").strip().lower()
    if category not in PREP_CATEGORY_CODES:
        category = "other"

    offset_str = (form.get("due_offset_days") or "").strip()
    due_offset_days: Optional[int]
    if not offset_str:
        due_offset_days = None
    else:
        try:
            due_offset_days = int(offset_str)
        except ValueError:
            due_offset_days = None

    trip_id_raw = (form.get("trip_id") or "").strip()
    trip_id: Optional[int]
    if not trip_id_raw or trip_id_raw.lower() == "none":
        trip_id = None
    else:
        try:
            trip_id = int(trip_id_raw)
        except ValueError:
            trip_id = None

    return {
        "title": title,
        "notes": notes,
        "category": category,
        "due_offset_days": due_offset_days,
        "trip_id": trip_id,
    }


def group_items_by_category(items: Iterable[Any]) -> Dict[str, List[Any]]:
    """
    Group prep items by category for display.

    Keys are the category codes in PREP_CATEGORIES display order, each
    mapped to its open (not-done) items in input order. A final "done"
    bucket (literal key) at the end collects every done item.

    Even categories with zero open items get an empty list so the caller
    can render predictable structure. Items with an unknown category fall
    into the "other" bucket so they aren't lost.
    """
    grouped: Dict[str, List[Any]] = {code: [] for code, _, _ in PREP_CATEGORIES}
    done_bucket: List[Any] = []

    for it in items:
        if getattr(it, "done", False):
            done_bucket.append(it)
            continue
        cat = getattr(it, "category", None) or "other"
        if cat not in grouped:
            cat = "other"
        grouped[cat].append(it)

    grouped["done"] = done_bucket
    return grouped


def items_for_dashboard_panel(
    items: Iterable[Any],
    today: date,
    limit: int = 5,
) -> List[Any]:
    """
    Return the top open prep to-dos for the dashboard panel.

    Filters out done items, sorts by `sort_key`, and slices to `limit`.
    """
    open_items = [it for it in items if not getattr(it, "done", False)]
    open_items.sort(key=lambda it: sort_key(it, today))
    return open_items[:limit]

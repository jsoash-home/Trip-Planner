"""
src/itinerary.py

Pure helpers for itinerary items — category metadata, form parsing,
and per-day grouping. No DB, no Flask imports.
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


# (code, label, emoji, css_class) — display order on forms.
ITINERARY_CATEGORIES: Tuple[Tuple[str, str, str, str], ...] = (
    ("sightseeing", "Sightseeing", "🏛️", "is-sightseeing"),
    ("meal",        "Meal",        "🍽️", "is-meal"),
    ("transit",     "Transit",     "🚆", "is-transit"),
    ("break",       "Break",       "☕", "is-break"),
    ("other",       "Other",       "📌", "is-other"),
)

ITINERARY_CATEGORY_CODES = frozenset(c for c, _, _, _ in ITINERARY_CATEGORIES)
ITINERARY_CATEGORY_LABELS = {c: lbl for c, lbl, _, _ in ITINERARY_CATEGORIES}
ITINERARY_CATEGORY_EMOJIS = {c: emoji for c, _, emoji, _ in ITINERARY_CATEGORIES}
ITINERARY_CATEGORY_CSS = {c: css for c, _, _, css in ITINERARY_CATEGORIES}


def category_label(code: str) -> str:
    """Display label for a category code; falls back to the code itself."""
    return ITINERARY_CATEGORY_LABELS.get(code, code)


def category_emoji(code: str) -> str:
    """Display emoji for a category code; falls back to a generic pin."""
    return ITINERARY_CATEGORY_EMOJIS.get(code, "📌")


def category_css(code: str) -> str:
    """CSS modifier class for a category chip; falls back to is-other."""
    return ITINERARY_CATEGORY_CSS.get(code, "is-other")


def _parse_time_input(s: str) -> time:
    """Parse the value emitted by <input type="time"> ("HH:MM" or "HH:MM:SS")."""
    s = s.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Could not parse time string: {s!r}")


def parse_itinerary_form(
    form: Mapping[str, str],
    trip_start: date,
    trip_end: date,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Pull and validate itinerary fields from a submitted HTML form.

    The day_date must fall within [trip_start, trip_end] inclusive.
    Times are optional; if both are present, end >= start.

    Returns (cleaned_data, errors). On success, cleaned_data is suitable
    for `ItineraryItem(trip_id=..., **cleaned_data)`.
    """
    errors: List[str] = []

    title = (form.get("title") or "").strip()
    if not title:
        errors.append("Title is required.")

    category = (form.get("category") or "other").strip().lower()
    if category not in ITINERARY_CATEGORY_CODES:
        errors.append("Category is not valid.")
        category = "other"

    day_str = (form.get("day_date") or "").strip()
    day_date: Optional[date] = None
    if not day_str:
        errors.append("Day is required.")
    else:
        try:
            day_date = date.fromisoformat(day_str)
        except ValueError:
            errors.append("Day is not a valid date.")

    if day_date is not None and (day_date < trip_start or day_date > trip_end):
        errors.append(
            f"Day must be between {trip_start.isoformat()} and {trip_end.isoformat()}."
        )

    start_time: Optional[time] = None
    end_time: Optional[time] = None
    start_str = (form.get("start_time") or "").strip()
    end_str = (form.get("end_time") or "").strip()

    if start_str:
        try:
            start_time = _parse_time_input(start_str)
        except ValueError:
            errors.append("Start time is not valid.")
    if end_str:
        try:
            end_time = _parse_time_input(end_str)
        except ValueError:
            errors.append("End time is not valid.")

    if start_time and end_time and end_time < start_time:
        errors.append("End time must be on or after start time.")

    location = (form.get("location") or "").strip() or None
    notes = (form.get("notes") or "").strip() or None

    data: Dict[str, Any] = {
        "title": title,
        "category": category,
        "day_date": day_date,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "notes": notes,
    }
    return data, errors


def itinerary_form_values(item) -> Dict[str, str]:
    """
    Convert an ItineraryItem row into form field strings for the edit page.

    Times render as "HH:MM" (the format <input type="time"> expects).
    Returns an empty dict when item is None — the new-item form uses the
    same `form.get(...)` template API in both modes.
    """
    if item is None:
        return {}
    return {
        "title": item.title or "",
        "category": item.category or "other",
        "day_date": item.day_date.isoformat() if item.day_date else "",
        "start_time": item.start_time.strftime("%H:%M") if item.start_time else "",
        "end_time": item.end_time.strftime("%H:%M") if item.end_time else "",
        "location": item.location or "",
        "notes": item.notes or "",
    }


def sort_within_day(items: Iterable) -> List:
    """
    Order items within a single day for display.

    Untimed items first (sorted by `order_within_day` then `id`), then
    timed items in chronological order (`start_time`, then
    `order_within_day`, then `id`). The id tiebreaker keeps sort stable
    when multiple items share a key.
    """
    untimed: List = []
    timed: List = []
    for it in items:
        if getattr(it, "start_time", None) is None:
            untimed.append(it)
        else:
            timed.append(it)
    untimed.sort(key=lambda x: (getattr(x, "order_within_day", 0) or 0, getattr(x, "id", 0) or 0))
    timed.sort(
        key=lambda x: (
            x.start_time,
            getattr(x, "order_within_day", 0) or 0,
            getattr(x, "id", 0) or 0,
        )
    )
    return untimed + timed


def group_items_by_day(
    items: Iterable,
    start: date,
    end: date,
) -> List[Tuple[date, List]]:
    """
    Build the per-day timeline payload.

    Returns a list of (day_date, items_for_that_day) tuples covering every
    day from start to end inclusive — even days with no items get an empty
    list (the timeline UI still renders the column). Items whose
    `day_date` falls outside the trip range are dropped with a warning.
    """
    if start > end:
        logger.warning("group_items_by_day got start > end: %s > %s", start, end)
        return []

    by_day: Dict[date, List] = {}
    for item in items:
        d = getattr(item, "day_date", None)
        if d is None:
            continue
        if d < start or d > end:
            logger.warning(
                "group_items_by_day skipping item id=%s — day %s outside trip [%s, %s]",
                getattr(item, "id", "?"), d, start, end,
            )
            continue
        by_day.setdefault(d, []).append(item)

    out: List[Tuple[date, List]] = []
    n_days = (end - start).days + 1
    for i in range(n_days):
        d = start + timedelta(days=i)
        out.append((d, sort_within_day(by_day.get(d, []))))
    return out


def format_time_range(
    start: Optional[time],
    end: Optional[time],
) -> str:
    """
    Friendly time range for an itinerary chip.

    Examples:
      both:       "9:30 AM – 11:45 AM"
      start only: "9:30 AM"
      end only:   "→ 5:00 PM"
      neither:    "Anytime"
    """
    if start is None and end is None:
        return "Anytime"

    def _fmt(t: time) -> str:
        s = t.strftime("%I:%M %p")
        if s.startswith("0"):
            s = s[1:]
        return s

    if start and end is None:
        return _fmt(start)
    if end and start is None:
        return "→ " + _fmt(end)
    return _fmt(start) + " – " + _fmt(end)

"""
trip_helpers.py

Pure functions about trip dates and state. No DB, no network — every
function takes plain Python values and returns plain Python values, so
they're trivial to unit-test.
"""

import logging
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


VALID_STATUSES = ("planning", "booked", "in_progress", "completed")

# Suggested cover emojis offered as quick-pick buttons in the trip form.
SUGGESTED_TRIP_EMOJIS = (
    "🏝️", "✈️", "🏔️", "🏛️", "🌊", "🌴",
    "🍝", "🍜", "🗽", "🚗", "🏨", "⛷️",
)


def derive_status(start: date, end: date, today: date) -> str:
    """
    Return the natural status of a trip given its dates and today's date.

    Rules:
      - today is between start and end (inclusive) → "in_progress"
      - today is after end                         → "completed"
      - today is before start                      → "planning"

    The user can override this at the model level; this helper is for the
    default / display fallback.
    """
    if start > end:
        # Defensive — UI prevents this but a corrupt DB row shouldn't crash.
        logger.warning("derive_status got start > end: %s > %s", start, end)
        return "planning"
    if today > end:
        return "completed"
    if today < start:
        return "planning"
    return "in_progress"


def days_until(start: date, today: date) -> int:
    """
    Days from today until the trip starts. Negative if the trip already started.
    """
    return (start - today).days


def days_remaining(end: date, today: date) -> int:
    """
    Days from today until the trip ends. Negative if the trip already ended.
    """
    return (end - today).days


def group_trips_by_state(trips: Iterable, today: date) -> Dict[str, List]:
    """
    Split an iterable of Trip rows into three buckets keyed by display state.

    Returns a dict with three keys, each a list:
      - "active":   today is between start and end (sorted by end_date asc)
      - "upcoming": today is before start          (sorted by start_date asc)
      - "past":     today is after end             (sorted by end_date desc — most recent first)

    Trips with corrupt dates (start > end) are dropped with a warning so a
    bad row can't crash the dashboard.
    """
    active: List = []
    upcoming: List = []
    past: List = []

    for t in trips:
        if t.start_date is None or t.end_date is None:
            logger.warning("group_trips_by_state skipping trip id=%s with null dates", getattr(t, "id", "?"))
            continue
        if t.start_date > t.end_date:
            logger.warning("group_trips_by_state skipping trip id=%s start>%s end=%s", t.id, t.start_date, t.end_date)
            continue
        state = derive_status(t.start_date, t.end_date, today)
        if state == "in_progress":
            active.append(t)
        elif state == "planning":
            upcoming.append(t)
        else:
            past.append(t)

    active.sort(key=lambda t: t.end_date)
    upcoming.sort(key=lambda t: t.start_date)
    past.sort(key=lambda t: t.end_date, reverse=True)

    return {"active": active, "upcoming": upcoming, "past": past}


def countdown_label(start: date, end: date, today: date) -> str:
    """
    Friendly countdown string for a trip card.

    Examples:
      "Today!"                       — first day of trip
      "23 days to go"                — upcoming
      "On day 3 of 7"                — mid-trip
      "Last day"                     — final day of trip
      "Ended 2 days ago"             — recent past
      "Ended Mar 14, 2026"           — long past (over a month ago)
    """
    if today < start:
        d = days_until(start, today)
        if d == 1:
            return "Tomorrow!"
        return f"{d} days to go"

    if today > end:
        d = (today - end).days
        if d <= 30:
            if d == 1:
                return "Ended yesterday"
            return f"Ended {d} days ago"
        return f"Ended {end.strftime('%b %d, %Y')}"

    # today is between start and end (inclusive)
    if today == end:
        return "Last day"
    if today == start:
        return "Today!"
    total = (end - start).days + 1
    current = (today - start).days + 1
    return f"On day {current} of {total}"


def is_valid_status(status: Optional[str]) -> bool:
    """Whether a string is one of the allowed status values."""
    return status in VALID_STATUSES


def status_label(status: str) -> str:
    """Human-readable label for a status string."""
    return {
        "planning": "Planning",
        "booked": "Booked",
        "in_progress": "On the trip",
        "completed": "Completed",
    }.get(status, status)


def parse_trip_form(form: Mapping[str, str]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Pull and validate trip fields from a submitted HTML form.

    The first return value is a dict of cleaned values keyed by model
    field name (suitable for `Trip(**data)` once the date fields are
    not None). The second is a list of human-readable error strings; an
    empty list means the form is valid.

    Whitespace is stripped on every text field; empty strings on optional
    fields become None. Currency codes are upper-cased.
    """
    errors: List[str] = []

    name = (form.get("name") or "").strip()
    if not name:
        errors.append("Trip name is required.")

    destination = (form.get("destination") or "").strip() or None
    cover_emoji = (form.get("cover_emoji") or "").strip() or None
    primary_currency = (form.get("primary_currency") or "USD").strip().upper() or "USD"
    notes = (form.get("notes") or "").strip() or None

    start_str = (form.get("start_date") or "").strip()
    end_str = (form.get("end_date") or "").strip()

    start_date: Optional[date] = None
    end_date: Optional[date] = None

    if not start_str:
        errors.append("Start date is required.")
    else:
        try:
            start_date = date.fromisoformat(start_str)
        except ValueError:
            errors.append("Start date is not a valid date.")

    if not end_str:
        errors.append("End date is required.")
    else:
        try:
            end_date = date.fromisoformat(end_str)
        except ValueError:
            errors.append("End date is not a valid date.")

    if start_date and end_date and start_date > end_date:
        errors.append("Start date must be on or before end date.")

    data: Dict[str, Any] = {
        "name": name,
        "destination": destination,
        "cover_emoji": cover_emoji,
        "primary_currency": primary_currency,
        "notes": notes,
        "start_date": start_date,
        "end_date": end_date,
    }
    return data, errors


def trip_form_values(trip) -> Dict[str, str]:
    """
    Convert a Trip model row into form field values for the edit page.

    Dates are rendered as YYYY-MM-DD strings (the format <input type="date">
    expects). Returns an empty dict when trip is None — used by the create
    page so the template can read the same `form.get(...)` API in both modes.
    """
    if trip is None:
        return {}
    return {
        "name": trip.name or "",
        "destination": trip.destination or "",
        "cover_emoji": trip.cover_emoji or "",
        "start_date": trip.start_date.isoformat() if trip.start_date else "",
        "end_date": trip.end_date.isoformat() if trip.end_date else "",
        "primary_currency": trip.primary_currency or "USD",
        "notes": trip.notes or "",
    }


def progress_fraction(start: date, today: date, window_days: int = 90) -> float:
    """
    How close today is to `start`, expressed as a 0.0–1.0 fraction.

    A `window_days` window before the start date is the "runway"; `today`
    at the start of that window returns 0.0 and `today == start` (or
    later) returns 1.0. Clamps both ways so callers never see a value
    outside [0.0, 1.0].

    Used by the dashboard progress ring.
    """
    if today >= start:
        return 1.0
    days_out = (start - today).days
    if days_out >= window_days:
        return 0.0
    return 1.0 - (days_out / window_days)


# Emoji → theme phrase fragment used by themed_countdown_label.
# Returning None means "use plain copy" — applies to unknown emojis and
# the default 🧳 suitcase.
_EMOJI_THEME_MAP: Dict[str, str] = {
    "🏝️": "the beach",
    "🌴": "the beach",
    "🌊": "the beach",
    "✈️": "takeoff",
    "🏔️": "the mountains",
    "⛷️": "the mountains",
    "🍝": "the next great meal",
    "🍜": "the next great meal",
    "🏛️": "history",
    "🚗": "the open road",
    "🏨": "check-in",
    "🗽": "the city",
}


def emoji_theme(emoji: Optional[str]) -> Optional[str]:
    """
    Map a trip's cover emoji to a theme phrase fragment.

    Returns None for unknown emojis, the default 🧳, None, and empty
    strings — the caller should fall back to plain copy in those cases.
    """
    if not emoji:
        return None
    return _EMOJI_THEME_MAP.get(emoji)

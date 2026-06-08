"""
trip_helpers.py

Pure functions about trip dates and state. No DB, no network — every
function takes plain Python values and returns plain Python values, so
they're trivial to unit-test.
"""

import logging
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from src.destination_clock import is_valid_iana

logger = logging.getLogger(__name__)


VALID_STATUSES = ("planning", "booked", "in_progress", "completed")

# Cover photo URL: free-form https URL up to this many characters. Matches
# Trip.cover_image_url column length.
COVER_IMAGE_URL_MAX_LEN = 800

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


def sort_nav_trips(trips: Iterable, today: date, limit: int = 5) -> List:
    """
    Order trips for the navbar trip switcher and cap the result.

    Ordering:
      1. in_progress trips first (sorted by end_date ascending — ones
         ending soonest float to the top so they don't feel buried).
      2. upcoming trips next (sorted by start_date ascending — the
         next trip comes first).
      3. completed trips last (sorted by end_date descending — most
         recent past first).

    Trips with null or inverted dates are dropped with a warning, same
    as group_trips_by_state, so a bad row can't crash the navbar.
    """
    active: List = []
    upcoming: List = []
    past: List = []

    for t in trips:
        if t.start_date is None or t.end_date is None:
            logger.warning("sort_nav_trips skipping trip id=%s with null dates", getattr(t, "id", "?"))
            continue
        if t.start_date > t.end_date:
            logger.warning("sort_nav_trips skipping trip id=%s start>%s end=%s", t.id, t.start_date, t.end_date)
            continue
        state = derive_status(t.start_date, t.end_date, today)
        if state == "in_progress":
            active.append(t)
        elif state == "completed":
            past.append(t)
        else:
            upcoming.append(t)

    active.sort(key=lambda t: t.end_date)
    upcoming.sort(key=lambda t: t.start_date)
    past.sort(key=lambda t: t.end_date, reverse=True)

    return (active + upcoming + past)[:limit]


def pick_active_trip(trips: Iterable, today: date) -> Optional[Any]:
    """
    Pick the single "active trip" to surface in the global ribbon.

    Filters to trips where ``derive_status == "in_progress"`` and returns
    the one ending soonest (tiebreaker: lowest id, for determinism).
    Returns ``None`` if no trip is currently in progress.

    Multiple simultaneous in-progress trips are rare but possible
    (e.g. an overlapping return-leg) — when it happens, the one closer
    to its end is the more time-sensitive one to surface, and we log a
    debug-level note so we can see it happened.
    """
    active: List = []
    for t in trips:
        if t.start_date is None or t.end_date is None:
            continue
        if t.start_date > t.end_date:
            continue
        if derive_status(t.start_date, t.end_date, today) == "in_progress":
            active.append(t)

    if not active:
        return None
    if len(active) > 1:
        logger.info(
            "pick_active_trip: %d in-progress trips on %s, surfacing earliest end_date",
            len(active),
            today,
        )
    active.sort(key=lambda t: (t.end_date, t.id))
    return active[0]


def day_of_trip(start: date, end: date, today: date) -> Tuple[int, int]:
    """
    Return (current_day, total_days) for a trip in progress.

    Day 1 is the start date; the final day equals total_days. Callers
    should guard with `derive_status(...) == "in_progress"` — for dates
    outside [start, end] the numbers are not meaningful.

    Used by the dashboard trip card to render "Day 3 of 7" on the
    in-progress pill.
    """
    total = (end - start).days + 1
    current = (today - start).days + 1
    return current, total


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


def parse_trip_form(form: Mapping[str, str]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Pull and validate trip fields from a submitted HTML form.

    The first return value is a dict of cleaned values keyed by model
    field name (suitable for `Trip(**data)` once the date fields are
    not None). The second is a dict of per-field error messages keyed
    by the form field name (e.g. `"start_date"`); an empty dict means
    the form is valid. Cross-field errors are attached to the
    "logically responsible" field (e.g. start > end → `end_date`).

    Whitespace is stripped on every text field; empty strings on optional
    fields become None. Currency codes are upper-cased.
    """
    field_errors: Dict[str, str] = {}

    name = (form.get("name") or "").strip()
    if not name:
        field_errors["name"] = "Trip name is required."

    destination = (form.get("destination") or "").strip() or None
    cover_emoji = (form.get("cover_emoji") or "").strip() or None
    primary_currency = (form.get("primary_currency") or "USD").strip().upper() or "USD"
    notes = (form.get("notes") or "").strip() or None

    cover_image_url_raw = (form.get("cover_image_url") or "").strip()
    cover_image_url: Optional[str] = None
    if cover_image_url_raw:
        if len(cover_image_url_raw) > COVER_IMAGE_URL_MAX_LEN:
            field_errors["cover_image_url"] = (
                f"Cover photo URL is too long (max {COVER_IMAGE_URL_MAX_LEN} characters)."
            )
        elif not cover_image_url_raw.startswith("https://"):
            field_errors["cover_image_url"] = (
                "Cover photo URL must start with https://"
            )
        else:
            cover_image_url = cover_image_url_raw

    start_str = (form.get("start_date") or "").strip()
    end_str = (form.get("end_date") or "").strip()

    start_date: Optional[date] = None
    end_date: Optional[date] = None

    if not start_str:
        field_errors["start_date"] = "Start date is required."
    else:
        try:
            start_date = date.fromisoformat(start_str)
        except ValueError:
            field_errors["start_date"] = "Start date is not a valid date."

    if not end_str:
        field_errors["end_date"] = "End date is required."
    else:
        try:
            end_date = date.fromisoformat(end_str)
        except ValueError:
            field_errors["end_date"] = "End date is not a valid date."

    if start_date and end_date and start_date > end_date:
        field_errors["end_date"] = "End date must be on or after the start date."

    raw_tz = (form.get("timezone_iana") or "").strip()
    if not raw_tz:
        timezone_iana: Optional[str] = None
    elif is_valid_iana(raw_tz):
        timezone_iana = raw_tz
    else:
        field_errors["timezone_iana"] = "Not a recognized time zone."
        timezone_iana = None

    data: Dict[str, Any] = {
        "name": name,
        "destination": destination,
        "cover_emoji": cover_emoji,
        "cover_image_url": cover_image_url,
        "primary_currency": primary_currency,
        "notes": notes,
        "start_date": start_date,
        "end_date": end_date,
        "timezone_iana": timezone_iana,
    }
    return data, field_errors


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
        "cover_image_url": getattr(trip, "cover_image_url", None) or "",
        "start_date": trip.start_date.isoformat() if trip.start_date else "",
        "end_date": trip.end_date.isoformat() if trip.end_date else "",
        "primary_currency": trip.primary_currency or "USD",
        "notes": trip.notes or "",
        "timezone_iana": getattr(trip, "timezone_iana", None) or "",
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


def themed_countdown_label(
    start: date,
    end: date,
    today: date,
    emoji: Optional[str] = None,
    unit: str = "days",
) -> str:
    """
    Like countdown_label but with optional themed phrasing and a unit choice.

    Only the "N days to go" upcoming state (N ≥ 2) gets themed. All other
    states (Tomorrow!, Today!, On day X of Y, Last day, Ended …) pass
    through countdown_label unchanged — themed phrasing only makes sense
    when there's a number to attach a unit to.

    `unit` may be "days" or "sleeps". Anything else is treated as "days".
    `emoji` is looked up via emoji_theme(); None / unknown emoji / 🧳
    fall back to the plain "N days/sleeps to go" phrasing.
    """
    if today >= start:
        return countdown_label(start, end, today)

    days_out = days_until(start, today)
    if days_out <= 1:
        # "Tomorrow!" — leave alone.
        return countdown_label(start, end, today)

    unit_word = "sleeps" if unit == "sleeps" else "days"
    theme = emoji_theme(emoji)
    if theme:
        return f"{days_out} {unit_word} until {theme}"
    return f"{days_out} {unit_word} to go"


def format_changes_since_label(
    new_bookings: int, new_items: int
) -> Optional[str]:
    """
    Banner copy for "what changed since last visit" on the trip overview.

    Returns None when both counts are zero (or negative) so the caller can
    omit the banner entirely. Otherwise returns a sentence like:

      "2 bookings and 1 itinerary item were added since your last visit."

    Singular / plural is handled for each noun independently.
    """
    b = max(0, new_bookings)
    i = max(0, new_items)
    if b == 0 and i == 0:
        return None

    parts = []
    if b > 0:
        parts.append(f"{b} booking{'' if b == 1 else 's'}")
    if i > 0:
        parts.append(f"{i} itinerary item{'' if i == 1 else 's'}")

    subject = " and ".join(parts)
    # "was" when the whole subject is a single thing (b+i == 1), else "were".
    verb = "was" if (b + i) == 1 else "were"
    return f"{subject} {verb} added since your last visit."

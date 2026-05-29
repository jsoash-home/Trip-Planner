"""
src/booking_helpers.py

Pure helpers for bookings — booking-type metadata, form parsing, grouping
for display, totals for rollups, and a friendly date/time range
formatter. No DB, no Flask imports.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from src.map_helpers import should_clear_geocode

logger = logging.getLogger(__name__)


# (code, label, emoji) — order here is the display order on the bookings list.
BOOKING_TYPES: Tuple[Tuple[str, str, str], ...] = (
    ("flight",     "Flights",     "✈️"),
    ("hotel",      "Hotels",      "🏨"),
    ("car",        "Car rentals", "🚗"),
    ("transport",  "Transport",   "🚆"),
    ("activity",   "Activities",  "🎟️"),
    ("restaurant", "Restaurants", "🍽️"),
    ("other",      "Other",       "📌"),
)

BOOKING_TYPE_CODES = frozenset(t[0] for t in BOOKING_TYPES)
BOOKING_TYPE_LABELS = {code: label for code, label, _ in BOOKING_TYPES}
BOOKING_TYPE_EMOJIS = {code: emoji for code, _, emoji in BOOKING_TYPES}


def booking_type_label(code: str) -> str:
    """Human label for a booking type code. Falls back to the code itself."""
    return BOOKING_TYPE_LABELS.get(code, code)


def booking_type_emoji(code: str) -> str:
    """Display emoji for a booking type. Falls back to a generic pin."""
    return BOOKING_TYPE_EMOJIS.get(code, "📌")


def _parse_datetime_local(s: str) -> datetime:
    """
    Parse the value emitted by <input type="datetime-local">.

    The browser produces "YYYY-MM-DDTHH:MM" (and sometimes adds seconds).
    We use strptime instead of fromisoformat because Python 3.9's
    fromisoformat is stricter about formats than 3.11's.
    """
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Could not parse datetime-local string: {s!r}")


def parse_booking_form(
    form: Mapping[str, str],
    default_currency: str = "USD",
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Pull and validate booking fields from a submitted HTML form.

    Returns (cleaned_data, field_errors). On success, cleaned_data is
    suitable for `Booking(trip_id=..., **cleaned_data)`. field_errors
    is keyed by form field name (e.g. `"title"`, `"end_datetime"`);
    an empty dict means the form is valid. Cross-field errors attach
    to the "logically responsible" field (end < start → `end_datetime`).
    """
    field_errors: Dict[str, str] = {}

    type_ = (form.get("type") or "").strip().lower()
    if type_ not in BOOKING_TYPE_CODES:
        field_errors["type"] = "Booking type is not valid."
        type_ = "other"

    title = (form.get("title") or "").strip()
    if not title:
        field_errors["title"] = "Title is required."

    vendor = (form.get("vendor") or "").strip() or None
    confirmation_number = (form.get("confirmation_number") or "").strip() or None
    location = (form.get("location") or "").strip() or None
    url = (form.get("url") or "").strip() or None
    notes = (form.get("notes") or "").strip() or None

    currency = (form.get("currency") or default_currency).strip().upper() or default_currency

    cost: Optional[float] = None
    cost_str = (form.get("cost") or "").strip()
    if cost_str:
        try:
            cost = float(cost_str)
        except ValueError:
            field_errors["cost"] = "Cost must be a number (or blank)."
            cost = None
        else:
            if cost < 0:
                field_errors["cost"] = "Cost can't be negative."
                cost = None

    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None
    start_str = (form.get("start_datetime") or "").strip()
    end_str = (form.get("end_datetime") or "").strip()

    if start_str:
        try:
            start_dt = _parse_datetime_local(start_str)
        except ValueError:
            field_errors["start_datetime"] = "Start date/time is not valid."
    if end_str:
        try:
            end_dt = _parse_datetime_local(end_str)
        except ValueError:
            field_errors["end_datetime"] = "End date/time is not valid."

    if start_dt and end_dt and end_dt < start_dt:
        field_errors["end_datetime"] = "End date/time must be on or after start."

    data: Dict[str, Any] = {
        "type": type_,
        "title": title,
        "vendor": vendor,
        "confirmation_number": confirmation_number,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "location": location,
        "cost": cost,
        "currency": currency,
        "url": url,
        "notes": notes,
    }
    return data, field_errors


def booking_form_values(booking) -> Dict[str, str]:
    """
    Convert a Booking row into form field strings for the edit page.

    Datetimes are rendered as "YYYY-MM-DDTHH:MM" (the format
    <input type="datetime-local"> expects). Returns an empty dict when
    booking is None, so the create form can use the same `form.get(...)`
    template API.
    """
    if booking is None:
        return {}
    return {
        "type": booking.type or "other",
        "title": booking.title or "",
        "vendor": booking.vendor or "",
        "confirmation_number": booking.confirmation_number or "",
        "start_datetime": booking.start_datetime.strftime("%Y-%m-%dT%H:%M") if booking.start_datetime else "",
        "end_datetime": booking.end_datetime.strftime("%Y-%m-%dT%H:%M") if booking.end_datetime else "",
        "location": booking.location or "",
        "cost": "" if booking.cost is None else f"{booking.cost:g}",
        "currency": booking.currency or "USD",
        "url": booking.url or "",
        "notes": booking.notes or "",
    }


def group_bookings_by_type(bookings: Iterable) -> List[Tuple[str, str, str, List]]:
    """
    Split bookings into display groups in canonical type order.

    Returns a list of tuples: (type_code, label, emoji, items_in_group).
    Empty types are omitted. Within each group, bookings are sorted by
    start_datetime ascending (None goes last).
    """
    by_type: Dict[str, List] = {}
    for b in bookings:
        by_type.setdefault(b.type or "other", []).append(b)

    out: List[Tuple[str, str, str, List]] = []
    for code, label, emoji in BOOKING_TYPES:
        items = by_type.get(code)
        if not items:
            continue
        items.sort(key=lambda b: (b.start_datetime is None, b.start_datetime))
        out.append((code, label, emoji, items))
    return out


def total_cost_by_currency(bookings: Iterable) -> Dict[str, float]:
    """
    Sum booking costs grouped by currency code.

    Bookings with cost=None are skipped. Returned dict is keyed by
    upper-case ISO code; an empty dict means no costed bookings.
    """
    totals: Dict[str, float] = {}
    for b in bookings:
        if b.cost is None:
            continue
        cur = (b.currency or "USD").upper()
        totals[cur] = totals.get(cur, 0.0) + float(b.cost)
    return totals


def _strip_leading_zero_hour(time_str: str) -> str:
    """`09:30 AM` → `9:30 AM`. Helper for format_datetime_range."""
    if time_str.startswith("0"):
        return time_str[1:]
    return time_str


def _auto_title(prefix: str, label: str, sep: str = " ") -> str:
    """Compose an auto-generated itinerary title; drops the separator if no label."""
    if not label:
        return prefix
    return f"{prefix}{sep}{label}"


def auto_itinerary_items_for_booking(booking) -> List[Dict[str, Any]]:
    """
    Given a booking-shaped object (or row), return the list of itinerary
    item field dicts that should be auto-created and linked back to it.

    Each returned dict is shaped for `ItineraryItem(trip_id=...,
    linked_booking_id=..., **out)`. Required fields a caller still needs
    to fill: `trip_id`, `linked_booking_id`, and `order_within_day`.

    Mapping:
      flight     → "Depart <vendor>" on dep day, "Arrive <vendor>" on arr day  (transit)
      hotel      → "Check in: <vendor>" / "Check out: <vendor>"                (other)
      car        → "Pick up car: <vendor>" / "Return car: <vendor>"            (transit)
      restaurant → booking.title at the booked time                            (meal)
      activity   → booking.title at the booked time                            (sightseeing)
      transport  → none
      other      → none

    Items with a missing required datetime are skipped (a flight with no
    departure datetime emits no "Depart" item, etc.). The caller is
    responsible for filtering items whose `day_date` falls outside the
    trip's date range — this helper stays pure and date-range-agnostic.
    """
    type_ = (getattr(booking, "type", None) or "").lower()
    vendor = getattr(booking, "vendor", None) or ""
    title = getattr(booking, "title", None) or ""
    start_dt: Optional[datetime] = getattr(booking, "start_datetime", None)
    end_dt: Optional[datetime] = getattr(booking, "end_datetime", None)
    location = getattr(booking, "location", None) or None

    label = vendor or title  # vendor wins; fall back to the booking title
    out: List[Dict[str, Any]] = []

    if type_ == "flight":
        if start_dt is not None:
            out.append({
                "title": _auto_title("Depart", label),
                "category": "transit",
                "day_date": start_dt.date(),
                "start_time": start_dt.time(),
                "end_time": None,
                "location": location,
                "notes": None,
                "auto_kind": "depart",
            })
        if end_dt is not None:
            out.append({
                "title": _auto_title("Arrive", label),
                "category": "transit",
                "day_date": end_dt.date(),
                "start_time": end_dt.time(),
                "end_time": None,
                "location": None,
                "notes": None,
                "auto_kind": "arrive",
            })

    elif type_ == "hotel":
        if start_dt is not None:
            out.append({
                "title": _auto_title("Check in:", label, sep=" "),
                "category": "other",
                "day_date": start_dt.date(),
                "start_time": start_dt.time(),
                "end_time": None,
                "location": location,
                "notes": None,
                "auto_kind": "check_in",
            })
        if end_dt is not None:
            out.append({
                "title": _auto_title("Check out:", label, sep=" "),
                "category": "other",
                "day_date": end_dt.date(),
                "start_time": end_dt.time(),
                "end_time": None,
                "location": None,
                "notes": None,
                "auto_kind": "check_out",
            })

    elif type_ == "car":
        if start_dt is not None:
            out.append({
                "title": _auto_title("Pick up car:", label, sep=" "),
                "category": "transit",
                "day_date": start_dt.date(),
                "start_time": start_dt.time(),
                "end_time": None,
                "location": location,
                "notes": None,
                "auto_kind": "pickup",
            })
        if end_dt is not None:
            out.append({
                "title": _auto_title("Return car:", label, sep=" "),
                "category": "transit",
                "day_date": end_dt.date(),
                "start_time": end_dt.time(),
                "end_time": None,
                "location": None,
                "notes": None,
                "auto_kind": "return",
            })

    elif type_ == "restaurant":
        if start_dt is not None:
            # Use end_time only when it's on the same day (avoid "ends 12 hours later"
            # weirdness if the user mistakenly sets a far-future end).
            same_day_end_time = (
                end_dt.time() if end_dt and end_dt.date() == start_dt.date() else None
            )
            out.append({
                "title": title or label or "Reservation",
                "category": "meal",
                "day_date": start_dt.date(),
                "start_time": start_dt.time(),
                "end_time": same_day_end_time,
                "location": location,
                "notes": None,
                "auto_kind": "single",
            })

    elif type_ == "activity":
        if start_dt is not None:
            same_day_end_time = (
                end_dt.time() if end_dt and end_dt.date() == start_dt.date() else None
            )
            out.append({
                "title": title or label or "Activity",
                "category": "sightseeing",
                "day_date": start_dt.date(),
                "start_time": start_dt.time(),
                "end_time": same_day_end_time,
                "location": location,
                "notes": None,
                "auto_kind": "single",
            })

    # transport / other: no auto-link. (Falls through to the empty list.)

    return out


def format_datetime_range(
    start: Optional[datetime],
    end: Optional[datetime],
) -> str:
    """
    Friendly display of a datetime range. Examples:

      both, same day:  "Jun 1, 2026 · 9:30 AM – 11:45 AM"
      both, two days:  "Jun 1 · 9:30 AM – Jun 10, 2026 · 2:15 PM"
      start only:      "Jun 1, 2026 · 9:30 AM"
      end only:        "→ Jun 10, 2026 · 2:15 PM"
      neither:         ""
    """
    if start is None and end is None:
        return ""

    if start and end is None:
        return start.strftime("%b %d, %Y · ") + _strip_leading_zero_hour(start.strftime("%I:%M %p"))

    if end and start is None:
        return "→ " + end.strftime("%b %d, %Y · ") + _strip_leading_zero_hour(end.strftime("%I:%M %p"))

    # Both present
    start_time = _strip_leading_zero_hour(start.strftime("%I:%M %p"))
    end_time = _strip_leading_zero_hour(end.strftime("%I:%M %p"))
    if start.date() == end.date():
        return start.strftime("%b %d, %Y · ") + start_time + " – " + end_time
    return (
        start.strftime("%b %d · ") + start_time + " – "
        + end.strftime("%b %d, %Y · ") + end_time
    )


# ────────────────────────────────────────────────────────────────────
# Drift detection — compares a stored ItineraryItem to what its linked
# booking would auto-generate now. Pure: no DB, no Flask.
# ────────────────────────────────────────────────────────────────────

# Fields we compare between a stored item and the auto-generated would-be.
DRIFT_FIELDS: Tuple[str, ...] = (
    "title", "category", "day_date", "start_time", "end_time", "location",
)


def parse_touched(s: Optional[str]) -> Set[str]:
    """Parse a comma-separated touched-fields string into a set.

    Unknown field names (not in DRIFT_FIELDS) are silently dropped so a
    later shrink of DRIFT_FIELDS doesn't break existing DB rows.
    """
    if not s:
        return set()
    parts = (p.strip() for p in s.split(","))
    return {p for p in parts if p in DRIFT_FIELDS}


def serialize_touched(fields: Iterable[str]) -> str:
    """Serialize a set of field names to sorted CSV. Unknown names dropped.

    Sorted output is stable for tests and human-readable in `sqlite3`.
    """
    valid = sorted(f for f in fields if f in DRIFT_FIELDS)
    return ",".join(valid)


@dataclass
class FieldDrift:
    """One field that disagrees between the stored item and the booking."""
    field_name: str
    current: Any   # value currently on the stored ItineraryItem
    would_be: Any  # value the auto-generator would produce now


@dataclass
class DriftReport:
    """Aggregate drift result for a single linked itinerary item."""
    fields: List[FieldDrift] = field(default_factory=list)
    is_orphaned: bool = False  # True when the booking no longer generates this slot

    @property
    def has_drift(self) -> bool:
        return self.is_orphaned or bool(self.fields)


def detect_drift(item, booking) -> Optional[DriftReport]:
    """
    Compare a stored ItineraryItem to the auto-generated would-be item
    from its linked booking. Returns:

      - None when the item is in sync, has no linked booking, is a legacy
        item without auto_kind, or every drifted field is in auto_fields_touched.
      - DriftReport(is_orphaned=True) when the booking no longer
        generates an item of this auto_kind.
      - DriftReport(fields=[...]) listing every untouched field that disagrees.

    Pure: takes any object exposing the required attributes; no DB call.
    """
    if getattr(item, "linked_booking_id", None) is None:
        return None

    kind = getattr(item, "auto_kind", None)
    if kind is None:
        return None  # legacy linked item — drift not tracked

    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == kind]
    if not matches:
        return DriftReport(fields=[], is_orphaned=True)

    touched = parse_touched(getattr(item, "auto_fields_touched", ""))
    would_be = matches[0]
    drifts: List[FieldDrift] = []
    for f in DRIFT_FIELDS:
        if f in touched:
            continue
        current = getattr(item, f, None)
        proposed = would_be.get(f)
        if current != proposed:
            drifts.append(FieldDrift(field_name=f, current=current, would_be=proposed))

    if not drifts:
        return None
    return DriftReport(fields=drifts, is_orphaned=False)


@dataclass
class NewItemSuggestion:
    """A would-be itinerary item that a booking could generate but doesn't
    have linked yet. Used by the drift review landing page to offer
    'Add' buttons for newly-available auto-slots after a booking edit."""
    booking: Any            # a Booking row — generic to keep this module Flask-free
    auto_kind: str
    item_data: Dict[str, Any]


def missing_auto_kinds_for_booking(
    booking,
    existing_kinds: Iterable[str],
    trip_start_date,
    trip_end_date,
) -> List[Dict[str, Any]]:
    """
    Return the list of would-be itinerary item dicts (from
    auto_itinerary_items_for_booking) whose auto_kind is NOT in
    `existing_kinds` AND whose day_date falls within
    [trip_start_date, trip_end_date].

    Pure: no DB, no Flask. Caller pre-fetches `existing_kinds`.
    """
    existing = set(existing_kinds)
    out: List[Dict[str, Any]] = []
    for w in auto_itinerary_items_for_booking(booking):
        kind = w.get("auto_kind")
        day = w.get("day_date")
        if kind in existing:
            continue
        if day is None or day < trip_start_date or day > trip_end_date:
            continue
        out.append(w)
    return out


# ─── clear_stale_geocode_on_booking_edit ─────────────────────────────


def clear_stale_geocode_on_booking_edit(booking, new_location: str) -> None:
    """Clear geocoded coords when the user changes location text, UNLESS
    they manually pinned the row.

    Call from the booking_edit route AFTER parsing the form but BEFORE
    overwriting `booking.location`. Mutates the row in place.
    """
    if should_clear_geocode(
        booking.location or "",
        new_location or "",
        manually_pinned=bool(booking.geocoded_manually),
    ):
        booking.geocoded_lat = None
        booking.geocoded_lng = None
        booking.geocoded_at = None
        booking.geocoded_city = None
        booking.geocoded_country_code = None

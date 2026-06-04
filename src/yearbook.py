"""
src/yearbook.py

Pure helpers for the Trip Yearbook page. No DB, no Flask imports — every
function takes plain Python values (Trip / Booking / ItineraryItem rows
are read via attribute access, so dataclass stand-ins work in tests).

Six helpers + two dataclasses:

  - compute_trip_stats       — chips at the top of the yearbook
  - compute_highlight_items  — starred items grouped by day number
  - compute_country_list     — unique country codes in visit order
  - derive_yearbook_view     — preview / final / hidden by trip state
  - sanitize_public_view     — strip private fields for /yearbook/<token>
  - generate_share_token     — opaque URL-safe token for share links
  - days_overview            — one DayOverview per day in [start, end]
"""

import logging
import secrets
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

from src.itinerary import sort_within_day
from src.trip_helpers import derive_status

logger = logging.getLogger(__name__)


@dataclass
class TripStats:
    """Aggregate numbers rendered as chips on the yearbook hero."""

    days_away: int
    country_count: int
    city_count: int
    bookings_by_type: Dict[str, int] = field(default_factory=dict)
    spend_by_category: Dict[str, Dict[str, float]] = field(default_factory=dict)
    biggest_spend_category: Optional[str] = None
    starred_count: int = 0


@dataclass
class DayOverview:
    """One entry in the All-days-at-a-glance strip."""

    number: int   # 1-based day index within the trip
    date: date
    items: List   # list[ItineraryItem]; empty when the day has none


def compute_trip_stats(trip, bookings, itinerary) -> TripStats:
    """
    Build the chip-bar stats for the yearbook hero.

    `country_count` and `city_count` aggregate over both bookings and
    itinerary items that have geocoded coordinates. Rows missing a
    country code (or a city, for city_count) are skipped.

    `bookings_by_type` is the per-type count using Booking.type.

    `spend_by_category` is keyed by booking type, with a per-currency
    sub-dict of totals. Bookings with cost=None are ignored.

    `biggest_spend_category` is the type with the largest spend in
    `trip.primary_currency`. Returns None when no costs are in the
    primary currency.
    """
    bookings_list = list(bookings) if bookings else []
    itinerary_list = list(itinerary) if itinerary else []

    days_away = (trip.end_date - trip.start_date).days + 1

    # Country + city dedup across both sources.
    country_codes: set = set()
    cities: set = set()
    for row in bookings_list + itinerary_list:
        cc = getattr(row, "geocoded_country_code", None)
        if cc:
            country_codes.add(cc)
            city = getattr(row, "geocoded_city", None)
            if city:
                cities.add((city, cc))

    # Per-type booking counts.
    bookings_by_type: Dict[str, int] = {}
    for b in bookings_list:
        t = getattr(b, "type", None) or "other"
        bookings_by_type[t] = bookings_by_type.get(t, 0) + 1

    # Per-type, per-currency spend rollup.
    spend_by_category: Dict[str, Dict[str, float]] = {}
    for b in bookings_list:
        cost = getattr(b, "cost", None)
        if cost is None:
            continue
        t = getattr(b, "type", None) or "other"
        cur = (getattr(b, "currency", None) or "USD").upper()
        cat = spend_by_category.setdefault(t, {})
        cat[cur] = cat.get(cur, 0.0) + float(cost)

    # Biggest category in primary currency.
    primary = (getattr(trip, "primary_currency", None) or "USD").upper()
    biggest_spend_category: Optional[str] = None
    biggest_total = 0.0
    for t, by_cur in spend_by_category.items():
        in_primary = by_cur.get(primary, 0.0)
        if in_primary > biggest_total:
            biggest_total = in_primary
            biggest_spend_category = t

    starred_count = sum(
        1 for it in itinerary_list if getattr(it, "starred", False)
    )

    return TripStats(
        days_away=days_away,
        country_count=len(country_codes),
        city_count=len(cities),
        bookings_by_type=bookings_by_type,
        spend_by_category=spend_by_category,
        biggest_spend_category=biggest_spend_category,
        starred_count=starred_count,
    )


def compute_highlight_items(
    itinerary_items: Iterable,
    trip_start_date: date,
) -> Dict[int, List]:
    """
    Group starred itinerary items by trip-day number (1-based).

    Days with zero starred items are absent from the result. Items
    within a day are sorted with `sort_within_day` so the page renders
    untimed-first-then-chronological consistently with the itinerary
    page. Items whose `day_date` is before the trip starts are
    skipped defensively.
    """
    by_day: Dict[int, List] = {}
    for item in itinerary_items:
        if not getattr(item, "starred", False):
            continue
        d = getattr(item, "day_date", None)
        if d is None:
            continue
        day_num = (d - trip_start_date).days + 1
        if day_num < 1:
            logger.warning(
                "compute_highlight_items skipping item id=%s — day %s before trip start %s",
                getattr(item, "id", "?"), d, trip_start_date,
            )
            continue
        by_day.setdefault(day_num, []).append(item)

    return {d: sort_within_day(items) for d, items in by_day.items()}


def compute_country_list(bookings, itinerary) -> List[str]:
    """
    Country ISO codes in first-appearance order across bookings and
    itinerary items, de-duplicated. Rows with no `geocoded_country_code`
    are skipped. The order matches the first time each code appears in
    the combined sequence (bookings then itinerary).
    """
    out: List[str] = []
    seen: set = set()
    for row in list(bookings or []) + list(itinerary or []):
        cc = getattr(row, "geocoded_country_code", None)
        if not cc or cc in seen:
            continue
        seen.add(cc)
        out.append(cc)
    return out


def derive_yearbook_view(trip, today: date) -> str:
    """
    Map the trip's date-derived status to a yearbook view mode.

    Returns one of:
      - "hidden"   — trip hasn't started; yearbook is 404 / tile disabled
      - "preview"  — trip is in progress; banner + same content as final
      - "final"    — trip is completed; the keepsake view

    Uses `derive_status` so a user-overridden `trip.status` doesn't
    accidentally expose the yearbook before the trip actually starts.
    """
    s = derive_status(trip.start_date, trip.end_date, today)
    if s == "in_progress":
        return "preview"
    if s == "completed":
        return "final"
    return "hidden"


def sanitize_public_view(
    view_model: Dict[str, Any],
    *,
    show_notes: bool,
    show_spend: bool,
) -> Dict[str, Any]:
    """
    Return a copy of `view_model` safe to render in the public share view.

    Always:
      - If view_model contains a `bookings` list, replace each entry with
        a dict that omits `confirmation_number` and `cost`/`currency`.
      - If view_model contains a `collaborators` list, drop it entirely.

    Conditional:
      - `show_notes` False → records that the template should skip notes.
      - `show_spend` False → wipes stats.spend_by_category +
        biggest_spend_category so the spend chip vanishes.

    The returned dict always includes `show_notes` and `show_spend` flag
    keys so the template can branch without a separate prop.
    """
    result = dict(view_model)
    result["show_notes"] = show_notes
    result["show_spend"] = show_spend

    if "bookings" in result and result["bookings"] is not None:
        safe = []
        for b in result["bookings"]:
            safe.append({
                "type": getattr(b, "type", None),
                "title": getattr(b, "title", None),
                "vendor": getattr(b, "vendor", None),
                "start_datetime": getattr(b, "start_datetime", None),
                "end_datetime": getattr(b, "end_datetime", None),
                "location": getattr(b, "location", None),
            })
        result["bookings"] = safe

    if "collaborators" in result:
        result.pop("collaborators", None)

    if not show_spend:
        stats = result.get("stats")
        if stats is not None:
            result["stats"] = replace(
                stats,
                spend_by_category={},
                biggest_spend_category=None,
            )

    return result


def generate_share_token() -> str:
    """
    Opaque URL-safe token suitable for /yearbook/<token>.

    `secrets.token_urlsafe(24)` yields a 32-character URL-safe string —
    the exact width of the `yearbook_share_token` column.
    """
    return secrets.token_urlsafe(24)


def days_overview(trip, itinerary_items) -> List[DayOverview]:
    """
    Build one DayOverview per day in [trip.start_date, trip.end_date].

    Days with zero items still appear (empty `items` list) so the
    All-days-at-a-glance strip on the yearbook always shows the full
    trip arc. Items within each day are sorted with `sort_within_day`.
    """
    by_day: Dict[date, List] = {}
    for item in itinerary_items or []:
        d = getattr(item, "day_date", None)
        if d is None:
            continue
        by_day.setdefault(d, []).append(item)

    out: List[DayOverview] = []
    n_days = (trip.end_date - trip.start_date).days + 1
    if n_days < 1:
        logger.warning(
            "days_overview got start > end: %s > %s",
            trip.start_date, trip.end_date,
        )
        return out
    for i in range(n_days):
        d = trip.start_date + timedelta(days=i)
        items = sort_within_day(by_day.get(d, []))
        out.append(DayOverview(number=i + 1, date=d, items=items))
    return out

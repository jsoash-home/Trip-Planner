"""
src/budget.py

Pure helpers for the budget page. No tables of its own — the rollup is
derived from existing Booking rows on the trip.

Two pieces:
  - rollup_bookings_by_category()  — per-type counts and totals (in display order)
  - format_money_totals()          — turn a per-currency totals dict into a label
"""

import logging
from typing import Dict, Iterable, List, Mapping, Optional

from src.booking_helpers import (
    BOOKING_TYPES,
    BOOKING_TYPE_EMOJIS,
    BOOKING_TYPE_LABELS,
)
from src.currency import format_money

logger = logging.getLogger(__name__)


def rollup_bookings_by_category(bookings: Iterable) -> List[Dict]:
    """
    Group bookings by type and sum costs per currency within each group.

    Returns a list of category dicts in canonical display order
    (the order of BOOKING_TYPES). Categories with zero bookings are
    omitted. Each dict has:

      code              — booking-type code (e.g. "flight")
      label             — human-readable label (e.g. "Flights")
      emoji             — display emoji
      count             — total bookings in this category
      uncosted_count    — bookings with cost=None
      totals_by_currency — {USD: 1200.0, EUR: 600.0, ...}; empty when all uncosted
    """
    by_type: Dict[str, List] = {}
    for b in bookings:
        by_type.setdefault(getattr(b, "type", None) or "other", []).append(b)

    out: List[Dict] = []
    for code, label, emoji in BOOKING_TYPES:
        items = by_type.get(code)
        if not items:
            continue
        totals: Dict[str, float] = {}
        uncosted = 0
        for b in items:
            cost = getattr(b, "cost", None)
            if cost is None:
                uncosted += 1
                continue
            cur = (getattr(b, "currency", None) or "USD").upper()
            totals[cur] = totals.get(cur, 0.0) + float(cost)
        out.append({
            "code": code,
            "label": label,
            "emoji": emoji,
            "count": len(items),
            "uncosted_count": uncosted,
            "totals_by_currency": totals,
        })
    return out


def format_money_totals(
    totals_by_currency: Mapping[str, float],
    *,
    empty: str = "—",
) -> str:
    """
    Render a per-currency totals dict as a single display string.

    Examples:
      {"USD": 1234.5, "EUR": 600}  -> "$1,234.50 + €600.00"
      {"USD": 100}                 -> "$100.00"
      {}                           -> "—"   (or whatever `empty` is set to)

    Currencies are joined with " + " in alphabetical code order so the
    output is stable across renders.
    """
    if not totals_by_currency:
        return empty
    parts: List[str] = []
    for code in sorted(totals_by_currency.keys()):
        parts.append(format_money(totals_by_currency[code], code))
    return " + ".join(parts)


def category_label(code: str) -> str:
    """Re-export of BOOKING_TYPE_LABELS lookup, kept here to avoid a
    cross-module import in the route layer."""
    return BOOKING_TYPE_LABELS.get(code, code)


def category_emoji(code: str) -> str:
    """Same — re-export of BOOKING_TYPE_EMOJIS lookup."""
    return BOOKING_TYPE_EMOJIS.get(code, "📌")

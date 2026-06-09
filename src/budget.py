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


def rollup_bookings_by_category(
    bookings: Iterable,
    *,
    primary_currency: Optional[str] = None,
) -> List[Dict]:
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

    When ``primary_currency`` is supplied, each dict also includes:

      primary_total     — sum of costs in the primary currency only (0.0 if none)
      share_fraction    — primary_total / sum of all primary_totals, in [0.0, 1.0]
                          (0.0 when the grand primary total is zero)
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

    if primary_currency is not None:
        primary = primary_currency.upper()
        for cat in out:
            cat["primary_total"] = cat["totals_by_currency"].get(primary, 0.0)
        grand_primary = sum(cat["primary_total"] for cat in out)
        for cat in out:
            if grand_primary > 0:
                share = cat["primary_total"] / grand_primary
                cat["share_fraction"] = max(0.0, min(1.0, share))
            else:
                cat["share_fraction"] = 0.0

    return out


def convert_totals(
    totals_by_currency: Mapping[str, float],
    target_currency: str,
    rates: Mapping[str, float],
) -> Dict[str, float]:
    """
    Collapse per-currency totals into the target currency using rates.

    ``rates`` is keyed by source currency; value is "how many
    target_currency per one source_currency" — the shape produced by
    src.exchange_rates.cross_rates_via_usd. The target itself is
    treated as having implicit rate 1.0 even if absent.

    Source currencies whose rate is missing pass through unchanged —
    they appear in the result keyed by their original (upper-cased)
    code, alongside the (single) target_currency entry. Callers can
    detect these as "non-target keys in the result" and surface a
    "not converted" footnote.

    Examples:
      convert_totals({"USD": 100, "EUR": 50}, "USD", {"EUR": 0.909})
        -> {"USD": ~145.45}

      convert_totals({"EUR": 100, "BRL": 200}, "USD",
                     {"EUR": 0.909}) -> {"USD": ~90.91, "BRL": 200}

      convert_totals({}, "USD", {})  -> {}
    """
    target = target_currency.upper()
    effective_rates = {k.upper(): v for k, v in rates.items()}
    effective_rates.setdefault(target, 1.0)

    out: Dict[str, float] = {}
    for code, amount in totals_by_currency.items():
        code_upper = code.upper()
        rate = effective_rates.get(code_upper)
        if rate is None:
            out[code_upper] = out.get(code_upper, 0.0) + float(amount)
        else:
            converted = float(amount) * rate
            out[target] = out.get(target, 0.0) + converted
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

"""
src/exchange_rates.py — exchangerate.host client + ExchangeRateCache helpers.

Mix of pure helpers (testable without network/DB) and impure helpers
(API + cache layer). Tests in tests/test_exchange_rates.py mock
requests.get so the suite never hits the network.

Pattern mirrored on src/weather.py: external API + cache table +
freshness check. No API key required — exchangerate.host is free
and non-authenticated.

In v1, fetches always use base="USD". Cross-pair conversions (e.g.
EUR→GBP) go through USD via cross_rates_via_usd.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, Mapping, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


API_URL = "https://api.exchangerate.host/latest"
REQUEST_TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_BASE = "USD"


@dataclass
class RateBundle:
    """One coherent fetch of rates from exchangerate.host."""

    base: str                       # ISO 4217 code; always "USD" in v1
    rates: Dict[str, float]         # {"EUR": 1.10, "GBP": 1.27, ...}
    rate_date: date                 # API's "date" field, fallback to today
    fetched_at: datetime            # used for TTL freshness checks


# ──────────────────────────  pure helpers  ────────────────────────────


def is_rate_fresh(fetched_at: datetime, now: datetime) -> bool:
    """True iff fetched_at is within the 24-hour cache TTL of now."""
    return fetched_at + timedelta(seconds=CACHE_TTL_SECONDS) > now


def cache_key_for(
    base: str, target: str, d: date,
) -> Tuple[str, str, date]:
    """Build the three-part cache key. Codes are upper-cased."""
    return (base.upper(), target.upper(), d)


def cross_rates_via_usd(
    usd_rates: Mapping[str, float],
    target: str,
) -> Dict[str, float]:
    """
    Convert a USD-base rate dict into a source→target rate dict.

    `usd_rates[X]` reads as "how many X per one USD". The result
    `out[Y]` reads as "how many target per one Y", so callers can
    plug it straight into convert_totals.

    Math: cross(X→Y) = rate(USD→Y) / rate(USD→X).

    Always includes the target itself with rate 1.0 (so same-currency
    sources pass through with no special-case math) and includes USD
    with the direct rate when target != "USD".

    Returns {} when the target's USD rate is missing — that signals
    the caller to fall back to mixed display.
    """
    target = target.upper()
    if target == "USD":
        rate_target = 1.0
    elif target in usd_rates:
        rate_target = usd_rates[target]
    else:
        return {}

    out: Dict[str, float] = {target: 1.0}
    if target != "USD":
        out["USD"] = rate_target
    for src, rate_src in usd_rates.items():
        src_upper = src.upper()
        if src_upper == target or src_upper == "USD":
            continue
        if not rate_src:
            continue
        out[src_upper] = rate_target / rate_src
    return out


# ──────────────────────────  exchangerate.host  ───────────────────────


def fetch_latest_rates(base: str = DEFAULT_BASE) -> Optional[RateBundle]:
    """Single exchangerate.host API call. Returns a `RateBundle` on
    success; `None` on network failure, non-200, success=false, or
    malformed JSON. Five-second timeout. Never raises.
    """
    params = {"base": base.upper()}
    try:
        resp = requests.get(
            API_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        logger.warning("exchangerate.host network error for base=%s: %s", base, e)
        return None
    if resp.status_code != 200:
        logger.warning(
            "exchangerate.host returned %s for base=%s", resp.status_code, base,
        )
        return None
    try:
        payload = resp.json()
    except ValueError as e:
        logger.warning("exchangerate.host returned non-JSON for base=%s: %s", base, e)
        return None
    # The API includes "success": true on success; some responses omit it.
    # Treat missing field as success; explicit false as failure.
    if payload.get("success") is False:
        logger.warning("exchangerate.host returned success=false for base=%s", base)
        return None

    raw_rates = payload.get("rates") or {}
    clean_rates: Dict[str, float] = {}
    for code, val in raw_rates.items():
        if isinstance(val, (int, float)) and val > 0:
            clean_rates[code.upper()] = float(val)

    rate_date = date.today()
    raw_date = payload.get("date")
    if isinstance(raw_date, str):
        try:
            rate_date = date.fromisoformat(raw_date)
        except ValueError:
            pass

    return RateBundle(
        base=base.upper(),
        rates=clean_rates,
        rate_date=rate_date,
        fetched_at=datetime.utcnow(),
    )


# ──────────────────────────  cache wrapper  ───────────────────────────


def get_rates_for(
    base: str,
    targets: Iterable[str],
    *,
    db_session,
    now: Optional[datetime] = None,
) -> Dict[str, float]:
    """Cache-first. Returns `{target: rate}` for every target whose
    rate could be served from cache OR freshly fetched. Targets whose
    rate cannot be obtained are omitted from the dict.

    Side effect: writes / updates `ExchangeRateCache` rows on a
    successful fetch. Defensive against the table being missing on
    a fresh deploy (treat as "no cache").
    """
    from models import ExchangeRateCache  # avoid circular import at module load
    from sqlalchemy.exc import IntegrityError, OperationalError

    base = base.upper()
    targets_set = {t.upper() for t in targets}
    if not targets_set:
        return {}
    now = now or datetime.utcnow()

    fresh: Dict[str, float] = {}
    try:
        rows = ExchangeRateCache.query.filter(
            ExchangeRateCache.base_currency == base,
            ExchangeRateCache.target_currency.in_(targets_set),
        ).all()
    except OperationalError as e:
        logger.warning("ExchangeRateCache table missing (%s); skipping cache", e)
        rows = []

    for row in rows:
        if is_rate_fresh(row.fetched_at, now):
            fresh[row.target_currency] = row.rate

    if base in targets_set:
        fresh.setdefault(base, 1.0)

    if targets_set.issubset(fresh.keys()):
        return fresh

    bundle = fetch_latest_rates(base)
    if bundle is None:
        return fresh

    for target in targets_set:
        if target == base:
            fresh[target] = 1.0
            continue
        rate = bundle.rates.get(target)
        if rate is None:
            continue
        fresh[target] = rate

        existing = ExchangeRateCache.query.filter_by(
            base_currency=base,
            target_currency=target,
            rate_date=bundle.rate_date,
        ).one_or_none()
        if existing is not None:
            existing.rate = rate
            existing.fetched_at = bundle.fetched_at
        else:
            db_session.add(ExchangeRateCache(
                base_currency=base,
                target_currency=target,
                rate=rate,
                rate_date=bundle.rate_date,
                fetched_at=bundle.fetched_at,
            ))

    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        logger.info("ExchangeRateCache insert raced; rolled back")

    return fresh

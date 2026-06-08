"""
src/destination_clock.py — pure helpers for the destination-clock /
time-zone feature.

Two responsibilities:
  1. Resolve `(lat, lng)` → IANA zone via `timezonefinder` (wrapped so a
     missing install doesn't take down unrelated pages).
  2. Format/validate IANA names + offset minutes for display.

All functions are pure (no DB, no network) apart from `iana_from_coords`,
which calls into the bundled timezonefinder data. Tests in
`tests/test_destination_clock.py` mock at the module boundary so they
never depend on the actual coordinate→zone lookup.
"""

import logging
from typing import Optional, Set
from zoneinfo import available_timezones

logger = logging.getLogger(__name__)


try:
    from timezonefinder import TimezoneFinder
    _TF = TimezoneFinder()
except Exception as e:
    _TF = None
    logger.warning(
        "timezonefinder unavailable; iana_from_coords will return None: %s", e,
    )


COMMON_TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Toronto", "America/Mexico_City",
    "America/Sao_Paulo", "America/Buenos_Aires",
    "Europe/London", "Europe/Paris", "Europe/Berlin",
    "Europe/Madrid", "Europe/Rome", "Europe/Amsterdam",
    "Europe/Athens", "Europe/Istanbul",
    "Africa/Cairo", "Africa/Lagos", "Africa/Johannesburg",
    "Asia/Dubai", "Asia/Mumbai", "Asia/Bangkok",
    "Asia/Singapore", "Asia/Hong_Kong", "Asia/Shanghai",
    "Asia/Tokyo", "Asia/Seoul",
    "Australia/Sydney", "Australia/Melbourne",
    "Pacific/Auckland", "Pacific/Honolulu",
]


_AVAILABLE_TZS: Optional[Set[str]] = None


def _load_available_tzs() -> Set[str]:
    """Lazily build the set of IANA names. `available_timezones()` is
    not cheap, so we cache the result at module scope on first call."""
    global _AVAILABLE_TZS
    if _AVAILABLE_TZS is None:
        _AVAILABLE_TZS = set(available_timezones())
    return _AVAILABLE_TZS


def iana_from_coords(lat: float, lng: float) -> Optional[str]:
    """Resolve `(lat, lng)` → IANA zone name, or None.

    Returns None when:
      - `timezonefinder` isn't installed (module-level singleton is None)
      - the coords are over open ocean / unsupported (the underlying
        library returns None natively)
      - the underlying call raises (logged as a warning)
    """
    if _TF is None:
        return None
    try:
        return _TF.timezone_at(lat=lat, lng=lng)
    except Exception as e:
        logger.warning(
            "timezonefinder lookup failed for (%s, %s): %s", lat, lng, e,
        )
        return None


def is_valid_iana(name: str) -> bool:
    """True iff `name` is a non-empty string that names a known IANA zone."""
    return bool(name) and name in _load_available_tzs()


def hours_offset_label(offset_minutes: int) -> str:
    """Format a signed minute offset as `"N h ahead"` / `"N h behind"` /
    `"same time"`. Half/quarter-hour zones include a minutes segment.

    The caller is responsible for rounding to the nearest minute.
    """
    if offset_minutes == 0:
        return "same time"
    direction = "ahead" if offset_minutes > 0 else "behind"
    hours, mins = divmod(abs(offset_minutes), 60)
    if mins == 0:
        return f"{hours} h {direction}"
    return f"{hours} h {mins} min {direction}"


def format_clock_label(city_hint: Optional[str], iana: str) -> str:
    """Display label for the destination clock — prefer a hand-typed
    city name; otherwise derive a readable label from the IANA tail."""
    if city_hint:
        return f"🕒 {city_hint}"
    tail = iana.rsplit("/", 1)[-1].replace("_", " ")
    return f"🕒 {tail}"

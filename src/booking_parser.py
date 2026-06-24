"""
src/booking_parser.py

Pure helpers for parsing pasted booking text into ParsedBooking records.

Task 1 ships:
  - module-level constants (confidence cutoff, paste size cap, LLM gating)
  - ParsedBooking + ParseResult dataclasses
  - shared extractors: dates, money, confirmation number, URL
  - score_confidence() over a per-type required-fields map

Per-type extractors (flight / hotel / car / …) and the orchestrator land in
later tasks. No DB, no Flask, no network here.
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple, Union

from src.booking_helpers import BOOKING_TYPE_CODES  # noqa: F401 — exported for parsers
from src.currency import SUPPORTED_CURRENCY_CODES

logger = logging.getLogger(__name__)


# ─────────────────────────────  constants  ─────────────────────────────────

MIN_CONFIDENCE = 0.4
MAX_BOOKINGS_PER_PARSE = 5
MAX_PASTE_BYTES = 50_000
LLM_MODEL = "claude-opus-4-8"
LLM_MAX_TOKENS = 4096
LLM_GATE_ENV_FLAG = "PASTE_PARSER_LLM_ENABLED"


# ─────────────────────────────  dataclasses  ───────────────────────────────


@dataclass
class ParsedBooking:
    """One booking pulled out of a pasted string. Mirrors Booking model fields."""

    type: str
    title: str
    vendor: Optional[str] = None
    confirmation_number: Optional[str] = None
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    location: Optional[str] = None
    cost: Optional[float] = None
    currency: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    confidence: float = 0.0
    source: Literal["rules", "llm"] = "rules"


@dataclass
class ParseResult:
    """All bookings recovered from one paste, plus where they came from."""

    bookings: List[ParsedBooking]
    source: Literal["rules", "llm", "none"]
    notes: str = ""


# ─────────────────────────────  extract_dates  ─────────────────────────────


# Month name → number, for human-format date matchers below.
_MONTHS: Dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# ISO 8601 datetime: 2026-08-17T14:30 or 2026-08-17 14:30 (optional seconds).
_RE_ISO_DT = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2})?\b"
)

# ISO 8601 date only: 2026-08-17.
_RE_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# Human "Aug 17, 2026 [at] 3:45 PM" / "August 17, 2026 3:45 PM" /
# "Mon, Aug 17 2026 3:45 PM". The leading weekday is optional.
_MONTH_NAMES = r"(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)"
_RE_HUMAN_DT = re.compile(
    rf"(?:[A-Za-z]+,\s+)?({_MONTH_NAMES})\s+(\d{{1,2}}),?\s+(\d{{4}})(?:\s+(?:at\s+)?(\d{{1,2}}):(\d{{2}})\s*(AM|PM))?",
    re.IGNORECASE,
)

# US slash form: 08/17/2026 [3:45 PM] or 8/17/26.
_RE_US_SLASH_DT = re.compile(
    r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})(?:\s+(\d{1,2}):(\d{2})\s*(AM|PM))?",
    re.IGNORECASE,
)


def _to_24h(hour: int, ampm: Optional[str]) -> int:
    """Convert 12h + AM/PM to 24h. AM/PM None means hour is already 24h."""
    if ampm is None:
        return hour
    ap = ampm.upper()
    if ap == "AM":
        return 0 if hour == 12 else hour
    # PM
    return 12 if hour == 12 else hour + 12


def extract_dates(text: str) -> List[datetime]:
    """Find every recognisable date/datetime in text.

    Returns naive datetimes (no tzinfo) sorted ascending, deduplicated.
    Date-only matches become datetime(y, m, d, 0, 0).
    Supports ISO, human ("Aug 17, 2026 3:45 PM"), and US slash forms.
    """
    found: List[datetime] = []
    matched_spans: List[Tuple[int, int]] = []  # to avoid date-only re-matching a datetime

    # 1. ISO datetimes first (most specific).
    for m in _RE_ISO_DT.finditer(text):
        y, mo, d, h, mi = (int(x) for x in m.groups()[:5])
        try:
            found.append(datetime(y, mo, d, h, mi))
            matched_spans.append(m.span())
        except ValueError as e:
            logger.debug("extract_dates: bad ISO datetime %s: %s", m.group(0), e)

    # 2. ISO date-only — skip ranges already covered by an ISO datetime match.
    for m in _RE_ISO_DATE.finditer(text):
        if any(s <= m.start() < e for s, e in matched_spans):
            continue
        y, mo, d = (int(x) for x in m.groups())
        try:
            found.append(datetime(y, mo, d, 0, 0))
        except ValueError as e:
            logger.debug("extract_dates: bad ISO date %s: %s", m.group(0), e)

    # 3. Human form ("Aug 17, 2026 [at] 3:45 PM"), with or without time.
    for m in _RE_HUMAN_DT.finditer(text):
        month_str, day_str, year_str, h_str, mi_str, ampm = m.groups()
        month = _MONTHS.get(month_str.lower())
        if month is None:
            continue
        try:
            day = int(day_str)
            year = int(year_str)
            if h_str is not None:
                hour = _to_24h(int(h_str), ampm)
                minute = int(mi_str)
                found.append(datetime(year, month, day, hour, minute))
            else:
                found.append(datetime(year, month, day, 0, 0))
        except ValueError as e:
            logger.debug("extract_dates: bad human date %s: %s", m.group(0), e)

    # 4. US slash form. 2-digit years assume 20YY.
    for m in _RE_US_SLASH_DT.finditer(text):
        mo_str, d_str, y_str, h_str, mi_str, ampm = m.groups()
        try:
            month = int(mo_str)
            day = int(d_str)
            year = int(y_str)
            if year < 100:
                year += 2000
            if h_str is not None:
                hour = _to_24h(int(h_str), ampm)
                minute = int(mi_str)
                found.append(datetime(year, month, day, hour, minute))
            else:
                found.append(datetime(year, month, day, 0, 0))
        except ValueError as e:
            logger.debug("extract_dates: bad US slash date %s: %s", m.group(0), e)

    # Dedup + sort.
    return sorted(set(found))


# ─────────────────────────────  extract_money  ─────────────────────────────


# Symbol → ISO code lookup for the symbol-form matcher.
_SYMBOL_TO_CODE: Dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",  # ambiguous with CNY; JPY is the more common paste-context
    "₹": "INR",
    "₩": "KRW",
    "฿": "THB",
}


def _parse_amount(raw: str) -> Optional[float]:
    """Parse a numeric token that may use comma-as-decimal (European) form."""
    raw = raw.strip()
    # European "45,00" or "1.234,56" → "45.00" / "1234.56".
    # US "1,234.56" → "1234.56".
    has_dot = "." in raw
    has_comma = "," in raw
    if has_dot and has_comma:
        # Whichever appears last is the decimal separator.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif has_comma and not has_dot:
        # Comma alone — treat as decimal if it has exactly 2 trailing digits,
        # otherwise as a thousands separator.
        last_comma = raw.rfind(",")
        if len(raw) - last_comma - 1 == 2:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def extract_money(text: str) -> Optional[Tuple[float, str]]:
    """Find the largest currency amount in text.

    Returns (amount, ISO_code) for the biggest detected total (heuristic:
    "Total" lines tend to be the largest number). Supports $/€/£/¥/₹/₩/฿
    symbols and ISO-code prefixes (USD, EUR, …) from currency.SUPPORTED_CURRENCIES.
    Returns None if no amount is found.
    """
    candidates: List[Tuple[float, str]] = []

    # ISO-code prefix form: "USD 123.45", "EUR 45,00".
    code_alt = "|".join(re.escape(c) for c in sorted(SUPPORTED_CURRENCY_CODES))
    re_iso = re.compile(
        rf"\b({code_alt})\s+([\d.,]+)",
        re.IGNORECASE,
    )
    for m in re_iso.finditer(text):
        code = m.group(1).upper()
        amount = _parse_amount(m.group(2))
        if amount is not None:
            candidates.append((amount, code))

    # Symbol form: "$123.45", "€45,00".
    symbol_class = "".join(re.escape(s) for s in _SYMBOL_TO_CODE.keys())
    re_sym = re.compile(rf"([{symbol_class}])\s*([\d.,]+)")
    for m in re_sym.finditer(text):
        symbol = m.group(1)
        code = _SYMBOL_TO_CODE.get(symbol)
        if code is None:
            continue
        amount = _parse_amount(m.group(2))
        if amount is not None:
            candidates.append((amount, code))

    if not candidates:
        return None
    # Largest amount wins — "Total" is usually the biggest number.
    return max(candidates, key=lambda c: c[0])


# ──────────────────────  extract_confirmation_number  ──────────────────────


# Each anchor accepts either ":" or " is " between the label and the token,
# so "Confirmation #: ABC123" AND "Your confirmation number is 2116414472"
# both match. \s+is\s+ requires whitespace on both sides so we don't pick
# up "confirmation numbering is..." or similar.
_CONFIRMATION_ANCHORS = (
    r"confirmation\s*(?:number|code|#)?\s*(?::|\s+is\s+)",
    r"booking\s*(?:reference|ref|code|number)\s*(?::|\s+is\s+)",
    r"record\s*locator\s*(?::|\s+is\s+)",
    r"reservation\s*(?:number|code|#)?\s*(?::|\s+is\s+)",
)
# Capture allows hyphens in the middle (e.g. Amtrak's "AMT-7721-NER")
# but not at either end. 5-15 chars total.
_RE_CONFIRMATION_ANCHOR = re.compile(
    r"(?:" + "|".join(_CONFIRMATION_ANCHORS) + r")\s*"
    r"([A-Za-z0-9][A-Za-z0-9\-]{3,13}[A-Za-z0-9])",
    re.IGNORECASE,
)

# Fallback: standalone 6–10 alphanumeric token with at least one letter AND digit.
_RE_CONFIRMATION_FALLBACK = re.compile(r"\b([A-Za-z0-9]{6,10})\b")

# Words that indicate a nearby token belongs to a loyalty / rewards program,
# not a booking confirmation. Used in the fallback path to skip tokens whose
# preceding context names a membership program (e.g. "Enterprise Plus" /
# "AAdvantage"). Kept narrow on purpose — "member" alone false-matches
# normal words like "remember".
_LOYALTY_CONTEXT_WORDS = ("membership", "loyalty")
_LOYALTY_CONTEXT_WINDOW = 60


def _has_loyalty_context(text: str, token_start: int) -> bool:
    """True if the chars preceding token_start mention a loyalty/membership program."""
    window = text[max(0, token_start - _LOYALTY_CONTEXT_WINDOW):token_start].lower()
    return any(word in window for word in _LOYALTY_CONTEXT_WORDS)


def extract_confirmation_number(text: str) -> Optional[str]:
    """Find a booking confirmation number.

    Prefers an anchor phrase ("Confirmation #:", "Booking reference:",
    "Record locator:", "Reservation number:", or the same labels followed
    by " is "). Anchored matches are filtered to those containing at least
    one digit so phrases like "confirmation number is pending" don't pose
    as the captured token. Falls back to any 6–10 char alphanumeric token
    containing at least one letter AND one digit, skipping tokens that
    sit in a loyalty / membership context.
    """
    for m in _RE_CONFIRMATION_ANCHOR.finditer(text):
        token = m.group(1)
        if any(c.isdigit() for c in token):
            return token

    for m in _RE_CONFIRMATION_FALLBACK.finditer(text):
        token = m.group(1)
        if not (any(c.isalpha() for c in token) and any(c.isdigit() for c in token)):
            continue
        if _has_loyalty_context(text, m.start()):
            continue
        return token
    return None


# ─────────────────────────────  extract_url  ───────────────────────────────


_RE_URL = re.compile(r"https?://\S+")


def extract_url(text: str) -> Optional[str]:
    """First http(s) URL in text, terminated by whitespace."""
    m = _RE_URL.search(text)
    return m.group(0) if m else None


# ─────────────────────────────  score_confidence  ──────────────────────────


# Fields a ParsedBooking of each type *should* have populated to count as a
# confident extraction. The score is (filled / total) of these fields.
_REQUIRED_FIELDS_PER_TYPE: Dict[str, Tuple[str, ...]] = {
    "flight":     ("type", "title", "vendor", "start_datetime", "location"),
    "hotel":      ("type", "title", "vendor", "start_datetime", "end_datetime"),
    "car":        ("type", "title", "vendor", "start_datetime", "end_datetime"),
    "restaurant": ("type", "title", "vendor", "start_datetime"),
    "activity":   ("type", "title", "start_datetime"),
    "transport":  ("type", "title", "vendor", "start_datetime"),
    "other":      ("type", "title"),
}


def score_confidence(parsed: ParsedBooking) -> float:
    """Fraction of required-for-type fields that are populated (0.0 to 1.0).

    Unknown booking types score 0.0 — we don't know what to require.
    """
    required = _REQUIRED_FIELDS_PER_TYPE.get(parsed.type)
    if not required:
        return 0.0
    filled = sum(
        1 for f in required if getattr(parsed, f, None) not in (None, "")
    )
    return filled / len(required)


# ─────────────────────────────  extract_flight  ────────────────────────────


# IATA airport-code pair. Forms handled:
#   SFO → LHR     (unicode arrow)
#   SFO -> LHR    (ascii arrow)
#   SFO-LHR / SFO - LHR   (dash, optional spaces)
#   SFO to LHR
#   San Francisco (SFO) → London Heathrow (LHR)   (parens + city names between)
# \b-bounded so we don't grab parts of words like "SFOTAX".
# We allow up to ~60 chars of "any non-newline" between IATA + separator + IATA
# so emails that wrap the IATA code in parens after a city name still match.
# Lazy quantifier + leftmost-first finditer means we get the first IATA of
# each pair, not a greedy span across multiple pairs.
_IATA_SEP = r"(?:→|->|\s+to\s+|\s*-\s*)"
_RE_IATA_PAIR = re.compile(
    r"\b([A-Z]{3})\b[^\n]{0,60}?" + _IATA_SEP + r"[^\n]{0,60}?\b([A-Z]{3})\b"
)

# Flight number: 2-letter airline + 1-4 digits, optional space.
_RE_FLIGHT_NO = re.compile(r"\b([A-Z]{2})\s?(\d{1,4})\b")

# Vendor anchors that point at an explicit airline name.
_RE_VENDOR_ANCHOR = re.compile(
    r"(?:Operated\s+by|Airline|Carrier)\s*:\s*([A-Z][A-Za-z &\-]+?)(?:\n|$)",
    re.IGNORECASE,
)

# Known airlines for fallback header scan. Longest first to win in regex alt.
_KNOWN_AIRLINES: Tuple[str, ...] = (
    "American Airlines",
    "British Airways",
    "Singapore Airlines",
    "Cathay Pacific",
    "Virgin Atlantic",
    "Japan Airlines",
    "Qatar Airways",
    "Air Canada",
    "Air France",
    "Aer Lingus",
    "United Airlines",
    "Spirit Airlines",
    "United",
    "American",
    "Delta",
    "Southwest",
    "JetBlue",
    "Alaska",
    "Lufthansa",
    "KLM",
    "Emirates",
    "ANA",
    "Iberia",
)
_RE_KNOWN_AIRLINE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _KNOWN_AIRLINES) + r")\b"
)

# Departure / arrival date anchor patterns. The anchor captures everything to
# end of line so we can hand the tail to extract_dates.
_RE_DEP_ANCHOR = re.compile(
    r"\bDepart(?:ure|ing|s)?\b\s*:\s*(.+)", re.IGNORECASE
)
_RE_ARR_ANCHOR = re.compile(
    r"\bArriv(?:e|es|al|ing)\b\s*:\s*(.+)", re.IGNORECASE
)

# Window (in chars) around an IATA pair we scan for segment-local fields.
_SEGMENT_RADIUS = 400


def _vendor_from_anchor_or_header(text: str) -> Optional[str]:
    """Find an airline name via 'Airline:' anchor or known-airlines header scan."""
    m = _RE_VENDOR_ANCHOR.search(text)
    if m:
        return m.group(1).strip()

    # Scan first ~6 lines for a known airline name.
    header = "\n".join(text.splitlines()[:6])
    m = _RE_KNOWN_AIRLINE.search(header)
    if m:
        return m.group(1)
    return None


def _nearest_flight_no(segment: str, pair_offset_in_segment: int) -> Optional[str]:
    """Find the flight number closest to the IATA pair within `segment`.

    Ties broken by smallest distance, then by lowest position (first wins).
    Segment slicing already constrains the search radius.
    """
    best: Optional[Tuple[int, str]] = None  # (distance, value)
    for m in _RE_FLIGHT_NO.finditer(segment):
        mid = (m.start() + m.end()) // 2
        dist = abs(mid - pair_offset_in_segment)
        candidate = f"{m.group(1)} {m.group(2)}"
        if best is None or dist < best[0]:
            best = (dist, candidate)
    return best[1] if best else None


def _datetime_for_anchor(
    text: str,
    anchor_re: "re.Pattern[str]",
    near_offset: Optional[int] = None,
) -> Optional[datetime]:
    """Find the anchor line; return a datetime parsed from its tail.

    If `near_offset` is given, pick the anchor whose start is closest to that
    offset (used for multi-segment emails where several Depart: lines exist).
    Otherwise return the first datetime from the first matching anchor.
    """
    matches = list(anchor_re.finditer(text))
    if not matches:
        return None
    if near_offset is not None:
        matches.sort(key=lambda m: abs(m.start() - near_offset))
    for m in matches:
        dates = extract_dates(m.group(1))
        if dates:
            return dates[0]
    return None


def _build_flight_title(
    vendor: Optional[str], flight_no: Optional[str], origin: str, dest: str
) -> str:
    """`Vendor FN: ORIG → DEST` with graceful degradation if pieces are missing."""
    arrow = f"{origin} → {dest}"
    if vendor and flight_no:
        return f"{vendor} {flight_no}: {arrow}"
    if flight_no:
        return f"{flight_no}: {arrow}"
    if vendor:
        return f"{vendor}: {arrow}"
    return arrow


def _segment_has_flight_evidence(segment: str) -> bool:
    """True iff a segment around an IATA pair has a strong flight signal.

    A "strong" signal is one that's specific to real flight emails:
      - a flight number (e.g. "UA 423", "BA 286")
      - an explicit airline anchor (Operated by: / Airline: / Carrier:)
      - a Depart: anchor that yields a parseable date

    Bare known-airline words in nearby prose ("United States" in a
    car-rental policy) do NOT count — that's exactly the false-positive
    pattern that lets PEC ↔ PEC pairs in policy text masquerade as flights.
    """
    if _RE_FLIGHT_NO.search(segment):
        return True
    if _RE_VENDOR_ANCHOR.search(segment):
        return True
    for m in _RE_DEP_ANCHOR.finditer(segment):
        if extract_dates(m.group(1)):
            return True
    return False


def _extract_one_segment(
    full_text: str,
    pair_start: int,
    pair_end: int,
    origin: str,
    dest: str,
    email_vendor: Optional[str],
    email_conf: Optional[str],
    email_cost: Optional[Tuple[float, str]],
) -> Optional[ParsedBooking]:
    """Build one ParsedBooking from a single IATA-pair match.

    Looks for vendor/flight-no/dates inside a ±SEGMENT_RADIUS window around
    the pair. Falls back to email-level vendor/conf/cost when nothing local.
    Returns None when the segment lacks any flight-specific signal — that
    guards against prose pairs like "PEC ... PEC" in car-rental policy
    text being treated as real IATA airport pairs.
    """
    seg_start = max(0, pair_start - _SEGMENT_RADIUS)
    seg_end = min(len(full_text), pair_end + _SEGMENT_RADIUS)
    segment = full_text[seg_start:seg_end]

    if not _segment_has_flight_evidence(segment):
        return None

    vendor = _vendor_from_anchor_or_header(segment) or email_vendor
    # Within the segment, choose anchors/flight-no nearest the IATA pair —
    # round-trip emails contain multiple Depart:/Arrive: lines.
    near_offset = pair_start - seg_start
    flight_no = _nearest_flight_no(segment, near_offset)
    start_dt = _datetime_for_anchor(segment, _RE_DEP_ANCHOR, near_offset)
    end_dt = _datetime_for_anchor(segment, _RE_ARR_ANCHOR, near_offset)

    # Segment-local conf / cost win over email-level ones if present.
    seg_conf = extract_confirmation_number(segment)
    if seg_conf is None:
        seg_conf = email_conf
    seg_cost = extract_money(segment) or email_cost

    title = _build_flight_title(vendor, flight_no, origin, dest)

    # location is used by the auto-itinerary-link to set the "Depart {origin}"
    # item's location — that only fires when a start_datetime exists, so we
    # only populate location when there's flight evidence (dep date OR
    # flight no OR vendor). Bare IATA pairs leave it None.
    has_flight_evidence = bool(start_dt or flight_no or vendor)

    p = ParsedBooking(
        type="flight",
        title=title,
        vendor=vendor,
        confirmation_number=seg_conf,
        start_datetime=start_dt,
        end_datetime=end_dt,
        location=origin if has_flight_evidence else None,
        cost=seg_cost[0] if seg_cost else None,
        currency=seg_cost[1] if seg_cost else None,
        url=extract_url(segment),
    )
    p.confidence = score_confidence(p)
    return p


def extract_flight(text: str) -> Optional[Union[ParsedBooking, List[ParsedBooking]]]:
    """Parse one or more flight bookings out of pasted text.

    Returns None if no IATA airport-code pair is found. Returns a single
    ParsedBooking for one-segment flights, or a list (sorted by start_datetime,
    None-dated last) for multi-segment confirmations.
    """
    pairs = list(_RE_IATA_PAIR.finditer(text))
    if not pairs:
        return None

    email_vendor = _vendor_from_anchor_or_header(text)
    email_conf = extract_confirmation_number(text)
    email_cost = extract_money(text)

    # Each pair becomes a ParsedBooking only if its segment carries a
    # flight-specific signal — Nones are noise pairs from prose acronyms.
    segments: List[ParsedBooking] = [
        seg for seg in (
            _extract_one_segment(
                text,
                m.start(),
                m.end(),
                m.group(1),
                m.group(2),
                email_vendor,
                email_conf,
                email_cost,
            )
            for m in pairs
        )
        if seg is not None
    ]

    if not segments:
        return None
    if len(segments) == 1:
        return segments[0]
    # Multi-segment — sort by start_datetime (None-dated sort last).
    segments.sort(key=lambda s: (s.start_datetime is None, s.start_datetime))
    return segments


# ─────────────────────────────  extract_hotel  ─────────────────────────────


# Check-in / check-out anchors. \b-anchored and require `:` per Task 2 fix —
# stops "Departure" inside "Department of Transportation" from triggering.
# "Arrival" / "Departure" still match here (they're real hotel anchors too)
# but the negative-anchor _RE_IATA_PAIR check rejects flight emails before
# we get here, so the overlap is safe.
_RE_HOTEL_CHECKIN_ANCHOR = re.compile(
    r"\bCheck[- ]?in\b\s*:\s*(.+)", re.IGNORECASE
)
_RE_HOTEL_CHECKOUT_ANCHOR = re.compile(
    r"\bCheck[- ]?out\b\s*:\s*(.+)", re.IGNORECASE
)
_RE_HOTEL_ARRIVAL_ANCHOR = re.compile(
    r"\bArrival\b\s*:\s*(.+)", re.IGNORECASE
)
_RE_HOTEL_DEPARTURE_ANCHOR = re.compile(
    r"\bDeparture\b\s*:\s*(.+)", re.IGNORECASE
)

# Hotel vendor anchors. Lazy capture bounded by sentence terminators or
# end-of-line so prose like "Your stay at Marriott Times Square is
# confirmed…" stops at "is" instead of swallowing the rest of the line.
_RE_HOTEL_STAY_AT = re.compile(
    r"(?:Your\s+)?stay\s+at\s+([^\n]+?)(?:\s+is\b|\s+for\b|\s+on\b|[.,!]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_HOTEL_RESERVATION_AT = re.compile(
    r"\breservation\s+at\s+([^\n]+?)(?:\s+is\b|\s+for\b|\s+on\b|[.,!]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_HOTEL_ANCHOR = re.compile(
    r"\bHotel\b\s*:\s*(.+)", re.IGNORECASE
)

# Address block anchor.
_RE_ADDRESS_ANCHOR = re.compile(
    r"\bAddress\b\s*:\s*(.+)", re.IGNORECASE
)

# Party-size anchors.
_RE_PARTY_ANCHOR = re.compile(
    r"\b(?:Party|Guests|Travelers)\b\s*:\s*(.+)", re.IGNORECASE
)

# Known hotel chain names — fallback when no anchor phrase matches.
# Sorted longest-first so the regex alternation prefers specific names.
_KNOWN_HOTEL_CHAINS: Tuple[str, ...] = tuple(sorted(
    (
        "Mandarin Oriental",
        "Ritz-Carlton",
        "Four Seasons",
        "InterContinental",
        "Holiday Inn",
        "Best Western",
        "Premier Inn",
        "Comfort Inn",
        "Hampton Inn",
        "La Quinta",
        "Travelodge",
        "Marriott",
        "Sheraton",
        "Radisson",
        "Westin",
        "Hilton",
        "Hyatt",
        "Accor",
        "Aman",
        "Ibis",
    ),
    key=len,
    reverse=True,
))
_RE_KNOWN_HOTEL_CHAIN = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in _KNOWN_HOTEL_CHAINS) + r")\b",
    re.IGNORECASE,
)

# Aggregator brand names to strip out of subject-line vendor fallback.
_HOTEL_AGGREGATOR_NAMES = ("Booking.com", "Airbnb", "Expedia", "Hotels.com", "Agoda", "Vrbo")

# Hotel-time defaults when only a date is given.
_HOTEL_CHECKIN_DEFAULT_HOUR = 15
_HOTEL_CHECKOUT_DEFAULT_HOUR = 11


# Matches a clock time like "3:00 PM" or "15:30". Used for both presence
# checks (_line_has_time) and to extract hour/minute/ampm (_parse_clock_time).
_RE_CLOCK_TIME = re.compile(
    r"\b(\d{1,2}):(\d{2})(?:\s*(AM|PM))?\b", re.IGNORECASE
)


def _line_has_time(line: str) -> bool:
    return bool(_RE_CLOCK_TIME.search(line))


def _parse_clock_time(s: str) -> Optional[Tuple[int, int]]:
    """Parse '2:00 PM' / '14:30' → (14, 0) / (14, 30). None on bad input."""
    m = _RE_CLOCK_TIME.search(s)
    if not m:
        return None
    try:
        hour = _to_24h(int(m.group(1)), m.group(3))
        minute = int(m.group(2))
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour, minute


def _datetime_with_default_hour(line: str, default_hour: int) -> Optional[datetime]:
    """Parse the first date in `line`; if no time was provided, snap to default_hour.

    Handles the "ISO date + separate time" form that extract_dates' ISO regex
    misses ("2026-07-22 at 2:00 PM" — the ISO datetime regex requires a 2-digit
    hour and a T or space, not " at "). In that case we parse the time
    portion of the line separately and merge it into the date.
    """
    dates = extract_dates(line)
    if not dates:
        return None
    dt = dates[0]
    if dt.hour == 0 and dt.minute == 0:
        if _line_has_time(line):
            parsed_time = _parse_clock_time(line)
            if parsed_time is not None:
                h, mi = parsed_time
                return dt.replace(hour=h, minute=mi)
        else:
            return dt.replace(hour=default_hour, minute=0)
    return dt


def _hotel_vendor(text: str) -> Optional[str]:
    """Find the hotel name via anchor phrases, then known-chain header scan."""
    for anchor in (_RE_HOTEL_STAY_AT, _RE_HOTEL_RESERVATION_AT, _RE_HOTEL_ANCHOR):
        m = anchor.search(text)
        if m:
            name = m.group(1).strip()
            # Strip aggregator brand if it leaked into the capture.
            for agg in _HOTEL_AGGREGATOR_NAMES:
                if name.lower().startswith(agg.lower()):
                    name = name[len(agg):].lstrip(" :—-").strip()
            if name:
                return name

    # Fallback: scan first ~6 lines for a known chain name and use the
    # whole line as the vendor (keeps "Hampton Inn & Suites Tysons Corner"
    # together rather than just "Hampton Inn").
    header_lines = text.splitlines()[:6]
    for line in header_lines:
        m = _RE_KNOWN_HOTEL_CHAIN.search(line)
        if m:
            stripped = line.strip()
            # Drop leading "Hotel:" / "Hotel " labels.
            stripped = re.sub(r"^Hotel\s*:?\s*", "", stripped, flags=re.IGNORECASE)
            return stripped or m.group(1)
    return None


def _hotel_location(text: str, vendor: Optional[str]) -> Optional[str]:
    """Address from explicit `Address:` anchor, else line immediately after vendor.

    The vendor-line match requires the line to BE the vendor name (modulo
    surrounding whitespace) or to END with it — that way a line containing
    the vendor as part of a longer sentence (e.g. "Manage your reservation
    at Marriott.com") does not false-match.
    """
    m = _RE_ADDRESS_ANCHOR.search(text)
    if m:
        return m.group(1).strip() or None

    if vendor:
        target = vendor.strip().lower()
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            if (stripped == target or stripped.endswith(target)) and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line:
                    return next_line
    return None


def _hotel_party(text: str) -> Optional[str]:
    m = _RE_PARTY_ANCHOR.search(text)
    return m.group(1).strip() if m else None


def extract_hotel(text: str) -> Optional[ParsedBooking]:
    """Parse a hotel booking out of pasted text.

    Returns None if:
      - the text looks like a flight (contains an IATA airport-code pair), OR
      - neither a check-in nor check-out anchor is present.
    """
    # Negative anchor: a flight email shouldn't reach the hotel branch.
    if _RE_IATA_PAIR.search(text):
        return None

    checkin_match = (
        _RE_HOTEL_CHECKIN_ANCHOR.search(text) or _RE_HOTEL_ARRIVAL_ANCHOR.search(text)
    )
    checkout_match = (
        _RE_HOTEL_CHECKOUT_ANCHOR.search(text) or _RE_HOTEL_DEPARTURE_ANCHOR.search(text)
    )
    if not (checkin_match and checkout_match):
        return None

    vendor = _hotel_vendor(text)
    title = vendor if vendor else "Hotel stay"

    start_dt = _datetime_with_default_hour(
        checkin_match.group(1), _HOTEL_CHECKIN_DEFAULT_HOUR
    )
    end_dt = _datetime_with_default_hour(
        checkout_match.group(1), _HOTEL_CHECKOUT_DEFAULT_HOUR
    )

    location = _hotel_location(text, vendor)
    conf = extract_confirmation_number(text)
    cost = extract_money(text)
    url = extract_url(text)
    notes = _hotel_party(text)

    p = ParsedBooking(
        type="hotel",
        title=title,
        vendor=vendor,
        confirmation_number=conf,
        start_datetime=start_dt,
        end_datetime=end_dt,
        location=location,
        cost=cost[0] if cost else None,
        currency=cost[1] if cost else None,
        url=url,
        notes=notes,
    )
    p.confidence = score_confidence(p)
    return p


# ─────────────────────────────  extract_car  ───────────────────────────────


# Pick-up / drop-off anchors. \b-bounded with required `:` per Task 3 fix —
# stops words like "Returning" or "Pickup line" from triggering when the
# anchor is unrelated prose. Capture the tail of the line for date parsing.
_RE_CAR_PICKUP_ANCHOR = re.compile(
    r"\b(?:Pick[- ]?up|Collect)\b\s*:\s*(.+)", re.IGNORECASE
)
_RE_CAR_DROPOFF_ANCHOR = re.compile(
    r"\b(?:Drop[- ]?off|Return)\b\s*:\s*(.+)", re.IGNORECASE
)

# Pick-up location anchor — distinct from the datetime anchor.
_RE_CAR_PICKUP_LOCATION = re.compile(
    r"\bPick[- ]?up\s+location\b\s*:\s*(.+)", re.IGNORECASE
)

# Rental-company vendor anchors.
_RE_CAR_VENDOR_ANCHOR = re.compile(
    r"\b(?:Rental\s+company|Rented\s+from|Vendor)\b\s*:\s*([^\n]+?)(?:[.,!]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Known rental companies — fallback when no anchor phrase matches.
# Sorted longest-first so the alternation prefers specific multi-word names
# ("Fox Rent A Car" over "Fox").
_KNOWN_RENTAL_COMPANIES: Tuple[str, ...] = tuple(sorted(
    (
        "Fox Rent A Car",
        "Ace Rent A Car",
        "Europcar",
        "National",
        "Thrifty",
        "Payless",
        "Hertz",
        "Avis",
        "Sixt",
        "Budget",
        "Alamo",
        "Dollar",
        "Turo",
        "Enterprise",
    ),
    key=len,
    reverse=True,
))
_RE_KNOWN_RENTAL_COMPANY = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in _KNOWN_RENTAL_COMPANIES) + r")\b",
    re.IGNORECASE,
)

# Car-time default when only a date is given.
_CAR_DEFAULT_HOUR = 10


def _car_vendor(text: str) -> Optional[str]:
    """Find the rental company via anchor phrase, then known-list header scan."""
    m = _RE_CAR_VENDOR_ANCHOR.search(text)
    if m:
        name = m.group(1).strip()
        if name:
            return name

    # Fallback: scan first ~6 lines for a known rental company.
    header = "\n".join(text.splitlines()[:6])
    m = _RE_KNOWN_RENTAL_COMPANY.search(header)
    if m:
        # Return the canonical-case form from our list (case-insensitive match
        # → match group is in input case; look up the canonical spelling).
        matched_lower = m.group(1).lower()
        for canonical in _KNOWN_RENTAL_COMPANIES:
            if canonical.lower() == matched_lower:
                return canonical
        return m.group(1)
    return None


def _car_pickup_location(text: str, pickup_line: str) -> Optional[str]:
    """Pickup location from explicit `Pick-up location:` anchor, else
    the same-line text after the pickup datetime (split on em-dash)."""
    m = _RE_CAR_PICKUP_LOCATION.search(text)
    if m:
        loc = m.group(1).strip()
        if loc:
            return loc

    # Same-line fallback: "Pick-up: Mon, Jun 14 2026 at 10:00 AM — LAX Hertz Counter"
    # Try em-dash first, then ascii hyphen surrounded by spaces.
    for sep in (" — ", " - "):
        if sep in pickup_line:
            tail = pickup_line.split(sep, 1)[1].strip()
            if tail:
                return tail
    return None


def extract_car(text: str) -> Optional[ParsedBooking]:
    """Parse a car rental booking out of pasted text.

    Returns None if:
      - the text looks like a flight (contains an IATA airport-code pair), OR
      - the text looks like a hotel (has a check-in anchor), OR
      - either a pickup or drop-off anchor is missing.
    """
    # Negative anchors: car emails shouldn't bleed across to flight or hotel.
    if _RE_IATA_PAIR.search(text):
        return None
    if _RE_HOTEL_CHECKIN_ANCHOR.search(text):
        return None

    pickup_match = _RE_CAR_PICKUP_ANCHOR.search(text)
    dropoff_match = _RE_CAR_DROPOFF_ANCHOR.search(text)
    if not (pickup_match and dropoff_match):
        return None

    vendor = _car_vendor(text)
    title = f"{vendor} car rental" if vendor else "Car rental"

    start_dt = _datetime_with_default_hour(pickup_match.group(1), _CAR_DEFAULT_HOUR)
    end_dt = _datetime_with_default_hour(dropoff_match.group(1), _CAR_DEFAULT_HOUR)

    location = _car_pickup_location(text, pickup_match.group(1))
    conf = extract_confirmation_number(text)
    cost = extract_money(text)
    url = extract_url(text)

    p = ParsedBooking(
        type="car",
        title=title,
        vendor=vendor,
        confirmation_number=conf,
        start_datetime=start_dt,
        end_datetime=end_dt,
        location=location,
        cost=cost[0] if cost else None,
        currency=cost[1] if cost else None,
        url=url,
    )
    p.confidence = score_confidence(p)
    return p


# ─────────────────────────────  extract_restaurant  ────────────────────────


# Required-anchor regexes. \b-bounded; the colon-form anchors require `:` so
# casual mentions of "reservation" inside hotel prose don't false-match.
# The "<anchor> at" forms (no colon) need the "at" itself as the disambiguator.
_RESTAURANT_REQUIRED_ANCHORS = (
    r"\bReservation\b\s*:",
    r"\bTable\s+for\b\s*:",
    r"\bBooking\s+confirmed\b\s*:",
    r"\breservation\s+at\b",
    r"\btable\s+at\b",
    r"\bbooking\s+confirmed\s+at\b",
)
_RE_RESTAURANT_REQUIRED_ANCHOR = re.compile(
    "|".join(_RESTAURANT_REQUIRED_ANCHORS), re.IGNORECASE
)

# Vendor anchors — `at <name>` forms. Lazy capture bounded by sentence
# terminators / control words so it doesn't swallow trailing prose.
_RE_RESTAURANT_AT_VENDOR = re.compile(
    r"(?:Your\s+)?(?:reservation|table|booking\s+confirmed)\s+at\s+([^\n]+?)"
    r"(?:\s+is\b|\s+for\b|\s+on\b|[.,!]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Restaurant aggregator brand names — stripped from subject-line vendor
# fallback the same way hotel aggregators are. Sorted longest-first for
# greedy regex alt safety.
_RESTAURANT_AGGREGATOR_NAMES: Tuple[str, ...] = tuple(sorted(
    ("OpenTable", "SevenRooms", "TheFork", "Resy", "Yelp", "Tock"),
    key=len,
    reverse=True,
))

# Party-size anchor for the notes field.
_RE_RESTAURANT_PARTY = re.compile(
    r"\b(?:Party\s+of|Table\s+for|Guests?:)\s*(\d+)\b", re.IGNORECASE
)


def _restaurant_vendor(text: str) -> Optional[str]:
    """Find the restaurant name via `at <X>` anchors, stripping aggregator prefixes."""
    m = _RE_RESTAURANT_AT_VENDOR.search(text)
    if m:
        name = m.group(1).strip()
        # Strip aggregator brand if it leaked into the capture.
        for agg in _RESTAURANT_AGGREGATOR_NAMES:
            if name.lower().startswith(agg.lower()):
                name = name[len(agg):].lstrip(" :—-").strip()
        if name:
            return name
    return None


# Address-like line: starts with a street number, has a comma, and looks like
# a postal address. Used as the restaurant-location heuristic when there's no
# `Address:` anchor — restaurant emails rarely use one.
_RE_ADDRESS_LIKE_LINE = re.compile(
    r"^\s*\d+\s+[^,\n]+,[^,\n]+(?:,[^\n]+)?\s*$"
)


def _restaurant_location(text: str) -> Optional[str]:
    """Address from explicit `Address:` anchor, else first address-like line.

    Address-like = starts with a street number, has at least one comma. This
    is the same heuristic used for "real" addresses in postal contexts; it
    won't false-match on date lines or party-size lines.
    """
    m = _RE_ADDRESS_ANCHOR.search(text)
    if m:
        return m.group(1).strip() or None

    for line in text.splitlines():
        if _RE_ADDRESS_LIKE_LINE.match(line):
            return line.strip()
    return None


def _restaurant_party_notes(text: str) -> Optional[str]:
    """Extract a 'Party of N' summary if any party-size anchor is present."""
    m = _RE_RESTAURANT_PARTY.search(text)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return f"Party of {n}"


def extract_restaurant(text: str) -> Optional[ParsedBooking]:
    """Parse a restaurant reservation out of pasted text.

    Returns None if:
      - the text looks like a flight (IATA airport-code pair), OR
      - the text looks like a hotel (check-in anchor), OR
      - the text looks like a car rental (pick-up anchor), OR
      - none of the restaurant required-anchors are present.
    """
    # Triple-negative anchors: a flight, hotel, or car email should never
    # reach the restaurant branch even if the word "reservation" appears.
    if _RE_IATA_PAIR.search(text):
        return None
    if _RE_HOTEL_CHECKIN_ANCHOR.search(text):
        return None
    if _RE_CAR_PICKUP_ANCHOR.search(text):
        return None

    if not _RE_RESTAURANT_REQUIRED_ANCHOR.search(text):
        return None

    vendor = _restaurant_vendor(text)
    title = f"Reservation at {vendor}" if vendor else "Restaurant reservation"

    dates = extract_dates(text)
    # Use the time as found — don't guess a 7pm default; the spec says
    # missing time means the slot isn't clearly stated and None is honest.
    start_dt: Optional[datetime] = None
    for d in dates:
        if d.hour != 0 or d.minute != 0:
            start_dt = d
            break

    location = _restaurant_location(text)
    conf = extract_confirmation_number(text)
    cost = extract_money(text)
    url = extract_url(text)
    notes = _restaurant_party_notes(text)

    p = ParsedBooking(
        type="restaurant",
        title=title,
        vendor=vendor,
        confirmation_number=conf,
        start_datetime=start_dt,
        end_datetime=None,
        location=location,
        cost=cost[0] if cost else None,
        currency=cost[1] if cost else None,
        url=url,
        notes=notes,
    )
    p.confidence = score_confidence(p)
    return p


# ─────────────────────────────  extract_activity  ──────────────────────────


# Required-anchor regexes. \b-bounded; the colon-form anchors require `:` so
# casual mentions of "ticket" or "event" inside other-type prose don't
# false-match. Ordered roughly by specificity — alternation is non-greedy
# enough that order rarely matters but we keep the "(s)" forms grouped.
_ACTIVITY_REQUIRED_ANCHORS = (
    r"\bTickets?\s+for\b\s*:",
    r"\bTicket\(s\)\s+for\b\s*:?",
    r"\bYour\s+tickets?\s+for\b",
    r"\bTour\b\s*:",
    r"\bAdmission\b\s*:",
    r"\bEvent\b\s*:",
    r"\bBooking\s+for\b\s*:",
)
_RE_ACTIVITY_REQUIRED_ANCHOR = re.compile(
    "|".join(_ACTIVITY_REQUIRED_ANCHORS), re.IGNORECASE
)

# Title-capturing anchors: `Tickets for: <name>`, `Your tickets for: <name>`,
# `Booking for: <name>`. Lazy capture bounded by newline / sentence terminator.
# The `\s+at\s+` boundary keeps the venue ("...at Madison Square Garden")
# out of the title — venue belongs in `location`.
_RE_ACTIVITY_TICKETS_FOR = re.compile(
    r"(?:Your\s+)?Tickets?\s+for\s*:\s*([^\n]+?)(?:\s+at\s+|[.!]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_ACTIVITY_BOOKING_FOR = re.compile(
    r"\bBooking\s+for\s*:\s*([^\n]+?)(?:[.!]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Vendor anchors — `at <X>`, `Hosted by <X>`, `Your visit to <X>`. Lazy
# capture bounded by sentence terminators / control words, mirroring hotel /
# restaurant patterns.
_RE_ACTIVITY_HOSTED_BY = re.compile(
    r"\bHosted\s+by\s+([^\n]+?)(?:\s+is\b|\s+on\b|[.,!]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_ACTIVITY_YOUR_VISIT_TO = re.compile(
    r"\bYour\s+visit\s+to\s+([^\n]+?)(?:\s+is\b|\s+on\b|[.,!]|$)",
    re.IGNORECASE | re.MULTILINE,
)
_RE_ACTIVITY_TICKETS_AT = re.compile(
    r"\bTickets?\s+for\s+[^\n]+?\s+at\s+([^\n]+?)(?:\s+is\b|\s+on\b|[.,!]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Venue / location anchors.
_RE_ACTIVITY_VENUE = re.compile(
    r"\bVenue\b\s*:\s*(.+)", re.IGNORECASE
)
_RE_ACTIVITY_LOCATION = re.compile(
    r"\bLocation\b\s*:\s*(.+)", re.IGNORECASE
)

# End-time anchors — most activities are single-point so end_datetime stays
# None. These let us pick up the rare explicit case. `Ends at` is the only
# anchor we trust; a bare `until <date>` false-matches refund-policy lines
# like "Refundable until July 17 2026 at 11:59 PM" so we don't accept it.
_RE_ACTIVITY_ENDS_AT = re.compile(
    r"\bEnds\s+at\b\s*:?\s*(.+)", re.IGNORECASE
)

# Activity aggregator brand names — stripped from subject-line / title
# vendor fallback the same way hotel + restaurant aggregators are. Sorted
# longest-first for greedy regex alt safety.
_ACTIVITY_AGGREGATOR_NAMES: Tuple[str, ...] = tuple(sorted(
    (
        "Atlas Obscura",
        "GetYourGuide",
        "TripAdvisor",
        "Ticketmaster",
        "Eventbrite",
        "StubHub",
        "Viator",
        "Klook",
    ),
    key=len,
    reverse=True,
))


def _strip_aggregator_prefix(name: str) -> str:
    """Strip a leading aggregator brand (case-insensitive) + common separators."""
    for agg in _ACTIVITY_AGGREGATOR_NAMES:
        if name.lower().startswith(agg.lower()):
            return name[len(agg):].lstrip(" :—-").strip()
    return name


def _activity_vendor(text: str) -> Optional[str]:
    """Find the activity provider via `at <X>` / `Hosted by <X>` / `Your visit to <X>` anchors."""
    for anchor in (
        _RE_ACTIVITY_TICKETS_AT,
        _RE_ACTIVITY_HOSTED_BY,
        _RE_ACTIVITY_YOUR_VISIT_TO,
    ):
        m = anchor.search(text)
        if m:
            name = _strip_aggregator_prefix(m.group(1).strip())
            if name:
                return name
    return None


def _activity_title(text: str, vendor: Optional[str]) -> str:
    """Pick the best title: anchor capture, first-line subject, or a fallback.

    Order:
      1. `Tickets for: <Event>` / `Your tickets for: <Event>` / `Booking for: <Event>`.
      2. First non-blank line, stripped of aggregator prefix — if what
         remains isn't empty AND isn't just an aggregator name on its own.
      3. `f"{vendor} event"` if vendor is known.
      4. `"Activity booking"`.
    """
    for anchor in (_RE_ACTIVITY_TICKETS_FOR, _RE_ACTIVITY_BOOKING_FOR):
        m = anchor.search(text)
        if m:
            name = m.group(1).strip()
            if name:
                return name

    # First-line subject fallback.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip if the line IS just an aggregator name (e.g. "Eventbrite").
        if stripped.lower() in {a.lower() for a in _ACTIVITY_AGGREGATOR_NAMES}:
            continue
        candidate = _strip_aggregator_prefix(stripped)
        if candidate:
            return candidate
        # else: keep looking
        break

    if vendor:
        return f"{vendor} event"
    return "Activity booking"


def _activity_location(text: str) -> Optional[str]:
    """Venue address from `Venue:`, `Location:`, or `Address:` anchor."""
    for anchor in (_RE_ACTIVITY_VENUE, _RE_ACTIVITY_LOCATION, _RE_ADDRESS_ANCHOR):
        m = anchor.search(text)
        if m:
            value = m.group(1).strip()
            if value:
                return value
    return None


def _activity_end_datetime(text: str) -> Optional[datetime]:
    """Look for an explicit end time — only the `Ends at:` anchor is trusted."""
    m = _RE_ACTIVITY_ENDS_AT.search(text)
    if m:
        dates = extract_dates(m.group(1))
        if dates:
            return dates[0]
    return None


def extract_activity(text: str) -> Optional[ParsedBooking]:
    """Parse a single activity / event ticket out of pasted text.

    Returns None if:
      - the text looks like a flight (IATA airport-code pair), OR
      - the text looks like a hotel (check-in anchor), OR
      - the text looks like a car rental (pick-up anchor), OR
      - none of the activity required-anchors are present.
    """
    # Triple-negative anchors: a flight, hotel, or car email should never
    # reach the activity branch even if the word "ticket" appears.
    if _RE_IATA_PAIR.search(text):
        return None
    if _RE_HOTEL_CHECKIN_ANCHOR.search(text):
        return None
    if _RE_CAR_PICKUP_ANCHOR.search(text):
        return None

    if not _RE_ACTIVITY_REQUIRED_ANCHOR.search(text):
        return None

    vendor = _activity_vendor(text)
    title = _activity_title(text, vendor)

    # start_datetime: first datetime in text, excluding refund-policy lines
    # ("Refundable until <date>" must not pose as the event time). No
    # default hour — None when the paste is date-only (per spec).
    event_text = "\n".join(
        line for line in text.splitlines()
        if "refund" not in line.lower()
    )
    dates = extract_dates(event_text)
    start_dt: Optional[datetime] = dates[0] if dates else None
    end_dt = _activity_end_datetime(text)

    location = _activity_location(text)
    conf = extract_confirmation_number(text)
    cost = extract_money(text)
    url = extract_url(text)

    p = ParsedBooking(
        type="activity",
        title=title,
        vendor=vendor,
        confirmation_number=conf,
        start_datetime=start_dt,
        end_datetime=end_dt,
        location=location,
        cost=cost[0] if cost else None,
        currency=cost[1] if cost else None,
        url=url,
    )
    p.confidence = score_confidence(p)
    return p


# ─────────────────────────────  extract_transport  ─────────────────────────


# Transport-type keyword anchor. The keyword itself doesn't need a colon —
# it just needs to appear somewhere in the email. Case-insensitive, \b-bounded
# so "Coachman" doesn't trip the "Coach" anchor.
_RE_TRANSPORT_TYPE_KEYWORD = re.compile(
    r"\b(?:Train|Rail|Ferry|Bus|Coach)\b", re.IGNORECASE
)

# Origin → Destination pair on a single line. Line-anchored (MULTILINE) and
# the inner character classes use a literal space (not \s) so the capture
# can't accidentally span newlines — the MULTILINE line anchors only enforce
# line boundaries at the outer edges, not within the inner captures.
# Origin/dest must start with a letter (so date/price lines like
# "Total: $89.00" can't pose as a station name) and may include letters,
# digits, spaces, apostrophes, periods, and hyphens (covers "St Pancras",
# "Hook of Holland", "Gare d'Austerlitz" modulo the apostrophe limitation).
#
# Known limitation: French station names with apostrophes like "Gare
# d'Austerlitz" are matched (apostrophe is in the class) but anything past
# a non-`[\w '.\-]` character will be truncated. Acceptable for v1.
_RE_TRANSPORT_OD_PAIR = re.compile(
    r"^[ \t]*([A-Za-z][\w '.\-]*?)[ \t]*(?:→|->|—|\s-\s|\sto\s)[ \t]*"
    r"([A-Za-z][\w '.\-]+?)[ \t]*$",
    re.MULTILINE,
)

# Carrier vendor anchors.
_RE_TRANSPORT_VENDOR_ANCHOR = re.compile(
    r"\b(?:Train\s+operator|Operator|Carrier)\s*:\s*([^\n]+?)(?:[.,!]|$)",
    re.IGNORECASE | re.MULTILINE,
)

# Departure / arrival anchors. The plain-flight `_RE_DEP_ANCHOR` already
# matches `Depart:` / `Departure:`; we also want `Leaving:`.
_RE_TRANSPORT_DEP_ANCHOR = re.compile(
    r"\b(?:Depart(?:ure|ing|s)?|Leaving)\b\s*:\s*(.+)", re.IGNORECASE
)
_RE_TRANSPORT_ARR_ANCHOR = re.compile(
    r"\bArriv(?:e|es|al|ing)\b\s*:\s*(.+)", re.IGNORECASE
)

# Known transport carriers — fallback when no anchor matches. Sorted
# longest-first so multi-word names ("Deutsche Bahn") beat shorter ones
# ("DB") in the alternation.
_KNOWN_TRANSPORT_CARRIERS: Tuple[str, ...] = tuple(sorted(
    (
        "Amtrak",
        "Eurostar",
        "Greyhound",
        "FlixBus",
        "Megabus",
        "OUIGO",
        "SNCF",
        "DB",
        "Deutsche Bahn",
        "Trenitalia",
        "Italo",
        "Renfe",
        "AVE",
        "ÖBB",
        "NS",
        "Eurail",
        "ScotRail",
        "LNER",
        "GWR",
        "Northern",
        "Avanti",
        "JR",
        "Japan Rail",
        "Shinkansen",
        "Stena Line",
        "Brittany Ferries",
        "P&O",
        "DFDS",
        "MSC",
    ),
    key=len,
    reverse=True,
))
_RE_KNOWN_TRANSPORT_CARRIER = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in _KNOWN_TRANSPORT_CARRIERS) + r")\b",
    re.IGNORECASE,
)

# Transport-type keyword words to reject if they pose as the origin or
# destination of an O→D pair (e.g. a stray "Train to airport" sentence).
_TRANSPORT_TYPE_WORDS = {"train", "rail", "ferry", "bus", "coach"}


def _transport_vendor(text: str) -> Optional[str]:
    """Find the carrier via anchor phrase, then known-carrier header scan."""
    m = _RE_TRANSPORT_VENDOR_ANCHOR.search(text)
    if m:
        name = m.group(1).strip()
        if name:
            return name

    # Fallback: scan first ~6 lines for a known carrier name.
    header = "\n".join(text.splitlines()[:6])
    m = _RE_KNOWN_TRANSPORT_CARRIER.search(header)
    if m:
        # Canonical-case lookup so "amtrak" → "Amtrak".
        matched_lower = m.group(1).lower()
        for canonical in _KNOWN_TRANSPORT_CARRIERS:
            if canonical.lower() == matched_lower:
                return canonical
        return m.group(1)
    return None


def _transport_od_pair(text: str) -> Optional[Tuple[str, str]]:
    """Find the first valid origin → destination pair.

    Rejects matches where either end is a transport-type keyword
    (e.g. "Train to airport") or a known carrier name (e.g. the email
    subject line "Amtrak — Trip Confirmation" which falsely looks like
    an O→D pair because em-dash is also a separator).
    """
    carrier_names_lower = {c.lower() for c in _KNOWN_TRANSPORT_CARRIERS}
    for m in _RE_TRANSPORT_OD_PAIR.finditer(text):
        origin = m.group(1).strip()
        destination = m.group(2).strip()
        o_lower = origin.lower()
        d_lower = destination.lower()
        if o_lower in _TRANSPORT_TYPE_WORDS or d_lower in _TRANSPORT_TYPE_WORDS:
            continue
        if o_lower in carrier_names_lower or d_lower in carrier_names_lower:
            continue
        return origin, destination
    return None


def _looks_like_real_flight(text: str) -> bool:
    """True if the text has an IATA airport-code pair that isn't a
    confirmation-number artefact like 'AMT-7721-NER'.

    The bare `_RE_IATA_PAIR` regex is permissive — it spans up to 60
    non-newline chars between the two 3-letter groups, so a confirmation
    number `XXX-DIGITS-YYY` looks like a pair. We additionally require
    that the matched span between the two codes is not purely numeric
    (with hyphens), which is what those confirmation tokens look like.
    """
    for m in _RE_IATA_PAIR.finditer(text):
        between = text[m.start(1) + len(m.group(1)) : m.start(2)]
        # If everything between the two codes is digits/hyphens, it's a
        # confirmation number, not a flight pair. Real flight pairs have
        # an arrow, the word "to", or city names with letters.
        if re.fullmatch(r"[\d\-\s]+", between):
            continue
        return True
    return False


def extract_transport(text: str) -> Optional[ParsedBooking]:
    """Parse a train / ferry / bus / coach booking out of pasted text.

    Returns None if:
      - the text looks like a flight (real IATA airport-code pair, not a
        confirmation-number artefact) — that's a flight, not transport, OR
      - no transport-type keyword (Train / Rail / Ferry / Bus / Coach) is
        present, OR
      - no origin → destination pair is found.

    v1 is single-segment per email. Multi-leg trains would warrant a
    multi-segment shape later.
    """
    # Negative anchor: a flight email shouldn't reach the transport branch.
    if _looks_like_real_flight(text):
        return None

    if not _RE_TRANSPORT_TYPE_KEYWORD.search(text):
        return None

    od = _transport_od_pair(text)
    if od is None:
        return None
    origin, destination = od

    vendor = _transport_vendor(text)
    if vendor:
        title = f"{vendor}: {origin} → {destination}"
    else:
        title = f"{origin} → {destination}"

    start_dt = _datetime_for_anchor(text, _RE_TRANSPORT_DEP_ANCHOR)
    end_dt = _datetime_for_anchor(text, _RE_TRANSPORT_ARR_ANCHOR)

    conf = extract_confirmation_number(text)
    cost = extract_money(text)
    url = extract_url(text)

    p = ParsedBooking(
        type="transport",
        title=title,
        vendor=vendor,
        confirmation_number=conf,
        start_datetime=start_dt,
        end_datetime=end_dt,
        location=origin,
        cost=cost[0] if cost else None,
        currency=cost[1] if cost else None,
        url=url,
    )
    p.confidence = score_confidence(p)
    return p


# ─────────────────────────────  extract_other  ─────────────────────────────


# Aggregator-like prefixes to strip from a title pulled from an email's first
# line (e.g. forwarded or replied threads land with `Re:` / `Fwd:` headers).
_RE_TITLE_PREFIX = re.compile(r"^(re|fwd|fw):\s*", re.IGNORECASE)

# Cap applied to the score so the catch-all rarely outranks a real extractor.
_OTHER_CONFIDENCE_CAP = 0.5

# How many leading non-empty lines to scan for a non-banner title before
# giving up and using the first one as-is.
_TITLE_SCAN_LIMIT = 10


def _first_nonempty_line(text: str) -> Optional[str]:
    """First line in text that isn't empty/whitespace-only."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _looks_like_banner(line: str) -> bool:
    """True if a line reads like a generic marketing header banner.

    Banners are all-uppercase marketing headers ("YOUR RESERVATION IS
    CONFIRMED", "ORDER RECEIVED") — they make poor titles because they
    don't carry the specific subject of the email. The check requires at
    least three letters so short tokens like "OK" or "HI" don't disqualify
    themselves. Digits, punctuation, and whitespace don't count.
    """
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 3:
        return False
    return all(c.isupper() for c in letters)


def _best_title_line(text: str) -> Optional[str]:
    """Pick the first non-banner non-empty line in the leading window.

    Falls back to the first non-empty line if every line in the scan
    window looks like a banner — that way we always return *something*
    rather than dropping a booking on the floor for the catch-all.
    """
    seen: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        seen.append(stripped)
        if not _looks_like_banner(stripped):
            return stripped
        if len(seen) >= _TITLE_SCAN_LIMIT:
            break
    return seen[0] if seen else None


def extract_other(text: str) -> Optional[ParsedBooking]:
    """Catch-all extractor — runs after every typed extractor returns None.

    Returns None only when the text is genuinely empty: no dates, no money,
    and no confirmation number. Otherwise builds a low-confidence
    ParsedBooking from whatever the shared helpers can find, capped at 0.5
    confidence so a real-type extractor always wins.
    """
    dates = extract_dates(text)
    money = extract_money(text)
    conf = extract_confirmation_number(text)

    if not dates and money is None and conf is None:
        return None

    title_line = _best_title_line(text)
    if not title_line:
        return None
    title = _RE_TITLE_PREFIX.sub("", title_line)

    p = ParsedBooking(
        type="other",
        title=title,
        vendor=None,
        confirmation_number=conf,
        start_datetime=dates[0] if dates else None,
        end_datetime=None,
        location=None,
        cost=money[0] if money else None,
        currency=money[1] if money else None,
        url=extract_url(text),
        notes=None,
    )
    p.confidence = min(score_confidence(p), _OTHER_CONFIDENCE_CAP)
    return p


# ─────────────────────────────  parse_rules  ───────────────────────────────


# All per-type extractors, run in declaration order. extract_other is the
# weak catch-all and runs last so high-confidence typed matches win the
# top spot after sorting.
_EXTRACTORS = (
    extract_flight,
    extract_hotel,
    extract_car,
    extract_restaurant,
    extract_activity,
    extract_transport,
    extract_other,
)


def parse_rules(text: str) -> List[ParsedBooking]:
    """Run all 7 extractors, filter by confidence, cap at MAX_BOOKINGS_PER_PARSE.

    Each extractor returns:
      - None — no match
      - ParsedBooking — single segment
      - list[ParsedBooking] — multiple segments (currently only flight does this)

    Returns: list of ParsedBooking sorted by confidence descending, then by
    start_datetime ascending (None-dated bookings sort last).
    """
    results: List[ParsedBooking] = []
    for extractor in _EXTRACTORS:
        out = extractor(text)
        if out is None:
            continue
        if isinstance(out, list):
            results.extend(out)
        else:
            results.append(out)

    # Suppress the catch-all "other" extractor when any typed extractor matched.
    # extract_other fires whenever dates + money + a confirmation number are
    # present (i.e. every real booking email), so without this filter a single
    # flight paste would produce 2 results and route the UI to the multi-
    # booking review screen instead of the single-form pre-fill.
    typed_results = [b for b in results if b.type != "other"]
    if typed_results:
        results = typed_results

    # Drop anything below the confidence floor.
    kept = [r for r in results if r.confidence >= MIN_CONFIDENCE]

    # Sort: highest confidence first; ties broken by earliest start_datetime;
    # None-dated bookings sort last (tuple `(is_none, value)` keeps Python
    # 3.9 happy without mixing None with datetime in a comparison).
    kept.sort(
        key=lambda b: (
            -b.confidence,
            b.start_datetime is None,
            b.start_datetime or datetime.min,
        )
    )

    return kept[:MAX_BOOKINGS_PER_PARSE]


# ─────────────────────────────  LLM fallback  ─────────────────────────────
#
# Optional gated path that hands the paste to Claude for structured extraction.
# Deliberately lazy-imported so the module loads cleanly without the
# `anthropic` or `pydantic` SDKs installed — the gate fails first.

# Pydantic schema for Anthropic structured-output parsing. Lazy-defined so
# the module imports cleanly without pydantic. If pydantic isn't installed,
# `_HAS_PYDANTIC` stays False and parse_with_llm's gate fails before it
# would ever touch BatchedParsedBookings.
try:
    from pydantic import BaseModel as _PydanticBaseModel

    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False
    _PydanticBaseModel = object  # placeholder so class def doesn't crash


if _HAS_PYDANTIC:

    class ParsedBookingSchema(_PydanticBaseModel):
        """Pydantic mirror of ParsedBooking minus bookkeeping fields."""

        type: str  # one of: flight, hotel, car, restaurant, activity, transport, other
        title: str
        vendor: Optional[str] = None
        confirmation_number: Optional[str] = None
        start_datetime: Optional[str] = None  # ISO 8601; converted post-parse
        end_datetime: Optional[str] = None
        location: Optional[str] = None
        cost: Optional[float] = None
        currency: Optional[str] = None  # ISO 4217 code
        url: Optional[str] = None
        notes: Optional[str] = None

    class BatchedParsedBookings(_PydanticBaseModel):
        bookings: List[ParsedBookingSchema]


def _llm_gates_pass() -> bool:
    """True iff ANTHROPIC_API_KEY is set AND PASTE_PARSER_LLM_ENABLED='1'
    AND the `anthropic` SDK is importable. Lazy import — never raises."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    if os.environ.get(LLM_GATE_ENV_FLAG) != "1":
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _safe_iso(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 string into a datetime, or return None on failure.

    Accepts a trailing 'Z' by normalising it to '+00:00' for fromisoformat.
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_with_llm(text: str) -> List[ParsedBooking]:
    """Call Claude with a structured-output schema, parse to ParsedBookings.

    Returns [] on any API/network/schema/import error. Caller is responsible
    for checking _llm_gates_pass() first (this fn re-checks defensively).
    """
    if not _llm_gates_pass():
        return []

    try:
        from anthropic import Anthropic

        client = Anthropic()  # reads ANTHROPIC_API_KEY from env

        system_prompt = (
            "You are extracting structured booking data from a pasted email body. "
            "Identify each booking the email describes and return them as a list. "
            "Cap your list at " + str(MAX_BOOKINGS_PER_PARSE) + " bookings. "
            "If you cannot identify any booking, return an empty list. "
            "type must be one of: flight, hotel, car, restaurant, activity, transport, other. "
            "Datetimes must be ISO 8601 strings (e.g. '2026-08-17T14:30:00'). "
            "Currency must be a 3-letter ISO 4217 code."
        )

        response = client.messages.parse(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
            output_format=BatchedParsedBookings,
        )
        parsed = response.parsed_output  # BatchedParsedBookings instance

        results: List[ParsedBooking] = []
        for b in parsed.bookings:
            results.append(
                ParsedBooking(
                    type=b.type if b.type in BOOKING_TYPE_CODES else "other",
                    title=b.title,
                    vendor=b.vendor,
                    confirmation_number=b.confirmation_number,
                    start_datetime=_safe_iso(b.start_datetime),
                    end_datetime=_safe_iso(b.end_datetime),
                    location=b.location,
                    cost=b.cost,
                    currency=b.currency,
                    url=b.url,
                    notes=b.notes,
                    confidence=1.0,
                    source="llm",
                )
            )
        return results
    except Exception as e:
        logger.warning("parse_with_llm failed: %s", e)
        return []


# ─────────────────────────  parse_booking_email  ──────────────────────────


def parse_booking_email(text: str) -> ParseResult:
    """Public entry point. Tries rules first; falls back to LLM only if
    all three LLM gates pass. Returns ParseResult with bookings list +
    source attribution + a user-facing notes string when empty."""
    # Truncate over-sized pastes on a UTF-8 byte boundary. `errors="ignore"`
    # drops a trailing partial codepoint cleanly.
    encoded = text.encode("utf-8")
    original_len = len(encoded)
    if original_len > MAX_PASTE_BYTES:
        logger.info(
            "paste body truncated from %d to %d bytes", original_len, MAX_PASTE_BYTES
        )
        text = encoded[:MAX_PASTE_BYTES].decode("utf-8", errors="ignore")

    rules_results = parse_rules(text)
    if rules_results:
        return ParseResult(bookings=rules_results, source="rules")

    if _llm_gates_pass():
        llm_results = parse_with_llm(text)
        if llm_results:
            return ParseResult(bookings=llm_results, source="llm")

    return ParseResult(
        bookings=[],
        source="none",
        notes="Couldn't extract anything from that email — try typing it in.",
    )

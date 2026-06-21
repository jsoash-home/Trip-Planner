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


_CONFIRMATION_ANCHORS = (
    r"confirmation\s*(?:number|code|#)?\s*:",
    r"booking\s*(?:reference|ref|code|number)\s*:",
    r"record\s*locator\s*:",
    r"reservation\s*(?:number|code)\s*:",
)
_RE_CONFIRMATION_ANCHOR = re.compile(
    r"(?:" + "|".join(_CONFIRMATION_ANCHORS) + r")\s*([A-Za-z0-9]{5,15})",
    re.IGNORECASE,
)

# Fallback: standalone 6–10 alphanumeric token with at least one letter AND digit.
_RE_CONFIRMATION_FALLBACK = re.compile(r"\b([A-Za-z0-9]{6,10})\b")


def extract_confirmation_number(text: str) -> Optional[str]:
    """Find a booking confirmation number.

    Prefers an anchor phrase ("Confirmation #:", "Booking reference:",
    "Record locator:", "Reservation number:"). Falls back to any 6–10
    char alphanumeric token containing at least one letter AND one digit
    (so plain words and pure numbers don't match).
    """
    m = _RE_CONFIRMATION_ANCHOR.search(text)
    if m:
        return m.group(1)

    for m in _RE_CONFIRMATION_FALLBACK.finditer(text):
        token = m.group(1)
        if any(c.isalpha() for c in token) and any(c.isdigit() for c in token):
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


def _extract_one_segment(
    full_text: str,
    pair_start: int,
    pair_end: int,
    origin: str,
    dest: str,
    email_vendor: Optional[str],
    email_conf: Optional[str],
    email_cost: Optional[Tuple[float, str]],
) -> ParsedBooking:
    """Build one ParsedBooking from a single IATA-pair match.

    Looks for vendor/flight-no/dates inside a ±SEGMENT_RADIUS window around
    the pair. Falls back to email-level vendor/conf/cost when nothing local.
    """
    seg_start = max(0, pair_start - _SEGMENT_RADIUS)
    seg_end = min(len(full_text), pair_end + _SEGMENT_RADIUS)
    segment = full_text[seg_start:seg_end]

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

    segments: List[ParsedBooking] = [
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
    ]

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


# Matches a clock time like "3:00 PM" or "15:30" — used to tell apart
# "date-only" from "datetime with a midnight time".
_RE_ANY_CLOCK_TIME = re.compile(
    r"\b\d{1,2}:\d{2}(?:\s*(?:AM|PM))?\b", re.IGNORECASE
)


def _line_has_time(line: str) -> bool:
    return bool(_RE_ANY_CLOCK_TIME.search(line))


def _datetime_with_default_hour(line: str, default_hour: int) -> Optional[datetime]:
    """Parse the first date in `line`; if no time was provided, snap to default_hour."""
    dates = extract_dates(line)
    if not dates:
        return None
    dt = dates[0]
    # extract_dates returns hour=0, minute=0 for date-only matches.
    if dt.hour == 0 and dt.minute == 0 and not _line_has_time(line):
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

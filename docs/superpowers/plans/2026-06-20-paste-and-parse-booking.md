# Paste-and-Parse Booking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user paste a booking confirmation email and either pre-fill the new-booking form (1 result) or open a multi-booking review screen (2+ results), with a hybrid parser whose LLM fallback is built but gated off until an API key is added.

**Architecture:** New pure module `src/booking_parser.py` with `ParsedBooking` dataclass, 7 universal-by-type extractors, a strategy-pattern orchestrator, and a 3-gated LLM fallback. Two new Flask routes drive the flow; existing `parse_booking_form()` + `auto_itinerary_items_for_booking()` are reused unchanged.

**Tech Stack:** Python 3.9, Flask, SQLAlchemy, Jinja2, pytest, anthropic SDK (lazy-imported only when all 3 LLM gates pass).

**Spec:** [docs/superpowers/specs/2026-06-20-paste-and-parse-booking-design.md](../specs/2026-06-20-paste-and-parse-booking-design.md)

---

## TDD loop is implicit

Every task that introduces a function follows:
1. Write the failing test(s) for the public surface defined below.
2. Run pytest, confirm RED.
3. Implement minimally to GREEN.
4. Commit (one commit per task — `feat:` for new code, `test:` if test-only).

The skill loop is in your subagent prompt; this plan only specifies *what* each task produces. Don't pad with the procedural ritual.

---

## File map

### New files
| Path | Responsibility |
|---|---|
| `src/booking_parser.py` | `ParsedBooking` / `ParseResult` dataclasses, 7 extractors, orchestrator, gated LLM fallback. ~500-700 lines. |
| `templates/bookings_paste_review.html` | Multi-booking review screen with N checkbox+form cards. |
| `tests/test_booking_parser.py` | Per-extractor tests + orchestrator + LLM gating tests. |
| `tests/fixtures/booking_emails/<type>/` | One subdir per type (flight/, hotel/, car/, restaurant/, activity/, transport/, other/). ≥3 `.txt` samples per type. Plus `_negative/` with should-not-match samples. |

### Modified files
| Path | Change |
|---|---|
| `app.py` | Two new routes: `POST /trips/<id>/bookings/parse` and `POST /trips/<id>/bookings/paste-confirm`. |
| `templates/booking_form.html` | Add collapsible `<details class="paste-from-email">` section above existing form; thread `prefilled` Jinja context into each `value="..."`. |
| `tests/test_routes.py` | New tests for the 2 routes (access control, 0/1/N branches, bulk-create). |

### Unchanged
- `models.py`, `src/booking_helpers.py`, auto-itinerary-link pipeline, CSS files, JS files.

---

## Constants & contracts (reference throughout plan)

```python
# src/booking_parser.py
MIN_CONFIDENCE = 0.4          # extractor results below this are dropped
MAX_BOOKINGS_PER_PARSE = 5    # rules + LLM both cap; review screen sanity
MAX_PASTE_BYTES = 50_000      # truncate longer emails before parsing
LLM_MODEL = "claude-opus-4-8" # per claude-api skill default; user can override later
LLM_MAX_TOKENS = 4096
LLM_GATE_ENV_FLAG = "PASTE_PARSER_LLM_ENABLED"  # must be "1" to enable
```

`BOOKING_TYPE_CODES` is imported from `src/booking_helpers.py` (already exists; do NOT redefine).

### `ParsedBooking` dataclass (single source of truth)

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal

@dataclass
class ParsedBooking:
    type: str                                      # one of BOOKING_TYPE_CODES
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
    bookings: list
    source: Literal["rules", "llm", "none"]
    notes: str = ""
```

### Per-extractor contract

```python
def extract_<type>(text: str) -> Optional[ParsedBooking] | list[ParsedBooking] | None
```

- Returns `None` if no match.
- Returns a single `ParsedBooking` for one-segment emails.
- Returns `list[ParsedBooking]` when the extractor itself detects multiple segments (e.g. flight extractor finds two IATA-pair sequences).
- Sets `confidence` and `source="rules"` on every returned booking.

### Public entry point

```python
def parse_booking_email(text: str) -> ParseResult
```

---

## Task 1: ParsedBooking dataclass + shared helpers

**Files:**
- Create: `src/booking_parser.py` (dataclasses + helpers only — extractors come later)
- Test: `tests/test_booking_parser.py` (new file)

**Public surface:**
- `ParsedBooking`, `ParseResult` dataclasses (exact fields above).
- `extract_dates(text: str) -> list[datetime]` — finds ISO-ish datetimes, "Mon, Aug 17 2026" forms, "08/17/2026 3:45 PM". Returns naive datetimes (no timezone — matches Booking model convention).
- `extract_money(text: str) -> Optional[tuple[float, str]]` — returns `(amount, "USD")` from `$123.45` / `USD 123.45` / `€45,00` etc. Supports the 30 currencies already in `src/currency.SUPPORTED_CURRENCIES` (import that list).
- `extract_confirmation_number(text: str) -> Optional[str]` — looks for `Confirmation #:` / `Booking reference:` / `Record locator:` keyword anchors, then captures the alphanumeric token after. Falls back to standalone 6–10 char alphanumeric tokens if anchor not present.
- `extract_url(text: str) -> Optional[str]` — first `https?://` URL.
- `score_confidence(parsed: ParsedBooking) -> float` — fraction of expected-for-type fields populated. Per-type field weights live in a `_REQUIRED_FIELDS_PER_TYPE` dict. Returns 0.0 to 1.0.

**Test list (one test per item):**
- `test_extract_dates_finds_iso`
- `test_extract_dates_finds_human_format`
- `test_extract_dates_finds_us_slash_format`
- `test_extract_dates_returns_empty_on_no_match`
- `test_extract_money_usd_dollar_sign`
- `test_extract_money_iso_prefix` (`USD 100`, `EUR 45.50`)
- `test_extract_money_euro_comma_decimal` (`€45,00`)
- `test_extract_money_returns_none_on_no_match`
- `test_extract_confirmation_number_with_anchor`
- `test_extract_confirmation_number_no_anchor_fallback`
- `test_extract_url_first_https`
- `test_extract_url_returns_none_if_absent`
- `test_score_confidence_full_match_is_1`
- `test_score_confidence_empty_is_0`
- `test_score_confidence_partial_flight` (e.g. type + title + dates but no cost)

**Notes:**
- These helpers are pure; no fixtures needed beyond inline strings in tests.
- Use Python's stdlib `re` and `datetime`. No new dependencies.

**Commit:** `feat(booking-parser): dataclasses + shared extraction helpers`

---

## Task 2: extract_flight

**Files:**
- Modify: `src/booking_parser.py` (add `extract_flight`)
- Test: `tests/test_booking_parser.py` (extend)
- Create: `tests/fixtures/booking_emails/flight/*.txt` (≥3 real-shape samples) + `flight/_negative/*.txt` (≥2)

**Public surface:**
- `extract_flight(text: str) -> Optional[ParsedBooking] | list[ParsedBooking]`

**Detection rules:**
- Requires at least one **IATA airport-code pair** (e.g. `SFO → LHR`, `SFO-LHR`, `SFO to LHR`). Anchors the type.
- Captures airline name from `Operated by` / `Airline:` anchor or from the start of the email subject if recognizable.
- Captures flight number via regex `\b[A-Z]{2}\s?\d{1,4}\b` near the IATA pair.
- Dates: dep date from "Depart:" / "Departing:" anchor; arr date from "Arrive:" anchor; falls back to first 1–2 dates from `extract_dates`.
- `title`: `"{vendor} {flight_number}: {origin} → {destination}"` if all known, else best subset.
- `location`: origin IATA (used as the trip's departure city for the auto-itinerary "Depart" item).
- `start_datetime`: departure; `end_datetime`: arrival.
- **Multi-segment:** detect by ≥2 IATA pairs with distinct dates. Return `list[ParsedBooking]` ordered by `start_datetime`.

**Test list:**
- `test_flight_single_segment_united_style`
- `test_flight_single_segment_with_iata_dash_form`
- `test_flight_multi_segment_returns_list` (round-trip)
- `test_flight_extracts_confirmation_number`
- `test_flight_extracts_cost_and_currency`
- `test_flight_missing_arrival_time_still_returns_booking` (start_datetime set, end_datetime None — that's OK; auto-itinerary handles it)
- `test_flight_returns_none_for_hotel_confirmation` (negative — `_negative/marriott.txt`)
- `test_flight_returns_none_for_restaurant_confirmation` (negative — `_negative/opentable.txt`)
- `test_flight_confidence_high_when_all_fields_present`
- `test_flight_confidence_low_when_only_iata_pair`

**Fixture sources:** synthetic examples mimicking common patterns (don't use real PII). One generic United-style, one with Lufthansa-style multi-leg layout, one with British Airways e-ticket layout.

**Commit:** `feat(booking-parser): flight extractor + fixtures`

---

## Task 3: extract_hotel

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`
- Create: `tests/fixtures/booking_emails/hotel/*.txt` + `hotel/_negative/*.txt`

**Public surface:**
- `extract_hotel(text: str) -> Optional[ParsedBooking]`

**Detection rules:**
- Requires anchors `Check-in` / `Check in` / `Arrival` AND `Check-out` / `Check out` / `Departure` OR the phrases "your stay at" / "reservation at".
- `vendor`: hotel name from "stay at <X>", "reservation at <X>", or capitalized phrase after the anchor.
- `start_datetime`: check-in date (time defaults to 15:00 if not specified).
- `end_datetime`: check-out date (time defaults to 11:00 if not specified).
- `location`: hotel address from "Address:" anchor or line after vendor.
- `cost`: total stay cost (sum of nightly rates if itemized; otherwise the "Total" line).
- `title`: `vendor` (e.g. `"Marriott Times Square"`).

**Test list:**
- `test_hotel_marriott_style`
- `test_hotel_booking_com_style`
- `test_hotel_airbnb_style`
- `test_hotel_extracts_nightly_total`
- `test_hotel_check_in_time_defaults_3pm`
- `test_hotel_returns_none_for_flight_confirmation` (negative)
- `test_hotel_returns_none_for_car_rental` (negative)

**Commit:** `feat(booking-parser): hotel extractor + fixtures`

---

## Task 4: extract_car

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`
- Create: `tests/fixtures/booking_emails/car/*.txt` + `car/_negative/*.txt`

**Public surface:**
- `extract_car(text: str) -> Optional[ParsedBooking]`

**Detection rules:**
- Anchors: `Pick-up` / `Pickup` / `Collect` AND `Drop-off` / `Return`.
- `vendor`: rental company (Hertz, Enterprise, Avis, Sixt, Budget, Alamo, National — match against a small list, fall back to capitalized phrase after the anchor).
- `start_datetime`: pickup; `end_datetime`: return.
- `location`: pickup location.
- `title`: `"{vendor} car rental"`.

**Test list:**
- `test_car_hertz_style`
- `test_car_enterprise_style`
- `test_car_extracts_pickup_dropoff_times`
- `test_car_returns_none_for_taxi_receipt` (negative)

**Commit:** `feat(booking-parser): car extractor + fixtures`

---

## Task 5: extract_restaurant

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`
- Create: `tests/fixtures/booking_emails/restaurant/*.txt` + `restaurant/_negative/*.txt`

**Public surface:**
- `extract_restaurant(text: str) -> Optional[ParsedBooking]`

**Detection rules:**
- Anchors: `Reservation` / `Table for` / `Booking confirmed`.
- Strong negative anchor: if `IATA` pair OR `Check-in` present → return None (lets flight/hotel win).
- `vendor`: restaurant name (often in subject line "Your reservation at <X>").
- `start_datetime`: reservation datetime (single point in time — no end_datetime).
- `location`: restaurant address.
- `notes`: party size (`"Party of N"`).
- `title`: `"Dinner at {vendor}"` or `"Reservation at {vendor}"`.

**Test list:**
- `test_restaurant_opentable_style`
- `test_restaurant_resy_style`
- `test_restaurant_captures_party_size_in_notes`
- `test_restaurant_returns_none_for_hotel` (negative)

**Commit:** `feat(booking-parser): restaurant extractor + fixtures`

---

## Task 6: extract_activity

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`
- Create: `tests/fixtures/booking_emails/activity/*.txt` + `activity/_negative/*.txt`

**Public surface:**
- `extract_activity(text: str) -> Optional[ParsedBooking]`

**Detection rules:**
- Anchors: `Ticket` / `Tour` / `Admission` / `Event` / `Tickets for`.
- Strong negative: IATA pair, `Check-in`, or "table for" → return None.
- `vendor`: tour/event provider (e.g. Viator, GetYourGuide, Eventbrite, museum name).
- `start_datetime`: event datetime.
- `end_datetime`: only if explicitly listed (most events are single-point).
- `location`: venue address.
- `title`: event name from subject line.

**Test list:**
- `test_activity_viator_tour`
- `test_activity_eventbrite_concert`
- `test_activity_museum_tickets`
- `test_activity_returns_none_for_flight` (negative)

**Commit:** `feat(booking-parser): activity extractor + fixtures`

---

## Task 7: extract_transport

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`
- Create: `tests/fixtures/booking_emails/transport/*.txt` + `transport/_negative/*.txt`

**Public surface:**
- `extract_transport(text: str) -> Optional[ParsedBooking]`

**Detection rules:**
- Anchors: `Train` / `Rail` / `Ferry` / `Bus` / `Coach` / station codes (e.g. `London St Pancras → Paris Gare du Nord`).
- Strong negative: IATA airport-code pair → return None (let flight extractor handle).
- `vendor`: carrier (Amtrak, Eurostar, Greyhound, FlixBus, DB, etc. — small list; fallback to capitalized phrase).
- `start_datetime`: departure; `end_datetime`: arrival.
- `location`: origin station.
- `title`: `"{vendor}: {origin} → {destination}"`.

**Test list:**
- `test_transport_amtrak_style`
- `test_transport_eurostar_style`
- `test_transport_ferry_style`
- `test_transport_returns_none_for_flight_with_iata` (negative)

**Commit:** `feat(booking-parser): transport extractor + fixtures`

---

## Task 8: extract_other (weak fallback)

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`
- Create: `tests/fixtures/booking_emails/other/*.txt` (≥2 generic confirmations)

**Public surface:**
- `extract_other(text: str) -> Optional[ParsedBooking]`

**Detection rules:**
- The catch-all. Runs no negative anchors.
- `title`: first line of email (typically the subject when pasted with headers, or the first heading).
- `start_datetime`: first date from `extract_dates` (if any).
- `confidence`: caps at 0.5 by construction (this is the weakest extractor and should rarely beat a real one).
- Returns `None` if no dates AND no money AND no confirmation number found (truly empty).

**Test list:**
- `test_other_generic_confirmation_captures_title_and_date`
- `test_other_returns_none_for_truly_empty_text`
- `test_other_confidence_capped_at_half`

**Commit:** `feat(booking-parser): other (generic) extractor`

---

## Task 9: parse_rules orchestrator

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`

**Public surface:**
- `parse_rules(text: str) -> list[ParsedBooking]`

**Behaviour:**
- Runs all 7 extractors in order: flight, hotel, car, restaurant, activity, transport, other.
- Flattens any `list[ParsedBooking]` returns into the combined result.
- Drops any result with `confidence < MIN_CONFIDENCE`.
- Truncates to top `MAX_BOOKINGS_PER_PARSE` by confidence descending.
- Returns the list (may be empty).

**Test list:**
- `test_parse_rules_one_flight_returns_one_booking`
- `test_parse_rules_round_trip_returns_two_bookings`
- `test_parse_rules_garbage_text_returns_empty`
- `test_parse_rules_drops_low_confidence_results`
- `test_parse_rules_caps_at_max_bookings`
- `test_parse_rules_flight_and_other_both_match_returns_only_flight` (confidence ordering — flight should beat the weaker `other` fallback)

**Commit:** `feat(booking-parser): orchestrator (parse_rules)`

---

## Task 10: LLM gating + parse_with_llm (mocked)

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`

**Public surface:**
```python
def _llm_gates_pass() -> bool:
    """True iff ANTHROPIC_API_KEY set AND PASTE_PARSER_LLM_ENABLED='1'
    AND `anthropic` SDK is importable. Lazy import — never raises."""

def parse_with_llm(text: str) -> list[ParsedBooking]:
    """Call Claude with a structured-output schema, parse to ParsedBookings.
    Returns [] on any API/network/schema error. Caller is responsible for
    checking _llm_gates_pass() first (this fn re-checks defensively)."""
```

**Implementation notes:**
- Lazy import: `from anthropic import Anthropic` inside the function body, wrapped in `try/except ImportError`.
- Use the Pydantic `BatchedParsedBookings` schema via `client.messages.parse()` — see [claude-api skill: Structured Outputs](https://anthropic.com).
  - Inside the parser module, define a `BatchedParsedBookingsSchema(BaseModel)` with `bookings: list[ParsedBookingSchema]` (separate from the dataclass — Pydantic, not dataclasses).
  - Convert each Pydantic instance back to the `ParsedBooking` dataclass with `source="llm"`, `confidence=1.0`.
- Model: `LLM_MODEL` constant (`"claude-opus-4-8"`).
- System prompt: explains task + lists the 7 type codes + asks for ≤5 bookings + asks to return [] if nothing found.
- User prompt: the email text, verbatim.
- On `ImportError`, `anthropic.APIError`, `pydantic.ValidationError`, or any exception: log at WARNING with `_request_id` if available, return `[]`.

**Test list:**
- `test_llm_gates_pass_returns_false_when_key_missing` (monkeypatch env)
- `test_llm_gates_pass_returns_false_when_flag_unset`
- `test_llm_gates_pass_returns_false_when_sdk_missing` (monkeypatch the import)
- `test_llm_gates_pass_returns_true_when_all_three_present`
- `test_parse_with_llm_returns_empty_when_gates_off`
- `test_parse_with_llm_returns_bookings_when_sdk_mocked` (use `unittest.mock` to stub `client.messages.parse`)
- `test_parse_with_llm_returns_empty_on_api_error` (mocked client raises `APIError`)
- `test_parse_with_llm_returns_empty_on_validation_error`

**Commit:** `feat(booking-parser): gated LLM fallback (parse_with_llm)`

---

## Task 11: parse_booking_email (public entry point)

**Files:**
- Modify: `src/booking_parser.py`
- Test: `tests/test_booking_parser.py`

**Public surface:**
- `parse_booking_email(text: str) -> ParseResult`

**Behaviour:**
1. If `len(text.encode("utf-8")) > MAX_PASTE_BYTES`: truncate to that size, log at INFO.
2. `results = parse_rules(text)`. If non-empty → return `ParseResult(bookings=results, source="rules")`.
3. Else if `_llm_gates_pass()`: `results = parse_with_llm(text)`. If non-empty → return `ParseResult(bookings=results, source="llm")`.
4. Else return `ParseResult(bookings=[], source="none", notes="Couldn't extract anything from that email — try typing it in.")`.

**Test list:**
- `test_parse_booking_email_rules_path`
- `test_parse_booking_email_llm_path` (LLM gates patched on, rules empty, LLM mocked)
- `test_parse_booking_email_none_path` (both empty)
- `test_parse_booking_email_truncates_huge_input`
- `test_parse_booking_email_empty_string_returns_none_source`

**Commit:** `feat(booking-parser): public parse_booking_email entry point`

---

## Task 12: booking_form.html — collapsible paste section + pre-fill

**Files:**
- Modify: `templates/booking_form.html`

**What to add:**
- A `<details class="paste-from-email">` block above the existing form fields (inside `{% block content %}` near the top of the form area):
  ```html
  <details class="paste-from-email"
           {% if prefilled and not prefilled %}open{% endif %}
           {% if paste_failed %}open{% endif %}>
    <summary>📨 Paste from email</summary>
    <form method="post"
          action="{{ url_for('booking_paste', trip_id=trip.id) }}"
          class="vp-paste-form">
      <textarea name="paste_body"
                rows="10"
                placeholder="Paste your confirmation email here…"
                required>{{ paste_body or '' }}</textarea>
      <button type="submit" class="btn btn-secondary">Parse email</button>
    </form>
    {% if paste_failed %}
    <div class="alert alert-warning mt-2">{{ paste_failed_message }}</div>
    {% endif %}
  </details>
  ```
- Wire each existing `<input>` / `<select>` to read from a `prefilled` dict. Examples:
  - `<input id="b-title" name="title" value="{{ prefilled.title if prefilled else '' }}" required>`
  - `<select name="type">{% for code, label, _ in BOOKING_TYPES %}<option value="{{ code }}" {% if prefilled and prefilled.type == code %}selected{% elif booking and booking.type == code %}selected{% endif %}>{{ label }}</option>{% endfor %}</select>`
  - Repeat for all 11 fields: type, title, vendor, confirmation_number, start_datetime, end_datetime, location, cost, currency, url, notes.
- For datetime fields: format via Jinja `{{ prefilled.start_datetime.strftime('%Y-%m-%dT%H:%M') if prefilled and prefilled.start_datetime else '' }}` (HTML `datetime-local` expects this).

**CSS:**
- One small block in `static/css/app.css`:
  ```css
  .paste-from-email { margin-bottom: 1rem; }
  .paste-from-email summary {
    cursor: pointer;
    padding: 0.5rem 0.75rem;
    background: var(--vp-surface-2);
    border-radius: 0.375rem;
  }
  .paste-from-email .vp-paste-form { margin-top: 0.75rem; }
  .paste-from-email textarea {
    width: 100%;
    font-family: ui-monospace, 'SF Mono', Menlo, monospace;
    font-size: 0.875rem;
  }
  ```

**Tests:** Template changes verified by Task 13's route tests (rendering check). No standalone template test needed.

**Commit:** `feat(ui): booking form — paste-from-email collapsible section`

---

## Task 13: POST /bookings/parse route

**Files:**
- Modify: `app.py` — add `booking_paste` view function.
- Modify: `tests/test_routes.py` — add tests.

**Public surface:**
- Route: `POST /trips/<int:trip_id>/bookings/parse`
- View function name: `booking_paste`
- URL name (`url_for`): `booking_paste`

**Implementation:**
```python
@app.route("/trips/<int:trip_id>/bookings/parse", methods=["POST"])
@login_required
def booking_paste(trip_id: int):
    trip = _trip_with_access_or_404(trip_id, role="editor")
    text = (request.form.get("paste_body") or "").strip()
    if not text:
        flash("Paste the email body first.", "warning")
        return redirect(url_for("booking_new", trip_id=trip_id))

    from src.booking_parser import parse_booking_email
    result = parse_booking_email(text)

    if not result.bookings:
        # Re-render the new-booking form, paste section open, body retained
        return render_template(
            "booking_form.html",
            trip=trip,
            booking=None,
            prefilled=None,
            paste_body=text,
            paste_failed=True,
            paste_failed_message=result.notes,
            BOOKING_TYPES=BOOKING_TYPES,
            SUPPORTED_CURRENCIES=SUPPORTED_CURRENCIES,
        )

    if len(result.bookings) == 1:
        return render_template(
            "booking_form.html",
            trip=trip,
            booking=None,
            prefilled=result.bookings[0],
            paste_body=None,
            paste_failed=False,
            BOOKING_TYPES=BOOKING_TYPES,
            SUPPORTED_CURRENCIES=SUPPORTED_CURRENCIES,
        )

    # 2+ bookings → review screen
    return render_template(
        "bookings_paste_review.html",
        trip=trip,
        bookings=result.bookings,
        BOOKING_TYPES=BOOKING_TYPES,
        SUPPORTED_CURRENCIES=SUPPORTED_CURRENCIES,
    )
```

**Test list (in `tests/test_routes.py`):**
- `test_booking_paste_403_for_viewer`
- `test_booking_paste_redirects_when_body_empty`
- `test_booking_paste_renders_form_with_no_matches_section_open` (assert HTML contains `<details ... open>` and the original text retained in textarea)
- `test_booking_paste_prefills_form_for_single_match` (patch `parse_booking_email` to return 1 ParsedBooking; assert rendered HTML has the values in `value="..."` attrs)
- `test_booking_paste_renders_review_screen_for_multi_match` (patch to return 2; assert rendered HTML includes review template marker)

**Commit:** `feat(routes): POST /bookings/parse — parse email + dispatch`

---

## Task 14: bookings_paste_review.html template

**Files:**
- Create: `templates/bookings_paste_review.html`

**Template structure (skeleton — full content lives in the file itself):**

```html
{% extends "base.html" %}
{% block content %}
<div class="container my-4">
  <h2>Parser found {{ bookings|length }} bookings</h2>
  <p class="text-muted">Review and edit each one before saving.</p>

  <form method="post"
        action="{{ url_for('booking_paste_confirm', trip_id=trip.id) }}"
        class="vp-paste-review">

    {% for booking in bookings %}
    <div class="card mb-3 vp-paste-card">
      <div class="card-body">
        <div class="form-check">
          <input class="form-check-input" type="checkbox"
                 name="bookings[{{ loop.index0 }}][_selected]"
                 id="bk-{{ loop.index0 }}-selected"
                 checked>
          <label class="form-check-label" for="bk-{{ loop.index0 }}-selected">
            Include this booking
          </label>
        </div>

        <!-- Field grid: type, title, vendor, confirmation_number,
             start_datetime, end_datetime, location, cost, currency,
             url, notes — all with name="bookings[{{ loop.index0 }}][<field>]"
             and value="{{ booking.<field> or '' }}" -->
        <!-- Same input markup pattern as booking_form.html, just with the
             indexed name attribute. Type select uses BOOKING_TYPES list. -->
      </div>
    </div>
    {% endfor %}

    <button type="submit" class="btn btn-primary">
      Save selected ({{ bookings|length }})
    </button>
    <a href="{{ url_for('booking_new', trip_id=trip.id) }}" class="btn btn-link">
      Cancel
    </a>
  </form>
</div>
{% endblock %}
```

**Inline-field markup pattern (one card):** see `booking_form.html` for the standard input set — same fields, same Bootstrap classes, only the `name` attribute changes to the indexed form.

**Tests:** Verified by Task 15's route tests (form submission round-trip).

**Commit:** `feat(ui): paste review template (multi-booking)`

---

## Task 15: POST /bookings/paste-confirm route

**Files:**
- Modify: `app.py` — add `booking_paste_confirm` view function.
- Modify: `tests/test_routes.py` — add tests.

**Public surface:**
- Route: `POST /trips/<int:trip_id>/bookings/paste-confirm`
- View function name: `booking_paste_confirm`
- URL name: `booking_paste_confirm`

**Implementation:**
```python
@app.route("/trips/<int:trip_id>/bookings/paste-confirm", methods=["POST"])
@login_required
def booking_paste_confirm(trip_id: int):
    trip = _trip_with_access_or_404(trip_id, role="editor")

    # Walk indexed bookings[N][...] keys; collect indices where _selected is "on"
    indices = sorted({
        int(key.split("[")[1].split("]")[0])
        for key in request.form
        if key.startswith("bookings[") and key.endswith("][_selected]")
        and request.form.get(key) == "on"
    })

    if not indices:
        flash("Select at least one booking to save.", "warning")
        # Re-render review with the form state — easiest path: redirect to /new
        return redirect(url_for("booking_new", trip_id=trip_id))

    created = 0
    for i in indices:
        # Build a fake-form dict matching parse_booking_form's expectations
        fake_form = {
            "type": request.form.get(f"bookings[{i}][type]", "other"),
            "title": request.form.get(f"bookings[{i}][title]", ""),
            "vendor": request.form.get(f"bookings[{i}][vendor]", ""),
            "confirmation_number": request.form.get(f"bookings[{i}][confirmation_number]", ""),
            "start_datetime": request.form.get(f"bookings[{i}][start_datetime]", ""),
            "end_datetime": request.form.get(f"bookings[{i}][end_datetime]", ""),
            "location": request.form.get(f"bookings[{i}][location]", ""),
            "cost": request.form.get(f"bookings[{i}][cost]", ""),
            "currency": request.form.get(f"bookings[{i}][currency]", "USD"),
            "url": request.form.get(f"bookings[{i}][url]", ""),
            "notes": request.form.get(f"bookings[{i}][notes]", ""),
        }
        try:
            booking = parse_booking_form(fake_form, trip_id=trip_id)
        except ValueError as e:
            flash(f"Skipped booking {i + 1}: {e}", "warning")
            continue
        db.session.add(booking)
        db.session.flush()  # to get booking.id before auto-itinerary
        auto_items = auto_itinerary_items_for_booking(booking)
        for item_dict in auto_items:
            day_date = item_dict.get("day_date")
            if day_date and (day_date < trip.start_date or day_date > trip.end_date):
                continue
            db.session.add(ItineraryItem(trip_id=trip_id, **item_dict))
        created += 1

    db.session.commit()
    flash(f"Created {created} booking(s) from paste.", "success")
    return redirect(url_for("bookings_list", trip_id=trip_id))
```

**Note:** Verify `parse_booking_form`'s signature in [src/booking_helpers.py:62](src/booking_helpers.py:62) matches `(form_dict, trip_id)` before implementing. If it expects a `request.form`-like object, wrap `fake_form` with `werkzeug.datastructures.ImmutableMultiDict(fake_form)`. The implementer should confirm during Task 15 by reading the existing function. **The auto-itinerary-date-window filter above (`day_date < trip.start_date or day_date > trip.end_date`) mirrors the rule in the existing single-booking `booking_new` route — find it and copy verbatim rather than rewriting.**

**Test list:**
- `test_booking_paste_confirm_403_for_viewer`
- `test_booking_paste_confirm_redirects_when_no_selections`
- `test_booking_paste_confirm_creates_one_when_one_selected` (POST with `bookings[0][_selected]=on` + all fields; assert 1 Booking row exists for the trip)
- `test_booking_paste_confirm_creates_multiple` (2 selections)
- `test_booking_paste_confirm_auto_itinerary_links_fire` (assert ItineraryItem rows with matching `linked_booking_id`)
- `test_booking_paste_confirm_skips_invalid_card_but_saves_others` (one card has bad date format; assert other still created + flash includes skip message)

**Commit:** `feat(routes): POST /bookings/paste-confirm — bulk-create from review`

---

## Self-review checklist (run before opening for execution)

- [ ] Every spec section maps to a task (Architecture → Tasks 1–11; UI flow → Tasks 12, 14; Routes → Tasks 13, 15; LLM gating → Task 10; Multi-booking → Tasks 2, 9; Error handling → Tasks 11, 13, 15).
- [ ] No placeholders (`TBD`, `TODO`, `similar to above`, "fill in details").
- [ ] Type consistency: `ParsedBooking` field names identical across Tasks 1, 9, 10, 11, 13, 15. `parse_booking_email` / `parse_rules` / `parse_with_llm` / `_llm_gates_pass` named consistently.
- [ ] Route names (`booking_paste`, `booking_paste_confirm`) consistent between routes (Tasks 13, 15) and templates (Tasks 12, 14).
- [ ] All 15 tasks under the 17-task cap per the project's CLAUDE.md.
- [ ] No frontend task ships without browser verification step (rolled into Tasks 12, 13, 14, 15 via the project's "frontend verification mandatory" rule from CLAUDE.md — the implementer must hit the page in the browser before claiming done; `pytest` alone doesn't satisfy this for the UI tasks).

---

## Open implementation-time decisions

These are deliberate plan-time deferrals; resolve when you get to the task:

1. **`anthropic` in `requirements.txt`?** Default: leave it out. Lazy import inside `parse_with_llm` already handles the absence. Adding it now ships ~3 MB of dead dependency. Revisit when the user enables the LLM gate.
2. **Currency formatting in `extract_money`:** the prefix-vs-postfix and comma-decimal patterns. Defer to Task 1's test list — implementer adds whatever cases come up.
3. **Per-extractor confidence weights:** start with equal weights (1 / number-of-required-fields). Tune in Task 9 if a single extractor consistently wins when it shouldn't (e.g. `other` outranking `flight` due to denominator quirks).

---

## Out of scope (do not bloat the plan with these)

- LLM path on by default (gated; only flips on when user sets env vars)
- D1 email-in infrastructure (separate parked item)
- Image/PDF parsing
- Per-provider templates (universal-by-type only)
- "Remember this provider" learning
- Async/background parse

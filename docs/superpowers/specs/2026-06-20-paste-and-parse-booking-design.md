# Paste-and-Parse Booking — Design Spec

> **Status:** Approved through brainstorming. Implementation plan to follow
> at `docs/superpowers/plans/2026-06-20-paste-and-parse-booking.md`.
>
> **Date:** 2026-06-20
> **Phase:** 4 (post-Phase-3)
> **Source:** Parked item D2 in [docs/PHASE_3_ROADMAP.md](../../PHASE_3_ROADMAP.md)

## Summary

Add a "Paste from email" surface to the new-booking flow. The user pastes a
confirmation email's body into a textarea; the server extracts whatever
booking fields it can (type, vendor, dates, location, cost, confirmation
number, …) and either pre-fills the standard booking form (single result)
or opens a multi-booking review screen (round-trip flight, multi-segment).

The user saves as they would for a typed-out booking. Auto-itinerary-link
pipeline is unchanged — each saved booking still gets its linked
ItineraryItems via the existing `auto_itinerary_items_for_booking()`.

## Why

- Typing a booking from an email is the most tedious part of the app.
- Most of the friction is mechanical transcription (flight numbers,
  ISO datetimes, currency codes) — exactly what rule-based extractors
  and LLMs are good at.
- The recently-shipped trip-guide skill demonstrates the project is
  ready for AI-assisted features when the user is.

## Scope

### In scope (v1)
- All 7 booking types: flight, hotel, car, restaurant, activity,
  transport, other.
- Universal-by-type rule-based extractors (one per type) running locally
  with no external dependencies.
- LLM fallback **built but gated off** behind three env-var gates until
  the user adds an Anthropic API key.
- Multi-booking detection (round-trip flights, multi-leg itineraries).
- Single-result path: pre-fill standard booking form.
- Multi-result path: new review screen with checkboxes + inline edits,
  bulk-create on submit.
- Auto-itinerary-link still fires per saved booking (no changes).

### Out of scope (v1)
- LLM path active by default (built but gated).
- Per-provider rule templates (United, Marriott, etc.) — universal-by-type
  is good enough and degrades gracefully.
- Forwarded-email infrastructure (that's D1 — stays parked).
- Image / PDF attachments — text body only.
- Background / async parsing (synchronous in-request is fine).
- "Remember this provider" or per-user training data.
- Editing the parsed JSON directly. The review screen's inline form is
  the only edit surface in v1.

### Intentional limitations
- Bookings spanning multiple types in one email (e.g. flight + rental car
  bundle from a travel agency) are best-effort. The orchestrator picks
  the highest-confidence extractor per "segment" and may miss the
  second type. Workaround: paste the email twice, edit the type
  dropdown on the second go.

## File map

### New files
| Path | Purpose |
|---|---|
| `src/booking_parser.py` | Parser module: `ParsedBooking` dataclass, 7 universal-by-type extractors, orchestrator (`parse_booking_email`), and the gated LLM-fallback function. |
| `templates/bookings_paste_review.html` | Multi-booking review screen (rendered when parser returns ≥ 2 bookings). |
| `tests/test_booking_parser.py` | Unit tests for the parser: per-extractor fixtures, orchestrator branching, LLM gating. |
| `tests/fixtures/booking_emails/` | Real-world email samples per type, used as inputs in `test_booking_parser.py`. ≥ 3 samples per type. |

### Modified files
| Path | Change |
|---|---|
| `app.py` | Two new routes: `POST /trips/<id>/bookings/parse` (entry point — runs parser, dispatches to single-form pre-fill or review screen) and `POST /trips/<id>/bookings/paste-confirm` (bulk-create from the review screen). |
| `templates/booking_form.html` | Add collapsible `<details class="paste-from-email">` section above the form fields. Form auto-populates from `prefilled` dict passed by the parse route. |
| `requirements.txt` | (Optional, decided in plan) Add `anthropic` package, OR leave out and lazy-import inside the LLM-fallback function. Plan-time decision; the codebase compiles either way. |

### Unchanged
- `models.py` — no schema changes.
- `src/booking_helpers.py` — `parse_booking_form()` still does form-to-Booking;
  the new parser produces a separate `ParsedBooking` dataclass that's
  marshalled into form input.
- Auto-itinerary-link pipeline.

## Architecture

### Module: `src/booking_parser.py`

The parser is **pure** — no DB access, no Flask context, no network calls
(rules path). Easy to unit-test in isolation.

#### Public surface

```python
@dataclass
class ParsedBooking:
    """One booking extracted from an email body. Mirrors Booking model
    fields but is decoupled from SQLAlchemy."""
    type: str                              # one of BOOKING_TYPE_CODES
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
    # Bookkeeping (not persisted; used by orchestrator + review screen)
    confidence: float = 0.0                # 0–1, self-scored by extractor
    source: Literal["rules", "llm"] = "rules"


@dataclass
class ParseResult:
    bookings: List[ParsedBooking]
    source: Literal["rules", "llm", "none"]
    notes: str = ""                        # user-facing message when source="none"


def parse_booking_email(text: str) -> ParseResult:
    """Public entry point. Tries rules → LLM (if gated on) → empty."""
```

#### Internal structure

```
src/booking_parser.py
├─ Constants: MIN_CONFIDENCE = 0.4, LLM_MODEL = "claude-opus-4-8"
├─ Shared helpers
│   ├─ extract_dates(text) -> list[datetime]
│   ├─ extract_money(text) -> Optional[tuple[float, str]]   # (amount, currency)
│   ├─ extract_confirmation_number(text) -> Optional[str]
│   ├─ extract_url(text) -> Optional[str]
│   └─ score_confidence(parsed: ParsedBooking) -> float
├─ Per-type extractors (each Optional[ParsedBooking] | None)
│   ├─ extract_flight(text)        # IATA codes, flight numbers, dep/arr times
│   ├─ extract_hotel(text)         # check-in/out, hotel name, nights
│   ├─ extract_car(text)           # pickup/return, rental co, location
│   ├─ extract_restaurant(text)    # reservation time, party size, restaurant
│   ├─ extract_activity(text)      # event name, date, venue
│   ├─ extract_transport(text)     # train/bus/ferry — dep/arr, carrier
│   └─ extract_other(text)         # weak generic fallback (subject + dates)
├─ parse_rules(text) -> list[ParsedBooking]   # runs all 7, returns winners
├─ _llm_gates_pass() -> bool                   # checks env + import
├─ parse_with_llm(text) -> list[ParsedBooking] # lazy-imports anthropic
└─ parse_booking_email(text) -> ParseResult    # PUBLIC orchestrator
```

### Orchestration logic

```
parse_booking_email(text):
    1. results = parse_rules(text)
       # Each of 7 extractors runs; returns a list filtered to
       # those with confidence >= MIN_CONFIDENCE.

    2. If results is non-empty:
       return ParseResult(bookings=results, source="rules")

    3. If _llm_gates_pass():
       results = parse_with_llm(text)
       if results: return ParseResult(bookings=results, source="llm")

    4. return ParseResult(
           bookings=[],
           source="none",
           notes="Couldn't extract anything from that email — try typing it in."
       )
```

### Multi-booking detection

Each extractor returns either:
- `None` (didn't match)
- A single `ParsedBooking` (most common — one segment)
- A `list[ParsedBooking]` (when the extractor detects multiple segments
  in the same email — e.g. flight extractor finds two flight-number /
  IATA-pair sequences with different dates)

`parse_rules()` flattens the per-extractor results into one combined list,
filters by confidence, and returns. The LLM fallback returns `list` natively
(see schema below).

### LLM gating

Three independent gates, all must pass for the LLM path to run:

1. `os.environ.get("ANTHROPIC_API_KEY")` is set and non-empty.
2. `os.environ.get("PASTE_PARSER_LLM_ENABLED") == "1"`.
3. `anthropic` package can be imported (lazy import inside the function).

If any gate fails, `_llm_gates_pass()` returns False silently. The user sees
the same "couldn't parse" message as if no extractor matched. No degraded
behaviour; no log noise; no surprise API call.

Until the user enables the LLM path, the codebase still compiles and tests
still pass — `parse_with_llm` is dead code but well-formed and unit-tested
via a mocked client.

### LLM call shape (when enabled)

Uses the Anthropic Python SDK (`pip install anthropic`). Per the
`claude-api` skill defaults:

- **Model:** `claude-opus-4-8` (default — the skill is firm on this).
- **Structured output:** `client.messages.parse()` with a Pydantic
  `BatchedParsedBookings` schema that wraps `list[ParsedBookingSchema]`.
- **`max_tokens`:** 4096 (well under any timeout).
- **`thinking`:** omitted (this is a single-shot extraction, not
  reasoning-heavy).
- **Prompt structure:** system prompt explains the task + lists the 7
  booking types + lists the ParsedBooking fields and rules; user prompt
  is the pasted email body verbatim.

The Pydantic schema mirrors `ParsedBooking` minus the bookkeeping fields
(`confidence`, `source` are set server-side after parsing). On success,
the parsed bookings are wrapped in `ParsedBooking(..., source="llm",
confidence=1.0)` since the LLM either confidently extracted or refused.

LLM failure modes:
- API error / network error → logged at `WARNING`, returns `[]` so the
  user gets the "couldn't parse" message rather than a 500.
- Schema validation failure → handled by `messages.parse()` automatic retry;
  if retry fails, same fallback as above.

## UI flow

### Surface 1: collapsible paste section on the new-booking form

```
/trips/<id>/bookings/new
┌──────────────────────────────────────┐
│ + New Booking                        │
├──────────────────────────────────────┤
│ ▸ 📨 Paste from email                │  ← <details>, closed by default
│   [           textarea           ]   │  ← when open
│   [Parse email]                      │
├──────────────────────────────────────┤
│ Type:        [Flight        ▼]       │  ← standard form, possibly pre-filled
│ Title:       [_________________]     │
│ ...                                  │
│ [Save booking]                       │
└──────────────────────────────────────┘
```

- The `<details>` element keeps state purely in the DOM; no JS persistence.
- The `Parse email` button POSTs the textarea to
  `POST /trips/<id>/bookings/parse`.
- Form-field IDs and the existing hidden trip_id remain untouched; the
  parse route re-renders `booking_form.html` with a `prefilled: dict`
  context variable; Jinja `{{ prefilled.get('title', '') }}` populates
  each `<input value="...">`. (This app doesn't use CSRF tokens — Flask
  bare, no Flask-WTF.)

### Surface 2: multi-booking review screen

Rendered when parser returns ≥ 2 bookings. Stacks N "mini-forms",
each with a checkbox and the standard booking-form fields editable
inline.

```
/trips/<id>/bookings/paste-review        (rendered, not navigated)
┌─────────────────────────────────────────────┐
│ Parser found 2 bookings:                     │
├─────────────────────────────────────────────┤
│ ☑  Flight                                    │
│    [Title____] [Vendor____] [Conf #_______]  │
│    [Dep DT__]  [Arr DT___]                   │
│    [Location____]                            │
│    [Cost__][USD ▼]                           │
├─────────────────────────────────────────────┤
│ ☑  Flight                                    │
│    [Title____] [Vendor____] [Conf #_______]  │
│    [Dep DT__]  [Arr DT___]                   │
│    [Location____]                            │
│    [Cost__][USD ▼]                           │
├─────────────────────────────────────────────┤
│ [Save selected (2)]    [Cancel]              │
└─────────────────────────────────────────────┘
```

- Each card has index-based field names: `bookings[0][title]`,
  `bookings[0][type]`, … `bookings[N][title]`, etc. Standard Flask
  `request.form.getlist('bookings[0][title]')` style.
- `Cancel` goes back to `GET /trips/<id>/bookings/new`. No data persisted.
- `Save selected (N)` POSTs to `POST /trips/<id>/bookings/paste-confirm`,
  which iterates over checked indices, calls existing `parse_booking_form()`
  per card, and creates each Booking. Then runs
  `auto_itinerary_items_for_booking()` per booking (existing pipeline).

### Error state: no parser matched

- Re-render `/trips/<id>/bookings/new` with the paste section
  expanded (sticky open via `<details open>`), the pasted text still in
  the textarea (preserves user effort), and a Bootstrap alert above the
  form: "Couldn't extract anything from that email — try typing it in,
  or paste a different message."

## Data flow

```
User pastes text + clicks "Parse email"
  │
  ▼ POST /trips/<id>/bookings/parse  {paste_body: "…"}
  │
  Route: app.py / bookings_paste
  │   1. require_trip_access(trip_id, "editor")
  │   2. text = request.form["paste_body"]
  │   3. result = parse_booking_email(text)
  │
  ├─ if result.bookings == []:
  │     render booking_form.html with flash + paste-section open + text retained
  │
  ├─ if len(result.bookings) == 1:
  │     prefilled = asdict(result.bookings[0])
  │     render booking_form.html with prefilled context
  │
  └─ if len(result.bookings) >= 2:
        render bookings_paste_review.html with bookings list

User reviews + saves
  │
  ▼ POST /trips/<id>/bookings/paste-confirm  {bookings[N][...]}
  │
  Route: app.py / bookings_paste_confirm
  │   1. require_trip_access(trip_id, "editor")
  │   2. For each index where bookings[i][_selected] == "on":
  │      a. Build a fake-form dict for parse_booking_form()
  │      b. booking = parse_booking_form(fake_form, trip_id)
  │      c. db.session.add(booking) + flush to get ID
  │      d. items = auto_itinerary_items_for_booking(booking)
  │      e. db.session.add_all(items)
  │   3. db.session.commit()
  │   4. flash success + redirect to /trips/<id>/bookings
```

## Error / no-match handling

| Condition | Response |
|---|---|
| Rules return 0, LLM gated off | Render booking form, paste section open, flash "couldn't parse" |
| Rules return 0, LLM enabled, LLM also returns 0 | Same as above |
| Rules return ≥1 with valid `type` | Pre-fill form (single) or render review (multiple) |
| LLM API error (network, 5xx, auth) | Log at WARNING, return empty → same as "couldn't parse" |
| LLM returns malformed JSON | Pydantic retry within SDK; if still fails, return empty |
| Parsed `type` not in BOOKING_TYPE_CODES | Coerce to `"other"`, retain other fields |
| Parsed datetime in wrong format | Skip that field (leave `None`), don't reject whole booking |
| Empty paste body submitted | Re-render form with validation error "paste the email body first" |
| Paste body > 50 KB | Truncate to 50 KB before parsing + log at INFO. Most confirmation emails are < 20 KB. |
| Form submitted with no checked bookings | Re-render review screen with flash "select at least one" |

## Testing approach

### `tests/test_booking_parser.py`

- **Per-extractor (7 modules):** ≥ 3 fixture emails each under
  `tests/fixtures/booking_emails/<type>/`. Each test asserts the extractor
  returns a `ParsedBooking` with the expected `type`, `title`, dates,
  vendor, cost, currency, confirmation number. Includes one
  "should-not-match" sample per type to verify the extractor doesn't
  over-match unrelated emails.

- **Orchestrator:**
  - `parse_booking_email("")` → `ParseResult(bookings=[], source="none")`
  - `parse_booking_email("<flight-confirmation>")` → 1 result, source="rules"
  - `parse_booking_email("<round-trip-flight>")` → 2 results, source="rules"
  - `parse_booking_email("<garbage>")` with LLM gate off → 0 results
  - `parse_booking_email("<garbage>")` with LLM gate on + mocked SDK → 1
    or 2 results depending on mocked response

- **LLM gating logic:**
  - Missing `ANTHROPIC_API_KEY` → gate fails, no SDK import attempted
  - Missing `PASTE_PARSER_LLM_ENABLED` → gate fails
  - SDK import fails (mock the ImportError) → gate fails
  - All gates pass → `parse_with_llm` called with mocked SDK

### `tests/test_routes.py` (additions)

- `POST /trips/<id>/bookings/parse` with no body → 400 with friendly message
- `POST /trips/<id>/bookings/parse` returning 0 bookings → 200, paste section open in HTML
- `POST /trips/<id>/bookings/parse` returning 1 booking → 200, form fields prefilled
- `POST /trips/<id>/bookings/parse` returning 2 bookings → 200, review template rendered
- `POST /trips/<id>/bookings/paste-confirm` with no selections → 200, error flash
- `POST /trips/<id>/bookings/paste-confirm` with 2 selections → 302 to bookings list, 2 bookings created, auto-itinerary-link rows present
- Access control: non-editor on any of the above → 403

## Key design decisions

### Why universal-by-type rules (not per-provider templates)
- Per-provider regexes are brittle and require maintenance per airline /
  hotel chain / OTA. Universal patterns (IATA codes, ISO/RFC datetimes,
  currency-amount tuples) degrade gracefully — a partial match still
  pre-fills *some* fields.
- The LLM fallback (when enabled) covers the long tail. Per-provider
  rules would duplicate work.

### Why strategy pattern (run all 7, pick winners) over type-first classification
- Type classification adds a failure mode: classify wrong → wrong
  extractor runs → fields missing.
- The strategy pattern's "cost" is microseconds — regex hits are cheap.
- Tie-breaking by confidence score is straightforward; the rules engine
  knows when it's guessing vs. when it's confident.

### Why pre-fill the standard form (not a separate "save from paste" route)
- Reuses the existing form template, validation, and submit handler.
- The booking-save POST handler already calls
  `auto_itinerary_items_for_booking()` — no duplication.
- Total new route count: 2 (parse, paste-confirm). Without form reuse it
  would be 4+.

### Why one paste = N bookings (variable UX based on count)
- Single-booking emails (most restaurants, activities, hotels) want
  zero-friction pre-fill — the review screen would feel like extra clicks.
- Multi-booking emails (round-trip flights, multi-leg itineraries) want
  explicit per-segment confirmation — pre-filling just the first
  segment would lose the second silently.
- Dispatching by count gives each case the right UX.

### Why LLM-off-by-default
- Users without API keys still get value from day 1 (rules path).
- Cost ($0.005 per parse with Opus 4.8) and privacy (email body leaves
  the server) are real concerns — opt-in is the correct default.
- The 3-gate check (key + flag + SDK) means flipping it on is
  deliberate and reversible.

## Migration notes

None — no schema changes. The feature is additive: existing routes,
templates, helpers, and tests are all untouched except for the explicit
modifications listed in the file map.

## Open questions (resolved in plan)

- Should `anthropic` be added to `requirements.txt` now (lazy import + dead
  code) or left out until the user enables the LLM path? Plan to decide
  based on whether shipping the SDK install delta now beats deferring it.
- Exact confidence-scoring formula per extractor — currently "fraction of
  expected fields populated". May refine during implementation if some
  extractors over-trigger.
- Whether the LLM prompt should describe the 7 types and field rules
  inline (longer prompt, no cache benefit at this volume) or use the
  Anthropic prompt-caching pattern (overkill for an opt-in feature at
  expected volumes). Default: inline.

## Risks

| Risk | Mitigation |
|---|---|
| Universal-by-type extractors over-trigger across types (e.g. hotel extractor matches a restaurant reservation) | `MIN_CONFIDENCE` filter; type-specific keyword anchoring in each extractor; per-type "should-not-match" tests catch regressions. |
| Pasted email contains sensitive info (credit card last 4, frequent-flyer numbers) and is logged | Don't log paste bodies. Log only at WARNING/ERROR for parser-internal failures, never `logger.info("parsing: %s", text)`. |
| Multi-segment review screen confuses users with N > 5 results | v1 caps at 5 bookings per parse (rules return top 5 by confidence; LLM prompt requests ≤ 5). Larger emails get truncated; user can paste again. |
| LLM path enabled accidentally (env var typo, leaked key) | Three independent gates means a single misconfiguration leaves the path off. Logged at INFO when LLM call is made so it's visible in prod logs. |
| `parse_booking_form()` validates form fields stricter than `ParsedBooking` allows | Plan-stage check: walk through each field's validation; reconcile any mismatches before implementation. |

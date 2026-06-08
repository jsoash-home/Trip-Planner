# Destination Clock / Time Zones — Design Spec

> **Status:** Approved design, awaiting implementation plan. Phase 3
> feature B2 from [docs/PHASE_3_ROADMAP.md](../../PHASE_3_ROADMAP.md).
> Spec captures the design decisions made during the 2026-06-07
> brainstorm. Second feature in the "plan smarter" thread; A1 / A2 /
> A3 / B1 shipped 2026-05-31 through 2026-06-07.

## Goal

Show the destination's current local time on the trip overview,
ticking once per second, alongside a small "X hours ahead/behind"
tag computed against the viewer's own time zone. The clock renders
in two places:

- On the **trip overview hero** for trips in `planning` status — as
  a slim panel beneath the existing countdown so the hero reads
  "27 days · 🕒 Tokyo, 3:47 PM (14 h ahead)".
- On the **Today section** for trips in `in_progress` status — as
  a chip just above the existing weather hero so the section reads
  "🕒 Rome, 8:12 AM (6 h ahead)" → weather chip → today's items.

For `completed` trips the clock is hidden — the "Welcomed home N
days ago" copy is the hero, and the destination time isn't useful
to the user any more.

Each trip's IANA time zone is stored on a new nullable column
`Trip.timezone_iana` (e.g. `Europe/Paris`). The value is
**lazily auto-derived** at trip-overview view time (and surfaced
as a preview on the trip edit form) from the first geocoded
booking's `(lat, lng)` via the `timezonefinder` library — a pure
Python lookup with no API key and no network. Deriving on view
matches how geocoding works today (lazy, on map view), and lets
existing trips self-heal the next time they're opened — no
backfill job. The trip form lets the user override the derived
value with a searchable text input.

If the column is `NULL` (no geocoded bookings yet, lookup
failed, or trip predates the feature), the clock simply doesn't
render. No fake "guess by country name" fallback.

## Background and motivation

Phase 3 roadmap calls this out as the fifth feature — a small,
high-clarity helper for travellers checking the overview from
their home timezone:

> 🕒 Tokyo, **3:47 PM** (14 h ahead)

It's the smallest remaining "plan smarter" feature. Phase 2's
geocoding pipeline already gave every booking a `(lat, lng)` pair,
so the lookup is free of new infrastructure. The UI mirrors the
`countdown.js` ticker pattern exactly: a setInterval(1000) loop
updates the DOM in place. The B1 weather hero already lives in the
Today section, so adding a clock chip beside it is one row in the
template.

## Scope

**In scope:**

- One new SQLAlchemy column `Trip.timezone_iana` (`String(64)`,
  nullable). Migrated via the existing `_run_safe_alters` pattern
  in `app.py`.
- One new `src/destination_clock.py` module:
  - Pure helpers: `iana_from_coords`, `is_valid_iana`,
    `hours_offset_label`, `format_clock_label`.
  - Pure helper for trip-form parsing: extend
    `parse_trip_form` in `src/trip_helpers.py` to read and
    validate `timezone_iana` from the form payload.
- Lazy auto-derive: when `trip.timezone_iana is None` AND any
  booking on the trip has `geocoded_lat`/`geocoded_lng` set,
  populate the column from the first booking (by
  `start_datetime`) with coords. Triggered from the `trip_overview`
  GET and the `trip_edit` GET (so the form can show the preview).
  Never overwrites a user-set value.
- One new `static/js/destination_clock.js` — the ticker. Mirrors
  the `tickHero` + `setInterval(…, 1000)` pattern in
  `static/js/countdown.js`. Computes the viewer-vs-destination
  offset using the browser's `Intl.DateTimeFormat().resolvedOptions().timeZone`.
- Trip form template: a text input with a `<datalist>` of common
  zones + a help line showing what was auto-derived ("Auto-detected
  from your first booking: `Europe/Paris`. Override below if
  needed.").
- Trip overview template: clock panel under the countdown for
  `planning` trips.
- Today section template: clock chip above the weather hero for
  `in_progress` trips.
- Unit tests for every pure helper. Integration tests for the
  trip-form round-trip, the auto-derive-on-booking-save path,
  and the template render guards (clock shows when set, hides
  when `NULL`).

**Out of scope (explicit):**

- No per-leg timezone story. v1 uses one IANA zone per trip; a
  multi-zone itinerary (Tokyo → Bangkok) shows Tokyo. The spec
  flags this as a known limitation; revisit in a later phase if
  it bites.
- No "world clock" of every city the user visits. Just one clock
  per trip.
- No server-side computation of "X hours ahead" — the viewer's
  zone is unknown to the server. Compute in JS.
- No daylight-saving warnings ("Paris springs forward on Mar 29
  during your trip"). Nice-to-have for a later polish pass.
- No clock on the dashboard `/trips` cards. Too small a slot to
  carry a ticker without visual noise.
- No clock on the yearbook or lifetime map.
- No backwards-fill job for existing trips. Existing trips
  populate `timezone_iana` the next time any of their bookings is
  edited — or the user sets it manually on the trip form.
- No editing of the time zone from the overview hero — that lives
  on the trip form only.
- No abbreviated zone names ("JST", "PST") — IANA strings only.
  Abbreviations are ambiguous and rotate with DST.

## Decisions baked in

| Decision | Choice | Why / rejected alternative |
|---|---|---|
| Time-zone library | **`timezonefinder`** (pure Python, no key, MIT) | Roadmap-specified. Local lookup — no API call, no cache table needed. Adds ~50 MB of zone-boundary data via its sub-dependency `h3` is NOT used; `timezonefinder` ships its own ~10 MB lookup tables. Acceptable for v1; flag the install size in the loose-ends section. |
| Validation | **stdlib `zoneinfo.available_timezones()`** | Python 3.9+ ships zoneinfo. Cheap to call once per form submit. Rejects "Europe/Pariss" before it can be saved. |
| Column type | **`String(64)`, nullable** | Longest IANA name is 30-something chars; 64 is roomy. Nullable because most existing trips don't have one yet and we don't force a backfill. |
| Auto-derive trigger | **Lazy at view time** — `trip_overview` GET and `trip_edit` GET, when `trip.timezone_iana is None` AND at least one booking has coords. Use the first booking by `start_datetime`. | Geocoding itself is lazy (runs on map view, not on booking save). Deriving at view time matches that, self-heals existing trips with no backfill job, and keeps the booking-save path untouched. |
| User override | **Free-text input + `<datalist>` of common zones** | A full 400-zone `<select>` is unusable. A searchable text box with autocomplete works for both "I know I want Asia/Tokyo" and "I'll just leave the auto-detected value." |
| Form field placement | **Below the cover emoji + currency row on the trip form** | Sits with the other "trip-wide settings" fields. |
| Hero placement (planning) | **Clock panel under the countdown number, above the themed copy** | Sits where the eye already goes for the countdown — one glance gets "27 days, and Tokyo is 3:47 PM right now." |
| Hero placement (in_progress) | **Chip at top of the Today section, immediately above the weather hero** | Today section is the established hero for in-progress trips. Clock + weather makes for a tight "where I am, what time, what's the sky doing" cluster. |
| Hero placement (completed) | **None — clock is hidden** | "Welcomed home" is the message; the destination time isn't relevant. |
| Tick frequency | **1 second** | Matches `countdown.js`. Drift is visible at the seconds level; longer intervals feel sticky. |
| Offset computation | **Browser-side, viewer's tz from `Intl.DateTimeFormat().resolvedOptions().timeZone`** | Server can't know it. `Intl` is in every browser we care about. |
| Offset label rounding | **Whole hours when the offset is integral, "30 min" / "45 min" suffix when not** | India is +5:30, Nepal is +5:45, parts of Australia are +9:30. "14 h ahead" reads cleanly; "5 h 30 min ahead" handles the half-zones. |
| Offset sign vocabulary | **"X h ahead" / "X h behind" / "same time"** | Friendlier than "+14" or "−14". |
| Multi-leg trip handling | **Use the first-booking-by-start-datetime's coords; document the limit** | Matches roadmap. A Tokyo→Bangkok trip showing Tokyo is wrong some of the time, but it's never confusingly wrong — it's a coherent "the trip's anchor city." |
| Failure mode (lookup raises) | **Silently leave `timezone_iana = NULL`, log a warning, render nothing** | Same posture as B1 weather — enrichment, not core. |
| Failure mode (saved value not in `available_timezones`) | **Render nothing client-side, log a warning** | Defensive: zoneinfo data could shift between the version that saved and the version that reads. Old trips with stale zones don't break. |

## Architecture

```
                  ┌──────────────────────────────────────┐
                  │  timezonefinder (pure-Python lookup) │
                  │  TimezoneFinder().timezone_at(...)   │
                  └─────────────────▲────────────────────┘
                                    │ (no network)
                          ┌─────────┴────────────┐
                          │ src/destination_clock│
                          │  iana_from_coords()  │
                          │  is_valid_iana()     │
                          │  hours_offset_label  │
                          │  format_clock_label  │
                          └─────────▲────────────┘
                                    │
                  ┌─────────────────┼─────────────────────┐
                  │                                       │
                  ▼                                       ▼
        ┌──────────────────────────┐          ┌────────────────────────┐
        │ trip_overview GET        │          │ trip form (new + edit) │
        │ trip_edit GET            │          │  → user override input │
        │  → lazy auto-derive if   │          │    + datalist          │
        │    trip.tz is NULL       │          │                        │
        └──────────────────────────┘          └────────────────────────┘
                  │                                       │
                  └───────────────────┬───────────────────┘
                                      ▼
                          Trip.timezone_iana (DB)
                                      │
                  ┌───────────────────┼───────────────────────────┐
                  │                                               │
                  ▼                                               ▼
        ┌──────────────────────────┐              ┌────────────────────────────┐
        │ trip overview hero       │              │ today section (in_progress)│
        │ (planning status)        │              │                            │
        │  <span data-vp-clock …>  │              │  <span data-vp-clock …>    │
        └─────────────▲────────────┘              └─────────────▲──────────────┘
                      │                                         │
                      └───────────────────┬─────────────────────┘
                                          ▼
                          static/js/destination_clock.js
                          (setInterval, 1s, in-place DOM update)
```

### Data model changes

| Table | Column | Type | Default | Notes |
|---|---|---|---|---|
| `trip` | `timezone_iana` | `String(64)` | NULL | IANA name (e.g. `Europe/Paris`). NULL means "no clock yet." |

Migration uses the same additive `ALTER TABLE` pattern as B1's
`user.weather_units` add — extend `_run_safe_alters()` in
`app.py`.

### `src/destination_clock.py` (new module)

```python
import logging
from typing import Optional
from zoneinfo import available_timezones

logger = logging.getLogger(__name__)

# Common-zone list used by the trip-form <datalist>. Curated, not
# the full 400-zone catalogue — covers the top travel destinations.
COMMON_TIMEZONES: list[str] = [
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


# Pure helpers (no DB, no network — timezonefinder is in-process)

def iana_from_coords(lat: float, lng: float) -> Optional[str]:
    """Return an IANA zone name for (lat, lng), or None on lookup
    failure / ocean coordinate. Wraps timezonefinder so the rest
    of the app doesn't depend on it directly."""

def is_valid_iana(name: str) -> bool:
    """True iff name is in zoneinfo.available_timezones()."""

def hours_offset_label(offset_minutes: int) -> str:
    """Friendly label: '14 h ahead', '5 h 30 min ahead',
    '8 h behind', 'same time'."""

def format_clock_label(city_hint: Optional[str], iana: str) -> str:
    """The text the hero badge leads with — '🕒 Tokyo' when a
    city hint is available, '🕒 Asia/Tokyo' otherwise."""
```

`hours_offset_label` is server-side too even though the live ticker
is in JS — the server pre-renders the initial label so the panel
isn't blank for the half-second before JS boots. JS replaces it
once `Intl` reports the viewer's zone.

### Auto-derive flow

Tiny helper in `app.py` — call it from `trip_overview` GET and
`trip_edit` GET, before rendering:

```python
def _ensure_trip_timezone(trip) -> Optional[str]:
    """If trip.timezone_iana is None and at least one booking has
    coords, derive + persist. Returns the (now-set) value, or None
    if nothing could be derived. Idempotent."""
    if trip.timezone_iana:
        return trip.timezone_iana
    candidates = sorted(
        [b for b in trip.bookings
         if b.geocoded_lat is not None and b.geocoded_lng is not None],
        key=lambda b: (b.start_datetime or datetime.max),
    )
    if not candidates:
        return None
    iana = iana_from_coords(candidates[0].geocoded_lat,
                            candidates[0].geocoded_lng)
    if not iana:
        return None
    trip.timezone_iana = iana
    db.session.commit()
    return iana
```

The check `trip.timezone_iana is None` guards against overwriting
a value the user has already set. Both call sites are GET routes
the user already lands on naturally — no extra page load required.

### Trip-form parsing change

`parse_trip_form` in `src/trip_helpers.py` reads a new field:

```python
raw_tz = (form.get("timezone_iana") or "").strip()
if raw_tz and not is_valid_iana(raw_tz):
    errors["timezone_iana"] = "Not a recognized time zone."
else:
    parsed["timezone_iana"] = raw_tz or None
```

Empty string → `None` (lets the user clear an override and fall
back to "auto-derived from next booking save"). Invalid string →
field error, same path as the existing currency / date validations.

### `static/js/destination_clock.js` (new file)

```javascript
/**
 * destination_clock.js — ticking destination clock + viewer offset.
 *
 * DOM convention:
 *   <span data-vp-clock
 *         data-clock-iana="Europe/Paris"
 *         data-clock-city="Paris">
 *     <span data-clock-time>3:47 PM</span>
 *     <span data-clock-offset>(14 h ahead)</span>
 *   </span>
 *
 * Tick: setInterval(1000). Mirrors countdown.js.
 *
 * Offset: viewer tz from
 *   Intl.DateTimeFormat().resolvedOptions().timeZone
 * computed once on boot and cached for the page.
 */
```

Public surface (one function called from `DOMContentLoaded`):

- `startDestinationClocks()` — find every `[data-vp-clock]`, render
  once, then `setInterval(1000)`.

Internal helpers:

- `formatTimeForZone(date, iana)` — wraps
  `new Intl.DateTimeFormat([], {timeZone: iana, hour: 'numeric',
  minute: '2-digit'}).format(date)`. Returns `'—'` if `iana` is
  unknown.
- `computeOffsetMinutes(viewerIana, destIana)` — returns the
  signed offset minutes; uses two `Intl.DateTimeFormat`
  formatToParts of the same instant.
- `friendlyOffsetLabel(minutes)` — the JS twin of
  `hours_offset_label`. Same strings, same rounding rules.

The IIFE pattern matches `countdown.js`. Wired up in
`templates/base.html` with one extra `<script>` include.

### Routes

No new routes. The existing `trip_new` / `trip_edit` /
`booking_new` / `booking_edit` routes are extended:

| Method | Path | Change |
|---|---|---|
| GET | `/trips/new` | Pass `common_timezones=COMMON_TIMEZONES` to the template. |
| POST | `/trips/new` | Use the extended `parse_trip_form` — save `timezone_iana`. |
| GET | `/trips/<id>/edit` | Call `_ensure_trip_timezone(trip)` (lazy auto-derive). Pass `common_timezones` plus a `tz_autodetect_preview` hint computed from the first geocoded booking (independent of the persisted value), so the form can say "We'd auto-detect: Europe/Paris." |
| POST | `/trips/<id>/edit` | Save `timezone_iana`. |
| GET | `/trips/<id>` | Call `_ensure_trip_timezone(trip)` (lazy auto-derive). Pass `initial_dest_time` (server-formatted clock string) so the hero panel isn't blank for 200ms while JS boots. |

### Template changes

**`templates/_countdown_hero.html`** — clock panel inside the
`planning` branch, after the themed copy:

```jinja
{% if trip.timezone_iana %}
  <div class="vp-destclock vp-destclock--hero"
       data-vp-clock
       data-clock-iana="{{ trip.timezone_iana }}"
       data-clock-city="{{ trip.destination or trip.timezone_iana.split('/')[-1].replace('_', ' ') }}">
    🕒 <span class="vp-destclock__city">{{ trip.destination or trip.timezone_iana.split('/')[-1].replace('_', ' ') }}</span>,
    <span class="vp-destclock__time" data-clock-time>{{ initial_dest_time }}</span>
    <span class="vp-destclock__offset text-muted" data-clock-offset></span>
  </div>
{% endif %}
```

`initial_dest_time` is a context var the overview route computes
server-side via `zoneinfo.ZoneInfo(trip.timezone_iana)` against
`datetime.utcnow()` — formatted as `H:MM AM/PM`. This avoids a
"blank for 200ms" hero state while JS boots.

**`templates/_today_section.html`** (the partial used by trip
overview when in-progress) — chip above the existing weather hero:

```jinja
{% if trip.timezone_iana %}
  <div class="vp-destclock vp-destclock--chip"
       data-vp-clock
       data-clock-iana="{{ trip.timezone_iana }}"
       data-clock-city="{{ trip.destination or trip.timezone_iana.split('/')[-1].replace('_', ' ') }}">
    🕒 {{ trip.destination or trip.timezone_iana.split('/')[-1].replace('_', ' ') }}
    · <span data-clock-time>{{ initial_dest_time }}</span>
    <span class="text-muted small" data-clock-offset></span>
  </div>
{% endif %}
```

**`templates/trip_form.html`** — new field below the currency row:

```jinja
<div class="mb-3">
  <label for="trip-timezone" class="form-label">
    Destination time zone <span class="text-muted small">— optional</span>
  </label>
  <input id="trip-timezone" name="timezone_iana" type="text"
         list="vp-tz-list"
         class="form-control{{ invalid_class(field_errors, 'timezone_iana') }}"
         value="{{ form.get('timezone_iana', '') }}"
         placeholder="e.g. Europe/Paris">
  {% if tz_autodetect_preview and not form.get('timezone_iana') %}
    <div class="form-text small">
      Auto-detected from your first booking:
      <code>{{ tz_autodetect_preview }}</code>.
    </div>
  {% endif %}
  {{ field_error(field_errors, 'timezone_iana') }}
  <datalist id="vp-tz-list">
    {% for tz in common_timezones %}
      <option value="{{ tz }}">
    {% endfor %}
  </datalist>
</div>
```

**`templates/base.html`** — one new `<script>` include:

```html
<script src="{{ url_for('static', filename='js/destination_clock.js') }}" defer></script>
```

### CSS additions in `static/css/app.css`

- `.vp-destclock` — flex row, gap `0.4rem`, `font-variant-numeric:
  tabular-nums` so the seconds don't jitter the layout.
- `.vp-destclock--hero` — `font-size: 1rem`, sits as a sibling of
  `.countdown-hero-themed`. Centered.
- `.vp-destclock--chip` — `font-size: 0.9rem`, pill background
  `var(--vp-surface-2)`, padding `0.25rem 0.7rem`, fits in the
  Today section above the weather chip.
- `.vp-destclock__offset` — `font-size: 0.85em`, muted color.

## The page experience

### Planning hero (countdown + clock)

```
        ┌─────────────────────────────────────────┐
        │              27 days                    │
        │                                         │
        │              — h — m — s                │
        │                                         │
        │   ✨ Three weeks of magic in Paris ✨    │
        │                                         │
        │   🕒 Paris, 3:47 PM (6 h ahead)         │  ← new
        └─────────────────────────────────────────┘
```

The clock ticks once per second. The offset stays static after
the first paint — recomputed on page load only.

### In-progress Today section

```
☀️ Today — Day 3
🕒 Rome · 8:12 AM (6 h ahead)              ← new clock chip
[ ☀️ 28° / 17° · 💧 0% ]                    ← existing weather hero

  09:00  Walking tour of Trastevere
  ...
```

### Completed (no clock)

```
  Welcomed home 4 days ago
```

No clock — same as today.

### Trip form

```
Destination time zone — optional
[ Europe/Paris                                  ▼ ]
Auto-detected from your first booking: Europe/Paris.
```

Typing "asia" filters the datalist to Asia/* options. Clearing the
field saves NULL and the next booking save will re-auto-detect.

## Edge cases

| Case | Behavior |
|---|---|
| Trip has no bookings yet | `trip.timezone_iana` stays NULL. No clock renders. Trip form shows no auto-detect preview. |
| First booking is added without coords (failed geocode) | `trip.timezone_iana` stays NULL. No clock. The next time the user opens a map view, geocoding may populate coords; the subsequent overview/edit visit then derives. |
| First booking is geocoded but `iana_from_coords` returns None (ocean coord, pole) | Stay NULL, log a warning. The lazy derive retries on every visit, so a later, coord-bearing booking can win. |
| User-set `timezone_iana` differs from what auto-derive would pick | Auto-derive is skipped entirely on subsequent booking saves (the guard is `trip.timezone_iana is None`). User's choice wins. |
| User types an invalid zone name in the trip form | `parse_trip_form` returns a field error; form re-renders with the validation message; no save. |
| User clears the form value back to empty | `timezone_iana` saves as NULL. Next booking save re-auto-detects. |
| Saved zone string is not in current `zoneinfo.available_timezones()` (e.g. a deprecation) | Server template still renders the panel (it doesn't validate at render); JS `Intl.DateTimeFormat` throws on the unknown name → we catch it in `formatTimeForZone` and the panel hides itself by setting `display: none` via a class. Log a console warning. |
| Viewer's browser blocks `Intl` or it returns no time zone | The static server-rendered time still shows; the offset label stays blank. No jitter, no error. |
| Half-hour zone (India: +5:30) | `friendlyOffsetLabel` formats it as `"5 h 30 min ahead"`. |
| Same time zone as viewer (`Asia/Tokyo` viewer, `Asia/Tokyo` trip) | Offset label reads `"same time"`. The clock still ticks. |
| DST transition during the page session | The clock keeps ticking through it — `Intl.DateTimeFormat` re-derives the offset every call. The offset label could go stale by one hour on the page that was open through the transition; refreshing the page fixes it. Documented limitation. |
| In-progress trip with no `timezone_iana` AND no `today_forecast` | Today section header still renders; both chips hidden. No layout collapse. |
| Multi-leg trip where the user is past the first booking's city | Clock still shows the first booking's city. v1 limitation, called out in the trip form help text? — no, not surfaced in v1. Loose end. |
| Database migration — first deploy | `_run_safe_alters` adds `trip.timezone_iana`. Existing trips have NULL — no clocks render until a booking is edited or the user sets the value manually. |
| `timezonefinder` install fails on a deploy target (missing build tool) | Import wrapped in try/except in `src/destination_clock.py` — failing import sets `iana_from_coords = lambda *_: None`. Logs a startup warning. Trip pages still render; auto-derive is a no-op until the install is fixed. |

## Testing

### Unit tests (new) — `tests/test_destination_clock.py`

**`iana_from_coords`** (~4):
- Known landmass coord returns expected zone (Paris → `Europe/Paris`).
- Ocean coord returns None.
- Pole-adjacent coord returns None or `Etc/...` — accept either.
- `timezonefinder` failure (mocked to raise) returns None and logs.

**`is_valid_iana`** (~3):
- Known zone returns True.
- Mistyped zone (`Europe/Pariss`) returns False.
- Empty string returns False.

**`hours_offset_label`** (~7):
- 0 minutes → `"same time"`.
- +840 minutes → `"14 h ahead"`.
- -480 minutes → `"8 h behind"`.
- +330 minutes → `"5 h 30 min ahead"`.
- +345 minutes → `"5 h 45 min ahead"`.
- -570 minutes → `"9 h 30 min behind"`.
- +60 minutes → `"1 h ahead"` (singular handled — see decision).

**`format_clock_label`** (~3):
- City hint present → `"🕒 Tokyo"`.
- City hint None → `"🕒 Asia/Tokyo"`.
- City hint with underscore in IANA fallback gets replaced
  (`Asia/Ho_Chi_Minh` → `"Ho Chi Minh"`).

### Unit tests (extend) — `tests/test_trip_helpers.py`

**`parse_trip_form` — timezone_iana branch** (~4):
- Valid IANA string saves through to `parsed["timezone_iana"]`.
- Invalid IANA string raises a field error.
- Empty string saves as None.
- Whitespace gets stripped before validation.

### Integration tests (extend) — `tests/test_routes.py`

- `test_trip_new_saves_timezone_iana` — POST with `Asia/Tokyo`, row has it.
- `test_trip_new_rejects_invalid_timezone` — POST with `Europe/Pariss`, form re-renders with error.
- `test_trip_edit_clears_timezone_when_empty_string_posted` — POST empty, row goes NULL.
- `test_trip_overview_auto_derives_timezone_when_null` — GET on a trip with NULL tz and a geocoded booking populates the column.
- `test_trip_overview_does_not_overwrite_existing_timezone` — GET on a trip with tz already set leaves it alone.
- `test_trip_edit_auto_derives_timezone_when_null` — GET on the edit form populates the column from the first geocoded booking.
- `test_trip_overview_renders_clock_panel_when_tz_set` — body contains `data-vp-clock` with the right zone.
- `test_trip_overview_skips_clock_panel_when_tz_null` — body does not contain `data-vp-clock`.
- `test_today_section_renders_clock_chip_when_tz_set` — in-progress trip with tz set.
- `test_today_section_skips_clock_chip_when_tz_null` — in-progress trip with no tz.

Approximately 21 unit + 10 integration = **~31 new tests**.
Suite target: 567 → ~598.

### Manual smoke checklist

- Open a trip's edit page with no `timezone_iana` set and a
  geocoded booking — the "Auto-detected" preview shows.
- Save with a manual override → reload `/trips/<id>` → hero shows
  the new zone, time ticks, offset label appears.
- Clear the field to empty → save → trip overview hero hides
  the clock.
- Add a new booking with a geocoded location → reload → trip
  overview hero shows the freshly-detected zone.
- Open in a browser whose system timezone matches the trip's zone
  → offset reads `"same time"`.
- Open in a browser whose system timezone is India (+5:30) →
  offset reads `"5 h 30 min behind"` for a `Europe/London` trip.
- Force an invalid zone name into the form (DevTools edit the
  `value` to `Europe/Pariss`) → submit → form re-renders with
  the error message; row is unchanged.
- In-progress trip with `timezone_iana` set: Today section shows
  the chip above the weather hero.

## Dependencies

- **New Python package: `timezonefinder` (>=6.5)** — added to
  `requirements.txt`. Pure-Python, MIT-licensed, ships its own
  lookup data, no API key. Installation size is ~10 MB
  uncompressed; not a deploy concern for Railway / Render.
- Phase 2 geocoding — already supplies `geocoded_lat` /
  `geocoded_lng` on bookings.
- B1 weather feature — already lives in the Today section; the
  destination chip sits adjacent and follows the same pattern.
- stdlib `zoneinfo` — Python 3.9+ baseline already declared.
- Browser `Intl.DateTimeFormat` — ubiquitous in the browsers we
  support.

## Open questions resolved during brainstorm

| Question | Decision |
|---|---|
| Lookup library | `timezonefinder` (pure Python, no key) |
| Storage column | `Trip.timezone_iana String(64)` nullable |
| Auto-derive trigger | Lazy at view time (trip_overview / trip_edit GET) when trip.tz is NULL and a booking has coords |
| User override UX | Text input + datalist of common zones, with auto-detect preview |
| Multi-zone trips | Use first booking; document limitation; no per-leg story in v1 |
| Hero placement (planning) | Panel under the countdown |
| Hero placement (in-progress) | Chip above the weather hero in the Today section |
| Hero placement (completed) | Hidden |
| Offset computation | Browser-side via `Intl`; server pre-renders initial dest time |
| Tick frequency | 1 s (mirrors countdown.js) |
| Half-hour zones | Show `"X h Y min ahead/behind"` |
| Validation | `zoneinfo.available_timezones()` |
| Failure mode | Silent — no chip, log warning |

## Updating this document

Same convention as A1 / A2 / A3 / B1. Fix the spec inline and
commit `docs: clarify <section> in destination-clock spec` if
implementation reveals a design issue. The spec is the record of
"what we agreed to" — not a frozen artifact.

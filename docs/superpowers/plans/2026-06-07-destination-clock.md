# Destination Clock / Time Zones — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the destination's local time on the trip overview
(planning hero + in-progress Today section), ticking once per
second, with a friendly "X h ahead / behind" tag computed in the
browser. Store the IANA zone on `Trip.timezone_iana`, auto-derive
lazily from the first geocoded booking, and let the user override
on the trip form.

**Architecture:** One new nullable column (`Trip.timezone_iana`),
one new module (`src/destination_clock.py`) with pure helpers,
one new static JS file (`static/js/destination_clock.js`) that
mirrors `countdown.js`. Lazy auto-derive lives in a tiny helper
`_ensure_trip_timezone(trip)` in `app.py`, called from the
`trip_overview` and `trip_edit` GET handlers. Trip form gains a
text input + `<datalist>`. Hero panel for planning trips; chip
for in-progress trips above the existing B1 weather hero.

**Tech Stack:** Python 3.9, Flask, SQLAlchemy, **new dependency
`timezonefinder`** (pure Python, no key), stdlib `zoneinfo` for
validation, browser `Intl.DateTimeFormat` for offset, pytest with
`timezonefinder` mocked at module boundary.

---

## Spec

Full design: [docs/superpowers/specs/2026-06-07-destination-clock-design.md](../specs/2026-06-07-destination-clock-design.md)

Read it first. This plan executes that spec.

## Background reading

Before starting, read these to put the patterns in head:

- [src/weather.py](../../../src/weather.py) — the closest existing
  analog: thin helpers + a wrapping module that the route layer
  calls. Mirror its pure/impure split.
- [src/trip_helpers.py:246](../../../src/trip_helpers.py) —
  `parse_trip_form` signature this plan extends.
- [static/js/countdown.js](../../../static/js/countdown.js) — the
  setInterval(1000) ticker + IIFE pattern to mirror.
- [templates/_countdown_hero.html](../../../templates/_countdown_hero.html)
  — the trip-overview hero partial; T6 adds the clock panel inside
  the `planning` branch.
- [templates/_today_section.html](../../../templates/_today_section.html)
  — the in-progress hero partial; T7 adds the clock chip above the
  weather hero.
- [app.py:1661](../../../app.py) — `_trip_primary_coords` for the
  shape of the in-app coord helper (we add a sibling for
  "first-by-start_datetime").
- [app.py:283](../../../app.py) — `_run_safe_alters` for the
  additive `ALTER TABLE` pattern.

---

## File map

**Create:**

- `src/destination_clock.py` — pure helpers (`iana_from_coords`,
  `is_valid_iana`, `hours_offset_label`, `format_clock_label`,
  `COMMON_TIMEZONES`).
- `tests/test_destination_clock.py` — unit tests.
- `static/js/destination_clock.js` — ticker + offset computation.

**Modify:**

- `requirements.txt` — add `timezonefinder>=6.5`.
- `models.py` — add `timezone_iana` column on `Trip`.
- `app.py` — `_run_safe_alters` ALTER; new `_ensure_trip_timezone`
  helper; pass `initial_dest_time` / `common_timezones` /
  `tz_autodetect_preview` to templates from `trip_overview`,
  `trip_new`, `trip_edit`.
- `src/trip_helpers.py` — `parse_trip_form` reads + validates
  `timezone_iana`.
- `tests/test_trip_helpers.py` — extend `parse_trip_form` tests.
- `tests/test_routes.py` — append clock integration tests.
- `templates/trip_form.html` — new optional field with datalist
  and preview help line.
- `templates/_countdown_hero.html` — clock panel inside the
  `planning` branch.
- `templates/_today_section.html` — clock chip above the weather
  hero.
- `templates/base.html` — include `destination_clock.js`.
- `static/css/app.css` — append `.vp-destclock*` styles.
- `docs/PHASE_3_ROADMAP.md` — flip B2 row to ✓ shipped with plan
  link (final task).

**Do not modify:**

- `src/weather.py`, `static/js/countdown.js`. The new clock module
  mirrors them by example, doesn't edit them.
- The `booking_new` / `booking_edit` routes. Auto-derive is lazy
  on view, not on save.

---

## Task 1: Schema — `Trip.timezone_iana` column + migration

**Files:**

- Modify: `models.py`
- Modify: `app.py` (the `_run_safe_alters` block)

**Schema (one shot, hard to recover — be careful):**

`Trip.timezone_iana` — `db.Column(db.String(64), nullable=True)`.

Placed in the `Trip` model after the existing
`primary_currency` column.

**`_run_safe_alters` addition:**

```python
"ALTER TABLE trip ADD COLUMN timezone_iana VARCHAR(64)",
```

Wrap in the existing `try/except OperationalError: pass` pattern.

**No tests for this task.** Smoke: app starts cleanly; `sqlite3
vacation.db ".schema trip"` shows the new column.

**Commit:** `feat: Trip.timezone_iana column + safe ALTER`

---

## Task 2: `src/destination_clock.py` — pure helpers + tests

**Files:**

- Modify: `requirements.txt` (add `timezonefinder>=6.5`)
- Create: `src/destination_clock.py`
- Create: `tests/test_destination_clock.py`

**Install:** `pip install timezonefinder` locally before running
tests. Document in commit body.

**Public surface:**

```python
import logging
from typing import Optional
from zoneinfo import available_timezones

logger = logging.getLogger(__name__)

COMMON_TIMEZONES: list[str]   # ~30 curated zones (see spec)

def iana_from_coords(lat: float, lng: float) -> Optional[str]: ...
def is_valid_iana(name: str) -> bool: ...
def hours_offset_label(offset_minutes: int) -> str: ...
def format_clock_label(city_hint: Optional[str], iana: str) -> str: ...
```

**Implementation notes:**

- `iana_from_coords` wraps `timezonefinder.TimezoneFinder()` with
  a module-level singleton (instantiating is ~30 ms; don't do it
  per call). Catch any exception → log warning → return None.
- Import `timezonefinder` inside a try/except at module top so a
  missing install at deploy time doesn't break unrelated routes —
  fall back to `def iana_from_coords(*_): return None` and log a
  startup warning. (Matches spec's failure-mode row.)
- `is_valid_iana(name)`: `return bool(name) and name in available_timezones()`.
  Cache `available_timezones()` result in a module-level set on
  first call.
- `hours_offset_label(0) == "same time"`. Sign: positive → ahead,
  negative → behind. Half-hour zones format as
  `"5 h 30 min ahead"` / `"9 h 30 min behind"`. Round to nearest
  minute (drop seconds).
- `format_clock_label(city_hint, iana)`: prefix `"🕒 "`. If
  `city_hint` truthy use it; else use the last segment of `iana`
  with underscores replaced by spaces.

**Test list (~17):**

`iana_from_coords` (~4):
- `test_iana_from_coords_paris_returns_europe_paris`
- `test_iana_from_coords_mid_ocean_returns_none`
- `test_iana_from_coords_pole_adjacent_handled`
- `test_iana_from_coords_lookup_exception_returns_none` (mock the
  module-level TF instance to raise)

`is_valid_iana` (~3):
- `test_is_valid_iana_known_zone`
- `test_is_valid_iana_mistyped_zone`
- `test_is_valid_iana_empty_string`

`hours_offset_label` (~7):
- `test_hours_offset_label_zero_same_time`
- `test_hours_offset_label_positive_whole_hours`
- `test_hours_offset_label_negative_whole_hours`
- `test_hours_offset_label_positive_half_hour`
- `test_hours_offset_label_positive_45_min`
- `test_hours_offset_label_negative_half_hour`
- `test_hours_offset_label_one_hour_singular_ok` (verify it says
  `"1 h ahead"` — singular `h` is fine; don't over-engineer
  `"1 hour"`)

`format_clock_label` (~3):
- `test_format_clock_label_with_city_hint`
- `test_format_clock_label_without_city_hint_uses_iana_tail`
- `test_format_clock_label_underscore_in_iana_tail`

**Verify:** `pytest tests/test_destination_clock.py -v` all pass.

**Commit:** `feat: src/destination_clock.py pure helpers + 17 tests`

---

## Task 3: `parse_trip_form` reads + validates `timezone_iana`

**Files:**

- Modify: `src/trip_helpers.py`
- Modify: `tests/test_trip_helpers.py`

**Surface change:**

`parse_trip_form` adds a `timezone_iana` key to its `parsed` dict
and a possible `timezone_iana` key in `errors`:

- Read `(form.get("timezone_iana") or "").strip()`.
- Empty → `parsed["timezone_iana"] = None`.
- Non-empty + `is_valid_iana(value)` → `parsed["timezone_iana"] = value`.
- Non-empty + invalid → `errors["timezone_iana"] = "Not a recognized time zone."`

Import `is_valid_iana` from `src.destination_clock` at the top of
`src/trip_helpers.py`.

**Test list (~4):**

- `test_parse_trip_form_accepts_valid_timezone`
- `test_parse_trip_form_rejects_invalid_timezone`
- `test_parse_trip_form_empty_timezone_becomes_none`
- `test_parse_trip_form_whitespace_only_timezone_becomes_none`

**Verify:** `pytest tests/test_trip_helpers.py -v` green.

**Commit:** `feat: parse_trip_form handles optional timezone_iana`

---

## Task 4: `_ensure_trip_timezone` helper + tests

**Files:**

- Modify: `app.py`
- Modify: `tests/test_routes.py`

**Helper surface (place near `_trip_primary_coords` at line 1661):**

```python
def _ensure_trip_timezone(trip) -> Optional[str]:
    """Lazy derive Trip.timezone_iana from the first geocoded
    booking (by start_datetime). Idempotent — returns the existing
    value if already set. Returns the (now-set) IANA or None."""
```

**Implementation notes:**

- Early return if `trip.timezone_iana` truthy.
- Filter `trip.bookings` to those with both `geocoded_lat` and
  `geocoded_lng` not None. Sort by `(b.start_datetime or
  datetime.max)`. Take the first.
- If none: return None.
- Call `iana_from_coords(b.geocoded_lat, b.geocoded_lng)`.
- If None: return None (don't write).
- Else: set `trip.timezone_iana = iana`, `db.session.commit()`,
  log `logger.info("Derived timezone %s for trip id=%s", iana, trip.id)`,
  return iana.

**Call sites in this task:** none yet. T6 and T7 wire it into
`trip_overview` and `trip_edit`. We test the helper in isolation
here.

**Test list (~5, using the existing in-memory app fixture):**

- `test_ensure_trip_timezone_returns_existing_when_set`
- `test_ensure_trip_timezone_returns_none_when_no_bookings`
- `test_ensure_trip_timezone_returns_none_when_no_geocoded_bookings`
- `test_ensure_trip_timezone_derives_and_persists_from_first_booking`
  (patch `src.destination_clock.iana_from_coords` to return
  `"Europe/Paris"`)
- `test_ensure_trip_timezone_handles_iana_lookup_returning_none`
  (patch returns None; trip stays NULL; no commit failure)

**Verify:** `pytest tests/test_routes.py -k ensure_trip_timezone -v`
green; full suite green.

**Commit:** `feat: _ensure_trip_timezone lazy auto-derive helper + 5 tests`

---

## Task 5: Trip form — timezone_iana input + datalist + preview

**Files:**

- Modify: `app.py` (the `trip_new` and `trip_edit` views)
- Modify: `templates/trip_form.html`
- Modify: `tests/test_routes.py`

**Route changes:**

In both `trip_new` and `trip_edit`:

- Import `COMMON_TIMEZONES` from `src.destination_clock`.
- Pass `common_timezones=COMMON_TIMEZONES` to `render_template`.

In `trip_edit` only:

- Call `_ensure_trip_timezone(trip)` early (after the access check,
  before parsing the form on POST). This populates the column on
  first visit.
- After that, compute `tz_autodetect_preview`: scan bookings for
  the first with coords, run `iana_from_coords`, surface the
  result (or None) to the template. This is **independent** of
  `trip.timezone_iana` so the form can show "We'd auto-detect: X"
  even after the user clears the field.

In `trip_new`: skip the preview (no bookings yet).

Both routes also need to include `timezone_iana` in the data dict
that's passed back to `Trip(...)` / `setattr` so the form save
persists it.

**Template change** in `trip_form.html`, after the currency row:

Insert the markup from the spec (lines under "Trip-form parsing
change"). Wire `value="{{ form.get('timezone_iana', '') }}"`
and the `tz_autodetect_preview` help line.

**Implementation note:** the existing form-data handling pattern
in `trip_new` / `trip_edit` should already iterate `data.items()`
or do an explicit attribute assign. Add `timezone_iana` to the
same surface. Read the current edit handler before editing — it's
the more involved of the two.

**Test list (~5):**

- `test_trip_new_saves_timezone_iana`
- `test_trip_new_rejects_invalid_timezone`
- `test_trip_edit_saves_timezone_iana`
- `test_trip_edit_clears_timezone_when_empty_string_posted`
- `test_trip_edit_get_renders_autodetect_preview_when_tz_null`

**Verify:** `pytest tests/test_routes.py -k 'trip_new or trip_edit' -v`
green; full suite green. Manual smoke:

- Visit `/trips/new`: form shows the new field with the datalist.
- Submit with `Asia/Tokyo`: trip saves, value persists.
- Submit with `Europe/Pariss`: field error renders.
- On `/trips/<id>/edit` for a trip with NULL tz and a geocoded
  booking: column populates and preview text shows.

**Commit:** `feat: trip form — destination time zone with autocomplete`

---

## Task 6: Trip overview hero panel (planning) + server-rendered initial time

**Files:**

- Modify: `app.py` (the `trip_overview` view)
- Modify: `templates/_countdown_hero.html`
- Modify: `static/css/app.css`
- Modify: `tests/test_routes.py`

**Route changes in `trip_overview`:**

- Call `_ensure_trip_timezone(trip)` near the top.
- If `trip.timezone_iana`, compute `initial_dest_time` server-side:
  ```python
  from zoneinfo import ZoneInfo
  try:
      zi = ZoneInfo(trip.timezone_iana)
      initial_dest_time = datetime.now(zi).strftime("%-I:%M %p")
  except Exception:
      initial_dest_time = None
  ```
  (`%-I` is glibc; on macOS / Linux it works. If portability bites,
  switch to `%I` then lstrip a leading `'0'`.)
- Pass `initial_dest_time` to the template.

**Template change** in `_countdown_hero.html`, inside the
`{% if _status == 'planning' %}` branch, after the
`countdown-hero-themed` div, before the closing `</section>`:

Render the spec's `vp-destclock vp-destclock--hero` block. Wire
`data-clock-iana="{{ trip.timezone_iana }}"`,
`data-clock-city="{{ trip.destination or trip.timezone_iana.split('/')[-1].replace('_', ' ') }}"`,
and `data-clock-time="{{ initial_dest_time or '—' }}"`.

The block is guarded by `{% if trip.timezone_iana %}`.

**CSS additions:**

```css
.vp-destclock {
  display: inline-flex;
  align-items: baseline;
  gap: 0.4rem;
  font-variant-numeric: tabular-nums;
}
.vp-destclock--hero {
  font-size: 1rem;
  margin-top: 0.5rem;
  justify-content: center;
}
.vp-destclock--chip {
  font-size: 0.9rem;
  padding: 0.25rem 0.7rem;
  background: var(--vp-surface-2);
  border-radius: 999px;
  margin-bottom: 0.4rem;
}
.vp-destclock__offset {
  font-size: 0.85em;
  color: var(--vp-muted, #6c757d);
}
```

**Test list (~3):**

- `test_trip_overview_renders_clock_panel_when_tz_set`
- `test_trip_overview_skips_clock_panel_when_tz_null`
- `test_trip_overview_auto_derives_timezone_on_first_visit`
  (set up a trip with a geocoded booking + null tz; GET; assert
  tz now populated and the panel is in the body)

**Verify:** Full suite green. Manual smoke: open a planning trip
with a known tz set, watch the seconds tick in the browser.

**Commit:** `feat: 🕒 destination clock panel on planning hero`

---

## Task 7: Today-section clock chip (in_progress) + tests

**Files:**

- Modify: `templates/_today_section.html`
- Modify: `tests/test_routes.py`

**Template change:** inside `_today_section.html`, *above* the
existing `{% if today_forecast %}` block, add:

```jinja
{% if trip.timezone_iana %}
  <div class="vp-destclock vp-destclock--chip"
       data-vp-clock
       data-clock-iana="{{ trip.timezone_iana }}"
       data-clock-city="{{ trip.destination or trip.timezone_iana.split('/')[-1].replace('_', ' ') }}">
    🕒 {{ trip.destination or trip.timezone_iana.split('/')[-1].replace('_', ' ') }}
    · <span data-clock-time>{{ initial_dest_time or '—' }}</span>
    <span class="text-muted small" data-clock-offset></span>
  </div>
{% endif %}
```

No route changes — `initial_dest_time` was already wired in T6.

**Test list (~2):**

- `test_today_section_renders_clock_chip_when_tz_set` — in-progress
  trip with tz set; chip in body.
- `test_today_section_skips_clock_chip_when_tz_null` — in-progress
  trip with no tz; no chip; weather hero (if mocked in) still
  renders.

**Verify:** Full suite green. Manual smoke: mark a trip as
in_progress (or use one) with tz set; chip renders above the
weather hero in the Today section.

**Commit:** `feat: 🕒 destination clock chip in Today section`

---

## Task 8: `destination_clock.js` ticker + base.html include

**Files:**

- Create: `static/js/destination_clock.js`
- Modify: `templates/base.html`

**JS public surface:**

```javascript
// IIFE — mirrors countdown.js.
// On DOMContentLoaded:
//   1. Read viewer IANA via Intl.DateTimeFormat().resolvedOptions().timeZone
//   2. For each [data-vp-clock]: render time + offset once.
//   3. setInterval(1000): re-render the time text only (offset stays).
```

**Implementation notes:**

- `formatTimeForZone(date, iana)`:
  `new Intl.DateTimeFormat([], {timeZone: iana, hour: 'numeric',
  minute: '2-digit'}).format(date)`. Try/catch — on exception,
  hide the clock element (`el.style.display = 'none'`) and log
  a console warning. Return null.
- `computeOffsetMinutes(viewerIana, destIana)`:
  Use two `Intl.DateTimeFormat` calls with `timeZoneName: 'longOffset'`
  formatToParts to extract `GMT±HH:MM` for each, then subtract.
  Returns signed integer minutes. On exception, return null.
- `friendlyOffsetLabel(minutes)`: JS twin of
  `hours_offset_label` — same strings. Wrap with parentheses:
  `"(14 h ahead)"`.
- Wire everything from `DOMContentLoaded`. Bail early if no
  `[data-vp-clock]` on the page.
- Cache offset per-element after first compute — recomputing every
  second is wasteful and `formatToParts` is not cheap.

**base.html change:** add the script tag with `defer`, alongside
the existing `countdown.js` include.

**No new tests** — JS isn't unit-tested in this project, and the
server-rendered `initial_dest_time` is covered by T6.

**Manual smoke:**

- Open `/trips/<id>` for a planning trip with a known tz. Watch
  the seconds tick. Confirm offset matches the real difference
  between your laptop's tz and the destination.
- Open DevTools, set system tz to match the trip (or use a
  trip-tz that matches your system) — offset reads `"(same time)"`.
- Force an invalid tz into the DOM via DevTools (edit the attr to
  `Europe/Pariss`). Clock element should hide itself; console
  warning logged.

**Commit:** `feat: destination_clock.js ticker + offset`

---

## Task 9: Update roadmap + close out

**Files:**

- Modify: `docs/PHASE_3_ROADMAP.md`

**Change:**

- Flip the B2 status row to ✓ shipped.
- Link plan and spec in the same format as A1 / A2 / A3 / B1.

**No tests.**

**Commit:** `docs: mark destination clock (B2) shipped + add spec/plan`

---

## Phase boundary checkpoints

After each task, verify before moving on. Stop here if anything is red.

| After task | Verify |
|---|---|
| T1 | App starts; `sqlite3 vacation.db ".schema trip"` shows `timezone_iana VARCHAR(64)`. |
| T2 | `pytest tests/test_destination_clock.py -v` all pass (~17). |
| T3 | `pytest tests/test_trip_helpers.py -v` (+4 new). |
| T4 | `pytest tests/test_routes.py -k ensure_trip_timezone -v` (~5 new). Full suite green. |
| T5 | `pytest tests/test_routes.py -k 'trip_new or trip_edit' -v` (~5 new). Manual: form round-trip works. |
| T6 | `pytest tests/test_routes.py -k trip_overview -v` (~3 new). Manual: planning hero shows the clock, server-rendered time visible. |
| T7 | Full suite green. Manual: in_progress trip overview shows the chip. |
| T8 | Manual: clock ticks in browser; offset label is correct vs viewer tz; invalid tz hides itself. |
| T9 | Roadmap reflects shipped status. |

---

## Done when

- 9 tasks committed (one commit per task).
- `pytest` green; new test count ≈ **31** (~17 unit on
  destination_clock + ~4 unit on trip_helpers + ~10 integration on
  routes). Suite lands ~598.
- Manual smoke checklists for T5–T8 completed.
- `docs/PHASE_3_ROADMAP.md` B2 row → ✓ shipped, plan + spec links
  populated.

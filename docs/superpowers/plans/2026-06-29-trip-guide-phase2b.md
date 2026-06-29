# Trip-Guide Phase 2b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 4 smaller seeds from the Phase 2a validation notes — top-bar
responsive fold, things_to_do hierarchy re-verify, data-check callouts for
hotel-night gaps, and Mapbox-relevance-aware chip skipping.

**Architecture:** Three small surface tweaks (CSS + emit) plus one new pure
helper module (`src/data_check.py`) plus an in-memory-only extension to
`GeocodeResult.relevance` (no DB migration). Trip-2's compose script is the
end-to-end verification harness for each task. Two-track compose refactor
(seed 5 from the 2026-06-27 note) is OUT OF SCOPE — that gets its own Phase 2c
plan with its own brainstorm.

**Tech Stack:** Python 3.9, Flask-SQLAlchemy, pytest. Composer script
(`scripts/2026-06-27_compose_trip2.py`) and SKILL.md spec
(`.claude/skills/trip-guide/SKILL.md`) move together for each spec-affecting
change.

---

## Background

Two prior validation passes shipped the Phase 2a editorial spine:

- [2026-06-27-trip-guide-phase2a-validation.md](../notes/2026-06-27-trip-guide-phase2a-validation.md) — script-grep verification on Trip-2, all 14 asserts pass
- [2026-06-29-trip-guide-phase2a-validation-eyeball.md](../notes/2026-06-29-trip-guide-phase2a-validation-eyeball.md) — browser eyeball pass, Findings 1 + 6 closed in commits `a232e95` + `4b3ea81`

This plan addresses the 4 outstanding findings (3 from 2026-06-27, 1 from 2026-06-29).

## File Map

| File | State | Responsibility |
|---|---|---|
| `scripts/2026-06-27_compose_trip2.py` | Modify | Top-bar markup + CSS (T1); things_to_do CSS if needed (T2); data-check emit + CSS (T4); confidence-threshold wiring (T6) |
| `.claude/skills/trip-guide/SKILL.md` | Modify | Document data-check callout pattern (T4); document confidence-threshold rule (T6) |
| `src/data_check.py` | Create | Pure helper: detect hotel-night gaps |
| `tests/test_data_check.py` | Create | Unit tests for `find_hotel_night_gaps` |
| `src/geocoding.py` | Modify | Add `relevance: Optional[float]` to `GeocodeResult`, parse from Mapbox response |
| `tests/test_geocoding.py` | Modify | Add tests covering the new field + None-on-cache-hit semantics |
| `src/walking_distance.py` | Modify | Add `min_confidence` param + skip-on-low-confidence behaviour |
| `tests/test_walking_distance.py` | Modify | Tests for the threshold cases |
| `docs/superpowers/notes/2026-06-29-trip-guide-phase2a-validation-eyeball.md` | Modify | Mark closed findings + add T2 verify result |

## Tasks

### Task 1 — Top-bar responsive fold (Finding 7)

**Why:** Eyeball validation found the top sticky bar gets visually crowded
at viewport widths between ~760px and ~920px — breadcrumb + mode toggle + Save
as PDF compete for one row. Existing `@media (max-width: 760px)` rule hides
the entire crumb; the gap is 760–920px.

**Approach (chosen at brainstorm):** Collapse breadcrumb to just `"Trip guide"`
eyebrow below 920px. Wrap the rest in a span; hide the span via CSS at the
mid-breakpoint. The full crumb hide-rule at 760px stays as-is.

**Files:**
- Modify `scripts/2026-06-27_compose_trip2.py:3443-3452` (topbar HTML — wrap the rest of `.crumb` in `<span class="crumb-rest">`)
- Modify same file CSS block (around line 2798–2810 in the existing `@media (max-width: 760px)` zone) — add `@media (max-width: 920px) { .topbar .crumb .crumb-rest { display: none; } }`

**Public surface:** New CSS class `.crumb-rest` (single-purpose hide-target).

**Verify:**
- Regen trip-2 via `.venv/bin/python scripts/2026-06-27_compose_trip2.py`
- `preview_resize` to 800×800 — confirm crumb shows only "Trip guide" and mode-toggle/PDF button have breathing room
- `preview_resize` to 1280×900 — confirm full crumb still shows
- `preview_resize` to 600×800 — confirm entire crumb hidden (existing 760px rule still wins)

**Tests:** None — CSS-only change, covered by visual verify.

**Commit:** `fix(trip-guide): collapse top-bar crumb to eyebrow at 760–920px widths`

---

### Task 2 — Re-verify Finding 4 (things_to_do hierarchy)

**Why:** Pre-Finding-1 the eyeball pass noted that `things_to_do` card titles
were less visually prominent than the neighborhood mono tag below them
(because titles read as plain headings while the tag carried accent color).
The hypothesis was that Finding 1's underline fix (commit `a232e95`) would
restore correct hierarchy.

**Approach:** Eyeball check on the regenerated guide. If hierarchy is now
correct (title dominates), mark Finding 4 closed in the validation note. If
still inverted, bump h5 weight/size in the compose script's CSS.

**Files (conditional — only if still inverted):**
- Modify `scripts/2026-06-27_compose_trip2.py` (CSS for `.ttd-card h5` or equivalent)

**Verify:**
- `preview_eval` scroll to `#things-to-do`
- `preview_screenshot`
- Visual check: is the title the dominant element on each card?

**Tests:** None — eyeball decides.

**Outcome:**
- **If clean:** append a "Task 2 outcome" line to the existing validation note (`docs/superpowers/notes/2026-06-29-trip-guide-phase2a-validation-eyeball.md`) under Finding 4. No commit if no code change beyond the note; otherwise single commit `docs(trip-guide): mark Finding 4 closed after underline fix`.
- **If still inverted:** small CSS tweak to bump h5 weight from 400→600 or size from 1em→1.05em, regen, re-verify, commit as `fix(trip-guide): bump things_to_do card title weight for visual hierarchy`.

---

### Task 3 — Pure helper: detect hotel-night gaps

**Why:** Trip-2's Bergen booking ends 2026-08-28 morning but the user clearly
stayed Bergen the night of 08-28 (Day 15 has Bergen activity). Per spec,
`hotel_for_night` returns None for 08-28. The chip-skip is correct per data;
the data is what's off. Surfacing this as a callout lets the user spot
bookings-data inconsistencies they wouldn't otherwise see.

**Files:**
- Create `src/data_check.py`
- Create `tests/test_data_check.py`

**Public surface:**

```python
@dataclass(frozen=True)
class HotelNightGap:
    day_date: date          # the night with no hotel coverage
    day_number: int         # 1-indexed day number within trip
    reason: str             # one-line human-readable hint

def find_hotel_night_gaps(
    bookings: Iterable,             # rows with booking_type + start_datetime + end_datetime
    itinerary_items: Iterable,      # rows with day_date
    trip_start: date,
    trip_end: date,
) -> List[HotelNightGap]:
    ...
```

**Gap definition:** A `day_date` is a gap when ALL of:
1. `trip_start <= day_date < trip_end` (the trip's nights, exclusive of last day)
2. `hotel_for_night(bookings, day_date)` returns `None`
3. The day has ≥1 itinerary item with `day_date == day_date` OR a non-hotel booking overlapping (flight on that day, restaurant booking that day, etc.)

Days with no hotel AND no activity (true transit days where the user is in
the air or on a ferry) are NOT gaps — they're expected.

**Test list (names only):**

- `test_returns_empty_when_all_nights_covered`
- `test_returns_empty_when_no_bookings_no_itinerary`
- `test_detects_single_hotel_gap_with_itinerary_on_that_day`
- `test_skips_transit_day_with_no_activity`
- `test_skips_check_out_morning_when_user_actually_left` (true transit)
- `test_detects_multiple_gaps_returned_in_date_order`
- `test_day_number_correct_relative_to_trip_start`
- `test_reason_string_mentions_the_day_and_why`
- `test_handles_empty_bookings_iterable`
- `test_inclusive_exclusive_boundary_correct` (last-day-no-night)

**Commit:** `feat(data_check): add find_hotel_night_gaps pure helper`

---

### Task 4 — Emit data-check callout in day_by_day

**Why:** Surface T3's gaps in the rendered guide as a small `.data-check-note`
callout inside the affected day's card-group. Amber-ish styling signals
"verify your data" without alarming the reader.

**Files:**
- Modify `scripts/2026-06-27_compose_trip2.py` — import `find_hotel_night_gaps`, call once before emit, lookup-by-day-date inside `emit_day_by_day`, render callout where applicable. Add `.data-check-note` CSS rule near `.opnote` styling.
- Modify `.claude/skills/trip-guide/SKILL.md` — document the pattern in the `day_by_day` content model section AND in the Walking-distance chips section (cross-reference: chip-skip + data-check-callout fire together when hotel_for_night returns None).

**Public surface (compose-script-local):**

```python
# At compose time, BEFORE emit_day_by_day:
gaps = find_hotel_night_gaps(bookings_db_rows, itinerary_db_rows, trip.start_date, trip.end_date)
gaps_by_date = {g.day_date: g for g in gaps}
# Pass gaps_by_date into emit_day_by_day, which emits .data-check-note for any day matching
```

**CSS shape (illustrative — final colors picked at compose time):**

```css
.data-check-note {
  margin: 12px 0;
  padding: 10px 14px;
  background: rgba(212, 162, 76, 0.08);   /* faint amber tint */
  border-left: 3px solid #d4a24c;
  font-family: var(--font-mono);
  font-size: 0.85em;
  color: var(--ink-soft);
}
.data-check-note::before { content: "⚠ Data check · "; color: #d4a24c; }
```

**Verify:**
- Regen trip-2 — expect ≥1 data-check callout on Day 15 (the 2026-08-28 Bergen gap)
- `grep -c 'data-check-note' data/guides/2.html` → ≥1
- Eyeball in browser: callout reads as informational, not alarming

**Tests:** Pure-helper coverage is in T3; the emit path is covered by the visual verify and the markup-grep audit at the end of the compose script (extend the audit to count `.data-check-note` instances).

**SKILL.md additions:**

Add a new short subsection under `day_by_day` content model:

> **Data-check callout.** When the `hotel_for_night` helper returns None on
> a day that has activity (itinerary items or non-hotel bookings overlapping),
> emit a `<div class="data-check-note">` inside that day's card group with
> the gap reason. This catches bookings-data holes (a hotel that ends a day
> early, an unbooked night between two hotels) the user may not have noticed.

Cross-reference from the Walking-distance chips section's "Hotel resolution per
day" subsection: "On gap days the chip skips per the existing rule AND a
`data-check-note` surfaces — see day_by_day content model."

**Commit:** `feat(trip-guide): emit data-check callout on hotel-night gaps + SKILL.md`

---

### Task 5 — Add `relevance` to GeocodeResult (in-memory only)

**Why:** Mapbox returns a `relevance` field (0.0–1.0) per feature indicating
how confidently the response matched the query. Below ~0.7 the result is
usually a city-centroid fallback rather than the actual venue. Surfacing this
through `GeocodeResult` lets the composer make threshold decisions.

**Files:**
- Modify `src/geocoding.py:27-32` — `GeocodeResult` dataclass
- Modify `src/geocoding.py:87` — Mapbox parse path (`feat = features[0]`) to read `feat.get('relevance')`
- Modify `tests/test_geocoding.py` — add coverage for the new field

**Public surface (after change):**

```python
@dataclass
class GeocodeResult:
    lat: float
    lng: float
    city: Optional[str]
    country_code: Optional[str]
    relevance: Optional[float] = None    # NEW — None on cache hits or non-Mapbox providers
```

**Design choice — no DB migration.** `GeocodeCache` columns are unchanged.
Relevance is populated only on the cache-miss path that calls Mapbox. On a
cache hit, `relevance` returns None. The composer treats None as
"trusted/legacy" — see T6 for the threshold rule. To force re-evaluation,
manually `DELETE FROM geocode_cache WHERE location_text_normalized = ...` and
re-run.

**Test list (names only):**

- `test_relevance_populated_from_mapbox_response_when_present`
- `test_relevance_defaults_to_none_when_missing_from_response`
- `test_cache_hit_returns_geocoderesult_with_relevance_none`
- `test_geocoderesult_is_backward_compatible_with_callers_ignoring_relevance`

**Commit:** `feat(geocoding): surface Mapbox relevance on GeocodeResult`

---

### Task 6 — Confidence-threshold gating in walking_chip + composer

**Why:** Use T5's relevance field to skip chips on low-confidence venues.
A "24 min walk · 2.0km from X" chip is misleading when the venue coord is
actually a city-centroid fallback.

**Approach (chosen at brainstorm):** Skip the chip entirely when
relevance is known and below threshold. Soften-the-label path is rejected
for simplicity.

**Files:**
- Modify `src/walking_distance.py:38` — extend `walking_chip` signature
- Modify `tests/test_walking_distance.py` — add threshold cases
- Modify `scripts/2026-06-27_compose_trip2.py` — geocode_all_venues should return relevance alongside coords; emit_walking_chip_for_card threads it through
- Modify `.claude/skills/trip-guide/SKILL.md` — document the rule in the Walking-distance chips section

**Public surface (after change):**

```python
def walking_chip(
    venue_coords: Optional[Tuple[float, float]],
    hotel_coords: Optional[Tuple[float, float]],
    hotel_name: str,
    *,
    venue_confidence: Optional[float] = None,
    min_confidence: float = 0.7,
) -> str:
    """Return the chip HTML, or empty string if any coord is None
    OR if venue_confidence is known and below min_confidence.
    Confidence=None is treated as 'trusted' (cache-hit / non-Mapbox).
    """
```

**Threshold semantics:**

| `venue_confidence` value | Behaviour |
|---|---|
| `None` | Trust — render chip (cache hits + non-Mapbox sources) |
| `>= min_confidence` (default 0.7) | Render chip |
| `< min_confidence` | Skip chip (return empty string) |

**Composer wiring (compose-script changes):**

Today `venue_coords` is a `Dict[str, Tuple[float, float]]`. Change to
`Dict[str, Tuple[float, float, Optional[float]]]` — third element is
relevance. Update `geocode_all_venues()` to read `result.relevance` and store
it. Update `emit_walking_chip_for_card()` to unpack the third element and pass
as `venue_confidence`. (Alternative: a parallel `venue_relevance: Dict[str, float]`
dict — choose whichever reads cleaner during execution.)

**Test list (names only):**

- `test_renders_chip_when_confidence_above_threshold`
- `test_skips_chip_when_confidence_below_threshold`
- `test_renders_chip_when_confidence_none_legacy_trusted`
- `test_renders_chip_at_exact_threshold_boundary`
- `test_min_confidence_param_overrides_default`
- `test_other_skip_paths_still_work_with_confidence_passed`

**Verify on trip-2:**

- Regen, audit chip count — expected to drop somewhat as low-confidence
  venues (per the 2026-06-27 note: "Fruene Coffee", "Tim Wendelboe", any
  city-centroid fallbacks) lose their chips
- Eyeball: chip-bearing day_by_day cards still feel anchored to a hotel; the
  ones that no longer have chips read fine without them
- Capture before/after chip counts in the commit message

**SKILL.md additions:**

Add a new subsection to Walking-distance chips, after "Geocoding reuses
existing infrastructure":

> **Confidence threshold.** `walking_chip` accepts an optional
> `venue_confidence` (float 0.0–1.0, defaults to None). When venue
> confidence is known AND below `min_confidence` (default 0.7), the chip
> is skipped — same path as None-coord skip. The threshold guards against
> Mapbox city-centroid fallbacks, where the chip distance would be wrong
> by kilometres. Confidence=None is treated as trusted (legacy / cache-hit
> rows).

**Commit:** `feat(walking_distance): skip chips on low-confidence venue geocodes`

---

## Self-Review

Spec coverage:
- Finding 7 (top-bar fold) → Task 1 ✓
- Finding 4 (things_to_do hierarchy re-verify) → Task 2 ✓
- Data-check callout (2026-06-27 Obs 3) → Tasks 3 + 4 ✓
- Geocoder confidence (2026-06-27 Obs 4) → Tasks 5 + 6 ✓
- Two-track compose refactor (2026-06-27 Obs 5) → OUT OF SCOPE, parked for Phase 2c ✓

Type consistency: `find_hotel_night_gaps` in T3 returns `List[HotelNightGap]` —
T4's emit calls it via `find_hotel_night_gaps(bookings_db_rows, itinerary_db_rows, ...)`
and indexes by `g.day_date` (matches T3 dataclass field). `GeocodeResult.relevance`
in T5 (`Optional[float]`) feeds T6's `venue_confidence` param (also
`Optional[float]`). `walking_chip` signature in T6 adds keyword-only params
after the existing positional ones — backwards-compatible.

Placeholder scan: no "TBD" / "TODO" / "implement later" remain. Each task names
exact files, public surfaces, test names, verify steps, and commit message.

Total: 6 tasks, ~330 lines. Comfortably under the 17-task / 1000-line caps.

---

## Out of scope (parked for Phase 2c)

**Two-track compose refactor** (2026-06-27 Obs 5). The skill's `compose()` step
should adopt a Python-data + central-emit-helpers pattern rather than authoring
HTML inline. Substantial architectural refactor with deep ripple effects
across SKILL.md + every existing compose path. Requires its own brainstorm to
decide: extract emit helpers into `src/guide_emit.py` shared module vs.
per-trip composer files? How does the skill prompt invoke them?

Write Phase 2c plan in a fresh session after Phase 2b ships.

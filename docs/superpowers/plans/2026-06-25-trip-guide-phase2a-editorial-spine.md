# Trip Guide Phase 2a — Editorial Spine Refinements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two-tier hyperlink rule (practical links allowed in card grids and tables, citation links restricted to bibliography + Go-deeper cards, atmospheric body prose stays link-free) and walking-distance-from-hotel chips on `day_by_day` site cards and single-hotel `things_to_do` entries.

**Architecture:** Three new pure-helper modules in `src/` (`place_links`, `walking_distance`, `geocoding`) + one extension to `src/trip_helpers.py` (`hotel_for_night`) + one new field on `GuideConfig` (`geocode_cache`) + four SKILL.md documentation edits. No DB schema change, no Flask route change, no template change.

**Tech Stack:** Python 3.9 (no `X | Y` union syntax — use `Optional[X]`), Flask + SQLAlchemy + SQLite, pytest, `requests` (already a dep), Mapbox (already wired through `MAPBOX_TOKEN` and `src/geocoding.py`).

**Spec:** [docs/superpowers/specs/2026-06-25-trip-guide-phase2a-editorial-spine-design.md](../specs/2026-06-25-trip-guide-phase2a-editorial-spine-design.md). Every locked design decision lives there. This plan does not restate them — it points at them.

---

## Pivot note (after Task 2 shipped)

The v1 plan included Task 3 (new Nominatim-based `src/geocoding.py`)
and Task 5 (new `GuideConfig.geocode_cache` JSON field). When the
implementer started Task 3, they discovered the project **already
has** `src/geocoding.py` using Mapbox, a `GeocodeCache` DB table,
and `Booking.geocoded_lat / geocoded_lng / geocoded_city /
geocoded_country_code` columns auto-populated by
`ensure_geocoded()`. Building parallel infra would have been
wasteful and conflicting.

**Tasks 3 and 5 are removed.** Task numbers 1, 2, 4, 6 are preserved
(matches the v1 commit messages for Tasks 1 and 2 already on `main`).
Task 4 gets a small wording tweak (composer reads
`booking.geocoded_lat/lng` directly). Task 6's Step 6.5 collapses to
a few existing-helper calls.

**New end state:** 987/987 tests (was 995/995 in v1). 4 remaining
tasks instead of 6 — Tasks 1 and 2 already shipped, leaving Tasks 4
and 6.

See the spec's "Revision note" for the design rationale.

---

## File map

| Path | Action | Responsibility |
|---|---|---|
| `src/place_links.py` | **Done (Task 1)** | Build Google Maps search URLs and the practical-link HTML snippet. Pure, no network. |
| `tests/test_place_links.py` | **Done (Task 1)** | 6 tests covering `maps_url` and `practical_link`. |
| `src/walking_distance.py` | **Done (Task 2)** | Haversine math + chip formatting (≤2km / 2–5km / >5km adaptive). Pure. |
| `tests/test_walking_distance.py` | **Done (Task 2)** | 9 tests covering `haversine_km` and `walking_chip`. |
| `src/trip_helpers.py` | Modify | Add `hotel_for_night(bookings, date)` helper. |
| `tests/test_trip_helpers.py` | Modify | Add 4 tests for `hotel_for_night`. |
| `.claude/skills/trip-guide/SKILL.md` | Modify | Two new top-level sections + revise Task 6 anti-pattern + four new Step 10 verification asserts + Step 6.5 (existing-helper invocation). |

End state: **987/987 tests green** (968 baseline + 6 from Task 1 + 9 from Task 2 + 4 from Task 4 = 987; the SKILL.md task adds no tests).

---

## Task ordering

Pure helpers first, smallest to largest, each independently testable. Then the `GuideConfig` field. Then SKILL.md updates. This order means tasks 1–4 can be reviewed and merged in any order without dependency; tasks 5–6 reference the now-existing helpers.

---

## Task 1 — `src/place_links.py`

**Files:**
- Create: `src/place_links.py`
- Create: `tests/test_place_links.py`

**Public surface:**

```python
def maps_url(name: str, city: str) -> str:
    """Google Maps search URL for `name` in `city`. Uses urllib.parse.quote."""

def practical_link(name: str, city: str) -> str:
    """<a class="practical-link" href="<maps_url>" rel="noopener" target="_blank">{html-escaped name}</a>"""
```

**Implementation notes:**
- `maps_url`: combine `f"{name}, {city}"`, `urllib.parse.quote(query, safe="")`, prepend `https://www.google.com/maps/search/?api=1&query=`.
- `practical_link`: use `html.escape(name)` on the link text only (the URL is already URL-encoded). Hard-code `class="practical-link"`, `rel="noopener"`, `target="_blank"`.
- No external dependencies beyond `urllib.parse` and `html` (stdlib).

**Test names** (one assertion each, no shared helpers needed):
- `test_maps_url_builds_google_search_query`
- `test_maps_url_url_encodes_punctuation`
- `test_maps_url_url_encodes_unicode`
- `test_practical_link_includes_rel_noopener`
- `test_practical_link_escapes_html_in_name`
- `test_practical_link_target_blank`

**Verify:** `.venv/bin/pytest tests/test_place_links.py -q` → 6 passed. Full suite: `.venv/bin/pytest tests/ -q` → 974/974.

**Commit:** `feat(place_links): add maps_url + practical_link helpers`

---

## Task 2 — `src/walking_distance.py`

**Files:**
- Create: `src/walking_distance.py`
- Create: `tests/test_walking_distance.py`

**Public surface:**

```python
from typing import Optional, Tuple

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""

def walking_chip(
    venue_coords: Optional[Tuple[float, float]],
    hotel_coords: Optional[Tuple[float, float]],
    hotel_name: str,
) -> str:
    """Chip HTML or '' when either coord is None. See spec decisions 2 + 4."""
```

**Implementation notes:**
- `haversine_km` uses `math.radians`, `math.sin`, `math.cos`, `math.atan2`, `math.sqrt`. Earth radius constant `6371.0` km defined at module top with comment naming the source assumption.
- `walking_chip`:
  - Return `""` if `venue_coords is None or hotel_coords is None`.
  - Compute `km_straight = haversine_km(*venue_coords, *hotel_coords)`.
  - `km_route = km_straight * 1.3` (street multiplier per spec decision 2).
  - `walk_min = math.ceil(km_route / 5.0 * 60)` (5 km/h pace, ceil to minute).
  - `drive_min = math.ceil(km_route / 30.0 * 60)` (30 km/h in-city driving pace).
  - Format band (spec decision 4):
    - `km_route <= 2.0`: `<span class="walkchip">{walk_min} min walk · {km_route:.1f}km from {hotel}</span>`
    - `2.0 < km_route <= 5.0`: `<span class="walkchip">{walk_min} min walk · {km_route:.1f}km · or {drive_min} min by car from {hotel}</span>`
    - `km_route > 5.0`: `<span class="walkchip">{drive_min} min by car · {km_route:.1f}km from {hotel}</span>`
  - HTML-escape `hotel_name` via `html.escape`.

**Test names:**
- `test_haversine_km_known_landmark_pair` (e.g. Vatican → Colosseum, expected ~2.5km ± 0.2)
- `test_haversine_km_zero_for_same_point`
- `test_haversine_km_symmetric`
- `test_walking_chip_under_2km_format`
- `test_walking_chip_2_to_5km_format`
- `test_walking_chip_over_5km_format`
- `test_walking_chip_returns_empty_on_none_venue_coords`
- `test_walking_chip_returns_empty_on_none_hotel_coords`
- `test_walking_chip_html_escapes_hotel_name`

**Verify:** `.venv/bin/pytest tests/test_walking_distance.py -q` → 9 passed. Full suite: 983/983.

**Commit:** `feat(walking_distance): add haversine + adaptive chip helpers`

---

## ~~Task 3 — `src/geocoding.py`~~ REMOVED (see Pivot note)

The project already has `src/geocoding.py` using Mapbox. We reuse
the existing `geocode_with_cache(text, db_session, token)` and
`ensure_geocoded(rows, db_session, token)`. No new module.

---

## Task 4 — Extend `src/trip_helpers.py` with `hotel_for_night`

**Files:**
- Modify: `src/trip_helpers.py` (add one function alongside the existing pure helpers)
- Modify: `tests/test_trip_helpers.py` (append 4 tests)

**Public surface:**

```python
import datetime
from typing import List, Optional
from models import Booking  # already imported elsewhere in this file

def hotel_for_night(
    bookings: List[Booking],
    date: datetime.date,
) -> Optional[Booking]:
    """Return the hotel booking whose stay covers the night of `date`.

    Semantics: a hotel booking with check-in start_date and check-out end_date
    covers nights where start_date <= date < end_date. The night of the
    check-out date is NOT spent at that hotel.

    Returns None when no booking covers `date`. Returns the first match when
    two bookings overlap (logs a warning).
    """
```

**Implementation notes:**
- The `Booking` model has `type` (str), `start_date` (date), `end_date` (date). The hotel-night semantics are spec decision §5 — check-out date is NOT a night.
- Walk `bookings` in input order. Match condition:
  - `booking.type == "hotel"`
  - `booking.start_date is not None and booking.end_date is not None`
  - `booking.start_date <= date < booking.end_date`
- Track matches; if more than one, log `logger.warning("multiple hotels cover night %s: %s", date, [b.id for b in matches])` and return the first.
- If no match, return `None`.
- This is the only place in this plan that touches the SQLAlchemy model — function takes plain Booking instances and reads attributes, no queries.

**Test names** (use existing fixtures in `tests/test_trip_helpers.py` for `make_booking`; if no factory exists, build one locally with `types.SimpleNamespace`):
- `test_hotel_for_night_picks_covering_booking`
- `test_hotel_for_night_returns_none_when_no_coverage`
- `test_hotel_for_night_excludes_checkout_night`
- `test_hotel_for_night_picks_first_when_overlapping_logs_warning` (uses `caplog`)

**Verify:** `.venv/bin/pytest tests/test_trip_helpers.py -q` → previous test count + 4 passed. Full suite: 987/987.

**Commit:** `feat(trip_helpers): add hotel_for_night helper`

---

## ~~Task 5 — Add `geocode_cache` to `GuideConfig`~~ REMOVED (see Pivot note)

Coordinates are already persisted in the existing `GeocodeCache` DB
table (for venue lookups) and `Booking.geocoded_lat / geocoded_lng`
columns (for hotels). No new `GuideConfig` field. No new JSON sidecar
key. No new migration.

---

## Task 6 — SKILL.md: practical-hyperlinks + walking-distance + Task 6 revision + Step 10 updates

**Files:**
- Modify: `.claude/skills/trip-guide/SKILL.md`

**Where edits land:**

1. **New top-level section `## Practical hyperlinks`** between `## Source disclosure` and `## The 10-step flow`. Cover, in this order:
   - The two-tier rule restated (citation vs practical, where each appears) — see spec §"Locked design decisions" decision 1.
   - The link CSS verbatim — see spec §"Locked design decisions" decision 7.
   - Helper signatures — `maps_url(name, city)` and `practical_link(name, city)` from `src/place_links.py`. Show the one-line import the composer uses: `from src.place_links import practical_link`.
   - The `rel="noopener"` + `target="_blank"` convention with one-sentence rationale (security + UX).
   - Anti-patterns: no inline citation markers in body prose, no external-link glyphs (`↗`), no Apple-Maps user-agent rewriting, no links in atmospheric prose.

2. **Revise the "no URL citations in body prose" anti-pattern** in the existing `## Source disclosure` section. Currently reads:

   > No URL citations in body prose — they go in the consolidated "Sources & further reading" section only.

   Replace with the wording in spec §"SKILL.md changes" item 2 — the new two-paragraph form distinguishing citation URLs (still restricted) from practical URLs (now allowed in specific surfaces, with a cross-link to the new `## Practical hyperlinks` section).

3. **New top-level section `## Walking-distance chips`** between `## Practical hyperlinks` and `## The 10-step flow`. Cover, in this order:
   - The math: haversine + 1.3× street multiplier + 5 km/h walking / 30 km/h driving + ceil to nearest minute. Reference spec decisions 2 + 4.
   - The three adaptive format bands (≤2km, 2–5km, >5km) with one example each.
   - Hotel-per-day resolution: cite `hotel_for_night(bookings, date)`. Document that the check-out night is NOT the hotel night.
   - Single-hotel-vs-multi-hotel rule for `things_to_do` (decision 5).
   - Geocode cache lifecycle: cache lives on `GuideConfig.geocode_cache`, key is `"<name>::<city>"`, persisted via `save_config`. Document that second regeneration is offline if no new venues appear.
   - Nominatim politeness rules: 1 req/sec, custom `User-Agent`, no parallel requests. Cite the OSM usage policy URL: `https://operations.osmfoundation.org/policies/nominatim/`.

4. **New `### Step 6.5: Ensure coordinates`** inside `## The 10-step flow`, between Step 6 and Step 7. Composer:
   - Calls `ensure_geocoded(bookings, db_session=db.session, token=MAPBOX_TOKEN)` once to fill in any missing hotel coords (Booking.geocoded_lat / lng).
   - For each named venue about to render in a practical surface, calls `geocode_with_cache(text=f"{name}, {city}", db_session=db.session, token=MAPBOX_TOKEN)` and keeps the returned `GeocodeResult` alongside the venue data.
   - If `MAPBOX_TOKEN` is empty, logs a warning and skips both steps — chips won't render but the guide still composes.

5. **Modify Step 7 (Compose the HTML)** to add the practical-link wrapping rule and the walking-chip emission rule. Cite the helper imports and the `.tags` row placement on day_by_day site cards.

6. **Step 10 verification additions** (append to existing list of asserts):
   - Every bibliography entry is an `<a>` tag.
   - Every "Go deeper" card title is an `<a>` tag (or the card is omitted per Task 6 no-fabricated-sources rule).
   - Every named venue in `things_to_do`, `food` (where to eat), `day_by_day` site cards, and `field_guide` landmark/museum entries has a Google Maps link (`a.practical-link[href*="google.com/maps"]`).
   - Atmospheric body prose (history paragraphs, day intros, food culture intros) contains zero `<a>` tags — grep should find none under `.section--atmospheric > p`.
   - Walking-distance chips render on `day_by_day` site cards on days where `hotel_for_night` resolves AND both endpoints geocoded.
   - "Hotels at a glance" addresses are clickable.

**Implementation notes:**
- This is a docs-only task — no Python changes, no new tests. Verification is "the new sections fence cleanly, the markdown still renders, the suite stays at 994/994."
- Expected line addition to SKILL.md: ~200 lines. Final length ~1760, well under any practical limit (SKILL.md has no enforced cap).

**Verify:** `.venv/bin/pytest tests/ -q` → 987/987 (unchanged from Task 4 end state). `grep -c "^## " .claude/skills/trip-guide/SKILL.md` should be exactly 2 higher than before this task.

**Commit:** `docs(trip-guide): practical hyperlinks + walking-distance chips + step 6.5`

---

## Cross-task type/signature consistency

The signatures used in Task 6 must match exactly what's defined in
tasks 1, 2, and 4. Pinned forms:

- `maps_url(name: str, city: str) -> str` (Task 1, done)
- `practical_link(name: str, city: str) -> str` (Task 1, done)
- `haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float` (Task 2, done)
- `walking_chip(venue_coords: Optional[Tuple[float, float]], hotel_coords: Optional[Tuple[float, float]], hotel_name: str) -> str` (Task 2, done)
- `hotel_for_night(bookings: List[Booking], date: datetime.date) -> Optional[Booking]` (Task 4)

Existing helpers Task 6 references (do NOT redefine):

- `geocode_with_cache(text: str, *, db_session, token: str) -> Optional[GeocodeResult]`
- `ensure_geocoded(rows: Iterable, *, db_session, token: str) -> None`
- `GeocodeResult` dataclass with `.lat`, `.lng`, `.city`, `.country_code` attributes
- `Booking.geocoded_lat`, `.geocoded_lng`, `.geocoded_city`, `.geocoded_country_code` columns

Any deviation in implementation is a plan failure — fix the plan or fix the code, but make them match.

---

## Spec coverage check (self-review)

| Spec section | Plan task(s) |
|---|---|
| §"Locked design decisions" 1 (two-tier rule) | Tasks 1, 6 |
| §"Locked design decisions" 2 (walking distance math) | Task 2 |
| §"Locked design decisions" 3 (Mapbox + existing cache) | Task 6 (composer calls existing helpers) |
| §"Locked design decisions" 4 (adaptive chip format) | Task 2 |
| §"Locked design decisions" 5 (hotel resolution per day + single/multi rule) | Tasks 4, 6 |
| §"Locked design decisions" 6 (Google Maps URL target) | Task 1 |
| §"Locked design decisions" 7 (link styling) | Task 6 |
| §"Architecture" → `src/place_links.py` | Task 1 |
| §"Architecture" → `src/walking_distance.py` | Task 2 |
| §"Architecture" → `src/geocoding.py` (existing, reused) | Task 6 |
| §"Architecture" → `hotel_for_night` extension | Task 4 |
| §"Architecture" → cache shape (existing, reused) | Task 6 |
| §"Architecture" → composer integration (Step 6.5, Step 7 additions) | Task 6 |
| §"Architecture" → SKILL.md changes (4 items) | Task 6 |
| §"Edge cases" (Mapbox no result, network failure, MAPBOX_TOKEN missing, hotel night unresolved, multi-hotel things_to_do, same venue cached, print mode, reduced motion) | Tasks 2, 4 (helper behaviour); Task 6 (composer behaviour + docs) |
| §"Testing approach" (19 new tests across 3 test files) | Tasks 1, 2, 4 |
| §"Acceptance criteria" 1–7 | All tasks together; Step 10 asserts in Task 6 |

No gaps.

---

## Out of scope

These belong to **Plan 2b — Visual primitives toolkit** (a separate plan, not yet written):
- `era_chip`, `swimlane_timeline`, `phenology_strip`, `silhouette_svg`, `climate_strip`, `size_comparison_panel`, `geology_section_svg`, `stratigraphic_stack` SVG helpers.
- Reusable `<defs>` icon library for IUCN status pills, endemic globe, period glyphs.
- viewBox sizing convention, color-variable substitution mechanism, silhouette path data registry.

These belong to **Phase 3** (`docs/superpowers/plans/2026-06-23-trip-guide-depth.md` §"Phase 3 stub"):
- Habitat-first field guide rewrite, sidenote system, character vignettes, histpin, `quick_reference` 9th section, fixed-bottom SOS overlay, day-of auto-scroll, place-card tap-action row, `twovoices` module.

---

## Done definition

- 987/987 tests green via `.venv/bin/pytest tests/ -q`.
- Tasks 1, 2 already on `main`. Tasks 4, 6 still to commit. Plus the
  spec + plan v2 revision commit.
- SKILL.md has two new top-level sections (Practical hyperlinks and
  Walking-distance chips), a revised Task 6 anti-pattern, a new
  Step 6.5, and four new Step 10 verification asserts.
- The existing Mapbox geocoder + `GeocodeCache` table + Booking
  geocoded_* columns are reused as-is. No new geocoding code, no new
  cache infrastructure.
- Plan 2b can be brainstormed next; the existing geocoder + cache are
  ready for `era_chip` and other Plan 2b helpers to reuse.

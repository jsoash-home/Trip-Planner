# Trip Guide Phase 2a — Editorial Spine Refinements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two-tier hyperlink rule (practical links allowed in card grids and tables, citation links restricted to bibliography + Go-deeper cards, atmospheric body prose stays link-free) and walking-distance-from-hotel chips on `day_by_day` site cards and single-hotel `things_to_do` entries.

**Architecture:** Three new pure-helper modules in `src/` (`place_links`, `walking_distance`, `geocoding`) + one extension to `src/trip_helpers.py` (`hotel_for_night`) + one new field on `GuideConfig` (`geocode_cache`) + four SKILL.md documentation edits. No DB schema change, no Flask route change, no template change.

**Tech Stack:** Python 3.9 (no `X | Y` union syntax — use `Optional[X]`), Flask + SQLAlchemy + SQLite, pytest, `requests` (already a dep, used by `app.py`), Nominatim (OpenStreetMap geocoder, free, public endpoint, 1 req/sec rate limit).

**Spec:** [docs/superpowers/specs/2026-06-25-trip-guide-phase2a-editorial-spine-design.md](../specs/2026-06-25-trip-guide-phase2a-editorial-spine-design.md). Every locked design decision lives there. This plan does not restate them — it points at them.

---

## File map

| Path | Action | Responsibility |
|---|---|---|
| `src/place_links.py` | Create | Build Google Maps search URLs and the practical-link HTML snippet. Pure, no network. |
| `tests/test_place_links.py` | Create | 6 tests covering `maps_url` and `practical_link`. |
| `src/walking_distance.py` | Create | Haversine math + chip formatting (≤2km / 2–5km / >5km adaptive). Pure. |
| `tests/test_walking_distance.py` | Create | 9 tests covering `haversine_km` and `walking_chip`. |
| `src/geocoding.py` | Create | Nominatim wrapper with cache-first lookup, 1 req/sec rate limit, fail-soft. Only module with network. |
| `tests/test_geocoding.py` | Create | 7 tests, all with `requests` mocked. Suite stays offline. |
| `src/trip_helpers.py` | Modify | Add `hotel_for_night(bookings, date)` helper. |
| `tests/test_trip_helpers.py` | Modify | Add 4 tests for `hotel_for_night`. |
| `src/guide_builder.py` | Modify | Add `geocode_cache: Dict[str, List[float]]` field on `GuideConfig` (default-factory empty dict). Add `tests/test_guide_builder.py` round-trip assertion that the field persists. |
| `tests/test_guide_builder.py` | Modify | One new test for `geocode_cache` round-trip. |
| `.claude/skills/trip-guide/SKILL.md` | Modify | Two new top-level sections + revise Task 6 anti-pattern + four new Step 10 verification asserts. |

End state: **995/995 tests green** (968 current + 27 new — `6+9+7+4` from the helper modules and `1` from the `guide_builder` round-trip; the SKILL.md tasks add no tests). The spec's "26 new tests" headline number plus the round-trip test introduced in Task 5 below.

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

## Task 3 — `src/geocoding.py`

**Files:**
- Create: `src/geocoding.py`
- Create: `tests/test_geocoding.py`

**Public surface:**

```python
from typing import Dict, List, Optional, Tuple

def geocode(
    name: str,
    city: str,
    cache: Dict[str, List[float]],
) -> Optional[Tuple[float, float]]:
    """Cache-first Nominatim lookup. Returns (lat, lon) or None on no-match / network error."""
```

**Implementation notes:**
- Module constants at top:
  - `NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"`
  - `USER_AGENT = "vacation-planner/0.1 (jeffsoash@gmail.com)"`
  - `RATE_LIMIT_SECONDS = 1.0`
- Cache key shape: `f"{name}::{city}"`. Cache value: 2-element `[lat, lon]` list (JSON-safe; the in-memory return is a `Tuple[float, float]`).
- Flow:
  1. Look up cache key; if hit, return `(cache[key][0], cache[key][1])` immediately, no network, no sleep.
  2. Cache miss: GET `NOMINATIM_URL` with params `{"q": f"{name}, {city}", "format": "json", "limit": 1}` and headers `{"User-Agent": USER_AGENT}`. Wrap in `try/except requests.RequestException`; on any exception, log a warning and return `None`.
  3. Parse JSON. If list is empty, return `None` (do NOT write to cache — leaves room for retry on the next run).
  4. Extract `lat = float(result[0]["lat"])`, `lon = float(result[0]["lon"])`. Catch `(KeyError, ValueError)` around the float coerce; on failure, log warning and return `None`.
  5. Write `cache[key] = [lat, lon]`.
  6. `time.sleep(RATE_LIMIT_SECONDS)` BEFORE returning (so two back-to-back calls are paced).
  7. Return `(lat, lon)`.
- The caller owns persistence of `cache` to the config sidecar (see Task 4 and Task 6).

**Test names** (all use `unittest.mock.patch` on `src.geocoding.requests.get` and `src.geocoding.time.sleep`):
- `test_geocode_cache_hit_returns_cached_no_network`
- `test_geocode_cache_miss_calls_nominatim_mocked`
- `test_geocode_empty_result_returns_none`
- `test_geocode_empty_result_does_not_write_to_cache`
- `test_geocode_writes_to_cache_on_success`
- `test_geocode_network_error_returns_none`
- `test_geocode_sleeps_after_real_call`

The suite MUST stay offline. Verify locally by running tests with the network unplugged (or with `requests` raising in the mock).

**Verify:** `.venv/bin/pytest tests/test_geocoding.py -q` → 7 passed. Full suite: 990/990.

**Commit:** `feat(geocoding): add Nominatim wrapper with cache + rate limit`

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

**Verify:** `.venv/bin/pytest tests/test_trip_helpers.py -q` → previous test count + 4 passed. Full suite: 994/994.

**Commit:** `feat(trip_helpers): add hotel_for_night helper`

---

## Task 5 — Add `geocode_cache` to `GuideConfig`

**Files:**
- Modify: `src/guide_builder.py` (the `@dataclass` definition of `GuideConfig`)
- Modify: `tests/test_guide_builder.py` (one new test for round-trip persistence)

**Public surface change:**

```python
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class GuideConfig:
    # ... existing fields ...
    geocode_cache: Dict[str, List[float]] = field(default_factory=dict)
```

**Implementation notes:**
- The dataclass uses `dataclasses.asdict` for serialization to JSON and `**data` for hydration. `Dict[str, List[float]]` survives both directions natively (no custom `__post_init__` needed).
- `load_or_init_config` already handles missing keys gracefully — existing configs without `geocode_cache` hydrate with the default `{}` because Python dataclass field defaults fire when the key is absent. Verify this in the round-trip test below.
- No migration script. No `.config.json` rewrite needed at load time.
- The cache is empty by default; population happens at compose time per Task 6.

**Test name:**
- `test_guide_config_geocode_cache_round_trips_through_save_load` — save a config with `geocode_cache = {"Vatican::Rome": [41.9, 12.45]}`, load it back, assert the dict survives intact AND that loading an older config file (one without the `geocode_cache` key) returns a `GuideConfig` with an empty `geocode_cache` dict (default-factory fired).

**Verify:** `.venv/bin/pytest tests/test_guide_builder.py -q` → previous + 1 passed. Full suite: 995/995.

**Commit:** `feat(guide_builder): persist geocode_cache on GuideConfig`

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

4. **New `### Step 6.5: Build the geocode cache`** inside `## The 10-step flow`, between Step 6 and Step 7. Composer iterates every named venue + every hotel, calls `geocode(name, city, cfg.geocode_cache)`, and calls `save_config(trip_id, cfg)` once at the end. Throttling is enforced inside `geocode()` — the composer does NOT need to sleep.

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

**Verify:** `.venv/bin/pytest tests/ -q` → 995/995 (unchanged from Task 5 end state). `grep -c "^## " .claude/skills/trip-guide/SKILL.md` should be exactly 2 higher than before this task.

**Commit:** `docs(trip-guide): practical hyperlinks + walking-distance chips + step 6.5`

---

## Cross-task type/signature consistency

The signatures used in tasks 5–6 must match exactly what's defined in tasks 1–4. Pinned forms:

- `maps_url(name: str, city: str) -> str`
- `practical_link(name: str, city: str) -> str`
- `haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float`
- `walking_chip(venue_coords: Optional[Tuple[float, float]], hotel_coords: Optional[Tuple[float, float]], hotel_name: str) -> str`
- `geocode(name: str, city: str, cache: Dict[str, List[float]]) -> Optional[Tuple[float, float]]`
- `hotel_for_night(bookings: List[Booking], date: datetime.date) -> Optional[Booking]`
- `GuideConfig.geocode_cache: Dict[str, List[float]]` (default-factory `dict`)

Any deviation from these in implementation is a plan failure — fix the plan or fix the code, but make them match.

---

## Spec coverage check (self-review)

| Spec section | Plan task(s) |
|---|---|
| §"Locked design decisions" 1 (two-tier rule) | Tasks 1, 6 |
| §"Locked design decisions" 2 (walking distance math) | Task 2 |
| §"Locked design decisions" 3 (Nominatim + cache) | Tasks 3, 5, 6 |
| §"Locked design decisions" 4 (adaptive chip format) | Task 2 |
| §"Locked design decisions" 5 (hotel resolution per day + single/multi rule) | Tasks 4, 6 |
| §"Locked design decisions" 6 (Google Maps URL target) | Task 1 |
| §"Locked design decisions" 7 (link styling) | Task 6 |
| §"Architecture" → `src/place_links.py` | Task 1 |
| §"Architecture" → `src/walking_distance.py` | Task 2 |
| §"Architecture" → `src/geocoding.py` | Task 3 |
| §"Architecture" → `hotel_for_night` extension | Task 4 |
| §"Architecture" → cache shape on `GuideConfig` | Task 5 |
| §"Architecture" → composer integration (Step 6.5, Step 7 additions) | Task 6 |
| §"Architecture" → SKILL.md changes (4 items) | Task 6 |
| §"Edge cases" (Nominatim no result, network failure, hotel night unresolved, multi-hotel things_to_do, same venue cached, print mode, reduced motion) | Tasks 2, 3, 4 (helper behaviour); Task 6 (composer behaviour + docs) |
| §"Testing approach" (26 new tests across 4 test files) | Tasks 1–5 |
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

- 995/995 tests green via `.venv/bin/pytest tests/ -q`.
- Five new commits on `main` plus one for this plan file (total six new commits since the validation note).
- SKILL.md has two new top-level sections and one revised anti-pattern.
- `GuideConfig` carries `geocode_cache`; a manual round-trip via `load_or_init_config` + `save_config` is verified offline.
- Plan 2b can be brainstormed next; the geocode cache is ready for `era_chip` and other Plan 2b helpers to reuse.

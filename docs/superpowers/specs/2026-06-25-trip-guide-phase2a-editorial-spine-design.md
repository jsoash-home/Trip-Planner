# Trip Guide Phase 2a — Editorial Spine Refinements — Design

**Date:** 2026-06-25
**Status:** Approved, ready for implementation plan
**Scope:** Two new pure-helper modules + one extension to `src/trip_helpers.py` + edits to `.claude/skills/trip-guide/SKILL.md`. No changes to bookings, itinerary, packing, sharing, countdown, or any existing Flask routes. No DB schema changes.
**Parent plan:** [docs/superpowers/plans/2026-06-23-trip-guide-depth.md](../plans/2026-06-23-trip-guide-depth.md) (Phase 2)
**Seed:** [docs/superpowers/notes/2026-06-25-trip-guide-phase1-validation.md](../notes/2026-06-25-trip-guide-phase1-validation.md)

## Problem

The Phase 1 validation pass surfaced two gaps in the trip-guide skill's
output. Both came from a real read of a regenerated guide, not from a
brainstorm — these are gaps the reader actually noticed.

1. **The bibliography and "Go deeper" cards list titles and authors as
   plain text.** A reader who wants to follow up on a book recommendation
   has to retype the title into a search box. Phase 1 Task 6 explicitly
   forbids URLs in body prose, and that rule over-applied: it kept
   citation links out of body prose (good) AND kept them out of the
   bibliography (not the intent). It also blocks practical links —
   Google Maps URLs for restaurants and museums, ticketing pages,
   official-site URLs — which the in-trip reader genuinely wants.

2. **The day-by-day site cards and `things_to_do` entries don't tell
   the reader how far they are from where they're sleeping that night.**
   The reader has to flip to a map to find out. A `12 min walk · 0.9km
   from Hotel X` chip on each entry closes that gap inline.

## Goals

1. Establish a two-tier hyperlink rule that lets practical links live
   in body prose while keeping citation links concentrated in the
   bibliography.
2. Add walking-distance-from-hotel chips to `day_by_day` site cards
   and (single-hotel trips only) `things_to_do` entries.
3. Make both behaviours fall back gracefully when their inputs aren't
   available (geocoding fails, hotel night unresolved, etc.) without
   breaking the render.
4. Keep all new code as pure helpers in `src/`, isolated and unit-
   tested per the project's structure rules.
5. Document the new rules in `SKILL.md` so the composer (Claude Code)
   applies them at compose time without needing to be told.

## Non-goals (this phase)

- **Visual primitive helpers** (`era_chip`, `swimlane_timeline`,
  `phenology_strip`, `silhouette_svg`, etc.). Those are Plan 2b.
- **In-line citation markers** (footnote-style `[1]` superscripts). The
  user picked the strict split during brainstorming — no inline
  citation markers in body prose.
- **External-link glyphs** (`↗`) on practical links. Subtle underline +
  accent on hover is enough.
- **User-agent-aware Maps URL rewriting** for Apple Maps. Google Maps
  search URL is the single target.
- **Live distance-matrix calls** to Google for exact walking times.
  Haversine + ~1.3× street multiplier + 5 km/h is good enough.
- **A "this is a stale link" indicator.** Once shipped, link rot is the
  reader's problem — same as a printed guide.

## Locked design decisions

The brainstorm asked five multiple-choice questions; each answer
becomes a binding decision below.

### 1. Two-tier hyperlink rule (strict split)

- **Citation links** — books, podcasts, films, Substacks of named
  authors, academic sources, the "Local voice" cards' targets. These
  appear ONLY in:
  - The consolidated "Sources & further reading" section.
  - The per-section "Go deeper" 4-card rows.
  Every entry in both surfaces becomes a real `<a href="...">` tag.

- **Practical links** — Google Maps URLs for named venues, ticketing
  pages, official-site URLs. These ARE allowed in the specific
  practical surfaces below, NOT in atmospheric body prose:
  - Every named venue in `things_to_do`.
  - Every named restaurant in `food` (where to eat).
  - Every named site card in `day_by_day`.
  - Every named landmark / museum entry in `field_guide` (wildlife
    entries have no Maps target — skip).
  - Every hotel row in the "Hotels at a glance" table.

- **Atmospheric body prose is link-free.** `history` paragraphs,
  `day_by_day` day-intro sentences, `food` culture intros, and any
  other prose covered by the named-particulars density floor stay
  unlinked. The reading-rhythm preservation goal from Phase 1's
  editorial voice rules is unchanged here — practical links land
  inside card grids and tables, not running prose.

- **No inline citation markers** in body prose. The bibliography is
  the single citation surface.

### 2. Walking distance: haversine + multiplier

- Compute straight-line distance from coordinates via the haversine
  formula.
- Multiply by **1.3** to approximate routed walking distance through a
  street grid.
- Divide by **5 km/h** (average adult walking pace) to get minutes.
- Round up to the nearest minute.
- Format adapts by distance band — see decision 4 below.

### 3. Coordinates via Nominatim, cached per trip

- Geocode every hotel and every named venue once via Nominatim
  (OpenStreetMap's free geocoder).
- Polite-use rules: 1 request per second, custom `User-Agent` header
  identifying the project (`vacation-planner/0.1
  (jeffsoash@gmail.com)`), no parallel requests.
- Cache results on `GuideConfig.geocode_cache` as
  `{"<name>::<city>": [lat, lon]}`. Persists across regenerations via
  the existing config sidecar JSON.

### 4. Adaptive chip format

The chip always shows when both endpoints geocoded. Format adapts to
the distance:

| Distance | Format |
|---|---|
| ≤ 2km | `12 min walk · 0.9km from Hotel X` |
| 2–5km | `40 min walk · 3.2km · or 10 min by car from Hotel X` |
| > 5km | `15 min by car · 5.8km from Hotel X` |

The "or 10 min by car" alternate in the middle band uses a 30 km/h
in-city driving pace (haversine × 1.3 / 30 km/h). The chip never
shows if either endpoint failed to geocode.

### 5. Hotel resolution per day

- `day_by_day` site cards: chip resolves to **the hotel whose stay
  covers the night of that day's date**, via
  `hotel_for_night(bookings, date)`. Returns `None` on transit days
  (no hotel booking covers that night); the chip is omitted on those
  days.
- `things_to_do`: chip is emitted only on **single-hotel trips** (one
  hotel covering every night of the trip). Multi-hotel trips omit the
  chip on `things_to_do` entirely — labelling "which hotel?" is more
  noise than signal.

### 6. Maps URL target: Google Maps search URL

Single format: `https://www.google.com/maps/search/?api=1&query=<name+city>`.
URL-encoded with `urllib.parse.quote`. Works in every browser; deep-
links into the Google Maps app on iOS and Android.

### 7. Link styling

Subtle by default, accent on hover. CSS verbatim:

```css
a.practical-link {
  color: var(--ink);
  text-decoration-color: var(--hairline);
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
  transition: color 120ms, text-decoration-color 120ms,
              text-decoration-thickness 120ms;
}
a.practical-link:hover,
a.practical-link:focus-visible {
  color: var(--accent);
  text-decoration-color: var(--accent);
  text-decoration-thickness: 2px;
}
```

The same class is used for bibliography entries (no per-section
variants — practical and citation links style identically since they
never share a paragraph).

## Architecture

### New modules

#### `src/place_links.py`

Pure. Renders Google Maps URLs and the practical-link HTML snippet.

```python
def maps_url(name: str, city: str) -> str: ...
def practical_link(name: str, city: str) -> str: ...
```

- `maps_url` builds the Google Maps search URL with `urllib.parse.quote`
  on the combined `name + ", " + city` query.
- `practical_link` wraps the name in
  `<a class="practical-link" href="..." rel="noopener" target="_blank">name</a>`,
  with the name HTML-escaped via `html.escape`.

No external dependencies. No network.

#### `src/walking_distance.py`

Pure. Haversine math + chip formatting.

```python
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float: ...

def walking_chip(
    venue_coords: Optional[Tuple[float, float]],
    hotel_coords: Optional[Tuple[float, float]],
    hotel_name: str,
) -> str: ...
```

- `haversine_km` returns straight-line km between two lat/lon pairs.
- `walking_chip` returns the chip HTML or an empty string if either
  coordinate is `None`. Internally multiplies by 1.3 (street factor),
  divides by 5 km/h walking pace, picks the adaptive format from the
  distance band, HTML-escapes the hotel name.

Depends only on `math` (standard library).

#### `src/geocoding.py`

The only module with network access.

```python
def geocode(
    name: str,
    city: str,
    cache: Dict[str, List[float]],
) -> Optional[Tuple[float, float]]: ...
```

- Looks up `"<name>::<city>"` in `cache` first; cache hit returns
  immediately without network.
- Cache miss: HTTP GET against Nominatim's public endpoint
  (`https://nominatim.openstreetmap.org/search`) with `format=json`,
  `limit=1`, `User-Agent: vacation-planner/0.1 (jeffsoash@gmail.com)`.
- Empty result → returns `None`, does NOT write to cache.
- Successful result → writes `[lat, lon]` to cache (so the caller can
  persist), returns the tuple.
- `time.sleep(1.0)` after every actual HTTP call to respect Nominatim
  rate limits.
- All exceptions caught and logged via `logger.warning`; failures
  return `None`.

Adds `requests` to dev-runtime requirements (the project already uses
it elsewhere; verify before adding).

### Extension to `src/trip_helpers.py`

One new helper:

```python
def hotel_for_night(
    bookings: List[Booking],
    date: datetime.date,
) -> Optional[Booking]: ...
```

- Walks `bookings`, finds the first booking where
  `booking.type == "hotel"` AND `booking.start_date <= date < booking.end_date`.
  ("`< end_date`" matches hotel check-out semantics: the night of
  the check-out date is NOT spent there.)
- Returns `None` if no booking covers the night.
- Returns the first match if two bookings overlap (edge case; logged
  warning).

### Cache shape

`GuideConfig.geocode_cache: Dict[str, List[float]]` — empty dict by
default. Survives regeneration via the existing
`save_config(trip_id, cfg)` path. Keys are stable
`"<name>::<city>"` strings; values are 2-element lists `[lat, lon]`
(JSON-safe; `Tuple` is the in-memory type but lists serialize cleanly).

The `GuideConfig` dataclass and its serialization live in
`src/guide_builder.py`; the field is added there as a default-factory
empty dict. No migration needed — `load_or_init_config` already
handles missing keys gracefully.

### Composer integration

The skill picks up the new behaviour at compose time. SKILL.md
documents two new sub-steps in the 10-step flow:

- **Step 6.5: Build the geocode cache.** Before composing
  `day_by_day` and `things_to_do`, walk every named venue + every
  hotel, geocode any missing into `cfg.geocode_cache`, persist via
  `save_config`. The 1 req/sec throttle is enforced inside
  `geocode()` — the composer just iterates.
- **Step 7 additions** (in the existing Compose step):
  - For each `day_by_day` site card: call
    `hotel_for_night(bookings, day_date)`, then
    `walking_chip(venue_coords, hotel_coords, hotel_name)`. Emit the
    chip in the `.tags` row alongside the existing `.travelpill`.
  - For each `things_to_do` entry: if single-hotel, emit a chip; if
    multi-hotel, skip.
  - For every bibliography entry and "Go deeper" card target: wrap the
    title text in `<a class="practical-link" href="...">`.
  - For every named venue / restaurant / hotel reference in a
    **practical surface** (the card grids and table listed in
    decision 1): wrap in `practical_link(name, city)`. Atmospheric
    prose (history paragraphs, day intros, food culture intros) stays
    unlinked.

### SKILL.md changes

Three edits:

1. **New top-level section "Practical hyperlinks"** between "Source
   disclosure" and "The 10-step flow". Contents: the two-tier rule
   (citation vs practical), the link CSS verbatim, the `maps_url` and
   `practical_link` helper signatures, the `rel="noopener" target="_blank"`
   convention, anti-patterns (no inline citation markers, no external-
   link glyphs, no Apple-Maps rewriting).

2. **Revise Task 6's anti-pattern** in the "Source disclosure" section
   to allow practical links in body prose. The line currently reads:

   > No URL citations in body prose — they go in the consolidated
   > "Sources & further reading" section only.

   Becomes:

   > No **citation** URLs in body prose — book / podcast / film /
   > Substack links go in the consolidated "Sources & further
   > reading" section and "Go deeper" cards only. **Practical** URLs
   > (Google Maps for venues, ticketing pages, official sites) ARE
   > fair game in body prose — see "Practical hyperlinks" for the
   > full rule.

3. **New top-level section "Walking-distance chips"** between
   "Practical hyperlinks" and "The 10-step flow". Contents: the
   haversine + 1.3× + 5 km/h math, the three adaptive format bands,
   the `hotel_for_night` per-day resolution, the single-vs-multi-hotel
   rule for `things_to_do`, the geocode cache lifecycle, the
   Nominatim politeness rules (1 req/sec, custom User-Agent).

4. **Step 10 verification additions:**
   - Every bibliography entry is an `<a>` tag.
   - Every "Go deeper" card title is an `<a>` tag (or the card is
     entirely omitted per Task 6's no-fabricated-sources rule).
   - Every named venue in `things_to_do`, `food` (where to eat),
     `day_by_day` site cards, and the landmark/museum entries in
     `field_guide` has a Google Maps link
     (`a.practical-link[href*="google.com/maps"]`).
   - Atmospheric prose (history paragraphs, day intros) contains zero
     `<a>` tags — the verifier grep should find none.
   - Walking-distance chips render on `day_by_day` site cards on days
     where `hotel_for_night` resolves AND both endpoints geocoded.
   - "Hotels at a glance" addresses are clickable.

## Edge cases

- **Nominatim returns no result.** `geocode` returns `None`. Chip
  omitted for that venue. Link still rendered — Google Maps URL works
  even on bad-name queries; the reader gets a search results page.
- **Network failure during geocoding.** Same as no result: `None`,
  chip omitted, warning logged. Pause-and-retry is the composer's
  call, not the helper's.
- **Hotel night unresolved** (transit day, gap in booking dates). Chip
  omitted on that day's cards.
- **Multi-hotel trip** in `things_to_do`. Chips omitted entirely.
  Composer doesn't try "closest hotel" logic — overkill for v1.
- **Same venue used across multiple days.** Cache hits on the second
  lookup; one geocode total.
- **Print mode.** Link underlines preserved (per `@media print`
  defaults). Chips render normally — they're small mono text, useful
  on paper too.
- **Reduced-motion preference.** Link hover transitions skip per the
  existing `@media (prefers-reduced-motion: reduce)` block at the top
  of every guide.

## Testing approach

One test file per new module. Mocked tests for `geocoding.py` so the
suite stays offline.

| Test file | Test names |
|---|---|
| `tests/test_place_links.py` | `maps_url_builds_google_search_query`, `maps_url_url_encodes_punctuation`, `maps_url_url_encodes_unicode`, `practical_link_includes_rel_noopener`, `practical_link_escapes_html_in_name`, `practical_link_target_blank` |
| `tests/test_walking_distance.py` | `haversine_km_known_landmark_pair`, `haversine_km_zero_for_same_point`, `haversine_km_symmetric`, `walking_chip_under_2km_format`, `walking_chip_2_to_5km_format`, `walking_chip_over_5km_format`, `walking_chip_returns_empty_on_none_venue_coords`, `walking_chip_returns_empty_on_none_hotel_coords`, `walking_chip_html_escapes_hotel_name` |
| `tests/test_geocoding.py` | `geocode_cache_hit_returns_cached_no_network`, `geocode_cache_miss_calls_nominatim_mocked`, `geocode_empty_result_returns_none`, `geocode_empty_result_does_not_write_to_cache`, `geocode_writes_to_cache_on_success`, `geocode_network_error_returns_none`, `geocode_sleeps_after_real_call` |
| `tests/test_trip_helpers.py` (additions) | `hotel_for_night_picks_covering_booking`, `hotel_for_night_returns_none_when_no_coverage`, `hotel_for_night_excludes_checkout_night`, `hotel_for_night_picks_first_when_overlapping_logs_warning` |

Total: 26 new tests. Suite currently at 968; expected end state ~994.

## Risks and open questions

- **Nominatim rate limit / blocking.** OSM's geocoder is generous but
  not unlimited. On a trip with 50+ named venues, hitting all of them
  at 1 req/sec is ~50 seconds of geocoding the first time. Acceptable.
  If we ever hit a 429, we add an exponential backoff to `geocode()`.
- **Stale Maps URLs.** Google Maps search URLs are by name, not by
  place ID, so they survive venue renames better than place-ID-pinned
  URLs. Link rot is still possible (venue closes) but no worse than a
  printed guide.
- **Geocoded venue mismatch.** "Café Tortoni, Buenos Aires" geocodes
  fine. "Café Tortoni, Madrid" geocodes to a different (or no)
  result. The composer always passes `(name, city)` together; cache
  keys include the city to keep the disambiguation explicit.
- **Plan 2b dependency.** This phase establishes the `practical-link`
  CSS class and the geocode cache. Plan 2b's `era_chip` and other
  visual primitives can reuse the cache for nothing extra.

## Acceptance criteria

A guide regenerated after this phase ships must:

1. Have every bibliography entry rendered as `<a>` tags.
2. Have every "Go deeper" card title as `<a>` (or be omitted per Task
   6's no-fabricated-sources rule).
3. Have every named venue in `things_to_do`, `food` (where to eat),
   `day_by_day` site cards, and `field_guide` landmark/museum entries
   as a Google Maps `<a>`. Atmospheric body prose contains zero
   `<a>` tags.
4. Have walking-distance chips on `day_by_day` site cards on days
   where both endpoints geocoded.
5. Have walking-distance chips on `things_to_do` entries if and only
   if the trip is single-hotel.
6. Persist `geocode_cache` to the config sidecar; second regeneration
   makes zero geocoding HTTP calls if no new venues were added.
7. Pass all existing tests (968) plus the 26 new ones.

A guide is signed off when the user manually reviews these and the
chip/link presentation reads right at a glance.

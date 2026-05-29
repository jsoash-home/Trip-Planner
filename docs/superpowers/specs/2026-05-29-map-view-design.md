# Map View — Design Spec

> **Status:** Approved design, awaiting implementation plan. Phase 2 feature #5
> from [docs/PHASE_2_ROADMAP.md](../../PHASE_2_ROADMAP.md). Spec captures the
> design decisions made during the 2026-05-29 brainstorm.

## Goal

Add two map surfaces to the app:

1. **In-trip map** — a map of pinned bookings and itinerary items for a single
   trip, used for planning upcoming trips and remembering past ones. Lives on
   the trip itself: a small teaser on the trip overview page plus a dedicated
   `/trips/<id>/map` sub-page where real planning happens.
2. **Lifetime map** — a map at `/map` showing every place you've been across
   every completed and in-progress trip, filterable by year, with three jobs
   in one view: trophy case (look at coverage), memory index (click a pin,
   jump back to that trip), and planning aid (see the gaps).

Both maps render with Mapbox GL JS, fed by server-rendered GeoJSON. Free-text
`location` strings on existing booking and itinerary rows get geocoded once
to stored `(lat, lng)` and reused forever after.

## Background and motivation

The v1 codebase already captures a free-text `location` string on every
`Booking` and `ItineraryItem` row. That data sits unused — there's no way to
see "where" any of your trip is, just the words. The Phase 2 roadmap scopes a
map view as feature #5; this brainstorm expands the original single-purpose
"per-trip map" into the two-surface design captured here, because a lifetime
view doesn't naturally fit inside a single trip page.

The design prioritizes a single ambitious lifetime view (the user picked "all
three jobs" — trophy + memory + planning — knowing it's the riskiest scope)
while keeping the in-trip experience tight and obviously useful for planning.

## Out of scope for v1

All deferred to later phases. Listed so the boundary is unambiguous:

1. Background geocoding worker (v1 is synchronous-on-map-view).
2. Route lines drawn between pins (flight paths, daily walking routes).
3. Map embed in the public share-link view (Phase 2 #4).
4. Dashboard widget showing a small cross-trip map.
5. "Where am I now?" geolocation features.
6. Country / trip-type / role filters on the lifetime map (year only in v1).
7. Booking-only / itinerary-only toggle on the in-trip map (day filter is
   sufficient).
8. "Re-geocode this pin" link in the popup for manually-pinned rows.
9. Per-trip "exclude from lifetime map" toggle.
10. Persistent day-chip selection on the in-trip map across page loads.
11. Pin jitter / spiderfy for overlapping coordinates.
12. Trip duplication's interaction with geocoded coords (see note in
    Future-compatibility section below).

---

## Architecture overview

Two pages, three new routes, one shared geocoding pipeline, one shared JS
module. No new dependencies on the backend beyond `requests` (which the
project likely already has); on the frontend, Mapbox GL JS via CDN, loaded
only on map pages.

```
                            ┌──────────────────────────┐
                            │  Mapbox Geocoding API    │
                            └────────────▲─────────────┘
                                         │ (lazy, on map view)
                          ┌──────────────┴──────────────┐
                          │     src/geocoding.py        │
                          │  (cache → API → save)       │
                          └──────────────▲──────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
        ▼                                ▼                                ▼
┌───────────────┐              ┌───────────────────┐              ┌────────────────┐
│  GET /trips/  │              │   GET /trips/     │              │   GET /map     │
│  <id>/map     │              │   <id>/map/       │              │                │
│  (page)       │              │   data.geojson    │              │   GET /map/    │
│               │              │                   │              │   data.geojson │
│  GET /trips/  │              │   POST /trips/    │              │                │
│  <id>/map/    │              │   <id>/map/pin/   │              └────────────────┘
│  data.geojson │              │   <type>/<id>     │
│  (lazy-geoc.) │              │   (drag-correct)  │
└───────────────┘              └───────────────────┘
```

All routes are added to `app.py` (project convention: no blueprints).
Helpers live in `src/`. Templates in `templates/`. JS in `static/js/`.

---

## Data model changes

Additive only. No removals, no renames.

### New columns on `Booking` AND `ItineraryItem` (same shape on each)

| Column | Type | Default | Purpose |
|---|---|---|---|
| `geocoded_lat` | Float | NULL | Forward-geocoded latitude. |
| `geocoded_lng` | Float | NULL | Forward-geocoded longitude. |
| `geocoded_at` | DateTime | NULL | When coords were last written. |
| `geocoded_manually` | Boolean | False | `True` means the user drag-corrected this pin; don't auto-re-geocode if `location` text changes. |
| `geocoded_city` | String | NULL | City name from Mapbox response (`context.place.text`). |
| `geocoded_country_code` | String(2) | NULL | ISO Alpha-2 country code (`context.country.short_code`). |

### New table `GeocodeCache`

Global de-dupe table. Two users with bookings called "Eiffel Tower" share
one cached lat/lng.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `location_text_normalized` | String | Indexed, unique. Lowercased + whitespace-collapsed input. |
| `lat` | Float | |
| `lng` | Float | |
| `city` | String, nullable | |
| `country_code` | String(2), nullable | |
| `provider` | String | `"mapbox"` for v1; column gives room to switch later. |
| `created_at` | DateTime | |

Cache never expires in v1. Real-world locations rarely move; wrong pins are
fixed via the row-level manual override, not by invalidating the cache.

### No changes to `Trip`

The lifetime map aggregates from bookings + items. We don't need a per-trip
lat/lng. (The existing `destination` free-text field on `Trip` is unused by
this feature.)

### Migration story

Same as every prior schema change in this project (per CLAUDE.md): the app
uses `db.create_all()` on boot, no Alembic. New columns default to NULL and
backfill safely on existing rows. Back up `vacation.db` before first run with
the new code — the implementation plan will include a backup step.

### New environment variable

`MAPBOX_TOKEN` — a Mapbox **public** access token (`pk.*`). Goes in `.env`
locally and the host's env vars in production. Public tokens are designed
to be exposed in HTML; we restrict by referrer domain in the Mapbox
dashboard so a leaked token can't be abused elsewhere. Added to
`.env.example` with a comment pointing to Mapbox signup.

---

## Geocoding pipeline

### When it runs

Lazy, on map-page load. Booking saves and itinerary saves stay fast — we
never block a POST on a geocoding API call. Cost: first map open for a trip
with N un-geocoded rows is slow (~300 ms × N). All subsequent opens are
instant because coords are now on the rows.

### Pipeline per row

When `/trips/<id>/map/data.geojson` (or `/map/data.geojson`) is requested,
for every row that has non-empty `location` and missing `geocoded_lat`:

1. Normalize the location text: `strip() + lower() + collapse whitespace`.
2. Look up `GeocodeCache` for that normalized string.
   - **Hit:** copy `lat`, `lng`, `city`, `country_code` onto the row. Set
     `geocoded_at = utcnow()`. Leave `geocoded_manually = False`.
   - **Miss:** call Mapbox Geocoding API (`/geocoding/v5/mapbox.places/{q}.json`).
     On success: write the result to *both* `GeocodeCache` and the row.
3. Commit, then render the GeoJSON response.

### Manual override (drag-to-correct)

Pins on the in-trip map are draggable for users with editor+ role. On
drag-end, the client fires `POST /trips/<id>/map/pin/<row_type>/<row_id>`
with the new `lat` and `lng`. Server:

1. Validates trip access (`editor` minimum via `require_trip_access`).
2. Validates row exists and belongs to the trip.
3. Validates `-90 <= lat <= 90` and `-180 <= lng <= 180`.
4. Writes the coords to the row. Sets `geocoded_manually = True` and
   `geocoded_at = utcnow()`.
5. Returns 204.

Client shows a 1.5-second "Saved" toast. On any error (network, validation,
permission), the pin snaps back to its original position and a flash
banner reports the issue.

Manual override is **in-trip map only** in v1. The lifetime map is
read-only — fix a wrong pin by opening the source trip.

### Reaction to location-text edits

When a user edits a booking's `location` text via the booking edit form
(same for itinerary items):

- If `geocoded_manually == False`: clear `geocoded_lat`, `geocoded_lng`,
  `geocoded_city`, `geocoded_country_code`, `geocoded_at`. The next map
  view re-geocodes the new text.
- If `geocoded_manually == True`: leave coords untouched. The user pinned
  it there on purpose; we trust them.

The decision is encapsulated in a pure helper
`should_clear_geocode(old_text: str, new_text: str, manually_pinned: bool) -> bool`
so it's unit-testable. The booking-edit and itinerary-edit routes call it
and act on the result.

### Error handling

| Scenario | Behavior |
|---|---|
| Mapbox returns 0 results | Leave coords NULL. Row silently absent from the map. `logger.warning("geocode 0 results: %s", text)`. |
| Mapbox returns multiple ambiguous results | Take the first (Mapbox sorts by relevance). Manual override fixes wrong ones. |
| Mapbox API 5xx / timeout | Catch. Leave coords NULL. Map renders with whatever already-geocoded pins exist. Flash banner: "Some locations couldn't be geocoded — try again later." `logger.error`. |
| Mapbox 429 rate limit | Same as 5xx. Backoff out of scope for v1; re-attempts next map view. |
| `MAPBOX_TOKEN` missing | Detected at app boot. Map pages render with a banner: "Map provider not configured." App keeps running. Logged at error level. |

### Cache invariants

- `GeocodeCache` is global across all users.
- Cache never expires.
- Cache writes are in the same DB transaction as the row update, so a
  failed write doesn't desync the two.

---

## In-trip map

### Overview mini-map (teaser)

A small section on `trip_overview.html`, placed between the existing Today /
Upcoming hero and the bookings/itinerary/packing tiles.

- **Render:** static, non-interactive Mapbox view, ~120 px tall.
- **Pins:** all geocoded bookings + itinerary items for the trip, fit-to-bounds.
- **Click anywhere:** navigates to the full `/trips/<id>/map` page.
- **No popups, no dragging, no day filter** — this is a teaser.
- **Hidden entirely** when the trip has zero geocoded pins. No empty box.

### Dedicated `/trips/<id>/map` page

A new section tile labeled "Map" is added to the trip overview's section
grid (built in `app.py` and rendered via `_section_tiles.html`), alongside
Bookings / Itinerary / Packing / Budget / Share. The project has no
persistent cross-page sub-nav — section tiles on the overview are how the
user navigates between trip sub-pages.

**Layout, top to bottom:**

1. **Day filter chip bar.** Reuses the existing horizontal-scroll chip
   pattern from Session 15 (`templates/trip_itinerary.html` mobile day
   picker). Chips:
   - "All days" (default active)
   - "Day 1 Mon 8/17" · "Day 2 Tue 8/18" · … (one per trip day)
   - "Anytime" (for pins where `day_date` is NULL — typically standalone
     bookings)
2. **Map.** Full-width, 480 px tall desktop, 360 px mobile. Fit-to-bounds
   of currently-visible pins. Recenters when the day filter changes.
3. **Side note** (only when applicable). Small muted text below the map:
   *"3 items have no location — [add locations]."* Link goes to
   `/trips/<id>/bookings` (filtering to those rows is deferred to v2; the
   v1 link just opens the bookings list).

### Pin sources and the de-duplication rule

To avoid showing two pins at the same location for the same logical event
(e.g. a hotel booking and its auto-generated "Check in" itinerary item):

- **Every `Booking` with non-empty `location` produces a pin.**
- **An `ItineraryItem` produces a pin only if it has non-empty `location`
  AND `linked_booking_id IS NULL`.**

The rule means user-added itinerary items always pin (locations not tied
to any booking — manual entries like "Hike up Mount Fløyen"), while
auto-created items (those with a `linked_booking_id`) defer to their
parent booking for the pin.

### Coloring and the legend

Color is by category, using the existing itinerary palette so visual
continuity holds with the itinerary view. The project defines five
itinerary categories with paired CSS tokens:

| Category | Source rows | CSS tokens (existing) |
|---|---|---|
| transit | flight / car bookings; transit items | `--vp-cat-transit-fg`, `--vp-cat-transit-bg` |
| meal | restaurant bookings; meal items | `--vp-cat-meal-fg`, `--vp-cat-meal-bg` |
| sightseeing | activity bookings; sightseeing items | `--vp-cat-sightseeing-fg`, `--vp-cat-sightseeing-bg` |
| break | break items only | `--vp-cat-break-fg`, `--vp-cat-break-bg` |
| other | hotel bookings, transport / other bookings, other items | `--vp-cat-other-fg`, `--vp-cat-other-bg` |

Booking → category mapping mirrors the existing rules in
`auto_itinerary_items_for_booking` in [`src/booking_helpers.py`](../../src/booking_helpers.py):
flight → transit, car → transit, transport → transit, restaurant → meal,
activity → sightseeing, hotel → other, other → other.

A small legend in the bottom-left corner of the map shows the
color → category mapping. Collapsed by default on mobile, expandable on
tap.

### Day-filter mechanics

Same client-side pattern as Session 15: clicking a day chip applies a
Mapbox `filter` expression to the pin layer based on the feature's
`day_index` property. No server round-trip, no page reload.

State is session-only — not persisted across page loads. "All days" is the
natural landing state every time, unlike the itinerary day-picker where
remembering the last day viewed makes more sense.

### Pin click — popup card

Mapbox's standard popup, styled to match the existing booking-detail and
itinerary-chip aesthetic:

```
┌─────────────────────────────┐
│ 🏨 Hotel Skansen            │
│ Mon Aug 17 · 3:00 PM        │
│ Båstad, Sweden              │
│ [ Open booking → ]          │
└─────────────────────────────┘
```

Fields:
- Category emoji + title
- Datetime if present (omitted when the row has no `start_datetime`)
- The original `location` text (not the geocoded city/country — those are
  for the map's aggregation, not the user-facing label)
- One action link: "Open booking →" for bookings, "Open itinerary item →"
  for items. Auto-created itinerary items linked to a booking link to the
  **booking** instead (same logic as the itinerary chip today).

### Drag-to-correct override

Editor+ users can drag pins. See "Manual override" in the Geocoding
section for the full mechanics. Viewers (read-only collaborators) see
non-draggable pins with no hover affordance — the cursor doesn't change.

### Empty state

Trip with no geocoded pins yet (no location text on any row, OR first map
open in progress): single centered message —
*"No locations to map yet. Add a location to a booking or itinerary item,
then open this page again."* The chip bar and side note are hidden.

---

## Lifetime map

### Where it lives

`/map` — new top-level route, no `<trip_id>`. Linked from the user dropdown
in the navbar (next to "Dashboard"), with a globe icon. Reachable in two
clicks from anywhere in the app.

### Layout

1. **Stats bar.** A muted single-line summary above the map:
   *"23 countries · 84 cities · 47 trips."* Updates live as the year chip
   changes.
2. **Year filter chips.** Same scrolling-chip pattern as the in-trip day
   filter. "All years" (default) plus one chip for each year that has at
   least one trip, descending. Empty years are skipped to keep the bar
   tight.
3. **Map.** Full-width, 560 px tall desktop, 400 px mobile. Initial view:
   world, fit-to-bounds of all visited countries. Below the map: a small
   legend (year color swatches for the visible years) and a "Replay
   animation" link.

### Trips included

- **Status:** completed OR in-progress.
- **Ownership:** trips the user owns *or* is a collaborator on (any role).

A trip's pins disappear from a user's lifetime map immediately on the next
request if their collaborator access is revoked. Trip status changes
(planning → in-progress → completed) reflect on the next request because
inclusion is computed at request time, not cached.

### The three zoom layers

| Zoom range | Layer | What renders |
|---|---|---|
| 0–3 (world) | Country paint | Visited countries shaded. Individual pins hidden. |
| 4–8 (country / region) | City pins | One dot per `(geocoded_city, geocoded_country_code)` combo, sized proportionally to pin count there. Colored by *most recent* year that city was visited. Country paint stays visible but muted underneath. |
| 9+ (city / street) | Individual pins | One dot per booking/itinerary item with coords. Same year-color palette. Country paint and city dots hidden. |

All three layers ship in one GeoJSON payload (small — even 50 trips × 30
pins is well under 100 KB). Mapbox's `layer.minzoom` / `maxzoom` switches
between them as the user zooms. No round-trip per zoom level.

### Country paint

Uses Mapbox's built-in `country-boundaries-v1` vector tile source. A fill
layer matches features whose `iso_3166_1` is in the user's
`visited_country_codes` list and shades them. When a single year is
filtered, the fill is colored with that year's palette color; with "All
years" active, a neutral "visited" color.

### Year color palette

A fixed 12-color cycle. Distinct, colorblind-safe (Okabe-Ito-derived or a
similar curated palette). Years cycle through the palette via
`palette[year % 12]`. Defined as a constant in `src/map_helpers.py` so
it's easy to swap if it doesn't feel right when we see it live.

### Year filter

Click a year chip → narrows country paint, city dots, and individual pins
to that year's data. Stats bar updates. "All years" restores. All
client-side via Mapbox filter expressions; no server round-trip.

### Chronological fade-in on first load (D-lite)

When the page loads:

1. Server returns the full GeoJSON in chronological order — earliest
   trip's pins first.
2. Client checks `prefers-reduced-motion`. If `reduce`, render everything
   instantly; skip the rest.
3. Otherwise: feed features into the map source incrementally over a
   ~1.5-second total budget. Each trip's pins appear together, in order.
   Country paint fills in as countries acquire their first pin.
4. After the animation, behavior is normal — year filter, zoom, clicks all
   responsive.
5. A "Replay animation" link below the map re-triggers the fade-in. Useful
   if the user wants to watch it again.

### Click behavior by layer

| Click target | Behavior |
|---|---|
| Country (paint) at world zoom | Smooth-zoom to fit that country's bounds. |
| City pin at country zoom | Popup listing every trip that touched the city: trip name + year + "Open trip →" link, one row per trip. (Three visits to Paris = three rows.) |
| Individual pin at city zoom | Compact popup: title, datetime, location text, "Open trip →" link. No direct booking/item edit link — lifetime view is read-only; you go via the trip. |

### Read-only and privacy

- No drag-to-correct. Fix wrong pins via the in-trip map.
- Collaborator trips contribute pins identically to owned trips.
- Popups never display collaborator emails or owner identity.

### Empty state

No completed-or-in-progress trips → centered message:
*"No travel history yet. Your map will fill in after your first trip
wraps up."* Map and chips hidden. Stats bar replaced with the message.

---

## Routes, files, and code structure

### New files

```
src/
├── geocoding.py             — Mapbox client + cache wrapper (calls external API)
└── map_helpers.py           — pure helpers (no API, no DB)
tests/
├── test_geocoding.py        — mocks the Mapbox call
└── test_map_helpers.py
templates/
├── trip_map.html            — /trips/<id>/map page
├── lifetime_map.html        — /map page
└── _mini_map.html           — overview-page tile partial
static/
├── js/map.js                — Mapbox init, chips, fade-in, drag handlers
└── css/map.css              — map-only styles (small; fold into app.css if under ~40 lines)
```

### Modified files

| File | What changes |
|---|---|
| `models.py` | Add the six new columns to `Booking` and `ItineraryItem`. Add new `GeocodeCache` model. |
| `app.py` | Add five new routes (below). Hook into the booking-edit and itinerary-edit handlers to call `should_clear_geocode` and act on the result. Load `MAPBOX_TOKEN` from env. |
| `templates/base.html` | Add "Map" entry to the user dropdown with a globe icon. |
| `templates/trip_overview.html` | Include `_mini_map.html` between the hero and the tile section. |
| `app.py` section-tile builder | Add a "Map" tile to the trip overview's section-tile list (the list passed into `_section_tiles.html`). Project has no separate sub-nav template — section tiles ARE the trip's between-page navigation. |
| `.env.example` | Add `MAPBOX_TOKEN=pk.your_public_token_here` with a comment. |
| `requirements.txt` | Add `requests` if not already present. |

### Routes (all added to `app.py`)

```
GET  /trips/<int:trip_id>/map                              → renders trip_map.html
GET  /trips/<int:trip_id>/map/data.geojson                 → in-trip pins (lazy-geocodes on demand)
POST /trips/<int:trip_id>/map/pin/<row_type>/<int:row_id>  → drag-correct (editor+ only)
GET  /map                                                  → renders lifetime_map.html
GET  /map/data.geojson                                     → lifetime pins (lazy-geocodes user's trips)
```

Splitting page-render from data-fetch keeps initial HTML responses fast.
The slow geocoding work only runs when the JS calls the `data.geojson`
endpoint after the page paints.

### Pure helpers in `src/map_helpers.py`

```python
@dataclass
class Pin:
    row_type: str               # "booking" or "item"
    row_id: int
    trip_id: int
    trip_name: str
    title: str
    location_text: str
    lat: float
    lng: float
    geocoded_city: Optional[str]
    geocoded_country_code: Optional[str]
    year: int                   # trip.start_date.year
    category: str
    datetime_iso: Optional[str]
    day_index: Optional[int]    # for in-trip day filter

def normalize_location(text: str) -> str: ...
def should_clear_geocode(old_text: str, new_text: str, manually_pinned: bool) -> bool: ...
def color_for_year(year: int) -> str: ...
def color_for_category(category: str) -> str: ...
def years_present(pins: list[Pin]) -> list[int]: ...
def stats_for_pins(pins: list[Pin]) -> dict: ...     # {"countries": N, "cities": N, "trips": N}
def pins_to_geojson(pins: list[Pin], color_fn) -> dict: ...
```

Each helper is fully unit-tested in `tests/test_map_helpers.py`. None of
them touch the DB or the network.

### Geocoding module in `src/geocoding.py`

NOT a pure helper — wraps the Mapbox API:

```python
@dataclass
class GeocodeResult:
    lat: float
    lng: float
    city: Optional[str]
    country_code: Optional[str]

def geocode_one(text: str, *, token: str) -> Optional[GeocodeResult]: ...
def geocode_with_cache(text: str, *, db_session, token: str) -> Optional[GeocodeResult]: ...
def ensure_geocoded(rows: Iterable, *, db_session, token: str) -> None: ...
```

Tests mock `requests.get` so the suite never hits Mapbox.

### Mapbox loading

Via CDN, same lazy-loading pattern as `canvas-confetti`:

```html
<link href="https://api.mapbox.com/mapbox-gl-js/v3.6.0/mapbox-gl.css" rel="stylesheet">
<script src="https://api.mapbox.com/mapbox-gl-js/v3.6.0/mapbox-gl.js"></script>
```

Included only in `trip_map.html`, `lifetime_map.html`, and (because the
mini-map renders Mapbox too) `trip_overview.html`. Mapbox GL JS is ~250 KB
gzipped; paying that on three pages is the right trade-off for the visual
quality.

### Token plumbing

Server reads `MAPBOX_TOKEN` from env at app boot. Map page templates
inject it via a `data-mapbox-token` attribute on the map container
`<div>`. `static/js/map.js` reads from that attribute. Never written into
JS source directly.

---

## Testing approach

| Layer | Test strategy | Location |
|---|---|---|
| Pure helpers (`map_helpers.py`) | Full unit coverage. Each function gets a happy path + obvious edge cases. | `tests/test_map_helpers.py` |
| Geocoding (`geocoding.py`) | Mock `requests.get`. Cover: cache hit, cache miss + API success, API zero results, API 5xx, API timeout, missing token. | `tests/test_geocoding.py` |
| Routes | Smoke tests using the existing test client. Cover: page renders for owner / editor / viewer / anonymous; `data.geojson` returns valid JSON; drag-correct accepted for editor, rejected for viewer, rejected for cross-trip access. | extend `tests/test_app.py`, or new `tests/test_map_routes.py` if it grows. |
| Booking / itinerary edit hooks | Editing `location` on a non-manual row clears coords; editing on a manual row preserves them. | extend `tests/test_booking_helpers.py` and `tests/test_itinerary.py`. |

Mapbox itself is never called from tests. TDD per project standard.

---

## Edge cases

| Case | Behavior |
|---|---|
| Trip with zero locations on any row | In-trip map shows empty state. Mini-map hidden on overview. |
| Booking location edited from `"Paris"` → `""` | `should_clear_geocode` returns True. Coords cleared. Pin disappears next render. |
| Booking location edited on a manually-pinned row | Coords preserved. User's drag wins. |
| Two rows with the same normalized location | First geocodes via API and writes cache. Second hits cache. One API call total. |
| Lifetime map for a user with only planning trips | Empty state. Map and chips hidden. |
| Collaborator removed from a trip | Next `/map` load excludes that trip's pins. Inclusion is request-time. |
| 100+ trips × 30 pins each | GeoJSON ~300 KB. Mapbox clustering handles render. First geocoding pass slow if many ungeocoded — flagged for future optimization, not a v1 blocker. |
| Mapbox returns a wrong country for an ambiguous location ("Springfield") | First-result strategy places the pin wrong. User drag-corrects on in-trip map. |
| Two pins at exact same `(lat, lng)` | Mapbox stacks them. Top one wins on click. Acceptable for v1. |
| Pin without `start_datetime` (e.g. hotel with only dates) | Day filter places it under `day_date` / "Anytime." Popup omits the time line. |
| `MAPBOX_TOKEN` not configured | Map pages render a banner; app keeps running. Error logged at boot. |

---

## Performance bounds (v1 acceptable)

- First map open for a trip with N un-geocoded rows: ~300 ms × N. Painful
  at 50+, fine at 10–15. Subsequent opens drop to <200 ms typical.
- GeoJSON payload: under 100 KB for typical users. No streaming or
  pagination needed.
- Mapbox free-tier quotas (50k map loads, 100k geocodes per month): a
  heavy user might burn ~1–2k loads/month. Well within free tier.

---

## Security and privacy

- `MAPBOX_TOKEN` is a **public** token (`pk.*`). Designed to be exposed in
  HTML. Restrict by referrer domain in the Mapbox dashboard so a leaked
  token can't be abused elsewhere.
- POST drag-correct route is CSRF-protected (Flask-Login default) and
  re-checks trip access via `require_trip_access(trip_id, "editor")`.
- Lifetime map respects the sharing model: only trips the user owns or
  collaborates on contribute pins. Removing a collaborator's access
  immediately removes their pins on the next request.
- Popup cards never display collaborator emails or owner identity.

---

## Accessibility

- `prefers-reduced-motion: reduce` skips the fade-in animation entirely.
  Map renders fully populated immediately.
- Chip filter bars use `<button>` elements with proper ARIA `aria-pressed`
  state — same pattern as existing chip bars from earlier sessions.
- Empty states use clear, screen-reader-friendly copy.
- Color palette is colorblind-safe.
- Pin meaning never relies on color alone (category emoji on in-trip;
  geocoded city/country labels available on hover for lifetime).

---

## Logging

Per project standards — `logger = logging.getLogger(__name__)` at the top
of every new module. No `print()` calls.

- `logger.info` — each geocoding API call attempted (`"geocoding: %s"`).
- `logger.warning` — zero-result geocodes, with the input text for
  debugging.
- `logger.error` — API 5xx, network failures, missing token at boot.

---

## Future-compatibility notes

These won't be built in v1, but the design leaves room for them:

- **Trip duplication interaction.** When the trip-duplication feature ships
  (Phase 2 #6), the copy logic should carry `geocoded_lat`, `geocoded_lng`,
  `geocoded_city`, `geocoded_country_code` over to the copied rows but
  clear `geocoded_manually` and `geocoded_at` so future edits behave
  normally. (Documents and pins should NOT carry over — both are
  instance-specific.) One-line note in the duplication helper at copy
  time.
- **Public share-link maps.** When the share-link feature ships (Phase 2
  #4), the public trip page can embed the same `_mini_map.html` partial
  in read-only mode. The mini-map is already non-interactive, so the work
  is just "render it on the public template."
- **Background geocoding.** If first-map-open latency starts to hurt at
  scale, move `ensure_geocoded` to a background job (Celery / RQ / a
  simple cron) without touching the routes. Routes would return whatever
  coords exist; the worker fills in the gaps.
- **More filters on lifetime.** Country, trip-type, role, etc. The chip
  bar pattern scales — adding more chip groups is mechanical.

---

## Brainstorm record

Decisions made during the 2026-05-29 brainstorm session, in order:

1. **Lifetime map purpose** — all three jobs: trophy + memory + planning aid.
2. **Pin granularity** — zoom-aware: countries paint at world view, cities
   at country view, individual locations at city view.
3. **"Over time" UI** — B + D-lite + A: year filter chips, chronological
   fade-in on first load, color by year.
4. **Trips included on lifetime map** — completed + in-progress, owned +
   collaborator. Future trips excluded.
5. **Where future-trip planning lives** — the in-trip map, not the
   lifetime map.
6. **In-trip map placement** — mini-map teaser on overview + dedicated
   `/trips/<id>/map` sub-page.
7. **Map provider** — Mapbox GL JS.
8. **Geocoding strategy** — lazy on first map view.
9. **Manual override** — yes, in-trip drag-to-correct in v1.
10. **Pin click popups** — title + datetime + location + "Open …" link.
11. **In-trip pin scope** — bookings + itinerary on the same map, color by
    category, no booking-only / itinerary-only toggle in v1.
12. **Lifetime filters beyond year** — none in v1.
13. **Items without location** — silently excluded; in-trip page shows a
    small side note with a count.

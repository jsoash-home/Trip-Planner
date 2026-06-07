# Lifetime Stats Dashboard — Design Spec

> **Status:** Approved design, awaiting implementation plan. Phase 3
> feature A2 from [docs/PHASE_3_ROADMAP.md](../../PHASE_3_ROADMAP.md).
> Spec captures the design decisions made during the 2026-06-07
> brainstorm. Depends softly on A1 (Trip Yearbook) — reuses helper
> patterns and the `src/yearbook.py` module. A1 shipped 2026-05-31;
> A3 shipped 2026-06-06.

## Goal

Add a stats strip above the lifetime map at `/map` showing aggregate
totals across the user's completed trips, plus a small "trips per
year" bar chart below the map.

The strip surfaces the numbers the user already feels when they scroll
the country-shaded map. The chart adds a year-over-year shape so the
page reads as both "where" (the map) and "when" (the bars).

This is the third "remember forever" feature (after A1 yearbook and A3
on-this-day) and the last of the A thread. It reuses the
`src/yearbook.py` helper module added by A1 and the deduplicated
country / city logic already exercised by `compute_trip_stats` and
`compute_country_list`.

## Background and motivation

The lifetime map already says "this app cares about looking back." But
the page itself only renders pins — the totals that explain the
emotional weight of those pins (how many countries, how many trips,
the longest one) are absent. A1's yearbook surfaces per-trip numbers;
A2 lifts the same numbers one altitude higher so they apply to the
user's whole travel life.

The phase 3 roadmap shows the feel:

> 🌍 **22 countries** · 🏙️ **47 cities** · 📅 **186 days away**
> ✈️ **34 flights** · 🧳 **9 trips** · 🗺️ **Longest: 21 days**

The strip sits above the map; the bar chart sits below it. The map
itself remains visually dominant — the stats are framing, not the
hero.

## Scope

**In scope:**

- Two new pure helpers in `src/yearbook.py`:
  - `compute_lifetime_stats(trips)` → `LifetimeStats` dataclass
  - `compute_trips_per_year(trips)` → `list[YearBar]` for the chart
- Reuses A1's dedup logic for countries and cities.
- One stats strip block in `templates/lifetime_map.html` (above the
  map block).
- One CSS-bar chart block below the map.
- Empty / zero state handled with a small nudge copy.
- Unit tests against `FakeTrip` with `.bookings` and `.itinerary_items`
  list attributes (extend the existing dataclass).
- One integration test that `/map` renders the stats strip when the
  user has at least one completed trip.

**Out of scope (explicit):**

- No total-spend chip. Multi-currency totals are still per-currency
  until B3 (home-currency budget totals) ships.
- No biggest-spend-category at the lifetime level. The per-trip number
  on the yearbook is enough; lifetime aggregation across currencies
  isn't meaningful yet.
- No "by country" breakdown. The map IS the by-country view.
- No filter UI on the strip (e.g. "stats for 2023 only"). The
  existing year-chip filter on the map already covers that vibe for
  pins; replicating it on the chip strip is scope creep.
- No persistence — recomputed on every page load. Cheap (one query,
  small datasets per user).
- No chart library. Plain CSS bars. No Chart.js, no D3, no canvas.
- No interactivity on the bar chart in v1. Hover tooltip is fine; no
  click-through.
- No "achievement" copy ("First trip!", "10 countries unlocked!").
  Parked for the achievement system listed in the roadmap's extras.

## Decisions baked in

| Decision | Choice | Why / rejected alternative |
|---|---|---|
| Days vs. nights for the time-away chip | **Days** = (end − start + 1) | Matches `compute_trip_stats.days_away` so the per-trip and lifetime numbers reconcile. Rejected "nights" — would have shown 186 nights on the lifetime page but 21 days on the trip page; inconsistent. |
| Trips that count toward stats | **Only `completed`** | An in-progress trip would inflate "days away" before it's real; an upcoming trip even more so. Matches roadmap. |
| Trips that count toward the map | Unchanged: completed + in-progress (existing `_trip_is_for_lifetime` filter) | The map is "where I've been or am right now"; the stats are "what wrapped up." Two intentionally different sets. |
| Country / city dedup scope | **Across all trips, unique by ISO code (countries) and (city, country_iso) (cities)** | Same dedup `compute_trip_stats` uses; consistent with how A1 counts inside a trip. |
| By-year chart inclusion | **Included in v1** | Pairs naturally with the map's year-filter chips. Pure CSS so no dependency cost. |
| By-year chart data | **Trip count per calendar year** keyed by `start_date.year` | Simplest mental model. A trip that straddles year boundary (rare) contributes once to its start year. Alternative "days per year" was rejected as harder to read at a glance. |
| Chart year range | **min(start_year) to max(start_year)** of completed trips | No padding. A user with one 2024 trip sees one bar. |
| Empty-state behavior (zero completed trips) | **Render strip with zeros + small nudge copy** | Roadmap leaves it open; user requested explicit nudge during 2026-06-07 brainstorm. "Your stats will fill in after your first completed trip." |
| Map placement of strip | **Above the map**, between heading and map div | Roadmap-specified. Matches the visual flow: stats frame, map dominates. |
| Spend on the strip | **Omitted in v1** | Multi-currency aggregation is B3's job. Lifetime "$X spent" with no currency conversion is misleading. |

## Architecture

### New helpers in `src/yearbook.py`

Two pure functions + two dataclasses, mirroring the style of
`compute_trip_stats` and `on_this_day`.

```python
@dataclass
class LifetimeStats:
    """Aggregate totals rendered above the lifetime map."""

    trip_count: int              # number of completed trips
    country_count: int           # unique geocoded_country_code across all trips
    city_count: int              # unique (geocoded_city, geocoded_country_code)
    days_away: int               # sum of (end - start + 1) across completed trips
    flight_count: int            # bookings where type == "flight"
    longest_trip_days: int       # max (end - start + 1); 0 when no trips


@dataclass
class YearBar:
    """One bar in the trips-per-year chart."""

    year: int
    trip_count: int


def compute_lifetime_stats(trips) -> LifetimeStats:
    """Aggregate stats over the user's already-filtered completed trips.

    Each `trip` is expected to expose `.start_date`, `.end_date`,
    `.bookings` (iterable of Booking-like rows), and `.itinerary_items`
    (iterable of ItineraryItem-like rows). Both lists can be empty.

    Returns a LifetimeStats with zeros when `trips` is empty.

    Country / city dedup mirrors compute_trip_stats: only rows with a
    non-empty `geocoded_country_code` contribute; cities additionally
    need `geocoded_city`. A city is unique by `(city, country_iso)`
    so two "Paris" entries in France and Texas count as two cities.
    """


def compute_trips_per_year(trips) -> list[YearBar]:
    """One YearBar per calendar year between the earliest and latest
    completed trip's start_date.year, inclusive. Years with zero trips
    get a YearBar with trip_count=0 so the chart shows the full
    timeline (no gaps). Returns [] when `trips` is empty.

    Keyed by trip.start_date.year — a trip that straddles a year
    boundary counts toward its start year only.
    """
```

The helpers do not import Flask or SQLAlchemy. They operate on
attribute access — the route hands them already-loaded Trip rows whose
relationships are eager-loaded enough for `.bookings` /
`.itinerary_items` to enumerate without an extra query.

### Route change in `app.py`

The existing `lifetime_map()` route at `app.py:1160` loads owned +
collaborator trips, filters via `_trip_is_for_lifetime`, and renders
`lifetime_map.html`. The change:

1. After the existing filter, derive a separate **completed-only**
   list:

   ```python
   completed = [
       t for t in owned + collab
       if t.start_date and t.end_date and derive_status(
           t.start_date, t.end_date, today
       ) == "completed"
   ]
   ```

2. Compute the helpers and pass them to the template:

   ```python
   lifetime_stats = compute_lifetime_stats(completed)
   year_bars = compute_trips_per_year(completed)
   ```

3. Add to `render_template`:

   ```python
   lifetime_stats=lifetime_stats,
   year_bars=year_bars,
   ```

`/map/data.geojson` is unchanged — pins still cover completed +
in-progress, as before. Stats and pins are deliberately scoped to
different sets.

### Template change in `templates/lifetime_map.html`

Insert a stats strip above the year-chip bar (which sits above the
map) and a bar chart below the "Replay animation" link.

```jinja
{# Above the map #}
{% if lifetime_stats.trip_count > 0 %}
  <div class="vp-lifetime-stats mb-3">
    <span class="vp-lifetime-stat">
      🌍 <strong>{{ lifetime_stats.country_count }}</strong> countries
    </span>
    <span class="vp-lifetime-stat">
      🏙️ <strong>{{ lifetime_stats.city_count }}</strong> cities
    </span>
    <span class="vp-lifetime-stat">
      📅 <strong>{{ lifetime_stats.days_away }}</strong> days away
    </span>
    <span class="vp-lifetime-stat">
      ✈️ <strong>{{ lifetime_stats.flight_count }}</strong> flights
    </span>
    <span class="vp-lifetime-stat">
      🧳 <strong>{{ lifetime_stats.trip_count }}</strong> trips
    </span>
    <span class="vp-lifetime-stat">
      🗺️ Longest: <strong>{{ lifetime_stats.longest_trip_days }}</strong> days
    </span>
  </div>
{% else %}
  <div class="vp-lifetime-stats vp-lifetime-stats--empty text-muted small mb-3">
    Your stats will fill in after your first completed trip.
  </div>
{% endif %}
```

The empty-state copy renders even when the map below shows the "No
travel history yet" message — that way the empty page has one
consistent nudge ("here's what's coming") rather than two unrelated
empty boxes.

The chart sits below the existing "Replay animation" link:

```jinja
{% if year_bars %}
  <div class="vp-year-chart mt-4" aria-label="Trips per year">
    <h2 class="h6 text-muted">Trips per year</h2>
    <div class="vp-year-chart__bars">
      {% set max_count = year_bars | map(attribute='trip_count') | max %}
      {% for bar in year_bars %}
        <div class="vp-year-chart__col">
          <div class="vp-year-chart__bar"
               style="height: {{ (bar.trip_count / max_count * 100) | round if max_count else 0 }}%;"
               title="{{ bar.year }}: {{ bar.trip_count }} trip{{ '' if bar.trip_count == 1 else 's' }}">
          </div>
          <div class="vp-year-chart__label">{{ bar.year }}</div>
        </div>
      {% endfor %}
    </div>
  </div>
{% endif %}
```

Zero-trip years still render a column (label shown, bar invisible).
The `title` attribute gives a free hover tooltip without any JS.

### CSS in `static/css/app.css`

Appended at the end of the file. Three new classes:

- `.vp-lifetime-stats` — flex row, gap, wraps on narrow screens. Each
  `.vp-lifetime-stat` is a pill-shaped chip with a soft background
  (`var(--vp-pill-info-bg)` if it exists, else a flat `#f5f5f7` tint).
- `.vp-lifetime-stats--empty` — overrides the strip styling to look
  like a single muted line (no chips, no background — just text).
- `.vp-year-chart` — bounded width, fixed height (`160px` for the
  bars). `.vp-year-chart__bars` is a flex row, `align-items: flex-end`
  so short bars sit on the baseline. Each `.vp-year-chart__col` has a
  fixed width (`32px`) with the bar taking the column's full width.
  Bars use the trip-card accent colour. Labels rotate 0° (no
  rotation needed for 4-digit years if columns stay 32px+).

No JS needed for the chart — the `style="height: ..."` inline is
computed in Jinja so the render is fully static.

## The page experience

### Auth view (user with completed trips)

```
🌍 Your travels

[ 🌍 22 countries ][ 🏙️ 47 cities ][ 📅 186 days away ]
[ ✈️ 34 flights  ][ 🧳 9 trips    ][ 🗺️ Longest: 21 days ]

[ year-chip filter bar — unchanged ]

[ map div — unchanged ]

Replay animation

Trips per year
█ █ █ █ █ █ █ █ █
2017 2018 2019 ... 2025
```

### Auth view (user with only in-progress trips, no completed)

The strip renders the empty-state nudge:

```
🌍 Your travels

Your stats will fill in after your first completed trip.

[ year-chip filter + map render normally for in-progress pins ]

(no chart — year_bars is [])
```

### Auth view (user with zero trips at all)

The existing "No travel history yet" empty-state copy still wins;
the new empty-state nudge stacks above it but reads as a single
coherent "nothing yet" message. (Visually fine — the strip's nudge
is muted small text, not a giant card.)

### Print view

The map page isn't a print-optimised surface. No `@media print`
work in this spec. The strip + chart simply print as-is alongside
the map if a user prints — acceptable, not optimised.

## Edge cases

| Case | Behavior |
|---|---|
| Zero completed trips | Strip shows empty-state nudge; chart hidden. |
| One completed trip | Strip shows real numbers including `Longest: N days`. Chart shows a single bar for that year. |
| Trip with no bookings AND no itinerary items | Counts toward `trip_count` and `days_away` and `longest_trip_days`, contributes zero to country / city / flight counts. |
| Trip straddles year boundary (e.g. Dec 28 2025 – Jan 3 2026) | Counts as one trip in 2025 (its `start_date.year`). All days count toward `days_away`. |
| Same country across multiple trips (e.g. annual Tokyo visits) | Counted once. The `country_count` dedup is on `geocoded_country_code` across all trips. |
| Same city name in two countries (Paris, France vs Paris, Texas) | Counted as two cities — dedup key is `(city, country_iso)`. |
| Booking with `type=None` | Doesn't increment `flight_count`. Doesn't break anything else. |
| Trip with `start_date > end_date` (data corruption) | `days_away` contribution is `end - start + 1` which goes negative. Helper accepts but logs a warning; the route filter already excludes trips where either date is None. Negatives are absorbed quietly — fixing the data is out of scope. |
| All completed trips in the same year | Chart shows one bar; range = `[year, year]`. |
| Multi-year gap (trips in 2018 and 2024, nothing between) | Chart shows bars for every year 2018–2024, with zero-height bars for 2019–2023. Year labels still render. |
| Trip with one geocoded booking and one non-geocoded booking | Non-geocoded row contributes nothing to country / city counts. Geocoded row contributes normally. |
| Collaborator trips | Included exactly as the map already includes them — owned + accepted-collab, both. |
| Trip whose status is overridden manually to "completed" but date-derived is still in_progress | `derive_status(start, end, today)` wins. The user's manual override doesn't inflate stats. Matches A1's defensive `derive_yearbook_view`. |

## Testing

### Unit tests (new) — `tests/test_yearbook.py`

Extend the existing `FakeTrip` dataclass with two fields:

```python
bookings: list = field(default_factory=list)
itinerary_items: list = field(default_factory=list)
```

This keeps existing A1 / A3 tests working (defaults are empty lists)
and lets the new tests pass lists inline.

**`compute_lifetime_stats`** — ~9 tests:

- `test_lifetime_stats_empty_trips_returns_zeros`
- `test_lifetime_stats_single_trip_counts`
- `test_lifetime_stats_days_away_sums_across_trips`
- `test_lifetime_stats_country_dedup_across_trips`
- `test_lifetime_stats_city_dedup_across_trips`
- `test_lifetime_stats_same_city_different_country_counts_twice`
- `test_lifetime_stats_flight_count_only_counts_flights`
- `test_lifetime_stats_longest_trip_days_picks_max`
- `test_lifetime_stats_trip_with_no_rows_counts_for_days_and_trip_count`

**`compute_trips_per_year`** — ~5 tests:

- `test_trips_per_year_empty_trips_returns_empty_list`
- `test_trips_per_year_single_year`
- `test_trips_per_year_multiple_years_fills_gaps_with_zero`
- `test_trips_per_year_keyed_by_start_date_year`
- `test_trips_per_year_two_trips_in_same_year`

### Integration test (new) — `tests/test_routes.py`

One test: `test_lifetime_map_renders_stats_strip_for_user_with_completed_trip`.

Creates a user, owns one completed trip (start/end in the past),
GETs `/map`, asserts:

- Response 200.
- Body contains the string `🧳` (or the more specific
  `<strong>1</strong> trips` substring).
- Body contains `Trips per year` (chart heading present).

A complementary test for the empty state would be nice; if the
project sits at 517 tests as stated, that's one more for ~518–519
total + 14 unit = ~531–532.

### Manual smoke checklist

- `/map` while logged in as a user with at least one completed trip:
  strip renders above the map with non-zero numbers.
- Same user, browser-resize to mobile width: chips wrap, no overflow.
- New user with zero trips: the existing "No travel history yet"
  message still shows AND the strip's empty-state nudge sits above
  it without looking duplicative.
- User with one completed trip in 2024 and one in 2026: chart shows
  three columns (2024, 2025 empty, 2026), labels visible, bars
  drawn correctly.
- Hover a bar: native tooltip shows "2024: 1 trip" / "2026: 2 trips".

## Dependencies

- A1 (Trip Yearbook) — shipped 2026-05-31. We reuse `src/yearbook.py`
  module + `derive_status`-style filter pattern. Helpers slot into
  the same file.
- A3 (On this day) — shipped 2026-06-06. No code dependency; just
  ensures `src/yearbook.py` is the right module home.
- No new external libraries. No schema changes. No new routes.

## Open questions resolved during brainstorm

| Question | Decision |
|---|---|
| Nights vs days for the time-away chip | Days (matches yearbook) |
| By-year chart in v1 or defer | Include in v1 (CSS bars only) |
| Empty-state behavior | Render strip with nudge copy ("Your stats will fill in…") |
| Strip placement | Above the map, above the year-chip filter bar |
| Chart placement | Below the map, below "Replay animation" link |
| Total-spend chip | Out of scope (multi-currency aggregation → B3) |
| Trip-set scope (map vs stats) | Map: completed + in-progress (unchanged). Stats: completed only |
| Year-bar data | Trip count per `start_date.year`; year-boundary trips count once |

## Updating this document

Same convention as A1 / A3. If implementation reveals a design issue,
fix the spec inline and commit `docs: clarify <section> in
lifetime-stats spec`. The spec is the record of "what we agreed to" —
not a frozen artifact.

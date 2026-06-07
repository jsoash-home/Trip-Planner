# Lifetime Stats Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stats strip above the lifetime map at `/map` showing
aggregate totals across the user's completed trips, plus a small
"trips per year" CSS bar chart below the map.

**Architecture:** Two new pure helpers in `src/yearbook.py`
(`compute_lifetime_stats`, `compute_trips_per_year`) returning
`LifetimeStats` / `YearBar` dataclasses. One route extension
(`lifetime_map()`) that derives a completed-only trip list and passes
the helpers' output to the template. One stats-strip block + one
year-chart block in `templates/lifetime_map.html`. No JS, no schema
changes, no new routes.

**Tech Stack:** Python 3.9, Flask, Jinja2, plain CSS, pytest. No new
dependencies.

---

## Spec

Full design: [docs/superpowers/specs/2026-06-07-lifetime-stats-design.md](../specs/2026-06-07-lifetime-stats-design.md)

Read it first. This plan executes that spec.

## Background reading

Before starting, read these to put the patterns in head:

- [src/yearbook.py](../../../src/yearbook.py) — the module the new
  helpers extend. Mirror the style of `compute_trip_stats` for
  shape, dedup, and dataclass conventions.
- [app.py:1160](../../../app.py) — the `lifetime_map` route that
  already loads owned + collaborator trips and filters via
  `_trip_is_for_lifetime`. Plan extends this route only.
- [templates/lifetime_map.html](../../../templates/lifetime_map.html)
  — the template that gets the new strip + chart blocks.
- [tests/test_yearbook.py](../../../tests/test_yearbook.py) —
  `FakeTrip`, `FakeBooking`, `FakeItem` dataclasses. `FakeTrip` gets
  two new default-empty list fields in T1.

---

## File map

**Create:**

- _(none — every change extends existing files)_

**Modify:**

- `src/yearbook.py` — add `LifetimeStats`, `YearBar` dataclasses +
  `compute_lifetime_stats`, `compute_trips_per_year` helpers.
- `tests/test_yearbook.py` — extend `FakeTrip` with `bookings` and
  `itinerary_items` fields; append unit tests for both new helpers.
- `app.py` — derive `completed` trip list inside `lifetime_map()`,
  call helpers, import them, pass to `render_template`.
- `tests/test_routes.py` — append one integration test that the
  `/map` page renders the stats strip.
- `templates/lifetime_map.html` — add the stats strip block above
  the map and the year chart block below "Replay animation".
- `static/css/app.css` — append styles for `.vp-lifetime-stats`,
  `.vp-lifetime-stat`, `.vp-lifetime-stats--empty`,
  `.vp-year-chart`, `.vp-year-chart__bars`, `.vp-year-chart__col`,
  `.vp-year-chart__bar`, `.vp-year-chart__label`.

**Do not modify:**

- `models.py`, the rest of `src/`, the rest of `templates/`. This
  feature is read-only over already-fetched rows.
- The `/map/data.geojson` route — pins still cover completed +
  in-progress, unchanged. Stats and pins are deliberately scoped to
  different sets.

---

## Task 1: Helpers + dataclasses + unit tests

**Files:**

- Modify: `src/yearbook.py`
- Modify: `tests/test_yearbook.py`

**Public surface:**

```python
@dataclass
class LifetimeStats:
    trip_count: int            # completed trips passed in
    country_count: int         # unique geocoded_country_code across all rows
    city_count: int            # unique (geocoded_city, geocoded_country_code)
    days_away: int             # sum of (end - start + 1)
    flight_count: int          # bookings where type == "flight"
    longest_trip_days: int     # max (end - start + 1); 0 when no trips


@dataclass
class YearBar:
    year: int
    trip_count: int


def compute_lifetime_stats(trips) -> LifetimeStats:
    ...


def compute_trips_per_year(trips) -> List[YearBar]:
    ...
```

**Implementation notes:**

- `compute_lifetime_stats`: iterate each trip once; on each iteration
  walk `trip.bookings` + `trip.itinerary_items` for country / city
  dedup (sets across all trips, not per-trip), and `trip.bookings`
  again for flight count. Days math is `(end - start).days + 1` per
  trip; sum into `days_away`, track max into `longest_trip_days`.
- Empty input → return `LifetimeStats(0, 0, 0, 0, 0, 0)`. The
  dataclass needs no special `__post_init__`.
- `compute_trips_per_year`: get all `trip.start_date.year` values,
  compute `(min_year, max_year)`, iterate inclusive. Bucket each
  trip into its `start_date.year`. Year-boundary trips count once
  (their start year only). Empty input → return `[]`.
- City dedup key is `(city, country_iso)` so "Paris" in FR and "Paris"
  in US count as two — same key shape as `compute_trip_stats`.
- Country / city contributions: only count rows whose
  `geocoded_country_code` is truthy. Cities additionally need
  `geocoded_city`.
- A trip with `start_date > end_date` (data corruption) contributes
  a negative `days_away` slice — accept it and `logger.warning(...)`.
  Don't crash. The route filter ensures both dates exist.

**FakeTrip extension in `tests/test_yearbook.py`:**

```python
@dataclass
class FakeTrip:
    start_date: date
    end_date: date
    primary_currency: str = "USD"
    notes: Optional[str] = None
    status: str = "planning"
    id: int = 1
    bookings: list = field(default_factory=list)
    itinerary_items: list = field(default_factory=list)
```

Requires `from dataclasses import field`. Existing A1 / A3 tests
keep working because the defaults are empty lists.

**Test list (compute_lifetime_stats — 9):**

- `test_lifetime_stats_empty_trips_returns_zeros`
- `test_lifetime_stats_single_trip_counts`
- `test_lifetime_stats_days_away_sums_across_trips`
- `test_lifetime_stats_country_dedup_across_trips`
- `test_lifetime_stats_city_dedup_across_trips`
- `test_lifetime_stats_same_city_different_country_counts_twice`
- `test_lifetime_stats_flight_count_only_counts_flights`
- `test_lifetime_stats_longest_trip_days_picks_max`
- `test_lifetime_stats_trip_with_no_rows_counts_for_days_and_trip_count`

**Test list (compute_trips_per_year — 5):**

- `test_trips_per_year_empty_trips_returns_empty_list`
- `test_trips_per_year_single_year`
- `test_trips_per_year_multiple_years_fills_gaps_with_zero`
- `test_trips_per_year_keyed_by_start_date_year`
- `test_trips_per_year_two_trips_in_same_year`

**Verify:** `pytest tests/test_yearbook.py -v` all pass (14 new tests).

**Commit:** `feat: lifetime stats + trips-per-year helpers in src/yearbook.py`

---

## Task 2: Wire helpers into `/map` route + integration test

**Files:**

- Modify: `app.py` (the `lifetime_map` route at app.py:1160 — confirm
  line number)
- Modify: `tests/test_routes.py`

**Route change:**

Inside `lifetime_map()`, after the existing `qualifying` line:

```python
completed = [
    t for t in owned + collab
    if t.start_date and t.end_date
    and derive_status(t.start_date, t.end_date, today) == "completed"
]
lifetime_stats = compute_lifetime_stats(completed)
year_bars = compute_trips_per_year(completed)
```

Pass both to `render_template` alongside `has_any_qualifying_trips`.

**Import additions** at the top of `app.py` — extend the existing
`from src.yearbook import (...)` block to add
`compute_lifetime_stats` and `compute_trips_per_year`. `derive_status`
is already imported.

**Implementation note:** the route already runs `derive_status` only
inside the `_trip_is_for_lifetime` body for pin filtering. Stats need
a separate `completed`-only filter — explicit and obvious in the
route body. Don't try to fold both filters into one helper.

**Integration test list:**

- `test_lifetime_map_renders_stats_strip_for_user_with_completed_trip`

The test creates a user, owns one completed trip (start/end before
today), GETs `/map`, asserts response 200 AND body contains
`<strong>1</strong> trips` AND body contains `Trips per year`.

**Verify:** `pytest tests/test_routes.py -k lifetime_map -v` passes.
Then `pytest tests/ -q` still green (existing map tests must not
regress).

**Commit:** `feat: pass lifetime_stats + year_bars to /map template`

---

## Task 3: Stats strip block + CSS

**Files:**

- Modify: `templates/lifetime_map.html`
- Modify: `static/css/app.css`

**Template insert** — above the existing `vp-stats-bar` div, inside
the existing `{% block content %}`. Render unconditionally (the strip
itself handles both the populated and empty states):

```jinja
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

**Placement note:** insert immediately after the `<h1>` heading. The
empty-state branch renders even when the page below shows "No travel
history yet" — that's intentional per spec.

**CSS additions** (append to `static/css/app.css`):

- `.vp-lifetime-stats` — `display: flex; flex-wrap: wrap; gap: 0.5rem`.
- `.vp-lifetime-stat` — pill: padding `0.35rem 0.75rem`, soft
  background (use existing `--vp-pill-info-bg` token if present, else
  `#f5f5f7`), `border-radius: 999px`, `font-size: 0.9rem`.
- `.vp-lifetime-stats--empty` — overrides: no flex chips, no
  background — just a plain muted small text line (the `text-muted
  small` Bootstrap classes carry most of it; this override just
  removes any `gap` / `padding` the base class adds).

**Manual smoke (after this task):**

- `/map` while logged in as a user with one+ completed trip: strip
  renders with real numbers.
- Same user, mobile-width browser resize: chips wrap, no overflow.
- New user with zero trips: empty-state nudge renders above the "No
  travel history yet" block.

**Commit:** `feat: ✨ lifetime stats chip strip on /map`

---

## Task 4: Year chart block + CSS

**Files:**

- Modify: `templates/lifetime_map.html`
- Modify: `static/css/app.css`

**Template insert** — below the existing "Replay animation" link
inside `{% block content %}`:

```jinja
{% if year_bars %}
  <div class="vp-year-chart mt-4" aria-label="Trips per year">
    <h2 class="h6 text-muted">Trips per year</h2>
    {% set max_count = year_bars | map(attribute='trip_count') | max %}
    <div class="vp-year-chart__bars">
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

**Placement note:** inside the same `{% else %}` branch as the map
itself (the branch that runs when `mapbox_token` exists and there's
travel history), so the chart only shows when the user has data.
When `year_bars` is `[]` (zero completed trips), the entire block
hides — empty-state copy is already in the strip from T3.

**CSS additions** (append to `static/css/app.css`):

- `.vp-year-chart` — block layout, `max-width: 720px`, `margin-top:
  1.5rem`.
- `.vp-year-chart__bars` — `display: flex; align-items: flex-end;
  gap: 0.5rem; height: 160px; border-bottom: 1px solid
  var(--vp-border-color, #dee2e6); padding-bottom: 0.25rem`.
- `.vp-year-chart__col` — `display: flex; flex-direction: column;
  align-items: center; width: 36px; height: 100%`.
- `.vp-year-chart__bar` — `width: 100%; background: var(--vp-accent,
  #6f42c1); border-radius: 4px 4px 0 0; min-height: 0; margin-top:
  auto` (so the bar grows from the baseline).
- `.vp-year-chart__label` — `font-size: 0.75rem; color: var(--bs-secondary-color,
  #6c757d); margin-top: 0.25rem; text-align: center`.

Zero-count bars render with `height: 0%` (collapsed) — the label
still shows so the timeline reads continuously.

**Manual smoke (after this task):**

- User with completed trips in 2024 and 2026 (none in 2025): chart
  renders three columns. 2024 + 2026 bars are visible at the same
  height; 2025 column shows a label with no bar.
- User with one trip: chart renders one column with a full-height
  bar.
- Hover any bar: native browser tooltip shows
  `"YYYY: N trip(s)"`.

**Commit:** `feat: 📊 trips-per-year chart on /map`

---

## Phase boundary checkpoints

After each task, verify before moving on. Stop here if anything is red.

| After task | Verify |
|---|---|
| T1 | `pytest tests/test_yearbook.py -v` all pass (14 new tests). |
| T2 | `pytest tests/test_routes.py -k lifetime_map` passes; full suite still green. |
| T3 | Manual smoke per the T3 list. App imports without error. |
| T4 | Manual smoke per the T4 list. Full suite still green. |

---

## Done when

- 4 tasks committed (one commit per task).
- `pytest` green; new test count = 15 (14 unit + 1 integration). Suite
  lands ~531–532.
- Manual smoke checklists for T3 and T4 completed.
- `docs/PHASE_3_ROADMAP.md` updated: status table row A2 → ✓ shipped,
  plan link populated.

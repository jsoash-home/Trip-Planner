# "On this day" tickler — Design Spec

> **Status:** Approved design, awaiting implementation plan. Phase 3
> feature A3 from [docs/PHASE_3_ROADMAP.md](../../PHASE_3_ROADMAP.md).
> Spec captures the design decisions made during the 2026-06-06
> brainstorm. Depends on A1 (Trip Yearbook) for click-through target;
> A1 shipped 2026-06-06.

## Goal

Add a small dashboard block that surfaces past trips overlapping
today's calendar date — the "on this day in prior years" nostalgia
moment most photo apps do. Empty by default, lights up when the
user has a personal memory worth showing.

The block appears on `/trips`, just above the "Past" section. When
the user has past trips whose date range contains a date with the
same `(month, day)` as today in any prior calendar year, the block
renders that handful of trips as mini cards with a small "Day N · N
years ago" overlay. Each card click-throughs to the trip's yearbook
page from A1.

This is the smallest of the three "A" features (A1 yearbook, A2
lifetime stats, A3 this one). It reuses the `src/yearbook.py` module
from A1 and the existing trip-card macro, so the new surface area is
small and the feature ships in one short session.

## Background and motivation

A1 (Trip Yearbook) made every completed trip individually memorable.
A3 makes the dashboard *itself* memorable on the right days — instead
of being a flat list of trips, it occasionally surfaces "five years
ago today you were in Lisbon" as a small reward for landing on the
page.

The phase 3 roadmap describes the feel:

> 📍 **On this day…**
> Three years ago you were in **Tokyo** — day 4 of *Cherry Blossom 2023*.
> Five years ago you were in **Lisbon** — day 1 of *Portugal 2021*.

We're translating that copy into the existing card grid rather than
prose bullets — the section sits one row above "Past" trips, and
matching the card visuals lets the eye glide naturally from "on this
day" memories into the full past-trip list.

## Scope

**In scope:**
- One new pure helper in `src/yearbook.py` — `on_this_day(trips, today)`
- `OnThisDayEntry` dataclass returned by the helper
- One section block on `/trips` (between "Upcoming" and "Past")
- Reuse of the existing `_trip_card.html` macro with a small overlay
  badge for "Day N · X years ago" / "Last year"
- "+ N more …" expand link when more than 3 entries match
- Unit tests against `FakeTrip` dataclasses (no DB)
- One integration test that the dashboard renders the section

**Out of scope (explicit):**
- No today-view inclusion. Dashboard only.
- No "Hide this card forever" dismissal. The block hides automatically
  when there's nothing to show — that's the only state.
- No backfill of `geocoded_city` onto the card. The trip's own emoji
  + name from the existing card is enough.
- No new route. The expand toggles inline.
- No A2 dependency. A3 lands ahead of A2; A2 will build on A1 + A3
  helpers when it's its turn.
- No persistence of expand state across reloads.

## Architecture

### New helper (`src/yearbook.py`)

```python
from dataclasses import dataclass
from datetime import date

@dataclass
class OnThisDayEntry:
    trip: object        # Trip-like; the dashboard's already-loaded row
    day_number: int     # 1-based day of the trip on the matched date
    years_ago: int      # 1 for last year, 2 for two years ago, …
    matched_date: date  # actual calendar date that matched (for tests)


def on_this_day(trips, today: date) -> list[OnThisDayEntry]:
    """Return one entry per past trip whose [start_date, end_date]
    range contains a date with the same (month, day) as `today` in any
    prior calendar year. Sorted most-recent year first.

    Excludes:
      - trips whose start_date.year == today.year (current-year trips
        don't count as "prior years")
      - trips that don't have any matching calendar date in their range

    Special case: today is Feb 29. In non-leap target years, treat the
    match day as Feb 28 of that year (one branch in the helper).
    """
```

The helper is pure: it takes already-fetched `Trip` rows and a `date`,
returns plain objects. No DB queries inside.

### Route change

`trips_list()` in `app.py` already builds the deduped `trips` list of
owned + collaborator trips. Add one line:

```python
on_this_day_entries = on_this_day(trips, today)
```

Pass `on_this_day_entries` to the template. No new route.

### Template change

`templates/trips_list.html` already has section blocks for Active /
Upcoming / Past. Add a new conditional section between Upcoming and
Past:

```jinja
{% if on_this_day_entries %}
  <h2 class="vp-section-title">✨ On this day</h2>
  <div class="row g-3" data-on-this-day-grid>
    {% for entry in on_this_day_entries[:3] %}
      <div class="col-md-6 col-lg-4">
        {{ trip_card(entry.trip, today, counts, on_this_day=entry) }}
      </div>
    {% endfor %}
    {% for entry in on_this_day_entries[3:] %}
      <div class="col-md-6 col-lg-4" data-on-this-day-extra hidden>
        {{ trip_card(entry.trip, today, counts, on_this_day=entry) }}
      </div>
    {% endfor %}
  </div>
  {% if on_this_day_entries|length > 3 %}
    <button type="button" class="btn btn-link vp-otd-expand"
            data-on-this-day-expand>
      + {{ on_this_day_entries|length - 3 }} more …
    </button>
  {% endif %}
{% endif %}
```

### Trip card overlay

The existing `_trip_card.html` macro takes `(trip, today, counts)`.
Extend its signature with an optional `on_this_day=None` keyword. When
present, two things change:

1. The card's link target switches from `trip_overview` to `yearbook`
   for this trip — clicking an "on this day" card lands on the
   keepsake, not the task-oriented overview.
2. A small overlay badge renders in the card's top-right corner:

```
Day 4 · 3 years ago
```

Phrasing for the right-side fragment:
- `years_ago == 1` → `Last year`
- `years_ago >= 2` → `{years_ago} years ago`

The badge uses existing badge styles (`.vp-pill-new` family) tinted
gold/amber to differentiate from drift / new-item pills. (Exact tint
chosen during implementation — adopt whichever named token in
`app.css` reads warmest against the existing card background.)

### Expand button JS

One tiny inline handler (no new JS file — this is the only behavior):

```javascript
(function () {
  var btn = document.querySelector('[data-on-this-day-expand]');
  if (!btn) return;
  btn.addEventListener('click', function () {
    document.querySelectorAll('[data-on-this-day-extra]').forEach(function (el) {
      el.removeAttribute('hidden');
    });
    btn.remove();
  });
}());
```

Lives in `templates/trips_list.html` inside a `{% block scripts %}` so
it's only loaded on the dashboard.

## Copy and tone

| State | Copy |
|---|---|
| Section header | `✨ On this day` |
| Card badge — last year | `Day {N} · Last year` |
| Card badge — N years ago | `Day {N} · {N} years ago` |
| Expand link | `+ {N} more …` |
| Empty state | Section hidden entirely; nothing rendered. |

The `✨` emoji is intentional — it mirrors the existing emoji-led
section conventions on the dashboard (no emojis on Active/Upcoming/Past
because those are routine, but this one is the small "delight" surface
so it earns a flourish).

No subtitle under the section header. The cards themselves carry all
the meaning.

## Edge cases

| Case | Behavior |
|---|---|
| User has zero past trips | Section hidden. |
| User has past trips but none overlap today | Section hidden. |
| Trip exactly one year old today | Entry shows `Day {N} · Last year`. |
| Today is Feb 29 (leap year) | Match Feb 28 in non-leap target years. The actual day_number derives from the trip's `[start, end]` range containing Feb 28 of that year. |
| Trip range straddles year boundary (Dec 30 – Jan 2) | Helper checks each calendar year in `[start.year, end.year]` independently. A trip ending Jan 2, 2024 contributes to "today is Jan 1" matches. |
| Same trip touches today's date in multiple prior years | Impossible — a trip has one date range, one start year. |
| User is currently on a trip | Irrelevant — current-year trips are excluded by the `year < today.year` filter. The "on this day" block is independent of the active-trip ribbon at the top of base.html. |
| Trip owner email changes | Doesn't matter — the helper takes Trip rows from the route's already-built `owned + shared` list. |

## Testing

Unit tests live in `tests/test_yearbook.py` (the file added with A1).
The existing `FakeTrip` dataclass is reused; no DB.

Approximately 8 unit tests:

- `test_on_this_day_empty_trips_returns_empty`
- `test_on_this_day_past_trip_overlap_returns_entry`
- `test_on_this_day_past_trip_no_overlap_returns_empty`
- `test_on_this_day_current_year_trip_excluded`
- `test_on_this_day_feb_29_today_matches_feb_28_in_non_leap_year`
- `test_on_this_day_multiple_matches_sorted_most_recent_first`
- `test_on_this_day_years_ago_computed_correctly`
- `test_on_this_day_year_boundary_trip_matches_both_calendar_years`

Plus one integration test on the dashboard route in
`tests/test_routes.py`:

- `test_dashboard_renders_on_this_day_section_when_past_trip_matches`

Total new tests: ~9. Suite size after: ~516.

## Dependencies

- A1 (Trip Yearbook) — shipped 2026-06-06. Click-through target is
  `/trips/<id>/yearbook`, which only exists post-A1.
- Geocoding pipeline from Phase 2 — not needed for v1 (we render the
  trip's own emoji + name on the card, not a country flag).
- No new external libraries. No schema changes. No new routes.

## Open questions resolved during brainstorm

| Question | Decision |
|---|---|
| Block placement on dashboard | Above "Past" (between Upcoming and Past) |
| Entry visual treatment | Mini trip cards (reuse `_trip_card.html` macro) |
| Cap on entries shown | 3 visible by default + `+ N more …` expand |
| Click-through target | `/trips/<id>/yearbook` (always) |
| Today-view inclusion | No — dashboard only |
| Year-delta phrasing | `Last year` for 1; `N years ago` for ≥2 |
| Feb 29 handling | Match Feb 28 in non-leap target years |
| Same-year trip handling | Excluded ("prior years" only) |

## Updating this document

If implementation reveals a design issue, fix the spec inline and
commit `docs: clarify <section> in on-this-day spec`. The spec is the
record of "what we agreed to" — not a frozen artifact.

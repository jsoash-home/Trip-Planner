# "On this day" tickler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dashboard section that surfaces past trips overlapping
today's calendar date in prior years — small mini-card grid that
appears above "Past" trips, hidden when nothing matches.

**Architecture:** One new pure helper in `src/yearbook.py`
(`on_this_day`) returning `OnThisDayEntry` rows. One route extension
(`trips_list`) to call the helper. One macro extension
(`_trip_card.html`) so a card can render a "Day N · X years ago"
overlay AND retarget its link to the yearbook page. One new section
block in `trips_list.html` with a tiny inline JS handler for the
"+ N more …" expand.

**Tech Stack:** Python 3.9, Flask, Jinja2, vanilla JS, pytest. No new
dependencies. No schema changes. No new routes.

---

## Spec

Full design: [docs/superpowers/specs/2026-06-06-on-this-day-design.md](../specs/2026-06-06-on-this-day-design.md)

Read it first. This plan executes that spec.

## Background reading

Before starting, read these to put the patterns in head:

- [src/yearbook.py](../../../src/yearbook.py) — the module the new
  helper extends. Mirror the style of `days_overview` /
  `compute_country_list` (pure, dataclass-friendly).
- [app.py:796](../../../app.py) — the `trips_list` route that already
  builds the deduped `trips` list of owned + collaborator trips.
- [templates/_trip_card.html](../../../templates/_trip_card.html) —
  the macro this plan extends with an `on_this_day=None` kwarg.
- [templates/trips_list.html](../../../templates/trips_list.html) —
  the dashboard template that gets the new section.
- [tests/test_yearbook.py](../../../tests/test_yearbook.py) —
  `FakeTrip` dataclass is reused for the new tests.

---

## File map

**Create:**

- _(none — every change extends existing files)_

**Modify:**

- `src/yearbook.py` — add `OnThisDayEntry` dataclass + `on_this_day` helper.
- `tests/test_yearbook.py` — append unit tests for the helper.
- `app.py` — call `on_this_day(trips, today)` in `trips_list`, pass
  result to the template.
- `tests/test_routes.py` — append one integration test that the
  dashboard renders the section.
- `templates/_trip_card.html` — extend the macro signature with
  `on_this_day=None` (overlay badge + link target switch).
- `templates/trips_list.html` — add the section block + inline expand
  JS in `{% block scripts %}`.
- `static/css/app.css` — overlay badge + expand-button styles.

**Do not modify:**

- `models.py`, the rest of `src/`, the rest of `templates/`. This
  feature is read-only over already-fetched data.

---

## Task 1: `on_this_day` helper + tests

**Files:**

- Modify: `src/yearbook.py`
- Modify: `tests/test_yearbook.py`

**Public surface:**

```python
@dataclass
class OnThisDayEntry:
    trip: object           # Trip-like row; carries id, name, cover_emoji, etc.
    day_number: int        # 1-based day of trip on the matched calendar date
    years_ago: int         # 1 for last year, 2 for two years ago, …
    matched_date: date     # the actual calendar date that matched (for tests)


def on_this_day(trips, today: date) -> list:
    """Return one OnThisDayEntry per past trip whose [start_date,
    end_date] range contains a date with the same (month, day) as
    `today` in any prior calendar year. Sorted most-recent year
    first.

    Excludes:
      - trips with start_date.year >= today.year (current/future-year
        trips don't count as "prior years")
      - trips whose range doesn't contain any matching date
    """
```

**Implementation notes:**

- The match day = `today.day` for every target year EXCEPT the
  Feb 29 case: when `today.month == 2 and today.day == 29` and the
  target year is not a leap year, the match day becomes 28. Use
  `calendar.isleap(year)` to detect.
- Iterate target years from `(today.year - 1)` down to
  `min(t.start_date.year for t in trips)` — bounded by the oldest
  trip so the loop is finite and tiny.
- For each trip, intersect its `[start_date, end_date]` with the
  candidate match date for the matching year. If contained,
  `day_number = (matched_date - trip.start_date).days + 1`.
- `years_ago = today.year - matched_date.year`.
- Sort the result list by `years_ago` ascending (most recent first).

**Test list:**

- `test_on_this_day_empty_trips_returns_empty`
- `test_on_this_day_past_trip_overlap_returns_entry`
- `test_on_this_day_past_trip_no_overlap_returns_empty`
- `test_on_this_day_current_year_trip_excluded`
- `test_on_this_day_future_trip_excluded`
- `test_on_this_day_feb_29_today_matches_feb_28_in_non_leap_year`
- `test_on_this_day_multiple_matches_sorted_most_recent_first`
- `test_on_this_day_years_ago_computed_correctly`
- `test_on_this_day_year_boundary_trip_matches_both_calendar_years`

Use `FakeTrip` from `tests/test_yearbook.py` (already present from
A1). No DB needed.

**Commit:** `feat: on_this_day helper + 9 tests in src/yearbook.py`

---

## Task 2: Wire helper into dashboard route + integration test

**Files:**

- Modify: `app.py` (the `trips_list` route at app.py:796 — confirm
  line number)
- Modify: `tests/test_routes.py`

**Route change:**

In `trips_list()`, after `grouped = group_trips_by_state(...)`:

```python
on_this_day_entries = on_this_day(trips, today)
```

Pass `on_this_day_entries=on_this_day_entries` to `render_template`.

**Test list:**

- `test_dashboard_renders_on_this_day_section_when_past_trip_matches`

The test creates a past trip whose `[start, end]` contains today's
`(month, day)` in a prior year, GETs `/trips`, asserts
`"On this day"` appears in the body AND the trip's name appears in
the section.

**Commit:** `feat: pass on_this_day_entries to dashboard template`

---

## Task 3: Extend `_trip_card.html` macro

**Files:**

- Modify: `templates/_trip_card.html`

**Macro signature change:**

```jinja
{% macro trip_card(t, today, counts, on_this_day=None) %}
```

**Behavior when `on_this_day` is not None:**

1. The card's outer `<a href="...">` switches from
   `url_for('trip_overview', trip_id=t.id)` to
   `url_for('yearbook', trip_id=t.id)`.
2. Render a small badge in the card's top-right corner:

```jinja
{% if on_this_day %}
  <span class="vp-otd-badge">
    Day {{ on_this_day.day_number }} ·
    {% if on_this_day.years_ago == 1 %}
      Last year
    {% else %}
      {{ on_this_day.years_ago }} years ago
    {% endif %}
  </span>
{% endif %}
```

Place the badge near the existing pill area (drift / "new" pills
already render top-right; the OTD badge slots into the same row).

**Implementation note:** read the macro first — the existing pill
container shape will dictate exactly where the new badge goes. Don't
duplicate it into a second container if one already exists.

**No tests for this task** — covered by the integration test in
Task 2 (asserts the macro renders without crashing under the new
kwarg) and by Task 4's manual smoke.

**Commit:** `feat: _trip_card on_this_day kwarg — overlay + yearbook link`

---

## Task 4: Dashboard section + expand JS + CSS

**Files:**

- Modify: `templates/trips_list.html`
- Modify: `static/css/app.css`

**Template block** (insert between the Upcoming and Past blocks):

```jinja
{% if on_this_day_entries %}
  <h2 class="vp-section-title">✨ On this day</h2>
  <div class="row g-3">
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
    <button type="button"
            class="btn btn-link vp-otd-expand"
            data-on-this-day-expand>
      + {{ on_this_day_entries|length - 3 }} more …
    </button>
  {% endif %}
{% endif %}
```

**Scripts block** (add to `templates/trips_list.html`; if the file
already has `{% block scripts %}`, extend it instead of replacing):

```jinja
{% block scripts %}
  <script>
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
  </script>
{% endblock %}
```

**CSS** (append to `static/css/app.css`):

- `.vp-otd-badge` — small pill, gold/amber background tint (reuse
  `--vp-pill-drift-*` palette or `--vp-pill-new-*`; pick whichever
  reads warmest), 0.7rem font, `border-radius: 999px`, padding
  `0.15rem 0.55rem`. Positioned in the card's top-right pill row.
- `.vp-otd-expand` — small, muted text-link styling, `margin: 0.5rem 0 1.5rem`.

**Manual smoke (after this task):**

- Make a past trip whose `[start, end]` contains today's `(month,
  day)` from a prior year (edit DB or create one in the UI then
  shift dates with `sqlite3 vacation.db`). Reload `/trips` → ✨ On
  this day section appears with one card; the card's badge reads
  `Day N · Last year` (or `N years ago`).
- Click the card → lands on the yearbook page.
- If you have more than 3 matches, the `+ N more …` link expands
  the rest in place; clicking again does nothing (the link is gone).
- Drop the past trip's date range so it no longer overlaps today →
  the section disappears entirely.

**Commit:** `feat: ✨ On this day section on /trips`

---

## Phase boundary checkpoints

After each task, verify before moving on. Stop here if anything is red.

| After task | Verify |
|---|---|
| T1 | `pytest tests/test_yearbook.py -v` all pass (9 new tests). |
| T2 | `pytest tests/test_routes.py -k on_this_day` passes. |
| T3 | App still imports without error; `pytest tests/ -q` still green; existing `_trip_card` tests still pass. |
| T4 | Manual smoke per the list above. |

---

## Done when

- 4 tasks committed (one commit per task).
- `pytest` green; new test count = 10 (9 unit + 1 integration).
- Manual smoke checklist completed.
- `docs/PHASE_3_ROADMAP.md` updated: status table row A3 → ✓ shipped,
  plan link populated.

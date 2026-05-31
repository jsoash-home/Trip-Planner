# Trip Yearbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Trip Yearbook (Phase 3 feature A1): a per-trip
retrospective page at `/trips/<id>/yearbook` with stats, an
interactive route map, starred-item highlights, markdown notes,
print styling, and an optional public share link.

**Architecture:** One new pure-helpers module (`src/yearbook.py`)
with stats / highlights / sanitize functions. One new column on
`ItineraryItem` (`starred`) and three new columns on `Trip`
(`yearbook_share_token`, `yearbook_public_show_notes`,
`yearbook_public_show_spend`). Five new routes in `app.py`. One
new template (`yearbook.html`) used in three modes (preview / final
/ public) via a `view_mode` flag. The interactive Mapbox GL map on
the auth view falls back to a Mapbox static-image URL for print +
public-share contexts.

**Tech Stack:** Python 3.9, Flask, SQLAlchemy, Jinja2, Mapbox GL JS
(already loaded for /map), Mapbox Static-Image API (no new SDK —
just URL building), pytest. No new dependencies.

---

## Spec

Full design: [docs/superpowers/specs/2026-05-31-trip-yearbook-design.md](../specs/2026-05-31-trip-yearbook-design.md)

Read it first. This plan executes that spec.

## Background reading

Before starting, read these to put the patterns in head:

- [models.py](../../../models.py) — `Trip` and `ItineraryItem`
  tables we're adding columns to.
- [src/trip_helpers.py](../../../src/trip_helpers.py) — the style
  `src/yearbook.py` mirrors (pure, dataclasses, no DB).
- [src/map_helpers.py](../../../src/map_helpers.py) — extends with
  one new function for static-image URLs. Note the existing `Pin`
  dataclass.
- [app.py:494](../../../app.py) — `_trip_with_access_or_404` is the
  guard every trip-scoped route uses.
- [app.py:572](../../../app.py) — `_section_tiles_for(trip)` builds
  the tiles row; we extend it with a yearbook tile.
- [app.py:951](../../../app.py) — `_build_pins_for_trip(trip)` already
  exists; reuse for both interactive and static map.

---

## File map

**Create:**

- `src/yearbook.py` — pure helpers (stats / highlights / sanitize /
  view-derivation / share-token generation).
- `tests/test_yearbook.py` — unit tests for the helpers.
- `templates/yearbook.html` — the page (used in preview / final /
  public modes via a `view_mode` flag).
- `templates/base_public.html` — stripped layout for public yearbook
  (no navbar, no auth chrome, no yearbook JS bundle).
- `static/js/yearbook.js` — star toggle on itinerary page +
  interactive Mapbox mount on yearbook page.

**Modify:**

- `models.py` — add `ItineraryItem.starred` and three `Trip` columns.
- `migrate_schema.py` (or whatever bootstrap exists; verify on Task 1)
  — additive ALTER statements.
- `src/map_helpers.py` — add `build_static_map_url`.
- `app.py` — add 5 routes, extend `_section_tiles_for` with the
  yearbook tile.
- `templates/trip_itinerary.html` — add ★ button per item card.
- `tests/test_map_helpers.py` — extend with `build_static_map_url`
  cases.
- `tests/test_app_routes.py` (or wherever route tests live) — extend
  with the 5 new routes' integration tests. Verify file location
  before adding.
- `static/css/app.css` — yearbook styling + `@media print` rules.

**Do not modify:**

- `src/trip_helpers.py`, `src/itinerary.py`, `src/booking_helpers.py`,
  `src/budget.py`, `src/packing.py`, `src/sharing.py`,
  `src/currency.py`, `src/drift_review.py`, `src/geocoding.py` —
  yearbook helpers go in their own module.

---

## Task 1: Schema migration

**Files:**

- Modify: `models.py`
- Run: whatever the project uses to apply schema (per CLAUDE.md, the
  app auto-bootstraps DB on startup — verify by reading `app.py`'s DB
  init block. If it's pure `db.create_all()`, additive columns may
  require manual `ALTER TABLE` on existing SQLite. Use
  `sqlite3 vacation.db` to apply if needed.)

**Columns added:**

| Table | Column | SQLAlchemy type | Default | Index |
|---|---|---|---|---|
| `itinerary_item` | `starred` | `db.Boolean, nullable=False` | `False` | no |
| `trip` | `yearbook_share_token` | `db.String(32), nullable=True` | `None` | yes (unique) |
| `trip` | `yearbook_public_show_notes` | `db.Boolean, nullable=False` | `False` | no |
| `trip` | `yearbook_public_show_spend` | `db.Boolean, nullable=False` | `True` | no |

**ALTER statements for existing local SQLite (apply in this order):**

```sql
ALTER TABLE itinerary_item ADD COLUMN starred BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE trip ADD COLUMN yearbook_share_token VARCHAR(32);
CREATE UNIQUE INDEX ix_trip_yearbook_share_token ON trip (yearbook_share_token);
ALTER TABLE trip ADD COLUMN yearbook_public_show_notes BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE trip ADD COLUMN yearbook_public_show_spend BOOLEAN NOT NULL DEFAULT 1;
```

**Verify:**
`sqlite3 vacation.db ".schema trip"` and
`sqlite3 vacation.db ".schema itinerary_item"` show new columns.

**Commit:** `feat: schema for yearbook — starred + share token columns`

---

## Task 2: `src/yearbook.py` pure helpers + tests

**Files:**

- Create: `src/yearbook.py`
- Create: `tests/test_yearbook.py`

**Public surface:**

```python
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

@dataclass
class TripStats:
    days_away: int
    country_count: int
    city_count: int
    bookings_by_type: dict  # {"flight": 2, "hotel": 3, ...}
    spend_by_category: dict  # {"transport": {"USD": 850.0}, ...}
    biggest_spend_category: Optional[str]
    starred_count: int

def compute_trip_stats(trip, bookings, itinerary) -> TripStats: ...

def compute_highlight_items(itinerary_items) -> dict:
    """Returns {day_number: [item, ...]}. Days with zero stars absent.
    Sort within day reuses src.itinerary.sort_within_day."""

def compute_country_list(bookings, itinerary) -> list:
    """List of country names in order of first appearance. Dedup.
    Excludes rows without geocoded country_iso."""

def derive_yearbook_view(trip, today: date) -> Literal["hidden", "preview", "final"]:
    """Maps trip status (recomputed from dates) to view mode.
    planning/upcoming -> hidden, in_progress -> preview, completed -> final."""

def sanitize_public_view(view_model: dict, *, show_notes: bool, show_spend: bool) -> dict:
    """Returns a copy of view_model with private fields removed.
    Always strips: per-booking confirmation_number, per-booking cost,
    collaborator names.
    Conditional: notes (only if show_notes), spend_by_category +
    biggest_spend_category + total spend (only if show_spend)."""

def generate_share_token() -> str:
    """Opaque token via secrets.token_urlsafe(24). ~32 chars URL-safe."""

@dataclass
class DayOverview:
    number: int           # 1-based
    date: date
    items: list           # list[ItineraryItem]; empty if no items that day

def days_overview(trip, itinerary_items) -> list:
    """Returns one DayOverview per day in [trip.start_date, trip.end_date].
    Days with zero items still appear (empty items list). Used by the
    'All days at a glance' strip on the yearbook."""
```

**Implementation notes:**

- `compute_trip_stats.days_away` = `(trip.end_date - trip.start_date).days + 1`.
  1-day trips → 1.
- `country_count` / `city_count` aggregate over both bookings and
  itinerary items that have geocoded coords. Country key is
  `country_iso`; city key is `(geocoded_city, country_iso)` tuple.
  Skip rows where either is NULL.
- `biggest_spend_category` picks the category with the largest spend
  in the trip's primary currency (use the first booking with a
  non-null currency, or the trip's first currency-bearing field if
  one exists; if multiple currencies and no clear primary, return
  None and skip the "Biggest" line in the template).
- `compute_highlight_items` uses `_day_index(trip, item.day_date)`
  pattern from app.py:941 — but pure: pass `trip_start_date` as an
  arg and compute inline.

**Test list** (write in `tests/test_yearbook.py`):

- `test_compute_trip_stats_basic_shape`
- `test_compute_trip_stats_empty_inputs`
- `test_compute_trip_stats_multi_currency_no_cross_sum`
- `test_compute_trip_stats_days_away_one_day_trip`
- `test_compute_trip_stats_days_away_eight_day_trip`
- `test_compute_trip_stats_country_dedup`
- `test_compute_trip_stats_city_dedup`
- `test_compute_trip_stats_starred_count`
- `test_compute_trip_stats_biggest_spend_category_single_currency`
- `test_compute_trip_stats_biggest_spend_category_none_when_no_costs`
- `test_compute_highlight_items_only_starred`
- `test_compute_highlight_items_grouped_by_day`
- `test_compute_highlight_items_empty_days_absent`
- `test_compute_highlight_items_sorted_within_day_by_time`
- `test_compute_country_list_dedup`
- `test_compute_country_list_first_appearance_order`
- `test_compute_country_list_skips_null_country_iso`
- `test_derive_yearbook_view_planning_hidden`
- `test_derive_yearbook_view_upcoming_hidden`
- `test_derive_yearbook_view_in_progress_preview`
- `test_derive_yearbook_view_completed_final`
- `test_sanitize_public_view_always_strips_confirmation_number`
- `test_sanitize_public_view_always_strips_booking_cost`
- `test_sanitize_public_view_strips_notes_when_show_notes_false`
- `test_sanitize_public_view_keeps_notes_when_show_notes_true`
- `test_sanitize_public_view_strips_spend_when_show_spend_false`
- `test_sanitize_public_view_keeps_spend_when_show_spend_true`
- `test_generate_share_token_is_url_safe_32_chars`
- `test_generate_share_token_returns_unique_values`
- `test_days_overview_returns_one_per_day_in_range`
- `test_days_overview_empty_day_has_empty_items_list`
- `test_days_overview_groups_items_by_day_date`

Use `dataclass`-based `FakeBooking` / `FakeItem` / `FakeTrip` stand-ins
following the pattern in `tests/test_packing.py` — no DB.

**Commit:** `feat: src/yearbook.py pure helpers + 29 tests`

---

## Task 3: Star toggle route

**Files:**

- Modify: `app.py` — new route
- Modify: `tests/test_app_routes.py` (verify file name first)

**Route:**

```
POST /trips/<int:trip_id>/items/<int:item_id>/star
  Guard: _trip_with_access_or_404(trip_id, role="editor")
  Body: none (toggle)
  Behavior:
    - Load ItineraryItem by id; 404 if not found OR if item.trip_id != trip_id
    - Flip item.starred
    - db.session.commit()
    - Return JSON: {"starred": new_value}
```

**Test list:**

- `test_star_toggle_editor_flips_false_to_true`
- `test_star_toggle_editor_flips_true_to_false`
- `test_star_toggle_owner_allowed`
- `test_star_toggle_viewer_forbidden`  (403)
- `test_star_toggle_non_collaborator_404`
- `test_star_toggle_item_belongs_to_different_trip_404`
- `test_star_toggle_unknown_item_404`

**Commit:** `feat: POST /items/<id>/star route + tests`

---

## Task 4: Star button on itinerary page

**Files:**

- Create: `static/js/yearbook.js` (first slice — star handler only)
- Modify: `templates/trip_itinerary.html`
- Modify: `static/css/app.css`

**HTML per itinerary card** (insert before/after the existing card
title; pattern lives in the current itinerary template — read it
first):

```html
<button type="button"
        class="btn btn-link p-0 star-toggle"
        data-item-id="{{ item.id }}"
        data-trip-id="{{ trip.id }}"
        aria-pressed="{{ 'true' if item.starred else 'false' }}"
        aria-label="{{ 'Unstar' if item.starred else 'Star' }} this highlight"
        {% if user_role == 'viewer' %}disabled{% endif %}>
  <span class="star-icon">{{ '★' if item.starred else '☆' }}</span>
</button>
```

**`static/js/yearbook.js` — star section:**

```javascript
// Optimistic-update star toggle.
// Find every .star-toggle, attach click handler.
// On click: read data-item-id + data-trip-id, swap glyph + aria-pressed
// optimistically, POST to /trips/<trip>/items/<item>/star, on non-2xx
// revert and show a brief error chip (reuse existing toast/chip pattern
// if there is one; otherwise a 2s fade-out span).
```

**CSS** (`static/css/app.css`):

- `.star-toggle` — no border, color: muted gray for ☆.
- `.star-toggle[aria-pressed="true"] .star-icon` — color: gold
  (`#f5b400` or similar; check existing palette).
- `.star-toggle:disabled` — opacity 0.5, cursor not-allowed.

**Manual smoke:**

- Star an item → glyph fills, persists on reload.
- As viewer (open in second browser as collaborator with role=viewer):
  button is disabled.
- Disconnect network in DevTools → click star → reverts after
  failure.

**Commit:** `feat: ★ star toggle on itinerary cards`

---

## Task 5: Authenticated yearbook route + skeleton template

**Files:**

- Modify: `app.py` — new GET route + extend `_section_tiles_for`
- Create: `templates/yearbook.html`
- Modify: `templates/trip_overview.html` (only if the tile renders via
  a partial that needs adjustment; typically `_section_tiles.html`
  handles it)

**Route:**

```
GET /trips/<int:trip_id>/yearbook
  Guard: _trip_with_access_or_404(trip_id, role="viewer")
  Behavior:
    - today = date.today()
    - view_mode = derive_yearbook_view(trip, today)
    - if view_mode == "hidden": abort(404)
    - bookings = trip.bookings (eager loaded)
    - itinerary = trip.itinerary_items (eager loaded)
    - stats = compute_trip_stats(trip, bookings, itinerary)
    - highlights = compute_highlight_items(itinerary)
    - countries = compute_country_list(bookings, itinerary)
    - render yearbook.html with {trip, stats, highlights, countries,
        view_mode, user_role}
  Returns 200 (preview or final) or 404 (hidden).
```

**`_section_tiles_for` extension:**

Add a new tile dict to the list it returns:

```python
{
    "key": "yearbook",
    "label": "Yearbook",
    "emoji": "📓",
    "subtitle": _yearbook_tile_subtitle(trip, today),
    "url": url_for("yearbook", trip_id=trip.id) if not _yearbook_hidden(trip, today) else None,
    "disabled": _yearbook_hidden(trip, today),
}
```

`_yearbook_tile_subtitle` returns:
- "After the trip" when hidden
- "Preview while in progress" when preview
- f"{stats.starred_count} highlights" when final (compute stars
  cheaply with a `db.session.query(...).filter(starred=True).count()`)

**`templates/yearbook.html` skeleton** (this task: hero + numbers +
notes; map and highlights land in Tasks 6 & 7):

```jinja
{% extends "base.html" %}
{% block content %}
<div class="yearbook">
  <header class="yearbook-hero">
    <div class="yearbook-emoji">{{ trip.cover_emoji or '🧳' }}</div>
    <h1>{{ trip.name }}</h1>
    <p class="yearbook-dates">{{ trip.start_date.strftime('%b %-d') }} – {{ trip.end_date.strftime('%b %-d, %Y') }}</p>
    {% if view_mode == "preview" %}
      <div class="alert alert-warning yearbook-preview-banner">
        🚧 Trip still in progress — this is a preview of your yearbook.
      </div>
    {% endif %}
  </header>

  <section class="yearbook-numbers">
    <div class="chip">📅 {{ stats.days_away }} days</div>
    <div class="chip">🌍 {{ stats.country_count }} countries</div>
    <div class="chip">🏙️ {{ stats.city_count }} cities</div>
    {% for type, n in stats.bookings_by_type.items() %}
      <div class="chip">{{ type_emoji(type) }} {{ n }} {{ type }}s</div>
    {% endfor %}
  </section>

  {# Spend row #}
  {% if stats.spend_by_category %}
    <section class="yearbook-spend">
      <div class="chip">💰
        {% for currency, total in flatten_spend(stats.spend_by_category) %}
          {{ format_money(total, currency) }}{% if not loop.last %} + {% endif %}
        {% endfor %}
      </div>
      {% if stats.biggest_spend_category %}
        <span class="muted">· Biggest: {{ stats.biggest_spend_category }}</span>
      {% endif %}
    </section>
  {% endif %}

  {# Notes #}
  {% if trip.notes %}
    <section class="yearbook-notes card">
      <div class="card-body markdown">{{ trip.notes | markdown }}</div>
    </section>
  {% endif %}
</div>
{% endblock %}
```

Helper functions `type_emoji(type)` and `flatten_spend(spend_dict)` —
keep small inline filters or add to a Jinja-context-registered helper
file. `format_money` already exists in `src/currency.py`.

**Test list (route):**

- `test_yearbook_planning_returns_404`
- `test_yearbook_upcoming_returns_404`
- `test_yearbook_in_progress_returns_200_with_preview_banner`
- `test_yearbook_completed_returns_200_no_preview_banner`
- `test_yearbook_viewer_allowed`
- `test_yearbook_non_collaborator_404`
- `test_yearbook_renders_stats_chips`
- `test_yearbook_renders_notes_when_present`
- `test_yearbook_skips_notes_section_when_blank`

**Manual smoke:**

- Set a trip's end_date to yesterday → yearbook tile shows
  "N highlights" subtitle; page renders without preview banner.
- Set a trip's status range to "in_progress" → tile shows
  "Preview while in progress"; page shows warning banner.

**Commit:** `feat: /yearbook route + page skeleton (hero + numbers + notes)`

---

## Task 6: Interactive Mapbox GL map block on yearbook

**Files:**

- Modify: `app.py` — yearbook route: build pins + add to view model
- Modify: `templates/yearbook.html`
- Modify: `static/js/yearbook.js`
- Modify: `static/css/app.css`

**Route additions:**

```python
pins = _build_pins_for_trip(trip)  # existing helper, app.py:951
pins_geojson = pins_to_geojson(pins, color_for_category)  # from src.map_helpers
# Pass both pins_geojson and the static URL (computed in Task 8) to template.
# For now: just pins_geojson + MAPBOX_TOKEN.
```

**Template addition** (insert between numbers and notes sections):

```jinja
{% if pins_geojson.features %}
  <section class="yearbook-map">
    <div id="yearbook-map"
         data-pins='{{ pins_geojson | tojson | e }}'
         data-token="{{ mapbox_token }}"></div>
  </section>
{% endif %}
```

**`static/js/yearbook.js` — map section:**

- On `DOMContentLoaded`: find `#yearbook-map`. If present and Mapbox
  GL is loaded (script tag in base.html — verify it's there from
  Phase 2 map work; load conditionally if not), mount a map
  centered on the pins' bounding box (use the same fit-bounds
  approach as the in-trip `/map` page; copy the bbox-from-features
  helper if separate).
- Add the same color-by-category styled circle layer as the in-trip
  map.

**CSS:**

```css
.yearbook-map { margin: 2rem 0; }
#yearbook-map { height: 360px; border-radius: 8px; }
@media (max-width: 600px) { #yearbook-map { height: 240px; } }
```

**Test list:**

- `test_yearbook_renders_map_block_when_pins_exist`
- `test_yearbook_omits_map_block_when_no_pins`
- `test_yearbook_passes_geojson_to_template`

**Manual smoke:**

- Open a yearbook for a trip with geocoded pins → interactive map
  renders, can pan/zoom, pins colored by category.
- Open a yearbook for a trip with no geocoded data → map section
  doesn't render.

**Commit:** `feat: interactive Mapbox GL map on yearbook page`

---

## Task 7: Highlights + days-at-a-glance + yearbook tile polish

**Files:**

- Modify: `templates/yearbook.html`
- Modify: `static/css/app.css`
- Modify: `app.py` (only if `_section_tiles_for` needs additional
  data passed; otherwise no change)

**Template additions:**

**Highlights section** (after the map):

```jinja
<section class="yearbook-highlights">
  <h2>★ Highlights{% if stats.starred_count %} ({{ stats.starred_count }}){% endif %}</h2>
  {% if highlights %}
    {% for day_num, items in highlights.items() | sort %}
      <div class="yearbook-day">
        <h3>Day {{ day_num }} · {{ day_date_for(trip, day_num).strftime('%b %-d') }}</h3>
        {% for item in items %}
          {% include "_yearbook_highlight_card.html" %}
        {% endfor %}
      </div>
    {% endfor %}
  {% else %}
    <p class="muted">
      {% if view_mode == "preview" %}
        ★ Star items on your itinerary as the trip unfolds — they'll show up here.
      {% else %}
        ★ Star items on your itinerary to remember the standouts.
      {% endif %}
      <a href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">Go to itinerary →</a>
    </p>
  {% endif %}
</section>
```

**Create `templates/_yearbook_highlight_card.html`:**

```jinja
<div class="yearbook-card category-{{ item.category }}">
  <div class="yearbook-card__title">{{ item.title }}</div>
  {% if item.time %}<div class="yearbook-card__time">{{ item.time.strftime('%I:%M %p') }}</div>{% endif %}
  {% if item.location %}<div class="yearbook-card__location">📍 {{ item.location }}</div>{% endif %}
  {% if item.notes %}<div class="yearbook-card__notes markdown">{{ item.notes | markdown }}</div>{% endif %}
</div>
```

**All-days strip** (after highlights):

```jinja
<section class="yearbook-days">
  <h2>All days at a glance</h2>
  {% for day in days_overview(trip, itinerary) %}
    <div class="yearbook-day-row">
      <div class="yearbook-day-row__header">
        Day {{ day.number }} · {{ day.date.strftime('%a %b %-d') }}
      </div>
      <div class="yearbook-day-row__chips">
        {% for item in day.items %}
          <span class="chip category-{{ item.category }}"
                title="{{ item.title }}{% if item.time %} · {{ item.time }}{% endif %}">
            {{ item.title }}
          </span>
        {% endfor %}
      </div>
    </div>
  {% endfor %}
</section>
```

`days_overview(trip, itinerary)` was defined in T2 — it lives in
`src/yearbook.py` and returns a list of `DayOverview` dataclasses. The
route passes the result into the template; no Jinja filter needed.

**Test list:**

- `test_yearbook_highlights_section_with_zero_stars_shows_nudge`
- `test_yearbook_highlights_section_with_stars_renders_day_groups`
- `test_yearbook_all_days_strip_renders_every_day_in_range`
- `test_yearbook_all_days_empty_day_renders_empty_chip_row`
- `test_yearbook_tile_subtitle_planning_says_after_trip`
- `test_yearbook_tile_subtitle_in_progress_says_preview`
- `test_yearbook_tile_subtitle_completed_shows_starred_count`

**Manual smoke:**

- Star 3 items across 2 days, reload yearbook → Highlights section
  shows day-grouped cards.
- Trip with 8 days, items only on day 3 → All-days strip shows 8
  rows, day 3 has chips, others empty.

**Commit:** `feat: highlights + all-days strip on yearbook + tile polish`

---

## Task 8: Static-image map helper + share token route + visibility settings

**Files:**

- Modify: `src/map_helpers.py` — add `build_static_map_url`
- Modify: `tests/test_map_helpers.py` — add cases
- Modify: `app.py` — two new routes
- Modify: `tests/test_app_routes.py`

**`src/map_helpers.py` addition:**

```python
def build_static_map_url(
    pins: List[Pin],
    width: int = 600,
    height: int = 360,
    style: str = "streets-v12",
    token: Optional[str] = None,
) -> Optional[str]:
    """Build a Mapbox static-image URL with markers from pins.
    Returns None if token is missing OR pins is empty.

    URL shape:
      https://api.mapbox.com/styles/v1/mapbox/{style}/static
        /{markers}/auto/{width}x{height}@2x?access_token={token}

    Markers are comma-separated pin-s+{color}({lng},{lat}) entries.
    color comes from color_for_category(pin.category).
    URL-encode markers segment (the parens and commas)."""
```

Use the standard library only (no requests; we're just building a
URL string). `urllib.parse.quote` for encoding the markers segment.

**Test list (map_helpers):**

- `test_build_static_map_url_empty_pins_returns_none`
- `test_build_static_map_url_no_token_returns_none`
- `test_build_static_map_url_single_pin_format`
- `test_build_static_map_url_multiple_pins_comma_separated`
- `test_build_static_map_url_includes_width_height_in_path`
- `test_build_static_map_url_uses_color_for_category`

**Routes:**

```
POST /trips/<int:trip_id>/yearbook/share
  Guard: _trip_with_access_or_404(trip_id, role="editor")
  Pre-check: derive_yearbook_view(trip, today) must be "final";
             else return 400 with JSON {"error": "available after trip completes"}
  Body: JSON {"action": "enable" | "disable" | "rotate"}
  Behavior:
    enable  -> if token already set: no-op; else set token = generate_share_token(); commit
    rotate  -> set token = generate_share_token(); commit
    disable -> set token = None; commit
  Response JSON: {"token": Optional[str], "url": Optional[str]}
    url = url_for("yearbook_public", token=token, _external=True) when token set else None

POST /trips/<int:trip_id>/yearbook/visibility
  Guard: _trip_with_access_or_404(trip_id, role="editor")
  Body: JSON {"show_notes": bool, "show_spend": bool}
  Behavior:
    Persist to trip.yearbook_public_show_notes / yearbook_public_show_spend; commit
  Response JSON: {"show_notes": bool, "show_spend": bool}
```

**Test list (routes):**

- `test_share_enable_creates_token`
- `test_share_enable_again_is_idempotent`
- `test_share_rotate_replaces_token`
- `test_share_disable_clears_token`
- `test_share_on_in_progress_trip_returns_400`
- `test_share_on_planning_trip_returns_400`
- `test_share_viewer_forbidden`
- `test_visibility_toggle_persists`
- `test_visibility_viewer_forbidden`

**Commit:** `feat: build_static_map_url + share/visibility toggle routes`

---

## Task 9: Public yearbook route + share UI on auth view

**Files:**

- Modify: `app.py` — new GET public route
- Create: `templates/base_public.html`
- Create: `templates/_yearbook_body.html` — extract page content to a
  shared partial so auth + public templates can each extend a
  different base while sharing the body
- Create: `templates/yearbook_public.html` — thin shell extending
  `base_public.html` and including `_yearbook_body.html`
- Modify: `templates/yearbook.html` — becomes a thin shell extending
  `base.html` and including `_yearbook_body.html`; move existing
  page content into `_yearbook_body.html`
- Modify: `static/js/yearbook.js` — share toggle handler

**`templates/base_public.html`:**

A stripped-down clone of `base.html` with:
- No navbar / user dropdown
- No yearbook JS bundle (`<script src="/static/js/yearbook.js">` omitted)
- No Mapbox GL JS tag (the public view uses the static image only)
- Same CSS includes (bootstrap, app.css)
- Footer: small "📓 Powered by Vacation Planner" link
- `<meta name="robots" content="noindex, nofollow">` in `<head>`

**Public route:**

```
GET /yearbook/<string:token>
  No auth.
  Behavior:
    trip = Trip.query.filter_by(yearbook_share_token=token).first()
    if trip is None: abort(404)
    today = date.today()
    if derive_yearbook_view(trip, today) != "final": abort(404)
    bookings = trip.bookings
    itinerary = trip.itinerary_items
    stats = compute_trip_stats(trip, bookings, itinerary)
    highlights = compute_highlight_items(itinerary)
    pins = _build_pins_for_trip(trip)
    static_map_url = build_static_map_url(pins, 600, 360, MAPBOX_STYLE, MAPBOX_TOKEN)
    view_model = {
        trip, stats, highlights, static_map_url,
        view_mode="public",
    }
    view_model = sanitize_public_view(
        view_model,
        show_notes=trip.yearbook_public_show_notes,
        show_spend=trip.yearbook_public_show_spend,
    )
    response = make_response(render_template("yearbook_public.html", **view_model))
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
```

**Template structure (two thin shells + shared partial):**

`templates/yearbook.html` (auth view, modified from Task 5):
```jinja
{% extends "base.html" %}
{% block content %}
  {% include "_yearbook_body.html" %}
{% endblock %}
```

`templates/yearbook_public.html` (new):
```jinja
{% extends "base_public.html" %}
{% block content %}
  {% include "_yearbook_body.html" %}
{% endblock %}
```

`templates/_yearbook_body.html` (new) — contains everything currently
inside `{% block content %}` in the existing yearbook.html: hero,
numbers, map block, highlights, all-days strip, notes, share UI,
footer actions. All conditional rendering already keys off
`view_mode` and `user_role`, which are passed to both templates.

(Migration step during this task: move the existing body content
out of yearbook.html into _yearbook_body.html, then replace
yearbook.html with the thin shell above. No content changes; pure
extraction.)

**Map block** (replace earlier interactive-only block):

```jinja
{% if static_map_url or pins_geojson.features %}
  <section class="yearbook-map">
    {% if static_map_url %}
      <img class="yearbook-map__static" src="{{ static_map_url }}" alt="Trip route">
    {% endif %}
    {% if view_mode != "public" and pins_geojson.features %}
      <div id="yearbook-map" class="yearbook-map__interactive"
           data-pins='{{ pins_geojson | tojson | e }}'
           data-token="{{ mapbox_token }}"></div>
    {% endif %}
  </section>
{% endif %}
```

In the JS, when mounting Mapbox into `#yearbook-map`, also hide the
sibling `.yearbook-map__static` (`element.style.display = "none"`).
Print CSS (Task 10) swaps them.

**Share-toggle UI** (insert at bottom of yearbook.html when
`view_mode == "final"`):

```jinja
{% if view_mode == "final" and user_role in ("editor", "owner") %}
  <section class="yearbook-share">
    <h2>Share publicly</h2>
    {% if trip.yearbook_share_token %}
      <div class="share-on">
        <input type="text" readonly value="{{ url_for('yearbook_public', token=trip.yearbook_share_token, _external=True) }}" id="share-url">
        <button class="btn btn-sm" data-action="copy">Copy</button>
        <button class="btn btn-sm btn-warning" data-action="rotate">New link</button>
        <button class="btn btn-sm btn-danger" data-action="disable">Revoke</button>
      </div>
      <div class="share-visibility">
        <label><input type="checkbox" data-vis="show_notes" {% if trip.yearbook_public_show_notes %}checked{% endif %}> Include notes</label>
        <label><input type="checkbox" data-vis="show_spend" {% if trip.yearbook_public_show_spend %}checked{% endif %}> Include spend totals</label>
      </div>
    {% else %}
      <div class="share-off">
        🔒 Yearbook is private
        <button class="btn btn-sm btn-primary" data-action="enable">Create public link</button>
      </div>
    {% endif %}
  </section>
{% endif %}
```

**JS for share UI** (in `static/js/yearbook.js`):

- Wire up `data-action` buttons → POST to `/trips/<id>/yearbook/share`
  with the right action; on success, reload the page (simpler than
  partial swap; the UI is small).
- Wire up `data-vis` checkboxes → POST to
  `/trips/<id>/yearbook/visibility` with both current checkbox
  values; no reload needed.
- Copy button → uses `navigator.clipboard.writeText(input.value)`,
  flashes "Copied!".

**Test list:**

- `test_public_yearbook_valid_token_renders`
- `test_public_yearbook_unknown_token_404`
- `test_public_yearbook_token_on_in_progress_trip_404`
- `test_public_yearbook_response_has_noindex_header`
- `test_public_yearbook_strips_confirmation_numbers`
- `test_public_yearbook_strips_booking_costs`
- `test_public_yearbook_hides_notes_when_toggle_off`
- `test_public_yearbook_includes_notes_when_toggle_on`
- `test_public_yearbook_hides_spend_when_toggle_off`
- `test_public_yearbook_uses_base_public_template`
- `test_auth_yearbook_still_renders_after_partial_extraction`

**Manual smoke:**

- Mark a trip `completed`. On yearbook page, click "Create public
  link" → URL appears. Open URL in incognito → public page renders,
  no navbar, no costs, no confirmation #s.
- Toggle "Include notes" off → reload incognito → notes section gone.
- Click "Revoke" → reopen incognito URL → 404.

**Commit:** `feat: public /yearbook/<token> route + share UI`

---

## Task 10: Print stylesheet + static-image fallback wiring

**Files:**

- Modify: `static/css/app.css`
- Modify: `app.py` — yearbook route also passes `static_map_url` to
  auth view (already does in public route from Task 9; mirror that
  here)

**Route addition (auth view):**

```python
static_map_url = build_static_map_url(pins, 600, 360, MAPBOX_STYLE, MAPBOX_TOKEN)
```

Pass into the template alongside `pins_geojson`. The template from
Task 9 already renders both — interactive on top, static beneath,
JS hides the static one on mount.

**CSS** (`@media print` block):

```css
@media print {
  /* Hide chrome */
  .navbar, .footer, .yearbook-share, .yearbook-preview-banner,
  .star-toggle, .btn { display: none !important; }

  /* Hide interactive map, show static */
  #yearbook-map { display: none !important; }
  .yearbook-map__static { display: block !important; }

  /* Page breaks */
  .yearbook-day, .yearbook-day-row { page-break-inside: avoid; }
  .yearbook-highlights, .yearbook-days { page-break-before: auto; }

  /* Type */
  body { font-size: 11pt; }
  h1 { font-size: 24pt; }
  h2 { font-size: 16pt; }

  /* Margins */
  @page { margin: 1.5cm; }
}
```

**Footer actions block** (add to `yearbook.html` if not already
present from Task 5):

```jinja
{% if view_mode != "public" %}
  <footer class="yearbook-footer">
    <button class="btn" onclick="window.print()">Print</button>
  </footer>
{% endif %}
```

**Manual smoke (print specifically):**

- Open yearbook for a completed trip with map + highlights.
- Cmd+P (browser print preview).
- Expected: static map image, no navbar, no footer buttons, no
  preview banner, day sections don't split awkwardly across pages.
- Repeat for in_progress (preview) view → preview banner hidden in
  print (good — print is meant for the keepsake).
- Repeat for public view → already no navbar; no footer buttons;
  static map; same print behavior.

**Commit:** `feat: print stylesheet + static map fallback`

---

## Phase boundary checkpoints

After each phase, verify before moving on. Stop here if anything
is red.

| After task | Verify |
|---|---|
| T1 | `sqlite3 vacation.db ".schema trip"` shows new columns; app starts without error |
| T2 | `pytest tests/test_yearbook.py -v` all pass |
| T4 | Star button works in browser; persists; viewer disabled |
| T5 | Yearbook tile + page render in browser for in_progress + completed |
| T7 | Highlights + all-days strip render correctly |
| T9 | Public link works in incognito; sanitization confirmed |
| T10 | Print preview is clean across all three view modes |

---

## Done when

- 10 tasks committed (one commit per task minimum).
- `pytest` green; new test count ≈ 35 added.
- Manual smoke checklist in spec § Testing completed.
- Spec linked from the Phase 3 roadmap row marked ✓ with this
  plan path.
- `docs/PHASE_3_ROADMAP.md` updated:
  status table row A1 → ✓, plan link populated.

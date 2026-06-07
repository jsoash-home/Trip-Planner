# Weather Forecast on Itinerary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a weather chip on each itinerary day inside a 14-day
window, a hero chip on the trip overview's Today section during a
trip, and a `/settings` page where the user picks metric or imperial
units. Forecasts come from Open-Meteo (no API key) and are cached for
6 hours.

**Architecture:** One new SQLAlchemy model (`WeatherCache`), one new
column on `User` (`weather_units`), one new module (`src/weather.py`)
with pure helpers + impure API/cache layer, one new route
(`/settings`), two template integrations (itinerary day header + trip
overview Today hero), Bootstrap popovers. No new Python packages —
`requests` already present.

**Tech Stack:** Python 3.9, Flask, SQLAlchemy, Open-Meteo HTTP API,
Bootstrap 5.3 popover JS, pytest with `requests.get` mocked.

---

## Spec

Full design: [docs/superpowers/specs/2026-06-07-weather-forecast-design.md](../specs/2026-06-07-weather-forecast-design.md)

Read it first. This plan executes that spec.

## Background reading

Before starting, read these to put the patterns in head:

- [src/geocoding.py](../../../src/geocoding.py) — the closest
  existing analog: external API + cache table + freshness check.
  Mirror its style for `src/weather.py`.
- [models.py:291](../../../models.py) — `GeocodeCache` for the
  shape of an opaque cache row.
- [app.py:283](../../../app.py) — `_run_safe_alters` for the
  additive `ALTER TABLE` pattern used to add the new column.
- [templates/_today_section.html](../../../templates/_today_section.html)
  — the partial that already renders the Today section on trip
  overview; T7 extends it.
- [templates/trip_itinerary.html](../../../templates/trip_itinerary.html)
  — the per-day rendering this plan adds the chip to.
- [tests/test_geocoding.py](../../../tests/test_geocoding.py) —
  the mocking pattern (`@patch("src.geocoding.requests.get")`)
  for testing impure API code.

---

## File map

**Create:**

- `src/weather.py` — module with dataclasses + pure helpers +
  API client + cache wrapper.
- `tests/test_weather.py` — unit tests for everything in
  `src/weather.py`.
- `templates/settings.html` — settings form page.

**Modify:**

- `models.py` — add `weather_units` column to `User`; add
  `WeatherCache` model.
- `app.py` — call `_run_safe_alters` for `user.weather_units`;
  add `/settings` GET + POST; extend `trip_overview` and
  `trip_itinerary` to load forecasts.
- `tests/test_routes.py` — append `/settings`, itinerary chip, and
  trip overview hero chip integration tests.
- `templates/trip_itinerary.html` — chip on each day header +
  inline popover init script.
- `templates/_today_section.html` — hero chip at top of Today.
- `templates/base.html` (or wherever the navbar dropdown lives) —
  add "Settings" link entry above "Sign out".
- `static/css/app.css` — append `.vp-weather-chip` and
  `.vp-weather-hero` styles.

**Do not modify:**

- `src/geocoding.py`, the rest of `src/`. Weather is its own
  module; reuse-by-example not by edit.

---

## Task 1: Migration + WeatherCache model + User.weather_units

**Files:**

- Modify: `models.py`
- Modify: `app.py` (the `_run_safe_alters` block)

**Schema (one shot, hard to recover — be careful):**

`User.weather_units` — `db.Column(db.String(10), nullable=False,
default="metric")`.

`WeatherCache` (new table):

| Column | Type | Notes |
|---|---|---|
| `id` | `Integer` PK | autoincrement |
| `lat_rounded` | `Float` not null | indexed (composite) |
| `lng_rounded` | `Float` not null | indexed (composite) |
| `forecast_date` | `Date` not null | indexed (composite) |
| `temp_unit` | `String(10)` not null | `'celsius'` or `'fahrenheit'` |
| `high_temp` | `Float` not null | |
| `low_temp` | `Float` not null | |
| `precipitation_probability` | `Integer` nullable | 0..100 |
| `humidity` | `Integer` nullable | 0..100 |
| `wmo_code` | `Integer` not null | Open-Meteo daily `weather_code` |
| `hourly_json` | `Text` nullable | 4-slot JSON string |
| `fetched_at` | `DateTime` not null, default `datetime.utcnow` | TTL anchor |

Composite unique index on
`(lat_rounded, lng_rounded, forecast_date, temp_unit)` named
`uq_weather_cache_key`.

**`_run_safe_alters` addition (in `app.py`):**

```python
"ALTER TABLE user ADD COLUMN weather_units VARCHAR(10) NOT NULL DEFAULT 'metric'",
```

Wrap in the existing `try/except OperationalError: pass` pattern so
re-runs don't crash.

`WeatherCache` table itself is created via the existing
`db.create_all()` call on startup.

**Implementation notes:**

- Use `datetime.utcnow` (not `datetime.now`) for `fetched_at` —
  matches `GeocodeCache`.
- The composite index is the only thing making cache lookups fast;
  don't skip it.

**No tests for this task** — schema changes are smoke-tested by T2's
imports. Manual smoke: `sqlite3 vacation.db ".schema weather_cache"`
should show the table.

**Commit:** `feat: WeatherCache model + User.weather_units column`

---

## Task 2: src/weather.py pure helpers + dataclasses + tests

**Files:**

- Create: `src/weather.py`
- Create: `tests/test_weather.py`

**Public surface:**

```python
WMO_TO_EMOJI: dict[int, str]   # full table per spec
DEFAULT_EMOJI: str = "🌡️"
DEFAULT_WINDOW_DAYS: int = 14
CACHE_TTL_SECONDS: int = 6 * 60 * 60

@dataclass
class DayForecast:
    date: date
    high: float
    low: float
    temp_unit: str               # "celsius" | "fahrenheit"
    wmo_code: int
    emoji: str
    precipitation_probability: Optional[int]
    humidity: Optional[int]
    hourly: list                 # [{"hour": int, "temp": float, "code": int}, ...]


def wmo_code_to_emoji(code: int) -> str: ...
def is_in_forecast_window(d: date, today: date,
                          window_days: int = DEFAULT_WINDOW_DAYS) -> bool: ...
def cache_key_for(lat: float, lng: float, d: date, unit: str) -> tuple: ...
def format_temperature(value: float, unit: str) -> str: ...
def pick_day_coords(items_for_day, trip_fallback_coords): ...
```

**Implementation notes:**

- `format_temperature` returns `"14°"` for either unit (no `C`/`F`
  suffix — the page context makes the unit obvious). Use `round()`
  then `int()`.
- `pick_day_coords`: scan `items_for_day` in given order, return
  `(item.geocoded_lat, item.geocoded_lng)` for the first item with
  both set. If none, return `trip_fallback_coords` (a tuple or
  None). If both empty, return None.
- `is_in_forecast_window`: inclusive on both ends. `today` →
  in. `today + window_days - 1` → in. `today + window_days` → out.

**Test list (~19):**

`wmo_code_to_emoji`:
- `test_wmo_code_to_emoji_known_code`
- `test_wmo_code_to_emoji_unknown_returns_default`
- `test_wmo_code_to_emoji_boundary_codes`

`is_in_forecast_window`:
- `test_is_in_forecast_window_today_is_in`
- `test_is_in_forecast_window_last_day_in_window`
- `test_is_in_forecast_window_one_past_window_excluded`
- `test_is_in_forecast_window_yesterday_excluded`

`cache_key_for`:
- `test_cache_key_for_rounds_to_two_decimals`
- `test_cache_key_for_includes_unit`
- `test_cache_key_for_negative_coords`

`format_temperature`:
- `test_format_temperature_celsius_integer`
- `test_format_temperature_fahrenheit_integer`
- `test_format_temperature_fractional_rounds`
- `test_format_temperature_subzero`

`pick_day_coords`:
- `test_pick_day_coords_first_item_wins`
- `test_pick_day_coords_skips_items_without_coords`
- `test_pick_day_coords_falls_back_to_trip_coords`
- `test_pick_day_coords_returns_none_when_nothing_available`
- `test_pick_day_coords_uses_tuple_fallback`

**Use `FakeItem` style** small local dataclasses in
`tests/test_weather.py` — don't depend on the yearbook fakes.

**Verify:** `pytest tests/test_weather.py -v` all pass.

**Commit:** `feat: src/weather.py pure helpers + dataclasses + 19 tests`

---

## Task 3: fetch_forecast (Open-Meteo client) + tests

**Files:**

- Modify: `src/weather.py`
- Modify: `tests/test_weather.py`

**Public surface:**

```python
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 5.0

def fetch_forecast(lat: float, lng: float, *, unit: str,
                   start_date: date, end_date: date) -> Optional[dict]:
    """Single Open-Meteo API call. Returns raw JSON dict on 200;
    None on any error (4xx, 5xx, timeout, missing keys)."""
```

**Implementation notes:**

- `unit` is `"metric"` or `"imperial"` — map to
  `temperature_unit=celsius|fahrenheit` in the query.
- Pass `timezone=auto` so daily/hourly values are local-time keyed.
- `daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,relative_humidity_2m_mean`
- `hourly=temperature_2m,weather_code`
- Catch `requests.RequestException`, `ValueError`, `KeyError` and
  return `None`. Always `logger.warning(...)` first.
- 5s timeout.

**Test list (~3, with `@patch("src.weather.requests.get")`):**

- `test_fetch_forecast_success_returns_dict`
- `test_fetch_forecast_5xx_returns_none`
- `test_fetch_forecast_network_error_returns_none`

**Verify:** `pytest tests/test_weather.py -v` all pass.

**Commit:** `feat: Open-Meteo fetch_forecast client + 3 tests`

---

## Task 4: get_forecast_for_day (cache wrapper) + tests

**Files:**

- Modify: `src/weather.py`
- Modify: `tests/test_weather.py`

**Public surface:**

```python
def get_forecast_for_day(lat: float, lng: float, d: date, *,
                         unit: str, db_session) -> Optional[DayForecast]:
    """Cache-first. Returns None on a miss whose API call also
    fails. Side effect: writes a WeatherCache row on a successful
    fetch."""
```

**Implementation notes:**

- Compute `cache_key = cache_key_for(lat, lng, d, temp_unit)` where
  `temp_unit = "celsius" if unit == "metric" else "fahrenheit"`.
- Query `WeatherCache` by the composite key columns. If fresh
  (`fetched_at + CACHE_TTL_SECONDS > utcnow`), build a
  `DayForecast` from the row and return.
- If stale or missing, call `fetch_forecast(lat, lng, unit=unit,
  start_date=d, end_date=d)`.
- If fetch fails (returns None), return None — do NOT delete a
  stale row. Stale data is still better than no data on a
  subsequent recovery? On reflection, prefer to keep stale rows
  invisible: the page just doesn't show a chip. Document this.
- If fetch succeeds, parse the daily + hourly values; build the
  4-slot hourly micro-strip; insert/update the cache row with
  `commit()`; return the `DayForecast`.
- Hourly micro-strip extraction: take Open-Meteo's `hourly.time`
  list, find indices whose hour-of-day is in `{6, 12, 18, 22}`,
  pull the corresponding `temperature_2m` and `weather_code`.
- On `IntegrityError` (race condition writing the same key from
  two requests), rollback and re-query — return the row the other
  process wrote.

**Test list (~5):**

- `test_get_forecast_for_day_cache_hit_no_api_call`
- `test_get_forecast_for_day_cache_miss_fetches_and_writes`
- `test_get_forecast_for_day_stale_cache_refetches`
- `test_get_forecast_for_day_api_failure_returns_none`
- `test_get_forecast_for_day_different_unit_separate_cache`

Tests use the Flask app fixture from `tests/conftest.py` so
`db.session` works against a real (in-memory) DB. Mock
`src.weather.fetch_forecast`.

**Verify:** `pytest tests/test_weather.py -v` all pass.

**Commit:** `feat: cache-first get_forecast_for_day + 5 tests`

---

## Task 5: /settings page + navbar link + tests

**Files:**

- Modify: `app.py`
- Create: `templates/settings.html`
- Modify: `templates/base.html` (or the navbar partial — read first)
- Modify: `tests/test_routes.py`

**Route surface:**

```python
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings(): ...
```

GET renders `settings.html` with `current_user`.

POST:
- Read `weather_units` from form data.
- Validate: must be `"metric"` or `"imperial"`. On invalid value,
  flash `"Invalid units selection."` and re-render without saving.
- On valid: write to `current_user.weather_units`, `db.session.commit()`,
  flash `"Settings updated."`, redirect to `/settings`.

**Template structure (`settings.html`):**

Mirror the existing simple form pattern (e.g. `trip_new.html`):
extends `base.html`, single `<form method="post">` with a radio
group bound to `weather_units`, a Save button, and the flash
container.

**Navbar:** Read the navbar partial first to find the dropdown.
Insert a `<a class="dropdown-item" href="{{ url_for('settings') }}">⚙️ Settings</a>`
above the sign-out link.

**Test list:**

- `test_settings_get_renders_form_with_current_unit`
- `test_settings_post_updates_user_weather_units`
- `test_settings_post_rejects_invalid_unit`

**Verify:** `pytest tests/test_routes.py -k settings` passes.
Full suite green.

**Commit:** `feat: /settings page with weather units toggle`

---

## Task 6: Itinerary per-day chips + popover + CSS + test

**Files:**

- Modify: `app.py` (the `trip_itinerary` view — find the route)
- Modify: `templates/trip_itinerary.html`
- Modify: `static/css/app.css`
- Modify: `tests/test_routes.py`

**Route change:** in the `trip_itinerary` view, after building the
grouped-by-day items, derive a `day_forecasts` dict
`{day_date: DayForecast}`:

```python
trip_fallback = _trip_primary_coords(trip)  # see implementation note
day_forecasts = {}
for day_date, items in by_day.items():
    if not is_in_forecast_window(day_date, today):
        continue
    coords = pick_day_coords(items, trip_fallback)
    if coords is None:
        continue
    lat, lng = coords
    fc = get_forecast_for_day(
        lat, lng, day_date,
        unit=current_user.weather_units, db_session=db.session,
    )
    if fc:
        day_forecasts[day_date] = fc
```

Pass `day_forecasts` and a `format_temperature` Jinja-callable to
the template.

**Implementation note — `_trip_primary_coords`:** small private
helper in `app.py`. Find the most common `(geocoded_lat,
geocoded_lng)` pair across the trip's bookings + items where both
are non-null. Return `None` if no rows have coords. Don't over-
engineer — a few lines.

**Template change:** in the day-header render block, append:

```jinja
{% set day_forecast = day_forecasts.get(day_date) %}
{% if day_forecast %}
  <button type="button"
          class="vp-weather-chip btn btn-link p-0 ms-2"
          data-bs-toggle="popover"
          data-bs-html="true"
          data-bs-trigger="click focus"
          data-bs-title="{{ day_date.strftime('%a, %b %d') }}"
          data-bs-content='{% include "_weather_popover_content.html" %}'>
    {{ day_forecast.emoji }}
    {{ format_temperature(day_forecast.high, day_forecast.temp_unit) }}
    /
    {{ format_temperature(day_forecast.low, day_forecast.temp_unit) }}
  </button>
{% endif %}
```

`_weather_popover_content.html` (new tiny partial) renders the
popover body: condition text, humidity, precip%, 4-slot hourly
strip. Reuses `day_forecast` from the parent scope.

**Inline init script** at the bottom of `trip_itinerary.html`:

```javascript
document.querySelectorAll('[data-bs-toggle="popover"]').forEach(
  function (el) { new bootstrap.Popover(el); }
);
```

**CSS additions:**

```css
.vp-weather-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.6rem;
  background: var(--vp-surface-2);
  color: var(--vp-text);
  border-radius: 999px;
  font-size: 0.85rem;
  text-decoration: none;
}
.vp-weather-chip:hover {
  background: var(--vp-accent-soft);
}
```

**Test list:**

- `test_itinerary_renders_weather_chip_for_today` (patch
  `src.weather.fetch_forecast` to return a fixed dict so cache
  miss path runs; assert chip emoji + temp markup in body)
- `test_itinerary_skips_chip_for_day_beyond_window`
- `test_weather_failure_does_not_break_itinerary_page` (patch
  fetch to return None; assert 200 + no chip in body)

**Manual smoke:**

- View an upcoming-trip itinerary with today within the next 14
  days. Chips render for in-window days. Click a chip: popover
  opens with humidity / precip / hourly strip.
- View a far-future trip. No chips.

**Commit:** `feat: 🌦️ weather chip per itinerary day + popover`

---

## Task 7: Trip overview Today hero chip + test

**Files:**

- Modify: `app.py` (the `trip_overview` view)
- Modify: `templates/_today_section.html`
- Modify: `static/css/app.css`
- Modify: `tests/test_routes.py`

**Route change:** in `trip_overview`, when
`derive_status(...) == "in_progress"` AND
`is_in_forecast_window(today, today)`:

```python
trip_fallback = _trip_primary_coords(trip)
todays_items = sort_within_day([
    i for i in trip.itinerary_items if i.day_date == today
])
coords = pick_day_coords(todays_items, trip_fallback)
today_forecast = (
    get_forecast_for_day(coords[0], coords[1], today,
                         unit=current_user.weather_units,
                         db_session=db.session)
    if coords else None
)
```

Pass `today_forecast` to the template / partial.

**Template change** in `_today_section.html`, at the top of the
section:

```jinja
{% if today_forecast %}
  <div class="vp-weather-hero mb-2">
    <span class="vp-weather-hero__emoji">{{ today_forecast.emoji }}</span>
    <span class="vp-weather-hero__temp">
      {{ format_temperature(today_forecast.high, today_forecast.temp_unit) }}
      /
      {{ format_temperature(today_forecast.low, today_forecast.temp_unit) }}
    </span>
    {% if today_forecast.precipitation_probability %}
      <span class="vp-weather-hero__meta text-muted small">
        💧 {{ today_forecast.precipitation_probability }}%
      </span>
    {% endif %}
  </div>
{% endif %}
```

**CSS additions:**

```css
.vp-weather-hero {
  display: inline-flex;
  align-items: baseline;
  gap: 0.6rem;
}
.vp-weather-hero__emoji {
  font-size: 1.6rem;
}
.vp-weather-hero__temp {
  font-size: 1.1rem;
  font-weight: 600;
}
```

**Test list:**

- `test_trip_overview_today_section_renders_hero_chip` — set a
  trip with today inside its range; patch
  `src.weather.fetch_forecast`; assert hero markup in body.

**Manual smoke:**

- Mark a trip as in_progress (or wait for one to be). Overview
  page shows hero chip at the top of Today.
- Trip with no geocoded rows + no fallback: no hero chip; page
  still renders fine.

**Commit:** `feat: 🌤️ weather hero chip on trip overview Today section`

---

## Phase boundary checkpoints

After each task, verify before moving on. Stop here if anything is red.

| After task | Verify |
|---|---|
| T1 | App starts; `sqlite3 vacation.db ".schema weather_cache"` shows the table; `user.weather_units` column present. |
| T2 | `pytest tests/test_weather.py -v` all pass (~19 tests). |
| T3 | `pytest tests/test_weather.py -v` (~22 tests now). |
| T4 | `pytest tests/test_weather.py -v` (~27 tests). |
| T5 | `pytest tests/test_routes.py -k settings -v` passes; full suite green. Manual: navigate to `/settings`, toggle, save. |
| T6 | `pytest tests/test_routes.py -k itinerary` passes; full suite green. Manual: chip renders on in-window day, popover opens. |
| T7 | Full suite green. Manual: hero chip on in-progress trip overview. |

---

## Done when

- 7 tasks committed (one commit per task).
- `pytest` green; new test count = ~33 (~27 unit + ~6 integration).
  Suite lands ~565.
- Manual smoke checklists for T5, T6, T7 completed.
- `docs/PHASE_3_ROADMAP.md` updated: status table row B1 → ✓
  shipped, plan link populated.

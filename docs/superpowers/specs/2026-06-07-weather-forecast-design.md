# Weather Forecast on Itinerary — Design Spec

> **Status:** Approved design, awaiting implementation plan. Phase 3
> feature B1 from [docs/PHASE_3_ROADMAP.md](../../PHASE_3_ROADMAP.md).
> Spec captures the design decisions made during the 2026-06-07
> brainstorm. First feature in the "plan smarter" thread; A1 / A2 / A3
> shipped 2026-05-31 through 2026-06-07.

## Goal

Show a small weather chip on each itinerary day that falls within
the next 14 days. The chip carries the day's high/low and a
condition emoji (🌧️ 14° / 8°). Tapping the chip opens a popover
with humidity, precipitation chance, and an hourly micro-strip.

Within the trip overview's Today section (the section that lights
up when `derive_status == "in_progress"`), a larger hero chip
renders at the top of the section — same data shape, bigger
treatment.

A small `/settings` page is added so the user can choose between
metric and imperial units. The preference persists on the `User`
row and applies everywhere weather renders.

This is the first "plan smarter" feature and the first place the
app calls a non-Mapbox external API. Open-Meteo is free, requires
no API key, and allows commercial use — the integration is
specifically chosen to avoid the friction of provisioning a
weather-API key.

## Background and motivation

The phase 3 roadmap calls weather the highest-payoff helper in the
"plan smarter" thread:

> 🌧️ 14° / 8° — Day 3, Paris

Travelers actually want to know what to pack and what to do.
Geocoding shipped in phase 2 already pinned an itinerary day to a
lat/lng; this feature stops at the threshold of asking "what's the
weather there?" and answers it.

The cache pattern mirrors `src/geocoding.py` + `GeocodeCache`:
external API + cache table + freshness check. Lazy on page load
(no background job) is fine for v1.

## Scope

**In scope:**

- One new SQLAlchemy model `WeatherCache` keyed by
  `(lat_rounded_to_2dp, lng_rounded_to_2dp, date)`.
- One new column `User.weather_units` (`metric` | `imperial`,
  default `metric`).
- One new `src/weather.py` module:
  - Pure helpers: `is_in_forecast_window`,
    `wmo_code_to_emoji`, `format_temperature`, `pick_day_coords`,
    `cache_key_for`.
  - Impure (mocked in tests): `fetch_forecast` (Open-Meteo client),
    `get_forecast_for_day` (cache-first, returns
    `Optional[DayForecast]`).
- One new `/settings` page (GET + POST) where the unit toggle lives.
  Linked from the navbar user dropdown.
- Itinerary template: small chip on each day header within the
  14-day window.
- Trip overview "Today" section: large hero chip at the top of the
  section when `derive_status == "in_progress"` and today is
  in-window.
- Popover content: humidity, precipitation chance, condition
  description, and a 4-slot hourly micro-strip (morning / midday /
  evening / night) using Bootstrap's existing popover JS.
- Unit tests for every pure helper. Integration tests for the
  itinerary page chip render, the `/settings` POST round-trip, and
  the cache hit/miss path (with `requests.get` mocked).

**Out of scope (explicit):**

- No precipitation totals, no wind speed, no UV index in v1 —
  popover stays compact.
- No "long-range" climate guess for days beyond the 14-day window.
  The chip simply doesn't render. The spec calls this out as a
  deliberate honesty choice.
- No push notifications, no "rain alert" emails. Pure render-time.
- No per-trip / per-day unit override. Units are user-global.
- No imperial-with-metric-secondary display ("14°C / 57°F"). Pick
  one, show it cleanly.
- No background prefetch job. Forecasts populate on page load.
  Acceptable because trip itinerary pages are infrequent.
- No multi-provider fallback. If Open-Meteo is down, chips just
  don't render that page load.
- No "yesterday's weather" backlook on completed days. Only
  forward-looking days within the window.
- No B3-style currency profile fields on the new `/settings` page
  in v1 (B3 will add them when it ships).

## Decisions baked in

| Decision | Choice | Why / rejected alternative |
|---|---|---|
| Provider | **Open-Meteo** (`https://api.open-meteo.com/v1/forecast`) | Free, no API key, commercial use allowed, generous rate limits. Roadmap-specified. |
| Forecast window | **14 calendar days from today** (inclusive of today) | Roadmap-specified. Open-Meteo natively supports 16 days; we cap at 14 to leave a safety margin and align with the "useful planning horizon." |
| Day-representative coords | **First geocoded itinerary item on that day** (sorted by `sort_within_day`); fallback to the trip's primary city (mode of `geocoded_city` across all bookings + itinerary). If neither exists, no chip. | Matches roadmap. Simple to reason about. |
| Cache key | **`(round(lat, 2), round(lng, 2), iso_date)`** | 2 decimal places ≈ 1.1 km — fine for daily weather. Coalesces nearby items in the same city to one API call. |
| Cache TTL | **6 hours** | Roadmap-specified. Forecast doesn't shift dramatically within a day; one fetch per location per six hours is plenty. |
| Units | **`User.weather_units`** column, `metric` (default) or `imperial`. | User chose. Open-Meteo natively accepts `temperature_unit=celsius|fahrenheit` so we pass through the preference at fetch time. |
| Settings page | **New `/settings` route + template added in B1** | User decided in the design brainstorm; pre-emptive scaffolding for B3 which will add the currency dropdown to the same page. |
| Chip placement | **One chip per day header on the itinerary page** | User chose. Renders inline next to "Day N · {date}" so the eye lands on it without scanning. |
| Today-view chip | **Hero chip at the top of the Today section on trip overview** | User chose. Bigger / bolder than the per-day chip; renders only when `derive_status == "in_progress"` AND today is in-window. |
| Popover content | **Humidity %, precipitation probability %, condition text, 4-slot hourly micro-strip** | Roadmap covers humidity, precip, hourly. The 4-slot strip (06 / 12 / 18 / 22 local time) is a v1 compromise — keeps the popover compact while gesturing at "hourly". |
| Emoji map | **WMO weather code → emoji** lookup (see `wmo_code_to_emoji` below) | Open-Meteo returns WMO code; map to a small fixed table. |
| Failure mode | **API error / network failure → no chip; log a warning. NO error banner on the page.** | Weather is enrichment, not core. A red banner above the itinerary because the API blipped would feel broken. |

## Architecture

```
                  ┌──────────────────────────────────────┐
                  │  Open-Meteo API  (no key required)   │
                  └─────────────────▲────────────────────┘
                                    │
                          ┌─────────┴────────────┐
                          │  src/weather.py      │
                          │  fetch_forecast()    │
                          │  get_forecast_for_day│
                          │  (cache-first)       │
                          └─────────▲────────────┘
                                    │
                          ┌─────────┴────────────┐
                          │   WeatherCache table │
                          │  (lat, lng, date)    │
                          │   TTL 6 hours        │
                          └─────────▲────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                                                       │
        ▼                                                       ▼
┌──────────────────────────┐                  ┌────────────────────────────┐
│ GET /trips/<id>/itinerary│                  │ GET /trips/<id>            │
│ (chip per day in window) │                  │ (hero chip on Today)       │
└──────────────────────────┘                  └────────────────────────────┘
                                                            │
                                                            ▼
                                                ┌────────────────────────────┐
                                                │ GET / POST /settings       │
                                                │  (unit toggle)             │
                                                └────────────────────────────┘
```

### Data model changes

| Table | Column | Type | Default | Notes |
|---|---|---|---|---|
| `user` | `weather_units` | String(10) | `'metric'` | `'metric'` or `'imperial'`. Validated by route. |
| `weather_cache` (new) | `id` | Integer | — | PK |
| `weather_cache` | `lat_rounded` | Float | — | rounded to 2 decimal places |
| `weather_cache` | `lng_rounded` | Float | — | rounded to 2 decimal places |
| `weather_cache` | `forecast_date` | Date | — | The forecast's calendar date |
| `weather_cache` | `temp_unit` | String(10) | — | `celsius` or `fahrenheit` — cached per unit so flipping the toggle still hits cache for previously-fetched dates |
| `weather_cache` | `high_temp` | Float | — | numeric high in `temp_unit` |
| `weather_cache` | `low_temp` | Float | — | numeric low |
| `weather_cache` | `precipitation_probability` | Integer | nullable | 0–100; null when API omits |
| `weather_cache` | `humidity` | Integer | nullable | mean daily humidity %; null when omitted |
| `weather_cache` | `wmo_code` | Integer | — | Open-Meteo's daily `weather_code` |
| `weather_cache` | `hourly_json` | Text | nullable | JSON-encoded 4-slot hourly strip: `[{"hour": 6, "temp": 12, "code": 2}, ...]` |
| `weather_cache` | `fetched_at` | DateTime | `utcnow` | TTL anchor — `fetched_at + 6h < utcnow` → re-fetch |
| `weather_cache` | composite index | — | — | `(lat_rounded, lng_rounded, forecast_date, temp_unit)` unique |

Migration uses the same additive `ALTER TABLE` pattern as the
existing column adds in `app.py:_run_safe_alters()`.

### `src/weather.py` (new module)

```python
WMO_TO_EMOJI: dict[int, str] = {
    0: "☀️",      # Clear sky
    1: "🌤️",     # Mainly clear
    2: "⛅",      # Partly cloudy
    3: "☁️",      # Overcast
    45: "🌫️",    # Fog
    48: "🌫️",    # Depositing rime fog
    51: "🌦️",    # Drizzle: light
    53: "🌦️",
    55: "🌧️",
    56: "🌧️",
    57: "🌧️",
    61: "🌧️",    # Rain: slight
    63: "🌧️",
    65: "🌧️",
    66: "🌧️",
    67: "🌧️",
    71: "🌨️",    # Snow fall
    73: "🌨️",
    75: "🌨️",
    77: "🌨️",
    80: "🌦️",    # Rain showers
    81: "🌧️",
    82: "⛈️",
    85: "🌨️",
    86: "🌨️",
    95: "⛈️",    # Thunderstorm
    96: "⛈️",
    99: "⛈️",
}
DEFAULT_EMOJI = "🌡️"
DEFAULT_WINDOW_DAYS = 14
CACHE_TTL_SECONDS = 6 * 60 * 60


@dataclass
class DayForecast:
    """One day's forecast — what the chip + popover render from."""
    date: date
    high: float                            # in cached temp_unit
    low: float
    temp_unit: str                         # "celsius" | "fahrenheit"
    wmo_code: int
    emoji: str
    precipitation_probability: Optional[int]  # 0..100 or None
    humidity: Optional[int]                # 0..100 or None
    hourly: list[dict]                     # 4-slot micro-strip


# Pure helpers (no network, no DB)

def wmo_code_to_emoji(code: int) -> str: ...

def is_in_forecast_window(d: date, today: date,
                          window_days: int = DEFAULT_WINDOW_DAYS) -> bool:
    """True iff today <= d <= today + (window_days - 1)."""

def cache_key_for(lat: float, lng: float, d: date,
                  unit: str) -> tuple:
    """Returns (round(lat, 2), round(lng, 2), d, unit)."""

def format_temperature(value: float, unit: str) -> str:
    """'14°' for celsius, '57°' for fahrenheit. No decimal."""

def pick_day_coords(items_for_day, trip_fallback_coords):
    """Return (lat, lng) tuple or None. First item's coords if
    available; otherwise the trip fallback (lifetime-map primary
    city geocode), or None."""


# Impure (mocked in tests)

def fetch_forecast(lat: float, lng: float, *, unit: str,
                   start_date: date, end_date: date) -> Optional[dict]:
    """One Open-Meteo call. Returns the raw JSON dict or None on
    network / 5xx error. Timeout 5s."""

def get_forecast_for_day(lat: float, lng: float, d: date, *,
                         unit: str, db_session) -> Optional[DayForecast]:
    """Cache-first. Returns None when nothing is in cache AND the
    API call fails. Side effects: writes a WeatherCache row on
    successful fetch."""
```

### Open-Meteo request shape

```
GET https://api.open-meteo.com/v1/forecast?
  latitude={lat}&longitude={lng}
  &daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,relative_humidity_2m_mean
  &hourly=temperature_2m,weather_code
  &temperature_unit={celsius|fahrenheit}
  &timezone=auto
  &start_date={iso}&end_date={iso}
```

`timezone=auto` makes Open-Meteo return values keyed in the
target's local time — important so "Day 3" reads as the local
daytime weather, not UTC.

### Hourly micro-strip extraction

Open-Meteo's `hourly` arrays give 24 values per day. We sample at
indices `[6, 12, 18, 22]` (local time) into a 4-element list of
`{"hour": int, "temp": float, "code": int}` dicts, JSON-encoded
into `WeatherCache.hourly_json`.

### Routes

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/settings` | login_required | Renders settings.html with the user's current `weather_units`. |
| POST | `/settings` | login_required | Reads `weather_units` from form; validates against `{'metric', 'imperial'}`; writes to `current_user.weather_units`; flash + redirect to `/settings`. |
| GET | `/trips/<id>/itinerary` | (existing) | Extended to fetch a `DayForecast` for each day in `[today, today + 13]` overlapping the trip range. Skips days with no representative coords. Forecasts threaded into the template. |
| GET | `/trips/<id>` | (existing) | When `derive_status == "in_progress"` AND today is in the trip window, fetch one extra `DayForecast` for today and pass it as `today_forecast`. |

`fetch_forecast` is called at most once per route call per unique
coord+date pair — the cache hit happens before the API call.

### Template changes

`templates/trip_itinerary.html` — per-day chip on the day header:

```jinja
<h2 class="day-header">
  Day {{ day_num }} · {{ day_date.strftime("%a, %b %d") }}
  {% if day_forecast %}
    <button type="button"
            class="vp-weather-chip btn btn-link p-0"
            data-bs-toggle="popover"
            data-bs-html="true"
            data-bs-title="{{ day_date.strftime("%a, %b %d") }}"
            data-bs-content="{{ render_popover(day_forecast)|e }}">
      {{ day_forecast.emoji }}
      {{ format_temperature(day_forecast.high, day_forecast.temp_unit) }} /
      {{ format_temperature(day_forecast.low, day_forecast.temp_unit) }}
    </button>
  {% endif %}
</h2>
```

`templates/_today_section.html` (the existing partial used by the
trip overview Today section) — hero chip at the top:

```jinja
{% if today_forecast %}
  <div class="vp-weather-hero">
    <span class="vp-weather-hero__emoji">{{ today_forecast.emoji }}</span>
    <span class="vp-weather-hero__temp">
      {{ format_temperature(today_forecast.high, today_forecast.temp_unit) }} /
      {{ format_temperature(today_forecast.low, today_forecast.temp_unit) }}
    </span>
    <span class="vp-weather-hero__meta text-muted small">
      {% if today_forecast.precipitation_probability %}
        💧 {{ today_forecast.precipitation_probability }}%
      {% endif %}
    </span>
  </div>
{% endif %}
```

`templates/_navbar.html` (or `base.html` user dropdown) — add a
"Settings" link entry just above "Sign out".

`templates/settings.html` (new) — a small form with the unit
radio + a Save button.

### CSS additions in `static/css/app.css`

- `.vp-weather-chip` — pill, padding `0.25rem 0.6rem`, `font-size:
  0.85rem`, background `var(--vp-surface-2)`, no border, hover
  background `var(--vp-accent-soft)`.
- `.vp-weather-hero` — larger inline-flex, gap `0.6rem`, emoji
  rendered at `1.6rem`. Sits as the first child of the Today
  section.
- Popover styles are Bootstrap defaults; no override.

### Bootstrap popovers

Already loaded via the CDN bundle in `base.html`. We initialize
all `[data-bs-toggle="popover"]` elements with one inline script
at the bottom of `trip_itinerary.html`:

```javascript
document.querySelectorAll('[data-bs-toggle="popover"]').forEach(
  function (el) { new bootstrap.Popover(el, { trigger: 'click focus' }); }
);
```

## The page experience

### Itinerary page (within forecast window)

```
Day 1 · Mon, Jun 8     [🌤️ 22° / 14°]
  09:00  Breakfast at Café Marly
  ...

Day 2 · Tue, Jun 9     [⛅ 19° / 12°]
  ...
```

Click the chip → popover:

```
Tue, Jun 9
Partly cloudy

💧 Precip 20% chance · 💦 Humidity 64%

  06: 🌤️ 13°    12: ☀️ 18°    18: 🌤️ 16°    22: 🌙 14°
```

### Itinerary page (beyond forecast window)

```
Day 8 · Mon, Jun 15
  09:00  Breakfast at Café Marly
  ...
```

No chip. No "forecast unavailable" copy. The absence is the
message.

### Trip overview Today section (in-progress trip, today in-window)

```
☀️ Today — Day 3
[ ☀️ 28° / 17° · 💧 0% ]    ← hero chip

  09:00  Walking tour of Trastevere
  13:00  Lunch at Roscioli
  ...
```

### Settings page

```
Settings

Temperature units
  ◉ Celsius (°C)
  ◯ Fahrenheit (°F)

[ Save ]
```

After save, flash "Settings updated." and redirect.

## Edge cases

| Case | Behavior |
|---|---|
| Day has no items with coords AND trip has no fallback coords | No chip rendered for that day. Popover code skipped entirely (the `{% if day_forecast %}` guard hides everything). |
| Day in window but Open-Meteo returns 500 / network error | No chip. `logger.warning("weather fetch failed for ...")`. No banner. |
| Cache row stale (`fetched_at + 6h < utcnow`) | Treated as a miss. Re-fetch and overwrite. |
| User toggles units mid-session | Cache rows for the new unit get populated on next page load (cache is per-unit). Old rows stay until their TTL expires. |
| Trip ends within the window | Forecasts only render for days in `[max(today, trip.start), min(today+13, trip.end)]`. Days after the trip ends don't have day headers anyway, so n/a. |
| Trip starts beyond the window (planning trip starting in 30 days) | No chips render. Page looks like a normal itinerary. |
| Today is the trip's last day | Today section appears (in_progress), hero chip renders if coords exist. The itinerary section also shows a chip on that day header — duplicate emoji on the same day is acceptable and matches what the spec asks for. |
| Open-Meteo returns a previously-unknown WMO code | `wmo_code_to_emoji` returns the default `🌡️` and the chip still renders with that emoji + the temps. Log a debug-level note. |
| User has zero trips | `/settings` works fine. Itinerary / overview pages don't apply. |
| Database migration — first deploy | `_run_safe_alters` adds `user.weather_units` column (default `'metric'`). `WeatherCache` table created via `db.create_all()` on app startup. Existing users inherit `'metric'`. |
| Concurrent fetches for the same key | Two requests racing to fetch the same `(lat, lng, date, unit)`: second one's insert fails on unique index → log and re-query. No user-visible difference. |
| Trip overview hero chip but no `today_forecast` | The hero section just renders without the chip. The "Today" heading still shows. |

## Testing

### Unit tests (new) — `tests/test_weather.py`

**`wmo_code_to_emoji`** (~3):
- Known code returns expected emoji.
- Unknown code returns `DEFAULT_EMOJI`.
- Code at table boundaries (0, 99) both map.

**`is_in_forecast_window`** (~4):
- Today is in window.
- Today + 13 is in window.
- Today + 14 is NOT in window.
- Yesterday is NOT in window.

**`cache_key_for`** (~3):
- Rounds lat / lng to 2 decimal places.
- Includes the unit string.
- Negative coords round correctly.

**`format_temperature`** (~4):
- Celsius rounds and adds `°`.
- Fahrenheit rounds and adds `°`.
- Fractional values floor to nearest integer.
- Sub-zero handled.

**`pick_day_coords`** (~5):
- First item with coords wins.
- Items without coords are skipped.
- Empty list falls back to trip coords.
- All-coordless plus null trip fallback returns None.
- Trip fallback returns a (lat, lng) tuple, not a dataclass.

**`fetch_forecast`** (~3, with `requests.get` mocked):
- 200 response returns the JSON dict.
- 500 response returns None.
- Network error / timeout returns None.

**`get_forecast_for_day`** (~5, with cache + API mocked):
- Cache miss → API call → cache write → returns DayForecast.
- Cache hit (fresh row) → no API call → returns DayForecast.
- Stale row → API call → overwrites cache.
- API failure on miss → returns None, no cache row written.
- Different unit cached separately.

### Integration tests (extend) — `tests/test_routes.py`

- `test_settings_get_renders_form_with_current_unit`
- `test_settings_post_updates_user_weather_units`
- `test_settings_post_rejects_invalid_unit`
- `test_itinerary_renders_weather_chip_for_today` (mock `fetch_forecast`)
- `test_itinerary_skips_chip_for_day_beyond_window`
- `test_trip_overview_today_section_renders_hero_chip` (mock fetch)

Plus one cross-cutting test:

- `test_weather_failure_does_not_break_itinerary_page` —
  `fetch_forecast` returns None; page still 200s; no chip in body.

Approximately 26 unit + 7 integration = **33 new tests**. Suite
target: 532 → ~565.

### Manual smoke checklist

- Visit `/settings`, switch to Fahrenheit, save. Reload itinerary —
  chips show `°F` values.
- Switch back. Chips show `°C`.
- Itinerary page for an upcoming trip starting in 2 days: chips
  render for days 1-12 (within 14-day window), no chips for days
  13+.
- Itinerary page for a trip 30 days out: no chips.
- Click a chip: popover opens with humidity, precip%, hourly strip.
- Trip overview while a trip is in progress: hero chip at top of
  Today section.
- Disconnect network, reload page: page still renders, no chips,
  no error banner. Console log shows the warning.

## Dependencies

- Geocoding from Phase 2 — already supplies `geocoded_lat` /
  `geocoded_lng` on bookings and itinerary items.
- A1 / A3 — `src/yearbook.py` has the trip-primary-city pattern
  we reuse for the fallback coord.
- Bootstrap 5.3 popover JS — already loaded in `base.html`.
- No new Python packages — `requests` is already a dependency for
  geocoding.

## Open questions resolved during brainstorm

| Question | Decision |
|---|---|
| Provider | Open-Meteo (free, no key) |
| Cache TTL | 6 hours |
| Forecast window | 14 days |
| Units handling | `User.weather_units` column (metric default) |
| Settings UI in v1 | Build small `/settings` page now (reused by B3 later) |
| Chip placement on itinerary | One chip per day header |
| Today-view chip | Hero chip at top of Today section |
| Popover content | Humidity %, precip %, condition text, 4-slot hourly micro-strip |
| Failure behavior | Silent — no chip, log warning, no banner |
| Cross-unit cache | Cache per `(lat, lng, date, unit)` so flipping the toggle still hits cache |

## Updating this document

Same convention as A1 / A2 / A3. Fix the spec inline and commit
`docs: clarify <section> in weather-forecast spec` if implementation
reveals a design issue. The spec is the record of "what we agreed
to" — not a frozen artifact.

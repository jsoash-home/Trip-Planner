# Vacation Planner — Phase 3 Roadmap

> **Status:** Vision document. Modeled on `PHASE_2_ROADMAP.md`. Captures
> the six phase-3 features in depth, plus parked items for later phases,
> so nothing about the plan can be lost. Detailed TDD implementation
> plans live in `docs/superpowers/plans/` and are written one at a time,
> just before each feature is built. Design specs live in
> `docs/superpowers/specs/`.

## How to use this document

- This roadmap is **the source of truth for what phase 3 means**.
- Each feature has a short executable plan written when you're ready to
  build it. See the table below for the current status.
- Pick the next feature from the ordering section, then ask Claude to
  "write the design spec for [feature]" / "write the plan for [feature]".
- When a feature ships, mark it ✓ in the status column and link the
  plan that built it.

## Theme

Phase 2 made the app powerful (sharing, drift review, fun countdown,
map view). Phase 3 makes it **memorable and assistive**.

Two threads:

- **A. Remember it forever.** The lifetime map already says this app
  cares about looking back. Phase 3 leans hard into that: each completed
  trip earns a yearbook page; the dashboard surfaces "on this day"
  nostalgia; lifetime totals sit alongside the map.
- **B. Plan smarter.** Three small practical helpers that make the
  pre-trip and in-trip experience smarter without changing what the app
  is: weather forecast on each itinerary day, destination clock on the
  overview, and home-currency totals on the budget page.

## Status table

| #  | Feature                              | Effort        | Status      | Plan |
|----|--------------------------------------|---------------|-------------|------|
| A1 | Trip Yearbook                        | medium        | ✓ shipped   | [2026-05-31-trip-yearbook.md](superpowers/plans/2026-05-31-trip-yearbook.md) |
| A3 | "On this day" tickler                | small         | ✓ shipped   | [2026-06-06-on-this-day.md](superpowers/plans/2026-06-06-on-this-day.md) |
| A2 | Lifetime stats dashboard             | small         | ✓ shipped   | [2026-06-07-lifetime-stats.md](superpowers/plans/2026-06-07-lifetime-stats.md) |
| B1 | Weather forecast on itinerary        | small-medium  | ✓ shipped   | [2026-06-07-weather-forecast.md](superpowers/plans/2026-06-07-weather-forecast.md) |
| B2 | Destination clock / time zones       | small         | ✓ shipped   | [2026-06-07-destination-clock.md](superpowers/plans/2026-06-07-destination-clock.md) |
| B3 | Home-currency budget totals          | small-medium  | ✓ shipped   | [2026-06-09-home-currency-budget.md](superpowers/plans/2026-06-09-home-currency-budget.md) |

Row order is the **recommended build order**. See "Ordering rationale"
below.

---

## The six features, in depth

### A1 — Trip Yearbook

**What it is.** A new page at `/trips/<id>/yearbook` available once a
trip is `completed`. A single recap card with:

- The trip name, dates, and a hero strip (route map thumbnail or the
  trip emoji theme).
- **Numbers.** Days away, countries visited, cities visited, total
  bookings, total spend, biggest spend category. Optionally: nights
  in hotels, flight legs, miles flown (rough).
- **Route map.** A static map thumbnail showing the pins for the trip
  (reuse the existing `/map` geojson + Mapbox static-image API).
- **Highlights.** A scrollable list of itinerary items the user
  "starred" (new boolean field on `ItineraryItem`). If nothing is
  starred, show the day-by-day chip strip from the existing
  `_section_tiles.html` style.
- **Notes.** The existing `Trip.notes` field rendered with markdown,
  as the personal write-up.
- **Print / share.** A print-friendly stylesheet (CSS `@media print`)
  and a "Copy public link" button if public share links (Phase 2 #4)
  has shipped by then.

The page is the after-trip twin of the fun countdown hero — the
countdown is what the trip *will* be, the yearbook is what it *was*.

**Why it's first.** It's the keystone feature for the "remember
forever" theme. Building it first forces the data we'll want elsewhere
(starred items, easy stats helpers, route map thumbnails) to land in
pure helpers that A2 and A3 then reuse. It also reuses three patterns
the codebase is strong at: a new pure helpers module
(`src/yearbook.py`), a new template, a new route guarded by
`require_trip_access`.

**What code to mirror.**

- **Route shape.** Same as `trip_overview()` in `app.py` — load trip
  via `_trip_with_access_or_404`, compute view-model dict, render
  template. See [app.py:1xxx](../app.py).
- **Pure helpers.** Mirror `src/trip_helpers.py`. New module
  `src/yearbook.py` with pure functions:
  `compute_trip_stats(trip, bookings, itinerary)`,
  `compute_highlight_items(itinerary)`,
  `compute_country_list(bookings, itinerary)`.
- **Map thumbnail.** Reuse Mapbox static-image API. New helper in
  `src/map_helpers.py`:
  `build_static_map_url(pins, width, height, token) -> str`.
- **Template.** Mirror `_countdown_hero.html` style — a single
  cohesive panel, theme-aware, with chip strips for sub-sections.

**Key design decisions.**

- **Visibility.** Yearbook link appears on the trip overview only when
  `derive_status(trip) == "completed"`. The page itself returns 404
  for `planning` / `upcoming` / `in_progress` trips so the URL isn't
  guessable.
- **Starring.** Add a `starred: Boolean` column to `ItineraryItem`.
  An "★ Highlight this" toggle button on each itinerary card during
  or after the trip. Defaults to `False`. No migration of historic
  data needed.
- **Stat computation.** Pure functions take in-memory rows, return a
  dict of stats. No DB queries inside helpers. Cached at request
  time — these are completed trips so the data is static, but we
  don't bother with persistence.
- **Map thumbnail.** Use Mapbox static-image API
  (`/styles/v1/{style}/static/{overlays}/auto/{w}x{h}@2x`). Free up to
  50k loads/month. URL is built server-side from the existing pins.
- **Country list.** Compute by looking at the `country_iso` column on
  geocoded rows — already populated by Phase 2 map work for the
  lifetime map.
- **Trip duplication.** When duplication (Phase 2 #6) lands, copied
  itinerary items reset `starred=False`. Highlights are
  trip-instance-specific.

**Dependencies.** None. Geocoding from Phase 2 supplies the country
data; static-image API is Mapbox's same-token same-account flow.

**See:** `docs/superpowers/specs/2026-05-31-trip-yearbook-design.md`
(to be written next).

---

### A3 — "On this day" tickler

**What it is.** A small block on the dashboard (`/trips`) showing past
trips that overlap today's calendar date in prior years. Example:

> 📍 **On this day…**
> Three years ago you were in **Tokyo** — day 4 of *Cherry Blossom 2023*.
> Five years ago you were in **Lisbon** — day 1 of *Portugal 2021*.

If no past trip overlaps today, the block doesn't render. Click-through
opens the trip's yearbook (A1) or overview.

**Why second.** Smallest feature in phase 3. Reuses A1's
`compute_country_list` / "where was I on day N" logic. One pure helper,
one template partial, one block on the existing dashboard.

**What code to mirror.** `src/trip_helpers.py` style. New helper in
`src/yearbook.py` (reuse the module from A1):
`on_this_day(user, today_date) -> list[OnThisDayEntry]`.

**Key design decisions.**

- **Definition of overlap.** A past trip's `[start_date, end_date]`
  includes a date with the same `(month, day)` as today. Year-agnostic
  match. February 29 quietly matches February 28/29 in non-leap years
  — pick one (28) and document.
- **Which trips count.** Owned trips + accepted collaborator trips,
  both. Mirrors lifetime map scope.
- **Order.** Most recent first (3 years ago before 5 years ago).
- **Empty state.** Block hides entirely. No "no trips today" copy —
  that would just be a daily reminder that you're not traveling, which
  is the wrong vibe.

**Dependencies.** Stronger if A1 ships first — clicking "On this day"
landing on a yearbook page hits emotionally harder than landing on an
overview.

---

### A2 — Lifetime stats dashboard

**What it is.** A stats strip above the lifetime map (`/map`) showing
aggregate totals across all the user's trips:

> 🌍 **22 countries** · 🏙️ **47 cities** · 🛏️ **186 nights away**
> ✈️ **34 flights** · 📅 **9 trips** · 🗺️ **Longest: 21 days**

Optionally a "by year" bar chart below the map (sparkline-style).

**Why third.** Pure aggregation over existing data. Easy win. Pairs
visually with the lifetime map and benefits the same audience (anyone
who scrolls the map to admire their countries).

**What code to mirror.** Same `src/yearbook.py` pattern. New pure
function: `compute_lifetime_stats(user, trips, bookings, itinerary)
-> LifetimeStats`. Renders on the existing `/map` template.

**Key design decisions.**

- **Trip count.** Only `completed` trips count toward lifetime stats.
  In-progress and upcoming trips would inflate the "nights away"
  total before they're real.
- **Country / city dedup.** Same country counted once across trips.
  Same city counted once across trips (so a yearly Paris visit doesn't
  inflate to 5 cities).
- **By-year chart.** Optional. If included, use plain `<canvas>` or
  even just CSS bars — no Chart.js dependency unless we already have
  one.

**Dependencies.** Soft on A1 (shared helpers in `src/yearbook.py`).

---

### B1 — Weather forecast on itinerary

**What it is.** Each itinerary day inside the forecast window (~14 days
out) shows a small weather chip: high/low + emoji icon. Tap the chip
for a detail popover (humidity, precip chance, hourly).

> 🌧️ 14° / 8° — Day 3, Paris

**Why fourth.** First feature in the "plan smarter" thread. Touches
the geocoding pipeline from Phase 2 (each itinerary day has a
representative lat/lng → forecast lookup). New external API but a
*free, no-key, no-card-on-file* one (Open-Meteo).

**What code to mirror.** Nothing local — new pattern. The closest
analog is the geocoding cache in `src/geocoding.py` — same shape:
external API + cache table + freshness check.

**Key design decisions.**

- **Provider.** Open-Meteo (`api.open-meteo.com`). Free, no API key
  required, generous rate limits. License allows commercial use.
- **Representative lat/lng per day.** Use the first geocoded
  itinerary item's coords for that day. Fallback: the trip's primary
  city (Phase 2 already infers this for the lifetime map).
- **Cache.** New `WeatherCache` table keyed by
  `(lat_rounded_to_2dp, lng_rounded_to_2dp, date)`. Rows expire after
  6 hours. Background-friendly but v1 can be on-demand at page load.
- **Forecast window.** Show chips only for days within 14 days of
  today. Days beyond the window show nothing (don't fake it with
  historical averages — that's misleading).
- **In-trip behavior.** During the trip, chips still render; "today"
  and "tomorrow" get the most prominence on the today view.

**Dependencies.** None. The Phase 2 map geocoding gives us lat/lng
for itinerary items already.

---

### B2 — Destination clock / time zones

**What it is.** Show the destination's local time on the trip overview
hero (alongside the fun countdown) and on the today view. Plus a small
"X hours ahead/behind" tag.

> 🕒 Tokyo, **3:47 PM** (14 h ahead)

**Why fifth.** Tiny feature. Mostly a frontend tweak — JS reads the
trip's timezone (a new column) and updates every second.

**What code to mirror.** The fun countdown ticker in
`static/js/countdown.js` — same pattern (DOM target, setInterval, dom
update).

**Key design decisions.**

- **Trip timezone.** New nullable column `Trip.timezone_iana` (e.g.
  `Europe/Paris`). Auto-derived from the first geocoded booking via a
  `tz_finder` library (`timezonefinder` is pure-Python, no key,
  small).
- **Fallback.** If unset, the destination clock block doesn't render.
  No fake "guess by country" fallback.
- **Multi-zone trips.** v1 uses one timezone per trip. Multi-leg trips
  that cross zones use the first booking's. Document the limitation;
  revisit later if it bites.
- **Editing.** Trip form gets a "Time zone" dropdown (or autofill
  preview from "first booking inferred X — keep / change").

**Dependencies.** Geocoding from Phase 2 supplies the lat/lng.

---

### B3 — Home-currency budget totals

**What it is.** The budget page can show totals in the user's home
currency in addition to the per-booking currency. A small toggle:
"Show in: [USD ▼]" recomputes the totals using current exchange rates.

**Why sixth.** Most complex of the "plan smarter" thread because of
currency rounding and rate freshness. Reuses the `src/budget.py`
helpers cleanly.

**What code to mirror.** `src/currency.py` already has the
`SUPPORTED_CURRENCIES` list. Extend `src/budget.py` with a new pure
function: `convert_totals(totals_by_currency, target_currency, rates)
-> dict`.

**Key design decisions.**

- **Provider.** exchangerate.host (free, no key) for daily rates.
  Cached once per day per base currency.
- **Cache.** New `ExchangeRateCache` table keyed by
  `(base_currency, target_currency, date)`. TTL: 24 hours.
- **Home currency.** New `User.home_currency` column (default `USD`).
  Settable from a profile page (which we'd build small here — there
  isn't one yet).
- **Display.** Booking lines still show their original currency. Only
  the rollup totals at the bottom of the budget page get the
  converted version. A small "≈ rates as of 2026-05-30" disclaimer
  below.
- **No live re-conversion.** Don't recompute on every page load — use
  the cached daily rate.

**Dependencies.** None.

---

## Parked for later phases

These were in the original brainstorm but deferred. Keep them here so
they aren't lost.

### C — Live the trip (in-trip mode)

- **C1. PWA / offline shell.** Service worker + manifest so today
  view, bookings, and itinerary render with no signal. New pattern,
  real tradeoffs (cache invalidation, stale data warnings).
- **C2. Daily journal.** One-tap freeform note per day during the
  trip; surfaces on the Yearbook (A1) as the highlights prose.
- **C3. Quick spend log.** Log actual costs as you go and roll them
  up against the budget plan. Pair with B3 (home-currency totals).

### D — Capture without typing

- **D1. Email-in booking parser.** Forward `trips+<token>@…` →
  booking auto-created. Needs inbound email infra (Postmark inbound
  or Cloudflare Email Workers) + a brittle parser.
- **D2. Paste-and-parse.** Paste an email body into a textarea → get
  a pre-filled booking form. Same parser as D1 minus the email
  pipeline. Strictly easier; ship first.

### Extras worth keeping

- **iCal subscription feed.** Subscribe to your trip itinerary in
  Google/Apple Calendar. Read-only `.ics` route, secret token in URL.
  Small effort, high utility for the "live the trip" thread.
- **Photo attachments.** Attach photos to bookings/itinerary items;
  pin popups show a thumbnail; Yearbook (A1) surfaces them.
  Overlaps Phase 2 #2 (document storage) — wait for that to land or
  build photos as the first concrete case of document storage.
- **Achievement system.** Visited 10 countries, first international,
  5-trip year, longest trip, etc. Pure aggregation, no new
  dependencies. Pairs naturally with A2 (lifetime stats).
- **Trip themes / moods.** Pick an emoji theme that styles the trip
  pages with a colour palette (beach palette, mountain palette, city
  palette). Builds on the existing `emoji_theme` helper. Pure CSS.

---

## Ordering rationale

The recommended order, top to bottom: **A1, A3, A2, B1, B2, B3.**

The principles in priority order:

1. **A1 is the keystone.** It forces the pure helpers (`src/yearbook.py`,
   stats computation, route-map thumbnail) that A2 and A3 then reuse.
   Building A1 first means A2 and A3 are mostly thin wrappers.
2. **Cohesive theme first, then practical helpers.** A1/A2/A3 are one
   coherent "remember forever" surface. Ship them as a set so the
   theme reads as deliberate, then move to the more utilitarian B
   thread.
3. **A3 before A2.** A3 is smaller and depends on A1 more directly
   ("on this day" needs A1 to link to). A2 can be a polish layer that
   lands after.
4. **B1 first in the B thread.** Highest payoff (weather is what most
   travelers actually want to know). Smallest new external dep
   (Open-Meteo, no key).
5. **B3 last.** Currency conversion has the most tradeoffs (rate
   freshness, rounding, display). Easiest to defer; not blocking
   anything else.

Safe deviations:

- **Pull B1 (weather) earlier** if you want to ship a "plan smarter"
  win between A1 and A3.
- **Skip A2 if A1 + A3 satisfy the lifetime-stats craving.** A1's
  per-trip stats may already feel like enough.

Avoid these deviations:

- **A2 before A1.** You'd duplicate stats logic and then have to
  refactor it during A1.
- **B3 before B1.** Currency handling is finicky; not the first place
  you want to introduce a new external cache pattern in phase 3.

---

## Updating this document

Same convention as `PHASE_2_ROADMAP.md`. When you finish a feature:

1. Mark its row in the status table as ✓ and link the plan that built
   it.
2. If your understanding of the feature changed during the build
   (almost always happens), update the feature's section here.
3. Commit with `docs: update phase-3 roadmap after <feature> shipped`.

When you start a new feature, ask Claude to write the design spec
first (lives in `docs/superpowers/specs/`), then the executable plan
(lives in `docs/superpowers/plans/`). The plan gets linked from the
status table here.

This document does not get deleted when phase 3 finishes. It becomes
the historical record of how phase 3 was scoped, what was built, and
what got reshaped along the way.

---

## Phase 4 — Beyond

Phase 3 is now complete. Phase 4 captures the features built after the
six-feature phase 3 set. Each row is a feature that has shipped (or is
parked) post-phase-3.

| Feature                  | Status      | Spec                                                          | Plan                                                       |
|--------------------------|-------------|---------------------------------------------------------------|------------------------------------------------------------|
| Trip-prep to-dos (v1)    | ✓ shipped   | [docs/superpowers/specs/2026-06-14-trip-prep-todos-design.md](superpowers/specs/2026-06-14-trip-prep-todos-design.md) | [docs/superpowers/plans/2026-06-14-trip-prep-todos.md](superpowers/plans/2026-06-14-trip-prep-todos.md) |
| Trip guide skill         | ✓ shipped   | [docs/superpowers/specs/2026-06-19-trip-guide-skill-design.md](superpowers/specs/2026-06-19-trip-guide-skill-design.md) | (shipped without a tracked plan file)                       |
| Paste-and-parse (D2)     | ✓ shipped   | [docs/superpowers/specs/2026-06-20-paste-and-parse-booking-design.md](superpowers/specs/2026-06-20-paste-and-parse-booking-design.md) | [docs/superpowers/plans/2026-06-20-paste-and-parse-booking.md](superpowers/plans/2026-06-20-paste-and-parse-booking.md) |

### Parked

- **Trip-prep to-dos v2: AI-suggested prep tasks.** Use the trip's
  destination, dates, and bookings to suggest a starter set of prep
  to-dos (e.g. "Check passport expiry — Japan requires 6 months
  validity", "Order JR Pass before departure"). Builds on the v1
  to-do surface; needs a prompt template and a one-shot LLM call.
- **Paste-and-parse v2: enable the LLM fallback.** v1 built the LLM
  path but gated it off behind 3 env-var checks. When the user adds
  `ANTHROPIC_API_KEY` and `PASTE_PARSER_LLM_ENABLED=1` (plus
  `pip install anthropic`), the fallback kicks in for any email the
  universal-by-type rules don't parse. ~$0.005 per parse with
  Opus 4.8 + Haiku-tier fallback as a cost option.
- **Email-in booking parser (D1).** Forward `trips+<token>@…` →
  booking auto-created. Strictly bigger than D2 — needs inbound-email
  infra (Postmark / Cloudflare Email Workers). D2 was the smaller
  half; revisit only if the paste flow proves too tedious.

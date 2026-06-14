# Session Log

## 2026-06-14 — Date-rot fix + ship in-flight data-safety infra + 12 emoji additions

**Shipped:**
- **fix:** trip fixture `end_date` bumped from `2026-06-10` to `2030-12-31`
  (`tests/test_routes.py:42`, commit `4153d8d`). 5 drift-counts dashboard
  tests had been silently failing on `main` since 2026-06-10 — purely from
  the calendar rolling past the literal end_date. Now date-rot-proof for
  years.
- **feat:** automated DB snapshots (commit `6e38548`) — `src/backup.py`
  (`snapshot_sqlite_db_if_due`) copies `vacation.db` → `data/backups/` at
  app startup when latest snapshot >6h old, prunes to 20 most recent.
  No-op on Postgres / first run. 10 unit tests. Wired in `app.py:212`
  (SQLite branch only). Same commit adds a `tests/conftest.py` tripwire
  that hard-fails the suite if SQLAlchemy bound to anything other than
  `:memory:`. And new "Data safety rules" section in `CLAUDE.md`.
- **feat:** 12 more trip emojis + theme phrases (commit `3b3ddd7`) —
  🌲 🏞️ 🛶 🏕️ 🔥 🐻 🏙️ 🌉 🛳️ 🚂 🏀 ⚽ in `src/trip_helpers.py`. 9 new unit tests.

**Test status:** 659 passing / 0 failing — up from 654/5 at session start
(+5 recovered by the fixture fix, plus +14 net new from this session's work).

**Stopped at:** Three commits pushed to `origin/main`, working tree clean.
User wants to brainstorm a new **trip-prep to-do list** feature next session
(e.g. "buy travel backpacks", "finish choosing Svalbard daytrips") —
brainstorming was started inline this session but deferred so the close-out
could finish first.

**Pick up next with:** Resume the brainstorming session for the trip-prep
to-do feature. The user explicitly asked for "several different ideas, be
creative and modern with the tools and tech used." The `superpowers:brainstorming`
skill was invoked; restart it cleanly next session. Real example to-dos
from the user: travel backpacks (gear, household scope), camera lens (gear),
waterproof shoes (gear), finish choosing Svalbard daytrips (trip-research /
decision).

**Kickoff prompt for next session:**

> I want to add a trip-prep to-do list to Vacation Planner so I can track
> things I need to do or buy before a trip. Real examples I gave last
> session: buy travel backpacks for me + kids, get a new camera lens, buy
> waterproof shoes, finish choosing Svalbard daytrips. Run
> `superpowers:brainstorming` and give me several creative, modern
> approaches before we settle on one. Tests green at 659. The drift-review
> wizard, packing list, and itinerary are the most relevant existing
> surfaces to look at when picking an approach. Spec → `docs/superpowers/specs/`,
> plan → `docs/superpowers/plans/`.

**Loose ends:**
- The 8 `vacation.db.bak*` files at project root are now redundant given
  `src/backup.py` snapshots to `data/backups/`. Past session logs kept
  them intentionally — worth a quick "delete these?" prompt next session.
- B3 (home-currency budget) manual browser smoke from the 2026-06-09
  handoff is still outstanding — not blocking, but the tests cover the
  same paths.
- Drift detection feature is fully shipped (committed before B3) but
  wasn't named in the 2026-06-09 handoff — flag for situational
  awareness in case next session involves dashboard work.

---

## 2026-06-09 — B3 Home-Currency Budget Totals shipped; Phase 3 complete

**Shipped:**
- **B3 Home-currency budget totals** (6 tasks, plan `docs/superpowers/plans/2026-06-09-home-currency-budget.md`, last commit `d0901d5`) — new `User.home_currency String(3) NOT NULL DEFAULT 'USD'` column + new `ExchangeRateCache` table (keyed by `(base_currency, target_currency, rate_date)` with 24-hour TTL), `src/exchange_rates.py` with `RateBundle` + pure helpers (`is_rate_fresh`, `cache_key_for`, `cross_rates_via_usd`) + impure `fetch_latest_rates` / `get_rates_for` (cache-first). `src/budget.py` extended with `convert_totals` — passes through missing-rate sources unconverted. `/settings` page (B1) gains a home-currency `<select>` with atomic save (bad code → neither field changes). `/trips/<id>/budget` gains a `Show in: [USD ▼]` toggle: defaults to `current_user.home_currency`, accepts any supported code or `MIXED`, renders the disclaimer "≈ rates as of YYYY-MM-DD via exchangerate.host" + per-currency unconverted footnote, and falls back with a small "Couldn't fetch rates" note when no useful rate is reachable. No new Python deps (exchangerate.host via existing `requests`).
- Roadmap updated: B3 row marked ✓ shipped — **Phase 3 is complete** (A1 / A2 / A3 / B1 / B2 / B3 all ✓).

**Test status:** 640 passing / 0 failing — up from 603 at session start (+37: 19 exchange_rates unit, 7 convert_totals unit, 4 settings integration, 7 budget integration).

**Stopped at:** B3 work committed locally; 7 commits queued for `git push`. No outstanding code work — Phase 3 is fully closed out.

**Pick up next with:** Manual browser smoke of B3 in a logged-in tab — visit `/settings`, change home currency, then load a trip's `/budget` page and toggle between USD / EUR / Mixed; disable network and reload to verify the "Couldn't fetch rates" fallback. Beyond that, Phase 4 is open territory — the C / D / extras sections of `docs/PHASE_3_ROADMAP.md` line 319+ name 12+ parked candidates (PWA / offline shell, daily journal, quick spend log, email-in booking parser, iCal feed, photo attachments, achievement system, trip themes).

**Kickoff prompt for next session:**

> B3 (home-currency budget) is shipped — Phase 3 done. Tests green at 640. Before starting anything new, do the manual browser smoke for B3: visit `/settings` and change home currency to EUR; load a trip with mixed-currency bookings → verify totals show in EUR with the "≈ rates as of … via exchangerate.host" disclaimer; toggle "Show in:" to JPY (whole-yen, no decimals) and to "Mixed (no conversion)"; force `?show_as=ZZZ` in the URL → page should render in home currency. Then pick the next feature from `docs/PHASE_3_ROADMAP.md` line 319+ (C — Live the trip / D — Capture without typing / Extras: iCal feed, photo attachments, achievements, themes).

**Loose ends:**
- Manual browser smoke of B3 not done in-session (agent can't drive OAuth). Quick to do in a logged-in browser; tests cover the same paths.
- A running dev server on port 5002 (PID 10192 at session-close time) — Flask reloader picked up the schema migration once on T1, so it's on the new code. Restart isn't required, but a fresh boot would zero out any in-memory state from before T1.
- `vacation.db.bak` and ~6 dated `vacation.db.bak.*` snapshots at project root, intentionally kept per prior session decisions.
- exchangerate.host has been reliable; first budget page load with conversion on hits it once per day per (base, target). If the service ever goes away, swap providers in `src.exchange_rates.fetch_latest_rates` — everything downstream is provider-agnostic.

---

## 2026-06-08 — B2 Destination Clock / Time Zones shipped

**Shipped:**
- **B2 Destination clock / time zones** (9 tasks, plan `docs/superpowers/plans/2026-06-07-destination-clock.md`, last commit `27ede2b`) — new `Trip.timezone_iana String(64)` column, `src/destination_clock.py` with `iana_from_coords` / `is_valid_iana` / `hours_offset_label` / `format_clock_label` + `COMMON_TIMEZONES`, `timezonefinder>=6.5` added to requirements. `_ensure_trip_timezone(trip)` helper in `app.py` lazily auto-derives on `trip_overview` and `trip_edit` GETs. Trip form gains an optional text input with `<datalist>` autocomplete + auto-detect preview line. Planning hero gets a 🕒 clock panel under the countdown; Today section gets a 🕒 chip above the weather hero (B1). `static/js/destination_clock.js` ticks the dest time once per second and renders "(N h ahead/behind)" relative to viewer's browser zone. Silent failure mode — no chip on broken IANA or missing `timezonefinder` install. Manual browser smoke passed.
- Roadmap updated: B2 row marked ✓ shipped with plan link.

**Test status:** 603 passing / 0 failing — up from 567 at session start (+36: 17 pure-helper, ~14 route integration, 4 form parsing, plus the small T4 cleanup re-run).

**Stopped at:** B2 pushed to origin/main. No outstanding work. Phase 3 status: A1 ✓, A2 ✓, A3 ✓, B1 ✓, B2 ✓, B3 still queued.

**Pick up next with:** Write the design spec for B3 — Home-currency budget totals. Last remaining phase-3 feature; reuses `src/budget.py` rollup helpers and adds an `ExchangeRateCache` table fed by exchangerate.host. Also adds a `User.home_currency` column to the same `/settings` page B1 created.

**Kickoff prompt for next session:**

> Start B3 (Home-currency budget totals) from `docs/PHASE_3_ROADMAP.md` line 279. Begin with the design spec — same convention as A1 / A2 / A3 / B1 / B2 (all shipped). Tests green at 603. `src/budget.py` already has `rollup_bookings_by_category`; B3 extends it with a `convert_totals(totals_by_currency, target_currency, rates) -> dict` helper. `/settings` page (built in B1) is the natural home for the `home_currency` dropdown. Spec → `docs/superpowers/specs/`, plan → `docs/superpowers/plans/`.

**Loose ends:**
- Three quality nits the final code reviewer flagged (none blocking): (1) DRY the `_tz_city` Jinja derivation between `_countdown_hero.html` and `trip_overview.html` — extract a macro if a 3rd clock surface appears; (2) Extract `_first_geocoded_booking(trip)` to share between `_ensure_trip_timezone` and the `trip_edit` preview computation; (3) `destination_clock.js` `formatTimeForZone` logs `console.warn` every second on a malformed IANA — short-circuit after first failure via an element flag.
- `vacation.db.bak` (May 25, 120 KB) still at project root, intentionally kept per prior session decisions.
- T4 had a real Python gotcha worth remembering: `from src.destination_clock import iana_from_coords` at the top of `app.py` binds the name into `app`'s namespace, so tests must `@patch("app.iana_from_coords")`, not `@patch("src.destination_clock.iana_from_coords")`. A comment in `tests/test_routes.py` above the first ensure-trip-timezone test documents this.

---

## 2026-06-07 — Two more phase-3 features shipped: Lifetime Stats (A2) + Weather Forecast (B1)

**Shipped:**
- **A2 Lifetime stats dashboard** (4 tasks, plan `docs/superpowers/plans/2026-06-07-lifetime-stats.md`, last commit `ac5adda`) — `compute_lifetime_stats` + `compute_trips_per_year` helpers in `src/yearbook.py`, route wiring on `/map` to filter completed-only, ✨ chip strip above the map (countries / cities / days / flights / trips / longest), pure-CSS trips-per-year bar chart below with zero-bars for gap years. Empty-state nudge when no completed trips.
- **B1 Weather forecast on itinerary** (7 tasks, plan `docs/superpowers/plans/2026-06-07-weather-forecast.md`, last commit `0168048`) — new `WeatherCache` model + `User.weather_units` column, `src/weather.py` with Open-Meteo client + 6h cache (per-unit keyed), `/settings` page with the C°/F° toggle, ⚙️ navbar link, 🌦️ chip per itinerary day header with Bootstrap popover (humidity / precip / 4-slot hourly), 🌤️ hero chip on the trip overview Today section. Silent failure mode — no chip when Open-Meteo is down, no banner.
- **chore: `scripts/dev.sh`** — port-5002-freeing dev launcher (last commit `6872bcc`).
- Roadmap updated: A2 + B1 rows both marked ✓ shipped with plan links.

**Test status:** 567 passing / 0 failing — up from 517 at session start (+50: +14 for A2, +35 for B1, plus a yearbook FakeTrip field that made downstream B1 tests easier).

**Stopped at:** Both features pushed to origin/main. No outstanding work. Phase 3 status: A1 ✓, A2 ✓, A3 ✓, B1 ✓, B2 / B3 still queued.

**Pick up next with:** Write the design spec for B2 — Destination clock / time zones. Smallest remaining phase-3 feature; mostly a frontend ticker on the trip overview + a `Trip.timezone_iana` column auto-derived via `timezonefinder` from the first geocoded booking.

**Kickoff prompt for next session:**

> Start B2 (Destination clock / time zones) from `docs/PHASE_3_ROADMAP.md` line 247. Begin with the design spec — same convention as A1 / A2 / A3 / B1 (all shipped). Tests green at 567. `static/js/countdown.js` has the setInterval-ticker pattern to mirror; `timezonefinder` is the proposed lib (pure-Python, no key). Spec → `docs/superpowers/specs/`, plan → `docs/superpowers/plans/`.

**Loose ends:**
- Dev server on `:5002` needs a restart to pick up the B1 schema migrations (`_ensure_weather_columns` + `db.create_all()` for `weather_cache`). The migrations are no-op on re-run, but the column / table need to land for `/settings` and the chips to work in your live browser.
- A2's empty-state nudge wasn't visually smoked — it shows when a user has zero completed trips. Existing `vacation.db` has trips so we can't see it without spinning up a fresh DB.
- First weather page load per location will hit the Open-Meteo API (200–800 ms). Background prefetch is parked as a polish pass.
- `vacation.db.bak` (May 25, 122 KB) still kept at project root by request.

---

## 2026-06-07 — Two phase-3 features shipped: Trip Yearbook (A1) + "On this day" tickler (A3)

**Shipped:**
- **A1 Trip Yearbook** (10 tasks, plan `docs/superpowers/plans/2026-05-31-trip-yearbook.md`, last commit `d0f7d1b`) — schema migration, `src/yearbook.py` helpers, ★ star toggle on itinerary cards, `/trips/<id>/yearbook` page with hero / chips / map / highlights / all-days strip, public `/yearbook/<token>` share with sanitized view + visibility toggles, print stylesheet. Manual smoke passed in browser.
- **A3 "On this day" tickler** (4 tasks, plan `docs/superpowers/plans/2026-06-06-on-this-day.md`, last commit `c21ebb6`) — `on_this_day` helper + 9 unit tests, dashboard route wiring, `_trip_card` macro extension (overlay badge + yearbook link target), ✨ section on `/trips` with "+ N more …" expand. Shipped via subagent-driven development; two review-driven fixes caught along the way (`calendar.monthrange` test fix, `is not none` macro consistency).
- Roadmap updated: A1 + A3 rows both marked ✓ shipped with plan links.

**Test status:** 517 passing / 0 failing — up from 423 at session start (+94 across the two features).

**Stopped at:** Both features pushed to origin/main. No outstanding work. Phase 3 status: A1 ✓, A3 ✓, A2 / B1 / B2 / B3 still queued.

**Pick up next with:** Write the design spec for A2 — Lifetime stats dashboard. It's the natural follow-on; `src/yearbook.py` now has every helper A2 will likely reuse.

**Kickoff prompt for next session:**

> Start A2 (Lifetime stats dashboard) from `docs/PHASE_3_ROADMAP.md` line 42. Begin with the design spec — same convention as A1 (May 31) and A3 (June 6). Tests green at 517. `src/yearbook.py` has `compute_trip_stats`, `compute_country_list`, `on_this_day`-style patterns to reuse. Spec → `docs/superpowers/specs/`, plan → `docs/superpowers/plans/`.

**Loose ends:**
- A3's visual smoke not yet done — need a prior-year trip in `vacation.db` whose dates overlap today's `(month, day)` to verify the ✨ section appears on `/trips`. Easy reproduction: shift a copy of an existing trip's `start_date`/`end_date` back one year.
- `vacation.db.bak` (122 KB) still at project root, intentionally kept this session. Decide whether to delete next time.

---

## 2026-05-31 — Map view: browser verification, plan closed out

**Verified in the user's regular browser:** `/trips/2/map` (Scandinavia '26, 45 geocoded rows) renders Mapbox tiles, pins, day chips, popups, and drag-to-correct — exactly as designed. The in-trip map is fully functional.

**Lifetime map status:** `/map` correctly returns an empty FeatureCollection for the user's current data. Only "TEST TRIP" qualifies (start_date ≤ today) and it has zero geocoded data. Scandinavia '26 is excluded as a future trip per the `_trip_is_for_lifetime` rule. This is working as designed — the lifetime map will populate organically once a trip with geocoded pins has started.

**False-alarm finding from the Claude-driven Chrome MCP browser:** The MCP extension's privacy filter silently blocked Mapbox's vector tile XHRs (which include `access_token=pk....` as a query parameter). This produced a white-globe-with-stars rendering with no tiles in the verification browser, but the issue does NOT exist for normal browsing. Recorded here so a future session that tries to verify maps via Chrome MCP doesn't waste time on the same red herring — drive Mapbox maps via a non-extension tab or trust the test-client smoke pass.

**Verdict:** PASS. Map view plan (Tasks 1–17, all 4 phases) is functionally complete and shipped.

**Test status:** 423 passing / 0 failing — no change.

**Stopped at:** Plan closed out. No outstanding work on the map view feature.

**Pick up next with:** Open. The plan's "What's intentionally NOT in this plan" list (`docs/superpowers/plans/2026-05-29-map-view.md:3193`) names 12 deferred items if you want to pick one (route lines between pins, dashboard mini-map widget, per-trip exclude-from-lifetime toggle, etc.).

**Loose ends:**
- `.claude/launch.json` was created this session to register the Flask dev server for the Claude Preview tools. Currently untracked. Keep if you want to use `/run` or `/verify` against the app in future sessions; delete (`rm -rf .claude/`) if you don't want the file around.
- `vacation.db.bak` (May 25, 122 KB) still at project root, gitignored. Still safe to delete.

---

## 2026-05-30 — Map view Phase 3 + Phase 4: lifetime map end-to-end (plan complete)

**Shipped (7 commits, Tasks 11–17 — the entire lifetime map and final polish):**
- `feat: /map/data.geojson aggregates owned + collaborator trips` (731e083) — new lifetime data route, excludes purely future trips, sorts pins chronologically for fade-in, lazy-geocodes when token present. +1 test.
- `feat: lifetime map page + nav link + flat pin layer` (a82ab9d) — `/map` page route, `templates/lifetime_map.html`, "🌍 Map" top-level nav entry (adapted from the plan's Bootstrap-dropdown assumption to this codebase's custom `vp-navlink`), `vpInitLifetimeMap` factory in `static/js/map.js`.
- `feat: city-level clustering on lifetime map` (fd964a9) — Mapbox built-in clustering with `clusterMaxZoom: 9`, cluster circles + count labels + click-to-zoom.
- `feat: country paint layer at world zoom on lifetime map` (ed24c47) — `visited_country_codes` in payload meta; `mapbox.country-boundaries-v1` fill layer with `maxzoom: 4` so it fades into the cluster/pin layers.
- `feat: year chip filter + stats bar on lifetime map` (b7870ee) — `renderStatsBar`, `renderYearChips`, `applyYearFilter`; filter applies to pins + clusters + counts; stats recompute for the filtered subset.
- `feat: chronological fade-in on lifetime map (D-lite)` (c89b881) — `chronologicalFadeIn` groups features by `trip_id` in server order, ticks them in over ~1.5s; `wireReplay` for the Replay link; `prefers-reduced-motion` skips the animation.
- `feat: empty states for in-trip and lifetime map` (d43e792) — Task 17. `has_any_location` + `has_any_qualifying_trips` flags + friendly copy when each is false. Missing-token banner was already in place from earlier tasks.

**Test status:** 423 passing / 0 failing (+1 new lifetime route test).

**Stopped at:** The full 17-task map view plan is shipped. Plan file at `docs/superpowers/plans/2026-05-29-map-view.md` is complete — every checkbox covered.

**Pick up next with:** No concrete next action queued. Open-ended. The plan's "What's intentionally NOT in this plan" list (line 3193) names 12 deferred items if you want to pick one: route lines between pins, dashboard mini-map widget, per-trip exclude-from-lifetime toggle, etc. The other natural next step is a real browser walkthrough — none of the lifetime map's visual behavior (clusters, country paint, fade-in, year filter, replay) was confirmed in a real browser this session.

**Kickoff prompt for next session:**

> The full 17-task map view plan is shipped. Tests are green at 423 passing. The lifetime map (`/map`) was verified server-side via test client (status 200, all expected template hooks present) but NOT visually confirmed in a real browser — clusters, country paint, year chips, fade-in, and Replay link are all untested visually. Either: (a) walk through the lifetime map in a browser to verify, following the 14-point smoke list at `docs/superpowers/plans/2026-05-29-map-view.md:3137`; or (b) pick one of the deferred items from line 3193 (e.g., dashboard mini-map widget, route lines between pins).

**Loose ends:**
- **Browser walkthrough never happened.** Specifically untested in a real browser: cluster zoom behavior, year-chip filter, country paint at world zoom, chronological fade-in, Replay link, `prefers-reduced-motion` path, drag-correct pin save (from Phase 2).
- The plan assumed a Bootstrap dropdown for the "Map" nav link, but this codebase uses a custom `.vp-nav` flex layout. I added the link as a top-level `.vp-navlink` between "New trip" and the user area. Worth a sanity look in the browser to make sure it doesn't crowd the nav on smaller widths.
- `vacation.db.bak` (May 25, 122 KB) still at project root, gitignored. Decide whether to delete next session.

## 2026-05-30 — Map view Task 10: mini-map teaser on trip overview (Phase 2 complete)

**Shipped:**
- `feat: mini-map teaser on trip overview` (b3e0cfd) — new `templates/_mini_map.html` partial renders only when `has_pins and mapbox_token`. Computed `has_pins` in `trip_overview` route from `geocoded_lat` across bookings + itinerary items. Included partial between the dates/status cards and the "Plan" section-tile grid. New `vpInitMiniMap` factory in `static/js/map.js`: non-interactive, no attribution control, fits bounds with `maxZoom: 11`. Whole tile is a clickable link to the full `/map` page.

**Test status:** 422 passing / 0 failing.

**Stopped at:** Phase 2 of the map view plan complete (Tasks 5–10 all shipped + pushed). Stopped at the user-requested phase boundary before Phase 3 (lifetime map, Tasks 11–17).

**Pick up next with:** Task 11 — Lifetime GeoJSON route `/map/data.geojson` at `docs/superpowers/plans/2026-05-29-map-view.md:2411`.

**Kickoff prompt for next session:**

> Pick up the map view work at Task 11 (Lifetime GeoJSON route `/map/data.geojson`). Plan: docs/superpowers/plans/2026-05-29-map-view.md line 2411. Tests are green (422 passing). Task 10 (mini-map teaser) shipped in b3e0cfd, completing Phase 2. Phase 3 covers Tasks 11–17 (lifetime map end-to-end).

**Loose ends:**
- Mini-map was server-side smoke-tested via Flask test client but not visually verified in a real browser (no live Mapbox tile render confirmed). The JS factory closely mirrors `vpInitTripMap`, which is already working in production.
- `vacation.db.bak` (May 25, 122 KB) sits at the project root. Gitignored, harmless, but no longer needed if you trust the current local DB.

## 2026-05-30 — Map view Task 7: pin popup cards

**Shipped:**
- `feat: pin popup cards on in-trip map` (39d3546) — click a pin to see title, formatted datetime, location, and an "Open booking →" / "Open itinerary item →" deep link. Server-rendered "N items have no location" side note (no_location_count via app.py → trip_map.html). Added `buildPopupHTML` helper + click/mouseenter/mouseleave wiring in `static/js/map.js`. Popup CSS (`.vp-map-popup .vp-popup-*`) was already in `static/css/map.css` from earlier scaffolding.

**Test status:** 419 passing / 0 failing.

**Stopped at:** Task 7 complete and pushed. Plan map-view tasks remaining: Task 8 (day filter chips), Task 9 (drag-to-correct), plus later tasks for the lifetime map.

**Pick up next with:** Task 8 — day filter chips at `docs/superpowers/plans/2026-05-29-map-view.md:1915`.

**Kickoff prompt for next session:**

> Pick up the map view work at Task 8 (Day filter chips). Plan: docs/superpowers/plans/2026-05-29-map-view.md line 1915. Tests are green (419 passing). Task 7 (popups) shipped in 39d3546.

**Loose ends:**
- None.

## 2026-05-30 — Map view debug: empty pins were a Mapbox token URL-restriction; 7 airport/station pins manually overridden

**Shipped:**
- Fixed empty map: token in `.env` was URL-restricted to `http://localhost:5002/`, but backend `requests.get` sends no Referer → Mapbox returned 403 on every geocode. Replaced with a fresh unrestricted token. All 45 rows now geocoded.
- `fix: map tile summary counts rows with location, not just geocoded ones` (e9529ea) — Map section tile was lying about "no locations" because count used `geocoded_lat` which is null until first /map open.
- Data fix (local SQLite only): renamed 10 ambiguous location strings (`MSP`, `LYR`, etc. → full airport/station names) and manually overrode the 7 strings Mapbox still couldn't geocode well, with `geocoded_manually=1` and provider="manual" cache entries.

**Test status:** 419 passing / 0 failing.

**Stopped at:** End of Phase 2 debugging detour. Plan is back on track at Task 7.

**Pick up next with:** Start **Task 7: Pin popup cards** in a fresh window. Plan file: `docs/superpowers/plans/2026-05-29-map-view.md` (Task 7 begins at line 1795).

**Loose ends:**
- Data fix is local-only. If you ever wipe `vacation.db` or develop from another machine, you'd need to redo the manual coord overrides (or back up the DB now). The cache entries with `provider="manual"` are sticky within this DB but don't travel via git.
- Today the lazy-geocode flow silently swallows backend 403s (route still returns 200 with empty features → map looks blank with no signal). A "geocoding failed" banner would be a future polish; Task 17 covers the missing-token banner but not the silent-403 case.
- Two flight bookings still have raw codes the user may or may not want renamed: `OSL - GARDERMOEN` (booking #3 — actually geocoded correctly) and `Tallinn D-Terminal` for the ferry booking (not the renamed item).

## 2026-05-29 — Map view: spec, plan, and Tasks 1-6 of 17 shipped

**Shipped:**
- Design spec (`6c33b13`) + 17-task implementation plan (`4e16952`) for in-trip + lifetime maps
- Phase 1 complete: schema migration, pure helpers, geocoding pipeline, token wiring (Tasks 1-4)
- Phase 2 partial: `/map/data.geojson` route (Task 5) + map page with Mapbox + section tile (Task 6)
- Tightened gitignore to catch bare `*.bak` files

**Test status:** 419 passing / 0 failing (+42 new tests across the session)

**Stopped at:** End of Task 6. Map page renders but is empty in the browser — debugging mid-investigation when session wrapped. Best guesses: `MAPBOX_TOKEN` not loaded from `.env`, OR Mapbox geocoded zero results for the location strings.

**Pick up next with:** Debug the empty map. Three checks in order: (1) server logs for `INFO src.geocoding  geocoding:` lines vs `ERROR geocode HTTP 4xx`, (2) browser network tab — does `data.geojson` return populated `features` or `[]`, (3) browser console for JS errors. Once resolved, start **Task 7: Pin popup cards** in a fresh window. Plan file: `docs/superpowers/plans/2026-05-29-map-view.md`.

**Loose ends:**
- `_map_tile_summary` UX bug: tile says "Add a location to get started" even when locations exist (the count uses `geocoded_lat` which is null until first map open). One-line fix discussed but not applied — decide next session.
- Going forward: stop at each phase boundary instead of continuous execution. Phase 2 ends at Task 10.
- Pending Tasks 7-17 still ahead. Phase 2 has 4 more (7-10), Phase 3 has 6 (11-16), Phase 4 polish has 1 (17).

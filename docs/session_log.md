# Session Log

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

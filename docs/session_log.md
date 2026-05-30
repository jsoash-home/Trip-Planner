# Session Log

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

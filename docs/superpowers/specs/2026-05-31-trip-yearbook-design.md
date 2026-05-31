# Trip Yearbook — Design Spec

> **Status:** Approved design, awaiting implementation plan. Phase 3
> feature A1 from [docs/PHASE_3_ROADMAP.md](../../PHASE_3_ROADMAP.md).
> Spec captures the design decisions made during the 2026-05-31
> brainstorm.

## Goal

Add a per-trip retrospective page at `/trips/<id>/yearbook` that earns
the title "Yearbook":

- For a trip that's `in_progress`, a **preview** view assembled from
  the data so far, with a "Trip still in progress" banner.
- For a trip that's `completed`, the **final** view: numbers (days,
  countries, cities, spend), an interactive route map of the trip's
  pins, a "Highlights" section pulled from itinerary items the user
  starred during or after the trip, the trip's notes rendered with
  markdown, and a print stylesheet + an optional public share link.

The yearbook is the after-trip twin of the fun countdown hero — the
countdown was what the trip *will* be; the yearbook is what it *was*.

## Background and motivation

The v1 + Phase 2 codebase already captures everything needed to
assemble a per-trip recap: trip dates, bookings, itinerary items,
geocoded pins, notes, costs, emoji theme. There's no surface that
*assembles* these into a single keepsake view. The closest existing
analog is the trip overview, which is task-oriented (sections + edit
links) rather than retrospective.

The Phase 3 brainstorm picked yearbook as the keystone of a "remember
forever" thread (alongside A2 lifetime stats dashboard and A3 "on this
day" tickler). Building yearbook first forces the pure helpers
(stats computation, country/city extraction, static-map URL builder)
that A2 and A3 then reuse.

## Decisions baked in

| Decision | Choice | Rejected alternative |
|---|---|---|
| Scope of v1 | Full vision: stats + interactive map + starring + notes + print + public share | "Bare bones" stats + notes only |
| Visibility | `planning`/`upcoming` → hidden (404). `in_progress` → preview. `completed` → final | Always visible; manual "seal yearbook" button |
| Sharing | Yearbook-only public share token (`/yearbook/<token>`) | Wait for Phase 2 #4; bundle #4 into A1; collaborator-only |
| Map rendering | Interactive Mapbox GL on auth view, **static-image fallback** for print and public share | Static only; reuse `_mini_map.html` |
| Starring UX | `★` toggle on itinerary cards (NOT on yearbook). Available in any status. No cap. | Dedicated "choose highlights" editor on yearbook |
| Share toggle during `in_progress` | Hidden — only available on `completed` | Allow mid-trip sharing |
| Miles flown stat | Deferred (no airport-code data) | Estimate via airport-code lookup table |
| Yearbook tile placement | New tile in `_section_tiles.html` row on trip overview | Standalone link in navbar |

## Out of scope for v1

Listed so the boundary is unambiguous. Each may become a polish pass
or a separate Phase 3 spec later.

1. Miles flown / flight legs stat (no airport-code data on bookings).
2. Auto-conversion of multi-currency spend totals into one home
   currency (B3 handles this).
3. Photo attachments on bookings / itinerary items (parking lot).
4. Daily journal entries written during the trip (parking lot C2).
5. Public-share preview thumbnail (Open Graph / Twitter card image).
6. Trip duplication's interaction with `starred` (cleanup: copies
   reset to `starred=False`, but that's a one-liner in the duplication
   path — handled there when #6 ships, not here).
7. Yearbook-specific URL slugs ("/yearbook/cherry-blossom-2026").
   Tokens are opaque random strings.
8. "Comment on a yearbook" or any kind of reaction system.
9. PDF export. v1 relies on the browser's print-to-PDF.
10. "Star anywhere" — only itinerary items can be starred. Not
    bookings, not the trip itself.

---

## Architecture overview

One new page, five new routes, one new pure-helpers module, three new
columns on `Trip`, one new column on `ItineraryItem`. No new
third-party services; existing Mapbox token covers both interactive
maps and the static-image API.

```
                         ┌───────────────────────────────┐
                         │   Mapbox Static-Image API     │
                         └───────────────▲───────────────┘
                                         │ (URL built server-side; visitor's browser
                                         │  loads the <img> once per render)
                                         │
                                  ┌──────┴──────┐
                                  │ src/map_    │
                                  │ helpers.py  │
                                  │ build_      │
                                  │ static_     │
                                  │ map_url()   │
                                  └──────▲──────┘
                                         │
                          ┌──────────────┴──────────────┐
                          │     src/yearbook.py         │
                          │  (pure helpers: stats,      │
                          │   highlights, sanitize,     │
                          │   derive view)              │
                          └──────────────▲──────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        │                                │                                │
        ▼                                ▼                                ▼
┌──────────────────┐         ┌────────────────────┐         ┌─────────────────────┐
│ GET /trips/<id>/ │         │ POST /trips/<id>/  │         │  GET /yearbook/     │
│ yearbook         │         │ yearbook/share     │         │  <token>            │
│ (auth, full view)│         │ (editor+, toggle)  │         │  (PUBLIC, sanitized)│
└──────────────────┘         └────────────────────┘         └─────────────────────┘
                                         ▲
                                         │
                             ┌───────────┴────────────┐
                             │ POST /trips/<id>/      │
                             │ items/<item_id>/star   │
                             │ (editor+, toggle)      │
                             └────────────────────────┘
```

---

## Data model changes

One migration, four nullable / default-valued columns. No backfills
required.

| Table | Column | Type | Default | Notes |
|---|---|---|---|---|
| `itinerary_item` | `starred` | Boolean | `False` | Highlighted items appear on the yearbook |
| `trip` | `yearbook_share_token` | String (length 32), nullable | `NULL` | When NULL: no public share. When set: opaque UUID-style token; public route looks up by this. Indexed. |
| `trip` | `yearbook_public_show_notes` | Boolean | `False` | If `False`, `Trip.notes` are stripped from the public view |
| `trip` | `yearbook_public_show_spend` | Boolean | `True` | If `False`, the spend chip is omitted from the public view |

Migration is additive only — no destructive operations on existing
rows. Existing trips default to "no public share, notes hidden if
shared, spend shown if shared."

---

## Pure helpers — `src/yearbook.py` (new module)

Mirrors the shape of `src/trip_helpers.py`. Every helper takes
in-memory rows + scalars and returns a plain value (dataclass, list,
or dict). No DB queries inside helpers.

```python
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

@dataclass
class TripStats:
    days_away: int                          # (end - start).days + 1
    country_count: int                      # unique country_iso across rows
    city_count: int                         # unique (city, country_iso)
    bookings_by_type: dict[str, int]        # {"flight": 2, "hotel": 3, ...}
    spend_by_category: dict[str, dict[str, float]]
                                            # {"transport": {"USD": 850.0}, ...}
    biggest_spend_category: Optional[str]   # category with largest sum
                                            # in the trip's primary currency
                                            # (or None if no costs)
    starred_count: int                      # how many itinerary items
                                            # carry starred=True

def compute_trip_stats(trip, bookings, itinerary) -> TripStats:
    """Aggregate stats over already-loaded rows. Multi-currency stays
    multi-currency: we do NOT sum across currencies (B3 does that
    later)."""

def compute_highlight_items(itinerary_items) -> dict[int, list]:
    """Return starred items grouped by day_number, in chronological
    order. Days with zero starred items are absent from the dict."""

def compute_country_list(bookings, itinerary) -> list[str]:
    """Country names in order of first appearance. Dedup. Excludes
    rows without geocoded country."""

def derive_yearbook_view(trip, today: date) -> Literal["hidden", "preview", "final"]:
    """planning/upcoming -> hidden, in_progress -> preview, completed -> final.
    Drives both link visibility on overview and 404 logic in the route."""

def sanitize_public_view(view_model: dict, *, show_notes: bool, show_spend: bool) -> dict:
    """Strip private fields for the public share view.
    Always stripped: per-booking confirmation_number, per-booking cost,
    collaborator names, editor controls.
    Conditional: notes (only if show_notes), spend chip + per-category
    rollup (only if show_spend)."""

def generate_share_token() -> str:
    """Opaque 32-char URL-safe token using secrets.token_urlsafe(24)."""
```

The view model passed to the template is built by the route. Helpers
operate on already-loaded rows; the route is responsible for the
SQLAlchemy queries.

---

## Static-image map helper — `src/map_helpers.py` (extend)

```python
def build_static_map_url(
    pins: list[Pin],
    width: int = 600,
    height: int = 360,
    style: str = "streets-v12",
    token: Optional[str] = None,
) -> Optional[str]:
    """Build a Mapbox static-image URL with markers from the given
    Pin list. Returns None if token is missing or pins is empty (the
    template handles the None case by hiding the map block).

    Uses pin-s+{color}({lng},{lat}) marker syntax. Auto-fit viewport
    via the special /auto path component. URL-encodes everything."""
```

The same `Pin` dataclass already used by the in-trip map (in the
existing `src/map_helpers.py`).

---

## Routes

| Method | Path | Auth | Behavior |
|---|---|---|---|
| GET | `/trips/<id>/yearbook` | trip access (any role) | Loads trip + bookings + itinerary. If `derive_yearbook_view(trip, today) == "hidden"`, returns 404. Otherwise renders `yearbook.html` with the full view model and `view_mode = "preview"` or `"final"`. |
| POST | `/trips/<id>/items/<item_id>/star` | trip access, role≥editor | Toggles `ItineraryItem.starred` for the given item. Returns JSON `{starred: bool}`. JS handles optimistic UI on the itinerary page. |
| POST | `/trips/<id>/yearbook/share` | trip access, role≥editor, **only when `derive_yearbook_view == "final"`** | Body: `{action: "enable" \| "disable" \| "rotate"}`. Enable: sets `yearbook_share_token` to a fresh token if currently NULL. Disable: sets to NULL. Rotate: replaces with a fresh token (revokes old). Returns JSON `{token: Optional[str], url: Optional[str]}`. |
| POST | `/trips/<id>/yearbook/visibility` | trip access, role≥editor | Body: `{show_notes: bool, show_spend: bool}`. Persists the two public-view toggles. Returns JSON of the new values. |
| GET | `/yearbook/<token>` | **public — no auth** | Looks up `Trip` where `yearbook_share_token == token` AND derived view is `"final"`. 404 on miss. Renders the same `yearbook.html` template with `view_mode = "public"`; the view model has been routed through `sanitize_public_view()`. Response header: `X-Robots-Tag: noindex, nofollow` and meta tags ditto. |

All four trip-scoped routes guard via the existing
`_trip_with_access_or_404` helper (role parameter `viewer` for GET,
`editor` for POST). The public `/yearbook/<token>` route bypasses
auth by design.

---

## The page experience

The same template `yearbook.html` renders all three modes (preview,
final, public). The differences are driven by the view model and a
`view_mode` flag passed in.

### Sections, top to bottom

1. **Hero strip**
   - Trip name + ISO date range.
   - Emoji glyph from `Trip.cover_emoji` (large, decorative).
   - If `view_mode == "preview"`: a yellow banner
     "🚧 Trip still in progress — this is a preview of your yearbook."
   - If `view_mode == "public"`: the navbar of the auth `base.html` is
     replaced with a thin "📓 Vacation Planner" footer link; no user
     dropdown, no navigation chrome.

2. **The numbers — chip strip**
   ```
   📅 8 days   🌍 2 countries   🏙️ 4 cities   🛏️ 3 hotels   ✈️ 2 flights
   ```
   - Days = `stats.days_away` (uses calendar inclusive count).
   - Countries / cities = `stats.country_count` / `stats.city_count`.
   - Per-type counts pulled from `stats.bookings_by_type`.
   - Spend row beneath (omitted entirely if
     `view_mode == "public"` AND `yearbook_public_show_spend == False`):
     ```
     💰 ¥240,000 + $150.00  ·  Biggest: lodging
     ```
     Multi-currency stays multi-currency until B3 ships. Each currency
     gets its own subtotal.

3. **Route map block**
   ```html
   <div class="yearbook-map">
     <img class="yearbook-map__static" src="{{ static_map_url }}" alt="Route map">
     <div class="yearbook-map__interactive d-none" id="yearbook-map"
          data-pins='{{ pins_json | tojson }}'></div>
   </div>
   ```
   - **Auth view** (preview + final): JS hides `.yearbook-map__static`,
     mounts Mapbox GL into `#yearbook-map`. Interactive pan/zoom.
   - **Public view:** JS is omitted. Only the static `<img>` renders.
   - **Print:** `@media print` swaps to the static-image element.
   - If `build_static_map_url` returns None (no pins yet, e.g. early
     preview before any geocoding): the block hides entirely.

4. **Highlights**
   - Section title: "★ Highlights" with the count.
   - Day-grouped cards, each card a compressed itinerary-item view:
     title, time, location, notes (markdown rendered), category badge.
   - No edit controls. To unstar, the user goes back to the itinerary
     page.
   - Empty state varies by view_mode:
     - Preview: "★ Star items on your itinerary as the trip unfolds —
       they'll show up here." — with a deep link to the itinerary page.
     - Final: same nudge, copy adjusted ("to remember the standouts").
     - Public: section hides entirely if no highlights — empty
       Highlights on a public page is more sad than charming.

5. **All days at a glance**
   - One row per day. Each row: "Day N · {date}" header + a chip strip
     of all items that day (regardless of `starred`).
   - Chips are category-coloured (reuse existing palette). Tooltip on
     hover shows title + time. Click in auth view scrolls to that item
     on the itinerary page; in public view, click is a no-op (or could
     link nowhere — it's read-only).

6. **Trip notes**
   - Rendered as markdown via the existing `markdown` library.
   - Card-style block.
   - In public view: hidden if `yearbook_public_show_notes == False`.

7. **Footer actions** (auth view only; absent in public view)
   - **Print** button → `window.print()`.
   - **Share publicly** toggle button (only visible when `view_mode == "final"`):
     - Off state: "🔒 Yearbook is private" + button "Create public link"
     - On state: Read-only text input with the public URL,
       "Copy" button, "Revoke link" button, and two checkboxes
       (`Include notes in public view`, `Include spend totals`).

### Visual style

Match the existing app's Bootstrap-on-CDN look. The yearbook page
should feel slightly more "magazine" than the rest of the app:
- Wider top margin, generous vertical rhythm between sections.
- Big section headings in the theme's accent colour (drawn from
  `emoji_theme(trip.cover_emoji)` if mapped, otherwise default).
- Cards use the existing `_section_tiles.html` chip style for chip
  strips, and the existing itinerary-card style for highlights.

### Yearbook tile on trip overview

Adds one new tile to the existing `_section_tiles.html` row:

| State | Tile contents | Click behavior |
|---|---|---|
| `derive_yearbook_view == "hidden"` (planning / upcoming) | "📓 Yearbook" title + small subtitle "After the trip" | Greyed/disabled; no link |
| `derive_yearbook_view == "preview"` (in_progress) | "📓 Yearbook" + small subtitle "Preview while in progress" | Links to `/trips/<id>/yearbook` |
| `derive_yearbook_view == "final"` (completed) | "📓 Yearbook" + subtitle "N highlights" (count of starred items) | Links to `/trips/<id>/yearbook` |

---

## Starring UX (on the itinerary page)

On each itinerary item card in `templates/trip_itinerary.html`:

```html
<button class="btn btn-sm btn-link star-toggle"
        data-item-id="{{ item.id }}"
        data-trip-id="{{ trip.id }}"
        aria-pressed="{{ 'true' if item.starred else 'false' }}"
        aria-label="{{ 'Unstar' if item.starred else 'Star' }} this highlight">
  <span class="star-icon">{{ '★' if item.starred else '☆' }}</span>
</button>
```

- Visual: hollow `☆` when off; filled gold `★` when on.
- Click handler in a new `static/js/yearbook.js` (or extend existing
  scripts):
  - Optimistic toggle (swap class + glyph + aria-pressed before the
    request completes).
  - POST to `/trips/<id>/items/<item_id>/star`.
  - On error: revert the toggle, flash a brief error chip.
- Permission: viewer sees the star state but the button is disabled
  (server renders `disabled` attribute when `role == "viewer"`).
- Available in any trip status — including `planning`/`upcoming` (so
  users can mark anticipated highlights). The yearbook itself remains
  hidden for those statuses; the data just sits.

---

## Data flow (auth view)

```
Browser GET /trips/123/yearbook
  → require_trip_access(trip_id=123, role="viewer")
  → Load Trip + Bookings + ItineraryItems (eager via session.query)
  → view = derive_yearbook_view(trip, today)
  → if view == "hidden": abort 404
  → stats = compute_trip_stats(trip, bookings, itinerary)
  → highlights = compute_highlight_items(itinerary)
  → countries = compute_country_list(bookings, itinerary)
  → pins = _build_pins_for_trip(trip)  # existing helper at app.py:951
  → static_map_url = build_static_map_url(pins, 600, 360, token=MAPBOX_TOKEN)
  → render yearbook.html with {trip, stats, highlights, countries,
                                 pins_json, static_map_url, view_mode}

Browser
  → Renders HTML
  → /static/js/yearbook.js loads
  → JS mounts Mapbox GL onto #yearbook-map using pins_json
  → JS hides .yearbook-map__static (replaced by interactive map)
  → Page is interactive

User clicks "Print"
  → window.print()
  → @media print CSS rule shows .yearbook-map__static (img),
     hides #yearbook-map and the footer actions
```

## Data flow (public view)

```
Browser GET /yearbook/abc123tokenxyz
  → Query Trip WHERE yearbook_share_token = "abc123tokenxyz"
  → If no row or derive_yearbook_view != "final": abort 404
  → Load Bookings + ItineraryItems for that trip
  → Build view_model exactly like the auth view
  → view_model = sanitize_public_view(view_model,
                                       show_notes=trip.yearbook_public_show_notes,
                                       show_spend=trip.yearbook_public_show_spend)
  → render yearbook.html with {..., view_mode="public"}
       using a stripped base layout (no navbar, no user chrome)
  → Response headers: X-Robots-Tag: noindex, nofollow

Browser
  → Renders HTML
  → Public template extends a stripped base.html that omits the yearbook
    JS bundle entirely — no Mapbox GL JS download, no fetch to /static/js/yearbook.js
  → Static map <img> is the only map visible
  → Page is read-only and shareable
```

---

## Error handling

- **Missing Mapbox token** → `build_static_map_url` returns None;
  template hides the map block; banner on auth view says "Map not
  configured." (Reuses the Phase 2 missing-token banner pattern.)
- **Geocoding incomplete** (in_progress trip, some pins still lacking
  coords) → preview view still renders. Numbers reflect only the
  geocoded subset; non-geocoded items still appear in highlights and
  the all-days chip strip without map representation.
- **Public share token collision** (1 in ~10^36 with `token_urlsafe(24)`,
  but be defensive) → if the database constraint trips, regenerate
  and retry once. Surface a flash error if it fails twice (won't
  happen).
- **Multi-currency spend with very long lists** → spend chip wraps to
  multiple lines via flex. No truncation in v1.
- **Trip with zero bookings AND zero itinerary** → numbers show "0
  days, 0 countries..." which is fine. The map block hides; the
  highlights block hides; the all-days block hides. The notes block
  still shows if notes exist.
- **Public view requested for a trip whose token was revoked** → 404,
  not a "this link was revoked" message. We don't leak existence.
- **Star toggle from a stale browser tab** (item was deleted by another
  session) → POST returns 404 → JS shows brief error chip, reloads
  the itinerary page after 2 seconds.

---

## Testing

### Unit tests (new) — `tests/test_yearbook.py`

**`compute_trip_stats`**
- Basic shape: a trip with 2 flights, 3 hotels, 5 itinerary items
  across 4 days → counts match.
- Empty bookings + empty itinerary → all counts 0, `biggest_spend_category` None.
- Multi-currency: bookings in USD and JPY → `spend_by_category` has
  separate keys, no cross-currency sum.
- Days away: 1-day trip (`start == end`) → `days_away == 1`. 8-day
  trip → `days_away == 8`.
- Country dedup: 3 bookings all in France → `country_count == 1`.
- City dedup: 2 bookings in Paris, 1 in Lyon → `city_count == 2`.

**`compute_highlight_items`**
- Returns only starred items.
- Groups by `day_number` (computed from `day_date - trip.start_date`).
- Days with zero starred items are absent from the dict.
- Items within a day are sorted by time (or position if time is null,
  using `sort_within_day` from existing `src/itinerary.py`).

**`compute_country_list`**
- Dedup across bookings + itinerary.
- Order of first appearance based on `day_date` (then booking
  start_datetime).
- Rows with NULL `country_iso` excluded.

**`derive_yearbook_view`**
- 4 status branches → 3 outputs (`planning` and `upcoming` both → `hidden`).
- Edge case: trip whose dates would compute as `completed` but the
  user hasn't run `derive_status` recently → `derive_yearbook_view`
  recomputes from `today`, doesn't trust a stale stored status.

**`sanitize_public_view`**
- `show_notes=False` strips `trip.notes` from the view model.
- `show_notes=True` keeps `trip.notes`.
- `show_spend=False` removes both the spend chip and per-category
  rollup.
- `show_spend=True` keeps them.
- Always strips: per-booking `confirmation_number`, per-booking
  `cost`, collaborator names, any field with `private` suffix.

**`generate_share_token`**
- Returns a 32-char URL-safe string.
- Two consecutive calls return different tokens.

### Unit tests (extend) — `tests/test_map_helpers.py`

**`build_static_map_url`**
- Empty pins → returns None.
- Missing token → returns None.
- Single pin → URL contains one `pin-s+{color}({lng},{lat})` segment.
- Multiple pins → markers separated by `,` (URL-encoded).
- Width / height respected in the URL path.

### Integration tests (extend) — `tests/test_app_routes.py`

**GET `/trips/<id>/yearbook`** for each visibility branch:
- Planning trip → 404.
- Upcoming trip → 404.
- In-progress trip → 200, contains "Trip still in progress" banner.
- Completed trip → 200, no preview banner.

**Access control:**
- Non-collaborator → 404 (existing access-guard pattern).
- Viewer → 200 (GET allowed).
- Editor / owner → 200.

**POST `/trips/<id>/items/<item_id>/star`:**
- Editor toggles starred=False → True → JSON response `{starred: true}`.
- Editor toggles back → False → `{starred: false}`.
- Viewer → 403.
- Item not in this trip → 404.

**POST `/trips/<id>/yearbook/share`:**
- Editor on `final` trip, action=enable → token created.
- Same trip, action=enable again → no-op, same token.
- action=rotate → new token, old becomes invalid.
- action=disable → token cleared.
- Same on `in_progress` trip → 400 (only available on `completed`).
- Viewer → 403.

**GET `/yearbook/<token>`:**
- Valid token → 200, response contains sanitized markers (no
  `confirmation_number`, no booking `cost`).
- Unknown token → 404.
- Token cleared (revoked) → 404.
- Token on a non-final trip (shouldn't happen if the toggle is
  guarded, but be defensive) → 404.
- Public view does NOT include the navbar or user dropdown.
- Response header includes `X-Robots-Tag: noindex, nofollow`.

### Manual smoke checklist

- Star an itinerary item from the itinerary page → ★ fills, persists
  on reload.
- Mark trip as in_progress (or wait for clock) → yearbook tile
  appears on overview, page renders with preview banner.
- Mark as completed → preview banner gone, share toggle appears.
- Click "Create public link" → URL appears, copy it, open in
  incognito → public page renders, no nav, no costs, no
  confirmation #s.
- Toggle "Include notes in public view" off → reload incognito →
  notes section hidden.
- Print preview from auth view → static-image map visible, footer
  actions hidden, no JS chrome.
- Revoke link → reopen incognito URL → 404.
- Geocoding incomplete edge case: in_progress trip with one pin not
  yet geocoded → page still renders; that pin missing from map but
  appearing in highlights/all-days.

Target: ~35 new tests. Project sits at 419 passing; we'd land
somewhere around 450–455.

---

## Slices / implementation order

Each phase is independently shippable. We commit and verify at every
phase boundary.

### Phase 1 — Foundation
- **T1.** Migration: add `ItineraryItem.starred`,
  `Trip.yearbook_share_token`, `Trip.yearbook_public_show_notes`,
  `Trip.yearbook_public_show_spend`. Run on local SQLite; verify
  with `sqlite3 vacation.db ".schema"`.
- **T2.** `src/yearbook.py` pure helpers +
  `tests/test_yearbook.py`. All unit tests pass.

### Phase 2 — Starring (smallest user-visible slice)
- **T3.** `POST /trips/<id>/items/<item_id>/star` route + access
  guards + integration tests.
- **T4.** Star button on itinerary cards + optimistic-update JS in
  `static/js/yearbook.js`. Viewer disabled state.

After Phase 2: starring works end-to-end; the data goes nowhere yet
(no yearbook page). Still a small visible feature.

### Phase 3 — Authenticated yearbook
- **T5.** `GET /trips/<id>/yearbook` route + `yearbook.html`
  skeleton (hero + numbers + notes). Visibility logic + tests.
- **T6.** Interactive Mapbox GL block on yearbook page.
- **T7.** Highlights section + "All days at a glance" chip strip +
  yearbook tile on trip overview.

After Phase 3: a fully usable retrospective for the trip owner /
collaborators. Print works (browsers print interactive maps
poorly, but it's not unusable). Sharing not yet built.

### Phase 4 — Public share
- **T8.** `POST /trips/<id>/yearbook/share` + visibility toggles
  route + `build_static_map_url` in `src/map_helpers.py` + tests.
- **T9.** `GET /yearbook/<token>` public route + sanitized
  template branch + the share-toggle UI on the auth view.

### Phase 5 — Print polish
- **T10.** `@media print` CSS rules + static-image fallback wiring
  on auth view + manual print test on all three view modes.

**Total: 10 tasks across 5 phases.** Fits comfortably under the
17-task / 1000-line plan cap.

---

## Done when

- All 10 tasks shipped, each behind its own commit.
- All ~35 new tests pass; full suite green.
- Manual smoke checklist completed.
- Yearbook visible on trip overview for in_progress + completed trips.
- Starring works from itinerary page, reflects on yearbook.
- Public share link works in incognito; respects show_notes /
  show_spend toggles.
- Print preview is clean: static map, no footer actions, no
  preview banner.
- Spec + implementation plan both committed.

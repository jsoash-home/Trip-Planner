# Fun Countdown — Design Spec

**Date:** 2026-05-25
**Status:** Approved (defaults chosen by user 2026-05-25)

## Goal

Replace the small countdown chip with a delightful countdown experience: a live-ticking hero on the trip overview page, milestone celebrations with confetti, a progress ring on dashboard cards, emoji-themed copy, and a "sleeps until" unit toggle.

## Decisions baked in

| Decision | Choice | Rejected alternative |
|---|---|---|
| Sleeps mode persistence (G) | `localStorage` key `vp.countdown.unit` | New `User.countdown_unit` column |
| Themed copy source (F) | `trip.cover_emoji` → theme word table | Destination string keyword matching |
| Progress ring baseline (D) | Fixed 90-day window | Per-trip `created_at` baseline |
| Confetti library | `canvas-confetti` via CDN (~6 KB) | Hand-rolled emoji rainfall |
| Reduced-motion | Respect `prefers-reduced-motion: reduce` — skip animations, render static milestone copy | Always animate |
| Server-side unit awareness | None — JS swaps `data-countdown-*` on load, brief flash acceptable | Render unit on server from cookie |

**No schema changes.** No new DB columns. All client-side state in `localStorage`.

## Architecture

Three new pure helpers in `src/trip_helpers.py`:

```python
def progress_fraction(start: date, today: date, window_days: int = 90) -> float:
    """0.0 when today is >= window_days before start; 1.0 at start or later."""

def emoji_theme(emoji: Optional[str]) -> Optional[str]:
    """Map cover emoji to a theme word. Returns None for unknown / default."""

def themed_countdown_label(start, end, today, emoji) -> str:
    """Like countdown_label but substitutes theme phrasing when emoji matches."""
```

One new vanilla JS file `static/js/countdown.js` that:
1. Reads the unit toggle from `localStorage` and applies it to every element with `data-countdown-unit`
2. Ticks the hero countdown (`data-countdown-hero`) every second
3. On page load, checks the current threshold and fires the milestone celebration if not yet seen for this trip (keyed `vp.celebrated.<trip_id>.<threshold>` in `localStorage`)

One new template partial `templates/_countdown_hero.html` rendered at the top of `trip_overview.html` when the trip is upcoming.

Existing `templates/_trip_card.html` gets a progress-ring variant for upcoming trips; active/past keep the current chip.

## Slices

### Slice 1 — Hero countdown on trip overview page (A)
Big `D-23 · 4h 12m 07s` block above the trip overview header for upcoming trips only. Static "Welcomed home 14 days ago" for completed trips. In-progress trips show nothing extra (the existing "Today" section is the hero).

**Files:** `templates/_countdown_hero.html` (new), `templates/trip_overview.html` (include), `static/css/app.css` (hero styles), `static/js/countdown.js` (ticker).

### Slice 2 — Milestone celebrations (C)
Thresholds: **30, 14, 7, 3, 1**. When the page loads and `days_until == threshold` and the `vp.celebrated.<trip_id>.<threshold>` key is unset, swap the hero copy to celebratory text (`"🎉 One week to go!"`) and fire a confetti burst. Mark the key set. Reduced-motion: no confetti, but copy still swaps.

**Files:** `static/js/countdown.js`, CDN script tag in `templates/base.html`.

### Slice 3 — Progress ring on dashboard cards (D)
SVG ring around the days-remaining number for upcoming-trip cards. `progress_fraction(start, today, 90)` drives the stroke-dashoffset. Active and past cards keep the existing text chip.

**Files:** `src/trip_helpers.py`, `tests/test_trip_helpers.py`, `templates/_trip_card.html`, `static/css/app.css`.

### Slice 4 — Themed countdown copy (F)
Emoji → theme word lookup:

| Emoji | Theme phrase fragment |
|---|---|
| 🏝️ 🌴 🌊 | "the beach" |
| ✈️ | "takeoff" |
| 🏔️ ⛷️ | "the mountains" |
| 🍝 🍜 | "the next great meal" |
| 🏛️ | "history" |
| 🚗 | "the open road" |
| 🏨 | "check-in" |
| 🗽 | "the city" |
| (anything else, including 🧳 default) | none — falls back to plain |

When themed and unit is `sleeps`: `"23 sleeps until the beach"`. When themed and unit is `days`: `"23 days until the beach"`. When unthemed: existing `countdown_label` output.

**Files:** `src/trip_helpers.py`, `tests/test_trip_helpers.py`, `templates/_trip_card.html`, `templates/_countdown_hero.html`.

### Slice 5 — Sleeps mode toggle (G)
Small pill button in the dashboard header next to the "New trip" button: `"Days · Sleeps"` segmented control. Click writes to `localStorage["vp.countdown.unit"]`, the JS module then updates every `data-countdown-unit` element on the page in place.

**Files:** `templates/trips_list.html` (toggle), `static/js/countdown.js` (apply on load + on click), `static/css/app.css` (toggle styles).

## Data flow

```
Server render
  → renders both forms in DOM: data-countdown-days="23" data-countdown-sleeps="23 sleeps until the beach"
  → JS reads localStorage, sets visibility on the matching span
  → JS starts hero tick (overview page only)
  → JS checks threshold; fires confetti if first time
Toggle click
  → updates localStorage
  → JS re-runs the visibility swap
```

The "brief flash" is acceptable because we start in the default unit (`days`) on both server and JS — only users who toggled away from default see the swap, and it happens on `DOMContentLoaded` before paint stabilizes.

## Error handling

- `localStorage` unavailable (private browsing, very old browsers) → JS catches `SecurityError`, falls back to default unit, no milestone dedup (re-fires on each visit — annoying but not broken)
- `cover_emoji` is `None` or unknown → `themed_countdown_label` returns plain output
- `progress_fraction` clamps to `[0.0, 1.0]` so a trip 200 days away renders an empty ring, not negative
- Trip with `start_date < today` (race during midnight) → hero is past-state copy; progress ring is full
- No confetti CDN (offline) → milestone copy still swaps, no animation; warning logged to console

## Testing

**Unit tests (new):**
- `tests/test_trip_helpers.py`:
  - `progress_fraction` — at start, mid-window, beyond window, clamps below 0, clamps above 1
  - `emoji_theme` — known emojis, unknown emoji, `None`, default `🧳`
  - `themed_countdown_label` — themed upcoming, themed today/last day, themed past, unthemed fallback, with both unit values

**Manual smoke:**
- Trip 23 days out, themed emoji → hero shows "23 days until X", ticking
- Toggle to sleeps → updates everywhere without page reload
- Move system clock to 7 days before trip, reload → confetti fires once, mark in localStorage, reload again → no confetti
- Enable reduced-motion → no confetti, copy still swaps
- Past trip → static "welcomed home" copy, no ticker
- Unknown emoji → plain "23 days to go"

## Out of scope

- Per-user (server-side) preference for unit choice
- Custom theme phrases per user
- Destination keyword matching (emoji-only)
- Animations on the dashboard ring filling up over time (static snapshot only)
- Sound effects on milestones
- Sharing milestone screenshots
- Confetti customization per theme

## Done when

- All 5 slices visible in browser smoke test
- All new pure helpers covered by unit tests
- `pytest` green
- Reduced-motion behaves correctly
- Spec & implementation plan both committed

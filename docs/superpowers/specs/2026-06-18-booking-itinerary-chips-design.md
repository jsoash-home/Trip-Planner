# Booking ↔ Itinerary Chips — Design

**Date:** 2026-06-18
**Status:** Approved, ready for implementation plan
**Scope:** Templates + CSS + tiny JS. No routes, no models, no migrations.

## Problem

A booking can auto-spawn itinerary items (a flight produces Depart and
Arrive entries, a hotel produces Check-in and Check-out, etc.). The
relationship is stored cleanly in the database — `ItineraryItem.linked_booking_id`
points back at the source `Booking` — but the UI barely exposes it:

- **Itinerary page:** linked items show a tiny 🔗 icon with a tooltip
  ("Linked to a booking"). The booking is not named, and the icon is
  not clickable.
- **Bookings page:** shows nothing. No way to know a booking has spawned
  items, no way to jump to them.
- **Deleting orphans:** the delete button works for any item, but the
  user can't tell at a glance which items are standalone (safe to
  delete) vs. linked (deleting will leave an orphan booking).

The user wants to *see* the relationship clearly in both directions, and
have an obvious cue for "this one is standalone, fine to delete."

## Goals

1. From an itinerary item, see which booking it came from, and click
   through to that booking.
2. From a booking, see how many itinerary items it spawned, and click
   through to them.
3. Standalone (unlinked) itinerary items are visually obvious by the
   absence of a chip — no extra label needed.

## Non-goals

- No "Standalone" pill on unlinked items. Absence of a chip is the signal.
- No bulk "delete all unlinked" view or filter. Per-item delete already
  works and the new chips make orphans easy to spot.
- No backend changes — relationships and FKs are already in place.
- No new routes. Existing `booking_edit` and `itinerary` routes are
  the link targets.

## Solution overview

Two new chips, one per side, mirroring each other:

### Itinerary side

Replace the existing icon-only `linked_booking` hint with a clickable
pill on each linked item:

```
[ 🏨 Holiday Inn — view booking → ]
```

- **Text:** `{booking type emoji} {booking.vendor or booking.title}`.
  Vendor preferred since it's usually the meaningful name (e.g. "United"
  for a flight). Falls back to booking title when vendor is empty,
  matching the auto-spawn helper's existing rule.
- **Element:** `<a>` styled as a chip; clicking navigates to
  `/trips/<trip_id>/bookings/<booking_id>/edit`.
- **Tooltip:** keep "Linked to a booking — click to view" via `title=`
  for accessibility.
- **Unlinked items:** no chip rendered. The empty space is the signal.

### Booking side

For each booking with at least one linked item, render a small chip on
its row in `bookings_list.html`:

```
[ 🗓 2 in itinerary → ]   (or "1 in itinerary" for singular)
```

- **Element:** `<a>` styled as a chip; clicking navigates to
  `/trips/<trip_id>/itinerary#item-{first_linked_item_id}`.
- **"First" means** chronologically — sorted by `day_date`, then
  `start_time` (None last), then `order_within_day`. This matches the
  existing `sort_within_day` helper's ordering rule. Computed in the
  `bookings_list` route (see Implementation notes), not in the template.
- **Multi-item bookings** (flight: Depart + Arrive) get **one** chip.
  Once the user lands on the itinerary page, the per-item chips on the
  other days let them find the rest in one glance.

### Arrival highlight

When the itinerary page loads with a `#item-{id}` hash, briefly flash
the target chip so the user sees where the jump landed.

- Reuses the existing `data-just-synced` flash pattern already used by
  the itinerary drift sync feature.
- Implemented as ~15 lines of JS in `static/js/itinerary.js` that read
  `location.hash` on `DOMContentLoaded`, find the element, set
  `data-just-synced="true"` on it for ~2 seconds, then clear.

## File changes

| File | Change |
|---|---|
| `templates/trip_itinerary.html` | Replace lines ~121–125 (icon-only `linked_booking` block) with a clickable pill `<a>`. Add `id="item-{{ it.id }}"` to each `.itin-chip` div (line ~106). |
| `templates/bookings_list.html` | In the `{% for b in items %}` loop, render the "N in itinerary" chip when `b.itinerary_items` is non-empty. |
| `static/js/itinerary.js` | Add a `DOMContentLoaded` handler that flashes `#item-{N}` if present in `location.hash`. |
| `static/css/app.css` | Two new classes: `.itin-chip-booking-link` (the clickable pill on itinerary items) and `.booking-row-itin-chip` (the chip on booking rows). |

## Implementation notes

- **First linked item lookup.** Compute in the `bookings_list` route:
  build a `first_linked_item_id: dict[int, int]` keyed by booking id
  and pass it to the template alongside `grouped`. The sort logic
  lives in a new pure helper `first_linked_itinerary_item(items)` in
  `src/booking_helpers.py`, sharing the same sort key as
  `src/itinerary.py`'s `sort_within_day` (`day_date`, `start_time`
  with None last, `order_within_day`). Unit-tested per project rules.
- **Booking type emoji on the itinerary chip.** The template already
  has the `BOOKING_TYPES` constant accessible via the existing
  `booking_types` template global (used on `bookings_list.html`'s
  filter bar). Use the same lookup — don't introduce a parallel map.
- **Accessibility.** Both chips are real `<a>` tags with `aria-label`
  text that includes both the action and the target ("View booking:
  Holiday Inn", "Jump to 2 linked itinerary items").
- **Style.** Chips should feel native to existing styles. The
  itinerary-side pill should pick up the category tint of the
  *booking's type* (a hotel chip subtle blue, a flight chip subtle
  green, etc.), to make scanning easier. The booking-side chip can
  use the neutral `.filter-chip` look that already exists in the same
  template.
- **Delete UX.** Unchanged. The new chips make linked items visually
  obvious; the absence of a chip makes standalone items obvious. The
  existing trash button on each itinerary chip works for both.

## Edge cases

- **Booking linked to items on multiple days.** Handled — the booking
  chip jumps to the chronologically first item; the per-item chips
  link back from each one.
- **Item linked to a booking that was deleted.** Can't happen at the
  DB level due to `cascade="save-update, merge, delete"` on
  `Booking.itinerary_items`. If a stale FK ever appeared, the
  template's `{% if it.linked_booking %}` guard would render nothing
  (treat as standalone) — no crash.
- **User manually un-linked an item** (FK set to NULL via a future
  feature). Currently no UI does this, but if it ever existed, the
  item would render as standalone. Fine.
- **Booking on `bookings_list` that has 0 linked items** (e.g. a
  transport / other type that doesn't auto-spawn, or a flight with
  no datetimes). No chip rendered. Matches the "absence = signal"
  rule.

## Testing

Pure-helper tests for any new function added to `src/booking_helpers.py`
(e.g. `first_linked_itinerary_item(items)` if extracted). Template
behaviour is verified by the existing `webapp-testing` flow per
project rules: load `/trips/<id>/itinerary` and `/trips/<id>/bookings`
in headless Chrome, confirm zero console errors and that the new
chips render with the expected text and `href`.

## Out of scope (could come later)

- A "show only standalone items" filter on the itinerary page.
- A dropdown on the booking-row chip listing every linked item with
  per-item jump links (would be useful only for bookings with 3+
  items, which is rare).
- A way to manually link an existing standalone itinerary item to a
  booking after the fact (currently linking is only done at booking
  creation by the auto-spawn helper).

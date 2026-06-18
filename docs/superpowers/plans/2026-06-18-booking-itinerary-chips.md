# Booking ↔ Itinerary Chips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing `ItineraryItem.linked_booking_id` relationship visible in both directions via two clickable, mirroring chips — one on each itinerary item that came from a booking, one on each booking that spawned items.

**Architecture:** No backend changes. One new pure helper in `src/booking_helpers.py` computes the chronologically-first linked item per booking. The `bookings_list` route builds a `{booking_id → first_item_id}` dict and passes it to the template. Templates render two new chip classes; CSS adds two small style blocks; a tiny JS hook flashes `#item-{N}` on arrival using the existing `data-just-synced` animation.

**Tech Stack:** Flask, Jinja2, Bootstrap 5, vanilla JS. Pure helpers tested with pytest.

**Source spec:** `docs/superpowers/specs/2026-06-18-booking-itinerary-chips-design.md`

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `src/booking_helpers.py` | Modify | Add `first_linked_itinerary_item(items)` pure helper. |
| `tests/test_booking_helpers.py` | Modify | Add unit tests for the new helper. |
| `app.py` | Modify | In `bookings_list`, build `first_linked_item_id` dict and pass to template. |
| `templates/bookings_list.html` | Modify | Render `.booking-row-itin-chip` on each booking row with linked items. |
| `templates/trip_itinerary.html` | Modify | Add `id="item-{N}"` to each `.itin-chip` and replace the icon-only `linked_booking` hint with a clickable `.itin-chip-booking-link` pill. |
| `static/css/app.css` | Modify | Add `.itin-chip-booking-link` and `.booking-row-itin-chip` styles. Reuse existing `[data-just-synced]` animation. |
| `static/js/itinerary.js` | Modify | Add `DOMContentLoaded` hook: if `location.hash` matches `#item-N`, set `data-just-synced="true"` on that element briefly. |

---

## Public surface

### New pure helper

```python
# src/booking_helpers.py
def first_linked_itinerary_item(items: Iterable) -> Optional[Any]:
    """
    Pick the chronologically first item from a sequence of ItineraryItem
    rows linked to one booking.

    Sort order matches the spec: (day_date, start_time None-last,
    order_within_day, id). Returns None for an empty input. Pure: takes
    any objects exposing day_date/start_time/order_within_day/id.
    """
```

Sort key sketch (handles `None` start_time without `TypeError`):

```python
from datetime import time as _time
def _key(it):
    st = getattr(it, "start_time", None)
    return (
        getattr(it, "day_date", None),
        st is None,
        st or _time.min,
        getattr(it, "order_within_day", 0) or 0,
        getattr(it, "id", 0) or 0,
    )
```

Note: `sort_within_day` in `src/itinerary.py` puts untimed items FIRST within a day. This helper puts them LAST. The spec calls for "None last" to find the chronologically first *timed* anchor for the jump link; a timed item is a more meaningful jump target than an untimed one.

### Route plumbing (`bookings_list`)

Build the dict after the existing `grouped = group_bookings_by_type(bookings)` line:

```python
first_linked_item_id: Dict[int, int] = {}
for b in bookings:
    first = first_linked_itinerary_item(b.itinerary_items)
    if first is not None:
        first_linked_item_id[b.id] = first.id
```

Pass it to `render_template`:

```python
return render_template(
    "bookings_list.html",
    ...
    first_linked_item_id=first_linked_item_id,
)
```

Import update in `app.py`:

```python
from src.booking_helpers import (
    ...,
    first_linked_itinerary_item,
)
```

### Template — booking-side chip (`bookings_list.html`)

Insert immediately after the `booking-row-meta` block (around line 116, before the `notes` block) so the chip lands under the meta line:

```jinja
{% set linked_count = b.itinerary_items | length %}
{% if linked_count > 0 and first_linked_item_id.get(b.id) %}
  <a class="booking-row-itin-chip"
     href="{{ url_for('itinerary', trip_id=trip.id) }}#item-{{ first_linked_item_id[b.id] }}"
     aria-label="Jump to {{ linked_count }} linked itinerary item{{ '' if linked_count == 1 else 's' }}">
    <span aria-hidden="true">🗓</span>
    {{ linked_count }} in itinerary →
  </a>
{% endif %}
```

### Template — itinerary-side pill (`trip_itinerary.html`)

Add the per-item anchor to the existing `.itin-chip` opening tag (around line 106):

```jinja
<div class="itin-chip {{ category_css(it.category) }}"
     id="item-{{ it.id }}"
     {% if it.id|string in just_synced_ids %}data-just-synced="true"{% endif %}>
```

Replace the icon-only `linked_booking` block (lines ~121–125) with the clickable pill. The pill goes BELOW the `.itin-chip-title` line, at the same level as `.itin-chip-meta`, so it doesn't get cramped inside the title flex row:

```jinja
{# inside .itin-chip-title, drop the existing icon-only span entirely #}

{# below .itin-chip-title, sibling of .itin-chip-meta: #}
{% if it.linked_booking %}
  {% set b = it.linked_booking %}
  {% set chip_label = b.vendor or b.title %}
  <a class="itin-chip-booking-link is-{{ b.type }}"
     href="{{ url_for('booking_edit', trip_id=trip.id, booking_id=b.id) }}"
     title="Linked to a booking — click to view"
     aria-label="View booking: {{ chip_label }}">
    <span aria-hidden="true">{{ booking_type_emoji(b.type) }}</span>
    {{ chip_label }} <span aria-hidden="true">→</span>
  </a>
{% endif %}
```

Note: the template already accesses `it.linked_booking` via the SQLAlchemy `backref` (defined in `models.py:158`) — no route change needed.

### CSS additions (`static/css/app.css`)

Place near the other `.itin-chip-*` rules (after line ~928):

```css
.itin-chip-booking-link {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.35rem;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  border: 1px solid var(--vp-border);
  background: var(--vp-surface);
  color: var(--vp-text-muted);
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.2;
  text-decoration: none;
  transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}
.itin-chip-booking-link:hover {
  background: var(--vp-surface-2);
  color: var(--vp-text);
  border-color: var(--vp-text-muted);
}
.itin-chip-booking-link:focus-visible {
  outline: 2px solid var(--vp-accent);
  outline-offset: 2px;
}

/* Tint by source booking type — subtle background only, so it reads as
   "from the same family" without competing with the parent chip's
   category color. */
.itin-chip-booking-link.is-flight     { background: rgba(34, 197, 94, 0.10); }
.itin-chip-booking-link.is-hotel      { background: rgba(59, 130, 246, 0.10); }
.itin-chip-booking-link.is-car        { background: rgba(234, 179, 8, 0.10); }
.itin-chip-booking-link.is-restaurant { background: rgba(244, 114, 182, 0.10); }
.itin-chip-booking-link.is-activity   { background: rgba(168, 85, 247, 0.10); }
.itin-chip-booking-link.is-transport,
.itin-chip-booking-link.is-other      { background: var(--vp-surface); }
```

Place near `.booking-row-actions` (around line 741):

```css
.booking-row-itin-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.35rem;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  border: 1px solid var(--vp-border);
  background: var(--vp-surface);
  color: var(--vp-text-muted);
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.2;
  text-decoration: none;
  transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}
.booking-row-itin-chip:hover {
  background: var(--vp-surface-2);
  color: var(--vp-text);
  border-color: var(--vp-text-muted);
}
.booking-row-itin-chip:focus-visible {
  outline: 2px solid var(--vp-accent);
  outline-offset: 2px;
}
```

Existing `[data-just-synced]` animation (CSS at app.css:498) already provides the arrival flash — no new keyframe needed.

### JS — arrival flash (`static/js/itinerary.js`)

Append to the existing IIFE — keep it inside the same `(function () { 'use strict'; ... }());` block. Place it BEFORE the closing `}());` and AFTER the existing `activate(initial, false);` call:

```javascript
  // Item-level arrival flash. If the page loaded with #item-N in the
  // URL (e.g. from the bookings-list chip), briefly highlight that chip
  // using the existing data-just-synced animation.
  var itemMatch = (location.hash || '').match(/^#item-(\d+)$/);
  if (itemMatch) {
    var target = document.getElementById('item-' + itemMatch[1]);
    if (target) {
      target.setAttribute('data-just-synced', 'true');
      setTimeout(function () {
        target.removeAttribute('data-just-synced');
      }, 1400);
    }
  }
```

Notes:
- 1400 ms ≥ the 1200 ms animation duration in `app.css:499`. Cleanup removes the attribute so a subsequent re-flash (e.g. from the drift-sync code) still re-triggers the animation.
- No scrollIntoView needed — the browser already scrolls to `#item-N` on hash load.

---

## Test list

New tests in `tests/test_booking_helpers.py` for `first_linked_itinerary_item`:

- `test_first_linked_itinerary_item_empty_returns_none`
- `test_first_linked_itinerary_item_single_item_returns_it`
- `test_first_linked_itinerary_item_earliest_day_wins`
- `test_first_linked_itinerary_item_timed_beats_untimed_same_day`
- `test_first_linked_itinerary_item_earlier_time_wins_same_day`
- `test_first_linked_itinerary_item_order_within_day_breaks_tie`
- `test_first_linked_itinerary_item_id_breaks_tie_when_keys_equal`

Use `dataclasses.dataclass` (`FakeItem` with `id`, `day_date`, `start_time`, `order_within_day`) for fixtures — mirrors the existing `FakeBooking` pattern at `tests/test_booking_helpers.py:24`.

Browser verification (per `CLAUDE.md` rule) lives at the end of the plan — Task 7.

---

## Tasks

### Task 1: Add `first_linked_itinerary_item` pure helper

**Files:**
- Modify: `src/booking_helpers.py` (add function near `group_bookings_by_type`, ~line 168)
- Test: `tests/test_booking_helpers.py` (extend the existing import block + add a new test section)

- [ ] **Step 1:** Write the 7 failing tests listed above. Test names only — bodies are normal pytest functions using `FakeItem` dataclasses. Run them and confirm they all fail with `ImportError: cannot import name 'first_linked_itinerary_item'`.

- [ ] **Step 2:** Implement `first_linked_itinerary_item` using the sort key shown in the "Public surface" section. Add `Any` to the `typing` import if not already present.

- [ ] **Step 3:** Run `pytest tests/test_booking_helpers.py -v` and confirm all 7 new tests + the existing 100+ tests pass.

- [ ] **Step 4:** Commit:

```bash
git add src/booking_helpers.py tests/test_booking_helpers.py
git commit -m "feat: first_linked_itinerary_item helper for booking → itinerary chip"
```

---

### Task 2: Wire `first_linked_item_id` into the `bookings_list` route

**Files:**
- Modify: `app.py` (import + `bookings_list` route at lines 1949–1985)

- [ ] **Step 1:** Add `first_linked_itinerary_item` to the import block in `app.py:62` near the other `booking_helpers` imports.

- [ ] **Step 2:** In `bookings_list`, after `grouped = group_bookings_by_type(bookings)` (line 1964), add the dict-build loop shown in the "Route plumbing" section. Pass `first_linked_item_id=first_linked_item_id` as a new kwarg to `render_template` (after the existing `active_type_label=...`).

- [ ] **Step 3:** Run `pytest -q` and confirm zero regressions.

- [ ] **Step 4:** Commit:

```bash
git add app.py
git commit -m "feat: pass first_linked_item_id dict to bookings_list template"
```

---

### Task 3: Render booking-side chip in `bookings_list.html`

**Files:**
- Modify: `templates/bookings_list.html` (inside the `{% for b in items %}` loop around line 100)

- [ ] **Step 1:** Add the chip block shown in the "Template — booking-side chip" section. Place it as the LAST child of `.booking-row-main`, after the `{% if b.notes %}` block (around line 119). This keeps it inside the main column, below the notes if present.

- [ ] **Step 2:** Visual smoke check via the dev server (port 5002):
  - Bookings list shows `🗓 N in itinerary →` on rows whose booking spawned items.
  - Rows with zero linked items show no chip.
  - Click navigates to `/trips/<id>/itinerary#item-<N>`.
  - Per `CLAUDE.md` frontend rule: open `http://localhost:5002` (NOT 127.0.0.1) and confirm zero browser console errors.

- [ ] **Step 3:** Commit:

```bash
git add templates/bookings_list.html
git commit -m "feat: booking row chip linking to first itinerary item"
```

---

### Task 4: Add per-item anchors + clickable booking pill to `trip_itinerary.html`

**Files:**
- Modify: `templates/trip_itinerary.html` (line 106 for the anchor; lines 121–125 for the old `linked_booking_id` block; insert new pill below line 126)

- [ ] **Step 1:** Add `id="item-{{ it.id }}"` to the `.itin-chip` opening tag at line 106 (see exact diff in "Public surface" → "Template — itinerary-side pill").

- [ ] **Step 2:** Delete the existing `{% if it.linked_booking_id %} ... {{ icon('link-45deg') }} ... {% endif %}` block (lines 121–125) from inside `.itin-chip-title`.

- [ ] **Step 3:** Insert the new `{% if it.linked_booking %} ... <a class="itin-chip-booking-link is-{{ b.type }}"> ... </a> {% endif %}` block as a sibling of `.itin-chip-meta` (between the title `</div>` closing tag at line 126 and the `{% if it.location %}` block at line 127).

- [ ] **Step 4:** Smoke check at `http://localhost:5002/trips/<id>/itinerary`:
  - Items linked to a booking show a pill with the booking type emoji + vendor/title.
  - Items without a linked booking show no pill (no leftover link icon).
  - Clicking a pill navigates to `/trips/<id>/bookings/<booking_id>/edit`.
  - Browser console clean.

- [ ] **Step 5:** Commit:

```bash
git add templates/trip_itinerary.html
git commit -m "feat: clickable booking pill on linked itinerary items + per-item anchors"
```

---

### Task 5: CSS for both chips

**Files:**
- Modify: `static/css/app.css` (add `.itin-chip-booking-link` rules near line 928; add `.booking-row-itin-chip` rules near line 745)

- [ ] **Step 1:** Add the `.itin-chip-booking-link` block (including the per-type background tints) shown in the "CSS additions" section, after the existing `.itin-chip-actions` rule (around line 928).

- [ ] **Step 2:** Add the `.booking-row-itin-chip` block shown in the "CSS additions" section, after `.booking-row-actions` (around line 745).

- [ ] **Step 3:** Reload `/trips/<id>/itinerary` and `/trips/<id>/bookings` with a cache-buster (`?v=2` etc.). Confirm:
  - Itinerary pill is rounded, subtly tinted by booking type, clickable, focusable.
  - Booking-row chip is the same rounded shape, neutral surface, hover darkens.
  - Browser console clean.

- [ ] **Step 4:** Commit:

```bash
git add static/css/app.css
git commit -m "style: chip styles for booking ↔ itinerary cross-links"
```

---

### Task 6: Arrival flash JS in `static/js/itinerary.js`

**Files:**
- Modify: `static/js/itinerary.js` (append the `#item-N` hook inside the existing IIFE)

- [ ] **Step 1:** Add the snippet shown in the "JS — arrival flash" section AFTER `activate(initial, false);` (current line 87) and BEFORE the closing `}());`.

- [ ] **Step 2:** From a bookings page, click a `.booking-row-itin-chip`. Confirm:
  - The browser jumps to the itinerary page at the target item.
  - The target chip briefly pulses green (existing `vp-pulse-success` animation).
  - The pulse fades and is removable: click again with a different `#item-N` → it re-fires.
  - Reduced-motion users see no animation (the existing `@media (prefers-reduced-motion: no-preference)` guard handles this).
  - Browser console clean.

- [ ] **Step 3:** Commit:

```bash
git add static/js/itinerary.js
git commit -m "feat: flash target itinerary chip on #item-N arrival"
```

---

### Task 7: Browser verification per CLAUDE.md

**Files:** None modified. This is the mandatory frontend verification step.

- [ ] **Step 1:** Ensure dev server is running on port 5002. Use the `webapp-testing` skill to load `/trips/<id>/itinerary` headless. Confirm zero console errors and that linked items have a visible pill.

- [ ] **Step 2:** Load `/trips/<id>/bookings` headless. Confirm zero console errors and that bookings with linked items show the `🗓 N in itinerary →` chip.

- [ ] **Step 3:** Navigate from a booking chip to `#item-N`. Confirm the page jumps and the target highlights briefly. Capture the proof (screenshot or DOM snapshot showing `data-just-synced="true"` on the target chip during the window).

- [ ] **Step 4:** Pick a trip with at least one unlinked itinerary item and one linked itinerary item. Confirm the unlinked one has NO pill (absence-as-signal per spec).

- [ ] **Step 5:** Run the full test suite once more: `pytest -q`. Confirm green.

- [ ] **Step 6:** No commit unless verification revealed a fix.

---

## Self-review notes

- Spec coverage: every section of the spec maps to a task. Itinerary side → Task 4 + 5. Booking side → Tasks 2, 3, 5. Arrival flash → Task 6. Pure helper → Task 1. Browser verify → Task 7.
- No placeholders. All code blocks above are concrete enough to copy.
- Type consistency: the helper is called `first_linked_itinerary_item` in the helper module, the route variable is `first_linked_item_id`, the template kwarg is `first_linked_item_id`. The `is-{type}` CSS modifier matches the codes in `BOOKING_TYPES` (`flight`, `hotel`, `car`, `transport`, `activity`, `restaurant`, `other`).
- One thing to watch: the spec wording says the sort key "matches `sort_within_day`'s ordering rule" but `sort_within_day` puts untimed FIRST and the spec says "None last." This plan follows the spec's explicit "None last" rule (a timed anchor is a better jump target). If the user wants this changed during implementation, only Task 1's sort key needs to flip.

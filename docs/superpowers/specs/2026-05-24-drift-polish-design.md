# Booking ↔ Itinerary Drift — Phase 4 "Polish" Design Spec

**Status:** approved design (2026-05-24), ready for implementation plan.

**Audience:** the engineer (likely future Claude + Jeff) who will translate this
into an implementation plan via `superpowers:writing-plans`.

---

## Goal

Three small polish improvements on top of phases 1–3 (per-item drift, bulk review,
per-field smart preservation), plus a gated cleanup task to retire the deprecated
`customized_by_user` column:

1. **Dashboard tile pills.** Show drift and "new items available" counts as small
   pills on each trip card on the dashboard so the user sees an actionable trip
   without opening it.
2. **Animations on the resync moment.** Animated flash messages, a "just synced"
   pulse on the item that was fixed, and a positive "all in sync!" flash when
   the last drift on a trip clears.
3. **Keyboard shortcuts in the drift review wizard.** Single-key bindings for
   the four wizard actions plus a visible hint row.
4. **Drop the deprecated `customized_by_user` column.** Gated as the final task
   in the plan — requires explicit confirmation that phase 3 has been in use
   for at least a week without rollback.

Each slice is independent. No shared abstractions, no new data model except the
column drop, no new dependencies.

## Out of scope

- AJAX / htmx — the "just synced" feedback is delivered via a URL param + CSS
  pulse on the next page load, not via in-place DOM updates. Introducing htmx
  is a bigger architectural shift than this polish phase warrants.
- A re-silence affordance ("silence all drift on this item" follow-up to phase
  3's "Keep mine"). Phase 3 just landed; the behavior change hasn't surprised
  anyone yet. Revisit if it does.
- Animations on B (drift pill appearance) and C (wizard step transitions) and
  E (dashboard badge pulse) from the brainstorming. The chosen set is the
  "you accomplished something" moments only.
- Keyboard shortcuts outside the wizard step. The detail page and landing page
  stay mouse-only; the wizard is where speed matters.
- A `?` overlay listing shortcuts. The visible hint row is enough.
- Persistent dismissal of the dashboard pills. Pills disappear when their
  count reaches zero, not via a "dismiss" action.

## File map

| File | Action | Responsibility |
|---|---|---|
| `src/drift_review.py` | Modify | Add `drift_counts_for_trips(trips)` pure helper — batched `{trip_id: (drift_count, new_count)}` lookup. |
| `app.py` | Modify | `trips_list` calls the batched helper and passes counts to the template. `itinerary_resync` adds `?just_synced=<id>` and a `success-celebrate` flash category when the last drift clears. `_apply_resync_to_item` returns `(success, was_last_drift)`. Bulk-resync uses the same celebration check. Add the `customized_by_user` `DROP COLUMN` statement to `_ensure_drift_columns` (gated task). |
| `models.py` | Modify | Remove the `customized_by_user` column declaration (gated task). |
| `templates/_trip_card.html` | Modify | Render two pill row when drift/new counts > 0. |
| `templates/trips_list.html` | Modify | Pass `counts` into the `trip_card` macro. |
| `templates/trip_itinerary.html` | Modify | Read `?just_synced=<id>` from request and stamp `data-just-synced` on matching item(s). |
| `templates/drift_review_item.html` | Modify | Add IDs to action buttons + Skip + Back links. Add the keyboard-shortcut hint row. Add the inline keydown handler in `{% block scripts %}`. |
| `templates/_drift_actions.html` | Modify | Add unconditional `id` attributes on the Resync / Keep / Unlink form buttons (`id="resync-btn"`, etc.). |
| `templates/base.html` | Modify | Allow new flash category `success-celebrate` in the category whitelist. Add the auto-dismiss JS at the bottom (one block, ~15 lines). |
| `static/css/app.css` | Modify | Pill styles for the trip card. Flash slide-in keyframe + auto-dismiss class. `data-just-synced` pulse keyframe. `success-celebrate` flash variant. `vp-shortcut-hint` + `kbd` styling. All animations wrapped in `prefers-reduced-motion: no-preference`. |
| `tests/test_drift_review.py` | Modify | Tests for `drift_counts_for_trips`. |
| `tests/test_routes.py` | Modify | Tests: dashboard renders pills when drift exists; resync redirect includes `?just_synced`; flash category is `success-celebrate` when last drift clears; wizard renders hint row + action IDs. |

---

## Slice 1 — Dashboard tile pills

### Visual

Below the existing countdown chip on each trip card, when at least one count
is non-zero, render a small row of pills:

- Amber pill: `⚠ N out of sync`
- Blue pill: `＋ N suggested`

Each pill is rendered only when its count is `> 0`. When both are zero, the
entire row is omitted (no whitespace difference vs. today's card).

### Pure helper

`src/drift_review.py` gains:

```python
def drift_counts_for_trips(trips) -> Dict[int, Tuple[int, int]]:
    """For each trip, return (drift_count, new_items_count).

    Batched: one query for all relevant itinerary items, one for all
    relevant bookings, then in-memory grouping. Skips trips whose status
    is 'completed' or whose end_date is before today (drift on a finished
    trip isn't actionable).

    Returns a dict keyed by trip.id. Trips not in the result dict
    implicitly have (0, 0).
    """
```

Implementation outline (pseudocode):

```python
from datetime import date
from collections import defaultdict
from typing import Dict, Iterable, Tuple

from models import Booking, ItineraryItem
from src.booking_helpers import detect_drift, missing_auto_kinds_for_booking


def drift_counts_for_trips(trips) -> Dict[int, Tuple[int, int]]:
    today = date.today()
    active = [t for t in trips
              if t.status != "completed" and t.end_date >= today]
    if not active:
        return {}
    trip_ids = [t.id for t in active]

    bookings = Booking.query.filter(Booking.trip_id.in_(trip_ids)).all()
    items = ItineraryItem.query.filter(
        ItineraryItem.trip_id.in_(trip_ids)
    ).all()

    bookings_by_trip: Dict[int, list] = defaultdict(list)
    for b in bookings:
        bookings_by_trip[b.trip_id].append(b)

    items_by_trip: Dict[int, list] = defaultdict(list)
    bookings_by_id = {b.id: b for b in bookings}
    for it in items:
        items_by_trip[it.trip_id].append(it)

    out: Dict[int, Tuple[int, int]] = {}
    for t in active:
        # Drift count: per-item detect_drift, skip None.
        drift = 0
        existing_kinds_by_booking: Dict[int, set] = defaultdict(set)
        for it in items_by_trip.get(t.id, []):
            if it.linked_booking_id and it.auto_kind:
                existing_kinds_by_booking[it.linked_booking_id].add(it.auto_kind)
            if it.linked_booking_id in bookings_by_id:
                report = detect_drift(it, bookings_by_id[it.linked_booking_id])
                if report is not None:
                    drift += 1

        # New-items count: per-booking, missing slots in [start_date, end_date].
        new_count = 0
        for b in bookings_by_trip.get(t.id, []):
            existing = existing_kinds_by_booking.get(b.id, set())
            new_count += len(missing_auto_kinds_for_booking(
                b, existing, t.start_date, t.end_date,
            ))

        if drift > 0 or new_count > 0:
            out[t.id] = (drift, new_count)
    return out
```

Key design points:

- **One DB round-trip per table.** Two `IN`-clause queries cover all visible
  trips, no N+1.
- **Pure-ish.** Calls SQLAlchemy queries internally because the data lives in
  the DB and pre-fetching outside the helper would duplicate logic. The helper
  is still trivially testable with the in-memory SQLite fixture used by the
  existing route tests.
- **Skip completed trips.** Avoids nagging on finished trips, which is the
  90%+ source of "drift exists but nobody cares."

### Route change — `trips_list`

```python
from src.drift_review import drift_counts_for_trips

# Inside trips_list, after computing `trips`:
counts = drift_counts_for_trips(trips)
return render_template("trips_list.html",
                       grouped=group_trips_by_state(trips, today),
                       counts=counts,
                       today=today)
```

`trips_list.html` passes `counts` through to the `trip_card` macro invocation
sites — the macro signature gains an optional `counts` keyword:

```jinja
{% from "_trip_card.html" import trip_card %}
...
{{ trip_card(t, today, counts) }}
```

### Macro change — `_trip_card.html`

The signature becomes `trip_card(trip, today, counts=None)`. Inside, after the
existing countdown chip line:

```jinja
{% if counts %}
  {% set tc = counts.get(trip.id, (0, 0)) %}
  {% if tc[0] > 0 or tc[1] > 0 %}
    <div class="trip-card-status-row">
      {% if tc[0] > 0 %}
        <span class="trip-card-pill trip-card-pill--drift">
          <i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
          {{ tc[0] }} out of sync
        </span>
      {% endif %}
      {% if tc[1] > 0 %}
        <span class="trip-card-pill trip-card-pill--new">
          <i class="bi bi-plus-circle" aria-hidden="true"></i>
          {{ tc[1] }} suggested
        </span>
      {% endif %}
    </div>
  {% endif %}
{% endif %}
```

### CSS

Add to `static/css/app.css`:

```css
.trip-card-status-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.5rem;
}
.trip-card-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  line-height: 1.3;
}
.trip-card-pill--drift {
  background-color: #fff3cd;
  color: #8a4a00;
  border: 1px solid #ffe69c;
}
.trip-card-pill--new {
  background-color: #e0f2fe;
  color: #075985;
  border: 1px solid #bae6fd;
}
```

### Tests

In `tests/test_drift_review.py`:

- Empty trip list → empty dict.
- Trip with no bookings → not in dict.
- Trip with bookings and no drift → not in dict.
- Trip with one drifting item → `{trip.id: (1, 0)}`.
- Trip with a new auto-slot available → `{trip.id: (0, 1)}`.
- Completed trip (status='completed') is skipped.
- Past trip (end_date < today) is skipped.
- Two trips with different counts return both entries.

In `tests/test_routes.py`:

- GET `/trips` for a user with one drifting trip renders the `trip-card-pill--drift` class. (Use HTML scanning, not full DOM parsing.)

---

## Slice 2 — Animations

### 2a. Animated flash messages (global)

In `static/css/app.css`:

```css
@media (prefers-reduced-motion: no-preference) {
  .vp-flash {
    animation: vp-flash-in 250ms cubic-bezier(0.2, 0.8, 0.2, 1);
    transition: opacity 400ms ease, transform 400ms ease;
  }
  .vp-flash--dismissing {
    opacity: 0;
    transform: translateY(-8px);
  }
  @keyframes vp-flash-in {
    from { opacity: 0; transform: translateY(-8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
}
```

In `templates/base.html`, at the bottom of `<body>` (inside `{% block scripts %}`-equivalent, or directly):

```html
<script>
  document.querySelectorAll('.vp-flash:not(.vp-flash--danger)').forEach(el => {
    let dismissTimer = setTimeout(() => el.classList.add('vp-flash--dismissing'), 4000);
    let removeTimer = setTimeout(() => el.remove(), 4400);
    el.addEventListener('mouseenter', () => {
      clearTimeout(dismissTimer);
      clearTimeout(removeTimer);
    });
  });
</script>
```

Behavior:
- All flashes except `--danger` slide in, hold 4s, fade out.
- Hovering pauses dismissal (timer cleared; flash stays until page navigation).
- Danger flashes stay indefinitely.

### 2b. "Just synced" pulse

In `app.py`, modify `itinerary_resync` (and `itinerary_bulk_resync`):

```python
# Existing redirect:
return redirect(url_for("trip_itinerary", trip_id=trip.id))
# Becomes:
return redirect(url_for("trip_itinerary", trip_id=trip.id, just_synced=item.id))
```

**Bulk resync:** the bulk-resync POST redirects to the drift-review landing
page, not the itinerary. The landing page does not render itinerary chips, so
`?just_synced` would have no visible effect there. For MVP we **omit** the
param on bulk redirects and rely on the celebration flash (slice 2c) to confirm
the bulk action.

In `templates/trip_itinerary.html`, parse the param once:

```jinja
{% set just_synced_raw = request.args.get('just_synced', '') %}
{% set just_synced_ids = just_synced_raw.split(',') if just_synced_raw else [] %}
```

Inside the item chip render loop, on the chip's outer `<div>`:

```jinja
<div class="itin-chip {{ ... }}"
     {% if it.id|string in just_synced_ids %}data-just-synced="true"{% endif %}>
  ...
</div>
```

CSS:

```css
@media (prefers-reduced-motion: no-preference) {
  [data-just-synced] {
    animation: vp-pulse-success 1.2s ease-out 1;
  }
  @keyframes vp-pulse-success {
    0%   { background-color: rgba(214, 241, 227, 0.8); box-shadow: 0 0 0 0 rgba(22, 101, 52, 0.4); }
    60%  { background-color: rgba(214, 241, 227, 0.4); box-shadow: 0 0 0 12px rgba(22, 101, 52, 0); }
    100% { background-color: transparent; box-shadow: 0 0 0 0 rgba(22, 101, 52, 0); }
  }
}
```

The animation runs once on page load (one-shot via `1` iteration count) and
leaves the chip in its normal style.

**Wizard mid-flow:** the wizard's per-step resync redirects to the *next*
wizard step, not back to the itinerary. We do **not** pass `just_synced`
through those mid-wizard redirects — the next step is a fresh focus. Only the
*final* wizard-resync (when there's no next item, redirect goes back to the
landing page) and direct *detail-page* resyncs carry the param when their
redirect target is the itinerary page.

### 2c. "All in sync!" celebration flash

Modify `_apply_resync_to_item` in `app.py` to return a tuple:

```python
def _apply_resync_to_item(item, booking) -> Tuple[bool, bool]:
    """Resync `item` from `booking`. Returns (applied, was_last_drift_on_trip).

    `applied` is False when the booking no longer generates this auto_kind
    (orphaned slot). `was_last_drift_on_trip` is True when this resync
    just cleared the trip's final drifting item — caller uses this to
    pick the celebration flash variant.
    """
```

The function computes `was_last_drift_on_trip` after applying the resync by
re-running `detect_drift` over the trip's remaining linked items.

Call sites adapt:

```python
applied, was_last = _apply_resync_to_item(item, booking)
if not applied:
    flash("The booking no longer suggests this item.", "warning")
    return ...
if was_last:
    flash("Everything is in sync with your bookings ✓", "success-celebrate")
else:
    flash(f"Resynced “{item.title}”.", "success")
```

For the bulk-resync route, "was_last_drift" is computed once after the bulk
commit — if `detect_drift` returns None for every remaining linked item,
celebrate.

`templates/base.html` flash-category whitelist:

```python
{% if category in ['info', 'success', 'success-celebrate', 'warning', 'danger'] %}
```

CSS for the celebration variant:

```css
.vp-flash--success-celebrate {
  /* Same base styling as .vp-flash--success, plus a leading tick icon
     and slightly larger text. */
  background-color: #d6f1e3;
  color: #166534;
  border-color: #86efac;
  font-size: 1rem;
  font-weight: 600;
}
.vp-flash--success-celebrate::before {
  content: "✓";
  display: inline-block;
  margin-right: 0.5rem;
  color: #16a34a;
  font-weight: 700;
}
```

### Tests

- `test_resync_redirect_includes_just_synced_param` — POST to resync redirects with the expected query string.
- `test_resync_clears_last_drift_uses_celebration_flash` — when only one drifting item exists, resync triggers the `success-celebrate` category.
- `test_bulk_resync_clearing_all_uses_celebration_flash` — same for the bulk POST.
- `test_resync_with_remaining_drift_uses_regular_flash` — resync of 1 of 2 drifting items uses plain `success`.
- Manual smoke: verify pulse plays once, flash slides in and out, hover pauses dismissal.

### Edge cases

- `prefers-reduced-motion: reduce` → all keyframes skipped via media query. Flashes appear/disappear instantly; pulse never plays.
- User refreshes the page after resync → `?just_synced` stays in URL; pulse replays. Acceptable cosmetic cost.
- Multiple items in one `?just_synced=1,2,3` → all three get the attribute and pulse simultaneously.
- Bulk resync that clears 5 items but leaves 2 drifting → regular success flash, no celebration.

---

## Slice 3 — Keyboard shortcuts (wizard only)

### Bindings

| Key | Action | Element |
|---|---|---|
| `R` | Resync to booking | `<button id="resync-btn">` |
| `K` | Keep mine | `<button id="keep-btn">` |
| `U` | Unlink | `<button id="unlink-btn">` |
| `S` | Skip to next item | `<a id="skip-link">` |
| `Esc` | Back to itinerary | `<a id="back-link">` |

All single-key, case-insensitive, no modifiers. Disabled when typing in a form
input or when any modifier (Ctrl/Cmd/Alt) is held.

### Template changes

`templates/_drift_actions.html` — add `id` attributes unconditionally:

```jinja
<button id="resync-btn" class="btn btn-vp-primary" type="submit">...</button>
<button id="keep-btn" class="btn btn-outline-secondary" type="submit">Keep mine</button>
<button id="unlink-btn" class="btn btn-outline-secondary" type="submit">Unlink from booking</button>
```

The IDs are harmless on the drift detail page (no script there listens to
them).

`templates/drift_review_item.html` — add IDs and the hint row:

```jinja
{% if next_item %}
  <a id="skip-link" class="btn btn-outline-secondary" href="...">Skip →</a>
{% else %}
  <a id="skip-link" class="btn btn-outline-secondary" href="...">Skip → done</a>
{% endif %}

<a id="back-link" class="btn btn-link ms-auto" href="...">Back to itinerary</a>

<!-- After the action row, inside the vp-card: -->
<div class="vp-shortcut-hint mt-3 pt-2 border-top">
  <kbd>R</kbd> Resync
  <kbd>K</kbd> Keep mine
  <kbd>U</kbd> Unlink
  <kbd>S</kbd> Skip
  <kbd>Esc</kbd> Back
</div>

{% block scripts %}
<script>
  (function () {
    const map = { r: 'resync-btn', k: 'keep-btn', u: 'unlink-btn', s: 'skip-link' };
    document.addEventListener('keydown', (e) => {
      if (e.target.matches('input, textarea, select, [contenteditable]')) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        document.getElementById('back-link')?.click();
        return;
      }
      const id = map[e.key.toLowerCase()];
      if (!id) return;
      const el = document.getElementById(id);
      if (!el) return;
      e.preventDefault();
      el.click();  // works for both <button type=submit> and <a>
    });
  })();
</script>
{% endblock %}
```

### CSS

```css
.vp-shortcut-hint {
  font-size: 0.78rem;
  color: var(--vp-text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
}
.vp-shortcut-hint kbd {
  display: inline-block;
  min-width: 1.4em;
  padding: 0.1rem 0.35rem;
  margin-right: 0.25rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--vp-text);
  background-color: var(--vp-surface-2);
  border: 1px solid var(--vp-border);
  border-bottom-width: 2px;
  border-radius: 4px;
  line-height: 1;
}
```

### Tests

- `test_wizard_step_renders_shortcut_hint` — wizard step page contains "vp-shortcut-hint" class.
- `test_wizard_action_buttons_have_ids` — the page HTML contains `id="resync-btn"`, `id="keep-btn"`, `id="unlink-btn"`, `id="skip-link"`, `id="back-link"`.
- Manual smoke: load the wizard with drift present, press R/K/U/S/Esc; verify each navigates correctly.

### Edge cases

- User is typing in an inline edit field (none today, but the guard is there for future).
- `Ctrl+R` browser reload — only bare `R` triggers our handler; modifier is filtered.
- Screen-reader users — the hint row is real DOM text reachable via tab order; `<kbd>` is semantic.
- Touch users — keydown never fires; the hint row is small enough to ignore visually.

---

## Slice 4 — Drop the deprecated `customized_by_user` column

**Gated** as the final task in the implementation plan.

### Before running

The plan task starts with an explicit check-in step:

> **Confirm with Jeff that phase 3 has been in production use for at least one
> week with no rollback needed.** If unsure, stop and ask.

This is intentional: dropping a column is destructive. Phase 3's backfill
already preserved the data via `auto_fields_touched`, so the rollback path
exists (re-add the column declaration; phase-1's `ADD COLUMN` migration runs
again on next boot), but historical row-level values are lost.

### Changes

**`app.py`** — extend `_ensure_drift_columns` with one more guarded statement:

```python
statements = [
    "ALTER TABLE itinerary_item ADD COLUMN auto_kind VARCHAR(20)",
    "ALTER TABLE itinerary_item ADD COLUMN customized_by_user BOOLEAN NOT NULL DEFAULT 0",
    "ALTER TABLE itinerary_item ADD COLUMN auto_fields_touched VARCHAR(255) NOT NULL DEFAULT ''",
    # ... existing backfill UPDATE ...
    "ALTER TABLE itinerary_item DROP COLUMN customized_by_user",
]
```

The existing `try/except Exception` swallow pattern in the migration helper
already handles "column doesn't exist" idempotency, so a re-run on an
already-dropped DB is a no-op.

**`models.py`** — remove the column declaration and its deprecation comment:

```python
# DELETE this block:
#
# # DEPRECATED in phase 3: replaced by auto_fields_touched. No longer read
# # or written. Column left in place for one release before being dropped.
# customized_by_user = db.Column(db.Boolean, nullable=False, default=False)
```

No code changes elsewhere — phase 3 already eliminated all reads and writes.
Verified by `grep -r customized_by_user .` returning only the model
declaration + migration helper.

### Postgres / SQLite compatibility

- Postgres ≥ 9.6 supports `ALTER TABLE ... DROP COLUMN` natively.
- SQLite ≥ 3.35 (March 2021) supports `DROP COLUMN`. Older SQLite would error;
  the migration helper's `try/except` catches it and logs at debug level.

### Tests

- Existing test suite passes unchanged — phase 3 removed all references.
- New test: `test_migration_drops_customized_by_user_column` — boot the app
  against a fresh in-memory SQLite, run `PRAGMA table_info(itinerary_item)`,
  assert `customized_by_user` is absent.
- Manual: boot the app twice against a real DB; second boot logs the DROP as
  skipped without errors.

### Rollback path (documented, not implemented)

If a rollback is ever needed:

1. Re-add the column declaration to `models.py`.
2. Re-run `_ensure_drift_columns` (the `ADD COLUMN` line is still in the list
   and will recreate the column with default `False`).
3. Historical `customized_by_user=True` values are gone — but phase 3's
   backfill translated those to `auto_fields_touched`, which persists.

---

## Open questions

None — all major decisions settled via brainstorming. Tactical choices below
are confirmed:

- Dashboard pills: differentiated drift vs new-items (not unified count).
- Animation set: animated flash + just-synced pulse + all-in-sync celebration.
  Wizard-mid-flow does not pulse.
- Keyboard scope: wizard step only.
- Discoverability: visible hint row (no `?` overlay).
- Column drop: gated final task; safety check-in before running.
- No new dependencies (no htmx, no Alpine, no animation library).

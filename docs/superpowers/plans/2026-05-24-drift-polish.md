# Drift Polish — Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the four polish items from the phase-4 spec — dashboard tile pills, animated resync feedback, wizard keyboard shortcuts, and a gated `customized_by_user` column drop — so the drift detection feature feels finished.

**Architecture:** Four independent slices, no shared abstractions. Slice 1 adds one private helper in `app.py` and a new pill row on the dashboard trip card. Slice 2 is pure CSS plus ~15 lines of JS in `base.html` for animated flashes, a `?just_synced=<id>` URL-param pulse on the resynced item, and a `success-celebrate` flash category for the "all in sync" moment. Slice 3 wires single-key shortcuts into the wizard step with a visible hint row. Slice 4 — gated behind an explicit user check-in — drops the deprecated `customized_by_user` column.

**Tech Stack:** Python 3.9, Flask, Flask-SQLAlchemy, Jinja2, Bootstrap 5, vanilla JS, pytest. No new dependencies.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `app.py` | Modify | Add `_drift_counts_for_trips`; wire into `trips_list`; change `_apply_resync_to_item` to return `(applied, was_last_drift)`; update its three call sites for celebration flash + `?just_synced` redirect param; add the gated `DROP COLUMN` statement to `_ensure_drift_columns`. |
| `models.py` | Modify | Remove the `customized_by_user` column declaration (gated, last task). |
| `templates/_trip_card.html` | Modify | Render two pill row when `counts.get(trip.id, (0,0))` is non-zero. |
| `templates/trips_list.html` | Modify | Pass `counts` into the `trip_card` macro at every invocation site. |
| `templates/trip_itinerary.html` | Modify | Read `?just_synced` from `request.args` and stamp `data-just-synced` on matching item(s). |
| `templates/_drift_actions.html` | Modify | Add unconditional `id` attributes on the Resync / Keep / Unlink buttons. |
| `templates/drift_review_item.html` | Modify | Add `id` on Skip + Back links; add the keyboard-shortcut hint row; add inline `{% block scripts %}` keydown handler. |
| `templates/base.html` | Modify | Extend the flash category whitelist to include `success-celebrate`; add the auto-dismiss JS block. |
| `static/css/app.css` | Modify | Trip card pill styles; `.vp-flash` slide-in keyframe + dismissing transition; `.vp-flash--success-celebrate` variant; `[data-just-synced]` pulse keyframe; `.vp-shortcut-hint` + `kbd` styling. All animations gated by `prefers-reduced-motion: no-preference`. |
| `tests/test_routes.py` | Modify | Integration tests for: dashboard renders pills when drift exists / skips completed trips; resync redirect includes `?just_synced=<id>`; flash category is `success-celebrate` when last drift clears; wizard renders hint row + action IDs; column drop is idempotent (after slice 4). |

---

## Task 1: `_drift_counts_for_trips` helper (TDD via the dashboard route)

The new helper batches a `(drift_count, new_items_count)` lookup for every trip on the dashboard. The cheapest way to drive its design is from the route test — we'll wire the helper in Task 2, so Task 1 is "write the function, prove it works in isolation."

**Files:**
- Modify: `app.py` (add helper near `_annotate_drift_for_items` ~ line 860)
- Modify: `tests/test_routes.py` (append three new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
# ─── Dashboard drift counts ─────────────────────────────────────────

def test_drift_counts_empty_when_no_trips(app, owner):
    """No trips → helper returns an empty dict."""
    from app import _drift_counts_for_trips
    assert _drift_counts_for_trips([]) == {}


def test_drift_counts_includes_drifting_trip(app, trip):
    """A trip with one drifting linked item shows (1, 0)."""
    from app import _drift_counts_for_trips
    _make_flight_with_arrive(trip)  # 1 drifting item, no new slots missing
    counts = _drift_counts_for_trips([trip])
    assert counts == {trip.id: (1, 0)}


def test_drift_counts_skips_completed_trip(app, owner):
    """status='completed' trip is omitted from the result dict."""
    from app import _drift_counts_for_trips
    t = Trip(owner_id=owner.id, name="Done trip",
             start_date=date(2026, 1, 1), end_date=date(2026, 1, 7),
             status="completed")
    db.session.add(t)
    db.session.commit()
    _make_flight_with_arrive(t)  # would drift, but trip is completed
    counts = _drift_counts_for_trips([t])
    assert counts == {}


def test_drift_counts_skips_past_trip(app, owner):
    """A trip whose end_date is before today is omitted."""
    from app import _drift_counts_for_trips
    t = Trip(owner_id=owner.id, name="Past trip",
             start_date=date(2020, 1, 1), end_date=date(2020, 1, 7))
    db.session.add(t)
    db.session.commit()
    _make_flight_with_arrive(t)
    counts = _drift_counts_for_trips([t])
    assert counts == {}


def test_drift_counts_includes_new_items_only_trip(app, trip):
    """A trip with no drift but a missing auto-slot shows (0, 1)."""
    from app import _drift_counts_for_trips
    # Flight booking with both datetimes, but only the 'depart' item exists —
    # 'arrive' is the missing auto-slot.
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1), title="Depart United", category="transit",
    ))
    db.session.commit()
    counts = _drift_counts_for_trips([trip])
    assert counts == {trip.id: (0, 1)}
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run:

```bash
.venv/bin/pytest tests/test_routes.py -k drift_counts -v
```

Expected: all 5 tests FAIL with `ImportError: cannot import name '_drift_counts_for_trips'`.

- [ ] **Step 3: Add the helper to `app.py`**

In `app.py`, just below `_annotate_drift_for_items` (around line 887, after the closing `return drift_count` line and before `def _annotate_new_items_for_trip`), insert:

```python
def _drift_counts_for_trips(trips) -> Dict[int, Tuple[int, int]]:
    """For each trip, return (drift_count, new_items_count).

    Batched: two queries cover all relevant bookings and itinerary items,
    then in-memory grouping. Skips trips whose status is 'completed' or
    whose end_date is before today (drift on a finished trip isn't
    actionable).

    Returns a dict keyed by trip.id. Trips not in the result dict
    implicitly have (0, 0). Used by the dashboard to render per-trip
    pills.
    """
    today = date.today()
    active = [
        t for t in trips
        if t.status != "completed" and t.end_date >= today
    ]
    if not active:
        return {}
    trip_ids = [t.id for t in active]

    bookings = Booking.query.filter(Booking.trip_id.in_(trip_ids)).all()
    items = ItineraryItem.query.filter(
        ItineraryItem.trip_id.in_(trip_ids)
    ).all()

    bookings_by_trip: Dict[int, list] = {}
    bookings_by_id: Dict[int, Any] = {}
    for b in bookings:
        bookings_by_trip.setdefault(b.trip_id, []).append(b)
        bookings_by_id[b.id] = b

    items_by_trip: Dict[int, list] = {}
    existing_kinds_by_booking: Dict[int, set] = {}
    for it in items:
        items_by_trip.setdefault(it.trip_id, []).append(it)
        if it.linked_booking_id and it.auto_kind:
            existing_kinds_by_booking.setdefault(
                it.linked_booking_id, set()
            ).add(it.auto_kind)

    out: Dict[int, Tuple[int, int]] = {}
    for t in active:
        drift = 0
        for it in items_by_trip.get(t.id, []):
            if not it.linked_booking_id:
                continue
            booking = bookings_by_id.get(it.linked_booking_id)
            if booking is None:
                continue
            if detect_drift(it, booking) is not None:
                drift += 1

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

You also need to make sure these names are already in scope at the top of `app.py`:

- `Dict`, `Tuple`, `Any` from `typing` — check the existing `from typing import ...` line and add any missing.
- `date` from `datetime` — already imported (used elsewhere).
- `Booking`, `ItineraryItem` — already imported from `models`.
- `detect_drift`, `missing_auto_kinds_for_booking` — already imported from `src.booking_helpers`.

To verify, run:

```bash
.venv/bin/python -c "from app import _drift_counts_for_trips; print('import ok')"
```

Expected: `import ok`. If you get `NameError`, add the missing typing import.

- [ ] **Step 4: Run the tests**

Run:

```bash
.venv/bin/pytest tests/test_routes.py -k drift_counts -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Run the full test suite to catch regressions**

Run:

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: _drift_counts_for_trips batches per-trip drift+new-item counts"
```

---

## Task 2: Wire the dashboard pills

Call the helper from `trips_list`, pass the result through the `trip_card` macro, render two pills when either count is non-zero, and style them.

**Files:**
- Modify: `app.py` (the `trips_list` function around line 510)
- Modify: `templates/trips_list.html`
- Modify: `templates/_trip_card.html`
- Modify: `static/css/app.css`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/test_routes.py`:

```python
def test_dashboard_renders_drift_pill(app, trip, owner):
    """A drifting trip shows the amber drift pill on the dashboard."""
    _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert resp.status_code == 200
    assert b"trip-card-pill--drift" in resp.data
    assert b"1 out of sync" in resp.data


def test_dashboard_renders_new_pill(app, trip, owner):
    """A trip with a missing auto-slot shows the blue 'suggested' pill."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1), title="Depart United", category="transit",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert b"trip-card-pill--new" in resp.data
    assert b"1 suggested" in resp.data


def test_dashboard_no_pills_when_clean(app, trip, owner):
    """A trip with no drift and no new items renders no status row."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert b"trip-card-pill" not in resp.data
    assert b"trip-card-status-row" not in resp.data
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run:

```bash
.venv/bin/pytest tests/test_routes.py -k "dashboard_renders or dashboard_no_pills" -v
```

Expected: the first two FAIL (markup not rendered yet). The third PASSES already because nothing renders the row.

- [ ] **Step 3: Update `trips_list` to pass counts**

In `app.py`, find `trips_list` (around line 510) and change the return statement. The current body ends with:

```python
    grouped = group_trips_by_state(trips, today)
    has_any = any(grouped.values())
    return render_template(
        "trips_list.html",
        grouped=grouped,
        has_any_trips=has_any,
        today=today,
    )
```

Change it to:

```python
    grouped = group_trips_by_state(trips, today)
    has_any = any(grouped.values())
    counts = _drift_counts_for_trips(trips)
    return render_template(
        "trips_list.html",
        grouped=grouped,
        has_any_trips=has_any,
        today=today,
        counts=counts,
    )
```

- [ ] **Step 4: Update `templates/trips_list.html` to pass counts through to the macro**

In `templates/trips_list.html`, change every `{{ trip_card(t, today) }}` invocation to `{{ trip_card(t, today, counts) }}`. There are three of them (active, upcoming, past sections).

The full body of each section's loop becomes:

```jinja
{% for t in grouped.active %}
  <div class="col-md-6 col-lg-4">{{ trip_card(t, today, counts) }}</div>
{% endfor %}
```

…repeated for `grouped.upcoming` and `grouped.past`.

- [ ] **Step 5: Update `_trip_card.html` to accept and render the pills**

Replace the entire content of `templates/_trip_card.html` with:

```jinja
{# Reusable trip card for the dashboard.
   `today` is a date passed in from the route so we don't recompute it per card.
   `counts` is the {trip_id: (drift_count, new_count)} dict from _drift_counts_for_trips. #}
{% macro trip_card(trip, today, counts=None) %}
  {% set status = derive_status(trip.start_date, trip.end_date, today) %}
  {% set countdown = countdown_label(trip.start_date, trip.end_date, today) %}
  {% set countdown_cls = ('is-active' if status == 'in_progress' else ('is-past' if status == 'completed' else '')) %}
  <a class="trip-card" href="{{ url_for('trip_overview', trip_id=trip.id) }}">
    <div class="trip-card-emoji" aria-hidden="true">{{ trip.cover_emoji or '🧳' }}</div>
    <div class="trip-card-name">{{ trip.name }}</div>
    {% if trip.destination %}
      <div class="trip-card-destination">{{ trip.destination }}</div>
    {% endif %}
    <div class="trip-card-dates">
      {{ trip.start_date.strftime('%b %d') }} – {{ trip.end_date.strftime('%b %d, %Y') }}
    </div>
    {% if current_user.is_authenticated and trip.owner_id != current_user.id %}
      <div class="trip-card-shared-by">
        Shared by {{ trip.owner.name or trip.owner.email }}
      </div>
    {% endif %}
    <span class="trip-card-countdown {{ countdown_cls }}">{{ countdown }}</span>
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
  </a>
{% endmacro %}
```

- [ ] **Step 6: Add the pill styles to `static/css/app.css`**

Find the trip-card block (around line 150–204). Just after the `.trip-card-countdown.is-past { ... }` rule (around line 204), insert:

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

- [ ] **Step 7: Run the integration tests**

Run:

```bash
.venv/bin/pytest tests/test_routes.py -k "dashboard_renders or dashboard_no_pills" -v
```

Expected: all 3 tests PASS.

- [ ] **Step 8: Smoke-test in the browser**

Boot the server:

```bash
.venv/bin/python app.py
```

Force drift on a trip by mutating a flight booking's vendor in the DB (same trick as phase 1):

```bash
.venv/bin/python -c "
from app import app
from models import Booking, db
with app.app_context():
    b = Booking.query.filter_by(type='flight').first()
    if b:
        b.vendor = 'TEST DRIFT'
        db.session.commit()
        print(f'Mutated booking id={b.id}')
"
```

Visit `http://localhost:5002/trips`. Confirm the trip with the mutated booking shows the amber "N out of sync" pill below the countdown. Revert the mutation when you're done:

```bash
.venv/bin/python -c "
from app import app
from models import Booking, db
with app.app_context():
    b = Booking.query.filter_by(vendor='TEST DRIFT').first()
    if b:
        b.vendor = 'United'  # or whatever it was
        db.session.commit()
"
```

Stop the server.

- [ ] **Step 9: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add app.py templates/trips_list.html templates/_trip_card.html static/css/app.css tests/test_routes.py
git commit -m "feat: dashboard trip cards show drift and new-item counts"
```

---

## Task 3: Animated flash messages (global, CSS + small JS)

The existing `.vp-flash` block gets a slide-in keyframe and an auto-dismiss timer. Hover pauses the timer. Danger flashes are exempt.

**Files:**
- Modify: `static/css/app.css`
- Modify: `templates/base.html`

This is a visual change with no logic to test in pytest — manual smoke is the verification.

- [ ] **Step 1: Add the keyframe + dismissing class CSS**

In `static/css/app.css`, find the `.vp-flash` rule (around line 271). Just after the existing `.vp-flash--danger` rule (around line 280), insert:

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

- [ ] **Step 2: Add the auto-dismiss JS to `base.html`**

In `templates/base.html`, find the existing `<script src="...bootstrap...">` line near the bottom (around line 72). Just after that line and before `{% block scripts %}{% endblock %}`, add:

```html
  <script>
    // Auto-dismiss non-danger flash messages after 4 seconds.
    // Hovering pauses dismissal so the user can read at their pace.
    document.querySelectorAll('.vp-flash:not(.vp-flash--danger)').forEach(function (el) {
      var dismissTimer = setTimeout(function () {
        el.classList.add('vp-flash--dismissing');
      }, 4000);
      var removeTimer = setTimeout(function () {
        el.remove();
      }, 4400);
      el.addEventListener('mouseenter', function () {
        clearTimeout(dismissTimer);
        clearTimeout(removeTimer);
      });
    });
  </script>
```

- [ ] **Step 3: Smoke-test in the browser**

Boot the server:

```bash
.venv/bin/python app.py
```

Log in, perform any action that triggers a success flash (e.g. add a booking, edit an itinerary item). Confirm:
- The flash slides in from above (subtle translateY animation).
- After ~4 seconds it fades out and disappears.
- Hovering over the flash pauses the dismissal — once you mouse away, it does NOT resume (the timers are cleared, not paused; this is intentional simplicity).
- A flash with category `danger` (force one by triggering a real error, e.g. trying to access another user's trip) stays indefinitely.

If `prefers-reduced-motion: reduce` is set in your OS, the flash should appear instantly with no animation, but the auto-dismiss still works (the JS doesn't check for the media query — only the CSS animations are gated).

Stop the server.

- [ ] **Step 4: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass. No tests depend on flash DOM timing.

- [ ] **Step 5: Commit**

```bash
git add static/css/app.css templates/base.html
git commit -m "feat: animated flash messages with auto-dismiss"
```

---

## Task 4: `_apply_resync_to_item` returns `(applied, was_last_drift)` + celebration flash

To know whether a resync just cleared the *last* drift on a trip, we re-check `detect_drift` against the trip's remaining linked items after the resync runs. The helper changes shape; its three call sites (per-item route, wizard route via shared helper, bulk route) update accordingly. The new `success-celebrate` flash category gets a style and a whitelist entry.

**Files:**
- Modify: `app.py` (the `_apply_resync_to_item` function and its callers)
- Modify: `templates/base.html` (flash category whitelist)
- Modify: `static/css/app.css` (celebration variant)
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
# ─── Celebration flash ─────────────────────────────────────────────

def test_resync_last_drift_uses_celebration_flash(app, trip, owner):
    """When a resync clears the only drifting item, flash category is
    success-celebrate."""
    _, item = _make_flight_with_arrive(trip)  # exactly 1 drifting item
    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
        # Follow redirect to inspect the rendered flash.
        resp = client.get(f"/trips/{trip.id}/itinerary")
    assert b"vp-flash--success-celebrate" in resp.data
    assert b"Everything is in sync" in resp.data


def test_resync_with_remaining_drift_uses_regular_flash(app, trip, owner):
    """When other drift remains after a resync, use the regular success flash."""
    _, item1 = _make_flight_with_arrive(trip)
    # A second drifting item on a different booking.
    b2 = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                 start_datetime=datetime(2026, 6, 2, 15, 0),
                 end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b2)
    db.session.commit()
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b2.id, auto_kind="check_in",
        day_date=date(2026, 6, 2), title="STALE TITLE", category="other",
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/{item1.id}/resync")
        resp = client.get(f"/trips/{trip.id}/itinerary")
    assert b"vp-flash--success-celebrate" not in resp.data
    # Plain success flash should still appear.
    assert b"vp-flash--success" in resp.data


def test_bulk_resync_clearing_all_uses_celebration_flash(app, trip, owner):
    """Bulk resync that clears all drift uses the celebration flash."""
    _, _ = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/drift-review/bulk-resync")
        resp = client.get(f"/trips/{trip.id}/itinerary")
    assert b"vp-flash--success-celebrate" in resp.data
```

- [ ] **Step 2: Run them to confirm failure**

```bash
.venv/bin/pytest tests/test_routes.py -k "celebration_flash or remaining_drift_uses_regular" -v
```

Expected: 3 tests FAIL — no celebration flash category exists yet.

- [ ] **Step 3: Update `_apply_resync_to_item` signature**

In `app.py`, find `_apply_resync_to_item` (around line 1208). Replace its entire definition with:

```python
def _apply_resync_to_item(item, booking) -> Tuple[bool, bool]:
    """Apply the booking's auto-generated values to one item.

    Only overwrites fields that the user hasn't personally touched
    (auto_fields_touched). The touched set itself is preserved, so a
    user who touched `title` will continue to keep their title across
    future resyncs — by design, per the phase-3 spec.

    Returns:
        (applied, was_last_drift_on_trip)

        applied is True when the item was updated, False when the
        booking no longer generates an item of this auto_kind
        (orphaned slot — caller should suggest Unlink/Delete).

        was_last_drift_on_trip is True when, after this resync, no
        remaining drifting items exist on the trip. Caller uses this
        to pick the celebration flash variant. False when applied is
        False.

    Caller is responsible for committing the session before reading
    was_last_drift_on_trip, because the check re-runs detect_drift
    over freshly-mutated state.
    """
    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == item.auto_kind]
    if not matches:
        return (False, False)
    would_be = matches[0]
    touched = parse_touched(item.auto_fields_touched)
    for f in DRIFT_FIELDS:
        if f in touched:
            continue
        setattr(item, f, would_be.get(f))
    # auto_fields_touched preserved intentionally.

    # Compute was_last_drift on the trip by checking every other linked
    # item against its booking. The item we just resynced is included —
    # detect_drift on it will return None now, so it doesn't count.
    remaining = ItineraryItem.query.filter_by(trip_id=item.trip_id).all()
    booking_ids = {it.linked_booking_id for it in remaining if it.linked_booking_id}
    bookings_by_id = {
        b.id: b for b in Booking.query.filter(Booking.id.in_(booking_ids)).all()
    } if booking_ids else {}
    was_last = True
    for it in remaining:
        if not it.linked_booking_id:
            continue
        b = bookings_by_id.get(it.linked_booking_id)
        if b is None:
            continue
        # We haven't committed yet — `item` already has its new values via
        # setattr above, so detect_drift on it will see in-sync state.
        if detect_drift(it, b) is not None:
            was_last = False
            break
    return (True, was_last)
```

Note: this function now does extra DB work per call. For the bulk-resync path that calls it in a loop, we re-derive `was_last` once at the end of the loop instead of trusting individual calls — see Step 5.

- [ ] **Step 4: Update `itinerary_resync` to use the tuple and emit `success-celebrate`**

In `app.py`, find `itinerary_resync` (around line 1264). Replace the block:

```python
    if not _apply_resync_to_item(item, booking):
        flash(
            "The booking no longer suggests this item. Use Unlink or Delete.",
            "warning",
        )
        return redirect(url_for("trip_itinerary", trip_id=trip.id))
    db.session.commit()
    logger.info("Resynced itinerary item id=%s from booking id=%s",
                item.id, booking.id)
    flash(f"Resynced “{item.title}” to the booking.", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

with:

```python
    applied, was_last = _apply_resync_to_item(item, booking)
    if not applied:
        flash(
            "The booking no longer suggests this item. Use Unlink or Delete.",
            "warning",
        )
        return redirect(url_for("trip_itinerary", trip_id=trip.id))
    db.session.commit()
    logger.info("Resynced itinerary item id=%s from booking id=%s",
                item.id, booking.id)
    if was_last:
        flash("Everything is in sync with your bookings ✓", "success-celebrate")
    else:
        flash(f"Resynced “{item.title}” to the booking.", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

- [ ] **Step 5: Update `itinerary_drift_review_bulk_resync` to use the tuple and emit celebration**

In `app.py`, find `itinerary_drift_review_bulk_resync` (around line 1132). Replace the POST handling block:

```python
    if request.method == "POST":
        # Re-fetch each item's booking (avoid trusting stale objects),
        # then apply resync. Single commit covers all items.
        updated = 0
        for it in eligible:
            booking = db.session.get(Booking, it.linked_booking_id)
            if booking is None:
                continue
            if _apply_resync_to_item(it, booking):
                updated += 1
        db.session.commit()
        logger.info("Bulk-resynced %d itinerary items for trip_id=%s",
                    updated, trip.id)
        flash(
            f"Resynced {updated} item{'' if updated == 1 else 's'} to "
            f"{'its' if updated == 1 else 'their'} booking"
            f"{'' if updated == 1 else 's'}.",
            "success",
        )
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))
```

with:

```python
    if request.method == "POST":
        # Re-fetch each item's booking (avoid trusting stale objects),
        # then apply resync. Single commit covers all items. We ignore
        # the per-call was_last flag — see below for the trip-level check.
        updated = 0
        for it in eligible:
            booking = db.session.get(Booking, it.linked_booking_id)
            if booking is None:
                continue
            applied, _ = _apply_resync_to_item(it, booking)
            if applied:
                updated += 1
        db.session.commit()
        logger.info("Bulk-resynced %d itinerary items for trip_id=%s",
                    updated, trip.id)

        # After the bulk commit, recompute whether any drift remains
        # on the trip. If not, use the celebration flash.
        remaining_items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
        any_drift_left = _annotate_drift_for_items(remaining_items) > 0
        if updated > 0 and not any_drift_left:
            flash("Everything is in sync with your bookings ✓", "success-celebrate")
        else:
            flash(
                f"Resynced {updated} item{'' if updated == 1 else 's'} to "
                f"{'its' if updated == 1 else 'their'} booking"
                f"{'' if updated == 1 else 's'}.",
                "success",
            )
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))
```

- [ ] **Step 6: Add `success-celebrate` to the base.html flash whitelist**

In `templates/base.html`, find this line (around line 62):

```jinja
<div class="vp-flash vp-flash--{{ category if category in ['info','success','warning','danger'] else 'info' }}">
```

Change the category list to include `success-celebrate`:

```jinja
<div class="vp-flash vp-flash--{{ category if category in ['info','success','success-celebrate','warning','danger'] else 'info' }}">
```

- [ ] **Step 7: Add the celebration flash CSS variant**

In `static/css/app.css`, find the existing flash variants (around lines 277–280):

```css
.vp-flash--info    { background: var(--vp-accent-soft); color: var(--vp-accent); }
.vp-flash--success { background: #d6f1e3;             color: var(--vp-success); }
.vp-flash--warning { background: #fbeec7;             color: var(--vp-warning); }
.vp-flash--danger  { background: #f7d8d2;             color: var(--vp-danger); }
```

Just after the `.vp-flash--danger` line, insert:

```css
.vp-flash--success-celebrate {
  background: #d6f1e3;
  color: var(--vp-success);
  font-size: 1rem;
  font-weight: 600;
  border: 1px solid #86efac;
}
.vp-flash--success-celebrate::before {
  content: "✓";
  display: inline-block;
  margin-right: 0.5rem;
  color: #16a34a;
  font-weight: 700;
}
```

Also update the auto-dismiss JS selector in `base.html` (from Task 3) so the celebration flash does dismiss too — `:not(.vp-flash--danger)` already includes it, so no change is needed. Verify by re-reading the script you added; if you used a more restrictive selector, broaden it.

- [ ] **Step 8: Run the integration tests**

```bash
.venv/bin/pytest tests/test_routes.py -k "celebration_flash or remaining_drift_uses_regular" -v
```

Expected: all 3 PASS.

- [ ] **Step 9: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass. In particular, the existing resync tests should still pass — `_apply_resync_to_item` returns a tuple now, but the calling code is the only place that unpacks it, and the resync's *behavior* (which fields it overwrites) hasn't changed.

If you see failures like `TypeError: cannot unpack non-iterable bool object` — there's another caller of `_apply_resync_to_item` you missed. Search:

```bash
grep -n "_apply_resync_to_item" app.py
```

…and update each call site to unpack the tuple.

- [ ] **Step 10: Smoke-test in the browser**

Boot the server. Force exactly one drifting item on a trip (mutate a booking via the DB trick). Visit the itinerary, click Review drift → click into the wizard or detail page → click Resync. Confirm:
- The redirect lands on the itinerary page.
- The flash reads "Everything is in sync with your bookings ✓" with the larger font and green tick.
- The flash auto-dismisses after ~4 seconds (carried over from Task 3).

Now force two drifting items, resync only one — the flash should be the plain "Resynced …" message, not the celebration.

Stop the server.

- [ ] **Step 11: Commit**

```bash
git add app.py templates/base.html static/css/app.css tests/test_routes.py
git commit -m "feat: celebration flash when a resync clears the last drift"
```

---

## Task 5: `?just_synced` URL param + pulse animation on the resynced item

After a successful per-item resync, the redirect carries `?just_synced=<item_id>`. The itinerary template stamps `data-just-synced="true"` on the matching chip, and CSS runs a one-time success pulse.

**Files:**
- Modify: `app.py` (the `itinerary_resync` redirect)
- Modify: `templates/trip_itinerary.html`
- Modify: `static/css/app.css`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes.py`:

```python
def test_resync_redirect_includes_just_synced_param(app, trip, owner):
    """The redirect URL after a successful resync carries ?just_synced=<id>."""
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    assert f"just_synced={item.id}" in resp.headers["Location"]


def test_just_synced_param_stamps_data_attribute(app, trip, owner):
    """The itinerary page renders data-just-synced='true' on the matching chip."""
    _, item = _make_flight_with_arrive(trip)
    # Resync changes the item's title back to "Arrive United" so the chip
    # exists; we then visit with the query param.
    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
        resp = client.get(f"/trips/{trip.id}/itinerary?just_synced={item.id}")
    assert resp.status_code == 200
    assert b'data-just-synced="true"' in resp.data
```

- [ ] **Step 2: Run them to confirm failure**

```bash
.venv/bin/pytest tests/test_routes.py -k "just_synced" -v
```

Expected: both FAIL.

- [ ] **Step 3: Update `itinerary_resync` to add the redirect param**

In `app.py`, find the resync route's *non-wizard* return statement (the last `return redirect(url_for("trip_itinerary", trip_id=trip.id))` in `itinerary_resync`, around line 1293). Change it to:

```python
    return redirect(url_for("trip_itinerary", trip_id=trip.id, just_synced=item.id))
```

The wizard-flow redirect (`return _redirect_after_wizard_action(...)`) stays unchanged. Per the spec, mid-wizard transitions do not pulse.

- [ ] **Step 4: Update `trip_itinerary.html` to stamp the attribute**

In `templates/trip_itinerary.html`, find the chip-rendering block (around line 70–117). At the top of the template body, just after the breadcrumb `<div>` (around line 10) and before the `{% if drift_count > 0 ... %}` banner, add:

```jinja
{% set just_synced_raw = request.args.get('just_synced', '') %}
{% set just_synced_ids = just_synced_raw.split(',') if just_synced_raw else [] %}
```

Then find the `<div class="itin-chip ...">` opening tag (around line 71):

```jinja
<div class="itin-chip {{ category_css(it.category) }}">
```

Replace it with:

```jinja
<div class="itin-chip {{ category_css(it.category) }}"
     {% if it.id|string in just_synced_ids %}data-just-synced="true"{% endif %}>
```

- [ ] **Step 5: Add the pulse keyframe to `static/css/app.css`**

In `static/css/app.css`, after the `@media (prefers-reduced-motion: no-preference) { ... }` block you added in Task 3, add a second `@media (prefers-reduced-motion: no-preference)` block (Yes, two blocks is fine — keeps each animation block self-contained and easy to read):

```css
@media (prefers-reduced-motion: no-preference) {
  [data-just-synced] {
    animation: vp-pulse-success 1.2s ease-out 1;
  }
  @keyframes vp-pulse-success {
    0%   {
      background-color: rgba(214, 241, 227, 0.8);
      box-shadow: 0 0 0 0 rgba(22, 101, 52, 0.4);
    }
    60%  {
      background-color: rgba(214, 241, 227, 0.4);
      box-shadow: 0 0 0 12px rgba(22, 101, 52, 0);
    }
    100% {
      background-color: transparent;
      box-shadow: 0 0 0 0 rgba(22, 101, 52, 0);
    }
  }
}
```

Place this block just after the `.vp-flash`-related `@media` block (around the new lines you added in Task 3, ~line 281-296).

- [ ] **Step 6: Run the new tests**

```bash
.venv/bin/pytest tests/test_routes.py -k "just_synced" -v
```

Expected: both PASS.

- [ ] **Step 7: Smoke-test in the browser**

Boot the server. Force drift on one item, resync it via the detail page. After the redirect, confirm:
- The URL contains `?just_synced=<id>`.
- The chip for the just-resynced item briefly glows green (background ramps up then fades).
- A second item that wasn't resynced does NOT pulse.

If `prefers-reduced-motion: reduce` is set in your OS, the chip should appear normally with no pulse.

Stop the server.

- [ ] **Step 8: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add app.py templates/trip_itinerary.html static/css/app.css tests/test_routes.py
git commit -m "feat: pulse the just-resynced itinerary chip after redirect"
```

---

## Task 6: Add IDs to the wizard action buttons

Three buttons (Resync / Keep / Unlink) live in `_drift_actions.html`. Two links (Skip / Back) live in `drift_review_item.html`. Adding stable IDs to each is a prerequisite for the keyboard handler in Task 7. The IDs are harmless on the drift detail page (no listener there).

**Files:**
- Modify: `templates/_drift_actions.html`
- Modify: `templates/drift_review_item.html`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes.py`:

```python
def test_wizard_step_has_action_ids(app, trip, owner):
    """The wizard step renders id attributes on each action element."""
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/{item.id}"
        )
    assert resp.status_code == 200
    assert b'id="resync-btn"' in resp.data
    assert b'id="keep-btn"' in resp.data
    assert b'id="unlink-btn"' in resp.data
    assert b'id="skip-link"' in resp.data
    assert b'id="back-link"' in resp.data
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/test_routes.py::test_wizard_step_has_action_ids -v
```

Expected: FAIL — the IDs don't exist yet.

- [ ] **Step 3: Update `_drift_actions.html` with button IDs**

Replace the entire content of `templates/_drift_actions.html` with:

```jinja
{# Renders the Resync / Keep mine / Unlink form buttons for one item.
   Expects: trip, item, drift (or None), user_role.
   Optional: from_wizard (truthy → adds ?from=wizard to action URLs so
   the route redirects to the next drifting wizard step).
   The id="..." attrs let the wizard's keyboard handler find each
   button by key. They're harmless on the drift detail page. #}
{% if can_edit(user_role) %}
  {% set qs = {'from': 'wizard'} if from_wizard else {} %}
  <div class="d-flex gap-2 flex-wrap">
    {% if drift is not none and not drift.is_orphaned %}
      <form method="post"
            action="{{ url_for('itinerary_resync', trip_id=trip.id, item_id=item.id, **qs) }}"
            class="m-0">
        <button id="resync-btn" class="btn btn-vp-primary" type="submit">
          <i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>
          Resync to booking
        </button>
      </form>
      <form method="post"
            action="{{ url_for('itinerary_keep_mine', trip_id=trip.id, item_id=item.id, **qs) }}"
            class="m-0">
        <button id="keep-btn" class="btn btn-outline-secondary" type="submit">Keep mine</button>
      </form>
    {% endif %}
    <form method="post"
          action="{{ url_for('itinerary_unlink', trip_id=trip.id, item_id=item.id, **qs) }}"
          class="m-0">
      <button id="unlink-btn" class="btn btn-outline-secondary" type="submit">Unlink from booking</button>
    </form>
  </div>
{% endif %}
```

(The only difference from the existing partial: `id="resync-btn"`, `id="keep-btn"`, `id="unlink-btn"` added on the three `<button>` tags.)

- [ ] **Step 4: Update `drift_review_item.html` Skip + Back links with IDs**

In `templates/drift_review_item.html`, find the action row (around lines 43–60). Change each Skip-link variant and the Back link.

Find:

```jinja
    {% if next_item %}
      <a class="btn btn-outline-secondary"
         href="{{ url_for('itinerary_drift_review_item', trip_id=trip.id, item_id=next_item.id) }}">
        Skip →
      </a>
    {% else %}
      <a class="btn btn-outline-secondary"
         href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">
        Skip → done
      </a>
    {% endif %}
    <a class="btn btn-link ms-auto" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">
      Back to itinerary
    </a>
```

Replace with:

```jinja
    {% if next_item %}
      <a id="skip-link" class="btn btn-outline-secondary"
         href="{{ url_for('itinerary_drift_review_item', trip_id=trip.id, item_id=next_item.id) }}">
        Skip →
      </a>
    {% else %}
      <a id="skip-link" class="btn btn-outline-secondary"
         href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">
        Skip → done
      </a>
    {% endif %}
    <a id="back-link" class="btn btn-link ms-auto" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">
      Back to itinerary
    </a>
```

- [ ] **Step 5: Run the test**

```bash
.venv/bin/pytest tests/test_routes.py::test_wizard_step_has_action_ids -v
```

Expected: PASS.

- [ ] **Step 6: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass. The IDs are additive markup — no behaviour change for the drift detail page either.

- [ ] **Step 7: Commit**

```bash
git add templates/_drift_actions.html templates/drift_review_item.html tests/test_routes.py
git commit -m "feat: id attributes on wizard action buttons and links"
```

---

## Task 7: Wizard keyboard shortcuts (hint row + JS handler)

Single-key shortcuts: `R K U S` map to the four actions, `Esc` to Back. A visible hint row at the bottom of the wizard step lists the bindings. Inline JS in a `{% block scripts %}` block on the wizard template — scoped to that page only.

**Files:**
- Modify: `templates/drift_review_item.html`
- Modify: `static/css/app.css`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes.py`:

```python
def test_wizard_step_has_shortcut_hint(app, trip, owner):
    """The wizard step renders the keyboard-shortcut hint row."""
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/{item.id}"
        )
    assert resp.status_code == 200
    assert b"vp-shortcut-hint" in resp.data
    # Each key is rendered inside a <kbd> tag.
    assert b"<kbd>R</kbd>" in resp.data
    assert b"<kbd>Esc</kbd>" in resp.data
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/test_routes.py::test_wizard_step_has_shortcut_hint -v
```

Expected: FAIL.

- [ ] **Step 3: Add the hint row + script to `drift_review_item.html`**

In `templates/drift_review_item.html`, find the closing `</div>` of the action row + the closing `</div>` of the `vp-card` (around line 60–61). The current structure is:

```jinja
  <div class="mt-3 pt-3 border-top d-flex gap-2 flex-wrap align-items-center">
    {% set from_wizard = True %}
    {% include "_drift_actions.html" %}
    {% if next_item %}
      <a id="skip-link" class="btn btn-outline-secondary" href="...">Skip →</a>
    {% else %}
      <a id="skip-link" class="btn btn-outline-secondary" href="...">Skip → done</a>
    {% endif %}
    <a id="back-link" class="btn btn-link ms-auto" href="...">Back to itinerary</a>
  </div>
</div>
{% endblock %}
```

Just before that final `</div>` (the closing tag of `<div class="vp-card mb-4">`), insert the hint row. Then append a `{% block scripts %}` block after `{% endblock %}` for the keydown handler.

The new full bottom of the file becomes:

```jinja
  <div class="mt-3 pt-3 border-top d-flex gap-2 flex-wrap align-items-center">
    {% set from_wizard = True %}
    {% include "_drift_actions.html" %}
    {% if next_item %}
      <a id="skip-link" class="btn btn-outline-secondary"
         href="{{ url_for('itinerary_drift_review_item', trip_id=trip.id, item_id=next_item.id) }}">
        Skip →
      </a>
    {% else %}
      <a id="skip-link" class="btn btn-outline-secondary"
         href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">
        Skip → done
      </a>
    {% endif %}
    <a id="back-link" class="btn btn-link ms-auto" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">
      Back to itinerary
    </a>
  </div>

  <div class="vp-shortcut-hint mt-3 pt-2 border-top">
    <span><kbd>R</kbd> Resync</span>
    <span><kbd>K</kbd> Keep mine</span>
    <span><kbd>U</kbd> Unlink</span>
    <span><kbd>S</kbd> Skip</span>
    <span><kbd>Esc</kbd> Back</span>
  </div>
</div>
{% endblock %}

{% block scripts %}
<script>
  (function () {
    var map = { r: 'resync-btn', k: 'keep-btn', u: 'unlink-btn', s: 'skip-link' };
    document.addEventListener('keydown', function (e) {
      // Skip when the user is typing in a form field.
      if (e.target.matches('input, textarea, select, [contenteditable]')) return;
      // Skip on modifier keys (don't intercept Cmd-R / Ctrl-R reload).
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        var backLink = document.getElementById('back-link');
        if (backLink) backLink.click();
        return;
      }
      var id = map[e.key.toLowerCase()];
      if (!id) return;
      var el = document.getElementById(id);
      if (!el) return;  // Button is hidden (orphan case) — do nothing.
      e.preventDefault();
      el.click();  // works for both <button type=submit> and <a>
    });
  })();
</script>
{% endblock %}
```

- [ ] **Step 4: Add the hint and `kbd` CSS to `static/css/app.css`**

Append to `static/css/app.css` (at the very end of the file is fine):

```css
/* Keyboard-shortcut hint row — shown on the drift review wizard step. */
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

- [ ] **Step 5: Run the new test**

```bash
.venv/bin/pytest tests/test_routes.py::test_wizard_step_has_shortcut_hint -v
```

Expected: PASS.

- [ ] **Step 6: Manual smoke test for the shortcuts**

Boot the server. Force at least one drifting item, navigate to the drift review wizard. On the wizard step page:

1. Press `R` — should submit the resync form and navigate to the next item (or back to landing if last).
2. Reload, press `K` — should submit the keep-mine form.
3. Reload, press `U` — should submit the unlink form.
4. Reload, press `S` — should navigate to the next drift item or back to landing.
5. Reload, press `Esc` — should navigate back to the itinerary page.
6. Try pressing `Ctrl+R` — browser should reload normally; our handler must NOT intercept.
7. Type `R` in any input field (if there is one — there isn't on this page, but verify the guard works if you add an input). The handler should ignore it.

If the case-insensitivity isn't working, check that `e.key.toLowerCase()` is what indexes into the `map`. The keydown event's `.key` is `"R"` (uppercase) when caps-lock is on or shift is held; `.toLowerCase()` normalizes.

Stop the server.

- [ ] **Step 7: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add templates/drift_review_item.html static/css/app.css tests/test_routes.py
git commit -m "feat: keyboard shortcuts and hint row on drift review wizard"
```

---

## Task 8: Drop the deprecated `customized_by_user` column (GATED)

**Before running this task, STOP and confirm with Jeff that phase 3 has been in
production use for at least one week with no rollback needed.** Phase 3 just
landed today (2026-05-24); this task should NOT execute on day 1. If you're an
agent reading the plan and this hasn't been confirmed, ask the user before
proceeding.

If confirmed, the rest of the task is mechanical: add a guarded
`DROP COLUMN` to `_ensure_drift_columns` and remove the column declaration
from `models.py`. Phase 3 already eliminated every read and write of the
column, so no other code changes are required.

**Files:**
- Modify: `app.py` (the `_ensure_drift_columns` helper around line 151)
- Modify: `models.py` (the `ItineraryItem` class around lines 174–177)
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Pre-flight grep — confirm no live references**

Run:

```bash
grep -rn "customized_by_user" /Users/jeff_s/Projects/Vacation\ Planner/{app.py,models.py,src,templates,tests} --include="*.py" --include="*.html"
```

Expected matches:

- `models.py` — the deprecated column declaration (we're about to remove it).
- `app.py:_ensure_drift_columns` — the original `ADD COLUMN` statement and the backfill `UPDATE`.

If you see any other references (e.g. `item.customized_by_user`), STOP and investigate before continuing — phase 3 was supposed to remove them all.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_routes.py`:

```python
def test_customized_by_user_column_dropped(app):
    """After migrations run, customized_by_user is no longer a column."""
    from sqlalchemy import inspect
    insp = inspect(db.engine)
    cols = {c["name"] for c in insp.get_columns("itinerary_item")}
    assert "customized_by_user" not in cols
    # Sanity: the other drift columns are still there.
    assert "auto_kind" in cols
    assert "auto_fields_touched" in cols
```

- [ ] **Step 3: Run to confirm it fails**

```bash
.venv/bin/pytest tests/test_routes.py::test_customized_by_user_column_dropped -v
```

Expected: FAIL — the column is still present.

- [ ] **Step 4: Add the `DROP COLUMN` statement to `_ensure_drift_columns`**

In `app.py`, find the `_ensure_drift_columns` helper (around line 151). The current `statements` list ends with the `ADD COLUMN auto_fields_touched ...` line. Append one more entry to the list:

```python
    statements = [
        "ALTER TABLE itinerary_item ADD COLUMN auto_kind VARCHAR(20)",
        "ALTER TABLE itinerary_item ADD COLUMN customized_by_user BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE itinerary_item ADD COLUMN auto_fields_touched VARCHAR(255) NOT NULL DEFAULT ''",
        # Phase 4: drop the deprecated column. The existing try/except
        # swallow handles "column doesn't exist" idempotency and older
        # SQLite versions that lack DROP COLUMN support.
        "ALTER TABLE itinerary_item DROP COLUMN customized_by_user",
    ]
```

The backfill UPDATE (below the statements list) runs *before* the DROP because list order is preserved by the `for stmt in statements:` loop. The backfill is guarded by `WHERE customized_by_user = TRUE` — if the column is already dropped on a re-run, the UPDATE will fail and be swallowed by the outer try/except, which is fine.

**However**: this ordering issue means a *fresh* DB that hasn't had any data backfilled but does have the column will have it added, backfilled, and dropped within one boot. Since fresh DBs have no `customized_by_user=TRUE` rows, the backfill is a no-op anyway. The net effect is correct: column gone, `auto_fields_touched` data preserved.

For a DB that's already been migrated by phase 3 (i.e. real production DBs):
1. First boot after this change: ADD COLUMN statements all log "Migration skipped" (columns exist). Backfill runs — its `auto_fields_touched = ''` guard makes it a no-op for previously-backfilled rows. DROP COLUMN runs successfully.
2. Second boot: backfill fails (no column), swallowed. DROP COLUMN fails (no column), swallowed. Both logged at warning. No errors visible to the user.

- [ ] **Step 5: Remove the column declaration from `models.py`**

In `models.py`, find this block inside the `ItineraryItem` class (around lines 174–177):

```python
    # DEPRECATED in phase 3: will be replaced by auto_fields_touched.
    # Still read and written by some routes until Tasks 3–6 of the
    # phase-3 plan land. Column will be dropped in a later phase.
    customized_by_user = db.Column(db.Boolean, nullable=False, default=False)
```

Delete the entire block (the three comment lines and the column declaration).

- [ ] **Step 6: Run the new test**

```bash
.venv/bin/pytest tests/test_routes.py::test_customized_by_user_column_dropped -v
```

Expected: PASS.

- [ ] **Step 7: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass. If any test fails with a `customized_by_user` reference, phase 3 missed something — investigate that specific test before proceeding.

- [ ] **Step 8: Test the migration's idempotency**

Boot the app once against the real DB to apply the migration:

```bash
.venv/bin/python -c "from app import app; print('boot ok')"
```

Expected: prints `boot ok`. Logs include `Migration: applied ALTER TABLE itinerary_item DROP COLUMN customized_by_user` (first time) or `Migration skipped` (subsequent times).

Boot a second time to confirm idempotency:

```bash
.venv/bin/python -c "from app import app; print('boot ok')"
```

Expected: `boot ok`, no errors. The DROP statement logs a warning ("Migration skipped") because the column is gone.

Verify the column is actually gone:

```bash
.venv/bin/python -c "
from app import app, db
from sqlalchemy import inspect
with app.app_context():
    insp = inspect(db.engine)
    cols = [c['name'] for c in insp.get_columns('itinerary_item')]
    print('itinerary_item columns:', cols)
    assert 'customized_by_user' not in cols, 'column still present!'
    print('column-drop OK')
"
```

Expected: prints the column list (no `customized_by_user`), then `column-drop OK`.

- [ ] **Step 9: Commit**

```bash
git add app.py models.py tests/test_routes.py
git commit -m "chore: drop deprecated customized_by_user column"
```

---

## Done. What ships in this plan

- Dashboard pills on every active trip card showing drift and new-item counts.
- Animated flash messages site-wide (auto-dismiss after 4s, hover pauses).
- A green pulse on the chip you just resynced.
- A celebration flash when a resync clears the last drift on a trip.
- Single-key shortcuts (`R K U S Esc`) on the drift review wizard, with a visible hint row.
- (Gated) Removal of the deprecated `customized_by_user` column.

After Task 7 lands and you've used the feature for a week, run Task 8 to drop the column. After Task 8 lands, the drift feature is feature-complete; no further phase is currently planned. If the phase-3 "intentional behavior change" (edits re-engaging drift on touched items) starts to bother you in practice, that's the trigger to brainstorm a re-silence affordance.

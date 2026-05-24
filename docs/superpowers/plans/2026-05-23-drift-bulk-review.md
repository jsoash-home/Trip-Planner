# Drift Bulk Review — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the user a guided "review all drift" flow with a wizard that walks each drifting itinerary item one at a time, plus a bulk "Resync all unchanged" shortcut — instead of phase 1's per-item-only workflow.

**Architecture:** A small new module `src/drift_review.py` exposes one pure helper (`chronological_order`) for sorting items into display order. Three new routes (landing, wizard step, bulk-resync confirm + POST) reuse phase 1's `detect_drift` and the existing action POSTs. Existing per-item action routes (`itinerary_resync`, `itinerary_keep_mine`, `itinerary_unlink`) gain an optional `?from=wizard` query param that redirects to the next drifting item instead of back to the itinerary page. Two new template partials (diff table + actions block) eliminate duplication between the phase-1 detail page and the new wizard step.

**Tech Stack:** Python 3.9, Flask, Flask-SQLAlchemy, Jinja2, Bootstrap 5, pytest. No new dependencies.

**Out of scope for phase 2** (deferred to later phases):
- Surfacing "customized items that have drifted again" (would require relaxing the `customized_by_user` silence rule in `detect_drift`)
- Per-field selective resync (phase 3)
- "New items available" prompts when a booking change would generate additional slots (phase 3)
- Wizard wrap-around for skipped items
- Bulk Keep mine / bulk Unlink (only bulk Resync is in scope)
- Dashboard tile drift indicator (phase 4)

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `src/drift_review.py` | Create | Pure `chronological_order(items)` helper |
| `tests/test_drift_review.py` | Create | Unit tests for the pure helper |
| `templates/_drift_diff_table.html` | Create | Partial: the "Field / Current / Booking says" table |
| `templates/_drift_actions.html` | Create | Partial: Resync / Keep mine / Unlink buttons + optional `from_wizard` |
| `templates/itinerary_drift.html` | Modify | Switch to using the two partials |
| `templates/drift_review.html` | Create | Landing page: counts + Start review + Resync N unchanged |
| `templates/drift_review_item.html` | Create | Wizard step: progress + diff + four buttons (Resync/Keep/Unlink/Skip) |
| `templates/drift_bulk_resync_confirm.html` | Create | Bulk confirmation: list of eligible items' diffs + submit |
| `templates/trip_itinerary.html` | Modify | Banner text → link; add "Review drift" button next to "Add item" |
| `app.py` | Modify | Add 4 routes; add `_annotate_drift_for_items` helper; extract `_apply_resync_to_item` helper; add `?from=wizard` handling to phase-1 action routes |
| `tests/test_routes.py` | Modify | Integration tests for the four new routes + wizard redirect behavior |

---

## Task 1: Extract diff table + action buttons into Jinja partials

Phase 1's `itinerary_drift.html` template contains two blocks we'll reuse in the new wizard step and bulk confirmation: the diff table and the action-button row. We pull each out into its own partial under `templates/` so both pages can `{% include %}` them. No visible UI change.

**Files:**
- Create: `templates/_drift_diff_table.html`
- Create: `templates/_drift_actions.html`
- Modify: `templates/itinerary_drift.html`

- [ ] **Step 1: Create the diff-table partial**

Create `templates/_drift_diff_table.html` with exactly the table currently inside `itinerary_drift.html`:

```jinja
{# Renders the field-level diff for one item's drift report.
   Expects: drift (DriftReport with .fields). #}
<table class="table table-sm align-middle mb-3">
  <thead>
    <tr>
      <th>Field</th>
      <th>Current</th>
      <th>Booking says</th>
    </tr>
  </thead>
  <tbody>
    {% for f in drift.fields %}
      <tr>
        <td class="text-muted">{{ f.field_name }}</td>
        <td>{{ f.current if f.current is not none else '—' }}</td>
        <td><strong>{{ f.would_be if f.would_be is not none else '—' }}</strong></td>
      </tr>
    {% endfor %}
  </tbody>
</table>
```

- [ ] **Step 2: Create the actions partial**

Create `templates/_drift_actions.html`:

```jinja
{# Renders the Resync / Keep mine / Unlink form buttons for one item.
   Expects: trip, item, drift (or None), user_role.
   Optional: from_wizard (truthy → adds ?from=wizard to action URLs so
   the route redirects to the next drifting wizard step). #}
{% if can_edit(user_role) %}
  {% set qs = {'from': 'wizard'} if from_wizard else {} %}
  <div class="d-flex gap-2 flex-wrap">
    {% if drift is not none and not drift.is_orphaned %}
      <form method="post"
            action="{{ url_for('itinerary_resync', trip_id=trip.id, item_id=item.id, **qs) }}"
            class="m-0">
        <button class="btn btn-vp-primary" type="submit">
          <i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>
          Resync to booking
        </button>
      </form>
      <form method="post"
            action="{{ url_for('itinerary_keep_mine', trip_id=trip.id, item_id=item.id, **qs) }}"
            class="m-0">
        <button class="btn btn-outline-secondary" type="submit">Keep mine</button>
      </form>
    {% endif %}
    <form method="post"
          action="{{ url_for('itinerary_unlink', trip_id=trip.id, item_id=item.id, **qs) }}"
          class="m-0">
      <button class="btn btn-outline-secondary" type="submit">Unlink from booking</button>
    </form>
  </div>
{% endif %}
```

- [ ] **Step 3: Refactor `itinerary_drift.html` to use the partials**

Replace the content of `templates/itinerary_drift.html` with:

```jinja
{% extends "base.html" %}
{% block title %}Drift — {{ item.title }} — {{ trip.name }}{% endblock %}

{% block content %}
<div class="text-muted small mb-2">
  <a class="text-muted text-decoration-none" href="{{ url_for('trips_list') }}">My trips</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_overview', trip_id=trip.id) }}">{{ trip.name }}</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">Itinerary</a>
  &nbsp;›&nbsp; Drift
</div>

<h1 class="h3 mb-3">
  <i class="bi bi-exclamation-triangle-fill text-warning me-1" aria-hidden="true"></i>
  This item is out of sync
</h1>

<div class="vp-card mb-4">
  <div class="mb-3">
    <strong>{{ item.title }}</strong>
    <span class="text-muted">— linked to booking "{{ booking.title }}"</span>
  </div>

  {% if drift is none %}
    <p class="mb-0">This item is now in sync with the booking. Nothing to do.</p>
  {% elif drift.is_orphaned %}
    <p>
      The booking no longer suggests this item — for example, the
      relevant date/time on the booking was cleared.
    </p>
    <p class="mb-0">You can keep the item as a stand-alone entry, or delete it.</p>
  {% else %}
    {% include "_drift_diff_table.html" %}
  {% endif %}

  <div class="mt-3 pt-3 border-top d-flex gap-2 flex-wrap align-items-center">
    {% include "_drift_actions.html" %}
    <a class="btn btn-link ms-auto" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">Back to itinerary</a>
  </div>
</div>
{% endblock %}
```

Note: this version drops the inner `{% if can_edit %}` guard (now inside the partial) and lets the partial handle that. The "Back to itinerary" link stays outside the partial since it's specific to this page.

- [ ] **Step 4: Smoke test in the browser**

Boot the server, force drift on a booking (same trick as phase 1: edit a flight's vendor in the DB), then visit `/trips/<id>/itinerary/<item_id>/drift`. Confirm the page looks identical to before — diff table renders, buttons work.

```bash
.venv/bin/python app.py
```

Open `http://localhost:5002/`, log in, navigate to a drift detail page. Verify: page renders, diff table shows fields, all three buttons present (Resync / Keep mine / Unlink), Back-to-itinerary link works.

Stop the server.

- [ ] **Step 5: Run the existing test suite to confirm no regressions**

```bash
.venv/bin/pytest -v
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add templates/_drift_diff_table.html templates/_drift_actions.html templates/itinerary_drift.html
git commit -m "refactor: extract drift diff table and actions into Jinja partials"
```

---

## Task 2: Pure helper for chronological item order

Both the landing page and the wizard need to walk drifting items in chronological display order (day_date, then within-day order). Adding a small pure helper in a new module keeps `src/itinerary.py` from growing.

**Files:**
- Create: `src/drift_review.py`
- Create: `tests/test_drift_review.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_drift_review.py`:

```python
"""Unit tests for src/drift_review — chronological ordering of items."""

from datetime import date, time
from types import SimpleNamespace

from src.drift_review import chronological_order


def _item(item_id, day, start=None, order=0):
    return SimpleNamespace(
        id=item_id,
        day_date=day,
        start_time=start,
        order_within_day=order,
    )


def test_empty_list_returns_empty():
    assert chronological_order([]) == []


def test_items_sorted_across_days():
    a = _item(1, date(2026, 6, 3), time(9, 0))
    b = _item(2, date(2026, 6, 1), time(9, 0))
    c = _item(3, date(2026, 6, 2), time(9, 0))
    assert [it.id for it in chronological_order([a, b, c])] == [2, 3, 1]


def test_untimed_items_come_first_within_day():
    timed = _item(1, date(2026, 6, 1), time(9, 0))
    untimed = _item(2, date(2026, 6, 1), None)
    assert [it.id for it in chronological_order([timed, untimed])] == [2, 1]


def test_untimed_items_sorted_by_order_within_day():
    a = _item(1, date(2026, 6, 1), None, order=2)
    b = _item(2, date(2026, 6, 1), None, order=1)
    assert [it.id for it in chronological_order([a, b])] == [2, 1]


def test_timed_items_sorted_by_start_time_within_day():
    a = _item(1, date(2026, 6, 1), time(15, 0))
    b = _item(2, date(2026, 6, 1), time(9, 0))
    assert [it.id for it in chronological_order([a, b])] == [2, 1]


def test_id_tiebreaker_is_stable():
    a = _item(2, date(2026, 6, 1), time(9, 0), order=0)
    b = _item(1, date(2026, 6, 1), time(9, 0), order=0)
    assert [it.id for it in chronological_order([a, b])] == [1, 2]


def test_items_with_no_day_date_are_skipped():
    a = _item(1, date(2026, 6, 1), time(9, 0))
    b = _item(2, None, time(9, 0))
    assert [it.id for it in chronological_order([a, b])] == [1]
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_drift_review.py -v
```

Expected: all 7 tests FAIL with `ModuleNotFoundError: No module named 'src.drift_review'`.

- [ ] **Step 3: Implement the helper**

Create `src/drift_review.py`:

```python
"""
src/drift_review.py

Pure helpers for the drift review wizard — chronological ordering of
itinerary items so the wizard can walk them in trip-day order. No DB,
no Flask imports.
"""

import logging
from typing import Iterable, List

from src.itinerary import sort_within_day

logger = logging.getLogger(__name__)


def chronological_order(items: Iterable) -> List:
    """
    Return `items` sorted in trip-display order: day_date ascending,
    then within each day using the same rule as `sort_within_day`
    (untimed first by order_within_day, then timed by start_time).

    Items with no `day_date` are dropped with a debug log line — those
    only arise from in-memory test fixtures, real DB rows always have
    one because the column is NOT NULL.
    """
    by_day = {}
    for it in items:
        d = getattr(it, "day_date", None)
        if d is None:
            logger.debug("chronological_order skipping item without day_date: %r", it)
            continue
        by_day.setdefault(d, []).append(it)

    out: List = []
    for d in sorted(by_day):
        out.extend(sort_within_day(by_day[d]))
    return out
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_drift_review.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Run the full test suite to catch unrelated breakage**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/drift_review.py tests/test_drift_review.py
git commit -m "feat: chronological_order helper for drift review wizard"
```

---

## Task 3: Drift review landing page

Adds the GET landing page that shows the drift breakdown and two CTAs. Also wires the entry points: a "Review drift" button on the itinerary page header, and turns the banner's static text into a link.

**Files:**
- Modify: `app.py` (add `_annotate_drift_for_items` helper; add `itinerary_drift_review` route)
- Create: `templates/drift_review.html`
- Modify: `templates/trip_itinerary.html` (link the banner, add the page header button)
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Extract drift-annotation helper**

The existing `trip_itinerary` route (in `app.py` around line 820-846) inlines the logic for annotating each item with `.drift` and counting the drifting ones. We'll need the same logic in the new routes, so extract it.

In `app.py`, just above the `trip_itinerary` route (around line 819), add this helper:

```python
def _annotate_drift_for_items(items):
    """Annotate each item in-place with a `.drift` attribute (DriftReport or None).

    Pre-fetches all referenced bookings in one query to avoid N+1.
    Returns the count of items with non-None drift, so callers that
    just need the count don't have to re-iterate.
    """
    linked_booking_ids = {it.linked_booking_id for it in items if it.linked_booking_id}
    bookings_by_id = {
        b.id: b for b in Booking.query.filter(Booking.id.in_(linked_booking_ids)).all()
    } if linked_booking_ids else {}

    drift_count = 0
    for it in items:
        it.drift = None
        if not it.linked_booking_id:
            continue
        booking = bookings_by_id.get(it.linked_booking_id)
        if booking is None:
            # Booking row is gone but the cascade didn't clean this item up.
            it.drift = DriftReport(is_orphaned=True)
            drift_count += 1
            continue
        it.drift = detect_drift(it, booking)
        if it.drift is not None:
            drift_count += 1
    return drift_count
```

Then in `trip_itinerary`, replace lines 823-846 (the explicit annotation block) with:

```python
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    drift_count = _annotate_drift_for_items(items)
```

so the route now reads as:

```python
@app.route("/trips/<int:trip_id>/itinerary")
@login_required
def trip_itinerary(trip_id):
    """Day-by-day timeline view. Viewer+ access."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    drift_count = _annotate_drift_for_items(items)
    days = group_items_by_day(items, trip.start_date, trip.end_date)
    return render_template(
        "trip_itinerary.html",
        trip=trip,
        user_role=user_role,
        days=days,
        drift_count=drift_count,
    )
```

- [ ] **Step 2: Add `chronological_order` to the imports**

In `app.py`, find the existing import block at the top. Add a new import:

```python
from src.drift_review import chronological_order
```

Place it alphabetically — after `src.currency` and before `src.itinerary`.

- [ ] **Step 3: Write the failing landing-page tests**

Append to `tests/test_routes.py`:

```python
def _login(client, user):
    """Stuff a Flask-Login session for the given user."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_drift_review_landing_empty(app, trip, owner):
    """No drift anywhere → landing page shows the all-clear state."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/itinerary/drift-review")
    assert resp.status_code == 200
    assert b"Nothing" in resp.data or b"all in sync" in resp.data.lower() or b"0 items" in resp.data


def test_drift_review_landing_counts_resyncable_vs_orphan(app, trip, owner):
    """One resyncable + one orphaned → page shows both counts."""
    # Booking + a stale linked item (resyncable drift).
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item_a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                           auto_kind="arrive", day_date=date(2026, 6, 1),
                           title="Arrive Delta",  # drifted: booking says United
                           category="transit")
    db.session.add(item_a)
    # Booking that no longer suggests "depart" (start_datetime cleared).
    b2 = Booking(trip_id=trip.id, type="flight", title="DL200", vendor="Delta",
                 start_datetime=None,
                 end_datetime=datetime(2026, 6, 2, 14, 0))
    db.session.add(b2)
    db.session.commit()
    item_b = ItineraryItem(trip_id=trip.id, linked_booking_id=b2.id,
                           auto_kind="depart", day_date=date(2026, 6, 2),
                           title="Depart Delta", category="transit")
    db.session.add(item_b)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/itinerary/drift-review")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 2 total drifting, 1 resyncable, 1 orphan.
    assert "2" in body and "1" in body
    assert "Start review" in body
    assert "Resync 1 unchanged" in body
```

- [ ] **Step 4: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "drift_review_landing" -v
```

Expected: both tests FAIL with 404.

- [ ] **Step 5: Add the landing route**

In `app.py`, just before the existing `itinerary_drift` route (around line 966), add:

```python
@app.route("/trips/<int:trip_id>/itinerary/drift-review")
@login_required
def itinerary_drift_review(trip_id):
    """Landing page for the drift review wizard. Viewer+ access.

    Shows total / resyncable / orphan counts and two CTAs (Start
    review, Resync N unchanged). Doubles as the "all done" view when
    the wizard finishes.
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]
    resyncable = [it for it in drifting if not it.drift.is_orphaned]
    orphans = [it for it in drifting if it.drift.is_orphaned]
    return render_template(
        "drift_review.html",
        trip=trip,
        user_role=user_role,
        drift_count=len(drifting),
        resyncable_count=len(resyncable),
        orphans=orphans,
        first_drifting_id=drifting[0].id if drifting else None,
    )
```

- [ ] **Step 6: Create the landing template**

Create `templates/drift_review.html`:

```jinja
{% extends "base.html" %}
{% block title %}Review drift — {{ trip.name }} — Vacation Planner{% endblock %}

{% block content %}
<div class="text-muted small mb-2">
  <a class="text-muted text-decoration-none" href="{{ url_for('trips_list') }}">My trips</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_overview', trip_id=trip.id) }}">{{ trip.name }}</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">Itinerary</a>
  &nbsp;›&nbsp; Review drift
</div>

<h1 class="h3 mb-3">
  <i class="bi bi-exclamation-triangle-fill text-warning me-1" aria-hidden="true"></i>
  Review drift
</h1>

<div class="vp-card mb-4">
  {% if drift_count == 0 %}
    <p class="mb-3">Nothing's out of sync right now — every linked itinerary item matches its booking.</p>
    <a class="btn btn-vp-primary" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">
      <i class="bi bi-arrow-left me-1" aria-hidden="true"></i>
      Back to itinerary
    </a>
  {% else %}
    <p class="mb-3">
      <strong>{{ drift_count }}</strong> itinerary item{{ '' if drift_count == 1 else 's' }}
      {{ 'is' if drift_count == 1 else 'are' }} out of sync with
      {{ 'its' if drift_count == 1 else 'their' }} booking{{ '' if drift_count == 1 else 's' }}.
      {% if resyncable_count > 0 and orphans|length > 0 %}
        {{ resyncable_count }} can be auto-resynced.
        {{ orphans|length }} need{{ 's' if orphans|length == 1 else '' }} individual review.
      {% elif resyncable_count > 0 %}
        All can be auto-resynced.
      {% else %}
        These need individual review — their bookings no longer suggest them.
      {% endif %}
    </p>

    <div class="d-flex gap-2 flex-wrap">
      {% if first_drifting_id %}
        <a class="btn btn-vp-primary"
           href="{{ url_for('itinerary_drift_review_item', trip_id=trip.id, item_id=first_drifting_id) }}">
          Start review →
        </a>
      {% endif %}
      {% if can_edit(user_role) and resyncable_count > 0 %}
        <a class="btn btn-outline-secondary"
           href="{{ url_for('itinerary_drift_review_bulk_resync', trip_id=trip.id) }}">
          <i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>
          Resync {{ resyncable_count }} unchanged
        </a>
      {% endif %}
      <a class="btn btn-link ms-auto" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">
        Back to itinerary
      </a>
    </div>

    {% if orphans %}
      <hr>
      <h2 class="h6 text-muted mb-2">Still needs review</h2>
      <ul class="list-unstyled small mb-0">
        {% for it in orphans %}
          <li class="mb-1">
            <a href="{{ url_for('itinerary_drift_review_item', trip_id=trip.id, item_id=it.id) }}">
              {{ it.title }}
            </a>
            <span class="text-muted">— {{ it.day_date.strftime('%a, %b %d') }} — booking no longer suggests this</span>
          </li>
        {% endfor %}
      </ul>
    {% endif %}
  {% endif %}
</div>
{% endblock %}
```

Note: the template references two routes we haven't created yet (`itinerary_drift_review_item` in Task 4, `itinerary_drift_review_bulk_resync` in Task 7). Until those exist, the page renders but the links would 500. We accept this temporary breakage — Task 4 and Task 7 fix it.

- [ ] **Step 7: Run the landing-page tests**

```bash
.venv/bin/pytest tests/test_routes.py -k "drift_review_landing" -v
```

Expected: both tests PASS. (Don't click the buttons yet — the wizard step doesn't exist.)

- [ ] **Step 8: Wire the entry points on the itinerary page**

In `templates/trip_itinerary.html`, find the banner block (lines 12-20) and replace:

```jinja
{% if drift_count > 0 %}
  <div class="alert alert-warning d-flex align-items-center justify-content-between" role="alert">
    <div>
      <i class="bi bi-exclamation-triangle-fill me-2" aria-hidden="true"></i>
      {{ drift_count }} itinerary item{{ '' if drift_count == 1 else 's' }} out of sync with {{ 'its' if drift_count == 1 else 'their' }} booking{{ '' if drift_count == 1 else 's' }}.
    </div>
    <small class="text-muted">Click the warning pill on each item to review.</small>
  </div>
{% endif %}
```

with:

```jinja
{% if drift_count > 0 %}
  <div class="alert alert-warning d-flex align-items-center justify-content-between" role="alert">
    <div>
      <i class="bi bi-exclamation-triangle-fill me-2" aria-hidden="true"></i>
      {{ drift_count }} itinerary item{{ '' if drift_count == 1 else 's' }} out of sync with {{ 'its' if drift_count == 1 else 'their' }} booking{{ '' if drift_count == 1 else 's' }}.
    </div>
    <a class="alert-link" href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">
      Review all drift →
    </a>
  </div>
{% endif %}
```

Next, find the page-header row (lines 22-30) and add a "Review drift" button next to the existing "Add item" button. Replace:

```jinja
<div class="d-flex align-items-center justify-content-between mb-3">
  <h1 class="h3 mb-0">Itinerary</h1>
  {% if can_edit(user_role) %}
    <a class="btn btn-vp-primary" href="{{ url_for('itinerary_new', trip_id=trip.id) }}">
      <i class="bi bi-plus-lg me-1" aria-hidden="true"></i>
      Add item
    </a>
  {% endif %}
</div>
```

with:

```jinja
<div class="d-flex align-items-center justify-content-between mb-3">
  <h1 class="h3 mb-0">Itinerary</h1>
  <div class="d-flex gap-2">
    {% if drift_count > 0 %}
      <a class="btn btn-outline-warning"
         href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">
        <i class="bi bi-exclamation-triangle-fill me-1" aria-hidden="true"></i>
        Review drift
      </a>
    {% endif %}
    {% if can_edit(user_role) %}
      <a class="btn btn-vp-primary" href="{{ url_for('itinerary_new', trip_id=trip.id) }}">
        <i class="bi bi-plus-lg me-1" aria-hidden="true"></i>
        Add item
      </a>
    {% endif %}
  </div>
</div>
```

The "Review drift" button is visible to viewers too (drift review is a viewer-accessible read; only the action POSTs require editor).

- [ ] **Step 9: Smoke test**

Boot the server, force drift on a booking, visit the itinerary page. Confirm:
- Banner now ends with "Review all drift →" link instead of the prompt text
- "Review drift" button appears next to "Add item"
- Both links open `/trips/<id>/itinerary/drift-review`
- Landing page shows the correct counts
- Clicking "Start review" 500s (expected — wizard route doesn't exist yet); clicking "Resync N unchanged" 500s (expected — bulk route doesn't exist yet)

Resolve the drift (either edit the booking back or use one of the existing buttons on the per-item drift page). Reload the itinerary page. Confirm:
- Banner and "Review drift" button are gone (drift_count is 0)

Stop the server.

- [ ] **Step 10: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add app.py templates/drift_review.html templates/trip_itinerary.html tests/test_routes.py
git commit -m "feat: drift review landing page + itinerary page entry points"
```

---

## Task 4: Wizard step route + template

The wizard renders one drifting item at a time with progress indicator, diff table, and four buttons.

**Files:**
- Modify: `app.py` (add `itinerary_drift_review_item` route)
- Create: `templates/drift_review_item.html`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def test_drift_review_wizard_renders_first_item(app, trip, owner):
    """GET wizard step on a drifting item shows the diff + Skip + buttons."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta", category="transit")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/item/{item.id}"
        )
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Item 1 of 1" in body
    assert "Skip" in body
    assert "Resync to booking" in body
    assert "Keep mine" in body
    assert "Unlink from booking" in body


def test_drift_review_wizard_progress_counts(app, trip, owner):
    """Two drifting items → 'Item 1 of 2' on the first, 'Item 2 of 2' on the second."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    # Two linked items, both drifted on title.
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp1 = client.get(f"/trips/{trip.id}/itinerary/drift-review/item/{a.id}")
        resp2 = client.get(f"/trips/{trip.id}/itinerary/drift-review/item/{z.id}")
    assert b"Item 1 of 2" in resp1.data
    assert b"Item 2 of 2" in resp2.data


def test_drift_review_wizard_redirects_when_item_not_drifting(app, trip, owner):
    """GET wizard step on an item that isn't drifting → redirect to landing."""
    b = Booking(trip_id=trip.id, type="restaurant", title="Noma", vendor="Noma",
                start_datetime=datetime(2026, 6, 1, 19, 0), end_datetime=None)
    db.session.add(b)
    db.session.commit()
    # In-sync item — no drift.
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="single", day_date=date(2026, 6, 1),
                         start_time=__import__("datetime").time(19, 0),
                         title="Noma", category="meal")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/item/{item.id}",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "/drift-review" in resp.headers["Location"]
    assert f"/item/{item.id}" not in resp.headers["Location"]
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "drift_review_wizard" -v
```

Expected: all 3 tests FAIL with 404.

- [ ] **Step 3: Add the wizard route**

In `app.py`, just below the `itinerary_drift_review` route added in Task 3, add:

```python
@app.route("/trips/<int:trip_id>/itinerary/drift-review/item/<int:item_id>")
@login_required
def itinerary_drift_review_item(trip_id, item_id):
    """One wizard step — render one drifting item's diff and actions.
    Viewer+ access (the action POSTs still require editor).

    Redirects back to the landing page if the item isn't drifting (e.g.,
    user bookmarked the URL and the drift has since been resolved).
    """
    trip, item, user_role = _itinerary_item_with_access_or_404(
        trip_id, item_id, role="viewer"
    )
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]

    current = next((it for it in drifting if it.id == item_id), None)
    if current is None:
        flash("That item isn't out of sync — nothing to review.", "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    idx = drifting.index(current)
    next_item = drifting[idx + 1] if idx + 1 < len(drifting) else None
    booking = (
        db.session.get(Booking, current.linked_booking_id)
        if current.linked_booking_id else None
    )
    return render_template(
        "drift_review_item.html",
        trip=trip,
        user_role=user_role,
        item=current,
        booking=booking,
        drift=current.drift,
        next_item=next_item,
        progress_current=idx + 1,
        progress_total=len(drifting),
    )
```

- [ ] **Step 4: Create the wizard template**

Create `templates/drift_review_item.html`:

```jinja
{% extends "base.html" %}
{% block title %}Review drift — {{ item.title }} — {{ trip.name }}{% endblock %}

{% block content %}
<div class="text-muted small mb-2">
  <a class="text-muted text-decoration-none" href="{{ url_for('trips_list') }}">My trips</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_overview', trip_id=trip.id) }}">{{ trip.name }}</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">Itinerary</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">Review drift</a>
  &nbsp;›&nbsp; Item {{ progress_current }} of {{ progress_total }}
</div>

<div class="d-flex align-items-center justify-content-between mb-3">
  <h1 class="h3 mb-0">
    <i class="bi bi-exclamation-triangle-fill text-warning me-1" aria-hidden="true"></i>
    Item {{ progress_current }} of {{ progress_total }}
  </h1>
</div>

<div class="vp-card mb-4">
  <div class="mb-3">
    <strong>{{ item.title }}</strong>
    {% if booking %}
      <span class="text-muted">— linked to booking "{{ booking.title }}"</span>
    {% endif %}
  </div>

  {% if drift is none %}
    <p class="mb-0">This item is now in sync. <a href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">Back to review</a></p>
  {% elif drift.is_orphaned %}
    <p>
      The booking no longer suggests this item — for example, the
      relevant date/time on the booking was cleared.
    </p>
    <p class="mb-0">You can keep the item as a stand-alone entry, or unlink it.</p>
  {% else %}
    {% include "_drift_diff_table.html" %}
  {% endif %}

  <div class="mt-3 pt-3 border-top d-flex gap-2 flex-wrap align-items-center">
    {% set from_wizard = True %}
    {% include "_drift_actions.html" %}
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
  </div>
</div>
{% endblock %}
```

The `{% set from_wizard = True %}` line makes the included `_drift_actions.html` partial add `?from=wizard` to its action URLs (the partial checks `from_wizard` and appends the query string accordingly). `{% include %}` in Jinja passes the current template's variables by default, so no `with context` clause is needed.

(The action POSTs don't yet honor the `from=wizard` param — Task 5 wires that. For now, clicking Resync/Keep/Unlink in the wizard will redirect to the itinerary page, same as phase 1. Skip works correctly today.)

- [ ] **Step 5: Run the wizard tests**

```bash
.venv/bin/pytest tests/test_routes.py -k "drift_review_wizard" -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Smoke test**

Boot the server, force drift on a booking, visit the itinerary page, click "Review drift", then click "Start review →". Confirm:
- Wizard step renders with progress indicator ("Item 1 of N")
- Diff table is correct
- Skip button advances to next item, or "Skip → done" returns to landing on the last item
- Resync/Keep/Unlink still work (they redirect to the itinerary page for now — Task 5 fixes that)

Stop the server.

- [ ] **Step 7: Commit**

```bash
git add app.py templates/drift_review_item.html tests/test_routes.py
git commit -m "feat: drift review wizard step with progress and skip"
```

---

## Task 5: Per-item action POSTs honor `?from=wizard`

Wire the three phase-1 action routes to redirect to the next drifting wizard step (or back to landing) when invoked from the wizard.

**Files:**
- Modify: `app.py` (3 routes: `itinerary_resync`, `itinerary_keep_mine`, `itinerary_unlink`)
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def test_wizard_resync_redirects_to_next_drifting(app, trip, owner):
    """Resync with ?from=wizard advances to the next drifting item's wizard."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{a.id}/resync?from=wizard"
        )
    assert resp.status_code == 302
    assert f"/drift-review/item/{z.id}" in resp.headers["Location"]


def test_wizard_resync_redirects_to_landing_when_no_more_drift(app, trip, owner):
    """Resync the last drifting item with ?from=wizard → land on review home."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta", category="transit")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{item.id}/resync?from=wizard"
        )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/trips/{trip.id}/itinerary/drift-review")


def test_wizard_keep_mine_redirects_to_next_drifting(app, trip, owner):
    """Keep mine with ?from=wizard advances to the next drifting item."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{a.id}/keep-mine?from=wizard"
        )
    assert resp.status_code == 302
    assert f"/drift-review/item/{z.id}" in resp.headers["Location"]


def test_wizard_unlink_redirects_to_next_drifting(app, trip, owner):
    """Unlink with ?from=wizard advances to the next drifting item."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{a.id}/unlink?from=wizard"
        )
    assert resp.status_code == 302
    assert f"/drift-review/item/{z.id}" in resp.headers["Location"]


def test_non_wizard_resync_still_redirects_to_itinerary(app, trip, owner):
    """Phase-1 behavior preserved: no ?from=wizard → redirect to itinerary."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta", category="transit")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/trips/{trip.id}/itinerary")
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "wizard_" -v
```

Expected: 4 of the new tests FAIL (the redirect URL is `/trips/<id>/itinerary` not the wizard URL); the `test_non_wizard_resync_still_redirects_to_itinerary` test PASSES.

- [ ] **Step 3: Add the redirect helper**

In `app.py`, just above the `itinerary_resync` route (around line 990), add this helper:

```python
def _redirect_after_wizard_action(trip_id, current_item_id):
    """After a wizard-originated action, redirect to the next drifting
    item's wizard step — or to the landing page if no more drift.

    The "next" is computed against the chronological position of
    `current_item_id` in the full trip, which works even after the
    action has cleared drift on the current item.
    """
    items = ItineraryItem.query.filter_by(trip_id=trip_id).all()
    _annotate_drift_for_items(items)
    all_ordered = chronological_order(items)
    current_pos = next(
        (i for i, it in enumerate(all_ordered) if it.id == current_item_id),
        -1,
    )
    next_item = next(
        (it for i, it in enumerate(all_ordered)
         if i > current_pos and it.drift is not None),
        None,
    )
    if next_item is not None:
        return redirect(url_for(
            "itinerary_drift_review_item",
            trip_id=trip_id, item_id=next_item.id,
        ))
    return redirect(url_for("itinerary_drift_review", trip_id=trip_id))
```

- [ ] **Step 4: Wire the helper into `itinerary_resync`**

In `app.py`, find the existing `itinerary_resync` route. Replace its final two lines:

```python
    flash(f"Resynced "{item.title}" to the booking.", "success")
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

with:

```python
    flash(f"Resynced "{item.title}" to the booking.", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

Also do the same earlier in the same route — the early-return branches that redirect on error conditions should still go to the itinerary page (those are error paths, not action paths). Leave them alone.

- [ ] **Step 5: Wire the helper into `itinerary_keep_mine`**

Find `itinerary_keep_mine`. Replace its final two lines (currently `flash` then `return redirect(url_for("trip_itinerary"...`) with:

```python
    flash(f"Kept your version of "{item.title}".", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

- [ ] **Step 6: Wire the helper into `itinerary_unlink`**

Find `itinerary_unlink`. Replace its final two lines with:

```python
    flash(f"Unlinked "{item.title}" from its booking.", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

- [ ] **Step 7: Run the wizard-redirect tests**

```bash
.venv/bin/pytest tests/test_routes.py -k "wizard_" -v
```

Expected: all 5 tests PASS.

- [ ] **Step 8: Run the full suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 9: Smoke test in the browser**

Boot the server, force drift on two bookings (so you have 2 drifting items). Visit the itinerary page → Review drift → Start review.

On the first item: click Keep mine. Confirm the page advances to the second drifting item's wizard step (not back to the itinerary page).

On the second (now last) item: click Resync. Confirm the page lands on the drift review home with "Nothing's out of sync".

Stop the server.

- [ ] **Step 10: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: wizard action routes redirect to next drifting item"
```

---

## Task 6: Extract `_apply_resync_to_item` helper

Before adding the bulk-resync POST, extract the per-item resync body from `itinerary_resync` into a small private helper so both routes use the same logic. Pure refactor — no behavior change.

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add the helper**

In `app.py`, just above `itinerary_resync` (and above `_redirect_after_wizard_action` from Task 5), add:

```python
def _apply_resync_to_item(item, booking) -> bool:
    """Apply the booking's auto-generated values to one item.

    Returns True if the item was updated, False if the booking no
    longer generates an item of this auto_kind (orphaned). Caller is
    responsible for committing the session.
    """
    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == item.auto_kind]
    if not matches:
        return False
    would_be = matches[0]
    for f in DRIFT_FIELDS:
        setattr(item, f, would_be.get(f))
    item.customized_by_user = False
    return True
```

- [ ] **Step 2: Update `itinerary_resync` to call the helper**

In `app.py`, find the body of `itinerary_resync`. Replace this block:

```python
    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == item.auto_kind]
    if not matches:
        flash(
            "The booking no longer suggests this item. Use Unlink or Delete.",
            "warning",
        )
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    would_be = matches[0]
    for f in DRIFT_FIELDS:
        setattr(item, f, would_be.get(f))
    item.customized_by_user = False
    db.session.commit()
```

with:

```python
    if not _apply_resync_to_item(item, booking):
        flash(
            "The booking no longer suggests this item. Use Unlink or Delete.",
            "warning",
        )
        return redirect(url_for("trip_itinerary", trip_id=trip.id))
    db.session.commit()
```

- [ ] **Step 3: Run the existing resync tests to confirm no behavior change**

```bash
.venv/bin/pytest tests/test_routes.py -k "resync" -v
```

Expected: all existing resync tests pass — including the wizard-redirect tests from Task 5.

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "refactor: extract _apply_resync_to_item helper for reuse"
```

---

## Task 7: Bulk-resync confirmation page (GET)

Renders the confirmation page that lists every eligible item's diff and warns about any orphans that will be skipped.

**Files:**
- Modify: `app.py` (add `itinerary_drift_review_bulk_resync` GET route)
- Create: `templates/drift_bulk_resync_confirm.html`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def test_bulk_resync_confirm_lists_eligible_items(app, trip, owner):
    """GET confirmation page lists each resyncable item with its diff."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta", category="transit")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Item appears in the list, and the resync button mentions count = 1.
    assert "Arrive Delta" in body
    assert "Resync these 1" in body or "Resync these 1 item" in body


def test_bulk_resync_confirm_mentions_orphans(app, trip, owner):
    """When orphans exist alongside eligible items, page notes them."""
    # Resyncable: a normal flight with drift.
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item_ok = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                            auto_kind="arrive", day_date=date(2026, 6, 1),
                            title="Arrive Delta", category="transit")
    db.session.add(item_ok)
    # Orphan: booking that no longer suggests "depart" (start_datetime cleared).
    b2 = Booking(trip_id=trip.id, type="flight", title="DL200", vendor="Delta",
                 start_datetime=None,
                 end_datetime=datetime(2026, 6, 2, 14, 0))
    db.session.add(b2)
    db.session.commit()
    orphan = ItineraryItem(trip_id=trip.id, linked_booking_id=b2.id,
                           auto_kind="depart", day_date=date(2026, 6, 2),
                           title="Depart Delta", category="transit")
    db.session.add(orphan)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    body = resp.data.decode("utf-8")
    assert "1 orphan" in body or "1 item can't be auto-resynced" in body
    # Orphan item title NOT in the resync list block.
    assert "Resync these 1" in body or "Resync these 1 item" in body


def test_bulk_resync_confirm_redirects_when_nothing_eligible(app, trip, owner):
    """No eligible items → flash + redirect to landing."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(
        f"/trips/{trip.id}/itinerary/drift-review"
    )
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "bulk_resync_confirm" -v
```

Expected: all 3 tests FAIL with 404.

- [ ] **Step 3: Add the route**

In `app.py`, just below `itinerary_drift_review_item` (from Task 4), add:

```python
@app.route("/trips/<int:trip_id>/itinerary/drift-review/bulk-resync")
@login_required
def itinerary_drift_review_bulk_resync(trip_id):
    """Confirmation page for the bulk-resync action. Editor+ access.

    Lists every eligible item (drifting + not orphaned) with its diff.
    Flags the count of orphaned items being skipped. Redirects back to
    the landing page if no eligible items exist.
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="editor")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]
    eligible = [it for it in drifting if not it.drift.is_orphaned]
    orphan_count = sum(1 for it in drifting if it.drift.is_orphaned)

    if not eligible:
        flash("Nothing to bulk-resync — all drifting items need individual review.",
              "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    return render_template(
        "drift_bulk_resync_confirm.html",
        trip=trip,
        user_role=user_role,
        eligible=eligible,
        eligible_count=len(eligible),
        orphan_count=orphan_count,
    )
```

- [ ] **Step 4: Create the confirmation template**

Create `templates/drift_bulk_resync_confirm.html`:

```jinja
{% extends "base.html" %}
{% block title %}Confirm bulk resync — {{ trip.name }} — Vacation Planner{% endblock %}

{% block content %}
<div class="text-muted small mb-2">
  <a class="text-muted text-decoration-none" href="{{ url_for('trips_list') }}">My trips</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_overview', trip_id=trip.id) }}">{{ trip.name }}</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">Itinerary</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">Review drift</a>
  &nbsp;›&nbsp; Bulk resync
</div>

<h1 class="h3 mb-3">
  <i class="bi bi-arrow-clockwise text-warning me-1" aria-hidden="true"></i>
  Confirm bulk resync
</h1>

<div class="vp-card mb-4">
  <p>
    This will overwrite the following <strong>{{ eligible_count }}</strong>
    item{{ '' if eligible_count == 1 else 's' }} with
    {{ 'its' if eligible_count == 1 else 'their' }} booking's current values.
    {% if orphan_count > 0 %}
      {{ orphan_count }} item{{ '' if orphan_count == 1 else 's' }} can't be
      auto-resynced (booking no longer suggests
      {{ 'it' if orphan_count == 1 else 'them' }}) — review
      {{ 'it' if orphan_count == 1 else 'them' }} individually after.
    {% endif %}
  </p>

  {% for it in eligible %}
    <div class="border rounded p-3 mb-3">
      <div class="mb-2">
        <strong>{{ it.title }}</strong>
        <span class="text-muted small">— {{ it.day_date.strftime('%a, %b %d') }}</span>
      </div>
      {% set drift = it.drift %}
      {% include "_drift_diff_table.html" %}
    </div>
  {% endfor %}

  <form method="post"
        action="{{ url_for('itinerary_drift_review_bulk_resync', trip_id=trip.id) }}"
        class="d-flex gap-2 flex-wrap mt-3 pt-3 border-top">
    <button type="submit" class="btn btn-vp-primary">
      <i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>
      Resync these {{ eligible_count }} item{{ '' if eligible_count == 1 else 's' }}
    </button>
    <a class="btn btn-outline-secondary"
       href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">
      Cancel
    </a>
  </form>
</div>
{% endblock %}
```

The `{% set drift = it.drift %}` is needed because `_drift_diff_table.html` expects a variable named `drift`, but in this template we're iterating over `eligible` items whose drift is on `it.drift`.

- [ ] **Step 5: Run the confirmation tests**

```bash
.venv/bin/pytest tests/test_routes.py -k "bulk_resync_confirm" -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Smoke test**

Boot the server. Force drift on a couple of bookings. From the itinerary page, click "Review drift" → "Resync N unchanged". Confirm:
- Confirmation page lists each item with its diff table
- The submit button says "Resync these N items"
- The Cancel link returns to the landing page
- Clicking the submit button 500s (POST handler doesn't exist yet — Task 8 adds it)

Stop the server.

- [ ] **Step 7: Commit**

```bash
git add app.py templates/drift_bulk_resync_confirm.html tests/test_routes.py
git commit -m "feat: bulk-resync confirmation page lists eligible items"
```

---

## Task 8: Bulk-resync POST handler

Add the POST that actually applies the resync to every eligible item in one transaction.

**Files:**
- Modify: `app.py`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def test_bulk_resync_post_updates_all_eligible(app, trip, owner):
    """POST resyncs every eligible item in one transaction."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(
        f"/trips/{trip.id}/itinerary/drift-review"
    )
    db.session.refresh(a)
    db.session.refresh(z)
    assert a.title == "Check in: Hilton"
    assert z.title == "Check out: Hilton"
    assert a.customized_by_user is False
    assert z.customized_by_user is False


def test_bulk_resync_post_skips_orphans(app, trip, owner):
    """Orphans in the mix don't break the resync of eligible items."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    eligible_item = ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id,
        auto_kind="arrive", day_date=date(2026, 6, 1),
        title="Arrive Delta", category="transit",
    )
    db.session.add(eligible_item)
    b2 = Booking(trip_id=trip.id, type="flight", title="DL200", vendor="Delta",
                 start_datetime=None,
                 end_datetime=datetime(2026, 6, 2, 14, 0))
    db.session.add(b2)
    db.session.commit()
    orphan = ItineraryItem(trip_id=trip.id, linked_booking_id=b2.id,
                           auto_kind="depart", day_date=date(2026, 6, 2),
                           title="Depart Delta", category="transit")
    db.session.add(orphan)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    assert resp.status_code == 302
    db.session.refresh(eligible_item)
    db.session.refresh(orphan)
    # Eligible was resynced.
    assert eligible_item.title == "Arrive United"
    # Orphan untouched.
    assert orphan.title == "Depart Delta"


def test_bulk_resync_post_redirects_when_nothing_eligible(app, trip, owner):
    """POST with no eligible items → flash + redirect, no DB change."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(
        f"/trips/{trip.id}/itinerary/drift-review"
    )
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "bulk_resync_post" -v
```

Expected: 2 tests FAIL (404 — POST not registered); 1 may pass since the empty-trip case redirects naturally from the GET handler... actually no, the GET handler doesn't accept POST. All 3 FAIL with 405 (method not allowed) or 404.

- [ ] **Step 3: Add the POST handler**

In `app.py`, find the `itinerary_drift_review_bulk_resync` route added in Task 7. Change its decorator from:

```python
@app.route("/trips/<int:trip_id>/itinerary/drift-review/bulk-resync")
```

to accept both methods:

```python
@app.route(
    "/trips/<int:trip_id>/itinerary/drift-review/bulk-resync",
    methods=["GET", "POST"],
)
```

Then at the top of the function body (just after the access guard and items load), branch on the method. Replace:

```python
def itinerary_drift_review_bulk_resync(trip_id):
    """Confirmation page for the bulk-resync action. Editor+ access.
    ...
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="editor")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]
    eligible = [it for it in drifting if not it.drift.is_orphaned]
    orphan_count = sum(1 for it in drifting if it.drift.is_orphaned)

    if not eligible:
        flash("Nothing to bulk-resync — all drifting items need individual review.",
              "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    return render_template(
        "drift_bulk_resync_confirm.html",
        ...
    )
```

with:

```python
def itinerary_drift_review_bulk_resync(trip_id):
    """Confirmation page (GET) + bulk apply (POST). Editor+ access.

    Lists every eligible item (drifting + not orphaned) with its diff.
    Flags the count of orphaned items being skipped. Redirects back to
    the landing page if no eligible items exist.
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="editor")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]
    eligible = [it for it in drifting if not it.drift.is_orphaned]
    orphan_count = sum(1 for it in drifting if it.drift.is_orphaned)

    if not eligible:
        flash("Nothing to bulk-resync — all drifting items need individual review.",
              "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

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

    return render_template(
        "drift_bulk_resync_confirm.html",
        trip=trip,
        user_role=user_role,
        eligible=eligible,
        eligible_count=len(eligible),
        orphan_count=orphan_count,
    )
```

- [ ] **Step 4: Run the POST tests**

```bash
.venv/bin/pytest tests/test_routes.py -k "bulk_resync_post" -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Run the full suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Smoke test the full bulk flow**

Boot the server. Force drift on two bookings (give yourself 2 eligible items). Visit itinerary → Review drift → Resync N unchanged → click the big submit button.

Confirm:
- Lands on drift review home with success flash "Resynced 2 items..."
- Drift count is now 0
- "Nothing's out of sync" message

Stop the server.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: bulk-resync POST applies eligible items in one transaction"
```

---

## Task 9: End-to-end manual smoke test

A final walkthrough to confirm the whole feature hangs together. No new code — exercise the UI as a real user would.

- [ ] **Step 1: Set up drift scenarios**

Boot the server:

```bash
.venv/bin/python app.py
```

Open the trip. In the DB, force drift on three different bookings so you have:
1. A drifting flight (eligible — booking still suggests this item)
2. An orphaned hotel check-out (booking's `end_datetime` cleared so check-out is no longer auto-generated)
3. Another drifting restaurant (eligible)

You can mutate via this snippet (adjust to your data):

```bash
.venv/bin/python -c "
from app import app
from models import Booking, db
with app.app_context():
    b = Booking.query.filter_by(type='flight').first()
    if b: b.vendor = 'TEST DRIFT FLIGHT'
    b2 = Booking.query.filter_by(type='hotel').first()
    if b2: b2.end_datetime = None
    b3 = Booking.query.filter_by(type='restaurant').first()
    if b3: b3.title = 'TEST DRIFT REST'
    db.session.commit()
    print('Mutated bookings.')
"
```

- [ ] **Step 2: Walk the entry points**

Visit the itinerary page. Confirm:
- Trip banner shows "3 itinerary items out of sync..." with a "Review all drift →" link
- "Review drift" amber-outlined button next to "Add item" in the page header
- The per-item amber pills are still on each drifting chip (phase-1 behavior preserved)

- [ ] **Step 3: Walk the landing page**

Click "Review all drift →" from the banner. Confirm:
- Landing page renders
- Count message reads: "3 items out of sync. 2 can be auto-resynced. 1 needs individual review."
- "Start review →" CTA visible
- "Resync 2 unchanged" CTA visible
- "Still needs review" list at the bottom shows the orphaned hotel check-out item

- [ ] **Step 4: Walk the wizard**

Click "Start review →". Confirm:
- Lands on the first drifting item (chronologically)
- "Item 1 of 3" in the breadcrumb and heading
- Diff table renders correctly
- Buttons: Resync to booking, Keep mine, Unlink from booking, Skip →, Back to itinerary

Click "Skip →". Confirm: advances to "Item 2 of 3".

Click "Resync to booking". Confirm:
- Success flash mentions "Resynced ..."
- Advances to "Item 3 of 3" (since one of the originally-3 is now resolved, the wizard's progress shows the still-drifting items; the actioned item drops out of the list)

Note on expected progress numbers: after the first Resync, the wizard recomputes drifting items, so progress may now show "Item 2 of 2" rather than "Item 3 of 3" — both are correct depending on which item you actioned. The key check is monotonic forward progress.

On the last item, click "Skip → done" (label changes because there's no next). Confirm: lands on the drift review home.

- [ ] **Step 5: Walk the bulk flow**

From the landing page (still showing the remaining items), click "Resync N unchanged". Confirm:
- Confirmation page shows each eligible item with its diff table
- "Resync these N items" submit button
- Cancel link returns to landing

Click submit. Confirm:
- Lands on drift review home
- Success flash "Resynced N items..."
- Only the orphaned item remains (drift count = 1)
- Resync-all button is gone (no more eligible items)

Click into the orphaned item from "Still needs review". Confirm:
- Wizard step renders with the "Booking no longer suggests this" message
- Only Unlink (and Back) buttons visible (no Resync / Keep — orphans can't be resynced)

Click Unlink. Confirm: lands on drift review home with "Nothing's out of sync".

- [ ] **Step 6: Walk the empty state**

Refresh `/trips/<id>/itinerary/drift-review` directly. Confirm: shows "Nothing's out of sync right now" with a "Back to itinerary" button. No CTAs.

Visit the itinerary page. Confirm: no banner, no "Review drift" button — clean state.

Stop the server.

- [ ] **Step 7: Final test run**

```bash
.venv/bin/pytest -v
```

Expected: every test passes — the original 197 from before phase 1, the phase-1 additions, and the phase-2 additions from this plan.

- [ ] **Step 8: No commit needed**

Step 9 has no code changes. If everything works, the feature is done. If anything is off, fix it in a follow-up commit with a clear message.

---

## Done. Next sessions

When phase 2 ships, the remaining phases sketched in the phase-1 plan still stand:

- **Phase 3 — Smart preservation** — Per-field tracking (`auto_fields_touched`) so resync only touches fields the user hasn't customized. Plus "new items available" prompts when a booking change generates additional slots.
- **Phase 4 — Polish** — Animations, dashboard tile indicator, keyboard shortcuts.

Each phase remains a separate plan file.

# Trip Duplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any user with read access to a trip create their own copy of it as a brand-new trip — bookings, itinerary items, and packing items copied with dates shifted, collaborators dropped, status reset to "planning."

**Architecture:** Add one pure-Python module `src/trip_cloning.py` with four small helpers (one per row type — trip / booking / itinerary item / packing item) that take a source row + new-trip context and return a dict of kwargs for the new row. The new route in `app.py` orchestrates: load source, build new Trip, flush for ID, loop through children using the helpers, commit. No SQLAlchemy logic inside the helpers — they're pure and unit-testable like every other helper in `src/`.

**Tech Stack:** Python 3.9, Flask, SQLAlchemy (via `db.session`), Jinja2 templates, pytest. No new dependencies.

---

## Background (read this first)

Before starting, read these files so the patterns are in your head:

- [models.py](../../../models.py) — the four tables this feature touches: `Trip`, `Booking`, `ItineraryItem`, `PackingItem`. Note `Trip.collaborators` (which we will NOT copy) and `ItineraryItem.linked_booking_id` (which needs remapping).
- [src/packing.py](../../../src/packing.py) — the style of pure helper this plan adopts: typed, small, well-named.
- [app.py:486-524](../../../app.py) — `trip_new()` route. The duplication route follows the same shape: parse form → build Trip → flush → seed children → commit → redirect.
- [tests/test_packing.py](../../../tests/test_packing.py) — the test style this plan adopts: dataclass-based fake row objects (`FakeItem`) standing in for SQLAlchemy rows, so the pure helpers can be tested without a database.

Key rule already documented in [CLAUDE.md](../../../CLAUDE.md): we do NOT regenerate itinerary items from bookings on duplication. We copy itinerary items directly and remap `linked_booking_id` via a dict. Otherwise we'd produce duplicate Depart/Arrive chips on top of the user's existing items.

---

## File structure

**Create:**

- `src/trip_cloning.py` — four pure helpers: `clone_trip_fields`, `clone_booking`, `clone_itinerary_item`, `clone_packing_item`.
- `tests/test_trip_cloning.py` — unit tests for each helper, using `FakeRow` dataclasses (no DB).
- `templates/trip_duplicate.html` — small form: new name (optional) + new start date.

**Modify:**

- `app.py` — add `trip_duplicate()` route handling GET (form) + POST (perform copy).
- `templates/trip_overview.html` — add a "Duplicate this trip" button.

**Do not modify:**

- `models.py` — this feature adds no schema changes.
- Any test file other than the new `tests/test_trip_cloning.py`.

---

## Task 1: `clone_booking` helper

The simplest helper to start with — no foreign-key remapping needed.

**Files:**

- Create: `src/trip_cloning.py`
- Create: `tests/test_trip_cloning.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_trip_cloning.py` with:

```python
"""Unit tests for src/trip_cloning.py."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from src.trip_cloning import clone_booking


@dataclass
class FakeBooking:
    """Stand-in for a Booking row — only the fields the cloner reads."""

    id: int
    type: str = "other"
    title: str = ""
    vendor: Optional[str] = None
    confirmation_number: Optional[str] = None
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    location: Optional[str] = None
    cost: Optional[float] = None
    currency: str = "USD"
    url: Optional[str] = None
    notes: Optional[str] = None


def test_clone_booking_shifts_datetimes_by_day_offset():
    src = FakeBooking(
        id=7,
        type="flight",
        title="MSP → OSL",
        vendor="Delta",
        start_datetime=datetime(2026, 8, 17, 14, 30),
        end_datetime=datetime(2026, 8, 18, 6, 45),
    )
    result = clone_booking(src, day_offset=timedelta(days=10))
    assert result["start_datetime"] == datetime(2026, 8, 27, 14, 30)
    assert result["end_datetime"] == datetime(2026, 8, 28, 6, 45)


def test_clone_booking_preserves_non_date_fields():
    src = FakeBooking(
        id=7,
        type="hotel",
        title="Grand Hotel",
        vendor="Hilton",
        location="Oslo",
        cost=199.50,
        currency="NOK",
        url="https://example.com",
        notes="Late check-in",
    )
    result = clone_booking(src, day_offset=timedelta(days=0))
    assert result["type"] == "hotel"
    assert result["title"] == "Grand Hotel"
    assert result["vendor"] == "Hilton"
    assert result["location"] == "Oslo"
    assert result["cost"] == 199.50
    assert result["currency"] == "NOK"
    assert result["url"] == "https://example.com"
    assert result["notes"] == "Late check-in"


def test_clone_booking_clears_confirmation_number():
    src = FakeBooking(id=7, title="Flight", confirmation_number="ABC123")
    result = clone_booking(src, day_offset=timedelta(days=0))
    assert result["confirmation_number"] is None


def test_clone_booking_handles_none_datetimes():
    src = FakeBooking(id=7, title="Loose end", start_datetime=None, end_datetime=None)
    result = clone_booking(src, day_offset=timedelta(days=30))
    assert result["start_datetime"] is None
    assert result["end_datetime"] is None


def test_clone_booking_does_not_include_id_or_trip_id():
    src = FakeBooking(id=7, title="Flight")
    result = clone_booking(src, day_offset=timedelta(days=0))
    assert "id" not in result
    assert "trip_id" not in result
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_trip_cloning.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.trip_cloning'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/trip_cloning.py`:

```python
"""
src/trip_cloning.py

Pure helpers for trip duplication. Each helper takes a source row (or
plain object exposing the same attributes) plus the duplication context
and returns a dict of kwargs suitable for constructing the new row.

No DB, no Flask imports. Foreign-key plumbing (trip_id, remapped
linked_booking_id) is supplied by the caller in app.py.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _shift(dt: Optional[datetime], offset: timedelta) -> Optional[datetime]:
    """Shift a datetime by offset; pass through None unchanged."""
    if dt is None:
        return None
    return dt + offset


def clone_booking(source, day_offset: timedelta) -> Dict[str, Any]:
    """Build kwargs for a new Booking row that copies `source`.

    `start_datetime` and `end_datetime` are shifted by `day_offset`.
    `confirmation_number` is cleared (specific to the original
    reservation). `id` and `trip_id` are excluded — caller sets them.
    """
    return {
        "type": source.type,
        "title": source.title,
        "vendor": source.vendor,
        "confirmation_number": None,
        "start_datetime": _shift(source.start_datetime, day_offset),
        "end_datetime": _shift(source.end_datetime, day_offset),
        "location": source.location,
        "cost": source.cost,
        "currency": source.currency,
        "url": source.url,
        "notes": source.notes,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_trip_cloning.py -v`

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/trip_cloning.py tests/test_trip_cloning.py
git commit -m "feat: add clone_booking helper for trip duplication"
```

---

## Task 2: `clone_itinerary_item` helper

Handles the date shift plus `linked_booking_id` remapping via a dict the caller passes in.

**Files:**

- Modify: `src/trip_cloning.py`
- Modify: `tests/test_trip_cloning.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trip_cloning.py`:

```python
from src.trip_cloning import clone_itinerary_item


@dataclass
class FakeItineraryItem:
    """Stand-in for an ItineraryItem row."""

    id: int
    day_date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    title: str = ""
    category: str = "other"
    location: Optional[str] = None
    notes: Optional[str] = None
    order_within_day: int = 0
    linked_booking_id: Optional[int] = None


def test_clone_itinerary_item_shifts_day_date():
    src = FakeItineraryItem(id=3, day_date=date(2026, 8, 17), title="Walk Akershus")
    result = clone_itinerary_item(src, day_offset=timedelta(days=10), booking_id_map={})
    assert result["day_date"] == date(2026, 8, 27)


def test_clone_itinerary_item_preserves_times_and_other_fields():
    src = FakeItineraryItem(
        id=3,
        day_date=date(2026, 8, 17),
        start_time=time(9, 30),
        end_time=time(11, 0),
        title="Akershus Fortress",
        category="sightseeing",
        location="Oslo, Norway",
        notes="Free entry",
        order_within_day=2,
    )
    result = clone_itinerary_item(src, day_offset=timedelta(days=0), booking_id_map={})
    assert result["start_time"] == time(9, 30)
    assert result["end_time"] == time(11, 0)
    assert result["title"] == "Akershus Fortress"
    assert result["category"] == "sightseeing"
    assert result["location"] == "Oslo, Norway"
    assert result["notes"] == "Free entry"
    assert result["order_within_day"] == 2


def test_clone_itinerary_item_remaps_linked_booking_id():
    src = FakeItineraryItem(id=3, day_date=date(2026, 8, 17), linked_booking_id=42)
    result = clone_itinerary_item(
        src, day_offset=timedelta(days=0), booking_id_map={42: 999}
    )
    assert result["linked_booking_id"] == 999


def test_clone_itinerary_item_unmapped_linked_booking_falls_back_to_none():
    # If a linked_booking_id isn't in the map (shouldn't happen in normal
    # flow but defensive coding for partial data), drop the link.
    src = FakeItineraryItem(id=3, day_date=date(2026, 8, 17), linked_booking_id=42)
    result = clone_itinerary_item(
        src, day_offset=timedelta(days=0), booking_id_map={}
    )
    assert result["linked_booking_id"] is None


def test_clone_itinerary_item_handles_no_link():
    src = FakeItineraryItem(id=3, day_date=date(2026, 8, 17), linked_booking_id=None)
    result = clone_itinerary_item(
        src, day_offset=timedelta(days=0), booking_id_map={}
    )
    assert result["linked_booking_id"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_trip_cloning.py -v`

Expected: 5 prior tests pass, 5 new tests FAIL with `ImportError: cannot import name 'clone_itinerary_item'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/trip_cloning.py`:

```python
from datetime import date
from typing import Mapping


def clone_itinerary_item(
    source,
    day_offset: timedelta,
    booking_id_map: Mapping[int, int],
) -> Dict[str, Any]:
    """Build kwargs for a new ItineraryItem row that copies `source`.

    `day_date` is shifted by `day_offset` (a timedelta of whole days).
    `linked_booking_id` is remapped through `booking_id_map`; if the
    source link is not in the map, the new row has no link.
    """
    new_day: date = source.day_date + day_offset

    src_link = source.linked_booking_id
    new_link = booking_id_map.get(src_link) if src_link is not None else None

    return {
        "day_date": new_day,
        "start_time": source.start_time,
        "end_time": source.end_time,
        "title": source.title,
        "category": source.category,
        "location": source.location,
        "notes": source.notes,
        "order_within_day": source.order_within_day,
        "linked_booking_id": new_link,
    }
```

Note: the `from datetime import date` and `from typing import Mapping` lines are added imports — fold them into the existing imports at the top of the file rather than duplicating.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_trip_cloning.py -v`

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/trip_cloning.py tests/test_trip_cloning.py
git commit -m "feat: add clone_itinerary_item helper with booking-id remap"
```

---

## Task 3: `clone_packing_item` helper

The simplest helper — no date shifting, just field copy with `packed` reset.

**Files:**

- Modify: `src/trip_cloning.py`
- Modify: `tests/test_trip_cloning.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trip_cloning.py`:

```python
from src.trip_cloning import clone_packing_item


@dataclass
class FakePackingItem:
    """Stand-in for a PackingItem row."""

    id: int
    name: str
    category: str = "other"
    packed: bool = False
    notes: Optional[str] = None


def test_clone_packing_item_copies_fields():
    src = FakePackingItem(id=1, name="Passport", category="documents", notes="6mo valid")
    result = clone_packing_item(src)
    assert result["name"] == "Passport"
    assert result["category"] == "documents"
    assert result["notes"] == "6mo valid"


def test_clone_packing_item_resets_packed_to_false():
    src = FakePackingItem(id=1, name="Toothbrush", category="toiletries", packed=True)
    result = clone_packing_item(src)
    assert result["packed"] is False


def test_clone_packing_item_excludes_id_and_trip_id():
    src = FakePackingItem(id=99, name="Charger")
    result = clone_packing_item(src)
    assert "id" not in result
    assert "trip_id" not in result
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_trip_cloning.py -v`

Expected: 10 prior pass, 3 new FAIL with `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/trip_cloning.py`:

```python
def clone_packing_item(source) -> Dict[str, Any]:
    """Build kwargs for a new PackingItem row that copies `source`.

    `packed` is reset to False — the duplicate trip starts unpacked.
    """
    return {
        "name": source.name,
        "category": source.category,
        "packed": False,
        "notes": source.notes,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_trip_cloning.py -v`

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/trip_cloning.py tests/test_trip_cloning.py
git commit -m "feat: add clone_packing_item helper"
```

---

## Task 4: `clone_trip_fields` helper

The orchestration-level helper: takes the source `Trip` plus the user-supplied new name and new start date, returns kwargs for the new `Trip(...)` constructor. `owner_id` is excluded — caller sets it to `current_user.id`.

**Files:**

- Modify: `src/trip_cloning.py`
- Modify: `tests/test_trip_cloning.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trip_cloning.py`:

```python
from src.trip_cloning import clone_trip_fields


@dataclass
class FakeTrip:
    """Stand-in for a Trip row."""

    id: int
    name: str = ""
    destination: Optional[str] = None
    start_date: date = date(2026, 1, 1)
    end_date: date = date(2026, 1, 7)
    status: str = "planning"
    cover_emoji: Optional[str] = None
    primary_currency: str = "USD"
    notes: Optional[str] = None


def test_clone_trip_fields_uses_provided_name_and_start():
    src = FakeTrip(
        id=1,
        name="Scandinavia '26",
        start_date=date(2026, 8, 17),
        end_date=date(2026, 9, 5),
    )
    result = clone_trip_fields(
        src,
        new_name="Scandinavia '27",
        new_start_date=date(2027, 8, 17),
    )
    assert result["name"] == "Scandinavia '27"
    assert result["start_date"] == date(2027, 8, 17)


def test_clone_trip_fields_shifts_end_date_by_same_offset():
    src = FakeTrip(
        id=1,
        start_date=date(2026, 8, 17),
        end_date=date(2026, 9, 5),  # 19 days after start
    )
    result = clone_trip_fields(
        src, new_name="copy", new_start_date=date(2026, 9, 1)
    )
    # 15 days later → end_date moves by 15 days too → 2026-09-20
    assert result["end_date"] == date(2026, 9, 20)


def test_clone_trip_fields_resets_status_to_planning():
    src = FakeTrip(id=1, status="completed")
    result = clone_trip_fields(
        src, new_name="copy", new_start_date=date(2027, 1, 1)
    )
    assert result["status"] == "planning"


def test_clone_trip_fields_copies_destination_emoji_currency_notes():
    src = FakeTrip(
        id=1,
        destination="Norway, Sweden, Denmark",
        cover_emoji="🇳🇴",
        primary_currency="NOK",
        notes="Plan visa for Svalbard side trip",
    )
    result = clone_trip_fields(
        src, new_name="copy", new_start_date=date(2027, 1, 1)
    )
    assert result["destination"] == "Norway, Sweden, Denmark"
    assert result["cover_emoji"] == "🇳🇴"
    assert result["primary_currency"] == "NOK"
    assert result["notes"] == "Plan visa for Svalbard side trip"


def test_clone_trip_fields_excludes_id_and_owner_id():
    src = FakeTrip(id=42)
    result = clone_trip_fields(
        src, new_name="copy", new_start_date=date(2027, 1, 1)
    )
    assert "id" not in result
    assert "owner_id" not in result
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_trip_cloning.py -v`

Expected: 13 prior pass, 5 new FAIL with `ImportError`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/trip_cloning.py`:

```python
def clone_trip_fields(
    source,
    new_name: str,
    new_start_date: date,
) -> Dict[str, Any]:
    """Build kwargs for a new Trip row that copies `source`.

    `end_date` is shifted by the same number of days that `start_date`
    moved, so the duration is preserved. Status resets to "planning".
    `owner_id` is excluded — caller sets it to the current user.
    """
    day_offset: timedelta = new_start_date - source.start_date
    new_end_date: date = source.end_date + day_offset

    return {
        "name": new_name,
        "destination": source.destination,
        "start_date": new_start_date,
        "end_date": new_end_date,
        "status": "planning",
        "cover_emoji": source.cover_emoji,
        "primary_currency": source.primary_currency,
        "notes": source.notes,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_trip_cloning.py -v`

Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add src/trip_cloning.py tests/test_trip_cloning.py
git commit -m "feat: add clone_trip_fields helper"
```

---

## Task 5: Duplicate form template + GET route

Now the route layer. This task only handles GET (rendering the form). POST comes in Task 6 so we can keep each task small.

**Files:**

- Create: `templates/trip_duplicate.html`
- Modify: `app.py` (add the GET branch of `trip_duplicate` route)

- [ ] **Step 1: Create the template**

Create `templates/trip_duplicate.html`:

```jinja
{% extends "base.html" %}
{% block title %}Duplicate {{ trip.name }}{% endblock %}

{% block content %}
<div class="container py-4" style="max-width: 640px;">
  <h2 class="mb-3">Duplicate trip</h2>
  <p class="text-muted">
    This will create a new trip owned by you, copying every booking,
    itinerary item, and packing item from
    <strong>{{ trip.name }}</strong>. Dates shift by the offset between
    the old and new start date. Collaborators are not copied.
  </p>

  {% if errors %}
    <div class="alert alert-danger">
      <ul class="mb-0">
        {% for e in errors %}<li>{{ e }}</li>{% endfor %}
      </ul>
    </div>
  {% endif %}

  <form method="post">
    <div class="mb-3">
      <label for="name" class="form-label">New trip name</label>
      <input type="text" class="form-control" id="name" name="name"
             value="{{ form.name or (trip.name ~ ' (copy)') }}"
             maxlength="200">
      <div class="form-text">Leave as-is or change to anything you like.</div>
    </div>

    <div class="mb-3">
      <label for="start_date" class="form-label">New start date</label>
      <input type="date" class="form-control" id="start_date" name="start_date"
             value="{{ form.start_date or '' }}" required>
      <div class="form-text">
        End date and every booking/itinerary date shift by the same offset.
        Original trip ran {{ trip.start_date }} → {{ trip.end_date }}
        ({{ (trip.end_date - trip.start_date).days + 1 }} days).
      </div>
    </div>

    <button type="submit" class="btn btn-primary">Create copy</button>
    <a href="{{ url_for('trip_overview', trip_id=trip.id) }}"
       class="btn btn-link">Cancel</a>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 2: Add the route stub to app.py**

In `app.py`, add this route. Place it directly after `trip_edit` (around line 640 in the current file, right before `booking_new`):

```python
@app.route("/trips/<int:trip_id>/duplicate", methods=["GET", "POST"])
@login_required
def trip_duplicate(trip_id):
    """Create a new trip that copies this one, with dates shifted."""
    trip, _user_role = _trip_with_access_or_404(trip_id, role="viewer")

    if request.method == "POST":
        # Filled in by Task 6.
        abort(501)

    # GET — fresh form, pre-fill name with " (copy)" suffix.
    return render_template(
        "trip_duplicate.html",
        trip=trip,
        form={},
        errors=[],
    )
```

You'll also need `abort` in the imports — check the top of `app.py` and confirm it's already imported from `flask`. If not, add it. (It is in v1 — used by `_trip_with_access_or_404`.)

- [ ] **Step 3: Smoke-test the GET in a browser**

Start the dev server:

```bash
python app.py
```

Open `http://localhost:5002`, log in, open any existing trip. Then manually visit:

```
http://localhost:5002/trips/<TRIP_ID>/duplicate
```

Expected:
- Page renders with the form.
- Name field pre-filled with "(your trip name) (copy)".
- Start date field empty and required.
- Submitting the form returns a 501 ("Not Implemented") — that's expected; POST handler comes in the next task.

- [ ] **Step 4: Commit**

```bash
git add templates/trip_duplicate.html app.py
git commit -m "feat: scaffold trip duplicate route + form (GET only)"
```

---

## Task 6: POST handler — perform the duplication

The orchestration: validate the form, build the new trip, flush, loop through child rows using the helpers, commit, redirect.

**Files:**

- Modify: `app.py` (fill in the POST branch of `trip_duplicate`)

- [ ] **Step 1: Add a form parser for the duplicate form**

The existing `parse_trip_form` in `src/trip_helpers.py` is for the regular new/edit form and validates more fields than duplicate needs. Rather than reuse it, parse inline in the route — only two fields. Replace the `if request.method == "POST"` block in `trip_duplicate` with:

```python
    if request.method == "POST":
        from datetime import date as _date
        from src.trip_cloning import (
            clone_booking,
            clone_itinerary_item,
            clone_packing_item,
            clone_trip_fields,
        )

        errors = []
        new_name = (request.form.get("name") or "").strip()
        if not new_name:
            new_name = f"{trip.name} (copy)"
        if len(new_name) > 200:
            errors.append("Name must be 200 characters or fewer.")

        raw_start = (request.form.get("start_date") or "").strip()
        new_start_date = None
        if not raw_start:
            errors.append("New start date is required.")
        else:
            try:
                new_start_date = _date.fromisoformat(raw_start)
            except ValueError:
                errors.append("New start date is not a valid date.")

        if errors:
            return render_template(
                "trip_duplicate.html",
                trip=trip,
                form=request.form,
                errors=errors,
            )

        # Build the new Trip row.
        new_trip = Trip(
            owner_id=current_user.id,
            **clone_trip_fields(trip, new_name=new_name, new_start_date=new_start_date),
        )
        db.session.add(new_trip)
        db.session.flush()  # populate new_trip.id

        day_offset = new_trip.start_date - trip.start_date

        # Copy bookings, building old_id → new_id map for itinerary remap.
        booking_id_map = {}
        for src_b in trip.bookings:
            new_b = Booking(
                trip_id=new_trip.id,
                **clone_booking(src_b, day_offset=day_offset),
            )
            db.session.add(new_b)
            db.session.flush()
            booking_id_map[src_b.id] = new_b.id

        # Copy itinerary items using the booking_id_map for remapping.
        for src_i in trip.itinerary_items:
            new_i = ItineraryItem(
                trip_id=new_trip.id,
                **clone_itinerary_item(
                    src_i,
                    day_offset=day_offset,
                    booking_id_map=booking_id_map,
                ),
            )
            db.session.add(new_i)

        # Copy packing items.
        for src_p in trip.packing_items:
            new_p = PackingItem(
                trip_id=new_trip.id,
                **clone_packing_item(src_p),
            )
            db.session.add(new_p)

        db.session.commit()
        logger.info(
            "Duplicated trip src_id=%s -> new_id=%s for user_id=%s "
            "(bookings=%s, items=%s, packing=%s)",
            trip.id, new_trip.id, current_user.id,
            len(booking_id_map),
            len(trip.itinerary_items),
            len(trip.packing_items),
        )
        flash(f"Created a copy: “{new_trip.name}”.", "success")
        return redirect(url_for("trip_overview", trip_id=new_trip.id))
```

The `from datetime import date as _date` and `from src.trip_cloning import ...` lines should ideally move to the top of `app.py` instead of being inside the function. Move them up there as part of this edit. The inline-import form is just here so the diff is small to read.

- [ ] **Step 2: Smoke-test the POST in a browser**

Restart the dev server:

```bash
python app.py
```

Test the happy path:
1. Log in. Open a trip you've populated (the Scandinavia '26 trip from `scripts/load_scandinavia.py` is ideal — it has ~24 bookings, lots of itinerary items, and the default packing list).
2. Visit `/trips/<id>/duplicate`.
3. Pick a new start date (e.g., 6 months from the original).
4. Submit.

Expected:
- Redirected to the new trip's overview page.
- New trip name ends with " (copy)" if you didn't change it.
- New trip's start date is what you entered; end date is shifted by the same offset.
- New trip's status is "planning."
- Bookings list shows the same bookings, with confirmation numbers blank.
- Itinerary shows the same items on the shifted days, with the Depart/Arrive chips still linked to their (new) bookings.
- Packing list shows the defaults, all unchecked even if you'd checked some on the source trip.
- No collaborators on the new trip.

Test the error paths:
1. Submit with an empty start date → "New start date is required."
2. Submit with `2026-13-45` (via DevTools removing the date picker constraint, or curl) → "New start date is not a valid date."
3. Submit a 250-character name → "Name must be 200 characters or fewer."

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: implement trip duplicate POST handler"
```

---

## Task 7: Add the "Duplicate" button to the trip overview

The feature is now functional via direct URL. Make it discoverable.

**Files:**

- Modify: `templates/trip_overview.html`

- [ ] **Step 1: Find the right spot in trip_overview.html**

Open `templates/trip_overview.html`. Find the header area near the top with the trip name and existing action buttons (Edit, Share). It's usually a `.d-flex` row of buttons.

- [ ] **Step 2: Add the Duplicate button**

Add this anchor inside that button row, alongside the existing Edit and Share buttons. Anyone with `viewer` role or higher can see the button — no role check needed because the route itself allows viewer access:

```jinja
<a href="{{ url_for('trip_duplicate', trip_id=trip.id) }}"
   class="btn btn-outline-secondary btn-sm">
  Duplicate
</a>
```

- [ ] **Step 3: Smoke-test in a browser**

Reload an existing trip overview page.

Expected:
- A "Duplicate" button appears alongside Edit / Share.
- Clicking it navigates to the duplicate form.
- Submitting the form creates the new trip and redirects.
- Log in as a different user who is a *viewer* on the trip — they also see the Duplicate button and it works for them (creating a copy owned by *them*).

- [ ] **Step 4: Commit**

```bash
git add templates/trip_overview.html
git commit -m "feat: add Duplicate button to trip overview page"
```

---

## Final verification

After all 7 tasks are committed, run:

```bash
pytest tests/
```

Expected: all 197 existing tests still pass + 18 new tests from `tests/test_trip_cloning.py` = 215 passed.

Then update the roadmap. In `docs/PHASE_2_ROADMAP.md`, change the status table row for "Trip duplication" from `not started` to `✓ shipped 2026-MM-DD` and commit:

```bash
git add docs/PHASE_2_ROADMAP.md
git commit -m "docs: mark trip duplication as shipped in phase-2 roadmap"
```

When ready to merge to `main`:

```bash
git switch main
git merge phase-2
git push
git switch phase-2
```

(Or open a PR on GitHub if you'd prefer the diff-review flow.)

---

## What's intentionally NOT in this plan

- **A "Duplicate" link on the trips-list page.** The button on the overview is enough for v1. Adding a second entry point doubles the surface area for no real win.
- **Choosing collaborators to carry over.** v1 drops all collaborators. Users can re-add via the existing Share UI.
- **Copying documents.** Phase 2 feature #2 isn't built yet — when it is, the duplication route gets one extra "do nothing with documents" comment (the roadmap calls this out).
- **Copying the trip's primary currency to USD on copy.** We keep it as-is; if you copy a Norway trip, the currency stays NOK — that's almost always what you want.
- **Smart date-shifting that respects holidays / weekends.** The plain offset is correct for v1. A traveler who wants to align to a specific Saturday can manually adjust each booking afterward.

# Booking ↔ Itinerary Drift Detection — Phase 1 MVP

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a booking is edited, surface the resulting drift on its linked itinerary items in the UI and let the user resync, keep their version, or unlink — instead of silently letting the two go out of sync (today's behavior).

**Architecture:** Two new columns on `ItineraryItem` track auto-shape (`auto_kind`) and whether the user has customized the item (`customized_by_user`). A pure helper `detect_drift(item, booking)` compares the stored item to what the auto-generator would produce now and returns a structured report. The itinerary view annotates each linked item with its drift state and renders a pill + (on click) a detail page with three explicit actions: Resync, Keep mine, Unlink.

**Tech Stack:** Python 3.9, Flask, Flask-SQLAlchemy, Jinja2, Bootstrap 5, pytest. No new dependencies.

**Out of scope for phase 1** (deferred to later phases):
- Per-field preservation on resync (we resync all fields at once)
- "New items available" prompts when a booking change would generate additional items
- Dashboard tile drift indicator
- Animations / transitions on the resync action

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `models.py` | Modify | Add `customized_by_user` and `auto_kind` columns to `ItineraryItem` |
| `app.py` | Modify | Add `_ensure_drift_columns()` migration; pass auto_kind through `booking_new`; mark `customized_by_user=True` in `itinerary_edit`; add 3 new POST routes + 1 GET route; annotate drift on `trip_itinerary` |
| `src/booking_helpers.py` | Modify | Add `auto_kind` to each returned dict in `auto_itinerary_items_for_booking`; add `FieldDrift`, `DriftReport`, `detect_drift()` |
| `templates/trip_itinerary.html` | Modify | Add drift pill on item chips; add trip-level banner |
| `templates/itinerary_drift.html` | Create | Drift detail page with diff table and 3 action buttons |
| `static/css/app.css` | Modify | Drift pill + banner styles |
| `tests/test_booking_helpers.py` | Modify | Tests for `auto_kind` in generated dicts |
| `tests/test_drift.py` | Create | Tests for `detect_drift()` pure helper |
| `tests/test_routes.py` | Create | Integration tests for delete cascade, resync/keep/unlink routes |
| `scripts/backfill_auto_kind.py` | Create | One-off script to set `auto_kind` on legacy linked items |

---

## Task 1: Add schema columns + safe migration

We need two new columns on `ItineraryItem`. Because the app uses `db.create_all()` (no Alembic), we add a small idempotent migration helper that runs at startup and adds columns to existing SQLite/Postgres tables if missing.

**Files:**
- Modify: `models.py` (add columns to `ItineraryItem`)
- Modify: `app.py:143-146` (run migration before `db.create_all` returns, after `db.init_app`)

- [ ] **Step 1: Add the two columns to `ItineraryItem`**

In `models.py`, find the `ItineraryItem` class. Just below the existing `linked_booking_id` column (around line 164-166), add:

```python
    # When this item was auto-spawned from a booking, this records which
    # "slot" it was: depart/arrive/check_in/check_out/pickup/return/single.
    # NULL for stand-alone items and for legacy linked items predating
    # this column.
    auto_kind = db.Column(db.String(20), nullable=True)

    # Flips to True the first time a user edits this item via the
    # itinerary form, or when they click "Keep mine" on the drift card.
    # When True, drift detection is silenced for this item.
    customized_by_user = db.Column(db.Boolean, nullable=False, default=False)
```

- [ ] **Step 2: Add the migration helper in `app.py`**

In `app.py`, just before the existing `db.init_app(app)` block (around line 143), add this helper function:

```python
def _ensure_drift_columns() -> None:
    """
    Add the auto_kind + customized_by_user columns to itinerary_item if
    they don't exist yet. SQLite + Postgres both accept the ANSI
    ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` since Postgres 9.6 and
    SQLite 3.35. We swallow OperationalError so a re-run on already-
    migrated DBs is a no-op (older SQLite without IF NOT EXISTS).
    """
    from sqlalchemy import text
    statements = [
        "ALTER TABLE itinerary_item ADD COLUMN auto_kind VARCHAR(20)",
        "ALTER TABLE itinerary_item ADD COLUMN customized_by_user BOOLEAN NOT NULL DEFAULT 0",
    ]
    with db.engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                logger.info("Migration: applied %s", stmt)
            except Exception as e:
                # Column already exists, or DB is mid-create — both fine.
                logger.debug("Migration skipped (%s): %s", stmt, e)
```

- [ ] **Step 3: Wire the migration into startup**

In `app.py`, modify the existing startup block from:

```python
db.init_app(app)
with app.app_context():
    db.create_all()
    logger.info("Database schema ensured")
```

to:

```python
db.init_app(app)
with app.app_context():
    db.create_all()
    _ensure_drift_columns()
    logger.info("Database schema ensured")
```

- [ ] **Step 4: Boot the app and confirm migration ran**

Run:

```bash
cd "/Users/jeff_s/Projects/Vacation Planner"
.venv/bin/python -c "from app import app; print('boot ok')"
```

Expected: prints `boot ok` with a log line `Migration: applied ALTER TABLE itinerary_item ADD COLUMN auto_kind VARCHAR(20)` (first run) or `Migration skipped` (second run).

Then run it a second time to confirm idempotency:

```bash
.venv/bin/python -c "from app import app; print('boot ok')"
```

Expected: `boot ok`, no failures.

- [ ] **Step 5: Commit**

```bash
git add models.py app.py
git commit -m "feat: add auto_kind and customized_by_user columns for drift detection"
```

---

## Task 2: Tag generated items with `auto_kind`

The auto-generator already produces items for flights, hotels, cars, restaurants, activities. We add a stable `auto_kind` to each so drift detection can match an existing item back to its slot.

**Files:**
- Modify: `src/booking_helpers.py:215-348` (the `auto_itinerary_items_for_booking` function)
- Modify: `tests/test_booking_helpers.py` (extend existing tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_booking_helpers.py` (use the same test style as the existing tests in that file):

```python
def test_auto_kind_set_for_flight():
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=datetime(2026, 6, 1, 14, 0),
                        location=None)
    items = auto_itinerary_items_for_booking(b)
    assert [it["auto_kind"] for it in items] == ["depart", "arrive"]


def test_auto_kind_set_for_hotel():
    b = SimpleNamespace(type="hotel", title="Hilton", vendor="Hilton",
                        start_datetime=datetime(2026, 6, 1, 15, 0),
                        end_datetime=datetime(2026, 6, 3, 11, 0),
                        location=None)
    items = auto_itinerary_items_for_booking(b)
    assert [it["auto_kind"] for it in items] == ["check_in", "check_out"]


def test_auto_kind_set_for_car():
    b = SimpleNamespace(type="car", title="Hertz", vendor="Hertz",
                        start_datetime=datetime(2026, 6, 1, 9, 0),
                        end_datetime=datetime(2026, 6, 5, 17, 0),
                        location=None)
    items = auto_itinerary_items_for_booking(b)
    assert [it["auto_kind"] for it in items] == ["pickup", "return"]


def test_auto_kind_set_for_restaurant():
    b = SimpleNamespace(type="restaurant", title="Noma", vendor="Noma",
                        start_datetime=datetime(2026, 6, 1, 19, 0),
                        end_datetime=None, location=None)
    items = auto_itinerary_items_for_booking(b)
    assert items[0]["auto_kind"] == "single"


def test_auto_kind_set_for_activity():
    b = SimpleNamespace(type="activity", title="Museum", vendor=None,
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=None, location=None)
    items = auto_itinerary_items_for_booking(b)
    assert items[0]["auto_kind"] == "single"
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run:

```bash
.venv/bin/pytest tests/test_booking_helpers.py -k auto_kind -v
```

Expected: 5 tests FAIL with `KeyError: 'auto_kind'`.

- [ ] **Step 3: Update `auto_itinerary_items_for_booking` to set `auto_kind`**

In `src/booking_helpers.py`, find each `out.append({...})` call inside `auto_itinerary_items_for_booking`. Add an `"auto_kind"` key to each dict. The exact mapping:

| Booking type / which item | auto_kind value |
|---|---|
| flight, start_dt branch | `"depart"` |
| flight, end_dt branch | `"arrive"` |
| hotel, start_dt branch | `"check_in"` |
| hotel, end_dt branch | `"check_out"` |
| car, start_dt branch | `"pickup"` |
| car, end_dt branch | `"return"` |
| restaurant | `"single"` |
| activity | `"single"` |

For example, the flight depart branch becomes:

```python
if start_dt is not None:
    out.append({
        "title": _auto_title("Depart", label),
        "category": "transit",
        "day_date": start_dt.date(),
        "start_time": start_dt.time(),
        "end_time": None,
        "location": location,
        "notes": None,
        "auto_kind": "depart",
    })
```

Apply the same pattern to all 8 append sites.

- [ ] **Step 4: Run the auto_kind tests**

Run:

```bash
.venv/bin/pytest tests/test_booking_helpers.py -k auto_kind -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Run the full booking_helpers test file to confirm no regressions**

Run:

```bash
.venv/bin/pytest tests/test_booking_helpers.py -v
```

Expected: all tests PASS (the existing ones still work because they don't assert on dict shape).

- [ ] **Step 6: Commit**

```bash
git add src/booking_helpers.py tests/test_booking_helpers.py
git commit -m "feat: tag generated itinerary items with auto_kind"
```

---

## Task 3: Persist `auto_kind` from `booking_new`

The new column is set, the helper produces it — now the route needs to pass it through to the `ItineraryItem` constructor.

**Files:**
- Modify: `app.py:677-681` (the `db.session.add(ItineraryItem(...))` call in `booking_new`)

- [ ] **Step 1: Update the constructor call in `booking_new`**

In `app.py`, find this block (around line 677) inside `booking_new`:

```python
db.session.add(ItineraryItem(
    trip_id=trip.id,
    linked_booking_id=booking.id,
    **item_data,
))
```

This already passes `**item_data`, which now includes `auto_kind` (from Task 2). **No code change required** — but verify by reading the surrounding code that `auto_kind` is a valid column name on `ItineraryItem` (it is, from Task 1) and that nothing strips it before this call (nothing does).

If you find the dict is stripped somewhere, add `auto_kind=item_data["auto_kind"]` explicitly. Otherwise, the `**item_data` splat handles it.

- [ ] **Step 2: Smoke test the route via the dev server**

Start the server:

```bash
.venv/bin/python app.py
```

In a browser, log in, pick a trip, click "Add booking", fill in a flight with both datetimes, and submit. Then check the DB:

```bash
.venv/bin/python -c "
from app import app
from models import ItineraryItem
with app.app_context():
    for it in ItineraryItem.query.filter(ItineraryItem.linked_booking_id.isnot(None)).order_by(ItineraryItem.id.desc()).limit(4):
        print(it.id, it.title, 'auto_kind=', it.auto_kind)
"
```

Expected: the two most-recent linked items have `auto_kind='depart'` and `auto_kind='arrive'`.

Stop the server with Ctrl+C.

- [ ] **Step 3: Commit (if any code changed in Step 1)**

If you needed to add an explicit `auto_kind=...` argument:

```bash
git add app.py
git commit -m "feat: persist auto_kind when spawning linked itinerary items"
```

If no code changed, skip this step.

---

## Task 4: Implement `detect_drift` pure helper

Pure helper compares an existing item against what its booking would auto-generate now. Returns a structured drift report (or None if in-sync, or None if drift is silenced).

**Files:**
- Modify: `src/booking_helpers.py` (add dataclasses + function at the bottom)
- Create: `tests/test_drift.py`

- [ ] **Step 1: Write the failing tests in `tests/test_drift.py`**

Create the new file `tests/test_drift.py`:

```python
"""Tests for detect_drift — compares a stored itinerary item against
what its linked booking would auto-generate now."""

from datetime import date, datetime, time
from types import SimpleNamespace

from src.booking_helpers import DriftReport, detect_drift


def _item(**overrides):
    """Convenience: build a stand-in itinerary item with sensible defaults."""
    base = dict(
        linked_booking_id=1,
        auto_kind="depart",
        customized_by_user=False,
        title="Depart United",
        category="transit",
        day_date=date(2026, 6, 1),
        start_time=time(10, 0),
        end_time=None,
        location=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _flight():
    return SimpleNamespace(
        type="flight", title="UA101", vendor="United",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        end_datetime=datetime(2026, 6, 1, 14, 0),
        location=None,
    )


def test_in_sync_returns_none():
    assert detect_drift(_item(), _flight()) is None


def test_no_linked_booking_returns_none():
    assert detect_drift(_item(linked_booking_id=None), _flight()) is None


def test_customized_by_user_returns_none():
    # Booking dates changed, but user has marked the item as customized.
    item = _item(customized_by_user=True, day_date=date(2026, 1, 1))
    assert detect_drift(item, _flight()) is None


def test_legacy_item_without_auto_kind_returns_none():
    item = _item(auto_kind=None, day_date=date(2026, 1, 1))
    assert detect_drift(item, _flight()) is None


def test_day_change_detected():
    item = _item(day_date=date(2026, 6, 2))  # booking now says Jun 1
    report = detect_drift(item, _flight())
    assert isinstance(report, DriftReport)
    assert report.is_orphaned is False
    fields = {f.field: (f.current, f.would_be) for f in report.fields}
    assert fields["day_date"] == (date(2026, 6, 2), date(2026, 6, 1))


def test_title_change_detected():
    item = _item(title="Depart Delta")  # booking says United
    report = detect_drift(item, _flight())
    fields = {f.field for f in report.fields}
    assert "title" in fields


def test_orphaned_when_booking_no_longer_generates_kind():
    # Booking had an end_datetime so it generated arrive. Now the user
    # cleared end_datetime, so no "arrive" item would be generated.
    flight_no_end = SimpleNamespace(
        type="flight", title="UA101", vendor="United",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        end_datetime=None, location=None,
    )
    arrive_item = _item(auto_kind="arrive", title="Arrive United",
                        day_date=date(2026, 6, 1), start_time=time(14, 0))
    report = detect_drift(arrive_item, flight_no_end)
    assert report.is_orphaned is True
    assert report.fields == []


def test_has_drift_property():
    assert DriftReport(fields=[], is_orphaned=True).has_drift is True
    assert DriftReport(fields=[], is_orphaned=False).has_drift is False
```

- [ ] **Step 2: Run to confirm they fail**

Run:

```bash
.venv/bin/pytest tests/test_drift.py -v
```

Expected: all tests FAIL with `ImportError: cannot import name 'DriftReport' from 'src.booking_helpers'`.

- [ ] **Step 3: Implement `FieldDrift`, `DriftReport`, and `detect_drift` in `src/booking_helpers.py`**

Append to `src/booking_helpers.py`:

```python
# ────────────────────────────────────────────────────────────────────
# Drift detection — compares a stored ItineraryItem to what its linked
# booking would auto-generate now. Pure: no DB, no Flask.
# ────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field

# Fields we compare between a stored item and the auto-generated would-be.
_DRIFT_FIELDS: Tuple[str, ...] = (
    "title", "category", "day_date", "start_time", "end_time", "location",
)


@dataclass
class FieldDrift:
    """One field that disagrees between the stored item and the booking."""
    field: str
    current: Any   # value currently on the stored ItineraryItem
    would_be: Any  # value the auto-generator would produce now


@dataclass
class DriftReport:
    """Aggregate drift result for a single linked itinerary item."""
    fields: List[FieldDrift] = field(default_factory=list)
    is_orphaned: bool = False  # True when the booking no longer generates this slot

    @property
    def has_drift(self) -> bool:
        return self.is_orphaned or bool(self.fields)


def detect_drift(item, booking) -> Optional[DriftReport]:
    """
    Compare a stored ItineraryItem to the auto-generated would-be item
    from its linked booking. Returns:

      - None when the item is in sync, has no linked booking, has been
        marked customized_by_user, or is a legacy item without auto_kind.
      - DriftReport(is_orphaned=True) when the booking no longer
        generates an item of this auto_kind.
      - DriftReport(fields=[...]) listing every field that disagrees.

    Pure: takes any object exposing the required attributes; no DB call.
    """
    if getattr(item, "linked_booking_id", None) is None:
        return None
    if getattr(item, "customized_by_user", False):
        return None

    kind = getattr(item, "auto_kind", None)
    if kind is None:
        return None  # legacy linked item — drift not tracked

    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == kind]
    if not matches:
        return DriftReport(fields=[], is_orphaned=True)

    would_be = matches[0]
    drifts: List[FieldDrift] = []
    for f in _DRIFT_FIELDS:
        current = getattr(item, f, None)
        proposed = would_be.get(f)
        if current != proposed:
            drifts.append(FieldDrift(field=f, current=current, would_be=proposed))

    if not drifts:
        return None
    return DriftReport(fields=drifts, is_orphaned=False)
```

You also need to add `from dataclasses import dataclass, field` and ensure `Any` is in the existing `typing` import at the top. The existing import is:

```python
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
```

`Any` is already there. The `dataclasses` import is new.

- [ ] **Step 4: Run the drift tests**

Run:

```bash
.venv/bin/pytest tests/test_drift.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Run the entire test suite to catch unrelated breakage**

Run:

```bash
.venv/bin/pytest -v
```

Expected: all tests PASS, including the original 197 plus the new ones from Task 2 and Task 4.

- [ ] **Step 6: Commit**

```bash
git add src/booking_helpers.py tests/test_drift.py
git commit -m "feat: detect_drift compares stored items to their bookings"
```

---

## Task 5: Integration tests for the delete cascade

We confirmed the cascade works empirically during investigation, but there's no automated test for it. Add one now (and use the same fixture infrastructure for later route tests).

**Files:**
- Create: `tests/test_routes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_routes.py`:

```python
"""Integration tests — exercise routes + DB end-to-end with an
in-memory SQLite database. Uses Flask's test_client and a fresh DB
per test via a pytest fixture."""

from datetime import date, datetime

import pytest

from app import app as flask_app
from models import Booking, ItineraryItem, Trip, User, db


@pytest.fixture
def app():
    """Bind the app to an in-memory SQLite DB for this test."""
    flask_app.config["TESTING"] = True
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def owner(app):
    u = User(google_id="g1", email="owner@example.com", name="Owner")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def trip(app, owner):
    t = Trip(owner_id=owner.id, name="Test trip",
             start_date=date(2026, 6, 1), end_date=date(2026, 6, 10))
    db.session.add(t)
    db.session.commit()
    return t


def test_delete_booking_cascades_linked_items(app, trip):
    """Deleting a booking removes its auto-linked itinerary items."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()

    db.session.add_all([
        ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="depart", day_date=date(2026, 6, 1),
                      title="Depart UA"),
        ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="arrive", day_date=date(2026, 6, 1),
                      title="Arrive UA"),
        # A stand-alone item with no linked_booking — should survive.
        ItineraryItem(trip_id=trip.id, linked_booking_id=None,
                      day_date=date(2026, 6, 1), title="Coffee"),
    ])
    db.session.commit()

    assert ItineraryItem.query.filter_by(trip_id=trip.id).count() == 3

    db.session.delete(b)
    db.session.commit()

    remaining = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    assert len(remaining) == 1
    assert remaining[0].title == "Coffee"
    assert Booking.query.get(b.id) is None
```

- [ ] **Step 2: Run the test**

Run:

```bash
.venv/bin/pytest tests/test_routes.py -v
```

Expected: PASS. (We're testing existing behavior — the cascade was already correct, we just lacked a test.)

If it fails, the cascade is broken. Stop and investigate before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_routes.py
git commit -m "test: cover booking delete cascade for linked itinerary items"
```

---

## Task 6: `itinerary_edit` marks the item as customized

When a user manually edits a linked item (renames it, moves its day, etc.), we set `customized_by_user = True` so drift detection silences for that item.

**Files:**
- Modify: `app.py:849-884` (the `itinerary_edit` route)
- Modify: `tests/test_routes.py` (add a route test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes.py`:

```python
def test_itinerary_edit_marks_customized(app, trip, owner):
    """Editing a linked itinerary item flips customized_by_user to True."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 2, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="check_in", day_date=date(2026, 6, 2),
                         title="Check in: Hilton", category="other")
    db.session.add(item)
    db.session.commit()
    assert item.customized_by_user is False

    with flask_app.test_client() as client:
        # Bypass login by stuffing the session.
        with client.session_transaction() as sess:
            sess["_user_id"] = str(owner.id)
            sess["_fresh"] = True
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{item.id}/edit",
            data={
                "title": "Check in: Hilton (front desk)",
                "category": "other",
                "day_date": "2026-06-02",
                "start_time": "15:00",
                "end_time": "",
                "location": "",
                "notes": "",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.customized_by_user is True
    assert item.title == "Check in: Hilton (front desk)"
```

- [ ] **Step 2: Run the test to confirm it fails**

Run:

```bash
.venv/bin/pytest tests/test_routes.py::test_itinerary_edit_marks_customized -v
```

Expected: FAIL — `item.customized_by_user` is still `False` after the edit.

- [ ] **Step 3: Update `itinerary_edit`**

In `app.py`, find the `itinerary_edit` route. After the `for field, value in data.items(): setattr(item, field, value)` line and before `db.session.commit()`, add:

```python
        # If the user is editing an auto-linked item, mark it as
        # customized so drift detection silences for this item.
        if item.linked_booking_id is not None:
            item.customized_by_user = True
```

The block now looks like:

```python
        for field, value in data.items():
            setattr(item, field, value)
        if item.linked_booking_id is not None:
            item.customized_by_user = True
        db.session.commit()
```

- [ ] **Step 4: Run the test**

Run:

```bash
.venv/bin/pytest tests/test_routes.py::test_itinerary_edit_marks_customized -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: editing a linked item marks it customized_by_user"
```

---

## Task 7: Resync / Keep mine / Unlink routes

Three POST routes give the user explicit action verbs on a drifting item.

**Files:**
- Modify: `app.py` (add 3 routes — anywhere after `itinerary_delete`, around line 898)
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def _make_flight_with_arrive(trip):
    """Helper: make a flight booking + its 'arrive' linked item."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    # An "arrive" item that's drifted (wrong title — was "Arrive United",
    # but we save a stale value to simulate a booking edit).
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta",  # stale — booking now says United
                         category="transit")
    db.session.add(item)
    db.session.commit()
    return b, item


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_resync_updates_fields_from_booking(app, trip, owner):
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.title == "Arrive United"
    assert item.customized_by_user is False


def test_keep_mine_marks_customized(app, trip, owner):
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/keep-mine")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.customized_by_user is True
    assert item.title == "Arrive Delta"  # unchanged


def test_unlink_clears_linked_booking(app, trip, owner):
    b, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/unlink")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.linked_booking_id is None
    assert item.auto_kind is None
    # The booking still exists.
    assert Booking.query.get(b.id) is not None
```

- [ ] **Step 2: Run them to confirm they fail**

Run:

```bash
.venv/bin/pytest tests/test_routes.py -k "resync or keep_mine or unlink" -v
```

Expected: all 3 tests FAIL with 404 (the routes don't exist yet).

- [ ] **Step 3: Add the three routes in `app.py`**

In `app.py`, just after `itinerary_delete` (which ends around line 897), add:

```python
@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/resync", methods=["POST"])
@login_required
def itinerary_resync(trip_id, item_id):
    """Re-apply the auto-generated values from the linked booking. Editor+ only.

    Updates the drifting fields, clears customized_by_user (since the item
    is now back in auto shape), and leaves linked_booking_id intact.
    """
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    if item.linked_booking_id is None:
        flash("This item isn't linked to a booking.", "warning")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    booking = Booking.query.get(item.linked_booking_id)
    if booking is None:
        flash("The linked booking is gone — try Unlink instead.", "warning")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == item.auto_kind]
    if not matches:
        flash(
            "The booking no longer suggests this item. Use Unlink or Delete.",
            "warning",
        )
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    would_be = matches[0]
    for f in ("title", "category", "day_date", "start_time", "end_time", "location"):
        setattr(item, f, would_be.get(f))
    item.customized_by_user = False
    db.session.commit()
    logger.info("Resynced itinerary item id=%s from booking id=%s",
                item.id, booking.id)
    flash(f"Resynced “{item.title}” to the booking.", "success")
    return redirect(url_for("trip_itinerary", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/keep-mine", methods=["POST"])
@login_required
def itinerary_keep_mine(trip_id, item_id):
    """Silence drift detection for this item. Editor+ only.

    Sets customized_by_user=True without changing any fields, so the
    drift badge disappears but the booking link is preserved.
    """
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    item.customized_by_user = True
    db.session.commit()
    logger.info("Marked itinerary item id=%s as customized_by_user", item.id)
    flash(f"Kept your version of “{item.title}”.", "success")
    return redirect(url_for("trip_itinerary", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/unlink", methods=["POST"])
@login_required
def itinerary_unlink(trip_id, item_id):
    """Sever the booking link. Editor+ only.

    Sets linked_booking_id and auto_kind to NULL. The item becomes a
    plain stand-alone itinerary entry that no longer drifts.
    """
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    item.linked_booking_id = None
    item.auto_kind = None
    item.customized_by_user = False
    db.session.commit()
    logger.info("Unlinked itinerary item id=%s from its booking", item.id)
    flash(f"Unlinked “{item.title}” from its booking.", "success")
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

- [ ] **Step 4: Run the new route tests**

Run:

```bash
.venv/bin/pytest tests/test_routes.py -k "resync or keep_mine or unlink" -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Run the full test suite**

Run:

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: add resync, keep-mine, and unlink routes for linked items"
```

---

## Task 8: Annotate drift on the itinerary view + render inline badge

The `trip_itinerary` view loads items. We compute drift for each linked item, attach it to the item as a `.drift` attribute, and render an amber pill.

**Files:**
- Modify: `app.py:779-791` (the `trip_itinerary` route)
- Modify: `templates/trip_itinerary.html:44-79` (the item chip rendering)

- [ ] **Step 1: Annotate drift in the route**

In `app.py`, replace the body of `trip_itinerary` with:

```python
@app.route("/trips/<int:trip_id>/itinerary")
@login_required
def trip_itinerary(trip_id):
    """Day-by-day timeline view. Viewer+ access."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()

    # Annotate each linked item with its drift state (or None).
    # Pre-fetch all referenced bookings in one query so we don't N+1.
    linked_booking_ids = {it.linked_booking_id for it in items if it.linked_booking_id}
    bookings_by_id = {
        b.id: b for b in Booking.query.filter(Booking.id.in_(linked_booking_ids)).all()
    } if linked_booking_ids else {}

    drift_count = 0
    for it in items:
        it.drift = None
        if it.linked_booking_id and it.linked_booking_id in bookings_by_id:
            it.drift = detect_drift(it, bookings_by_id[it.linked_booking_id])
            if it.drift is not None:
                drift_count += 1

    days = group_items_by_day(items, trip.start_date, trip.end_date)
    return render_template(
        "trip_itinerary.html",
        trip=trip,
        user_role=user_role,
        days=days,
        drift_count=drift_count,
    )
```

You also need to add `detect_drift` to the import block at the top of `app.py`. Find the existing import:

```python
from src.booking_helpers import (
    BOOKING_TYPES,
    auto_itinerary_items_for_booking,
    ...
)
```

and add `detect_drift,` to the alphabetically-correct slot in that import list.

- [ ] **Step 2: Render the drift pill on each item chip**

In `templates/trip_itinerary.html`, find the item chip block (around line 44-79). Inside the chip `<div>`, just before the `{% if can_edit(user_role) %}` action block, add:

```jinja
{% if it.drift %}
  <a class="itin-drift-pill"
     href="{{ url_for('itinerary_drift', trip_id=trip.id, item_id=it.id) }}"
     title="This item is out of sync with its booking">
    <i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
    {% if it.drift.is_orphaned %}
      Booking removed this
    {% else %}
      {{ it.drift.fields | length }} field{{ '' if it.drift.fields|length == 1 else 's' }} drifted
    {% endif %}
  </a>
{% endif %}
```

(`itinerary_drift` is the route we'll add in Task 9. The link will 404 until then — that's fine, we'll wire it next.)

- [ ] **Step 3: Boot the server and look at it**

Start the server and visit a trip's itinerary page. You should see no pills yet (no drift exists), but the page should still render without errors.

```bash
.venv/bin/python app.py
```

Open `http://localhost:5002/`, log in, navigate to a trip's itinerary. Confirm the page loads without a 500 error.

To actually see a pill, briefly mutate a booking via the DB:

```bash
.venv/bin/python -c "
from app import app
from models import Booking, db
with app.app_context():
    b = Booking.query.first()
    if b and b.type == 'flight':
        b.vendor = 'TEST DRIFT'
        db.session.commit()
        print(f'Mutated booking id={b.id} vendor to TEST DRIFT')
    else:
        print('No flight booking found to mutate')
"
```

Reload the itinerary in the browser — the linked items should now show the amber pill.

(You can revert your mutation when done.)

Stop the server.

- [ ] **Step 4: Commit**

```bash
git add app.py templates/trip_itinerary.html
git commit -m "feat: surface drift on the itinerary view via an inline pill"
```

---

## Task 9: Drift detail page

The pill links to a detail page that shows the field-level diff and the three action buttons (Resync, Keep mine, Unlink).

**Files:**
- Modify: `app.py` (add `itinerary_drift` GET route — alongside the actions from Task 7)
- Create: `templates/itinerary_drift.html`

- [ ] **Step 1: Add the GET route in `app.py`**

Just before `itinerary_resync` (added in Task 7), add:

```python
@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/drift")
@login_required
def itinerary_drift(trip_id, item_id):
    """Show the drift report for a linked itinerary item. Viewer+ access."""
    trip, item, user_role = _itinerary_item_with_access_or_404(
        trip_id, item_id, role="viewer"
    )
    if item.linked_booking_id is None:
        flash("This item isn't linked to a booking.", "warning")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))
    booking = Booking.query.get(item.linked_booking_id)
    if booking is None:
        flash("The linked booking is gone — try Unlink instead.", "warning")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    drift = detect_drift(item, booking)
    return render_template(
        "itinerary_drift.html",
        trip=trip,
        item=item,
        booking=booking,
        drift=drift,
        user_role=user_role,
    )
```

- [ ] **Step 2: Create the template**

Create `templates/itinerary_drift.html`:

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
    <span class="text-muted">— linked to booking “{{ booking.title }}”</span>
  </div>

  {% if drift is none %}
    <p class="mb-0">This item is now in sync with the booking. Nothing to do.</p>
  {% elif drift.is_orphaned %}
    <p>
      The booking no longer suggests this item — for example, the
      relevant date/time on the booking was cleared.
    </p>
    <p>You can keep the item as a stand-alone entry, or delete it.</p>
  {% else %}
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
            <td class="text-muted">{{ f.field }}</td>
            <td>{{ f.current if f.current is not none else '—' }}</td>
            <td><strong>{{ f.would_be if f.would_be is not none else '—' }}</strong></td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endif %}

  {% if can_edit(user_role) %}
    <div class="d-flex gap-2 flex-wrap mt-3 pt-3 border-top">
      {% if drift is not none and not drift.is_orphaned %}
        <form method="post" action="{{ url_for('itinerary_resync', trip_id=trip.id, item_id=item.id) }}" class="m-0">
          <button class="btn btn-vp-primary" type="submit">
            <i class="bi bi-arrow-clockwise me-1" aria-hidden="true"></i>
            Resync to booking
          </button>
        </form>
        <form method="post" action="{{ url_for('itinerary_keep_mine', trip_id=trip.id, item_id=item.id) }}" class="m-0">
          <button class="btn btn-outline-secondary" type="submit">Keep mine</button>
        </form>
      {% endif %}
      <form method="post" action="{{ url_for('itinerary_unlink', trip_id=trip.id, item_id=item.id) }}" class="m-0">
        <button class="btn btn-outline-secondary" type="submit">Unlink from booking</button>
      </form>
      <a class="btn btn-link ms-auto" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">Back to itinerary</a>
    </div>
  {% endif %}
</div>
{% endblock %}
```

The project's `vp-card` is a single container with internal padding (no header/body/footer sub-classes), so we use Bootstrap's spacing utilities (`mb-3`, `border-top`) to separate the sections.

- [ ] **Step 3: Smoke-test it in the browser**

Boot the server again, force drift on a booking (as you did in Task 8), reload the itinerary page, click the amber pill on one of the linked items. Confirm the drift detail page renders correctly with the table and three buttons. Try each button (Resync should clear the drift; Keep mine should silence the pill; Unlink should drop the link).

- [ ] **Step 4: Commit**

```bash
git add app.py templates/itinerary_drift.html
git commit -m "feat: drift detail page with field diff and resync/keep/unlink actions"
```

---

## Task 10: Trip-level "N items out of sync" banner

When the itinerary page loads, if any items have drift, show a banner at the top.

**Files:**
- Modify: `templates/trip_itinerary.html` (add a banner above the day columns)

- [ ] **Step 1: Add the banner**

In `templates/trip_itinerary.html`, just after the breadcrumb `<div>` (around line 10) and before the `<div class="d-flex align-items-center justify-content-between mb-3">` heading row, add:

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

- [ ] **Step 2: Smoke-test**

Boot the server, force drift on a booking, reload the itinerary page. Confirm the banner appears at the top showing the correct count. Resync via the detail page, return to the itinerary page, confirm the banner disappears once the count is zero.

- [ ] **Step 3: Commit**

```bash
git add templates/trip_itinerary.html
git commit -m "feat: trip-level drift banner on the itinerary page"
```

---

## Task 11: Booking edit success flash mentions drift potential

After editing a booking that has linked items, the flash should hint that drift may now exist.

**Files:**
- Modify: `app.py:712-748` (the `booking_edit` route)

- [ ] **Step 1: Update the success flash**

In `app.py`, inside `booking_edit`, find:

```python
        for field, value in data.items():
            setattr(booking, field, value)
        db.session.commit()
        logger.info("Edited booking id=%s title=%r", booking.id, booking.title)
        flash("Booking updated.", "success")
        return redirect(url_for("bookings_list", trip_id=trip.id))
```

Replace it with:

```python
        for field, value in data.items():
            setattr(booking, field, value)
        db.session.commit()
        logger.info("Edited booking id=%s title=%r", booking.id, booking.title)

        linked_count = ItineraryItem.query.filter_by(
            linked_booking_id=booking.id
        ).count()
        if linked_count > 0:
            noun = "item" if linked_count == 1 else "items"
            flash(
                f"Booking updated. {linked_count} linked itinerary {noun} may now "
                f"be out of sync — check the Itinerary page.",
                "success",
            )
        else:
            flash("Booking updated.", "success")
        return redirect(url_for("bookings_list", trip_id=trip.id))
```

- [ ] **Step 2: Smoke-test**

Boot the server. Edit a booking that has linked itinerary items. Confirm the flash mentions the count and points to the Itinerary page.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: booking edit flash mentions linked items that may drift"
```

---

## Task 12: Drift pill CSS + backfill script for legacy items

Two small finishing touches.

**Files:**
- Modify: `static/css/app.css`
- Create: `scripts/backfill_auto_kind.py`

- [ ] **Step 1: Add the drift pill CSS**

Append to `static/css/app.css`:

```css
/* Drift pill — appears on itinerary chips whose linked booking has changed. */
.itin-drift-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin-top: 0.35rem;
  padding: 0.15rem 0.55rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: #8a4a00;
  background-color: #fff3cd;
  border: 1px solid #ffe69c;
  border-radius: 999px;
  text-decoration: none;
  line-height: 1.3;
}
.itin-drift-pill:hover {
  background-color: #ffe69c;
  color: #5b3000;
  text-decoration: none;
}
.itin-drift-pill .bi {
  font-size: 0.8em;
}
```

- [ ] **Step 2: Create the backfill script**

Create `scripts/backfill_auto_kind.py`:

```python
"""
scripts/backfill_auto_kind.py

One-off helper that walks every existing linked itinerary item and
fills in its auto_kind by matching the item's title prefix to the
shape the auto-generator would produce now. Skips items whose
auto_kind is already set.

Usage:
    cd "/Users/jeff_s/Projects/Vacation Planner"
    .venv/bin/python scripts/backfill_auto_kind.py

The script reports how many items it updated. It commits at the end —
if you want a dry run, pass --dry-run.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402
from models import Booking, ItineraryItem, db  # noqa: E402
from src.booking_helpers import auto_itinerary_items_for_booking  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


def backfill(dry_run: bool = False) -> int:
    updated = 0
    with app.app_context():
        candidates = ItineraryItem.query.filter(
            ItineraryItem.linked_booking_id.isnot(None),
            ItineraryItem.auto_kind.is_(None),
        ).all()
        logger.info("Found %d linked items missing auto_kind", len(candidates))

        for item in candidates:
            booking = Booking.query.get(item.linked_booking_id)
            if booking is None:
                logger.warning("Item id=%s links to gone booking id=%s — skipped",
                               item.id, item.linked_booking_id)
                continue
            would_be = auto_itinerary_items_for_booking(booking)
            best = None
            for w in would_be:
                if (w.get("title") == item.title
                        and w.get("day_date") == item.day_date):
                    best = w
                    break
            if best is None:
                logger.warning(
                    "Item id=%s title=%r — no auto_kind match in booking id=%s",
                    item.id, item.title, booking.id,
                )
                continue
            item.auto_kind = best["auto_kind"]
            updated += 1
            logger.info("Set auto_kind=%s on item id=%s", item.auto_kind, item.id)

        if dry_run:
            logger.info("DRY RUN — rolling back. Would have updated %d items.", updated)
            db.session.rollback()
        else:
            db.session.commit()
            logger.info("Committed. Updated %d items.", updated)
    return updated


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without committing.")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
```

- [ ] **Step 3: Run the backfill in dry-run mode**

Run:

```bash
.venv/bin/python scripts/backfill_auto_kind.py --dry-run
```

Expected: prints a count of candidates and which items would be updated. Nothing committed.

- [ ] **Step 4: Run the backfill for real**

```bash
.venv/bin/python scripts/backfill_auto_kind.py
```

Expected: prints "Committed. Updated N items." Then verify:

```bash
.venv/bin/python -c "
from app import app
from models import ItineraryItem
with app.app_context():
    total = ItineraryItem.query.filter(ItineraryItem.linked_booking_id.isnot(None)).count()
    missing = ItineraryItem.query.filter(
        ItineraryItem.linked_booking_id.isnot(None),
        ItineraryItem.auto_kind.is_(None)
    ).count()
    print(f'linked items: {total} — missing auto_kind: {missing}')
"
```

Expected: most/all linked items have `auto_kind` set. A small number may still be missing (e.g., items whose title was already manually edited so prefix-matching failed) — those are fine; drift detection will treat them as untracked.

- [ ] **Step 5: Final full test run**

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add static/css/app.css scripts/backfill_auto_kind.py
git commit -m "chore: drift pill styling and auto_kind backfill script"
```

---

## Done. Next sessions

When phase 1 ships and you've used it for a few real edits, evaluate which phase to do next:

- **Phase 2 — Bulk review** — A "Review all drift" flow that walks through each drifting item like a wizard, with a `Resync all unchanged` bulk button.
- **Phase 3 — Smart preservation** — Per-field tracking (`auto_fields_touched`) so resync only touches fields the user hasn't customized. Plus "new items available" prompts when a booking change generates additional slots.
- **Phase 4 — Polish** — Animations, dashboard tile indicator, keyboard shortcuts.

Each phase is a separate plan file.

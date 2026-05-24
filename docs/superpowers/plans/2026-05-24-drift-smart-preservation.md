# Drift Smart Preservation — Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Source of truth:** [`docs/superpowers/specs/2026-05-24-drift-smart-preservation-design.md`](../specs/2026-05-24-drift-smart-preservation-design.md). If a step here conflicts with the spec, the spec wins — flag it and stop.

**Goal:** Replace the whole-row `customized_by_user` flag with a per-field `auto_fields_touched` set so resync only touches fields the user hasn't customized, and surface "new items available" prompts when a booking edit creates additional auto-slots.

**Architecture:** A new TEXT column `auto_fields_touched` stores a sorted comma-separated set of field names. Two pure helpers parse/serialize it. `detect_drift` filters its comparison by the set. `itinerary_edit` records only fields that actually changed value. `_apply_resync_to_item` skips touched fields. "Keep mine" stuffs all six DRIFT_FIELDS into the set (same observable behavior as today). A new pure helper `missing_auto_kinds_for_booking` powers a new-items section on the drift review landing page, plus a flash update on booking edit, plus per-item-add and bulk-add routes.

**Tech Stack:** Python 3.9, Flask, Flask-SQLAlchemy, Jinja2, Bootstrap 5, pytest. No new dependencies.

**Out of scope** (see spec): dropping the `customized_by_user` column; persistent dismissal of new-item suggestions; UI for "untouching" a field; a new wizard step for new items; dashboard tile indicator.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `models.py` | Modify | Add `auto_fields_touched` column. Mark `customized_by_user` deprecated by comment. |
| `app.py` | Modify | Extend `_ensure_drift_columns`. Rewrite `itinerary_edit`, `_apply_resync_to_item`, `itinerary_keep_mine`, `itinerary_unlink`. Add `_annotate_new_items_for_trip` helper. Update `booking_edit` flash. Pass new context to `trip_itinerary` and `itinerary_drift_review`. Add three new routes (per-item add, bulk add confirm, bulk add POST). |
| `src/booking_helpers.py` | Modify | Add `parse_touched`, `serialize_touched`, `missing_auto_kinds_for_booking`, `NewItemSuggestion`. Rewrite `detect_drift` to per-field semantics. |
| `templates/drift_review.html` | Modify | Add "New items the booking would create" section and headline sentence. |
| `templates/drift_bulk_add_confirm.html` | Create | Bulk-add confirmation page. |
| `templates/trip_itinerary.html` | Modify | Banner copy adapts to include new-items count + Review button. |
| `tests/test_booking_helpers.py` | Modify | Tests for new pure helpers. |
| `tests/test_drift.py` | Modify | Tests for per-field drift semantics. |
| `tests/test_routes.py` | Modify | Update tests asserting on `customized_by_user`. Add integration coverage for partial-resync, new-item flash, new-item add routes. |

---

## Task 1: Schema column + migration backfill

Add the `auto_fields_touched` column. Extend the existing idempotent migration helper with one ALTER and one backfill UPDATE that translates the old whole-row flag into the equivalent "all fields touched" state.

**Files:**
- Modify: `models.py` (the `ItineraryItem` class — lines 134–180 area)
- Modify: `app.py:147-168` (the `_ensure_drift_columns` helper)

- [ ] **Step 1: Add the column to `ItineraryItem`**

In `models.py`, find the existing `customized_by_user` column declaration (around line 173–177). Replace the comment above it AND add the new column directly below it:

```python
    # DEPRECATED in phase 3: replaced by auto_fields_touched. No longer
    # read or written by application code. Column left in place for one
    # release before being dropped.
    customized_by_user = db.Column(db.Boolean, nullable=False, default=False)

    # Set of DRIFT_FIELDS the user has personally edited on this item.
    # Stored as a sorted comma-separated string (e.g. "day_date,title").
    # Empty string means nothing touched. Replaces customized_by_user.
    auto_fields_touched = db.Column(db.String(255), nullable=False, default="")
```

- [ ] **Step 2: Extend `_ensure_drift_columns`**

In `app.py`, find `_ensure_drift_columns` (around line 147). Add one more ALTER statement to the `statements` list AND add a separate backfill block after the loop.

Replace the current function with:

```python
def _ensure_drift_columns() -> None:
    """
    Add the drift-tracking columns to itinerary_item if they don't exist
    yet. SQLite + Postgres both accept the ANSI ``ALTER TABLE ... ADD
    COLUMN`` since the versions we support. We swallow OperationalError
    so a re-run on already-migrated DBs is a no-op.

    Also backfills auto_fields_touched from the deprecated
    customized_by_user flag — see the phase-3 design doc.
    """
    from sqlalchemy import text
    statements = [
        "ALTER TABLE itinerary_item ADD COLUMN auto_kind VARCHAR(20)",
        "ALTER TABLE itinerary_item ADD COLUMN customized_by_user BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE itinerary_item ADD COLUMN auto_fields_touched VARCHAR(255) NOT NULL DEFAULT ''",
    ]
    with db.engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                logger.info("Migration: applied %s", stmt)
            except Exception as e:
                # Column already exists, or DB is mid-create — both fine.
                logger.debug("Migration skipped (%s): %s", stmt, e)

        # One-time backfill: translate the deprecated customized_by_user
        # flag into the equivalent "all fields touched" state. The
        # `auto_fields_touched = ''` guard makes the UPDATE a no-op on
        # re-run. Sort order matches what serialize_touched(DRIFT_FIELDS)
        # produces.
        try:
            conn.execute(text(
                "UPDATE itinerary_item "
                "SET auto_fields_touched = 'category,day_date,end_time,location,start_time,title' "
                "WHERE customized_by_user = 1 "
                "AND (auto_fields_touched = '' OR auto_fields_touched IS NULL)"
            ))
            logger.info("Migration: backfilled auto_fields_touched from customized_by_user")
        except Exception as e:
            logger.debug("Migration backfill skipped: %s", e)
```

Note: the backfill uses `customized_by_user = 1` because SQLite stores booleans as integers. Postgres accepts `1` here too (it'll coerce to TRUE).

- [ ] **Step 3: Boot the app and confirm migration ran**

Run:

```bash
cd "/Users/jeff_s/Projects/Vacation Planner"
.venv/bin/python -c "from app import app; print('boot ok')"
```

Expected: prints `boot ok` with log lines including `Migration: applied ALTER TABLE itinerary_item ADD COLUMN auto_fields_touched ...` (first run) and `Migration: backfilled auto_fields_touched from customized_by_user`.

Run a second time to confirm idempotency:

```bash
.venv/bin/python -c "from app import app; print('boot ok')"
```

Expected: prints `boot ok`. The ALTER is skipped (logged at debug, not visible by default). The UPDATE runs but matches zero rows on re-run.

- [ ] **Step 4: Verify the backfill by hand**

```bash
.venv/bin/python -c "
from app import app
from models import ItineraryItem
with app.app_context():
    customized = ItineraryItem.query.filter_by(customized_by_user=True).all()
    print(f'{len(customized)} rows with customized_by_user=True')
    for it in customized[:5]:
        print(f'  id={it.id} auto_fields_touched={it.auto_fields_touched!r}')
"
```

Expected: every row with `customized_by_user=True` has `auto_fields_touched='category,day_date,end_time,location,start_time,title'`. If there are zero such rows, the spec-checked "intentional behavior change" simply doesn't apply to your data — fine.

- [ ] **Step 5: Commit**

```bash
git add models.py app.py
git commit -m "feat: add auto_fields_touched column with backfill from customized_by_user"
```

---

## Task 2: `parse_touched` and `serialize_touched` pure helpers

Two small pure helpers in `src/booking_helpers.py` that all the per-field logic depends on. Pure means no DB, no Flask — easy to unit-test exhaustively.

**Files:**
- Modify: `src/booking_helpers.py` (append to the drift-detection section near the bottom)
- Modify: `tests/test_booking_helpers.py` (new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_booking_helpers.py`:

```python
from src.booking_helpers import parse_touched, serialize_touched


def test_parse_touched_empty_returns_empty_set():
    assert parse_touched("") == set()


def test_parse_touched_none_returns_empty_set():
    assert parse_touched(None) == set()


def test_parse_touched_single_field():
    assert parse_touched("title") == {"title"}


def test_parse_touched_multiple_fields():
    assert parse_touched("title,day_date") == {"title", "day_date"}


def test_parse_touched_drops_unknown_field_names():
    # 'frobnicate' isn't in DRIFT_FIELDS — should be silently dropped.
    assert parse_touched("title,frobnicate,day_date") == {"title", "day_date"}


def test_parse_touched_handles_whitespace():
    assert parse_touched("title, day_date") == {"title", "day_date"}


def test_serialize_touched_empty_returns_empty_string():
    assert serialize_touched(set()) == ""


def test_serialize_touched_single_field():
    assert serialize_touched({"title"}) == "title"


def test_serialize_touched_sorts_output():
    # Input set order is non-deterministic; output must be sorted.
    assert serialize_touched({"title", "day_date"}) == "day_date,title"


def test_serialize_touched_drops_unknown_field_names():
    assert serialize_touched({"title", "frobnicate"}) == "title"


def test_serialize_touched_round_trips_with_parse():
    fields = {"title", "day_date", "location"}
    assert parse_touched(serialize_touched(fields)) == fields


def test_serialize_touched_all_drift_fields_matches_backfill_string():
    """Spec invariant: serialize_touched(DRIFT_FIELDS) must equal the
    string used by the migration backfill UPDATE."""
    from src.booking_helpers import DRIFT_FIELDS
    expected = "category,day_date,end_time,location,start_time,title"
    assert serialize_touched(DRIFT_FIELDS) == expected
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_booking_helpers.py -k "parse_touched or serialize_touched" -v
```

Expected: all 12 tests FAIL with `ImportError: cannot import name 'parse_touched' from 'src.booking_helpers'`.

- [ ] **Step 3: Implement the helpers**

In `src/booking_helpers.py`, find the existing `DRIFT_FIELDS` tuple (around line 399). Just below it (before the `FieldDrift` dataclass), add:

```python
def parse_touched(s: Optional[str]) -> "Set[str]":
    """Parse a comma-separated touched-fields string into a set.

    Unknown field names (not in DRIFT_FIELDS) are silently dropped so a
    later shrink of DRIFT_FIELDS doesn't break existing DB rows.
    """
    if not s:
        return set()
    parts = (p.strip() for p in s.split(","))
    return {p for p in parts if p in DRIFT_FIELDS}


def serialize_touched(fields: Iterable[str]) -> str:
    """Serialize a set of field names to sorted CSV. Unknown names dropped.

    Sorted output is stable for tests and human-readable in `sqlite3`.
    """
    valid = sorted(f for f in fields if f in DRIFT_FIELDS)
    return ",".join(valid)
```

You also need to add `Set` to the existing typing import at the top of the file. Find:

```python
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
```

and change it to:

```python
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple
```

Then update the `parse_touched` return type hint from the string `"Set[str]"` to the proper `Set[str]`:

```python
def parse_touched(s: Optional[str]) -> Set[str]:
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_booking_helpers.py -k "parse_touched or serialize_touched" -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Run the full booking_helpers suite to catch regressions**

```bash
.venv/bin/pytest tests/test_booking_helpers.py -v
```

Expected: every test passes.

- [ ] **Step 6: Commit**

```bash
git add src/booking_helpers.py tests/test_booking_helpers.py
git commit -m "feat: parse_touched and serialize_touched helpers for per-field tracking"
```

---

## Task 3: Per-field `detect_drift`

Rewrite `detect_drift` to filter its comparison by `auto_fields_touched`. The old `customized_by_user` short-circuit is removed — silencing is now expressed by populating the touched set.

**Files:**
- Modify: `src/booking_helpers.py:423-460` (the `detect_drift` function body)
- Modify: `tests/test_drift.py` (new tests, and remove/update obsolete ones)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_drift.py`:

```python
from src.booking_helpers import serialize_touched


def test_touched_field_is_silently_ignored():
    """If the user has touched the title, a title drift should not be flagged."""
    item = _item(title="Depart Delta",
                 auto_fields_touched=serialize_touched({"title"}))
    # Booking still says United, but user has touched the title — no drift.
    assert detect_drift(item, _flight()) is None


def test_partial_touched_still_flags_untouched_fields():
    """Touched=title; day_date differs → report has only day_date."""
    item = _item(
        title="Depart Delta",
        day_date=date(2026, 6, 5),  # booking says Jun 1
        auto_fields_touched=serialize_touched({"title"}),
    )
    report = detect_drift(item, _flight())
    assert report is not None
    fields = {f.field_name for f in report.fields}
    assert fields == {"day_date"}


def test_all_touched_returns_none():
    """auto_fields_touched contains every DRIFT_FIELD → silenced."""
    from src.booking_helpers import DRIFT_FIELDS
    item = _item(
        title="Depart Delta",
        day_date=date(2026, 1, 1),
        auto_fields_touched=serialize_touched(DRIFT_FIELDS),
    )
    assert detect_drift(item, _flight()) is None


def test_touched_set_without_actual_drift_returns_none():
    """Touched but no drifted untouched field → returns None."""
    item = _item(auto_fields_touched=serialize_touched({"title"}))
    # All fields match the booking → no drift even though title is touched.
    assert detect_drift(item, _flight()) is None
```

You also need to update the `_item` fixture at the top of the file to accept `auto_fields_touched`. Find the existing `_item` helper (around line 348) and change it to:

```python
def _item(**overrides):
    """Convenience: build a stand-in itinerary item with sensible defaults."""
    base = dict(
        linked_booking_id=1,
        auto_kind="depart",
        customized_by_user=False,
        auto_fields_touched="",
        title="Depart United",
        category="transit",
        day_date=date(2026, 6, 1),
        start_time=time(10, 0),
        end_time=None,
        location=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)
```

The existing `test_customized_by_user_returns_none` test (around line 382) becomes obsolete — the new semantics ignore `customized_by_user`. Replace it with:

```python
def test_customized_by_user_flag_is_ignored_under_per_field_model():
    """The deprecated customized_by_user flag no longer silences drift.
    Silencing is expressed by populating auto_fields_touched instead."""
    item = _item(customized_by_user=True, day_date=date(2026, 1, 1))
    report = detect_drift(item, _flight())
    assert report is not None
    fields = {f.field_name for f in report.fields}
    assert "day_date" in fields
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_drift.py -v
```

Expected: the four new tests FAIL (current detect_drift either short-circuits on customized_by_user or doesn't consult auto_fields_touched). The replaced `test_customized_by_user_flag_is_ignored_under_per_field_model` also FAILS.

- [ ] **Step 3: Rewrite `detect_drift`**

In `src/booking_helpers.py`, replace the body of `detect_drift` (current version reads `customized_by_user`) with:

```python
def detect_drift(item, booking) -> Optional[DriftReport]:
    """
    Compare a stored ItineraryItem to the auto-generated would-be item
    from its linked booking. Returns:

      - None when the item is in sync, has no linked booking, is a legacy
        item without auto_kind, or every drifted field is in auto_fields_touched.
      - DriftReport(is_orphaned=True) when the booking no longer
        generates an item of this auto_kind.
      - DriftReport(fields=[...]) listing every untouched field that disagrees.

    Pure: takes any object exposing the required attributes; no DB call.
    """
    if getattr(item, "linked_booking_id", None) is None:
        return None

    kind = getattr(item, "auto_kind", None)
    if kind is None:
        return None  # legacy linked item — drift not tracked

    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == kind]
    if not matches:
        return DriftReport(fields=[], is_orphaned=True)

    touched = parse_touched(getattr(item, "auto_fields_touched", ""))
    would_be = matches[0]
    drifts: List[FieldDrift] = []
    for f in DRIFT_FIELDS:
        if f in touched:
            continue
        current = getattr(item, f, None)
        proposed = would_be.get(f)
        if current != proposed:
            drifts.append(FieldDrift(field_name=f, current=current, would_be=proposed))

    if not drifts:
        return None
    return DriftReport(fields=drifts, is_orphaned=False)
```

- [ ] **Step 4: Run the drift tests**

```bash
.venv/bin/pytest tests/test_drift.py -v
```

Expected: all tests PASS. The new four pass, the replaced `test_customized_by_user_flag_is_ignored_under_per_field_model` passes, and the existing in-sync / no-linked / orphan tests still pass.

- [ ] **Step 5: Run the full suite to catch regressions**

```bash
.venv/bin/pytest -v
```

Expected: most tests pass, but some route tests will fail because they still assert on `customized_by_user` — those are intentional and fixed in later tasks. Note which tests fail so you can confirm them against the expected list in Tasks 4–6.

- [ ] **Step 6: Commit**

```bash
git add src/booking_helpers.py tests/test_drift.py
git commit -m "feat: detect_drift filters by auto_fields_touched (per-field)"
```

---

## Task 4: `itinerary_edit` records changed fields

Replace the blunt `customized_by_user = True` flag with a diff-then-write loop that adds only fields whose value actually changed to `auto_fields_touched`. A form submit that doesn't change any value leaves the touched set alone.

**Files:**
- Modify: `app.py:920-957` (the `itinerary_edit` route)
- Modify: `tests/test_routes.py` (rewrite one existing test, add one new test)

- [ ] **Step 1: Write the failing tests**

In `tests/test_routes.py`, find the existing `test_itinerary_edit_marks_customized` test (the spec says it lives in the file already). Rename it and rewrite it. Then append a new no-op test:

```python
def test_itinerary_edit_records_changed_fields_only(app, trip, owner):
    """Editing only the title flips just `title` in auto_fields_touched."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 2, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="check_in", day_date=date(2026, 6, 2),
                         start_time=datetime(2026, 6, 2, 15, 0).time(),
                         title="Check in: Hilton", category="other")
    db.session.add(item)
    db.session.commit()
    assert item.auto_fields_touched == ""

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{item.id}/edit",
            data={
                "title": "Check in: Hilton (front desk)",  # CHANGED
                "category": "other",                       # unchanged
                "day_date": "2026-06-02",                  # unchanged
                "start_time": "15:00",                     # unchanged
                "end_time": "",                            # unchanged
                "location": "",                            # unchanged
                "notes": "",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.auto_fields_touched == "title"
    assert item.title == "Check in: Hilton (front desk)"


def test_itinerary_edit_no_op_does_not_change_touched_set(app, trip, owner):
    """Submitting the edit form without changing anything leaves the
    auto_fields_touched set untouched."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 2, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="check_in", day_date=date(2026, 6, 2),
                         start_time=datetime(2026, 6, 2, 15, 0).time(),
                         title="Check in: Hilton", category="other",
                         auto_fields_touched="day_date")  # pre-existing touch
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{item.id}/edit",
            data={
                "title": "Check in: Hilton",
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
    # No change → touched set untouched.
    assert item.auto_fields_touched == "day_date"
```

If `test_itinerary_edit_marks_customized` exists (it should — it was added in phase 1 Task 6), delete its body and replace it with the renamed test above. If you don't find it, no harm — the new test stands on its own.

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "itinerary_edit" -v
```

Expected: the two new tests FAIL — `auto_fields_touched` is not yet set by the route.

- [ ] **Step 3: Update `itinerary_edit`**

In `app.py`, find the `itinerary_edit` route (around line 920). Replace the block:

```python
        for field, value in data.items():
            setattr(item, field, value)
        if item.linked_booking_id is not None:
            item.customized_by_user = True
        db.session.commit()
```

with:

```python
        # Compute which DRIFT_FIELDS actually changed value, BEFORE writing.
        # parse_itinerary_form returns a dict with all DRIFT_FIELDS keys
        # (title, category, day_date, start_time, end_time, location) plus
        # `notes` — so data.get(f) is safe to compare for every f in DRIFT_FIELDS.
        changed_fields: set = set()
        if item.linked_booking_id is not None:
            for f in DRIFT_FIELDS:
                if data.get(f) != getattr(item, f):
                    changed_fields.add(f)

        for field, value in data.items():
            setattr(item, field, value)

        if item.linked_booking_id is not None and changed_fields:
            prior = parse_touched(item.auto_fields_touched)
            item.auto_fields_touched = serialize_touched(prior | changed_fields)
        db.session.commit()
```

You also need to add `parse_touched` and `serialize_touched` to the existing `from src.booking_helpers import ...` block at the top of `app.py`. Find the import block (search for `from src.booking_helpers import` — it's around line 30–50) and add them in alphabetical order. The existing import likely looks like:

```python
from src.booking_helpers import (
    BOOKING_TYPES,
    DRIFT_FIELDS,
    DriftReport,
    auto_itinerary_items_for_booking,
    booking_form_values,
    detect_drift,
    parse_booking_form,
)
```

Add the two new helpers, alphabetically:

```python
from src.booking_helpers import (
    BOOKING_TYPES,
    DRIFT_FIELDS,
    DriftReport,
    auto_itinerary_items_for_booking,
    booking_form_values,
    detect_drift,
    parse_booking_form,
    parse_touched,
    serialize_touched,
)
```

(Match the exact existing surrounding imports — don't invent ones that aren't there.)

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_routes.py -k "itinerary_edit" -v
```

Expected: both new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: itinerary_edit records only fields that actually changed"
```

---

## Task 5: `_apply_resync_to_item` skips touched fields

Resync stops overwriting fields the user has personally touched, and preserves the touched set (so re-resyncing later still skips them). This is the behavior change called out in the spec: under phase 1 resync cleared the silence flag; under phase 3 resync preserves `auto_fields_touched`.

**Files:**
- Modify: `app.py:1120-1135` (the `_apply_resync_to_item` helper)
- Modify: `tests/test_routes.py` (extend the existing resync test)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def test_resync_skips_touched_fields_and_preserves_touched_set(app, trip, owner):
    """Partial-touched item: untouched fields update, touched fields stay,
    touched set is preserved."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    # User has touched title (renamed it) AND day differs (booking moved).
    # On resync, title should stay, day should update, touched stays "title".
    item = ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="arrive",
        day_date=date(2026, 6, 5),     # stale; booking says Jun 1
        title="Arrive at JFK gate B22",  # user-touched
        category="transit",
        auto_fields_touched="title",
    )
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.title == "Arrive at JFK gate B22"   # preserved (touched)
    assert item.day_date == date(2026, 6, 1)         # updated (not touched)
    assert item.auto_fields_touched == "title"       # preserved
```

Also update the existing `test_resync_updates_fields_from_booking` test (currently asserts `customized_by_user is False`). Find it and replace that assertion with:

```python
    # No touches to start → resync updates the field, touched set stays empty.
    assert item.auto_fields_touched == ""
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "resync" -v
```

Expected: the new partial-touched test FAILS (resync currently overwrites everything). The updated `test_resync_updates_fields_from_booking` should PASS already because `auto_fields_touched` defaults to `""`.

- [ ] **Step 3: Update `_apply_resync_to_item`**

In `app.py`, find `_apply_resync_to_item` (around line 1120). Replace:

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

with:

```python
def _apply_resync_to_item(item, booking) -> bool:
    """Apply the booking's auto-generated values to one item.

    Only overwrites fields that the user hasn't personally touched
    (auto_fields_touched). The touched set itself is preserved, so a
    user who touched `title` will continue to keep their title across
    future resyncs — by design, per the phase-3 spec.

    Returns True if the item was updated, False if the booking no
    longer generates an item of this auto_kind (orphaned). Caller is
    responsible for committing the session.
    """
    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == item.auto_kind]
    if not matches:
        return False
    would_be = matches[0]
    touched = parse_touched(item.auto_fields_touched)
    for f in DRIFT_FIELDS:
        if f in touched:
            continue
        setattr(item, f, would_be.get(f))
    # auto_fields_touched preserved intentionally.
    return True
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_routes.py -k "resync" -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: resync preserves user-touched fields"
```

---

## Task 6: `itinerary_keep_mine` and `itinerary_unlink` use `auto_fields_touched`

Update the two action routes to write the new column instead of the deprecated flag. Update their tests.

**Files:**
- Modify: `app.py:1199-1234` (the `itinerary_keep_mine` and `itinerary_unlink` routes)
- Modify: `tests/test_routes.py` (update existing tests)

- [ ] **Step 1: Update the existing tests**

In `tests/test_routes.py`, find the existing `test_keep_mine_marks_customized` and `test_unlink_clears_linked_booking` tests. Replace them with:

```python
def test_keep_mine_sets_all_touched(app, trip, owner):
    """Keep mine fills auto_fields_touched with every DRIFT_FIELD."""
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/keep-mine")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.auto_fields_touched == "category,day_date,end_time,location,start_time,title"
    assert item.title == "Arrive Delta"  # field values unchanged


def test_unlink_clears_linked_booking_and_touched_set(app, trip, owner):
    """Unlink severs the link AND clears auto_fields_touched."""
    b, item = _make_flight_with_arrive(trip)
    # Pretend the user had touched something before unlinking.
    item.auto_fields_touched = "title"
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/unlink")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.linked_booking_id is None
    assert item.auto_kind is None
    assert item.auto_fields_touched == ""
    assert Booking.query.get(b.id) is not None
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "keep_mine or unlink" -v
```

Expected: both tests FAIL — the routes still write `customized_by_user`, not `auto_fields_touched`.

- [ ] **Step 3: Update `itinerary_keep_mine`**

In `app.py`, find `itinerary_keep_mine` (around line 1199). Replace the line:

```python
    item.customized_by_user = True
```

with:

```python
    item.auto_fields_touched = serialize_touched(DRIFT_FIELDS)
```

The updated route body looks like:

```python
@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/keep-mine", methods=["POST"])
@login_required
def itinerary_keep_mine(trip_id, item_id):
    """Silence drift detection for this item by marking every field as
    user-touched. Editor+ only."""
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    item.auto_fields_touched = serialize_touched(DRIFT_FIELDS)
    db.session.commit()
    logger.info("Marked itinerary item id=%s as fully touched (keep mine)", item.id)
    flash(f"Kept your version of “{item.title}”.", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

- [ ] **Step 4: Update `itinerary_unlink`**

In `app.py`, find `itinerary_unlink` (around line 1217). Replace the line:

```python
    item.customized_by_user = False
```

with:

```python
    item.auto_fields_touched = ""
```

The updated route body looks like:

```python
@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/unlink", methods=["POST"])
@login_required
def itinerary_unlink(trip_id, item_id):
    """Sever the booking link. Editor+ only.

    Sets linked_booking_id and auto_kind to NULL and clears the touched
    set — the item becomes a plain stand-alone itinerary entry.
    """
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    item.linked_booking_id = None
    item.auto_kind = None
    item.auto_fields_touched = ""
    db.session.commit()
    logger.info("Unlinked itinerary item id=%s from its booking", item.id)
    flash(f"Unlinked “{item.title}” from its booking.", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))
```

- [ ] **Step 5: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_routes.py -k "keep_mine or unlink" -v
```

Expected: both tests PASS.

- [ ] **Step 6: Run the full suite — phase 3 per-field work should be regression-free now**

```bash
.venv/bin/pytest -v
```

Expected: all tests PASS. If any still fail because they assert on `customized_by_user`, they're tests not covered by this plan's modifications — investigate before continuing.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: keep_mine and unlink write auto_fields_touched"
```

---

## Task 7: `missing_auto_kinds_for_booking` pure helper + `NewItemSuggestion`

The first new-items piece. A pure helper returns the list of would-be item dicts whose auto_kind doesn't already exist for the booking AND whose day is in trip range. Plus a small typed-return dataclass for use in templates.

**Files:**
- Modify: `src/booking_helpers.py` (append to the drift-detection section)
- Modify: `tests/test_booking_helpers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_booking_helpers.py`:

```python
from src.booking_helpers import NewItemSuggestion, missing_auto_kinds_for_booking


def test_missing_auto_kinds_returns_empty_when_all_exist():
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=datetime(2026, 6, 1, 14, 0),
                        location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds={"depart", "arrive"},
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    assert result == []


def test_missing_auto_kinds_returns_both_when_none_exist():
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=datetime(2026, 6, 1, 14, 0),
                        location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds=set(),
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    kinds = [w["auto_kind"] for w in result]
    assert sorted(kinds) == ["arrive", "depart"]


def test_missing_auto_kinds_returns_only_missing_when_one_exists():
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=datetime(2026, 6, 1, 14, 0),
                        location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds={"depart"},
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    kinds = [w["auto_kind"] for w in result]
    assert kinds == ["arrive"]


def test_missing_auto_kinds_excludes_items_outside_trip_range():
    """A suggestion whose day_date is outside [trip_start, trip_end] is filtered."""
    b = SimpleNamespace(type="flight", title="UA101", vendor="United",
                        start_datetime=datetime(2026, 7, 1, 10, 0),  # after end
                        end_datetime=datetime(2026, 7, 1, 14, 0),
                        location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds=set(),
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    assert result == []


def test_missing_auto_kinds_empty_for_non_spawning_booking_types():
    """Transport and 'other' bookings generate no auto-slots."""
    b = SimpleNamespace(type="transport", title="Subway", vendor=None,
                        start_datetime=datetime(2026, 6, 1, 10, 0),
                        end_datetime=None, location=None)
    result = missing_auto_kinds_for_booking(
        b, existing_kinds=set(),
        trip_start_date=date(2026, 6, 1), trip_end_date=date(2026, 6, 10),
    )
    assert result == []


def test_new_item_suggestion_carries_booking_kind_and_data():
    """Dataclass smoke test — fields and attribute access."""
    s = NewItemSuggestion(booking="booking-stand-in", auto_kind="arrive",
                          item_data={"title": "X"})
    assert s.booking == "booking-stand-in"
    assert s.auto_kind == "arrive"
    assert s.item_data == {"title": "X"}
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_booking_helpers.py -k "missing_auto_kinds or new_item_suggestion" -v
```

Expected: all 6 tests FAIL with import errors.

- [ ] **Step 3: Implement the helper and dataclass**

In `src/booking_helpers.py`, append to the bottom of the file (after `detect_drift`):

```python
@dataclass
class NewItemSuggestion:
    """A would-be itinerary item that a booking could generate but doesn't
    have linked yet. Used by the drift review landing page to offer
    'Add' buttons for newly-available auto-slots after a booking edit."""
    booking: Any            # a Booking row — generic to keep this module Flask-free
    auto_kind: str
    item_data: Dict[str, Any]


def missing_auto_kinds_for_booking(
    booking,
    existing_kinds: Iterable[str],
    trip_start_date,
    trip_end_date,
) -> List[Dict[str, Any]]:
    """
    Return the list of would-be itinerary item dicts (from
    auto_itinerary_items_for_booking) whose auto_kind is NOT in
    `existing_kinds` AND whose day_date falls within
    [trip_start_date, trip_end_date].

    Pure: no DB, no Flask. Caller pre-fetches `existing_kinds`.
    """
    existing = set(existing_kinds)
    out: List[Dict[str, Any]] = []
    for w in auto_itinerary_items_for_booking(booking):
        kind = w.get("auto_kind")
        day = w.get("day_date")
        if kind in existing:
            continue
        if day is None or day < trip_start_date or day > trip_end_date:
            continue
        out.append(w)
    return out
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_booking_helpers.py -k "missing_auto_kinds or new_item_suggestion" -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run the full booking_helpers suite**

```bash
.venv/bin/pytest tests/test_booking_helpers.py -v
```

Expected: every test passes.

- [ ] **Step 6: Commit**

```bash
git add src/booking_helpers.py tests/test_booking_helpers.py
git commit -m "feat: missing_auto_kinds_for_booking and NewItemSuggestion"
```

---

## Task 8: `_annotate_new_items_for_trip` helper + wire routes

Add a helper in `app.py` that computes the full new-items list for a trip in two queries (bookings + their linked items). Wire it into `trip_itinerary` (passes the count) and `itinerary_drift_review` (passes the full list).

**Files:**
- Modify: `app.py` (add helper near `_annotate_drift_for_items`; update `trip_itinerary` and `itinerary_drift_review`)
- Modify: `tests/test_routes.py` (one integration test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes.py`:

```python
def test_drift_review_lists_new_item_suggestions(app, trip, owner):
    """After a booking edit that adds a previously-missing auto-slot, the
    drift review landing page lists the suggestion."""
    # Flight that started with only a depart datetime (so only the depart
    # item exists). Now end_datetime is filled in → 'arrive' is missing.
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))  # newly added
    db.session.add(b)
    db.session.commit()
    # Only the depart item exists — no arrive yet.
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/itinerary/drift-review")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Suggestion text appears.
    assert "Arrive United" in body
    assert "New items the booking would create" in body
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
.venv/bin/pytest tests/test_routes.py::test_drift_review_lists_new_item_suggestions -v
```

Expected: FAIL — the template doesn't render the new section yet (added in Task 12). Note: this test will also fail because the route doesn't yet pass `new_items` — that's fine, this task addresses the route part now and Task 12 finishes the template.

If you'd rather defer the test until Task 12 lands the template, you can — but writing it now anchors the contract for both.

- [ ] **Step 3: Add the helper in `app.py`**

In `app.py`, just below the existing `_annotate_drift_for_items` helper (around line 845), add:

```python
def _annotate_new_items_for_trip(trip) -> List["NewItemSuggestion"]:
    """Return every NewItemSuggestion across all bookings for the trip.

    Pre-fetches all bookings and their linked items in two queries to
    avoid N+1.
    """
    bookings = Booking.query.filter_by(trip_id=trip.id).all()
    if not bookings:
        return []
    booking_ids = [b.id for b in bookings]
    items = ItineraryItem.query.filter(
        ItineraryItem.linked_booking_id.in_(booking_ids)
    ).all()
    existing_by_booking: dict = {}
    for it in items:
        if it.auto_kind:
            existing_by_booking.setdefault(it.linked_booking_id, set()).add(it.auto_kind)

    out: List[NewItemSuggestion] = []
    for b in bookings:
        existing = existing_by_booking.get(b.id, set())
        for w in missing_auto_kinds_for_booking(
            b, existing, trip.start_date, trip.end_date,
        ):
            out.append(NewItemSuggestion(
                booking=b, auto_kind=w["auto_kind"], item_data=w,
            ))
    return out
```

Then add `NewItemSuggestion` and `missing_auto_kinds_for_booking` to the `from src.booking_helpers import (...)` block at the top of `app.py`. Alphabetically the import block becomes:

```python
from src.booking_helpers import (
    BOOKING_TYPES,
    DRIFT_FIELDS,
    DriftReport,
    NewItemSuggestion,
    auto_itinerary_items_for_booking,
    booking_form_values,
    detect_drift,
    missing_auto_kinds_for_booking,
    parse_booking_form,
    parse_touched,
    serialize_touched,
)
```

- [ ] **Step 4: Wire `trip_itinerary` to pass the count**

In `app.py`, find the `trip_itinerary` route (around line 848). Update its body to also compute and pass `new_items_count`:

```python
@app.route("/trips/<int:trip_id>/itinerary")
@login_required
def trip_itinerary(trip_id):
    """Day-by-day timeline view. Viewer+ access."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    drift_count = _annotate_drift_for_items(items)
    new_items_count = len(_annotate_new_items_for_trip(trip))
    days = group_items_by_day(items, trip.start_date, trip.end_date)
    return render_template(
        "trip_itinerary.html",
        trip=trip,
        user_role=user_role,
        days=days,
        drift_count=drift_count,
        new_items_count=new_items_count,
    )
```

- [ ] **Step 5: Wire `itinerary_drift_review` to pass the full list**

In `app.py`, find the `itinerary_drift_review` route (around line 980–1000). Add the new-items list to its render context:

```python
@app.route("/trips/<int:trip_id>/itinerary/drift-review")
@login_required
def itinerary_drift_review(trip_id):
    """Landing page for the drift review wizard. Viewer+ access."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]
    resyncable = [it for it in drifting if not it.drift.is_orphaned]
    orphans = [it for it in drifting if it.drift.is_orphaned]
    new_items = _annotate_new_items_for_trip(trip)
    return render_template(
        "drift_review.html",
        trip=trip,
        user_role=user_role,
        drift_count=len(drifting),
        resyncable_count=len(resyncable),
        orphans=orphans,
        first_drifting_id=drifting[0].id if drifting else None,
        new_items=new_items,
    )
```

(Match the existing return signature — if the current route also passes `bookings_by_id` or anything else, keep it.)

- [ ] **Step 6: Run the full suite to confirm no regressions in OTHER tests**

```bash
.venv/bin/pytest -v
```

Expected: the test from Step 1 still fails (template work in Task 12). All other tests still pass.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: _annotate_new_items_for_trip helper wired to itinerary + drift review"
```

---

## Task 9: Per-item add-suggested route

A POST route that adds one suggested item by `(booking_id, auto_kind)`. Re-derives the missing list to verify the slot is still missing.

**Files:**
- Modify: `app.py` (add route after `itinerary_unlink`, around line 1234)
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def test_add_suggested_creates_linked_item(app, trip, owner):
    """POST /add-suggested/<bid>/<kind> creates the missing linked item."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    # Only depart exists.
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    assert ItineraryItem.query.filter_by(linked_booking_id=b.id).count() == 1

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/add-suggested/{b.id}/arrive"
        )
    assert resp.status_code == 302
    arrive_items = ItineraryItem.query.filter_by(
        linked_booking_id=b.id, auto_kind="arrive"
    ).all()
    assert len(arrive_items) == 1
    assert arrive_items[0].title == "Arrive United"
    assert arrive_items[0].auto_fields_touched == ""


def test_add_suggested_is_idempotent(app, trip, owner):
    """A second POST for an already-existing slot is a no-op (no duplicate)."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/add-suggested/{b.id}/arrive")
        client.post(f"/trips/{trip.id}/itinerary/add-suggested/{b.id}/arrive")
    arrive_items = ItineraryItem.query.filter_by(
        linked_booking_id=b.id, auto_kind="arrive"
    ).all()
    assert len(arrive_items) == 1
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "add_suggested" -v
```

Expected: both tests FAIL with 404 — route doesn't exist.

- [ ] **Step 3: Add the route**

In `app.py`, immediately after `itinerary_unlink` (around line 1234), add:

```python
@app.route(
    "/trips/<int:trip_id>/itinerary/add-suggested/<int:booking_id>/<string:auto_kind>",
    methods=["POST"],
)
@login_required
def itinerary_add_suggested(trip_id, booking_id, auto_kind):
    """Create one new linked itinerary item from a booking's suggestion.

    Editor+ only. Re-derives the missing list to verify the slot really is
    missing (in case of concurrent state). Redirects to drift review.
    """
    trip, _ = _trip_with_access_or_404(trip_id, role="editor")
    booking = db.session.get(Booking, booking_id)
    if booking is None or booking.trip_id != trip.id:
        flash("That booking doesn't exist.", "warning")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    existing_kinds = {
        it.auto_kind for it in ItineraryItem.query.filter_by(
            linked_booking_id=booking.id
        ).all() if it.auto_kind
    }
    missing = missing_auto_kinds_for_booking(
        booking, existing_kinds, trip.start_date, trip.end_date,
    )
    match = next((w for w in missing if w["auto_kind"] == auto_kind), None)
    if match is None:
        flash("That item already exists or is no longer suggested.", "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    match["order_within_day"] = _next_order_within_day(trip.id, match["day_date"])
    item = ItineraryItem(
        trip_id=trip.id,
        linked_booking_id=booking.id,
        auto_fields_touched="",
        **match,
    )
    db.session.add(item)
    db.session.commit()
    logger.info(
        "Added suggested item id=%s kind=%s for booking id=%s",
        item.id, auto_kind, booking.id,
    )
    flash(
        f"Added “{item.title}” to {item.day_date.strftime('%a, %b %d')}.",
        "success",
    )
    return redirect(url_for("itinerary_drift_review", trip_id=trip.id))
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_routes.py -k "add_suggested" -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: itinerary_add_suggested route for accepting one new item"
```

---

## Task 10: Bulk add suggested items — confirm GET + apply POST

The bulk-add flow as one task: GET renders a confirmation page listing every missing item, POST applies them all in one transaction. Both routes are added together so the template can reference both endpoint names via `url_for` without `BuildError`.

**Files:**
- Modify: `app.py` (add GET + POST routes after `itinerary_add_suggested` from Task 9)
- Create: `templates/drift_bulk_add_confirm.html`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes.py`:

```python
def test_bulk_add_confirm_lists_all_missing_items(app, trip, owner):
    """GET /add-all-suggested renders the confirmation page with each missing item."""
    b1 = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                 start_datetime=datetime(2026, 6, 1, 10, 0),
                 end_datetime=datetime(2026, 6, 1, 14, 0))
    b2 = Booking(trip_id=trip.id, type="flight", title="DL200", vendor="Delta",
                 start_datetime=datetime(2026, 6, 2, 8, 0),
                 end_datetime=datetime(2026, 6, 2, 12, 0))
    db.session.add_all([b1, b2])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/itinerary/add-all-suggested")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Depart United" in body
    assert "Arrive United" in body
    assert "Depart Delta" in body
    assert "Arrive Delta" in body


def test_bulk_add_creates_all_missing_items(app, trip, owner):
    """POST /add-all-suggested creates every missing item in one transaction."""
    b1 = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                 start_datetime=datetime(2026, 6, 1, 10, 0),
                 end_datetime=datetime(2026, 6, 1, 14, 0))
    b2 = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                 start_datetime=datetime(2026, 6, 1, 15, 0),
                 end_datetime=datetime(2026, 6, 3, 11, 0))
    db.session.add_all([b1, b2])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/add-all-suggested")
    assert resp.status_code == 302

    # 4 items total: depart + arrive (flight), check_in + check_out (hotel)
    all_items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    kinds = sorted(it.auto_kind for it in all_items)
    assert kinds == ["arrive", "check_in", "check_out", "depart"]
    assert all(it.auto_fields_touched == "" for it in all_items)


def test_bulk_add_is_idempotent(app, trip, owner):
    """A second POST after all suggestions are accepted is a safe no-op."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/add-all-suggested")
        client.post(f"/trips/{trip.id}/itinerary/add-all-suggested")
    assert ItineraryItem.query.filter_by(trip_id=trip.id).count() == 2
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_routes.py -k "bulk_add" -v
```

Expected: all three tests FAIL with 404 — neither route exists yet.

- [ ] **Step 3: Add both routes**

In `app.py`, just after `itinerary_add_suggested` (added in Task 9), add the GET-then-POST pair:

```python
@app.route("/trips/<int:trip_id>/itinerary/add-all-suggested", methods=["GET"])
@login_required
def itinerary_add_all_suggested_confirm(trip_id):
    """Confirmation page listing every missing item that would be added.

    Viewer+ to view; the submit button only renders for editor+ in the
    template.
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    new_items = _annotate_new_items_for_trip(trip)
    return render_template(
        "drift_bulk_add_confirm.html",
        trip=trip,
        user_role=user_role,
        new_items=new_items,
    )


@app.route("/trips/<int:trip_id>/itinerary/add-all-suggested", methods=["POST"])
@login_required
def itinerary_add_all_suggested(trip_id):
    """Add every missing suggested item across all bookings on this trip.

    Editor+ only. Re-derives the missing list per booking to avoid
    duplicates from concurrent state changes. One commit per request.
    """
    trip, _ = _trip_with_access_or_404(trip_id, role="editor")
    bookings = Booking.query.filter_by(trip_id=trip.id).all()
    if not bookings:
        flash("No bookings on this trip.", "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    booking_ids = [b.id for b in bookings]
    items = ItineraryItem.query.filter(
        ItineraryItem.linked_booking_id.in_(booking_ids)
    ).all()
    existing_by_booking: dict = {}
    for it in items:
        if it.auto_kind:
            existing_by_booking.setdefault(it.linked_booking_id, set()).add(it.auto_kind)

    added = 0
    for b in bookings:
        existing = existing_by_booking.get(b.id, set())
        for w in missing_auto_kinds_for_booking(
            b, existing, trip.start_date, trip.end_date,
        ):
            w["order_within_day"] = _next_order_within_day(trip.id, w["day_date"])
            db.session.add(ItineraryItem(
                trip_id=trip.id,
                linked_booking_id=b.id,
                auto_fields_touched="",
                **w,
            ))
            added += 1
    db.session.commit()
    logger.info("Bulk-added %d suggested items for trip_id=%s", added, trip.id)
    if added == 0:
        flash("No new suggestions to add.", "info")
    else:
        flash(
            f"Added {added} suggested item{'' if added == 1 else 's'}.",
            "success",
        )
    return redirect(url_for("itinerary_drift_review", trip_id=trip.id))
```

- [ ] **Step 4: Create the template**

Create `templates/drift_bulk_add_confirm.html`:

```jinja
{% extends "base.html" %}
{% block title %}Add suggested items — {{ trip.name }} — Vacation Planner{% endblock %}

{% block content %}
<div class="text-muted small mb-2">
  <a class="text-muted text-decoration-none" href="{{ url_for('trips_list') }}">My trips</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_overview', trip_id=trip.id) }}">{{ trip.name }}</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">Itinerary</a>
  &nbsp;›&nbsp;
  <a class="text-muted text-decoration-none" href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">Review drift</a>
  &nbsp;›&nbsp; Add suggested items
</div>

<h1 class="h3 mb-3">
  <i class="bi bi-plus-circle me-1 text-primary" aria-hidden="true"></i>
  Add suggested items
</h1>

<div class="vp-card mb-4">
  {% if not new_items %}
    <p class="mb-3">No new items are currently suggested by your bookings.</p>
    <a class="btn btn-link" href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">
      <i class="bi bi-arrow-left me-1" aria-hidden="true"></i>
      Back to review
    </a>
  {% else %}
    <p class="mb-3">
      The following {{ new_items|length }} item{{ '' if new_items|length == 1 else 's' }}
      would be added to your itinerary, linked to the listed booking:
    </p>
    <table class="table table-sm align-middle mb-3">
      <thead>
        <tr>
          <th>Title</th>
          <th>Day</th>
          <th>Time</th>
          <th>Category</th>
          <th>From booking</th>
        </tr>
      </thead>
      <tbody>
        {% for s in new_items %}
          <tr>
            <td><strong>{{ s.item_data.title }}</strong></td>
            <td>{{ s.item_data.day_date.strftime('%a, %b %d') }}</td>
            <td>
              {% if s.item_data.start_time %}
                {{ s.item_data.start_time.strftime('%H:%M') }}
              {% else %}
                <span class="text-muted">—</span>
              {% endif %}
            </td>
            <td>{{ s.item_data.category }}</td>
            <td class="text-muted">{{ s.booking.title }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>

    <div class="d-flex gap-2 flex-wrap mt-3 pt-3 border-top">
      {% if can_edit(user_role) %}
        <form method="post"
              action="{{ url_for('itinerary_add_all_suggested', trip_id=trip.id) }}"
              class="m-0">
          <button class="btn btn-vp-primary" type="submit">
            <i class="bi bi-check-lg me-1" aria-hidden="true"></i>
            Yes, add {{ new_items|length }} item{{ '' if new_items|length == 1 else 's' }}
          </button>
        </form>
      {% endif %}
      <a class="btn btn-link ms-auto"
         href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">
        Cancel
      </a>
    </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run the tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_routes.py -k "bulk_add" -v
```

Expected: all three tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app.py templates/drift_bulk_add_confirm.html tests/test_routes.py
git commit -m "feat: bulk add-all-suggested confirm page + apply route"
```

---

## Task 11: `booking_edit` flash mentions new items

After a booking edit, the flash should call out both drift potential AND new-item availability.

**Files:**
- Modify: `app.py:740-788` (the `booking_edit` route)
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes.py`:

```python
def test_booking_edit_flash_mentions_new_items_available(app, trip, owner):
    """Editing a flight to add end_datetime creates a new 'arrive' slot;
    the flash should mention it."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=None)
    db.session.add(b)
    db.session.commit()
    # Existing depart item — no arrive yet (since booking had no end_datetime).
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        # Edit: add end_datetime → arrive slot becomes available as a new suggestion.
        resp = client.post(
            f"/trips/{trip.id}/bookings/{b.id}/edit",
            data={
                "type": "flight", "title": "UA101", "vendor": "United",
                "confirmation_number": "", "location": "",
                "start_datetime": "2026-06-01T10:00",
                "end_datetime": "2026-06-01T14:00",
                "cost": "", "currency": "USD", "url": "", "notes": "",
            },
            follow_redirects=True,
        )
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "new item" in body.lower()
    assert "1" in body  # the count
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
.venv/bin/pytest tests/test_routes.py::test_booking_edit_flash_mentions_new_items_available -v
```

Expected: FAIL — current flash doesn't mention new items.

- [ ] **Step 3: Update the flash logic in `booking_edit`**

In `app.py`, find `booking_edit` (around line 742). Locate the block that builds the flash after the commit (around lines 763–778). Replace:

```python
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
```

with:

```python
        linked_items = ItineraryItem.query.filter_by(
            linked_booking_id=booking.id
        ).all()
        linked_count = len(linked_items)
        existing_kinds = {it.auto_kind for it in linked_items if it.auto_kind}
        new_items = missing_auto_kinds_for_booking(
            booking, existing_kinds, trip.start_date, trip.end_date,
        )
        new_count = len(new_items)

        parts: list = []
        if linked_count > 0:
            parts.append(
                f"{linked_count} linked itinerary item"
                f"{'' if linked_count == 1 else 's'} may now be out of sync"
            )
        if new_count > 0:
            parts.append(
                f"{new_count} new item{'' if new_count == 1 else 's'} available"
            )
        if parts:
            flash(
                f"Booking updated. {', '.join(parts)} — review on the Itinerary page.",
                "success",
            )
        else:
            flash("Booking updated.", "success")
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
.venv/bin/pytest tests/test_routes.py::test_booking_edit_flash_mentions_new_items_available -v
```

Expected: PASS.

- [ ] **Step 5: Confirm existing booking_edit flash tests still pass**

```bash
.venv/bin/pytest tests/test_routes.py -k "booking_edit" -v
```

Expected: every booking_edit-flavored test PASSES.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: booking_edit flash mentions new-item suggestions"
```

---

## Task 12: Drift review template additions + trip itinerary banner

The user-facing surface for new items. Template changes only — all the data is already being passed by the routes from Task 8.

**Files:**
- Modify: `templates/drift_review.html`
- Modify: `templates/trip_itinerary.html`

- [ ] **Step 1: Update `drift_review.html` headline + new-items section**

In `templates/drift_review.html`, find the existing top headline `<p>` (the one that says "{{ drift_count }} itinerary item(s) ... out of sync ..."). Inside that block, just before its closing `</p>`, append a sentence that runs only when `new_items` is non-empty:

```jinja
      {% if new_items %}
        And {{ new_items|length }} new item{{ '' if new_items|length == 1 else 's' }}
        {{ 'is' if new_items|length == 1 else 'are' }} suggested below.
      {% endif %}
```

Then, after the existing orphans `{% if orphans %}` section (the "Still needs review" block), append the new-items section. Insert immediately after the orphans block's closing `{% endif %}`:

```jinja
    {% if new_items %}
      <hr>
      <h2 class="h6 text-muted mb-2">New items the booking would create</h2>
      <ul class="list-unstyled small mb-2">
        {% for s in new_items %}
          <li class="mb-1 d-flex gap-2 align-items-center">
            <span>
              <strong>{{ s.item_data.title }}</strong>
              — {{ s.item_data.day_date.strftime('%a, %b %d') }}
              {% if s.item_data.start_time %}
                at {{ s.item_data.start_time.strftime('%H:%M') }}
              {% endif %}
              <span class="text-muted">— from {{ s.booking.title }}</span>
            </span>
            {% if can_edit(user_role) %}
              <form method="post" class="m-0 ms-auto"
                    action="{{ url_for('itinerary_add_suggested',
                                        trip_id=trip.id,
                                        booking_id=s.booking.id,
                                        auto_kind=s.auto_kind) }}">
                <button class="btn btn-sm btn-outline-secondary" type="submit">Add</button>
              </form>
            {% endif %}
          </li>
        {% endfor %}
      </ul>
      {% if can_edit(user_role) and new_items|length > 1 %}
        <a class="btn btn-sm btn-vp-primary"
           href="{{ url_for('itinerary_add_all_suggested_confirm', trip_id=trip.id) }}">
          <i class="bi bi-plus-circle me-1" aria-hidden="true"></i>
          Add all {{ new_items|length }} new items
        </a>
      {% endif %}
    {% endif %}
```

Note: `itinerary_add_all_suggested_confirm` is the name of the GET route from Task 10. Double-check the endpoint name matches the `@app.route` you defined.

- [ ] **Step 2: Update the "all clear" branch when only new items exist**

The existing landing page hides the CTAs when `drift_count == 0`. But the user might still have new items to add. Update the top-level branching in `drift_review.html`. Find:

```jinja
  {% if drift_count == 0 %}
    <p class="mb-3">Nothing's out of sync right now — every linked itinerary item matches its booking.</p>
    <a class="btn btn-vp-primary" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">
      <i class="bi bi-arrow-left me-1" aria-hidden="true"></i>
      Back to itinerary
    </a>
  {% else %}
```

and change it to:

```jinja
  {% if drift_count == 0 and not new_items %}
    <p class="mb-3">Nothing's out of sync right now — every linked itinerary item matches its booking.</p>
    <a class="btn btn-vp-primary" href="{{ url_for('trip_itinerary', trip_id=trip.id) }}">
      <i class="bi bi-arrow-left me-1" aria-hidden="true"></i>
      Back to itinerary
    </a>
  {% elif drift_count == 0 and new_items %}
    <p class="mb-3">
      Every linked item is in sync, but
      {{ new_items|length }} new item{{ '' if new_items|length == 1 else 's' }}
      {{ 'is' if new_items|length == 1 else 'are' }} suggested below.
    </p>
  {% else %}
```

(The `{% endif %}` at the end of the existing block stays where it was.)

- [ ] **Step 3: Update the itinerary banner in `trip_itinerary.html`**

In `templates/trip_itinerary.html`, find the existing drift banner (added in phase 1 Task 10, around line 12–24). The current block looks something like:

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

Replace it with:

```jinja
{% if drift_count > 0 or new_items_count > 0 %}
  <div class="alert alert-warning d-flex align-items-center justify-content-between" role="alert">
    <div>
      <i class="bi bi-exclamation-triangle-fill me-2" aria-hidden="true"></i>
      {% if drift_count > 0 %}
        {{ drift_count }} itinerary item{{ '' if drift_count == 1 else 's' }} out of sync.
      {% endif %}
      {% if new_items_count > 0 %}
        {{ new_items_count }} new item{{ '' if new_items_count == 1 else 's' }}
        suggested by booking changes.
      {% endif %}
    </div>
    <a class="btn btn-sm btn-outline-secondary"
       href="{{ url_for('itinerary_drift_review', trip_id=trip.id) }}">Review</a>
  </div>
{% endif %}
```

- [ ] **Step 4: Run the previously-failing drift-review test from Task 8**

```bash
.venv/bin/pytest tests/test_routes.py::test_drift_review_lists_new_item_suggestions -v
```

Expected: PASS (now that the template renders the section).

- [ ] **Step 5: Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests PASS — phase 3 is fully implemented and regression-free.

- [ ] **Step 6: Manual smoke test in the browser**

```bash
.venv/bin/python app.py
```

In a browser:
1. Open `http://localhost:5002/`, log in, pick a trip with a flight booking.
2. Edit the booking — clear its `end_datetime` (or add it back if missing). Submit.
3. Confirm the flash mentions new-item availability if you added a datetime, or drift if you cleared one.
4. Navigate to the itinerary page. Confirm the banner adapts: shows both counts when both are non-zero.
5. Click "Review". On the drift review page, confirm the "New items the booking would create" section appears with per-item Add buttons.
6. Click "Add" on a suggestion. Confirm the item appears on the itinerary, the suggestion disappears from the review page.
7. If multiple suggestions exist, click "Add all N new items". Confirm the bulk-add confirmation page lists them all. Submit. Confirm all are created.
8. Edit an existing linked item — change ONLY its title via the form. Then edit its booking — change the time. Visit the drift review page. Confirm drift is flagged on time but NOT on title (your touch is preserved).
9. Resync that item. Confirm the time updates but the title stays.

Stop the server with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add templates/drift_review.html templates/trip_itinerary.html
git commit -m "feat: drift review surfaces new-item suggestions; itinerary banner unified"
```

---

## Done. Phase 3 ships when:

- All 12 tasks committed.
- `pytest` is green.
- Manual smoke test from Task 12 Step 6 passes.
- The migration ran cleanly against your local DB (Task 1 Step 4 verified backfill).

## Next sessions

When phase 3 has baked in for a release or two:

- **Phase 4 — Polish.** Dashboard tile drift indicator. Animations on the resync action. Keyboard shortcuts inside the wizard.
- **Drop `customized_by_user` column.** One small task with a guarded ALTER TABLE DROP COLUMN and a removal of the deprecated-column declaration from `models.py`.
- **Optional: re-silence affordance.** If users find the "edit re-engages drift" behavior surprising (see the spec's "Intentional behavior change" callout), add a one-click "silence all drift on this item" button as a follow-up to Keep mine.

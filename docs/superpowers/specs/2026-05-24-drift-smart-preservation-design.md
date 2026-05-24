# Booking ↔ Itinerary Drift — Phase 3 "Smart Preservation" Design Spec

**Status:** approved design (2026-05-24), ready for implementation plan.

**Audience:** the engineer (likely future Claude + Jeff) who will translate this
into an implementation plan via `superpowers:writing-plans`.

---

## Goal

Two related improvements on top of phase 1 (per-item drift) and phase 2 (bulk
review):

1. **Per-field tracking.** Replace the whole-row `customized_by_user` flag with
   a field-granular `auto_fields_touched` set, so that editing one field of a
   linked itinerary item only silences drift on *that* field — other fields
   continue to track the booking and can still be resynced.
2. **"New items available" prompts.** When a booking is edited and the change
   would now generate additional auto-slots (e.g. adding `end_datetime` to a
   flight produces a previously-absent "Arrive" item), surface those new
   suggestions so the user can accept them with a click.

Today's behavior — set the flag, silence forever; ignore additions on edit —
is too coarse for a user who tweaks one detail and still wants the rest to
follow the booking.

## Out of scope

- Dropping the `customized_by_user` column from the schema. It stays in the
  database (un-read, un-written, marked deprecated by comment) so this change
  is reversible without a destructive ALTER. A follow-up may drop it.
- A UI for "untouching" a field — i.e. reverting a touched field back to
  tracking the booking. The implicit paths (Keep mine + edit) are the only
  ways the set mutates. If a real need surfaces we can add this later.
- Persistent dismissal of new-item suggestions. The suggestion disappears
  when the user adds it or when the booking changes such that the slot is no
  longer generated. No "I don't want this, ever" affordance.
- A new wizard step for new-item suggestions. The drift wizard remains
  focused on existing drifted items; new-item review happens on the landing
  page only.
- Dashboard tile drift indicator (phase 4).

## File map

| File | Action | Responsibility |
|---|---|---|
| `models.py` | Modify | Add `auto_fields_touched` column to `ItineraryItem`. Mark `customized_by_user` deprecated by comment. |
| `app.py` | Modify | Extend `_ensure_drift_columns` with new ALTER + backfill UPDATE. Rewrite `itinerary_edit` to record changed fields. Rewrite `_apply_resync_to_item` to skip touched fields. Rewrite `itinerary_keep_mine` and `itinerary_unlink` to use the new column. Add `_annotate_new_items_for_bookings` helper. Update `booking_edit` flash. Update `trip_itinerary` and `itinerary_drift_review` routes. Add three new routes (per-item add, bulk add confirm, bulk add POST). |
| `src/booking_helpers.py` | Modify | Add `parse_touched`, `serialize_touched`, `missing_auto_kinds_for_booking`, `NewItemSuggestion`. Update `detect_drift` to per-field semantics. |
| `templates/drift_review.html` | Modify | Add "New items the booking would create" section + optional bulk Add button. Update top-of-page headline. |
| `templates/drift_bulk_add_confirm.html` | Create | Bulk-add confirmation page (mirrors `drift_bulk_resync_confirm.html`). |
| `templates/trip_itinerary.html` | Modify | Banner copy adapts to include new-items count. |
| `tests/test_booking_helpers.py` | Modify | New tests for the three new pure helpers. |
| `tests/test_drift.py` | Modify | New tests for per-field drift semantics. |
| `tests/test_routes.py` | Modify | Rewrite the few tests that assert on `customized_by_user`. Add integration coverage for partial-resync, new-item flash, new-item add routes. |

---

## Data model

### New column

On `ItineraryItem` in `models.py`:

```python
# Set of DRIFT_FIELDS the user has personally edited on this item.
# Stored as a sorted comma-separated string (e.g. "day_date,title").
# Empty string means nothing touched.
# Replaces the deprecated customized_by_user flag with field-granular tracking.
auto_fields_touched = db.Column(db.String(255), nullable=False, default="")
```

### Deprecated column

`customized_by_user` stays on the model and in the database — its declaration
gets a one-line comment renaming it as deprecated:

```python
# DEPRECATED in phase 3: replaced by auto_fields_touched. No longer read or
# written. Column left in place for one release before being dropped.
customized_by_user = db.Column(db.Boolean, nullable=False, default=False)
```

### Migration

`_ensure_drift_columns` in `app.py` gets one more ALTER and one backfill
UPDATE. Both are guarded so reruns are no-ops:

```python
# Add column (idempotent — re-runs raise OperationalError which the existing
# try/except swallows, same pattern as phase 1).
"ALTER TABLE itinerary_item ADD COLUMN auto_fields_touched VARCHAR(255) NOT NULL DEFAULT ''",
```

Followed by a backfill statement that translates the old whole-row flag into
the equivalent "all fields touched" state:

```sql
UPDATE itinerary_item
   SET auto_fields_touched = 'category,day_date,end_time,location,start_time,title'
 WHERE customized_by_user = 1
   AND (auto_fields_touched = '' OR auto_fields_touched IS NULL)
```

The `auto_fields_touched = ''` guard makes the UPDATE a no-op on re-run.
Sorted field order matches what `serialize_touched(DRIFT_FIELDS)` produces.

---

## Pure helpers

### `parse_touched` and `serialize_touched`

Added near the bottom of `src/booking_helpers.py`, alongside `detect_drift`:

```python
def parse_touched(s: Optional[str]) -> Set[str]:
    """Parse a comma-separated touched-fields string into a set.

    Unknown field names (not in DRIFT_FIELDS) are silently dropped — keeps
    behavior stable if DRIFT_FIELDS later shrinks and an old DB row still
    references a removed field.
    """
    if not s:
        return set()
    parts = (p.strip() for p in s.split(","))
    return {p for p in parts if p in DRIFT_FIELDS}


def serialize_touched(fields: Iterable[str]) -> str:
    """Serialize a set of field names to sorted CSV. Unknown names dropped.

    Sorted output is stable for tests and human-readable in `sqlite3` output.
    """
    valid = sorted(f for f in fields if f in DRIFT_FIELDS)
    return ",".join(valid)
```

### `missing_auto_kinds_for_booking`

Also in `src/booking_helpers.py`:

```python
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

    Pure: no DB, no Flask. Caller pre-fetches existing_kinds.
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

### `NewItemSuggestion`

A small dataclass in `src/booking_helpers.py` for typed return:

```python
@dataclass
class NewItemSuggestion:
    booking: Any            # a Booking row — kept generic to avoid Flask import
    auto_kind: str
    item_data: Dict[str, Any]
```

---

## `detect_drift` becomes per-field

Replacing the current short-circuit on `customized_by_user`:

```python
def detect_drift(item, booking) -> Optional[DriftReport]:
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

Behavior summary:
- Item with no linked booking → `None`.
- Item with `auto_kind = None` (legacy) → `None`.
- Booking no longer generates this kind → `DriftReport(is_orphaned=True)`.
- All DRIFT_FIELDS in `auto_fields_touched` → loop produces no drifts → `None`.
- Otherwise → `DriftReport` listing only untouched fields that disagree.

The `customized_by_user` short-circuit is **removed** from this function.

---

## Route changes

### `itinerary_edit`

Replace:

```python
for field, value in data.items():
    setattr(item, field, value)
if item.linked_booking_id is not None:
    item.customized_by_user = True
```

with:

```python
# Compute which DRIFT_FIELDS actually changed value, before writing.
changed_fields: Set[str] = set()
if item.linked_booking_id is not None:
    for f in DRIFT_FIELDS:
        if data.get(f) != getattr(item, f):
            changed_fields.add(f)

for field, value in data.items():
    setattr(item, field, value)

if item.linked_booking_id is not None and changed_fields:
    prior = parse_touched(item.auto_fields_touched)
    item.auto_fields_touched = serialize_touched(prior | changed_fields)
```

A form submit that doesn't change any value leaves `auto_fields_touched`
untouched. This matters for the case where a user opens an edit form, makes
no real change, and saves — they shouldn't accidentally silence drift on
fields they didn't intend to.

**Implementation note:** the comparison `data.get(f) != getattr(item, f)`
assumes `parse_itinerary_form` returns a dict whose keys exactly match the
`DRIFT_FIELDS` names on the model. The implementation plan should verify
this in `src/itinerary.py` before relying on the direct comparison — if any
DRIFT_FIELD is missing from `data` (e.g. category isn't in the parsed
dict), it would always read as `None != current_value` and mark the field
spuriously touched.

### `_apply_resync_to_item`

Currently overwrites every DRIFT_FIELD and clears the flag. New version:

```python
def _apply_resync_to_item(item, booking) -> bool:
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
    # auto_fields_touched is preserved — touched fields stay the user's.
    return True
```

**Notable behavior change vs. phase 1:** resync used to clear
`customized_by_user`. Under the new model it preserves `auto_fields_touched`,
so if you've touched `title` and you resync, your title stays and the other
fields update. Re-resyncing later (after another booking change) again skips
title, by design.

### `itinerary_keep_mine`

Replace `item.customized_by_user = True` with:

```python
item.auto_fields_touched = serialize_touched(DRIFT_FIELDS)
```

`serialize_touched` produces the deterministic
`"category,day_date,end_time,location,start_time,title"` string. Same
observable behavior as today: drift on this item is silenced entirely going
forward.

### `itinerary_unlink`

Replace `item.customized_by_user = False` with:

```python
item.auto_fields_touched = ""
```

The item becomes stand-alone, so per-field tracking is meaningless.

### New routes for "Add suggested item"

Three new routes added in `app.py` near the existing drift action routes:

| Path | Method | Purpose |
|---|---|---|
| `/trips/<int:trip_id>/itinerary/add-suggested/<int:booking_id>/<string:auto_kind>` | POST | Add one suggested item (editor+). Redirects to drift review landing. |
| `/trips/<int:trip_id>/itinerary/add-all-suggested` | GET | Confirmation page (viewer+ to view, button hidden for non-editors). |
| `/trips/<int:trip_id>/itinerary/add-all-suggested` | POST | Bulk add in one transaction (editor+). |

#### Per-item add — `itinerary_add_suggested`

Verifies that the slot is still missing (in case of concurrent state),
builds the item dict, fills in `trip_id`, `linked_booking_id`,
`order_within_day` (via `_next_order_within_day`), `auto_fields_touched=""`,
adds + commits. Flashes "Added "{title}" to {day}." or, if no-op,
"That item already exists." Redirects to drift review landing.

#### Bulk add confirm — GET `itinerary_add_all_suggested`

Renders `templates/drift_bulk_add_confirm.html` with the list of
suggestions. Page mirrors `drift_bulk_resync_confirm.html`: bulleted/table
list of what would be created, single submit button, cancel link back to
landing.

#### Bulk add apply — POST `itinerary_add_all_suggested`

Re-derives the missing list (don't trust form contents). For each
suggestion, builds and adds the item with `auto_fields_touched=""`. One
commit. Flashes "Added N suggested items." Redirects to drift review
landing.

### `booking_edit` flash

After the existing commit + `linked_count` calculation, also compute
`new_count`:

```python
existing_kinds = {
    it.auto_kind for it in ItineraryItem.query.filter_by(
        linked_booking_id=booking.id
    ).all() if it.auto_kind
}
new_items = missing_auto_kinds_for_booking(
    booking, existing_kinds, trip.start_date, trip.end_date,
)
new_count = len(new_items)
```

Build the flash by combining drift and new-item language:

```python
parts: List[str] = []
if linked_count > 0:
    parts.append(
        f"{linked_count} linked itinerary item{'' if linked_count == 1 else 's'} "
        f"may now be out of sync"
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

### `trip_itinerary` and `itinerary_drift_review` routes

Both routes need to pass new-items context to their templates. Extract a
helper `_annotate_new_items_for_trip(trip)` in `app.py`:

```python
def _annotate_new_items_for_trip(trip) -> List[NewItemSuggestion]:
    """Return the list of new-item suggestions across all bookings for trip.

    Pre-fetches all bookings and their linked items in two queries.
    """
    bookings = Booking.query.filter_by(trip_id=trip.id).all()
    if not bookings:
        return []
    booking_ids = [b.id for b in bookings]
    items = ItineraryItem.query.filter(
        ItineraryItem.linked_booking_id.in_(booking_ids)
    ).all()
    existing_by_booking: Dict[int, Set[str]] = {}
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

`trip_itinerary` passes `new_items_count=len(_annotate_new_items_for_trip(trip))`
to its template (banner uses it).

`itinerary_drift_review` passes the full `new_items` list to its template
(the new section renders from it).

---

## Templates

### `templates/drift_review.html` additions

After the existing CTAs row and "Still needs review" (orphan) section, add:

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
       href="{{ url_for('itinerary_add_all_suggested', trip_id=trip.id) }}">
      <i class="bi bi-plus-circle me-1" aria-hidden="true"></i>
      Add all {{ new_items|length }} new items
    </a>
  {% endif %}
{% endif %}
```

The headline paragraph at the top of the page gains a second sentence when
`new_items` is non-empty:

```jinja
{% if new_items %}
  And {{ new_items|length }} new item{{ '' if new_items|length == 1 else 's' }}
  {{ 'is' if new_items|length == 1 else 'are' }} suggested below.
{% endif %}
```

### `templates/drift_bulk_add_confirm.html` (new)

Mirrors `drift_bulk_resync_confirm.html`. Table of suggestions
(title / day / time / category / from-booking), a "Yes, add these" submit
button, and a "Cancel" link back to the drift review landing.

### `templates/trip_itinerary.html` banner

The existing drift banner becomes a "things-to-review" banner. When
`drift_count + new_items_count > 0`, show the alert with body adapted:

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

(Replaces the current text-only "Click the warning pill on each item to
review." with a button, since the page now needs to send the user somewhere
specific.)

---

## Testing strategy

### New tests in `tests/test_booking_helpers.py`

- `parse_touched("")`, `parse_touched(None)`, `parse_touched("title,day_date")`
- `parse_touched("title,unknown")` drops `unknown`
- `serialize_touched({"day_date", "title"})` returns `"day_date,title"` (sorted)
- `serialize_touched({"title", "unknown"})` returns `"title"`
- `missing_auto_kinds_for_booking` — booking with both kinds present → empty
- `missing_auto_kinds_for_booking` — flight with no items → both depart+arrive
- `missing_auto_kinds_for_booking` — flight with only depart item → just arrive
- `missing_auto_kinds_for_booking` — flight whose date is outside trip → empty
- `missing_auto_kinds_for_booking` — booking with no auto-spawn (transport) → empty

### New tests in `tests/test_drift.py`

- Touched field is silently ignored even when value differs
- Partial touched: touched=`{title}`, day differs → drift report contains only `day_date`
- All touched → `detect_drift` returns `None`
- Touched=`{title}` but no field differs → returns `None`

### Modified tests in `tests/test_routes.py`

- Rename `test_itinerary_edit_marks_customized` → `test_itinerary_edit_records_changed_fields_only`. Assert `auto_fields_touched == "title"` after a title-only edit.
- Add `test_itinerary_edit_no_op_does_not_change_touched_set`.
- Rename `test_keep_mine_marks_customized` → `test_keep_mine_sets_all_touched`. Assert `auto_fields_touched == "category,day_date,end_time,location,start_time,title"`.
- Modify `test_resync_updates_fields_from_booking` to additionally cover partial-touched: touched=`{title}` before resync; title stays, other fields update, touched set unchanged.
- Modify `test_unlink_clears_linked_booking` to assert `auto_fields_touched == ""`.

### New tests in `tests/test_routes.py` for new-item suggestions

- After editing a flight to add `end_datetime`: drift review landing renders the "arrive" suggestion.
- POST `/itinerary/add-suggested/<bid>/arrive` creates the linked item with `auto_fields_touched == ""`.
- Second POST for the same kind is a no-op (item already exists).
- GET `/itinerary/add-all-suggested` lists every missing suggestion.
- POST `/itinerary/add-all-suggested` creates all of them in one go.
- `booking_edit` flash mentions both drift and new-item counts when both are non-zero.

---

## Migration verification (manual smoke after the migration step ships)

1. Boot the app against the existing SQLite DB. Confirm log line "Migration: applied ALTER TABLE itinerary_item ADD COLUMN auto_fields_touched ..." on first run, "Migration skipped" on second.
2. Open `sqlite3 vacation.db` and inspect rows:
   ```sql
   SELECT id, customized_by_user, auto_fields_touched FROM itinerary_item;
   ```
   Rows that had `customized_by_user=1` should now also have
   `auto_fields_touched='category,day_date,end_time,location,start_time,title'`.
3. Re-edit one of those items via the form, changing only the title. Confirm
   `auto_fields_touched` narrows to `"title"`. This is an **intentional
   behavior change** — see below.

### Intentional behavior change to highlight in the release notes

Items that were "fully silenced" under phase 1 (`customized_by_user=True`)
become **re-eligible** for drift detection on fields the user touches in
future edits. Concretely: if a user clicked "Keep mine" on an item to
silence it, then later edits only the title, the system will start
flagging drift on day/time/etc. again if the booking changes those.

The rationale is that "Keep mine" expresses the user's wish to silence
drift *given the state of the item at that moment*; a subsequent edit
indicates new engagement, so re-engaging drift detection on the rest of
the fields matches intent better than continuing to ignore them.

If users find this surprising, a future phase can add a UI affordance to
re-silence the whole item with one click.

---

## Open questions

None — all major decisions made via brainstorming. Tactical choices below
are settled but worth re-flagging for the implementation plan:

- Storage: comma-separated TEXT column, not JSON.
- Bulk-add UX: confirmation page first, mirrors bulk-resync.
- New-items prompt placement: booking-edit flash + landing page section
  (no wizard step).
- Dismissal: no persistent dismiss for MVP.
- `customized_by_user` column: stays in schema, deprecated by comment.

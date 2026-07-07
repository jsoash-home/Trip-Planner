# Guide Storage — Database Backend — Implementation Plan

**Design spec:** [2026-07-07-guide-storage-db-backend-design.md](../specs/2026-07-07-guide-storage-db-backend-design.md)

**Scope check:** 6 tasks, this file ~180 lines. Well under the project
caps (17 tasks, 1000 lines).

**Test bar:** 1057 passing on `main` at plan-write time. Target after
this feature: ~1065 passing (8 new tests, zero regressions).

## Files created / modified

| File | Type | Purpose |
|---|---|---|
| `models.py` | modified | Add `Trip.guide_html`, `Trip.guide_config_json` columns |
| `scripts/2026-07-07_add_guide_storage_columns.py` | created | One-off migration, mirrors 2026-06-19 script |
| `src/guide_builder.py` | modified | Fill 5 `elif GUIDE_STORAGE == "database":` branches, add small internal helper |
| `tests/test_guide_builder.py` | modified | Add ~8 DB-mode tests |
| `CLAUDE.md` | modified | Update "Storage abstraction" paragraph |
| `docs/PHASE_3_ROADMAP.md` | modified | Note DB backend shipped in the Phase 4 table |

## Task list

### Task 1 — Add DB columns to the `Trip` model

**File:** `models.py`

**Public surface (append to the `Trip` class near `guide_share_token`):**

```python
guide_html = db.Column(db.LargeBinary, nullable=True)
guide_config_json = db.Column(db.Text, nullable=True)
```

**Tests to add:** none — the schema is exercised by every later task.
`pytest tests/ -q` must still be 1057-green after this task on its own
(new columns default to NULL; nothing else changes).

**Verification:** run the full test suite, confirm no regressions.

---

### Task 2 — Migration script

**File:** `scripts/2026-07-07_add_guide_storage_columns.py`

Mirror `scripts/2026-06-19_add_guide_share_token.py` exactly for
structure: header docstring, `--yes` flag, `--db PATH` flag, backup
snapshot (`_take_backup`, `max_age_hours=0`), idempotency check, apply
inside one transaction, log before/after column counts.

**Public surface (module-level constants):**

```python
TABLE_NAME = "trip"
NEW_COLUMNS = {
    "guide_html": "BLOB",
    "guide_config_json": "TEXT",
}

def run_migration(db_path: Path, yes: bool) -> int: ...
def main() -> int: ...
```

**Idempotency:** check both columns via `PRAGMA table_info(trip)`;
exit 0 if both present.

**Tests to add:** none — one-off scripts aren't unit-tested. Manual
verification against a throwaway copy is the gate.

**Verification:**

```
cp vacation.db /tmp/vacation_test.db
.venv/bin/python scripts/2026-07-07_add_guide_storage_columns.py \
    --db /tmp/vacation_test.db --yes
sqlite3 /tmp/vacation_test.db "PRAGMA table_info(trip);"  # both cols present
rm /tmp/vacation_test.db
```

**Data-safety reminder:** DO NOT run this against `vacation.db` during
development — wait until all tests pass, then apply once. `vacation.db`
is production data (see CLAUDE.md).

---

### Task 3 — Fill DB branches in `guide_builder.py`, part 1 (HTML helpers)

**File:** `src/guide_builder.py`

Fill the `elif GUIDE_STORAGE == "database":` branches in:

- `guide_exists(trip_id)` — return
  `db.session.get(Trip, trip_id).guide_html is not None`. Raise
  `TripNotFound` if the trip row itself is missing.
- `save_guide(trip_id, html)` — encode `html` as UTF-8 bytes if given a
  `str`, write to `Trip.guide_html`, load-or-init the config, bump
  `last_generated_at`, save the config, commit. Return `None`
  (filesystem mode returns a `Path`; DB mode has no path — the return
  value is unused everywhere in the codebase; audit and confirm).
- `read_guide(trip_id)` — return the column bytes; raise `GuideMissing`
  if NULL, `TripNotFound` if the row is missing.

Add a tiny internal helper to avoid three copies of the same lookup:

```python
def _load_trip_or_raise(trip_id: int) -> "Trip":
    from models import Trip, db
    trip = db.session.get(Trip, trip_id)
    if trip is None:
        raise TripNotFound(f"Trip {trip_id} not found")
    return trip
```

**Return-value audit:** `git grep -n "save_guide("` — confirm nowhere
uses the returned `Path`. Callers either ignore it or (in the skill)
log it. If any caller does use it, either keep filesystem's return
semantic and return `None` in DB mode (documented), or return an
opaque sentinel string like `"<db>"`. Recommendation: return `None` in
DB mode, note in the docstring, `# type: ignore` any call sites the
audit surfaces.

**Tests to add (5), in `tests/test_guide_builder.py`:**

- `test_db_save_and_read_guide_roundtrip` — write bytes, read back
  identical bytes.
- `test_db_guide_exists_false_before_save_true_after`
- `test_db_read_guide_raises_guide_missing_when_null`
- `test_db_save_guide_bumps_last_generated_at_in_config_column` — read
  `Trip.guide_config_json`, parse, assert `last_generated_at` is set to
  a UTC ISO timestamp.
- `test_db_save_guide_raises_trip_not_found_when_no_row`

Each test starts with:

```python
def test_db_something(monkeypatch, client):
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")
    with client.application.app_context():
        # arrange: create a Trip row via db.session
        # act:     call the storage helper
        # assert:  ...
```

**Verification:** `.venv/bin/python -m pytest tests/test_guide_builder.py -v`
— all new tests green; existing filesystem tests still pass.

---

### Task 4 — Fill DB branches in `guide_builder.py`, part 2 (config helpers)

**File:** `src/guide_builder.py`

Fill the `elif GUIDE_STORAGE == "database":` branches in:

- `load_or_init_config(trip_id)` — read `Trip.guide_config_json`. If
  NULL, return `_fresh_config(trip_id)`. If present, `json.loads`,
  check `schema_version`, build `GuideConfig(**data)`. On JSON
  parse error, schema-version mismatch, or missing required key: log
  `logger.warning` (same message shape as the filesystem branch) and
  return `_fresh_config(trip_id)`.
- `save_config(trip_id, config)` — `json.dumps(asdict(config), indent=2)`
  into the column, commit. Return `None` (filesystem returns a Path;
  same audit as Task 3).

**Note:** filesystem mode's `save_config` returns `Path`. Nothing in
the codebase uses that return value either — audit with
`git grep -n "save_config("`.

**Tests to add (3):**

- `test_db_load_or_init_config_returns_fresh_when_column_is_null`
- `test_db_save_config_and_load_or_init_roundtrip_full_config` — build
  a `GuideConfig` with every field populated (sections, palette,
  depth_tier, section_depth_overrides, archetype, narrator_angle),
  save, load, assert equality field-by-field.
- `test_db_load_or_init_config_returns_fresh_on_schema_version_mismatch`
  — hand-write a JSON blob with `"schema_version": 99`, store, then
  call `load_or_init_config`, assert result equals `_fresh_config`.

**Verification:** full test suite green (~1065 passing).

---

### Task 5 — Update `CLAUDE.md` "Storage abstraction" paragraph

**File:** `CLAUDE.md`

Current text in the "Trip guide" section:

> **Storage abstraction.** All guide IO goes through
> `src/guide_builder.read_guide` / `save_guide` — Flask routes never touch
> the filesystem directly. A `GUIDE_STORAGE` env var (default `filesystem`)
> dispatches between local-file and a future database backend; the latter
> is unimplemented in v1 (raises `NotImplementedError`) and exists to make
> later cloud-hosting work cheap.

Replace with the accurate current-state description: both modes
supported, `filesystem` is the local default, `database` writes both
HTML and config JSON to `Trip.guide_html` / `Trip.guide_config_json`
respectively, `.bak` rotation only exists in filesystem mode, existing
on-disk guides are not auto-migrated.

**Tests to add:** none.

---

### Task 6 — Note the DB backend in `docs/PHASE_3_ROADMAP.md`

**File:** `docs/PHASE_3_ROADMAP.md`

In the Phase 4 table (around line 424), add a new row:

```
| Guide storage: DB backend | ✓ shipped   | [.../2026-07-07-guide-storage-db-backend-design.md](...) | [.../2026-07-07-guide-storage-db-backend.md](...) |
```

Also, in `docs/superpowers/plans/2026-07-03-trip-guide-phase2c.md`
under "Out of scope (deferred to future phases)", strike the storage-
backend line (or add a done note) so the trail from Phase 2c to this
work is visible.

**Tests to add:** none.

---

## Verification gate before merge

Run the full suite:

```
.venv/bin/python -m pytest tests/ -q
```

Expected: ~1065 passing, 0 failing.

Then apply the migration to `vacation.db` (only after tests pass):

```
.venv/bin/python scripts/2026-07-07_add_guide_storage_columns.py
```

Confirm the new columns exist:

```
sqlite3 vacation.db "PRAGMA table_info(trip);" | grep guide_
```

## Out of scope (deferred, per spec)

- Skill DB-awareness.
- Auto-migration of existing on-disk guides.
- Compression at rest.
- Multiple guide versions per trip.
- Cloud deploy itself.

## Rollback plan

If something goes wrong after the migration:

1. Stop the app.
2. `cp data/backups/vacation-<latest-timestamp>.db vacation.db`.
3. Confirm the Phase 2c `NotImplementedError` behaviour is back by
   setting `GUIDE_STORAGE=database` and hitting a guide route.
4. Revert the code changes with `git revert`.

The columns being nullable means no user-visible data is lost even
without a rollback — filesystem-mode guides on disk are untouched.

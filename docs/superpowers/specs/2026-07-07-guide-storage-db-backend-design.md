# Guide Storage — Database Backend — Design Spec

> **Status:** Draft, awaiting review. Fills the
> `elif GUIDE_STORAGE == "database":` branches that Phase 2c stubbed out
> in `src/guide_builder.py`, and extends the same dispatch to the guide
> config sidecar so both storage sources of truth move together.
> Cloud-deployment prep — no user-visible behaviour change locally.

## Goal

Let the trip guide (rendered HTML + config JSON) live in the app's
database when `GUIDE_STORAGE=database`, so guides survive on a cloud
host where the local filesystem is ephemeral and (with more than one
app copy) not shared.

Locally, the default (`filesystem`) mode stays exactly the same. Setting
the env var opts you into the new mode; everything else — routes,
templates, the skill, tests — is untouched.

## Background and motivation

The trip-guide skill runs on your Mac. At the end of a generation run
it writes two files:

- `data/guides/<trip_id>.html` — the rendered guide (~200–500 KB HTML).
- `data/guides/<trip_id>.config.json` — sections chosen, palette,
  archetype, depth tier, `last_generated_at`, etc.

Flask reads those files back when the user opens `/trips/<id>/guide` or
the public `/guides/share/<token>` URL.

This works perfectly on one computer. It stops working the moment the
app is hosted:

- **Ephemeral disk.** Railway / Fly / Render restart the app container
  regularly. Each new container starts with an empty scratch disk.
  Any file you wrote goes away.
- **No shared disk between copies.** If the host runs two copies for
  reliability, copy A writes the guide but copy B serves the request
  that reads it back. Copy B returns 404.

Phase 2c laid the groundwork: three helpers (`guide_exists`,
`save_guide`, `read_guide`) already dispatch on `GUIDE_STORAGE`.
Filesystem mode is fully implemented; `"database"` mode raises
`NotImplementedError`. This feature fills those branches and extends
the same pattern to the two config helpers (`load_or_init_config`,
`save_config`).

Why both together: the two files are a package. The rendered HTML is
useless without the config that records how it was made (so
`last_generated_at` on the "last regenerated N days ago" affordance
works), and the config is meaningless without the HTML it describes.
Splitting them across two storage backends would create sync problems
and give the user a partially-working guide surface. If we move one to
the DB, we move the other too.

## Scope

### In scope

- **Two new nullable columns on `Trip`:**
  - `guide_html` — `db.LargeBinary`, holds the rendered HTML bytes.
  - `guide_config_json` — `db.Text`, holds the same JSON currently
    written to `<id>.config.json`.
- **Migration script** `scripts/2026-07-07_add_guide_storage_columns.py`,
  mirroring `scripts/2026-06-19_add_guide_share_token.py`: backup
  snapshot, idempotency check, `--yes` flag, transactional apply.
- **DB-branch implementations** in five functions in
  `src/guide_builder.py`:
  - `guide_exists(trip_id)`
  - `save_guide(trip_id, html)`
  - `read_guide(trip_id)`
  - `load_or_init_config(trip_id)`
  - `save_config(trip_id, config)`
- **New tests** in `tests/test_guide_builder.py` that monkeypatch
  `GUIDE_STORAGE = "database"` and round-trip both HTML and config
  through the in-memory SQLite DB.
- **Updated docs**: `CLAUDE.md`'s "Storage abstraction" paragraph, plus
  a note in `docs/PHASE_3_ROADMAP.md`'s Phase 4 table.

### Out of scope (deferred)

- **Trip-guide skill DB-awareness.** The skill
  (`.claude/skills/trip-guide/SKILL.md`) still writes to
  `data/guides/` locally. Making the skill author guides against a
  hosted DB is a separate pass — you'd want auth, and probably a
  worker queue, and it's not needed for read-serving.
- **`.bak` rotation in DB mode.** Filesystem mode saves the previous
  HTML to `<id>.html.bak` before overwriting. DB mode skips this;
  Postgres backups handle undo.
- **Auto-migration of existing on-disk guides into the DB.** If you
  switch to `GUIDE_STORAGE=database`, existing filesystem guides are
  invisible until you re-generate them. Documented, not automated.
- **Compression at rest.** Guides are small enough (~500 KB) that gzip
  isn't worth the complexity.
- **Streaming / chunked responses.** `LargeBinary` loads the whole
  blob into memory. Fine for ~500 KB.
- **Multiple guide versions per trip.** Column model can't hold
  history; if we ever want that, a `TripGuide` table is a separate
  pass.
- **The actual cloud deploy.** This work makes cloud deploy possible;
  the deploy itself is its own project.

## Key design decisions

### 1. Two columns on `Trip` vs a new `TripGuide` table

**Chosen:** two columns on `Trip`.

Rationale:
- One-to-one relationship — the natural model for a column, not a
  table.
- `Trip.guide_html IS NOT NULL` doubles as the "exists" predicate
  without a JOIN.
- Nothing currently needs to filter, aggregate, or version guide
  contents.
- A `TripGuide` table is easy to introduce later if we ever want
  multi-version history — this doesn't foreclose that path.

### 2. Config as a single JSON column vs several typed columns

**Chosen:** single `guide_config_json` TEXT column.

Rationale:
- Mirrors what's already on disk 1:1. `json.dumps(asdict(config))`
  in, `json.loads(...)` + `GuideConfig(**data)` out.
- `GuideConfig` evolves — `depth_tier`, `archetype`,
  `narrator_angle`, and `section_depth_overrides` were all added
  after the first version. In a JSON column, adding a field is a
  code change, not a migration.
- `GuideConfig.schema_version` already carries the versioning story.
- Nothing queries by config field. The config is only ever read
  whole (when generating or serving a guide).

### 3. Skip `.bak` rotation in DB mode

**Chosen:** no `.bak` in DB mode.

Rationale:
- Postgres backup pipelines (managed by the host, and locally the
  automatic `data/backups/` snapshots) already provide a restore
  path.
- The user regenerates guides rarely; the `.bak` has never been
  used in anger since it shipped.
- Storing a second copy of every guide doubles space with no earned
  benefit.

### 4. `LargeBinary` vs `Text` for the HTML

**Chosen:** `LargeBinary`.

Rationale:
- The filesystem read is `Path.read_bytes()` — bytes, not text. The
  downstream Flask `send_file` / response body path takes bytes.
- Postgres maps `LargeBinary` to `BYTEA`, SQLite to `BLOB`. Both are
  fine for ~500 KB payloads.
- `Text` would force an encoding choice on every read/write. Bytes
  is what the rest of the pipe already expects.

### 5. How the app knows which mode to use

**Chosen:** `GUIDE_STORAGE=database` env var, unset locally so
`filesystem` remains the default.

Rationale:
- Mirrors the existing `DATABASE_URL` mechanism. No new config file,
  no new precedence rules.
- Cloud config sets:
  - `DATABASE_URL=postgres://...`
  - `GUIDE_STORAGE=database`
- Local dev leaves both unset.

### 6. What `save_guide` does in DB mode

Filesystem mode does three things: rotate `.bak`, write HTML, bump
`last_generated_at` in the sidecar. DB mode does two: write HTML to
the column, bump `last_generated_at` in the config column. Both
writes happen in the same `db.session.commit()` so a failure leaves
the trip in a consistent state.

## Data model changes

**Add to `models.py` (in the `Trip` class):**

```python
guide_html = db.Column(db.LargeBinary, nullable=True)
guide_config_json = db.Column(db.Text, nullable=True)
```

Both nullable so existing rows continue to work. Existing guides on
disk remain fully readable via filesystem mode; the DB columns are
only populated once someone runs a save under database mode.

**No changes to** `TripCollaborator`, `Booking`, `ItineraryItem`,
`PackingItem`, or any other model.

## Public API impact

None. The five refactored functions keep their exact same signatures
and return types. Callers in `app.py` and the trip-guide skill do not
change. Existing filesystem-mode tests pass unchanged.

## Testing approach

`tests/conftest.py` sets `DATABASE_URL=sqlite:///:memory:` before
importing the app (tripwire enforced). Every DB-mode test scopes the
storage mode with `monkeypatch`:

```python
def test_db_something(monkeypatch, client):
    monkeypatch.setattr(guide_builder, "GUIDE_STORAGE", "database")
    # ...write and read via the storage helpers...
```

Existing filesystem tests keep passing because `GUIDE_STORAGE`
defaults to `"filesystem"` at import time and monkeypatch is
per-test-scoped.

**Test list (8):**

- `test_db_save_and_read_guide_roundtrip`
- `test_db_guide_exists_false_before_save_true_after`
- `test_db_read_guide_raises_guide_missing_when_null`
- `test_db_save_guide_bumps_last_generated_at_in_config_column`
- `test_db_save_guide_raises_trip_not_found_when_no_row`
- `test_db_load_or_init_config_returns_fresh_when_column_is_null`
- `test_db_save_config_and_load_or_init_roundtrip_full_config`
- `test_db_load_or_init_config_returns_fresh_on_schema_version_mismatch`

Together these cover: happy path, exists probe, empty-state read,
config sidebar bump, missing trip, empty-config init, full-config
round-trip, schema-version guard.

## Migration considerations

- **Idempotent:** re-running the script after both columns exist
  exits cleanly with a "nothing to do" log line.
- **Backup first:** `_take_backup` (as in the 2026-06-19 script) is
  called with `max_age_hours=0` so a snapshot is always taken
  regardless of the standard 6-hour recency window.
- **SQLite:** two `ALTER TABLE trip ADD COLUMN` statements inside a
  single transaction. `ROLLBACK` on any error.
- **Postgres (cloud):** `ALTER TABLE trip ADD COLUMN` on a nullable
  column is fast and non-locking.
- **Rollback documented in script header.** `DROP COLUMN` requires
  SQLite ≥ 3.35; a one-liner per column.

## Non-goals restated

- No skill DB-awareness.
- No automated on-disk-to-DB guide migration.
- No mode-removal — filesystem stays supported and remains the
  local-dev default.
- No new dependencies. `json`, SQLAlchemy, and Flask-SQLAlchemy are
  already in use.

## Follow-up work this unlocks

- **Cloud deploy of Vacation Planner.** The blocker was "guides
  don't survive." This removes it. A full deploy still needs Postgres
  provisioning, the OAuth `OAUTHLIB_INSECURE_TRANSPORT` cleanup called
  out in `CLAUDE.md`, and a `Procfile` / `railway.toml` — but the
  guide storage question is settled.
- **Skill running against a hosted DB.** Once the read path works
  from a cloud DB, the next natural pass is letting the skill *author*
  guides against that DB directly (or against an API the app
  exposes). Explicit non-goal here, but named so we know where the
  next room is.

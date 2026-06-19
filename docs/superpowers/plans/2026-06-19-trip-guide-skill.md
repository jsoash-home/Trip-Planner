# Trip Guide Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Claude-Code skill that generates a bespoke single-file HTML trip guide for a Vacation Planner trip, and surface it as a hero card on the trip overview page (with optional public share-link).

**Architecture:** Python helper in `src/guide_builder.py` owns DB read + file IO + share-token management with full unit tests. A project-local skill at `.claude/skills/trip-guide/SKILL.md` orchestrates the creative work (research, palette, HTML composition) and calls the helper. Two new Flask routes serve the generated HTML — one gated by `require_trip_access` for owners + collaborators, one unauthed-via-UUID for sharing. Storage today is filesystem (`data/guides/<trip_id>.html`); a `GUIDE_STORAGE` env var dispatch keeps the door open for a later database backend when hosting.

**Tech Stack:** Flask, Flask-SQLAlchemy, SQLite (local) / Postgres (future cloud), Jinja2, vanilla JS, pytest, project-local Claude Code skill (markdown).

**Spec:** [docs/superpowers/specs/2026-06-19-trip-guide-skill-design.md](../specs/2026-06-19-trip-guide-skill-design.md)

---

## File map

**Created:**
- `src/guide_builder.py` — all plumbing helpers, type-hinted, ~180 lines
- `tests/test_guide_builder.py` — mirrors the helper module
- `templates/_guide_hero.html` — Jinja partial for the trip-overview hero card
- `static/js/guide_hero.js` — copy-to-clipboard for the share URL (~15 lines)
- `.claude/skills/trip-guide/SKILL.md` — the skill itself
- `scripts/2026-06-19_add_guide_share_token.py` — one-time SQLite migration

**Modified:**
- `models.py` — adds `guide_share_token` column to `Trip`
- `app.py` — two new routes; trip-overview view context extension
- `templates/trip_overview.html` — one `{% include "_guide_hero.html" %}` line
- `static/css/app.css` — `.guide-hero` block (~20 lines)
- `tests/test_routes.py` — route tests for the two new endpoints + context test
- `.gitignore` — adds `data/guides/`
- `CLAUDE.md` — new "Trip Guide" subsection

**Untouched:** Bookings, itinerary, packing, sharing-collaborator, countdown, weather, drift-review, geocoding, dashboard.

---

## Phase 1 — Data layer (Tasks 1–7)

No user-visible change after this phase. End state: helper module + tests + DB column present, all tests green.

### Task 1: Add `guide_share_token` column to Trip model

**Files:**
- Modify: `models.py` — `Trip` class

**Change:** Add one column to the `Trip` model:

```python
guide_share_token = db.Column(db.String(36), unique=True, nullable=True, index=True)
```

Position it near other "optional metadata" columns on `Trip` (use existing ordering — likely after the emoji/theme fields). Reflect in any `__repr__` only if other optional fields appear there.

**No test for the model change itself.** Schema is verified by Task 2's migration script and Tasks 4–7's helper tests creating Trip rows.

**Verify:** `pytest tests/ -q` still passes (no regressions in existing test suite, which uses the in-memory DB fixture that auto-picks up the new column via `db.create_all()`).

**Commit message:**
```
feat(models): add Trip.guide_share_token column
```

---

### Task 2: Migration script for existing `vacation.db`

**Files:**
- Create: `scripts/2026-06-19_add_guide_share_token.py`

**Purpose:** Apply the column to the real `vacation.db` file (the in-memory test DB picks it up automatically from `db.create_all()`, but the production SQLite file needs an explicit ALTER).

**Script behavior:**
1. Take a backup snapshot first via `src/backup.py:snapshot_db()` (force, regardless of last-snapshot timing).
2. Connect to `vacation.db` with raw `sqlite3`.
3. If the column already exists (check `PRAGMA table_info(trip)`), exit cleanly with "already migrated".
4. Otherwise: `ALTER TABLE trip ADD COLUMN guide_share_token VARCHAR(36)` and `CREATE UNIQUE INDEX ix_trip_guide_share_token ON trip (guide_share_token)`.
5. Print a summary line of the change.

**Rollback path documented in a top-of-file docstring:**
```
DROP INDEX ix_trip_guide_share_token;
ALTER TABLE trip DROP COLUMN guide_share_token;
```
(Note: SQLite 3.35+ supports `DROP COLUMN`. Confirm the user's SQLite version with `sqlite3 --version` before running.)

**Pre-run confirmation in script:** Print "About to alter vacation.db — proceed? [y/N]". Refuse to run unless `--yes` flag is passed OR interactive `y` confirmation. Per the project's data-safety rules, no silent writes to `vacation.db`.

**Verify:** Run the script locally against the real `vacation.db`. Confirm via `sqlite3 vacation.db ".schema trip"` that the column and index exist.

**Commit message:**
```
chore: migration script for Trip.guide_share_token
```

---

### Task 3: Create `src/guide_builder.py` — constants, dataclass, errors

**Files:**
- Create: `src/guide_builder.py`
- Create: `tests/test_guide_builder.py` (skeleton — no tests yet, just imports + an empty test class so the file exists)

**Public surface (this task adds the module-level scaffolding only — function bodies in later tasks):**

```python
import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from models import db, Trip
# (Bookings/ItineraryItem imports added in Task 4)

logger = logging.getLogger(__name__)

GUIDES_DIR = Path("data/guides")
CONFIG_SCHEMA_VERSION = 1
SECTION_KEYS = (
    "day_by_day",
    "field_guide",
    "things_to_do",
    "weather",
    "history",
    "fun_facts",
    "food",
)
GUIDE_STORAGE = os.getenv("GUIDE_STORAGE", "filesystem")


class GuideError(Exception):
    """Base error for guide_builder."""


class TripNotFound(GuideError):
    """Trip ID does not exist."""


class GuideMissing(GuideError):
    """No guide HTML found for this trip."""


@dataclass
class GuideConfig:
    schema_version: int
    trip_id: int
    sections: list
    palette: dict
    last_generated_at: Optional[str]
```

**Tests in this task:** None yet — just an importable test module with one trivial test:

```python
def test_module_imports():
    from src import guide_builder  # noqa: F401
```

**Verify:** `pytest tests/test_guide_builder.py -q` passes the single import test.

**Commit message:**
```
feat(guide_builder): scaffold module — constants, dataclass, errors
```

---

### Task 4: `load_trip_data` + tests

**Files:**
- Modify: `src/guide_builder.py` — add `load_trip_data`
- Modify: `tests/test_guide_builder.py` — add tests

**Public surface:**

```python
def load_trip_data(trip_id: int) -> dict:
    """
    Return {"trip": dict, "bookings": [dict, ...], "itinerary": [dict, ...],
            "collaborators": [dict, ...]} for the given trip.

    Itinerary is pre-sorted by day_date ascending, then by sort_within_day
    rules. Bookings include a "linked_itinerary_ids" field listing any
    ItineraryItem.id rows whose linked_booking_id points back at the booking.

    Raises TripNotFound if no row exists.
    """
```

**Implementation notes:**
- Use SQLAlchemy session inside a pushed Flask app context (the helper module needs to be importable from both Flask requests AND the skill — for the skill case, the caller pushes the context).
- Reuse `src/itinerary.py:sort_within_day` for the ordering — don't duplicate.
- Return *plain dicts*, not SQLAlchemy ORM objects. The skill consumes these as data; ORM objects would leak ORM concerns into the skill prompt.
- Booking dict shape: `{id, type, vendor, title, start_datetime, end_datetime, location, notes, cost, currency, linked_itinerary_ids}`. Datetimes serialized as ISO 8601 strings.
- ItineraryItem dict shape: `{id, day_date, category, title, start_time, end_time, location, notes, linked_booking_id}`. Times as ISO `HH:MM` strings or None.
- Collaborators: `{email, role}` per row. Owner not included (owner is the trip itself).

**Test list (`tests/test_guide_builder.py`):**
- `test_load_trip_data_happy_path` — seed Trip + 2 Bookings + 4 ItineraryItems across 3 days; assert shape and counts.
- `test_load_trip_data_raises_trip_not_found` — unknown trip_id raises `TripNotFound`.
- `test_load_trip_data_itinerary_sorted_by_day_then_time` — items returned in chronological order regardless of insert order.
- `test_load_trip_data_bookings_include_linked_itinerary_ids` — flight booking spawns Depart + Arrive items; the booking dict lists both item ids.
- `test_load_trip_data_no_collaborators_returns_empty_list` — solo trip → `collaborators == []`.
- `test_load_trip_data_with_collaborator_returns_role` — viewer collaborator appears with role string.

**Verify:** `pytest tests/test_guide_builder.py -q`

**Commit message:**
```
feat(guide_builder): load_trip_data — read trip + bookings + itinerary
```

---

### Task 5: `load_or_init_config` + `save_config` + tests

**Files:**
- Modify: `src/guide_builder.py`
- Modify: `tests/test_guide_builder.py`

**Public surface:**

```python
def load_or_init_config(trip_id: int) -> GuideConfig:
    """
    Read data/guides/<trip_id>.config.json; return a fresh empty
    GuideConfig if the file is missing, corrupt, or has a mismatched
    schema_version (logs a warning in the latter two cases).
    """

def save_config(trip_id: int, config: GuideConfig) -> Path:
    """
    Write the config to data/guides/<trip_id>.config.json.
    Atomic write (temp file + os.replace). Creates the directory if
    needed. Returns the written path.
    """
```

**Implementation notes:**
- "Fresh empty config" means `GuideConfig(schema_version=CONFIG_SCHEMA_VERSION, trip_id=trip_id, sections=[], palette={}, last_generated_at=None)`.
- Atomic write pattern: `tmp = path.with_suffix(path.suffix + ".tmp")`; write to tmp; `os.replace(tmp, path)`.
- Use `dataclasses.asdict(config)` for serialization.

**Test list:**
- `test_load_or_init_config_returns_fresh_when_missing`
- `test_load_or_init_config_returns_fresh_when_corrupt_json` — write garbage to the file; assert fresh + warning logged via `caplog`.
- `test_load_or_init_config_returns_fresh_when_schema_version_mismatched` — write a config with `schema_version=999`; assert fresh + warning.
- `test_load_or_init_config_returns_saved_when_valid` — write a valid config; read it back; assert equality.
- `test_save_config_creates_directory_if_missing` — `data/guides/` doesn't exist; save succeeds; dir created.
- `test_save_config_atomic_write` — mock `os.replace` to raise; existing file untouched, no `.tmp` left behind. *(If mocking proves fiddly, drop this test — atomic write is defensive, not a feature.)*

**Test fixture:** Use `tmp_path` pytest fixture and monkeypatch `guide_builder.GUIDES_DIR` to `tmp_path / "guides"` so tests never write to the real `data/guides/`.

**Verify:** `pytest tests/test_guide_builder.py -q`

**Commit message:**
```
feat(guide_builder): config sidecar — load_or_init_config + save_config
```

---

### Task 6: `save_guide` + `read_guide` + `guide_path` + `guide_exists` + tests

**Files:**
- Modify: `src/guide_builder.py`
- Modify: `tests/test_guide_builder.py`

**Public surface:**

```python
def guide_path(trip_id: int) -> Path:
    """Pure path computation. Does not check existence."""

def guide_exists(trip_id: int) -> bool:
    """Dispatches on GUIDE_STORAGE."""

def save_guide(trip_id: int, html: str) -> Path:
    """
    Dispatches on GUIDE_STORAGE.
    Filesystem backend: rotates existing HTML to .bak (if present),
    atomic-writes new HTML, bumps last_generated_at on the config sidecar.
    Returns the written path (or a synthetic path for non-filesystem backends).
    """

def read_guide(trip_id: int) -> bytes:
    """
    Dispatches on GUIDE_STORAGE.
    Filesystem backend reads from disk. Raises GuideMissing if absent.
    """
```

**Implementation notes:**
- Dispatch shape inside each storage-dependent function:
  ```python
  if GUIDE_STORAGE == "filesystem":
      ...
  elif GUIDE_STORAGE == "database":
      raise NotImplementedError("database backend pending hosted-deployment work")
  else:
      raise ValueError(f"unknown GUIDE_STORAGE: {GUIDE_STORAGE!r}")
  ```
- `save_guide` bumps `last_generated_at` by calling `load_or_init_config` → mutate → `save_config`. Uses `datetime.now(timezone.utc).isoformat()`.
- `.bak` rotation: simple `shutil.copy2(path, path.with_suffix(".html.bak"))` before the atomic write of the new file.

**Test list:**
- `test_guide_path_computes_expected_path`
- `test_guide_exists_returns_false_when_missing`
- `test_guide_exists_returns_true_when_present`
- `test_save_guide_writes_file`
- `test_save_guide_creates_directory_if_missing`
- `test_save_guide_rotates_previous_to_bak`
- `test_save_guide_no_bak_on_first_run`
- `test_save_guide_bumps_last_generated_at`
- `test_read_guide_returns_bytes_when_present`
- `test_read_guide_raises_guide_missing_when_absent`
- `test_save_guide_database_storage_raises_not_implemented` — monkeypatch `guide_builder.GUIDE_STORAGE = "database"`; assert `NotImplementedError`.
- `test_save_guide_unknown_storage_raises_value_error`

**Verify:** `pytest tests/test_guide_builder.py -q`

**Commit message:**
```
feat(guide_builder): file IO + storage backend dispatch
```

---

### Task 7: Share-token helpers + tests

**Files:**
- Modify: `src/guide_builder.py`
- Modify: `tests/test_guide_builder.py`

**Public surface:**

```python
def set_share_token(trip_id: int) -> str:
    """
    Generate uuid.uuid4().hex, write to Trip.guide_share_token, commit.
    Idempotent: if Trip already has a token, return the existing one
    without rotating.
    Raises TripNotFound if no trip row.
    """

def clear_share_token(trip_id: int) -> None:
    """
    Set Trip.guide_share_token = None, commit. Idempotent.
    Raises TripNotFound if no trip row.
    """

def trip_by_share_token(token: str) -> Optional[Trip]:
    """
    Return the Trip ORM object whose guide_share_token matches, or None.
    Case-sensitive (uuid.hex is lowercase).
    """
```

**Test list:**
- `test_set_share_token_generates_hex_token` — token is 32 hex chars.
- `test_set_share_token_persists_to_trip`
- `test_set_share_token_idempotent_returns_existing` — call twice; same token both times; no rotation.
- `test_set_share_token_unknown_trip_raises_trip_not_found`
- `test_clear_share_token_clears_field`
- `test_clear_share_token_idempotent_on_already_null`
- `test_trip_by_share_token_finds_correct_trip` — two trips, two tokens; lookup returns the right one.
- `test_trip_by_share_token_returns_none_for_unknown_token`
- `test_trip_by_share_token_case_sensitive` — uppercase version of a valid token returns None.

**Verify:** `pytest tests/test_guide_builder.py -q` — all guide_builder tests pass; full suite still green with `pytest tests/ -q`.

**Commit message:**
```
feat(guide_builder): share-token lifecycle helpers
```

---

## Phase 2 — Routes + hero card (Tasks 8–14)

End state: dropping a hand-written HTML into `data/guides/<trip_id>.html` makes the hero card appear on the trip overview and both routes work.

### Task 8: `GET /trips/<int:trip_id>/guide` route + tests

**Files:**
- Modify: `app.py` — add the route near other `/trips/<id>/...` routes (likely after `trip_overview` around line 1611)
- Modify: `tests/test_routes.py` — add tests

**Route shape:**

```python
@app.route("/trips/<int:trip_id>/guide")
@login_required
def trip_guide(trip_id):
    require_trip_access(trip_id, "viewer")
    try:
        html = guide_builder.read_guide(trip_id)
    except guide_builder.GuideMissing:
        abort(404)
    return Response(html, mimetype="text/html")
```

**Test list (`tests/test_routes.py`):**
- `test_trip_guide_owner_gets_200`
- `test_trip_guide_viewer_collaborator_gets_200`
- `test_trip_guide_editor_collaborator_gets_200`
- `test_trip_guide_non_collaborator_gets_403`
- `test_trip_guide_missing_file_returns_404`
- `test_trip_guide_unknown_trip_returns_404` *(should hit `require_trip_access`'s own 404/403 path — verify which the project uses)*

**Test fixture note:** Use `tmp_path` + monkeypatch `guide_builder.GUIDES_DIR` so route tests don't pollute the real `data/guides/`.

**Verify:** `pytest tests/test_routes.py::test_trip_guide -v` — all 6 pass.

**Commit message:**
```
feat(routes): GET /trips/<id>/guide — gated guide serving
```

---

### Task 9: `GET /guides/share/<token>` route + tests

**Files:**
- Modify: `app.py`
- Modify: `tests/test_routes.py`

**Route shape:**

```python
@app.route("/guides/share/<token>")
def guide_share(token):
    trip = guide_builder.trip_by_share_token(token)
    if trip is None:
        abort(404)  # NOT 403 — don't leak token existence
    try:
        html = guide_builder.read_guide(trip.id)
    except guide_builder.GuideMissing:
        abort(404)
    return Response(html, mimetype="text/html")
```

**Note:** No `@login_required`. The token IS the credential.

**Test list:**
- `test_guide_share_valid_token_returns_200`
- `test_guide_share_unknown_token_returns_404`
- `test_guide_share_token_with_no_file_returns_404`
- `test_guide_share_works_when_logged_out`
- `test_guide_share_works_for_different_user` — log in as a non-collaborator, hit the share URL, expect 200 (token bypasses auth).

**Verify:** `pytest tests/test_routes.py::test_guide_share -v`

**Commit message:**
```
feat(routes): GET /guides/share/<token> — public share access
```

---

### Task 10: Trip-overview view context extension

**Files:**
- Modify: `app.py:1506` — `trip_overview` view function
- Modify: `tests/test_routes.py` — test the context

**Change inside `trip_overview` view function:** Add the following before the `render_template` call:

```python
guide_exists = guide_builder.guide_exists(trip_id)
share_url = None
if guide_exists and trip.guide_share_token and is_owner(current_user, trip):
    share_url = url_for("guide_share", token=trip.guide_share_token, _external=True)
guide_last_generated_at = None
if guide_exists:
    guide_last_generated_at = guide_builder.load_or_init_config(trip_id).last_generated_at
```

Pass `guide_exists`, `share_url`, `guide_last_generated_at` into the template context dict.

**Reuses existing `is_owner` from `src/sharing.py`.**

**Test list (extend `tests/test_routes.py`):**
- `test_trip_overview_no_guide_passes_guide_exists_false` — pass through to template; assert `b"TRIP GUIDE"` not in response.
- `test_trip_overview_with_guide_passes_guide_exists_true` — create a guide file; assert `b"TRIP GUIDE"` in response.
- `test_trip_overview_owner_with_share_token_sees_share_url` — assert the share URL string appears in the rendered HTML.
- `test_trip_overview_editor_does_not_see_share_url` — editor collaborator; assert the share URL string is NOT in response (gated by `is_owner`).

(The partial file is created in Task 11; this task's "no guide → no hero" test can pass before Task 11 by relying on the conditional include — but the "with guide → has hero" tests pass only AFTER Task 11. Either reorder, or mark the latter tests as `xfail` until Task 11, then flip in Task 11's commit.)

**Recommendation:** Reorder — write Task 10's plumbing without the assertions that depend on Task 11's partial existing. Then Task 11 adds the partial AND the assertions in a single commit.

**Verify:** `pytest tests/test_routes.py -k trip_overview -v`

**Commit message:**
```
feat(routes): pass guide context into trip overview
```

---

### Task 11: Create `_guide_hero.html` partial + wire into trip overview

**Files:**
- Create: `templates/_guide_hero.html`
- Modify: `templates/trip_overview.html` — add `{% include "_guide_hero.html" %}` immediately after the existing `{% include "_countdown_hero.html" %}` line
- Modify: `tests/test_routes.py` — flip the deferred assertions from Task 10

**Partial structure (rough — final palette/CSS classes determined by Task 12):**

```html
{% if guide_exists %}
<section class="card guide-hero" style="--theme-accent: {{ trip.emoji_theme.color }};">
  <p class="eyebrow">TRIP GUIDE</p>
  <h2 class="guide-hero__title">{{ trip.title }}</h2>
  <div class="guide-hero__actions">
    <a class="btn btn-primary" href="{{ url_for('trip_guide', trip_id=trip.id) }}">Open guide</a>
    {% if share_url %}
    <div class="guide-hero__share">
      <button class="btn btn-link" data-share-url="{{ share_url }}" aria-label="Copy share link">Copy share link</button>
      <code class="mono">{{ share_url }}</code>
    </div>
    {% endif %}
  </div>
  {% if guide_last_generated_at %}
  <p class="guide-hero__meta">Last updated · {{ guide_last_generated_at }}</p>
  {% endif %}
</section>
{% endif %}
```

**Implementation notes:**
- The exact way `trip.emoji_theme.color` is accessed depends on how `emoji_theme()` returns its struct — verify against `src/trip_helpers.py:emoji_theme` and adjust the dotted access (it may be `trip.emoji_theme()['color']` or similar).
- The `mono` class likely already exists in `static/css/app.css` from other partials — verify and reuse; do not duplicate.
- The Bootstrap `btn` and `btn-primary` classes match the rest of the app.
- The `_guide_hero.html` partial outputs **nothing** when `guide_exists` is False — see `{% if guide_exists %}` wrapper.

**Tests now active (from Task 10's deferred list):**
- `test_trip_overview_with_guide_passes_guide_exists_true`
- `test_trip_overview_owner_with_share_token_sees_share_url`
- `test_trip_overview_editor_does_not_see_share_url`

**Frontend verification (required by `CLAUDE.md`):**
1. `python app.py` (or start the dev server how the project starts it).
2. Drop a stub `data/guides/<some-real-trip-id>.html` with a valid HTML document.
3. Use `webapp-testing` to load `http://localhost:5002/trips/<id>` — assert zero console errors, assert `TRIP GUIDE` text visible.
4. Click "Open guide" — assert the stub HTML renders.

**Commit message:**
```
feat(templates): trip-guide hero card on trip overview
```

---

### Task 12: `.guide-hero` CSS

**Files:**
- Modify: `static/css/app.css` — append `.guide-hero` block

**CSS shape (approximate — tune to match the app's existing card visual language):**

```css
.guide-hero {
  border-left: 4px solid var(--theme-accent, #6366f1);
  padding: 1.25rem 1.5rem;
  margin: 1rem 0;
  background: var(--bs-body-bg);
  border-radius: 0.5rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.guide-hero .eyebrow {
  font-family: 'Space Mono', ui-monospace, monospace;
  font-size: 0.75rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--bs-secondary);
  margin: 0 0 0.5rem;
}
.guide-hero__title {
  font-size: 1.5rem;
  margin: 0 0 1rem;
}
.guide-hero__actions {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}
.guide-hero__share {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}
.guide-hero__share code {
  background: var(--bs-light);
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
}
.guide-hero__meta {
  font-size: 0.75rem;
  color: var(--bs-secondary);
  margin: 0.75rem 0 0;
}
@media print {
  .guide-hero { display: none; }
}
```

**Implementation note:** If the app already has design tokens for accents / eyebrows / cards (check `static/css/app.css` first — there are probably patterns for cards), prefer reusing those over adding new ones.

**Frontend verification (required):** Reload the trip overview, check console clean + card looks card-shaped + theme-accent visible.

**Commit message:**
```
style(guide-hero): card styling matching app design language
```

---

### Task 13: `guide_hero.js` — copy-to-clipboard + wiring

**Files:**
- Create: `static/js/guide_hero.js`
- Modify: `templates/base.html` — load the script (look for the existing script-tag block; add `<script src="{{ url_for('static', filename='js/guide_hero.js') }}" defer></script>` alongside)

**JS shape (~15 lines):**

```javascript
(function () {
  function init() {
    document.querySelectorAll('[data-share-url]').forEach(function (btn) {
      btn.addEventListener('click', async function (e) {
        e.preventDefault();
        const url = btn.dataset.shareUrl;
        try {
          await navigator.clipboard.writeText(url);
          btn.textContent = 'Copied!';
          setTimeout(function () { btn.textContent = 'Copy share link'; }, 1800);
        } catch (err) {
          window.prompt('Copy this link:', url);
        }
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

**Frontend verification (required):**
1. With a guide present and a share token set on the trip, reload `/trips/<id>`.
2. Click "Copy share link" — assert button text changes to "Copied!" briefly.
3. Paste into a new tab — assert the share URL works.
4. Console clean.

**Commit message:**
```
feat(js): copy-to-clipboard for guide share link
```

---

### Task 14: `.gitignore` + Phase 2 integration check

**Files:**
- Modify: `.gitignore` — add `data/guides/`
- No other code changes

**Integration check — manual end-to-end of Phase 2 only (no skill yet):**
1. Drop a beautiful hand-written HTML into `data/guides/<trip_id>.html` for a real trip.
2. Log in as owner — open `/trips/<id>` — assert hero card visible.
3. Click "Open guide" — assert the HTML renders.
4. With sqlite3 manually set the trip's `guide_share_token` to a UUID hex.
5. Reload `/trips/<id>` — assert share URL appears.
6. Open the share URL in a private window (logged out) — assert HTML renders.
7. Log in as a collaborator (editor) — assert hero visible BUT no share URL.
8. Delete the file — reload — assert hero gone, `/trips/<id>/guide` returns 404.

**Verify:** Manual checklist above + `pytest tests/ -q` full suite green.

**Commit message:**
```
chore: gitignore data/guides/ + Phase 2 wrap
```

---

## Phase 3 — Skill + docs (Tasks 15–17)

End state: typing `/trip-guide` in Claude Code generates a real guide that auto-renders on the trip overview.

### Task 15: Write `.claude/skills/trip-guide/SKILL.md`

**Files:**
- Create: `.claude/skills/trip-guide/SKILL.md`

**Frontmatter:**

```yaml
---
name: trip-guide
description: Generate a bespoke single-file HTML trip guide for a Vacation Planner trip. Reads bookings + itinerary from vacation.db and writes the guide to data/guides/<trip_id>.html, served by the app's /trips/<id>/guide route. Use when the user asks to build, generate, regenerate, or share a trip guide. Requires no Anthropic API key — runs entirely in Claude Code.
---
```

**Skill body — required sections (write each in prose; checklist format inside each):**

1. **When to use this skill.** User says "trip guide", "generate a guide", "build a guide for X trip", "share my trip with [person]", "regenerate the Iceland guide", etc.

2. **Quality bar / visual anchors.** Pointers (not copies) to the existing benchmark files:
   - `~/Downloads/galapagos-wildlife-guide.html` (1112 lines — filterable wildlife encyclopedia with sticky search + chips)
   - `~/Downloads/Galapagos_Field_Log_Mar27-Apr3_2027.html` (455 lines — day-by-day editorial field log)
   - Read both before composing your first guide for any new destination. Match the typographic polish, palette discipline, and editorial voice.

3. **Flow checklist** (the ten steps from spec Section 2):
   1. Resolve the trip (ID or name → confirm back).
   2. Call `python -c "from src.guide_builder import load_trip_data; ..."` to read trip data. Push an app context inside the snippet.
   3. Call `load_or_init_config(trip_id)`. If `last_generated_at` is set, prompt the user (regenerate-same / change-sections / cancel).
   4. Section picker — multi-select from `SECTION_KEYS`.
   5. Palette proposal — research destination feel; propose hex codes + font pairing; user accepts or steers; save to config.
   6. Research + compose section by section using built-in knowledge plus `WebSearch`/`WebFetch`.
   7. Compose the HTML (single-file, inline CSS, Google Fonts CDN, no framework, mobile-responsive, print-friendly, `prefers-reduced-motion` respected).
   8. Save via `save_guide(trip_id, html)`.
   9. Share-token prompt — first run or on demand. Call `set_share_token(trip_id)` if yes. Print both URLs.
   10. Frontend verification — load guide in headless Chrome via `webapp-testing`, assert zero console errors and visible content; load `/trips/<id>` and assert hero card. Stop on failure.

4. **Section content model** — short summary of the 7 sections (refer the engineer to the spec for full detail).

5. **Helper invocation pattern** — concrete snippets the skill uses to call `src/guide_builder.py`:

```python
# Push a Flask app context before any helper call:
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///vacation.db")
from app import app
from src import guide_builder
with app.app_context():
    data = guide_builder.load_trip_data(trip_id)
```

6. **Anti-patterns** — do NOT:
   - Generate placeholder content ("Lorem ipsum", "Day intro TBD").
   - Skip the frontend verification step.
   - Write to `vacation.db` directly — only through `set_share_token` / `clear_share_token`.
   - Embed images from external URLs — inline SVG / CSS only.
   - Re-use a palette wholesale from a previous trip's guide — each trip earns its own.

7. **First-run handoff to user** — after a successful generation, print a short summary: trip name, sections included, palette name, both URLs (gated + share if minted), and the file path.

**Verify the skill exists:** `ls .claude/skills/trip-guide/SKILL.md` and `cat .claude/skills/trip-guide/SKILL.md | head -3`.

**Commit message:**
```
feat(skill): trip-guide — generate bespoke HTML guides
```

---

### Task 16: Update `CLAUDE.md` documentation

**Files:**
- Modify: `CLAUDE.md` (the project one, not the global one)

**Add a new subsection** between the existing "Today view" or "Fun countdown" section and "Local port":

```markdown
## Trip guide

A Claude-Code-only skill (`.claude/skills/trip-guide/SKILL.md`) generates a
bespoke single-file HTML guide for any trip. The skill reads the trip's
bookings + itinerary from `vacation.db` (via `src/guide_builder.py`),
prompts you for which sections to include (day-by-day, field guide,
things-to-do, weather, history, fun facts + practical tips, food + drink),
researches a palette, composes the HTML, and saves to
`data/guides/<trip_id>.html`.

The trip overview page renders a hero card with an "Open guide" button
when the file exists. A nullable `guide_share_token` column on `Trip`
optionally mints a public URL (`/guides/share/<token>`) for sharing with
non-collaborators.

**Storage abstraction.** All guide IO goes through
`src/guide_builder.read_guide` / `save_guide` — Flask routes never touch
the filesystem directly. A `GUIDE_STORAGE` env var (default `filesystem`)
dispatches between local-file and a future database backend; the latter
is unimplemented in v1 (raises `NotImplementedError`) and exists to make
later cloud-hosting work cheap.

**Run the skill:** type `/trip-guide` in Claude Code inside this repo.
The skill is project-local and only surfaces here.

**Migration:** `scripts/2026-06-19_add_guide_share_token.py` adds the
share-token column to existing `vacation.db`. Run once locally; backed
up automatically by the script before altering.
```

**Verify:** Read the diff; confirm no other CLAUDE.md sections were disturbed.

**Commit message:**
```
docs: CLAUDE.md — trip guide skill + storage abstraction
```

---

### Task 17: End-to-end smoke test against a real trip

**Files:** None modified. This is a manual verification pass.

**Pre-conditions:**
- All previous tasks committed and pushed.
- `vacation.db` already migrated (Task 2 ran successfully).
- Dev server running at `http://localhost:5002`.
- At least one real trip in the DB with some bookings + itinerary items.

**Steps:**
1. Open Claude Code in this project.
2. Type `/trip-guide` (or "build a trip guide for the [name] trip").
3. Follow the skill's prompts — pick sections, accept palette, watch composition.
4. After the skill claims success: open `http://localhost:5002/trips/<id>` — confirm hero card.
5. Click "Open guide" — read top-to-bottom. Note any quality issues but DO NOT fix in this task.
6. Mint a share link (re-run skill, answer y to share). Open the share URL in a private window — confirm it works.
7. Open `data/guides/<trip_id>.html` directly in a browser by `file://` URL — confirm it renders standalone (no broken paths to CDNs, no missing fonts).
8. Print preview — confirm `@media print` styles produce a clean printed guide (no sticky nav, no chips, no hero card on the trip-overview side).
9. Re-run skill on same trip — confirm regenerate-same path works, confirm `.bak` file was created in `data/guides/`.

**Likely follow-up work (NOT in this plan):**
- A "Phase 4 — tune the skill" session driven by what you find in step 5. Plan a separate short session with two more test trips. Likely changes: palette guidance, day-by-day editorial voice, food-section restaurant-quality bar.

**No commit for this task** — it's verification only.

---

## Self-review

**Spec coverage check:**
- ✅ Skill exists and is project-local (Task 15)
- ✅ Reads `vacation.db` directly (Task 4 — `load_trip_data`)
- ✅ Modular section catalog with 7 sections (Tasks 3, 15)
- ✅ Interactive picker cached in JSON sidecar (Task 5)
- ✅ Filesystem storage today + dispatch for future DB (Task 6)
- ✅ Bespoke palette per trip (Task 15)
- ✅ Default-gated route + optional UUID share token (Tasks 7, 8, 9)
- ✅ Hero card on trip overview (Tasks 10, 11)
- ✅ Owner-only share-URL visibility (Task 10)
- ✅ Forward compatibility for cloud hosting (Tasks 3, 6 — `GUIDE_STORAGE` dispatch)
- ✅ DB migration with safety confirmation (Task 2)
- ✅ Unit tests for every helper function (Tasks 4–7)
- ✅ Route tests for both routes + context (Tasks 8–10)
- ✅ Frontend verification per `CLAUDE.md` (Tasks 11, 12, 13)
- ✅ Documentation in `CLAUDE.md` (Task 16)
- ✅ End-to-end smoke test (Task 17)

**No spec gaps found.**

**Placeholder scan:** No "TBD", "TODO", "implement later", or "similar to Task N" markers. The single `# TODO:` comment inside the dispatch code block is a deliberate part of the design (marks the documented-stub DB backend).

**Type consistency:** Function names and shapes used in Tasks 8–11 match the surfaces defined in Tasks 3–7 (`read_guide`, `guide_exists`, `trip_by_share_token`, `is_owner`).

**Scope:** 17 tasks across three phases. Fits the project's plan-size cap. Phase 3 could be split into a follow-up if execution reveals more work, but the current granularity is right.

**Task ordering caveat already flagged:** Task 10 introduces test assertions that only pass once Task 11 lands. The plan recommends bundling those assertions into Task 11's commit — engineer should follow that note.

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-19-trip-guide-skill.md`.**

# Phase 3 — In-Pocket Trip Companion — Implementation Plan

> **For agentic workers:** use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` — one task per session,
> commit after each, review between. Steps use checkbox (`- [ ]`) syntax.

**Goal:** ship the "parked" Phase 3 in-trip + capture themes — an in-pocket
companion (offline shell, journal, spend log) plus four lifetime-value
extras (iCal, photos, achievements, themes).

**Sequencing (extras first, trio last):** small extras lock in shared
patterns (storage abstraction, migration flow, share-token style) that
C1–C3 then re-use.

**Scope:** 15 tasks / 7 phases. **Test bar:** `pytest tests/ -q` — zero regressions.

**Data-safety:** every migration mirrors
`scripts/2026-07-07_add_guide_storage_columns.py` — `snapshot_sqlite_db_if_due(max_age_hours=0)`,
idempotent, `--db PATH` + `--yes`, single transaction.

**Deploy readiness (cloud-hosting checklist).** Every session is designed
for future cloud hosting (Railway/Render/Fly). No feature writes non-DB
state to the local filesystem in cloud mode. At deploy time set:

- `DATABASE_URL=postgres://...` (Postgres)
- `GUIDE_STORAGE=database` and `PHOTO_STORAGE=database`
- `APP_VERSION=<git-sha>` on every deploy — this busts the PWA cache
- `SESSION_COOKIE_SECURE=True`, `SESSION_COOKIE_SAMESITE=Lax`
- Remove `os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"` from `app.py`
- Confirm your host runs pending migration scripts on release, or run
  them manually via `python scripts/YYYY-MM-DD_*.py --yes` before boot

---

## Files created / modified (whole plan)

| File | Type | Phase | Purpose |
|---|---|---|---|
| `models.py` | modified | 1,3,4,5,6 | Add `User.ical_token`, `Photo`, `SpendEntry`, `JournalEntry` |
| `scripts/2026-07-08_add_ical_token.py` | created | 1 | `User.ical_token` migration |
| `scripts/2026-07-10_add_photo_table.py` | created | 4 | Create `photo` table |
| `scripts/2026-07-11_add_spend_entry.py` | created | 5 | Create `spend_entry` table |
| `scripts/2026-07-12_add_journal_entry.py` | created | 6 | Create `journal_entry` table |
| `src/ical_feed.py` | created | 1 | Pure `.ics` builder + token helpers |
| `src/trip_helpers.py` | modified | 2 | Add `theme_palette`, palette map |
| `src/achievements.py` | created | 3 | Pure aggregation + achievement registry |
| `src/photo_storage.py` | created | 4 | Filesystem + database backends, thumbnails |
| `src/spend.py` | created | 5 | Parse form, rollup, convert to home currency |
| `src/journal.py` | created | 6 | Parse form, list-by-day, feeder for yearbook |
| `app.py` | modified | 1,3,4,5,6,7 | Routes for each feature + SW/manifest serving |
| `templates/base.html` | modified | 2,4,5,6,7 | Palette CSS vars, PWA meta tags, SW registration |
| `templates/_countdown_hero.html` | modified | 2 | Palette-driven gradient |
| `templates/trip_card.html` | modified | 2 | Palette-driven accent |
| `templates/user_profile.html` | modified | 1 | iCal subscribe URL + rotate button |
| `templates/achievements.html` | created | 3 | Earned + progress list |
| `templates/photo_upload.html` | created | 4 | Upload form + gallery snippet |
| `templates/spend_*.html` | created | 5 | List, add, edit forms; budget-page integration |
| `templates/journal_*.html` | created | 6 | List, edit forms; today-view snippet |
| `templates/offline.html` | created | 7 | Offline fallback page |
| `static/manifest.json` | created | 7 | PWA manifest |
| `templates/service-worker.js.j2` | created | 7 | Jinja template — SW body with `APP_VERSION` injected from env |
| `static/js/pwa-register.js` | created | 7 | Registration + update toast |
| `tests/test_ical_feed.py` | created | 1 | ~8 tests |
| `tests/test_trip_helpers.py` | modified | 2 | ~4 palette tests appended |
| `tests/test_achievements.py` | created | 3 | ~10 tests |
| `tests/test_photo_storage.py` | created | 4 | ~8 tests |
| `tests/test_spend.py` | created | 5 | ~10 tests |
| `tests/test_journal.py` | created | 6 | ~6 tests |
| `tests/test_pwa_shell.py` | created | 7 | ~4 route/header tests |
| `CLAUDE.md` | modified | 1,4,7 | New env vars + storage patterns |
| `requirements.txt` | modified | 1,4 | Add `icalendar`, `Pillow` |

---

## Phase 1 — iCal subscription feed

**Design choice: token on User, not Trip.** One token per user, one
subscription URL that carries every trip they own or collaborate on.
Cheaper to manage than per-trip tokens and matches the "just appears
on your calendar" story. Rotating the token invalidates every device
at once — accept that; a leaked calendar isn't the same failure mode
as a leaked share link.

**Timezone handling:** the app stores naive local datetimes. Emit
VEVENTs as floating (no TZID, no `Z`). Google/Apple render floating
times at the device's local tz, which is what a traveler wants
("dinner at 8pm" reads as 8pm wherever the phone is).

### Task 1 — Migration + iCal builder

**Files:**
- Modify: `models.py` (add `User.ical_token`)
- Create: `scripts/2026-07-08_add_ical_token.py`
- Create: `src/ical_feed.py`
- Create: `tests/test_ical_feed.py`
- Modify: `requirements.txt` (add `icalendar>=5.0`)

**Public surface — `User` (append near `home_currency`):**

```python
ical_token = db.Column(db.String(36), unique=True, nullable=True, index=True)
```

**Public surface — `src/ical_feed.py`:**

```python
FLOATING_TZ: Optional[str] = None  # naive/floating events

def build_feed(user: User, now: datetime) -> bytes: ...
def build_events_for_trip(trip: Trip) -> List["icalendar.Event"]: ...
def event_from_itinerary(item: ItineraryItem) -> Optional["icalendar.Event"]: ...
def event_from_booking(booking: Booking) -> Optional["icalendar.Event"]: ...
def generate_token() -> str: ...       # 32-char urlsafe
def user_by_token(token: str) -> Optional[User]: ...
```

**Rules:**
- Itinerary item with `start_time` and `end_time` → timed VEVENT.
- Itinerary item with only `day_date` → all-day VEVENT (`DTSTART;VALUE=DATE`).
- Booking flight/hotel/car with both start+end datetimes → VEVENT.
- Booking with missing dates → skip (returns None; caller filters).
- SUMMARY: `{trip.name}: {title}` so calendar picks read well.
- UID: `<trip_id>-<kind>-<row_id>@vacation-planner.local` — stable across regenerations.

**Test list (no bodies — write them in `tests/test_ical_feed.py`):**
- `test_all_day_item_emits_date_only`
- `test_timed_item_emits_dtstart_dtend`
- `test_untimed_flight_returns_none`
- `test_flight_with_both_datetimes_emits_event`
- `test_hotel_emits_multi_day_event`
- `test_summary_prefixes_trip_name`
- `test_uid_stable_across_calls`
- `test_generate_token_is_urlsafe_and_unique`

**Migration script:** mirror `scripts/2026-07-07_add_guide_storage_columns.py`
structurally (arg parser, `snapshot_sqlite_db_if_due`, idempotency,
transaction). One new column, one table: `user`.

**Verify:** `pytest tests/test_ical_feed.py -v`; migration against `/tmp/vacation_test.db` copy.

**Commit:** `feat(ical): add User.ical_token + feed builder`

---

### Task 2 — Route + subscribe UI

**Files:**
- Modify: `app.py` (route + profile endpoint)
- Modify: `templates/user_profile.html`
- Modify: `CLAUDE.md` (mention `/ical/subscribe/<token>.ics`)

**Public surface — `app.py`:**

```python
@app.route("/ical/subscribe/<token>.ics")
def ical_feed(token: str):
    """Public feed. No login. 404 on unknown token."""

@app.route("/settings/ical/rotate", methods=["POST"])
@login_required
def ical_rotate():
    """Invalidate old token; mint a new one; redirect to profile."""
```

**Response:**
- Content-Type `text/calendar; charset=utf-8`
- `Cache-Control: private, max-age=300` (five-minute caches; calendar
  clients poll every few hours regardless)
- Body from `ical_feed.build_feed(user, datetime.utcnow())`

**Profile template additions:**
- Section "Calendar subscription" with the full `webcal://` URL, a
  Copy button, and a "Rotate token" form (POST to
  `/settings/ical/rotate`).
- If `ical_token is None`, show a "Generate subscription URL" button
  that POSTs to the same rotate endpoint.

**Test list — extend `tests/test_ical_feed.py` at the bottom:**
- `test_route_404_on_unknown_token`
- `test_route_returns_calendar_content_type`
- `test_rotate_invalidates_old_token`

**Verify:** `pytest tests/test_ical_feed.py -v`; open `/settings`, rotate, subscribe in Calendar.app.

**Commit:** `feat(ical): subscribe route + profile UI`

---

## Phase 2 — Trip themes (palettes)

Small, purely visual, no schema. Extends the existing
`emoji_theme` helper.

### Task 3 — Palette helper + template wiring

**Files:**
- Modify: `src/trip_helpers.py`
- Modify: `templates/trip_card.html`
- Modify: `templates/_countdown_hero.html`
- Modify: `tests/test_trip_helpers.py`

**Public surface — `src/trip_helpers.py`:**

```python
class Palette(TypedDict):
    accent: str        # hex, e.g. "#0ea5e9"
    accent_soft: str   # 20%-tint of accent for backgrounds
    hero_from: str     # gradient start
    hero_to: str       # gradient end
    on_accent: str     # readable text on accent — "#fff" or "#111"

_THEME_PALETTES: Dict[str, Palette] = {
    "beach":    Palette(accent="#0ea5e9", accent_soft="#e0f2fe", hero_from="#38bdf8", hero_to="#fbbf24", on_accent="#fff"),
    "mountain": Palette(accent="#166534", accent_soft="#dcfce7", hero_from="#15803d", hero_to="#78716c", on_accent="#fff"),
    "city":     Palette(accent="#7c3aed", accent_soft="#ede9fe", hero_from="#4c1d95", hero_to="#db2777", on_accent="#fff"),
    "forest":   Palette(accent="#15803d", accent_soft="#dcfce7", hero_from="#166534", hero_to="#a3e635", on_accent="#fff"),
    "desert":   Palette(accent="#c2410c", accent_soft="#fed7aa", hero_from="#ea580c", hero_to="#fbbf24", on_accent="#fff"),
    "snow":     Palette(accent="#0369a1", accent_soft="#e0f2fe", hero_from="#38bdf8", hero_to="#e0e7ff", on_accent="#fff"),
    # add one entry per theme phrase currently in _EMOJI_THEME_MAP
}
_DEFAULT_PALETTE: Palette = Palette(
    accent="#6d28d9", accent_soft="#ede9fe",
    hero_from="#7c3aed", hero_to="#db2777", on_accent="#fff",
)

def theme_palette(emoji: Optional[str]) -> Palette:
    """Emoji → palette. Falls back to _DEFAULT_PALETTE for unknown emoji."""
```

**Template wiring:**
- `trip_card.html`: on the outer card element, add
  `style="--vp-accent: {{ palette.accent }}; --vp-accent-soft: {{ palette.accent_soft }};"`.
  Replace hard-coded card border/tag colours with `var(--vp-accent)`.
- `_countdown_hero.html`: replace the fixed purple gradient with
  `linear-gradient(135deg, {{ palette.hero_from }}, {{ palette.hero_to }})`.
- Both templates get `palette` from the Jinja context — routes that
  render them pass `palette=theme_palette(trip.cover_emoji)`.

**Test list — append to `tests/test_trip_helpers.py`:**
- `test_theme_palette_returns_beach_for_beach_emoji`
- `test_theme_palette_returns_default_for_unknown_emoji`
- `test_theme_palette_returns_default_for_none`
- `test_palette_hex_values_are_valid_css`

**Verify:** `pytest tests/test_trip_helpers.py -v`; dashboard cards + trip hero show themed border/gradient per palette.

**Commit:** `feat(themes): palette per emoji-theme, card + hero`

---

## Phase 3 — Achievement system

Pure aggregation. No new schema — everything is computed at read
time from existing trips + bookings + geocoded countries.

### Task 4 — Aggregation + registry

**Files:**
- Create: `src/achievements.py`
- Create: `tests/test_achievements.py`

**Public surface — `src/achievements.py`:**

```python
class UserStats(TypedDict):
    trips_completed: int
    trips_in_year: Dict[int, int]           # {2026: 5, 2025: 3}
    countries_visited: Set[str]             # 2-letter codes from geocoded_country_code
    continents_visited: Set[str]            # derived via a COUNTRY_TO_CONTINENT map
    total_nights: int                       # sum of trip lengths
    solo_trips: int                         # trips with 0 collaborators
    group_trips: int                        # trips with >=1 collaborator

class Achievement(NamedTuple):
    id: str                      # "countries_10"
    name: str                    # "Ten and Counting"
    description: str             # "Visited 10 different countries"
    icon: str                    # single emoji, no shortcodes
    predicate: Callable[[UserStats], bool]
    progress: Callable[[UserStats], Tuple[int, int]]  # (current, target)

def compute_stats(user: User) -> UserStats: ...
def all_achievements() -> List[Achievement]: ...
def earned(user: User) -> List[Achievement]: ...
def near_earned(user: User, limit: int = 3) -> List[Tuple[Achievement, int, int]]: ...
```

**Initial achievement list (10 total, seed of the registry):**

| id | name | predicate |
|---|---|---|
| `first_trip` | First Trip | `trips_completed >= 1` |
| `countries_5` | Five Countries | `len(countries_visited) >= 5` |
| `countries_10` | Ten and Counting | `len(countries_visited) >= 10` |
| `countries_25` | Quarter-Century Club | `len(countries_visited) >= 25` |
| `continents_all` | All Seven | `len(continents_visited) >= 7` |
| `five_trip_year` | Road Warrior | `max(trips_in_year.values(), default=0) >= 5` |
| `nights_30` | Month on the Road | `total_nights >= 30` |
| `nights_100` | Century of Nights | `total_nights >= 100` |
| `solo_5` | Lone Wanderer | `solo_trips >= 5` |
| `group_5` | Squad Traveler | `group_trips >= 5` |

**Test list:**
- `test_compute_stats_empty_user`
- `test_compute_stats_counts_only_completed_trips`
- `test_countries_from_geocoded_country_codes`
- `test_continents_derived_from_countries`
- `test_trips_in_year_groups_by_start_date`
- `test_solo_vs_group_split`
- `test_earned_first_trip_after_one_completed`
- `test_earned_countries_10`
- `test_near_earned_returns_progress_tuples`
- `test_near_earned_excludes_already_earned`

**Verification:** `.venv/bin/pytest tests/test_achievements.py -v`

**Commit:** `feat(achievements): stats aggregation + 10-badge registry`

---

### Task 5 — Route + template

**Files:**
- Modify: `app.py`
- Create: `templates/achievements.html`
- Modify: `templates/base.html` (navbar link "Achievements" for logged-in users)

**Public surface — `app.py`:**

```python
@app.route("/achievements")
@login_required
def achievements_view():
    stats = compute_stats(current_user)
    earned_list = earned(current_user)
    near = near_earned(current_user, limit=5)
    return render_template("achievements.html",
                           stats=stats, earned=earned_list, near=near)
```

**Template layout:**
- Hero: total count "N of M earned" with a progress ring.
- Grid: earned achievements first (full-colour cards), then locked
  achievements (grey cards with progress bar `current/target`).
- No filters, no sorts, no share button — YAGNI.

**Test list — add to `tests/test_achievements.py`:**
- `test_route_requires_login`
- `test_route_renders_all_achievements_in_grid`

**Verify:** `pytest tests/test_achievements.py -v`; `/achievements` renders earned/locked split.

**Commit:** `feat(achievements): /achievements route + grid template`

---

## Phase 4 — Photo attachments

Mirror the guide storage abstraction — `PHOTO_STORAGE=filesystem`
(default, dev-only) writes to `data/photos/<trip_id>/<photo_id>.<ext>`;
`PHOTO_STORAGE=database` writes bytes into a BLOB column. This is
where the plan is heaviest — three tasks.

**Cloud note:** filesystem mode is dev-only — cloud hosts wipe local
disk on redeploy. Set `PHOTO_STORAGE=database` on the host. Postgres
BLOB storage is fine early; past ~1000 photos, object storage
(S3/Cloudflare R2) is the eventual answer and slots in as a third
backend behind the same `photo_storage.py` interface (`save_photo`,
`read_photo_bytes`, `read_thumbnail_bytes`, `delete_photo`) — no
route changes needed.

### Task 6 — `Photo` model + migration

**Files:**
- Modify: `models.py`
- Create: `scripts/2026-07-10_add_photo_table.py`

**Public surface — `models.py` (new class):**

```python
class Photo(db.Model):
    __tablename__ = "photo"
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    # Polymorphic parent — either a booking, an itinerary_item, or NULL
    # (photo attached at trip level, not a specific chip).
    parent_kind = db.Column(db.String(20), nullable=True)     # "booking"|"itinerary"|None
    parent_id = db.Column(db.Integer, nullable=True, index=True)

    filename = db.Column(db.String(300), nullable=False)     # original filename
    mime = db.Column(db.String(60), nullable=False)          # "image/jpeg" etc.
    size_bytes = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    taken_at = db.Column(db.DateTime, nullable=True)         # from EXIF; nullable

    # Populated only when PHOTO_STORAGE=database. Filesystem mode
    # leaves these NULL and writes bytes to data/photos/<trip>/<id>.<ext>.
    data = db.Column(db.LargeBinary, nullable=True)
    thumbnail = db.Column(db.LargeBinary, nullable=True)     # 400px longest edge

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
```

Add cascade to `Trip`:
```python
photos = db.relationship("Photo", backref="trip", lazy=True, cascade="all, delete-orphan")
```

**Migration:** mirror the guide-storage script. Table + indexes:
- `photo` table with columns above
- `ix_photo_trip_id`, `ix_photo_owner_id`, `ix_photo_parent_id`

**Test list:** none (schema exercised by later tasks).

**Verification:** run full suite; migration against throwaway DB copy.

**Commit:** `feat(photos): Photo model + migration`

---

### Task 7 — Storage backends + thumbnails

**Files:**
- Create: `src/photo_storage.py`
- Create: `tests/test_photo_storage.py`
- Modify: `requirements.txt` (add `Pillow>=10`)
- Modify: `CLAUDE.md` (document `PHOTO_STORAGE` env var — same pattern as `GUIDE_STORAGE`)

**Public surface — `src/photo_storage.py`:**

```python
PHOTO_STORAGE = os.getenv("PHOTO_STORAGE", "filesystem")
THUMB_MAX_EDGE = 400
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic"}

def save_photo(*, trip_id: int, owner_id: int, parent_kind: Optional[str],
               parent_id: Optional[int], upload) -> Photo:
    """upload is a werkzeug FileStorage. Handles validation, EXIF read,
    thumbnail generation, storage-backend dispatch, DB row insert."""

def read_photo_bytes(photo_id: int) -> Tuple[bytes, str]:
    """(data, mime) — dispatches on PHOTO_STORAGE."""

def read_thumbnail_bytes(photo_id: int) -> Tuple[bytes, str]:
    """(data, mime). Same dispatch."""

def delete_photo(photo_id: int) -> None:
    """Removes storage-backed bytes and the DB row. Idempotent."""

def _fs_path(photo: Photo) -> Path: ...
def _make_thumbnail(raw: bytes, mime: str) -> bytes: ...
def _read_exif_taken_at(raw: bytes) -> Optional[datetime]: ...
```

**Rules:**
- Reject uploads with `Content-Length > MAX_UPLOAD_BYTES` before reading.
- Reject mimes not in `ALLOWED_MIMES` (`werkzeug`'s guess, not the header).
- HEIC: convert to JPEG on save (Pillow needs `pillow-heif` — flag in `requirements.txt` if we go this route, otherwise reject HEIC and note it).
- `_fs_path`: `data/photos/<trip_id>/<photo_id>.<ext>`. Ensure parent dir exists.
- Thumbnail: JPEG, quality 80, longest edge = 400px.
- EXIF: read `DateTimeOriginal`; NULL if missing or unparsable — do not raise.

**Test list:**
- `test_save_photo_filesystem_writes_file_and_row`
- `test_save_photo_database_writes_blobs_no_file`
- `test_save_photo_rejects_oversize`
- `test_save_photo_rejects_bad_mime`
- `test_thumbnail_dimensions_clamped_to_400`
- `test_exif_taken_at_populated_when_present`
- `test_read_photo_bytes_dispatches_on_env`
- `test_delete_photo_removes_file_and_row_and_is_idempotent`

Use `tmp_path` fixture for filesystem mode; monkeypatch `PHOTO_STORAGE`
between the two modes.

**Verification:** `.venv/bin/pytest tests/test_photo_storage.py -v`

**Commit:** `feat(photos): dual-mode storage + thumbnails`

---

### Task 8 — Upload routes + display integration

**Files:**
- Modify: `app.py` (upload/list/delete/serve routes)
- Create: `templates/photo_upload.html`
- Modify: `templates/booking_edit.html` (photo strip)
- Modify: `templates/itinerary_edit.html` (photo strip)
- Modify: `templates/trip_overview.html` (photo strip on chips + trip-level gallery)
- Modify: existing map pin popup template (thumbnail if a photo exists)

**Public surface — `app.py`:**

```python
@app.route("/trips/<int:trip_id>/photos/upload", methods=["POST"])
def photo_upload(trip_id): ...  # multipart; parent_kind/parent_id in form

@app.route("/photos/<int:photo_id>/thumb")
def photo_thumb(photo_id): ...  # public within share-token scope; else login

@app.route("/photos/<int:photo_id>")
def photo_full(photo_id): ...

@app.route("/photos/<int:photo_id>/delete", methods=["POST"])
def photo_delete(photo_id): ...
```

All four run through `require_trip_access(trip_id, role="editor")`
except `photo_thumb` / `photo_full` which allow viewer role.

**Template rules:**
- Booking / itinerary edit forms get a "Photos" section with a
  drop-zone (styled `<input type="file" multiple accept="image/*">`)
  and a strip of existing thumbnails, each with a delete link.
- Trip overview: a "Gallery" section listing photos not tied to a
  specific chip. Optional in v1 — the strip on chips is enough.
- Pin popups: if any photo exists for the chip, show the first
  thumbnail above the popup title.
- Yearbook: **out of scope for this task.** Note it in the plan
  file's "follow-ups" section at the bottom.

**Test list — extend `tests/test_photo_storage.py`:**
- `test_upload_route_creates_photo_row`
- `test_upload_route_403_for_viewer`
- `test_thumb_route_returns_bytes`
- `test_delete_route_removes_row`

**Verify:** `pytest tests/test_photo_storage.py -v`; upload JPEG to a booking → thumbnail renders; delete → row and file gone.

**Commit:** `feat(photos): upload + serve + display on chips and pins`

---

## Phase 5 — Quick spend log (C3)

New model, home-currency rollup using the existing exchange-rate
cache. Two tasks: data + core rollup, then routes/templates/budget
integration.

### Task 9 — `SpendEntry` model + parse + rollup

**Files:**
- Modify: `models.py`
- Create: `scripts/2026-07-11_add_spend_entry.py`
- Create: `src/spend.py`
- Create: `tests/test_spend.py`

**Public surface — `models.py` (new class):**

```python
class SpendEntry(db.Model):
    __tablename__ = "spend_entry"
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    day_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False)  # ISO 4217
    # One of: food, transport, lodging, activities, shopping, other
    category = db.Column(db.String(20), nullable=False, default="other")
    description = db.Column(db.String(200), nullable=True)

    # Optional link back to a booking whose "actual" this represents.
    linked_booking_id = db.Column(
        db.Integer, db.ForeignKey("booking.id"), nullable=True, index=True,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
```

Add cascade to `Trip`:
```python
spend_entries = db.relationship("SpendEntry", backref="trip", lazy=True, cascade="all, delete-orphan")
```

**Public surface — `src/spend.py`:**

```python
CATEGORIES: Tuple[str, ...] = ("food", "transport", "lodging",
                               "activities", "shopping", "other")

@dataclass
class ParsedSpend:
    day_date: date
    amount: float
    currency: str
    category: str
    description: Optional[str]
    linked_booking_id: Optional[int]

def parse_spend_form(form: Mapping[str, str], trip: Trip) -> ParsedSpend:
    """Validate + coerce. Raises ValueError with human message on bad input."""

def group_by_day(entries: Iterable[SpendEntry]) -> Dict[date, List[SpendEntry]]: ...
def group_by_category(entries: Iterable[SpendEntry]) -> Dict[str, List[SpendEntry]]: ...

def rollup_totals(entries: Iterable[SpendEntry], home_currency: str,
                  rates: Mapping[str, float]) -> Dict[str, float]:
    """Return {"total_home": X, "food_home": Y, ...} — all in home_currency.
    `rates` is a cross-rate table like the one from exchange_rates.
    Foreign currencies missing from `rates` count as 0 and the caller
    should surface a warning."""

def actuals_vs_budget(trip: Trip, entries: Iterable[SpendEntry],
                      rates: Mapping[str, float]) -> Dict[str, Dict[str, float]]:
    """Per-category: {"food": {"budget_home": B, "actual_home": A,
    "remaining_home": B - A}}. Budget comes from
    src/budget.rollup_bookings_by_category() over the trip's bookings."""
```

**Rules:**
- Empty description → NULL. Whitespace-only → NULL.
- Amount must be positive; `parse_spend_form` raises `ValueError`
  otherwise. Zero is rejected — a zero-dollar entry has no purpose.
- Currency validated against `is_valid_currency` from `src/currency.py`.
- Category not in `CATEGORIES` → default to `"other"`.
- `day_date` must fall within the trip's range or `ValueError`.

**Test list:**
- `test_parse_valid_form_all_fields`
- `test_parse_empty_description_becomes_none`
- `test_parse_rejects_zero_amount`
- `test_parse_rejects_negative_amount`
- `test_parse_rejects_bad_currency`
- `test_parse_rejects_date_outside_trip`
- `test_group_by_day_sorted`
- `test_rollup_converts_to_home_currency`
- `test_rollup_missing_rate_treats_as_zero`
- `test_actuals_vs_budget_returns_per_category_deltas`

**Verification:** `.venv/bin/pytest tests/test_spend.py -v`

**Commit:** `feat(spend): SpendEntry model + parse + rollup`

---

### Task 10 — Routes + templates + budget integration

**Files:**
- Modify: `app.py` (spend routes)
- Create: `templates/spend_list.html`
- Create: `templates/spend_new.html`
- Create: `templates/spend_edit.html`
- Modify: `templates/budget.html` (actuals section)
- Modify: `templates/trip_overview.html` ("Log spend" quick button + today totals)

**Public surface — `app.py`:**

```python
@app.route("/trips/<int:trip_id>/spend")            # GET list
@app.route("/trips/<int:trip_id>/spend/new", methods=["GET", "POST"])
@app.route("/trips/<int:trip_id>/spend/<int:id>/edit", methods=["GET", "POST"])
@app.route("/trips/<int:trip_id>/spend/<int:id>/delete", methods=["POST"])
```

All routes gated by `require_trip_access(trip_id, role="editor")`
except the list which allows viewer.

**Template layout:**
- `spend_list.html`: group by day, total per day in home currency,
  category chips coloured, category totals at the bottom.
- Trip overview quick button: FAB (or nav button) that opens
  `/spend/new` with today's date + trip currency pre-filled.
- Budget page: below the existing "planned" section, add "Actuals"
  showing per-category `budget_home / actual_home / remaining_home`
  bars from `actuals_vs_budget`.

**Test list — extend `tests/test_spend.py`:**
- `test_list_route_shows_entries_grouped_by_day`
- `test_new_route_creates_entry`
- `test_edit_route_updates_entry`
- `test_delete_route_removes_entry`
- `test_viewer_can_see_list_but_not_edit`

**Verify:** `pytest tests/test_spend.py -v`; Log spend → save → budget page shows actuals.

**Commit:** `feat(spend): routes + budget integration`

---

## Phase 6 — Daily journal (C2)

Journal ties into the existing Yearbook — one entry per trip per
day, markdown body. Two tasks: data + core, then routes/UI +
today-view integration.

### Task 11 — `JournalEntry` model + parse

**Files:**
- Modify: `models.py`
- Create: `scripts/2026-07-12_add_journal_entry.py`
- Create: `src/journal.py`
- Create: `tests/test_journal.py`

**Public surface — `models.py` (new class):**

```python
class JournalEntry(db.Model):
    __tablename__ = "journal_entry"
    __table_args__ = (
        db.UniqueConstraint("trip_id", "day_date", name="uq_journal_trip_day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    day_date = db.Column(db.Date, nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)   # markdown source

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```

Add cascade to `Trip`:
```python
journal_entries = db.relationship("JournalEntry", backref="trip", lazy=True, cascade="all, delete-orphan")
```

**Public surface — `src/journal.py`:**

```python
@dataclass
class ParsedJournal:
    day_date: date
    body: str

def parse_journal_form(form: Mapping[str, str], trip: Trip) -> ParsedJournal:
    """Validate + coerce. Raises ValueError on bad input."""

def entries_by_day(trip: Trip) -> Dict[date, JournalEntry]:
    """Fast lookup for the today-view snippet and yearbook."""

def all_days_with_status(trip: Trip) -> List[Tuple[date, bool]]:
    """Every day from start to end paired with (has_entry). Drives the
    list-view calendar strip."""

def render_body(body: str) -> str:
    """Markdown → HTML for read views. Uses the existing `markdown`
    library the app already depends on."""
```

**Rules:**
- Whitespace-only body rejected with `ValueError`.
- `day_date` must be inside the trip's range.
- Unique constraint handles double-submits; the route catches
  `IntegrityError` and redirects to the existing entry's edit view.

**Test list:**
- `test_parse_valid_form`
- `test_parse_rejects_empty_body`
- `test_parse_rejects_whitespace_only_body`
- `test_parse_rejects_date_outside_trip`
- `test_entries_by_day_returns_dict_keyed_by_date`
- `test_all_days_with_status_covers_full_trip_range`

**Verification:** `.venv/bin/pytest tests/test_journal.py -v`

**Commit:** `feat(journal): JournalEntry model + parse helpers`

---

### Task 12 — Routes + templates + today-view integration

**Files:**
- Modify: `app.py`
- Create: `templates/journal_list.html`
- Create: `templates/journal_edit.html`
- Modify: `templates/trip_overview.html` (today-section snippet)
- Modify: existing yearbook template (add Journal section listing entries)

**Public surface — `app.py`:**

```python
@app.route("/trips/<int:trip_id>/journal")                                    # list
@app.route("/trips/<int:trip_id>/journal/<isodate:day>", methods=["GET","POST"])  # edit/create
@app.route("/trips/<int:trip_id>/journal/<isodate:day>/delete", methods=["POST"])
```

Register an `isodate` URL converter (`YYYY-MM-DD` → `date`) at the top
of `app.py` if not already present.

Access: editor for write, viewer for list; the `edit/create` route
returns 403 for viewers on POST.

**Template rules:**
- `journal_list.html`: calendar strip using `all_days_with_status`;
  filled squares link to the entry, empty squares link to create.
- `journal_edit.html`: markdown textarea + preview toggle; one save
  button; delete button below.
- Today-view snippet in `trip_overview.html`: if `derive_status ==
  "in_progress"`, show either the day's existing entry (first ~200
  chars + "edit") or a big "Add today's journal" button.
- Yearbook: append a "Journal" section that lists entries grouped by
  day with `render_body`.

**Test list — extend `tests/test_journal.py`:**
- `test_list_route_shows_calendar_strip`
- `test_edit_route_creates_new_entry`
- `test_edit_route_updates_existing_entry`
- `test_delete_route_removes_entry`
- `test_viewer_get_but_not_post`
- `test_double_submit_redirects_to_edit`

**Verify:** `pytest tests/test_journal.py -v`; in-progress trip today section shows Add journal → save → yearbook shows entry.

**Commit:** `feat(journal): routes + today snippet + yearbook link`

---

## Phase 7 — PWA / offline shell (C1)

Biggest phase. Three tasks: manifest + install metadata, SW cache
strategy, registration + update UX. Lands last so the SW's cache-key
list already knows every route from phases 1–6.

**Revisit-first checkpoint:** before starting Session 8, live with the
iCal feed for one real trip — Calendar apps already work offline, so
iCal covers ~70% of "check my plans without signal." Only pursue if
the remaining 30% (booking confirmations, hotel addresses, packing
list, in-app feel) actually bites. SWs are the most bug-prone piece
of frontend work here — don't invest without confirmed value.

**Cache-key strategy:** static assets cache-first keyed
`vp-static-v{APP_VERSION}`; `/trips/<id>` and children (today,
bookings, itinerary, packing, journal, spend, budget) use
stale-while-revalidate keyed `vp-html-v{APP_VERSION}`. Never
intercept non-GET. `activate` sweeps caches not matching current
keys. `APP_VERSION` bump = full refetch — document in CLAUDE.md.

### Task 13 — Manifest + install metadata

**Files:**
- Create: `static/manifest.json`
- Modify: `templates/base.html` (link + meta tags)
- Add: two icons under `static/img/` — `icon-192.png`, `icon-512.png`.
  Use the existing app-icon file if one exists; otherwise generate
  a simple emoji-on-gradient PNG (32-line Pillow script in the plan
  workspace, don't commit the script).

**`static/manifest.json`:**

```json
{
  "name": "Vacation Planner",
  "short_name": "Trips",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0f172a",
  "theme_color": "#6d28d9",
  "icons": [
    { "src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

**Template additions to `base.html` `<head>`:**

```html
<link rel="manifest" href="{{ url_for('static', filename='manifest.json') }}">
<meta name="theme-color" content="#6d28d9">
<link rel="apple-touch-icon" href="{{ url_for('static', filename='img/icon-192.png') }}">
```

**Test list:** none needed — the file is static.

**Verify:** `/manifest.json` is valid JSON with correct MIME; Chrome devtools → Application → Manifest shows no errors.

**Commit:** `feat(pwa): manifest + install metadata`

---

### Task 14 — Service worker

**Files:**
- Create: `templates/service-worker.js.j2`  (Jinja template, NOT static)
- Modify: `app.py` (route to serve SW at `/service-worker.js` root-scope)

**Why a template, not a static file:** the SW file must contain a
per-deploy `APP_VERSION` string so browsers bust cache when we ship.
On cloud hosts we don't hand-edit files at deploy time — we set
`APP_VERSION=<git-sha>` as an env var and render it in.

**`app.py` addition:**

```python
@app.route("/service-worker.js")
def service_worker():
    body = render_template("service-worker.js.j2",
                           app_version=os.getenv("APP_VERSION", "dev"))
    resp = make_response(body)
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp
```

**`templates/service-worker.js.j2` public shape:**

```javascript
const APP_VERSION = "{{ app_version }}";  // env-injected at request time
const STATIC_CACHE = `vp-static-v${APP_VERSION}`;
const HTML_CACHE   = `vp-html-v${APP_VERSION}`;
const STATIC_ASSETS = [
  "/", "/offline",
  "/static/css/app.css",
  "/static/js/countdown.js",
  "/static/js/pwa-register.js",
  "/static/img/icon-192.png",
  "/static/img/icon-512.png",
];

self.addEventListener("install",  e => e.waitUntil(precacheStatic()));
self.addEventListener("activate", e => e.waitUntil(cleanupOldCaches()));
self.addEventListener("fetch",    e => e.respondWith(route(e.request)));

async function precacheStatic() { /* addAll(STATIC_ASSETS) */ }
async function cleanupOldCaches() { /* keep only current keys */ }
async function route(request) {
  if (request.method !== "GET") return fetch(request);
  if (isStatic(request))  return cacheFirst(request, STATIC_CACHE);
  if (isTripHtml(request)) return staleWhileRevalidate(request, HTML_CACHE);
  return fetch(request).catch(() => caches.match("/offline"));
}
```

**Create: `templates/offline.html`** — extends `base.html`, shows
"You're offline. Trips already loaded should still work." + a
retry button.

**Rules:**
- `isTripHtml(request)`: regex `^/trips/\d+(/|$)`.
- `staleWhileRevalidate`: return cached response immediately, then
  fetch and update cache in background. On network failure with
  no cache: fall through to `/offline`.
- Do NOT cache responses with `Cache-Control: no-store` or `private`
  (the iCal feed is `private` — it's a GET but we skip caching it).

**Test list — `tests/test_pwa_shell.py`:**
- `test_service_worker_served_with_no_cache_and_root_scope_header`
- `test_manifest_served_as_application_manifest_json`
- `test_offline_route_returns_200`
- `test_static_assets_list_matches_files_present`

**Verify:** `pytest tests/test_pwa_shell.py -v`; SW installed in devtools; Offline network → `/trips/<id>` renders from cache.

**Commit:** `feat(pwa): service worker + offline fallback`

---

### Task 15 — Registration + update toast

**Files:**
- Create: `static/js/pwa-register.js`
- Modify: `templates/base.html` (script tag before `</body>`)

**`static/js/pwa-register.js` shape:**

```javascript
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js")
      .then(reg => reg.addEventListener("updatefound", () => onUpdate(reg)));
  });
}
function onUpdate(reg) { /* show a bottom toast "New version — Refresh" */ }
```

**Toast markup:** a fixed-bottom `<div id="vp-update-toast">` with a
"Refresh" button that calls `window.location.reload()`. Styled in
`static/css/app.css`. Hidden by default; `onUpdate` unhides it.

**Rules:**
- Do not register the SW on `file://` (guards `webapp-testing`).
- Do not register during test runs — check `navigator.userAgent`
  for `HeadlessChrome` and skip if the URL includes `?nosw=1`
  (query param the tests set).

**Test list — extend `tests/test_pwa_shell.py`:**
- `test_register_script_included_in_base_template`

**Verify:** `pytest tests/test_pwa_shell.py -v`; bump `APP_VERSION` → reload → update toast appears.

**Commit:** `feat(pwa): SW registration + update toast`

## Follow-ups + rules

Deferred: yearbook photo/prose (post-Tasks 8/12), push notifications
(post-PWA), icon PNGs (generate+commit if missing). `PHOTO_STORAGE=filesystem`
uploads sit outside `vacation.db` backups — note in CLAUDE.md. Every
`<int:trip_id>` route uses `require_trip_access`; `trip_id` FK models get
`cascade="all, delete-orphan"` on `Trip`; every new module gets `logger`.
Frontend verification per CLAUDE.md after Tasks 3, 8, 10, 12, 15.

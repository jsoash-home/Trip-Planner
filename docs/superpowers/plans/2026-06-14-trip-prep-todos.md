# Trip-Prep To-Dos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the trip-prep to-do system per `docs/superpowers/specs/2026-06-14-trip-prep-todos-design.md` — three surfaces (dashboard panel, `/prep`, per-trip prep tab) on one `TripPrepItem` model + `TripPrepLink` link table, with paste-to-create, smart trip-relative deadlines, and a done→packing-list loop.

**Architecture:** Mirrors the existing packing/itinerary feature pattern. Pure helpers in `src/`, models in `models.py`, routes in `app.py`, Jinja templates, vanilla JS + Bootstrap 5. New dependency: `beautifulsoup4`. No LLM in v1; v2 hook reserved for AI suggestions.

**Tech Stack:** Flask, SQLAlchemy, Jinja2, Bootstrap 5, vanilla JS, `requests` + `beautifulsoup4` for URL metadata scraping, pytest with the in-memory DB pattern in `tests/conftest.py`.

**Reference for behavior + edge cases:** the spec at `docs/superpowers/specs/2026-06-14-trip-prep-todos-design.md`. Tasks below capture the public surface and test list — defer to the spec for "why" and behavior nuance.

---

## File map

| File | Status | Purpose |
|---|---|---|
| `requirements.txt` | modified | add `beautifulsoup4>=4.12` |
| `models.py` | modified | `TripPrepItem` + `TripPrepLink` models, relationships |
| `src/url_metadata.py` | created | OG / `<title>` extraction + impure `fetch_url_metadata` |
| `src/prep_helpers.py` | created | categories, due-date math, urgency, sort, form parse, group, dashboard slice |
| `tests/test_url_metadata.py` | created | unit tests for metadata module |
| `tests/test_prep_helpers.py` | created | unit tests for pure helpers |
| `tests/test_routes.py` | modified | route integration tests (extends existing file) |
| `app.py` | modified | 7 new routes + `_ensure_prep_tables()` + dashboard wiring |
| `templates/dashboard.html` | modified | include the new `_prep_panel.html` partial |
| `templates/_prep_panel.html` | created | dashboard widget — top-5 items + paste-to-create |
| `templates/prep.html` | created | `/prep` user-level page |
| `templates/trip_prep.html` | created | `/trips/<id>/prep` per-trip tab |
| `templates/_prep_item_row.html` | created | shared macro — one row of a prep item (used by `prep.html`, `trip_prep.html`, `_prep_panel.html`) |
| `templates/trip_overview.html` | modified | add Prep tab to the per-trip nav |
| `static/js/prep.js` | created | small vanilla-JS niceties (link-row visibility, packing-prompt dismiss) |
| `static/css/app.css` | modified | prep-specific styles (urgency pills, thumbnail tiles) |
| `docs/PHASE_3_ROADMAP.md` | modified | add a "Phase 4" section header and link this plan / spec under it |

---

## Task 1: Add `beautifulsoup4` dependency

**Files:**
- Modify: `requirements.txt`

**Public surface:**
- Add line: `beautifulsoup4>=4.12`

**Test list:** none (dependency-only).

**Commit:** `chore: add beautifulsoup4 for url-metadata scraping`

Then run `python3 -m pip install -r requirements.txt` to install locally before any task imports it.

---

## Task 2: `TripPrepItem` + `TripPrepLink` models + migration helper

**Files:**
- Modify: `models.py` (add models at the bottom)
- Modify: `app.py` (add `_ensure_prep_tables()` helper, call it after `db.create_all()` in both SQLite + Postgres branches)

**Models — `TripPrepItem`:**

| Column | Type | Constraints |
|---|---|---|
| `id` | `db.Integer` | PK |
| `owner_id` | `db.Integer` | `FK("user.id"), nullable=False, index=True` |
| `trip_id` | `db.Integer` | `FK("trip.id"), nullable=True, index=True` |
| `title` | `db.String(200)` | `nullable=False` |
| `notes` | `db.Text` | `nullable=True` |
| `category` | `db.String(20)` | `nullable=False, default="other"` |
| `link_url` | `db.String(800)` | `nullable=True` |
| `link_image_url` | `db.String(800)` | `nullable=True` |
| `done` | `db.Boolean` | `nullable=False, default=False` |
| `done_at` | `db.DateTime` | `nullable=True` |
| `due_offset_days` | `db.Integer` | `nullable=True` |
| `packing_prompt_dismissed_at` | `db.DateTime` | `nullable=True` |
| `created_at` | `db.DateTime` | `nullable=False, default=datetime.utcnow` |
| `sort_order` | `db.Integer` | `nullable=False, default=0` |

Relationships:
- `owner = db.relationship("User", backref=db.backref("trip_prep_items", lazy=True))`
- `trip = db.relationship("Trip", backref=db.backref("prep_items", lazy=True))`
- `links = db.relationship("TripPrepLink", backref="item", cascade="all, delete-orphan", lazy=True)`

**Models — `TripPrepLink`:**

| Column | Type | Constraints |
|---|---|---|
| `id` | `db.Integer` | PK |
| `trip_prep_item_id` | `db.Integer` | `FK("trip_prep_item.id"), nullable=False, index=True` |
| `trip_id` | `db.Integer` | `FK("trip.id"), nullable=False, index=True` |
| `due_offset_days` | `db.Integer` | `nullable=True` |
| `created_at` | `db.DateTime` | `nullable=False, default=datetime.utcnow` |

Table args:
```python
__table_args__ = (
    db.UniqueConstraint("trip_prep_item_id", "trip_id", name="uq_prep_link_item_trip"),
)
```

Relationship: `trip = db.relationship("Trip", backref=db.backref("prep_links", lazy=True))`

**`_ensure_prep_tables()` in `app.py`:** idempotent — `inspect(db.engine).get_table_names()` check before creating either table. Same shape as `_ensure_weather_columns` and the home_currency helper.

**Test list (in `tests/test_routes.py`):**
- `test_trip_prep_item_persists_round_trip` — create + fetch + assert all fields
- `test_trip_prep_link_unique_constraint` — IntegrityError on duplicate `(item_id, trip_id)`
- `test_trip_prep_item_cascade_deletes_links` — delete item, link row gone
- `test_ensure_prep_tables_is_idempotent` — call twice, no error, tables still exist

**Commit:** `feat: TripPrepItem + TripPrepLink models + ensure-tables migration`

---

## Task 3: `src/prep_helpers.py` — constants + due-date math + urgency

**Files:**
- Create: `src/prep_helpers.py`
- Create: `tests/test_prep_helpers.py`

**Public surface:**

```python
PREP_CATEGORIES: Tuple[Tuple[str, str, str], ...]  # (code, label, emoji)
PREP_CATEGORY_CODES: frozenset
PREP_CATEGORY_LABELS: Dict[str, str]
PREP_CATEGORY_EMOJIS: Dict[str, str]

URGENCY_OVERDUE = "overdue"
URGENCY_URGENT = "urgent"      # ≤ 7 days
URGENCY_SOON = "soon"          # ≤ 30 days
URGENCY_LATER = "later"
URGENCY_NONE = "none"

def category_label(code: str) -> str
def category_emoji(code: str) -> str
def due_date(trip_start: Optional[date], offset_days: Optional[int]) -> Optional[date]
def urgency_bucket(today: date, due: Optional[date]) -> str
```

**Categories (final list):**

```python
PREP_CATEGORIES = (
    ("gear",     "Gear",     "🎒"),
    ("buy",      "Buy",      "🛒"),
    ("research", "Research", "🔍"),
    ("book",     "Book",     "📅"),
    ("admin",    "Admin",    "📋"),
    ("other",    "Other",    "📦"),
)
```

**Test list:**
- `test_category_label_known`
- `test_category_label_unknown_returns_code`
- `test_category_emoji_known`
- `test_due_date_with_offset`
- `test_due_date_no_offset_returns_none`
- `test_due_date_no_trip_start_returns_none`
- `test_urgency_bucket_overdue` (due in past)
- `test_urgency_bucket_urgent_at_7_days`
- `test_urgency_bucket_soon_at_30_days`
- `test_urgency_bucket_later_at_31_days`
- `test_urgency_bucket_none_when_due_is_none`

**Commit:** `feat: src/prep_helpers.py — categories + due-date + urgency`

---

## Task 4: `src/prep_helpers.py` — sort, parse, group, dashboard slice

**Files:**
- Modify: `src/prep_helpers.py`
- Modify: `tests/test_prep_helpers.py`

**Public surface:**

```python
def sort_key(item, today: date) -> Tuple
# Order: urgency rank (overdue=0, urgent=1, soon=2, later=3, none=4),
# then due_date asc, then sort_order asc, then created_at asc.
# Done items always sort after open items regardless of urgency.

def parse_prep_form(form: Mapping[str, str]) -> dict
# Returns {"title", "notes", "category", "due_offset_days", "trip_id"}.
# Defaults: category -> "other" if missing/unknown. due_offset_days -> None on
# blank or invalid. trip_id -> None if blank or "none". Title is stripped.
# Raises ValueError when title is empty after strip.

def group_items_by_category(items) -> Dict[str, list]
# Keys are category codes in PREP_CATEGORIES display order. Open items first,
# then a synthetic "done" bucket at the end keyed by literal "done".

def items_for_dashboard_panel(items, today: date, limit: int = 5) -> list
# Open items only, sorted by sort_key, sliced to `limit`.
```

**Test list (additions):**
- `test_sort_key_overdue_before_urgent`
- `test_sort_key_done_items_last_regardless_of_urgency`
- `test_sort_key_tiebreaker_uses_sort_order_then_created_at`
- `test_parse_prep_form_full_input`
- `test_parse_prep_form_strips_title`
- `test_parse_prep_form_empty_title_raises`
- `test_parse_prep_form_unknown_category_defaults_to_other`
- `test_parse_prep_form_blank_offset_returns_none`
- `test_parse_prep_form_non_integer_offset_returns_none`
- `test_parse_prep_form_blank_trip_id_returns_none`
- `test_group_items_by_category_preserves_display_order`
- `test_group_items_by_category_done_bucket_at_end`
- `test_items_for_dashboard_panel_excludes_done`
- `test_items_for_dashboard_panel_respects_limit`
- `test_items_for_dashboard_panel_sorts_by_urgency`

**Commit:** `feat: prep_helpers — sort, parse, group, dashboard slice`

---

## Task 5: `src/url_metadata.py` — pure helpers

**Files:**
- Create: `src/url_metadata.py`
- Create: `tests/test_url_metadata.py`

**Public surface:**

```python
URL_RE: re.Pattern  # matches "http(s)://..." with optional trailing punctuation stripped

def looks_like_url(text: str) -> bool
# Returns True iff stripped text matches URL_RE.

def extract_metadata_from_html(html: str, source_url: str) -> dict
# Returns {"title": str, "image_url": Optional[str], "source_url": str}.
# Preference order for title:
#   1. <meta property="og:title" content="...">
#   2. <meta name="twitter:title" content="...">
#   3. <title>...</title>
#   4. source_url (fallback)
# Preference order for image_url:
#   1. <meta property="og:image" content="...">
#   2. <meta name="twitter:image" content="...">
#   3. None
# Relative image URLs are resolved against source_url via urljoin.
# Whitespace stripped on title; titles longer than 200 chars truncated to 197 + "…".
```

**Test list:**
- `test_looks_like_url_http`
- `test_looks_like_url_https`
- `test_looks_like_url_with_surrounding_whitespace`
- `test_looks_like_url_rejects_plain_text`
- `test_looks_like_url_rejects_mailto`
- `test_looks_like_url_rejects_text_containing_url` (only-URL is True; URL-with-prefix-text is False — keeps the rule simple)
- `test_extract_metadata_prefers_og_title`
- `test_extract_metadata_falls_back_to_twitter_title`
- `test_extract_metadata_falls_back_to_title_tag`
- `test_extract_metadata_falls_back_to_source_url`
- `test_extract_metadata_prefers_og_image`
- `test_extract_metadata_no_image_returns_none`
- `test_extract_metadata_resolves_relative_image_url`
- `test_extract_metadata_truncates_long_title`
- `test_extract_metadata_strips_title_whitespace`

**Commit:** `feat: url_metadata pure helpers — OG/title extraction`

---

## Task 6: `src/url_metadata.py` — impure `fetch_url_metadata`

**Files:**
- Modify: `src/url_metadata.py`
- Modify: `tests/test_url_metadata.py`

**Public surface:**

```python
FETCH_TIMEOUT_SECONDS: float = 5.0
FETCH_USER_AGENT: str = "Mozilla/5.0 (compatible; VacationPlanner/1.0)"

def fetch_url_metadata(url: str, timeout: float = FETCH_TIMEOUT_SECONDS) -> dict
# Returns the same shape as extract_metadata_from_html.
# Silent failure: any requests exception, non-200 status, non-HTML content type,
# or parse exception is caught and logged at WARNING, and the function returns
# {"title": url, "image_url": None, "source_url": url}.
# Uses requests.get(url, timeout=timeout, headers={"User-Agent": FETCH_USER_AGENT}).
# Content-Type sniff: response.headers.get("content-type", "").startswith("text/html")
# or "application/xhtml" — otherwise treated as a failure (fall back to URL).
```

**Test list (additions, all mock `requests.get`):**
- `test_fetch_url_metadata_success_returns_title_and_image`
- `test_fetch_url_metadata_timeout_falls_back_to_url` (verifies WARNING logged)
- `test_fetch_url_metadata_http_404_falls_back_to_url`
- `test_fetch_url_metadata_http_500_falls_back_to_url`
- `test_fetch_url_metadata_non_html_content_type_falls_back_to_url`
- `test_fetch_url_metadata_malformed_html_falls_back_to_url`
- `test_fetch_url_metadata_passes_timeout_and_user_agent_to_requests`

**Commit:** `feat: url_metadata.fetch_url_metadata — silent-failure HTTP fetch`

---

## Task 7: `GET /prep` route + template skeleton (read-only)

**Files:**
- Modify: `app.py`
- Create: `templates/prep.html`
- Modify: `tests/test_routes.py`

**Route:**

```python
@app.route("/prep", methods=["GET"])
@login_required
def prep_page():
    """User-level cross-trip prep list. Owner-only — cross-trip items
    are never shared with collaborators."""
```

Query: `TripPrepItem.query.filter_by(owner_id=current_user.id, trip_id=None).all()`.
Render `templates/prep.html` with context: `items`, `grouped=group_items_by_category(items)`, `today=date.today()`, `categories=PREP_CATEGORIES`, `trips=current_user.trips` (for the optional "link to trip" field later).

**Template (`templates/prep.html`) — read-only skeleton:**
- Extends `base.html`.
- Page title: "Trip prep".
- Empty state: friendly nudge with the user's first name + Bootstrap card explaining what this is.
- For each non-empty category group: a card with the category emoji + label header and rows of items (title, optional thumbnail tile, optional urgency pill).
- Done group rendered last, collapsed by default (Bootstrap collapse), title strikethrough.

Forms / inputs come in Task 8 — this task is **read-only** so we can integration-test the query and template rendering without create-flow coupling.

**Test list (additions in `tests/test_routes.py`):**
- `test_prep_page_requires_login`
- `test_prep_page_renders_for_owner`
- `test_prep_page_empty_state_when_no_items`
- `test_prep_page_renders_items_grouped_by_category`
- `test_prep_page_hides_per_trip_items` (those belong to the per-trip tab)
- `test_prep_page_hides_other_users_items`

**Commit:** `feat: GET /prep — user-level cross-trip prep list (read-only)`

---

## Task 8: `POST /prep` create + paste-to-create flow

**Files:**
- Modify: `app.py`
- Modify: `templates/prep.html` (add create form at top)
- Modify: `tests/test_routes.py`

**Route:**

```python
@app.route("/prep", methods=["POST"])
@login_required
def prep_create():
    """Create a new TripPrepItem. Handles both:
    - plain text title -> direct create
    - URL paste -> fetch_url_metadata enrich, then create"""
```

Behavior:
1. Read `request.form` — single field `input` (the combined paste-or-type field), plus optional `category`, `notes`, `due_offset_days`, `trip_id` from the more detailed form on `/prep`.
2. If `looks_like_url(input)`: call `fetch_url_metadata(input)`. Use returned `title` for the item's title; store `input` as `link_url`; store image as `link_image_url`.
3. Else: treat `input` as the title.
4. If `trip_id` is provided AND the trip belongs to the user (owner or shared as editor): set `TripPrepItem.trip_id` directly (NOT a cross-trip item).
5. Otherwise: `trip_id=None` (cross-trip item).
6. `owner_id=current_user.id`. `category` defaults to `other`.
7. `db.session.add(...); db.session.commit()`.
8. Flash success: "Added '<title>'."
9. Redirect to `request.referrer or url_for("prep_page")`.

**Template change:** sticky create card at the top of `prep.html` with the single paste-or-type input + an expandable details section (Bootstrap collapse) for category / notes / due offset / link-to-trip.

**Test list (additions):**
- `test_prep_create_plain_text_title`
- `test_prep_create_with_url_calls_fetch_metadata` (mock `fetch_url_metadata`)
- `test_prep_create_url_failure_still_creates_item_with_url_as_title` (mock returns the fallback shape)
- `test_prep_create_assigns_owner_to_current_user`
- `test_prep_create_with_trip_id_creates_per_trip_item`
- `test_prep_create_with_other_users_trip_id_rejects` (403 or rewrites to cross-trip — pick: 403)
- `test_prep_create_defaults_category_to_other`
- `test_prep_create_empty_input_shows_error_flash`

**Commit:** `feat: POST /prep — create + paste-to-create URL enrich`

---

## Task 9: `POST /prep/<id>/toggle` + done_at logic

**Files:**
- Modify: `app.py`
- Modify: `templates/prep.html` (the checkbox already exists from Task 7; wire form action)
- Modify: `tests/test_routes.py`

**Route:**

```python
@app.route("/prep/<int:item_id>/toggle", methods=["POST"])
@login_required
def prep_toggle(item_id: int):
    """Flip the done flag. Sets/clears done_at. May fire the
    done -> packing-list flash banner (handled in Task 13)."""
```

Behavior:
1. Load item; 404 if missing.
2. Access check: owner can always toggle. For per-trip items, also allow editors on that trip via the existing `require_trip_access(trip_id, "editor")` helper. Otherwise 403.
3. Flip `done`. If now True, set `done_at = datetime.utcnow()`. If now False, set `done_at = None` AND `packing_prompt_dismissed_at = None` (reopens the prompt for the next toggle).
4. Commit. Redirect to `request.referrer or url_for("prep_page")`.

The packing prompt itself is implemented in Task 13 — this task just lays down the toggle + state. Document the hook in a one-line comment in the handler so Task 13 has an obvious insertion point.

**Test list (additions):**
- `test_prep_toggle_owner_can_flip_done`
- `test_prep_toggle_sets_done_at_when_marking_done`
- `test_prep_toggle_clears_done_at_when_marking_undone`
- `test_prep_toggle_resets_packing_prompt_dismissed_at_when_undone`
- `test_prep_toggle_404_when_missing`
- `test_prep_toggle_403_for_unrelated_user_on_cross_trip_item`
- `test_prep_toggle_403_for_viewer_on_per_trip_item`
- `test_prep_toggle_allows_editor_collaborator_on_per_trip_item`

**Commit:** `feat: POST /prep/<id>/toggle — done flip + done_at + reset prompt`

---

## Task 10: `POST /prep/<id>/edit` + `POST /prep/<id>/delete`

**Files:**
- Modify: `app.py`
- Modify: `templates/prep.html` (per-row edit + delete buttons; edit opens a modal with the same fields as the create form)
- Modify: `tests/test_routes.py`

**Routes:**

```python
@app.route("/prep/<int:item_id>/edit", methods=["POST"])
@login_required
def prep_edit(item_id: int):
    """Update title, notes, category, due_offset_days, trip_id."""

@app.route("/prep/<int:item_id>/delete", methods=["POST"])
@login_required
def prep_delete(item_id: int):
    """Delete the item. Cascade removes its links via the
    cascade='all, delete-orphan' relationship from Task 2."""
```

Behavior — `prep_edit`:
- Access check identical to `prep_toggle`.
- Use `parse_prep_form(request.form)` (same helper as create).
- If `trip_id` changes from set→None or None→set, the cross/per-trip nature changes. Allowed — just update the field.
- If `trip_id` changes to a trip the user has no access to, 403.
- Flash "Updated '<title>'." Redirect to referrer.

Behavior — `prep_delete`:
- Access check identical to `prep_toggle`.
- `db.session.delete(item); db.session.commit()`.
- Flash "Deleted '<title>'." Redirect to `request.referrer or url_for("prep_page")`.

**Test list (additions):**
- `test_prep_edit_owner_updates_title_and_notes`
- `test_prep_edit_changes_category`
- `test_prep_edit_changes_due_offset`
- `test_prep_edit_changing_trip_id_to_inaccessible_trip_rejected`
- `test_prep_edit_empty_title_returns_error_flash`
- `test_prep_delete_owner_removes_item`
- `test_prep_delete_cascades_links`
- `test_prep_edit_403_for_unrelated_user`
- `test_prep_delete_403_for_viewer_collaborator`

**Commit:** `feat: POST /prep/<id>/edit + /delete`

---

## Task 11: `GET /trips/<id>/prep` + per-trip tab + nav update

**Files:**
- Modify: `app.py`
- Create: `templates/trip_prep.html`
- Modify: `templates/trip_overview.html` (add "Prep" link to the nav)
- Modify: `tests/test_routes.py`

**Route:**

```python
@app.route("/trips/<int:trip_id>/prep", methods=["GET"])
@login_required
def trip_prep_tab(trip_id: int):
    """Per-trip prep tab. Visible per the trip's sharing rules.
    Splits items into:
      - Linked from your gear: cross-trip items linked to this trip
        via TripPrepLink (owner only — invisible to collaborators).
      - Trip-specific: items with trip_id=<this trip>, visible per
        sharing rules."""
```

Behavior:
- `require_trip_access(trip_id, "viewer")`.
- `trip = Trip.query.get_or_404(trip_id)`.
- `is_owner = trip.owner_id == current_user.id`.
- Trip-specific items: `TripPrepItem.query.filter_by(trip_id=trip.id).all()`.
- Linked items: only when `is_owner=True` — `TripPrepItem.query.join(TripPrepLink).filter(TripPrepLink.trip_id==trip.id, TripPrepItem.owner_id==current_user.id).all()`. For viewer collaborators on a shared trip the linked-from-gear section is hidden entirely.
- Render `trip_prep.html` with `trip`, `trip_specific`, `linked` (or `None`), `today`.

**Template (`trip_prep.html`):**
- Extends `base.html`.
- Includes the per-trip nav from `trip_overview.html` (existing macro / partial — follow the same pattern Itinerary / Packing / Budget use).
- Inline create input at top, with `trip_id` hidden field pre-filled to this trip (so create defaults to per-trip).
- Two sections: "Linked from your gear" (when present) and "Trip-specific". Each renders item rows the same way `prep.html` does — share a `_prep_item_row.html` macro between the two templates (extract during this task).

**Template change (`trip_overview.html`):** add a "Prep" entry to the per-trip nav between "Bookings" and "Packing".

**Test list (additions):**
- `test_trip_prep_tab_owner_sees_trip_specific_items`
- `test_trip_prep_tab_owner_sees_linked_cross_trip_items`
- `test_trip_prep_tab_editor_collaborator_sees_trip_specific_only`
- `test_trip_prep_tab_viewer_collaborator_sees_trip_specific_only_readonly`
- `test_trip_prep_tab_viewer_collaborator_does_not_see_linked_section`
- `test_trip_prep_tab_404_when_trip_missing`
- `test_trip_prep_tab_403_when_not_a_collaborator`
- `test_trip_overview_nav_includes_prep_link`

**Commit:** `feat: /trips/<id>/prep — per-trip prep tab + nav entry`

---

## Task 12: `TripPrepLink` create + delete routes

**Files:**
- Modify: `app.py`
- Modify: `templates/prep.html` (per-row "Link to trip" dropdown for cross-trip items)
- Modify: `templates/trip_prep.html` (per-row "Unlink" button on linked items)
- Modify: `tests/test_routes.py`

**Routes:**

```python
@app.route("/prep/<int:item_id>/link", methods=["POST"])
@login_required
def prep_link_create(item_id: int):
    """Link a cross-trip item to a trip. Body: trip_id, optional
    due_offset_days. 400 if item is per-trip (has its own trip_id).
    403 if user is not the item owner."""

@app.route("/prep/<int:item_id>/link/<int:link_id>", methods=["POST"])
@login_required
def prep_link_delete(item_id: int, link_id: int):
    """Delete the link. 404 if link doesn't belong to this item.
    403 if user is not the item owner."""
```

Behavior — `prep_link_create`:
- Load item; 404 if missing. 403 if `item.owner_id != current_user.id`. 400 if `item.trip_id is not None` (per-trip items can't be linked).
- Parse `trip_id` from form; 400 if missing.
- Verify the user has at least viewer access to the target trip (so we don't leak existence of trips they can't see); 403 otherwise.
- Reject duplicate link (unique constraint will too, but check first for a clean flash message).
- Create `TripPrepLink(trip_prep_item_id=item.id, trip_id=trip_id, due_offset_days=offset_or_none)`.
- Redirect to referrer with flash.

Behavior — `prep_link_delete`:
- Load link by `link_id`. 404 if missing or `link.trip_prep_item_id != item_id`.
- Load item; 403 if not owner.
- Delete link, commit, flash, redirect.

**Test list (additions):**
- `test_prep_link_create_attaches_link`
- `test_prep_link_create_stores_offset`
- `test_prep_link_create_400_when_item_is_per_trip`
- `test_prep_link_create_400_when_trip_id_missing`
- `test_prep_link_create_403_when_user_not_owner_of_item`
- `test_prep_link_create_403_when_user_has_no_access_to_target_trip`
- `test_prep_link_create_rejects_duplicate_link`
- `test_prep_link_delete_removes_link`
- `test_prep_link_delete_404_when_link_does_not_belong_to_item`
- `test_prep_link_delete_403_when_user_not_owner_of_item`

**Commit:** `feat: POST /prep/<id>/link + /link/<link_id> — link CRUD`

---

## Task 13: Done → packing-list prompt

**Files:**
- Modify: `app.py` (extend `prep_toggle` from Task 9; add `prep_packing_decision` route)
- Modify: `templates/base.html` (the flash partial already renders flashes; add a slightly richer flash type "decision" that can include action buttons — see template change below)
- Modify: `tests/test_routes.py`

**Behavior in `prep_toggle` (Task 9 left a hook for this):**

After flipping to `done=True`, check:
1. `item.category in {"gear", "buy"}`
2. `item.packing_prompt_dismissed_at is None`
3. Exactly one trip is linked: either `item.trip_id is not None`, OR `item.trip_id is None and len(item.links) == 1`.

If all three hold, push a special flash:

```python
flash(
    {
        "type": "prep_packing_prompt",
        "item_id": item.id,
        "item_title": item.title,
        "trip_id": resolved_trip_id,
        "trip_name": resolved_trip.name,
    },
    "decision",
)
```

The `"decision"` category is the new flash type the template handles.

**Template change (`templates/base.html` flash block):** when a flash has category `decision` and the payload is a `dict` with `type == "prep_packing_prompt"`, render a card with the question and two POST forms: `/prep/<id>/packing-decision?action=add` and `/prep/<id>/packing-decision?action=dismiss`. Anything else falls through to the existing flash rendering unchanged.

**Route:**

```python
@app.route("/prep/<int:item_id>/packing-decision", methods=["POST"])
@login_required
def prep_packing_decision(item_id: int):
    """Accept (?action=add) or dismiss (?action=dismiss) the
    done -> packing prompt."""
```

Behavior:
- Load item; 404 if missing. 403 if not owner.
- `action = request.args.get("action")`; 400 unless in `{"add", "dismiss"}`.
- Resolve the linked trip the same way `prep_toggle` did (per-trip `item.trip_id` OR the single link's `trip_id`). 400 if it can't be resolved (shouldn't happen — defensive).
- Always set `item.packing_prompt_dismissed_at = datetime.utcnow()`.
- If `action == "add"`: create `PackingItem(trip_id=<resolved>, name=item.title, category="other", packed=False)`.
- Commit. Flash plain success message. Redirect to referrer.

**Test list (additions):**
- `test_done_packing_prompt_fires_for_gear_per_trip_item`
- `test_done_packing_prompt_fires_for_buy_with_single_link`
- `test_done_packing_prompt_does_not_fire_for_research_category`
- `test_done_packing_prompt_does_not_fire_for_cross_trip_with_zero_links`
- `test_done_packing_prompt_does_not_fire_for_cross_trip_with_multiple_links`
- `test_done_packing_prompt_does_not_fire_when_already_dismissed`
- `test_done_packing_prompt_fires_again_after_undone_then_done` (because Task 9 resets `packing_prompt_dismissed_at` on undone — confirms that path is wired)
- `test_packing_decision_add_creates_packing_item`
- `test_packing_decision_dismiss_does_not_create_packing_item`
- `test_packing_decision_add_marks_dismissed_so_prompt_does_not_refire`
- `test_packing_decision_403_when_not_owner`
- `test_packing_decision_400_when_action_invalid`

**Commit:** `feat: done -> packing-list prompt + decision route`

---

## Task 14: Dashboard panel partial + include

**Files:**
- Create: `templates/_prep_panel.html`
- Modify: `templates/dashboard.html` (include the partial below the trip-cards section)
- Modify: `app.py` (the dashboard route — pass `prep_panel_items` to the template)
- Modify: `static/css/app.css` (urgency pill colors, thumbnail tile size)
- Modify: `tests/test_routes.py`

**Dashboard route change:**
- Query: open `TripPrepItem` rows for `owner_id=current_user.id` (any `trip_id`).
- `prep_panel_items = items_for_dashboard_panel(items, date.today(), limit=5)`.
- Pass to template; the existing dashboard context is otherwise unchanged.

**Partial (`templates/_prep_panel.html`):**
- Hidden entirely when `prep_panel_items` is empty.
- Title row: "🎒 Trip prep" + "See all → /prep" link.
- The same paste-or-type input as on `/prep` (POSTs to `/prep` with the referrer set to `/`).
- Up to 5 item rows: checkbox (POSTs to `/prep/<id>/toggle`), thumbnail tile (image if `link_image_url`, otherwise the category emoji), title + per-row subtitle ("cross-trip · linked to <trip>" or "per-trip · <trip name>"), optional urgency pill.

**CSS additions:**
- `.prep-pill--overdue` (red), `.prep-pill--urgent` (amber), `.prep-pill--soon` (blue), `.prep-pill--later`, `.prep-pill--none`.
- `.prep-thumb` (40 × 40, rounded, centered emoji fallback).

**Test list (additions):**
- `test_dashboard_includes_prep_panel_when_items_exist`
- `test_dashboard_hides_prep_panel_when_no_items`
- `test_dashboard_prep_panel_shows_at_most_five_items`
- `test_dashboard_prep_panel_excludes_done_items`
- `test_dashboard_prep_panel_includes_per_trip_and_cross_trip_items`
- `test_dashboard_prep_panel_other_users_items_hidden`

**Commit:** `feat: dashboard trip-prep panel + urgency styles`

---

## Task 15: `static/js/prep.js` polish + final integration

**Files:**
- Create: `static/js/prep.js`
- Modify: `templates/base.html` (include the script when the user is authenticated)
- Modify: `docs/PHASE_3_ROADMAP.md` (add "Phase 4" header with this feature linked)
- Modify: `docs/PHASE_3_ROADMAP.md` (mark v1 trip-prep to-dos ✓ shipped under Phase 4 with spec + plan links)

**`static/js/prep.js` scope:**
- Single small helper: progressively enhance the paste-or-type input. On `paste` event, if the pasted text looks like a URL, show a small "Fetching link…" badge that disappears when the form submits or after 6 s (best-effort UX — no functional dependency).
- Wrap localStorage access in try/catch (private browsing).
- No external deps.

**Roadmap update (`docs/PHASE_3_ROADMAP.md`):**
- Append a new `## Phase 4` section (or "Beyond Phase 3" — match the existing style) with one row for trip-prep to-dos:

```
| Feature | Status | Spec | Plan |
|---|---|---|---|
| Trip-prep to-dos (v1) | ✓ shipped | docs/superpowers/specs/2026-06-14-trip-prep-todos-design.md | docs/superpowers/plans/2026-06-14-trip-prep-todos.md |
```

Also list "v2: AI-suggested prep tasks" as a parked candidate beneath it (not shipped).

**Final smoke check (manual, after this task lands):**
1. Run `python3 -m pytest tests/ -q` — expect roughly 709 passing (659 + ~50 new).
2. Boot the dev server, sign in, visit `/`, `/prep`, and `/trips/<one of your trips>/prep`. Confirm each surface renders the empty state cleanly with no items, then add a plain-text to-do and confirm it appears. Skip the URL paste path if you don't want to hit the network — the route handles it but the smoke doesn't require a live page.

**Test list (additions):**
- `test_base_template_includes_prep_js_when_authenticated`
- `test_base_template_does_not_include_prep_js_when_anonymous`

**Commit:** `chore: prep.js paste hint + Phase 4 roadmap entry`

---

## Notes for the executing engineer / subagent

- **DB safety:** the test suite is bound to `:memory:` SQLite via the `tests/conftest.py` tripwire. Never `db.create_all()` or `db.drop_all()` against `vacation.db`. See "Data safety rules" in `CLAUDE.md`.
- **Python 3.9:** use `Optional[X]`, not `X | None`.
- **No print, use the module logger:** `logger = logging.getLogger(__name__)` at the top of every new file. `print()` is forbidden.
- **Type hints required** on every new function — parameters and return type.
- **Frontend verification mandate** (from `~/.claude/CLAUDE.md`): Task 14 introduces user-visible UI on the dashboard. Before marking that task complete, follow the "Frontend verification" rule — start the dev server, load `/`, confirm zero browser console errors, confirm the panel renders with the items you created via tests / sqlite shell. If `webapp-testing` is unavailable, at minimum `node --check static/js/prep.js`.
- **Commit cadence:** one commit per task (or one per logical sub-step if a task is exceptionally large — none of these are). Conventional Commits style (`feat:`, `fix:`, `chore:`, `docs:`).

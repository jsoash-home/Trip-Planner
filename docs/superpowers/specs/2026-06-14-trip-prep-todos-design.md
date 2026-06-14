# Trip-Prep To-Dos — Design Spec

> **Status:** Draft, awaiting review. Captures decisions made during
> the 2026-06-14 brainstorm. First feature in a new "before you go"
> thread — sits alongside packing / itinerary / budget on each trip
> and adds a user-level cross-trip surface for travel gear.

## Goal

Let a user track things they need to do, buy, or decide **before** a
trip starts — things that don't fit the packing list (those are items
you already own and put in a bag) and don't fit the itinerary (those
are things that happen *during* the trip).

Examples from the brainstorm:

- "Buy travel backpacks (me + kids)" — cross-trip gear, surfaces on
  the upcoming Svalbard trip but lives at the user level.
- "Get a new camera lens" — cross-trip gear, no specific trip.
- "Buy waterproof shoes" — cross-trip gear, needed-by-Svalbard.
- "Finish choosing Svalbard daytrips" — per-trip research, only
  matters for that one trip.

The feature spans **three surfaces** powered by **one new model**
(`TripPrepItem`) plus a small link table (`TripPrepLink`) for the
cross-trip → per-trip relationship.

## Background and motivation

The packing list answers "what goes in the bag?" — but says nothing
about the chain of *prep* that precedes the bag (research, decisions,
purchases, admin like passport renewal). The itinerary answers "what
happens during the trip?" — but says nothing about pre-trip
preparation either. There is no surface today for the messy in-between.

The user explicitly asked for a creative, modern take. v1 keeps the
data model simple but ships three concrete pieces of magic:

1. **Paste-to-create** — drop a URL into a single input, the app
   scrapes the page title and OpenGraph image so the to-do shows up
   pre-filled with a thumbnail. No LLM, just `requests` +
   `beautifulsoup4`.
2. **Smart "needs by" deadlines** — to-dos linked to a trip can carry
   a relative offset ("3 weeks before departure") instead of a hard
   date. The dashboard panel and `/prep` page rank by urgency derived
   from that offset and today.
3. **Done → packing list loop** — checking off a `gear` or `buy`
   to-do that's linked to exactly one trip prompts: "Add it to the
   packing list?" One click closes the loop between buying gear and
   tracking that it goes in the bag.

A v2 hook is reserved for **AI-suggested prep tasks per trip**
(destination + dates + booking types → Claude generates 5–10 candidate
to-dos). v1 does not add the `anthropic` SDK or any new env var —
v2 picks that up later.

## Scope

**In scope (v1):**

- One new SQLAlchemy model `TripPrepItem`.
- One new SQLAlchemy model `TripPrepLink` (cross-trip ↔ trip links).
- One new `src/url_metadata.py` module: pure helper to parse OG/title
  tags out of HTML, plus an impure `fetch_url_metadata(url)` that
  combines `requests.get` + the parse helper with timeout + silent
  failure.
- One new `src/prep_helpers.py` module: pure helpers for due-date
  math, urgency bucketing, sort keys, form parsing, and grouping.
- Seven new Flask routes:
  - `GET /prep` — full cross-trip list.
  - `POST /prep` — create a new to-do (also handles paste-to-create).
  - `POST /prep/<id>/toggle` — toggle done state (and fire the
    done→packing prompt when applicable).
  - `POST /prep/<id>/edit`, `POST /prep/<id>/delete`.
  - `POST /prep/<id>/packing-decision` — accept or dismiss the
    done→packing prompt; either action sets
    `packing_prompt_dismissed_at`.
  - `GET /trips/<id>/prep` — per-trip tab.
- A new dashboard panel (`templates/_prep_panel.html`) included in
  `templates/dashboard.html` below the trip cards.
- One new dependency: `beautifulsoup4>=4.12`.
- Idempotent migration helper `_ensure_prep_tables()` called at app
  boot, matching the `weather_cache` / `home_currency` pattern.
- ~50 new tests (unit + route integration).

**Out of scope (v1):**

- AI suggestions (deferred to v2 — design hook described below).
- Screenshot import (held pending v2 LLM pattern).
- Multi-status (only `done` / not-done in v1; no `in_progress`).
- Recurring to-dos ("renew TSA PreCheck every 5 years").
- Tags beyond the predefined categories.
- Reordering across categories.
- Email/Slack inbox.
- Push or email notification reminders.

## Data model

### `TripPrepItem`

One row per to-do. `trip_id` distinguishes per-trip from cross-trip;
the link table connects cross-trip items to one or more trips.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | int | PK | |
| `owner_id` | int | FK → `user.id`, NOT NULL, INDEXED | who created it. Cross-trip items are private to this user. |
| `trip_id` | int | FK → `trip.id`, NULLABLE, INDEXED | NULL = cross-trip; set = per-trip. |
| `title` | str(200) | NOT NULL | e.g. "Buy travel backpacks (me + kids)" |
| `notes` | text | NULLABLE | markdown rendered same as itinerary notes |
| `category` | str(20) | NOT NULL, default `other` | one of `gear`, `research`, `buy`, `book`, `admin`, `other` |
| `link_url` | str(800) | NULLABLE | source URL when created via paste-to-create |
| `link_image_url` | str(800) | NULLABLE | OG image scraped from the URL |
| `done` | bool | NOT NULL, default `False` | |
| `done_at` | datetime | NULLABLE | set when `done` flips True, cleared when it flips back to False; powers the packing prompt and "Done" section sorting |
| `due_offset_days` | int | NULLABLE | days before trip start; only meaningful for per-trip items (use the link's offset for cross-trip items) |
| `packing_prompt_dismissed_at` | datetime | NULLABLE | set when user accepts or dismisses the done→packing prompt for this item — prompt only fires once |
| `created_at` | datetime | NOT NULL, default now | |
| `sort_order` | int | NOT NULL, default `0` | manual reorder within a category |

### `TripPrepLink`

Cross-trip items can link to N trips. Per-link offset means "buy
these backpacks 21 days before Svalbard, 14 days before Italy."

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | int | PK | |
| `trip_prep_item_id` | int | FK → `trip_prep_item.id`, NOT NULL, INDEXED | |
| `trip_id` | int | FK → `trip.id`, NOT NULL, INDEXED | |
| `due_offset_days` | int | NULLABLE | days before this specific trip's start |
| `created_at` | datetime | NOT NULL, default now | |

Unique constraint on `(trip_prep_item_id, trip_id)` — no duplicate
links.

**Invariant:** a `TripPrepLink` row only exists for items where
`TripPrepItem.trip_id IS NULL` (i.e. cross-trip items). Per-trip
items use their own `trip_id` + `due_offset_days` directly and
never appear in this table. The route handlers and form parsers
enforce this; no DB-level CHECK constraint because SQLite's
support is uneven.

### Sharing rules

- **Per-trip items** (`trip_id` set on `TripPrepItem`): inherit the
  trip's sharing model. Collaborators with `editor` role can CRUD;
  `viewer` can read. The owner of the trip and the owner of the item
  may differ (an editor can create a per-trip to-do on a shared
  trip — `owner_id` is who created it).
- **Cross-trip items** (`trip_id` NULL): always private to
  `owner_id`. Surface on the owner's per-trip prep tab through the
  link table even when the trip is shared, but invisible to
  collaborators on that same trip.

The existing `require_trip_access` guard handles per-trip access.
A new tiny guard `require_prep_item_ownership(item_id)` covers
cross-trip CRUD.

## Modules

### `src/url_metadata.py`

Pure where it can be, with a thin impure wrapper.

```python
def looks_like_url(text: str) -> bool: ...
def extract_metadata_from_html(html: str, fallback_url: str) -> dict:
    """Return {'title': str, 'image_url': Optional[str], 'source_url': str}.
    Prefers OG tags, falls back to <title>, finally falls back to URL."""

def fetch_url_metadata(url: str, timeout: float = 5.0) -> dict:
    """Impure: GET the URL, run extract_metadata_from_html.
    Silent failure: returns {'title': url, 'image_url': None,
    'source_url': url} on any exception (logged at WARNING)."""
```

### `src/prep_helpers.py`

All pure.

```python
PREP_CATEGORIES = (
    ("gear",     "Gear",     "🎒"),
    ("buy",      "Buy",      "🛒"),
    ("research", "Research", "🔍"),
    ("book",     "Book",     "📅"),
    ("admin",    "Admin",    "📋"),
    ("other",    "Other",    "📦"),
)

def due_date(trip_start: date, offset_days: Optional[int]) -> Optional[date]: ...
def urgency_bucket(today: date, due: Optional[date]) -> str:
    """One of: 'overdue', 'urgent' (≤7d), 'soon' (≤30d), 'later', 'none'."""
def sort_key(item, today: date) -> Tuple: ...
def parse_prep_form(form: Mapping[str, str]) -> dict: ...
def group_items_by_category(items) -> Dict[str, list]: ...
def items_for_dashboard_panel(items, today: date, limit: int = 5) -> list: ...
```

## The three v1 surfaces

### Surface 1 — Dashboard panel

A new `templates/_prep_panel.html` partial, included on
`templates/dashboard.html` below the trip-cards section.

Renders:

- The paste-or-type input + Add button (POSTs to `/prep`).
- The top 5 items ranked by `prep_helpers.sort_key` — mix of
  cross-trip and per-trip, urgency badges visible.
- "See all → /prep" link.

Hidden when the user has zero prep items (no nudge — the empty state
is "you don't need this yet").

### Surface 2 — `/prep`

Full cross-trip list at user level. Items grouped by category
into a responsive grid (two columns on desktop, single column on
mobile). Open items rendered first, a "Done" group at the bottom
sorted by `done_at` descending. Same paste-to-create input
prominent at the top. Per-trip-only items don't appear here — they
live on the per-trip tab.

### Surface 3 — `/trips/<id>/prep`

New tab on each trip overview (added to the existing nav: Overview /
Itinerary / Bookings / **Prep** / Packing / Budget / Map).

Two sections:

- **Linked from your gear** — cross-trip items that link to this
  trip via `TripPrepLink`. Owner sees them; collaborators don't.
- **Trip-specific** — items with `trip_id = <this trip>`. Visible
  per the trip's sharing rules.

Inline create input at the top defaults to creating a per-trip item
(not cross-trip).

## The three v1 magic flows

### A — Paste-to-create

User pastes a URL into the input on any of the three surfaces and
hits Add. The route handler:

1. Calls `url_metadata.looks_like_url(input)`. If True, calls
   `url_metadata.fetch_url_metadata(input)` to get title + image.
2. If the input is plain text, uses it as the title directly.
3. Creates the `TripPrepItem` row with `title`, optional `link_url`,
   optional `link_image_url`.
4. Redirects back to the surface the user was on.

Silent failure: a URL that times out or fails to parse still creates
the item — just with the URL itself as the title. Logger.warning on
any exception.

**Caveat to flag in the spec:** Amazon and a few other large
retailers block unauthenticated scrapers. Those URLs will save with
title="Amazon.com" (the literal page title their bot-block page
returns) instead of the product name. v2 could add a real product-
API fallback — out of scope for v1.

### D — Smart "needs by" deadlines

Create/edit form has an optional "When does this need to be done?"
field with quick options:

- 1 week before
- 2 weeks before
- 1 month before
- 6 weeks before
- 2 months before
- Custom (days)
- None

For per-trip items the offset lives on `TripPrepItem.due_offset_days`.
For cross-trip items linked to a trip, the offset lives on the
`TripPrepLink.due_offset_days` for that link — so the same
cross-trip item can be 21 days before Svalbard and 14 days before
the next trip independently.

Urgency rendering on the dashboard panel + `/prep` + per-trip tab:

| Bucket | Trigger | Badge |
|---|---|---|
| `overdue` | `due < today` | red |
| `urgent` | `due - today ≤ 7 days` | amber |
| `soon` | `due - today ≤ 30 days` | blue |
| `later` | further out | neutral text |
| `none` | no offset set | sorted last |

### E — Done → packing list loop

When the user POSTs `/prep/<id>/toggle` and the new state is `done`,
the route checks:

1. Item category is `gear` or `buy`.
2. Item is linked to exactly one trip (either via `trip_id` or via
   exactly one `TripPrepLink`).
3. `packing_prompt_dismissed_at` is None.

If all three hold, the response sets a flash banner: "Add
'<title>' to **<trip name>** packing list? [Yes] [No, just mark
done]." Both buttons POST to `/prep/<id>/packing-decision` with a
`?action=add` or `?action=dismiss` param. Either action sets
`packing_prompt_dismissed_at = now()` so the prompt never fires
twice for the same item.

The `Yes` path creates a `PackingItem(trip_id=<linked trip>,
name=<prep title>, category='other', packed=False)` and redirects
back to the surface the user came from.

## Testing strategy

Matches the project's existing pattern. Estimate ~50 new tests.

### `tests/test_url_metadata.py`

- `looks_like_url`: http/https, ftp, mailto, plain text, edge cases
  (text with embedded URL, URL with surrounding whitespace).
- `extract_metadata_from_html`: OG-tag preferred, falls back to
  `<title>`, falls back to URL. Tests against fixture HTML.
- `fetch_url_metadata`: mocked `requests.get` for success, timeout,
  HTTP 4xx/5xx, non-HTML content type, malformed HTML. Verify
  WARNING log on every failure path.

### `tests/test_prep_helpers.py`

- `due_date`: with/without offset, edge cases.
- `urgency_bucket`: each bucket boundary.
- `sort_key`: urgency before created_at, none-offset items last.
- `parse_prep_form`: valid input, missing required fields, invalid
  category (defaults to `other`), invalid offset (silently
  dropped).
- `group_items_by_category`: empty list, all categories, unknown
  category fallback.
- `items_for_dashboard_panel`: limit enforced, urgent items
  preferred.

### `tests/test_routes.py` (extends existing file)

- Owner-only access to `/prep`, `/prep/<id>/*` (cross-trip items).
- Per-trip access guard on `/trips/<id>/prep` — owner, editor
  collaborator, viewer collaborator, non-member each get the
  expected status code.
- Paste-to-create with a mocked `fetch_url_metadata` — successful
  enrich path, silent-failure path (item still created).
- Toggle done flips the field and fires the packing prompt only
  when conditions hold; second toggle does NOT re-fire it.
- Done → packing decision `add` creates a `PackingItem`; `dismiss`
  does not, and either action sets the dismissed timestamp.
- Dashboard panel renders top 5, hidden when zero items.
- `TripPrepLink` CRUD: cross-trip item linked to a shared trip —
  collaborator on that trip does NOT see it on their per-trip prep
  tab.

## Migration

Same idempotent pattern as `_ensure_weather_columns` and
`_ensure_home_currency_column`:

```python
def _ensure_prep_tables() -> None:
    """Create trip_prep_item and trip_prep_link tables if missing.
    Safe to call on every app boot."""
    inspector = inspect(db.engine)
    if "trip_prep_item" not in inspector.get_table_names():
        TripPrepItem.__table__.create(db.engine)
    if "trip_prep_link" not in inspector.get_table_names():
        TripPrepLink.__table__.create(db.engine)
```

Called once at app startup after `db.create_all()`, on both SQLite
and Postgres paths.

## v2 hook — AI suggestions

Reserved but not implemented in v1. The spec earmarks one
integration point:

- A future `POST /trips/<id>/prep/suggest` route.
- Takes the trip's destination (`destination_iana`, `name`,
  `notes`), `start_date`, `end_date`, and existing prep titles.
- Asks Claude (via the `anthropic` SDK, gated on
  `ANTHROPIC_API_KEY` env var) for 5–10 candidate to-dos.
- Returns JSON for the user to accept or dismiss; accepted items
  create `TripPrepItem` rows with `category='research'` or
  `'gear'` depending on the suggestion.

v1 leaves a comment in `prep_helpers.py` marking the planned hook
point. v1 does NOT add the `anthropic` dependency or the env var.

## Open questions

None. All design decisions resolved during the brainstorm:

- Scope: hybrid per-trip + cross-trip with linking (option C).
- Magic features: A + D + E for v1; B held for v2; C held further.
- Sharing: per-trip items follow trip sharing; cross-trip items
  always private to owner.
- IA: dedicated surfaces (Approach 1 — three new screens).

## File map

| File | Status | Purpose |
|---|---|---|
| `models.py` | modified | `TripPrepItem` + `TripPrepLink` models |
| `src/url_metadata.py` | new | OG/title scraper helpers |
| `src/prep_helpers.py` | new | due-date, urgency, sort, parse, group |
| `tests/test_url_metadata.py` | new | unit tests |
| `tests/test_prep_helpers.py` | new | unit tests |
| `tests/test_routes.py` | modified | route integration tests |
| `app.py` | modified | 6 new routes + `_ensure_prep_tables()` |
| `templates/dashboard.html` | modified | include `_prep_panel.html` |
| `templates/_prep_panel.html` | new | dashboard panel partial |
| `templates/prep.html` | new | `/prep` user-level page |
| `templates/trip_prep.html` | new | `/trips/<id>/prep` tab |
| `templates/trip_overview.html` | modified | add Prep tab to nav |
| `requirements.txt` | modified | add `beautifulsoup4>=4.12` |
